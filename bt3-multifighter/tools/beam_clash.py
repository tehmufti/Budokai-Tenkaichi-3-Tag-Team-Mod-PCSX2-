"""Bind the native single beam struggle to the two actual colliding fighters.

Only a captured 4/6 actor world is extended. Original actor/model IDs stay
unchanged; callsite bridges translate the native struggle's two logical sides.
The native timer, stick input, strength, damage and outcome animations remain.
"""
from native_map import A, CRC, FLAG, SERIAL, elf_path
import struct
from prototype import Assembler, ROOT, elf_reader
import fresh_team_combat as core
import team_intro
import result_presentation
import extra_throws as throws
import leader_transform_safety as leader
import cinematic_camera_state as camera
import fresh_team_camera as fresh
import team_participation as participation
import battle_mode_policy as policy
from battle_mode_policy import ACTOR_COUNTS

CODE, CONTROL, END, MAGIC = 0x07243000, 0x0724F000, 0x07250000, 0x42434C31
GATE, VALID, START = CODE, CODE+0x400, CODE+0xC00
FRAME, ABORT, RESOLVE, CONTACT = CODE+0x1800, CODE+0x2000, CODE+0x2800, CODE+0x2C00
PARTICIPANT, ACTOR, MODEL, POSITION = CODE+0x3000, CODE+0x3400, CODE+0x3800, CODE+0x3C00
STOP_MODEL, SCALE, ORDER, WINNER = CODE+0x4000, CODE+0x4400, CODE+0x4800, CODE+0x4C00
NATIVE_FRAME, WIN_CALL, CLEAN_GROUP = CODE+0x5000, CODE+0x5400, CODE+0x5800
READY0, READY1 = CODE+0x5C00, CODE+0x6000
# Header: identity; active(1=pending,2=running), age; accept/reject/finish/abort.
# +40 observed native phase, +44 transition age; +48 last pending age,
# +52 cumulative pending updates; +56/+60 observed participant actions.
# +64 actor[2], +72 model[2], +80 physical[2]; captured actors at +0x100.
ACTIVE, ACTORS, MODELS, INDICES = CONTROL+16, CONTROL+64, CONTROL+72, CONTROL+80
SAVED = tuple(range(2,29))+(30,31)
SAVE_SIZE=0x120
CALLS = {
 READY0: (A(0x12E58C),), READY1: (A(0x12E594),),
 ACTOR: (A(0x1D87A4),A(0x1D89B4),A(0x1D8BBC),A(0x1D8E7C),A(0x1D8E88)),
 MODEL: (A(0x1D8758),A(0x1D8768),A(0x1D8794),A(0x175484),A(0x175494)),
 POSITION: (A(0x1D8C08),A(0x1D8C1C),A(0x1D92C4),A(0x1D92D8)),
 STOP_MODEL: (A(0x174D58),A(0x174D60),A(0x174D9C)),
 SCALE: (A(0x1D8AF4),),
 WIN_CALL: (A(0x1D918C),),
 CLEAN_GROUP: (A(0x174D68),A(0x174D70),A(0x174DA4)),
}
DESTINATIONS={READY0:A(0x1584E8),READY1:A(0x1584E8),ACTOR:A(0x1DC178), MODEL:A(0x206D68), POSITION:A(0x2058E0),
 STOP_MODEL:A(0x158560),SCALE:A(0x174F68),WIN_CALL:A(0x174CE0),CLEAN_GROUP:A(0x12CBC8)}
HOOKS=((A(0x1B0B90),START),(A(0x1D9900),FRAME),(core.RESOLVER,RESOLVE),
       (leader.FALLBACK,CONTACT),(camera.PARTICIPANT,PARTICIPANT),
       (A(0x174AF8),ORDER),(A(0x1D925C),WINNER))


def save(a):
 a.addiu(29,29,-SAVE_SIZE)
 for i,r in enumerate(SAVED):a.i(63,r,29,8*i)


def restore(a,exclude=()):
 for i,r in enumerate(SAVED):
  if r not in exclude:a.i(55,r,29,8*i)
 a.addiu(29,29,SAVE_SIZE)


