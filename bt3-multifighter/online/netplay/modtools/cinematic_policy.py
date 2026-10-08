"""Captured native presentation policy with one binary ultimate preference.

Unchecked ultimates retain independent split views and suppress only their
native global activation stops. Checked ultimates share the original authored
camera and stop uninvolved actors for its full authenticated lifetime. Native
performer/victim handlers, impact timers and resource/scene holds stay intact.

Actor-local authored cameras raise native flag0xD3; director cameras require
an arbitration receipt or authenticated native track and model ownership. The cinematic still
advances once per frame. Ordinary rushes keep private participant viewports;
transformation close-ups retain their separate, ally-only split preference.

One decision drives both halves of the checked presentation. A stop that no
authenticated owner explains used to leave split screen with two ordinary
cameras while every bystander was frozen, so an ultimate whose native camera
binds a summoned effect model instead of a fighter paused player two without
ever framing the move. The living performer of the running native cinematic
is accepted as that shared subject, and any frame that still stops uninvolved
fighters presents one view instead of restoring the two ordinary viewports.

The shared stop never holds a fighter the running presentation itself needs:
one the authored camera binds (a victim at +768/+772), nor the live rush
partner of a member or of such a fighter. Holding them froze the reaction that
ends the move, so the presentation renewed itself until the hold bound (the
30 s rush stall). A latch is never taken, nor kept, onto a camera that is
showing another pair's live rush.
"""
from native_map import A, CRC, FLAG_BITS, SERIAL, TRANSLATED, elf_path
import struct
from prototype import Assembler, ROOT, elf_reader
import mod_settings as settings
import special_pause as pause
import fresh_team_combat as core
import fresh_team_camera as fresh
import cinematic_camera_state as camera
import camera_continuity as continuity
import leader_camera as leader
import team_intro
import result_presentation as result
import battle_mode_policy as modes
from native_map import ticks

CODE, PREPARE, STORE, CLASSIFY = 0x07110000,0x07111000,0x07112800,0x07112C00
VIEW, BIND, SUBJECT = 0x07113000,0x07114000,0x07115000
RESULT_ACTOR, RESULT_MODEL, RESULT_CAMERA, RESULT_WINNER = 0x07116000,0x07116400,0x07116800,0x07116C00
OLD_PREPARE, OLD_STORE = 0x07118000,0x0711A000
CLONES, PRIORITY, CONTROL, END = (0x0711B000,0x0711B400),0x0711C000,0x0711F000,0x07120000
SHARED_FORM = 0x0711C800
# Native flag 0xD3 lives in bank byte 26 bit 3 (sub_1DABE8 sets bank B, sub_1DAC78 ORs both).
# Native actor flag 211 (0xD3) in both flag banks (+0x1085 current, +0x10AD requested): USA bytes 4255/4295, bit 8.
_PRIORITY_INDEX, PRIORITY_FLAG_BIT = FLAG_BITS((0xD3,))
PRIORITY_FLAG_BYTES = (0x1085+_PRIORITY_INDEX, 0x10AD+_PRIORITY_INDEX)
# Native actor flags 293/294 (0x125/0x126, the presentation of an activated ultimate): USA byte 0x24, bits 5/6.
ULTIMATE_FLAG_INDEX, ULTIMATE_FLAG_MASK = FLAG_BITS((0x125, 0x126))
ULTIMATE_FLAG_BYTES = (0x1085+ULTIMATE_FLAG_INDEX, 0x10AD+ULTIMATE_FLAG_INDEX)
LAST_PRIORITY, PRIORITY_VIEWS = 40, 44
# Set for the frame when uninvolved fighters are stopped for an authored
# ultimate: the checked category forced the whole stop, or the native global
# activation stop stayed whole because nothing could narrow it. The generic
# special-pause mode never sets it, so ordinary specials keep their split
# views exactly as before.
SHARED_STOP = 60
# The authored camera a proven ultimate owner started keeps running long after
# every actor-side proof of it expires: a thrown Spirit Bomb leaves its caster
# in an ordinary action while its own cinematic plays on. This is not an
# action latch. It holds only while that exact camera record still animates,
# the owner is still a living registered fighter, no other fighter has proven
# ownership of the camera, and a bounded number of updates has not elapsed.
LATCH_OWNER, LATCH_MEMBERS, LATCH_AGE, LATCH_CAMERA = 68, 72, 76, 80
LATCH_UPDATES = ticks(900)       # 30 s of 30 Hz (European 25 Hz) updates
# 1 = one shared view for a checked transformation, stopping every bystander
# for its whole close-up; 0 = each half frames the close-up itself.
TRANSFORM_VIEW = 64
TRANSFORM_VIEWS = ('each_half','shared')
MAGIC=0x43504F31
RENDER_CALLS=(A(0x12B798),A(0x12B9F8),A(0x12BAC8))
RESULT_CALLS=(
    *((p,A(0x1DC178),RESULT_ACTOR) for p in (A(0x209F60),A(0x209F98),A(0x209FD4))),
    *((p,A(0x12B1D0),RESULT_MODEL) for p in (A(0x2171A8),A(0x2171C8),A(0x217764),A(0x21777C),A(0x217A78))),
    *((p,A(0x23DE60),RESULT_CAMERA) for p in (A(0x217A20),A(0x217A44))),
)
COOP_FUSION = 0x07117400
ULTIMATE_OWNER, ULTIMATE_STOP, ULTIMATE_FRAME = 0x0711D000,0x0711E800,0x0711EC00
NATIVE_CAMERA_OWNER = 0x0711E000
ULTIMATE_KIND, ULTIMATE_MEMBERS = 52,56
BYSTANDERS, SCRIPT_STOP = 0x0711F900,0x0711F200
FREE_MASK = 84
# The shared stop removes every nonmember from its own update, and an actor-local
# ultimate's victim is a nonmember: the reaction that ends the move can then never
# run, so the presentation renews its own ownership proof forever and the match is
# stuck with the picture still drawing. HOLD_AGE counts the consecutive updates one
# shared stop has actually held someone. Past HOLD_UPDATES the stop releases every
# fighter, drops the latched presentation, and refuses to stop anyone again for
# HOLD_RELEASE updates, so the interrupted move always gets frames to finish in.
# HOLD_OVERRUNS/HOLD_LONGEST are telemetry the watcher reads; neither gates anything.
# HOLD_BLOCK remembers the owner whose hold overran, so the same unfinishable
# presentation cannot freeze everyone again the moment its release window ends.
# It is forgotten on the first update nothing owns a shared presentation, which a
# genuinely new one always follows.
# HOLD_IDLE counts consecutive updates with no shared presentation at all: the block is
# forgotten only after HOLD_FORGET of them, so one ownerless update cannot buy a stuck
# presentation a fresh budget. HOLD_TOTAL accumulates every held update of the whole battle;
# past HOLD_MATCH this stop never holds anyone again for the rest of that match, whoever owns
# it, so a roster that keeps producing unfinishable presentations still ends up playable.
HOLD_AGE, HOLD_COOLDOWN, HOLD_OVERRUNS, HOLD_LONGEST, HOLD_BLOCK = 88, 92, 96, 100, 104
HOLD_IDLE, HOLD_TOTAL = 108, 112
# 900 matches LATCH_UPDATES: the longest presentation the authored cameras are expected to
# run (a thrown Spirit Bomb is the long case). HOLD_MATCH is three of those.
HOLD_UPDATES, HOLD_RELEASE, HOLD_FORGET, HOLD_MATCH = ticks(900), ticks(120), ticks(30), ticks(2700)
# Participant protection (beta.37). PROTECT answers the fighters a hold must leave running: the ones the
# running authored camera binds at +768/+772, plus the live reciprocal rush partner (+3732/+3736, still in
# 301..303/313..315 or about to be) of a member or of such a fighter. FOREIGN answers whether the running
# camera shows another pair's live rush, which no latch may take or keep. Telemetry only, guest-written:
# PROTECT_LAST is the last protected mask, PROTECT_UPDATES the updates that protected anyone, LATCH_REFUSED
# the latches refused or dropped for a foreign camera.
PROTECT, FOREIGN, PENDING = 0x0711A400, 0x0711A800, 0x0711AC00
PROTECT_LAST, PROTECT_UPDATES, LATCH_REFUSED = 116, 120, 124
# Native return addresses with their proven actor register and displacement.
SCRIPT_ACTORS = {
    (16,0):(A(0x1C1E2C),A(0x1D64CC),A(0x200AB4)),
    (17,0):(A(0x1C2124),A(0x1C4EA4),A(0x1D452C),A(0x1D45EC),A(0x1D4B30),A(0x1D4C74),
            A(0x1DFE74),A(0x1E16F8),A(0x1E1DB0)),
    (16,-16):(A(0x1DFDA8),),
}
SAVED=tuple(range(2,28))+(30,31)


def save(a,regs=SAVED,size=0x100):
    a.addiu(29,29,-size)
    for i,r in enumerate(regs):a.i(63,r,29,8*i)


def restore(a,regs=SAVED,size=0x100,skip=()):
    for i,r in enumerate(regs):
        if r not in skip:a.i(55,r,29,8*i)
    a.addiu(29,29,size)


def camera_running(a,reg,fail,tag):
    """reg = the native camera record; continue only while it animates.

    Exactly the truth 23DBC0 reports - its own running track, or a direct
    position override - read without calling it, without repeating its finished-track cleanup side effect.
    """
    import special_camera_arbitration as arbitration
    arbitration.pointer(a,reg,832,fail)
    a.lw(8,reg,812);a.branch(5,8,0,tag+'_running')
    a.lw(8,reg,776);a.i(12,8,8,3);a.addiu(9,0,1);a.branch(5,8,9,fail)
    a.lw(11,reg,704);arbitration.pointer(a,11,24,fail)
    a.label(tag+'_running')


def shared_owner(a,fail,tag,shared_stop=True,rush_support=True,bounded=False):
    """v0 = the actor owning one shared checked presentation, else branch.

    Ultimates answer first. A transformation only owns the shared view when
    its own checkbox and the shared preference are both set, so the each-half
    preference keeps the two close-ups the split screen already draws.

    bounded callers (everything that frames or routes the view) also answer 'nobody'
    while ultimate_stop is suppressing holds: a presentation whose hold ran past its
    bound must not keep the screen welded to a move that is never going to end. The
    stop itself is never bounded here, because its own bookkeeping needs the true owner.
    """
    if bounded:
        a.li(8,CONTROL);a.lw(9,8,HOLD_BLOCK);a.branch(5,9,0,fail)
        a.lw(9,8,HOLD_COOLDOWN);a.branch(5,9,0,fail)
        a.lw(9,8,HOLD_TOTAL);a.li(11,HOLD_MATCH);a.r(0x2B,11,9,11);a.branch(4,11,0,fail)
    if not shared_stop:
        a.li(8,CONTROL);a.lw(8,8,16);a.branch(4,8,0,fail)
        a.call(ULTIMATE_OWNER);a.branch(4,2,0,fail);a.label(tag+'_owned');return
    a.li(8,CONTROL);a.lw(8,8,16);a.branch(4,8,0,tag+'_rush' if rush_support else tag+'_form')
    a.call(ULTIMATE_OWNER);a.branch(5,2,0,tag+'_owned')
    if rush_support:
        import rush_cinematics as rush
        a.label(tag+'_rush');a.li(8,rush.CONTROL);a.lw(9,8);a.li(11,rush.MAGIC)
        a.branch(5,9,11,tag+'_form');a.call(rush.OWNER);a.branch(5,2,0,tag+'_owned')
    a.label(tag+'_form')
    a.li(8,CONTROL);a.lw(9,8,20);a.branch(4,9,0,fail)
    a.lw(9,8,TRANSFORM_VIEW);a.branch(4,9,0,fail)
    a.call(SHARED_FORM);a.branch(4,2,0,fail)
    a.label(tag+'_owned')


def gate(a,fail,combat=True):
    core.gate(a,fail)
    a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,fail)
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,fail)
    a.lw(9,8,8);a.branch(5,9,10,fail)
    a.li(9,core.PAIR+4);a.lw(9,9);a.branch(5,9,0,fail)
    a.lw(9,8,12);a.li(11,team_intro.BATTLE);a.lw(11,11);a.branch(5,9,11,fail)
    a.branch(4,11,0,fail)
    if combat:
        a.lw(9,11);a.addiu(11,0,3);a.branch(5,9,11,fail)
        a.li(9,result.RESULT);a.lw(9,9);a.branch(5,9,0,fail)


def classify():
    """a0=current action -> v0 ordinary0, ultimate1, transformation2, other3.

    Exact native1E03C8:261 is ultimate,262..315 repeats slots2,3,4.
    The loop avoids touching HI/LO in the enclosing hitstop calculation.
    """
    a=Assembler(CLASSIFY);a.addiu(8,4,-236);a.i(11,9,8,8);a.branch(5,9,0,'form')
    a.addiu(8,4,-261);a.branch(4,8,0,'ultimate')
    a.addiu(8,4,-253);a.i(11,9,8,63);a.branch(4,9,0,'other')
    a.addiu(8,4,-262);a.i(11,9,8,54);a.branch(4,9,0,'ordinary')
    a.label('mod');a.i(11,9,8,3);a.branch(5,9,0,'remainder');a.addiu(8,8,-3);a.jump('mod')
    a.label('remainder');a.addiu(9,0,2);a.branch(4,8,9,'ultimate')
    a.label('ordinary');a.move(2,0);a.jr()
    a.label('ultimate');a.addiu(2,0,1);a.jr()
    a.label('form');a.addiu(2,0,2);a.jr()
    a.label('other');a.addiu(2,0,3);a.jr()
    return a.finish()


