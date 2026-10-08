"""The controller hub: one SDL owner thread for the whole Play session, and the only writer of the input mailboxes.

beta.36 gave every input object its own SDL (Player Setup's capture, the assignment, selector and battle bridges),
each in a short-lived thread. On Windows a PlayStation-type pad read through HIDAPI vanished from a still-running
reader when another SDL thread ended, and pads were identified by per-capture slot numbers that changed with
connection order. Here SDL is loaded, initialised, polled and closed on one thread ('TTM controller hub') only, pads
are identified by identity keys (serial, device path, XInput slot), and every consumer reads snapshots.

The guest side is unchanged apart from the PASS mask of controller_assignment: the three mailboxes keep their bytes
and the hub publishes to them through sinks (AssignmentSink for P1/P2, SelectorSink and BattleSink for P3/P4), each a
token-authenticated controller_mailbox.Mailbox attached by the watcher and handed over with add_sink/remove_sink.

The seat rules are controller_checkin (pure); the hub feeds them press events, press matching against PCSX2's own
ports (read-only, through the assignment mailbox's process memory) and connection changes.
"""
import collections
import contextlib
import ctypes
import os
import re
import struct
import threading
import time
from pathlib import Path

import controller_checkin as checkin
import controller_mailbox as transport
import input_binding
import quad_controller as quad
import mode_menu

ROOT = Path(__file__).resolve().parents[1]
SDL_INIT_GAMECONTROLLER = 0x2000
FAST, SLOW = 0.008, 0.050          # poll periods: sinks or Player Setup / device table and hotplug only
RING = 512
LIGHT_KEYS = checkin.PSEUDO        # PCSX2 ports as light sources ('pcsx2:1', 'pcsx2:2')
ANY = 0x10000000                   # a press on a controller without a gamepad layout (no PS2 button known)
TRIGGER = 10000                    # an analog trigger above this counts as L2/R2 (quad_controller.encode_pad)
# Press matching against PCSX2's ports (FINAL spec 3.7).
MATCH_BEFORE, MATCH_AFTER, MATCH_UNIQUE, PSEUDO_AFTER = 0.060, 0.120, 0.060, 0.120
CONFIRMED = 3
LATCH = 0.100                      # a new press stays published until the guest took it, at most this long
# Self-heal: a claimed non-XInput pad missing this long while Windows still lists its HID path.
HEAL_AFTER, HEAL_GAP, HEAL_LIMIT = 3.0, 30.0, 3
XINPUT_PATH = re.compile(r'\AXInput#(\d+)\Z', re.I)
TYPES = {0: 'unknown', 1: 'Xbox 360', 2: 'Xbox One', 3: 'PS3', 4: 'PS4', 5: 'Switch Pro', 6: 'virtual', 7: 'PS5',
         8: 'Luna', 9: 'Stadia', 10: 'Shield', 11: 'Joy-Con (L)', 12: 'Joy-Con (R)', 13: 'Joy-Con pair'}
# SDL_GameControllerButton indices of quad_controller.BUTTON_MAP (input_binding.SDL_BUTTONS order).
MAPPED_BUTTONS = tuple((input_binding.SDL_BUTTONS.index(name), name) for name in quad.BUTTON_MAP)

# Play-window lines (English templates; Spanish in localization.ES). The watcher prefixes the code.
SAY = {
    'unavailable': ("Players 3 and 4 cannot join: the mod's controller reader (SDL2) did not start ({detail}). Players 1 "
                    'and 2 keep their PCSX2 controllers. On Linux install libsdl2-2.0-0 (Debian/Ubuntu), SDL2 or '
                    'sdl2-compat.'),
    'unmapped': ('{name} is connected but has no gamepad layout (GUID {guid}), so it cannot join as player 3 or 4. It '
                 'can still play as player 1 or 2 through PCSX2 (PCSX2 settings > Controllers), or in its XInput/X mode.'),
    'lost': ("Player {n}'s controller ({name}) disconnected; that fighter stands still. Reconnect it, or hold START for 2 "
             'seconds on a free controller to take over.'),
    'twin': ('{name} appears twice (DS4Windows, Steam Input or another remapper): the mod uses one copy and ignores the '
             'other. If a player moves twice, hide the copy (HidHide) or turn the remapper off.'),
    'double': ('{name} moves player {n} and also player {k} through PCSX2 controller port {k}. Remove it from that port in '
               'PCSX2 settings > Controllers, or let it join as player {k}.'),
    'back': 'Player {n} is back on {name}.',
}
CODES = {'unavailable': 'TTM-CTRL-20', 'unmapped': 'TTM-CTRL-21', 'lost': 'TTM-CTRL-22', 'twin': 'TTM-CTRL-23',
         'double': 'TTM-CTRL-24'}


def database_paths(runtime=None, data=None):
    """(PCSX2's game_controller_db.txt, or the vendored copy; the user's database in PCSX2's data folder or None)."""
    import runtime_profile
    runtime = Path(runtime) if runtime is not None else runtime_profile.DIRECTORY
    data = Path(data) if data is not None else runtime_profile.DATA
    shipped = runtime/'resources'/'game_controller_db.txt'
    db = shipped if shipped.is_file() else Path(__file__).resolve().parent/'vendor'/'game_controller_db.txt'
    user = data/'game_controller_db.txt'
    return (db if db.is_file() else None), (user if user.is_file() else None)


