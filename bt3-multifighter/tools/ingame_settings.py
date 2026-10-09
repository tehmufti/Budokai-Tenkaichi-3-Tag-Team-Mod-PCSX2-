"""Controller-operated settings inside the guest display, from Modded Modes.

Host-drawn screens: a category index (every settings page, the per-character
CPU transformation exceptions and Restore defaults), one page per category,
the page help, the exceptions list, confirmations and an error screen. Edits
are staged locally and saved atomically only on Square. The guest input code
is unchanged: it reports new presses in CONTROL+12 (input_binding bit order)
and the host reads the held pad word for repeats. The guest input lease
expires if the host goes away. When each setting applies is on its page help.
"""
from native_map import A
import copy
import struct
import time
from functools import lru_cache
import localization
from prototype import Assembler
import feature_preferences
import fonts
import input_binding
import mod_settings

CODE, CONTROL, END = 0x06910000, 0x06910F00, 0x06911000
MAGIC = 0x53455431
PAD, MANAGER, MENU = A(0x333800), A(0x2FF10C), 0x076FF000
MAIN_CALLER = A(0x336890)


def input_code():
    # Called from the saved-register native menu wrapper. a0 is the native
    # caller; preserve RA ourselves since no other functions are called here.
    a=Assembler(CODE);a.li(8,CONTROL);a.lw(9,8);a.li(10,MAGIC)
    a.branch(5,9,10,'no');a.lw(9,8,4);a.branch(4,9,0,'no')
    a.lw(9,8,8);a.branch(4,9,0,'expire');a.addiu(9,9,-1);a.sw(9,8,8)
    a.li(10,MAIN_CALLER);a.branch(5,4,10,'no')
    a.li(10,MANAGER);a.lw(10,10);a.li(11,0x100000);a.r(0x2B,11,10,11);a.branch(5,11,0,'expire')
    a.li(11,0x1FFF000);a.r(0x2B,11,10,11);a.branch(4,11,0,'expire')
    a.lw(10,10,0x18);a.addiu(11,0,4);a.branch(5,10,11,'expire')
    a.li(10,MENU);a.lw(11,10,4);a.addiu(12,0,2);a.branch(5,11,12,'expire')
    a.li(10,PAD);a.lw(11,10,0x150);a.lw(12,8,16);a.sw(11,8,16)
    a.i(14,12,12,0xFFFF);a.r(0x24,11,11,12);a.lw(12,8,12);a.r(0x25,11,11,12);a.sw(11,8,12)
    a.sw(0,10,0x18C);a.sw(0,10,0x190);a.addiu(2,0,1);a.jr()
    a.label('expire');a.sw(0,8,4);a.sw(0,8,12)
    a.label('no');a.move(2,0);a.jr()
    return a.finish()


def code_pieces():return [(CODE,input_code())]


