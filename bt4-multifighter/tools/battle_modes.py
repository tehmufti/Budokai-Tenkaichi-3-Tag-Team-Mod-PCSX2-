"""Late, captured-match FFA/co-op installation; never changes native identities.

Run after ordinary preparation and before intro release. Team mode is a no-op.
FFA replaces only reviewed policy payloads. Native winner/result code remains
responsible for ending the match; its predicate waits for the last survivor.

The lock-on queue at lockon_queue.CODE exists in two exact emissions: the
original R3 one and the button-aware one (Mod settings L3). The FFA/co-op
variant keeps whichever flavour is installed; the flavour is recognised by its
bytes, so no mode-control word records it and the CONTROL layout is unchanged.
"""
from native_map import A, CRC, SERIAL
import struct
from prototype import Assembler
import fresh_team_combat as core
import fresh_team_ai as ai
import team_participation as part
import team_defeat as defeat
import guest_killfeed as feed
import guest_healthbars as bars
import lockon_queue as lockon
import lockon_switch as old_lockon
import cpu_retaliation as retaliation
import los_targets as los
import battle_mode_policy as policy

CONTROL=policy.CONTROL
FFA_DEFEAT, END = 0x07120000, 0x07130000
# Three to five teams: the native time-over decision (also double KO and double ring-out) and its replacement.
TIME_HOOK, TIME_OVER = A(0x217E38), 0x07121000
TIME_NATIVE = struct.pack('<2I', 0x27BDFFF0, 0xFFB00000)        # addiu sp,sp,-16 ; sd s0,0(sp)
SAVED=tuple(range(3,29))+(30,31)


def squad_defeat_code():
    """20B878(side) for three to five teams, in the free-for-all predicate's cave.

    The native winner routine keeps asking whether side 0 or side 1 is defeated. While two teams have a living
    fighter the answer is no. When one team is left it names a living member w (a player's fighter first) and the
    other native side is the defeated one, so the native result runs for w's side; w's teammates on the other side
    simply stay alive. The SQUAD block records the living teams, the winning team and w; CONTROL+44 gets w, which
    is what the result presentation shows for a free-for-all.
    """
    F=policy.SQUAD_FIELDS
    a=Assembler(FFA_DEFEAT);a.addiu(29,29,-0x100)
    for i,r in enumerate(SAVED):a.i(63,r,29,8*i)
    core.gate(a,'fallback');a.li(16,CONTROL);a.lw(8,16);a.li(9,policy.MAGIC)
    a.branch(5,8,9,'fallback');a.lw(8,16,4);a.lw(9,28,-22364)
    a.branch(5,8,9,'fallback');a.lw(8,16,12);a.addiu(9,0,policy.FFA)
    a.branch(5,8,9,'fallback')
    a.li(23,policy.SQUAD);a.lw(8,23);a.li(9,policy.SQUAD_MAGIC);a.branch(5,8,9,'fallback')
    a.lw(8,23,F['manager']);a.lw(9,28,-22364);a.branch(5,8,9,'fallback')
    # s1 count, s2 index, s3 living-team mask, s4 first living fighter, s5 side asked, s6 present, fp first living player
    a.move(17,10);a.move(18,0);a.move(19,0)
    a.addiu(20,0,-1);a.move(21,4);a.lw(22,16,20);a.addiu(30,0,-1)
    a.label('scan');a.addiu(8,0,1);a.r(4,8,18,8);a.r(0x24,8,8,22)
    a.branch(4,8,0,'next');a.li(8,core.POINTERS);a.r(0,9,0,18,2)
    a.r(0x2D,8,8,9);a.lw(4,8);a.branch(4,4,0,'invalid')
    a.lw(8,4);a.branch(5,8,18,'invalid');a.call(feed.ROW)
    a.branch(4,2,0,'invalid');a.lw(8,2);a.branch(6,8,0,'next')
    a.r(0x21,8,23,18);a.i(36,8,8,F['team_of'])
    a.i(11,9,8,policy.MAX_TEAMS);a.branch(4,9,0,'invalid')
    a.addiu(9,0,1);a.r(4,9,8,9);a.r(0x25,19,19,9)
    a.branch(1,20,1,'seen');a.move(20,18);a.label('seen')
    a.lw(9,23,F['humans']);a.addiu(8,0,1);a.r(4,8,18,8);a.r(0x24,9,9,8);a.branch(4,9,0,'next')
    a.branch(1,30,1,'next');a.move(30,18)
    a.label('next');a.addiu(18,18,1);a.branch(5,18,17,'scan')
    a.sw(19,23,F['alive'])
    a.addiu(8,19,-1);a.r(0x24,8,8,19);a.branch(5,8,0,'undecided')
    a.branch(4,19,0,'draw')
    a.branch(1,30,0,'winner');a.move(20,30)
    a.label('winner');a.sw(20,16,44);a.sw(20,23,F['winner'])
    a.r(0x21,8,23,20);a.i(36,8,8,F['team_of']);a.sw(8,23,F['winner_team'])
    a.i(12,8,20,1);a.r(0x26,2,8,21);a.jump('return')
    a.label('draw');a.addiu(8,0,-1);a.sw(8,16,44);a.addiu(2,0,1);a.jump('return')
    a.label('undecided');a.addiu(8,0,-1);a.sw(8,23,F['winner_team']);a.sw(8,23,F['winner'])
    a.label('invalid');a.move(2,0);a.addiu(8,0,-1);a.sw(8,16,44)
    a.label('return')
    for i,r in enumerate(SAVED):a.i(55,r,29,8*i)
    a.addiu(29,29,0x100);a.jr()
    a.label('fallback')
    for i,r in enumerate(SAVED):a.i(55,r,29,8*i)
    a.addiu(29,29,0x100);a.jump(defeat.CODE)
    data=a.finish();assert len(data)<0x1000;return data


