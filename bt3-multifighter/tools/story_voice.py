"""Read-only character dialogue previews from the user's disc; no audio is bundled.

Native 265E38 computes bank_base + character*100 + line. Resolve its two
constants from the selected executable, including BT4 and European layouts.
ADX type-3 predictor math is checked against FFmpeg's adx decoder:
https://github.com/FFmpeg/FFmpeg/blob/master/libavcodec/adxdec.c
https://github.com/FFmpeg/FFmpeg/blob/master/libavcodec/adx.c
"""
from dataclasses import dataclass
from pathlib import Path
import math
import struct
import sys


def disc_class():
    root=str(Path(__file__).resolve().parents[2])
    if root not in sys.path:sys.path.insert(0,root)
    from iso_compatibility.disc import Disc
    return Disc


def default_iso(parent=None):
    import game_profile,regional
    from native_map import SERIAL
    while parent:
        if hasattr(parent,'iso') and hasattr(parent.iso,'text'):
            value=parent.iso.text()
            if Path(value).is_file():return value
        parent=parent.parent()
    name='SLUS_219.78.DBZBT4B14REV2ENG.iso' if SERIAL=='SLUS-21978' else regional.ISO_NAME
    return str(game_profile.source_iso(Path(__file__).resolve().parents[2]/'games'/name))


def voice_bases(elf):
    signature=struct.pack('<2I',0x00051040,0x27BDFFF0)
    candidates=[];start=0
    while True:
        at=elf.find(signature,start)
        if at<0:break
        start=at+4
        if at+0x98>len(elf):continue
        words=struct.unpack_from('<38I',elf,at)
        if (words[3],words[5],words[6],words[9])!=(0x00451021,0x000210C0,0x00451021,0x00021080):continue
        high=words[13];bases=[]
        for n in (19,15):
            op=words[n];rs=(op>>21)&31
            if op>>26!=13 or (op>>16)&31!=5 or rs not in (0,2):break
            if rs==2 and high>>16!=0x3C02:break
            bases.append(((high&65535)<<16 if rs==2 else 0)|(op&65535))
        if len(bases)==2:candidates.append(tuple(bases))
    if len(candidates)!=1:raise ValueError('This disc has no recognized character dialogue mapping')
    return candidates[0]


def locate(disc,ident):
    if disc.kind=='bt3-afs':
        # Native global IDs span all AFS volumes, not just character resources.
        index=ident
        for volume in sorted(disc.tables):
            rows=disc.tables[volume]
            if index<len(rows):
                off,size=rows[index]
                if not 0<size<=8*1024*1024:raise ValueError('Empty or oversized dialogue resource')
                return disc.volume_paths[volume],off,size
            index-=len(rows)
        raise ValueError('Dialogue ID is outside this disc')
    return disc.locate(ident)


def read(disc,ident,limit=None):
    path,off,size=locate(disc,ident)
    with disc.iso.open_file_from_iso(iso_path=path) as stream:
        stream.seek(off);data=stream.read(min(size,limit) if limit else size)
    return data


@dataclass(frozen=True)
class Adx:
    offset:int
    channels:int
    rate:int
    samples:int
    cutoff:int

    @property
    def seconds(self):return self.samples/self.rate


def header(data):
    if len(data)<24 or data[:2]!=b'\x80\x00' or data[4:7]!=b'\x03\x12\x04':
        raise ValueError('No supported ADX dialogue in this slot')
    off=int.from_bytes(data[2:4],'big')+4
    channels=data[7];rate,samples=struct.unpack_from('>II',data,8);cutoff=int.from_bytes(data[16:18],'big')
    if not (24<=off<=4096 and channels in (1,2) and 8000<=rate<=96000 and 0<samples<=rate*120
            and 0<cutoff<rate/2 and data[18] in (3,4) and data[19]==0):
        raise ValueError('Unsupported or excessive dialogue header')
    if len(data)>=off and data[off-6:off]!=b'(c)CRI':raise ValueError('Invalid ADX header marker')
    return Adx(off,channels,rate,samples,cutoff)


def decode(data):
    """Decode one bounded ADX voice into interleaved signed 16-bit little endian PCM."""
    h=header(data);blocks=(h.samples+31)//32
    if h.offset+blocks*18*h.channels>len(data):raise ValueError('Truncated dialogue audio')
    root2=math.sqrt(2);x=root2-math.cos(2*math.pi*h.cutoff/h.rate)
    c=(x-math.sqrt((x+root2-1)*(x-root2+1)))/(root2-1)
    # ADX coefficients are rounded from single precision to nearest integer.
    f32=lambda v:struct.unpack('<f',struct.pack('<f',v))[0]
    a,b=round(f32(2*c*4096)),round(f32(-c*c*4096))
    pcm=bytearray(h.samples*h.channels*2);history=[[0,0] for _ in range(h.channels)]
    cursor=h.offset
    for block in range(blocks):
        for channel in range(h.channels):
            scale=int.from_bytes(data[cursor:cursor+2],'big')
            if scale&0x8000:raise ValueError('Dialogue ends before its declared sample count')
            previous,older=history[channel]
            for i in range(32):
                raw=data[cursor+2+i//2];nibble=(raw>>4 if i%2==0 else raw&15)
                if nibble>=8:nibble-=16
                value=max(-32768,min(32767,nibble*scale+((a*previous+b*older)>>12)))
                older,previous=previous,value
                frame=block*32+i
                if frame<h.samples:struct.pack_into('<h',pcm,2*(frame*h.channels+channel),value)
            history[channel]=[previous,older];cursor+=18
    return h,bytes(pcm)


def inventory(iso,character,bank):
    if not (type(character) is int and 0<=character<=65535 and bank in (0,1)):raise ValueError('Invalid voice selection')
    with disc_class()(iso) as disc:
        base=voice_bases(disc.elf)[bank]+100*character;rows=[]
        for line in range(100):
            try:h=header(read(disc,base+line,4096));rows.append((line,h.seconds,None))
            except (ValueError,IndexError) as error:rows.append((line,0,str(error)))
        return rows


def load(iso,character,line,bank=0):
    if not (type(character) is int and 0<=character<=65535 and type(line) is int and 0<=line<100 and bank in (0,1)):
        raise ValueError('Invalid voice selection')
    with disc_class()(iso) as disc:
        return decode(read(disc,voice_bases(disc.elf)[bank]+100*character+line))
