"""Guest receipts and combat-time expiry for eligible runtime fusions.

The receipt is made after accepted native BEGIN, before the native reload can
replace the survivor. Expiry requests an acknowledged hold; only the serial host
service may publish its rebuilt original body and reactivate its real partner.
Preselected fusion characters never get receipts. Optional lore rules admit
reviewed mortal Potara recipes as well as Fusion Dance.
"""
from native_map import A, FLAG
import struct
import localization
from prototype import Assembler
import fusion_partner_lifecycle as fusion
import fresh_team_combat as core
import team_participation as part
import team_start_gate as start
import guest_killfeed as feed
import guest_healthbars as bars
import native_preparation as native
import battle_mode_policy as policy
import body_swap as body
import body_swap_runner as runner
import body_swap_resources as resources
import fusion_rules
from regional import Y_ORIGIN, screen_y
from native_map import ACTOR_HZ

CAPTURE, ACTIVATE, TICK, FRAME, JOB, DRAW = (0x070D0000,0x070D2000,0x070D2800,0x070D5000,0x070D5800,0x070D6800)
OLD, TEXT, RECORDS, CONTROL, JOB_CONTROL, END = (0x070D7800,0x070D8000,0x06BD0000,0x070DF000,0x070DF100,0x070E0000)
MAGIC=0x46555331
STRIDE=0x400
ROW_OFFSETS=(0x100,0x200)
# Status: 0 empty/cancelled, 1 accepted timed fusion, 2 fused countdown,
# 3 expiry held for service, 5 fully defused. Failure >=100 retains the hold.
F=dict(status=0,remaining=4,leader=8,partner=12,leader_id=16,partner_id=20,
       leader_mid=24,partner_mid=28,leader_model=32,partner_model=36,
       leader_resource=40,partner_resource=44,leader_slot=48,partner_slot=52,
       leader_controller=56,leader_cpu=60,partner_controller=64,partner_cpu=68,
       generation=72,result=76,partner_input1=80,partner_input2=84,partner_input3=88,
       leader_character=92)
JUMP=lambda p:struct.pack('<2I',(2<<26)|(p>>2),0)


def scope(a,fail):
    core.gate(a,fail);a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,fail)
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,fail)
    a.lw(9,8,8);a.branch(5,9,10,fail);a.lw(9,8,12);a.branch(4,9,0,fail)
    a.li(8,core.PAIR+4);a.lw(9,8);a.branch(5,9,0,fail)


