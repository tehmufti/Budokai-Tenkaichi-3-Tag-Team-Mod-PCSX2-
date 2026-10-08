"""Keep unrelated fighters visible during captured specials in all pause modes.

Only the native exclusive-owner branch is relaxed. Per-actor hide flags,
registered model activation, authored paired subjects and camera state remain
native. This module never connects to the emulator.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path

from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
import special_pause as pause

ENTRY = A(0x1C0FB8)
CODE, DECIDE, CONTROL = 0x07523000, 0x07523400, 0x0753F200
MAGIC = 0x53564932
CONTINUE, HIDE = A(0x1C0FC0), A(0x1C0FF8)
PRIOR = struct.pack('<2I', 0x1633000F, 0x0200202D)
core = pause.core


def wrapper_code():
    a = Assembler(CODE)
    # The original delay instruction establishes a0=current actor before this
    # code. Preserve every native GPR and the existing function stack frame.
    pause.save(a, pause.SAVED, 0x100); a.call(DECIDE)
    a.branch(5, 2, 0, 'relaxed')
    pause.restore(a, pause.SAVED, 0x100)
    a.branch(5, 17, 19, 'hide'); a.jump(CONTINUE)
    a.label('hide'); a.jump(HIDE)
    a.label('relaxed'); pause.restore(a, pause.SAVED, 0x100); a.jump(CONTINUE)
    data=a.finish(); assert len(data)<=DECIDE-CODE; return data


def decide_code(*, legacy=False, kernel_scratch=False):
    # k0/k1 belong to the EE kernel: its interrupt entry overwrites them and never restores them (LS-2 rig run
    # D0011: an interrupt between 'lui/ori k0' and 'lw t0,0(k0)' left k0 = COP0 Status 0x70030C17; the load
    # TLB-missed forever and the match hung). a2/a3 are free here: the wrapper saves every GPR. The legacy and
    # kernel_scratch (beta.33) forms rebuild the bytes older releases installed, for in-place upgrades.
    k0,k1=(26,27) if legacy or kernel_scratch else (6,7)
    a=Assembler(DECIDE); pause.mode_gate(a,'native',include_all=not legacy)
    a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,'native')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'native')
    a.lw(9,8,8);a.branch(5,9,10,'native')
    a.move(20,10);a.move(21,17);a.move(22,19)
    for r in (21,22):
        a.r(0x2B,8,r,20);a.branch(4,8,0,'native')
    a.branch(4,21,22,'native')
    a.move(24,0);a.li(25,core.POINTERS);a.li(k0,pause.CONTROL+0x80)
    a.move(14,0);a.move(15,0)
    # Resolve current and exclusive owner by captured physical identity. Actual
    # models may be nonconsecutive, or change resources during a leader reload.
    a.label('validate');a.lw(23,25);a.lw(8,k0);a.branch(5,23,8,'native')
    a.lw(8,23);a.branch(5,8,24,'native')
    a.lw(8,23,12);a.i(11,9,8,12);a.branch(4,9,0,'native')
    a.r(0,9,0,8,2);a.li(11,core.MODELS);a.r(0x2D,9,9,11);a.lw(9,9)
    a.li(11,0x100000);a.r(0x2B,11,9,11);a.branch(5,11,0,'native')
    a.li(11,0x8000000-0x1670);a.r(0x2B,11,9,11);a.branch(4,11,0,'native')
    a.lw(11,9,16);a.branch(5,8,11,'native')
    a.branch(5,24,21,'not_current');a.branch(5,23,16,'native');a.move(14,9)
    a.label('not_current');a.branch(5,24,22,'next');a.move(15,23)
    a.label('next');a.addiu(24,24,1);a.addiu(25,25,4);a.addiu(k0,k0,4)
    a.branch(5,24,20,'validate')
    a.lw(8,15,2376);a.addiu(9,8,-253);a.i(11,9,9,63);a.branch(4,9,0,'native')
    # A bound subject's intentional exclusive hide stays authored. Merely
    # being the selected target does not hide an otherwise visible fighter.
    a.addiu(9,8,-301);a.i(11,9,9,3);a.branch(5,9,0,'pair')
    a.addiu(9,8,-313);a.i(11,9,9,3);a.branch(4,9,0,'camera_check')
    a.label('pair');a.lw(8,15,3732);a.lw(9,15,3736)
    for r in (8,9):
        a.r(0x2B,11,r,20);a.branch(4,11,0,'native')
    a.branch(4,8,9,'native');a.branch(4,22,8,'pair_valid');a.branch(5,22,9,'native')
    a.label('pair_valid');a.branch(4,21,8,'native');a.branch(4,21,9,'native')
    a.label('camera_check');a.lw(k1,28,-22180);a.branch(4,k1,0,'relax')
    a.lw(8,k1,812);a.branch(5,8,0,'camera')
    a.lw(8,k1,704);a.branch(4,8,0,'relax')
    a.lw(8,k1,776);a.i(12,8,8,3);a.addiu(9,0,1);a.branch(5,8,9,'relax')
    a.label('camera')
    for off in (768,772):
        a.lw(13,k1,off);a.branch(4,13,0,f'next{off}')
        a.branch(4,13,14,'native')
        a.move(24,0);a.li(25,core.POINTERS)
        a.label(f'scan{off}');a.lw(8,25);a.lw(8,8,12);a.r(0,8,0,8,2)
        a.li(9,core.MODELS);a.r(0x2D,8,8,9);a.lw(8,8)
        a.branch(4,8,13,f'next{off}')
        a.addiu(24,24,1);a.addiu(25,25,4);a.branch(5,24,20,f'scan{off}')
        a.jump('native')
        a.label(f'next{off}')
    a.label('relax');a.li(8,CONTROL);a.lw(9,8,12);a.addiu(9,9,1);a.sw(9,8,12)
    a.sw(14,8,16);a.sw(22,8,20);a.addiu(2,0,1);a.jr()
    a.label('native');a.move(2,0);a.jr()
    data=a.finish();assert DECIDE+len(data)<0x07525000
    # Clear the whole previous predicate footprint during an in-place upgrade.
    return data if legacy else data.ljust(len(decide_code(legacy=True)),b'\0')


def program(*, legacy=False, kernel_scratch=False):
    return [(CODE,wrapper_code()),(DECIDE,decide_code(legacy=legacy,kernel_scratch=kernel_scratch)),
            (ENTRY,struct.pack('<2I',(2<<26)|(CODE>>2),0x0200202D))]


def build_memory(ram,config=None,source='<offline-memory>'):
    manager,count,battle,actors=pause.identity(ram);pause.dependencies(ram,manager,count)
    if pause.installed_version(ram,manager,count,battle,actors)!=2:
        raise ValueError('Upgrade to three-mode special_pause before visibility')
    _,_,native=elf_reader(elf_path(ROOT))
    # Every surrounding instruction remains native; this prevents accidental
    # replay against a different visibility function or patched local hides.
    for p,n in ((A(0x1C0EB8),ENTRY-A(0x1C0EB8)),(ENTRY+8,A(0x1C1040)-ENTRY-8)):
        if ram[p:p+n]!=native(p,n):raise ValueError(f'Native visibility flow changed:{p:08X}')
    upgraded=None
    if all(ram[p:p+len(data)]==data for p,data in program()):
        if struct.unpack_from('<3I',ram,CONTROL)!=(MAGIC,manager,count):
            raise ValueError('Visibility capture ownership mismatch')
        pieces=[]
    elif all(ram[p:p+len(data)]==data for p,data in program(legacy=True)):
        if struct.unpack_from('<3I',ram,CONTROL)!=(MAGIC,manager,count):
            raise ValueError('Visibility capture ownership mismatch')
        # Preserve capture and observation counters; only expand the existing
        # predicate to include native-pause mode. Its timing code is untouched.
        pieces=[(DECIDE,decide_code())];upgraded=2
    elif all(ram[p:p+len(data)]==data for p,data in program(kernel_scratch=True)):
        if struct.unpack_from('<3I',ram,CONTROL)!=(MAGIC,manager,count):
            raise ValueError('Visibility capture ownership mismatch')
        # The beta.33 predicate kept values in k0/k1; replace it in place, keeping capture and counters.
        pieces=[(DECIDE,decide_code())];upgraded=3
    else:
        if ram[ENTRY:ENTRY+8]!=PRIOR:raise ValueError('Visibility hook changed')
        if any(ram[CODE:0x07525000]) or any(ram[CONTROL:CONTROL+64]):
            raise ValueError('Visibility reservation occupied')
        control=bytearray(64);struct.pack_into('<3I',control,0,MAGIC,manager,count)
        pieces=program()+[(CONTROL,bytes(control))]
    return dict(serial=SERIAL,crc=CRC,source=str(source),control=CONTROL,
                version=4,upgrade_from=upgraded,
                status='ALL-MODE SPECIAL VISIBILITY; LIVE VALIDATION REQUIRED',
                blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex()) for p,d in pieces],
                limitations=['Only exclusive-owner hiding is relaxed for unrelated registered fighters.',
                             'Actor-local vanish/hide flags, authored bound subjects and inactive models remain native.',
                             'Unknown camera subjects, menus, loading and results retain native behavior.',
                             'Pause mode changes timing only; unrelated fighters stay visible in all three modes.'])


def build(source):return build_memory(read_ram(source),source=source)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();args.out.write_text(json.dumps(build(args.source),indent=2)+'\n')