def prepare(shared_stop=True,participants=False):
    import special_camera_arbitration as arbitration
    bail='bail' if shared_stop else 'done'
    a=Assembler(PREPARE);save(a)
    a.call(OLD_PREPARE)
    a.li(8,CONTROL);a.sw(0,8,24);a.sw(0,8,28);a.sw(0,8,32)
    if shared_stop:
        a.sw(0,8,SHARED_STOP)
        # One frame, one step of the latched presentation's bounded life.
        # This runs before the gate so a lost world, a finished battle or a
        # stopped camera releases it on the very next update.
        a.lw(16,8,LATCH_OWNER);a.branch(4,16,0,'latch_done')
        a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,'latch_drop')
        a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'latch_drop')
        a.lw(9,8,12);a.li(11,team_intro.BATTLE);a.lw(11,11);a.branch(5,9,11,'latch_drop')
        a.branch(4,11,0,'latch_drop');a.lw(9,11);a.addiu(11,0,3);a.branch(5,9,11,'latch_drop')
        a.li(9,result.RESULT);a.lw(9,9);a.branch(5,9,0,'latch_drop')
        a.lw(9,8,LATCH_AGE);a.li(11,LATCH_UPDATES);a.r(0x2B,9,9,11);a.branch(4,9,0,'latch_drop')
        a.lw(17,28,-22180);a.lw(9,8,LATCH_CAMERA);a.branch(5,9,17,'latch_drop')
        camera_running(a,17,'latch_drop','latch')
        if participants:
            # The one cinematic camera record now shows another pair's live rush: that is not
            # this owner's presentation, whatever the record's address says.
            a.addiu(4,16,-1);a.call(FOREIGN);a.branch(5,2,0,'latch_foreign')
        a.addiu(4,16,-1);a.call(continuity.LOOKUP);a.branch(4,3,0,'latch_drop')
        a.li(8,CONTROL);a.lw(9,8,LATCH_AGE);a.addiu(9,9,1);a.sw(9,8,LATCH_AGE)
        a.jump('latch_done')
        if participants:
            a.label('latch_foreign');a.li(8,CONTROL);a.lw(9,8,LATCH_REFUSED);a.addiu(9,9,1);a.sw(9,8,LATCH_REFUSED)
        a.label('latch_drop');a.li(8,CONTROL);a.sw(0,8,LATCH_OWNER);a.sw(0,8,LATCH_MEMBERS)
        a.sw(0,8,LATCH_AGE);a.sw(0,8,LATCH_CAMERA)
        a.label('latch_done');a.li(8,CONTROL)
    gate(a,'done')
    # Loading/reload ownership remains native; never release manager/scene holds.
    a.lw(8,28,-22364);a.lw(9,8,628);a.branch(5,9,0,'done')
    a.li(8,continuity.SCENE_FLAGS);a.lw(9,8);a.i(12,9,9,0x2000);a.branch(5,9,0,'done')
    a.move(16,10);a.move(17,0);a.move(18,0);a.move(19,0);a.move(20,0);a.move(21,0)
    if shared_stop:a.move(24,0)
    # s2 owners, s3 keep-stop mask, s4 protected-contact mask, s5 force-all,
    # s8 the checked ultimate presentation that stops every bystander.
    a.label('scan');a.r(0,8,0,17,2);a.li(9,core.POINTERS);a.r(0x2D,8,8,9);a.lw(22,8)
    a.r(0,8,0,17,2);a.li(9,pause.CONTROL+0x80);a.r(0x2D,8,8,9);a.lw(8,8)
    a.branch(5,8,22,bail);a.lw(8,22);a.branch(5,8,17,bail)
    a.lw(8,22,12);a.i(11,9,8,12);a.branch(4,9,0,bail)
    a.r(0,9,0,8,2);a.li(11,core.MODELS);a.r(0x2D,9,9,11);a.lw(9,9)
    a.branch(4,9,0,bail);a.lw(9,9,16);a.branch(5,8,9,bail)
    a.i(36,8,22,ULTIMATE_FLAG_BYTES[0]);a.i(36,9,22,ULTIMATE_FLAG_BYTES[1]);a.r(0x25,8,8,9);a.i(12,8,8,ULTIMATE_FLAG_MASK)
    a.branch(4,8,0,'next')
    a.addiu(23,0,1);a.r(4,23,17,23);a.r(0x25,18,18,23);a.r(0x25,20,20,23)
    a.lw(4,22,2376);a.call(CLASSIFY);a.addiu(8,0,3);a.branch(4,2,8,bail)
    a.branch(4,2,0,'ordinary')
    a.r(0,8,0,2,2);a.li(9,CONTROL+12);a.r(0x2D,8,8,9);a.lw(8,8)
    a.branch(4,8,0,'protected_pair');a.addiu(21,0,1)
    if shared_stop:
        # Record which checked category stopped everyone; the first wins, and
        # the selector decides from it whether one view or two are right.
        a.branch(5,24,0,'protected_pair');a.move(24,2)
    a.jump('protected_pair')
    a.label('ordinary');a.li(8,pause.MODE);a.lw(8,8);a.addiu(9,0,1)
    a.branch(5,8,9,'target_mode');a.addiu(21,0,1);a.jump('protected_pair')
    a.label('target_mode');a.branch(5,8,0,'protected_pair')
    a.r(0x25,19,19,23)
    a.r(0,8,0,17,2);a.li(9,core.TABLE);a.r(0x2D,8,8,9);a.lw(8,8)
    a.r(0x2B,9,8,16);a.branch(4,9,0,bail);a.addiu(9,0,1);a.r(4,9,8,9)
    a.r(0x25,19,19,9);a.r(0x25,20,20,9)
    a.label('protected_pair');a.lw(8,22,2376)
    for start in (301,313):
        a.addiu(9,8,-start);a.i(11,9,9,3);a.branch(5,9,0,'pair')
    a.jump('next')
    a.label('pair')
    for off in (3732,3736):
        a.lw(8,22,off);a.r(0x2B,9,8,16);a.branch(4,9,0,bail)
        a.addiu(9,0,1);a.r(4,9,8,9);a.r(0x25,20,20,9)
    a.label('next');a.addiu(17,17,1);a.branch(5,17,16,'scan');a.branch(4,18,0,'done')
    a.li(8,CONTROL);a.addiu(9,0,1);a.sw(9,8,24);a.sw(19,8,28);a.sw(21,8,32)
    if shared_stop:a.sw(24,8,SHARED_STOP)
    a.li(8,pause.CONTROL);a.sw(9,8,20);a.sw(19,8,24);a.sw(0,8,28);a.sw(18,8,44);a.sw(20,8,52)
    if shared_stop:
        a.jump('done')
        # An unrecognised captured world or action category leaves the whole
        # native activation stop in place. The generic pause mode may still
        # have narrowed it on its own; only record the frames where nothing
        # did, so the selector can stop restoring two ordinary viewports
        # while the fighters those viewports follow cannot act.
        a.label('bail')
        a.li(8,pause.CONTROL);a.lw(9,8,20);a.branch(5,9,0,'done')
        a.move(17,0)
        a.label('bail_scan')
        a.r(0,8,0,17,2);a.li(9,core.POINTERS);a.r(0x2D,8,8,9);a.lw(18,8)
        arbitration.pointer(a,18,0x1600,'bail_next')
        a.i(36,8,18,ULTIMATE_FLAG_BYTES[0]);a.i(36,9,18,ULTIMATE_FLAG_BYTES[1]);a.r(0x25,8,8,9);a.i(12,8,8,ULTIMATE_FLAG_MASK)
        a.branch(4,8,0,'bail_next')
        a.li(8,CONTROL);a.addiu(9,0,3);a.sw(9,8,SHARED_STOP);a.jump('done')
        a.label('bail_next');a.addiu(17,17,1);a.branch(5,17,16,'bail_scan')
    a.label('done');restore(a);a.jr()
    data=a.finish();assert len(data)<STORE-PREPARE;return data


def store():
    a=Assembler(STORE);regs=(8,9,10,11);save(a,regs,0x20)
    a.li(8,CONTROL);a.lw(9,8,24);a.branch(4,9,0,'old')
    a.lw(9,8,32);a.branch(5,9,0,'native')
    a.addiu(9,17,-1);a.addiu(10,0,1);a.r(4,10,9,10)
    a.lw(9,8,28);a.r(0x24,9,9,10);a.branch(4,9,0,'skip')
    a.li(8,pause.CONTROL);a.lw(9,8,28);a.r(0x25,9,9,10);a.sw(9,8,28)
    a.label('native');a.sw(0,16,4904);a.sw(18,16,4900);restore(a,regs,0x20);a.jr()
    a.label('skip');a.li(8,pause.CONTROL);a.lw(9,8,36);a.addiu(9,9,1);a.sw(9,8,36)
    restore(a,regs,0x20);a.jr()
    a.label('old');restore(a,regs,0x20);a.jump(OLD_STORE)
    return a.finish()


def coop_fusion():
    """Side -> consenting leader actor, only during the actual fusion action.

    The partner is an ally, so opponent/victim matching cannot identify their
    shared animation. This records no camera ownership: it merely recognises
    the exact accepted pair while both original bodies still exist.
    """
    a=Assembler(COOP_FUSION);save(a);a.move(16,4);gate(a,'no')
    a.i(11,8,16,2);a.branch(4,8,0,'no')
    a.li(8,CONTROL);a.lw(8,8,20);a.branch(4,8,0,'no')
    a.li(8,modes.CONTROL);a.lw(9,8);a.li(11,modes.MAGIC);a.branch(5,9,11,'no')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'no')
    a.lw(9,8,8);a.branch(5,9,10,'no');a.lw(9,8,12);a.addiu(11,0,modes.COOP)
    a.branch(5,9,11,'no');a.lw(9,8,16);a.addiu(11,0,2);a.branch(5,9,11,'no')
    a.lw(9,8,24);a.addiu(11,0,-1);a.branch(5,9,11,'no')
    a.lw(9,8,64);a.addiu(11,0,1);a.branch(5,9,11,'no')
    # Do not steal a manually selected spectator view or a KO successor.
    a.li(8,fresh.SUCCESSOR_CONTROL);a.r(0,9,0,16,2);a.r(0x2D,8,8,9);a.lw(9,8,8)
    a.r(0,11,0,16,1);a.branch(5,9,11,'no')
    a.li(8,core.POINTERS);a.lw(17,8);a.branch(4,17,0,'no')
    a.lw(9,17,2376);a.addiu(9,9,-241);a.i(11,9,9,2);a.branch(4,9,0,'no')
    for physical in (0,2):
        a.addiu(4,0,physical);a.call(continuity.LOOKUP);a.branch(4,3,0,'no')
    a.move(2,17);a.jump('return')
    a.label('no');a.move(2,0)
    a.label('return');restore(a,skip=(2,));a.jr()
    data=a.finish();assert len(data)<OLD_PREPARE-COOP_FUSION;return data


