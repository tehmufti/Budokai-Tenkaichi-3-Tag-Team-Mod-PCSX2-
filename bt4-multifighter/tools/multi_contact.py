"""Captured multi-opponent contacts through native collision and hit routines.

Ordinary attacks enumerate actual enemy geometry. Lock-on remains independent;
the resolver override exists only while evaluating one actual contact. Authored
paired moves retain their selected recipient and all existing cinematic guards.
"""
from native_map import A, CRC, FLAG, SERIAL, elf_path
import struct
from prototype import Assembler, ROOT, elf_reader
import fresh_team_combat as core
import team_targets6 as geometry
import battle_mode_policy as policy
import team_participation as participation
import cinematic_contact_guard as contact
import dash_clash as dash
import beam_clash as beam
from battle_mode_policy import ACTOR_COUNTS

CODE, CONTROL, END, MAGIC = 0x071A0000, 0x071AF000, 0x071E0000, 0x4D434F31
GATE, VALID, SINGLE, RESOLVE = CODE, CODE+0x400, CODE+0xC00, CODE+0x1800
COLLISION, GATHER, CANCEL, DAMAGE = CODE+0x2000, CODE+0x3000, CODE+0x5000, CODE+0x6000
PROJECTILE, SHOT_WORKER, SHOT_CLASS, SHOT_ROW = CODE+0x7000, CODE+0xA000, CODE+0xB000, CODE+0xC000
SHOT_BEGIN, SHOT_INIT = CODE+0xD000, CODE+0xE000
MELEE_ROWS, PENDING = CODE+0x10000, CODE+0x10100
SHOT_ROWS = CODE+0x20000
# Context: enabled + source/defender physical IDs and captured pointers.
CONTEXT = CONTROL+0x20
NATIVE = elf_reader(elf_path(ROOT))[2]
JUMP = lambda target: struct.pack('<2I',(2<<26)|(target>>2),0)
CALL = lambda target: struct.pack('<I',(3<<26)|(target>>2))
CALL_HOOKS = ((A(0x1CA5A4),GATHER,A(0x1C97C0)),(A(0x1CA5C4),CANCEL,A(0x1C9988)),
              (A(0x1CA5E0),DAMAGE,A(0x1C9B50)))


def save(a):
    a.addiu(29,29,-0x80)
    for i,r in enumerate(range(16,24)):a.i(63,r,29,8*i)
    a.i(63,30,29,64);a.i(63,31,29,72)


def restore(a):
    for i,r in enumerate(range(16,24)):a.i(55,r,29,8*i)
    a.i(55,30,29,64);a.i(55,31,29,72);a.addiu(29,29,0x80)


def increment(a,offset):
    a.li(8,CONTROL);a.lw(9,8,offset);a.addiu(9,9,1);a.sw(9,8,offset)


def context(a,source,target):
    a.li(8,CONTEXT);a.lw(9,source);a.sw(9,8,4);a.lw(9,target);a.sw(9,8,8)
    a.sw(source,8,12);a.sw(target,8,16);a.addiu(9,0,1);a.sw(9,8)


def clear_context(a):
    a.li(8,CONTEXT);a.sw(0,8)


def gate_code():
    a=Assembler(GATE);core.gate(a,'no');a.li(8,CONTROL)
    a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,'no')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'no')
    a.lw(9,8,8);a.branch(5,9,10,'no')
    a.li(9,core.PAIR+4);a.lw(9,9);a.branch(5,9,0,'no')
    a.addiu(2,0,1);a.jr();a.label('no');a.move(2,0);a.jr()
    data=a.finish();assert len(data)<=VALID-GATE;return data


def valid_code():
    """Actual a0/a1 pointers -> Boolean; all identity/participation checks first."""
    a=Assembler(VALID);a.addiu(29,29,-16);a.i(63,31,29,0)
    a.call(GATE);a.branch(4,2,0,'done')
    for actor,pid in ((4,12),(5,13)):
        a.li(8,0x100000);a.r(0x2B,9,actor,8);a.branch(5,9,0,'no')
        a.li(8,0x8000000-0x1600);a.r(0x2B,9,8,actor);a.branch(5,9,0,'no')
        a.lw(pid,actor);a.r(0x2B,9,pid,10);a.branch(4,9,0,'no')
        a.r(0,9,0,pid,2)
        for table in (core.POINTERS,CONTROL+0x100):
            a.li(8,table);a.r(0x2D,8,8,9);a.lw(8,8);a.branch(5,8,actor,'no')
        geometry.alive_argument(a,actor,'no')
        a.li(8,participation.CONTROL);a.lw(9,8,4);a.lw(11,28,-22364)
        a.branch(5,9,11,'no');a.lw(9,8,8);a.branch(5,9,10,'no')
        a.lw(9,8,12);a.lw(11,8,16);a.r(0x27,11,11,0);a.r(0x24,9,9,11)
        a.addiu(11,0,1);a.r(4,11,pid,11);a.r(0x24,9,9,11);a.branch(4,9,0,'no')
    policy.emit_enemy(a,12,13,'no','contact_enemy')
    a.addiu(2,0,1);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');a.i(55,31,29,0);a.addiu(29,29,16);a.jr()
    data=a.finish();assert len(data)<=SINGLE-VALID;return data


