"""Mutual native fusion input for the two human allies (physical0 and2).

Eligibility and resource replacement remain native leader paths. P2 may request
the leader's corresponding fusion variant; the other player consents with a
plain R3 press edge (direction and L3 bits ignored, a pad already holding R3
is not consent). A request expires without spending or starting fusion, and a
body that is busy when consent arrives keeps the request pending rather than
destroying it.
"""
from native_map import A, CRC, FLAG, SERIAL
import struct
import localization
from prototype import Assembler
import battle_mode_policy as mode
import fusion_partner_lifecycle as fusion
import fresh_team_combat as core
import team_participation as participation
import team_start_gate as start
import guest_killfeed as feed
import coop_controller as controller
from input_script import RECORDS, RECORD_STRIDE
from regional import Y_ORIGIN, screen_y
from native_map import ACTOR_HZ

GATE, ELIGIBILITY, BEGIN, TICK, COMMIT, DRAW = (0x07130000,0x07130400,0x07131000,0x07133000,0x07135000,0x07136000)
CONTACT = 0x07138000
TEXT_P1,TEXT_P2,TEXT_HINT=0x0713E000,0x0713E080,0x0713E100
TEXT_OWNER=(0x0713E180,0x0713E200)
TEXT_COUNTDOWN=0x0713E280
COUNTDOWN_SECONDS=5
COUNTDOWN_STRIDE=64
# Mod settings (Fusion) may hide the owner caption, the switch countdown or
# both. They only exist while the fused controls alternate: swap_20s, the
# CONTROL+32 value 0. Every other mode keeps the default emission, and a
# hidden variant differs from the default in DRAW alone (the text stays).
SWAP_MODE=0
CAPTION_VARIANTS=((False,True),(True,False),(False,False))
CHORD_TEXT=0x07139000
END=0x07140000
CONTROL=mode.CONTROL
CHORD_MASK=0xF6
R3=0x4
# Four active seconds at the measured 30 Hz actor clock. The prompt is drawn
# for exactly this window - begin() sets the expiry word the draw gates on, and
# both the accepted and the cancelled paths clear it - so the offer is on screen
# while it stands and gone the moment it does not.
REQUEST_TTL=4*ACTOR_HZ
VARIANT, SLOT, INITIATOR, LAST_OTHER = 80,84,88,92


def gate():
    a=Assembler(GATE);core.gate(a,'no');a.li(8,CONTROL);a.lw(9,8);a.li(11,mode.MAGIC)
    a.branch(5,9,11,'no');a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'no')
    a.lw(9,8,8);a.branch(5,9,10,'no');a.lw(9,8,12);a.addiu(11,0,mode.COOP)
    a.branch(5,9,11,'no');a.li(8,core.PAIR+4);a.lw(9,8);a.branch(5,9,0,'no')
    a.addiu(2,0,1);a.jr();a.label('no');a.move(2,0);a.jr();return a.finish()


def eligibility():
    a=Assembler(ELIGIBILITY);fusion.save(a);a.call(GATE);a.branch(4,2,0,'native')
    a.li(8,core.POINTERS);a.lw(9,8,8);a.lw(4,29,fusion.OFFSETS[4])
    a.branch(5,4,9,'native');a.lw(4,8)
    # The selected variant is evaluated against the retained native leader.
    for r in (5,6,7,8):a.i(30,r,29,fusion.OFFSETS[r])
    a.call(fusion.ELIGIBILITY);a.branch(4,2,0,'native');a.i(31,2,29,fusion.OFFSETS[2]);fusion.restore(a);a.jr()
    a.label('native');fusion.restore(a);a.jump(fusion.ELIGIBILITY)
    return a.finish()


