"""Keep native counter teleports and melee clashes with their actual opponents.

Multi-contact evaluates a hit with the real attacker/defender in scope. A
counter used to lose that scope before its queued animation ran, so the
defender could teleport toward its old lock-on target. Only newly accepted
counter flags create a short-lived binding; normal hits never change lock-on.
The native animations, inputs, strength and outcomes are left in place.
"""
import struct
from native_map import A, FLAG, CRC, SERIAL, ticks
from prototype import Assembler
import beam_clash as beam
import dash_clash as dash
import dash_contact_guard as body
import multi_contact as multi
import fresh_team_combat as core
import battle_mode_policy as policy

CODE, END = dash.CODE+0x6000, dash.CODE+0xE000
HIT, CAPTURE, LOOKUP, RESOLVE = CODE, CODE+0x1000, CODE+0x2000, CODE+0x3400
FRAME, BODY, OLD_FRAME, OLD_RESOLVE = CODE+0x3C00, CODE+0x4800, CODE+0x5000, CODE+0x5100
GATE = CODE+0x5200
CONTROL, ROWS, STRIDE, MAGIC = CODE+0x6000, CODE+0x6100, 64, 0x56504731
CLOCK, CAPTURED, REJECTED = CONTROL+4, CONTROL+8, CONTROL+12
# The old fields are cleared by native flag dispatch; only the new edges
# observed inside this one confirmed contact can claim the response.
DEFENDER_FLAGS = (0x68,0x69,0x6A,0x6B,0x6D,0x6F,0x70,0x74,0x75,0x76,0x77,0x79,0x7B,0x7C,0x7D)
SOURCE_FLAGS = (0x6C,0x6F,0x7A,0x7E)
RESPONSE_ACTIONS = (32,33,34,43,44,45,46,47,48,49,50,56,57,60,61,65,69,121,122,123,124,125,126,189,201,202)
RESPONSE_RANGES = ((32,3),(43,8),(56,2),(60,2),(65,1),(69,1),(121,6),(189,1),(201,2))
MAX_AGE = ticks(180, base=30)
BODY_SITE, BODY_NATIVE = A(0x1C92C4), A(0x1DEEA8)
JUMP, CALL, NATIVE = multi.JUMP, multi.CALL, multi.NATIVE


def flags(a, actor, values, result):
    """Pack current and next-update flag banks without calling native code."""
    a.move(result,0)
    for i,number in enumerate(values):
        n=FLAG(number)
        for bank in (0x1085,0x10AD):
            a.i(36,8,actor,bank+(n>>3));a.i(12,8,8,1<<(n&7))
            a.r(2,8,0,8,n&7)  # srl
            if i:a.r(0,8,0,8,i)
            a.r(0x25,result,result,8)


def busy(a, actor, yes):
    for offset in dash.throws.ACTION_FIELDS:
        a.lw(8,actor,offset)
        for first,length in RESPONSE_RANGES:
            a.addiu(9,8,-first);a.i(11,9,9,length);a.branch(5,9,0,yes)
    flags(a,actor,DEFENDER_FLAGS+SOURCE_FLAGS,12);a.branch(5,12,0,yes)


def authored(a, actor, yes):
    for offset in dash.throws.ACTION_FIELDS:
        a.lw(8,actor,offset)
        for first,length in ((180,8),(236,80)):
            a.addiu(9,8,-first);a.i(11,9,9,length);a.branch(5,9,0,yes)
    multi.contact.paired_pending(a,actor,yes)


def gate_code():
    a=Assembler(GATE);a.addiu(29,29,-16);a.i(63,31,29,0)
    a.call(multi.GATE);a.branch(4,2,0,'done');a.call(dash.GATE)
    a.branch(4,2,0,'done');a.li(8,CONTROL);a.lw(8,8);a.li(9,MAGIC)
    a.branch(4,8,9,'done');a.move(2,0)
    a.label('done');a.i(55,31,29,0);a.addiu(29,29,16);a.jr()
    b=a.finish();assert len(b)<=CONTROL-GATE;return b


