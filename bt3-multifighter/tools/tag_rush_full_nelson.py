"""Portable full-nelson fitting reference; no emulator or asset writes.

FK matrices are row-indexed 4x4 matrices acting on column vectors, matching
model_viewer.pose_matrices. Rotations are XYZW quaternions. Only local joint
rotations change: the real upper-arm, forearm and palm offsets remain fixed.
The native helper uses the same paired targets; this module also handles
degenerate pole directions deterministically for offline previews.
"""
from dataclasses import dataclass
import math


ARMS=((18,19,20,21,31),(32,33,34,35,45))
EPS=1e-8


def _v(value):
    out=tuple(float(x) for x in value)
    if len(out)!=3 or not all(math.isfinite(x) for x in out):
        raise ValueError('Expected a finite three-dimensional point')
    return out


def add(a,b):return tuple(x+y for x,y in zip(a,b))
def sub(a,b):return tuple(x-y for x,y in zip(a,b))
def scale(v,k):return tuple(x*k for x in v)
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def length(v):return math.sqrt(dot(v,v))
def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])


def unit(value):
    value=_v(value);n=length(value)
    if n<EPS:raise ValueError('Degenerate direction or arm segment')
    return scale(value,1./n)


def qnorm(value):
    value=tuple(float(x) for x in value)
    if len(value)!=4 or not all(math.isfinite(x) for x in value):
        raise ValueError('Expected a finite XYZW quaternion')
    n=math.sqrt(dot(value,value))
    if n<EPS:raise ValueError('Degenerate quaternion')
    return tuple(x/n for x in value)


def qmul(p,q):
    x,y,z,w=p;X,Y,Z,W=q
    return (w*X+x*W+y*Z-z*Y,w*Y-x*Z+y*W+z*X,
            w*Z+x*Y-y*X+z*W,w*W-x*X-y*Y-z*Z)


def conjugate(q):return (-q[0],-q[1],-q[2],q[3])


def rotate(q,v):
    out=qmul(qmul(q,(*v,0.)),conjugate(q))
    return out[:3]


def from_to(old,new):
    old,new=unit(old),unit(new);d=max(-1.,min(1.,dot(old,new)))
    if 1.+d>1e-5:return qnorm((*cross(old,new),1.+d))
    axis=(1.,0.,0.) if abs(old[0])<.8 else (0.,1.,0.)
    return (*unit(cross(old,axis)),0.)


def nlerp(old,new,gain):
    old,new=qnorm(old),qnorm(new)
    if dot(old,new)<0:new=tuple(-x for x in new)
    return qnorm(tuple(a+(b-a)*gain for a,b in zip(old,new)))


def position(matrix):return _v(matrix[i][3] for i in range(3))


def rotation(matrix):
    """Unit quaternion from a finite, orthonormal FK rotation."""
    m=tuple(tuple(float(matrix[i][j]) for j in range(3)) for i in range(3))
    columns=[_v(m[i][j] for i in range(3)) for j in range(3)]
    if any(abs(dot(c,c)-1.)>2e-4 for c in columns):
        raise ValueError('Arm fitting does not stretch a scaled FK matrix')
    if any(abs(dot(columns[i],columns[j]))>2e-4 for i,j in ((0,1),(0,2),(1,2))):
        raise ValueError('Arm fitting requires an orthogonal FK matrix')
    if dot(cross(columns[0],columns[1]),columns[2])<.999:
        raise ValueError('Arm fitting requires a right-handed FK matrix')
    trace=sum(m[i][i] for i in range(3))
    if trace>0:
        s=math.sqrt(trace+1.)*2
        q=((m[2][1]-m[1][2])/s,(m[0][2]-m[2][0])/s,(m[1][0]-m[0][1])/s,s/4)
    else:
        i=max(range(3),key=lambda k:m[k][k]);j=(i+1)%3;k=(i+2)%3
        s=math.sqrt(max(0.,1.+m[i][i]-m[j][j]-m[k][k]))*2
        if s<EPS:raise ValueError('Degenerate FK rotation')
        out=[0.]*4;out[i]=s/4;out[j]=(m[i][j]+m[j][i])/s
        out[k]=(m[i][k]+m[k][i])/s;out[3]=(m[k][j]-m[j][k])/s;q=tuple(out)
    return qnorm(q)


@dataclass(frozen=True)
class ArmSolution:
    local_rotations: dict
    shoulder: tuple
    elbow: tuple
    wrist: tuple
    palm: tuple
    requested_palm: tuple
    reach_error: float
    upper_length: float
    forearm_length: float
    clamped: bool


