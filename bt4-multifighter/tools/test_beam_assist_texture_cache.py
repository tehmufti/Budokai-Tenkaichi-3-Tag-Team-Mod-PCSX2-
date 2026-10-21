"""Native producer parity, shared components and the multi-helper VRAM load."""
import struct,unittest
from pathlib import Path as _TestPath
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise unittest.SkipTest('An extracted game executable is required for native assist tests')
import beam_assist_texture_cache as cache
import beam_assist_effects as fx
import texture_queue_guard as guard
import fresh_team_combat as core
from test_beam_assist_effects import machine as emitter_machine
from test_tag_rush_scene import SceneCpu as EffectCpu
from test_tag_rush_camera import run

GP,Q,DESCRIPTOR,TEXTURE=0x304270,0x1B1E1E0,0x1C00000,0x1C10000
MASK64=(1<<64)-1

class Cpu(EffectCpu):
    def extra_instruction(self,ins,pc):
        op,fn=ins>>26,ins&63
        rt,rd,sa=(ins>>16)&31,(ins>>11)&31,(ins>>6)&31
        if op==0 and fn in (0x38,0x3C,0x3E):
            value=self.r[rt]&MASK64
            self.r[rd]=((value<<(sa+(32 if fn==0x3C else 0)))&MASK64 if fn!=0x3E
                        else value>>(sa+32))
            return
        if op==39:
            rs,imm=(ins>>21)&31,ins&65535
            address=(self.r[rs]+(imm if imm<32768 else imm-65536))&0xFFFFFFFF
            self.r[rt]=self.u(address);return
        return super().extra_instruction(ins,pc)

def machine():
    c=emitter_machine();c.__class__=Cpu
    for i in range(3):c.write(cache.BASE+i*cache.STRIDE,cache.code(i))
    c.w(GP+guard.QUEUE_GP,Q);c.w(Q+0x800,0);c.w(Q+0x804,0x2B00);c.w(Q+0x808,0x2A00)
    return c

def texture(c,index=0,header=None):
    d=DESCRIPTOR+index*16;h=TEXTURE+index*64 if header is None else header
    c.write(d,struct.pack('<Q',0x0123456789ABCDEF));c.w(d+8,h)
    c.w(h+16,16);c.w(h+20,4)
    return d

def acquire(c,d,kind=0):
    c.r[4:7]=[d,1,2];run(c,cache.BASE+kind*cache.STRIDE)
    return c.r[2]&MASK64

class CacheTests(unittest.TestCase):
    def test_different_palettes_share_pixels_without_sharing_colours(self):
        c=machine();a=texture(c,0);b=texture(c,1)
        for h in (TEXTURE,TEXTURE+64):c.w(h+56,0x2000000)
        first,second=acquire(c,a),acquire(c,b)
        self.assertEqual(first&0x3FFF,second&0x3FFF)
        self.assertNotEqual((first>>37)&0x3FFF,(second>>37)&0x3FFF)
        self.assertEqual(c.u(Q+0x804),0x2B18)

    def test_repeated_headers_and_partial_requests_share_one_upload(self):
        c=machine();d=texture(c)
        image=acquire(c,d,1);self.assertEqual(image&0x3FFF,0x2B00)
        clut=acquire(c,d,2);self.assertEqual(clut,0x2B10)
        full=acquire(c,d);self.assertEqual(full&0x3FFF,0x2B00)
        self.assertEqual((full>>37)&0x3FFF,clut)
        same=texture(c,1,TEXTURE)
        for _ in range(10):self.assertEqual(acquire(c,same),full)
        self.assertEqual(c.u(Q+0x800),1);self.assertEqual(c.u(Q+0x804),0x2B14)
        self.assertEqual(c.u(Q+0x808),0x2B14)

    def test_eight_helpers_and_native_effects_do_not_overlap(self):
        c=machine();ranges=[]
        # Captured BT4 peak:40 other headers, ten per assistant. The native
        # image/palette producers submit two rows for most of these headers.
        for i in range(120):
            d=texture(c,i);image=acquire(c,d,1)&0x3FFF;palette=acquire(c,d,2)
            ranges.extend(((image,image+16),(palette,palette+4)))
        self.assertEqual(c.u(Q+0x800),120)
        self.assertTrue(all(b<=d for (_,b),(d,_)in zip(sorted(ranges),sorted(ranges)[1:])))
        self.assertLessEqual(c.u(Q+0x804),0x3480)
        # A second viewport uses the same allocations, not another upload.
        for i in range(120):acquire(c,DESCRIPTOR+i*16)
        self.assertEqual(c.u(Q+0x800),120)

    def test_texture_register_keeps_native_mask_and_caller_mode(self):
        for kind in (0,1):
            c=machine();d=texture(c);initial=struct.unpack('<Q',c.read(d,8))[0]
            result=acquire(c,d,kind);base=initial&0xFFF80003FFFFC000
            expected=base|(1<<34)|(2<<35)|0x2B00
            if kind==0:expected|=0x2B10<<37
            self.assertEqual(result,expected);self.assertEqual(struct.unpack('<Q',c.read(d,8))[0],base)

    def test_full_queue_or_other_match_keeps_existing_guard(self):
        for scenario in ('full','other','disabled'):
            c=machine();d=texture(c);called=[]
            c.callbacks[guard.CODE]=lambda m:called.append(m.r[4])
            if scenario=='full':c.w(Q+0x800,128)
            elif scenario=='other':c.w(fx.CONTROL+fx.C['manager'],123)
            else:c.w(fx.CONTROL+fx.C['ready'],0)
            if scenario=='full':
                for i in range(128):c.w(Q+i*16,DESCRIPTOR+0x1000);c.w(DESCRIPTOR+0x1008,TEXTURE+0x1000)
            acquire(c,d);self.assertEqual(called,[d])

if __name__=='__main__':unittest.main()
