"""Install three/four-player presentation last, after ordinary gameplay guards."""
from native_map import A
import struct
import battle_mode_policy as policy
import fresh_team_combat as core
import team_participation as participation
import quad_viewports as views
import quad_controller as controllers
import quad_lifecycle as lifecycle


def variants(ram):
    import fusion_partner_lifecycle as fusion
    import teammate_revive as revive
    import cinematic_policy as cinema
    import viewport_hud as hud
    import teammate_revive_ring as ring
    import display_settings as display
    import hud_subject
    revive_mobile=(struct.unpack_from('<I',ram,revive.CONTROL)[0]!=revive.MAGIC or
                   struct.unpack_from('<I',ram,revive.CONTROL+24)[0]>=5)
    previous=struct.unpack_from('<I',ram,hud.CONTROL+16)[0]
    result=[(display.feed.SMALL_TEXT,bytes(len(display.feed.text_code(compact=True))),display.feed.text_code(compact=True)),
              (fusion.SYNC,fusion.sync_code(),fusion.sync_code(quad_support=True)),
              (cinema.CODE,cinema.selector(),cinema.selector(quad_support=True)),
              (hud.ACTIVE,hud.active(),hud.active(quad_support=True)),
              (hud.POST,hud.post_code(),hud.post_code(quad_support=True)),
              (hud_subject.CODE,hud_subject.watched_resolver_code(),hud_subject.watched_resolver_code(quad_support=True)),
              (hud.CODE,hud.wrapper(previous,deferred=True,extensions=hud.hud_extensions(ram)),
               hud.wrapper(previous,revival=False,deferred=True)),
              (display.HUD_DRAW_FILTER,display.hud_draw_filter_code(),display.hud_draw_filter_code(quad_support=True)),
              (display.SCORE,display.score_code(),display.score_code(quad=True)),
              (display.FEED_DRAW,display.relocated(display.feed.draw_code,display.feed.DRAW,display.FEED_DRAW),
               display.relocated(display.feed.draw_code,display.feed.DRAW,display.FEED_DRAW,quad=True)),
              (revive.RING,ring.ring(),ring.ring(quad_support=True)),
              (revive.TICK,revive.tick(mobile=revive_mobile),revive.tick(quad_support=True,mobile=revive_mobile))]
    if struct.unpack_from('<I',ram,policy.CONTROL+12)[0]==policy.COOP:
        import coop_controller as coop
        result.append((coop.ACTOR_PAD,coop.payload(takeover=True),
                       coop.payload(takeover=True,three_humans=True)))
    import fusion_duration as timer
    if struct.unpack_from('<I',ram,timer.CONTROL)[0]==timer.MAGIC:
        previous=struct.unpack_from('<I',ram,timer.CONTROL+36)[0]
        result.append((timer.DRAW,timer.draw(previous),timer.draw(previous,quad_support=True)))
    return result


def installed(ram):
    if struct.unpack_from('<I',ram,controllers.CONTROL)[0]!=controllers.MAGIC:return False
    manager,count=struct.unpack_from('<2I',ram,controllers.CONTROL+4)
    if (struct.unpack_from('<4I',ram,core.MODE)!=(1,count,manager,count) or
            struct.unpack_from('<I',ram,core.ACTORS)[0]!=manager or
            struct.unpack_from('<4I',ram,views.CONTROL)!=(views.MAGIC,manager,count,1)):
        raise ValueError('Four-player dependency belongs to another capture')
    return True


