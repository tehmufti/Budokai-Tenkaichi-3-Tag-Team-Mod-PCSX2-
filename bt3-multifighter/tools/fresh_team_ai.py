"""Offline private AI for a fresh native two-leader match and hidden extras.

The install is dormant. Arm only after verified virtual getter/target/role
bridges are present; publish only after native init and combat support pass.
No old team AI installation or emulator connection is required.
"""
from native_map import A, CRC, SERIAL
import argparse
import json
import struct
from pathlib import Path
from types import FunctionType

from ai_shadow import Assembler, AI_GLOBAL, FRAME_HOOK
from camera_snapshot import published
import distinct_ai
import team_config_ai as configured
import team_pair_ai as pair
import team_six_ai as six
import battle_mode_policy as policy

FRAME, PICKER, INITIALIZE, CONTROL = 0x07330000, 0x07332000, 0x07336000, 0x07338000
DESCRIPTORS, SHADOWS, RECORDS = six.DESCRIPTORS, six.SHADOWS, six.RECORDS
AUXILIARY = (CONTROL+0x800, CONTROL+0xC00)
ARMED, ACTIVE = CONTROL+0x30, CONTROL+0x34
NATIVE_FRAME = A(0x1BB620)
CREATION_HEADER = 0x07358400
INPUT_FREEZE = 0x07361850
INIT_FEATURES = {'virtual_actor_getters', 'pair_local_targets', 'native_ai_role_bridges', 'high_ee_execution'}
COMBAT_FEATURES = INIT_FEATURES | {'physical_getters', 'survivor_targets', 'ko_retention', 'special_limits',
    'model_effect_bounds', 'contact_matrix', 'hitstop12', 'dead_contact_exclusion',
    'render_capacity', 'projectile_pool_compatibility', 'clash_bounds', 'fallen_bodies', 'leader_camera', 'team_defeat',
    'cinematic_contact_isolation', 'throw_limits', 'opponent_events', 'extra_loader_guard', 'los_targets'}


def normalize(config):
    required = {'physical_id', 'actor', 'model_id', 'model', 'dataset', 'team', 'cpu'}
    rows = []
    for row in config['actors']:
        if set(row) != required or not isinstance(row.get('cpu'), bool):
            raise ValueError('Each actor needs explicit identity/model/dataset/team and boolean CPU assignment')
        rows.append({k: v if k == 'cpu' else configured.integer(v) for k, v in row.items()})
    n = len(rows)
    if not policy.MIN_ACTORS <= n <= policy.MAX_ACTORS:
        raise ValueError(f'Fresh mode supports {policy.MIN_ACTORS}..{policy.MAX_ACTORS} fighters')
    for i, row in enumerate(rows):
        if row['physical_id'] != i or row['team'] != i & 1 or not 0 <= row['model_id'] < 12:
            raise ValueError('Physical IDs must be ordered by alternating teams and use registered model IDs 0..11')
    for key in ('actor', 'model_id', 'model'):
        if len({row[key] for row in rows}) != n:
            raise ValueError(f'Every fighter needs a distinct {key}')
    if configured.integer(config.get('preserve_count', 2)) != 2:
        raise ValueError('Fresh mode preserves the two native leaders')
    targets = [configured.integer(x) for x in config.get('targets', default_targets(n))]
    if len(targets) != n or any(not 0 <= j < n or (i & 1) == (j & 1) for i, j in enumerate(targets)):
        raise ValueError('Each initial target must identify an opposing fighter')
    result = {'actors': rows, 'targets': targets, 'preserve_count': 2}
    for key in ('actor_manager', 'ai_manager', 'creation_header'):
        if key not in config:
            raise ValueError(f'Explicit captured {key} is required')
        result[key] = configured.integer(config[key])
        if not 0x100000 <= result[key] < 0x8000000-0x1000:
            raise ValueError(f'Invalid captured {key}')
    return result


def default_targets(n):
    # Physical IDs alternate between teams, so XOR1 selects the same roster
    # slot on the other side. Odd diagnostic capacities fall back to its leader.
    return tuple((i ^ 1) if (i ^ 1) < n else ((i & 1) ^ 1) for i in range(n))


def rebind(function, **values):
    context = dict(function.__globals__)
    context.update(values)
    return FunctionType(function.__code__, context, function.__name__, function.__defaults__, function.__closure__)


def initializer(n):
    return rebind(configured.initializer, INITIALIZE=INITIALIZE, CONTROL=CONTROL,
                  DESCRIPTORS=DESCRIPTORS, RECORDS=RECORDS)(n, preserve=2)


