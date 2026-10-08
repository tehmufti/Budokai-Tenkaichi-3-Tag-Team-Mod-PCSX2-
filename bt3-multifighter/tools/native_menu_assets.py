"""Guarded native main-menu atlas extraction/rebinding; never changes an ISO.

Menu labels are native animated image nodes, not an overlay. This module builds
owned copies of their texture descriptors and DMA payloads. Pixel data begins
0x60 bytes into the native IMAGE packet; 0x80 causes displaced/corrupted glyphs.
"""
from native_map import A
from regional import NATIVE_FONT_ASCII
from dataclasses import dataclass
import hashlib
from localization import tr
import json
import struct
import zlib
from functools import lru_cache
from pathlib import Path
from prototype import ROOT
import fonts

MAIN_OBJECT=A(0x3B0E80)
NODE_STRIDE=0xE4
LABEL_TABLE_INDICES={'off':8,'on':12}
WIDTH,HEIGHT=512,256
LABELS=('Team Battle','Free-for-all','Co-op','Modded Training',
        '1 Player','2 Players','Mod Settings','Back')
NATIVE_ROW_LAYOUTS=((0,1,2,3,5,6,7,8,9),(0,1,2,3,5,6,7,8,9,10))


def u32(r,p):
    if p<0 or p+4>len(r):raise ValueError('Native menu address out of range')
    return struct.unpack('<I',bytes(r[p:p+4]))[0]


def span(r,p,n):
    if p<0x100000 or p+n>len(r):raise ValueError('Invalid native menu asset pointer')
    return bytes(r[p:p+n])


@dataclass(frozen=True)
class Atlas:
    descriptor:int
    pixel_packet:int
    palette_packet:int
    pixel_size:int
    palette_size:int

    def indices(self,ram):return unswizzle(span(ram,self.pixel_packet+0x60,WIDTH*HEIGHT))
    def palette(self,ram):
        raw=span(ram,self.palette_packet+0x60,1024)
        return bytes(c for i in range(256) for c in raw[palette_slot(i)*4:palette_slot(i)*4+4])
    def rgba(self,ram):
        pal=self.palette(ram)
        return bytes(c for k in self.indices(ram) for c in (*pal[k*4:k*4+3],min(255,pal[k*4+3]*2)))


def palette_slot(i):return (i&0xE7)|((i&8)<<1)|((i&16)>>1)


@lru_cache(maxsize=1)
def addresses():
    return tuple(_addresses())


def _addresses():
    for y in range(HEIGHT):
        for x in range(WIDTH):
            yield ((y&~15)*WIDTH+(x&~15)*2+
                   ((((y&~3)>>1)+(y&1))&7)*WIDTH*2+
                   ((x+(((y+2)>>2)&1)*4)&7)*4+((y>>1)&1)+((x>>2)&2))


def unswizzle(data):
    if len(data)!=WIDTH*HEIGHT:raise ValueError('Expected native 512x256 indexed texture')
    return bytes(data[i]for i in addresses())


def swizzle(data):
    if len(data)!=WIDTH*HEIGHT:raise ValueError('Expected native 512x256 indexed texture')
    out=bytearray(len(data))
    for value,index in zip(data,addresses()):out[index]=value
    return bytes(out)


def atlas(ram,descriptor):
    span(ram,descriptor,64)
    tex0=struct.unpack('<Q',span(ram,descriptor+0x30,8))[0]
    if ((tex0>>20)&63,(tex0>>26)&15,(tex0>>30)&15)!=(19,9,8):
        raise ValueError('Unsupported native menu label texture format')
    pp,cp=u32(ram,descriptor+0x38),u32(ram,descriptor+0x3C)
    ps,cs=u32(ram,descriptor+8),u32(ram,descriptor+12)
    if (ps,cs)!=(0x20080,0x480):raise ValueError('Unexpected label DMA packet lengths')
    for p,size,loops in ((pp,ps,0x2000),(cp,cs,0x40)):
        data=span(ram,p,size)
        if struct.unpack_from('<Q',data,0x50)[0]!=(0x800000000000000|0x8000|loops):
            raise ValueError('Native label IMAGE packet changed')
        if tuple(struct.unpack_from('<Q',data,off)[0]for off in (0x28,0x38,0x48))!=(0x51,0x52,0x53):
            raise ValueError('Native label transfer registers changed')
    return Atlas(descriptor,pp,cp,ps,cs)


