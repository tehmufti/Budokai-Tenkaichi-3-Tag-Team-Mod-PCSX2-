"""Tag Team Tournament transitions under the watcher's cover (round 5): the owned in-game cover, its carry into a
loaded state, the draft's black veil, the covered result hand-back and the reveal at the tournament's opening."""
# Native execution tests use only the developer's own fixture helpers.
import importlib.util as _TestSpec
import unittest as _TestUnit
if not all(_TestSpec.find_spec(_name) for _name in ('test_guest_loading_screen',)):
    raise _TestUnit.SkipTest('The developer loading-screen fixture helpers are required for tournament transition tests')
import struct
import unittest
from unittest.mock import patch

from PIL import Image

import guest_loading_screen as g
import localization as loc
import loading_protocol as protocol
import tag_tournament as tt
import test_guest_loading_screen as screen_fixture
from test_ai_shadow import Mips


class ZeroRam:
    """A RAM image of zeros for cover_blocks (only sliced)."""
    def __getitem__(self, s):
        return bytes(s.stop - s.start)


def black():
    return Image.new('RGB', (512, 448), (0, 0, 0))


class OwnedCover(unittest.TestCase):
    def setUp(self):
        g.invalidate_buffers()

    def test_owned_surface_draws_in_every_scene_without_a_modal_owner_while_leased(self):
        for scene_loop in (0, 1):
            for lease_age, drawn in ((0, True), (g.LEASE, False)):
                c, packet = screen_fixture.machine()
                c.w(g.SCENE_LOOP, scene_loop); c.w(g.CONTROL+32, g.OWNED); c.w(g.CONTROL+16, lease_age)
                screen_fixture.frame(c)
                self.assertEqual(bool(c.refs), drawn, (scene_loop, lease_age))
                if drawn:
                    self.assertEqual(c.u(g.CONTROL+12), 0, 'an owned cover counts menu frames')
                    self.assertEqual(c.u(g.CONTROL+g.MENU_FRAMES), 1)

    def test_cover_blocks_make_a_loaded_image_draw_the_cover_from_its_first_frame(self):
        record = g.cover_record(black())
        blocks = g.cover_blocks(record, ZeroRam(), counters=(5, 40, 151))
        self.assertEqual([b['address'] for b in blocks], [g.CONTROL, g.BUFFERS[0]])
        self.assertTrue(all(set(bytes.fromhex(b['expected_hex'])) <= {0} for b in blocks))
        c, _ = screen_fixture.machine()
        for b in blocks:
            c.write(b['address'], bytes.fromhex(b['data_hex']))
        c.w(g.SCENE_LOOP, 0)
        screen_fixture.frame(c)
        self.assertTrue(c.refs)
        self.assertEqual(c.read(c.refs[0][1], len(record['packet'])), record['packet'])
        self.assertEqual(c.u(g.CONTROL+24), g.BUFFERS[0])                 # consumed: the guest took it
        self.assertEqual(c.u(g.CONTROL+g.MENU_FRAMES), 41)                # the animation goes on
        self.assertEqual(c.u(g.CONTROL+g.CYCLE_WORD), 2)                  # 151 % 150, one step

    def test_the_cover_is_carried_into_the_buffer_the_image_did_not_hand_to_its_gs(self):
        class Ram(ZeroRam):
            def __init__(self, consumed):
                self.consumed = consumed

            def __getitem__(self, s):
                data = bytearray(super().__getitem__(s))
                at = g.CONTROL+24
                if s.start <= at < s.stop:
                    data[at-s.start:at-s.start+4] = struct.pack('<I', self.consumed)
                return bytes(data)
        for consumed, buffer in ((g.BUFFERS[0], g.BUFFERS[1]), (g.BUFFERS[1], g.BUFFERS[0]), (0, g.BUFFERS[0])):
            record = g.cover_record(black())
            blocks = g.cover_blocks(record, Ram(consumed))
            self.assertEqual(record['buffer'], buffer)
            self.assertEqual(blocks[1]['address'], buffer)
            control = bytes.fromhex(blocks[0]['data_hex'])
            self.assertEqual(struct.unpack_from('<I', control, 4)[0], buffer)
            self.assertEqual(struct.unpack_from('<I', control, 24)[0], consumed)

    def test_adopted_cover_only_renews_its_lease_and_draws_from_menu_frames(self):
        p = screen_fixture.FakePine(); p.install()
        record = g.cover_record(black())
        for b in g.cover_blocks(record, ZeroRam()):
            p.write(b['address'], bytes.fromhex(b['data_hex']))
        p.writes = []
        screen = g.GuestLoadingScreen()
        screen.adopt(record)
        with patch('pine.PineClient', return_value=p):
            self.assertTrue(screen.sync(True))
            self.assertFalse(any(g.BUFFERS[0] <= a < g.BUFFERS[1] + g.CAPACITY for a, _ in p.writes),
                             'no buffer upload after an adopt')
            self.assertEqual(p.read_u32(g.CONTROL+32), g.OWNED)
            p.write_u32(g.CONTROL+24, g.BUFFERS[0]); p.write_u32(g.CONTROL+g.MENU_FRAMES, 3)
            p.write_u32(g.CONTROL+g.DRAWN_LATCH, 1)
            self.assertTrue(screen.presented(p))
            self.assertTrue(screen.wait_drawn(0.2))
        self.assertEqual(screen.record()['generation'], record['generation'])

    def test_show_owned_and_show_picture_owned_publish_surface_two(self):
        p = screen_fixture.FakePine(); p.install()
        screen = g.GuestLoadingScreen()
        with patch('pine.PineClient', return_value=p):
            screen.show_picture(black(), surface='owned')
            self.assertEqual(p.read_u32(g.CONTROL+32), g.OWNED)
            screen.show_picture(black(), surface='battle')
            self.assertEqual(p.read_u32(g.CONTROL+32), 0)

    def test_new_cover_texts_translate_as_the_cover_draws_them(self):
        import autopilot
        for text in (autopilot.TOURNAMENT_START_COVER, autopilot.TOURNAMENT_PASS_COVER):
            self.assertIn(text.upper(), loc.ES)
            self.assertLessEqual(len(text), 60)


