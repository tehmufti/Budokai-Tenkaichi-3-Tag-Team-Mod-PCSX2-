"""Assistant-only pose routing with actual native animation-flag decoding."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import os
import struct
import subprocess
import sys
import unittest
from pathlib import Path
import beam_assist_pose as fix
import beam_pose
from native_map import A, GPO, GP, elf_path
from prototype import ROOT, elf_reader
from test_tag_rush_camera import CameraCpu

MANAGER=0x1900000
ACTORS=[0x2000000+i*0x2000 for i in range(4)]
MODELS=[0x2400000+i*0x2000 for i in range(4)]
PARAMS=0x3000000
SLOT=fix.assist.CONTROL+fix.assist.SLOTS
BATTLE=0x1950000


def machine():
    c=CameraCpu({'segments':[]});c.r[28]=GP
    for address,data in ((fix.CODE,fix.code()),(fix.assist.GATE,fix.assist.gate_code()),
                         (fix.assist.RUNNING,fix.assist.running_code()),
                         (fix.assist.SLOTOF,fix.assist.slotof_code()),
                         (fix.beam.GATE,fix.beam.gate_code()),(fix.beam.VALID,fix.beam.valid_code())):
        c.write(address,data)
    c.write(fix.FLAGS,elf_reader(elf_path(ROOT))[2](fix.FLAGS,0x38))
    c.w(MANAGER+32,0x3100100)
    for clip in (264,298,332,364):c.w(0x3100100+4*clip,0x80000040)
    c.w(fix.core.ACTORS,MANAGER);c.w(MANAGER,2)
    c.write(fix.core.MODE,struct.pack('<4I',1,4,MANAGER,4))
    c.write(fix.CONTROL,struct.pack('<2I',fix.MAGIC,MANAGER))
    c.write(fix.assist.CONTROL,struct.pack('<4I',fix.assist.MAGIC,MANAGER,4,BATTLE))
    c.w(fix.assist.CONTROL+fix.assist.C['assist'],1)
    c.w(fix.beam.team_intro.BATTLE,BATTLE);c.w(BATTLE,3)
    c.write(fix.beam.CONTROL,struct.pack('<4I',fix.beam.MAGIC,MANAGER,4,BATTLE))
    c.w(fix.beam.ACTIVE,2);c.w(fix.beam.CONTROL+24,9)
    c.write(fix.beam.ACTORS,struct.pack('<2I',*ACTORS[:2]))
    c.write(fix.beam.MODELS,struct.pack('<2I',0,1));c.write(fix.beam.INDICES,struct.pack('<2I',0,1))
    for i,(actor,model) in enumerate(zip(ACTORS,MODELS)):
        c.w(fix.core.POINTERS+4*i,actor);c.w(fix.beam.CONTROL+0x100+4*i,actor)
        c.w(fix.core.MODELS+4*i,model);c.w(actor,i);c.w(actor+12,i)
        c.w(actor+2376,304);c.w(actor+0x9E4,30000)
        c.w(model+4,1);c.w(model+8,1);c.w(model+16,i);c.w(model+2348,PARAMS)
        for clip in (264,298,332,364):
            pointer=0x3200000+clip*16;c.w(model+192+clip*4,pointer);c.w(pointer,256)
    for key,value in dict(actor=ACTORS[2],phys=2,state=fix.assist.P_PENDING,serial=9).items():
        c.w(SLOT+fix.assist.S[key],value)
    c.write(PARAMS,bytes(640));c.poses=[]
    c.callbacks[fix.NATIVE]=lambda m:c.poses.append((m.r[4],m.r[5],m.f[12]))
    return c


def run(c,index=2,clip=264):
    c.r[4]=ACTORS[index];c.r[5]=clip;c.f[12]=0x3E4CCCCD;c.r[31]=0xFEED0000
    c.run(fix.CODE);return c.poses[-1][1]


class AssistPoseTests(unittest.TestCase):
    def test_registered_assist_selects_own_beam_then_generic_without_actor_changes(self):
        for slot,expected in ((2,264),(3,298),(4,332),(0,364)):
            c=machine()
            if slot:c.write(PARAMS+316+slot,b'\2')
            before=[c.read(a,0x1600)for a in ACTORS]
            self.assertEqual(run(c),expected)
            self.assertEqual([c.read(a,0x1600)for a in ACTORS],before)
            self.assertEqual(c.poses,[(ACTORS[2],expected,0x3E4CCCCD)])

    def test_native_participants_and_unregistered_or_stale_assist_keep_exact_original(self):
        for kind in ('leader','enemy','unregistered','moving','failed','serial','disabled','manager','ended','dead','identity','reload','action'):
            c=machine();index=2
            if kind in ('leader','enemy'):index=('leader','enemy').index(kind)
            elif kind=='unregistered':c.w(SLOT,0)
            elif kind=='moving':c.w(SLOT+fix.assist.S['state'],fix.assist.P_MOVING)
            elif kind=='failed':c.w(SLOT+fix.assist.S['state'],fix.assist.P_FAILED)
            elif kind=='serial':c.w(SLOT+fix.assist.S['serial'],8)
            elif kind=='disabled':c.w(fix.assist.CONTROL+fix.assist.C['assist'],0)
            elif kind=='manager':c.w(fix.CONTROL+4,MANAGER+16)
            elif kind=='ended':c.w(fix.beam.ACTIVE,0)
            elif kind=='dead':c.w(ACTORS[2]+0x9E4,0)
            elif kind=='identity':c.w(MODELS[2]+16,3)
            elif kind=='reload':c.w(MODELS[2]+8,0)
            elif kind=='action':c.w(ACTORS[2]+2376,11)
            self.assertEqual(run(c,index,332),332,kind)

    def test_missing_clip_and_paired_native_flag_are_not_borrowed(self):
        c=machine();c.w(MODELS[2]+192+364*4,0);self.assertEqual(run(c),264)
        c=machine();c.w(0x3100100+364*4,0xA0000040);self.assertEqual(run(c),264)
        c=machine();c.write(PARAMS+318,b'\2');c.write(PARAMS+315,b'\1')
        self.assertEqual(run(c),364)

    def test_confirmed_assist_preserves_caller_registers_and_fpu(self):
        c=machine();c.w(SLOT+fix.assist.S['state'],fix.assist.P_CONFIRMED)
        c.r[4]=ACTORS[2];c.r[5]=264;c.r[31]=0xFEED0000
        before=c.r.copy();floats=c.f.copy();c.run(fix.CODE)
        self.assertEqual(c.r[:5]+c.r[6:],before[:5]+before[6:])
        self.assertEqual(c.r[5],364);self.assertEqual(c.f,floats)

    def test_exact_native_hook_and_checked_reinstallation(self):
        native=elf_reader(elf_path(ROOT))[2];self.assertEqual(native(fix.HOOK,8),fix.NATIVE_HEAD)
        ram=bytearray(0x8000000)
        struct.pack_into('<I',ram,fix.assist.CONTROL,fix.assist.MAGIC)
        struct.pack_into('<I',ram,fix.assist.CONTROL+fix.assist.C['manager'],MANAGER)
        struct.pack_into('<I',ram,fix.assist.CONTROL+fix.assist.C['assist'],1)
        ram[fix.HOOK:fix.HOOK+8]=fix.NATIVE_HEAD
        result=fix.build_memory(ram)
        for row in result['blocks']:
            data=bytes.fromhex(row['data_hex']);p=row['address'];ram[p:p+len(data)]=data
        self.assertEqual(fix.build_memory(ram)['blocks'],[])
        ram[fix.CODE]^=1
        with self.assertRaisesRegex(ValueError,'installation changed'):fix.build_memory(ram)

    def test_regional_native_pose_calls_and_helpers_compile(self):
        if not all((ROOT/'analysis'/name).is_file() for name in ('SLES_549.45','SLPS_258.15')):
            self.skipTest('Regional executable fixtures are unavailable in this tree')
        for adapter in ('bt3-pal','bt3-jpn'):
            env=dict(os.environ,TAGTEAM_ADAPTER=adapter)
            result=subprocess.run([sys.executable,'-c',
              "import sys; from pathlib import Path; import native_map as n; root=Path(sys.argv[1]); original=n.elf_path; n.elf_path=lambda _:original(root); import prototype; prototype.ROOT=root; import beam_assist_pose as f; assert prototype.elf_reader(n.elf_path(root))[2](f.HOOK,8)==f.NATIVE_HEAD; print(len(f.code()))",str(ROOT)],
              cwd=Path(__file__).parent,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
