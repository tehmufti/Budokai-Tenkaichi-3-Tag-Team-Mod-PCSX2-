"""Offline per-tick body clearance for the authored paired-beam scenes.

Reference model of what the guest does each actor tick after the shared
opening: sample every role's authored root, apply the body-sized lane spacing,
pose the real recipient skeleton with the retargeted clip, then run the same
overlap guard (tag_rush_blue_native.separate_code). Used by the guard tests to
prove that no two bodies intersect during the dash-in, the charge or the beam
exchange, for real character skeletons and several arena scales.
"""
import math
import struct
from types import SimpleNamespace

import numpy as np

import tag_rush_blue_native as blue


def _yaw(angle):
    c,s=math.cos(angle),math.sin(angle)
    return np.array(((c,0.,s,0.),(0.,1.,0.,0.),(-s,0.,c,0.),(0.,0.,0.,1.)))


class Rig:
    """Real native hierarchy (imported meshes included) and its binds."""
    def __init__(self,iso,character,cache):
        import tag_rush_assets as assets
        key=('skeleton',character)
        if key not in cache:cache[key]=assets.read_skeleton(iso,character)
        skeleton=cache[key];unique={row['bone']:row for row in skeleton['rows']}
        self.character=character;self.height=skeleton['height']
        self.binds={bone:row['translation'] for bone,row in unique.items()}
        self.bones=tuple(SimpleNamespace(native_id=bone,parent_id=row['parent'],bind_translation=row['translation'])
                         for bone,row in unique.items())


def pose(recipient,donor,raw,frame):
    """The tag retarget: donor bind deltas, Y by height ratio, recipient binds."""
    from model_animations import AnimationClip,BoneTransform
    clip=AnimationClip.from_decoded(0,raw);result={}
    for bone,t in clip.evaluate(min(float(frame),clip.frame_count)).items():
        translation=t.translation
        if translation is not None and bone in donor.binds and bone in recipient.binds:
            delta=[a-b for a,b in zip(translation,donor.binds[bone])]
            delta[1]*=recipient.height/donor.height
            translation=tuple(a+b for a,b in zip(delta,recipient.binds[bone]))
        result[bone]=BoneTransform(translation,t.rotation)
    return pose_matrices(recipient.bones,result)


def pose_matrices(bones,transforms):
    """model_viewer.pose_matrices without the GUI dependency."""
    from tag_rush_full_nelson_profiles import matrix
    world,remaining={},{b.native_id:b for b in bones}
    while remaining:
        progress=False
        for key,bone in list(remaining.items()):
            if bone.parent_id in remaining:continue
            t=transforms.get(key)
            local=matrix(t.rotation) if t else np.eye(4)
            local[:3,3]=t.translation if t and t.translation is not None else bone.bind_translation
            world[key]=world.get(bone.parent_id,np.eye(4))@local
            del remaining[key];progress=True
        if not progress:raise ValueError('Skeleton contains a parent cycle')
    return world


def body_points(world_root,matrices,scale=1.):
    out=[]
    for bone,radius in blue.BODY:
        m=matrices.get(bone)
        if m is None:continue
        out.append(((world_root@m)[:3,3],radius*scale))
    return out


def penetration(first,second):
    worst=-1e9
    for p,r in first:
        for q,s in second:
            worst=max(worst,r+s+blue.CLEARANCE-float(np.linalg.norm(p-q)))
    return worst