def bump(a,off):
 a.li(8,CONTROL);a.lw(9,8,off);a.addiu(9,9,1);a.sw(9,8,off)


def gate_code():
 a=Assembler(GATE);core.gate(a,'no')
 a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,'no')
 a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'no')
 a.lw(9,8,8);a.branch(5,9,10,'no')
 a.li(11,team_intro.BATTLE);a.lw(11,11);a.lw(9,8,12);a.branch(5,9,11,'no')
 a.branch(4,11,0,'no');a.lw(9,11);a.addiu(11,0,3);a.branch(5,9,11,'no')
 a.li(9,result_presentation.RESULT);a.lw(9,9);a.branch(5,9,0,'no')
 a.addiu(2,0,1);a.jr();a.label('no');a.move(2,0);a.jr()
 b=a.finish();assert len(b)<=VALID-GATE;return b


def valid_code():
 # Leaf returns v0; pointer identity tolerates temporary AI role aliases.
 a=Assembler(VALID);a.addiu(29,29,-0x10);a.i(63,31,29,0)
 a.call(GATE);a.branch(4,2,0,'done');a.li(8,CONTROL)
 a.lw(9,8,16);a.branch(4,9,0,'no')
 for side in range(2):
  a.lw(12,8,80+4*side);a.lw(10,8,8);a.r(0x2B,9,12,10);a.branch(4,9,0,'no')
  a.lw(13,8,64+4*side);a.r(0,9,0,12,2);a.li(10,core.POINTERS);a.r(0x2D,10,10,9)
  a.lw(10,10);a.branch(5,10,13,'no')
  a.addiu(10,8,0x100);a.r(0x2D,10,10,9);a.lw(10,10);a.branch(5,10,13,'no')
  a.lw(12,8,72+4*side);a.i(11,9,12,12);a.branch(4,9,0,'no')
  a.lw(9,13,12);a.branch(5,9,12,'no')
 a.lw(12,8,80);a.lw(13,8,84)
 policy.emit_enemy(a,12,13,'no','beam_valid',t0=9,t1=10)
 a.addiu(2,0,1);a.jump('done');a.label('no');a.move(2,0)
 a.label('done');a.i(55,31,29,0);a.addiu(29,29,0x10);a.jr()
 b=a.finish();assert len(b)<=START-VALID;return b


def alive(a,actor,fail):
 a.lw(8,actor,0x994);a.i(11,9,8,5);a.branch(4,9,0,fail)
 a.r(0,9,0,8,2);a.r(0x2D,9,9,8);a.r(0,9,0,9,3)
 a.r(0x2D,9,9,8);a.r(0,9,0,9,2);a.r(0x2D,9,9,actor)
 a.lw(8,9,0x9E4);a.branch(6,8,0,fail)


