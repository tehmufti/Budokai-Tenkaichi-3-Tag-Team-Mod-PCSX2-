"""Chunked on-demand EE RAM view for host builders written against snapshots.

A LazyRam is a full-size bytearray whose bytes are fetched from a PINE-style
client (``read(address, length)``) the first time a slice, an index or a
``struct.unpack_from`` touches them. Builders keep their ``ram[a:b]`` and
``struct.unpack_from('<I', ram, p)`` idioms; the only cooperation needed is
the ``patched()`` context, which routes ``struct.unpack_from`` through the
fetch. Chunks are 64 KiB aligned, so pointer scans over one actor or model
cost one exchange instead of thousands. Nothing here writes to the guest.

Unfetched bytes read as POISON, not zero. Anything that reaches the buffer
without going through this class - the buffer protocol, ``bytes(ram)``,
``struct.unpack_from`` outside ``patched()`` - therefore yields 0xCCCCCCCC
words, which fail every pointer, identity and magic guard loudly instead of
building a program out of plausible zeros. ``bytearray(ram)`` copies are the
one thing callers must not do; use ``view()`` instead.

``view(overrides)`` makes a second LazyRam sharing the same source whose
bytes differ only at the override addresses (an analysis view for builders
that require a workspace to look empty or a hook to look restored). It copies
only the chunks its parent already holds and fetches the rest on demand.

A LazyRam is NOT an atomic snapshot: with no guest hold, one pass can straddle
a guest mutation. Callers that need consistency must bracket a pass with a
guest generation word and repeat it if that word moved.
"""
import contextlib
import struct

SIZE = 0x8000000
CHUNK = 0x10000
POISON = 0xCC
_original_unpack_from = struct.unpack_from
_poison_chunk = bytes([POISON]) * CHUNK


class LazyRam(bytearray):
    """Full-size bytearray filled from ``client.read`` on first access."""

    def __init__(self, client, *, parent=None, overrides=None):
        # Grow in place: the old bytes()*SIZE initializer briefly allocated two
        # full EE images for every constructor while combat was held.
        super().__init__([POISON])
        self *= SIZE
        self.client = client
        self.parent = parent
        self.generation = 0
        self.parent_generation = parent.generation if parent is not None else None
        self.overrides = dict(overrides or {})
        self.fetched = bytearray(SIZE // CHUNK)
        self.exchanges = 0
        self.bytes_fetched = 0
        if parent is not None:
            for index, flag in enumerate(parent.fetched):
                if flag:
                    lo = index * CHUNK
                    bytearray.__setitem__(self, slice(lo, lo + CHUNK),
                                          bytearray.__getitem__(parent, slice(lo, lo + CHUNK)))
                    self.fetched[index] = 1
            self._write_overrides(0, SIZE)

    def _write_overrides(self, address, length):
        for at, data in self.overrides.items():
            lo,hi=max(at,address),min(at+len(data),address+length)
            if hi<=lo:continue
            # Overrides may cross a chunk boundary. Apply every resident
            # intersection without fetching or modifying its absent neighbors.
            for index in range(lo//CHUNK,(hi-1)//CHUNK+1):
                if self.fetched[index]:
                    left,right=max(lo,index*CHUNK),min(hi,(index+1)*CHUNK)
                    bytearray.__setitem__(self,slice(left,right),data[left-at:right-at])

    def fetch(self, address, length):
        """Ensure [address, address+length) is resident; one read per gap run."""
        if self.parent is not None and self.parent.generation != self.parent_generation:
            raise RuntimeError('LazyRam analysis view belongs to an expired snapshot')
        if length <= 0:
            return
        if not 0 <= address <= SIZE - length:
            raise IndexError('LazyRam fetch outside EE RAM')
        first, last = address // CHUNK, (address + length - 1) // CHUNK
        index = first
        while index <= last:
            if self.fetched[index]:
                index += 1
                continue
            end = index
            while end + 1 <= last and not self.fetched[end + 1]:
                end += 1
            lo, hi = index * CHUNK, (end + 1) * CHUNK
            if self.parent is not None:
                self.parent.fetch(lo, hi - lo)
                data = bytearray.__getitem__(self.parent, slice(lo, hi))
            else:
                data = self.client.read(lo, hi - lo)
                self.exchanges += 1
                self.bytes_fetched += hi - lo
            if len(data) != hi - lo:
                raise IOError('Short EE RAM read')
            bytearray.__setitem__(self, slice(lo, hi), data)
            for i in range(index, end + 1):
                self.fetched[i] = 1
            if self.overrides:self._write_overrides(lo,hi-lo)
            index = end + 1
        if self.overrides:
            self._write_overrides(address, length)

    def prefetch(self, ranges):
        for address, length in ranges:
            self.fetch(address, length)

    def invalidate(self):
        """Expire a snapshot and poison its resident chunks before reusing it.

        Uninstrumented buffer reads must never see stale, plausible pointers.
        Only the few MiB actually fetched need clearing, not the whole 128 MiB.
        """
        for index, flag in enumerate(self.fetched):
            if flag:
                lo=index*CHUNK
                bytearray.__setitem__(self,slice(lo,lo+CHUNK),_poison_chunk)
        self.fetched = bytearray(SIZE // CHUNK)
        self.exchanges = self.bytes_fetched = 0
        self.generation += 1

    def __getitem__(self, key):
        if isinstance(key, slice):
            start, stop, step = key.indices(SIZE)
            if step != 1:
                raise ValueError('LazyRam supports contiguous slices only')
            if stop > start:
                self.fetch(start, stop - start)
        else:
            index = key if key >= 0 else SIZE + key
            self.fetch(index, 1)
        return bytearray.__getitem__(self, key)

    def __iter__(self):
        raise TypeError('Refusing to iterate 128 MiB of EE RAM; slice what you need')

    def view(self, overrides, *, reuse=None):
        """A lazily fetched copy whose bytes differ only at ``overrides``."""
        merged = dict(self.overrides)
        merged.update({int(k): bytes(v) for k, v in overrides.items()})
        if reuse is None:return LazyRam(self.client, parent=self, overrides=merged)
        if reuse is self:raise ValueError('An analysis view cannot replace its parent')
        reuse.invalidate()
        reuse.client=self.client;reuse.parent=self;reuse.parent_generation=self.generation
        reuse.overrides=merged
        # No copy is needed: the child will obtain already-fetched chunks from
        # its current parent on demand, with no additional transport reads.
        return reuse

    def resident(self):
        return sum(self.fetched) * CHUNK


def _lazy_unpack_from(fmt, buffer, offset=0):
    if isinstance(buffer, LazyRam):
        buffer.fetch(offset, struct.calcsize(fmt))
    return _original_unpack_from(fmt, buffer, offset)


@contextlib.contextmanager
def patched():
    """Route struct.unpack_from through LazyRam.fetch for the duration."""
    previous = struct.unpack_from
    struct.unpack_from = _lazy_unpack_from
    try:
        yield
    finally:
        struct.unpack_from = previous
