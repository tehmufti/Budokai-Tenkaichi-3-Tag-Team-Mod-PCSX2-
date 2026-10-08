"""Optional Genocide Blast streams with native per-enemy children.

Super Buu114 Genocide Blast (slot2, family1) and Krillin25 Scattering Bullet
(slot3, family4) have separately switchable, exact resource guards. Extend
its native free-node chain using a real heap allocation, give every child an
independent row/descriptor and target, and let the native effect/collision code
do the rest. Parent destruction drains children before freeing the extension.
No target-table, actor-damage, allocator-alias or original-resource writes.
"""
from native_map import A, CRC, SERIAL, TRANSLATED, elf_path
import struct
from prototype import Assembler, ROOT, elf_reader
import fresh_team_combat as core
import battle_mode_policy as policy
import multi_contact as contacts
import team_intro
import result_presentation as result

KEY='buu_ultimate_all_enemies'
KRILLIN_KEY='krillin_scattering_all_enemies'
CODE,END=0x070E0000,0x070F0000
SPAWN,QUALIFY,ENSURE,FIND_NODE=CODE,CODE+0x1800,CODE+0x3000,CODE+0x5000
UPDATE,CLEANUP,TARGET,INITIAL,HOMING=CODE+0x6000,CODE+0x7000,CODE+0x7800,CODE+0x8000,CODE+0x8800
UPDATE_OLD,CLEANUP_OLD=CODE+0x9000,CODE+0x9100
KRILLIN_UPDATE_OLD,KRILLIN_CLEANUP_OLD=CODE+0x9200,CODE+0x9300
PHYSICAL=CODE+0xB000
ENEMY=CODE+0x9800
ACTIVE_FOR_TARGET=CODE+0xA800
CONTEXT,CONTROL,RECORDS=CODE+0xEE00,CODE+0xEF00,CODE+0xF000
MAGIC=0x42554631
STRIDE,ROW,DESC,NODE,BODY=0x2000,0x40,0x90,0x140,0x180
PARENT_CALLBACKS,CHILD_CALLBACKS=A(0x2C37B8),A(0x2C37D0)
KRILLIN_PARENT,KRILLIN_CHILD=A(0x2C39B8),A(0x2C39D0)
NATIVE=elf_reader(elf_path(ROOT))[2]
HOOKS=((A(0x14BAFC),SPAWN,'jump'),(A(0x14C970),UPDATE,'entry'),
       (A(0x14CE30),CLEANUP,'entry'),(A(0x131078),HOMING,'call'),(A(0x14C4E8),INITIAL,'call'),
       (A(0x15DFD8),UPDATE,'entry'),(A(0x15E588),CLEANUP,'entry'),
       (A(0x15E150),INITIAL,'call'),(A(0x15E1B0),INITIAL,'call'),(A(0x15D6EC),HOMING,'call'))
SAVED=tuple(range(2,28))+(30,31)


def save(a):
    a.addiu(29,29,-0x100)
    for i,r in enumerate(SAVED):a.i(63,r,29,8*i)


def restore(a,skip=()):
    for i,r in enumerate(SAVED):
        if r not in skip:a.i(55,r,29,8*i)
    a.addiu(29,29,0x100)


def pointer(a,reg,size,fail):
    a.i(12,8,reg,3);a.branch(5,8,0,fail)
    a.li(8,0x100000);a.r(0x2B,9,reg,8);a.branch(5,9,0,fail)
    a.li(8,0x08000000-size);a.r(0x2B,9,8,reg);a.branch(5,9,0,fail)


def gate(a,fail):
    core.gate(a,fail)
    a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,fail)
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,fail)
    a.lw(9,8,8);a.branch(5,9,10,fail)
    a.li(8,team_intro.BATTLE);a.lw(8,8);a.li(9,CONTROL);a.lw(9,9,12);a.branch(5,8,9,fail)
    a.branch(4,8,0,fail);a.lw(8,8);a.addiu(9,0,3);a.branch(5,8,9,fail)
    a.li(8,result.RESULT);a.lw(8,8);a.branch(5,8,0,fail)