def single_code():
    """a0 actor: paired moves and dash/rush entry flags retain one recipient."""
    a=Assembler(SINGLE)
    for offset in contact.PAIRED_FIELDS:
        a.lw(8,4,offset)
        for first,length in ((180,8),(250,3),(301,15)):
            a.addiu(9,8,-first);a.i(11,9,9,length);a.branch(5,9,0,'yes')
    contact.paired_pending(a,4,'yes')
    for bank in (0x1085,0x10AD):
        for flag in (FLAG(0x47),FLAG(0x48),FLAG(0x49)):
            a.i(36,8,4,bank+(flag>>3));a.i(12,8,8,1<<(flag&7));a.branch(5,8,0,'yes')
    a.move(2,0);a.jr();a.label('yes');a.addiu(2,0,1);a.jr()
    data=a.finish();assert len(data)<=RESOLVE-SINGLE;return data


def resolve_code():
    a=Assembler(RESOLVE);a.addiu(29,29,-0x20)
    for i,r in enumerate((8,9,10,31)):a.i(63,r,29,8*i)
    a.call(GATE);a.branch(4,2,0,'old');a.li(8,CONTEXT);a.lw(9,8)
    a.branch(4,9,0,'old');a.lw(9,8,12);a.branch(4,4,9,'source')
    a.lw(9,8,16);a.branch(5,4,9,'old');a.lw(2,8,12);a.lw(3,8,4);a.jump('done')
    a.label('source');a.lw(2,8,16);a.lw(3,8,8)
    a.label('done')
    for i,r in enumerate((8,9,10,31)):a.i(55,r,29,8*i)
    a.addiu(29,29,0x20);a.jr()
    a.label('old')
    for i,r in enumerate((8,9,10,31)):a.i(55,r,29,8*i)
    a.addiu(29,29,0x20);a.jump(dash.RESOLVE)
    data=a.finish();assert len(data)<=COLLISION-RESOLVE;return data


def actor(a,destination,index):
    a.li(8,core.POINTERS);a.r(0,9,0,index,2);a.r(0x2D,8,8,9);a.lw(destination,8)


def collision_code():
    a=Assembler(COLLISION);save(a);a.call(GATE);a.branch(4,2,0,'old')
    a.move(23,10);a.li(8,core.MATRIX_CONTROL);a.lw(9,8,8);a.addiu(9,9,1);a.sw(9,8,8)
    a.li(8,core.MATRIX_ROWS);a.addiu(9,8,48)
    a.label('clear');a.sw(0,8);a.addiu(8,8,4);a.branch(5,8,9,'clear')
    a.move(16,0)
    a.label('source');actor(a,18,16);a.move(4,18);a.call(SINGLE);a.move(22,2)
    a.move(4,18);a.call(dash.RESOLVE);a.move(21,3);a.move(17,0)
    a.label('target');a.branch(4,22,0,'all');a.branch(5,17,21,'next')
    a.label('all');actor(a,19,17);a.move(4,18);a.move(5,19);a.call(VALID)
    a.branch(4,2,0,'next')
    geometry.model_argument(a,4,18,'next');geometry.model_argument(a,5,19,'next')
    a.call(A(0x1AF650));increment(a,16)
    a.label('next');a.addiu(17,17,1);a.branch(5,17,23,'target')
    a.addiu(16,16,1);a.branch(5,16,23,'source')
    a.move(2,0);restore(a);a.jr()
    a.label('old');restore(a);a.jump(core.BEGIN)
    data=a.finish();assert len(data)<=GATHER-COLLISION;return data


