"""Guest director ownership, clocks, cleanup and ABI checks; no emulator."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import math
import struct
import unittest
from unittest.mock import patch
import tag_rush_scene as scene
import tag_team_rush as tag
import tag_rush_assets as assets
import tag_rush_camera as camera
import tag_rush_safety as safety
import tag_rush_effects as effects
import tag_rush_audio as audio
import tag_rush_pause as active_pause
import arena_bounds
import giant_options as giants
from test_tag_rush_safety import SafetyCpu, ACTOR, MODEL, control
from test_tag_rush_camera import run, RENDERER, ORDINARY, AUTHORED
from test_extra_special_pools import Cpu as FullCpu


class SceneCpu(FullCpu):
    def extra_instruction(self,ins,pc):
        op,rs,rt,rd,fn=ins>>26,(ins>>21)&31,(ins>>16)&31,(ins>>11)&31,ins&63
        if op==0 and fn==6:self.r[rd]=(self.r[rt]&0xFFFFFFFF)>>(self.r[rs]&31);return
        if op==0 and fn==0x27:self.r[rd]=~(self.r[rs]|self.r[rt])&0xFFFFFFFF;return
        if op==17 and rs==2:self.r[rt]=int(self.condition)<<23;return
        if op==17 and rs==6:self.condition=bool(self.r[rt]&(1<<23));return
        if op==17 and rs==16 and fn==4:self.set_number((ins>>6)&31,math.sqrt(self.number(rd)));return
        if op==0 and fn==25:
            value=(self.r[rs]&0xFFFFFFFF)*(self.r[rt]&0xFFFFFFFF);self.lo=value&0xFFFFFFFF;self.hi=value>>32;return
        if op==0 and fn==27:
            self.lo,self.hi=divmod(self.r[rs]&0xFFFFFFFF,self.r[rt]&0xFFFFFFFF);return
        if ins>>26==17 and (ins>>21)&31==20 and ins&63==32:
            raw=self.f[(ins>>11)&31];self.set_number((ins>>6)&31,raw if raw<0x80000000 else raw-0x100000000);return
        return super().extra_instruction(ins,pc)


def fixture(ki=(True,True), hz=30, adversarial=True):
    with patch.object(scene,'ACTOR_HZ',hz):blocks=scene.pieces()
    c=SceneCpu({'segments':[dict(address=p,data_hex=b.hex()) for p,b in blocks]})
    control(c,active=0,count=4);c.w(tag.CONTROL+tag.C['ready'],1)
    c.w(c.r[28]-22172,RENDERER);c.w(c.r[28]-22176,ORDINARY);c.w(c.r[28]-22180,AUTHORED)
    c.w(RENDERER+0xC40,ORDINARY+16)
    c.w(tag.CONTROL+tag.C['scene_table'],scene.TABLE);c.w(tag.CONTROL+tag.C['damage'],15000)
    c.calls=[];c.frames=[];c.placements=[];c.actors=[];c.models=[];c.damage=[];c.marker=[]
    c.beams=[];c.explosions=[];c.fx_updates=0;c.stop_remaining=0;c.idle_starts=[]
    c.write(effects.CONTROL,struct.pack('<8I',effects.MAGIC,c.u(tag.CONTROL+4),4,1,0,0,0,2))
    for role in (0,1):c.w(effects.ROWS+role*effects.STRIDE+effects.R['prepared'],effects.PREPARED)
    c.w(scene.ADMISSION,0x3100000);c.w(scene.ADMISSION+4,256)
    c.w(scene.STAGING,0x3110000)
    for variant in range(4):
        for phase in range(5):c.write(0x3110000+variant*80+phase*16,struct.pack('<4f',0,-160 if phase<4 else 0,0,0))
    stage,bounds=0x3120000,0x3120100
    c.w(arena_bounds.STAGE,stage);c.w(stage+64,bounds);c.write(bounds,struct.pack('<3f',1000,-1000,1000))
    for index in range(4):
        actor=ACTOR+index*0x2000;model=MODEL+index*0x2000;c.actors.append(actor);c.models.append(model)
        c.w(tag.core.POINTERS+index*4,actor);c.w(tag.core.MODELS+index*4,model)
        c.w(actor,index);c.w(actor+12,index);c.w(actor+0x994,0);c.w(actor+0x9E4,30000);c.w(actor+2376,43)
        for off in (2380,2388,2392,2396,2400):c.w(actor+off,-1)
        c.w(model+4,1);c.w(model+8,1);c.w(model+12,index);c.w(model+16,index)
        c.w(model+64,0x3180000+index*0x1000);c.w(model+192,0x3200000+index*0x1000)
        c.w(model+5728,0x3300000+index*0x20000);c.w(c.u(model+5728)+98344,7)
        c.w(model+2348,0x3900000+index*0x1000)
        for own_clip in (264,332,364):
            pointer=0x3A00000+index*0x2000+own_clip*4
            c.w(model+192+own_clip*4,pointer);c.w(pointer,256)
        c.w(model+2332,0x3500000+index*0x100);c.fw(c.u(model+2332)+4,.83 if index==2 else .9)
        c.fw(model+2592,1.0)
        c.w(model+2880,0x3400000+index*0x10000)
        c.write(model+2384,struct.pack('<4f',100+60*index,-10,30+20*index,1))
        c.write(actor+16,c.read(model+2384,16))
        c.write(model+2400,struct.pack('<4f',0,.7,0,1))
        c.fw(model+3200,1);c.w(actor+2420,37)
        for bone in (2,3,17,31,45,52):
            point=0x3800000+index*0x1000+bone*0x80;c.w(model+3436+4*bone,point)
            x,y,z,_=struct.unpack('<4f',c.read(model+2384,16));c.write(point+64,struct.pack('<4f',x,y-30,z,1))
        c.write(0x3100000+index,bytes([1+2*int(ki[index//2] if index in (0,2) else True)]))
        c.w(tag.METERS+index*32,750);c.w(tag.METERS+index*32+4,index);c.w(tag.METERS+index*32+12,99)
    clips=[0x06D20000+index*0x1000 for index in range(3)]
    for clip in clips:c.write(clip,struct.pack('<2I',512,300))
    donors=0x06D25000;c.write(donors,struct.pack('<3I',0x06D26000,0x06D28000,0x06D26000))
    for model,height in ((0x06D26000,.9),(0x06D28000,.83)):
        c.w(model+2332,model+0xA00);c.fw(model+0xA04,height)
    for variant in range(4):
        base=assets.BASE+variant*0x200;c.w(scene.TABLE+8*variant,base);c.w(scene.TABLE+8*variant+4,5)
        for phase in range(5):
            duration=(68,99,149,119,40 if variant==1 else 262)[phase]
            ends=[duration]*3
            if phase==4 and variant in (2,3):ends[1 if variant==2 else 0]=80
            roles=(clips[0],clips[1] if phase>=2 else 0,clips[2])
            flags=(assets.FINISHER|(6 if variant==0 else 0 if variant==1 else 2 if variant==2 else 4)) if phase==4 else 0
            c.write(base+phase*64,struct.pack('<16I',duration,*roles,0,0,0,flags,352+phase,414+phase,357+phase,*ends,60,donors))
    def clobber(m):
        if adversarial:
            for reg in (*range(8,16),24,25):m.r[reg]=0xABCD0000+reg
            for reg in range(20):m.set_number(reg,1000.+reg)
            m.hi=0xAABB;m.lo=0xCCDD
    def callback(address,fn):
        def wrapper(m):
            m.calls.append((address,tuple(m.r[4:9])));fn(m);clobber(m)
        c.callbacks[address]=wrapper
    callback(tag.GATE,lambda m:m.r.__setitem__(2,1))
    callback(safety.PREFLIGHT,lambda m:m.r.__setitem__(2,1))
    callback(safety.FLOOR,lambda m:m.r.__setitem__(2,0))
    callback(camera.INIT,lambda m:m.r.__setitem__(2,1))
    callback(camera.UPDATE,lambda m:None)
    callback(audio.RESET,lambda m:None)
    callback(audio.TICK,lambda m:None)
    def spawn(m):m.beams.append((m.r[4],m.r[5]));m.r[2]=1
    callback(effects.SPAWN,spawn)
    callback(effects.EXPLOSION,lambda m:m.explosions.append((m.r[4],m.r[5],m.u(scene.STATE+scene.S['phase']),m.u(scene.STATE+scene.S['ticks']))))
    callback(effects.UPDATE,lambda m:setattr(m,'fx_updates',m.fx_updates+1))
    callback(effects.STOP,lambda m:m.r.__setitem__(2,m.stop_remaining))
    callback(scene.A(0x1C4650),lambda m:m.r.__setitem__(2,0x80000040))
    callback(scene.A(0x23E6A0),lambda m:m.w(m.r[28]-22176,m.r[4]))
    callback(scene.A(0x1E0290),lambda m:m.w(m.r[4]+2380,m.r[5]))
    def idle(m):
        actor=m.r[4];requested=m.u(actor+2380)
        if requested!=0xFFFFFFFF:m.w(actor+2376,requested)
        m.w(actor+2380,-1);m.w(actor+2420,198 if m.u(actor+2376)==217 else 0)
        if m.u(actor+2376)==217:
            model=m.models[m.u(actor+12)];m.w(model+2880,m.u(model+192)+0x80);m.fw(model+3192,0.)
            m.fw(model+3200,1.)
            m.w(actor+0x1000,4 if m.u(actor+164*m.u(actor+0x994)+0xA0C) else 0)
    callback(scene.A(0x1E23D0),idle)
    def decode(m):
        model=m.r[4];m.marker.append(m.u(m.u(model+5728)+98344));m.fw(model+3192,0)
    callback(scene.A(0x24D038),decode)
    callback(scene.A(0x24BBE8),lambda m:None)
    callback(scene.A(0x24C958),lambda m:m.frames.append((m.r[4],m.fr(m.r[4]+3192))))
    callback(scene.A(0x24E2B0),lambda m:None)
    def set_root(m):
        actor=m.r[4];model=m.models[m.u(actor+12)]
        m.write(actor+16,m.read(m.r[5],16));m.write(actor+32,m.read(m.r[6],16))
        m.write(model+2384,m.read(m.r[5],16));m.write(model+2400,m.read(m.r[6],16))
    callback(scene.A(0x1D7418),set_root)
    def bone(m):m.write(m.r[6],m.read(m.u(m.models[m.r[4]]+3436+4*m.r[5])+64,16))
    callback(scene.A(0x2058E0),bone)
    callback(scene.A(0x1DAC78),lambda m:m.r.__setitem__(2,0))
    callback(scene.A(0x1DC298),lambda m:m.r.__setitem__(2,m.r[4]+16))
    def root_pose(m):m.write(m.models[m.u(m.r[4]+12)]+2384,m.read(m.r[4]+16,16))
    callback(scene.A(0x1D7198),root_pose)
    callback(scene.A(0x1D70E8),lambda m:None)
    callback(scene.A(0x1DABE8),lambda m:None)
    def pose(m):
        model=m.r[4];x,y,z,_=struct.unpack('<4f',m.read(model+2384,16))
        row=(0 if model==m.models[0] else 1 if model==m.models[2] else 2)
        frame=m.fr(model+3192);x+=(-30,30,0)[row];z+=frame*.1
        for bone in (2,3,17,31,45,52):
            point=(x+25,y-15,z+80,1) if bone==52 else (x,y-30,z,1)
            m.write(m.u(model+3436+bone*4)+64,struct.pack('<4f',*point))
    callback(scene.A(0x24E3F8),pose)
    def own_pose(m):
        model=m.models[m.u(m.r[4]+12)];m.fw(model+3192,0);m.fw(model+3200,1)
        m.idle_starts.append((m.r[4],m.r[5],m.number(12)))
        m.fw(model+2884,30.);m.fw(model+3204,1. if m.number(12)>0 else 0.)
        m.w(m.r[4]+2420,m.r[5]);m.w(model+2880,m.u(model+192)+0x80)
    callback(scene.A(0x1C3E60),own_pose)
    def idle_loop(m):
        model=m.models[m.u(m.r[4]+12)];previous=m.fr(model+3192)
        m.fw(model+3196,previous);m.fw(model+3192,(previous+m.fr(model+3200))%m.fr(model+2884))
        m.fw(model+3204,max(0.,m.fr(model+3204)-m.fr(model+3208)))
    callback(scene.A(0x1C4920),idle_loop)
    def place(m):
        assert m.u(tag.CONTROL+16)==1
        m.placements.append((m.r[4],struct.unpack('<4f',m.read(m.r[5],16))))
        model=m.models[m.u(m.r[4]+12)];m.write(model+2384,m.read(m.r[5],16));m.r[2]=1
    callback(safety.PLACE,place)
    def damage(m):
        assert m.u(tag.CONTROL+16)==1
        hp=m.r[4]+164*m.u(m.r[4]+0x994)+0x9E4
        m.damage.append(tuple(m.r[4:7]));m.w(hp,max(0,m.u(hp)-m.r[5]));m.r[2]=1
    callback(safety.DAMAGE,damage)
    return c


def start(c):c.r[4:7]=[0,2,1];run(c,scene.START)


def reach_beam_event(c,hz=30):
    while c.u(scene.STATE+scene.S['phase'])<4:run(c,scene.STEP)
    run(c,scene.STEP)
    while c.u(scene.STATE+scene.S['ticks'])*60<160*hz:run(c,scene.STEP)


class SceneTests(unittest.TestCase):
    def test_start_final_preflight_rejects_giant_in_any_role_before_mutation(self):
        import team_participation as participation
        for index in (0,2,1):
            for enabled in (0,1):
                c=fixture();c.write(safety.PREFLIGHT,safety.preflight_code());del c.callbacks[safety.PREFLIGHT]
                c.w(participation.CONTROL+12,15)
                c.write(giants.CONTROL,struct.pack('<4If',giants.MAGIC,c.u(tag.CONTROL+4),4,enabled,2.0))
                c.write(c.u(c.models[index]+2332)+2,b'\x04')
                before=[(c.read(a,0x1600),c.read(m,0x1700)) for a,m in zip(c.actors,c.models)]
                start(c);self.assertEqual(c.r[2],0);self.assertEqual(c.u(tag.CONTROL+16),0)
                self.assertEqual([c.u(tag.METERS+32*i) for i in range(4)],[750]*4)
                self.assertEqual(before,[(c.read(a,0x1600),c.read(m,0x1700)) for a,m in zip(c.actors,c.models)])
        c=fixture();c.write(safety.PREFLIGHT,safety.preflight_code());del c.callbacks[safety.PREFLIGHT]
        c.w(participation.CONTROL+12,15);start(c);self.assertEqual(c.r[2],1)

    def test_start_captures_before_cleanup_and_spends_no_meter(self):
        c=fixture();oldclips=[c.u(m+192) for m in c.models];start(c)
        self.assertEqual(c.r[2],1);self.assertEqual(c.u(tag.CONTROL+16),1)
        self.assertEqual(c.u(tag.CONTROL+tag.C['start_requests']),1)
        self.assertEqual(c.u(tag.CONTROL+20),7);self.assertEqual(c.u(tag.CONTROL+44),0)
        self.assertEqual([c.u(tag.METERS+32*i) for i in range(4)],[750]*4)
        self.assertEqual([c.u(tag.METERS+32*i+4) for i in range(4)],[0xFFFFFFFF]*4)
        self.assertEqual([c.u(scene.ROWS+i*scene.STRIDE+scene.R['clip0']) for i in range(3)],[oldclips[i] for i in (0,2,1)])
        self.assertEqual(c.marker,[0,0]);self.assertTrue(all(c.u(c.u(m+5728)+98344)==7 for m in c.models))
        # The partner retains its own spot until the authored entrance.
        self.assertEqual(c.fr(c.models[2]+2384),220.)
        self.assertEqual(c.fr(c.models[0]+2384),160.)

    def test_unsupported_changed_or_invalid_data_refuses_without_actor_mutation(self):
        for bad in ('flags','scratch','bone','clip','donor','phase','count','camera','cramped','fx_ready','fx_receipt'):
            c=fixture()
            if bad=='flags':c.write(0x3100000,b'\0')
            elif bad=='scratch':c.w(c.models[2]+5728,0)
            elif bad=='bone':c.w(c.models[1]+3436+17*4,0)
            elif bad=='clip':c.w(assets.BASE+4,0)
            elif bad=='donor':c.w(assets.BASE+60,0)
            elif bad=='phase':c.w(assets.BASE+64*3+56,50)
            elif bad=='count':c.w(scene.TABLE+4,0)
            elif bad=='camera':c.callbacks[camera.INIT]=lambda m:m.r.__setitem__(2,0)
            elif bad=='fx_ready':c.w(effects.CONTROL+effects.C['ready'],0)
            elif bad=='fx_receipt':c.w(effects.ROWS+effects.STRIDE+effects.R['prepared'],0)
            else:c.write(0x3120100,struct.pack('<3f',1000,-100,100))
            before=[(c.read(a,0x1600),c.read(m,0x1700)) for a,m in zip(c.actors,c.models)]
            start(c);self.assertEqual(c.r[2],0,bad);self.assertEqual(c.u(tag.CONTROL+16),0,bad)
            self.assertEqual(before,[(c.read(a,0x1600),c.read(m,0x1700)) for a,m in zip(c.actors,c.models)],bad)

    def test_both_actual_beam_hands_must_be_present_and_finite_before_start(self):
        for index in (0,2):
            for bone in (31,45):
                for invalid in ('missing','nan'):
                    c=fixture();node=c.u(c.models[index]+3436+bone*4)
                    if invalid=='missing':c.w(c.models[index]+3436+bone*4,0)
                    else:c.fw(node+68,float('nan'))
                    before=[(c.read(a,0x1600),c.read(m,0x1700)) for a,m in zip(c.actors,c.models)]
                    start(c);self.assertEqual(c.r[2],0,(index,bone,invalid))
                    self.assertEqual(c.u(tag.CONTROL+tag.C['active']),0)
                    self.assertEqual(c.idle_starts,[]);self.assertEqual(c.beams,[])
                    self.assertEqual(before,[(c.read(a,0x1600),c.read(m,0x1700)) for a,m in zip(c.actors,c.models)])

    def test_transformed_current_character_uses_fresh_admission_flags(self):
        c=fixture();c.w(c.models[2]+12,90);c.write(0x3100000+90,b'\x01');start(c)
        self.assertEqual(c.r[2],1);self.assertEqual(c.u(tag.CONTROL+44),2)
        self.assertEqual(c.u(scene.ROWS+scene.STRIDE+scene.R['character']),90)

    def test_borrowed_phases_do_not_freeze_an_inherited_idle_blend(self):
        c=fixture();seen=[]
        for model in c.models:
            for off,value in ((3204,5/9),(3208,2/9),(3212,.25)):c.fw(model+off,value)
        previous=c.callbacks[scene.A(0x24C958)]
        def pose(m):
            model=m.r[4]
            for role in range(3):
                row=scene.ROWS+role*scene.STRIDE
                if m.u(row+scene.R['model'])==model and m.u(row+scene.R['borrowed']):
                    seen.append((role,m.u(scene.STATE+scene.S['phase'])))
                    self.assertEqual([m.fr(model+off) for off in (3204,3208,3212)],[0.]*3)
            previous(m)
        c.callbacks[scene.A(0x24C958)]=pose
        start(c);self.assertEqual(c.r[2],1)
        while c.u(scene.STATE+scene.S['phase'])<4:run(c,scene.STEP)
        run(c,scene.STEP)
        self.assertEqual(set(seen),{(role,phase) for phase in range(5)
                                   for role in range(3) if role!=1 or phase>=2})

    def test_common_anchor_clamps_once_and_keeps_authored_roles_together(self):
        c=fixture();c.fw(c.models[1]+2384,950);c.fw(c.models[1]+2392,0)
        start(c);self.assertEqual(c.r[2],1)
        self.assertAlmostEqual(c.fr(scene.STATE+scene.S['origin']),750.)
        # Victim follows the authored contact bone, not the attacker's root.
        self.assertEqual(c.read(c.u(c.models[0]+3436+4*52)+64,16),c.read(c.u(c.models[1]+3436+4*3)+64,16))
        self.assertEqual(c.fr(c.models[2]+2384),220.)
        # The real teammate moves into the shared choreography only when its
        # first authored partner clip arrives; it does not disappear meanwhile.
        while c.u(scene.STATE+scene.S['phase'])<2:run(c,scene.STEP)
        run(c,scene.STEP)
        self.assertEqual(c.read(c.models[2]+2384,32),c.read(c.models[0]+2384,32))

    def test_mixed_finisher_blends_non_ki_role_into_its_own_moving_idle(self):
        for hz in (30,25):
            for ki,nonki,role in (((True,False),2,1),((False,True),0,0)):
                c=fixture(ki,hz);start(c)
                while c.u(scene.STATE+scene.S['phase'])<4:run(c,scene.STEP)
                row=scene.ROWS+role*scene.STRIDE;model=c.models[nonki]
                while not c.u(row+scene.R['recovering']):
                    previous=c.fr(model+3192);run(c,scene.STEP)
                self.assertAlmostEqual(previous,80.)
                self.assertEqual(c.u(scene.STATE+scene.S['ticks']),math.ceil(80*hz/60)+1)
                own=[x for x in c.idle_starts if x[0]==c.actors[nonki]]
                self.assertEqual(len(own),1);self.assertAlmostEqual(own[0][2],.2)
                self.assertEqual(c.u(model+192),c.u(row+scene.R['clip0']))
                self.assertEqual(c.u(model+2880),c.u(model+192)+0x80)
                self.assertEqual(c.u(tag.CONTROL+16),1);self.assertEqual(c.u(tag.CONTROL+20),7)
                anchor=c.read(row+scene.R['recovery_anchor'],12);target_root=c.read(c.models[1]+2384,12)
                c.frames.clear()
                for _ in range(20):
                    run(c,scene.STEP)
                    for actual,expected in zip(struct.unpack('<3f',c.read(c.u(model+3436+8)+64,12)),struct.unpack('<3f',anchor)):
                        self.assertAlmostEqual(actual,expected,places=4)
                    self.assertEqual(c.read(c.models[1]+2384,12),target_root)
                values=[frame for at,frame in c.frames if at==model]
                self.assertGreater(len(set(values)),5);self.assertTrue(all(0<=v<30 for v in values))
                self.assertEqual(len([x for x in c.idle_starts if x[0]==c.actors[nonki]]),1)
                self.assertAlmostEqual(c.fr(model+3204),0.)

    def test_wasteland_root_clearance_allows_grounded_start_without_bypassing_floor(self):
        c=fixture();c.write(0x3120100,struct.pack('<3f',1200,-350,1000))
        c.fw(c.models[1]+2388,0.)
        c.fw(c.u(c.models[0]+2332)+4,1.)
        # Execute the real recovery/terrain admission. Only the native mesh
        # query is substituted with the flat floor seen in the live capture.
        from beam_struggle import floor_code
        code=tag.core.rebound(floor_code,FLOOR=safety.FLOOR,QUERY=safety.QUERY)()
        c.write(safety.FLOOR,code);del c.callbacks[safety.FLOOR]
        queries=[]
        def ground(m):queries.append(m.number(12));m.set_number(0,0.);m.r[2]=1
        c.callbacks[safety.QUERY]=ground
        start(c);self.assertEqual(c.r[2],1);self.assertTrue(queries)
        origin=c.fr(scene.STATE+scene.S['origin']+4)
        ratio=c.fr(scene.STATE+scene.S['height_scale'])
        self.assertAlmostEqual(origin,-40.*ratio,places=4)
        for offset in assets.NATIVE_STAGING:
            self.assertGreaterEqual(origin+offset[1]*ratio,-350.)
            self.assertLess(origin+offset[1]*ratio,0.)
        self.assertEqual(c.u(tag.CONTROL+tag.C['start_requests']),1)

    def test_recovery_cancellation_restores_control_and_resets_for_next_scene(self):
        c=fixture((False,True));start(c)
        row=scene.ROWS
        while not c.u(row+scene.R['recovering']):run(c,scene.STEP)
        c.r[4]=1;run(c,scene.FINISH)
        self.assertEqual(c.u(tag.CONTROL+16),0);self.assertEqual(c.u(tag.CONTROL+20),0)
        self.assertEqual(c.damage,[]);self.assertEqual(len(c.placements),3)
        for index in (0,1,2):
            self.assertEqual(c.u(c.models[index]+192),0x3200000+index*0x1000)
            self.assertEqual(c.fr(c.models[index]+3204),0.)
        start(c);self.assertEqual(c.r[2],1)
        self.assertEqual(c.u(row+scene.R['recovering']),0)
        self.assertNotEqual(c.u(c.models[0]+192),c.u(row+scene.R['clip0']))

    def test_recovery_code_reservation_does_not_overlap_audio_or_safety(self):
        blocks=dict(scene.pieces())
        self.assertLessEqual(audio.END,scene.RECOVERY)
        self.assertLessEqual(scene.RECOVERY+len(blocks[scene.RECOVERY]),scene.RECOVERY_END)
        self.assertLessEqual(scene.RECOVERY_END,safety.STATE)

    def test_canonical_giant_clearance_uses_live_height_and_temporary_scale(self):
        c=fixture();model=c.models[0];parameters=c.u(model+2332)
        c.write(parameters+2,b'\x04');c.fw(parameters+4,1.8)
        c.write(giants.CONTROL,struct.pack('<4If',giants.MAGIC,c.u(tag.CONTROL+4),4,1,2.0))
        c.fw(c.models[1]+2384,950);c.fw(c.models[1]+2392,0)
        before=c.read(giants.CONTROL,20),c.read(parameters,12),c.read(model+2592,4)
        start(c);self.assertEqual(c.r[2],1)
        self.assertAlmostEqual(c.fr(scene.STATE+scene.S['origin']),500.,places=4)
        # Fourfold height reserves authored roots (160 staging +40 clearance),
        # not a full-body envelope. Giants still fail the real START preflight.
        self.assertAlmostEqual(c.fr(scene.STATE+scene.S['origin']+4),-170.,places=3)
        self.assertEqual(before,(c.read(giants.CONTROL,20),c.read(parameters,12),c.read(model+2592,4)))

    def test_disabled_stale_and_non_giant_options_do_not_scale_clearance(self):
        for change in ('disabled','manager','count','class'):
            c=fixture();parameters=c.u(c.models[0]+2332);c.write(parameters+2,b'\x04')
            c.write(giants.CONTROL,struct.pack('<4If',giants.MAGIC,c.u(tag.CONTROL+4),4,1,3.0))
            if change=='disabled':c.w(giants.CONTROL+12,0)
            elif change=='manager':c.w(giants.CONTROL+4,0)
            elif change=='count':c.w(giants.CONTROL+8,6)
            else:c.write(parameters+2,b'\0')
            c.fw(c.models[1]+2384,950);c.fw(c.models[1]+2392,0);start(c)
            self.assertEqual(c.r[2],1,change);self.assertAlmostEqual(c.fr(scene.STATE+scene.S['origin']),750.,places=4)

    def test_oversized_or_nonfinite_scale_and_too_low_terrain_decline_cleanly(self):
        for change in ('huge','nan','short_ceiling','buried_ceiling'):
            c=fixture()
            if change=='huge':c.fw(c.models[0]+2592,100.)
            elif change=='nan':c.fw(c.models[0]+2592,float('nan'))
            elif change=='short_ceiling':
                c.fw(c.u(c.models[0]+2332)+4,9.);c.write(0x3120100,struct.pack('<3f',1000,-500,500))
            else:
                def floor(m):m.fw(m.r[4]+12,-990);m.r[2]=1
                c.callbacks[safety.FLOOR]=floor
            before=[(c.read(a,0x1600),c.read(m,0x1700)) for a,m in zip(c.actors,c.models)]
            start(c);self.assertEqual(c.r[2],0,change)
            self.assertEqual(before,[(c.read(a,0x1600),c.read(m,0x1700)) for a,m in zip(c.actors,c.models)])

    def test_all_variants_and_pal_finish_on_their_deterministic_clocks(self):
        for hz in (30,25):
            for ki,variant in (((True,True),0),((False,False),1),((True,False),2),((False,True),3)):
                c=fixture(ki,hz);start(c);self.assertEqual(c.u(tag.CONTROL+44),variant)
                ticks=1
                while c.u(tag.CONTROL+16) and ticks<500:
                    run(c,scene.STEP);ticks+=1
                expected=sum(math.ceil(n*hz/60) for n in (68,99,149,119,40 if variant==1 else 262))+1
                self.assertEqual(ticks,expected,(hz,variant));self.assertEqual(c.u(tag.CONTROL+16),0)
                self.assertEqual(c.damage,[(c.actors[1],15000,scene.damage_schedule.FINAL_FLAGS)])
                self.assertEqual(c.u(tag.CONTROL+84),1);self.assertEqual(len(c.placements),3)
                roles=() if variant==1 else (0,1) if variant==0 else (0,) if variant==2 else (1,)
                self.assertEqual(c.beams,[(role,math.ceil(102*hz/60)) for role in roles])
                for i in (0,1,2):
                    self.assertEqual(c.u(c.models[i]+192),0x3200000+i*0x1000)
                    self.assertEqual(c.u(c.models[i]+2880),c.u(c.models[i]+192)+0x80)
                    self.assertEqual(c.fr(c.models[i]+3200),1)
                # Private framing points at the current posed group every tick.
                self.assertTrue(math.isfinite(c.fr(camera.CAMERA+720)))
                self.assertGreater(c.fr(camera.CAMERA+728),c.fr(scene.STATE+scene.S['focus']+8))

    def test_cancel_restores_valid_cast_without_damage_or_stale_world_writes(self):
        c=fixture();start(c);c.w(c.actors[1]+0x9E4,0);run(c,scene.STEP)
        self.assertEqual(c.u(tag.CONTROL+16),0);self.assertEqual(c.damage,[])
        self.assertEqual(c.u(tag.CONTROL+88),1)
        c=fixture();start(c);c.w(c.r[28]-22364,0x2000000)
        before=[c.read(m,0x1700) for m in c.models];run(c,scene.STEP)
        self.assertEqual(before,[c.read(m,0x1700) for m in c.models]);self.assertEqual(c.u(tag.CONTROL+16),0)

    def test_changed_model_is_not_touched_but_other_cast_members_clean_up(self):
        c=fixture();start(c);replacement=0x4000000;c.w(tag.core.MODELS+8,replacement)
        before=c.read(c.models[2],0x1700);run(c,scene.STEP)
        self.assertEqual(c.read(c.models[2],0x1700),before);self.assertEqual(c.u(tag.CONTROL+16),0)
        self.assertEqual(c.damage,[]);self.assertEqual(len(c.placements),2)

    def test_helpers_restore_full_guest_registers_and_bystanders(self):
        c=fixture();before=c.read(c.actors[3],0x1600),c.read(c.models[3],0x1700)
        start(c);saved=c.r.copy();fpu=c.f.copy();run(c,scene.STEP)
        self.assertEqual(c.r[1:31],saved[1:31]);self.assertEqual(c.f,fpu)
        c.r[4]=1;run(c,scene.FINISH)
        self.assertEqual(before,(c.read(c.actors[3],0x1600),c.read(c.models[3],0x1700)))

    def test_finish_releases_owned_camera_on_success_and_cancellation(self):
        for cancel in (0,1):
            for binding in (camera.CAMERA,camera.CAMERA+16):
                c=fixture();start(c)
                c.w(c.r[28]-22176,camera.CAMERA);c.w(RENDERER+0xC40,binding)
                c.r[4]=cancel;run(c,scene.FINISH)
                self.assertEqual(c.u(c.r[28]-22176),ORDINARY)
                self.assertEqual(c.u(RENDERER+0xC40),ORDINARY+16)
                self.assertEqual(c.u(c.r[28]-22180),AUTHORED)
                self.assertEqual(c.u(tag.CONTROL+16),0)
                self.assertEqual(c.u(tag.CONTROL+20),0)

    def test_camera_cleanup_preserves_other_views_and_new_worlds(self):
        for change in ('other_view','new_renderer','new_manager'):
            c=fixture();start(c)
            c.w(c.r[28]-22176,camera.CAMERA);c.w(RENDERER+0xC40,camera.CAMERA+16)
            if change=='other_view':
                c.w(c.r[28]-22176,ORDINARY+0x1000);c.w(RENDERER+0xC40,ORDINARY+0x1010)
            elif change=='new_renderer':c.w(c.r[28]-22172,RENDERER+0x10000)
            else:c.w(c.r[28]-22364,0x2000000)
            before=(c.u(c.r[28]-22176),c.u(RENDERER+0xC40),c.u(c.r[28]-22180))
            c.r[4]=1;run(c,scene.FINISH)
            self.assertEqual(before,(c.u(c.r[28]-22176),c.u(RENDERER+0xC40),c.u(c.r[28]-22180)),change)
            self.assertEqual(c.u(tag.CONTROL+16),0)

    def test_native_contact_anchor_tracks_victim_without_global_pair_scans(self):
        c=fixture();start(c)
        for _ in range(80):
            run(c,scene.STEP)
            lead=c.read(c.u(c.models[0]+3436+4*52)+64,12)
            victim=c.read(c.u(c.models[1]+3436+4*3)+64,12)
            self.assertEqual(lead,victim)
        self.assertNotIn(scene.A(0x1D7C30),[address for address,_ in c.calls])
        self.assertTrue(any(address==scene.A(0x1D7198) for address,_ in c.calls))
        # Native stage offsets keep the early paired sequence elevated, then
        # make the authored cut back down for the beam ending.
        before=c.fr(scene.STATE+scene.S['phase_origin']+4)
        while c.u(scene.STATE+scene.S['phase'])<4:run(c,scene.STEP)
        run(c,scene.STEP)
        self.assertAlmostEqual(c.fr(scene.STATE+scene.S['phase_origin']+4)-before,160.)

    def test_effects_retire_without_blocking_or_releasing_borrowed_poses_early(self):
        c=fixture();start(c)
        reach_beam_event(c);self.assertEqual(len(c.beams),2)
        c.stop_remaining=2;c.r[4]=0;run(c,scene.FINISH)
        self.assertEqual(c.u(tag.CONTROL+16),1);self.assertEqual(c.damage,[]);self.assertEqual(c.placements,[])
        self.assertEqual(c.u(scene.STATE+scene.S['retiring']),1)
        oldframes=c.frames.copy();c.stop_remaining=1;run(c,scene.STEP)
        self.assertEqual(c.frames,oldframes);self.assertEqual(c.u(tag.CONTROL+16),1)
        c.stop_remaining=0;run(c,scene.STEP)
        self.assertEqual(c.u(tag.CONTROL+16),0);self.assertEqual(len(c.damage),1)
        self.assertEqual(c.u(scene.STATE+scene.S['retirement_ticks']),2)

    def test_stuck_native_emitter_disarms_tag_and_returns_player_control(self):
        c=fixture();start(c);c.stop_remaining=1
        c.r[4]=0;run(c,scene.FINISH)
        for _ in range(scene.RETIREMENT_LIMIT-2):run(c,scene.STEP)
        self.assertEqual(c.u(tag.CONTROL+16),1);self.assertEqual(c.placements,[])
        run(c,scene.STEP)
        self.assertEqual(c.u(tag.CONTROL+16),0);self.assertEqual(c.u(tag.CONTROL+tag.C['ready']),0)
        self.assertEqual(c.u(scene.STATE+scene.S['cleanup_pending']),1)
        self.assertEqual(len(c.placements),3);self.assertEqual(c.damage,[])
        self.assertEqual(c.u(effects.ROWS+effects.R['prepared']),effects.PREPARED)
        self.assertEqual(c.u(effects.ROWS+effects.STRIDE+effects.R['prepared']),effects.PREPARED)

    def test_failed_second_beam_cancels_both_without_applying_damage(self):
        c=fixture();start(c)
        def spawn(m):m.beams.append((m.r[4],m.r[5]));m.r[2]=int(m.r[4]==0)
        c.callbacks[effects.SPAWN]=spawn
        reach_beam_event(c)
        self.assertEqual(c.u(tag.CONTROL+16),0);self.assertEqual(c.damage,[])
        self.assertEqual([r for r,_ in c.beams],[0,1]);self.assertEqual(len(c.placements),3)

    def test_beams_wait_until_reviewed_source_frame_160_in_ntsc_and_pal(self):
        for hz in (30,25):
            c=fixture(hz=hz);start(c)
            while c.u(scene.STATE+scene.S['phase'])<4:run(c,scene.STEP)
            run(c,scene.STEP);fire_tick=math.ceil(160*hz/60)
            while c.u(scene.STATE+scene.S['ticks'])<fire_tick-1:run(c,scene.STEP)
            self.assertEqual(c.beams,[])
            run(c,scene.STEP)
            self.assertEqual(c.u(scene.STATE+scene.S['ticks']),fire_tick)
            self.assertEqual(c.beams,[(0,math.ceil(102*hz/60)),(1,math.ceil(102*hz/60))])
            for _ in range(5):run(c,scene.STEP)
            self.assertEqual(len(c.beams),2)

    def test_new_world_stops_private_effects_without_touching_actor_or_camera(self):
        for remaining in (0,2):
            c=fixture();start(c);c.stop_remaining=remaining;c.w(c.r[28]-22364,0x2000000)
            old=(tuple(c.read(a,0x1600) for a in c.actors),tuple(c.read(m,0x1700) for m in c.models),
                 c.u(c.r[28]-22176),c.u(RENDERER+0xC40))
            before=sum(address==effects.STOP for address,_ in c.calls);c.r[4]=1;run(c,scene.FINISH)
            self.assertEqual(sum(address==effects.STOP for address,_ in c.calls),before+1)
            self.assertEqual(c.u(scene.STATE+scene.S['cleanup_pending']),int(remaining>0))
            self.assertEqual(c.u(tag.CONTROL+tag.C['ready']),0);self.assertEqual(c.u(tag.CONTROL+16),0)
            self.assertEqual(old,(tuple(c.read(a,0x1600) for a in c.actors),tuple(c.read(m,0x1700) for m in c.models),
                                 c.u(c.r[28]-22176),c.u(RENDERER+0xC40)))

    def test_native_pause_holds_scene_then_resumes_without_restarting_phases(self):
        c=fixture();start(c);c.write(tag.TICK,tag.tick_code());c.w(tag.CONTROL+tag.C['shared'],1)
        battle=0x3130000;c.w(scene.A(0x2FEB38),battle);c.w(battle,3)
        c.write(active_pause.CHECK,active_pause.code());c.w(scene.A(0x3337C0),1)
        c.callbacks[scene.A(0x12CE88)]=lambda m:m.r.__setitem__(2,
            int(bool(m.u(c.actors[m.r[4]]+4896) or m.u(scene.A(0x3337B8))&0x100)))
        c.callbacks[tag.GATE]=lambda m:m.r.__setitem__(2,int(m.u(scene.A(0x333700))==0))
        c.w(scene.A(0x333700),1);before=c.read(scene.STATE,scene.END-scene.STATE),c.frames.copy(),c.fx_updates
        for _ in range(5):run(c,tag.TICK)
        self.assertEqual(before,(c.read(scene.STATE,scene.END-scene.STATE),c.frames.copy(),c.fx_updates))
        c.w(scene.A(0x333700),0);run(c,tag.TICK)
        self.assertEqual(c.u(scene.STATE+scene.S['ticks']),2)
        self.assertEqual(c.u(tag.CONTROL+16),1)

    def test_incomplete_presentation_is_explicitly_not_installable(self):
        pack={'variants':{name:dict(address=assets.BASE+320*i,count=5) for i,name in enumerate(('two_ki','two_melee','mixed_ki_lead','mixed_ki_partner'))}}
        plan=scene.installation(pack)
        self.assertFalse(plan['usable']);self.assertTrue(plan['limitations'])
        self.assertEqual(plan['control_words'][96],scene.TABLE)
        import tag_rush_approach as approach
        import tag_rush_voices as voices
        import tag_rush_audio_queue as queue
        import tag_rush_launch as launch
        self.assertEqual(plan['mutable_ranges'],[(scene.STATE,scene.END),(effects.CONTROL,effects.END),(audio.STATE,audio.END),
                                               (queue.STATE,queue.END),(approach.STATE,approach.END),(launch.STATE,launch.END),(voices.STATE,voices.END),
            (scene.fall_recovery.STATE,scene.fall_recovery.END),(scene.damage_schedule.STATE,scene.damage_schedule.END)])


if __name__=='__main__':unittest.main()