def frame_stub(n, free_for_all=False):
    a = Assembler(FRAME)
    # Dormant installation and changed worlds take the native entry directly.
    a.load_address(8, CONTROL)
    a.mem(35, 2, 8, 0x30)
    a.branch(2, 0, 'fallback'); a.nop()
    for offset, gp_offset in ((0x28, -22364), (0x2C, -0x5760)):
        a.mem(35, 2, 8, offset); a.mem(35, 3, 28, gp_offset)
        a.branch(2, 3, 'fallback', not_equal=True); a.nop()
    a.load_address(8, pair.CONTROL)
    a.mem(35, 2, 8, 0); a.branch(2, 0, 'fallback'); a.nop()
    a.mem(35, 2, 8, 4); a.branch(2, 0, 'fallback', not_equal=True); a.nop()
    a.addiu(29, 29, -0x60)
    saved = [(16+i, i*8) for i in range(8)] + [(31, 0x40)]
    for register, offset in saved: a.mem(63, register, 29, offset)
    a.load_address(8, CONTROL); a.mem(35, 9, 8, 0)
    a.branch(9, 0, 'initialized', not_equal=True); a.nop()
    a.jump(INITIALIZE, link=True); a.nop()
    a.label('initialized')
    a.load_address(8, CONTROL)
    for offset, expected in ((0, 5), (4, n-2), (0x20, n)):
        a.mem(35, 9, 8, offset); a.addiu(10, 0, expected)
        a.branch(9, 10, 'restore_fallback', not_equal=True); a.nop()
    a.mem(35, 9, 8, 0x34); a.branch(9, 0, 'restore_fallback'); a.nop()
    a.mem(35, 9, 8, 0x38); a.branch(9, 0, 'restore_fallback'); a.nop()
    a.mem(35, 9, 9, 28); a.branch(9, 0, 'restore_fallback'); a.nop()
    a.load_address(8, six.MODE)
    a.mem(35, 9, 8, 0); a.branch(9, 0, 'restore_fallback'); a.nop()
    a.mem(35, 9, 8, 4); a.addiu(10, 0, n)
    a.branch(9, 10, 'restore_fallback', not_equal=True); a.nop()
    a.mem(35, 9, 8, 12)
    a.branch(9, 10, 'restore_fallback', not_equal=True); a.nop()
    a.mem(35, 9, 8, 8); a.mem(35, 10, 28, -22364)
    a.branch(9, 10, 'restore_fallback', not_equal=True); a.nop()
    for i in range(n):
        a.load_address(8, DESCRIPTORS[i]); a.mem(35, 9, 8, 0)
        a.load_address(8, six.POINTERS+i*4); a.mem(35, 10, 8, 0)
        a.branch(9, 10, 'restore_fallback', not_equal=True); a.nop()
    a.load_address(16, pair.CONTROL)
    a.mem(35, 17, 28, -0x5760); a.mem(35, 18, 17, 0xA50)
    for register, descriptor in ((21, DESCRIPTORS[0]), (22, DESCRIPTORS[1])):
        a.load_address(8, descriptor); a.mem(35, register, 8, 0)
    for register, offset in ((21, 0x48), (22, 0x4C)):
        a.mem(35, 8, register, 0x1278); a.mem(43, 8, 29, offset)
        a.mem(43, 0, register, 0x1278)
    a.jump(NATIVE_FRAME, link=True); a.nop()
    for register, offset in ((21, 0x48), (22, 0x4C)):
        a.mem(35, 8, 29, offset); a.mem(43, 8, register, 0x1278)
    a.mem(35, 8, 17, 0xA50); a.branch(8, 18, 'return'); a.nop()
    a.jump(PICKER, link=True); a.nop()
    emit_slice = rebind(six.emit_slice, CONTROL=CONTROL)
    for i in range(n): emit_slice(a, i, free_for_all=free_for_all)
    a.load_address(9, CONTROL); a.mem(35, 8, 9, 0x10)
    a.addiu(8, 8, 1); a.mem(43, 8, 9, 0x10)
    a.label('return')
    for register, offset in saved: a.mem(55, register, 29, offset)
    a.emit(0x03E00008); a.addiu(29, 29, 0x60)
    a.label('restore_fallback')
    for register, offset in saved: a.mem(55, register, 29, offset)
    a.addiu(29, 29, 0x60)
    a.label('fallback'); a.jump(NATIVE_FRAME); a.nop()
    return a.finish()


