"""Build a state-scoped, guarded BT3 third-model experiment; never writes PINE.

The output manifest is an executable MIPS payload, NOT a completed team-battle
mod. A separately allocated actor clone supplies the new model's transform.
The normal actor scheduler still has two entries. Restore the baseline state
after the experiment, including on success; resource destruction is not patched.
"""
from __future__ import annotations
from native_map import A, CRC, GPO, GP_RELATIVE_OPS, SERIAL, elf_path

import argparse
import hashlib
import json
import math
import struct
from pathlib import Path
from functools import lru_cache

ROOT = Path(__file__).resolve().parents[1]
ACTOR_SIZE = 0x1600
MODEL_SIZE = 0x1670
EXT_SIZE = 0x1A0C0
HOOK = A(0x1C2A28)
EXT_HOOK = A(0x2499C8)


class Assembler:
    def __init__(self, base):
        self.base, self.words, self.labels, self.fixups = base, [], {}, []

    @property
    def pc(self):
        return self.base + len(self.words) * 4

    def emit(self, word):
        self.words.append(word & 0xFFFFFFFF)

    def label(self, name):
        assert name not in self.labels
        self.labels[name] = self.pc

    def i(self, op, rt, rs, imm):
        assert -32768 <= imm <= 65535
        if rs == 28 and op in GP_RELATIVE_OPS:
            imm = GPO(imm)            # the European $gp reaches the same variable at another offset
        self.emit((op << 26) | (rs << 21) | (rt << 16) | (imm & 65535))

    def r(self, fn, rd, rs, rt=0, shift=0):
        self.emit((rs << 21) | (rt << 16) | (rd << 11) | (shift << 6) | fn)

    def move(self, rd, rs):
        self.r(0x2D, rd, rs)

    def li(self, rt, value):
        value &= 0xFFFFFFFF
        self.i(15, rt, 0, value >> 16)
        self.i(13, rt, rt, value & 65535)

    def lw(self, rt, rs, offset=0):
        self.i(35, rt, rs, offset)

    def sw(self, rt, rs, offset=0):
        self.i(43, rt, rs, offset)

    def addiu(self, rt, rs, value):
        self.i(9, rt, rs, value)

    def branch(self, op, rs, rt, label):
        self.fixups.append((len(self.words), label, 'branch'))
        self.emit((op << 26) | (rs << 21) | (rt << 16))
        self.emit(0)

    def jump(self, destination, link=False):
        if isinstance(destination, str):
            self.fixups.append((len(self.words), destination, 'jump'))
            self.emit((3 if link else 2) << 26)
        else:
            assert ((self.pc + 4) ^ destination) & 0xF0000000 == 0
            self.emit(((3 if link else 2) << 26) | (destination >> 2))
        self.emit(0)

    def call(self, address):
        self.jump(address, True)

    def jr(self, reg=31):
        self.r(8, 0, reg)
        self.emit(0)

    def finish(self):
        for index, label, kind in self.fixups:
            target = self.labels[label]
            if kind == 'branch':
                delta = (target - (self.base + index * 4 + 4)) // 4
                assert -32768 <= delta < 32768
                self.words[index] |= delta & 65535
            else:
                self.words[index] |= target >> 2
        return struct.pack('<' + 'I' * len(self.words), *self.words)


def elf_reader(path):
    path = Path(path).resolve()
    stamp = path.stat()
    blob, segments, read = _elf_reader_cached(path, stamp.st_mtime_ns, stamp.st_ctime_ns, stamp.st_size)
    # Callers historically received a mutable list; keep their mutations local.
    return blob, list(segments), read


@lru_cache(maxsize=4)
def _elf_reader_cached(path, modified_ns, changed_ns, length):
    """Cache immutable native code, invalidated when the executable changes."""
    blob = path.read_bytes()
    assert blob[:7] == b'\x7fELF\x01\x01\x01'
    phoff = struct.unpack_from('<I', blob, 28)[0]
    size, count = struct.unpack_from('<HH', blob, 42)
    segments = []
    for n in range(count):
        kind, offset, va, _, filesz, memsz, _, _ = struct.unpack_from('<8I', blob, phoff + n * size)
        if kind == 1:
            segments.append((va, offset, filesz, memsz))
    segments = tuple(segments)

    def read(address, length):
        for va, offset, filesz, _ in segments:
            if va <= address and address + length <= va + filesz:
                return blob[offset + address - va:offset + address - va + length]
        raise ValueError(f'ELF address not file backed: {address:08X}')

    return blob, segments, read


