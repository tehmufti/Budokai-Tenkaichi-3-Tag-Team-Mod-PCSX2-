"""Read-only USA BT3 character assets for the native desktop model viewer.

Decodes the original PAK, PMDL skeleton and VIF triangle-strip packets. No
emulator connection, game writes, downloaded model, or placeholder geometry.
Coordinates and skin IDs remain native: Y points down; vertex positions are
bind-world. Skin with poseWorld @ inverse(bindWorld), then convert view axes.
"""
from dataclasses import dataclass
from pathlib import Path
import struct
import numpy as np

class AssetFormatError(ValueError):
    pass

# Verified against all 161 original-USA base packages. High bone IDs also
# contain ordinary hair/belts; never treat every high ID as an accessory.
HALO_CHARACTERS = frozenset((0,1,2,3,4,5,6,22,23,25,26,27,28,34,35,36,53))


def part_names(asset):
    return {111: 'Halo'} if asset.character in HALO_CHARACTERS and 111 in asset.triangle_bones else {}

@dataclass(frozen=True)
class Bone:
    native_id: int
    parent_id: int
    bind_translation: tuple
    bind_world: np.ndarray

@dataclass(frozen=True)
class Texture:
    rgba: np.ndarray
    tex0: int
    image_base: int
    palette_base: int

@dataclass(frozen=True)
class Material:
    texture_index: int
    tex0: int

@dataclass(frozen=True)
class ModelAsset:
    positions: np.ndarray
    normals: np.ndarray
    uv: np.ndarray
    triangles: np.ndarray
    triangle_materials: np.ndarray
    bone_indices: np.ndarray
    bone_weights: np.ndarray
    bones: tuple
    materials: tuple
    textures: tuple
    character: int = -1
    costume: int = 0
    damaged: bool = False
    warnings: tuple = ()

    @property
    def triangle_bones(self):
        """Native part/bone ID for each triangle, for viewer visibility filters."""
        return self.bone_indices[self.triangles[:,0],0]

def _check(condition, message):
    if not condition: raise AssetFormatError(message)

def _u32(data, off):
    _check(0 <= off <= len(data)-4, 'Truncated native asset')
    return struct.unpack_from('<I', data, off)[0]

def package_entry(data, index):
    count=_u32(data,0)
    _check(1 <= count <= 4096 and len(data)>=4*(count+2), 'Invalid native package table')
    _check(1 <= index <= count, 'Native package entry out of range')
    start,end=(_u32(data,4*index)&~3,_u32(data,4*(index+1))&~3)
    _check(4*(count+2)<=start<=end<=len(data),'Invalid native package entry bounds')
    return data[start:end]

def read_archive_entry(iso_path, file_id):
    """One file of the selected disc by its USA global file ID (the European and Japanese discs number files
    differently)."""
    from native_map import TRANSLATED
    if TRANSLATED:
        _check(isinstance(file_id,int) and 1<=file_id<=3399,'Archive file ID out of range')
        import regional
        data=regional.read_disc_file(iso_path,file_id)
        _check(0<len(data)<32*1024*1024,'Invalid character resource size')
        return data
    import pycdlib
    iso=pycdlib.PyCdlib();iso.open(str(iso_path))
    try:
        with iso.open_file_from_iso(iso_path='/DATA/PZS3US1.AFS;1') as stream:
            magic,count=struct.unpack('<4sI',stream.read(8))
            _check(magic==b'AFS\0' and count==3399,'Expected original USA BT3 AFS1 archive')
            _check(1<=file_id<=count,'Archive file ID out of range')
            stream.seek(8+(file_id-1)*8);off,size=struct.unpack('<II',stream.read(8))
            _check(0<size<32*1024*1024,'Invalid character resource size')
            stream.seek(off);data=stream.read(size)
            _check(len(data)==size,'Truncated ISO resource')
            return data
    finally: iso.close()

def read_animation_bank(iso_path, character):
    _check(isinstance(character,int) and 0<=character<161,'Character ID out of range')
    return read_archive_entry(iso_path,10*character+1432)

def load_character(iso_path, character, costume=0, damaged=False):
    _check(isinstance(character,int) and 0<=character<161,'Character ID out of range')
    _check(isinstance(costume,int) and 0<=costume<4,'Costume ID out of range')
    data=read_archive_entry(iso_path,10*character+(1428 if damaged else 1424)+costume)
    return parse_character_package(data,character,costume,damaged)

