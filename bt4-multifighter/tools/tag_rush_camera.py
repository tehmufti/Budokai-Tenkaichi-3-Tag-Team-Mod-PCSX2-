"""Private camera routing for the local cooperative tag rush.

The cinematic has its own camera record and native matrix construction. Its
update retains the native track and restores the render binding before another
view is visited. A bystander's camera remains owned by the normal policy.
"""
import struct
from native_map import A
from prototype import Assembler
from regional import SCISSOR_Y1
import fresh_team_combat as core
import fresh_team_camera as follow

BASE, END = 0x06D78000, 0x06D80000
INIT, UPDATE, SELECT, QUERY = BASE, BASE+0x800, BASE+0x1000, BASE+0x2000
FIT_VIEW, FIT_END = BASE+0x2400, BASE+0x2800
FIT_WEIGHT = BASE+0x1800
CAMERA = 0x06D7C000
CONTROL, MAGIC = 0x06D08000, 0x54414731
ACTIVE, MEMBERS, SHARED = 16, 20, 24
REGS = tuple(range(2, 28))+(30, 31)


def save(a):
    a.addiu(29,29,-0x140)
    for i,r in enumerate(REGS):a.i(63,r,29,8*i)


def restore(a,skip=()):
    for i,r in enumerate(REGS):
        if r not in skip:a.i(55,r,29,8*i)
    a.addiu(29,29,0x140)


def emit_active(a,fail):
    """Inline ownership guard; clobbers t0,t1,t3. No call into absent code."""
    a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,fail)
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,fail)
    a.branch(4,9,0,fail)
    a.lw(9,8,8);a.li(11,core.MODE+4);a.lw(11,11);a.branch(5,9,11,fail)
    a.lw(9,8,12);a.branch(4,9,0,fail)
    a.lw(9,8,ACTIVE);a.addiu(11,0,1);a.branch(5,9,11,fail)


def emit_presentation(a,fail):
    """Camera-only ownership includes the native launch; gameplay ACTIVE does not."""
    import tag_team_rush as runtime
    import tag_rush_approach as rush
    emit_active(a,fail+'_launch');a.jump(fail+'_present')
    a.label(fail+'_launch');a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,fail)
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,fail);a.branch(4,9,0,fail)
    a.lw(9,8,8);a.li(11,core.MODE+4);a.lw(11,11);a.branch(5,9,11,fail)
    a.lw(9,8,12);a.branch(4,9,0,fail)
    a.lw(9,8,runtime.C['approaching']);a.li(11,1);a.branch(5,9,11,fail)
    a.li(8,rush.STATE);a.lw(9,8);a.li(11,rush.MAGIC);a.branch(5,9,11,fail)
    a.lw(9,8,rush.S['active']);a.li(11,1);a.branch(5,9,11,fail)
    a.lw(9,8,rush.S['manager']);a.lw(11,28,-22364);a.branch(5,9,11,fail)
    a.li(8,CONTROL);a.label(fail+'_present')


def emit_shared(a,yes,tag):
    emit_presentation(a,tag);a.lw(9,8,SHARED);a.branch(5,9,0,yes);a.label(tag)