def identity_key(row, taken=()):
    """'serial:<s>' for a serial no other connected controller has, else 'path:<device path>' when it is not an XInput
    path, else 'xinput:<n>:<vid>:<pid>'; without Serial/Path (old SDL2) 'guid:<hex>#<order>'. A collision with a key
    in `taken` appends '#<instance>'."""
    serial, path = row.get('serial') or '', row.get('path') or ''
    xinput = XINPUT_PATH.match(path)
    if serial and row.get('serial_unique', True):key = f'serial:{serial}'
    elif path and not xinput:key = f'path:{path}'
    elif xinput or row.get('xinput') is not None:
        slot = int(xinput.group(1)) if xinput else row.get('xinput')
        key = f"xinput:{slot}:{row.get('vid', 0):04x}:{row.get('pid', 0):04x}"
    else:key = f"guid:{row.get('guid') or 'unknown'}#{row.get('order', 0)}"
    if key in taken:key += f"#{row.get('instance', 0)}"
    return key


def native_state(block):
    """A PCSX2 pad record's +0x104..+0x11B: (connected, PS2 button word, (RX, RY, LX, LY)).

    +0x104 status 1 = connected, +0x108 state 2 = reading; +0x114 raw: buttons active-low (low byte first), sticks."""
    status, state = struct.unpack_from('<2I', block, 0)
    buttons = (block[0x10] | block[0x11] << 8) ^ 0xFFFF
    return (status == 1 and state == 2), buttons, tuple(block[0x12:0x16])


def _later(a, b):
    """Sequence a is at or after b (32-bit wrap)."""
    return ((a-b) & 0xFFFFFFFF) < 0x80000000


class GUID(ctypes.Structure):
    _fields_ = [('data', ctypes.c_uint8*16)]


class Version(ctypes.Structure):
    _fields_ = [('major', ctypes.c_uint8), ('minor', ctypes.c_uint8), ('patch', ctypes.c_uint8)]


class HidInfo(ctypes.Structure):
    pass


HidInfo._fields_ = [('path', ctypes.c_char_p), ('vendor_id', ctypes.c_ushort), ('product_id', ctypes.c_ushort),
                    ('serial_number', ctypes.c_wchar_p), ('release_number', ctypes.c_ushort),
                    ('manufacturer_string', ctypes.c_wchar_p), ('product_string', ctypes.c_wchar_p),
                    ('usage_page', ctypes.c_ushort), ('usage', ctypes.c_ushort), ('interface_number', ctypes.c_int),
                    ('interface_class', ctypes.c_int), ('interface_subclass', ctypes.c_int),
                    ('interface_protocol', ctypes.c_int), ('next', ctypes.POINTER(HidInfo))]