def physical():
    """Pointer -> stable roster index, even inside a temporary native AI alias."""
    a=Assembler(PHYSICAL);a.li(8,CONTROL);a.lw(10,8,8);a.move(2,0)
    policy.emit_actor_count(a,10,'no',scratch=9)
    a.li(11,core.POINTERS)
    a.label('scan');a.lw(8,11);a.branch(4,8,4,'done')
    a.addiu(11,11,4);a.addiu(2,2,1);a.branch(5,2,10,'scan')
    a.label('no');a.addiu(2,0,-1)
    a.label('done');a.jr();return a.finish()


def qualify():
    """Exact native model/slot/row/pool -> source actor; no phase dependency."""
    a=Assembler(QUALIFY);save(a);gate(a,'no');a.move(16,4);a.move(17,6);a.move(18,10)
    pointer(a,16,24,'no');pointer(a,17,80,'no')
    a.lw(19,17);a.i(11,8,19,12);a.branch(4,8,0,'no')
    a.li(8,core.MODELS);a.r(0,9,0,19,2);a.r(0x2D,8,8,9);a.lw(20,8)
    pointer(a,20,0x1670,'no');a.lw(8,20,16);a.branch(5,8,19,'no')
    a.lw(8,20,12);a.addiu(9,0,25);a.branch(4,8,9,'krillin')
    a.addiu(9,0,114);a.branch(5,8,9,'no')
    # Expected slot, callback, classifier, resource, family and option bit.
    for r,v in ((24,2),(25,CHILD_CALLBACKS),(26,0x04000109),(22,43),(23,1),(21,1)):a.li(r,v)
    a.jump('move')
    a.label('krillin')
    for r,v in ((24,3),(25,KRILLIN_CHILD),(26,0x04000009),(22,56),(23,4),(21,2)):a.li(r,v)
    a.label('move');a.branch(5,5,25,'no')
    a.li(8,CONTROL);a.lw(8,8,16);a.r(0x24,8,8,21);a.branch(4,8,0,'no')
    a.lw(8,17,4);a.branch(5,8,24,'no')
    a.lw(21,20,2348);pointer(a,21,0x154,'no');a.lw(8,21);a.branch(5,8,26,'no')
    a.lw(21,17,28);pointer(a,21,0xAC,'no')
    a.r(0,8,0,24,2);a.r(0x21,8,20,8);a.lw(8,8,156);a.branch(5,8,21,'no')
    a.lw(8,21);a.branch(5,8,22,'no')
    a.lw(21,17,36);pointer(a,21,140,'no');a.i(36,8,21,13);a.branch(5,8,23,'no')
    a.lw(21,16);pointer(a,21,64,'no');a.lw(8,21,40);a.addiu(9,25,-24);a.branch(5,8,9,'no')
    a.lw(8,21,36);a.branch(5,8,16,'no');a.lw(8,17,40);a.branch(5,8,21,'no')
    a.lw(22,28,-22648);pointer(a,22,12,'no');a.lw(22,22,4);pointer(a,22,1344*12,'no')
    a.r(0,8,0,19,2);a.r(0x21,8,8,19);a.r(0,8,0,8,2);a.r(0x21,8,8,19);a.r(0,8,0,8,6)
    a.r(0x21,22,22,8)
    # row = modelbase + slot*80; descriptor = modelbase +440+slot*140.
    a.r(0,8,0,24,2);a.r(0x21,8,8,24);a.r(0,8,0,8,4);a.r(0x21,8,8,22);a.branch(5,8,17,'no')
    a.r(0,8,0,24,5);a.r(0,9,0,24,1);a.r(0x21,8,8,9);a.r(0x21,8,8,24);a.r(0,8,0,8,2);a.r(0x21,8,8,22);a.addiu(8,8,440)
    a.lw(9,17,36);a.branch(5,8,9,'no')
    a.move(22,0)
    a.label('scan');a.li(8,core.POINTERS);a.r(0,9,0,22,2);a.r(0x21,8,8,9);a.lw(23,8)
    pointer(a,23,0x1600,'next');a.lw(8,23,12);a.branch(4,8,19,'found')
    a.label('next');a.addiu(22,22,1);a.branch(5,22,18,'scan');a.jump('no')
    a.label('found');a.move(2,23);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');restore(a,(2,));a.jr();return a.finish()