def gather_code():
    """Native hit-latch evaluation per contacted defender; defer damage normally."""
    a=Assembler(GATHER);save(a);a.move(16,4);a.call(GATE);a.branch(4,2,0,'old')
    a.move(23,10);a.lw(17,16);a.r(0x2B,8,17,23);a.branch(4,8,0,'old')
    a.r(0,8,0,17,2);a.li(21,PENDING);a.r(0x2D,21,21,8);a.sw(0,21)
    a.li(22,MELEE_ROWS);a.r(0x2D,22,22,8)
    a.move(4,16);a.call(SINGLE);a.branch(5,2,0,'single')
    # The original 1C8F18 has already updated attack segment CAD/F44. Its
    # native latch clear resets every victim's reservation at the same boundary.
    a.move(4,16);a.addiu(5,0,FLAG(0x60));a.call(A(0x1DAC78))
    a.branch(5,2,0,'latched');a.sw(0,22)
    a.label('latched');a.lw(8,16,0xF48);a.sw(8,29,80)
    a.move(4,16);a.call(dash.RESOLVE);a.sw(3,29,84)
    a.addiu(8,0,-1);a.sw(8,29,88);a.move(18,0)
    a.label('victim');actor(a,19,18);a.move(4,16);a.move(5,19);a.call(VALID)
    a.branch(4,2,0,'next')
    a.lw(8,16,12);a.r(0,8,0,8,2);a.li(9,core.MATRIX_ROWS);a.r(0x2D,8,8,9);a.lw(8,8)
    a.lw(9,19,12);a.addiu(10,0,1);a.r(4,10,9,10);a.r(0x24,8,8,10)
    a.branch(5,8,0,'contact')
    # Native flag65 permits the selected-target follow-through even without a
    # fresh geometry bit. Preserve that authored exception for that target.
    a.lw(8,29,84);a.branch(5,8,18,'next')
    a.move(4,16);a.addiu(5,0,FLAG(0x65));a.call(A(0x1DAC78));a.branch(4,2,0,'next')
    a.label('contact')
    a.addiu(20,0,1);a.r(4,20,18,20);a.lw(8,22);a.r(0x24,8,8,20)
    a.move(4,16);a.addiu(5,0,FLAG(0x60));a.branch(4,8,0,'unhit')
    a.call(A(0x1DA9D0));a.jump('evaluate');a.label('unhit');a.call(A(0x1DAA50))
    a.label('evaluate');a.lw(8,29,80);a.sw(8,16,0xF48)
    a.addiu(8,0,-1);a.sw(8,16,0xF40);context(a,16,19)
    a.move(4,16);a.call(A(0x1C97C0));clear_context(a)
    a.lw(8,16,0xF40);a.branch(5,8,18,'latch')
    a.lw(8,21);a.r(0x25,8,8,20);a.sw(8,21)
    a.lw(8,29,84);a.branch(5,8,18,'latch');a.sw(18,29,88)
    a.label('latch');a.move(4,16);a.addiu(5,0,FLAG(0x60));a.call(A(0x1DAC78))
    a.branch(4,2,0,'next');a.lw(8,22);a.r(0x25,8,8,20);a.sw(8,22)
    a.label('next');a.addiu(18,18,1);a.branch(5,18,23,'victim')
    a.lw(8,29,88);a.sw(8,16,0xF40)
    # F48 is a source animation counter, not a count of enemy geometry tests.
    a.lw(8,29,80);a.sw(8,16,0xF48);a.move(4,16);a.addiu(5,0,FLAG(0x65));a.call(A(0x1DAC78))
    a.branch(4,2,0,'aggregate');a.lw(8,16,0xF48);a.addiu(8,8,1);a.sw(8,16,0xF48)
    a.label('aggregate');a.move(4,16);a.addiu(5,0,FLAG(0x60));a.lw(8,22)
    a.branch(4,8,0,'clear');a.call(A(0x1DA9D0));a.jump('done')
    a.label('clear');a.call(A(0x1DAA50));a.jump('done')
    a.label('single');a.addiu(8,0,-1);a.sw(8,21)
    a.label('old');a.move(4,16);a.call(A(0x1C97C0))
    a.label('done');restore(a);a.jr()
    data=a.finish();assert len(data)<=CANCEL-GATHER;return data


