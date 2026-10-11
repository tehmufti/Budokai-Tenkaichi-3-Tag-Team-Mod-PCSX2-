"""Bounded visual-only native beam emitters for tag-team rush attacks.

The real 16A7D0 emitter owns rendering and its native pool node. Both collision
and projectile translation are disabled immediately; the director alone applies
the scheduled attack damage. Endpoints follow posed hand/body bones, not target slots.

Enabled for supported offline matches after the guest bootstrap confirms
private initialization. Never call 14CEB0 under
an arbitrary live allocator, nor free a descriptor while its emitter exists.
"""
import struct
from prototype import Assembler
from native_map import A, ACTOR_HZ
import tag_team_rush as tag
import fusion_partner_lifecycle as full
import fresh_team_combat as core
import beam_struggle as fp

BASE, END = 0x06D60000, 0x06D73000
SPAWN, UPDATE, STOP, OWNED, GEOMETRY = (BASE, BASE+0x2000, BASE+0x4000, BASE+0x5000, BASE+0x6000)
INIT, RELEASE = BASE+0x8000, BASE+0xA000
IGNITE = BASE+0x7000
SELECT_SOURCE = GEOMETRY+0x800
CHARGE_SPAWN, CHARGE, CHARGE_END = 0x06D96000, 0x06D98000, 0x06D99000
FIRE_BIND = CHARGE+0x800
IMPACT = RELEASE  # Native copied-position one-shot; no private actor ownership.
CONTROL, ROWS, STRIDE = BASE+0xC000, BASE+0xC100, 0x1000
ARENAS, ARENA_SIZE = BASE+0xF000, 0x2000
MAGIC, PREPARED = 0x54465831, 0x46585031
C=dict(magic=0,manager=4,count=8,ready=12,pool=16,spawned=20,failed=24,init_status=28)
R=dict(node=0,body=4,source=8,target=12,source_model=16,target_model=20,
       source_index=24,target_index=28,manager=32,source_bone=36,pool=40,
       stopping=44,ticks=48,prepared=52,source_character=56,target_character=60,ignited=64,charged=68)
HEADER, META, DESC, CONTEXT, REQUEST = 0x100, 0x180, 0x220, 0x540, 0x7A0
SOURCE, DIRECTION, TARGET = 0x7E0, 0x7F0, 0x800
NODE_SIZE, BODY_SIZE, MAX_TICKS = 64, 0x620, 10*ACTOR_HZ
NATIVE_POOL_OFFSET=-22600
EMIT=A(0x16A7D0); COLLISION=A(0x16ACA8); MOTION=A(0x16AC40)
TERMINATE=A(0x16A900); ALIVE=A(0x16A9C0); BONE=A(0x2058E0)
CALLBACKS=A(0x2C3AD8); NATIVE_UPDATE=A(0x16A400)
NATIVE_IMPACT=A(0x187B00)
EXPLOSION = BASE+0xB000
NATIVE_EXPLOSION=A(0x187BE0)
EXPLOSION_SCALE=4.5  # 1.5x the original tag-ending visual scale of3.0.


def gate(a,fail,active=True):
    core.gate(a,fail)
    a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,fail)
    a.lw(9,8,C['manager']);a.lw(11,28,-22364);a.branch(5,9,11,fail)
    a.lw(9,8,C['count']);a.branch(5,9,10,fail)
    a.lw(9,8,C['ready']);a.li(11,1);a.branch(5,9,11,fail)
    a.lw(9,8,C['pool']);a.lw(11,28,NATIVE_POOL_OFFSET);a.branch(5,9,11,fail)
    a.li(8,tag.CONTROL);a.lw(9,8);a.li(11,tag.MAGIC);a.branch(5,9,11,fail)
    a.lw(9,8,tag.C['manager']);a.lw(11,28,-22364);a.branch(5,9,11,fail)
    a.lw(9,8,tag.C['count']);a.branch(5,9,10,fail)
    if active:
        a.lw(9,8,tag.C['active']);a.li(11,1);a.branch(5,9,11,fail)


def row_pointer(a,slot,row,fail):
    a.i(11,8,slot,2);a.branch(4,8,0,fail)
    a.r(0,row,0,slot,12);a.li(8,ROWS);a.r(0x21,row,row,8)


def finite(a,base,offsets,fail):
    for offset in offsets:
        a.lw(8,base,offset);a.li(9,0x7F800000);a.r(0x24,8,8,9);a.branch(4,8,9,fail)


