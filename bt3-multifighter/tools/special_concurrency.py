"""Allow unrelated specials with camera ownership and bound-pair exclusion.

Installed last, after the reviewed legacy special/transform/reload guards. Only
three special eligibility wrappers change here. ordinary_form_admission also
uses the predicate generator while preserving exclusive native resource
handshakes. Camera arbitration is required before relaxing admission.
"""
from native_map import CRC, SERIAL, elf_path
import struct
from prototype import Assembler, ROOT, elf_reader
import cinematic_admission as old
import fresh_team_combat as core
import extra_throws as throws
import battle_mode_policy as policy
from battle_mode_policy import ACTOR_COUNTS

PREDICATE, CONTROL, END = 0x077F8000, 0x077FFF00, 0x07800000
MAGIC = 0x53434E31
SPECIAL_ENTRIES = (0, 1, 6)


def alive(a, actor, fail):
    a.lw(8,actor,0x994);a.i(11,9,8,5);a.branch(4,9,0,fail)
    a.r(0,9,0,8,2);a.r(0x2D,9,9,8);a.r(0,9,0,9,3)
    a.r(0x2D,9,9,8);a.r(0,9,0,9,2);a.r(0x2D,9,9,actor)
    a.lw(8,9,0x9E4);a.branch(6,8,0,fail)


def predicate_code(*, base=PREDICATE, ordinary_form=False):
    a=Assembler(base)
    core.gate(a,'legacy');a.move(15,10)
    a.li(8,CONTROL);a.lw(9,8);a.li(10,MAGIC);a.branch(5,9,10,'legacy')
    a.lw(9,8,4);a.lw(10,28,-22364);a.branch(5,9,10,'legacy')
    a.lw(9,8,8);a.branch(5,9,15,'legacy')
    a.li(13,core.POINTERS);a.move(12,0)
    a.label('find');a.lw(11,13);a.branch(4,11,4,'owned')
    a.addiu(13,13,4);a.addiu(12,12,1);a.branch(5,12,15,'find');a.jump('legacy')
    a.label('owned')
    # Preserve the native continuation of an already accepted move.
    a.lw(8,4,2376)
    for first,length in (((236,5),) if ordinary_form else ((253,63),(236,8))):
        a.addiu(9,8,-first);a.i(11,9,9,length);a.branch(5,9,0,'allow')
    if ordinary_form:
        # A form belongs to its user, not their lock-on target. An occupied or
        # dead target must not disable the user's transformation.
        a.move(14,12)
        import extra_reload_quiet as reload
        import native_preparation as preparation
        a.li(8,reload.SCENE_FLAGS);a.lw(9,8);a.i(12,9,9,reload.SCENE_RELOAD_MASK)
        a.branch(5,9,0,'form_blocked')
        a.lw(8,28,-22364)
        for offset in (600,612,628):
            a.lw(9,8,offset);a.branch(5,9,0,'form_blocked')
        a.lw(9,8,604);a.lw(10,8,608);a.branch(5,9,10,'form_blocked')
        for address in (reload.LOADER_STATE,reload.LOADER_HANDLE):
            a.li(8,address);a.lw(9,8);a.branch(5,9,0,'form_blocked')
        a.li(8,reload.LOADER_PENDING);a.lw(9,8);a.i(12,9,9,0xFFFF)
        a.branch(5,9,0,'form_blocked')
        a.li(8,reload.TASK_FIFO);a.lw(8,8)
        a.li(9,0x100000);a.r(0x2B,10,8,9);a.branch(5,10,0,'fifo_ready')
        a.li(9,0x08000000-31);a.r(0x2B,10,8,9);a.branch(4,10,0,'fifo_ready')
        a.i(12,9,8,3);a.branch(5,9,0,'fifo_ready')
        a.lw(9,8,12);a.branch(5,9,0,'form_blocked');a.label('fifo_ready')
        a.li(8,preparation.CONTROL+16);a.lw(9,8);a.branch(5,9,0,'form_blocked')
        a.li(8,reload.BG_CONTROL);a.lw(9,8);a.li(10,reload.BG_MAGIC)
        a.branch(5,9,10,'loader_ready');a.lw(9,8,4);a.lw(10,8,8)
        a.branch(5,9,10,'form_blocked');a.label('loader_ready')
    else:
        a.li(8,core.TABLE);a.r(0,9,0,12,2);a.r(0x2D,8,8,9);a.lw(14,8)
        a.r(0x2B,8,14,15);a.branch(4,8,0,'pair_blocked')
        policy.emit_enemy(a,12,14,'pair_blocked','special_target')
    # Beam contact publishes its actual pair before the AA actions commit.
    # Reserve those fighters through the whole pending/running handshake;
    # actor+3732/+3736 describe ordinary paired supers, not a beam struggle.
    import beam_clash as beam
    import special_camera_arbitration as camera
    camera.emit_owned_beam(a,'beam_checked')
    a.li(8,beam.INDICES)
    for off in (0,4):
        a.lw(9,8,off)
        # A free actor may charge/fire while its lock-on target is occupied.
        # Beam contact and the paired-contact guards still veto interference;
        # admission must not disable P2 merely because P1 is its current target.
        a.branch(4,12,9,'pair_blocked')
    a.label('beam_checked')
    # A recorded native throw reserves its actual two participants.
    for r in (12,14):
        a.li(8,throws.ROWS);a.r(0,9,0,r,2);a.r(0x2D,8,8,9);a.lw(8,8)
        a.branch(5,8,0,'pair_blocked')
    a.move(3,0);a.li(13,core.POINTERS)
    a.label('others');a.lw(11,13)
    a.branch(4,11,4,'next');a.branch(4,11,0,'next');alive(a,11,'next')
    # Native form/reload cinematics are separate from effect camera requests.
    for off in old.ACTION_FIELDS:
        a.lw(8,11,off);a.addiu(9,8,-236);a.i(11,9,9,8);a.branch(5,9,0,'form_blocked')
    for off in old.ACTION_FIELDS:
        a.lw(8,11,off)
        for first in (301,313):
            a.addiu(9,8,-first);a.i(11,9,9,3);a.branch(5,9,0,'paired')
    a.jump('next')
    a.label('paired');a.lw(8,11,3732);a.lw(9,11,3736)
    a.r(0x2B,10,8,15);a.branch(4,10,0,'pair_blocked')
    a.r(0x2B,10,9,15);a.branch(4,10,0,'pair_blocked')
    a.branch(4,8,9,'pair_blocked')
    policy.emit_enemy(a,8,9,'pair_blocked','special_pair',t0=10,t1=11)
    # The relationship helper consumes t3; reload the scanned actor pointer.
    a.lw(11,13)
    a.branch(4,3,8,'member');a.branch(5,3,9,'pair_blocked');a.label('member')
    for r in (12,14):
        a.branch(4,r,8,'pair_blocked');a.branch(4,r,9,'pair_blocked')
    a.label('next');a.addiu(13,13,4);a.addiu(3,3,1);a.branch(5,3,15,'others')
    # Stage destruction and direct non-effect cinematic paths are not owned by
    # the effect arbiter. Preserve their exclusive presentation transaction.
    a.lw(11,28,-22180);a.branch(4,11,0,'allow')
    a.lw(8,11,812);a.branch(5,8,0,'camera_active')
    a.lw(8,11,704);a.branch(4,8,0,'allow')
    a.lw(8,11,776);a.i(12,8,8,3);a.addiu(9,0,1);a.branch(5,8,9,'allow')
    a.label('camera_active')
    # The native beam camera is owned by its captured pair. Independent
    # special animations can continue while the arbiter retains that camera.
    camera.emit_owned_beam(a,'effect_camera')
    a.jump('allow')
    a.label('effect_camera')
    camera.emit_owned_camera(a,'camera_blocked')
    a.jump('allow')
    a.label('form_blocked');a.addiu(3,0,3);a.jump('blocked')
    a.label('pair_blocked');a.addiu(3,0,4);a.jump('blocked')
    a.label('camera_blocked');a.addiu(3,0,2)
    a.label('blocked');a.addiu(2,0,1);a.jr()
    a.label('allow');a.move(2,0);a.move(3,0);a.jr()
    a.label('legacy');a.jump(old.PREDICATE)
    result=a.finish();assert len(result)<CONTROL-base;return result