def cancel_code():
    """Native reciprocal strike arbitration for every queued pair, once."""
    a=Assembler(CANCEL);save(a);a.call(GATE);a.branch(4,2,0,'old');a.move(23,10)
    # Preserve the native first pass, including mixed ordinary/single-paired
    # rows. Its cancellations must also remove the matching multi-queue bit.
    a.move(16,0);a.label('save_ids');actor(a,18,16)
    a.lw(8,18,0xF40);a.r(0,9,0,16,2);a.addiu(10,29,80);a.r(0x2D,10,10,9);a.sw(8,10)
    a.addiu(16,16,1);a.branch(5,16,23,'save_ids')
    a.call(A(0x1C9988));a.move(16,0)
    a.label('native_result');actor(a,18,16);a.r(0,9,0,16,2)
    a.addiu(20,29,80);a.r(0x2D,20,20,9);a.lw(8,20);a.lw(19,18,0xF40)
    a.r(0x2B,10,8,23);a.branch(4,10,0,'saved_result')
    a.addiu(10,0,-1);a.branch(5,19,10,'saved_result')
    a.li(21,PENDING);a.r(0x2D,21,21,9);a.lw(11,21);a.branch(4,11,10,'saved_result')
    a.addiu(10,0,1);a.r(4,10,8,10);a.r(0x27,10,10,0);a.r(0x24,11,11,10);a.sw(11,21)
    a.label('saved_result');a.sw(19,20);a.addiu(8,0,-1);a.sw(8,18,0xF40)
    a.addiu(16,16,1);a.branch(5,16,23,'native_result')
    a.move(16,0);a.label('left');a.addiu(17,16,1)
    a.label('right');a.r(0x2B,8,17,23);a.branch(4,8,0,'next_left')
    a.r(0,8,0,16,2);a.li(20,PENDING);a.r(0x2D,20,20,8);a.lw(8,20)
    a.addiu(9,0,-1);a.branch(4,8,9,'next_right');a.addiu(10,0,1);a.r(4,10,17,10)
    a.r(0x24,8,8,10);a.branch(4,8,0,'next_right')
    a.r(0,8,0,17,2);a.li(21,PENDING);a.r(0x2D,21,21,8);a.lw(8,21)
    a.branch(4,8,9,'next_right');a.addiu(11,0,1);a.r(4,11,16,11)
    a.r(0x24,8,8,11);a.branch(4,8,0,'next_right')
    actor(a,18,16);actor(a,19,17);a.sw(17,18,0xF40);a.sw(16,19,0xF40)
    a.call(A(0x1C9988))
    for source,target,row in ((18,17,20),(19,16,21)):
        a.addiu(9,0,-1);a.lw(8,source,0xF40);tag=f'kept_{source}';a.branch(5,8,9,tag)
        a.addiu(10,0,1);a.r(4,10,target,10);a.r(0x27,10,10,0);a.lw(8,row);a.r(0x24,8,8,10);a.sw(8,row)
        a.label(tag);a.addiu(8,0,-1);a.sw(8,source,0xF40);a.addiu(9,0,-1)
    a.label('next_right');a.addiu(17,17,1);a.jump('right')
    a.label('next_left');a.addiu(16,16,1);a.branch(5,16,23,'left')
    a.move(16,0);a.label('restore_ids');actor(a,18,16)
    a.r(0,9,0,16,2);a.addiu(10,29,80);a.r(0x2D,10,10,9);a.lw(8,10)
    a.r(0x2B,10,8,23);a.branch(4,10,0,'restore_one')
    a.li(10,PENDING);a.r(0x2D,10,10,9);a.lw(10,10);a.addiu(11,0,-1)
    a.branch(4,10,11,'restore_one');a.addiu(11,0,1);a.r(4,11,8,11);a.r(0x24,10,10,11)
    a.branch(5,10,0,'restore_one');a.addiu(8,0,-1)
    a.label('restore_one');a.sw(8,18,0xF40)
    a.addiu(16,16,1);a.branch(5,16,23,'restore_ids')
    restore(a);a.jr();a.label('old');restore(a);a.jump(A(0x1C9988))
    data=a.finish();assert len(data)<=DAMAGE-CANCEL;return data


def damage_code():
    a=Assembler(DAMAGE);save(a);a.move(16,4);a.call(GATE);a.branch(4,2,0,'old');a.move(23,10)
    a.lw(17,16);a.r(0x2B,8,17,23);a.branch(4,8,0,'old')
    a.r(0,8,0,17,2);a.li(21,PENDING);a.r(0x2D,21,21,8);a.lw(22,21)
    a.addiu(8,0,-1);a.branch(4,22,8,'old');a.lw(20,16,0xF40);a.move(18,0)
    a.label('victim');a.addiu(8,0,1);a.r(4,8,18,8);a.r(0x24,8,8,22);a.branch(4,8,0,'next')
    actor(a,19,18);a.move(4,16);a.move(5,19);a.call(VALID);a.branch(4,2,0,'next')
    a.sw(18,16,0xF40);context(a,16,19);a.move(4,16);a.call(A(0x1C9B50));clear_context(a);increment(a,20)
    a.label('next');a.addiu(18,18,1);a.branch(5,18,23,'victim')
    a.sw(20,16,0xF40);a.sw(0,21);restore(a);a.jr()
    a.label('old');a.move(4,16);restore(a);a.jump(A(0x1C9B50))
    data=a.finish();assert len(data)<=PROJECTILE-DAMAGE;return data


