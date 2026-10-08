"""The host's fighter-update service for an online match (kit 2.0, Stage 4; see kit_services.py).

Run by the host's installation copy's Python with that copy's tools as the working folder:
    python kit_service.py --port P --token T --tools TOOLS --w1 0x07B38200
It runs the Tag Team Mod's own extra reload worker (CPU transformations, a taken-over teammate's transformation,
damaged costumes, Cell's absorption) against the host's game through RemotePine: every read goes to the host's game
now, every write is queued and SEALED before the next read - the host's session sends bulk to every PC and schedules
the control words for one frame on every PC.

Online variant of the worker's guest code (the IO stage is built per job and delivered in the packet, so nothing in
the match file changes): the IO stage's disc-pump poll `jal 0x265298` becomes `jal W1` (netplay_core's gate channel
1: the read completes at the same agreed frame on every PC), and its start-phase check of the native loader's pending
word (0x31E77C, which drains at a different moment on every PC) becomes a W1 pre-drain (the stage starts at the agreed
frame every PC's loader is idle). Kit 2.1: the background (unheld) IO path is ON online too - kit_prepare installs
its runner with the loader-idle test as a W1 pre-drain (background_online) - so the disc read runs while the fight
goes on, as offline; the held path stays for whatever the worker does not send to the background runner.
"""
import argparse
import json
import socket
import struct
import sys
import time
import traceback


class LinkError(RuntimeError):
    pass


class RemotePine:
    """The PineClient surface the mod's workers use, over the session's broker."""

    def __init__(self, port, token):
        self.sock = socket.create_connection(('127.0.0.1', port), timeout=60)
        self.file = self.sock.makefile('rb')
        self.rid = 0
        self.dirty = False
        self.call('hello', token=token)

    def call(self, op, **fields):
        self.rid += 1
        self.sock.sendall((json.dumps(dict(id=self.rid, op=op, **fields), separators=(',', ':')) + '\n').encode())
        line = self.file.readline()
        if not line:
            raise LinkError('the session closed the service link')
        m = json.loads(line)
        if m.get('id') != self.rid:
            raise LinkError('service link out of order')
        return m

    # writes are queued; a read seals them first (the broker does it on its side as well)
    def write_ranges(self, ranges):
        ranges = [(int(a), bytes(d)) for a, d in ranges]
        if ranges:
            self.call('write', writes=[[a, d.hex()] for a, d in ranges])
            self.dirty = True

    def write(self, address, data):
        self.write_ranges([(address, data)])

    def write_u32(self, address, value):
        self.write(address, struct.pack('<I', value & 0xFFFFFFFF))

    def seal(self):
        """Send the queued writes (they land at frame K on every PC) and wait until the host's game has applied
        them, so the next read sees them, exactly as offline (a write, then a read of it)."""
        if not self.dirty:
            return
        m = self.call('seal')
        self.dirty = False
        k = m.get('k')
        if k is None:
            return
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            frame, state = self.frame()
            if frame is None or state != 2 or frame > k:
                return
            time.sleep(0.01)
        raise LinkError(f'the host game did not reach frame {k}')

    def read_ranges(self, ranges):
        self.seal()
        ranges = [(int(a), int(n)) for a, n in ranges]
        out = []
        for i in range(0, len(ranges), 512):
            m = self.call('read', ranges=ranges[i:i + 512])
            out += [bytes.fromhex(h) for h in m['data']]
        return out

    def read(self, address, length):
        return self.read_ranges([(address, length)])[0]

    def read_u32(self, address):
        return struct.unpack('<I', self.read(address, 4))[0]

    def status(self):
        self.seal()
        return self.call('status')['status']

    def frame(self):
        m = self.call('frame')
        return m.get('frame'), m.get('state')

    def log(self, text):
        try:
            self.call('log', text=str(text)[:500])
        except (OSError, LinkError):
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.seal()

    def close(self):
        try:
            self.seal()
        finally:
            self.sock.close()


def netplay_variant(w1):
    """The online IO stage (see the module text): patch the preload builder's assembler."""
    import extra_reload_preload as preload
    from native_map import A
    import prototype
    pump, pending = A(0x265298), A(0x31E77C)
    zero_word = 0x07B4FFFC                     # the end of the netplay core's reservation: always 0
    base = prototype.Assembler

    class Online(base):
        def call(self, target, *args, **kwargs):
            return base.call(self, w1 if target == pump else target, *args, **kwargs)

        def li(self, reg, value, *args, **kwargs):
            if value == pending:
                # W1 pre-drain: start only at the agreed frame every PC's native loader is idle (status stays 0 and
                # the runner calls this stage again next frame); then the old check reads a word that is 0.
                base.call(self, w1)
                self.branch(4, 2, 0, 'done')
                return base.li(self, reg, zero_word, *args, **kwargs)
            return base.li(self, reg, value, *args, **kwargs)
    preload.Assembler = Online
    background_variant(w1)
    return Online


