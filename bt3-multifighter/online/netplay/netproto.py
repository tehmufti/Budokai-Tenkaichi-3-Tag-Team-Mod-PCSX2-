"""Wire format of the lockstep session, version 4 (kit 2.1: one host, any number of guests, ten input slots - one per
fighter of the 5 v 5 engine; UDP, little-endian, one datagram per message, no fragmentation). Version 4 = version 3
with acks[10] and a 16-bit slot mask.

The host is the hub of a star: every playing PC sends its own inputs to the host, and the host forwards every input
slot's inputs to every other PC (players and spectators). Only the host compares the games: every PC reports its
per-frame state hashes to the host.

Header (28 bytes): magic 'NPS3', version, kind, sender member id (the host is member 1), flags, session id (every PC
derives it from the installed savestate, the input delay, the core layout and the EPOCH: an earlier fight, a rematch
or the world before a resync never talk), packet sequence, the sender's millisecond clock, the echo of the newest clock
value received from the other side and how long the sender held it (round-trip time = now - echo - hold).

HELLO: input delay, core layout, redundancy, epoch, 8 bytes of the installed savestate's sha256, a 16-byte name, the
       sender's input slot (NO_SLOT for a spectator or a host that does not play), its role and the slot mask.
DATA:  the sender's game frame and total stall vblanks (monitoring), hash_ack (the next frame whose hash report the
       sender still needs: guests send it as 0, only the host collects reports), sealed / sched_through (the
       frame-scheduled host writes: sealed = the newest frame the host's batches are complete for, NO_SCHED when no
       scheduling runs; sched_through = the newest scheduled batch the sender applied), acks[4] (per input slot, the
       next frame the sender still needs: every frame below it has arrived), then input BLOCKS (slot, count, first,
       count x 12-byte inputs), hash reports (frame, combined hash, rng class hash) and (host -> guest only) the
       scheduled entries the receiver has not acknowledged (seq, frame K, count, count x {address, value, mask}):
       from the host, sealed = its frame + D + 1 and sched_through = how many entries it has scheduled; from a guest,
       sched_through = how many entries it has written into its game's SCHED ring (netplay_core OPT_SCHED).
       Input = 12 bytes: the netplay_core raw layout (8) + an aux word (u32: the gate bytes the capturing PC's game
       recorded with the input; spec 9).
       Redundancy: every DATA carries all of the receiver's missing frames from its ack on (each block up to its share
       of MAX_DATA) and all of its missing hash reports from its hash_ack on (up to MAX_HASHES): a lost datagram costs
       only the next one.
BYE:   a reason code; the receiver ends its session after a short linger.
"""
import hashlib
import struct

MAGIC = b'NPS4'
VERSION = 4
HELLO, DATA, BYE = 1, 2, 3
HEADER = struct.Struct('<4sBBBBIIIIHH')
HELLO_BODY = struct.Struct('<HHHH8s16sBBH')         # delay, layout, redundancy, epoch, tag, name, slot, role, mask
DATA_BODY = struct.Struct('<IIIII10IBBH')           # frame, stall, hash_ack, sealed, sched_through, acks[10],
                                                    # nblocks, hcount, nsched
BLOCK = struct.Struct('<BBHI')                      # slot, count (entries), flags (BLOCK_RLE), first frame
BLOCK_RLE = 1                                       # kit 2.1: each entry's aux byte 3 is its repeat count - 1 (the
                                                    # gate's channel 3 byte is reserved, always 0): a held or idle pad
                                                    # costs one 12-byte entry for up to 256 frames
INPUT = struct.Struct('<8sI')                       # raw8, aux
HASH_REPORT = struct.Struct('<III')
SCHED_HEAD = struct.Struct('<IIHH')                 # seq, frame K, count, bulk (kit 2.1: the host-service bulk
                                                    # message this entry needs written first; 0: none)
SCHED_WRITE = struct.Struct('<III')                 # address, value, mask
MAX_SCHED_WRITES = 41                               # netplay_core.SCHED_WRITES
MAX_SCHED = 8                                       # entries per datagram
RAW = 8
SLOTS = 10
NO_SLOT = 0xFF
NO_SCHED = 0xFFFFFFFF
ROLE_PLAYER, ROLE_SPECTATOR, ROLE_HUB = 0, 1, 2
MAX_DATA = 1400                                     # bytes per datagram (below every common path MTU)
MAX_HASHES = 32
MAX_BLOCK = 255
BYE_DONE, BYE_ABORTED, BYE_DESYNC, BYE_ERROR, BYE_LEFT = 1, 2, 3, 4, 5
assert HEADER.size == 28 and DATA_BODY.size == 64 and INPUT.size == 12 and BLOCK.size == 8


class ProtocolError(ValueError):
    pass


def header(kind, member, session, seq, t_send, echo=0, hold=0, flags=0):
    return HEADER.pack(MAGIC, VERSION, kind, member & 0xFF, flags, session & 0xFFFFFFFF, seq & 0xFFFFFFFF,
                       t_send & 0xFFFFFFFF, echo & 0xFFFFFFFF, min(max(hold, 0), 0xFFFF), 0)


