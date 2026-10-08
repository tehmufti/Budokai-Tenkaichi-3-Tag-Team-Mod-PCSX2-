"""Mutual-consent fusion for native team leaders and any allied human seat.

One transaction per native team; arbitrary controller numbers, independent
receipts, and no shared-screen publication into the legacy two-player ABI.
The resource loader still requires the surviving body to be a native leader.
"""
from native_map import A, FLAG_BITS
import struct
import localization
from prototype import Assembler
import fresh_team_combat as core
import fusion_partner_lifecycle as fusion
import battle_mode_policy as modes
import quad_controller as pads
import quad_lifecycle as seats
import guest_killfeed as feed
import team_participation as part
import coop_controller as controls
from regional import Y_ORIGIN, screen_y
from native_map import ACTOR_HZ

BASE,END=0x06BB0000,0x06BD0000
GATE,RESOLVE,BEGIN,TICK,COMMIT,PAD,FOLLOW,DRAW=(BASE+i*0x2000 for i in range(8))
ELIGIBILITY=BASE+0x10000
PRESENTATION=BASE+0x11000
SHARED=BASE+0x12000
CINEMATIC=BASE+0x13000
CONTROL,ROWS,MERGED,TEXT=BASE+0x1A000,BASE+0x1A100,BASE+0x14000,BASE+0x1C000
MAGIC=0x4D465531
STRIDE=64
# Mod settings (Fusion) may hide the owner caption and/or the switch
# countdown. CONTROL+20 records the hidden ones (bit0 owner, bit1 countdown)
# and is written only when non-zero, so a default install is unchanged. Both
# captions only exist in swap_20s (CONTROL+12 == 0); other modes never hide.
# Hiding removes only that line: the consent prompt, and each pair's timer in
# the pair's own views for the whole turn, stay as in the default (see draw).
HIDE_OWNER,HIDE_COUNTDOWN=1,2
CAPTION_KEYS=('show_fusion_control_owner','show_fusion_control_countdown')
F=dict(status=0,partner=4,variant=8,initiator=12,recipient=16,last=20,ttl=24,
       epoch=28,result=32,leader_seat=36,partner_seat=40)


def pad_address(a,out,seat,tag):
    for i in range(4):
        a.addiu(8,0,i);a.branch(5,seat,8,tag+str(i))
        a.li(out,pads.RECORDS+i*pads.RECORD_STRIDE if i<2 else pads.PADS+(i-2)*pads.RECORD_STRIDE)
        a.jump(tag+'done');a.label(tag+str(i))
    a.move(out,0);a.label(tag+'done')


def gate():
    a=Assembler(GATE);core.gate(a,'no');a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,'no')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'no');a.lw(9,8,8);a.branch(5,9,10,'no')
    a.li(8,core.PAIR+4);a.lw(9,8);a.branch(5,9,0,'no')
    a.addiu(2,0,1);a.jr();a.label('no');a.move(2,0);a.jr();return a.finish()


def resolve():
    """caller/variant -> leader ptr, side, partner, variant, two seat+1 values.

    Extra requests match the result character against the leader's native
    recipes. Variant numbers are not interchangeable between characters.
    """
    a=Assembler(RESOLVE);fusion.save(a);a.call(GATE);a.branch(4,2,0,'no')
    a.lw(17,29,fusion.OFFSETS[4]);a.lw(20,29,fusion.OFFSETS[5]);a.move(18,0)
    a.label('caller');a.li(8,core.POINTERS);a.r(0,9,0,18,2);a.r(0x21,8,8,9);a.lw(9,8)
    a.branch(4,9,17,'found');a.addiu(18,18,1);a.branch(5,18,10,'caller');a.jump('no')
    a.label('found');a.i(12,19,18,1);a.li(8,core.POINTERS);a.r(0,9,0,19,2);a.r(0x21,8,8,9);a.lw(16,8)
    a.r(0,8,0,19,6);a.li(9,ROWS);a.r(0x21,8,8,9);a.lw(8,8);a.branch(5,8,0,'own_recipe')
    a.i(11,8,20,3);a.branch(4,8,0,'no');a.branch(4,18,19,'evaluate')
    a.move(4,17);a.move(5,20);a.call(A(0x20E340));a.move(21,2);a.move(20,0)
    a.label('variant');a.move(4,16);a.move(5,20);a.call(A(0x20E340));a.branch(4,2,21,'evaluate')
    a.label('next_variant');a.addiu(20,20,1);a.i(11,8,20,3);a.branch(5,8,0,'variant');a.jump('own_recipe')
    a.label('evaluate');a.move(4,16);a.move(5,20);a.addiu(6,0,1);a.move(7,0);a.addiu(8,29,0x300)
    a.call(fusion.ELIGIBILITY);a.branch(4,2,0,'failed')
    a.lw(22,29,0x300);a.addiu(8,22,-1);a.i(11,8,8,modes.emitted_capacity()-1);a.branch(4,8,0,'failed')
    a.i(12,9,19,1);a.r(0,22,0,22,1);a.r(0x21,22,22,9)
    a.branch(4,18,19,'seats');a.branch(5,18,22,'next_variant')
    a.label('seats');a.r(0,8,0,19,6);a.li(9,ROWS);a.r(0x21,8,8,9);a.lw(8,8);a.branch(5,8,0,'no')
    a.move(23,0);a.move(24,0)
    for seat in range(4):
        a.li(8,seats.CONTROL+seats.F['owned']+4*seat);a.lw(8,8)
        a.branch(5,8,19,f'leader{seat}');a.addiu(23,0,seat+1);a.label(f'leader{seat}')
        a.branch(5,8,22,f'partner{seat}');a.addiu(24,0,seat+1);a.label(f'partner{seat}')
    for reg,value in ((2,16),(3,19),(4,22),(5,20),(6,23),(7,24)):a.i(31,value,29,fusion.OFFSETS[reg])
    fusion.restore(a);a.jr()
    a.label('failed');a.branch(5,18,19,'next_variant')
    a.jump('no')
    a.label('own_recipe');a.branch(4,18,19,'no');a.move(19,18);a.move(16,17)
    a.lw(20,29,fusion.OFFSETS[5]);a.i(11,8,20,3);a.branch(5,8,0,'evaluate')
    a.label('no');a.i(31,0,29,fusion.OFFSETS[2]);fusion.restore(a);a.jr();return a.finish()


