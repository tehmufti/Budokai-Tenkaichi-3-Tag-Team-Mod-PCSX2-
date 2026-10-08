"""Run native row/pool registration and verify held initialization isolation."""
import copy
import struct
import unittest
from pathlib import Path

import extra_special_pools as fix
from camera_snapshot import read_ram
from prototype import ROOT,elf_reader
from test_terrain_crossing_guard import ScalarMips

NATIVE=elf_reader(ROOT/'analysis/SLUS_216.78')[2]
SOURCE=ROOT/'runtime128/sstates/SLUS-21678 (428113C2).148.p2s'
PREPARED=ROOT/'analysis/prepared-states/20260920-184301-c345ccc6'


def three_mask_scan(words,base,span):
    """The former relocation scan, kept as the reference for pointer_word_indices."""
    import numpy as np
    return np.flatnonzero((words>=base)&(words<base+span)&((words&3)==0))


def fixture():
    ram=bytearray(read_ram(SOURCE));u=lambda p:struct.unpack_from('<I',ram,p)[0]
    for i in range(6):
        actor=u(fix.core.POINTERS+i*4)
        for off in (0x1278,0x127C,0x1280,0x1284):struct.pack_into('<I',ram,actor+off,0)
    return ram


class Cpu(ScalarMips):
    instruction_budget=400000
    hi=lo=0
    def extra_instruction(self,ins,pc):
        if ins>>26 in (30,31,37):
            op=ins>>26;rs,rt=(ins>>21)&31,(ins>>16)&31;imm=ins&65535;imm=imm if imm<32768 else imm-65536
            address=(self.r[rs]+imm)&0xFFFFFFFF
            if op==31:self.write(address,(self.r[rt]&((1<<128)-1)).to_bytes(16,'little'))
            else:self.r[rt]=int.from_bytes(self.read(address,2 if op==37 else 16),'little')
            return None
        if ins>>26 in (26,27,44,45):
            op=ins>>26;rs,rt=(ins>>21)&31,(ins>>16)&31;imm=ins&65535;imm=imm if imm<32768 else imm-65536
            address=(self.r[rs]+imm)&0xFFFFFFFF
            # Native14B9B0 uses paired unaligned operations for its aligned
            # 28-byte stack record. These cases each transfer a full doubleword.
            assert address&7==(7 if op in (26,44) else 0)
            address&=~7
            if op in (26,27):self.r[rt]=int.from_bytes(self.read(address,8),'little')
            else:self.write(address,(self.r[rt]&0xFFFFFFFFFFFFFFFF).to_bytes(8,'little'))
            return None
        if ins>>26==17 and (ins>>21)&31==16 and ins&63==36:
            self.f[(ins>>6)&31]=int(round(self.number((ins>>11)&31)))&0xFFFFFFFF;return None
        if ins>>26==0 and ins&63==2:
            self.r[(ins>>11)&31]=(self.r[(ins>>16)&31]&0xFFFFFFFF)>>((ins>>6)&31);return None
        if ins>>26==0 and ins&63==24:
            value=self.signed_word(self.r[(ins>>21)&31])*self.signed_word(self.r[(ins>>16)&31])
            self.lo=value&0xFFFFFFFF;self.hi=(value>>32)&0xFFFFFFFF;return None
        if ins>>26==0 and ins&63==27:
            left,right=self.r[(ins>>21)&31]&0xFFFFFFFF,self.r[(ins>>16)&31]&0xFFFFFFFF
            if right:self.lo,self.hi=left//right,left%right
            return None
        if ins>>26==0 and ins&63 in (16,18):
            self.r[(ins>>11)&31]=self.hi if ins&63==16 else self.lo;return None
        if ins>>26==0 and ins&63 in (17,19):
            value=self.r[(ins>>21)&31]&0xFFFFFFFF
            if ins&63==17:self.hi=value
            else:self.lo=value
            return None
        if ins>>26==0 and ins&63==39:
            self.r[(ins>>11)&31]=~(self.r[(ins>>21)&31]|self.r[(ins>>16)&31])&0xFFFFFFFFFFFFFFFF;return None
        if ins>>26==0 and ins&63==10:
            if not self.r[(ins>>16)&31]:self.r[(ins>>11)&31]=self.r[(ins>>21)&31]
            return None
        if ins>>26==41:
            rs,rt=(ins>>21)&31,(ins>>16)&31;imm=ins&65535;imm=imm if imm<32768 else imm-65536
            self.write((self.r[rs]+imm)&0xFFFFFFFF,struct.pack('<H',self.r[rt]&65535));return None
        return super().extra_instruction(ins,pc)