def start_code():
 # Mid-loop original registers: s3 and s2 point to colliding contact rows.
 a=Assembler(START);save(a);a.call(GATE);a.branch(4,2,0,'native')
 a.li(8,core.PAIR+4);a.lw(8,8);a.branch(5,8,0,'reject')
 a.li(8,A(0x3337B8));a.lw(8,8);a.i(12,8,8,0x2000);a.branch(5,8,0,'reject')
 a.li(16,CONTROL);a.lw(8,16,16);a.branch(5,8,0,'reject')
 import dash_clash as dash
 a.li(8,dash.ACTIVE);a.lw(8,8);a.branch(5,8,0,'reject')
 a.lw(8,16,4);a.lw(8,8,64);a.branch(5,8,0,'reject')
 a.call(A(0x174CC0));a.branch(5,2,0,'reject')
 # Both original beam contact records must retain their private resource row.
 for source,base in ((19,0),(18,1)):
  a.lw(4,source);a.i(11,8,4,12);a.branch(4,8,0,'reject')
  a.li(8,core.POINTERS);a.move(17,0);a.lw(22,16,8)
  a.label(f'scan{base}');a.lw(20,8);a.branch(4,20,0,f'next{base}')
  a.lw(9,20,12);a.branch(4,4,9,f'found{base}')
  a.label(f'next{base}');a.addiu(8,8,4);a.addiu(17,17,1);a.branch(5,17,22,f'scan{base}');a.jump('reject')
  a.label(f'found{base}')
  a.r(0,8,0,17,2);a.addiu(9,16,0x100);a.r(0x2D,9,9,8);a.lw(9,9);a.branch(5,9,20,'reject')
  a.lw(9,20);a.branch(5,9,17,'reject')
  # The participation mask excludes absent reserves and fusion-consumed actors.
  a.li(8,participation.CONTROL);a.lw(9,8,4);a.lw(10,16,4);a.branch(5,9,10,'reject')
  a.lw(9,8,12);a.lw(10,8,16);a.r(0x27,10,10,0);a.r(0x24,9,9,10)
  a.addiu(10,0,1);a.r(4,10,17,10);a.r(0x24,9,9,10);a.branch(4,9,0,'reject')
  alive(a,20,'reject')
  a.lw(8,20,2376);a.addiu(9,8,-253);a.i(11,9,9,63);a.branch(4,9,0,'reject')
  for first,n in ((301,6),(313,3)):
   a.addiu(9,8,-first);a.i(11,9,9,n);a.branch(5,9,0,'reject')
  a.li(8,throws.ROWS);a.r(0,9,0,17,2);a.r(0x2D,8,8,9);a.lw(8,8);a.branch(5,8,0,'reject')
  a.move(4,20);a.call(A(0x1E0430));a.addiu(8,2,-2);a.i(11,8,8,3);a.branch(4,8,0,'reject')
  # Actual actor/model pair is stored in temporaries before publication.
  a.addiu(9,29,0xE8+16*base)
  a.sw(20,9);a.sw(17,9,4);a.lw(10,20,12);a.sw(10,9,8)
  if base==0:a.move(23,17)
  else:policy.emit_enemy(a,17,23,'reject','beam_start')
 # Publish side order only after all validations; original contact rows unchanged.
 for side in range(2):
  for field,off in ((0,64),(4,80),(8,72)):
   a.lw(8,29,0xE8+16*side+field);a.sw(8,16,off+4*side)
 a.sw(0,16,20);a.addiu(8,0,1);a.sw(8,16,16);bump(a,24)
 a.lw(4,16,72);a.call(A(0x207350));a.lw(4,16,76);a.call(A(0x207350))
 restore(a);a.jump(A(0x1B0BA0))
 a.label('reject');bump(a,28);restore(a)
 # Same cancellation fallback used natively when a clash is unsupported.
 a.lw(2,29,0x10);a.jump(A(0x1B0B34))
 a.label('native');restore(a);a.move(4,0);a.call(A(0x207350))
 a.addiu(4,0,1);a.call(A(0x207350));a.jump(A(0x1B0BA0))
 b=a.finish();assert len(b)<=FRAME-START;return b


def readiness_code(base,row_register):
 # 12E458 keeps first/second contact+0x20 in s3/s2 after geometry tests.
 # This happens before START reserves a struggle, so VALID is insufficient.
 a=Assembler(base);save(a);a.call(GATE);a.branch(4,2,0,'native')
 a.lw(4,row_register,-0x20);a.i(11,8,4,12);a.branch(4,8,0,'skip')
 a.li(8,core.PAIR+4);a.lw(8,8);a.branch(5,8,0,'skip')
 import dash_clash as dash
 a.li(8,dash.ACTIVE);a.lw(8,8);a.branch(5,8,0,'skip')
 a.li(13,core.POINTERS);a.move(14,0);a.li(15,CONTROL);a.lw(24,15,8)
 a.label('scan');a.lw(12,13);a.branch(4,12,0,'next')
 a.lw(9,12,12);a.branch(4,9,4,'found')
 a.label('next');a.addiu(13,13,4);a.addiu(14,14,1);a.branch(5,14,24,'scan');a.jump('skip')
 a.label('found');a.r(0,8,0,14,2);a.addiu(9,15,0x100);a.r(0x2D,9,9,8)
 a.lw(9,9);a.branch(5,9,12,'skip');a.lw(9,12);a.branch(5,9,14,'skip')
 a.li(8,participation.CONTROL);a.lw(9,8,4);a.lw(10,15,4);a.branch(5,9,10,'skip')
 a.lw(9,8,12);a.lw(10,8,16);a.r(0x27,10,10,0);a.r(0x24,9,9,10)
 a.addiu(10,0,1);a.r(4,10,14,10);a.r(0x24,9,9,10);a.branch(4,9,0,'skip')
 alive(a,12,'skip');a.lw(4,12,12);restore(a,(4,));a.jump(A(0x1584E8))
 a.label('skip');restore(a);a.move(2,0);a.jr()
 a.label('native');restore(a);a.jump(A(0x1584E8))
 b=a.finish();assert len(b)<=0x400;return b


