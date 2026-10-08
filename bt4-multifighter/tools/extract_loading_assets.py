"""Extract actual English names and selection portraits from the user's USA ISO.

Reads AFS1 entry450, its second byte-pair compressed package, then native
package entries29/30/31. No network assets or generated character art.
The European disc's English set is file 455. The Japanese disc's set (file 450)
names fighters in kanji/kana only: its portraits come from the disc and its
English names from bt3_english_names.json (regional.english_names).
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def package(data):
    if len(data) < 8: raise ValueError('Truncated package')
    count = struct.unpack_from('<I', data)[0]
    if not 0 < count <= 4096 or 4*(count+2) > len(data):
        raise ValueError('Invalid package count')
    offsets = struct.unpack_from('<'+str(count+1)+'I', data, 4)
    if offsets[0] < 4*(count+2) or offsets[-1] > len(data) or any(a >= b for a,b in zip(offsets,offsets[1:])):
        raise ValueError('Invalid package offsets')
    return [data[a:b] for a,b in zip(offsets,offsets[1:])]


def unpack_bpe(data):
    """Gage byte-pair blocks, preceded by the native output/input lengths."""
    if len(data) < 8: raise ValueError('Truncated compressed header')
    expected, packed = struct.unpack_from('<II', data)
    if not 0 < expected <= 16*1024*1024 or not 0 < packed <= len(data)-8:
        raise ValueError('Invalid compressed lengths')
    data = data[:packed+8]; cursor=8; output=bytearray()
    def byte():
        nonlocal cursor
        if cursor >= len(data): raise ValueError('Truncated compressed block')
        value=data[cursor];cursor+=1;return value
    while len(output) < expected:
        left=list(range(256));right=[0]*256; code=0
        while code < 256:
            count=byte()
            if count > 127: code+=count-127;count=0
            if code >= 256: break
            for _ in range(count+1):
                if code >= 256: raise ValueError('Dictionary overrun')
                left[code]=byte()
                if left[code] != code:right[code]=byte()
                code+=1
        length=byte()*256+byte()
        if not length or cursor+length > len(data): raise ValueError('Invalid compressed block length')
        for value in data[cursor:cursor+length]:
            stack=[(value,0)]
            while stack:
                code,depth=stack.pop()
                if depth >= 256:raise ValueError('Cyclic byte-pair dictionary')
                if left[code] == code:
                    output.append(code)
                    if len(output) > expected:raise ValueError('Decompression overflow')
                else:stack.extend(((right[code],depth+1),(left[code],depth+1)))
        cursor+=length
    if cursor != len(data):raise ValueError('Unused compressed bytes')
    return bytes(output)


def english_label(data):
    if not data.startswith(b'\xff\xfe'):raise ValueError('Expected native UTF16 label')
    # Native fixed slots contain stale padding after the printable Latin label.
    # Stop at the first terminator/non-Latin padding code point.
    text=[]
    for pos in range(2,len(data)-1,2):
        code=struct.unpack_from('<H',data,pos)[0]
        if not (32 <= code <= 126 or code in (0xAA,0xB0,0xBA) or
                (192 <= code <= 255 and chr(code).isalpha())):break
        text.append(chr(code))
    return ''.join(text).strip()


def portrait_rgba(data):
    """Native64x64 PSMT8, uploaded as32x32 PSMCT32 plus CSM1 palette."""
    if len(data)!=0x1580:raise ValueError('Unexpected portrait size')
    tex0=struct.unpack_from('<Q',data,0x50)[0]
    if ((tex0>>20)&63,(tex0>>26)&15,(tex0>>30)&15)!=(19,6,6):
        raise ValueError('Unexpected portrait texture layout')
    pixels=data[0xC0:0x10C0];palette=data[0x1140:0x1540];colors=[]
    for index in range(256):
        entry=(index&0xE7)|((index&8)<<1)|((index&16)>>1)
        red,green,blue,alpha=palette[entry*4:entry*4+4]
        colors.append(bytes((red,green,blue,min(255,alpha*2))))
    output=bytearray()
    for y in range(64):
        for x in range(64):
            block=(y&~15)*64+(x&~15)*2
            swap=(((y+2)>>2)&1)*4
            row=(((y&~3)>>1)+(y&1))&7
            source=block+row*128+((x+swap)&7)*4+((y>>1)&1)+((x>>2)&2)
            output.extend(colors[pixels[source]])
    return bytes(output)


def extract(iso_path, destination=ROOT/'assets'):
    import pycdlib
    from PIL import Image
    import regional
    if regional.DISC_REGION!='US':
        # The European English text set: file 455 (USA 451, AFS1 index 450), read by the disc's own numbering; the
        # Japanese text set: file 450.
        raw=regional.read_disc_file(iso_path,451)
    else:
        iso=pycdlib.PyCdlib();iso.open(str(iso_path))
        try:
            with iso.open_file_from_iso(iso_path='/DATA/PZS3US1.AFS;1') as stream:
                magic,count=struct.unpack('<4sI',stream.read(8))
                if magic!=b'AFS\0' or count!=3399:raise ValueError('Expected USA AFS1 archive')
                table=stream.read(count*8);offset,size=struct.unpack_from('<II',table,450*8)
                stream.seek(offset);raw=stream.read(size)
        finally:iso.close()
    ui=package(unpack_bpe(package(raw)[1]))
    names,forms,portraits=package(ui[29]),package(ui[30]),package(ui[31])
    if (len(names),len(forms),len(portraits))!=(168,168,165):raise ValueError('Unexpected English UI tables')
    entries=[];decoded=[]
    english=regional.english_names() if regional.TEXT_LANGUAGE!='en' else None
    for index in range(161):
        base,form=english[index] if english else (english_label(names[index]),english_label(forms[index]))
        if not base:raise ValueError(f'Empty character name{index}')
        name=base+(f' - {form}' if form else '')
        entries.append(dict(character_id=index,name=name,base_name=base,form=form,
                            portrait=f'portraits/{index:03d}.png',bitmap=f'portraits/{index:03d}.bmp'))
        decoded.append(portrait_rgba(portraits[index]))
    if entries[0]['base_name']!='Goku (Early)' or entries[55]['base_name']!='Hercule' or entries[133]['form']!='Legendary Super Saiyan':
        raise ValueError('Character identity validation failed')
    destination=Path(destination);(destination/'portraits').mkdir(parents=True,exist_ok=True)
    for row,pixels in zip(entries,decoded):
        image=Image.frombytes('RGBA',(64,64),pixels);image.save(destination/row['portrait'])
        background=Image.new('RGB',(64,64),(17,24,39));background.paste(image,mask=image.getchannel('A'))
        background.save(destination/row['bitmap'])
    manifest=dict(source=('User-owned SLES-54945 ISO / DATA/PZS3EU1.AFS / file 455 / package1' if regional.PAL else
                          'User-owned SLPS-25815 ISO / DATA/PZS3JP1.AFS / file 450 / package1 portraits; English names '
                          + regional.ENGLISH_NAMES if regional.DISC_REGION=='JP' else
                          'User-owned SLUS-21978 ISO / DATA/PZS3US1.AFS / index450 / package1'),
        source_sha256=hashlib.sha256(raw).hexdigest(),native_entries=dict(names=29,forms=30,portraits=31),characters=entries)
    (destination/'characters.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('iso',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'assets');args=parser.parse_args()
    result=extract(args.iso,args.output);print(f"Extracted {len(result['characters'])} real names and portraits")