def validate_pad(ram):
    """Verify the entire outer accessor and its captured continuation."""
    if not installed(ram):raise ValueError('Four-player pad owner is missing')
    template=controllers.pad(0)
    previous_word,delay=struct.unpack_from('<2I',ram,controllers.PAD+len(template)-8)
    if previous_word>>26!=2 or delay:raise ValueError('Four-player pad continuation changed')
    previous=(previous_word&0x3FFFFFF)<<2
    import coop_controller as coop
    import spectator_takeover as takeover
    if previous not in (coop.ACTOR_PAD,takeover.PAD):
        raise ValueError('Unknown four-player pad predecessor')
    data=controllers.pad(previous)
    import multiplayer_fusion as fusion
    hook=fusion.dependency_override(ram,coop.HOOK,views.jump(controllers.PAD))
    if ram[controllers.PAD:controllers.PAD+len(data)]!=data or ram[coop.HOOK:coop.HOOK+8]!=hook:
        raise ValueError('Four-player pad executable changed')
    return previous


def dependency_override(ram,address,expected):
    """Recognize complete four-seat emissions inside existing strict validators."""
    if not installed(ram):return expected
    import multiplayer_fusion as fusion
    replaced=fusion.dependency_override(ram,address,expected)
    if replaced!=expected:return replaced
    if address==A(0x1C2A28) and len(expected)==8:
        word,delay=struct.unpack('<2I',expected)
        if word>>26!=2 or delay:raise ValueError('Four-player frame continuation is not a jump')
        previous=(word&0x3FFFFFF)<<2
        for at,data in ((controllers.FRAME,controllers.frame(lifecycle.FRAME)),
                        (lifecycle.FRAME,lifecycle.frame(previous)),
                        (address,views.jump(controllers.FRAME))):
            if ram[at:at+len(data)]!=data:raise ValueError(f'Four-player frame chain changed at {at:08X}')
        return views.jump(controllers.FRAME)
    for at,old,new in variants(ram):
        if address==at and expected==old:
            import lockoff_target
            new=lockoff_target.dependency_override(ram,at,new)
            if ram[at:at+len(new)]!=new:raise ValueError(f'Four-player executable changed at {at:08X}')
            return new
    return expected


def four_seat_variants(ram):
    """Scope expanded behavior to four-seat installs, preserving old emissions."""
    import teammate_revive as revive
    blocks=[]
    for at,old,new in variants(ram):
        if at in (revive.TICK,revive.RING) and struct.unpack_from('<I',ram,revive.CONTROL)[0]!=revive.MAGIC:continue
        if ram[at:at+len(old)]!=old:raise ValueError(f'Four-player variant predecessor changed at {at:08X}')
        if len(new)>len(old) and any(ram[at+len(old):at+len(new)]):
            raise ValueError(f'Four-player variant extension occupied at {at:08X}')
        size=max(len(old),len(new))
        blocks.append(dict(address=at,expected_hex=ram[at:at+size].hex(),data_hex=(new+bytes(size-len(new))).hex()))
    return dict(blocks=blocks)


@policy.matching_install
def build_memory(ram,mode='teams',source='<prepared>',humans=4,settings=None,assignment=None):
    from fresh_team_trainer import compose_manifests
    present=struct.unpack_from('<I',ram,participation.PRESENT)[0]
    if humans not in (2,3,4):raise ValueError('Multiview needs two to four humans')
    subjects=policy.human_seats(mode,humans,present,assignment)
    count=struct.unpack_from('<I',ram,core.MODE+4)[0]
    policy.validate_roster('coop' if mode=='training_coop' else 'teams' if mode=='training' else mode,
                           count,present,humans,assignment)
    import multiplayer_fusion as fusion
    import mod_settings
    settings=mod_settings.validate_settings(settings or {})
    manifest=compose_manifests(ram,[lambda r:views.build_memory(r,subjects),
                                    lambda r:lifecycle.build_memory(r,subjects,mode),
                                    lambda r:controllers.build_memory(r,subjects),four_seat_variants,
                                    lambda r:fusion.build_memory(r,settings)])
    split=A(0x331DC8)+36
    manifest['blocks'].append(dict(address=split,expected_hex=ram[split:split+4].hex(),data_hex=struct.pack('<I',1).hex()))
    manifest.update(source=str(source),human_seats=subjects,humans=humans)
    return manifest