class Backend:
    """Every SDL2 call the hub makes. Created, used and closed on the hub thread only."""
    REQUIRED = {
        'SDL_SetHint': ([ctypes.c_char_p, ctypes.c_char_p], ctypes.c_int),
        'SDL_InitSubSystem': ([ctypes.c_uint32], ctypes.c_int),
        'SDL_QuitSubSystem': ([ctypes.c_uint32], None),
        'SDL_NumJoysticks': ([], ctypes.c_int),
        'SDL_IsGameController': ([ctypes.c_int], ctypes.c_int),
        'SDL_JoystickGetDeviceInstanceID': ([ctypes.c_int], ctypes.c_int32),
        'SDL_GameControllerOpen': ([ctypes.c_int], ctypes.c_void_p),
        'SDL_GameControllerClose': ([ctypes.c_void_p], None),
        'SDL_GameControllerGetAttached': ([ctypes.c_void_p], ctypes.c_int),
        'SDL_GameControllerGetPlayerIndex': ([ctypes.c_void_p], ctypes.c_int),
        'SDL_GameControllerUpdate': ([], None),
        'SDL_GameControllerGetButton': ([ctypes.c_void_p, ctypes.c_int], ctypes.c_uint8),
        'SDL_GameControllerGetAxis': ([ctypes.c_void_p, ctypes.c_int], ctypes.c_int16),
    }
    OPTIONAL = {
        'SDL_GetVersion': ([ctypes.POINTER(Version)], None),
        'SDL_GetError': ([], ctypes.c_char_p),
        'SDL_JoystickNameForIndex': ([ctypes.c_int], ctypes.c_char_p),
        'SDL_JoystickGetDeviceGUID': ([ctypes.c_int], GUID),
        'SDL_JoystickGetDeviceVendor': ([ctypes.c_int], ctypes.c_uint16),
        'SDL_JoystickGetDeviceProduct': ([ctypes.c_int], ctypes.c_uint16),
        'SDL_GameControllerName': ([ctypes.c_void_p], ctypes.c_char_p),
        'SDL_GameControllerGetType': ([ctypes.c_void_p], ctypes.c_int),
        'SDL_GameControllerGetSerial': ([ctypes.c_void_p], ctypes.c_char_p),     # SDL 2.0.14
        'SDL_GameControllerPath': ([ctypes.c_void_p], ctypes.c_char_p),          # SDL 2.24
        'SDL_GameControllerNumMappings': ([], ctypes.c_int),
        'SDL_GameControllerAddMappingsFromRW': ([ctypes.c_void_p, ctypes.c_int], ctypes.c_int),
        'SDL_RWFromFile': ([ctypes.c_char_p, ctypes.c_char_p], ctypes.c_void_p),
        'SDL_JoystickOpen': ([ctypes.c_int], ctypes.c_void_p),
        'SDL_JoystickClose': ([ctypes.c_void_p], None),
        'SDL_JoystickGetAttached': ([ctypes.c_void_p], ctypes.c_int),
        'SDL_JoystickNumButtons': ([ctypes.c_void_p], ctypes.c_int),
        'SDL_JoystickGetButton': ([ctypes.c_void_p, ctypes.c_int], ctypes.c_uint8),
        'SDL_JoystickGetSerial': ([ctypes.c_void_p], ctypes.c_char_p),
        'SDL_JoystickPath': ([ctypes.c_void_p], ctypes.c_char_p),                 # SDL 2.24
        'SDL_hid_enumerate': ([ctypes.c_ushort, ctypes.c_ushort], ctypes.POINTER(HidInfo)),   # SDL 2.0.18
        'SDL_hid_free_enumeration': ([ctypes.POINTER(HidInfo)], None),
    }
    HINTS = ((b'SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS', b'1'), (b'SDL_JOYSTICK_WGI', b'0'), (b'SDL_JOYSTICK_RAWINPUT', b'0'),
             (b'SDL_JOYSTICK_HIDAPI_PS4_RUMBLE', b'0'), (b'SDL_JOYSTICK_HIDAPI_PS5_RUMBLE', b'0'))

    def __init__(self, dll):
        self.dll = dll; self.fn = {}
        for table, required in ((self.REQUIRED, True), (self.OPTIONAL, False)):
            for name, (args, result) in table.items():
                try:fn = getattr(dll, name)
                except AttributeError:
                    if required:raise
                    continue
                fn.argtypes = args; fn.restype = result; self.fn[name] = fn
        self.initialized = False

    def has(self, name):return name in self.fn

    def error(self):
        if not self.has('SDL_GetError'):return 'unknown error'
        try:return (self.fn['SDL_GetError']() or b'').decode('utf-8', 'replace') or 'unknown error'
        except Exception:return 'unknown error'

    def init(self, database=None, user=None):
        """Hints, then SDL_InitSubSystem(GAMECONTROLLER), then the user's database. Paths go to SDL as UTF-8."""
        for key, value in self.HINTS:self.fn['SDL_SetHint'](key, value)
        if database is not None:
            self.fn['SDL_SetHint'](b'SDL_GAMECONTROLLERCONFIG_FILE', os.fspath(database).encode('utf-8'))
        if self.fn['SDL_InitSubSystem'](SDL_INIT_GAMECONTROLLER) != 0:
            raise OSError(f'SDL controller input could not initialize ({self.error()})')
        self.initialized = True
        added = None
        if user is not None and self.has('SDL_RWFromFile') and self.has('SDL_GameControllerAddMappingsFromRW'):
            rw = self.fn['SDL_RWFromFile'](os.fspath(user).encode('utf-8'), b'rb')
            added = self.fn['SDL_GameControllerAddMappingsFromRW'](rw, 1) if rw else -1
        version = None
        if self.has('SDL_GetVersion'):
            v = Version(); self.fn['SDL_GetVersion'](ctypes.byref(v)); version = f'{v.major}.{v.minor}.{v.patch}'
        mappings = self.fn['SDL_GameControllerNumMappings']() if self.has('SDL_GameControllerNumMappings') else None
        return dict(version=version, mappings=mappings, user_added=added)

    def restart(self):
        self.fn['SDL_QuitSubSystem'](SDL_INIT_GAMECONTROLLER)
        if self.fn['SDL_InitSubSystem'](SDL_INIT_GAMECONTROLLER) != 0:
            self.initialized = False
            raise OSError(f'SDL controller input could not initialize again ({self.error()})')

    def quit(self):
        if self.initialized:self.fn['SDL_QuitSubSystem'](SDL_INIT_GAMECONTROLLER); self.initialized = False

    def update(self):self.fn['SDL_GameControllerUpdate']()

    def instances(self):
        return [(index, self.fn['SDL_JoystickGetDeviceInstanceID'](index))
                for index in range(max(0, self.fn['SDL_NumJoysticks']()))]

    def _text(self, name, *args):
        if not self.has(name):return ''
        try:return (self.fn[name](*args) or b'').decode('utf-8', 'replace')
        except Exception:return ''

    def open(self, index, instance):
        """Open one joystick: a game controller when SDL has a layout for it, else a plain joystick (presses only)."""
        mapped = bool(self.fn['SDL_IsGameController'](index))
        row = dict(index=index, instance=instance, mapped=mapped, name=self._text('SDL_JoystickNameForIndex', index),
                   vid=self.fn['SDL_JoystickGetDeviceVendor'](index) if self.has('SDL_JoystickGetDeviceVendor') else 0,
                   pid=self.fn['SDL_JoystickGetDeviceProduct'](index) if self.has('SDL_JoystickGetDeviceProduct') else 0,
                   guid=bytes(self.fn['SDL_JoystickGetDeviceGUID'](index).data).hex()
                   if self.has('SDL_JoystickGetDeviceGUID') else '', kind='', serial='', path='', player=-1)
        if mapped:
            handle = self.fn['SDL_GameControllerOpen'](index)
            if not handle:return None
            row.update(name=self._text('SDL_GameControllerName', handle) or row['name'],
                       serial=self._text('SDL_GameControllerGetSerial', handle),
                       path=self._text('SDL_GameControllerPath', handle),
                       player=self.fn['SDL_GameControllerGetPlayerIndex'](handle),
                       kind=TYPES.get(self.fn['SDL_GameControllerGetType'](handle), 'unknown')
                       if self.has('SDL_GameControllerGetType') else '')
        else:
            if not self.has('SDL_JoystickOpen'):return None
            handle = self.fn['SDL_JoystickOpen'](index)
            if not handle:return None
            row.update(serial=self._text('SDL_JoystickGetSerial', handle), path=self._text('SDL_JoystickPath', handle))
        row['handle'] = handle; row['paths_supported'] = self.has('SDL_GameControllerPath')
        return row

    def close(self, row):
        if row.get('handle'):
            self.fn['SDL_GameControllerClose' if row['mapped'] else 'SDL_JoystickClose'](row['handle'])
            row['handle'] = None

    def attached(self, row):
        name = 'SDL_GameControllerGetAttached' if row['mapped'] else 'SDL_JoystickGetAttached'
        return bool(self.fn[name](row['handle'])) if name in self.fn else True

    def read(self, row):
        """(PS2 button word with stick direction bits, 32-byte packet) of a game controller; (ANY or 0, None) of a
        plain joystick."""
        handle = row['handle']
        if not row['mapped']:
            count = self.fn['SDL_JoystickNumButtons'](handle) if self.has('SDL_JoystickNumButtons') else 0
            pressed = any(self.fn['SDL_JoystickGetButton'](handle, i) for i in range(min(max(count, 0), 32)))
            return (ANY if pressed else 0), None
        get = self.fn['SDL_GameControllerGetButton']
        names = [name for index, name in MAPPED_BUTTONS if get(handle, index)]
        axes = [self.fn['SDL_GameControllerGetAxis'](handle, i) for i in range(6)]
        packet = quad.encode_pad(names, axes)
        return struct.unpack_from('<I', packet)[0], packet

    def hid_paths(self):
        """Lower-case paths of every HID device Windows lists (SDL_hid_enumerate), or None without it."""
        if not self.has('SDL_hid_enumerate'):return None
        head = self.fn['SDL_hid_enumerate'](0, 0); paths = set(); node = head
        try:
            while node:
                info = node.contents
                if info.path:paths.add(info.path.decode('utf-8', 'replace').lower())
                node = info.next
        finally:
            if head and self.has('SDL_hid_free_enumeration'):self.fn['SDL_hid_free_enumeration'](head)
        return paths


