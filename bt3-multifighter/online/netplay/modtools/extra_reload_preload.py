"""Dormant, one-extra resource preloader; never commits a model/AI replacement.

This is an offline experimental component, not a production transformation
switch. Installation writes only unused code/data. There is no frame hook and
enabled defaults to zero. A later diagnostic caller may invoke CODE while the
captured battle is idle with every fighter's CPU/input disabled. Completed
resources remain owned by this transaction until a separately reviewed commit.
"""
from native_map import A, CRC, RANGE, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path

from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
import fresh_team_combat as core
from extra_transform_guard import loader_guard_segments
from battle_mode_policy import ACTOR_COUNTS
from native_map import FILE_ID

CODE, CONTROL, END = 0x073E2000, 0x073EF000, 0x073F0000
RAM_BYTES = 0x08000000
REGISTRY_GLOBAL, REGISTRY_OFFSET = A(0x2FEC44), 439276
FIELDS = dict(enabled=0, status=4, manager=8, actor=12, model=16, physical=20,
              old_resource=24, old_dataset=28, resource=32, handle=36, completed=40,
              request_count=44, buffers=64, sizes=80, file_ids=96, registry=112)
ERRORS = {110: 'Captured world/actor/model identity changed',
          111: 'The diagnostic requires every actor idle with CPU/input disabled',
          112: 'Native loader or reload queue is already occupied',
          120: 'A file could not be opened without waiting', 121: 'File size is invalid or exceeds8MiB',
          130: 'No empty dynamic resource slot', 131: 'Independent heap1 allocation failed',
          132: 'Dynamic resource reservation did not match the checked slot',
          133: 'Resource metadata or queued file pointer changed'}


def request_files(character, costume, damaged):
    if type(character) is not int or not 0 <= character <= 160:
        raise ValueError('Character must be an explicit native USA ID0..160')
    if type(costume) is not int or not 0 <= costume <= 3:
        raise ValueError('Costume must be an explicit native slot0..3')
    if type(damaged) is not bool:
        raise ValueError('Damaged must be a Boolean')
    return [FILE_ID(10*character + (1428 if damaged else 1424) + costume),
            FILE_ID(10*character+1432), FILE_ID(10*character+1433)]


def capture(ram, physical, *, allow_leaders=False):
    if len(ram) != RAM_BYTES: raise ValueError('Requires128MiB EE RAM')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager, count = u(core.ACTORS), u(core.MODE+4)
    if (not 0x100000 <= manager <= RAM_BYTES-640 or u(manager) != 2 or
            u(core.MODE) != 1 or u(core.MODE+8) != manager or
            count not in ACTOR_COUNTS or u(core.MODE+12) != count):
        raise ValueError('Requires an active captured4/6 actor world')
    if type(allow_leaders) is not bool: raise ValueError('Leader scope must be Boolean')
    if type(physical) is not int or not (0 if allow_leaders else 2) <= physical < count:
        raise ValueError('Choose one captured extra physical ID')
    actors = [u(core.POINTERS+4*i) for i in range(count)]
    if len(set(actors)) != count: raise ValueError('Actor pointers are not independent')
    models = []
    for i, actor in enumerate(actors):
        if not 0x100000 <= actor <= RAM_BYTES-0x1600 or u(actor) != i:
            raise ValueError('Physical actors must be valid and outside virtual AI aliases')
        model_id = u(actor+12)
        if model_id >= 12: raise ValueError('Actual model ID exceeds native slots')
        model = u(core.MODELS+model_id*4)
        if not 0x100000 <= model <= RAM_BYTES-0x1670 or u(model+16) != model_id:
            raise ValueError('Invalid registered actual model')
        models.append(model)
    actor, model = actors[physical], models[physical]
    resource, dataset = u(model+20), u(model+2356)
    if not 0x100000 <= resource < RAM_BYTES-56 or not 0x100000 <= dataset < RAM_BYTES:
        raise ValueError('Extra does not own a valid loaded model/dataset')
    registry = u(REGISTRY_GLOBAL)+REGISTRY_OFFSET
    if not 0x100000 <= registry < RAM_BYTES-848:
        raise ValueError('Invalid native model resource registry')
    if u(A(0x2FF084)) != 0x02000000 or u(A(0x2FF08C)) != 0x06000000:
        raise ValueError('Requires the established extended heap1')
    return dict(manager=manager, count=count, physical=physical, actor=actor, model=model,
                model_id=u(model+16), old_resource=resource, old_dataset=dataset,
                actors=actors, models=models, registry=registry,owner_action=u(actor+0x948))