def capture():
    a=Assembler(CAPTURE);fusion.save(a);scope(a,'done')
    a.lw(16,29,fusion.OFFSETS[4]);a.lw(17,16);a.i(11,8,17,policy.emitted_actors());a.branch(4,8,0,'done')
    a.lw(8,16,2388);a.addiu(9,0,241);a.branch(4,8,9,'timed_kind')
    a.addiu(9,0,242);a.branch(5,8,9,'done');a.li(8,CONTROL);a.lw(8,8,44);a.branch(4,8,0,'done')
    a.lw(8,16,4816)
    for result in fusion_rules.MORTAL_POTARA_RESULTS:
        a.addiu(9,0,result);a.branch(4,8,9,'timed_kind')
    a.jump('done');a.label('timed_kind')
    a.lw(8,16,4856);a.addiu(9,8,-1);a.i(11,9,9,policy.emitted_capacity()-1);a.branch(4,9,0,'done')
    a.i(12,9,17,1);a.r(0,18,0,8,1);a.r(0x21,18,18,9);a.r(0,8,0,18,2)
    a.li(9,core.POINTERS);a.r(0x21,8,8,9);a.lw(19,8)
    a.r(0,8,0,17,10);a.li(20,RECORDS);a.r(0x21,20,20,8)
    a.lw(8,20);a.addiu(8,8,-1);a.i(11,8,8,3);a.branch(5,8,0,'done')
    a.li(8,part.CONSUMED);a.lw(8,8);a.addiu(9,0,1);a.r(4,9,18,9)
    a.r(0x24,8,8,9);a.branch(5,8,0,'done')
    for i,r in enumerate((16,19)):
        a.lw(21,r,12);a.i(11,8,21,12);a.branch(4,8,0,'done')
        a.r(0,8,0,21,2);a.li(9,core.MODELS);a.r(0x21,8,8,9);a.lw(22,8)
        fusion.pointer(a,22,0x1670,'done');a.lw(8,22,16);a.branch(5,8,21,'done')
        a.lw(23,r,0x994);a.lw(8,r,0x998);a.r(0x2B,8,23,8);a.branch(4,8,0,'done')
        fusion.row_address(a,24,r,23,8);a.lw(8,24,64);a.branch(6,8,0,'done')
        for off,reg in ((8+4*i,r),(16+4*i,17 if i==0 else 18),(24+4*i,21),(32+4*i,22),(48+4*i,23)):
            a.sw(reg,20,off)
        for dst,base,off in ((40+4*i,22,20),(56+8*i,r,4),(60+8*i,r,0x1278)):
            a.lw(8,base,off);a.sw(8,20,dst)
        for off in range(0,164,4):a.lw(8,24,off);a.sw(8,20,ROW_OFFSETS[i]+off)
    for i,off in enumerate((0x127C,0x1280,0x1284)):a.lw(8,19,off);a.sw(8,20,80+4*i)
    a.lw(21,20,44);fusion.pointer(a,21,56,'done')
    for off in range(0,56,4):a.lw(8,21,off);a.sw(8,20,0x300+off)
    a.li(8,body.FINISHED);a.lw(8,8);a.sw(8,20,96)
    a.lw(8,16,4816);a.sw(8,20,76);a.lw(8,20,ROW_OFFSETS[0]);a.sw(8,20,92)
    a.li(8,CONTROL);a.lw(9,8,16);a.lw(10,16,2388);a.addiu(11,0,242)
    a.branch(5,10,11,'duration_ready');a.r(0,9,0,9,1)
    a.label('duration_ready');a.sw(9,20,4);a.sw(9,20,100);a.lw(9,8,24);a.addiu(9,9,1)
    a.sw(9,8,24);a.sw(9,20,72);a.addiu(9,0,1);a.sw(9,20)
    a.label('done');fusion.restore(a);a.jr();data=a.finish();assert len(data)<ACTIVATE-CAPTURE;return data


def activate():
    """a0 leader, a1 actual consumed physical; called after forward CONSUME."""
    a=Assembler(ACTIVATE);fusion.save(a);scope(a,'done')
    a.lw(16,29,fusion.OFFSETS[4]);a.lw(17,16);a.i(11,8,17,policy.emitted_actors());a.branch(4,8,0,'done')
    a.r(0,8,0,17,10);a.li(18,RECORDS);a.r(0x21,18,18,8)
    a.lw(8,18);a.addiu(9,0,1);a.branch(5,8,9,'done')
    a.lw(8,18,8);a.branch(5,8,16,'done');a.lw(8,18,20);a.lw(9,29,fusion.OFFSETS[5]);a.branch(5,8,9,'done')
    a.lw(9,16,0x994);fusion.row_address(a,10,16,9,8)
    a.lw(8,10);a.lw(9,18,76);a.branch(5,8,9,'done')
    a.addiu(8,0,2);a.sw(8,18)
    a.label('done');fusion.restore(a);a.jr();return a.finish()


def active_combat(a,fail):
    a.li(8,start.CONTROL);a.lw(8,8);a.branch(5,8,0,fail)
    for p,mask in ((A(0x3337B8),0x3900),(A(0x333700),0xFFFF)):
        a.li(8,p);a.lw(8,8);a.i(12,8,8,mask);a.branch(5,8,0,fail)
    a.li(8,A(0x3337C0));a.lw(8,8);a.addiu(9,0,1);a.branch(5,8,9,fail)
    a.li(8,native.CONTROL+16);a.lw(8,8);a.branch(5,8,0,fail)
    a.lw(8,28,-22364);a.lw(8,8,628);a.branch(5,8,0,fail)
    a.li(8,A(0x2FEB38));a.lw(8,8);fusion.pointer(a,8,264,fail,9,11)
    a.lw(9,8,260);a.li(11,A(0x2C6070));a.branch(5,9,11,fail)
    a.lw(8,8);a.addiu(9,0,3);a.branch(5,8,9,fail)


