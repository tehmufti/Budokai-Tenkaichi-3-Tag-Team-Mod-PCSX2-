"""Bounded guest IO stage for one captured extra's private reload transaction.

This extends the reviewed dormant preloader with a nonspinning queue submission
and a bounded polling deadline. It installs no frame/native hook, changes no
actor/model/AI, and leaves all transformation guards in place. The caller owns
the preparation hold and may call ENTRY once per guest frame. READY means only
that an independent resource triple has loaded; model commit is separate.
"""
from native_map import A, CRC, RANGE, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from types import FunctionType

import extra_reload_preload as prior
import extra_transform_guard
from camera_snapshot import read_ram
from prototype import Assembler, ROOT, elf_reader

ENTRY, INNER, QUEUE = 0x07600000, 0x07600800, 0x07604000
CONTROL, END = 0x0760F000, 0x07610000
POLL_UPDATES = 1800
POLLS, TIMEOUT = 120, 124
FREE_JOBS, PENDING_JOBS = A(0x31E768), A(0x31E774)
ERRORS = dict(prior.ERRORS, **{})
ERRORS[134] = 'Resource read exceeded the polling deadline; retain queued buffers'
# Preserve logical damage state when an empty damaged file is replaced with
# this costume's intact mesh. File IDs alone cannot encode that distinction.
REQUEST_META,REQUEST_MAGIC=224,0x42543452


def decode_request(ram,files):
    from bt4_resources import decode_files,request_files
    marker,character,costume,damaged=struct.unpack_from('<4I',ram,CONTROL+REQUEST_META)
    if marker==REQUEST_MAGIC:
        if damaged not in (0,1) or request_files(character,costume,bool(damaged))!=list(files):
            raise ValueError('Reload request metadata does not match its loaded files')
        return character,costume,bool(damaged)
    # Old prepared checkpoints have no request metadata. Their non-aliased
    # file IDs remain decodable; never infer a damaged alias from an intact ID.
    return decode_files(files)


def inner_code(world, files, quiet=False,allow_forms=False,quiet_guard=None,allocation_sizes=None,mesh_only=False,background=False):
    # Keep the prior independently reviewed identity/allocation/retention logic.
    # Replace only the unsafe2651C0 call: its initial open loop never yielded.
    env = dict(prior.payload.__globals__)
    env.update(CODE=INNER, CONTROL=CONTROL, ERRORS=ERRORS)
    code = bytearray(FunctionType(prior.payload.__code__, env)(world, files, quiet,allow_forms,quiet_guard,allocation_sizes,mesh_only,background))
    old, new = (3 << 26) | (A(0x2651C0) >> 2), (3 << 26) | (QUEUE >> 2)
    count = 0
    for off in range(0, len(code), 4):
        if struct.unpack_from('<I', code, off)[0] == old:
            struct.pack_into('<I', code, off, new)
            count += 1
    if count != (1 if mesh_only else 3):
        raise ValueError('Reviewed resource submission call layout changed')
    if INNER + len(code) >= QUEUE:
        raise ValueError('Loader body exceeds reservation')
    return bytes(code)


