"""Lock-on target selection (lockon_select) in the guest instruction harness.

The queue's lock-off emission, the unchanged lock-off programs and lockon_select run on the FPU-capable
interpreter, with an orthographic native projection (screen x = world x, screen y = world y), per the
lock-on design's tests T-1..T-18 as amended (circle order, stick masking latch, stale P3/P4 records,
merged co-op pad, release lock-off, KO debounce, combat-only marker, exact view seat), and the beta.35 additions
(the right stick alone and the hold-mode R3 fix), and the beta.38 target ring (one packet before the bars, its drop-in).
"""
import copy
import json
import math
import os
import random
import re
import struct
import unittest
from pathlib import Path
from unittest.mock import patch

import battle_mode_policy as modes
import coop_controller as coop
import display_settings as display
import fresh_team_camera as follow
import fresh_team_combat as core
import guest_healthbars as bars
import hud_subject
import lockoff_target as off
import lockon_queue as q
import lockon_select as sel
import lockon_threat as threat
import lockon_switch as ls
import mod_settings
import quad_controller as quad
import quad_viewports as views
import team_participation as part
from input_script import RECORDS
from native_map import A
from prototype import ROOT
from test_fusion_partner_lifecycle import FusionCpu

GP, MANAGER, CAM = 0x304270, 0x1870400, 0x1900000
ACTORS = [0x2000000+i*0x2000 for i in range(12)]
MODELS = [0x3000000+i*0x2000 for i in range(12)]
BONES = [0x3100000+i*0x100 for i in range(12)]
PREVIOUS = 0x07200600
BATTLE = 0x1A00000
ORTHO = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1792, 1824, 0, 1)
MIRROR = (-1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1792+511, 1824, 0, 1)
L3, R3, RIGHT, LEFT, DOWN, UP = 0x2, 0x4, sel.RIGHT, sel.LEFT, sel.DOWN, sel.UP
# Real prepared images with the lock-off program, per game: (image, its battle mode, a Fight Again image).
# BT3: a Sept 24 six-fighter FFA and its staged rematch. BT4: its Sept 24 two-a-side teams match (no battle-mode
# record; the teams rematch path does not re-validate lock-off, so only acceptance is checked there).
IMAGES = {'BT3': ('20260924-134818-fac07f48/17-playable-team.p2s', 'ffa', '20260924-210159-7eaae701/rematch-staged.p2s'),
          'BT4': ('20260924-220908-25fb4413/19-playable-team.p2s', None, '20260924-220908-25fb4413/19-playable-team.p2s')}
IMAGE, IMAGE_MODE, REMATCH_IMAGE = IMAGES[mod_settings.ADAPTER]
FIXTURE_FFA = ROOT/'analysis/prepared-states'/IMAGE
QUAD_NEXT = 0x07210000   # where the quad frame emission continues (a harness stop)
PRESSED_WORDS = (336, 340)


def project(matrix, point):
    clip = [sum(matrix[k*4+j]*point[k] for k in range(4)) for j in range(4)]
    if not all(math.isfinite(x) for x in clip) or clip[3] <= 0: return None
    return int(clip[0]/clip[3]*16), int(clip[1]/clip[3]*16), 1, max(1, int(clip[3]))


def settings(**values):
    base = {'lockon_switch_button': 'l3', 'lockon_hold_seconds': 0.0}
    base.update(values)
    return mod_settings.validate_settings(base)


# lockon_threat runs in front of these programs, so its two keys are legacy here too.
LEGACY = dict(lockon_cycle_order='selection_order', lockon_right_stick=False, lockon_after_ko='game_default',
              lockon_target_marker=False, lockon_attacker_switch='never', lockon_threat_marks='hide')


def make(count=6, humans=(0,), mode='teams', positions=None, view=(0, 511, 0, 447), button=L3, off_button=L3,
         threshold=15, on_threshold=1, order='left_to_right', stick=1, after_ko=1, marker=1, resolver=None,
         install=True, targets=None, matrix=ORTHO, side=0, style=2):
    c = FusionCpu(); c.r[28] = GP
    c.w(core.ACTORS, MANAGER); c.w(MANAGER, 2); c.w(MANAGER+4, ACTORS[0])
    c.write(core.MODE, struct.pack('<4I', 1, count, MANAGER, count))
    positions = positions or [(40+40*i, 224, 0) for i in range(count)]
    for i in range(count):
        a, m = ACTORS[i], MODELS[i]
        c.w(core.POINTERS+4*i, a)
        for field, value in ((0, i), (4, i if i < 2 else i & 1), (8, i & 1), (12, i), (0x994, 0), (0x9E4, 1000),
                             (0x9E8, 1000), (0x948, 11), (0x1278, 0 if i in humans else 1)):
            c.w(a+field, value)
        c.w(core.MODELS+4*i, m); c.w(m+4, 1); c.w(m+8, 1)
        place(c, i, positions[i])
    targets = targets if targets is not None else [(i ^ 1) if mode != 'ffa' else (1 if i == 0 else 0) for i in range(count)]
    for i, t in enumerate(targets): c.w(core.TABLE+4*i, t)
    c.w(part.CONTROL+12, (1 << count)-1); c.w(part.CONTROL+16, 0)
    if mode != 'teams':
        c.write(modes.CONTROL, struct.pack('<4I', modes.MAGIC, MANAGER, count, {'ffa': modes.FFA, 'coop': modes.COOP}[mode]))
    c.write(q.CODE, q.payload(PREVIOUS, button_aware=q.CONFIGURABLE, pad_resolver=resolver, lockoff=True,
                              free_for_all=mode == 'ffa', coop_controls=mode == 'coop'))
    c.write(ls.CONTROL, struct.pack('<3I', 1, MANAGER, button))
    c.w(q.CONTROL+q.FIELDS['timeout'], q.DEFAULT_TIMEOUT)
    c.write(q.CONTROL+q.TIMING_UPDATES, struct.pack('<2I', on_threshold, q.TIMING_TAG))
    for p, b in off.programs(): c.write(p, b)
    c.write(off.CONTROL, struct.pack('<5I', off.MAGIC, MANAGER, off_button, threshold, 0))
    if install:
        for p, b in sel.programs(): c.write(p, b)
        control = bytearray(0x100)
        struct.pack_into('<8I', control, 0, sel.MAGIC, MANAGER, sel.ORDERS[order], stick, sel.STICK_CONFIRM, after_ko,
                         marker, sel.COLOUR)
        struct.pack_into('<I', control, sel.FIELDS['side'], side)
        struct.pack_into('<I', control, sel.FIELDS['style'], style if marker else 0)
        struct.pack_into('<12I', control, sel.FIELDS['keys'], *(sel.INVALID,)*12)
        c.write(sel.CONTROL, bytes(control))
    # Seat cameras: side 0 follows the first human, side 1 the second (or physical 1).
    c.w(follow.SUCCESSOR_CONTROL+8, humans[0] if humans else 0)
    c.w(follow.SUCCESSOR_CONTROL+12, humans[1] if len(humans) > 1 else 1)
    c.w(GP-22172, CAM-1824); c.w(GP-22176, CAM)
    for base in (CAM, CAM+656):
        for i, v in enumerate(view): c.w(base+512+4*i, v)
        c.write(base+320, struct.pack('<16f', *matrix))
    c.w(A_BATTLE, BATTLE); c.w(BATTLE, 3)
    c.events, c.matrix, c.saved_matrix, c.calls, c.packets, c.cursor = [], None, [], [], [], 0x5000000
    def push(m): m.events.append('push'); m.saved_matrix.append(m.matrix)
    def pop(m): m.events.append('pop'); m.matrix = m.saved_matrix.pop()
    def load(m): m.matrix = struct.unpack('<16f', m.read(m.r[4], 64))
    def projection(m):
        value = project(m.matrix, struct.unpack('<4f', m.read(m.r[5], 16)))
        m.r[2] = int(value is not None); m.write(m.r[4], struct.pack('<4i', *(value or (0, 0, -1, -1))))
    def subtract(m):
        left = struct.unpack('<4f', m.read(m.r[5], 16)); right = struct.unpack('<4f', m.read(m.r[6], 16))
        m.write(m.r[4], struct.pack('<4f', *(x-y for x, y in zip(left, right))))
    def pad(m): m.r[2] = RECORDS+m.u(m.r[4]+4)*448
    def begin(m): m.r[2] = m.cursor+16
    def end(m):
        m.events.append('sprite'); m.packets.append(m.read(m.cursor+16, m.r[4]-m.cursor-16)); m.cursor = m.r[4]
    c.callbacks = {0x120AB0: push, 0x120AC8: pop, 0x120B80: load, 0x1210D8: projection, 0x121ED8: subtract,
                   0x1DC2A0: pad, 0x100878: begin, 0x100890: end,
                   0x1DAA50: lambda m: m.calls.append(('clear', m.r[4], m.r[5])),
                   0x1DA9D0: lambda m: m.calls.append(('set', m.r[4], m.r[5])),
                   0x1E0290: lambda m: m.calls.append(('action', m.r[4], m.r[5])),
                   display.BAR_DRAW: lambda m: m.events.append('bars')}
    return c


A_BATTLE = 0x2FEB38


def place(c, i, position, w=1.0):
    x, y, z = position
    c.write(MODELS[i]+2416, struct.pack('<4f', x, y, z, w))


def frame(c):
    c.r[29] = 0x1FFFF00; c.r[31] = 0xFEED0000
    saved = list(c.r[16:24]); fpu = list(c.f[20:32])
    stop = c.run(q.CODE, stops=(PREVIOUS,))
    assert stop == PREVIOUS and c.r[29] == 0x1FFFF00 and c.r[16:24] == saved and c.f[20:32] == fpu
    assert not c.saved_matrix
    return c.u(core.TABLE)


def press(c, raw, n=1, seat=0):
    """The native poller publishes the physical word into the pad record before every update."""
    for _ in range(n): c.w(RECORDS+448*seat+328, raw); frame(c)


def target(c, seat=0): return c.u(core.TABLE+4*seat)
def row(c, seat=0): return off.ROWS+seat*off.STRIDE
def own(c, seat=0): return sel.ROWS+seat*sel.STRIDE
def counter(c, name): return c.u(sel.CONTROL+sel.FIELDS[name])


def tap(c, seat=0, button=L3):
    press(c, button, seat=seat); press(c, 0, seat=seat)
    return target(c, seat)


def flick(c, direction, seat=0, button=L3, hold=1, neutral=True):
    """Hold the switch button, flick, return the stick to neutral and release."""
    press(c, button, seat=seat); press(c, button | direction, hold, seat=seat)
    if neutral: press(c, button, seat=seat)
    press(c, 0, seat=seat)
    return target(c, seat)


def polar(deg, dist, centre=(256, 224, 0)):
    return (centre[0]+dist*math.cos(math.radians(deg)), centre[1], centre[2]+dist*math.sin(math.radians(deg)))


# ------------------------------------------------------------------------ pure models (T-13)
def pseudo_angle(dx, dz):
    """Mirror of the guest's circle key: 4 + quadrant + fraction in [4, 8), float bits 22..1."""
    f32 = lambda v: struct.unpack('<f', struct.pack('<f', v))[0]
    dx, dz = f32(dx), f32(dz)
    length = f32(abs(dx)+abs(dz))
    if length < 1: return 0
    if dz >= 0 and not math.copysign(1, dz) < 0:
        numerator, quadrant = (dz, 4.0) if dx >= 0 and not math.copysign(1, dx) < 0 else (abs(dx), 5.0)
    else:
        numerator, quadrant = (abs(dz), 6.0) if dx < 0 or math.copysign(1, dx) < 0 else (dx, 7.0)
    bits = struct.unpack('<I', struct.pack('<f', f32(f32(numerator/length)+quadrant)))[0]
    return ((bits << 9) & 0xFFFFFFFF) >> 10


def circle_next(viewer, enemies, cur, side, step=1):
    keys = {j: (pseudo_angle((-1 if side else 1)*(x-viewer[0]), z-viewer[2]) << 4) | j
            for j, (x, _, z) in enemies.items()}
    ck = keys[cur]
    others = [k for j, k in keys.items() if j != cur]
    if step > 0:
        bigger = [k for k in others if k > ck]
        return (min(bigger) if bigger else min(others)) & 15
    smaller = [k for k in others if k < ck]
    return (max(smaller) if smaller else max(others)) & 15


def camera_side(viewer, target, hand, back):
    """Side flag from a perspective camera `back` units behind the viewer facing the target (hand mirrors x)."""
    vx, _, vz = viewer; tx, _, tz = target
    dx, dz = tx-vx, tz-vz; d = math.hypot(dx, dz) or 1
    fx, fz = dx/d, dz/d; cx, cz = vx-back*fx, vz-back*fz
    def screen(x, z):
        rx, rz = x-cx, z-cz; depth = rx*fx+rz*fz
        return hand*(rx*(-fz)+rz*fx)/depth if depth > 0 else None
    t, p = screen(tx, tz), screen(vx-dz, vz+dx)
    return None if t is None or p is None or t == p else int(p < t)


