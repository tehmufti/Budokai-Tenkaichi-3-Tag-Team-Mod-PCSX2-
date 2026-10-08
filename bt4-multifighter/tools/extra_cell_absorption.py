"""Independent extra Cell auxiliary handshake, separate from his form reload.

The reviewed host enables this service after validating its exact code. Without
that worker, extras keep the existing no-Android fallback. The auxiliary ACK
and FINISH never consume the actual replacement form's separate request row.
"""
from native_map import A, TRANSLATED, elf_path
import struct
from prototype import Assembler, ROOT, elf_reader
import fresh_team_combat as core
import extra_reload_requests as requests
from native_map import ticks

CODE, CAMERA, LEGACY_END = 0x07665000, 0x07667000, 0x07668000
AUX_BEGIN, AUX_READY = 0x07668000, 0x07669000
AUX_OWNED, AUX_UPDATE, OLD_UPDATE = 0x0766A000, 0x0766B000, 0x0766B800
AUX_RENDER, OLD_RENDER, RENDER_HOOK = 0x0766B900, 0x0766BF00, A(0x1D3668)
AUX_LIFE0, AUX_LIFE1 = 0x0766C000, 0x0766D000
UPDATE_HOOK = A(0x1D35B0)
LIFECYCLE = ((A(0x1C2810),0x07384000,AUX_LIFE0),(A(0x1C2858),0x07384400,AUX_LIFE1))
AUX_CONTROL, AUX_RECORDS, END = 0x0766E000, 0x0766E100, 0x0766F000
AUX_ENABLED, AUX_MAGIC = AUX_CONTROL, 0x43415831
AUX_STRIDE, AUX_ROWS, AUX_TIMEOUT = 64, requests.ROWS, ticks(180)
AUX_FIELDS = dict(generation=0,status=4,actor=8,model_id=12,model=16,
                  character=20,costume=24,source=28,manager=32,physical=36,
                  old_resource=40,queued_frame=44,target=48,reason=52,
                  bound_handle=56,bound_model_id=60)
# reason52 is the active READY-call count while pending; when skipped it is
# replaced by a reason code. Claimed rows never expire or mutate behind IO.
AUX_SKIPPED_DISABLED, AUX_SKIPPED_TIMEOUT = 1, 2
FRAME, QUIET_HOLD = 0x0768F028, 0x0768F010
assert AUX_RECORDS+AUX_ROWS*AUX_STRIDE<=END
FORM_CONTROL = 0x0766F000
HANDLER, HANDLER_SIZE = A(0x1FE960), 0x4A8
NATIVE = elf_reader(elf_path(ROOT))[2]
CALLS = ((A(0x1FEA30), A(0x1D6290), 0), (A(0x1FEB50), A(0x1D6360), 1),
         (A(0x1FEB6C), A(0x1D63D8), 0), (A(0x1FEB98), A(0x1D6408), 0))
CAMERA_CALLS = (A(0x1FE9D8), A(0x1FEAFC))
NATIVE_CAMERA = A(0x1C7330)
SAVED = (3, 8, 9, 10, 11, 12, 13, 14, 15, 24, 25)


