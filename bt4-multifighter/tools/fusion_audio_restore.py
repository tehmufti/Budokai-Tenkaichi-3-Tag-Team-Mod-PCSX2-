"""Restore the native leader's short-voice bank after a held defusion.

Streamed dialogue reads the current model; charging/grunts read SPU bank16/32,
which a model-only rebuild does not replace. Reuse the game's bounded sound
scratch allocation, then its ordinary asynchronous bank upload. No new bank,
heap allocation, blocking file-open loop, or modification to another actor's
sound bank. The caller keeps the existing defusion hold until upload completes.
"""
from native_map import A
import struct
from functools import lru_cache
import body_swap as body
import body_swap_runner as runner
import body_swap_resources as resources
import fusion_duration as timer
import extra_voice as voice
from prototype import Assembler,ROOT

ENTRY,CONTROL,END=runner.RETIRE,runner.RETIRE_CONTROL,runner.END
LOADER_GLOBAL,AUDIO_GLOBAL,OPTIONS_GLOBAL=A(0x2FF11C),A(0x2FF18C),A(0x2FF28C)


@lru_cache(maxsize=322)
def bank_file(character,japanese):
    # Native BT4 sub_19BD88 selects these expanded voice-bank ranges.
    import sys
    if str(ROOT.parent) not in sys.path:sys.path.insert(0,str(ROOT.parent))
    from iso_compatibility.disc import Disc,package
    from bt4_disc import ISO
    source=ISO
    with Disc(source) as disc:
        try:
            data=disc.read((0x1D10C if japanese else 0x1D012)+character)
            body.require(len(package(data))>=3 and len(data)<=591872,'Invalid native short-voice bank')
        except ValueError:
            if not japanese:raise
            # B14 REV2 slot246 has no valid Japanese short-voice PAK. Restore
            # this same fighter's English bank instead of stranding defusion.
            data=disc.read(0x1D012+character)
            body.require(len(package(data))>=3 and len(data)<=591872,'Invalid fallback short-voice bank')
    return data


def code(config):
    a=Assembler(ENTRY);a.addiu(29,29,-0x40)
    for i,r in enumerate((16,17,18,19,31)):a.i(63,r,29,8*i)
    a.li(16,CONTROL);a.lw(8,16);a.branch(4,8,0,'done')
    a.lw(8,16,4);a.addiu(9,0,5);a.branch(4,8,9,'done')
    for at,value in config['guards']:
        a.li(8,at);a.lw(8,8);a.li(9,value);a.branch(5,8,9,'error')
    a.lw(8,16,4);a.branch(5,8,0,'poll')
    # Stop only streams owned by the two former fusion partners.
    a.li(8,voice.CONTROL);a.lw(9,8);a.li(10,voice.MAGIC);a.branch(5,9,10,'streams_done')
    for slot in range(2):
        a.li(17,voice.CONTROL+voice.OWNERS+4*slot);a.lw(9,17)
        for pid in config['physical_ids']:
            a.addiu(10,0,pid+1);a.branch(4,9,10,f'stop{slot}')
        a.jump(f'next{slot}');a.label(f'stop{slot}')
        a.addiu(4,0,4+slot);a.call(A(0x265AD0));a.sw(0,17)
        a.label(f'next{slot}')
    a.label('streams_done')
    # Native SPU bank replacement stops its samples; discard the former
    # speakers' loop receipts too, or an identical request reuses a dead handle.
    for index,row in enumerate(config['loop_rows']):
        a.li(17,row)
        for slot in range(4):
            a.lw(4,17,12*slot);a.i(10,8,4,0);a.branch(5,8,0,f'loop{index}_{slot}')
            a.call(A(0x125128));a.addiu(8,0,-1);a.sw(8,17,12*slot)
            a.label(f'loop{index}_{slot}')
    if config['side']<2:
        a.addiu(4,0,16<<config['side']);a.li(5,config['buffer']);a.move(6,0);a.call(A(0x124C38))
    a.addiu(8,0,1);a.sw(8,16,4)
    a.label('poll')
    if config['side']<2:a.call(A(0x124E60));a.branch(4,2,0,'done')
    # The consumed partner did not tick its voice cooldown while fused.
    for actor in config['actors']:
        a.li(8,actor)
        for off in range(5204,5204+37*4,4):a.sw(0,8,off)
    a.addiu(8,0,5);a.sw(8,16,4);a.jump('done')
    a.label('error');a.addiu(8,0,110);a.sw(8,16,4)
    a.label('done');a.lw(2,16,4)
    for i,r in enumerate((16,17,18,19,31)):a.i(55,r,29,8*i)
    a.addiu(29,29,0x40);a.jr();return a.finish()


