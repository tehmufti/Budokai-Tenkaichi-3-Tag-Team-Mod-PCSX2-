"""Director executes every new finisher phase, using actual role bodies."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import math
import struct
import unittest
import tag_team_rush as tag
import tag_rush_scene as scene
import tag_rush_assets as assets
import tag_rush_choreography as choreography
import tag_rush_staging as staging
import tag_rush_safety as safety
import tag_rush_effects as effects
import tag_rush_special_pair as special
import tag_rush_authored_hold as authored
from test_tag_rush_scene import fixture,start
from test_tag_rush_camera import run


def machine(variant):
    names=choreography.VARIANTS
    ki=((True,True),(False,False),(True,False),(False,True),(True,True))[variant]
    c=fixture(ki=ki);tables={}
    if variant==4:
        c.w(c.models[2]+12,22);c.write(c.u(scene.ADMISSION)+22,bytes([3]))
        # This variant applies the real authored helper from its first tick.
        # The ordinary director fixture only needs six world markers, so give
        # the held actors the full, valid local rig required by that helper.
        for index in (0,1):
            model=c.models[index]
            for bone in (0,*authored.JOINTS):
                node=0x3B00000+index*0x10000+bone*0x100
                c.w(model+3436+bone*4,node)
                for column,values in enumerate(((1.,0.,0.),(0.,1.,0.),(0.,0.,1.))):
                    c.write(node+16+16*column,struct.pack('<4f',*values,0.))
                c.write(node+160,struct.pack('<4f',0.,0.,0.,1.))
            c.fw(c.u(model+3436+19*4)+144,-2.1538)
            c.fw(c.u(model+3436+33*4)+144,2.1538)
    cursor=0x3110000
    for index,name in enumerate(names):
        phases=assets.timeline(name);base=0x06D14000+index*0x800
        table=tag.CONTROL+special.TABLE_OFFSET if name==special.NAME else scene.TABLE+8*index
        c.w(table,base);c.w(table+4,len(phases));tables[name]=phases
        for phase,p in enumerate(phases):
            roles=[0x06D20000,0x06D21000,0x06D22000]
            if p.roles[1]is None:roles[1]=0
            c.write(base+phase*64,struct.pack('<16I',p.source_frames,*roles,0,0,0,p.flags,
                    352+phase,414+phase,357+phase,*p.ends,60,0x06D25000))
            c.write(cursor,struct.pack('<4f',0,-160 if phase<4 and name!=special.NAME else 0,0,0));cursor+=16
    data,info=choreography.pack_records(tables,0x06D30000)
    c.write(0x06D30000,data);c.w(tag.CONTROL+staging.TABLE_OFFSET,info['table_address'])
    # FLOOR is only a buried-root correction; airborne placement uses QUERY.
    c.callbacks[safety.FLOOR]=lambda m:m.r.__setitem__(2,0)
    def ground(m):m.set_number(0,0.);m.r[2]=1
    c.callbacks[safety.QUERY]=ground
    c.callbacks[scene.A(0x11F588)]=lambda m:m.set_number(0,math.sin(m.number(12)))
    c.callbacks[scene.A(0x11F620)]=lambda m:m.set_number(0,math.cos(m.number(12)))
    # Native matrix/shots math has its separate emitted tests; this fixture
    # exercises complete director/placement clocks and the fallback framing.
    c.callbacks[scene.shots.UPDATE]=lambda m:m.r.__setitem__(2,0)
    # Charge and ignition now keep one native emitter alive through the beam
    # pose. Their ownership/pool behavior is covered by the effects tests;
    # this complete-director fixture records both lifecycle boundaries.
    c.charges=[]
    def charge(m):
        m.charges.append((m.r[4],m.u(scene.STATE+scene.S['phase']),m.u(scene.STATE+scene.S['ticks'])))
        m.r[2]=1
    def ignite(m):
        role=(m.r[4]-effects.ROWS)//effects.STRIDE
        assert role in (0,1)
        m.beams.append((role,0));m.r[2]=1
    c.callbacks[effects.CHARGE_SPAWN]=charge
    c.callbacks[effects.IGNITE]=ignite
    return c


class EndingTests(unittest.TestCase):
    def test_all_new_endings_run_their_full_phases_and_expected_beam_roles(self):
        for variant,roles in enumerate(((0,1),(),(0,),(1,),(1,))):
            c=machine(variant);start(c);self.assertEqual(c.r[2],1)
            phase_count=(6,9,8,8,5)[variant]
            self.assertEqual(c.u(scene.STATE+scene.S['count']),phase_count)
            seen=set();fire=[];old=0
            for _ in range(650):
                phase=c.u(scene.STATE+scene.S['phase']);seen.add(phase)
                run(c,scene.STEP)
                if len(c.beams)>old:
                    fire.append((phase,c.u(scene.STATE+scene.S['ticks'])));old=len(c.beams)
                if not c.u(tag.CONTROL+tag.C['active']):break
            self.assertEqual(c.u(tag.CONTROL+tag.C['completed']),1,variant)
            self.assertEqual(c.u(tag.CONTROL+tag.C['cancelled']),0,variant)
            self.assertEqual([r for r,_ in c.beams],list(roles),variant)
            phase=phase_count-1
            self.assertEqual(c.charges,[(role,phase,1) for role in roles])
            if roles:self.assertEqual(fire,[(phase,math.ceil(choreography.BEAM_START*scene.ACTOR_HZ/60))])
            self.assertEqual(c.explosions,[(2,17,phase,math.ceil(choreography.BEAM_BURST*scene.ACTOR_HZ/60))] if roles else [])
            self.assertEqual(len(c.damage),1);self.assertEqual(c.damage[0][1],15000)
            self.assertEqual({actor for actor,_ in c.placements},{c.actors[i]for i in (0,2,1)})
            self.assertTrue(all(c.u(scene.ROWS+i*scene.STRIDE+scene.R['recovering'])==0 for i in range(3)))
            self.assertTrue(set(range(phase_count))<=seen)
            self.assertEqual(c.u(c.actors[1]+2376),217)

    def test_missing_custom_placement_cancels_without_finisher(self):
        c=machine(0);start(c)
        c.w(scene.STATE+scene.S['phase'],4);c.w(tag.CONTROL+staging.TABLE_OFFSET,0)
        run(c,scene.STEP)
        self.assertEqual(c.damage,[]);self.assertEqual(c.u(tag.CONTROL+tag.C['active']),0)


if __name__=='__main__':unittest.main()
