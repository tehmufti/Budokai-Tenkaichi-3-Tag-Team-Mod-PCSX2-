"""The online menus' look, after Budokai Tenkaichi 3's own menus: night-blue panels in metallic gold frames, orange-yellow
italic headings on a gradient banner, glowing gold and cyan selections. Tk only (standard library), Windows and Linux.

Nothing here comes from the game: the colours, gradients and frames are drawn, and the fonts are the system's own
(Arial Black where Windows has it, else the body font in bold italic). Fighter portraits and stage pictures are read
from the player's own disc at run time (kit_catalog) and never ship with the kit.
"""
import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

# ---- palette ------------------------------------------------------------------------------------------------------------
NIGHT = '#050b1d'        # the window
DEEP = '#0a1638'         # scroll troughs, gaps
PANEL = '#0f2257'        # panel fill
CARD = '#16306f'         # rows and cards inside a panel
CARD_HI = '#204394'      # a hovered row
INSET = '#081438'        # entries, lists, chat
EDGE = '#c8861a'         # metallic gold frame (Tk derives the bevel's light and dark sides from it)
EDGE_DARK = '#3a2405'
EDGE_BLUE = '#3a64c4'      # the frame of a secondary panel (the hub)
GOLD = '#ffc531'         # headings, selections
ORANGE = '#ff9a1f'
AMBER = '#f2a024'        # primary buttons
AMBER_HI = '#ffd257'
INK = '#f4f7ff'
DIM = '#a9bde6'
FAINT = '#7088bd'
DARK_INK = '#1b0f00'     # text on gold
GLOW = '#8ff3ff'         # focus and hover glow (the game's cyan cursor)
TEAM = ('#3d8bff', '#ff4b4b')
TEAM_DIM = ('#2a5cb0', '#a8323a')
GREEN = '#5fe38a'
RED = '#ff6464'
BLUE = '#2f62c8'
BLUE_HI = '#4c84f0'
DANGER = '#b5303a'
DANGER_HI = '#e04652'
GO = '#38b862'
GO_HI = '#5ad883'
OFF_BG = '#26365e'       # a disabled button
OFF_FG = '#8a9bc4'

BODY_FAMILY = 'Segoe UI' if os.name == 'nt' else 'DejaVu Sans'
HEAD_FAMILY = BODY_FAMILY
HEAD_STYLE = 'bold italic'
S = 1.0                  # this screen's UI scale (kit_lobby_ui.App.fit_window)


def px(n):
    """A pixel size of the 96-DPI design at this screen's scale."""
    return int(round(n * S))


def font(size=10, bold=False):
    return (BODY_FAMILY, size, 'bold' if bold else 'normal')


def heading(size=12):
    return (HEAD_FAMILY, size, HEAD_STYLE)


def init(root):
    """Pick the heading font this system has and style the ttk widgets; call once after the Tk root exists."""
    global HEAD_FAMILY, HEAD_STYLE
    try:
        families = set(tkfont.families(root))
    except tk.TclError:
        families = set()
    for family, style in (('Arial Black', 'italic'), ('Segoe UI Black', 'italic'), ('DejaVu Sans', 'bold italic'),
                          ('Liberation Sans', 'bold italic')):
        if family in families:
            HEAD_FAMILY, HEAD_STYLE = family, style
            break
    else:
        HEAD_FAMILY, HEAD_STYLE = BODY_FAMILY, 'bold italic'
    # Entries, combo boxes and check boxes use Tk's named fonts: give them the body font in points (they follow the
    # display scale) instead of a system font measured in pixels (tiny on Linux, oversized on some desktops).
    for name, size in (('TkDefaultFont', 9), ('TkTextFont', 10)):
        try:
            tkfont.nametofont(name, root=root).configure(family=BODY_FAMILY, size=size)
        except (tk.TclError, TypeError):
            pass
    style_ttk(root)