def queue_code():
    """Submit already preflighted metadata through the exact native job lists.

    Native2651C0's successful suffix is reproduced with a checked free node.
    The job's own-buffer flag is0, so only this transaction owns its allocation.
    Actual file opening remains in native265298, once per later guest poll.
    """
    a = Assembler(QUEUE); a.addiu(29, 29, -0x30)
    for i, r in enumerate((16, 17, 18, 19, 31)): a.i(63, r, 29, i*8)
    a.move(16, 4); a.move(17, 5); a.li(18, CONTROL)
    a.lw(8, 18, 4); a.addiu(9, 0, 2); a.branch(5, 8, 9, 'invalid')
    for i in range(3):
        a.lw(8, 18, 96+i*4); a.branch(5, 8, 16, f'next{i}')
        a.lw(8, 18, 64+i*4); a.branch(5, 8, 17, 'invalid')
        a.lw(19, 18, 80+i*4); a.jump('matched'); a.label(f'next{i}')
    a.jump('invalid')
    a.label('matched')
    a.branch(4, 19, 0, 'invalid'); a.i(12, 8, 19, 2047); a.branch(5, 8, 0, 'invalid')
    a.r(2, 19, 0, 19, 11); a.i(11, 8, 19, 4097); a.branch(4, 8, 0, 'invalid')
    a.li(8, FREE_JOBS); a.lw(9, 8); a.branch(4, 9, 0, 'invalid')
    a.lw(9, 8, 8); a.branch(4, 9, 0, 'invalid')
    a.li(4, FREE_JOBS); a.call(A(0x255BD8)); a.branch(4, 2, 0, 'invalid')
    a.sw(0, 2, 8); a.sw(16, 2, 12); a.sw(19, 2, 16); a.sw(17, 2, 20)
    a.move(5, 2); a.li(4, PENDING_JOBS); a.call(A(0x255978))
    a.move(2, 17); a.jump('done')
    a.label('invalid'); a.move(2, 0)
    a.label('done')
    for i, r in enumerate((16, 17, 18, 19, 31)): a.i(55, r, 29, i*8)
    a.addiu(29, 29, 0x30); a.jr()
    code = a.finish(); assert len(code) < 0x800
    return code


def entry_code():
    a = Assembler(ENTRY); a.addiu(29, 29, -0x20)
    for i, r in enumerate((8, 9, 10)): a.i(63, r, 29, i*8)
    a.li(8, CONTROL); a.lw(9, 8); a.branch(4, 9, 0, 'inner')
    a.lw(9, 8, 4); a.addiu(10, 0, 2); a.branch(5, 9, 10, 'inner')
    a.lw(9, 8, POLLS); a.lw(10, 8, TIMEOUT)
    a.r(0x2B, 10, 9, 10); a.branch(4, 10, 0, 'expired')
    a.addiu(9, 9, 1); a.sw(9, 8, POLLS); a.jump('inner')
    a.label('expired'); a.addiu(9, 0, 134); a.sw(9, 8, 4)
    a.label('inner')
    for i, r in enumerate((8, 9, 10)): a.i(55, r, 29, i*8)
    a.addiu(29, 29, 0x20); a.jump(INNER)
    code = a.finish(); assert len(code) < INNER-ENTRY
    return code


