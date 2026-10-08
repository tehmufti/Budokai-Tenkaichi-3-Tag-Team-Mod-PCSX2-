"""CPU-only dynamic target decisions, driven by captured native damage and time.

Written for free-for-all, where every other contestant is a candidate. The same
policy drives Team Battle and co-op NPCs through a compile-time ``battle_mode``:
those variants consult battle_mode_policy for every candidate, damage record and
retained target, so an ally is never scored, never accumulates a grudge and is
dropped the moment a stale plan names one. Only the opening differs - a team NPC
keeps the matching-slot opponent it was given instead of drawing a random one.
The FFA byte stream is unchanged, so prepared FFA states stay valid.

This owns the damage history instead of sharing the team retaliation matrix.
The existing AI picker synchronizes target descriptors and retains its last-dead
target fallback. All timing is released gameplay updates (30 Hz).
"""
from native_map import A, CRC, SERIAL
import struct
import secrets
from prototype import Assembler
import fresh_team_combat as core
import fresh_team_ai as ai
import battle_mode_policy as mode
import team_participation as part
import team_start_gate as start
import cpu_retaliation as retaliation
import cinematic_admission as admission
import extra_throws as throws
import beam_clash as beam
import dash_clash as dash
import battle_mode_policy as policy

CODE,GATE,ALIVE,SAFE,RANDOM,SCORE,ACCUMULATE,APPLY=(
    0x071E0000,0x071E0000,0x071E0800,0x071E1000,0x071E1800,0x071E2000,0x071E4000,0x071E5000)
CONTROL,ROWS,MATRIX,END=0x071FF000,0x071FF100,0x071FF400,0x07200000
MAGIC=0x46464132
ROW_SIZE=32
# Rows and grudge cells are sized for every fighter the engine can hold, not the
# current team capacity, so a larger match never shares a row or a cell. A cell
# row is 12 x 8 = 96 bytes, reached with two shifts (64 + 32). Three-a-side
# installs carry six-wide tables; layout() follows the build being emitted.
TABLE_ACTORS=policy.ENGINE_ACTORS
CELL_STRIDE=TABLE_ACTORS*8
CELL_SHIFTS=policy.stride_shifts(CELL_STRIDE)
assert ROWS+TABLE_ACTORS*ROW_SIZE<=MATRIX and MATRIX+TABLE_ACTORS*CELL_STRIDE<=END,'Grudge tables overrun their reservation'


def layout():
    """(actors, cell row stride, cell row shifts) for the build being emitted."""
    actors=policy.emitted_tables()
    return actors,actors*8,policy.stride_shifts(actors*8)
MIN_HOLD,EVALUATE,WINDOW=60,15,240
MODE_NAMES=('teams','ffa','coop')


def check_mode(battle_mode):
    if battle_mode not in MODE_NAMES:raise ValueError('Unknown dynamic targeting mode')
    return battle_mode


def save(a):
    a.addiu(29,29,-0x60)
    for i,r in enumerate(tuple(range(16,24))+(31,)):a.i(63,r,29,i*8)


def restore(a):
    for i,r in enumerate(tuple(range(16,24))+(31,)):a.i(55,r,29,i*8)
    a.addiu(29,29,0x60)


def row(a,dst,index,base=ROWS):
    a.r(0,8,0,index,5);a.li(dst,base);a.r(0x2D,dst,dst,8)


def cell(a,dst,victim,source):
    shifts=layout()[2]
    a.r(0,8,0,victim,shifts[0]);a.r(0,9,0,victim,shifts[1]);a.r(0x2D,8,8,9)
    a.r(0,9,0,source,3);a.r(0x2D,8,8,9);a.li(dst,MATRIX);a.r(0x2D,dst,dst,8)


