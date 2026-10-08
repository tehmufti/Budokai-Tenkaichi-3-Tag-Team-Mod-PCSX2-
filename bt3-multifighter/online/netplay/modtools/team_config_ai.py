"""Offline configured6..12 actor AI upgrade; existing six artifacts unchanged.

Configuration lists physical_id, actor, model_id, model, dataset, team, and
cpu for every actor. Physical IDs remain ordered by alternating teams because
the installed combat resolver uses that layout. No emulator writes occur.
"""
from native_map import A, CRC, SERIAL
import argparse
import json
import struct
from pathlib import Path
from types import FunctionType, SimpleNamespace

from ai_shadow import Assembler, AI_GLOBAL, FRAME_HOOK
import distinct_ai
import team_six_ai as six
import team_pair_ai as pair
import packet_pool_grow as packets

ROOT = Path(__file__).resolve().parents[1]
FRAME, PICKER, INITIALIZE, CONTROL = 0x07210000, 0x07212000, 0x07216000, 0x07218000
AUXILIARY = (CONTROL+0x800, CONTROL+0xC00)
DESCRIPTORS, SHADOWS, RECORDS = six.DESCRIPTORS, six.SHADOWS, six.RECORDS


def integer(value):
    return int(value, 0) if isinstance(value, str) else int(value)


def normalize(config):
    if any(not isinstance(row.get('cpu'), bool) for row in config['actors']):
        raise ValueError('CPU assignments must be explicit JSON booleans')
    actors = [{k: (v if k == 'cpu' else integer(v)) for k, v in row.items()}
              for row in config['actors']]
    n = len(actors)
    if not 6 <= n <= 12:
        raise ValueError('Configured actor count must be6..12')
    for i, row in enumerate(actors):
        if set(row) != {'physical_id', 'actor', 'model_id', 'model', 'dataset', 'team', 'cpu'}:
            raise ValueError('Every actor requires explicit physical_id/actor/model_id/model/dataset/team/cpu')
        if row['physical_id'] != i or row['team'] != i & 1:
            raise ValueError('Current combat hooks require physical IDs ordered by alternating team0/team1')
        if not 0 <= row['model_id'] < 12:
            raise ValueError('Native model table capacity is12')
    for key in ('actor', 'model_id', 'model'):
        if len({row[key] for row in actors}) != n:
            raise ValueError(f'Every fighter requires a distinct {key}')
    preserve = integer(config.get('preserve_count', 6))
    if preserve != 6:
        raise ValueError('This upgrade starts from the existing six-context checkpoint')
    defaults = list(config.get('targets', default_targets(n)))
    defaults = [integer(i) for i in defaults]
    if len(defaults) != n or any(not 0 <= j < n or (j & 1) == (i & 1) for i, j in enumerate(defaults)):
        raise ValueError('Each initial target must be an opposing physical actor')
    return {'actors': actors, 'preserve_count': preserve, 'targets': defaults,
            'creation_header': integer(config.get('creation_header', 0x07318400 if n > 6 else 0))}


def capture_config(source, count, cpu_mask):
    """Read actual creation descriptors into an explicit reviewable config."""
    if not 6 <= count <= 12 or not 0 <= cpu_mask < 1 << count:
        raise ValueError('Invalid actor count or CPU mask')
    ram = Path(source).read_bytes()
    if len(ram) != 0x8000000:
        raise ValueError('Requires full128MiB EE RAM')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    rows = []
    for i in range(count):
        actor = u(DESCRIPTORS[i]) if i < 6 else u(0x07318000+(i-6)*0x80+28)
        if not 0x100000 <= actor <= len(ram)-0x1600 or u(actor) != i:
            raise ValueError(f'Missing or aliased physical actor{i}')
        mid = u(actor+12)
        if mid >= 12:
            raise ValueError('Invalid model ID')
        model = u(A(0x31C640)+mid*4)
        if not 0x100000 <= model <= len(ram)-0x1680:
            raise ValueError('Missing registered model')
        rows.append({'physical_id': i, 'actor': actor, 'model_id': mid, 'model': model,
                     'dataset': u(model+2356), 'team': u(actor+8), 'cpu': bool(cpu_mask & (1<<i))})
    return normalize({'actors': rows})


