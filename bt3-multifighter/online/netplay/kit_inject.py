"""Frame-exact guest pad input for the host's PRIVATE match-making copy (no host key messages).

The private copy is driven from inside the game. A small guest program replaces the native pad poll's raw read
(sub_122A38's `jal 0x295FB8` at A(0x122B08), the read every menu, the title and the battle loop use) and, while
enabled, gives port 0 the button word of the current command instead of the keyboard pad:

  CONTROL +0 magic 'TTMI'   +4 enable          +8 request (host)      +12 done (guest: = request when finished)
          +16 buttons (raw bits, active high)  +20 hold polls          +24 gap polls (neutral after the press)
          +28 hold left     +32 gap left       +36 active              +40 port-0 polls (a progress counter)

A command is a press of `buttons` for exactly `hold` native polls followed by `gap` neutral polls, so the game's own
edge detection sees one clean press at whatever speed the emulator runs; the host never has to time anything. The
host writes buttons/hold/gap and then request = done + 1 (the request word last), and waits for done == request.

CODE ARRIVES THROUGH PCSX2'S OWN PATCH ENGINE. The program and its hook word are a pnach (pnach_text) that only the
private copy's cheats folder holds; PCSX2 applies it on its EE thread at every vsync, exactly like the mod's own boot
hooks. PINE only ever writes the CONTROL page, which is a separate 4 KiB page from the program (a PINE write into a
page holding recompiled code clears blocks from another thread while the EE may be running them: live, Oct 15, it
closed PCSX2 twice in 20 cold builds). While disabled the program is the native read with an extra stack frame.

A prepared match never keeps the hook: kit_prepare._convert restores the native jal in the exported match
(unhook_blocks), offline, before any other check reads that RAM. The program itself and its (disabled) CONTROL page
stay: a checkpoint can be saved while the EE is inside the program or inside the raw read it called, and that frame
must still return through real code on every peer. Nothing else uses the reservation, which lies outside every guest
range the mod reserves (heap1 ends at 0x06000000, the hub starts at 0x06400000, native preparation's packet buffer
and the online core live at 0x07800000 and above) and was zero in every base, capture and match checked (Oct 15).
Guest rules: a 32-byte stack frame (16-byte aligned), no k0/k1, native addresses through A(), the hook's predecessor
and the reservation verified before use (the CONTROL page must be empty or ours).
"""
import contextlib
import hashlib
import struct
import time

from native_map import A

CODE, CONTROL, END = 0x06300000, 0x06301000, 0x06302000
MAGIC = 0x494D5454                                   # 'TTMI'
F = dict(magic=0, enable=4, request=8, done=12, buttons=16, hold=20, gap=24, hold_left=28, gap_left=32,
         active=36, polls=40)
CONTROL_SIZE = 44
NEUTRAL_LO, NEUTRAL_HI = 0x7F7FFFFF, 0x00007F7F      # raw bytes ff ff 7f 7f 7f 7f 00 00
# Raw pad bits (active high here; the raw word itself is active low).
BUTTONS = dict(select=0x0001, l3=0x0002, r3=0x0004, start=0x0008, up=0x0010, right=0x0020, down=0x0040,
               left=0x0080, l2=0x0100, r2=0x0200, l1=0x0400, r1=0x0800, triangle=0x1000, circle=0x2000,
               cross=0x4000, square=0x8000)
PNACH_SUFFIX = '_TTMPrivatePad.pnach'


def site():
    return A(0x122B08)


def rawread():
    return A(0x295FB8)


def jal(target):
    return 0x0C000000 | (target >> 2)