class Sink:
    """One mailbox the hub publishes to. The watcher attaches the Mailbox (PINE token) and adds the sink; the hub
    thread is the only writer afterwards. active turns False when the hub dropped it (its world was replaced:
    MappingLost) and failure says why when it was an error."""
    kind = 'sink'

    def __init__(self, mailbox, capture=None):
        self.mailbox, self.capture = mailbox, capture
        self.hub = None; self.active = True; self.failure = None
        self.sequence = 0; self.latch = [{}, {}]; self.live = [0, 0]

    def close(self):
        """Remove the sink (the hub stays). Never blocks long: a hub that does not answer raises RuntimeError."""
        hub, self.hub = self.hub, None
        if hub is not None:hub.remove_sink(self)
        self.active = False

    def keys(self, hub, now):return (None, None)

    def check(self):return True

    def publish(self, hub, now):
        """Writer flag CONTROL+28=1, MAILBOX, sequence CONTROL+16, flag 0 (the guests' snapshot protocol)."""
        if not self.check():raise transport.MappingLost('The guest input service is no longer installed')
        control = self.mailbox.CONTROL
        _, consumed = struct.unpack('<2I', self.mailbox.read(control+16, 8))
        keys = self.keys(hub, now)
        packets = [hub.packet(key, self, slot, now, consumed) for slot, key in enumerate(keys)]
        self.write(packets)
        return packets

    def write(self, packets):
        control = self.mailbox.CONTROL
        self.mailbox.write_u32(control+28, 1)
        self.mailbox.write(self.mailbox.MAILBOX, b''.join(packets))
        self.sequence = (self.sequence+1) & 0xFFFFFFFF or 1
        self.mailbox.write_u32(control+16, self.sequence)
        self.mailbox.write_u32(control+28, 0)


class AssignmentSink(Sink):
    """P1/P2 (controller_assignment). allow_arm is the watcher's `custom` rule (modded matches only, never online);
    in_match says lost seats publish neutral (a match) or pass PCSX2's port through (menus)."""
    kind = 'assignment'

    def __init__(self, mailbox, capture=None, *, allow_arm=False, in_match=False):
        super().__init__(mailbox, capture)
        self.allow_arm, self.in_match = allow_arm, in_match
        self.armed, self.pass_mask = False, 3

    def plan(self, hub):
        if not self.allow_arm or hub.online:return False, 3, (None, None)
        return checkin.p12(hub.checkin.roster, self.in_match)

    def keys(self, hub, now):return self.plan(hub)[2]

    def ports(self):
        """PCSX2's own port records (read-only): two (connected, buttons, sticks)."""
        return [native_state(self.mailbox.read(mode_menu.PAD+k*0x1C0+0x104, 24)) for k in (0, 1)]

    def publish(self, hub, now):
        import controller_assignment as assignment
        from quad_menu_input import MENU_BITS
        armed, mask, keys = self.plan(hub)
        if not armed:
            packets = super().publish(hub, now)
            if self.armed:self.mailbox.write_u32(assignment.CONTROL+12, 0); self.armed = False
            return packets
        if self.armed and mask == self.pass_mask:return super().publish(hub, now)
        # Arming, or a roster change: PASS first; each seat whose PASS bit is being cleared starts from the current
        # packet's button word (held buttons create no edge); one packet; then armed.
        before = self.pass_mask if self.armed else 3
        _, consumed = struct.unpack('<2I', self.mailbox.read(assignment.CONTROL+16, 8))
        packets = [hub.packet(key, self, slot, now, consumed) for slot, key in enumerate(keys)]
        self.mailbox.write_u32(assignment.CONTROL+assignment.PASS, mask)
        for seat, packet in enumerate(packets):
            # Only a seat whose PASS bit is being cleared: an already overridden seat keeps its private words, so a
            # press that arrives with this packet is still an edge for it.
            if not before & ~mask & (1 << seat):continue
            word = struct.unpack_from('<I', packet)[0]
            menu = 0
            for bits, translated in MENU_BITS:
                if word & bits:menu |= translated
            self.mailbox.write(assignment.CONTROL+0x40+12*seat, struct.pack('<3I', word, menu, 0))
        self.write(packets)
        if not self.armed:self.mailbox.write_u32(assignment.CONTROL+12, 1)
        self.armed, self.pass_mask = True, mask
        return packets