def build_memory(ram, physical, character, costume=0, damaged=False,
                 source='<offline-memory>', timeout=POLL_UPDATES, quiet=False,allow_forms=False,mesh_only=False,
                 background=False,row=None,generation=None):
    world = prior.capture(ram, physical)
    if quiet:
        import extra_reload_quiet
        extra_reload_quiet.validate(ram,world,allow_forms)
    if type(background) is not bool:raise ValueError('Background mode must be Boolean')
    guard = None
    if background:
        # The background body is still BUILT under the acknowledged hold; only
        # its later calls are unheld, so the ordinary validate() above applies.
        if not quiet or not allow_forms:
            raise ValueError('Background reload IO serves acknowledged ordinary forms only')
        import extra_reload_requests as requests
        import extra_reload_quiet
        if row!=requests.RECORDS+(physical-2)*requests.STRIDE:
            raise ValueError('Background reload IO requires this extra private request row')
        if type(generation) is not int or not 1<=generation<=0xFFFFFFFF:
            raise ValueError('Background reload IO requires the captured row generation')
        guard = extra_reload_quiet.background_guard(row,generation,world['owner_action'])
    elif row is not None or generation is not None:
        raise ValueError('A held reload job has no background request row')
    files = prior.request_files(character, costume, damaged)
    if type(mesh_only) is not bool:raise ValueError('Mesh-only mode must be Boolean')
    if mesh_only:files=[files[0],0xFFFFFFFF,0xFFFFFFFF]
    if type(timeout) is not int or not 1 <= timeout <= 18000:
        raise ValueError('Polling timeout must be1..18000 guest calls')
    _, _, native = elf_reader(elf_path(ROOT))
    # Existing admission can wrap the reverse-transform entry. Its retained
    # loader implementation and both queue entries must remain exact.
    for p, data in extra_transform_guard.loader_guard_segments(native):
        if p == extra_transform_guard.loader.TRANSFORM_HOOK: continue
        if quiet and allow_forms and p in (extra_transform_guard.loader.PUSH_HOOK,extra_transform_guard.loader.READY_HOOK):
            import extra_reload_forms as forms
            code,body=(forms.PUSH,forms.push_code()) if p==extra_transform_guard.loader.PUSH_HOOK else (forms.READY,forms.handshake('ready'))
            hook=struct.pack('<2I',(2<<26)|(code>>2),0)
            if ram[p:p+8]==hook and ram[code:code+len(body)]==body:continue
        if quiet and p == extra_transform_guard.loader.PUSH_HOOK:
            import extra_reload_requests as requests
            hook=struct.pack('<2I',(2<<26)|(requests.CODE>>2),0)
            body=requests.payload()
            if ram[p:p+len(hook)]==hook and ram[requests.CODE:requests.CODE+len(body)]==body:
                continue
        if ram[p:p+len(data)] != data:
            raise ValueError(f'Existing loader safety changed at{p:08X}')
    for p, size in (RANGE(0x2654D8, 0x58), (A(0x26B5E8), 0x38), (A(0x26AA40), 0x38),
                    (A(0x2554D8), 0x30), (A(0x255508), 0x68), (A(0x24B238), 0x60),
                    (A(0x265298), 0x180), (A(0x255BD8), 0x28),
                    (A(0x255B88), 0x50), (A(0x255978), 0x68)):
        if ram[p:p+size] != native(p, size):
            raise ValueError(f'Native IO/allocator helper changed:{p:08X}')
    if any(ram[ENTRY:END]): raise ValueError('Reload IO reservation occupied')
    control = bytearray(256)
    for key in ('manager', 'actor', 'model', 'physical', 'old_resource', 'old_dataset', 'registry'):
        struct.pack_into('<I', control, prior.FIELDS[key], world[key])
    struct.pack_into('<I', control, 36, 0xFFFFFFFF)
    struct.pack_into('<3I', control, 96, *files)
    struct.pack_into('<4I',control,REQUEST_META,REQUEST_MAGIC,character,costume,int(damaged))
    struct.pack_into('<I', control, TIMEOUT, timeout)
    pieces = [(ENTRY, entry_code()), (INNER, inner_code(world, files, quiet,allow_forms,guard,mesh_only=mesh_only,background=background)),
              (QUEUE, queue_code()), (CONTROL, bytes(control))]
    return dict(serial=SERIAL, crc=CRC, source=str(source),
        status='DORMANT BOUNDED RELOAD IO; MODEL COMMIT SEPARATE',
        entry=ENTRY, control=CONTROL, world=world, timeout=timeout, quiet=quiet, background=background,
        request=dict(physical=physical, character=character, costume=costume,
                     damaged=damaged, file_ids=files), errors=ERRORS,
        blocks=[dict(address=p, expected_hex=ram[p:p+len(d)].hex(), data_hex=d.hex()) for p,d in pieces],
        requirements=['No hook or guard unlock is installed; enabled0 remains inert.',
                      'Caller must hold all captured fighters idle with CPU/input0 and invoke ENTRY once per frame.',
                      'Status5 publishes independently loaded resources only; model/AI/effect commit is separate.',
                      'Timeout/error after submission retains buffers and record; restore checkpoint before discarding them.'],
        evidence=['Queue submission contains no file-open retry loop.',
                  'Native265298 attempts a pending open once per call; deadline bounds service polling.',
                  'Native free/pending list operations and owned-buffer flag match2651C0 successful suffix.'])


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path); p.add_argument('--out', required=True, type=Path)
    p.add_argument('--physical', required=True, type=int); p.add_argument('--character', required=True, type=int)
    p.add_argument('--costume', type=int, default=0); p.add_argument('--damaged', action='store_true')
    x = p.parse_args(); m = build_memory(read_ram(x.source), x.physical, x.character, x.costume, x.damaged, x.source)
    x.out.write_text(json.dumps(m, indent=2)+'\n'); print(x.out)