def build(ram_path, elf_path, output, cave=0xB0000, x_offset=50.0):
    ram = ram_path.read_bytes()
    assert len(ram) == 0x2000000, 'Expected one 32 MiB EE RAM dump'
    elf, segments, readelf = elf_reader(elf_path)
    state = cave + 0x3000
    redirect = cave + 0x2000
    assert cave % 16 == 0 and 0x30000 <= cave and cave + 0x4000 <= 0xFF000
    assert not any(ram[cave:cave + 0x4000]), 'Experimental cave is not zero in this state'
    assert not any(va < cave + 0x4000 and cave < va + memsz for va, _, _, memsz in segments)
    for address in (HOOK, EXT_HOOK):
        assert ram[address:address + 8] == readelf(address, 8), f'Changed hook at {address:08X}'
        assert struct.unpack('<2I', readelf(address, 8)) == (0x27BDFFF0, 0xFFB00000)
    u32 = lambda addr: struct.unpack_from('<I', ram, addr)[0]
    assert u32(A(0x31BE04)) == 0, 'Stage-1 creation requires live recording mode, not replay input playback'
    manager = u32(A(0x2FEB14))
    assert 0x100000 < manager < 0x1FFFF00 and u32(manager) == 2
    actors = u32(manager + 4)
    assert u32(actors) == 0 and u32(actors + 12) == 0
    assert u32(A(0x31C640)) and u32(A(0x31C644))
    assert any(not u32(A(0x31C640) + i * 4) for i in range(2, 12)), 'No apparently available model entry'
    source_model = u32(A(0x31C640))
    source_animation = u32(actors + 2420)
    assert source_animation < 414, 'Source uses an unsupported special/shared animation path'
    assert struct.unpack_from('<H', ram, source_model + 2888)[0] == source_animation, 'Actor/model animation mismatch'
    duration = struct.unpack_from('<f', ram, source_model + 2884)[0]
    frames = struct.unpack_from('<2f', ram, source_model + 3192)
    assert math.isfinite(duration) and duration > 0
    assert all(math.isfinite(f) and 0 <= f <= duration + 4 for f in frames), 'Invalid source animation frames'
    collision = u32(u32(A(0x31C640)) + 84)
    collision_size = 16
    while collision_size + 464 <= 0x3800:
        terminal = u32(collision + collision_size) & 1
        collision_size += 464
        if terminal:
            break
    else:
        raise ValueError('Collision descriptor too large for this experimental allocation')

    # s0=state, s1=manager, s2=source actor, s3=source model,
    # s4=allocation, s5=new model id, s6=new model, s7=new actor.
    a = Assembler(cave)
    a.addiu(29, 29, -0x80)
    for n in range(8):
        a.i(63, 16 + n, 29, n * 8)  # sd, as the original EE ABI does
    a.i(63, 31, 29, 0x40)
    a.li(16, state)
    a.lw(8, 16, 0)
    a.branch(5, 8, 0, 'already_ran')
    a.addiu(8, 0, 1)
    a.sw(8, 16, 0)
    a.li(8, A(0x31BE04))
    a.lw(9, 8)
    a.branch(5, 9, 0, 'error_150')
    a.li(8, A(0x2FEB14))
    a.lw(17, 8)
    a.lw(9, 17)
    a.addiu(8, 0, 2)
    a.branch(5, 8, 9, 'error_110')
    a.lw(18, 17, 4)
    a.lw(8, 18, 12)
    a.branch(5, 8, 0, 'error_112')
    a.li(8, A(0x31C640))
    a.lw(19, 8)
    a.lw(8, 18, 2420)
    a.i(11, 9, 8, 414)
    a.branch(4, 9, 0, 'error_140')
    a.i(37, 9, 19, 2888)  # lhu: current model animation id
    a.branch(5, 8, 9, 'error_140')
    a.sw(8, 16, 0x24)
    a.sw(17, 16, 0x10)
    a.sw(18, 16, 0x14)
    a.sw(19, 16, 0x18)
    a.lw(8, 19, 5728)
    a.sw(8, 16, 0x28)
    a.li(4, 0x20000)
    a.addiu(5, 0, 32)
    a.move(6, 0)
    a.addiu(7, 0, 2)
    a.call(A(0x2554D8))
    a.branch(4, 2, 0, 'error_120')
    a.move(20, 2)
    a.sw(20, 16, 4)
    a.move(4, 20)
    a.move(5, 0)
    a.li(6, 0x20000)
    a.call(A(0x2A9ACC))
    a.addiu(8, 0, 2)
    a.sw(8, 16, 0)
    # 24DB28 mutates its descriptor's bone pointers. Back it up before creating
    # a model using the source resource, restore it immediately, then give the
    # new model its own copy and rerun 24DB28 on that copy.
    a.lw(8, 19, 84)
    a.sw(8, 16, 0x30)
    a.li(9, 0x1C800)
    a.r(0x21, 9, 20, 9)
    a.sw(9, 16, 0x2C)
    a.addiu(10, 0, collision_size)
    a.sw(10, 16, 0x34)
    a.label('backup_collision')
    a.lw(11, 8)
    a.sw(11, 9)
    a.addiu(8, 8, 4)
    a.addiu(9, 9, 4)
    a.addiu(10, 10, -4)
    a.branch(5, 10, 0, 'backup_collision')
    a.move(4, 0)
    a.lw(5, 19, 20)
    a.addiu(6, 0, 1)
    a.call(A(0x249AB8))
    a.move(21, 2)
    a.sw(21, 16, 8)
    a.lw(8, 16, 0x2C)
    a.lw(9, 16, 0x30)
    a.addiu(10, 0, collision_size)
    a.label('restore_collision')
    a.lw(11, 8)
    a.sw(11, 9)
    a.addiu(8, 8, 4)
    a.addiu(9, 9, 4)
    a.addiu(10, 10, -4)
    a.branch(5, 10, 0, 'restore_collision')
    a.i(11, 8, 21, 12)
    a.branch(4, 8, 0, 'error_130')
    a.i(11, 8, 21, 2)
    a.branch(5, 8, 0, 'error_130')
    a.move(4, 21)
    a.call(A(0x2499B0))
    a.move(22, 2)
    a.sw(22, 16, 0xC)
    a.lw(8, 16, 0x2C)
    a.sw(8, 22, 84)
    a.move(4, 22)
    a.call(A(0x24DB28))
    a.addiu(8, 0, 3)
    a.sw(8, 16, 0)
    a.li(8, 0x1B000)
    a.r(0x21, 23, 20, 8)
    a.sw(23, 16, 0x1C)
    # Copy, relocating only pointers inside the actor/model/private ext ranges.
    a.move(8, 18)
    a.move(9, 23)
    a.addiu(10, 18, ACTOR_SIZE)
    a.lw(14, 16, 0x28)
    a.label('copy_word')
    a.lw(11, 8)
    for tag, source, target, size in (
        ('actor', 18, 23, ACTOR_SIZE), ('model', 19, 22, MODEL_SIZE), ('ext', 14, 20, EXT_SIZE)
    ):
        a.r(0x23, 12, 11, source)  # subu unsigned offset handles below-base
        if size <= 32767:
            a.i(11, 13, 12, size)  # sltiu
        else:
            a.li(15, size)
            a.r(0x2B, 13, 12, 15)
        a.branch(4, 13, 0, 'not_' + tag)
        a.r(0x21, 11, 12, target)
        a.jump('store_word')
        a.label('not_' + tag)
    a.label('store_word')
    a.sw(11, 9)
    a.addiu(8, 8, 4)
    a.addiu(9, 9, 4)
    a.branch(5, 8, 10, 'copy_word')
    a.sw(21, 23, 12)
    # A cloned fighter must not own and later delete the source's sub-entity.
    for offset in (4912, 4916, 4920):
        a.sw(0, 23, offset)
    # Keep role 0 in this private actor. It is not put into the live actor array.
    a.li(8, struct.unpack('<I', struct.pack('<f', x_offset))[0])
    a.emit((0x11 << 26) | (4 << 21) | (8 << 16) | (1 << 11))  # mtc1 t0,f1
    a.i(49, 0, 23, 16)  # lwc1 f0,16(s7)
    a.emit((0x11 << 26) | (16 << 21) | (1 << 16))  # add.s f0,f0,f1
    a.i(57, 0, 23, 16)  # swc1 f0,16(s7)
    a.move(4, 22)
    a.move(5, 0)
    a.lw(6, 16, 0x24)
    a.addiu(7, 0, 1)
    a.call(A(0x24D038))  # same active animation as the cloned actor, privately decompressed
    # Preserve playback mode, current/previous frame, and frame step. Blend
    # weights are not copied because no secondary animation was initialized.
    for offset in (3188, 3192, 3196, 3200):
        a.lw(8, 19, offset)
        a.sw(8, 22, offset)
    a.move(4, 23)
    a.addiu(5, 0, 1)
    a.call(A(0x1D7198))  # clone transform -> newly allocated model
    a.move(4, 22)
    a.call(A(0x24C958))  # animation -> independent bone transforms
    a.move(4, 22)
    a.call(A(0x24E3F8))  # world bone matrices
    a.addiu(8, 0, 5)
    a.sw(8, 16, 0)
    a.jump('finish')
    a.label('already_ran')
    a.addiu(9, 0, 5)
    a.branch(5, 8, 9, 'finish')
    # Optional animation ticking controlled by state+0x20. No brain is invoked.
    a.lw(8, 16, 0x20)
    a.branch(4, 8, 0, 'finish')
    for function in (A(0x24CC88), A(0x24C958), A(0x24E3F8)):
        a.lw(4, 16, 0xC)
        a.call(function)
    a.jump('finish')
    for code in (110, 111, 112, 120, 130, 140, 150):
        a.label(f'error_{code}')
        a.addiu(8, 0, code)
        a.sw(8, 16, 0)
        a.jump('finish')
    a.label('finish')
    for n in range(8):
        a.i(55, 16 + n, 29, n * 8)
    a.i(55, 31, 29, 0x40)
    a.addiu(29, 29, 0x80)
    for word in struct.unpack('<2I', readelf(HOOK, 8)):
        a.emit(word)
    a.jump(HOOK + 8)
    payload = a.finish()
    assert len(payload) < 0x2000

    r = Assembler(redirect)
    r.i(11, 8, 4, 2)
    r.branch(5, 8, 0, 'original')
    r.li(8, state)
    r.lw(9, 8, 0)
    r.addiu(10, 0, 2)
    r.branch(4, 9, 10, 'private_ext')
    r.lw(9, 8, 8)
    r.branch(5, 4, 9, 'original')
    r.label('private_ext')
    r.lw(2, 8, 4)
    r.branch(4, 2, 0, 'original')
    r.jr()
    r.label('original')
    for word in struct.unpack('<2I', readelf(EXT_HOOK, 8)):
        r.emit(word)
    r.jump(EXT_HOOK + 8)
    redirection = r.finish()

    def block(address, data, purpose):
        return {'address': address, 'expected_hex': ram[address:address + len(data)].hex(),
                'data_hex': data.hex(), 'purpose': purpose}

    blocks = [block(cave, payload, 'One-shot allocator/model/actor-clone routine'),
              block(redirect, redirection, 'New allocated model id receives independent extended storage'),
              block(state, bytes(0x40), 'Status/output mailbox; starts unarmed'),
              block(EXT_HOOK, struct.pack('<2I', (2 << 26) | (redirect >> 2), 0), 'Extended-buffer hook'),
              block(HOOK, struct.pack('<2I', (2 << 26) | (cave >> 2), 0), 'Frame-entry hook; install last')]
    # Retain a human-readable disassembly and verify every generated instruction.
    from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS64, CS_MODE_LITTLE_ENDIAN
    md = Cs(CS_ARCH_MIPS, CS_MODE_MIPS64 | CS_MODE_LITTLE_ENDIAN)
    asm = []
    for addr, data in ((cave, payload), (redirect, redirection)):
        instructions = list(md.disasm(data, addr))
        assert len(instructions) * 4 == len(data), 'Invalid MIPS encoding'
        asm.extend(f'{i.address:08X}: {i.mnemonic} {i.op_str}' for i in instructions)
    manifest = {
        'status': 'EXPERIMENTAL THIRD MODEL + PRIVATE ACTOR CLONE; NOT YET A THIRD NPC',
        'elf_sha256': hashlib.sha256(elf).hexdigest(), 'ram_sha256': hashlib.sha256(ram).hexdigest(),
        'serial': SERIAL, 'crc': CRC, 'cave': cave, 'state': state,
        'state_fields': {'0': 'status: 0 pending, 1 entered, 2 allocated, 3 model-created, 5 ready, 110/111/112/120/130/140/150 error',
                         '4': 'allocation and new-model extended buffer', '8': 'new model id', '12': 'new model ptr',
                         '16': 'manager', '20': 'original actor', '24': 'original model', '28': 'private cloned actor',
                         '32': 'optional animation tick flag (initial 0)', '36': 'source animation id', '40': 'original extended buffer',
                         '44': 'private collision descriptor', '48': 'original collision descriptor', '52': 'collision descriptor size'},
        'requirements': ['Pause game and verify every expected byte before any write.',
                         'Save baseline; write blocks in order and force EE recompiler invalidation before resuming.',
                         'Read mailbox to establish what ran; verify model visibility independently.',
                         'Restore full baseline afterward. Do not return to menus, save progress, or rely on normal teardown.',
                         'The cave is zero/outside ELF in this state, not a proven permanently reserved region.'],
        'blocks': blocks,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2) + '\n')
    output.with_suffix('.asm.txt').write_text('\n'.join(asm) + '\n')
    print(f'{output}: {len(payload)}-byte payload, {len(redirection)}-byte redirect, mailbox {state:08X}')
    return manifest


