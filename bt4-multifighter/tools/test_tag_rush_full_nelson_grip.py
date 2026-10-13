"""Poser geometry oracles and exact authored endpoint skinning fidelity."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import math
import unittest
import tag_rush_full_nelson as ik
import tag_rush_full_nelson_profiles as profiles
from test_tag_rush_full_nelson import simple_arm,solve,actual_pose,discs,native_fit,authored_reference


def inside_mesh(triangles,points):
    """Independent three-axis closed-surface oracle, in bounded batches."""
    import numpy as np
    triangles=np.asarray(triangles,float);points=np.asarray(points,float);outputs=[]
    for start in range(0,len(points),128):
        pts=points[start:start+128];votes=[]
        for axis in range(3):
            uv=[k for k in range(3) if k!=axis];a=triangles[:,0,uv];e=triangles[:,1,uv]-a;f=triangles[:,2,uv]-a
            den=e[:,0]*f[:,1]-e[:,1]*f[:,0];ok=abs(den)>1e-9
            a,e,f,den,t=a[ok],e[ok],f[ok],den[ok],triangles[ok]
            q=pts[:,None,uv]-a[None,:,:]
            u=(q[:,:,0]*f[None,:,1]-q[:,:,1]*f[None,:,0])/den
            v=(e[None,:,0]*q[:,:,1]-e[None,:,1]*q[:,:,0])/den
            z=t[None,:,0,axis]+u*(t[None,:,1,axis]-t[None,:,0,axis])+v*(t[None,:,2,axis]-t[None,:,0,axis])-pts[:,None,axis]
            hits=(u>=-1e-6)&(v>=-1e-6)&(u+v<=1+1e-6)&(z>1e-4)
            distances=np.sort(np.where(hits,z,np.inf),axis=1)
            with np.errstate(invalid='ignore'):
                unique=np.concatenate((np.ones((len(pts),1),bool),np.diff(distances,axis=1)>1e-4),axis=1)
            votes.append(np.sum(np.isfinite(distances)&unique,axis=1)%2==1)
        outputs.extend(np.sum(votes,axis=0)>=2)
    return np.asarray(outputs,bool)


def surface_distances(points,triangles):
    """Closest point-to-triangle distance, including face interiors and edges."""
    import numpy as np
    triangles=np.asarray(triangles,float);points=np.asarray(points,float)
    a,b,c=triangles[:,0],triangles[:,1],triangles[:,2];ab=b-a;ac=c-a
    n=np.cross(ab,ac);length=np.linalg.norm(n,axis=1);valid=length>1e-8
    a,b,c,ab,ac,n,length=(v[valid] for v in (a,b,c,ab,ac,n,length));n=n/length[:,None]
    aa=np.sum(ab*ab,axis=1);bb=np.sum(ab*ac,axis=1);cc=np.sum(ac*ac,axis=1);den=aa*cc-bb*bb
    result=[]
    for start in range(0,len(points),128):
        pts=points[start:start+128];offset=pts[:,None,:]-a[None,:,:]
        signed=np.sum(offset*n[None,:,:],axis=2);plane=offset-signed[:,:,None]*n[None,:,:]
        pa=np.sum(plane*ab[None,:,:],axis=2);pc=np.sum(plane*ac[None,:,:],axis=2)
        u=(cc*pa-bb*pc)/den;v=(aa*pc-bb*pa)/den
        distance=np.where((u>=0)&(v>=0)&(u+v<=1),abs(signed),np.inf)
        for first,last in ((a,b),(b,c),(c,a)):
            edge=last-first;at=pts[:,None,:]-first[None,:,:]
            t=np.clip(np.sum(at*edge[None,:,:],axis=2)/np.sum(edge*edge,axis=1),0,1)
            distance=np.minimum(distance,np.linalg.norm(at-t[:,:,None]*edge[None,:,:],axis=2))
        result.extend(np.min(distance,axis=1))
    return np.asarray(result)


class ReviewedGripTests(unittest.TestCase):
    def test_small_normal_interpolation_is_bounded_and_continuous(self):
        small=ik.normal_parameters(3.8064466751111894);normal=ik.normal_parameters(4.590895023297749)
        self.assertAlmostEqual(small['gap'],2.65);self.assertAlmostEqual(small['lower'],-1.)
        self.assertAlmostEqual(normal['gap'],3.);self.assertAlmostEqual(normal['lower'],-.1)
        self.assertEqual(ik.normal_parameters(.01),small);self.assertEqual(ik.normal_parameters(50.),normal)
        previous=None
        for i in range(101):
            params=ik.normal_parameters(3.8064466751111894+.7844483481865596*i/100)
            if previous is not None:
                for key in params:self.assertLess(abs(params[key]-previous[key]),.02)
            previous=params
        for width in (0.,-1.,math.nan,math.inf):
            with self.assertRaises(ValueError):ik.normal_parameters(width)

    def test_elbow_circle_changes_only_arm_plane_not_lengths_or_contact(self):
        world=simple_arm();args=dict(target_palm=(2.,2.,0.),elbow_pole=(0.,0.,3.))
        base=solve(world,**args);axis=ik.unit(ik.sub(base.wrist,base.shoulder))
        origin=ik.add(base.shoulder,ik.scale(axis,ik.dot(ik.sub(base.elbow,base.shoulder),axis)))
        start=ik.unit(ik.sub(base.elbow,origin))
        for amount in (-1.,-.5,0.,.5,1.):
            fitted=solve(world,elbow_roll_gain=amount,**args)
            self.assertLess(ik.length(ik.sub(fitted.palm,base.palm)),1e-6)
            self.assertAlmostEqual(ik.length(ik.sub(fitted.elbow,fitted.shoulder)),2.)
            self.assertAlmostEqual(ik.length(ik.sub(fitted.wrist,fitted.elbow)),2.)
            if abs(amount)==1:
                angle=math.degrees(math.acos(ik.dot(start,ik.unit(ik.sub(fitted.elbow,origin)))))
                self.assertAlmostEqual(angle,20.,places=6)
        for amount in (-1.1,1.1,math.nan):
            with self.assertRaises(ValueError):solve(world,elbow_roll_gain=amount,**args)
        for degrees in (-60.,-20.,20.,60.):
            angle=math.radians(degrees)
            fitted=solve(world,elbow_roll=(math.cos(angle),math.sin(angle)),**args)
            self.assertLess(ik.length(ik.sub(fitted.palm,base.palm)),1e-6)
            actual=math.degrees(math.acos(ik.dot(start,ik.unit(ik.sub(fitted.elbow,origin)))))
            self.assertAlmostEqual(actual,abs(degrees),places=6)
        for coefficients in ((0.,0.),(math.nan,0.),(1.1,0.),(1.,)):
            with self.assertRaises(ValueError):solve(world,elbow_roll=coefficients,**args)

    def test_closed_surface_oracles_agree_without_a_pose_collision_golden(self):
        import numpy as np
        vertices=np.array(((-1,-1,-1),(-1,-1,1),(-1,1,-1),(-1,1,1),
                           (1,-1,-1),(1,-1,1),(1,1,-1),(1,1,1)),float)
        faces=np.array(((0,1,3),(0,3,2),(4,6,7),(4,7,5),(0,4,5),(0,5,1),
                        (2,3,7),(2,7,6),(0,2,6),(0,6,4),(1,5,7),(1,7,3)))
        triangles=vertices[faces]
        points=np.array(((0,0,0),(.3,.2,.4),(1.5,0,0),(0,-2,0)),float)
        expected=np.array((True,True,False,False))
        self.assertTrue(np.array_equal(inside_mesh(triangles,points),expected))
        self.assertEqual(profiles.solid_evaluator(triangles)(points),2)
        distances=surface_distances(points,triangles)
        self.assertTrue(np.allclose(distances,(1.,.6,.5,1.),atol=1e-6))

    def test_actual_guest_skin_matches_the_authored_reference_for_every_vertex(self):
        import numpy as np
        import tag_rush_assets as assets
        import tag_rush_authored_hold as authored
        from native_map import SERIAL
        paths=discs()
        if not paths:self.skipTest('User-owned game disc unavailable')
        broad=190 if SERIAL=='SLUS-21978' else 133
        for iso in paths:
            cache={};holder,pose,world=actual_pose(iso,0,0,2,20,cache)
            hm=profiles.geometry(assets._mesh_package(iso,0),(0,0,False))
            for character in(25,27,broad):
                with self.subTest(iso=iso.name,character=character):
                    victim,vpose,vworld=actual_pose(iso,character,2,2,20,cache)
                    vm=profiles.geometry(assets._mesh_package(iso,character),(character,0,False))
                    receipt,expected=authored_reference(holder,pose,world,victim,vpose,vworld)
                    cpu,_,_=native_fit(holder,pose,world,victim,vpose,vworld,phase=2,ticks=11,recompose=True)
                    self.assertEqual(cpu.r[2],1)
                    self.assertEqual(receipt['source_sha256'],authored.SOURCE_SHA256)
                    for role,mesh in((0,hm),(1,vm)):
                        got=profiles.skin(mesh,cpu.recomposed[role]);want=profiles.skin(mesh,expected[role][2])
                        self.assertEqual(got.shape,want.shape)
                        self.assertLess(float(np.linalg.norm(got-want,axis=1).max()),1e-3)
                        # Bone translations remain native: no contact correction
                        # or stretching can silently replace the edited pose.
                        for first,last in((19,20),(20,21),(21,31),(33,34),(34,35),(35,45)):
                            a=cpu.recomposed[role];b=world if role==0 else vworld
                            self.assertAlmostEqual(ik.length(ik.sub(ik.position(a[first]),ik.position(a[last]))),
                                ik.length(ik.sub(ik.position(b[first]),ik.position(b[last]))),places=4)
                    # Endpoint rotations, including hands/head, are final. A
                    # subsequent IK pass must not move them to a different grip.
                    for role,name in((0,'holder'),(1,'victim')):
                        for bone,q in receipt['actors'][name]['rotations'].items():
                            import struct
                            actual=struct.unpack('<4f',cpu.read(0x2300000+role*0x10000+bone*256+160,16))
                            self.assertGreater(abs(ik.dot(actual,q)),1.-2e-5)


if __name__=='__main__':unittest.main()