def squad_timeover_code():
    """217E38(result) for three to five teams: who wins when the time is over.

    A team's score is its remaining health as a share of its full health, over every fighter of the team (a fallen
    fighter counts with no health and its full maximum). Two teams are compared by cross-multiplication of the
    four sums, sumHealth_a * sumMax_b against sumHealth_b * sumMax_a, as exact 64-bit products (MULTU, HI:LO), so
    no division and no rounding decides; a tie keeps the lower team number. Only a team with a living fighter can
    win. The winner fighter w is that team's first living player, else its first living fighter; the native
    result gets w's row, the SQUAD block the team and w. battle_mode_policy.timeover_winner is the same rule.
    With fusions (feature 'fusion') a consumed partner is not counted: the fused fighter stands for the pair.
    """
    F=policy.SQUAD_FIELDS;HEALTH,FULL=0x100,0x118
    a=Assembler(TIME_OVER);a.addiu(29,29,-0x140)
    for i,r in enumerate(SAVED):a.i(63,r,29,8*i)
    a.move(21,4)
    core.gate(a,'fallback');a.li(16,CONTROL);a.lw(8,16);a.li(9,policy.MAGIC)
    a.branch(5,8,9,'fallback');a.lw(8,16,4);a.lw(9,28,-22364)
    a.branch(5,8,9,'fallback');a.lw(8,16,12);a.addiu(9,0,policy.FFA)
    a.branch(5,8,9,'fallback')
    a.li(23,policy.SQUAD);a.lw(8,23);a.li(9,policy.SQUAD_MAGIC);a.branch(5,8,9,'fallback')
    a.lw(8,23,F['manager']);a.lw(9,28,-22364);a.branch(5,8,9,'fallback')
    # s1 count, s2 index, s3 living-team mask, s5 result, s6 present, s7 SQUAD
    a.move(17,10);a.move(18,0);a.move(19,0);a.lw(22,16,20)
    if policy.squad_feature('fusion'):
        # A fighter consumed by a fusion has no health of its own while fused: it is left out of both sums and
        # the fused fighter's health and maximum stand for the pair (after the fusion ends each counts again).
        a.li(8,part.CONSUMED);a.lw(8,8);a.r(0x24,8,8,22);a.r(0x26,22,22,8)
    for k in range(policy.MAX_TEAMS):a.sw(0,29,HEALTH+4*k);a.sw(0,29,FULL+4*k)
    a.label('scan');a.addiu(8,0,1);a.r(4,8,18,8);a.r(0x24,8,8,22)
    a.branch(4,8,0,'next');a.li(8,core.POINTERS);a.r(0,9,0,18,2)
    a.r(0x2D,8,8,9);a.lw(4,8);a.branch(4,4,0,'next')
    a.lw(8,4);a.branch(5,8,18,'next');a.call(feed.ROW)
    a.branch(4,2,0,'next');a.lw(13,2,4);a.branch(6,13,0,'next')        # t5 full health; none: not counted
    a.lw(12,2);a.branch(7,12,0,'has_health');a.move(12,0)              # t4 health, never below zero
    a.label('has_health');a.r(0x2B,9,13,12);a.branch(4,9,0,'bounded');a.move(12,13)   # nor above its maximum
    a.label('bounded');a.r(0x21,8,23,18);a.i(36,24,8,F['team_of'])      # t8 team
    a.i(11,9,24,policy.MAX_TEAMS);a.branch(4,9,0,'next')
    a.r(0,8,0,24,2);a.r(0x21,8,8,29)
    a.lw(9,8,HEALTH);a.r(0x21,9,9,12);a.sw(9,8,HEALTH)
    a.lw(9,8,FULL);a.r(0x21,9,9,13);a.sw(9,8,FULL)
    a.branch(4,12,0,'next');a.addiu(9,0,1);a.r(4,9,24,9);a.r(0x25,19,19,9)   # a living fighter: the team can win
    a.label('next');a.addiu(18,18,1);a.branch(5,18,17,'scan')
    a.branch(4,19,0,'fallback')                                         # nobody alive: the native tie rules
    # s4 best team (-1), t8 candidate: ahead when health[t]*full[best] > health[best]*full[t] (64-bit products)
    a.addiu(20,0,-1);a.move(24,0)
    a.label('team');a.addiu(8,0,1);a.r(4,8,24,8);a.r(0x24,8,8,19);a.branch(4,8,0,'team_next')
    a.branch(1,20,0,'take')                                             # bltz best: the first living team
    a.r(0,8,0,24,2);a.r(0x21,8,8,29);a.lw(10,8,HEALTH);a.lw(11,8,FULL)
    a.r(0,8,0,20,2);a.r(0x21,8,8,29);a.lw(12,8,HEALTH);a.lw(13,8,FULL)
    a.r(0x19,0,10,13);a.r(0x10,14,0,0);a.r(0x12,15,0,0)                 # t6:t7 = health[t]*full[best]
    a.r(0x19,0,12,11);a.r(0x10,9,0,0);a.r(0x12,8,0,0)                   # t1:t0 = health[best]*full[t]
    a.r(0x2B,25,9,14);a.branch(5,25,0,'take')                           # high word larger
    a.branch(5,14,9,'team_next')                                        # high word smaller
    a.r(0x2B,25,8,15);a.branch(4,25,0,'team_next')                      # equal high words: the low word decides
    a.label('take');a.move(20,24)
    a.label('team_next');a.addiu(24,24,1);a.addiu(9,0,policy.MAX_TEAMS);a.branch(5,24,9,'team')
    # w: the best team's first living player, else its first living fighter (fp, t9)
    a.move(18,0);a.addiu(30,0,-1);a.addiu(25,0,-1)
    a.label('find');a.addiu(8,0,1);a.r(4,8,18,8);a.r(0x24,8,8,22)
    a.branch(4,8,0,'find_next');a.r(0x21,8,23,18);a.i(36,8,8,F['team_of']);a.branch(5,8,20,'find_next')
    a.li(8,core.POINTERS);a.r(0,9,0,18,2);a.r(0x2D,8,8,9);a.lw(4,8);a.branch(4,4,0,'find_next')
    a.lw(8,4);a.branch(5,8,18,'find_next');a.call(feed.ROW)
    a.branch(4,2,0,'find_next');a.lw(8,2);a.branch(6,8,0,'find_next')
    a.branch(1,25,1,'first_known');a.move(25,18);a.label('first_known')
    a.lw(9,23,F['humans']);a.addiu(8,0,1);a.r(4,8,18,8);a.r(0x24,9,9,8);a.branch(4,9,0,'find_next')
    a.branch(1,30,1,'find_next');a.move(30,18)
    a.label('find_next');a.addiu(18,18,1);a.branch(5,18,17,'find')
    a.branch(1,30,1,'named');a.move(30,25);a.label('named')
    a.branch(1,30,0,'fallback')
    a.sw(19,23,F['alive']);a.sw(20,23,F['winner_team']);a.sw(30,23,F['winner']);a.sw(30,16,44)
    a.i(12,2,30,1);a.addiu(2,2,1);a.sw(2,21,0)
    for i,r in enumerate(SAVED):a.i(55,r,29,8*i)
    a.addiu(29,29,0x140);a.jr()
    a.label('fallback')
    for i,r in enumerate(SAVED):a.i(55,r,29,8*i)
    a.addiu(29,29,0x140)
    for word in struct.unpack('<2I',TIME_NATIVE):a.emit(word)
    a.jump(TIME_HOOK+8)
    data=a.finish();assert TIME_OVER+len(data)<=TIME_OVER+0x1000;return data