def ensure():
    """pool/row/source -> pool receipt. Extend only an intact empty native pool."""
    a=Assembler(ENSURE);save(a);a.move(16,4);a.move(17,5);a.move(18,6)
    a.move(4,18);a.call(PHYSICAL);a.addiu(8,0,-1);a.branch(4,2,8,'no');a.r(0,8,0,2,5);a.li(19,RECORDS);a.r(0x21,19,19,8)
    a.lw(8,19);a.branch(4,8,0,'new');a.branch(5,8,16,'no')
    a.lw(8,19,16);a.branch(5,8,17,'no');a.lw(8,19,8);a.branch(5,8,18,'no')
    a.move(2,19);a.jump('done')
    a.label('new');a.lw(8,16,4);a.lw(9,16,8);a.r(0x25,8,8,9);a.branch(5,8,0,'no')
    a.lw(20,16,16);pointer(a,20,128,'no');a.lw(8,16,12);a.branch(5,8,20,'no')
    a.lw(8,20,52);a.addiu(9,20,64);a.branch(5,8,9,'no');a.lw(8,20,116);a.branch(5,8,0,'no')
    for off in (32,96):a.lw(8,20,off);a.branch(5,8,16,'no')
    a.lw(21,20,56);pointer(a,21,2*0x13D0,'no')
    a.lw(8,16);a.lw(8,8,40);a.li(9,KRILLIN_PARENT);a.branch(4,8,9,'small_body')
    a.addiu(9,21,0x13D0);a.jump('body_size');a.label('small_body');a.addiu(9,21,0xEC0)
    a.label('body_size');a.lw(8,20,120);a.branch(5,8,9,'no')
    a.lw(8,16,20);a.branch(5,8,21,'no')
    a.li(8,CONTROL);a.lw(22,8,8);a.r(0,22,0,22,1)
    a.r(0,4,0,22,13);a.addiu(5,0,32);a.move(6,0);a.addiu(7,0,2)
    a.call(A(0x2554D8));a.branch(4,2,0,'no');a.move(23,2)
    a.move(4,23);a.move(5,0);a.r(0,6,0,22,13);a.call(A(0x2A9ACC))
    a.move(24,0)
    a.label('slot');a.r(0,8,0,24,13);a.r(0x21,25,23,8)
    a.i(11,8,24,2);a.branch(4,8,0,'added')
    a.r(0,8,0,24,6);a.r(0x21,26,20,8);a.jump('record')
    a.label('added');a.addiu(26,25,NODE);a.i(41,24,26,2);a.sw(16,26,32)
    a.addiu(8,25,BODY);a.sw(8,26,56)
    a.addiu(8,24,1);a.branch(4,8,22,'record');a.addiu(8,26,STRIDE);a.sw(8,26,52)
    a.label('record');a.sw(26,25);a.sw(18,25,4);a.sw(17,25,12)
    a.addiu(24,24,1);a.branch(5,24,22,'slot')
    # Publish only after every new node has a native body and pool identity.
    a.sw(16,19);a.lw(8,16);a.sw(8,19,4);a.sw(18,19,8);a.sw(20,19,12)
    a.sw(17,19,16);a.sw(23,19,20);a.sw(22,19,24)
    a.addiu(8,0,2);a.branch(4,22,8,'published');a.addiu(8,23,2*STRIDE+NODE);a.sw(8,20,116)
    a.label('published');a.move(2,19);a.jump('done')
    a.label('no');a.move(2,0)
    a.label('done');restore(a,(2,));a.jr();return a.finish()


def find_node():
    """node -> private slot, or0; usable during teardown without world gates."""
    a=Assembler(FIND_NODE);save(a);a.move(16,4);pointer(a,16,64,'no')
    a.lw(17,16,32);a.li(18,RECORDS);a.addiu(19,0,12)
    a.label('pool');a.lw(8,18);a.branch(4,8,17,'slots')
    a.addiu(18,18,32);a.addiu(19,19,-1);a.branch(5,19,0,'pool');a.jump('no')
    a.label('slots');a.branch(4,17,0,'no');a.lw(20,18,20);a.lw(21,18,24)
    a.i(11,8,21,25);a.branch(4,8,0,'no');a.branch(4,21,0,'no');pointer(a,20,24*STRIDE,'no')
    a.label('slot');a.lw(8,20);a.branch(4,8,16,'found')
    a.addiu(20,20,STRIDE);a.addiu(21,21,-1);a.branch(5,21,0,'slot');a.jump('no')
    a.label('found');a.move(2,20);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');restore(a,(2,));a.jr();return a.finish()


