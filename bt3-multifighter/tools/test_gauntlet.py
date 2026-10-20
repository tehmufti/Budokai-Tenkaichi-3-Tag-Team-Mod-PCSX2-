"""Fighter Gauntlet: data file, validator, wave plan, run plan, story mission and the guest program.

The guest tests interpret the emitted MIPS (test_ai_shadow.Mips) over a small synthetic match: actors, models,
HP rows, the story and participation words. Native calls are stubbed and recorded.
"""
# BT4 fighter names come from the chosen disc's extracted roster (assets/characters.json), which a source
# checkout does not contain.
import unittest as _TestUnit
import gauntlet_data as _TestData
if _TestData.family() == 'bt4' and not _TestData._names_bt4():
    raise _TestUnit.SkipTest('The BT4 gauntlet tests need the disc roster (assets/characters.json)')
import copy
import json
import struct
import tempfile
import unittest
from pathlib import Path

import gauntlet_data as data
import gauntlet_mode as mode
import gauntlet_runtime as rt
import story_missions
from test_ai_shadow import Mips


# ---------------------------------------------------------------- data, validator, plan
def doc(*gauntlets, game=None):
    game = game or data.family()
    return dict(schema=1, games={game: dict(roster=data.default_roster(game), potara=data.builtin_potara())},
                gauntlets=list(gauntlets))


def gauntlet(gid='g', waves=None, **extra):
    waves = waves if waves is not None else [dict(label='Guldo', fighters=[dict(id=90, costume=0, potara=[], buffed=False)])]
    return dict(id=gid, title=gid.upper(), game=data.family(), category='saga', waves=waves, **extra)


def wave(*ids, **extra):
    return dict(label=extra.pop('label', ''), fighters=[dict(id=i, costume=0, potara=[], buffed=False) for i in ids],
                **extra)


class DataTests(unittest.TestCase):
    def test_tree_file_is_valid(self):
        game = data.family()
        for path in (data.PATH,):
            if not path.exists():
                continue
            usable, problems, _, _ = data.validate(json.loads(path.read_text(encoding='utf-8')), game)
            self.assertFalse(problems, problems[:3])
            self.assertTrue(any(g['category'] == 'test' and len(g['waves']) == 3 for g in usable))
            self.assertTrue(all(g['game'] == game for g in usable))

    def test_validator_reports_and_keeps_the_good_gauntlets(self):
        bad = [gauntlet('ok'), gauntlet('unknown', [wave(999)]), gauntlet('costume', [dict(label='', fighters=[
            dict(id=90, costume=7, potara=[], buffed=False)])]), gauntlet('items', [dict(label='', fighters=[
                dict(id=90, costume=0, potara=[12345], buffed=False)])]), gauntlet('big', [wave(90, 84, 82, 13, 25, 22)]),
               gauntlet('empty', []), gauntlet('ok'), dict(gauntlet('otheronly'), game='bt4' if data.family() == 'bt3' else 'bt3')]
        usable, problems, _, _ = data.validate(doc(*bad), data.family())
        self.assertEqual([g['id'] for g in usable], ['ok'])
        reasons = dict(problems)
        self.assertIn('unknown fighter', reasons['unknown'])
        self.assertIn('costume', reasons['costume'])
        self.assertIn('Potara', reasons['items'])
        self.assertIn('1..5', reasons['big'])
        self.assertIn('waves', reasons['empty'])
        self.assertIn('duplicate', reasons['ok'])
        self.assertNotIn('otheronly', reasons)          # another game's gauntlets are simply not offered

    def test_schema_and_shape_errors(self):
        with self.assertRaises(data.GauntletError):
            data.validate(dict(schema=2, gauntlets=[]), data.family())
        with self.assertRaises(data.GauntletError):
            data.validate(dict(schema=1, gauntlets={}), data.family())

    def test_load_falls_back_to_builtin_and_always_has_the_test_gauntlet(self):
        with tempfile.TemporaryDirectory() as folder:
            game = data.family()
            missing = data.load(game, Path(folder) / 'none.json')
            self.assertEqual(missing['source'], 'built-in')
            self.assertIn(f'quick_test_{game}', {g['id'] for g in missing['gauntlets']})
            broken = Path(folder) / 'broken.json'; broken.write_text('{nope', encoding='utf-8')
            loaded = data.load(game, broken)
            self.assertEqual(loaded['source'], 'built-in'); self.assertTrue(loaded['problems'])
            only = Path(folder) / 'only.json'
            only.write_text(json.dumps(doc(dict(gauntlet('mine'), game=game), game=game)), encoding='utf-8')
            loaded = data.load(game, only)
            self.assertEqual([g['id'] for g in loaded['gauntlets']], [f'quick_test_{game}', 'mine'])

    def test_builtin_samples(self):
        for game in (data.family(),):
            usable, problems, _, _ = data.validate(data.builtin(game), game)
            self.assertFalse(problems)
            test = next(g for g in usable if g['category'] == 'test')
            self.assertEqual(len(test['waves']), 3)
        if data.family() == 'bt3':
            namek = next(g for g in data.validate(data.builtin('bt3'), 'bt3')[0] if g['id'] == 'namek_saga_sample_bt3')
            labels = [w['label'] for w in namek['waves']]
            self.assertEqual(len(labels), 13)
            self.assertEqual(labels[0], 'Cui'); self.assertEqual(labels[-1], 'FINAL: Super Saiyan Goku')
            self.assertEqual([f['character'] for f in namek['waves'][4]['fighters']], [86, 87, 88, 89, 90])

    def test_grouped_order(self):
        items = [dict(gauntlet(c + '1'), category=c) for c in ('roster', 'saga', 'test', 'zzz')]
        usable, _, _, _ = data.validate(doc(*items), data.family())
        self.assertEqual([title for title, _ in data.grouped(usable)], ['Test', 'Sagas', 'Rosters', 'Zzz'])


class PlanTests(unittest.TestCase):
    def test_difficulty_ramp(self):
        levels = [data.difficulty(i, 13) for i in range(13)]
        self.assertEqual(levels[0], 1); self.assertEqual(levels[-1], 4)
        self.assertEqual(levels, sorted(levels)); self.assertNotIn(0, levels)
        self.assertEqual(data.difficulty(0, 1), 4)
        self.assertEqual([data.difficulty(i, 3) for i in range(3)], [1, 3, 4])   # 1 + round(3p)
        self.assertEqual(data.difficulty(5, 13, dict(difficulty=0)), 0)          # an explicit override wins
        self.assertEqual(data.difficulty(5, 13, dict(cpu=0)), 1)                 # the editor's curve, never Very Easy
        self.assertEqual(data.difficulty(5, 13, dict(cpu=3)), 3)

    def test_halfway(self):
        self.assertEqual(data.halfway(13), 6); self.assertEqual(data.halfway(2), 1); self.assertEqual(data.halfway(1), 0)
        self.assertEqual(data.halfway(10, dict(buff_from=0.75)), 7)

    def test_buffs_from_halfway_solo_strongest(self):
        g = data.validate(doc(gauntlet('g', [wave(90), wave(84, 82), wave(91), wave(13, 25, 22), wave(95)])), data.family())[0][0]
        plan = data.plan(g)
        self.assertFalse(plan[0]['buffed']); self.assertFalse(plan[1]['buffed'])
        self.assertEqual(plan[0]['enemies'][0]['damage'], 1.0)
        self.assertTrue(plan[2]['buffed'])
        solo, group, boss = plan[2]['enemies'][0], plan[3]['enemies'][0], plan[4]['enemies'][0]
        self.assertTrue(solo['auto_items']); self.assertTrue(group['auto_items'])
        self.assertGreater(solo['damage'], group['damage']); self.assertGreater(solo['defense'], group['defense'])
        self.assertGreater(solo['extra_hp'], group['extra_hp'])
        self.assertIn(322, boss['items'])                   # the final wave gets the +30,000 health item
        self.assertGreaterEqual(boss['extra_hp'], 30000)

    def test_given_items_and_buffed_flag(self):
        f = dict(id=90, costume=1, potara=[2, 5, 322], buffed=True)
        g = data.validate(doc(gauntlet('g', [dict(label='x', fighters=[f]), wave(84)])), data.family())[0][0]
        e = data.plan(g)[0]['enemies'][0]
        self.assertFalse(e['auto_items']); self.assertEqual(e['items'], [2, 5, 322]); self.assertEqual(e['costume'], 1)
        self.assertAlmostEqual(e['damage'], round(1.15 * 1.10, 3)); self.assertAlmostEqual(e['defense'], round(1.15 * 1.10, 3))
        self.assertEqual(e['extra_hp'], 30000)

    def test_item_effects_parse(self):
        potara = {x['id']: x for x in data.builtin_potara()}
        potara[900] = dict(id=900, effect='Minus: Max Health is reduced by 10000.', stats=[0, 0, 0, 0])
        self.assertEqual(data.item_effects([0, 3, 9, 322, 900], potara), (1 + 0.05 + 0.025, 1.05, 20000))

    def test_refill(self):
        self.assertEqual(data.refill_amount('quarter', 40000), 2500)
        self.assertEqual(data.refill_amount('bar', 40000), 10000)
        self.assertEqual(data.refill_amount('full', 37000), 37000)
        self.assertEqual(data.refill_amount('off', 40000), 0)