def defeat_code():
    if policy.emitted_squads() is not None:return squad_defeat_code()
    a=Assembler(FFA_DEFEAT);a.addiu(29,29,-0x100)
    for i,r in enumerate(SAVED):a.i(63,r,29,8*i)
    core.gate(a,'fallback');a.li(16,CONTROL);a.lw(8,16);a.li(9,policy.MAGIC)
    a.branch(5,8,9,'fallback');a.lw(8,16,4);a.lw(9,28,-22364)
    a.branch(5,8,9,'fallback');a.lw(8,16,12);a.addiu(9,0,policy.FFA)
    a.branch(5,8,9,'fallback');a.move(17,10);a.move(18,0);a.move(19,0)
    a.addiu(20,0,-1);a.move(21,4);a.lw(22,16,20)
    a.label('scan');a.addiu(8,0,1);a.r(4,8,18,8);a.r(0x24,8,8,22)
    a.branch(4,8,0,'next');a.li(8,core.POINTERS);a.r(0,9,0,18,2)
    a.r(0x2D,8,8,9);a.lw(4,8);a.branch(4,4,0,'invalid')
    a.lw(8,4);a.branch(5,8,18,'invalid');a.call(feed.ROW)
    a.branch(4,2,0,'invalid');a.lw(8,2);a.branch(6,8,0,'next')
    a.addiu(19,19,1);a.move(20,18)
    a.label('next');a.addiu(18,18,1);a.branch(5,18,17,'scan')
    a.i(11,8,19,2);a.branch(4,8,0,'invalid')
    a.sw(20,16,44);a.branch(4,19,0,'draw')
    a.i(12,8,20,1);a.r(0x26,2,8,21);a.jump('return')
    a.label('draw');a.addiu(2,0,1);a.jump('return')
    a.label('invalid');a.move(2,0);a.addiu(8,0,-1);a.sw(8,16,44)
    a.label('return')
    for i,r in enumerate(SAVED):a.i(55,r,29,8*i)
    a.addiu(29,29,0x100);a.jr()
    a.label('fallback')
    for i,r in enumerate(SAVED):a.i(55,r,29,8*i)
    a.addiu(29,29,0x100);a.jump(defeat.CODE)
    data=a.finish();assert len(data)<0x1000;return data


