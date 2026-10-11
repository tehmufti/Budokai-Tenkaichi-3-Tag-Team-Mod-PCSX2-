"""Execute the emitted receipt, health and attributed-damage helpers."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import struct
import unittest
from unittest.mock import patch
import fusion_buffs as f
from test_fusion_partner_lifecycle import machine, FusionCpu


class BuffCpu(FusionCpu):
    def extra_instruction(self,ins,pc):
        op,fn=ins>>26,ins&63
        rs,rt,rd=(ins>>21)&31,(ins>>16)&31,(ins>>11)&31
        if op==0 and fn==6:
            self.r[rd]=(self.r[rt]&0xFFFFFFFF)>>(self.r[rs]&31);return None
        if op==0 and fn==25:
            value=(self.r[rs]&0xFFFFFFFF)*(self.r[rt]&0xFFFFFFFF)
            self.lo=value&0xFFFFFFFF;self.hi=value>>32;return None
        return super().extra_instruction(ins,pc)


def setup(**settings):
    with patch('test_fusion_partner_lifecycle.FusionCpu',BuffCpu):c=machine()
    for p,b in f.pieces():c.write(p,b)
    c.write(f.CONTROL,struct.pack('<4I',f.MAGIC,c.manager,6,f.VERSION)+f.config(settings))
    return c


def enable(kind='non_potara',health=2,damage=2,defense=2):
    p='fusion_'+kind
    return {p+'_buffs_enabled':True,p+'_health_multiplier':health,
            p+'_damage_multiplier':damage,p+'_defense_multiplier':defense}


def activate(c,physical=0,partner=2,kind=241):
    c.w(f.part.CONSUMED,c.u(f.part.CONSUMED)|(1<<partner))
    c.r[4:7]=[c.actors[physical],kind,partner];c.run(f.ACTIVATE)


def row(c,i=0):return c.actors[i]+0x9A4+164*c.u(c.actors[i]+0x994)


def damage(c,victim,attacker,amount,flags=0):
    frame=0x1600000;c.w(frame+0xF0,victim);c.w(frame+0xF4,attacker)
    c.w(frame+f.feed.REG_OFFSET[5],amount);c.w(frame+f.feed.REG_OFFSET[6],flags)
    c.r[4]=frame;c.run(f.DAMAGE)
    return c.u(frame+f.feed.REG_OFFSET[5]),c.u(frame+f.feed.REG_OFFSET[6])


class FusionBuffTests(unittest.TestCase):
    def test_disabled_or_neutral_settings_install_nothing(self):
        for settings in ({},enable(health=1,damage=1,defense=1),
                         {'fusion_potara_buffs_enabled':False,'fusion_potara_health_multiplier':5}):
            self.assertEqual(f.build_memory(b'',settings)['blocks'],[])

    def test_native_successful_commit_applies_once_after_actual_merge(self):
        c=setup(**enable());c.w(c.source+2376,241)
        native_hp=c.u(row(c)+64)+c.u(row(c,2)+64)
        c.r[4]=c.source;c.run(f.fusion.COMMIT)
        self.assertEqual(c.u(row(c)+64),2*native_hp)
        self.assertEqual(c.u(f.ROWS),1)
        before=c.read(c.source,0x1600)
        for _ in range(5):c.run(f.TICK)
        activate(c)
        self.assertEqual(c.read(c.source,0x1600),before)

    def test_independent_types_and_preselected_fusion_no_receipt(self):
        c=setup(**(enable(health=2)|enable('potara',health=3)))
        c.w(row(c),48);c.run(f.TICK)
        self.assertEqual(c.u(row(c)+68),30000)
        activate(c);activate(c,1,3,242)
        self.assertEqual(c.u(row(c)+68),60000)
        self.assertEqual(c.u(row(c,1)+68),90000)
        self.assertEqual(c.u(row(c,4)+68),30000)

    def test_disabled_type_and_unsuccessful_invalid_or_nonfusion_never_apply(self):
        for kind in (240,242,243):
            c=setup(**enable());before=c.read(c.source,0x1600);activate(c,kind=kind)
            self.assertEqual(c.read(c.source,0x1600),before)
            self.assertEqual(c.u(f.ROWS),0)
        c=setup(**enable());c.r[4:7]=[c.source,241,2];c.run(f.ACTIVATE)
        self.assertEqual(c.u(f.ROWS),0)

    def test_partial_health_large_ratio_and_cap_are_exact_without_overflow(self):
        for hp,maximum,factor in ((25000,50000,5),(199999,200000,5),
                                 (400001,500000,5),(1,30000,.25),(12345,77777,2.75)):
            with self.subTest(hp=hp,maximum=maximum,factor=factor):
                c=setup(**enable(health=factor));c.w(row(c)+64,hp);c.w(row(c)+68,maximum)
                activate(c);boosted=min(1000000,maximum*round(factor*1000)//1000)
                self.assertEqual(c.u(row(c)+68),boosted)
                self.assertEqual(c.u(row(c)+64),max(1,hp*boosted//maximum))
                c.w(f.part.CONSUMED,0);c.run(f.TICK)
                self.assertEqual(c.u(row(c)+68),maximum)
                self.assertEqual(c.u(row(c)+64),max(1,max(1,hp*boosted//maximum)*maximum//boosted))

    def test_damage_defense_unknown_attacker_cost_flags_and_floors(self):
        c=setup(**(enable(damage=3,defense=2)|enable('potara',damage=2,defense=4)))
        activate(c);activate(c,1,3,242)
        self.assertEqual(damage(c,1,0,1000),(750,0))
        self.assertEqual(damage(c,0,1,1000),(1000,0))
        self.assertEqual(damage(c,0,0xFFFFFFFF,1000),(500,0))
        self.assertEqual(damage(c,1,0,1),(1,0))
        self.assertEqual(damage(c,1,0,1000,0x2000400),(750,0x2000400))
        self.assertEqual(damage(c,1,0,1000,1),(1000,1))
        self.assertEqual(damage(c,0,0,1000),(1000,0))
        self.assertEqual(damage(c,1,0,0),(0,0))

    def test_forms_carry_receipt_and_scale_fresh_native_rows_once(self):
        c=setup(**enable());activate(c);base=row(c)
        c.w(base,49);c.run(f.TICK)  # native form kept its existing modified health
        self.assertEqual(c.u(base+68),60000)
        c.w(c.source+0x994,1);other=row(c)
        for off,value in ((0,50),(64,9000),(68,40000)):c.w(other+off,value)
        c.run(f.TICK);c.run(f.TICK)
        self.assertEqual((c.u(other+64),c.u(other+68)),(18000,80000))
        c.w(c.source+0x994,0);c.run(f.TICK)
        self.assertEqual(c.u(base+68),60000)
        c.w(f.part.CONSUMED,0);c.run(f.TICK)
        self.assertEqual(c.u(base+68),30000);self.assertEqual(c.u(other+68),40000)

    def test_native_defusion_replacement_rows_are_never_overwritten(self):
        c=setup(**enable());activate(c)
        for off,value in ((0,3),(64,7777),(68,30000)):c.w(row(c)+off,value)
        c.w(f.part.CONSUMED,0);c.run(f.TICK)
        self.assertEqual((c.u(row(c)+64),c.u(row(c)+68)),(7777,30000))
        self.assertEqual(c.u(f.ROWS),0)

    def test_body_change_only_clears_the_receipt_of_an_involved_actor(self):
        for involved in (False,True):
            c=setup(**enable());activate(c)
            for p,v in ((f.body.CONTROL,f.body.MAGIC),(f.body.CONTROL+4,c.manager),
                        (f.body.FINISHED,1),(f.body.ROWS+4,c.source if involved else c.actors[1])):c.w(p,v)
            c.run(f.TICK)
            self.assertEqual(c.u(f.ROWS),int(not involved))
            self.assertEqual(c.u(row(c)+68),30000 if involved else 60000)

    def test_dead_fusion_is_not_resurrected_during_cleanup(self):
        c=setup(**enable());activate(c);c.w(row(c)+64,0)
        c.w(f.part.CONSUMED,0);c.run(f.TICK)
        self.assertEqual(c.u(row(c)+64),0);self.assertEqual(c.u(row(c)+68),30000)

    def test_stale_match_or_pointer_receipts_cannot_touch_other_fighters(self):
        for change in ('manager','count','actor','partner'):
            c=setup(**enable());activate(c);before=c.read(c.source,0x1600)
            if change=='manager':c.w(f.CONTROL+4,c.manager+4)
            elif change=='count':c.w(f.CONTROL+8,4)
            elif change=='actor':c.w(f.core.POINTERS,c.actors[4])
            else:c.w(f.core.POINTERS+8,c.actors[4])
            c.run(f.TICK)
            if change=='partner':self.assertEqual(c.u(row(c)+68),30000)
            else:self.assertEqual(c.read(c.source,0x1600),before)
            self.assertEqual(damage(c,1,0,1000),(1000,0))

    def test_register_fpu_hilo_preserved_and_actor_allocation_bounded(self):
        c=setup(**enable(health=5));activate(c);saved=c.r.copy();c.hi=321;c.lo=654
        c.run(f.TICK)
        self.assertEqual(c.r,saved);self.assertEqual((c.hi,c.lo),(321,654))
        parts=f.pieces();self.assertTrue(all(f.BASE<=p<p+len(d)<=f.CONTROL for p,d in parts))
        self.assertLess(f.ROWS+12*f.STRIDE,f.END)

    def test_full_killfeed_chain_scales_before_one_attributed_native_damage(self):
        c=setup(**enable(damage=3));activate(c)
        for p,b in ((f.feed.GATE,f.feed.gate_code()),(f.feed.IDENTIFY,f.feed.identify_code()),
                    (f.feed.ROW,f.feed.row_code()),(f.feed.DAMAGE,f.feed.damage_code())):c.write(p,b)
        for off,v in ((0,1),(4,c.manager),(8,6)):c.w(f.feed.CONTROL+off,v)
        calls=[];kills=[]
        def native(m):
            calls.append((m.r[4],m.r[5],m.r[6]));p=row(c,1)
            m.w(p+64,max(0,m.u(p+64)-m.r[5]))
        c.callbacks[f.feed.DAMAGE_NATIVE]=native
        c.callbacks[f.feed.RECORD]=lambda m:kills.append((m.r[4],m.r[5]))
        caller,attacker_register=next(iter(f.feed.ATTRIBUTION.items()))
        c.w(row(c,1)+64,2500);c.r[4:7]=[c.actors[1],1000,0x2000000]
        c.r[attacker_register]=c.source;c.r[31]=caller;c.run(f.feed.DAMAGE,stops=(caller,))
        self.assertEqual(calls,[(c.actors[1],3000,0x2000000)])
        self.assertEqual(kills,[(1,0)])

    def test_installer_checks_identity_code_and_zero_arena_and_repeat(self):
        ram=bytearray(0x8000000);w=lambda p,v:struct.pack_into('<I',ram,p,v)
        manager=0x1800000
        for p,v in ((f.core.ACTORS,manager),(f.core.MODE,1),(f.core.MODE+4,6),
                    (f.core.MODE+8,manager),(f.core.MODE+12,6),(f.fusion.CONTROL,1),
                    (f.fusion.CONTROL+4,manager),(f.fusion.CONTROL+8,6)):w(p,v)
        for p,data in ((f.fusion.COMMIT,f.fusion.commit_code(True)),
                       (f.fusion.EXTRA_COMMIT,f.fusion.commit_code(True,True)),
                       (f.feed.TICK,f.feed.tick_code()),(f.feed.DAMAGE,f.feed.damage_code())):
            ram[p:p+len(data)]=data
        with f.policy.building_for(f.policy.TEAM_CAPACITY):
            w(f.BASE,1)
            with self.assertRaisesRegex(ValueError,'reservation occupied'):f.build_memory(ram,enable())
            w(f.BASE,0);manifest=f.build_memory(ram,enable())
            for block in manifest['blocks']:
                p=block['address'];b=bytes.fromhex(block['data_hex']);ram[p:p+len(b)]=b
            self.assertEqual(f.build_memory(ram,enable())['blocks'],[])
            ram[f.HEALTH]^=1
            with self.assertRaisesRegex(ValueError,'program changed'):f.build_memory(ram,enable())

    def test_timed_defusion_health_pool_removes_only_owned_multiplier(self):
        c=setup(**enable(health=5));activate(c)
        ram=bytearray(0x8000000)
        for p,size in ((f.CONTROL,48),(f.ROWS,12*f.STRIDE),(f.core.ACTORS,4),
                       (f.core.MODE,16),(f.core.POINTERS,24),(c.source,0x1600)):
            ram[p:p+size]=c.read(p,size)
        current=c.u(row(c)+64)
        self.assertEqual(f.unscaled_health(ram,c.source,current),10000)
        self.assertEqual(f.unscaled_health(ram,c.source,1),1)
        self.assertEqual(f.unscaled_health(ram,c.source,0),0)
        struct.pack_into('<I',ram,row(c)+68,12345)
        self.assertEqual(f.unscaled_health(ram,c.source,current),current)


if __name__=='__main__':unittest.main()