def context_save(a):
    a.li(8,CONTEXT)
    for off in (0,4,8):a.lw(9,8,off);a.sw(9,29,0xE0+off)


def context_restore(a):
    a.li(8,CONTEXT)
    for off in (0,4,8):a.lw(9,29,0xE0+off);a.sw(9,8,off)


def context_set(a,source,target,node):
    a.li(8,CONTEXT);a.sw(source,8);a.sw(target,8,4);a.sw(node,8,8)


def spawn():
    a=Assembler(SPAWN);save(a);a.move(16,4);a.move(17,5);a.move(18,6)
    a.li(8,CONTROL);a.lw(8,8,16);a.branch(4,8,0,'native')
    a.call(QUALIFY);a.branch(4,2,0,'native');a.move(19,2)
    a.move(4,16);a.move(5,18);a.move(6,19);a.call(ENSURE);a.branch(4,2,0,'native');a.move(20,2)
    a.li(8,CONTROL);a.lw(21,8,8);a.move(22,0);a.move(23,0);context_save(a)
    a.label('enemy');a.li(8,core.POINTERS);a.r(0,9,0,22,2);a.r(0x21,8,8,9);a.lw(24,8)
    a.move(4,19);a.move(5,24);a.call(ENEMY);a.branch(4,2,0,'next')
    a.move(4,16);a.move(5,24);a.call(ACTIVE_FOR_TARGET);a.i(11,8,2,2);a.branch(4,8,0,'next')
    a.lw(25,16,12);a.branch(4,25,0,'finish')
    a.move(4,25);a.call(FIND_NODE);a.branch(4,2,0,'finish');a.move(26,2)
    a.sw(24,26,8)
    # Native per-child bookkeeping must not alias a sibling's cached aim.
    a.move(8,18);a.addiu(9,26,ROW);a.addiu(10,18,80)
    a.label('row_copy');a.lw(11,8);a.sw(11,9);a.addiu(8,8,4);a.addiu(9,9,4);a.branch(5,8,10,'row_copy')
    a.lw(8,18,36);a.addiu(9,26,DESC);a.addiu(10,8,140)
    a.label('desc_copy');a.lw(11,8);a.sw(11,9);a.addiu(8,8,4);a.addiu(9,9,4);a.branch(5,8,10,'desc_copy')
    a.addiu(8,26,DESC);a.sw(8,26,ROW+36)
    context_set(a,19,24,25)
    a.move(4,16);a.move(5,17);a.addiu(6,26,ROW);a.call(A(0x1AD7B8))
    a.branch(4,2,0,'finish');a.branch(5,23,0,'count');a.move(23,2)
    a.label('count');a.li(8,CONTROL);a.lw(9,8,24);a.addiu(9,9,1);a.sw(9,8,24)
    a.label('next');a.addiu(22,22,1);a.branch(5,22,21,'enemy')
    a.label('finish');context_restore(a);a.move(2,23);restore(a,(2,));a.jr()
    a.label('native');restore(a);a.jump(A(0x1AD7B8))
    return a.finish()