def identity(a,row,fail):
    for indexoff,actoroff,modeloff,charoff in (
            (R['source_index'],R['source'],R['source_model'],R['source_character']),
            (R['target_index'],R['target'],R['target_model'],R['target_character'])):
        a.lw(10,row,indexoff);a.li(8,CONTROL);a.lw(8,8,C['count']);a.r(0x2B,8,10,8);a.branch(4,8,0,fail)
        a.lw(22,row,actoroff);full.pointer(a,22,0x1600,fail)
        a.lw(8,22);a.branch(5,8,10,fail)
        a.r(0,10,0,10,2);a.li(8,core.POINTERS);a.r(0x21,8,8,10);a.lw(8,8);a.branch(5,8,22,fail)
        a.lw(23,row,modeloff);full.pointer(a,23,0x1700,fail)
        a.lw(10,22,12);a.i(11,8,10,12);a.branch(4,8,0,fail)
        a.lw(8,23,16);a.branch(5,8,10,fail)
        a.r(0,10,0,10,2);a.li(8,core.MODELS);a.r(0x21,8,8,10);a.lw(8,8);a.branch(5,8,23,fail)
        a.lw(8,23,12);a.lw(9,row,charoff);a.branch(5,8,9,fail)
        for offset in (4,8):
            a.lw(8,23,offset);a.li(9,1);a.branch(5,8,9,fail)


def owned_code():
    """a0 exact private row -> v0 native body or0, no global battle gate.

    Node reuse is authenticated against its pool, exact body, private header
    and descriptor. A stale pointer can never stop a different native attack.
    """
    a=Assembler(OWNED);a.li(8,ROWS);a.branch(4,4,8,'row');a.li(8,ROWS+STRIDE);a.branch(5,4,8,'no')
    a.label('row');a.lw(10,4,R['node']);full.pointer(a,10,NODE_SIZE,'no')
    a.lw(11,4,R['pool']);a.lw(8,28,NATIVE_POOL_OFFSET);a.branch(5,11,8,'no')
    a.lw(8,10,32);a.branch(5,8,11,'no')
    a.lw(8,10,40);a.li(9,CALLBACKS);a.branch(5,8,9,'no')
    a.lw(2,10,56);full.pointer(a,2,BODY_SIZE,'no');a.lw(8,4,R['body']);a.branch(5,8,2,'no')
    a.lw(8,2);a.addiu(9,4,HEADER);a.branch(5,8,9,'no')
    a.lw(8,2,48);a.addiu(9,4,DESC);a.branch(5,8,9,'no')
    a.lw(8,2,1408);a.i(12,8,8,1);a.branch(4,8,0,'no');a.jr()
    a.label('no');a.move(2,0);a.jr();return a.finish()


def geometry_code():
    """a0 private row -> posed source/target/direction, v0 success."""
    a=Assembler(GEOMETRY);tag.save(a);a.move(16,4);identity(a,16,'no')
    a.lw(17,16,R['source_model']);a.lw(18,16,R['target_model'])
    a.lw(19,16,R['source_bone']);a.li(8,31);a.branch(4,19,8,'hand');a.li(8,45);a.branch(4,19,8,'hand')
    a.li(8,54);a.branch(5,19,8,'no')
    a.label('hand');a.r(0,8,0,19,2);a.r(0x21,8,17,8);a.lw(10,8,3436);full.pointer(a,10,80,'no')
    finite(a,10,(64,68,72),'no');a.lw(10,18,3436+4*17);full.pointer(a,10,80,'no');finite(a,10,(64,68,72),'no')
    a.lw(4,17,16);a.move(5,19);a.addiu(6,16,SOURCE);a.call(BONE)
    a.lw(4,18,16);a.li(5,17);a.addiu(6,16,TARGET);a.call(BONE)
    finite(a,16,(SOURCE,SOURCE+4,SOURCE+8,TARGET,TARGET+4,TARGET+8),'no')
    fp.fconst(a,3,0.0)
    for off in (0,4,8):
        a.i(49,0,16,TARGET+off);a.i(49,1,16,SOURCE+off);fp.fop(a,1,0,0,1)
        a.i(57,0,16,DIRECTION+off);fp.fop(a,2,0,0,0);fp.fop(a,0,3,3,0)
    fp.fconst(a,1,.0001);fp.fop(a,0x34,0,1,3);a.branch(17,8,0,'no')
    fp.fop(a,4,3,3,3)
    for off in (0,4,8):
        a.i(49,0,16,DIRECTION+off);fp.fop(a,3,0,0,3);a.i(57,0,16,DIRECTION+off)
    a.sw(0,16,DIRECTION+12);a.li(2,1);a.jump('done')
    a.label('no');a.move(2,0);a.label('done');tag.restore(a,2);a.jr();data=a.finish()
    assert GEOMETRY+len(data)<=SELECT_SOURCE;return data


