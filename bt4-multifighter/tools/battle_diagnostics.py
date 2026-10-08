"""Bounded read-only battle history for camera failures and logic soft locks.

The render watchdog cannot see a lock while music/animations keep playing.
Keep the last half-minute of ownership, actions and stop flags without saving
a state, pausing, or modifying guest memory. A diagnostic failure is nonfatal.
"""
from native_map import A
from collections import deque
import struct
import time

from atomic_files import write_json
import cinematic_policy as cinematic
import fresh_team_combat as core
import native_preparation as preparation
import special_camera_arbitration as arbitration


def snapshot(p):
    u=p.read_u32
    def words(at,n):return list(struct.unpack('<'+'I'*n,p.read(at,n*4)))
    def valid(at,size):return at%4==0 and 0x100000<=at<=0x8000000-size
    mode=words(core.MODE,4);manager=u(core.ACTORS)
    if mode[0]!=1 or not 2<=mode[1]<=12 or mode[2:]!=[manager,mode[1]] or not valid(manager,632):return None
    battle=u(cinematic.team_intro.BATTLE)
    if not valid(battle,4) or u(battle)!=3:return None
    camera=u(A(0x304270-22180));director=u(arbitration.DIRECTOR)
    result=dict(manager=manager,count=mode[1],scene_flags=u(cinematic.continuity.SCENE_FLAGS),
                manager_hold=u(manager+628),alias=words(core.PAIR,8),
                preparation=words(preparation.CONTROL,16),policy=words(cinematic.CONTROL,24),
                pause=words(cinematic.pause.CONTROL,16),arbitration=words(arbitration.CONTROL,16),
                subjects=words(cinematic.fresh.SUCCESSOR_CONTROL+8,2),
                camera_address=camera,camera=words(camera+704,32) if valid(camera,832) else [],
                director_address=director,director=words(director,8) if valid(director,32) else [],actors=[])
    for physical,actor in enumerate(words(core.POINTERS,mode[1])):
        if not valid(actor,0x1600):return None
        # Read each actor once so transient action fields stay from one sample.
        data=p.read(actor,0x1600);v=lambda off:struct.unpack_from('<I',data,off)[0]
        if v(0)!=physical or v(12)>=12:return None
        model=u(core.MODELS+4*v(12));row=0x9A4+164*min(v(0x994),4)
        item=dict(physical=physical,address=actor,controller=v(4),team=v(8),model_id=v(12),
                  actions=[v(off) for off in range(2376,2404,4)],health=v(row+64),character=v(row),
                  flags=data[0x1080:0x10D8].hex(),stops=[v(off) for off in range(4896,4912,4)],
                  pair=[v(3732),v(3736)],input=[v(off) for off in range(0x1278,0x1288,4)],
                  position=list(struct.unpack_from('<4f',data,16)),model=model)
        if valid(model,0x1670):
            item['model_header']=words(model,6)
            item['model_tracks']=words(model+0x908,3)
            item['model_root']=words(model+2416,4)
        result['actors'].append(item)
    # Never attribute samples across a match transition to the old manager.
    if u(core.ACTORS)!=manager or words(core.MODE,4)!=mode:return None
    return result


def presenting(value):
    """Is the game showing an authored presentation, or holding for one?

    These frames are the ones worth keeping: a plain thirty-second window
    rolls past a cutscene long before anyone can describe what went wrong.
    """
    camera=value['camera']
    if camera and (camera[27] or (camera[0] and camera[18]&3==1)):return True
    policy=value['policy']
    # force-all, shared-stop record, published kind/members, latched owner.
    if any(policy[index] for index in (8,13,14,15,17)):return True
    for actor in value['actors']:
        action=actor['actions'][0]
        if 236<=action<=243 or action==261 or 262<=action<316 and (action-262)%3==2:return True
        if actor['stops'][0]:return True
    return False


class Recorder:
    def __init__(self):
        self.samples=deque(maxlen=30);self.presentations=deque(maxlen=60)
        self.next_sample=0.;self.next_write=0.;self.identity=None

    def tick(self,p,path,clock=time.monotonic):
        now=clock()
        if now<self.next_sample:return
        self.next_sample=now+1.
        try:
            value=snapshot(p)
            if value is None:return
            identity=(value['manager'],value['count'],tuple(a['address'] for a in value['actors']))
            if identity!=self.identity:
                self.samples.clear();self.presentations.clear();self.identity=identity
            value['time']=time.time();self.samples.append(value)
            # Keep every presentation frame, and look twice a second while
            # one lasts, so a whole cutscene survives in its own history.
            if presenting(value):
                self.presentations.append(value);self.next_sample=now+.5
            if now>=self.next_write:
                # An external reader must not stall reload/input servicing
                # while holding this optional log open on Windows.
                write_json(path,dict(format=2,read_only=True,samples=list(self.samples),
                                     presentations=list(self.presentations)),timeout=0)
                self.next_write=now+2.
        except Exception:
            # Telemetry must never turn a playable match into preparation failure.
            return
