import support
"""netplay_view: the per-window view programs run in guest_soak's MIPS interpreter over a synthetic EE image.

Native callees are stubbed (guest_soak returns v0 = v1 = 0 from the executable's text and runs a semantic hook): the
bind 23E6A0 sets gp-22176 like the native one, the render 12B7F8 records what it saw (bound camera, manager+3136,
LEADER_CONTROL+12) and can draw rand()/MT values, 244D70 records a release. cinematic_policy's selector chain and its
VIEW predicate are guest addresses and are answered by callbacks. VIEWER is asked from inside the stubbed render
the way 207FB0's tie-break asks it (a second interpreter over the same RAM), and its native fallback 23EE08 answers
a chosen value. A real converted fixture can be added with TAGTEAM_NETPLAY_VIEW_FIXTURE (a single-view .p2s, e.g.
p25/states/fixture-2v2-single.p2s)."""
import os
import struct
import unittest

import guest_soak as soak
import netplay_core as nc
import netplay_state_hash as nh
import netplay_view as nv
import cinematic_policy as cinema
import fresh_team_camera as follow
from native_map import GP

TEXT = (0x100000, 0x2C0000)
MANAGER, CINEMATIC, BATTLE, IMPURE = 0x01873F00, 0x01874B80, 0x0187A420, 0x002E9518
SIDE = [MANAGER + 1824, MANAGER + 1824 + 656]
RENDER, BIND, VIS_VIEW, VIS_PAIR, RELEASE = 0x12B7F8, 0x23E6A0, 0x24AD08, 0x24ADF8, 0x244D70
VIEWED, TIE_BREAK = 0x23EE08, 0x20805C            # the native viewed side; 207FB0's `jal 23EE08`
SCENE = 0x331DC8


def put(ram, address, *words):
    struct.pack_into('<%dI' % len(words), ram, address, *words)


class Cpu(soak.Cpu):
    """guest_soak's interpreter plus cfc2 (VU0 R reads)."""
    vu0_r = 0x1234

    def extra_instruction(self, ins, pc):
        if ins >> 26 == 18 and (ins >> 21) & 31 == 2 and (ins >> 11) & 31 == 20:
            self.r[(ins >> 16) & 31] = self.vu0_r
            return None
        return super().extra_instruction(ins, pc)


def image(views=1, slot=1, mode=nc.LOCKSTEP, split=0, director=3, result=0, canonical=None, state=nc.RUNNING):
    ram = bytearray(0x8000000)
    put(ram, GP - 22172, MANAGER)
    put(ram, GP - 22176, SIDE[0] if canonical is None else canonical)
    put(ram, GP - 22180, CINEMATIC)
    put(ram, GP - 22328, BATTLE)
    put(ram, BATTLE, director)
    put(ram, 0x333700, result)
    put(ram, SCENE + 36, split)
    put(ram, 0x2E9808, IMPURE)
    put(ram, IMPURE + 168, 0x11111111, 0x22222222)
    for i, off in enumerate(nv.MT_INDEXES):
        put(ram, GP + off, 100 + i)
    put(ram, MANAGER + 3136, SIDE[0])
    put(ram, follow.LEADER_CONTROL, 1, 0, 0, 0)
    control = bytearray(nc.control(mode=mode if mode != nc.OFF else nc.PLAYBACK, delay=1))
    struct.pack_into('<I', control, nc.F['mode'], mode)
    struct.pack_into('<I', control, nc.F['local_slot'], slot & 0xFFFFFFFF)
    struct.pack_into('<I', control, nc.F['state'], state)
    ram[nc.CONTROL:nc.CONTROL + len(control)] = control
    ram[nv.CONTROL:nv.CONTROL + nv.CONTROL_BYTES] = nv.control(views)
    put(ram, cinema.CONTROL, cinema.MAGIC)
    for address, code in nv.programs(camera=(0x06943000, 0x06943084), marker=(0x06954234, 0x069542F0, 0x06954300)):
        ram[address:address + len(code)] = code
    return ram


