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
SAVED=tuple(range(3,29))+(30,31)


def defeat_code():
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
                 show_fusion_owner=True,show_fusion_countdown=True):
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
    mask=u(part.PRESENT);targets=policy.targets(mode,n,mask)
    policy.validate_roster(mode,n,mask,humans)
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
        add(defeat.ENTRY,struct.pack('<2I',(2<<26)|(FFA_DEFEAT>>2),0),struct.pack('<2I',(2<<26)|(defeat.CODE>>2),0))
        # FFA has no allies, so native fusion cannot consume another contestant.
        import fusion_partner_lifecycle as fusion
        for p in (fusion.ELIGIBILITY_HOOK,fusion.BEGIN_HOOK):
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


def static_overrides(mode,n,initial,previous,present,button_aware=False,pad_resolver=None):
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
        out.append((throws.OLD_RESOLVE,resolver(),resolver(True)))
        before=ai.program(n,initial)
        after=ai.program(n,policy.targets('ffa',n,present),free_for_all=True)
        for old,new in zip(before['segments'],after['segments']):
            if old['data_hex']!=new['data_hex']:
                out.append((old['address'],bytes.fromhex(old['data_hex']),bytes.fromhex(new['data_hex'])))
        out.append((lockon.CODE,lockon.payload(previous,button_aware=button_aware),
                    lockon.payload(previous,free_for_all=True,button_aware=button_aware,pad_resolver=pad_resolver)))
        for p,fun,target in ((retaliation.ACCUMULATE,retaliation.accumulate_code,ffa.ACCUMULATE),
                             (retaliation.APPLY,retaliation.apply_code,ffa.APPLY)):
            out.append((p,fun(),jump(target)))
        out.append((los.CODE,los.code(),los.code(True)))
        out += [(bars.DRAW,bars.draw_code(),bars.draw_code(True)),
                (bars.CONTROL+0x30,struct.pack('<2I',*bars.COLORS),struct.pack('<2I',bars.COLORS[1],bars.COLORS[1])),
                (defeat.ENTRY,jump(defeat.CODE),jump(FFA_DEFEAT))]
        for p,target in ((fusion.ELIGIBILITY_HOOK,fusion.ELIGIBILITY),(fusion.BEGIN_HOOK,fusion.BEGIN)):
            out.append((p,jump(target),struct.pack('<2I',0x03E00008,0x0000102D)))
    elif mode=='coop':
        import coop_fusion as coop
        out.append((lockon.CODE,lockon.payload(previous,button_aware=button_aware),
                    lockon.payload(previous,coop_controls=True,button_aware=button_aware,pad_resolver=pad_resolver)))
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


def validate_memory(ram,manager=None,count=None):
    """Strict code/identity validation. Returns mode name or None if uninstalled.

    Actor-chain outer wrappers are independently verified by their installers;
    the owned fusion tick and its original continuation remain exact here.
    """
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
        if ram[p:p+len(expected)]!=expected:raise ValueError(f'Battle-mode code changed:{p:08X}')
    if mode=='ffa':
        import ffa_targeting
        ffa_targeting.validate_memory(ram,manager,count,mask,'ffa')
        data=defeat_code()
        if ram[FFA_DEFEAT:FFA_DEFEAT+len(data)]!=data:raise ValueError('FFA native winner predicate changed')
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
    mode=validate_memory(ram,manager,count)
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