class Scene:
    """One authored variant on real recipients; ticks at the native rate."""
    def __init__(self,iso,name,characters,*,scale=1.,yaw=.7,hz=30,cache=None,raw_bank=False,spacing=True):
        self.cache={} if cache is None else cache;self.name=name;self.scale=scale;self.yaw=yaw;self.hz=hz
        self.rigs=[Rig(iso,c,self.cache) for c in characters]
        self.variant=blue.NAMES.index(name);self.spacing_at=0
        self.root_indices=(0,0,0)
        if raw_bank:
            # Variant5 straight from the reviewed authored bank (for solving).
            if self.variant:raise ValueError('Only variant5 has an authored bank')
            header,payload=blue.bank();self.data=payload;self.base=0
            self.samples,self.phases,self.mode=213,7,blue.LANE
            self.roots=tuple(header['roots'][:3]);self.edges=blue.EDGES
        else:
            built=self.cache.get(('build',))
            if built is None:built=self.cache[('build',)]=blue.build(iso)
            self.built=built;self.data=built['blocks'][0][1];self.base=blue.DATA
            table=struct.unpack_from('<12I',self.data,blue.TABLES-blue.DATA+blue.TABLE_SIZE*self.variant)
            self.samples,self.phases,self.mode=table[:3];self.roots=table[3:6]
            self.edges=struct.unpack_from('<%dI'%(self.phases+1),self.data,table[7]-blue.DATA)
            self.spacing_at=table[8] if spacing else 0
            if table[10]:self.root_indices=struct.unpack_from('<3I',self.data,table[10]-blue.DATA)
        timeline=blue.own_timeline(name);self.timeline=timeline
        clips=self.cache.get(('clips',raw_bank))
        if clips is None:clips=self.cache[('clips',raw_bank)]=blue._blue_clips() if raw_bank else blue.prepared_clips(iso)
        self.clips=clips
        donors=self.cache.get(('donors',name))
        if donors is None:
            if self.variant==0:chars=(122,35,0)
            else:
                import tag_rush_galick_pair as galick
                chars=galick.DONORS
            donors=self.cache[('donors',name)]=[Rig(iso,c,self.cache) for c in chars]
        self.donors=donors
        self.sep=[np.zeros(3) for _ in range(3)];self.ground=[0.,0.,0.]

    def sample(self,phase,ticks):
        frame=self.edges[phase]+ticks*60//self.hz
        return min(frame>>1,self.samples-1),min(ticks*60/self.hz,self.timeline[phase].source_frames)

    def matrix(self,role,index):
        if self.root_indices[role]:
            index=struct.unpack_from('<H',self.data,self.root_indices[role]-self.base+2*index)[0]
        at=self.roots[role]-self.base+64*index
        return np.frombuffer(self.data[at:at+64],dtype='<f4').reshape(4,4).T.astype(np.float64)

    def root(self,role,index):
        m=self.matrix(role,index).copy();p=m[:3,3].copy()
        local=p*(self.scale if self.mode==blue.LANE else 1.)
        if role<2 and self.mode==blue.LANE:
            other=self.matrix(role^1,index)[:3,3]
            local=local+np.asarray(blue.lane_offset(p,other,self.scale))
            if self.spacing_at:
                at=self.spacing_at-blue.DATA+16*index
                local=local+(1. if role==0 else -1.)*np.frombuffer(self.data[at:at+12],dtype='<f4').astype(np.float64)
        world=_yaw(self.yaw)@np.vstack((np.column_stack((m[:3,:3],local)),(0,0,0,1)))
        world[:3,3]+=self.sep[role];world[1,3]+=self.ground[role]
        return world

    def bodies(self,phase,ticks):
        index,frame=self.sample(phase,ticks);result=[]
        for role,(rig,donor) in enumerate(zip(self.rigs,self.donors)):
            source=self.timeline[phase].roles[role]
            raw=self.clips[source]
            result.append((self.root(role,index),body_points(self.root(role,index),pose(rig,donor,raw,frame))))
        return result

    def guard(self,phase,ticks,*,enabled=True):
        """Return (worst penetration before, after) the guest's guard."""
        bodies=self.bodies(phase,ticks)
        before=max(penetration(bodies[a][1],bodies[b][1]) for a,b in ((0,1),(0,2),(1,2)))
        if not enabled:return before,before
        pushed_any=False
        for _ in range(2):
            pushed=False
            for a,b,share in ((0,1,.5),(0,2,1.),(1,2,1.)):
                pen=penetration(bodies[a][1],bodies[b][1])
                if pen<=0:continue
                d=bodies[a][0][:3,3]-bodies[b][0][:3,3];d[1]=0.;n=float(np.linalg.norm(d))
                d=d/n if n>=.01 else np.array((math.cos(self.yaw),0.,-math.sin(self.yaw)))
                self.sep[a]+=d*pen*share
                if share<1:self.sep[b]-=d*pen*share
                pushed=True
            for role in (0,1):self.sep[role]=np.clip(self.sep[role],-blue.SEPARATION_LIMIT,blue.SEPARATION_LIMIT)
            if not pushed:break
            pushed_any=True;bodies=self.bodies(phase,ticks)
        if not pushed_any:
            for role in (0,1):self.sep[role]*=blue.SEPARATION_DECAY
        after=max(penetration(bodies[a][1],bodies[b][1]) for a,b in ((0,1),(0,2),(1,2)))
        return before,after

    def run(self,phases=None,*,enabled=True):
        """Every actor tick of the chosen authored phases -> worst rows."""
        rows=[]
        for phase in (range(self.phases) if phases is None else phases):
            ticks=math.ceil(self.timeline[phase].source_frames*self.hz/60)
            for tick in range(1,ticks+1):
                before,after=self.guard(phase,tick,enabled=enabled)
                rows.append((phase,tick,before,after))
        return rows


