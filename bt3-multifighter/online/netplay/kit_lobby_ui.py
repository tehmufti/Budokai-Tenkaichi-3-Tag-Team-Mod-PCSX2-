"""The online lobby window (Tk, standard library only; English and Spanish). The UI process of a kit: it shows the
session process's state and sends its commands (kit_ipc); it never touches the network, PINE or PCSX2 itself, so a
crash here does not end a match (start "Play online" again: it re-attaches).

Screens (kit 2.0): Start (name, EN/ES, Open / Join a room, files, controllers, Advanced), Check (this PC's
checklist), Room (the people in it - watching or playing -, the two teams or free-for-all columns the host builds on
the spot with any fighters and colours, the rules panel: stage, music, Duel Time, CPU level, referee, destructible,
the host's gameplay rules and this PC's own display settings; Ready / Start / Just watch / Leave, chat), the fighter
and stage pickers, Preparing, Sending / Loading, Fight (playing or watching, End match / Leave this match), Results
(Retry needs every player within 10 s, else everyone returns to the lobby). Waits over a second while
the game window is shown get a small always-on-top banner over it that never takes the focus (kit_win.overlay_style).
Disc names (fighters, stages, referees, the game's setting labels) stay as on the disc in both languages.
"""
import json
import os
import struct
import subprocess
import sys
import time
import tkinter as tk
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
import kit_win
from kit_text import t

BG, PANEL, CARD, INK, DIM, GOLD, RED, BLUE, GREEN = ('#0f1724', '#1b2638', '#24324a', '#eef2f8', '#9fb0c8', '#f5b83f',
                                                     '#c8414b', '#3f7fd6', '#4caf6a')
FONT = 'Segoe UI' if os.name == 'nt' else 'DejaVu Sans'
TIMES = (60, 90, 180, 240, 0)
FALLBACK = 30.0
DESIGN = (1220, 760)                     # the window's size at 96 DPI (100 %)
S = 1.0                                  # this screen's UI scale (App.fit_window)
PZ = 1                                   # portraits and stage pictures are drawn twice as large from 175 % on
SERVER_BROWSER_VISIBLE = False          # keep discovery available for later, but out of the player menus


def px(n):
    """A pixel size of the 96-DPI design at this screen's scale."""
    return int(round(n * S))


def font(size=10, bold=False):
    return (FONT, size, 'bold' if bold else 'normal')


def elide(text, width=64):
    """A long path as its start and its end."""
    text = str(text)
    return text if len(text) <= width else text[:22] + ' … ' + text[-(width - 25):]


def configure_changed(widget, **options):
    """Do not redraw an unchanged control on every session status packet."""
    changed = {key: value for key, value in options.items() if str(widget.cget(key)) != str(value)}
    if changed:
        widget.configure(**changed)


def wrap_label(label):
    """Use the space the layout gave a label, rather than a fixed design width."""
    label.configure(width=1, justify='left', anchor='w', wraplength=px(400))
    def resize(event):
        width = max(20, event.width - 4)
        if label.winfo_pixels(label.cget('wraplength')) != width:
            label.configure(wraplength=width)
    label.bind('<Configure>', resize, add='+')
    return label


class Flow(tk.Frame):
    """Buttons keep their full labels and move to another row when necessary."""
    def __init__(self, parent, **options):
        super().__init__(parent, **options)
        self.widgets, self.job, self.positions = [], None, None
        self.bind('<Configure>', lambda _: self.schedule())
        self.bind('<Destroy>', self.cancel, add='+')

    def set_widgets(self, widgets):
        widgets = list(widgets)
        if widgets == self.widgets:
            if self.positions is None or any((w.winfo_reqwidth(), w.winfo_reqheight()) != (width, height)
                                             for w, _, _, width, height in self.positions):
                self.schedule()
            return
        for widget in self.widgets:
            if widget not in widgets:
                widget.place_forget()
        self.widgets = widgets
        self.schedule()

    def add(self, widget):
        self.set_widgets(self.widgets + [widget])
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
        x, y, row_height, positions = 0, 0, 0, []
        for widget in self.widgets:
            if isinstance(widget, (tk.Button, tk.Label)):
                padding = 2 * sum(widget.winfo_pixels(widget.cget(key))
                                  for key in ('padx', 'borderwidth', 'highlightthickness'))
                wrap = max(20, width - 2 * px(3) - padding - 4)
                if widget.winfo_pixels(widget.cget('wraplength')) != wrap:
                    widget.configure(wraplength=wrap)
                if widget.winfo_reqwidth() + 2 * px(3) > width:
                    widget.configure(width=0)
            w, h = widget.winfo_reqwidth(), widget.winfo_reqheight()
            needed = w + 2 * px(3)
            if x and x + needed > width:
                x, y, row_height = 0, y + row_height + px(4), 0
            positions.append((widget, x + px(3), y + px(2), w, h))
            x, row_height = x + needed, max(row_height, h)
        if positions != self.positions:
            self.positions = positions
            for widget, x, y, w, h in positions:
                widget.place(x=x, y=y, width=w, height=h)
        height = y + row_height + px(4) if self.widgets else 0
        if int(self.cget('height')) != height:
            self.configure(height=height)


class ScrollPanel(tk.Frame):
    """Width follows the window; overflowing height stays reachable by scrolling."""
    def __init__(self, parent, bg=BG, height=400, **options):
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

    def cancel(self, event):
        if event.widget is self and self.job:
            self.after_cancel(self.job)
            self.job = None

    def schedule(self):
        if not self.job and self.winfo_exists():
            self.job = self.after_idle(self.arrange)

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
    tw, th, top = png_decode(top_png)
    out = bytearray(base)
    dx, dy = top_rect[0] - base_rect[0], top_rect[1] - base_rect[1]
    for y in range(th):
        yy = y + dy
        if not 0 <= yy < bh:
            continue
        x0, x1 = max(0, dx), min(bw, dx + tw)
        if x0 >= x1:
            continue
        out[(yy * bw + x0) * 4:(yy * bw + x1) * 4] = top[(y * tw + x0 - dx) * 4:(y * tw + x1 - dx) * 4]
    return png_encode(bw, bh, bytes(out))


