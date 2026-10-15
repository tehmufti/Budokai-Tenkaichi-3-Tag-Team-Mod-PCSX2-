"""Piccolo's native Special Beam Cannon, scoped to private tag emitters.

Both Piccolo forms use Early's identical BT3/BT4 slot4 visual package. Native
14CEB0 parses its spiral/core, charge and impact children. Gameplay, collision,
damage and move identity remain owned by the tag director, not this descriptor.
The normal effect row keeps its address throughout; its idle descriptor is
switched between two privately prepared recipes before a parent is allocated.
"""
import hashlib
import struct
from prototype import Assembler
from native_map import A
import tag_team_rush as tag
import fusion_partner_lifecycle as full
import fresh_team_combat as core
import beam_struggle as fp

BASE, END = 0x06E90000, 0x06ED0000
INIT, SELECT, STATE, STATE_END = BASE, BASE+0x2000, BASE+0x3000, BASE+0x3100
BANKS, BANK_STRIDE = BASE+0x4000, 0x1000
ARENAS, ARENA_SIZE = BASE+0x6000, 0x2000
RESOURCE = BASE+0xA000
MAGIC, PREPARED = 0x53424331, 0x53425031
S = dict(magic=0, manager=4, count=8, pool=12, status=16, ready=20)
STANDARD_META, STANDARD_DESC = 0, 0xA0
SPECIAL_META, SPECIAL_DESC = 0x400, 0x4A0
RECEIPT, STANDARD_RESOURCE, STANDARD_SLOT, FLAVOR = 0x800, 0x804, 0x808, 0x80C
META_SIZE, DESC_SIZE = 160, 800
STANDARD_SCRIPT_OFFSET = 192
COUNTS, STRIDES = (2, 8, 1, 0), (520, 264, 136, 72)
ROWS = ((0,1,0),(5,11,4),(9,1,1),(14,6,2),(15,1,1),(16,2,1),(17,1,1),(18,2,1))
RESOURCE_SIZE, METADATA_SIZE, SCRIPT_SIZE = 167168, 640, 1920
# The scoped private-emitter flavor stays off: a16A7D0 parent hands the
# spiral a fixed point and a fitted scale, so its600-unit visual drew only
# small hollow rings at this34..60-unit lane (Oct12). Piccolo now fires the
# game's own family0 SBC presentation object (native_spawn_code below); the
# ordinary recipe remains the fallback when that object cannot be started.
SCOPED_PICCOLO = False
RESOURCE_SHA256 = '1727de14fba2463614913aa83a7f726bc5be6bcb6e3490d230a93bdbb2fd1274'
MASKED_SHA256 = '86300cc26f09727d57d33f72477f38d7e0a953514af3b89426c50075cdb66fea'


def validate_asset(resource, metadata):
    """Accept only the reviewed native recipe, including its exact textures."""
    from model_assets import package_entry
    if (len(resource)!=RESOURCE_SIZE or len(metadata)!=METADATA_SIZE or
            metadata[314]!=0 or struct.unpack_from('<I',metadata,8)[0]!=0x04000129):
        raise ValueError('Unreviewed Special Beam Cannon resource or metadata')
    count=struct.unpack_from('<I',resource)[0]
    if count!=57:raise ValueError('Special Beam Cannon package count changed')
    entries={i:package_entry(resource,i) for i in range(1,count+1)}
    script=entries[4]
    if (len(script)!=SCRIPT_SIZE or script[4:6]!=bytes((8,25)) or
            tuple(tuple(script[64+32*i:67+32*i]) for i in range(8))!=ROWS):
        raise ValueError('Special Beam Cannon event recipe changed')
    counts, cursor, relocations=[0]*4,5,[]
    for kind,commands,shapes in ROWS:
        if not kind:continue
        group=1 if kind in (5,15,16,17,18) else 2 if kind==9 else 0
        counts[group]+=shapes
        for _ in range(shapes):
            start=struct.unpack_from('<I',resource,cursor*4)[0]&~3
            shape=entries[cursor];cursor+=1
            if len(shape)<32:raise ValueError('Truncated Special Beam Cannon shape')
            textures,words=struct.unpack_from('<2I',shape);table=words*4
            if not 1<=textures<=(32,16,8,4)[group] or table<32 or table+64*textures>len(shape):
                raise ValueError('Special Beam Cannon texture bounds changed')
            relocations.append((start+16,4))
            for j in range(textures):
                pixels,palette=struct.unpack_from('<2I',shape,table+64*j)
                if any(off and not table+64*textures<=off*4<len(shape) for off in (pixels,palette)):
                    raise ValueError('Special Beam Cannon texture points outside its shape')
                if pixels:relocations.append((start+table+64*j+56,4))
                if palette:relocations.append((start+table+64*j+60,4))
        for _ in range(commands):
            if not entries[cursor]:raise ValueError('Missing Special Beam Cannon command')
            cursor+=1 if kind==14 else 2
    if cursor!=count+1 or tuple(counts)!=COUNTS:
        raise ValueError('Special Beam Cannon allocation recipe changed')
    masked=bytearray(resource)
    for off,size in relocations:masked[off:off+size]=bytes(size)
    if hashlib.sha256(masked).hexdigest()!=MASKED_SHA256:
        raise ValueError('Special Beam Cannon source pixels or events changed')
    return dict(descriptor_counts=COUNTS,descriptor_raw_bytes=sum(n*s for n,s in zip(COUNTS,STRIDES)),
        resource_sha256=RESOURCE_SHA256,mutable_ranges=tuple(relocations),reviewed=True,
        script_offset=struct.unpack_from('<I',resource,16)[0]&~3,script_size=SCRIPT_SIZE,
        rule_count=25,character=22,slot=4)