def inspect(ram):
    obj=u32(ram,MAIN_OBJECT);span(ram,obj,0x188)
    count=u32(ram,obj+0x144)
    if not 1<=count<=11:raise ValueError('Invalid native main-menu row count')
    ids=tuple(u32(ram,obj+0x118+4*i)for i in range(count))
    # Native 335568..3355C8 skips row 4 and appends row 10 only when the
    # save's seven Dragon Ball bits are all set. New saves have nine rows.
    # Keep the exact native order; arbitrary subsets/duplicates are not safe.
    if ids not in NATIVE_ROW_LAYOUTS:
        raise ValueError(f'Unexpected native USA menu rows: {ids!r}')
    tree=u32(ram,obj+0x34);nodes=u32(ram,tree);n=u32(ram,tree+4)
    if n!=72:raise ValueError('Unexpected native menu node count')
    # Highlight instances follow movie timelines, including the first slot at
    # 3. Main-menu readiness precedes that slot's construction on scene return;
    # its name can be blank, just like the other highlighted plate instances.
    # Their presence/count is not an asset-version signature.
    # Read the table together and validate its actual label slots instead.
    table=span(ram,nodes,n*NODE_STRIDE)
    names=[table[i*NODE_STRIDE:i*NODE_STRIDE+64].split(b'\0')[0] for i in range(n)]
    off_slots=(1,28,33,38,43,48,53)
    on_slots=(3,30,35,40,45,50,55)
    if (tuple(i for i,name in enumerate(names) if name==b'mc_menu_text_off')!=off_slots
            or any(names[i] not in (b'',b'mc_menu_text_on') for i in on_slots)
            or any(name==b'mc_menu_text_on' and i not in on_slots for i,name in enumerate(names))):
        raise ValueError('Native animated label nodes changed')
    found={name:atlas(ram,u32(ram,obj+0x40+4*i))for name,i in LABEL_TABLE_INDICES.items()}
    return obj,found


_COMPOSE_CACHE={}


def label_key(palette,labels,font_path):
    # Bound baked pixels to the actual font, palette and labels. A changed
    # installation/theme safely falls back to the ordinary generator. Off
    # Windows the layout engine and Pillow version are bound too (the tag is
    # empty on Windows, so its baked keys are unchanged).
    return hashlib.sha256(palette+json.dumps(tuple(labels)).encode()+Path(font_path).read_bytes()+fonts.render_tag()).hexdigest()


@lru_cache(maxsize=1)
def baked_labels():
    try:
        records=json.loads(Path(__file__).with_name('native_menu_labels.json').read_text(encoding='utf-8'))
        return records if isinstance(records,dict) else {}
    except (OSError,ValueError):return {}