def eligibility():
    a=Assembler(ELIGIBILITY);fusion.save(a);a.call(RESOLVE);a.branch(4,2,0,'native')
    a.r(2,9,0,4,1);a.lw(8,29,fusion.OFFSETS[8]);a.branch(4,8,0,'return')
    a.sw(9,8);a.label('return');a.addiu(8,0,1);a.i(31,8,29,fusion.OFFSETS[2]);fusion.restore(a);a.jr()
    a.label('native');fusion.restore(a);a.jump(fusion.ELIGIBILITY);return a.finish()


def begin():
    a=Assembler(BEGIN);fusion.save(a);a.call(RESOLVE);a.branch(4,2,0,'denied')
    # A CPU partner keeps ordinary native fusion. A human always consents,
    # including when the leader is an NPC and the human requested the move.
    a.branch(4,7,0,'native');a.move(17,2);a.move(18,3);a.move(19,4);a.move(20,5)
    a.addiu(21,6,-1);a.addiu(22,7,-1);a.r(0,8,0,18,6);a.li(16,ROWS);a.r(0x21,16,16,8)
    a.lw(8,29,fusion.OFFSETS[4]);a.branch(4,8,17,'leader_request')
    a.move(23,22);a.move(24,21);a.jump('request');a.label('leader_request');a.move(23,21);a.move(24,22)
    a.label('request');a.i(11,8,23,4);a.branch(4,8,0,'denied')
    pad_address(a,25,23,'request_pad');a.lw(8,25,328);a.i(12,8,8,4);a.branch(4,8,0,'denied')
    for key,reg in (('partner',19),('variant',20),('initiator',23),('recipient',24),('leader_seat',21),('partner_seat',22)):
        a.sw(reg,16,F[key])
    a.li(8,CONTROL);a.lw(8,8,16);a.addiu(8,8,4*ACTOR_HZ);a.sw(8,16,F['ttl'])
    a.move(8,0);a.i(11,9,24,4);a.branch(4,9,0,'no_other_pad')
    pad_address(a,25,24,'other_pad');a.lw(8,25,328)
    a.label('no_other_pad');a.sw(8,16,F['last']);a.addiu(8,0,1);a.sw(8,16)
    a.label('denied');a.i(31,0,29,fusion.OFFSETS[2]);fusion.restore(a);a.jr()
    a.label('native');a.i(31,2,29,fusion.OFFSETS[4]);a.i(31,5,29,fusion.OFFSETS[5])
    a.r(2,8,0,4,1);a.i(31,8,29,fusion.OFFSETS[6]);fusion.restore(a);a.jump(fusion.BEGIN);return a.finish()