def scope(a):
    """a0 physical -> t6 registered Cell actor; otherwise branch to native."""
    a.li(11,FORM_CONTROL);a.lw(12,11);a.addiu(13,0,1)
    a.branch(5,12,13,'native');a.lw(14,11,4);a.lw(12,28,-22364)
    a.branch(5,12,14,'native');a.lw(15,11,8)
    for p,value in ((requests.CONTROL,1),(requests.CONTROL+24,1),(core.MODE,1),(core.PAIR+4,0)):
        a.li(11,p);a.lw(12,11);a.addiu(13,0,value);a.branch(5,12,13,'native')
    for p,value in ((requests.CONTROL+4,14),(core.MODE+8,14),
                    (requests.CONTROL+8,15),(core.MODE+4,15),(core.MODE+12,15)):
        a.li(11,p);a.lw(12,11);a.branch(5,12,value,'native')
    a.i(11,11,4,2);a.branch(5,11,0,'native');a.r(0x2B,11,4,15);a.branch(4,11,0,'native')
    a.r(0,11,0,4,2);a.li(12,core.POINTERS);a.r(0x21,11,11,12);a.lw(14,11)
    a.li(11,0x100000);a.r(0x2B,12,14,11);a.branch(5,12,0,'native')
    a.li(11,0x08000000-0x1600);a.r(0x2B,12,11,14);a.branch(5,12,0,'native')
    a.i(12,12,14,3);a.branch(5,12,0,'native');a.lw(12,14);a.branch(5,12,4,'native')
    a.lw(12,14,0x948);a.addiu(13,0,239);a.branch(5,12,13,'native')
    a.lw(12,14,0x994);a.lw(13,14,0x998);a.i(11,11,13,6)
    a.branch(4,11,0,'native');a.r(0x2B,11,12,13);a.branch(4,11,0,'native')
    # Selected row is 164 bytes, not a shared leader bench assumption.
    a.r(0,11,0,12,5);a.r(0x21,11,11,12);a.r(0,11,0,11,2)
    a.r(0,12,0,12,5);a.r(0x21,11,11,12);a.r(0x21,11,11,14)
    a.lw(12,11,0x9A4);a.addiu(13,12,-105);a.i(11,13,13,2);a.branch(4,13,0,'native')
    a.addiu(13,12,1);a.lw(11,14,0x12D0);a.branch(5,11,13,'native')
    a.addiu(13,12,-4);a.lw(11,14,0x12F0);a.branch(5,11,13,'native')


def legacy_wrapper(index):
    """Only an enabled, registered extra Cell absorption owns this shortcut."""
    _, previous, result = CALLS[index]
    a = Assembler(CODE+index*0x800); a.addiu(29,29,-0x60)
    for i,r in enumerate(SAVED):a.i(63,r,29,i*8)
    scope(a)
    for i,r in enumerate(SAVED):a.i(55,r,29,i*8)
    a.addiu(29,29,0x60);a.addiu(2,0,result);a.jr()
    a.label('native')
    for i,r in enumerate(SAVED):a.i(55,r,29,i*8)
    a.addiu(29,29,0x60);a.jump(previous)
    data=a.finish();assert len(data)<=0x800;return data



def camera_wrapper():
    """Keep an Android-less extra absorption framed on its own Cell model.

    Redirect only the two action-239 camera requests, not animation or camera
    policy. Leaders and a genuinely bound auxiliary retain the native scene.
    Entry 6 is Cell's stock centered close-up; all anchors use his own skeleton.
    """
    a=Assembler(CAMERA);a.addiu(29,29,-0x60)
    for i,r in enumerate(SAVED):a.i(63,r,29,i*8)
    a.i(63,4,29,0x58)
    a.li(11,0x100000);a.r(0x2B,12,4,11);a.branch(5,12,0,'native')
    a.li(11,0x08000000-0x1600);a.r(0x2B,12,11,4);a.branch(5,12,0,'native')
    a.i(12,12,4,3);a.branch(5,12,0,'native');a.lw(4,4)
    scope(a)
    a.i(55,11,29,0x58);a.branch(5,11,14,'native')
    a.lw(11,14,0x1330);a.branch(5,11,0,'native')
    a.branch(5,5,0,'native');a.addiu(11,6,-4);a.i(11,12,11,2)
    a.branch(4,12,0,'native');a.addiu(6,0,6)
    a.label('native')
    for i,r in enumerate(SAVED):a.i(55,r,29,i*8)
    a.i(55,4,29,0x58);a.addiu(29,29,0x60);a.jump(NATIVE_CAMERA)
    data=a.finish();assert len(data)<LEGACY_END-CAMERA;return data



def auxiliary_row(physical):
    if type(physical)is not int or not 2<=physical<AUX_ROWS+2:
        raise ValueError('Auxiliary physical ID outside captured extra rows')
    return AUX_RECORDS+(physical-2)*AUX_STRIDE


def _return(a,result):
    for i,r in enumerate(SAVED):a.i(55,r,29,i*8)
    a.addiu(29,29,0x60);a.addiu(2,0,result);a.jr()