def select_source_code():
    """a0 owned effect row ->v0 posed muzzle bone31/45/54, or0.

    Native14B108 copies the selected slot's flags into converted metadata+60;
    native14AA18/14A958 use bit0x2000 to emit from bone54. Apply that rule only
    to the exact captured own firing clip, never a different special or generic
    clash364. Otherwise choose the actual forward hand for this pose.
    """
    import tag_rush_scene as scene
    import tag_rush_native_pose as pose
    import tag_rush_assets as assets
    a=Assembler(SELECT_SOURCE);tag.save(a);a.move(16,4)
    a.li(8,ROWS);a.li(20,scene.ROWS);a.branch(4,16,8,'row')
    a.li(8,ROWS+STRIDE);a.branch(5,16,8,'no');a.li(20,scene.ROWS+scene.STRIDE)
    a.label('row');a.lw(21,16,R['source_model']);a.lw(22,16,R['target_model'])
    a.li(8,scene.STATE);a.lw(9,8);a.li(10,scene.SCENE_MAGIC);a.branch(5,9,10,'hands')
    a.lw(11,8,scene.S['descriptor']);full.pointer(a,11,64,'no')
    a.li(9,assets.BASE);a.r(0x2B,10,11,9);a.branch(5,10,0,'no')
    a.li(9,assets.END-64);a.r(0x2B,10,9,11);a.branch(5,10,0,'no')
    a.lw(8,11,28);a.i(12,8,8,pose.OWN_CLASH_POSE);a.branch(4,8,0,'hands')
    a.lw(8,20,pose.ACTIVE);a.li(9,1);a.branch(5,8,9,'hands')
    a.lw(8,20,scene.R['model']);a.branch(5,8,21,'hands')
    a.lw(8,20,pose.FIRE_CLIP)
    for slot,clip in enumerate((264,298,332)):
        a.li(9,clip);a.li(19,4*slot);a.branch(4,8,9,'flags')
    a.jump('hands')
    a.label('flags');a.lw(10,21,2348);full.pointer(a,10,640,'no')
    a.r(0x21,10,10,19);a.lw(8,10);a.i(12,8,8,0x2000);a.branch(4,8,0,'hands')
    a.lw(10,21,3436+4*54);full.pointer(a,10,80,'no');finite(a,10,(64,68,72),'no')
    a.li(2,54);a.jump('done')
    a.label('hands')
    for reg,bone in ((12,31),(13,45)):
        a.lw(reg,21,3436+4*bone);full.pointer(a,reg,80,'no');finite(a,reg,(64,68,72),'no')
    a.lw(14,22,3436+4*17);full.pointer(a,14,80,'no');finite(a,14,(64,68,72),'no')
    finite(a,21,(2416,2420,2424),'no');fp.fconst(a,3,0.)
    for off in (0,4,8):
        a.i(49,0,13,64+off);a.i(49,1,12,64+off);fp.fop(a,1,0,0,1)
        a.i(49,1,14,64+off);a.i(49,2,21,2416+off);fp.fop(a,1,1,1,2)
        fp.fop(a,2,0,0,1);fp.fop(a,0,3,3,0)
    a.li(2,31);fp.fconst(a,0,0.);fp.fop(a,0x34,0,0,3)
    a.branch(17,8,0,'done');a.li(2,45);a.jump('done')
    a.label('no');a.move(2,0);a.label('done');tag.restore(a,2);a.jr();data=a.finish()
    assert SELECT_SOURCE+len(data)<=IGNITE;return data