def ask_viewer(buffer, native):
    """VIEWER run over BUFFER (shared, not copied) the way 207FB0's tie-break calls it, the native 23EE08 answering
    NATIVE: (v0, how many times 23EE08 was asked)."""
    cpu = Cpu(b'', TEXT)
    cpu.buffer = buffer
    cpu.stub_sentinel = True
    asked = []

    def viewed(c):
        asked.append(c.r[31])
        c.r[2] = native
    cpu.semantic[VIEWED] = viewed
    saved = {r: 0x6000 + r for r in (16, 17, 18, 19, 20, 21, 22, 23, 30)}
    cpu.call(nv.VIEWER, registers=saved)
    assert all(cpu.r[r] == v for r, v in saved.items()) and cpu.r[29] == soak.STACK, 'VIEWER is a leaf'
    return cpu.r[2], len(asked)


class Machine:
    def __init__(self, ram):
        self.cpu = Cpu(ram, TEXT)
        self.cpu.stub_sentinel = True
        self.renders, self.binds, self.vis, self.releases = [], [], [], []
        self.on_render = None
        self.cpu.semantic.update({RENDER: self.render, BIND: self.bind, VIS_VIEW: lambda c: self.vis.append('view'),
                                  VIS_PAIR: lambda c: self.vis.append('pair'), RELEASE: self.release})

    def u(self, address):
        return self.cpu.u(address)

    def w(self, address, *words):
        put(self.cpu.buffer, address, *words)

    def view(self):
        return nv.parse_control(bytes(self.cpu.buffer[nv.CONTROL:nv.CONTROL + nv.CONTROL_BYTES]))

    def render(self, cpu):
        self.renders.append(dict(bound=self.u(GP - 22176), current=self.u(MANAGER + 3136),
                                 leader=self.u(follow.LEADER_CONTROL + 12)))
        if self.on_render:
            self.on_render(self)

    def bind(self, cpu):
        self.binds.append((cpu.r[4], cpu.r[5]))
        self.w(GP - 22176, cpu.r[4])

    def release(self, cpu):
        self.releases.append(cpu.r[4])
        self.w(cpu.r[4], 0)

    def record(self, canonical=None, view0=0, view1=0, shared=0, current=None):
        """What SEL would have recorded this update (current: manager+3136 at the selection, a side camera unless one
        of the mod's shared presentations bound the cinematic there)."""
        self.w(nv.CONTROL + nv.F['canonical'], self.u(GP - 22176) if canonical is None else canonical, view0, view1,
               shared)
        self.w(nv.CONTROL + nv.F['current'], SIDE[0] if current is None else current)

    def swap(self):
        saved = {r: 0x5000 + r for r in (16, 17, 18, 19, 20, 21, 22, 23, 30)}
        self.cpu.call(nv.SWAP, registers=saved)
        for r, v in saved.items():
            assert self.cpu.r[r] == v, f'SWAP changed callee-saved ${r}'
        assert self.cpu.r[29] == soak.STACK