def bridge(base,native,actor=False):
 a=Assembler(base);save(a);a.call(VALID);a.branch(4,2,0,'native')
 a.lw(4,29,SAVED.index(4)*8);a.i(11,8,4,2);a.branch(4,8,0,'native')
 a.r(0,8,0,4,2);a.li(9,ACTORS if actor else MODELS);a.r(0x2D,9,9,8);a.lw(2 if actor else 4,9)
 restore(a,(2,) if actor else (4,))
 if actor:a.jr()
 else:a.jump(native)
 a.label('native');restore(a);a.jump(native)
 b=a.finish();assert len(b)<=0x400;return b


def abort_code():
 a=Assembler(ABORT);save(a);a.call(VALID);a.branch(4,2,0,'clear')
 a.li(16,CONTROL)
 for off in (64,68):
  a.lw(4,16,off);a.addiu(5,0,FLAG(0xAA));a.call(A(0x1DAA50))
  a.lw(4,16,off);a.addiu(5,0,FLAG(0xC3));a.call(A(0x1DA9D0))
 a.addiu(4,0,-1);a.call(A(0x174CE0))
 a.lw(8,16,4);a.lw(9,8,64);a.addiu(9,9,-1);a.i(11,9,9,5)
 a.branch(4,9,0,'clear');a.sw(0,8,64)
 a.label('clear');bump(a,36);a.li(8,CONTROL);a.sw(0,8,16);a.sw(0,8,20)
 restore(a);a.jr()
 b=a.finish();assert len(b)<=RESOLVE-ABORT;return b


def frame_code():
 a=Assembler(FRAME);save(a);a.call(GATE);a.branch(4,2,0,'detached')
 a.li(8,CONTROL);a.lw(9,8,16);a.branch(4,9,0,'native')
 a.li(8,A(0x3337B8));a.lw(8,8);a.i(12,9,8,0x100);a.branch(5,9,0,'native')
 a.i(12,8,8,0x2000);a.branch(5,8,0,'abort')
 a.call(VALID);a.branch(4,2,0,'abort')
 a.li(16,CONTROL);a.lw(8,16,20);a.addiu(8,8,1);a.sw(8,16,20)
 a.i(11,9,8,900);a.branch(4,9,0,'abort')
 # Read-only diagnostics distinguish a startup wait from native stage timing.
 # They never change a participant, scheduler flag or native timer.
 a.lw(9,16,4);a.lw(9,9,64);a.lw(10,16,40)
 a.branch(4,9,10,'same_phase');a.sw(9,16,40);a.sw(8,16,44)
 a.label('same_phase')
 for side in range(2):
  a.lw(9,16,64+4*side);a.lw(9,9,2376);a.sw(9,16,56+4*side)
 # Native coordinator may run one frame before the second AA action commits.
 a.lw(9,16,16);a.addiu(10,0,2);a.branch(4,9,10,'native')
 for side in range(2):
  a.lw(10,16,64+4*side);alive(a,10,'abort')
  a.lw(9,10,2376);a.addiu(9,9,-304);a.i(11,9,9,3);a.branch(4,9,0,'pending')
 a.addiu(9,0,2);a.sw(9,16,16);a.jump('native')
 a.label('pending');a.lw(8,16,20);a.sw(8,16,48)
 a.lw(9,16,52);a.addiu(9,9,1);a.sw(9,16,52)
 a.i(11,8,8,20);a.branch(4,8,0,'abort')
 restore(a);a.move(2,0);a.jr()
 a.label('abort');a.call(ABORT);a.jump('native')
 a.label('detached');a.li(8,CONTROL);a.sw(0,8,16);a.sw(0,8,20)
 a.label('native');restore(a);a.addiu(29,29,-0x30);a.i(63,31,29,0)
 a.call(NATIVE_FRAME);a.i(63,2,29,8);a.i(63,3,29,16)
 # Native phase transition is authoritative; release only after both actors exit.
 save(a);a.call(VALID);a.branch(4,2,0,'return')
 a.li(16,CONTROL);a.lw(8,16,4);a.lw(8,8,64);a.branch(5,8,0,'return')
 a.lw(8,16,16);a.addiu(9,0,2);a.branch(5,8,9,'return')
 for side in range(2):
  a.lw(8,16,64+4*side);a.lw(9,8,2376);a.addiu(9,9,-304);a.i(11,9,9,3);a.branch(5,9,0,'return')
 bump(a,32);a.sw(0,8,16);a.sw(0,8,20)
 a.label('return');restore(a);a.i(55,2,29,8);a.i(55,3,29,16);a.i(55,31,29,0)
 a.addiu(29,29,0x30);a.jr()
 b=a.finish();assert len(b)<=ABORT-FRAME;return b


