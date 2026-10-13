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
# Piccolo keeps the reviewed ordinary tag-beam recipe (his palette) for now.
# The scoped native Special Beam Cannon spiral is a600-unit visual: fitted to
# this34..60-unit lane it draws only a trail of small hollow rings and no beam
# body (live captures base-raditz/scale1-raditz, Oct12), which is what the
# user saw. Its resource, receipts and selector remain prepared, so flip this
# once its draw gating is solved; until then the pair fires a beam that
# visibly reaches the victim.
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


def pieces(plan):
    _plan(plan)
    return [(INIT,init_code(plan)),(SELECT,select_code(plan)),
            (STATE,struct.pack('<I',MAGIC)+bytes(STATE_END-STATE-4)),
            (BANKS,bytes(2*BANK_STRIDE)),(ARENAS,bytes(2*ARENA_SIZE))]


def mutable_ranges(plan):
    """Absolute half-open ranges; source pixels, script and metadata immutable."""
    p=_plan(plan)
    return [(STATE+4,STATE_END),(BANKS,BANKS+2*BANK_STRIDE),(ARENAS,ARENAS+2*ARENA_SIZE),
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