def shot_begin_code():
    a=Assembler(SHOT_BEGIN);beam.save(a);a.call(GATE);a.branch(4,2,0,'native')
    increment(a,60);a.label('native');beam.restore(a)
    for word in struct.unpack('<2I',NATIVE(A(0x1B0030),8)):a.emit(word)
    a.jump(A(0x1B0038));return a.finish()


def shot_init_code():
    """Invalidate shadow state at the real persistent effect initialization.

    Recycled pointers may have the same descriptors and zero A/B counters.
    This runs even inside temporary AI/model aliases, because allocation can
    occur there. It only invalidates our matching keys before exact native init.
    """
    a=Assembler(SHOT_INIT);beam.save(a);a.li(8,CONTROL);a.lw(9,8)
    a.li(10,MAGIC);a.branch(5,9,10,'native');a.li(8,SHOT_ROWS);a.addiu(10,0,64)
    a.label('row');a.lw(9,8);a.branch(5,9,4,'next');a.sw(0,8)
    a.label('next');a.addiu(8,8,0x100);a.addiu(10,10,-1);a.branch(5,10,0,'row')
    a.label('native');beam.restore(a)
    for word in struct.unpack('<2I',NATIVE(A(0x1AD988),8)):a.emit(word)
    a.jump(A(0x1AD990))
    data=a.finish();assert len(data)<=CONTROL-SHOT_INIT;return data


def shot_worker_code():
    """Relocate the exact native one-model geometry/contact block, including
    float range checks, block/deflect checks and repeating-hit callbacks.

    a0=record,a1=defender model ID,a2=model,a3=native projectile index.
    Native side effects stay in place; only exits become this worker's return.
    """
    a=Assembler(SHOT_WORKER);a.addiu(29,29,-0x60)
    for i,r in enumerate((16,17,18,19,20,31)):a.i(63,r,29,0x20+8*i)
    a.move(16,4);a.move(17,5);a.addiu(18,4,0x130);a.move(19,7);a.move(2,6)
    a.lw(20,28,-0x58C8)
    for i in range(7):
        a.li(8,struct.unpack('<I',NATIVE(A(0x2ED838)+4*i,4))[0]);a.sw(8,29,4*i)
    lo,hi=A(0x1B00E8),A(0x1B01FC)
    for p in range(lo,hi,4):
        a.label(f'n_{p:x}');word=struct.unpack('<I',NATIVE(p,4))[0];op=word>>26
        if op in (1,4,5,6,7,20,21,22,23) or (op==17 and (word>>21)&31==8):
            signed=(word&65535)-0x10000 if word&0x8000 else word&65535
            target=p+4+4*signed
            label=f'n_{target:x}' if lo<=target<hi else 'done'
            if not lo<=target<hi and target not in (A(0x1B01FC),A(0x1B0200)):
                raise ValueError(f'Unreviewed projectile branch {p:X}->{target:X}')
            # Preserve the exact opcode/register fields, including likely and
            # floating-condition branches. Assembler resolves just the offset.
            a.fixups.append((len(a.words),label,'branch'));a.emit(word&0xFFFF0000)
        else:a.emit(word)
    a.label('done')
    for i,r in enumerate((16,17,18,19,20,31)):a.i(55,r,29,0x20+8*i)
    a.addiu(29,29,0x60);a.jr()
    data=a.finish();assert len(data)<=SHOT_CLASS-SHOT_WORKER;return data