# Identity words that must hold on EVERY call, including an unheld background
# poll: they are the only ones this body dereferences or derives an address
# from. Everything else in `checks` describes the OWNER, which a background job
# must stop re-testing once its three files are on the shared native pending
# list - a terminal error110 there would abandon that list with an open handle
# and make every later extra reload refuse with112 for the rest of the match.
MEMORY_SAFETY = (core.MODE, core.ACTORS, REGISTRY_GLOBAL, A(0x2FF084), A(0x2FF08C))


def payload(world, files, quiet=False,allow_forms=False,quiet_guard=None,allocation_sizes=None,mesh_only=False,background=False):
    if type(mesh_only) is not bool:raise ValueError('Mesh-only mode must be Boolean')
    if type(background) is not bool:raise ValueError('Background mode must be Boolean')
    if background and not quiet:raise ValueError('Background IO requires the quiet job body')
    if background and mesh_only:raise ValueError('Mesh-only auxiliary IO keeps the held job body')
    if mesh_only and (len(files)!=3 or files[0]<0 or tuple(files[1:])!=(0xFFFFFFFF,0xFFFFFFFF)):
        raise ValueError('Mesh-only resource requires one file and two native absent IDs')
    if mesh_only and allocation_sizes is not None:raise ValueError('Mesh-only IO uses exact native file allocation sizes')
    if allocation_sizes is not None:
        if (not isinstance(allocation_sizes,(tuple,list)) or len(allocation_sizes)!=3 or
                any(type(n) is not int or not 2048<=n<=0x800000 or n%2048 for n in allocation_sizes)):
            raise ValueError('Explicit resource capacities require three aligned2KiB..8MiB sizes')
    a = Assembler(CODE); a.addiu(29, 29, -0x50)
    for n, reg in enumerate((16, 17, 18, 19, 20, 21, 31)): a.i(63, reg, 29, n*8)
    a.li(16, CONTROL); a.lw(8, 16); a.branch(4, 8, 0, 'done')
    a.lw(8, 16, 4); a.addiu(9, 0, 5); a.branch(4, 8, 9, 'done')
    a.i(11, 9, 8, 100); a.branch(4, 9, 0, 'done')
    checks = [(core.ACTORS, world['manager']), (core.MODE, 1), (core.MODE+4, world['count']),
              (core.MODE+8, world['manager']), (core.MODE+12, world['count']),
              (world['manager'], 2), (core.PAIR+4, 0),
              (world['actor'], world['physical']), (world['actor']+12, world['model_id']),
              (core.MODELS+4*world['model_id'], world['model']),
              (world['model']+16, world['model_id']), (world['model']+20, world['old_resource']),
              (world['model']+2356, world['old_dataset']),
              (REGISTRY_GLOBAL, world['registry']-REGISTRY_OFFSET),
              (A(0x2FF084), 0x02000000), (A(0x2FF08C), 0x06000000)]
    owner_checks = [c for c in checks if c[0] not in MEMORY_SAFETY] if background else []
    if background: checks = [c for c in checks if c[0] in MEMORY_SAFETY]

    def emit_owner_identity():
        for pointer, value in owner_checks if background else checks:
            a.li(8, pointer); a.lw(8, 8); a.li(9, value); a.branch(5, 8, 9, 'error110')
        for i, actor in enumerate(world['actors']):
            a.li(8, core.POINTERS+4*i); a.lw(8, 8); a.li(9, actor); a.branch(5, 8, 9, 'error110')
            if quiet: continue
            a.li(8, actor)
            for off in (0x1278, 0x127C, 0x1280, 0x1284):
                a.lw(9, 8, off); a.branch(5, 9, 0, 'error111')
            a.lw(9, 8, 0x948); a.addiu(10, 0, 11); a.branch(5, 9, 10, 'error111')
        if quiet:
            if quiet_guard is None:
                import extra_reload_quiet
                extra_reload_quiet.guard(a,world,'error111',allow_forms)
            else:
                quiet_guard(a,world,'error111')

    if background:
        for pointer, value in checks:
            a.li(8, pointer); a.lw(8, 8); a.li(9, value); a.branch(5, 8, 9, 'error110')
    else:
        emit_owner_identity()
    a.lw(8, 16, 4); a.branch(4, 8, 0, 'start')
    a.addiu(9, 0, 2); a.branch(5, 8, 9, 'error133'); a.jump('poll')
    a.label('start')
    # Background start phase: the owner is still re-validated before anything is
    # opened, allocated, reserved or queued. Only the poll phase is drain-only.
    if background: emit_owner_identity()
    a.li(8, world['manager'])
    for off in (600, 612, 628):
        a.lw(9, 8, off); a.branch(5, 9, 0, 'error112')
    a.lw(9, 8, 604); a.lw(10, 8, 608); a.branch(5, 9, 10, 'error112')
    for pointer, mask in ((A(0x331DC8)+6640, 0x1800), (A(0x31E77C), 0xFFFF)):
        a.li(8, pointer); a.lw(8, 8); a.i(12, 8, 8, mask); a.branch(5, 8, 0, 'error112')
    a.li(8, world['registry']+836); a.lw(8, 8); a.addiu(9, 0, -1)
    a.branch(5, 8, 9, 'error112')
    if mesh_only:
        # An absent native section cannot borrow another fighter's buffer.
        for off in (68,72,84,88):
            a.lw(8,16,off);a.branch(5,8,0,'error133')
    # Resolve each file once before native helpers that otherwise spin on an
    # unavailable file. Close metadata handles before allocating/queuing data.
    for i, file_id in enumerate(files):
        if mesh_only and i:continue
        a.li(4, file_id); a.call(A(0x2654D8)); a.branch(4, 2, 0, 'error120')
        a.move(17, 2); a.move(4, 17); a.call(A(0x26B5E8)); a.move(18, 2)
        a.move(4, 17); a.call(A(0x26AA40))
        a.i(11, 8, 18, 4097); a.branch(4, 8, 0, 'error121')
        a.branch(4, 18, 0, 'error121'); a.r(0, 18, 0, 18, 11); a.sw(18, 16, 80+i*4)
        if allocation_sizes is not None:
            a.li(8,allocation_sizes[i]);a.r(0x2B,8,8,18);a.branch(5,8,0,'error121')
    # Locate the same first unused record that24B238 will reserve; require no
    # old pointers before writing it. Allocation failure never replaces an old
    # model and only frees this transaction's not-yet-queued buffers.
    a.li(19, world['registry']); a.move(20, 0)
    a.label('free_scan'); a.lw(8, 19, 48); a.i(12, 8, 8, 1); a.branch(4, 8, 0, 'free_found')
    a.addiu(20, 20, 1); a.addiu(19, 19, 56); a.i(11, 8, 20, 12); a.branch(5, 8, 0, 'free_scan')
    a.jump('error130')
    a.label('free_found')
    for off in (0, 16, 32):
        a.lw(8, 19, off); a.branch(5, 8, 0, 'error130')
    for i in range(1 if mesh_only else 3):
        if allocation_sizes is None:a.lw(4, 16, 80+i*4)
        else:a.li(4,allocation_sizes[i])
        a.addiu(5, 0, 64); a.move(6, 0); a.addiu(7, 0, 1)
        a.call(A(0x2554D8)); a.branch(4, 2, 0, 'allocation_failed'); a.sw(2, 16, 64+i*4)
    a.call(A(0x24B238)); a.branch(5, 2, 19, 'error132')
    a.lw(8, 19, 52); a.addiu(9, 20, 2); a.branch(5, 8, 9, 'error132')
    a.sw(8, 16, 36); a.sw(19, 16, 32)
    for i, file_id in enumerate(files):
        a.lw(8, 16, 64+i*4); a.sw(8, 19, 16*i)
        a.lw(8, 16, 80+i*4); a.sw(8, 19, 16*i+4)
        a.li(8, file_id); a.sw(8, 19, 16*i+8); a.sw(0, 19, 16*i+12)
    a.addiu(8, 0, 3); a.sw(8, 19, 48)
    # Queue jobs only after all independent buffers and the record exist.
    a.addiu(8, 0, 2); a.sw(8, 16, 4)
    for i, file_id in enumerate(files):
        if mesh_only and i:continue
        a.li(4, file_id); a.lw(5, 16, 64+i*4); a.call(A(0x2651C0))
        a.lw(8, 16, 64+i*4); a.branch(5, 2, 8, 'error133')
        a.addiu(8, 0, i+1); a.sw(8, 16, 44)
    a.jump('done')
    a.label('poll'); a.lw(19, 16, 32)
    for i in range(12):
        a.li(8, world['registry']+56*i); a.branch(4, 19, 8, 'poll_valid')
    a.jump('error133'); a.label('poll_valid')
    a.call(A(0x265298)); a.branch(4, 2, 0, 'done')
    a.lw(8, 19, 48); a.addiu(9, 0, 3); a.branch(5, 8, 9, 'error133')
    a.lw(8, 19, 52); a.lw(9, 16, 36); a.branch(5, 8, 9, 'error133')
    for i, file_id in enumerate(files):
        for roff, coff in ((16*i, 64+i*4), (16*i+4, 80+i*4)):
            a.lw(8, 19, roff); a.lw(9, 16, coff); a.branch(5, 8, 9, 'error133')
        a.lw(8, 19, 16*i+8); a.li(9, file_id); a.branch(5, 8, 9, 'error133')
    a.addiu(8, 0, 1); a.sw(8, 16, 40); a.addiu(8, 0, 5); a.sw(8, 16, 4); a.jump('done')
    a.label('allocation_failed')
    for i in range(3):
        a.lw(4, 16, 64+i*4); a.branch(4, 4, 0, f'not_allocated{i}')
        a.call(A(0x255508)); a.sw(0, 16, 64+i*4); a.label(f'not_allocated{i}')
    a.jump('error131')
    for error in ERRORS:
        a.label(f'error{error}'); a.addiu(8, 0, error); a.sw(8, 16, 4); a.jump('done')
    a.label('done'); a.lw(2, 16, 4)
    for n, reg in enumerate((16, 17, 18, 19, 20, 21, 31)): a.i(55, reg, 29, n*8)
    a.addiu(29, 29, 0x50); a.jr()
    code = a.finish(); assert CODE+len(code) < CONTROL
    return code


