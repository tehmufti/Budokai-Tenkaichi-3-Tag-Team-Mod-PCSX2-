"""Optional continuous face-button contests, using the native clash animations.

All prompts, penalties and scores live in EE RAM. A private deterministic
sequence gives both contestants the same buttons without consuming the game's
random stream. The original clash coordinator still owns cameras and release.
"""
import struct
from native_map import A, ACTOR_HZ, elf_path
from prototype import Assembler, ROOT, elf_reader
import beam_clash as beam
import dash_clash as dash
import fresh_team_combat as core
import roster_selection_guard as guard

# Between fusion_partner_lifecycle and special_camera_arbitration, outside
# the native preparation packet and the online transport reservations.
BASE, END = 0x077E0000, 0x077F0000
FRAME, STEP, FIND, INPUT, PROMPT, AWARD = (BASE+i*0x1000 for i in range(6))
OLD_INPUT, OLD_PROMPT = BASE+0x6000, BASE+0x6100
CONTROL, ROWS = BASE+0x7000, BASE+0x7100
MAGIC=0x43515431
# identity, enabled; current coordinator and serial; two rows of 64 bytes:
# actor, random, next button, accepted total, blocked-until, last frame,
# weighted beam strength. The last value preserves bonuses at each input,
# rather than retroactively multiplying every earlier input when an ally joins.
INPUT_ENTRY, PROMPT_ENTRY = A(0x1D4F30), A(0x20C5C8)
def award_sites():
    read=elf_reader(elf_path(ROOT))[2]
    expected=0x0C000000|(A(0x1E11D0)>>2)
    sites=(A(0x1D96B8),A(0x1D96C8))
    if struct.unpack('<I',read(sites[0],4))[0]!=expected:
        # BT4 moved the vanish awards into its own two-human helper. Hook
        # those calls, never the branch occupying BT3's former call site.
        call=struct.unpack('<I',read(A(0x1D96B0),4))[0]
        if call>>26!=3:raise ValueError('Unknown native vanish award layout')
        target=(call&0x3FFFFFF)<<2
        sites=(target+0x2C,target+0x4C)
    if any(struct.unpack('<I',read(p,4))[0]!=expected for p in sites):
        raise ValueError('Native vanish award calls changed')
    return sites
AWARDS=award_sites()
KEY='clash_button_sequence'

def jump(p):return struct.pack('<2I',0x08000000|(p>>2),0)
def jal(p):return struct.pack('<I',0x0C000000|(p>>2))

def find_code():
    """a0 actor -> v0 current row, or 0 outside an active owned contest."""
    a=Assembler(FIND);a.li(8,CONTROL);a.move(2,0)
    a.lw(9,8);a.li(10,MAGIC);a.branch(5,9,10,'done');a.lw(9,8,8);a.branch(4,9,0,'done')
    a.lw(9,8,4);a.li(10,core.ACTORS);a.lw(10,10);a.branch(5,9,10,'done')
    a.lw(10,9,64)
    for state in (1,2,6,7,9,10):
        a.addiu(11,0,state);a.branch(4,10,11,'active')
    a.jump('done');a.label('active')
    a.lw(9,8,12);a.branch(4,9,0,'done');a.lw(10,9,16);a.branch(4,10,0,'done')
    a.li(9,ROWS)
    for i in range(2):
        a.lw(10,9,64*i);a.branch(5,4,10,f'next{i}');a.addiu(2,9,64*i);a.jr();a.label(f'next{i}')
    a.label('done');a.jr();return a.finish()

def step_code():
    """a0 row, a1 age, a2 four-bit pressed mask; one decision per update."""
    a=Assembler(STEP);a.move(2,0)
    a.lw(8,4,20);a.branch(4,8,5,'done');a.sw(5,4,20)
    a.lw(8,4,16);a.r(0x2B,8,5,8);a.branch(5,8,0,'done')
    a.i(12,6,6,15);a.branch(4,6,0,'done')
    a.lw(9,4,8);a.addiu(10,0,1);a.r(4,10,9,10);a.branch(5,10,6,'wrong')
    a.lw(10,4,12);a.addiu(10,10,1);a.sw(10,4,12)
    a.lw(10,4,4)
    a.r(0,11,0,10,13);a.r(0x26,10,10,11)
    a.r(2,11,0,10,17);a.r(0x26,10,10,11)
    a.r(0,11,0,10,5);a.r(0x26,10,10,11);a.sw(10,4,4)
    # Add 1..3 to the old icon: the next prompt is always visibly different.
    a.r(2,11,0,10,8);a.addiu(12,0,3);a.r(27,0,11,12);a.r(16,11,0)
    a.r(0x21,9,9,11);a.addiu(9,9,1);a.i(12,9,9,3);a.sw(9,4,8)
    a.addiu(2,0,1);a.jr()
    a.label('wrong');a.addiu(8,5,round(ACTOR_HZ*.4));a.sw(8,4,16)
    a.label('done');a.jr();return a.finish()