class SwapTests(unittest.TestCase):
    def test_side_zero_renders_the_selected_camera_unchanged(self):
        m = Machine(image(slot=0)); m.record()
        m.swap()
        self.assertEqual(m.renders, [dict(bound=SIDE[0], current=SIDE[0], leader=0)])
        self.assertEqual((m.binds, m.vis), ([], []))
        v = m.view()
        self.assertEqual((v['side'], v['renders'], v['swaps_side'], v['kept'], v['not_live']), (0, 1, 0, 0, 0))

    def test_side_one_renders_side_camera_one_and_restores_everything_logic_reads(self):
        m = Machine(image(slot=1)); m.record()
        m.swap()
        self.assertEqual(m.renders, [dict(bound=SIDE[1], current=SIDE[1], leader=1)])
        self.assertEqual(m.binds, [(SIDE[1], 1), (SIDE[0], 1)])
        self.assertEqual(m.vis, ['view', 'pair'])
        self.assertEqual((m.u(GP - 22176), m.u(MANAGER + 3136), m.u(follow.LEADER_CONTROL + 12)), (SIDE[0], SIDE[0], 0))
        v = m.view()
        self.assertEqual((v['side'], v['swaps_side'], v['last']), (1, 1, SIDE[1]))

    def test_cinematic_choice(self):
        S0 = SIDE[0]
        cases = [  # canonical, view0, view1, shared, current (manager+3136), slot -> camera rendered
            (CINEMATIC, 0, 0, 1, S0, 1, CINEMATIC),   # one shared presentation for everybody (the stop record)
            (CINEMATIC, 0, 0, 0, S0, 1, CINEMATIC),   # nobody takes part: shared
            (CINEMATIC, 1, 0, 0, S0, 1, SIDE[1]),     # side 0's own cinematic: side 1 keeps its camera
            (CINEMATIC, 1, 0, 0, CINEMATIC, 1, CINEMATIC),  # the mod's shared path bound it (checked ultimate)
            (CINEMATIC, 1, 0, 0, S0, 0, CINEMATIC),
            (CINEMATIC, 0, 1, 0, S0, 1, CINEMATIC),   # side 1 takes part
            # The native selection chose the cinematic for side 0 (a shared presentation whose stop record lags,
            # or VIEW without the victim rule): side 0 keeps exactly what the native single view shows.
            (CINEMATIC, 0, 1, 0, S0, 0, CINEMATIC),
            (CINEMATIC, 0, 1, 0, CINEMATIC, 0, CINEMATIC),
            (SIDE[0], 0, 1, 0, S0, 1, CINEMATIC),     # side 1 takes part in the running cinematic; side 0 does not
            (SIDE[0], 0, 1, 0, S0, 0, SIDE[0]),
            (SIDE[0], 1, 0, 0, S0, 1, SIDE[1]),
            (SIDE[0], 1, 0, 0, S0, 0, CINEMATIC),     # side 0 as the victim of a running cinematic (split rule)
        ]
        for canonical, view0, view1, shared, current, slot, expected in cases:
            with self.subTest(canonical=hex(canonical), view0=view0, view1=view1, shared=shared, current=hex(current),
                              slot=slot):
                m = Machine(image(slot=slot, canonical=canonical)); m.record(canonical, view0, view1, shared, current)
                m.w(MANAGER + 3136, current)
                m.swap()
                self.assertEqual(m.renders[0]['bound'], expected)
                self.assertEqual(m.u(GP - 22176), canonical)
                self.assertEqual(m.u(MANAGER + 3136), current, 'manager+3136 restored (a cinematic never sets it)')
                if expected == CINEMATIC and canonical != CINEMATIC:
                    self.assertEqual(m.renders[0]['current'], current)
                    self.assertEqual(m.view()['swaps_cine'], 1)
                if expected == canonical:
                    self.assertEqual((m.binds, m.view()['swaps_side'], m.view()['swaps_cine']), ([], 0, 0))

    def test_only_the_live_fight_swaps(self):
        for kw in (dict(director=4), dict(result=2), dict(director=2)):
            with self.subTest(**kw):
                m = Machine(image(slot=1, **kw)); m.record()
                m.swap()
                self.assertEqual(m.renders, [dict(bound=SIDE[0], current=SIDE[0], leader=0)])
                self.assertEqual(m.view()['not_live'], 1)

    def test_a_stale_record_never_swaps(self):
        m = Machine(image(slot=1)); m.record(canonical=SIDE[1])
        m.swap()
        self.assertEqual((m.renders[0]['bound'], m.view()['kept']), (SIDE[0], 1))

    def test_local_side_comes_only_from_lockstep_local_slot(self):
        for kw, side in ((dict(slot=1, mode=nc.PLAYBACK), 0), (dict(slot=nc.NO_SLOT), 0), (dict(slot=2), 0),
                         (dict(slot=1, state=nc.ARMED), 0), (dict(slot=1, state=nc.DECIDED), 0),
                         (dict(slot=1, state=nc.ABORTED), 0), (dict(slot=1), 1)):
            with self.subTest(**kw):
                m = Machine(image(**kw)); m.record()
                m.swap()
                self.assertEqual(m.view()['side'], side)
                self.assertEqual(m.renders[0]['bound'], SIDE[side])

    def test_views_off_and_split_view_take_the_native_render(self):
        for kw in (dict(views=0), dict(split=1)):
            with self.subTest(**kw):
                m = Machine(image(slot=1, **kw)); m.record()
                m.on_render = lambda mm: mm.w(IMPURE + 168, 0xAAAA)
                m.swap()
                self.assertEqual(m.renders, [dict(bound=SIDE[0], current=SIDE[0], leader=0)])
                self.assertEqual(m.u(IMPURE + 168), 0xAAAA, 'no bracket outside per-window views')
                self.assertEqual(m.view()['renders'], 0)

    def test_render_rand_draws_never_reach_the_game_and_mt_draws_are_counted(self):
        for slot in (0, 1):
            with self.subTest(slot=slot):
                m = Machine(image(slot=slot)); m.record()

                def draw(mm):
                    mm.w(IMPURE + 168, 0x33333333, 0x44444444)
                    mm.w(GP - 21008, 555)
                    mm.cpu.vu0_r = 0x9999
                m.on_render = draw
                m.swap()
                self.assertEqual((m.u(IMPURE + 168), m.u(IMPURE + 172)), (0x11111111, 0x22222222))
                v = m.view()
                self.assertEqual((v['rand_restored'], v['mt_trips'], v['vu0_trips']), (1, 1, 1))

    def test_no_render_draw_no_counters(self):
        m = Machine(image(slot=1)); m.record()
        m.swap()
        v = m.view()
        self.assertEqual((v['rand_restored'], v['mt_trips'], v['vu0_trips']), (0, 0, 0))