def queue_snapshot(ram):
    """Read the native8x36 ring without mistaking inactive stale slots for requests."""
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager = u(core.ACTORS)
    if not 0x100000 <= manager <= len(ram)-640: raise ValueError('Invalid actor manager')
    write, read, active = u(manager+604), u(manager+608), u(manager+600)
    if write >= 8 or read >= 8: raise ValueError('Invalid native queue cursors')
    base = manager+312
    def decode(pointer):
        if not base <= pointer < base+8*36 or (pointer-base) % 36:
            raise ValueError('Active request pointer is not a native record')
        values = struct.unpack_from('<9i', ram, pointer)
        keys = ('owner_physical', 'kind', 'character', 'costume', 'damaged',
                'animation_character', 'combat_character', 'sound_character', 'auxiliary_kind')
        return dict(address=pointer, **dict(zip(keys, values)))
    indices = []; at = read
    while at != write: indices.append(at); at = (at+1) % 8
    return dict(manager=manager, write_cursor=write, read_cursor=read, phase=u(manager+612),
                ready=u(manager+616), busy=u(manager+628), active=decode(active) if active else None,
                queued=[decode(base+i*36) for i in indices], capacity=7, record_bytes=36)


def build_memory(ram, physical, character, costume=0, damaged=False, source='<offline-memory>'):
    world = capture(ram, physical); files = request_files(character, costume, damaged)
    _, _, native = elf_reader(elf_path(ROOT))
    for p, data in loader_guard_segments(native):
        if ram[p:p+len(data)] != data: raise ValueError(f'Preserve extra-loader/Spirit Bomb guard:{p:08X}')
    for p, size in (RANGE(0x2654D8, 0x58), (A(0x26B5E8), 0x38), (A(0x26AA40), 0x38),
                    (A(0x2554D8), 0x30), (A(0x255508), 0x68), (A(0x24B238), 0x60),
                    (A(0x2651C0), 0xD8), (A(0x265298), 0x180)):
        if ram[p:p+size] != native(p, size): raise ValueError(f'Native loader/allocator changed:{p:08X}')
    if any(ram[CODE:END]): raise ValueError('One-extra preloader reservation occupied')
    control = bytearray(256)
    for key in ('manager', 'actor', 'model', 'physical', 'old_resource', 'old_dataset', 'registry'):
        struct.pack_into('<I', control, FIELDS[key], world[key])
    struct.pack_into('<I', control, 36, 0xFFFFFFFF); struct.pack_into('<3I', control, 96, *files)
    blocks = [dict(address=p, expected_hex=ram[p:p+len(b)].hex(), data_hex=b.hex())
              for p, b in ((CODE, payload(world, files)), (CONTROL, bytes(control)))]
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()),
                status='DORMANT ONE-EXTRA PRELOADER; NO HOOK, NO MODEL/AI COMMIT',
                blocks=blocks, code=CODE, control=CONTROL, fields=FIELDS, world=world,
                request=dict(character=character, costume=costume, damaged=damaged, file_ids=files),
                native_queue=queue_snapshot(ram), errors=ERRORS,
                requirements=['Install alone is inert: enabled0 and no native entry is redirected.',
                              'A diagnostic caller must disable all actor CPU/input and require idle action11 before invoking.',
                              'Set enabled1 only in that separate diagnostic; status5/completed1 means resources ready only.',
                              'Failure is terminal; after queuing IO, keep buffers allocated and restore checkpoint to discard.',
                              'Do not remove existing reload/transform guards or assign this resource to a live model.'],
                limitations=['No automatic request interception, animation handoff, resource reclamation, sound-bank swap, or AI commit.',
                             'Metadata availability and allocator failure are checked; guest behavior remains untested live.',
                             '2651C0 reopens each preflighted file in its native unbounded loop; transient reopen failure remains a diagnostic risk.'])


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path); p.add_argument('--out', required=True, type=Path)
    p.add_argument('--physical', type=int); p.add_argument('--character', type=int)
    p.add_argument('--costume', type=int, default=0); p.add_argument('--damaged', action='store_true')
    p.add_argument('--audit', action='store_true'); x = p.parse_args(); ram = read_ram(x.source)
    result = queue_snapshot(ram) if x.audit else build_memory(ram, x.physical, x.character, x.costume, x.damaged, x.source)
    x.out.write_text(json.dumps(result, indent=2)+'\n'); print(x.out)
