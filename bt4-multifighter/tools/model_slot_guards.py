"""Keep an exhausted model table from turning into wild writes.

The engine has twelve model slots and every fighter holds one. At ten fighters
two remain for everything else a move can create on the fly: the temporary
model a summoning special brings in (Hercule's Buu, Goten in Gohan's ultimate)
and the type1 cosmetic models of other effects. Native code already fails
cleanly at the allocator - 2498A0 returns -1 when the free list at
pool+69120 is empty - but two consumers do not check that result:

* 1D6290 queues the summon loader 127680, which later asks 2499B0 for the
  failed model ID and dereferences whatever that returns.
* Five 1A8C40 callers (15445C, 156478, 159328, 15AD18, 169BA8) pass its -1
  straight to the cosmetic helpers, which write model fields through 2499B0.

While the fresh multi-fighter match is active, 1D6290 takes its own existing
failure result (0) when no model slot is free, so the special simply goes
without its summoned model, and the seven cosmetic helpers skip any ID that is
not a registered type1 model. A request only sees the slots free at the time:
the loader (127680, spawned by 128318) allocates frames
later, after its disc load, and a cosmetic model or the other leader's summon
can take the slots meanwhile. Its 249AB8 result then goes unchecked through
20B3C0 into 1D3540, which binds the ID at leader+0x1330; every frame after,
1D35B0 would work through 2499B0(-1). So 20B3C0 - the loader's only bind call
and the only caller of 1D3540 - now refuses a failed ID: it releases the loaded
file exactly as the summon's own cleanup 1D3568 does (24B8A0) and leaves the
leader unbound, so the loader ends normally and the special goes without its
summoned model whatever order the allocators ran in. Nothing is evicted, and
outside a fresh match - or with a free slot, or a valid cosmetic model - the
native code runs as is.
Only v0/v1 are touched; v1 is restored, and every argument (a0..a3, t0) is
left exactly as the caller passed it.

The kind-1 auxiliary loader now visits every captured physical actor, using
the existing serialized queue and native bind/cleanup protocol. The ordinary
form/costume loader stays unchanged. SUMMON_PENDING allows the readiness and
form guards to defer to the native handshake only for a real pending summon.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path

from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
import fresh_team_combat as core

CODE, PREDICATE, WRAPPERS, CONTROL, END = 0x072A0000, 0x072A0400, 0x072A0800, 0x072AF000, 0x072B0000
BIND_GUARD = 0x072A1000
SUMMON_LIMIT, SUMMON_PENDING = 0x072A1800, 0x072A2000
SUMMON_LOOP = A(0x1283C8)
RESOURCE_GUARDS = ((A(0x127800),0x072A2800),(A(0x127840),0x072A2C00))
MAGIC = 0x4D534C31  # 'MSL1'
FIELDS = dict(magic=0, manager=4, requests=8, skipped=12, refused_binds=16, refused_resources=20)
# 20B3C0(a0 leader, a1 loaded file handle, a2 model ID): the summon bind.
BIND, RELEASE_FILE = A(0x20B3C0), A(0x24B8A0)
REQUEST = A(0x1D6290)
REQUEST_ORIGINAL = bytes.fromhex('d0ffbd270000b0ff')  # addiu sp,-0x30 ; sd s0,0(sp)
HELPERS = (A(0x1A8CA0), A(0x1A8CB8), A(0x1A8CE8), A(0x1A8D08), A(0x1A8D48), A(0x1A8DA0), A(0x1A8DD0))
MODELS, POOL_GLOBAL, FREE_LIST = A(0x31C640), A(0x2FEC44), 69120
MANAGER_GP = -22364  # 0x2FEB14 through $gp
NATIVE = elf_reader(elf_path(ROOT))[2]
assert CODE < PREDICATE < WRAPPERS < WRAPPERS + len(HELPERS)*0x100 <= BIND_GUARD
assert BIND_GUARD + 0x100 <= CONTROL < END


def active(a, native):
    """Branch to native unless this match's fresh mode is live. v0/v1 only."""
    a.li(2, CONTROL); a.lw(3, 2, FIELDS['magic']); a.li(2, MAGIC); a.branch(5, 3, 2, native)
    a.li(2, CONTROL); a.lw(3, 2, FIELDS['manager']); a.lw(2, 28, MANAGER_GP); a.branch(5, 3, 2, native)
    a.li(2, core.MODE); a.lw(2, 2); a.addiu(3, 0, 1); a.branch(5, 2, 3, native)