def spawn_code(color=False,charging=False):
    """a0 role0/1, a1 lifetime actor ticks1..10seconds -> v0 success.

    Requires two privately parsed descriptors and PREPARED row receipts.
    The allocator setup is intentionally separate from an in-progress scene.
    """
    import tag_rush_scene as scene
    import tag_rush_assets as assets
    a=Assembler(CHARGE_SPAWN if charging else SPAWN);tag.save(a);a.move(17,4);a.move(18,5);gate(a,'no')
    row_pointer(a,17,16,'no');a.addiu(8,18,-1);a.i(11,8,8,MAX_TICKS);a.branch(4,8,0,'no')
    a.lw(8,16,R['prepared']);a.li(9,PREPARED);a.branch(5,8,9,'no')
    a.lw(8,16,R['node']);a.branch(5,8,0,'no')
    for offset,value in ((HEADER+36,META),(DESC+796,HEADER)):
        a.lw(8,16,offset);a.addiu(9,16,value);a.branch(5,8,9,'no')
    a.li(8,tag.CONTROL);a.r(0,9,0,17,2);a.r(0x21,9,8,9);a.lw(19,9,tag.C['initiator']);a.lw(20,8,tag.C['victim'])
    a.branch(4,19,20,'no');a.lw(10,8,tag.C['count'])
    for index,actoroff,modeloff,indexoff,charoff in ((19,R['source'],R['source_model'],R['source_index'],R['source_character']),
            (20,R['target'],R['target_model'],R['target_index'],R['target_character'])):
        a.r(0x2B,9,index,10);a.branch(4,9,0,'no')
        a.r(0,8,0,index,2);a.li(9,core.POINTERS);a.r(0x21,8,8,9);a.lw(21,8);full.pointer(a,21,0x1600,'no')
        a.lw(8,21);a.branch(5,8,index,'no');a.sw(21,16,actoroff);a.sw(index,16,indexoff)
        a.lw(22,21,12);a.i(11,8,22,12);a.branch(4,8,0,'no')
        a.r(0,8,0,22,2);a.li(9,core.MODELS);a.r(0x21,8,8,9);a.lw(23,8);full.pointer(a,23,0x1700,'no')
        a.lw(8,23,16);a.branch(5,8,22,'no');a.sw(23,16,modeloff);a.lw(8,23,12);a.sw(8,16,charoff)
    # A character's own clash pose may point either hand toward the victim.
    # Choose once when the emitter starts, using the real posed bones; retain that
    # native bone binding throughout the emitter's lifetime. Older borrowed
    # endings keep their known hand45 (custom) / hand31 (Sadistic Dance).
    a.li(19,31);a.li(8,scene.STATE);a.lw(9,8);a.li(10,scene.SCENE_MAGIC)
    a.branch(5,9,10,'source_ready')
    a.lw(11,8,scene.S['descriptor']);full.pointer(a,11,64,'no')
    a.li(9,assets.BASE);a.r(0x2B,10,11,9);a.branch(5,10,0,'no')
    a.li(9,assets.END-64);a.r(0x2B,10,9,11);a.branch(5,10,0,'no')
    a.lw(10,11,28);a.i(12,9,10,assets.OWN_CLASH_POSE);a.branch(5,9,0,'own_source')
    a.i(12,9,10,assets.CUSTOM_FINISHER);a.branch(4,9,0,'source_ready')
    a.li(19,45)
    a.jump('source_ready')
    a.label('own_source');a.move(4,16);a.call(SELECT_SOURCE);a.branch(4,2,0,'no');a.move(19,2)
    a.label('source_ready');a.sw(19,16,R['source_bone'])
    if color:
        import tag_rush_colors as colors
        a.move(4,16);a.call(colors.APPLY);a.branch(4,2,0,'no')
    a.move(4,16);a.call(GEOMETRY);a.branch(4,2,0,'no')
    a.lw(19,28,NATIVE_POOL_OFFSET);full.pointer(a,19,24,'no');a.lw(10,19,12);full.pointer(a,10,64,'no')
    a.lw(8,10,32);a.branch(5,8,19,'no')
    a.lw(8,16,R['source_model']);a.lw(8,8,16);a.sw(8,16,HEADER)
    a.sw(8,16,HEADER+32)
    # Context anchors are native manual bindings; neither participant needs
    # synthetic move flags or a beam special in their own move list.
    a.addiu(4,16,CONTEXT);a.move(5,0);a.li(6,592);a.call(A(0x2A9ACC))
    for phase in (0,1):
        a.addiu(4,16,CONTEXT);a.li(5,phase);a.lw(6,16,R['source_bone']);a.move(7,0);a.call(A(0x1517A0))
    a.addiu(4,16,HEADER);a.addiu(5,16,CONTEXT);a.call(A(0x1512C8))
    for off,ptr in ((0,HEADER),(4,DESC),(8,CONTEXT),(12,SOURCE),(16,DIRECTION)):
        a.addiu(8,16,ptr);a.sw(8,16,REQUEST+off)
    for off,value in ((20,0),(24,1),(28,1),(32,1),(36,0x41200000),(40,0x3F800000),(44,0),(48,0)):
        a.li(8,value);a.sw(8,16,REQUEST+off)
    a.addiu(4,16,REQUEST);a.call(EMIT);a.branch(4,2,0,'failed');a.sw(2,16,R['node'])
    full.pointer(a,2,NODE_SIZE,'unknown_node');a.lw(8,2,56);a.sw(8,16,R['body']);a.sw(19,16,R['pool'])
    a.move(4,16);a.call(OWNED);a.branch(4,2,0,'unknown_node')
    a.lw(4,16,R['node']);a.li(5,1);a.call(COLLISION);a.branch(4,2,0,'stop')
    a.lw(4,16,R['node']);a.li(5,1);a.call(MOTION);a.branch(4,2,0,'stop')
    a.sw(18,16,R['ticks']);a.sw(0,16,R['stopping'])
    a.lw(21,16,R['body'])
    if charging:
        #16A108 admits only the firing pair supplied by the request.169F48
        #therefore never updates manually started charge children: their glow
        #stays at the first pose's hand while the character draws it back.
        #Keep both native event pairs active on this private parent so its
        #ordinary updater moves existing charge children with the posed hand.
        a.sw(0,21,40);a.sw(0,21,44);a.li(8,2);a.sw(8,21,1412)
    for source,dest in ((SOURCE,1440),(TARGET,1456),(TARGET,1472),(DIRECTION,1376)):
        for off in range(0,16,4):a.lw(8,16,source+off);a.sw(8,21,dest+off)
    # The native constructor replaces the selected phase's hand binding from
    # the real move's events. Restore our explicit posed-hand bindings before
    # activating visual children; neither actor is running that donor move.
    for phase in (0,1):
        a.addiu(4,21,64);a.li(5,phase);a.lw(6,16,R['source_bone']);a.move(7,0);a.call(A(0x1517A0))
    a.addiu(4,16,HEADER);a.addiu(5,21,64);a.call(A(0x1512C8))
    a.sw(0,16,R['ignited']);a.sw(0,16,R['charged'])
    a.move(4,16);a.call(CHARGE if charging else IGNITE);a.branch(4,2,0,'stop')
    a.li(8,CONTROL);a.lw(9,8,C['spawned']);a.addiu(9,9,1);a.sw(9,8,C['spawned'])
    a.li(2,1);a.jump('done')
    a.label('stop');a.lw(4,16,R['node']);a.call(TERMINATE);a.li(8,1);a.sw(8,16,R['stopping'])
    a.jump('failed')
    # A changed allocator contract must not create more unknown objects. Keep
    # the receipt for inspection; do not call a destructor on an unowned node.
    a.label('unknown_node');a.li(8,CONTROL);a.sw(0,8,C['ready'])
    a.label('failed');a.li(8,CONTROL);a.lw(9,8,C['failed']);a.addiu(9,9,1);a.sw(9,8,C['failed'])
    a.label('no');a.move(2,0);a.label('done');tag.restore(a,2);a.jr();result=a.finish()
    assert len(result)<=0x2000;return result


