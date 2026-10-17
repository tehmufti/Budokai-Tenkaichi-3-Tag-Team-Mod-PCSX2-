"""Authored reference choreography for the BT4 paired-beam cinematic.

Revision 13 uses the user's accepted Vegeta charging pose in the local
renderer. Saved joint changes blend over the native charge animation and
back into the release; the other choreography and cameras remain intact.
Public times are real seconds. All actors update regardless of camera.
Native integration must keep each attacker's own
dash aura throughout this scene and restore its prior state on every exit.
Coordinates are right-handed, Y up, in native model units.
"""
from dataclasses import dataclass
import math

NAME = 'blue_galick_kamehameha'
REVISION = 13
GOKU_BLUE, VEGETA_BLUE = 122, 35
PREVIEW_ONLY = True
PREVIOUS_PLAYBACK_RATE = 2.35
MOVEMENT_MULTIPLIER = 1.5
PLAYBACK_RATE = PREVIOUS_PLAYBACK_RATE * MOVEMENT_MULTIPLIER
AUTHORED_DURATION = 17.5
CHARGE_SOURCE_START, CHARGE_SOURCE_END = 4.45, 8.03
CHARGE_EXTRA_SECONDS = 1.05
OPENING_SOURCE_END = 3.45
OPENING_END = 2.0
OPENING_CUTS = (0., .55, 1.02, 1.50, OPENING_END)
FLIGHT_DISTANCE_SCALE = OPENING_END / 1.05
JOIN_OFFSET = OPENING_END - OPENING_SOURCE_END / PLAYBACK_RATE
CHARGE_START = CHARGE_SOURCE_START / PLAYBACK_RATE + JOIN_OFFSET
CHARGE_END = CHARGE_SOURCE_END / PLAYBACK_RATE + CHARGE_EXTRA_SECONDS + JOIN_OFFSET
DURATION = AUTHORED_DURATION / PLAYBACK_RATE + CHARGE_EXTRA_SECONDS + JOIN_OFFSET
FIRE = 8.25 / PLAYBACK_RATE + CHARGE_EXTRA_SECONDS + JOIN_OFFSET
IMPACT = 11.9 / PLAYBACK_RATE + CHARGE_EXTRA_SECONDS + JOIN_OFFSET
RECOVERY = 14.65 / PLAYBACK_RATE + CHARGE_EXTRA_SECONDS + JOIN_OFFSET
VICTIM = (0., 53., 230.)
ROLES = ('goku', 'vegeta', 'victim')
AURA_POLICY = 'native_dash_continuous'
AURA_ROLES = ('goku', 'vegeta')
BLUE = (0.10, 0.62, 1.0)
GOLD = (1.0, 0.76, 0.05)
# Raising the palms toward the crown intersected this model's head and hair.
# Retain native endpoints; route the elbows below and behind the real head.
VEGETA_CHARGE_HAND_SHIFT = (0., 0., 0.)
VEGETA_CHARGE_ELBOW_POLE = (0., 2., 4.)  # native pose space, Y down
VEGETA_OUTWARD_TURN = 10.  # positive world yaw turns away from Goku, who is on -X
VEGETA_LEAN_BACK = 20.  # torso line relative to vertical, from the user's sketch
VEGETA_ARMS_BACK = .45  # native units opposite the animated chest's forward axis
VEGETA_ARMS_RELEASE = .16  # authored seconds to return to the native firing arms
VEGETA_TARGET_GLANCE = 69.  # sixty more degrees toward the opponent than draft 10
VEGETA_HEAD_ELEVATION = 20.  # forty degrees lower than draft 11, above horizontal


def eligible(a, b, *, bt4=False):
    return bool(bt4 and type(a) is int and type(b) is int
                and {a, b} == {GOKU_BLUE, VEGETA_BLUE})


def smooth(value):
    t = max(0., min(float(value), 1.))
    return t*t*(3.-2.*t)


def lerp(a, b, t):
    return tuple(x+(y-x)*t for x,y in zip(a,b))


def bezier(points, t):
    points = tuple(tuple(p) for p in points)
    while len(points) > 1:
        points = tuple(lerp(a,b,t) for a,b in zip(points,points[1:]))
    return points[0]