# Presses arrive as the guest's 16-bit edge mask (input_binding.MASKS order).
_M = input_binding.MASKS
SELECT, UP, RIGHT, DOWN, LEFT = _M['select'], _M['up'], _M['right'], _M['down'], _M['left']
L2, R2, L1, R1 = _M['l2'], _M['r2'], _M['l1'], _M['r1']
TRIANGLE, CIRCLE, CROSS, SQUARE = _M['triangle'], _M['circle'], _M['cross'], _M['square']
BACK = 0x10000            # the configured menu switch button, when a screen has no other use for it
# Buttons each screen gives a meaning. The menu switch button acts as Back
# (never destructively) wherever it is not one of these.
USED = {
    'index': UP|DOWN|CROSS|CIRCLE|SQUARE|TRIANGLE,
    'page': UP|DOWN|LEFT|RIGHT|CROSS|L1|R1|L2|R2|CIRCLE|SQUARE|TRIANGLE,
    'help': CIRCLE|CROSS|TRIANGLE,
    'exceptions': UP|DOWN|LEFT|RIGHT|CROSS|L1|R1|L2|R2|SELECT|SQUARE|TRIANGLE,
    'confirm': CROSS|SQUARE|TRIANGLE,
    'error': CROSS|TRIANGLE,
}
ROWS = 7                  # settings per page
INDEX_VISIBLE = 16        # category index rows between y=70 and the footer; more scroll with arrows
CHARACTER_ROWS = 13       # characters per exceptions page
JUMP_PAGES = 5            # L2/R2 on the exceptions list
REPEAT_DELAY = .4         # seconds a direction is held before it repeats, one step per host poll
BUDGET = 7680             # tested sprite budget: 75% of gif_packet's 10240 rectangles
POLICIES = (None, True, False)   # Default, Allow, Block (mod_settings npc_transform_overrides values)
POLICY_LABELS = {None: 'Default', True: 'Allow', False: 'Block'}
# Display only: a row is dimmed while its master switch does not enable it.
DEPENDS = {
    'lockoff_button': ('lockoff_enabled', True),
    'lockoff_hold_seconds': ('lockoff_enabled', True),
    'lockoff_target_hud': ('lockoff_enabled', True),
    'lockon_right_stick_mode': ('lockon_right_stick', True),
    'lockon_target_style': ('lockon_target_marker', True),
    'show_fusion_control_owner': ('coop_fusion_controls', 'swap_20s'),
    'show_fusion_control_countdown': ('coop_fusion_controls', 'swap_20s'),
    'fusion_duration_seconds': ('fusion_duration_enabled', True),
    'show_fusion_timer': ('fusion_duration_enabled', True),
    'fusion_defusion_animation': ('fusion_duration_enabled', True),
    'ginyu_stolen_abilities': ('true_body_change', True),
    'giant_size_multiplier': ('canonical_giants', True),
    'giant_attack_speed_percent': ('canonical_giants', True),
    'giant_damage_percent': ('canonical_giants', True),
    'giant_armor_levels': ('canonical_giants', True),
    'giant_camera_distance_percent': ('canonical_giants', True),
    'show_hud_portraits': ('split_hud_style', 'native'),
    'show_hud_sparking_effects': ('split_hud_style', 'native'),
    'takeover_hint_seconds': ('show_takeover_hints', True),
    'takeover_confirmation_seconds': ('show_takeover_confirmation', True),
    'revive_stock_cost': ('revive_enabled', True),
    'revive_channel_seconds': ('revive_enabled', True),
    'revive_radius': ('revive_enabled', True),
    'revive_health_bars': ('revive_enabled', True),
    'revive_recovery_seconds': ('revive_enabled', True),
    'show_revive_ring': ('revive_enabled', True),
    'revive_ring_opacity': ('show_revive_ring', True),
    'revive_ring_wave_height': ('show_revive_ring', True),
    'revive_ring_wave_speed': ('show_revive_ring', True),
    # Outnumbered: the value rows serve only the Custom preset.
    'outnumbered_damage_bonus_percent': ('outnumbered_preset', 'custom'),
    'outnumbered_damage_reduction_percent': ('outnumbered_preset', 'custom'),
    'outnumbered_recovery_speed_percent': ('outnumbered_preset', 'custom'),
    'outnumbered_getup_protection_seconds': ('outnumbered_preset', 'custom'),
    'outnumbered_combo_breaker_hits': ('outnumbered_preset', 'custom'),
    'training_health_delay_seconds': ('training_refill_health', True),
    'beam_struggle_damage_penalty_percent': ('beam_struggle_interference', True),
    'beam_assist_multiplier_percent': ('beam_assist_enabled', True),
    'beam_assist_cpu': ('beam_assist_enabled', True),
    'beam_assist_range': ('beam_assist_enabled', True),
    'ground_motion_style': ('ground_running', True),
    'ground_walk_tilt_percent': ('ground_running', True),
    'ground_walk_speed_percent': ('ground_running', True),
    'ground_run_speed_percent': ('ground_running', True),
    'ground_size_speed': ('ground_running', True),
}
# Display only, like DEPENDS: a row is also dimmed while other settings all hold values that disable it.
DIMMED_BY = {
    # Outnumbered: who is helped matters for every preset except Off.
    'outnumbered_scope': (('outnumbered_preset', 'off'),),
    'outnumbered_applies_to': (('outnumbered_preset', 'off'),),
    # R3 is the right stick's own click: it cannot be held while flicking. The stick alone still aims with R3.
    'lockon_right_stick': (('lockon_switch_button', 'r3'), ('lockon_right_stick_mode', 'with_switch_button')),
}
# Display only, like DEPENDS: a button row is also dimmed while it equals another button that takes precedence (the
# match then installs nothing for it): (other key, None or the (switch, value) under which the other counts).
CONFLICTS = {}
# Circle help for the two rows after the categories: (help heading, text).
ROW_HELP = {
    'exceptions': ('CPU transformation exceptions',
                   'An exception applies to a CPU fighter in that character or form. Default follows the CPU '
                   'switches; Allow ignores them (the chance setting still applies); Block stops it from '
                   'transforming. Humans are unaffected. Select lists only the exceptions. Applies from the next '
                   'match; a Fight Again rematch keeps the settings of its match.'),
    'restore': ('Restore defaults',
                'Restore defaults stages the default of every setting except the language and clears the '
                'per-character exceptions. It never turns the mod mode menus off. Nothing is saved until you '
                'press Square.'),
}
# Every English string these screens show (templates before formatting);
# test_ingame_settings checks each has a Spanish translation.
TEXTS = (
    'MOD SETTINGS', 'Choose a category', 'Per-character exceptions ({n} set)…', 'Restore defaults…',
    'Up/Down: select    Cross: open    Circle: help', 'Square: save and exit    Triangle: close',
    'Up/Down: select    Left/Right: change    L2/R2: ×10', 'Up/Down: select    Left/Right: change    L2/R2: first/last',
    'Up/Down: select    Left/Right: change    L2/R2: off/on',
    'L1/R1: category    Circle: help    Square: save    Triangle: back',
    'Help: {group}', 'Circle or Triangle: back',
    'CPU transformation exceptions', 'Default follows the CPU switches; Allow and Block override them.',
    'Only characters with an exception ({n})', 'No exceptions set.',
    'Up/Down: select    Left/Right: change    L1/R1: page    L2/R2: 5 pages',
    'Select: exceptions only    Square: save    Triangle: back',
    'Select: every character    Square: save    Triangle: back',
    'Default', 'Allow', 'Block',
    'Discard unsaved changes?', 'Your unsaved changes will be lost.',
    'Triangle: discard and close    Cross: go back', 'Square: save and exit',
    'Restore defaults?',
    'Every setting except the language returns to its default and the per-character exceptions are cleared. Nothing is saved until you press Square.',
    'Cross: restore    Triangle: back',
    'Turn off the mod mode menus?',
    'This screen opens from those menus, so after saving only the desktop Mod settings (Mod settings.cmd) can turn them back on.',
    'Cross: turn off    Triangle: keep on',
    'Your settings could not be opened. The saved file was left unchanged.',
    'Repair replaces the file with the default settings and keeps a copy as {name}.',
    'Cross: repair settings    Triangle: close',
    'This screen could not be drawn.', 'Cross: back to the categories    Triangle: close', 'Triangle: close',
    'Your settings could not be repaired.', 'Settings repaired. The old file was kept as {name}.',
    'Your changes could not be saved.', 'Saved.', 'Saved. Launch options apply after restarting Play.',
    'Defaults restored. Save to keep them.', '{n} unsaved changes', '1 unsaved change',
    'Character {cid}', 'Restore defaults', *(text for pair in ROW_HELP.values() for text in pair),
)
# Colours. Small text is drawn without antialiasing; the title and the value
# line keep it and are mapped to a fixed palette with two blend steps.
BG, PANEL, OUTLINE, ACCENT = (9,15,27), (31,52,81), (237,184,74), (241,177,55)
TITLE, HEADER, LABEL, VALUE = (243,194,97), (122,201,240), (233,237,243), (243,194,97)
FOOTER, OK, ERROR, DIM = (178,200,222), (125,208,137), (245,112,101), (112,124,142)
SMOOTH = ((TITLE, BG), (VALUE, BG), (VALUE, PANEL), (DIM, BG), (DIM, PANEL), (HEADER, BG), (LABEL, BG))
FONT, BOLD = fonts.path('sans'), fonts.path('sans-bold')   # Arial on Windows, bundled Liberation Sans elsewhere
WIDTH, HEIGHT = 512, 448
TEXT_WIDTH = 468          # footer, status, help and confirmation lines (x 22..490)
LABEL_WIDTH = 459         # a setting label on its row