def program(n, targets=None, free_for_all=False):
    if not policy.MIN_ACTORS <= n <= policy.MAX_ACTORS:
        raise ValueError(f'Fresh count must be {policy.MIN_ACTORS}..{policy.MAX_ACTORS}')
    picker = rebind(six.picker_stub, N=n, DEFAULTS=tuple(targets or default_targets(n)),
                    PICKER=PICKER, CONTROL=CONTROL)(free_for_all=free_for_all)
    payloads = [(FRAME, frame_stub(n, free_for_all=free_for_all)), (PICKER, picker), (INITIALIZE, initializer(n))]
    for (start, data), end in zip(payloads, (PICKER, INITIALIZE, CONTROL)):
        if start+len(data) > end: raise ValueError('Fresh AI code reservations overlap')
    return {'segments': [{'address': p, 'data_hex': b.hex()} for p, b in payloads], 'count': n}


def read_source(source):
    ram = published(source)  # a preparation's in-memory stage image
    if ram is None: ram = Path(source).read_bytes()
    if len(ram) != 0x8000000: raise ValueError('Requires complete 128 MiB EE RAM')
    return ram, lambda p: struct.unpack_from('<I', ram, p)[0]


def validate_world(ram, u, config):
    manager, ai = config['actor_manager'], config['ai_manager']
    if u(pair.ACTOR_GLOBAL) != manager or u(AI_GLOBAL) != ai or u(manager) != 2 or u(pair.CONTROL+4):
        raise ValueError('Native two-actor manager, original AI manager and inactive aliases required')
    if u(INPUT_FREEZE) != 1 or u(INPUT_FREEZE+4) != manager:
        raise ValueError('Captured fresh preparation must hold both leader inputs until activation')
    rows = config['actors']
    if u(manager+4) != rows[0]['actor'] or rows[1]['actor'] != rows[0]['actor']+0x1600:
        raise ValueError('Leader pointers must match the native two-actor array')
    header = config['creation_header']
    if u(header) != 20 or u(header+8) < len(rows)-2 or u(header+12) != manager or u(header+28):
        raise ValueError('Fresh hidden actor creation must be complete and unpublished')
    for i, row in enumerate(rows):
        actor, model, dataset = row['actor'], row['model'], row['dataset']
        for value, size in ((actor, 0x1600), (model, 0x1680), (dataset, 4)):
            if not 0x100000 <= value <= len(ram)-size: raise ValueError('Invalid actor/model/dataset pointer')
        if actor % 16 or u(actor) != i or u(actor+8) != i&1 or u(actor+12) != row['model_id']:
            raise ValueError(f'Actor {i} identity/team/model changed')
        if u(actor+0x994) >= 5: raise ValueError('Native roster slot must remain0..4')
        if u(A(0x31C640)+row['model_id']*4) != model or u(model+16) != row['model_id'] or u(model+2356) != dataset:
            raise ValueError(f'Actor {i} registered model/dataset changed')
        if u(model+4) != 1 or u(model+8) != int(i < 2) or u(actor+0x1278):
            raise ValueError('All CPUs must be off; extra models must remain initialized and hidden')
    return manager, ai


def support_matches(ram, support, required, count):
    if configured.integer(support.get('capacity', 0)) < count:
        raise ValueError('Supporting engine capacity is insufficient')
    features = support.get('features', {})
    if not isinstance(features, dict) or not required <= set(features):
        raise ValueError('Required support features need explicit full code payloads')
    for name in required:
        if not features[name]: raise ValueError(f'Empty supporting feature: {name}')
        for entry in features[name]:
            address, data = configured.integer(entry['address']), bytes.fromhex(entry['data_hex'])
            if address < 0 or not data or ram[address:address+len(data)] != data:
                raise ValueError(f'Support code for {name} differs at{address:08X}')
    # These six narrow bridges have already been audited for virtual-role input.
    for address, _, bridge, _ in distinct_ai.CALLS:
        if ram[address:address+4] != struct.pack('<I', (3<<26)|(bridge>>2)):
            raise ValueError('Missing reviewed native initialization role bridge call')
    for address, native in ((distinct_ai.MODEL_BRIDGE, A(0x2499B0)),
                            (distinct_ai.HEIGHT_BRIDGE, A(0x204EA0)), (distinct_ai.RADIUS_BRIDGE, A(0x2062F0))):
        code = distinct_ai.role_bridge(address, native)
        if ram[address:address+len(code)] != code: raise ValueError('Narrow role bridge body changed')


def block(ram, address, data, purpose):
    old = ram[address:address+len(data)]
    if len(old) != len(data): raise ValueError('Patch extends beyond EE RAM')
    return {'address': address, 'expected_hex': old.hex(), 'data_hex': data.hex(), 'purpose': purpose}


