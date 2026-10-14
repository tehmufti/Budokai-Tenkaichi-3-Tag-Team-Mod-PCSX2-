"""The online lobby window (Tk, standard library only; English and Spanish). The UI process of a kit: it shows the
session process's state and sends its commands (kit_ipc); it never touches the network, PINE or PCSX2 itself, so a
crash here does not end a match (start "Play online" again: it re-attaches).

Screens: Start (name, EN/ES, Open / Join a room, files, controllers, Advanced), Check (this PC's checklist), Room (the
people in it - watching or playing -, the two teams or free-for-all columns the host builds on the spot with any
fighters and colours, the rules panel: stage, music, Duel Time, CPU level, referee, destructible, the host's gameplay
rules and this PC's own display settings; Ready / Start / Just watch / Leave, chat), the fighter, stage and Potara
pickers, Preparing, Sending / Loading, Fight (playing or watching, End match / Leave this match), Results (Retry needs
every player within 10 s, else everyone returns to the lobby). Waits over a second while the game window is shown get
a small always-on-top banner over it that never takes the focus (kit_win.overlay_style).

How the window stays steady:
- one owner for navigation: go() is the only way to change screens. It closes this screen's dialogs and questions,
  cancels its timers (later()) and rebuilds; nothing else destroys a screen. Typed text (name, address, chat, the
  rename box) lives in variables that outlive screens and language switches.
- session packets update widgets in place (configure_changed, per-row update()); a panel is rebuilt only when its
  structure changes (members join or leave, team sizes, mode, the host role, the language).
- resizing does no Python work per frame: wrapping labels, the lobby's wide or stacked layout and the panel heights are
  recomputed once the size has been still for a moment (relayout_soon), with hysteresis at the layout thresholds.
- the window's frame is fixed: the title band on top, this screen's actions and the chat pinned at the bottom (they
  never scroll away); only the middle scrolls.
- one-shot commands ignore repeated clicks (once()), Ready waits for the session's answer, spin boxes send at most one
  rule change per pause, and a question answered after the screen changed is ignored.
- the session pump survives a drawing error in any screen (it is logged and the screen is rebuilt).
Disc names (fighters, stages, referees, the game's setting labels) stay as on the disc in both languages.
"""
import json
import os
import struct
import subprocess
import sys
import time
import tkinter as tk
import weakref
import zlib
from pathlib import Path
from tkinter import filedialog, ttk

import kit_catalog
import kit_browser
import kit_net
import queue
import threading
import kit_lobby_console
import kit_paths
import kit_settings
import kit_text
import kit_theme as th
import kit_win
from kit_text import t

# The old colour names, mapped onto the theme (other modules and tests import them).
BG, PANEL, CARD, INK, DIM, GOLD, RED, BLUE, GREEN = (th.NIGHT, th.PANEL, th.CARD, th.INK, th.DIM, th.GOLD, th.RED,
                                                     th.BLUE, th.GREEN)
FONT = th.BODY_FAMILY
TIMES = (60, 90, 180, 240, 0)
FALLBACK = 30.0
DESIGN = (1220, 760)                     # the window's size at 96 DPI (100 %)
S = 1.0                                  # this screen's UI scale (App.fit_window; th.S is the same number)
PZ = 1                                   # portraits and stage pictures are drawn twice as large from 175 % on
SERVER_BROWSER_VISIBLE = False          # keep discovery available for later, but out of the player menus
WIDE_ON, WIDE_OFF = 1130, 1100           # the lobby's three columns: on from 1130 px, back to stacked below 1100 px
SETTLE_MS = 45                           # a size must be still this long before the layout is recomputed
MAX_WAIT_MS = 600                        # ... but during a long drag (or a build) it is recomputed at least this often
DRAG_S = 0.15                            # a window whose size changed this recently is being dragged
SCREENS = {'start': 'start', 'check': 'check', 'lobby': 'lobby', 'preparing': 'prep', 'sending': 'prep',
           'loading': 'prep', 'fight': 'fight', 'results': 'results'}
CHAT_SCREENS = ('lobby', 'prep', 'fight', 'results')


def px(n):
    """A pixel size of the 96-DPI design at this screen's scale."""
    return th.px(n)


font = th.font
heading = th.heading


def elide(text, width=64):
    """A long path as its start and its end."""
    text = str(text)
    return text if len(text) <= width else text[:22] + ' … ' + text[-(width - 25):]


def configure_changed(widget, **options):
    """Do not redraw an unchanged control on every session status packet."""
    changed = {key: value for key, value in options.items() if str(widget.cget(key)) != str(value)}
    if changed:
        widget.configure(**changed)
        if 'state' in changed and hasattr(widget, '_ttm'):
            th._paint(widget)
    if getattr(widget, '_ttm_collapse', False) and 'text' in options:   # an empty line takes no room
        manager = widget.winfo_manager()
        if options['text'] and not manager:
            widget.grid()
        elif not options['text'] and manager == 'grid':
            widget.grid_remove()


def collapsing(label):
    """A gridded label of the pinned bar that disappears while it has no text."""
    label._ttm_collapse = True
    if not label.cget('text'):
        label.grid_remove()
    return label


# ---- wrapping labels: one pass after a resize, not one callback per label per frame --------------------------------------
_WRAPS = weakref.WeakSet()


def wrap_label(label, pad=4):
    """A label that wraps to the width its layout gives it: at once when it appears or its column changes, but only
    after the drag has stopped while the window is being resized (every rewrap makes Tk lay the window out again)."""
    label.configure(width=1, justify='left', anchor='w', wraplength=px(400))
    label._ttm_pad = pad
    _WRAPS.add(label)
    label.bind('<Configure>', _label_configured, add='+')
    return label


def _label_configured(event):
    label = event.widget
    try:
        entry = _relayout_entry(label.winfo_toplevel())
        if time.monotonic() - entry.get('drag', 0.0) < DRAG_S:
            return                                           # the settle pass after the drag does it
        width = max(20, event.width - label._ttm_pad)
        if abs(label.winfo_pixels(label.cget('wraplength')) - width) > 1:
            label.configure(wraplength=width)
            remeasure(label.winfo_toplevel())
    except (tk.TclError, AttributeError, KeyError):
        pass


def remeasure(top):
    """A label's new height must reach the scroll panels it sits in (their content has a fixed size otherwise)."""
    for panel in list(_PANELS):
        if getattr(panel, 'top', None) is top:
            panel.schedule()


def rewrap(top=None):
    """Give every mapped wrapping label (of one toplevel) its current width; returns how many changed."""
    changed = 0
    for label in list(_WRAPS):
        try:
            if not label.winfo_exists() or not label.winfo_ismapped():
                continue
            if top is not None and label.winfo_toplevel() is not top:
                continue
            width = max(20, label.winfo_width() - label._ttm_pad)
            if abs(label.winfo_pixels(label.cget('wraplength')) - width) > 1:
                label.configure(wraplength=width)
                changed += 1
        except (tk.TclError, AttributeError):
            pass
    return changed


def _relayout_entry(top):
    entry = getattr(top, '_ttm_relayout', None)
    if entry is None:
        entry = top._ttm_relayout = dict(job=None, last=0.0, first=None, hooks=[])
    return entry


def relayout_soon(widget, delay=SETTLE_MS):
    """Recompute the wrapping (and the toplevel's layout hooks) once its size has been still for `delay` ms."""
    try:
        top = widget.winfo_toplevel()
    except (tk.TclError, KeyError):
        return
    entry = _relayout_entry(top)
    if entry.get('dead'):
        return
    entry['last'] = time.monotonic()
    if entry['first'] is None:
        entry['first'] = entry['last']
    if entry['job'] is None:
        try:                                                 # the root's timer: it outlives a closing dialog
            entry['job'] = top._root().after(delay, lambda: _relayout(top, delay))
        except tk.TclError:
            pass


def add_relayout_hook(top, hook):
    _relayout_entry(top)['hooks'].append(hook)


def _relayout(top, delay):
    entry = _relayout_entry(top)
    entry['job'] = None
    try:
        if not top.winfo_exists():
            return
    except tk.TclError:
        return
    now = time.monotonic()
    still = (now - entry['last']) * 1000
    waited = (now - (entry['first'] or now)) * 1000
    if still < delay - 5 and waited < MAX_WAIT_MS:          # still being dragged: look again a little later
        try:
            entry['job'] = top._root().after(max(10, int(delay - still)), lambda: _relayout(top, delay))
        except tk.TclError:
            pass
        return
    entry['first'] = None
    for hook in list(entry['hooks']):
        try:
            hook()
        except tk.TclError:
            pass
    if rewrap(top):                  # heights may change, widths do not: the next settle finds nothing more to do
        remeasure(top)


_PANELS = weakref.WeakSet()


def watch_resizes(top):
    """Every Configure inside `top` (it, its children) restarts the settle timer and lets the scroll panels re-measure
    their content (an idle call each, a few attribute reads); the expensive work waits for the size to settle."""
    def changed(event):
        if event.widget is top:
            entry = _relayout_entry(top)
            size = (event.width, event.height)
            if entry.get('size') not in (None, size):
                entry['drag'] = time.monotonic()             # the window itself changed size: a drag
            entry['size'] = size
        relayout_soon(top)
        remeasure(top)

    def gone(event):
        if event.widget is top:                              # no timer may outlive its window
            entry = _relayout_entry(top)
            entry['dead'] = True
            if entry['job'] is not None:
                try:
                    top._root().after_cancel(entry['job'])
                except tk.TclError:
                    pass
                entry['job'] = None
    top.bind('<Configure>', changed, add='+')
    top.bind('<Destroy>', gone, add='+')


class Flow(tk.Frame):
    """Buttons keep their full labels and move to another row when necessary. `right` widgets sit at the right end of
    a single row (the confirming actions) when everything fits on one line."""

    def __init__(self, parent, align='left', **options):
        super().__init__(parent, **options)
        self.widgets, self.right, self.job, self.positions = [], [], None, None
        self.align = align
        self.bind('<Configure>', lambda _: self.schedule())
        self.bind('<Destroy>', self.cancel, add='+')

    def set_widgets(self, widgets, right=()):
        widgets, right = list(widgets), [w for w in right if w in widgets]
        if widgets == self.widgets and right == self.right:
            if self.positions is None or any((w.winfo_reqwidth(), w.winfo_reqheight()) != (width, height)
                                             for w, _, _, width, height in self.positions):
                self.schedule()
            return
        for widget in self.widgets:
            if widget not in widgets:
                widget.place_forget()
        self.widgets, self.right = widgets, right
        self.positions = None
        self.schedule()

    def add(self, widget):
        self.set_widgets(self.widgets + [widget], self.right)
        return widget

    def cancel(self, event):
        if event.widget is self and self.job:
            self.after_cancel(self.job)
            self.job = None

    def schedule(self):
        if not self.job:
            self.job = self.after_idle(self.arrange)

    def arrange(self):
        self.job = None
        if not self.winfo_exists():
            return
        width = max(1, self.winfo_width())
        gap = px(6)
        x, y, row_height, positions, rows = 0, 0, 0, [], [[]]
        for widget in self.widgets:
            if isinstance(widget, (tk.Button, tk.Label)):
                natural = getattr(widget, '_ttm_natural', None)
                text = widget.cget('text')
                if natural is None or natural[0] != text:
                    current = widget.winfo_pixels(widget.cget('wraplength'))
                    if current:
                        widget.configure(wraplength=0)
                    natural = widget._ttm_natural = (text, widget.winfo_reqwidth())
                wrap = 0
                if natural[1] + 2 * px(3) > width:                # only a label too long for the row wraps
                    padding = 2 * sum(widget.winfo_pixels(widget.cget(key))
                                      for key in ('padx', 'borderwidth', 'highlightthickness'))
                    wrap = max(20, width - 2 * px(3) - padding - 4)
                if widget.winfo_pixels(widget.cget('wraplength')) != wrap:
                    widget.configure(wraplength=wrap)
                if wrap and widget.winfo_reqwidth() + 2 * px(3) > width:
                    widget.configure(width=0)
            w, h = widget.winfo_reqwidth(), widget.winfo_reqheight()
            needed = w + gap
            if x and x + needed > width:
                x, y, row_height = 0, y + row_height + px(4), 0
                rows.append([])
            positions.append([widget, x + px(3), y + px(2), w, h])
            rows[-1].append(positions[-1])
            x, row_height = x + needed, max(row_height, h)
        if self.right and len(rows) == 1 and positions:          # one line: confirming actions to the right edge
            shift = width - (positions[-1][1] + positions[-1][3]) - px(3)
            for p in positions:
                if p[0] in self.right and shift > 0:
                    p[1] += shift
        elif self.align == 'right':
            for row in rows:
                if row:
                    shift = width - (row[-1][1] + row[-1][3]) - px(3)
                    for p in row:
                        p[1] += max(0, shift)
        for row in rows:                                         # centre each row's items vertically
            tallest = max((p[4] for p in row), default=0)
            for p in row:
                p[2] += (tallest - p[4]) // 2
        positions = [tuple(p) for p in positions]
        # (The old Flow reused x and y as the loop variables here, so its height came out px(2) taller whenever the
        # buttons moved and the next pass shrank it again: every resize step laid the whole window out twice.)
        height = y + row_height + px(4) if self.widgets else 0
        if positions != self.positions:
            self.positions = positions
            for widget, px_, py_, w, h in positions:
                widget.place(x=px_, y=py_, width=w, height=h)
        if int(self.cget('height')) != height:
            self.configure(height=height)


class ScrollPanel(tk.Frame):
    """Width follows the window; overflowing height stays reachable by scrolling. With `edge`, the panel wears the gold
    frame (the frame itself is this widget's border)."""

    def __init__(self, parent, bg=BG, height=400, edge=None, **options):
        options.pop('highlightbackground', None)
        options.pop('highlightthickness', None)
        if edge:
            super().__init__(parent, bg=edge, relief='ridge', bd=max(2, px(3)), **options)
        else:
            super().__init__(parent, bg=bg, **options)
        self.auto_height, self.job, self.size = False, None, None
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, width=1, height=px(height))
        self.bar = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.content = tk.Frame(self.canvas, bg=bg)
        self.window = self.canvas.create_window(0, 0, window=self.content, anchor='nw')
        self.canvas.bind('<Configure>', lambda _: self.schedule())
        self.content.bind('<Configure>', lambda _: self.schedule())
        self.bind('<Destroy>', self.cancel, add='+')
        self.top = self.winfo_toplevel()
        _PANELS.add(self)

    def cancel(self, event):
        if event.widget is self and self.job:
            self.after_cancel(self.job)
            self.job = None

    def schedule(self):
        try:
            if not self.job and self.winfo_exists():
                self.job = self.after_idle(self.arrange)
        except tk.TclError:
            pass

    def arrange(self):
        self.job = None
        if not self.winfo_exists():
            return
        width = max(1, self.canvas.winfo_width())
        requested = self.content.winfo_reqheight()
        height = max(self.canvas.winfo_height(), requested)
        if self.auto_height:
            if self.canvas.winfo_pixels(self.canvas.cget('height')) != requested:
                self.canvas.configure(height=requested)
            if self.bar.winfo_manager():
                self.bar.pack_forget()
        elif requested > self.canvas.winfo_height() + 1:
            if not self.bar.winfo_manager():
                self.bar.pack(side='right', fill='y')
        else:
            if self.bar.winfo_manager():
                self.bar.pack_forget()
        if self.size != (width, height):
            self.size = width, height
            self.canvas.itemconfigure(self.window, width=width, height=height)
            self.canvas.configure(scrollregion=(0, 0, width, height))

    def scrollable(self):
        first, last = self.canvas.yview()
        return first > 0.001 or last < 0.999


# ---- PNG helpers (our own captures: 8-bit RGBA, filter 0) -----------------------------------------------------------------
def png_decode(data):
    """(width, height, rgba bytes) of a PNG this module (or kit_win.capture_png) wrote."""
    at, w, h, idat = 8, 0, 0, b''
    while at < len(data):
        n = struct.unpack('>I', data[at:at + 4])[0]
        kind = data[at + 4:at + 8]
        body = data[at + 8:at + 8 + n]
        if kind == b'IHDR':
            w, h = struct.unpack('>II', body[:8])
        elif kind == b'IDAT':
            idat += body
        at += 12 + n
    raw = zlib.decompress(idat)
    stride = w * 4
    out = bytearray()
    for y in range(h):
        row = raw[y * (stride + 1):(y + 1) * (stride + 1)]
        if row[0] != 0:
            raise ValueError('filtered PNG')
        out += row[1:]
    return w, h, bytes(out)


def png_encode(w, h, rgba):
    rows = b''.join(b'\0' + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))
    chunk = lambda kind, body: struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows, 6)) + chunk(b'IEND', b''))


def composite(base_png, base_rect, top_png, top_rect):
    """The game window's picture with the banner's picture pasted where the banner sits (proof of the overlay)."""
    bw, bh, base = png_decode(base_png)
    tw, th_, top = png_decode(top_png)
    out = bytearray(base)
    dx, dy = top_rect[0] - base_rect[0], top_rect[1] - base_rect[1]
    for y in range(th_):
        yy = y + dy
        if not 0 <= yy < bh:
            continue
        x0, x1 = max(0, dx), min(bw, dx + tw)
        if x0 >= x1:
            continue
        out[(yy * bw + x0) * 4:(yy * bw + x1) * 4] = top[(y * tw + x0 - dx) * 4:(y * tw + x1 - dx) * 4]
    return png_encode(bw, bh, bytes(out))


class FighterRow:
    """One fighter of the room's teams, updated in place when its character, colour, owner or lock changes."""

    def __init__(self, app, parent, team, index, host):
        self.app, self.team, self.index = app, team, index
        self.values = None
        self.frame = tk.Frame(parent, bg=th.CARD, highlightthickness=max(1, px(2)),
                              highlightbackground=th.TEAM_DIM[team % 2])
        self.frame.pack(fill='x', pady=px(3))
        self.frame.columnconfigure(1, weight=1)
        self.pic = th.portrait_frame(self.frame, None, bg=th.INSET)
        self.pic.grid(row=0, column=0, rowspan=2, sticky='nw', padx=px(4), pady=px(4))
        self.name = wrap_label(tk.Label(self.frame, bg=th.CARD, fg=th.INK, font=font(10, True)))
        self.name.grid(row=0, column=1, sticky='ew', padx=(px(2), px(4)), pady=(px(4), 0))
        self.sub = wrap_label(tk.Label(self.frame, bg=th.CARD, fg=th.DIM, font=font(9)))
        self.sub.grid(row=1, column=1, sticky='new', padx=(px(2), px(4)))
        self.actions = Flow(self.frame, bg=th.CARD)
        self.actions.grid(row=2, column=0, columnspan=2, sticky='ew', padx=px(2), pady=(0, px(4)))
        self.potara = app.button(self.actions, app.T('potara.title'),
                                 lambda: app.open_potara_picker(self.team, self.index), kind='plain')
        self.lock = app.button(self.actions, '', self.toggle_lock, kind='ghost')
        self.claim = app.button(self.actions, app.T('room.claim'),
                                lambda: app.once(('claim', self.team, self.index),
                                                 lambda: app.send('claim', team=self.team, index=self.index)),
                                kind='secondary')
        self.editable = False
        for w in (self.frame, self.pic, self.pic.picture, self.name, self.sub):
            w.bind('<Button-1>', self.click, add='+')
            w.bind('<Enter>', lambda e: self.hover(True), add='+')
            w.bind('<Leave>', lambda e: self.hover(False), add='+')

    def click(self, _event):
        if self.editable:
            self.app.open_picker(self.team, self.index)

    def hover(self, on):
        color = th.CARD_HI if on and self.editable else th.CARD
        for w in (self.frame, self.name, self.sub, self.actions):
            try:
                if w.cget('bg') != color:
                    w.configure(bg=color)
            except tk.TclError:
                pass

    def toggle_lock(self):
        f = self.f
        self.app.send('lock', team=self.team, index=self.index, locked=not bool(f.get('locked')))

    def update(self, f, members, host, lobby_open):
        app = self.app
        self.f = f
        owner = f.get('owner')
        mine = owner is not None and owner == app.me()
        who = members.get(owner, {}).get('name') if owner is not None else None
        locked = bool(f.get('locked'))
        catalog = app.catalog
        key = (f['character'], f['costume'], owner, who, locked, tuple(f.get('potaras', [])), mine, host, lobby_open,
               catalog.c.get('dir') if catalog else None)
        if key == self.values:
            return
        self.values = key
        img = app.image(catalog.chars[f['character']]['portrait']) if catalog and \
            f['character'] in catalog.chars else None
        if self.pic.picture.cget('image') != (str(img) if img else ''):
            if img:
                self.pic.picture.configure(image=img, text='', width=0, height=0)
            else:
                self.pic.picture.configure(image='', text='?', width=4, height=2)
        configure_changed(self.pic, bg=th.GLOW if mine else th.EDGE, relief='flat' if mine else 'ridge')
        name = catalog.name(f['character']) if catalog else str(f['character'])
        configure_changed(self.name, text=name, fg=th.GOLD if mine else th.INK)
        state = (app.T('room.human', name=who) if who else
                 app.T('room.cpu_locked') if locked else app.T('room.cpu'))
        sub = f'{app.T("lobby.colour")} {f["costume"] + 1} · ' + state
        items = f.get('potaras', [])
        if items:
            sub += ' · ' + app.T('potara.count', n=len(items))
        configure_changed(self.sub, text=sub, fg=th.GOLD if mine else (th.GREEN if who else th.DIM))
        configure_changed(self.frame, highlightbackground=th.GOLD if mine else th.TEAM_DIM[self.team % 2])
        self.editable = (host or mine) and lobby_open
        self.frame.configure(cursor='hand2' if self.editable else '')
        widgets = [self.potara]
        if host and lobby_open:
            configure_changed(self.lock, text=app.T('room.unlock' if locked else 'room.lock'))
            widgets.append(self.lock)
        if owner is None and not locked and lobby_open:
            widgets.append(self.claim)
        self.actions.set_widgets(widgets)