@lru_cache(maxsize=None)
def _font(path, size):
    return fonts.truetype(path, size)


@lru_cache(maxsize=1)
def _palette():
    from PIL import Image
    colors = [BG, PANEL, OUTLINE, ACCENT, TITLE, HEADER, LABEL, FOOTER, OK, ERROR, DIM]
    for fg, bg in SMOOTH:
        colors += [tuple(round(b+(f-b)*t) for f, b in zip(fg, bg)) for t in (1/3, 2/3)]
    image = Image.new('P', (1, 1))
    flat = [c for rgb in colors for c in rgb]
    image.putpalette(flat + flat[:3]*(256-len(colors)))
    return image


class Canvas:
    """One 512x448 picture; records every text that had to be shortened."""
    def __init__(self):
        from PIL import Image, ImageDraw
        self.image = Image.new('RGB', (WIDTH, HEIGHT), BG)
        self.draw = ImageDraw.Draw(self.image)
        self.trimmed = []

    def font(self, size, bold=False):
        return _font(BOLD if bold else FONT, size)

    def width(self, text, size=12, bold=False, smooth=False):
        self.draw.fontmode = 'L' if smooth else '1'
        return self.draw.textlength(text, font=self.font(size, bold))

    def fit(self, text, limit, size=12, bold=False, smooth=False, trim_ok=False):
        if self.width(text, size, bold, smooth) <= limit:
            return text
        if not trim_ok:
            self.trimmed.append(text)
        while text and self.width(text+'…', size, bold, smooth) > limit:
            text = text[:-1]
        return text.rstrip()+'…'

    def text(self, xy, text, size=12, bold=False, fill=LABEL, smooth=False, limit=TEXT_WIDTH, trim_ok=False):
        text = self.fit(text, limit, size, bold, smooth, trim_ok)
        self.draw.fontmode = 'L' if smooth else '1'
        self.draw.text(xy, text, font=self.font(size, bold), fill=fill)

    def right(self, x, y, text, size=12, bold=False, fill=FOOTER):
        self.text((x-self.width(text, size, bold), y), text, size, bold, fill)

    def wrap(self, text, limit=TEXT_WIDTH, size=12, bold=False, lines=None):
        """Word-wrapped lines; the last kept line ends in an ellipsis when cut."""
        result = []
        for paragraph in text.split('\n'):
            line = ''
            for word in paragraph.split():
                candidate = (line+' '+word).strip()
                if line and self.width(candidate, size, bold) > limit:
                    result.append(line); line = word
                else:
                    line = candidate
            result.append(line)
        if lines is not None and len(result) > lines:
            if lines <= 0:
                return []
            result = result[:lines]
            result[-1] = self.fit(result[-1]+' …', limit, size, bold, trim_ok=True)
        return [self.fit(line, limit, size, bold, trim_ok=True) for line in result]

    def finish(self):
        from PIL import Image
        return self.image.quantize(palette=_palette(), dither=Image.Dither.NONE).convert('RGB')