class RunPlanTests(unittest.TestCase):
    def setUp(self):
        waves = [(90,), (84, 82), (13, 25), (29,), (86, 87, 88, 89, 90), (91,), (22, 13, 25), (92,), (93,), (94,), (1,),
                 (95,), (2,)]
        self.namek = data.validate(doc(gauntlet('namek', [wave(*w) for w in waves])), data.family())[0][0]
        self.players = [(3, 0, '00' * 16), (23, 0, '00' * 16), (25, 1, '00' * 16)]

    def run_plan(self, players=None, humans=1, refill='half'):
        return mode.run_plan(self.namek, None, mode.Setup(self.namek, humans, 3, refill), players or self.players)

    def test_roster_wave1_preloads_and_free_slots(self):
        run = self.run_plan()
        self.assertEqual(run['roster'][1]['enemy']['character'], 90)                       # the native leader
        self.assertEqual({p: (r['wave'], r['state']) for p, r in run['roster'].items() if p != 1},
                         {3: (2, rt.READY), 5: (2, rt.READY), 7: (3, rt.READY), 9: (3, rt.READY)})
        self.assertEqual(run['wave_mask'], 1 << 1); self.assertEqual(run['player_mask'], 0b10101)
        self.assertEqual(run['gate_mask'], sum(1 << p for p in (3, 5, 7, 9)))
        self.assertEqual(run['refill'], 5000)
        self.assertEqual(run['slots'][3]['hp'], 0)       # a preloaded fighter keeps its native health

    def test_resource_budget_limits_preloads(self):
        five = [(3, 0, ''), (23, 0, ''), (25, 1, ''), (29, 0, ''), (22, 0, '')]
        run = self.run_plan(five)
        loaded = {(r['enemy']['character'], r['enemy']['costume']) for p, r in run['roster'].items() if p != 1}
        self.assertLessEqual(len(loaded | {(c, k) for c, k, _ in five[1:]}), mode.RECORD_BUDGET)
        free = [p for p, r in run['roster'].items() if r['state'] == rt.VANISHED]
        self.assertTrue(free)
        keys = {(c, k) for c, k, _ in five[1:]} | loaded
        self.assertTrue(all((run['roster'][p]['enemy']['character'], run['roster'][p]['enemy']['costume']) in keys
                            and run['roster'][p]['wave'] == 0 for p in free))

    def test_mission_validates_and_holds_the_enemy_side(self):
        run = self.run_plan()
        d = story_missions.validate(mode.mission(run, data.family()))
        enemies = [f for f in d['fighters'] if f['team'] == 2]
        self.assertEqual(len(enemies), 5)
        self.assertTrue(all(f['transformations'] == dict(enabled=False) for f in enemies))
        self.assertEqual([f['reserve'] for f in enemies], [False, True, True, True, True])
        self.assertEqual(len(d['events']), 4)
        self.assertTrue(all(e['when'] == dict(type='time', seconds=86400) for e in d['events']))
        self.assertEqual(d['win_when'], dict(type='time', seconds=86400))
        self.assertTrue(d['menus']['retry']); self.assertIsNone(d['stage'])

    def test_cpu_only_and_settings(self):
        run = self.run_plan(humans=0)
        self.assertEqual(run['humans'], 0)
        s = mode.settings_for(dict(tournament_ring_outs=True, revive_enabled=False, other=1))
        self.assertEqual(s, dict(tournament_ring_outs=False, revive_enabled=True, other=1))

    def test_guest_tables(self):
        run = json.loads(json.dumps(self.run_plan()))
        run['names'] = {90: 'Guldo'}
        waves, strings, pointers = rt.tables(run)
        self.assertEqual(struct.unpack_from('<I', waves)[0], 13)
        count, level, banner = struct.unpack_from('<3I', waves, rt.WAVE_HEADER)
        self.assertEqual((count, level), (1, 1))
        text = lambda ptr: strings[ptr - rt.STRINGS:].split(b'\0')[0].decode()
        self.assertEqual(text(banner), 'WAVE 1 / 13')
        self.assertEqual(text(pointers['text_next']), 'NEXT WAVE')
        self.assertEqual(text(struct.unpack_from('<I', run['_names_blob'], 90 * 4)[0]), 'GULDO')
        ginyu = rt.WAVE_HEADER + rt.WAVE_STRIDE * 4
        self.assertEqual(struct.unpack_from('<I', waves, ginyu)[0], 5)
        self.assertEqual([struct.unpack_from('<I', waves, ginyu + 32 + 20 * k)[0] for k in range(5)], [86, 87, 88, 89, 90])

    def test_strings_have_spanish(self):
        import localization
        texts = [v for k, v in vars(mode).items() if k.isupper() and isinstance(v, str) and ('{' in v or ' ' in v)]
        texts += list(mode.GUEST_TEXTS) + list(mode.REFILL_LABELS) + list(data.CATEGORY_TITLES.values())
        texts += ['Fighter Gauntlet']
        missing = [t for t in texts if t not in localization.ES]
        self.assertFalse(missing, missing)


# ---------------------------------------------------------------- the guest program
import fresh_team_combat as core
import team_participation as part
import story_runtime as story
import guest_killfeed as feed
import team_start_gate as start
import native_preparation as native
import extra_reload_quiet as quiet
from ai_shadow import GP
from native_map import A, ACTOR_HZ

MANAGER = 0x00500000
ACTOR = lambda i: 0x00600000 + i * 0x2000
MODEL = lambda i: 0x00700000 + i * 0x2000
HP = lambda i: ACTOR(i) + 0x9A4 + 0x40     # selected row slot 0 + 0x40


