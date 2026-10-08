"""Offline, guarded world-coordinate scaling research.

Builds a reproducible coordinate plan including the playable arena bounds.
The separate expanded_maps module can write an explicitly experimental copy
for playtests; it excludes animated stage models. Ambient effects, event actors
and cinematic framing still need validation before a production release.
"""
from collections import Counter
import math
import struct
from .disc import require, package, u32
from .stages import inspect_stage, region, floats


class ScalePlan:
    def __init__(self,data,factor):
        require(type(factor) in (int,float) and math.isfinite(factor) and 1<=factor<=4,
                'Scale must be finite and between 1 and 4')
        self.data=data;self.factor=float(factor);self.fields={};self.categories=Counter()
        self.blockers=[]

    def vector(self,at,count,category):
        values=floats(self.data,at,count)
        for i,value in enumerate(values):
            offset=at+4*i
            require(offset%4==0,'Unaligned stage coordinate')
            if offset in self.fields:continue  # shared vertices/packets must scale once
            self.fields[offset]=value;self.categories[category]+=1

    def preview(self):
        result=bytearray(self.data)
        for at,value in self.fields.items():struct.pack_into('<f',result,at,value*self.factor)
        return bytes(result)

    def summary(self):
        return dict(scale=self.factor,float_fields=len(self.fields),categories=dict(self.categories),
                    ready_for_runtime=not self.blockers,blockers=self.blockers,
                    boundary_expands=True,fighter_size_and_speed_unchanged=True)


def plan_stage(data,factor=2):
    inspect_stage(data)
    plan=ScalePlan(data,factor)
    entries=package(data);base,limit=entries[0];root=data[base:limit]
    h=lambda at:struct.unpack_from('<H',root,at)[0]
    ptr=lambda at:4*u32(root,at)
    def vector(at,count,kind):
        require(0<=at<=len(root)-count*4,'Scale field outside stage root')
        plan.vector(base+at,count,kind)
    def rows(count_at,ptr_at,stride):return region(root,ptr(ptr_at),u32(root,count_at),stride)

    # Native23FE70/23FEF8/23FF38 read radius, floor and ceiling here. Scale
    # these with geometry, not merely the camera or visible scenery.
    vector(ptr(64),3,'arena_limits')
    vector(76,1,'visibility_distance')
    colliders=set()
    for at in rows(56,60,64):
        vector(at+28,1,'sector_radius')
        vector(at+32,3,'sector_center');vector(at+48,3,'sector_half_extent')
        if ptr(at+4):colliders.add(ptr(at+4))
        for auxiliary in region(root,ptr(at+24),u32(root,at+20),16):
            if ptr(auxiliary+8):colliders.add(ptr(auxiliary+8))
    for at in sorted(colliders):
        require(at<=len(root)-48,'Truncated collision header')
        node_count,triangle_count=u32(root,at),u32(root,at+4)
        require(0<node_count<=1000000 and 0<triangle_count<=1000000,'Invalid collision counts')
        nodes=list(region(root,ptr(at+12),node_count,32))
        triangles=list(region(root,ptr(at+16),triangle_count,32))
        max_index=-1
        vector(at+24,6,'collision_header_bounds')
        for node in nodes:
            vector(node,6,'collision_tree_bounds')
            left,right=u32(root,node+24),u32(root,node+28)
            if right==0xffffffff:require(left<triangle_count,'Collision leaf references missing triangle')
            else:require(left<node_count and right<node_count,'Collision tree links outside node table')
        for triangle in triangles:
            indices=[u32(root,triangle+n) for n in (4,8,12)]
            max_index=max(max_index,*indices)
            vector(triangle+28,1,'collision_plane_distance')
            # Unit normals must remain unchanged under uniform scaling.
            floats(root,triangle+16,3)
        require(max_index<1000000,'Excessive collision vertex index')
        for vertex in region(root,ptr(at+20),max_index+1,16):
            vector(vertex,3,'collision_vertices')

    visited=set();pending=[ptr(80)]
    while pending:
        at=pending.pop()
        require(at not in visited,'Cycle/shared node in visibility tree')
        visited.add(at);require(len(visited)<=100000 and 96<=at<=len(root)-64,'Invalid visibility tree')
        vector(at+40,3,'visibility_tree_centers')
        pending.extend(ptr(at+4*n) for n in range(1,9) if ptr(at+4*n))
    # Bounding spheres for render batches (native2405F8).
    for group in rows(32,36,8):
        for batch in region(root,ptr(group+4),u32(root,group),32):
            vector(batch+12,4,'render_batch_bounds')
    # Native object motion source records: position followed by Euler angles.
    for obj in rows(48,52,80):
        for motion in region(root,ptr(obj+68),u32(root,obj+64),32):
            vector(motion,3,'object_translation')

    packets=set();sky_packets=set()
    for group_index,group in enumerate(rows(24,28,8)):
        for material in region(root,ptr(group+4),h(group+2),16):
            for draw in region(root,ptr(material+4),h(material+2),16):
                (sky_packets if group_index==0 else packets).add(ptr(draw+8))
    # Native115DE0's first render group is the depth-disabled sky dome. Its
    # vertices are already 30,000..55,000 units away, well outside the enlarged
    # playable arena. Doubling them crosses the native far clipping range and
    # cuts moving seams through the background. Never scale sky UVs or vertices.
    require(not sky_packets.intersection(packets),'Sky and world share a render packet')
    for packet in sorted(packets):
        tag=u32(root,packet)
        require((tag>>28)&7==6,'Unsupported stage DMA chain')
        end=packet+16+(tag&0xffff)*16
        require(end<=len(root),'Stage DMA packet exceeds resource')
        cursor=packet+8
        while cursor<end:
            word=u32(root,cursor);cursor+=4
            command=(word>>24)&0x7f;count=(word>>16)&255;immediate=word&65535
            if command==0:continue
            if command==0x6c:
                require(count>0 and cursor+count*16<=end,'Invalid stage VIF UNPACK')
                if immediate==0x8003:
                    require(count%3==0,'Changed stage vertex stride')
                    # Reviewed stage packets: position, color, UV. Keep colors,
                    # texture coordinates, flags and homogeneous W unchanged.
                    for vertex in range(cursor,cursor+count*16,48):vector(vertex,3,'render_vertices')
                else:require(immediate==0x8000 and count in (1,3),'Unknown stage VIF destination')
                cursor+=count*16
            else:require(command==0x17,'Unknown stage VIF command')
        require(cursor==end,'Stage VIF packet is misaligned')

    start,end=entries[1];mapd=data[start:end]
    for count_at,pointer_at,stride,position_offsets in (
            (8,12,64,(32,)), (24,28,32,(0,)), (40,44,32,(0,16)),
            (48,52,32,(0,16)), (56,60,32,(0,16))):
        for row in region(mapd,u32(mapd,pointer_at),u32(mapd,count_at),stride):
            for off in position_offsets:plan.vector(start+row+off,3,'mapd_positions')
    for start,end in entries[2:5]:
        if start==end:continue
        track=data[start:end]
        require(track[:4]==b'CMAn' and len(track)>=48,'Unknown stage camera archive')
        require(u32(track,4)==6 and 0<u32(track,12)<=8,'Unsupported stage camera channels')
        # Native23D1E8 relocates these offsets;23D270 interpolates each channel
        # from key+8 using key+4 as time. Channels0..2 are world XYZ;3..5 are
        # angles. Tangents, times, flags and rotation must remain untouched.
        plan.vector(start+u32(track,24),3,'intro_camera_position')
        seen=set()
        def camera_rows(offset,count,stride):
            require(48<=offset<=len(track) and count<100000 and
                    offset+count*stride<=len(track),'Camera track exceeds archive')
            return range(offset,offset+count*stride,stride)
        for row in camera_rows(u32(track,8),u32(track,12),16):
            channel=u32(track,row)
            require(channel<8 and channel not in seen,'Invalid camera channel')
            seen.add(channel)
            keys=camera_rows(u32(track,row+4),u32(track,row+8),32)
            for key in keys:
                if channel<3:plan.vector(start+key+8,1,'intro_camera_keys')
    # Keep unresolved systems explicit; a partial plan is useful for regression
    # tests but must never be mistaken for a playable map-scale patch.
    plan.blockers.append('Ambient stage effects, event/prop actors and destruction debris still need matching spatial transforms')
    if u32(root,16) or (len(entries)>8 and entries[8][1]>entries[8][0]):
        plan.blockers.append('Animated stage model and keyframe transforms require decoding')
    plan.blockers.append('Stage-transition framing and native fixed-distance arena margins require gameplay validation')
    return plan


