"""Active patch identity, cache history and the last check before PCSX2 loads it."""
from pathlib import Path
import hashlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'bt3-multifighter/online/netplay'))
import kit_ident as ident
import kit_install
import kit_paths
import kit_emu
import runtime_profile
from kit_codes import KitError


class PatchIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)

    def installation(self,name,own=b'current patch',old=(),*,linux=None):
        root=self.root/name;runtime=root/'online/match/runtime'
        if linux is None:linux=not runtime_profile.WINDOWS
        for card in ident.MEMCARDS:
            path=runtime/'memcards'/card;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'blank card')
        for data in old:self.cached(runtime,data)
        if own is not None:
            path=root/'game/runtime28'/('PCSX2/cheats'if linux else 'cheats')/ident.PNACH
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(own)
        return root,runtime

    def cached(self,runtime,data):
        sha=hashlib.sha256(data).hexdigest();path=runtime/'pnach'/(sha+'.pnach')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        return sha,path

    def identity(self,installation):
        root,runtime=installation
        with patch.multiple(kit_paths,INTEGRATED=True,INSTALL_ROOT=root,RUNTIME=runtime), \
                patch.object(ident,'code_identity',return_value={'digest':'same code'}):
            return ident.local_identity(disc={},bios={},ini_text='',pcsx2=dict(digest='same emulator',tested=True,savestate=1))

    def refusals(self,one,two):return [r[0]for r in ident.compare(one,two)if r[1]=='refuse']

    def test_same_active_patch_with_different_old_font_and_upgrade_histories(self):
        first=self.installation('first',old=(b'old RAQM patch',b'legacy build'))
        other=self.installation('other',old=(b'old BASIC patch',))
        one,two=self.identity(first),self.identity(other)
        self.assertEqual(one['patches'],two['patches'])
        self.assertEqual(self.refusals(one,two),[])
        self.cached(other[1],b'one more abandoned cached patch')
        self.assertEqual(self.identity(other)['patches'],one['patches'])
        self.assertEqual(one['patches']['pnach_sha256'],[hashlib.sha256(b'current patch').hexdigest()])

    def test_actual_active_patch_difference_still_refuses_both_directions(self):
        first=self.identity(self.installation('first',own=b'patch=1,EE,00100000,word,00000000\n'))
        other=self.identity(self.installation('other',own=b'patch=1,EE,00100000,word,00000001\n'))
        self.assertEqual(self.refusals(first,other),['TTM-NET-04'])
        self.assertEqual(self.refusals(other,first),['TTM-NET-04'])

    def test_missing_active_patch_never_falls_back_to_an_old_supported_cache(self):
        installation=self.installation('missing',own=None,old=(b'old runtime',))
        with self.assertRaises(KitError)as error:self.identity(installation)
        self.assertEqual(error.exception.code,'TTM-NET-25')

    def test_profile_backup_cannot_override_the_actual_runtime_patch(self):
        installation=self.installation('profile')
        path=installation[0]/'game/runtime28/a-backup/cheats'/ident.PNACH
        path.parent.mkdir(parents=True);path.write_bytes(b'wrong obsolete backup')
        value=self.identity(installation)
        self.assertEqual(value['patches']['pnach_sha256'],[hashlib.sha256(b'current patch').hexdigest()])

    def test_linux_uses_its_actual_portable_data_folder(self):
        installation=self.installation('linux',linux=True)
        with patch.object(runtime_profile,'WINDOWS',False):value=self.identity(installation)
        self.assertEqual(value['patches']['pnach_sha256'],[hashlib.sha256(b'current patch').hexdigest()])

    def test_damaged_current_cache_is_rebuilt_from_the_installed_source(self):
        installation=self.installation('damaged');runtime=installation[1]
        sha,path=self.cached(runtime,b'current patch');path.write_bytes(b'cache was truncated')
        value=self.identity(installation)
        self.assertEqual(value['patches']['pnach_sha256'],[sha])
        self.assertEqual(path.read_bytes(),b'current patch')

    def test_active_cache_cannot_be_missing_invalid_or_tampered(self):
        _,runtime=self.installation('invalid',own=None,old=(b'one',))
        for active in ('not a hash','f'*64):
            with self.assertRaises(KitError)as error:ident.patches_identity(runtime,active=active)
            self.assertEqual(error.exception.code,'TTM-NET-25')
        sha,path=self.cached(runtime,b'expected');path.write_bytes(b'tampered')
        with self.assertRaises(KitError)as error:ident.patches_identity(runtime,active=sha)
        self.assertEqual(error.exception.code,'TTM-NET-25')

    def test_standalone_legacy_kits_still_compare_their_complete_patch_set(self):
        first=self.installation('one',own=None,old=(b'legacy one',))
        other=self.installation('two',own=None,old=(b'legacy one',b'legacy two'))
        one,two=ident.patches_identity(first[1]),ident.patches_identity(other[1])
        self.assertNotEqual(one['digest'],two['digest'])

    def test_memory_cards_remain_informational(self):
        first=self.installation('one');other=self.installation('two')
        (other[1]/'memcards'/ident.MEMCARDS[0]).write_bytes(b'different card')
        one,two=self.identity(first),self.identity(other)
        self.assertEqual(self.refusals(one,two),[])
        self.assertEqual([(c,l)for c,l,_ in ident.compare(one,two)],[('TTM-NET-04','note')])

    def test_chosen_patch_is_checked_again_at_emulator_install(self):
        installation=self.installation('race');value=self.identity(installation)
        runtime=installation[1];sha=value['patches']['pnach_sha256'][0]
        emu=kit_emu.Emulator(root=self.root/'emulator')
        with patch.object(kit_paths,'RUNTIME',runtime):
            self.assertTrue(emu.install_pnach(sha));self.assertFalse(emu.install_pnach(sha))
            cached=runtime/'pnach'/(sha+'.pnach');cached.write_bytes(b'changed after handshake')
            with self.assertRaises(KitError)as error:emu.install_pnach(sha)
        self.assertEqual(error.exception.code,'TTM-NET-25')
        self.assertEqual((emu.root/'cheats'/ident.PNACH).read_bytes(),b'current patch')

    def test_cache_change_after_the_check_cannot_change_the_installed_bytes(self):
        import atomic_files
        installation=self.installation('changed-during-copy');value=self.identity(installation)
        runtime=installation[1];sha=value['patches']['pnach_sha256'][0]
        cached=runtime/'pnach'/(sha+'.pnach');write=atomic_files.write_bytes
        def racing_write(target,data):
            cached.write_bytes(b'changed between checking and installation')
            return write(target,data)
        emu=kit_emu.Emulator(root=self.root/'racing-emulator')
        with patch.object(kit_paths,'RUNTIME',runtime),patch.object(atomic_files,'write_bytes',side_effect=racing_write):
            self.assertTrue(emu.install_pnach(sha))
        self.assertEqual((emu.root/'cheats'/ident.PNACH).read_bytes(),b'current patch')


if __name__=='__main__':unittest.main()