def begin():
    a=Assembler(BEGIN);fusion.save(a);a.call(GATE);a.branch(4,2,0,'native')
    a.li(16,CONTROL);a.lw(8,16,24);a.addiu(9,0,-1);a.branch(5,8,9,'denied')
    a.li(8,core.POINTERS);a.lw(17,8);a.lw(18,8,8)
    a.lw(19,29,fusion.OFFSETS[4]);a.move(20,0);a.branch(4,19,17,'human')
    a.addiu(20,0,1);a.branch(5,19,18,'native')
    a.label('human');a.move(4,17);a.lw(5,29,fusion.OFFSETS[5])
    a.addiu(6,0,1);a.move(7,0);a.addiu(8,29,0x300);a.call(fusion.ELIGIBILITY)
    a.branch(4,2,0,'native');a.lw(8,29,0x300);a.addiu(9,0,1)
    a.branch(4,8,9,'human_partner');a.jump('native')
    a.label('human_partner');a.lw(8,16,48);a.addiu(9,0,-1)
    a.branch(5,8,9,'denied') # Repeated holds do not extend or replace a request.
    a.li(8,RECORDS);a.branch(4,20,0,'pad_ready');a.addiu(8,8,RECORD_STRIDE)
    a.label('pad_ready');a.lw(21,8,328);a.i(12,21,21,CHORD_MASK)
    a.i(12,9,21,4);a.branch(4,9,0,'denied')
    a.sw(0,16,48);a.addiu(8,0,2);a.sw(8,16,52);a.sw(21,16,56)
    a.lw(8,16,36);a.addiu(8,8,REQUEST_TTL);a.sw(8,16,60);a.sw(0,16,64)
    a.lw(8,29,fusion.OFFSETS[5]);a.sw(8,16,VARIANT);a.addiu(8,0,1);a.sw(8,16,SLOT)
    a.sw(20,16,INITIATOR)
    a.li(8,RECORDS+RECORD_STRIDE);a.branch(4,20,0,'other_ready');a.addiu(8,8,-RECORD_STRIDE)
    a.label('other_ready');a.lw(8,8,328);a.i(12,8,8,CHORD_MASK);a.sw(8,16,LAST_OTHER)
    a.label('denied');a.i(31,0,29,fusion.OFFSETS[2]);fusion.restore(a);a.jr()
    a.label('native');fusion.restore(a);a.jump(fusion.BEGIN)
    data=a.finish();assert len(data)<TICK-BEGIN;return data