def tick(previous):
    import fusion_duration as timer
    a=Assembler(TICK);fusion.save(a);a.call(GATE);a.branch(4,2,0,'done')
    timer.active_combat(a,'done')
    a.li(8,CONTROL);a.lw(9,8,16);a.addiu(9,9,1);a.sw(9,8,16)
    a.li(16,ROWS);a.move(18,0)
    a.label('row');a.lw(8,16);a.branch(4,8,0,'next');a.addiu(9,0,3);a.branch(4,8,9,'fused')
    a.li(8,core.POINTERS);a.r(0,9,0,18,2);a.r(0x21,8,8,9);a.lw(17,8)
    a.lw(19,16,F['partner']);a.li(8,core.POINTERS);a.r(0,9,0,19,2);a.r(0x21,8,8,9);a.lw(20,8)
    a.lw(8,16);a.addiu(9,0,2);a.branch(4,8,9,'queued')
    a.li(8,CONTROL);a.lw(8,8,16);a.lw(9,16,F['ttl']);a.r(0x23,9,9,8);a.branch(6,9,0,'cancel')
    for reg in (17,20):
        a.move(4,reg);a.call(feed.ROW);a.branch(4,2,0,'cancel');a.lw(8,2);a.branch(6,8,0,'cancel')
    a.lw(21,16,F['recipient']);a.i(11,8,21,4);a.branch(4,8,0,'accepted') # CPU needs no confirmation.
    pad_address(a,22,21,'accept_pad');a.lw(8,22,328);a.lw(9,16,F['last']);a.sw(8,16,F['last'])
    a.i(12,8,8,4);a.branch(4,8,0,'next');a.i(12,9,9,4);a.branch(5,9,0,'next')
    a.label('accepted')
    for reg in (17,20):
        a.lw(8,reg,2376);a.addiu(9,0,11);a.branch(4,8,9,f'idle{reg}');a.addiu(9,0,15);a.branch(5,8,9,'next');a.label(f'idle{reg}')
        for off in (2380,2388,2392,2396,2400):a.lw(8,reg,off);a.addiu(9,0,-1);a.branch(5,8,9,'next')
        for off in (3480,3500,3512):a.lw(8,reg,off);a.branch(5,8,0,'next')
        # Native actor flag 148 (0x94) in both flag banks (USA bytes 0x1097/0x10BF, bit 0x10).
        index,mask=FLAG_BITS((0x94,))
        for off in (0x1085+index,0x10AD+index):a.i(36,8,reg,off);a.i(12,8,8,mask);a.branch(5,8,0,'next')
    a.move(4,17);a.lw(5,16,F['variant']);a.addiu(6,0,1);a.move(7,0);a.addiu(8,29,0x300)
    a.call(fusion.ELIGIBILITY);a.branch(4,2,0,'cancel');a.lw(8,29,0x300);a.r(2,9,0,19,1);a.branch(5,8,9,'cancel')
    a.move(4,17);a.lw(5,16,F['variant']);a.move(6,9);a.call(fusion.BEGIN);a.branch(4,2,0,'cancel')
    a.lw(8,17,4816);a.sw(8,16,F['result']);a.addiu(8,0,2);a.sw(8,16);a.jump('next')
    a.label('queued')
    a.li(8,part.CONSUMED);a.lw(8,8);a.addiu(9,0,1);a.r(4,9,19,9);a.r(0x24,8,8,9);a.branch(4,8,0,'still_queued')
    a.lw(9,17,0x994);fusion.row_address(a,10,17,9,8);a.lw(8,10);a.lw(9,16,F['result']);a.branch(5,8,9,'cancel')
    a.li(8,CONTROL);a.lw(8,8,16);a.sw(8,16,F['epoch']);a.addiu(8,0,3);a.sw(8,16);a.sw(0,17,0x1278);a.jump('next')
    a.label('still_queued')
    for off in (2376,2380,2388,2392,2396,2400):
        a.lw(8,17,off);a.addiu(8,8,-241);a.i(11,8,8,2);a.branch(5,8,0,'next')
    a.jump('cancel')
    a.label('fused');a.lw(19,16,F['partner']);a.li(8,part.CONSUMED);a.lw(8,8);a.addiu(9,0,1);a.r(4,9,19,9);a.r(0x24,8,8,9)
    a.branch(5,8,0,'next') # Defusion releases consumption; cameras/pads revert in the same frame.
    a.label('cancel');a.sw(0,16)
    a.label('next');a.addiu(16,16,STRIDE);a.addiu(18,18,1);a.addiu(8,0,modes.emitted_actors());a.branch(5,18,8,'row')
    a.label('done');fusion.restore(a);a.jump(previous);return a.finish()