def machine(empty_slots=()):
    ram=fixture();u=lambda p:struct.unpack_from('<I',ram,p)[0]
    for mid,slot in empty_slots:
        model=u(fix.core.MODELS+4*mid);bundle=u(u(model+20)+32)
        struct.pack_into('<I',ram,model+156+slot*4,0)
        struct.pack_into('<I',ram,bundle+4*(slot+1),u(bundle+4*(slot+2)))
    manifest=fix.build_memory(ram)
    c=Cpu({'segments':[]});c.manifest=manifest;c.native_calls=[];c.allocations=[]
    primary,allocator=u(fix.GLOBAL),u(fix.ALLOC_GLOBAL);pool=u(primary)
    c.primary=primary;c.allocator=allocator;c.pool=pool
    for p,n in ((fix.GLOBAL,8),(fix.ALLOC_GLOBAL,4),(fix.core.ACTORS,4),
                (fix.core.MODE,16),(fix.core.PAIR,32),(fix.core.POINTERS,24),
                (fix.core.MODELS,48),(primary,12),(pool,24),(u(pool+16),3*64),
                (allocator,156),(0x2C3700,0x400),
                (fix.start.CONTROL,0x100),(fix.intro.CONTROL,0x100)):
        c.write(p,ram[p:p+n])
    for i in range(6):
        p=u(fix.core.POINTERS+4*i);model=u(fix.core.MODELS+4*u(p+12))
        c.write(p,ram[p:p+0x1600]);c.write(model,ram[model:model+0x1670])
    for b in manifest['blocks']:c.write(b['address'],bytes.fromhex(b['data_hex']))
    for p,n in ((0x14AE50,0xC8),(0x14B018,0xF0),(0x14B918,0x98),
                (0x1AD468,0x60),(0x1AD4C8,0x1E0),(0x1AD728,0x90),
                (0x1AD7B8,0x68),(0x1AD820,0xB0),(0x1AD988,0x70),
                (0x1A7230,0x10),(0x1A7240,0x10),(0x14AFC8,0x28)):
        c.write(p,NATIVE(p,n))
    # Reapply the three scoped calls over the native routines just installed.
    for p,code,_,_ in fix.META_CALLS:c.w(p,(3<<26)|(code>>2))
    c.callbacks[manifest['previous_frame']]=lambda m:m.native_calls.append(('frame',))
    def allocate(m):
        p=0x02000000+len(c.allocations)*fix.ARENA_BYTES;c.allocations.append((p,m.r[4]))
        m.r[2]=p
    c.callbacks[0x2554D8]=allocate
    c.callbacks[0x2A9ACC]=lambda m:None  # new fake arenas are zero by construction
    def bump(m):
        group=m.r[4];p=allocator+16*group;size=(m.r[5]+31)&~31
        cursor=m.u(p+4);assert cursor+size<=m.u(p)+m.u(p+8)
        m.w(p+4,cursor+size);m.w(p+12,m.u(p+12)+size);m.r[2]=cursor
    c.callbacks[0x1A7110]=bump
    c.callbacks[0x1A71B8]=lambda m:None
    def metadata(m):
        # Heavy native resource parsing is outside this unit. Its callers,
        # independent row address and actual-model resource bridge run natively.
        mid,slot,out=m.r[4],m.r[5],m.r[6]
        c.native_calls.append(('metadata',mid,slot,out,m.u(fix.CONTROL+24)))
        m.write(out,bytes(140));m.write(out+13,bytes([0]))
    c.callbacks[0x14B108]=metadata
    parent_callback=struct.unpack('<I',NATIVE(0x2C3700+12,4))[0]
    initializer=struct.unpack('<I',NATIVE(parent_callback+4,4))[0]
    def parent_init(m):
        node,row=m.r[4],m.r[5]
        c.native_calls.append(('parent',node,row,m.u(node+56)))
        m.w(m.u(node+56)+800,row)
        m.w(node+36,m.u(node+56)+1024)
    c.callbacks[initializer]=parent_init
    return c