def frame_code():
    a=Assembler(FRAME);guard.save(a)
    a.li(16,CONTROL);a.lw(8,16,8);a.branch(4,8,0,'done')
    a.call(dash.GATE);a.branch(4,2,0,'done')
    a.li(8,A(0x3337B8));a.lw(8,8);a.i(12,8,8,0x2100);a.branch(5,8,0,'done')
    a.li(17,beam.CONTROL);a.lw(8,17,16);a.branch(5,8,0,'coordinator')
    a.li(17,dash.CONTROL);a.lw(8,17,16);a.branch(5,8,0,'coordinator')
    a.sw(0,16,12);a.jump('done')
    a.label('coordinator');a.lw(18,17,20);a.lw(19,17,24)
    a.lw(8,16,12);a.branch(5,8,17,'reset');a.lw(8,16,16);a.branch(4,8,19,'ready')
    a.label('reset');a.sw(17,16,12);a.sw(19,16,16)
    a.li(9,0x6D2B79F5);a.r(0x26,9,9,19);a.i(12,10,9,3)
    for i in range(2):
        a.li(8,ROWS+i*64);a.lw(11,17,64+i*4);a.sw(11,8);a.sw(9,8,4);a.sw(10,8,8)
        a.sw(0,8,12);a.sw(0,8,16);a.sw(0,8,24);a.addiu(11,0,-1);a.sw(11,8,20)
    a.label('ready')
    for i in range(2):
        a.li(20,ROWS+i*64);a.lw(21,20);a.move(4,21);a.call(FIND);a.branch(4,2,0,f'score{i}')
        a.lw(6,21,0x744);a.r(2,6,0,6,27)
        a.lw(8,21,0x1278);a.branch(4,8,0,f'input{i}')
        # The real manager has only two work rows. Read the physical fighter's
        # private manager; never index the native array with an extra's ID.
        import fresh_team_ai as ai
        a.lw(4,21);a.addiu(2,0,13)
        for physical,descriptor in enumerate(ai.DESCRIPTORS):
            a.addiu(8,0,physical);a.branch(5,4,8,f'cpu_next{i}_{physical}')
            a.li(8,descriptor);a.lw(9,8);a.branch(5,9,21,f'cpu_fallback{i}')
            a.lw(8,8,4);a.branch(4,8,0,f'cpu_fallback{i}')
            a.lw(2,8,0x18+(physical&1)*0x520);a.jump(f'cpu_ready{i}')
            a.label(f'cpu_next{i}_{physical}')
        a.label(f'cpu_fallback{i}');a.i(11,8,4,2);a.branch(4,8,0,f'cpu_ready{i}');a.call(A(0x1BB450))
        a.label(f'cpu_ready{i}');a.move(6,0);a.branch(1,2,0,f'input{i}')
        a.i(11,8,2,30);a.branch(5,8,0,f'level{i}');a.addiu(2,0,29);a.label(f'level{i}')
        a.addiu(8,0,12);a.r(24,0,2,8);a.r(18,8,0);a.addiu(9,0,29);a.r(27,0,8,9);a.r(18,8,0)
        a.addiu(9,0,18);a.r(0x23,8,9,8);a.r(27,0,18,8);a.r(16,8,0);a.branch(5,8,0,f'input{i}')
        a.lw(8,20,8);a.addiu(6,0,1);a.r(4,6,8,6)
        a.label(f'input{i}');a.move(4,20);a.move(5,18);a.call(STEP)
        a.lw(8,20,24);a.sw(8,21,0xE4C);a.branch(4,2,0,f'score{i}')
        # Reuse the existing beam push routine so confirmed assists, CPU
        # strength, fractional credit and damage interference all still apply.
        import beam_struggle as struggle
        a.li(8,beam.CONTROL);a.branch(5,17,8,f'plain{i}')
        a.li(8,struggle.CONTROL);a.lw(9,8);a.li(10,struggle.MAGIC);a.branch(5,9,10,f'plain{i}')
        a.li(8,beam.ACTIVE);a.lw(23,8);a.addiu(9,0,i+1);a.sw(9,8)
        a.move(4,21);a.call(struggle.PUSH)
        a.li(8,beam.ACTIVE);a.sw(23,8);a.lw(8,21,0xE4C);a.jump(f'weighted{i}')
        a.label(f'plain{i}');a.lw(8,20,24);a.addiu(8,8,1)
        a.label(f'weighted{i}');a.sw(8,20,24)
        a.label(f'score{i}');a.lw(8,20,12);a.sw(8,21,0xE50)
        a.lw(8,20,24);a.sw(8,21,0xE4C)
        a.label(f'skip{i}')
    # Continuous vanish exchanges last eight seconds, then resolve on the
    # next native animation boundary. A tie gets a two-second extension.
    a.lw(22,16,4);a.lw(8,22,64);a.addiu(9,0,10);a.branch(5,8,9,'done')
    a.i(11,8,18,8*ACTOR_HZ);a.addiu(9,0,6);a.branch(4,8,0,'count');a.move(9,0)
    a.label('count');a.sw(9,22,0x80)
    a.i(11,8,18,10*ACTOR_HZ);a.branch(5,8,0,'done')
    a.li(8,ROWS);a.lw(9,8,12);a.lw(10,8,76);a.branch(5,9,10,'done')
    a.i(12,10,19,1);a.r(0,10,0,10,6);a.r(0x21,8,8,10);a.lw(8,8);a.addiu(9,9,1);a.sw(9,8,0xE50)
    a.label('done');guard.restore(a);a.jump(dash.FRAME);return a.finish()