def gate_code(battle_mode='ffa'):
    check_mode(battle_mode)
    a=Assembler(GATE);core.gate(a,'no')
    a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,'no')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'no')
    a.lw(9,8,8);a.branch(5,9,10,'no')
    # Teams installs no mode control at all, so an absent block is the teams
    # answer and a present one must still say teams for this manager.
    a.li(8,mode.CONTROL);a.lw(9,8);a.li(12,mode.MAGIC)
    a.branch(5,9,12,'mode_absent' if battle_mode=='teams' else 'no')
    a.lw(9,8,4);a.branch(5,9,11,'no');a.lw(9,8,8);a.branch(5,9,10,'no')
    a.lw(9,8,12);a.addiu(12,0,mode.MODES[battle_mode]);a.branch(5,9,12,'no')
    if battle_mode=='teams':a.label('mode_absent')
    a.li(8,part.CONTROL);a.lw(9,8,4);a.branch(5,9,11,'no');a.lw(9,8,8);a.branch(5,9,10,'no')
    a.lw(9,8,12);a.li(8,CONTROL);a.lw(8,8,12);a.branch(5,9,8,'no')
    for p in (core.PAIR+4,start.CONTROL,A(0x333700)):
        a.li(8,p);a.lw(8,8);a.branch(5,8,0,'no')
    a.li(8,A(0x3337B8));a.lw(8,8);a.i(12,8,8,0x2100);a.branch(5,8,0,'no')
    a.li(8,A(0x3337C0));a.lw(8,8);a.addiu(9,0,1);a.branch(5,8,9,'no')
    a.lw(8,28,-22364);a.lw(8,8,628);a.branch(5,8,0,'no')
    a.li(8,A(0x2FEB38));a.lw(8,8);a.li(9,0x100000);a.r(0x2B,9,8,9);a.branch(5,9,0,'no')
    a.li(9,0x7FFFE00);a.r(0x2B,9,8,9);a.branch(4,9,0,'no')
    a.lw(9,8,260);a.li(11,A(0x2C6070));a.branch(5,9,11,'no')
    a.lw(9,8);a.addiu(11,0,3);a.branch(5,9,11,'no')
    a.addiu(2,0,1);a.jr();a.label('no');a.move(2,0);a.jr();return a.finish()


def alive_code():
    """a0 physical index => v0 actor, v1 current HP; captured/present only."""
    a=Assembler(ALIVE);a.li(8,CONTROL);a.lw(9,8,8);a.r(0x2B,9,4,9);a.branch(4,9,0,'no')
    a.lw(9,8,12);a.li(8,part.CONSUMED);a.lw(8,8);a.r(0x27,8,8,0);a.r(0x24,9,9,8)
    a.addiu(8,0,1);a.r(4,8,4,8);a.r(0x24,8,8,9);a.branch(4,8,0,'no')
    a.r(0,9,0,4,2);a.li(8,core.POINTERS);a.r(0x2D,8,8,9);a.lw(2,8)
    a.li(8,CONTROL+0x80);a.r(0x2D,8,8,9);a.lw(8,8);a.branch(5,2,8,'no')
    a.branch(4,2,0,'no');a.lw(8,2);a.branch(5,8,4,'no')
    a.lw(8,2,0x994);a.i(11,9,8,5);a.branch(4,9,0,'no')
    a.r(0,9,0,8,7);a.r(0,10,0,8,5);a.r(0x2D,9,9,10)
    a.r(0,10,0,8,2);a.r(0x2D,9,9,10);a.r(0x2D,9,9,2)
    a.lw(3,9,0x9E4);a.branch(6,3,0,'no');a.jr()
    a.label('no');a.move(2,0);a.move(3,0);a.jr();return a.finish()