def wrapper(index):
    if index>=2:return legacy_wrapper(index)
    a=Assembler(CODE+index*0x800);a.addiu(29,29,-0x60)
    for i,r in enumerate(SAVED):a.i(63,r,29,i*8)
    scope(a);a.jump(AUX_BEGIN if index==0 else AUX_READY)
    a.label('native')
    for i,r in enumerate(SAVED):a.i(55,r,29,i*8)
    a.addiu(29,29,0x60);a.jump(CALLS[index][1])
    code=a.finish();assert len(code)<=0x800;return code.ljust(0x800,b"\0")


def _gate(a,fallback):
    """Enter with old scope: a0 physical, t6 actor, t4 selected source."""
    a.li(11,AUX_CONTROL);a.lw(8,11);a.addiu(9,0,1);a.branch(5,8,9,fallback)
    a.lw(8,11,4);a.li(9,AUX_MAGIC);a.branch(5,8,9,fallback)
    a.lw(8,11,8);a.lw(9,28,-22364);a.branch(5,8,9,fallback)
    a.lw(8,11,12);a.branch(5,8,15,fallback)
    a.i(11,8,4,AUX_ROWS+2);a.branch(4,8,0,fallback)
    # Verify exact Android costume and current, independently registered Cell
    # fighter model before recording any pointer for the host.
    a.addiu(8,12,-105);a.r(0,8,0,8,1);a.lw(9,14,0x12F4);a.branch(5,8,9,fallback)
    a.lw(13,14,12);a.i(11,8,13,12);a.branch(4,8,0,fallback)
    a.r(0,8,0,13,2);a.li(9,core.MODELS);a.r(0x21,8,8,9);a.lw(9,8)
    a.li(11,0x100000);a.r(0x2B,8,9,11);a.branch(5,8,0,fallback)
    a.li(11,0x08000000-0x1670);a.r(0x2B,8,11,9);a.branch(5,8,0,fallback)
    a.i(12,8,9,3);a.branch(5,8,0,fallback)
    for off,value in ((0,0),(4,1)):
        a.lw(8,9,off);a.addiu(11,0,value);a.branch(5,8,11,fallback)
    a.lw(8,9,12);a.branch(5,8,12,fallback)
    a.lw(8,9,16);a.branch(5,8,13,fallback)
    a.lw(8,9,20)
    a.li(11,0x100000);a.r(0x2B,11,8,11);a.branch(5,11,0,fallback)
    a.li(11,0x08000000-56);a.r(0x2B,11,11,8);a.branch(5,11,0,fallback)
    a.i(12,11,8,3);a.branch(5,11,0,fallback)
    a.addiu(10,4,-2);a.r(0,10,0,10,6);a.li(11,AUX_RECORDS);a.r(0x21,10,10,11)
    # Returns t2 row, t1 model, t5 model ID, t4 source, t6 actor.


def auxiliary_begin_code():
    a=Assembler(AUX_BEGIN);_gate(a,'fallback')
    a.addiu(11,12,-4);a.branch(5,5,11,'fallback')
    a.addiu(11,12,-105);a.r(0,11,0,11,1);a.branch(5,6,11,'fallback')
    a.branch(5,7,0,'fallback');a.i(55,8,29,8);a.addiu(11,0,2);a.branch(5,8,11,'fallback')
    a.lw(8,14,0x1330);a.branch(5,8,0,'fallback')
    # A duplicate call cannot replace a claimed receipt. A fresh native BEGIN
    # supersedes completed/skipped/stale rows, including a previous match.
    a.lw(8,10,4);a.addiu(11,0,2);a.branch(5,8,11,'queue')
    a.lw(8,10,8);a.branch(5,8,14,'queue');a.lw(8,10,16);a.branch(5,8,9,'queue')
    a.lw(8,10,32);a.lw(11,28,-22364);a.branch(4,8,11,'fallback')
    a.label('queue');a.lw(8,10);a.addiu(8,8,1);a.branch(5,8,0,'generation');a.addiu(8,0,1)
    a.label('generation');a.sw(8,10)
    # Publish status last: no partially populated pending row is observable.
    a.sw(0,10,4);a.sw(14,10,8);a.sw(13,10,12);a.sw(9,10,16)
    a.sw(5,10,20);a.sw(6,10,24);a.sw(12,10,28)
    a.lw(8,28,-22364);a.sw(8,10,32);a.sw(4,10,36);a.lw(8,9,20);a.sw(8,10,40)
    a.li(8,FRAME);a.lw(8,8);a.sw(8,10,44);a.addiu(8,12,1);a.sw(8,10,48)
    for off in (52,56,60):a.sw(0,10,off)
    a.addiu(8,0,1);a.sw(8,10,4)
    a.label('fallback');_return(a,0)
    code=a.finish();assert len(code)<AUX_READY-AUX_BEGIN;return code