def shot_class_code():
    """a0=source,a1=record -> only authored capture reactions stay selected.

    Native1CC6D4..1CC728 binds reactions29/30 through1CC2A0 and34 through
    1CA6D0. Check both regular/guarded and normal/alternate descriptor variants.
    """
    a=Assembler(SHOT_CLASS);save(a);a.move(16,4);a.move(17,5)
    a.call(SINGLE);a.branch(5,2,0,'yes');a.lw(18,17,0x64)
    a.lw(8,17,0x68);a.branch(5,8,0,'no');a.branch(4,18,0,'no')
    a.lw(18,18,4);a.addiu(8,18,-2);a.i(11,8,8,3);a.branch(4,8,0,'no')
    for fun in (A(0x211080),A(0x2110B0),A(0x2110F8),A(0x211128)):
        a.move(4,16);a.move(5,18);a.call(fun)
        for value in (29,30,34):a.addiu(8,0,value);a.branch(4,2,8,'yes')
    a.label('no');a.move(2,0);a.jump('done');a.label('yes');a.addiu(2,0,1)
    a.label('done');restore(a);a.jr()
    data=a.finish();assert len(data)<=SHOT_ROW-SHOT_CLASS;return data


def shot_row_code():
    """a0 record,a1 physical owner -> persistent per-victim native A/B bytes.

    Native12DEA8 rebuilds up to64 transient records each frame. The persistent
    effect at record+60 owns repeat bytes+A/+B. Keys use that pointer, owner and
    both descriptor pointers; external counter reset also starts a new epoch.
    """
    a=Assembler(SHOT_ROW);a.lw(12,4,0x60);a.li(8,0x100000)
    a.r(0x2B,9,12,8);a.branch(5,9,0,'no');a.li(8,0x8000000-0x40)
    a.r(0x2B,9,8,12);a.branch(5,9,0,'no')
    a.li(2,SHOT_ROWS);a.li(8,CONTROL);a.lw(13,8,60);a.move(14,0);a.move(15,0);a.move(11,0)
    a.label('scan');a.lw(8,2);a.branch(4,8,12,'key')
    a.branch(4,8,0,'empty');a.lw(8,2,24);a.branch(4,8,13,'next')
    a.branch(5,15,0,'next');a.move(15,2);a.jump('next')
    # Initializer invalidation leaves holes. Finish looking for an existing
    # persistent key before allocating a new row, preserving its victim clocks.
    a.label('empty');a.branch(5,11,0,'next');a.move(15,2);a.addiu(11,0,1);a.jump('next')
    a.label('key');a.lw(8,2,4);a.branch(5,8,5,'reset')
    for field,stored in ((0x64,8),(0x68,12)):
        a.lw(8,4,field);a.lw(9,2,stored);a.branch(5,8,9,'reset')
    for field,stored in ((10,16),(11,20)):
        a.i(36,8,12,field);a.lw(9,2,stored);a.branch(5,8,9,'reset')
    a.sw(13,2,24);a.jr()
    a.label('next');a.addiu(2,2,0x100);a.addiu(14,14,1);a.i(11,8,14,64);a.branch(5,8,0,'scan')
    a.branch(4,15,0,'no');a.move(2,15)
    a.label('reset');a.sw(12,2);a.sw(5,2,4);a.lw(8,4,0x64);a.sw(8,2,8)
    a.lw(8,4,0x68);a.sw(8,2,12);a.sw(13,2,24)
    a.i(36,8,12,10);a.sw(8,2,16);a.i(36,9,12,11);a.sw(9,2,20)
    a.r(0,9,0,9,8);a.r(0x25,8,8,9)
    # A new owner resets the repeat-hit clock of every victim the engine can
    # hold. Leaving victims 6+ at a previous owner's values could refuse a hit.
    # Three-a-side installs reset six (policy.emitted_tables()).
    for i in range(policy.emitted_tables()):a.sw(8,2,32+4*i)
    a.jr();a.label('no');a.move(2,0);a.jr()
    data=a.finish();assert len(data)<=SHOT_BEGIN-SHOT_ROW;return data