def tick(previous):
    a=Assembler(TICK);fusion.save(a);a.call(GATE);a.branch(4,2,0,'done')
    a.li(8,start.CONTROL);a.lw(8,8);a.branch(5,8,0,'done')
    # The actor entry is also called while the native update early-outs for
    # pause, stage loading and results. Clock only released combat (30 Hz).
    a.li(8,A(0x3337B8));a.lw(8,8);a.i(12,8,8,0x2100);a.branch(5,8,0,'done')
    a.li(8,A(0x333700));a.lw(8,8);a.branch(5,8,0,'done')
    a.li(8,A(0x3337C0));a.lw(8,8);a.addiu(9,0,1);a.branch(5,8,9,'done')
    a.lw(8,28,-22364);a.lw(8,8,628);a.branch(5,8,0,'done')
    a.li(8,A(0x2FEB38));a.lw(8,8);a.li(9,0x100000);a.r(0x2B,9,8,9);a.branch(5,9,0,'done')
    a.li(9,0x7FFFE00);a.r(0x2B,9,8,9);a.branch(4,9,0,'done')
    a.lw(9,8,260);a.li(10,A(0x2C6070));a.branch(5,9,10,'done')
    a.lw(8,8);a.addiu(9,0,3);a.branch(5,8,9,'done')
    a.li(16,CONTROL);a.lw(8,16,36);a.addiu(8,8,1);a.sw(8,16,36)
    a.lw(9,16,48);a.addiu(10,0,-1);a.branch(5,9,10,'pending')
    # Native damage can cancel a queued fusion before model replacement. The
    # consent token must not survive that canceled transaction or grant later
    # control ownership to an unrelated transform/fusion.
    a.lw(9,16,64);a.branch(4,9,0,'done');a.li(8,core.POINTERS);a.lw(17,8)
    for off in (2376,2380,2388,2392,2396,2400):
        a.lw(8,17,off);a.addiu(8,8,-241);a.i(11,8,8,2);a.branch(5,8,0,'done')
    a.jump('cancel')
    a.label('pending')
    # A changed option cancels unanswered offers without disturbing the
    # accepted queue/active ownership handled above.
    a.li(9,fusion.DISABLED);a.lw(9,9);a.branch(5,9,0,'cancel')
    a.lw(9,16,60);a.r(0x23,9,9,8);a.branch(6,9,0,'cancel')
    a.li(8,participation.CONSUMED);a.lw(8,8);a.i(12,8,8,4);a.branch(5,8,0,'cancel')
    a.li(8,core.POINTERS);a.lw(17,8);a.lw(18,8,8)
    for r in (17,18):
        a.move(4,r);a.call(feed.ROW);a.branch(4,2,0,'cancel');a.lw(8,2);a.branch(6,8,0,'cancel')
    a.li(8,RECORDS+RECORD_STRIDE);a.lw(9,16,INITIATOR);a.branch(4,9,0,'pad_ready')
    a.addiu(8,8,-RECORD_STRIDE)
    a.label('pad_ready');a.lw(8,8,328);a.i(12,8,8,CHORD_MASK)
    # Consent is a plain R3 press edge from the other human: any direction or
    # L3 bit is ignored, so the requester's exact chord still consents and a
    # tap is enough. A pad already holding R3 when the request appears is not
    # consent, which keeps the lock-on hold and the native transformation
    # gesture from accepting a fusion nobody answered.
    a.lw(9,16,LAST_OTHER);a.sw(8,16,LAST_OTHER)
    a.i(12,10,8,R3);a.branch(4,10,0,'done')
    a.i(12,10,9,R3);a.branch(5,10,0,'done')
    # Consent is not permission to break an already bound cinematic or to
    # redirect a pending native damage transfer onto the fusion result.
    for r in (17,18):
        # Start only from neutral grounded/airborne idle, with no queued
        # transition. This includes ordinary hurt states and the native hit94
        # marker which is set before the hurt action becomes visible.
        # A busy body keeps the request pending instead of destroying it: the
        # consent sample was already recorded, so the partner releases R3 and
        # taps again once both are still, and the request still expires on its
        # own. Cancelling here would make a mistimed tap throw the request away.
        ready=f'neutral_{r}';a.lw(8,r,2376);a.addiu(9,0,11);a.branch(4,8,9,ready)
        a.addiu(9,0,15);a.branch(5,8,9,'done');a.label(ready)
        for off in (2380,2388,2392,2396,2400):
            a.lw(8,r,off);a.addiu(9,0,-1);a.branch(5,8,9,'done')
        for bank in (0x1085,0x10AD):
            a.i(36,8,r,bank+(FLAG(0x94)>>3));a.i(12,8,8,1<<(FLAG(0x94)&7));a.branch(5,8,0,'done')
        for off in (3480,3500,3512):a.lw(8,r,off);a.branch(5,8,0,'done')
    # Revalidate ordinary native fusion eligibility when consent actually arrives.
    a.move(4,17);a.lw(5,16,VARIANT);a.addiu(6,0,1);a.move(7,0)
    a.addiu(8,29,0x300);a.call(fusion.ELIGIBILITY);a.branch(4,2,0,'cancel')
    a.lw(8,29,0x300);a.lw(9,16,SLOT);a.branch(5,8,9,'cancel')
    a.addiu(8,0,1);a.sw(8,16,64)
    a.move(4,17);a.lw(5,16,VARIANT);a.lw(6,16,SLOT);a.call(fusion.BEGIN)
    a.branch(4,2,0,'cancel');a.addiu(8,0,-1);a.sw(8,16,48);a.sw(0,16,60);a.jump('done')
    a.label('cancel');a.addiu(8,0,-1);a.sw(8,16,48);a.sw(8,16,52)
    a.sw(0,16,56);a.sw(0,16,60);a.sw(0,16,64)
    a.label('done');fusion.restore(a);a.jump(previous)
    data=a.finish();assert len(data)<COMMIT-TICK;return data


def commit():
    a=Assembler(COMMIT);fusion.save(a);fusion.restore(a,False);a.call(fusion.COMMIT)
    fusion.save(a,True);a.call(GATE);a.branch(4,2,0,'done')
    a.li(16,CONTROL);a.lw(8,16,64);a.branch(4,8,0,'done')
    a.li(8,participation.CONSUMED);a.lw(8,8);a.i(12,8,8,4);a.branch(4,8,0,'done')
    a.li(8,fusion.CONTROL);a.lw(9,8,20);a.addiu(10,0,2);a.branch(5,9,10,'done')
    a.lw(9,8,24);a.li(10,core.POINTERS);a.lw(10,10);a.branch(5,9,10,'done')
    a.sw(0,16,24);a.addiu(8,0,2);a.sw(8,16,28);a.sw(0,16,64)
    a.lw(8,16,36);a.sw(8,16,40);a.addiu(8,0,-1);a.sw(8,16,48);a.sw(8,16,52)
    a.label('done');fusion.restore(a);a.jr();data=a.finish();assert len(data)<DRAW-COMMIT;return data