def safe_code():
    """a0 actor, a1 physical index. Ignore unrelated actors' cinematic state."""
    a=Assembler(SAFE)
    for off in admission.ACTION_FIELDS:
        a.lw(8,4,off)
        for first,length in ((180,8),(236,80)):
            a.addiu(9,8,-first);a.i(11,9,9,length);a.branch(5,9,0,'no')
    a.lw(8,4,2376);a.i(11,9,8,4);a.branch(5,9,0,'no')
    for off in retaliation.DEFERRED:a.lw(8,4,off);a.branch(5,8,0,'no')
    a.r(0,9,0,5,2);a.li(8,throws.ROWS);a.r(0x2D,8,8,9);a.lw(8,8);a.branch(5,8,0,'no')
    for name,control,magic in (('beam',beam.CONTROL,beam.MAGIC),('dash',dash.CONTROL,dash.MAGIC)):
        a.li(8,control);a.lw(9,8);a.li(10,magic);a.branch(5,9,10,name+'_done')
        a.lw(9,8,4);a.lw(10,28,-22364);a.branch(5,9,10,name+'_done')
        a.lw(9,8,16);a.branch(4,9,0,name+'_done')
        for off in (64,68):a.lw(9,8,off);a.branch(4,9,4,'no')
        a.label(name+'_done')
    a.addiu(2,0,1);a.jr();a.label('no');a.move(2,0);a.jr();return a.finish()


def random_code():
    a=Assembler(RANDOM);a.li(8,CONTROL);a.lw(2,8,20)
    # Private xorshift state. Never mutates the game's RNG or HI/LO registers.
    for shift,right in ((13,False),(17,True),(5,False)):
        a.r(2 if right else 0,9,0,2,shift);a.r(0x26,2,2,9)
    a.sw(2,8,20);a.jr();return a.finish()


def damage_value(a,out,victim,source,tick,tag):
    cell(a,11,victim,source);a.lw(out,11,4);a.branch(4,out,0,tag+'_done')
    a.lw(8,11);a.r(0x23,8,tick,8);a.i(11,9,8,WINDOW);a.branch(4,9,0,tag+'_expired')
    for edge in (60,120,180):
        a.i(11,9,8,edge);a.branch(5,9,0,tag+'_done');a.r(2,out,0,out,1)
    a.jump(tag+'_done');a.label(tag+'_expired');a.move(out,0);a.sw(0,11,4)
    a.label(tag+'_done')