def hello(member, session, seq, t_send, *, delay, layout, redundancy, state_sha, epoch=0, name='', slot=None,
          role=ROLE_PLAYER, mask=0, echo=0, hold=0):
    tag = bytes.fromhex(state_sha[:16]) if isinstance(state_sha, str) else bytes(state_sha[:8])
    return header(HELLO, member, session, seq, t_send, echo, hold) + HELLO_BODY.pack(
        delay, layout, redundancy, epoch & 0xFFFF, tag.ljust(8, b'\0'), name.encode('utf-8')[:16].ljust(16, b'\0'),
        NO_SLOT if slot is None else slot, role, mask & 0xFFFF)


def _input(item):
    """raw8 or (raw8, aux) -> (raw8, aux)."""
    if isinstance(item, (bytes, bytearray)):
        raw, aux = bytes(item), 0
    else:
        raw, aux = bytes(item[0]), item[1]
    if len(raw) != RAW:
        raise ProtocolError('raw inputs are 8 bytes')
    return raw, aux & 0xFFFFFFFF


def _runs(items):
    """(entries, rle): consecutive equal inputs as one entry each (aux byte 3 = repeats - 1, up to 256), unless an
    aux word already uses byte 3 (never: the reserved gate channel) - then the block goes as it is."""
    if any(aux >> 24 for _, aux in items):
        return list(items), False
    out = []
    for raw, aux in items:
        if out and out[-1][0] == raw and (out[-1][1] & 0xFFFFFF) == aux and out[-1][1] >> 24 < 255:
            out[-1] = (raw, out[-1][1] + (1 << 24))
        else:
            out.append((raw, aux))
    return out, True


