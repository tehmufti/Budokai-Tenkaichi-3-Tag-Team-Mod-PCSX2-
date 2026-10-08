"""Companion checks for two specialized projectile pool formats."""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path
from prototype import ROOT, elf_reader
from camera_snapshot import read_ram
from projectile_pool_guard import payload, NATIVE, RESOURCE_GLOBAL

FAMILIES = (
    dict(code=0x07322000, control=0x07322800, parent_callbacks=A(0x2C3DD0),
         child_callbacks=A(0x2C3DE8), size=304, hooks=(A(0x177B98), A(0x177BA8))),
    dict(code=0x07322400, control=0x07322840, parent_callbacks=A(0x2C3E00),
         child_callbacks=A(0x2C3E18), size=480, hooks=(A(0x178C80),)),
)


def build(source):
    r = read_ram(source); assert len(r) == 0x8000000
    u = lambda p: struct.unpack_from('<I', r, p)[0]
    _, _, native = elf_reader(elf_path(ROOT))
    manager, resources = u(A(0x2FEB14)), u(RESOURCE_GLOBAL)
    assert manager and manager == u(0xD8088) and resources
    for start, length in ((A(0x177A20), 0xA8), (A(0x178AF8), 0xC0)):
        assert r[start:start+length] == native(start, length)
    blocks = []
    for family in FAMILIES:
        args = {k: v for k, v in family.items() if k != 'hooks'}
        b = payload(**args, descriptor_size=88, check_header=False)
        control = struct.pack('<8I', 1, manager, resources, 0, 0, 0, 0, 0)
        for p, data in ((family['code'], b), (family['control'], control)):
            assert not any(r[p:p+len(data)]), f'Occupied specialized projectile cave{p:08X}'
            blocks.append(dict(address=p, expected_hex=r[p:p+len(data)].hex(), data_hex=data.hex()))
        for hook in family['hooks']:
            old = native(hook, 8); assert r[hook:hook+8] == old
            assert int.from_bytes(old[:4], 'little') == (3 << 26) | (NATIVE >> 2)
            data = struct.pack('<I', (3 << 26) | (family['code'] >> 2))+old[4:]
            blocks.append(dict(address=hook, expected_hex=old.hex(), data_hex=data.hex()))
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()),
                status='SPECIALIZED PROJECTILE POOL COMPATIBILITY; OFFLINE TESTED', blocks=blocks,
                evidence=['177B18 requires parent2C3DD0, child2C3DE8,304-byte bodies and88-byte descriptor.',
                          '178C10 requires parent2C3E00, child2C3E18,480-byte bodies and88-byte descriptor.',
                          'Borrowed side0 kind1/2 pools are generic1504-byte families whose metadata format differs.'],
                behavior=['Check each selected pool before allocation, preserving original native callsite delay slots.',
                          'Matching specialized pools retain native allocation; incompatible borrowed families return0.',
                          'Both consecutive allocation calls in177B18 are independently protected.'])


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path); p.add_argument('--out', required=True, type=Path)
    x = p.parse_args(); x.out.write_text(json.dumps(build(x.source), indent=2)+'\n'); print(x.out)