class ViewerTests(unittest.TestCase):
    """207FB0's 'viewed fighter' tie-break: side s exactly while SWAP renders the live fight for side s."""

    def run_swap(self, native, record=None, current=None, **kw):
        m = Machine(image(**kw))
        m.record(**(record or {}))
        if current is not None:
            m.w(MANAGER + 3136, current)
        m.seen = []
        m.on_render = lambda mm: mm.seen.append(ask_viewer(mm.cpu.buffer, native))
        m.swap()
        return m

    def test_window_b_lends_side_one_to_its_live_render_and_takes_it_back(self):
        m = self.run_swap(native=0, slot=1)
        self.assertEqual(m.renders, [dict(bound=SIDE[1], current=SIDE[1], leader=1)])
        self.assertEqual(m.seen, [(1, 0)], 'side 1 answered without asking 23EE08')
        v = m.view()
        self.assertEqual((v['lent'], v['viewer_calls']), (0, 1))
        self.assertEqual(ask_viewer(m.cpu.buffer, native=0), (0, 1), 'after the render (logic): the native answer')

    def test_window_b_lends_its_side_when_it_shows_the_bound_camera(self):
        # A shared presentation bound as the canonical camera: no swap, but window B still renders for side 1
        # (LEADER_CONTROL+12 = 1), so the viewed fighter follows the same rule.
        m = self.run_swap(native=0, slot=1, canonical=CINEMATIC,
                          record=dict(canonical=CINEMATIC, shared=1), current=SIDE[0])
        self.assertEqual((m.renders[0]['bound'], m.renders[0]['leader'], m.binds), (CINEMATIC, 1, []))
        self.assertEqual(m.seen, [(1, 0)])
        self.assertEqual(m.view()['lent'], 0)

    def test_window_a_and_every_unswapped_render_keep_the_native_answer(self):
        cases = (dict(slot=0), dict(slot=1, director=4), dict(slot=1, director=2), dict(slot=1, result=2),
                 dict(slot=1, views=0), dict(slot=1, split=1), dict(slot=1, mode=nc.PLAYBACK),
                 dict(slot=1, state=nc.DECIDED), dict(slot=1, state=nc.ABORTED), dict(slot=nc.NO_SLOT))
        for kw in cases:
            for native in (0, 1):
                with self.subTest(native=native, **kw):
                    m = self.run_swap(native=native, **kw)
                    self.assertEqual(m.seen, [(native, 1)])
                    self.assertEqual((m.view()['lent'], m.view()['viewer_calls']), (0, 0))

    def test_a_stale_record_keeps_the_native_answer(self):
        m = self.run_swap(native=0, slot=1, record=dict(canonical=SIDE[1]))
        self.assertEqual((m.view()['kept'], m.seen), (1, [(0, 1)]))

    def test_outside_swap_viewer_is_the_native_call(self):
        ram = image(slot=1)
        for native in (0, 1, 2):
            self.assertEqual(ask_viewer(ram, native), (native, 1))

    def test_viewer_answers_a_lent_side_only_with_the_module_installed(self):
        ram = image(slot=1)
        put(ram, nv.CONTROL + nv.F['lent'], 1)
        self.assertEqual(ask_viewer(ram, 0), (1, 0))
        put(ram, nv.CONTROL, 0)                                   # magic gone: native
        self.assertEqual(ask_viewer(ram, 0), (0, 1))

    def test_render_rand_bracket_still_covers_the_lent_render(self):
        m = Machine(image(slot=1)); m.record()

        def draw(mm):
            mm.w(IMPURE + 168, 0x33333333, 0x44444444)
            mm.seen = ask_viewer(mm.cpu.buffer, 0)
        m.on_render = draw
        m.swap()
        self.assertEqual((m.u(IMPURE + 168), m.u(IMPURE + 172), m.seen), (0x11111111, 0x22222222, (1, 0)))


