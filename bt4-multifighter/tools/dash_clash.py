"""Actual-participant routing for native dash/melee clashes250..252.

Installed immediately after the guarded beam_clash stage. Both native coordinators
share manager+64, so one dash OR beam struggle may own it at a time. Native
strength/input, animations and winner flags remain untouched.
"""
from native_map import A, CRC, FLAG, SERIAL, elf_path
import struct
from types import SimpleNamespace
from prototype import Assembler
import fresh_team_combat as core
import clash_bounds as bounds
import extra_throws as throws
import battle_mode_policy as policy
import team_participation as participation
from battle_mode_policy import ACTOR_COUNTS

CODE, CONTROL, END, MAGIC = 0x07180000, 0x0718F000, 0x07190000, 0x44434C31
GATE, VALID, START = CODE, CODE+0x400, CODE+0xC00
FRAME, ABORT, ACTOR = CODE+0x1800, CODE+0x2400, CODE+0x2C00
RESOLVE, CONTACT, PARTICIPANT = CODE+0x3000, CODE+0x3400, CODE+0x3800
ANIMATION_SIDE, EFFECT_SIDE = CODE+0x3C00, CODE+0x4000
ACTIVE, ACTORS, MODELS, INDICES = CONTROL+16, CONTROL+64, CONTROL+72, CONTROL+80
ACTOR_CALLS = (A(0x1D87E4),A(0x1D8808),A(0x1D883C),A(0x1D888C),A(0x1D88B0),
               A(0x1D88E4),A(0x1D8908),A(0x1D893C),A(0x1D8D8C),A(0x1D935C),
               A(0x1D9368),A(0x1D948C),A(0x1D9498),A(0x1D9544),A(0x1D9550))


def start_code():
    import beam_clash as beam
    a=Assembler(START);beam.save(a);a.call(GATE);a.branch(4,2,0,'old')
    a.li(8,core.PAIR+4);a.lw(8,8);a.branch(5,8,0,'reject')
    a.li(8,A(0x3337B8));a.lw(8,8);a.i(12,8,8,0x2000);a.branch(5,8,0,'reject')
    a.li(22,CONTROL);a.lw(8,22,16);a.branch(5,8,0,'reject')
    a.li(8,beam.ACTIVE);a.lw(8,8);a.branch(5,8,0,'reject')
    a.lw(8,22,4);a.lw(8,8,64);a.branch(5,8,0,'reject')
    for side,actor in ((0,16),(1,17)):
        a.li(8,core.POINTERS);a.move(19,0);a.lw(23,22,8)
        a.label(f'scan{side}');a.lw(9,8);a.branch(4,9,actor,f'found{side}')
        a.addiu(19,19,1);a.addiu(8,8,4);a.branch(5,19,23,f'scan{side}');a.jump('reject')
        a.label(f'found{side}');a.lw(8,actor);a.branch(5,8,19,'reject')
        a.r(0,8,0,19,2);a.addiu(9,22,0x100);a.r(0x2D,9,9,8)
        a.lw(9,9);a.branch(5,9,actor,'reject')
        a.li(9,throws.ROWS);a.r(0x2D,9,9,8);a.lw(9,9);a.branch(5,9,0,'reject')
        a.li(8,participation.CONTROL);a.lw(9,8,4);a.lw(10,22,4)
        a.branch(5,9,10,'reject');a.lw(9,8,12);a.lw(10,8,16)
        a.r(0x27,10,10,0);a.r(0x24,9,9,10);a.addiu(10,0,1)
        a.r(4,10,19,10);a.r(0x24,9,9,10);a.branch(4,9,0,'reject')
        beam.alive(a,actor,'reject')
        for off in throws.ACTION_FIELDS:
            a.lw(8,actor,off)
            for first,length in ((180,8),(236,80)):
                a.addiu(9,8,-first);a.i(11,9,9,length);a.branch(5,9,0,'reject')
        throws.contact.paired_pending(a,actor,'reject')
        a.lw(8,actor,12);a.i(11,9,8,12);a.branch(4,9,0,'reject')
        a.sw(actor,29,0xE8+16*side);a.sw(19,29,0xEC+16*side);a.sw(8,29,0xF0+16*side)
    a.lw(12,29,0xEC);a.lw(13,29,0xFC)
    policy.emit_enemy(a,12,13,'reject','dash_start')
    for side in range(2):
        for src,dst in ((0,64),(4,80),(8,72)):
            a.lw(8,29,0xE8+16*side+src);a.sw(8,22,dst+4*side)
    a.addiu(8,0,1);a.sw(8,22,16);a.sw(0,22,20)
    a.lw(8,22,24);a.addiu(8,8,1);a.sw(8,22,24)
    beam.restore(a);a.addiu(5,0,0x61);a.branch(4,20,0,'second')
    a.jump(A(0x1C9130));a.label('second');a.jump(A(0x1C9178))
    a.label('reject');a.li(8,CONTROL);a.lw(9,8,28);a.addiu(9,9,1);a.sw(9,8,28)
    beam.restore(a);a.jump(A(0x1C9218))
    a.label('old');beam.restore(a);a.jump(bounds.CODE)
    b=a.finish();assert len(b)<=FRAME-START;return b


