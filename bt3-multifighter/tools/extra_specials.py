"""Allow captured NPC extras to use native Blast1, Blast2 and ultimate commands.

The original proof disabled both command dispatchers for every extra. This
upgrade removes only that blanket rejection for living captured CPUs. Native
input, ki/stock/MAX POWER eligibility, the cinematic admission lock and all
resource/transform protections still decide whether a move can start.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
import fresh_team_combat as core
import fresh_team_safety as safety
import cinematic_admission as admission
import extra_transform_guard as transforms
import projectile_pool_guard as projectile
import special_projectile_pool_guard as specialized
import effect_cleanup_owner as owner
import effect_texture_guard as texture
from battle_mode_policy import ACTOR_COUNTS
import battle_mode_policy as policy

CODE, CONTROL, RECORDS, END = 0x07440000, 0x0744F000, 0x0744F100, 0x07450000
# native entry, old blanket guard, new dispatcher, native trampoline, record fields
ENTRIES = ((A(0x203E00),0x07380800,CODE,CODE+0x800,0,4),
           (A(0x204128),0x07380C00,CODE+0x1000,CODE+0x1800,8,12))
SAVED = (2,3,8,9,10,11,12,13)


def payload(entry, previous, code, trampoline, attempts, successes, require_pools=True):
    a=Assembler(code);a.addiu(29,29,-0x90)
    for i,r in enumerate(SAVED):a.i(63,r,29,i*8)
    core.gate(a,'old')
    a.li(8,CONTROL);a.lw(9,8);a.branch(4,9,0,'old')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'old')
    a.lw(9,8,8);a.branch(5,9,10,'old')
    a.li(11,core.POINTERS+8);a.addiu(12,0,2)
    a.label('scan');a.lw(9,11);a.branch(4,9,4,'found')
    a.addiu(11,11,4);a.addiu(12,12,1);a.branch(5,12,10,'scan');a.jump('old')
    a.label('found')
    if require_pools:
        # Dispatch must wait for native per-model special rows and child pools.
        # The ordinary two-row effect manager is not safe for extra model IDs.
        a.li(11,0x0750F000);a.lw(9,11);a.addiu(13,0,5);a.branch(5,9,13,'old')
        a.lw(9,11,4);a.lw(13,28,-22364);a.branch(5,9,13,'old')
    a.lw(9,8,12);a.branch(4,9,0,'alive')
    a.lw(9,4,0x1278);a.branch(5,9,0,'alive')
    # A human may drive one captured extra: co-op player2 owns physical2 and
    # keeps CPU flag0, so the CPU requirement alone refused every special it
    # asked for (charging never reaches these dispatchers, which is why only
    # specials were missing). Named physicals are admitted by an explicit
    # mask; every other human-flagged extra still falls through to the old
    # blanket guard, exactly as before.
    a.lw(9,8,20);a.addiu(11,0,1);a.r(4,11,12,11)
    a.r(0x24,9,9,11);a.branch(4,9,0,'old')
    a.label('alive');a.lw(9,4,0x994);a.i(11,11,9,5);a.branch(4,11,0,'old')
    a.r(0,11,0,9,2);a.r(0x2D,11,11,9);a.r(0,11,0,11,3)
    a.r(0x2D,11,11,9);a.r(0,11,0,11,2);a.r(0x2D,11,11,4)
    a.lw(11,11,0x9E4);a.branch(6,11,0,'old')
    # Independent enable bit per captured physical extra, identity by pointer.
    a.lw(9,8,16);a.addiu(11,0,1);a.r(4,11,12,11)
    a.r(0x24,9,9,11);a.branch(4,9,0,'old')
    a.sw(12,29,0x40);a.sw(4,29,0x48);a.i(63,31,29,0x50)
    a.r(0,9,0,12,5);a.li(8,RECORDS);a.r(0x2D,8,8,9)
    a.lw(9,8,attempts);a.addiu(9,9,1);a.sw(9,8,attempts)
    for i,r in enumerate(SAVED):a.i(55,r,29,i*8)
    a.call(trampoline)
    # Retain the complete native return state while recording queued starts.
    for i,r in enumerate((8,9,10,11)):a.i(63,r,29,0x60+i*8)
    a.lw(8,29,0x40);a.r(0,8,0,8,5);a.li(9,RECORDS);a.r(0x2D,9,9,8)
    a.sw(2,9,20);a.branch(6,2,0,'return')
    a.lw(8,9,successes);a.addiu(8,8,1);a.sw(8,9,successes)
    a.lw(10,29,0x48);a.addiu(11,2,-1);a.i(11,8,11,4)
    a.branch(4,8,0,'return');a.r(0,11,0,11,2);a.r(0x2D,10,10,11)
    a.lw(8,10,2388);a.sw(8,9,16)
    a.label('return')
    for i,r in enumerate((8,9,10,11)):a.i(55,r,29,0x60+i*8)
    a.i(55,31,29,0x50);a.addiu(29,29,0x90);a.jr()
    a.label('old')
    for i,r in enumerate(SAVED):a.i(55,r,29,i*8)
    a.addiu(29,29,0x90);a.jump(previous)
    data=a.finish();assert len(data)<=0x800;return data


def dependencies(native):
    parts=[(admission.PREDICATE,admission.predicate_code())]
    for i,(entry,cave,previous,_) in enumerate(admission.ENTRIES[:2]):
        parts += [(entry,struct.pack('<2I',(2<<26)|(cave>>2),0)),
                  (cave,admission.wrapper(entry,cave,previous,native(entry,8),i))]
    # The reverse-transform entry is additionally wrapped by admission, so
    # validate the preceding loader implementation and its push/ready hooks.
    parts += [(p,d) for p,d in transforms.loader_guard_segments(native) if p!=transforms.loader.TRANSFORM_HOOK]
    parts += [(projectile.CODE,projectile.payload()),
              (projectile.HOOK,struct.pack('<I',(3<<26)|(projectile.CODE>>2))),
              (owner.CODE,owner.payload(native)),(owner.ENTRY,struct.pack('<2I',(2<<26)|(owner.CODE>>2),0)),
              (texture.CODE,texture.payload(native(texture.HOOK,8))),
              (texture.HOOK,struct.pack('<2I',(2<<26)|(texture.CODE>>2),0))]
    for family in specialized.FAMILIES:
        args={k:v for k,v in family.items() if k!='hooks'}
        parts.append((family['code'],projectile.payload(**args,descriptor_size=88,check_header=False)))
        for hook in family['hooks']:parts.append((hook,struct.pack('<I',(3<<26)|(family['code']>>2))))
    return parts


def build_memory(ram, config=None, source='<offline-memory>', *, cpu_only=True, enabled_mask=None, human_mask=0):
    if len(ram)!=0x8000000:raise ValueError('Requires128MiB EE RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if count not in ACTOR_COUNTS or u(core.MODE)!=1 or u(core.MODE+8)!=manager or u(core.MODE+12)!=count:
        raise ValueError('Requires an active captured4/6 match')
    if not 0x100000<=manager<len(ram)-0x1000 or u(manager)!=2 or u(core.PAIR+4):
        raise ValueError('Requires native manager identity and restored AI aliases')
    actors=[u(core.POINTERS+i*4) for i in range(count)]
    if len(set(actors))!=count:raise ValueError('Duplicate actor pointers')
    for i,actor in enumerate(actors):
        if not 0x100000<=actor<len(ram)-0x1600 or u(actor)!=i:raise ValueError('Invalid actual actor identity')
        mid=u(actor+12)
        if mid>=12 or not 0x100000<=u(core.MODELS+mid*4)<len(ram)-0x1670:raise ValueError('Invalid registered model')
    if any(ram[CODE:END]):raise ValueError('Extra special reservation occupied')
    _,_,native=elf_reader(elf_path(ROOT))
    for p,d in dependencies(native):
        if ram[p:p+len(d)]!=d:raise ValueError(f'Preserve installed cinematic/reload/effect guard{p:08X}')
    for ctrl in (admission.CONTROL,owner.CONTROL,texture.CONTROL,projectile.CONTROL,
                 *(f['control'] for f in specialized.FAMILIES)):
        if u(ctrl)!=1 or u(ctrl+4)!=manager:raise ValueError(f'Required protection inactive{ctrl:08X}')
    mask=((1<<count)-1)&~3 if enabled_mask is None else int(enabled_mask)
    if mask<0 or mask&~(((1<<count)-1)&~3):raise ValueError('Only captured extra enable bits are valid')
    humans=int(human_mask)
    if humans<0 or humans&~mask:raise ValueError('Human extras must be enabled captured extras')
    pieces=[]
    for entry,previous,code,trampoline,attempts,successes in ENTRIES:
        old=safety.owned_code(entry,previous,2,native(entry,8))
        if ram[previous:previous+len(old)]!=old:raise ValueError(f'Old blanket command guard changed{previous:08X}')
        if ram[entry:entry+8]!=struct.pack('<2I',(2<<26)|(previous>>2),0):raise ValueError('Command entry chain changed')
        # These bodies are intentionally native; eligibility calls inside them
        # must continue through the validated admission wrappers above.
        end=A(0x203F50) if entry==A(0x203E00) else A(0x2041FC)
        if ram[entry+8:end]!=native(entry+8,end-entry-8):raise ValueError('Native command dispatcher changed')
        tail=native(entry,8)+struct.pack('<2I',(2<<26)|((entry+8)>>2),0)
        pieces += [(code,payload(entry,previous,code,trampoline,attempts,successes)),(trampoline,tail),
                   (entry,struct.pack('<2I',(2<<26)|(code>>2),0))]
    control=bytearray(0x100);struct.pack_into('<6I',control,0,1,manager,count,int(cpu_only),mask,humans)
    # One 32-byte telemetry record per physical fighter (indexed by physical id).
    pieces += [(RECORDS,bytes(policy.emitted_actors()*32)),(CONTROL,bytes(control))]
    return dict(serial=SERIAL,crc=CRC,source=str(source),
        status='NPC EXTRA NATIVE SPECIAL COMMANDS; PER-MOVE LIVE VALIDATION REQUIRED',
        blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex()) for p,d in pieces],
        control=CONTROL,records=RECORDS,record_stride=32,
        telemetry={'blast2_checks':0,'blast2_starts':4,'blast1_checks':8,'blast1_starts':12,'last_queued_action':16,'last_return':20},
        behavior=['Living enabled captured extras may process native Blast1/Blast2/ultimate input commands.',
                  'Native resources, ki/stock/MAX POWER requirements and serialized cinematic admission remain.',
                  'Private AI input selection, native leader commands, extra transform/reload bounds and effect compatibility stay unchanged.'],
        limitations=['Incompatible borrowed projectile families remain safely suppressed and can reduce a move’s visible effect or damage.',
                     'Extras still cannot transform, fuse, use damaged costumes or unsupported throws.',
                     'This restores command dispatch, not universal character/move compatibility or guaranteed AI frequency.'])


def upgrade_memory(ram, source='<offline-memory>'):
    """Add readiness to a Sept12 pre-pool command proof without changing hooks.

    Both payloads are regenerated from the current source, so this only ever
    recognises an image whose dispatcher was built from this same revision.
    The human-extra mask (CONTROL+20) changed those bytes, so a genuine
    September12 image must be prepared afresh instead of patched in place.
    """
    blocks=[]
    for args in ENTRIES:
        entry,previous,code,trampoline,attempts,successes=args
        old=payload(*args,require_pools=False);new=payload(*args)
        if ram[entry:entry+8]!=struct.pack('<2I',(2<<26)|(code>>2),0):raise ValueError('Extra command hook changed')
        if ram[code:code+len(old)]!=old or any(ram[code+len(old):code+len(new)]):
            raise ValueError('Unrecognized old extra dispatcher; prepare this match again instead of upgrading it')
        blocks.append(dict(address=code,expected_hex=ram[code:code+len(new)].hex(),data_hex=new.hex()))
    return dict(serial=SERIAL,crc=CRC,source=str(source),blocks=blocks,
                status='WAIT FOR OWN SPECIAL EFFECT POOLS BEFORE EXTRA DISPATCH')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
    x=p.parse_args();m=build_memory(read_ram(x.source),source=x.source)
    x.out.write_text(json.dumps(m,indent=2)+'\n');print(f'{x.out}: {len(m["blocks"])} blocks')
