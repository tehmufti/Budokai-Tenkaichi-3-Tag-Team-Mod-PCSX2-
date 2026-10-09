"""Execute stock retained KO, dispatcher, get-up and locomotion selection.

Model bundle binding/render/physics leaves are fixture callbacks. Actual action
handlers, HP/flag predicates, queue/dispatcher reset and animation completion
clock execute the original USA ELF, rather than a mocked revival transition.
"""
import struct
import unittest
from prototype import ROOT, elf_reader
from test_fusion_partner_lifecycle import FusionCpu

NATIVE=elf_reader(ROOT/'analysis/SLUS_216.78')[2]
ACTOR, MODEL=0x1900000,0x900000

class Cpu(FusionCpu):
    def extra_instruction(self,ins,pc):
        if ins>>26==17 and (ins>>21)&31==16 and ins&63==50:
            self.condition=self.number((ins>>11)&31)==self.number((ins>>16)&31);return
        return super().extra_instruction(ins,pc)

def fixture(air=False,actor=ACTOR,model=MODEL):
    c=Cpu();c.events=[]
    ranges=((0x1E23D0,0x1E0),(0x1E9EC8,0x3D0),(0x1EA920,0x410),
            (0x1DC2D0,0x78),(0x1CE1B8,0x20),(0x1CE030,0x38),
            (0x1DA9D0,0x318),(0x1E0290,0x118),(0x1E0A20,0x98),
            (0x1C47A8,0x110),(0x204DB0,0x48),(0x2012D8,0x108),
            (0x2013E0,0xA38),(0x2C4980,0x600),(0x2EF900,0x100))
    for p,n in ranges:c.write(p,NATIVE(p,n))
    c.write(c.r[28]-0x7300,NATIVE(c.r[28]-0x7300,0xB00))
    for off,val in ((0x948,216),(0x950,216),(0x964,91),(0x994,0),(0x998,1),
                    (0x9E4,0),(0x9E8,30000),(0xFB0,1)):
        c.w(actor+off,val)
    for off in (0x94C,0x954,0x958,0x95C,0x960):c.w(actor+off,-1)
    c.w(actor+0x10AD+((0x11 if air else 0xF)>>3),1<<((0x11 if air else 0xF)&7))
    c.w(model+4,1);c.w(model+8,1)
    c.callbacks[0x1DC280]=lambda m:m.r.__setitem__(2,model)
    c.callbacks[0x1DC298]=lambda m:m.r.__setitem__(2,actor+16)
    def animation(m):
        m.events.append(('animation',m.r[5]));m.w(actor+0x974,m.r[5])
        m.fw(model+0xB44,30.);m.fw(model+0xC78,0.);m.fw(model+0xC80,1.)
        m.fw(model+0xC84,0.);m.fw(model+0xC88,1.)
    c.callbacks[0x1C3E60]=animation
    c.callbacks[0x1C4638]=lambda m:m.r.__setitem__(2,m.u(m.r[4]+0x974))
    c.callbacks[0x1C4650]=lambda m:m.r.__setitem__(2,0)
    c.callbacks[0x1D4F30]=lambda m:m.r.__setitem__(2,0)
    c.callbacks[0x1DC480]=lambda m:m.r.__setitem__(2,0)
    c.callbacks[0x204748]=lambda m:m.r.__setitem__(2,0)
    c.callbacks[0x1E0510]=lambda m:m.set_number(0,0.)
    c.callbacks[0x204EA0]=lambda m:m.set_number(0,20.)
    c.callbacks[0x1C46A8]=lambda m:m.set_number(0,0.)
    # These are unrelated scene, physics, input event, sound and animation
    # blend leaves. They do not own the action queue or positive HP transition.
    for p in (0x1DA970,0x1E12D0,0x1D7320,0x1C7A88,0x1E1288,0x1E16C0,
              0x1E1D20,0x1DE080,0x1DEDF8,0x1DF1A0,0x1DA370,0x1DD258,
              0x1C42A8,0x1C42F0,0x1C4338,0x1C4920,0x1DED28,0x1296B8):c.callbacks[p]=lambda m:None
    c.callbacks[0x1E7F38]=lambda m:m.r.__setitem__(2,m.r[5])
    c.callbacks[0x1E80C0]=lambda m:m.r.__setitem__(2,0)
    c.callbacks[0x2A9ACC]=lambda m:m.write(m.r[4],bytes([m.r[5]&255])*m.r[6])
    return c

def dispatch(c,actor=ACTOR):c.r[4]=actor;c.r[31]=0xFEED0000;c.run(0x1E23D0)
