"""Fresh captured-world camera ownership, KO successors and visible bodies.

Reuses the reviewed camera/body algorithms in isolated emitter namespaces.
All former exposure reads become the shared fresh MODE read; an outer gate
additionally enforces configured count and manager identity. No legacy patch
code, camera globals, actor ownership or controller transfer is required.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from types import FunctionType

from prototype import Assembler, ROOT, elf_reader
from ai_shadow import Assembler as AIAssembler
from camera_snapshot import read_ram
import camera_successor as successor
import leader_camera as leader
import team_fallen_bodies as body
import fresh_team_ai as ai
import fresh_team_combat as combat
import battle_mode_policy as policy

GATE = 0x073A0000
LEADER, LEADER_INNER, LEADER_NATIVE, LEADER_CONTROL = 0x073A0200, 0x073A0400, 0x073A2A00, 0x073AF000
SUCCESSOR, SUCCESSOR_INNER, LOOKUP, SUCCESSOR_CONTROL = 0x073A1000, 0x073A1200, 0x073A2000, 0x073AF100
BODY, BODY_INNER, BODY_NATIVE, BODY_CONTROL = 0x073A2200, 0x073A2400, 0x073A2800, 0x073AF200


class FreshAIAssembler(AIAssembler):
    def load_address(self, register, address):
        if address in (0xB3088, 0xF609C): address = combat.MODE
        super().load_address(register, address)


class FreshAssembler(Assembler):
    def li(self, register, value):
        if value == 0xB3088: value = combat.MODE
        super().li(register, value)


def rebound(function, **values):
    context = dict(function.__globals__); context.update(values)
    return FunctionType(function.__code__, context, function.__name__, function.__defaults__, function.__closure__)


def gate_code():
    a = Assembler(GATE); combat.gate(a, 'native')
    a.addiu(2, 0, 1); a.jr()
    a.label('native'); a.move(2, 0); a.jr()
    return a.finish()


def scope(base, target, native):
    a = Assembler(base); saved = (2, 3, 8, 9, 10, 31)
    a.addiu(29, 29, -0x30)
    for i, register in enumerate(saved): a.i(63, register, 29, i*8)
    a.call(GATE); a.branch(4, 2, 0, 'native')
    for i, register in enumerate(saved): a.i(55, register, 29, i*8)
    a.addiu(29, 29, 0x30); a.jump(target)
    a.label('native')
    for i, register in enumerate(saved): a.i(55, register, 29, i*8)
    a.addiu(29, 29, 0x30); a.jump(native)
    data = a.finish(); assert len(data) < 0x200; return data


def program(config):
    config = ai.normalize(config)
    _, _, native = elf_reader(elf_path(ROOT))
    selection = rebound(leader.payload_cinematic, Assembler=FreshAssembler, CODE=LEADER_INNER, CONTROL=LEADER_CONTROL)()
    camera = rebound(successor.stub, Assembler=FreshAIAssembler, CODE=SUCCESSOR_INNER,
                     LOOKUP=LOOKUP, CONTROL=SUCCESSOR_CONTROL)()
    lookup = rebound(successor.lookup_stub, LOOKUP=LOOKUP)()
    fallen = rebound(body.stub, Assembler=FreshAIAssembler, CODE=BODY_INNER,
                     CONTROL=BODY_CONTROL, EXPOSURE=combat.MODE)()
    old_leader = native(leader.HOOK, 8)
    assert old_leader == leader.ORIGINAL
    native_leader = old_leader + struct.pack('<2I', (2<<26)|((leader.HOOK+8)>>2), 0)
    native_body = native(body.ENTRY, 20)
    assert native_body == bytes.fromhex('ffff02240100a2544c0985ac0800e00300000000')
    camera_control = bytearray(64)
    struct.pack_into('<6I', camera_control, 0, 1, config['actor_manager'], 0, 1, 0xFFFFFFFF, 0xFFFFFFFF)
    payloads = [(GATE, gate_code(), 'leader_camera'),
        (LEADER, scope(LEADER, LEADER_INNER, LEADER_NATIVE), 'leader_camera'),
        (LEADER_INNER, selection, 'leader_camera'), (LEADER_NATIVE, native_leader, 'leader_camera'),
        (SUCCESSOR, scope(SUCCESSOR, SUCCESSOR_INNER, successor.NATIVE), 'leader_camera'),
        (SUCCESSOR_INNER, camera, 'leader_camera'), (LOOKUP, lookup, 'leader_camera'),
        (BODY, scope(BODY, BODY_INNER, BODY_NATIVE), 'fallen_bodies'),
        (BODY_INNER, fallen, 'fallen_bodies'), (BODY_NATIVE, native_body, 'fallen_bodies'),
        (LEADER_CONTROL, struct.pack('<4I', 1, 0, 0, 0), 'leader_camera'),
        (SUCCESSOR_CONTROL, bytes(camera_control), 'leader_camera'),
        (BODY_CONTROL, struct.pack('<4I', 1, 0, 0, 0), 'fallen_bodies')]
    ordered = sorted(payloads)
    assert all(p+len(data) <= end for (p, data, _), (end, _, _) in zip(ordered, ordered[1:]))
    assert ordered[-1][0]+len(ordered[-1][1]) < 0x073B0000
    for entry, target, feature in ((leader.HOOK, LEADER, 'leader_camera'), (body.ENTRY, BODY, 'fallen_bodies')):
        payloads.append((entry, struct.pack('<2I', (2<<26)|(target>>2), 0), feature))
    assert native(successor.HOOK, 8) == struct.pack('<2I', (3<<26)|(successor.NATIVE>>2), 0x8C500C40)
    payloads.append((successor.HOOK, struct.pack('<I', (3<<26)|(SUCCESSOR>>2)), 'leader_camera'))
    return payloads


def upgrade_memory(ram, source='<offline>'):
    """Replace an installed leader-only selection with the cinematic-aware one.

    For prepared checkpoints that already contain the fresh camera support.
    The block guards the currently installed inner code and its zero tail.
    """
    if len(ram) != 0x8000000: raise ValueError('Full128MiB EE RAM is required')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    if u(leader.HOOK) != (2<<26)|(LEADER>>2): raise ValueError('Fresh leader camera wrapper is not installed')
    old = rebound(leader.payload, Assembler=FreshAssembler, CODE=LEADER_INNER, CONTROL=LEADER_CONTROL)()
    new = rebound(leader.payload_cinematic, Assembler=FreshAssembler, CODE=LEADER_INNER, CONTROL=LEADER_CONTROL)()
    current = ram[LEADER_INNER:LEADER_INNER+len(new)]
    if current == new: raise ValueError('Cinematic-aware camera selection is already installed')
    if current[:len(old)] != old or any(current[len(old):]): raise ValueError('Unknown leader camera selection code')
    if LEADER_INNER+len(new) > SUCCESSOR: raise ValueError('Upgraded selection overlaps the successor cave')
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()),
        blocks=[dict(address=LEADER_INNER, expected_hex=current.hex(), data_hex=new.hex(),
                     purpose='Cinematic-aware leader camera selection')],
        telemetry=dict(frames=LEADER_CONTROL+4, split_frames=LEADER_CONTROL+8, last_side=LEADER_CONTROL+12,
                       cinematic_views=LEADER_CONTROL+16))


def upgrade(source): return upgrade_memory(read_ram(source), source)


def build_memory(ram, config, source='<offline-fixture>'):
    config = ai.normalize(config)
    if len(ram) != 0x8000000: raise ValueError('Full128MiB EE RAM is required')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    ai.validate_world(ram, u, config)
    _, _, native = elf_reader(elf_path(ROOT))
    payloads = program(config); blocks = []; features = {'leader_camera': [], 'fallen_bodies': []}
    for address, data, feature in payloads:
        old = ram[address:address+len(data)]
        if address < A(0x300000):
            if old != native(address, len(data)): raise ValueError(f'Native camera/body hook changed:{address:X}')
        elif any(old): raise ValueError(f'Fresh camera/body cave occupied:{address:X}')
        blocks.append(dict(address=address, expected_hex=old.hex(), data_hex=data.hex(), purpose=feature))
        features[feature].append(dict(address=address, data_hex=data.hex()))
    features['fallen_bodies'].append(dict(address=GATE, data_hex=gate_code().hex()))
    if ram[successor.HOOK+4:successor.HOOK+8] != native(successor.HOOK+4, 4):
        raise ValueError('Native camera successor call delay slot changed')
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()), config=config,
        status='FRESH BODY AND CAMERA SUPPORT; DORMANT UNTIL MATCHING COUNT PUBLICATION', blocks=blocks,
        support={'capacity': policy.emitted_actors(), 'features': features},
        controls={'leader_selection': LEADER_CONTROL, 'camera_successor': SUCCESSOR_CONTROL, 'fallen_bodies': BODY_CONTROL},
        behavior=['Initial side0/1 cameras follow their original leaders.',
                  'After KO keep or choose a living teammate; if the side is eliminated follow a living opponent.',
                  'If nobody survives keep a valid fallen body as camera subject.',
                  'Dead captured requests for invisible action235 become native visible KO216; living requests stay native.',
                  'Native cinematic timing continues while view selection stays on the normal side cameras.'],
        requirements=['Independent KO/tag retention and dead-contact exclusion must also be installed.',
                      'No controller transfer or completed team round transition is implemented.'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path); parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path); args = parser.parse_args()
    result = build_memory(read_ram(args.source), json.loads(args.config.read_text()), args.source)
    args.out.write_text(json.dumps(result, indent=2)+'\n'); print(args.out)