def abort_code():
    import beam_clash as beam
    a=Assembler(ABORT);beam.save(a);a.call(VALID);a.branch(4,2,0,'clear')
    a.li(16,CONTROL)
    for off in (64,68):
        for flag in (FLAG(0x61),FLAG(0x62)):
            a.lw(4,16,off);a.addiu(5,0,flag);a.call(A(0x1DAA50))
        # Native end flags for250 and252. A pending251 falls back through252.
        for flag in (FLAG(0xBF),FLAG(0xC6)):
            a.lw(4,16,off);a.addiu(5,0,flag);a.call(A(0x1DABE8))
    a.lw(8,16,4);a.lw(9,8,64);a.addiu(9,9,-6);a.i(11,9,9,6)
    a.branch(4,9,0,'clear');a.sw(0,8,64)
    a.label('clear');a.li(8,CONTROL);a.lw(9,8,36);a.addiu(9,9,1);a.sw(9,8,36)
    a.sw(0,8,16);a.sw(0,8,20);beam.restore(a);a.jr()
    b=a.finish();assert len(b)<=ACTOR-ABORT;return b


def frame_code():
    import beam_clash as beam
    a=Assembler(FRAME);beam.save(a);a.call(GATE);a.branch(4,2,0,'detached')
    a.li(16,CONTROL);a.lw(8,16,16);a.branch(4,8,0,'native')
    a.li(8,A(0x3337B8));a.lw(8,8);a.i(12,9,8,0x100);a.branch(5,9,0,'native')
    a.i(12,8,8,0x2000);a.branch(5,8,0,'abort')
    a.call(VALID);a.branch(4,2,0,'abort')
    a.lw(8,16,20);a.addiu(8,8,1);a.sw(8,16,20)
    a.i(11,9,8,900);a.branch(4,9,0,'abort')
    a.lw(8,16,16);a.addiu(9,0,2);a.branch(4,8,9,'native')
    for side in range(2):
        a.lw(10,16,64+4*side);beam.alive(a,10,'abort')
        a.lw(9,10,2376);a.addiu(9,9,-250);a.i(11,9,9,3);a.branch(4,9,0,'pending')
    a.addiu(8,0,2);a.sw(8,16,16);a.jump('native')
    a.label('pending');a.lw(8,16,20);a.i(11,8,8,20);a.branch(4,8,0,'abort')
    beam.restore(a);a.move(2,0);a.jr()
    a.label('abort');a.call(ABORT);a.jump('native')
    a.label('detached');a.li(8,CONTROL);a.sw(0,8,16);a.sw(0,8,20)
    a.label('native');beam.restore(a);a.addiu(29,29,-0x20);a.i(63,31,29,0)
    a.call(beam.FRAME);a.i(63,2,29,8);a.i(63,3,29,16)
    beam.save(a);a.call(VALID);a.branch(4,2,0,'done')
    a.li(16,CONTROL);a.lw(8,16,4);a.lw(8,8,64);a.branch(5,8,0,'done')
    a.lw(8,16,16);a.addiu(9,0,2);a.branch(5,8,9,'done')
    for side in range(2):
        a.lw(8,16,64+4*side);a.lw(9,8,2376);a.addiu(9,9,-250)
        a.i(11,9,9,3);a.branch(5,9,0,'done')
    a.lw(8,16,32);a.addiu(8,8,1);a.sw(8,16,32);a.sw(0,16,16);a.sw(0,16,20)
    a.label('done');beam.restore(a);a.i(55,2,29,8);a.i(55,3,29,16)
    a.i(55,31,29,0);a.addiu(29,29,0x20);a.jr()
    b=a.finish();assert len(b)<=ABORT-FRAME;return b