def emit_camera(a,out,physical,fail,tag):
    """Physical index -> private camera, or branch fail; t0,t1,t3 scratch.

    out and physical must not be one of those scratch registers. Even a
    shared presentation rejects a stale/out-of-range subject.
    """
    assert out not in (8,9,11) and physical not in (8,9,11)
    emit_active(a,tag+'_approach')
    a.lw(9,8,8);a.r(0x2B,11,physical,9);a.branch(4,11,0,fail)
    a.lw(9,8,SHARED);a.branch(5,9,0,tag+'_yes')
    a.lw(9,8,MEMBERS);a.li(11,1);a.r(4,11,physical,11);a.r(0x24,9,9,11);a.branch(4,9,0,fail)
    a.jump(tag+'_yes')
    a.label(tag+'_approach')
    # Launch owns the same private camera but never sets cinematic ACTIVE:
    # the victim can evade during travel and unrelated fighters remain free.
    import tag_team_rush as runtime
    import tag_rush_approach as rush
    a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,fail)
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,fail);a.branch(4,9,0,fail)
    a.lw(9,8,8);a.li(11,core.MODE+4);a.lw(11,11);a.branch(5,9,11,fail)
    a.r(0x2B,11,physical,9);a.branch(4,11,0,fail)
    a.lw(9,8,12);a.branch(4,9,0,fail)
    a.lw(9,8,runtime.C['approaching']);a.li(11,1);a.branch(5,9,11,fail)
    a.li(8,rush.STATE);a.lw(9,8);a.li(11,rush.MAGIC);a.branch(5,9,11,fail)
    a.lw(9,8,rush.S['active']);a.li(11,1);a.branch(5,9,11,fail)
    a.lw(9,8,rush.S['manager']);a.lw(11,28,-22364);a.branch(5,9,11,fail)
    a.li(8,CONTROL);a.lw(9,8,SHARED);a.branch(5,9,0,tag+'_native')
    for role in range(3):
        a.li(8,rush.ROWS+role*rush.STRIDE);a.lw(9,8,rush.R['index']);a.branch(4,9,physical,tag+'_native')
    a.jump(fail)
    a.label(tag+'_native');a.lw(out,28,-22180)
    a.li(8,0x100000);a.r(0x2B,9,out,8);a.branch(5,9,0,fail)
    a.li(8,0x8000000-832);a.r(0x2B,9,8,out);a.branch(5,9,0,fail)
    a.li(8,rush.ROWS);a.lw(9,8,rush.R['model']);a.lw(11,out,768)
    a.branch(4,9,11,tag+'_native_bound');a.lw(11,out,772);a.branch(5,9,11,fail)
    a.label(tag+'_native_bound');a.jump(tag+'_selected')
    a.label(tag+'_yes');a.li(out,CAMERA);a.label(tag+'_selected')


def emit_side_camera(a,out,side,fail,tag):
    """Native side -> its currently watched physical subject -> camera."""
    assert out not in (8,9,11) and side not in (8,9,11)
    a.li(8,follow.SUCCESSOR_CONTROL);a.r(0,9,0,side,2);a.r(0x21,8,8,9)
    a.lw(out,8,8);emit_camera(a,out,out,fail,tag)


def copy(a,src,dst,size,tag):
    a.addiu(10,src,size);a.label(tag)
    a.i(55,11,src,0);a.i(55,12,src,8);a.i(63,11,dst,0);a.i(63,12,dst,8)
    a.addiu(src,src,16);a.addiu(dst,dst,16);a.branch(5,src,10,tag)


def init_code():
    """Initialize once at activation, before runtime publishes ACTIVE=1."""
    a=Assembler(INIT);save(a)
    a.lw(16,28,-22176);a.li(8,0x100000);a.r(0x2B,9,16,8);a.branch(5,9,0,'no')
    a.li(8,0x8000000-832);a.r(0x2B,9,8,16);a.branch(5,9,0,'no')
    a.i(12,9,16,15);a.branch(5,9,0,'no')
    a.lw(17,28,-22172);a.li(8,0x100000);a.r(0x2B,9,17,8);a.branch(5,9,0,'no')
    a.li(8,0x8000000-0xC44);a.r(0x2B,9,8,17);a.branch(5,9,0,'no')
    a.i(12,9,17,3);a.branch(5,9,0,'no');a.lw(18,17,0xC40)
    a.move(8,16);a.li(9,CAMERA);copy(a,8,9,832,'copy')
    # Use a full-screen template; participant split passes make render-local
    # clones with their own viewport/projection, preserving this pose.
    a.li(4,CAMERA);a.move(5,0);a.call(A(0x23E950))
    a.li(8,CAMERA)
    for off in (704,776,768,772,*range(780,812,4)):a.sw(0,8,off)
    a.li(9,1);a.sw(9,8,812)
    a.sw(16,28,-22176);a.sw(18,17,0xC40)
    a.li(2,1);a.jump('done')
    a.label('no');a.move(2,0)
    a.label('done');restore(a,skip=(2,));a.jr();return a.finish()


def update_code():
    """Compute matrices after runtime writes eye720/Euler736; no ownership leak."""
    a=Assembler(UPDATE);save(a);emit_active(a,'done')
    a.lw(16,28,-22180);a.lw(17,28,-22176);a.lw(18,28,-22172);a.lw(19,18,0xC40)
    # Native23D510's direct-camera branch computes these same matrices after
    # applying its camera-local shake. Call the two pure camera builders
    # directly: no global track is borrowed or advanced a second time.
    a.li(4,CAMERA);a.addiu(5,4,64);a.addiu(6,4,720);a.addiu(7,4,736);a.call(A(0x23E608))
    a.li(4,CAMERA);a.addiu(5,4,720);a.call(A(0x23E598))
    a.move(4,17);a.li(5,1);a.call(A(0x23E6A0))
    a.sw(16,28,-22180);a.sw(17,28,-22176);a.sw(19,18,0xC40)
    a.label('done');restore(a);a.jr();return a.finish()


