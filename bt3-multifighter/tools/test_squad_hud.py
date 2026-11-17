"""The team chip and the winner banner of a Team Battle with three to five teams (squad_hud.py)."""
import struct
import unittest

import battle_mode_policy as policy
import fresh_team_camera as camera
import fresh_team_combat as core
import guest_killfeed as feed
import localization
import squad_hud
import tag_rush_hud as meter
import viewport_hud as hud
from native_map import GPO
from regional import Y_ORIGIN, screen_y
from test_ai_shadow import GP, Mips

MANAGER, VIEWPORT = 0x1870400, 0x01A00000


class Captions(unittest.TestCase):
    def test_records_in_english_and_spanish(self):
        data = squad_hud.data()
        self.assertEqual(len(data), 2*policy.MAX_TEAMS*squad_hud.RECORD)
        for team in range(policy.MAX_TEAMS):
            chip = data[team*32:team*32+28].rstrip(b'\0'); banner = data[160+team*32:160+team*32+28].rstrip(b'\0')
            self.assertEqual((chip, banner), (f'TEAM {team+1}'.encode(), f'TEAM {team+1} WINS'.encode()))
            left = struct.unpack_from('<I', data, 160+team*32+28)[0]
            self.assertEqual(left, 256-len(banner)*18//2)
        with localization.using({'language': 'es'}):
            data = squad_hud.data()
        self.assertEqual(data[64:92].rstrip(b'\0'), b'EQUIPO 3')
        self.assertEqual(data[160+64:160+92].rstrip(b'\0'), b'GANA EL EQUIPO 3')
        left = struct.unpack_from('<I', data, 160+64+28)[0]
        self.assertTrue(4 <= left and left+16*18 <= 512)            # the longest banner stays on the screen

    def test_installed_only_with_a_team_table(self):
        ram = bytearray(0x8000000)
        self.assertIsNone(squad_hud.hud_extension(ram))
        self.assertEqual(squad_hud.build_memory(ram)['blocks'], [])
        self.assertIn('squad_hud', hud.HUD_EXTENSION_MODULES)
        self.assertEqual(hud.hud_extensions(ram), ())
        squads = policy.squad_layout((2, 2, 2))
        ram[policy.SQUAD:policy.SQUAD+0x100] = squads.block(MANAGER)
        struct.pack_into('<4I', ram, policy.CONTROL, policy.MAGIC, MANAGER, 6, policy.FFA)
        blocks = squad_hud.build_memory(ram)['blocks']               # no HUD wrapper in this image: the pieces only
        self.assertEqual([b['address'] for b in blocks], [squad_hud.CODE, squad_hud.BIG_TEXT, squad_hud.DATA])
        for b in blocks:
            data = bytes.fromhex(b['data_hex']); ram[b['address']:b['address']+len(data)] = data
        self.assertEqual(squad_hud.hud_extension(ram), squad_hud.entry())
        self.assertEqual(squad_hud.build_memory(ram)['blocks'], [])


class Draw(unittest.TestCase):
    def run_pass(self, squads, *, split=None, subject=0, target=1, winner=-1, rect=(0, 511, 0, 447)):
        with policy.building_squads(squads): code = squad_hud.draw_code()
        m = Mips(dict(segments=[dict(address=squad_hud.CODE, data_hex=code.hex()),
                                dict(address=squad_hud.DATA, data_hex=squad_hud.data().hex())]))
        m.w((GP+GPO(-22364)) & 0xFFFFFFFF, MANAGER); m.w((GP+GPO(-22176)) & 0xFFFFFFFF, VIEWPORT)
        block = bytearray(squads.block(MANAGER))
        struct.pack_into('<i', block, policy.SQUAD_FIELDS['winner_team'], winner)
        m.write(policy.SQUAD, bytes(block))
        for offset, value in zip((512, 516, 520, 524), rect): m.w(VIEWPORT+offset, value)
        m.w(camera.SUCCESSOR_CONTROL+8, subject); m.w(core.TABLE+4*subject, target)
        if split is not None:
            for index, (view_rect, who) in enumerate(split):
                at = hud.VIEWS+index*hud.VIEW_STRIDE; holder = 0x01B00000+4*index
                m.write(at, struct.pack('<6I', 1, *view_rect, holder)); m.w(holder, who)
        calls = []
        def text(kind):
            def call(machine): calls.append((kind, machine.r[4], machine.r[5], machine.r[6], machine.r[7]))
            return call
        m.callbacks[feed.TEXT] = text('small'); m.callbacks[squad_hud.BIG_TEXT] = text('big')
        m.callbacks[hud.ACTIVE] = lambda machine: machine.r.__setitem__(2, int(split is not None))
        m.instruction_budget = 40000; stack = m.r[29]
        m.run(squad_hud.CODE)
        self.assertEqual(m.r[29], stack)
        return calls

    @staticmethod
    def at(x, y): return ((x+1792) << 4, (y+Y_ORIGIN) << 4)

    def test_one_full_view_names_its_team_and_the_team_it_is_locked_on(self):
        squads = policy.squad_layout((2, 2, 2, 2, 2))
        calls = self.run_pass(squads, subject=2, target=5)
        own, other = calls
        self.assertEqual(own, ('small', squad_hud.DATA, *self.at(meter.FULL_X, screen_y(meter.FULL_LABEL)), policy.TEAM_COLORS[0]))
        self.assertEqual(other, ('small', squad_hud.DATA+32*3,
                                 *self.at(511-meter.FULL_X-squad_hud.CHIP_WIDTH, screen_y(meter.FULL_LABEL)), policy.TEAM_COLORS[3]))

    def test_split_views_show_their_own_fighter_and_mirror_the_right_column(self):
        squads = policy.squad_layout((2, 2, 2, 2, 2))
        views = (((0, 254, 0, 447), 8), ((257, 511, 0, 447), 9))            # the split team's two fighters
        left = self.run_pass(squads, split=views, rect=views[0][0])
        right = self.run_pass(squads, split=views, rect=views[1][0])
        self.assertEqual(left, [('small', squad_hud.DATA+32*4, *self.at(meter.SPLIT_X, screen_y(meter.SPLIT_Y)), policy.TEAM_COLORS[4])])
        self.assertEqual(right, [('small', squad_hud.DATA+32*4,
                                  *self.at(511-meter.SPLIT_X-squad_hud.CHIP_WIDTH, screen_y(meter.SPLIT_Y)), policy.TEAM_COLORS[4])])
        # a pass that is none of the views draws no chip
        self.assertEqual(self.run_pass(squads, split=views, rect=(0, 511, 0, 223)), [])

    def test_the_banner_names_the_winning_team(self):
        squads = policy.squad_layout((2, 2, 2))
        calls = self.run_pass(squads, subject=0, target=1, winner=2)
        self.assertEqual(calls[-1], ('big', squad_hud.DATA+160+32*2, *self.at(256-11*18//2, screen_y(squad_hud.BANNER_ROW)),
                                     policy.TEAM_COLORS[2]))
        self.assertEqual(len(calls), 3)
        self.assertEqual([c[0] for c in self.run_pass(squads, winner=-1)], ['small', 'small'])

    def test_another_match_draws_nothing(self):
        squads = policy.squad_layout((2, 2, 2))
        with policy.building_squads(squads): code = squad_hud.draw_code()
        m = Mips(dict(segments=[dict(address=squad_hud.CODE, data_hex=code.hex())]))
        m.w((GP+GPO(-22364)) & 0xFFFFFFFF, MANAGER+0x40); m.write(policy.SQUAD, squads.block(MANAGER))
        m.callbacks[feed.TEXT] = lambda machine: self.fail('drawn in another match')
        m.run(squad_hud.CODE)


if __name__ == '__main__':
    unittest.main()