def solve_arm(world, *, shoulder,elbow,wrist,palm,parent,target_palm,elbow_pole,
              palm_rotation=None,target_wrist=None,gain=1.,elbow_roll_gain=0.,elbow_roll=None):
    """Solve one real arm without changing translations, scaling or input data.

    target_wrist optionally matches the native paired fitter's explicit wrist
    target. In that mode the palm turns toward target_palm while retaining its
    existing twist. Otherwise palm_rotation is the desired world wrist rotation
    (or the current orientation), and the real marker offset locates the wrist.
    Unreachable targets stop just inside the arm's valid reach. A zero palm
    offset is valid; zero upper-arm/forearm lengths are not.
    """
    if not math.isfinite(gain) or not 0.<=gain<=1.:raise ValueError('Invalid fitting gain')
    if not math.isfinite(elbow_roll_gain) or not -1.<=elbow_roll_gain<=1.:raise ValueError('Invalid elbow-plane roll')
    if elbow_roll is not None:
        elbow_roll=tuple(float(x) for x in elbow_roll)
        if len(elbow_roll)!=2 or not all(math.isfinite(x) and abs(x)<=1. for x in elbow_roll) or sum(x*x for x in elbow_roll)<EPS:
            raise ValueError('Invalid elbow-plane coefficients')
    P=_v(target_palm);pole=_v(elbow_pole)
    S,E,W,H=(position(world[b]) for b in (shoulder,elbow,wrist,palm))
    Rp,Rs,Re,Rw=(rotation(world[b]) for b in (parent,shoulder,elbow,wrist))
    upper,forearm=sub(E,S),sub(W,E);l1,l2=length(upper),length(forearm)
    if min(l1,l2)<EPS:raise ValueError('Degenerate arm segment')
    palm_local=rotate(conjugate(Rw),sub(H,W))
    desired_rotation=qnorm(palm_rotation) if palm_rotation is not None else Rw
    T=_v(target_wrist) if target_wrist is not None else sub(P,rotate(desired_rotation,palm_local))
    offset=sub(T,S);distance=length(offset)
    # A target exactly at the shoulder still has a deterministic folded pose.
    u=unit(offset) if distance>EPS else unit(sub(W,S) if length(sub(W,S))>EPS else upper)
    margin=min(.001,min(l1,l2)*.1)
    low,high=abs(l1-l2)+margin,l1+l2-margin
    d=max(low,min(high,distance));clamped=abs(d-distance)>1e-7
    T=add(S,scale(u,d));along=(l1*l1-l2*l2+d*d)/(2*d)
    h=math.sqrt(max(0.,l1*l1-along*along))
    plane=sub(sub(pole,S),scale(u,dot(sub(pole,S),u)))
    if length(plane)<EPS:
        plane=sub(upper,scale(u,dot(upper,u)))
    if length(plane)<EPS:
        axis=(1.,0.,0.) if abs(u[0])<.8 else (0.,1.,0.)
        plane=cross(u,axis)
    # Optional cosine/sine coefficients interpolate the reviewed arm plane
    # without a search or transcendental operation in the native fitter.
    cosine,sine=elbow_roll if elbow_roll is not None else (
        1.-.06030737921409157*abs(elbow_roll_gain),.3420201433256687*elbow_roll_gain)
    plane=add(scale(plane,cosine),scale(cross(u,plane),sine))
    desired_elbow=add(add(S,scale(u,along)),scale(unit(plane),h))
    Qs=from_to(upper,sub(desired_elbow,S))
    Qe=from_to(rotate(Qs,forearm),sub(T,desired_elbow));total=qmul(Qe,Qs)
    new_s=qmul(Qs,Rs);new_e=qmul(total,Re)
    if target_wrist is not None and palm_rotation is None:
        moved=qmul(total,Rw);to_palm=sub(P,T)
        if length(palm_local)>EPS and length(to_palm)>EPS:
            desired_rotation=qmul(from_to(rotate(moved,palm_local),to_palm),moved)
        else:desired_rotation=moved
    old=(qmul(conjugate(Rp),Rs),qmul(conjugate(Rs),Re),qmul(conjugate(Re),Rw))
    solved=(qmul(conjugate(Rp),new_s),qmul(conjugate(new_s),new_e),
            qmul(conjugate(new_e),desired_rotation))
    local=tuple(nlerp(a,b,gain) for a,b in zip(old,solved))
    # Reconstruct the result from the unchanged local offsets. This also gives
    # honest contact error during acquisition or an unreachable target.
    out_s=qmul(Rp,local[0]);out_e=qmul(out_s,local[1]);out_w=qmul(out_e,local[2])
    out_E=add(S,rotate(out_s,rotate(conjugate(Rs),upper)))
    out_W=add(out_E,rotate(out_e,rotate(conjugate(Re),forearm)))
    out_H=add(out_W,rotate(out_w,palm_local))
    return ArmSolution(dict(zip((shoulder,elbow,wrist),local)),S,out_E,out_W,out_H,P,
                       length(sub(P,out_H)),l1,l2,clamped)