def room_for_inputs(nblocks, nhashes, sched_bytes=0):
    """How many 12-byte inputs fit beside nblocks block headers, nhashes hash reports and the scheduled entries."""
    used = HEADER.size + DATA_BODY.size + nblocks * BLOCK.size + nhashes * HASH_REPORT.size + sched_bytes
    return max(0, (MAX_DATA - used) // INPUT.size)


def sched_size(entry):
    return SCHED_HEAD.size + len(entry[2]) * SCHED_WRITE.size


def sched_fit(entries, budget=700):
    """The leading entries (seq order) that fit in `budget` bytes (at least the first one, at most MAX_SCHED)."""
    out, used = [], 0
    for e in entries[:MAX_SCHED]:
        size = sched_size(e)
        if out and used + size > budget:
            break
        out.append(e)
        used += size
    return out


def data(member, session, seq, t_send, *, frame, stall, acks, blocks=(), hashes=(), hash_ack=0, sealed=NO_SCHED,
         sched_through=0, sched=(), echo=0, hold=0):
    """acks: 10 next-needed frames (one per input slot); blocks: [(slot, first, [raw8 or (raw8, aux), ...])];
    hashes: (frame, combined, rng) tuples; sched: [(seq, K, [(address, value, mask), ...])] (sched_fit them first).
    Blocks are cut so the datagram stays within MAX_DATA."""
    hashes = list(hashes)[:MAX_HASHES]
    sched = list(sched)[:MAX_SCHED]
    for e in sched:
        if not 0 < len(e[2]) <= MAX_SCHED_WRITES:
            raise ProtocolError('a scheduled entry holds 1..41 writes')
    blocks = [(s, f, [_input(i) for i in items]) for s, f, items in blocks if items]
    room = room_for_inputs(len(blocks), len(hashes), sum(sched_size(e) for e in sched))
    share = room // len(blocks) if blocks else 0
    spare = room - share * len(blocks)
    cut = []
    for s, f, items in blocks:
        entries, rle = _runs(items)
        take = min(len(entries), MAX_BLOCK, share + spare)
        spare -= max(0, take - share)
        cut.append((s, f, entries[:take], rle))
    acks = list(acks) + [0] * (SLOTS - len(acks))
    body = DATA_BODY.pack(frame & 0xFFFFFFFF, stall & 0xFFFFFFFF, hash_ack & 0xFFFFFFFF, sealed & 0xFFFFFFFF,
                          sched_through & 0xFFFFFFFF, *(a & 0xFFFFFFFF for a in acks[:SLOTS]), len(cut), len(hashes),
                          len(sched))
    out = [header(DATA, member, session, seq, t_send, echo, hold), body]
    for s, f, items, rle in cut:
        out.append(BLOCK.pack(s, len(items), BLOCK_RLE if rle else 0, f & 0xFFFFFFFF))
        out += [INPUT.pack(raw, aux) for raw, aux in items]
    out += [HASH_REPORT.pack(*(v & 0xFFFFFFFF for v in h)) for h in hashes]
    for e in sched:
        s_seq, k, writes = e[:3]
        out.append(SCHED_HEAD.pack(s_seq & 0xFFFFFFFF, k & 0xFFFFFFFF, len(writes), (e[3] if len(e) > 3 else 0) & 0xFFFF))
        out += [SCHED_WRITE.pack(a & 0xFFFFFFFF, v & 0xFFFFFFFF, m & 0xFFFFFFFF) for a, v, m in writes]
    datagram = b''.join(out)
    assert len(datagram) <= MAX_DATA, len(datagram)
    return datagram


def bye(member, session, seq, t_send, reason, echo=0, hold=0):
    return header(BYE, member, session, seq, t_send, echo, hold) + struct.pack('<HH', reason, 0)


def parse(datagram):
    """dict(kind, member, session, seq, t_send, echo, hold, ...body fields). ProtocolError on anything malformed (an
    older kit's datagram included)."""
    if len(datagram) < HEADER.size:
        raise ProtocolError('short datagram')
    magic, version, kind, member, flags, session, seq, t_send, echo, hold, _ = HEADER.unpack_from(datagram)
    if magic != MAGIC or version != VERSION:
        raise ProtocolError('not a netplay datagram of this version')
    out = dict(kind=kind, member=member, flags=flags, session=session, seq=seq, t_send=t_send, echo=echo, hold=hold)
    body = datagram[HEADER.size:]
    if kind == HELLO:
        if len(body) != HELLO_BODY.size:
            raise ProtocolError('bad HELLO size')
        delay, layout, redundancy, epoch, tag, name, slot, role, mask = HELLO_BODY.unpack(body)
        out.update(delay=delay, layout=layout, redundancy=redundancy, epoch=epoch, state_tag=tag.hex(),
                   name=name.rstrip(b'\0').decode('utf-8', 'replace'), slot=None if slot == NO_SLOT else slot,
                   role=role, mask=mask)
    elif kind == DATA:
        if len(body) < DATA_BODY.size:
            raise ProtocolError('short DATA')
        fields = DATA_BODY.unpack_from(body)
        frame, stall, hash_ack, sealed, sched_through = fields[:5]
        acks = list(fields[5:5 + SLOTS])
        nblocks, hcount, nsched = fields[5 + SLOTS], fields[6 + SLOTS], fields[7 + SLOTS]
        at = DATA_BODY.size
        if hcount > MAX_HASHES or nblocks > SLOTS or nsched > MAX_SCHED:
            raise ProtocolError('bad DATA counts')
        blocks = []
        for _ in range(nblocks):
            if len(body) < at + BLOCK.size:
                raise ProtocolError('short block')
            slot, count, flags, first = BLOCK.unpack_from(body, at)
            at += BLOCK.size
            if slot >= SLOTS or len(body) < at + count * INPUT.size or flags & ~BLOCK_RLE:
                raise ProtocolError('bad block')
            items = [INPUT.unpack_from(body, at + i * INPUT.size) for i in range(count)]
            at += count * INPUT.size
            if flags & BLOCK_RLE:
                items = [(r, a & 0xFFFFFF) for r, a in items for _ in range((a >> 24) + 1)]
            blocks.append((slot, first, [(bytes(r), a) for r, a in items]))
        if len(body) < at + hcount * HASH_REPORT.size:
            raise ProtocolError('bad DATA size')
        hashes = [HASH_REPORT.unpack_from(body, at + i * HASH_REPORT.size) for i in range(hcount)]
        at += hcount * HASH_REPORT.size
        sched = []
        for _ in range(nsched):
            if len(body) < at + SCHED_HEAD.size:
                raise ProtocolError('short scheduled entry')
            s_seq, k, count, bulk = SCHED_HEAD.unpack_from(body, at)
            at += SCHED_HEAD.size
            if not 0 < count <= MAX_SCHED_WRITES or len(body) < at + count * SCHED_WRITE.size:
                raise ProtocolError('bad scheduled entry')
            sched.append((s_seq, k, [SCHED_WRITE.unpack_from(body, at + i * SCHED_WRITE.size) for i in range(count)],
                          bulk))
            at += count * SCHED_WRITE.size
        if len(body) != at:
            raise ProtocolError('bad DATA size')
        out.update(frame=frame, stall=stall, hash_ack=hash_ack, sealed=sealed, sched_through=sched_through,
                   acks=acks, blocks=blocks, hashes=hashes, sched=sched)
    elif kind == BYE:
        if len(body) != 4:
            raise ProtocolError('bad BYE size')
        out['reason'] = struct.unpack_from('<H', body)[0]
    else:
        raise ProtocolError(f'unknown kind {kind}')
    return out


def session_id(state_sha, delay, layout, epoch=0):
    """The id every PC derives from the installed savestate's sha256 (hex), the input delay, the core layout and the
    epoch (each fight of a session, and each resync inside a fight, gets the next epoch)."""
    digest = hashlib.sha256(f'v4:{state_sha}:{delay}:{layout}:{epoch}'.encode()).digest()
    return struct.unpack('<I', digest[:4])[0] or 1
