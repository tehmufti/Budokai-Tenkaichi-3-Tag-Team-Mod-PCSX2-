"""High-resolution menu transition logo in an immutable DMA-referenced texture.

The 768px picture occupies a separate read-only EE reservation, outside heap1,
the loading double buffers and injected programs. GS scratch is shared with
the battle loading cover only while the menu is completely black. Re-upload
each frame because the native menu also uses this VRAM between our draws.
"""
from functools import lru_cache
from prototype import ROOT
from PIL import Image
import struct
import loading_texture_probe as gs
import loading_protocol as protocol
from regional import tbp

DATA, END = 0x06B00000, 0x06B80000
WIDTH, HEIGHT, TBP, CBP, TBW = 768, 576, tbp(0x2D00), tbp(0x3408), 12
MAGIC=0x54455831


@lru_cache(maxsize=1)
def picture():
    with Image.open(ROOT/'Tag Team Mod Logo.png') as source:
        logo=source.convert('RGB')
    h=round(WIDTH*logo.height/logo.width)
    result=Image.new('RGB',(WIDTH,HEIGHT))
    result.paste(logo.resize((WIDTH,h),Image.Resampling.LANCZOS),(0,(HEIGHT-h)//2))
    return result.quantize(256,method=Image.Quantize.MEDIANCUT,
                           dither=Image.Dither.NONE)


@lru_cache(maxsize=1)
def packet():
    pic=picture();pal=pic.getpalette()
    colours=[(*pal[i:i+3],255) for i in range(0,768,3)]
    blocks=protocol.vram_blocks(gs.PSMT8,TBP,TBW,WIDTH,HEIGHT)
    palette=protocol.vram_blocks(gs.PSMCT32,CBP,1,16,16)
    assert not blocks & palette and max(blocks|palette)<tbp(0x3480)
    out=bytearray(gs.ad_block(protocol.SETUP))
    out+=gs.upload_image(TBP,TBW,gs.PSMT8,WIDTH,HEIGHT,pic.tobytes())
    out+=gs.upload_image(CBP,1,gs.PSMCT32,16,16,gs.clut_image(colours))
    out+=gs.ad_block([(0,gs.TEXFLUSH),
        (gs.tex0(TBP,TBW,gs.PSMT8,10,10,1,1,CBP,0,0,0,1),gs.TEX0_1),
        (gs.LINEAR_TEX1,gs.TEX1_1),
        (gs.clamp1(2,2,0,WIDTH-1,0,HEIGHT-1),gs.CLAMP_1),
        (protocol.BG_SPRITE,gs.PRIM)])
    out+=gs.textured_sprite(128,128,384,320,0,0,WIDTH*16,HEIGHT*16)
    out+=gs.ad_block([(5,gs.CLAMP_1),(0,gs.TEX1_1)],eop=True)
    result=protocol.referenced(bytes(out))
    assert len(result)<END-DATA
    return result


def ready_address():
    return DATA+len(packet())


def plan(ram):
    """Publish once before arming a menu, never rewrite 444 KB every frame."""
    blob=packet()+struct.pack('<4I',MAGIC,0,0,0)
    current=bytes(ram[DATA:DATA+len(blob)])
    if current==blob:return []
    if any(current):raise ValueError('Menu logo texture reservation has a different owner')
    return [(DATA,blob)]