def auxiliary_ready_code():
    a=Assembler(AUX_READY);_gate(a,'ready')
    a.lw(8,10);a.branch(4,8,0,'ready')
    for off,reg in ((8,14),(12,13),(16,9),(28,12),(36,4)):
        a.lw(8,10,off);a.branch(5,8,reg,'ready')
    a.lw(8,10,32);a.lw(11,28,-22364);a.branch(5,8,11,'ready')
    a.lw(8,10,40);a.lw(11,9,20);a.branch(5,8,11,'ready')
    a.lw(8,10,20);a.addiu(11,12,-4);a.branch(5,8,11,'ready')
    a.lw(8,10,24);a.addiu(11,12,-105);a.r(0,11,0,11,1);a.branch(5,8,11,'ready')
    a.lw(8,10,48);a.addiu(11,12,1);a.branch(5,8,11,'ready')
    a.lw(8,10,4);a.addiu(11,0,6);a.branch(4,8,11,'ready')
    a.addiu(11,0,5);a.branch(4,8,11,'bound')
    a.addiu(11,0,2);a.branch(4,8,11,'wait')
    a.addiu(11,0,1);a.branch(5,8,11,'ready')
    # Count only actual READY updates while the native actor is progressing,
    # never scene-pause wall time or a held host transaction.
    a.li(8,QUIET_HOLD);a.lw(8,8);a.branch(5,8,0,'wait')
    a.lw(8,10,52);a.addiu(8,8,1);a.sw(8,10,52)
    a.i(11,11,8,AUX_TIMEOUT);a.branch(5,11,0,'wait')
    a.addiu(8,0,AUX_SKIPPED_TIMEOUT);a.sw(8,10,52);a.addiu(8,0,6);a.sw(8,10,4);a.jump('ready')
    a.label('bound')
    # A status bit alone is insufficient: require this exact type2 model and
    # live independent native resource before allowing native animation/free.
    a.lw(8,14,0x1330);a.addiu(11,0,1);a.branch(5,8,11,'wait')
    a.lw(24,10,56);a.lw(8,14,0x1334);a.branch(5,8,24,'wait')
    a.addiu(8,24,-2);a.i(11,8,8,12);a.branch(4,8,0,'wait')
    a.lw(25,10,60);a.lw(8,14,0x1338);a.branch(5,8,25,'wait')
    a.i(11,8,25,12);a.branch(4,8,0,'wait')
    a.r(0,8,0,25,2);a.li(11,core.MODELS);a.r(0x21,8,8,11);a.lw(9,8)
    a.li(11,0x100000);a.r(0x2B,8,9,11);a.branch(5,8,0,'wait')
    a.li(11,0x08000000-0x1670);a.r(0x2B,8,11,9);a.branch(5,8,0,'wait')
    a.i(12,8,9,3);a.branch(5,8,0,'wait')
    for off,value in ((0,2),(4,1)):
        a.lw(8,9,off);a.addiu(11,0,value);a.branch(5,8,11,'wait')
    a.lw(8,9,16);a.branch(5,8,25,'wait')
    a.lw(8,9,12);a.lw(11,10,20);a.branch(5,8,11,'wait')
    a.lw(9,9,20)
    a.li(11,0x100000);a.r(0x2B,8,9,11);a.branch(5,8,0,'wait')
    a.li(11,0x08000000-56);a.r(0x2B,8,11,9);a.branch(5,8,0,'wait')
    a.i(12,8,9,3);a.branch(5,8,0,'wait')
    a.lw(8,9,48);a.addiu(11,0,3);a.branch(5,8,11,'wait')
    a.lw(8,9,52);a.branch(5,8,24,'wait')
    a.lw(8,10,40);a.branch(4,8,9,'wait')
    # The original camera5 call occurred on the first17E frame, before async
    # publication, and therefore used camera6. Reissue the authored absorption
    # view exactly once after a verified Android exists, before native177.
    # Host publication resets reason52 to0; it is a camera marker for status5.
    a.lw(8,10,52);a.branch(5,8,0,'ready')
    a.addiu(29,29,-0xC0)
    camera_saved=(4,5,6,7,10,31)
    for i,r in enumerate(camera_saved):a.i(63,r,29,8*i)
    for i in range(32):a.i(57,i,29,0x40+4*i)
    a.move(4,14);a.move(5,0);a.addiu(6,0,5);a.call(NATIVE_CAMERA)
    for i in range(32):a.i(49,i,29,0x40+4*i)
    for i,r in enumerate(camera_saved):a.i(55,r,29,8*i)
    a.addiu(29,29,0xC0);a.addiu(8,0,1);a.sw(8,10,52)
    a.label('ready');_return(a,1)
    a.label('wait');_return(a,0)
    code=a.finish();assert len(code)<AUX_CONTROL-AUX_READY;return code