def request_code():
    """1D6290 front door: its own 0 result when the model free list is empty."""
    a = Assembler(CODE)
    a.addiu(29, 29, -0x10); a.i(63, 3, 29, 0)
    active(a, 'native')
    a.li(2, POOL_GLOBAL); a.lw(2, 2); a.branch(4, 2, 0, 'native')
    a.li(3, FREE_LIST); a.r(0x21, 2, 2, 3); a.lw(2, 2); a.branch(4, 2, 0, 'refuse')
    a.li(2,POOL_GLOBAL);a.lw(2,2);a.li(3,439156);a.r(0x21,2,2,3)
    a.lw(2,2);a.i(12,2,2,0x7FFF);a.li(3,0x7FFF);a.branch(5,2,3,'native')
    a.label('refuse')
    a.li(2, CONTROL); a.lw(3, 2, FIELDS['requests']); a.addiu(3, 3, 1); a.sw(3, 2, FIELDS['requests'])
    a.i(55, 3, 29, 0); a.addiu(29, 29, 0x10); a.move(2, 0); a.jr()
    a.label('native'); a.i(55, 3, 29, 0); a.addiu(29, 29, 0x10)
    for word in struct.unpack('<2I', REQUEST_ORIGINAL): a.emit(word)
    a.jump(REQUEST + 8)
    code = a.finish(); assert CODE + len(code) <= PREDICATE; return code


def predicate_code():
    """v0 = 1 to skip a helper for a0 that is not a registered type1 model."""
    a = Assembler(PREDICATE)
    active(a, 'native')
    a.i(11, 2, 4, 12); a.branch(4, 2, 0, 'skip')
    a.li(2, MODELS); a.r(0, 3, 0, 4, 2); a.r(0x21, 2, 2, 3); a.lw(2, 2)
    a.branch(4, 2, 0, 'skip'); a.lw(3, 2, 16); a.branch(5, 3, 4, 'skip')
    a.lw(2, 2); a.addiu(3, 0, 1); a.branch(5, 2, 3, 'skip')
    a.label('native'); a.move(2, 0); a.jr()
    a.label('skip'); a.addiu(2, 0, 1); a.jr()
    code = a.finish(); assert PREDICATE + len(code) <= WRAPPERS; return code


def helper_code(index):
    entry = HELPERS[index]; original = NATIVE(entry, 8)
    a = Assembler(WRAPPERS + index*0x100)
    a.addiu(29, 29, -0x10); a.i(63, 31, 29, 0); a.i(63, 3, 29, 8); a.call(PREDICATE)
    a.i(55, 31, 29, 0); a.branch(4, 2, 0, 'native')
    a.li(2, CONTROL); a.lw(3, 2, FIELDS['skipped']); a.addiu(3, 3, 1); a.sw(3, 2, FIELDS['skipped'])
    a.i(55, 3, 29, 8); a.addiu(29, 29, 0x10); a.move(2, 0); a.jr()
    a.label('native'); a.i(55, 3, 29, 8); a.addiu(29, 29, 0x10)
    for word in struct.unpack('<2I', original):
        assert word >> 26 not in range(1, 8), f'Helper {entry:X} prologue is not position independent'
        a.emit(word)
    a.jump(entry + 8)
    code = a.finish(); assert len(code) <= 0x100; return code


def bind_code():
    """20B3C0: a failed model ID releases its loaded file instead of binding."""
    original = NATIVE(BIND, 8)
    a = Assembler(BIND_GUARD)
    active(a, 'native')
    a.r(0x2A, 2, 6, 0); a.branch(4, 2, 0, 'native')          # slt v0,a2,zero
    a.addiu(29, 29, -0x10); a.i(63, 31, 29, 0)
    a.move(4, 5); a.call(RELEASE_FILE)
    a.li(2, CONTROL); a.lw(3, 2, FIELDS['refused_binds']); a.addiu(3, 3, 1); a.sw(3, 2, FIELDS['refused_binds'])
    a.i(55, 31, 29, 0); a.addiu(29, 29, 0x10); a.jr()
    a.label('native')
    for word in struct.unpack('<2I', original):
        assert word >> 26 not in range(1, 8), 'Bind prologue is not position independent'
        a.emit(word)
    a.jump(BIND + 8)
    code = a.finish(); assert len(code) <= 0x100; return code


def summon_limit_code():
    """Widen only the native auxiliary loader, never the form/costume loader.

    Replays addiu s1,1 / slti v0,s1,2 at the end of 128318. Its existing
    kind-1 queue predicate and serialized IO/ACK protocol remain native.
    """
    a=Assembler(SUMMON_LIMIT);core.save_temporaries(a)
    a.addiu(17,17,1);core.gate(a,'native')
    a.r(0x2A,2,17,10);a.jump('done')
    a.label('native');a.i(10,2,17,2)
    a.label('done');core.restore_temporaries(a);a.jump(SUMMON_LOOP+8)
    code=a.finish();assert SUMMON_LIMIT+len(code)<=SUMMON_PENDING;return code