def score_code():
    """a0 self index,a1 candidate,a2 opening flag => v0 nonnegative score."""
    a=Assembler(SCORE);save(a);a.move(16,4);a.move(17,5);a.move(23,6)
    a.call(ALIVE);a.move(18,2);a.move(4,17);a.call(ALIVE);a.move(19,2);a.move(22,3)
    a.branch(4,18,0,'zero');a.branch(4,19,0,'zero')
    a.call(RANDOM);a.i(12,20,2,127);a.addiu(20,20,512)
    a.branch(4,23,0,'normal');a.i(12,20,2,1023);a.addiu(20,20,512);a.jump('crowd')
    a.label('normal');a.li(8,CONTROL);a.lw(21,8,16)
    damage_value(a,12,16,17,21,'damage');a.r(2,12,0,12,3)
    a.i(11,8,12,801);a.branch(5,8,0,'damage_ready');a.addiu(12,0,800)
    a.label('damage_ready');a.r(0x2D,20,20,12)
    # Current model world roots, including vertical separation. Floating
    # registers are restored; positive squared-distance bits compare safely.
    for actor,out in ((18,13),(19,14)):
        a.lw(8,actor,12);a.i(11,9,8,12);a.branch(4,9,0,'distance_done')
        a.r(0,8,0,8,2);a.li(out,core.MODELS);a.r(0x2D,out,out,8);a.lw(out,out)
        a.branch(4,out,0,'distance_done')
    for f in range(4):a.i(57,f,29,0x48+f*4)
    a.emit((17<<26)|(4<<21)|(0<<16)|(3<<11)) # mtc1 zero,f3
    for off in (2416,2420,2424):
        a.i(49,0,13,off);a.i(49,1,14,off)
        for fn,fd,fs,ft in ((1,2,0,1),(2,2,2,2),(0,3,3,2)):
            a.emit((17<<26)|(16<<21)|(ft<<16)|(fs<<11)|(fd<<6)|fn)
    a.emit((17<<26)|(0<<21)|(12<<16)|(3<<11)) # mfc1 t4,f3
    for f in range(4):a.i(49,f,29,0x48+f*4)
    for radius,bonus,label in ((256.,350,'near'),(800.,220,'medium'),(2000.,80,'far')):
        a.li(8,struct.unpack('<I',struct.pack('<f',radius*radius))[0]);a.r(0x2B,8,12,8)
        a.branch(4,8,0,label+'_next');a.addiu(20,20,bonus);a.jump('distance_done');a.label(label+'_next')
    a.label('distance_done')
    # An attacker already engaging us and a briefly vulnerable opponent are
    # opportunities, not mandates to dogpile an opponent with low health.
    a.li(8,core.TABLE);a.r(0,9,0,17,2);a.r(0x2D,8,8,9);a.lw(8,8)
    a.branch(5,8,16,'not_attacking');a.addiu(20,20,100);a.label('not_attacking')
    a.lw(8,19,2376);a.addiu(8,8,-192);a.i(11,8,8,34)
    a.branch(4,8,0,'not_hurt');a.addiu(20,20,80);a.label('not_hurt')
    a.i(11,8,22,8000);a.branch(4,8,0,'not_low');a.addiu(20,20,60);a.label('not_low')
    row(a,11,16);a.lw(8,11,12);a.branch(5,8,17,'not_previous')
    a.lw(8,11,8);a.r(0x23,8,21,8);a.i(11,8,8,WINDOW)
    a.branch(4,8,0,'not_previous');a.addiu(20,20,-180);a.label('not_previous')
    a.li(8,core.TABLE);a.r(0,9,0,16,2);a.r(0x2D,8,8,9);a.lw(8,8)
    a.branch(5,8,17,'crowd')
    # Commitment weakens as a duel grows old. With no recent threat or useful
    # opportunity difference, private jitter can eventually change opponents
    # instead of holding one incumbent for the entire free-for-all.
    row(a,11,16);a.lw(8,11,8);a.r(0x23,8,21,8);a.i(11,9,8,180)
    a.branch(4,9,0,'older_duel');a.addiu(20,20,160);a.jump('crowd')
    a.label('older_duel');a.i(11,9,8,360);a.branch(4,9,0,'crowd');a.addiu(20,20,80)
    a.label('crowd');a.move(21,0)
    a.label('crowd_next');a.branch(4,21,16,'crowd_skip');a.branch(4,21,17,'crowd_skip')
    a.move(4,21);a.call(ALIVE);a.branch(4,2,0,'crowd_skip')
    a.lw(8,2,0x1278);a.addiu(9,0,1);a.branch(5,8,9,'crowd_skip')
    a.li(8,core.TABLE);a.r(0,9,0,21,2);a.r(0x2D,8,8,9);a.lw(8,8)
    a.branch(5,8,17,'crowd_skip');a.addiu(20,20,-120)
    a.label('crowd_skip');a.addiu(21,21,1);a.li(8,CONTROL);a.lw(8,8,8);a.branch(5,21,8,'crowd_next')
    a.branch(7,20,0,'positive');a.move(20,0);a.label('positive');a.move(2,20);a.jump('done')
    a.label('zero');a.move(2,0)
    a.label('done');restore(a);a.jr();return a.finish()


def accumulate_code(battle_mode='ffa'):
    check_mode(battle_mode)
    a=Assembler(ACCUMULATE);save(a);a.move(16,4);a.move(17,5);a.move(18,6)
    a.call(GATE);a.branch(4,2,0,'done');a.branch(6,18,0,'done');a.branch(4,16,17,'done')
    # Damage between allies is an accident, not a grudge worth remembering.
    if battle_mode!='ffa':mode.emit_enemy(a,16,17,'done','acc')
    a.move(4,16);a.call(ALIVE);a.branch(4,2,0,'done')
    a.lw(8,2,0x1278);a.addiu(9,0,1);a.branch(5,8,9,'done')
    a.move(4,17);a.call(ALIVE);a.branch(4,2,0,'done')
    a.li(8,CONTROL);a.lw(19,8,16);damage_value(a,12,16,17,19,'old')
    a.r(0x2D,12,12,18);a.li(9,32000);a.r(0x2B,8,12,9)
    a.branch(5,8,0,'bounded');a.move(12,9);a.label('bounded')
    cell(a,11,16,17);a.sw(19,11);a.sw(12,11,4)
    a.li(8,CONTROL);a.lw(9,8,24);a.addiu(9,9,1);a.sw(9,8,24)
    a.label('done');restore(a);a.jr();return a.finish()