def side_code(base,actor,result,animation=False):
    """Native clash animations371/372 and shared effect ownership use side0/1.

    Physical IDs never change. Convert only these two audited local reads.
    """
    import beam_clash as beam
    a=Assembler(base);beam.save(a);a.call(VALID);a.branch(4,2,0,'old')
    a.li(8,ACTORS);a.lw(9,8);a.branch(4,actor,9,'zero')
    a.lw(9,8,4);a.branch(5,actor,9,'old');a.addiu(result,0,1);a.jump('return')
    a.label('zero');a.move(result,0);a.jump('return')
    a.label('old');a.lw(result,actor)
    a.label('return');beam.restore(a,(result,))
    if animation:a.addiu(2,0,0x174);a.jump(A(0x1F47F8))
    else:
        a.branch(5,2,0,'second');a.jump(A(0x1F513C))
        a.label('second');a.jump(A(0x1F5160))
    b=a.finish();assert len(b)<=0x400;return b


def pieces():
    import beam_clash as beam
    values=dict(GATE=GATE,VALID=VALID,CONTROL=CONTROL,MAGIC=MAGIC,START=START,
                ACTORS=ACTORS,MODELS=MODELS,RESOLVE=RESOLVE,CONTACT=CONTACT,
                PARTICIPANT=PARTICIPANT)
    rebound=lambda fn,**kw:core.rebound(fn,**(values|kw))
    out=[(GATE,rebound(beam.gate_code)()),(VALID,rebound(beam.valid_code)()),
         (START,start_code()),(FRAME,frame_code()),(ABORT,abort_code()),
         (ANIMATION_SIDE,side_code(ANIMATION_SIDE,17,3,True)),
         (EFFECT_SIDE,side_code(EFFECT_SIDE,16,2)),
         (ACTOR,rebound(beam.bridge)(ACTOR,A(0x1DC178),actor=True)),
         (RESOLVE,rebound(beam.resolve_code,throws=SimpleNamespace(RESOLVE=beam.RESOLVE))()),
         (CONTACT,rebound(beam.contact_code,throws=SimpleNamespace(CONTACT=beam.CONTACT))()),
         (PARTICIPANT,rebound(beam.participant_code,throws=SimpleNamespace(PARTICIPANT=beam.PARTICIPANT))())]
    for site in ACTOR_CALLS:out.append((site,struct.pack('<I',(3<<26)|(ACTOR>>2))))
    for hook,dest in ((bounds.HOOK,START),(A(0x1D9900),FRAME),(core.RESOLVER,RESOLVE),
                      (beam.leader.FALLBACK,CONTACT),(beam.camera.PARTICIPANT,PARTICIPANT),
                      (A(0x1F47F0),ANIMATION_SIDE),(A(0x1F5130),EFFECT_SIDE)):
        out.append((hook,struct.pack('<2I',(2<<26)|(dest>>2),0)))
    return out


def installed_pieces(ram):
    """Exact original emission plus the optional reviewed body-contact layer."""
    import dash_contact_guard
    import vanish_pair_guard
    return list((dict(pieces()) | dict(dash_contact_guard.overlay(ram)) |
                 dict(vanish_pair_guard.overlay(ram))).items())