def view(enhanced=True):
    """a0=side -> v0 cinematic allowed. Bound rush/throw/beam stays framed."""
    a=Assembler(VIEW);save(a);a.move(16,4)
    a.call(A(0x23DBC0));a.branch(4,2,0,'no')
    if enhanced:
        a.move(4,16);a.call(camera.PARTICIPANT);a.branch(5,2,0,'participant')
        a.move(4,16);a.call(COOP_FUSION);a.branch(4,2,0,'victim')
        # The shared track must actually bind the fusing leader. An unrelated
        # special's global camera must never be copied into the partner's half.
        a.lw(8,2,12);a.i(11,9,8,12);a.branch(4,9,0,'victim')
        a.r(0,8,0,8,2);a.li(9,core.MODELS);a.r(0x2D,8,8,9);a.lw(8,8)
        a.lw(9,28,-22180);a.branch(4,9,0,'victim');a.branch(4,8,0,'victim')
        a.lw(11,9,768);a.branch(4,8,11,'yes');a.lw(11,9,772);a.branch(4,8,11,'yes')
        a.jump('victim');a.label('participant')
    else:
        a.move(4,16);a.call(camera.PARTICIPANT);a.branch(4,2,0,'victim')
    # The participant chain handles stage destruction with no actor ownership.
    a.li(8,continuity.SCENE_FLAGS);a.lw(8,8);a.i(12,8,8,0x2000);a.branch(5,8,0,'yes')
    a.li(8,fresh.SUCCESSOR_CONTROL);a.r(0,9,0,16,2);a.r(0x2D,8,8,9);a.lw(17,8,8)
    a.li(8,CONTROL);a.lw(9,8,8);a.r(0x2B,9,17,9);a.branch(4,9,0,'no')
    a.r(0,8,0,17,2);a.li(9,core.POINTERS);a.r(0x2D,8,8,9);a.lw(17,8);a.lw(4,17,2376)
    for start,count in ((301,6),(313,3)):
        a.addiu(8,4,-start);a.i(11,8,8,count);a.branch(5,8,0,'yes')
    # A grab is part of the global cinematic only through its own verified
    # pair. The participant fallback assumes a thrower's partner is slot^1,
    # so an unrelated rush binding the enemy leader took over the grab view.
    import extra_throws
    a.addiu(8,4,-183);a.i(11,8,8,5);a.branch(4,8,0,'not_throw')
    a.lw(18,28,-22180);a.branch(4,18,0,'no')
    for who in ('owner','partner'):
        if who=='partner':
            a.move(4,17);a.call(extra_throws.LOOKUP);a.branch(4,2,0,'no');a.move(8,2)
        else:
            a.move(8,17)
        a.lw(8,8,12);a.i(11,9,8,12);a.branch(4,9,0,'no')
        a.r(0,8,0,8,2);a.li(9,core.MODELS);a.r(0x2D,8,8,9);a.lw(8,8)
        a.lw(9,18,768);a.branch(4,8,9,'yes');a.lw(9,18,772);a.branch(4,8,9,'yes')
    a.jump('no')
    a.label('not_throw')
    # An activation can bind the victim before its paired action commits.
    # Classify the verified director's caster, not the victim's old hit state.
    import special_camera_arbitration as arbitration
    arbitration.emit_owned_camera(a,'view_subject')
    a.li(8,arbitration.CONTROL);a.lw(18,8,24)
    a.li(19,core.POINTERS);a.li(8,CONTROL);a.lw(20,8,8)
    a.label('camera_owner');a.lw(21,19);a.lw(8,21,12);a.branch(4,8,18,'owner_found')
    a.addiu(19,19,4);a.addiu(20,20,-1);a.branch(5,20,0,'camera_owner');a.jump('view_subject')
    a.label('owner_found');a.lw(4,21,2376)
    a.label('view_subject')
    a.call(CLASSIFY);a.branch(4,2,0,'yes');a.addiu(8,0,3);a.branch(4,2,8,'yes')
    a.r(0,8,0,2,2);a.li(9,CONTROL+12);a.r(0x2D,8,8,9);a.lw(8,8);a.branch(4,8,0,'no')
    a.label('yes');a.addiu(2,0,1);a.jump('return')
    a.label('no');a.move(2,0)
    a.label('return');restore(a,skip=(2,));a.jr()
    # A viewport whose own subject is being hit is not a participant of the
    # attacker's cinematic, so it kept its ordinary follow camera while the
    # attack played on the other half. Recognise the recorded victim of the
    # caster that currently owns the effect camera and let the ordinary
    # classification (and its checkbox) decide, exactly as for the caster.
    # Split only: single-view selection is left byte-for-byte unchanged.
    a.label('victim')
    import extra_throws
    import cinematic_contact_guard as contact
    a.call(A(0x12AB10));a.branch(4,2,0,'no');a.call(A(0x12A9E8));a.branch(5,2,0,'no')
    arbitration.emit_owned_camera(a,'no')
    a.li(8,fresh.SUCCESSOR_CONTROL);a.r(0,9,0,16,2);a.r(0x2D,8,8,9);a.lw(17,8,8)
    a.li(8,CONTROL);a.lw(22,8,8);a.r(0x2B,9,17,22);a.branch(4,9,0,'no')
    a.r(0,8,0,17,2);a.li(9,core.POINTERS);a.r(0x2D,8,8,9);a.lw(18,8)
    # Resolve the caster from the model id the arbitration recorded.
    a.li(8,arbitration.CONTROL);a.lw(19,8,24)
    a.li(20,core.POINTERS);a.move(21,0)
    a.label('victim_scan');a.lw(23,20);a.lw(8,23,12);a.branch(4,8,19,'victim_caster')
    a.addiu(20,20,4);a.addiu(21,21,1);a.branch(5,21,22,'victim_scan');a.jump('no')
    a.label('victim_caster')
    modes.emit_enemy(a,21,17,'no','victim')
    # The caster must still be inside a special; a stale pair record from an
    # earlier move must never frame an ordinary hit.
    for off in extra_throws.ACTION_FIELDS:
        a.lw(8,23,off);a.addiu(9,8,-253);a.i(11,9,9,63);a.branch(5,9,0,'victim_active')
    a.jump('no')
    a.label('victim_active')
    # Reciprocal pair record: both identities in range, distinct, naming this
    # viewport's subject and that caster, and agreeing from both sides.
    a.lw(8,18,3732);a.r(0x2B,9,8,22);a.branch(4,9,0,'no')
    a.lw(9,18,3736);a.r(0x2B,10,9,22);a.branch(4,10,0,'no')
    a.branch(4,8,9,'no')
    a.branch(4,8,17,'victim_owner');a.branch(5,9,17,'no')
    a.label('victim_owner');a.branch(4,8,21,'victim_caster_named');a.branch(5,9,21,'no')
    a.label('victim_caster_named')
    a.lw(10,23,3732);a.branch(5,10,8,'no')
    a.lw(10,23,3736);a.branch(5,10,9,'no')
    # Either the authored reaction already committed, or the native contact
    # marker says it is about to on this same update.
    a.lw(8,18,4016);a.addiu(9,0,29);a.branch(4,8,9,'victim_ok')
    a.addiu(9,0,30);a.branch(4,8,9,'victim_ok')
    contact.paired_pending(a,18,'victim_ok')
    a.jump('no')
    a.label('victim_ok');a.lw(4,23,2376);a.jump('view_subject')
    data=a.finish();assert len(data)<BIND-VIEW;return data


def selector(complete_ultimates=True,activation_cameras=True,shared_stop=True,quad_support=False,rush_support=True):
    unowned='stopped_views' if shared_stop else 'ordinary_selector'
    a=Assembler(CODE);save(a);a.call(camera.CODE);a.i(63,2,29,0xE0);a.i(63,3,29,0xE8)
    gate(a,'return')
    if quad_support:
        import multiplayer_fusion as fusion
        a.li(8,fusion.CONTROL);a.lw(9,8);a.li(11,fusion.MAGIC);a.branch(5,9,11,'not_shared_pair')
        a.call(fusion.SHARED);a.branch(4,2,0,'not_shared_pair')
        a.addiu(8,0,1);a.i(63,8,29,0xE0)
        a.move(4,0);a.call(A(0x23EF98));a.addiu(4,0,1);a.call(A(0x23EFD0))
        a.move(4,0);a.addiu(5,0,1);a.call(A(0x23EE78))
        # Model replacement commits the shared pair before the fusion's
        # final pose finishes. Keep its authenticated authored track here;
        # side0's combat camera looks at the back of that scripted pose.
        a.li(8,fusion.seats.views.SUBJECTS);a.lw(4,8);a.call(fusion.CINEMATIC)
        a.branch(4,2,0,'return');a.lw(4,28,-22180)
        a.lw(8,28,-22172);a.sw(4,8,0xC40);a.addiu(5,0,1);a.call(A(0x23E6A0))
        a.jump('return');a.label('not_shared_pair')
    if complete_ultimates:
        shared_owner(a,unowned,'select',shared_stop,rush_support,bounded=True)
        # Both humans see the one original authored ultimate. Its actor-local
        # path is already computed for side0 by PRIORITY; a director-owned
        # cinematic supplies its own full-screen record instead.
        a.move(22,3);a.addiu(8,0,1);a.i(63,8,29,0xE0)
        a.move(4,0);a.call(A(0x23EF98));a.addiu(4,0,1);a.call(A(0x23EFD0))
        a.move(4,0);a.addiu(5,0,1);a.call(A(0x23EE78))
        a.addiu(8,0,2)
        if activation_cameras:
            a.branch(4,22,8,'shared_native_camera')
            # Some ultimates start with activation priority before D3 and use
            # native position-driven cameras, rather than a director track.
            # Once an ultimate owns the shared presentation, honor the stock
            # active-camera selector instead of overwriting it with side0.
            a.call(A(0x23DBC0));a.branch(4,2,0,'return')
            a.label('shared_native_camera')
        else:a.branch(5,22,8,'return')
        a.lw(4,28,-22180);a.lw(8,28,-22172);a.sw(4,8,0xC40)
        a.addiu(5,0,1);a.call(A(0x23E6A0));a.jump('return')
        if shared_stop:
            # No owner, yet this frame still stops the fighters the viewports
            # follow: either a checked category forced the whole stop or the
            # native activation stop stayed whole. A bystander who cannot act
            # must not be shown an ordinary camera, so present the running
            # cinematic once instead of restoring two viewports. Frames with
            # no running native cinematic have nothing shared to show and
            # keep their independent views.
            a.label('stopped_views');gate(a,'return')
            a.li(8,CONTROL);a.lw(9,8,SHARED_STOP);a.branch(4,9,0,'ordinary_selector')
            # A transformation asked to stay in two halves keeps them: its own
            # close-up already fills both, so nobody is stranded.
            a.addiu(11,0,2);a.branch(5,9,11,'stopped_camera')
            a.lw(9,8,TRANSFORM_VIEW);a.branch(4,9,0,'ordinary_selector')
            a.label('stopped_camera')
            # Single view already follows the cinematic natively; only the
            # two restored viewports below can strand a stopped bystander.
            a.call(A(0x12AB10));a.branch(4,2,0,'ordinary_selector')
            a.call(A(0x12A9E8));a.branch(5,2,0,'ordinary_selector')
            a.call(A(0x23DBC0));a.branch(4,2,0,'ordinary_selector')
            a.addiu(8,0,1);a.i(63,8,29,0xE0)
            a.move(4,0);a.call(A(0x23EF98));a.addiu(4,0,1);a.call(A(0x23EFD0))
            a.move(4,0);a.addiu(5,0,1);a.call(A(0x23EE78))
            a.lw(4,28,-22180);a.lw(8,28,-22172);a.sw(4,8,0xC40)
            a.addiu(5,0,1);a.call(A(0x23E6A0));a.jump('return')
        a.label('ordinary_selector');gate(a,'return')
    # core.gate leaves the captured fighter count in t2, which the native
    # queries below clobber.
    a.move(23,10)
    a.call(A(0x12AB10));a.branch(4,2,0,'single');a.call(A(0x12A9E8));a.branch(5,2,0,'single')
    # A committed co-op fusion leaves one body that both viewports already
    # resolve to (subject publishes the fused leader for either side), so a
    # split view draws the same fighter, and the authored fusion close-up,
    # twice at half width. Ask for the single full-screen view the stock game
    # already uses for its own priority cinematics rather than touching the
    # native split-mode word, which would freeze both viewport templates.
    a.li(8,modes.CONTROL);a.lw(9,8);a.li(11,modes.MAGIC);a.branch(5,9,11,'split')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'split')
    a.lw(9,8,8);a.branch(5,9,23,'split')
    a.lw(9,8,12);a.addiu(11,0,modes.COOP);a.branch(5,9,11,'split')
    if quad_support:a.lw(9,8,16);a.i(11,11,9,3);a.branch(4,11,0,'split')
    a.lw(9,8,24);a.r(0x2B,11,9,23);a.branch(4,11,0,'split')
    # 12B6E0's result is skipped for a single view, so report one here.
    a.addiu(8,0,1);a.i(63,8,29,0xE0)
    a.move(16,0);a.move(4,16);a.call(A(0x23EF98));a.addiu(4,0,1);a.call(A(0x23EFD0))
    a.move(4,0);a.addiu(5,0,1);a.call(A(0x23EE78))
    a.move(4,16);a.call(VIEW);a.branch(4,2,0,'return')
    a.lw(8,28,-22180);a.branch(4,8,0,'return')
    a.move(4,8);a.addiu(5,0,1);a.call(A(0x23E6A0));a.jump('return')
    a.label('split')
    # Existing selector may have set full-screen templates for the chosen side.
    # Restore both ordinary camera viewport templates before the native passes.
    for side in range(2):
        a.addiu(4,0,side);a.call(A(0x23EF98))
        a.addiu(4,0,1);a.move(5,0);a.call(A(0x23EE78))
    a.move(4,0);a.call(A(0x23EF98));a.i(63,0,29,0xE0);a.jump('return')
    a.label('single');a.call(A(0x23EE08));a.i(11,8,2,2);a.branch(5,8,0,'side');a.move(2,0)
    a.label('side');a.move(16,2);a.move(4,2);a.call(VIEW);a.branch(5,2,0,'return')
    a.move(4,16);a.call(A(0x23EF98));a.addiu(4,0,1);a.call(A(0x23EFD0))
    a.move(4,0);a.addiu(5,0,1);a.call(A(0x23EE78))
    a.label('return');a.i(55,2,29,0xE0);a.i(55,3,29,0xE8);restore(a,skip=(2,3));a.jr()
    data=a.finish();assert len(data)<PREPARE-CODE;return data