def apply_code(battle_mode='ffa'):
    check_mode(battle_mode)
    a=Assembler(APPLY);save(a);a.call(GATE);a.branch(4,2,0,'done')
    a.li(8,CONTROL);a.lw(17,8,16);a.addiu(17,17,1);a.sw(17,8,16)
    a.move(16,0)
    a.label('actor');a.move(4,16);a.call(ALIVE);a.branch(4,2,0,'next');a.move(18,2)
    a.lw(8,18,0x1278);a.addiu(9,0,1);a.branch(5,8,9,'next')
    a.move(4,18);a.move(5,16);a.call(SAFE);a.branch(4,2,0,'next')
    row(a,19,16);a.li(8,core.TABLE);a.r(0,9,0,16,2);a.r(0x2D,8,8,9);a.lw(20,8)
    a.lw(8,19);a.branch(4,8,0,'opening')
    a.branch(4,20,16,'forced');a.move(4,20);a.call(ALIVE);a.branch(4,2,0,'forced')
    # A retained target that is now an ally (a rematch plan, a fusion, a mode
    # change) is replaced at once rather than held for the minimum duel time.
    if battle_mode!='ffa':mode.emit_enemy(a,16,20,'forced','cur')
    a.lw(8,19,8);a.r(0x23,8,17,8);a.i(11,8,8,MIN_HOLD);a.branch(5,8,0,'next')
    a.lw(8,19,4);a.r(0x23,8,17,8);a.branch(1,8,0,'next')
    a.lw(8,19,16);a.r(0x23,8,17,8);a.branch(1,8,0,'retaliation_only')
    a.move(23,0);a.jump('search')
    a.label('retaliation_only');a.move(21,0)
    a.label('threat');damage_value(a,12,16,21,17,'threat_value')
    a.branch(4,21,20,'threat_next');a.i(11,8,12,2000);a.branch(4,8,0,'periodic')
    a.label('threat_next');a.addiu(21,21,1);a.li(8,CONTROL);a.lw(8,8,8);a.branch(5,21,8,'threat')
    a.addiu(8,17,EVALUATE);a.sw(8,19,4);a.jump('next')
    a.label('periodic');a.move(23,0);a.jump('search')
    if battle_mode=='ffa':
        a.label('opening');a.addiu(23,0,1);a.jump('search')
    else:
        # Teams and co-op open on the matching-slot opponent the participation
        # plan already chose, so a match starts on the authored pairings and
        # only then drifts. A dead or allied opening falls to an ordinary
        # score search rather than the free-for-all's random draw.
        a.label('opening');a.move(4,20);a.call(ALIVE);a.branch(4,2,0,'opening_search')
        mode.emit_enemy(a,16,20,'opening_search','open')
        a.move(21,20);a.move(22,0);a.addiu(23,0,1);a.jump('commit')
        a.label('opening_search');a.move(23,0);a.jump('search')
    a.label('forced');a.move(23,0)
    a.label('search');a.addiu(21,0,-1);a.addiu(22,0,-1);a.move(18,0)
    a.label('candidate');a.branch(4,18,16,'candidate_next')
    if battle_mode!='ffa':mode.emit_enemy(a,16,18,'candidate_next','cand')
    a.move(4,18);a.call(ALIVE)
    a.branch(4,2,0,'candidate_next');a.move(4,16);a.move(5,18);a.move(6,23);a.call(SCORE)
    a.r(0x2A,8,22,2);a.branch(4,8,0,'candidate_next');a.move(22,2);a.move(21,18)
    a.label('candidate_next');a.addiu(18,18,1);a.li(8,CONTROL);a.lw(8,8,8);a.branch(5,18,8,'candidate')
    a.branch(1,21,0,'next');a.branch(4,21,20,'commit')
    a.li(8,core.TABLE);a.r(0,9,0,16,2);a.r(0x2D,8,8,9);a.sw(21,8)
    # Immediate native AI descriptor coherence, in case actor update follows
    # this damage tick before the next regular picker invocation.
    a.r(0,9,0,16,6);a.li(8,ai.DESCRIPTORS[0]);a.r(0x2D,8,8,9)
    a.r(0,9,0,21,6);a.li(10,ai.DESCRIPTORS[0]);a.r(0x2D,9,9,10);a.sw(9,8,24)
    a.sw(20,19,12);a.sw(17,19,8);a.lw(8,19,20);a.addiu(8,8,1);a.sw(8,19,20)
    a.li(8,CONTROL);a.lw(9,8,28);a.addiu(9,9,1);a.sw(9,8,28)
    a.label('commit');a.addiu(8,0,1);a.sw(8,19);a.addiu(8,17,EVALUATE);a.sw(8,19,4)
    a.branch(4,23,0,'hold_set');a.sw(17,19,8);a.label('hold_set')
    a.call(RANDOM);a.i(12,2,2,127);a.addiu(2,2,120);a.r(0x2D,2,2,17);a.sw(2,19,16)
    a.sw(21,19,24);a.sw(22,19,28)
    a.label('next');a.addiu(16,16,1);a.li(8,CONTROL);a.lw(8,8,8);a.branch(5,16,8,'actor')
    a.label('done');restore(a);a.jr();return a.finish()