class SelectTests(unittest.TestCase):
    def machine(self, **kw):
        m = Machine(image(**kw))
        m.seen = []

        def chain(cpu):
            m.w(GP - 22176, CINEMATIC)
            cpu.r[2], cpu.r[3] = 0x1234567890 & 0xFFFFFFFF, 7

        def view(cpu):
            m.seen.append((cpu.r[4], m.u(SCENE + 36)))
            cpu.r[2] = int(cpu.r[4] == 1)
        m.cpu.callbacks[cinema.CODE] = chain
        m.cpu.callbacks[cinema.VIEW] = view
        return m

    def test_records_the_selection_with_the_split_victim_rule_and_keeps_the_chain_result(self):
        m = self.machine()
        m.w(cinema.CONTROL + cinema.SHARED_STOP, 3)
        m.cpu.vu0_r = 0x7777
        m.cpu.call(nv.SEL)
        self.assertEqual((m.cpu.r[2], m.cpu.r[3]), (0x34567890, 7))
        self.assertEqual(m.seen, [(0, 1), (1, 1)], 'VIEW asked for both sides with the split flag set')
        self.assertEqual(m.u(SCENE + 36), 0, 'single view again')
        v = m.view()
        self.assertEqual((v['canonical'], v['view0'], v['view1'], v['shared'], v['vu0_r'], v['selections'],
                          v['current']), (CINEMATIC, 0, 1, 3, 0x7777, 1, SIDE[0]))

    def test_records_a_shared_presentation_bound_as_the_current_camera(self):
        m = self.machine()
        chain = m.cpu.callbacks[cinema.CODE]

        def shared(cpu):                     # cinematic_policy's shared paths: manager+3136 = gp-22176 = cinematic
            chain(cpu)
            m.w(MANAGER + 3136, CINEMATIC)
        m.cpu.callbacks[cinema.CODE] = shared
        m.cpu.call(nv.SEL)
        self.assertEqual((m.view()['canonical'], m.view()['current']), (CINEMATIC, CINEMATIC))

    def test_no_camera_manager_records_zero(self):
        m = self.machine()
        m.w(GP - 22172, 0)
        m.cpu.call(nv.SEL)
        self.assertEqual((m.view()['current'], m.view()['selections']), (0, 1))

    def test_views_off_or_split_record_nothing(self):
        for kw in (dict(views=0), dict(split=1)):
            with self.subTest(**kw):
                m = self.machine(**kw)
                m.cpu.call(nv.SEL)
                self.assertEqual((m.seen, m.view()['selections'], m.cpu.r[3]), ([], 0, 7))