def summon_pending_code():
    """a0 physical -> v0 whether its native kind-1 summon is queued/active.

    Inspect only the eight-record ring and its exact active member. Stale
    records outside the unread ring must not hold a later costume request.
    """
    a=Assembler(SUMMON_PENDING);a.addiu(29,29,-0x40)
    for i,r in enumerate((3,8,9,10,11,12,13)):a.i(63,r,29,8*i)
    a.move(2,0);core.gate(a,'done')
    a.lw(11,28,-22364);a.addiu(11,11,0x138)
    a.lw(12,11,0x120);a.branch(4,12,0,'ring')
    # An active pointer must be one of the native ring's eight 36-byte rows.
    a.move(8,11);a.addiu(9,0,8)
    a.label('active_row');a.branch(4,8,12,'active_valid')
    a.addiu(8,8,36);a.addiu(9,9,-1);a.branch(5,9,0,'active_row');a.jump('ring')
    a.label('active_valid');a.lw(8,11,0x12C);a.addiu(9,0,5);a.branch(4,8,9,'ring')
    a.lw(8,12);a.branch(5,8,4,'ring');a.lw(8,12,4);a.addiu(9,0,1);a.branch(4,8,9,'yes')
    a.label('ring');a.lw(12,11,0x128);a.lw(13,11,0x124)
    for r in (12,13):a.i(11,8,r,8);a.branch(4,8,0,'done')
    a.label('next');a.branch(4,12,13,'done')
    a.r(0,8,0,12,3);a.r(0x21,8,8,12);a.r(0,8,0,8,2);a.r(0x21,8,8,11)
    a.lw(9,8);a.branch(5,9,4,'advance');a.lw(9,8,4);a.addiu(10,0,1);a.branch(4,9,10,'yes')
    a.label('advance');a.addiu(12,12,1);a.i(12,12,12,7);a.jump('next')
    a.label('yes');a.addiu(2,0,1)
    a.label('done')
    for i,r in enumerate((3,8,9,10,11,12,13)):a.i(55,r,29,8*i)
    a.addiu(29,29,0x40);a.jr()
    code=a.finish();assert len(code)<0x800;return code


def resource_code(entry,base):
    """Validate the native summon resource before allocating any model.

    24B7A8 returns -1 when its twelve resource rows are occupied. Native
    127680 used that as a handle, then constructed a model from a null bundle,
    trapping 114860 in its geometry-chain loop (live BT4 10-fighter FFA).
    Guard again at consumption, since capacity can change after admission.
    """
    a=Assembler(base)
    a.addiu(29,29,-0x20);a.i(63,31,29,0);a.i(63,16,29,8)
    active(a,'native')
    a.lw(4,28,-0x58D8);a.r(0x2A,2,4,0);a.branch(5,2,0,'refuse')
    a.call(A(0x24B910));a.move(16,2)
    def pointer(reg,size):
        a.li(3,0x100000);a.r(0x2B,3,reg,3);a.branch(5,3,0,'refuse')
        a.li(3,0x8000000-size);a.r(0x2B,3,3,reg);a.branch(5,3,0,'refuse')
        a.i(12,3,reg,3);a.branch(5,3,0,'refuse')
    pointer(16,56)
    a.lw(2,16,48);a.i(12,2,2,1);a.branch(4,2,0,'refuse')
    a.lw(2,16,52);a.lw(3,28,-0x58D8);a.branch(5,2,3,'refuse')
    a.lw(2,16);pointer(2,20)
    # Entry 3 is the geometry. Check both offsets against the recorded file
    # size before the native PAK accessor can read or follow its mesh chain.
    a.lw(4,16,4);a.li(3,0x8000000);a.r(0x23,3,3,2)
    a.r(0x2B,3,3,4);a.branch(5,3,0,'refuse')
    a.i(11,3,4,20);a.branch(5,3,0,'refuse')
    a.lw(5,2,12);a.lw(6,2,16)
    a.r(2,5,0,5,2);a.r(0,5,0,5,2)
    a.r(2,6,0,6,2);a.r(0,6,0,6,2)
    a.r(0x2B,3,4,6);a.branch(5,3,0,'refuse')
    a.r(0x2B,3,6,5);a.branch(5,3,0,'refuse')
    a.r(0x23,3,6,5);a.i(11,3,3,112);a.branch(5,3,0,'refuse')
    # Cosmetics can take the last group while this file is reading. Refuse
    # before the constructor, whose texture allocator also returns -1 on full.
    a.li(2,POOL_GLOBAL);a.lw(2,2);a.li(3,439156);a.r(0x21,2,2,3)
    a.lw(2,2);a.i(12,2,2,0x7FFF);a.li(3,0x7FFF);a.branch(4,2,3,'refuse')
    a.move(2,16);a.jump('return')
    a.label('native');a.lw(4,28,-0x58D8);a.call(A(0x24B910))
    a.label('return');a.i(55,31,29,0);a.i(55,16,29,8)
    a.addiu(29,29,0x20);a.jump(entry+8)
    a.label('refuse');a.li(2,CONTROL);a.lw(3,2,FIELDS['refused_resources'])
    a.addiu(3,3,1);a.sw(3,2,FIELDS['refused_resources'])
    if entry==A(0x127800):
        # Intro-only branch has no bind guard. Release its handle and take
        # the same native task/scene cleanup without dereferencing model -1.
        a.lw(4,28,-0x58D8);a.call(RELEASE_FILE)
    a.i(55,31,29,0);a.i(55,16,29,8);a.addiu(29,29,0x20)
    a.addiu(2,0,-1)
    if entry==A(0x127800):
        a.sw(2,28,-0x58D4);a.jump(A(0x12786C))
    else:
        # Existing 20B3C0 failure handling releases the handle, then the
        # native task finishes and releases its scene hold/queue normally.
        a.jump(A(0x127858))
    data=a.finish();assert len(data)<0x400;return data


