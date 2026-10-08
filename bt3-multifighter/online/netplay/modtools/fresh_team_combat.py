"""Direct, dormant combat installation for a fresh native match and hidden extras.

There is no dependency on the B/C/D code installed by earlier experiments.
Actor configuration is shared with fresh_team_ai; actual activation is separate.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from types import FunctionType, SimpleNamespace

import battle_mode_policy as policy
from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
import fresh_team_ai
import team_targets as selectors
import team_targets6 as targets
import contact_matrix as matrix
import hitstop12
import distinct_ai
import virtual_role_queries

COUNT, PHYSICAL, LOGICAL = 0x07368000, 0x07368200, 0x07368600
RESOLVER, COLLISION, PROJECTILE = 0x07368800, 0x07369000, 0x0736A000
RECORD, RECORD_INNER, BEGIN, NATIVE_TAIL = 0x0736B000, 0x0736B200, 0x0736B500, 0x0736B800
HITSTOP, HITSTOP_COUNT = 0x0736C000, 0x0736C400
TABLE, POINTERS, MODE, PAIR = 0xD8000, 0xD8040, 0xD8080, 0xC4000
MATRIX_CONTROL, MATRIX_ROWS = 0xD1000, 0xD1040
ARENA_END = 0x07380000
ACTORS, MODELS = A(0x2FEB14), A(0x31C640)


def rebound(function, **values):
    context = dict(function.__globals__); context.update(values)
    return FunctionType(function.__code__, context, function.__name__, function.__defaults__, function.__closure__)


def gate(a, fail):
    """t0..t2 only; t2 returns active count. Count is the final publication gate.

    The range test admits MIN_ACTORS..MAX_ACTORS from battle_mode_policy. It is
    inlined into dozens of guest programs, so it is kept to exactly the same
    three words it has always been; only the immediate follows the capacity.
    """
    a.li(8, MODE); a.lw(9, 8); a.branch(4, 9, 0, fail)
    a.lw(10, 8, 4); a.lw(9, 8, 12); a.branch(5, 10, 9, fail)
    policy.emit_actor_count(a, 10, fail, scratch=9)
    a.lw(9, 8, 8); a.lw(8, 28, -22364); a.branch(5, 8, 9, fail)
    a.branch(4, 8, 0, fail)
    a.lw(9, 8); a.addiu(8, 0, 2); a.branch(5, 8, 9, fail)


def alias_gate(a, fail):
    # Initialization intentionally runs with public mode disabled/count two.
    a.li(8, MODE); a.lw(9, 8, 8); a.lw(10, 28, -22364)
    a.branch(4, 9, 0, fail); a.branch(5, 9, 10, fail)
    a.li(8, PAIR)
    for offset in (0, 4):
        a.lw(9, 8, offset); a.branch(4, 9, 0, fail)


def save_temporaries(a):
    a.addiu(29, 29, -0x20)
    for i, register in enumerate((8, 9, 10)): a.i(63, register, 29, i*8)


def restore_temporaries(a):
    for i, register in enumerate((8, 9, 10)): a.i(55, register, 29, i*8)
    a.addiu(29, 29, 0x20)


def count_code():
    a = Assembler(COUNT); save_temporaries(a); gate(a, 'native')
    a.move(2, 10); restore_temporaries(a); a.jr()
    a.label('native'); restore_temporaries(a)
    # Native count entry has JR as its second instruction; replay all three.
    a.lw(3, 28, -22364); a.emit(0x03E00008); a.lw(2, 3)
    return a.finish()


def getter_code(base, entry, logical=False, fused=True):
    """Hook for native 1DC178 (physical index) or 1DC1A0 (logical id) getters.

    The native logical getter loops over 1DC168/1DC178, which are the COUNT and
    PHYSICAL hooks here. While the count is published and no pair alias is live
    those hooks only answer from POINTERS, so the fused logical path scans
    POINTERS directly and leaves the native loop's registers: v0 the actor or 0,
    v1 the +12 id of the last actor examined, a0 the index reached; t0..t2 are
    restored. Its bound is the gated count in t2, so it follows the capacity the
    install was built for. fused=False emits the earlier bytes, which replay the
    native loop for every lookup; the equivalence tests run against them.
    """
    a = Assembler(base); save_temporaries(a); alias_gate(a, 'physical')
    a.i(11, 9, 4, 2); a.branch(4, 9, 0, 'physical')
    a.r(0, 9, 0, 4, 2); a.r(0x2D, 8, 8, 9); a.lw(2, 8, 8)
    a.branch(4, 2, 0, 'physical'); a.jump('return')
    a.label('physical')
    if not logical:
        gate(a, 'native')
        a.r(0x2B, 9, 4, 10); a.branch(4, 9, 0, 'null')
        a.li(8, POINTERS); a.r(0, 9, 0, 4, 2); a.r(0x2D, 8, 8, 9)
        a.lw(2, 8); a.jump('return')
        a.label('null'); a.move(2, 0)
    elif fused:
        gate(a, 'native')
        # Both pair words live: the physical hook answers roles 0/1 from PAIR.
        a.li(8, PAIR); a.lw(9, 8); a.branch(4, 9, 0, 'scan')
        a.lw(9, 8, 4); a.branch(5, 9, 0, 'native')
        a.label('scan'); a.move(9, 4); a.move(4, 0); a.li(8, POINTERS)
        a.label('next'); a.branch(4, 4, 10, 'null')
        a.lw(2, 8); a.lw(3, 2, 12); a.branch(4, 3, 9, 'return')
        a.addiu(8, 8, 4); a.addiu(4, 4, 1); a.jump('next')
        a.label('null'); a.move(2, 0)
    else:
        a.jump('native')
    a.label('return'); restore_temporaries(a); a.jr()
    a.label('native'); restore_temporaries(a)
    _, _, native = elf_reader(elf_path(ROOT))
    for word in struct.unpack('<2I', native(entry, 8)): a.emit(word)
    a.jump(entry+8)
    return a.finish()


def resolver_code(free_for_all=False):
    a = Assembler(RESOLVER); alias_gate(a, 'global')
    a.lw(9, 8, 8); a.branch(4, 4, 9, 'role0')
    a.lw(9, 8, 12); a.branch(5, 4, 9, 'global')
    a.lw(2, 8, 8); a.lw(3, 8, 16); a.jump('pair_check')
    a.label('role0'); a.lw(2, 8, 12); a.lw(3, 8, 20)
    a.label('pair_check')
    a.branch(4, 2, 0, 'global'); a.li(8, MODE); a.lw(10, 8, 12)
    a.r(0x2B, 9, 3, 10); a.branch(4, 9, 0, 'global')
    a.li(8, POINTERS); a.r(0, 9, 0, 3, 2); a.r(0x2D, 8, 8, 9)
    a.lw(9, 8); a.branch(5, 2, 9, 'global'); a.jr()
    a.label('global'); gate(a, 'native')
    a.li(8, POINTERS); a.move(3, 0)
    a.label('find'); a.lw(2, 8); a.branch(4, 4, 2, 'found')
    a.addiu(8, 8, 4); a.addiu(3, 3, 1); a.r(0x2B, 9, 3, 10)
    a.branch(5, 9, 0, 'find'); a.jump('native')
    a.label('found')
    if free_for_all: a.move(2, 3)
    else: a.i(12, 2, 3, 1)
    a.li(8, TABLE); a.r(0, 9, 0, 3, 2); a.r(0x2D, 8, 8, 9); a.lw(3, 8)
    a.r(0x2B, 9, 3, 10); a.branch(4, 9, 0, 'native')
    if free_for_all: a.branch(4, 3, 2, 'native')
    else: a.i(12, 9, 3, 1); a.branch(4, 9, 2, 'native')
    a.li(8, POINTERS); a.r(0, 9, 0, 3, 2); a.r(0x2D, 8, 8, 9); a.lw(2, 8)
    a.branch(4, 2, 0, 'native'); a.jr()
    a.label('native')
    # Every original selector used self==0 ? native actor1 : native actor0.
    a.lw(3, 4); a.i(11, 3, 3, 1); a.lw(8, 28, -22364); a.lw(2, 8, 4)
    a.branch(4, 3, 0, 'return'); a.addiu(2, 2, 0x1600)
    a.label('return'); a.jr()
    return a.finish()


def scoped_record_code():
    a = Assembler(RECORD); save_temporaries(a); gate(a, 'native')
    restore_temporaries(a); a.jump(RECORD_INNER)
    a.label('native'); restore_temporaries(a); a.jump(NATIVE_TAIL)
    return a.finish()


def begin_code():
    a = Assembler(BEGIN); gate(a, 'call_native')
    a.li(8, MATRIX_CONTROL); a.lw(9, 8, 8); a.addiu(9, 9, 1); a.sw(9, 8, 8)
    a.li(8, MATRIX_ROWS); a.addiu(9, 8, 48)
    a.label('clear'); a.sw(0, 8); a.addiu(8, 8, 4); a.branch(5, 8, 9, 'clear')
    a.label('call_native'); a.jump(COLLISION)
    return a.finish()


def selector_sites():
    old = json.loads((ROOT/'analysis/research_opponent_patches.json').read_text())['patches']
    sites = [(A(int(row['address'], 16)), None) for row in old]
    sites += [(address, destination) for address, _, destination in selectors.MISSING]
    assert len(sites) == len(set(p for p, _ in sites)) == 27
    return sites


def program():
    _, _, native = elf_reader(elf_path(ROOT))
    old = SimpleNamespace(RESOLVER=RESOLVER, COLLISION=matrix.ENTRY, PROJECTILE=A(0x1B00C4),
        MODELS=MODELS, collision_code=lambda: native(matrix.ENTRY, 8),
        projectile_code=lambda: native(A(0x1B00C4), 8))
    common = dict(gate=gate, old=old, RESOLVER=RESOLVER, COLLISION=COLLISION,
                  PROJECTILE=PROJECTILE, TARGETS=PROJECTILE+0x1000)
    collision = rebound(targets.collision_code, **common)(alive=True)
    projectile = rebound(targets.projectile_code, **common)(alive=True)
    record = rebound(matrix.record_code, RECORD=RECORD_INNER, BEGIN=BEGIN,
                     ORIGINAL=NATIVE_TAIL, CONTROL=MATRIX_CONTROL, ROWS=MATRIX_ROWS)()
    tail = native(matrix.PRODUCER, matrix.RESUME-matrix.PRODUCER)
    tail += struct.pack('<2I', (2<<26)|(matrix.RESUME>>2), 0)
    hitstop, _ = rebound(hitstop12.relocated_code, CODE=HITSTOP, COUNT=HITSTOP_COUNT)()
    hitcount = rebound(hitstop12.count_code, COUNT=HITSTOP_COUNT)()
    payloads = [(COUNT, count_code(), 'virtual_actor_getters'),
        (PHYSICAL, getter_code(PHYSICAL, A(0x1DC178)), 'physical_getters'),
        (LOGICAL, getter_code(LOGICAL, A(0x1DC1A0), True), 'virtual_actor_getters'),
        (RESOLVER, resolver_code(), 'pair_local_targets'),
        (COLLISION, collision, 'dead_contact_exclusion'),
        (PROJECTILE, projectile, 'dead_contact_exclusion'),
        (RECORD, scoped_record_code(), 'contact_matrix'), (RECORD_INNER, record, 'contact_matrix'),
        (BEGIN, begin_code(), 'contact_matrix'), (NATIVE_TAIL, tail, 'contact_matrix'),
        (HITSTOP, hitstop, 'hitstop12'), (HITSTOP_COUNT, hitcount, 'hitstop12')]
    ordered = sorted(payloads)
    for (p, data, _), (end, _, _) in zip(ordered, ordered[1:]):
        assert p+len(data) <= end, f'Fresh combat code overlaps at{p:X}'
    assert ordered[-1][0]+len(ordered[-1][1]) < ARENA_END
    for entry, target, feature in ((A(0x1DC168), COUNT, 'virtual_actor_getters'),
            (A(0x1DC178), PHYSICAL, 'physical_getters'), (A(0x1DC1A0), LOGICAL, 'virtual_actor_getters'),
            (matrix.ENTRY, BEGIN, 'contact_matrix'), (A(0x1B00C4), PROJECTILE, 'dead_contact_exclusion'),
            (matrix.PRODUCER, RECORD, 'contact_matrix'), (hitstop12.ENTRY, HITSTOP, 'hitstop12')):
        payloads.append((entry, struct.pack('<2I', (2<<26)|(target>>2), 0), feature))
    for address, destination in selector_sites():
        source = (struct.unpack('<I', native(address, 4))[0]>>21)&31
        assert source in (4, 17)
        data = rebound(selectors.selector_code, RESOLVER=RESOLVER)(address, source, destination)
        payloads.append((address, data, 'pair_local_targets'))
    for address, function in ((distinct_ai.MODEL_BRIDGE, A(0x2499B0)),
            (distinct_ai.HEIGHT_BRIDGE, A(0x204EA0)), (distinct_ai.RADIUS_BRIDGE, A(0x2062F0))):
        payloads.append((address, distinct_ai.role_bridge(address, function), 'native_ai_role_bridges'))
    for address, function, bridge, _ in distinct_ai.CALLS:
        assert struct.unpack('<I', native(address, 4))[0] == (3<<26)|(function>>2)
        payloads.append((address, struct.pack('<I', (3<<26)|(bridge>>2)), 'native_ai_role_bridges'))
    for call, function, bridge, load, base, _ in virtual_role_queries.SPECS:
        assert struct.unpack('<I', native(load, 4))[0] == (35<<26)|(base<<21)|(4<<16)
        assert struct.unpack('<I', native(call, 4))[0] == (3<<26)|(function>>2)
        start = min(call, load); data = bytearray(native(start, 8))
        struct.pack_into('<I', data, call-start, (3<<26)|(bridge>>2))
        payloads.append((start, bytes(data), 'native_ai_role_bridges'))
    return payloads


def support(payloads):
    features = {}
    for address, data, feature in payloads:
        features.setdefault(feature, []).append({'address': address, 'data_hex': data.hex()})
    # Each feature records its executable dependencies, not only the entry jump.
    features['virtual_actor_getters'] += features['physical_getters']
    features['physical_getters'] += [x for x in features['virtual_actor_getters'] if x not in features['physical_getters']]
    features['pair_local_targets'] += features['virtual_actor_getters']
    features['contact_matrix'] += features['dead_contact_exclusion'] + features['pair_local_targets']
    features['dead_contact_exclusion'] += features['pair_local_targets']
    return {'capacity': policy.emitted_actors(), 'features': features}


def build_memory(ram, config, source='<offline-fixture>'):
    if len(ram) != 0x8000000: raise ValueError('Full128MiB EE RAM is required')
    config = fresh_team_ai.normalize(config); n = len(config['actors'])
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    fresh_team_ai.validate_world(ram, u, config)
    _, _, native = elf_reader(elf_path(ROOT))
    payloads = program(); blocks = []
    for address, data, feature in payloads:
        old = ram[address:address+len(data)]
        if 0x100000 <= address < A(0x300000):
            if old != native(address, len(data)): raise ValueError(f'Native hook changed:{address:X}')
        elif any(old): raise ValueError(f'Fresh combat code cave occupied:{address:X}')
        blocks.append(dict(address=address, expected_hex=old.hex(), data_hex=data.hex(), purpose=feature))
    tables = bytearray(0x100)
    struct.pack_into('<12I', tables, 0, *config['targets'], *([0xFFFFFFFF]*(12-n)))
    struct.pack_into('<12I', tables, 0x40, *[r['actor'] for r in config['actors']], *([0]*(12-n)))
    struct.pack_into('<4I', tables, 0x80, 0, 2, config['actor_manager'], n)
    matrix_control = bytearray(0x100); struct.pack_into('<I', matrix_control, 0, 1)
    for address, data, why in ((TABLE, bytes(tables), 'Dormant captured table; public count remains2'),
            (PAIR, bytes(0x40), 'Dormant virtual AI-pair interface'),
            (MATRIX_CONTROL, bytes(matrix_control), 'Scoped twelve-model contact telemetry')):
        old = ram[address:address+len(data)]
        if any(old): raise ValueError(f'Fresh combat control occupied:{address:X}')
        blocks.append(dict(address=address, expected_hex=old.hex(), data_hex=data.hex(), purpose=why))
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()),
        status='FRESH COMBAT CORE INSTALLED DORMANT; PHASE2 REQUIRED BEFORE ACTIVATION',
        config=config, blocks=blocks, support=support(payloads),
        interfaces={'targets': TABLE, 'actors': POINTERS, 'mode': MODE, 'active_count': MODE+4,
                    'captured_manager': MODE+8, 'configured_count': MODE+12, 'pair_control': PAIR},
        remaining=['Private AI install/init and survivor target picker.',
            'KO/tag retention, extra special/clash limits, fallen bodies and camera successor.',
            'Effect index bounds, projectile pool compatibility, statistics/audio/replay guards.',
            'Render capacity verification and safe match teardown or source-state restore.',
            'Activation must publish expanded auxiliary arrays, actor-driven models and count last.'])


def build(source, config):
    return build_memory(read_ram(source), config, source)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path); p.add_argument('--config', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path); x = p.parse_args()
    result = build(x.source, json.loads(x.config.read_text()))
    x.out.write_text(json.dumps(result, indent=2)+'\n'); print(f'{x.out}: {len(result["blocks"])} guarded blocks')