def build_memory(ram,snap):
    u=lambda p:body.u(ram,p)
    ptr=lambda p,n=4:0x100000<=p<=len(ram)-n and p%4==0
    body.require(not any(ram[ENTRY:END]),'Defusion audio workspace occupied')
    loader,audio,options=map(u,(LOADER_GLOBAL,AUDIO_GLOBAL,OPTIONS_GLOBAL))
    body.require(ptr(loader,88) and ptr(audio,608) and ptr(options,5644),'Native audio managers changed')
    buffer,capacity=u(loader+44),u(loader+84)
    body.require(capacity==591872 and ptr(buffer,capacity),'Native sound scratch capacity changed')
    body.require(all(u(audio+76*i+48)==0 for i in range(8)),'A native sound upload is already running')
    side=snap['side'];record=audio+76*(4+side)
    body.require(side>=2 or (u(record)>0 and u(record+36)==585728 and u(record+40)==4096 and u(record+44)==2048),
                 'Native leader voice bank allocations changed')
    body.require((u(timer.native.CONTROL+16),u(timer.native.CONTROL+20))==(1,1),'Defusion audio needs the native hold')
    # Extras stream their own voice from the restored model; no native bank
    # belongs to them. Never shift a leader SPU-bank mask by a physical ID.
    data=bank_file(struct.unpack_from('<I',bytes.fromhex(snap['rows'][0]['data_hex']))[0],bool(u(options+5640)&1)) if side<2 else b''
    body.require(len(data)<=capacity,'Short-voice bank exceeds sound scratch')
    guards=[(LOADER_GLOBAL,loader),(AUDIO_GLOBAL,audio),(loader+44,buffer),(loader+84,capacity),
            (timer.core.ACTORS,snap['world']['manager']),(snap['record'],3),(snap['record']+72,snap['generation']),
            (timer.native.CONTROL+16,1),(timer.native.CONTROL+20,1)]
    for p,n in ((A(0x124C38),0x188),(A(0x124E60),0x50),(A(0x265AD0),0x48)):
        body.require(bytes(ram[p:p+n])==body.NATIVE(p,n),f'Native audio helper changed:{p:08X}')
    loop_base=u(snap['world']['manager']+12)
    body.require(ptr(loop_base,52*snap['world']['count']),'Native loop sound records changed')
    guards.append((snap['world']['manager']+12,loop_base))
    config=dict(loop_rows=[loop_base+52*pid for pid in (side,snap['partner']['physical'])],guards=guards,side=side,buffer=buffer,actors=[r['actor'] for r in snap['rows']],
                physical_ids=[side,snap['partner']['physical']])
    control=bytearray(64);struct.pack_into('<I',control,8,snap['world']['manager'])
    # Upload bytes are intentionally not owned scratch: the native loader owns
    # this allocation and may reuse it after the sound transfer completes.
    upload=resources.parts_manifest(ram,[(buffer,data)] if data else [])
    job=resources.parts_manifest(ram,[(ENTRY,code(config)),(CONTROL,bytes(control))],entry=ENTRY,control=CONTROL,configuration=config)
    return upload,job
