"""Selection and clash code cannot share the match preparation staging area."""
import struct
import unittest
import clash_sequence as clash
import cpu_difficulty_select as cpu
import loading_protocol as loading
import native_preparation as preparation


class FeatureReservations(unittest.TestCase):
    def test_menu_and_clash_survive_every_preparation_packet_size(self):
        spans = [(cpu.BASE, cpu.END), (clash.BASE, clash.END)]
        forbidden = list(preparation.protected_ranges())
        forbidden += [(p, p + loading.CAPACITY) for p in loading.BUFFERS]
        for lo, hi in spans:
            self.assertTrue(all(hi <= start or end <= lo for start, end in forbidden))
        self.assertTrue(cpu.END <= clash.BASE or clash.END <= cpu.BASE)

    def test_every_clash_piece_can_be_submitted_through_native_preparation(self):
        pieces = clash.pieces()
        blocks = [dict(address=p, expected_hex=bytes(len(data)).hex(), data_hex=data.hex()) for p, data in pieces]
        packet = preparation.encode({'blocks': blocks})
        self.assertTrue(packet)

    def guarded_image(self):
        import cinematic_contact_guard as contact
        from native_map import A
        native=clash.elf_reader(clash.elf_path(clash.ROOT))[2]
        ram=bytearray(0x8000000)
        struct.pack_into('<2I',ram,clash.dash.CONTROL,clash.dash.MAGIC,0x1870400)
        for p,n in ((clash.INPUT_ENTRY,8),(clash.PROMPT_ENTRY,8),*((p,4) for p in clash.AWARDS)):
            ram[p:p+n]=native(p,n)
        ram[A(0x1D9900):A(0x1D9900)+8]=clash.jump(clash.dash.FRAME)
        index,(_,cave,kind,rejected)=next((i,s) for i,s in enumerate(contact.SPECS) if s[0]==clash.INPUT_ENTRY)
        guard=contact.wrapper(clash.INPUT_ENTRY,cave,kind,rejected,native(clash.INPUT_ENTRY,8),index)
        ram[cave:cave+len(guard)]=guard
        ram[clash.INPUT_ENTRY:clash.INPUT_ENTRY+8]=clash.jump(cave)
        struct.pack_into('<I',ram,clash.core.ACTORS,0x1870400)
        return ram,cave

    def test_clash_keeps_the_installed_throw_guard_and_rejects_foreign_code(self):
        ram,cave=self.guarded_image()
        manifest=clash.build_memory(ram,{clash.KEY:True})
        self.assertTrue(preparation.encode(manifest))
        for b in manifest['blocks']:
            p=b['address'];data=bytes.fromhex(b['data_hex']);ram[p:p+len(data)]=data
        self.assertEqual(ram[clash.OLD_INPUT:clash.OLD_INPUT+8],clash.jump(cave))
        self.assertFalse(clash.build_memory(ram,{clash.KEY:True})['blocks'])
        self.assertEqual(len(clash.build_memory(ram,{clash.KEY:False})['blocks']),1)
        ram[cave+8]^=1
        with self.assertRaisesRegex(ValueError,'contact guard changed'):
            clash.build_memory(ram,{clash.KEY:True})

    def test_clash_chains_revival_and_scenario_protection(self):
        import teammate_revive as revive
        import story_runtime as story
        ram,cave=self.guarded_image()
        struct.pack_into('<I',ram,revive.CONTROL,revive.MAGIC)
        struct.pack_into('<I',ram,revive.CONTROL+24,revive.OPTIONS_VERSION)
        struct.pack_into('<I',ram,revive.CONTROL+44,cave)
        guard=revive.barrier(revive.COMMAND,cave,'command',prescan=True)
        ram[revive.COMMAND:revive.COMMAND+len(guard)]=guard
        ram[clash.INPUT_ENTRY:clash.INPUT_ENTRY+8]=clash.jump(revive.COMMAND)
        for b in clash.build_memory(ram,{clash.KEY:True})['blocks']:
            p=b['address'];data=bytes.fromhex(b['data_hex']);ram[p:p+len(data)]=data
        self.assertEqual(story.dependency_override(ram,clash.INPUT_ENTRY,clash.jump(revive.COMMAND)),clash.jump(clash.INPUT))
        # Scenario protection may be added afterward, retaining this chain.
        struct.pack_into('<3I',ram,story.CONTROL,story.MAGIC,0x1870400,0)
        wrapper=story.protection_code(story.COMMAND,clash.INPUT,'command')
        ram[story.COMMAND:story.COMMAND+len(wrapper)]=wrapper
        ram[clash.INPUT_ENTRY:clash.INPUT_ENTRY+8]=clash.jump(story.COMMAND)
        self.assertEqual(story.dependency_override(ram,clash.INPUT_ENTRY,clash.jump(revive.COMMAND)),clash.jump(story.COMMAND))
        self.assertFalse(clash.build_memory(ram,{clash.KEY:True})['blocks'])
        ram[revive.COMMAND+8]^=1
        with self.assertRaisesRegex(ValueError,'revival guard changed'):
            clash.build_memory(ram,{clash.KEY:True})


