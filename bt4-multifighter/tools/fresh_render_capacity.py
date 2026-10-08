"""Install the reviewed rendering observer in a fresh hidden-team preparation.

Reuses the exact packet and draw-pool machine code tested by capacity_stage.
The fresh heap has its own live canary; no legacy prototype flags are invented.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
from pathlib import Path

import capacity_stage as cap
import fresh_memory as memory
import packet_pool_grow as packets
from camera_snapshot import read_ram
from prototype import ROOT, elf_reader
from team_prototype import make_block
import battle_mode_policy as policy


def world(r):
    u = lambda p: struct.unpack_from('<I', r, p)[0]
    assert len(r) == 0x8000000
    manager, pool = u(A(0x2FEB14)), u(A(0x2FEC44))
    assert 0x100000 <= manager < len(r)-0x1000 and u(manager) == 2
    assert 0x100000 <= pool < len(r)-440000
    assert u(memory.CONTROL) == 20 and u(memory.CONTROL+80) == 1
    assert u(memory.CONTROL+84) == manager
    assert r[memory.CODE:memory.CODE+len(memory.payload())] == memory.payload()
    assert u(A(0x2FF084)) == 0x02000000 and u(A(0x2FF08C)) == 0x06000000
    for actor in (u(manager+4), u(manager+4)+0x1600):
        assert not any(u(actor+p) for p in (0x1278, 0x127C, 0x1280, 0x1284))
    return u, manager, pool


def build(mode, source):
    r = read_ram(source)
    u, manager, pool = world(r)
    _, _, native = elf_reader(elf_path(ROOT))
    payloads = []
    if mode == 'observe':
        assert not any(r[cap.FRAME:cap.CONTROL+0x100])
        assert u(cap.FRAME_ENTRY) >> 26 == 2 and not u(cap.FRAME_ENTRY+4)
        previous = (u(cap.FRAME_ENTRY) & 0x3ffffff) << 2
        assert previous in (0x07340000, 0x07364000), 'Unreviewed fresh preparation chain'
        if previous == 0x07340000:
            assert u(0x07358400) == 20 and not u(0x0735841C)
        else:
            assert u(0x07367004) == 5
        assert r[cap.PACKET_ENTRY:cap.PACKET_ENTRY+0xB8] == native(cap.PACKET_ENTRY, 0xB8)
        data = bytearray(256)
        for offset, value in ((0, cap.MAGIC), (4, 1), (48, 1), (88, pool),
                              (96, previous), (100, manager), (104, 2)):
            struct.pack_into('<I', data, offset, value)
        payloads = [(cap.FRAME, cap.frame_code(previous)), (cap.PACKET, cap.packet_code()),
                    (cap.PACKET_TRAMPOLINE, cap.packet_trampoline(native)),
                    (cap.CONTROL, bytes(data)),
                    (cap.FRAME_ENTRY, struct.pack('<2I', (2<<26)|(cap.FRAME>>2), 0)),
                    (cap.PACKET_ENTRY, struct.pack('<2I', (2<<26)|(cap.PACKET>>2), 0))]
    else:
        assert u(cap.CONTROL) == cap.MAGIC and u(cap.CONTROL+52) == 5
        assert u(cap.CONTROL+8) and u(cap.CONTROL+16)
        assert not u(cap.CONTROL+40) and not u(cap.CONTROL+44)
        assert u(cap.CONTROL+88) == pool and u(cap.CONTROL+100) == manager
        previous = u(cap.CONTROL+96)
        for p, b in ((cap.FRAME, cap.frame_code(previous)), (cap.PACKET, cap.packet_code()),
                     (cap.PACKET_TRAMPOLINE, cap.packet_trampoline(native))):
            assert r[p:p+len(b)] == b
        assert u(cap.FRAME_ENTRY) == (2<<26)|(cap.FRAME>>2) and not u(cap.FRAME_ENTRY+4)
        assert u(cap.PACKET_ENTRY) == (2<<26)|(cap.PACKET>>2) and not u(cap.PACKET_ENTRY+4)
        for p, n in ((A(0x255CF0), 0x30), (A(0x2554D8), 0x30)):
            assert r[p:p+n] == native(p, n)
        assert not any(r[cap.GROW:cap.GROW+len(cap.grow_code())])
        assert not any(r[cap.CONTROL+64:cap.CONTROL+80])
        payloads = [(cap.GROW, cap.grow_code()), (cap.CONTROL+64, struct.pack('<I', 1)),
                    (cap.FRAME_ENTRY, struct.pack('<2I', (2<<26)|(cap.GROW>>2), 0))]
    blocks = [make_block(r, p, b, 'Fresh render '+mode) for p, b in payloads]
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()),
                status='FRESH RENDER '+mode.upper()+'; HIDDEN TEAM UNCHANGED', blocks=blocks,
                control=cap.CONTROL, previous=previous)


def support(source):
    r = read_ram(source)
    u, manager, pool = world(r)
    assert u(cap.CONTROL) == cap.MAGIC
    assert u(cap.CONTROL+52) == 5 and u(cap.CONTROL+8) > 0 and u(cap.CONTROL+16) > 0
    assert u(cap.CONTROL+88) == pool and u(cap.CONTROL+100) == manager
    assert not u(cap.CONTROL+40) and not u(cap.CONTROL+44)
    assert u(cap.CONTROL+68) == 20 and u(cap.CONTROL+76) == 512
    assert u(packets.CONTROL) == 5 and u(packets.CONTROL+8) == 2
    assert u(packets.CONTROL+56) == manager
    assert u(packets.CONTROL+12) == packets.SIZE
    assert u(packets.CAPACITY) == packets.SIZE
    assert u(pool+397320) > 0
    for i in range(2):
        assert u(packets.BASES+4*i) == u(packets.CONTROL+24+4*i)
        assert 0x02000000 <= u(packets.BASES+4*i) < 0x06000000-packets.SIZE+1
        assert u(packets.ENDS+4*i)-u(packets.BASES+4*i) == packets.SIZE
    segments = []
    _, _, native = elf_reader(elf_path(ROOT))
    for p, b in ((cap.GROW, cap.grow_code()), (cap.FRAME, cap.frame_code(u(cap.CONTROL+96))),
                 (cap.PACKET, cap.packet_code()), (cap.PACKET_TRAMPOLINE, cap.packet_trampoline(native)),
                 (packets.CODE, packets.payload()),
                 (cap.FRAME_ENTRY, struct.pack('<2I', (2<<26)|(cap.GROW>>2), 0)),
                 (cap.PACKET_ENTRY, struct.pack('<2I', (2<<26)|(cap.PACKET>>2), 0)),
                 (packets.HOOK, struct.pack('<2I', (2<<26)|(packets.CODE>>2), 0))):
        assert r[p:p+len(b)] == b
        segments.append(dict(address=p, data_hex=b.hex()))
    execution = [dict(address=memory.CODE, data_hex=memory.payload().hex()),
                 dict(address=cap.FRAME, data_hex=cap.frame_code(u(cap.CONTROL+96)).hex())]
    return dict(capacity=policy.emitted_actors(), features={'render_capacity': segments, 'high_ee_execution': execution},
                evidence=dict(free_draw_nodes=u(pool+397320), packet_bytes=packets.SIZE,
                              packet_submissions=u(cap.CONTROL+16),
                              fresh_memory_canary_status=u(memory.CONTROL),
                              high_code_frames=u(cap.CONTROL+8), captured_manager=manager))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=('observe', 'grow', 'support'))
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    x = p.parse_args()
    result = support(x.source) if x.mode == 'support' else build(x.mode, x.source)
    x.out.write_text(json.dumps(result, indent=2)+'\n')
    print(x.out)
