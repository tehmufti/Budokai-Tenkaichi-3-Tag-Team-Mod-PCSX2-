"""PINE link to the kit's PCSX2 that runs netplay_core (TTM Online Kit copy of p22/online/pinelink.py; only the
import of netplay_core and listener_pid differ).

Original text: PINE link to one scratch PCSX2 that runs tools/netplay_core (the host half's only way into the guest).

PineLink wraps pine.PineClient: before connecting it checks that the PINE port is served by the process this rig
started (so a session never writes into somebody else's emulator: the user's PCSX2 or another agent's rig), checks
the running game's serial, and reconnects once on a dropped connection. PCSX2 serves one PINE client at a time,
so while a session holds the link nothing else may connect to that instance.

CoreView (mixed into PineLink and into fakeguest.FakeGuest) reads and writes the core's rings with the fewest
bytes: only the OUTGOING / HASHES slots of the frames asked for, and INCOMING writes with every data word first and
every commit tag last (netplay_core.incoming_writes).
"""
import os
import struct
import sys
import threading
import time
from pathlib import Path

import kit_paths  # noqa: E402,F401  (TTM Online Kit: the bundled mod modules are in netplay/modtools)
import netplay_core as nc  # noqa: E402
from kit_win import listener_pid  # noqa: E402,F401  (standard library only: no psutil in the kit)


def slot_ranges(base, slots, entry, first, last):
    """[(address, length, first frame of the range)] covering frames first..last of a ring (wrap split in two)."""
    if last < first:
        return []
    first = max(first, last - slots + 1)
    out, frame = [], first
    while frame <= last:
        slot = frame % slots
        count = min(last - frame + 1, slots - slot)
        out.append((base + slot * entry, count * entry, frame))
        frame += count
    return out


class CoreView:
    """netplay_core accessors over read_ranges/write_ranges."""

    def control(self):
        return nc.parse_control(self.read_ranges([(nc.CONTROL, nc.CONTROL_BYTES)])[0])

    def _entries(self, base, slots, entry, first, last, parse):
        ranges = slot_ranges(base, slots, entry, first, last)
        if not ranges:
            return {}
        out = {}
        for (address, length, frame), data in zip(ranges, self.read_ranges([(a, n) for a, n, _ in ranges])):
            for i in range(length // entry):
                frame_i, item = parse(data[i * entry:(i + 1) * entry])
                if frame_i == frame + i:
                    out[frame_i] = item
        return out

    def outgoing(self, first, last):
        """{frame: (raw8, aux)} for the committed captures of frames first..last (aux: the gate word the game captured
        with the input on core layout 2; the capture's game frame on layout 1)."""
        def parse(b):
            tag = int.from_bytes(b[8:12], 'little')
            return tag - 1, (bytes(b[:8]), int.from_bytes(b[12:16], 'little'))
        return self._entries(nc.OUTGOING, nc.OUT_SLOTS, nc.OUT_ENTRY, first, last, parse)

    def hashes(self, first, last):
        """{frame: parsed HASHES entry} for frames first..last."""
        def parse(b):
            entry = nc.parse_hash(bytes(b))
            return entry['frame'], entry
        return self._entries(nc.HASHES, nc.HASH_SLOTS, nc.HASH_ENTRY, first, last, parse)

    def publish(self, slot, frames, aux=0):
        """Commit {frame: raw8 or (raw8, aux)} into INCOMING[slot] (data first, then each frame's tag + aux as one
        aligned 8-byte write)."""
        if frames:
            self.write_ranges(nc.incoming_writes(slot, frames, aux))

    def configure(self, **values):
        self.write_ranges(nc.config_writes(**values))

    def abort(self):
        self.configure(abort=1)

    def write_sched(self, seq, frame, writes):
        """One SCHED ring entry (netplay_core OPT_SCHED): body first, the tag word (frame + 1) last."""
        address, body = nc.sched_entry(seq, frame, writes)
        self.write_ranges([(address + 4, body[4:]), (address, body[:4])])

    def set_sealed(self, frame):
        """CONTROL.sched_sealed: this PC's game may run every frame up to `frame` (its entries are all written)."""
        self.w32(nc.CONTROL + nc.F['sched_sealed'], frame)

    def u32(self, address):
        return struct.unpack('<I', self.read_ranges([(address, 4)])[0])[0]

    def w32(self, address, value):
        self.write_ranges([(address, struct.pack('<I', value & 0xFFFFFFFF))])


class PineLink(CoreView):
    def __init__(self, port, pid=None, timeout=5.0, serial=__import__('kit_adapter').state_name(0).split(' (')[0], owner=None):
        """owner: a callable giving the PID behind the PINE port (default: the TCP listener's, Windows); Linux passes
        the kit emulator's Unix-socket check (kit_emu.LinuxEmulator.pine_owner)."""
        self.port, self.pid, self.timeout, self.serial = port, pid, timeout, serial
        self.owner = owner
        self.client, self.info = None, None
        self.lock = threading.RLock()          # one PINE client per PCSX2: every thread of the kit shares this one

    def connect(self):
        import pine
        if self.pid is not None:
            owner = self.owner() if self.owner else listener_pid(self.port)
            if owner != self.pid:
                raise RuntimeError(f'PINE {self.port} is served by process {owner}, not by {self.pid}')
        client = pine.PineClient(port=self.port, timeout=self.timeout)
        client.connect()
        try:
            info = client.info()
            if self.serial and info.get('serial') != self.serial:
                raise RuntimeError(f'PINE {self.port}: running game {info.get("serial")!r}, expected {self.serial}')
        except BaseException:
            client.close()
            raise
        self.client, self.info = client, info
        return self

    def close(self):
        if self.client is not None:
            self.client.close()
            self.client = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *_):
        self.close()

    def _call(self, name, *args):
        with self.lock:
            for attempt in (0, 1):
                if self.client is None:
                    self.connect()
                try:
                    return getattr(self.client, name)(*args)
                except (OSError, RuntimeError):
                    self.close()
                    if attempt:
                        raise
                    time.sleep(0.05)

    def read_ranges(self, ranges):
        return self._call('read_ranges', list(ranges))

    def write_ranges(self, ranges):
        return self._call('write_ranges', list(ranges))

    def read(self, address, length):
        return self.read_ranges([(address, length)])[0]

    def write(self, address, data):
        self.write_ranges([(address, data)])

    def status(self):
        return self._call('status')

    def save_state(self, slot):
        return self._call('save_state', slot)

    def load_state(self, slot):
        return self._call('load_state', slot)