class App:
    def __init__(self, client, args, session_pid=None, restart=None):
        self.client, self.args, self.session_pid = client, args, session_pid
        self.state = {}
        self.lang = args.lang or 'en'
        self.root = tk.Tk()
        self.root.title(t('app.title', self.lang))
        self.root.configure(bg=BG)
        self.fit_window()
        th.init(self.root)
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)
        self.catalog = None
        self.images = {}
        self.screen = None
        self.token = 0                                    # changes with every screen: stale callbacks see it
        self.jobs = []
        self.sig = None
        self.sigs = {}
        self.files = {}
        self.chat_rows = []
        self.chat_drawn = None
        self.logs = []
        self.advanced_open = False
        self.dialog = None
        self.question = None
        self.error_shown = None
        self.error_window = None
        self.overlay = None
        self.overlay_hwnd = None
        self.pads_text = None
        self.pads_seen = set()
        self.picker = None
        self.potara_picker = None
        self.settings_live = None
        self.pending = {}
        self.spin_sent = {}
        self.ready_wanted = None
        self.alive = True
        self.lobby_layout = None
        self.lobby_mid = None
        self.lobby_panels = []
        self.rename_var = None
        self.self_name = None
        self.adv = None
        # Typed text outlives screens, rebuilds and language switches.
        self.name_var = tk.StringVar(master=self.root)
        self.addr_var = tk.StringVar(master=self.root)
        self.password_var = tk.StringVar(master=self.root)
        self.chat_var = tk.StringVar(master=self.root)
        self.synced = {}
        self.listed_var = None
        self.recent_hosts = self.read_recent()
        self.shots = Path(args.shot_dir) if args.shot_dir else None
        steps = kit_lobby_console.bot_steps(args)
        if args.lobby_script:
            steps += json.loads(Path(args.lobby_script).read_text(encoding='utf-8'))
        self.script = kit_lobby_console.Script(steps, self.send, self.shot, self.log,
                                               out=self.shots / 'script.json' if self.shots else None,
                                               ui=self.ui_step) if steps else None
        self.bot = kit_lobby_console.AutoBot(args, self.send) if (args.auto_ready or args.auto_vote) else None
        self.build_frame()
        watch_resizes(self.root)
        add_relayout_hook(self.root, self.relayout)
        self.root.bind_all('<MouseWheel>', self.scroll, add='+')
        self.root.bind_all('<Button-4>', self.scroll, add='+')
        self.root.bind_all('<Button-5>', self.scroll, add='+')
        self.root.after(30, self.pump)
        self.root.after(500, self.poll_pads)
        self.send('files')

    # ---- the window's fixed frame: title band, scrolling middle, pinned actions and chat -------------------------------------
    def build_frame(self):
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        top = tk.Frame(root, bg=BG)
        top.grid(row=0, column=0, sticky='ew')
        top.columnconfigure(0, weight=1)
        self.banner = th.Banner(top, bg=BG, size=18)
        self.banner.grid(row=0, column=0, sticky='ew', pady=(px(8), 0))
        self.head_tools = tk.Frame(top, bg=BG)
        self.head_tools.grid(row=0, column=1, sticky='e', padx=px(12), pady=(px(8), 0))
        self.head_line = wrap_label(tk.Label(top, text='', bg=BG, fg=th.DIM, font=font(10)))
        self.head_line.grid(row=1, column=0, columnspan=2, sticky='ew', padx=px(22), pady=(px(2), px(4)))
        self.head_line.grid_remove()
        self.top_band = top
        self.viewport = ScrollPanel(root)
        self.viewport.grid(row=1, column=0, sticky='nsew')
        self.body = self.viewport.content
        self.foot = tk.Frame(root, bg=BG)
        self.foot.grid(row=2, column=0, sticky='ew', padx=px(16), pady=(px(4), px(6)))
        self.foot.columnconfigure(0, weight=1)
        self.chat_area = tk.Frame(root, bg=BG)
        self.chat_area.grid(row=3, column=0, sticky='ew', padx=px(16), pady=(0, px(10)))
        self.chat_area.columnconfigure(1, weight=1)
        self.chat_text = tk.Text(self.chat_area, height=3, width=30, bg=th.INSET, fg=th.INK, relief='flat',
                                 font=font(9), wrap='word', state='disabled', highlightthickness=1,
                                 highlightbackground=th.EDGE_DARK, padx=px(6), pady=px(3), cursor='arrow')
        self.chat_text.tag_configure('who', foreground=th.GOLD, font=font(9, True))
        self.chat_text.tag_configure('at', foreground=th.FAINT)
        self.chat_text.grid(row=0, column=0, columnspan=3, sticky='ew')
        self.chat_label = tk.Label(self.chat_area, text='', bg=BG, fg=th.GOLD, font=heading(9))
        self.chat_label.grid(row=1, column=0, sticky='w', pady=(px(4), 0))
        self.chat_entry = ttk.Entry(self.chat_area, textvariable=self.chat_var, width=20, font=font(10))
        self.chat_entry.grid(row=1, column=1, sticky='ew', padx=px(6), pady=(px(4), 0))
        self.chat_entry.bind('<Return>', lambda e: self.send_chat())
        self.chat_send = self.button(self.chat_area, '', self.send_chat, kind='plain')
        self.chat_send.grid(row=1, column=2, sticky='e', pady=(px(4), 0))
        self.chat_area.grid_remove()
        self.retext_frame()

    def set_head_line(self, text):
        """The subtitle under the title band; the row disappears while there is nothing to say."""
        configure_changed(self.head_line, text=text or '')
        if text and not self.head_line.winfo_manager():
            self.head_line.grid()
        elif not text and self.head_line.winfo_manager():
            self.head_line.grid_remove()

    def retext_frame(self):
        configure_changed(self.chat_label, text=self.T('lobby.chat'))
        configure_changed(self.chat_send, text=self.T('lobby.send'))

    def show_chat(self, on):
        if on and not self.chat_area.winfo_manager():
            self.chat_area.grid()
            self.draw_chat()
        elif not on and self.chat_area.winfo_manager():
            self.chat_area.grid_remove()

    # ---- plumbing ---------------------------------------------------------------------------------------------------
    def fit_window(self):
        global S, PZ
        try:
            dpi = float(self.root.winfo_fpixels('1i'))
        except (tk.TclError, ValueError):
            dpi = 96.0
        scale = max(1.0, dpi / 96.0)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w, h = DESIGN[0] * scale, DESIGN[1] * scale
        fit = min(1.0, sw * 0.97 / w, (sh - 70 * scale) / h)
        if fit < 1.0:
            try:
                self.root.tk.call('tk', 'scaling', float(self.root.tk.call('tk', 'scaling')) * fit)
            except tk.TclError:
                pass
        S = th.S = scale * fit
        PZ = 2 if S >= 1.75 else 1
        if self.args.ui_geometry:
            self.root.geometry(self.args.ui_geometry)
        else:
            self.root.geometry(f'{int(w * fit)}x{int(h * fit)}+{px(10)}+{px(10)}')
        self.root.minsize(min(px(640), sw - 40), min(px(360), sh - 80))

    def resize(self, event=None):
        """Kept for callers of the old window: a resize now only restarts the settle timer."""
        relayout_soon(self.root)

    def relayout(self):
        """Once the window size has settled: the lobby's columns, panel heights and chat lines."""
        if not self.alive:
            return
        self.viewport.schedule()
        if self.screen == 'lobby' and self.lobby_mid is not None and self.lobby_mid.winfo_exists():
            self.arrange_lobby()
        if self.screen in ('prep', 'fight'):
            self.fit_versus()
        lines = 4 if self.root.winfo_height() >= px(760) else 3 if self.root.winfo_height() >= px(620) else 2
        if int(self.chat_text.cget('height')) != lines:
            self.chat_text.configure(height=lines)
            self.chat_text.see('end')

    def scroll(self, event):
        units = -1 if getattr(event, 'num', None) == 4 or getattr(event, 'delta', 0) > 0 else 1
        widget = event.widget
        if isinstance(widget, str):                         # a Tk-internal widget (combobox list): not ours
            return None
        start = widget
        while widget is not None:
            if isinstance(widget, ScrollPanel):
                first, last = widget.canvas.yview()
                if (units < 0 and first > 0.001) or (units > 0 and last < 0.999):
                    widget.canvas.yview_scroll(units * 3, 'units')
                    return 'break'
            # The portrait and stage pickers have their own scrolling canvas.
            elif isinstance(widget, tk.Canvas) and widget.cget('yscrollcommand'):
                first, last = widget.yview()
                if (units < 0 and first > 0.001) or (units > 0 and last < 0.999):
                    widget.yview_scroll(units * 3, 'units')
                    return 'break'
            elif isinstance(widget, (tk.Text, tk.Listbox)):
                return None                                  # they scroll themselves
            widget = getattr(widget, 'master', None)
        # Anywhere else in the main window (title band, pinned actions): the page scrolls.
        try:
            if start.winfo_toplevel() is self.root and self.viewport.winfo_exists():
                first, last = self.viewport.canvas.yview()
                if (units < 0 and first > 0.001) or (units > 0 and last < 0.999):
                    self.viewport.canvas.yview_scroll(units * 3, 'units')
                    return 'break'
        except (tk.TclError, AttributeError):
            pass
        return None

    def style(self):
        """The ttk look (kit_theme.style_ttk); kept as a method for callers of the old window."""
        th.style_ttk(self.root)

    def send(self, cmd, **fields):
        self.client.send(cmd, **fields)

    def once(self, key, action, hold=1.2):
        """Run a one-shot command once: repeated clicks within `hold` seconds (or until the screen changes) are ignored."""
        now = time.monotonic()
        until, token = self.pending.get(key, (0.0, None))
        if until > now and token == self.token:
            return False
        self.pending[key] = (now + hold, self.token)
        action()
        return True

    def later(self, ms, fn):
        """A timer of this screen: dropped when the screen changes or the window closes."""
        token = self.token

        def run():
            if self.alive and token == self.token:
                fn()
        try:
            job = self.root.after(ms, run)
        except tk.TclError:
            return None
        self.jobs.append(job)
        return job

    def log(self, text):
        self.logs.append(text)
        del self.logs[:-200]
        try:
            print(text, flush=True)
        except (OSError, ValueError):
            pass

    def T(self, key, **args):
        return t(key, self.lang, **args)

    def pump(self):
        again = True
        try:
            for ev in self.client.poll(0):
                kind = ev.get('ev')
                if kind in ('state', 'snapshot'):
                    if kind == 'snapshot':
                        self.chat_rows = list(ev.get('chat') or [])
                        self.logs += ev.get('logs') or []
                    try:
                        self.on_state(ev['state'])
                    except tk.TclError:
                        if not self.alive:
                            raise
                        self.ui_error()
                        self.state = ev['state']
                    except Exception:  # noqa: BLE001 - a drawing bug must not stop the window (and its script)
                        self.ui_error()
                        self.state = ev['state']
                elif kind == 'log':
                    self.log(ev.get('text', ''))
                elif kind == 'chat':
                    self.chat_rows.append(ev)
                    self.draw_chat()
                elif kind == 'files':
                    self.files = ev
                    if self.screen == 'start':
                        self.draw_files()
                elif kind in ('bye', 'replaced'):
                    again = False
                    self.close_window()
                    return
            if self.client.closed:
                again = False
                self.lost()
                return
            if self.script:
                self.script.feed(self.state)
                self.script.tick()
            if self.bot:
                self.bot.tick(self.state)
            self.tick_screen()
        except tk.TclError:
            if not self.alive:
                again = False
                return
            self.ui_error()
        except Exception:  # noqa: BLE001 - logged; the window keeps following the session
            self.ui_error()
        finally:
            if again and self.alive:
                try:
                    self.root.after(40, self.pump)
                except tk.TclError:
                    pass

    def ui_error(self):
        import traceback
        self.log('UI ERROR: ' + traceback.format_exc())
        self.screen = None                                     # the next packet (or recover()) rebuilds the screen
        if not getattr(self, 'recovering', False) and self.alive:
            self.recovering = True
            try:
                self.root.after(600, self.recover)
            except tk.TclError:
                pass

    def recover(self):
        """Rebuild the screen from the last state after a drawing error (at most every 0.6 s, never in a loop)."""
        self.recovering = False
        if not self.alive or self.screen is not None or not self.state:
            return
        try:
            self.on_state(self.state)
        except Exception:  # noqa: BLE001 - logged; the next packet tries again
            import traceback
            self.log('UI ERROR (rebuild): ' + traceback.format_exc())
            self.screen = None

    def lost(self):
        if self.screen == 'lost':
            return
        self.go('lost')
        self.later(8000, self.close_window)

    def build_lost(self):
        self.header(self.body, self.T('app.title'), '')
        box = th.Panel(self.body, edge=th.DANGER)
        box.pack(fill='x', padx=px(16), pady=px(24))
        wrap_label(tk.Label(box.inner, text=self.T('session.lost'), bg=th.PANEL, fg=th.RED,
                            font=heading(14))).pack(fill='x', padx=px(18), pady=px(22))
        row = Flow(self.foot, bg=BG, align='right')
        row.grid(row=0, column=0, sticky='ew')
        row.set_widgets([self.button(row, self.T('close'), self.close_window, kind='primary', big=True)])

    def update_lost(self):
        pass

    def close_window(self):
        if not self.alive:
            return
        self.alive = False
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def on_close(self):
        self.send('quit')
        try:
            self.root.withdraw()
            self.root.after(300, self.close_window)
        except tk.TclError:
            pass

    # ---- state -> screens ------------------------------------------------------------------------------------------------
    def on_state(self, state):
        self.state = state
        if not state.get('error'):
            self.error_shown = None
            if self.error_window is not None:
                self.close_error()
        if state.get('lang') and state['lang'] != self.lang:
            self.lang = state['lang']
            self.root.title(t('app.title', self.lang))
            self.retext_frame()
            self.screen = None
        cat = state.get('catalog')
        if cat and (self.catalog is None or self.catalog.c.get('dir') != cat['dir']):
            try:
                self.catalog = kit_catalog.View(kit_catalog.read_dir(cat['dir']))
            except (OSError, ValueError):
                self.catalog = None
        screen = SCREENS.get(state.get('phase') or 'start', 'start')
        if screen != self.screen:
            self.go(screen)
        getattr(self, 'update_' + screen)()
        self.update_overlay()
        self.show_error()

    def go(self, screen):
        """The only screen change: close this screen's dialogs and questions, drop its timers, build the next one."""
        self.token += 1
        self.clear()
        self.screen = screen
        self.sig = None
        try:
            getattr(self, 'build_' + screen)()
        except Exception:
            self.screen = None
            raise
        self.show_chat(screen in CHAT_SCREENS)
        relayout_soon(self.root, 10)

    def clear(self):
        self.close_dialog()
        if self.question is not None:
            try:
                self.question.destroy()
            except tk.TclError:
                pass
            self.question = None
        for job in self.jobs:
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass
        self.jobs = []
        self.lobby_layout = None
        self.lobby_mid = None
        self.lobby_panels = []
        self.sigs = {}
        self.settings_live = None
        self.vs = None
        for parent in (self.body, self.foot, self.head_tools):
            for w in parent.winfo_children():
                w.destroy()
        self.viewport.canvas.yview_moveto(0)

    def tick_screen(self):
        if self.screen == 'results':
            self.update_results()

    def image(self, rel, zoom=1):
        if not rel:                                          # (an older catalog has no picture for this one)
            return None
        zoom *= PZ
        key = (rel, zoom)
        if key not in self.images and self.catalog:
            try:
                im = tk.PhotoImage(master=self.root, data=(Path(self.catalog.c['dir']) / rel).read_bytes())
                self.images[key] = im.zoom(zoom, zoom) if zoom > 1 else im
            except (OSError, tk.TclError):
                self.images[key] = None
        return self.images.get(key)

    def small(self, rel):
        """A portrait at half size (the lobby's people and the scoreboards)."""
        if not rel:
            return None
        key = (rel, 'small')
        if key not in self.images and self.catalog:
            try:
                im = tk.PhotoImage(master=self.root, data=(Path(self.catalog.c['dir']) / rel).read_bytes())
                self.images[key] = im.subsample(2, 2) if PZ == 1 else im
            except (OSError, tk.TclError):
                self.images[key] = None
        return self.images.get(key)

    def portrait(self, cid, zoom=1):
        if self.catalog and cid in self.catalog.chars:
            return self.image(self.catalog.chars[cid]['portrait'], zoom)
        return None

    def header(self, parent, title, line=None):
        """This screen's title band and subtitle; returns the area at the top right for this screen's tools."""
        self.banner.set(title)
        self.set_head_line(line or '')
        tk.Label(self.head_tools, text=self.T('kit', version=self.state.get('kit', '')), bg=BG, fg=th.FAINT,
                 font=font(8)).pack(side='right')
        return self.head_tools

    def button(self, parent, text, command, color=None, fg=None, big=False, state='normal', width=None, kind=None):
        """A game button. kind: primary (gold), secondary (blue), go (green), danger (red), plain, ghost, chip."""
        if kind is None:
            kind = {GOLD: 'primary', th.GOLD: 'primary', th.AMBER: 'primary', BLUE: 'secondary', RED: 'danger',
                    GREEN: 'go'}.get(color, 'plain')
        b = tk.Button(parent, text=text, command=command, state=state)
        th.style_button(b, kind, big=big)
        if width:
            b.configure(width=width)
        return b

    def chip(self, parent, text, chosen, command, enabled=True):
        b = tk.Button(parent, text=text, command=command)
        th.style_button(b, 'chip_on' if chosen else 'chip')
        b.configure(font=font(9, True))
        if chosen:
            b.configure(highlightbackground='#fff0a0')
        if chosen:
            b._ttm['off'] = th.GOLD                            # the host's choice stays lit for everybody
            b.configure(disabledforeground=th.DARK_INK)
        th.enable(b, enabled)
        return b

    def panel_title(self, parent, text, bg=None):
        label = wrap_label(tk.Label(parent, text=text, bg=bg or th.PANEL, fg=th.GOLD, font=heading(11)))
        label.pack(fill='x', padx=px(10), pady=(px(8), px(4)))
        return label

    def confirm(self, text):
        """Yes/No in the window's style. A Yes given after the screen changed (the question became stale) is a No."""
        token = self.token
        win = self.toplevel(self.T('app.title'), modal=True)
        self.question = win
        answer = {'yes': False}
        box = th.Panel(win)
        box.pack(fill='both', expand=True, padx=px(10), pady=px(10))
        wrap_label(tk.Label(box.inner, text=text, bg=th.PANEL, fg=th.INK, font=font(11, True))).pack(
            fill='x', padx=px(18), pady=(px(18), px(12)))
        row = Flow(box.inner, bg=th.PANEL, align='right')
        row.pack(fill='x', padx=px(12), pady=(0, px(12)))

        def finish(value):
            answer['yes'] = value
            try:
                win.destroy()
            except tk.TclError:
                pass
        yes = self.button(row, self.T('yes'), lambda: finish(True), kind='danger')
        no = self.button(row, self.T('no'), lambda: finish(False), kind='plain')
        row.set_widgets([no, yes])
        win.bind('<Escape>', lambda e: finish(False))
        win.bind('<Return>', lambda e: finish(True))
        win.geometry(f'{px(460)}x{px(190)}')
        self.place_dialog(win, px(460), px(190))
        no.focus_set()
        try:
            win.grab_set()
        except tk.TclError:
            pass
        self.root.wait_window(win)
        if self.question is win:
            self.question = None
        return answer['yes'] and token == self.token and self.alive

    def toplevel(self, title, modal=False):
        """A dialog window in the theme: transient, watched for resizes, Escape closes it."""
        win = tk.Toplevel(self.root, bg=BG)
        win.title(title)
        if self.root.winfo_viewable():                       # (a withdrawn window would hide its dialogs)
            win.transient(self.root)
        watch_resizes(win)
        if not modal:
            win.bind('<Escape>', lambda e: self.close_dialog() if self.dialog is win else win.destroy())
        return win

    def place_dialog(self, win, width=None, height=None, dx=30, dy=30, size=True):
        """Put a dialog near the window but always inside the screen (size=False: keep its natural size)."""
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        win.update_idletasks()
        width = min(width or win.winfo_reqwidth(), sw - px(20))
        height = min(height or win.winfo_reqheight(), sh - px(60))
        x = max(0, min(self.root.winfo_rootx() + px(dx), sw - width - px(10)))
        y = max(0, min(self.root.winfo_rooty() + px(dy), sh - height - px(50)))
        win.geometry(f'{int(width)}x{int(height)}+{int(x)}+{int(y)}' if size else f'+{int(x)}+{int(y)}')

    def lobby(self):
        return self.state.get('lobby') or {}

    def match(self):
        return self.lobby().get('match') or {}

    def members(self):
        return {m['id']: m for m in self.lobby().get('members') or []}

    def me(self):
        return self.state.get('me')

    def is_host(self):
        return self.state.get('role') == 'host'

    def my_slot(self):
        return kit_lobby_console.slot_of(self.match(), self.me())

    def name_of(self, ident):
        return (self.members().get(ident) or {}).get('name') or ''

    def sync_var(self, name, var, value):
        """Show the session's value unless the player has typed something else since it was last shown."""
        value = value or ''
        if var.get() == self.synced.get(name, ''):
            if var.get() != value:
                var.set(value)
        self.synced[name] = value

    @staticmethod
    def read_recent():
        try:
            recent = json.loads((kit_paths.DATA / 'recent-hosts.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return []
        return [s for s in recent if isinstance(s, str)] if isinstance(recent, list) else []

    # ---- S1 start --------------------------------------------------------------------------------------------------------
    def build_start(self):
        st = self.state
        cfg = st.get('settings') or {}
        tools = self.header(self.body, self.T('s1.title'), self.T('s1.subtitle'))
        lang = self.button(tools, self.T('lang.other'), self.toggle_lang, kind='chip')
        lang.pack(side='right', padx=(0, px(12)))
        self.sync_var('name', self.name_var, (st.get('profile') or {}).get('name'))
        self.sync_var('addr', self.addr_var, cfg.get('host_address') or (self.recent_hosts[0] if self.recent_hosts
                                                                         else ''))
        main = th.Panel(self.body)
        main.pack(fill='x', padx=px(16), pady=px(6))
        inner = main.inner
        row = tk.Frame(inner, bg=th.PANEL)
        row.pack(fill='x', padx=px(16), pady=(px(14), px(6)))
        wrap_label(tk.Label(row, text=self.T('s1.name'), bg=th.PANEL, fg=th.GOLD,
                            font=heading(11))).pack(fill='x')
        self.name_entry = ttk.Entry(row, textvariable=self.name_var, width=20, font=font(12))
        self.name_entry.pack(fill='x', pady=px(4))
        wrap_label(tk.Label(row, text=self.T('s1.name_hint'), bg=th.PANEL, fg=th.DIM,
                            font=font(9))).pack(fill='x')
        actions = Flow(inner, bg=th.PANEL)
        actions.pack(fill='x', padx=px(14), pady=px(10))
        self.host_button = actions.add(self.button(actions, self.T('s1.host'), self.do_host, kind='primary', big=True))
        self.join_button = actions.add(self.button(actions, self.T('s1.join'), self.do_join, kind='secondary',
                                                   big=True))
        self.room_name_var = tk.StringVar(value=cfg.get('room_name') or '')
        self.directory_var = tk.StringVar(value=cfg.get('directory') or '')
        self.listed_var = None
        if SERVER_BROWSER_VISIBLE:
            online = tk.Frame(inner, bg=th.PANEL)
            online.pack(fill='x', padx=px(14), pady=px(4))
            tk.Label(online, text=self.T('browser.password'), bg=th.PANEL, fg=th.INK, font=font(9)).pack(side='left')
            ttk.Entry(online, textvariable=self.password_var, show='*', width=18).pack(side='left', padx=px(6))
            self.listed_var = tk.BooleanVar(value=bool(cfg.get('listed')))
            ttk.Checkbutton(online, text=self.T('browser.listed'), variable=self.listed_var).pack(side='left',
                                                                                                padx=px(8))
            tk.Label(online, text=self.T('browser.name'), bg=th.PANEL, fg=th.INK, font=font(9)).pack(side='left')
            ttk.Entry(online, textvariable=self.room_name_var, width=20).pack(side='left', padx=px(6))
            self.button(online, self.T('browser.open'), self.open_browser).pack(side='left', padx=px(6))
            directory = tk.Frame(inner, bg=th.PANEL)
            directory.pack(fill='x', padx=px(14))
            tk.Label(directory, text=self.T('browser.directory'), bg=th.PANEL, fg=th.DIM,
                     font=font(8)).pack(side='left')
            ttk.Entry(directory, textvariable=self.directory_var, width=46).pack(side='left', padx=px(6))
        sep = tk.Frame(inner, bg=th.EDGE_DARK, height=1)
        sep.pack(fill='x', padx=px(14), pady=(px(4), px(8)))
        self.files_box = tk.Frame(inner, bg=th.PANEL)
        self.files_box.pack(fill='x', padx=px(16), pady=(0, px(4)))
        self.files_sig = None
        self.draw_files()
        pads = tk.Frame(inner, bg=th.PANEL)
        pads.pack(fill='x', padx=px(16), pady=(px(6), px(14)))
        pads.columnconfigure(1, weight=1)
        tk.Label(pads, text=self.T('s1.controllers'), bg=th.PANEL, fg=th.GOLD, font=heading(10)).grid(
            row=0, column=0, sticky='nw')
        self.pads_label = wrap_label(tk.Label(pads, text='', bg=th.PANEL, fg=th.DIM, font=font(10)))
        self.pads_label.grid(row=0, column=1, sticky='ew', padx=px(8))
        self.pads_text = None
        adv = tk.Frame(self.body, bg=BG)
        adv.pack(fill='x', padx=px(16))
        self.adv_toggle = tk.Button(adv, text='', command=self.toggle_adv, bg=BG, fg=th.DIM, relief='flat', bd=0,
                                    activebackground=BG, activeforeground=th.GOLD, font=heading(10), cursor='hand2',
                                    highlightthickness=0)
        self.adv_toggle.pack(anchor='w', pady=(px(4), 0))
        self.adv_box = tk.Frame(adv, bg=BG)
        self.draw_advanced(self.adv_box)
        self.draw_inputs(pads)
        self.show_advanced(self.advanced_open)
        self.start_status = wrap_label(tk.Label(self.body, text='', bg=BG, fg=th.DIM, font=font(10)))
        self.start_status.pack(fill='x', padx=px(18), pady=px(6))

    def show_advanced(self, on):
        """Open or close Advanced in place (nothing else on the screen is rebuilt, so nothing typed is lost)."""
        self.advanced_open = bool(on)
        if getattr(self, 'adv_toggle', None) is None or not self.adv_toggle.winfo_exists():
            return
        self.adv_toggle.configure(text=('▾  ' if self.advanced_open else '▸  ') + self.T('s1.advanced'))
        if self.advanced_open and not self.adv_box.winfo_manager():
            self.adv_box.pack(fill='x', pady=(px(2), px(4)))
        elif not self.advanced_open and self.adv_box.winfo_manager():
            self.adv_box.pack_forget()
        relayout_soon(self.root, 10)

    def draw_files(self):
        box = getattr(self, 'files_box', None)
        if box is None or not box.winfo_exists():
            return
        sig = (str(box), json.dumps([self.files, self.lang], sort_keys=True))
        if sig == getattr(self, 'files_sig', None):
            return
        self.files_sig = sig
        for w in box.winfo_children():
            w.destroy()
        f = self.files or {}
        if f.get('integrated'):                             # kit 2.1: everything comes from the installation
            wrap_label(tk.Label(box, text='✓  ' + self.T('s1.integrated'), bg=th.PANEL, fg=th.GREEN,
                                font=font(10, True))).pack(fill='x')
            for key, field in (('s1.iso', 'iso'), ('s1.bios', 'bios')):
                wrap_label(tk.Label(box, text=f'    {self.T(key)}  {elide(f.get(field)) if f.get(field) else self.T("s1.not_chosen")}',
                                    bg=th.PANEL, fg=th.INK, font=font(9))).pack(fill='x')
            return
        if not f.get('iso') or not f.get('bios'):
            wrap_label(tk.Label(box, text=self.T('s1.first_run'), bg=th.PANEL, fg=th.GOLD,
                                font=font(10, True))).pack(fill='x')
        lines = [('s1.iso', 'iso'), ('s1.bios', 'bios'), ('s1.install', 'install')]
        grid = tk.Frame(box, bg=th.PANEL)
        grid.pack(fill='x')
        grid.columnconfigure(1, weight=1)
        r = 0
        for key, field in lines:
            tk.Label(grid, text=self.T(key), bg=th.PANEL, fg=th.INK, font=font(10, True), anchor='w').grid(
                row=r, column=0, sticky='w', pady=px(2))
            value = elide(f.get(field)) if f.get(field) else self.T('s1.not_chosen')
            wrap_label(tk.Label(grid, text=value, bg=th.PANEL, fg=th.INK if f.get(field) else th.DIM,
                                font=font(9))).grid(row=r, column=1, sticky='ew', padx=px(8))
            self.button(grid, self.T('s1.choose'), lambda fld=field: self.choose_file(fld)).grid(
                row=r, column=2, sticky='e', pady=px(2))
            r += 1
            text, color = '', th.DIM
            if field == 'iso' and f.get('iso'):
                region = f.get('iso_region')
                if f.get('iso_error'):
                    text, color = f['iso_error'].get('title_' + self.lang) or f['iso_error'].get('code'), th.RED
                elif region is None and f.get('iso_serial'):
                    text, color = self.T('s1.iso_ok', serial=f.get('iso_serial')), th.GREEN
                elif region in ('europe', 'japan'):
                    text, color = self.T('s1.iso_' + region), th.RED
                elif region == 'other':
                    text, color = self.T('s1.iso_other', serial=f.get('iso_serial')), th.RED
            if field == 'install':
                info = f.get('install_info') or {}
                if info.get('refused'):
                    why = self.T('why.refused_code', detail=info['refused_regions']) if info.get('refused_regions') \
                        else self.T('why.refused')
                    text, color = self.T('s1.install_refused', why=why), th.RED
                elif info.get('error'):
                    why = info.get('error_es') if self.lang == 'es' and info.get('error_es') else info.get('error')
                    text, color = self.T('s1.install_refused', why=why), th.RED
                elif info.get('build') == 'known':
                    text, color = self.T('s1.install_ok', version=info.get('version')), th.GREEN
                elif info.get('build') == 'candidate':
                    text, color = self.T('s1.install_candidate', version=info.get('version')), th.GOLD
            if text:
                wrap_label(tk.Label(grid, text=text, bg=th.PANEL, fg=color, font=font(9, True))).grid(
                    row=r, column=0, columnspan=3, sticky='ew', padx=(px(16), 0))
                r += 1
            if field == 'install':
                for found in (f.get('install_found') or [])[:3]:
                    wrap_label(tk.Label(grid, text=self.T('s1.install_found', path=elide(found['root'], 70),
                                                          version=found.get('version') or '?'),
                                        bg=th.PANEL, fg=th.INK if found.get('ok') else th.DIM, font=font(9))).grid(
                        row=r, column=0, columnspan=2, sticky='ew', padx=(px(16), 0))
                    if found.get('ok'):
                        self.button(grid, self.T('s1.use'),
                                    lambda r_=found['root']: (self.send('setup', install=r_), self.send('files'))).grid(
                            row=r, column=2, sticky='e')
                    r += 1

    def choose_file(self, field):
        token = self.token
        if field == 'install':
            path = filedialog.askdirectory(title=self.T('s1.install'), parent=self.root)
        else:
            types = [('ISO', '*.iso'), ('*', '*.*')] if field == 'iso' else [('BIOS', '*.bin'), ('*', '*.*')]
            path = filedialog.askopenfilename(title=self.T('s1.' + field), filetypes=types, parent=self.root)
        if path and self.alive and token == self.token:
            self.send('setup', **{field: path})
            self.send('files')

    def toggle_lang(self):
        self.lang = 'es' if self.lang == 'en' else 'en'
        self.send('setup', lang=self.lang)
        self.retext_frame()
        self.screen = None
        self.on_state(dict(self.state, lang=self.lang))

    def toggle_adv(self):
        self.show_advanced(not self.advanced_open)

    def draw_advanced(self, parent):
        cfg = self.state.get('settings') or {}
        box = th.Panel(parent)
        box.pack(fill='x', pady=px(4))
        grid = box.inner
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        if self.adv is None:                                   # the drafts outlive the screen and language switches
            self.adv = dict(port=tk.StringVar(master=self.root, value=str(cfg.get('port') or 47400)),
                            delay=tk.StringVar(master=self.root, value=str(cfg.get('delay') or '')),
                            renderer=tk.StringVar(master=self.root, value=cfg.get('renderer') or 'default'),
                            pad=tk.StringVar(master=self.root),
                            fullscreen=tk.BooleanVar(master=self.root, value=bool(cfg.get('fullscreen'))))
            self.adv_pad = cfg.get('pad') or 'SDL-0'
        pads = ['SDL-0', 'SDL-1', 'keyboard']
        self.pad_names = {self.T('adv.pad.' + p): p for p in pads}
        self.adv['pad'].set(self.T('adv.pad.' + self.adv_pad))
        rows = [('adv.port', 'port'), ('adv.delay', 'delay')]
        for i, (key, field) in enumerate(rows):
            wrap_label(tk.Label(grid, text=self.T(key), bg=th.PANEL, fg=th.INK, font=font(9))).grid(
                row=i, column=0, sticky='ew', padx=px(12), pady=px(3))
            ttk.Entry(grid, textvariable=self.adv[field], width=1).grid(row=i, column=1, sticky='ew', padx=px(8),
                                                                         pady=px(2))
        wrap_label(tk.Label(grid, text=self.T('adv.renderer'), bg=th.PANEL, fg=th.INK,
                            font=font(9))).grid(row=2, column=0, sticky='ew', padx=px(12), pady=px(3))
        ttk.Combobox(grid, textvariable=self.adv['renderer'], state='readonly', width=1,
                     values=['default', 'auto', 'd3d11', 'd3d12', 'vulkan', 'opengl', 'software']).grid(
            row=2, column=1, sticky='ew', padx=px(8), pady=px(2))
        ttk.Checkbutton(grid, text=self.T('adv.fullscreen'), variable=self.adv['fullscreen']).grid(
            row=4, column=0, columnspan=2, sticky='w', padx=px(12), pady=px(3))
        wrap_label(tk.Label(grid, text=self.T('adv.local'), bg=th.PANEL, fg=th.DIM,
                            font=font(8))).grid(row=5, column=0, columnspan=2, sticky='ew', padx=px(12))
        if not SERVER_BROWSER_VISIBLE:
            wrap_label(tk.Label(grid, text=self.T('browser.password'), bg=th.PANEL, fg=th.INK,
                                font=font(9))).grid(row=6, column=0, sticky='ew', padx=px(12), pady=(px(3), px(10)))
            ttk.Entry(grid, textvariable=self.password_var, show='*', width=1).grid(
                row=6, column=1, sticky='ew', padx=px(8), pady=(px(2), px(10)))

    def draw_inputs(self, parent):
        row=tk.Frame(parent,bg=th.PANEL)
        row.grid(row=1,column=0,columnspan=2,sticky='ew',pady=(px(10),0))
        row.columnconfigure(1,weight=1)
        wrap_label(tk.Label(row,text=self.T('adv.pad'),bg=th.PANEL,fg=th.GOLD,font=heading(10))).grid(
            row=0,column=0,sticky='w',padx=(0,px(8)))
        box=ttk.Combobox(row,textvariable=self.adv['pad'],state='readonly',width=1,values=list(self.pad_names))
        box.grid(row=0,column=1,sticky='ew')
        def chosen(_):
            self.adv_pad=self.pad_names.get(self.adv['pad'].get(),'SDL-0')
            fields=dict(pad=self.adv_pad)
            if self.adv_pad=='keyboard' and 'keyboard_bindings' not in (self.state.get('settings') or {}):
                import keyboard_bindings
                fields['keyboard_bindings']=dict(keyboard_bindings.DEFAULT)
            self.send('setup',**fields)
        box.bind('<<ComboboxSelected>>',chosen)
        controls=tk.Frame(row,bg=th.PANEL);controls.grid(row=1,column=0,columnspan=2,sticky='ew',pady=px(6))
        self.button(controls,self.T('input.bindings'),self.edit_keyboard).pack(anchor='w')
        wrap_label(tk.Label(controls,text=self.T('input.hint'),bg=th.PANEL,fg=th.DIM,font=font(9))).pack(fill='x',pady=px(3))

    def edit_keyboard(self):
        import keyboard_bindings as kb
        import keyboard_controls_ui as ui
        settings=self.state.get('settings') or {}
        current=settings.get('keyboard_bindings')
        fallback=kb.LEGACY_ONLINE if settings.get('pad')=='keyboard' else kb.DEFAULT
        try:current=kb.validate(current,online=True) if current is not None else dict(fallback)
        except ValueError:current=dict(kb.DEFAULT)
        result=ui.show(self.root,current,language=self.lang,online=True)
        if result is not None:
            self.adv_pad='keyboard';self.adv['pad'].set(self.T('adv.pad.keyboard'))
            self.send('setup',pad='keyboard',keyboard_bindings=result)

    def save_start_fields(self):
        fields = {}
        fields['name'] = self.name_var.get().strip()[:16]
        fields['host_address'] = self.addr_var.get().strip()
        self.synced['name'] = fields['name'] if fields['name'] else self.synced.get('name', '')
        if self.listed_var is not None:
            fields.update(listed=bool(self.listed_var.get()), room_name=self.room_name_var.get().strip()[:64],
                          directory=self.directory_var.get().strip())
        elif not SERVER_BROWSER_VISIBLE:
            fields['listed'] = False
        if self.adv:
            fields['pad']=self.pad_names.get(self.adv['pad'].get(),'SDL-0')
        if self.advanced_open and self.adv:
            try:
                fields['port'] = int(self.adv['port'].get() or 47400)
            except ValueError:
                pass
            d = self.adv['delay'].get().strip()
            fields['delay'] = int(d) if d.isdigit() else None
            fields['renderer'] = self.adv['renderer'].get()
            fields['pad'] = self.pad_names.get(self.adv['pad'].get(), 'SDL-0')
            fields['fullscreen'] = bool(self.adv['fullscreen'].get())
        if fields:
            self.send('setup', **fields)
        return fields

    def do_host(self):
        def host():
            self.save_start_fields()
            self.send('host', password=self.password_var.get())
            self.password_var.set('')
        self.once('host', host, hold=2.0)

    def do_join(self):
        self.close_dialog()
        win = self.toplevel(self.T('s1.join'))
        self.dialog = win
        win.resizable(False, False)
        box = th.Panel(win, edge=th.EDGE)
        box.pack(fill='both', expand=True, padx=px(10), pady=px(10))
        inner = box.inner
        tk.Label(inner, text=self.T('s1.address'), bg=th.PANEL, fg=th.GOLD, font=heading(11)).pack(
            anchor='w', padx=px(16), pady=(px(14), px(4)))
        address = tk.StringVar(master=win, value=self.addr_var.get())
        entry = ttk.Combobox(inner, textvariable=address, values=self.recent_hosts, width=42, font=font(11))
        entry.pack(fill='x', padx=px(16))
        tk.Label(inner, text=self.T('join.address_hint'), bg=th.PANEL, fg=th.DIM, font=font(9),
                 wraplength=px(470), justify='left').pack(anchor='w', padx=px(16), pady=(px(6), px(12)))
        tk.Label(inner, text=self.T('browser.password'), bg=th.PANEL, fg=th.INK, font=font(9, True)).pack(
            anchor='w', padx=px(16))
        password = tk.StringVar(master=win, value=self.password_var.get())
        ttk.Entry(inner, textvariable=password, show='*', width=24).pack(anchor='w', padx=px(16), pady=(px(4), px(6)))
        status = tk.Label(inner, text='', bg=th.PANEL, fg=th.RED, font=font(9, True), wraplength=px(470),
                          justify='left')
        status.pack(anchor='w', padx=px(16))

        def submit():
            raw = address.get().strip()
            if not raw:
                status.configure(text=self.T('join.address_required'))
                entry.focus_set()
                return
            try:
                host, port = kit_net.address(raw, (self.state.get('settings') or {}).get('port') or 47400)
                if not host or any(c.isspace() or c in '/\\' for c in host) or not 1 <= int(port) <= 65535:
                    raise ValueError('Invalid host address')
            except (ValueError, TypeError):
                status.configure(text=self.T('join.address_invalid'))
                entry.focus_set()
                return
            secret = password.get()
            password.set('')

            def join():
                self.addr_var.set(raw)
                self.save_start_fields()
                self.password_var.set('')
                self.close_dialog()
                self.send('join', address=raw, password=secret)
            self.once('join', join, hold=2.0)

        buttons = Flow(inner, bg=th.PANEL)
        buttons.pack(fill='x', padx=px(12), pady=(px(10), px(14)))
        cancel = self.button(buttons, self.T('cancel'), self.close_dialog)
        go = self.button(buttons, self.T('s1.join'), submit, kind='secondary', big=True)
        buttons.set_widgets([cancel, go], right=[go])
        win.protocol('WM_DELETE_WINDOW', self.close_dialog)
        win.bind('<Return>', lambda e: submit())
        entry.configure(width=36)
        self.place_dialog(win, None, None, dx=70, dy=100, size=False)
        try:
            win.grab_set()
        except tk.TclError:
            pass
        entry.focus_set()
        entry.selection_range(0, 'end')

    def open_browser(self):
        if not SERVER_BROWSER_VISIBLE:
            return
        self.close_dialog()
        win = self.toplevel(self.T('browser.open'))
        self.dialog = win
        win.geometry('850x410')
        rows = {}
        columns = ('name', 'disc', 'players', 'phase', 'password', 'source')
        tree = ttk.Treeview(win, columns=columns, show='headings', height=11)
        for key in columns:
            tree.heading(key, text=self.T('browser.protected' if key == 'password' else 'browser.' + key))
            tree.column(key, width=120 if key != 'name' else 190)
        tree.pack(fill='both', expand=True, padx=10, pady=10)
        status = tk.Label(win, text=self.T('browser.searching'), bg=BG, fg=th.DIM, wraplength=800)
        status.pack(fill='x', padx=10)
        result = queue.Queue()

        def refresh():
            status.configure(text=self.T('browser.searching'))
            url = self.directory_var.get().strip()

            def work():
                try:
                    result.put(kit_browser.discover(url))
                except Exception as error:  # noqa: BLE001
                    result.put(dict(rooms=[], errors=[str(error)]))
            threading.Thread(target=work, daemon=True).start()

        def poll():
            if not self.alive or not win.winfo_exists():
                return
            try:
                found = result.get_nowait()
            except queue.Empty:
                pass
            else:
                tree.delete(*tree.get_children())
                rows.clear()
                for i, room in enumerate(found['rooms']):
                    rows[str(i)] = room
                    tree.insert('', 'end', iid=str(i), values=(room['name'], room['adapter'], room['players'],
                                room['phase'], self.T('yes' if room['password'] else 'no'), room['source']))
                status.configure(text='; '.join(found['errors']) or self.T('browser.found', n=len(rows)))
            win.after(100, poll)

        def choose():
            selection = tree.selection()
            if selection:
                room = rows[selection[0]]
                self.addr_var.set(f"{room['host']}:{room['port']}")
                self.close_dialog()
                self.start_status.configure(text=self.T('browser.chosen'))
        buttons = tk.Frame(win, bg=BG)
        buttons.pack(fill='x', padx=10, pady=8)
        self.button(buttons, self.T('browser.refresh'), refresh).pack(side='left')
        self.button(buttons, self.T('browser.choose'), choose, kind='primary').pack(side='right')
        refresh()
        poll()

    def poll_pads(self):
        try:
            if self.screen == 'start' and getattr(self, 'pads_label', None) and self.pads_label.winfo_exists():
                pads = kit_win.xinput_pads()
                if not pads:
                    text = self.T('s1.no_pad')
                else:
                    names = ', '.join(self.T('s1.pad_n', n=i + 1) for i, _ in pads)
                    text = self.T('s1.pads', count=len(pads), list=names)
                    pressed = [i for i, p in pads if p]
                    if pressed:
                        self.pads_seen = set(pressed)
                    text += '   ' + (self.T('s1.pad_pressed', n=min(self.pads_seen) + 1) if self.pads_seen else
                                     self.T('s1.press_any'))
                if text != self.pads_text:
                    self.pads_text = text
                    self.pads_label.configure(text=text)
        except tk.TclError:
            pass
        if self.alive:
            try:
                self.root.after(250, self.poll_pads)
            except tk.TclError:
                pass

    def update_start(self):
        st = self.state
        self.sync_var('name', self.name_var, (st.get('profile') or {}).get('name'))
        self.sync_var('addr', self.addr_var, (st.get('settings') or {}).get('host_address') or
                      (self.recent_hosts[0] if self.recent_hosts else ''))
        status = getattr(self, 'start_status', None)
        if status is not None and status.winfo_exists():
            notice = st.get('notice')
            text = kit_text.notice_text(notice['key'], self.lang, notice.get('args')) if notice else \
                (self.logs[-1] if self.logs else '')
            configure_changed(status, text=text)

    # ---- S2 check --------------------------------------------------------------------------------------------------------
    def build_check(self):
        self.header(self.body, self.T('s2.title'))
        panel = th.Panel(self.body)
        panel.pack(fill='x', padx=px(16), pady=px(10))
        self.check_box = panel.inner
        self.check_sig = None
        self.check_note = wrap_label(tk.Label(self.body, text='', bg=BG, fg=th.DIM, font=font(10)))
        self.check_note.pack(fill='x', padx=px(18))

    def update_check(self):
        checks = self.state.get('checks') or []
        sig = (str(self.check_box), self.lang, tuple(item['key'] for item in checks))
        if sig != getattr(self, 'check_sig', None):
            self.check_sig = sig
            for w in self.check_box.winfo_children():
                w.destroy()
            self.check_rows = []
            for item in checks:
                row = tk.Frame(self.check_box, bg=th.PANEL)
                row.pack(fill='x', padx=px(14), pady=px(4))
                row.columnconfigure(1, weight=1)
                mark = tk.Label(row, bg=th.PANEL, font=heading(12), width=2, anchor='n')
                mark.grid(row=0, column=0, rowspan=2, sticky='n')
                title = wrap_label(tk.Label(row, bg=th.PANEL, font=font(10, True)))
                title.grid(row=0, column=1, sticky='ew')
                note = wrap_label(tk.Label(row, bg=th.PANEL, fg=th.DIM, font=font(9)))
                note.grid(row=1, column=1, sticky='ew')
                title.mark = mark
                self.check_rows.append((title, note))
        for item, (title, note) in zip(checks, self.check_rows):
            ok = item.get('ok')
            mark, color = ('✓', th.GREEN) if ok else ('…', th.GOLD) if ok is None else ('✗', th.RED)
            configure_changed(title.mark, text=mark, fg=color)
            configure_changed(title, text=self.T('check.' + item['key']), fg=th.INK if ok else color)
            configure_changed(note, text=item.get('note') or '')
        settings = self.state.get('settings') or {}
        if self.state.get('role') == 'guest' and settings.get('host_address'):
            configure_changed(self.check_note, text=self.T('s2.connecting', address=settings['host_address']))
        else:
            configure_changed(self.check_note, text=self.logs[-1] if self.logs else '')

    # ---- S3 the room ------------------------------------------------------------------------------------------------------
    def build_lobby(self):
        self.header(self.body, self.T('room.title'))
        self.build_bottom(self.foot)
        mid = tk.Frame(self.body, bg=BG)
        mid.pack(fill='both', expand=True, padx=px(12), pady=(px(2), px(6)))
        self.lobby_mid = mid
        self.lobby_panels = [ScrollPanel(mid, bg=th.PANEL, height=430, edge=th.EDGE) for _ in range(3)]
        self.people, self.teams, self.rules_box = [panel.content for panel in self.lobby_panels]
        self.team_rows = {}
        self.arrange_lobby()
        self.sigs = {}
        mid.bind('<Configure>', lambda e: self.arrange_lobby() if self.lobby_mid is mid else None, add='+')

    def arrange_lobby(self):
        width = self.body.winfo_width()
        if self.lobby_layout is None:
            wide = width >= px(WIDE_ON) or (width <= 1 and self.root.winfo_width() >= px(WIDE_ON))
        elif self.lobby_layout:
            wide = width >= px(WIDE_OFF)                     # hysteresis: a scroll bar appearing cannot flip it back
        else:
            wide = width >= px(WIDE_ON)
        if wide == self.lobby_layout:
            return
        self.lobby_layout = wide
        mid = self.lobby_mid
        for i in range(3):
            mid.columnconfigure(i, weight=0, minsize=0, uniform='')
            mid.rowconfigure(i, weight=0)
        for panel in self.lobby_panels:
            panel.grid_forget()
            panel.auto_height = not wide
            panel.canvas.yview_moveto(0)
            panel.schedule()
        if wide:
            for i, (panel, weight) in enumerate(zip(self.lobby_panels, (18, 54, 28))):
                mid.columnconfigure(i, weight=weight, uniform='lobby')
                panel.canvas.configure(height=px(240))          # a minimum: the row stretches them to the window
                panel.grid(row=0, column=i, sticky='nsew', padx=px(4))
            mid.rowconfigure(0, weight=1)
        else:
            mid.columnconfigure(0, weight=1)
            # Keep the fighters first when the side panels no longer fit.
            for row, index in enumerate((1, 0, 2)):
                self.lobby_panels[index].grid(row=row, column=0, sticky='ew', padx=px(4), pady=px(4))

    def fit_lobby_panels(self):
        """Kept for callers of the old window: in the wide layout the panels now stretch with the window by
        themselves (their minimum height is set once in arrange_lobby)."""

    def build_bottom(self, parent):
        foot = tk.Frame(parent, bg=BG)
        foot.grid(row=0, column=0, sticky='ew')
        foot.columnconfigure(0, weight=1)
        self.notice_label = wrap_label(tk.Label(foot, text='', bg=BG, fg=th.GOLD, font=font(10, True)))
        self.notice_label.grid(row=0, column=0, sticky='ew')
        collapsing(self.notice_label)
        self.start_hint = wrap_label(tk.Label(foot, text='', bg=BG, fg=th.DIM, font=font(9)))
        self.start_hint.grid(row=1, column=0, sticky='ew')
        collapsing(self.start_hint)
        buttons = Flow(foot, bg=BG)
        buttons.grid(row=2, column=0, sticky='ew', pady=(px(4), 0))
        self.lobby_buttons = buttons
        self.ready_button = self.button(buttons, self.T('room.ready_btn'), self.toggle_ready, kind='primary', big=True,
                                        width=14)
        self.start_button = self.button(buttons, self.T('room.start'),
                                        lambda: self.once('start', lambda: self.send('start'), hold=2.0),
                                        kind='go', big=True, width=16)
        self.watch_button = self.button(buttons, self.T('room.spectate'),
                                        lambda: self.once('unclaim', lambda: self.send('unclaim')), big=True)
        self.leave_button = self.button(buttons, self.T('room.close') if self.is_host() else self.T('room.leave'),
                                        self.leave, kind='danger', big=True)
        self.back_hub_button = self.button(buttons, self.T('room.back_hub'),
                                           lambda: self.once('back_hub', lambda: self.send('back_to_hub')))

    def send_chat(self):
        text = self.chat_var.get().strip()
        if text:
            self.send('chat', text=text)
            self.chat_var.set('')

    def draw_chat(self):
        """Append new chat lines (a full redraw only when the history was replaced, e.g. on re-attaching)."""
        box = self.chat_text
        if not box.winfo_exists() or not self.chat_area.winfo_manager():
            return
        rows = self.chat_rows[-30:]
        drawn = self.chat_drawn or []
        if rows == drawn:
            return
        common = 0
        if drawn and len(rows) >= len(drawn) and rows[:len(drawn)] == drawn:
            common = len(drawn)
        elif drawn and drawn[len(drawn) - len(rows) + 1:] == rows[:-1] and len(rows) == len(drawn):
            common = -1                                         # the window of the last 30 moved by one
        box.configure(state='normal')
        if common == 0:
            box.delete('1.0', 'end')
            new = rows
        elif common == -1:
            box.delete('1.0', '2.0')
            new = rows[-1:]
        else:
            new = rows[common:]
        for row in new:
            if box.index('end-1c') != '1.0':
                box.insert('end', '\n')
            box.insert('end', f'{row.get("at", "")} ', ('at',))
            box.insert('end', f'{row.get("who")}: ', ('who',))
            box.insert('end', f'{row.get("text")}')
        box.see('end')
        box.configure(state='disabled')
        self.chat_drawn = list(rows)

    def update_lobby(self):
        st, lob = self.state, self.lobby()
        if not lob:
            self.set_head_line(self.T('lobby.waiting_lobby'))
            return
        if self.is_host():
            jw = st.get('joinwith') or {}
            addr = (jw.get('main') or '?') + ('' if jw.get('default_port', True) else f':{jw.get("port")}')
            line = self.T('lobby.joinwith', addr=addr)
        else:
            host = st.get('host') or {}
            d = lob.get('delay_hint')
            line = self.T('lobby.connected', name=self.name_of(1) or host.get('name') or '') + \
                (f' · {host.get("rtt_ms")} ms' if host.get('rtt_ms') is not None else '')
            if d:
                line += f' · {self.T("adv.delay").split(" (")[0]} {d}'
        self.set_head_line(line)
        members, match = self.members(), self.match()
        identity = [self.me(), self.is_host(), self.lang]
        catalog = self.catalog.c.get('dir') if self.catalog else None
        # Ping, Ready, preparation telemetry and roster edits update existing widgets. Only a change of a panel's
        # structure (members, team sizes, mode, role, language) rebuilds it.
        teams = match.get('teams') or []
        parts = dict(people=json.dumps([sorted(members), identity]),
                     teams=json.dumps([[len(team) for team in teams], match.get('mode'), match.get('type'),
                                       lob.get('phase'), identity, catalog]),
                     rules=json.dumps([lob.get('phase'), identity, st.get('services'), catalog]))
        if parts['people'] != self.sigs.get('people'):
            self.sigs['people'] = parts['people']
            self.draw_people()
        if parts['teams'] != self.sigs.get('teams'):
            self.sigs['teams'] = parts['teams']
            self.draw_teams()
        self.update_teams()
        if parts['rules'] != self.sigs.get('rules'):
            self.sigs['rules'] = parts['rules']
            self.draw_rules()
        self.update_rules()
        self.update_people()
        configure_changed(self.warm_label, text=self.warm_text(lob.get('warm') or {}))
        self.update_buttons()
        self.show_notice()
        self.refresh_pickers()

    def show_notice(self):
        label = getattr(self, 'notice_label', None)
        if label is None or not label.winfo_exists():
            return
        notice = self.lobby().get('notice') or self.state.get('notice')
        text = kit_text.notice_text(notice['key'], self.lang, notice.get('args')) if notice and notice.get('key') \
            else ''
        if self.lobby().get('phase') == 'fight' and self.state.get('phase') == 'lobby':
            text = self.T('room.in_match')
        configure_changed(label, text=text)

    def draw_people(self):
        old_name = getattr(self, 'self_name', None)
        draft = self.rename_var.get() if getattr(self, 'rename_var', None) is not None else None
        for w in self.people.winfo_children():
            w.destroy()
        self.panel_title(self.people, self.T('room.members'))
        self.member_labels = {}
        for ident, m in sorted(self.members().items()):
            box = tk.Frame(self.people, bg=th.CARD, highlightthickness=1,
                           highlightbackground=th.GOLD if ident == self.me() else th.CARD)
            box.pack(fill='x', padx=px(8), pady=px(2))
            name = wrap_label(tk.Label(box, bg=th.CARD, fg=th.GOLD if ident == self.me() else th.INK,
                                       font=font(10, True)))
            name.pack(fill='x', padx=px(6), pady=(px(3), 0))
            line = tk.Frame(box, bg=th.CARD)
            line.pack(fill='x', padx=px(6), pady=(0, px(3)))
            status = wrap_label(tk.Label(line, bg=th.CARD, fg=th.DIM, font=font(9)))
            status.pack(fill='x')
            self.member_labels[ident] = name, status
            if self.is_host() and ident != 1:
                kick = tk.Button(line, text=self.T('room.kick'), bg=th.CARD, fg=th.RED, relief='flat', bd=0,
                                 activebackground=th.CARD_HI, activeforeground=th.RED, font=font(8, True),
                                 cursor='hand2', highlightthickness=0,
                                 command=lambda i=ident: self.once(('kick', i), lambda: self.send('kick', member=i)))
                kick.pack(anchor='e')
        row = tk.Frame(self.people, bg=th.PANEL)
        row.pack(fill='x', padx=px(8), pady=(px(10), px(8)))
        wrap_label(tk.Label(row, text=self.T('room.your_name'), bg=th.PANEL, fg=th.DIM,
                            font=font(8, True))).pack(fill='x')
        self.self_name = self.name_of(self.me())
        if self.rename_var is None:
            self.rename_var = tk.StringVar(master=self.root)
        self.rename_var.set(draft if draft is not None and old_name == self.self_name else self.self_name)
        entry = ttk.Entry(row, textvariable=self.rename_var, width=16)
        self.rename_entry = entry
        entry.pack(fill='x', pady=px(2))
        entry.bind('<Return>', lambda e: self.rename())
        self.button(row, self.T('room.rename'), self.rename).pack(anchor='w', pady=px(2))

    def update_people(self):
        for ident, m in self.members().items():
            if ident not in self.member_labels:
                continue
            name, status = self.member_labels[ident]
            tags = ([self.T('room.host_tag')] if ident == 1 else [])
            if ident == self.me():
                tags.append(self.T('room.you_tag'))
            configure_changed(name, text=m['name'] + (f' ({", ".join(tags)})' if tags else ''))
            at = kit_lobby_console.slot_of(self.match(), ident)
            role = self.T('room.playing_fighter', team=at[0] + 1, index=at[1] + 1) if at else self.T('room.watching')
            extra = [self.T('room.ready')] if at and m.get('ready') else []
            if m.get('rtt_ms') is not None:
                extra.append(f'{m["rtt_ms"]} ms')
            configure_changed(status, text=role + ('  ·  ' + '  ·  '.join(extra) if extra else ''),
                              fg=th.GREEN if at and m.get('ready') else th.DIM)
        current = self.name_of(self.me())
        if self.self_name != current:
            if self.rename_var.get() == self.self_name:
                self.rename_var.set(current)
            self.self_name = current

    def rename(self):
        name = self.rename_var.get().strip()[:16]
        if name and name != self.name_of(self.me()):
            self.send('name', name=name)

    def draw_teams(self):
        """The teams panel's structure (rows per team, mode and start buttons); update_teams() fills the rows."""
        for w in self.teams.winfo_children():
            w.destroy()
        self.team_rows = {}
        match = self.match()
        host = self.is_host() and self.lobby().get('phase') == 'lobby'
        start = Flow(self.teams, bg=th.PANEL)
        start.pack(fill='x', padx=px(10), pady=(px(8), 0))
        start.add(tk.Label(start, text=self.T('room.start_in'), bg=th.PANEL, fg=th.GOLD, font=heading(10)))
        for value, label in (('versus', self.T('room.start_menu')), ('hub', self.T('room.start_hub'))):
            chosen = match.get('type', 'versus') == value
            start.add(self.chip(start, label, chosen, lambda v=value: self.send('start_in', value=v), enabled=host))
        if match.get('type') == 'hub':
            wrap_label(tk.Label(self.teams, text=self.T('room.hub_why'), bg=th.PANEL, fg=th.DIM,
                                font=font(8))).pack(fill='x', padx=px(10))
        top = Flow(self.teams, bg=th.PANEL)
        top.pack(fill='x', padx=px(10), pady=(px(4), px(2)))
        top.add(tk.Label(top, text=self.T('room.mode'), bg=th.PANEL, fg=th.GOLD, font=heading(10)))
        for value, label in (('teams', self.T('room.mode.teams')), ('ffa', self.T('room.mode.ffa'))):
            chosen = match.get('mode') == value
            top.add(self.chip(top, label, chosen, lambda v=value: self.send('mode', mode=v),
                              enabled=host and match.get('type') != 'hub'))
        top.add(tk.Label(top, text=self.T('room.mode.three'), bg=th.PANEL, fg=th.FAINT, font=font(9, True)))
        wrap_label(tk.Label(self.teams, text=self.T('room.mode.three_why'), bg=th.PANEL, fg=th.DIM,
                            font=font(8))).pack(fill='x', padx=px(10))
        cols = tk.Frame(self.teams, bg=th.PANEL)
        cols.pack(fill='both', expand=True, padx=px(6), pady=px(4))
        teams = match.get('teams') or []
        columns = []
        self.team_titles = []
        for t_, team in enumerate(teams):
            col = tk.Frame(cols, bg=th.PANEL)
            columns.append(col)
            head = tk.Frame(col, bg=th.TEAM_DIM[t_ % 2])
            head.pack(fill='x', pady=(px(2), px(2)))
            title = tk.Label(head, text='', bg=th.TEAM_DIM[t_ % 2], fg=th.INK, font=heading(11))
            title.pack(side='left', padx=px(8), pady=px(3))
            self.team_titles.append(title)
            if host:
                sizes = [len(x) for x in teams]
                for delta, sign in ((1, '+'), (-1, '−')):
                    new = list(sizes)
                    new[t_] += delta                  # edit only this column
                    ok = all(1 <= n <= 5 for n in new) and sum(new) <= 10
                    b = tk.Button(head, text=sign, width=2, command=lambda n=new: self.send('sizes', sizes=n))
                    th.style_button(b, 'plain', parent_bg=th.TEAM_DIM[t_ % 2])
                    b.configure(font=font(10, True), padx=px(4), pady=0)
                    th.enable(b, ok)
                    b.pack(side='right', padx=px(2), pady=px(2))
            for i, _ in enumerate(team):
                self.team_rows[(t_, i)] = FighterRow(self, col, t_, i, host)
        layout = [None]

        def arrange_teams(width):
            if layout[0] is None:
                side_by_side = width >= px(620)
            else:
                side_by_side = width >= px(600) if layout[0] else width >= px(620)
            if layout[0] == side_by_side:
                return
            layout[0] = side_by_side
            for i, col in enumerate(columns):
                col.grid_forget()
                cols.columnconfigure(i, weight=1 if side_by_side or i == 0 else 0,
                                     uniform='teams' if side_by_side else '')
                col.grid(row=0 if side_by_side else i, column=i if side_by_side else 0,
                         sticky='nsew', padx=px(4), pady=px(2))
        cols.bind('<Configure>', lambda event: arrange_teams(event.width))
        # Give the first layout something to size before its Configure event.
        arrange_teams(self.teams.winfo_width())
        foot = Flow(self.teams, bg=th.PANEL)
        foot.pack(fill='x', padx=px(10), pady=(px(2), px(4)))
        self.total_label = tk.Label(foot, text='', bg=th.PANEL, fg=th.DIM, font=font(9))
        foot.add(self.total_label)
        if host:
            foot.add(self.button(foot, self.T('room.random_cpu'),
                                 lambda: self.once('random', lambda: self.send('random'), hold=0.6)))
        self.slot_hint = wrap_label(tk.Label(self.teams, text='', bg=th.PANEL, fg=th.DIM, font=font(8)))
        self.slot_hint.pack(fill='x', padx=px(10), pady=(0, px(8)))

    def update_teams(self):
        match = self.match()
        teams = match.get('teams') or []
        members = self.members()
        host = self.is_host() and self.lobby().get('phase') == 'lobby'
        lobby_open = self.lobby().get('phase') == 'lobby'
        for t_, team in enumerate(teams):
            if t_ < len(self.team_titles):
                configure_changed(self.team_titles[t_], text=self.T('room.team' if match.get('mode') == 'teams'
                                                                    else 'room.column', n=t_ + 1))
            for i, f in enumerate(team):
                row = self.team_rows.get((t_, i))
                if row is not None:
                    row.update(f, members, host, lobby_open)
        total = sum(len(team) for team in teams)
        configure_changed(self.total_label, text=self.T('room.total', n=total))
        humans = sum(1 for team in teams for f in team if f.get('owner') is not None)
        configure_changed(self.slot_hint, text=self.T('room.slot_hint21', n=humans))

    def fighter_row(self, parent, team, index, f, members, host):
        """One fighter row (kept for callers of the old window; the room uses FighterRow and updates it in place)."""
        row = FighterRow(self, parent, team, index, host)
        row.update(f, members, host, self.lobby().get('phase') == 'lobby')
        return row

    def draw_rules(self):
        """The rules panel's structure; update_rules() shows the values (no rebuild when the host changes a rule)."""
        for w in self.rules_box.winfo_children():
            w.destroy()
        host = self.is_host() and self.lobby().get('phase') == 'lobby'
        self.rule_widgets = {}
        self.panel_title(self.rules_box, self.T('room.rules'))
        grid = tk.Frame(self.rules_box, bg=th.PANEL)
        grid.pack(fill='x', padx=px(10))
        grid.columnconfigure(0, weight=1)
        wrap_label(tk.Label(grid, text=self.T('rule.stage'), bg=th.PANEL, fg=th.INK,
                            font=font(9, True))).grid(row=0, column=0, sticky='ew', pady=px(2))
        srow = tk.Frame(grid, bg=th.CARD, highlightthickness=1, highlightbackground=th.EDGE_DARK)
        srow.grid(row=1, column=0, sticky='ew')
        srow.columnconfigure(1, weight=1)
        self.stage_pic = th.portrait_frame(srow, None, bg=th.INSET)
        self.stage_pic.grid(row=0, column=0, rowspan=2, padx=px(4), pady=px(4), sticky='nw')
        self.stage_label = wrap_label(tk.Label(srow, text='', bg=th.CARD, fg=th.INK, font=font(10, True)))
        self.stage_label.grid(row=0, column=1, sticky='ew', padx=px(4), pady=(px(6), 0))
        if host:
            choose = self.button(srow, self.T('rule.choose_stage'), self.open_stage_picker, kind='secondary')
            choose.grid(row=1, column=1, sticky='nw', padx=px(4), pady=px(4))
            for w in (self.stage_pic, self.stage_pic.picture):
                w.bind('<Button-1>', lambda e: self.open_stage_picker(), add='+')
                w.configure(cursor='hand2')
        r = 1
        tracks = [self.T('rule.random')] + [self.T('room.track', n=n + 1) for n in range(24)]
        self.rule_combo(grid, r, 'room.music', tracks, tracks[0], host,
                        lambda v: self.send('rules', bgm='random' if v == tracks[0] else tracks.index(v) - 1),
                        name='bgm')
        self.rule_widgets['bgm'].values = tracks
        r += 1
        times = [kit_text.TIME_LABELS[x] for x in (60, 90, 180, 240, 0)]
        self.rule_combo(grid, r, 'rule.time', times, '240', host,
                        lambda v: self.native_changed('time', {b: a for a, b in kit_text.TIME_LABELS.items()}[v]),
                        name='time')
        r += 1
        self.rule_combo(grid, r, 'rule.com', list(kit_text.COM_LABELS), kit_text.COM_LABELS[2], host,
                        lambda v: self.native_changed('com', kit_text.COM_LABELS.index(v)), name='com')
        r += 1
        refs = list(kit_text.REFEREES[self.lang])
        self.rule_combo(grid, r, 'rule.referee', refs, refs[2], host,
                        lambda v: self.native_changed('referee', refs.index(v)), name='referee')
        self.rule_widgets['referee'].values = refs
        r += 1
        self.rule_combo(grid, r, 'rule.destructible', list(kit_text.ON_OFF), 'ON', host,
                        lambda v: self.native_changed('destructible', v == 'ON'), name='destructible')
        r += 1
        policies = [self.T('room.load_cancel'), self.T('room.load_drop')]
        self.rule_combo(grid, r, 'room.load_policy', policies, policies[0], host,
                        lambda v: self.send('load_policy', drop=v == policies[1]), name='policy')
        self.rule_widgets['policy'].values = policies
        wrap_label(tk.Label(self.rules_box, text=self.T('room.load_policy_note'), bg=th.PANEL, fg=th.DIM,
                            font=font(8))).pack(fill='x', padx=px(10), pady=(px(4), 0))
        row = Flow(self.rules_box, bg=th.PANEL)
        row.pack(fill='x', padx=px(10), pady=(px(8), px(2)))
        self.rules_button = self.button(row, self.T('room.rules_show'), self.open_rules, kind='secondary')
        row.add(self.rules_button)
        self.display_button = self.button(row, self.T('room.display'), self.open_display, kind='secondary')
        row.add(self.display_button)
        wrap_label(tk.Label(self.rules_box, text=self.T('room.rules_note'), bg=th.PANEL, fg=th.DIM,
                            font=font(8))).pack(fill='x', padx=px(10), pady=(px(4), 0))
        allowed = self.state.get('services') or []
        self.service_vars = {}
        for k in ('cpu_transform', 'fusion_timer', 'body_change'):
            if k not in allowed:
                continue
            var = tk.BooleanVar(master=self.root, value=False)
            box = ttk.Checkbutton(self.rules_box, text=self.T('room.service_on', name=self.T('room.service.' + k)),
                                  variable=var, state='normal' if host else 'disabled',
                                  command=lambda k=k, v=var: self.send('rules', services={k: bool(v.get())}))
            box.pack(anchor='w', padx=px(10), pady=(px(4), 0))
            self.service_vars[k] = var
        locked = [self.T('room.service.' + k) for k in ('cpu_transform', 'fusion_timer', 'body_change')
                  if k not in allowed]
        if locked:
            wrap_label(tk.Label(self.rules_box, text=self.T('room.services', list=', '.join(locked)), bg=th.PANEL,
                                fg=th.DIM, font=font(8))).pack(fill='x', padx=px(10), pady=(px(4), 0))
        wrap_label(tk.Label(self.rules_box, text=self.T('room.camera'), bg=th.PANEL, fg=th.GOLD,
                            font=heading(9))).pack(fill='x', padx=px(10), pady=(px(8), 0))
        self.camera_label = wrap_label(tk.Label(self.rules_box, text='', bg=th.PANEL, fg=th.INK, font=font(8)))
        self.camera_label.pack(fill='x', padx=px(10))
        self.controls_label = wrap_label(tk.Label(self.rules_box, text='', bg=th.PANEL, fg=th.INK, font=font(8)))
        self.controls_label.pack(fill='x', padx=px(10), pady=(px(6), 0))
        self.warm_label = wrap_label(tk.Label(self.rules_box, bg=th.PANEL, fg=th.DIM, font=font(8)))
        self.warm_label.pack(fill='x', padx=px(10), pady=(px(6), px(8)))

    def update_rules(self):
        match = self.match()
        stage = match.get('stage')
        name = self.T('rule.random') if stage == 'random' else (self.catalog.stage_name(stage) if self.catalog
                                                                else str(stage))
        configure_changed(self.stage_label, text=name)
        rel = None
        if self.catalog:
            rel = self.catalog.c.get('random_thumb') if stage == 'random' else \
                (self.catalog.stages.get(stage) or {}).get('thumb')
        img = self.image(rel) if rel else None
        if self.stage_pic.picture.cget('image') != (str(img) if img else ''):
            if img:
                self.stage_pic.picture.configure(image=img, text='', width=0, height=0)
            else:
                self.stage_pic.picture.configure(image='', text='?', width=4, height=2)
        bgm = match.get('bgm')
        tracks = self.rule_widgets['bgm'].values
        native = match.get('native') or {}
        refs = self.rule_widgets['referee'].values
        policies = self.rule_widgets['policy'].values
        drop = (self.lobby().get('room') or {}).get('drop_load_failures') is True
        shown = dict(bgm=tracks[0] if bgm == 'random' else tracks[min(len(tracks) - 1, (bgm or 0) + 1)],
                     time=kit_text.TIME_LABELS.get(native.get('time'), '240'),
                     com=kit_text.COM_LABELS[native.get('com', 2)],
                     referee=refs[native.get('referee', 2)],
                     destructible='ON' if native.get('destructible', True) else 'OFF',
                     policy=policies[int(drop)])
        for key, value in shown.items():
            box = self.rule_widgets[key]
            if box.get() != value:
                box.set(value)
        services = match.get('services') or {}
        for k, var in self.service_vars.items():
            if bool(var.get()) != bool(services.get(k)):
                var.set(bool(services.get(k)))
        values = kit_settings.gameplay_expand(match.get('gameplay'))
        camera = ' · '.join(f'{kit_settings.label(k, self.lang)}: {kit_settings.value_text(k, values[k], self.lang)}'
                            for k in kit_settings.CAMERA if k in values and k in kit_settings.FIELDS)
        configure_changed(self.camera_label, text=camera)
        configure_changed(self.controls_label, text=self.T('lobby.controls_title') + ': ' +
                          controls_card(values, self.lang))

    def warm_text(self, warm):
        why = t(warm['why_key'], self.lang, detail=warm.get('why') or '') if warm.get('why_key') else \
            (warm.get('why') or '')
        return {'warming': self.T('lobby.warming', t=f'{int(warm.get("eta_s") or 0)} s'),
                'warm': self.T('lobby.warm_ready'), 'suspended': self.T('lobby.warm_ready'),
                'busy': self.T('lobby.warm_busy'), 'failed': self.T('lobby.warm_failed', why=why),
                'refused': self.T('lobby.warm_refused', why=why), 'cold': self.T('lobby.warm_cold')}.get(
            warm.get('state'), '')

    def rule_combo(self, grid, r, key, values, current, editable, on_change, name=None):
        wrap_label(tk.Label(grid, text=self.T(key), bg=th.PANEL, fg=th.INK,
                            font=font(9, True))).grid(row=r * 2, column=0, sticky='ew', pady=(px(6), px(2)))
        box = ttk.Combobox(grid, values=values, width=1, state='readonly' if editable else 'disabled')
        box.set(current)
        box.grid(row=r * 2 + 1, column=0, sticky='ew')
        box.bind('<<ComboboxSelected>>', lambda e: on_change(box.get()))
        if name:
            self.rule_widgets[name] = box
        return box

    def native_changed(self, field, value):
        native = dict(self.match().get('native') or {})
        native[field] = value
        self.send('rules', native=native)

    def update_buttons(self):
        lob = self.lobby()
        in_lobby = lob.get('phase') == 'lobby' and self.state.get('phase') == 'lobby'
        slot = self.my_slot()
        me = self.members().get(self.me()) or {}
        buttons, right = [], []
        hint = ''
        if self.is_host() and in_lobby and lob.get('return_to_hub'):
            buttons.append(self.back_hub_button)
        buttons.insert(0, self.leave_button)
        if self.is_host():
            players = [k for k in self.members() if kit_lobby_console.slot_of(self.match(), k) is not None and k != 1]
            waiting = [self.name_of(k) for k in players if not self.members()[k].get('ready')]
            if slot is not None:
                buttons.append(self.watch_button)
                right.append(self.watch_button)
            buttons.append(self.start_button)
            right.append(self.start_button)
            th.enable(self.start_button, in_lobby and not waiting)
            hint = self.T('room.start_wait', names=', '.join(waiting)) if waiting else self.T('room.start_hint')
        elif slot is not None:
            buttons += [self.watch_button, self.ready_button]
            right += [self.watch_button, self.ready_button]
            ready = bool(me.get('ready'))
            if self.ready_wanted is not None and (self.ready_wanted[0] == ready or
                                                  time.monotonic() > self.ready_wanted[1]):
                self.ready_wanted = None                       # the session answered (or never will)
            configure_changed(self.ready_button, text=self.T('room.unready_btn' if ready else 'room.ready_btn'))
            th.set_kind(self.ready_button, 'plain' if ready else 'primary')
            th.enable(self.ready_button, in_lobby and self.ready_wanted is None)
        else:
            hint = self.T('room.watch_hint')
        self.lobby_buttons.set_widgets(buttons, right=right)
        if SERVER_BROWSER_VISIBLE and self.state.get('listing_warning'):
            hint += '\n' + self.T('browser.warning', reason=self.state['listing_warning'])
        configure_changed(self.start_hint, text=hint)

    def toggle_ready(self):
        if self.ready_wanted is not None and time.monotonic() < self.ready_wanted[1]:
            return                                             # one Ready at a time: wait for the session's answer
        me = self.members().get(self.me()) or {}
        want = not me.get('ready')
        self.ready_wanted = (want, time.monotonic() + 2.0)
        self.send('ready', ready=want)

    def ask(self, text):
        """True when the player said Yes and the screen is still the one the question was about."""
        token, screen = self.token, self.screen
        answer = self.confirm(text)
        return bool(answer) and self.alive and token == self.token and screen == self.screen

    def leave(self):
        if self.ask(self.T('room.close_confirm') if self.is_host() else self.T('lobby.leave_confirm')):
            self.once('leave', lambda: self.send('leave'), hold=2.0)

    # ---- dialogs ---------------------------------------------------------------------------------------------------------
    def close_dialog(self):
        if self.dialog is not None:
            try:
                self.dialog.destroy()
            except tk.TclError:
                pass
            self.dialog = None
        self.settings_live = None

    def open_rules(self):
        """The match's gameplay rules (the host edits them; everybody else sees them, kept current), in the mod's
        own words."""
        self.close_dialog()
        host = self.is_host() and self.lobby().get('phase') == 'lobby'
        values = kit_settings.gameplay_expand(self.match().get('gameplay'))
        win, body = self.settings_window(self.T('room.rules_show'), self.T('room.rules') +
                                         ('' if host else '  ' + self.T('lobby.set_by_host')))
        wrap_label(tk.Label(body, text=self.T('room.rules_note'), bg=BG, fg=th.DIM, font=font(8))).pack(
            fill='x', padx=px(4))
        wrap_label(tk.Label(body, text=self.T('room.camera') + ' - ' + self.T('room.camera_why'),
                            bg=BG, fg=th.GOLD, font=font(8))).pack(fill='x', padx=px(4))
        self.settings_grid(body, kit_settings.groups(), values, host, lambda k, v: self.send('rules', gameplay={k: v}))
        wrap_label(tk.Label(body, text=self.T('lobby.forced'), bg=BG, fg=th.DIM, font=font(8))).pack(fill='x',
                                                                                                     padx=px(4))
        self.settings_live = dict(win=win, kind='rules', editable=host)

    def open_display(self):
        """This PC's own display settings (never sent: applied to this PC's copy of every match)."""
        self.close_dialog()
        values = kit_settings.default_local()
        values.update((self.state.get('profile') or {}).get('local') or {})
        win, body = self.settings_window(self.T('room.display'), self.T('room.display'))
        wrap_label(tk.Label(body, text=self.T('room.display_note'), bg=BG, fg=th.DIM, font=font(8))).pack(
            fill='x', padx=px(4))
        self.settings_grid(body, kit_settings.local_groups(), values, True,
                           lambda k, v: self.send('local', values={k: v}))

    def settings_window(self, title, heading_text):
        """Keep Close visible and long settings pages inside the available screen."""
        win = self.toplevel(title)
        self.dialog = win
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        max_width, max_height = max(1, sw - px(40)), max(1, sh - px(80))
        width, height = min(px(1200), max_width), min(px(720), max_height)
        x = max(0, min(self.root.winfo_rootx() + px(20), sw - width - px(20)))
        y = max(0, min(self.root.winfo_rooty() + px(20), sh - height - px(60)))
        win.geometry(f'{width}x{height}+{x}+{y}')
        win.minsize(min(px(360), max_width), min(px(260), max_height))
        self.button(win, self.T('close'), win.destroy, kind='primary').pack(
            side='bottom', anchor='e', padx=px(12), pady=px(8))
        banner = th.Banner(win, bg=BG, size=14)
        banner.pack(fill='x', pady=(px(6), 0))
        banner.set(title)
        wrap_label(tk.Label(win, text=heading_text, bg=BG, fg=th.INK, font=font(11, True))).pack(
            fill='x', padx=px(14), pady=(px(2), 0))
        viewport = ScrollPanel(win, height=560)
        viewport.pack(fill='both', expand=True, padx=px(8), pady=px(6))
        win.settings_viewport = viewport
        return win, viewport.content

    def settings_grid(self, win, groups, values, editable, on_change):
        cols = tk.Frame(win, bg=BG)
        cols.pack(fill='both', pady=px(6))
        columns = [tk.Frame(cols, bg=BG) for _ in range(3)]
        boxes = []
        self.setting_widgets = {}
        self.setting_vars = {}
        for group, keys in groups:
            box = tk.Frame(cols, bg=th.PANEL, highlightthickness=1, highlightbackground=th.EDGE)
            box.columnconfigure(0, weight=1)
            boxes.append((box, len(keys) + 2))
            wrap_label(tk.Label(box, text=kit_settings.group_label(group, self.lang), bg=th.PANEL,
                                fg=th.GOLD, font=heading(9))).grid(
                row=0, column=0, columnspan=2, sticky='ew', padx=px(8), pady=(px(6), px(3)))
            for r, key in enumerate(keys, 1):
                wrap_label(tk.Label(box, text=kit_settings.label(key, self.lang), bg=th.PANEL, fg=th.INK,
                                    font=font(8))).grid(row=r, column=0, sticky='ew', padx=px(8), pady=1)
                kind, options = kit_settings.choices(key)
                if kind in ('choice', 'button', 'bool'):
                    shown = [kit_settings.value_text(key, v, self.lang) for v in options]
                    widget = ttk.Combobox(box, values=shown, width=max(10, min(30, max(len(x) for x in shown) + 1)),
                                          state='readonly' if editable else 'disabled')
                    try:
                        widget.set(shown[list(options).index(values.get(key))])
                    except ValueError:
                        widget.set(str(values.get(key)))
                    widget.bind('<<ComboboxSelected>>', lambda e, k=key, o=options, w=widget, sh=shown:
                                on_change(k, o[sh.index(w.get())]))
                else:
                    low, high = options
                    var = tk.StringVar(master=self.root, value=kit_settings.value_text(key, values.get(key), self.lang))
                    self.spin_sent[key] = var.get()
                    widget = ttk.Spinbox(box, from_=low, to=high, textvariable=var, width=8,
                                         state='normal' if editable else 'disabled',
                                         increment=1 if kind == 'int' else 0.25,
                                         command=lambda k=key, v=var: self.spin_changed(k, v, on_change, now=True))
                    widget.bind('<Return>', lambda e, k=key, v=var: self.spin_changed(k, v, on_change, now=True))
                    widget.bind('<FocusOut>', lambda e, k=key, v=var: self.spin_changed(k, v, on_change, now=True))
                    self.setting_vars[key] = var
                widget.grid(row=r, column=1, sticky='w', padx=px(8), pady=1)
                self.setting_widgets[key] = widget
        layout = [None]

        def arrange(event):
            count = max(1, min(3, event.width // max(1, px(430))))
            if count == layout[0]:
                return
            layout[0] = count
            heights, rows = [0] * count, [0] * count
            for i, column in enumerate(columns):
                cols.columnconfigure(i, weight=1 if i < count else 0, uniform='settings' if i < count else '')
                if i < count:
                    column.grid(row=0, column=i, sticky='new', padx=px(4))
                    column.columnconfigure(0, weight=1)
                else:
                    column.grid_remove()
            for box, weight in boxes:
                col = heights.index(min(heights))
                box.grid(in_=columns[col], row=rows[col], column=0, sticky='ew', pady=px(4))
                heights[col] += weight
                rows[col] += 1
        cols.bind('<Configure>', arrange)

    def spin_changed(self, key, var, on_change, now=False):
        """A spin box sends at most one change per pause: the first click at once, the rest when the clicks stop."""
        value = var.get()
        jobs = self.__dict__.setdefault('spin_jobs', {})
        stamp = self.__dict__.setdefault('spin_stamp', {})
        if jobs.get(key):
            try:
                self.root.after_cancel(jobs.pop(key))
            except tk.TclError:
                pass
        if value == self.spin_sent.get(key):
            return
        quiet = time.monotonic() - stamp.get(key, 0.0) > 0.35
        if now and quiet:
            self.spin_sent[key] = value
            stamp[key] = time.monotonic()
            on_change(key, value)
            return
        stamp[key] = time.monotonic()

        def flush():
            jobs.pop(key, None)
            current = var.get()
            if current != self.spin_sent.get(key):
                self.spin_sent[key] = current
                on_change(key, current)
        jobs[key] = self.root.after(350, flush)

    def refresh_pickers(self):
        """Keep open dialogs truthful when the room changes underneath them."""
        live = self.settings_live
        if live and live['kind'] == 'rules' and not live['editable']:
            try:
                if live['win'].winfo_exists():
                    values = kit_settings.gameplay_expand(self.match().get('gameplay'))
                    focus = self.root.focus_get()
                    for key, widget in self.setting_widgets.items():
                        if key not in values or widget is focus:
                            continue
                        shown = kit_settings.value_text(key, values[key], self.lang)
                        var = self.setting_vars.get(key)
                        if var is not None:
                            if var.get() != shown:
                                var.set(shown)
                        elif widget.get() != shown:
                            widget.set(shown)
            except (tk.TclError, KeyError):
                pass
        picker = self.picker
        if picker and picker['win'].winfo_exists():
            picker['refresh']()

    # ---- the fighter picker -----------------------------------------------------------------------------------------------
    def open_picker(self, team, index):
        if not self.catalog:
            return
        self.close_dialog()
        try:
            current = dict(self.match()['teams'][team][index])
        except (IndexError, KeyError, TypeError):
            return
        title = self.T('room.team', n=team + 1) + f' · {index + 1}'
        win = self.toplevel(title)
        self.dialog = win
        win.columnconfigure(0, weight=1)
        win.rowconfigure(2, weight=1)
        opened = dict(character=current['character'], costume=current['costume'], owner=current.get('owner'))
        banner = th.Banner(win, bg=BG, size=14)
        banner.grid(row=0, column=0, columnspan=3, sticky='ew', pady=(px(6), 0))
        banner.set(title)
        top = tk.Frame(win, bg=BG)
        top.grid(row=1, column=0, columnspan=3, sticky='ew', padx=px(12), pady=px(4))
        tk.Label(top, text=self.T('pick.search'), bg=BG, fg=th.GOLD, font=heading(9)).pack(side='left')
        search = tk.StringVar(master=win)
        search_entry = ttk.Entry(top, textvariable=search, width=22)
        search_entry.pack(side='left', padx=px(6))
        chips = tk.Frame(top, bg=BG)
        chips.pack(side='right')
        tk.Label(top, text=self.T('pick.colour'), bg=BG, fg=th.GOLD, font=heading(9)).pack(side='right',
                                                                                         padx=(px(12), px(4)))
        chosen = {'c': current['character'], 'k': current['costume']}
        cell_px = 70 * PZ
        size = 64 * PZ
        canvas = tk.Canvas(win, bg=th.INSET, highlightthickness=1, highlightbackground=th.EDGE_DARK,
                           width=7 * cell_px + px(12), height=(5 if PZ > 1 else 6) * cell_px)
        bar = ttk.Scrollbar(win, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        canvas.grid(row=2, column=0, sticky='nsew', padx=(px(12), 0), pady=px(6))
        bar.grid(row=2, column=1, sticky='ns', pady=px(6))
        side = th.Panel(win)
        side.grid(row=2, column=2, sticky='nsew', padx=px(12), pady=px(6))
        sidein = side.inner
        preview = tk.Label(sidein, bg=th.INSET, bd=0)
        preview.pack(padx=px(14), pady=(px(14), px(6)))
        info = wrap_label(tk.Label(sidein, text='', bg=th.PANEL, fg=th.GOLD, font=heading(11)))
        info.pack(fill='x', padx=px(12))
        forms_label = tk.Label(sidein, text=self.T('pick.forms'), bg=th.PANEL, fg=th.DIM, font=font(9, True))
        forms_row = tk.Frame(sidein, bg=th.PANEL)
        notice = wrap_label(tk.Label(sidein, text='', bg=th.PANEL, fg='#ffb08a', font=font(9, True)))
        buttons = Flow(win, bg=BG, align='right')
        buttons.grid(row=3, column=0, columnspan=3, sticky='ew', padx=px(12), pady=(0, px(10)))
        cells = []
        layout = {'cols': None, 'job': None, 'search': None}

        def draw_chips():
            for w in chips.winfo_children():
                w.destroy()
            for k in range(self.catalog.costumes(chosen['c'])):
                chip = self.chip(chips, f' {k + 1} ', k == chosen['k'], lambda k=k: (chosen.update(k=k), draw_chips()))
                chip.pack(side='left', padx=px(2), pady=px(2))
            configure_changed(info, text=self.catalog.name(chosen['c']))
            img = self.image(self.catalog.chars[chosen['c']]['portrait'], 2) if chosen['c'] in self.catalog.chars \
                else None
            preview.configure(image=img or '')

        def pick(c):
            chosen['c'] = c
            chosen['k'] = min(chosen['k'], max(0, self.catalog.costumes(c) - 1))
            draw_chips()
            draw_forms()
            mark()

        def draw_forms():
            for w in forms_row.winfo_children():
                w.destroy()
            cell = next((g for g in self.catalog.c['grid'] if chosen['c'] in g['forms']), None)
            if cell and len(cell['forms']) > 1:
                if not forms_label.winfo_manager():
                    forms_label.pack(anchor='w', padx=px(12), pady=(px(8), 0))
                    forms_row.pack(anchor='w', padx=px(10), pady=(0, px(8)))
                for i, f in enumerate(cell['forms']):
                    img = self.small(self.catalog.chars[f]['portrait'])
                    b = tk.Label(forms_row, image=img, bg=th.GOLD if f == chosen['c'] else th.INSET, bd=px(2),
                                 cursor='hand2', highlightthickness=0)
                    b.grid(row=i // 4, column=i % 4, padx=px(2), pady=px(2))
                    b.bind('<Button-1>', lambda e, f=f: pick(f))
            elif forms_label.winfo_manager():
                forms_label.pack_forget()
                forms_row.pack_forget()

        def entries():
            text = search.get().strip().lower()
            if text:
                return [c['id'] for c in self.catalog.find(text)]
            return [g['base'] for g in sorted(self.catalog.c['grid'], key=lambda g: (g['row'], g['col']))]

        def draw(*_):
            layout['job'] = None
            if not self.alive or not canvas.winfo_exists():
                return
            width = canvas.winfo_width()
            count = max(4, min(12, (width - px(12)) // cell_px)) if width > 1 else 7
            ids = entries()
            if (count, tuple(ids)) == (layout['cols'], layout['search']):
                return
            layout['cols'], layout['search'] = count, tuple(ids)
            canvas.delete('all')
            cells.clear()
            for i, c in enumerate(ids):
                r, col = divmod(i, count)
                x, y = px(6) + col * cell_px + (cell_px - size) // 2, px(6) + r * cell_px + (cell_px - size) // 2
                canvas.create_rectangle(x - 1, y - 1, x + size + 1, y + size + 1, fill=th.PANEL, outline=th.EDGE_DARK)
                img = self.image(self.catalog.chars[c]['portrait'])
                if img:
                    canvas.create_image(x, y, anchor='nw', image=img, tags=(f'c{c}',))
                canvas.tag_bind(f'c{c}', '<Button-1>', lambda e, c=c: pick(c))
                canvas.tag_bind(f'c{c}', '<Double-Button-1>', lambda e, c=c: (pick(c), ok()))
                cells.append((c, x, y))
            rows = (len(ids) + count - 1) // count
            canvas.configure(scrollregion=(0, 0, count * cell_px + px(12), rows * cell_px + px(12)))
            mark()

        def mark():
            canvas.delete('sel')
            for c, x, y in cells:
                cell = next((g for g in self.catalog.c['grid'] if g['base'] == c), None)
                if (cell and chosen['c'] in cell['forms']) or c == chosen['c']:
                    th.glow_box(canvas, x, y, x + size, y + size, tags=('sel',))

        def hover(event):
            canvas.delete('hover')
            x, y = canvas.canvasx(event.x), canvas.canvasy(event.y)
            for c, cx, cy in cells:
                if cx <= x <= cx + size and cy <= y <= cy + size:
                    canvas.create_rectangle(cx - 2, cy - 2, cx + size + 2, cy + size + 2, outline=th.GLOW, width=2,
                                            tags=('hover',))
                    break

        def redraw_soon(*_):
            if layout['job'] is None:
                layout['job'] = self.root.after(40, draw)

        def refresh():
            """The room changed: close if this player may no longer edit the fighter, warn if it was changed."""
            try:
                live = self.match()['teams'][team][index]
            except (IndexError, KeyError, TypeError):
                self.close_dialog()
                return
            allowed = (self.is_host() or live.get('owner') == self.me()) and self.lobby().get('phase') == 'lobby'
            if not allowed:
                self.close_dialog()
                return
            if (live['character'], live['costume'], live.get('owner')) != \
                    (opened['character'], opened['costume'], opened['owner']):
                if not notice.winfo_manager():
                    notice.pack(fill='x', padx=px(12), pady=px(6))
                configure_changed(notice, text=self.T('pick.changed'))

        def ok():
            try:
                live = self.match()['teams'][team][index]
            except (IndexError, KeyError, TypeError):
                self.close_dialog()
                return
            if (live['character'], live['costume'], live.get('owner')) != \
                    (opened['character'], opened['costume'], opened['owner']):
                # Changed by someone else since the picker opened: show it, and replace only on a second OK.
                opened.update(character=live['character'], costume=live['costume'], owner=live.get('owner'))
                if not notice.winfo_manager():
                    notice.pack(fill='x', padx=px(12), pady=px(6))
                configure_changed(notice, text=self.T('pick.changed'))
                return
            self.send('fighter', team=team, index=index, character=chosen['c'], costume=chosen['k'])
            self.close_dialog()
        cancel = self.button(buttons, self.T('cancel'), self.close_dialog, big=True)
        okb = self.button(buttons, self.T('ok'), ok, kind='primary', big=True)
        buttons.set_widgets([cancel, okb])
        search.trace_add('write', redraw_soon)
        canvas.bind('<Configure>', redraw_soon)
        canvas.bind('<Motion>', hover)
        canvas.bind('<Leave>', lambda e: canvas.delete('hover'))
        win.bind('<Return>', lambda e: ok())
        draw_chips()
        draw_forms()
        draw()
        win.minsize(px(520), px(360))
        self.place_dialog(win, 7 * cell_px + px(330), None)
        search_entry.focus_set()
        self.picker = dict(win=win, pick=pick, ok=ok, chosen=chosen, search=search, refresh=refresh)

    def open_potara_picker(self, team, index):
        """A draft loadout; Cancel leaves the roster/readiness unchanged."""
        if not self.catalog or not self.catalog.potaras:
            return
        self.close_dialog()
        try:
            current = self.match()['teams'][team][index]
        except (IndexError, KeyError, TypeError):
            return
        import kit_potara
        editable = (self.is_host() or current.get('owner') == self.me()) and self.lobby().get('phase') == 'lobby'
        if kit_potara.problems(current.get('potaras', []), self.catalog):
            return
        win = self.toplevel(self.T('potara.title') + ' · ' + self.catalog.name(current['character']))
        self.dialog = win
        win.minsize(px(460), px(330))
        win.maxsize(self.root.winfo_screenwidth() - 40, self.root.winfo_screenheight() - 60)
        outer = tk.Frame(win, bg=BG)
        outer.pack(fill='both', expand=True, padx=px(12), pady=px(10))
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)
        head = tk.Frame(outer, bg=BG)
        head.grid(row=0, column=0, sticky='ew')
        head.columnconfigure(1, weight=1)
        th.portrait_frame(head, self.image(self.catalog.chars[current['character']]['portrait'])
                          if current['character'] in self.catalog.chars else None, bg=th.INSET).grid(
            row=0, column=0, rowspan=2, sticky='nw', padx=(0, px(10)))
        wrap_label(tk.Label(head, text=self.catalog.name(current['character']), bg=BG, fg=th.GOLD,
                            font=heading(12))).grid(row=0, column=1, sticky='ew')
        note = wrap_label(tk.Label(head, text=self.T('potara.note'), bg=BG, fg=th.DIM, font=font(9)))
        note.grid(row=1, column=1, sticky='ew', pady=(px(4), px(8)))
        search = tk.StringVar(master=win)
        ttk.Entry(outer, textvariable=search).grid(row=1, column=0, sticky='ew', pady=(0, px(6)))
        body = tk.Frame(outer, bg=BG)
        body.grid(row=2, column=0, sticky='nsew')
        body.columnconfigure(0, weight=1)
        body.columnconfigure(2, weight=1)
        body.rowconfigure(0, weight=1)
        count = wrap_label(tk.Label(outer, bg=BG, fg=th.GOLD, font=heading(9)))
        count.grid(row=3, column=0, sticky='ew', pady=(px(6), 0))
        detail = wrap_label(tk.Label(outer, bg=BG, fg=th.DIM, font=font(9)))
        detail.grid(row=4, column=0, sticky='ew')
        notice = wrap_label(tk.Label(outer, bg=BG, fg='#ffb08a', font=font(9, True)))
        notice.grid(row=5, column=0, sticky='ew')
        buttons = Flow(outer, bg=BG)
        buttons.grid(row=6, column=0, sticky='ew', pady=(px(8), 0))
        compact = {'on': False}

        def fit(event):
            # A short window first drops the header (portrait and note): the lists and the buttons stay usable.
            if event.widget is not win:
                return
            small = event.height < px(420)
            if small != compact['on']:
                compact['on'] = small
                if small:
                    head.grid_remove()
                else:
                    head.grid()
        win.bind('<Configure>', fit, add='+')
        lists = dict(bg=th.INSET, fg=th.INK, selectbackground=th.GOLD, selectforeground=th.DARK_INK, font=font(9),
                     exportselection=False, relief='flat', highlightthickness=1, highlightbackground=th.EDGE_DARK,
                     highlightcolor=th.GLOW, activestyle='none')
        available = tk.Listbox(body, width=32, height=14, **lists)
        available.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(body, orient='vertical', command=available.yview)
        scroll.grid(row=0, column=1, sticky='ns', padx=(0, px(8)))
        available.configure(yscrollcommand=scroll.set)
        horizontal = ttk.Scrollbar(body, orient='horizontal', command=available.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        available.configure(xscrollcommand=horizontal.set)
        equipped = tk.Listbox(body, width=30, height=8, **lists)
        equipped.grid(row=0, column=2, sticky='nsew')
        horizontal = ttk.Scrollbar(body, orient='horizontal', command=equipped.xview)
        horizontal.grid(row=1, column=2, sticky='ew')
        equipped.configure(xscrollcommand=horizontal.set)
        draft = list(current.get('potaras', []))
        shown = []

        def name(ident):
            item = self.catalog.potaras[ident]
            return f'{item["name"]}  ({item["cost"]})'

        def refresh(*_):
            available.delete(0, 'end')
            shown[:] = [i for i, p in self.catalog.potaras.items() if search.get().casefold() in p['name'].casefold()]
            for i in shown:
                available.insert('end', name(i))
            equipped.delete(0, 'end')
            for i in draft:
                equipped.insert('end', name(i))
            count.configure(text=self.T('potara.budget', used=sum(self.catalog.potaras[i]['cost'] for i in draft),
                                        n=len(draft)))

        def preview(event):
            listing = event.widget
            selected = listing.curselection()
            if not selected:
                return
            ident = (shown if listing is available else draft)[selected[0]]
            item = self.catalog.potaras[ident]
            changes = [self.T('potara.stat.' + key) + f' {value:+d}'
                       for key, value in zip(('attack', 'defense', 'ki', 'super'), item['stats']) if value]
            detail.configure(text=item['name'] + (' · ' + ', '.join(changes) if changes else ''))

        def add(*_):
            selected = available.curselection()
            if not selected:
                return
            candidate = draft + [shown[selected[0]]]
            errors = kit_potara.problems(candidate, self.catalog)
            if errors:
                notice.configure(text=self.T('potara.invalid'))
                return
            draft[:] = sorted(candidate)
            notice.configure(text='')
            refresh()

        def remove(*_):
            selected = equipped.curselection()
            if selected:
                draft.pop(selected[0])
                notice.configure(text='')
                refresh()

        def ok():
            # Re-read the current fighter. A remote roster change cannot be
            # overwritten with this dialog's old character/costume.
            if not editable:
                return
            try:
                live = self.match()['teams'][team][index]
            except (IndexError, KeyError, TypeError):
                win.destroy()
                return
            if (live['character'], live['costume'], live.get('owner')) != \
                    (current['character'], current['costume'], current.get('owner')):
                notice.configure(text=self.T('potara.changed'))
                return
            self.send('fighter', team=team, index=index, character=live['character'],
                      costume=live['costume'], potaras=list(draft))
            win.destroy()
            self.dialog = None

        widgets, right = [], []
        if editable:
            widgets += [self.button(buttons, self.T('potara.add'), add, kind='secondary'),
                        self.button(buttons, self.T('potara.remove'), remove),
                        self.button(buttons, self.T('potara.clear'),
                                    lambda: (draft.clear(), notice.configure(text=''), refresh()))]
        cancel = self.button(buttons, self.T('cancel'), win.destroy)
        widgets.append(cancel)
        right.append(cancel)
        if editable:
            okb = self.button(buttons, self.T('ok'), ok, kind='primary')
            widgets.append(okb)
            right.append(okb)
        buttons.set_widgets(widgets, right=right)
        search.trace_add('write', refresh)
        available.bind('<<ListboxSelect>>', preview)
        equipped.bind('<<ListboxSelect>>', preview)
        if editable:
            available.bind('<Double-Button-1>', add)
            equipped.bind('<Double-Button-1>', remove)
        refresh()
        self.place_dialog(win, px(720), px(520))
        self.potara_picker = dict(win=win, draft=draft, ok=ok, available=available, shown=shown,
                                  equipped=equipped, add=add, remove=remove, search=search)

    def open_stage_picker(self):
        if not self.catalog:
            return
        self.close_dialog()
        win = self.toplevel(self.T('stage.title'))
        self.dialog = win
        win.columnconfigure(0, weight=1)
        win.rowconfigure(1, weight=1)
        banner = th.Banner(win, bg=BG, size=14)
        banner.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(px(6), px(2)))
        banner.set(self.T('stage.title'))
        order = self.catalog.stage_order() + ['random']
        current = self.match().get('stage')
        size = 64 * PZ
        cell_w, cell_h = size + px(44), size + px(46)
        canvas = tk.Canvas(win, bg=th.INSET, highlightthickness=1, highlightbackground=th.EDGE_DARK,
                           width=7 * cell_w + px(12), height=4 * cell_h + px(12))
        bar = ttk.Scrollbar(win, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        canvas.grid(row=1, column=0, sticky='nsew', padx=(px(12), 0), pady=px(4))
        bar.grid(row=1, column=1, sticky='ns', padx=(0, px(12)), pady=px(4))
        buttons = Flow(win, bg=BG, align='right')
        buttons.grid(row=2, column=0, columnspan=2, sticky='ew', padx=px(12), pady=(px(4), px(10)))
        buttons.set_widgets([self.button(buttons, self.T('cancel'), self.close_dialog)])
        layout = {'cols': None, 'job': None}
        cells = []

        def choose(sid):
            self.send('rules', stage=sid)
            self.close_dialog()

        def draw():
            layout['job'] = None
            if not self.alive or not canvas.winfo_exists():
                return
            width = canvas.winfo_width()
            count = max(2, min(10, (width - px(12)) // cell_w)) if width > 1 else 7
            if count == layout['cols']:
                return
            layout['cols'] = count
            canvas.delete('all')
            cells.clear()
            for i, sid in enumerate(order):
                r, col = divmod(i, count)
                x0, y0 = px(6) + col * cell_w, px(6) + r * cell_h
                x, y = x0 + (cell_w - size) // 2, y0 + px(6)
                tag = f's{i}'
                canvas.create_rectangle(x0 + 2, y0 + 2, x0 + cell_w - 2, y0 + cell_h - 2, fill=th.PANEL,
                                        outline=th.EDGE_DARK, tags=(tag,))
                rel = self.catalog.c.get('random_thumb') if sid == 'random' else self.catalog.stages[sid]['thumb']
                img = self.image(rel)
                if img:
                    canvas.create_image(x, y, anchor='nw', image=img, tags=(tag,))
                name = self.T('rule.random') if sid == 'random' else self.catalog.stage_name(sid)
                canvas.create_text(x0 + cell_w // 2, y + size + px(5), text=name, anchor='n', width=cell_w - px(8),
                                   fill=th.INK, font=font(8), justify='center', tags=(tag,))
                canvas.tag_bind(tag, '<Button-1>', lambda e, sid=sid: choose(sid))
                cells.append((sid, x0, y0))
                if sid == current:
                    th.glow_box(canvas, x0 + 4, y0 + 4, x0 + cell_w - 4, y0 + cell_h - 4)
            rows = (len(order) + count - 1) // count
            canvas.configure(scrollregion=(0, 0, count * cell_w + px(12), rows * cell_h + px(12)))

        def hover(event):
            canvas.delete('hover')
            x, y = canvas.canvasx(event.x), canvas.canvasy(event.y)
            for sid, x0, y0 in cells:
                if x0 <= x <= x0 + cell_w and y0 <= y <= y0 + cell_h:
                    canvas.create_rectangle(x0 + 2, y0 + 2, x0 + cell_w - 2, y0 + cell_h - 2, outline=th.GLOW,
                                            width=2, tags=('hover',))
                    break
        canvas.bind('<Configure>', lambda e: layout['job'] or layout.update(job=self.root.after(40, draw)))
        canvas.bind('<Motion>', hover)
        canvas.bind('<Leave>', lambda e: canvas.delete('hover'))
        draw()
        win.minsize(px(420), px(320))
        self.place_dialog(win, 7 * cell_w + px(50), min(self.root.winfo_screenheight() - px(80),
                                                         5 * cell_h + px(140)), dx=60, dy=40)

    # ---- S6 / S7 preparing, sending, loading ---------------------------------------------------------------------------
    def versus_card(self, parent):
        """Both teams' portraits facing each other (BT3's loading screen), from the room's roster; the portraits
        shrink to half size when the window is too narrow for them (fit_versus, after a resize)."""
        teams = (self.match().get('teams') or [])[:2]
        if not teams or not self.catalog:
            self.vs = None
            return None
        card = th.Panel(parent)
        card.pack(fill='x', padx=px(16), pady=(px(10), px(4)))
        self.vs = dict(card=card, teams=teams, small=None)
        self.fit_versus()
        return card

    def fit_versus(self):
        vs = getattr(self, 'vs', None)
        if not vs:
            return
        try:
            if not vs['card'].winfo_exists():
                return
        except tk.TclError:
            return
        width = self.body.winfo_width()
        n = max(len(team) for team in vs['teams'])
        need = 2 * n * (64 * PZ + px(10)) + px(150)
        small = 1 < width < need
        if small == vs['small']:
            return
        vs['small'] = small
        inner = vs['card'].inner
        for w in inner.winfo_children():
            w.destroy()
        row = tk.Frame(inner, bg=th.PANEL)
        row.pack(pady=px(10))
        for t_, team in enumerate(vs['teams']):
            side = tk.Frame(row, bg=th.PANEL)
            side.grid(row=0, column=0 if t_ == 0 else 2, padx=px(8))
            for i, f in enumerate(team):
                mine = f.get('owner') is not None and f.get('owner') == self.me()
                rel = self.catalog.chars[f['character']]['portrait'] if f['character'] in self.catalog.chars else None
                img = (self.small(rel) if small else self.image(rel)) if rel else None
                pic = th.portrait_frame(side, img, glow=th.GLOW if mine else None, bg=th.INSET)
                pic.grid(row=0, column=i if t_ == 0 else len(team) - 1 - i, padx=px(2))
            tk.Frame(side, bg=th.TEAM[t_], height=px(4)).grid(row=1, column=0, columnspan=max(1, len(team)),
                                                              sticky='ew', pady=(px(4), 0))
        tk.Label(row, text='VS', bg=th.PANEL, fg=th.GOLD, font=heading(18 if small else 26)).grid(
            row=0, column=1, padx=px(10))

    def build_prep(self):
        self.header(self.body, self.T('prep.title'))
        self.versus_card(self.body)
        box = th.Panel(self.body)
        box.pack(fill='x', padx=px(16), pady=px(10))
        inner = box.inner
        self.prep_title = wrap_label(tk.Label(inner, text='', bg=th.PANEL, fg=th.INK, font=font(12, True)))
        self.prep_title.pack(fill='x', padx=px(16), pady=(px(14), px(4)))
        self.prep_step = wrap_label(tk.Label(inner, text='', bg=th.PANEL, fg=th.GOLD, font=heading(11)))
        self.prep_step.pack(fill='x', padx=px(16))
        self.prep_bar = ttk.Progressbar(inner, length=px(600), maximum=100)
        self.prep_bar.pack(fill='x', padx=px(16), pady=px(12))
        self.prep_eta = wrap_label(tk.Label(inner, text='', bg=th.PANEL, fg=th.DIM, font=font(10)))
        self.prep_eta.pack(fill='x', padx=px(16), pady=(0, px(12)))
        foot = tk.Frame(self.foot, bg=BG)
        foot.grid(row=0, column=0, sticky='ew')
        foot.columnconfigure(0, weight=1)
        self.notice_label = wrap_label(tk.Label(foot, text='', bg=BG, fg=th.GOLD, font=font(10, True)))
        self.notice_label.grid(row=0, column=0, sticky='ew')
        collapsing(self.notice_label)
        row = Flow(foot, bg=BG)
        row.grid(row=1, column=0, sticky='ew', pady=(px(4), 0))
        self.prep_cancel = None
        if self.is_host():
            self.prep_cancel = self.button(row, self.T('prep.cancel'), self.cancel_prep, kind='danger', big=True)
            row.set_widgets([self.prep_cancel])

    def build_bottom_chat(self, parent):
        """The chat is part of the window's frame now (pinned at the bottom); kept for callers of the old window."""
        self.show_chat(True)

    def cancel_prep(self):
        if self.ask(self.T('prep.cancel_confirm')):
            self.once('cancel_prep', lambda: self.send('cancel_prep'), hold=2.0)

    def update_prep(self):
        st = self.state
        prog = st.get('progress') or {}
        title = (st.get('match') or {}).get('title') or ''
        phase = st.get('phase')
        configure_changed(self.prep_title, text=title)
        step = prog.get('step') or ('prep.settings' if phase == 'preparing' else 'load.starting')
        text = self.T(step, mb=prog.get('mb', ''), name='')
        if step == 'load.waiting':
            text = self.T('load.waiting_players')
        if phase == 'preparing' and step.startswith('prep.'):
            text = self.T('prep.host_step', step=text)
        configure_changed(self.prep_step, text=text)
        eta = prog.get('eta_s')
        configure_changed(self.prep_eta, text=self.T('prep.eta', t=f'{int(eta) // 60}:{int(eta) % 60:02d}')
                          if phase == 'preparing' and isinstance(eta, (int, float)) else '')
        configure_changed(self.prep_bar, value=prog.get('pct') or 0)
        self.set_head_line(self.T('send.title') if phase in ('sending', 'loading') else '')
        self.show_notice()

    # ---- S8 fight ------------------------------------------------------------------------------------------------------
    def build_fight(self):
        self.header(self.body, self.T('fight.title'))
        self.versus_card(self.body)
        box = th.Panel(self.body, edge=th.EDGE)
        box.pack(fill='x', padx=px(16), pady=px(10))
        inner = box.inner
        title = (self.state.get('match') or {}).get('title') or ''
        wrap_label(tk.Label(inner, text=title, bg=th.PANEL, fg=th.INK,
                            font=font(10, True))).pack(fill='x', padx=px(16), pady=(px(12), 0))
        self.fight_role = wrap_label(tk.Label(inner, text='', bg=th.PANEL, fg=th.GOLD, font=heading(12)))
        self.fight_role.pack(fill='x', padx=px(16), pady=(px(6), 0))
        self.fight_status = wrap_label(tk.Label(inner, text='', bg=th.PANEL, fg=th.GREEN, font=font(13, True)))
        self.fight_status.pack(fill='x', padx=px(16), pady=(px(6), px(4)))
        self.fight_banner = wrap_label(tk.Label(inner, text='', bg=th.PANEL, fg=th.GOLD, font=font(12, True)))
        self.fight_banner.pack(fill='x', padx=px(16))
        wrap_label(tk.Label(inner, text=self.T('fight.window_hint'), bg=th.PANEL, fg=th.DIM,
                            font=font(9))).pack(fill='x', padx=px(16), pady=(px(4), px(12)))
        self.hub_box = th.Panel(self.body, edge=th.EDGE_BLUE)
        self.hub_sig = None
        foot = tk.Frame(self.foot, bg=BG)
        foot.grid(row=0, column=0, sticky='ew')
        foot.columnconfigure(0, weight=1)
        self.notice_label = wrap_label(tk.Label(foot, text='', bg=BG, fg=th.GOLD, font=font(10, True)))
        self.notice_label.grid(row=0, column=0, sticky='ew')
        collapsing(self.notice_label)
        row = Flow(foot, bg=BG)
        row.grid(row=1, column=0, sticky='ew', pady=(px(4), 0))
        self.fight_buttons = row
        if self.is_host():
            self.end_button = self.button(row, self.T('fight.end_host'), self.end_fight, kind='danger', big=True)
        else:
            self.end_button = self.button(row, self.T('fight.leave_match'), self.leave_match, kind='danger', big=True)
        row.add(self.end_button)
        self.watch_buttons = []
        for side in (0, 1):
            b = self.button(row, self.T('fight.watch_team', team=side + 1), lambda s=side: self.send('watch', side=s),
                            kind='secondary')
            self.watch_buttons.append(b)

    def update_fight(self):
        st = self.state.get('status') or {}
        frame = st.get('frame')
        ms = st.get('rtt_ms')
        if ms is None and self.is_host():
            values = [m.get('rtt_ms') for m in (st.get('members') or {}).values() if m.get('rtt_ms') is not None]
            ms = max(values) if values else '-'
        configure_changed(self.fight_status, text=self.T('fight.status', frame=frame if frame is not None else '-',
                                                         ms=ms if ms is not None else '-', d=st.get('delay') or '-'))
        slot = st.get('slot')
        if slot is not None:
            configure_changed(self.fight_role, text=self.T('fight.playing', team=slot + 1))
        else:
            configure_changed(self.fight_role, text=self.T('fight.watching', side=(st.get('watch') or 0) + 1))
        self.fight_buttons.set_widgets([self.end_button] + (self.watch_buttons if slot is None else []),
                                       right=self.watch_buttons if slot is None else ())
        ov = self.state.get('overlay')
        configure_changed(self.fight_banner, text=self.overlay_text(ov) if ov else '')
        self.show_notice()
        self.draw_hub()

    def draw_hub(self):
        """The running hub: scoreboard, Fight freely, challenges (only while the lobby holds a hub view)."""
        box = getattr(self, 'hub_box', None)
        if box is None or not box.winfo_exists():
            return
        hub = self.lobby().get('hub')
        rows = (hub or {}).get('rows') or []
        sig = json.dumps([None if hub is None else {
            'fighters': [(r['i'], r['name'], r.get('member')) for r in rows],
            'duel': hub.get('duel'), 'open': hub.get('open'), 'challenges': hub.get('challenges'),
            'names': [(i, m['name']) for i, m in sorted(self.members().items())]}, self.me(), self.lang])
        if sig == self.hub_sig:
            if hub:
                self.update_hub_scores(hub)
            return
        self.hub_sig = sig
        keep = None
        old = getattr(self, 'hub_pick', None)
        try:
            if old is not None and old.winfo_exists():
                keep = old.get()                                     # a challenge choice survives a rebuild
        except tk.TclError:
            pass
        self.hub_pick = None
        inner = box.inner
        for w in inner.winfo_children():
            w.destroy()
        if not hub:
            box.pack_forget()
            return
        box.pack(fill='x', padx=px(16), pady=(0, px(6)))
        wrap_label(tk.Label(inner, text=self.T('fight.hub_title') + '   (' + self.T('fight.hub_cols') + ')',
                            bg=th.PANEL, fg=th.GOLD, font=heading(11))).pack(fill='x', padx=px(10),
                                                                              pady=(px(6), px(2)))
        duel = hub.get('duel')
        rows = hub.get('rows') or []
        names = {r['i']: r['name'] for r in rows}
        if duel:
            wrap_label(tk.Label(inner, text=self.T('fight.hub_dueling', a=names.get(duel[0], '?'),
                                                   b=names.get(duel[1], '?')),
                                bg=th.PANEL, fg=th.RED, font=font(10, True))).pack(fill='x', padx=px(10))
        grid = tk.Frame(inner, bg=th.PANEL)
        grid.pack(fill='x', padx=px(10))
        grid.columnconfigure(0, weight=1)
        self.hub_score_labels = {}
        for r, row in enumerate(sorted(rows, key=lambda x: (-x['kills'], x['deaths'], x['i']))):
            mine = row.get('member') == self.me()
            name = wrap_label(tk.Label(grid, bg=th.PANEL, fg=th.GOLD if mine else th.INK, font=font(9, mine)))
            name.grid(row=r, column=0, sticky='ew')
            labels = [name]
            for col, key in enumerate(('kills', 'deaths', 'wins'), 1):
                label = tk.Label(grid, bg=th.PANEL, fg=th.INK, font=font(9), width=5)
                label.grid(row=r, column=col)
                labels.append(label)
            self.hub_score_labels[row['i']] = labels
        self.hub_feed_labels = []
        for _ in range(3):
            label = wrap_label(tk.Label(inner, bg=th.PANEL, fg=th.DIM, font=font(8)))
            label.pack(fill='x', padx=px(10))
            self.hub_feed_labels.append(label)
        self.update_hub_scores(hub)
        me_row = next((r for r in rows if r.get('member') == self.me()), None)
        if me_row is None:
            join = tk.Frame(inner, bg=th.PANEL)                     # kit 2.1: a watcher may take a free fighter
            join.pack(fill='x', padx=px(10), pady=px(6))
            self.button(join, self.T('fight.hub_join'),
                        lambda: self.once('hub_join', lambda: self.send('hub_join')), kind='secondary').pack(
                side='left')
            wrap_label(tk.Label(join, text='  ' + self.T('fight.hub_join_why'), bg=th.PANEL, fg=th.DIM,
                                font=font(8))).pack(side='left', fill='x', expand=True)
            self.answer_rows(inner, hub)
            return
        actions = Flow(inner, bg=th.PANEL)
        actions.pack(fill='x', padx=px(10), pady=px(6))
        is_open = bool(hub.get('open', 0) >> me_row['i'] & 1)
        self.hub_open_button = self.button(actions, self.T('fight.hub_open_on' if is_open else 'fight.hub_open_off'),
                                           lambda: self.send('hub_open', on=not is_open),
                                           kind='danger' if is_open else 'plain')
        widgets = [self.hub_open_button]
        others = [r for r in rows if r.get('member') not in (None, self.me())]
        if others and not duel:
            widgets.append(tk.Label(actions, text=self.T('fight.hub_challenge'), bg=th.PANEL, fg=th.INK,
                                    font=font(9, True)))
            pick = ttk.Combobox(actions, values=[r['name'] for r in others], state='readonly', width=16)
            pick.set(keep if keep in [r['name'] for r in others] else others[0]['name'])
            self.hub_pick = pick
            widgets.append(pick)

            def target():
                return next((r['member'] for r in others if r['name'] == pick.get()), None)
            widgets.append(self.button(actions, self.T('fight.hub_duel'),
                                       lambda: self.once('hub_duel', lambda: self.send('hub_challenge', target=target(),
                                                                                       kind='duel'))))
            widgets.append(self.button(actions, self.T('fight.hub_match'),
                                       lambda: self.once('hub_match', lambda: self.send('hub_challenge',
                                                                                        target=target(),
                                                                                        kind='match'))))
        actions.set_widgets(widgets)
        self.answer_rows(inner, hub)

    def answer_rows(self, parent, hub):
        for ch in hub.get('challenges') or []:
            if ch.get('target') != self.me():
                continue
            row = Flow(parent, bg=th.PANEL)
            row.pack(fill='x', padx=px(10), pady=(0, px(6)))
            by = self.name_of(ch['by'])
            kind = self.T('fight.hub_duel' if ch['kind'] == 'duel' else 'fight.hub_match')
            row.set_widgets([
                tk.Label(row, text=self.T('fight.hub_incoming', name=by, kind=kind), bg=th.PANEL, fg=th.GOLD,
                         font=font(10, True)),
                self.button(row, self.T('fight.hub_accept'),
                            lambda b=ch['by']: self.once(('hub_answer', b), lambda: self.send(
                                'hub_answer', challenger=b, accept=True)), kind='go'),
                self.button(row, self.T('fight.hub_decline'),
                            lambda b=ch['by']: self.once(('hub_answer', b), lambda: self.send(
                                'hub_answer', challenger=b, accept=False)))])

    def update_hub_scores(self, hub):
        for position, row in enumerate(sorted(hub.get('rows') or [], key=lambda x: (-x['kills'], x['deaths'], x['i']))):
            labels = self.hub_score_labels.get(row['i'])
            if labels is None:
                continue
            tag = ' · AWAY' if hub.get('parked', 0) >> row['i'] & 1 else (' · DOWN' if row.get('down') else '')
            values = [row['name'] + tag] + [str(row[k]) for k in ('kills', 'deaths', 'wins')]
            for label, text in zip(labels, values):
                configure_changed(label, text=text)
                if int(label.grid_info()['row']) != position:
                    label.grid_configure(row=position)
        feed = hub.get('feed') or []
        for i, label in enumerate(self.hub_feed_labels):
            configure_changed(label, text=feed[i] if i < len(feed) else '')

    def end_fight(self):
        if self.ask(self.T('fight.end_confirm2')):
            self.once('end_fight', lambda: self.send('end_fight'), hold=2.0)

    def leave_match(self):
        if self.ask(self.T('fight.leave_match') + '?'):
            self.once('leave_match', lambda: self.send('leave_match'), hold=2.0)

    # ---- S9 results ----------------------------------------------------------------------------------------------------
    def build_results(self):
        self.header(self.body, self.T('results.title'))
        box = th.Panel(self.body)
        box.pack(fill='x', padx=px(16), pady=px(14))
        inner = box.inner
        self.res_title = wrap_label(tk.Label(inner, text='', bg=th.PANEL, fg=th.DIM, font=font(10)))
        self.res_title.pack(fill='x', padx=px(16), pady=(px(12), 0))
        self.res_winner = wrap_label(tk.Label(inner, text='', bg=th.PANEL, fg=th.GOLD, font=heading(22)))
        self.res_winner.pack(fill='x', padx=px(16), pady=(px(6), px(4)))
        self.res_faces = tk.Frame(inner, bg=th.PANEL)
        self.res_faces.pack(anchor='w', padx=px(16), pady=(0, px(6)))
        self.res_faces_sig = None
        self.res_sync = wrap_label(tk.Label(inner, text='', bg=th.PANEL, fg=th.DIM, font=font(9)))
        self.res_sync.pack(fill='x', padx=px(16))
        self.res_vote = wrap_label(tk.Label(inner, text='', bg=th.PANEL, fg=th.INK, font=font(12, True)))
        self.res_vote.pack(fill='x', padx=px(16), pady=(px(12), px(2)))
        self.res_agreed = wrap_label(tk.Label(inner, text='', bg=th.PANEL, fg=th.GREEN, font=font(10)))
        self.res_agreed.pack(fill='x', padx=px(16), pady=(0, px(14)))
        row = Flow(self.foot, bg=BG)
        row.grid(row=0, column=0, sticky='ew')
        self.res_retry = self.button(row, self.T('results.retry'),
                                     lambda: self.once('vote', lambda: self.send('vote', choice='retry'), hold=1.5),
                                     kind='primary', big=True, width=14)
        self.res_back = self.button(row, self.T('results.to_lobby'),
                                    lambda: self.once('vote', lambda: self.send('vote', choice='lobby'), hold=1.5),
                                    big=True)
        if self.my_slot() is not None or (self.is_host() and not self.match_players()):
            row.set_widgets([self.res_back, self.res_retry], right=[self.res_retry])

    def match_players(self):
        return list(((self.state.get('match') or {}).get('seats') or {}).keys())

    def update_results(self):
        if not getattr(self, 'res_vote', None) or not self.res_vote.winfo_exists():
            return
        res = self.state.get('results') or {}
        configure_changed(self.res_title, text=res.get('title') or (self.state.get('match') or {}).get('title') or '')
        winner, how = res.get('winner') or 0, res.get('how')
        team = None
        if how == 'nocontest' or not winner:
            text = self.T('results.nocontest') if not res.get('nocontest') else \
                self.T('results.nocontest_why', why=res['nocontest'])
        else:
            team = 1 if winner & 1 else 2
            text = self.T('results.winner_team', team=team) + ' ' + self.T('results.ko' if how == 'ko' else
                                                                          'results.time')
        configure_changed(self.res_winner, text=text)
        self.draw_winners(team)
        seconds = int(res.get('seconds') or 0)
        if res.get('compared') is not None:
            configure_changed(self.res_sync, text=self.T('results.sync', compared=res.get('compared'),
                                                         differing=res.get('differing'),
                                                         resyncs=res.get('resyncs') or 0) +
                              ' · ' + self.T('results.duration', m=seconds // 60, s=seconds % 60))
        vote = self.state.get('vote') or {}
        if vote.get('decision') == 'retry':
            line = self.T('results.decided_retry')
        elif vote.get('decision') == 'lobby':
            line = self.T('results.decided_lobby')
        elif vote:
            line = self.T('results.vote_line', left=int(vote.get('left_s') or 0), agreed=len(vote.get('agreed') or []),
                          players=len(vote.get('players') or []))
        else:
            line = ''
        if self.my_slot() is None and not self.is_host():
            line = self.T('results.spectator') + ('  ' + line if line else '')
        configure_changed(self.res_vote, text=line)
        names = [self.name_of(k) for k in vote.get('agreed') or []]
        configure_changed(self.res_agreed, text=self.T('results.agreed_by', names=', '.join(names)) if names else '')
        agreed = self.me() in (vote.get('agreed') or [])
        on = not (agreed or vote.get('decision'))
        for b in (self.res_retry, self.res_back):
            if b.winfo_exists():
                th.enable(b, on)

    def draw_winners(self, team):
        """The winning team's portraits under the result (drawn when the result arrives, not on every tick)."""
        teams = self.match().get('teams') or []
        sig = (team, json.dumps(teams[team - 1] if team and team <= len(teams) else None))
        if sig == self.res_faces_sig:
            return
        self.res_faces_sig = sig
        for w in self.res_faces.winfo_children():
            w.destroy()
        if not team or team > len(teams) or not self.catalog:
            return
        for i, f in enumerate(teams[team - 1]):
            mine = f.get('owner') is not None and f.get('owner') == self.me()
            th.portrait_frame(self.res_faces, self.portrait(f['character']), glow=th.GLOW if mine else None,
                              bg=th.INSET).grid(row=0, column=i, padx=px(3))

    # ---- overlay -----------------------------------------------------------------------------------------------------------
    def overlay_text(self, ov):
        args = dict(ov.get('args') or {})
        args.setdefault('name', '')
        return self.T(ov['key'], **args)

    def update_overlay(self):
        ov = self.state.get('overlay')
        pc = self.state.get('pcsx2') or {}
        if not ov or not pc.get('pid'):
            if self.overlay is not None:
                try:
                    self.overlay.destroy()
                except tk.TclError:
                    pass
                self.overlay, self.overlay_hwnd = None, None
            return
        info = kit_win.window_info(pc['pid'], pc.get('desktop'))
        text = self.overlay_text(ov)
        if self.overlay is None:
            self.overlay = tk.Toplevel(self.root, bg=th.EDGE)
            self.overlay.overrideredirect(True)
            self.overlay.attributes('-topmost', True)
            try:
                self.overlay.attributes('-alpha', 0.94)
            except tk.TclError:
                pass
            frame = tk.Frame(self.overlay, bg=th.EDGE, relief='ridge', bd=max(2, px(3)))
            frame.pack(fill='both', expand=True)
            self.overlay_label = tk.Label(frame, text=text, bg=th.PANEL, fg=th.GOLD, font=heading(13),
                                          padx=px(20), pady=px(8))
            self.overlay_label.pack()
            self.overlay.update_idletasks()
            if os.name == 'nt':
                import ctypes
                hwnd = ctypes.windll.user32.GetAncestor(self.overlay.winfo_id(), 2)
                kit_win.overlay_style(hwnd)
                self.overlay_hwnd = hwnd
        else:
            configure_changed(self.overlay_label, text=text)
        self.overlay.update_idletasks()
        w = self.overlay.winfo_reqwidth()
        if info and not info.get('minimised'):
            left, top, right, _ = info['rect']
            x, y = left + max(0, (right - left - w) // 2), top + px(40)
        else:
            x, y = self.root.winfo_rootx() + px(40), self.root.winfo_rooty() + px(40)
        position = (x, y)
        if getattr(self.overlay, '_position', None) != position:
            self.overlay.geometry(f'+{x}+{y}')
            self.overlay._position = position

    # ---- errors ----------------------------------------------------------------------------------------------------------
    def show_error(self):
        """One error window at a time: a new error replaces the text of the open one."""
        err = self.state.get('error')
        if not err or err == self.error_shown:
            return
        self.error_shown = err
        win = self.error_window
        try:
            fresh = win is None or not win.winfo_exists()
        except tk.TclError:
            fresh = True
        if fresh:
            win = tk.Toplevel(self.root, bg=BG)
            win.title(self.T('err.title'))
            if self.root.winfo_viewable():
                win.transient(self.root)
            watch_resizes(win)
            win.protocol('WM_DELETE_WINDOW', self.dismiss_error)
            win.bind('<Escape>', lambda e: self.dismiss_error())
            self.error_window = win
            win.minsize(px(420), px(240))
            self.place_dialog(win, px(700), px(380), dx=80, dy=80)
        for w in win.winfo_children():
            w.destroy()
        banner = th.Banner(win, bg=BG, size=13)
        banner.pack(fill='x', pady=(px(6), 0))
        banner.set(self.T('err.title'))
        row = Flow(win, bg=BG)
        row.pack(side='bottom', fill='x', padx=px(12), pady=(0, px(12)))
        box = th.Panel(win, edge=th.DANGER)
        box.pack(fill='both', expand=True, padx=px(12), pady=px(8))
        text = tk.Text(box.inner, width=60, height=10, bg=th.INSET, fg=th.INK, font=font(10), relief='flat',
                       wrap='word', padx=px(10), pady=px(8), highlightthickness=0)
        bar = ttk.Scrollbar(box.inner, orient='vertical', command=text.yview)
        text.configure(yscrollcommand=bar.set)
        bar.pack(side='right', fill='y')
        text.pack(fill='both', expand=True)
        text.insert('1.0', err.get(self.lang) or err.get('en') or '')
        text.configure(state='disabled')

        def remedy(name):
            self.dismiss_error()
            if name == 'retry':
                if self.state.get('role') == 'host':
                    self.send('host')
                else:
                    self.send('join', address=(self.state.get('settings') or {}).get('host_address', ''))
            elif name == 'advanced':
                if self.screen == 'start':
                    self.show_advanced(True)
                else:
                    self.advanced_open = True
            elif name in ('choose_iso', 'choose_bios'):
                self.choose_file(name.split('_')[1])
            elif name == 'compare_files':
                self.send('setup', disc_check='quick')
            elif name == 'logs':
                folder = self.state.get('run_dir') or str(kit_paths.RUNS)
                if os.name == 'nt':
                    os.startfile(folder)  # noqa: S606 - the player's own logs folder
        widgets = []
        for name in err.get('remedies') or []:
            if name == 'relay':
                continue
            widgets.append(self.button(row, self.T('remedy.' + name), lambda n=name: remedy(n),
                                       kind='secondary' if name == 'retry' else 'plain'))
        close = self.button(row, self.T('close'), self.dismiss_error, kind='primary')
        widgets.append(close)
        row.set_widgets(widgets, right=[close])

    def dismiss_error(self):
        self.close_error()
        self.send('dismiss')

    def close_error(self):
        win, self.error_window = self.error_window, None
        if win is not None:
            try:
                win.destroy()
            except tk.TclError:
                pass

    # ---- screenshots (tests: the lobby script's "shot" step) ---------------------------------------------------------------
    def shot(self, name):
        if not self.shots or os.name != 'nt':
            return None
        import ctypes
        self.shots.mkdir(parents=True, exist_ok=True)
        self.root.update()
        hwnd = ctypes.windll.user32.GetAncestor(self.root.winfo_id(), 2)
        png = kit_win.capture_png(hwnd)
        path = self.shots / f'{name}.png'
        if png:
            path.write_bytes(png)
        for extra, win in (('dialog', self.dialog), ('error', getattr(self, 'error_window', None))):
            try:
                if win is not None and win.winfo_exists():
                    win.update()
                    h = ctypes.windll.user32.GetAncestor(win.winfo_id(), 2)
                    data = kit_win.capture_png(h)
                    if data:
                        (self.shots / f'{name}-{extra}.png').write_bytes(data)
            except tk.TclError:
                pass
        if self.overlay is not None and self.overlay_hwnd:
            pc = self.state.get('pcsx2') or {}
            game, rect = kit_win.capture_pid(pc.get('pid'), pc.get('desktop'))
            top = kit_win.capture_png(self.overlay_hwnd)
            if game and top:
                import ctypes.wintypes as wt
                r = wt.RECT()
                ctypes.windll.user32.GetWindowRect(wt.HWND(self.overlay_hwnd), ctypes.byref(r))
                (self.shots / f'{name}-overlay-on-game.png').write_bytes(
                    composite(game, rect, top, (r.left, r.top, r.right, r.bottom)))
        return str(path)

    def ui_step(self, step):
        """Test scripts: what a player's mouse would do."""
        what = step['ui']
        if what == 'picker':
            self.open_picker(int(step.get('team', 0)), int(step.get('index', 0)))
        elif what == 'search' and self.picker:
            self.picker['search'].set(step.get('text', ''))
        elif what == 'pick' and self.picker:
            self.picker['pick'](int(step['char']))
            if 'colour' in step:
                self.picker['chosen']['k'] = int(step['colour']) - 1
        elif what == 'pick_ok' and self.picker:
            self.picker['ok']()
        elif what == 'stage_picker':
            self.open_stage_picker()
        elif what == 'rules':
            self.open_rules()
        elif what == 'display':
            self.open_display()
        elif what == 'close_dialog':
            self.close_dialog()
        elif what == 'lang':
            if step.get('value') != self.lang:
                self.toggle_lang()
        elif what == 'advanced':
            if self.screen == 'start':
                self.show_advanced(bool(step.get('open', True)))
            else:
                self.advanced_open = bool(step.get('open', True))
        elif what == 'close_error' and getattr(self, 'error_window', None) is not None:
            self.dismiss_error()
        elif what == 'click':
            widget = getattr(self, str(step.get('widget')), None)
            if widget is None or not widget.winfo_exists() or not widget.winfo_ismapped():
                raise RuntimeError(f'{step.get("widget")} is not on the screen')
            widget.invoke()

    def run(self):
        self.root.mainloop()
        return 0


def controls_card(m, lang):
    """'Switch target: tap R3 · Transform: R3 · ...' for this match's gameplay rules, in the lobby's language."""
    import localization
    tt = lambda key, **a: kit_text.t(key, lang, **a)
    button = lambda name: localization.value_label(name, lang)
    parts = []
    hold = m.get('lockon_hold_seconds', 0)
    switch = button(m.get('lockon_switch_button', 'r3'))
    parts.append(tt('card.switch_tap', button=switch) if not hold else tt('card.switch_hold', button=switch,
                                                                         seconds=f'{hold:g}'))
    if m.get('lockon_right_stick'):
        parts.append(tt('card.stick_alone') if m.get('lockon_right_stick_mode') == 'right_stick_alone' else
                     tt('card.stick_with', button=switch))
    if m.get('lockoff_enabled'):
        parts.append(tt('card.lockoff', button=button(m.get('lockoff_button', 'l3')),
                        seconds=f'{m.get("lockoff_hold_seconds", 0):g}'))
    parts.append(tt('card.transform'))
    if m.get('spectator_takeover_enabled'):
        parts.append(tt('card.takeover', button='L2 + Square' if m.get('lockon_switch_button') == 'square' else
                        'Square'))
    if m.get('revive_enabled'):
        parts.append(tt('card.revive', seconds=f'{m.get("revive_channel_seconds", 4):g}',
                        stocks=m.get('revive_stock_cost', 4)))
    parts.append(tt('card.pause'))
    return ' · '.join(parts)


def run(client, args, session_pid=None, restart=None):
    app = App(client, args, session_pid, restart)
    return app.run()