def build_refresh(ram_path, output):
    """Add actor-to-model transform refresh to an already successful stage 1."""
    ram = ram_path.read_bytes()
    u32 = lambda address: struct.unpack_from('<I', ram, address)[0]
    assert u32(0xB3000) == 5 and not any(ram[0xB1000:0xB1200])
    needle = struct.pack('<I', (3 << 26) | (A(0x24CC88) >> 2))
    offsets = [i for i in range(0xB0000, 0xB1000, 4) if ram[i:i + 4] == needle]
    assert len(offsets) == 1, 'Expected exactly one original optional model tick call'
    a = Assembler(0xB1000)
    a.addiu(29, 29, -16)
    a.i(63, 31, 29, 8)
    a.li(8, 0xB3000)
    a.lw(4, 8, 28)
    a.addiu(5, 0, 1)
    a.call(A(0x1D7198))
    a.li(8, 0xB3000)
    a.lw(4, 8, 12)
    a.call(A(0x24CC88))
    a.i(55, 31, 29, 8)
    a.addiu(29, 29, 16)
    a.jr()
    code = a.finish()
    blocks = []
    for address, data, purpose in (
        (0xB1000, code, 'Refresh private actor transform into its model before the optional pose tick'),
        (offsets[0], struct.pack('<I', (3 << 26) | (0xB1000 >> 2)), 'Optional tick redirects through transform refresh')):
        blocks.append({'address': address, 'expected_hex': ram[address:address + len(data)].hex(),
                       'data_hex': data.hex(), 'purpose': purpose})
    output.write_text(json.dumps({'status': 'Stage-1 transform refresh; enable mailbox+32 separately', 'blocks': blocks}, indent=2) + '\n')
    print(f'{output}: {len(code)}-byte helper, redirects {offsets[0]:08X}')