def ignite_code(charging=False):
    """a0 owned row -> advance its reviewed native charge or firing event.

    A native beam parent normally reads special-move event bits in14D7A0.
    Borrowed poses do not publish those gameplay events.14D8A8 is the native
    explicit-event equivalent: raw bit1 charges and bit2 fires, with no model mutation.
    Once started, the ordinary emitter updates and retires these same children.
    """
    # Native 14D8A8 maps raw bit1 to charge rules (kind0), bit2 to fire
    # (kind1). Firing also stops charge rules whose native end event is2.
    # Both stages share one authenticated emitter and its ordinary children.
    flag='charged' if charging else 'ignited'
    a=Assembler(CHARGE if charging else IGNITE);tag.save(a);a.move(16,4);a.call(OWNED);a.branch(4,2,0,'no');a.move(17,2)
    a.lw(8,16,R[flag]);a.branch(5,8,0,'yes')
    a.lw(8,16,R['prepared']);a.li(9,PREPARED);a.branch(5,8,9,'no')
    if not charging:
        a.lw(8,16,R['charged']);a.branch(4,8,0,'bound')
        a.move(4,16);a.call(FIRE_BIND);a.branch(4,2,0,'no');a.label('bound')
    a.addiu(18,16,DESC);a.move(19,0)
    a.label('group');a.r(0,8,0,19,4);a.r(0x21,8,18,8)
    a.lw(10,8,12);a.branch(4,10,0,'next_group');a.i(36,22,8,20);full.pointer(a,10,16,'no')
    a.i(36,21,10,1);a.r(0x21,9,21,22);a.i(11,9,9,20);a.branch(4,9,0,'no')
    a.move(20,0);a.branch(4,21,0,'next_group')
    a.label('rule');a.r(0x21,8,22,20);a.r(0,8,0,8,6);a.lw(9,18,8);a.r(0x21,10,9,8)
    full.pointer(a,10,64,'no');a.i(36,8,10,8)
    if charging:
        a.branch(5,8,0,'next_rule');a.i(36,8,10,10);a.branch(4,8,0,'fire')
        a.li(9,5);a.branch(5,8,9,'next_rule')
    else:
        a.li(9,1);a.branch(4,8,9,'fire_selector')
        a.branch(5,8,0,'next_rule');a.lw(8,16,R['charged']);a.branch(4,8,0,'next_rule')
        a.i(36,8,10,9);a.li(9,2);a.branch(5,8,9,'next_rule');a.jump('fire')
        a.label('fire_selector');a.i(36,8,10,10);a.branch(4,8,9,'fire')
        a.li(9,5);a.branch(5,8,9,'next_rule')
    a.label('fire');a.move(4,18);a.addiu(5,17,656);a.move(6,0);a.move(7,19);a.move(8,20)
    a.move(9,0);a.move(10,0);a.li(11,1 if charging else 2);a.call(A(0x14D8A8));a.branch(4,2,0,'next_rule')
    a.move(11,2);a.move(4,18);a.addiu(5,17,656);a.addiu(6,17,64);a.addiu(7,17,1456)
    a.addiu(8,17,1376);a.move(9,19);a.move(10,20);a.i(49,12,17,1420);a.call(A(0x14FF50))
    a.label('next_rule');a.addiu(20,20,1);a.branch(5,20,21,'rule')
    a.label('next_group');a.addiu(19,19,1);a.li(8,19);a.branch(5,19,8,'group')
    a.li(8,1);a.sw(8,16,R[flag])
    a.label('yes');a.li(2,1);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');tag.restore(a,2);a.jr();result=a.finish()
    assert len(result)<=(FIRE_BIND-CHARGE if charging else INIT-IGNITE);return result


def fire_bind_code():
    """Rebind once to the firing pose's actual forward hand, on the same node.

    A character can reverse its forward hand between charge261 and fire264.
    Updating the native contexts before firing avoids a muzzle on the back
    hand. Later recoil keeps this binding rather than swapping every frame.
    """
    a=Assembler(FIRE_BIND);tag.save(a);a.move(16,4);a.call(OWNED)
    a.branch(4,2,0,'no');a.move(17,2);identity(a,16,'no')
    a.move(4,16);a.call(SELECT_SOURCE);a.branch(4,2,0,'no');a.move(19,2);a.sw(19,16,R['source_bone'])
    for phase in (0,1):
        a.addiu(4,17,64);a.li(5,phase);a.move(6,19);a.move(7,0);a.call(A(0x1517A0))
    a.addiu(4,16,HEADER);a.addiu(5,17,64);a.call(A(0x1512C8))
    a.move(4,16);a.call(GEOMETRY);a.branch(4,2,0,'no')
    for source,dest in ((SOURCE,1440),(TARGET,1456),(TARGET,1472),(DIRECTION,1376)):
        for off in range(0,16,4):a.lw(8,16,source+off);a.sw(8,17,dest+off)
    a.li(2,1);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');tag.restore(a,2);a.jr();result=a.finish()
    assert FIRE_BIND+len(result)<=CHARGE_END;return result


