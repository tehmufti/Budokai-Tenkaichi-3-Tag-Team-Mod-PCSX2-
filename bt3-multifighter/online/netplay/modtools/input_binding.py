"""Capture mapped controller/keyboard input without attaching to PCSX2.

The saved binding is a logical PS2 button, so each player keeps their own
emulator controller mapping. No INI, gamepad, emulator or memory is written.

SDL2 comes from the bundled SDL2.dll on Windows and from the system's
libSDL2-2.0.so.0 (SDL2 or sdl2-compat) elsewhere. This module serves the rebind
dialog of Mod settings. Players' controllers during play are read by the
controller hub (controller_hub.py), which logs every controller it sees.
"""
import configparser
from localization import tr
import ctypes
import os
import runtime_profile
from pathlib import Path

BUTTONS = ('select','l3','r3','start','up','right','down','left',
           'l2','r2','l1','r1','triangle','circle','cross','square')
MASKS = {name:1<<i for i,name in enumerate(BUTTONS)}
LABELS = {name:(name.upper() if name in ('l1','l2','l3','r1','r2','r3') else name.title()) for name in BUTTONS}
ROOT = Path(__file__).resolve().parents[1]


def label(name,settings=None):
    """Settings-screen name of a PS2 button, in the chosen language.

    LABELS itself stays English: guest menu hints and lock-on status text use it.
    """
    return tr(LABELS[name],settings)
INI = runtime_profile.CONFIG
SDL_BUTTONS = ('FaceSouth','FaceEast','FaceWest','FaceNorth','Back','Guide','Start',
               'LeftStick','RightStick','LeftShoulder','RightShoulder','DPadUp',
               'DPadDown','DPadLeft','DPadRight','Misc1','Paddle1','Paddle2','Paddle3','Paddle4','Touchpad')
SDL_AXES = ('LeftX','LeftY','RightX','RightY','LeftTrigger','RightTrigger')


def token(value):return value.strip().casefold()


def mappings(path=INI):
    """Input source -> logical buttons, preserving ambiguity rather than guessing."""
    parser=configparser.ConfigParser(interpolation=None,strict=False)
    with Path(path).open(encoding='utf-8-sig') as source:parser.read_file(source)
    result={}
    for section in ('Pad1','Pad2'):
        if not parser.has_section(section):continue
        for name in BUTTONS:
            for binding in parser.get(section,name,fallback='').splitlines():
                if '&' in binding:continue  # A chord is not a single captured input.
                binding=token(binding)
                if binding:result.setdefault(binding,set()).add(name)
    return result


def resolve(sources,bindings):
    matched=set()
    for source in sources:matched.update(bindings.get(token(source),()))
    if len(matched)>1:raise ValueError('That input maps to several PS2 buttons. Choose one below or revise the PCSX2 controller mapping.')
    return next(iter(matched),None)


WINDOWS = os.name == 'nt'
SDL_SONAME = 'libSDL2-2.0.so.0'  # SDL2's runtime name on every distribution (SDL2 or sdl2-compat)


class SDLUnavailable(OSError):
    """SDL2 could not be loaded: controllers 3 and 4 cannot be read (players 1 and 2 are unaffected)."""


def load_sdl(dll=None):
    """SDL2 for pad capture: the bundled SDL2.dll on Windows, the system library elsewhere (never the DLL)."""
    if dll or WINDOWS:
        return ctypes.CDLL(str(dll or (ROOT/'tools/vendor/SDL2.dll' if (ROOT/'tools/vendor/SDL2.dll').is_file() else ROOT/'runtime128/SDL2.dll')))
    errors = []
    try:
        return ctypes.CDLL(SDL_SONAME)
    except OSError as error:
        errors.append(str(error))
    from ctypes.util import find_library
    found = find_library('SDL2-2.0')
    if found:
        try:
            return ctypes.CDLL(found)
        except OSError as error:
            errors.append(str(error))
    raise SDLUnavailable(f'SDL2 ({SDL_SONAME}) is not installed, so the mod cannot read controllers 3 and 4. '
                         "Install your distribution's SDL2 package (Debian/Ubuntu: libsdl2-2.0-0; Fedora: SDL2 or "
                         'sdl2-compat; Arch: sdl2 or sdl2-compat). Players 1 and 2 are not affected. '
                         f'({"; ".join(errors)})')


