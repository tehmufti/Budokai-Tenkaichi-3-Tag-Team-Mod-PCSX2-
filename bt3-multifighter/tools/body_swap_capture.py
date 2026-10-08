"""Capture one actual Body Change pair and defer its stock random reload.

The authored paired animation still runs to completion on the original bodies.
The claimed pair's five local reload calls are intercepted. A distinct valid
overlapping pair finishes without a reload and cannot overwrite the first claim.
No worker or replacement resources are installed by this isolated builder.
"""
from native_map import A, CRC, SERIAL
import struct
from prototype import Assembler
import body_swap as body
import fusion_partner_lifecycle as saved
import extra_reload_preload as preload

core=body.core
CONTROL,ROWS=body.CONTROL,body.ROWS
FULL_ROWS=(ROWS+0x200,ROWS+0x300)
HANDOFF_ROWS=body.HANDOFF_ROWS
CAPTURE,QUEUE,READY,ACK,FINISH=(body.CODE+i*0x2000 for i in range(5))
ADMISSION,ADMISSION_HOOK=0x0702A000,A(0x203E80)
END=0x07030000
HOOKS=((body.PICK_CALL,CAPTURE,body.PICKER),(A(0x1F9AF8),QUEUE,A(0x1D61F8)),
       (A(0x1F9B20),READY,A(0x1D6360)),(A(0x1F9B40),ACK,A(0x1D63D8)),(A(0x1F9B78),FINISH,A(0x1D6408)))


def identity(a,fail):
    core.gate(a,fail);a.li(16,CONTROL);a.lw(8,16);a.li(9,body.MAGIC);a.branch(5,8,9,fail)
    a.lw(8,16,4);a.lw(9,28,-22364);a.branch(5,8,9,fail)
    a.lw(8,16,8);a.branch(5,8,10,fail)
    a.li(8,core.PAIR+4);a.lw(8,8);a.branch(5,8,0,fail)