def build_stage2(ram_path, elf_path, output):
    """Expose the existing clone without moving the two original actor objects.

    Requires ai_shadow's physical-index-2 getter hook. Count remains two in
    the actual manager, and the guarded count getter returns three when enabled.
    This is deliberately a separate experiment after third-model verification.
    """
    ram = ram_path.read_bytes()
    assert len(ram) == 0x2000000
    elf, _, readelf = elf_reader(elf_path)
    u32 = lambda address: struct.unpack_from('<I', ram, address)[0]
    state, code, flag = 0xB3000, 0xB6000, 0xB4818
    assert u32(state) == 5, 'Third-model initialization has not succeeded'
    alloc, manager, actor = u32(state + 4), u32(state + 16), u32(state + 28)
    assert u32(manager) == 2 and u32(actor) == 0
    assert 2 <= u32(actor + 12) < 12
    assert u32(state + 44) + u32(state + 52) <= alloc + 0x1F000
    assert not any(ram[code:code + 0x100]) and u32(flag) == 0
    assert ram[A(0x1DC168):A(0x1DC178)] == readelf(A(0x1DC168), 16)
    a = Assembler(code)
    a.li(8, flag)
    a.lw(8, 8)
    a.branch(4, 8, 0, 'normal')
    a.addiu(2, 0, 3)
    a.jr()
    a.label('normal')
    for word in struct.unpack('<4I', readelf(A(0x1DC168), 16)):
        a.emit(word)
    count_code = a.finish()
    blocks = []

    def block(address, data, purpose):
        blocks.append({'address': address, 'expected_hex': ram[address:address + len(data)].hex(),
                       'data_hex': data.hex(), 'purpose': purpose})

    block(code, count_code, 'Count getter: three only while shared exposure flag is enabled')
    block(A(0x1DC168), struct.pack('<2I', (2 << 26) | (code >> 2), 0), 'Count getter hook')
    for field, destination, backup in ((8, alloc + 0x1F000, state + 56),
                                       (12, alloc + 0x1F100, state + 60)):
        previous = u32(manager + field)
        extra = bytearray(52)
        for offset in (0, 12, 24, 36):
            struct.pack_into('<I', extra, offset, 0xFFFFFFFF)
        data = ram[previous:previous + 104] + extra
        block(destination, data, 'Three 52-byte actor audio/event slots; new slot has empty handles')
        block(backup, struct.pack('<I', previous), 'Original manager auxiliary pointer backup')
        block(manager + field, struct.pack('<I', destination), 'Expanded auxiliary array pointer')
    block(actor, struct.pack('<I', 2), 'Physical actor index 2; model id stays the allocated model id')
    block(flag, struct.pack('<I', 1), 'Expose clone in getter/count: apply ONLY after matching getter/AI hooks')
    manifest = {'status': 'EXPERIMENTAL THIRD ACTOR EXPOSURE; REQUIRES AI_SHADOW GETTER HOOKS',
                'elf_sha256': hashlib.sha256(elf).hexdigest(), 'ram_sha256': hashlib.sha256(ram).hexdigest(),
                'state': state, 'exposure_flag': flag,
                'requirements': ['Apply ai_shadow physical-index-2 getter hook before the exposure flag.',
                                 'Apply verified opposing-leader selector patches before updating actor index 2.',
                                 'Additional two-entry subsystems may remain; this is a guarded crash-localization experiment.',
                                 'Force EE recompiler invalidation after applying code; restore the full baseline after testing.'],
                'blocks': blocks}
    output.write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'{output}: {len(count_code)}-byte count hook, actor {actor:08X}, model {u32(actor+12)}')
    return manifest


