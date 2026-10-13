"""Authoritative user-authored restraint poses on the captured real actors.

The scene decoder restores the borrowed lower-body animation each update.
The special pair follows reviewed open/reach/catch poses into the three
edited endpoints without refitting their arms or changing bone lengths.
All outputs and pointers are validated before either actor is published.
"""
from prototype import Assembler
from native_map import A
import beam_struggle as fp
import fusion_partner_lifecycle as full
import tag_team_rush as tag

BASE,END=0x06E80000,0x06E90000
FIT=BASE
JOINTS=(17,18,19,20,21,31,32,33,34,35,45,46,47)


class Math:
    def __init__(self,a):self.a=a;self.next=0x100;self.labels=0
    def slot(self):
        at=self.next;self.next+=16;assert self.next<0x1E00;return at
    def label(self):self.labels+=1;return 'math'+str(self.labels)
    def load(self,at,f=0):self.a.i(49,f,29,at)
    def store(self,at,f=0):self.a.i(57,f,29,at)
    def constant(self,at,value):fp.fconst(self.a,0,value);self.store(at)
    def copy(self,out,src,n=3):
        for i in range(n):self.load(src+i*4);self.store(out+i*4)
    def point(self,out,model,bone,offset=64,n=3):
        self.a.lw(10,model,3436+bone*4)
        for i in range(n):self.a.i(49,0,10,offset+i*4);self.store(out+i*4)
    def vec(self,out,a,b,fn=0):
        for i in range(3):self.load(a+i*4);self.load(b+i*4,1);fp.fop(self.a,fn,0,0,1);self.store(out+i*4)
    def scale(self,out,v,s):
        for i in range(3):self.load(v+i*4);self.load(s,1);fp.fop(self.a,2,0,0,1);self.store(out+i*4)
    def dot(self,out,a,b,n=3):
        fp.fconst(self.a,2,0.)
        for i in range(n):self.load(a+i*4);self.load(b+i*4,1);fp.fop(self.a,2,0,0,1);fp.fop(self.a,0,2,2,0)
        self.store(out,2)
    def unit(self,out,v,n=3):
        length=self.slot();self.dot(length,v,v,n);self.load(length);fp.fconst(self.a,1,1e-10)
        fp.fop(self.a,0x34,0,0,1);self.a.branch(17,8,1,'no')
        fp.fop(self.a,4,0,0);self.store(length)
        for i in range(n):self.load(v+i*4);self.load(length,1);fp.fop(self.a,3,0,0,1);self.store(out+i*4)
        return length
    def cross(self,out,u,v):
        for i,j,k in ((0,1,2),(1,2,0),(2,0,1)):
            self.load(u+j*4);self.load(v+k*4,1);fp.fop(self.a,2,2,0,1)
            self.load(u+k*4);self.load(v+j*4,1);fp.fop(self.a,2,0,0,1)
            fp.fop(self.a,1,0,2,0);self.store(out+i*4)
    def fromto(self,out,old,new):
        u,v,c,d=(self.slot()for _ in range(4));self.unit(u,old);self.unit(v,new)
        self.cross(c,u,v);self.dot(d,u,v);self.load(d);fp.fconst(self.a,1,1.);fp.fop(self.a,0,0,0,1);self.store(c+12)
        good,axis_ready=self.label(),self.label();fp.fconst(self.a,1,.00001);fp.fop(self.a,0x34,0,1,0)
        self.a.branch(17,8,1,good)
        # A deterministic perpendicular axis also covers a folded wrist.
        axis=self.slot()
        for i in range(3):self.constant(axis+i*4,0.)
        self.load(u);fp.fop(self.a,5,0,0);fp.fconst(self.a,1,.8);fp.fop(self.a,0x34,0,0,1)
        self.a.branch(17,8,1,axis_ready);self.constant(axis+4,1.);self.a.jump(axis_ready+'done')
        self.a.label(axis_ready);self.constant(axis,1.);self.a.label(axis_ready+'done')
        self.cross(c,u,axis);self.constant(c+12,0.);self.a.label(good);self.unit(out,c,4)
    def qmul(self,out,p,q):
        # Only disjoint private stack slots reach this shared operation.
        for register,at in ((4,out),(5,p),(6,q)):self.a.addiu(register,29,at)
        self.a.call('nelson_qmul')
    def conjugate(self,out,q):
        for i in range(4):
            self.load(q+i*4)
            if i<3:fp.fconst(self.a,1,0.);fp.fop(self.a,1,0,1,0)
            self.store(out+i*4)
    def rotate(self,out,q,v,inverse=False):
        p,c,r,t=(self.slot()for _ in range(4));self.copy(p,v);self.constant(p+12,0.);self.conjugate(c,q)
        self.qmul(r,c if inverse else q,p);self.qmul(t,r,q if inverse else c);self.copy(out,t)
    def local(self,out,model,bone,world):
        self.a.lw(10,model,3436+bone*4)
        for i in range(3):
            fp.fconst(self.a,2,0.)
            for j in range(3):
                self.a.i(49,0,10,16+i*16+j*4);self.load(world+j*4,1)
                fp.fop(self.a,2,0,0,1);fp.fop(self.a,0,2,2,0)
            self.store(out+i*4,2)
    def world(self,out,model,bone,local):
        self.a.lw(10,model,3436+bone*4)
        for i in range(3):
            fp.fconst(self.a,2,0.)
            for j in range(3):
                self.a.i(49,0,10,16+j*16+i*4);self.load(local+j*4,1)
                fp.fop(self.a,2,0,0,1);fp.fop(self.a,0,2,2,0)
            self.store(out+i*4,2)
    def framequat(self,out,columns):
        """Stable XYZW rotation from three already checked orthogonal axes."""
        trace,denom,value=(self.slot()for _ in range(3))
        def cell(row,column,register=0):self.load(columns[column]+row*4,register)
        cell(0,0);cell(1,1,1);fp.fop(self.a,0,0,0,1);cell(2,2,1);fp.fop(self.a,0,0,0,1);self.store(trace)
        positive,done=self.label(),self.label();fp.fconst(self.a,1,0.);fp.fop(self.a,0x34,0,1,0)
        self.a.branch(17,8,1,positive)
        # Pick the largest diagonal; the other three cases stay well away
        # from zero even for a half-turn around any arbitrary body axis.
        case1,case2=self.label(),self.label()
        cell(0,0);cell(1,1,1);fp.fop(self.a,0x34,0,0,1);self.a.branch(17,8,1,case1)
        cell(2,2,1);fp.fop(self.a,0x34,0,0,1);self.a.branch(17,8,1,case2)
        cases=((0,None),(1,case1),(2,case2))
        for i,label in cases:
            if label:self.a.label(label)
            if i==1:
                cell(1,1);cell(2,2,1);fp.fop(self.a,0x34,0,0,1);self.a.branch(17,8,1,case2)
            j,k=(i+1)%3,(i+2)%3
            cell(i,i);fp.fconst(self.a,1,1.);fp.fop(self.a,0,0,0,1)
            cell(j,j,1);fp.fop(self.a,1,0,0,1);cell(k,k,1);fp.fop(self.a,1,0,0,1)
            fp.fop(self.a,4,0,0);fp.fconst(self.a,1,2.);fp.fop(self.a,2,0,0,1);self.store(denom)
            fp.fconst(self.a,1,.25);fp.fop(self.a,2,0,0,1);self.store(value+i*4)
            for target,row,column,other_row,other_column,subtract in ((j,i,j,j,i,False),(k,i,k,k,i,False),(3,k,j,j,k,True)):
                cell(row,column);cell(other_row,other_column,1);fp.fop(self.a,1 if subtract else 0,0,0,1)
                self.load(denom,1);fp.fop(self.a,3,0,0,1);self.store(value+target*4)
            self.a.jump(done)
        self.a.label(positive);self.load(trace);fp.fconst(self.a,1,1.);fp.fop(self.a,0,0,0,1)
        fp.fop(self.a,4,0,0);fp.fconst(self.a,1,2.);fp.fop(self.a,2,0,0,1);self.store(denom)
        fp.fconst(self.a,1,.25);fp.fop(self.a,2,0,0,1);self.store(value+12)
        for target,row,column,other_row,other_column in ((0,2,1,1,2),(1,0,2,2,0),(2,1,0,0,1)):
            cell(row,column);cell(other_row,other_column,1);fp.fop(self.a,1,0,0,1)
            self.load(denom,1);fp.fop(self.a,3,0,0,1);self.store(value+target*4)
        self.a.label(done);self.unit(out,value,4)
    def nlerp(self,out,old,new,gain):
        for register,at in ((4,out),(5,old),(6,new),(7,gain)):self.a.addiu(register,29,at)
        self.a.call('nelson_nlerp')
    def helpers(self):
        a=self.a;a.label('nelson_qmul')
        terms=(((3,0,1),(0,3,1),(1,2,1),(2,1,-1)),
               ((3,1,1),(0,2,-1),(1,3,1),(2,0,1)),
               ((3,2,1),(0,1,1),(1,0,-1),(2,3,1)),
               ((3,3,1),(0,0,-1),(1,1,-1),(2,2,-1)))
        for i,row in enumerate(terms):
            fp.fconst(a,2,0.)
            for j,k,sign in row:
                a.i(49,0,5,j*4);a.i(49,1,6,k*4);fp.fop(a,2,0,0,1);fp.fop(a,0 if sign>0 else 1,2,2,0)
            a.i(57,2,4,i*4)
        a.jr();a.label('nelson_nlerp')
        for source,norm in ((5,6),(6,7)):
            fp.fconst(a,norm,0.)
            for i in range(4):
                a.i(49,0,source,4*i);fp.fop(a,2,0,0,0);fp.fop(a,0,norm,norm,0)
            fp.fconst(a,0,1e-10);fp.fop(a,0x34,0,norm,0);a.branch(17,8,1,'no')
            # EE/R5900 SQRT.S reads Ft, not the usual MIPS Fs field.
            fp.fop(a,4,norm,0,norm)
        fp.fconst(a,2,0.)
        for i in range(4):
            a.i(49,0,5,4*i);fp.fop(a,3,0,0,6);a.i(49,1,6,4*i);fp.fop(a,3,1,1,7)
            fp.fop(a,2,0,0,1);fp.fop(a,0,2,2,0)
        fp.fconst(a,3,1.);fp.fconst(a,0,0.);fp.fop(a,0x34,0,2,0);a.branch(17,8,0,'nelson_nlerp_sign')
        fp.fconst(a,3,-1.);a.label('nelson_nlerp_sign');fp.fconst(a,2,0.)
        for i in range(4):
            a.i(49,0,6,4*i);fp.fop(a,3,0,0,7);fp.fop(a,2,0,0,3)
            a.i(49,1,5,4*i);fp.fop(a,3,1,1,6);fp.fop(a,1,0,0,1)
            a.i(49,4,7,0);fp.fop(a,2,0,0,4);fp.fop(a,0,0,0,1);a.i(57,0,29,0x80+4*i)
            fp.fop(a,2,0,0,0);fp.fop(a,0,2,2,0)
        fp.fconst(a,0,1e-10);fp.fop(a,0x34,0,2,0);a.branch(17,8,1,'no');fp.fop(a,4,2,0,2)
        for i in range(4):
            a.i(49,0,29,0x80+4*i);fp.fop(a,3,0,0,2);a.i(57,0,4,4*i)
        a.jr()


