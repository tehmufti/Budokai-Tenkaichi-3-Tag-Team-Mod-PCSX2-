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


if __name__ == '__main__':
    unittest.main()
