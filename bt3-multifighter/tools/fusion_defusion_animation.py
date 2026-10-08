"""Play native power-down poses under the acknowledged defusion hold.

Only skeletal animation advances. Native transformation actions and their
reload/effect events are deliberately not dispatched by this presentation.
The two phases are the same 375 -> 377 clips used by native action 238.
"""
from native_map import A
import struct
import math
from prototype import Assembler
import fusion_duration as timer
import body_swap_runner as runner
import body_swap_commit as commit
import body_swap_resources as resources
import giant_options

ENTRY,CONTROL,END=runner.RETIRE,runner.RETIRE_CONTROL,runner.END
ANCHOR=ENTRY+0x2000


def code(config):
    a=Assembler(ENTRY);a.addiu(29,29,-0x30)
    for i,r in enumerate((16,17,18,19,31)):a.i(63,r,29,8*i)
    a.li(16,CONTROL);a.lw(8,16);a.branch(4,8,0,'done')
    a.lw(8,16,4);a.addiu(9,0,5);a.branch(4,8,9,'done')
    for at,value in config['guards']:
        a.li(8,at);a.lw(8,8);a.li(9,value);a.branch(5,8,9,'error')
    a.li(17,config['actor']);a.li(18,config['model'])
    a.lw(8,16,4);a.branch(5,8,0,'advance')
    a.move(4,17);a.li(5,375);a.emit((17<<26)|(4<<21)|(12<<11));a.call(A(0x1C3E60))
    a.addiu(8,0,1);a.sw(8,16,4)
    a.label('advance');a.move(4,17);a.move(5,0);a.call(A(0x1C47A8));a.move(19,2)
    a.move(4,18);a.call(A(0x24C958));a.move(4,18);a.call(A(0x24E3F8));a.call(ANCHOR)
    a.lw(8,16,16);a.addiu(8,8,1);a.sw(8,16,16)
    a.branch(5,19,0,'phase');a.i(11,9,8,24);a.branch(5,9,0,'done')
    a.label('phase');a.lw(8,16,4);a.addiu(9,0,2);a.branch(4,8,9,'complete')
    a.move(4,17);a.li(5,377);a.emit((17<<26)|(4<<21)|(12<<11));a.call(A(0x1C3E60))
    a.addiu(8,0,2);a.sw(8,16,4);a.sw(0,16,16);a.jump('done')
    a.label('complete');a.addiu(8,0,5);a.sw(8,16,4);a.jump('done')
    a.label('error');a.li(8,110);a.sw(8,16,4)
    a.label('done')
    for i,r in enumerate((16,17,18,19,31)):a.i(55,r,29,8*i)
    a.addiu(29,29,0x30);a.jr();return a.finish()


def build_memory(ram,snap):
    u=commit.u
    require=commit.require;actor=snap['source']['actor'];model=snap['source']['model']
    require(not any(ram[ENTRY:END]),'Defusion presentation workspace occupied')
    guards=[(snap['record'],3),(snap['record']+72,snap['generation']),
            (timer.core.ACTORS,snap['world']['manager']),
            (actor+12,snap['source']['model_id']),(model+12,snap['source']['character']),
            (timer.native.CONTROL+16,1),(timer.native.CONTROL+20,1)]
    require(all(u(ram,p)==v for p,v in guards),'Defusion animation ownership changed')
    # Mods may omit these standard clips. Keep their ordinary defusion safe
    # instead of passing a missing/combat-special clip into the pose decoder.
    flags=u(ram,snap['world']['manager']+32)
    for clip in (375,377):
        packed=u(ram,model+192+4*clip)
        if not commit.ptr(ram,packed,8) or not commit.ptr(ram,flags+4*clip):return None
        if u(ram,flags+4*clip)&0x20000000:return None
        size=u(ram,packed+4)
        if not 0<size<0xC000 or not commit.ptr(ram,packed,8+size):return None
    for p,n in ((A(0x1C3E60),0xF8),(A(0x1C47A8),0xE0),(A(0x24C958),0x10),
                (A(0x24E2B0),0x148),(A(0x24E3F8),0xB0),(A(0x1D70E8),0xB0)):
        require(bytes(ram[p:p+n])==giant_options.native_helper(ram,p,n,timer.body.NATIVE),
                f'Defusion animation helper changed:{p:08X}')
    root=tuple(u(ram,model+2416+4*i)for i in range(4))
    require(all(math.isfinite(v)for v in struct.unpack('<4f',struct.pack('<4I',*root))),
            'Defusion animation position is invalid')
    config=dict(actor=actor,model=model,guards=guards)
    control=bytearray(32);struct.pack_into('<I',control,8,snap['world']['manager'])
    return resources.parts_manifest(ram,[(ENTRY,code(config)),(CONTROL,bytes(control)),
        (ANCHOR,commit.anchor_code(ANCHOR,actor,model,root))],entry=ENTRY,control=CONTROL,
        defusion_animation=True,configuration=config)