def sdl_status():
    """One line for dependency checks: can controller 3/4 capture load SDL2 here?"""
    try:
        load_sdl()
    except OSError as error:
        return f'unavailable. {error}'
    return 'SDL2 available'


def grab_dialog(dialog, attempts=40, delay=25):
    """grab_set(), retried while X11 has not mapped a new dialog yet ("window not viewable").

    Bounded (about a second), unlike wait_visibility(), which can wait forever. Without the
    grab the dialog still works; it is only not modal. Windows grabs on the first attempt.
    """
    import tkinter
    for attempt in range(attempts):
        try:
            dialog.grab_set()
            return True
        except tkinter.TclError:
            if attempt+1 == attempts:
                return False
            dialog.update_idletasks(); dialog.after(delay); dialog.update()


def keyboard_sources(keysym):
    aliases={'return':'Return','kp_enter':'Enter','escape':'Escape','space':'Space',
             'backspace':'Backspace','prior':'PageUp','next':'PageDown',
             'shift_l':'Shift','shift_r':'Shift','control_l':'Control','control_r':'Control',
             'alt_l':'Alt','alt_r':'Alt'}
    key=aliases.get(keysym.casefold(),keysym)
    return ('Keyboard/'+key,)


class ControllerCapture:
    """Read SDL2's standardized pad controls; devices are released on close."""
    def __init__(self,dll=None,*,background=False):
        self.dll=load_sdl(dll)
        self.controllers=[];self.initialized=False;self.background=background;self._instances={}
        signatures={
            'SDL_SetHint':([ctypes.c_char_p,ctypes.c_char_p],ctypes.c_int),
            'SDL_InitSubSystem':([ctypes.c_uint32],ctypes.c_int),
            'SDL_QuitSubSystem':([ctypes.c_uint32],None),
            'SDL_NumJoysticks':([],ctypes.c_int),
            'SDL_IsGameController':([ctypes.c_int],ctypes.c_int),
            'SDL_JoystickGetDeviceInstanceID':([ctypes.c_int],ctypes.c_int32),
            'SDL_GameControllerOpen':([ctypes.c_int],ctypes.c_void_p),
            'SDL_GameControllerClose':([ctypes.c_void_p],None),
            'SDL_GameControllerGetAttached':([ctypes.c_void_p],ctypes.c_int),
            'SDL_GameControllerGetPlayerIndex':([ctypes.c_void_p],ctypes.c_int),
            'SDL_GameControllerUpdate':([],None),
            'SDL_GameControllerGetButton':([ctypes.c_void_p,ctypes.c_int],ctypes.c_uint8),
            'SDL_GameControllerGetAxis':([ctypes.c_void_p,ctypes.c_int],ctypes.c_int16)}
        for name,(args,result) in signatures.items():
            fn=getattr(self.dll,name);fn.argtypes=args;fn.restype=result
        self.dll.SDL_SetHint(b'SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS',b'1')
        if background:
            # Windows.Gaming.Input can enumerate Xbox pads yet return no input
            # while PCSX2 owns the foreground. Use SDL's polling/XInput path in
            # this helper process; leave PCSX2 and the rebind dialog untouched.
            self.dll.SDL_SetHint(b'SDL_JOYSTICK_WGI',b'0')
            self.dll.SDL_SetHint(b'SDL_JOYSTICK_RAWINPUT',b'0')
        if self.dll.SDL_InitSubSystem(0x2000)!=0:raise OSError('SDL controller input could not initialize')
        self.initialized=True
        try:
            self.previous=self.pressed()
        except Exception:self.close();raise

    def update(self):
        """Poll and reopen hotplugged pads without renumbering attached seats."""
        self.dll.SDL_GameControllerUpdate()
        devices=[(index,self.dll.SDL_JoystickGetDeviceInstanceID(index))
                 for index in range(max(0,self.dll.SDL_NumJoysticks()))]
        present={instance for _,instance in devices if instance>=0}
        for instance,(slot,pad) in list(self._instances.items()):
            if instance not in present or not self.dll.SDL_GameControllerGetAttached(pad):
                self.dll.SDL_GameControllerClose(pad);del self._instances[instance]
        used={slot for slot,_ in self._instances.values()}
        for index,instance in devices:
            if instance<0 or instance in self._instances or not self.dll.SDL_IsGameController(index):continue
            pad=self.dll.SDL_GameControllerOpen(index)
            if not pad:continue
            # The background Xbox backend exposes its stable XInput user index.
            # SDL device indices compact after unplugging another controller.
            slot=self.dll.SDL_GameControllerGetPlayerIndex(pad) if self.background else index
            if slot<0:slot=index
            if slot in used:slot=next(i for i in range(len(used)+1) if i not in used)
            used.add(slot);self._instances[instance]=(slot,pad)
        self.controllers=sorted(self._instances.values())

    def pressed(self):
        self.update();result=set()
        for index,pad in self.controllers:
            prefix=f'SDL-{index}/'
            for button,name in enumerate(SDL_BUTTONS):
                if self.dll.SDL_GameControllerGetButton(pad,button):result.add(prefix+name)
            for axis,name in enumerate(SDL_AXES):
                value=self.dll.SDL_GameControllerGetAxis(pad,axis)
                if value>20000:result.add(prefix+'+'+name)
                if axis<4 and value<-20000:result.add(prefix+'-'+name)
        return result

    def poll(self):
        current=self.pressed();new=current-self.previous;self.previous=current
        return new

    def close(self):
        for _,pad in self.controllers:self.dll.SDL_GameControllerClose(pad)
        self.controllers=[];self._instances={}
        if self.initialized:self.dll.SDL_QuitSubSystem(0x2000);self.initialized=False