def projectile_code():
    a=Assembler(PROJECTILE);beam.save(a);a.call(GATE);a.branch(4,2,0,'old')
    a.move(23,10);a.move(30,16);a.sw(19,29,0x100) # native s0 record / s3 index
    a.lw(8,30,0x68);a.lw(9,30,0x64);a.lw(17,30)
    a.branch(5,8,0,'model_source');a.branch(4,9,0,'model_source')
    a.r(0x2B,8,17,23);a.branch(4,8,0,'done');actor(a,16,17);a.jump('source_found')
    a.label('model_source');a.move(18,0)
    a.label('source_scan');actor(a,16,18);a.branch(4,16,0,'source_next')
    a.lw(8,16,12);a.branch(4,8,17,'model_found')
    a.label('source_next');a.addiu(18,18,1);a.branch(5,18,23,'source_scan');a.jump('done')
    a.label('model_found');a.move(17,18)
    a.label('source_found');a.move(4,16);a.call(dash.RESOLVE);a.sw(3,29,0xF0)
    a.move(4,16);a.move(5,30);a.call(SHOT_CLASS);a.sw(2,29,0xF4)
    a.move(4,30);a.move(5,17);a.call(SHOT_ROW);a.move(22,2);a.branch(4,22,0,'done')
    a.lw(21,30,0x60);a.sw(0,29,0xE8);a.sw(0,29,0xEC);a.sw(0,29,0xF8)
    a.move(18,0)
    a.label('target');a.lw(8,29,0xF4);a.branch(4,8,0,'all')
    a.lw(8,29,0xF0);a.branch(5,8,18,'next')
    a.label('all');actor(a,19,18);a.move(4,16);a.move(5,19);a.call(VALID)
    a.branch(4,2,0,'next');a.move(4,16);a.move(5,19);a.call(contact.PROTECTED)
    a.branch(5,2,0,'next');a.move(4,19);a.move(5,16);a.call(contact.PROTECTED)
    a.branch(5,2,0,'next');geometry.model_argument(a,6,19,'next')
    a.sw(6,29,0xFC);a.r(0,8,0,18,2);a.addiu(20,22,32);a.r(0x2D,20,20,8)
    a.i(36,8,20,0);a.i(40,8,21,10);a.i(36,8,20,1);a.i(40,8,21,11)
    context(a,16,19);a.move(4,30);a.lw(5,19,12);a.lw(6,29,0xFC);a.lw(7,29,0x100)
    a.call(SHOT_WORKER);clear_context(a);increment(a,24)
    for field,stored,temp in ((10,0,0xE8),(11,1,0xEC)):
        a.i(36,8,21,field);a.i(40,8,20,stored);a.lw(9,29,temp)
        a.r(0x2B,10,9,8);a.r(0x0B,9,8,10);a.sw(9,29,temp)
    a.addiu(8,0,1);a.sw(8,29,0xF8)
    a.label('next');a.addiu(18,18,1);a.branch(5,18,23,'target')
    a.lw(8,29,0xF8);a.branch(4,8,0,'done')
    for temp,field,stored in ((0xE8,10,16),(0xEC,11,20)):
        a.lw(8,29,temp);a.i(40,8,21,field);a.sw(8,22,stored)
    a.label('done');clear_context(a);beam.restore(a);a.jump(A(0x1B01FC))
    a.label('old');beam.restore(a);a.jump(core.PROJECTILE)
    data=a.finish();assert len(data)<=SHOT_WORKER-PROJECTILE;return data


def pieces():
    payloads=[(GATE,gate_code()),(VALID,valid_code()),(SINGLE,single_code()),
              (RESOLVE,resolve_code()),(COLLISION,collision_code()),
              (GATHER,gather_code()),(CANCEL,cancel_code()),(DAMAGE,damage_code()),
              (PROJECTILE,projectile_code()),(SHOT_WORKER,shot_worker_code()),
              (SHOT_CLASS,shot_class_code()),(SHOT_ROW,shot_row_code()),
              (SHOT_BEGIN,shot_begin_code()),(SHOT_INIT,shot_init_code())]
    payloads += [(A(0x1AF740),JUMP(COLLISION)),(A(0x1B00C4),JUMP(PROJECTILE)),
                 (core.RESOLVER,JUMP(RESOLVE)),(A(0x1B0030),JUMP(SHOT_BEGIN)),
                 (A(0x1AD988),JUMP(SHOT_INIT))]
    payloads += [(p,CALL(target)) for p,target,_ in CALL_HOOKS]
    spans=sorted((p,p+len(b)) for p,b in payloads)
    if any(end>q for (_,end),(q,_) in zip(spans,spans[1:])):raise ValueError('Multi-contact code overlaps')
    return payloads


def originals():
    return [(A(0x1AF740),JUMP(core.BEGIN)),(A(0x1B00C4),JUMP(core.PROJECTILE)),
            (core.RESOLVER,JUMP(dash.RESOLVE)),(A(0x1B0030),NATIVE(A(0x1B0030),8)),
            (A(0x1AD988),NATIVE(A(0x1AD988),8))] + [
                (p,NATIVE(p,4)) for p,_,_ in CALL_HOOKS]


def installed_pieces(ram):
    """Canonical contact program plus an exact optional counter-pair layer."""
    import vanish_pair_guard
    return list((dict(pieces()) | dict(vanish_pair_guard.overlay(ram))).items())


