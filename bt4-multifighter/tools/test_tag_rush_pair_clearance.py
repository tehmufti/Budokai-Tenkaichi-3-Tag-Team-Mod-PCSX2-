"""Bodies never intersect in the paired-beam scenes (dash-in, charge, beams).

Guest guard arithmetic is executed on the CPU model; the authored scenes are
evaluated per actor tick on real disc skeletons (imported meshes included).
"""
import math
import struct
import unittest

import numpy as np

import tag_rush_blue_native as blue
import tag_rush_scene as scene


def guard_cpu(points,roots,yaw=0.):
    """Three bodies of synthetic bone points; ROOT_STEP re-poses with SEP."""
    from test_tag_rush_scene import SceneCpu
    c=SceneCpu({'segments':[dict(address=a,data_hex=b.hex()) for a,b in blue.pieces()]})
    c.write(scene.STATE+scene.S['rotation'],struct.pack('<4f',0.,yaw,0.,0.))
    c.callbacks[scene.A(0x11F588)]=lambda m:m.set_number(0,math.sin(m.number(12)))
    c.callbacks[scene.A(0x11F620)]=lambda m:m.set_number(0,math.cos(m.number(12)))
    models=[]
    for role in range(3):
        row=scene.ROWS+role*scene.STRIDE;model=0x3000000+role*0x10000;models.append(model)
        c.w(row+scene.R['model'],model);c.fw(model+2592,1.)
        for bone,_ in blue.BODY:c.w(model+3436+4*bone,model+0x4000+bone*0x80)
    def pose(role):
        row=scene.ROWS+role*scene.STRIDE;model=models[role]
        sep=np.array(struct.unpack('<3f',c.read(row+blue.SEP,12)))
        c.write(model+2384,struct.pack('<4f',*(np.asarray(roots[role])+sep),1.))
        for bone,_ in blue.BODY:
            c.write(c.u(model+3436+4*bone)+64,struct.pack('<3f',*(np.asarray(points[role][bone])+sep)))
    def root_step(m):
        role=m.r[4];assert m.r[5]==scene.ROWS+role*scene.STRIDE;pose(role);m.r[2]=1;c.reposed.append(role)
    c.reposed=[];c.callbacks[blue.ROOT_STEP]=root_step
    c.pose=pose
    for role in range(3):pose(role)
    return c


def sep(c,role):
    return np.array(struct.unpack('<3f',c.read(scene.ROWS+role*scene.STRIDE+blue.SEP,12)))


def body(center):
    x,y,z=center
    return {bone:(x+(bone%3-1)*.4,y-bone*.2,z) for bone,_ in blue.BODY}


class GuardTests(unittest.TestCase):
    def run_guard(self,c):
        from test_tag_rush_camera import run
        run(c,blue.SEPARATE);self.assertEqual(c.r[2],1)

    def worst(self,c):
        import tag_rush_pair_clearance as clearance
        bodies=[]
        for role in range(3):
            model=0x3000000+role*0x10000
            bodies.append([(np.array(struct.unpack('<3f',c.read(c.u(model+3436+4*bone)+64,12))),radius)
                           for bone,radius in blue.BODY])
        return max(clearance.penetration(bodies[a],bodies[b]) for a,b in ((0,1),(0,2),(1,2)))

    def test_overlapping_attackers_share_the_push_and_the_victim_never_moves(self):
        c=guard_cpu([body((0,0,0)),body((2.,0,.5)),body((0,0,200.))],[(0,0,0),(2.,0,.5),(0,0,200.)])
        self.assertGreater(self.worst(c),3.)
        self.run_guard(c)
        self.assertLessEqual(self.worst(c),1e-3)
        np.testing.assert_allclose(sep(c,0),-sep(c,1),atol=1e-5)
        self.assertEqual(sep(c,2).tolist(),[0.,0.,0.])
        self.assertLess(sep(c,0)[0],0.);self.assertEqual(sep(c,0)[1],0.)
        self.assertIn(0,c.reposed);self.assertIn(1,c.reposed)

    def test_attacker_backs_off_the_victim_alone(self):
        c=guard_cpu([body((0,0,0)),body((60.,0,0)),body((0,0,3.))],[(0,0,0),(60.,0,0),(0,0,3.)])
        self.run_guard(c)
        self.assertLessEqual(self.worst(c),1e-3)
        self.assertLess(sep(c,0)[2],0.);self.assertEqual(sep(c,1).tolist(),[0.,0.,0.])
        self.assertEqual(sep(c,2).tolist(),[0.,0.,0.])

    def test_coincident_roots_split_along_the_scene_side_axis(self):
        yaw=.6
        c=guard_cpu([body((0,0,0)),body((0,0,0)),body((0,0,300.))],[(0,0,0),(0,0,0),(0,0,300.)],yaw)
        self.run_guard(c)
        direction=sep(c,0)/np.linalg.norm(sep(c,0))
        np.testing.assert_allclose(direction,(math.cos(yaw),0.,-math.sin(yaw)),atol=1e-4)

    def test_clear_bodies_decay_slowly_and_stay_bounded(self):
        c=guard_cpu([body((0,0,0)),body((40.,0,0)),body((0,0,300.))],[(0,0,0),(40.,0,0),(0,0,300.)])
        c.write(scene.ROWS+blue.SEP,struct.pack('<3f',3.,0.,0.))
        c.write(scene.ROWS+scene.STRIDE+blue.SEP,struct.pack('<3f',99.,0.,-99.))
        self.run_guard(c)
        self.assertAlmostEqual(sep(c,0)[0],3.*blue.SEPARATION_DECAY,places=5)
        self.assertAlmostEqual(sep(c,1)[0],blue.SEPARATION_LIMIT*blue.SEPARATION_DECAY,places=4)
        self.assertAlmostEqual(sep(c,1)[2],-blue.SEPARATION_LIMIT*blue.SEPARATION_DECAY,places=4)
        self.assertEqual(c.reposed,[])

    def test_a_bone_the_rig_lacks_is_skipped_but_a_bad_matrix_cancels(self):
        from test_tag_rush_camera import run
        c=guard_cpu([body((0,0,0)),body((2.,0,0)),body((0,0,300.))],[(0,0,0),(2.,0,0),(0,0,300.)])
        c.w(0x3000000+3436+4*17,0);run(c,blue.SEPARATE);self.assertEqual(c.r[2],1)
        self.assertLessEqual(self.worst_without(c,17),1e-3)
        c.w(0x3000000+3436+4*47,0x3000002);run(c,blue.SEPARATE);self.assertEqual(c.r[2],0)

    def worst_without(self,c,missing):
        import tag_rush_pair_clearance as clearance
        bodies=[]
        for role in range(3):
            model=0x3000000+role*0x10000
            bodies.append([(np.array(struct.unpack('<3f',c.read(c.u(model+3436+4*bone)+64,12))),radius)
                           for bone,radius in blue.BODY if c.u(model+3436+4*bone)])
        return max(clearance.penetration(bodies[a],bodies[b]) for a,b in ((0,1),(0,2),(1,2)))


