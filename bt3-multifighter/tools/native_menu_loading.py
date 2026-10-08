"""Small animated loading indication in the native GS frame, after its fade.

Uses the existing verified loading sprite packet format and GIF arena guards.
Artwork uses the native palette/style and a high-resolution DMA texture.
"""
from native_map import A
from functools import lru_cache
import fonts
from prototype import Assembler, ROOT
from regional import Y_ORIGIN
from native_map import GPO
CODE,DATA,END=0x07697400,0x076F6000,0x076FF000
CONTROL=0x076FF000
DECODE=0x07691000


@lru_cache(maxsize=2)
def packets(language='en'):
    from PIL import Image,ImageDraw
    import guest_loading_screen as gs
    # Palette quantization rounds near-black keys to black. Use actual black
    # so the text packet cannot paint over the logo submitted before it.
    key=(0,0,0);im=Image.new('RGB',(512,448),key);d=ImageDraw.Draw(im)
    font=fonts.truetype('sans-bold',22)
    # Match the warm native highlighted text and dark purple outline.
    d.text((326,389),'Cargando' if language=='es' else 'Now Loading',font=font,fill=(247,171,97),stroke_width=2,stroke_fill=(81,34,92))
    # A small fixed palette keeps the packet bounded and the native glyph edge.
    palette=Image.new('P',(1,1));colors=[key,(247,171,97),(81,34,92),(181,153,185)]
    palette.putpalette([v for rgb in colors for v in rgb]+[0]*(768-12))
    im=im.quantize(palette=palette,dither=Image.Dither.NONE).convert('RGB')
    base=gs.gif_packet(gs.image_rectangles(im,key=key))
    dots=[]
    for frame in range(4):
        dots.append(gs.gif_packet([(442+i*11,424,447+i*11,429,(247,171,97)if i<frame else(81,34,92))for i in range(3)]))
    assert len({len(b)for b in dots})==1
    assert len(encode(base))+sum(map(len,dots))<END-DATA
    return base,tuple(dots)


def encode(packet):
    import struct
    count=struct.unpack_from('<Q',packet,96)[0]&0x7fff
    colors=[];records=bytearray()
    for off in range(112,112+count*24,24):
        color,xy0,xy1=struct.unpack_from('<3Q',packet,off)
        if color not in colors:colors.append(color)
        assert len(colors)<=16
        # Screen rows of this disc's frame (gif_packet already stretched them on a 512-line frame).
        x0,y0=(xy0&65535)//16-1792,((xy0>>16)&65535)//16-Y_ORIGIN
        x1,y1=(xy1&65535)//16-1792,((xy1>>16)&65535)//16-Y_ORIGIN
        assert all(0<=v<512 for v in (x0,y0,x1-1,y1-1)), (x0,y0,x1,y1,hex(xy0),hex(xy1))
        records.extend((x0|(y0<<9)|((x1-1)<<18)|((y1-1)<<27)|(colors.index(color)<<36)).to_bytes(5,'little'))
    blob=packet[:112]+struct.pack('<16Q',*(colors+[0]*(16-len(colors))))+records
    return blob+bytes(-len(blob)%16)


def decode_payload():
    # v0 destination, t0 encoded source; a0 returns the aligned packet end.
    a=Assembler(DECODE)
    for off in range(0,112,4):a.lw(9,8,off);a.sw(9,2,off)
    a.move(5,8);a.addiu(5,5,112);a.addiu(6,8,240)
    a.lw(7,8,96);a.i(12,7,7,0x7fff);a.addiu(4,2,112)
    a.label('rectangle');a.move(9,0)
    for i in range(5):
        a.i(36,10,6,i)
        if i:a.r(0x3C if i==4 else 0x38,10,0,10,0 if i==4 else i*8)
        a.r(0x25,9,9,10)
    a.r(0x3E,10,0,9,4);a.r(0,10,0,10,3);a.r(0x21,10,10,5)
    a.i(55,10,10,0);a.i(63,10,4,0)
    for shift,off in ((0,8),(18,16)):
        a.r(0x3A,10,0,9,shift);a.i(12,11,10,511);a.r(0x3A,12,0,10,9);a.i(12,12,12,511)
        a.addiu(11,11,1792+int(bool(shift)));a.addiu(12,12,Y_ORIGIN+int(bool(shift)))
        a.r(0,11,0,11,4);a.r(0,12,0,12,20);a.r(0x25,11,11,12)
        a.sw(11,4,off);a.sw(0,4,off+4)
    a.addiu(6,6,5);a.addiu(4,4,24);a.addiu(7,7,-1);a.branch(5,7,0,'rectangle')
    a.i(12,8,4,15);a.branch(4,8,0,'done');a.sw(0,4);a.sw(0,4,4);a.addiu(4,4,8)
    a.label('done');a.jr();blob=a.finish();assert len(blob)<0x1000;return blob