def tick():
    a=Assembler(TICK);fusion.save(a);scope(a,'done');active_combat(a,'done')
    a.li(16,RECORDS);a.move(17,0)
    a.label('record');a.lw(8,16);a.addiu(9,0,1);a.branch(4,8,9,'pending')
    a.addiu(9,0,2);a.branch(5,8,9,'next');a.lw(18,16,8)
    a.li(8,core.POINTERS);a.r(0,9,0,17,2);a.r(0x21,8,8,9);a.lw(8,8);a.branch(5,8,18,'cancel')
    a.lw(8,18);a.branch(5,8,17,'cancel');a.lw(8,18,4);a.lw(9,16,56);a.branch(5,8,9,'cancel')
    a.li(8,body.FINISHED);a.lw(8,8);a.lw(9,16,96);a.branch(4,8,9,'body_identity')
    for i in range(2):
        a.li(8,body.ROWS+i*64+4);a.lw(8,8);a.branch(4,8,18,'cancel')
    a.label('body_identity')
    a.move(4,18);a.call(feed.ROW);a.branch(4,2,0,'cancel');a.lw(8,2);a.branch(6,8,0,'cancel')
    a.li(8,part.CONSUMED);a.lw(8,8);a.lw(9,16,20);a.addiu(10,0,1);a.r(4,10,9,10)
    a.r(0x24,8,8,10);a.branch(4,8,0,'cancel')
    a.lw(8,16,4);a.branch(4,8,0,'expired');a.addiu(8,8,-1);a.sw(8,16,4);a.branch(5,8,0,'next')
    a.label('expired')
    # A busy move/transform finishes naturally before the held reload.
    a.lw(8,18,2376);a.addiu(9,0,11);a.branch(4,8,9,'idle');a.addiu(9,0,15);a.branch(5,8,9,'next')
    a.label('idle')
    for off in (2380,2388,2392,2396,2400):a.lw(8,18,off);a.addiu(9,0,-1);a.branch(5,8,9,'next')
    for off in (3480,3500,3512):a.lw(8,18,off);a.branch(5,8,0,'next')
    for bank in (0x1085,0x10AD):
        a.i(36,8,18,bank+(FLAG(0x94)>>3));a.i(12,8,8,1<<(FLAG(0x94)&7));a.branch(5,8,0,'next')
    a.li(8,body.CONTROL);a.lw(9,8);a.li(10,body.MAGIC);a.branch(5,9,10,'body_free')
    a.lw(9,8,16);a.branch(5,9,0,'next');a.label('body_free')
    a.lw(19,28,-22364)
    for off in (600,612,628):a.lw(8,19,off);a.branch(5,8,0,'next')
    a.lw(8,19,604);a.lw(9,19,608);a.branch(5,8,9,'next')
    for physical in range(2,policy.emitted_actors()):
        a.li(8,fusion.requests.RECORDS+(physical-2)*64+4);a.lw(8,8);a.addiu(8,8,-2)
        a.i(11,8,8,3);a.branch(5,8,0,'next')
    a.li(8,native.CONTROL);a.sw(19,8,24);a.addiu(9,0,1);a.sw(9,8,16)
    a.addiu(9,0,3);a.sw(9,16);a.li(8,CONTROL);a.sw(17,8,28);a.jump('done')
    a.label('pending');a.lw(18,16,8)
    for off in (2376,2380,2388,2392,2396,2400):
        a.lw(8,18,off);a.addiu(8,8,-241);a.i(11,8,8,2);a.branch(5,8,0,'next')
    a.label('cancel');a.sw(0,16)
    a.label('next');a.addiu(16,16,STRIDE);a.addiu(17,17,1);a.addiu(8,0,policy.emitted_actors());a.branch(5,17,8,'record')
    a.label('done');fusion.restore(a);a.jr();data=a.finish();assert len(data)<FRAME-TICK;return data


