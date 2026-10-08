"""Four-seat input transport for prepared three/four-human matches.

P1/P2 retain PCSX2's existing mappings (or the check-in's override, controller_assignment).
P3/P4 use private native-format pad records, published at a game-frame boundary by the
controller hub (controller_hub.BattleSink). A short guest lease neutralizes held buttons if
the host stops, a controller disconnects, or the match changes. Installed only for
three/four-player modes; unused seats cannot claim a fighter.
"""
from native_map import A, elf_path
import math
import struct
from prototype import Assembler,ROOT,elf_reader
import fresh_team_combat as core
import battle_mode_policy as modes
from input_script import chain_head as legacy_chain_head,RECORDS,RECORD_STRIDE
from input_binding import SDL_BUTTONS,MASKS

BASE,END=0x06C10000,0x06C20000
FRAME,PAD=BASE,BASE+0x1800
TRAMPOLINE,PAD_TAIL=BASE+0x2800,BASE+0x2840
PADS,MAILBOX,CONTROL=BASE+0x4000,BASE+0x5000,BASE+0xF000
MAGIC=0x51494E31
LEASE=15 # half a second of guest updates
NATIVE=elf_reader(elf_path(ROOT))[2]
SAVED=tuple(range(2,16))+(24,25,31)
BUTTON_MAP={'FaceSouth':'cross','FaceEast':'circle','FaceWest':'square','FaceNorth':'triangle',
            'Back':'select','Start':'start','LeftStick':'l3','RightStick':'r3',
            'LeftShoulder':'l1','RightShoulder':'r1','DPadUp':'up','DPadRight':'right',
            'DPadDown':'down','DPadLeft':'left'}


def chain_head(ram,hook,trampoline,native):
    """Admit exact current participation/input wrappers, not arbitrary jumps."""
    import team_participation as part
    import quad_lifecycle as lifecycle
    head=struct.unpack_from('<2I',ram,hook)
    for at,emitter in ((part.FRAME,part.frame_code),(lifecycle.FRAME,lifecycle.frame),(FRAME,frame)):
        if head!=((2<<26)|(at>>2),0):continue
        template=emitter(0)
        sites=[i for i in range(0,len(template),4) if struct.unpack_from('<I',template,i)[0] in (2<<26,3<<26)]
        if len(sites)!=1:raise ValueError('Ambiguous four-player frame predecessor')
        previous=(struct.unpack_from('<I',ram,at+sites[0])[0]&0x3FFFFFF)<<2
        if not 0x100000<=previous<0x8000000:raise ValueError('Invalid four-player frame predecessor')
        blob=emitter(previous)
        if ram[at:at+len(blob)]!=blob:raise ValueError('Four-player frame predecessor changed')
        return at,[]
    return legacy_chain_head(ram,hook,trampoline,native)


def save(a):
    a.addiu(29,29,-0xE0)
    for i,r in enumerate(SAVED):a.i(63,r,29,8*i)


def restore(a,skip=()):
    for i,r in enumerate(SAVED):
        if r not in skip:a.i(55,r,29,8*i)
    a.addiu(29,29,0xE0)


def gate(a,fail):
    core.gate(a,fail);a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,fail)
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,fail)
    a.lw(9,8,8);a.branch(5,9,10,fail);a.lw(9,8,12);a.branch(4,9,0,fail)


def frame(previous):
    a=Assembler(FRAME);save(a);gate(a,'done')
    a.lw(9,8,28);a.branch(5,9,0,'stale')
    a.lw(9,8,16);a.lw(11,8,20);a.branch(5,9,11,'fresh')
    a.label('stale')
    a.lw(9,8,24);a.i(11,11,9,LEASE);a.branch(4,11,0,'neutral')
    a.addiu(9,9,1);a.sw(9,8,24);a.jump('held')
    a.label('fresh');a.sw(9,29,0xD0)
    # Snapshot first, then check both writer flag and publication sequence.
    # A host write can span several PINE stores; never publish a torn pad.
    for seat in range(2):
        a.li(9,MAILBOX+seat*32)
        for field in range(5):
            a.lw(11,9,field*4);a.sw(11,29,0xA0+seat*20+field*4)
    a.lw(9,8,28);a.branch(5,9,0,'stale')
    a.lw(9,8,16);a.lw(11,29,0xD0);a.branch(5,9,11,'stale')
    a.sw(9,8,20);a.sw(0,8,24)
    for seat in range(2):
        a.addiu(9,29,0xA0+seat*20);a.li(10,PADS+seat*RECORD_STRIDE)
        a.lw(11,9);a.sw(11,10,328)
        for src,dst in ((4,304),(8,308),(12,312),(16,316)):
            a.lw(11,9,src);a.sw(11,10,dst)
    a.jump('held')
    a.label('neutral')
    for seat in range(2):
        a.li(10,PADS+seat*RECORD_STRIDE)
        for off in (304,308,312,316,328):a.sw(0,10,off)
    a.label('held')
    for seat in range(2):
        a.li(10,PADS+seat*RECORD_STRIDE);a.lw(11,10,328);a.lw(12,10,332)
        a.r(0x27,12,12,0);a.r(0x24,12,12,11);a.sw(12,10,336);a.sw(12,10,340);a.sw(11,10,332)
        for off in (348,384,388,396,400):a.sw(0,10,off)
    a.label('done');restore(a);a.jump(previous);return a.finish()