def rectangles(picture):
    import guest_loading_screen
    return guest_loading_screen.picture_rectangles(picture)


def format_number(value):
    if type(value) is int:
        return str(value)
    text = f'{value:.3f}'.rstrip('0')
    return text+'0' if text.endswith('.') else text


class Controller:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.active = False; self.screen = None; self.input_ready = False; self.presented_once = False
        self.groups = mod_settings.ui_groups()
        self.group = 0; self.row = 0; self.index_row = 0; self.view = 'index'; self.back_view = 'index'
        self.values = {}; self.saved = {}; self.status = ('', OK); self.dirty = True; self.closing = False
        self.character = 0; self.exceptions_only = False; self.character_ids = list(mod_settings.NPC_OVERRIDE_IDS)
        self.filtered = []; self.help_topic = None   # a ROW_HELP key, or None for the page note
        self.confirming = None; self.failure = None; self.held = {}; self.trimmed = []
        self.report = None        # the file's settings after this visit's last save or repair

    # ---- model -------------------------------------------------------------
    def tr(self, text, **values):
        return localization.tr(text, self.values or None, **values)

    def fields(self, group=None):
        name = self.groups[self.group if group is None else group]
        return [(key, row) for key, row in mod_settings.ui_fields().items() if row[4] == name]

    def changes(self):
        """Staged values that differ from the saved file (settings and exceptions)."""
        if not self.saved:
            return {}
        keys = (*mod_settings.ui_fields(), mod_settings.NPC_OVERRIDES_KEY)
        return {key: copy.deepcopy(self.values[key]) for key in keys if self.values.get(key) != self.saved.get(key)}

    def dimmed(self, key, values=None):
        values = self.values if values is None else values
        if key in DIMMED_BY and all(values.get(other) == value for other, value in DIMMED_BY[key]):
            return True
        for other, condition in CONFLICTS.get(key, ()):
            if values.get(key) == values.get(other) and (condition is None or values.get(condition[0]) == condition[1]):
                return True
        seen = set()
        while key in DEPENDS and key not in seen:
            seen.add(key); master, wanted = DEPENDS[key]
            if values.get(master) != wanted:
                return True
            key = master
        return False

    def overrides(self):
        return self.values.get(mod_settings.NPC_OVERRIDES_KEY, {})

    def back_button(self):
        """The configured menu switch button, when this screen has no other use for it."""
        mask = input_binding.MASKS.get((self.saved or {}).get('menu_toggle_button', 'select'), 0)
        return 0 if mask & USED[self.view] else mask

    def value_text(self, key):
        value = self.values[key]
        if type(value) in (int, float):
            return format_number(value)
        return localization.value_label(value, self.values or None)

    def character_rows(self):
        if not self.exceptions_only:
            return self.character_ids
        return self.filtered

    # ---- rendering -----------------------------------------------------------
    def picture(self):
        canvas = Canvas()
        getattr(self, '_draw_'+self.view)(canvas)
        self.trimmed = canvas.trimmed
        return canvas.finish()

    def _frame(self, c, header, right=''):
        c.draw.rectangle((0, 0, WIDTH-1, 4), fill=ACCENT)
        c.text((20, 14), self.tr('MOD SETTINGS'), 23, True, TITLE, smooth=True)
        limit = TEXT_WIDTH-(c.width(right)+12 if right else 0)
        c.text((22, 48), header, 14, True, HEADER, limit=limit)
        if right:
            c.right(490, 50, right)

    def _footer(self, c, *lines, status=True):
        for i, line in enumerate(lines):
            c.text((22, 366+i*18), line, fill=FOOTER)
        if not status:
            return
        text, color = self.status
        if not text:
            count = len(self.changes())
            text = self.tr('1 unsaved change') if count == 1 else self.tr('{n} unsaved changes', n=count)
            color = OK
        for i, line in enumerate(c.wrap(text, lines=2)):
            c.text((22, 406+i*17), line, fill=color, trim_ok=True)

    def _marker(self, c, y):
        c.draw.rectangle((7, y+4, 10, y+7), fill=OUTLINE)

    def _draw_index(self, c):
        self._frame(c, self.tr('Choose a category'))
        changed = self.changes()
        fields = mod_settings.ui_fields()
        count = len(self.overrides())
        rows = [self.tr(group) for group in self.groups]
        rows += [self.tr('Per-character exceptions ({n} set)…', n=count), self.tr('Restore defaults…')]
        # Windowed index: identical with INDEX_VISIBLE rows or fewer, otherwise the window follows the selection.
        first = 0 if len(rows) <= INDEX_VISIBLE else min(max(0, self.index_row-INDEX_VISIBLE+1), len(rows)-INDEX_VISIBLE)
        if len(rows) > INDEX_VISIBLE and self.index_row < first: first = self.index_row
        for slot, i in enumerate(range(first, min(len(rows), first+INDEX_VISIBLE))):
            text = rows[i]
            y = 70+slot*18+(6 if (i >= len(self.groups) and first <= len(self.groups)) else 0)
            if i == self.index_row:
                c.draw.rectangle((15, y-2, 497, y+15), fill=PANEL, outline=OUTLINE)
            if i < len(self.groups):
                mark = any(fields[key][4] == self.groups[i] for key in changed if key in fields)
            else:
                mark = i == len(self.groups) and mod_settings.NPC_OVERRIDES_KEY in changed
            if mark:
                self._marker(c, y-1)
            c.text((24, y), text, 12, True, LABEL, limit=440)
        if len(rows) > INDEX_VISIBLE:
            if first > 0: c.draw.polygon(((490, 62), (496, 68), (484, 68)), fill=FOOTER)
            if first+INDEX_VISIBLE < len(rows): c.draw.polygon(((484, 356), (496, 356), (490, 362)), fill=FOOTER)
        self._footer(c, self.tr('Up/Down: select    Cross: open    Circle: help'),
                     self.tr('Square: save and exit    Triangle: close'))

    def _draw_page(self, c):
        fields = self.fields(); changed = self.changes()
        name = self.groups[self.group]
        self._frame(c, f'{self.tr(name)}  ({self.group+1}/{len(self.groups)})', f'{self.row+1}/{len(fields)}')
        page = self.row//ROWS
        for index, (key, meta) in enumerate(fields[page*ROWS:page*ROWS+ROWS], page*ROWS):
            y = 80+(index % ROWS)*41; selected = index == self.row; dim = self.dimmed(key)
            if selected:
                c.draw.rectangle((15, y-4, 497, y+33), fill=PANEL, outline=OUTLINE)
            if key in changed:
                self._marker(c, y)
            c.text((23, y), self.tr(meta[5]), 12, False, DIM if dim else LABEL, limit=LABEL_WIDTH)
            value = self.value_text(key)
            c.text((26, y+16), '<  '+value+'  >' if selected else value, 14, True, DIM if dim else VALUE,
                   smooth=True, limit=LABEL_WIDTH)
        kind = fields[self.row][1][1]
        big = {'bool': 'Up/Down: select    Left/Right: change    L2/R2: off/on',
               'int': 'Up/Down: select    Left/Right: change    L2/R2: ×10',
               'float': 'Up/Down: select    Left/Right: change    L2/R2: ×10'}.get(
                   kind, 'Up/Down: select    Left/Right: change    L2/R2: first/last')
        self._footer(c, self.tr(big), self.tr('L1/R1: category    Circle: help    Square: save    Triangle: back'))

    def _draw_help(self, c):
        if self.help_topic is not None:
            heading, note = ROW_HELP[self.help_topic]
            heading, note = self.tr(heading), self.tr(note)
        else:
            name = self.groups[self.group]
            heading, note = self.tr(name), mod_settings.help_note(name, self.values or None)
        self._frame(c, self.tr('Help: {group}', group=heading))
        for i, line in enumerate(c.wrap(note, size=13, lines=14)):
            c.text((22, 78+i*19), line, 13, False, LABEL)
        self._footer(c, self.tr('Circle or Triangle: back'), status=False)

    def _draw_exceptions(self, c):
        from character_names import character_table
        table = character_table(); ids = self.character_rows(); overrides = self.overrides()
        pages = max(1, -(-len(ids)//CHARACTER_ROWS)); page = self.character//CHARACTER_ROWS
        self._frame(c, self.tr('CPU transformation exceptions'), f'{page+1}/{pages}')
        note = (self.tr('Only characters with an exception ({n})', n=len(ids)) if self.exceptions_only
                else self.tr('Default follows the CPU switches; Allow and Block override them.'))
        c.text((22, 68), note, fill=FOOTER)
        if not ids:
            c.text((24, 92), self.tr('No exceptions set.'), fill=LABEL)
        colors = {None: FOOTER, True: OK, False: ERROR}
        for index, cid in enumerate(ids[page*CHARACTER_ROWS:page*CHARACTER_ROWS+CHARACTER_ROWS], page*CHARACTER_ROWS):
            y = 90+(index % CHARACTER_ROWS)*21
            if index == self.character:
                c.draw.rectangle((15, y-3, 497, y+16), fill=PANEL, outline=OUTLINE)
            name = table.get(cid, {}).get('name') or self.tr('Character {cid}', cid=cid)
            c.text((24, y), name, 12, False, LABEL, limit=330, trim_ok=True)
            policy = overrides.get(str(cid))
            c.text((370, y), self.tr(POLICY_LABELS[policy]), 12, True, colors[policy], limit=120)
        self._footer(c, self.tr('Up/Down: select    Left/Right: change    L1/R1: page    L2/R2: 5 pages'),
                     self.tr('Select: every character    Square: save    Triangle: back' if self.exceptions_only
                             else 'Select: exceptions only    Square: save    Triangle: back'))

    CONFIRM = {
        'discard': ('Discard unsaved changes?', 'Your unsaved changes will be lost.',
                    ('Triangle: discard and close    Cross: go back', 'Square: save and exit')),
        'restore': ('Restore defaults?', 'Every setting except the language returns to its default and the '
                    'per-character exceptions are cleared. Nothing is saved until you press Square.',
                    ('Cross: restore    Triangle: back',)),
        'menus_off': ('Turn off the mod mode menus?', 'This screen opens from those menus, so after saving only '
                      'the desktop Mod settings (Mod settings.cmd) can turn them back on.',
                      ('Cross: turn off    Triangle: keep on',)),
    }

    def _draw_confirm(self, c):
        heading, body, keys = self.CONFIRM[self.confirming]
        self._frame(c, self.tr(heading))
        for i, line in enumerate(c.wrap(self.tr(body), size=13, lines=8)):
            c.text((22, 90+i*20), line, 13, False, LABEL)
        self._footer(c, *(self.tr(k) for k in keys))

    def _draw_error(self, c):
        failure = self.failure
        self._frame(c, '')
        y = 76
        for line in c.wrap(self.tr(failure['title']), lines=3):
            c.text((22, y), line, fill=ERROR, trim_ok=True); y += 17
        y += 8
        for line in c.wrap(failure['detail'], lines=failure.get('lines', 10)):
            c.text((22, y), line, fill=LABEL, trim_ok=True); y += 17
        if failure['repair']:
            name = mod_settings.broken_copy_path().name
            y += 8
            for line in c.wrap(self.tr('Repair replaces the file with the default settings and keeps a copy as {name}.',
                                       name=name), lines=3):
                c.text((22, y), line, fill=FOOTER, trim_ok=True); y += 17
            keys = 'Cross: repair settings    Triangle: close'
        elif failure['back']:
            keys = 'Cross: back to the categories    Triangle: close'
        else:
            keys = 'Triangle: close'
        self._footer(c, self.tr(keys), status=False)

    def error_picture(self):
        """The error screen, shortened until it certainly fits the sprite budget.

        Missing fonts, or no text version that fits, fall back to a fixed
        screen in PIL's built-in bitmap font.
        """
        for lines in (10, 6, 3, 1):
            self.failure['lines'] = lines
            try:
                image = self.picture()
            except OSError:
                image = self._plain_error()
            if len(rectangles(image)) < BUDGET:
                return image
        return self._plain_error()

    def _plain_error(self):
        from PIL import Image, ImageDraw, ImageFont
        image = Image.new('RGB', (WIDTH, HEIGHT), BG); d = ImageDraw.Draw(image)
        d.rectangle((0, 0, WIDTH-1, 4), fill=ACCENT)
        d.text((22, 60), 'MOD SETTINGS ERROR', font=ImageFont.load_default(), fill=ERROR)
        d.text((22, 380), 'TRIANGLE: CLOSE', font=ImageFont.load_default(), fill=FOOTER)
        return image

    # ---- host loop -------------------------------------------------------------
    def open(self):
        from guest_loading_screen import GuestLoadingScreen
        self.screen = GuestLoadingScreen(); self.active = True; self.dirty = True; self.input_ready = False
        self.presented_once = False; self.held = {}; self.status = ('', OK); self.closing = False
        self.confirming = None; self.failure = None; self.view = 'index'; self.index_row = self.group
        self.values = {}; self.saved = {}; self.help_topic = None
        try:
            self.saved = mod_settings.load_settings()
        except (ValueError, OSError) as error:
            self.fail('Your settings could not be opened. The saved file was left unchanged.', error,
                      repair=isinstance(error, ValueError))
            return
        self.values = copy.deepcopy(self.saved)

    def fail(self, title, error, *, repair=False, back=False):
        self.failure = dict(title=title, detail=str(error), repair=repair, back=back)
        self.view = 'error'; self.dirty = True

    def publish(self, p):
        """Draw the current screen; a picture that cannot be drawn becomes the error screen."""
        try:
            image = self.error_picture() if self.view == 'error' else self.picture()
            self.screen.show_picture(image, surface='menu', client=p)
        except (ValueError, OSError) as error:
            if self.view == 'error':
                self.close(p); return
            self.fail('This screen could not be drawn.', error, back=True)
            try:
                self.screen.show_picture(self.error_picture(), surface='menu', client=p)
            except (ValueError, OSError):
                self.close(p); return
        self.dirty = False

    def repeats(self, edges, pad):
        """Directions held past REPEAT_DELAY act as a press every poll."""
        now = self.clock(); result = 0
        for bit in (UP, DOWN, LEFT, RIGHT):
            if edges & bit:
                self.held[bit] = now
            elif pad & bit and bit in self.held:
                if now-self.held[bit] >= REPEAT_DELAY:
                    result |= bit
            else:
                self.held.pop(bit, None)
        return result

    def tick(self, p):
        """One host poll. Returns the saved settings once, on the poll that
        closes a visit which saved or repaired them, and None otherwise.

        The native menu queues a refresh whenever the returned settings differ
        from its own and applies it only after this screen closes, so it must
        see the final saved state of the visit, never an intermediate save.
        """
        self._poll(p)
        if self.active or self.report is None:
            return None
        report, self.report = self.report, None
        return report

    def _poll(self, p):
        state = struct.unpack('<3I', p.read(CONTROL, 12))
        wanted = state[0] == MAGIC and state[1] == 1
        if not wanted:
            if self.active: self.close(p)
            return
        if not self.active: self.open()
        p.write_u32(CONTROL+8, 180)
        edges = p.read_u32(CONTROL+12) & 0xFFFF
        if edges: p.write_u32(CONTROL+12, 0)
        repeats = 0
        if not self.screen.presented(p):
            # Nothing visible to act on. Triangle still hands control back,
            # asking first once edits exist that a visible screen showed.
            if edges & TRIANGLE:
                if (not self.presented_once or not self.changes() or
                        (self.view == 'confirm' and self.confirming == 'discard')):
                    self.close(p); return
                self.ask('discard', 'index'); self.dirty = True
            edges = 0
        elif not self.input_ready:
            self.presented_once = True
            self.input_ready = (p.read_u32(PAD+0x150) & 0xFFFF) == 0
            edges = 0
        else:
            self.presented_once = True
            repeats = self.repeats(edges, p.read_u32(PAD+0x150) & 0xFFFF)
        if edges or repeats:
            self.press(edges, repeats)
        if self.closing:
            self.close(p); return
        if self.dirty: self.publish(p)
        else: self.screen.sync(client=p)

    def close(self, p):
        p.write_u32(CONTROL+4,0);p.write_u32(CONTROL+12,0)
        # Retain the released edge in the native pager as well as this modal.
        p.write_u32(MENU+28,p.read_u32(PAD+0x150))
        if self.screen:self.screen.hide(client=p)
        self.screen=None;self.active=False;self.closing=False;self.held={}

    # ---- input -------------------------------------------------------------------
    def press(self, edges, repeats=0):
        """Apply one poll's presses; returns the saved settings after a save
        (tick reports only the visit's final saved state, when it closes)."""
        back = self.back_button()
        if back and edges & back:
            edges = (edges & ~back) | BACK
        self.dirty = True
        handler = getattr(self, '_press_'+self.view)
        view = self.view
        result = handler(edges, repeats)
        if self.view != view:
            self.held = {}
        return result

    def ask(self, kind, back_view=None):
        self.confirming = kind; self.back_view = back_view or self.view; self.view = 'confirm'

    def leave(self):
        if self.changes():
            self.ask('discard', 'index')
        else:
            self.closing = True

    def _press_index(self, edges, repeats):
        count = len(self.groups)+2
        if edges & SQUARE:
            return self.save(exit=True)
        if edges & (TRIANGLE | BACK):
            self.leave(); return None
        if edges & CIRCLE:
            if self.index_row < len(self.groups):
                self.group = self.index_row; self.help_topic = None
            else:
                self.help_topic = 'exceptions' if self.index_row == len(self.groups) else 'restore'
            self.back_view = 'index'; self.view = 'help'; return None
        if edges & CROSS:
            if self.index_row < len(self.groups):
                self.group = self.index_row; self.row = 0; self.view = 'page'
            elif self.index_row == len(self.groups):
                self.filtered = [cid for cid in self.character_ids if str(cid) in self.overrides()]
                self.character = 0; self.view = 'exceptions'
            else:
                self.ask('restore', 'index')
            self.status = ('', OK); return None
        moves = edges | repeats
        if moves & (UP | DOWN):
            self.index_row = (self.index_row+(1 if moves & DOWN else -1)) % count
        return None

    def _press_page(self, edges, repeats):
        fields = self.fields()
        if edges & SQUARE:
            return self.save(exit=False)
        if edges & (TRIANGLE | BACK):
            self.view = 'index'; self.index_row = self.group; return None
        if edges & CIRCLE:
            self.help_topic = None; self.back_view = 'page'; self.view = 'help'; return None
        if edges & (L1 | R1):
            self.group = (self.group+(1 if edges & R1 else -1)) % len(self.groups); self.row = 0
            self.status = ('', OK); return None
        moves = edges | repeats
        if moves & (UP | DOWN):
            self.row = (self.row+(1 if moves & DOWN else -1)) % len(fields)
            self.status = ('', OK); return None
        key, meta = fields[self.row]
        numeric = meta[1] in ('int', 'float')
        if edges & (L2 | R2):
            return self.change(key, 1 if edges & R2 else -1, big=True)
        steps = edges | (repeats if numeric else 0)
        if steps & (LEFT | RIGHT | CROSS):
            return self.change(key, -1 if steps & LEFT else 1)
        return None

    def change(self, key, direction, big=False):
        kind = mod_settings.ui_fields()[key][1]
        current = self.values[key]
        value = feature_preferences.step_value(key, current, direction, big)
        if value == current and type(value) is type(current):
            return None
        self.status = ('', OK)
        if key == 'native_mode_menu_enabled' and current is True and value is False:
            self.ask('menus_off', 'page'); return None
        if kind == 'bool' and value is True and key in mod_settings.CHECKED_ENABLES:
            allowed, message = mod_settings.can_enable(key, self.values)
            if not allowed:
                self.status = (message, ERROR); return None
        self.values[key] = value
        return None

    def _press_help(self, edges, repeats):
        if edges & (CIRCLE | CROSS | TRIANGLE | BACK):
            self.view = self.back_view
            # A category's help returns to that category's row; an extra row's help to that row.
            if self.view == 'index' and self.help_topic is None: self.index_row = self.group
            self.help_topic = None
        return None

    def _press_exceptions(self, edges, repeats):
        ids = self.character_rows()
        if edges & SQUARE:
            return self.save(exit=False)
        if edges & (TRIANGLE | BACK):
            self.view = 'index'; self.index_row = len(self.groups); return None
        if edges & SELECT:
            self.exceptions_only = not self.exceptions_only
            # The filtered list stays put while editing, even when a row returns to Default.
            self.filtered = [cid for cid in self.character_ids if str(cid) in self.overrides()]
            self.character = 0; return None
        if not ids:
            return None
        moves = edges | repeats
        pages = -(-len(ids)//CHARACTER_ROWS)
        if moves & (UP | DOWN):
            self.character = (self.character+(1 if moves & DOWN else -1)) % len(ids); return None
        if edges & (L1 | R1 | L2 | R2):
            jump = (JUMP_PAGES if edges & (L2 | R2) else 1)*(1 if edges & (R1 | R2) else -1)
            page = (self.character//CHARACTER_ROWS+jump) % pages
            self.character = min(page*CHARACTER_ROWS, len(ids)-1); return None
        if edges & (LEFT | RIGHT | CROSS):
            cid = str(ids[self.character]); overrides = dict(self.overrides())
            policy = POLICIES[(POLICIES.index(overrides.get(cid))+(-1 if edges & LEFT else 1)) % len(POLICIES)]
            if policy is None: overrides.pop(cid, None)
            else: overrides[cid] = policy
            self.values[mod_settings.NPC_OVERRIDES_KEY] = overrides
        return None

    def _press_confirm(self, edges, repeats):
        kind = self.confirming
        if kind == 'discard':
            if edges & SQUARE:
                self.view = 'index'; return self.save(exit=True)
            if edges & TRIANGLE:
                self.values = copy.deepcopy(self.saved); self.closing = True; return None
            if edges & (CROSS | BACK):
                self.view = self.back_view
            return None
        if edges & CROSS:
            if kind == 'restore':
                self.restore()
            elif kind == 'menus_off':
                self.values['native_mode_menu_enabled'] = False
            self.view = self.back_view; return None
        if edges & (TRIANGLE | BACK):
            self.view = self.back_view
        return None

    def _press_error(self, edges, repeats):
        failure = self.failure
        if edges & CROSS and failure['repair']:
            return self.repair()
        if edges & (CROSS | BACK) and failure['back']:
            self.view = 'index'; self.status = ('', OK); return None
        if edges & (TRIANGLE | BACK):
            self.closing = True
        return None

    # ---- actions -------------------------------------------------------------------
    def save(self, exit):
        changes = self.changes()
        if not changes:
            # Nothing staged: the file is never rewritten (or created).
            if exit: self.closing = True
            else: self.status = (self.tr('Saved.'), OK)
            return None
        try:
            settings = mod_settings.save_settings(changes)
        except (OSError, ValueError) as error:
            self.status = (self.tr('Your changes could not be saved.')+' '+str(error), ERROR); return None
        if isinstance(settings, dict):
            self.saved = copy.deepcopy(settings); self.values = copy.deepcopy(settings)
            self.report = copy.deepcopy(settings)
        if any(key in feature_preferences.RESTART_KEYS for key in changes):
            self.status = (self.tr('Saved. Launch options apply after restarting Play.'), OK)
        elif exit:
            self.closing = True
        else:
            self.status = (self.tr('Saved.'), OK)
        return settings

    def restore(self):
        """Stage the defaults (mod_settings.default_settings: never the language)."""
        fields = mod_settings.ui_fields()
        for key, value in mod_settings.default_settings().items():
            if key in fields or key == mod_settings.NPC_OVERRIDES_KEY:
                self.values[key] = copy.deepcopy(value)
        for key in mod_settings.CHECKED_ENABLES:
            if self.values.get(key) is True and not mod_settings.can_enable(key, self.values)[0]:
                self.values[key] = False
        # Turning the mod menus off in game always takes its own confirmation.
        if self.saved.get('native_mode_menu_enabled') is True:
            self.values['native_mode_menu_enabled'] = True
        self.status = (self.tr('Defaults restored. Save to keep them.'), OK)

    def repair(self):
        name = mod_settings.broken_copy_path().name   # where repair_settings keeps the old file
        try:
            settings = mod_settings.repair_settings()
        except (OSError, ValueError) as error:
            self.fail('Your settings could not be repaired.', error); return None
        self.saved = copy.deepcopy(settings); self.values = copy.deepcopy(settings)
        self.report = copy.deepcopy(settings)
        self.view = 'index'; self.failure = None
        self.status = (self.tr('Settings repaired. The old file was kept as {name}.', name=name), OK)
        return settings