def build_stats_guard(ram_path, elf_path, output):
    """Skip two-player post-frame statistics for added physical actor slots."""
    ram = ram_path.read_bytes()
    elf, _, readelf = elf_reader(elf_path)
    entry, cave = A(0x1C1158), 0xB6100
    assert ram[entry:entry + 8] == readelf(entry, 8)
    assert not any(ram[cave:cave + 0x100])
    a = Assembler(cave)
    a.lw(2, 4)
    a.i(11, 2, 2, 2)
    a.branch(4, 2, 0, 'skip_extra')
    for word in struct.unpack('<2I', readelf(entry, 8)):
        a.emit(word)
    a.jump(entry + 8)
    a.label('skip_extra')
    a.move(2, 0)
    a.jr()
    code = a.finish()
    blocks = []
    for address, data, purpose in (
        (cave, code, 'Preserve stats tracking for actor 0/1; return zero for added physical slots'),
        (entry, struct.pack('<2I', (2 << 26) | (cave >> 2), 0), 'Guard two-entry achievement/statistics routine')):
        blocks.append({'address': address, 'expected_hex': ram[address:address + len(data)].hex(),
                       'data_hex': data.hex(), 'purpose': purpose})
    # Damage, melee and other core routines also emit achievement events
    # outside the post-frame stats routine; protect their central sink too.
    event_entry, event_cave = A(0x1296B8), 0xB6180
    assert ram[event_entry:event_entry + 8] == readelf(event_entry, 8)
    assert not any(ram[event_cave:event_cave + 0x40])
    e = Assembler(event_cave)
    e.i(11, 2, 4, 2)
    e.branch(4, 2, 0, 'skip_extra')
    for word in struct.unpack('<2I', readelf(event_entry, 8)):
        e.emit(word)
    e.jump(event_entry + 8)
    e.label('skip_extra')
    e.i(11, 2, 5, 90)  # preserve the usual event<90 success result
    e.jr()
    event_code = e.finish()
    for address, data, purpose in (
        (event_cave, event_code, 'Skip writes to two-player achievement/event storage for extra actors'),
        (event_entry, struct.pack('<2I', (2 << 26) | (event_cave >> 2), 0), 'Guard central actor event sink')):
        blocks.append({'address': address, 'expected_hex': ram[address:address + len(data)].hex(),
                       'data_hex': data.hex(), 'purpose': purpose})
    manifest = {'status': 'SUPPLEMENTAL THIRD-ACTOR STATS GUARD',
                'elf_sha256': hashlib.sha256(elf).hexdigest(), 'ram_sha256': hashlib.sha256(ram).hexdigest(),
                'requirements': ['Force EE recompiler invalidation after applying code.',
                                 'This suppresses statistics only; other two-entry subsystem access remains under investigation.'],
                'blocks': blocks}
    output.write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'{output}: {len(code)}-byte actor-statistics guard at {cave:08X}, {len(event_code)}-byte event guard at {event_cave:08X}')
    return manifest