def style_ttk(root):
    s = ttk.Style(root)
    try:
        s.theme_use('clam')
    except tk.TclError:
        pass
    s.configure('.', background=PANEL, foreground=INK, fieldbackground=INSET, bordercolor=EDGE_DARK,
                lightcolor=CARD, darkcolor=INSET, troughcolor=DEEP, selectbackground=GOLD,
                selectforeground=DARK_INK, insertcolor=INK, focuscolor=GLOW, font=font(10))
    for name in ('TCombobox', 'TEntry', 'TSpinbox'):
        s.configure(name, fieldbackground=INSET, foreground=INK, background=CARD, arrowcolor=GOLD,
                    bordercolor=EDGE, lightcolor=INSET, darkcolor=INSET, insertcolor=INK, padding=px(3),
                    selectbackground=GOLD, selectforeground=DARK_INK, arrowsize=px(13))
        s.map(name, fieldbackground=[('readonly', INSET), ('disabled', DEEP)],
              foreground=[('disabled', OFF_FG), ('readonly', INK)],
              background=[('active', CARD_HI), ('disabled', DEEP), ('readonly', CARD)],
              bordercolor=[('focus', GLOW), ('hover', AMBER_HI)],
              lightcolor=[('focus', GLOW)], arrowcolor=[('disabled', OFF_FG)],
              selectbackground=[('readonly', INSET)], selectforeground=[('readonly', INK)])
    for orient in ('Vertical', 'Horizontal'):
        s.configure(f'{orient}.TScrollbar', background=CARD, troughcolor=DEEP, bordercolor=DEEP, arrowcolor=GOLD,
                    lightcolor=CARD_HI, darkcolor=INSET, gripcount=0, arrowsize=px(14))
        s.map(f'{orient}.TScrollbar', background=[('active', CARD_HI), ('pressed', BLUE)])
    s.configure('Horizontal.TProgressbar', background=ORANGE, troughcolor=INSET, bordercolor=EDGE,
                lightcolor=AMBER_HI, darkcolor='#c2410c', thickness=px(18))
    s.configure('TCheckbutton', background=PANEL, foreground=INK, indicatorbackground=INSET,
                indicatorforeground=GOLD, focuscolor=GLOW, font=font(10))
    s.map('TCheckbutton', background=[('active', PANEL)], foreground=[('disabled', OFF_FG)],
          indicatorbackground=[('disabled', DEEP), ('pressed', CARD)])
    s.configure('Treeview', background=INSET, fieldbackground=INSET, foreground=INK, rowheight=px(26), font=font(9))
    s.configure('Treeview.Heading', background=CARD, foreground=GOLD, font=font(9, True))
    s.map('Treeview', background=[('selected', GOLD)], foreground=[('selected', DARK_INK)])
    root.option_add('*TCombobox*Listbox.background', INSET)
    root.option_add('*TCombobox*Listbox.foreground', INK)
    root.option_add('*TCombobox*Listbox.selectBackground', GOLD)
    root.option_add('*TCombobox*Listbox.selectForeground', DARK_INK)
    root.option_add('*TCombobox*Listbox.font', font(10))
    _progress_image(root, s)


def _progress_image(root, s):
    """The progress bar as a ki gauge: a vertical orange-yellow gradient (a 9-slice image element)."""
    try:
        height = max(8, px(18))
        img = tk.PhotoImage(master=root, width=6, height=height)
        for y in range(height):
            img.put(blend('#fff09a', '#ff8a1e', '#c2410c', y / max(1, height - 1)), to=(0, y, 6, y + 1))
        root._ttm_progress = img                                    # keep the image alive with the window
        s.element_create('ttm.pbar', 'image', img, border=(2, 2), sticky='nswe')
        s.layout('Horizontal.TProgressbar', [('Horizontal.Progressbar.trough', {'sticky': 'nswe', 'children': [
            ('ttm.pbar', {'side': 'left', 'sticky': 'ns'})]})])
    except tk.TclError:
        pass                                                         # the plain coloured bar stays


def blend(top, mid, bottom, t):
    """A colour on a three-stop vertical gradient (t from 0 to 1)."""
    def rgb(c):
        return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
    a, b = (rgb(top), rgb(mid)) if t < 0.5 else (rgb(mid), rgb(bottom))
    f = t * 2 if t < 0.5 else (t - 0.5) * 2
    return '#%02x%02x%02x' % tuple(int(x + (y - x) * f) for x, y in zip(a, b))


# ---- buttons ------------------------------------------------------------------------------------------------------------
KINDS = {'primary': (AMBER, AMBER_HI, DARK_INK), 'secondary': (BLUE, BLUE_HI, INK), 'danger': (DANGER, DANGER_HI, INK),
         'go': (GO, GO_HI, DARK_INK), 'plain': (CARD, CARD_HI, INK), 'ghost': (PANEL, CARD, DIM),
         'chip': (CARD, CARD_HI, INK), 'chip_on': (GOLD, AMBER_HI, DARK_INK)}


def style_button(b, kind='plain', big=False, parent_bg=None):
    """A raised, gold-lit game button; hover lights it, keyboard focus draws the cyan ring."""
    bg, hi, fg = KINDS[kind]
    head = kind in ('primary', 'go') or big
    b.configure(bg=bg, fg=fg, activebackground=hi, activeforeground=fg, relief='raised', bd=max(1, px(2)),
                highlightthickness=max(1, px(2)), highlightcolor=GLOW,
                highlightbackground=parent_bg or b.master.cget('bg'), disabledforeground=OFF_FG, cursor='hand2',
                font=heading(12 if big else 10) if head else font(11 if big else 9, True),
                padx=px(16 if big else 10), pady=px(6 if big else 3))
    b._ttm = dict(kind=kind, bg=bg, hi=hi)
    if not getattr(b, '_ttm_hover', False):
        b._ttm_hover = True
        b.bind('<Enter>', _enter, add='+')
        b.bind('<Leave>', _leave, add='+')
    _paint(b)
    return b