def query_code():
    a=Assembler(QUERY);save(a);emit_camera(a,2,4,'no','query');a.jump('done')
    a.label('no');a.move(2,0)
    a.label('done');restore(a,skip=(2,));a.jr();return a.finish()


def emit_fit_view(a,clone,source,label):
    """Set a1 to the rendered eye; only tag clones call the optional helper."""
    a.addiu(2,source,544)
    a.li(8,CAMERA);a.branch(5,source,8,label)
    a.move(4,clone);a.move(5,source);a.call(FIT_VIEW);a.label(label)
    a.move(5,2)


def fit_view_code():
    """Pull a narrow tag view back without widening its native lens.

    a0 = render-local clone with the authored view already copied; a1 = source.
    Return the rendered eye pointer for 23E598. A half-width/full-height view
    needs twice the focal-plane distance to retain the shot's horizontal span.
    Dolly along the actual forward basis, preserving roll, aim and native FOV;
    widening that FOV instead exposed unrendered skybox margins. Quarter views
    already retain the full shot's aspect ratio and need no additional fit.
    """
    import beam_struggle as fp
    import tag_team_rush as tag
    import tag_rush_assets as assets
    a=Assembler(FIT_VIEW);save(a);a.move(16,4);a.move(17,5)
    a.addiu(2,17,544)
    a.li(8,CAMERA);a.branch(5,17,8,'done');a.branch(4,16,17,'done')
    # The original Sadistic Dance cuts are already authored for this game.
    # Only our custom ending shots opt into portrait-view fitting.
    a.li(18,tag.MEMBERS_SAVE);a.lw(8,18);a.li(9,0x54534331);a.branch(5,8,9,'done')
    a.lw(8,18,20);a.li(9,assets.BASE);a.r(0x2B,10,8,9);a.branch(5,10,0,'done')
    a.li(9,assets.END-64);a.r(0x2B,10,9,8);a.branch(5,10,0,'done')
    a.i(12,9,8,15);a.branch(5,9,0,'done')
    a.lw(8,8,28);a.i(12,8,8,assets.CUSTOM_FINISHER);a.branch(4,8,0,'done')
    a.lw(8,16,520);a.branch(5,8,0,'done')
    a.lw(8,16,524);a.li(9,SCISSOR_Y1);a.branch(5,8,9,'done')
    a.lw(8,16,512);a.lw(9,16,516)
    a.branch(4,8,0,'left');a.li(10,257);a.branch(5,8,10,'done')
    a.li(10,511);a.branch(5,9,10,'done');a.jump('fit')
    a.label('left');a.li(10,254);a.branch(5,9,10,'done')
    a.label('fit');a.addiu(18,18,64)  # custom shot's authored world-space focus
    for base,offsets in ((17,(72,88,104,720,724,728,56,120)),(18,(0,4,8))):
        for off in offsets:
            a.lw(8,base,off);a.li(9,0x7F800000);a.r(0x24,8,8,9);a.branch(4,8,9,'done')
    # In the row-vector world-to-camera matrix, column2 is the world forward
    # vector. dot(focus-eye,forward) is the shot's focal-plane distance.
    fp.fconst(a,3,0.)
    for off,basis in ((0,72),(4,88),(8,104)):
        a.i(49,0,18,off);a.i(49,1,17,720+off);fp.fop(a,1,0,0,1)
        a.i(49,1,17,basis);fp.fop(a,2,0,0,1);fp.fop(a,0,3,3,0)
    a.move(4,18);a.call(FIT_WEIGHT);fp.fop(a,2,3,3,0)
    fp.fconst(a,4,1.);fp.fop(a,0x34,0,3,4);a.branch(17,8,1,'done')
    # Reject bad/stale framing rather than placing the camera kilometres away.
    fp.fconst(a,4,4096.);fp.fop(a,0x34,0,3,4);a.branch(17,8,0,'done')
    for off,basis in ((0,72),(4,88),(8,104)):
        a.i(49,0,17,basis);fp.fop(a,2,0,0,3);a.i(49,1,17,720+off)
        fp.fop(a,1,0,1,0);a.i(57,0,16,720+off)
    a.li(8,0x3F800000);a.sw(8,16,732)
    # A backward movement along camera Z changes only view-space translation
    # Z. Assign from the source on every pass, never compound a prior dolly.
    for off in (56,120):
        a.i(49,0,17,off);fp.fop(a,0,0,0,3);a.i(57,0,16,off)
    a.addiu(2,16,720)
    a.label('done');restore(a,skip=(2,));a.jr();data=a.finish()
    assert FIT_VIEW+len(data)<=FIT_END
    return data