def commit():
    a=Assembler(COMMIT);fusion.save(a);fusion.restore(a,False);a.call(fusion.COMMIT);fusion.save(a,True)
    a.call(GATE);a.branch(4,2,0,'done');a.li(16,ROWS);a.move(18,0)
    a.label('row');a.lw(8,16);a.addiu(9,0,2);a.branch(5,8,9,'next')
    a.li(8,core.POINTERS);a.r(0,9,0,18,2);a.r(0x21,8,8,9);a.lw(17,8)
    a.lw(9,17,0x994);fusion.row_address(a,10,17,9,8);a.lw(8,10);a.lw(9,16,F['result']);a.branch(5,8,9,'next')
    a.li(8,fusion.CONTROL);a.lw(9,8,24);a.branch(5,9,17,'next');a.lw(9,8,20);a.lw(19,16,F['partner']);a.branch(5,9,19,'next')
    a.li(8,part.CONSUMED);a.lw(8,8);a.addiu(9,0,1);a.r(4,9,19,9);a.r(0x24,8,8,9);a.branch(4,8,0,'next')
    a.li(8,CONTROL);a.lw(8,8,16);a.sw(8,16,F['epoch']);a.addiu(8,0,3);a.sw(8,16)
    a.sw(0,17,0x1278)
    a.label('next');a.addiu(16,16,STRIDE);a.addiu(18,18,1);a.addiu(8,0,modes.emitted_actors());a.branch(5,18,8,'row')
    a.label('done');fusion.restore(a);a.jr();return a.finish()


def follow():
    a=Assembler(FOLLOW);fusion.save(a);a.call(GATE);a.branch(4,2,0,'no');a.lw(17,29,fusion.OFFSETS[4])
    a.li(16,ROWS);a.move(18,0)
    a.label('row');a.lw(8,16);a.addiu(9,0,2);a.branch(4,8,9,'queued')
    a.addiu(9,0,3);a.branch(5,8,9,'next')
    a.lw(19,16,F['partner']);a.li(8,part.CONSUMED);a.lw(8,8);a.addiu(9,0,1);a.r(4,9,19,9);a.r(0x24,8,8,9);a.branch(4,8,0,'next')
    a.jump('match')
    a.label('queued');a.li(8,core.POINTERS);a.r(0,9,0,18,2);a.r(0x21,8,8,9);a.lw(8,8)
    a.lw(8,8,2376);a.addiu(8,8,-241);a.i(11,8,8,2);a.branch(4,8,0,'next');a.lw(19,16,F['partner'])
    a.label('match');a.branch(4,17,18,'yes');a.branch(4,17,19,'yes')
    a.label('next');a.addiu(16,16,STRIDE);a.addiu(18,18,1);a.addiu(8,0,modes.emitted_actors());a.branch(5,18,8,'row')
    a.label('no');a.addiu(18,0,-1);a.label('yes');a.i(31,18,29,fusion.OFFSETS[2]);fusion.restore(a);a.jr();return a.finish()


def pad(previous):
    a=Assembler(PAD);fusion.save(a);a.call(GATE);a.branch(4,2,0,'native')
    a.lw(17,29,fusion.OFFSETS[4]);a.lw(18,17);a.i(11,8,18,modes.emitted_actors());a.branch(4,8,0,'native')
    a.move(4,18);a.call(FOLLOW);a.branch(5,2,18,'native')
    a.r(0,8,0,18,6);a.li(16,ROWS);a.r(0x21,16,16,8)
    a.lw(8,16);a.addiu(9,0,3);a.branch(5,8,9,'native')
    a.lw(19,16,F['leader_seat']);a.lw(20,16,F['partner_seat'])
    # The lower-numbered participating player is P1 for this fusion's policy.
    a.r(0x2B,8,19,20);a.branch(5,8,0,'ordered');a.move(8,19);a.move(19,20);a.move(20,8);a.label('ordered')
    a.i(11,8,20,4);a.branch(4,8,0,'first')
    a.li(8,CONTROL);a.lw(9,8,12);a.addiu(10,0,1);a.branch(4,9,10,'merge');a.branch(5,9,0,'first')
    a.lw(9,8,16);a.lw(10,16,F['epoch']);a.r(0x23,9,9,10)
    a.r(16,24,0);a.r(18,25,0);a.li(10,controls.SWAP_UPDATES);a.r(27,0,9,10);a.r(18,11,0);a.r(17,0,24);a.r(19,0,25)
    a.i(12,11,11,1);a.branch(4,11,0,'first');a.move(19,20)
    a.label('first');pad_address(a,22,19,'first_pad');a.jump('return')
    a.label('merge');pad_address(a,21,19,'merge_a');pad_address(a,23,20,'merge_b')
    a.r(0,8,0,18,9);a.li(22,MERGED);a.r(0x21,22,22,8)
    for off in range(0,pads.RECORD_STRIDE,8):a.i(55,9,21,off);a.i(63,9,22,off)
    a.li(12,controls.MOVEMENT_MASK);a.li(13,0xFFFFFFFF^controls.MOVEMENT_MASK)
    for off in (328,332,336,340,348):
        a.lw(9,21,off);a.r(0x24,9,9,13);a.lw(10,23,off);a.r(0x24,10,10,12);a.r(0x25,9,9,10);a.sw(9,22,off)
    for off in (304,308,312,316):a.lw(9,23,off);a.sw(9,22,off)
    a.label('return');a.i(31,22,29,fusion.OFFSETS[2]);fusion.restore(a);a.jr()
    a.label('native');fusion.restore(a);a.jump(previous);return a.finish()