class Guest(Mips):
    instruction_budget = 400000

    def __init__(self, manifest):
        super().__init__(manifest); self.lo = self.hi = 0; self.f = [0] * 32

    def fpu(self, ins):
        """The single-precision subset PLACE uses (lwc1/swc1, mtc1/mfc1, add/sub/mul/div/sqrt/abs, cvt.w.s/cvt.s.w)."""
        op, rs, rt_ = ins >> 26, (ins >> 21) & 31, (ins >> 16) & 31
        fs, fd, fn = (ins >> 11) & 31, (ins >> 6) & 31, ins & 63
        f32 = lambda w: struct.unpack('<f', struct.pack('<I', w & 0xFFFFFFFF))[0]
        w32 = lambda v: struct.unpack('<I', struct.pack('<f', v))[0]
        if op in (49, 57):
            at = (self.r[rs] + ((ins & 0xFFFF) ^ 0x8000) - 0x8000) & 0xFFFFFFFF
            if op == 49:
                self.f[rt_] = self.u(at)
            else:
                self.w(at, self.f[rt_])
            return True
        if op != 17:
            return False
        if rs == 4:
            self.f[fs] = self.r[rt_] & 0xFFFFFFFF
        elif rs == 0:
            self.r[rt_] = self.f[fs]
        elif rs == 16 and fn in (0, 1, 2, 3, 4, 5):
            a, b = f32(self.f[fs]), f32(self.f[rt_])
            value = (a + b, a - b, a * b, a / b if b else float('inf'), abs(b) ** 0.5, abs(a))[fn]
            self.f[fd] = w32(value)
        elif rs == 16 and fn == 6:
            self.f[fd] = self.f[fs]
        elif rs == 16 and fn == 0x24:
            self.f[fd] = int(f32(self.f[fs])) & 0xFFFFFFFF
        elif rs == 20 and fn == 0x20:
            v = self.f[fs]; self.f[fd] = w32(float(v - (1 << 32) if v >> 31 else v))
        else:
            raise AssertionError(f'Unsupported COP1 instruction {ins:08X}')
        return True

    def extra_instruction(self, ins, pc):
        op, fn = ins >> 26, ins & 63
        rs, rt_, rd = (ins >> 21) & 31, (ins >> 16) & 31, (ins >> 11) & 31
        if self.fpu(ins):
            return None
        if op == 0 and fn == 2:
            self.r[rd] = (self.r[rt_] & 0xFFFFFFFF) >> ((ins >> 6) & 31); return None
        if op == 0 and fn == 0x27:
            self.r[rd] = ~(self.r[rs] | self.r[rt_]) & 0xFFFFFFFF; return None
        if op == 0 and fn in (0x18, 0x19):
            a, b = self.r[rs] & 0xFFFFFFFF, self.r[rt_] & 0xFFFFFFFF
            if fn == 0x18:
                a = a - (1 << 32) if a >> 31 else a; b = b - (1 << 32) if b >> 31 else b
            self.lo = (a * b) & 0xFFFFFFFF; self.hi = ((a * b) >> 32) & 0xFFFFFFFF; return None
        if op == 0 and fn == 0x1B:
            a, b = self.r[rs] & 0xFFFFFFFF, self.r[rt_] & 0xFFFFFFFF
            self.lo, self.hi = (a // b, a % b) if b else (0, 0); return None
        if op == 0 and fn == 0x12:
            self.r[rd] = self.lo; return None
        if op == 0 and fn == 0x10:
            self.r[rd] = self.hi; return None
        if op == 0 and fn == 6:
            self.r[rd] = (self.r[rt_] & 0xFFFFFFFF) >> (self.r[rs] & 31); return None
        return super().extra_instruction(ins, pc)


class World:
    """A synthetic captured match: 3 players (0, 2, 4) and the five enemy slots, the gauntlet program installed."""

    def __init__(self, run=None, players=3):
        segments = [dict(address=p, data_hex=d.hex()) for p, d in rt.code_blocks()]
        self.m = Guest(dict(segments=segments))
        m = self.m
        self.calls = []
        count = 10
        m.w(core.MODE, 1); m.w(core.MODE + 4, count); m.w(core.MODE + 8, MANAGER); m.w(core.MODE + 12, count)
        m.w(MANAGER, 2); m.w(GP - 22364, MANAGER)
        self.present = [0, 2, 4][:players] + [1, 3, 5, 7, 9]
        for i in range(count):
            a, mo = ACTOR(i), MODEL(i)
            m.w(core.POINTERS + 4 * i, a); m.w(a, i); m.w(a + 8, i & 1); m.w(a + 12, i)
            m.w(core.MODELS + 4 * i, mo); m.w(mo + 4, 1); m.w(mo + 8, 1); m.w(mo + 12, 100 + i); m.w(mo + 16, i)
            m.w(a + 0x994, 0); m.w(a + 0x998, 1); m.w(a + 0x948, 11); m.w(a + 0x94C, 0xFFFFFFFF)
            m.w(HP(i), 40000 if i in self.present else 0); m.w(HP(i) + 4, 40000)
            m.w(a + 0x1278, 1)
        m.w(story.CONTROL, story.MAGIC); m.w(story.CONTROL + 4, MANAGER)
        self.camera = 0x00900000                     # the cinematic camera record (idle) and intro camera tracks
        m.w(GP - 22180, self.camera)
        for i in range(count):
            m.w(MODEL(i) + 176, 0x00950000 + 0x100 * i)
        c = rt.CONTROL
        m.w(c, rt.MAGIC); m.w(c + 4, MANAGER); m.w(c + 8, count)
        m.w(c + rt.C['gate_mask'], sum(1 << p for p in (3, 5, 7, 9)))
        if run is not None:
            self.install(run)
        for address, name in ((story.ARRIVAL, 'arrival'), (A(0x1BB478), 'difficulty'), (A(0x1E0290), 'action'),
                              (A(0x209EE8), 'intro'), (A(0x24F5D8), 'bank'), (A(0x23DE60), 'camera'),
                              (A(0x265970), 'voice_stop'), (A(0x265E38), 'voice'), (A(0x265F40), 'voice_end'),
                              (A(0x209F20), 'idle'), (A(0x23DCB8), 'camera_end'), (0x07600000, 'io'),
                              (0x07610000, 'stage'), (A(0x23FF78), 'ground')):
            m.callbacks[address] = self.stub(name)

    def stub(self, name):
        def call(m):
            self.calls.append((name, m.r[4], m.r[5]))
            m.r[2] = 1
            if name == 'io':
                status = m.u(0x0760F004); m.w(0x0760F004, 5 if status == 2 else 2)
            if name == 'stage':
                m.w(0x0761F004, 5)
        return call

    def install(self, run):
        m, c = self.m, rt.CONTROL
        waves, strings, pointers = rt.tables(run)
        for at, blob in ((rt.WAVES, waves), (rt.STRINGS, strings)):
            m.write(at, blob)
        timing = dict(rt.DEFAULT_TIMING, countdown=2, vanish=1, overtime=1, step=0.5, tail=0.2, banner=1,
                      release=0.5, give_up=3, getup=0.2, group_step=0.3, intro_wait=1, intro_nopose=0.5, intro_min=0.1)
        values = dict(waves=len(run['waves']), refill=run['refill'], player_mask=run['player_mask'],
                      enemy_mask=run['enemy_mask'], wave_mask=run['wave_mask'], participants=run['participants'],
                      player_team=1, **pointers, **{k: max(1, round(v * ACTOR_HZ)) for k, v in timing.items()})
        for k, v in values.items():
            m.w(c + rt.C[k], v)
        for p, row in run['slots'].items():
            for k, v in row.items():
                m.w(rt.SLOTS + p * rt.SLOT_STRIDE + rt.S[k], v)

    def update(self, n=1):
        for _ in range(n):
            self.m.r[29] = 0x2000000 - 0x100; self.m.r[31] = 0xFEED0000
            self.m.run(rt.UPDATE)

    def word(self, key):
        return self.m.u(rt.CONTROL + rt.C[key])

    def slot(self, p, key):
        return self.m.u(rt.SLOTS + p * rt.SLOT_STRIDE + rt.S[key])

    def ko(self, p):
        self.m.w(HP(p), 0)

    def start_story(self):
        self.m.w(story.CONTROL + 12, 1)


def small_run(waves=((90,), (84, 82), (91,)), refill=2500):
    g = data.validate(doc(gauntlet('t', [wave(*w) for w in waves])), data.family())[0][0]
    run = mode.run_plan(g, None, mode.Setup(g, 1, 3, 'quarter'), [(3, 0, ''), (23, 0, ''), (25, 1, '')])
    run = json.loads(json.dumps(run))
    run['slots'] = {int(k): v for k, v in run['slots'].items()}
    run['roster'] = {int(k): v for k, v in run['roster'].items()}
    run['refill'] = refill
    return run


class GuestWaveTests(unittest.TestCase):
    def test_full_run_to_victory(self):
        run = small_run()
        w = World(run)
        w.update(3)
        self.assertEqual(w.word('state'), rt.INIT)                     # nothing before "Fight!"
        w.start_story(); w.update()
        self.assertEqual(w.word('state'), rt.FIGHT); self.assertGreater(w.word('banner_until'), w.word('tick'))
        w.m.w(HP(0), 20000)                                            # a hurt player, a KO'd player
        w.ko(4)
        w.ko(1); w.update()
        self.assertEqual(w.slot(1, 'state'), rt.KO)
        self.assertEqual(w.word('state'), rt.COUNTDOWN)                # an empty enemy side never ends the match
        self.assertEqual(w.m.u(story.CONTROL + 96), 0)
        self.assertEqual(w.m.u(HP(0)), 20000)                          # no health back during the break ...
        self.assertEqual(w.m.u(story.CONTROL + 48), run['enemy_mask'])  # ... where only enemy bodies are protected
        w.update(ACTOR_HZ)
        self.assertEqual(w.m.u(story.CONTROL + 112) & 2, 2)            # the KO'd leader is retired (hidden)
        # Countdown ends: wave 2 is preloaded (slots 3 and 5), the intro protects everyone and admits both.
        for _ in range(3 * ACTOR_HZ):
            w.update()
            if w.word('state') == rt.INTRO:
                break
        self.assertEqual(w.word('state'), rt.INTRO); self.assertEqual(w.word('wave'), 1)
        self.assertEqual(w.m.u(story.CONTROL + 48), run['participants'])
        self.assertEqual(w.m.u(HP(0)), 22500)                          # +1/4 bar once, as the wave starts
        self.assertEqual(w.m.u(HP(4)), 0)                              # a KO'd teammate is not healed
        w.update(); self.assertEqual(w.m.u(HP(0)), 22500)
        w.update(2)
        # One entrant at a time: slot 3 is spawned, standing (idle requested: no fall, no get-up), and its intro
        # plays; slot 5 is still hidden until 3's shot has had its full length.
        self.assertEqual(w.word('wave_mask'), 1 << 3)
        self.assertEqual(w.slot(3, 'state'), rt.ACTIVE); self.assertEqual(w.m.u(ACTOR(3) + 0x1278), 0)
        self.assertEqual(w.m.u(ACTOR(3) + 0x94C), 11)
        self.assertIn(('arrival', ACTOR(3), MODEL(3)), w.calls)
        self.assertEqual(w.slot(5, 'state'), rt.READY)
        shot = round(0.5 * ACTOR_HZ)
        w.update(shot - 4); self.assertEqual(w.word('wave_mask'), 1 << 3)
        w.update(4); self.assertEqual(w.word('wave_mask'), (1 << 3) | (1 << 5))
        self.assertEqual(w.word('intro_actor'), 5)
        self.assertEqual(w.word('intro_camera'), 6)                    # handed straight to the next entrant
        for _ in range(4 * ACTOR_HZ):
            w.update()
            if w.word('state') == rt.FIGHT:
                break
        self.assertEqual(w.word('state'), rt.FIGHT)
        self.assertEqual(w.m.u(story.CONTROL + 48), 0)                 # protection released
        self.assertEqual(w.m.u(ACTOR(3) + 0x1278), 1)                  # CPU flags back
        self.assertEqual([c[0] for c in w.calls].count('camera'), 2)   # one native intro camera per entrant
        self.assertEqual([c[0] for c in w.calls].count('camera_end'), 0)  # the stub never shows our track running
        # Wave 3 is preloaded too (slot 7): clear wave 2, then wave 3 -> victory.
        w.ko(3); w.ko(5); w.update(); self.assertEqual(w.word('state'), rt.COUNTDOWN)
        for _ in range(8 * ACTOR_HZ):
            w.update()
            if w.word('state') == rt.FIGHT and w.word('wave') == 2:
                break
        self.assertEqual(w.word('wave_mask'), 1 << 7)
        w.ko(7); w.update()
        self.assertEqual(w.word('state'), rt.WON); self.assertEqual(w.m.u(story.CONTROL + 96), 1)

    def test_extra_bodies_are_consumed_after_the_vanish_delay_but_not_during_an_intro(self):
        run = small_run(waves=((90, 84), (82,)))
        w = World(run); w.start_story(); w.update()
        w.ko(3); w.update()
        self.assertEqual(w.slot(3, 'state'), rt.KO)
        w.update(ACTOR_HZ - 2)
        self.assertFalse(w.m.u(part.CONSUMED) & (1 << 3))
        w.update(3)
        self.assertTrue(w.m.u(part.CONSUMED) & (1 << 3)); self.assertEqual(w.slot(3, 'state'), rt.VANISHED)

    def test_overtime_and_reinforcements(self):
        run = small_run(waves=((90,), (86, 87, 88, 89, 84)))
        for p in (3, 5, 7, 9):        # nothing preloaded: every slot is free and must be loaded first
            run['slots'][p].update(state=rt.VANISHED, wave=0)
        w = World(run); w.start_story(); w.update()
        w.ko(1); w.update()
        self.assertEqual(w.word('state'), rt.COUNTDOWN)
        w.update(3 * ACTOR_HZ + 2)
        self.assertEqual(w.word('state'), rt.COUNTDOWN)               # nobody loaded: the countdown waits
        # The host makes one slot READY in the overtime: the intro starts with it, four stay pending.
        row = rt.SLOTS + 3 * rt.SLOT_STRIDE
        w.m.w(row + rt.S['wave'], 2); w.m.w(row + rt.S['state'], rt.READY)
        w.update(2)
        self.assertEqual(w.word('state'), rt.INTRO)                   # past the overtime: what is ready enters
        # A fighter that becomes ready while the intro waits (a slot is free for it) gets its own intro too.
        w.update(round(0.5 * ACTOR_HZ) + 2)
        self.assertEqual(w.word('state'), rt.INTRO); self.assertGreater(w.word('intro_waited'), 0)
        row = rt.SLOTS + 9 * rt.SLOT_STRIDE
        w.m.w(row + rt.S['wave'], 2); w.m.w(row + rt.S['index'], 4); w.m.w(row + rt.S['state'], rt.READY)
        w.update(2)
        self.assertEqual(w.word('intro_actor'), 9); self.assertEqual(w.word('pending'), 3)
        for _ in range(4 * ACTOR_HZ):                                   # ... then the wait is bounded
            w.update()
            if w.word('state') == rt.FIGHT:
                break
        self.assertEqual(w.word('state'), rt.FIGHT)
        self.assertEqual(w.word('pending'), 3)
        w.ko(9); w.update()
        w.m.w(rt.SLOTS + 5 * rt.SLOT_STRIDE + rt.S['wave'], 2); w.m.w(rt.SLOTS + 5 * rt.SLOT_STRIDE + rt.S['state'], rt.READY)
        w.update()
        self.assertEqual(w.word('pending'), 2)                        # a reinforcement during the fight
        self.assertEqual(w.word('wave_mask'), (1 << 3) | (1 << 5))
        self.assertEqual(w.m.u(ACTOR(5) + 0x94C), 11)                 # it stands too
        w.ko(3); w.ko(5); w.update(2)
        self.assertEqual(w.word('state'), rt.FIGHT)                   # owed fighters keep the wave open
        w.update(3 * ACTOR_HZ + 2)
        self.assertEqual(w.word('pending'), 0)                        # ... until the give-up bound
        w.update()
        self.assertEqual(w.word('state'), rt.WON)

    def test_pending_never_goes_negative(self):
        run = small_run(waves=((90,), (84,)))
        w = World(run); w.start_story(); w.update()
        w.ko(1); w.update(); w.update(4 * ACTOR_HZ)
        self.assertEqual(w.word('pending'), 0)
        # A stray READY slot for the current wave is not admitted once the wave owes nobody.
        row = rt.SLOTS + 9 * rt.SLOT_STRIDE
        w.m.w(row + rt.S['wave'], w.word('wave') + 1); w.m.w(row + rt.S['state'], rt.READY)
        w.update(5)
        self.assertEqual(w.word('pending'), 0); self.assertEqual(w.slot(9, 'state'), rt.READY)

    def test_loss_when_every_player_fighter_is_down(self):
        w = World(small_run()); w.start_story(); w.update()
        for p in (0, 2, 4):
            w.ko(p)
        w.update()
        self.assertEqual(w.word('state'), rt.LOST); self.assertEqual(w.word('result'), 2)
        self.assertEqual(w.m.u(story.CONTROL + 96), 0)               # the native result decides the loss

    def test_gates(self):
        w = World(small_run()); w.start_story()
        a, mo = ACTOR(7), MODEL(7)
        w.m.w(part.CONSUMED, 1 << 7); w.m.w(mo + 8, 0); w.m.w(a + 0x948, 216); w.m.w(HP(7), 0)
        w.update(2); self.assertEqual(w.m.u(rt.GATES + 28), 0)
        w.update(); gate = w.m.u(rt.GATES + 28)
        self.assertEqual(gate & 0xFFFF0000, rt.GATE_MAGIC); generation = gate & 0xFFFF
        w.m.w(mo + 8, 1); w.update(); self.assertEqual(w.m.u(rt.GATES + 28), 0)
        w.m.w(mo + 8, 0); w.update(3)
        self.assertEqual(w.m.u(rt.GATES + 28) & 0xFFFF, generation + 1)   # a new vanish, a new generation


class GuestTransportTests(unittest.TestCase):
    def publish(self, w, blocks):
        manifest = dict(blocks=[dict(address=p, expected_hex=old.hex(), data_hex=new.hex()) for p, old, new in blocks])
        packet, count = native.encode(manifest)
        w.m.write(rt.PACKET, packet)
        c = rt.CONTROL
        w.m.w(c + rt.C['copy_blocks'], count); w.m.w(c + rt.C['copy_bytes'], len(packet))
        w.m.w(c + rt.C['copy_request'], w.word('copy_request') + 1)
        w.update()
        return w.word('copy_status')

    def test_copier(self):
        w = World()
        code = bytes(range(16))
        self.assertEqual(self.publish(w, [(0x07600000, bytes(16), code)]), 1)
        self.assertEqual(w.m.read(0x07600000, 16), code)
        self.assertEqual(self.publish(w, [(0x07600000, bytes(16), code)]), 100)         # old bytes differ
        self.assertEqual(self.publish(w, [(0x07400000, bytes(4), b'1234')]), 101)        # outside the workspaces
        self.assertEqual(self.publish(w, [(0x07670FFC, bytes(8), bytes(range(8)))]), 1)  # inside retire
        self.assertEqual(self.publish(w, [(0x0761FFFC, bytes(8), bytes(range(8)))]), 101)  # runs past its end
        if rt.METADATA is not None:
            meta = rt.METADATA
            self.assertEqual(self.publish(w, [(meta.DATA + 0x14000, bytes(4), b'meta')]), 1)  # handle 3's sidecars
            self.assertEqual(self.publish(w, [(meta.ROWS, bytes(4), b'rows')]), 1)            # handle 2's row
            for refused in (meta.CODE, meta.CONTROL, meta.ROWS + 12 * 64, meta.DATA + 12 * meta.STRIDE):
                self.assertEqual(self.publish(w, [(refused, bytes(4), b'nope')]), 101, hex(refused))
        self.assertEqual(self.publish(w, [(rt.EXT_WORD, bytes(8), bytes(8))]), 101)      # getter: only the stage jump
        w.m.w(rt.EXT_WORD, 0x0812345); w.m.w(rt.EXT_WORD + 4, 0)
        self.assertEqual(self.publish(w, [(rt.EXT_WORD, w.m.read(rt.EXT_WORD, 8), rt.EXT_NEW)]), 1)
        w.m.w(native.CONTROL + 16, 1)                                                   # a hold in progress
        self.assertEqual(self.publish(w, [(0x07610000, bytes(4), b'abcd')]), 103)
        w.m.w(native.CONTROL + 16, 0); w.m.w(0x0762F004, 2)                             # a commit mid-job
        self.assertEqual(self.publish(w, [(0x07610000, bytes(4), b'abcd')]), 103)

    def test_runner(self):
        w = World()
        c = rt.CONTROL
        w.m.w(0x0760F000, 1)
        w.update(2)

        def start(entry, control, kind):
            w.m.write(c + rt.C['run_status'], struct.pack('<8I', 0, entry, control, kind, 3, 0, 0, 50))
            w.m.w(c + rt.C['run_request'], w.word('run_request') + 1)
        start(0x07600000, 0x0760F000, rt.RUN_IO)
        w.update()
        self.assertNotEqual(w.word('run_ack'), w.word('run_request'))                 # io polls on
        w.update(2)
        self.assertEqual((w.word('run_ack'), w.word('run_status')), (w.word('run_request'), 5))
        w.m.w(0x0761F000, 1); start(0x07610000, 0x0761F000, rt.RUN_ONCE); w.update()
        self.assertEqual(w.word('run_status'), 5)
        w.m.w(0x0760F004, 0); w.m.w(runner_busy := quiet.LOADER_STATE, 1)
        start(0x07600000, 0x0760F000, rt.RUN_IO); w.update(3)
        self.assertNotEqual(w.word('run_ack'), w.word('run_request'))                 # the loader idle gate waits
        self.assertEqual(w.word('run_waits'), 3)
        w.m.w(runner_busy, 0); w.update(3)
        self.assertEqual(w.word('run_status'), 5)
        start(0x07400000, 0x0760F000, rt.RUN_ONCE); w.update()
        self.assertEqual(w.word('run_status'), 110)                                   # only the four workspaces


class GuestSpectatorTests(unittest.TestCase):
    def test_cycle_skips_the_removed(self):
        import spectator_switch as spec
        run = small_run(waves=((90, 84), (82,)))
        w = World(run); w.m.w(rt.CONTROL + rt.C['spectate'], 1)
        w.m.write(rt.ORDER, bytes([0, 2, 4, 1, 3, 5, 7, 9])); w.m.w(rt.CONTROL + rt.C['order_count'], 8)
        for p in (5, 7, 9):
            w.m.w(part.CONSUMED, w.m.u(part.CONSUMED) | (1 << p))
        w.start_story(); w.update()
        watched = []
        for _ in range(6):
            w.m.w(spec.pad_buttons(1), 0x800); w.update(); w.m.w(spec.pad_buttons(1), 0); w.update()
            watched.append(w.word('watched') - 1)
        self.assertEqual(watched, [0, 2, 4, 1, 3, 0])
        self.assertEqual(w.m.u(spec.CONTROL + spec.FIELDS['lock']), 1)
        w.m.w(spec.pad_buttons(0), 0x400); w.update(); w.m.w(spec.pad_buttons(0), 0); w.update()
        self.assertEqual(w.word('watched') - 1, 3)                                    # L1 goes back
        w.ko(3); w.update()
        self.assertEqual(w.word('watched') - 1, 0)                                    # a KO'd subject: the next one


class FakePine:
    """Guest words for the Service: slots and gates of the recycled physicals."""
    def __init__(self):
        self.mem = {}

    def read_u32(self, at):
        return self.mem.get(at, 0)

    def read(self, at, n):
        return b''.join(struct.pack('<I', self.mem.get(at + k, 0)) for k in range(0, n, 4))

    def write_u32(self, at, value):
        self.mem[at] = value

    def write(self, at, data):
        for k in range(0, len(data), 4):
            self.mem[at + k] = struct.unpack_from('<I', data, k)[0]


class FakeWorker:
    def __init__(self, retained):
        self.retained, self.job, self.form_job, self.swept = retained, None, None, []

    def sweep(self, p, physical):
        self.swept.append(physical); return True

    def kept(self):
        return sum(len(v) for v in self.retained.values())


class ServiceRecordTests(unittest.TestCase):
    """g7: kept bundles of hidden slots are swept; io 130 waits for a sweep instead of skipping at once."""
    def vanished(self, p, physical):
        p.write_u32(rt.SLOTS + rt.SLOT_STRIDE * physical + rt.S['state'], rt.VANISHED)
        p.write_u32(rt.GATES + 4 * physical, 0x47410001)

    def test_a_hidden_slot_with_kept_bundles_is_swept_once_per_period(self):
        p, worker = FakePine(), FakeWorker({5: ['old'], 7: ['old']})
        self.vanished(p, 7)
        s = mode.Service(log=lambda m: None)
        self.assertTrue(s.sweep(p, worker)); self.assertEqual(worker.swept, [7])     # 5 is still fighting
        self.assertFalse(s.sweep(p, worker))                                          # not again within the period
        s.assigned[7] = (2, 0); s.sweeps.clear()
        self.assertFalse(s.sweep(p, worker))                                          # never a slot being loaded

    def test_records_running_out_waits_for_a_sweep(self):
        s = mode.Service(log=lambda m: None)
        s.kept = 2
        skipped = []
        s.skip = lambda p, number: skipped.append(number)
        s.wave = lambda p, number: (1, [(90, 0, 0, 1000, 1000)])
        for attempt in range(mode.RECORD_RETRIES - 1):
            s.assigned[3] = (2, 0)
            s.finished(None, dict(physical=3, phase='failed', reason='io: job ended with status 130'))
        self.assertEqual(skipped, []); self.assertGreater(s.retry_at, 0)
        s.assigned[3] = (2, 0)
        s.finished(None, dict(physical=3, phase='failed', reason='io: job ended with status 130'))
        self.assertEqual(skipped, [2])
        s.kept = 0
        for attempt in range(mode.LOAD_ATTEMPTS):
            s.assigned[5] = (3, 0)
            s.finished(None, dict(physical=5, phase='failed', reason='io: job ended with status 130'))
        self.assertEqual(skipped, [2, 3])                                             # nothing kept: the usual rule

    def test_the_gauntlet_retirement_skips_only_the_flag_and_byte_block(self):
        import gauntlet_reload
        self.assertEqual(gauntlet_reload.ACTOR_DATA, ((0x7A0, 0x8C0), (0x1080, 0x1270)))
        for lo, hi in gauntlet_reload.ACTOR_DATA:
            self.assertTrue(hi <= 0x15E8 and lo % 4 == 0)   # the cached attack-script pointers stay checked


class RoundTwoGuestTests(unittest.TestCase):
    def test_a_vanished_body_goes_back_to_its_start_position_and_its_auras_end(self):
        run = small_run(waves=((90, 84), (82,)))
        w = World(run)
        home = struct.pack('<3f', 120.0, -4.0, -300.0)
        w.m.write(MODEL(3) + 2416, home)
        w.m.w(rt.CONTROL + rt.C['cleanup'], rt.AURA)
        w.m.callbacks[rt.AURA] = w.stub('aura')
        w.start_story(); w.update()
        self.assertEqual(w.word('homes') & (1 << 3), 1 << 3)
        self.assertEqual(w.m.read(rt.SLOTS + 3 * rt.SLOT_STRIDE + rt.S['home'], 12), home)
        far = struct.pack('<3f', 15.0, -2.0, 40.0)                        # it fell among the fighters
        for at in (ACTOR(3) + 0x10, ACTOR(3) + 0x100, MODEL(3) + 2416):
            w.m.write(at, far)
        w.ko(3); w.update(ACTOR_HZ + 2)
        self.assertEqual(w.slot(3, 'state'), rt.VANISHED)
        for at in (ACTOR(3) + 0x10, ACTOR(3) + 0x100, MODEL(3) + 2416):
            self.assertEqual(w.m.read(at, 12), home)
        self.assertEqual(w.m.read(ACTOR(3) + 0x30, 12), bytes(12))
        self.assertIn(3, [c[1] for c in w.calls if c[0] == 'aura'])                    # a0 = its model ID

    def test_a_retired_leader_stays_at_its_start_position(self):
        run = small_run()
        w = World(run)
        home = struct.pack('<3f', -50.0, -3.0, 600.0)
        w.m.write(MODEL(1) + 2416, home)
        w.start_story(); w.update()
        w.ko(1); w.update(ACTOR_HZ + 2)
        self.assertEqual(w.slot(1, 'state'), rt.VANISHED)
        self.assertEqual(w.m.read(MODEL(1) + 2416, 12), home)
        for at in (ACTOR(1) + 0x10, MODEL(1) + 2416):                    # the game moves the hidden leader
            w.m.write(at, struct.pack('<3f', 54.0, -50.0, -26.0))
        w.update()
        for at in (ACTOR(1) + 0x10, ACTOR(1) + 0x100, MODEL(1) + 2416):
            self.assertEqual(w.m.read(at, 12), home)

    def test_none_gives_no_health_back(self):
        run = small_run(refill=0)
        w = World(run); w.start_story(); w.update()
        w.m.w(HP(0), 12345); w.m.w(HP(2), 777)
        w.ko(1); w.update()
        self.assertEqual(w.word('state'), rt.COUNTDOWN)
        for _ in range(8 * ACTOR_HZ):                                    # countdown, intro, release
            w.update()
            if w.word('state') == rt.FIGHT and w.word('wave') == 1:
                break
        self.assertEqual(w.word('state'), rt.FIGHT)
        self.assertEqual((w.m.u(HP(0)), w.m.u(HP(2))), (12345, 777))
        self.assertEqual(data.REFILL[0][:2], ('off', 'None (no health back)'))

    def test_the_spectator_follows_the_player_team_only(self):
        run = small_run()
        _, order = rt.name_table(run)
        self.assertEqual(list(order), [0, 2, 4])


class BreakMovementTests(unittest.TestCase):
    """Round 4: the player team moves between waves; entrants arrive near the team."""

    def mirror(self, w, viewer, state):
        """BREAK as the native opponent mirror calls it: a0 = the (KO'd) opponent, s1 = the viewing actor."""
        dead = []
        w.m.callbacks[rt.OPPONENT_DEAD] = lambda m: (dead.append(m.r[4]), m.r.__setitem__(2, 1))
        w.m.w(rt.CONTROL + rt.C['state'], state)
        w.m.r[4], w.m.r[17], w.m.r[29], w.m.r[31] = ACTOR(1), viewer, 0x2000000 - 0x100, 0xFEED0000
        for r in (8, 9, 10):
            w.m.r[r] = 0x1234 + r
        w.m.run(rt.BREAK)
        self.assertEqual([w.m.r[r] for r in (8, 9, 10)], [0x1234 + r for r in (8, 9, 10)])
        return w.m.r[2], dead

    def test_the_player_team_is_not_frozen_by_a_dead_opponent_during_the_countdown(self):
        w = World(small_run())
        self.assertEqual(self.mirror(w, ACTOR(0), rt.COUNTDOWN), (0, []))           # human, countdown: alive
        self.assertEqual(self.mirror(w, ACTOR(4), rt.COUNTDOWN), (0, []))           # CPU teammate too
        self.assertEqual(w.word('breaks'), 2)
        self.assertEqual(self.mirror(w, ACTOR(0), rt.FIGHT), (1, [ACTOR(1)]))       # the native test otherwise
        self.assertEqual(self.mirror(w, ACTOR(0), rt.INTRO), (1, [ACTOR(1)]))
        self.assertEqual(self.mirror(w, ACTOR(0), rt.WON), (1, [ACTOR(1)]))
        self.assertEqual(self.mirror(w, ACTOR(3), rt.COUNTDOWN), (1, [ACTOR(1)]))   # an enemy body
        self.assertEqual(self.mirror(w, 0x00650000, rt.COUNTDOWN), (1, [ACTOR(1)])) # not a captured actor
        w.m.w(rt.CONTROL + 4, MANAGER + 0x10)                                       # another match
        self.assertEqual(self.mirror(w, ACTOR(0), rt.COUNTDOWN), (1, [ACTOR(1)]))

    def test_the_mirror_call_is_the_flag_177_test_the_pad_reader_clears_input_for(self):
        from prototype import elf_reader, ROOT
        from native_map import elf_path
        try:
            read = elf_reader(elf_path(ROOT))[2]
        except (OSError, ValueError, IndexError, TypeError):
            self.skipTest('USA executable not present')
        word = lambda p: struct.unpack('<I', read(p, 4))[0]
        jal = lambda p: (3 << 26) | (p >> 2)
        self.assertEqual(word(rt.MIRROR_CALL), jal(rt.OPPONENT_DEAD))
        self.assertEqual(word(rt.MIRROR_CALL + 0x10), jal(A(0x1DA9D0)))             # ... sets flag 177
        self.assertEqual(word(rt.MIRROR_CALL + 0x14) & 0xFFFF, 177)
        self.assertEqual(word(A(0x1D4738)), jal(A(0x1DAC78)))                       # the pad reader asks for it
        self.assertEqual(word(A(0x1D473C)) & 0xFFFF, 177)

    def test_the_break_hook_belongs_to_a_run_only(self):
        blocks = dict(rt.code_blocks())
        self.assertIn(rt.BREAK, blocks); self.assertIn(rt.PLACE, blocks)
        self.assertLessEqual(len(blocks[rt.BREAK]), rt.PLACE - rt.BREAK)
        self.assertLessEqual(len(blocks[rt.PLACE]), rt.CONTROL - rt.PLACE)

    def place(self, team, homes, spawns, players=3, radii=None, bodies=None, floor=None, arena=None, admit=(3,)):
        """Admit wave-2 entrants `admit` (each spawned at spawns[p] by the native spawn) with the given team positions
        (by physical), enemy homes, native body radii, other bodies' positions, an optional floor probe (callable
        x, z -> floor y or None) and arena radius; returns {physical: placed (x, y, z)}."""
        import spawn_placement as planner
        import arena_bounds as arena_mod
        run = small_run()
        w = World(run, players=players)

        def arrival(m):
            actor = m.r[4]
            p = next(q for q in range(12) if ACTOR(q) == actor)
            m.write(MODEL(p) + 2416, struct.pack('<3f', *spawns[p])); m.r[2] = 1
        w.m.callbacks[story.ARRIVAL] = arrival
        for p, pos in list(team.items()) + list((bodies or {}).items()):
            w.m.write(MODEL(p) + 2416, struct.pack('<3f', *pos))
        for p, r in (radii or {}).items():
            w.m.write(MODEL(p) + 0x1004, struct.pack('<f', r))
        mask = 0
        for p, pos in homes.items():
            w.m.write(rt.SLOTS + p * rt.SLOT_STRIDE + rt.S['home'], struct.pack('<3f', *pos)); mask |= 1 << p
        w.m.w(rt.CONTROL + rt.C['homes'], mask)
        if floor is not None:
            w.m.write(planner.QUERY, planner.query_code()[:8])

            def probe(m):
                x, z = struct.unpack('<f', m.read(m.r[4], 4))[0], struct.unpack('<f', m.read(m.r[4] + 8, 4))[0]
                y = floor(x, z)
                m.r[2] = int(y is not None)
                if y is not None:
                    m.f[0] = struct.unpack('<I', struct.pack('<f', y))[0]
            w.m.callbacks[planner.QUERY] = probe
        if arena is not None:
            stage, block = 0x00A00000, 0x00A01000
            w.m.w(arena_mod.STAGE, stage); w.m.w(stage + 64, block)
            w.m.write(block, struct.pack('<3f', arena, -350.0, 1000.0))
        out = {}
        for p in admit:
            w.m.w(rt.SLOTS + p * rt.SLOT_STRIDE + rt.S['state'], rt.READY)
            w.m.r[4], w.m.r[29], w.m.r[31] = p, 0x2000000 - 0x100, 0xFEED0000
            w.m.run(rt.ADMIT)
            self.assertEqual(w.m.r[2], 1)
            out[p] = struct.unpack('<3f', w.m.read(MODEL(p) + 2416, 12))
            for at in (ACTOR(p) + 0x10, ACTOR(p) + 0x100):
                self.assertEqual(w.m.read(at, 12), w.m.read(MODEL(p) + 2416, 12))
            self.assertEqual(w.m.read(ACTOR(p) + 0x30, 12), bytes(12))
            self.assertEqual(w.m.u(ACTOR(p) + 0x94C), 11)                          # stands at once
        return w, out

    @staticmethod
    def gap(a, b, ra=0.0, rb=0.0):
        return (a[0] - b[0]) ** 2 + (a[2] - b[2]) ** 2, (rt.PLACE_GAP + rt.PLACE_SIZE * (ra + rb)) ** 2

    def test_entrants_stand_on_an_arc_facing_a_team_that_flew_far_away(self):
        team = {0: (2000.0, -300.0, 0.0), 2: (2000.0, -300.0, 100.0), 4: (2000.0, -300.0, -100.0)}
        w, got = self.place(team, {1: (0.0, 0.0, 0.0), 3: (0.0, 0.0, 0.0)}, {3: (-10.0, -2.0, 30.0), 5: (-10.0, -2.0, 30.0)},
                            admit=(3, 5))
        for p, (x, y, z) in got.items():
            self.assertAlmostEqual(((x - 2000.0) ** 2 + z * z) ** 0.5, rt.PLACE_FAR, delta=1.0)   # the arc
            self.assertLess(x, 2000.0); self.assertAlmostEqual(y, -2.0, delta=0.01)                # on its ground
        d2, need2 = self.gap(got[3], got[5])
        self.assertGreaterEqual(d2, need2 - 1.0)                       # both native marks were the same spot
        self.assertEqual(w.word('placed'), 2)
        self.assertIn(('ground', 0xFFFFFFFF, MODEL(3) + 2416), [(c[0], c[1] & 0xFFFFFFFF, c[2]) for c in w.calls])

    def test_a_team_near_the_formation_gets_the_arc_at_its_own_distance(self):
        team = {0: (300.0, 0.0, 0.0), 2: (300.0, 0.0, 40.0), 4: (300.0, 0.0, -40.0)}
        _, got = self.place(team, {1: (0.0, 0.0, 0.0)}, {3: (12.0, -1.0, 7.0)})
        x, _, z = got[3]
        self.assertAlmostEqual(((x - 300.0) ** 2 + z * z) ** 0.5, 300.0, delta=1.0)

    def test_an_entrant_never_lands_in_a_player_or_a_hidden_body(self):
        team = {0: (5.0, 0.0, 0.0)}
        # the arc's first slot (D = PLACE_NEAR from the player, towards the homes at -x) holds a KO'd body
        bodies = {7: (5.0 - rt.PLACE_NEAR + 15.0, 0.0, 0.0)}
        _, got = self.place(team, {1: (-400.0, 0.0, 0.0)}, {3: (5.0, 0.0, 0.0)}, players=1, bodies=bodies)
        for other, pos in list(team.items()) + list(bodies.items()):
            d2, need2 = self.gap(got[3], pos)
            self.assertGreaterEqual(d2, need2 - 1.0, other)
        d2, need2 = self.gap(got[3], team[0]); self.assertGreaterEqual(d2 ** 0.5, rt.PLACE_GAP + rt.PLACE_TEAM - 1.0)

    def test_a_giant_keeps_a_wider_gap(self):
        team = {0: (2000.0, 0.0, 0.0)}
        _, got = self.place(team, {1: (0.0, 0.0, 0.0)}, {3: (0.0, 0.0, 0.0), 5: (0.0, 0.0, 0.0)}, players=1,
                            radii={3: 30.0, 5: 5.0}, admit=(3, 5))
        d2, need2 = self.gap(got[3], got[5], 30.0, 5.0)
        self.assertGreaterEqual(d2, need2 - 1.0)

    def test_the_floor_probe_sets_the_height_and_a_floorless_spot_is_skipped(self):
        team = {0: (2000.0, -500.0, 0.0)}
        floor = lambda x, z: None if z > 0.5 else 37.5                  # no floor on one side
        _, got = self.place(team, {1: (0.0, 0.0, 0.0)}, {3: (0.0, -400.0, 0.0), 5: (0.0, -400.0, 0.0)}, players=1,
                            floor=floor, admit=(3, 5))
        for p in (3, 5):
            self.assertAlmostEqual(got[p][1], 37.5, delta=0.01)         # stands on the floor, never mid-air
            self.assertLessEqual(got[p][2], 0.5)

    def test_spots_outside_the_arena_are_skipped(self):
        team = {0: (950.0, 0.0, 0.0)}
        _, got = self.place(team, {1: (1400.0, 0.0, 0.0)}, {3: (0.0, 0.0, 0.0)}, players=1, arena=1200.0)
        x, _, z = got[3]
        limit = 1200.0 - 140.0
        self.assertLessEqual(x * x + z * z, limit * limit + 1.0)

    def test_a_shot_lasts_until_the_native_entrance_pose_has_played_out(self):
        run = small_run()
        w = World(run)
        w.m.w(rt.CONTROL + rt.C['step'], 3 * ACTOR_HZ)                    # the bound: 3 s
        w.start_story(); w.update(); w.ko(1); w.update()
        for _ in range(4 * ACTOR_HZ):
            w.update()
            if w.word('state') == rt.INTRO:
                break
        w.update(2); self.assertEqual(w.word('intro_actor'), 3)
        w.m.w(ACTOR(3) + 0x948, 67)                                        # its entrance pose starts
        w.update(ACTOR_HZ)                                                 # past intro_nopose: still its shot
        self.assertEqual(w.word('intro_actor'), 3); self.assertEqual(w.word('intro_posed'), 1)
        w.m.w(ACTOR(3) + 0x948, 11); w.update(2)                           # the pose is over: next entrant
        self.assertEqual(w.word('intro_actor'), 5)
        w.m.w(ACTOR(5) + 0x948, 67); w.update(3 * ACTOR_HZ + 2)            # a pose never ends: the bound
        self.assertNotEqual(w.word('intro_phase'), 2)

    def test_no_living_player_keeps_the_spawn(self):
        run = small_run()
        w = World(run, players=1); w.ko(0)
        spawn = struct.pack('<3f', 1.0, 2.0, 3.0)
        w.m.callbacks[story.ARRIVAL] = lambda m: (m.write(MODEL(3) + 2416, spawn), m.r.__setitem__(2, 1))
        w.m.w(rt.SLOTS + 3 * rt.SLOT_STRIDE + rt.S['state'], rt.READY)
        w.m.r[4], w.m.r[29], w.m.r[31] = 3, 0x2000000 - 0x100, 0xFEED0000
        w.m.run(rt.ADMIT)
        self.assertEqual(w.m.read(MODEL(3) + 2416, 12), spawn); self.assertEqual(w.word('placed'), 0)


class CountdownSizeTests(unittest.TestCase):
    def test_the_countdown_digits_are_half_the_first_size(self):
        u0, v0, u1, v1 = rt.DIGIT_UV
        self.assertEqual(((u1 - u0) * rt.DIGIT_SCALE, (v1 - v0) * rt.DIGIT_SCALE), (36, 39))
        self.assertEqual(rt.DIGIT_STEP, 30)
        self.assertLess(rt.COUNTDOWN_LABEL, 11)
        code = rt.draw_code(story.DRAW)                                   # whole GS units only
        self.assertEqual(len(code) % 4, 0)

    def test_the_panel_draws_within_its_gs_budget_in_both_languages(self):
        import guest_loading_screen as screen

        class Owner:
            def library(self):
                return data.load(data.family())
        for lang in ('en', 'es'):
            for humans, row in ((1, 0), (0, 3), (3, 4)):
                p = mode.Panel(Owner()); p.settings = {'language': lang}; p.humans = humans; p.row = row
                p.size = max(3, humans)
                rects = screen.picture_rectangles(p.picture())
                self.assertLess(len(rects), 9500, (lang, humans))
                screen.gif_packet(rects)


class SpanishBlurbTests(unittest.TestCase):
    """Every shipped gauntlet carries description_es; Spanish shows it in the picker and on the Setup card."""
    def library(self):
        return data.load(data.family())

    def test_every_shipped_gauntlet_has_a_spanish_blurb(self):
        raw = json.loads(data.PATH.read_text(encoding='utf-8-sig'))
        for g in raw['gauntlets']:
            self.assertTrue(g.get('description_es'), g['id'])
            self.assertNotEqual(g['description_es'], g['description'], g['id'])
        for g in self.library()['gauntlets']:
            self.assertTrue(g['description_es'], g['id'])

    def test_the_picker_and_the_card_show_the_spanish_blurb(self):
        lib = self.library()
        es = {g['id']: desc for _, desc, kind, g in
              ((label, desc, kind, g) for label, desc, kind, g in mode.picker_items(lib, {'language': 'es'}))
              if g is not None}
        en = {g['id']: desc for label, desc, kind, g in mode.picker_items(lib, {'language': 'en'}) if g is not None}
        for g in lib['gauntlets']:
            if g['id'] not in es:
                continue
            first = es[g['id']].split('\n')[0]
            self.assertEqual(first, mode._line(mode.blurb(g, {'language': 'es'})), g['id'])
            self.assertNotEqual(first, en[g['id']].split('\n')[0], g['id'])
            self.assertEqual(mode.description(g, {'language': 'es'}), g['description_es'])
            self.assertEqual(mode.description(g, {'language': 'en'}), g['description'])

    def test_the_wave_banner_title_follows_the_language(self):
        import localization
        lib = self.library()
        g = next(x for x in lib['gauntlets'] if x['id'].startswith('quick_test'))
        rows = mode.wave_rows(g, lib.get('potara') or {})
        self.assertEqual(rows[1]['label_es'], 'Los secuaces de Frieza')
        with localization.using('es'):
            self.assertEqual(rt.text(rt.wave_title(rows[1])), 'LOS SECUACES DE FRIEZA')
            self.assertEqual(rt.wave_title(rows[0]), rows[0]['label'])        # a name: no Spanish form, the label
        with localization.using('en'):
            self.assertEqual(rt.wave_title(rows[1]), "Frieza's henchmen")
        titled = sum(1 for x in lib['gauntlets'] for w in x['waves'] if w['label_es'])
        self.assertGreater(titled, 100)
        for x in lib['gauntlets']:
            for w in x['waves']:
                self.assertTrue(rt.text(w['label_es'] or w['label']).isascii())

    def test_a_gauntlet_without_a_spanish_blurb_keeps_the_cpu_range_line(self):
        lib = copy.deepcopy(self.library())
        for g in lib['gauntlets']:
            g['description_es'] = ''
        for label, desc, kind, g in mode.picker_items(lib, {'language': 'es'}):
            if g is not None:
                self.assertIn('CPU', desc.split('\n')[0], g['id'])
                self.assertEqual(mode.description(g, {'language': 'es'}), '')


class RollbackTests(unittest.TestCase):
    """Round 2: a load that fails after its io gives back its staged model and resource record, then retries once."""
    def worker(self):
        import gauntlet_reload as gr
        notes = []
        w = gr.GauntletWorker(progress=notes.append)
        return w, notes

    def test_a_failure_after_io_queues_a_rollback_and_never_one_after_the_commit(self):
        w, notes = self.worker()
        job = dict(physical=5, phase='stage-run', io_done=dict(resource=0x92B704, handle=3), stage_tried=True)
        self.assertIs(w._fail(job, 'stage: job ended with status 144'), job)
        self.assertEqual(w.job['phase'], 'rollback-plan'); self.assertTrue(w.job['rollback'])
        self.assertEqual((w.job['physical'], w.job['io_done']['handle'], w.job['stage_tried']), (5, 3, True))
        w.job = None
        w._fail(dict(physical=5, phase='io-run'), 'io: job ended with status 130')     # nothing was loaded
        self.assertIsNone(w.job)
        w._fail(dict(physical=5, phase='retire-run', io_done=dict(resource=1, handle=3), committed=True), 'x')
        self.assertIsNone(w.job)                                                      # the owner uses it now
        rollback = dict(physical=5, phase='retire-run', rollback=True, io_done=dict(resource=1, handle=3))
        w._fail(rollback, 'retire: job ended with status 110')
        self.assertIsNone(w.job); self.assertIn('could not be rolled back', notes[-1])

    def test_unstage_releases_only_the_checked_model(self):
        import gauntlet_reload as gr
        import extra_reload_retire as retire
        model, mid, guard = 0x008DD210, 3, 0x07000100
        code = gr.unstage_code([(guard, 7)], mid, model)

        def run(guard_value=7, released=1):
            m = Guest(dict(segments=[dict(address=retire.ENTRY, data_hex=code.hex())]))
            m.w(retire.CONTROL, 1); m.w(retire.CONTROL + 4, 0); m.w(guard, guard_value); m.w(model + 4, 1)
            calls = []

            def release(g):
                calls.append(g.r[4])
                if released:
                    g.w(model + 4, 0)
                g.r[2] = released
            m.callbacks[gr.UNSTAGE_RELEASE] = release
            m.r[31] = 0xFEED0000; m.run(retire.ENTRY)
            return m.u(retire.CONTROL + 4), calls, m.u(model + 4)
        self.assertEqual(run(), (5, [mid], 0))
        self.assertEqual(run(guard_value=8), (110, [], 1))                            # a guard changed: untouched
        self.assertEqual(run(released=0)[0], 160)

    def test_a_failed_load_is_retried_once_then_skipped(self):
        s = mode.Service(log=lambda m: None)
        skipped = []
        s.skip = lambda p, number: skipped.append(number)
        s.wave = lambda p, number: (1, [(90, 0, 0, 1000, 1000)])
        s.assigned[3] = (4, 0)
        s.finished(None, dict(physical=3, phase='failed', reason='stage: job ended with status 144'))
        self.assertEqual(skipped, [])                                                 # one retry
        s.assigned[3] = (4, 0)
        s.finished(None, dict(physical=3, phase='failed', reason='stage: job ended with status 144'))
        self.assertEqual(skipped, [4])

    def test_the_injection_hook_is_off_unless_named(self):
        import gauntlet_reload as gr
        self.assertIsNone(gr.injection('')); self.assertIsNone(gr.injection(None))
        self.assertEqual(gr.injection('io'), dict(step='io', count=1))
        with self.assertRaises(ValueError):
            gr.injection('commit')


if __name__ == '__main__':
    unittest.main()
