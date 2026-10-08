"""Skip unsupported extra costume reloads, but wait for native summons.

An ultimate whose special flag 0x80000 inflicts a battle-damaged costume makes
the paired handler (0x1F97F8) enqueue a model-reload record owned by the
DEFENDER's physical id through sub_1D61F8 and then wait for sub_1D6360 to
report it ready. The original consumers serve physical ids 0 and 1, so a
record owned by an extra was never served; the manager's busy
word (+628) stays set and the whole battle freezes while HUD and pause keep
working. This was observed with Goku's Spirit Bomb against an extra.

The push guard skips records owned by captured extras and the ready guard
answers ready for them, so the pair proceeds without the costume swap.
Kind-1 auxiliary requests (Dragon Fist and other summoned models) instead
retain native readiness: model_slot_guards extends their native loader to
captured extras. Do not acknowledge those before their model is loaded.
The base transformation guard refuses command 107; extra_reload_forms later
replaces that policy with the host-serviced form handshake. Offline builder.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
import fresh_team_combat as core
from battle_mode_policy import ACTOR_COUNTS

PUSH_HOOK, READY_HOOK, TRANSFORM_HOOK = A(0x1D61F8), A(0x1D6360), A(0x203BA0)
PUSH, PUSH_TAIL = 0x073CE000, 0x073CE100
READY, READY_TAIL = 0x073CE200, 0x073CE300
TRANSFORM = 0x073CE400
CONTROL = 0x073CE800
FIELDS = dict(enabled=0, manager=4, skipped_pushes=16, forced_ready=20)
MODE = core.MODE


def tail(entry, original, at):
    a = Assembler(at)
    for word in struct.unpack('<2I', original):
        assert word >> 26 not in (1, 2, 3, 4, 5, 6, 7, 20, 21), 'Branching native prologue'
        a.emit(word)
    a.jump(entry+8)
    return a.finish()


def extra_gate(a, fail):
    """a0 = physical id. Falls through only for a captured extra (2..count-1).

    Uses t3..t5 so the seven argument registers of sub_1D61F8 stay intact.
    """
    a.li(11, MODE); a.lw(12, 11); a.branch(4, 12, 0, fail)
    a.lw(12, 11, 4); a.lw(13, 11, 12); a.branch(5, 12, 13, fail)
    a.lw(13, 11, 8); a.lw(11, 28, -22364); a.branch(5, 11, 13, fail)
    a.i(11, 11, 4, 2); a.branch(5, 11, 0, fail)
    a.r(0x2B, 11, 4, 12); a.branch(4, 11, 0, fail)


def push_code():
    a = Assembler(PUSH); extra_gate(a, 'native')
    a.li(11, CONTROL); a.lw(12, 11, FIELDS['skipped_pushes']); a.addiu(12, 12, 1); a.sw(12, 11, FIELDS['skipped_pushes'])
    a.move(2, 0); a.jr()
    a.label('native'); a.jump(PUSH_TAIL)
    result = a.finish(); assert len(result) <= PUSH_TAIL-PUSH; return result


def ready_code(auxiliary=True):
    a = Assembler(READY); extra_gate(a, 'native')
    if auxiliary:
        import model_slot_guards as summons
        a.li(11,summons.CONTROL);a.lw(12,11);a.li(13,summons.MAGIC)
        a.branch(5,12,13,'skip_auxiliary')
        a.addiu(29,29,-16);a.i(63,31,29,0);a.call(summons.SUMMON_PENDING)
        a.i(55,31,29,0);a.addiu(29,29,16);a.branch(5,2,0,'native')
        a.label('skip_auxiliary')
    a.li(11, CONTROL); a.lw(12, 11, FIELDS['forced_ready']); a.addiu(12, 12, 1); a.sw(12, 11, FIELDS['forced_ready'])
    a.addiu(2, 0, 1); a.jr()
    a.label('native'); a.jump(READY_TAIL)
    result = a.finish(); assert len(result) <= READY_TAIL-READY; return result


def build_memory(ram, config=None, source='<offline-memory>'):
    if len(ram) != 0x8000000: raise ValueError('Requires128MiB captured EE RAM')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager = u(A(0x2FEB14))
    if not 0x100000 <= manager <= len(ram)-16 or u(manager) != 2: raise ValueError('Requires the native two-row actor manager')
    if config is None:
        if u(MODE) != 1 or u(MODE+8) != manager or u(MODE+4) not in ACTOR_COUNTS:
            raise ValueError('Requires an active captured team or an explicit hidden configuration')
    else:
        import fresh_team_ai
        config = fresh_team_ai.normalize(config)
        fresh_team_ai.validate_world(ram, u, config)
    _, _, native = elf_reader(elf_path(ROOT))
    if any(ram[PUSH:CONTROL+0x100]): raise ValueError('Extra-loader reservation occupied')
    control = bytearray(0x100); struct.pack_into('<2I', control, 0, 1, manager)
    pieces = [(PUSH, push_code(), 'Skip reload records owned by captured extras'),
              (READY, ready_code(), 'Report extra-owned reload records ready'),
              (CONTROL, bytes(control), 'Ownership and counters')]
    for entry, cave, at in ((PUSH_HOOK, PUSH, PUSH_TAIL), (READY_HOOK, READY, READY_TAIL)):
        original = native(entry, 8)
        if ram[entry:entry+8] != original: raise ValueError(f'Native entry changed:{entry:X}')
        pieces += [(at, tail(entry, original, at), 'Displaced native prologue'),
                   (entry, struct.pack('<2I', (2<<26)|(cave>>2), 0), 'Install wrapper')]
    original = native(TRANSFORM_HOOK, 8)
    if ram[TRANSFORM_HOOK:TRANSFORM_HOOK+8] != original: raise ValueError('Native transformation command changed')
    import fresh_team_safety as safety
    pieces += [(TRANSFORM, safety.owned_code(TRANSFORM_HOOK, TRANSFORM, 2, original), 'Refuse transformation command 107 for extras'),
               (TRANSFORM_HOOK, struct.pack('<2I', (2<<26)|(TRANSFORM>>2), 0), 'Install transformation guard')]
    blocks = []
    for p, data, why in pieces:
        old = ram[p:p+len(data)]
        if PUSH <= p < CONTROL+0x100 and any(old): raise ValueError(f'Occupied reservation:{p:X}')
        blocks.append(dict(address=p, expected_hex=old.hex(), data_hex=data.hex(), purpose=why))
    intervals = sorted((b['address'], b['address']+len(bytes.fromhex(b['data_hex']))) for b in blocks)
    assert all(end <= q for (_, end), (q, _) in zip(intervals, intervals[1:]))
    support = [dict(address=b['address'], data_hex=b['data_hex']) for b in blocks if b['address'] != CONTROL]
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()), blocks=blocks, control=CONTROL,
        status='EXTRA MODEL-RELOAD GUARD AND TRANSFORMATION LIMIT',
        telemetry=dict(skipped_pushes=CONTROL+16, forced_ready=CONTROL+20),
        support={'capacity': 12, 'features': {'extra_loader_guard': support}},
        evidence=['0x1F9CDC pushes a record with the defender physical id; 0x1F9D00/0x1F9E70 wait on 1D6360 for it.',
                  '1283F0/128318 serve reload records for physical ids 0 and 1 only (slti 2).'],
        limitations=['Extras never receive battle-damaged costumes; leaders keep native behavior.',
                     'Extras cannot transform; leaders can (their reloads are served natively).'])


def build(source, config=None):
    return build_memory(read_ram(source), config, source)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--source', required=True, type=Path)
    p.add_argument('--config', type=Path); p.add_argument('--out', required=True, type=Path); x = p.parse_args()
    result = build(x.source, json.loads(x.config.read_text()) if x.config else None)
    x.out.write_text(json.dumps(result, indent=2)+'\n'); print(f'{x.out}: {len(result["blocks"])} guarded blocks')