def stop_code():
    """Request native teardown of only our two nodes; return nodes still live.

    There is no spin loop and no descriptor free. Native update/destructor must
    retire both nodes before private descriptor storage may be reused.
    """
    a=Assembler(STOP);tag.save(a);a.li(16,ROWS);a.move(17,0);a.move(18,0)
    a.label('slot');a.move(4,16);a.call(OWNED);a.branch(4,2,0,'retired')
    a.lw(4,16,R['node']);a.call(TERMINATE);a.li(8,1);a.sw(8,16,R['stopping'])
    a.addiu(18,18,1);a.jump('next')
    a.label('retired');a.sw(0,16,R['node']);a.sw(0,16,R['body']);a.sw(0,16,R['stopping']);a.sw(0,16,R['ticks'])
    a.label('next');a.addiu(16,16,STRIDE);a.addiu(17,17,1);a.li(8,2);a.branch(5,17,8,'slot')
    a.move(2,18);tag.restore(a,2);a.jr();return a.finish()


def update_code():
    """Follow rendered bones; invalid identity/timeout stops that emitter."""
    a=Assembler(UPDATE);tag.save(a)
    a.li(8,A(0x333700));a.lw(8,8);a.branch(5,8,0,'done')
    gate(a,'stop_all');a.li(16,ROWS);a.move(17,0)
    a.label('slot');a.move(4,16);a.call(OWNED);a.branch(4,2,0,'retired');a.move(18,2)
    # Native descriptor parents reset these upload-cache masks every update.
    # Ours is private, so it must not reuse last frame's dynamic GS references.
    a.addiu(4,16,DESC);a.call(A(0x14D460))
    a.lw(8,16,R['stopping']);a.branch(5,8,0,'next')
    a.lw(8,16,R['ticks']);a.branch(4,8,0,'stop');a.addiu(8,8,-1);a.sw(8,16,R['ticks'])
    a.move(4,16);a.call(GEOMETRY);a.branch(4,2,0,'stop')
    for source,dest in ((SOURCE,1440),(TARGET,1456),(TARGET,1472),(DIRECTION,1376)):
        for off in range(0,16,4):a.lw(8,16,source+off);a.sw(8,18,dest+off)
    a.jump('next')
    a.label('stop');a.lw(4,16,R['node']);a.call(TERMINATE);a.li(8,1);a.sw(8,16,R['stopping']);a.jump('next')
    a.label('retired');a.sw(0,16,R['node']);a.sw(0,16,R['body']);a.sw(0,16,R['stopping']);a.sw(0,16,R['ticks'])
    a.label('next');a.addiu(16,16,STRIDE);a.addiu(17,17,1);a.li(8,2);a.branch(5,17,8,'slot');a.jump('done')
    a.label('stop_all');a.call(STOP)
    a.label('done');tag.restore(a);a.jr();return a.finish()