def presentation():
    a=Assembler(PRESENTATION);fusion.save(a);a.call(GATE);a.branch(4,2,0,'no')
    for side in range(modes.emitted_actors()):
        a.li(8,core.POINTERS+4*side);a.lw(8,8);a.lw(8,8,2376)
        a.addiu(8,8,-241);a.i(11,8,8,2);a.branch(5,8,0,'yes')
    a.label('no');a.move(8,0);a.jump('return');a.label('yes');a.addiu(8,0,1)
    a.label('return');a.i(31,8,29,fusion.OFFSETS[2]);fusion.restore(a);a.jr();return a.finish()


def shared():
    """Two consenting humans share one view; larger sessions retain each view."""
    a=Assembler(SHARED);fusion.save(a);a.call(GATE);a.branch(4,2,0,'no')
    a.li(8,seats.views.CONTROL);a.lw(9,8,seats.views.VIEW_COUNT);a.addiu(10,0,2);a.branch(5,9,10,'no')
    a.li(8,seats.views.SUBJECTS);a.lw(9,8);a.lw(10,8,4);a.branch(5,9,10,'no')
    a.li(8,core.MODE);a.lw(8,8,4);a.r(0x2B,8,9,8);a.branch(4,8,0,'no')
    a.r(0,8,0,9,6);a.li(10,ROWS);a.r(0x21,8,8,10);a.lw(9,8)
    a.addiu(10,0,3);a.branch(5,9,10,'no')
    for off in (F['leader_seat'],F['partner_seat']):
        a.lw(9,8,off);a.i(11,9,9,2);a.branch(4,9,0,'no')
    a.addiu(8,0,1);a.jump('return');a.label('no');a.move(8,0)
    a.label('return');a.i(31,8,29,fusion.OFFSETS[2]);fusion.restore(a);a.jr();return a.finish()


def cinematic():
    """Physical watched fighter -> authenticated fusion camera participation.

    The legacy co-op lookup only understood physical0/2 and two humans.
    Resolve the real accepted pair, including extras and either team, without
    borrowing another actor's concurrently running special camera.
    """
    import cinematic_policy as cinema
    a=Assembler(CINEMATIC);fusion.save(a);a.call(GATE);a.branch(4,2,0,'no')
    a.li(8,cinema.CONTROL);a.lw(9,8);a.li(10,cinema.MAGIC);a.branch(5,9,10,'no')
    # Fusion always uses its native track for the participating pair, as the
    # existing two-player fusion does. The ordinary-transform checkbox must
    # not detach the partner camera halfway through an accepted fusion.
    a.lw(4,29,fusion.OFFSETS[4]);a.call(FOLLOW);a.branch(1,2,0,'no');a.move(16,2)
    a.li(8,core.POINTERS);a.r(0,9,0,16,2);a.r(0x21,8,8,9);a.lw(17,8)
    fusion.pointer(a,17,2404,'no',8,9)
    a.lw(8,17,2376);a.addiu(8,8,-241);a.i(11,8,8,2);a.branch(4,8,0,'no')
    a.lw(18,28,-22180);cinema.camera_running(a,18,'no','fusion_camera')
    # Either original participant may be the authored track's anchor.
    for partner in (False,True):
        if partner:
            a.r(0,8,0,16,6);a.li(9,ROWS);a.r(0x21,8,8,9);a.lw(8,8,F['partner'])
            a.li(9,core.MODE);a.lw(9,9,4);a.r(0x2B,9,8,9);a.branch(4,9,0,'no')
            a.r(0,8,0,8,2);a.li(9,core.POINTERS);a.r(0x21,8,8,9);a.lw(17,8)
            fusion.pointer(a,17,16,'no',8,9)
        a.lw(8,17,12);a.i(11,9,8,12);a.branch(4,9,0,'no')
        a.r(0,8,0,8,2);a.li(9,core.MODELS);a.r(0x21,8,8,9);a.lw(8,8)
        a.branch(4,8,0,'no')
        a.lw(9,18,768);a.branch(4,8,9,'yes');a.lw(9,18,772);a.branch(4,8,9,'yes')
    a.label('no');a.move(8,0);a.jump('return');a.label('yes');a.addiu(8,0,1)
    a.label('return');a.i(31,8,29,fusion.OFFSETS[2]);fusion.restore(a);a.jr()
    data=a.finish();assert len(data)<MERGED-CINEMATIC;return data