def pieces():
    import summon_resources
    parts = [(CODE, request_code()), (PREDICATE, predicate_code())]
    parts += [(WRAPPERS + i*0x100, helper_code(i)) for i in range(len(HELPERS))]
    parts += [(BIND_GUARD, bind_code()), (BIND, struct.pack('<2I', (2 << 26) | (BIND_GUARD >> 2), 0))]
    parts += [(SUMMON_LIMIT,summon_limit_code()),(SUMMON_PENDING,summon_pending_code()),
              (SUMMON_LOOP,struct.pack('<2I',(2<<26)|(SUMMON_LIMIT>>2),0))]
    parts.append((REQUEST, struct.pack('<2I', (2 << 26) | (CODE >> 2), 0)))
    parts += [(entry, struct.pack('<2I', (2 << 26) | ((WRAPPERS + i*0x100) >> 2), 0))
              for i, entry in enumerate(HELPERS)]
    for entry,base in RESOURCE_GUARDS:
        parts += [(base,resource_code(entry,base)),(entry,struct.pack('<2I',(2<<26)|(base>>2),0))]
    return parts+summon_resources.pieces()


def build_memory(ram, source='<offline-memory>'):
    if len(ram) != 0x8000000: raise ValueError('Requires128MiB EE RAM')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager = u(A(0x2FEB14))
    if not 0x100000 <= manager < len(ram)-0x1000 or u(manager) != 2:
        raise ValueError('Requires the native actor manager')
    if u(core.MODE) != 1 or u(core.MODE+8) != manager:
        raise ValueError('Requires an active fresh multi-fighter match')
    for entry in (REQUEST, BIND) + HELPERS:
        if ram[entry:entry+8] != NATIVE(entry, 8): raise ValueError(f'Native model routine {entry:X} changed')
    for entry,_ in RESOURCE_GUARDS:
        if ram[entry:entry+8]!=NATIVE(entry,8):raise ValueError(f'Native summon resource loader changed:{entry:X}')
    import summon_resources
    for entry,_ in summon_resources.HOOKS:
        if ram[entry:entry+8]!=NATIVE(entry,8):raise ValueError(f'Native summon resource helper changed:{entry:X}')
    if ram[SUMMON_LOOP:SUMMON_LOOP+8]!=NATIVE(SUMMON_LOOP,8):raise ValueError('Native summon loader loop changed')
    if ram[A(0x2498A0):A(0x249918)] != NATIVE(A(0x2498A0), 0x78):
        raise ValueError('Native model allocator changed')
    if any(ram[CODE:END]): raise ValueError('Model slot guard reservation occupied')
    control = struct.pack('<6I', MAGIC, manager, 0, 0, 0, 0)
    blocks = [dict(address=p, expected_hex=ram[p:p+len(d)].hex(), data_hex=d.hex())
              for p, d in [(CONTROL, control)] + pieces()]
    return dict(serial=SERIAL, crc=CRC, source=str(source), control=CONTROL,
                status='MODEL SLOT EXHAUSTION GUARDS', blocks=blocks,
                telemetry={'refused_requests': CONTROL+FIELDS['requests'],
                           'skipped_cosmetic_calls': CONTROL+FIELDS['skipped'],
                           'refused_summon_binds': CONTROL+FIELDS['refused_binds'],
                           'refused_summon_resources': CONTROL+FIELDS['refused_resources']})


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path); p.add_argument('--out', required=True, type=Path)
    x = p.parse_args()
    x.out.write_text(json.dumps(build_memory(read_ram(x.source), x.source), indent=2)+'\n'); print(x.out)