def initializer(n, preserve=6):
    a = Assembler(INITIALIZE)
    a.addiu(29, 29, -0x60)
    saved = [(16+i, i*8) for i in range(8)] + [(31, 0x40)]
    for reg, offset in saved:
        a.mem(63, reg, 29, offset)
    # D5000 only accepts aliases inside published count. Unpublished actors
    # must use its disabled-mode D3000 pair-local fallback during native init.
    a.load_address(8, six.MODE)
    a.mem(35, 9, 8, 0)
    a.mem(43, 9, 29, 0x48)
    a.load_address(16, pair.CONTROL)
    a.mem(35, 17, 28, -0x5760)
    a.load_address(18, CONTROL)
    a.mem(35, 9, 18, 0x2C)
    a.branch(17, 9, 'invalid', not_equal=True)
    a.nop()
    a.branch(17, 0, 'invalid')
    a.nop()
    a.mem(35, 9, 18, 0x28)
    a.mem(35, 10, 28, -22364)
    a.branch(9, 10, 'invalid', not_equal=True)
    a.nop()
    a.mem(43, 17, 18, 8)
    a.addiu(9, 0, 1)
    a.mem(43, 9, 18, 0)
    a.mem(43, 0, 8, 0)
    for physical in range(preserve, n):
        distinct_ai.emit_initialize(a, physical, DESCRIPTORS[physical], RECORDS[physical], CONTROL)
    a.addiu(8, 0, 5)
    a.branch(0, 0, 'status')
    a.nop()
    for label, value in (('invalid', 101), ('owned', 102), ('dataset_failed', 103)):
        a.label(label)
        a.addiu(8, 0, value)
        a.branch(0, 0, 'status')
        a.nop()
    a.label('status')
    a.load_address(9, CONTROL)
    a.mem(43, 8, 9, 0)
    a.load_address(8, six.MODE)
    a.mem(35, 9, 29, 0x48)
    a.mem(43, 9, 8, 0)
    for reg, offset in saved:
        a.mem(55, reg, 29, offset)
    a.emit(0x03E00008)
    a.addiu(29, 29, 0x60)
    return a.finish()


def default_targets(n):
    return (3, 2, 1, 0, 5, 4) + tuple((i ^ 1) if (i ^ 1) < n else 1 for i in range(6, n))


def program(n, defaults=None):
    if not 6 <= n <= 12:
        raise ValueError('Supported counts6..12')
    defaults = tuple(defaults or default_targets(n))
    # Rebind only a private emitter namespace. The six module, its constants,
    # files, and generated artifacts are never changed or monkey-patched.
    context = dict(six.__dict__)
    context.update(N=n, DEFAULTS=defaults, FRAME=FRAME, PICKER=PICKER,
                   INITIALIZE=INITIALIZE, CONTROL=CONTROL,
                   distinct_ai=SimpleNamespace(FRAME=six.FRAME))
    for name in ('emit_slice', 'picker_stub', 'frame_stub'):
        original = getattr(six, name)
        context[name] = FunctionType(original.__code__, context, original.__name__, original.__defaults__, original.__closure__)
    payloads = ((FRAME, context['frame_stub']()), (PICKER, context['picker_stub']()),
                (INITIALIZE, initializer(n)))
    if FRAME+len(payloads[0][1]) > PICKER or PICKER+len(payloads[1][1]) > INITIALIZE or INITIALIZE+len(payloads[2][1]) > CONTROL:
        raise ValueError('Configured AI code reservations overlap')
    return {'segments': [{'address': p, 'data_hex': b.hex()} for p, b in payloads],
            'count': n, 'targets': defaults}