def background_variant(w1):
    """Kit 2.1: extra_reload_quiet's BACKGROUND runner (the unheld IO path) as kit_prepare installs it online: its
    loader-idle test reads the native loader's state / handle / pending words, which drain at a different moment on
    every PC; online they read a word that is always 0, and the job the runner calls keeps its own idle test - the W1
    pre-drain of its start phase (netplay_variant) - which starts the read at the agreed frame every PC's loader is
    idle. (A second W1 wait in the runner itself would take every agreement before the job's own start could: the
    first live test livelocked that way.) Patches the module's Assembler, so the worker's own check
    (background_code() == the installed bytes) recognises the online runner and uses the unheld path."""
    import extra_reload_quiet as quiet
    import prototype
    base = prototype.Assembler
    zero = 0x07B4FFFC

    class Online(base):
        def li(self, reg, value, *args, **kwargs):
            if value in (quiet.LOADER_STATE, quiet.LOADER_HANDLE, quiet.LOADER_PENDING):
                return base.li(self, reg, zero, *args, **kwargs)
            return base.li(self, reg, value, *args, **kwargs)
    quiet.Assembler = Online
    return Online


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, required=True)
    ap.add_argument('--token', required=True)
    ap.add_argument('--tools', required=True)
    ap.add_argument('--w1', required=True)
    ap.add_argument('--services', default='cpu_transform')
    args = ap.parse_args()
    sys.path.insert(0, args.tools)
    p = RemotePine(args.port, args.token)
    w1 = int(args.w1, 0)
    try:
        netplay_variant(w1)
        import extra_reload_worker
        import fighter_updates
        from fresh_team_combat import MODE
        from native_map import A
        BATTLE = A(0x2FEB38)

        def log(text):
            print(text, flush=True)
            p.log(text)
        while True:                                       # attach in combat only, as the mod's watcher does
            battle = p.read_u32(BATTLE)
            phase = p.read_u32(battle) if 0x100000 <= battle < 0x8000000 - 0x200 else -1
            if phase == 3:
                break
            if phase not in (0, 1, 2):
                log(f'the fight ended before combat (director {phase})')
                p.call('done', why='no combat')
                return 0
            time.sleep(0.2)
        def report(text):
            log(text)
            if 'timed out' in str(text) or 'refused' in str(text):         # kit 2.1 diagnostics: the runner's words
                try:
                    bg = struct.unpack('<16I', p.read(0x0765E000, 64))
                    gate = struct.unpack('<4I', p.read(0x07B01000 + 0xE0, 16))
                    log('background runner words ' + ' '.join(f'{w:x}' for w in bg) +
                        ' | gate local/seq/agreed/opened ' + ' '.join(f'{w:x}' for w in gate))
                except Exception as error:  # noqa: BLE001 - a diagnostic only
                    log(f'(background words unreadable: {error})')
        worker = extra_reload_worker.Worker(progress=report, cell_auxiliary=True)
        worker.attach(p)
        body = None
        if 'body_change' in args.services.split(','):
            body = fighter_updates.attach_body(p, progress=log)
        background = p.read_u32(0x0765E000) == 0x424B4731       # extra_reload_quiet BG_CONTROL magic (kit 2.1)
        log('fighter updates attached (online: ' + ('unheld background IO path' if background else 'held IO path') +
            ', W1 gate' + (', Body Change' if body else '') + ')')
        idle = 0.05
        while True:
            battle = p.read_u32(BATTLE)
            phase = p.read_u32(battle) if 0x100000 <= battle < 0x8000000 - 0x200 else -1
            if phase not in (0, 1, 2, 3):
                log(f'the fight is over (director {phase}): the service ends')
                p.call('done', why=f'director {phase}')
                break
            if phase == 3 and p.read_u32(MODE) == 1:
                fighter_updates.poll(p, worker, body, None)
                if worker.failure:
                    raise RuntimeError(worker.failure)
                if body is not None and body.failure:
                    raise RuntimeError(body.failure)
            p.seal()
            time.sleep(fighter_updates.poll_delay(worker, body, None, idle))
    except LinkError:
        return 0
    except Exception as error:  # noqa: BLE001 - reported to the session, which ends the match as No contest
        print(traceback.format_exc(), flush=True)
        p.log(f'FAILED: {type(error).__name__}: {error}')
        return 2
    finally:
        try:
            p.close()
        except OSError:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