def draw(four_humans=True,three_humans=True,show_owner=True,show_countdown=True):
    a=Assembler(DRAW);fusion.save(a);a.call(feed.DRAW);a.call(GATE);a.branch(4,2,0,'done')
    # The clock only advances in released combat, so a request that is live
    # when the round ends can never expire. Gate the drawing on the same
    # battle phase the clock uses, or the offer would stay on screen through
    # the KO and the win pose long after nobody can accept it.
    a.li(8,A(0x2FEB38));a.lw(8,8);a.li(9,0x100000);a.r(0x2B,9,8,9);a.branch(5,9,0,'done')
    a.li(9,0x7FFFE00);a.r(0x2B,9,8,9);a.branch(4,9,0,'done')
    a.lw(9,8,260);a.li(10,A(0x2C6070));a.branch(5,9,10,'done')
    a.lw(8,8);a.addiu(9,0,3);a.branch(5,8,9,'done')
    a.li(16,CONTROL)
    a.lw(17,28,-22176);a.branch(4,17,0,'done')
    a.lw(8,16,60);a.branch(4,8,0,'owner')
    # Both players must be able to read a prompt that asks them to answer, so
    # draw it in every viewport pass instead of only the left one. The pass's
    # own horizontal origin (camera+512) offsets the text, which leaves the
    # single-view and left-hand results byte-identical to before.
    a.li(4,TEXT_P2);a.lw(8,16,INITIATOR);a.branch(4,8,0,'text_ready');a.li(4,TEXT_P1)
    a.label('text_ready');a.lw(8,17,512);a.addiu(8,8,1792+10);a.r(0,5,0,8,4)
    a.li(6,(Y_ORIGIN+screen_y(204))*16);a.li(7,0x80D0FFFF);a.call(feed.TEXT)
    a.lw(8,16,56);a.i(12,8,8,255);a.r(0,8,0,8,6);a.li(4,CHORD_TEXT);a.r(0x2D,4,4,8)
    a.lw(8,17,512);a.addiu(8,8,1792+10);a.r(0,5,0,8,4)
    a.li(6,(Y_ORIGIN+screen_y(217))*16);a.li(7,0x80EEEEEE);a.call(feed.TEXT);a.jump('done')
    # While the fused fighter's controls alternate, say whose turn it is. The
    # answer is computed exactly as the pad routing computes it, from the same
    # two words, so the caption can never disagree with the controller. The
    # request prompt is finished by then, so they share the same line.
    a.label('owner')
    a.lw(8,16,16);a.addiu(9,0,2)
    if four_humans:
        if three_humans:
            a.branch(4,8,9,'human_count');a.addiu(9,0,3)
        a.branch(4,8,9,'human_count');a.addiu(9,0,4)
    a.branch(5,8,9,'done')
    if four_humans:a.label('human_count')
    a.lw(8,16,8);a.lw(9,16,24);a.r(0x2B,8,9,8);a.branch(4,8,0,'done')
    a.lw(8,16,32);a.branch(5,8,0,'done')
    a.lw(8,16,36);a.lw(9,16,40);a.r(0x23,8,8,9)
    a.r(16,12,0);a.r(18,13,0)
    a.li(9,controller.SWAP_UPDATES);a.r(27,0,8,9);a.r(18,11,0);a.r(16,18,0)
    a.r(17,0,12);a.r(19,0,13)
    # Retain the exact routing remainder and next owner across the text call.
    a.i(12,19,11,1);a.i(14,19,19,1)
    # A hidden caption leaves out only its own draw (Mod settings: Fusion).
    # Every register the remaining code reads is set above, so the other
    # caption and the pad routing are unchanged.
    if show_owner:
        a.i(12,11,11,1);a.li(4,TEXT_OWNER[0]);a.branch(4,11,0,'owner_ready');a.li(4,TEXT_OWNER[1])
        a.label('owner_ready');a.lw(8,17,512);a.addiu(8,8,1792+10);a.r(0,5,0,8,4)
        a.li(6,(Y_ORIGIN+screen_y(204))*16);a.li(7,0x80D0FFFF);a.call(feed.TEXT)
    if show_countdown:
        # Warn during the final five active seconds. Pausing freezes both this
        # countdown and the controller's epoch, so the warning cannot run ahead.
        a.li(8,controller.SWAP_UPDATES);a.r(0x23,18,8,18)
        a.i(11,8,18,COUNTDOWN_SECONDS*ACTOR_HZ+1);a.branch(4,8,0,'done')
        a.addiu(18,18,-1);a.move(20,0)
        a.label('count_seconds');a.i(11,8,18,ACTOR_HZ);a.branch(5,8,0,'count_ready')
        a.addiu(18,18,-ACTOR_HZ);a.addiu(20,20,1);a.jump('count_seconds')
        a.label('count_ready');a.r(0,8,0,19,2);a.r(0x2D,8,8,19);a.r(0x2D,8,8,20)
        a.r(0,8,0,8,6);a.li(4,TEXT_COUNTDOWN);a.r(0x2D,4,4,8)
        a.lw(8,17,512);a.addiu(8,8,1792+10);a.r(0,5,0,8,4)
        a.li(6,(Y_ORIGIN+screen_y(217))*16);a.li(7,0x8050CFFF);a.call(feed.TEXT)
    a.label('done');fusion.restore(a);a.jr();data=a.finish();assert len(data)<CONTACT-DRAW;return data