def build_install(source, config):
    config = normalize(config)
    rows, n = config['actors'], len(config['actors'])
    ram = Path(source).read_bytes()
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    if len(ram) != 0x8000000 or u(six.CONTROL) != 5 or u(six.MODE) != 1 or u(six.COUNT) != 6:
        raise ValueError('Requires an initialized and exposed six-context128MiB checkpoint')
    manager, normal_ai = u(pair.ACTOR_GLOBAL), u(AI_GLOBAL)
    if not normal_ai or manager != u(six.CAPTURED_MANAGER) or manager != u(pair.ACTOR_HEADER) or u(pair.CONTROL+4):
        raise ValueError('Actor/AI manager or alias state mismatch')
    if not u(pair.EXPOSURE) or not u(0xF609C):
        raise ValueError('Six exposure must still be active')
    creation = config['creation_header']
    if creation and (u(creation+8) < n-6 or u(creation+28)):
        raise ValueError('Additional actor creation must be complete and still unpublished')
    if any(ram[FRAME:CONTROL+0x1000]):
        raise ValueError('Configured code/control/auxiliary arena is occupied')
    if u(FRAME_HOOK) != (3<<26) | (six.FRAME>>2):
        raise ValueError('Expected existing six-frame hook')
    for p, _, bridge, _ in distinct_ai.CALLS:
        if u(p) != (3<<26) | (bridge>>2):
            raise ValueError('Missing narrow native-init role bridge')
    payloads = []
    for i, row in enumerate(rows):
        actor, mid, model, dataset = (row[k] for k in ('actor', 'model_id', 'model', 'dataset'))
        if not 0x100000 <= actor <= len(ram)-0x1600 or u(actor) != i or u(actor+8) != row['team'] or u(actor+12) != mid:
            raise ValueError(f'Actor{i} identity/team/model mismatch')
        if u(actor+0x994) >= 5:
            raise ValueError('Native roster slot must remain0..4; sixth team member needs its own valid stat row')
        if u(A(0x31C640)+mid*4) != model or u(model+16) != mid or u(model+2356) != dataset or not u(model+4):
            raise ValueError(f'Actor{i} model registration/dataset mismatch')
        if i < 6 and not u(model+8):
            raise ValueError('An existing fighter model is no longer enabled')
        if i >= 6 and (u(model+4) != 1 or u(model+8) != 0):
            raise ValueError('Added models must remain registered but hidden until packet capacity is ready')
        own = 0x10+(i&1)*0x520
        if i < 6:
            if u(DESCRIPTORS[i]) != actor or u(DESCRIPTORS[i]+4) != SHADOWS[i] or u(SHADOWS[i]+own+24) != dataset:
                raise ValueError('Existing six private contexts must match the configured actors')
            continue
        if u(actor+0x1278):
            raise ValueError('New actors must have CPU disabled before private initialization')
        source_shadow = SHADOWS[i&1]
        context = ram[source_shadow:source_shadow+0xA60]
        if struct.unpack_from('<I', context, own+36)[0] & 1:
            raise ValueError('Cannot seed a private manager with an owned dataset')
        # Initialization targets an existing opposite leader while unpublished.
        descriptor = struct.pack('<12I', actor, SHADOWS[i], i&1, 0, 0, i,
                                 DESCRIPTORS[(i&1)^1], 0, mid, model, dataset, source_shadow)
        record = struct.pack('<8I', actor, mid, model, dataset, SHADOWS[i], 0, 0, 0)
        payloads += [(DESCRIPTORS[i], descriptor), (RECORDS[i], record), (SHADOWS[i], context)]
    generated = program(n, config['targets'])
    control = bytearray(0x40)
    struct.pack_into('<4I', control, 0x20, n, 6, manager, normal_ai)
    payloads += [(s['address'], bytes.fromhex(s['data_hex'])) for s in generated['segments']]
    payloads.append((CONTROL, bytes(control)))
    blocks = []
    for address, data in payloads:
        old = ram[address:address+len(data)]
        if any(old):
            raise ValueError(f'Occupied new descriptor/context/code region{address:08X}')
        blocks.append({'address': address, 'expected_hex': old.hex(), 'data_hex': data.hex()})
    blocks.append({'address': FRAME_HOOK, 'expected_hex': ram[FRAME_HOOK:FRAME_HOOK+4].hex(),
                   'data_hex': struct.pack('<I', (3<<26) | (FRAME>>2)).hex()})
    return {**generated, 'serial': SERIAL, 'crc': CRC, 'source_ram': str(Path(source).resolve()),
            'status': 'CONFIGURED PRIVATE AI INITIALIZATION; PUBLIC COUNT UNCHANGED', 'config': config,
            'blocks': blocks, 'control': CONTROL, 'auxiliary_reservations': AUXILIARY,
            'requirements': ['High EE code execution at07210000 must be proved before installation.',
                             'Created additional actors and distinct registered models/datasets, CPU disabled.',
                             'D3000 pair-local fallback remains installed; initializer withdraws/restores D8080 synchronously.',
                             'Publication is separate, after native initialization status5/completedN-6 and support guards pass.'],
            'limitations': ['Existing six contexts/counters remain in place; new contexts6..11 use native initialization.',
                            'Current combat hooks require alternating physical team IDs.',
                            'Native selected roster supports five rows; a sixth member needs independent valid stats, not slot5.']}