def set_kind(b, kind):
    """Change a button's look in place (only when it differs: session packets must not redraw it)."""
    if getattr(b, '_ttm', {}).get('kind') == kind:
        return
    bg, hi, fg = KINDS[kind]
    b._ttm = dict(kind=kind, bg=bg, hi=hi)
    b.configure(fg=fg, activebackground=hi, activeforeground=fg)
    _paint(b)


def enable(b, on):
    on = bool(on)
    if (str(b.cget('state')) != 'disabled') != on:
        b.configure(state='normal' if on else 'disabled')
        _paint(b)


def _paint(b, hover=False):
    look = getattr(b, '_ttm', None)
    if not look:
        return
    if str(b.cget('state')) == 'disabled':
        color = look.get('off', OFF_BG)
    else:
        color = look['hi'] if hover else look['bg']
    if b.cget('bg') != color:
        b.configure(bg=color)


def _enter(event):
    try:
        _paint(event.widget, hover=True)
    except tk.TclError:
        pass


def _leave(event):
    try:
        _paint(event.widget)
    except tk.TclError:
        pass


# ---- frames -------------------------------------------------------------------------------------------------------------
class Panel(tk.Frame):
    """A night-blue panel in a metallic gold frame; put the content in .inner."""

    def __init__(self, parent, fill=PANEL, edge=EDGE, width=3, **options):
        super().__init__(parent, bg=edge, relief='ridge', bd=max(2, px(width)), **options)
        self.inner = tk.Frame(self, bg=fill, highlightthickness=1, highlightbackground=EDGE_DARK)
        self.inner.pack(fill='both', expand=True)


def portrait_frame(parent, image, glow=None, bg=None):
    """A portrait in a thin gold bevel; glow (a colour) lights the frame for the player's own fighter."""
    frame = tk.Frame(parent, bg=glow or EDGE, relief='ridge' if not glow else 'flat', bd=max(1, px(2)))
    label = tk.Label(frame, image=image, bg=bg or INSET, bd=0, highlightthickness=0)
    if image is None:
        label.configure(width=4, height=2, text='?', fg=FAINT, font=heading(14))
    label.pack()
    frame.picture = label
    return frame


class Banner(tk.Canvas):
    """The screen title: an orange-gold gradient band with an italic outlined title (BT3's menu headers) and a thin
    gold rule to the right edge. Redrawn only when the title changes; a resize just stretches the rule."""

    def __init__(self, parent, bg=NIGHT, size=20):
        self.size = size
        self.h = px(size * 2 + 10)
        super().__init__(parent, bg=bg, highlightthickness=0, height=self.h, width=px(200))
        self.text = None
        self.bind('<Configure>', self._stretch, add='+')

    def set(self, text):
        text = str(text or '')
        if text == self.text:
            return
        self.text = text
        self.delete('all')
        f = heading(self.size)
        try:
            width = tkfont.Font(root=self, font=f).measure(text)
        except tk.TclError:
            width = len(text) * px(self.size)
        h = self.h - px(10)
        top = px(5)
        slant = h * 0.55
        end = px(30) + width + px(44)
        for y in range(h):
            color = blend('#ffe066', '#ff9a1f', '#b8400c', y / max(1, h - 1))
            x1 = end + (h - y) * 0.55
            self.create_line(0, top + y, x1, top + y, fill=color)
        self.create_line(0, top, end + slant, top, fill='#fff3b8')                      # the bevel's bright lip
        self.create_line(0, top + h, end, top + h, fill='#5a1e00', width=2)
        self.create_line(end + slant + px(6), top + h // 2, end + slant + px(6), top + h // 2, fill=EDGE, width=2,
                         tags=('rule',))
        x, y = px(28), top + h // 2
        for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1), (2, 3)):                     # dark outline + drop shadow
            self.create_text(x + dx, y + dy, text=text, anchor='w', font=f, fill='#3a1400')
        self.create_text(x, y, text=text, anchor='w', font=f, fill='#fffbe6')
        self.end = end + slant
        self._stretch()

    def _stretch(self, _event=None):
        try:
            w = self.winfo_width()
            y = self.h // 2
            start = getattr(self, 'end', 0) + px(10)
            self.coords('rule', start, y, max(start, w - px(8)), y)
        except tk.TclError:
            pass


def glow_box(canvas, x0, y0, x1, y1, tags=(), colors=('#8a3a00', ORANGE, GOLD, '#fff3b0')):
    """The game's selection: a soft orange halo fading into a bright gold ring around a cell."""
    n = len(colors)
    for i, color in enumerate(colors):
        d = n - i
        canvas.create_rectangle(x0 - d, y0 - d, x1 + d, y1 + d, outline=color, width=2 if i < n - 1 else 1, tags=tags)