def input_code():
    a=Assembler(INPUT);beam.save(a);a.addiu(8,0,51);a.branch(5,5,8,'old');a.call(FIND);a.branch(4,2,0,'old')
    beam.restore(a,(2,));a.move(2,0);a.jr()
    a.label('old');beam.restore(a);a.jump(OLD_INPUT);return a.finish()

def prompt_code():
    a=Assembler(PROMPT);beam.save(a);a.move(16,5);a.move(17,6);a.move(18,7)
    a.call(A(0x1DC210));a.branch(4,2,0,'old');a.move(19,2);a.lw(8,19,0x1278);a.branch(5,8,0,'old')
    a.move(4,19);a.call(FIND);a.branch(4,2,0,'old');a.lw(5,2,8);a.addiu(5,5,27);a.move(4,19);a.call(A(0x20B418))
    a.branch(4,16,0,'kind');a.sw(2,16);a.label('kind');a.branch(4,17,0,'pad');a.addiu(8,0,2);a.sw(8,17)
    a.label('pad');a.branch(4,18,0,'result');a.sw(0,18);a.label('result');beam.restore(a,(2,));a.addiu(2,0,1);a.jr()
    a.label('old');beam.restore(a);a.jump(OLD_PROMPT);return a.finish()

def award_code():
    a=Assembler(AWARD);beam.save(a);a.call(FIND);a.branch(4,2,0,'old');beam.restore(a);a.jr()
    a.label('old');beam.restore(a);a.jump(A(0x1E11D0));return a.finish()

def pieces(guarded_input=False):
    read=elf_reader(elf_path(ROOT))[2]
    out=[(FRAME,frame_code()),(STEP,step_code()),(FIND,find_code()),(INPUT,input_code()),(PROMPT,prompt_code()),(AWARD,award_code())]
    for entry,old in ((INPUT_ENTRY,OLD_INPUT),(PROMPT_ENTRY,OLD_PROMPT)):
        if entry==INPUT_ENTRY and guarded_input:
            out.append((old,jump(guarded_input)));continue
        a=Assembler(old);a.words.extend(struct.unpack('<2I',read(entry,8)));a.jump(entry+8);out.append((old,a.finish()))
    out += [(A(0x1D9900),jump(FRAME)),(INPUT_ENTRY,jump(INPUT)),(PROMPT_ENTRY,jump(PROMPT))]
    out += [(p,jal(AWARD)) for p in AWARDS]
    return out