def compose_indices(ram,source,labels=LABELS,font_path=None):
    """Generate atlas rows in the game's own palette and native on/off colors."""
    if len(labels)>8 or any(not isinstance(t,str)or not t for t in labels):
        raise ValueError('Expected one to eight nonempty menu labels')
    font_path=font_path or fonts.path('sans-bold')
    cache_key=(source.palette(ram),tuple(labels),str(font_path))
    if cache_key in _COMPOSE_CACHE:return _COMPOSE_CACHE[cache_key]
    try:
        record=baked_labels().get(label_key(cache_key[0],labels,font_path))
        if isinstance(record,dict):
            # Bounded decompression even if a cache file was damaged.
            decoder=zlib.decompressobj();pixels=decoder.decompress(bytes.fromhex(record['data']),WIDTH*HEIGHT+1)
            if (decoder.eof and len(pixels)==WIDTH*HEIGHT and
                    hashlib.sha256(pixels).hexdigest()==record['sha256']):
                _COMPOSE_CACHE[cache_key]=pixels;return pixels
    except (OSError,KeyError,TypeError,ValueError,zlib.error):pass
    from PIL import Image,ImageDraw
    import numpy as np
    font=fonts.truetype(str(font_path),22)
    im=Image.new('RGBA',(WIDTH,HEIGHT));d=ImageDraw.Draw(im)
    # Native off state is lavender outlined in dark purple; on is warm orange.
    native=Image.frombytes('RGBA',(WIDTH,HEIGHT),source.rgba(ram))
    colors=np.array(native).reshape(-1,4)
    opaque=colors[colors[:,3]>=250,:3]
    warm=float(opaque[:,0].mean())>float(opaque[:,2].mean())
    fill=(247,171,97,255) if warm else (181,153,185,255)
    outline=(71,24,19,255) if warm else (81,34,92,255)
    for i,label in enumerate(labels):
        box=d.textbbox((5,i*32+1),label,font=font,stroke_width=2)
        if box[2]>WIDTH-5:raise ValueError('Native menu label exceeds atlas row')
        d.text((5,i*32+1),label,font=font,fill=fill,stroke_width=2,stroke_fill=outline)
    pixels=np.asarray(im,dtype=np.int32).reshape(-1,4)
    pal=np.frombuffer(source.palette(ram),dtype=np.uint8).reshape(256,4).astype(np.int32)
    pal[:,3]=np.minimum(255,pal[:,3]*2)
    # Transparent RGB must not select opaque black. Premultiplication also
    # preserves the stock palette's soft outline and antialiasing choices.
    pixels[:,:3]=pixels[:,:3]*pixels[:,3,None]//255
    pal[:,:3]=pal[:,:3]*pal[:,3,None]//255
    # Most of the atlas is transparent, with repeated glyph colors elsewhere.
    # Match each distinct RGBA value once, keeping the exact previous distance
    # and tie-breaking rules. The cold main-menu path no longer compares all
    # 131072 pixels against256 colors twice before accepting Select.
    colors,inverse=np.unique(pixels,axis=0,return_inverse=True)
    mapped=np.empty(len(colors),dtype=np.uint8)
    for start in range(0,len(colors),2048):
        dif=colors[start:start+2048,None,:]-pal[None,:,:]
        mapped[start:start+2048]=np.argmin(np.sum(dif*dif,axis=2),axis=1)
    result=mapped[inverse].tobytes()
    if len(_COMPOSE_CACHE)>=8:_COMPOSE_CACHE.clear()
    _COMPOSE_CACHE[cache_key]=result
    return result


def clone(ram,source,destination,indices):
    """Owned descriptor + original DMA headers/palette with replaced pixel data.

    The native image table is rebound to this descriptor, never to an RGB overlay.
    The original package and its allocator ownership remain untouched.
    """
    if destination&63:raise ValueError('Owned atlas must be 64-byte aligned')
    descriptor=bytearray(span(ram,source.descriptor,64))
    pp=destination+64;cp=pp+source.pixel_size
    struct.pack_into('<II',descriptor,0x38,pp,cp)
    pix=bytearray(span(ram,source.pixel_packet,source.pixel_size))
    pix[0x60:0x60+WIDTH*HEIGHT]=swizzle(indices)
    pal=span(ram,source.palette_packet,source.palette_size)
    return bytes(descriptor)+bytes(pix)+pal


DESCRIPTIONS = (
    ('Fight with every selected teammate\non the battlefield at the same time.',
     'Every fighter is an opponent.\nChoose one to four players, or CPUs.',
     'Two to four players share Team 1.\nSelect an ally for every human player.',
     'Practice with selected team rosters.\nSet CPU behavior and refill in Mod settings.\nOriginal Training stays in the original menu.', '', '', 'Adjust the mod with your controller.\nSave changes for your next match.', ''),
    ('', '', '', '',
     'Control Team 1 against CPU opponents.\nChoose the fighters for each team.',
     'Player 1 faces Player 2.\nAdd CPU teammates on either side.',
     'Watch two teams of CPU fighters.\nChoose the fighters for each team.',
     'Return to the mod mode groups.'),
    ('', '', '', '',
     'One player against every other fighter.\nAll remaining fighters are CPUs.',
     'Two players fight each other and CPUs.\nEvery fighter is an opponent.',
     'Watch a free-for-all between CPUs.\nEvery fighter is an opponent.',
     'Return to the mod mode groups.'),
    ('', '', '', '', '',
     'Two players share Team 1.\nChoose at least two Team 1 fighters\nand one or more CPU opponents.', '',
     'Return to the mod mode groups.'),
    ('', '', 'Two to four allies practice together.\nSelect an ally for every human player\nand one or more CPU opponents.', '',
     'Practice with one human and CPU fighters.\nChoose CPU behavior and refill in Mod settings.',
     'Practice with a human on each side.\nAdd CPU fighters to either team.', '',
     'Return to the mod mode groups.'))