def pad(previous):
    a=Assembler(PAD);save(a);gate(a,'native')
    # The existing consenting P1/P2 fusion retains its selected merged/swap
    # control policy. Unrelated seats must still resolve independently.
    a.li(9,modes.CONTROL);a.lw(10,9);a.li(11,modes.MAGIC);a.branch(5,10,11,'seats')
    a.lw(10,9,24);a.i(11,11,10,modes.emitted_actors());a.branch(4,11,0,'seats')
    a.r(0,10,0,10,2);a.li(11,core.POINTERS);a.r(0x2D,10,10,11);a.lw(10,10)
    a.branch(4,4,10,'native')
    a.label('seats')
    for seat in range(4):
        a.lw(9,8,0x40+seat*4);a.lw(10,8,8);a.r(0x2B,10,9,10);a.branch(4,10,0,f'next{seat}')
        a.r(0,9,0,9,2);a.li(10,core.POINTERS);a.r(0x2D,10,10,9);a.lw(10,10)
        a.branch(5,4,10,f'next{seat}')
        a.li(2,RECORDS+seat*RECORD_STRIDE if seat<2 else PADS+(seat-2)*RECORD_STRIDE)
        restore(a,skip=(2,));a.jr();a.label(f'next{seat}')
    a.label('native');restore(a);a.jump(previous);return a.finish()


def seats(mode,present,humans=4):
    """Physical seats, preserving the established P1/P2 roles."""
    return modes.human_seats(mode,humans,present)


@modes.matching_install
def target_plan(ram):
    """Keep the existing gesture/queue policy, resolve each human's own pad."""
    import lockon_queue as lock
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    previous=lock.legacy_previous(ram)
    mode=u(modes.CONTROL+12) if u(modes.CONTROL)==modes.MAGIC else modes.TEAMS
    options=dict(free_for_all=mode==modes.FFA,coop_controls=mode==modes.COOP)
    variant=lock.installed_variant(ram,previous,**options)
    if variant is None:raise ValueError('Unknown four-player target queue predecessor')
    before=lock.payload(previous,button_aware=variant,**options)
    after=lock.payload(previous,button_aware=variant,pad_resolver=A(0x1DC2A0),**options)
    if len(after)>lock.END-lock.CODE:raise ValueError('Four-player target queue exceeds reservation')
    if len(after)>len(before) and any(ram[lock.CODE+len(before):lock.CODE+len(after)]):
        base=lock.payload(previous,button_aware=variant)
        historical=(base+bytes(max(0,len(after)-len(base))))[len(before):len(after)]
        if ram[lock.CODE+len(before):lock.CODE+len(after)]!=historical:
            raise ValueError('Four-player target queue extension occupied')
    size=max(len(before),len(after))
    return dict(blocks=[dict(address=lock.CODE,expected_hex=ram[lock.CODE:lock.CODE+size].hex(),
                            data_hex=(after+bytes(size-len(after))).hex())])


@modes.matching_install
def build_memory(ram,subjects):
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    count,manager=u(core.MODE+4),u(core.ACTORS)
    if count not in modes.ACTOR_COUNTS or (u(core.MODE),u(core.MODE+8),u(core.MODE+12))!=(1,manager,count):
        raise ValueError('Four pads need a captured active match')
    if len(subjects) not in (2,3,4) or len(set(subjects))!=len(subjects) or any(not 0<=i<count for i in subjects):raise ValueError('Three or four distinct captured seats required')
    if any(ram[BASE:END]):raise ValueError('Quad pad reservation occupied')
    previous,extra=chain_head(ram,A(0x1C2A28),TRAMPOLINE,NATIVE)
    pad_previous,pad_extra=chain_head(ram,A(0x1DC2A0),PAD_TAIL,NATIVE)
    control=bytearray(0x80);struct.pack_into('<4I',control,0,MAGIC,manager,count,1)
    struct.pack_into('<I',control,24,LEASE);struct.pack_into('<4I',control,0x40,*(tuple(subjects)+(0xFFFFFFFF,)*(4-len(subjects))))
    data=[(p,b) for p,b,*_ in extra+pad_extra]
    data.extend(((FRAME,frame(previous)),(PAD,pad(pad_previous)),(CONTROL,bytes(control)),
        (PADS,bytes(2*RECORD_STRIDE)),(MAILBOX,bytes(64)),
        (A(0x1C2A28),struct.pack('<2I',(2<<26)|(FRAME>>2),0)),
        (A(0x1DC2A0),struct.pack('<2I',(2<<26)|(PAD>>2),0))))
    return dict(blocks=[dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=b.hex()) for p,b in data]+
                      target_plan(ram)['blocks'])


def normalize_axis(raw,deadzone=.18):
    v=max(-1.,min(1.,raw/32767.));m=abs(v)
    return 0. if m<=deadzone else math.copysign((m-deadzone)/(1-deadzone),v)


def encode_pad(button_names,axes):
    """SDL standard layout -> native digital word + two normalized sticks."""
    word=sum(MASKS[BUTTON_MAP[n]] for n in set(button_names) if n in BUTTON_MAP)
    if axes[4]>10000:word|=MASKS['l2']
    if axes[5]>10000:word|=MASKS['r2']
    sticks=[normalize_axis(v) for v in axes[:4]]
    for start in (0,2):
        length=math.hypot(*sticks[start:start+2])
        if length>1:sticks[start:start+2]=[v/length for v in sticks[start:start+2]]
    # Native poller also publishes dominant-axis directional bits.
    for start,shift in ((0,16),(2,20)):
        x,y=sticks[start:start+2]
        if abs(y)>=abs(x):word|=((4 if y>.5 else 8 if y<-.5 else 0)<<shift)
        else:word|=((2 if x>.5 else 1 if x<-.5 else 0)<<shift)
    return struct.pack('<I4f12x',word,*sticks)