@dataclass(frozen=True)
class PairFit:
    victim_delta: tuple
    right: tuple
    up: tuple
    back: tuple
    shoulder_width: float
    desired_neck: tuple
    palm_targets: tuple
    elbow_poles: tuple
    arms: tuple
    gain: float
    victim_rotations: dict
    holder_rotations: dict


def adjusted_victim(world,*,style=0,gain=1.):
    """Rigidly pose the real arm chains for the reachable upper-arm restraint.

    The topology is the reviewed native humanoid arm layout. A local quaternion
    changes before its descendants are rebuilt; neither a segment nor a model
    is scaled. Returning a copy also makes partial acquisition safe to preview.
    """
    if style not in (0,1):raise ValueError('Unknown full-nelson fitting style')
    if not math.isfinite(gain) or not 0.<=gain<=1.:raise ValueError('Invalid fitting gain')
    result=dict(world);local={}
    def axis(y,z):
        y=math.radians(y)*.5;z=math.radians(z)*.5
        return qmul((0.,math.sin(y),0.,math.cos(y)),(0.,0.,math.sin(z),math.cos(z)))
    targets=((18,17,31,axis(30,30)),(19,18,31,axis(-10,25)),
             (32,17,45,axis(-30,-30)),(33,32,45,axis(10,-25))) if style else (
             (18,17,31,axis(0,30)),(19,18,31,axis(-45,30)),(20,19,31,axis(-35,0)),
             (32,17,45,axis(0,-30)),(33,32,45,axis(45,-30)),(34,33,45,axis(35,0)))
    for bone,parent,end,target in targets:
        before=rotation(result[bone]);parent_rotation=rotation(result[parent])
        original=qmul(conjugate(parent_rotation),before)
        after=nlerp(original,target,gain);local[bone]=after
        delta=qmul(qmul(parent_rotation,after),conjugate(before));pivot=position(result[bone])
        for child in range(bone,end+1):
            if child not in result:continue
            old=result[child];point=add(pivot,rotate(delta,sub(position(old),pivot)))
            columns=[rotate(delta,_v(old[i][j] for i in range(3))) for j in range(3)]
            result[child]=tuple(tuple(columns[j][i] for j in range(3))+(point[i],) for i in range(3))+((0.,0.,0.,1.),)
    return result,local


def normal_parameters(width):
    """Bounded small-to-ordinary grip, measured on real Krillin and Tien rigs."""
    if not math.isfinite(width) or width<EPS:raise ValueError('Invalid shoulder span')
    blend=max(0.,min(1.,(width-3.8064466751111894)/.7844483481865596))
    return dict(blend=blend,gap=2.65+.35*blend,lower=-1.+.9*blend,
                spread=1.+.25*blend,palm_height=1.1+.9*blend)


def _qxyz(x,y,z):
    def axis(which,angle):
        a=math.radians(angle)*.5;v=[0.,0.,0.,math.cos(a)];v[which]=math.sin(a);return tuple(v)
    return qmul(axis(0,x),qmul(axis(1,y),axis(2,z)))


