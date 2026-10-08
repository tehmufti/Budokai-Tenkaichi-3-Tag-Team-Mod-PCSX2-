"""Complete cinematic camera binding and identify the actual viewed participant.

The earlier selector restored only gp-22176 after loading a side camera. Native
23E6A0 also loads VU matrices24..31 and the GS scissor; all three must agree.
This wrapper rebinds the selected camera without advancing the cinematic twice.
The participant helper follows the current KO successor and verifies the bound
model/recorded special pair instead of matching any simultaneous paired action.
Offline captured4/6 builder; no emulator access.
"""
from native_map import A, CRC, SERIAL
import argparse
import json
import struct
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
import fresh_team_combat as core
import fresh_team_camera as fresh
import leader_camera as leader
from battle_mode_policy import ACTOR_COUNTS

CODE, PARTICIPANT, OLD_PARTICIPANT, CONTROL = 0x073F0000, 0x073F0800, 0x073F1C00, 0x073F2000
HELPER_ENTRY = fresh.LEADER_INNER+leader.PARTICIPANT_OFFSET
CAMERA, CINEMATIC = A(0x2FEBD0), A(0x2FEBCC)


def wrapper():
    a = Assembler(CODE); a.addiu(29, 29, -0x40)
    for r, off in ((16,0),(17,8),(31,16)): a.i(63,r,29,off)
    a.call(fresh.LEADER); a.i(63,2,29,24); a.i(63,3,29,32)
    core.gate(a,'return')
    a.li(16,CONTROL); a.lw(8,16); a.branch(4,8,0,'return')
    a.lw(8,16,4); a.lw(9,28,-22364); a.branch(5,8,9,'return')
    a.li(8,core.PAIR+4); a.lw(8,8); a.branch(5,8,0,'return')
    a.lw(17,28,-22176)
    a.li(8,0x100000); a.r(0x2B,9,17,8); a.branch(5,9,0,'return')
    a.li(8,0x08000000-832); a.r(0x2B,9,17,8); a.branch(4,9,0,'return')
    a.i(12,9,17,15); a.branch(5,9,0,'return')
    # Exact native camera bind: both VU matrices, scissor, then active pointer.
    a.move(4,17); a.addiu(5,0,1); a.call(A(0x23E6A0))
    a.lw(8,16,8); a.addiu(8,8,1); a.sw(8,16,8)
    a.sw(17,16,16); a.lw(8,29,24); a.sw(8,16,20)
    a.lw(8,28,-22180); a.branch(5,8,17,'return')
    a.lw(8,16,12); a.addiu(8,8,1); a.sw(8,16,12)
    a.label('return'); a.i(55,2,29,24); a.i(55,3,29,32)
    for r, off in ((16,0),(17,8),(31,16)): a.i(55,r,29,off)
    a.addiu(29,29,0x40); a.jr()
    result=a.finish(); assert len(result)<PARTICIPANT-CODE; return result


def participant():
    a=Assembler(PARTICIPANT); a.addiu(29,29,-0x20)
    for i,r in enumerate((3,24,25)): a.i(63,r,29,i*8)
    core.gate(a,'old'); a.move(15,10)
    a.li(8,CONTROL); a.lw(9,8); a.branch(4,9,0,'old')
    a.lw(9,8,4); a.lw(8,28,-22364); a.branch(5,8,9,'old')
    a.i(11,8,4,2); a.branch(4,8,0,'no')
    a.move(10,4)
    # Camera side and fighter physical ID diverge after KO succession.
    a.li(8,fresh.SUCCESSOR_CONTROL); a.lw(9,8); a.branch(4,9,0,'owner')
    a.lw(9,8,4); a.lw(2,28,-22364); a.branch(5,9,2,'owner')
    a.r(0,9,0,4,2); a.r(0x2D,8,8,9); a.lw(9,8,8)
    a.r(0x2B,2,9,15); a.branch(4,2,0,'owner'); a.move(10,9)
    a.label('owner'); a.li(8,core.POINTERS); a.r(0,9,0,10,2); a.r(0x2D,8,8,9); a.lw(11,8)
    a.branch(4,11,0,'no'); a.lw(12,28,-22180); a.branch(4,12,0,'no')
    a.lw(13,12,768); a.lw(14,12,772)
    a.lw(3,11,12); a.i(11,2,3,12); a.branch(4,2,0,'no')
    a.r(0,3,0,3,2); a.li(8,core.MODELS); a.r(0x2D,8,8,3); a.lw(25,8)
    a.branch(4,25,0,'no'); a.branch(4,25,13,'yes'); a.branch(4,25,14,'yes')
    a.lw(8,11,0x948)
    for start in (301,313):
        a.addiu(9,8,-start); a.i(11,9,9,3); a.branch(5,9,0,'paired')
    a.addiu(9,8,-183); a.i(11,9,9,5); a.branch(4,9,0,'no')
    a.i(11,9,10,2); a.branch(4,9,0,'no')
    a.i(14,24,10,1); a.jump('other')
    a.label('paired')
    # Explicit position-driven cameras do not have a model bind. Keep the
    # previous paired-state fallback only for that unbound native mode.
    a.r(0x25,8,13,14); a.branch(4,8,0,'yes')
    a.lw(8,11,3732); a.lw(9,11,3736)
    a.r(0x2B,2,8,15); a.branch(4,2,0,'no')
    a.r(0x2B,2,9,15); a.branch(4,2,0,'no'); a.branch(4,8,9,'no')
    a.branch(4,10,8,'attacker'); a.branch(5,10,9,'no'); a.move(24,8); a.jump('other')
    a.label('attacker'); a.move(24,9)
    a.label('other'); a.li(8,core.POINTERS); a.r(0,9,0,24,2); a.r(0x2D,8,8,9); a.lw(8,8)
    a.branch(4,8,0,'no'); a.lw(9,8,12); a.i(11,2,9,12); a.branch(4,2,0,'no')
    a.r(0,9,0,9,2); a.li(8,core.MODELS); a.r(0x2D,8,8,9); a.lw(8,8)
    a.branch(4,8,0,'no'); a.branch(4,8,13,'yes'); a.branch(4,8,14,'yes')
    a.label('no'); a.move(2,0); a.jump('return')
    a.label('yes'); a.addiu(2,0,1)
    a.label('return')
    for i,r in enumerate((3,24,25)): a.i(55,r,29,i*8)
    a.addiu(29,29,0x20); a.jr()
    a.label('old')
    for i,r in enumerate((3,24,25)): a.i(55,r,29,i*8)
    a.addiu(29,29,0x20); a.jump(OLD_PARTICIPANT)
    result=a.finish(); assert len(result)<OLD_PARTICIPANT-PARTICIPANT; return result