def auxiliary_owned_code():
    """a0 actor -> v0 owned row, v1 status1/5; or v0=0. Read-only."""
    a=Assembler(AUX_OWNED)
    a.li(11,AUX_CONTROL);a.lw(8,11,4);a.li(9,AUX_MAGIC);a.branch(5,8,9,'no')
    a.lw(15,11,12);a.addiu(8,15,-3);a.i(11,8,8,AUX_ROWS);a.branch(4,8,0,'no')
    a.lw(12,11,8);a.lw(8,28,-22364);a.branch(5,8,12,'no')
    for p,expected in ((core.MODE,1),(core.PAIR+4,0)):
        a.li(11,p);a.lw(8,11);a.addiu(9,0,expected);a.branch(5,8,9,'no')
    for p,reg in ((core.MODE+8,12),(core.MODE+4,15),(core.MODE+12,15)):
        a.li(11,p);a.lw(8,11);a.branch(5,8,reg,'no')
    a.li(11,0x100000);a.r(0x2B,8,4,11);a.branch(5,8,0,'no')
    a.li(11,0x08000000-0x1600);a.r(0x2B,8,11,4);a.branch(5,8,0,'no')
    a.i(12,8,4,3);a.branch(5,8,0,'no');a.lw(13,4)
    a.i(11,8,13,2);a.branch(5,8,0,'no');a.r(0x2B,8,13,15);a.branch(4,8,0,'no')
    a.r(0,8,0,13,2);a.li(11,core.POINTERS);a.r(0x21,8,8,11);a.lw(8,8)
    a.branch(5,8,4,'no');a.addiu(10,13,-2);a.r(0,10,0,10,6)
    a.li(11,AUX_RECORDS);a.r(0x21,10,10,11)
    a.lw(3,10,4);a.addiu(11,0,1);a.branch(4,3,11,'row_status')
    a.addiu(11,0,5);a.branch(5,3,11,'no')
    a.label('row_status');a.lw(8,10);a.branch(4,8,0,'no')
    for off,reg in ((8,4),(32,12),(36,13)):
        a.lw(8,10,off);a.branch(5,8,reg,'no')
    a.lw(8,10,28);a.addiu(11,8,-105);a.i(11,11,11,2);a.branch(4,11,0,'no')
    a.addiu(11,8,-4);a.lw(8,10,20);a.branch(5,8,11,'no')
    a.addiu(11,0,1);a.branch(4,3,11,'owned')
    a.lw(8,4,0x1330);a.addiu(11,0,1);a.branch(5,8,11,'no')
    a.lw(24,10,56);a.lw(8,4,0x1334);a.branch(5,8,24,'no')
    a.addiu(8,24,-2);a.i(11,8,8,12);a.branch(4,8,0,'no')
    a.lw(25,10,60);a.lw(8,4,0x1338);a.branch(5,8,25,'no')
    a.i(11,8,25,12);a.branch(4,8,0,'no')
    a.r(0,8,0,25,2);a.li(11,core.MODELS);a.r(0x21,8,8,11);a.lw(9,8)
    a.li(11,0x100000);a.r(0x2B,8,9,11);a.branch(5,8,0,'no')
    a.li(11,0x08000000-0x1670);a.r(0x2B,8,11,9);a.branch(5,8,0,'no')
    a.i(12,8,9,3);a.branch(5,8,0,'no')
    for off,value in ((0,2),(4,1)):
        a.lw(8,9,off);a.addiu(11,0,value);a.branch(5,8,11,'no')
    a.lw(8,9,16);a.branch(5,8,25,'no');a.lw(8,9,12);a.lw(11,10,20);a.branch(5,8,11,'no')
    # Resolve handle independently through the native registry. Matching flags
    # in an unrelated allocation cannot authorize native freeing.
    a.li(11,A(0x2FEC44));a.lw(11,11)
    a.li(8,0x100000);a.r(0x2B,8,11,8);a.branch(5,8,0,'no')
    a.li(8,0x08000000-440200);a.r(0x2B,8,8,11);a.branch(5,8,0,'no')
    a.i(12,8,11,3);a.branch(5,8,0,'no')
    a.li(8,439276);a.r(0x21,11,11,8);a.addiu(8,24,-2)
    a.r(0,14,0,8,6);a.r(0,8,0,8,3);a.r(0x23,8,14,8);a.r(0x21,11,11,8)
    a.lw(8,9,20);a.branch(5,8,11,'no')
    a.lw(8,11,48);a.addiu(9,0,3);a.branch(5,8,9,'no')
    a.lw(8,11,52);a.branch(5,8,24,'no')
    a.label('owned');a.move(2,10);a.jr()
    a.label('no');a.move(2,0);a.jr()
    code=a.finish();assert len(code)<AUX_UPDATE-AUX_OWNED;return code