def caption_flags(fusion_mode,show_owner=True,show_countdown=True):
    """(show_owner, show_countdown) emitted for the CONTROL+32 fusion mode."""
    for value in (show_owner,show_countdown):
        if type(value) is not bool:raise ValueError('Fusion caption visibility must be Boolean')
    return (show_owner,show_countdown) if fusion_mode==SWAP_MODE else (True,True)


def accepted_draws(fusion_mode=SWAP_MODE):
    """Every DRAW emission other than the default an installed state may hold.

    The exact pre-four-player caption emissions stay valid in historical
    checkpoints, and a swap-mode install may hide either caption or both.
    Each is shorter than the default, so a validator must also require the
    rest of the default's span to be zero.
    """
    older=(draw(four_humans=False),draw(three_humans=False))
    if fusion_mode!=SWAP_MODE:return older
    return older+tuple(draw(show_owner=owner,show_countdown=countdown) for owner,countdown in CAPTION_VARIANTS)


def contact():
    """Protect the human leader only after its actual native fusion is queued."""
    a=Assembler(CONTACT);fusion.save(a);a.call(GATE);a.branch(4,2,0,'native')
    a.li(16,CONTROL);a.lw(8,16,64);a.branch(4,8,0,'native')
    a.li(8,core.POINTERS);a.lw(17,8)
    a.lw(8,29,fusion.OFFSETS[4]);a.branch(4,8,17,'leader')
    a.lw(8,29,fusion.OFFSETS[5]);a.branch(5,8,17,'native')
    a.label('leader')
    for off in (2376,2380,2388,2392,2396,2400):
        a.lw(8,17,off);a.addiu(8,8,-241);a.i(11,8,8,2);a.branch(5,8,0,'blocked')
    a.label('native');fusion.restore(a);a.jump(fusion.CONTACT)
    a.label('blocked');fusion.restore(a);a.addiu(2,0,1);a.jr()
    data=a.finish();assert len(data)<CHORD_TEXT-CONTACT;return data