def draw(show_owner=True,show_countdown=True):
    """Consent prompt, owner caption, switch countdown and fusion timer per view.

    A hidden caption only stops its own line from being drawn; the timer's
    placement is the same in every variant for the whole 20 s turn. A swap-mode
    human pair's timer stays in the pair's two views, so a defeated human
    spectating the fused fighter never sees it, exactly as with both captions
    shown. By default the owner line itself marks the pair. With the owner
    caption hidden, a spare frame word (PAIR) is set at the same step instead,
    and one doubleword store clears both caption slots so the marker's reset
    fits: no variant is longer than the default draw. Fusions without a human
    pair (CPU partner, native leader fusion) keep showing their timer in every
    view whose subject is the fused fighter.
    """
    import fusion_duration as timer
    import multiview_layout as layout
    PAIR=0x320 # frame word, hidden-owner variants only: this row's pair is shown
    def tighten(a,reg,pixels):
        # Keep the full-height two-player display unchanged.
        tag='small_'+str(a.pc)
        a.li(10,seats.views.CONTROL);a.lw(11,10,seats.views.VIEW_COUNT);a.i(11,11,11,3);a.branch(5,11,0,tag)
        a.addiu(reg,reg,-pixels*4);a.label(tag)
    a=Assembler(DRAW);fusion.save(a);a.call(GATE);a.branch(4,2,0,'done')
    a.li(8,A(0x2FEB38));a.lw(8,8);fusion.pointer(a,8,264,'done',9,11)
    a.lw(8,8);a.addiu(9,0,3);a.branch(5,8,9,'done')
    a.call(SHARED);a.sw(2,29,0x31C)
    a.li(16,ROWS);a.move(18,0)
    a.label('row')
    if show_owner:a.sw(0,29,0x310);a.sw(0,29,0x314)
    else:a.i(63,0,29,0x310);a.sw(0,29,PAIR) # sd $zero clears 0x310 and 0x314
    a.sw(0,29,0x318)
    a.lw(8,16);a.addiu(9,0,1);a.branch(4,8,9,'request')
    a.addiu(9,0,3);a.branch(5,8,9,'timer');a.li(8,CONTROL);a.lw(9,8,12);a.branch(5,9,0,'timer')
    a.lw(9,8,16);a.lw(10,16,F['epoch']);a.r(0x23,9,9,10)
    a.r(16,24,0);a.r(18,25,0);a.li(10,controls.SWAP_UPDATES);a.r(27,0,9,10);a.r(18,11,0);a.r(16,23,0);a.r(17,0,24);a.r(19,0,25)
    a.lw(19,16,F['leader_seat']);a.lw(20,16,F['partner_seat']);a.r(0x2B,8,19,20);a.branch(5,8,0,'ordered')
    a.move(8,19);a.move(19,20);a.move(20,8);a.label('ordered')
    a.i(11,8,20,4);a.branch(4,8,0,'timer');a.i(12,8,11,1);a.branch(4,8,0,'owner')
    a.move(8,19);a.move(19,20);a.move(20,8)
    a.label('owner');a.addiu(19,19,4);a.r(0,19,0,19,6);a.li(8,TEXT);a.r(0x21,19,19,8)
    # Every human swap pair reaches this store, before any countdown line.
    a.sw(19,29,0x310 if show_owner else PAIR)
    if show_countdown:
        # Same combat clock as PAD, warning only in the last five seconds.
        a.li(8,controls.SWAP_UPDATES);a.r(0x23,23,8,23);a.i(11,8,23,5*ACTOR_HZ+1);a.branch(4,8,0,'timer')
        a.addiu(23,23,-1);a.move(21,0)
        a.label('seconds');a.i(11,8,23,ACTOR_HZ);a.branch(5,8,0,'count_label');a.addiu(23,23,-ACTOR_HZ);a.addiu(21,21,1);a.jump('seconds')
        a.label('count_label');a.r(0,8,0,20,2);a.r(0x21,8,8,20);a.r(0x21,8,8,21);a.r(0,8,0,8,6)
        a.li(9,TEXT+8*64);a.r(0x21,8,8,9);a.sw(8,29,0x314)
    a.label('timer');a.li(8,timer.CONTROL);a.lw(9,8);a.li(11,timer.MAGIC);a.branch(5,9,11,'label')
    a.lw(9,8,12);a.branch(4,9,0,'label');a.lw(9,8,20);a.branch(4,9,0,'label')
    a.r(0,9,0,18,10);a.li(21,timer.RECORDS);a.r(0x21,21,21,9);a.lw(9,21)
    a.addiu(9,9,-2);a.i(11,9,9,2);a.branch(4,9,0,'label');a.sw(21,29,0x318);a.jump('label')
    a.label('request');a.lw(19,16,F['recipient']);a.i(11,8,19,4);a.branch(4,8,0,'next')
    a.r(0,19,0,19,6);a.li(8,TEXT);a.r(0x21,19,19,8);a.sw(19,29,0x310)
    a.label('label')
    # A request or a human pair draws in the pair's seats only. A leader/CPU
    # fusion has no consent record, but its timer still belongs to any
    # viewport watching that body. Hidden-owner variants test PAIR where the
    # default tests the countdown: PAIR is always set when a countdown is.
    for partner,(left,right,top,bottom) in enumerate(seats.views.RECTS):
        if partner:a.lw(8,29,0x31C);a.branch(5,8,0,f'skip{partner}')
        a.li(8,seats.views.CONTROL);a.lw(9,8,seats.views.VIEW_COUNT);a.i(11,9,9,partner+1);a.branch(5,9,0,f'skip{partner}')
        a.lw(8,29,0x310);a.lw(9,29,0x314 if show_owner else PAIR);a.r(0x25,8,8,9);a.branch(4,8,0,f'watched{partner}')
        a.addiu(20,0,partner);a.lw(8,16,F['leader_seat']);a.branch(4,8,20,f'seat{partner}')
        a.lw(8,16,F['partner_seat']);a.branch(4,8,20,f'seat{partner}');a.jump(f'skip{partner}')
        a.label(f'watched{partner}');a.lw(8,29,0x318);a.branch(4,8,0,f'skip{partner}')
        a.li(8,seats.views.SUBJECTS+4*partner);a.lw(8,8);a.branch(5,8,18,f'skip{partner}')
        a.label(f'seat{partner}');a.li(5,(1792+left+8)*16);a.li(6,(Y_ORIGIN+top+screen_y(layout.FUSION_Y))*16)
        if partner==2:
            a.li(8,seats.views.CONTROL);a.lw(8,8,seats.views.VIEW_COUNT);a.addiu(9,0,3);a.branch(5,8,9,f'located{partner}')
            a.addiu(5,5,128*16)
        a.label(f'located{partner}');a.sw(5,29,0x300);a.sw(6,29,0x304)
        for line,offset,color in ((0,0x310,0x80D0FFFF),(1,0x314,0x8050CFFF)):
            a.lw(4,29,offset);a.branch(4,4,0,f'line{partner}_{line}')
            a.lw(5,29,0x300);a.lw(6,29,0x304);a.addiu(6,6,line*12*16);tighten(a,6,line*12)
            a.li(7,color);a.call(feed.SMALL_TEXT);a.label(f'line{partner}_{line}')
        a.lw(21,29,0x318);a.branch(4,21,0,f'skip{partner}')
        a.lw(8,21,4);a.addiu(8,8,29);a.addiu(9,0,30);a.r(27,0,8,9);a.r(18,8,0)
        a.r(0,8,0,8,5);a.li(4,timer.TEXT);a.r(0x21,4,4,8)
        a.lw(5,29,0x300);a.lw(6,29,0x304);a.addiu(6,6,24*16);tighten(a,6,24);a.li(7,0x80A0FFFF);a.call(feed.SMALL_TEXT)
        a.lw(8,21,4);a.li(9,120);a.li(10,seats.views.CONTROL);a.lw(11,10,seats.views.VIEW_COUNT);a.i(11,11,11,3);bar_tag='bar_width_'+str(a.pc);a.branch(5,11,0,bar_tag);a.li(9,90);a.label(bar_tag);a.r(24,0,8,9);a.r(18,8,0);a.li(9,timer.CONTROL);a.lw(9,9,16);a.lw(10,21,100);total_tag='timer_total_'+str(a.pc)
        a.branch(4,10,0,total_tag);a.move(9,10);a.label(total_tag)
        a.r(27,0,8,9);a.r(18,6,0);a.r(0,6,0,6,4);a.lw(4,29,0x300);a.r(0x21,6,6,4)
        a.lw(5,29,0x304);a.addiu(5,5,36*16);tighten(a,5,36);a.addiu(7,5,3*16);tighten(a,7,3);a.li(8,0x80A0FFFF);a.call(timer.bars.RECT)
        a.label(f'skip{partner}')
    a.label('next');a.addiu(16,16,STRIDE);a.addiu(18,18,1);a.addiu(8,0,modes.emitted_actors());a.branch(5,18,8,'row')
    a.label('done');fusion.restore(a);a.jr();return a.finish()