def build_activation(source, installation, support):
    """Prepare final publication only after explicit supporting patch verification.

    support contains capacity>=N, verified feature names, and expected code
    bytes for the separately reviewed generalized engine guards. It is not a
    permission flag: each supplied hook/body is checked against the snapshot.
    """
    ram = Path(source).read_bytes()
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    config = normalize(installation['config'])
    rows, n = config['actors'], len(config['actors'])
    required = {'physical_getters', 'ko_retention', 'special_limits', 'model_effect_bounds',
                'contact_matrix', 'hitstop12', 'dead_contact_exclusion', 'render_capacity', 'high_ee_execution'}
    if n > 6:
        required.update(('temporary_model_capacity', 'packet_capacity'))
    if integer(support['capacity']) < n or not required <= set(support['features']) or not support.get('expected_code'):
        raise ValueError('Generalized actor/model/KO/special/collision support proof is incomplete')
    for entry in support['expected_code']:
        p, data = integer(entry['address']), bytes.fromhex(entry['data_hex'])
        if not data or ram[p:p+len(data)] != data:
            raise ValueError(f'Supporting code does not match at{p:08X}')
    if len(ram) != 0x8000000 or u(CONTROL) != 5 or u(CONTROL+4) != n-6:
        raise ValueError('All added private contexts must complete native initialization')
    if u(six.MODE) != 1 or u(six.COUNT) != 6 or not u(0xF609C) or u(pair.CONTROL+4):
        raise ValueError('Requires intact prior six exposure outside an AI alias slice')
    if u(FRAME_HOOK) != (3<<26) | (FRAME>>2) or u(CONTROL+0x20) != n:
        raise ValueError('Configured frame/count mismatch')
    for segment in program(n, config['targets'])['segments']:
        address, code = segment['address'], bytes.fromhex(segment['data_hex'])
        if ram[address:address+len(code)] != code:
            raise ValueError('Configured AI code differs from the reviewed generator')
    manager = u(pair.ACTOR_GLOBAL)
    if manager != u(CONTROL+0x28) or manager != u(six.CAPTURED_MANAGER):
        raise ValueError('Actor manager changed')
    if n > 6:
        verify_packet_capacity(ram, manager)
    creation = config['creation_header']
    if creation and (u(creation+8) < n-6 or u(creation+28)):
        raise ValueError('Additional actor creation is incomplete or already exposed')
    blocks = []
    def block(p, data, why):
        blocks.append({'address': p, 'expected_hex': ram[p:p+len(data)].hex(), 'data_hex': data.hex(), 'purpose': why})
    def word(p, value, why):
        block(p, struct.pack('<I', value), why)
    for i, row in enumerate(rows):
        actor, mid, model, dataset = (row[k] for k in ('actor', 'model_id', 'model', 'dataset'))
        own = SHADOWS[i]+0x10+(i&1)*0x520
        if u(DESCRIPTORS[i]) != actor or u(actor) != i or u(actor+8) != (i&1) or u(actor+12) != mid:
            raise ValueError('Actor identities changed before publication')
        if u(A(0x31C640)+mid*4) != model or u(model+2356) != dataset or u(own+24) != dataset or u(own) != (i&1):
            raise ValueError('Native private AI does not match actual model dataset')
        if i >= 6:
            if u(RECORDS[i]+20) != dataset or u(RECORDS[i]+28) & 1:
                raise ValueError('Added native context verification failed')
            if u(model+4) != 1 or u(model+8) != 0:
                raise ValueError('Added model is not in the expected registered/hidden state')
            word(model+3184, 1, 'New actor drives its model pose')
            word(model+3188, 0, 'Disable generic preview model updates')
        word(actor+0x1278, int(row['cpu']), 'Apply configured CPU assignment without changing controller ownership')
        if not row['cpu']:
            for offset in (0x127C, 0x1280, 0x1284):
                word(actor+offset, 0, 'Clear previous CPU input for a configured human/inactive fighter')
        word(six.POINTERS+i*4, actor, 'Publish captured physical actor pointer')
        word(six.TARGETS+i*4, config['targets'][i], 'Publish initial opposing target')
    for i, destination in enumerate(AUXILIARY):
        src = u(manager+8+i*4)
        data = bytearray(52*n)
        data[:52*6] = ram[src:src+52*6]
        for row in range(6, n):
            for offset in (0, 12, 24, 36):
                struct.pack_into('<I', data, 52*row+offset, 0xFFFFFFFF)
        if any(ram[destination:destination+len(data)]):
            raise ValueError('Auxiliary reservation occupied')
        block(destination, bytes(data), 'Copy live six auxiliary records and initialize added rows')
        word(manager+8+i*4, destination, 'Publish expanded auxiliary event/audio array')
    for row in rows[6:]:
        word(row['model']+8, 1, 'Enable added geometry after packet capacity and actor/AI/array setup')
    if creation:
        word(creation+28, 1, 'Mark new actor creation exposed after private initialization')
    # Count is the final publication write: old-six frame stays active until it.
    word(six.COUNT, n, 'Publish configured actor count only after every context/pointer/array is ready')
    return {'serial': SERIAL, 'crc': CRC, 'status': 'CONFIGURED ACTOR PUBLICATION; REVIEW BEFORE LIVE USE',
            'source_ram': str(Path(source).resolve()), 'config': config, 'blocks': blocks,
            'support': support, 'limitations': ['Live stability, total render capacity, match victory, and sixth roster resources remain separate work.']}