CLEANUP_SAVED=tuple(range(1,29))+(30,31)


def _cleanup_save(a):
    a.addiu(29,29,-0x180)
    for i,r in enumerate(CLEANUP_SAVED):a.i(63,r,29,8*i)
    for i in range(32):a.i(57,i,29,0x100+4*i)


def _cleanup_restore(a):
    for i in range(32):a.i(49,i,29,0x100+4*i)
    for i,r in enumerate(CLEANUP_SAVED):a.i(55,r,29,8*i)
    a.addiu(29,29,0x180)


def _destroy_owned(a):
    a.move(16,2);a.addiu(8,0,1);a.branch(4,3,8,'cancel_pending')
    a.call(A(0x1D3568))
    for off in (4,56,60):a.sw(0,16,off)
    a.jump('released')
    a.label('cancel_pending');a.addiu(8,0,3);a.sw(8,16,52);a.addiu(8,0,6);a.sw(8,16,4)
    a.label('released')


def auxiliary_update_code():
    a=Assembler(AUX_UPDATE);_cleanup_save(a);a.call(AUX_OWNED)
    a.branch(4,2,0,'native');a.lw(8,4,0x948);a.addiu(9,0,239);a.branch(4,8,9,'native')
    _destroy_owned(a);_cleanup_restore(a);a.move(2,0);a.jr()
    a.label('native');_cleanup_restore(a);a.jump(OLD_UPDATE)
    code=a.finish();assert len(code)<OLD_UPDATE-AUX_UPDATE;return code


def auxiliary_lifecycle_code(base,previous):
    a=Assembler(base);_cleanup_save(a)
    # AUX_OWNED validates world and row before each destruction. Iterating the
    # fixed reserved rows does not dereference an actor until that predicate.
    a.li(17,AUX_RECORDS);a.addiu(18,0,AUX_ROWS)
    a.label('loop');a.lw(4,17,8);a.call(AUX_OWNED);a.branch(4,2,0,'next')
    _destroy_owned(a)
    a.label('next');a.addiu(17,17,AUX_STRIDE);a.addiu(18,18,-1);a.branch(5,18,0,'loop')
    a.li(8,AUX_CONTROL);a.lw(9,8,4);a.li(10,AUX_MAGIC);a.branch(5,9,10,'done')
    a.lw(9,8,8);a.lw(10,28,-22364);a.branch(5,9,10,'done');a.sw(0,8)
    a.label('done');_cleanup_restore(a);a.jump(previous)
    code=a.finish();assert len(code)<0x1000;return code