def audit_iso(path,output,factor=2):
    """Write metadata only. Original ISO and emulator configuration stay untouched."""
    from .disc import Disc
    from .adapters import identify,verify_stage_mapping
    from .scanner import atomic_json
    import hashlib
    report=dict(source=str(path),scale=factor,stages=[],ready_for_runtime=False)
    with Disc(path) as disc:
        adapter,known=identify(disc)
        require(adapter is not None and known,'Map scaling research requires a reviewed executable')
        verify_stage_mapping(disc,adapter)
        for stage in range(adapter.stage_count):
            for mode,base in (('normal',adapter.stage_base),('split_screen',adapter.split_stage_base)):
                row=dict(stage_id=stage,variant=mode,file_id=base+stage)
                try:
                    raw=disc.read(base+stage);plan=plan_stage(raw,factor)
                    scaled=plan.preview();before=inspect_stage(raw);after=inspect_stage(scaled)
                    row.update(plan.summary(),original_bounds=before['arena'],expanded_bounds=after['arena'],
                               source_sha256=hashlib.sha256(raw).hexdigest(),preview_sha256=hashlib.sha256(scaled).hexdigest())
                except (ValueError,struct.error) as error:row['error']=str(error)
                report['stages'].append(row)
    atomic_json(output,report)
    return report


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('iso');p.add_argument('--output',required=True)
    p.add_argument('--scale',type=float,default=2);args=p.parse_args()
    result=audit_iso(args.iso,args.output,args.scale)
    print(f"Audited {len(result['stages'])} stage variants. Report: {args.output}. Runtime scaling remains disabled.")