def build_memory(ram,mode='teams',humans=1,fusion_controls='swap_20s',source='<prepared>',
                 show_fusion_owner=True,show_fusion_countdown=True,squads=None,seats=None):
    """squads (battle_mode_policy.Squads) makes a free-for-all a match of three to five teams: the free-for-all
    variants are then emitted for those teams and the SQUAD block is installed with the mode control."""
    if squads is not None and mode!='ffa':raise ValueError('Three to five teams run on the free-for-all engine')
    with policy.building_squads(squads):
        return _build_memory(ram,mode,humans,fusion_controls,source,show_fusion_owner,show_fusion_countdown,squads,seats)


def _build_memory(ram,mode,humans,fusion_controls,source,show_fusion_owner,show_fusion_countdown,squads,seats):
    if len(ram)!=0x8000000:raise ValueError('Requires128MiB captured EE RAM')
    if mode not in policy.MODES or humans not in policy.HUMAN_COUNTS:raise ValueError('Invalid match mode/human count')
    if fusion_controls not in ('swap_20s','split_controls','player1'):raise ValueError('Invalid co-op fusion controls')
    # Mod settings (Fusion): the swap mode's owner caption and switch countdown.
    if type(show_fusion_owner) is not bool:raise ValueError('Fusion owner caption visibility must be Boolean')
    if type(show_fusion_countdown) is not bool:raise ValueError('Fusion countdown visibility must be Boolean')
    if mode=='teams':return dict(serial=SERIAL,crc=CRC,mode=mode,blocks=[])
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager,n=u(core.ACTORS),u(core.MODE+4)
    if n not in policy.ACTOR_COUNTS or (u(core.MODE),u(core.MODE+8),u(core.MODE+12))!=(1,manager,n):
        raise ValueError('Install battle mode on the captured active engine before release')
    if (u(part.CONTROL+4),u(part.CONTROL+8))!=(manager,n):raise ValueError('Missing captured participation')
    mask=u(part.PRESENT);targets=policy.targets(mode,n,mask,squads)
    policy.validate_roster(mode,n,mask,humans,seats if squads is not None else None,squads)
    if any(ram[FFA_DEFEAT:END]):raise ValueError('Battle mode reservation occupied')
    for i in range(n):
        actor=u(core.POINTERS+4*i)
        if not 0x100000<=actor<len(ram)-0x1600 or (u(actor),u(actor+8))!=(i,i&1):raise ValueError('Native actor identity changed')
    blocks=[]
    def add(p,new,expected=None):
        old=ram[p:p+len(new)]
        if expected is not None:
            if ram[p:p+len(expected)]!=expected:raise ValueError(f'Unknown prior mode payload:{p:08X}')
            if len(new)>len(expected) and any(ram[p+len(expected):p+len(new)]):raise ValueError(f'Mode extension occupied:{p:08X}')
        blocks.append(dict(address=p,expected_hex=old.hex(),data_hex=new.hex()))
    control=bytearray(0x100)
    struct.pack_into('<12I',control,0,policy.MAGIC,manager,n,policy.MODES[mode],humans,mask,
        0xFFFFFFFF,0xFFFFFFFF,('swap_20s','split_controls','player1').index(fusion_controls),0,0,0xFFFFFFFF)
    struct.pack_into('<2I',control,48,0xFFFFFFFF,0xFFFFFFFF)
    initial_targets=[u(core.TABLE+4*i) for i in range(n)]
    struct.pack_into('<'+'I'*n,control,128,*initial_targets)
    frame_previous=(u(A(0x1C2A28))&0x3FFFFFF)<<2
    struct.pack_into('<I',control,100,frame_previous)
    add(CONTROL,bytes(control))
    if squads is not None:
        add(policy.SQUAD,squads.block(manager,policy.human_seats(mode,humans,mask,seats,squads)))
    add(core.TABLE,struct.pack('<'+'I'*n,*targets))
    for i,j in enumerate(targets):add(ai.DESCRIPTORS[i]+24,struct.pack('<I',ai.DESCRIPTORS[j]))
    length=len(old_lockon.code(0));tail=old_lockon.CODE+length-8
    if u(tail)>>26!=2 or u(tail+4):raise ValueError('Unknown lock-on chain')
    previous=(u(tail)&0x3FFFFFF)<<2
    # Static metadata is separate from runtime lock-on/AI targets.
    struct.pack_into('<I',control,96,previous)
    blocks[0]['data_hex']=bytes(control).hex()
    button_aware=lockon.installed_variant(ram,previous)
    if button_aware is None:raise ValueError(f'Unknown prior mode payload:{lockon.CODE:08X}')
    base=lockon.payload(previous,button_aware=button_aware)
    if mode=='ffa':
        import extra_throws as throws
        import ffa_targeting as ffa
        if any(ram[ffa.CODE:ffa.END]):raise ValueError('FFA targeting reservation occupied')
        resolver=core.rebound(core.resolver_code,RESOLVER=throws.OLD_RESOLVE)
        add(throws.OLD_RESOLVE,resolver(True),resolver())
        # Prepared default target payloads can contain unequal-team fallbacks.
        # Infer the installed picker from the current held target plan.
        oldtargets=[u(core.TABLE+4*i) for i in range(n)]
        before=ai.program(n,oldtargets);after=ai.program(n,targets,free_for_all=True)
        for old,new in zip(before['segments'],after['segments']):
            if old['data_hex']!=new['data_hex']:
                add(new['address'],bytes.fromhex(new['data_hex']),bytes.fromhex(old['data_hex']))
        add(lockon.CODE,lockon.payload(previous,free_for_all=True,button_aware=button_aware),base)
        for p,fun,target in ((retaliation.ACCUMULATE,retaliation.accumulate_code,ffa.ACCUMULATE),
                             (retaliation.APPLY,retaliation.apply_code,ffa.APPLY)):
            add(p,struct.pack('<2I',(2<<26)|(target>>2),0),fun())
        add(los.CODE,los.code(True),los.code())
        for p,data in ffa.program()+ffa.initial_data(manager,n,mask,[u(core.POINTERS+4*i) for i in range(n)]):
            add(p,data)
        add(bars.DRAW,bars.draw_code(hide_view_subject=True),bars.draw_code())
        add(bars.CONTROL+0x30,struct.pack('<2I',bars.COLORS[1],bars.COLORS[1]))
        add(FFA_DEFEAT,defeat_code())
        if policy.squad_feature('timeover'):
            # Three to five teams: time over, double KO and double ring-out are decided between the teams.
            add(TIME_OVER,squad_timeover_code())
            add(TIME_HOOK,struct.pack('<2I',(2<<26)|(TIME_OVER>>2),0),TIME_NATIVE)
        add(defeat.ENTRY,struct.pack('<2I',(2<<26)|(FFA_DEFEAT>>2),0),struct.pack('<2I',(2<<26)|(defeat.CODE>>2),0))
        # FFA has no allies, so native fusion cannot consume another contestant. With three to five teams
        # teammates fuse (feature 'fusion'): the hooks stay and fusion_partner_lifecycle offers teammates only.
        import fusion_partner_lifecycle as fusion
        for p in (fusion.ELIGIBILITY_HOOK,fusion.BEGIN_HOOK):
            if policy.squad_feature('fusion'):break
            destination=fusion.ELIGIBILITY if p==fusion.ELIGIBILITY_HOOK else fusion.BEGIN
            add(p,struct.pack('<2I',0x03E00008,0x0000102D),struct.pack('<2I',(2<<26)|(destination>>2),0))
    else:
        add(lockon.CODE,lockon.payload(previous,coop_controls=True,button_aware=button_aware),base)
        import coop_fusion
        virtual=bytearray(ram)
        for b in blocks:
            p=b['address'];d=bytes.fromhex(b['data_hex']);virtual[p:p+len(d)]=d
        # Captions exist only in swap_20s; coop_fusion keeps every other mode's default emission.
        fusion=coop_fusion.build_memory(virtual,source=source,show_owner=show_fusion_owner,
                                        show_countdown=show_fusion_countdown)
        blocks+=fusion['blocks']
    spans=sorted((b['address'],b['address']+len(bytes.fromhex(b['data_hex']))) for b in blocks)
    if any(aend>bstart for (_,aend),(bstart,_) in zip(spans,spans[1:])):raise ValueError('Battle mode patches overlap')
    return dict(serial=SERIAL,crc=CRC,source=str(source),mode=mode,humans=humans,
                control=CONTROL,targets=targets,present_mask=mask,blocks=blocks,lockon_button_aware=button_aware,
                limitations=['Native actor IDs/team fields remain unchanged; relationship policy is separate.',
                             'Free-for-all uses native last-survivor result handling; time/ring-out policies remain native.'])