def native_text(text):
    """The mod's own text as the game font can draw it. The Japanese font has the printable ASCII letters but no
    accented Latin ones: Spanish accents fold to their base letter there (inverted marks to plain ones)."""
    if not NATIVE_FONT_ASCII:
        return text
    import unicodedata
    text = text.replace('\u00bf', '?').replace('\u00a1', '!').replace('\u00ab', '"').replace('\u00bb', '"')
    folded = ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))
    return ''.join(c if c == '\n' or 32 <= ord(c) < 127 else '?' for c in folded)


def dbt(strings):
    """Native DBT offset table: UTF-16 BOM strings aligned to 64 bytes."""
    out=bytearray((4+4*len(strings)+63)&~63)
    struct.pack_into('<I',out,0,len(strings))
    for i,text in enumerate(strings):
        struct.pack_into('<I',out,4+i*4,len(out))
        out.extend(('\ufeff'+text+'\0').encode('utf-16le'))
        out.extend(bytes((-len(out))&63))
    return bytes(out)


def descriptions(ram,obj,button='Select',show_hint=True,settings=None):
    hint='['+button+']: '+tr('Original game menu',settings) if show_hint else ''
    custom=dbt([native_text(tr(text,settings)+('\n'+hint if hint else '')) for page in DESCRIPTIONS for text in page])
    source=u32(ram,obj+8)
    if u32(ram,source)!=64 or u32(ram,source+4)!=0x140:
        raise ValueError('Native main-menu DBT changed')
    strings=[]
    for i in range(64):
        off=u32(ram,source+4+i*4)&~3
        raw=span(ram,source+off,2048)
        end=next((j for j in range(0,len(raw)-1,2)if raw[j:j+2]==b'\0\0'),None)
        if end is None:raise ValueError('Unterminated native menu text')
        text=raw[:end].decode('utf-16le').lstrip('\ufeff')
        if show_hint:text+=native_text('\n['+button+']: '+tr('Mod modes',settings))
        strings.append(text)
    return custom,dbt(strings)

# Submenus reuse the root-only label row for Four Players in a second owned
# atlas. Keep native 512x256 uploads and UVs unchanged, including CPU Only.
DESCRIPTIONS=tuple(tuple((
    'Four players, two on each team.\nSelect at least two fighters per team.' if page==1 else
    'Four players and any selected CPUs.\nSelect at least four fighters total.' if page==2 else
    'Four players share Team 1.\nSelect at least four Team 1 fighters.' if page==3 else
    'Four players practice on two teams.\nSelect at least two fighters per team.' if page==4 else text
) if row==0 and page else text for row,text in enumerate(texts))
    for page,texts in enumerate(DESCRIPTIONS))
DESCRIPTIONS += (('Four allies practice against CPUs.\nSelect at least four Team 1 fighters.', '', '', '', '',
                 'Two allies practice against CPUs.\nSelect at least two Team 1 fighters.', '',
                 'Return to Modded Training.'),)

# Row 1 is only reused on submenus; the root keeps its Free-for-all label.
THREE_DESCRIPTIONS={1:"Three players: P1 and P3 on Team 1.\nP2 on Team 2. Add CPU fighters as desired.",2:"Three players and any selected CPUs.\nSelect at least three fighters total.",3:"Three allies share Team 1.\nSelect at least three Team 1 fighters.",4:"Three players practice on two teams.\nP1/P3 on Team 1; P2 on Team 2.",5:"Three allies practice against CPUs.\nSelect at least three Team 1 fighters."}
DESCRIPTIONS=tuple(tuple(THREE_DESCRIPTIONS[page] if row==1 and page else text for row,text in enumerate(texts)) for page,texts in enumerate(DESCRIPTIONS))

# Co-op is a team assignment, no longer a separate visible mode or submenu.
DESCRIPTIONS=tuple(tuple(
    'Choose each player team before character select.\nShare a team for cooperative play.\nAdd CPU fighters to either team.'
    if page in (1,4) and row in (0,1,5) else text
    for row,text in enumerate(texts)) for page,texts in enumerate(DESCRIPTIONS))