def input_owner(ram,installed):
    """Keep the existing throw/contact guard when no owned clash consumes input."""
    import cinematic_contact_guard as contact
    original=elf_reader(elf_path(ROOT))[2](INPUT_ENTRY,8)
    index,(_,cave,kind,rejected)=next((i,spec) for i,spec in enumerate(contact.SPECS) if spec[0]==INPUT_ENTRY)
    current=ram[OLD_INPUT:OLD_INPUT+8] if installed else ram[INPUT_ENTRY:INPUT_ENTRY+8]
    if current==original:return 0
    import teammate_revive as revive
    if current==jump(revive.COMMAND):
        u=lambda p:struct.unpack_from('<I',ram,p)[0]
        version=u(revive.CONTROL+24)
        if u(revive.CONTROL)!=revive.MAGIC or version not in revive.VERSIONS or u(revive.CONTROL+44)!=cave:
            raise ValueError('Clash input revival continuation changed')
        expected=revive.barrier(revive.COMMAND,cave,'command',prescan=version>=4)
        if ram[revive.COMMAND:revive.COMMAND+len(expected)]!=expected:
            raise ValueError('Clash input revival guard changed')
        owner=revive.COMMAND
    elif current==jump(cave):owner=cave
    else:raise ValueError(f'Clash button hook changed at {INPUT_ENTRY:08X}')
    expected=contact.wrapper(INPUT_ENTRY,cave,kind,rejected,original,index)
    if ram[cave:cave+len(expected)]!=expected:raise ValueError('Clash input contact guard changed')
    return owner

def dependency_override(ram,address,expected):
    """Authenticate this inner wrapper before a scenario/tag outer wrapper."""
    if address!=INPUT_ENTRY or len(expected)!=8:return expected
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if u(CONTROL)!=MAGIC:return expected
    if u(CONTROL+4)!=u(core.ACTORS):raise ValueError('Clash input belongs to another match')
    if bytes(ram[OLD_INPUT:OLD_INPUT+8])!=expected:return expected
    owner=input_owner(ram,True)
    continuation=jump(owner) if owner else elf_reader(elf_path(ROOT))[2](INPUT_ENTRY,8)+jump(INPUT_ENTRY+8)
    for p,data in ((INPUT,input_code()),(OLD_INPUT,continuation)):
        if bytes(ram[p:p+len(data)])!=data:raise ValueError('Clash input wrapper changed')
    return jump(INPUT)

def overlay(ram):
    if struct.unpack_from('<I',ram,CONTROL)[0]!=MAGIC:return []
    return [(A(0x1D9900),jump(FRAME))]

def build_memory(ram,settings=None,source='<prepared>'):
    import mod_settings
    opts=mod_settings.validate_settings(settings or {})
    enabled=opts[KEY];u=lambda p:struct.unpack_from('<I',ram,p)[0]
    installed=u(CONTROL)==MAGIC
    if not enabled and not installed:return dict(blocks=[],status='CLASH BUTTON SEQUENCE OFF')
    if u(dash.CONTROL)!=dash.MAGIC:raise ValueError('Button clashes require actual-participant clash routing')
    manager=u(dash.CONTROL+4);guarded=input_owner(ram,installed);data=pieces(guarded)
    if installed:
        if u(CONTROL+4)!=manager:raise ValueError('Clash button sequence belongs to a different match')
        for p,b in data:
            if p==INPUT_ENTRY:
                import story_runtime
                b=story_runtime.dependency_override(ram,p,b)
            if ram[p:p+len(b)]!=b:raise ValueError(f'Clash button program changed at {p:08X}')
        data=[]
    else:
        if any(ram[BASE:END]):raise ValueError('Clash button reservation occupied')
        original=elf_reader(elf_path(ROOT))[2]
        for p,n in ((PROMPT_ENTRY,8),*((p,4) for p in AWARDS)):
            if ram[p:p+n]!=original(p,n):raise ValueError(f'Clash button hook changed at {p:08X}')
        if ram[A(0x1D9900):A(0x1D9900)+8]!=jump(dash.FRAME):raise ValueError('Unexpected clash update owner')
        data.append((CONTROL,struct.pack('<5I',MAGIC,manager,int(enabled),0,0)))
    if installed:data.append((CONTROL+8,struct.pack('<I',int(enabled))))
    return dict(source=source,status='CLASH BUTTON SEQUENCE',blocks=[dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=b.hex()) for p,b in data if ram[p:p+len(b)]!=b])