class ExtraSpecialPoolTests(unittest.TestCase):
    def test_native_initializer_accepts_declared_empty_effect_without_a_parent(self):
        c=machine(empty_slots=((2,0),(4,1)))
        c.run(fix.CODE)
        self.assertEqual(c.u(fix.CONTROL),5)
        self.assertEqual(c.u(fix.CONTROL+12),4)
        for mid,slot in ((2,0),(4,1)):
            row=fix.ROWS+mid*fix.ROW_BYTES+slot*80
            self.assertEqual(c.u(row+28),0)
            self.assertEqual(c.u(row+40),0)
            self.assertEqual(c.u(row+36),fix.ROWS+mid*fix.ROW_BYTES+480+140*slot)
        self.assertEqual(len([x for x in c.native_calls if x[0]=='metadata']),20)
        self.assertEqual(len([x for x in c.native_calls if x[0]=='parent']),18)

    def test_null_resource_for_nonempty_bundle_slot_is_still_rejected(self):
        ram=fixture();u=lambda p:struct.unpack_from('<I',ram,p)[0]
        model=u(fix.core.MODELS+8)
        self.assertFalse(fix.absent_special_resource(ram,model,0))
        struct.pack_into('<I',ram,model+156,0)
        with self.assertRaisesRegex(ValueError,'fighter 2.*slot 1'):
            fix.build_memory(ram)

    def test_native_registration_uses_independent_own_rows_and_restores_allocator(self):
        c=machine();before=c.read(c.allocator,156);regs=c.r.copy();fp=c.f.copy()
        c.run(fix.CODE)
        self.assertEqual(c.u(fix.CONTROL),5);self.assertEqual(c.u(fix.CONTROL+12),4)
        self.assertEqual(c.read(c.allocator,156),before)
        self.assertEqual(c.r,regs);self.assertEqual(c.f[20:32],fp[20:32])
        self.assertEqual(c.u(c.primary+8),12);self.assertEqual(c.u(fix.CONTROL+16),0)
        self.assertEqual(len([x for x in c.native_calls if x[0]=='metadata']),20)
        for i in range(4):
            record=fix.RECORDS+i*64;mid=c.u(record+4);model=c.u(record+8);row=fix.ROWS+mid*1344
            arena=c.u(record+12);self.assertEqual(arena,0x02000000+i*fix.ARENA_BYTES)
            self.assertLess(c.u(record+20),fix.ARENA_BYTES)
            self.assertEqual(c.u(row+1324),c.u(record+16))
            for slot in range(5):
                r=row+80*slot;parent=c.u(r+40);body=c.u(parent+56)
                self.assertEqual(c.u(r+28),c.u(model+156+4*slot))
                self.assertEqual(c.u(r+36),row+480+140*slot)
                self.assertEqual(c.u(body+800),r)
                self.assertTrue(arena<=body<arena+fix.ARENA_BYTES)
        prior=len(c.native_calls);c.run(fix.CODE)
        self.assertEqual(len(c.native_calls),prior+1,'Second frame must only tail to original frame')

    def test_capture_input_and_prearmed_start_fail_closed(self):
        for offset in (0x1278,0x127C,0x1280,0x948):
            c=machine();actor=c.u(fix.core.POINTERS+8);c.w(actor+offset,7)
            c.w(fix.start.CONTROL,1);c.w(fix.start.CONTROL+4,1)
            c.w(fix.start.CONTROL+8,c.u(fix.CONTROL+4))
            c.run(fix.CODE);self.assertEqual(c.u(fix.CONTROL),102)
            self.assertEqual(c.allocations,[]);self.assertEqual(c.u(fix.start.CONTROL+4),0)
            self.assertEqual(c.u(c.primary+8),2)

    def test_failed_allocation_never_publishes_ready_or_changes_native_allocator(self):
        c=machine();before=c.read(c.allocator,156)
        c.callbacks[0x2554D8]=lambda m:m.r.__setitem__(2,0)
        c.run(fix.CODE);self.assertEqual(c.u(fix.CONTROL),110)
        self.assertEqual(c.read(c.allocator,156),before)
        self.assertEqual(c.u(c.pool+12),0);self.assertEqual(c.u(c.primary+8),2)

    def test_post_native_failure_restores_allocator_and_init_alias(self):
        c=machine();before=c.read(c.allocator,156)
        def bad_metadata(m):m.write(m.r[6],bytes(140));m.write(m.r[6]+13,bytes([0]));m.w(m.r[6]-480+36,0)
        c.callbacks[0x14B108]=bad_metadata
        # Force a null top-level allocation after the normal native initializer
        # rather than relying on unchecked internals to simulate resource OOM.
        c.callbacks[0x1AD7B8]=lambda m:m.r.__setitem__(2,0)
        c.run(fix.CODE);self.assertEqual(c.u(fix.CONTROL),120)
        self.assertEqual(c.read(c.allocator,156),before);self.assertEqual(c.u(fix.CONTROL+16),0)
        self.assertEqual(c.u(c.primary+8),2)

    def test_actual_model_bridges_preserve_arguments_and_native_fallback(self):
        for _,code,previous,field in fix.META_CALLS:
            c=machine();c.w(fix.CONTROL+16,1);c.w(fix.CONTROL+20,10);c.w(fix.CONTROL+24,0x04000000)
            c.r[4]=10;c.r[5]=3;c.w(0x04000000+field+(12 if field==156 else 0),0x05550000)
            before=c.r.copy();c.run(code);self.assertEqual(c.r[2],0x05550000)
            for i in range(32):
                if i!=2:self.assertEqual(c.r[i],before[i])
            c.w(fix.CONTROL+16,0);seen=[]
            c.callbacks[previous]=lambda m:seen.append((m.r[4],m.r[5]))
            c.run(code);self.assertEqual(seen,[(10,3)])

    def test_actual_native_metadata_parser_matches_own_character_for_model_permutations(self):
        ram=fixture();u=lambda p:struct.unpack_from('<I',ram,p)[0]
        for pid,mid in ((2,2),(3,3),(4,7),(5,10)):
            model=u(fix.core.MODELS+4*pid)
            for slot in range(5):
                outputs=[]
                for patched in (False,True):
                    c=machine();c.callbacks.pop(0x14B108);c.write(0x14B108,NATIVE(0x14B108,0x7D8))
                    for field in (2348,2352):
                        p=u(model+field);c.write(p,ram[p:p+0x1000])
                    c.callbacks[0x2A9ACC]=lambda m:m.write(m.r[4],bytes(m.r[6]))
                    c.callbacks[0x205330]=lambda m:m.r.__setitem__(2,m.u(model+2348))
                    c.callbacks[0x205370]=lambda m:m.r.__setitem__(2,m.u(model+2352))
                    if patched:
                        for hook,code,_,_ in fix.META_CALLS[1:]:c.w(hook,(3<<26)|(code>>2))
                        c.w(fix.CONTROL+16,1);c.w(fix.CONTROL+20,mid);c.w(fix.CONTROL+24,model)
                    c.r[4:8]=[mid if patched else pid,slot,0x04100000,0]
                    c.run(0x14B108);outputs.append(c.read(0x04100000,140))
                self.assertEqual(*outputs,(pid,mid,slot))

    def test_relocation_rejects_active_and_unaccounted_old_references(self):
        ram=fixture();u=lambda p:struct.unpack_from('<I',ram,p)[0]
        primary=u(fix.GLOBAL);old=u(primary+4);node=u(old+40);pool=u(node+36)
        for p,value in ((pool+4,0x01000000),(0x04000000,old)):
            broken=bytearray(ram);struct.pack_into('<I',broken,p,value)
            with self.assertRaises(ValueError):fix.build_memory(broken)

    def test_relocation_scan_boundaries_are_the_old_row_range_and_alignment(self):
        ram=fixture();u=lambda p:struct.unpack_from('<I',ram,p)[0]
        old=u(u(fix.GLOBAL)+4);expected=fix.build_memory(bytes(ram))['rebased_references']
        for value,refused in ((old+2684,True),(old+2688,False),(old-4,False),(old+2,False)):
            broken=bytearray(ram);struct.pack_into('<I',broken,0x04000000,value)
            with self.subTest(offset=value-old):
                if refused:
                    with self.assertRaisesRegex(ValueError,'Additional cached primary-row'):fix.build_memory(broken)
                else:self.assertEqual(fix.build_memory(broken)['rebased_references'],expected)

    def test_pointer_scan_is_exactly_the_three_mask_scan(self):
        import numpy as np
        base,span=0x01A00000,2688
        edge=[0,1,2,3,4,base-4,base-1,base,base+1,base+2,base+3,base+4,base+span-4,base+span-3,
              base+span-1,base+span,base+span+4,0x7FFFFFFC,0x80000000,0xFFFFF000,0xFFFFFFFC,0xFFFFFFFF]
        rng=np.random.default_rng(22)
        words=np.concatenate([np.array(edge,dtype='<u4'),
                              rng.integers(0,1<<32,200000,dtype=np.uint64).astype('<u4'),
                              (base-64+rng.integers(0,span+128,200000)).astype('<u4')])
        for b,s in ((base,span),(base,96),(base,0),(0,4),(0,span),(0xFFFFF000,0x1000)):
            got,want=fix.pointer_word_indices(words,b,s),three_mask_scan(words,b,s)
            self.assertTrue(np.array_equal(got,want) and got.dtype==want.dtype,(hex(b),s))
        for bad in ((words.astype('<i8'),base,span),(words,-4,span),(words,0xFFFFFFF0,0x20),(words,base,1<<32)):
            with self.assertRaises(ValueError):fix.pointer_word_indices(*bad)
        if not PREPARED.is_dir():return
        for name in ('00-original-selected-match.bin','14-ai-ready.bin'):
            ram=(PREPARED/name).read_bytes();words=np.frombuffer(ram,dtype='<u4')
            row=struct.unpack_from('<I',ram,struct.unpack_from('<I',ram,fix.GLOBAL)[0]+4)[0]
            for b in (row,0x01A00000,0x00100000):
                for s in (96,2688):
                    got=fix.pointer_word_indices(words,b,s)
                    self.assertTrue(np.array_equal(got,three_mask_scan(words,b,s)),(name,hex(b),s))

    def test_real_fresh169_rebases_inactive_typed_caches_and_empty_effect_parents(self):
        ram=read_ram(ROOT/'runtime128/sstates/SLUS-21678 (428113C2).169.p2s')
        manifest=fix.build_memory(ram);self.assertEqual(len(manifest['rebased_references']),22)
        blocks={b['address']:bytes.fromhex(b['data_hex']) for b in manifest['blocks']}
        self.assertEqual(struct.unpack('<I',blocks[0x197D9E4])[0],fix.ROWS+1344+160)
        self.assertEqual(struct.unpack('<I',blocks[0x1AB95E0])[0],fix.ROWS+1344+160)

    def test_actual_native_special_start_uses_each_own_row_and_effect_pool(self):
        c=machine()
        for p,n in ((0x14B9B0,0x170),(0x14B8E0,0x38),(0x14ABB0,0x28)):c.write(p,NATIVE(p,n))
        record=0x04010000;c.write(record,struct.pack('<3I4f',2,2,0,1,1,10,20));c.r[4]=record
        c.run(0x14B9B0);self.assertEqual(c.r[2],0,'Uninitialized extra row cannot follow neighboring native memory')
        c.run(fix.CODE);self.assertEqual(c.u(fix.CONTROL),5)
        starts=[];monitors=[]
        c.callbacks[0x14BC00]=lambda m:m.set_number(0,2)
        c.callbacks[0x158460]=lambda m:monitors.append(m.r[4])
        c.callbacks[0x1AD7B8]=lambda m:starts.append((m.r[4],m.r[5],m.r[6]))
        for mid in range(2,6):
            for slot in (2,3,4):
                row=fix.ROWS+1344*mid+80*slot;parent=c.u(row+40)
                c.write(record,struct.pack('<3I4f',mid,slot,0,1,1,10,20));c.r[4]=record
                c.run(0x14B9B0)
                self.assertEqual(starts[-1][0],c.u(parent+36));self.assertEqual(starts[-1][2],row)
                self.assertEqual(monitors[-1],row);self.assertEqual(c.u(row),mid)
                self.assertEqual(c.u(fix.ROWS+1344*mid+1328),slot)

    def test_native_free_restores_original_rows_and_disables_readiness(self):
        c=machine();c.w(fix.CONTROL,5);seen=[]
        c.callbacks[fix.FREE_TAIL]=lambda m:seen.append((m.u(c.primary+4),m.u(c.primary+8)))
        before=c.r.copy();c.run(fix.FREE)
        self.assertEqual(seen,[(c.manifest['old_rows'],2)])
        self.assertEqual(c.u(fix.CONTROL),90);self.assertEqual(c.r,before)
        c.run(fix.NOOP);self.assertEqual(c.r,before)


if __name__=='__main__':unittest.main()