def static_overrides(mode,n,initial,previous,present,button_aware=False,pad_resolver=None,revive_targets=None):
    """(address, original, installed) executable changes; no runtime target data.

    button_aware selects the lock-on queue emission the state was prepared from.
    """
    import fusion_partner_lifecycle as fusion
    jump=lambda p:struct.pack('<2I',(2<<26)|(p>>2),0)
    out=[]
    if mode=='ffa':
        import extra_throws as throws
        import ffa_targeting as ffa
        resolver=core.rebound(core.resolver_code,RESOLVER=throws.OLD_RESOLVE)
        out.append((throws.OLD_RESOLVE,resolver(revive_targets=revive_targets),resolver(True,revive_targets=revive_targets)))
        before=ai.program(n,initial,revive_targets=revive_targets)
        after=ai.program(n,policy.targets('ffa',n,present,policy.emitted_squads()),free_for_all=True,revive_targets=revive_targets)
        for old,new in zip(before['segments'],after['segments']):
            if old['data_hex']!=new['data_hex']:
                out.append((old['address'],bytes.fromhex(old['data_hex']),bytes.fromhex(new['data_hex'])))
        out.append((lockon.CODE,lockon.payload(previous,button_aware=button_aware,revive_targets=revive_targets),
                    lockon.payload(previous,free_for_all=True,button_aware=button_aware,pad_resolver=pad_resolver,revive_targets=revive_targets)))
        for p,fun,target in ((retaliation.ACCUMULATE,retaliation.accumulate_code,ffa.ACCUMULATE),
                             (retaliation.APPLY,retaliation.apply_code,ffa.APPLY)):
            out.append((p,fun(),jump(target)))
        out.append((los.CODE,los.code(),los.code(True)))
        out += [(bars.DRAW,bars.draw_code(),bars.draw_code(True)),
                (bars.CONTROL+0x30,struct.pack('<2I',*bars.COLORS),struct.pack('<2I',bars.COLORS[1],bars.COLORS[1])),
                (defeat.ENTRY,jump(defeat.CODE),jump(FFA_DEFEAT))]
        if policy.squad_feature('timeover'):out.append((TIME_HOOK,TIME_NATIVE,jump(TIME_OVER)))
        for p,target in ((fusion.ELIGIBILITY_HOOK,fusion.ELIGIBILITY),(fusion.BEGIN_HOOK,fusion.BEGIN)):
            if policy.squad_feature('fusion'):break
            out.append((p,jump(target),struct.pack('<2I',0x03E00008,0x0000102D)))
    elif mode=='coop':
        import coop_fusion as coop
        out.append((lockon.CODE,lockon.payload(previous,button_aware=button_aware,revive_targets=revive_targets),
                    lockon.payload(previous,coop_controls=True,button_aware=button_aware,pad_resolver=pad_resolver,revive_targets=revive_targets)))
        for p,target,replacement in ((fusion.ELIGIBILITY_HOOK,fusion.ELIGIBILITY,coop.ELIGIBILITY),
                                     (fusion.BEGIN_HOOK,fusion.BEGIN,coop.BEGIN),
                                     (fusion.COMMIT_HOOK,fusion.COMMIT,coop.COMMIT),
                                     (fusion.contact.PROTECTED,fusion.CONTACT,coop.CONTACT)):
            size=4 if p==fusion.COMMIT_HOOK else 8
            out.append((p,jump(target)[:size],jump(replacement)[:size]))
        world=feed.world_code();needle=struct.pack('<I',(3<<26)|(feed.DRAW>>2))
        offsets=[i for i in range(0,len(world),4) if world[i:i+4]==needle]
        if len(offsets)!=1:raise ValueError('Kill-feed render contract changed')
        out.append((feed.WORLD+offsets[0],needle,struct.pack('<I',(3<<26)|(coop.DRAW>>2))))
    return out