def init_code(beam=None):
    """Parse the reviewed donor under two bounded private bump arenas.

    Only the known 1/6/0/1 shape recipe is emitted. Its four shape arrays need
    2176 raw bytes per descriptor, well below each 8192-byte private arena.
    Original allocator rows/selector and model parameters are restored before
    any error is reported. The arena receipt is never a live-appearance claim.
    """
    if beam is None:
        a=Assembler(INIT);a.move(2,0);a.jr();return a.finish()
    if not beam.get('reviewed') or tuple(beam.get('descriptor_counts',()))!=(1,6,0,1) or beam.get('descriptor_raw_bytes')!=2176:
        raise ValueError('Native tag-beam descriptor has not been reviewed')
    resource,metadata=beam['resource_address'],beam['metadata_address']
    import tag_rush_assets as assets
    for p,size in ((resource,107456),(metadata,640)):
        if type(p) is not int or p%16 or not assets.BASE<=p<p+size<=assets.END:
            raise ValueError('Native tag-beam resources escaped the asset reservation')
    a=Assembler(INIT);tag.save(a);core.gate(a,'no');a.li(16,CONTROL)
    a.lw(8,16,C['init_status']);a.branch(5,8,0,'no')
    for index in range(2):
        a.li(8,ROWS+index*STRIDE);a.lw(8,8,R['node']);a.branch(5,8,0,'no')
    a.li(8,core.POINTERS);a.lw(21,8);full.pointer(a,21,0x1600,'no')
    a.lw(8,21);a.branch(5,8,0,'no')
    a.lw(20,21,12);a.i(11,8,20,12);a.branch(4,8,0,'no')
    a.r(0,8,0,20,2);a.li(9,core.MODELS);a.r(0x21,8,8,9);a.lw(21,8);full.pointer(a,21,0x1700,'no')
    a.lw(8,21,16);a.branch(5,8,20,'no')
    for offset in (4,8):a.lw(8,21,offset);a.li(9,1);a.branch(5,8,9,'no')
    a.lw(17,28,-22416);full.pointer(a,17,156,'no')
    a.lw(8,17,152);a.li(9,0x3FE);a.branch(5,8,9,'no')
    a.lw(22,28,NATIVE_POOL_OFFSET);full.pointer(a,22,24,'no')
    a.li(8,1);a.sw(8,16,C['init_status']);a.sw(0,16,C['ready'])
    a.li(8,MAGIC);a.sw(8,16,C['magic']);a.lw(8,28,-22364);a.sw(8,16,C['manager'])
    a.li(8,core.MODE);a.lw(8,8,4);a.sw(8,16,C['count']);a.sw(22,16,C['pool'])
    for off in (80,84,88,92,148):a.lw(8,17,off);a.sw(8,29,0x340+off-80 if off<148 else 0x350)
    a.lw(8,21,2348);a.sw(8,29,0x354)
    a.move(18,0);a.li(19,ROWS)
    a.label('descriptor')
    a.addiu(4,19,HEADER);a.move(5,0);a.li(6,0x720);a.call(A(0x2A9ACC))
    a.sw(20,19,HEADER);a.li(8,2);a.sw(8,19,HEADER+4);a.sw(20,19,HEADER+32)
    a.li(8,resource);a.sw(8,19,HEADER+28);a.addiu(8,19,META);a.sw(8,19,HEADER+36)
    a.li(8,metadata);a.sw(8,21,2348)
    a.move(4,20);a.li(5,2);a.addiu(6,19,META);a.move(7,0);a.call(A(0x14B108))
    a.lw(8,29,0x354);a.sw(8,21,2348)
    a.r(0,8,0,18,13);a.li(9,ARENAS);a.r(0x21,8,8,9)
    a.sw(8,17,80);a.sw(8,17,84);a.li(8,ARENA_SIZE);a.sw(8,17,88);a.sw(0,17,92)
    a.li(8,5);a.sw(8,17,148)
    a.addiu(4,19,HEADER);a.addiu(5,19,DESC);a.move(6,0);a.li(7,resource);a.move(8,0);a.li(9,4);a.call(A(0x14CEB0))
    a.lw(22,17,92)
    for off in (80,84,88,92,148):a.lw(8,29,0x340+off-80 if off<148 else 0x350);a.sw(8,17,off)
    a.li(8,ARENA_SIZE);a.r(0x2B,8,8,22);a.branch(5,8,0,'failed')
    a.lw(8,19,DESC+796);a.addiu(9,19,HEADER);a.branch(5,8,9,'failed')
    for group,count in enumerate((1,6,0,1)):
        a.lw(8,19,DESC+780+4*group);a.li(9,count);a.branch(5,8,9,'failed')
        if count:
            # Every parsed array must lie wholly in this descriptor's arena.
            # This also catches allocation failure before any emitter uses it.
            length=(520,1584,0,72)[group]
            a.lw(10,19,DESC+764+4*group);a.r(0,8,0,18,13);a.li(9,ARENAS);a.r(0x21,8,8,9)
            a.r(0x2B,9,10,8);a.branch(5,9,0,'failed');a.addiu(8,8,ARENA_SIZE-length)
            a.r(0x2B,9,8,10);a.branch(5,9,0,'failed');a.i(12,8,10,15);a.branch(5,8,0,'failed')
    if beam.get('color_plan'):
        import tag_rush_colors as colors
        a.move(4,19);a.call(colors.INIT);a.branch(4,2,0,'failed')
    a.li(8,31);a.sw(8,19,R['source_bone']);a.li(8,PREPARED);a.sw(8,19,R['prepared'])
    a.addiu(19,19,STRIDE);a.addiu(18,18,1);a.li(8,2);a.branch(5,18,8,'descriptor')
    a.li(8,2);a.sw(8,16,C['init_status']);a.li(2,1);a.sw(2,16,C['ready']);a.jump('done')
    a.label('failed');a.li(8,100);a.sw(8,16,C['init_status'])
    a.label('no');a.move(2,0);a.label('done');tag.restore(a,2);a.jr();return a.finish()