def program(battle_mode='ffa'):
    check_mode(battle_mode)
    pieces=[(GATE,gate_code(battle_mode)),(ALIVE,alive_code()),(SAFE,safe_code()),(RANDOM,random_code()),
            (SCORE,score_code()),(ACCUMULATE,accumulate_code(battle_mode)),(APPLY,apply_code(battle_mode))]
    for (p,d),(q,_) in zip(pieces,pieces[1:]+[(CONTROL,b'')]):
        if p+len(d)>q:raise ValueError('Dynamic targeting code reservation overlap')
    return pieces


def seed_value(seed=None):
    if seed is None:return secrets.randbits(32) or 1
    if type(seed) is not int or not 0<seed<=0xFFFFFFFF:raise ValueError('FFA seed must be a nonzero32-bit integer')
    return seed


def initial_data(manager,count,mask,actors,seed=None):
    seed=seed_value(seed)
    control=bytearray(0x100);struct.pack_into('<6I',control,0,MAGIC,manager,count,mask,0,seed)
    struct.pack_into('<'+'I'*count,control,0x80,*actors)
    # Every row starts with 'no previous target'. Rows beyond the first six
    # used to start at 0, which read as 'previously targeted fighter 0'.
    actors,stride,_=layout()
    rows=bytearray(actors*ROW_SIZE)
    for i in range(actors):struct.pack_into('<I',rows,i*ROW_SIZE+12,0xFFFFFFFF)
    return [(CONTROL,bytes(control)),(ROWS,bytes(rows)),(MATRIX,bytes(actors*stride))]


def validate_memory(ram,manager,count,mask,battle_mode='ffa'):
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if (u(CONTROL),u(CONTROL+4),u(CONTROL+8),u(CONTROL+12))!=(MAGIC,manager,count,mask):
        raise ValueError('Dynamic targeting capture changed')
    for i in range(count):
        if u(CONTROL+0x80+4*i)!=u(core.POINTERS+4*i):raise ValueError('Dynamic targeting actor changed')
    for p,d in program(battle_mode):
        if ram[p:p+len(d)]!=d:raise ValueError(f'Dynamic targeting code changed:{p:08X}')


