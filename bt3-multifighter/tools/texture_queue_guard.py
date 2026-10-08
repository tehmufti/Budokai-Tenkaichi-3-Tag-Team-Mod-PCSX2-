"""Keep the per-frame texture upload queue from overrunning its 128 entries.

The render code queues texture uploads in a 2 KiB table: 16-byte entries at
Q = *(gp-0x577C), the count at Q+0x800 and the two VRAM cursors after it.
Four leaf producers (1ADC68, 1ADD28, 1ADDC0, 1ADE20) write the entry at
Q+count*16 and increment the count with no bound; the flush at 1AE138 resets
it every frame. Six fighters leave entries up to about 70 in the buffer. Ten
fighters bring more effect and model textures into the same frame, and a
129th entry would land on the count itself: the next producer would then write
through a pointer-sized count - a wild EE write.

When the queue is already full, each producer first points the count at the
last slot, so its native body replaces that one upload and leaves the count at
128: a texture skips one frame instead of memory being overrun. The producers
compute and return their GS register and advance the VRAM cursors exactly as
before. Below 128 nothing changes. Only v0/v1 are touched (every producer sets
both before reading them); arguments a0..a3 and t0 are left alone.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path

from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram

CODE, CONTROL, END = 0x072B0000, 0x072BF000, 0x072C0000
MAGIC = 0x54585131  # 'TXQ1'
FIELDS = dict(magic=0, replaced=4)
QUEUE_GP, COUNT, CAPACITY = -0x577C, 0x800, 128
PRODUCERS = (A(0x1ADC68), A(0x1ADD28), A(0x1ADDC0), A(0x1ADE20))
STRIDE = 0x80
NATIVE = elf_reader(elf_path(ROOT))[2]
assert CODE + len(PRODUCERS)*STRIDE <= CONTROL < END


def wrapper_code(index):
    entry = PRODUCERS[index]; original = NATIVE(entry, 8)
    a = Assembler(CODE + index*STRIDE)
    a.lw(3, 28, QUEUE_GP); a.lw(2, 3, COUNT)
    a.i(11, 2, 2, CAPACITY); a.branch(5, 2, 0, 'native')
    a.addiu(2, 0, CAPACITY-1); a.sw(2, 3, COUNT)
    a.li(3, CONTROL); a.lw(2, 3, FIELDS['replaced']); a.addiu(2, 2, 1); a.sw(2, 3, FIELDS['replaced'])
    a.label('native')
    for word in struct.unpack('<2I', original):
        assert word >> 26 not in range(1, 8), f'Producer {entry:X} prologue is not position independent'
        a.emit(word)
    a.jump(entry + 8)
    code = a.finish(); assert len(code) <= STRIDE; return code


def pieces():
    parts = [(CODE + i*STRIDE, wrapper_code(i)) for i in range(len(PRODUCERS))]
    parts += [(entry, struct.pack('<2I', (2 << 26) | ((CODE + i*STRIDE) >> 2), 0))
              for i, entry in enumerate(PRODUCERS)]
    return parts


def build_memory(ram, source='<offline-memory>'):
    if len(ram) != 0x8000000: raise ValueError('Requires128MiB EE RAM')
    for entry in PRODUCERS:
        # The whole leaf body must be native: the wrapper relies on each one
        # setting v0/v1 before reading them.
        if ram[entry:entry+0x60] != NATIVE(entry, 0x60): raise ValueError(f'Native texture producer {entry:X} changed')
    if any(ram[CODE:END]): raise ValueError('Texture queue guard reservation occupied')
    blocks = [dict(address=p, expected_hex=ram[p:p+len(d)].hex(), data_hex=d.hex())
              for p, d in [(CONTROL, struct.pack('<2I', MAGIC, 0))] + pieces()]
    return dict(serial=SERIAL, crc=CRC, source=str(source), control=CONTROL,
                status='TEXTURE UPLOAD QUEUE BOUND', blocks=blocks,
                telemetry={'replaced_uploads': CONTROL+FIELDS['replaced']})


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path); p.add_argument('--out', required=True, type=Path)
    x = p.parse_args()
    x.out.write_text(json.dumps(build_memory(read_ram(x.source), x.source), indent=2)+'\n'); print(x.out)