class App:
    def __init__(self, client, args, session_pid=None, restart=None):
        self.client, self.args, self.session_pid = client, args, session_pid
        self.state = {}
        self.lang = args.lang or 'en'
        self.root = tk.Tk()
        self.root.title(t('app.title', self.lang))
        self.root.configure(bg=BG)
        self.fit_window()
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)
        self.style()
        self.catalog = None
        self.images = {}
        self.screen = None
        self.sig = None
        self.files = {}
        self.chat_rows = []
        self.logs = []
        self.advanced_open = False
        self.dialog = None
        self.error_shown = None
        self.overlay = None
        self.overlay_hwnd = None
        self.pads_text = None
        self.pads_seen = set()
        self.picker = None
        self.shots = Path(args.shot_dir) if args.shot_dir else None
        steps = kit_lobby_console.bot_steps(args)
        if args.lobby_script:
            steps += json.loads(Path(args.lobby_script).read_text(encoding='utf-8'))
        self.script = kit_lobby_console.Script(steps, self.send, self.shot, self.log,
                                               out=self.shots / 'script.json' if self.shots else None,
                                               ui=self.ui_step) if steps else None
        self.bot = kit_lobby_console.AutoBot(args, self.send) if (args.auto_ready or args.auto_vote) else None
        self.viewport = ScrollPanel(self.root)
        self.viewport.pack(fill='both', expand=True)
        self.body = self.viewport.content
        self.lobby_layout = None
        self.root.bind('<Configure>', self.resize, add='+')
        self.root.bind_all('<MouseWheel>', self.scroll, add='+')
        self.root.bind_all('<Button-4>', self.scroll, add='+')
        self.root.bind_all('<Button-5>', self.scroll, add='+')
        self.root.after(30, self.pump)
        self.root.after(500, self.poll_pads)
        self.send('files')

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
        S = scale * fit
        PZ = 2 if S >= 1.75 else 1
        if self.args.ui_geometry:
            self.root.geometry(self.args.ui_geometry)
        else:
            self.root.geometry(f'{int(w * fit)}x{int(h * fit)}+{px(10)}+{px(10)}')
        self.root.minsize(min(px(640), sw - 40), min(px(360), sh - 80))

    def resize(self, event):
        self.viewport.schedule()
        if self.screen == 'lobby' and getattr(self, 'lobby_mid', None) is not None:
            if event.widget in (self.root, self.body, self.lobby_mid):
                self.arrange_lobby()
            for panel in self.lobby_panels:
                panel.schedule()

    def scroll(self, event):
        units = -1 if getattr(event, 'num', None) == 4 or getattr(event, 'delta', 0) > 0 else 1
        widget = event.widget
        while widget is not None:
            if isinstance(widget, ScrollPanel):
                first, last = widget.canvas.yview()
                if (units < 0 and first > 0.001) or (units > 0 and last < 0.999):
                    widget.canvas.yview_scroll(units * 3, 'units')
                    return 'break'
            # The portrait picker has its own scrolling canvas.
            elif isinstance(widget, tk.Canvas) and widget.cget('yscrollcommand'):
                first, last = widget.yview()
                if (units < 0 and first > 0.001) or (units > 0 and last < 0.999):
                    widget.yview_scroll(units * 3, 'units')
                    return 'break'
            widget = getattr(widget, 'master', None)

    def style(self):
        s = ttk.Style(self.root)
        try:
            s.theme_use('clam')
        except tk.TclError:
            pass
        s.configure('TCombobox', fieldbackground=CARD, background=CARD, foreground=INK, arrowcolor=INK,
                    bordercolor=PANEL, lightcolor=CARD, darkcolor=CARD)
        s.map('TCombobox', fieldbackground=[('readonly', CARD), ('disabled', PANEL)],
              foreground=[('readonly', INK), ('disabled', DIM)], background=[('readonly', CARD), ('disabled', PANEL)],
              selectbackground=[('readonly', CARD)], selectforeground=[('readonly', INK)])
        s.configure('TEntry', fieldbackground=CARD, foreground=INK, insertcolor=INK)
        s.configure('Horizontal.TProgressbar', background=GOLD, troughcolor=CARD, bordercolor=PANEL)
        s.configure('TCheckbutton', background=PANEL, foreground=INK)
        s.configure('Treeview', background=CARD, fieldbackground=CARD, foreground=INK,
                    rowheight=px(26), font=font(9))
        s.configure('Treeview.Heading', background=PANEL, foreground=INK, font=font(9, True))
        s.map('Treeview', background=[('selected', GOLD)], foreground=[('selected', '#101010')])
        self.root.option_add('*TCombobox*Listbox.background', CARD)
        self.root.option_add('*TCombobox*Listbox.foreground', INK)
        self.root.option_add('*TCombobox*Listbox.selectBackground', GOLD)
        self.root.option_add('*TCombobox*Listbox.selectForeground', '#101010')

    def send(self, cmd, **fields):
        self.client.send(cmd, **fields)

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
                        raise
                    except Exception:  # noqa: BLE001 - a drawing bug must not stop the window (and its script)
                        import traceback
                        self.log('UI ERROR: ' + traceback.format_exc())
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
                    self.root.destroy()
                    return
            if self.client.closed:
                self.lost()
                return
            if self.script:
                self.script.feed(self.state)
                self.script.tick()
            if self.bot:
                self.bot.tick(self.state)
            self.tick_screen()
        except tk.TclError:
            return
        self.root.after(40, self.pump)

    def lost(self):
        self.clear()
        tk.Label(self.body, text=self.T('session.lost'), bg=BG, fg=RED, font=font(14, True)).pack(pady=80)
        self.root.after(8000, self.root.destroy)

    def on_close(self):
        self.send('quit')
        self.root.after(300, self.root.destroy)

    # ---- state -> screens ------------------------------------------------------------------------------------------------
    def on_state(self, state):
        self.state = state
        if state.get('lang') and state['lang'] != self.lang:
            self.lang = state['lang']
            self.root.title(t('app.title', self.lang))
            self.screen = None
        cat = state.get('catalog')
        if cat and (self.catalog is None or self.catalog.c.get('dir') != cat['dir']):
            try:
                self.catalog = kit_catalog.View(kit_catalog.read_dir(cat['dir']))
            except (OSError, ValueError):
                self.catalog = None
        phase = state.get('phase') or 'start'
        screen = {'start': 'start', 'check': 'check', 'lobby': 'lobby', 'preparing': 'prep', 'sending': 'prep',
                  'loading': 'prep', 'fight': 'fight', 'results': 'results'}.get(phase, 'start')
        if screen != self.screen:
            self.screen = screen
            self.sig = None
            getattr(self, 'build_' + screen)()
        getattr(self, 'update_' + screen)()
        self.update_overlay()
        self.show_error()

    def clear(self):
        self.close_dialog()
        self.lobby_layout = None
        for w in self.body.winfo_children():
            w.destroy()
        self.viewport.canvas.yview_moveto(0)

    def tick_screen(self):
        if self.screen == 'results':
            self.update_results()

    def image(self, rel, zoom=1):
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
        """A portrait at half size (the lobby's fighter rows)."""
        key = (rel, 'small')
        if key not in self.images and self.catalog:
            try:
                im = tk.PhotoImage(master=self.root, data=(Path(self.catalog.c['dir']) / rel).read_bytes())
                self.images[key] = im.subsample(2, 2) if PZ == 1 else im
            except (OSError, tk.TclError):
                self.images[key] = None
        return self.images.get(key)

    def header(self, parent, title, line=None):
        head = tk.Frame(parent, bg=BG)
        head.pack(fill='x', padx=16, pady=(12, 4))
        top = tk.Frame(head, bg=BG)
        top.pack(fill='x')
        tk.Label(top, text=title, bg=BG, fg=GOLD, font=font(16, True)).pack(side='left')
        self.head_line = wrap_label(tk.Label(head, text=line or '', bg=BG, fg=DIM, font=font(10)))
        self.head_line.pack(fill='x', pady=(2, 0))
        tk.Label(top, text=self.T('kit', version=self.state.get('kit', '')), bg=BG, fg=DIM,
                 font=font(8)).pack(side='right')
        return top

    def button(self, parent, text, command, color=CARD, fg=INK, big=False, state='normal', width=None):
        b = tk.Button(parent, text=text, command=command, bg=color, fg=fg, activebackground=GOLD,
                      activeforeground='#101010', relief='flat', bd=0, font=font(12 if big else 10, True),
                      padx=14 if big else 10, pady=8 if big else 4, cursor='hand2', state=state,
                      disabledforeground='#5b6b84')
        if width:
            b.configure(width=width)
        return b

    def confirm(self, text):
        from tkinter import messagebox
        return messagebox.askyesno(self.T('app.title'), text, parent=self.root)

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

    # ---- S1 start --------------------------------------------------------------------------------------------------------
    def build_start(self):
        self.clear()
        st = self.state
        profile = st.get('profile') or {}
        cfg = st.get('settings') or {}
        head = self.header(self.body, self.T('s1.title'))
        tk.Button(head, text=self.T('lang.other'), command=self.toggle_lang, bg=CARD, fg=INK, relief='flat',
                  font=font(9, True), cursor='hand2').pack(side='right', padx=(0, 12))
        wrap_label(tk.Label(self.body, text=self.T('s1.subtitle'), bg=BG, fg=DIM,
                            font=font(10))).pack(fill='x', padx=18)
        main = tk.Frame(self.body, bg=PANEL, highlightbackground=GOLD, highlightthickness=2)
        main.pack(fill='x', padx=16, pady=6)
        row = tk.Frame(main, bg=PANEL)
        row.pack(fill='x', padx=14, pady=(12, 6))
        wrap_label(tk.Label(row, text=self.T('s1.name'), bg=PANEL, fg=INK,
                            font=font(10, True))).pack(fill='x')
        self.name_var = tk.StringVar(value=profile.get('name') or '')
        ttk.Entry(row, textvariable=self.name_var, width=20, font=font(11)).pack(fill='x', pady=4)
        wrap_label(tk.Label(row, text=self.T('s1.name_hint'), bg=PANEL, fg=DIM,
                            font=font(9))).pack(fill='x')
        actions = Flow(main, bg=PANEL)
        actions.pack(fill='x', padx=14, pady=8)
        self.host_button = actions.add(self.button(actions, self.T('s1.host'), self.do_host, color=GOLD,
                                                   fg='#101010', big=True))
        self.join_button = actions.add(self.button(actions, self.T('s1.join'), self.do_join, color=BLUE, big=True))
        recent = []
        try:
            recent = json.loads((kit_paths.DATA / 'recent-hosts.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass
        self.recent_hosts = [s for s in recent if isinstance(s, str)] if isinstance(recent, list) else []
        self.addr_var = tk.StringVar(value=cfg.get('host_address') or (self.recent_hosts[0] if self.recent_hosts else ''))
        self.password_var = tk.StringVar()
        self.listed_var = None
        if SERVER_BROWSER_VISIBLE:
            online = tk.Frame(main, bg=PANEL)
            online.pack(fill='x', padx=14, pady=4)
            tk.Label(online, text=self.T('browser.password'), bg=PANEL, fg=INK, font=font(9)).pack(side='left')
            ttk.Entry(online, textvariable=self.password_var, show='*', width=18).pack(side='left', padx=6)
            self.listed_var = tk.BooleanVar(value=bool(cfg.get('listed')))
            ttk.Checkbutton(online, text=self.T('browser.listed'), variable=self.listed_var).pack(side='left', padx=8)
            tk.Label(online, text=self.T('browser.name'), bg=PANEL, fg=INK, font=font(9)).pack(side='left')
            self.room_name_var = tk.StringVar(value=cfg.get('room_name') or '')
            ttk.Entry(online, textvariable=self.room_name_var, width=20).pack(side='left', padx=6)
            self.button(online, self.T('browser.open'), self.open_browser).pack(side='left', padx=6)
            directory = tk.Frame(main, bg=PANEL)
            directory.pack(fill='x', padx=14)
            tk.Label(directory, text=self.T('browser.directory'), bg=PANEL, fg=DIM, font=font(8)).pack(side='left')
            self.directory_var = tk.StringVar(value=cfg.get('directory') or '')
            ttk.Entry(directory, textvariable=self.directory_var, width=46).pack(side='left', padx=6)
        self.files_box = tk.Frame(main, bg=PANEL)
        self.files_box.pack(fill='x', padx=14, pady=(6, 2))
        self.draw_files()
        pads = tk.Frame(main, bg=PANEL)
        pads.pack(fill='x', padx=14, pady=(4, 10))
        tk.Label(pads, text=self.T('s1.controllers'), bg=PANEL, fg=INK, font=font(10, True)).pack(side='left')
        self.pads_label = wrap_label(tk.Label(pads, text='', bg=PANEL, fg=DIM, font=font(10)))
        self.pads_label.pack(fill='x', padx=8)
        self.pads_text = None
        adv = tk.Frame(self.body, bg=BG)
        adv.pack(fill='x', padx=16)
        tk.Button(adv, text=('▾ ' if self.advanced_open else '▸ ') + self.T('s1.advanced'), command=self.toggle_adv,
                  bg=BG, fg=DIM, relief='flat', font=font(10, True), cursor='hand2').pack(anchor='w')
        if self.advanced_open:
            self.draw_advanced(adv)
        self.start_status = wrap_label(tk.Label(self.body, text='', bg=BG, fg=DIM, font=font(10)))
        self.start_status.pack(fill='x', padx=18, pady=6)

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
            wrap_label(tk.Label(box, text=self.T('s1.integrated'), bg=PANEL, fg=GREEN,
                                font=font(10, True))).pack(fill='x')
            for key, field in (('s1.iso', 'iso'), ('s1.bios', 'bios')):
                wrap_label(tk.Label(box, text=f'    {self.T(key)} {elide(f.get(field)) if f.get(field) else self.T("s1.not_chosen")}',
                                    bg=PANEL, fg=INK, font=font(9))).pack(fill='x')
            return
        if not f.get('iso') or not f.get('bios'):
            tk.Label(box, text=self.T('s1.first_run'), bg=PANEL, fg=GOLD, font=font(10, True)).pack(anchor='w')
        lines = [('s1.iso', 'iso'), ('s1.bios', 'bios'), ('s1.install', 'install')]
        label_width = max(len(self.T(key)) for key, _ in lines) + 2
        for key, field in lines:
            row = tk.Frame(box, bg=PANEL)
            row.pack(fill='x', pady=1)
            tk.Label(row, text=self.T(key), bg=PANEL, fg=INK, font=font(10, True), width=label_width,
                     anchor='w').pack(side='left')
            value = elide(f.get(field)) if f.get(field) else self.T('s1.not_chosen')
            tk.Label(row, text=value, bg=PANEL, fg=INK if f.get(field) else DIM, font=font(9), anchor='w').pack(
                side='left', padx=6)
            self.button(row, self.T('s1.choose'), lambda fld=field: self.choose_file(fld)).pack(side='right')
            if field == 'iso' and f.get('iso'):
                region = f.get('iso_region')
                if f.get('iso_error'):
                    text, color = f['iso_error'].get('title_' + self.lang) or f['iso_error'].get('code'), RED
                elif region is None and f.get('iso_serial'):
                    text, color = self.T('s1.iso_ok', serial=f.get('iso_serial')), GREEN
                elif region in ('europe', 'japan'):
                    text, color = self.T('s1.iso_' + region), RED
                elif region == 'other':
                    text, color = self.T('s1.iso_other', serial=f.get('iso_serial')), RED
                else:
                    text, color = '', DIM
                tk.Label(box, text='    ' + text, bg=PANEL, fg=color, font=font(9, True)).pack(anchor='w')
            if field == 'install':
                info = f.get('install_info') or {}
                if info.get('refused'):
                    why = self.T('why.refused_code', detail=info['refused_regions']) if info.get('refused_regions') \
                        else self.T('why.refused')
                    text, color = self.T('s1.install_refused', why=why), RED
                elif info.get('error'):
                    why = info.get('error_es') if self.lang == 'es' and info.get('error_es') else info.get('error')
                    text, color = self.T('s1.install_refused', why=why), RED
                elif info.get('build') == 'known':
                    text, color = self.T('s1.install_ok', version=info.get('version')), GREEN
                elif info.get('build') == 'candidate':
                    text, color = self.T('s1.install_candidate', version=info.get('version')), GOLD
                else:
                    text, color = '', DIM
                if text:
                    tk.Label(box, text='    ' + text, bg=PANEL, fg=color, font=font(9, True), wraplength=px(1000),
                             justify='left').pack(anchor='w')
                for found in (f.get('install_found') or [])[:3]:
                    line = tk.Frame(box, bg=PANEL)
                    line.pack(fill='x')
                    tk.Label(line, text='    ' + self.T('s1.install_found', path=elide(found['root'], 70),
                                                         version=found.get('version') or '?'),
                             bg=PANEL, fg=INK if found.get('ok') else DIM, font=font(9)).pack(side='left')
                    if found.get('ok'):
                        self.button(line, self.T('s1.use'),
                                    lambda r=found['root']: (self.send('setup', install=r), self.send('files'))).pack(
                            side='left', padx=6)

    def choose_file(self, field):
        if field == 'install':
            path = filedialog.askdirectory(title=self.T('s1.install'))
        else:
            types = [('ISO', '*.iso'), ('*', '*.*')] if field == 'iso' else [('BIOS', '*.bin'), ('*', '*.*')]
            path = filedialog.askopenfilename(title=self.T('s1.' + field), filetypes=types)
        if path:
            self.send('setup', **{field: path})
            self.send('files')

    def toggle_lang(self):
        self.lang = 'es' if self.lang == 'en' else 'en'
        self.send('setup', lang=self.lang)
        self.screen = None
        self.on_state(dict(self.state, lang=self.lang))

    def toggle_adv(self):
        self.save_start_fields()
        self.advanced_open = not self.advanced_open
        self.build_start()

    def draw_advanced(self, parent):
        cfg = self.state.get('settings') or {}
        box = tk.Frame(parent, bg=PANEL)
        box.pack(fill='x', pady=4)
        box.columnconfigure(0, weight=1)
        box.columnconfigure(1, weight=1)
        self.adv = {}
        rows = [('adv.port', 'port', str(cfg.get('port') or 47400)), ('adv.delay', 'delay', str(cfg.get('delay') or ''))]
        for i, (key, field, value) in enumerate(rows):
            wrap_label(tk.Label(box, text=self.T(key), bg=PANEL, fg=INK, font=font(9))).grid(
                row=i, column=0, sticky='ew', padx=10, pady=3)
            var = tk.StringVar(value=value)
            ttk.Entry(box, textvariable=var, width=1).grid(row=i, column=1, sticky='ew', padx=4)
            self.adv[field] = var
        wrap_label(tk.Label(box, text=self.T('adv.renderer'), bg=PANEL, fg=INK,
                            font=font(9))).grid(row=2, column=0, sticky='ew', padx=10, pady=3)
        self.adv['renderer'] = tk.StringVar(value=cfg.get('renderer') or 'default')
        ttk.Combobox(box, textvariable=self.adv['renderer'], state='readonly', width=1,
                     values=['default', 'auto', 'd3d11', 'd3d12', 'vulkan', 'opengl', 'software']).grid(
            row=2, column=1, sticky='ew', padx=4)
        wrap_label(tk.Label(box, text=self.T('adv.pad'), bg=PANEL, fg=INK,
                            font=font(9))).grid(row=3, column=0, sticky='ew', padx=10)
        pads = ['SDL-0', 'SDL-1', 'keyboard']
        self.pad_names = {self.T('adv.pad.' + p): p for p in pads}
        self.adv['pad'] = tk.StringVar(value=self.T('adv.pad.' + (cfg.get('pad') or 'SDL-0')))
        ttk.Combobox(box, textvariable=self.adv['pad'], state='readonly', width=1,
                     values=list(self.pad_names)).grid(row=3, column=1, sticky='ew', padx=4)
        self.adv['fullscreen'] = tk.BooleanVar(value=bool(cfg.get('fullscreen')))
        ttk.Checkbutton(box, text=self.T('adv.fullscreen'), variable=self.adv['fullscreen']).grid(
            row=4, column=0, columnspan=2, sticky='w', padx=10, pady=3)
        wrap_label(tk.Label(box, text=self.T('adv.local'), bg=PANEL, fg=DIM,
                            font=font(8))).grid(row=5, column=0, columnspan=2, sticky='ew', padx=10)
        if not SERVER_BROWSER_VISIBLE:
            wrap_label(tk.Label(box, text=self.T('browser.password'), bg=PANEL, fg=INK,
                                font=font(9))).grid(row=6, column=0, sticky='ew', padx=10, pady=3)
            ttk.Entry(box, textvariable=self.password_var, show='*', width=1).grid(row=6, column=1, sticky='ew', padx=4)

    def save_start_fields(self):
        fields = {}
        if getattr(self, 'name_var', None) is not None:
            fields['name'] = self.name_var.get().strip()[:16]
        if getattr(self, 'addr_var', None) is not None:
            fields['host_address'] = self.addr_var.get().strip()
        if getattr(self, 'listed_var', None) is not None:
            fields.update(listed=bool(self.listed_var.get()), room_name=self.room_name_var.get().strip()[:64],
                          directory=self.directory_var.get().strip())
        elif not SERVER_BROWSER_VISIBLE:
            fields['listed'] = False
        if self.advanced_open and getattr(self, 'adv', None):
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
        self.save_start_fields()
        self.send('host', password=self.password_var.get())
        self.password_var.set('')

    def do_join(self):
        self.close_dialog()
        win = tk.Toplevel(self.root, bg=BG)
        self.dialog = win
        win.title(self.T('s1.join'))
        win.transient(self.root)
        win.resizable(False, False)
        win.geometry('+%d+%d' % (self.root.winfo_rootx() + px(70), self.root.winfo_rooty() + px(100)))
        box = tk.Frame(win, bg=PANEL, highlightbackground=BLUE, highlightthickness=2)
        box.pack(fill='both', expand=True, padx=12, pady=12)
        tk.Label(box, text=self.T('s1.address'), bg=PANEL, fg=INK, font=font(11, True)).pack(
            anchor='w', padx=16, pady=(14, 4))
        address = tk.StringVar(value=self.addr_var.get())
        entry = ttk.Combobox(box, textvariable=address, values=self.recent_hosts, width=42, font=font(11))
        entry.pack(fill='x', padx=16)
        tk.Label(box, text=self.T('join.address_hint'), bg=PANEL, fg=DIM, font=font(9),
                 wraplength=px(470), justify='left').pack(anchor='w', padx=16, pady=(6, 12))
        tk.Label(box, text=self.T('browser.password'), bg=PANEL, fg=INK, font=font(9)).pack(anchor='w', padx=16)
        password = tk.StringVar(value=self.password_var.get())
        ttk.Entry(box, textvariable=password, show='*', width=24).pack(anchor='w', padx=16, pady=(4, 6))
        status = tk.Label(box, text='', bg=PANEL, fg=RED, font=font(9), wraplength=px(470), justify='left')
        status.pack(anchor='w', padx=16)

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
            self.addr_var.set(raw)
            self.save_start_fields()
            self.password_var.set('')
            self.close_dialog()
            self.send('join', address=raw, password=secret)

        buttons = tk.Frame(box, bg=PANEL)
        buttons.pack(fill='x', padx=16, pady=(10, 14))
        self.button(buttons, self.T('cancel'), self.close_dialog).pack(side='left')
        self.button(buttons, self.T('s1.join'), submit, color=BLUE, big=True).pack(side='right')
        win.protocol('WM_DELETE_WINDOW', self.close_dialog)
        win.bind('<Escape>', lambda e: self.close_dialog())
        win.bind('<Return>', lambda e: submit())
        win.grab_set()
        entry.focus_set()
        entry.selection_range(0, 'end')

    def open_browser(self):
        if not SERVER_BROWSER_VISIBLE:
            return
        self.close_dialog()
        win = tk.Toplevel(self.root, bg=BG)
        self.dialog = win
        win.title(self.T('browser.open'))
        win.geometry('850x410')
        rows = {}
        columns = ('name', 'disc', 'players', 'phase', 'password', 'source')
        tree = ttk.Treeview(win, columns=columns, show='headings', height=11)
        for key in columns:
            tree.heading(key, text=self.T('browser.protected' if key == 'password' else 'browser.' + key))
            tree.column(key, width=120 if key != 'name' else 190)
        tree.pack(fill='both', expand=True, padx=10, pady=10)
        status = tk.Label(win, text=self.T('browser.searching'), bg=BG, fg=DIM, wraplength=800)
        status.pack(fill='x', padx=10)
        result = queue.Queue()

        def refresh():
            status.configure(text=self.T('browser.searching'))
            url = self.directory_var.get().strip()
            def work():
                try:
                    result.put(kit_browser.discover(url))
                except Exception as error:
                    result.put(dict(rooms=[], errors=[str(error)]))
            threading.Thread(target=work, daemon=True).start()

        def poll():
            if not win.winfo_exists():
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
        self.button(buttons, self.T('browser.choose'), choose, color=GOLD, fg='#101010').pack(side='right')
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
        self.root.after(250, self.poll_pads)

    def update_start(self):
        status = getattr(self, 'start_status', None)
        if status is not None and status.winfo_exists():
            notice = self.state.get('notice')
            text = kit_text.notice_text(notice['key'], self.lang, notice.get('args')) if notice else \
                (self.logs[-1] if self.logs else '')
            status.configure(text=text)

    # ---- S2 check --------------------------------------------------------------------------------------------------------
    def build_check(self):
        self.clear()
        self.header(self.body, self.T('s2.title'))
        self.check_box = tk.Frame(self.body, bg=PANEL)
        self.check_box.pack(fill='x', padx=16, pady=10)
        self.check_note = wrap_label(tk.Label(self.body, text='', bg=BG, fg=DIM, font=font(10)))
        self.check_note.pack(fill='x', padx=18)

    def update_check(self):
        checks = self.state.get('checks') or []
        sig = (str(self.check_box), self.lang, tuple(item['key'] for item in checks))
        if sig != getattr(self, 'check_sig', None):
            self.check_sig = sig
            for w in self.check_box.winfo_children():
                w.destroy()
            self.check_rows = []
            for item in checks:
                row = tk.Frame(self.check_box, bg=PANEL)
                row.pack(fill='x', padx=12, pady=3)
                title = wrap_label(tk.Label(row, bg=PANEL, font=font(10, True)))
                title.pack(fill='x')
                note = wrap_label(tk.Label(row, bg=PANEL, fg=DIM, font=font(9)))
                note.pack(fill='x')
                self.check_rows.append((title, note))
        for item, (title, note) in zip(checks, self.check_rows):
            ok = item.get('ok')
            mark, color = ('✓', GREEN) if ok else ('…', GOLD) if ok is None else ('✗', RED)
            configure_changed(title, text=mark + ' ' + self.T('check.' + item['key']), fg=color)
            configure_changed(note, text=item.get('note') or '')
        settings = self.state.get('settings') or {}
        if self.state.get('role') == 'guest' and settings.get('host_address'):
            configure_changed(self.check_note, text=self.T('s2.connecting', address=settings['host_address']))
        else:
            configure_changed(self.check_note, text=self.logs[-1] if self.logs else '')

    # ---- S3 the room ------------------------------------------------------------------------------------------------------
    def build_lobby(self):
        self.clear()
        self.header(self.body, self.T('room.title'))
        self.build_bottom(self.body)
        self.notice_label = wrap_label(tk.Label(self.body, text='', bg=BG, fg=GOLD, font=font(10, True)))
        self.notice_label.pack(side='bottom', fill='x', padx=18, pady=(4, 0))
        mid = tk.Frame(self.body, bg=BG)
        mid.pack(fill='both', expand=True, padx=16)
        self.lobby_mid = mid
        self.lobby_panels = [ScrollPanel(mid, bg=PANEL, height=430, highlightbackground=color, highlightthickness=2)
                             for color in (BLUE, GOLD, RED)]
        self.people, self.teams, self.rules_box = [panel.content for panel in self.lobby_panels]
        self.arrange_lobby()
        self.sigs = {}

    def arrange_lobby(self):
        wide = self.body.winfo_width() >= px(1130)
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
            if wide:
                panel.canvas.configure(height=px(430))
            panel.canvas.yview_moveto(0)
            panel.schedule()
        if wide:
            for i, (panel, weight) in enumerate(zip(self.lobby_panels, (18, 54, 28))):
                mid.columnconfigure(i, weight=weight, uniform='lobby')
                panel.grid(row=0, column=i, sticky='nsew', padx=4)
            mid.rowconfigure(0, weight=1)
        else:
            mid.columnconfigure(0, weight=1)
            # Keep the fighters first when the side panels no longer fit.
            for row, index in enumerate((1, 0, 2)):
                self.lobby_panels[index].grid(row=row, column=0, sticky='ew', padx=4, pady=4)

    def build_bottom(self, parent):
        foot = tk.Frame(parent, bg=BG)
        foot.pack(side='bottom', fill='x', padx=16, pady=8)
        self.start_hint = wrap_label(tk.Label(foot, text='', bg=BG, fg=DIM, font=font(9)))
        self.start_hint.pack(fill='x')
        buttons = Flow(foot, bg=BG)
        buttons.pack(fill='x', pady=(2, 6))
        self.lobby_buttons = buttons
        self.ready_button = self.button(buttons, self.T('room.ready_btn'), self.toggle_ready, color=GOLD,
                                        fg='#101010', big=True, width=14)
        self.start_button = self.button(buttons, self.T('room.start'), lambda: self.send('start'), color=GREEN,
                                        fg='#101010', big=True, width=16)
        self.watch_button = self.button(buttons, self.T('room.spectate'), lambda: self.send('unclaim'), big=True)
        self.leave_button = self.button(buttons, self.T('room.close') if self.is_host() else self.T('room.leave'),
                                        self.leave, big=True)
        self.back_hub_button = self.button(buttons, self.T('room.back_hub'), lambda: self.send('back_to_hub'))
        chat = tk.Frame(foot, bg=BG)
        chat.pack(fill='x')
        self.chat_text = tk.Text(chat, height=3, width=30, bg=PANEL, fg=INK, relief='flat', font=font(9),
                                 wrap='word', state='disabled')
        self.chat_text.pack(fill='x')
        row = tk.Frame(chat, bg=BG)
        row.pack(fill='x', pady=(4, 0))
        tk.Label(row, text=self.T('lobby.chat'), bg=BG, fg=INK, font=font(9, True)).pack(side='left')
        self.chat_var = tk.StringVar()
        entry = ttk.Entry(row, textvariable=self.chat_var, width=20)
        entry.pack(side='left', padx=6, fill='x', expand=True)
        entry.bind('<Return>', lambda e: self.send_chat())
        self.button(row, self.T('lobby.send'), self.send_chat).pack(side='left')
        self.draw_chat()

    def send_chat(self):
        text = self.chat_var.get().strip()
        if text:
            self.send('chat', text=text)
            self.chat_var.set('')

    def draw_chat(self):
        box = getattr(self, 'chat_text', None)
        if box is None or not box.winfo_exists():
            return
        sig = (str(box), json.dumps(self.chat_rows[-30:], sort_keys=True))
        if sig == getattr(self, 'chat_sig', None):
            return
        self.chat_sig = sig
        box.configure(state='normal')
        box.delete('1.0', 'end')
        for row in self.chat_rows[-30:]:
            box.insert('end', f'{row.get("at", "")} {row.get("who")}: {row.get("text")}\n')
        box.see('end')
        box.configure(state='disabled')

    def update_lobby(self):
        st, lob = self.state, self.lobby()
        if not lob:
            configure_changed(self.head_line, text=self.T('lobby.waiting_lobby'))
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
        configure_changed(self.head_line, text=line)
        members, match = self.members(), self.match()
        identity = [self.me(), self.is_host(), self.lang]
        # Ping, Ready and preparation telemetry update existing labels. They must
        # not destroy entries, comboboxes, portraits or an open equipment picker.
        parts = dict(people=json.dumps([sorted(members), identity]),
                     teams=json.dumps([match.get('teams'), match.get('mode'), match.get('type'),
                                       [(i, m['name']) for i, m in sorted(members.items())],
                                       lob.get('phase'), identity, self.catalog.c.get('dir') if self.catalog else None]),
                     rules=json.dumps([{k: match.get(k) for k in ('stage', 'bgm', 'native', 'services', 'gameplay')},
                                       lob.get('phase'), identity, st.get('services'),
                                       (lob.get('room') or {}).get('drop_load_failures'),
                                       self.catalog.c.get('dir') if self.catalog else None]))
        if parts['people'] != self.sigs.get('people'):
            self.sigs['people'] = parts['people']
            self.draw_people()
        if parts['teams'] != self.sigs.get('teams'):
            self.sigs['teams'] = parts['teams']
            self.draw_teams()
        if parts['rules'] != self.sigs.get('rules'):
            self.sigs['rules'] = parts['rules']
            self.draw_rules()
        self.update_people()
        configure_changed(self.warm_label, text=self.warm_text(lob.get('warm') or {}))
        self.update_buttons()
        self.show_notice()

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
        tk.Label(self.people, text=self.T('room.members'), bg=PANEL, fg=GOLD, font=font(11, True)).pack(
            anchor='w', padx=10, pady=(8, 4))
        self.member_labels = {}
        for ident, m in sorted(self.members().items()):
            box = tk.Frame(self.people, bg=CARD)
            box.pack(fill='x', padx=8, pady=2)
            name = wrap_label(tk.Label(box, bg=CARD, fg=GOLD if ident == self.me() else INK, font=font(10, True)))
            name.pack(fill='x', padx=6, pady=(3, 0))
            line = tk.Frame(box, bg=CARD)
            line.pack(fill='x', padx=6, pady=(0, 3))
            status = wrap_label(tk.Label(line, bg=CARD, fg=DIM, font=font(9)))
            status.pack(fill='x')
            self.member_labels[ident] = name, status
            if self.is_host() and ident != 1:
                tk.Button(line, text=self.T('room.kick'), bg=CARD, fg=RED, relief='flat', font=font(8, True),
                          cursor='hand2', command=lambda i=ident: self.send('kick', member=i)).pack(anchor='e')
        row = tk.Frame(self.people, bg=PANEL)
        row.pack(fill='x', padx=8, pady=(10, 4))
        tk.Label(row, text=self.T('room.your_name'), bg=PANEL, fg=DIM, font=font(8)).pack(anchor='w')
        self.self_name = self.name_of(self.me())
        self.rename_var = tk.StringVar(value=draft if draft is not None and old_name == self.self_name else self.self_name)
        entry = ttk.Entry(row, textvariable=self.rename_var, width=16)
        self.rename_entry = entry
        entry.pack(fill='x', pady=2)
        entry.bind('<Return>', lambda e: self.rename())
        self.button(row, self.T('room.rename'), self.rename).pack(anchor='w', pady=2)

    def update_people(self):
        for ident, m in self.members().items():
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
                              fg=GREEN if at and m.get('ready') else DIM)
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
        for w in self.teams.winfo_children():
            w.destroy()
        match = self.match()
        host = self.is_host() and self.lobby().get('phase') == 'lobby'
        start = Flow(self.teams, bg=PANEL)
        start.pack(fill='x', padx=10, pady=(8, 0))
        start.add(tk.Label(start, text=self.T('room.start_in'), bg=PANEL, fg=INK, font=font(10, True)))
        for value, label in (('versus', self.T('room.start_menu')), ('hub', self.T('room.start_hub'))):
            chosen = match.get('type', 'versus') == value
            start.add(tk.Button(start, text=label, bg=GOLD if chosen else CARD, fg='#101010' if chosen else INK, relief='flat',
                      font=font(9, True), state='normal' if host else 'disabled', cursor='hand2',
                      command=lambda v=value: self.send('start_in', value=v),
                      disabledforeground=INK if chosen else DIM))
        if match.get('type') == 'hub':
            wrap_label(tk.Label(self.teams, text=self.T('room.hub_why'), bg=PANEL, fg=DIM,
                                font=font(8))).pack(fill='x', padx=10)
        top = Flow(self.teams, bg=PANEL)
        top.pack(fill='x', padx=10, pady=(4, 2))
        top.add(tk.Label(top, text=self.T('room.mode'), bg=PANEL, fg=INK, font=font(10, True)))
        modes = [('teams', self.T('room.mode.teams')), ('ffa', self.T('room.mode.ffa'))]
        for value, label in modes:
            chosen = match.get('mode') == value
            b = tk.Button(top, text=label, bg=GOLD if chosen else CARD, fg='#101010' if chosen else INK, relief='flat',
                          font=font(9, True), state='normal' if host and match.get('type') != 'hub' else 'disabled',
                          cursor='hand2',
                          command=lambda v=value: self.send('mode', mode=v), disabledforeground=INK if chosen else DIM)
            top.add(b)
        three = tk.Label(top, text=self.T('room.mode.three'), bg=PANEL, fg='#5b6b84', font=font(9, True))
        top.add(three)
        wrap_label(tk.Label(self.teams, text=self.T('room.mode.three_why'), bg=PANEL, fg=DIM,
                            font=font(8))).pack(fill='x', padx=10)
        cols = tk.Frame(self.teams, bg=PANEL)
        cols.pack(fill='both', expand=True, padx=6, pady=4)
        teams = match.get('teams') or []
        total = sum(len(team) for team in teams)
        members = self.members()
        columns = []
        for t_, team in enumerate(teams):
            col = tk.Frame(cols, bg=PANEL)
            columns.append(col)
            head = tk.Frame(col, bg=PANEL)
            head.pack(fill='x')
            title = self.T('room.team' if match.get('mode') == 'teams' else 'room.column', n=t_ + 1)
            tk.Label(head, text=title, bg=PANEL, fg=BLUE if t_ == 0 else RED, font=font(11, True)).pack(side='left')
            if host:
                sizes = [len(x) for x in teams]
                for delta, sign in ((-1, '−'), (1, '+')):
                    new = list(sizes); new[t_] += delta                  # edit only this column
                    ok = all(1 <= n <= 5 for n in new) and sum(new) <= 10
                    tk.Button(head, text=sign, width=2, bg=CARD, fg=INK, relief='flat', font=font(10, True),
                              state='normal' if ok else 'disabled', cursor='hand2',
                              command=lambda n=new: self.send('sizes', sizes=n)).pack(side='right', padx=1)
            for i, f in enumerate(team):
                self.fighter_row(col, t_, i, f, members, host)
        layout = [None]
        def arrange_teams(width):
            side_by_side = width >= px(620)
            if layout[0] == side_by_side:
                return
            layout[0] = side_by_side
            for i, col in enumerate(columns):
                col.grid_forget()
                cols.columnconfigure(i, weight=1 if side_by_side or i == 0 else 0,
                                     uniform='teams' if side_by_side else '')
                col.grid(row=0 if side_by_side else i, column=i if side_by_side else 0,
                         sticky='nsew', padx=4, pady=2)
        cols.bind('<Configure>', lambda event: arrange_teams(event.width))
        # Give the first layout something to size before its Configure event.
        arrange_teams(self.teams.winfo_width())
        foot = Flow(self.teams, bg=PANEL)
        foot.pack(fill='x', padx=10, pady=(2, 8))
        foot.add(tk.Label(foot, text=self.T('room.total', n=total), bg=PANEL, fg=DIM, font=font(9)))
        if host:
            foot.add(self.button(foot, self.T('room.random_cpu'), lambda: self.send('random')))
        humans = sum(1 for team in teams for f in team if f.get('owner') is not None)
        wrap_label(tk.Label(self.teams, text=self.T('room.slot_hint21', n=humans), bg=PANEL, fg=DIM,
                            font=font(8))).pack(fill='x', padx=10, pady=(0, 8))

    def fighter_row(self, parent, team, index, f, members, host):
        row = tk.Frame(parent, bg=CARD, cursor='hand2')
        row.pack(fill='x', pady=2)
        owner = f.get('owner')
        mine = owner is not None and owner == self.me()
        info = tk.Frame(row, bg=CARD)
        info.pack(fill='x', padx=2, pady=2)
        img = self.small(self.catalog.chars[f['character']]['portrait']) if self.catalog and \
            f['character'] in self.catalog.chars else None
        pic = tk.Label(info, image=img, bg=GOLD if mine else CARD)
        pic.pack(side='left', padx=2, pady=2)
        text = tk.Frame(info, bg=CARD)
        text.pack(side='left', fill='x', expand=True, padx=4)
        name = self.catalog.name(f['character']) if self.catalog else str(f['character'])
        wrap_label(tk.Label(text, text=name, bg=CARD, fg=INK, font=font(9, True))).pack(fill='x')
        who = members.get(owner, {}).get('name') if owner is not None else None
        locked = bool(f.get('locked'))
        state = (self.T('room.human', name=who) if who else
                 self.T('room.cpu_locked') if locked else self.T('room.cpu'))
        sub = f'{self.T("lobby.colour")} {f["costume"] + 1} · ' + state
        items = f.get('potaras', [])
        if items:
            sub += ' · ' + self.T('potara.count', n=len(items))
        wrap_label(tk.Label(text, text=sub, bg=CARD, fg=GOLD if mine else (GREEN if who else DIM),
                            font=font(8))).pack(fill='x')
        editable = (host or mine) and self.lobby().get('phase') == 'lobby'
        if editable:
            for w in (row, pic, text, *text.winfo_children()):
                w.bind('<Button-1>', lambda e, t_=team, i=index: self.open_picker(t_, i))
        actions = Flow(row, bg=CARD)
        actions.pack(fill='x', padx=2, pady=(0, 2))
        actions.add(self.button(actions, self.T('potara.title'),
                               lambda t_=team, i=index: self.open_potara_picker(t_, i)))
        lobby_open = self.lobby().get('phase') == 'lobby'
        if host and lobby_open:
            actions.add(tk.Button(actions, text=self.T('room.unlock' if locked else 'room.lock'), bg=CARD, fg=DIM, relief='flat',
                      font=font(8), cursor='hand2',
                      command=lambda t_=team, i=index, l_=not locked: self.send('lock', team=t_, index=i,
                                                                                locked=l_)))
        if owner is None and not locked and lobby_open:
            actions.add(self.button(actions, self.T('room.claim'),
                                    lambda t_=team, i=index: self.send('claim', team=t_, index=i)))

    def draw_rules(self):
        for w in self.rules_box.winfo_children():
            w.destroy()
        match = self.match()
        host = self.is_host() and self.lobby().get('phase') == 'lobby'
        wrap_label(tk.Label(self.rules_box, text=self.T('room.rules'), bg=PANEL, fg=GOLD,
                            font=font(11, True))).pack(fill='x', padx=10, pady=(8, 4))
        grid = tk.Frame(self.rules_box, bg=PANEL)
        grid.pack(fill='x', padx=10)
        grid.columnconfigure(0, weight=1)
        r = 0
        wrap_label(tk.Label(grid, text=self.T('rule.stage'), bg=PANEL, fg=INK,
                            font=font(9, True))).grid(row=0, column=0, sticky='ew', pady=2)
        stage = match.get('stage')
        stage_name = self.T('rule.random') if stage == 'random' else (self.catalog.stage_name(stage) if self.catalog
                                                                      else str(stage))
        srow = tk.Frame(grid, bg=PANEL)
        srow.grid(row=1, column=0, sticky='ew')
        wrap_label(tk.Label(srow, text=stage_name, bg=PANEL, fg=INK, font=font(9))).pack(fill='x')
        if host:
            self.button(srow, self.T('rule.choose_stage'), self.open_stage_picker).pack(anchor='w', pady=2)
        r += 1
        tracks = [self.T('rule.random')] + [self.T('room.track', n=n + 1) for n in range(24)]
        bgm = match.get('bgm')
        current = tracks[0] if bgm == 'random' else tracks[(bgm or 0) + 1]
        self.rule_combo(grid, r, 'room.music', tracks, current, host,
                        lambda v: self.send('rules', bgm='random' if v == tracks[0] else tracks.index(v) - 1))
        r += 1
        native = match.get('native') or {}
        times = [kit_text.TIME_LABELS[x] for x in (60, 90, 180, 240, 0)]
        self.rule_combo(grid, r, 'rule.time', times, kit_text.TIME_LABELS.get(native.get('time'), '240'), host,
                        lambda v: self.native_changed('time', {b: a for a, b in kit_text.TIME_LABELS.items()}[v]))
        r += 1
        self.rule_combo(grid, r, 'rule.com', list(kit_text.COM_LABELS), kit_text.COM_LABELS[native.get('com', 2)], host,
                        lambda v: self.native_changed('com', kit_text.COM_LABELS.index(v)))
        r += 1
        refs = list(kit_text.REFEREES[self.lang])
        self.rule_combo(grid, r, 'rule.referee', refs, refs[native.get('referee', 2)], host,
                        lambda v: self.native_changed('referee', refs.index(v)))
        r += 1
        self.rule_combo(grid, r, 'rule.destructible', list(kit_text.ON_OFF),
                        'ON' if native.get('destructible', True) else 'OFF', host,
                        lambda v: self.native_changed('destructible', v == 'ON'))
        r += 1
        policies = [self.T('room.load_cancel'), self.T('room.load_drop')]
        drop = (self.lobby().get('room') or {}).get('drop_load_failures') is True
        self.rule_combo(grid, r, 'room.load_policy', policies, policies[int(drop)], host,
                        lambda v: self.send('load_policy', drop=v == policies[1]))
        wrap_label(tk.Label(self.rules_box, text=self.T('room.load_policy_note'), bg=PANEL, fg=DIM,
                            font=font(8))).pack(fill='x', padx=10, pady=(4, 0))
        row = Flow(self.rules_box, bg=PANEL)
        row.pack(fill='x', padx=10, pady=(8, 2))
        self.rules_button = self.button(row, self.T('room.rules_show'), self.open_rules)
        row.add(self.rules_button)
        self.display_button = self.button(row, self.T('room.display'), self.open_display)
        row.add(self.display_button)
        wrap_label(tk.Label(self.rules_box, text=self.T('room.rules_note'), bg=PANEL, fg=DIM,
                            font=font(8))).pack(fill='x', padx=10, pady=(4, 0))
        allowed = self.state.get('services') or []
        services = match.get('services') or {}
        for k in ('cpu_transform', 'fusion_timer', 'body_change'):
            if k not in allowed:
                continue
            on = bool(services.get(k))
            var = tk.BooleanVar(value=on)
            box = ttk.Checkbutton(self.rules_box, text=self.T('room.service_on', name=self.T('room.service.' + k)),
                                  variable=var, state='normal' if host else 'disabled',
                                  command=lambda k=k, v=var: self.send('rules', services={k: bool(v.get())}))
            box.pack(anchor='w', padx=10, pady=(4, 0))
        locked = [self.T('room.service.' + k) for k in ('cpu_transform', 'fusion_timer', 'body_change')
                  if k not in allowed]
        if locked:
            wrap_label(tk.Label(self.rules_box, text=self.T('room.services', list=', '.join(locked)), bg=PANEL, fg=DIM,
                                font=font(8))).pack(fill='x', padx=10, pady=(4, 0))
        values = kit_settings.gameplay_expand(match.get('gameplay'))
        camera = ' · '.join(f'{kit_settings.label(k, self.lang)}: {kit_settings.value_text(k, values[k], self.lang)}'
                            for k in kit_settings.CAMERA if k in values and k in kit_settings.FIELDS)
        tk.Label(self.rules_box, text=self.T('room.camera'), bg=PANEL, fg=GOLD, font=font(9, True)).pack(
            anchor='w', padx=10, pady=(6, 0))
        self.camera_label = wrap_label(tk.Label(self.rules_box, text=camera, bg=PANEL, fg=INK, font=font(8)))
        self.camera_label.pack(fill='x', padx=10)
        wrap_label(tk.Label(self.rules_box, text=self.T('lobby.controls_title') + ': ' + controls_card(values, self.lang),
                            bg=PANEL, fg=INK, font=font(8))).pack(fill='x', padx=10, pady=(6, 0))
        self.warm_label = wrap_label(tk.Label(self.rules_box, bg=PANEL, fg=DIM, font=font(8)))
        self.warm_label.pack(fill='x', padx=10, pady=(6, 8))

    def warm_text(self, warm):
        why = t(warm['why_key'], self.lang, detail=warm.get('why') or '') if warm.get('why_key') else \
            (warm.get('why') or '')
        return {'warming': self.T('lobby.warming', t=f'{int(warm.get("eta_s") or 0)} s'),
                'warm': self.T('lobby.warm_ready'), 'suspended': self.T('lobby.warm_ready'),
                'busy': self.T('lobby.warm_busy'), 'failed': self.T('lobby.warm_failed', why=why),
                'refused': self.T('lobby.warm_refused', why=why), 'cold': self.T('lobby.warm_cold')}.get(
            warm.get('state'), '')

    def rule_combo(self, grid, r, key, values, current, editable, on_change):
        wrap_label(tk.Label(grid, text=self.T(key), bg=PANEL, fg=INK,
                            font=font(9, True))).grid(row=r * 2, column=0, sticky='ew', pady=(4, 2))
        box = ttk.Combobox(grid, values=values, width=1, state='readonly' if editable else 'disabled')
        box.set(current)
        box.grid(row=r * 2 + 1, column=0, sticky='ew')
        box.bind('<<ComboboxSelected>>', lambda e: on_change(box.get()))
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
        buttons = []
        hint = ''
        if self.is_host():
            players = [k for k in self.members() if kit_lobby_console.slot_of(self.match(), k) is not None and k != 1]
            waiting = [self.name_of(k) for k in players if not self.members()[k].get('ready')]
            if slot is not None:
                buttons.append(self.watch_button)
            buttons.append(self.start_button)
            configure_changed(self.start_button, state='normal' if in_lobby and not waiting else 'disabled')
            hint = self.T('room.start_wait', names=', '.join(waiting)) if waiting else self.T('room.start_hint')
        elif slot is not None:
            buttons += [self.watch_button, self.ready_button]
            ready = bool(me.get('ready'))
            configure_changed(self.ready_button, text=self.T('room.unready_btn' if ready else 'room.ready_btn'),
                                        bg=CARD if ready else GOLD, fg=INK if ready else '#101010',
                                        state='normal' if in_lobby else 'disabled')
        else:
            hint = self.T('room.watch_hint')
        if self.is_host() and in_lobby and lob.get('return_to_hub'):
            buttons.append(self.back_hub_button)
        buttons.append(self.leave_button)
        self.lobby_buttons.set_widgets(buttons)
        if SERVER_BROWSER_VISIBLE and self.state.get('listing_warning'):
            hint += '\n' + self.T('browser.warning', reason=self.state['listing_warning'])
        configure_changed(self.start_hint, text=hint)

    def toggle_ready(self):
        me = self.members().get(self.me()) or {}
        self.send('ready', ready=not me.get('ready'))

    def leave(self):
        if self.confirm(self.T('room.close_confirm') if self.is_host() else self.T('lobby.leave_confirm')):
            self.send('leave')

    # ---- dialogs ---------------------------------------------------------------------------------------------------------
    def close_dialog(self):
        if self.dialog is not None:
            try:
                self.dialog.destroy()
            except tk.TclError:
                pass
            self.dialog = None

    def open_rules(self):
        """The match's gameplay rules (the host edits them; everybody else sees them), in the mod's own words."""
        self.close_dialog()
        host = self.is_host() and self.lobby().get('phase') == 'lobby'
        values = kit_settings.gameplay_expand(self.match().get('gameplay'))
        win = tk.Toplevel(self.root, bg=BG)
        self.dialog = win
        win.title(self.T('room.rules_show'))
        win.geometry('+%d+%d' % (self.root.winfo_rootx() + 20, self.root.winfo_rooty() + 20))
        tk.Label(win, text=self.T('room.rules') + ('' if host else '  ' + self.T('lobby.set_by_host')), bg=BG,
                 fg=INK, font=font(12, True)).pack(anchor='w', padx=12, pady=(10, 0))
        tk.Label(win, text=self.T('room.rules_note'), bg=BG, fg=DIM, font=font(8), wraplength=px(900),
                 justify='left').pack(anchor='w', padx=12)
        tk.Label(win, text=self.T('room.camera') + ' - ' + self.T('room.camera_why'), bg=BG, fg=GOLD, font=font(8),
                 wraplength=px(900), justify='left').pack(anchor='w', padx=12)
        self.settings_grid(win, kit_settings.groups(), values, host, lambda k, v: self.send('rules', gameplay={k: v}))
        tk.Label(win, text=self.T('lobby.forced'), bg=BG, fg=DIM, font=font(8), wraplength=px(900),
                 justify='left').pack(anchor='w', padx=12)
        self.button(win, self.T('close'), win.destroy, color=GOLD, fg='#101010').pack(anchor='e', padx=12, pady=8)

    def open_display(self):
        """This PC's own display settings (never sent: applied to this PC's copy of every match)."""
        self.close_dialog()
        values = kit_settings.default_local()
        values.update((self.state.get('profile') or {}).get('local') or {})
        win = tk.Toplevel(self.root, bg=BG)
        self.dialog = win
        win.title(self.T('room.display'))
        win.geometry('+%d+%d' % (self.root.winfo_rootx() + 60, self.root.winfo_rooty() + 40))
        tk.Label(win, text=self.T('room.display'), bg=BG, fg=INK, font=font(12, True)).pack(anchor='w', padx=12,
                                                                                            pady=(10, 0))
        tk.Label(win, text=self.T('room.display_note'), bg=BG, fg=DIM, font=font(8), wraplength=px(700),
                 justify='left').pack(anchor='w', padx=12)
        self.settings_grid(win, kit_settings.local_groups(), values, True,
                           lambda k, v: self.send('local', values={k: v}))
        self.button(win, self.T('close'), win.destroy, color=GOLD, fg='#101010').pack(anchor='e', padx=12, pady=8)

    def settings_grid(self, win, groups, values, editable, on_change):
        cols = tk.Frame(win, bg=BG)
        cols.pack(fill='both', padx=8, pady=6)
        columns = [tk.Frame(cols, bg=BG) for _ in range(3)]
        for i, c in enumerate(columns):
            c.grid(row=0, column=i, sticky='n', padx=4)
        heights = [0, 0, 0]
        self.setting_widgets = {}
        for group, keys in groups:
            col = heights.index(min(heights))
            heights[col] += len(keys) + 2
            box = tk.Frame(columns[col], bg=PANEL)
            box.pack(fill='x', pady=4)
            tk.Label(box, text=kit_settings.group_label(group, self.lang), bg=PANEL, fg=GOLD, font=font(9, True)).grid(
                row=0, column=0, columnspan=2, sticky='w', padx=6, pady=(4, 2))
            for r, key in enumerate(keys, 1):
                tk.Label(box, text=kit_settings.label(key, self.lang), bg=PANEL, fg=INK, font=font(8),
                         wraplength=px(230), justify='left').grid(row=r, column=0, sticky='w', padx=6, pady=1)
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
                    var = tk.StringVar(value=kit_settings.value_text(key, values.get(key), self.lang))
                    widget = ttk.Spinbox(box, from_=low, to=high, textvariable=var, width=8,
                                         state='normal' if editable else 'disabled',
                                         increment=1 if kind == 'int' else 0.25,
                                         command=lambda k=key, v=var: on_change(k, v.get()))
                    widget.bind('<Return>', lambda e, k=key, v=var: on_change(k, v.get()))
                    widget.bind('<FocusOut>', lambda e, k=key, v=var: on_change(k, v.get()))
                widget.grid(row=r, column=1, sticky='w', padx=6, pady=1)
                self.setting_widgets[key] = widget

    # ---- the fighter picker -----------------------------------------------------------------------------------------------
    def open_picker(self, team, index):
        if not self.catalog:
            return
        self.close_dialog()
        try:
            current = self.match()['teams'][team][index]
        except (IndexError, KeyError, TypeError):
            return
        win = tk.Toplevel(self.root, bg=BG)
        self.dialog = win
        title = self.T('room.team', n=team + 1) + f' · {index + 1}'
        win.title(title)
        win.geometry('+%d+%d' % (self.root.winfo_rootx() + 30, self.root.winfo_rooty() + 30))
        win.transient(self.root)
        tk.Label(win, text=title, bg=BG, fg=GOLD, font=font(12, True)).pack(anchor='w', padx=12, pady=(10, 2))
        top = tk.Frame(win, bg=BG)
        top.pack(fill='x', padx=12)
        tk.Label(top, text=self.T('pick.search'), bg=BG, fg=INK, font=font(9)).pack(side='left')
        search = tk.StringVar()
        ttk.Entry(top, textvariable=search, width=24).pack(side='left', padx=6)
        chosen = {'c': current['character'], 'k': current['costume']}
        info = tk.Label(top, text='', bg=BG, fg=INK, font=font(10, True))
        info.pack(side='left', padx=16)
        chips = tk.Frame(top, bg=BG)
        chips.pack(side='left')
        cell_px = 70 * PZ
        rows_shown = 5 if PZ > 1 else 8
        canvas = tk.Canvas(win, bg=BG, highlightthickness=0, width=7 * cell_px + 10, height=rows_shown * cell_px)
        bar = ttk.Scrollbar(win, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        forms_row = tk.Frame(win, bg=BG)

        def draw_chips():
            for w in chips.winfo_children():
                w.destroy()
            tk.Label(chips, text=self.T('pick.colour'), bg=BG, fg=DIM, font=font(9)).pack(side='left')
            for k in range(self.catalog.costumes(chosen['c'])):
                chip = tk.Label(chips, text=f' {k + 1} ', bg=GOLD if k == chosen['k'] else CARD,
                                fg='#101010' if k == chosen['k'] else INK, font=font(10, True), cursor='hand2')
                chip.pack(side='left', padx=2)
                chip.bind('<Button-1>', lambda e, k=k: (chosen.update(k=k), draw_chips()))
            info.configure(text=self.catalog.name(chosen['c']))

        def pick(c):
            chosen['c'] = c
            chosen['k'] = min(chosen['k'], self.catalog.costumes(c) - 1)
            draw_chips()
            draw_forms()
            draw()

        def draw_forms():
            for w in forms_row.winfo_children():
                w.destroy()
            cell = next((g for g in self.catalog.c['grid'] if chosen['c'] in g['forms']), None)
            if cell and len(cell['forms']) > 1:
                tk.Label(forms_row, text=self.T('pick.forms'), bg=BG, fg=DIM, font=font(9)).pack(side='left')
                for f in cell['forms']:
                    img = self.image(self.catalog.chars[f]['portrait'])
                    b = tk.Label(forms_row, image=img, bg=GOLD if f == chosen['c'] else BG, bd=2, cursor='hand2')
                    b.pack(side='left', padx=2)
                    b.bind('<Button-1>', lambda e, f=f: pick(f))

        def draw(*_):
            canvas.delete('all')
            text = search.get().strip().lower()
            if text:
                ids = [c['id'] for c in self.catalog.find(text)]
                cells = [(i // 7, i % 7, c) for i, c in enumerate(ids)]
            else:
                cells = [(g['row'], g['col'], g['base']) for g in self.catalog.c['grid']]
            for r, col, c in cells:
                x, y = 6 + col * cell_px, 6 + r * cell_px
                img = self.image(self.catalog.chars[c]['portrait'])
                if img:
                    canvas.create_image(x, y, anchor='nw', image=img, tags=(f'c{c}',))
                cell = next((g for g in self.catalog.c['grid'] if g['base'] == c), None)
                if cell and chosen['c'] in cell['forms'] or c == chosen['c']:
                    canvas.create_rectangle(x - 2, y - 2, x + 64 * PZ + 2, y + 64 * PZ + 2, outline=GOLD, width=3)
                canvas.tag_bind(f'c{c}', '<Button-1>', lambda e, c=c: pick(c))
            rows = max((r for r, _, _ in cells), default=0) + 1
            canvas.configure(scrollregion=(0, 0, 7 * cell_px + 10, rows * cell_px + 10))
        search.trace_add('write', draw)
        canvas.pack(side='left', fill='both', expand=True, padx=(12, 0), pady=6)
        bar.pack(side='left', fill='y', pady=6)
        side = tk.Frame(win, bg=BG)
        side.pack(side='left', fill='y', padx=12, pady=6)
        forms_row.pack(in_=side, anchor='nw')
        buttons = tk.Frame(side, bg=BG)
        buttons.pack(side='bottom', anchor='se')

        def ok():
            self.send('fighter', team=team, index=index, character=chosen['c'], costume=chosen['k'])
            win.destroy()
            self.dialog = None
        self.button(buttons, self.T('ok'), ok, color=GOLD, fg='#101010').pack(side='left', padx=4)
        self.button(buttons, self.T('cancel'), win.destroy).pack(side='left', padx=4)
        canvas.bind('<MouseWheel>', lambda e: (canvas.yview_scroll(-1 if e.delta > 0 else 1, 'units'), 'break')[1])
        draw_chips()
        draw_forms()
        draw()
        self.picker = dict(win=win, pick=pick, ok=ok, chosen=chosen, search=search)

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
        win = tk.Toplevel(self.root, bg=BG)
        self.dialog = win
        win.title(self.T('potara.title') + ' · ' + self.catalog.name(current['character']))
        win.transient(self.root)
        win.geometry('+%d+%d' % (self.root.winfo_rootx()+30, self.root.winfo_rooty()+30))
        win.minsize(px(600), px(390))
        win.maxsize(self.root.winfo_screenwidth()-40, self.root.winfo_screenheight()-60)
        outer = tk.Frame(win, bg=BG)
        outer.pack(fill='both', expand=True, padx=12, pady=10)
        wrap_label(tk.Label(outer, text=self.catalog.name(current['character']), bg=BG, fg=GOLD,
                            font=font(12, True))).pack(fill='x')
        wrap_label(tk.Label(outer, text=self.T('potara.note'), bg=BG, fg=DIM,
                            font=font(9))).pack(fill='x', pady=(4,8))
        search = tk.StringVar()
        ttk.Entry(outer, textvariable=search).pack(fill='x', pady=(0,6))
        body = tk.Frame(outer, bg=BG)
        body.pack(fill='both', expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(2, weight=1)
        body.rowconfigure(0, weight=1)
        available = tk.Listbox(body, bg=CARD, fg=INK, selectbackground=GOLD, selectforeground=BG,
                              font=font(9), exportselection=False, width=32, height=14)
        available.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(body, orient='vertical', command=available.yview)
        scroll.grid(row=0, column=1, sticky='ns', padx=(0,8))
        available.configure(yscrollcommand=scroll.set)
        horizontal = ttk.Scrollbar(body, orient='horizontal', command=available.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        available.configure(xscrollcommand=horizontal.set)
        equipped = tk.Listbox(body, bg=CARD, fg=INK, selectbackground=GOLD, selectforeground=BG,
                             font=font(9), exportselection=False, width=30, height=8)
        equipped.grid(row=0, column=2, sticky='nsew')
        horizontal = ttk.Scrollbar(body, orient='horizontal', command=equipped.xview)
        horizontal.grid(row=1, column=2, sticky='ew')
        equipped.configure(xscrollcommand=horizontal.set)
        draft = list(current.get('potaras', []))
        shown = []
        count = wrap_label(tk.Label(outer, bg=BG, fg=GOLD, font=font(9, True)))
        count.pack(fill='x', pady=6)
        detail = wrap_label(tk.Label(outer, bg=BG, fg=DIM, font=font(9)))
        detail.pack(fill='x')
        notice = wrap_label(tk.Label(outer, bg=BG, fg='#ef9b86', font=font(9)))
        notice.pack(fill='x')

        def name(ident):
            item = self.catalog.potaras[ident]
            return f'{item["name"]}  ({item["cost"]})'

        def refresh(*_):
            available.delete(0, 'end')
            shown[:] = [i for i,p in self.catalog.potaras.items() if search.get().casefold() in p['name'].casefold()]
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
            changes = [self.T('potara.stat.'+key)+f' {value:+d}'
                       for key,value in zip(('attack','defense','ki','super'), item['stats']) if value]
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

        buttons = tk.Frame(outer, bg=BG)
        buttons.pack(fill='x', pady=(8,0))
        if editable:
            self.button(buttons, self.T('potara.add'), add).pack(side='left')
            self.button(buttons, self.T('potara.remove'), remove).pack(side='left', padx=4)
            self.button(buttons, self.T('potara.clear'), lambda:(draft.clear(), notice.configure(text=''), refresh())).pack(side='left')
            self.button(buttons, self.T('ok'), ok, color=GOLD, fg=BG).pack(side='right')
        self.button(buttons, self.T('cancel'), win.destroy).pack(side='right', padx=4)
        search.trace_add('write', refresh)
        available.bind('<<ListboxSelect>>', preview)
        equipped.bind('<<ListboxSelect>>', preview)
        if editable:
            available.bind('<Double-Button-1>', add)
            equipped.bind('<Double-Button-1>', remove)
        refresh()
        self.potara_picker = dict(win=win, draft=draft, ok=ok, available=available, shown=shown,
                                  equipped=equipped, add=add, remove=remove, search=search)

    def open_stage_picker(self):
        if not self.catalog:
            return
        self.close_dialog()
        win = tk.Toplevel(self.root, bg=BG)
        self.dialog = win
        win.title(self.T('stage.title'))
        win.transient(self.root)
        win.geometry('+%d+%d' % (self.root.winfo_rootx() + 60, self.root.winfo_rooty() + 40))
        tk.Label(win, text=self.T('stage.title'), bg=BG, fg=GOLD, font=font(12, True)).pack(anchor='w', padx=12,
                                                                                         pady=(10, 4))
        grid = tk.Frame(win, bg=BG)
        grid.pack(padx=12, pady=6)
        order = self.catalog.stage_order() + ['random']

        def choose(sid):
            self.send('rules', stage=sid)
            win.destroy()
            self.dialog = None
        import tkinter.font as tkfont
        wrap = tkfont.Font(root=win, font=font(7)).measure('0' * 15)
        for i, sid in enumerate(order):
            cell = tk.Frame(grid, bg=CARD, cursor='hand2')
            cell.grid(row=i // 7, column=i % 7, padx=3, pady=3, sticky='n')
            rel = self.catalog.c.get('random_thumb') if sid == 'random' else self.catalog.stages[sid]['thumb']
            img = self.image(rel)
            pic = tk.Label(cell, image=img, bg=CARD)
            pic.pack()
            name = self.T('rule.random') if sid == 'random' else self.catalog.stage_name(sid)
            lab = tk.Label(cell, text=name, bg=CARD, fg=INK, font=font(7), wraplength=wrap, width=16)
            lab.pack()
            for w in (cell, pic, lab):
                w.bind('<Button-1>', lambda e, sid=sid: choose(sid))
        self.button(win, self.T('cancel'), win.destroy).pack(anchor='e', padx=12, pady=8)

    # ---- S6 / S7 preparing, sending, loading ---------------------------------------------------------------------------
    def build_prep(self):
        self.clear()
        self.header(self.body, self.T('prep.title'))
        box = tk.Frame(self.body, bg=PANEL, highlightbackground=GOLD, highlightthickness=2)
        box.pack(fill='x', padx=16, pady=20)
        self.prep_title = wrap_label(tk.Label(box, text='', bg=PANEL, fg=INK, font=font(12, True)))
        self.prep_title.pack(fill='x', padx=14, pady=(12, 4))
        self.prep_step = wrap_label(tk.Label(box, text='', bg=PANEL, fg=GOLD, font=font(11, True)))
        self.prep_step.pack(fill='x', padx=14)
        self.prep_bar = ttk.Progressbar(box, length=px(600), maximum=100)
        self.prep_bar.pack(fill='x', padx=14, pady=10)
        self.prep_eta = wrap_label(tk.Label(box, text='', bg=PANEL, fg=DIM, font=font(10)))
        self.prep_eta.pack(fill='x', padx=14, pady=(0, 10))
        self.prep_cancel = None
        if self.is_host():
            self.prep_cancel = self.button(box, self.T('prep.cancel'), self.cancel_prep, color=RED)
            self.prep_cancel.pack(anchor='w', padx=14, pady=(0, 12))
        self.notice_label = wrap_label(tk.Label(self.body, text='', bg=BG, fg=GOLD, font=font(10, True)))
        self.notice_label.pack(fill='x', padx=18)
        self.build_bottom_chat(self.body)

    def build_bottom_chat(self, parent):
        foot = tk.Frame(parent, bg=BG)
        foot.pack(side='bottom', fill='x', padx=16, pady=8)
        self.chat_text = tk.Text(foot, height=4, width=30, bg=PANEL, fg=INK, relief='flat', font=font(9),
                                 wrap='word', state='disabled')
        self.chat_text.pack(fill='x')
        row = tk.Frame(foot, bg=BG)
        row.pack(fill='x', pady=(4, 0))
        self.chat_var = tk.StringVar()
        entry = ttk.Entry(row, textvariable=self.chat_var, width=20)
        entry.pack(side='left', padx=(0, 6), fill='x', expand=True)
        entry.bind('<Return>', lambda e: self.send_chat())
        self.button(row, self.T('lobby.send'), self.send_chat).pack(side='left')
        self.draw_chat()

    def cancel_prep(self):
        if self.confirm(self.T('prep.cancel_confirm')):
            self.send('cancel_prep')

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
        configure_changed(self.head_line, text=self.T('send.title') if phase in ('sending', 'loading') else '')
        self.show_notice()

    # ---- S8 fight ------------------------------------------------------------------------------------------------------
    def build_fight(self):
        self.clear()
        self.header(self.body, self.T('fight.title'))
        box = tk.Frame(self.body, bg=PANEL, highlightbackground=GREEN, highlightthickness=2)
        box.pack(fill='x', padx=16, pady=16)
        title = (self.state.get('match') or {}).get('title') or ''
        wrap_label(tk.Label(box, text=title, bg=PANEL, fg=INK,
                            font=font(10, True))).pack(fill='x', padx=14, pady=(10, 0))
        self.fight_role = wrap_label(tk.Label(box, text='', bg=PANEL, fg=GOLD, font=font(11, True)))
        self.fight_role.pack(fill='x', padx=14, pady=(6, 0))
        self.fight_status = wrap_label(tk.Label(box, text='', bg=PANEL, fg=GREEN, font=font(14, True)))
        self.fight_status.pack(fill='x', padx=14, pady=(6, 4))
        self.fight_banner = wrap_label(tk.Label(box, text='', bg=PANEL, fg=GOLD, font=font(12, True)))
        self.fight_banner.pack(fill='x', padx=14)
        wrap_label(tk.Label(box, text=self.T('fight.window_hint'), bg=PANEL, fg=DIM,
                            font=font(9))).pack(fill='x', padx=14, pady=(4, 12))
        row = Flow(self.body, bg=BG)
        row.pack(fill='x', padx=16)
        self.fight_buttons = row
        if self.is_host():
            self.end_button = self.button(row, self.T('fight.end_host'), self.end_fight, color=RED, big=True)
        else:
            self.end_button = self.button(row, self.T('fight.leave_match'), self.leave_match, color=RED, big=True)
        row.add(self.end_button)
        self.watch_buttons = []
        for side in (0, 1):
            b = self.button(row, self.T('fight.watch_team', team=side + 1), lambda s=side: self.send('watch', side=s))
            self.watch_buttons.append(b)
        self.notice_label = wrap_label(tk.Label(self.body, text='', bg=BG, fg=GOLD, font=font(10, True)))
        self.notice_label.pack(fill='x', padx=18, pady=6)
        self.hub_box = tk.Frame(self.body, bg=PANEL, highlightbackground=BLUE, highlightthickness=2)
        self.hub_sig = None
        self.build_bottom_chat(self.body)

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
        self.fight_buttons.set_widgets([self.end_button] + (self.watch_buttons if slot is None else []))
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
        for w in box.winfo_children():
            w.destroy()
        if not hub:
            box.pack_forget()
            return
        box.pack(fill='x', padx=16, pady=(0, 6), before=self.chat_text.master)
        tk.Label(box, text=self.T('fight.hub_title') + '   (' + self.T('fight.hub_cols') + ')', bg=PANEL, fg=GOLD,
                 font=font(11, True)).pack(anchor='w', padx=10, pady=(6, 2))
        duel = hub.get('duel')
        rows = hub.get('rows') or []
        names = {r['i']: r['name'] for r in rows}
        if duel:
            tk.Label(box, text=self.T('fight.hub_dueling', a=names.get(duel[0], '?'), b=names.get(duel[1], '?')),
                     bg=PANEL, fg=RED, font=font(10, True)).pack(anchor='w', padx=10)
        grid = tk.Frame(box, bg=PANEL)
        grid.pack(fill='x', padx=10)
        grid.columnconfigure(0, weight=1)
        self.hub_score_labels = {}
        for r, row in enumerate(sorted(rows, key=lambda x: (-x['kills'], x['deaths'], x['i']))):
            mine = row.get('member') == self.me()
            name = wrap_label(tk.Label(grid, bg=PANEL, fg=GOLD if mine else INK, font=font(9, mine)))
            name.grid(row=r, column=0, sticky='ew')
            labels = [name]
            for col, key in enumerate(('kills', 'deaths', 'wins'), 1):
                label = tk.Label(grid, bg=PANEL, fg=INK, font=font(9), width=5)
                label.grid(row=r, column=col)
                labels.append(label)
            self.hub_score_labels[row['i']] = labels
        self.hub_feed_labels = []
        for _ in range(3):
            label = wrap_label(tk.Label(box, bg=PANEL, fg=DIM, font=font(8)))
            label.pack(fill='x', padx=10)
            self.hub_feed_labels.append(label)
        self.update_hub_scores(hub)
        me_row = next((r for r in rows if r.get('member') == self.me()), None)
        if me_row is None:
            join = tk.Frame(box, bg=PANEL)                     # kit 2.1: a watcher may take a free fighter
            join.pack(fill='x', padx=10, pady=6)
            self.button(join, self.T('fight.hub_join'), lambda: self.send('hub_join')).pack(side='left')
            tk.Label(join, text='  ' + self.T('fight.hub_join_why'), bg=PANEL, fg=DIM, font=font(8),
                     wraplength=px(420), justify='left').pack(side='left')
            return
        actions = tk.Frame(box, bg=PANEL)
        actions.pack(fill='x', padx=10, pady=6)
        is_open = bool(hub.get('open', 0) >> me_row['i'] & 1)
        self.hub_open_button = self.button(actions, self.T('fight.hub_open_on' if is_open else 'fight.hub_open_off'),
                                           lambda: self.send('hub_open', on=not is_open),
                                           color=RED if is_open else CARD)
        self.hub_open_button.pack(side='left')
        others = [r for r in rows if r.get('member') not in (None, self.me())]
        if others and not duel:
            tk.Label(actions, text='  ' + self.T('fight.hub_challenge'), bg=PANEL, fg=INK, font=font(9, True)).pack(
                side='left')
            pick = ttk.Combobox(actions, values=[r['name'] for r in others], state='readonly', width=16)
            pick.set(others[0]['name'])
            pick.pack(side='left', padx=4)

            def target():
                return next((r['member'] for r in others if r['name'] == pick.get()), None)
            self.button(actions, self.T('fight.hub_duel'),
                        lambda: self.send('hub_challenge', target=target(), kind='duel')).pack(side='left', padx=2)
            self.button(actions, self.T('fight.hub_match'),
                        lambda: self.send('hub_challenge', target=target(), kind='match')).pack(side='left', padx=2)
        for ch in hub.get('challenges') or []:
            if ch.get('target') != self.me():
                continue
            row = tk.Frame(box, bg=PANEL)
            row.pack(fill='x', padx=10, pady=(0, 6))
            by = self.name_of(ch['by'])
            kind = self.T('fight.hub_duel' if ch['kind'] == 'duel' else 'fight.hub_match')
            tk.Label(row, text=self.T('fight.hub_incoming', name=by, kind=kind), bg=PANEL, fg=GOLD,
                     font=font(10, True)).pack(side='left')
            self.button(row, self.T('fight.hub_accept'), lambda b=ch['by']: self.send('hub_answer', challenger=b,
                                                                                     accept=True),
                        color=GREEN, fg='#101010').pack(side='left', padx=4)
            self.button(row, self.T('fight.hub_decline'), lambda b=ch['by']: self.send('hub_answer', challenger=b,
                                                                                      accept=False)).pack(side='left')

    def update_hub_scores(self, hub):
        for position, row in enumerate(sorted(hub.get('rows') or [], key=lambda x: (-x['kills'], x['deaths'], x['i']))):
            labels = self.hub_score_labels[row['i']]
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
        if self.confirm(self.T('fight.end_confirm2')):
            self.send('end_fight')

    def leave_match(self):
        if self.confirm(self.T('fight.leave_match') + '?'):
            self.send('leave_match')

    # ---- S9 results ----------------------------------------------------------------------------------------------------
    def build_results(self):
        self.clear()
        self.header(self.body, self.T('results.title'))
        box = tk.Frame(self.body, bg=PANEL, highlightbackground=GOLD, highlightthickness=2)
        box.pack(fill='x', padx=16, pady=16)
        self.res_title = wrap_label(tk.Label(box, text='', bg=PANEL, fg=INK, font=font(10)))
        self.res_title.pack(fill='x', padx=14, pady=(10, 0))
        self.res_winner = wrap_label(tk.Label(box, text='', bg=PANEL, fg=GOLD, font=font(20, True)))
        self.res_winner.pack(fill='x', padx=14, pady=(6, 4))
        self.res_sync = wrap_label(tk.Label(box, text='', bg=PANEL, fg=DIM, font=font(9)))
        self.res_sync.pack(fill='x', padx=14)
        self.res_vote = wrap_label(tk.Label(box, text='', bg=PANEL, fg=INK, font=font(12, True)))
        self.res_vote.pack(fill='x', padx=14, pady=(12, 2))
        self.res_agreed = wrap_label(tk.Label(box, text='', bg=PANEL, fg=GREEN, font=font(10)))
        self.res_agreed.pack(fill='x', padx=14, pady=(0, 12))
        row = Flow(self.body, bg=BG)
        row.pack(fill='x', padx=16)
        self.res_retry = self.button(row, self.T('results.retry'), lambda: self.send('vote', choice='retry'),
                                     color=GOLD, fg='#101010', big=True, width=14)
        self.res_back = self.button(row, self.T('results.to_lobby'), lambda: self.send('vote', choice='lobby'),
                                    big=True)
        if self.my_slot() is not None or (self.is_host() and not self.match_players()):
            row.set_widgets([self.res_retry, self.res_back])
        self.build_bottom_chat(self.body)

    def match_players(self):
        return list(((self.state.get('match') or {}).get('seats') or {}).keys())

    def update_results(self):
        if not getattr(self, 'res_vote', None) or not self.res_vote.winfo_exists():
            return
        res = self.state.get('results') or {}
        configure_changed(self.res_title, text=res.get('title') or (self.state.get('match') or {}).get('title') or '')
        winner, how = res.get('winner') or 0, res.get('how')
        if how == 'nocontest' or not winner:
            text = self.T('results.nocontest') if not res.get('nocontest') else \
                self.T('results.nocontest_why', why=res['nocontest'])
        else:
            team = 1 if winner & 1 else 2
            text = self.T('results.winner_team', team=team) + ' ' + self.T('results.ko' if how == 'ko' else
                                                                          'results.time')
        configure_changed(self.res_winner, text=text)
        seconds = int(res.get('seconds') or 0)
        if res.get('compared') is not None:
            configure_changed(self.res_sync, text=self.T('results.sync', compared=res.get('compared'),
                                                differing=res.get('differing'), resyncs=res.get('resyncs') or 0) +
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
        state = 'disabled' if agreed or vote.get('decision') else 'normal'
        for b in (self.res_retry, self.res_back):
            if b.winfo_exists():
                configure_changed(b, state=state)

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
                self.overlay.destroy()
                self.overlay, self.overlay_hwnd = None, None
            return
        info = kit_win.window_info(pc['pid'], pc.get('desktop'))
        text = self.overlay_text(ov)
        if self.overlay is None:
            self.overlay = tk.Toplevel(self.root, bg='#101010')
            self.overlay.overrideredirect(True)
            self.overlay.attributes('-topmost', True)
            try:
                self.overlay.attributes('-alpha', 0.92)
            except tk.TclError:
                pass
            self.overlay_label = tk.Label(self.overlay, text=text, bg='#101010', fg=GOLD, font=font(13, True),
                                          padx=18, pady=8)
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
        err = self.state.get('error')
        if not err or err == self.error_shown:
            return
        self.error_shown = err
        win = tk.Toplevel(self.root, bg=BG)
        win.title(self.T('err.title'))
        win.transient(self.root)
        win.geometry('+%d+%d' % (self.root.winfo_rootx() + 80, self.root.winfo_rooty() + 80))
        text = tk.Text(win, width=80, height=16, bg=PANEL, fg=INK, font=('Consolas', 9), relief='flat', wrap='none')
        text.insert('1.0', err.get(self.lang) or err.get('en') or '')
        text.configure(state='disabled')
        text.pack(padx=12, pady=12)
        row = tk.Frame(win, bg=BG)
        row.pack(fill='x', padx=12, pady=(0, 12))

        def remedy(name):
            win.destroy()
            self.send('dismiss')
            if name == 'retry':
                if self.state.get('role') == 'host':
                    self.send('host')
                else:
                    self.send('join', address=(self.state.get('settings') or {}).get('host_address', ''))
            elif name == 'advanced':
                self.advanced_open = True
                if self.screen == 'start':
                    self.build_start()
            elif name in ('choose_iso', 'choose_bios'):
                self.choose_file(name.split('_')[1])
            elif name == 'compare_files':
                self.send('setup', disc_check='quick')
            elif name == 'logs':
                folder = self.state.get('run_dir') or str(kit_paths.RUNS)
                if os.name == 'nt':
                    os.startfile(folder)  # noqa: S606 - the player's own logs folder
        for name in err.get('remedies') or []:
            if name == 'relay':
                continue
            self.button(row, self.T('remedy.' + name), lambda n=name: remedy(n)).pack(side='left', padx=4)

        def close():
            win.destroy()
            self.send('dismiss')
        self.button(row, self.T('close'), close, color=GOLD, fg='#101010').pack(side='right')
        self.error_window = win

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
            self.advanced_open = bool(step.get('open', True))
            if self.screen == 'start':
                self.build_start()
        elif what == 'close_error' and getattr(self, 'error_window', None) is not None:
            self.error_window.destroy()
            self.send('dismiss')
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
