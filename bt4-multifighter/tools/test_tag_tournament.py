"""Tag Team Tournament (tag_tournament.py): guest code and its conditional pnach (run through a D-code
interpreter), the bracket model, team plans with drafted rosters (costumes, Potara items, leader adoption,
registration order), the roster draft passes, native text tables, the watcher controller against a fake PINE
(draft, routing with the auto entry, arming, the hand-made entry fallback, restart), the stand-ins for the type
menu / registration and the locked-entrant post-pass (run in a MIPS interpreter), the setup panel, Spanish strings
and the hooks other modules carry (pad mask, fade draw, draft owners, slot labels).
"""
import json
import random
import re
import struct
import tempfile
import unittest
from pathlib import Path

import battle_mode_policy as policy
import capstone
import localization as loc
import native_mode_menu as nmm
import native_preparation as prep
import tag_tournament as tt
import team_assignment as ta
from native_map import elf_path
from prototype import ROOT, elf_reader

NATIVE = elf_reader(elf_path(ROOT))[2]
MD = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS64 + capstone.CS_MODE_LITTLE_ENDIAN)


def entrants_blob(characters, humans=(), boss_character=56, order=None):
    """humans: entrant indices; order: their registration order (default: entrant order)."""
    blob = bytearray(tt.ENTRANTS * tt.ENTRANT_BYTES)
    order = list(order if order is not None else humans)
    for i, c in enumerate(list(characters) + [boss_character]):
        flags = (tt.HUMAN if i in humans else 0) | (tt.BOSS_FLAG if i == tt.BOSS else 0)
        struct.pack_into('<H', blob, i * tt.ENTRANT_BYTES, flags)
        struct.pack_into('<3I', blob, i * tt.ENTRANT_BYTES + 4, c, 0, order.index(i) if i in order else 0)
    return bytes(blob)