def frame(previous):
    a=Assembler(FRAME);a.addiu(29,29,-16);a.i(63,31,29,0);a.call(previous)
    a.i(55,31,29,0);a.addiu(29,29,16);fusion.save(a);scope(a,'done')
    a.call(TICK);a.li(8,CONTROL);a.lw(9,8,28);a.i(11,10,9,policy.emitted_actors());a.branch(4,10,0,'done')
    a.r(0,9,0,9,10);a.li(8,RECORDS);a.r(0x21,8,8,9);a.lw(8,8);a.addiu(9,0,3)
    a.branch(5,8,9,'done');a.call(JOB)
    a.label('done');fusion.restore(a);a.jr();return a.finish()


def draw(previous,stacked=True,quad_support=False):
    a=Assembler(DRAW);fusion.save(a);a.call(previous);scope(a,'done')
    if quad_support:
        # Multiplayer fusion draws the same receipt underneath each pair's
        # owner/countdown labels. Keep the ordinary two-player HUD unchanged.
        import multiplayer_fusion as multi
        a.li(8,multi.CONTROL);a.lw(9,8);a.li(11,multi.MAGIC);a.branch(5,9,11,'legacy_caption')
        a.call(multi.SHARED);a.branch(4,2,0,'done');a.call(multi.DRAW);a.jump('done')
        a.label('legacy_caption')
    a.li(8,CONTROL);a.lw(8,8,20);a.branch(4,8,0,'done')
    a.li(8,A(0x2FEB38));a.lw(8,8);fusion.pointer(a,8,264,'done',9,11)
    a.lw(9,8,260);a.li(11,A(0x2C6070));a.branch(5,9,11,'done')
    a.lw(8,8);a.addiu(9,0,3);a.branch(5,8,9,'done')
    a.lw(17,28,-22176);fusion.pointer(a,17,832,'done');a.li(16,RECORDS);a.move(18,0);a.move(19,0)
    a.label('record');a.lw(8,16);a.addiu(8,8,-2);a.i(11,8,8,2);a.branch(4,8,0,'next')
    # Extra CPU fusions are visible when watched; do not stack every NPC's
    # timer across the whole screen. Physical IDs are not screen row numbers.
    import fresh_team_camera as camera
    a.i(11,8,18,2);a.branch(5,8,0,'visible_timer')
    a.li(8,camera.SUCCESSOR_CONTROL);a.lw(9,8,8);a.branch(4,9,18,'visible_timer')
    a.lw(9,8,12);a.branch(5,9,18,'next')
    a.label('visible_timer')
    a.lw(8,16,4);a.addiu(8,8,ACTOR_HZ-1);a.addiu(9,0,ACTOR_HZ);a.r(27,0,8,9);a.r(18,8,0)
    a.r(0,8,0,8,5);a.li(4,TEXT);a.r(0x21,4,4,8)
    a.lw(5,17,512);a.addiu(5,5,1792+8);a.r(0,5,0,5,4)
    a.r(0,6,0,19,5);a.addiu(6,6,Y_ORIGIN+screen_y(232 if stacked else 168));a.r(0,6,0,6,4)
    a.li(7,0x80A0FFFF);a.call(feed.TEXT)
    a.lw(8,16,4);a.li(9,120);a.r(24,0,8,9);a.r(18,8,0);a.li(9,CONTROL);a.lw(9,9,16);a.lw(10,16,100);total_tag='timer_total_'+str(a.pc)
    a.branch(4,10,0,total_tag);a.move(9,10);a.label(total_tag)
    a.r(27,0,8,9);a.r(18,6,0);a.lw(4,17,512);a.addiu(4,4,1792+8)
    a.r(0,5,0,19,5);a.addiu(5,5,Y_ORIGIN+screen_y(232 if stacked else 168)+12);a.r(0x21,6,6,4);a.addiu(7,5,3)
    for r in (4,5,6,7):a.r(0,r,0,r,4)
    a.li(8,0x80A0FFFF);a.call(bars.RECT);a.addiu(19,19,1)
    a.label('next');a.addiu(16,16,STRIDE);a.addiu(18,18,1);a.addiu(8,0,policy.emitted_actors());a.branch(5,18,8,'record')
    a.label('done');fusion.restore(a);a.jr();return a.finish()