def verify_packet_capacity(ram, manager):
    """Require the successful native packet-arena publication, not a feature label."""
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    if (u(packets.CONTROL) != 5 or u(packets.CONTROL+8) != 2
            or u(packets.CONTROL+12) != packets.SIZE
            or u(packets.CONTROL+56) != manager):
        raise ValueError('Both expanded packet arenas must complete publication for this actor manager')
    capacity = u(packets.CAPACITY)
    if capacity < packets.SIZE:
        raise ValueError('Native graphics packet capacity is below4MiB')
    ranges = []
    for index in range(2):
        base, end = u(packets.BASES+index*4), u(packets.ENDS+index*4)
        if (base != u(packets.CONTROL+24+index*4) or end-base != capacity
                or base < 0x02000000 or end > 0x06000000 or base & 63):
            raise ValueError('Native packet arena pointers differ from the successful expansion')
        ranges.append((base, end))
    if max(p[0] for p in ranges) < min(p[1] for p in ranges):
        raise ValueError('Expanded graphics packet arenas overlap')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    capture = sub.add_parser('capture')
    capture.add_argument('--count', type=int, required=True)
    capture.add_argument('--cpu-mask', type=integer, required=True)
    install = sub.add_parser('install')
    install.add_argument('--config', type=Path, required=True)
    activate = sub.add_parser('activate')
    activate.add_argument('--installation', type=Path, required=True)
    activate.add_argument('--support', type=Path, required=True)
    for command in (capture, install, activate):
        command.add_argument('--ram', type=Path, required=True)
        command.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    if args.command == 'capture':
        result = capture_config(args.ram, args.count, args.cpu_mask)
    elif args.command == 'install':
        result = build_install(args.ram, json.loads(args.config.read_text()))
    else:
        result = build_activation(args.ram, json.loads(args.installation.read_text()), json.loads(args.support.read_text()))
    args.out.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(f"{args.out}: {len(result.get('blocks', []))} guarded blocks")