def update():
    a=Assembler(UPDATE);save(a);a.move(16,4);a.call(FIND_NODE);a.branch(4,2,0,'native');a.move(17,2)
    a.lw(18,16,56);pointer(a,18,0x13D0,'done')
    a.lw(8,16,40);a.li(9,KRILLIN_CHILD);a.branch(4,8,9,'small_row')
    a.li(9,CHILD_CALLBACKS);a.branch(5,8,9,'native');a.lw(8,18,144);a.jump('row_check')
    a.label('small_row');a.lw(8,18,1316)
    a.label('row_check');a.addiu(9,17,ROW);a.branch(5,8,9,'native')
    gate(a,'done');a.lw(18,17,4);a.lw(19,17,8)
    a.move(4,18);a.move(5,19);a.call(ENEMY);a.branch(4,2,0,'dead')
    context_save(a);context_set(a,18,19,16);a.move(4,16)
    a.lw(8,16,40);a.li(9,KRILLIN_CHILD);a.branch(4,8,9,'small_update')
    a.call(UPDATE_OLD);a.jump('updated');a.label('small_update');a.call(KRILLIN_UPDATE_OLD)
    a.label('updated');context_restore(a);a.jump('done')
    a.label('dead');a.move(4,16);a.call(A(0x1ADA58))
    a.label('done');restore(a);a.jr()
    a.label('native');restore(a)
    a.lw(8,4,40);a.li(9,KRILLIN_CHILD);a.branch(4,8,9,'small_native')
    a.jump(UPDATE_OLD);a.label('small_native');a.jump(KRILLIN_UPDATE_OLD)
    return a.finish()


def cleanup():
    a=Assembler(CLEANUP);save(a);a.move(16,4);pointer(a,16,64,'native');a.lw(17,16,36)
    a.branch(4,17,0,'native');a.li(18,RECORDS);a.addiu(19,0,12)
    a.label('scan');a.lw(8,18);a.branch(4,8,17,'found')
    a.addiu(18,18,32);a.addiu(19,19,-1);a.branch(5,19,0,'scan');a.jump('native')
    a.label('found');a.lw(8,18,4);a.branch(5,8,16,'native')
    # Original native child destructors run while their private rows/assets
    # still exist. The engine's subsequent pool free sees only native storage.
    a.move(4,17);a.call(A(0x1AD9F8))
    a.lw(20,18,12);a.addiu(8,20,64);a.sw(8,20,52);a.sw(0,20,116);a.sw(20,17,12)
    a.lw(4,18,20);a.call(A(0x255508))
    for off in range(0,32,4):a.sw(0,18,off)
    a.li(8,CONTROL);a.lw(9,8,28);a.addiu(9,9,1);a.sw(9,8,28)
    a.label('native');restore(a)
    a.lw(8,4,40);a.li(9,KRILLIN_PARENT);a.branch(4,8,9,'small_native')
    a.jump(CLEANUP_OLD);a.label('small_native');a.jump(KRILLIN_CLEANUP_OLD)
    return a.finish()


def target():
    a=Assembler(TARGET);save(a);a.move(16,4);a.li(8,CONTEXT);a.lw(9,8);a.branch(5,16,9,'no')
    a.lw(17,8,4);a.move(5,17);a.call(ENEMY);a.branch(4,2,0,'no')
    a.lw(2,17,12);a.addiu(3,0,1);a.jump('done')
    a.label('no');a.move(2,0);a.move(3,0)
    a.label('done');restore(a,(2,3));a.jr();return a.finish()


def initial():
    """Aim an owned stream at its target, including enemies behind the caster.

    Native130DD8 clamps a rear target to the caster's forward direction. Keep
    the native target bone/vector operations but omit that single-target cone.
    """
    a=Assembler(INITIAL);save(a);a.move(16,5);a.move(17,6);a.move(18,7)
    a.li(8,CONTEXT);a.lw(4,8);a.branch(4,4,0,'native')
    a.lw(8,4,12);a.branch(5,8,18,'native');a.call(TARGET);a.branch(4,3,0,'native')
    a.move(4,2);a.addiu(5,0,17);a.addiu(6,29,0xE0);a.call(A(0x2058E0))
    a.move(4,16);a.addiu(5,29,0xE0);a.move(6,17);a.call(A(0x121ED8))
    a.move(4,16);a.move(5,16);a.call(A(0x121E50));a.addiu(2,0,1)
    restore(a,(2,));a.jr()
    a.label('native');restore(a);a.jump(A(0x130DD8));return a.finish()


def homing():
    a=Assembler(HOMING);save(a);a.move(16,4);a.li(8,CONTEXT);a.lw(4,8)
    a.branch(4,4,0,'native');a.lw(8,4,12);a.branch(5,8,16,'native')
    a.call(TARGET);a.branch(4,3,0,'native');restore(a,(2,));a.jr()
    a.label('native');restore(a);a.jump(A(0x205260));return a.finish()


