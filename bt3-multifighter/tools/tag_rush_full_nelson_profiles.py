"""Small immutable head-clearance records derived from the selected disc's meshes.

No renderer, GUI, texture decoding or per-frame host work is involved. The guest
keeps fitting to the current bones; these values only leave room for the actual
head shape, which cannot be inferred from a character's neck bone length.
"""
import hashlib
import math
import struct
from pathlib import Path
from types import SimpleNamespace

DATA,END=0x06E8F000,0x06E90000
MAGIC,STRIDE=0x4E454C33,32
MAX_ROWS=(END-DATA-16)//STRIDE
_CACHE={}


def matrix(q):
    import numpy as np
    x,y,z,w=q;n=math.sqrt(x*x+y*y+z*z+w*w)
    if not math.isfinite(n) or n<1e-8:raise ValueError('Invalid head-profile rotation')
    x,y,z,w=(v/n for v in (x,y,z,w))
    return np.array(((1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w),0),
                     (2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w),0),
                     (2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y),0),(0,0,0,1)),dtype=np.float64)


def world_matrices(bones,pose):
    import numpy as np
    result={};pending={b.native_id:b for b in bones}
    while pending:
        progressed=False
        for key,bone in list(pending.items()):
            if bone.parent_id in pending:continue
            p=pose.get(key);local=matrix(p.rotation) if p else np.eye(4)
            local[:3,3]=p.translation if p and p.translation is not None else bone.bind_translation
            result[key]=result.get(bone.parent_id,np.eye(4))@local
            del pending[key];progressed=True
        if not progressed:raise ValueError('Invalid head-profile hierarchy')
    return result


def skin(mesh,world):
    return skin_evaluator(mesh)(world)


def skin_evaluator(mesh):
    """Prepare immutable bind-space vertices once for a small fitting search."""
    import numpy as np
    positions=np.column_stack((mesh.positions,np.ones(len(mesh.positions))))
    parts=[]
    for b in mesh.bones:
        weights=np.sum(np.where(mesh.bone_indices==b.native_id,mesh.bone_weights,0),axis=1)
        used=weights>0
        if np.any(used):parts.append((b.native_id,used,positions[used]@np.linalg.inv(b.bind_world).T,weights[used,None]))
    def evaluate(world):
        result=np.zeros((len(positions),3))
        for bone,used,points,weights in parts:result[used]+=(points@np.asarray(world[bone]).T)[:,:3]*weights
        return result
    return evaluate


def geometry(package,key):
    """Reuse the reviewed native VIF parser, with texture descriptors only."""
    import model_assets as models
    from native_map import SERIAL
    data=models.package_entry(package,3);bundle=models.package_entry(package,12)
    count,offset=struct.unpack_from('<II',bundle);offset*=4
    if not 0<count<=128 or offset<32 or offset+count*64>len(bundle):raise ValueError('Invalid mesh descriptors')
    textures=[]
    for i in range(count):
        row=struct.unpack_from('<16I',bundle,offset+i*64)
        textures.append(SimpleNamespace(image_base=row[8],palette_base=row[9],tex0=row[12]|row[13]<<32))
    options={'imported':struct.unpack_from('<I',package)[0]==52} if SERIAL=='SLUS-21978' else {}
    return models.parse_geometry(data,tuple(textures),*key,**options)


def posed(mesh,binding,donor,clip,frame):
    import tag_rush_full_nelson as ik
    from model_animations import BoneTransform
    db={r['bone']:r['translation'] for r in donor['rows']}
    tb={r['bone']:r['translation'] for r in binding['rows']};result={}
    for bone,t in clip.evaluate(frame).items():
        xyz=t.translation
        if xyz is not None and bone in db and bone in tb:
            d=list(ik.sub(xyz,db[bone]));d[1]*=binding['height']/donor['height'];xyz=ik.add(d,tb[bone])
        result[bone]=BoneTransform(xyz,t.rotation)
    return result,world_matrices(mesh.bones,result)