class SelectorSink(Sink):
    """P3/P4 at character selection (quad_menu_input). mode 'private': seats 3-4 of the roster (3-4 humans);
    'extras': two free controllers (all controllers allowed with fewer than three humans)."""
    kind = 'selector'

    def __init__(self, mailbox, capture=None, *, mode='private'):
        super().__init__(mailbox, capture); self.mode = mode

    def check(self):
        import quad_menu_input as menu
        return struct.unpack_from('<I', self.mailbox.read(menu.CONTROL, 16))[0] == menu.MAGIC

    def keys(self, hub, now):return hub.private_keys() if self.mode == 'private' else hub.extra_keys()


class BattleSink(Sink):
    """P3/P4 in a prepared three/four-human match (quad_controller); validated each publish as beta.36's bridge was."""
    kind = 'battle'

    def __init__(self, mailbox, capture=None):
        super().__init__(mailbox, capture); self.owner = None

    def check(self):
        fields = struct.unpack('<4I', self.mailbox.read(quad.CONTROL, 16))
        if fields[0] != quad.MAGIC or not fields[3]:return False
        if self.owner is None:self.owner = fields[1:3]
        if fields[1:3] != self.owner:raise ValueError('Four-pad input belongs to a different match')
        if self.mailbox.read_u32(quad.core.ACTORS) != fields[1]:return False
        return struct.unpack('<4I', self.mailbox.read(quad.core.MODE, 16)) == (1, fields[2], fields[1], fields[2])

    def keys(self, hub, now):return hub.private_keys()