class GateTests(unittest.TestCase):
    def jump_target(self, ram, entry):
        m = Machine(ram)
        hit = {}
        for target in (0x06943084, 0x06943008, 0x069542F0, 0x0695423C, 0x06954300):
            m.cpu.callbacks[target] = lambda cpu, t=target: hit.update(target=t, t0=cpu.r[8], a0=cpu.r[4],
                                                                       s0=cpu.r[16])
        m.cpu.call(entry, a0=0xA0)
        return hit

    def test_own_view_takes_each_readers_single_view_path(self):
        self.assertEqual(self.jump_target(image(), nv.CAMERA_GATE)['target'], 0x06943084)
        self.assertEqual(self.jump_target(image(), nv.MARKER_GATE)['target'], 0x069542F0)
        self.assertEqual(self.jump_target(image(), nv.CAMERA_GATE)['a0'], 0xA0)

    def test_layout4_marker_takes_the_rendered_subject_and_camera_the_fighters_own(self):
        import netplay_core as nc
        ram = bytearray(image())
        struct.pack_into('<I', ram, nv.CONTROL + nv.F['subject'], 5)
        hit = self.jump_target(bytes(ram), nv.MARKER_GATE)
        self.assertEqual((hit['target'], hit['s0']), (0x06954300, 5), 'the seat checks with s0 = the subject')
        ram[nc.SEAT_CONTROL:nc.SEAT_CONTROL + nc.SEAT_CONTROL_BYTES] = nc.seat_control([0, 1, None, 0xA0 // 0x20, 7])
        struct.pack_into('<I', ram, nv.CAM_LOGIC, 1 << 4)        # slot 4 (physical 7) has its own camera
        m = Machine(bytes(ram))
        m.cpu.call(nv.CAMERA_GATE, a0=7)
        self.assertEqual(m.cpu.r[2], nv.CAMS + 2 * nv.CAM_BYTES)
        self.assertEqual(self.jump_target(bytes(ram), nv.CAMERA_GATE)['target'], 0x06943084,
                         'slot 3 (physical 5) has no camera this update: the successor path')

    def test_otherwise_the_quad_path_resumes_with_t0_loaded(self):
        for kw in (dict(views=0), dict(split=1)):
            with self.subTest(**kw):
                hit = self.jump_target(image(**kw), nv.CAMERA_GATE)
                self.assertEqual((hit['target'], hit['t0']), (0x06943008, nv.QUAD_CONTROL))
                hit = self.jump_target(image(**kw), nv.MARKER_GATE)
                self.assertEqual((hit['target'], hit['t0']), (0x0695423C, nv.QUAD_CONTROL))


class BurstTests(unittest.TestCase):
    SLOT = 0x01900000

    def run_burst(self, **kw):
        m = Machine(image(**kw))
        m.w(self.SLOT, 1, 0, 0x41F00000, 0, 0, 0, 0, 0, 0x3F800000, 0xBD000000)
        m.w(self.SLOT + 64, 0x44F00000)
        m.cpu.call(nv.BURST, a0=self.SLOT)
        return m

    def test_own_view_hides_instead_of_releasing(self):
        m = self.run_burst()
        self.assertEqual(m.cpu.r[2], 1)
        self.assertEqual(m.releases, [])
        self.assertEqual((m.u(self.SLOT), m.u(self.SLOT + 32), m.u(self.SLOT + 36)), (1, 0, 0))
        self.assertEqual(m.cpu.f[1], 0x44F00000, '$f1 holds what the native branch-likely delay slot loads')
        self.assertEqual(m.view()['hidden'], 1)

    def test_otherwise_releases_exactly_as_before(self):
        for kw in (dict(views=0), dict(split=1)):
            with self.subTest(**kw):
                m = self.run_burst(**kw)
                self.assertEqual((m.cpu.r[2], m.releases, m.u(self.SLOT + 32)), (0, [self.SLOT], 0x3F800000))


class StaticTests(unittest.TestCase):
    def programs(self):
        return nv.programs(camera=(0x06943000, 0x06943084), marker=(0x06954234, 0x069542F0, 0x06954300))

    def test_stack_frames_are_16_byte_multiples_and_released_on_every_exit(self):
        import support as lint
        for address, code in self.programs():
            with self.subTest(address=hex(address)):
                adjust = lint.sp_adjustments(code)
                self.assertEqual([x for x in adjust if x % 16], [])
                if adjust:
                    self.assertLess(adjust[0], 0)
                    self.assertTrue(all(x == -adjust[0] for x in adjust[1:]))

    def test_no_kernel_scratch_registers(self):
        for address, code in self.programs():
            for i in range(0, len(code), 4):
                w = struct.unpack_from('<I', code, i)[0]
                op = w >> 26
                regs = []
                if op == 0:
                    regs = [(w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31]
                elif op not in (2, 3, 17, 18, 0x31):
                    regs = [(w >> 21) & 31, (w >> 16) & 31]
                elif op == 18:
                    regs = [(w >> 16) & 31]
                self.assertFalse({26, 27} & set(regs), f'{address + i:08X}: {w:08X}')

    def test_reservation_and_layout(self):
        spans = sorted((a, a + len(c)) for a, c in self.programs())
        self.assertGreaterEqual(spans[0][0], nv.CONTROL + nv.CONTROL_BYTES)
        self.assertTrue(all(e <= nv.END or nc.VIEW_AREA <= s and e <= nc.VIEW_AREA_END for s, e in spans))
        self.assertTrue(all(s >= nv.CAM_LOGIC + 0x100 for s, _ in spans if s >= nc.VIEW_AREA), 'cameras stay data')
        self.assertTrue(all(e <= s for (_, e), (s, _) in zip(spans, spans[1:])))
        self.assertGreaterEqual(nv.CONTROL, nc.CONTROL + nc.CONTROL_BYTES)
        self.assertEqual(nv.REDIRECT + 36, nv.CONTROL + nv.F['views'])

    def test_hash_rows_extend_only_the_table(self):
        rows = nv.hash_rows()
        self.assertTrue(all(cls == 7 for _, cls, *_ in rows))
        lean = nh.table_bytes(profile='lean')
        extended = nh.table_bytes(rows=nh.descriptors('lean') + rows)
        self.assertEqual(extended[:len(lean) - 16], lean[:-16])
        self.assertEqual(len(extended), len(lean) + 16 * len(rows))
        self.assertLessEqual(nc.TABLE + len(extended), nc.TABLE_END)


@unittest.skipUnless(os.environ.get('TAGTEAM_NETPLAY_VIEW_FIXTURE'), 'needs a converted single-view fixture')
class FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from camera_snapshot import read_ram
        cls.ram = read_ram(os.environ['TAGTEAM_NETPLAY_VIEW_FIXTURE'])

    def test_installs_every_site_with_core_and_no_overlap(self):
        blocks = nv.blocks(self.ram)
        self.assertEqual(nv.parse_control(dict(blocks)[nv.CONTROL])['patched'], 63)
        core = nc.blocks(self.ram, mode=nc.LOCKSTEP, delay=1, extra_rows=nv.hash_rows())
        spans = sorted((p, p + len(b)) for p, b in blocks + core)
        self.assertTrue(all(e <= s for (_, e), (s, _) in zip(spans, spans[1:])))
        words = {p: struct.unpack_from('<I', b)[0] for p, b in blocks if len(b) in (4, 8)}
        self.assertEqual(words[0x23EFF0], nv.j(nv.SEL))
        self.assertEqual(words[0x12BCD8], nv.jal(nv.SWAP))
        self.assertEqual(words[0x2455A8], nv.jal(nv.BURST))
        self.assertEqual(words[0x2455B0], 0x50400023)
        self.assertEqual(words[TIE_BREAK], nv.jal(nv.VIEWER))
        self.assertEqual(struct.unpack_from('<I', self.ram, TIE_BREAK)[0], nv.jal(VIEWED), 'the fixture is native')

    def test_refuses_a_changed_tie_break(self):
        ram = bytearray(self.ram)
        put(ram, TIE_BREAK, 0x24020001)
        with self.assertRaises(ValueError):
            nv.blocks(bytes(ram))

    def test_refuses_a_split_view_image(self):
        ram = bytearray(self.ram)
        put(ram, SCENE + 36, 1)
        with self.assertRaises(ValueError):
            nv.blocks(bytes(ram))


if __name__ == '__main__':
    unittest.main()