def disc():
    import bt4_disc
    from pathlib import Path
    return bt4_disc.ISO if Path(bt4_disc.ISO).exists() else None


@unittest.skipUnless(disc(),'BT4 disc not available')
class RealSkeletonTests(unittest.TestCase):
    """Every actor tick of the authored scenes, on real disc rigs."""
    cache={}

    def scan(self,name,characters,scale=1.,phases=None,guard=False):
        import tag_rush_pair_clearance as clearance
        scene_=clearance.Scene(disc(),name,characters,scale=scale,cache=self.cache)
        rows=scene_.run(phases,enabled=guard)
        # 'after' includes CLEARANCE: above it, two body samples intersect.
        worst=max(rows,key=lambda r:r[3])
        self.assertLessEqual(worst[3],blue.CLEARANCE,(name,characters,scale,worst))
        return rows

    def test_goku_and_vegeta_blue_never_touch_in_the_dash_in_or_the_charge_on_any_arena(self):
        for victim,scale in ((16,1.),(133,.35),(133,.1)):
            rows=self.scan(blue.NAMES[0],(blue.GOKU,blue.VEGETA_BLUE,victim),scale,range(0,6))
            self.assertEqual(len(rows),sum(math.ceil(p.source_frames/2) for p in blue.own_timeline(blue.NAMES[0])[:6]))
        # The smallest clamped lane brings the victim within reach of the
        # beam stance; the runtime guard backs the attackers off at once.
        import tag_rush_pair_clearance as clearance
        rows=clearance.Scene(disc(),blue.NAMES[0],(blue.GOKU,blue.VEGETA_BLUE,133),scale=.05,cache=self.cache).run()
        self.assertLess(max(r[3] for r in rows),blue.CLEARANCE+.6)
        self.assertLessEqual(sum(r[3]>blue.CLEARANCE for r in rows),1)

    def test_trunks_and_vegeta_forms_never_touch_each_other_or_the_victim(self):
        for characters in ((225,31,133),(72,35,16),(149,113,0),(226,33,133)):
            self.scan(blue.NAMES[1],characters)

    def test_the_old_lane_scaling_is_what_made_the_pair_intersect(self):
        import tag_rush_pair_clearance as clearance
        old=clearance.Scene(disc(),blue.NAMES[0],(blue.GOKU,blue.VEGETA_BLUE,133),scale=.35,cache=self.cache,spacing=False)
        old.root=lambda role,index,s=old:clearance._yaw(s.yaw)@np.vstack((np.column_stack((s.matrix(role,index)[:3,:3],
            s.matrix(role,index)[:3,3]*s.scale)),(0,0,0,1)))
        rows=old.run(range(0,6),enabled=False)
        self.assertGreater(max(r[2] for r in rows),blue.CLEARANCE+2.)

    def test_spacing_table_is_the_offline_solution_for_the_exact_pair(self):
        import tag_rush_pair_clearance as clearance,tag_rush_blue_spacing as spacing
        self.assertEqual(tuple(clearance.generate_spacing(disc())),spacing.ROLE0)


if __name__=='__main__':unittest.main()