class SettingsTests(unittest.TestCase):
    """T-15: defaults, validation, the legacy truth table, texts, pages and hints."""
    def test_defaults_legacy_values_and_validation(self):
        defaults = mod_settings.validate_settings({})
        self.assertEqual([defaults[k] for k in sel.KEYS],
                         ['left_to_right', True, 'nearest_to_centre', True, 'with_switch_button', 'arrow'])
        for key, bad in (('lockon_cycle_order', 'nearest'), ('lockon_right_stick', 1), ('lockon_after_ko', True),
                         ('lockon_target_marker', 'on'), (sel.STICK_MODE_KEY, 'off'), (sel.STICK_MODE_KEY, True),
                         (sel.STICK_MODE_KEY, None), ('lockon_right_stick', 'with_switch_button')):
            with self.assertRaises(ValueError): mod_settings.validate_settings({key: bad})
        self.assertEqual(sel.LEGACY, {k: v for k, v in LEGACY.items() if k not in threat.KEYS})
        self.assertEqual(threat.LEGACY, {k: LEGACY[k] for k in threat.KEYS})
        self.assertNotIn(sel.STICK_MODE_KEY, sel.LEGACY, 'the mode only matters while the bool is on')
        self.assertEqual((sel.STICK_MODES, sel.STICK_CONFIRM), ({'with_switch_button': 1, 'right_stick_alone': 2}, 0))

    def test_wanted_exactly_when_an_effective_setting_is_not_legacy(self):
        self.assertFalse(sel.wanted(settings(**LEGACY)))
        for key, value in (('lockon_cycle_order', 'left_to_right'), ('lockon_cycle_order', 'nearest_first'),
                           ('lockon_right_stick', True), ('lockon_after_ko', 'nearest_to_centre'),
                           ('lockon_target_marker', True)):
            self.assertTrue(sel.wanted(settings(**dict(LEGACY, **{key: value}))), key)
        # R3 is the right stick's own click: aiming with it held is off, so it alone installs nothing.
        r3 = dict(LEGACY, lockon_right_stick=True, lockon_switch_button='r3')
        self.assertFalse(sel.wanted(settings(**r3)))
        self.assertEqual(sel.effective(settings(lockon_switch_button='r3'))['stick'], 0)
        self.assertEqual(sel.effective(settings())['stick'], 1)
        # The right stick alone works with R3 (stick 2); with the bool off the mode changes nothing.
        alone = dict(r3, lockon_right_stick_mode='right_stick_alone')
        self.assertTrue(sel.wanted(settings(**alone)))
        self.assertEqual(sel.effective(settings(**alone))['stick'], 2)
        self.assertEqual(sel.effective(settings(lockon_right_stick_mode='right_stick_alone'))['stick'], 2)
        unused = dict(LEGACY, lockon_right_stick_mode='right_stick_alone')
        self.assertFalse(sel.wanted(settings(**unused)))
        self.assertEqual(sel.effective(settings(**unused))['stick'], 0)

    def test_save_load_round_trip_and_a_beta34_file_gets_the_default_mode(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'mod-settings.json'
            for values in (dict(LEGACY, lockon_right_stick_mode='with_switch_button'),
                           dict(lockon_cycle_order='nearest_first', lockon_right_stick=True, lockon_after_ko='nearest_to_centre',
                                lockon_target_marker=True, lockon_right_stick_mode='right_stick_alone')):
                mod_settings.save_settings(values, path)
                loaded = mod_settings.load_settings(path)
                self.assertEqual({k: loaded[k] for k in values}, values)
                self.assertIs(json.loads(path.read_text(encoding='utf-8'))['lockon_right_stick'], values['lockon_right_stick'])
            # A beta.34 file (the bool, no mode key) keeps its bool and gets the default mode.
            path.write_text(json.dumps(dict(lockon_right_stick=True, lockon_switch_button='l3')), encoding='utf-8')
            loaded = mod_settings.load_settings(path)
            self.assertEqual((loaded['lockon_right_stick'], loaded[sel.STICK_MODE_KEY]), (True, 'with_switch_button'))

    def test_pages_rows_and_texts(self):
        groups = dict(mod_settings.GROUPS)
        self.assertEqual(groups['Controls'][-5:], ('lockon_right_stick', sel.STICK_MODE_KEY, 'lockon_cycle_order',
                                                   'lockon_attacker_switch', 'lockon_after_ko'))
        self.assertEqual(len(groups['Controls']), 10)
        import ingame_settings
        self.assertLess(groups['Controls'].index(sel.STICK_MODE_KEY), ingame_settings.ROWS, 'the pair shares a sub-page')
        self.assertEqual(groups['HUD'][-5:-1], ('lockon_target_marker', sel.STYLE_KEY, 'lockon_target_look', 'lockon_threat_marks'))
        self.assertEqual(len(groups['HUD']), 11)   # Version 12: the target marker look follows the indicator; then the tag attack meter
        import localization
        fields = mod_settings.ui_fields()
        rows = ('lockon_right_stick', sel.STICK_MODE_KEY, 'lockon_target_marker')
        self.assertEqual([fields[k][5] for k in rows],
                         ['Right stick picks a target', 'Picking with the right stick', 'Mark your target'])
        self.assertEqual([localization.tr(fields[k][5], {'language': 'es'}) for k in rows],
                         ['El stick derecho elige objetivo', 'Elegir con el stick derecho', 'Marcar tu objetivo'])
        self.assertEqual([localization.value_label(v, {'language': language}) for language in ('en', 'es')
                          for v in fields[sel.STICK_MODE_KEY][2]],
                         ['Hold switch button', 'Stick alone (in combat)', 'Con el botón de cambio', 'Solo el stick (en combate)'])
        for key in sel.KEYS:
            label = fields[key][5]
            self.assertIn(label, localization.ES, key)
            if fields[key][1] == 'choice':
                en = [localization.value_label(v, {'language': 'en'}) for v in fields[key][2]]
                es = [localization.value_label(v, {'language': 'es'}) for v in fields[key][2]]
                self.assertEqual(len(set(en)), len(en)); self.assertEqual(len(set(es)), len(es))
                self.assertNotEqual(en, es)
        for group in ('Controls', 'HUD'):
            self.assertIn(mod_settings.notes[group], localization.ES)
        # Live: three- and four-view matches (and two-player matches with a team assignment, which use those views)
        # draw no overhead bars, so no ring; the help says so, and names the ring as a switch of its own.
        hud_en, hud_es = mod_settings.notes['HUD'], localization.tr(mod_settings.notes['HUD'], {'language': 'es'})
        # beta.37: the attacker marks are a switch of their own; they are drawn in those views too.
        # beta.39: the indicator (arrow, ring or both) is drawn in every view.
        self.assertIn('target indicator, attacker arrows and tag attack meter are separate switches', hud_en)
        self.assertIn('a gold arrow, a ring sized to your target, or both, in every view', hud_en)
        self.assertIn('indicador del objetivo, flechas de atacantes y medidor de ataque tag se activan por separado', hud_es)
        self.assertIn('una flecha dorada, un anillo a la medida del objetivo o ambos, en cada vista', hud_es)
        self.assertEqual([localization.value_label(v, {'language': language}) for language in ('en', 'es')
                          for v in mod_settings.ui_fields()[sel.STYLE_KEY][2]],
                         ['Gold arrow', 'Ring', 'Arrow and ring', 'Flecha dorada', 'Anillo', 'Flecha y anillo'])
        controls_en = mod_settings.notes['Controls']
        controls_es = localization.tr(controls_en, {'language': 'es'})
        self.assertIn('during an attack warning, your attacker', controls_en)
        self.assertIn('locked on in combat; no camera then', controls_en)
        self.assertIn('fijado en combate; sin cámara', controls_es)
        self.assertIn('con aviso de ataque, tu atacante', controls_es)
        self.assertIn('Mod settings.cmd', controls_es)
        for text in (controls_en, controls_es, hud_en, hud_es):
            self.assertTrue('next match' in text or 'próximo combate' in text, text)
        self.assertEqual((len(controls_en), len(controls_es), len(hud_en), len(hud_es)), (411, 416, 515, 542))

    def test_stick_rows_dim_with_r3_and_the_bool_and_lock_off_rows_still_dim(self):
        import ingame_settings as s
        self.assertEqual(s.DEPENDS[sel.STICK_MODE_KEY], ('lockon_right_stick', True))
        c = s.Controller(); c.values = settings()
        self.assertFalse(c.dimmed('lockon_right_stick')); self.assertFalse(c.dimmed(sel.STICK_MODE_KEY))
        c.values['lockon_switch_button'] = 'r3'; self.assertTrue(c.dimmed('lockon_right_stick'), 'R3 cannot be held to aim')
        self.assertFalse(c.dimmed(sel.STICK_MODE_KEY), 'the mode row stays live: the stick alone works with R3')
        c.values[sel.STICK_MODE_KEY] = 'right_stick_alone'; self.assertFalse(c.dimmed('lockon_right_stick'))
        c.values['lockon_switch_button'] = 'l3'; self.assertFalse(c.dimmed('lockon_right_stick'))
        c.values['lockon_right_stick'] = False; self.assertTrue(c.dimmed(sel.STICK_MODE_KEY), 'the mode needs the bool')
        self.assertFalse(c.dimmed('lockon_right_stick'))
        c.values['lockon_right_stick'] = True; self.assertFalse(c.dimmed(sel.STICK_MODE_KEY))
        c.values['lockoff_enabled'] = False; self.assertTrue(c.dimmed('lockoff_hold_seconds'))
        self.assertFalse(c.dimmed('lockon_cycle_order'))

    def test_the_arrow_switch_is_independent_of_both_overhead_bar_switches(self):
        import ingame_settings as s
        self.assertNotIn('lockon_target_marker', s.DEPENDS); self.assertNotIn('lockon_target_marker', s.DIMMED_BY)
        self.assertEqual([k for k, (master, _) in s.DEPENDS.items() if master == 'lockon_target_marker'],
                         [sel.STYLE_KEY, 'lockon_target_look'])
        c = s.Controller()
        for friend in (True, False):
            for enemy in (True, False):
                for marker in (True, False):
                    values = settings(**{mod_settings.FRIEND_BARS_KEY: friend, mod_settings.ENEMY_BARS_KEY: enemy,
                                         'lockon_target_marker': marker})
                    c.values = values
                    self.assertFalse(c.dimmed('lockon_target_marker'), (friend, enemy, marker))
                    self.assertFalse(c.dimmed(mod_settings.FRIEND_BARS_KEY)); self.assertFalse(c.dimmed(mod_settings.ENEMY_BARS_KEY))
                    self.assertEqual(sel.effective(values)['marker'], int(marker), (friend, enemy))
                    self.assertEqual((values[mod_settings.FRIEND_BARS_KEY], values[mod_settings.ENEMY_BARS_KEY]),
                                     (friend, enemy), 'the arrow never changes a bar switch')

    def test_play_window_hints_follow_the_raw_bool_the_mode_and_the_button(self):
        import tempfile
        import localization
        import play_launcher
        hold = 'Hold {button} and flick the right stick to pick a target; left/right steps around you.'
        alone = 'Flick the right stick to pick a target while locked on; left/right steps around you.'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'mod-settings.json'
            cases = ((dict(lockon_switch_button='l3'), hold), (dict(lockon_switch_button='l3', lockon_right_stick=False), None),
                     (dict(lockon_switch_button='r3'), None), ({'language': 'es', 'lockon_switch_button': 'l3'}, hold),
                     (dict(lockon_switch_button='l3', lockon_right_stick_mode='right_stick_alone'), alone),
                     (dict(lockon_switch_button='r3', lockon_right_stick_mode='right_stick_alone'), alone),
                     ({'language': 'es', 'lockon_switch_button': 'l3', 'lockon_right_stick_mode': 'right_stick_alone'}, alone),
                     ({'language': 'es', 'lockon_switch_button': 'r3', 'lockon_right_stick_mode': 'right_stick_alone'}, alone),
                     (dict(lockon_switch_button='l3', lockon_right_stick_mode='with_switch_button'), hold),
                     (dict(lockon_switch_button='l3', lockon_right_stick=False, lockon_right_stick_mode='right_stick_alone'), None),
                     (dict(lockon_switch_button='l3', lockon_right_stick='yes', lockon_right_stick_mode='right_stick_alone'), None))
            for values, shown in cases:
                path.write_text(json.dumps(values), encoding='utf-8')
                lines = play_launcher.hint_lines(folder, 'C:/logs', windows=True)
                found = [l for l in lines if 'right stick' in l or 'stick derecho' in l]
                if shown is None:
                    self.assertEqual(found, [], values); continue
                language = values.get('language', 'en')
                self.assertEqual(found, [localization.tr(shown, language, button='L3')], values)


class ProgramTests(unittest.TestCase):
    """T-2/T-16/A15: layout, hooks, validators and refusals."""
    def test_reservation_is_owned_and_no_other_constant_overlaps_it(self):
        for p, b in sel.programs()[:-2]:
            self.assertTrue(sel.BASE <= p and p+len(b) <= sel.END, hex(p))
        self.assertEqual(sel.MARKS, sel.ROWS+sel.STRIDE*modes.ENGINE_ACTORS)
        self.assertLessEqual(sel.MARKS+8*modes.ENGINE_ACTORS, sel.END)
        pattern = re.compile(r'0x0*695[0-7][0-9A-Fa-f]{3}\b')
        trees = [Path(__file__).resolve().parent]
        sibling = mod_settings.ROOT.parent/('bt4-multifighter' if mod_settings.ADAPTER == 'BT3' else 'bt3-multifighter')/'tools'
        if sibling.is_dir(): trees.append(sibling)
        for tree in trees:
            for source in tree.glob('*.py'):
                if source.name in ('lockon_select.py', 'test_lockon_select.py'): continue
                self.assertIsNone(pattern.search(source.read_text(encoding='utf-8', errors='replace')), source)

    def test_entries_jump_to_the_wrappers_and_tails_resume_the_unchanged_bodies(self):
        first = sel.originals()
        self.assertEqual(first[off.INPUT], struct.pack('<2I', 0x27BDFF80, 0xFFB00000))
        self.assertEqual(first[off.APPLY], first[off.INPUT])
        parts = dict(sel.programs())
        self.assertEqual(parts[off.INPUT], struct.pack('<2I', (2 << 26) | (sel.INPUT2 >> 2), 0))
        self.assertEqual(parts[sel.TAIL_INPUT], first[off.INPUT]+struct.pack('<2I', (2 << 26) | ((off.INPUT+8) >> 2), 0))
        self.assertEqual(parts[sel.TAIL_APPLY], first[off.APPLY]+struct.pack('<2I', (2 << 26) | ((off.APPLY+8) >> 2), 0))

    def test_ring_data_rows_and_marks_do_not_overlap_and_the_programs_fit(self):
        self.assertEqual((sel.RING_HEADER, sel.MARKS), (0x06956100, 0x06957400))
        self.assertEqual((sel.SEG, sel.STRIP, sel.TRI), (0x06955800, 0x06955900, 0x06955A00))
        rows = (sel.ROWS, sel.ROWS+sel.STRIDE*modes.ENGINE_ACTORS+8*modes.ENGINE_ACTORS)
        spans = sorted([(p, p+len(b)) for p, b in sel.code_parts()]+[(sel.CONTROL, sel.CONTROL+0x100), rows])
        self.assertTrue(all(end <= start for (_, end), (start, _) in zip(spans, spans[1:])), [(hex(a), hex(b)) for a, b in spans])
        self.assertLessEqual(spans[-1][1], sel.END)
        parts = dict(sel.code_parts())
        self.assertLessEqual(len(parts[sel.INPUT2]), 0x1000); self.assertLessEqual(len(parts[sel.MARKER]), sel.SEG-sel.MARKER)
        self.assertEqual(len(parts[sel.RING_HEADER]), 0x1B0)
        self.assertLessEqual(sel.TAIL_APPLY+16, sel.RING_HEADER)

    def synthetic(self, installed=True, marker=1):
        ram = bytearray(0x8000000)
        struct.pack_into('<I', ram, core.ACTORS, MANAGER)
        struct.pack_into('<2I', ram, off.CONTROL, off.MAGIC, MANAGER)
        for p, b in off.programs(): ram[p:p+len(b)] = b
        site, before, after = sel.marker_site(); ram[site:site+4] = before
        if installed:
            for p, b in sel.programs(): ram[p:p+len(b)] = b
            struct.pack_into('<2I', ram, sel.CONTROL, sel.MAGIC, MANAGER)
            struct.pack_into('<I', ram, sel.CONTROL+sel.FIELDS['marker'], marker)
            struct.pack_into('<I', ram, sel.CONTROL+sel.FIELDS['style'], marker)
            if marker: ram[site:site+4] = after
        return ram

    def test_lock_off_validator_accepts_the_hooks_only_with_a_valid_module(self):
        off.validate_memory(self.synthetic(installed=False))
        ram = self.synthetic(); off.validate_memory(ram); sel.validate_memory(ram)
        broken = bytearray(ram); broken[sel.ORDER+12] ^= 1
        with self.assertRaisesRegex(ValueError, 'Target selection executable changed'): off.validate_memory(broken)
        foreign = bytearray(ram); struct.pack_into('<I', foreign, sel.CONTROL+4, MANAGER+4)
        with self.assertRaisesRegex(ValueError, 'Lock-off executable changed'): off.validate_memory(foreign)
        stripped = bytearray(ram); stripped[off.INPUT:off.INPUT+8] = sel.originals()[off.INPUT]
        with self.assertRaisesRegex(ValueError, 'Target selection executable changed'): off.validate_memory(stripped)
        tail = bytearray(ram); tail[sel.TAIL_APPLY] ^= 1
        with self.assertRaises(ValueError): off.validate_memory(tail)
        body = bytearray(ram); body[off.INPUT+12] ^= 1
        with self.assertRaisesRegex(ValueError, 'Lock-off executable changed'): off.validate_memory(body)

    def test_validator_rejects_a_changed_ring_byte(self):
        ram = self.synthetic(); sel.validate_memory(ram)
        for address in (sel.RING_HEADER, sel.RING_TABLE+20, sel.RING_SCALE+4, sel.MARK_FILL+8, sel.SEG+4, sel.TRI+40):
            broken = bytearray(ram); broken[address] ^= 1
            with self.assertRaisesRegex(ValueError, 'Target selection executable changed'): sel.validate_memory(broken)
            with self.assertRaisesRegex(ValueError, 'Target selection executable changed'): off.validate_memory(broken)

    def test_marker_call_is_recognised_by_the_display_installer_rule(self):
        ram = self.synthetic()
        site, before, after = sel.marker_site()
        self.assertEqual(sel.dependency_override(ram, site, before), after)
        self.assertEqual(sel.dependency_override(self.synthetic(marker=0), site, before), before)
        self.assertEqual(sel.dependency_override(self.synthetic(installed=False), site, before), before)
        moved = bytearray(ram); moved[site:site+4] = before
        with self.assertRaisesRegex(ValueError, 'marker'): sel.validate_memory(moved)

    def test_all_legacy_settings_install_nothing_and_lock_off_bytes_are_unchanged(self):
        ram = self.synthetic(installed=False)
        self.assertEqual(sel.build_memory(ram, settings=settings(**LEGACY)), dict(blocks=[]))
        self.assertEqual(sel.build_memory(ram, settings=settings(**dict(LEGACY, lockon_right_stick=True,
                                                                           lockon_switch_button='r3'))), dict(blocks=[]))
        # Lock-off disabled with all-legacy keys stays uninstalled; with any new behaviour it installs.
        disabled = dict(LEGACY, lockoff_enabled=False)
        self.assertEqual(off.build_memory(bytearray(16), settings=settings(**disabled)), dict(blocks=[]))
        with self.assertRaisesRegex(ValueError, 'full captured memory'):
            off.build_memory(bytearray(16), settings=settings(lockoff_enabled=False))

    @unittest.skipUnless(FIXTURE_FFA.is_file(), 'Sept 24 prepared image absent from this copy')
    def test_real_image_build_refusals_and_all_legacy_identity(self):
        from camera_snapshot import read_ram
        ram = bytearray(read_ram(FIXTURE_FFA))
        before = bytes(ram[off.BASE:off.END])
        self.assertEqual(sel.build_memory(ram, settings=settings(**LEGACY))['blocks'], [])
        manifest = sel.build_memory(ram, settings=settings())
        import quad_viewports as views
        quad = int(any(block['address'] == views.DRAW for block in manifest['blocks']))
        self.assertEqual(len(manifest['blocks']), len(sel.programs())+3+quad,
                         'code, hooks, CONTROL, ROWS, the marker call and (quad views) their extension list')
        blocks = {block['address']: bytes.fromhex(block['data_hex']) for block in manifest['blocks']}
        self.assertEqual(struct.unpack_from('<2I', blocks[sel.CONTROL], sel.FIELDS['style']), (sel.STYLES['arrow'], quad))
        self.assertEqual(struct.unpack_from('<2I', blocks[sel.CONTROL], 12), (1, sel.STICK_CONFIRM))
        self.assertEqual(len(blocks[sel.ROWS]), sel.STRIDE*modes.ENGINE_ACTORS+8*modes.ENGINE_ACTORS)
        self.assertEqual(manifest['settings'][sel.STICK_MODE_KEY], 'with_switch_button')
        alone = sel.build_memory(ram, settings=settings(lockon_right_stick_mode='right_stick_alone', lockon_switch_button='r3'))
        self.assertEqual(struct.unpack_from('<I', bytes.fromhex(next(b['data_hex'] for b in alone['blocks']
                                                                     if b['address'] == sel.CONTROL)), 12)[0], 2)
        self.assertTrue(any(line.startswith('Right stick alone') for line in alone['limitations']), alone['limitations'])
        held_r3 = sel.build_memory(ram, settings=settings(lockon_switch_button='r3'))
        self.assertTrue(any('works with R3' in line for line in held_r3['limitations']), held_r3['limitations'])
        for block in manifest['blocks']:
            p, data = block['address'], bytes.fromhex(block['data_hex'])
            self.assertEqual(ram[p:p+len(data)].hex(), block['expected_hex'])
        occupied = bytearray(ram); occupied[sel.END-4] = 1
        with self.assertRaisesRegex(ValueError, 'reservation occupied'): sel.build_memory(occupied, settings=settings())
        hooked = bytearray(ram); hooked[off.APPLY:off.APPLY+8] = struct.pack('<2I', 0x08000000, 0)
        with self.assertRaises(ValueError): sel.build_memory(hooked, settings=settings())
        self.assertEqual(bytes(ram[off.BASE:off.END]), before)


FIXTURE_REMATCH = ROOT/'analysis/prepared-states'/REMATCH_IMAGE


class RematchTests(unittest.TestCase):
    """T-12: Fight Again's validators accept the composed module (and name it when it is missing)."""
    def composed(self, path):
        from camera_snapshot import read_ram
        ram = bytearray(read_ram(path))
        for block in sel.build_memory(ram, settings=settings())['blocks']:
            data = bytes.fromhex(block['data_hex']); ram[block['address']:block['address']+len(data)] = data
        return ram

    @unittest.skipUnless(FIXTURE_FFA.is_file(), 'Sept 24 prepared image absent from this copy')
    def test_battle_mode_validation_accepts_the_hooked_entries(self):
        import battle_modes
        ram = self.composed(FIXTURE_FFA)
        self.assertEqual(battle_modes.validate_memory(ram), IMAGE_MODE)
        off.validate_memory(ram); sel.validate_memory(ram)
        checks = [off.validate_memory]+([battle_modes.validate_memory] if IMAGE_MODE else [])
        with patch.object(sel, 'dependency_override', lambda ram, address, expected: expected):
            for check in checks:
                with self.assertRaisesRegex(ValueError, 'Lock-off executable changed'): check(ram)
        broken = bytearray(ram); broken[sel.AIM+8] ^= 1
        for check in checks:
            with self.assertRaisesRegex(ValueError, 'Target selection executable changed'): check(broken)

    @unittest.skipUnless(FIXTURE_REMATCH.is_file(), 'Sept 24 rematch image absent from this copy')
    def test_fight_again_plan_accepts_a_staged_image_with_the_module(self):
        import prepared_rematch
        ram = self.composed(FIXTURE_REMATCH)
        self.assertIsNotNone(prepared_rematch.plan(ram))
        if IMAGE_MODE:
            with patch.object(sel, 'dependency_override', lambda ram, address, expected: expected):
                with self.assertRaisesRegex(ValueError, 'Lock-off executable changed'): prepared_rematch.plan(ram)


CENTRE = (256, 224, 0)


def ring(*bearings, count=6, viewer=0, distance=60):
    """Positions: viewer at the centre, then (slot, bearing) pairs on a circle; others parked apart."""
    places = [(40+40*i, 224, 300) for i in range(count)]
    places[viewer] = CENTRE
    for slot, bearing in bearings: places[slot] = polar(bearing, distance, CENTRE)
    return places


def follow_camera(c, seat=0, hand=1, back=12.0, focal=150.0, looking_at=None):
    """The lock-on camera: behind the seat's fighter on the line to its current target (or, while it is still
    swinging, to looking_at), facing it. Screen x = hand x the lateral offset (-1 mirrors the handedness)."""
    def position(i): return struct.unpack('<3f', c.read(MODELS[i]+2416, 12))
    def projection(m):
        px, py, pz, _ = struct.unpack('<4f', m.read(m.r[5], 16))
        vx, vy, vz = position(seat)
        tx, _, tz = position(m.u(core.TABLE+4*seat) if looking_at is None else looking_at)
        d = math.hypot(tx-vx, tz-vz) or 1; fx, fz = (tx-vx)/d, (tz-vz)/d
        rx, rz = px-(vx-back*fx), pz-(vz-back*fz); depth = rx*fx+rz*fz
        if depth <= 0.5:
            m.r[2] = 0; m.write(m.r[4], struct.pack('<4i', 0, 0, -1, -1)); return
        x = 256+focal*hand*(rx*(-fz)+rz*fx)/depth; y = 224+focal*(py-vy)/depth
        m.r[2] = 1; m.write(m.r[4], struct.pack('<4i', int((x+1792)*16), int((y+1824)*16), 1, max(1, int(depth))))
    c.callbacks[0x1210D8] = projection
    return c


def hand_side(hand):
    """The build constant that makes "next" the enemy to the right for a world of this handedness."""
    return int(hand < 0)


def expected_walk(places, count, hand, first=1, taps=None, ffa=False):
    enemies = {j: places[j] for j in range(count) if j != 0 and (ffa or j & 1)}
    cur, walk = first, []
    for _ in range(taps or len(enemies)):
        cur = circle_next(places[0], enemies, cur, hand_side(hand)); walk.append(cur)
    return walk


class OrderTests(unittest.TestCase):
    """T-3/T-4/T-13 (A1, A12): circle, nearest-first and slot orders; candidates are PICK's."""
    def test_circle_taps_go_right_around_you_and_wrap_for_both_handednesses(self):
        places = ring((1, 90), (3, 30), (5, 150))
        for hand in (1, -1):
            c = follow_camera(make(positions=places, side=hand_side(hand)), hand=hand)
            self.assertEqual(target(c), 1)
            screen = {j: camera_screen(CENTRE, places[1], places[j], hand, 12.0) for j in (3, 5)}
            first = tap(c)
            self.assertEqual(first, max(screen, key=screen.get), 'from straight ahead, next is the one on the right')
            self.assertEqual([first, tap(c), tap(c)], expected_walk(places, 6, hand), hand)
            self.assertEqual(target(c), 1, 'wraps')
            self.assertEqual(counter(c, 'steps'), 3); self.assertEqual(c.u(q.CONTROL+q.FIELDS['switches']), 3)
            keys = [c.u(sel.CONTROL+sel.FIELDS['keys']+4*i) for i in range(6)]
            self.assertEqual([k != sel.INVALID for k in keys], [False, True, False, True, False, True], 'allies/self excluded')

    def test_the_build_constant_decides_the_direction_with_or_without_a_camera(self):
        places = ring((1, 90), (3, 30), (5, 150))
        self.assertEqual(sel.SIDE, 1, 'the settled lock-on camera reading of the live game')
        for flag, walk in ((0, [5, 3, 1]), (1, [3, 5, 1])):
            for camera in (True, False):
                c = make(positions=places, side=flag)
                if not camera: c.w(GP-22172, 0)
                self.assertEqual([tap(c) for _ in range(3)], walk, (flag, camera))

    def test_a_camera_still_swinging_from_the_previous_target_never_traps_the_cycle(self):
        # Live, quick taps arrived while the camera still faced the previous target; a per-request reading of
        # the camera then flipped the direction and trapped the cycle between two enemies (1 and 5).
        places = ring((1, 90), (3, 30), (5, 150), count=8); places[7] = polar(250, 70, CENTRE)
        for hand in (1, -1):
            for lag in (1, 5, 7):
                c = follow_camera(make(count=8, mode='ffa', positions=places, side=hand_side(hand), targets=[1]+[0]*7),
                                  hand=hand, looking_at=lag)
                walk = [tap(c) for _ in range(7)]
                self.assertEqual(sorted(walk), list(range(1, 8)), (hand, lag, walk))

    def test_behind_you_and_off_screen_enemies_stay_in_the_circle(self):
        places = ring((1, 90), (3, 270)); places[5] = polar(0, 600, CENTRE)
        for hand in (1, -1):
            c = follow_camera(make(positions=places, side=hand_side(hand)), hand=hand)
            walk = [tap(c) for _ in range(3)]
            self.assertEqual(walk, expected_walk(places, 6, hand)); self.assertEqual(set(walk), {1, 3, 5})

    def test_dead_absent_consumed_and_invalid_fighters_are_never_chosen_ffa_admits_any_slot(self):
        c = make(count=8, mode='ffa', positions=ring(*((i, 15+30*i) for i in range(1, 8)), count=8),
                 targets=[1]+[0]*7)
        c.w(GP-22172, 0)
        c.w(ACTORS[2]+0x9E4, 0)                                    # defeated
        c.w(part.CONTROL+12, 0xFF & ~(1 << 3))                     # absent
        c.w(part.CONTROL+16, 1 << 4)                               # fusion-consumed
        c.w(ACTORS[5]+0x994, 7)                                    # invalid form row
        self.assertEqual([tap(c) for _ in range(3)], [6, 7, 1], 'even slots are enemies in FFA')
        self.assertEqual([c.u(sel.CONTROL+sel.FIELDS['keys']+4*i) != sel.INVALID for i in range(8)],
                         [False, True, False, False, False, False, True, True])

    def test_nearest_first_uses_straight_line_distance_and_wraps_to_the_nearest(self):
        # 3 is nearer than 5 in a straight line (17.3) but farther by |dx|+|dy|+|dz| (30 against 18).
        places = ring((1, 90)); places[1] = (256, 224, 30)
        places[3] = (256+10, 224-10, 10); places[5] = (256, 224, -18)
        c = make(positions=places, order='nearest_first', targets=[1, 0, 0, 0, 0, 0])
        self.assertEqual(tap(c), 3, 'past the farthest (1), wrap to the nearest')
        self.assertEqual(tap(c), 5); self.assertEqual(tap(c), 1)

    def test_selection_order_skips_a_consumed_slot_that_the_beta33_search_takes(self):
        c = make(install=False); c.w(part.CONTROL+16, 1 << 3)
        self.assertEqual(tap(c), 3, 'beta.33 inline search (pointer and health only) takes the consumed slot')
        c = make(order='selection_order', stick=0, after_ko=0, marker=0); c.w(part.CONTROL+16, 1 << 3)
        self.assertEqual(tap(c), 5); self.assertEqual(tap(c), 1)

    def test_only_the_current_target_left_consumes_without_a_change(self):
        c = make(count=4); c.w(ACTORS[3]+0x9E4, 0)
        self.assertEqual(tap(c), 1); self.assertEqual(counter(c, 'unchanged'), 1); self.assertEqual(counter(c, 'steps'), 0)

    def test_guest_keys_match_the_model_on_random_layouts(self):
        rng = random.Random(1)
        for layout in range(20):
            count = rng.choice((4, 6, 8, 10))
            places = [(rng.uniform(-300, 300), rng.uniform(-50, 50), rng.uniform(-300, 300)) for _ in range(count)]
            places[0] = (rng.uniform(-2, 2), 0, rng.uniform(-2, 2))
            c = make(count=count, mode='ffa', positions=places, targets=[1]+[0]*(count-1), side=layout & 1)
            c.w(GP-22172, 0)                                       # the build constant decides
            enemies = {j: places[j] for j in range(1, count)}
            expected, cur = [], 1
            for _ in range(count): cur = circle_next(places[0], enemies, cur, layout & 1); expected.append(cur)
            self.assertEqual([tap(c) for _ in range(count)], expected, layout)


def camera_screen(viewer, looked_at, point, hand, back):
    vx, _, vz = viewer; tx, _, tz = looked_at
    dx, dz = tx-vx, tz-vz; d = math.hypot(dx, dz) or 1
    fx, fz = dx/d, dz/d; cx, cz = vx-back*fx, vz-back*fz
    rx, rz = point[0]-cx, point[2]-cz
    return hand*(rx*(-fz)+rz*fx)/(rx*fx+rz*fz)


def screen_rule_traps(table, back):
    """The critique's model of DESIGN 4.1 (re-rank by screen x; behind the camera nearest first)."""
    def step(cur, hand):
        tx, _, tz = table[cur]; d = math.hypot(tx, tz) or 1; fx, fz = tx/d, tz/d; cx, cz = -back*fx, -back*fz
        keys = {}
        for j, (x, _, z) in table.items():
            rx, rz = x-cx, z-cz; depth = rx*fx+rz*fz
            keys[j] = (0, hand*(rx*(-fz)+rz*fx)/depth, j) if depth > 0 else (1, math.hypot(x, z), j)
        bigger = [k for k in keys.values() if k > keys[cur]]
        return (min(bigger) if bigger else min(keys.values()))[2]
    trapped = False
    for hand in (1, -1):
        cur, seen = 0, {0}
        for _ in range(3*len(table)): cur = step(cur, hand); seen.add(cur)
        trapped |= len(seen) < len(table)
    return trapped


class CircleModelTests(unittest.TestCase):
    """T-13 hard gate (A1): the fixed circle never traps, whatever the camera does between taps."""
    def walk(self, table, hand, back, steps):
        cur, seen = 0, {0}
        for _ in range(steps):
            cur = circle_next((0, 0, 0), table, cur, hand_side(hand)); seen.add(cur)
        return seen

    def test_a_settled_lock_on_camera_reads_the_same_side_for_every_target(self):
        rng = random.Random(3)
        for _ in range(2000):
            viewer = (rng.uniform(-50, 50), 0, rng.uniform(-50, 50))
            angle, dist = rng.uniform(0, 2*math.pi), rng.uniform(1, 90)
            target = (viewer[0]+dist*math.cos(angle), rng.uniform(-40, 40), viewer[2]+dist*math.sin(angle))
            for hand in (1, -1):
                self.assertEqual(camera_side(viewer, target, hand, rng.uniform(2, 30)), hand_side(hand))

    def test_the_critiques_counterexamples_trap_the_screen_x_rule_but_not_the_circle(self):
        for enemies, back in (([polar(0, 10, (0, 0, 0)), polar(170, 30, (0, 0, 0)), polar(190, 5, (0, 0, 0))], 3.0),
                              ([polar(-10, 24, (0, 0, 0)), polar(-58, 26, (0, 0, 0)), polar(16, 5, (0, 0, 0))], 10.0)):
            table = dict(enumerate(enemies))
            self.assertTrue(screen_rule_traps(table, back), enemies)
            for hand in (1, -1):
                self.assertEqual(self.walk(table, hand, back, len(table)), {0, 1, 2}, (enemies, hand))

    def test_every_enemy_is_visited_within_count_steps_for_2000_layouts(self):
        rng = random.Random(7)
        for _ in range(2000):
            n = rng.randint(1, 9)
            table = {}
            for j in range(n):
                angle, dist = rng.uniform(0, 2*math.pi), rng.choice((rng.uniform(0.2, 3), rng.uniform(2, 90)))
                table[j] = (dist*math.cos(angle), rng.uniform(-60, 60), dist*math.sin(angle))
            for hand in (1, -1):
                back = rng.uniform(3, 25)
                seen = self.walk(table, hand, back, n) if n > 1 else {0}
                self.assertEqual(len(seen), n, (table, hand, back))

    def test_the_first_tap_goes_to_the_enemy_on_the_right_for_both_handednesses(self):
        for hand in (1, -1):
            table = {0: (0, 0, 50), 1: (20, 0, 50), 2: (-20, 0, 50)}
            screen = {j: camera_screen((0, 0, 0), table[0], table[j], hand, 10.0) for j in (1, 2)}
            self.assertEqual(circle_next((0, 0, 0), table, 0, hand_side(hand)), max(screen, key=screen.get), hand)


def visible(c, seat=0): return c.u(RECORDS+448*seat+328)


def no_synthetic_press(test, physical, visible_words, bits=sel.STICK | R3):
    """T-18: a bit the actor sees may only rise when the physical input rises (a fresh press)."""
    for k in range(1, len(physical)):
        rose = visible_words[k] & ~visible_words[k-1] & bits
        test.assertFalse(rose & physical[k-1], f'synthetic press of {rose:#x} at update {k}: '
                                               f'{[hex(p) for p in physical]} -> {[hex(v) for v in visible_words]}')


def run_script(c, script, seat=0):
    seen = []
    for word in script: press(c, word, seat=seat); seen.append(visible(c, seat))
    return seen


def design_rule(script, button=L3):
    """The DESIGN's mask (clear the stick bits only while the button is held after an aim) as a model."""
    latch, previous, out = 0, 0, []
    for word in script:
        direction = word & sel.STICK
        if word & button and direction and direction != previous: latch = 1
        previous = direction
        out.append(word & ~sel.STICK if latch and word & button and direction else word)
        if not word & button: latch = 0
    return out


SCRIPTS = {
    'release the button with the stick held': [0, L3, L3 | RIGHT, L3 | RIGHT, RIGHT, RIGHT, RIGHT, RIGHT, RIGHT, 0],
    'diagonal sweep': [0, L3, L3 | RIGHT, L3 | UP, L3 | UP, L3, 0],
    'stick held before the button': [RIGHT, RIGHT | L3, RIGHT | L3, L3, 0],
    'R3 clicked mid-flick': [0, L3, L3 | RIGHT, L3 | RIGHT | R3, L3 | RIGHT | R3, L3 | R3, R3, 0],
    'button without the stick': [0, L3, L3, L3 | R3, 0],
    'stick without the button': [0, RIGHT, 0, LEFT, LEFT, 0],
}


class GestureTests(unittest.TestCase):
    """T-6/T-7/T-8/T-10/T-18 with A2-A7."""
    def setUp(self):
        self.places = ring((1, 90), (3, 30), (5, 150))

    def test_stick_left_right_step_around_you_whatever_the_tap_order(self):
        for order in ('left_to_right', 'nearest_first', 'selection_order'):
            for hand in (1, -1):
                c = follow_camera(make(positions=self.places, order=order, side=hand_side(hand)), hand=hand)
                expected = expected_walk(self.places, 6, hand)
                self.assertEqual(flick(c, RIGHT), expected[0], (order, hand))
                self.assertEqual(flick(c, LEFT), 1, 'left steps back')
                self.assertEqual(counter(c, 'steps'), 2); self.assertEqual(c.u(row(c)+off.OFF), 0)

    def test_one_step_per_flick_holding_does_not_repeat_and_a_new_flick_needs_neutral(self):
        c = follow_camera(make(positions=self.places))
        walk = expected_walk(self.places, 6, 1)
        press(c, L3); press(c, L3 | RIGHT, 30)
        self.assertEqual(target(c), walk[0], 'one step while held')
        press(c, L3 | UP, 3); press(c, L3 | RIGHT, 3)
        self.assertEqual(target(c), walk[0], 'no neutral: no new aim')
        press(c, L3); press(c, L3 | RIGHT)
        self.assertEqual(target(c), walk[1])
        press(c, 0); self.assertEqual(target(c), walk[1], 'release after an aim does not switch')
        self.assertEqual(c.u(q.CONTROL+q.FIELDS['switches']), 2)

    def test_release_after_an_aim_neither_switches_nor_locks_off(self):
        for on_threshold, off_button in ((1, L3), (6, L3), (1, 0x100), (6, 0x100)):
            c = follow_camera(make(positions=self.places, on_threshold=on_threshold, off_button=off_button, threshold=15))
            walk = expected_walk(self.places, 6, 1)
            press(c, L3, 8); press(c, L3 | RIGHT); press(c, L3, 30); press(c, 0, 2)
            self.assertEqual(target(c), walk[0], (on_threshold, off_button))
            self.assertEqual((c.u(row(c)+off.OFF), c.u(row(c)+off.FIRED)), (0, 0))
            self.assertEqual(c.u(q.CONTROL+q.FIELDS['switches']), 1)

    def test_up_down_pick_the_enemy_above_or_below_the_target_within_the_cone(self):
        # Orthographic camera: screen y = world y (down is +y).
        places = [(100, 300, 0), (256, 224, 0), (0, 0, 0), (270, 150, 0), (0, 0, 0), (400, 200, 0)]
        c = make(positions=places)
        self.assertEqual(flick(c, UP), 3)
        self.assertEqual(flick(c, DOWN), 1, 'from 3, 1 is below it')
        self.assertEqual(flick(c, DOWN), 1, 'nothing below 1 inside +-60 degrees: no change')
        self.assertEqual(counter(c, 'aims'), 2); self.assertEqual(counter(c, 'unchanged'), 1)
        self.assertEqual(c.u(sel.CONTROL+sel.FIELDS['aim_result']), 0xFFFFFFFF)
        # A tighter candidate beats a nearer one outside the cone; ties go to the lower slot.
        places = [(100, 300, 0), (256, 224, 0), (0, 0, 0), (256+60, 224-40, 0), (0, 0, 0), (256+25, 224-40, 0)]
        c = make(positions=places)
        self.assertEqual(flick(c, UP), 5)

    def test_masking_rules_and_no_synthetic_press(self):
        for name, script in SCRIPTS.items():
            c = follow_camera(make(positions=self.places))
            seen = run_script(c, script)
            no_synthetic_press(self, script, seen)
            if name == 'release the button with the stick held':
                self.assertEqual(seen[2:9], [L3, L3, 0, 0, 0, 0, 0], 'kept masked until the stick is released')
                self.assertEqual(counter(c, 'masked'), 7)
                self.assertTrue(any(design_rule(script)[k] & ~design_rule(script)[k-1] & script[k-1] & sel.STICK
                                    for k in range(1, len(script))), 'the DESIGN rule manufactures a press here')
            elif name == 'diagonal sweep':
                self.assertEqual(seen, [0, L3, L3, L3, L3, L3, 0]); self.assertEqual(counter(c, 'steps'), 1)
            elif name == 'R3 clicked mid-flick':
                self.assertEqual(seen, [0, L3, L3, L3, L3, L3, 0, 0], 'R3 masked from the flick until released')
                self.assertEqual(c.u(row(c)+off.OFF), 0)
            else:
                self.assertEqual(seen, script, f'{name}: untouched'); self.assertEqual(counter(c, 'masked'), 0)
                self.assertEqual(counter(c, 'aims'), 0, name)
                self.assertEqual(counter(c, 'steps'), int(any(w & L3 for w in script)), f'{name}: a plain tap switches')

    def test_stick_aim_off_or_r3_button_leaves_the_stick_native(self):
        for kwargs in (dict(stick=0), dict(stick=0, button=R3, off_button=R3)):
            c = make(positions=self.places, **kwargs)
            button = kwargs.get('button', L3)
            script = [0, button, button | RIGHT, button | RIGHT, RIGHT, 0]
            self.assertEqual(run_script(c, script), script)
            self.assertEqual((counter(c, 'masked'), counter(c, 'aims')), (0, 0))
            self.assertEqual(counter(c, 'steps'), 1, 'the release is an ordinary switch')

    def test_four_routed_pads_are_independent(self):
        pads = [RECORDS, RECORDS+448, quad.PADS, quad.PADS+448]
        places = [CENTRE, polar(90, 60, CENTRE), polar(100, 60, CENTRE), polar(30, 80, CENTRE), (256, 224, 200),
                  polar(150, 60, CENTRE)]
        c = make(positions=places, humans=(0, 1, 2, 3), resolver=0x1DC2A0)
        c.callbacks[0x1DC2A0] = lambda m: m.r.__setitem__(2, pads[m.u(m.r[4])])
        c.w(quad.CONTROL+20, 1); c.w(pads[2]+328, L3); frame(c)
        c.w(pads[2]+328, L3 | RIGHT); c.w(pads[0]+328, RIGHT); c.w(pads[1]+328, L3); frame(c)
        self.assertEqual([c.u(p+328) for p in pads], [RIGHT, L3, L3, 0], 'only the aiming seat is masked')
        self.assertNotEqual(target(c, 2), 3); self.assertEqual(target(c, 0), 1)
        self.assertEqual([c.u(own(c, i)+sel.MASK_BITS) for i in range(4)], [0, 0, RIGHT, 0])
        self.assertEqual(c.u(own(c, 2)+sel.MASK_SEQ), 1, 'P3 is a quad record: its publication is latched')

    def test_stale_p3_records_step_once_and_lease_neutral_or_fresh_neutral_rearm(self):
        pads = [RECORDS, RECORDS+448, quad.PADS, quad.PADS+448]
        places = [CENTRE, polar(90, 60, CENTRE), polar(270, 60, CENTRE), polar(30, 80, CENTRE),
                  polar(200, 60, CENTRE), polar(150, 60, CENTRE)]
        c = make(positions=places, humans=(0, 2), resolver=0x1DC2A0, targets=[1, 0, 1, 0, 1, 0])
        c.callbacks[0x1DC2A0] = lambda m: m.r.__setitem__(2, pads[m.u(m.r[4])])
        state = {'seq': 0}
        def fresh(word):
            state['seq'] += 1; c.w(quad.CONTROL+20, state['seq']); c.w(quad.CONTROL+24, 0); c.w(pads[2]+328, word)
            frame(c)
        def stale(n=1, lease=False):
            for _ in range(n):
                if lease: c.w(quad.CONTROL+24, quad.LEASE); c.w(pads[2]+328, 0)
                else: c.w(quad.CONTROL+24, c.u(quad.CONTROL+24)+1)
                frame(c)
        fresh(L3); fresh(L3 | RIGHT); first = target(c, 2)
        self.assertNotEqual(first, 1)
        stale(3); fresh(L3 | RIGHT); stale(2)
        self.assertEqual(target(c, 2), first, 'a held stick steps once across stale updates')
        self.assertEqual(c.u(pads[2]+328), L3); self.assertGreaterEqual(counter(c, 'restored'), 5)
        fresh(L3); fresh(L3 | RIGHT); second = target(c, 2)
        self.assertNotEqual(second, first, 'fresh neutral re-arms')
        stale(1, lease=True); stale(1, lease=True); fresh(L3 | RIGHT)
        self.assertNotEqual(target(c, 2), second, 'a lease-neutral update is a real neutral')

    def test_pressed_words_never_carry_a_masked_bit_on_native_or_quad_records(self):
        # The native poll derives +336 (edge) and +340 (edge with auto-repeat) from the physical word and the
        # previous one it keeps at +332, so a flick's first update carries its real edge. The quad frame derives
        # both from +328 and +332 every update: after a stale update +332 holds the masked word, and a fresh
        # publication raised the masked bit again (a synthetic press). Neither may reach the actor.
        pads = [RECORDS, RECORDS+448, quad.PADS, quad.PADS+448]
        places = [CENTRE, polar(90, 60, CENTRE), polar(270, 60, CENTRE), polar(30, 80, CENTRE),
                  polar(200, 60, CENTRE), polar(150, 60, CENTRE)]
        c = follow_camera(make(positions=places, humans=(0, 2), resolver=0x1DC2A0, targets=[1, 0, 1, 0, 1, 0]))
        c.callbacks[0x1DC2A0] = lambda m: m.r.__setitem__(2, pads[m.u(m.r[4])])
        c.write(quad.FRAME, quad.frame(QUAD_NEXT)); c.write(quad.CONTROL, struct.pack('<4I', quad.MAGIC, MANAGER, 6, 1))
        sequence = [0]

        def update(p1, p3):
            """One game update: the native poll (P1), the real quad frame (P3: a fresh word, or None for a stale
            update), then the queue; the pressed words the actor then reads are checked."""
            kept = c.u(RECORDS+332)
            c.write(RECORDS+328, struct.pack('<4I', p1, p1, p1 & ~kept, p1 & ~kept))
            if p3 is not None:
                sequence[0] += 1
                c.write(quad.MAILBOX, struct.pack('<I4f12x', p3, 0, 0, 0, 0)); c.w(quad.CONTROL+16, sequence[0])
            c.r[29] = 0x1FFFF00; c.r[31] = 0xFEED0000
            self.assertEqual(c.run(quad.FRAME, stops=(QUAD_NEXT,)), QUAD_NEXT)
            frame(c)
            for record in (RECORDS, quad.PADS):
                held = c.u(record+328)
                for word in PRESSED_WORDS:
                    pressed = c.u(record+word)
                    self.assertFalse(pressed & ~held & (sel.STICK | R3),
                                     f'record {record:#x} +{word}: pressed {pressed:#x} over held {held:#x} ({p1:#x}, {p3})')
        for p1, p3 in ((0, 0), (L3, L3), (L3 | RIGHT, L3 | RIGHT), (L3 | RIGHT, None), (L3 | RIGHT, None),
                       (L3 | RIGHT | R3, L3 | RIGHT | R3), (L3 | RIGHT | R3, None), (L3 | RIGHT, L3 | RIGHT),
                       (L3, None), (L3, L3), (0, 0), (RIGHT, RIGHT)):
            update(p1, p3)
        self.assertEqual(counter(c, 'steps'), 2, 'each seat stepped once')
        self.assertGreaterEqual(counter(c, 'restored'), 1, 'the stale P3 updates kept the mask')
        self.assertEqual([c.u(r+336) for r in (RECORDS, quad.PADS)], [RIGHT, RIGHT], 'a later plain push is native again')

    def test_merged_coop_control_masks_player_one_pad(self):
        import coop_controller
        # Two humans fused into physical 0, merged (split_controls) control: the resolver builds the record from
        # pad 0 (stick, R3, L3) and pad 1's movement bits. Its hook replaces the native accessor as in the game.
        c = make(positions=self.places, humans=(0,), mode='coop', targets=[1, 0, 1, 0, 1, 0])
        c.write(coop.ACTOR_PAD, coop_controller.payload()); c.write(coop.NATIVE_PAD, coop.NATIVE(coop.HOOK, 0x20))
        c.write(modes.CONTROL, struct.pack('<9I', modes.MAGIC, MANAGER, 6, modes.COOP, 2, 0x5, 0, 2, 1))
        c.write(0x1DC2A0, struct.pack('<2I', (2 << 26) | (coop.ACTOR_PAD >> 2), 0)); del c.callbacks[0x1DC2A0]
        c.w(RECORDS+448+328, 0x10)
        follow_camera(c)
        seen = []
        for word in (0, L3, L3 | RIGHT, RIGHT, 0):
            press(c, word); seen.append(visible(c))
            c.r[4] = ACTORS[0]; c.r[31] = 0xFEED0000; c.run(0x1DC2A0)     # the actor update's own resolver call
            self.assertEqual(c.r[2], coop.MERGED)
            self.assertEqual(c.u(coop.MERGED+328) & sel.STICK, 0, 'the merged record is rebuilt from the masked pad')
        self.assertEqual(seen, [0, L3, L3, 0, 0], 'pad 0 (where merged control takes the stick) is masked')
        self.assertEqual(c.u(own(c)+sel.MASK_REC), 0); self.assertEqual(counter(c, 'steps'), 1)
        press(c, L3); c.w(RECORDS+328, L3 | RIGHT); frame(c)
        self.assertEqual(c.u(own(c)+sel.MASK_REC), RECORDS, 'the latch names pad 0, not the rebuilt record')

    def test_shared_lock_off_fires_on_release_with_stick_aim_on(self):
        for rate, threshold, on_threshold in ((30, 15, 1), (25, 13, 1), (30, 15, 6), (25, 13, 5)):
            c = follow_camera(make(positions=self.places, threshold=threshold, on_threshold=on_threshold))
            press(c, L3, 40)
            self.assertEqual((c.u(row(c)+off.OFF), c.u(row(c)+off.FIRED)), (0, 0), 'nothing while held')
            press(c, 0); self.assertEqual(c.u(row(c)+off.OFF), 1, (rate, 'unlocks on release'))
            self.assertEqual(counter(c, 'release_unlocks'), 1); self.assertEqual(target(c), 1)
            c = follow_camera(make(positions=self.places, threshold=threshold, on_threshold=on_threshold))
            press(c, L3, 2*rate); press(c, L3 | RIGHT); press(c, L3); press(c, 0)
            self.assertEqual((c.u(row(c)+off.OFF), c.u(row(c)+off.FIRED)), (0, 0), 'a late flick steps, locked')
            self.assertNotEqual(target(c), 1)
            c = follow_camera(make(positions=self.places, threshold=threshold, on_threshold=on_threshold))
            press(c, L3, threshold-1); press(c, 0)
            self.assertEqual(c.u(row(c)+off.OFF), 0); self.assertNotEqual(target(c), 1, 'before the lock-off time: switch')
            c = follow_camera(make(positions=self.places, threshold=threshold, on_threshold=on_threshold))
            press(c, L3, threshold); press(c, 0); self.assertEqual(c.u(row(c)+off.OFF), 1, 'at the lock-off time: unlock')

    def test_without_stick_aim_or_with_a_separate_button_lock_off_fires_while_held_as_before(self):
        for kwargs in (dict(stick=0), dict(off_button=0x100)):
            c = make(positions=self.places, **kwargs)
            press(c, kwargs.get('off_button', L3), 15)
            self.assertEqual(c.u(row(c)+off.OFF), 1, kwargs)
            press(c, 0); self.assertEqual(c.u(row(c)+off.OFF), 1)

    def test_lock_off_disabled_mask_zero_still_switches_and_never_unlocks(self):
        c = follow_camera(make(positions=self.places, off_button=0))
        press(c, L3, 90); self.assertEqual(c.u(row(c)+off.OFF), 0)
        press(c, 0); self.assertNotEqual(target(c), 1); self.assertEqual(c.u(row(c)+off.OFF), 0)

    def test_unlocked_tap_uses_pick_and_unlocked_stick_relocks_toward_the_direction(self):
        places = [(100, 300, 0), (230, 224, 0), (0, 0, 0), (400, 224, 0), (0, 0, 0), (100, 224, 0)]
        c = make(positions=places, stick=1)
        press(c, L3, 15); press(c, 0); self.assertEqual(c.u(row(c)+off.OFF), 1)
        c.calls.clear(); press(c, L3); press(c, L3 | RIGHT)
        self.assertEqual((target(c), c.u(row(c)+off.OFF), c.u(row(c)+off.QUIET)), (3, 0, 2), 'right of the view centre')
        self.assertEqual(c.calls, [('set', ACTORS[0], 5)], 'relocked once through the native flag setter')
        press(c, L3); press(c, 0); self.assertEqual((target(c), c.u(row(c)+off.OFF)), (3, 0))
        press(c, L3, 15); press(c, 0); self.assertEqual(c.u(row(c)+off.OFF), 1)
        self.assertEqual(tap(c), 1, 'tap while unlocked: the enemy nearest the view centre (PICK)')
        self.assertEqual(c.u(row(c)+off.OFF), 0)
        press(c, L3, 15); press(c, 0); self.assertEqual(c.u(row(c)+off.OFF), 1)
        for n in range(3): c.write(MODELS[2*n+1]+2416+12, struct.pack('<f', -1.0))
        press(c, L3); press(c, L3 | LEFT); press(c, L3); press(c, 0)
        self.assertEqual(c.u(row(c)+off.OFF), 1, 'nobody in that direction: stays unlocked')

    def test_a_gap_in_the_humans_updates_resets_every_latch(self):
        c = follow_camera(make(positions=self.places))
        press(c, L3); press(c, L3 | RIGHT)
        self.assertEqual(c.u(own(c)+sel.MASK_BITS), RIGHT); self.assertEqual(c.u(own(c)+sel.AIM_LATCH), 1)
        c.w(ACTORS[0]+0x1278, 1); press(c, L3 | RIGHT, 3)          # taken over by the CPU: not processed
        c.w(ACTORS[0]+0x1278, 0); c.w(RECORDS+328, RIGHT); frame(c)
        self.assertEqual([c.u(own(c)+f) for f in (sel.MASK_BITS, sel.AIM_LATCH, sel.STICK_LATCH, sel.ARMED)], [0, 0, 0, 0])
        self.assertEqual(visible(c), RIGHT, 'a stick held across the gap is native again')

    def test_memory_writes_stay_inside_the_owned_state(self):
        c = follow_camera(make(positions=self.places))
        press(c, 0)
        allowed = [(core.TABLE, core.TABLE+48), (off.ROWS, off.ROWS+12*off.STRIDE), (sel.ROWS, sel.END),
                   (sel.CONTROL, sel.CONTROL+0x100), (ls.CONTROL, ls.CONTROL+0x400), (RECORDS+328, RECORDS+344),
                   (0x1FF0000, 0x2000000)]
        before = dict(c.memory)
        for word in (L3, L3 | RIGHT, L3, 0, L3, 0, L3 | UP, 0):     # the native poll's words, then the update
            edge = word & ~c.u(RECORDS+332); c.write(RECORDS+332, struct.pack('<3I', word, edge, edge)); press(c, word)
        changed = {a for a, v in c.memory.items() if before.get(a, 0) != v}
        stray = sorted(a for a in changed if not any(lo <= a < hi for lo, hi in allowed))
        self.assertEqual(stray, [], [hex(a) for a in stray[:8]])


class AfterKoTests(unittest.TestCase):
    """T-9 with A8: KO retarget to the enemy nearest the view centre, debounced, never relocking."""
    def machine(self, **kwargs):
        # PICK's choice (nearest the orthographic view centre) is 5; the survivor picker would take 3.
        places = [(100, 300, 0), (256, 224, 0), (0, 0, 0), (60, 60, 0), (0, 0, 0), (250, 230, 0)]
        return make(positions=places, **kwargs)

    def test_defeated_target_retargets_to_the_enemy_nearest_the_view_centre(self):
        c = self.machine(); press(c, 0)
        c.w(ACTORS[1]+0x9E4, 0); press(c, 0)
        self.assertEqual(target(c), 1, 'one update of zero health is not yet a defeat')
        press(c, 0); self.assertEqual(target(c), 5); self.assertEqual(counter(c, 'ko'), 1)
        self.assertEqual(c.u(q.CONTROL+q.FIELDS['switches']), 1)

    def test_the_choice_is_made_when_the_target_falls_before_the_camera_turns(self):
        # Live, by the safe point the camera had turned toward the game's replacement target, so "nearest the
        # centre" had become that replacement. The pick is taken on the first defeated update instead.
        c = self.machine(); press(c, 0)
        c.w(ACTORS[1]+0x9E4, 0); press(c, 0)                      # first defeated update: 5 is nearest the centre
        place(c, 5, (60, 60, 0)); place(c, 3, (256, 224, 0))     # the view then turns: 3 is now at the centre
        press(c, 0); self.assertEqual(target(c), 5); self.assertEqual(counter(c, 'ko'), 1)
        c = self.machine(); press(c, 0)
        c.w(ACTORS[1]+0x9E4, 0); press(c, 0)
        place(c, 3, (256, 224, 0)); c.w(ACTORS[5]+0x9E4, 0)      # the chosen enemy fell too: choose again now
        press(c, 0); self.assertEqual(target(c), 3)

    def test_survivor_picker_moved_the_table_first_is_still_overridden_once(self):
        c = self.machine(); press(c, 0)
        c.w(ACTORS[1]+0x9E4, 0); c.w(core.TABLE, 3); press(c, 0, 2)
        self.assertEqual(target(c), 5); press(c, 0, 5); self.assertEqual(target(c), 5); self.assertEqual(counter(c, 'ko'), 1)

    def test_waits_for_delayed_damage_and_paired_actions(self):
        for field, value in ((3480, 7), (0x948, 301)):
            c = self.machine(); press(c, 0); c.w(ACTORS[0]+field, value)
            c.w(ACTORS[1]+0x9E4, 0); press(c, 0, 4); self.assertEqual(target(c), 1, field)
            c.w(ACTORS[0]+field, 0 if field != 0x948 else 11); press(c, 0); self.assertEqual(target(c), 5, field)

    def test_the_choice_is_not_remeasured_while_the_safe_point_waits_and_the_camera_turns(self):
        # While the table still holds the fallen target, the defeat cycle repeats every other update; it must not
        # measure the choice again from a view that has turned (here toward 3) while the safe point waits.
        c = self.machine(); press(c, 0); c.w(ACTORS[0]+0x948, 301)       # a paired action: the safe point waits
        c.w(ACTORS[1]+0x9E4, 0); press(c, 0)                             # chosen now: 5 is nearest the centre
        place(c, 5, (60, 60, 0)); place(c, 3, (256, 224, 0))
        press(c, 0, 7); self.assertEqual(target(c), 1, 'still waiting for the safe point')
        c.w(ACTORS[0]+0x948, 11); press(c, 0)
        self.assertEqual((target(c), counter(c, 'ko')), (5, 1))

    def test_no_choice_or_request_while_a_cinematic_a_paired_pause_or_a_shared_rush_owns_the_view(self):
        import rush_cinematics as rush
        camera = 0x1950000

        def cinematic(c, on): c.w(0x2FEBCC, camera); c.w(camera+812, int(on))
        def pause(c, on): c.w(core.PAIR+4, int(on))
        def shared_rush(c, on):
            c.w(rush.CONTROL, rush.MAGIC); c.callbacks[rush.OWNER] = lambda m, v=int(on): m.r.__setitem__(2, v)
        for name, own in (('cinematic', cinematic), ('paired pause', pause), ('shared rush', shared_rush)):
            c = self.machine(); press(c, 0); own(c, True)
            place(c, 3, (256, 224, 0)); place(c, 5, (60, 60, 0))         # the cinematic's framing
            c.w(ACTORS[1]+0x9E4, 0); press(c, 0, 5)
            self.assertEqual((target(c), c.u(q.CONTROL+q.FIELDS['queued'])), (1, 0), f'{name}: the count waits')
            own(c, False); place(c, 3, (60, 60, 0)); place(c, 5, (250, 230, 0))   # the player's own view again
            press(c, 0); self.assertEqual(target(c), 1, f'{name}: one free update is not yet a defeat')
            press(c, 0); self.assertEqual((target(c), counter(c, 'ko')), (5, 1), name)

    def test_a_revived_target_defeated_again_is_retargeted_again(self):
        c = self.machine(); press(c, 0)
        c.w(ACTORS[1]+0x9E4, 0); press(c, 0, 2); self.assertEqual(target(c), 5)
        c.w(ACTORS[1]+0x9E4, 1000); c.w(core.TABLE, 1); press(c, 0, 2)    # revived, and targeted again
        c.w(ACTORS[1]+0x9E4, 0); press(c, 0, 2)
        self.assertEqual((target(c), counter(c, 'ko')), (5, 2), 'the second defeat is a new KO')
        # Revived in place: nobody else was visible at the first defeat, so the table kept the fallen target.
        c = self.machine(); press(c, 0)
        kept = {i: c.read(MODELS[i]+2416, 16) for i in (3, 5)}
        for i in kept: c.write(MODELS[i]+2416+12, struct.pack('<f', -1.0))
        c.w(ACTORS[1]+0x9E4, 0); press(c, 0, 4)
        self.assertEqual((target(c), counter(c, 'unchanged')), (1, 1))
        for i, data in kept.items(): c.write(MODELS[i]+2416, data)
        c.w(ACTORS[1]+0x9E4, 1000); press(c, 0)                            # seen alive again
        c.w(ACTORS[1]+0x9E4, 0); press(c, 0, 2)
        self.assertEqual((target(c), counter(c, 'ko'), c.u(q.CONTROL+q.FIELDS['queued'])), (5, 1, 2))

    def test_no_request_when_unlocked_game_default_a_non_target_dies_or_nobody_is_visible(self):
        c = self.machine(); press(c, L3, 15); press(c, 0); self.assertEqual(c.u(row(c)+off.OFF), 1)
        c.w(ACTORS[1]+0x9E4, 0); press(c, 0, 4)
        self.assertEqual((target(c), c.u(row(c)+off.OFF), counter(c, 'ko')), (1, 1, 0), 'never relocks')
        c = self.machine(after_ko=0); press(c, 0); c.w(ACTORS[1]+0x9E4, 0); press(c, 0, 4)
        self.assertEqual((target(c), c.u(q.CONTROL+q.FIELDS['queued'])), (1, 0), 'game default: no request')
        c = self.machine(); press(c, 0); c.w(ACTORS[3]+0x9E4, 0); press(c, 0, 4)
        self.assertEqual((target(c), c.u(q.CONTROL+q.FIELDS['queued'])), (1, 0), 'a non-target')
        c = self.machine(); press(c, 0)
        for i in (3, 5): c.write(MODELS[i]+2416+12, struct.pack('<f', -1.0))
        c.w(ACTORS[1]+0x9E4, 0); press(c, 0, 8)
        self.assertEqual((target(c), c.u(q.CONTROL+q.FIELDS['queued']), counter(c, 'unchanged')), (1, 1, 1), 'asked once')

    def test_transformation_reads_and_fusion_consumption_are_not_defeats(self):
        c = self.machine(); press(c, 0)
        c.w(ACTORS[1]+0x994, 1); c.w(ACTORS[1]+0x9E4+164, 0); press(c, 0)
        c.w(ACTORS[1]+0x9E4+164, 900); press(c, 0, 4)
        self.assertEqual((target(c), c.u(q.CONTROL+q.FIELDS['queued'])), (1, 0), 'form row moving')
        c.w(part.CONTROL+16, 1 << 1); c.w(ACTORS[1]+0x9E4+164, 0); press(c, 0, 4)
        self.assertEqual((target(c), c.u(q.CONTROL+q.FIELDS['queued'])), (1, 0), 'fusion partner consumed')
        c = self.machine(); press(c, 0); c.w(ACTORS[1]+0x9E4, 0); press(c, 0); c.w(ACTORS[1]+0x9E4, 5); press(c, 0, 4)
        self.assertEqual((target(c), c.u(q.CONTROL+q.FIELDS['queued'])), (1, 0), 'a single zero read')


FRAMES = q.CONTROL+q.FIELDS['frames']


def ring_packet(cx, cy, r, colour=sel.CHEV):
    """The spec's ring packet, built independently: the bars' header, three strips (rim, outer, inner: SEGMENTS+1
    outer/inner pairs each), then the chevron outlines and faces (tips 1.12 r either side, pointing inward)."""
    header = bytearray(bars.sprite_template()[:96]); struct.pack_into('<Q', header, 64, 0x43)
    out = bytes(header)

    def segment(prim, rgba, n, eop=False):
        return struct.pack('<8I', 2, 0x10000000, 0xE, 0, prim, 0, 0, 0)+struct.pack('<8I', rgba, sel.ONE, 1, 0, n | (eop << 15),
                                                                                   0x14000000, 5, 0)

    def xyz(x, y): return struct.pack('<2I', (x & 0xFFFF) | (y << 16), 0)
    points = [(round(16384*math.cos(2*math.pi*i/24)), round(16384*math.sin(2*math.pi*i/24))) for i in range(25)]
    inner, band = (r*205) >> 8, max(16, r >> 4)
    for rgba, ro, ri in ((sel.DARK, r+band//2, r-band), (sel.RING, r, r-band),
                         (sel.RING, inner, inner-max(12, band//2))):
        out += segment(0x44, rgba, 50)
        for c_, s_ in points:
            for rr in (ro, ri): out += xyz(cx+((c_*rr) >> 14), cy+((s_*rr) >> 14))
    tip = (r*287) >> 8
    outline, fill = sel.CHEVRONS[0], sel.CHEVRONS[1]
    for k, (table, rgba) in enumerate(((outline, sel.DARK), (fill, colour))):
        out += segment(0x43, rgba, 6, eop=k == 1)
        for x0, sign in ((cx-tip, 1), (cx+tip, -1)):
            for ux, uy in table: out += xyz(x0+sign*((ux*r) >> 8), cy+((uy*r) >> 8))
    return out


class MarkerTests(unittest.TestCase):
    """T-14 with A9/A10: the target ring in active combat, in its own view only, drawn before the bars.

    The 3-4 view cases check the ring's own seat logic; live, three- and four-view matches never call the bar
    wrapper (no overhead bars there), so no ring is drawn in them (the limitation the build reports)."""
    def machine(self, humans=(0,), **kwargs):
        places = kwargs.pop('positions', [(100, 300, 0), (256, 224, 0), (300, 200, 0), (400, 224, 0), (150, 150, 0),
                                          (60, 224, 0)])
        c = make(positions=places, humans=humans, **kwargs)
        for p, b in ((bars.RECT, bars.rectangle_code()), (bars.TEMPLATE, bars.sprite_template()),
                     (display.SUBJECT, display.subject_code())):
            c.write(p, b)
        c.write(bars.CONTROL+0x80, struct.pack('<4f', 0, bars.HEAD_LIFT, 0, 0))
        return c

    def run_marker(self, c):
        c.events.clear(); c.packets.clear(); c.r[31] = 0xFEED0000; c.r[29] = 0x1FFFF00
        saved = list(c.r[16:24]); c.r[2] = 0x12345678
        c.run(sel.MARKER)
        self.assertEqual((c.r[16:24], c.r[29], c.saved_matrix), (saved, 0x1FFFF00, []))

    def draw(self, c):
        self.run_marker(c)
        self.assertEqual(c.events[-1], 'bars', 'the overhead bars are drawn last, on every path')
        return list(c.packets)

    @staticmethod
    def radius(view, age=None, h=0):
        """(Rv, r) in sixteenths: (H*72) >> 8 for the projected head-root extent H, clamped to the view height's
        [27/64, 78/64] (sixteenths per line), times the drop-in scale (at rest from len(SCALE) on)."""
        vh = min(view[3]-view[2]+1, (11*(view[1]-view[0]+1)) >> 3)     # the view size: min(height, 11/8 width)
        rv = min(max((h*72) >> 8, (vh*27) >> 6), (vh*78) >> 6)
        scale = sel.SCALE[age] if age is not None and age < len(sel.SCALE) else 256
        return rv, (rv*scale) >> 8

    def expect(self, x, y, age=None, view=(0, 511, 0, 447), colour=sel.CHEV, h=0):
        """The ring of a target whose body centre stands at (x, y), its centre kept inside the view by Rv/2."""
        rv, r = self.radius(view, age, h)
        cx = min(max(int((x+1792)*16), (view[0]+1792)*16+rv//2), (view[1]+1793)*16-rv//2)
        cy = min(max(int((y+1824)*16), (view[2]+1824)*16+rv//2), (view[3]+1825)*16-rv//2)
        return ring_packet(cx, cy, r, colour)

    def test_the_ring_radius_scale_and_tables(self):
        self.assertEqual([self.radius(v)[0] for v in ((0, 511, 0, 447), (0, 511, 0, 223), (0, 511, 0, 511),
                                                      (0, 511, 0, 255))], [189, 94, 216, 108])
        self.assertEqual([self.radius(v, h=10**5)[0] for v in ((0, 511, 0, 447), (0, 511, 0, 223))], [546, 273])
        self.assertEqual((sel.SIZE_NUM, sel.MIN_NUM, sel.MAX_NUM), (72, 27, 78))
        self.assertEqual(sel.SCALE, (410, 371, 338, 310, 287, 271, 261, 256))
        self.assertEqual([round(s/256, 2) for s in sel.SCALE], [1.6, 1.45, 1.32, 1.21, 1.12, 1.06, 1.02, 1.0])
        data = sel.ring_data()
        self.assertEqual(len(data), 0x1B0)
        header = bytearray(bars.sprite_template()[:96]); struct.pack_into('<Q', header, 64, 0x43)
        self.assertEqual(data[:96], bytes(header), 'the bars\' A+D header: alpha on, Z test always')
        table = struct.unpack_from('<50i', data, sel.RING_TABLE-sel.RING_HEADER)
        self.assertEqual(table[:2], (16384, 0)); self.assertEqual(table[-2:], (16384, 0))
        self.assertEqual(table[12:14], (0, 16384), 'a quarter turn after 6 of 24 segments')
        self.assertEqual(struct.unpack_from('<8I', data, sel.RING_SCALE-sel.RING_HEADER), sel.SCALE)
        for k, shape in enumerate(sel.CHEVRONS):
            self.assertEqual(struct.unpack_from('<6i', data, sel.RING_OUTLINE+24*k-sel.RING_HEADER),
                             tuple(v for point in shape for v in point))
        # The outlines contain their faces with a margin (1.5 px at Rv 58 / scale 256).
        for (outline, face) in ((sel.CHEVRONS[0], sel.CHEVRONS[1]), (sel.CHEVRONS[2], sel.CHEVRONS[3])):
            self.assertGreater(outline[0][0], face[0][0]); self.assertLess(outline[1][0], face[1][0])
            self.assertLess(outline[1][1], face[1][1]); self.assertGreater(outline[2][1], face[2][1])

    def test_one_packet_drawn_before_the_bars_around_the_locked_humans_target(self):
        c = self.machine()
        self.assertEqual(self.draw(c), [self.expect(256, 224, 0)], 'first sight: the drop-in starts at 1.6x')
        self.assertEqual(c.events, ['push', 'sprite', 'pop', 'bars'])
        self.assertEqual(len(c.packets[0]), 96+3*(64+400)+2*(64+48))
        self.assertEqual(counter(c, 'markers'), 1)
        self.assertEqual(struct.unpack('<2I', c.read(sel.MARKS, 8)), (2, 0), 'seat 0 marks target 1 at update 0')
        c.w(core.TABLE, 3); self.assertEqual(self.draw(c), [self.expect(400, 224, 0)], 'a new target drops in')
        c.w(core.TABLE, 5); c.w(FRAMES, 900)
        self.assertEqual(self.draw(c), [self.expect(60, 224, 0)], 'another target drops in')
        self.assertEqual(counter(c, 'markers'), 3)

    def test_the_body_centre_is_the_midpoint_of_the_head_bone_and_the_root(self):
        c = self.machine()
        head = BONES[1]; c.w(MODELS[1]+3436+48*4, head); c.write(head+64, struct.pack('<4f', 256, 160, 0, 1))
        self.assertEqual(self.draw(c), [self.expect(256, 192, 0, h=64*16)])
        self.assertEqual((counter(c, 'size_h'), counter(c, 'size_r')), (1024, 288), 'r follows the head-root extent')

    def test_drop_in_scale_then_the_ring_rests(self):
        c = self.machine(); c.w(FRAMES, 1000); self.draw(c)
        for age in range(20):
            c.w(FRAMES, 1000+age)
            self.assertEqual(self.draw(c), [self.expect(256, 224, age)], age)
        c.w(FRAMES, 999); self.assertEqual(self.draw(c), [self.expect(256, 224)], 'an older update: at rest')

    def test_a_new_target_drops_in_and_an_unlock_clears_the_mark_so_a_relock_drops_in(self):
        c = self.machine(); c.w(FRAMES, 50); self.draw(c); c.w(FRAMES, 300)
        self.assertEqual(self.draw(c), [self.expect(256, 224)], 'at rest')
        c.w(core.TABLE, 3); self.assertEqual(self.draw(c), [self.expect(400, 224, 0)])
        c.w(FRAMES, 303); self.assertEqual(self.draw(c), [self.expect(400, 224, 3)])
        c.w(row(c)+off.OFF, 1); self.assertEqual(self.draw(c), []); self.assertEqual(c.events, ['bars'])
        self.assertEqual(c.u(sel.MARKS), 0, 'unlocking clears the mark')
        c.w(FRAMES, 400); c.w(row(c)+off.OFF, 0)
        self.assertEqual(self.draw(c), [self.expect(400, 224, 0)], 'the relock drops in again')
        c.w(FRAMES, 402); self.assertEqual(self.draw(c), [self.expect(400, 224, 2)])

    def test_the_centre_is_kept_inside_the_view_by_half_rv(self):
        for view in ((0, 511, 0, 447), (0, 254, 0, 447), (257, 511, 0, 447), (0, 254, 0, 222), (257, 511, 225, 447)):
            x0, x1, y0, y1 = view
            for x, y in ((x0+2, (y0+y1)//2), (x1-2, (y0+y1)//2), ((x0+x1)//2, y0+4), ((x0+x1)//2, y1-1),
                         (x0+1, y0+4), (x1, y1)):
                right = x0 != 0
                subject, target_ = (1, 2) if right else (0, 1)
                places = [(0, 0, 0)]*6; places[subject] = ((x0+x1)//2, (y0+y1)//2+30, 0); places[target_] = (x, y, 0)
                c = self.machine(humans=(0, 1) if right else (0,), positions=places, view=view, targets=[1, 2, 1, 0, 1, 0])
                got = self.draw(c)
                self.assertEqual(got, [self.expect(x, y, 0, view)], (view, x, y))
                rv = self.radius(view)[0]
                first = struct.unpack_from('<I', got[0], 96+64)[0]          # the rim's first outer point (cx + r + 24, cy)
                r0 = self.radius(view, 0)[1]
                cx16, cy16 = (first & 0xFFFF)-(r0+max(16, r0 >> 4)//2), first >> 16
                self.assertTrue((x0+1792)*16+rv//2 <= cx16 <= (x1+1793)*16-rv//2, (view, x, y))
                self.assertTrue((y0+1824)*16+rv//2 <= cy16 <= (y1+1825)*16-rv//2, (view, x, y))

    def test_no_ring_without_a_locked_living_human_or_a_valid_enemy_target_or_outside_combat(self):
        cases = [((row(None)+off.OFF, 1), 'unlocked'), ((ACTORS[0]+0x1278, 1), 'CPU subject'),
                 ((ACTORS[0]+0x9E4, 0), 'defeated subject'), ((ACTORS[1]+0x9E4, 0), 'defeated target'),
                 ((part.CONTROL+12, 0x3D), 'absent target'), ((core.TABLE, 2), 'ally target'),
                 ((core.PAIR+4, 1), 'virtual pair'), ((sel.CONTROL+sel.FIELDS['marker'], 0), 'marker off'),
                 ((BATTLE, 2), 'intro'), ((0x333700, 1), 'result screen'), ((sel.CONTROL+4, MANAGER+4), 'stale')]
        for (address, value), name in cases:
            c = self.machine(); c.w(address, value)
            self.assertEqual(self.draw(c), [], name)
            self.assertEqual(c.events, ['bars'], f'{name}: no projection before the seat and target are valid')
        c = self.machine(); camera = 0x1950000; c.w(0x2FEBCC, camera); c.w(camera+812, 1)
        self.assertEqual(self.draw(c), [], 'cinematic camera owns the view'); self.assertEqual(c.events, ['bars'])
        import rush_cinematics
        c = self.machine(); c.w(rush_cinematics.CONTROL, rush_cinematics.MAGIC)
        c.callbacks[rush_cinematics.OWNER] = lambda m: m.r.__setitem__(2, 1)
        self.assertEqual(self.draw(c), [], 'shared rush owns the view'); self.assertEqual(c.events, ['bars'])
        c.callbacks[rush_cinematics.OWNER] = lambda m: m.r.__setitem__(2, 0)
        self.assertEqual(len(self.draw(c)), 1)
        c = self.machine(); c.write(MODELS[1]+2416, struct.pack('<4f', 900, 224, 0, 1))
        self.assertEqual(self.draw(c), [], 'centre outside the view'); self.assertEqual(c.events, ['push', 'pop', 'bars'])
        c = self.machine(matrix=(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1792, 1824, 0, -1))
        self.assertEqual(self.draw(c), [], 'behind the camera'); self.assertEqual(c.events, ['push', 'pop', 'bars'])

    def test_the_chevrons_blink_while_the_target_attacks_you(self):
        c = self.machine()
        for p, b in threat.code_parts(): c.write(p, b)
        for p, b in threat.data_blocks(MANAGER, 1, 2, 0, sel.MARKER, 0): c.write(p, b)
        rows = threat.ROWS
        for frames, atk, marks, stamp, want in (
                (8, 0b10, 2, 8, threat.WARN_B), (4, 0b10, 2, 4, threat.WARN_A), (12, 0b10, 2, 11, threat.WARN_A),
                (12, 0b1000, 2, 12, None), (4, 0b10, 1, 4, None), (4, 0b10, 2, 2, None)):
            c.w(FRAMES, frames); c.w(sel.MARKS, 0)
            c.w(rows+threat.ATK, atk); c.w(rows+threat.STAMP, stamp); c.w(threat.CONTROL+threat.FIELDS['marks'], marks)
            got = self.draw(c)
            self.assertEqual(got, [self.expect(256, 224, 0, colour=want or sel.CHEV)], (frames, atk, marks, stamp))
        self.assertEqual((threat.WARN_A, threat.WARN_B), (sel.WARN_Y, sel.RED))

    def test_single_view_draws_only_the_view_subjects_ring_and_follows_side_one(self):
        c = self.machine(humans=(0, 1), targets=[1, 0, 1, 0, 1, 0])
        c.w(CAM+656+512, 0)                                         # both successor cameras full-screen
        self.assertEqual(self.draw(c), [self.expect(256, 224, 0)], 'side 0 subject: its own target only')
        c.w(follow.LEADER_CONTROL+12, 1)
        self.assertEqual(self.draw(c), [self.expect(100, 300, 0)], 'following side 1: the second human\'s target')
        self.assertEqual([c.u(sel.MARKS+8*k) for k in range(2)], [2, 1], 'each seat keeps its own mark')

    def test_split_and_quad_views_each_draw_their_own_seats_ring_at_their_own_size(self):
        for humans in (2, 3, 4):
            rects = views.rectangles(humans)
            for seat, rect in enumerate(rects):
                places = [(0, 0, 0)]*6
                targets = [5, 4, 3, 2, 1, 0][:humans]+[0]*(6-humans)
                for k, other in enumerate(rects):
                    places[targets[k]] = ((other[0]+other[1])/2, (other[2]+other[3])/2+20, 0)
                c = self.quad(humans, places, rect, targets)
                drawn = self.draw(c)
                t = c.u(core.TABLE+4*seat)
                self.assertEqual(drawn, [self.expect(places[t][0], places[t][1], 0, rect)], (humans, seat))
                self.assertEqual([c.u(sel.MARKS+8*k) for k in range(4)], [t+1 if k == seat else 0 for k in range(4)])
        c = self.machine(humans=(0, 1))
        c.write(views.CONTROL, struct.pack('<4I', views.MAGIC, MANAGER, 6, 1)); c.w(views.CONTROL+views.VIEW_COUNT, 2)
        self.assertEqual(self.draw(c), [], 'no quad camera holds this view: nothing')

    def quad(self, humans, places, rect, targets):
        c = self.machine(humans=tuple(range(humans)), positions=places, view=rect, mode='ffa', targets=targets)
        c.write(views.CONTROL, struct.pack('<4I', views.MAGIC, MANAGER, 6, 1))
        c.w(views.CONTROL+views.VIEW_COUNT, humans)
        for k, other in enumerate(views.rectangles(humans)):
            for i, v in enumerate(other): c.w(views.CAMERAS+k*1024+512+4*i, v)
            c.w(views.SUBJECTS+4*k, k)
        return c

    def test_split_seats_drop_in_on_their_own_clocks(self):
        rects = views.rectangles(2)
        places = [(0, 0, 0)]*6; targets = [5, 4, 0, 0, 0, 0]
        for k, other in enumerate(rects): places[targets[k]] = ((other[0]+other[1])//2, (other[2]+other[3])//2+20, 0)
        c = self.quad(2, places, rects[0], targets)

        def show(seat):
            for i, v in enumerate(rects[seat]): c.w(CAM+512+4*i, v)
            return self.draw(c)
        c.w(FRAMES, 10); self.assertEqual(show(0), [self.expect(*places[5][:2], 0, rects[0])])
        c.w(FRAMES, 14); self.assertEqual(show(1), [self.expect(*places[4][:2], 0, rects[1])], 'seat 1 drops in on its own')
        self.assertEqual(show(0), [self.expect(*places[5][:2], 4, rects[0])], 'seat 0 keeps its own start')
        self.assertEqual([struct.unpack('<2I', c.read(sel.MARKS+8*k, 8)) for k in range(2)], [(6, 10), (5, 14)])
        c.w(core.TABLE, 3); places3 = ((rects[0][0]+rects[0][1])//2-40, 200, 0); place(c, 3, places3)
        c.w(FRAMES, 20); self.assertEqual(show(0), [self.expect(places3[0], places3[1], 0, rects[0])], 'seat 0 retargets')
        self.assertEqual(show(1), [self.expect(*places[4][:2], 6, rects[1])], 'seat 1 is not restarted')

    def real_bars(self, c, friend, enemy):
        """The real display pass (BAR_DRAW with BAR_FILTER) in place of the harness's 'bars' event."""
        del c.callbacks[display.BAR_DRAW]
        c.write(display.BAR_DRAW, bars.draw_code(False, visibility_filter=display.BAR_FILTER, entry=display.BAR_DRAW))
        c.write(display.BAR_FILTER, display.bar_filter_code())
        c.write(display.CONTROL, struct.pack('<7I', display.MAGIC, MANAGER, int(friend), int(enemy), 1, 1, 0))
        c.w(bars.CONTROL, 1); c.w(bars.CONTROL+4, MANAGER)
        for i, v in enumerate(bars.COLORS): c.w(bars.CONTROL+0x30+4*i, v)
        return c

    def test_the_ring_switch_is_independent_of_both_bar_switches_with_the_real_bar_pass(self):
        counts = {}
        size = len(self.expect(256, 224, 0))
        for friend in (1, 0):
            for enemy in (1, 0):
                for marker in (1, 0):
                    c = self.real_bars(self.machine(marker=marker), friend, enemy)
                    self.run_marker(c)
                    kinds = ['ring' if len(p) == size else 'bar' if len(p) == 128 else len(p) for p in c.packets]
                    self.assertEqual(kinds.count('ring'), marker, (friend, enemy, marker))
                    self.assertEqual(set(kinds) - {'ring', 'bar'}, set())
                    if marker: self.assertEqual(kinds[0], 'ring', 'the ring is drawn before every bar')
                    counts[friend, enemy, marker] = kinds.count('bar')
                    if marker: self.assertEqual(c.packets[0], self.expect(256, 224, 0))
        for friend in (1, 0):
            for enemy in (1, 0):
                self.assertEqual(counts[friend, enemy, 1], counts[friend, enemy, 0], 'the ring never hides or adds a bar')
        self.assertEqual((counts[0, 0, 1], counts[0, 0, 0]), (0, 0), 'both bar switches off: the ring alone')
        self.assertGreater(counts[1, 0, 1], 0); self.assertGreater(counts[0, 1, 1], 0)
        self.assertEqual(counts[1, 1, 1], counts[1, 0, 1]+counts[0, 1, 1])

    def test_raster_ring_is_yellow_the_body_shows_through_and_the_bar_drawn_after_stays_intact(self):
        import numpy as np
        import gs_preview as g
        places = [(0, 0, 0)]*6; places[0] = (100, 400, 0); places[1] = (256, 324, 0)

        def image(friend, enemy, marker, background, age_frames=0):
            c = self.machine(positions=places, marker=marker)
            # A near target: its head 200 px above its root, so the ring is at its one-view maximum (34 px) around
            # the body centre (256, 224).
            head = BONES[1]; c.w(MODELS[1]+3436+48*4, head); c.write(head+64, struct.pack('<4f', 256, 124, 0, 1))
            c = self.real_bars(c, friend, enemy)
            c.w(FRAMES, 100); self.run_marker(c)
            if age_frames: c.w(FRAMES, 100+age_frames); self.run_marker(c)
            gs = g.GS(background)
            gs.feed(g.ad_packet((g.XYOFFSET_1, (1792*16) | ((1824*16) << 32))))
            for packet in c.packets: gs.feed(packet)
            return np.asarray(gs.image().convert('RGB'), np.int32), c
        grey = (90, 110, 90)
        alone, _ = image(0, 0, 1, grey, 20)
        cx, cy, rv = 256, 224, 34
        r, gr, b = alone[cy, cx+rv-1]
        self.assertTrue(r > 200 and gr > 190 and b < 80, ('outer ring pixel', alone[cy, cx+rv-1]))
        r, gr, b = alone[cy, cx+round(0.8*rv)-1]
        self.assertTrue(r > 200 and gr > 190 and b < 80, ('inner ring pixel', alone[cy, cx+round(0.8*rv)-1]))
        self.assertEqual(tuple(alone[cy, cx]), grey, 'the body inside the ring is untouched')
        self.assertEqual(tuple(alone[cy, cx+round(0.9*rv)]), grey, 'between the rings is untouched')
        tip = cx-round(1.12*rv)-2                                      # just behind the left chevron's tip
        r, gr, b = alone[cy, tip]
        self.assertTrue(r > 150 and gr > 140 and b < 120, ('chevron', alone[cy, tip]))
        self.assertEqual(tuple(alone[cy, cx-round(1.6*rv)]), grey, 'nothing beyond the chevrons')
        both, _ = image(1, 1, 1, grey); bars_only, _ = image(1, 1, 0, grey); ring_only, _ = image(0, 0, 1, grey)
        bar_pixels = np.any(bars_only != np.array(grey), axis=2)
        ring_pixels = np.any(ring_only != np.array(grey), axis=2)
        self.assertGreater(int(ring_pixels.sum()), 1500, 'the ring is drawn')
        self.assertTrue(np.array_equal(both[bar_pixels], bars_only[bar_pixels]), 'every bar pixel is intact over the ring')
        self.assertTrue(np.array_equal(both[~bar_pixels], ring_only[~bar_pixels]), 'elsewhere the ring is unchanged')


class IndicatorTests(unittest.TestCase):
    """beta.39: the gold arrow is the default indicator, the ring an option (ring / both); the ring follows the
    target's on-screen size per view; QMARKER draws the same indicator in quad views without the overhead bars."""
    machine = MarkerTests.machine
    run_marker = MarkerTests.run_marker
    expect = MarkerTests.expect
    radius = staticmethod(MarkerTests.radius)

    def draw(self, c, entry=None):
        c.events.clear(); c.packets.clear(); c.r[31] = 0xFEED0000; c.r[29] = 0x1FFFF00
        saved = list(c.r[16:24])
        c.run(sel.MARKER if entry is None else entry)
        self.assertEqual((c.r[16:24], c.r[29], c.saved_matrix), (saved, 0x1FFFF00, []))
        return list(c.packets)

    def arrow_tip(self, packet):
        """The packed tip of an arrow packet: the template with the same tip added to every XYZ2 low word."""
        template = sel.packet_template()
        self.assertEqual(len(packet), len(template))
        tip = (struct.unpack_from('<I', packet, 120)[0]-struct.unpack_from('<I', template, 120)[0]) & 0xFFFFFFFF
        expected = bytearray(template)
        for k in range(len(sel.ARROW_VERTICES)):
            at = 112+8+16*k
            struct.pack_into('<I', expected, at, (struct.unpack_from('<I', template, at)[0]+tip) & 0xFFFFFFFF)
        self.assertEqual(packet, bytes(expected))
        return tip & 0xFFFF, tip >> 16

    def test_settings_default_to_the_arrow_and_old_files_get_it(self):
        self.assertEqual(mod_settings.validate_settings({})[sel.STYLE_KEY], 'arrow')
        self.assertEqual(sel.STYLES, {'arrow': 1, 'ring': 2, 'both': 3})
        self.assertEqual(sel.effective(settings())['style'], 1)
        self.assertEqual(sel.effective(settings(lockon_target_style='both'))['style'], 3)
        self.assertEqual(sel.effective(settings(lockon_target_marker=False, lockon_target_style='ring'))['style'], 0)
        with self.assertRaises(ValueError): mod_settings.validate_settings({sel.STYLE_KEY: 'square'})
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'mod-settings.json'
            path.write_text(json.dumps(dict(lockon_target_marker=True)), encoding='utf-8')
            self.assertEqual(mod_settings.load_settings(path)[sel.STYLE_KEY], 'arrow', 'a beta.38 file gets the arrow')
        self.assertNotIn(sel.STYLE_KEY, sel.LEGACY)

    def test_the_arrow_alone_is_the_beta37_dart_above_the_head_drawn_before_the_bars(self):
        c = self.machine(style=1)
        [packet] = self.draw(c)
        self.assertEqual(c.events, ['push', 'sprite', 'pop', 'bars'])
        x16, y16 = self.arrow_tip(packet)
        self.assertEqual(x16, (256+1792)*16)
        self.assertLess(y16, (224+1824)*16-sel.TIP_GAP*16, 'above the lifted head, dropping in (10 px)')
        c.w(FRAMES, 1000)
        [rest] = self.draw(c)
        self.assertEqual(self.arrow_tip(rest)[1]-y16, 10*16, 'at rest the drop-in lift is gone')

    def test_both_draws_the_arrow_then_the_ring(self):
        c = self.machine(style=3)
        packets = self.draw(c)
        self.assertEqual(len(packets), 2); self.arrow_tip(packets[0])
        self.assertEqual(packets[1], self.expect(256, 224, 0))
        self.assertEqual(c.events, ['push', 'sprite', 'sprite', 'pop', 'bars'])
        self.assertEqual(counter(c, 'markers'), 2)

    def test_the_quad_entry_draws_the_indicator_without_the_overhead_bars(self):
        for style in (1, 2, 3):
            c = self.machine(style=style)
            packets = self.draw(c, sel.QMARKER)
            self.assertEqual(len(packets), 2 if style == 3 else 1, style)
            self.assertNotIn('bars', c.events, style)
            if style & 2: self.assertEqual(packets[-1], self.expect(256, 224, 0))
        c = self.machine(marker=0)
        self.assertEqual((self.draw(c, sel.QMARKER), c.events), ([], []), 'marker off: nothing, not even bars')

    def test_the_ring_follows_the_targets_on_screen_size_and_is_clamped_per_view(self):
        for lift, view, want in ((200, (0, 511, 0, 447), 546), (100, (0, 511, 0, 447), 450), (40, (0, 511, 0, 447), 189),
                                 (100, (0, 511, 0, 223), 273), (30, (0, 511, 0, 223), 135),
                                 (10, (0, 511, 0, 223), 94)):
            places = [(100, 300, 0), (256, 224, 0), (300, 200, 0), (400, 224, 0), (150, 150, 0), (60, 224, 0)]
            c = self.machine(positions=places, view=view)
            head = BONES[1]; c.w(MODELS[1]+3436+48*4, head)
            c.write(head+64, struct.pack('<4f', 256, 224-lift, 0, 1))
            c.w(FRAMES, 1000); self.draw(c); c.w(FRAMES, 1100)
            [packet] = self.draw(c)
            self.assertEqual((counter(c, 'size_h'), counter(c, 'size_r')), (lift*16, want), (lift, view))
            self.assertEqual(packet, self.expect(256, 224-lift//2, None, view, h=lift*16), (lift, view))

    def test_the_quad_extension_list_gains_one_qmarker_call_per_view_pair(self):
        import viewport_hud as hud
        base = views.draw(())
        added = views.draw(((sel.CONTROL, sel.MAGIC, sel.QMARKER),))
        self.assertEqual(sum(added[i:i+4] == sel.jal(sel.QMARKER) for i in range(0, len(added), 4)), 2)
        self.assertLessEqual(len(added), views.SELECT-views.DRAW)
        self.assertEqual([len(threat.quad_sites(d, views.DRAW, A(0x102708))) for d in (base, added)], [2, 2],
                         'the threat marks still find both world-effects links')


def no_synthetic_release(test, physical, seen, bits=sel.STICK | R3 | L3):
    """A bit the actor sees may only fall when the physical input falls (a real release)."""
    for k in range(1, len(physical)):
        fell = seen[k-1] & ~seen[k] & physical[k] & bits
        test.assertFalse(fell, f'synthetic release {fell:#x} at {k}: {[hex(p) for p in physical]} -> {[hex(v) for v in seen]}')


OTHER_BITS = (0x1000, 0x2000, 0x4000, 0x8000, 0x800, 0x400, 0x100, 0x10, 0x40, 0x1, 0x8)


class StickAloneTests(unittest.TestCase):
    """The right stick alone (CONTROL+12 = 2): only while locked on in active combat; every owned deflection is
    masked until neutral; one aim per flick after two neutral updates, committed on the next update; R3 wins."""
    def setUp(self): self.places = ring((1, 90), (3, 30), (5, 150))

    def m(self, **kw):
        kw.setdefault('positions', self.places); kw.setdefault('stick', 2)
        return follow_camera(make(**kw))

    def test_flick_needs_two_neutral_updates_commits_next_update_one_per_flick(self):
        c = self.m(); walk = expected_walk(self.places, 6, 1)
        press(c, RIGHT); press(c, 0); press(c, RIGHT); self.assertEqual(target(c), 1, 'one neutral since reset: no aim')
        press(c, 0, 2); press(c, RIGHT); self.assertEqual(target(c), 1, 'the edge only pends')
        press(c, RIGHT); self.assertEqual(target(c), walk[0], 'committed on the next update')
        press(c, RIGHT, 30); self.assertEqual(target(c), walk[0], 'held: no repeat')
        press(c, 0, 2); press(c, LEFT); press(c, 0); self.assertEqual(target(c), 1, 'a single-update flick still aims')
        self.assertEqual(counter(c, 'steps'), 2)
        press(c, 0, 2); press(c, RIGHT); press(c, 0); press(c, RIGHT); press(c, 0); press(c, RIGHT); press(c, 0, 3)
        self.assertEqual(counter(c, 'steps'), 3, 'threshold chatter with single neutral updates aims once')
        self.assertEqual((counter(c, 'release_unlocks'), c.u(row(c)+off.OFF)), (0, 0))

    def test_up_down_pick_the_enemy_above_or_below_the_target(self):
        places = [(100, 300, 0), (256, 224, 0), (0, 0, 0), (270, 150, 0), (0, 0, 0), (400, 200, 0)]
        c = make(positions=places, stick=2); press(c, 0, 3)
        press(c, UP, 2); press(c, 0, 2); self.assertEqual(target(c), 3)
        press(c, DOWN, 2); press(c, 0, 2); self.assertEqual(target(c), 1, 'from 3, 1 is below it')
        self.assertEqual(counter(c, 'aims'), 2)

    def test_ownership_masks_every_owned_deflection_and_never_r3(self):
        cases = {
            'flick held': ([0, 0, RIGHT, RIGHT, RIGHT, 0], [0, 0, 0, 0, 0, 0], 1),
            'sweep': ([0, 0, RIGHT, UP, UP, 0], [0, 0, 0, 0, 0, 0], 1),
            'chatter owned too': ([0, 0, RIGHT, 0, RIGHT, 0], [0, 0, 0, 0, 0, 0], 1),
            'R3 mid flick passes': ([0, 0, RIGHT, RIGHT | R3, R3, 0], [0, 0, 0, R3, R3, 0], 0),
            'R3 held then stick': ([0, 0, R3, R3 | RIGHT, R3 | RIGHT, R3, 0], [0, 0, R3, R3, R3, R3, 0], 0),
            'L3 habit': ([0, 0, L3, L3 | RIGHT, L3, 0], [0, 0, L3, L3, L3, 0], 1),
        }
        for name, (script, expect, steps) in cases.items():
            c = self.m(); seen = run_script(c, script)
            no_synthetic_press(self, script, seen); no_synthetic_release(self, script, seen)
            self.assertEqual(seen, expect, name)
            self.assertEqual(counter(c, 'steps'), steps, name)

    def test_r3_rules_are_defined_by_the_last_update_r3_was_down(self):
        # R3 down at the edge, or last down 1 or 2 updates before it: no aim; last down 3 updates before: aim.
        for last_down, aims in ((0, False), (1, False), (2, False), (3, True)):
            c = self.m(); press(c, 0, 3)
            if last_down == 0: script = [R3 | RIGHT, R3 | RIGHT, 0]
            else: script = [R3]+[0]*(last_down-1)+[RIGHT, RIGHT, 0]
            t0 = target(c); seen = run_script(c, script)
            self.assertEqual(target(c) != t0, aims, last_down)
            self.assertEqual([w & R3 for w in seen], [w & R3 for w in script], 'R3 always reaches the game')
        c = self.m(); press(c, 0, 3); t0 = target(c); seen = run_script(c, [RIGHT, RIGHT | R3, R3, 0])
        self.assertEqual((target(c), seen), (t0, [0, R3, R3, 0]), 'R3 on the commit update cancels the aim and passes')
        c = self.m(); press(c, 0, 3); t0 = target(c); seen = run_script(c, [RIGHT, RIGHT, RIGHT | R3, R3, 0])
        self.assertNotEqual(target(c), t0); self.assertEqual(seen, [0, 0, R3, R3, 0], 'aimed, then R3 passes')

    def test_every_closed_gate_leaves_the_stick_native_and_aims_nothing(self):
        import rush_cinematics as rush
        cam = 0x1950000
        cases = {
            'intro': lambda c, on: c.w(BATTLE, 2 if on else 3),
            'result': lambda c, on: c.w(0x333700, int(on)),
            'cinematic': lambda c, on: (c.w(0x2FEBCC, cam), c.w(cam+812, int(on))),
            'rush': lambda c, on: (c.w(rush.CONTROL, rush.MAGIC),
                                   c.callbacks.__setitem__(rush.OWNER, lambda m, v=int(on): m.r.__setitem__(2, v))),
            'transform 236': lambda c, on: c.w(ACTORS[0]+0x948, 236 if on else 11),
            'transform 243': lambda c, on: c.w(ACTORS[0]+0x948, 243 if on else 11),
            'paired 301': lambda c, on: c.w(ACTORS[0]+0x948, 301 if on else 11),
            'paired 313': lambda c, on: c.w(ACTORS[0]+0x948, 313 if on else 11),
            'paired 183': lambda c, on: c.w(ACTORS[0]+0x948, 183 if on else 11),
            'paired 187': lambda c, on: c.w(ACTORS[0]+0x948, 187 if on else 11),
            'pair word': lambda c, on: c.w(core.PAIR+4, int(on)),
        }
        for name, setter in cases.items():
            c = self.m(); press(c, 0, 3); setter(c, True)
            seen = run_script(c, [RIGHT, RIGHT, 0, 0])
            if name != 'pair word': self.assertEqual(seen, [RIGHT, RIGHT, 0, 0], name)
            self.assertEqual((counter(c, 'steps'), counter(c, 'masked')), (0, 0), name)
            press(c, RIGHT); setter(c, False); press(c, RIGHT, 3)
            if name != 'pair word':
                self.assertEqual((target(c), visible(c)), (1, RIGHT), name+': a stick held as the gate opens stays native')
            press(c, 0, 2); press(c, RIGHT, 2); self.assertNotEqual(target(c), 1, name)
        for action in (244, 188, 235, 300):                     # just outside the closed spans: open
            c = self.m(); c.w(ACTORS[0]+0x948, action); press(c, 0, 3); press(c, RIGHT, 2)
            self.assertNotEqual(target(c), 1, action)

    def test_a_gate_closing_between_the_edge_and_the_commit_cancels_the_aim(self):
        c = self.m(); press(c, 0, 3); press(c, RIGHT); c.w(BATTLE, 2); press(c, RIGHT); c.w(BATTLE, 3); press(c, RIGHT, 2)
        self.assertEqual(target(c), 1, 'cancelled when the gate closes before the commit')
        self.assertEqual(visible(c), 0, 'the owned flick stays masked until neutral across the closed gate')
        press(c, 0); self.assertEqual(visible(c), 0); press(c, 0); press(c, RIGHT, 2)
        self.assertNotEqual(target(c), 1, 'the next flick aims')

    def test_unlocked_the_stick_is_the_camera_a_tap_relocks_and_lock_off_fires_while_held(self):
        places = [(100, 300, 0), (230, 224, 0), (0, 0, 0), (400, 224, 0), (0, 0, 0), (100, 224, 0)]
        c = make(positions=places, stick=2)
        press(c, L3, 15); self.assertEqual(c.u(row(c)+off.OFF), 1, 'lock-off fires while held (beta.33 timing)')
        press(c, 0); self.assertEqual((c.u(row(c)+off.OFF), counter(c, 'release_unlocks')), (1, 0))
        press(c, 0, 3); seen = run_script(c, [RIGHT, RIGHT, 0, 0, UP, UP, 0])
        self.assertEqual(seen, [RIGHT, RIGHT, 0, 0, UP, UP, 0], 'unlocked: the stick reaches the game')
        self.assertEqual((c.u(row(c)+off.OFF), counter(c, 'masked'), counter(c, 'release_unlocks')), (1, 0, 0))
        press(c, L3); press(c, 0); self.assertEqual(c.u(row(c)+off.OFF), 0, 'a tap relocks')

    def test_the_hold_mode_habit_gives_one_aim_and_a_swallowed_release(self):
        c = self.m(threshold=15); press(c, 0, 3)
        run_script(c, [L3, L3 | RIGHT, L3 | RIGHT, L3, 0, 0])
        self.assertEqual((c.u(q.CONTROL+q.FIELDS['switches']), c.u(row(c)+off.OFF)), (1, 0))
        self.assertEqual(counter(c, 'release_unlocks'), 0)

    def test_r3_as_the_switch_button(self):
        c = self.m(button=R3, off_button=L3); press(c, 0, 3)
        t0 = target(c); press(c, R3); press(c, 0); self.assertNotEqual(target(c), t0, 'an R3 tap switches')
        press(c, 0, 2); t1 = target(c); press(c, RIGHT, 2); press(c, 0, 2)
        self.assertNotEqual(target(c), t1, 'the stick alone aims with R3 as the switch button')
        script = [R3, R3 | RIGHT, R3 | RIGHT, R3, 0, 0, 0]
        before = (counter(c, 'steps'), counter(c, 'aims'))
        seen = run_script(c, script)
        no_synthetic_press(self, script, seen); no_synthetic_release(self, script, seen)
        self.assertEqual(seen, [R3, R3, R3, R3, 0, 0, 0], 'owned stick masked, R3 visible')
        self.assertEqual((counter(c, 'steps')-before[0], counter(c, 'aims')-before[1]), (1, 0),
                         'holding R3 suspends aiming; its release is an ordinary switch')

    def test_the_confirm_fallback(self):
        c = self.m(); c.w(sel.CONTROL+sel.FIELDS['confirm'], 1); press(c, 0, 3)
        press(c, RIGHT); press(c, 0); self.assertEqual(target(c), 1, 'confirm: a one-update brush does not aim')
        press(c, 0, 2); press(c, RIGHT, 2); self.assertNotEqual(target(c), 1)

    def test_a_record_change_drops_the_owned_flick(self):
        c = self.m(); press(c, 0, 3); press(c, RIGHT)
        self.assertEqual((c.u(own(c)+sel.STICK_LATCH), c.u(own(c)+sel.PENDING), visible(c)), (1, RIGHT, 0))
        press(c, RIGHT); t0 = target(c); self.assertNotEqual(t0, 1)
        c.w(own(c)+sel.MASK_REC, RECORDS+448)                    # the actor's record moved (a co-op control swap)
        press(c, RIGHT)
        self.assertEqual([c.u(own(c)+f) for f in (sel.STICK_LATCH, sel.PENDING, sel.MASK_BITS)], [0, 0, 0])
        self.assertEqual(visible(c), RIGHT, 'the new record is not masked')
        press(c, RIGHT, 3); self.assertEqual((target(c), visible(c)), (t0, RIGHT), 'native until neutral, no aim')

    def test_pressed_words_never_carry_a_masked_bit_with_the_real_quad_frame(self):
        pads = [RECORDS, RECORDS+448, quad.PADS, quad.PADS+448]
        places = [CENTRE, polar(90, 60, CENTRE), polar(270, 60, CENTRE), polar(30, 80, CENTRE), polar(200, 60, CENTRE),
                  polar(150, 60, CENTRE)]
        c = follow_camera(make(positions=places, humans=(0, 2), resolver=0x1DC2A0, targets=[1, 0, 1, 0, 1, 0], stick=2))
        c.callbacks[0x1DC2A0] = lambda m: m.r.__setitem__(2, pads[m.u(m.r[4])])
        c.write(quad.FRAME, quad.frame(QUAD_NEXT)); c.write(quad.CONTROL, struct.pack('<4I', quad.MAGIC, MANAGER, 6, 1))
        sequence = [0]

        def update(p1, p3):
            kept = c.u(RECORDS+332)
            c.write(RECORDS+328, struct.pack('<4I', p1, p1, p1 & ~kept, p1 & ~kept))
            if p3 is not None:
                sequence[0] += 1; c.write(quad.MAILBOX, struct.pack('<I4f12x', p3, 0, 0, 0, 0)); c.w(quad.CONTROL+16, sequence[0])
            c.r[29] = 0x1FFFF00; c.r[31] = 0xFEED0000
            self.assertEqual(c.run(quad.FRAME, stops=(QUAD_NEXT,)), QUAD_NEXT)
            frame(c)
            for record in (RECORDS, quad.PADS):
                held = c.u(record+328)
                for word in PRESSED_WORDS:
                    self.assertFalse(c.u(record+word) & ~held & (sel.STICK | R3), (hex(record), word, p1, p3))
        for p1, p3 in ((0, 0), (0, 0), (0, 0), (RIGHT, RIGHT), (RIGHT, None), (RIGHT, None), (RIGHT | R3, RIGHT | R3),
                       (RIGHT | R3, None), (RIGHT, RIGHT), (0, None), (0, 0), (0, 0), (UP, UP), (UP, None), (0, 0)):
            update(p1, p3)
        self.assertEqual(counter(c, 'steps'), 2, 'each seat stepped once')
        self.assertGreaterEqual(counter(c, 'restored'), 1, 'the stale P3 updates kept the mask')

    def test_random_scripts_touch_only_stick_bits_and_never_fake_a_press_or_release(self):
        rng = random.Random(11); retargets = 0
        for trial in range(300):
            c = self.m(); script = []
            gate = rng.random() < .5
            for k in range(40):
                w = rng.choice((0, 0, 0, RIGHT, LEFT, UP, DOWN)) | (R3 if rng.random() < .2 else 0) \
                    | (L3 if rng.random() < .15 else 0) | (rng.choice(OTHER_BITS) if rng.random() < .4 else 0)
                script.append(w)
            seen = []
            for w in script:
                if gate and rng.random() < .15: c.w(BATTLE, rng.choice((2, 3)))
                press(c, w); seen.append(visible(c))
                self.assertEqual(c.u(own(c)+sel.MASK_BITS) & ~sel.STICK, 0, 'the stick alone masks only stick bits')
            no_synthetic_press(self, script, seen); no_synthetic_release(self, script, seen)
            for p, v in zip(script, seen): self.assertEqual(p & ~sel.STICK, v & ~sel.STICK)
            retargets += counter(c, 'steps')+counter(c, 'aims')
        self.assertGreater(retargets, 300)

    def test_random_scripts_follow_an_independent_model_while_every_gate_toggles(self):
        """Every update against a model of the stick-alone rules (INPUT2 step 4 of the design): whether it aims, in which
        direction, and what the actor sees, while the battle state, the result screen, the lock, the own action, the
        cinematic camera and the shared rush close and open the gate at random (with and without the confirm word)."""
        import rush_cinematics as rush
        cam = 0x1950000

        class Model:
            def __init__(self, confirm):
                self.grace = self.pending = self.latch = self.armed = self.mask = 0
                self.confirm = confirm

            def update(self, w, gate):
                old, self.grace = self.grace, 2 if w & R3 else max(self.grace-1, 0)
                t5, aim = w & sel.STICK, 0
                if self.pending:
                    d, self.pending = self.pending, 0
                    if gate and not w & R3 and (not self.confirm or t5): aim = d
                if not t5:
                    self.latch, self.armed = 0, min(self.armed+1, 2)
                else:
                    if not self.latch and self.armed and gate:
                        self.latch = 1
                        if self.armed >= 2 and not w & R3 and old == 0: self.pending = t5
                    self.armed = 0
                self.mask = (self.mask & w) | (t5 if self.latch else 0)
                return aim, w & ~self.mask

        rng = random.Random(23); aims = 0
        reasons = ('battle', 'result', 'unlocked', 'action', 'cinematic', 'rush')
        for trial in range(160):
            confirm = int(trial % 4 == 3)
            c = self.m(after_ko=0, threshold=10000); c.w(sel.CONTROL+sel.FIELDS['confirm'], confirm)
            owner = [0]; c.w(rush.CONTROL, rush.MAGIC)
            c.callbacks[rush.OWNER] = lambda m: m.r.__setitem__(2, owner[0])
            model = Model(confirm); press(c, 0); model.update(0, True)
            for k in range(50):
                reason = rng.choice(reasons) if rng.random() < .25 else None
                c.w(BATTLE, 2 if reason == 'battle' else 3); c.w(0x333700, int(reason == 'result'))
                c.w(row(c)+off.OFF, int(reason == 'unlocked'))
                c.w(ACTORS[0]+0x948, rng.choice((236, 243, 301, 183)) if reason == 'action' else 11)
                c.w(0x2FEBCC, cam if reason == 'cinematic' else 0); c.w(cam+812, 1)
                owner[0] = int(reason == 'rush')
                w = rng.choice((0, 0, 0, RIGHT, LEFT, UP, DOWN, RIGHT | UP)) | (R3 if rng.random() < .15 else 0) \
                    | (rng.choice(OTHER_BITS) if rng.random() < .3 else 0)
                queued = c.u(q.CONTROL+q.FIELDS['queued']); press(c, w)
                aim, seen = model.update(w, reason is None)
                state = (trial, k, hex(w), reason, confirm)
                self.assertEqual(c.u(q.CONTROL+q.FIELDS['queued'])-queued, int(bool(aim)), state)
                if aim: self.assertEqual((c.u(row(c)+off.KIND), c.u(own(c)+sel.ARG)), (4, aim), state)
                self.assertEqual(visible(c), seen, state)
                aims += bool(aim)
        self.assertGreater(aims, 150)

    def test_memory_writes_stay_inside_the_owned_state(self):
        c = self.m(); press(c, 0)
        allowed = [(core.TABLE, core.TABLE+48), (off.ROWS, off.ROWS+12*off.STRIDE), (sel.ROWS, sel.END),
                   (sel.CONTROL, sel.CONTROL+0x100), (ls.CONTROL, ls.CONTROL+0x400), (RECORDS+328, RECORDS+344),
                   (0x1FF0000, 0x2000000)]
        before = dict(c.memory)
        for word in (0, 0, RIGHT, RIGHT, 0, UP | R3, R3, 0, L3, 0, 0, 0, LEFT, 0, 0, 0, DOWN, DOWN, 0):
            edge = word & ~c.u(RECORDS+332); c.write(RECORDS+332, struct.pack('<3I', word, edge, edge)); press(c, word)
        changed = {a for a, v in c.memory.items() if before.get(a, 0) != v}
        stray = sorted(a for a in changed if not any(lo <= a < hi for lo, hi in allowed))
        self.assertEqual(stray, [], [hex(a) for a in stray[:8]])
        self.assertTrue(sel.ROWS < sel.MARKS and sel.MARKS+8*modes.ENGINE_ACTORS <= sel.END)


class HoldModeR3Tests(unittest.TestCase):
    """Hold mode (1): R3 is masked inside the latch only when it is newly pressed there."""
    def test_r3_held_before_the_aim_is_never_released_synthetically(self):
        places = ring((1, 90), (3, 30), (5, 150))
        for button in (L3, 0x100):
            c = follow_camera(make(positions=places, button=button, off_button=L3))
            script = [0, R3, R3 | button, R3 | button | RIGHT, R3 | button | RIGHT, R3 | button, R3, 0]
            seen = run_script(c, script)
            no_synthetic_release(self, script, seen, bits=R3); no_synthetic_press(self, script, seen)
            self.assertEqual([w & R3 for w in seen], [w & R3 for w in script], button)
            self.assertEqual(counter(c, 'steps'), 1, button)
