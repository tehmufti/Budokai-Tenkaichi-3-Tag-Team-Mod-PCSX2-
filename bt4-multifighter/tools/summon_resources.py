"""Two overflow resource records exclusively for native cinematic summons.

The twelve ordinary records can all be retained by ten fighters and their
replacement costumes. Only 127680's mesh-only loader may borrow these records;
forms, costumes and leader buffers keep their existing allocation rules. Native
disc loading, binding and freeing still own the buffers. The overflow handles
are recognized by lookup/release and drained by the native pool destructor.
"""
from native_map import A
import struct
from prototype import Assembler

LOAD, LOOKUP, RELEASE, TEARDOWN = 0x072A4000, 0x072A4800, 0x072A5000, 0x072A5800
RECORDS, OWNER = 0x072AE000, 0x072AE070
COUNT, FIRST_HANDLE = 2, 14
HOOKS = ((A(0x127710), LOAD), (A(0x24B910), LOOKUP), (A(0x24B8A0), RELEASE), (A(0x24B6E8), TEARDOWN))


def owner_gate(a, fallback):
    # Cleanup must still work once fresh mode is disabled, but never operate on
    # records from a different pool/match. Do not mistake a new scene for owner.
    import model_slot_guards as g
    a.li(2,g.CONTROL);a.lw(3,2);a.li(2,g.MAGIC);a.branch(5,2,3,fallback)
    a.li(2,OWNER);a.lw(2,2);a.branch(4,2,0,fallback)
    a.li(3,g.POOL_GLOBAL);a.lw(3,3);a.branch(5,2,3,fallback)


def load_code():
    import model_slot_guards as g
    a=Assembler(LOAD);saved=(16,17,18,19,20,31)
    a.addiu(29,29,-48)
    for i,r in enumerate(saved):a.i(63,r,29,i*8)
    a.move(17,5);a.move(18,6);a.move(19,7)
    a.call(A(0x24B7A8));a.move(16,2)
    a.r(0x2A,3,16,0);a.branch(4,3,0,'done')
    g.active(a,'done')
    # The native summon supplies mesh only; refuse any other caller/shape.
    a.addiu(2,0,-1);a.branch(5,18,2,'done');a.branch(5,19,2,'done')
    a.li(2,g.POOL_GLOBAL);a.lw(2,2);a.branch(4,2,0,'done')
    a.li(3,OWNER);a.lw(4,3);a.branch(4,4,0,'own');a.branch(5,4,2,'done')
    a.label('own');a.sw(2,3)
    for i in range(COUNT):
        a.li(20,RECORDS+i*56);a.lw(2,20,48);a.branch(5,2,0,f'next{i}')
        for off in (0,16,32):a.lw(2,20,off);a.branch(5,2,0,f'next{i}')
        a.addiu(2,0,FIRST_HANDLE+i);a.sw(2,20,52)
        a.addiu(2,0,1);a.sw(2,20,48);a.jump('load')
        a.label(f'next{i}')
    a.jump('done')
    a.label('load');a.move(4,20);a.move(5,17);a.move(6,18);a.move(7,19)
    a.call(A(0x24B3B0))
    for off in (0,16,32):a.addiu(4,20,off);a.addiu(5,0,1);a.call(A(0x24B450))
    a.addiu(2,0,3);a.sw(2,20,48);a.lw(16,20,52)
    a.label('done');a.move(2,16)
    for i,r in enumerate(saved):a.i(55,r,29,i*8)
    a.addiu(29,29,48);a.jr();data=a.finish();assert len(data)<0x800;return data


def find_record(a, fallback):
    # a0 handle -> v0 descriptor. a0 and all callee-saved registers unchanged.
    owner_gate(a,fallback)
    for i in range(COUNT):
        a.addiu(2,0,FIRST_HANDLE+i);a.branch(5,4,2,f'next{i}')
        a.li(2,RECORDS+i*56);a.lw(3,2,48);a.i(12,3,3,1)
        a.branch(4,3,0,fallback);a.lw(3,2,52);a.branch(5,3,4,fallback);a.jump('found')
        a.label(f'next{i}')
    a.jump(fallback)


def lookup_code():
    import model_slot_guards as g
    a=Assembler(LOOKUP);find_record(a,'native');a.label('found');a.jr()
    a.label('native')
    for w in struct.unpack('<2I',g.NATIVE(A(0x24B910),8)):a.emit(w)
    a.jump(A(0x24B918));return a.finish()


def release_code():
    import model_slot_guards as g
    a=Assembler(RELEASE);find_record(a,'native');a.label('found')
    a.addiu(29,29,-16);a.i(63,16,29,0);a.i(63,31,29,8);a.move(16,2)
    for off in (0,16,32):a.addiu(4,16,off);a.call(A(0x24B400))
    a.sw(0,16,48);a.i(55,16,29,0);a.i(55,31,29,8);a.addiu(29,29,16);a.jr()
    a.label('native')
    for w in struct.unpack('<2I',g.NATIVE(A(0x24B8A0),8)):a.emit(w)
    a.jump(A(0x24B8A8));return a.finish()


def teardown_code():
    import model_slot_guards as g
    a=Assembler(TEARDOWN);owner_gate(a,'native')
    a.addiu(29,29,-16);a.i(63,31,29,0)
    for i in range(COUNT):a.addiu(4,0,FIRST_HANDLE+i);a.call(RELEASE)
    a.li(2,OWNER);a.sw(0,2);a.i(55,31,29,0);a.addiu(29,29,16)
    a.label('native')
    for w in struct.unpack('<2I',g.NATIVE(A(0x24B6E8),8)):a.emit(w)
    a.jump(A(0x24B6F0));return a.finish()


def hook_bytes(entry,base):
    # Preserve the caller's a3=-1 delay slot at the loader callsite.
    return struct.pack('<2I',((3 if entry==A(0x127710) else 2)<<26)|(base>>2),
                       0x2407FFFF if entry==A(0x127710) else 0)


def pieces():
    return [(LOAD,load_code()),(LOOKUP,lookup_code()),(RELEASE,release_code()),(TEARDOWN,teardown_code())]+[
        (p,hook_bytes(p,b))for p,b in HOOKS]


def native_or_hook(ram,entry,size,native):
    """Other validated services may encounter our exact release entry hook."""
    expected=native(entry,size)
    if ram[entry:entry+size]==expected:return True
    base=dict(HOOKS).get(entry)
    return base is not None and ram[entry:entry+size]==hook_bytes(entry,base)+expected[8:]