def fit_pair(holder,victim,*,elapsed=28.,gap_base=None,head_clearance=None,body_clearance=0.,
             style=None,palm_height=None):
    """Bounded fixed-length behind-head clasp or broad-body upper-arm restraint.

    Models face -Z and use negative Y up. All authored local rotations are
    returned explicitly; the caller recomposes the same unchanged hierarchy.
    Acquisition blends over28 source frames. Exact costume profiles can refine
    head/body spacing, while an unknown broad transformed body uses style1.
    """
    if not math.isfinite(elapsed) or elapsed<0:raise ValueError('Invalid acquisition frame')
    if style is None:
        hw=length(sub(position(holder[33]),position(holder[19])))
        vw=length(sub(position(victim[33]),position(victim[19])))
        if min(hw,vw)<EPS:raise ValueError('Degenerate shoulder span')
        style=int(vw>hw*1.2)
    if style not in (0,1):raise ValueError('Unknown full-nelson fitting style')
    if gap_base is not None and (not math.isfinite(gap_base) or not 0.<=gap_base<=10.):raise ValueError('Invalid body spacing')
    if head_clearance is not None and (not math.isfinite(head_clearance) or not 0.<=head_clearance<=3.5):raise ValueError('Invalid head clearance')
    if not math.isfinite(body_clearance) or not 0.<=body_clearance<=2.:raise ValueError('Invalid body clearance')
    if palm_height is not None and (not math.isfinite(palm_height) or not -1.5<=palm_height<=3.):raise ValueError('Invalid palm height')
    t=min(1.,elapsed/28.);gain=t*t*(3.-2.*t)
    victim,victim_rotations=adjusted_victim(victim,style=style,gain=gain)
    right_raw=sub(position(victim[33]),position(victim[19]));width=length(right_raw)
    right=unit(right_raw);up=unit(sub(position(victim[46]),position(victim[17])))
    back=unit(cross(up,right));normal=normal_parameters(width)
    if head_clearance is None:head_clearance=.85 if style else .8*(1.-normal['blend'])
    if gap_base is None:gap_base=5. if style else normal['gap']
    if palm_height is None:palm_height=.25 if style else normal['palm_height']
    gap=gap_base+.16*width+.7*(1.-gain)+body_clearance
    neck=sub(sub(position(holder[46]),scale(back,gap)),scale(up,.5 if style else normal['lower']))
    delta=sub(neck,position(victim[46]))
    center=add(add(neck,scale(back,.4+.045*width+head_clearance)),scale(up,palm_height))
    arms=[];palms=[];poles=[]
    down,outside,forward=(5.,10.,-3.) if style else (1.5,1.8,-.8+.2*normal['blend'])
    for side,(parent,shoulder,elbow,wrist,palm) in zip((-1.,1.),ARMS):
        P=add(center,scale(right,side*normal['spread']))
        x,y,z=scale(right,-1.),scale(back,-1.),up
        if style:
            P=add(add(position(victim[shoulder]),delta),scale(sub(position(victim[elbow]),position(victim[shoulder])),.25))
            P=add(P,add(scale(back,2.9),scale(right,side*1.7)))
            x=scale(up,side);y=unit(add(scale(right,-side),scale(back,-1.)));z=cross(x,y)
            start=add(position(holder[shoulder]),add(scale(right,side*3.),add(back,scale(up,.5))))
            P=add(scale(start,1.-gain),scale(P,gain))
        else:
            # Route around the outside of the raised arms before closing the
            # clasp. Blending the old local rotations crossed the held body.
            P=add(P,add(scale(right,side*3.*(1.-gain)),
                        add(scale(back,2.*(1.-gain)),scale(up,4.*gain*(1.-gain)))))
        palm_rotation=rotation(tuple(tuple(c[i] for c in (x,y,z))+(0.,)for i in range(3))+((0.,0.,0.,1.),))
        pole=sub(add(sub(add(position(victim[shoulder]),delta),scale(up,down)),scale(right,side*outside)),scale(back,forward))
        arms.append(solve_arm(holder,shoulder=shoulder,elbow=elbow,wrist=wrist,palm=palm,parent=parent,
                              target_palm=P,palm_rotation=palm_rotation,elbow_pole=pole,gain=1.,
                              elbow_roll=None if style else (
                                  .9396926207859084-.4396926207859084*normal['blend'],
                                  side*(.3420201433256687+.5240052604587699*normal['blend']))))
        palms.append(P);poles.append(pole)
    holder_rotations={}
    for first,side in ((23,1.),(37,-1.)):
        for bone in range(first,first+8):
            parent=bone-1 if (bone-first)%2 else (21 if first==23 else 35)
            old=qmul(conjugate(rotation(holder[parent])),rotation(holder[bone]))
            flex=(35. if (bone-first)%2==0 else 45.) if style else (15. if (bone-first)%2==0 else 25.)
            holder_rotations[bone]=nlerp(old,_qxyz(0,0,-side*flex),gain)
    if not style:
        for bone,parent,angles in ((46,17,(-30,-45,35)),(47,46,(10,30,0))):
            old=qmul(conjugate(rotation(holder[parent])),rotation(holder[bone]))
            holder_rotations[bone]=nlerp(old,_qxyz(*angles),gain)
    return PairFit(delta,right,up,back,width,neck,tuple(palms),tuple(poles),tuple(arms),gain,victim_rotations,holder_rotations)


def body_profile(world,torso_points=()):
    """Measured pose dimensions for offline fitting audits.

    Optional torso_points must be actual posed torso vertices, excluding arms,
    hair, tails and effects. Depths measure from chest17 along the derived body
    back axis, so this can reveal costumes/bodies that need a larger chest gap.
    """
    chest,neck=position(world[17]),position(world[46])
    shoulders=sub(position(world[33]),position(world[19]))
    right=unit(shoulders);up=unit(sub(neck,chest));back=unit(cross(up,right))
    depths=[dot(sub(_v(point),chest),back) for point in torso_points]
    return dict(shoulder_width=length(shoulders),neck_to_chest=length(sub(neck,chest)),
                front_depth=max(0.,-min(depths)) if depths else None,
                back_depth=max(0.,max(depths)) if depths else None,
                neck=neck,right=right,up=up,back=back)