class TeamBattleReservations(unittest.TestCase):
    """Three to five teams: the menu block 0x06600000..0x06660000 and the free part of the battle-mode
    reservation, 0x07121000..0x0712F200 (the team table sits at its end, behind the mode control)."""
    MENU = (0x06600000, 0x06660000)
    MODE = (0x07121000, 0x0712F200)
    OWNERS = {'native_mode_menu.py', 'squad_select.py', 'battle_mode_policy.py', 'battle_modes.py', 'squad_hud.py'}

    def test_the_menu_block_holds_the_team_pages_and_nothing_else_does(self):
        import native_mode_menu as menu
        import squad_select as select
        lo, hi = self.MENU
        pieces = [(menu.TEAMS_OFF, menu.TEAMS_ON), (menu.TEAMS_ON, select.GUARD), (select.GUARD, select.DRAW),
                  (select.DRAW, menu.ATLASES), (menu.ATLASES, select.DATA), (select.DATA, select.END)]
        self.assertEqual((pieces[0][0], pieces[-1][1]), (lo, hi))
        self.assertTrue(all(a < b for a, b in pieces))
        for p, data in menu.code_pieces():
            if lo <= p < hi:
                owner = next((a, b) for a, b in pieces if a <= p < b)
                self.assertLessEqual(p+len(data), owner[1], hex(p))
        forbidden = list(preparation.protected_ranges())
        forbidden += [(p, p + loading.CAPACITY) for p in loading.BUFFERS]
        forbidden += [(cpu.BASE, cpu.END), (clash.BASE, clash.END)]
        self.assertTrue(all(hi <= start or end <= lo for start, end in forbidden))

    def test_the_team_table_sits_inside_the_battle_mode_reservation(self):
        import battle_mode_policy as policy
        import battle_modes as modes
        lo, hi = self.MODE
        self.assertEqual((policy.SQUAD, policy.SQUAD_END), (policy.CONTROL+0x100, hi))
        self.assertTrue(modes.FFA_DEFEAT < lo < policy.CONTROL < policy.SQUAD < policy.SQUAD_END <= modes.END)
        self.assertLessEqual(modes.FFA_DEFEAT+len(modes.squad_defeat_code()), lo)
        self.assertLessEqual(modes.FFA_DEFEAT+len(modes.defeat_code()), lo)
        self.assertLessEqual(len(policy.squad_layout((2, 2, 2)).block(0x1870400)), policy.SQUAD_END-policy.SQUAD)
        # the free part in use: the time-over rule, then the team HUD
        import squad_hud
        with policy.building_squads(policy.squad_layout((2, 2, 2))):
            self.assertLessEqual(modes.TIME_OVER+len(modes.squad_timeover_code()), squad_hud.CODE)
            for (address, data), limit in zip(squad_hud.pieces(), (squad_hud.BIG_TEXT, squad_hud.DATA, squad_hud.END)):
                self.assertLessEqual(address+len(data), limit)
        self.assertTrue(lo <= modes.TIME_OVER < squad_hud.CODE < squad_hud.END <= policy.CONTROL)

    def test_no_other_module_names_an_address_in_either_range(self):
        import re
        from pathlib import Path
        literal = re.compile(r'0x0[67][0-9A-Fa-f]{6}')
        found = {}
        for path in sorted(Path(__file__).resolve().parent.glob('*.py')):
            if path.name.startswith('test_') or path.name in self.OWNERS: continue
            for text in literal.findall(path.read_text(encoding='utf-8', errors='replace')):
                value = int(text, 16)
                if any(lo <= value < hi for lo, hi in (self.MENU, self.MODE)):
                    found.setdefault(path.name, set()).add(text)
        self.assertEqual(found, {})


if __name__ == '__main__':
    unittest.main()