def auxiliary_render_code():
    """Do not draw the independently loaded prop before its native animation."""
    a=Assembler(AUX_RENDER);_cleanup_save(a);a.call(AUX_OWNED)
    a.branch(4,2,0,'native');a.addiu(8,0,5);a.branch(5,3,8,'hidden')
    a.lw(8,2,60);a.r(0,8,0,8,2);a.li(9,core.MODELS);a.r(0x21,8,8,9);a.lw(9,8)
    a.lw(8,9,0xC70);a.branch(4,8,0,'hidden')
    a.addiu(8,0,1);a.sw(8,9,8)
    a.label('native');_cleanup_restore(a);a.jump(OLD_RENDER)
    a.label('hidden');_cleanup_restore(a);a.move(2,0);a.jr()
    code=a.finish();assert len(code)<OLD_RENDER-AUX_RENDER;return code


def external_originals():
    return [(UPDATE_HOOK,NATIVE(UPDATE_HOOK,8)),(RENDER_HOOK,NATIVE(RENDER_HOOK,8))]+[
        (entry,struct.pack('<2I',(2<<26)|(previous>>2),0))for entry,previous,_ in LIFECYCLE]


def cleanup_pieces():
    old=Assembler(OLD_UPDATE)
    for word in struct.unpack('<2I',NATIVE(UPDATE_HOOK,8)):old.emit(word)
    old.jump(UPDATE_HOOK+8)
    result=[(AUX_OWNED,auxiliary_owned_code()),(AUX_UPDATE,auxiliary_update_code()),
            (OLD_UPDATE,old.finish()),(UPDATE_HOOK,struct.pack('<2I',(2<<26)|(AUX_UPDATE>>2),0))]
    render=Assembler(OLD_RENDER)
    for word in struct.unpack('<2I',NATIVE(RENDER_HOOK,8)):render.emit(word)
    render.jump(RENDER_HOOK+8)
    result += [(AUX_RENDER,auxiliary_render_code()),(OLD_RENDER,render.finish()),
               (RENDER_HOOK,struct.pack('<2I',(2<<26)|(AUX_RENDER>>2),0))]
    for entry,previous,base in LIFECYCLE:
        result += [(base,auxiliary_lifecycle_code(base,previous)),
                   (entry,struct.pack('<2I',(2<<26)|(base>>2),0))]
    return result


def helper_images(address,size):
    """Exact accepted native/owned helper images for dormant constructors."""
    original=NATIVE(address,size);patched=bytearray(original)
    hooks=[(UPDATE_HOOK,AUX_UPDATE),(RENDER_HOOK,AUX_RENDER)]+[(entry,base)for entry,_,base in LIFECYCLE]
    for at,target in hooks:
        if address<=at and at+8<=address+size:
            patched[at-address:at-address+8]=struct.pack('<2I',(2<<26)|(target>>2),0)
    return (original,bytes(patched))

def previous_pieces(camera=True):
    """Exact historical bytes retained solely for checked upgrades."""
    result=[(CODE+i*0x800,legacy_wrapper(i))for i in range(len(CALLS))]+[
        (site,struct.pack('<I',(3<<26)|((CODE+i*0x800)>>2)))for i,(site,_,_)in enumerate(CALLS)]
    if camera:result += [(CAMERA,camera_wrapper())]+[
        (site,struct.pack('<I',(3<<26)|(CAMERA>>2)))for site in CAMERA_CALLS]
    return result


def pieces():
    result=[(CODE+i*0x800,wrapper(i))for i in range(len(CALLS))]+[
        (site,struct.pack('<I',(3<<26)|((CODE+i*0x800)>>2)))for i,(site,_,_)in enumerate(CALLS)]+[
        (CAMERA,camera_wrapper())]+[(site,struct.pack('<I',(3<<26)|(CAMERA>>2)))for site in CAMERA_CALLS]
    return result+[(AUX_BEGIN,auxiliary_begin_code()),(AUX_READY,auxiliary_ready_code())]+cleanup_pieces()