def capture_code():
    a=Assembler(CAPTURE);saved.save(a);identity(a,'native')
    a.lw(8,16,20);a.addiu(9,0,1);a.branch(5,8,9,'native')
    a.lw(8,16,16);a.branch(5,8,0,'existing')
    capacity(a,'denied')
    saved.pointer(a,4,0x1600,'native')
    a.lw(17,4,0xE94);a.lw(18,4,0xE98)
    for r in (17,18):a.r(0x2B,8,r,10);a.branch(4,8,0,'native')
    body.policy.emit_enemy(a,17,18,'native','capture_enemy')
    # Reverse-swap policy: only an original Ginyu owner recorded when capture
    # was enabled may claim an exchange. A body that received character 86
    # through an exchange falls through to the native path (and is refused
    # there by the admission wrapper), so no unplanned reverse swap occurs.
    a.lw(8,16,body.OWNERS-CONTROL);a.addiu(9,0,1);a.r(4,9,17,9);a.r(0x24,9,8,9);a.branch(4,9,0,'native')
    a.r(0,8,0,17,2);a.li(9,core.POINTERS);a.r(0x21,8,8,9);a.lw(8,8);a.branch(5,4,8,'native')
    # Require active participation for both actual contact identities.
    a.li(8,body.participation.CONTROL);a.lw(9,8);a.addiu(11,0,5);a.branch(5,9,11,'native')
    a.lw(9,8,4);a.lw(11,16,4);a.branch(5,9,11,'native')
    a.lw(9,8,8);a.lw(11,16,8);a.branch(5,9,11,'native')
    a.lw(12,8,12);a.lw(13,8,16)
    for r in (17,18):
        a.addiu(8,0,1);a.r(4,8,r,8);a.r(0x24,9,8,12);a.branch(4,9,0,'native')
        a.r(0x24,9,8,13);a.branch(5,9,0,'native')
    a.move(19,17);a.addiu(20,0,2);a.li(21,ROWS);a.li(15,FULL_ROWS[0])  # t7, never k0/k1: interrupts overwrite those (LS-2)
    a.label('body');a.r(0,8,0,19,2);a.li(9,core.POINTERS);a.r(0x21,8,8,9);a.lw(22,8)
    saved.pointer(a,22,0x1600,'native');a.lw(8,22);a.branch(5,8,19,'native')
    a.lw(8,22,0xE90);a.addiu(9,0,body.SCRIPT);a.branch(5,8,9,'native')
    for off,r in ((0xE94,17),(0xE98,18)):a.lw(8,22,off);a.branch(5,8,r,'native')
    a.lw(8,22,2376)
    for action in body.PAIRED:
        a.addiu(9,0,action);a.branch(4,8,9,'paired')
    a.jump('native');a.label('paired')
    a.lw(23,22,12);a.i(11,8,23,12);a.branch(4,8,0,'native')
    a.r(0,8,0,23,2);a.li(9,core.MODELS);a.r(0x21,8,8,9);a.lw(24,8)
    saved.pointer(a,24,0x1670,'native');a.lw(8,24,4);a.addiu(9,0,1);a.branch(5,8,9,'native')
    a.lw(8,24,16);a.branch(5,8,23,'native')
    a.lw(8,22,0x994);a.lw(9,22,0x998);a.i(11,11,9,6);a.branch(4,11,0,'native')
    a.r(0x2B,11,8,9);a.branch(4,11,0,'native');saved.row_address(a,25,22,8,9)
    a.lw(8,25);a.lw(9,24,12);a.branch(5,8,9,'native')
    a.i(11,9,8,161);a.branch(4,9,0,'native')
    a.branch(5,19,17,'not_source');a.addiu(9,0,body.GINYU);a.branch(5,8,9,'native');a.label('not_source')
    a.lw(8,25,4);a.i(11,9,8,4);a.branch(4,9,0,'native')
    a.lw(8,25,64);a.branch(6,8,0,'native');a.lw(9,25,68);a.r(0x2B,11,9,8);a.branch(5,11,0,'native')
    a.li(11,1000001);a.r(0x2B,11,9,11);a.branch(4,11,0,'native')
    a.lw(8,24,20);saved.pointer(a,8,56,'native',temp=9,test=11)
    a.lw(9,8,48);a.i(12,9,9,1);a.branch(4,9,0,'native')
    # These records are unpublished until both complete and status becomes1.
    for off,r in ((0,19),(4,22),(8,23),(12,24),(16,25)):a.sw(r,21,off)
    for dst,base,off in ((20,24,20),(24,24,12),(28,25,4),(32,25,64),(36,25,68),
                         (40,25,76),(44,25,84),(48,22,2376),(52,22,4),(56,22,0x1278),(60,25,0x70)):
        a.lw(8,base,off);a.sw(8,21,dst)
    for off in range(0,164,4):a.lw(8,25,off);a.sw(8,15,off)
    a.addiu(20,20,-1);a.move(19,18);a.addiu(21,21,64);a.addiu(15,15,0x100)
    a.branch(5,20,0,'body')
    for off in (12,24):a.lw(8,16,off);a.addiu(8,8,1);a.sw(8,16,off)
    a.r(0,8,0,17,4);a.li(9,body.DENIED);a.r(0x21,8,8,9)
    for off in range(0,16,4):a.sw(0,8,off)
    a.addiu(8,0,1);a.sw(8,16,16);a.jump('owned')
    a.label('existing')
    # Repeated native picker entry for the same published source must not
    # unexpectedly load a random body while the transaction is pending.
    a.li(8,ROWS+4);a.lw(8,8);a.branch(5,8,4,'denied')
    emit_claimed_pair(a,4,'denied','repeat');a.jump('owned')
    a.label('denied');emit_authored_pair(a,4,'native','denied_pair')
    # The picker is only the source actor's call. Local wrappers also execute
    # for the recipient, so their shared pair validator accepts either member.
    a.branch(5,4,22,'native')
    a.r(0,21,0,17,4);a.li(8,body.DENIED);a.r(0x21,21,21,8)
    for off,r in ((0,22),(4,23),(8,17),(12,18)):a.sw(r,21,off)
    a.lw(8,16,40);a.addiu(8,8,1);a.sw(8,16,40)
    a.label('owned');saved.restore(a);a.move(2,0);a.jr()
    a.label('native');saved.restore(a);a.jump(body.PICKER)
    data=a.finish();assert len(data)<0x2000;return data


def emit_authored_pair(a,actor,fail,tag):
    """Authenticate an original Ginyu's exact native reciprocal Body Change pair.

    Returns physical source/target in s1/s2, actor pointers in s6/s7. This
    never consults lock-on targets and never rewrites the primary claim.
    """
    saved.pointer(a,actor,0x1600,fail);a.lw(17,actor,0xE94);a.lw(18,actor,0xE98)
    a.lw(10,16,8)
    for r in (17,18):a.r(0x2B,8,r,10);a.branch(4,8,0,fail)
    body.policy.emit_enemy(a,17,18,fail,tag+'_enemy')
    a.lw(8,16,body.OWNERS-CONTROL);a.addiu(9,0,1);a.r(4,9,17,9);a.r(0x24,8,8,9);a.branch(4,8,0,fail)
    for r,physical in ((22,17),(23,18)):
        a.r(0,8,0,physical,2);a.li(9,core.POINTERS);a.r(0x21,8,8,9);a.lw(r,8)
        saved.pointer(a,r,0x1600,fail);a.lw(8,r);a.branch(5,8,physical,fail)
        a.lw(8,r,0xE90);a.addiu(9,0,body.SCRIPT);a.branch(5,8,9,fail)
        for off,value in ((0xE94,17),(0xE98,18)):a.lw(8,r,off);a.branch(5,8,value,fail)
    a.branch(4,actor,22,tag+'_member');a.branch(5,actor,23,fail);a.label(tag+'_member')
    a.lw(8,22,0x994);a.lw(9,22,0x998);a.i(11,10,9,6);a.branch(4,10,0,fail)
    a.r(0x2B,10,8,9);a.branch(4,10,0,fail);saved.row_address(a,25,22,8,9)
    a.lw(8,25);a.addiu(9,0,body.GINYU);a.branch(5,8,9,fail)