def program(previous,show_owner=True,show_countdown=True):
    # Preserve every existing kill-feed/healthbar/render wrapper.
    world=feed.world_code();needle=struct.pack('<I',(3<<26)|(feed.DRAW>>2))
    offsets=[i for i in range(0,len(world),4) if world[i:i+4]==needle]
    if len(offsets)!=1:raise ValueError('Unknown kill-feed render call')
    call=feed.WORLD+offsets[0]
    chords=bytearray(256*64)
    for mask in range(256):
        # Direction names and the joiner follow the match language (pinned like every guest string).
        encoded=localization.guest(' AND ').join(localization.guest(label) for bit,label in ((4,'R3'),(2,'L3'),(16,'UP'),(32,'RIGHT'),(64,'DOWN'),(128,'LEFT')) if mask&bit)
        chords[mask*64:mask*64+len(encoded)]=encoded
    countdown=bytearray(2*COUNTDOWN_SECONDS*COUNTDOWN_STRIDE)
    for player in range(2):
        for seconds in range(1,COUNTDOWN_SECONDS+1):
            label=localization.slot(f'P{player+1} TAKES CONTROL IN {seconds}',COUNTDOWN_STRIDE)
            offset=(player*COUNTDOWN_SECONDS+seconds-1)*COUNTDOWN_STRIDE
            countdown[offset:offset+len(label)]=label
    payloads=[(GATE,gate()),(ELIGIBILITY,eligibility()),(BEGIN,begin()),(TICK,tick(previous)),
        (COMMIT,commit()),(DRAW,draw(show_owner=show_owner,show_countdown=show_countdown)),(CONTACT,contact()),(TEXT_P1,localization.guest('FUSION - P1 TAP R3 TO ACCEPT')+b'\0'),
        (TEXT_P2,localization.guest('FUSION - P2 TAP R3 TO ACCEPT')+b'\0'),(TEXT_OWNER[0],localization.guest('FUSED - PLAYER 1 HAS CONTROL')+bytes(1)),
        (TEXT_OWNER[1],localization.guest('FUSED - PLAYER 2 HAS CONTROL')+bytes(1)),
        (CHORD_TEXT,bytes(chords)),(TEXT_COUNTDOWN,bytes(countdown)),
        (start.HOOK,struct.pack('<2I',(2<<26)|(TICK>>2),0)),
        (fusion.ELIGIBILITY_HOOK,struct.pack('<2I',(2<<26)|(ELIGIBILITY>>2),0)),
        (fusion.BEGIN_HOOK,struct.pack('<2I',(2<<26)|(BEGIN>>2),0)),
        (fusion.COMMIT_HOOK,struct.pack('<I',(2<<26)|(COMMIT>>2))),
        (fusion.contact.PROTECTED,struct.pack('<2I',(2<<26)|(CONTACT>>2),0)),
        (call,struct.pack('<I',(3<<26)|(DRAW>>2)))]
    return payloads


def build_memory(ram,source='<prepared>',show_owner=True,show_countdown=True):
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if len(ram)!=0x8000000 or u(CONTROL)!=mode.MAGIC or u(CONTROL+12)!=mode.COOP:
        raise ValueError('Install captured co-op policy before human fusion')
    show_owner,show_countdown=caption_flags(u(CONTROL+32),show_owner,show_countdown)
    if any(ram[GATE:END]):raise ValueError('Co-op fusion reservation occupied')
    for p,data in fusion.pieces():
        if ram[p:p+len(data)]!=data:raise ValueError(f'Unknown fusion lifecycle:{p:X}')
    previous=(u(start.HOOK)&0x3FFFFFF)<<2
    if u(start.HOOK)>>26!=2 or u(start.HOOK+4) or not 0x07000000<=previous<0x08000000:
        raise ValueError('Missing captured actor frame chain')
    payloads=program(previous,show_owner,show_countdown)
    for p,d in payloads:
        if p in (fusion.ELIGIBILITY_HOOK,fusion.BEGIN_HOOK,fusion.COMMIT_HOOK):
            target={fusion.ELIGIBILITY_HOOK:fusion.ELIGIBILITY,fusion.BEGIN_HOOK:fusion.BEGIN,
                    fusion.COMMIT_HOOK:fusion.COMMIT}[p]
            expected=struct.pack('<I',(2<<26)|(target>>2))+bytes(4)
            if ram[p:p+len(d)]!=expected[:len(d)]:raise ValueError('Fusion entry chain changed')
        elif feed.WORLD<=p<feed.WORLD+len(feed.world_code()):
            if ram[p:p+4]!=struct.pack('<I',(3<<26)|(feed.DRAW>>2)):raise ValueError('Kill-feed render chain changed')
        elif p==fusion.contact.PROTECTED:
            if ram[p:p+8]!=struct.pack('<2I',(2<<26)|(fusion.CONTACT>>2),0):raise ValueError('Fusion contact chain changed')
    return dict(serial=SERIAL,crc=CRC,source=str(source),control=CONTROL,
        blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex()) for p,d in payloads],
        input='Either human requests a native fusion; the other taps R3 before expiry (direction and L3 ignored, a held R3 is not consent).',
        fusion_publish=dict(leader=CONTROL+24,partner=CONTROL+28,epoch=CONTROL+40))