def capture_code():
    # a0 is the responding fighter, a1 is the attacker it actually countered.
    a=Assembler(CAPTURE);beam.save(a);a.move(16,4);a.move(17,5)
    a.call(multi.VALID);a.branch(4,2,0,'done')
    for actor in (16,17):authored(a,actor,'done')
    a.move(4,16);a.call(LOOKUP);a.branch(4,2,0,'bind');a.branch(5,2,17,'done')
    a.label('bind');a.lw(18,16);a.lw(19,17)
    dash.throws.model(a,16,20,'done');dash.throws.model(a,17,21,'done')
    a.r(0,8,0,18,6);a.li(22,ROWS);a.r(0x2D,22,22,8)
    a.sw(17,22);a.sw(16,22,4);a.sw(20,22,8);a.sw(21,22,12)
    for model,offset in ((20,16),(21,28)):
        for field,relative in ((20,0),(12,4),(5728,8)):
            a.lw(8,model,field);a.sw(8,22,offset+relative)
    a.li(8,CLOCK);a.lw(8,8);a.sw(8,22,40);a.sw(19,22,44)
    # A successful counter deliberately faces/targets its real attacker. The
    # resolver binding also survives unrelated automatic retarget requests.
    a.r(0,8,0,18,2);a.li(9,core.TABLE);a.r(0x2D,9,9,8);a.sw(19,9)
    a.li(8,CAPTURED);a.lw(9,8);a.addiu(9,9,1);a.sw(9,8)
    a.label('done');beam.restore(a);a.jr()
    b=a.finish();assert len(b)<=LOOKUP-CAPTURE;return b


def lookup_code():
    a=Assembler(LOOKUP);beam.save(a);a.move(16,4)
    a.move(22,0);a.move(23,0);a.move(18,0)
    a.call(GATE);a.branch(4,2,0,'done')
    # Native AI role aliases must keep their explicitly scoped pair.
    body.scan(a,16,19,'self','done');a.lw(8,16);a.branch(5,8,19,'done')
    a.r(0,8,0,19,6);a.li(18,ROWS);a.r(0x2D,18,18,8)
    a.lw(17,18);a.branch(4,17,0,'done');a.lw(8,18,4);a.branch(5,8,16,'clear')
    a.move(4,16);a.move(5,17);a.call(multi.VALID);a.branch(4,2,0,'clear')
    for actor in (16,17):authored(a,actor,'clear')
    for actor,stored,identity in ((16,8,16),(17,12,28)):
        dash.throws.model(a,actor,20,'clear');a.lw(8,18,stored);a.branch(5,8,20,'clear')
        for field,relative in ((20,0),(12,4),(5728,8)):
            a.lw(8,20,field);a.lw(9,18,identity+relative);a.branch(5,8,9,'clear')
    a.li(8,CLOCK);a.lw(8,8);a.lw(9,18,40);a.r(0x23,8,8,9)
    a.i(11,8,8,MAX_AGE);a.branch(4,8,0,'clear')
    busy(a,16,'yes');a.jump('clear')
    a.label('yes');a.move(22,17);a.lw(23,18,44);a.jump('done')
    a.label('clear');a.sw(0,18)
    a.label('done');a.move(2,22);a.move(3,23);beam.restore(a,(2,3));a.jr()
    b=a.finish();assert len(b)<=RESOLVE-LOOKUP;return b


def hit_code():
    # Preserve the native call's input and output registers. Metadata lives in
    # an outer stack frame, never in native caller-saved registers across it.
    a=Assembler(HIT);a.addiu(29,29,-0x40);a.i(63,31,29,0)
    beam.save(a);a.move(16,4);a.move(17,0)
    a.sw(0,29,beam.SAVE_SIZE+24);a.call(GATE);a.branch(4,2,0,'native')
    a.move(4,16);a.call(core.RESOLVER);a.move(17,2)
    a.move(4,16);a.move(5,17);a.call(multi.VALID);a.branch(4,2,0,'native')
    a.sw(16,29,beam.SAVE_SIZE+8);a.sw(17,29,beam.SAVE_SIZE+12)
    flags(a,17,DEFENDER_FLAGS,12);a.sw(12,29,beam.SAVE_SIZE+16)
    flags(a,16,SOURCE_FLAGS,12);a.sw(12,29,beam.SAVE_SIZE+20)
    a.addiu(8,0,1);a.sw(8,29,beam.SAVE_SIZE+24)
    a.label('native');beam.restore(a);a.call(A(0x1C97C0))
    beam.save(a);a.lw(8,29,beam.SAVE_SIZE+24);a.branch(4,8,0,'done')
    a.lw(16,29,beam.SAVE_SIZE+8);a.lw(17,29,beam.SAVE_SIZE+12)
    a.move(4,16);a.move(5,17);a.call(multi.VALID);a.branch(4,2,0,'done')
    flags(a,17,DEFENDER_FLAGS,12);a.lw(9,29,beam.SAVE_SIZE+16)
    a.r(0x27,9,9,0);a.r(0x24,12,12,9);a.branch(4,12,0,'done')
    a.move(4,17);a.move(5,16);a.call(CAPTURE)
    flags(a,16,SOURCE_FLAGS,12);a.lw(9,29,beam.SAVE_SIZE+20)
    a.r(0x27,9,9,0);a.r(0x24,12,12,9);a.branch(4,12,0,'done')
    a.move(4,16);a.move(5,17);a.call(CAPTURE)
    a.label('done');beam.restore(a);a.i(55,31,29,0);a.addiu(29,29,0x40);a.jr()
    b=a.finish();assert len(b)<=CAPTURE-HIT;return b