def installed_mode(ram):
    """Which flavour occupies the reservation, or None when it is empty.

    An occupied reservation that matches no flavour exactly, or whose capture
    no longer describes the live match, raises: callers use this to prove a
    prepared image carries the policy its mode expects and nothing else.
    """
    if not any(ram[CODE:END]):return None
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    for name in MODE_NAMES:
        if all(ram[p:p+len(d)]==d for p,d in program(name)):
            validate_memory(ram,u(core.ACTORS),u(core.MODE+4),u(part.PRESENT),name)
            return name
    raise ValueError('Unrecognized dynamic targeting policy')


def build_memory(ram,battle_mode='teams',seed=None,source='<prepared>'):
    """Install the dynamic NPC policy for a non-FFA prepared match.

    FFA installs its own copy inside battle_modes.build_memory, together with
    the picker, lock-on and defeat changes that only free-for-all needs. This
    entry covers Team Battle and co-op, where the rest of the match is already
    correct and only the NPC target decision changes.
    """
    check_mode(battle_mode)
    if battle_mode=='ffa':raise ValueError('Free-for-all installs its targeting with its battle mode')
    if len(ram)!=0x8000000:raise ValueError('Requires128MiB captured EE RAM')
    import battle_modes
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager,n=u(core.ACTORS),u(core.MODE+4)
    if n not in mode.ACTOR_COUNTS or (u(core.MODE),u(core.MODE+8),u(core.MODE+12))!=(1,manager,n):
        raise ValueError('Install dynamic targeting on the captured active engine')
    if (u(part.CONTROL+4),u(part.CONTROL+8))!=(manager,n):raise ValueError('Missing captured participation')
    mask=u(part.PRESENT)
    if battle_modes.validate_memory(ram)!=(None if battle_mode=='teams' else battle_mode):
        raise ValueError('Dynamic targeting requires its own captured battle mode')
    for i in range(n):
        actor=u(core.POINTERS+4*i)
        if not 0x100000<=actor<len(ram)-0x1600 or (u(actor),u(actor+8))!=(i,i&1):
            raise ValueError('Native actor identity changed')
    if (u(retaliation.CONTROL),u(retaliation.CONTROL+4),u(retaliation.CONTROL+8))!=(1,manager,n):
        raise ValueError('Dynamic targeting replaces an installed retaliation policy')
    if installed_mode(ram)==battle_mode:
        return dict(serial=SERIAL,crc=CRC,source=str(source),mode=battle_mode,blocks=[])
    if any(ram[CODE:END]):raise ValueError('Dynamic targeting reservation occupied')
    pieces=list(program(battle_mode))
    pieces += initial_data(manager,n,mask,[u(core.POINTERS+4*i) for i in range(n)],seed)
    for p,fun,target in ((retaliation.ACCUMULATE,retaliation.accumulate_code,ACCUMULATE),
                         (retaliation.APPLY,retaliation.apply_code,APPLY)):
        original=fun()
        if ram[p:p+len(original)]!=original:raise ValueError(f'Unknown prior retaliation payload:{p:08X}')
        pieces.append((p,struct.pack('<2I',(2<<26)|(target>>2),0)))
    return dict(serial=SERIAL,crc=CRC,source=str(source),mode=battle_mode,
        status='DYNAMIC NPC TARGETING; HUMAN TARGETS REMAIN MANUAL',
        blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=bytes(d).hex()) for p,d in pieces])


def reseed_memory(ram,seed=None,source='<prepared-ffa-rematch>'):
    """Fresh private entropy for a validated cached preparation before release."""
    if installed_mode(ram) is None:raise ValueError('Requires a captured dynamic targeting preparation')
    if struct.unpack_from('<I',ram,CONTROL+16)[0] or any(struct.unpack_from('<I',ram,ROWS+i*ROW_SIZE)[0] for i in range(layout()[0])):
        raise ValueError('Reseed only a fresh held preparation, before any FFA decisions')
    data=struct.pack('<I',seed_value(seed))
    return dict(serial=SERIAL,crc=CRC,source=source,
                blocks=[dict(address=CONTROL+20,expected_hex=ram[CONTROL+20:CONTROL+24].hex(),data_hex=data.hex())])