def impact_code(explosion=False):
    """a0 captured role0..2,a1 encoded native bone -> visual success.

    Ordinary contacts use1D3170's type16 impact through187B00. The beam ending
    uses12F328's family1/type3 explosion through187BE0. Both copy the request
    into the bounded native pool; its lifetime/destructor owns cleanup.
    No hitstop, attack events, damage or target writes are added here.
    """
    import tag_rush_camera as camera
    import tag_rush_scene as scene
    entry=EXPLOSION if explosion else IMPACT
    a=Assembler(entry);tag.save(a);a.move(16,4);a.move(17,5)
    a.li(8,A(0x333700));a.lw(8,8);a.branch(5,8,0,'no')
    camera.emit_active(a,'no');a.i(11,9,16,3);a.branch(4,9,0,'no')
    a.i(11,9,17,32);a.branch(4,9,0,'no')
    a.li(8,scene.STATE);a.lw(9,8);a.li(10,scene.SCENE_MAGIC);a.branch(5,9,10,'no')
    a.lw(9,8,scene.S['retiring']);a.branch(5,9,0,'no')
    if explosion:
        # 12F328 emits the native Kamehameha hit family, selected by the
        # converted special metadata+64 (14B108 maps source byte165 ->3).
        # This is a copied-position one-shot, not another attack/beam node.
        import tag_rush_assets as assets
        a.li(9,2);a.branch(5,16,9,'no')
        a.lw(10,8,scene.S['descriptor']);full.pointer(a,10,64,'no')
        a.li(9,assets.BASE);a.r(0x2B,9,10,9);a.branch(5,9,0,'no')
        a.li(9,assets.END-64);a.r(0x2B,9,9,10);a.branch(5,9,0,'no')
        a.lw(10,10,28);a.i(12,9,10,assets.FINISHER);a.branch(4,9,0,'no')
        a.i(12,9,10,assets.BEAM_LEAD|assets.BEAM_PARTNER);a.branch(4,9,0,'no')
    a.r(0,8,0,16,9);a.li(9,scene.ROWS);a.r(0x21,21,8,9)
    a.lw(10,21,scene.R['index']);a.li(8,tag.CONTROL);a.lw(9,8,tag.C['count'])
    a.r(0x2B,9,10,9);a.branch(4,9,0,'no')
    a.lw(10,21,scene.R['model_id']);a.i(11,9,10,12);a.branch(4,9,0,'no')
    scene.identity(a,21,'no','impact');a.lw(9,23,8);a.li(10,1);a.branch(5,9,10,'no')
    a.r(0,8,0,17,2);a.r(0x21,8,23,8);a.lw(10,8,3436);full.pointer(a,10,80,'no')
    finite(a,10,(64,68,72),'no');finite(a,23,(2404,),'no')
    # The ordinary battle initializes these14 descriptors and its30-node pool.
    # No new resource load or allocator switch occurs in the middle of a hit.
    a.lw(18,28,-22512);full.pointer(a,18,24,'no')
    a.lw(10,18,12);full.pointer(a,10,64,'no');a.lw(9,10,32);a.branch(5,9,18,'no')
    a.lw(19,28,-22516);full.pointer(a,19,11208,'no')
    descriptor=7208 if explosion else 4008
    for off in (descriptor,descriptor+8):a.lw(10,19,off);full.pointer(a,10,64,'no')
    a.lw(4,23,16);a.move(5,17);a.addiu(6,29,0x300);a.call(BONE)
    finite(a,29,(0x300,0x304,0x308),'no')
    a.li(8,0x3F800000);a.sw(8,29,0x30C)
    a.i(49,12,23,2404);a.call(A(0x11F588));a.i(57,0,29,0x310)
    a.i(49,12,23,2404);a.call(A(0x11F620));a.i(57,0,29,0x318)
    a.sw(0,29,0x314);a.sw(0,29,0x31C);a.li(8,3 if explosion else 16);a.sw(8,29,0x320)
    a.lw(8,23,16);a.sw(8,29,0x324);a.sw(0,29,0x328);a.sw(0,29,0x32C)
    if explosion:
        fp.fconst(a,12,EXPLOSION_SCALE);fp.fconst(a,13,0.0)
    a.addiu(4,29,0x300);a.call(NATIVE_EXPLOSION if explosion else NATIVE_IMPACT);a.jump('done')
    a.label('no');a.move(2,0);a.label('done');tag.restore(a,2);a.jr();data=a.finish()
    assert entry+len(data)<=(CONTROL if explosion else EXPLOSION);return data


def pieces(beam=None):
    plan=beam.get('color_plan') if beam else None
    result=[(SPAWN,spawn_code(bool(plan))),(UPDATE,update_code()),(STOP,stop_code()),
            (OWNED,owned_code()),(GEOMETRY,geometry_code()),(SELECT_SOURCE,select_source_code()),(IGNITE,ignite_code()),(INIT,init_code(beam)),(IMPACT,impact_code()),
            (EXPLOSION,impact_code(explosion=True)),(CONTROL,bytes(END-CONTROL)),
            (CHARGE_SPAWN,spawn_code(bool(plan),charging=True)),(CHARGE,ignite_code(charging=True)),
            (FIRE_BIND,fire_bind_code())]
    if plan:
        import tag_rush_colors as colors
        result.extend(colors.pieces(plan))
    spans=sorted((p,p+len(b)) for p,b in result)
    assert all(end<=p for (_,end),(p,_) in zip(spans,spans[1:]))
    return result


def installation(beam=None,*args,**kwargs):
    import tag_rush_colors as colors
    mutable=[(CONTROL,END)]
    if beam and beam.get('color_plan'):mutable.append((colors.STORAGE,colors.STORAGE_END))
    return dict(usable=False,blocks=pieces(beam),mutable_ranges=mutable,limitations=[
        'Private native beam descriptors use a reviewed bounded allocator; live initialization still needs to be checked.',
        'Beam origin, endpoint, firing phase, visibility in each view, and native cleanup need a live match check.'])
