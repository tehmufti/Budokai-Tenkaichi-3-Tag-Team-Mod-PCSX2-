"""Private P3/P4 selector input; no native multitap translation is assumed."""
import struct
from prototype import Assembler
import mode_menu
import roster_selection_guard as guard
import quad_controller as pads
import controller_mailbox as transport

CODE,CONTROL,MAILBOX,TOKEN=0x06C30000,0x06C3F000,0x06C3F100,0x06C3F080
MAGIC=0x514D4931
PAD_STRIDE=0x1C0
# Native 0x2574F0 uses left/right/down/up, NOT up/down/left/right.
# Include its digital-direction aliases and shoulder/stick commands too.
MENU_BITS=((0x10080,0x200001),(0x20020,0x400002),
           (0x40040,0x800004),(0x80010,0x1000008),
           (0x100000,0x10),(0x200000,0x20),(0x400000,0x40),(0x800000,0x80),
           (0x2000,0x100),(0x4000,0x200),(0x1000,0x400),(0x8000,0x800),
           (8,0x1000),(1,0x2000),(0x400,0x4000),(0x100,0x8000),
           (0x800,0x10000),(0x200,0x20000),(2,0x40000),(4,0x80000))


def payload():
    """a0 seat 2/3 -> v0 edge, v1 repeat, with a frame-based dead-input lease."""
    a=Assembler(CODE);a.move(2,0);a.move(3,0)
    a.li(8,CONTROL);a.lw(9,8);a.li(10,MAGIC);a.branch(5,9,10,'done')
    # Both P3 and P4 may be read in the same selector frame. Age the host
    # lease once per native pad update, not once per controller read.
    a.li(10,mode_menu.CONTROL+24);a.lw(10,10);a.lw(9,8,0x50)
    a.branch(4,9,10,'check_lease');a.sw(10,8,0x50)
    a.lw(9,8,28);a.branch(5,9,0,'stale')
    a.lw(9,8,16);a.lw(10,8,20);a.branch(4,9,10,'stale')
    a.sw(9,8,20);a.sw(0,8,24);a.jump('read')
    a.label('stale');a.lw(9,8,24);a.addiu(9,9,1);a.sw(9,8,24)
    a.label('check_lease');a.lw(9,8,24);a.i(11,10,9,15);a.branch(4,10,0,'neutral')
    a.label('read');a.addiu(9,4,-2);a.i(11,10,9,2);a.branch(4,10,0,'done')
    a.r(0,10,0,9,5);a.li(11,MAILBOX);a.r(0x21,11,11,10);a.lw(10,11)
    for mask,out in MENU_BITS:
        tag=f'button{out}';a.li(11,mask);a.r(0x24,11,10,11);a.branch(4,11,0,tag)
        a.li(12,out);a.r(0x25,3,3,12);a.label(tag)
    a.r(0,9,0,9,2);a.r(0x21,8,8,9);a.lw(10,8,0x40)
    a.r(0x27,11,10,0);a.r(0x24,2,3,11);a.sw(3,8,0x40)
    a.branch(5,3,10,'new');a.lw(10,8,0x48);a.addiu(10,10,1);a.sw(10,8,0x48)
    a.i(11,11,10,15);a.branch(5,11,0,'no_repeat');a.i(12,11,10,3)
    a.branch(4,11,0,'done');a.jump('no_repeat')
    a.label('new');a.sw(0,8,0x48);a.jr()
    a.label('no_repeat');a.move(3,0);a.jr()
    a.label('neutral');a.sw(0,8,0x40);a.sw(0,8,0x44)
    a.label('done');a.jr();return a.finish()


ROUTE=0x06C31000