def build_audio_guards(ram_path, elf_path, output):
    """Prevent added actors from addressing non-existent player voice channels."""
    ram = ram_path.read_bytes()
    elf, _, readelf = elf_reader(elf_path)
    blocks = []
    specs = ((A(0x265850), 6, 'voice playback by channel'),
             (A(0x265970), 6, 'voice stop by channel'),
             (A(0x265B18), 6, 'voice status by channel'),
             (A(0x265F88), 2, 'voice fade by player index'))
    for index, (entry, limit, purpose) in enumerate(specs):
        cave = 0xB6200 + index * 0x40
        assert ram[entry:entry + 8] == readelf(entry, 8), f'Modified audio entry {entry:08X}'
        assert not any(ram[cave:cave + 0x40])
        a = Assembler(cave)
        a.i(11, 2, 4, limit)
        a.branch(4, 2, 0, 'skip')
        original = struct.unpack('<2I', readelf(entry, 8))
        assert all((word >> 26) not in (1, 2, 3, 4, 5, 6, 7) for word in original)
        for word in original:
            a.emit(word)
        a.jump(entry + 8)
        a.label('skip')
        a.move(2, 0)
        a.jr()
        code = a.finish()
        assert len(code) <= 0x40
        for address, data, detail in (
            (cave, code, f'Guard {purpose}; index >= {limit} returns 0'),
            (entry, struct.pack('<2I', (2 << 26) | (cave >> 2), 0), f'Entry for {purpose}')):
            blocks.append({'address': address, 'expected_hex': ram[address:address + len(data)].hex(),
                           'data_hex': data.hex(), 'purpose': detail})
    manifest = {'status': 'SUPPLEMENTAL EXTRA-ACTOR AUDIO GUARDS',
                'elf_sha256': hashlib.sha256(elf).hexdigest(), 'ram_sha256': hashlib.sha256(ram).hexdigest(),
                'evidence': 'Player voice uses channel player_index+4. Channel 6 indexes outside the six-channel table and reads integer 60 as a pointer in the examined RAM.',
                'requirements': ['Force EE recompiler invalidation after applying code.',
                                 'Voice status returns 0 (idle); 265B48 converts this to true/done.',
                                 'Other voice entry points and other two-player systems may still require investigation.'],
                'blocks': blocks}
    output.write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'{output}: four audio guards at 000B6200..000B62E7')
    return manifest