def cpu(segments):
    c = Mips({'segments': [dict(address=a, data_hex=d.hex()) for a, d in segments]})
    c.instruction_budget = 20000
    return c


class HandBack(unittest.TestCase):
    def pine_with_streams(self, statuses):
        p = screen_fixture.FakePine()
        for ch, status in enumerate(statuses):
            handle = 0x00900000 + 0x100*ch
            p.write_u32(tt.ADX_TABLE+tt.ADX_ROW*ch, handle if status is not None else 0)
            if status is not None:
                p.write(handle, bytes((1, status, 0, 2)))
        return p

    def test_stream_playing_reads_the_native_stream_statuses(self):
        self.assertTrue(tt.stream_playing(self.pine_with_streams((0, 3, None, 0, 0, 0))))
        self.assertFalse(tt.stream_playing(self.pine_with_streams((0, 5, None, 1, 0, 0))))

    def test_no_guest_stream_stop_is_installed(self):
        # The game's own ADXT stop from the pad hook left the restored final crawling (live Oct 20).
        import native_mode_menu as nmm
        self.assertFalse(hasattr(tt, 'hush_code'))
        self.assertNotIn('hush', tt.F)
        self.assertEqual(sorted(a for a, _ in tt.service_pieces()),
                         sorted((tt.PAD_CODE, tt.VEIL_CHECK, tt.DRAW_CODE, tt.WATCH_CODE)))
        self.assertGreater(len(nmm.payload()), 0)

    def test_covered_copy_carries_only_the_black_owned_cover(self):
        seen = {}

        def fake_patch(source, manifest, out):
            import json
            seen['blocks'] = json.loads(open(manifest, encoding='utf-8').read())['blocks']
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            original = Path(d) / tt.ORIGINAL_NAME
            original.write_bytes(b'')
            with patch('state128.read_entry', return_value=bytes(0x8000000)),                     patch('zipfile.ZipFile'), patch('patch_state.patch', side_effect=fake_patch):
                out, record = tt.covered_copy(original, original.with_name(tt.COVERED_NAME))
        addresses = {b['address']: bytes.fromhex(b['data_hex']) for b in seen['blocks']}
        self.assertEqual(sorted(addresses), sorted((g.CONTROL, record['buffer'])))
        self.assertEqual(struct.unpack_from('<I', addresses[g.CONTROL], 32)[0], g.OWNED)
        self.assertEqual(addresses[record['buffer']][16:16+len(record['packet'])], record['packet'])
        self.assertEqual(out.name, tt.COVERED_NAME)


