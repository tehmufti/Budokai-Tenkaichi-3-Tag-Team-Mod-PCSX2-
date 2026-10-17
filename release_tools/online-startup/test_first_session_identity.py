"""A fresh installation and a rejoining peer advertise the same patch set."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'bt3-multifighter/online/netplay'))
import kit_ident as ident
import kit_install
import kit_paths


class FirstSessionIdentityTests(unittest.TestCase):
    def test_patch_is_installed_before_the_first_handshake(self):
        with tempfile.TemporaryDirectory()as folder:
            root=Path(folder);runtime=root/'online/match/runtime'
            for name in ident.MEMCARDS:
                p=runtime/'memcards'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'blank test card')
            old=b'old supported runtime patch';own=b'this installed release patch'
            p=runtime/'pnach'/(hashlib.sha256(old).hexdigest()+'.pnach');p.parent.mkdir();p.write_bytes(old)
            p=root/'game/runtime28/cheats'/ident.PNACH;p.parent.mkdir(parents=True);p.write_bytes(own)
            with patch.multiple(kit_paths,INTEGRATED=True,INSTALL_ROOT=root,RUNTIME=runtime), \
                    patch.object(ident,'code_identity',return_value={'digest':'same-code'}):
                before=ident.patches_identity()
                first=ident.local_identity(disc={},bios={},ini_text='',pcsx2={'tested':True})
                # This is also called by preboot/launch after the handshake.
                kit_install.installation_pnach()
                rejoin=ident.local_identity(disc={},bios={},ini_text='',pcsx2={'tested':True})
            self.assertEqual(len(before['pnach_sha256']),1)
            self.assertEqual(len(first['patches']['pnach_sha256']),2)
            self.assertEqual(first['patches'],rejoin['patches'])
            self.assertFalse(any(row[0]=='TTM-NET-04'for row in ident.compare(first,rejoin)))

    def test_standalone_identity_does_not_copy_an_installation_patch(self):
        with patch.object(kit_paths,'INTEGRATED',False), \
                patch.object(kit_install,'installation_pnach')as copy, \
                patch.object(ident,'code_identity',return_value={}), \
                patch.object(ident,'patches_identity',return_value={}):
            ident.local_identity(disc={},bios={},ini_text='',pcsx2={'tested':True})
        copy.assert_not_called()


if __name__=='__main__':unittest.main()