class Hub:
    """The SDL owner thread and the publish loop (FINAL spec section 3). state: 'off' | 'starting' | 'ready' |
    'failed' (failure says why). Every public method is safe from the watcher thread and never blocks on SDL."""
    def __init__(self, pid, *, log=None, report=None, sdl_loader=None, clock=time.monotonic, db_paths=None,
                 process_factory=None, sleep=time.sleep):
        self.pid, self.clock, self.sleep = pid, clock, sleep
        self.log = log or (lambda text: None)
        self.report = report
        self.sdl_loader = sdl_loader or input_binding.load_sdl
        self.db_paths = db_paths
        self.process_factory = process_factory
        self.lock = threading.RLock()
        self.state, self.failure = 'off', None
        self.ready_event = threading.Event()
        self.stop = threading.Event()
        self.thread = None
        self.sinks = []
        self.devices = {}          # key -> controller_checkin.Device
        self.rows = {}             # instance -> backend row (handle, key, ...)
        self.checkin = checkin.CheckIn()
        self.ring = collections.deque(maxlen=RING)
        self.presses = {}          # key (or PCSX2 port) -> (count, last press time)
        self.masked = {}           # key -> PS2 bits read as released until physically released
        self.previous = {}         # key -> previous PS2 word
        self.ports = None          # [(connected, buttons, sticks)] of PCSX2 ports 1-2 when readable
        self.port_previous = [0, 0]
        self.pending_hub, self.pending_native = [], []
        self.labels = {}           # port -> name of a layout-less controller that pressed with it
        self.messages = collections.deque(maxlen=64)
        self.notice = None         # (kind, values, time)
        self.online = False
        self.setup_open = False
        self.arrivals = 0
        self.heals, self.heal_at, self.missing_since, self.hid_checked_at = 0, None, {}, -1e9
        self.info = {}
        self.thread_ids = set()    # every thread that called into SDL (tests: exactly one)
        self.polls = 0
        self.poll_error, self.poll_error_at = None, 0.0

    # ---- lifecycle ------------------------------------------------------------------------------------------------
    def start(self):
        # The watcher calls this every tick: once started it returns without the lock, so a hub thread that holds
        # it (an SDL restart, a slow device open) never stalls the watcher.
        if self.thread is not None:return
        with self.lock:
            if self.thread is not None:return
            self.state = 'starting'
            self.thread = threading.Thread(target=self._run, name='TTM controller hub', daemon=True)
            self.thread.start()

    def wait_ready(self, timeout=0):
        """True when the reader runs; waits up to `timeout` seconds while it starts (0: no wait)."""
        if self.state == 'starting' and timeout:self.ready_event.wait(timeout)
        return self.state == 'ready'

    def require_ready(self, timeout=5):
        """Linux capability check: raise the reader's failure (it names SDL2) or a timeout."""
        if self.state == 'off':self.start()
        if self.wait_ready(timeout):return
        if self.state == 'failed':raise OSError(self.failure or 'SDL controller input is unavailable')
        raise RuntimeError('SDL controller initialization timed out')

    def close(self):
        """Watcher exit: stop the thread (SDL quits on it), drop the sinks, close the shared process handle."""
        self.stop.set()
        thread = self.thread
        if thread is not None and thread is not threading.current_thread():thread.join(timeout=5)
        with self.lock:
            for sink in self.sinks:sink.active = False; sink.hub = None
            self.sinks = []
        transport.release_process(self.pid)

    # ---- the thread -----------------------------------------------------------------------------------------------
    def _run(self):
        backend = None
        try:
            self.thread_ids.add(threading.get_ident())
            database, user = self.db_paths if self.db_paths is not None else database_paths()
            backend = Backend(self.sdl_loader())
            info = backend.init(database, user)
            self.backend = backend
            self.info = dict(info, database=str(database) if database else None, user=str(user) if user else None)
            with self.lock:self.state = 'ready'
            self.log(f"Controller hub: SDL {info['version'] or '2'} ready; controller database "
                     f"{database or 'none (SDL built-in layouts only)'}" + (f' + user database {user}' if user else '')
                     + f"; {info['mappings'] if info['mappings'] is not None else 'unknown'} mappings.")
        except Exception as error:   # noqa: BLE001 - reported as TTM-CTRL-20, players 1 and 2 go on
            with self.lock:
                self.state, self.failure = 'failed', str(error) or type(error).__name__
                self.messages.append(('warning', CODES['unavailable'], SAY['unavailable'],
                                      dict(detail=transport.plain_reason(self.failure))))
            self.log(f'Controller hub: the controller reader did not start: {self.failure}')
            self.ready_event.set()
            if backend is not None:
                try:backend.quit()
                except Exception:pass
            return
        self.ready_event.set()
        try:
            while not self.stop.is_set():
                self.thread_ids.add(threading.get_ident())
                started = self.clock()
                with self.lock:
                    try:self._poll(started)
                    except Exception as error:   # noqa: BLE001 - one bad poll never ends the reader
                        text = f'{type(error).__name__}: {error}'
                        if text != self.poll_error or started-self.poll_error_at >= 10:   # at most every 10 s
                            self.poll_error, self.poll_error_at = text, started
                            self.log(f'Controller hub: poll failed: {text}')
                    period = FAST if (self.sinks or self.setup_open) else SLOW
                spent = self.clock()-started
                self.sleep(max(0.001, period-spent))
        finally:
            try:
                for row in list(self.rows.values()):backend.close(row)
                self.rows = {}
                backend.quit()
            except Exception as error:   # noqa: BLE001
                self.log(f'Controller hub: SDL did not close cleanly: {error}')

    def _poll(self, now):
        self.polls += 1
        backend = self.backend
        backend.update()
        self._scan(now)
        events = []
        for instance, row in list(self.rows.items()):
            device = self.devices.get(row['key'])
            if device is None:continue
            word, packet = backend.read(row)
            row['packet'] = packet
            self._edges(now, row['key'], word, events, mapped=row['mapped'])
        assignment = next((s for s in self.sinks if s.kind == 'assignment'), None)
        native_events = []
        if assignment is not None:
            try:self.ports = assignment.ports()
            except transport.MappingLost:self.ports = None
            except Exception:self.ports = None
            if self.ports is not None:
                for port, (connected, buttons, _) in enumerate(self.ports, 1):
                    before = self.port_previous[port-1]; self.port_previous[port-1] = buttons
                    for bit in self._bits(buttons & ~before & 0xFFFF):
                        self.pending_native.append([now, port, bit, False])
                        count, _ = self.presses.get(checkin.PSEUDO[port], (0, 0))
                        self.presses[checkin.PSEUDO[port]] = (count+1, now)
        else:
            self.ports = None
        pseudo = self._match(now)
        self.checkin.step(now, self.devices, sorted(events+pseudo), in_match=self._in_match(), labels=self.labels)
        self._outputs(now)
        self._heal(now)
        for sink in list(self.sinks):
            try:sink.publish(self, now)
            except transport.MappingLost:self._drop(sink, None)
            except Exception as error:   # noqa: BLE001 - this sink only
                self._drop(sink, f'{type(error).__name__}: {error}' if not str(error) else str(error))

    def _in_match(self):
        return any(s.kind == 'battle' or (s.kind == 'assignment' and s.in_match) for s in self.sinks)

    @staticmethod
    def _bits(word):
        bit = 1
        while word:
            if word & bit:yield bit; word &= ~bit
            bit <<= 1

    def _edges(self, now, key, word, events, *, mapped):
        before = self.previous.get(key, 0); self.previous[key] = word
        masked = self.masked.get(key, 0)
        if masked:
            self.masked[key] = masked & word & 0xFFFF   # released bits are no longer masked
        device = self.devices[key]
        for bit in self._bits(word & ~before):
            if bit & 0xFFFF or bit == ANY:
                self.ring.append((now, key, 'down', bit)); events.append((now, key, 'down', bit))
                if bit & 0xFFFF and mapped and not device.twin_of:self.pending_hub.append((now, key, bit))
            device.last_active = now
            count, _ = self.presses.get(key, (0, 0)); self.presses[key] = (count+1, now)
        for bit in self._bits(before & ~word):
            if bit & 0xFFFF or bit == ANY:
                self.ring.append((now, key, 'up', bit)); events.append((now, key, 'up', bit))

    def _scan(self, now):
        current = dict((instance, index) for index, instance in self.backend.instances() if instance >= 0)
        for instance in [i for i in self.rows if i not in current or not self.backend.attached(self.rows[i])]:
            row = self.rows.pop(instance); self.backend.close(row)
            device = self.devices.get(row['key'])
            if device is not None:
                device.connected = False; self.previous.pop(row['key'], None); self.masked.pop(row['key'], None)
                self.log(f"Controller disconnected: {device.display or device.name} (key {device.key}).")
        added = [(i, current[i]) for i in current if i not in self.rows]
        if not added:return
        for instance, index in sorted(added, key=lambda item: item[1]):
            row = self.backend.open(index, instance)
            if row is None:continue
            connected = [d for d in self.devices.values() if d.connected]
            row['serial_unique'] = bool(row['serial']) and not any(d.serial == row['serial'] for d in connected)
            if not row.get('paths_supported') and not row['serial']:
                row['order'] = sum(1 for d in self.devices.values() if d.guid == row['guid'])
            xinput = XINPUT_PATH.match(row['path'] or '')
            row['xinput'] = int(xinput.group(1)) if xinput else None
            taken = {d.key for d in connected}
            key = identity_key(row, taken)
            if key not in self.devices:
                # A controller coming back keeps the key of its disconnected entry (same serial or device path).
                back = [d for d in self.devices.values() if not d.connected and d.key not in taken and
                        ((row['serial'] and d.serial == row['serial']) or (row['path'] and d.path == row['path'] and not xinput))]
                if len(back) == 1:key = back[0].key
            row['key'] = key
            device = self.devices.get(key)
            if device is None:
                self.arrivals += 1
                device = checkin.Device(key=key, first_seen=now, order=self.arrivals); self.devices[key] = device
            device.name, device.kind, device.vid, device.pid = row['name'] or 'Controller', row['kind'], row['vid'], row['pid']
            device.guid, device.serial, device.path, device.mapped = row['guid'], row['serial'], row['path'], row['mapped']
            device.xinput, device.connected = row['xinput'], True
            self.rows[instance] = row
            self.log(f"Controller connected: {device.name} ({device.kind or 'joystick'}, key {key}, "
                     f"layout {'yes' if device.mapped else 'no'}).")
        self._names()

    def _names(self):
        """display = SDL name; duplicates get ' #2', ' #3' in first_seen order."""
        groups = collections.defaultdict(list)
        for device in self.devices.values():groups[device.name].append(device)
        for name, rows in groups.items():
            rows.sort(key=lambda d: (d.first_seen, d.order))
            for i, device in enumerate(rows):device.display = name if i == 0 else f'{name} #{i+1}'

    def _group(self, key):
        """A controller and its twins (one device for press matching)."""
        device = self.devices.get(key)
        primary = device.twin_of if device is not None and device.twin_of else key
        return {primary} | {k for k, d in self.devices.items() if d.twin_of == primary}

    def _match(self, now):
        """Press matching (spec 3.7): hub presses against PCSX2 port presses. Returns pseudo press events."""
        if self.ports is None:
            self.pending_hub = [p for p in self.pending_hub if now-p[0] < 1.0]
            self.pending_native = []
            return []
        due = [p for p in self.pending_hub if now-p[0] >= MATCH_AFTER]
        self.pending_hub = [p for p in self.pending_hub if now-p[0] < MATCH_AFTER]
        recent = [(t, k, b) for (t, k, kind, b) in self.ring if kind == 'down' and now-t <= 1.0]
        for t, key, bit in due:
            device = self.devices.get(key)
            if device is None or not device.mapped:continue
            group = self._group(key)
            unique = not any(b == bit and k not in group and abs(t2-t) <= MATCH_UNIQUE and self.devices.get(k) is not None
                             and self.devices[k].mapped for t2, k, b in recent)
            for port, (connected, _, _) in enumerate(self.ports, 1):
                if not connected:continue
                hits = [n for n in self.pending_native if n[1] == port and n[2] == bit and t-MATCH_BEFORE <= n[0] <= t+MATCH_AFTER]
                if hits:
                    for n in hits:n[3] = True
                    if unique:self._score(group, port, +1)
                else:self._score(group, port, -1)
        pseudo = []
        for entry in list(self.pending_native):
            t, port, bit, matched = entry
            if now-t < PSEUDO_AFTER:continue
            self.pending_native.remove(entry)
            if matched or any(b == bit and abs(t2-t) <= PSEUDO_AFTER and self.devices.get(k) is not None
                              and self.devices[k].mapped for t2, k, b in recent):
                continue
            labels = [self.devices[k] for t2, k, b in recent if b == ANY and abs(t2-t) <= PSEUDO_AFTER and k in self.devices]
            if labels:self.labels[port] = labels[-1].display or labels[-1].name
            pseudo.append((t, checkin.PSEUDO[port], 'down', bit))
        return pseudo

    def _score(self, group, port, delta):
        for key in group:
            device = self.devices.get(key)
            if device is None:continue
            device.native_score[port] = device.native_score.get(port, 0)+delta
            if delta < 0:device.native_misses[port] = device.native_misses.get(port, 0)+1
            best = max((p for p, s in device.native_score.items() if s >= 1), key=lambda p: device.native_score[p],
                       default=None)
            confirmed = best is not None and device.native_score[best] >= CONFIRMED and not device.native_misses.get(best)
            if (best, confirmed) != (device.native_port, device.native_confirmed):
                if best is not None and (best != device.native_port or confirmed):
                    self.log(f"Controller {device.display or device.name} is PCSX2 port {best}"
                             + (' (confirmed).' if confirmed else '.'))
                device.native_port, device.native_confirmed = best, confirmed

    def _outputs(self, now):
        messages, notices, claims, lines = self.checkin.take()
        for level, code, kind, values in messages:self.messages.append((level, code, SAY[kind], values))
        for kind, values in notices:self.notice = (kind, values, now)
        for key, bit in claims:self.masked[key] = self.masked.get(key, 0) | (bit & self.previous.get(key, 0) & 0xFFFF)
        for line in lines:self.log(line)

    def _heal(self, now):
        roster = self.checkin.roster
        claimed = {s.key for s in roster.seats if s.key and s.source in ('hub', 'native')} if roster is not None else set()
        candidates = []
        for key in claimed:
            device = self.devices.get(key)
            if device is None or device.connected:self.missing_since.pop(key, None); continue
            since = self.missing_since.setdefault(key, now)
            if device.xinput is None and device.path and not XINPUT_PATH.match(device.path) and now-since >= HEAL_AFTER:
                candidates.append(device)
        if not candidates or self.heals >= HEAL_LIMIT or (self.heal_at is not None and now-self.heal_at < HEAL_GAP):return
        if now-self.hid_checked_at < 1.0:return   # SDL_hid_enumerate at most once a second
        self.hid_checked_at = now
        paths = self.backend.hid_paths()
        if not paths:return
        lost = [d for d in candidates if d.path.lower() in paths]
        if not lost:return
        self.heals += 1; self.heal_at = now
        self.log(f'Controller hub: {lost[0].display or lost[0].name} vanished while Windows still lists it; restarting '
                 f"SDL's controller input ({self.heals}/{HEAL_LIMIT} this match).")
        for row in list(self.rows.values()):self.backend.close(row)
        self.rows = {}
        for device in self.devices.values():device.connected = False
        self.previous = {}
        self.backend.restart()
        self._scan(now)

    def _drop(self, sink, failure):
        if sink in self.sinks:self.sinks.remove(sink)
        sink.active = False; sink.failure = failure; sink.hub = None
        self.log(f'Controller hub: {sink.kind} input ' + ('ended (the match or menu was replaced).' if failure is None
                                                          else f'stopped: {failure}'))

    # ---- what sinks publish -----------------------------------------------------------------------------------------
    def packet(self, key, sink, slot, now, consumed):
        """The 32-byte pad packet of `key` for one sink seat: claim-masked, and new presses latched until the guest's
        consumed sequence shows a packet carrying them was taken (at most LATCH seconds)."""
        device = self.devices.get(key) if key is not None else None
        row = next((r for r in self.rows.values() if r.get('key') == key), None) if device is not None else None
        packet = row.get('packet') if row is not None and device.connected else None
        if packet is None:
            sink.latch[slot] = {}; sink.live[slot] = 0
            return bytes(32)
        word = struct.unpack_from('<I', packet)[0] & ~self.masked.get(key, 0)
        live = word & 0xFFFF
        latch = sink.latch[slot]
        for bit in self._bits(live & ~sink.live[slot]):latch[bit] = ((sink.sequence+1) & 0xFFFFFFFF or 1, now)
        sink.live[slot] = live
        for bit, (first, when) in list(latch.items()):
            if _later(consumed, first) or now-when >= LATCH:del latch[bit]
            else:word |= bit
        return struct.pack('<I', word)+packet[4:]

    def private_keys(self):
        roster = self.checkin.roster
        if roster is None or roster.humans < 3:
            classic = checkin.classic_keys(self.devices, roster)
            return tuple(classic+[None]*(2-len(classic)))[:2]
        return checkin.private(roster, self.devices)

    def extra_keys(self):
        """The free controllers of 'Allow all controllers during character selection'. While PCSX2's ports are read,
        a controller never matched against them yet waits until its first press has been: a pad PCSX2 already uses
        never moves a second cursor, not even with that first press."""
        matching = ({key for _, key, _ in self.pending_hub if key in self.devices and not self.devices[key].native_score}
                    if self.ports is not None and any(port[0] for port in self.ports) else ())
        return checkin.extras(self.devices, self.checkin.roster, exclude=matching)

    # ---- the watcher's side -----------------------------------------------------------------------------------------
    @contextlib.contextmanager
    def _locked(self, timeout=1.0):
        """The hub lock for a watcher call; a hub that does not answer within `timeout` raises RuntimeError."""
        if not self.lock.acquire(timeout=timeout):raise RuntimeError('The controller hub did not respond')
        try:yield
        finally:self.lock.release()

    def add_sink(self, sink):
        with self._locked():
            for other in [s for s in self.sinks if s.kind == sink.kind]:self._drop(other, None)
            sink.hub = self; sink.active = True; sink.failure = None
            self.sinks.append(sink)
        return sink

    def remove_sink(self, sink):
        with self._locked():
            if sink in self.sinks:self.sinks.remove(sink)
            sink.active = False; sink.hub = None

    def configure(self, sink, **values):
        with self._locked():
            for name, value in values.items():setattr(sink, name, value)

    def open_setup(self, humans, team_mode, *, mode=None, keep=None):
        with self._locked():
            self.setup_open = True; self.notice = None
            return self.checkin.open(humans, team_mode, self.clock(), self.devices, mode=mode, keep=keep).copy()

    def close_setup(self, commit):
        """Continue (commit=True) keeps the roster for the match and later ones; Back drops the draft. Returns the
        roster line logged at Continue."""
        with self._locked():
            self.setup_open = False
            roster = self.checkin.roster
            if commit and roster is not None and self.state != 'ready':
                # No reader: connection order (beta.36), the teams Player 1 chose kept.
                fallback = checkin.Roster(roster.humans, 'connection_order', roster.team_mode)
                for seat, old in zip(fallback.seats, roster.seats):seat.team = old.team
                self.checkin.roster = fallback
            line = checkin.roster_line(self.checkin.roster, self.devices) if commit and self.checkin.roster else None
            self.checkin.close(commit, self.clock())
            if line:self.log(line)
            return line

    def clear_checkins(self):
        with self._locked():self.checkin.clear(self.clock()); self.notice = None

    def set_team(self, number, team):
        with self._locked():self.checkin.set_team(number, team, self.clock())

    def select(self, humans, via_setup, *, mode=None, keep=None):
        """A Modded Modes selection: which roster the match uses (controller_checkin.CheckIn.select)."""
        with self._locked():
            roster = self.checkin.select(humans, via_setup, self.clock(), self.devices, mode=mode, keep=keep)
            self.heals = 0
            return roster.copy()

    def new_match(self):
        with self._locked():self.checkin.new_match(); self.heals = 0

    def take_messages(self):
        with self._locked():
            out = list(self.messages); self.messages.clear(); return out

    def snapshot(self):
        """A copy for the panel: state, roster, devices, press counters, the latest notice, readiness."""
        import copy
        from types import SimpleNamespace
        with self._locked():
            roster = self.checkin.roster.copy() if self.checkin.roster is not None else None
            now = self.clock()
            return SimpleNamespace(state=self.state, failure=self.failure, roster=roster,
                                   devices={k: copy.copy(d) for k, d in self.devices.items()},
                                   presses=dict(self.presses), notice=self.notice, now=now,
                                   ready=checkin.ready(roster, now) if roster is not None else False,
                                   waiting=checkin.waiting(roster), classic=checkin.classic_keys(self.devices, roster),
                                   ports=list(self.ports) if self.ports is not None else None, labels=dict(self.labels))