def checked_time(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError('Cinematic time must be finite')
    return max(0.,min(float(value),DURATION))


def source_time(seconds):
    """Preserve the complete authored motion path, extending only its charge."""
    seconds = checked_time(seconds)
    if seconds <= OPENING_END:
        return seconds * OPENING_SOURCE_END / OPENING_END
    if seconds <= CHARGE_START:
        return (seconds - JOIN_OFFSET) * PLAYBACK_RATE
    if seconds < CHARGE_END:
        u = (seconds - CHARGE_START) / (CHARGE_END - CHARGE_START)
        return CHARGE_SOURCE_START + u * (CHARGE_SOURCE_END - CHARGE_SOURCE_START)
    return (seconds - CHARGE_EXTRA_SECONDS - JOIN_OFFSET) * PLAYBACK_RATE


def time_for_source(value):
    """Inverse staging clock for sampling/export; do not divide by the rate."""
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError('Authored time must be finite')
    value = max(0.,min(float(value),AUTHORED_DURATION))
    if value <= OPENING_SOURCE_END:
        return value * OPENING_END / OPENING_SOURCE_END
    if value <= CHARGE_SOURCE_START:
        return value / PLAYBACK_RATE + JOIN_OFFSET
    if value < CHARGE_SOURCE_END:
        u = (value - CHARGE_SOURCE_START) / (CHARGE_SOURCE_END - CHARGE_SOURCE_START)
        return CHARGE_START + u * (CHARGE_END - CHARGE_START)
    return value / PLAYBACK_RATE + CHARGE_EXTRA_SECONDS + JOIN_OFFSET


def motion_time(seconds):
    """Animation/effect clock keeps its full speed during the longer buildup."""
    seconds = checked_time(seconds)
    if seconds <= OPENING_END:
        return seconds * OPENING_SOURCE_END / OPENING_END
    return (seconds - JOIN_OFFSET) * PLAYBACK_RATE


def animation_seconds(seconds):
    return motion_time(seconds) / PREVIOUS_PLAYBACK_RATE


def _motion_at_source(t):
    return motion_time(time_for_source(t))


@dataclass(frozen=True)
class Pose:
    donor: int
    animation: int
    frame: float


@dataclass(frozen=True)
class Actor:
    position: tuple
    yaw: float
    roll: float
    pitch: float
    poses: tuple
    blend: float = 0.
    tuck: float = 0.
    charge_fit: float = 0.
    head_pitch: float = 0.
    head_aim: float = 0.
    head_target: tuple = ()
    head_reference: str = 'target'
    lean_back: float = 0.
    lean_gain: float = 0.
    arms_back: float = 0.
    head_glance: float = 0.
    head_elevation: float = 0.


@dataclass(frozen=True)
class Shot:
    name: str
    eye: tuple
    target: tuple
    fov: float
    roll: float = 0.


def _pose_recipe(role, t):
    donor = 0 if role == 'goku' else 29
    startup = 12. if role == 'goku' else 17.
    release = 17. if role == 'goku' else 20.
    flight = Pose(29,332,5.4)
    if t < 3.45:
        return (flight,),0.
    if t < 4.45:
        u = smooth((t-3.45)/1.)
        return (flight,Pose(donor,261,startup*smooth((t-3.6)/.85))),u
    if t < 8.03:
        return (Pose(donor,262,((_motion_at_source(t)-4.45)*24.) % 30.),),0.
    if t < 8.49:
        return (Pose(donor,263,release*(t-8.03)/.46),),0.
    if t < 14.65:
        return (Pose(donor,264,8.+3.*math.sin((t-8.25)*3.)**2),),0.
    if t < 15.45:
        return (Pose(donor,264,8.),Pose(donor,0,10.)),smooth((t-14.65)/.8)
    return (Pose(donor,0,10.+(t-15.45)*18.),),0.


def pose_recipe(role, seconds):
    return _pose_recipe(role, source_time(seconds))


def _flight_path(side):
    # Draft 4's high weaving approach. Its endpoint is adjusted by less than
    # one unit to meet draft 3's exact charge positions, rather than teleport.
    final = (-2.8,49.8,1.0) if side < 0 else (2.5,54.7,-2.2)
    center=(-.15,52.25,-.6)
    def extended(point,offset):
        return tuple(c+(v-c)*FLIGHT_DISTANCE_SCALE+d for c,v,d in zip(center,point,offset))
    # Lengthen the route in proportion to the shot holds, preserving its
    # velocity and the spacing between the fighters rather than slowing it.
    return (extended((-34.,124.,-330.),(side*7.,side*3.,0.)),
            extended((-50.,104.,-215.),(side*7.,0.,0.)),
            extended((44.,70.,-96.),(side*7.,side*3.,0.)),final)


def _angle_lerp(a, b, u):
    return a+((b-a+180.)%360.-180.)*u


def _attacker(role, t):
    side = -1. if role == 'goku' else 1.
    final = (-2.8,49.8,1.0) if side < 0 else (2.5,54.7,-2.2)
    if t < 3.45:
        # Keep the chase, weave and ease-out from draft 4, finishing the stop
        # inside the selected opening instead of carrying over its extra cuts.
        x=max(0.,min(t/OPENING_SOURCE_END,1.))
        u=1.-(1.-x)**1.7
        path=_flight_path(side)
        position=bezier(path,u)
        def heading(w):
            ahead=bezier(path,min(w+.004,1.));behind=bezier(path,max(w-.004,0.))
            delta=tuple(a-b for a,b in zip(ahead,behind))
            return math.degrees(math.atan2(delta[0],delta[2]))
        w=min(u,.985)
        h0,h1=heading(max(w-.03,0.)),heading(min(w+.03,.99))
        turn=_angle_lerp(h0,h1,1.)-h0
        settle=smooth((t-2.75)/.70)
        yaw=_angle_lerp(heading(w),-54.+side*4.,settle)
        roll=max(-38.,min(38.,-turn*2.2))*(1.-settle)+side*8.*settle
        pitch=(10.+6.*math.sin(math.pi*x))*(1.-settle)+12.*settle
    else:
        u=smooth((t-3.45)/1.)
        position=final
        charge_yaw=65. if side<0 else 22.
        yaw=(-54.+side*4.)*(1.-u)+charge_yaw*u
        roll=side*8.*(1.-u);pitch=12.*(1.-u)
        yaw*=1.-smooth((t-8.03)/.46)
    if role=='vegeta':
        yaw+=VEGETA_OUTWARD_TURN*smooth((t-3.45)/1.)*(1.-smooth((t-8.03)/.46))
    hover=.23*math.sin((_motion_at_source(t)-3.45)*2.1+side*.35)*smooth((t-3.45)/.8)
    position=(position[0],position[1]+hover,position[2])
    poses,blend=_pose_recipe(role,t)
    return Actor(position,yaw,roll,pitch,poses,blend,
                 smooth((t-3.45)/1.)*(1.-smooth((t-14.65)/.8)),
                 smooth((t-3.45)/.35)*(1.-smooth((t-8.03)/.46)),
                 -4.*smooth((t-3.36)/.14)*(1.-smooth((t-3.74)/.24)) if role=='vegeta' else 0.,
                 smooth((t-3.85)/.6)*(1.-smooth((t-8.25)/.6)) if role=='vegeta' else 0.,
                 (0.,71.,230.) if role=='vegeta' else (), 'chest' if role=='vegeta' else 'target',
                 VEGETA_LEAN_BACK if role=='vegeta' else 0.,
                 smooth((t-3.45)/1.)*(1.-smooth((t-8.03)/.46)) if role=='vegeta' else 0.,
                 arms_back=VEGETA_ARMS_BACK*(1.-smooth((t-8.03)/VEGETA_ARMS_RELEASE)) if role=='vegeta' else 0.,
                 head_glance=VEGETA_TARGET_GLANCE if role=='vegeta' else 0.,
                 head_elevation=VEGETA_HEAD_ELEVATION if role=='vegeta' else 0.)


def _victim(t):
    seconds=animation_seconds(time_for_source(t))
    if t < 11.9:
        # Active airborne guard and drift even while no attack camera sees him.
        # Settle into the impact anchor continuously; never teleport on the cut.
        drift=1.-smooth((t-11.)/.9)
        pos=(2.0*math.sin(seconds*2.6)*drift,
             53.+.85*math.sin(seconds*3.1)*drift,
             230.+1.2*math.sin(seconds*1.9)*drift)
        focus=lerp(_attacker('goku',t).position,_attacker('vegeta',t).position,.5)
        yaw=180.+math.degrees(math.atan2(pos[0]-focus[0],pos[2]-focus[2]))
        brace=smooth((seconds-.7)/.65)*(.83+.17*math.sin(seconds*4.1)**2)
        brace += (1.-brace)*smooth((seconds-animation_seconds(FIRE))/.7)
        poses=(Pose(133,33,(seconds*30.)%40.),
               Pose(133,145,12.+8.*math.sin(seconds*3.4)**2))
        return Actor(pos,yaw,0.,0.,poses,brace)
    age=t-11.9
    if age < .3:
        guarded=Pose(133,145,12.+8.*math.sin(animation_seconds(IMPACT)*3.4)**2)
        return Actor(VICTIM,180.,0.,0.,(guarded,Pose(133,174,age*12.)),smooth(age/.3))
    fall=smooth((age-1.7)/1.3)
    pos=(0.,53.-smooth((age-1.7)/4.)*68,230.+smooth(age/2.)*12)
    return Actor(pos,180.,0.,0.,(Pose(133,174,min(age*12,20.)),
                 Pose(133,198,max(0.,min((age-1.7)*10,18.)))),fall)


def actor(role, seconds):
    t=source_time(seconds)
    if role=='victim':return _victim(t)
    if role not in AURA_ROLES:raise ValueError('Unknown Blue-pair role')
    return _attacker(role,t)


def shot(seconds):
    real=checked_time(seconds);t=source_time(real)
    if real < OPENING_CUTS[1]:
        p=lerp(_attacker('goku',t).position,_attacker('vegeta',t).position,.5)
        q=lerp(_attacker('goku',min(t+.08,3.45)).position,
               _attacker('vegeta',min(t+.08,3.45)).position,.5)
        delta=tuple(b-a for a,b in zip(p,q));length=math.sqrt(sum(v*v for v in delta)) or 1.
        d=tuple(v/length for v in delta);u=smooth(real/OPENING_CUTS[1])
        eye=(p[0]-d[0]*30.-7.,p[1]-d[1]*30.+13.-3.*u,p[2]-d[2]*30.)
        return Shot('chase from behind and above',eye,
                    (p[0]+d[0]*26.,p[1]+d[1]*26.+1.,p[2]+d[2]*26.),52.,-7.+5.*u)
    if real < OPENING_CUTS[2]:
        u=(real-OPENING_CUTS[1])/(OPENING_CUTS[2]-OPENING_CUTS[1])
        p=lerp(_attacker('goku',t).position,_attacker('vegeta',t).position,.5)
        return Shot('diving overhead bank',(p[0]+5.,p[1]+48.-13.*u,p[2]+20.),
                    (p[0],p[1]+10.,p[2]+4.),45.,-9.+7.*u)
    if real < OPENING_CUTS[3]:
        u=smooth((real-OPENING_CUTS[2])/(OPENING_CUTS[3]-OPENING_CUTS[2]))
        p=lerp(_attacker('goku',t).position,_attacker('vegeta',t).position,.5)
        return Shot('wide over the lava field',lerp((-150.,112.,-40.),(-140.,100.,-20.),u),
                    lerp(p,(0.,56.,10.),.25),46.,2.)
    if real < OPENING_END:
        u=smooth((real-OPENING_CUTS[3])/(OPENING_END-OPENING_CUTS[3]))
        p=lerp(_attacker('goku',t).position,_attacker('vegeta',t).position,.5)
        return Shot('fast side tracking bank',(p[0]+37.-10.*u,p[1]+14.,p[2]+17.-9.*u),
                    (p[0],p[1]+10.,p[2]),44.,8.-12.*u)
    if t < 4.45:
        x=(t-3.45)/1.;u=smooth(x)
        # Follow Vegeta's changing head position through the native braking
        # pose, then arrive on the same face/hand framing as the charge hold.
        target=bezier(((-3.6,63.5,1.5),(-4.5,63.,7.),(5.825,70.5,3.425),(1.9,68.5,-.7)),x)
        offset=lerp((12.5,3.2,18.),(11.7,1.,14.1),u)
        eye=tuple(a+b for a,b in zip(target,offset))
        return Shot('Vegeta charge reveal',eye,target,44.-6.*u,5.-3.5*u)
    if t < 8.03:
        u=(real-CHARGE_START)/(CHARGE_END-CHARGE_START)
        pan=smooth((u-.12)/.76)
        eye=bezier(((13.6,69.5,13.4),(11.1,70.,16.7),(5.,67.,18.5),(1.,65.6,18.)),pan)
        target=bezier(((1.9,68.5,-.7),(2.1,68.4,-.8),(-3.5,64.2,3.),(-4.,64.,2.)),pan)
        return Shot('Vegeta to Goku charging closeup',eye,target,
                    38.+4.*pan,1.5-6.5*pan)
    if t < 8.25:
        u=smooth((t-8.03)/.22)
        return Shot('paired beam release',lerp((1.,65.6,18.),(-5.,66.5,20.),u),
                    lerp((-4.,64.,2.),(-.4,65.,.4),u),42.+10.*u,-5.-u)
    if t < 9.1:
        u=smooth((t-8.25)/.85)
        return Shot('explosive beam pullback',lerp((-5.,66.5,20.),(17.,71.,57.),u),
                    lerp((-.4,65.,.4),(0.,65.,8.),u),52.+10.*u,-6.+3.*u)
    if t < 10.55:
        u=smooth((t-9.1)/1.45)
        head=8.+(t-8.25)*222./3.65
        return Shot('racing the combined beam',(19.+5.*u,72.+6.*u,head+27.),
                    (0.,69.,head-26.),49.,-3.-7.*u)
    if t < 11.9:
        u=smooth((t-10.55)/1.35)
        return Shot('victim braces',lerp((22.,76.,180.),(12.,75.,187.),u),
                    (0.,71.,230.),50.,2.-3.*u)
    if t < 14.65:
        u=smooth((t-11.9)/2.75)
        tremor=.23*math.sin((real-JOIN_OFFSET)*71.)*(1.-u)
        eye=lerp((43.,78.,267.),(68.,87.,294.),u)
        return Shot('impact and white bloom',(eye[0]+tremor,eye[1],eye[2]),
                    (0.,72.,233.),54.,-3.*(1.-u))
    u=smooth((t-14.65)/(AUTHORED_DURATION-14.65))
    return Shot('wide aftermath',lerp((90.,88.,300.),(112.,94.,332.),u),
                lerp((0.,57.,130.),(0.,39.,151.),u),52.,0.)


def observer_shot(seconds):
    checked_time(seconds)
    return Shot('bystander view',(102.,81.,286.),(0.,65.,210.),54.,0.)


def cues(seconds):
    t=source_time(seconds)
    return dict(charge=smooth((t-4.2)/3.6) if t<8.25 else 0.,
                fire=smooth((t-8.25)/.16)*(1.-smooth((t-13.5)/1.1)) if t>=8.25 else 0.,
                beam_head=min(230.,8.+max(0.,t-8.25)*(222./3.65)),
                impact=smooth((t-11.9)/.3)*(1.-smooth((t-14.4)/1.6)),
                white=.80*math.sin(math.pi*smooth((t-13.65)/1.1))**2
                      if 13.65<t<14.75 else 0.,
                green_blasts=1.-smooth((t-3.2)/.25) if t<3.45 else 0.,
                dash_aura=1.)


SHOT_LIST = ((0.,'chase from behind and above'),(OPENING_CUTS[1],'diving overhead bank'),
             (OPENING_CUTS[2],'wide over the lava field'),(OPENING_CUTS[3],'fast side tracking bank'),
             (OPENING_END,'Vegeta charge reveal'),
             (CHARGE_START,'Vegeta to Goku charging closeup'),
             (CHARGE_END,'paired beam release'),(FIRE,'explosive beam pullback'),
             (time_for_source(9.1),'racing the combined beam'),
             (time_for_source(10.55),'victim braces'),
             (IMPACT,'impact and white bloom'),(RECOVERY,'wide aftermath'))