def manifest(source, config, blocks, status):
    return {'serial': SERIAL, 'crc': CRC, 'source_ram': str(Path(source).resolve()),
            'config': config, 'control': CONTROL, 'blocks': blocks, 'status': status}


def build_install(source, config):
    config = normalize(config); rows, n = config['actors'], len(config['actors'])
    ram, u = read_source(source); manager, ai = validate_world(ram, u, config)
    if u(FRAME_HOOK) != (3<<26)|(NATIVE_FRAME>>2): raise ValueError('Expected unmodified native AI frame call')
    if u(six.MODE) or u(six.COUNT) not in (0, 2): raise ValueError('Fresh install cannot replace an exposed team')
    if any(ram[FRAME:CONTROL+0x1000]) or any(ram[0x07000000:0x0700D000]):
        raise ValueError('Fresh code/private context reservations must be empty')
    original = ram[ai:ai+0xA60]
    if any(ai <= value < ai+0xA60 for value in struct.unpack('<664I', original)):
        raise ValueError('Native AI contains internal pointers that require relocation before cloning')
    for role in (0, 1):
        own = ai+0x10+role*0x520
        if u(own) != role or u(own+24) != rows[role]['dataset'] or u(own+36)&1:
            raise ValueError('Native leader AI must borrow the corresponding actual model dataset')
    payloads = []
    for i, row in enumerate(rows):
        actor, mid, model, data = (row[key] for key in ('actor', 'model_id', 'model', 'dataset'))
        desc = struct.pack('<12I', actor, SHADOWS[i], i&1, 0, 0, i,
                           DESCRIPTORS[(i&1)^1], 0, mid, model, data, ai)
        record = struct.pack('<8I', actor, mid, model, data, SHADOWS[i], 0, 0, 0)
        payloads += [(DESCRIPTORS[i], desc), (RECORDS[i], record), (SHADOWS[i], original)]
    generated = program(n, config['targets'])
    payloads += [(entry['address'], bytes.fromhex(entry['data_hex'])) for entry in generated['segments']]
    control = bytearray(64)
    struct.pack_into('<7I', control, 0x20, n, 2, manager, ai, 0, 0, config['creation_header'])
    payloads.append((CONTROL, bytes(control)))
    blocks = [block(ram, p, data, 'Dormant fresh private AI code/context') for p, data in payloads]
    blocks.append(block(ram, FRAME_HOOK, struct.pack('<I', (3<<26)|(FRAME>>2)), 'Dormant frame dispatch; native fallback'))
    result = manifest(source, config, blocks, 'DORMANT FRESH AI; CPU, MODELS AND PUBLIC COUNT UNCHANGED')
    result.update(generated)
    result['support'] = {'capacity': n, 'features': {'survivor_targets':
        [entry for entry in generated['segments'] if entry['address'] in (FRAME, PICKER)] +
        [{'address': FRAME_HOOK, 'data_hex': struct.pack('<I', (3<<26)|(FRAME>>2)).hex()}]}}
    result['requirements'] = ['Arm only after reviewed alias/target/role bridge code is verified.',
        'Native initialization completes extras2..N-1; leaders private contexts preserve native state.',
        'Activation separately verifies combat support and publishes the count last.']
    return result


def verify_installed(ram, u, installation):
    config = normalize(installation['config']); n = len(config['actors'])
    validate_world(ram, u, config)
    if u(FRAME_HOOK) != (3<<26)|(FRAME>>2) or u(CONTROL+0x20) != n or u(CONTROL+0x24) != 2:
        raise ValueError('Fresh frame/count setup differs')
    for offset, key in ((0x28, 'actor_manager'), (0x2C, 'ai_manager'), (0x38, 'creation_header')):
        if u(CONTROL+offset) != config[key]: raise ValueError('Captured fresh control identity differs')
    for entry in program(n, config['targets'])['segments']:
        p, data = entry['address'], bytes.fromhex(entry['data_hex'])
        if ram[p:p+len(data)] != data: raise ValueError('Fresh AI program changed')
    if u(six.MODE) or u(six.COUNT) != 2 or u(ACTIVE):
        raise ValueError('Fresh team must remain unpublished')
    if u(six.MODE+12) != n or u(six.CAPTURED_MANAGER) != config['actor_manager']:
        raise ValueError('Fresh combat core configuration differs from the private AI')
    for i, row in enumerate(config['actors']):
        expected = (row['actor'], SHADOWS[i], i&1)
        if tuple(u(DESCRIPTORS[i]+o) for o in (0, 4, 8)) != expected:
            raise ValueError('Private descriptor changed')
        if u(six.POINTERS+i*4) != row['actor']:
            raise ValueError('Dormant core pointer table must identify every hidden actor before initialization')
    return config