def bind(complete_ultimates=True,shared_stop=True,rush_support=True):
    a=Assembler(BIND);save(a);a.move(16,4);gate(a,'native')
    if complete_ultimates:
        if shared_stop:
            shared_owner(a,'ordinary_bind','bind',rush_support=rush_support,bounded=True);a.jump('native')
        else:
            a.li(8,CONTROL);a.lw(8,8,16);a.branch(4,8,0,'ordinary_bind')
            a.call(ULTIMATE_OWNER);a.branch(5,2,0,'native')
        a.label('ordinary_bind')
    a.call(A(0x12AB10));a.branch(4,2,0,'native');a.call(A(0x12A9E8));a.branch(5,2,0,'native')
    a.lw(17,28,-22176);a.lw(18,28,-22172)
    # 23EF98 selected precisely one of the two real side camera records.
    a.addiu(8,18,0x720);a.move(19,0);a.branch(4,8,17,'side')
    a.addiu(8,18,0x9B0);a.addiu(19,0,1);a.branch(5,8,17,'native')
    a.label('side');a.move(4,19);a.call(VIEW);a.branch(4,2,0,'native')
    a.lw(20,28,-22180);a.branch(4,20,0,'native')
    a.li(21,CLONES[0]);a.r(0,8,0,19,10);a.r(0x2D,21,21,8)
    a.move(8,20);a.move(9,21);a.addiu(10,20,0x340)
    a.label('copy');a.i(55,11,8,0);a.i(55,12,8,8);a.i(63,11,9,0);a.i(63,12,9,8)
    a.addiu(8,8,16);a.addiu(9,9,16);a.branch(5,8,10,'copy')
    # Retain pose260/270; native template supplies the split viewport/projection.
    a.move(4,21);a.addiu(5,19,1);a.call(A(0x23E950))
    # 23E950 installs that template over the whole record, including the view
    # matrix at +0..+127 which the split templates do not carry. Rebuilding the
    # camera from the bound model's anchor (23EAD0 -> 23E608) then replaced the
    # authored framing with a plain look-at, so a participating viewport showed
    # the attack from the wrong place. Restore the authored view, then rebuild
    # only the VU matrices from the template projections times that view and
    # keep the cinematic's own rendered eye (23E598 also publishes gp-22176).
    a.move(8,20);a.move(9,21);a.addiu(10,20,0x80)
    a.label('view_copy');a.i(55,11,8,0);a.i(55,12,8,8);a.i(63,11,9,0);a.i(63,12,9,8)
    a.addiu(8,8,16);a.addiu(9,9,16);a.branch(5,8,10,'view_copy')
    a.move(4,21);a.addiu(5,20,544);a.call(A(0x23E598))
    a.move(4,21);a.move(5,16);a.call(A(0x23E6A0))
    a.sw(21,18,0xC40);a.sw(21,28,-22176)
    a.li(8,CONTROL);a.lw(9,8,36);a.addiu(9,9,1);a.sw(9,8,36)
    restore(a);a.jr()
    a.label('native');restore(a);a.jump(A(0x23EFD0))
    data=a.finish();assert len(data)<SUBJECT-BIND;return data


def subject(enhanced=True):
    import spectator_switch as spec
    a=Assembler(SUBJECT);save(a);a.move(16,4);gate(a,'old',combat=False)
    a.i(11,9,16,2);a.branch(4,9,0,'old')
    # A spectator's explicit choice wins in every mode and on either team. It
    # is honoured before the mode rules because Team Battle would otherwise
    # fall through to camera_successor, which rescans to the viewport's own
    # side. The lock holds for as long as that fighter lives, then is released.
    a.li(8,spec.CONTROL);a.lw(9,8);a.li(11,spec.MAGIC);a.branch(5,9,11,'no_lock')
    a.r(0,9,0,16,2);a.r(0x2D,8,8,9);a.lw(19,8,spec.FIELDS['lock'])
    a.branch(4,19,0,'no_lock');a.addiu(19,19,-1)
    a.move(4,19)
    if enhanced:
        # Enhanced spectators may deliberately select a fallen, still registered
        # body to inspect its score. Older installs retain the living-only lookup.
        import spectator_takeover as takeover
        a.li(8,spec.CONTROL);a.lw(9,8,takeover.F['version']);a.addiu(11,0,takeover.VERSION)
        a.branch(5,9,11,'living_lock');a.call(takeover.LOOKUP);a.jump('lock_checked')
        a.label('living_lock');a.call(continuity.LOOKUP)
        a.label('lock_checked');a.branch(5,3,0,'publish')
    else:
        a.call(continuity.LOOKUP);a.branch(5,3,0,'publish')
    a.li(8,spec.CONTROL);a.r(0,9,0,16,2);a.r(0x2D,8,8,9);a.sw(0,8,spec.FIELDS['lock'])
    a.label('no_lock')
    a.li(8,modes.CONTROL);a.lw(9,8);a.li(11,modes.MAGIC);a.branch(5,9,11,'old')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'old')
    a.lw(9,8,8);a.branch(5,9,10,'old');a.move(18,10)
    a.lw(17,8,12);a.branch(4,17,0,'old')
    a.li(9,fresh.SUCCESSOR_CONTROL);a.r(0,10,0,16,2);a.r(0x2D,9,9,10);a.lw(19,9,8)
    a.addiu(9,0,modes.FFA);a.branch(4,17,9,'ffa')
    a.addiu(9,0,modes.COOP);a.branch(5,17,9,'old')
    a.lw(9,8,24);a.r(0x2B,10,9,18);a.branch(4,10,0,'coop');a.move(19,9);a.jump('check')
    a.label('coop');a.i(12,9,19,1);a.branch(4,9,0,'check');a.r(0,19,0,16,1);a.jump('check')
    a.label('ffa');a.li(9,result.RESULT);a.lw(9,9);a.branch(4,9,0,'check')
    a.lw(9,8,44);a.r(0x2B,10,9,18);a.branch(4,10,0,'check');a.move(19,9)
    a.label('check');a.move(4,19);a.call(continuity.LOOKUP);a.branch(5,3,0,'publish')
    a.move(20,0)
    a.label('scan');a.addiu(8,0,modes.COOP);a.branch(5,17,8,'candidate');a.i(12,8,20,1);a.branch(5,8,0,'next')
    a.label('candidate');a.move(4,20);a.call(continuity.LOOKUP);a.branch(5,3,0,'found')
    a.label('next');a.addiu(20,20,1);a.branch(5,20,18,'scan')
    # No living ally/contestant: the prior native result/KO chain handles it.
    a.jump('old')
    a.label('found');a.move(19,20)
    a.label('publish');a.li(8,fresh.SUCCESSOR_CONTROL);a.r(0,9,0,16,2);a.r(0x2D,8,8,9)
    a.sw(19,8,8);a.li(10,core.POINTERS);a.r(0,11,0,19,2);a.r(0x2D,10,10,11);a.lw(10,10);a.sw(10,8,0x30)
    a.addiu(9,0,1);a.sw(9,8,0x20)
    restore(a,skip=(2,));a.jr()
    a.label('old');restore(a);a.jump(fresh.SUCCESSOR)
    data=a.finish();assert len(data)<RESULT_ACTOR-SUBJECT;return data


def priority(enhanced=True,complete_ultimates=True,shared_stop=True,rush_support=True):
    """Side a0 -> actual model ID for its native camera calculation.

    Checked ultimates share the authenticated owner on both views. Otherwise
    native0xD3 transformation close-ups retain the existing unique ally policy.
    Camera selection never transfers input/spectator ownership or targets.
    """
    a=Assembler(PRIORITY);save(a);a.move(16,4)
    a.call(SUBJECT);a.move(17,2)
    gate(a,'keep');a.move(18,10)
    a.i(11,9,16,2);a.branch(4,9,0,'keep')
    if complete_ultimates:
        shared_owner(a,'ordinary_priority','priority_owner',shared_stop,rush_support,bounded=True)
        a.lw(8,2,12);a.branch(4,8,17,'keep');a.move(17,8)
        a.lw(9,2);a.li(8,CONTROL);a.sw(9,8,LAST_PRIORITY)
        a.lw(9,8,PRIORITY_VIEWS);a.addiu(9,9,1);a.sw(9,8,PRIORITY_VIEWS);a.jump('keep')
        a.label('ordinary_priority')
    a.li(8,fresh.SUCCESSOR_CONTROL);a.r(0,9,0,16,2);a.r(0x2D,8,8,9);a.lw(19,8,8)
    a.r(0x2B,9,19,18);a.branch(4,9,0,'keep')
    a.li(8,core.POINTERS);a.r(0,9,0,19,2);a.r(0x2D,8,8,9);a.lw(8,8);a.branch(4,8,0,'keep')
    a.lw(8,8,12);a.branch(5,8,17,'keep')
    # Outside the checked global ultimate override, a live grab keeps its own
    # camera instead of another fighter's transformation close-up.
    import extra_throws
    a.li(8,core.POINTERS);a.r(0,9,0,19,2);a.r(0x2D,8,8,9);a.lw(4,8)
    a.call(extra_throws.LOOKUP);a.branch(5,2,0,'keep')
    if not shared_stop:
        # Split rendering follows allies only; single view switches like stock play.
        a.call(A(0x12AB10));a.move(20,2);a.branch(4,20,0,'mode_known')
        a.call(A(0x12A9E8));a.branch(4,2,0,'mode_known');a.move(20,0)
        a.label('mode_known')
    if enhanced:
        # The two fusion actors can both raise the priority bit. They belong to
        # one accepted animation, not two competing close-ups. Both humans see
        # its authored leader camera; once committed the selector uses full view.
        a.move(4,16);a.call(COOP_FUSION);a.branch(4,2,0,'priority_scan')
        a.i(36,8,2,PRIORITY_FLAG_BYTES[0]);a.i(36,9,2,PRIORITY_FLAG_BYTES[1]);a.r(0x25,8,8,9)
        a.i(12,8,8,PRIORITY_FLAG_BIT);a.branch(4,8,0,'priority_scan')
        a.lw(17,2,12);a.jump('keep')
        a.label('priority_scan')
    a.move(21,0);a.addiu(22,0,-1);a.move(23,0)
    a.label('scan')
    a.li(8,core.POINTERS);a.r(0,9,0,23,2);a.r(0x2D,8,8,9);a.lw(8,8);a.branch(4,8,0,'next')
    a.i(36,9,8,PRIORITY_FLAG_BYTES[0]);a.i(36,11,8,PRIORITY_FLAG_BYTES[1]);a.r(0x25,9,9,11)
    a.i(12,9,9,PRIORITY_FLAG_BIT);a.branch(4,9,0,'next')
    a.lw(4,8,2376);a.call(CLASSIFY);a.branch(4,2,0,'next');a.addiu(8,0,3);a.branch(4,2,8,'next')
    a.r(0,8,0,2,2);a.li(9,CONTROL+12);a.r(0x2D,8,8,9);a.lw(8,8);a.branch(4,8,0,'next')
    a.move(4,23);a.call(continuity.LOOKUP);a.branch(4,3,0,'next')
    if not shared_stop:
        a.branch(4,20,0,'qualify')
        modes.emit_enemy(a,19,23,'qualify','priority');a.jump('next')
    # Only a checked category reaches here at all, and checking it asks for
    # its camera and its pause. Split screen used to refuse an enemy's
    # close-up, so a stopped bystander kept an ordinary camera with nothing
    # framed; both halves now follow whoever the game is presenting.
    # Native ties fall back to the default side: only a unique qualifier wins.
    a.label('qualify');a.addiu(21,21,1);a.move(22,23);a.i(63,2,29,0xE0)
    a.label('next');a.addiu(23,23,1);a.branch(5,23,18,'scan')
    a.addiu(8,0,1);a.branch(5,21,8,'keep');a.branch(4,22,19,'keep')
    a.i(55,17,29,0xE0);a.li(8,CONTROL);a.sw(22,8,LAST_PRIORITY)
    a.lw(9,8,PRIORITY_VIEWS);a.addiu(9,9,1);a.sw(9,8,PRIORITY_VIEWS)
    a.label('keep');a.move(2,17);restore(a,skip=(2,));a.jr()
    data=a.finish();assert len(data)<SHARED_FORM-PRIORITY;return data


