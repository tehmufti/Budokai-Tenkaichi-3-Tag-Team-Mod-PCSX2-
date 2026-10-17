"""Exercise dormant costume swap ownership and native refresh control flow.

Fixtures use a real held six-fighter checkpoint and real damaged character34
mesh/animation/combat files. Model decoding is mocked; native pool destruction,
allocator-free selection, replacement wrapper and actor cache code execute.
"""
import struct
import unittest

import extra_reload_commit as fix
import extra_reload_stage as stage
from prototype import ROOT,elf_reader
import test_extra_reload_stage as stage_tests
from test_extra_special_pools import Cpu as NativeCpu

NATIVE=elf_reader(ROOT/'analysis/SLUS_219.78')[2]
SOURCE=ROOT/'analysis/prepared-states/20260912-160547-f6726c66/17-playable-team.p2s'


class Cpu(NativeCpu):
    def __init__(self,ram,manifest):
        self.buffer=bytearray(ram)
        super().__init__({'segments':manifest['blocks']})
    def read(self,p,n):
        assert 0<=p<=len(self.buffer)-n,hex(p)
        return bytes(self.buffer[p:p+n])
    def write(self,p,d):
        assert 0<=p<=len(self.buffer)-len(d),hex(p)
        self.buffer[p:p+len(d)]=d
    def extra_instruction(self,ins,pc):
        if ins>>26==17 and (ins>>21)&31==20 and ins&63==32: # cvt.s.w
            source=(ins>>11)&31;dest=(ins>>6)&31
            self.set_number(dest,float(self.signed_word(self.f[source])));return None
        if ins>>26==17 and (ins>>21)&31==16 and ins&63==13: # trunc.w.s
            source=(ins>>11)&31;dest=(ins>>6)&31
            self.f[dest]=int(self.number(source))&0xFFFFFFFF;return None
        if ins>>26==0 and ins&63==26:
            left=self.signed_word(self.r[(ins>>21)&31]);right=self.signed_word(self.r[(ins>>16)&31])
            assert right
            quotient=abs(left)//abs(right)
            if (left<0)!=(right<0):quotient=-quotient
            self.lo=quotient&0xFFFFFFFF;self.hi=(left-quotient*right)&0xFFFFFFFF;return None
        return super().extra_instruction(ins,pc)


class CommitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        x=stage_tests.StageTests();x.base=stage_tests.fixture(character=34,source=SOURCE);x.manifest=stage.build_memory(x.base)
        c,*_=x.machine();c.run(stage.ENTRY);row=x.manifest['resource']
        c.w(row['geometry']+40,14);c.w(row['geometry']+12,c.u(row['geometry']+12)|0x80000000)
        # A real native model parses these resource fields. The staging test's
        # bounded model callback omitted them; copy the actual source metadata
        # only for the same-character fixture, then rebase into the new files.
        cls.base=bytes(c.buffer);cls.manifest=fix.build_memory(cls.base)

    def machine(self,wrong_dataset=False):
        c=Cpu(self.base,self.manifest);cfg=self.manifest['configuration'];w=cfg['world'];row=cfg['resource']
        calls=[];c.w(fix.CONTROL,1)
        before_model=c.read(w['model'],0x1670)
        def free_model(m):
            calls.append(('free_model',m.r[4]));self.assertEqual(m.r[4],w['model'])
            m.write(m.r[4],bytes(0x1670))
        c.callbacks[0x1135F0]=free_model
        c.callbacks[0x249000]=lambda m:calls.append(('retain_texture',m.r[4]))
        c.callbacks[0x24B910]=lambda m:m.r.__setitem__(2,row['resource'])
        c.callbacks[0x2499B0]=lambda m:m.r.__setitem__(2,m.u(stage.prior.core.MODELS+4*m.r[4]))
        def model_init(m):
            kind,model,resource=m.r[4:7]
            self.assertEqual((kind,model,resource),(0,w['model'],row['resource']))
            # Native249A28 calls this before writing ID/enable/character.
            m.write(model,before_model)
            m.w(model+20,resource);m.w(model+64,row['geometry'])
            m.w(model+2356,m.u(cfg['staged_model']+2356))
            m.w(model+84,row['collision']);m.w(row['collision']+28,0xABCD0123)
            for i in range(3):m.w(model+164+4*i,0)
            calls.append(('init_model',model))
        c.callbacks[0x113598]=model_init
        c.callbacks[0x2499C8]=lambda m:m.r.__setitem__(2,cfg['old_scratch'])
        c.callbacks[0x24E5A0]=lambda m:None
        c.callbacks[0x250CD0]=lambda m:None
        def collision(m):
            self.assertEqual(m.u(row['collision']+28),struct.unpack_from('<I',self.base,row['collision']+28)[0])
            self.assertEqual(m.u(m.r[4]+84),cfg['new_collision'])
            m.w(cfg['new_collision']+28,w['model']+0x100)
        c.callbacks[0x24DB28]=collision
        # Native actor cache and refresh suffix execute. Heavy rendering/flag
        # helpers are boundaries, not alternate HP/ki calculations.
        c.callbacks[0x1DC280]=lambda m:m.r.__setitem__(2,m.u(stage.prior.core.MODELS+4*m.u(m.r[4]+12)))
        for fn in (0x1DAA50,0x1DAAF0,0x1C31D0,0x1DABE8,0x1C42A8,0x24C958,0x1D7198,
                   0x24E3F8,0x1C3E60,0x24CC88,0x24FE78):c.callbacks[fn]=lambda m:None
        c.callbacks[0x2A9ACC]=lambda m:m.write(m.r[4],bytes(m.r[6]))
        c.callbacks[0x1E0358]=lambda m:m.r.__setitem__(2,m.u(m.r[4]+0x948))
        c.callbacks[0x20E480]=lambda m:m.r.__setitem__(2,0)
        c.callbacks[0x1CE1B8]=lambda m:m.r.__setitem__(2,fix.AI_META+0xC0)
        # Actual1ADA80→1AD6A8→1A71B8 must not free private arena interiors.
        c.callbacks[0x255508]=lambda m:self.fail('Heap free called on private effect arena')
        # The many typed child destructors run at their native boundaries;
        # preserve their allocation ownership while skipping audiovisual work.
        root=cfg['root'];child=c.u(root+36)
        if child:
            # Existing idle root has sub-pool children. Native callbacks can
            # own more nested pools; run the full generic destruction tree,
            # with only family-specific destructors suppressed.
            pending=[child];seen=set()
            while pending:
                pool=pending.pop();node=c.u(pool+4)
                while node:
                    self.assertNotIn(node,seen);seen.add(node)
                    callbacks=c.u(node+40);destroy=c.u(callbacks+8)
                    if destroy:c.callbacks[destroy]=lambda m:None
                    if c.u(node+36):pending.append(c.u(node+36))
                    node=c.u(node+48)
        def create_root(m):
            self.assertEqual((m.r[4],m.r[5],m.r[6]),(cfg['rootpool'],fix.effects.CALLBACKS,cfg['record']+4))
            self.assertEqual(m.u(cfg['allocator']+148),5)
            self.assertEqual((m.u(cfg['allocator']+80),m.u(cfg['allocator']+84)),(cfg['arena'],cfg['arena']))
            self.assertEqual(m.u(fix.effects.CONTROL+16),1)
            self.assertEqual(m.u(fix.effects.CONTROL+24),w['model'])
            # Allocation bookkeeping and typed-row binding is native in the
            # separate special-pools test suite; here assert its call contract.
            m.w(cfg['allocator']+92,0x18000)
            for i in range(5):m.w(cfg['effect_row']+i*80+28,m.u(w['model']+156+i*4))
            m.r[2]=root;calls.append(('effects',w['model_id']))
        c.callbacks[0x1AD7B8]=create_root
        c.callbacks[0x1BB510]=lambda m:None
        def init_ai(m):
            role=w['physical']&1;shadow=fix.fresh.SHADOWS[w['physical']]
            self.assertEqual(m.u(fix.AI_GLOBAL),shadow)
            self.assertEqual(m.u(fix.pair.CONTROL+4),1)
            self.assertEqual(m.u(w['actor']),role)
            self.assertEqual(m.r[4:6],[role,0])
            own=shadow+0x10+role*0x520
            m.w(own,role);m.w(own+24,0 if wrong_dataset else m.u(w['model']+2356))
            m.w(own+36,0);calls.append(('ai',w['physical']))
        c.callbacks[0x1BAF68]=init_ai
        return c,calls

    def test_native_cache_and_idle_refresh_preserve_health_while_model_id_stays_stable(self):
        c,calls=self.machine();cfg=self.manifest['configuration'];w=cfg['world']
        before=c.read(cfg['selected_row']+8,88);allocator=c.read(cfg['allocator'],156)
        others=[(p,c.read(p,0x1600)) for p in w['actors'] if p!=w['actor']]
        others += [(p,c.read(p,0x1670)) for p in w['models'] if p!=w['model']]
        kernel=c.read(0,0x1000);c.run(fix.ENTRY)
        self.assertEqual(c.u(fix.CONTROL+4),5);self.assertEqual(c.u(fix.AI_META),5)
        self.assertEqual((c.u(w['actor']+12),c.u(w['model']+16)),(w['model_id'],w['model_id']))
        self.assertEqual(c.u(w['model']+20),cfg['resource']['resource'])
        self.assertEqual(c.u(w['model']+8),1);self.assertEqual(c.u(cfg['staged_model']+8),0)
        self.assertEqual(c.u(cfg['selected_row']+96),1)
        self.assertEqual(c.read(cfg['selected_row']+8,88),before)
        self.assertEqual(c.read(cfg['allocator'],156),allocator)
        self.assertEqual(c.read(0,0x1000),kernel)
        for p,data in others:self.assertEqual(c.read(p,len(data)),data,hex(p))
        self.assertEqual(c.u(w['model']+2356),c.u(fix.fresh.DESCRIPTORS[w['physical']]+40))
        self.assertEqual(c.u(fix.pair.CONTROL+4),0)
        self.assertEqual([c.u(p) for p in w['actors']],list(range(w['count'])))
        self.assertIn(('retain_texture',cfg['old_group']),calls)

    def test_an_unshared_old_texture_group_is_returned_and_a_shared_one_kept(self):
        """TTM-MATCH-21 fusion freeze: every first transformation kept its old body's group
        reserved, so a 5v5 match ran out of groups. Only a group another live model draws
        from (a resident copy of the same bundle) stays reserved after the destructor."""
        if type(self) is not CommitTests:self.skipTest('the shared-bundle fixture belongs to the base commit case')
        cfg=self.manifest['configuration'];w=cfg['world'];old=cfg['old_group']
        self.assertTrue(cfg['return_unshared_group'])
        c,calls=self.machine()
        sharers=[]
        for mid in range(12):
            model=c.u(stage.prior.core.MODELS+4*mid)
            if model in (0,w['model']) or c.u(model+4)!=1:continue
            geometry=c.u(model+64)
            if c.u(geometry+40)==old:sharers.append(geometry)
        self.assertTrue(sharers,'the fixture shares the leader bundle')
        for geometry in sharers:c.w(geometry+40,13 if old!=13 else 12)
        c.run(fix.ENTRY);self.assertEqual(c.u(fix.CONTROL+4),5)
        self.assertNotIn(('retain_texture',old),calls)
        c,calls=self.machine();c.run(fix.ENTRY);self.assertEqual(c.u(fix.CONTROL+4),5)
        self.assertIn(('retain_texture',old),calls)
        # Body Change and defusion re-emit this payload from their own receipts: unchanged.
        self.assertEqual(fix.payload(dict(cfg,return_unshared_group=False)).count(struct.pack('<I',0x0C000000|(fix.A(0x249000)>>2))),
                         fix.payload(dict(cfg)).count(struct.pack('<I',0x0C000000|(fix.A(0x249000)>>2))))

    def test_runtime_owner_change_fails_before_any_destructor_or_model_rebind(self):
        c,calls=self.machine();cfg=self.manifest['configuration']
        c.w(cfg['world']['actor']+0x1278,1);before=c.read(cfg['world']['model'],0x1670)
        c.run(fix.ENTRY);self.assertEqual(c.u(fix.CONTROL+4),110)
        self.assertFalse(calls);self.assertEqual(c.read(cfg['world']['model'],0x1670),before)

    def test_private_ai_failure_restores_aliases_and_keeps_replacement_hidden(self):
        c,_=self.machine(wrong_dataset=True);cfg=self.manifest['configuration'];c.run(fix.ENTRY)
        self.assertEqual(c.u(fix.CONTROL+4),150);self.assertEqual(c.u(fix.AI_META),203)
        self.assertEqual(c.u(cfg['world']['model']+8),0)
        self.assertEqual(c.u(fix.pair.CONTROL+4),0)
        self.assertEqual([c.u(p) for p in cfg['world']['actors']],list(range(6)))

    def test_wrong_character_unready_pools_or_heap_selector_cannot_install(self):
        cfg=self.manifest['configuration']
        for p,value,message in ((cfg['world']['model']+12,13,'same-character'),
                                (fix.effects.CONTROL,0,'must be ready'),
                                (cfg['allocator']+152,0,'bounded arena')):
            ram=bytearray(self.base);struct.pack_into('<I',ram,p,value)
            with self.assertRaisesRegex(ValueError,message):fix.build_memory(ram)


if __name__=='__main__':unittest.main()