def generate_spacing(iso):
    """The exact reviewed Goku Blue/Vegeta Blue pair, solved without spacing."""
    return solve_spacing(Scene(iso,blue.NAMES[0],(blue.GOKU,blue.VEGETA_BLUE,0),raw_bank=True))


def write_spacing(iso,path=None):
    from pathlib import Path
    rows=generate_spacing(iso)
    lines=['"""Generated by tag_rush_pair_clearance.write_spacing; do not edit.','',
           'Variant5 role0 extra local spacing per authored sample (role1 negated).','"""','ROLE0=(']
    lines+=['    (%r,%r,%r),'%row for row in rows]+[')','']
    target=Path(path) if path else Path(__file__).with_name('tag_rush_blue_spacing.py')
    target.write_bytes('\r\n'.join(lines).encode())
    return rows


def solve_spacing(scene,*,margin=.6,dilate=8,blur=9):
    """Smooth symmetric extra spacing so the authored pair never touches.

    scene is a variant Scene at full scale with the exact reviewed pair. The
    result is one local (pre-yaw, unscaled) XYZ offset per sample for role0;
    role1 receives its negation. Spacing grows along the pair's horizontal
    authored separation only, so composition and travel are otherwise kept.
    """
    count=scene.samples;need=np.zeros(count);direction=np.zeros((count,3))
    for index in range(count):
        frame=2*index
        phase=max(i for i in range(scene.phases) if scene.edges[i]<=frame)
        local=min(frame-scene.edges[phase],scene.timeline[phase].source_frames)
        p=scene.matrix(0,index)[:3,3]-scene.matrix(1,index)[:3,3];p[1]=0.
        n=float(np.linalg.norm(p));d=p/n if n>=.01 else np.array((1.,0.,0.))
        direction[index]=d;extra=0.
        for _ in range(12):
            scene.sep=[np.zeros(3) for _ in range(3)]
            yaw=_yaw(scene.yaw)[:3,:3]
            scene.sep[0]=yaw@(d*extra*.5);scene.sep[1]=-yaw@(d*extra*.5)
            bodies=_bodies_at(scene,phase,index,local)
            pen=penetration(bodies[0][1],bodies[1][1])+margin
            if pen<=0:break
            extra+=pen
        need[index]=extra
    scene.sep=[np.zeros(3) for _ in range(3)]
    grown=np.array([need[max(0,i-dilate):i+dilate+1].max() for i in range(count)])
    kernel=np.ones(blur)/blur
    for _ in range(2):grown=np.convolve(np.pad(grown,blur//2,mode='edge'),kernel,mode='valid')
    grown=np.maximum(grown,need)
    vectors=direction*grown[:,None]*.5
    return [tuple(round(float(v),3) for v in row) for row in vectors]


def _bodies_at(scene,phase,index,frame):
    result=[]
    for role,(rig,donor) in enumerate(zip(scene.rigs,scene.donors)):
        raw=scene.clips[scene.timeline[phase].roles[role]]
        root=scene.root(role,index)
        result.append((root,body_points(root,pose(rig,donor,raw,frame))))
    return result