def shared_form_owner(script_stop_fix=True):
    """v0=the one living transformation owning the shared view, v1=1.

    Transformation close-ups are actor-local by design, so this needs no
    camera receipt: the native0xD3 priority flag or its activation flags,
    the transformation action family, a living registered body, and exactly
    one candidate. Ties keep the ordinary cameras, as split rendering always
    has. It publishes the same kind/member record every consumer already
    reads, so the shared view, the stop and the HUD cannot disagree.
    """
    a=Assembler(SHARED_FORM);save(a)
    a.li(8,CONTROL);a.sw(0,8,ULTIMATE_KIND);a.sw(0,8,ULTIMATE_MEMBERS)
    gate(a,'no');a.move(16,10)
    # Native leaders keep manager+628 raised during their form presentation.
    # It blocks combat updates, not camera ownership: rejecting it here split
    # P1's close-up until the reload finished. prepare still preserves holds.
    if not script_stop_fix:
        a.lw(8,28,-22364);a.lw(8,8,628);a.branch(5,8,0,'no')
    a.li(8,continuity.SCENE_FLAGS);a.lw(8,8);a.i(12,8,8,0x2000);a.branch(5,8,0,'no')
    a.li(8,CONTROL);a.lw(9,8,20);a.branch(4,9,0,'no')
    a.lw(9,8,TRANSFORM_VIEW);a.branch(4,9,0,'no')
    a.move(18,0);a.move(21,0);a.move(22,0);a.move(23,0)
    a.label('scan');a.li(8,core.POINTERS);a.r(0,9,0,18,2);a.r(0x2D,8,8,9);a.lw(19,8)
    a.branch(4,19,0,'next')
    a.i(36,8,19,PRIORITY_FLAG_BYTES[0]);a.i(36,9,19,PRIORITY_FLAG_BYTES[1]);a.r(0x25,8,8,9)
    a.i(12,8,8,PRIORITY_FLAG_BIT)
    a.i(36,9,19,ULTIMATE_FLAG_BYTES[0]);a.i(36,11,19,ULTIMATE_FLAG_BYTES[1]);a.r(0x25,9,9,11)
    a.i(12,9,9,ULTIMATE_FLAG_MASK);a.r(0x25,8,8,9)
    a.branch(4,8,0,'next')
    a.lw(4,19,2376);a.call(CLASSIFY);a.addiu(8,0,2);a.branch(5,2,8,'next')
    a.move(4,18);a.call(continuity.LOOKUP);a.branch(4,3,0,'next')
    a.addiu(21,21,1);a.move(22,19);a.move(23,18)
    a.label('next');a.addiu(18,18,1);a.branch(5,18,16,'scan')
    a.addiu(8,0,1);a.branch(5,21,8,'no')
    a.r(4,8,23,8);a.li(9,CONTROL);a.addiu(11,0,1)
    a.sw(11,9,ULTIMATE_KIND);a.sw(8,9,ULTIMATE_MEMBERS)
    a.move(2,22);a.addiu(3,0,1);a.jump('return')
    a.label('no');a.move(2,0);a.move(3,0)
    a.label('return');restore(a,skip=(2,3));a.jr()
    data=a.finish();assert len(data)<CONTROL-SHARED_FORM;return data


def ultimate_owner(native_cameras=True,activation_cameras=True,shared_stop=True,script_stop_fix=True,*,all_activations=True,
                   participants=False):
    """v0=live ultimate actor, v1=local1/director2; publishes exact members.

    No action-only latch: camera priority or authenticated native ownership
    must still be active. Stale pair fields cannot keep a match paused.
    """
    import special_camera_arbitration as arbitration
    a=Assembler(ULTIMATE_OWNER);save(a)
    if shared_stop:a.sw(0,29,224);a.sw(0,29,232)
    a.li(8,CONTROL);a.sw(0,8,ULTIMATE_KIND);a.sw(0,8,ULTIMATE_MEMBERS)
    gate(a,'no');a.move(16,10)
    # Manager stop is also raised throughout native ultimate impact scripts.
    # Camera ownership must survive it; combat holds are handled separately.
    if not script_stop_fix:
        a.lw(8,28,-22364);a.lw(8,8,628);a.branch(5,8,0,'no')
    a.li(8,continuity.SCENE_FLAGS);a.lw(8,8);a.i(12,8,8,0x2000);a.branch(5,8,0,'no')
    arbitration.emit_owned_camera(a,'native_camera' if native_cameras else 'local')
    a.li(8,arbitration.CONTROL);a.lw(17,8,24);a.move(18,0)
    if shared_stop:a.sw(17,29,232)
    if native_cameras:
        a.jump('director_scan')
        a.label('native_camera');a.call(NATIVE_CAMERA_OWNER);a.branch(4,3,0,'local')
        a.move(17,2);a.move(18,0)
        if shared_stop:a.sw(17,29,232)
    a.label('director_scan');a.li(8,core.POINTERS);a.r(0,9,0,18,2);a.r(0x2D,8,8,9);a.lw(19,8)
    a.lw(8,19,12);a.branch(5,8,17,'director_next')
    a.lw(4,19,2376);a.call(CLASSIFY);a.addiu(8,0,1);a.branch(5,2,8,'local')
    a.move(4,18);a.call(continuity.LOOKUP);a.branch(4,3,0,'unproven' if shared_stop else 'no')
    a.addiu(20,0,2);a.jump('members')
    a.label('director_next');a.addiu(18,18,1);a.branch(5,18,16,'director_scan')
    a.label('local');a.move(18,0);a.move(21,0);a.move(22,0)
    a.label('local_scan');a.li(8,core.POINTERS);a.r(0,9,0,18,2);a.r(0x2D,8,8,9);a.lw(19,8)
    a.i(36,8,19,PRIORITY_FLAG_BYTES[0]);a.i(36,9,19,PRIORITY_FLAG_BYTES[1]);a.r(0x25,8,8,9)
    a.i(12,8,8,PRIORITY_FLAG_BIT)
    if activation_cameras and native_cameras:
        a.i(36,9,19,ULTIMATE_FLAG_BYTES[0]);a.i(36,11,19,ULTIMATE_FLAG_BYTES[1]);a.r(0x25,9,9,11)
        a.i(12,9,9,ULTIMATE_FLAG_MASK);a.r(0x25,8,8,9)
    a.branch(4,8,0,'local_next')
    a.lw(4,19,2376);a.call(CLASSIFY);a.addiu(8,0,1);a.branch(5,2,8,'local_next')
    a.move(4,18);a.call(continuity.LOOKUP);a.branch(4,3,0,'local_next')
    # Stable first physical caster wins actor-local ties; every authenticated
    # simultaneous caster is retained in the participant pass below.
    a.branch(5,21,0,'local_next');a.addiu(21,0,1);a.move(22,19);a.move(23,18)
    a.label('local_next');a.addiu(18,18,1);a.branch(5,18,16,'local_scan')
    a.addiu(8,0,1);a.branch(5,21,8,'performer' if shared_stop else 'no')
    a.move(19,22);a.move(18,23);a.addiu(20,0,1)
    if shared_stop:
        a.jump('members')
        # Last resort while the game is really running an authored camera.
        # A Super Spirit Bomb binds that camera to its summoned energy model,
        # so no proof above can name a fighter, yet the move still stops the
        # match. Accept the one living performer of the ultimate family: the
        # recorded reciprocal pair names it at+3732, so the fighter being hit
        # (same family, +3732 naming the caster) can never claim the view,
        # and no other registered fighter may already own the bound camera.
        a.label('performer')
        a.lw(17,28,-22180);camera_running(a,17,'unproven','performer')
        a.move(18,0);a.move(21,0);a.move(24,0)
        a.label('performer_scan')
        a.li(8,core.POINTERS);a.r(0,9,0,18,2);a.r(0x2D,8,8,9);a.lw(19,8)
        a.branch(4,19,0,'performer_next')
        a.lw(4,19,2376);a.call(CLASSIFY);a.addiu(8,0,1);a.branch(5,2,8,'performer_next')
        a.move(4,18);a.call(continuity.LOOKUP);a.branch(4,3,0,'performer_next')
        a.move(25,0);a.lw(8,19,3732);a.lw(9,19,3736)
        a.r(0x2B,11,8,16);a.branch(4,11,0,'performer_single')
        a.r(0x2B,11,9,16);a.branch(4,11,0,'performer_single')
        a.branch(4,8,9,'performer_single')
        a.branch(5,8,18,'performer_next');a.addiu(25,9,1)
        a.label('performer_single')
        a.branch(5,21,0,'performer_next')
        a.addiu(21,0,1);a.move(22,19);a.move(23,18);a.move(24,25)
        a.label('performer_next');a.addiu(18,18,1);a.branch(5,18,16,'performer_scan')
        a.addiu(8,0,1);a.branch(5,21,8,'unproven')
        a.move(18,0)
        a.label('performer_owner')
        a.li(8,core.POINTERS);a.r(0,9,0,18,2);a.r(0x2D,8,8,9);a.lw(25,8)
        a.branch(4,25,22,'performer_owner_next')
        a.addiu(8,24,-1);a.branch(4,8,18,'performer_owner_next')
        a.lw(8,25,12);a.i(11,9,8,12);a.branch(4,9,0,'performer_owner_next')
        a.r(0,9,0,8,2);a.li(8,core.MODELS);a.r(0x2D,8,8,9);a.lw(25,8)
        a.branch(4,25,0,'performer_owner_next')
        a.lw(8,17,768);a.branch(4,8,25,'unproven');a.lw(8,17,772);a.branch(4,8,25,'unproven')
        a.label('performer_owner_next');a.addiu(18,18,1);a.branch(5,18,16,'performer_owner')
        # The fighter this performer is actually bound to advances with it.
        a.branch(4,24,0,'performer_alone')
        a.addiu(9,24,-1);a.addiu(8,0,1);a.r(4,8,9,8);a.sw(8,29,224)
        a.label('performer_alone')
        a.move(19,22);a.move(18,23);a.addiu(20,0,1)
    a.label('members');a.addiu(21,0,1);a.r(4,21,18,21)
    a.addiu(8,0,2);a.branch(5,20,8,'pair_member')
    # A verified director can bind its victim before the victim's queued
    # reaction commits. Resolve actual registered model pointers, not targets.
    a.lw(22,28,-22180);a.move(23,0)
    a.label('member_scan');a.li(8,core.POINTERS);a.r(0,9,0,23,2);a.r(0x2D,8,8,9);a.lw(24,8)
    a.lw(8,24,12);a.i(11,9,8,12);a.branch(4,9,0,'member_next')
    a.r(0,8,0,8,2);a.li(9,core.MODELS);a.r(0x2D,8,8,9);a.lw(8,8)
    a.lw(9,22,768);a.branch(4,8,9,'member');a.lw(9,22,772);a.branch(5,8,9,'member_next')
    a.label('member');a.move(4,23);a.call(continuity.LOOKUP);a.branch(4,3,0,'member_next')
    a.addiu(8,0,1);a.r(4,8,23,8);a.r(0x25,21,21,8)
    a.label('member_next');a.addiu(23,23,1);a.branch(5,23,16,'member_scan')
    a.label('pair_member');a.move(23,0)
    # The selected camera has one owner, but every live activation which can
    # assert native global hitstop must advance. Freezing an ordinary special
    # or transformation here can freeze the ultimate owner in return: each
    # waits for the other to clear its pause (captured Ultimate Gohan/Jeice activation).
    a.label('casting_scan');a.li(8,core.POINTERS);a.r(0,9,0,23,2);a.r(0x2D,8,8,9);a.lw(24,8)
    a.branch(4,24,19,'casting_member')
    a.i(36,8,24,PRIORITY_FLAG_BYTES[0]);a.i(36,9,24,PRIORITY_FLAG_BYTES[1]);a.r(0x25,8,8,9)
    a.i(12,8,8,PRIORITY_FLAG_BIT)
    if activation_cameras and native_cameras:
        a.i(36,9,24,ULTIMATE_FLAG_BYTES[0]);a.i(36,11,24,ULTIMATE_FLAG_BYTES[1]);a.r(0x25,9,9,11)
        a.i(12,9,9,ULTIMATE_FLAG_MASK);a.r(0x25,8,8,9)
    a.branch(4,8,0,'casting_next')
    a.lw(4,24,2376);a.call(CLASSIFY)
    if shared_stop and all_activations:
        a.addiu(8,0,3);a.branch(4,2,8,'casting_next')
    else:
        a.addiu(8,0,1);a.branch(5,2,8,'casting_next')
    a.move(4,23);a.call(continuity.LOOKUP);a.branch(4,3,0,'casting_next')
    a.label('casting_member');a.addiu(8,0,1);a.r(4,8,23,8);a.r(0x25,21,21,8)
    # Position-only director tracks need not bind the victim model. A live
    # reciprocal ultimate rush authenticates both native participants.
    a.lw(8,24,2376);a.addiu(9,0,303);a.branch(5,8,9,'casting_next')
    a.lw(8,24,3732);a.branch(5,8,23,'casting_next');a.lw(22,24,3736)
    a.r(0x2B,8,22,16);a.branch(4,8,0,'casting_next');a.branch(4,22,23,'casting_next')
    a.li(8,core.POINTERS);a.r(0,9,0,22,2);a.r(0x2D,8,8,9);a.lw(25,8)
    a.lw(8,25,2376);a.addiu(9,0,315);a.branch(5,8,9,'casting_next')
    a.lw(8,25,3732);a.branch(5,8,23,'casting_next');a.lw(8,25,3736);a.branch(5,8,22,'casting_next')
    a.move(4,22);a.call(continuity.LOOKUP);a.branch(4,3,0,'casting_next')
    a.addiu(8,0,1);a.r(4,8,22,8);a.r(0x25,21,21,8)
    a.label('casting_next');a.addiu(23,23,1);a.branch(5,23,16,'casting_scan')
    a.label('publish')
    if shared_stop:a.lw(9,29,224);a.r(0x25,21,21,9)
    a.li(8,CONTROL);a.sw(20,8,ULTIMATE_KIND);a.sw(21,8,ULTIMATE_MEMBERS)
    if shared_stop:
        if participants:
            # An actor-local proof says nothing about which presentation the one camera record is
            # running. While it shows another pair's live rush, this update's ownership stands, but
            # no latch may outlive the owner's own proof (s1c: a latch on the rush camera held the
            # rush pair until the 900-update bound).
            a.addiu(9,0,1);a.branch(5,20,9,'latch')
            a.move(4,18);a.call(FOREIGN);a.branch(4,2,0,'latch')
            a.li(8,CONTROL);a.lw(9,8,LATCH_OWNER);a.addiu(11,18,1);a.branch(5,9,11,'latch_refused')
            a.sw(0,8,LATCH_OWNER);a.sw(0,8,LATCH_MEMBERS);a.sw(0,8,LATCH_AGE);a.sw(0,8,LATCH_CAMERA)
            a.label('latch_refused');a.lw(9,8,LATCH_REFUSED);a.addiu(9,9,1);a.sw(9,8,LATCH_REFUSED)
            a.jump('published')
            a.label('latch');a.li(8,CONTROL)
        # Latch this proven presentation so the rest of its authored camera
        # survives the moment every actor-side proof of it expires.
        a.addiu(9,18,1);a.sw(9,8,LATCH_OWNER);a.sw(21,8,LATCH_MEMBERS)
        a.sw(0,8,LATCH_AGE);a.lw(9,28,-22180);a.sw(9,8,LATCH_CAMERA)
        if participants:a.label('published')
    a.move(2,19);a.move(3,20);a.jump('return')
    if shared_stop:
        # Nothing proves an owner now. The same camera record may still be
        # animating the presentation a proven owner started; keep it until it
        # stops, its owner falls, another fighter proves ownership, or the
        # bounded lifetime that `prepare` counts runs out.
        a.label('unproven')
        a.li(16,CONTROL);a.lw(18,16,LATCH_OWNER);a.branch(4,18,0,'no')
        a.addiu(18,18,-1)
        a.lw(17,28,-22180);a.lw(8,16,LATCH_CAMERA);a.branch(5,8,17,'no')
        camera_running(a,17,'no','latched')
        if participants:
            # Another pair's live rush on the camera: drop the latch so it cannot revive.
            a.move(4,18);a.call(FOREIGN);a.branch(4,2,0,'latched_own')
            a.li(8,CONTROL);a.sw(0,8,LATCH_OWNER);a.sw(0,8,LATCH_MEMBERS);a.sw(0,8,LATCH_AGE);a.sw(0,8,LATCH_CAMERA)
            a.lw(9,8,LATCH_REFUSED);a.addiu(9,9,1);a.sw(9,8,LATCH_REFUSED);a.jump('no')
            a.label('latched_own')
        a.li(8,core.POINTERS);a.r(0,9,0,18,2);a.r(0x2D,8,8,9);a.lw(19,8)
        a.branch(4,19,0,'no')
        a.move(4,18);a.call(continuity.LOOKUP);a.branch(4,3,0,'no')
        # A camera another fighter has actually proven is never inherited.
        a.lw(8,29,232);a.branch(4,8,0,'latched_owned')
        a.lw(9,19,12);a.branch(5,8,9,'no')
        a.label('latched_owned')
        a.li(8,CONTROL);a.lw(21,8,LATCH_MEMBERS);a.addiu(9,0,1)
        a.sw(9,8,ULTIMATE_KIND);a.sw(21,8,ULTIMATE_MEMBERS)
        a.move(2,19);a.addiu(3,0,1);a.jump('return')
    a.label('no');a.move(2,0);a.move(3,0)
    a.label('return');restore(a,skip=(2,3));a.jr()
    data=a.finish();assert len(data)<NATIVE_CAMERA_OWNER-ULTIMATE_OWNER;return data