def build_arm(source, installation, support):
    ram, u = read_source(source); config = verify_installed(ram, u, installation)
    if u(CONTROL) or u(ARMED): raise ValueError('Fresh initialization is already armed or attempted')
    support_matches(ram, support, INIT_FEATURES, len(config['actors']))
    blocks = [block(ram, pair.CONTROL, struct.pack('<I', 1), 'Enable verified virtual-pair control'),
              block(ram, ARMED, struct.pack('<I', 1), 'Arm hidden native AI initialization only')]
    return manifest(source, config, blocks, 'ARMED HIDDEN INITIALIZATION; EXPOSURE AND CPU REMAIN OFF')


def build_activation(source, installation, support):
    ram, u = read_source(source); config = verify_installed(ram, u, installation)
    rows, n = config['actors'], len(config['actors'])
    support_matches(ram, support, COMBAT_FEATURES, n)
    if u(CONTROL) != 5 or u(CONTROL+4) != n-2 or not u(ARMED) or not u(pair.CONTROL):
        raise ValueError('Every extra context must complete native initialization before publication')
    blocks = []
    def word(address, value, why): blocks.append(block(ram, address, struct.pack('<I', value), why))
    for i, row in enumerate(rows):
        own = SHADOWS[i]+0x10+(i&1)*0x520
        if u(own) != i&1 or u(own+24) != row['dataset'] or u(own+36)&1:
            raise ValueError('Private own context does not borrow the correct dataset')
        if i >= 2 and (u(RECORDS[i]+20) != row['dataset'] or u(RECORDS[i]+28)&1):
            raise ValueError('Extra native initialization verification failed')
        word(six.POINTERS+i*4, row['actor'], 'Publish captured physical pointer')
        word(six.TARGETS+i*4, config['targets'][i], 'Publish initial opposing target')
        word(row['actor']+0x1278, int(row['cpu']), 'Apply explicit human/CPU assignment')
        for offset in (0x127C, 0x1280, 0x1284): word(row['actor']+offset, 0, 'Clear pre-activation input')
        if i >= 2:
            word(row['model']+3184, 1, 'Actor drives its registered model pose')
            word(row['model']+3188, 0, 'Stop generic preview pose updates')
    manager = config['actor_manager']
    for index, destination in enumerate(AUXILIARY):
        source_pointer = u(manager+8+index*4)
        if not 0x100000 <= source_pointer <= len(ram)-104: raise ValueError('Invalid native auxiliary source')
        data = bytearray(52*n); data[:104] = ram[source_pointer:source_pointer+104]
        for i in range(2, n):
            for offset in (0, 12, 24, 36): struct.pack_into('<I', data, 52*i+offset, 0xFFFFFFFF)
        if any(ram[destination:destination+len(data)]): raise ValueError('Fresh auxiliary reservation occupied')
        blocks.append(block(ram, destination, bytes(data), 'Preserve native two rows and initialize extra event rows'))
        word(manager+8+index*4, destination, 'Publish expanded auxiliary rows')
    word(six.CAPTURED_MANAGER, manager, 'Publish captured actor-manager identity')
    for row in rows[2:]: word(row['model']+8, 1, 'Enable initialized extra geometry')
    word(config['creation_header']+28, 1, 'Expose completed fresh creation')
    word(six.MODE, 1, 'Enable verified team engine support')
    word(ACTIVE, 1, 'Enable private slices after the remaining count gate passes')
    word(INPUT_FREEZE, 0, 'Release fresh preparation input hold')
    word(six.COUNT, n, 'Publish actor count last')
    return manifest(source, config, blocks, 'FRESH TEAM ACTIVATION; ACTOR COUNT PUBLISHED LAST')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('install', 'arm', 'activate'))
    parser.add_argument('--ram', required=True, type=Path)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--installation', type=Path)
    parser.add_argument('--support', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    if args.stage == 'install':
        if not args.config: parser.error('--config is required for install')
        result = build_install(args.ram, json.loads(args.config.read_text()))
    else:
        if not args.installation or not args.support: parser.error('--installation and --support are required')
        builder = build_arm if args.stage == 'arm' else build_activation
        result = builder(args.ram, json.loads(args.installation.read_text()), json.loads(args.support.read_text()))
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(f"{args.out}: {len(result['blocks'])} guarded blocks")