def initial_state(ram):
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    return [(AUX_CONTROL,struct.pack('<4I',0,AUX_MAGIC,u(core.ACTORS),u(core.MODE+4))),
            (AUX_RECORDS,bytes(AUX_ROWS*AUX_STRIDE))]


def build_memory(ram,source='<prepared>'):
    """Install fresh or upgrade only exact historical dormant Cell images."""
    if len(ram)!=0x08000000:raise ValueError('Requires 128MiB captured EE RAM')
    # Cleanup must run before the exact captured safety detachment, never an
    # unknown predecessor that might already have freed these model pointers.
    import fresh_team_safety as safety
    from battle_mode_policy import ACTOR_COUNTS
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    count=u(core.MODE+4)
    if count not in ACTOR_COUNTS:raise ValueError('Cell service requires a captured fighter count')
    actors=[]
    for i in range(count):
        actor=u(core.POINTERS+4*i)
        if not 0x100000<=actor<=len(ram)-0x1600 or actor%4:
            raise ValueError('Cell lifecycle actor pointer changed')
        mid=u(actor+12)
        if mid>=12:raise ValueError('Cell lifecycle model identity changed')
        model=u(core.MODELS+4*mid)
        if not 0x100000<=model<=len(ram)-0x1670 or model%4:
            raise ValueError('Cell lifecycle model pointer changed')
        actors.append(dict(model=model))
    config=dict(creation_header=u(safety.CONTROL+16),actors=actors)
    for entry,previous,_ in LIFECYCLE:
        # The beta.37 detachment also forgets the widened trail lists; captures prepared before it keep the
        # beta.36 detachment. Either is the exact captured predecessor this cleanup must run before.
        candidates=[safety.lifecycle_code(entry,previous,NATIVE(entry,8),config,trail_clear=clear) for clear in (True,False)]
        if not any(ram[previous:previous+len(expected)]==expected for expected in candidates):
            raise ValueError('Cell lifecycle predecessor changed')
    current=pieces()+initial_state(ram)
    native_handler=NATIVE(HANDLER,HANDLER_SIZE)
    for site,previous_target,_ in CALLS:
        if struct.unpack('<I',NATIVE(site,4))[0]!=(3<<26)|(previous_target>>2):
            raise ValueError('Native Cell absorption call changed')
    for site in CAMERA_CALLS:
        if struct.unpack('<I',NATIVE(site,4))[0]!=(3<<26)|(NATIVE_CAMERA>>2):
            raise ValueError('Native Cell camera call changed')
    accepted=False
    import json
    prior=[(b['address'],bytes.fromhex(b['data_hex']))for b in json.loads(
        (ROOT/'analysis/sept20-cell-visible-prior-pieces.json').read_text(encoding='utf-8'))]
    for installed in ((),previous_pieces(False),previous_pieces(True),*(() if TRANSLATED else (prior+initial_state(ram),)),current):
        cave=bytearray(END-CODE);handler=bytearray(native_handler);external=dict(external_originals())
        for at,data in installed:
            if CODE<=at<END:cave[at-CODE:at-CODE+len(data)]=data
            elif HANDLER<=at<HANDLER+HANDLER_SIZE:handler[at-HANDLER:at-HANDLER+len(data)]=data
            elif at in external:external[at]=data
        if (ram[CODE:END]==bytes(cave) and ram[HANDLER:HANDLER+HANDLER_SIZE]==bytes(handler) and
                all(ram[at:at+len(data)]==data for at,data in external.items())):
            accepted=True;break
    if not accepted:raise ValueError('Cell absorption adapter or native handler changed')
    return dict(source=str(source),auxiliary_control=AUX_CONTROL,auxiliary_records=AUX_RECORDS,
        blocks=[dict(address=p,expected_hex=bytes(ram[p:p+len(d)]).hex(),data_hex=d.hex())
                for p,d in current if ram[p:p+len(d)]!=d],
        limitations=['Visible extra Android requires the separately enabled and verified auxiliary host worker; disabled or unclaimed jobs retain the safe centered-camera fallback.'])