def code():
    from prototype import Assembler
    t0, t1, t2, t3, t4, t5 = 8, 9, 10, 11, 12, 13
    s0, s2, s3 = 16, 18, 19
    a = Assembler(CODE)
    a.addiu(29, 29, -0x20)
    a.i(63, 31, 29, 0); a.i(63, s0, 29, 8); a.i(63, s3, 29, 16)
    a.move(s0, 5)                                       # a1 = the 18-byte raw buffer (record+0x114)
    a.call(rawread())                                    # the real read (a0/a1 untouched)
    a.move(s3, 2)
    a.li(t0, CONTROL)
    a.lw(t1, t0, F['magic']); a.li(t2, MAGIC); a.branch(5, t1, t2, 'done')
    a.lw(t1, t0, F['enable']); a.branch(4, t1, 0, 'done')
    a.branch(5, s2, 0, 'done')                           # port 0 only
    a.lw(t1, t0, F['polls']); a.addiu(t1, t1, 1); a.sw(t1, t0, F['polls'])
    a.move(t5, 0)                                        # t5 = buttons pressed this poll
    a.lw(t1, t0, F['active']); a.branch(5, t1, 0, 'run')
    a.lw(t1, t0, F['request']); a.lw(t2, t0, F['done']); a.branch(4, t1, t2, 'write')
    a.addiu(t1, 0, 1); a.sw(t1, t0, F['active'])
    a.lw(t1, t0, F['hold']); a.sw(t1, t0, F['hold_left'])
    a.lw(t1, t0, F['gap']); a.sw(t1, t0, F['gap_left'])
    a.label('run')
    a.lw(t3, t0, F['hold_left']); a.branch(6, t3, 0, 'gap')
    a.addiu(t3, t3, -1); a.sw(t3, t0, F['hold_left'])
    a.lw(t5, t0, F['buttons']); a.jump('finished')
    a.label('gap')
    a.lw(t3, t0, F['gap_left']); a.branch(6, t3, 0, 'finished')
    a.addiu(t3, t3, -1); a.sw(t3, t0, F['gap_left'])
    a.label('finished')
    a.lw(t3, t0, F['hold_left']); a.lw(t4, t0, F['gap_left']); a.r(0x25, t3, t3, t4)      # or
    a.branch(5, t3, 0, 'write')
    a.sw(0, t0, F['active']); a.lw(t1, t0, F['request']); a.sw(t1, t0, F['done'])
    a.label('write')
    a.i(12, t5, t5, 0xFFFF)                              # andi
    a.r(0x27, t5, t5, 0)                                 # nor: active low
    a.i(12, t5, t5, 0xFFFF)
    a.li(t1, NEUTRAL_LO & 0xFFFF0000); a.r(0x25, t5, t5, t1)
    # The buffer is record+0x114 (word aligned); store whole words.
    a.sw(t5, s0, 0); a.li(t1, NEUTRAL_HI); a.sw(t1, s0, 4)
    a.sw(0, s0, 8); a.sw(0, s0, 12); a.i(41, 0, s0, 16)  # sh zero: the rest of the 18 bytes
    a.addiu(s3, 0, 18)
    a.label('done')
    a.move(2, s3)
    a.i(55, 31, 29, 0); a.i(55, s0, 29, 8); a.i(55, s3, 29, 16)
    a.addiu(29, 29, 0x20)
    a.jr()
    data = a.finish()
    assert CODE + len(data) <= CONTROL, hex(len(data))
    return data


def pnach_text():
    """The private copy's patch: the program, then the hook word (applied on the EE thread at every vsync)."""
    program = code()
    lines = ['// TTM Online private match-making copy only: guest pad (kit_inject). Never installed for play.']
    for offset in range(0, len(program), 4):
        lines.append(f'patch=1,EE,{CODE + offset:08X},word,{struct.unpack_from("<I", program, offset)[0]:08X}')
    lines.append(f'patch=1,EE,{site():08X},word,{jal(CODE):08X}')
    return ('\n'.join(lines) + '\n').encode('ascii')


def pnach_name(serial, crc):
    """PCSX2's name for a cheat file of the disc: SLUS-21678_428113C2..., whichever way the profile spells the
    serial (the disc's own file name SLUS_216.78 or PCSX2's SLUS-21678)."""
    serial = str(serial).upper().replace('_', '-').replace('.', '')
    return f'{serial}_{str(crc).upper()}{PNACH_SUFFIX}'


def identity():
    """SHA-256 of the guest bytes this pad puts into the private copy (part of the neutral base's identity)."""
    return hashlib.sha256(pnach_text()).hexdigest()


def unhook_blocks(ram):
    """[(address, bytes)] that unhook an exported private RAM image: the native jal at the hook site and the pad
    disabled; the program stays (see the module docstring); [] when the image never had the pad. ValueError for any
    other bytes there."""
    u = lambda a: struct.unpack_from('<I', ram, a)[0]
    program = code()
    word = u(site())
    reserved = bytes(ram[CODE:END])
    if word == jal(rawread()) and not any(reserved):
        return []
    if word not in (jal(rawread()), jal(CODE)):
        raise ValueError(f'the native pad read holds {word:#010x}, not the native read or the private pad')
    if reserved[:len(program)] != program or any(reserved[len(program):CONTROL - CODE]):
        raise ValueError('the private pad reservation holds a program the kit does not know')
    control = reserved[CONTROL - CODE:]
    if any(control[CONTROL_SIZE:]) or (any(control[:CONTROL_SIZE]) and struct.unpack_from('<I', control)[0] != MAGIC):
        raise ValueError('the private pad control page holds foreign data')
    out = []
    if word != jal(rawread()):
        out.append((site(), struct.pack('<I', jal(rawread()))))
    if any(control[:CONTROL_SIZE]) and struct.unpack_from('<I', control, F['enable'])[0] != 0:
        out.append((CONTROL + F['enable'], bytes(4)))
    return out


class InjectError(RuntimeError):
    pass


class PadUnavailable(InjectError):
    """PCSX2 kept failing to answer within the bound (not a wrong program or hook)."""


def transient_errors():
    """What a busy emulator answers for a moment (a savestate being written, a VM transition): retried within the
    caller's bound. A wrong program or hook word (InjectError) is never retried."""
    try:
        from pine import PineError
    except ImportError:                                 # the unit tests' fake PINE
        PineError = RuntimeError
    return (OSError, PineError)


