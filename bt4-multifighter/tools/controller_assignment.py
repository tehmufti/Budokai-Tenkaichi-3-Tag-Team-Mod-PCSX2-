"""P1/P2 input from the controller check-in, for modded matches only.

Opt-in per seat: PCSX2's own bindings remain untouched while the hook is disarmed, and a seat whose PASS bit is
set keeps PCSX2's record of that port (a controller PCSX2 already uses as that player, a keyboard, the default
order). Mod-read seats receive the same standardized pad layout already used by P3/P4. The authenticated mailbox
has no executable writes and expires to neutral input. The controller hub's thread is the only writer of the
mailbox, the PASS mask, the armed word and the private words while a sink is attached (controller_hub.AssignmentSink).
"""
import struct
from prototype import Assembler
import controller_mailbox as transport
import quad_controller as pads
import mode_menu

CODE, CONTROL, MAILBOX, TOKEN = 0x06930000, 0x06933000, 0x06933100, 0x06933080
END, MAGIC = 0x06934000, 0x43415331
# CONTROL: +0 magic, +12 armed, +16 host sequence, +20 consumed sequence, +24 stale count, +28 writer flag,
# +0x30 PASS (bit0 seat 1, bit1 seat 2: a set bit leaves PCSX2's record untouched), +0x40+12k private previous,
# menu and repeat words, +0x80 TOKEN, +0x100 MAILBOX, +0x180 published state.
PASS = 0x30


def payload():
    # Called after the native poll and before menu/actor input consumers.
    # The outer native-mode wrapper preserves registers and HI/LO.
    from quad_menu_input import MENU_BITS
    a=Assembler(CODE);a.li(8,CONTROL);a.lw(9,8);a.li(10,MAGIC)
    a.branch(5,9,10,'done');a.lw(9,8,12);a.branch(4,9,0,'done')
    a.addiu(29,29,-0x60)
    a.lw(9,8,28);a.branch(5,9,0,'stale')
    a.lw(9,8,16);a.lw(10,8,20);a.branch(4,9,10,'stale');a.sw(9,29,80)
    for seat in range(2):
        a.li(9,MAILBOX+32*seat)
        for field in range(5):a.lw(10,9,4*field);a.sw(10,29,seat*20+4*field)
    a.lw(9,8,28);a.branch(5,9,0,'stale')
    a.lw(9,8,16);a.lw(10,29,80);a.branch(5,9,10,'stale')
    a.sw(9,8,20);a.sw(0,8,24)
    for seat in range(2):
        for field in range(5):a.lw(10,29,seat*20+4*field);a.sw(10,8,0x180+seat*32+field*4)
    a.jump('publish')
    a.label('stale');a.lw(9,8,24);a.i(11,10,9,pads.LEASE)
    a.branch(4,10,0,'neutral');a.addiu(9,9,1);a.sw(9,8,24);a.jump('publish')
    a.label('neutral')
    for seat in range(2):
        for field in range(5):a.sw(0,8,0x180+seat*32+field*4)
    a.label('publish')
    for seat in range(2):
        # A pass-through seat keeps PCSX2's own record untouched (its port's pad, keyboard or default order).
        a.lw(9,8,PASS);a.i(12,9,9,1<<seat);a.branch(5,9,0,f'next{seat}')
        # Use a private previous state; the native poll's previous word belongs
        # to PCSX2's original device, which may be another assigned player.
        a.li(12,mode_menu.PAD+seat*0x1C0);a.lw(10,8,0x180+seat*32)
        a.lw(11,8,0x40+seat*12);a.r(0x27,9,11,0);a.r(0x24,9,10,9)
        a.sw(10,12,328);a.sw(10,12,332);a.sw(9,12,336);a.sw(9,12,340)
        a.sw(10,8,0x40+seat*12)
        for offset in (348,384,388):a.sw(0,12,offset)
        for field,offset in enumerate((304,308,312,316),1):
            a.lw(9,8,0x180+seat*32+field*4);a.sw(9,12,offset)
        a.move(13,0)
        for mask,translated in MENU_BITS:
            tag=f's{seat}_{translated}';a.li(9,mask);a.r(0x24,9,10,9);a.branch(4,9,0,tag)
            a.li(9,translated);a.r(0x25,13,13,9);a.label(tag)
        a.lw(11,8,0x44+seat*12);a.r(0x27,9,11,0);a.r(0x24,9,13,9);a.sw(9,12,396)
        a.sw(13,8,0x44+seat*12);a.sw(13,12,400)
        a.branch(5,13,11,f'new{seat}');a.lw(9,8,0x48+seat*12);a.addiu(9,9,1);a.sw(9,8,0x48+seat*12)
        a.i(11,10,9,15);a.branch(5,10,0,f'norepeat{seat}');a.i(12,10,9,3)
        a.branch(4,10,0,f'next{seat}')
        a.label(f'norepeat{seat}');a.sw(0,12,400);a.jump(f'next{seat}')
        a.label(f'new{seat}');a.sw(0,8,0x48+seat*12)
        a.label(f'next{seat}')
    a.addiu(29,29,0x60);a.label('done');a.jr()
    code=a.finish();assert CODE+len(code)<CONTROL;return code