def installed_squads(ram):
    """The teams of an installed match of three to five teams, or None."""
    return policy.installed_squads(ram)


def validate_memory(ram,manager=None,count=None):
    """Strict code/identity validation. Returns mode name or None if uninstalled.

    Actor-chain outer wrappers are independently verified by their installers;
    the owned fusion tick and its original continuation remain exact here.
    A match of three to five teams reports 'ffa' (its engine); installed_squads() names its teams.
    """
    with policy.building_squads(policy.installed_squads(ram)):
        return _validate_memory(ram,manager,count)


def _validate_memory(ram,manager=None,count=None):
    if len(ram)!=0x8000000:raise ValueError('Requires128MiB captured EE RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if not any(ram[FFA_DEFEAT:END]):
        import coop_fusion as coop
        import ffa_targeting
        if any(ram[coop.GATE:coop.END]):raise ValueError('Orphaned cooperative fusion code')
        # Team Battle has no mode block of its own, so the dynamic NPC policy
        # is validated here: present it must be the teams flavour, absent is
        # the ordinary retaliation build.
        if ffa_targeting.installed_mode(ram) not in (None,'teams'):
            raise ValueError('Orphaned dynamic targeting policy')
        return None
    if u(CONTROL)!=policy.MAGIC:raise ValueError('Battle-mode identity is missing or corrupt')
    manager=u(core.ACTORS) if manager is None else manager
    count=u(core.MODE+4) if count is None else count
    if (u(CONTROL+4),u(CONTROL+8))!=(manager,count) or count not in policy.ACTOR_COUNTS:raise ValueError('Battle mode belongs to another capture')
    mode=next((name for name,value in policy.MODES.items() if value==u(CONTROL+12)),None)
    if mode not in ('ffa','coop'):raise ValueError('Unknown installed battle mode')
    mask=u(CONTROL+20)
    squads=policy.emitted_squads()
    if squads is not None:
        if mode!='ffa':raise ValueError('The team table belongs to another battle mode')
        humans_mask=u(policy.SQUAD+policy.SQUAD_FIELDS['humans'])
        seats=tuple(i for i in range(policy.MAX_ACTORS) if humans_mask&(1<<i))
        if squads.seats is not None and sorted(squads.seats)==list(seats):seats=squads.seats   # player order
        expected=squads.block(manager,seats);static=policy.SQUAD_FIELDS['alive']
        installed=bytes(ram[policy.SQUAD:policy.SQUAD_END])
        if (installed[:static]!=expected[:static] or installed[policy.SQUAD_FIELDS['colors']:]!=expected[policy.SQUAD_FIELDS['colors']:]
                or len(seats)!=u(CONTROL+16)):
            raise ValueError('The team table of this match changed')
        policy.validate_roster(mode,count,mask,u(CONTROL+16),seats,squads)
    else:
        if any(ram[policy.SQUAD:policy.SQUAD_END]):raise ValueError('Orphaned team table')
        policy.validate_roster(mode,count,mask,u(CONTROL+16))
    if u(CONTROL+32)>2:raise ValueError('Invalid fusion control mode')
    if (u(part.CONTROL+4),u(part.CONTROL+8),u(part.PRESENT))!=(manager,count,mask):raise ValueError('Battle participation changed')
    initial=[u(CONTROL+128+i*4) for i in range(count)]
    if initial!=policy.targets('teams',count,mask):raise ValueError('Battle-mode initial plan changed')
    previous=u(CONTROL+96)
    if not 0x07000000<=previous<0x08000000:raise ValueError('Invalid lock-on continuation')
    configured=lockon.installed_configuration(ram,previous,free_for_all=mode=='ffa',coop_controls=mode=='coop')
    if configured is None:raise ValueError(f'Battle-mode code changed:{lockon.CODE:08X}')
    for p,old,new in static_overrides(mode,count,initial,previous,mask,*configured):
        expected=new+old[len(new):]
        import lockoff_target
        expected=lockoff_target.dependency_override(ram,p,expected)
        import lockon_threat
        expected=lockon_threat.dependency_override(ram,p,expected)
        import viewport_hud
        expected=viewport_hud.dependency_override(ram,p,expected)
        import teammate_revive
        expected=teammate_revive.dependency_override(ram,p,expected)
        import body_swap_runner
        expected=body_swap_runner.dependency_override(ram,p,expected)
        import fusion_duration
        expected=fusion_duration.dependency_override(ram,p,expected)
        import multiplayer_fusion
        expected=multiplayer_fusion.dependency_override(ram,p,expected)
        if ram[p:p+len(expected)]!=expected:
            # Older checkpoints predate revivable allies in target selection.
            # Accept only the exact original emission and its exact padding.
            for lp,lo,lr in static_overrides(mode,count,initial,previous,mask,*configured,revive_targets=False):
                if lp!=p:continue
                legacy=lr+lo[len(lr):]
                legacy=lockoff_target.dependency_override(ram,p,legacy)
                legacy=lockon_threat.dependency_override(ram,p,legacy)
                if ram[p:p+len(legacy)]==legacy:break
            else:raise ValueError(f'Battle-mode code changed:{p:08X}')
    if mode=='ffa':
        import ffa_targeting
        ffa_targeting.validate_memory(ram,manager,count,mask,'ffa')
        data=defeat_code()
        if ram[FFA_DEFEAT:FFA_DEFEAT+len(data)]!=data:raise ValueError('FFA native winner predicate changed')
        if policy.squad_feature('timeover'):
            data=squad_timeover_code()
            if ram[TIME_OVER:TIME_OVER+len(data)]!=data:raise ValueError('Team time-over rule changed')
        elif any(ram[TIME_OVER:TIME_OVER+0x1000]):raise ValueError('Orphaned team time-over rule')
    else:
        import coop_fusion as coop
        frame=u(CONTROL+100)
        if not 0x07000000<=frame<0x08000000:raise ValueError('Invalid co-op continuation')
        for p,data in coop.program(frame):
            if p==A(0x1C2A28):continue
            import viewport_hud
            data=viewport_hud.dependency_override(ram,p,data)
            import teammate_revive
            data=teammate_revive.dependency_override(ram,p,data)
            import body_swap_runner
            data=body_swap_runner.dependency_override(ram,p,data)
            import fusion_duration
            data=fusion_duration.dependency_override(ram,p,data)
            import multiplayer_fusion
            data=multiplayer_fusion.dependency_override(ram,p,data)
            if ram[p:p+len(data)]!=data:
                # Exact pre-four-player caption emissions remain valid in
                # historical checkpoints; do not rewrite their live state. A
                # swap-mode install may also hide either fusion caption.
                older=coop.accepted_draws(u(CONTROL+32)) if p==coop.DRAW else ()
                if any(ram[p:p+len(old)]==old and not any(ram[p+len(old):p+len(data)]) for old in older):continue
                raise ValueError(f'Co-op fusion code changed:{p:08X}')
        import ffa_targeting
        if ffa_targeting.installed_mode(ram) not in (None,'coop'):
            raise ValueError('Orphaned dynamic targeting policy')
    return mode


def installed_button_aware(ram,mode,previous):
    """Lock-on emission flavour of an installed FFA/co-op state, by exact bytes."""
    flavour=lockon.installed_variant(ram,previous,free_for_all=mode=='ffa',coop_controls=mode=='coop')
    if flavour is None:raise ValueError(f'Battle-mode code changed:{lockon.CODE:08X}')
    return flavour


def base_view(ram,manager=None,count=None):
    """Validate modes and expose their reviewed prior static code in a copy.

    Used only for older safety dependency validators; never applied to RAM.
    Camera/cinematic/beam/controller hooks and all dynamic match data stay as-is.
    """
    with policy.building_squads(policy.installed_squads(ram)):
        return _base_view(ram,manager,count)


def _base_view(ram,manager=None,count=None):
    mode=_validate_memory(ram,manager,count)
    import body_swap_runner
    ram=body_swap_runner.base_view(ram)
    import teammate_revive
    ram=teammate_revive.base_view(ram)
    if mode is None:return ram
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    count=u(CONTROL+8);initial=[u(CONTROL+128+i*4) for i in range(count)]
    previous=u(CONTROL+96)
    copy=bytearray(ram)
    configured=lockon.installed_configuration(ram,previous,free_for_all=mode=='ffa',coop_controls=mode=='coop')
    if configured is None:raise ValueError(f'Battle-mode code changed:{lockon.CODE:08X}')
    for p,old,new in static_overrides(mode,count,initial,previous,u(CONTROL+20),*configured):
        import multiplayer_fusion
        if multiplayer_fusion.dependency_override(ram,p,new)!=new:
            continue  # Keep the independently validated multiplayer owner.
        restored=old+bytes(max(0,len(new)-len(old)))
        copy[p:p+len(restored)]=restored
    return copy