def capture_dialog(parent,current,*,ini=INI,title=None):
    """Modal capture; returns the selected logical button or None on cancel.

    `title` names the setting being rebound.
    """
    import tkinter as tk
    from tkinter import ttk
    dialog=tk.Toplevel(parent);dialog.title(title or tr('Rebind…'));dialog.transient(parent)
    dialog.resizable(False,False);panel=ttk.Frame(dialog,padding=20);panel.grid()
    result=[None];capture=[None];after=[None]
    status=tk.StringVar(value=tr('Press a controller button or a key mapped in PCSX2.'))
    ttk.Label(panel,textvariable=status,wraplength=400).grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,14))
    chosen=tk.StringVar(value=label(current))
    ttk.Label(panel,text=tr('Or choose a PS2 button:')).grid(row=1,column=0,sticky='w')
    ttk.Combobox(panel,textvariable=chosen,values=[label(n) for n in BUTTONS],state='readonly',width=14).grid(row=1,column=1)
    ttk.Label(panel,text=tr('The binding uses each player’s PCSX2 mapping. Native actions on this button still happen.'),wraplength=400).grid(row=2,column=0,columnspan=2,sticky='w',pady=12)
    try:bindings=mappings(ini)
    except (OSError,configparser.Error):bindings={};status.set(tr('Controller mappings could not be read. Choose a PS2 button below.'))

    def close(value=None):
        result[0]=value
        if after[0] is not None:dialog.after_cancel(after[0]);after[0]=None
        if capture[0] is not None:capture[0].close();capture[0]=None
        dialog.destroy()

    def accept_sources(sources):
        if not sources:return
        try:name=resolve(sources,bindings)
        except ValueError as error:status.set(str(error));return
        if name:close(name)
        else:status.set(tr('That input has no single PS2-button mapping. Choose a button below or assign it in PCSX2 first.'))

    def poll():
        after[0]=None
        try:accept_sources(capture[0].poll())
        except (OSError,ValueError) as error:status.set(str(error))
        if capture[0] is not None:after[0]=dialog.after(25,poll)

    def key(event):
        if event.keysym=='Escape':close();return 'break'
        accept_sources(keyboard_sources(event.keysym));return 'break'

    ttk.Button(panel,text=tr('Cancel'),command=close).grid(row=3,column=0,sticky='e')
    ttk.Button(panel,text=tr('Use selected button'),command=lambda:close(next(n for n in BUTTONS if label(n)==chosen.get()))).grid(row=3,column=1,padx=(8,0))
    dialog.protocol('WM_DELETE_WINDOW',close);dialog.bind('<KeyPress>',key)
    try:capture[0]=ControllerCapture();after[0]=dialog.after(25,poll)
    except (OSError,AttributeError):status.set(tr('Gamepad capture is unavailable. Press a mapped keyboard key or choose a PS2 button below.'))
    grab_dialog(dialog);dialog.focus_set();parent.wait_window(dialog)
    return result[0]
