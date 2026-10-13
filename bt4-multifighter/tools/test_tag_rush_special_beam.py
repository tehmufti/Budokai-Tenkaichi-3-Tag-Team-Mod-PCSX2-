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


if __name__=='__main__':unittest.main()