def build_assets(iso):
    import model_assets as model
    import tag_rush_assets as assets
    try:
        import bt4_resources  # noqa:F401
    except ImportError:
        combat=1653;metadata=model.package_entry(assets._mesh_package(iso,22),24)
    else:
        combat=5422;metadata=model.package_entry(model.read_archive_entry(iso,4172),2)[0x29D0:0x2C50]
    resource=model.package_entry(model.read_archive_entry(iso,combat),5)
    result=validate_asset(resource,metadata)
    metadata_address=RESOURCE+len(resource)
    assert metadata_address%16==0 and metadata_address+len(metadata)<=END
    result.update(resource_address=RESOURCE,resource_size=len(resource),metadata_address=metadata_address,
                  metadata_size=len(metadata),blocks=[(RESOURCE,resource+metadata)])
    return result


def _plan(plan):
    if (not isinstance(plan,dict) or not plan.get('reviewed') or
            tuple(plan.get('descriptor_counts',()))!=COUNTS or plan.get('descriptor_raw_bytes')!=3288 or
            plan.get('resource_sha256')!=RESOURCE_SHA256 or plan.get('resource_address')!=RESOURCE or
            plan.get('resource_size')!=RESOURCE_SIZE or plan.get('metadata_address')!=RESOURCE+RESOURCE_SIZE or
            plan.get('metadata_size')!=640 or plan.get('script_size')!=SCRIPT_SIZE or plan.get('rule_count')!=25):
        raise ValueError('Invalid private Special Beam Cannon plan')
    off=plan.get('script_offset')
    if type(off)is not int or off!=256:
        raise ValueError('Invalid private Special Beam Cannon script')
    for off,size in plan.get('mutable_ranges',()):
        if type(off)is not int or size!=4 or off%4 or not 0<=off<RESOURCE_SIZE-3:
            raise ValueError('Invalid Special Beam Cannon texture relocation')
    return plan