def emit_denied_pair(a,actor,fail,tag):
    emit_authored_pair(a,actor,fail,tag)
    a.r(0,21,0,17,4);a.li(8,body.DENIED);a.r(0x21,21,21,8)
    for off,r in ((0,22),(4,23),(8,17),(12,18)):
        a.lw(8,21,off);a.branch(5,8,r,fail)


def emit_claimed_pair(a,actor,fail,tag):
    """Validate this original-body actor belongs to the published native pair."""
    a.lw(8,16,16);a.i(11,9,8,1);a.branch(5,9,0,fail)
    # Status100 may be held for recovery and still owns its intercepted calls.
    a.i(11,9,8,101);a.branch(4,9,0,fail)
    a.li(21,ROWS);a.lw(17,21);a.lw(18,21,64)
    a.lw(10,16,8)
    for r in (17,18):a.r(0x2B,8,r,10);a.branch(4,8,0,fail)
    a.lw(8,21,4);a.branch(4,actor,8,tag+'_member')
    a.lw(8,21,68);a.branch(5,actor,8,fail);a.label(tag+'_member')
    for off,r in ((0xE94,17),(0xE98,18)):
        a.lw(8,actor,off);a.branch(5,8,r,fail)
    a.lw(8,actor,0xE90);a.addiu(9,0,body.SCRIPT);a.branch(5,8,9,fail)
    for off,r in ((0,17),(64,18)):
        a.lw(8,21,off+4);a.r(0,9,0,r,2);a.li(10,core.POINTERS);a.r(0x21,9,9,10);a.lw(9,9)
        a.branch(5,8,9,fail)
        saved.pointer(a,8,0x1600,fail,temp=9,test=11)
        a.lw(9,8);a.branch(5,9,r,fail)
        a.lw(9,8,0xE90);a.addiu(10,0,body.SCRIPT);a.branch(5,9,10,fail)
        for field,value in ((0xE94,17),(0xE98,18)):
            a.lw(9,8,field);a.branch(5,9,value,fail)


def local_code(entry,native,kind):
    a=Assembler(entry);saved.save(a);identity(a,'native')
    # Native1F97F8 keeps current actor in s1; its reload-call arguments are
    # physical source IDs, not actor pointers. Preserve both ABI meanings.
    a.lw(4,29,saved.OFFSETS[17]);saved.pointer(a,4,0x1600,'native')
    emit_denied_pair(a,4,'claimed',kind+'_denied')
    a.lw(8,29,saved.OFFSETS[4]);a.branch(5,8,17,'native');a.jump('owned')
    a.label('claimed')
    emit_claimed_pair(a,4,'native',kind)
    a.lw(8,29,saved.OFFSETS[4]);a.branch(5,8,17,'native')
    if kind=='finish':
        a.lw(8,16,16);a.addiu(9,0,1);a.branch(5,8,9,'owned')
        a.addiu(8,0,2);a.sw(8,16,16)
    a.label('owned');saved.restore(a);a.addiu(2,0,1 if kind=='ready' else 0);a.jr()
    a.label('native');saved.restore(a);a.jump(native)
    data=a.finish();assert len(data)<0x2000;return data


def pieces():
    return [(CAPTURE,capture_code())]+[(entry,local_code(entry,native,kind))
        for (_,entry,native),kind in zip(HOOKS[1:],('queue','ready','ack','finish'))]+[(ADMISSION,admission_code())]