def resolve_code():
 a=Assembler(RESOLVE);save(a)
 # Private AI slices must keep their explicit virtual roles.
 core.alias_gate(a,'binding');a.jump('native');a.label('binding')
 a.call(VALID);a.branch(4,2,0,'native')
 a.lw(4,29,SAVED.index(4)*8);a.li(8,CONTROL)
 a.lw(9,8,64);a.branch(4,4,9,'zero');a.lw(9,8,68);a.branch(5,4,9,'native')
 a.lw(2,8,64);a.lw(3,8,80);a.jump('yes')
 a.label('zero');a.lw(2,8,68);a.lw(3,8,84)
 a.label('yes');restore(a,(2,3));a.jr()
 a.label('native');restore(a);a.jump(throws.RESOLVE)
 b=a.finish();assert len(b)<=0x400;return b


def contact_code():
 a=Assembler(CONTACT);save(a);a.call(VALID);a.branch(4,2,0,'native')
 a.lw(4,29,SAVED.index(4)*8);a.lw(5,29,SAVED.index(5)*8);a.li(8,CONTROL)
 a.lw(9,8,64);a.lw(10,8,68)
 a.branch(4,4,9,'source0');a.branch(4,4,10,'source1')
 a.branch(4,5,9,'block');a.branch(4,5,10,'block');a.jump('native')
 a.label('source0');a.branch(4,5,10,'allow');a.jump('block')
 a.label('source1');a.branch(4,5,9,'allow')
 a.label('block');restore(a);a.addiu(2,0,1);a.jr()
 a.label('allow');restore(a);a.move(2,0);a.jr()
 a.label('native');restore(a);a.jump(throws.CONTACT)
 b=a.finish();assert len(b)<=0x400;return b


def participant_code():
 a=Assembler(PARTICIPANT);save(a);a.call(VALID);a.branch(4,2,0,'native')
 a.lw(4,29,SAVED.index(4)*8);a.i(11,8,4,2);a.branch(4,8,0,'native')
 a.move(14,4);a.li(8,fresh.SUCCESSOR_CONTROL);a.lw(9,8);a.branch(4,9,0,'owner')
 a.lw(9,8,4);a.lw(10,28,-22364);a.branch(5,9,10,'owner')
 a.r(0,9,0,4,2);a.r(0x2D,8,8,9);a.lw(14,8,8)
 a.label('owner');a.li(8,CONTROL);a.lw(9,8,80);a.branch(4,14,9,'yes')
 a.lw(9,8,84);a.branch(5,14,9,'native')
 a.label('yes');restore(a);a.addiu(2,0,1);a.jr()
 a.label('native');restore(a);a.jump(throws.PARTICIPANT)
 b=a.finish();assert len(b)<=0x400;return b