def _address32(x,y,width):
    # GS CT32: 64x32 page; 8x8 block; 8x2 column. Output byte address.
    block=((x>>3)&1)|(((y>>3)&1)<<1)|(((x>>4)&1)<<2)|(((y>>4)&1)<<3)|(((x>>5)&1)<<4)
    word=(x&1)|((y&1)<<1)|((x&6)<<1)|((y&6)<<3)
    return ((y//32)*max(1,width//64)+x//64)*8192+block*256+word*4

def _address4(x,y,width):
    # GS T4: 128x128 page; 32x16 block; 32x4 column, in nibble units.
    block=((y>>4)&1)|(((x>>5)&1)<<1)|(((y>>5)&1)<<2)|(((x>>6)&1)<<3)|(((y>>6)&1)<<4)
    nibble=((x&1)<<3)|((x&6)<<4)|((x&24)>>2)|((y&1)<<4)|((y&2)>>1)|((y&12)<<5)
    nibble ^= (((y>>1)^(y>>2))&1)<<6
    return ((y//128)*max(1,width//128)+x//128)*16384+block*512+nibble

def _image_packet(bundle, offset, size):
    _check(offset>=0 and size>=128 and offset+size<=len(bundle),'Texture IMAGE packet out of range')
    data=bundle[offset:offset+size]
    _check(tuple(struct.unpack_from('<Q',data,o)[0] for o in(0x28,0x38,0x48))==(0x51,0x52,0x53),'Unexpected texture transfer registers')
    width,height=struct.unpack_from('<II',data,0x30)
    tag=struct.unpack_from('<Q',data,0x50)[0];length=(tag&0x7fff)*16
    _check((tag>>58)&3==2 and 0<width<=4096 and 0<height<=4096,'Invalid texture IMAGE transfer')
    _check(96+length<=len(data),'Truncated texture IMAGE payload')
    return data[96:96+length],width,height

def decode_texture(bundle, descriptor):
    _check(descriptor+64<=len(bundle),'Truncated texture descriptor')
    row=struct.unpack_from('<16I',bundle,descriptor);tex0=row[12]|(row[13]<<32)
    width=1<<((tex0>>26)&15);height=1<<((tex0>>30)&15);psm=(tex0>>20)&63
    _check(width<=2048 and height<=2048,'Excessive texture dimensions')
    pixels,transfer_w,transfer_h=_image_packet(bundle,row[0]*4,row[2])
    if psm==0:
        _check((transfer_w,transfer_h)==(width,height) and len(pixels)==width*height*4,'Unexpected RGBA texture upload')
        rgba=np.frombuffer(pixels,dtype=np.uint8).reshape(height,width,4).copy()
    else:
        _check(psm in (19,20),'Unsupported GS texture pixel format '+str(psm))
        palette,_,_=_image_packet(bundle,row[1]*4,row[3])
        colors=256 if psm==19 else 16
        _check(len(palette)>=colors*4,'Truncated texture palette')
        pal=np.frombuffer(palette[:colors*4],dtype=np.uint8).reshape(colors,4)
        if psm==19:
            order=np.arange(256);order=(order&0xe7)|((order&8)<<1)|((order&16)>>1)
            pal=pal[order]
            # Same CT32-upload -> T8 mapping used by native_menu_assets.
            y,x=np.indices((height,width));source=((y&~15)*width+(x&~15)*2+((((y&~3)>>1)+(y&1))&7)*width*2+((x+(((y+2)>>2)&1)*4)&7)*4+((y>>1)&1)+((x>>2)&2))
            _check(int(source.max())<len(pixels),'Unsupported T8 upload dimensions')
            indices=np.frombuffer(pixels,dtype=np.uint8)[source]
        else:
            _check(len(pixels)==transfer_w*transfer_h*4,'Unexpected T4 upload byte length')
            y,x=np.indices((transfer_h,transfer_w));addresses=_address32(x,y,max(64,row[6]*64))
            yy,xx=np.indices((height,width));nibbles=_address4(xx,yy,max(128,((tex0>>14)&63)*64))
            memory=np.zeros(max(int(addresses.max())+4,int(nibbles.max())//2+1),dtype=np.uint8)
            raw=np.frombuffer(pixels,dtype=np.uint8).reshape(-1,4)
            for lane in range(4):memory[addresses.ravel()+lane]=raw[:,lane]
            indices=(memory[nibbles//2]>>((nibbles&1)*4))&15
        rgba=pal[indices].copy()
    rgba[:,:,3]=np.minimum(rgba[:,:,3].astype(np.uint16)*2,255).astype(np.uint8)
    return Texture(rgba,tex0,row[8],row[9])

def parse_character_package(data, character=-1, costume=0, damaged=False):
    _check(len(data)>64,'This costume or damaged variant is not present in the original game')
    _check(_u32(data,0)==252,'Expected native 252-entry character package')
    geometry=package_entry(data,3);bundle=package_entry(data,12)
    count=_u32(bundle,0);desc=_u32(bundle,4)*4
    _check(0<count<=128 and desc>=32 and desc+count*64<=len(bundle),'Invalid model texture descriptor table')
    textures=tuple(decode_texture(bundle,desc+i*64) for i in range(count))
    return parse_geometry(geometry,textures,character,costume,damaged)

def parse_geometry(data,textures,character=-1,costume=0,damaged=False):
    _check(len(data)>=144 and data[:4]==b'pmdl','Expected native PMDL geometry')
    count=_u32(data,8);offset=_u32(data,108)
    _check(0<count<=256,'Invalid skeleton part count')
    bones=[];stack=[];positions=[];normals=[];uv=[];indices=[];weights=[];triangles=[];triangle_materials=[];materials=[];material_lookup={};seen=set()
    for part_no in range(count):
        _check(offset+64<=len(data),'Truncated skeleton part')
        size,pop,last,nv,bone_id=struct.unpack_from('<IHHHH',data,offset)
        _check(size>=64 and offset+size<=len(data) and bone_id not in seen,'Invalid or duplicate skeleton part')
        seen.add(bone_id);world=np.asarray(struct.unpack_from('<3f',data,offset+16),dtype=np.float32);parent_world=np.asarray(struct.unpack_from('<3f',data,offset+32),dtype=np.float32);local=struct.unpack_from('<3f',data,offset+48)
        parent=stack[-1] if stack else None
        _check(np.all(np.isfinite(world)) and np.all(np.isfinite(local)),'Non-finite skeleton coordinates')
        _check(np.allclose(parent.bind_world[:3,3] if parent else 0,parent_world,atol=.003),'Skeleton parent translation mismatch')
        _check(parent is None or np.allclose(world-parent_world,local,atol=.003),'Skeleton local translation mismatch')
        matrix=np.eye(4,dtype=np.float32);matrix[:3,3]=world
        node=Bone(bone_id,parent.native_id if parent else -1,tuple(local),matrix);bones.append(node);stack.append(node)
        _check(pop<=len(stack),'Invalid skeleton stack pop')
        if pop:del stack[-pop:]
        if nv:
            _check(size>=128,'Truncated drawable model part');tag=_u32(data,offset+96)
            _check((tag>>28)&7==6,'Unsupported model DMA chain')
            cursor=offset+104;end=offset+112+(tag&0xffff)*16
            _check(end+16<=offset+size and _u32(data,end)==0x70000000,'Invalid model DMA terminator')
            material=None;chunk=None;part_vertices=0
            while cursor<end:
                word=_u32(data,cursor);cursor+=4;cmd=(word>>24)&0x7f;num=(word>>16)&255;imm=word&65535
                if cmd==0:continue
                if cmd==0x6c:
                    _check(num and cursor+num*16<=end,'Truncated model VIF UNPACK')
                    if imm==0x8000:
                        _check(num==5 and chunk is None,'Unexpected model material packet')
                        tex0=struct.unpack_from('<Q',data,cursor+16)[0]
                        _check(_u32(data,cursor+24)==6,'Missing model TEX0 register')
                        matches=[i for i,t in enumerate(textures) if data[78]<=i<data[78]+data[79] and t.image_base==(tex0&16383) and t.palette_base==((tex0>>37)&16383) and ((t.tex0>>20)&0x3fff)==((tex0>>20)&0x3fff)]
                        _check(len(matches)==1,'Missing or ambiguous model texture binding')
                        if tex0 not in material_lookup:material_lookup[tex0]=len(materials);materials.append(Material(matches[0],tex0))
                        material=material_lookup[tex0]
                        expected=_u32(data,cursor+48)&0x7fff
                    elif imm==0x8005:
                        _check(material is not None and num%3==0 and num//3==expected,'Unexpected model vertex packet')
                        chunk=np.frombuffer(data,dtype='<f4',count=num*4,offset=cursor).reshape(-1,3,4).copy()
                        _check(np.all(np.isfinite(chunk)),'Non-finite model vertices')
                    else:raise AssetFormatError('Unsupported model VIF destination')
                    cursor+=num*16
                elif cmd==0x17:
                    _check(chunk is not None and len(chunk)>=3,'Missing triangle strip before MSCNT')
                    start=len(positions);n=len(chunk);part_vertices+=n
                    positions.extend(chunk[:,0,:3]);normals.extend(chunk[:,1,:3]);uv.extend(chunk[:,2,:2])
                    w=chunk[:,0,3];_check(np.all((w>=0)&(w<=1)),'Invalid native skin weight')
                    indices.extend([(bone_id,parent.native_id if parent else bone_id)]*n);weights.extend(np.column_stack((w,1-w)))
                    for i in range(2,n):
                        a,b=(i-2,i-1) if i%2==0 else (i-1,i-2)
                        triangles.append((start+a,start+b,start+i));triangle_materials.append(material)
                    chunk=None
                else:raise AssetFormatError('Unsupported model VIF command '+hex(cmd))
            _check(cursor==end and chunk is None and part_vertices==nv,'Model packet vertex count mismatch')
        _check(bool(last)==(part_no==count-1),'Unexpected skeleton terminal marker')
        offset+=size
    _check(positions and triangles,'Model contains no drawable geometry')
    return ModelAsset(np.asarray(positions,dtype=np.float32),np.asarray(normals,dtype=np.float32),np.asarray(uv,dtype=np.float32),np.asarray(triangles,dtype=np.uint32),np.asarray(triangle_materials,dtype=np.uint16),np.asarray(indices,dtype=np.int16),np.asarray(weights,dtype=np.float32),tuple(bones),tuple(materials),tuple(textures),character,costume,damaged)