def _copy(a,src,dst,size,label):
    # src/dst expressions are supplied in t0/t1; no native calls or scratch
    # heap allocation while moving an authenticated, fixed-length recipe.
    a.li(10,size//4);a.label(label)
    a.lw(11,src);a.sw(11,dst);a.addiu(src,src,4);a.addiu(dst,dst,4)
    a.addiu(10,10,-1);a.branch(5,10,0,label)


def _receipt(a,fail,initializing=False):
    import tag_rush_effects as fx
    core.gate(a,fail);a.li(16,STATE);a.li(24,fx.CONTROL)
    a.lw(8,16);a.li(9,MAGIC);a.branch(5,8,9,fail)
    a.lw(8,24);a.li(9,fx.MAGIC);a.branch(5,8,9,fail)
    for own,native in ((S['manager'],fx.C['manager']),(S['count'],fx.C['count']),(S['pool'],fx.C['pool'])):
        if not initializing:
            a.lw(8,16,own);a.lw(9,24,native);a.branch(5,8,9,fail)
    a.lw(8,24,fx.C['manager']);a.lw(9,28,-22364);a.branch(5,8,9,fail)
    a.lw(8,24,fx.C['count']);a.branch(5,8,10,fail)
    a.lw(8,24,fx.C['pool']);a.lw(9,28,fx.NATIVE_POOL_OFFSET);a.branch(5,8,9,fail)
    a.lw(8,24,fx.C['init_status']);a.li(9,1 if initializing else 2);a.branch(5,8,9,fail)
    a.lw(8,24,fx.C['ready']);a.li(9,0 if initializing else 1);a.branch(5,8,9,fail)
    if not initializing:
        a.lw(8,16,S['ready']);a.li(9,1);a.branch(5,8,9,fail)
        a.lw(8,16,S['status']);a.li(9,2);a.branch(5,8,9,fail)


def _descriptor(a,desc,arena,counts,script,row,fail,prefix):
    import tag_rush_effects as fx
    a.lw(8,desc,796);a.addiu(9,row,fx.HEADER);a.branch(5,8,9,fail)
    if script is not None:
        for off,delta in ((0,0),(4,64),(8,320)):
            a.lw(8,desc,off);a.li(9,script+delta);a.branch(5,8,9,fail)
    for group,count in enumerate(counts):
        a.lw(8,desc,780+4*group);a.li(9,count);a.branch(5,8,9,fail)
        if count:
            a.lw(12,desc,764+4*group);a.r(0x2B,8,12,arena);a.branch(5,8,0,fail)
            a.addiu(9,arena,ARENA_SIZE-count*STRIDES[group]);a.r(0x2B,8,9,12);a.branch(5,8,0,fail)
            a.i(12,8,12,15);a.branch(5,8,0,fail)


def _standard_source(a,bank,desc,fail):
    import tag_rush_assets as assets
    a.lw(13,bank,STANDARD_RESOURCE);a.i(12,8,13,15);a.branch(5,8,0,fail)
    a.li(8,assets.BASE);a.r(0x2B,8,13,8);a.branch(5,8,0,fail)
    a.li(8,assets.END-107456);a.r(0x2B,8,8,13);a.branch(5,8,0,fail)
    a.lw(8,bank,STANDARD_SLOT);a.li(9,2);a.branch(5,8,9,fail)
    for off,delta in ((0,192),(4,256),(8,448)):
        a.lw(8,desc,off);a.addiu(9,13,delta);a.branch(5,8,9,fail)


def init_code(plan):
    """Called within effects INIT, after both ordinary descriptors exist."""
    import tag_rush_effects as fx
    p=_plan(plan);a=Assembler(INIT);tag.save(a);_receipt(a,'no',True)
    a.lw(8,16,S['status']);a.branch(5,8,0,'no')
    for index in range(2):
        a.li(19,fx.ROWS+index*fx.STRIDE)
        for key in ('node','stopping'):
            a.lw(8,19,fx.R[key]);a.branch(5,8,0,'no')
        a.lw(8,19,fx.R['prepared']);a.li(9,fx.PREPARED);a.branch(5,8,9,'no')
    a.li(8,core.POINTERS);a.lw(21,8);full.pointer(a,21,0x1600,'no')
    a.lw(8,21);a.branch(5,8,0,'no');a.lw(20,21,12);a.i(11,8,20,12);a.branch(4,8,0,'no')
    a.r(0,8,0,20,2);a.li(9,core.MODELS);a.r(0x21,8,8,9);a.lw(21,8);full.pointer(a,21,0x1700,'no')
    a.lw(8,21,16);a.branch(5,8,20,'no')
    for off in (4,8):a.lw(8,21,off);a.li(9,1);a.branch(5,8,9,'no')
    a.lw(17,28,-22416);full.pointer(a,17,156,'no');a.lw(8,17,152);a.li(9,0x3FE);a.branch(5,8,9,'no')
    a.li(8,1);a.sw(8,16,S['status'])
    for own,native in ((S['manager'],fx.C['manager']),(S['count'],fx.C['count']),(S['pool'],fx.C['pool'])):
        a.lw(8,24,native);a.sw(8,16,own)
    for off in (80,84,88,92,148):a.lw(8,17,off);a.sw(8,29,0x340+off-80 if off<148 else 0x350)
    a.lw(8,21,2348);a.sw(8,29,0x354)
    a.move(18,0);a.li(19,fx.ROWS);a.li(22,BANKS);a.li(23,ARENAS)
    a.label('row')
    a.addiu(4,19,fx.DESC);a.r(0,25,0,18,13);a.li(8,fx.ARENAS);a.r(0x21,25,25,8)
    _descriptor(a,4,25,(1,6,0,1),None,19,'failed','standard')
    a.lw(8,19,fx.HEADER+4);a.li(9,2);a.branch(5,8,9,'failed');a.sw(8,22,STANDARD_SLOT)
    a.lw(8,19,fx.HEADER+28);a.sw(8,22,STANDARD_RESOURCE)
    a.addiu(8,19,fx.META);a.addiu(9,22,STANDARD_META);_copy(a,8,9,META_SIZE,'copy_standard_meta')
    a.addiu(8,19,fx.DESC);a.addiu(9,22,STANDARD_DESC);_copy(a,8,9,DESC_SIZE,'copy_standard_desc')
    a.addiu(4,22,STANDARD_DESC);_standard_source(a,22,4,'failed')
    a.li(8,4);a.sw(8,19,fx.HEADER+4);a.li(8,RESOURCE);a.sw(8,19,fx.HEADER+28)
    a.addiu(8,22,SPECIAL_META);a.sw(8,19,fx.HEADER+36)
    a.li(8,p['metadata_address']);a.sw(8,21,2348)
    a.move(4,20);a.li(5,4);a.addiu(6,22,SPECIAL_META);a.move(7,0);a.call(A(0x14B108))
    a.lw(8,29,0x354);a.sw(8,21,2348)
    a.sw(23,17,80);a.sw(23,17,84);a.li(8,ARENA_SIZE);a.sw(8,17,88);a.sw(0,17,92);a.li(8,5);a.sw(8,17,148)
    a.addiu(4,19,fx.HEADER);a.addiu(5,22,SPECIAL_DESC);a.move(6,0);a.li(7,RESOURCE);a.move(8,0);a.li(9,4);a.call(A(0x14CEB0))
    a.lw(25,17,92)
    for off in (80,84,88,92,148):a.lw(8,29,0x340+off-80 if off<148 else 0x350);a.sw(8,17,off)
    a.lw(8,22,STANDARD_SLOT);a.sw(8,19,fx.HEADER+4);a.lw(8,22,STANDARD_RESOURCE);a.sw(8,19,fx.HEADER+28)
    a.addiu(8,19,fx.META);a.sw(8,19,fx.HEADER+36)
    a.li(8,ARENA_SIZE);a.r(0x2B,8,8,25);a.branch(5,8,0,'failed')
    a.addiu(4,22,SPECIAL_DESC);_descriptor(a,4,23,COUNTS,RESOURCE+p['script_offset'],19,'failed','special')
    a.li(8,PREPARED);a.sw(8,22,RECEIPT)
    a.addiu(19,19,fx.STRIDE);a.addiu(22,22,BANK_STRIDE);a.addiu(23,23,ARENA_SIZE)
    a.addiu(18,18,1);a.li(8,2);a.branch(5,18,8,'row')
    a.li(8,2);a.sw(8,16,S['status']);a.li(2,1);a.sw(2,16,S['ready']);a.jump('done')
    a.label('failed');a.li(8,100);a.sw(8,16,S['status'])
    a.label('no');a.move(2,0);a.label('done');tag.restore(a,2);a.jr()
    data=a.finish();assert INIT+len(data)<=SELECT;return data


def select_code(plan):
    """a0 exact idle row,a1 captured source character ->v0 ok,v1 flavor."""
    import tag_rush_effects as fx
    p=_plan(plan);a=Assembler(SELECT);tag.save(a);a.move(19,4);a.move(20,5);_receipt(a,'no')
    a.li(22,BANKS);a.li(23,ARENAS);a.li(25,fx.ARENAS);a.li(8,fx.ROWS);a.branch(4,19,8,'row')
    a.li(8,fx.ROWS+fx.STRIDE);a.branch(5,19,8,'no');a.addiu(22,22,BANK_STRIDE);a.addiu(23,23,ARENA_SIZE);a.addiu(25,25,ARENA_SIZE)
    a.label('row')
    for key in ('node','stopping'):
        a.lw(8,19,fx.R[key]);a.branch(5,8,0,'no')
    a.lw(8,19,fx.R['prepared']);a.li(9,fx.PREPARED);a.branch(5,8,9,'no')
    a.lw(8,22,RECEIPT);a.li(9,PREPARED);a.branch(5,8,9,'no')
    a.i(11,8,20,256);a.branch(4,8,0,'no');a.lw(8,19,fx.R['source_character']);a.branch(5,8,20,'no')
    a.addiu(4,22,SPECIAL_DESC);_descriptor(a,4,23,COUNTS,RESOURCE+p['script_offset'],19,'no','special')
    a.addiu(4,22,STANDARD_DESC);_descriptor(a,4,25,(1,6,0,1),None,19,'no','standard')
    _standard_source(a,22,4,'no')
    a.move(18,0)
    if SCOPED_PICCOLO:
        a.li(8,22);a.branch(4,20,8,'special');a.li(8,23);a.branch(4,20,8,'special')
    a.addiu(21,22,STANDARD_META);a.addiu(23,22,STANDARD_DESC)
    a.lw(24,22,STANDARD_RESOURCE);a.lw(25,22,STANDARD_SLOT);a.jump('copy')
    a.label('special');a.li(18,1);a.addiu(21,22,SPECIAL_META);a.addiu(23,22,SPECIAL_DESC);a.li(24,RESOURCE);a.li(25,4)
    a.label('copy');a.move(8,21);a.addiu(9,19,fx.META);_copy(a,8,9,META_SIZE,'copy_meta')
    a.move(8,23);a.addiu(9,19,fx.DESC);_copy(a,8,9,DESC_SIZE,'copy_desc')
    a.sw(24,19,fx.HEADER+28);a.sw(25,19,fx.HEADER+4);a.addiu(8,19,fx.META);a.sw(8,19,fx.HEADER+36)
    a.sw(18,22,FLAVOR);a.move(3,18);a.li(2,1);a.jump('done')
    a.label('no');a.move(2,0);a.move(3,0);a.label('done');a.i(31,3,29,full.OFFSETS[3]);tag.restore(a,2);a.jr()
    data=a.finish();assert SELECT+len(data)<=STATE;return data


# The game's own Special Beam Cannon presentation object, October 14.
# A real SBC dispatches Piccolo's slot4 through native 14B9B0: family0 class
# 2C38E0 (update155C60, constructor155A70, destructor155C10) is allocated in
# the slot's own child pool, under the slot's persistent family0 node 2C38C8.
# Its body drives the slot's own parsed descriptor: every frame 155918 hands
# the moving beam head (+0x60), the beam axis (+0x30) and scale1.0 (+0xC) to
# the rule children. The head starts at the firing fingers and travels
# 46.3units/frame (the character's own blast parameters), which is why the
# real drill core and spiral read correctly at any distance. The gameplay
# beam (collision, damage, clash rows) is a separate action object that only
# reads this visual; no gameplay object is created here, so damage stays the
# tag director's single receipt.
# Piccolo's charge(2), pre-fire(0x40), fire(4) and end(8) animation events
# reach the object through his event row. The wrapper below supplies exactly
# that sequence for the duration of the native update only, then restores
# the row, so no other reader sees a synthetic event.
NATIVE_SPAWN, NATIVE_UPDATE, NATIVE_DTOR = 0x06EC4000, 0x06EC5000, 0x06EC6000
NATIVE_IGNITE, NATIVE_STOP, NATIVE_CLASS = 0x06EC6400, 0x06EC6800, 0x06EC6C00
NSTATE, NSTATE_END = 0x06EC7000, 0x06EC7300
NRECORD, NMETA = NSTATE+0x100, NSTATE+0x180
NMAGIC = 0x53424E31
N = dict(magic=0, node=4, body=8, manager=12, count=16, source=20, source_model=24, model_id=28,
         target=32, target_model=36, target_id=40, stage=44, wait=48, fire=52, ticks=56,
         stop_calls=60, aimed=64, row=68, pool=72, desc=76, refused=80, last_bits=84)
SLOT, RECORD_SIZE, ROW_MODELS = 4, 80, 12
SBC_META_ID = 0x04000129
# Native SBC event sequence (live poll of a real training SBC, Oct14):
# charge2 at329f14, 0x40 at331f16, fire4 at331f18, end8 at335f2.
STAGES = dict(charge=1, charging=2, flash=3, hold=4, fire=5, firing=6, end=7, ended=8)
STAGE_BITS = {1: 2, 3: 0x40, 5: 4, 7: 8}
FIRE_DELAY = 1
STOP_FORCE = 6
# Keep source addresses inert until code emission. Translated discs
# can import the trainer while this feature is disabled; attempting
# to emit it still requires every address to pass the regional map.
KIND0_INIT_CLASS = 0x2C38C8
KIND0_UPDATE, KIND0_CTOR, KIND0_FREE = 0x155C60, 0x155A70, 0x14D798
RECORD_OF, ALLOCATE, RETIRE = 0x14B8E0, 0x1AD7B8, 0x1ADA58
# 1CF740 reads slots2..4 through the model's +0x92C blast table getters.
CHARACTER, SPECIAL_A, SPECIAL_DURATION = 0x1DC280, 0x210F00, 0x210E28
SPECIAL_SPEED, SPECIAL_HOMING = 0x210E60, 0x210EA8


def native_route():
    """The reviewed native route, pinned by tests and the live receipt."""
    return dict(slot=SLOT, family=0, family_class=A(0x2C38E0), init_class=A(KIND0_INIT_CLASS),
                update=A(KIND0_UPDATE), constructor=A(KIND0_CTOR), children_free=A(KIND0_FREE),
                meta_id=SBC_META_ID, events=tuple(STAGE_BITS[s] for s in (1, 3, 5, 7)),
                fire_delay=FIRE_DELAY, aim='record cache (meta+0xC=1, record+0x30, record+0x40 bit2)',
                head=0x60, axis=0x30, scale=0xC)


def _native_owned(a, node, body, fail):
    """node is the current authenticated native SBC visual; body loaded."""
    a.li(8, NSTATE); a.lw(9, 8, N['magic']); a.li(10, NMAGIC); a.branch(5, 9, 10, fail)
    a.lw(9, 8, N['node']); a.branch(4, 9, 0, fail); a.branch(5, 9, node, fail)
    full.pointer(a, node, 64, fail); a.lw(9, node, 40); a.li(10, NATIVE_CLASS); a.branch(5, 9, 10, fail)
    a.lw(body, node, 56); a.li(8, NSTATE); a.lw(9, 8, N['body']); a.branch(5, 9, body, fail)
    full.pointer(a, body, 0x5C0, fail)


def native_spawn_code():
    """a0 owned effect row, a1 charging -> v0 one native SBC visual started.

    Refuses before any allocation unless the row's source is an actual loaded
    Early/End Piccolo whose own slot4 record still names the reviewed family0
    Special Beam Cannon metadata, its persistent family node and child pool.
    The native record and metadata are copied privately; 14B9B0's metadata
    writes are reproduced on the copy from the same native blast getters.
    """
    import tag_rush_effects as fx
    a = Assembler(NATIVE_SPAWN); tag.save(a); a.move(19, 4); a.move(20, 5)
    _receipt(a, 'no'); a.li(21, NSTATE)
    a.lw(8, 21, N['magic']); a.li(9, NMAGIC); a.branch(5, 8, 9, 'free')
    a.lw(8, 21, N['node']); a.branch(5, 8, 0, 'no')
    a.label('free')
    a.li(8, fx.ROWS); a.branch(4, 19, 8, 'row'); a.li(8, fx.ROWS+fx.STRIDE); a.branch(5, 19, 8, 'no')
    a.label('row'); fx.identity(a, 19, 'no')
    a.lw(22, 19, fx.R['source']); a.lw(23, 19, fx.R['source_model'])
    a.lw(8, 23, 12); a.li(9, 22); a.branch(4, 8, 9, 'piccolo'); a.li(9, 23); a.branch(5, 8, 9, 'no')
    a.label('piccolo'); a.lw(17, 23, 16); a.i(11, 8, 17, ROW_MODELS); a.branch(4, 8, 0, 'no')
    a.move(4, 17); a.li(5, SLOT); a.call(A(RECORD_OF)); a.move(18, 2); full.pointer(a, 18, RECORD_SIZE, 'no')
    a.lw(24, 18, 0x24); full.pointer(a, 24, META_SIZE, 'no')
    a.lw(8, 24, 0x3C); a.li(9, SBC_META_ID); a.branch(5, 8, 9, 'no')
    a.i(32, 8, 24, 13); a.branch(5, 8, 0, 'no')
    a.lw(30, 18, 0x28); full.pointer(a, 30, 64, 'no')
    a.lw(8, 30, 40); a.li(9, A(KIND0_INIT_CLASS)); a.branch(5, 8, 9, 'no')
    a.lw(25, 30, 0x24); full.pointer(a, 25, 32, 'no'); a.lw(8, 25); a.branch(5, 8, 30, 'no')
    a.lw(9, 30, 56); full.pointer(a, 9, 0x330, 'no', temp=10, test=11)
    a.lw(10, 9, 4); a.branch(4, 10, 0, 'no')
    for off, delta in ((8, 64), (12, 320)):
        a.lw(11, 9, off); a.addiu(12, 10, delta); a.branch(5, 11, 12, 'no')
    a.addiu(9, 9, 4); a.sw(9, 21, N['desc']); a.sw(25, 21, N['pool'])
    # Private copies: the shared slot record/metadata are never written.
    a.move(8, 24); a.li(9, NMETA); _copy(a, 8, 9, META_SIZE, 'copy_meta')
    a.move(8, 18); a.li(9, NRECORD); _copy(a, 8, 9, RECORD_SIZE, 'copy_record')
    a.move(4, 22); a.call(A(CHARACTER)); full.pointer(a, 2, 0xA28, 'no'); a.lw(8, 2, 0xA24); a.sw(8, 21, 0x108)
    for getter, off in ((SPECIAL_A, 0x10C), (SPECIAL_DURATION, 0x110), (SPECIAL_SPEED, 0x114), (SPECIAL_HOMING, 0x118)):
        a.move(4, 22); a.li(5, SLOT); a.call(A(getter)); a.i(57, 0, 21, off)
    fx.finite(a, 21, (0x10C, 0x110, 0x114, 0x118), 'no')
    for off, low, high in ((0x110, 0., 100.), (0x114, 0., 10000.)):
        a.i(49, 0, 21, off); fp.fconst(a, 1, low); fp.fop(a, 0x34, 0, 1, 0); a.branch(17, 8, 0, 'no')
        fp.fconst(a, 1, high); fp.fop(a, 0x34, 0, 0, 1); a.branch(17, 8, 0, 'no')
    a.sw(17, 21, 0x100); a.li(8, SLOT); a.sw(8, 21, 0x104); a.li(8, NMETA); a.sw(8, 21, 0x124)
    a.sw(30, 21, 0x128)
    for off in range(0x130, 0x150, 4): a.sw(0, 21, off)
    # 14B9B0: metadata+0x28 = duration*30 (60 without its own clock),
    # +0x34 = speed, +0x38 = homing. +0xC selects the record's aim cache.
    a.i(49, 0, 21, 0x110); fp.fconst(a, 1, 30.); fp.fop(a, 2, 0, 0, 1); fp.fop(a, 0x24, 1, 0)
    a.i(57, 1, 21, 0x180+0x28); a.i(32, 8, 21, 0x180+4); a.branch(5, 8, 0, 'own_clock')
    a.li(8, 60); a.sw(8, 21, 0x180+0x28)
    a.label('own_clock')
    for src, dst in ((0x114, 0x34), (0x118, 0x38)): a.lw(8, 21, src); a.sw(8, 21, 0x180+dst)
    a.li(8, 1); a.i(40, 8, 21, 0x180+12)
    # Receipts before allocation: the constructor runs inside the allocator.
    a.sw(0, 21, N['magic']); a.sw(0, 21, N['node']); a.sw(0, 21, N['body'])
    a.li(8, tag.CONTROL); a.lw(9, 8, tag.C['manager']); a.sw(9, 21, N['manager'])
    a.lw(9, 8, tag.C['count']); a.sw(9, 21, N['count'])
    a.sw(22, 21, N['source']); a.sw(23, 21, N['source_model']); a.sw(17, 21, N['model_id'])
    a.lw(8, 19, fx.R['target']); a.sw(8, 21, N['target']); a.lw(8, 19, fx.R['target_model']); a.sw(8, 21, N['target_model'])
    a.lw(8, 8, 16); a.sw(8, 21, N['target_id']); a.sw(19, 21, N['row'])
    a.li(8, STAGES['charge']); a.sw(8, 21, N['stage']); a.r(0x2B, 8, 0, 20)
    a.i(14, 8, 8, 1); a.sw(8, 21, N['fire'])
    for key in ('wait', 'ticks', 'stop_calls', 'aimed', 'last_bits'): a.sw(0, 21, N[key])
    a.move(4, 25); a.li(5, NATIVE_CLASS); a.li(6, NRECORD); a.call(A(ALLOCATE)); a.move(24, 2)
    a.branch(4, 24, 0, 'refused')
    full.pointer(a, 24, 64, 'unknown'); a.lw(8, 24, 40); a.li(9, NATIVE_CLASS); a.branch(5, 8, 9, 'unknown')
    a.lw(25, 24, 56); full.pointer(a, 25, 0x5C0, 'orphan')
    a.lw(8, 25, 0x90); a.li(9, NRECORD); a.branch(5, 8, 9, 'orphan')
    a.lw(8, 25, 0x5B0); a.lw(9, 21, N['desc']); a.branch(5, 8, 9, 'orphan')
    # A real SBC binds its charge and fire contexts from the move's own
    # animation events (mask0x10000 -> bone31). The tag pose plays no such
    # event, so 1513A0 would fall back to the torso: bind both phases to the
    # row's authenticated firing hand before any event, as for every tag beam.
    a.lw(8, 19, fx.R['source_bone']); a.sw(8, 21, N['last_bits'])
    for phase in (0, 1):
        a.addiu(4, 25, 0x360); a.li(5, phase); a.lw(6, 21, N['last_bits']); a.move(7, 0); a.call(A(0x1517A0))
    a.sw(0, 21, N['last_bits'])
    a.sw(24, 21, N['node']); a.sw(25, 21, N['body']); a.li(8, NMAGIC); a.sw(8, 21, N['magic'])
    a.li(2, 1); a.jump('done')
    # Our class retires only through its own destructor; a refused receipt
    # is retired natively. An unrecognized allocator result is never touched.
    a.label('orphan'); a.move(4, 24); a.call(A(RETIRE))
    a.label('unknown')
    a.label('refused'); a.lw(8, 21, N['refused']); a.addiu(8, 8, 1); a.sw(8, 21, N['refused'])
    a.label('no'); a.move(2, 0); a.label('done'); tag.restore(a, 2); a.jr()
    data = a.finish(); assert NATIVE_SPAWN+len(data) <= NATIVE_UPDATE, len(data); return data


def native_update_code():
    """Class update a0 node: deliver this stage's native event, run 155C60.

    The event row word is replaced only around the native call. A stale,
    replaced or unauthenticated node of this class is retired natively.
    """
    import tag_rush_effects as fx
    import opponent_events as events
    a = Assembler(NATIVE_UPDATE); tag.save(a); a.move(16, 4); a.li(17, NSTATE)
    _native_owned(a, 16, 18, 'orphan')
    a.lw(8, 17, N['manager']); a.lw(9, 28, -22364); a.branch(5, 8, 9, 'orphan')
    a.lw(8, 17, N['count']); a.li(9, tag.CONTROL); a.lw(9, 9, tag.C['count']); a.branch(5, 8, 9, 'orphan')
    for actor, model, mid in (('source', 'source_model', 'model_id'), ('target', 'target_model', 'target_id')):
        a.lw(22, 17, N[model]); full.pointer(a, 22, 0x1700, 'end')
        a.lw(8, 22, 16); a.lw(9, 17, N[mid]); a.branch(5, 8, 9, 'end')
        a.i(11, 10, 9, ROW_MODELS); a.branch(4, 10, 0, 'end')
        a.r(0, 9, 0, 9, 2); a.li(10, core.MODELS); a.r(0x21, 9, 9, 10); a.lw(9, 9); a.branch(5, 9, 22, 'end')
        for off in (4, 8): a.lw(8, 22, off); a.li(9, 1); a.branch(5, 8, 9, 'end')
    a.lw(8, 17, N['ticks']); a.addiu(8, 8, 1); a.sw(8, 17, N['ticks'])
    a.i(11, 8, 8, fx.MAX_TICKS); a.branch(5, 8, 0, 'stage')
    a.label('end'); a.lw(8, 17, N['stage']); a.i(10, 9, 8, STAGES['end']); a.branch(4, 9, 0, 'stage')
    a.li(8, STAGES['end']); a.sw(8, 17, N['stage'])
    a.label('stage'); a.lw(8, 17, N['stage']); a.li(9, STAGES['charging']); a.branch(5, 8, 9, 'bits')
    a.lw(9, 17, N['fire']); a.branch(4, 9, 0, 'bits'); a.li(8, STAGES['flash']); a.sw(8, 17, N['stage'])
    a.label('bits'); a.move(20, 0)
    for stage, bits in STAGE_BITS.items():
        a.li(9, stage); a.branch(5, 8, 9, f'not{stage}'); a.li(20, bits); a.label(f'not{stage}')
    a.li(9, STAGES['fire']); a.branch(5, 8, 9, 'row')
    a.lw(9, 17, N['aimed']); a.branch(5, 9, 0, 'row')
    # Aim cache for 130DD8: from the object's own fire-hand context point
    # (+0x3C0, which 155C60 copies to the beam source +0x50 when it fires)
    # to the victim's torso17, so the drill passes through the held pair.
    for off in (0, 4, 8, 12): a.lw(8, 18, 0x3C0+off); a.sw(8, 29, 0x300+off)
    a.lw(4, 17, N['target_id']); a.li(5, 17); a.addiu(6, 29, 0x310); a.call(fx.BONE)
    fx.bounded_point(a, 29, (0x300, 0x304, 0x308, 0x310, 0x314, 0x318), 'row')
    fp.fconst(a, 3, 0.)
    for off in (0, 4, 8):
        a.i(49, 0, 29, 0x310+off); a.i(49, 1, 29, 0x300+off); fp.fop(a, 1, 0, 0, 1)
        a.i(57, 0, 29, 0x320+off); fp.fop(a, 2, 0, 0, 0); fp.fop(a, 0, 3, 3, 0)
    fp.fconst(a, 1, .0001); fp.fop(a, 0x34, 0, 1, 3); a.branch(17, 8, 0, 'row')
    fp.fop(a, 4, 3, 3, 3)
    for off in (0, 4, 8):
        a.i(49, 0, 29, 0x320+off); fp.fop(a, 3, 0, 0, 3); a.i(57, 0, 29, 0x320+off)
    fx.finite(a, 29, (0x320, 0x324, 0x328), 'row')
    for off in (0, 4, 8): a.lw(8, 29, 0x320+off); a.sw(8, 17, 0x130+off)
    a.sw(0, 17, 0x13C); a.lw(8, 17, 0x140); a.i(13, 8, 8, 2); a.sw(8, 17, 0x140)
    a.li(8, 1); a.sw(8, 17, N['aimed'])
    a.label('row'); a.lw(8, 28, -22644); full.pointer(a, 8, 12, 'no_row', temp=9, test=10)
    a.lw(19, 8, 4); full.pointer(a, 19, 16*ROW_MODELS, 'no_row', temp=9, test=10)
    a.lw(9, 17, N['model_id']); a.i(11, 10, 9, 2); a.branch(5, 10, 0, 'row_ready')
    a.li(10, events.ROWS); a.branch(5, 19, 10, 'no_row')
    a.label('row_ready'); a.r(0, 9, 0, 9, 4); a.r(0x21, 19, 19, 9)
    a.lw(21, 19); a.sw(20, 19); a.sw(20, 17, N['last_bits'])
    a.move(4, 16); a.call(A(KIND0_UPDATE)); a.sw(21, 19)
    # The destructor clears the receipt when the native update retired it.
    a.lw(8, 17, N['node']); a.branch(5, 8, 16, 'done')
    a.lw(9, 18); a.lw(8, 17, N['stage'])
    a.li(10, STAGES['charge']); a.branch(5, 8, 10, 'after_charge')
    a.i(12, 10, 9, 0x40); a.branch(4, 10, 0, 'done'); a.li(8, STAGES['charging']); a.sw(8, 17, N['stage']); a.jump('done')
    a.label('after_charge'); a.li(10, STAGES['flash']); a.branch(5, 8, 10, 'after_flash')
    a.li(8, STAGES['hold']); a.sw(8, 17, N['stage']); a.li(8, FIRE_DELAY); a.sw(8, 17, N['wait']); a.jump('done')
    a.label('after_flash'); a.li(10, STAGES['hold']); a.branch(5, 8, 10, 'after_hold')
    a.lw(10, 17, N['wait']); a.addiu(10, 10, -1); a.sw(10, 17, N['wait']); a.branch(5, 10, 0, 'done')
    a.li(8, STAGES['fire']); a.sw(8, 17, N['stage']); a.jump('done')
    a.label('after_hold'); a.li(10, STAGES['fire']); a.branch(5, 8, 10, 'after_fire')
    a.i(12, 10, 9, 0x10); a.branch(4, 10, 0, 'done'); a.li(8, STAGES['firing']); a.sw(8, 17, N['stage']); a.jump('done')
    a.label('after_fire'); a.li(10, STAGES['end']); a.branch(5, 8, 10, 'done')
    a.i(12, 10, 9, 8); a.branch(4, 10, 0, 'done'); a.li(8, STAGES['ended']); a.sw(8, 17, N['stage']); a.jump('done')
    a.label('no_row'); a.move(4, 16); a.call(A(RETIRE)); a.jump('done')
    a.label('orphan'); a.move(4, 16); a.call(A(RETIRE))
    a.label('done'); tag.restore(a); a.jr()
    data = a.finish(); assert NATIVE_UPDATE+len(data) <= NATIVE_DTOR, len(data); return data


def native_dtor_code():
    """Class destructor a0 node: 155C10's child cleanup, then our receipt.

    155C10 additionally sends the owner's action message0xA8 that ends a real
    special move. Piccolo is posed by the tag scene, not that action, so the
    message is not sent; his own state machine is never advanced from here.
    """
    a = Assembler(NATIVE_DTOR); tag.save(a); a.move(16, 4)
    full.pointer(a, 16, 64, 'receipt'); a.lw(18, 16, 56); full.pointer(a, 18, 0x5C0, 'receipt')
    a.lw(4, 18, 0x5B0); full.pointer(a, 4, 0x330, 'receipt'); a.addiu(5, 18, 0x94); a.call(A(KIND0_FREE))
    a.label('receipt'); a.li(17, NSTATE); a.lw(8, 17, N['node']); a.branch(5, 8, 16, 'done')
    a.sw(0, 17, N['node']); a.sw(0, 17, N['body']); a.li(8, STAGES['ended']); a.sw(8, 17, N['stage'])
    a.label('done'); tag.restore(a); a.jr()
    data = a.finish(); assert NATIVE_DTOR+len(data) <= NATIVE_IGNITE, len(data); return data


def native_ignite_code():
    """-> v0 fire requested on the live native SBC visual."""
    a = Assembler(NATIVE_IGNITE); tag.save(a); a.li(17, NSTATE); a.lw(16, 17, N['node'])
    _native_owned(a, 16, 18, 'no'); a.li(8, 1); a.sw(8, 17, N['fire']); a.li(2, 1); a.jump('done')
    a.label('no'); a.move(2, 0); a.label('done'); tag.restore(a, 2); a.jr()
    data = a.finish(); assert NATIVE_IGNITE+len(data) <= NATIVE_STOP, len(data); return data


def native_stop_code():
    """-> v0 1 while our native SBC visual still exists, else0.

    Requests the native end event; after STOP_FORCE requests the node is
    retired natively. No gameplay gate is needed: cleanup must also finish
    after a battle gate closes. A stale receipt is simply withdrawn.
    """
    a = Assembler(NATIVE_STOP); tag.save(a); a.li(17, NSTATE); a.lw(16, 17, N['node'])
    a.branch(4, 16, 0, 'none'); _native_owned(a, 16, 18, 'stale')
    a.lw(8, 17, N['stage']); a.i(10, 9, 8, STAGES['end']); a.branch(4, 9, 0, 'requested')
    a.li(8, STAGES['end']); a.sw(8, 17, N['stage'])
    a.label('requested'); a.lw(8, 17, N['stop_calls']); a.addiu(8, 8, 1); a.sw(8, 17, N['stop_calls'])
    a.i(10, 9, 8, STOP_FORCE); a.branch(5, 9, 0, 'live'); a.move(4, 16); a.call(A(RETIRE))
    a.label('live'); a.li(2, 1); a.jump('done')
    a.label('stale'); a.sw(0, 17, N['node']); a.sw(0, 17, N['body'])
    a.label('none'); a.move(2, 0); a.label('done'); tag.restore(a, 2); a.jr()
    data = a.finish(); assert NATIVE_STOP+len(data) <= NATIVE_CLASS, len(data); return data


def native_pieces():
    return [(NATIVE_SPAWN, native_spawn_code()), (NATIVE_UPDATE, native_update_code()),
            (NATIVE_DTOR, native_dtor_code()), (NATIVE_IGNITE, native_ignite_code()),
            (NATIVE_STOP, native_stop_code()),
            (NATIVE_CLASS, struct.pack('<3I', NATIVE_UPDATE, A(KIND0_CTOR), NATIVE_DTOR)+bytes(4)),
            (NSTATE, bytes(NSTATE_END-NSTATE))]


def pieces(plan):
    _plan(plan)
    return native_pieces()+[(INIT,init_code(plan)),(SELECT,select_code(plan)),
            (STATE,struct.pack('<I',MAGIC)+bytes(STATE_END-STATE-4)),
            (BANKS,bytes(2*BANK_STRIDE)),(ARENAS,bytes(2*ARENA_SIZE))]


def mutable_ranges(plan):
    """Absolute half-open ranges; source pixels, script and metadata immutable."""
    p=_plan(plan)
    return [(NSTATE,NSTATE_END),(STATE+4,STATE_END),(BANKS,BANKS+2*BANK_STRIDE),(ARENAS,ARENAS+2*ARENA_SIZE),
            *((RESOURCE+off,RESOURCE+off+size) for off,size in p['mutable_ranges'])]


def ready_receipts(ram,plan,manager=None,count=None):
    """Check parsed ownership in a complete preparation RAM snapshot.

    This is an installation receipt, not evidence that the live beam rendered.
    A ready pair must retain both descriptors even after one row changes flavor.
    """
    import tag_rush_effects as fx
    import tag_rush_assets as assets
    p=_plan(plan)
    def u(at):return struct.unpack_from('<I',ram,at)[0]
    def require(ok,message):
        if not ok:raise ValueError('Special Beam Cannon '+message)
    require(u(STATE)==MAGIC and u(STATE+S['ready'])==1 and u(STATE+S['status'])==2,'is not initialized')
    for own,native in ((S['manager'],fx.C['manager']),(S['count'],fx.C['count']),(S['pool'],fx.C['pool'])):
        require(u(STATE+own)==u(fx.CONTROL+native),'belongs to a different match')
    if manager is not None:require(u(STATE+S['manager'])==manager,'manager changed')
    if count is not None:require(u(STATE+S['count'])==count,'actor count changed')
    for index in range(2):
        bank=BANKS+index*BANK_STRIDE;row=fx.ROWS+index*fx.STRIDE
        require(u(bank+RECEIPT)==PREPARED,'descriptor pair is incomplete')
        require(u(bank+STANDARD_SLOT)==2 and u(bank+FLAVOR) in (0,1),'descriptor flavor changed')
        standard=u(bank+STANDARD_RESOURCE)
        require(standard%16==0 and assets.BASE<=standard<=assets.END-107456,'standard resource escaped its reservation')
        require(tuple(u(bank+STANDARD_DESC+off) for off in (0,4,8))==
                (standard+192,standard+256,standard+448),'standard script pointer changed')
        for desc,arena,counts in ((bank+STANDARD_DESC,fx.ARENAS+index*ARENA_SIZE,(1,6,0,1)),
                                  (bank+SPECIAL_DESC,ARENAS+index*ARENA_SIZE,COUNTS)):
            require(u(desc+796)==row+fx.HEADER,'descriptor owner changed')
            for group,n in enumerate(counts):
                require(u(desc+780+4*group)==n,'shape count changed')
                if n:
                    start=u(desc+764+4*group)
                    require(start%16==0 and arena<=start<=arena+ARENA_SIZE-n*STRIDES[group],
                            'shape array escaped its private arena')
        script=RESOURCE+p['script_offset']
        require(tuple(u(bank+SPECIAL_DESC+off) for off in (0,4,8))==(script,script+64,script+320),
                'script pointer changed')
        flavor=u(bank+FLAVOR)
        require(u(row+fx.R['flavor'])==flavor,'live flavor changed')
        require(u(row+fx.HEADER+4)==(4 if flavor else 2) and
                u(row+fx.HEADER+28)==(RESOURCE if flavor else standard) and
                u(row+fx.HEADER+36)==row+fx.META,'live resource binding changed')
        #14D460 changes upload masks in separately allocated shape arrays;
        #14D8A8/14FF50 change the parent's context/event state. Neither writes
        #the800-byte parsed descriptor or converted move metadata. Palette
        #changes also live in the separate private texture/CLUT storage.
        for off,cached,size in ((fx.DESC,SPECIAL_DESC if flavor else STANDARD_DESC,DESC_SIZE),
                                (fx.META,SPECIAL_META if flavor else STANDARD_META,META_SIZE)):
            require(ram[row+off:row+off+size]==ram[bank+cached:bank+cached+size],
                    'live descriptor recipe changed')
    return True