def resolve_code():
    a=Assembler(RESOLVE)
    # Most lookups have no counter binding. Keep their extra cost to a leaf
    # row check rather than saving every register/calling both scene gates.
    a.addiu(29,29,-16);a.i(63,8,29,0);a.i(63,9,29,8)
    a.lw(8,4);a.i(11,9,8,policy.ENGINE_ACTORS);a.branch(4,9,0,'empty')
    a.r(0,8,0,8,6);a.li(9,ROWS);a.r(0x2D,8,8,9)
    a.lw(9,8);a.branch(4,9,0,'empty');a.lw(9,8,4);a.branch(5,9,4,'empty')
    a.i(55,8,29,0);a.i(55,9,29,8);a.addiu(29,29,16);beam.save(a)
    a.call(GATE);a.branch(4,2,0,'old')
    a.li(8,multi.CONTEXT);a.lw(8,8);a.branch(5,8,0,'old')
    # Authored dash/beam participant routing takes precedence.
    for active in (dash.ACTIVE,beam.ACTIVE):
        a.li(8,active);a.lw(8,8);a.branch(5,8,0,'old')
    a.call(LOOKUP);a.branch(4,2,0,'old');beam.restore(a,(2,3));a.jr()
    a.label('old');beam.restore(a);a.jump(OLD_RESOLVE)
    a.label('empty');a.i(55,8,29,0);a.i(55,9,29,8);a.addiu(29,29,16);a.jump(OLD_RESOLVE)
    b=a.finish();assert len(b)<=FRAME-RESOLVE;return b


def frame_code():
    a=Assembler(FRAME);beam.save(a);a.call(GATE);a.branch(4,2,0,'clear_rows')
    a.li(8,A(0x3337B8));a.lw(8,8);a.i(12,9,8,0x100);a.branch(5,9,0,'old')
    a.li(8,CLOCK);a.lw(9,8);a.addiu(9,9,1);a.sw(9,8)
    a.call(dash.VALID);a.branch(4,2,0,'old')
    # VALID verifies captured identities but previously omitted HP/presence
    # once ACTIVE became 2. Release a running exchange on KO/removal as well.
    a.li(8,dash.ACTORS);a.lw(4,8);a.lw(5,8,4);a.call(multi.VALID)
    a.branch(5,2,0,'old');a.call(dash.ABORT);a.jump('old')
    a.label('clear_rows');a.li(8,ROWS);a.addiu(9,0,policy.ENGINE_ACTORS)
    a.label('clear');a.sw(0,8);a.addiu(8,8,STRIDE);a.addiu(9,9,-1);a.branch(5,9,0,'clear')
    a.label('old');beam.restore(a);a.jump(OLD_FRAME)
    b=a.finish();assert len(b)<=BODY-FRAME;return b


def body_code():
    # Native s1/s0 are source/proposed defender. Its touching flag may belong
    # to a different opponent, exactly like the earlier phantom-dash bug.
    a=Assembler(BODY);beam.save(a);a.call(GATE);a.branch(4,2,0,'old')
    a.move(4,17);a.move(5,16);a.call(multi.VALID);a.branch(4,2,0,'deny')
    body.scan(a,17,18,'body_source','deny')
    a.r(0,8,0,18,6);a.li(19,body.ROWS);a.r(0x2D,19,19,8)
    a.lw(8,19);a.branch(5,8,16,'deny')
    for actor,pointer,identity in ((17,4,12),(16,8,24)):
        dash.throws.model(a,actor,20,'deny');a.lw(8,19,pointer);a.branch(5,8,20,'deny')
        for field,relative in ((20,0),(12,4),(5728,8)):
            a.lw(8,20,field);a.lw(9,19,identity+relative);a.branch(5,8,9,'deny')
    a.label('old');beam.restore(a);a.jump(BODY_NATIVE)
    a.label('deny');a.li(8,REJECTED);a.lw(9,8);a.addiu(9,9,1);a.sw(9,8)
    a.move(2,0);beam.restore(a,(2,));a.jr()
    b=a.finish();assert len(b)<=OLD_FRAME-BODY;return b