def penetration(triangles,points):
    """Ray crossings through actual head triangles, bounded in small batches."""
    import numpy as np
    if not len(triangles):return 0.
    origin=triangles[:,0,:2];ab=triangles[:,1,:2]-origin;ac=triangles[:,2,:2]-origin
    det=ab[:,0]*ac[:,1]-ab[:,1]*ac[:,0];nonzero=np.abs(det)>1e-8
    worst=0.
    for start in range(0,len(points),128):
        pts=points[start:start+128];at=pts[:,None,:2]-origin[None,:,:]
        u=np.divide(at[:,:,0]*ac[None,:,1]-at[:,:,1]*ac[None,:,0],det[None,:],out=np.zeros(at.shape[:2]),where=nonzero[None,:])
        v=np.divide(ab[None,:,0]*at[:,:,1]-ab[None,:,1]*at[:,:,0],det[None,:],out=np.zeros(at.shape[:2]),where=nonzero[None,:])
        hit=nonzero[None,:]&(u>=0)&(v>=0)&(u+v<=1)
        depth=triangles[None,:,0,2]+u*(triangles[None,:,1,2]-triangles[None,:,0,2])+v*(triangles[None,:,2,2]-triangles[None,:,0,2])
        near=np.min(np.where(hit,depth,np.inf),axis=1);far=np.max(np.where(hit,depth,-np.inf),axis=1)
        inside=(pts[:,2]>near+1e-5)&(pts[:,2]<far-1e-5)
        if np.any(inside):worst=max(worst,float(np.max(far[inside]-pts[inside,2])))
    return worst