def build_memory(ram, config=None, source='<offline-memory>'):
    if len(ram)!=0x8000000: raise ValueError('Requires128MiB EE memory')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager=u(core.ACTORS); count=u(core.MODE+4)
    if not 0x100000<=manager<len(ram)-0x1000 or u(manager)!=2: raise ValueError('Native captured manager required')
    if u(core.MODE)!=1 or u(core.MODE+8)!=manager or count not in ACTOR_COUNTS or u(core.MODE+12)!=count:
        raise ValueError('Active captured4/6 team required')
    old_inner=fresh.rebound(leader.payload_cinematic,Assembler=fresh.FreshAssembler,CODE=fresh.LEADER_INNER,CONTROL=fresh.LEADER_CONTROL)()
    if ram[fresh.LEADER_INNER:fresh.LEADER_INNER+len(old_inner)]!=old_inner:
        raise ValueError('Requires the exact existing cinematic-aware selector')
    old_scope=fresh.scope(fresh.LEADER,fresh.LEADER_INNER,fresh.LEADER_NATIVE)
    if ram[fresh.LEADER:fresh.LEADER+len(old_scope)]!=old_scope: raise ValueError('Fresh camera scope differs')
    old_hook=struct.pack('<2I',(2<<26)|(fresh.LEADER>>2),0)
    if ram[leader.HOOK:leader.HOOK+8]!=old_hook: raise ValueError('Camera hook already changed')
    if any(ram[CODE:CONTROL+0x100]): raise ValueError('Camera state reservation occupied')
    old_prefix=ram[HELPER_ENTRY:HELPER_ENTRY+8]
    trampoline=old_prefix+struct.pack('<2I',(2<<26)|((HELPER_ENTRY+8)>>2),0)
    control=bytearray(0x100); struct.pack_into('<2I',control,0,1,manager)
    pieces=[(CODE,wrapper(),'Rebind the final camera matrices and scissor without advancing its animation again'),
            (PARTICIPANT,participant(),'Match the current successor against actual bound model or recorded special pair'),
            (OLD_PARTICIPANT,trampoline,'Displaced original participant helper for inactive fallback'),
            (CONTROL,bytes(control),'Enabled,captured manager,rebind/cinematic counters,last camera/render mode'),
            (HELPER_ENTRY,struct.pack('<2I',(2<<26)|(PARTICIPANT>>2),0),'Route camera participation through current ownership'),
            (leader.HOOK,struct.pack('<2I',(2<<26)|(CODE>>2),0),'Preserve existing selection then bind its complete render state')]
    blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex(),purpose=w) for p,d,w in pieces]
    return dict(serial=SERIAL,crc=CRC,source=str(Path(source).resolve()),blocks=blocks,
                status='COMPLETE CINEMATIC CAMERA STATE AND CURRENT SUBJECT MATCHING',control=CONTROL,
                telemetry=dict(rebinds=CONTROL+8,cinematic_rebinds=CONTROL+12,last_camera=CONTROL+16,render_mode=CONTROL+20),
                limitations=['Native scripted camera paths and terrain placement are unchanged.',
                             'The game still has one shared cinematic camera; this does not create concurrent independent cinematic tracks.'])


def build(source): return build_memory(read_ram(source),source=source)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
    x=p.parse_args();r=build(x.source);x.out.write_text(json.dumps(r,indent=2)+'\n');print(f'{x.out}: {len(r["blocks"])} guarded blocks')