def build_memory(ram, source='<prepared>'):
    import special_camera_arbitration as camera
    if len(ram)!=0x8000000:raise ValueError('Requires128MiB EE RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if count not in ACTOR_COUNTS or (u(core.MODE),u(core.MODE+8),u(core.MODE+12))!=(1,manager,count):
        raise ValueError('Requires a captured expanded match')
    if tuple(u(old.CONTROL+x) for x in (0,4,8))!=(1,manager,count):
        raise ValueError('Matching legacy admission required')
    native=elf_reader(elf_path(ROOT))[2]
    expected=old.predicate_code()
    if ram[old.PREDICATE:old.PREDICATE+len(expected)]!=expected:
        raise ValueError('Legacy transform admission changed')
    # Rebuilding the arbiter must be an idempotent no-op before admission opens.
    if camera.build_memory(ram,source=source)['blocks']:
        raise ValueError('Install complete special camera arbitration first')
    fresh=not any(ram[PREDICATE:END])
    control=struct.pack('<3I',MAGIC,manager,count)
    pieces=[(PREDICATE,predicate_code()),(CONTROL,control)]
    for index in SPECIAL_ENTRIES:
        entry,cave,previous,_=old.ENTRIES[index]
        original=old.wrapper(entry,cave,previous,native(entry,8),index)
        updated=core.rebound(old.wrapper,PREDICATE=PREDICATE)(entry,cave,previous,native(entry,8),index)
        if ram[entry:entry+8]!=struct.pack('<2I',(2<<26)|(cave>>2),0):
            raise ValueError('Special eligibility entry changed')
        if ram[cave:cave+len(original)] not in (original,updated):
            raise ValueError('Special eligibility wrapper changed')
        pieces.append((cave,updated))
    for p,data in pieces[:2]:
        if not fresh and ram[p:p+len(data)]!=data:
            raise ValueError('Concurrent special reservation changed')
    return dict(serial=SERIAL,crc=CRC,source=str(source),
        control=CONTROL,status='UNRELATED SPECIALS WITH OWNED CAMERA PRESENTATION',
        blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex())
                for p,d in pieces if ram[p:p+len(d)]!=d])