def closest_surface_distance(triangles,points):
    """Actual skin distance, including triangle interiors rather than vertices.

    This setup-only measurement prevents a collision-free but floating clasp
    from being accepted as a grip. It is bounded in batches of 128 hand vertices.
    """
    import numpy as np
    if not len(triangles) or not len(points):return math.inf
    valid=np.linalg.norm(np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]),axis=1)>1e-8
    triangles=triangles[valid]
    if not len(triangles):return math.inf
    # A sampled point-to-vertex pair supplies a valid upper bound. Triangle
    # boxes farther than that bound cannot contain the nearest surface point.
    # This prunes irrelevant front-of-skull faces without approximating contact.
    seed_points=points[::max(1,len(points)//16)]
    seed_vertices=triangles[::max(1,len(triangles)//32)].reshape((-1,3))
    bound=float(np.min(np.sum((seed_points[:,None,:]-seed_vertices[None,:,:])**2,axis=2)))
    gap=np.maximum(np.maximum(points.min(axis=0)-triangles.max(axis=1),
                              triangles.min(axis=1)-points.max(axis=0)),0.)
    triangles=triangles[np.sum(gap*gap,axis=1)<=bound+1e-10]
    a,b,c=triangles[:,0],triangles[:,1],triangles[:,2];ab=b-a;ac=c-a
    n=np.cross(ab,ac);length=np.linalg.norm(n,axis=1);valid=length>1e-8
    if not np.any(valid):return math.inf
    a,b,c,ab,ac,n,length=(v[valid] for v in (a,b,c,ab,ac,n,length));n=n/length[:,None]
    aa=np.sum(ab*ab,axis=1);bb=np.sum(ab*ac,axis=1);cc=np.sum(ac*ac,axis=1);den=aa*cc-bb*bb
    closest=math.inf
    for start in range(0,len(points),128):
        offset=points[start:start+128,None,:]-a[None,:,:]
        signed=np.sum(offset*n[None,:,:],axis=2);plane=offset-signed[:,:,None]*n[None,:,:]
        pa=np.sum(plane*ab[None,:,:],axis=2);pc=np.sum(plane*ac[None,:,:],axis=2)
        u=(cc*pa-bb*pc)/den;v=(aa*pc-bb*pa)/den
        distance=np.where((u>=0)&(v>=0)&(u+v<=1),abs(signed),np.inf)
        for first,last in ((a,b),(b,c),(c,a)):
            edge=last-first;at=points[start:start+128,None,:]-first[None,:,:]
            t=np.clip(np.sum(at*edge[None,:,:],axis=2)/np.sum(edge*edge,axis=1),0,1)
            distance=np.minimum(distance,np.linalg.norm(at-t[:,:,None]*edge[None,:,:],axis=2))
        closest=min(closest,float(distance.min()))
    return closest


def solid_evaluator(triangles):
    """Cache projected triangle buckets for exact, bounded three-axis ray tests."""
    import numpy as np
    low=triangles.min(axis=(0,1));high=triangles.max(axis=(0,1))
    axes=[];bins=16
    for axis in range(3):
        uv=[k for k in range(3) if k!=axis];a=triangles[:,0,uv];e=triangles[:,1,uv]-a;f=triangles[:,2,uv]-a
        den=e[:,0]*f[:,1]-e[:,1]*f[:,0];ok=abs(den)>1e-9
        a,e,f,den,t=a[ok],e[ok],f[ok],den[ok],triangles[ok]
        span=np.maximum(high[uv]-low[uv],1e-6);factor=bins/span
        lower=np.clip(np.floor((t[:,:,uv].min(axis=1)-low[uv]-1e-5)*factor),0,bins-1).astype(int)
        upper=np.clip(np.floor((t[:,:,uv].max(axis=1)-low[uv]+1e-5)*factor),0,bins-1).astype(int)
        buckets={}
        for i in range(bins):
            for j in range(bins):
                keep=(lower[:,0]<=i)&(upper[:,0]>=i)&(lower[:,1]<=j)&(upper[:,1]>=j)
                if np.any(keep):buckets[i*bins+j]=(a[keep],e[keep],f[keep],den[keep],t[keep,:,axis])
        axes.append((axis,uv,factor,buckets))
    def evaluate(points):
        points=points[np.all((points>=low)&(points<=high),axis=1)]
        votes=np.zeros(len(points),dtype=np.uint8)
        for axis,uv,factor,buckets in axes:
            cell=np.clip(np.floor((points[:,uv]-low[uv])*factor),0,bins-1).astype(int)
            ids=cell[:,0]*bins+cell[:,1]
            for key in np.unique(ids):
                if key not in buckets:continue
                a,e,f,den,t=buckets[key];indices=np.flatnonzero(ids==key)
                for start in range(0,len(indices),128):
                    at=indices[start:start+128];pts=points[at];q=pts[:,None,uv]-a[None,:,:]
                    u=(q[:,:,0]*f[None,:,1]-q[:,:,1]*f[None,:,0])/den
                    v=(e[None,:,0]*q[:,:,1]-e[None,:,1]*q[:,:,0])/den
                    z=t[None,:,0]+u*(t[None,:,1]-t[None,:,0])+v*(t[None,:,2]-t[None,:,0])-pts[:,None,axis]
                    hits=(u>=-1e-6)&(v>=-1e-6)&(u+v<=1+1e-6)&(z>1e-4)
                    distances=np.sort(np.where(hits,z,np.inf),axis=1)
                    with np.errstate(invalid='ignore'):
                        unique=np.concatenate((np.ones((len(pts),1),bool),np.diff(distances,axis=1)>1e-4),axis=1)
                    votes[at]+=np.sum(np.isfinite(distances)&unique,axis=1)%2==1
        return int(np.sum(votes>=2))
    return evaluate


def measure_pair(holder,victim,holder_pose,holder_world,victim_world,head_extra,*,style=0,
                 palm_height=None,details=False,prepared=None):
    import numpy as np
    import tag_rush_full_nelson as ik
    from model_animations import BoneTransform
    # Move the whole pair only as much as the thicker head needs. Keeping this
    # linked to clearance preserves an underarm elbow instead of folding it up.
    body_extra=0.
    fit=ik.fit_pair(holder_world,victim_world,head_clearance=head_extra,body_clearance=body_extra,
                    style=style,palm_height=palm_height)
    raw_world=victim_world
    cache=prepared['victim_cache'] if prepared else {}
    cache_key=(id(raw_world),style)
    if cache_key not in cache:
        transformed,_=ik.adjusted_victim(raw_world,style=style)
        vpoints=(prepared['victim_skin'] if prepared else skin_evaluator(victim))(transformed)
        cache[cache_key]=(transformed,vpoints)
    victim_world,vpoints=cache[cache_key]
    adjusted=dict(holder_pose)
    for arm in fit.arms:
        for bone,q in arm.local_rotations.items():
            old=adjusted.get(bone);adjusted[bone]=BoneTransform(old.translation if old else None,q)
    for bone,q in fit.holder_rotations.items():
        old=adjusted.get(bone);adjusted[bone]=BoneTransform(old.translation if old else None,q)
    final=world_matrices(holder.bones,adjusted)
    axes=np.array((fit.right,fit.up,fit.back));neck=np.array(ik.position(victim_world[46]))
    vertices=(vpoints-neck)@axes.T
    def weighted(mesh,ids,threshold=.5):
        return np.sum(np.where(np.isin(mesh.bone_indices,ids),mesh.bone_weights,0),axis=1)>threshold
    def triangles(ids,threshold=.5):
        selected=weighted(victim,ids,threshold)
        return vertices[victim.triangles[np.any(selected[victim.triangles],axis=1)]]
    points=((prepared['holder_skin'] if prepared else skin_evaluator(holder))(final)-fit.desired_neck)@axes.T
    hands=weighted(holder,tuple(range(21,32))+tuple(range(35,46)))
    arms=weighted(holder,(19,20,33,34));torso=weighted(holder,(3,16,17))
    head_triangles=triangles((46,47,80,81,82),.25)
    clear=penetration(head_triangles,points[hands])
    # Each hand must actually reach the skull. Broad bodies intentionally use
    # the separate upper-arm hook, whose contact is checked by its mesh tests.
    contact=0. if style else max(closest_surface_distance(triangles((46,47),.35),points[weighted(holder,ids,.35)])
                                  for ids in (tuple(range(21,32)),tuple(range(35,46))))
    # A hand target outside the skull does not prove the holder's own head is
    # outside a long mane. Report this independently; never silently remove hair.
    head_cache=prepared.setdefault('holder_head_cache',{}) if prepared is not None else {}
    if cache_key not in head_cache:
        held_head=weighted(holder,(46,47,48,49,50),.35)
        head_cache[cache_key]=penetration(head_triangles,points[held_head])
    holder_head=head_cache[cache_key]
    body_triangles=triangles((3,16,17))
    body=penetration(body_triangles,points[torso]);arm_body=penetration(body_triangles,points[arms])
    arm_upper=max(penetration(triangles((19,20)),points[arms]),penetration(triangles((33,34)),points[arms]))
    skin_intersections=None
    if not style and max(clear,body,arm_body,arm_upper)<.015:
        checked=weighted(holder,(19,20,33,34,3,16,17,46,47,48,49,50)+tuple(range(21,32))+tuple(range(35,46)),.35)
        solid_cache=prepared.setdefault('solid_cache',{}) if prepared is not None else {}
        if cache_key not in solid_cache:solid_cache[cache_key]=solid_evaluator(vertices[victim.triangles])
        skin_intersections=solid_cache[cache_key](points[checked])
    # The accepted normal clasp may place an elbow slightly above the shoulder
    # joint while still wrapping outside the raised arm. Requiring an elbow
    # below that joint incorrectly rejects a clear actual-mesh grip.
    safe=not any(a.clamped for a in fit.arms) and all(math.isfinite(a.reach_error) and a.reach_error<.001 for a in fit.arms)
    if details:
        return dict(head=clear,holder_head=holder_head,body=body,arm_body=arm_body,arm_upper=arm_upper,safe=safe,
                    body_extra=body_extra,reach=max(a.reach_error for a in fit.arms),
                    shoulder_width=fit.shoulder_width,contact=contact,skin_intersections=skin_intersections)
    return clear,safe,body_extra


def build_assets(iso,roster):
    import numpy as np
    import tag_rush_assets as assets
    import tag_rush_special_pair as special
    from model_animations import AnimationClip
    source_path=Path(iso).absolute();source_stat=source_path.stat()
    disc_identity=(str(source_path),source_stat.st_size,source_stat.st_mtime_ns)
    keys=sorted({(int(r['character']),int(r.get('costume',0)),bool(r.get('damaged',False))) for r in roster})
    # Clothing can break during the match. Prepare both exact states; a missing
    # damaged package is omitted, never substituted under the wrong key.
    keys=sorted(set(keys)|{(c,k,not d) for c,k,d in keys})
    if len(keys)>MAX_ROWS:raise ValueError('Too many full-nelson head profiles')
    donor=assets.read_skeleton(iso,special.DONOR);sources=special.read_sources(iso)
    db={r['bone']:r['translation'] for r in donor['rows']}
    import tag_rush_full_nelson as ik
    shift=ik.sub(sources[356].evaluate(24)[2].translation,db[2])
    clips={}
    for phase in (1,2,4):
        lead,victim,start,end,frames=special.SEGMENTS[phase]
        for role,anim in ((0,lead),(2,victim)):
            raw=special._crop(sources[anim],start,end,frames,shift if role==0 else None,role=role,phase=phase)
            clips[role,phase]=AnimationClip.from_decoded(0,raw)
    holder_raw=assets._mesh_package(iso,0);holder=geometry(holder_raw,(0,0,False));hb=assets.read_skeleton(iso,0)
    holder_skin=skin_evaluator(holder)
    source_id=hashlib.sha256(b'nelson-fit-profile-6'+holder_raw+b''.join(clips[k].__repr__().encode() for k in sorted(clips))).hexdigest()
    source_poses={p:posed(holder,hb,donor,clips[0,p],t) for p,t in ((1,16),(2,20),(4,100))}
    rows=[];unavailable=[];shape_cache={}
    for key in keys:
        try:
            raw=assets._mesh_package(iso,*key);digest=hashlib.sha256(raw).hexdigest();cache_key=(disc_identity,source_id,digest,key)
            cached=_CACHE.get(cache_key)
            # Damage commonly changes textures alone. Identical geometry and
            # the same character parameters can reuse every measured contact;
            # retain separate exact-key rows and full-package source receipts.
            import model_assets as models
            binding=assets.read_skeleton(iso,*key)
            shape_key=(key[0],float(binding['height']),hashlib.sha256(models.package_entry(raw,3)).digest())
            if cached is None:cached=shape_cache.get(shape_key)
            if cached is None:
                mesh=geometry(raw,key)
                prepared=dict(holder_skin=holder_skin,victim_skin=skin_evaluator(mesh),victim_cache={})
                samples=[]
                for phase,frame in ((1,16),(2,20),(4,100)):
                    vp,vw=posed(mesh,binding,donor,clips[2,phase],frame)
                    hp,hw=source_poses[phase];samples.append((hp,hw,vw))
                holder_width=ik.length(ik.sub(ik.position(samples[0][1][33]),ik.position(samples[0][1][19])))
                victim_width=ik.length(ik.sub(ik.position(samples[0][2][33]),ik.position(samples[0][2][19])))
                # Only bodies substantially wider than Goku may use separated
                # nape contacts. Small and normal fighters keep the close clasp.
                styles=(1,0) if victim_width>holder_width*1.2 else (0,)
                candidates=[]
                for style in styles:
                    adjusted,_=ik.adjusted_victim(samples[0][2],style=style)
                    width=ik.length(ik.sub(ik.position(adjusted[33]),ik.position(adjusted[19])))
                    nominal_height=.25 if style else ik.normal_parameters(width)['palm_height']
                    def evaluate(extra,palm_height):
                        values=[measure_pair(holder,mesh,hp,hw,vw,extra,style=style,
                            palm_height=palm_height,details=True,prepared=prepared) for hp,hw,vw in samples]
                        if not all(v['safe'] for v in values):return None
                        residuals={name:max(v[name] for v in values) for name in ('head','body','arm_body','arm_upper')}
                        score=sum(v*v for v in residuals.values())
                        counts=[v['skin_intersections'] for v in values]
                        return dict(score=score,contact=max(v['contact'] for v in values),
                                    skin_intersections=max(counts) if all(v is not None for v in counts) else None,
                                    extra=extra,gap=0.,palm_height=palm_height,
                                    style=style,residuals=residuals,holder_head=max(v['holder_head'] for v in values))
                    def rank(candidate):
                        return (bool(candidate['skin_intersections']),max(0.,candidate['score']-.015**2),
                                max(0.,candidate['contact']-.3),candidate['contact'],candidate['extra'])
                    best=evaluate(.85 if style else 0.,nominal_height)
                    # Begin at actual skin contact and move outward only as far
                    # as clearance requires. Starting at a large fixed offset
                    # previously selected hands visibly floating behind heads.
                    # Moving the hands cannot change the holder's fixed head
                    # or torso. Long manes/armour intersecting those regions
                    # need a different pose, not an exhaustive spacing search.
                    fixed_collision=best is not None and (best['holder_head']>=.015 or best['residuals']['body']>=.015)
                    if not style and not fixed_collision and (best is None or best['skin_intersections'] or best['score']>=.015**2 or best['contact']>.3):
                        for extra in (.2,.4,.6,.8,1.,1.2,1.4,1.6,1.8,2.,2.25,2.5,2.75,3.,3.25,3.5):
                            candidate=evaluate(extra,nominal_height)
                            if candidate is not None and (best is None or rank(candidate)<rank(best)):best=candidate
                            if best is not None and not best['skin_intersections'] and best['score']<.015**2 and best['contact']<=.3:break
                    if best is not None:
                        candidates.append(best)
                        if not best['skin_intersections'] and best['score']<.015**2 and best['contact']<=.3:break
                if not candidates:raise ValueError('Head profile has no bounded fixed-length fit')
                best=min(candidates,key=lambda c:(bool(c['skin_intersections']),max(0.,c['score']-.015**2),max(0.,c['contact']-.3),c['style'],c['contact']))
                # Diagnostic-only: keep the selected reachable arm geometry
                # while exposing head/hair overlap that needs a distinct pose.
                best['residuals']['holder_head']=best['holder_head']
                cached=(best['extra'],best['gap'],float(binding['height']),best['palm_height'],
                        best['style'],best['residuals'],best['contact'],best['skin_intersections']);_CACHE[cache_key]=cached
            shape_cache[shape_key]=cached;_CACHE[cache_key]=cached
            extra,gap,height,palm_height,style,residuals,contact,skin_intersections=cached
            limitations=[name+' intersection' for name,value in residuals.items() if value>=.015]
            if not style and contact>.3:limitations.append('Clasp does not reach the head')
            if skin_intersections:limitations.append('Holder arm or body skin intersection')
            rows.append(dict(character=key[0],costume=key[1],damaged=key[2],head_clearance=extra,
                             body_clearance=gap,height=height,palm_height=palm_height,style=style,
                             residual=residuals['head'],residuals=residuals,contact=contact,
                             skin_intersections=skin_intersections,limitations=limitations,
                             source_sha256=digest))
        except (ValueError,IndexError,KeyError,struct.error) as error:
            unavailable.append(dict(character=key[0],costume=key[1],damaged=key[2],reason=str(error)))
    final_stat=source_path.stat()
    if (final_stat.st_size,final_stat.st_mtime_ns)!=(source_stat.st_size,source_stat.st_mtime_ns):
        raise ValueError('ISO changed while deriving full-nelson head profiles')
    data=bytearray(struct.pack('<4I',MAGIC,len(rows),STRIDE,0))
    for row in rows:
        values=(row['head_clearance'],row['body_clearance'],row['height'],row['palm_height'])
        if not all(math.isfinite(v) for v in values) or not 0<values[2]<=1000:raise ValueError('Invalid derived head profile')
        data+=struct.pack('<3I4fI',row['character'],row['costume'],int(row['damaged']),*values,row['style'])
    if DATA+len(data)>END:raise ValueError('Full-nelson head profiles exceed reserved storage')
    return dict(blocks=[(DATA,bytes(data))],rows=rows,unavailable=unavailable,source_sha256=source_id)