def program(previous,draw_previous):
    return [(CAPTURE,capture()),(ACTIVATE,activate()),(TICK,tick()),(FRAME,frame(previous)),
            (JOB,core.rebound(runner.job_code,JOB=JOB,CONTROL=JOB_CONTROL,PROTECTED=DRAW)()),
            (DRAW,draw(draw_previous))]


def build_memory(ram,seconds=40,show_timer=True,source='<prepared>',lore=False,animate=True):
    if type(seconds) is not int or not 1<=seconds<=300:raise ValueError('Fusion duration must be 1..300 whole seconds')
    if type(show_timer) is not bool:raise ValueError('Fusion timer visibility must be Boolean')
    if type(lore) is not bool:raise ValueError('Fusion lore rules must be Boolean')
    if type(animate) is not bool:raise ValueError('Defusion animation must be Boolean')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if len(ram)!=0x8000000:raise ValueError('Requires captured EE RAM')
    if u(CONTROL)==MAGIC:
        validate_memory(ram)
        if (u(CONTROL+16),u(CONTROL+20),u(CONTROL+44),u(CONTROL+48))!=(seconds*ACTOR_HZ,int(show_timer),int(lore),int(animate)):raise ValueError('Fusion options require a newly prepared match')
        import four_player_mode
        data=four_player_mode.dependency_override(ram,DRAW,draw(u(CONTROL+36)))
        parts=[] if bytes(ram[DRAW:DRAW+len(data)])==data else [(DRAW,data)]
        return resources.parts_manifest(ram,parts,source=str(source),control=CONTROL,status='TIMED FUSION VERIFIED')
    if any(ram[CAPTURE:END]) or any(ram[RECORDS:RECORDS+policy.emitted_actors()*STRIDE]):raise ValueError('Timed fusion reservation occupied')
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if count not in policy.ACTOR_COUNTS or u(core.MODE+8)!=manager:raise ValueError('Captured fusion world required')
    original=bytes(ram[runner.HOOK:runner.HOOK+8])
    if original==body.NATIVE(runner.HOOK,8):previous=OLD
    elif original==JUMP(runner.ENTRY):previous=runner.ENTRY
    else:raise ValueError('Unreviewed native frame chain for timed fusion')
    world=bytes(ram[feed.WORLD:feed.WORLD+len(feed.world_code())]);calls=[]
    import coop_fusion
    import viewport_hud
    for i in range(0,len(world),4):
        word=struct.unpack_from('<I',world,i)[0]
        if word>>26==3 and ((word&0x3FFFFFF)<<2) in (feed.DRAW,coop_fusion.DRAW,viewport_hud.CODE):calls.append((feed.WORLD+i,(word&0x3FFFFFF)<<2))
    if len(calls)!=1:raise ValueError('Unreviewed fusion HUD chain')
    draw_at,draw_previous=calls[0];control=bytearray(0x100)
    struct.pack_into('<11I',control,0,MAGIC,manager,count,0,seconds*ACTOR_HZ,int(show_timer),0,0xFFFFFFFF,previous,draw_previous,draw_at)
    struct.pack_into('<I',control,44,int(lore))
    struct.pack_into('<I',control,48,int(animate))
    label_seconds=seconds*(2 if lore else 1)
    labels=bytearray((label_seconds+1)*32)
    for n in range(label_seconds+1):
        label=localization.slot(f'FUSION {n}S' if n else 'DEFUSION PENDING',32);labels[n*32:n*32+len(label)]=label
    lifecycle=[]
    for at,old,new in ((fusion.BEGIN,fusion.begin_code(),fusion.begin_code(True)),(fusion.COMMIT,fusion.commit_code(),fusion.commit_code(True))):
        if bytes(ram[at:at+len(old)])!=old or any(ram[at+len(old):at+len(new)]):raise ValueError('Fusion lifecycle changed before timed upgrade')
        lifecycle.append((at,new))
    parts=program(previous,draw_previous)+lifecycle+[(CONTROL,bytes(control)),(JOB_CONTROL,bytes(0x100)),(RECORDS,bytes(policy.emitted_actors()*STRIDE)),(TEXT,bytes(labels)),
        (runner.HOOK,JUMP(FRAME)),(draw_at,struct.pack('<I',(3<<26)|(DRAW>>2)))]
    if previous==OLD:parts.append((OLD,original+struct.pack('<2I',(2<<26)|((runner.HOOK+8)>>2),0)))
    return resources.parts_manifest(ram,parts,source=str(source),control=CONTROL,entry=FRAME,status='TIMED FUSION; SERIAL HOST WORKER REQUIRED')