def order_code():
 a=Assembler(ORDER);save(a);a.call(VALID);a.branch(4,2,0,'old')
 # v0 zero means first record belongs to side0; copied records keep realmodelID.
 a.li(8,MODELS);a.lw(9,8);a.lw(10,17);a.r(0x26,2,9,10);a.jump('return')
 a.label('old');a.lw(2,17)
 a.label('return');restore(a,(2,));a.move(6,18)
 a.branch(5,2,0,'reverse');a.jump(A(0x174B04))
 a.label('reverse');a.jump(A(0x174BA8))
 b=a.finish();assert len(b)<=0x400;return b


def winner_code():
 a=Assembler(WINNER);save(a);a.call(VALID);a.branch(4,2,0,'old')
 a.li(8,ACTORS);a.lw(9,8,4);a.r(0x26,2,19,9);a.r(0x2B,2,0,2);a.i(14,2,2,1)
 a.jump('return');a.label('old');a.lw(2,19)
 a.label('return');restore(a,(2,));a.sw(2,17,4);a.jump(A(0x1D9264))
 b=a.finish();assert len(b)<=0x400;return b


def win_call_code():
 a=Assembler(WIN_CALL);save(a);a.call(VALID);a.branch(4,2,0,'native')
 a.lw(4,29,SAVED.index(4)*8);a.addiu(8,0,-1);a.branch(4,4,8,'native')
 a.li(8,MODELS);a.lw(9,8,4);a.r(0x26,4,4,9);a.r(0x2B,4,0,4);a.i(14,4,4,1)
 restore(a,(4,));a.jump(A(0x174CE0))
 a.label('native');restore(a);a.jump(A(0x174CE0))
 b=a.finish();assert len(b)<=0x400;return b


def clean_group_code():
 # Native 2/3 mean shared owner0/1 aux groups, not arbitrary model indices.
 # The real beam rows are terminated above; the clash object kills itself.
 a=Assembler(CLEAN_GROUP);save(a);a.call(VALID);a.branch(4,2,0,'native')
 restore(a);a.move(2,0);a.jr();a.label('native');restore(a);a.jump(A(0x12CBC8))
 b=a.finish();assert len(b)<=0x400;return b


def pieces(native=None):
 if native is None:native=elf_reader(elf_path(ROOT))[2]
 out=[(GATE,gate_code()),(VALID,valid_code()),(START,start_code()),(FRAME,frame_code()),
 (ABORT,abort_code()),(RESOLVE,resolve_code()),(CONTACT,contact_code()),(PARTICIPANT,participant_code()),
 (ORDER,order_code()),(WINNER,winner_code()),(WIN_CALL,win_call_code()),(CLEAN_GROUP,clean_group_code()),
 (READY0,readiness_code(READY0,19)),(READY1,readiness_code(READY1,18))]
 for base,dest in ((ACTOR,A(0x1DC178)),(MODEL,A(0x206D68)),(POSITION,A(0x2058E0)),(STOP_MODEL,A(0x158560)),(SCALE,A(0x174F68))):
  out.append((base,bridge(base,dest,base==ACTOR)))
 out.append((NATIVE_FRAME,native(A(0x1D9900),8)+struct.pack('<2I',(2<<26)|(A(0x1D9908)>>2),0)))
 for hook,dest in HOOKS:
  out.append((hook,struct.pack('<2I',(2<<26)|(dest>>2),0)))
 # Skip the second obsolete leader AA call too (entry trampoline spans16bytes).
 out.append((A(0x1B0B98),bytes(8)))
 for dest,sites in CALLS.items():
  for hook in sites:out.append((hook,struct.pack('<I',(3<<26)|(dest>>2))))
 return out