class DraftVeil(unittest.TestCase):
    def machine(self, scene=40, magic=tt.DRAFT_MAGIC, length=None, stage_open=True):
        c = cpu([(tt.VEIL_CHECK, tt.veil_check_code()), (tt.PAD_CODE, tt.pad_code())])
        manager, obj = 0x00600000, 0x00800000
        c.w(tt.SCENE_MANAGER, manager); c.w(manager+0x18, scene)
        c.w(tt.DRAFT, magic); c.w(tt.DRAFT+tt.DRAFT_VEIL, len(tt.veil_packet()) if length is None else length)
        c.w(tt.TEAM_SELECT, obj); c.w(obj+tt.SEL_FLAGS, 4 if stage_open else 0)
        return c

    def test_veil_packet_fits_and_the_service_pieces_stay_apart_inside_the_reservation(self):
        self.assertLessEqual(len(tt.veil_packet()), tt.VEIL_CAPACITY)
        pieces = sorted(tt.service_pieces())
        for (a, d), (b, _) in zip(pieces, pieces[1:]):
            self.assertLessEqual(a+len(d), b)
        self.assertTrue(all(tt.BASE <= a and a+len(d) <= tt.END for a, d in pieces))
        self.assertLessEqual(tt.SPARES+4+2*tt.SPARE_MAX, tt.VEIL)
        self.assertLessEqual(tt.VEIL+tt.VEIL_CAPACITY, tt.VEIL_CHECK)
        self.assertLessEqual(tt.DRAFT+tt.DRAFT_VEIL+4, tt.READY)

    def test_veil_only_over_the_drafts_open_stage_selection(self):
        cases = ((dict(), len(tt.veil_packet())), (dict(scene=4), 0), (dict(magic=0), 0), (dict(length=0), 0),
                 (dict(length=tt.VEIL_CAPACITY+16), 0), (dict(stage_open=False), 0))
        for kwargs, expected in cases:
            c = self.machine(**kwargs)
            self.assertEqual(c.run(tt.VEIL_CHECK), 0xFEED0000)
            self.assertEqual(c.r[2], expected, kwargs)

    def test_draw_code_asks_for_the_veil_first(self):
        words = struct.unpack(f'<{len(tt.draw_code())//4}I', tt.draw_code())
        self.assertEqual([w for w in words if w >> 26 == 3][0], tt.jal(tt.VEIL_CHECK))

    def test_open_stage_selection_withholds_every_button_of_both_ports(self):
        c = self.machine()
        for port in (0, 0x1C0):
            for off in (0x150, 0x18C, 0x190):
                c.w(tt.PAD_RECORDS+port+off, 0xFFFF)
        self.assertEqual(c.run(tt.PAD_CODE), 0xFEED0000)
        for port in (0, 0x1C0):
            for off in (0x150, 0x18C, 0x190):
                self.assertEqual(c.u(tt.PAD_RECORDS+port+off), 0, (port, off))
        c = self.machine(stage_open=False)
        c.w(tt.PAD_RECORDS+0x18C, 0xFFFF)
        c.run(tt.PAD_CODE)
        self.assertEqual(c.u(tt.PAD_RECORDS+0x18C), 0xFFFF)


class Opening(unittest.TestCase):
    def pine(self, wait=0, script=0):
        p = screen_fixture.FakePine()
        obj = 0x00800000
        p.write_u32(tt.RUNTIME, obj); p.write_u32(obj+tt.OBJ_WAIT, wait); p.write_u32(obj+tt.OBJ_SCRIPT, script)
        return p

    def test_opening_starts_with_the_logo_jingle_or_any_later_script_step(self):
        self.assertFalse(tt.opening_started(self.pine()))
        self.assertTrue(tt.opening_started(self.pine(wait=tt.LOGO_WAIT)))
        self.assertTrue(tt.opening_started(self.pine(script=0x38)))
        p = self.pine(wait=tt.LOGO_WAIT); p.write_u32(tt.RUNTIME, 0)
        self.assertFalse(tt.opening_started(p))

    def test_veil_comes_down_at_the_opening_or_at_the_next_fighter_select(self):
        import time
        c = tt.Controller(); c.log = lambda text: None
        c.armed = True
        c.veil = dict(kind='start', since=time.monotonic())
        p = self.pine()
        with patch.object(tt.Controller, 'scene', staticmethod(lambda q: (0, tt.MAIN_MENU))):
            self.assertFalse(c.veil_tick(p))                         # the main menu under the cover
        with patch.object(tt.Controller, 'scene', staticmethod(lambda q: (0, tt.BRACKET_SCENE))):
            self.assertFalse(c.veil_tick(p))                         # scene 35 still loading
            p.write_u32(0x00800000+tt.OBJ_WAIT, tt.LOGO_WAIT)
            self.assertTrue(c.veil_tick(p))                          # the tournament's logo starts: cover down
        c.veil = dict(kind='start', since=time.monotonic(), bracket=time.monotonic()-tt.LOGO_SECONDS-1)
        with patch.object(tt.Controller, 'scene', staticmethod(lambda q: (0, tt.BRACKET_SCENE))):
            self.assertTrue(c.veil_tick(self.pine()))               # no logo seen: down anyway
        c.veil = dict(kind='pass', since=time.monotonic())
        c.draft = dict(stage='commit')
        with patch.object(tt.Controller, 'scene', staticmethod(lambda q: (0, tt.MAIN_MENU))):
            self.assertFalse(c.veil_tick(p))
        c.veil['since'] -= tt.VEIL_SECONDS + 1
        with patch.object(tt.Controller, 'scene', staticmethod(lambda q: (0, tt.MAIN_MENU))):
            self.assertTrue(c.veil_tick(p))                          # time limit
        c.veil = None
        self.assertTrue(c.veil_tick(p))


if __name__ == '__main__':
    unittest.main()