def program(previous,pad_previous,show_owner=True,show_countdown=True):
    return [(GATE,gate()),(RESOLVE,resolve()),(BEGIN,begin()),(ELIGIBILITY,eligibility()),
            (TICK,tick(previous)),(COMMIT,commit()),(FOLLOW,follow()),(PAD,pad(pad_previous)),
            (DRAW,draw(show_owner,show_countdown)),(PRESENTATION,presentation()),(SHARED,shared()),(CINEMATIC,cinematic())]


def hide_bits(fusion_mode,show_owner=True,show_countdown=True):
    """CONTROL+20 word for the settings; zero outside swap_20s (mode index 0)."""
    for value in (show_owner,show_countdown):
        if type(value) is not bool:raise ValueError('Fusion caption visibility must be Boolean')
    if fusion_mode!=0:return 0
    return (0 if show_owner else HIDE_OWNER)|(0 if show_countdown else HIDE_COUNTDOWN)


def installed_captions(ram):
    """(show_owner, show_countdown) of an installed program, from CONTROL+20."""
    bits,mode=struct.unpack_from('<I',ram,CONTROL+20)[0],struct.unpack_from('<I',ram,CONTROL+12)[0]
    if bits>HIDE_OWNER|HIDE_COUNTDOWN:raise ValueError('Invalid multiplayer fusion caption options')
    if bits and mode!=0:raise ValueError('Multiplayer fusion captions are only hidden in swap mode')
    return not bits&HIDE_OWNER,not bits&HIDE_COUNTDOWN