def fit_code():
    import tag_rush_scene as scene
    import tag_rush_special_pair as special
    import tag_rush_authored_hold as authored
    import tag_rush_staging as staging
    a=Assembler(FIT);tag.save(a);a.addiu(29,29,-0x2000)
    a.move(18,4);a.move(19,5);m=Math(a)
    # This is a scoped replacement for the special-pair ALIGN entry only.
    a.li(8,tag.CONTROL);a.lw(9,8,tag.C['variant']);a.li(10,special.VARIANT)
    a.branch(5,9,10,'no')
    a.li(8,scene.STATE);a.lw(9,8,scene.S['phase']);a.i(11,10,9,len(special.SEGMENTS))
    a.branch(4,10,0,'no')
    for row in (18,19):full.pointer(a,row,scene.STRIDE,'no')
    scene.finite(a,18,tuple(staging.FINAL_ROOT+i*4 for i in range(3)),'no')
    a.lw(16,18,scene.R['model']);a.lw(17,19,scene.R['model'])
    for model in (16,17):full.pointer(a,model,4000,'no')
    a.lw(8,16,12);a.branch(5,8,0,'no')
    for row,register in ((18,20),(19,21)):
        a.lw(4,row,scene.R['actor']);full.pointer(a,4,0x1600,'no')
        a.call(A(0x1DC298));full.pointer(a,2,32,'no');a.move(register,2)
        scene.finite(a,register,(0,4,8),'no')
    for model in (16,17):
        for bone in authored.JOINTS:
            a.lw(10,model,3436+bone*4);full.pointer(a,10,176,'no')
            scene.finite(a,10,(144,148,152,160,164,168,172),'no')
    # Replacing the upper body must not hide an invalid decoded source rig.
    # Check its quaternion norms separately now that the animation endpoints
    # no longer blend from the just-decoded upper-body rotations.
    for model in (16,17):
        label='source_rotation_guard'+str(model)
        a.addiu(10,model,3436+3*4);a.li(11,len(authored.JOINTS));a.label(label)
        a.lw(12,10);fp.fconst(a,2,0.)
        for i in range(4):
            a.i(49,0,12,160+4*i);fp.fop(a,2,0,0,0);fp.fop(a,0,2,2,0)
        fp.fconst(a,0,1e-10);fp.fop(a,0x34,0,2,0);a.branch(17,8,1,'no')
        fp.fconst(a,0,4.);fp.fop(a,0x34,0,0,2);a.branch(17,8,1,'no')
        a.addiu(10,10,4);a.addiu(11,11,-1)
        # The first selected joint is pelvis3; the others are16..47.
        a.li(12,len(authored.JOINTS)-1);ready='source_next'+str(model)
        a.branch(5,11,12,ready);a.addiu(10,10,12*4);a.label(ready)
        a.branch(5,11,0,label)
    # Roots follow the existing cinematic yaw and model scale, not a fixed
    # world axis. Validate those matrix columns before computing placements.
    a.lw(10,16,3436);full.pointer(a,10,80,'no')
    scene.finite(a,10,tuple(16+j*16+i*4 for j in range(3) for i in range(3)),'no')
    for model in (16,17):
        for bone in (19,33):
            a.lw(10,model,3436+bone*4)
            scene.finite(a,10,(144,),'no')
    holder_width,victim_width,ratio,weight,gain=(m.slot() for _ in range(5))
    for model,out in ((16,holder_width),(17,victim_width)):
        a.lw(10,model,3436+19*4);a.i(49,0,10,144)
        a.lw(10,model,3436+33*4);a.i(49,1,10,144)
        fp.fop(a,1,0,1,0);fp.fop(a,5,0,0);m.store(out)
        fp.fconst(a,1,.00001);fp.fop(a,0x34,0,0,1);a.branch(17,8,1,'no')
        fp.fconst(a,1,100.);fp.fop(a,0x34,0,1,0);a.branch(17,8,1,'no')
    m.load(victim_width);m.load(holder_width,1);fp.fop(a,3,0,0,1);m.store(ratio)
    # Table identity is tied to the frozen, user-edited session. Its bytes
    # belong to the immutable installed payload and source/cache identity.
    a.li(8,authored.DATA)
    for offset,value in ((0,authored.MAGIC),(4,authored.VERSION),(8,3),(12,authored.STRIDE),(48,len(authored.JOINTS)),(52,4),(56,authored.STRIDE*3),(60,authored.ACQUISITION_FRAMES)):
        a.lw(9,8,offset);a.li(10,value);a.branch(5,9,10,'no')
    digest=bytes.fromhex(authored.SOURCE_SHA256)
    for index in range(8):
        a.lw(9,8,16+4*index);a.li(10,int.from_bytes(digest[index*4:index*4+4],'little'));a.branch(5,9,10,'no')
    a.li(22,authored.DATA+authored.HEADER);a.li(23,authored.DATA+authored.HEADER+authored.STRIDE)
    m.load(ratio);fp.fconst(a,1,authored.TEMPLATES[1]['shoulder_ratio'])
    fp.fop(a,0x34,0,0,1);a.branch(17,8,1,'template_pair_ready')
    a.addiu(22,22,authored.STRIDE);a.addiu(23,23,authored.STRIDE)
    a.label('template_pair_ready')
    a.i(49,1,22,0);a.i(49,2,23,0);fp.fop(a,1,2,2,1)
    m.load(ratio);fp.fop(a,1,0,0,1);fp.fop(a,3,0,0,2)
    for limit,low in ((0.,True),(1.,False)):
        ready=m.label();fp.fconst(a,1,limit);fp.fop(a,0x34,0,0 if low else 1,1 if low else 0)
        a.branch(17,8,0,ready);fp.fop(a,6,0,1);a.label(ready)
    m.store(weight)
    # Acquisition uses the existing contiguous source clock, with a smooth
    # start/end rather than a pose or actor teleport at the held-phase seam.
    a.li(8,scene.STATE);a.lw(9,8,scene.S['phase']);a.lw(10,8,scene.S['ticks'])
    a.addiu(10,10,-1);a.emit((17<<26)|(4<<21)|(10<<16))
    a.emit((17<<26)|(20<<21)|(0<<11)|(0<<6)|32)
    fp.fconst(a,1,60./tag.ACTOR_HZ);fp.fop(a,2,0,0,1)
    prefix=0
    for index,segment in enumerate(special.SEGMENTS):
        ready=m.label();a.li(10,index);a.branch(5,9,10,ready)
        fp.fconst(a,1,prefix);fp.fop(a,0,0,0,1);a.jump('elapsed_ready')
        a.label(ready);prefix+=segment[4]
    a.label('elapsed_ready')
    elapsed=m.slot();m.store(elapsed)
    # Each reviewed keypose has three body templates. The endpoint bank is
    # bank0, with open/left-hook/right-hook in banks1/2/3 respectively.
    a.move(26,22);a.move(27,23)
    a.move(24,22);a.move(25,23);m.constant(gain,0.)
    m.load(elapsed);fp.fconst(a,1,authored.ACQUISITION_FRAMES);fp.fop(a,0x34,0,0,1)
    a.branch(17,8,0,'motion_ready')
    for segment,(first_bank,second_bank) in enumerate(((1,2),(2,3),(3,0))):
        next_segment=m.label()
        if segment<2:
            m.load(elapsed);fp.fconst(a,1,authored.KEYFRAMES[segment+1]);fp.fop(a,0x34,0,0,1)
            a.branch(17,8,0,next_segment)
        for out,base,bank in ((22,26,first_bank),(23,27,first_bank),(24,26,second_bank),(25,27,second_bank)):
            a.addiu(out,base,authored.STRIDE*3*bank)
        m.load(elapsed);fp.fconst(a,1,authored.KEYFRAMES[segment]);fp.fop(a,1,0,0,1)
        fp.fconst(a,1,authored.KEYFRAMES[segment+1]-authored.KEYFRAMES[segment]);fp.fop(a,3,0,0,1)
        for limit,low in ((0.,True),(1.,False)):
            ready=m.label();fp.fconst(a,1,limit);fp.fop(a,0x34,0,0 if low else 1,1 if low else 0)
            a.branch(17,8,0,ready);fp.fop(a,6,0,1);a.label(ready)
        fp.fconst(a,1,2.);fp.fop(a,2,1,0,1);fp.fconst(a,2,3.);fp.fop(a,1,1,2,1)
        fp.fop(a,2,0,0,0);fp.fop(a,2,0,0,1);m.store(gain);a.jump('motion_ready')
        a.label(next_segment)
    a.label('motion_ready')
    # No selected endpoint may contain a nonfinite/excessive value. The
    # compact loop also checks padding; no dynamic pointer comes from data.
    for row in (22,23,24,25):
        label='endpoint_guard'+str(row);a.addiu(10,row,authored.HOLDER_ROOT)
        a.li(11,(authored.STRIDE-authored.HOLDER_ROOT)//4)
        a.label(label);a.lw(12,10);a.li(13,0x7FFFFFFF);a.r(0x24,12,12,13)
        a.li(13,0x42C80000);a.r(0x2B,14,13,12);a.branch(5,14,0,'no')
        a.addiu(10,10,4);a.addiu(11,11,-1);a.branch(5,11,0,label)
    outputs=[]
    for model,role in ((16,0),(17,1)):
        for index,bone in enumerate(authored.JOINTS):
            first,second,from_pose,to_pose,result=(m.slot()for _ in range(5))
            offset=authored.ROTATIONS+role*len(authored.JOINTS)*16+index*16
            for left,right,target in ((22,23,from_pose),(24,25,to_pose)):
                for i in range(4):
                    a.i(49,0,left,offset+4*i);m.store(first+4*i)
                    a.i(49,0,right,offset+4*i);m.store(second+4*i)
                m.nlerp(target,first,second,weight)
            m.nlerp(result,from_pose,to_pose,gain)
            outputs.append((model,bone,result))
    roots=[]
    anchor=m.slot()
    # APPLY writes this mark once per phase. SETTLE can be zero on subsequent
    # hold phases, so current actor roots cannot be used as an additive base.
    for i in range(3):a.i(49,0,18,staging.FINAL_ROOT+4*i);m.store(anchor+4*i)
    # Phase0 settle: staging.TICK has just moved the victim root along its
    # glide into the hold. Carry the whole authored pair rigidly with it, so
    # the open reach is never replaced by the decoded native restraint start
    # (crossed arms, holder hips over the victim's head, victim turned).
    a.li(8,scene.STATE);a.lw(9,8,scene.S['phase']);a.branch(5,9,0,'anchor_ready')
    a.lw(8,19,staging.SETTLE);a.branch(4,8,0,'anchor_ready')
    for i in range(3):
        a.i(49,0,21,4*i);a.i(49,1,19,staging.FINAL_ROOT+4*i);fp.fop(a,1,0,0,1)
        m.load(anchor+4*i,1);fp.fop(a,0,0,0,1);m.store(anchor+4*i)
    a.label('anchor_ready')
    for row,offset in ((18,authored.HOLDER_ROOT),(19,authored.VICTIM_ROOT)):
        local,other,world,result=(m.slot()for _ in range(4))
        for left,right,out in ((22,23,local),(24,25,other)):
            for i in range(3):
                a.i(49,0,left,offset+4*i);a.i(49,1,right,offset+4*i)
                fp.fop(a,1,1,1,0);m.load(weight,2);fp.fop(a,2,1,1,2)
                fp.fop(a,0,0,0,1);m.store(out+4*i)
        # Every keypose retains the size-correct Y placement. Only the
        # holder's horizontal approach moves; the opponent never rises
        # through Goku's torso before the grip is made.
        for i in range(3):
            m.load(local+4*i);m.load(other+4*i,1);fp.fop(a,1,1,1,0)
            m.load(gain,2);fp.fop(a,2,1,1,2);fp.fop(a,0,0,0,1);m.store(local+4*i)
        m.world(world,16,0,local);m.vec(result,anchor,world)
        roots.append((row,result))
    # Transactional publication: every quaternion and position is ready and
    # checked before touching either real model. Bone lengths stay native.
    scene.finite(a,29,tuple(at+4*i for _,_,at in outputs for i in range(4))+
                 tuple(at+4*i for _,at in roots for i in range(3)),'no')
    # Finite is insufficient on the EE: a wrong normalization operand can
    # produce finite 1e20 quaternions and saturate the composed bone matrices.
    # Reject every non-unit output before either actor receives any writes.
    stride=outputs[1][2]-outputs[0][2]
    assert all(at==outputs[0][2]+index*stride for index,(_,_,at) in enumerate(outputs))
    a.addiu(10,29,outputs[0][2]);a.li(11,len(outputs));a.label('output_rotation_guard')
    fp.fconst(a,2,0.)
    for i in range(4):
        a.i(49,0,10,4*i);fp.fop(a,2,0,0,0);fp.fop(a,0,2,2,0)
    fp.fconst(a,0,.9);fp.fop(a,0x34,0,2,0);a.branch(17,8,1,'no')
    fp.fconst(a,0,1.1);fp.fop(a,0x34,0,0,2);a.branch(17,8,1,'no')
    a.addiu(10,10,stride);a.addiu(11,11,-1);a.branch(5,11,0,'output_rotation_guard')
    for model,bone,at in outputs:
        a.lw(10,model,3436+bone*4)
        for i in range(4):m.load(at+4*i);a.i(57,0,10,160+4*i)
    for (row,at),ptr in zip(roots,(20,21)):
        for i in range(3):m.load(at+4*i);a.i(57,0,ptr,4*i)
    for row in (18,19):
        a.lw(4,row,scene.R['actor']);a.move(5,0);a.call(A(0x1D7198))
    for model in (16,17):a.move(4,model);a.call(A(0x24E3F8))
    for row in (18,19):a.lw(4,row,scene.R['actor']);a.call(A(0x1D70E8))
    a.lw(4,19,scene.R['actor']);a.li(5,0x23);a.call(A(0x1DABE8))
    a.li(2,1);a.jump('done')
    a.label('no');a.move(2,0);a.label('done');a.addiu(29,29,0x2000);tag.restore(a,2);a.jr()
    m.helpers()
    result=a.finish();assert FIT+len(result)<=authored.DATA,len(result)
    return result


def pieces():
    import tag_rush_authored_hold as authored
    return [(FIT,fit_code())]+authored.pieces()