def validate(ram,manager,count):
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if (u(CONTROL),u(CONTROL+4),u(CONTROL+8))!=(MAGIC,manager,count):
        raise ValueError('Changed multi-contact captured identity')
    for i in range(count):
        if u(CONTROL+0x100+4*i)!=u(core.POINTERS+4*i):raise ValueError('Changed multi-contact actor table')
    for p,b in installed_pieces(ram):
        if ram[p:p+len(b)]!=b:raise ValueError(f'Changed multi-contact payload {p:08X}')
    for p,_,_ in CALL_HOOKS:
        if ram[p+4:p+8]!=NATIVE(p+4,4):raise ValueError(f'Changed multi-contact delay {p:08X}')


def base_view(ram,manager,count):
    """Strict validation, then canonical previous hooks in a disposable copy."""
    if not any(ram[CODE:END]):return ram
    validate(ram,manager,count);out=bytearray(ram)
    for p,b in originals():out[p:p+len(b)]=b
    return out


def prior_manifest(ram,builder):
    """Run a prior optional upgrader without dismantling this outer stage.

    This is a validated read view, never an installed rollback. Changes away
    from our hooks retain their real original guard; incompatible hook edits
    are rejected instead of silently losing multi-contact routing.
    """
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    view=base_view(ram,u(core.ACTORS),u(core.MODE+4))
    result=builder(view)
    if view is ram:return result
    hooks=originals();blocks=[]
    for block in result['blocks']:
        p=block['address'];old=bytes.fromhex(block['expected_hex']);data=bytes.fromhex(block['data_hex'])
        if view[p:p+len(old)]!=old:raise ValueError('Changed prior-builder guard')
        data=bytearray(data)
        for hook,baseline in hooks:
            lo=max(p,hook);hi=min(p+len(data),hook+len(baseline))
            if lo<hi:
                if data[lo-p:hi-p]!=view[lo:hi]:raise ValueError('Prior upgrade changes multi-contact predecessor')
                data[lo-p:hi-p]=ram[lo:hi]
        if data!=ram[p:p+len(data)]:
            blocks.append(dict(block,expected_hex=ram[p:p+len(old)].hex(),data_hex=data.hex()))
    return dict(result,blocks=blocks)


def build_memory(ram,source='<prepared>'):
    if len(ram)!=0x8000000:raise ValueError('Multi-contact requires 128 MiB captured RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if count not in ACTOR_COUNTS or (u(core.MODE),u(core.MODE+8),u(core.MODE+12))!=(1,manager,count):
        raise ValueError('Multi-contact requires captured active fighter publication')
    if u(CONTROL)==MAGIC:
        validate(ram,manager,count);return dict(source=str(source),control=CONTROL,blocks=[])
    if any(ram[CODE:END]):raise ValueError('Multi-contact reservation occupied')
    if dash.build_memory(ram)['blocks']:raise ValueError('Install actual-pair dash/beam guards first')
    for p,b in originals():
        if ram[p:p+len(b)]!=b:raise ValueError(f'Unknown multi-contact predecessor {p:08X}')
    for p,target,old in CALL_HOOKS:
        if NATIVE(p,4)!=CALL(old) or ram[p:p+8]!=NATIVE(p,8):raise ValueError(f'Changed native damage call {p:X}')
    # Keep geometry, contact producer and native damage bodies exact. Existing
    # owned cinematic entry guards are deliberately invoked, never bypassed.
    for p,b,_ in core.program():
        if p in (core.COLLISION,core.PROJECTILE,core.BEGIN,core.RECORD,core.RECORD_INNER):
            if ram[p:p+len(b)]!=b:raise ValueError(f'Changed collision dependency {p:08X}')
    actors=[u(core.POINTERS+4*i) for i in range(count)]
    if len(set(actors))!=count:raise ValueError('Duplicate multi-contact fighter')
    for i,p in enumerate(actors):
        if not 0x100000<=p<0x8000000-0x1600 or u(p)!=i or u(p+12)>=12:
            raise ValueError('Invalid multi-contact actor/model')
    header=bytearray(max(0x120,0x100+4*count));struct.pack_into('<3I',header,0,MAGIC,manager,count)
    struct.pack_into('<'+'I'*count,header,0x100,*actors)
    blocks=pieces()+[(CONTROL,bytes(header))]
    return dict(serial=SERIAL,crc=CRC,source=str(source),control=CONTROL,
                status='MULTI-OPPONENT NATIVE CONTACTS; LIVE VALIDATION REQUIRED',
                blocks=[dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=b.hex()) for p,b in blocks])