def enemy():
    """Stable pointer ownership, participation and team guards; alias-safe."""
    a=Assembler(ENEMY);save(a);a.move(16,4);a.move(17,5);gate(a,'no');a.move(22,10)
    a.li(8,contacts.CONTROL);a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'no')
    a.lw(9,8,8);a.branch(5,9,22,'no')
    for actor,pid in ((16,20),(17,21)):
        pointer(a,actor,0x1600,'no');a.move(4,actor);a.call(PHYSICAL);a.move(pid,2)
        a.addiu(8,0,-1);a.branch(4,pid,8,'no')
        a.li(8,contacts.CONTROL+0x100);a.r(0,9,0,pid,2);a.r(0x21,8,8,9);a.lw(8,8);a.branch(5,8,actor,'no')
        contacts.geometry.alive_argument(a,actor,'no')
        a.li(8,contacts.participation.CONTROL);a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'no')
        a.lw(9,8,8);a.branch(5,9,22,'no')
        a.lw(9,8,12);a.lw(11,8,16);a.r(0x27,11,11,0);a.r(0x24,9,9,11)
        a.addiu(11,0,1);a.r(4,11,pid,11);a.r(0x24,9,9,11);a.branch(4,9,0,'no')
        a.lw(18,actor,12);a.i(11,8,18,12);a.branch(4,8,0,'no')
        a.li(8,core.MODELS);a.r(0,9,0,18,2);a.r(0x21,8,8,9);a.lw(19,8)
        pointer(a,19,0x1670,'no');a.lw(8,19,16);a.branch(5,8,18,'no')
    policy.emit_enemy(a,20,21,'no','fanout_enemy')
    a.addiu(2,0,1);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');restore(a,(2,));a.jr();return a.finish()


def active_for_target():
    """Each enemy gets the same native two-child overlap allowance."""
    a=Assembler(ACTIVE_FOR_TARGET);save(a);a.lw(16,4,4);a.move(17,5);a.move(18,0);a.addiu(19,0,24)
    a.label('scan');a.branch(4,16,0,'done');pointer(a,16,64,'full')
    a.move(4,16);a.call(FIND_NODE);a.branch(4,2,0,'full');a.lw(8,2,8);a.branch(5,8,17,'next')
    a.addiu(18,18,1);a.addiu(8,0,2);a.branch(4,18,8,'done')
    a.label('next');a.lw(16,16,48);a.addiu(19,19,-1);a.branch(5,19,0,'scan')
    a.label('full');a.addiu(18,0,2)
    a.label('done');a.move(2,18);restore(a,(2,));a.jr();return a.finish()


def pieces():
    out=[(SPAWN,spawn()),(QUALIFY,qualify()),(ENSURE,ensure()),(FIND_NODE,find_node()),
         (UPDATE,update()),(CLEANUP,cleanup()),(TARGET,target()),(INITIAL,initial()),(HOMING,homing()),(ENEMY,enemy()),
         (ACTIVE_FOR_TARGET,active_for_target()),(PHYSICAL,physical())]
    for entry,at in ((A(0x14C970),UPDATE_OLD),(A(0x14CE30),CLEANUP_OLD),(A(0x15DFD8),KRILLIN_UPDATE_OLD),(A(0x15E588),KRILLIN_CLEANUP_OLD)):
        out.append((at,NATIVE(entry,8)+struct.pack('<2I',(2<<26)|((entry+8)>>2),0)))
    for entry,at,kind in HOOKS:
        if kind=='entry':data=struct.pack('<2I',(2<<26)|(at>>2),0)
        else:data=struct.pack('<I',((3 if kind=='call' else 2)<<26)|(at>>2))
        out.append((entry,data))
    spans=sorted((a,a+len(b)) for a,b in out)
    assert all(end<=at for (_,end),(at,_) in zip(spans,spans[1:]))
    return out


def legacy_pieces(filename='buu_fanout_legacy.json'):
    import json
    from pathlib import Path
    data=json.loads(Path(__file__).with_name(filename).read_text())
    return [(int(p),bytes.fromhex(v))for p,v in data[str(policy.emitted_capacity())].items()]