def build_replay_guards(ram_path, elf_path, output):
    """Prevent third-actor input from indexing the two-entry replay buffer.

    Recording happens during ordinary live matches. Playback skips leave the
    already computed input outputs untouched, allowing the extra actor's AI.
    """
    ram = ram_path.read_bytes()
    elf, _, readelf = elf_reader(elf_path)
    blocks = []
    for index, (entry, purpose) in enumerate(((A(0x1D8330), 'replay record initialization'),
                                             (A(0x1D8388), 'replay input recording'),
                                             (A(0x1D8470), 'replay input playback'))):
        cave = 0xB6400 + index * 0x40
        assert ram[entry:entry + 8] == readelf(entry, 8), f'Modified replay entry {entry:08X}'
        assert not any(ram[cave:cave + 0x40])
        a = Assembler(cave)
        a.lw(2, 4)
        a.i(11, 2, 2, 2)
        a.branch(4, 2, 0, 'skip')
        original = struct.unpack('<2I', readelf(entry, 8))
        assert all((word >> 26) not in (1, 2, 3, 4, 5, 6, 7) for word in original)
        for word in original:
            a.emit(word)
        a.jump(entry + 8)
        a.label('skip')
        a.move(2, 0)
        a.jr()
        code = a.finish()
        assert len(code) <= 0x40
        for address, data, detail in (
            (cave, code, f'Skip {purpose} for physical actor indices >=2; preserve caller-provided input'),
            (entry, struct.pack('<2I', (2 << 26) | (cave >> 2), 0), f'Entry for {purpose}')):
            blocks.append({'address': address, 'expected_hex': ram[address:address + len(data)].hex(),
                           'data_hex': data.hex(), 'purpose': detail})
    manifest = {'status': 'SUPPLEMENTAL THIRD-ACTOR REPLAY BUFFER GUARDS',
                'elf_sha256': hashlib.sha256(elf).hexdigest(), 'ram_sha256': hashlib.sha256(ram).hexdigest(),
                'evidence': '1D4370 records live-match actor inputs through 1D8388; replay has only two 54008-byte entries. Physical actor2 indexes beyond it.',
                'requirements': ['Apply before first count-three update, including in a live match.',
                                 'Force EE recompiler invalidation after applying code.',
                                 'Replay output does not contain the extra fighter; extra playback inputs remain controlled by its AI.'],
                'blocks': blocks}
    output.write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'{output}: three replay guards at 000B6400..000B64AB')
    return manifest