class Injector:
    """The private copy's guest pad. `pine` returns a new PINE client (a context manager)."""

    def __init__(self, pine, check=lambda: None, sleep=time.sleep):
        self.pine, self.check, self.sleep = pine, check, sleep
        self.installed = False

    @contextlib.contextmanager
    def conn(self, client=None):
        """PCSX2 serves one PINE connection at a time: a caller that holds one passes it in."""
        if client is not None:
            yield client
        else:
            with self.pine() as c:
                yield c

    def retry(self, fn, timeout, client=None):
        """fn(c) until it returns, retrying transient PINE errors on new connections (never on a caller's own)."""
        end = time.monotonic() + timeout
        while True:
            self.check()
            try:
                with self.conn(client) as c:
                    return fn(c)
            except InjectError:
                raise
            except transient_errors() as error:
                if client is not None or time.monotonic() > end:
                    raise PadUnavailable(f'PCSX2 did not answer the private pad ({type(error).__name__}: {error})')
            self.sleep(0.05)

    # ---- enable / disable ------------------------------------------------------------------------------------------
    def present(self, c):
        """True when PCSX2 has applied the pad patch (program + hook); InjectError for foreign bytes there."""
        program = code()
        word = struct.unpack('<I', c.read(site(), 4))[0]
        if word == jal(rawread()):
            return False                                 # the patch is not applied yet (boot) or not installed
        if word != jal(CODE):
            raise InjectError(f'The native pad read is not the expected one ({word:#010x})')
        if c.read(CODE, len(program)) != program:
            raise InjectError('A different program owns the private pad hook')
        return True

    def install(self, timeout=20.0):
        """Wait for the patch engine to place the pad, then enable it through its CONTROL page (data only)."""
        end = time.monotonic() + timeout

        def enable(c):
            if not self.present(c):
                return False
            control = c.read(CONTROL, END - CONTROL)
            magic = struct.unpack_from('<I', control)[0]
            if (any(control[CONTROL_SIZE:]) or magic not in (0, MAGIC) or
                    (magic == 0 and any(control[:CONTROL_SIZE]))):
                raise InjectError('The private pad control page is not empty')
            if magic != MAGIC:
                c.write(CONTROL, struct.pack('<11I', MAGIC, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
            # A command interrupted by a savestate load would otherwise resume. Disabled first, the guest cannot
            # finish an old command between reading `done` and clearing the request.
            c.write(CONTROL + F['enable'], struct.pack('<I', 0))
            done = struct.unpack('<I', c.read(CONTROL + F['done'], 4))[0]
            c.write(CONTROL + F['request'], struct.pack('<I', done))
            c.write(CONTROL + F['hold_left'], struct.pack('<3I', 0, 0, 0))
            c.write(CONTROL + F['enable'], struct.pack('<I', 1))
            return True
        while not self.retry(enable, max(0.1, end - time.monotonic())):
            if time.monotonic() > end:
                raise PadUnavailable('PCSX2 did not apply the private pad patch')
            self.sleep(0.02)
        self.installed = True

    def polls(self, client=None, timeout=10.0):
        return self.retry(lambda c: struct.unpack('<I', c.read(CONTROL + F['polls'], 4))[0], timeout, client)

    def wait_polls(self, count, timeout):
        """Wait until the hooked poll ran `count` more times (proof the hook is live)."""
        start = self.polls()
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.check()
            if (self.polls() - start) & 0xFFFFFFFF >= count:
                return True
            self.sleep(0.02)
        return False

    def remove(self, frame_word=None, timeout=20.0, client=None):
        """Disable the pad (the game reads the native pad again). The code stays until the export conversion removes
        it from the exported match; nothing but the CONTROL page is ever written through PINE."""
        def disable(c):
            if struct.unpack('<I', c.read(CONTROL, 4))[0] == MAGIC:
                c.write(CONTROL + F['enable'], struct.pack('<I', 0))
        self.retry(disable, timeout, client)
        self.installed = False

    # ---- presses -------------------------------------------------------------------------------------------------
    def press(self, *names, hold=3, gap=3, timeout=5.0, client=None):
        """One press of the named buttons (together); returns once the game has polled it fully. A transient PINE
        error while issuing rewrites the SAME request number, so a retry can never become a second press."""
        mask = 0
        for name in names:
            mask |= BUTTONS[name]
        target = []

        def issue(c):
            if struct.unpack('<I', c.read(CONTROL + F['enable'], 4))[0] != 1 or \
                    struct.unpack('<I', c.read(site(), 4))[0] != jal(CODE):
                raise InjectError('The private pad is not enabled')
            if not target:
                target.append((struct.unpack('<I', c.read(CONTROL + F['done'], 4))[0] + 1) & 0xFFFFFFFF)
            c.write(CONTROL + F['buttons'], struct.pack('<3I', mask, hold, gap))
            c.write(CONTROL + F['request'], struct.pack('<I', target[0]))
        self.retry(issue, timeout, client)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.retry(lambda c: struct.unpack('<I', c.read(CONTROL + F['done'], 4))[0], timeout, client) == \
                    target[0]:
                return True
            self.sleep(0.01)
        raise InjectError(f'The game did not poll the private press {"+".join(names)} within {timeout:.0f} s')
