"""Make the online kit's memory cards: a deterministic, formatted, EMPTY 8 MiB PS2 card (PCSX2 .ps2, ECC spares).

  python make_online_memcards.py bt3-multifighter/online/match/runtime/memcards/Mcd001.ps2 .../Mcd002.ps2

Both peers' games and the host's private match-making copy start from these files. The game accepts the card as
formatted (live, Oct 15: "create a save file? Yes" creates the save without the unformatted-card question).

Layout of a standard formatted card (512-byte pages + 16 spare, 2 pages per cluster, 16 pages per erase block,
8192 clusters): superblock in cluster 0, indirect FAT cluster 8, FAT clusters 9..40, allocatable clusters from 41
(8135 of them, the last two erase blocks are the backup blocks), root directory in allocatable cluster 0 holding
'.' and '..'. Every other page is erased (0xFF data and spare). Timestamps are fixed, so the image is reproducible.
"""
import struct
import sys

PAGE, SPARE, PPC, PPB, CLUSTERS = 512, 16, 2, 16, 8192
PAGES = CLUSTERS * PPC
IFC, FAT0, NFAT, ALLOC, ALLOC_END = 8, 9, 32, 41, 8135
B1, B2 = PAGES // PPB - 1, PAGES // PPB - 2


def _parity(b):
    b ^= b >> 4; b ^= b >> 2; b ^= b >> 1
    return b & 1


PARITY = [_parity(b) for b in range(256)]
MASKS = (0x55, 0x33, 0x0F, 0x00, 0xAA, 0xCC, 0xF0)
CPT = [sum(1 << i for i, m in enumerate(MASKS) if PARITY[b & m]) for b in range(256)]


def ecc128(chunk):
    cp, lp0, lp1 = 0x77, 0x7F, 0x7F
    for i, b in enumerate(chunk):
        cp ^= CPT[b]
        if PARITY[b]:
            lp0 ^= ~i
            lp1 ^= i
    return bytes((cp & 0xFF, lp0 & 0x7F, lp1 & 0x7F))


def spare(page):
    ecc = b''.join(ecc128(page[i:i + 128]) for i in range(0, PAGE, 128))
    return ecc + bytes(SPARE - len(ecc))


def tod():
    return struct.pack('<xBBBBBH', 0, 0, 0, 1, 1, 2000)


def entry(mode, length, name):
    return struct.pack('<HHL8sLL8sL28s448s', mode, 0, length, tod(), 0, 0, tod(), 0, bytes(28),
                       name.encode().ljust(448, b'\0'))


def build():
    card = bytearray(b'\xff' * (PAGES * (PAGE + SPARE)))

    def write_page(n, data):
        data = bytes(data).ljust(PAGE, b'\xff')
        assert len(data) == PAGE
        off = n * (PAGE + SPARE)
        card[off:off + PAGE] = data
        card[off + PAGE:off + PAGE + SPARE] = spare(data)

    def write_cluster(c, data):
        data = bytes(data).ljust(PAGE * PPC, b'\xff')
        for i in range(PPC):
            write_page(c * PPC + i, data[i * PAGE:(i + 1) * PAGE])

    ifc_list = [IFC] + [0] * 31
    bad = [0xFFFFFFFF] * 32
    sb = struct.pack('<28s12sHHHHLLLLLL8x32L32LBBxx', b'Sony PS2 Memory Card Format ', b'1.2.0.0'.ljust(12, b'\0'),
                     PAGE, PPC, PPB, 0xFF00, CLUSTERS, ALLOC, ALLOC_END, 0, B1, B2, *ifc_list, *bad, 2, 0x52)
    assert len(sb) == 340
    write_cluster(0, sb)
    write_cluster(IFC, struct.pack('<256L', *([FAT0 + i for i in range(NFAT)] + [0xFFFFFFFF] * (256 - NFAT))))
    fat = [0x7FFFFFFF] * ALLOC_END + [0xFFFFFFFF] * (NFAT * 256 - ALLOC_END)
    fat[0] = 0xFFFFFFFF                                  # the root directory: allocated, end of chain
    for i in range(NFAT):
        write_cluster(FAT0 + i, struct.pack('<256L', *fat[i * 256:(i + 1) * 256]))
    write_cluster(ALLOC, entry(0x8427, 2, '.') + entry(0xA426, 0, '..'))
    return bytes(card)


if __name__ == '__main__':
    data = build()
    assert len(data) == 8650752
    for path in sys.argv[1:]:
        open(path, 'wb').write(data)
    import hashlib
    print(hashlib.sha256(data).hexdigest())