def capacity(a,fail):
    """Require two empty native resources, model slots and texture groups."""
    a.li(8,preload.REGISTRY_GLOBAL);a.lw(22,8);saved.pointer(a,22,440124,fail)
    a.li(8,preload.REGISTRY_OFFSET);a.r(0x21,23,22,8);a.move(24,0);a.addiu(25,0,12)
    a.label('resources');a.lw(8,23,48);a.i(12,8,8,1);a.branch(5,8,0,'resource_next')
    for off in (0,16,32):a.lw(8,23,off);a.branch(5,8,0,'resource_next')
    a.addiu(24,24,1)
    a.label('resource_next');a.addiu(23,23,56);a.addiu(25,25,-1);a.branch(5,25,0,'resources')
    a.i(11,8,24,2);a.branch(5,8,0,fail)
    a.li(23,core.MODELS);a.move(24,0);a.addiu(25,0,12)
    a.label('models');a.lw(8,23);a.branch(4,8,0,'model_free')
    saved.pointer(a,8,0x1670,fail,temp=9,test=11);a.lw(8,8,4);a.branch(5,8,0,'model_next')
    a.label('model_free');a.addiu(24,24,1)
    a.label('model_next');a.addiu(23,23,4);a.addiu(25,25,-1);a.branch(5,25,0,'models')
    a.i(11,8,24,2);a.branch(5,8,0,fail)
    a.li(8,439156);a.r(0x21,8,22,8);a.lw(8,8);a.move(9,0);a.addiu(11,0,15)
    a.label('textures');a.i(12,12,8,1);a.r(0x21,9,9,12);a.r(2,8,0,8,1)
    a.addiu(11,11,-1);a.branch(5,11,0,'textures');a.i(11,8,9,14);a.branch(4,8,0,fail)


def admission_code():
    """Reject a new captured Ginyu ultimate while one swap is pending, and any
    Ginyu ultimate from a body that is not an original Ginyu owner.

    Slot 4 with a character-86 row is the only affected command. An original
    owner keeps stock admission whenever no claim is pending; a body that
    received Ginyu through an exchange can neither start a true exchange nor
    the stock random reload of its adopted native descriptor.
    """
    a=Assembler(ADMISSION);saved.save(a);identity(a,'native')
    a.lw(8,16,20);a.addiu(9,0,1);a.branch(5,8,9,'native')
    a.addiu(8,0,4);a.branch(5,5,8,'native')
    saved.pointer(a,4,0x1600,'native');a.lw(8,4);a.r(0x2B,9,8,10);a.branch(4,9,0,'native')
    a.r(0,8,0,8,2);a.li(9,core.POINTERS);a.r(0x21,8,8,9);a.lw(8,8);a.branch(5,8,4,'native')
    a.lw(8,4,0x994);a.i(11,9,8,5);a.branch(4,9,0,'native');saved.row_address(a,25,4,8,9)
    a.lw(8,25);a.addiu(9,0,body.GINYU);a.branch(5,8,9,'native')
    a.lw(8,16,16);a.addiu(8,8,-1);a.i(11,9,8,3);a.branch(5,9,0,'refuse')
    a.lw(8,4);a.addiu(9,0,1);a.r(4,9,8,9);a.lw(8,16,body.OWNERS-CONTROL);a.r(0x24,9,8,9);a.branch(4,9,0,'refuse')
    capacity(a,'refuse')
    a.jump('native')
    a.label('refuse');saved.restore(a);a.move(2,0);a.jr()
    a.label('native');saved.restore(a);a.jump(A(0x203CE0))
    return a.finish()


def program():
    """Immutable code and owned call instructions, without runtime data."""
    return pieces()+[(hook,struct.pack('<I',(3<<26)|(entry>>2))) for hook,entry,native in HOOKS]+[
        (ADMISSION_HOOK,struct.pack('<I',(3<<26)|(ADMISSION>>2)))]


def build_memory(ram,source='<offline-memory>',*,enabled=True,stolen_abilities=False):
    w=body.world(ram,preparing=True)
    body.require(type(enabled) is bool,'Enabled must be Boolean')
    body.require(type(stolen_abilities) is bool,'Stolen-body ability option must be Boolean')
    body.require(not any(ram[body.CODE:END]),'Body capture reservation occupied')
    for hook,entry,native in HOOKS:
        body.require(ram[hook:hook+8]==body.NATIVE(hook,8),f'Native Body Change call changed {hook:08X}')
        body.require(struct.unpack_from('<I',ram,hook)[0]==(3<<26)|(native>>2),'Unexpected native call target')
    body.require(ram[ADMISSION_HOOK:ADMISSION_HOOK+8]==body.NATIVE(ADMISSION_HOOK,8),'Native special admission call changed')
    owners=body.ginyu_owners(ram,w)
    parts=program()+[(CONTROL,struct.pack('<12I',body.MAGIC,w['manager'],w['count'],0,0,int(enabled),0,0,0,owners,0,int(stolen_abilities))),
                    (ROWS,bytes(body.ROWS_BYTES))]
    return dict(serial=SERIAL,crc=CRC,source=str(source),control=CONTROL,full_rows=list(FULL_ROWS),
        handoff_rows=list(HANDOFF_ROWS),ginyu_owners=owners,
        limitation='One pair is exchanged at once. New Ginyu ultimates wait while busy; a valid simultaneous already-authored pair finishes without a body/HP change instead of using the stock random body.',
        blocks=[dict(address=p,expected_hex=ram[p:p+len(data)].hex(),data_hex=data.hex()) for p,data in parts])