def preview():
    from PIL import Image,ImageDraw
    from test_guest_loading_screen import decode
    import native_menu_texture as texture
    base,dots=packets();out=Image.new('RGB',(512*4,448),(0,0,0));d=ImageDraw.Draw(out)
    for frame,dot in enumerate(dots):
        out.paste(texture.picture().convert('RGB').resize((256,192),Image.Resampling.LANCZOS),(128+512*frame,128))
        for x0,y0,x1,y1,rgb in decode(base)+decode(dot):d.rectangle((x0+512*frame,y0,x1-1+512*frame,y1-1),fill=rgb)
    return out


def payload():
    import native_menu_services as svc
    import native_menu_texture as texture
    base,dots=packets();spanish=packets('es')[0]
    spanish_at=DATA+len(encode(base));dots_at=spanish_at+len(encode(spanish))
    need=max(len(base),len(spanish))+len(dots[0])+128
    a=Assembler(CODE);svc.save(a)
    # This helper is called only by the scoped fade wrapper while fully black.
    a.li(8,texture.ready_address());a.lw(9,8);a.li(10,texture.MAGIC);a.branch(5,9,10,'done')
    a.lw(8,28,-23004);a.i(11,9,8,2);a.branch(4,9,0,'done')
    a.r(0,8,0,8,2);a.r(0x2D,8,28,8)
    # t0 = gp + 4*index: the arena base/end offsets are gp offsets through another register (GPO by hand).
    a.lw(9,8,GPO(-23024));a.lw(10,8,GPO(-23016));a.lw(11,28,-23008)
    a.r(0x2D,11,11,9);a.branch(5,11,10,'done')
    a.lw(11,28,-23000);a.r(0x2B,12,11,9);a.branch(5,12,0,'done')
    a.li(12,need);a.r(0x2D,12,11,12);a.r(0x2B,13,12,11);a.branch(5,13,0,'done')
    a.r(0x2B,13,10,12);a.branch(5,13,0,'done')
    a.li(8,CONTROL);a.lw(9,8,72);a.addiu(9,9,1);a.sw(9,8,72)
    a.r(3,9,0,9,3);a.i(12,9,9,3);a.sw(9,29,0xA0)
    def copy(tag,size):
        a.li(9,size);a.r(0x21,9,8,9);a.move(10,2)
        a.label(tag)
        for off in (0,8):a.i(55,11,8,off);a.i(63,11,10,off)
        a.addiu(8,8,16);a.addiu(10,10,16);a.branch(5,8,9,tag)
        a.move(4,10);a.call(A(0x100890))
    a.li(4,texture.DATA);a.li(5,len(texture.packet()));a.call(A(0x100738))
    a.call(A(0x100878))
    # Both pictures ship in the same immutable boot payload. The existing menu
    # language flag selects one; saving Language needs no code/hash changes.
    a.li(8,CONTROL);a.lw(9,8,0xD8);a.li(8,DATA);a.addiu(10,0,1)
    a.branch(5,9,10,'loading_text');a.li(8,spanish_at)
    a.label('loading_text');a.call(DECODE);a.call(A(0x100890))
    a.call(A(0x100878));a.li(8,dots_at);a.lw(9,29,0xA0)
    a.label('offset');a.branch(4,9,0,'dots');a.addiu(8,8,len(dots[0]));a.addiu(9,9,-1);a.jump('offset')
    a.label('dots');copy('copy_dots',len(dots[0]))
    # The next native menu frame must reload its overwritten sprite texture.
    a.li(8,A(0x2FE9C8));a.lw(8,8);a.li(9,0x100000);a.r(0x2B,9,8,9);a.branch(5,9,0,'done')
    a.li(9,0x08000000-0x234);a.r(0x2B,9,8,9);a.branch(4,9,0,'done');a.sw(0,8,0x230)
    a.call(A(0x21F438))
    a.label('done');svc.restore(a);a.jr();return a.finish()


def code_pieces():
    import native_menu_texture as texture
    base,dots=packets();code=payload();assert len(code)<0x400
    blob=encode(base)+encode(packets('es')[0])+b''.join(dots)
    assert len(blob)<=END-DATA
    return [(CODE,code+bytes(0x400-len(code))),(DECODE,decode_payload()),(DATA,blob+bytes(END-DATA-len(blob)))]