def validate_memory(ram):
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    import coop_fusion
    import viewport_hud
    if u(CONTROL)!=MAGIC or not 30<=u(CONTROL+16)<=9000 or u(CONTROL+20)>1 or u(CONTROL+44)>1:raise ValueError('Invalid timed fusion configuration')
    if (u(CONTROL+4),u(CONTROL+8))!=(u(core.ACTORS),u(core.MODE+4)):raise ValueError('Timed fusion world changed')
    if u(CONTROL+32) not in (OLD,runner.ENTRY) or u(CONTROL+36) not in (feed.DRAW,coop_fusion.DRAW,viewport_hud.CODE):
        raise ValueError('Unreviewed timed fusion continuation')
    if u(CONTROL+32)==OLD:
        expected=body.NATIVE(runner.HOOK,8)+struct.pack('<2I',(2<<26)|((runner.HOOK+8)>>2),0)
        if bytes(ram[OLD:OLD+len(expected)])!=expected:raise ValueError('Timed fusion native frame continuation changed')
    for at,data in program(u(CONTROL+32),u(CONTROL+36)):
        import four_player_mode
        data=four_player_mode.dependency_override(ram,at,data)
        if bytes(ram[at:at+len(data)])!=data:
            if at!=DRAW or bytes(ram[at:at+len(data)])!=draw(u(CONTROL+36),stacked=False):
                raise ValueError(f'Timed fusion program changed:{at:08X}')
    for at,data in ((fusion.BEGIN,fusion.begin_code(True)),(fusion.COMMIT,fusion.commit_code(True))):
        if bytes(ram[at:at+len(data)])!=data:raise ValueError('Timed fusion native lifecycle changed')
    if bytes(ram[runner.HOOK:runner.HOOK+8])!=JUMP(FRAME):raise ValueError('Timed fusion frame chain changed')
    return u(CONTROL+32)


def dependency_override(ram,address,expected):
    if u32(ram,CONTROL)!=MAGIC:return expected
    if address==u32(ram,CONTROL+40) and expected==struct.pack('<I',(3<<26)|(u32(ram,CONTROL+36)>>2)):
        actual=struct.pack('<I',(3<<26)|(DRAW>>2))
        if bytes(ram[address:address+4])!=actual:raise ValueError('Timed fusion HUD hook changed')
        return actual
    candidates={fusion.BEGIN:(fusion.begin_code(),fusion.begin_code(True)),fusion.COMMIT:(fusion.commit_code(),fusion.commit_code(True))}
    if address in candidates:
        old,new=candidates[address]
        if expected==old:
            if bytes(ram[address:address+len(new)])!=new:raise ValueError('Timed fusion lifecycle changed')
            return new
    return expected


def u32(ram,p):return struct.unpack_from('<I',ram,p)[0]