def installed_program(ram):
    """The exact program an installed CONTROL block says was emitted."""
    return program(pads.FRAME,pads.PAD,*installed_captions(ram))


def text_data():
    labels=[f'FUSION - P{i+1} TAP R3 TO ACCEPT' for i in range(4)]+[f'FUSED - PLAYER {i+1} HAS CONTROL' for i in range(4)]
    labels += [f'P{i+1} TAKES CONTROL IN {seconds}' for i in range(4) for seconds in range(1,6)]
    return b''.join(localization.slot(label,64) for label in labels)


def dependency_override(ram,address,expected):
    u=lambda at:struct.unpack_from('<I',ram,at)[0]
    if u(CONTROL)!=MAGIC:return expected
    if (u(CONTROL+4),u(CONTROL+8))!=(u(core.ACTORS),u(core.MODE+4)):
        raise ValueError('Multiplayer fusion belongs to another capture')
    replacements={A(0x1C2A28):(TICK,8),controls.HOOK:(PAD,8),
        fusion.ELIGIBILITY_HOOK:(ELIGIBILITY,8),fusion.BEGIN_HOOK:(BEGIN,8),fusion.COMMIT_HOOK:(COMMIT,4)}
    if address not in replacements:return expected
    for p,data in installed_program(ram):
        if ram[p:p+len(data)]!=data:raise ValueError(f'Multiplayer fusion code changed:{p:08X}')
    target,size=replacements[address];data=seats.views.jump(target)[:size]
    if ram[address:address+size]!=data:raise ValueError('Multiplayer fusion hook changed')
    return data


def build_memory(ram,settings):
    import mod_settings
    if struct.unpack_from('<I',ram,seats.CONTROL+seats.F['battle_mode'])[0]==modes.FFA:return dict(blocks=[])
    if any(ram[BASE:END]):raise ValueError('Multiplayer fusion reservation occupied')
    u=lambda at:struct.unpack_from('<I',ram,at)[0]
    previous=(u(A(0x1C2A28))&0x3FFFFFF)<<2
    if previous!=pads.FRAME:raise ValueError('Install multiplayer pads before fusion')
    fusion_mode=mod_settings.FUSION_MODES.index(settings[mod_settings.COOP_FUSION_KEY])
    # Settings saved before the caption options existed show both captions.
    hidden=hide_bits(fusion_mode,*(settings.get(key,True) for key in CAPTION_KEYS))
    control=struct.pack('<5I',MAGIC,u(core.ACTORS),u(core.MODE+4),fusion_mode,0)+(struct.pack('<I',hidden) if hidden else b'')
    parts=program(previous,pads.PAD,not hidden&HIDE_OWNER,not hidden&HIDE_COUNTDOWN)+[(CONTROL,control),(ROWS,bytes(modes.emitted_actors()*STRIDE)),(TEXT,text_data()),
        (A(0x1C2A28),seats.views.jump(TICK)),(controls.HOOK,seats.views.jump(PAD)),
        (fusion.ELIGIBILITY_HOOK,seats.views.jump(ELIGIBILITY)),(fusion.BEGIN_HOOK,seats.views.jump(BEGIN)),
        (fusion.COMMIT_HOOK,struct.pack('<I',(2<<26)|(COMMIT>>2)))]
    return dict(blocks=[dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=b.hex())for p,b in parts])
