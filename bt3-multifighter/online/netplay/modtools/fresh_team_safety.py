"""Fresh captured-team safety ports; native fallbacks and dormant publication.

This installs bounds before exposing extras. It does not reclaim experimental
allocations or promise reuse of the patched process for a subsequent match.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
import fresh_team_combat as core
import fresh_team_ai
import afterimage_bounds
import aura_index_guard
import aux_effect_bounds
import aux_trail_lists
import ground_effect_bounds
import extra_effect_suppression as cosmetics
import projectile_pool_guard
import special_projectile_pool_guard
import clash_bounds
import team_defeat
import cinematic_contact_guard
import battle_mode_policy as policy

CONTROL = 0x0738F000
EFFECTS, LIFE0, LIFE1 = 0x07383000, 0x07384000, 0x07384400
OWNED = ((A(0x1E80C0), 0x07380000, 0, 'ko_retention'),
         (A(0x203B18), 0x07380400, 0, 'ko_retention'),
         (A(0x203E00), 0x07380800, 2, 'special_limits'),
         (A(0x204128), 0x07380C00, 2, 'special_limits'),
         (A(0x1C1158), 0x07381000, 2, 'model_effect_bounds'),
         (A(0x1D8330), 0x07381400, 2, 'model_effect_bounds'),
         (A(0x1D8388), 0x07381800, 2, 'model_effect_bounds'),
         (A(0x1D8470), 0x07381C00, 2, 'model_effect_bounds'))
SCALARS = ((A(0x1296B8), 0x07382000, 2, True),
           (A(0x265850), 0x07382200, 6, False), (A(0x265970), 0x07382400, 6, False),
           (A(0x265B18), 0x07382600, 6, False), (A(0x265F88), 0x07382800, 2, False))


def native_tail(a, entry, original):
    for word in struct.unpack('<2I', original):
        assert word>>26 not in (1, 2, 3, 4, 5, 6, 7, 20, 21)
        a.emit(word)
    a.jump(entry+8)


def owned_code(entry, cave, first, original):
    a = Assembler(cave); core.save_temporaries(a); core.gate(a, 'native')
    a.li(8, core.POINTERS); a.r(0, 9, 0, 10, 2); a.r(0x2D, 9, 9, 8)
    a.addiu(8, 8, first*4)
    a.label('scan'); a.branch(4, 8, 9, 'native')
    a.lw(10, 8); a.branch(4, 4, 10, 'blocked'); a.addiu(8, 8, 4); a.jump('scan')
    a.label('blocked'); core.restore_temporaries(a); a.move(2, 0); a.jr()
    a.label('native'); core.restore_temporaries(a); native_tail(a, entry, original)
    result = a.finish(); assert len(result) < 0x400; return result


def scalar_code(entry, cave, limit, event, original):
    a = Assembler(cave); core.save_temporaries(a); core.gate(a, 'native')
    a.i(11, 8, 4, limit); a.branch(5, 8, 0, 'native')
    core.restore_temporaries(a)
    if event: a.i(11, 2, 5, 90)
    else: a.move(2, 0)
    a.jr()
    a.label('native'); core.restore_temporaries(a); native_tail(a, entry, original)
    result = a.finish(); assert len(result) < 0x200; return result


def effects_code(original):
    a = Assembler(EFFECTS)
    core.save_temporaries(a); core.gate(a, 'native')
    a.i(11, 8, 4, 12); a.branch(4, 8, 0, 'missing')
    a.i(11, 8, 5, 10); a.branch(4, 8, 0, 'missing')
    a.li(8, core.POINTERS); a.move(3, 0)
    a.label('scan'); a.lw(2, 8); a.branch(4, 2, 0, 'next')
    a.lw(2, 2, 12); a.branch(4, 2, 4, 'found')
    a.label('next'); a.addiu(3, 3, 1); a.addiu(8, 8, 4)
    a.branch(5, 3, 10, 'scan')
    a.label('missing'); core.restore_temporaries(a); a.move(2, 0); a.jr()
    a.label('found')
    a.i(12, 3, 3, 1)
    # Arithmetic below is native1722C0, with the resolved side replacing a0.
    a.r(0, 2, 0, 3, 1); a.r(0x2D, 2, 2, 3); a.r(0, 2, 0, 2, 4)
    core.restore_temporaries(a)
    a.lw(6, 28, -22568); a.r(0, 5, 0, 5, 2); a.lw(3, 6, 4)
    a.r(0x2D, 3, 3, 2); a.r(0x2D, 3, 3, 5)
    a.emit(0x03E00008); a.lw(2, 3, 8)
    a.label('native'); core.restore_temporaries(a); native_tail(a, A(0x1722C0), original)
    return a.finish()


def lifecycle_code(entry, cave, original, config, trail_clear=True):
    """trail_clear=False is the beta.36 emission (extra_cell_absorption accepts it as its predecessor in
    captures prepared before beta.37)."""
    a = Assembler(cave); a.addiu(29, 29, -0x20)
    for i, reg in enumerate((8, 9, 10, 11)): a.i(63, reg, 29, i*8)
    a.li(8, CONTROL); a.lw(9, 8, 4); a.lw(10, 28, -22364)
    a.branch(4, 9, 0, 'native'); a.branch(5, 9, 10, 'native')
    # Restore actual native heap pointers before native code frees/resets them.
    for offset, backup in ((8, 8), (12, 12)):
        a.lw(11, 8, backup); a.sw(11, 10, offset)
    for address in (core.MODE, core.PAIR, core.PAIR+4, core.PAIR+8, core.PAIR+12,
                    fresh_team_ai.ARMED, fresh_team_ai.ACTIVE, fresh_team_ai.INPUT_FREEZE):
        a.li(8, address); a.sw(0, 8)
    a.li(8, core.MODE+4); a.addiu(9, 0, 2); a.sw(9, 8)
    a.li(8, config['creation_header']); a.sw(0, 8, 20); a.sw(0, 8, 28)
    a.addiu(9, 0, 250); a.sw(9, 8)
    for i in range(len(config['actors'])-2):
        a.li(8, 0x07358000+i*0x80); a.sw(9, 8)
        a.addiu(10, 0, -1); a.sw(10, 8, 8)
    for row in config['actors'][2:]:
        a.li(8, row['model']); a.sw(0, 8, 8)
    # Forget the captured trail manager and the extras' trail lists: a manager the next battle
    # creates at the same address must never inherit lists that point into this one's pool.
    if trail_clear:
        a.li(8, aux_trail_lists.CONTROL); a.sw(0, 8, aux_trail_lists.MGR)
        for k in range(2*aux_trail_lists.OWNERS):
            a.sw(0, 8, aux_trail_lists.HEADS+4*k)
    a.label('native')
    for i, reg in enumerate((8, 9, 10, 11)): a.i(55, reg, 29, i*8)
    a.addiu(29, 29, 0x20); native_tail(a, entry, original)
    result = a.finish(); assert len(result) < 0x400; return result


def cosmetic_predicate(clear=False):
    # These trackers remain two rows during creation and teardown as well.
    # Reuse the reviewed cleanup predicate for both public commands and clears.
    code = core.rebound(cosmetics.predicate_code,
                        CLEAR_PREDICATE=cosmetics.CLEAR_PREDICATE if clear else cosmetics.PREDICATE)(True)
    return code


def component(module, virtual, source, **overrides):
    return core.rebound(module.build, read_ram=lambda _: virtual, **overrides)(source)


def build_memory(ram, config, source='<offline-fixture>', include_camera=True):
    config = fresh_team_ai.normalize(config)
    if len(ram) != 0x8000000: raise ValueError('Full128MiB EE RAM is required')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager, _ = fresh_team_ai.validate_world(ram, u, config)
    _, _, native = elf_reader(elf_path(ROOT))
    virtual = bytearray(ram)
    # Bind only actual caller-validated actor pointers. No live state is changed.
    for i, row in enumerate(config['actors']):
        struct.pack_into('<I', virtual, core.POINTERS+4*i, row['actor'])
    struct.pack_into('<4I', virtual, core.MODE, 0, 2, manager, len(config['actors']))
    blocks, features = [], {}
    controls = set()
    def add(p, data, feature, data_block=False):
        old = ram[p:p+len(data)]
        if 0x100000 <= p < A(0x300000):
            if old != native(p, len(data)): raise ValueError(f'Native safety hook changed:{p:X}')
        elif any(old): raise ValueError(f'Fresh safety reservation occupied:{p:X}')
        blocks.append(dict(address=p, expected_hex=old.hex(), data_hex=data.hex(), purpose=feature))
        if data_block: controls.add(p)
        else: features.setdefault(feature, []).append(dict(address=p, data_hex=data.hex()))
    for entry, cave, first, feature in OWNED:
        add(cave, owned_code(entry, cave, first, native(entry, 8)), feature)
        add(entry, struct.pack('<2I', (2<<26)|(cave>>2), 0), feature)
    for entry, cave, limit, event in SCALARS:
        add(cave, scalar_code(entry, cave, limit, event, native(entry, 8)), 'model_effect_bounds')
        add(entry, struct.pack('<2I', (2<<26)|(cave>>2), 0), 'model_effect_bounds')
    add(EFFECTS, effects_code(native(A(0x1722C0), 8)), 'model_effect_bounds')
    add(A(0x1722C0), struct.pack('<2I', (2<<26)|(EFFECTS>>2), 0), 'model_effect_bounds')
    for entry, cave in ((A(0x1C2810), LIFE0), (A(0x1C2858), LIFE1)):
        add(cave, lifecycle_code(entry, cave, native(entry, 8), config), 'ko_retention')
        add(entry, struct.pack('<2I', (2<<26)|(cave>>2), 0), 'ko_retention')
    add(CONTROL, struct.pack('<8I', 1, manager, u(manager+8), u(manager+12),
                            config['creation_header'], len(config['actors']), 0, 0), 'safety_capture', True)
    groups = ((afterimage_bounds, 'model_effect_bounds'), (aura_index_guard, 'model_effect_bounds'),
              (aux_effect_bounds, 'model_effect_bounds'), (ground_effect_bounds, 'model_effect_bounds'),
              (aux_trail_lists, 'model_effect_bounds'),
              (projectile_pool_guard, 'projectile_pool_compatibility'),
              (special_projectile_pool_guard, 'projectile_pool_compatibility'),
              (cosmetics, 'model_effect_bounds'))
    trails = None
    for module, feature in groups:
        overrides = {'predicate_code': cosmetic_predicate} if module is cosmetics else {}
        result = component(module, virtual, source, **overrides)
        if module is aux_trail_lists: trails = result
        data_addresses = {getattr(module, 'CONTROL', -1)}
        if module is special_projectile_pool_guard:
            data_addresses = {f['control'] for f in module.FAMILIES}
        for b in result['blocks']:
            add(b['address'], bytes.fromhex(b['data_hex']), feature, b['address'] in data_addresses)
    leader = config['actors'][0]['actor']
    clash_data = struct.pack('<9I', 1, manager, leader, config['actors'][1]['actor'],
                             0, 0, 0, 0, len(config['actors']))
    for p, data, is_data in ((clash_bounds.CODE, clash_bounds.code(), False),
            (clash_bounds.CONTROL, clash_data, True),
            (clash_bounds.HOOK, struct.pack('<2I', (2<<26)|(clash_bounds.CODE>>2), 0), False)):
        add(p, data, 'clash_bounds', is_data)
    # Use real actor HP for the native winner predicate, including before the
    # public actor table is populated. Its runtime ownership gate stays dormant.
    defeat = team_defeat.build_memory(ram, config, source)
    for b in defeat['blocks']:
        add(b['address'], bytes.fromhex(b['data_hex']), 'team_defeat',
            b['address'] == team_defeat.CONTROL)
    cinematic = cinematic_contact_guard.build_memory(ram, config, source)
    for b in cinematic['blocks']:
        add(b['address'], bytes.fromhex(b['data_hex']), 'cinematic_contact_isolation',
            b['address'] == cinematic_contact_guard.CONTROL)
    features['throw_limits'] = list(features['cinematic_contact_isolation'])
    # Opponent-model routing with widened event rows, extra reload guards and
    # per-target line of sight. Heap pointer patches are appended unguarded by
    # the cave checks above; their expected bytes come from the builders.
    import opponent_events, extra_loader_guard, los_targets
    for module, feature in ((opponent_events, 'opponent_events'), (extra_loader_guard, 'extra_loader_guard'),
                            (los_targets, 'los_targets')):
        result = module.build_memory(ram, config, source)
        data_addresses = {module.CONTROL}
        if module is opponent_events: data_addresses |= {module.ROWS, result['event_object']+4}
        for b in result['blocks']:
            payload = bytes.fromhex(b['data_hex'])
            if b['address'] < 0x100000 or A(0x300000) <= b['address'] < 0x07000000:
                blocks.append(dict(b, purpose=feature)); continue
            add(b['address'], payload, feature, b['address'] in data_addresses)
    if include_camera:
        import fresh_team_camera
        camera = fresh_team_camera.build_memory(ram, config, source)
        for b in camera['blocks']:
            if ram[b['address']:b['address']+len(bytes.fromhex(b['data_hex']))].hex() != b['expected_hex']:
                raise ValueError('Camera expected-byte guard differs from original source')
        blocks += camera['blocks']
        for key, entries in camera['support']['features'].items(): features.setdefault(key, []).extend(entries)
    intervals = sorted((b['address'], b['address']+len(bytes.fromhex(b['data_hex']))) for b in blocks)
    if any(q < end for (_, end), (q, _) in zip(intervals, intervals[1:])):
        raise ValueError('Overlapping fresh safety blocks')
    # Executable gate dependencies must be checked too, not only high wrappers.
    core_support = core.support(core.program())['features']
    for feature in ('ko_retention', 'special_limits', 'model_effect_bounds'):
        features[feature] += core_support['physical_getters']
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()),
        status='FRESH SAFETY INSTALLED; CORE MODE AND PUBLIC COUNT UNCHANGED', config=config,
        blocks=blocks, support={'capacity': policy.emitted_actors(), 'features': features},
        control=CONTROL, dormant_mode=core.MODE, telemetry=dict(trails['telemetry']),
        evidence=['Extra fighters own native auxiliary trails by fighter index; the two-owner trail lists are '
                  'widened to twelve (aux_trail_lists) so an extra can never link a pool node to itself.'],
        limitations=trails['limitations']+['Unsupported extra special/cinematic and cosmetic requests are suppressed.',
            'Projectiles whose borrowed character pool has an incompatible format return no projectile.',
            'Extra voices, statistics and replay entries are omitted.',
            'Lifecycle detaches and restores native auxiliary pointers but does not reclaim extra allocations.',
            "Lifecycle forgets the captured trail manager and the extras' trail lists; a manager created later "
            "in the same process tracks only the two leaders' trails.",
            'Native team results are enabled; winner presentation can still use a defeated original leader.',
            'Restore a clean source state before another match; full menu lifecycle is not implemented.',
            'Render-capacity proof and fresh private AI initialization remain activation prerequisites.'])


def build(source, config, include_camera=True):
    return build_memory(read_ram(source), config, source, include_camera)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path); p.add_argument('--config', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path); x = p.parse_args()
    result = build(x.source, json.loads(x.config.read_text()))
    x.out.write_text(json.dumps(result, indent=2)+'\n'); print(f'{x.out}: {len(result["blocks"])} guarded blocks')
