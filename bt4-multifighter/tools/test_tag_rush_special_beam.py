"""Original-disc recipe and executable private descriptor swap regressions."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import struct
import unittest
from pathlib import Path
import tag_rush_special_beam as sbc
import tag_rush_effects as fx
from native_map import A
from test_tag_rush_effects import machine,REGISTRY,BEAM,POOL
from test_tag_rush_camera import run

ISO=Path(__file__).resolve().parents[2]/'games'/('SLUS_219.78.DBZBT4B14REV2ENG.iso'
    if 'bt4' in str(Path(__file__)) else 'Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso')


def plan():
    return dict(reviewed=True,resource_address=sbc.RESOURCE,resource_size=sbc.RESOURCE_SIZE,
        metadata_address=sbc.RESOURCE+sbc.RESOURCE_SIZE,metadata_size=640,
        descriptor_counts=sbc.COUNTS,descriptor_raw_bytes=3288,resource_sha256=sbc.RESOURCE_SHA256,
        script_offset=256,script_size=1920,rule_count=25,mutable_ranges=())


def descriptor(c,at,header,arena,counts,script):
    c.write(at,bytes(800));c.write(at,struct.pack('<3I',script,script+64,script+(320 if counts==sbc.COUNTS else 256)))
    c.w(at+796,header);c.write(at+780,struct.pack('<4I',*counts));cursor=arena
    for group,n in enumerate(counts):
        if n:
            c.w(at+764+4*group,cursor);cursor=(cursor+n*sbc.STRIDES[group]+15)&~15
    return cursor-arena


def fixture(bad=None):
    c=machine();p=plan()
    for address,data in sbc.pieces(p):c.write(address,data)
    c.w(fx.CONTROL+fx.C['init_status'],1);c.w(fx.CONTROL+fx.C['ready'],0)
    for index in range(2):
        row=fx.ROWS+index*fx.STRIDE
        c.w(row+fx.HEADER,7);c.w(row+fx.HEADER+32,7);c.w(row+fx.HEADER+4,2)
        c.w(row+fx.HEADER+28,BEAM['resource_address']);c.w(row+fx.HEADER+36,row+fx.META)
        c.write(row+fx.META,bytes([0x31+index])*sbc.META_SIZE)
        descriptor(c,row+fx.DESC,row+fx.HEADER,fx.ARENAS+index*fx.ARENA_SIZE,(1,6,0,1),BEAM['resource_address']+sbc.STANDARD_SCRIPT_OFFSET)
    c.init_calls=[]
    def metadata(m):
        assert m.r[4:6]==[0,4]
        assert m.u(c.models[0]+2348)==p['metadata_address']
        m.write(m.r[6],bytes([0x71])*sbc.META_SIZE);c.init_calls.append('metadata')
    def parse(m):
        assert m.r[6:10]==[0,sbc.RESOURCE,0,4]
        assert m.u(REGISTRY+148)==5 and m.u(REGISTRY+88)==sbc.ARENA_SIZE
        assert m.u(m.r[4]+4)==4 and m.u(m.r[4]+28)==sbc.RESOURCE
        arena=m.u(REGISTRY+80)
        used=descriptor(m,m.r[5],m.r[4],arena,sbc.COUNTS,sbc.RESOURCE+256)
        if bad=='count':m.w(m.r[5]+780,4)
        elif bad=='pointer':m.w(m.r[5]+768,arena+sbc.ARENA_SIZE-16)
        elif bad=='script':m.w(m.r[5]+8,sbc.RESOURCE+256)
        elif bad=='owner':m.w(m.r[5]+796,0)
        elif bad=='used':used=sbc.ARENA_SIZE+16
        elif bad=='second' and arena>sbc.ARENAS:used=sbc.ARENA_SIZE+16
        m.w(REGISTRY+92,used);c.init_calls.append('parse')
    c.callbacks[A(0x14B108)]=metadata;c.callbacks[A(0x14CEB0)]=parse
    return c,p


def ready(c):
    run(c,sbc.INIT)
    if c.r[2]!=1:raise AssertionError('SBC initialization refused')
    c.w(fx.CONTROL+fx.C['init_status'],2);c.w(fx.CONTROL+fx.C['ready'],1)


def select(c,index,character):
    row=fx.ROWS+index*fx.STRIDE;c.w(row+fx.R['source_character'],character)
    c.r[4:6]=[row,character];run(c,sbc.SELECT)
    if c.r[2]:c.w(row+fx.R['flavor'],c.r[3])  # The SPAWN caller publishes returned flavor.
    return tuple(c.r[2:4])


class SpecialBeamTests(unittest.TestCase):
    def test_composed_effect_bootstrap_runs_both_real_native_recipes_and_receipts(self):
        if not ISO.is_file():self.skipTest('Reviewed local disc unavailable')
        from prototype import ROOT,elf_reader
        from native_map import elf_path
        import tag_rush_assets as assets
        c=machine(prepared=False);special=sbc.build_assets(ISO);standard=assets.read_native_beam_asset(ISO)
        for address,data in special['blocks']:c.write(address,data)
        c.write(BEAM['resource_address'],standard['resource']);c.write(BEAM['metadata_address'],standard['metadata'])
        for address,data in fx.pieces(dict(BEAM,special_beam=special)):c.write(address,data)
        native=elf_reader(elf_path(ROOT))[2];c.write(A(0x14CEB0),native(A(0x14CEB0),0x4F8))
        def entry(m):m.r[2]=m.r[4]+(m.u(m.r[4]+4*m.r[5])&~3)
        def group(m):
            kind=m.r[4];m.r[2]=3 if kind==2 else 1 if kind in (5,10,12,15,16,17,18) else 2 if kind==9 else 0
        def allocate(m):
            size=(m.r[5]+15)&~15;start=c.u(REGISTRY+80)+c.u(REGISTRY+92)
            self.assertLessEqual(c.u(REGISTRY+92)+size,sbc.ARENA_SIZE)
            c.w(REGISTRY+92,c.u(REGISTRY+92)+size);m.r[2]=start
        seen=[]
        def metadata(m):
            seen.append((m.r[5],c.u(c.models[0]+2348)));m.write(m.r[6],bytes(140))
        c.callbacks[A(0x14B108)]=metadata;c.callbacks[A(0x12CD58)]=entry;c.callbacks[A(0x14CE68)]=group
        c.callbacks[A(0x1A7240)]=lambda m:m.r.__setitem__(2,REGISTRY);c.callbacks[A(0x1A7110)]=allocate
        for addr,stride in ((0x1AE148,520),(0x1AE358,264),(0x1AE2A8,136),(0x1AE1F8,72)):
            c.callbacks[A(addr)]=lambda m,stride=stride:m.write(m.r[4],bytes(stride))
        before=c.read(REGISTRY,156);model=c.u(c.models[0]+2348)
        run(c,fx.INIT);self.assertEqual(c.r[2],1);self.assertEqual(c.u(fx.CONTROL+fx.C['ready']),1)
        self.assertEqual(seen,[(2,BEAM['metadata_address'])]*2+[(4,special['metadata_address'])]*2)
        self.assertEqual(c.read(REGISTRY,156),before);self.assertEqual(c.u(c.models[0]+2348),model)
        scoped=int(sbc.SCOPED_PICCOLO)
        self.assertEqual(select(c,0,22),(1,scoped));self.assertEqual(select(c,1,23),(1,scoped))
        self.assertEqual(select(c,0,0),(1,0))
        ram=bytearray(sbc.END)
        for start,end in ((fx.CONTROL,fx.ROWS+2*fx.STRIDE),(sbc.STATE,sbc.STATE_END),
                          (sbc.BANKS,sbc.BANKS+2*sbc.BANK_STRIDE)):
            ram[start:end]=c.read(start,end-start)
        self.assertTrue(sbc.ready_receipts(ram,special,c.u(fx.CONTROL+fx.C['manager']),4))
        struct.pack_into('<I',ram,sbc.BANKS+sbc.SPECIAL_DESC+768,0)
        with self.assertRaises(ValueError):sbc.ready_receipts(ram,special)

    def test_reviewed_source_identical_on_available_discs_and_mutation_scope(self):
        if not ISO.is_file():self.skipTest('Reviewed local disc unavailable')
        paths=[ISO]
        if 'bt4' in str(Path(__file__)):
            paths.append(ISO.with_name('SLUS_219.78.DBZBT4B14REV2.iso'))
        for path in paths:
            if not path.is_file():continue
            p=sbc.build_assets(path);raw=p['blocks'][0][1];resource=raw[:sbc.RESOURCE_SIZE];metadata=raw[sbc.RESOURCE_SIZE:]
            self.assertEqual(p['script_offset'],256);self.assertEqual(p['descriptor_counts'],(2,8,1,0))
            self.assertEqual(sbc.validate_asset(resource,metadata)['resource_sha256'],sbc.RESOURCE_SHA256)
            mutable=bytearray(resource)
            for off,size in p['mutable_ranges']:mutable[off:off+size]=bytes([0xA5])*size
            self.assertTrue(sbc.validate_asset(mutable,metadata)['reviewed'])
            mutable[-7]^=1
            with self.assertRaises(ValueError):sbc.validate_asset(mutable,metadata)
            spans=sorted((a,a+len(b)) for a,b in sbc.pieces(p)+p['blocks'])
            self.assertTrue(all(x[1]<=y[0] for x,y in zip(spans,spans[1:])))
            self.assertLessEqual(spans[-1][1],sbc.END)
            import tag_rush_assets as assets
            standard=assets.read_native_beam_asset(path)['resource']
            self.assertEqual(struct.unpack_from('<I',standard,16)[0]&~3,sbc.STANDARD_SCRIPT_OFFSET)

    def test_initializer_restores_allocator_model_header_and_keeps_normal_effect(self):
        c,p=fixture();allocator=c.read(REGISTRY,156);model=c.u(c.models[0]+2348)
        rows=[c.read(fx.ROWS+i*fx.STRIDE+fx.HEADER,0x440) for i in range(2)]
        run(c,sbc.INIT);self.assertEqual(c.r[2],1)
        self.assertEqual(c.read(REGISTRY,156),allocator);self.assertEqual(c.u(c.models[0]+2348),model)
        self.assertEqual([c.read(fx.ROWS+i*fx.STRIDE+fx.HEADER,0x440) for i in range(2)],rows)
        self.assertEqual(c.init_calls,['metadata','parse']*2)
        self.assertEqual(c.u(sbc.STATE+sbc.S['ready']),1)
        calls=list(c.init_calls);run(c,sbc.INIT);self.assertEqual(c.r[2],0);self.assertEqual(c.init_calls,calls)

    def test_parse_failure_restores_all_temporary_ownership_and_never_arms(self):
        for bad in ('count','pointer','script','owner','used','second'):
            c,p=fixture(bad);allocator=c.read(REGISTRY,156);model=c.u(c.models[0]+2348)
            headers=[c.read(fx.ROWS+i*fx.STRIDE+fx.HEADER,64) for i in range(2)]
            run(c,sbc.INIT);self.assertEqual(c.r[2],0,bad)
            self.assertEqual(c.read(REGISTRY,156),allocator,bad);self.assertEqual(c.u(c.models[0]+2348),model,bad)
            self.assertEqual([c.read(fx.ROWS+i*fx.STRIDE+fx.HEADER,64) for i in range(2)],headers,bad)
            self.assertEqual(c.u(sbc.STATE+sbc.S['ready']),0,bad);self.assertEqual(c.u(sbc.STATE+sbc.S['status']),100,bad)

    def test_same_role_swaps_piccolo_forms_and_restores_standard_without_identity_change(self):
        c,p=fixture();ready(c)
        for index in (0,1):
            row=fx.ROWS+index*fx.STRIDE;bank=sbc.BANKS+index*sbc.BANK_STRIDE
            for character in (22,23,0,77,22,0):
                expected=int(character in (22,23) and sbc.SCOPED_PICCOLO);self.assertEqual(select(c,index,character),(1,expected))
                self.assertEqual(c.u(row+fx.HEADER),7);self.assertEqual(c.u(row+fx.HEADER+32),7)
                self.assertEqual(c.u(row+fx.HEADER+36),row+fx.META)
                self.assertEqual(c.u(row+fx.DESC+796),row+fx.HEADER)
                self.assertEqual(c.u(row+fx.HEADER+4),4 if expected else 2)
                self.assertEqual(c.u(row+fx.HEADER+28),sbc.RESOURCE if expected else BEAM['resource_address'])
                self.assertEqual(c.read(row+fx.META,160),c.read(bank+(sbc.SPECIAL_META if expected else sbc.STANDARD_META),160))
                self.assertEqual(c.read(row+fx.DESC,800),c.read(bank+(sbc.SPECIAL_DESC if expected else sbc.STANDARD_DESC),800))

    def test_invalid_receipt_live_parent_or_changed_parsed_pointer_refuses_before_writes(self):
        cases=[(sbc.STATE,0),(sbc.STATE+sbc.S['manager'],4),(sbc.STATE+sbc.S['count'],9),
            (sbc.STATE+sbc.S['pool'],4),(sbc.STATE+sbc.S['ready'],0),
            (fx.ROWS+fx.R['node'],123),(fx.ROWS+fx.R['stopping'],1),(fx.ROWS+fx.R['prepared'],0),
            (sbc.BANKS+sbc.RECEIPT,0),(sbc.BANKS+sbc.SPECIAL_DESC+796,0),
            (sbc.BANKS+sbc.SPECIAL_DESC+768,sbc.ARENAS+sbc.ARENA_SIZE-16),
            (sbc.BANKS+sbc.STANDARD_DESC+764,0),(sbc.BANKS+sbc.SPECIAL_DESC,sbc.RESOURCE+512)]
        for at,value in cases:
            c,p=fixture();ready(c);c.w(at,value);before=c.read(fx.ROWS,2*fx.STRIDE)
            c.r[4:6]=[fx.ROWS,22];c.w(fx.ROWS+fx.R['source_character'],22)
            before=c.read(fx.ROWS,2*fx.STRIDE);run(c,sbc.SELECT)
            self.assertEqual(tuple(c.r[2:4]),(0,0),hex(at));self.assertEqual(c.read(fx.ROWS,2*fx.STRIDE),before,hex(at))

    def test_selector_preserves_wide_register_fpu_abi_except_returns(self):
        c,p=fixture();ready(c)
        for r in range(1,29):
            if r!=28:c.r[r]=((0xCAFE+r)<<96)|(r<<32)|r
        c.r[4:6]=[fx.ROWS,22];c.w(fx.ROWS+fx.R['source_character'],22)
        old=list(c.r);fpu=list(c.f)
        run(c,sbc.SELECT);self.assertEqual(tuple(c.r[2:4]),(1,int(sbc.SCOPED_PICCOLO)))
        for r in list(range(1,2))+list(range(4,29))+[30]:self.assertEqual(c.r[r],old[r],r)
        self.assertEqual(c.f,fpu)

    def test_native_descriptor_parser_uses_all_twenty_five_rules_and_owned_arenas(self):
        if not ISO.is_file():self.skipTest('Reviewed local disc unavailable')
        from prototype import ROOT,elf_reader
        from native_map import elf_path
        c,p=fixture();real=sbc.build_assets(ISO)
        for address,data in real['blocks']:c.write(address,data)
        native=elf_reader(elf_path(ROOT))[2]
        c.write(A(0x14CEB0),native(A(0x14CEB0),0x4F8))
        del c.callbacks[A(0x14CEB0)]
        def entry(m):m.r[2]=m.r[4]+(m.u(m.r[4]+4*m.r[5])&~3)
        def group(m):
            kind=m.r[4];m.r[2]=3 if kind==2 else 1 if kind in (5,10,12,15,16,17,18) else 2 if kind==9 else 0
        def allocate(m):
            self.assertEqual(m.r[4],REGISTRY)
            start=c.u(REGISTRY+80)+c.u(REGISTRY+92);size=(m.r[5]+15)&~15
            self.assertLessEqual(c.u(REGISTRY+92)+size,sbc.ARENA_SIZE)
            c.w(REGISTRY+92,c.u(REGISTRY+92)+size);m.r[2]=start
        shapes=[]
        def texture(m,stride):
            # Texture upload parsing is independently authenticated by source
            # hash/relocation bounds. Here execute the real native descriptor
            # traversal and allocation, and record its exact shape call sites.
            shapes.append((m.r[4],m.r[5],stride));m.write(m.r[4],bytes(stride))
        c.callbacks[A(0x12CD58)]=entry;c.callbacks[A(0x14CE68)]=group
        c.callbacks[A(0x1A7240)]=lambda m:m.r.__setitem__(2,REGISTRY)
        c.callbacks[A(0x1A7110)]=allocate
        for addr,stride in ((0x1AE148,520),(0x1AE358,264),(0x1AE2A8,136),(0x1AE1F8,72)):
            c.callbacks[A(addr)]=lambda m,stride=stride:texture(m,stride)
        ready(c);self.assertEqual(len(shapes),22)
        for index in (0,1):
            desc=sbc.BANKS+index*sbc.BANK_STRIDE+sbc.SPECIAL_DESC
            self.assertEqual(struct.unpack('<4I',c.read(desc+780,16)),sbc.COUNTS)
            offsets=[]
            for kind,commands,_ in sbc.ROWS:
                section=c.u(desc+12+16*kind)
                self.assertEqual(c.read(section,3),bytes((kind,commands,dict((k,s) for k,_,s in sbc.ROWS)[kind])))
                offsets.append(c.read(desc+20+16*kind,1)[0])
            self.assertEqual(offsets,[0,1,12,13,19,20,22,23])
            self.assertEqual(offsets[-1]+sbc.ROWS[-1][1],25)
        # Native resource remains eligible after its texture relocation words
        # have been used; switching forms cannot request a different move.
        scoped=int(sbc.SCOPED_PICCOLO)
        self.assertEqual(select(c,0,23),(1,scoped));self.assertEqual(select(c,1,22),(1,scoped))


SHARED_RECORD, SHARED_META, INIT_NODE, INIT_BODY, CHILD_POOL = 0x2500000, 0x2500100, 0x2501000, 0x2502000, 0x2503000
NATIVE_NODE, NATIVE_BODY, EVENTS, CHARACTER_DATA = 0x2510000, 0x2511000, 0x2520000, 0x2530000


def native_machine(character=22):
    """Effect rows wired to the real native-SBC route; native leaves are callbacks."""
    import opponent_events as events
    c,p=fixture();ready(c)
    beam=dict(BEAM,special_beam=p)
    for address,data in ((fx.SPAWN,fx.spawn_code(special=True)),(fx.CHARGE_SPAWN,fx.spawn_code(charging=True,special=True)),
                         (fx.IGNITE,fx.ignite_code(special=True)),(fx.STOP,fx.stop_code(True))):
        c.write(address,data)
    piccolo=c.models[2];c.w(piccolo+12,character)
    model_id=c.u(piccolo+16)
    # Shared slot4 record and its converted SBC metadata (family0, meta id).
    c.write(SHARED_RECORD,bytes(80));c.w(SHARED_RECORD+0x1C,0x1DEAF00)
    c.w(SHARED_RECORD+0x24,SHARED_META);c.w(SHARED_RECORD+0x28,INIT_NODE)
    meta=bytearray(160);meta[0:4]=bytes.fromhex('d4029e02');meta[4]=2;meta[13]=0
    struct.pack_into('<I',meta,0x28,60);struct.pack_into('<3f',meta,0x2C,0.,1.,500.)
    struct.pack_into('<I',meta,0x3C,sbc.SBC_META_ID);c.write(SHARED_META,bytes(meta))
    c.write(INIT_NODE,bytes(64));c.w(INIT_NODE+40,sbc.KIND0_INIT_CLASS);c.w(INIT_NODE+0x24,CHILD_POOL)
    c.w(INIT_NODE+56,INIT_BODY);c.w(CHILD_POOL,INIT_NODE)
    c.write(INIT_BODY,struct.pack('<4I',0,0x1DEB000,0x1DEB040,0x1DEB140))
    c.w(CHARACTER_DATA+0xA24,0x2C)
    c.w(c.r[28]-22644,EVENTS);c.w(EVENTS+4,events.ROWS)
    c.write(events.ROWS,bytes(16*12));c.w(events.ROWS+16*model_id,0x80000)
    c.native=[];c.row_seen=[];c.model_id=model_id
    def record(m):
        c.native.append(('record',m.r[4],m.r[5]));m.r[2]=SHARED_RECORD
    def character_data(m):
        c.native.append(('character',m.r[4]));m.r[2]=CHARACTER_DATA
    def getter(value,name):
        def run(m):
            c.native.append((name,m.r[4],m.r[5]));m.set_number(0,value)
        return run
    def allocate(m):
        c.native.append(('allocate',m.r[4],m.r[5],m.r[6]))
        if getattr(c,'allocation','ok')=='refused':m.r[2]=0;return
        m.write(NATIVE_NODE,bytes(64));m.write(NATIVE_BODY,bytes(0x5C0))
        m.w(NATIVE_NODE+32,m.r[4]);m.w(NATIVE_NODE+40,0x1234 if c.allocation=='unknown' else m.r[5])
        m.w(NATIVE_NODE+56,NATIVE_BODY);m.w(NATIVE_BODY+0x90,m.r[6]);m.w(NATIVE_BODY+0x5B0,INIT_BODY+4)
        m.write(NATIVE_BODY+0x3C0,struct.pack('<4f',10.,-20.,30.,1.));m.r[2]=NATIVE_NODE
    c.allocation='ok'
    def update(m):
        assert m.r[4]==NATIVE_NODE
        bits=m.u(events.ROWS+16*c.model_id);c.row_seen.append(bits)
        flags=m.u(NATIVE_BODY)
        for bit,flag in ((2,0x40),(4,0x10),(8,9)):
            if bits&bit:flags|=flag
        m.w(NATIVE_BODY,flags)
    def free(m):c.native.append(('free',m.r[4],m.r[5]))
    c.callbacks.update({sbc.RECORD_OF:record,sbc.CHARACTER:character_data,
        sbc.SPECIAL_A:getter(1.,'a'),sbc.SPECIAL_DURATION:getter(2.,'duration'),
        sbc.SPECIAL_SPEED:getter(46.296,'speed'),sbc.SPECIAL_HOMING:getter(0.,'homing'),
        sbc.ALLOCATE:allocate,sbc.KIND0_UPDATE:update,sbc.KIND0_FREE:free})
    return c


def native_update(c):
    c.r[4]=NATIVE_NODE;run(c,sbc.NATIVE_UPDATE)


class NativeSpecialBeamTests(unittest.TestCase):
    def test_route_pins_the_executables_own_family0_sbc_object_and_blast_getters(self):
        from prototype import ROOT,elf_reader
        from native_map import elf_path
        try:native=elf_reader(elf_path(ROOT))[2]
        except Exception as error:self.skipTest(f'Executable unavailable: {error}')
        u=lambda at:struct.unpack('<I',native(A(at),4))[0]
        route=sbc.native_route()
        self.assertEqual((route['slot'],route['family'],route['events'],route['fire_delay']),(4,0,(2,0x40,4,8),1))
        # 14B9B0's family table: kind0 dispatches class2C38E0; its init class is2C38C8.
        self.assertEqual(u(0x2C3704+12),route['family_class']);self.assertEqual(u(0x2C3700+12),sbc.KIND0_INIT_CLASS)
        self.assertEqual(tuple(u(0x2C38E0+4*i) for i in range(3)),(A(0x155C60),A(0x155A70),A(0x155C10)))
        # Our class keeps the native constructor; the update/destructor wrap it.
        c=native_machine()
        self.assertEqual(struct.unpack('<3I',c.read(sbc.NATIVE_CLASS,12)),(sbc.NATIVE_UPDATE,sbc.KIND0_CTOR,sbc.NATIVE_DTOR))
        # 1CF740 fills a slot2..4 request through the +0x92C blast getters.
        jal=lambda at:(u(at)&0x3FFFFFF)<<2
        self.assertEqual([jal(at) for at in (0x1CF838,0x1CF848,0x1CF858,0x1CF868)],
                         [sbc.SPECIAL_A,sbc.SPECIAL_DURATION,sbc.SPECIAL_SPEED,sbc.SPECIAL_HOMING])
        # The kind0 child dispatch hands the moving head, axis and scale to every rule.
        self.assertEqual((route['head'],route['axis'],route['scale']),(0x60,0x30,0xC))

    def test_piccolo_row_starts_the_native_object_without_a_private_emitter(self):
        for character in (22,23):
            c=native_machine(character);shared=c.read(SHARED_RECORD,80)+c.read(SHARED_META,160)
            c.r[4:6]=[1,60];run(c,fx.CHARGE_SPAWN);self.assertEqual(c.r[2],1,character)
            row=fx.ROWS+fx.STRIDE
            self.assertEqual((c.u(row+fx.R['native']),c.u(row+fx.R['node']),c.u(row+fx.R['flavor'])),(1,0,0))
            self.assertFalse(c.requests,'no private 16A7D0 emitter')
            self.assertEqual(c.read(SHARED_RECORD,80)+c.read(SHARED_META,160),shared,'shared slot data untouched')
            self.assertIn(('record',c.model_id,4),c.native)
            self.assertIn(('allocate',CHILD_POOL,sbc.NATIVE_CLASS,sbc.NRECORD),c.native)
            rec=c.read(sbc.NRECORD,80)
            self.assertEqual(struct.unpack_from('<2I',rec),(c.model_id,4))
            self.assertEqual(struct.unpack_from('<I',rec,8)[0],0x2C)
            self.assertEqual([round(x,3) for x in struct.unpack_from('<4f',rec,12)],[1.,2.,46.296,0.])
            self.assertEqual(struct.unpack_from('<I',rec,0x1C)[0],0x1DEAF00)
            self.assertEqual(struct.unpack_from('<2I',rec,0x24),(sbc.NMETA,INIT_NODE))
            meta=c.read(sbc.NMETA,160)
            self.assertEqual(struct.unpack_from('<I',meta,0x28)[0],60)
            self.assertAlmostEqual(struct.unpack_from('<f',meta,0x34)[0],46.296,places=3)
            self.assertEqual((meta[12],struct.unpack_from('<f',meta,0x38)[0]),(1,0.))
            n=lambda key:c.u(sbc.NSTATE+sbc.N[key])
            self.assertEqual((n('magic'),n('node'),n('body'),n('stage'),n('fire')),(sbc.NMAGIC,NATIVE_NODE,NATIVE_BODY,1,0))
            # Both native contexts are bound to the row's firing hand before any event.
            for phase in (0,1):self.assertEqual(c.u(NATIVE_BODY+0x360+16+64*phase),31)
            self.assertEqual(c.u(NATIVE_BODY+0x360)&5,5)

    def test_other_characters_and_unreviewed_slots_keep_the_ordinary_recipe(self):
        cases=[('character',lambda c:c.w(c.models[2]+12,0)),('meta',lambda c:c.w(SHARED_META+0x3C,0x4000009)),
               ('family',lambda c:c.write(SHARED_META+13,b'\x02')),('init',lambda c:c.w(INIT_NODE+40,0x2C3988)),
               ('pool owner',lambda c:c.w(CHILD_POOL,0)),('descriptor',lambda c:c.w(INIT_BODY+12,0x1DEB100)),
               ('duration',lambda c:c.callbacks.__setitem__(sbc.SPECIAL_DURATION,lambda m:m.set_number(0,0.))),
               ('refused',lambda c:setattr(c,'allocation','refused')),('busy',lambda c:(c.w(sbc.NSTATE,sbc.NMAGIC),c.w(sbc.NSTATE+4,0x2600000)))]
        for name,bad in cases:
            c=native_machine();bad(c);before=c.read(SHARED_RECORD,80)
            c.r[4:6]=[1,60];run(c,fx.CHARGE_SPAWN)
            row=fx.ROWS+fx.STRIDE
            self.assertEqual(c.u(row+fx.R['native']),0,name)
            self.assertEqual(c.read(SHARED_RECORD,80),before,name)
            if name=='busy':self.assertEqual(c.u(sbc.NSTATE+4),0x2600000,name)
            else:self.assertEqual(c.u(sbc.NSTATE+sbc.N['node']),0,name)
            self.assertEqual(c.u(sbc.NSTATE+sbc.N['refused']),int(name=='refused'),name)

    def test_unknown_allocator_result_is_never_retired_or_published(self):
        c=native_machine();c.allocation='unknown'
        c.r[4:6]=[1,60];run(c,fx.CHARGE_SPAWN)
        self.assertEqual(c.u(sbc.NSTATE+sbc.N['node']),0);self.assertEqual(c.read(NATIVE_NODE,1),b'\0')

    def test_wrapper_supplies_the_native_event_sequence_only_inside_the_update(self):
        import opponent_events as events
        c=native_machine();c.r[4:6]=[1,60];run(c,fx.CHARGE_SPAWN)
        row=events.ROWS+16*c.model_id
        stages=[]
        def step():
            native_update(c);stages.append(c.u(sbc.NSTATE+sbc.N['stage']))
            self.assertEqual(c.u(row),0x80000,'event row restored after the native update')
        step();step()
        c.r[4]=fx.ROWS+fx.STRIDE;run(c,fx.IGNITE);self.assertEqual(c.r[2],1)
        self.assertFalse(c.requests)
        for _ in range(4):step()
        c.r[4]=0;run(c,fx.STOP);self.assertEqual(c.r[2],1)
        step();step()
        # The row holds exactly the native event for that update, nothing else.
        self.assertEqual(c.row_seen,[2,0,0x40,0,4,0,8,0])
        self.assertEqual(stages,[2,2,4,5,6,6,8,8])
        # Aim cache: the fire-hand context point to the victim's torso17.
        hand=struct.unpack('<3f',c.read(NATIVE_BODY+0x3C0,12))
        torso=struct.unpack('<3f',c.read(c.u(c.models[1]+3436+4*17)+64,12))
        delta=[t-h for t,h in zip(torso,hand)];size=sum(x*x for x in delta)**.5
        aim=struct.unpack('<3f',c.read(sbc.NRECORD+0x30,12))
        for got,want in zip(aim,delta):self.assertAlmostEqual(got,want/size,places=5)
        self.assertEqual(c.u(sbc.NRECORD+0x40)&2,2);self.assertEqual(c.u(sbc.NSTATE+sbc.N['aimed']),1)

    def test_destructor_frees_children_without_the_owner_action_message(self):
        c=native_machine();c.r[4:6]=[1,60];run(c,fx.CHARGE_SPAWN)
        c.r[4]=NATIVE_NODE;run(c,sbc.NATIVE_DTOR)
        self.assertIn(('free',INIT_BODY+4,NATIVE_BODY+0x94),c.native)
        self.assertEqual((c.u(sbc.NSTATE+sbc.N['node']),c.u(sbc.NSTATE+sbc.N['body'])),(0,0))
        c.r[4]=0;run(c,fx.STOP);self.assertEqual(c.r[2],0)

    def test_stop_retires_natively_when_the_end_event_is_not_consumed(self):
        c=native_machine();c.r[4:6]=[1,60];run(c,fx.CHARGE_SPAWN)
        for call in range(sbc.STOP_FORCE):
            c.r[4]=0;run(c,fx.STOP);self.assertEqual(c.r[2],1)
            self.assertEqual(c.read(NATIVE_NODE,1)[0]&1,int(call==sbc.STOP_FORCE-1))
        self.assertEqual(c.u(sbc.NSTATE+sbc.N['stage']),7)

    def test_stale_or_foreign_node_of_our_class_is_retired_without_events(self):
        import opponent_events as events
        for stale in ('node','world'):
            c=native_machine();c.r[4:6]=[1,60];run(c,fx.CHARGE_SPAWN)
            if stale=='node':c.w(sbc.NSTATE+sbc.N['node'],0x2600000)
            else:c.w(sbc.NSTATE+sbc.N['manager'],0x1234)
            native_update(c)
            self.assertEqual(c.row_seen,[],stale);self.assertEqual(c.read(NATIVE_NODE,1)[0]&1,1,stale)
            self.assertEqual(c.u(events.ROWS+16*c.model_id),0x80000,stale)

    def test_native_addresses_are_mapped_only_when_the_supported_effect_is_emitted(self):
        import importlib.util
        from unittest.mock import patch
        from native_map import NativeMapError
        real_map=sbc.A
        unsupported={0x2C38C8,0x2C38E0,0x155C60,0x155A70,0x14D798,0x14B8E0,
                     0x1DC280,0x210F00,0x210E28,0x210E60,0x210EA8}
        def region(address):
            if address in unsupported:raise NativeMapError('Unreviewed regional SBC address')
            return real_map(address)
        spec=importlib.util.spec_from_file_location('sbc_region_import_probe',sbc.__file__)
        module=importlib.util.module_from_spec(spec)
        with patch('native_map.A',side_effect=region):spec.loader.exec_module(module)
        self.assertEqual(module.NATIVE_SPAWN,sbc.NATIVE_SPAWN)
        # Unsupported discs can import the disabled feature, but cannot emit
        # guest code containing an untranslated native address.
        for emit in (module.native_route,module.native_pieces):
            with self.assertRaisesRegex(NativeMapError,'Unreviewed regional SBC'):emit()

    def test_native_pieces_stay_inside_the_sbc_reservation_and_preserve_abi(self):
        spans=sorted((a,a+len(b)) for a,b in sbc.native_pieces())
        self.assertTrue(all(x[1]<=y[0] for x,y in zip(spans,spans[1:])))
        self.assertGreaterEqual(spans[0][0],sbc.RESOURCE+sbc.RESOURCE_SIZE+sbc.METADATA_SIZE)
        self.assertLessEqual(spans[-1][1],sbc.END)
        self.assertIn((sbc.NSTATE,sbc.NSTATE_END),sbc.mutable_ranges(plan()))
        c=native_machine();c.r[4:6]=[1,60];run(c,fx.CHARGE_SPAWN)
        for r in range(1,29):
            if r not in (28,):c.r[r]=((0xBEEF+r)<<96)|(r<<32)|r
        c.r[4]=NATIVE_NODE;old=list(c.r);fpu=list(c.f);run(c,sbc.NATIVE_UPDATE)
        for r in list(range(1,29))+[30]:
            if r!=28:self.assertEqual(c.r[r],old[r],r)
        self.assertEqual(c.f,fpu)


if __name__=='__main__':unittest.main()