def fit_weight_code():
    """a0=published focus; f0=portrait dolly weight, retaining distance f3.

    Charge closeups frame one shooter, so keep their authored distance. Ease
    in the wider composition with the authored60..90-frame pullback, then
    retain full fitting for the beams and impact.
    """
    from native_map import ACTOR_HZ
    import beam_struggle as fp
    import tag_rush_assets as assets
    import tag_rush_choreography as choreography
    a=Assembler(FIT_WEIGHT);fp.fconst(a,0,1.)
    a.lw(8,4,20-64);a.lw(8,8,28);a.i(12,8,8,assets.CHARGE_BEAM)
    a.branch(4,8,0,'done')
    a.lw(8,4,8-64);a.emit((17<<26)|(4<<21)|(8<<16))
    a.emit((17<<26)|(20<<21)|32)
    fp.fconst(a,1,60/ACTOR_HZ);fp.fop(a,2,0,0,1)
    fp.fconst(a,1,float(choreography.CHARGE_CLOSEUP));fp.fop(a,0x36,0,0,1)
    a.branch(17,8,1,'close')
    fp.fop(a,1,0,0,1);fp.fconst(a,1,float(choreography.BEAM_START-choreography.CHARGE_CLOSEUP))
    fp.fop(a,3,0,0,1);fp.fconst(a,1,1.);fp.fop(a,0x34,0,0,1)
    a.branch(17,8,0,'wide')
    fp.fop(a,2,2,0,0);fp.fconst(a,1,2.);fp.fop(a,2,0,0,1)
    fp.fconst(a,1,3.);fp.fop(a,1,0,1,0);fp.fop(a,2,0,2,0)
    a.jump('done');a.label('close');fp.fconst(a,0,0.);a.jump('done')
    a.label('wide');fp.fconst(a,0,1.)
    a.label('done');a.jr();data=a.finish();assert FIT_WEIGHT+len(data)<=QUERY
    return data


def select_code():
    """v0: -1 leave native selection, 0 split, 1 private full-screen.

    Called after the normal selector has advanced the original native track.
    The tag track is updated by the runtime once, never by a viewport pass.
    """
    a=Assembler(SELECT);save(a);emit_presentation(a,'native')
    a.lw(9,8,SHARED);a.branch(5,9,0,'shared')
    a.call(A(0x12AB10));a.branch(4,2,0,'single');a.call(A(0x12A9E8));a.branch(5,2,0,'single')
    for side in range(2):
        a.addiu(4,0,side);a.call(A(0x23EF98));a.addiu(4,0,1);a.move(5,0);a.call(A(0x23EE78))
    a.move(4,0);a.call(A(0x23EF98));a.move(2,0);a.jump('done')
    a.label('single');a.call(A(0x23EE08));a.i(11,8,2,2);a.branch(5,8,0,'side');a.move(2,0)
    a.label('side');a.move(16,2);emit_side_camera(a,20,16,'native','single');a.jump('full')
    a.label('shared');a.li(16,0);emit_camera(a,20,16,'native','shared_view')
    a.label('full');a.move(4,20);a.addiu(5,0,1);a.call(A(0x23E6A0))
    a.lw(9,28,-22172);a.sw(20,9,0xC40);a.sw(20,28,-22176)
    a.li(2,1);a.jump('done')
    a.label('native');a.li(2,0xFFFFFFFF)
    a.label('done');restore(a,skip=(2,));a.jr();return a.finish()


def pieces():
    out=[(INIT,init_code()),(UPDATE,update_code()),(SELECT,select_code()),(FIT_WEIGHT,fit_weight_code()),(QUERY,query_code()),
         (FIT_VIEW,fit_view_code())]
    for (p,b),(q,_) in zip(out,out[1:]):assert p+len(b)<=q
    assert out[-1][0]+len(out[-1][1])<=FIT_END<=CAMERA
    return out


def build_memory(ram):
    if any(ram[BASE:END]):raise ValueError('Tag rush camera reservation occupied')
    return {'blocks':[dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=b.hex()) for p,b in pieces()]}
