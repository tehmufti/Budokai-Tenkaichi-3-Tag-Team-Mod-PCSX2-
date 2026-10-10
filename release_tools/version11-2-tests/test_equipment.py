"""Portable online equipment ownership, canonical encoding and match identity."""
import copy
import struct
import unittest

from support import catalog
import kit_lobby
import kit_potara
import kit_spec
import kit_ident


class EquipmentTests(unittest.TestCase):
    def setUp(self):
        self.catalog = catalog()

    def test_native_encoding_and_strict_validation(self):
        items = [137,2,124]
        self.assertEqual(kit_potara.native(items), struct.pack('<8H',3,125,138,0,0,0,0,0))
        self.assertEqual(kit_potara.selected(kit_potara.native(items)), sorted(items))
        self.assertFalse(kit_potara.problems(items,self.catalog))
        for bad in ([True],[-1],[350],[24],[2,2],[1,2],[137,138],[2,5,124],list(range(9)),'2'):
            with self.subTest(items=bad):
                self.assertTrue(kit_potara.problems(bad,self.catalog))
        self.assertEqual(kit_potara.native([]),bytes(16))

    def test_uneven_match_identity_includes_each_fighters_equipment(self):
        teams = [[dict(character=0,costume=0,potaras=[2,124,137]),
                  dict(character=0,costume=1,potaras=[5])],
                 [dict(character=54,costume=0,potaras=[])]]
        first = kit_spec.make(tables_sha256='a'*64,teams=teams,stage=0)
        self.assertFalse(kit_spec.problems(first,self.catalog))
        teams[0][0]['potaras'].reverse()
        reordered = kit_spec.make(tables_sha256='a'*64,teams=teams,stage=0)
        self.assertEqual(kit_spec.spec_sha(first),kit_spec.spec_sha(reordered))
        teams[0][1]['potaras'] = []
        second = kit_spec.make(tables_sha256='a'*64,teams=teams,stage=0)
        self.assertNotEqual(kit_spec.spec_sha(first),kit_spec.spec_sha(second))
        self.assertEqual(kit_ident.KIT_VERSION,kit_spec.KIT)
        self.assertEqual(kit_ident.PROTOCOL,8)

    def test_ownership_ready_and_character_changes_preserve_equipment(self):
        lobby = kit_lobby.Lobby()
        guest = lobby.join('Guest')
        lobby.match['teams'][0][0]['owner'] = guest
        lobby.members[guest]['ready'] = True
        self.assertFalse(lobby.set_fighter(guest,0,0,0,0,self.catalog,[2,124]))
        self.assertFalse(lobby.members[guest]['ready'])
        before = copy.deepcopy(lobby.match)
        for team,index in ((1,0),(-1,0),(0,-1)):
            self.assertTrue(lobby.set_fighter(guest,team,index,0,0,self.catalog,[2]))
            self.assertEqual(before,lobby.match)
        self.assertFalse(lobby.set_fighter(guest,0,0,54,1,self.catalog))
        self.assertEqual(lobby.match['teams'][0][0]['potaras'],[2,124])
        self.assertFalse(lobby.set_fighter(1,1,0,0,0,self.catalog,[137]))
        snapshot = lobby.snapshot()
        snapshot['match']['teams'][0][0]['potaras'] = [True]
        self.assertEqual(kit_lobby.snapshot_problem(snapshot),'potaras')


if __name__ == '__main__':
    unittest.main()