def code_pieces():return [(CODE,payload())]


class Mailbox(transport.Mailbox):
    TOKEN_ADDRESS=TOKEN
    CONTROL,MAILBOX=CONTROL,MAILBOX
    # PCSX2's own port records are read (never written) for press matching: status, state and the raw read.
    READS={CONTROL:16,CONTROL+16:8,mode_menu.PAD+0x104:24,mode_menu.PAD+0x1C0+0x104:24}
    # Private previous/menu/repeat words: one seat at a time (seat 1 at +0x40, seat 2 at +0x4C).
    WRITES={MAILBOX:64,CONTROL+16:4,CONTROL+28:4,CONTROL+12:4,CONTROL+PASS:4,CONTROL+0x40:12,CONTROL+0x4C:12}

    @classmethod
    def identity(cls,p):
        if p.read(CODE,len(payload()))!=payload():raise ValueError('The controller assignment service is not installed in this PCSX2. Close PCSX2, then start Play again')
        return {CONTROL:p.read(CONTROL,16),CODE:p.read(CODE,16)}


class Owner:
    """The P1/P2 override's sink in the controller hub. No thread starts or ends here.

    attach(p, capture): ('menu',) or ('battle', match capture). allow_arm is the watcher's `custom` rule (a modded
    match or Modded Modes page, never native modes, never online); the hub arms from the check-in roster."""
    def __init__(self,pid,hub=None):self.pid=pid;self.hub=hub;self.service=None;self.capture=None

    def attach(self,p,capture,*,allow_arm=True,in_match=None,rewound=False):
        in_match=bool(capture and capture[0]=='battle') if in_match is None else in_match
        if self.service is not None:
            if self.service.failure:raise RuntimeError(self.service.failure)
            if self.capture==capture and self.service.active and not rewound:
                if (self.service.allow_arm,self.service.in_match)!=(allow_arm,in_match):
                    self.hub.configure(self.service,allow_arm=allow_arm,in_match=in_match)
                return
        self.close()
        if self.hub is None:raise RuntimeError('The controller reader is not running')
        if self.hub.state=='failed':raise transport.MailboxUnavailable(self.hub.failure or 'SDL controller input is unavailable')
        self.hub.start()
        # Disarm before staging data; the hub thread arms (PASS, private words, one packet, then armed).
        p.write_u32(CONTROL+12,0)
        p.write(CONTROL,struct.pack('<8I',MAGIC,0,0,0,0,0,pads.LEASE,0)+bytes(0x1E0))
        import controller_hub
        mailbox=Mailbox.attach(p,self.pid)
        self.service=self.hub.add_sink(controller_hub.AssignmentSink(mailbox,capture,allow_arm=allow_arm,in_match=in_match))
        self.capture=capture

    def disable(self,p):
        """No sink: the watcher disarms through PINE (only while no assignment sink exists)."""
        self.close();p.write_u32(CONTROL+12,0)

    def close(self):
        try:
            if self.service is not None:self.service.close()
        finally:
            self.service=None;self.capture=None