def native_camera_owner():
    """v0=actual model ID,v1=valid for an active native-owned camera.

    Native starts may legitimately bypass the arbitration token while loading
    or temporarily aliased. Model D7/D8/D9 tracks do not use that token at all.
    Prove the current track and actual model binding, never a stale action or
    merely the existence of an unrelated global cinematic.
    """
    import special_camera_arbitration as arbitration
    a=Assembler(NATIVE_CAMERA_OWNER);save(a)
    gate(a,'no');a.move(16,10)
    a.lw(17,28,-22180);arbitration.pointer(a,17,832,'no')
    a.lw(8,17,812);a.branch(5,8,0,'no')
    a.lw(8,17,776);a.i(12,8,8,3);a.addiu(9,0,1);a.branch(5,8,9,'no')
    a.lw(18,17,704);arbitration.pointer(a,18,24,'no')
    a.li(8,arbitration.DIRECTOR);a.lw(19,8);arbitration.pointer(a,19,28,'asset')
    a.lw(8,19,12);a.addiu(9,0,1);a.branch(5,8,9,'asset')
    a.lw(8,19);a.branch(5,8,18,'asset')
    a.lw(20,19,4);a.i(11,8,20,12);a.branch(4,8,0,'asset')
    a.lw(8,19,24);a.branch(5,8,20,'asset')
    a.li(8,core.MODELS);a.r(0,9,0,20,2);a.r(0x2D,8,8,9);a.lw(21,8)
    arbitration.pointer(a,21,0x1670,'asset')
    a.lw(8,21,16);a.branch(5,8,20,'asset')
    a.lw(8,17,772);a.branch(4,8,21,'yes')
    # 12F5F0 binds the caster specifically at+772; an old director cannot
    # claim a replacement throw/transformation camera bound at+768.
    a.label('asset');a.move(22,0)
    a.label('scan');a.li(8,core.POINTERS);a.r(0,9,0,22,2);a.r(0x2D,8,8,9);a.lw(23,8)
    arbitration.pointer(a,23,0x1600,'next')
    a.lw(20,23,12);a.i(11,8,20,12);a.branch(4,8,0,'next')
    a.li(8,core.MODELS);a.r(0,9,0,20,2);a.r(0x2D,8,8,9);a.lw(21,8)
    arbitration.pointer(a,21,0x1670,'next')
    a.lw(8,21,16);a.branch(5,8,20,'next')
    for off,bound in ((0x908,772),(0x90C,772),(0x910,768)):
        following=f'asset_{off:X}'
        a.lw(8,21,off);a.branch(5,8,18,following)
        a.lw(8,17,bound);a.branch(4,8,21,'yes');a.label(following)
    a.label('next');a.addiu(22,22,1);a.branch(5,22,16,'scan')
    a.label('no');a.move(2,0);a.move(3,0);a.jump('return')
    a.label('yes');a.move(2,20);a.addiu(3,0,1)
    a.label('return');restore(a,skip=(2,3));a.jr()
    data=a.finish();assert len(data)<ULTIMATE_STOP-NATIVE_CAMERA_OWNER;return data


def ultimate_stop(shared_stop=True,rush_support=True,participants=False):
    """Maintain checked cinematic pause after native activation flags expire.

    Bounded: see HOLD_AGE. A presentation that never ends releases everyone after
    HOLD_UPDATES consecutive holding updates. Nobody is held again during the next
    HOLD_RELEASE updates, nor while HOLD_BLOCK is live (until HOLD_FORGET updates pass
    with no presentation at all), nor at all once the battle has spent HOLD_MATCH
    updates holding fighters - whoever owns it and whatever character it is.
    """
    a=Assembler(ULTIMATE_STOP);save(a)
    # The release window runs before ownership: a stuck presentation keeps proving
    # itself every update, so only a check that ignores the proof can end the hold.
    a.li(8,CONTROL)
    # A battle that has already spent HOLD_MATCH updates holding fighters keeps its cameras
    # but stops pausing anyone: no sequence of presentations can add up to a stuck match.
    a.lw(9,8,HOLD_TOTAL);a.li(11,HOLD_MATCH);a.r(0x2B,11,9,11);a.branch(4,11,0,'hold_off')
    a.lw(9,8,HOLD_COOLDOWN);a.branch(4,9,0,'hold_owner')
    a.addiu(9,9,-1);a.sw(9,8,HOLD_COOLDOWN);a.sw(0,8,HOLD_AGE);a.jump('done')
    a.label('hold_owner')
    shared_owner(a,'hold_idle','stop',shared_stop,rush_support)
    a.li(8,CONTROL);a.sw(0,8,HOLD_IDLE)
    # Any live block suppresses every hold, not just the owner that overran: a second fighter
    # must not be able to freeze the match again with a fresh budget one update later.
    a.lw(11,8,HOLD_BLOCK);a.branch(5,11,0,'done')
    a.lw(9,8,HOLD_AGE);a.addiu(9,9,1);a.sw(9,8,HOLD_AGE)
    a.lw(11,8,HOLD_TOTAL);a.addiu(11,11,1);a.sw(11,8,HOLD_TOTAL)
    a.lw(11,8,HOLD_LONGEST);a.r(0x2B,11,11,9);a.branch(4,11,0,'hold_counted')
    a.sw(9,8,HOLD_LONGEST)
    a.label('hold_counted');a.li(11,HOLD_UPDATES);a.r(0x2B,11,9,11);a.branch(5,11,0,'hold_apply')
    # Overrun: drop the presentation and let every fighter advance again.
    a.addiu(11,0,HOLD_RELEASE);a.sw(11,8,HOLD_COOLDOWN);a.sw(0,8,HOLD_AGE);a.sw(2,8,HOLD_BLOCK)
    a.lw(11,8,HOLD_OVERRUNS);a.addiu(11,11,1);a.sw(11,8,HOLD_OVERRUNS)
    a.sw(0,8,LATCH_OWNER);a.sw(0,8,LATCH_MEMBERS);a.sw(0,8,LATCH_AGE);a.sw(0,8,LATCH_CAMERA)
    a.sw(0,8,ULTIMATE_KIND);a.sw(0,8,ULTIMATE_MEMBERS);a.sw(0,8,SHARED_STOP);a.jump('done')
    a.label('hold_off');a.sw(0,8,HOLD_AGE);a.jump('done')
    # Nothing owns a shared presentation: forget the block only after HOLD_FORGET such updates.
    a.label('hold_idle');a.li(8,CONTROL);a.sw(0,8,HOLD_AGE)
    a.lw(9,8,HOLD_IDLE);a.addiu(9,9,1);a.sw(9,8,HOLD_IDLE)
    a.li(11,HOLD_FORGET);a.r(0x2B,11,9,11);a.branch(5,11,0,'done')
    a.sw(0,8,HOLD_BLOCK);a.jump('done')
    a.label('hold_apply')
    # participants: the fighters the presentation itself needs are never held (PROTECT).
    if participants:a.call(PROTECT)
    a.li(8,CONTROL);a.lw(16,8,8);a.lw(17,8,ULTIMATE_MEMBERS)
    if participants:a.r(0x25,17,17,2)
    a.move(18,0)
    a.label('actor');a.addiu(8,0,1);a.r(4,8,18,8);a.r(0x24,8,8,17);a.branch(5,8,0,'next')
    a.li(8,core.POINTERS);a.r(0,9,0,18,2);a.r(0x2D,8,8,9);a.lw(8,8)
    # Do not shorten native impact timers, alter pending timers, or interfere
    # with the cast/victim state machine. One tick expires naturally on exit.
    a.lw(9,8,4896);a.branch(5,9,0,'next');a.addiu(9,0,1);a.sw(9,8,4896)
    a.label('next');a.addiu(18,18,1);a.branch(5,18,16,'actor')
    a.label('done');restore(a);a.jr()
    data=a.finish();assert len(data)<ULTIMATE_FRAME-ULTIMATE_STOP;return data