def rows_blob(pairs):
    blob = bytearray(16 * tt.ROW_RECORD)
    for k, (a, b) in enumerate(pairs):
        struct.pack_into('<4H', blob, k * tt.ROW_RECORD, 0, a, b, 8 + k // 2)
    return bytes(blob)


FIELD = [98, 151, 55, 150, 68, 57, 149, 28, 69, 79, 85, 70, 109, 158, 0, 2]
FIRST_ROUND = [(2 * k, 2 * k + 1) for k in range(8)]
ITEMS = bytes.fromhex('500143015301510156014f0100000000')


class FakePine:
    """EE memory (128 MiB, sparse above 32 MiB) and the calls the controller makes."""
    def __init__(self):
        self.mem = bytearray(0x2000000)
        self.high = {}

    def _page(self, a):
        return self.high.setdefault(a & ~0xFFFF, bytearray(0x10000))

    def read(self, a, n):
        if a >= 0x2000000:
            out = bytearray()
            while n:
                page, off = self._page(a), a & 0xFFFF
                k = min(n, 0x10000 - off)
                out += page[off:off + k]; a += k; n -= k
            return bytes(out)
        return bytes(self.mem[a:a + n])

    def write(self, a, data):
        if a >= 0x2000000:
            data = bytes(data)
            while data:
                page, off = self._page(a), a & 0xFFFF
                k = min(len(data), 0x10000 - off)
                page[off:off + k] = data[:k]; a += k; data = data[k:]
            return
        self.mem[a:a + len(data)] = data

    def read_u32(self, a):
        return struct.unpack('<I', self.read(a, 4))[0]

    def write_u32(self, a, v):
        self.write(a, struct.pack('<I', v))


def run_pnach(p, lines):
    """One frame of PCSX2's extended patch codes (2-codes and D-codes as tag_tournament emits them); returns the
    addresses written."""
    codes = [l.split(',') for l in lines if l.startswith('patch=')]
    written, i = [], 0

    def block(start, count):
        nonlocal written
        k = start
        end = start + count
        while k < end:
            address, value = int(codes[k][2], 16), codes[k][4]
            if codes[k][2][0] == 'D':
                n, t, v = int(value[:2], 16), int(value[2]), int(value[4:], 16)
                half = struct.unpack('<H', p.read(address & 0x0FFFFFFF, 2))[0]
                if (half == v) == (t == 0):
                    block(k + 1, n)
                k += 1 + n
                continue
            p.write_u32(address & 0x0FFFFFFF, int(value, 16)); written.append(address & 0x0FFFFFFF)
            k += 1
    while i < len(codes):
        n = int(codes[i][4][:2], 16) if codes[i][2][0] == 'D' else 0
        block(i, 1 + n)
        i += 1 + n
    return written


class GuestCode(unittest.TestCase):
    def test_hook_site_and_count_case_are_the_native_words(self):
        self.assertEqual(NATIVE(tt.HOOK, 8), struct.pack('<2I', *tt.ORIGINAL))
        self.assertEqual(struct.unpack('<I', NATIVE(tt.COUNT_CASE, 4))[0], tt.COUNT_FORCE)
        self.assertEqual(struct.unpack('<I', NATIVE(tt.COUNT_CASE - 8, 4))[0], tt.COUNT_KEEP)
        self.assertEqual(tt.RESUME, tt.HOOK + 8)

    def test_code_fits_its_slots_16_byte_frames_and_never_touches_k0_k1(self):
        pieces = [(tt.CODE, tt.cave_code(), tt.TYPE_STUB), (tt.TYPE_STUB, tt.type_stub(), tt.ENTRY_STUB),
                  (tt.ENTRY_STUB, tt.entry_stub(), tt.TRAMP), (tt.TRAMP, tt.tramp_code(), tt.PAD_CODE),
                  (tt.PAD_CODE, tt.pad_code(), tt.DRAW_CODE), (tt.DRAW_CODE, tt.draw_code(), tt.SETUP_STUB),
                  (tt.SETUP_STUB, tt.setup_stub(), tt.CONTROL), (tt.WATCH_CODE, tt.watch_code(), tt.DRAWBUF)]
        for base, blob, limit in pieces:
            self.assertLessEqual(base + len(blob), limit)
            for ins in MD.disasm(blob, base):
                self.assertNotRegex(ins.op_str, r'\$(k0|k1)\b', f'{ins.address:08X} {ins.mnemonic} {ins.op_str}')
                if ins.mnemonic == 'addiu' and ins.op_str.startswith('$sp, $sp'):
                    self.assertEqual(int(ins.op_str.rsplit(' ', 1)[1], 16) % 16, 0)
        used = {r for ins in MD.disasm(tt.cave_code(), tt.CODE) for r in re.findall(r'\$(s[0-7]|fp)\b', ins.op_str)}
        self.assertLessEqual(used, {f's{reg - 16}' for _, reg in tt.SAVED if 16 <= reg <= 23})
        used = {r for ins in MD.disasm(tt.draw_code(), tt.DRAW_CODE) for r in re.findall(r'\$(s[0-7]|fp)\b', ins.op_str)}
        self.assertLessEqual(used, {f's{reg - 16}' for _, reg in tt.DRAW_SAVED if 16 <= reg <= 23})
        used = {r for ins in MD.disasm(tt.setup_stub(), tt.SETUP_STUB) for r in re.findall(r'\$(s[0-7]|fp)\b', ins.op_str)}
        self.assertLessEqual(used, {f's{reg - 16}' for _, reg in tt.SETUP_SAVED if 16 <= reg <= 23})
        # the two stand-ins are leaves (no frame, no saved register): the dispatcher's a0 / ra reach the native
        for stub, base in ((tt.type_stub(), tt.TYPE_STUB), (tt.entry_stub(), tt.ENTRY_STUB)):
            self.assertFalse({r for ins in MD.disasm(stub, base) if ins.mnemonic != 'jr'
                              for r in re.findall(r'\$(s[0-7]|fp|sp|ra|a[0-3])\b', ins.op_str)})
        # the pad helper is a leaf without a frame: only temporaries
        self.assertFalse({r for ins in MD.disasm(tt.pad_code(), tt.PAD_CODE)
                          for r in re.findall(r'\$(s[0-7]|fp|sp|ra)\b', ins.op_str)} - {'ra'})

    def test_trampoline_is_the_relocated_prologue(self):
        tramp = list(MD.disasm(tt.tramp_code(), tt.TRAMP))
        self.assertEqual(tt.tramp_code()[:8], struct.pack('<2I', *tt.ORIGINAL))
        self.assertEqual((tramp[2].mnemonic, int(tramp[2].op_str, 16)), ('j', tt.RESUME))

    def test_pnach_installs_once_per_arming_or_draft_and_restores_once(self):
        p = FakePine()
        lines = tt.pnach_lines()
        for address, words in tt.NATIVE_WORDS:
            p.write(address, struct.pack(f'<{len(words)}I', *words))
        self.assertEqual(run_pnach(p, lines), [])                     # idle: nothing at all
        # drafting: the helpers and READY, never the row filler hook
        p.write_u32(tt.DRAFT, tt.DRAFT_MAGIC)
        written = run_pnach(p, lines)
        self.assertEqual(written[-1], tt.READY)
        self.assertEqual(p.read_u32(tt.READY), tt.READY_MAGIC)
        self.assertEqual(p.read(tt.PAD_CODE, len(tt.pad_code())), tt.pad_code())
        self.assertEqual(p.read(tt.DRAW_CODE, len(tt.draw_code())), tt.draw_code())
        self.assertEqual(p.read(tt.HOOK, 8), struct.pack('<2I', *tt.ORIGINAL))
        self.assertEqual(run_pnach(p, lines), [])                     # READY: no per-frame code writes
        p.write_u32(tt.DRAFT, 0)
        self.assertEqual(run_pnach(p, lines), [tt.READY])
        self.assertEqual(p.read_u32(tt.READY), 0)
        # armed: helpers, cave, count case and the hook (last of its block)
        p.write_u32(tt.CONTROL, tt.MAGIC)
        written = run_pnach(p, lines)
        self.assertIn(tt.HOOK, written)
        self.assertEqual(p.read(tt.HOOK, 8), tt.hook_words())
        self.assertEqual(p.read(tt.CODE, len(tt.cave_code())), tt.cave_code())
        self.assertEqual(p.read_u32(tt.COUNT_CASE), tt.COUNT_KEEP)
        self.assertLess(written.index(tt.CODE), written.index(tt.HOOK))
        self.assertEqual(run_pnach(p, lines), [])
        # disarmed: READY cleared, native words back once
        p.write_u32(tt.CONTROL, 0)
        run_pnach(p, lines)
        self.assertEqual(p.read(tt.HOOK, 8), struct.pack('<2I', *tt.ORIGINAL))
        self.assertEqual(p.read_u32(tt.COUNT_CASE), tt.COUNT_FORCE)
        self.assertEqual(p.read_u32(tt.READY), 0)
        self.assertEqual(run_pnach(p, lines), [])
        self.assertTrue(all(int(l.split(',')[4][:2], 16) < 200 for l in lines if l.split(',')[2].startswith('D')))

    def test_call_sites_are_the_native_calls(self):
        # the overlay is not in the executable: its words from the USA RAM the research read (DBZP.BIN at 0x334C00)
        for site, target, stub, _ in tt.call_sites():
            self.assertEqual(tt.jal(target) >> 26, 3)
            self.assertNotEqual(tt.jal(stub), tt.jal(target))
        self.assertEqual(tt.jal(0x364B18), 0x0C0D92C6)          # dispatcher 0x362220
        self.assertEqual(tt.jal(0x361D80), 0x0C0D8760)          # dispatcher 0x36229C
        self.assertEqual(tt.jal(0x369318), 0x0C0DA4C6)          # scene 35 fresh start 0x365020

    def test_call_sites_follow_the_auto_entry_and_the_arming(self):
        p = FakePine()
        lines = tt.pnach_lines()
        for address, words in tt.NATIVE_WORDS:
            p.write(address, struct.pack(f'<{len(words)}I', *words))
        sites = {site: (tt.jal(target), tt.jal(stub), auto) for site, target, stub, auto in tt.call_sites()}
        for site, (native, _, _) in sites.items():
            p.write_u32(site, native)
        word = lambda site: p.read_u32(site)
        p.write_u32(tt.CONTROL, tt.MAGIC)                       # armed without an auto entry: the post-pass only
        run_pnach(p, lines)
        self.assertEqual({s: word(s) == ours for s, (_, ours, auto) in sites.items()},
                         {s: not auto for s, (_, _, auto) in sites.items()})
        self.assertEqual(p.read(tt.TYPE_STUB, len(tt.type_stub())), tt.type_stub())
        p.write_u32(tt.AUTO, tt.AUTO_MAGIC)
        run_pnach(p, lines)
        self.assertTrue(all(word(s) == ours for s, (_, ours, _) in sites.items()))
        self.assertEqual(run_pnach(p, lines), [])                # once
        p.write_u32(tt.AUTO, 0)                                  # the registration stand-in consumed it
        run_pnach(p, lines)
        self.assertEqual({s: word(s) == native for s, (native, _, auto) in sites.items()},
                         {s: auto for s, (_, _, auto) in sites.items()})
        p.write_u32(tt.CONTROL, 0)
        run_pnach(p, lines)
        self.assertTrue(all(word(s) == native for s, (native, _, _) in sites.items()))
        self.assertEqual(run_pnach(p, lines), [])
        # another overlay (or a changed one) at the sites: never written
        q = FakePine()
        q.write_u32(tt.CONTROL, tt.MAGIC); q.write_u32(tt.AUTO, tt.AUTO_MAGIC)
        for site in sites:
            q.write_u32(site, 0x27BDFFF0)
        written = run_pnach(q, lines)
        self.assertFalse(set(written) & set(sites))
        # a stand-in missing (an armed state from an older build): its call is never redirected
        r = FakePine()
        for site, (native, _, _) in sites.items():
            r.write_u32(site, native)
        r.write(tt.HOOK, tt.hook_words())
        r.write_u32(tt.CONTROL, tt.MAGIC); r.write_u32(tt.AUTO, tt.AUTO_MAGIC)
        run_pnach(r, lines)
        self.assertTrue(all(r.read_u32(s) == native for s, (native, _, _) in sites.items()))

    def test_boot_pnach_carries_the_conditional_blocks(self):
        import guest_loading_screen as gls
        self.assertIn('\n'.join(tt.pnach_lines()), gls.pnach().decode())

    def test_reservation_is_referenced_by_no_other_module(self):
        here = Path(tt.__file__).parent
        hits = []
        for f in here.glob('*.py'):
            if f.name == 'tag_tournament.py' or f.name.startswith('test_'):
                continue
            for m in re.finditer(r'0x061[89][0-9A-Fa-f]{4}\b', f.read_text(encoding='utf-8', errors='replace')):
                hits.append((f.name, m.group(0)))
        self.assertEqual(hits, [])
        self.assertTrue(0x06000000 <= tt.BASE < tt.END <= 0x06400000)
        spans = sorted([(tt.CONTROL, tt.TABLE), (tt.TABLE, tt.TABLE + tt.ENTRANTS * tt.ENTRY),
                        (tt.DRAWBUF, tt.DRAWBUF + tt.DRAW_CAPACITY)] +
                       [(a, a + n) for a, n in tt.TEXT_SLOTS.items()])
        for (a0, a1), (b0, b1) in zip(spans, spans[1:]):
            self.assertLessEqual(a1, b0)
        self.assertLessEqual(spans[-1][1], tt.END)
        self.assertLessEqual(tt.DRAFT + 20, tt.READY)

    def test_resident_callers_check_ready(self):
        for blob, base, target in ((nmm.payload(), nmm.CODE, tt.PAD_CODE),):
            ins = list(MD.disasm(blob, base))
            calls = [k for k, i in enumerate(ins) if i.mnemonic == 'jal' and int(i.op_str, 16) == target]
            self.assertEqual(len(calls), 1)
        import native_menu_services as services
        ins = list(MD.disasm(services.fade(), services.FADE))
        self.assertEqual(sum(1 for i in ins if i.mnemonic == 'jal' and int(i.op_str, 16) == tt.DRAW_CODE), 1)
        # the pad mask runs after the P1/P2 assignment wrote the translated words
        import controller_assignment
        ins = list(MD.disasm(nmm.payload(), nmm.CODE))
        jal = [int(i.op_str, 16) for i in ins if i.mnemonic == 'jal']
        self.assertLess(jal.index(controller_assignment.CODE), jal.index(tt.PAD_CODE))

    def test_draft_owner_table_in_resolve_and_labels(self):
        import player_slot_labels as labels
        for blob in (ta.resolve_code(), labels.code()):
            # lui of the owner table and of its magic (word scan: capstone stops at EE-only instructions)
            luis = {w & 0xFFFF for w in struct.unpack(f'<{len(blob) // 4}I', blob) if w >> 26 == 15}
            self.assertIn(tt.DRAFT >> 16, luis)
            self.assertIn(tt.DRAFT_MAGIC >> 16, luis)


class CrowdShots(unittest.TestCase):
    def test_phase_zero_ends_at_once_before_the_loading(self):
        p = FakePine()
        battle = 0x00700000
        p.write_u32(tt.PHASE, battle)
        for sub in (0, 3, 5):
            p.write_u32(battle, tt.CROWD_PHASE); p.write_u32(battle + 8, sub)
            self.assertFalse(tt.skip_crowd_shots(p))
            self.assertEqual(p.read_u32(battle + 8), tt.CROWD_DONE)
        p.write_u32(battle, 1)                                   # phase 1 already: nothing written
        p.write_u32(battle + 8, 2)
        self.assertTrue(tt.skip_crowd_shots(p))
        self.assertEqual(p.read_u32(battle + 8), 2)
        p.write_u32(tt.PHASE, 0)
        self.assertTrue(tt.skip_crowd_shots(p))

    def test_the_done_substate_is_the_native_update_s_own(self):
        # 0x217CF0 (phase 0 update): substates below 7 through its jump table; case 6 returns phase 1 at once
        self.assertEqual(NATIVE(0x2C6070, 16), struct.pack('<4I', 0x217C40, 0x217C78, 0x217CF0, 0x217DB8))
        ins = list(MD.disasm(NATIVE(0x217CF0, 0x20), 0x217CF0))
        self.assertEqual((ins[5].mnemonic, ins[5].op_str), ('sltiu', '$v0, $v1, 7'))
        table = struct.unpack('<7I', NATIVE(0x2F1B10, 28))
        case6 = list(MD.disasm(NATIVE(table[tt.CROWD_DONE], 8), table[tt.CROWD_DONE]))
        self.assertEqual((case6[0].mnemonic, case6[0].op_str), ('addiu', '$v0, $zero, 1'))

    def test_the_intro_starts_with_the_crowd_after_the_loading(self):
        import team_intro
        from native_map import A
        p = FakePine()
        battle = 0x00700000
        p.write_u32(team_intro.BATTLE, battle)
        p.write_u32(battle + 260, A(0x2C6070))
        p.write_u32(A(0x2C6070), A(0x217C40))
        self.assertTrue(team_intro.crowd_first(p))
        self.assertEqual(p.read_u32(team_intro.CROWD), 1)
        q = FakePine(); q.write_u32(team_intro.BATTLE, battle); q.write_u32(battle + 260, 0x2C6130)
        self.assertFalse(team_intro.crowd_first(q))
        self.assertEqual(q.read_u32(team_intro.CROWD), 0)
        # the intro program enters phase 0 (0x217C40, index 0) when asked, else phase 1 as before
        words = struct.unpack(f'<{len(team_intro.payload(0x100000)) // 4}I', team_intro.payload(0x100000))
        calls = [w & 0x3FFFFFF for w in words if w >> 26 == 3]
        self.assertEqual(calls.count(A(0x216AF8) >> 2), 3)        # phase 0 enter + its shot starter, phase 1
        luis = [(w & 0xFFFF) << 16 for w in words if w >> 26 == 15]
        oris = [w & 0xFFFF for w in words if w >> 26 == 13]
        self.assertIn(A(0x217C40) & 0xFFFF0000, luis)
        self.assertIn(A(0x217C40) & 0xFFFF, oris)


class Model(unittest.TestCase):
    def test_entrants_rows_and_the_native_side_rule(self):
        ents = tt.parse_entrants(entrants_blob(FIELD, humans=(14,)))
        rows = tt.parse_rows(rows_blob(FIRST_ROUND))
        self.assertTrue(ents[14].human and not ents[15].human)
        self.assertEqual(tt.sides(ents, rows[7]), (14, 15))
        self.assertEqual(tt.sides(tt.parse_entrants(entrants_blob(FIELD, humans=(15,))), rows[7]), (15, 14))
        ents = tt.parse_entrants(entrants_blob(FIELD, humans=(3, 9), order=(9, 3)))
        self.assertEqual((ents[9].player, ents[3].player), (0, 1))

    def test_settled_needs_every_entrant_seated_once_and_the_boss(self):
        ents = tt.parse_entrants(entrants_blob(FIELD, humans=(14,)))
        self.assertTrue(tt.settled(ents, tt.parse_rows(rows_blob(FIRST_ROUND))))
        self.assertFalse(tt.settled(ents, tt.parse_rows(bytes(16 * tt.ROW_RECORD))))

    def test_results(self):
        self.assertEqual(tt.surrender_reason(0), tt.SURRENDER_SIDE1)
        self.assertEqual([tt.winner_side(f) for f in (0, 1, 2, 8, 9, 0xA, 3)], [None, 0, 1, None, 0, 1, None])
        with self.assertRaises(ValueError):
            tt.surrender_reason(2)


class Setups(unittest.TestCase):
    def test_teams_owners_entry_count_and_problems(self):
        s = tt.Setup(3, {1: 0, 2: 0, 3: 1, 4: 1})
        self.assertEqual(s.teams, [(0, (1, 2)), (1, (3, 4))])
        self.assertEqual((s.owners(0), s.owners(1)), ((1, 2, 0), (3, 4, 0)))
        self.assertEqual(s.entry_count(), 2)
        self.assertIsNone(s.problem())
        self.assertEqual(tt.Setup(1, {1: 0, 2: 0}).problem(), (tt.TOO_MANY, dict(t=1)))
        self.assertEqual(tt.Setup(2).entry_count(), 1)
        self.assertTrue(tt.Setup(2).cpu_only)
        self.assertEqual(tt.Setup.from_json(json.loads(json.dumps(s.to_json()))).teams, s.teams)
        kinds = tt.Setup(2, {1: 0}, 'skip', 2, 1)
        again = tt.Setup.from_json(json.loads(json.dumps(kinds.to_json())))
        self.assertEqual((again.kind, again.level, again.cpu_matches), (2, 1, 'skip'))
        self.assertEqual((tt.Setup.from_json(dict(size=2)).kind, tt.Setup.from_json(dict(size=2)).level), (0, 0))
        for bad in ((0, {}), (6, {}), (3, {2: 0}), (3, {1: 4}), (3, {}, 'ask', 5), (3, {}, 'ask', 0, 3)):
            with self.assertRaises(ValueError):
                tt.Setup(*bad)

    def test_draft_passes_and_receipts(self):
        s = tt.Setup(3, {1: 0, 2: 1, 3: 2})
        self.assertEqual(tt.draft_passes(s), [(0, 1), (2,)])
        self.assertEqual(tt.draft_passes(tt.Setup(1, {1: 0, 2: 1})), [(0, 1)])    # teams of one are drafted too
        self.assertEqual(tt.draft_passes(tt.Setup(3)), [(0,)])                    # CPU only: the team to follow
        self.assertEqual(tt.pass_receipt(tt.Setup(3), (0,)), (1, 1, (0xFFFFFFFF,) * 4, 0, (0,) * 12))
        choice, humans, seats, valid, owners = tt.pass_receipt(s, (0, 1))
        self.assertEqual((choice, humans, valid), (17, 3, 1))
        self.assertEqual(seats, (0, 1, 0xFFFFFFFF, 0xFFFFFFFF))
        # slot 0 by its player, CPU slots and END (slot `count`) by the team's first player
        self.assertEqual(owners, (1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2))
        choice, humans, seats, valid, owners = tt.pass_receipt(s, (2,))
        self.assertEqual(seats, (0xFFFFFFFF, 0xFFFFFFFF, 0, 0xFFFFFFFF))   # player 3 keeps its own lane
        self.assertEqual(owners[0::2], (3,) * 6)
        s = tt.Setup(3, {1: 0, 2: 0, 3: 1, 4: 1})
        choice, humans, seats, valid, owners = tt.pass_receipt(s, (0, 1))
        self.assertEqual((choice, seats), (12, (0, 2, 1, 3)))
        self.assertEqual(owners[:6], (1, 3, 2, 4, 1, 3))
        self.assertEqual(ta.TEAM_CHOICES[choice], 4)
        self.assertEqual(tt.pass_receipt(tt.Setup(2, {1: 0}), (0,))[:2], (1, 1))


class Plans(unittest.TestCase):
    def ents(self, humans=(14,), order=None):
        return tt.parse_entrants(entrants_blob(FIELD, humans=humans, order=order))

    def test_sizes_rosters_unique_random_members_and_no_random_giants(self):
        for size in range(1, 6):
            roster = [tt.member(0, 2, ITEMS), tt.member(29, 1), tt.member(12, 0, ITEMS)][:size]
            plan = tt.Plan(tt.Setup(size, {1: 0}), [roster], seed=size).build(self.ents())
            for i, team in enumerate(plan.teams):
                self.assertEqual(len(team), size)
                self.assertEqual(team[0][0], (FIELD + [56])[i])
            if size >= 2:
                self.assertEqual(plan.teams[14][1], (29, 1, bytes(16)))
            if size >= 3:
                self.assertEqual(plan.teams[14][2], (12, 0, ITEMS))      # a picked giant, its own Potara
            randoms = [m[0] for i, t in enumerate(plan.teams) if i != 14 for m in t[1:]]
            names = [tt.character_name(c) for c in randoms]
            self.assertFalse([n for n in names if any(w in n for w in tt.GIANT_NAMES)])
            for i, t in enumerate(plan.teams):
                if i != 14:
                    self.assertEqual(len({m[0] for m in t}), size)
            self.assertEqual(plan.flags[14], 0)
            self.assertEqual(plan.flags[0], tt.COPY_LEADER_ITEMS)

    def test_registration_order_maps_teams_and_adopts_a_different_leader(self):
        s = tt.Setup(2, {1: 0, 2: 1})
        rosters = [[tt.member(14, 1), tt.member(29)], [tt.member(85), tt.member(31)]]
        # Team 1's player registered second (entrant 3), team 2's first (entrant 9)
        plan = tt.Plan(s, rosters, seed=1).build(self.ents((3, 9), order=(9, 3)))
        self.assertEqual((plan.players[9], plan.players[3]), ((1,), (2,)))
        self.assertEqual(plan.teams[9][1][0], 29)
        self.assertEqual(plan.teams[3][1][0], 31)
        self.assertEqual(sorted(n['team'] for n in plan.notes), [0, 1])     # neither registered its drafted leader
        same = tt.Plan(s, [[tt.member(FIELD[9]), tt.member(29)], []], seed=1).build(self.ents((3, 9), order=(9, 3)))
        self.assertEqual(same.notes, [])

    def test_cpu_only_follows_the_drafted_team(self):
        plan = tt.Plan(tt.Setup(3), [[tt.member(FIELD[14], 1, ITEMS), tt.member(29, 2), tt.member(31)]],
                       seed=4).build(self.ents())
        self.assertEqual(plan.teams[14], [(FIELD[14], 0, bytes(16)), (29, 2, bytes(16)), (31, 0, bytes(16))])
        self.assertEqual((plan.players[14], plan.flags[14], plan.notes), ((), 0, []))
        self.assertEqual(plan.match(14, 15), (0, None, ()))

    def test_same_seed_same_teams(self):
        s = tt.Setup(5, {1: 0})
        a = tt.Plan(s, seed='x').build(self.ents()).teams
        self.assertEqual(a, tt.Plan(s, seed='x').build(self.ents()).teams)
        self.assertNotEqual(a, tt.Plan(s, seed='y').build(self.ents()).teams)

    def test_table_layout_with_costumes_and_items(self):
        plan = tt.Plan(tt.Setup(3, {1: 0}), [[tt.member(0), tt.member(29, 3, ITEMS), tt.member(31, 1)]],
                       seed=2).build(self.ents())
        table = plan.table()
        self.assertEqual(len(table), tt.ENTRANTS * tt.ENTRY)
        at = 14 * tt.ENTRY
        self.assertEqual(struct.unpack_from('<2I', table, at), (3, 0))
        self.assertEqual(struct.unpack_from('<2I', table, at + 8 + tt.MEMBER), (29, 3))
        self.assertEqual(table[at + 8 + tt.MEMBER + 8:at + 8 + 2 * tt.MEMBER], ITEMS)
        self.assertEqual(struct.unpack_from('<2I', table, 0), (3, tt.COPY_LEADER_ITEMS))
        restored = tt.Plan.from_json(json.loads(json.dumps(plan.to_json())))
        self.assertEqual(restored.table(), table)

    def test_match_seats_and_controller_order(self):
        s = tt.Setup(3, {1: 0, 2: 1, 3: 0})
        plan = tt.Plan(s, seed=3).build(self.ents((3, 9), order=(3, 9)))
        self.assertEqual(plan.players[3], (1, 3))
        humans, seats, order = plan.match(9, 3)          # P2's team on side 0, P1+P3 on side 1
        self.assertEqual((humans, seats, order), (3, (1, 0, 3), (1, 2, 3)))
        self.assertEqual(policy.human_seats('teams', humans, assignment=seats), seats)
        self.assertEqual(plan.match(9, 0), (1, (0,), (2,)))     # a lone player 2 drives match slot 1
        self.assertEqual(plan.match(0, 1), (0, None, ()))
        for k in range(200):
            r = random.Random(k)
            size, n = r.randint(1, 5), r.randint(1, 4)
            humans = {p: r.randint(0, 3) for p in range(1, n + 1)}
            setup = tt.Setup(size, humans)
            if setup.problem():
                continue
            plan = tt.Plan(setup, seed=k).build(self.ents(tuple(range(len(setup.teams)))))
            a, b = r.sample(range(17), 2)
            count, seats, order = plan.match(a, b)
            if count >= 2:
                self.assertEqual(policy.human_seats('teams', count, assignment=seats), seats)
            self.assertEqual(len(order), count)


class Draft(unittest.TestCase):
    def select(self, p, left, right, done=(False, False), stage=False):
        obj, rosters = 0x00900000, (0x00910000, 0x00911000)
        p.write_u32(tt.TEAM_SELECT, obj)
        p.write_u32(obj + 0x3C, 2)
        p.write_u32(obj + tt.SEL_FLAGS, 4 if stage else 0)
        for side, (roster, picks) in enumerate(zip(rosters, (left, right))):
            p.write_u32(obj + tt.SEL_SIDES + 4 * side, roster)
            for i, (c, k, items) in enumerate(picks):
                rec = bytearray(tt.SEL_RECORD)
                struct.pack_into('<2I', rec, 0x18, k, c)
                rec[0x20:0x30] = items
                p.write(roster + i * tt.SEL_RECORD, bytes(rec))
            p.write_u32(roster + tt.SEL_COUNT, len(picks))
            p.write_u32(roster + tt.SEL_STATE, tt.SEL_DONE if done[side] else 6)
        return obj, rosters

    def test_reads_picks_with_costume_and_items_and_completes_a_lone_side(self):
        p = FakePine()
        self.select(p, [(0, 2, ITEMS), (29, 1, bytes(16))], [], done=(True, False))
        self.assertEqual(tt.read_selection(p, 0), [(0, 2, ITEMS), (29, 1, bytes(16))])
        obj, sides = tt.selection_state(p)[:2]
        self.assertTrue(tt.complete_unused_side(p, obj, sides))
        obj, sides, stage = tt.selection_state(p)
        self.assertEqual([s[1] for s in sides], [tt.SEL_DONE, tt.SEL_DONE])
        self.assertEqual(tt.read_selection(p, 1), [(0, 2, ITEMS)])


class NativeTexts(unittest.TestCase):
    def native_table(self, strings):
        return tt.build_dbt([tt.BOM + s.encode('utf-16-le') for s in strings])

    def test_dbt_round_trip(self):
        p = FakePine()
        p.write(0x00700000, self.native_table(['a', 'bb', 'Those who wish to enter']))
        self.assertEqual(tt.read_dbt(p, 0x00700000)[2], tt.BOM + 'Those who wish to enter'.encode('utf-16-le'))
        self.assertIsNone(tt.read_dbt(p, 0x00710000))

    def test_announcer_opening_lines_point_at_our_copy(self):
        p = FakePine()
        entry, window, table = 0x00B80000, 0x0107C300, 0x00DAEEA0
        p.write_u32(tt.ENTRY_OBJECT, entry)
        p.write_u32(tt.ANNOUNCER_WINDOW, window)
        p.write_u32(entry + tt.ENTRY_TEXTS, table)
        p.write(table, self.native_table([f'line {i}' for i in range(246)]))
        p.write_u32(window + 0x48, table)
        text = tt.NativeText()
        self.assertTrue(text.announce(p, 'Team 2 · Player 3, this way please!\nRegister.'))
        self.assertEqual(p.read_u32(window + 0x48), tt.ANNOUNCE)
        ours = tt.read_dbt(p, tt.ANNOUNCE)
        self.assertEqual(ours[34].decode('utf-16-le'), '﻿Team 2 - Player 3, this way please!\nRegister.')
        self.assertEqual(ours[35].decode('utf-16-le'), '﻿line 35')
        self.assertEqual(len(ours), 246)

    def test_vs_form_lines_per_side(self):
        p = FakePine()
        obj, forms = 0x008C02E0, 0x00DB0000
        p.write_u32(obj + tt.OBJ_FORMS, forms)
        p.write(forms, self.native_table([f'form {i}' for i in range(0xA8)]))
        for side in range(2):
            p.write_u32(obj + tt.OBJ_FORM_TEXT + 0x8C * side + 4, forms)
        p.write(obj + tt.OBJ_ENTRANTS, entrants_blob(FIELD, humans=(2,)))
        p.write(obj + tt.OBJ_ROWS, rows_blob(FIRST_ROUND))
        p.write_u32(obj + tt.OBJ_ROW, 1)
        self.assertTrue(tt.NativeText().vs_lines(p, obj, {2: 'Team of 3: Vegeta, Piccolo', 3: 'Team of 2: Nam'}))
        left = tt.read_dbt(p, p.read_u32(obj + tt.OBJ_FORM_TEXT + 4))
        right = tt.read_dbt(p, p.read_u32(obj + tt.OBJ_FORM_TEXT + 0x8C + 4))
        self.assertEqual(left[FIELD[2]].decode('utf-16-le'), '﻿Team of 3: Vegeta, Piccolo')
        self.assertEqual(right[FIELD[3]].decode('utf-16-le'), '﻿Team of 2: Nam')
        self.assertEqual(left[FIELD[3]].decode('utf-16-le'), f'﻿form {FIELD[3]}')


class FakeHub:
    def __init__(self):
        self.orders = []

    def set_order(self, order):
        self.orders.append(tuple(order) if order else None)


class WatcherController(unittest.TestCase):
    def setUp(self):
        self.p = FakePine()
        self.c = tt.Controller()
        self.c.log = lambda text: None
        self.c.hub = FakeHub()
        self.tmp = tempfile.TemporaryDirectory()
        self.c.state_dir = Path(self.tmp.name)
        self.manager = 0x00600000
        self.p.write_u32(tt.SCENE_MANAGER, self.manager)

    def tearDown(self):
        self.tmp.cleanup()

    def scene(self, n):
        self.p.write_u32(self.manager + 0x18, n)

    def pager(self):
        self.p.write_u32(nmm.CONTROL, nmm.MAGIC)
        self.p.write_u32(nmm.CONTROL + 4, 2)

    def bracket(self, humans=(14,), order=None):
        obj = 0x00800000
        self.p.write_u32(tt.RUNTIME, obj)
        for base in (obj + tt.OBJ_ENTRANTS, self.manager + tt.MGR_ENTRANTS):
            self.p.write(base, entrants_blob(FIELD, humans=humans, order=order))
        self.p.write(obj + tt.OBJ_ROWS, rows_blob(FIRST_ROUND))
        self.p.write(self.manager + tt.MGR_ROWS, rows_blob(FIRST_ROUND))
        return obj

    def armed(self, setup, rosters=None):
        self.c.setup = setup
        self.c.rosters = rosters or [[] for _ in setup.teams]
        self.c.select(); self.scene(33); self.c.tick(self.p)
        self.assertTrue(self.c.armed)

    def test_draft_commits_reads_restores_then_routes_to_dragon_world_tour(self):
        setup = tt.Setup(2, {1: 0, 2: 1})
        self.c.begin(setup)
        self.assertTrue(self.c.drafting)
        self.scene(4); self.pager()
        self.c.menu_tick(self.p)
        self.assertEqual(self.p.read_u32(ta.MENU + ta.STATE), 2)
        self.assertEqual(self.p.read_u32(ta.MENU + ta.CHOICE), 7)
        self.assertEqual(self.p.read_u32(ta.MENU + ta.VALID), 1)
        self.assertEqual(self.p.read_u32(tt.DRAFT), 0)                 # never published at the main menu
        self.p.write_u32(ta.MENU + ta.STATE, 0)
        self.scene(40)
        Draft().select(self.p, [(5, 1, ITEMS), (29, 0, bytes(16))], [(85, 3, bytes(16)), (31, 0, bytes(16))],
                       done=(True, True), stage=True)
        self.c.menu_tick(self.p)
        self.assertEqual(self.p.read_u32(tt.DRAFT), tt.DRAFT_MAGIC)
        self.assertEqual(self.p.read(tt.DRAFT + 4, 13)[-1], 2)          # team size for the labels
        self.assertTrue(self.c.want_main)
        self.assertEqual(self.c.rosters, [[(5, 1, ITEMS), (29, 0, bytes(16))], [(85, 3, bytes(16)), (31, 0, bytes(16))]])
        self.scene(4)
        self.c.main_restored(self.p)
        self.assertEqual(self.p.read_u32(tt.DRAFT), 0)
        self.c.menu_tick(self.p)
        self.assertEqual((self.p.read_u32(ta.MENU + ta.STATE), self.p.read_u32(ta.MENU + ta.CHOICE)), (2, tt.CHOICE))
        self.assertTrue(self.c.route_ready() and self.c.armed and self.c.routing)
        self.assertEqual((self.p.read_u32(tt.CONTROL), self.p.read_u32(prep.ACCEPTED_MODE)),
                         (tt.MAGIC, tt.TOURNAMENT_MODE))
        auto = self.p.read(tt.AUTO, tt.AUTO_ENTRY + 2 * tt.AUTO_STRIDE)
        self.assertEqual(struct.unpack_from('<4I', auto), (tt.AUTO_MAGIC, 0, 0, 2))
        self.assertEqual(struct.unpack_from('<3I', auto, tt.AUTO_ENTRY), (5, 1, tt.HUMAN | tt.CUSTOM))
        self.assertEqual(auto[tt.AUTO_ENTRY + 16:tt.AUTO_ENTRY + 32], ITEMS)
        self.assertEqual(struct.unpack_from('<3I', auto, tt.AUTO_ENTRY + tt.AUTO_STRIDE), (85, 3, tt.HUMAN))
        self.c.tick(self.p)                                     # still the main menu: the route keeps it
        self.assertTrue(self.c.armed)
        self.c.select()                                         # the page's commit receipt changes nothing
        self.assertFalse(self.c.pending)
        self.scene(33); self.c.tick(self.p)
        self.assertTrue(self.c.armed and not self.c.routing)
        self.assertEqual(self.p.read_u32(tt.CONTROL + tt.F['draw_len']), 0)   # no entry guidance: the stand-ins
        saved = json.loads((self.c.state_dir / tt.STATE_FILE).read_text())
        self.assertEqual(len(saved['rosters']), 2)

    def route(self, setup, rosters):
        self.c.setup, self.c.rosters = setup, rosters
        self.scene(4)
        self.c.arm(self.p, auto=True)

    def test_a_route_that_never_leaves_the_main_menu_ends(self):
        self.route(tt.Setup(2, {1: 0}), [[tt.member(14)]])
        self.c.routed_at -= tt.ROUTE_SECONDS + 1
        self.c.tick(self.p)
        self.assertFalse(self.c.armed)
        self.assertEqual((self.p.read_u32(tt.CONTROL), self.p.read_u32(tt.AUTO)), (0, 0))

    def test_the_tournament_menu_after_the_bracket_ends_it(self):
        self.route(tt.Setup(2, {1: 0}), [[tt.member(14), tt.member(29)]])
        self.p.write_u32(tt.AUTO, 0)                            # the registration stand-in consumed it
        self.scene(35); self.bracket(); self.c.tick(self.p)
        self.assertTrue(self.c.bracket_seen)
        self.scene(33); self.c.tick(self.p)                     # Eliminated / champion: Dragon World Tour's menu
        self.assertFalse(self.c.armed)
        self.assertEqual(self.p.read_u32(tt.CONTROL), 0)

    def test_a_menu_the_stand_ins_did_not_answer_falls_back_to_the_guided_entry(self):
        self.route(tt.Setup(2, {1: 0, 2: 1}), [[tt.member(14)], [tt.member(29)]])
        self.scene(33); self.c.tick(self.p)
        self.assertEqual(self.p.read_u32(tt.AUTO), tt.AUTO_MAGIC)
        self.assertEqual(self.p.read_u32(tt.CONTROL + tt.F['draw_len']), 0)
        self.c.auto_since -= tt.AUTO_GRACE + 1
        self.c.tick(self.p)
        self.assertEqual(self.p.read_u32(tt.AUTO), 0)
        self.assertGreater(self.p.read_u32(tt.CONTROL + tt.F['draw_len']), 0)   # the How-many-people banner

    def test_a_restored_armed_state_is_cleared_at_the_main_menu(self):
        self.p.write_u32(tt.CONTROL, tt.MAGIC); self.p.write_u32(tt.AUTO, tt.AUTO_MAGIC)
        self.c.cleared = True                                   # (not the first tick of a new watcher)
        self.scene(4); self.c.tick(self.p)
        self.assertEqual((self.p.read_u32(tt.CONTROL), self.p.read_u32(tt.AUTO)), (0, 0))

    def test_teams_of_one_and_cpu_only_are_drafted_then_registered(self):
        for setup, picks, expect in ((tt.Setup(1, {1: 0, 2: 1}), ([(5, 0, bytes(16))], [(85, 2, bytes(16))]), 2),
                                     (tt.Setup(2), ([(14, 1, ITEMS), (29, 0, bytes(16))], []), 1)):
            c = tt.Controller(); c.log = lambda t: None; c.hub = FakeHub(); c.state_dir = self.c.state_dir
            p = FakePine(); p.write_u32(tt.SCENE_MANAGER, self.manager)
            self.p, self.c = p, c
            c.begin(setup)
            self.scene(4); self.pager(); c.menu_tick(p)
            self.assertEqual(p.read_u32(ta.MENU + ta.STATE), 2)
            p.write_u32(ta.MENU + ta.STATE, 0)
            self.scene(40)
            Draft().select(p, picks[0], picks[1], done=(True, bool(picks[1])), stage=bool(picks[1]))
            c.menu_tick(p)
            if not picks[1]:                                     # a lone side: the mod completes the other
                Draft().select(p, picks[0], picks[0][:1], done=(True, True), stage=True)
                c.menu_tick(p)
            self.assertTrue(c.want_main)
            self.scene(4); c.main_restored(p); c.menu_tick(p)
            self.assertTrue(c.armed)
            auto = p.read(tt.AUTO, tt.AUTO_ENTRY + 2 * tt.AUTO_STRIDE)
            self.assertEqual(struct.unpack_from('<I', auto, 12)[0], expect)
            self.assertEqual(struct.unpack_from('<2I', auto, tt.AUTO_ENTRY), picks[0][0][:2])

    def test_arm_on_dragon_world_tour_never_at_the_main_menu(self):
        self.c.setup = tt.Setup(3, {1: 0})
        self.c.select()
        self.scene(4); self.c.tick(self.p)
        self.assertFalse(self.c.armed)
        self.scene(33); self.c.tick(self.p)
        self.assertEqual((self.p.read_u32(tt.CONTROL), self.p.read_u32(prep.ACCEPTED_MODE)),
                         (tt.MAGIC, tt.TOURNAMENT_MODE))
        self.scene(6); self.c.tick(self.p)
        self.assertTrue(self.c.armed)
        self.scene(4); self.c.tick(self.p)
        self.assertFalse(self.c.armed)
        self.assertEqual((self.p.read_u32(tt.CONTROL), self.p.read_u32(prep.ACCEPTED_MODE)), (0, 0))
        self.assertEqual(self.c.hub.orders[-1], None)
        self.assertFalse((self.c.state_dir / tt.STATE_FILE).exists())

    def test_entry_blocks_a_wrong_count_and_routes_each_turn(self):
        self.armed(tt.Setup(3, {1: 0, 2: 1, 3: 1}), [[tt.member(14)], []])
        self.scene(34)
        self.p.write_u32(self.manager + tt.MGR_HUMANS, 3)
        self.c.tick(self.p)
        self.assertEqual(self.p.read_u32(tt.CONTROL + tt.F['block']), 1)
        self.assertGreater(self.p.read_u32(tt.CONTROL + tt.F['draw_len']), 0)
        self.p.write_u32(self.manager + tt.MGR_HUMANS, 2)
        entry, turn = 0x00B80000, 0x00B90000
        self.p.write_u32(tt.ENTRY_OBJECT, entry)
        self.p.write_u32(entry + tt.ENTRY_TURN_OBJECT, turn)
        for k, player in ((0, 1), (1, 2)):
            self.p.write_u32(turn + tt.ENTRY_TURN, k)
            self.c.tick(self.p)
            self.assertEqual(self.c.hub.orders[-1], (player,))
        self.assertEqual(self.p.read_u32(tt.CONTROL + tt.F['block']), 0)

    def test_plan_no_team_marks_and_the_launched_match_order(self):
        self.armed(tt.Setup(3, {1: 0, 2: 0}), [[tt.member(0), tt.member(29, 2, ITEMS), tt.member(31)]])
        self.scene(35)
        obj = self.bracket()
        self.layout(obj, 0x00840000)
        for _ in range(3):
            self.c.tick(self.p)
        plan = self.c.plan
        self.assertEqual(plan.teams[14][1], (29, 2, ITEMS))
        self.assertEqual(self.p.read(tt.TABLE, len(plan.table())), plan.table())
        self.assertEqual(self.p.read_u32(tt.CONTROL + tt.F['draw_len']), 0)   # nothing drawn over the bracket
        self.assertFalse(hasattr(tt, 'team_badges') or hasattr(tt, 'bracket_positions'))
        self.assertEqual(self.c.team_line(14), 'with ' + ', '.join(tt.short_name(c) for c in (29, 31)))
        self.p.write_u32(self.manager + tt.MGR_MATCH, 7)
        self.p.write_u32(tt.SETUP + 8, tt.TOURNAMENT_MODE)
        for side, e in ((0, 14), (1, 15)):
            self.p.write_u32(tt.SETUP + 0xC0 + side * tt.SIDE_STRIDE, 3)
            self.p.write_u32(tt.SETUP + 0xC4 + side * tt.SIDE_STRIDE, plan.teams[e][0][0])
        match = self.c.match_for(self.p)
        self.assertEqual((match['entrants'], match['humans'], match['assignment'], match['order']),
                         ((14, 15), 2, (0, 2), (1, 2)))
        self.assertEqual(self.c.hub.orders[-1], (1, 2))
        self.assertIs(self.c.match_for(self.p), match)          # the same launch asked again (loading cards)
        self.c.record(0)
        self.assertEqual(self.c.hub.orders[-1], None)
        self.assertIsNot(self.c.match_for(self.p), match)       # recorded: a new launch of that row is a new match

    def layout(self, obj, start, kinds=('chara', 'frame_')):
        """A bracket layout element block: mc_tournament_chara%d / mc_tournament_frame_%d records, 228 bytes each."""
        n = 0
        self.p.write_u32(obj + 0x54, start); self.p.write_u32(obj + 0x58, start + 2 * 17 * 228 + 64)
        records = {}
        for kind in kinds:
            for i in range(17):
                rec = bytearray(228); rec[:24] = f'mc_tournament_{kind}{i}'.encode().ljust(24, bytes(1))
                struct.pack_into('<2f', rec, 76, 51 + 58 * i, 269.0)
                self.p.write(start + 32 + n * 228, bytes(rec)); records[(kind, i)] = start + 32 + n * 228; n += 1
        return records

    def test_records_follow_a_new_layout_block_of_the_same_object(self):
        obj = 0x00800000
        cache = {}
        first = self.layout(obj, 0x00840000)
        self.assertEqual(tt.bracket_records(self.p, obj, cache)[3], first[('chara', 3)])
        second = self.layout(obj, 0x00850000)                     # the bracket rebuilt after a return
        self.assertEqual(tt.bracket_records(self.p, obj, cache)[3], second[('chara', 3)])
        self.assertEqual(tt.bracket_records(self.p, obj, cache, 'frame_')[3], second[('frame_', 3)])

    def test_a_marked_cpu_entrant_keeps_a_cpu_portrait_frame(self):
        self.armed(tt.Setup(2, {1: 0}, 'ask'))
        self.scene(35)
        obj = self.bracket(humans=(14, 4))                         # 4: the stop mark on row 2's A
        records = self.layout(obj, 0x00840000)
        for e in (14, 4, 6):                                       # the bracket styled all three as human
            self.p.write_u32(records[('frame_', e)] + tt.FRAME_CELL, tt.FRAME_HUMAN)
            self.p.write_u32(records[('frame_', e)] + tt.FRAME_FLAGS, tt.FRAME_TAG | 1)
        self.p.write_u32(tt.CONTROL + tt.F['wstop'], 3)
        self.c.tick(self.p)
        cell = lambda e: self.p.read_u32(records[('frame_', e)] + tt.FRAME_CELL)
        flags = lambda e: self.p.read_u32(records[('frame_', e)] + tt.FRAME_FLAGS)
        self.assertEqual((cell(14), flags(14)), (tt.FRAME_HUMAN, tt.FRAME_TAG | 1))   # the real human keeps it
        self.assertEqual([(cell(e), flags(e)) for e in (4, 6)], [(0, 1), (0, 1)])

    def test_a_launch_protects_the_rows_its_return_would_resolve(self):
        self.armed(tt.Setup(2, {1: 0}, 'ask'))
        self.assertEqual(self.p.read_u32(tt.CONTROL + tt.F['watch']), 1)
        self.assertEqual(self.p.read_u32(tt.CONTROL + tt.F['wlease']), tt.WATCH_LEASE)   # primed at arming
        self.scene(35)
        obj = self.bracket(humans=(14,))
        self.p.write_u32(tt.CONTROL + tt.F['wlease'], 0)
        self.c.tick(self.p)
        self.assertEqual(self.p.read_u32(tt.CONTROL + tt.F['wlease']), tt.WATCH_LEASE)   # every bracket tick
        # row 1 (entrants 2 vs 3, CPU) launched as a watched match; rows 0 played
        rows = bytearray(rows_blob(FIRST_ROUND))
        struct.pack_into('<H', rows, 0, 1)
        for k in range(8):
            if k == 7:
                struct.pack_into('<H', rows, 16 * k, 2)             # last row of round 1
        struct.pack_into('<H', rows, 0, 1)
        self.p.write(self.manager + tt.MGR_ROWS, bytes(rows))
        self.p.write_u32(self.manager + tt.MGR_MATCH, 1)
        self.p.write_u32(tt.SETUP + 8, tt.TOURNAMENT_MODE)
        plan = self.c.plan
        for side, e in ((0, 3), (1, 2)):
            self.p.write_u32(tt.SETUP + 0xC0 + side * tt.SIDE_STRIDE, 2)
            self.p.write_u32(tt.SETUP + 0xC4 + side * tt.SIDE_STRIDE, plan.teams[e][0][0])
        match = self.c.match_for(self.p)
        self.assertTrue(match['watched'])
        self.assertEqual((match['entrants'], match['humans'], match['order']), ((3, 2), 0, ()))
        flag = lambda e: struct.unpack('<H', self.p.read(self.manager + tt.MGR_ENTRANTS + 40 * e, 2))[0] & 1
        played = lambda r: struct.unpack('<H', self.p.read(self.manager + tt.MGR_ROWS + 16 * r, 2))[0] & 1
        self.assertEqual((flag(3), flag(4)), (1, 1))                 # side-0 B marked; stop on row 2's A
        self.assertEqual([played(r) for r in range(8)], [1, 0, 0, 1, 1, 1, 1, 0])   # rows 3..6 protected, 7 human
        self.assertEqual(struct.unpack('<4I', self.p.read(tt.CONTROL + tt.F['wclean'], 16)),
                         (2, 4, 3, (1 << 3) | (1 << 4) | (1 << 5) | (1 << 6)))
        self.assertEqual(self.c.result_side(self.p, 1), 1)            # never a CPU-only follow move
        self.c.protect(self.p, self.manager, clear=True)
        self.assertEqual((flag(3), flag(4)), (0, 0))
        self.assertEqual([played(r) for r in range(8)], [1, 0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(self.p.read_u32(tt.CONTROL + tt.F['wclean']), 0)
        # always skip arms nothing
        c = tt.Controller(); c.log = lambda t: None; c.setup = tt.Setup(2, {1: 0}, 'skip'); c.select()
        c.arm(self.p)
        self.assertEqual(self.p.read_u32(tt.CONTROL + tt.F['watch']), 0)

    def test_the_question_waits_while_left_or_right_looks_over_the_bracket(self):
        self.armed(tt.Setup(2, {1: 0}, 'ask'))
        self.scene(35); obj = self.bracket(); self.c.tick(self.p)
        self.p.write_u32(tt.CONTROL + tt.F['ask'], 2)
        self.c.tick(self.p)
        self.assertEqual(self.c.question['row'], 1)
        self.c.question['since'] -= tt.QUESTION_SECONDS + 1
        self.p.write_u32(tt.PAD_RECORDS + 0x188, 0x2)           # Right / Left held on controller 1 (translated)
        self.c.tick(self.p)
        self.assertEqual(self.p.read_u32(tt.CONTROL + tt.F['answer']), 0)
        self.p.write_u32(tt.PAD_RECORDS + 0x188, 0)
        self.c.question['since'] -= tt.QUESTION_SECONDS + 1
        self.c.tick(self.p)
        self.assertEqual(self.p.read_u32(tt.CONTROL + tt.F['answer']), 2)   # no answer at all: skipped

    def test_a_restarted_watcher_re_arms_from_its_saved_state(self):
        rosters = [[tt.member(0), tt.member(29)]]
        self.armed(tt.Setup(2, {1: 0}), rosters)
        self.scene(35); self.bracket(); self.c.tick(self.p)
        table = self.c.plan.table()
        fresh = tt.Controller(); fresh.log = lambda t: None; fresh.state_dir = self.c.state_dir
        fresh.tick(self.p)
        self.assertTrue(fresh.armed)
        self.assertEqual(fresh.plan.table(), table)
        self.assertEqual(fresh.rosters, rosters)
        # a stale arming without a saved state is cleared
        (self.c.state_dir / tt.STATE_FILE).unlink()
        other = tt.Controller(); other.log = lambda t: None; other.state_dir = self.c.state_dir
        other.tick(self.p)
        self.assertFalse(other.armed)
        self.assertEqual(self.p.read_u32(tt.CONTROL), 0)

    def test_cpu_only_follows_the_winner_and_names_side_zero(self):
        self.armed(tt.Setup(2))
        self.scene(35); self.bracket(humans=(14,)); self.c.tick(self.p)
        self.c.match = dict(entrants=(14, 15), row=7, round=0)
        self.assertEqual(self.c.result_side(self.p, 1), 0)
        flags = lambda e: struct.unpack('<H', self.p.read(self.manager + tt.MGR_ENTRANTS + e * 40, 2))[0]
        self.assertEqual((flags(14) & tt.HUMAN, flags(15) & tt.HUMAN), (0, tt.HUMAN))

    def test_human_teams_keep_the_real_side_and_the_request_order(self):
        self.armed(tt.Setup(2, {1: 0}))
        self.scene(35); self.bracket(); self.c.tick(self.p)
        self.c.match = dict(entrants=(14, 15), row=7, round=0)
        self.assertEqual(self.c.result_side(self.p, 1), 1)
        order = []
        p = FakePine(); p.write_u32 = lambda a, v: order.append((a, v))
        tt.force_result(p, 0)
        self.assertEqual(order, [(tt.RESULT_REASON, tt.SURRENDER_SIDE1), (tt.RESULT_FLAGS, tt.LATCHED)])


class WatchHelper(unittest.TestCase):
    """watch_code run instruction by instruction (natives are callbacks): the bracket wait asks the first unplayed
    CPU row, withholds the pad and latches presses; Watch = the native accept; Skip = the native result and advance
    with a stop mark; the return clears the host's marks."""

    def machine(self, rows, humans=(), played=()):
        from test_ai_shadow import Mips

        class Cpu(Mips):
            instruction_budget = 200000

            def extra_instruction(self, ins, pc):
                op, rs, rt, rd = ins >> 26, (ins >> 21) & 31, (ins >> 16) & 31, (ins >> 11) & 31
                imm = ins & 65535
                signed = imm if imm < 32768 else imm - 65536
                if op == 37:
                    self.r[rt] = int.from_bytes(self.read(self.r[rs] + signed, 2), 'little')
                elif op == 41:
                    self.write(self.r[rs] + signed, (self.r[rt] & 0xFFFF).to_bytes(2, 'little'))
                elif op == 0 and ins & 63 == 0x18:
                    self.lo = (self.r[rs] * self.r[rt]) & 0xFFFFFFFF
                elif op == 0 and ins & 63 == 0x12:
                    self.r[rd] = self.lo
                elif op == 0 and ins & 63 == 2:
                    self.r[rd] = (self.r[rt] & 0xFFFFFFFF) >> ((ins >> 6) & 31)
                elif op == 0 and ins & 63 == 0x27:
                    self.r[rd] = ~(self.r[rs] | self.r[rt]) & 0xFFFFFFFF
                else:
                    raise AssertionError(f'Unsupported instruction {ins:08X} at {pc:08X}')
                return None

        c = Cpu({'segments': [dict(address=tt.WATCH_CODE, data_hex=tt.watch_code().hex())]})
        obj, manager = 0x00800000, 0x00600000
        c.w(tt.RUNTIME, obj); c.w(tt.SCENE_MANAGER, manager)
        c.w(tt.CONTROL, tt.MAGIC); c.w(tt.CONTROL + tt.F['watch'], 1); c.w(tt.CONTROL + tt.F['wlease'], 100)
        for base in (obj + tt.OBJ_ENTRANTS, manager + tt.MGR_ENTRANTS):
            c.write(base, entrants_blob(FIELD, humans=humans))
        for base in (obj + tt.OBJ_ROWS, manager + tt.MGR_ROWS):
            for k, (a, b) in enumerate(rows):
                c.write(base + 16 * k, struct.pack('<4H', 1 if k in played else 0, a, b, 8 + k // 2))
        c.w(obj + tt.OBJ_WAIT, 4); c.w(obj + tt.OBJ_ROW, 7)
        c.calls = []
        for name in ('VS_START', 'ACCEPT_SOUND', 'ROW_RESULT', 'ROW_ADVANCE'):
            c.callbacks[getattr(tt, name)] = (lambda n: lambda m: m.calls.append((n, m.r[4], m.r[5])))(name)
        c.obj, c.manager = obj, manager
        return c

    def frame(self, c):
        c.r[4], c.r[31] = tt.BRACKET_PAD_RETURN, 0xFEED0000
        self.assertEqual(c.run(tt.WATCH_CODE), 0xFEED0000)

    def flags(self, c, base, index, stride):
        return struct.unpack('<H', c.read(base + index * stride, 2))[0]

    def test_asks_the_first_unplayed_cpu_row_and_withholds_the_pad(self):
        c = self.machine(FIRST_ROUND, humans=(14,))
        c.w(tt.PAD_RECORDS + 0x18C, 0x200); c.w(tt.PAD_RECORDS + 0x150, 0x4000)
        self.frame(c)
        self.assertEqual(c.u(tt.CONTROL + tt.F['ask']), 1)
        self.assertEqual(c.u(c.obj + tt.OBJ_ROW), 0)
        self.assertEqual(c.u(tt.PAD_RECORDS + 0x18C), 0)
        self.assertEqual(c.u(tt.CONTROL + tt.F['wbuttons']), 0x4000)
        self.assertEqual(c.calls, [])
        # Left/Right (the held word's two scroll bits) still reach the bracket while it asks; nothing else
        c = self.machine(FIRST_ROUND, humans=(14,))
        for port in (0, 0x1C0):
            c.w(tt.PAD_RECORDS + port + 0x188, 0x200 | 0x2); c.w(tt.PAD_RECORDS + port + 0x18C, 0x200)
            c.w(tt.PAD_RECORDS + port + 0x190, 0x10)
        self.frame(c)
        self.assertEqual(c.u(tt.CONTROL + tt.F['ask']), 1)
        for port in (0, 0x1C0):
            self.assertEqual([c.u(tt.PAD_RECORDS + port + off) for off in (0x188, 0x18C, 0x190)], [0x2, 0, 0])
        # a busy bracket or another caller of the pad routine: nothing
        c3 = self.machine(FIRST_ROUND, humans=(14,)); c3.w(c3.obj + tt.OBJ_WAIT, 4 | 0x40); self.frame(c3)
        self.assertEqual(c3.u(tt.CONTROL + tt.F['ask']), 0)
        c4 = self.machine(FIRST_ROUND, humans=(14,)); c4.r[4] = 0
        c4.r[31] = 0xFEED0000; c4.run(tt.WATCH_CODE)
        self.assertEqual(c4.u(tt.CONTROL + tt.F['ask']), 0)

    def test_a_human_row_is_left_to_the_native(self):
        c = self.machine(FIRST_ROUND, humans=(0,))
        self.frame(c)
        self.assertEqual((c.u(tt.CONTROL + tt.F['ask']), c.u(c.obj + tt.OBJ_ROW)), (0, 7))

    def test_watch_is_the_native_accept(self):
        c = self.machine(FIRST_ROUND, humans=(14,), played=(0,))
        c.w(tt.CONTROL + tt.F['answer'], 1)
        self.frame(c)
        self.assertEqual(c.calls, [('VS_START', c.obj, c.calls[0][2]), ('ACCEPT_SOUND', 1, 1)])
        self.assertEqual(c.u(c.obj + tt.OBJ_ROW), 1)
        self.assertEqual(c.u(c.obj + tt.OBJ_WAIT), 0)
        self.assertEqual((c.u(tt.CONTROL + tt.F['ask']), c.u(tt.CONTROL + tt.F['answer'])), (0, 0))

    def test_skip_is_the_native_result_then_the_advance_with_a_stop_mark(self):
        c = self.machine(FIRST_ROUND, humans=(14,))
        seen = []
        c.callbacks[tt.ROW_ADVANCE] = lambda m: seen.append(self.flags(m, m.obj + tt.OBJ_ENTRANTS, 2, 40) & 1)
        c.w(tt.CONTROL + tt.F['answer'], 2)
        self.frame(c)
        self.assertEqual(c.calls, [('ROW_RESULT', c.obj, 0)])
        self.assertEqual(seen, [1])                            # row 1's A marked during the advance only
        self.assertEqual(self.flags(c, c.obj + tt.OBJ_ENTRANTS, 2, 40) & 1, 0)
        # an expired lease answers Skip too
        c = self.machine(FIRST_ROUND, humans=(14,)); c.w(tt.CONTROL + tt.F['wlease'], 0)
        self.frame(c)
        self.assertEqual(c.calls[0], ('ROW_RESULT', c.obj, 0))

    def test_the_return_clears_the_marks_and_the_stop_mark_waits_for_its_row(self):
        c = self.machine(FIRST_ROUND, humans=(14, 3, 4), played=(0, 1, 3))   # row 1 watched: B=3 marked; stop on 2.A=4
        c.write(tt.CONTROL + tt.F['wclean'], struct.pack('<4I', 2, 3 + 1, 3, (1 << 3)))
        c.w(c.obj + tt.OBJ_ROW, 1)
        self.frame(c)
        self.assertEqual(self.flags(c, c.obj + tt.OBJ_ENTRANTS, 3, 40) & 1, 0)
        self.assertEqual(self.flags(c, c.manager + tt.MGR_ENTRANTS, 3, 40) & 1, 0)
        self.assertEqual(self.flags(c, c.obj + tt.OBJ_ROWS, 3, 16) & 1, 0)
        self.assertEqual(self.flags(c, c.manager + tt.MGR_ROWS, 3, 16) & 1, 0)
        self.assertEqual(c.u(tt.CONTROL + tt.F['wclean']), 0)
        self.assertEqual(c.u(tt.CONTROL + tt.F['wstop']), 3)      # the bracket is not on row 2 yet
        self.assertEqual(self.flags(c, c.obj + tt.OBJ_ENTRANTS, 4, 40) & 1, 1)
        c.w(c.obj + tt.OBJ_ROW, 2)
        self.frame(c)
        self.assertEqual(c.u(tt.CONTROL + tt.F['wstop']), 0)
        self.assertEqual(self.flags(c, c.obj + tt.OBJ_ENTRANTS, 4, 40) & 1, 0)
        self.assertEqual(c.u(tt.CONTROL + tt.F['ask']), 3)        # row 2 is a CPU row again: asked

    def test_the_round_script_pointer_does_not_hide_the_question(self):
        # live (European disc): +0x1A3C keeps the round's script pointer in every plain wait after round 1
        c = self.machine(FIRST_ROUND, humans=(14,)); c.w(c.obj + tt.OBJ_SCRIPT, 0x98)
        self.frame(c)
        self.assertEqual(c.u(tt.CONTROL + tt.F['ask']), 1)

    def test_a_busy_wait_on_a_cpu_row_never_takes_the_native_accept(self):
        for row, extra in ((0, {}), (2, {'wstop': 3})):
            c = self.machine(FIRST_ROUND, humans=(14, 4) if extra else (14,))
            c.w(c.obj + tt.OBJ_ROW, row); c.w(c.obj + tt.OBJ_WAIT, 4 | 0x400)
            for name, value in extra.items():
                c.w(tt.CONTROL + tt.F[name], value)
            for port in (0, 0x1C0):
                c.w(tt.PAD_RECORDS + port + 0x18C, 0x4000)
            self.frame(c)
            self.assertEqual([c.u(tt.PAD_RECORDS + port + 0x18C) for port in (0, 0x1C0)], [0, 0])
            self.assertEqual((c.u(tt.CONTROL + tt.F['ask']), c.calls), (0, []))
        # a human row keeps the native accept while busy
        c = self.machine(FIRST_ROUND, humans=(14,)); c.w(c.obj + tt.OBJ_WAIT, 4 | 0x400)
        c.w(tt.PAD_RECORDS + 0x18C, 0x4000)
        self.frame(c)
        self.assertEqual(c.u(tt.PAD_RECORDS + 0x18C), 0x4000)

    def test_a_question_waits_for_the_host_while_the_lease_runs(self):
        c = self.machine(FIRST_ROUND, humans=(14,)); c.w(tt.CONTROL + tt.F['wlease'], 3)
        for _ in range(3):
            self.frame(c)
            self.assertEqual((c.u(tt.CONTROL + tt.F['ask']), c.calls), (1, []))
        self.frame(c)                                                 # lease over: the native instant result
        self.assertEqual(c.calls[0], ('ROW_RESULT', c.obj, 0))


def make_cpu(segments, budget=200000):
    """The watch helper's interpreter (test_ai_shadow.Mips plus lhu/sh/mult/mflo/srl/nor) over (address, bytes)."""
    from test_ai_shadow import Mips

    class Cpu(Mips):
        instruction_budget = budget

        def extra_instruction(self, ins, pc):
            op, rs, rt, rd = ins >> 26, (ins >> 21) & 31, (ins >> 16) & 31, (ins >> 11) & 31
            imm = ins & 65535
            signed = imm if imm < 32768 else imm - 65536
            if op == 37:
                self.r[rt] = int.from_bytes(self.read(self.r[rs] + signed, 2), 'little')
            elif op == 41:
                self.write(self.r[rs] + signed, (self.r[rt] & 0xFFFF).to_bytes(2, 'little'))
            elif op == 0 and ins & 63 == 0x18:
                self.lo = (self.r[rs] * self.r[rt]) & 0xFFFFFFFF
            elif op == 0 and ins & 63 == 0x12:
                self.r[rd] = self.lo
            elif op == 0 and ins & 63 == 2:
                self.r[rd] = (self.r[rt] & 0xFFFFFFFF) >> ((ins >> 6) & 31)
            elif op == 0 and ins & 63 == 0x27:
                self.r[rd] = ~(self.r[rs] | self.r[rt]) & 0xFFFFFFFF
            else:
                raise AssertionError(f'Unsupported instruction {ins:08X} at {pc:08X}')
            return None

    return Cpu({'segments': [dict(address=a, data_hex=d.hex()) for a, d in segments]})


class StandIns(unittest.TestCase):
    """The type-menu and registration stand-ins and the entrant post-pass, instruction by instruction."""
    MANAGER, OBJ = 0x00600000, 0x00800000

    def machine(self, scene, record=None):
        c = make_cpu([(tt.TYPE_STUB, tt.type_stub()), (tt.ENTRY_STUB, tt.entry_stub()),
                      (tt.SETUP_STUB, tt.setup_stub())])
        c.w(tt.SCENE_MANAGER, self.MANAGER); c.w(self.MANAGER + 0x18, scene)
        c.w(tt.CONTROL, tt.MAGIC)
        if record is not None:
            c.write(tt.AUTO, record)
        c.natives = []
        for name in ('TYPE_MENU', 'REGISTRATION'):
            c.callbacks[getattr(tt, name)] = (lambda n: lambda m: (m.natives.append(n), m.r.__setitem__(2, 7)))(name)
        return c

    @staticmethod
    def record(setup, rosters):
        c = tt.Controller(); c.setup, c.rosters = setup, rosters
        return c.auto_record()

    def test_the_type_menu_is_answered_from_the_setup(self):
        rec = self.record(tt.Setup(2, {1: 0, 2: 1}, 'ask', 3, 2), [[tt.member(14)], [tt.member(29)]])
        c = self.machine(tt.TYPE_SCENE, rec)
        c.r[4] = 1
        self.assertEqual(c.run(tt.TYPE_STUB), 0xFEED0000)
        self.assertEqual((c.r[2], c.natives), (1, []))
        self.assertEqual([c.u(self.MANAGER + o) for o in (tt.MGR_FREE, tt.MGR_TYPE, tt.MGR_DIFFICULTY, tt.MGR_HUMANS)],
                         [1, 3, 2, 2])
        self.assertEqual(c.u(tt.AUTO), tt.AUTO_MAGIC)            # the registration still needs it
        # no auto entry, not armed, another scene or a bad record: the game's own menu
        for change in (lambda m: m.w(tt.AUTO, 0), lambda m: m.w(tt.CONTROL, 0),
                       lambda m: m.w(self.MANAGER + 0x18, 4), lambda m: m.w(tt.AUTO + 4, 9),
                       lambda m: m.w(tt.AUTO + 12, 0), lambda m: m.w(tt.AUTO + 12, 5)):
            c = self.machine(tt.TYPE_SCENE, rec); change(c)
            c.r[4] = 1
            self.assertEqual(c.run(tt.TYPE_STUB), 0xFEED0000)
            self.assertEqual((c.r[2], c.natives), (7, ['TYPE_MENU']))
            self.assertEqual(c.u(self.MANAGER + tt.MGR_HUMANS), 0)

    def test_the_registration_writes_each_drafted_leader_once(self):
        rec = self.record(tt.Setup(2, {1: 0, 2: 0, 3: 1}), [[tt.member(14, 2, ITEMS), tt.member(29)],
                                                            [tt.member(85, 1)]])
        c = self.machine(tt.ENTRY_SCENE, rec)
        c.write(self.MANAGER + tt.MGR_ENTRANTS, b'\xAA' * (tt.ENTRANTS * tt.ENTRANT_BYTES))
        c.r[4] = 2
        self.assertEqual(c.run(tt.ENTRY_STUB), 0xFEED0000)
        self.assertEqual((c.r[2], c.natives), (1, []))
        ents = tt.parse_entrants(c.read(self.MANAGER + tt.MGR_ENTRANTS, tt.ENTRANTS * tt.ENTRANT_BYTES))
        self.assertEqual([(e.flags, e.character, e.costume, e.player) for e in ents[:2]],
                         [(tt.HUMAN | tt.CUSTOM, 14, 2, 0), (tt.HUMAN, 85, 1, 1)])
        items = c.read(self.MANAGER + tt.MGR_ENTRANTS + 0x18, 16)
        self.assertEqual(items, ITEMS)
        self.assertEqual(c.read(self.MANAGER + tt.MGR_ENTRANTS + 2 * tt.ENTRANT_BYTES,
                                (tt.ENTRANTS - 2) * tt.ENTRANT_BYTES), bytes((tt.ENTRANTS - 2) * tt.ENTRANT_BYTES))
        self.assertEqual(c.u(tt.AUTO), 0)                        # one shot
        c.r[4], c.r[31] = 2, 0xFEED0000                          # a second call is the game's own registration
        c.run(tt.ENTRY_STUB)
        self.assertEqual(c.natives, ['REGISTRATION'])

    def post_pass(self, characters, humans=(), locked=(), spares=(), armed=True, draws=()):
        c = self.machine(tt.BRACKET_SCENE)
        if not armed:
            c.w(tt.CONTROL, 0)
        bitmap = bytearray(32)
        for k in locked:
            bitmap[k >> 3] |= 1 << (k & 7)
        c.write(tt.LOCKED, bytes(bitmap))
        c.w(tt.SPARES, len(spares)); c.write(tt.SPARES + 4, struct.pack(f'<{len(spares)}H', *spares))
        blob = entrants_blob(characters[:16], humans=humans, boss_character=characters[16])
        c.callbacks[tt.ENTRANT_SETUP] = lambda m: m.write(m.r[4] + tt.OBJ_ENTRANTS, blob)
        sequence = list(draws)
        c.callbacks[tt.RAND] = lambda m: m.r.__setitem__(2, sequence.pop(0) if sequence else 0)
        c.r[4] = self.OBJ
        self.assertEqual(c.run(tt.SETUP_STUB), 0xFEED0000)
        return c, tt.parse_entrants(c.read(self.OBJ + tt.OBJ_ENTRANTS, tt.ENTRANTS * tt.ENTRANT_BYTES))

    def test_the_post_pass_swaps_locked_cpu_entrants_only(self):
        field = list(FIELD) + [231]
        field[3], field[9], field[14] = 231, 240, 232           # two locked CPUs, a locked human, a locked boss
        spares = (FIELD[0], 10, 20, 30)
        c, ents = self.post_pass(field, humans=(14,), locked=(231, 232, 240), spares=spares, draws=(0, 1, 2))
        self.assertEqual(ents[3].character, 10)                  # spares[0] is in the bracket already: next draw
        self.assertEqual(ents[9].character, 20)
        self.assertEqual((ents[14].character, ents[16].character), (232, 231))   # the human and the boss stay
        self.assertEqual(c.u(tt.CONTROL + tt.F['swapped']), 2)
        self.assertEqual([e.character for i, e in enumerate(ents) if i not in (3, 9)],
                         [x for i, x in enumerate(field) if i not in (3, 9)])
        # not armed, or no spares (BT3: no locked slot): the native setup alone
        for kwargs in (dict(armed=False, spares=spares), dict(spares=())):
            c, ents = self.post_pass(field, humans=(14,), locked=(231, 232, 240), **kwargs)
            self.assertEqual([e.character for e in ents], field)
        # every draw taken: the last one is used anyway (bounded)
        c, ents = self.post_pass(field, locked=(231, 232, 240), spares=(FIELD[0],), draws=[0] * 20)
        self.assertEqual(ents[3].character, FIELD[0])


class LockedFighters(unittest.TestCase):
    def table(self, folder, shared=(2, 5, 6), unnamed=(7,)):
        table = {}
        for c in range(9):
            name = f'{c:03}.png'
            (folder / name).write_bytes(b'LOCK ICON' if c in shared else f'face {c}'.encode())
            table[c] = dict(character_id=c, name=f'Fighter {c}' if c in unnamed else f'Hero {c}', portrait=name)
        return table

    def test_the_lock_icon_is_the_portrait_several_slots_share(self):
        from unittest import mock
        import character_names
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            table = self.table(folder)
            with mock.patch.object(character_names, 'character_table', return_value=table), \
                    mock.patch.object(character_names, 'assets_folder', return_value=folder):
                self.assertEqual(tt.lock_art_ids(), {2, 5, 6})
                p = FakePine()
                p.write_u32(tt.PICK_RULE, 0x28820008)               # slti v0, a0, 8: 8 and up are not fighters
                locked, excluded = tt.unplayable(p)
                self.assertEqual((locked, excluded), ({2, 5, 6, 7}, {2, 5, 6, 7} | set(range(8, 256))))
                self.assertEqual(tt.roster_pool(exclude=excluded), [0, 1, 3, 4])
                c = tt.Controller(); c.log = lambda t: None
                c.publish_locked(p)
                self.assertEqual(p.read(tt.LOCKED, 1)[0], 0b11100100)
                self.assertEqual(p.read_u32(tt.SPARES), 4)
                self.assertEqual(struct.unpack('<4H', p.read(tt.SPARES + 4, 8)), (0, 1, 3, 4))
                plan = tt.Plan(tt.Setup(3, {1: 0}), seed=1, pool=c.pool).build(
                    tt.parse_entrants(entrants_blob([0, 1, 3, 4] * 4, humans=(0,), boss_character=1)))
                self.assertFalse({m[0] for t in plan.teams for m in t[1:]} - {0, 1, 3, 4})
            # two slots with one picture are not a lock icon
            table = self.table(folder, shared=(2, 5))
            with mock.patch.object(character_names, 'character_table', return_value=table), \
                    mock.patch.object(character_names, 'assets_folder', return_value=folder):
                self.assertEqual(tt.lock_art_ids(), set())

    def test_the_native_pick_rule_is_read_from_the_running_disc(self):
        p = FakePine()
        p.write_u32(tt.PICK_RULE, 0x288200A1)                       # BT3: slti v0, a0, 0xA1
        self.assertEqual(tt.native_excluded(p), frozenset(range(161, 256)))
        p.write_u32(tt.PICK_RULE, tt.BT4_PICK_CALL)                 # BT4: its filter refuses 0xA1..0xA4
        p.write_u32(tt.BT4_FILTER + 0x14, 0x2A0400A5); p.write_u32(tt.BT4_FILTER + 0x1C, 0x2A0400A1)
        self.assertEqual(tt.native_excluded(p), frozenset(range(161, 165)))
        p.write_u32(tt.PICK_RULE, 0)
        self.assertIsNone(tt.native_excluded(p))

    def test_bt4_filter_and_select_screen_specials(self):
        bt4 = Path(tt.__file__).resolve().parents[2] / 'bt4-multifighter'
        overlay = bt4 / 'analysis' / 'DBZP.BIN'
        if not overlay.exists():
            self.skipTest('no BT4 overlay copy')
        data = overlay.read_bytes()
        word = lambda a: struct.unpack_from('<I', data, a - 0x334C00)[0]
        self.assertEqual(word(0x369470), tt.BT4_PICK_CALL)
        self.assertEqual((word(tt.BT4_FILTER + 0x14), word(tt.BT4_FILTER + 0x1C)), (0x2A0400A5, 0x2A0400A1))
        for site, target, _, _ in tt.call_sites():
            self.assertEqual(word(site), tt.jal(target))


class Panel(unittest.TestCase):
    def test_rows_problem_and_commit(self):
        panel = tt.SetupPanel(tt.Controller())
        panel.humans, panel.teams, panel.size = 3, [0, 1, 0, 3], 2
        self.assertEqual([r[0] for r in panel.rows()], ['players', 'player', 'player', 'player', 'size', 'kind',
                                                        'level', 'cpu', 'continue', 'clear'])
        panel.change(('kind',), -1); panel.change(('level',), 1)
        self.assertEqual((panel.commit().kind, panel.commit().level), (len(tt.TYPES) - 1, 1))
        panel.change(('kind',), 1)
        self.assertEqual(panel.commit().kind, 0)
        self.assertIsNone(panel.problem())
        panel.size = 1
        self.assertEqual(panel.problem(), (tt.TOO_MANY, dict(t=1)))
        panel.size = 3
        self.assertEqual(panel.commit().teams, [(0, (1, 3)), (1, (2,))])
        panel.humans = 4
        panel.change(('players',), 1)
        self.assertEqual(panel.humans, 0)

    def test_cpu_match_policy_row(self):
        panel = tt.SetupPanel(tt.Controller())
        self.assertEqual(panel.commit().cpu_matches, 'ask')
        panel.change(('cpu',), 1)
        self.assertEqual(panel.commit().cpu_matches, 'watch')
        panel.change(('cpu',), 1)
        self.assertEqual(panel.commit().cpu_matches, 'skip')
        panel.change(('cpu',), 1)
        self.assertEqual(panel.commit().cpu_matches, 'ask')
        s = tt.Setup(2, {1: 0}, 'watch')
        self.assertEqual(tt.Setup.from_json(json.loads(json.dumps(s.to_json()))).cpu_matches, 'watch')
        self.assertEqual(tt.Setup.from_json(dict(size=2)).cpu_matches, 'ask')
        with self.assertRaises(ValueError):
            tt.Setup(2, {}, 'sometimes')

    def test_prompts_name_the_regions_buttons(self):
        import regional
        from unittest import mock
        tr = lambda text, **v: loc.tr(text, dict(language='en'), **v)
        with mock.patch.object(regional, 'JPN', False):
            self.assertEqual(tt.buttons(tr), dict(accept='Cross', back='Triangle'))
        with mock.patch.object(regional, 'JPN', True):
            self.assertEqual(tt.buttons(tr), dict(accept='Circle', back='Cross'))
            es = lambda text, **v: loc.tr(text, dict(language='es'), **v)
            self.assertEqual(es(tt.BANNER_MISMATCH_BACK, n=2, **tt.buttons(es)), 'Pulsa Cruz para volver y elegir 2.')
        for text in (tt.FOOTER_ALL, tt.BANNER_MISMATCH_BACK):
            self.assertNotIn('Triangle', text)
            self.assertNotIn('Cross', text)

    def test_picture_draws_in_both_languages(self):
        for language in ('en', 'es'):
            for humans in (0, 1, 4):
                panel = tt.SetupPanel(tt.Controller())
                panel.settings = dict(language=language)
                panel.humans, panel.teams, panel.size = humans, [0, 0, 1, 1], 3
                self.assertEqual(panel.picture().size, (512, 448))

    def test_every_new_string_has_spanish(self):
        import autopilot
        names = [n for n in dir(tt) if n.isupper() and isinstance(getattr(tt, n), str) and
                 n not in ('ORIGINAL_NAME', 'STATE_FILE')]
        texts = [getattr(tt, n) for n in names] + ['Tag Team Tournament']
        texts += list(tt.TYPES) + list(tt.BT4_TYPES) + list(tt.DIFFICULTIES)
        texts += [getattr(autopilot, n) for n in dir(autopilot) if n.startswith('SAY_TOURNAMENT')]
        texts += [autopilot.TOURNAMENT_COVER, autopilot.TOURNAMENT_FAILED]
        missing = [t for t in texts if t not in loc.ES]
        self.assertEqual(missing, [])


class MenuAndGate(unittest.TestCase):
    def test_modded_modes_row_and_choice(self):
        self.assertIn(4, nmm.PAGES[0])
        self.assertEqual(nmm.SELECTIONS[tt.CHOICE - 1], ('tournament', 0))
        self.assertNotIn(tt.CHOICE, ta.CHOICES)
        self.assertLess(len(nmm.payload()), 0x3000)
        for humans, choice in ((1, 1), (2, 7), (3, 17), (4, 12)):
            self.assertEqual(nmm.SELECTIONS[choice - 1], ('teams', humans))

    def test_gate_reads_the_accepted_mode(self):
        self.assertEqual(prep.ACCEPTED_MODE - prep.CONTROL, 64)
        self.assertIn(prep.gate_code(accepted_mode_word=False), prep.previous_gate_images())


if __name__ == '__main__':
    unittest.main()