def installed_legacy(ram):
    if TRANSLATED:raise ValueError('Multi-target projectile code changed')  # USA-only legacy images
    for name in ('buu_fanout_legacy.json','buu_fanout_family1_legacy.json'):
        parts=legacy_pieces(name)
        if all(ram[at:at+len(data)]==data for at,data in parts):return parts
    raise ValueError('Multi-target projectile code changed')


@policy.matching_install
def validate_memory(ram):
    u=lambda at:struct.unpack_from('<I',ram,at)[0]
    if struct.unpack_from('<4I',ram,CONTROL)!=(MAGIC,u(core.ACTORS),u(core.MODE+4),u(team_intro.BATTLE)):
        raise ValueError('Buu projectile extension belongs to another match')
    if u(CONTROL+16) not in (0,1,2,3):raise ValueError('Invalid Buu option')
    contacts.validate(ram,u(core.ACTORS),u(core.MODE+4))
    if not all(ram[at:at+len(data)]==data for at,data in pieces()):
        for at,data in installed_legacy(ram):
            if at<CODE and len(data)==4 and ram[at+4:at+8]!=NATIVE(at+4,4):
                raise ValueError('Buu legacy delay slot changed')
        if any(ram[RECORDS:RECORDS+12*32]):raise ValueError('Cannot upgrade active Buu streams')
        return False
    for entry,_,kind in HOOKS:
        if kind!='entry' and ram[entry+4:entry+8]!=NATIVE(entry+4,4):raise ValueError('Buu native delay slot changed')
    return True


@policy.matching_install
def build_memory(ram,config=None,source='<offline-memory>',*,enabled=False,krillin_enabled=False):
    if type(enabled) is not bool or type(krillin_enabled) is not bool:raise ValueError('Projectile options must be Boolean')
    flags=int(enabled)|(int(krillin_enabled)<<1)
    if len(ram)!=0x8000000:raise ValueError('Requires128MiB captured EE RAM')
    u=lambda at:struct.unpack_from('<I',ram,at)[0]
    if u(CONTROL)==MAGIC:
        current=validate_memory(ram)
        parts=[]
        if not current:
            legacy=installed_legacy(ram)
            for at,data in legacy:
                if at<CODE:parts.append((at,NATIVE(at,len(data))))
            for at,_,kind in HOOKS:
                if at not in dict(legacy) and ram[at:at+8]!=NATIVE(at,8):
                    raise ValueError(f'Genocide Blast native hook changed:{at:08X}')
            parts+=pieces()+[(CONTROL,struct.pack('<5I',MAGIC,u(core.ACTORS),u(core.MODE+4),u(team_intro.BATTLE),flags))]
        elif u(CONTROL+16)!=flags:parts.append((CONTROL+16,struct.pack('<I',flags)))
    elif not flags:parts=[]
    else:
        if any(ram[CODE:END]):raise ValueError('Buu projectile reservation occupied')
        if (u(core.MODE)!=1 or u(core.MODE+4) not in policy.ACTOR_COUNTS or u(core.MODE+8)!=u(core.ACTORS)
            or u(core.MODE+12)!=u(core.MODE+4)):
            raise ValueError('Captured active team required')
        contacts.validate(ram,u(core.ACTORS),u(core.MODE+4))
        for entry,_,kind in HOOKS:
            if ram[entry:entry+8]!=NATIVE(entry,8):raise ValueError(f'Buu native hook changed:{entry:08X}')
        control=bytearray(0x100);struct.pack_into('<5I',control,0,MAGIC,u(core.ACTORS),u(core.MODE+4),u(team_intro.BATTLE),flags)
        parts=pieces()+[(CONTROL,bytes(control))]
    parts=list(dict(parts).items())
    return dict(serial=SERIAL,crc=CRC,source=str(source),enabled=enabled,krillin_enabled=krillin_enabled,control=CONTROL,
                status='NATIVE GENOCIDE BLAST / SCATTERING BULLET STREAMS PER LIVING ENEMY',
                blocks=[dict(address=at,expected_hex=ram[at:at+len(data)].hex(),data_hex=data.hex()) for at,data in parts])