def build_teardown_guard(ram_path, elf_path, output):
    """Detach before actor-manager destruction or contiguous-array reset.

    This prevents invalid frees of the expanded auxiliary arrays, which occupy
    the interior of the stage-1 allocation. It does not reclaim that allocation
    or implement automatic re-spawning in subsequent matches. Reset otherwise
    zeros three actors in the original allocation that only contains two.
    """
    ram = ram_path.read_bytes()
    elf, _, readelf = elf_reader(elf_path)
    blocks = []
    for entry, cave, operation in ((A(0x1C2810), 0xB6600, 'destruction'),
                                    (A(0x1C2858), 0xB6680, 'contiguous actor reset')):
        state = 0xB3000
        assert ram[entry:entry + 8] == readelf(entry, 8)
        assert not any(ram[cave:cave + 0x80])
        a = Assembler(cave)
        a.li(8, state)
        a.lw(9, 8, 16)
        a.lw(10, 28, -22364)
        a.branch(5, 9, 10, 'original')
        a.branch(4, 10, 0, 'original')
        for field, backup in ((8, 56), (12, 60)):
            a.lw(11, 8, backup)
            a.branch(4, 11, 0, f'next_{field}')
            a.sw(11, 10, field)
            a.label(f'next_{field}')
        a.li(9, 0xB4800)
        for offset in (0, 12, 24):
            a.sw(0, 9, offset)
        a.sw(0, 8, 32)
        a.addiu(9, 0, -1)
        a.sw(9, 8, 8)  # disable extended-buffer routing for future models
        a.addiu(9, 0, 250)
        a.sw(9, 8, 0)  # detached: frame-entry payload stops dereferencing clone
        a.label('original')
        original = struct.unpack('<2I', readelf(entry, 8))
        assert all((word >> 26) not in (1, 2, 3, 4, 5, 6, 7) for word in original)
        for word in original:
            a.emit(word)
        a.jump(entry + 8)
        code = a.finish()
        assert len(code) <= 0x80
        for address, data, purpose in (
            (cave, code, f'Detach extra actor and restore manager allocation pointers before {operation}'),
            (entry, struct.pack('<2I', (2 << 26) | (cave >> 2), 0), f'Guard actor-manager {operation}')):
            blocks.append({'address': address, 'expected_hex': ram[address:address + len(data)].hex(),
                           'data_hex': data.hex(), 'purpose': purpose})
    manifest = {'status': 'EXPERIMENTAL TEARDOWN INVALID-FREE PREVENTION; NOT COMPLETE LIFECYCLE SUPPORT',
                'elf_sha256': hashlib.sha256(elf).hexdigest(), 'ram_sha256': hashlib.sha256(ram).hexdigest(),
                'requirements': ['Force EE recompiler invalidation after applying code.',
                                 'Does not reclaim the 0x20000 experiment allocation or spawn actors in a later match.',
                                 'Model cleanup and full match-end behavior still require runtime verification; baseline restoration remains preferred.'],
                'blocks': blocks}
    output.write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'{output}: two {len(code)}-byte lifecycle guards at B6600 and B6680')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ram', type=Path, default=ROOT / 'analysis/live-paused.bin')
    parser.add_argument('--elf', type=Path, default=elf_path(ROOT))
    parser.add_argument('--out', type=Path, default=ROOT / 'analysis/prototype-stage1.json')
    parser.add_argument('--cave', type=lambda s: int(s, 0), default=0xB0000)
    parser.add_argument('--x-offset', type=float, default=50.0)
    parser.add_argument('--stage2', action='store_true', help='Build exposure/aux-array patch from a successful stage-1 RAM dump')
    parser.add_argument('--refresh', action='store_true', help='Add transform refresh to existing stage-1 optional tick')
    parser.add_argument('--stats-guard', action='store_true', help='Guard two-player stats for physical actor indices >=2')
    parser.add_argument('--audio-guards', action='store_true', help='Guard absent player voice channels for extra actors')
    parser.add_argument('--replay-guards', action='store_true', help='Guard two-entry replay buffers during recording/playback')
    parser.add_argument('--teardown-guard', action='store_true', help='Restore true auxiliary allocation pointers before actor-manager destruction')
    args = parser.parse_args()
    if args.teardown_guard:
        build_teardown_guard(args.ram, args.elf, args.out)
    elif args.replay_guards:
        build_replay_guards(args.ram, args.elf, args.out)
    elif args.audio_guards:
        build_audio_guards(args.ram, args.elf, args.out)
    elif args.stats_guard:
        build_stats_guard(args.ram, args.elf, args.out)
    elif args.refresh:
        build_refresh(args.ram, args.out)
    elif args.stage2:
        build_stage2(args.ram, args.elf, args.out)
    else:
        build(args.ram, args.elf, args.out, args.cave, args.x_offset)
