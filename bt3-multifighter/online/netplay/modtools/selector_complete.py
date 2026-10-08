"""Offline completion of six binary opponent blocks missed by the old pattern scan."""
from native_map import A, CRC, SERIAL, elf_path
import json
import struct
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader

# Address, source actor pointer register, destination that must receive v0.
BLOCKS = ((A(0x1DB268), 4, None), (A(0x1DB2C0), 4, None), (A(0x1DB844), 17, 16),
          (A(0x1DB8DC), 17, 16), (A(0x1DBA48), 4, None), (A(0x1DBCF4), 17, 16))


def block_code(address, source, destination):
    a = Assembler(address)
    a.lw(4, source)
    a.i(12, 4, 4, 1)
    a.i(14, 4, 4, 1)
    a.call(A(0x1DC178))
    while len(a.words) < 9:
        a.emit(0)
    a.move(destination, 2) if destination is not None else a.emit(0)
    assert len(a.words) == 10
    return a.finish()


def build(ram_path, output):
    ram = Path(ram_path).read_bytes()
    _, _, readelf = elf_reader(elf_path(ROOT))
    blocks = []
    for address, source, destination in BLOCKS:
        original = readelf(address, 40)
        assert ram[address:address + 40] == original, f'Selector changed at {address:08X}'
        code = block_code(address, source, destination)
        blocks.append({'address': address, 'expected_hex': original.hex(), 'data_hex': code.hex(),
                       'purpose': 'Complete even actor->leader1, odd actor->leader0 opponent selection'})
    manifest = {'serial': SERIAL, 'crc': CRC,
                'status': 'SIX MISSING OPPOSING-LEADER SELECTORS; OFFLINE TESTED', 'blocks': blocks}
    Path(output).write_text(json.dumps(manifest, indent=2) + '\n')
    print(output)
    return manifest


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--ram', type=Path, default=ROOT / 'analysis/team-created.bin')
    ap.add_argument('--out', type=Path, default=ROOT / 'analysis/selectors-six.json')
    args = ap.parse_args()
    build(args.ram, args.out)