def trampoline(base, predecessor, original):
    a=Assembler(base)
    for word in struct.unpack('<2I',original[:8]):a.emit(word)
    a.jump(predecessor+8);return a.finish()


def gather_overlay():
    data=bytearray(multi.gather_code());old=CALL(A(0x1C97C0));found=0
    for offset in range(0,len(data),4):
        if data[offset:offset+4]==old:data[offset:offset+4]=CALL(HIT);found+=1
    if found!=2:raise ValueError('Counter evaluation call layout changed')
    return bytes(data)


def native_dependencies():
    # This wrapper uses the audited native s1/source and s0/defender pair.
    # Verify the assignment/branch block and the source argument delay slot.
    move_source=struct.pack('<I',(17<<21)|(4<<11)|0x2D)
    move_target=struct.pack('<I',(2<<21)|(16<<11)|0x2D)
    if NATIVE(BODY_SITE+4,4)!=move_source or NATIVE(BODY_SITE-12,4)!=move_target:
        raise ValueError('Native counter participant register layout changed')
    return [(BODY_SITE-24,NATIVE(BODY_SITE-24,24))]


def pieces():
    frame,resolve=dash.frame_code(),multi.resolve_code()
    out=[(HIT,hit_code()),(CAPTURE,capture_code()),(LOOKUP,lookup_code()),
         (RESOLVE,resolve_code()),(FRAME,frame_code()),(BODY,body_code()),
         (GATE,gate_code()),
         (OLD_FRAME,trampoline(OLD_FRAME,dash.FRAME,frame)),
         (OLD_RESOLVE,trampoline(OLD_RESOLVE,multi.RESOLVE,resolve)),
         (dash.FRAME,JUMP(FRAME)+frame[8:]),(multi.RESOLVE,JUMP(RESOLVE)+resolve[8:]),
         (multi.GATHER,gather_overlay()),(BODY_SITE,CALL(BODY)+NATIVE(BODY_SITE+4,4)),
         (CONTROL,struct.pack('<I',MAGIC))]
    spans=sorted((p,p+len(b)) for p,b in out)
    if any(end>q for (_,end),(q,_) in zip(spans,spans[1:])):raise ValueError('Vanish pair guard overlaps')
    return out


def overlay(ram):
    if not any(ram[CODE:END]):return []
    out=pieces()+native_dependencies()
    for p,b in out:
        if ram[p:p+len(b)]!=b:raise ValueError(f'Changed vanish pair guard {p:08X}')
    return out


@policy.matching_install
def build_memory(ram, source='<prepared>'):
    if len(ram)!=0x8000000:raise ValueError('Vanish pair guard requires 128 MiB RAM')
    if multi.prior_manifest(ram,dash.build_memory)['blocks']:
        raise ValueError('Install complete captured contact/clash chain first')
    if not body.overlay(ram):raise ValueError('Install body-contact provenance first')
    if overlay(ram):return dict(source=str(source),blocks=[])
    if ram[BODY_SITE:BODY_SITE+8]!=NATIVE(BODY_SITE,8) or NATIVE(BODY_SITE,4)!=CALL(BODY_NATIVE):
        raise ValueError('Native counter body-contact call changed')
    for p,b in native_dependencies():
        if ram[p:p+len(b)]!=b:raise ValueError('Native counter participant assignment changed')
    for p,b in ((dash.FRAME,dash.frame_code()),(multi.RESOLVE,multi.resolve_code()),(multi.GATHER,multi.gather_code())):
        if ram[p:p+len(b)]!=b:raise ValueError(f'Unknown vanish guard predecessor {p:08X}')
    payload=pieces()+[(CONTROL+4,bytes(0xFC)),(ROWS,bytes(STRIDE*policy.ENGINE_ACTORS))]
    return dict(serial=SERIAL,crc=CRC,source=str(source),
                status='ACTUAL COUNTER OPPONENTS AND LIVING CLASH PARTICIPANTS',
                blocks=[dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=b.hex()) for p,b in payload])