def protect():
    """v0 = fighters the running presentation needs that are not members; never holds anyone itself.

    P1: every registered fighter whose model the running authored camera binds at +768/+772 (the
    victim of an actor-local ultimate is a nonmember, and holding it froze the reaction that ends the
    move). P2: the reciprocal partner of a member or P1 fighter, while that partner is live in the
    native paired families (cinematic_contact_guard.paired_pending): stale pair fields alone never
    exempt anyone. Telemetry: PROTECT_LAST/PROTECT_UPDATES.
    """
    import special_camera_arbitration as arbitration
    a=Assembler(PROTECT);save(a)
    a.li(8,CONTROL);a.lw(16,8,8);a.lw(17,8,ULTIMATE_MEMBERS);a.move(18,0)
    # s0 count, s1 members, s2 protected mask, s3 camera, s4 index, s5 actor, s6/s7 pair, t8 partner, t9 its actor
    a.lw(19,28,-22180);camera_running(a,19,'pairs','protect_camera')
    a.move(20,0)
    a.label('bound_scan')
    a.li(8,core.POINTERS);a.r(0,9,0,20,2);a.r(0x2D,8,8,9);a.lw(21,8)
    arbitration.pointer(a,21,0x1600,'bound_next')
    a.lw(8,21,12);a.i(11,9,8,12);a.branch(4,9,0,'bound_next')
    a.r(0,9,0,8,2);a.li(8,core.MODELS);a.r(0x2D,8,8,9);a.lw(8,8);a.branch(4,8,0,'bound_next')
    a.lw(9,19,768);a.branch(4,8,9,'bound_yes');a.lw(9,19,772);a.branch(5,8,9,'bound_next')
    a.label('bound_yes');a.addiu(9,0,1);a.r(4,9,20,9);a.r(0x25,18,18,9)
    a.label('bound_next');a.addiu(20,20,1);a.branch(5,20,16,'bound_scan')
    a.label('pairs');a.move(20,0)
    a.label('pair_scan')
    a.r(0x25,8,17,18);a.addiu(9,0,1);a.r(4,9,20,9);a.r(0x24,8,8,9);a.branch(4,8,0,'pair_next')
    a.li(8,core.POINTERS);a.r(0,9,0,20,2);a.r(0x2D,8,8,9);a.lw(21,8)
    arbitration.pointer(a,21,0x1600,'pair_next')
    a.lw(22,21,3732);a.lw(23,21,3736)
    a.r(0x2B,8,22,16);a.branch(4,8,0,'pair_next');a.r(0x2B,8,23,16);a.branch(4,8,0,'pair_next')
    a.branch(4,22,23,'pair_next')
    a.move(24,23);a.branch(4,22,20,'pair_partner')
    a.move(24,22);a.branch(5,23,20,'pair_next')
    a.label('pair_partner')
    a.li(8,core.POINTERS);a.r(0,9,0,24,2);a.r(0x2D,8,8,9);a.lw(25,8)
    arbitration.pointer(a,25,0x1600,'pair_next')
    a.lw(8,25,3732);a.branch(5,8,22,'pair_next');a.lw(8,25,3736);a.branch(5,8,23,'pair_next')
    a.move(4,25);a.call(PENDING);a.branch(4,2,0,'pair_next')
    a.addiu(9,0,1);a.r(4,9,24,9);a.r(0x25,18,18,9)
    a.label('pair_next');a.addiu(20,20,1);a.branch(5,20,16,'pair_scan')
    # v0 = P & ~members, without nor.
    a.r(0x24,2,18,17);a.r(0x26,2,2,18);a.branch(4,2,0,'done')
    a.li(8,CONTROL);a.sw(2,8,PROTECT_LAST);a.lw(9,8,PROTECT_UPDATES);a.addiu(9,9,1);a.sw(9,8,PROTECT_UPDATES)
    a.label('done');restore(a,skip=(2,));a.jr()
    data=a.finish();assert len(data)<FOREIGN-PROTECT;return data


def foreign():
    """a0 = owner index -> v0 = 1 while the running authored camera shows another pair's live rush.

    The camera binds (+768/+772) a registered fighter X other than the owner whose reciprocal pair
    (+3732/+3736) is valid, agrees from both sides, does not contain the owner, and is live
    (paired_pending of X or of its partner). The owner's own rush pair is never foreign.
    """
    import special_camera_arbitration as arbitration
    a=Assembler(FOREIGN);save(a);a.move(16,4)
    a.li(8,CONTROL);a.lw(17,8,8)
    a.lw(19,28,-22180);camera_running(a,19,'no','foreign_camera')
    a.move(20,0)
    a.label('scan');a.branch(4,20,16,'next')
    a.li(8,core.POINTERS);a.r(0,9,0,20,2);a.r(0x2D,8,8,9);a.lw(21,8)
    arbitration.pointer(a,21,0x1600,'next')
    a.lw(8,21,12);a.i(11,9,8,12);a.branch(4,9,0,'next')
    a.r(0,9,0,8,2);a.li(8,core.MODELS);a.r(0x2D,8,8,9);a.lw(8,8);a.branch(4,8,0,'next')
    a.lw(9,19,768);a.branch(4,8,9,'bound');a.lw(9,19,772);a.branch(5,8,9,'next')
    a.label('bound');a.lw(22,21,3732);a.lw(23,21,3736)
    a.r(0x2B,8,22,17);a.branch(4,8,0,'next');a.r(0x2B,8,23,17);a.branch(4,8,0,'next')
    a.branch(4,22,23,'next');a.branch(4,22,16,'next');a.branch(4,23,16,'next')
    a.move(24,23);a.branch(4,22,20,'partner')
    a.move(24,22);a.branch(5,23,20,'next')
    a.label('partner')
    a.li(8,core.POINTERS);a.r(0,9,0,24,2);a.r(0x2D,8,8,9);a.lw(25,8)
    arbitration.pointer(a,25,0x1600,'next')
    a.lw(8,25,3732);a.branch(5,8,22,'next');a.lw(8,25,3736);a.branch(5,8,23,'next')
    a.move(4,21);a.call(PENDING);a.branch(5,2,0,'yes')
    a.move(4,25);a.call(PENDING);a.branch(5,2,0,'yes')
    a.label('next');a.addiu(20,20,1);a.branch(5,20,17,'scan')
    a.label('no');a.move(2,0);a.jump('return')
    a.label('yes');a.addiu(2,0,1)
    a.label('return');restore(a,skip=(2,));a.jr()
    data=a.finish();assert len(data)<PENDING-FOREIGN;return data


def pending():
    """a0 = actor -> v0 = 1 while it is live in a native paired family (cinematic_contact_guard.paired_pending:
    301..303/313..315 current or requested, or the rush-contact flag pair). Leaf; clobbers t0/t1 only."""
    import cinematic_contact_guard as contact
    a=Assembler(PENDING)
    contact.paired_pending(a,4,'yes')
    a.move(2,0);a.jr()
    a.label('yes');a.addiu(2,0,1);a.jr()
    data=a.finish();assert len(data)<CLONES[0]-PENDING;return data


def ultimate_frame(script_stop_fix=True):
    a=Assembler(ULTIMATE_FRAME);a.addiu(29,29,-16);a.i(63,31,29,0)
    save(a,pause.SAVED,0x100);a.call(PREPARE);restore(a,pause.SAVED,0x100)
    a.call(pause.NATIVE)
    if script_stop_fix:a.call(BYSTANDERS)
    a.call(ULTIMATE_STOP)
    a.i(55,31,29,0);a.addiu(29,29,16);a.jr()
    data=a.finish();assert len(data)<CONTROL-ULTIMATE_FRAME;return data


def bystanders(rush_support=True):
    """Publish an unchecked ultimate's living nonparticipants once per update."""
    a=Assembler(BYSTANDERS);save(a)
    a.li(8,CONTROL);a.sw(0,8,FREE_MASK);a.lw(9,8,16);a.branch(5,9,0,'done')
    if rush_support:
        import rush_cinematics as rush
        a.li(8,rush.CONTROL);a.lw(9,8);a.li(11,rush.MAGIC);a.branch(5,9,11,'rush_done')
        a.call(rush.OWNER);a.branch(5,2,0,'done');a.label('rush_done')
    a.call(ULTIMATE_OWNER);a.branch(4,2,0,'done')
    a.li(8,CONTROL);a.lw(16,8,8);a.lw(17,8,ULTIMATE_MEMBERS);a.move(18,0);a.move(19,0)
    a.label('scan');a.addiu(8,0,1);a.r(4,20,18,8);a.r(0x24,8,20,17);a.branch(5,8,0,'next')
    a.move(4,18);a.call(continuity.LOOKUP);a.branch(4,3,0,'next')
    # A concurrent checked transformation still owns its own native stop.
    a.li(8,core.POINTERS);a.r(0,9,0,18,2);a.r(0x2D,8,8,9);a.lw(8,8)
    a.lw(9,8,2376);a.addiu(9,9,-236);a.i(11,9,9,8);a.branch(4,9,0,'free')
    a.li(8,CONTROL);a.lw(9,8,20);a.branch(5,9,0,'done');a.jump('next')
    a.label('free');a.r(0x25,19,19,20)
    a.label('next');a.addiu(18,18,1);a.branch(5,18,16,'scan')
    a.li(8,CONTROL);a.sw(19,8,FREE_MASK)
    a.label('done');restore(a);a.jr();data=a.finish();assert len(data)<END-BYSTANDERS;return data


def script_stop():
    """Narrow only actor-local native script stops; never change the manager.

    Rendering, loading, scene scripts, RNG and unknown callers retain the
    original answer. Explicit actor identities make nested/aliased calls fail
    closed, and hitstop on the caster/victim remains untouched.
    """
    a=Assembler(SCRIPT_STOP);regs=tuple(range(8,16));save(a,regs,0x80)
    a.lw(8,28,-22364);a.lw(2,8,628);a.branch(4,2,0,'return')
    a.li(8,CONTROL);a.lw(9,8);a.li(10,MAGIC);a.branch(5,9,10,'return')
    a.lw(9,8,4);a.lw(10,28,-22364);a.branch(5,9,10,'return')
    a.lw(12,8,FREE_MASK);a.branch(4,12,0,'return');a.lw(9,8,16);a.branch(5,9,0,'return')
    a.li(9,core.MODE);a.lw(10,9);a.addiu(11,0,1);a.branch(5,10,11,'return')
    a.lw(10,9,4);a.lw(11,8,8);a.branch(5,10,11,'return')
    a.lw(10,8,12);a.li(9,team_intro.BATTLE);a.lw(9,9);a.branch(5,10,9,'return')
    a.branch(4,10,0,'return');a.lw(10,10);a.addiu(11,0,3);a.branch(5,10,11,'return')
    a.li(9,result.RESULT);a.lw(9,9);a.branch(5,9,0,'return')
    a.li(9,continuity.SCENE_FLAGS);a.lw(9,9);a.i(12,9,9,0x2000);a.branch(5,9,0,'return')
    a.li(9,core.PAIR+4);a.lw(9,9);a.branch(5,9,0,'return')
    for index,((reg,offset),callers) in enumerate(SCRIPT_ACTORS.items()):
        for caller in callers:a.li(9,caller);a.branch(4,31,9,f'actor{index}')
    a.jump('return')
    for index,(reg,offset) in enumerate(SCRIPT_ACTORS):
        a.label(f'actor{index}');a.addiu(13,reg,offset);a.jump('check')
    a.label('check');a.li(9,0x100000);a.r(0x2B,9,13,9);a.branch(5,9,0,'return')
    a.li(9,0x07FFE000);a.r(0x2B,9,13,9);a.branch(4,9,0,'return')
    a.lw(14,13);a.lw(9,8,8);a.r(0x2B,9,14,9);a.branch(4,9,0,'return')
    a.li(9,core.POINTERS);a.r(0,10,0,14,2);a.r(0x2D,9,9,10);a.lw(9,9);a.branch(5,9,13,'return')
    a.addiu(9,0,1);a.r(4,9,14,9);a.r(0x24,9,9,12);a.branch(4,9,0,'return');a.move(2,0)
    a.label('return');restore(a,regs,0x80);a.jr();data=a.finish();assert len(data)<BYSTANDERS-SCRIPT_STOP;return data


def result_winner():
    """Native side a0 -> actual FFA winner actor v0/model ID v1, or v0=0.

    The result script keeps its two logical voice channels. Only audited
    actor/model lookups for the winning channel use the surviving contestant.
    Ordinary battle, intro, losing-side and unknown captures remain native.
    """
    a=Assembler(RESULT_WINNER);gate(a,'no',combat=False)
    a.i(11,9,4,2);a.branch(4,9,0,'no')
    a.li(8,result.RESULT);a.lw(9,8);a.addiu(9,9,-1);a.i(11,9,9,2);a.branch(4,9,0,'no')
    a.li(8,modes.CONTROL);a.lw(9,8);a.li(11,modes.MAGIC);a.branch(5,9,11,'no')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'no')
    a.lw(9,8,8);a.branch(5,9,10,'no')
    a.lw(9,8,12);a.addiu(11,0,modes.FFA);a.branch(5,9,11,'no')
    a.lw(12,8,44);a.r(0x2B,9,12,10);a.branch(4,9,0,'no')
    a.i(12,9,12,1);a.branch(5,9,4,'no')
    a.lw(9,8,20);a.addiu(11,0,1);a.r(4,11,12,11);a.r(0x24,9,9,11);a.branch(4,9,0,'no')
    a.li(8,core.POINTERS);a.r(0,9,0,12,2);a.r(0x2D,8,8,9);a.lw(2,8)
    for reg in (2,):
        a.i(12,9,reg,3);a.branch(5,9,0,'no')
        a.li(11,0x100000);a.r(0x2B,9,reg,11);a.branch(5,9,0,'no')
        a.li(11,0x07FFF000);a.r(0x2B,9,reg,11);a.branch(4,9,0,'no')
    a.lw(9,2);a.branch(5,9,12,'no')
    a.lw(3,2,12);a.i(11,9,3,12);a.branch(4,9,0,'no')
    a.li(8,core.MODELS);a.r(0,9,0,3,2);a.r(0x2D,8,8,9);a.lw(8,8)
    a.i(12,9,8,3);a.branch(5,9,0,'no')
    a.li(11,0x100000);a.r(0x2B,9,8,11);a.branch(5,9,0,'no')
    a.li(11,0x07FFF000);a.r(0x2B,9,8,11);a.branch(4,9,0,'no')
    a.lw(9,8,16);a.branch(5,9,3,'no');a.jr()
    a.label('no');a.move(2,0);a.move(3,0);a.jr()
    data=a.finish();assert len(data)<OLD_PREPARE-RESULT_WINNER;return data