def route_payload():
    """Scoped selector only: a0 seat 1..4 or 5 shared; t5/t6 edge/repeat, v0 host Back.

    Host Back resets the selector's release gate. This lives in the routing
    reservation because the caller's native menu-code reservation is full.
    """
    a=Assembler(ROUTE);a.addiu(29,29,-0x10);a.i(63,31,29,0)
    a.addiu(9,0,5);a.branch(4,4,9,'shared_inputs')
    a.addiu(9,4,-1);a.li(12,mode_menu.PAD)
    # Private P3/P4 input has a guest-frame lease and native menu edge/repeat
    # translation; P1/P2 keep PCSX2's existing controller mappings.
    a.i(11,10,9,2);a.branch(4,10,0,'private_pad')
    a.branch(4,9,0,'source');a.addiu(12,12,PAD_STRIDE)
    a.label('source');a.lw(13,12,0x18C);a.lw(14,12,0x190)
    a.jump('source_ready');a.label('private_pad')
    a.move(4,9);a.call(CODE);a.move(13,2);a.move(14,3)
    a.jump('source_ready')
    a.label('shared_inputs')
    # Pick one complete edge/repeat pair, never OR opposing directions or
    # confirm/cancel from different controllers. Poll both private pads every
    # frame so their edge tracking and timeout remain current.
    a.move(13,0);a.move(14,0)
    for seat in range(4):
        if seat<2:
            a.li(12,mode_menu.PAD+seat*PAD_STRIDE);a.lw(2,12,0x18C);a.lw(3,12,0x190)
        else:
            a.addiu(4,0,seat);a.call(CODE)
        a.r(0x25,9,13,14);a.branch(5,9,0,f'shared_next{seat}')
        a.move(13,2);a.move(14,3);a.label(f'shared_next{seat}')
    a.label('source_ready');a.move(2,0)
    # Read remapped P1, not a physical controller number. Polling above still
    # consumes the interrupted picker's edge, including private P3/P4 input.
    from coop_character_select import BACK, READY
    a.li(12,mode_menu.PAD);a.lw(9,12,0x18C);a.i(12,9,9,BACK)
    a.branch(4,9,0,'return')
    a.move(2,9);a.move(13,9);a.move(14,0)
    # Never combine Cancel with another pad's confirm/direction. Require a
    # release afterward, so a held confirmation cannot undo the back action.
    a.li(8,guard.CONTROL);a.sw(0,8,READY)
    a.label('return');a.i(55,31,29,0);a.addiu(29,29,0x10);a.jr()
    data=a.finish();assert ROUTE+len(data)<CONTROL;return data


class Mailbox(transport.Mailbox):
    TOKEN_ADDRESS=TOKEN
    CONTROL,MAILBOX=CONTROL,MAILBOX
    READS={CONTROL:16,CONTROL+16:8}
    WRITES={MAILBOX:64,CONTROL+16:4,CONTROL+28:4}
    @classmethod
    def identity(cls,p):
        code=payload()
        if p.read(CODE,len(code))!=code:raise ValueError('Four-player selector code changed')
        scene=p.read_u32(mode_menu.SCENE_MANAGER)
        if not 0x100000<=scene<0x2000000 or p.read_u32(scene+0x18)!=40:
            raise ValueError('Four-player selection is not active')
        if p.read_u32(guard.CONTROL)!=guard.MAGIC:raise ValueError('Missing native mode menu')
        p.write(CONTROL,struct.pack('<4I',MAGIC,scene,2,1))
        return {CONTROL:p.read(CONTROL,16),mode_menu.SCENE_MANAGER:struct.pack('<I',scene),
                guard.CONTROL:struct.pack('<I',guard.MAGIC)}


class Owner(transport.Owner):
    """P3/P4 at character selection: one controller-hub sink (controller_hub.SelectorSink). seats 'private' (the
    check-in's seats 3-4) or 'extras' (all controllers allowed with fewer than three humans)."""
    def __init__(self,pid,**options):
        super().__init__(pid,**options);self.mailbox_type=Mailbox

    def sink(self,mailbox,capture):
        import controller_hub
        return controller_hub.SelectorSink(mailbox,capture,mode=self.seats)

    def attach(self,p,capture,*,rewound=False):
        if self.service is not None:
            if self.service.failure:raise RuntimeError(self.service.failure)
            if self.capture==capture and not rewound and self.service.active:
                if self.attached_seats!=self.seats:
                    self.hub.configure(self.service,mode=self.seats);self.attached_seats=self.seats
                return
        self.close()
        self.add(p,capture) # Unavailable input is reported once; P3/P4 stay neutral off Windows.
