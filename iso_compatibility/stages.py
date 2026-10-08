"""Bounded, read-only decoding of native stage roots and MAPD spawn data.

Root pointers are word offsets before native114C60 relocates them. MAPD
pointers are byte offsets before native242170 changes them. Never mix them.
"""
import math
import struct
from .disc import package, require, u32


def floats(data, at, count):
    require(0 <= at <= len(data)-count*4, 'Stage float array outside resource')
    values = struct.unpack_from('<'+'f'*count,data,at)
    require(all(math.isfinite(v) and abs(v)<1e8 for v in values),'Invalid stage coordinate')
    return list(values)


def region(data, pointer, count, stride):
    require(0 <= count <= 1000000 and 0 <= pointer <= len(data) and
            pointer+count*stride <= len(data), 'Stage table outside resource')
    require(not count or pointer >= 96, 'Stage table overlaps header')
    return range(pointer,pointer+count*stride,stride)


def inspect_stage(data):
    parts = package(data)
    require(len(parts)>=2,'Missing stage package parts')
    start,end = parts[0];root = data[start:end]
    require(len(root)>=96 and u32(root,0)==18 and u32(root,4)==0,
            'Unknown/unrelocated stage root layout')
    count = u32(root,56)
    require(0<count<=16384,'Invalid stage sector count')
    sector_rows = region(root,4*u32(root,60),count,64)
    bounds_at = 4*u32(root,64)
    bounds = floats(root,bounds_at,3)
    require(bounds[0]>0 and bounds[1]<bounds[2],'Invalid playable arena bounds')
    sectors=[];colliders=set()
    for at in sector_rows:
        center,half = floats(root,at+32,3),floats(root,at+48,3)
        require(all(v>=0 for v in half),'Negative sector half extent')
        neighbors=list(region(root,4*u32(root,at+12),u32(root,at+8),4))
        require(all(u32(root,p)<count for p in neighbors),'Invalid sector neighbor')
        collider=4*u32(root,at+4)
        require(collider==0 or 96<=collider<=len(root)-32,'Invalid sector collision root')
        if collider:colliders.add(collider)
        for aux in region(root,4*u32(root,at+24),u32(root,at+20),16):
            ptr=4*u32(root,aux+8)
            require(96<=ptr<=len(root)-32,'Invalid destruction collision root')
            colliders.add(ptr)
        sectors.append(dict(center=center,half_extent=half))
    collision_nodes=collision_triangles=0
    for collider in colliders:
        nodes,triangles=validate_collision(root,collider)
        collision_nodes+=nodes;collision_triangles+=triangles
    # Counts/pointers consumed by the native renderer, object manager and
    # collision loader; this validates layout, not VU rendering correctness.
    for count_at,ptr_at,stride in ((16,20,16),(24,28,8),(32,36,8),(40,44,1),
                                  (48,52,80),(68,72,80)):
        region(root,4*u32(root,ptr_at),u32(root,count_at),stride)
    tree=4*u32(root,80)
    require(96<=tree<=len(root)-64,'Invalid stage visibility tree')
    a,b=parts[1];mapd=data[a:b]
    require(len(mapd)>=168 and mapd[:4]==b'MAPD','Missing stage MAPD record')
    require(u32(mapd,40)==2,'Expected two native spawn anchors')
    spawns=[]
    for row in region(mapd,u32(mapd,44),2,32):
        values=floats(mapd,row,8)
        spawns.append(dict(position=values[:3],facing_point=values[4:7]))
    env=list(region(mapd,u32(mapd,20),u32(mapd,16),16))
    require(env,'Missing stage environment record')
    destruction_kind=u32(mapd,env[0]+12)
    return dict(format='native-stage18-mapd',sectors=count,
                arena=dict(horizontal_limit=bounds[0],floor=bounds[1],ceiling=bounds[2]),
                spawns=spawns,destruction_kind=destruction_kind,
                destruction_target={1:15,2:3}.get(destruction_kind),
                destructible_objects=u32(root,68),render_groups=u32(root,24),
                collision_trees=len(colliders),collision_nodes=collision_nodes,collision_triangles=collision_triangles,
                sector_extent=dict(minimum=[min(s['center'][i]-s['half_extent'][i] for s in sectors) for i in range(3)],
                                   maximum=[max(s['center'][i]+s['half_extent'][i] for s in sectors) for i in range(3)]),
                coordinate_convention='Raw authored MAPD coordinates; native initialization flips Y and Z',
                runtime_verified=False)


def validate_collision(root,at):
    require(96<=at<=len(root)-48,'Truncated collision header')
    nodes,triangles=u32(root,at),u32(root,at+4)
    require(0<nodes<=1000000 and 0<triangles<=1000000,'Invalid collision counts')
    node_rows=list(region(root,4*u32(root,at+12),nodes,32))
    triangle_rows=list(region(root,4*u32(root,at+16),triangles,32))
    floats(root,at+24,6);links=[]
    for node in node_rows:
        bounds=floats(root,node,6)
        require(all(bounds[i]<=bounds[i+3] for i in range(3)),'Reversed collision node bounds')
        left,right=u32(root,node+24),u32(root,node+28)
        if right==0xffffffff:
            require(left<triangles,'Collision leaf references missing triangle');links.append(())
        else:
            require(left<nodes and right<nodes,'Collision child outside tree');links.append((left,right))
    # Validate reachable graph without Python recursion, including cycles which
    # would recurse forever in native2316D0 despite every pointer being in range.
    active=set();done=set();pending=[(0,False)]
    while pending:
        node,leaving=pending.pop()
        if leaving:active.remove(node);done.add(node);continue
        if node in done:continue
        require(node not in active,'Cycle in collision tree')
        active.add(node);pending.append((node,True))
        pending.extend((child,False) for child in links[node])
    max_index=-1
    for triangle in triangle_rows:
        max_index=max(max_index,*(u32(root,triangle+off) for off in (4,8,12)))
        floats(root,triangle+16,4)
    require(max_index<1000000,'Excessive collision vertex index')
    for vertex in region(root,4*u32(root,at+20),max_index+1,16):floats(root,vertex,3)
    return nodes,triangles