def result_bridge(base,native,kind):
    a=Assembler(base);save(a);a.call(RESULT_WINNER);a.branch(4,2,0,'native')
    if kind=='camera':
        a.move(4,3);restore(a,skip=(4,));a.jump(native)
    else:
        if kind=='model':a.move(2,3)
        restore(a,skip=(2,));a.jr()
    a.label('native');restore(a);a.jump(native)
    data=a.finish();assert len(data)<0x400;return data


def program(enhanced=True,*,complete_ultimates=True,native_cameras=True,activation_cameras=True,shared_stop=True,script_stop_fix=True,rush_support=True,
            participants=False):
    """participants=False is exactly the beta.36 emission (old receipts and installs); build_memory always
    asks for participants=True, which adds PROTECT/FOREIGN and their call sites."""
    old_prep=fresh.rebound(pause.prepare_code,PREPARE=OLD_PREPARE)(legacy=False)
    old_store=fresh.rebound(pause.store_code,STORE=OLD_STORE)(legacy=False)
    assert OLD_STORE+len(old_store)<=PROTECT
    activation_cameras=activation_cameras and native_cameras and complete_ultimates
    shared_stop=shared_stop and activation_cameras
    participants=participants and complete_ultimates
    parts=[(CODE,selector(complete_ultimates,activation_cameras,shared_stop,rush_support=rush_support)),(PREPARE,prepare(shared_stop,participants and shared_stop)),(STORE,store()),(CLASSIFY,classify()),
            (VIEW,view(enhanced)),(BIND,bind(complete_ultimates,shared_stop,rush_support)),(SUBJECT,subject(enhanced)),(PRIORITY,priority(enhanced,complete_ultimates,shared_stop,rush_support)),
            (RESULT_ACTOR,result_bridge(RESULT_ACTOR,A(0x1DC178),'actor')),
            (RESULT_MODEL,result_bridge(RESULT_MODEL,A(0x12B1D0),'model')),
            (RESULT_CAMERA,result_bridge(RESULT_CAMERA,A(0x23DE60),'camera')),
            (RESULT_WINNER,result_winner()),
            (OLD_PREPARE,old_prep),(OLD_STORE,old_store)] + ([(COOP_FUSION,coop_fusion())] if enhanced else [])
    if complete_ultimates:
        parts += [(ULTIMATE_OWNER,ultimate_owner(native_cameras,activation_cameras,shared_stop,script_stop_fix,
                                                 participants=participants)),
                  (ULTIMATE_STOP,ultimate_stop(shared_stop,rush_support,participants)),(ULTIMATE_FRAME,ultimate_frame(script_stop_fix))]
        if native_cameras:parts.append((NATIVE_CAMERA_OWNER,native_camera_owner()))
        if shared_stop:parts.append((SHARED_FORM,shared_form_owner(script_stop_fix)))
        if script_stop_fix:parts += [(SCRIPT_STOP,script_stop()),(BYSTANDERS,bystanders(rush_support))]
        if participants:parts += [(PROTECT,protect()),(PENDING,pending())]
        if participants and shared_stop:parts.append((FOREIGN,foreign()))
    return parts


def hooks(complete_ultimates=True,script_stop_fix=True):
    jump=lambda p:struct.pack('<2I',(2<<26)|(p>>2),0)
    out=[(leader.HOOK,jump(CODE)),(pause.PREPARE,jump(PREPARE)),(pause.STORE,jump(STORE))]
    out += [(p,struct.pack('<I',(3<<26)|(BIND>>2))) for p in RENDER_CALLS]
    out += [(fresh.successor.HOOK,struct.pack('<I',(3<<26)|(PRIORITY>>2)))]
    out += [(p,struct.pack('<I',(3<<26)|(target>>2))) for p,_,target in RESULT_CALLS]
    if complete_ultimates:
        out += [(pause.FRAME,jump(ULTIMATE_FRAME))]
        if script_stop_fix:out += [(A(0x1D63A8),jump(SCRIPT_STOP))]
    return out


def validate_memory(ram,manager=None,count=None):
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager=u(core.ACTORS) if manager is None else manager
    count=u(core.MODE+4) if count is None else count
    if struct.unpack_from('<4I',ram,CONTROL)!=(MAGIC,manager,count,u(team_intro.BATTLE)):
        raise ValueError('Cinematic policy belongs to another capture')
    recognized=complete=None
    # participants=True is the beta.37 emission; False is every earlier one, upgraded in place by build_memory.
    for options in [(c,n,e,a,s,f,r,q) for c in (True,False) for n in ((True,False) if c else (False,))
                    for e in (True,False) for a in ((True,False) if n else (False,))
                    for s in ((True,False) if a else (False,)) for f in (True,False) for r in (True,False)
                    for q in ((True,False) if c else (False,))]:
        complete,native_cameras,enhanced,activation,shared,stop_fix,rush_support,participants=options
        candidate=program(enhanced,complete_ultimates=complete,native_cameras=native_cameras,
                          activation_cameras=activation,shared_stop=shared,script_stop_fix=stop_fix,rush_support=rush_support,
                          participants=participants)+hooks(complete,stop_fix)
        import four_player_mode
        candidate=[(p,four_player_mode.dependency_override(ram,p,b)) for p,b in candidate]
        if all(ram[p:p+len(data)]==data for p,data in candidate):
            recognized=candidate;break
        # The previous shipped classifier differs only in its participant
        # pass. Match the complete old program, including viewport overrides,
        # at the capture's capacity; do not strand old 3/4-player checkpoints.
        if complete and not participants and all(ram[p:p+len(data)]==data for p,data in candidate if p!=ULTIMATE_OWNER):
            previous=ultimate_owner(native_cameras,activation,shared,stop_fix,all_activations=False)
            if ram[ULTIMATE_OWNER:ULTIMATE_OWNER+len(previous)]==previous:
                recognized=[(p,previous if p==ULTIMATE_OWNER else data) for p,data in candidate];break
    if recognized is None and not TRANSLATED:  # USA-only frozen emissions
        import json
        # Captures built before a shipped emitter change stay upgradeable: each frozen record is
        # one exact prior emission, never a relaxation of the current one.
        for legacy in ('analysis/sept20-evening-before-cinematic.json',
                       'analysis/sept22-before-cinematic-hold-bound.json'):
            candidate=[(b['address'],bytes.fromhex(b['data_hex'])) for b in json.loads((ROOT/legacy).read_text())]
            if all(ram[p:p+len(data)]==data for p,data in candidate):
                recognized=candidate;complete=True;break
    if recognized is None:raise ValueError('Cinematic policy changed; no exact supported emission matches')
    native=elf_reader(elf_path(ROOT))[2]
    for p in (*RENDER_CALLS,fresh.successor.HOOK,*(p for p,_,_ in RESULT_CALLS)):
        if ram[p+4:p+8]!=native(p+4,4):raise ValueError('Cinematic policy delay slot changed')
    if any(u(CONTROL+o) not in (0,1) for o in (16,20,TRANSFORM_VIEW)):
        raise ValueError('Invalid cinematic checkbox value')
    previous_frame=pause.frame_code()
    frame_skip=8 if complete else 0
    if ram[pause.FRAME+frame_skip:pause.FRAME+len(previous_frame)]!=previous_frame[frame_skip:]:
        raise ValueError('Cinematic hitstop frame tail changed')
    return recognized


def dependency_overrides(ram,expected,manager,count):
    if not any(ram[CODE:END]):return expected
    replace=dict(validate_memory(ram,manager,count))
    return [(p,replace[p]+data[len(replace[p]):] if p in replace else data) for p,data in expected]


def build_memory(ram,config=None,source='<offline-memory>',*,ultimate=False,transformation=False,
                 transformation_view='shared'):
    if type(ultimate) is not bool or type(transformation) is not bool:
        raise ValueError('Cinematic options must be Boolean')
    if transformation_view not in TRANSFORM_VIEWS:
        raise ValueError(f'Transformation split view must be one of {TRANSFORM_VIEWS}')
    shared_form=TRANSFORM_VIEWS.index(transformation_view)
    manager,count,battle,actors=pause.identity(ram)
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    installed=u(CONTROL)==MAGIC
    if installed:
        installed_parts=validate_memory(ram,manager,count)
        import four_player_mode
        current=[(p,four_player_mode.dependency_override(ram,p,b)) for p,b in program(participants=True)+hooks()]
        parts=[]
        if installed_parts!=current:
            old=dict(installed_parts)
            for p,data in current:
                expected=old.get(p,pause.frame_code()[:len(data)] if p==pause.FRAME else b'')
                if p==A(0x1D63A8) and p not in old:
                    expected=elf_reader(elf_path(ROOT))[2](p,len(data))
                    if ram[p:p+len(data)]!=expected:raise ValueError('Native script-stop query changed')
                if data==expected:continue
                if len(data)>len(expected) and any(ram[p+len(expected):p+len(data)]):
                    raise ValueError(f'Cinematic policy upgrade extension occupied:{p:08X}')
                # Retire only the authenticated old tail when a helper shrinks.
                # Future upgrades can then use that space without mistaking our
                # own previous instructions for another patch's reservation.
                parts.append((p,data+bytes(max(0,len(expected)-len(data)))))
    else:
        if any(ram[CODE:END]):raise ValueError('Cinematic policy reservation occupied')
        pause.configure_memory(ram,mode={v:k for k,v in pause.MODES.items()}[u(pause.MODE)])
        native=elf_reader(elf_path(ROOT))[2]
        expected=[(leader.HOOK,struct.pack('<2I',(2<<26)|(camera.CODE>>2),0)),
                  (pause.PREPARE,pause.prepare_code()),(pause.STORE,pause.store_code()),
                  (fresh.successor.HOOK,struct.pack('<I',(3<<26)|(fresh.SUCCESSOR>>2)))]
        expected += [(p,native(p,8)) for p in (*RENDER_CALLS,A(0x1D63A8))]
        for p,target,_ in RESULT_CALLS:
            assert native(p,4)==struct.pack('<I',(3<<26)|(target>>2))
            expected.append((p,native(p,8)))
        for p,data in expected:
            if ram[p:p+len(data)]!=data:raise ValueError(f'Pre-cinematic hook changed at{p:08X}')
        control=bytearray(0x100);struct.pack_into('<6I',control,0,MAGIC,manager,count,battle,int(ultimate),int(transformation))
        struct.pack_into('<I',control,TRANSFORM_VIEW,shared_form)
        parts=program(participants=True)+hooks()+[(CONTROL,bytes(control))]
    if installed:
        for off,value in ((16,ultimate),(20,transformation),(TRANSFORM_VIEW,shared_form)):
            data=struct.pack('<I',int(value))
            if ram[CONTROL+off:CONTROL+off+4]!=data:parts.append((CONTROL+off,data))
    intervals=sorted((p,p+len(data)) for p,data in parts)
    assert all(end<=p for (_,end),(p,_) in zip(intervals,intervals[1:]))
    return dict(serial=SERIAL,crc=CRC,source=str(source),control=CONTROL,
        status='BINARY ULTIMATE CINEMATICS WITH INDEPENDENT ORDINARY SPLIT VIEWS',
        ultimate=ultimate,transformation=transformation,transformation_view=transformation_view,
        blocks=[dict(address=p,expected_hex=ram[p:p+len(data)].hex(),data_hex=data.hex()) for p,data in parts],
        telemetry=dict(last_priority=CONTROL+LAST_PRIORITY,priority_views=CONTROL+PRIORITY_VIEWS,
                       shared_stop=CONTROL+SHARED_STOP,transformation_view=CONTROL+TRANSFORM_VIEW,
                       hold_age=CONTROL+HOLD_AGE,hold_cooldown=CONTROL+HOLD_COOLDOWN,
                       hold_overruns=CONTROL+HOLD_OVERRUNS,hold_longest=CONTROL+HOLD_LONGEST,
                       hold_block=CONTROL+HOLD_BLOCK,hold_total=CONTROL+HOLD_TOTAL,
                       protect_updates=CONTROL+PROTECT_UPDATES,protect_last=CONTROL+PROTECT_LAST,
                       latch_refused=CONTROL+LATCH_REFUSED),
        limitations=['Shared native cinematic timeline; unrelated simultaneous pairs cannot have independent authored tracks.',
                     'Paired rush framing remains in its participant viewport even when activation cinematics are disabled.',
                     'Native impact, resource loading, arena transition and menu holds remain intact.',
                     'Simultaneous actor-local ultimates use the first living physical caster for the shared view while all verified performers keep advancing.',
                     'Transformations retain their separate checkbox; their split screen presentation is a separate preference.',
                     'A frame that keeps the whole native global stop with no running camera has nothing shared to present and keeps its split views.',
                     'The shared stop never holds the fighters the running authored camera binds, nor their live rush partners; everyone else outside the scene is held.',
                     'A shared stop is released after 900 consecutive holding updates and may not stop anyone again until 30 updates have passed with no presentation at all; past 2700 held updates in one battle it stops pausing anyone, so an unfinishable presentation costs seconds rather than the match.'])