def build_memory(ram, config=None, source='<offline-memory>'):
    import beam_clash as beam
    from prototype import ROOT, elf_reader
    if len(ram)!=0x8000000:raise ValueError('Requires128MiB captured RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if count not in ACTOR_COUNTS or (u(core.MODE),u(core.MODE+8),u(core.MODE+12))!=(1,manager,count):
        raise ValueError('Requires captured four/six actor world')
    if not 0x100000<=manager<len(ram)-0x1000 or u(manager)!=2 or u(core.PAIR+4):
        raise ValueError('Requires native manager and restored AI roles')
    battle=u(beam.team_intro.BATTLE)
    actors=[u(core.POINTERS+4*i) for i in range(count)]
    if not 0x100000<=battle<len(ram)-0x100 or len(set(actors))!=count:
        raise ValueError('Invalid battle or actor identity')
    for i,p in enumerate(actors):
        if not 0x100000<=p<len(ram)-0x1600 or u(p)!=i or u(p+12)>=12:
            raise ValueError('Invalid captured actor/model')
    header=bytearray(max(0x120,0x100+4*count));struct.pack_into('<4I',header,0,MAGIC,manager,count,battle)
    struct.pack_into('<'+'I'*count,header,0x100,*actors)
    patches=pieces()
    if u(CONTROL)==MAGIC:
        if ram[CONTROL:CONTROL+16]!=header[:16] or ram[CONTROL+0x100:CONTROL+0x100+4*count]!=header[0x100:0x100+4*count]:
            raise ValueError('Changed dash capture identity')
        for p,d in installed_pieces(ram):
            if ram[p:p+len(d)]!=d:raise ValueError(f'Changed dash hook{p:08X}')
        original=elf_reader(elf_path(ROOT))[2]
        for p in ACTOR_CALLS:
            if ram[p+4:p+8]!=original(p+4,4):
                raise ValueError(f'Changed native dash delay{p:08X}')
        if ram[A(0x1F5138):A(0x1F513C)]!=original(A(0x1F5138),4):
            raise ValueError('Changed native dash effect delay')
        return dict(source=str(source),control=CONTROL,blocks=[],status='ACTUAL-PAIR DASH CLASH INSTALLED')
    if any(ram[CODE:END]):raise ValueError('Dash clash reservation occupied')
    if beam.build_memory(ram,source=source)['blocks']:
        raise ValueError('Install complete beam-clash chain first')
    if ram[bounds.HOOK:bounds.HOOK+8]!=struct.pack('<2I',(2<<26)|(bounds.CODE>>2),0):
        raise ValueError('Expected original extra-clash admission guard')
    original=elf_reader(elf_path(ROOT))[2]
    for p in ACTOR_CALLS:
        if u(p)!=(3<<26)|(A(0x1DC178)>>2) or ram[p:p+8]!=original(p,8):
            raise ValueError(f'Native dash callsite changed{p:08X}')
    for p,size in ((A(0x1F47F0),8),(A(0x1F5130),12)):
        if ram[p:p+size]!=original(p,size):raise ValueError(f'Native dash side changed{p:08X}')
    patches.append((CONTROL,bytes(header)))
    intervals=sorted((p,p+len(d)) for p,d in patches)
    if any(q<end for (_,end),(q,_) in zip(intervals,intervals[1:])):
        raise ValueError('Dash patches overlap')
    return dict(serial=SERIAL,crc=CRC,source=str(source),control=CONTROL,
        status='ACTUAL-PAIR NATIVE DASH CLASH; LIVE VALIDATION REQUIRED',
        blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex()) for p,d in patches],
        counters=dict(accepted=CONTROL+24,rejected=CONTROL+28,completed=CONTROL+32,aborted=CONTROL+36),
        behavior=['Native dash clash250 and interactive dash clash251/252 use actual colliding actors.',
                  'One shared native beam or dash struggle at a time; other contacts stay isolated.',
                  'Per-actor native controls, strength, animation and winner flags remain native.'])