def build_memory(ram,config=None,source='<offline-memory>'):
 if len(ram)!=0x8000000:raise ValueError('Requires128MiB captured RAM')
 u=lambda p:struct.unpack_from('<I',ram,p)[0]
 manager,count=u(core.ACTORS),u(core.MODE+4)
 if count not in ACTOR_COUNTS or u(core.MODE)!=1 or u(core.MODE+8)!=manager or u(core.MODE+12)!=count:
  raise ValueError('Requires active captured4/6fighterworld')
 if not 0x100000<=manager<len(ram)-0x1000 or u(manager)!=2 or u(core.PAIR+4):
  raise ValueError('Requires native manager and restored AI roles')
 battle=u(team_intro.BATTLE)
 if not 0x100000<=battle<len(ram)-0x100:raise ValueError('Invalid battle object')
 actors=[u(core.POINTERS+4*i) for i in range(count)]
 if len(set(actors))!=count:raise ValueError('Duplicate actor identities')
 for i,p in enumerate(actors):
  if not 0x100000<=p<len(ram)-0x1600 or u(p)!=i or u(p+12)>=12:raise ValueError('Invalid captured actor/model')
 if u(participation.CONTROL+4)!=manager or u(participation.CONTROL+8)!=count:raise ValueError('Participation capture missing')
 native=elf_reader(elf_path(ROOT))[2]
 header=bytearray(max(0x120,0x100+4*count));struct.pack_into('<4I',header,0,MAGIC,manager,count,battle)
 struct.pack_into('<'+'I'*count,header,0x100,*actors)
 patches=pieces(native)
 existing=u(CONTROL)==MAGIC
 if existing:
  if ram[CONTROL:CONTROL+16]!=header[:16] or ram[CONTROL+0x100:CONTROL+0x100+4*count]!=header[0x100:0x100+4*count]:
   raise ValueError('Existing beam capture does not match')
  # beam_struggle's interference entry (8 bytes at CONTACT) is the one accepted change, while it is installed.
  import beam_struggle
  for p,d in beam_struggle.with_overlay(ram,patches):
   if ram[p:p+len(d)]!=d:raise ValueError(f'Changed installed beam hook{p:08X}')
  return dict(source=str(source),control=CONTROL,blocks=[],status='PAIR-OWNED BEAM CLASH ALREADY INSTALLED')
 if any(ram[CODE:END]):raise ValueError('Beam clash reservation occupied')
 expected_hooks={core.RESOLVER:throws.RESOLVE,leader.FALLBACK:throws.CONTACT,camera.PARTICIPANT:throws.PARTICIPANT}
 for hook,dest in expected_hooks.items():
  if ram[hook:hook+8]!=struct.pack('<2I',(2<<26)|(dest>>2),0):raise ValueError(f'Unexpected existing binding chain{hook:08X}')
 for dest,sites in CALLS.items():
  for hook in sites:
   if u(hook)!=(3<<26)|(DESTINATIONS[dest]>>2) or ram[hook:hook+8]!=native(hook,8):
    raise ValueError(f'Native beam callsite changed{hook:08X}')
 for hook,size in ((A(0x1B0B90),16),(A(0x1D9900),8),(A(0x174AF8),12),(A(0x1D925C),8)):
  if ram[hook:hook+size]!=native(hook,size):raise ValueError(f'Native beam entry changed{hook:08X}')
 patches.append((CONTROL,bytes(header)))
 intervals=sorted((p,p+len(d)) for p,d in patches)
 if any(q<end for (_,end),(q,_) in zip(intervals,intervals[1:])):raise ValueError('Beam patches overlap')
 return dict(serial=SERIAL,crc=CRC,source=str(source),control=CONTROL,
  status='PAIR-OWNED NATIVE BEAM CLASH; LIVE VALIDATION REQUIRED',
  blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex()) for p,d in patches],
  behavior=['One native beam struggle uses actual opposing colliding actors and model resources.',
   'Native stick input, strength, damage and outcome actions remain active.',
   'Additional or invalid beam collisions take the native cancellation path before AA events.',
   'Temporary pair targets and contact protection end with the native struggle; physical IDs stay unchanged.'],
  counters=dict(accepted=CONTROL+24,rejected=CONTROL+28,completed=CONTROL+32,aborted=CONTROL+36,
                phase=CONTROL+40,phase_changed_at=CONTROL+44,last_pending_age=CONTROL+48,
                pending_updates=CONTROL+52,actions=[CONTROL+56,CONTROL+60]))
