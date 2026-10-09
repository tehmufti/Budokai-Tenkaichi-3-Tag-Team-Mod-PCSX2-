"""Minimal synthetic actors and native-fusion fixtures for the release regressions."""
import struct
import support
import fusion_partner_lifecycle as fusion
import coop_fusion as coop
import multiplayer_fusion as multi
import battle_mode_policy as mode
import guest_killfeed as feed
import fusion_duration as timer
import extra_reload_forms as forms
from test_fusion_partner_lifecycle import machine as _native_machine


def native_machine(*args, **kwargs):
    c = _native_machine(*args, **kwargs)
    if support.ADAPTER == 'bt4':
        # BT4 extends native BEGIN through its separate executable add-on.
        # Load the caller's own bytes; omitting them cannot validate that path.
        c.write(0x334C00, support.ADDON.read_bytes())
    return c

PREVIOUS=0x0714FF00
def timed_machine(side=0,slot=1):
    fix=timer
    c=native_machine(side,slot)
    for at,data in fix.program(fix.OLD,fix.feed.DRAW):c.write(at,data)
    c.write(fix.fusion.BEGIN,fix.fusion.begin_code(True));c.write(fix.fusion.COMMIT,fix.fusion.commit_code(True))
    for at,value in ((fix.CONTROL,fix.MAGIC),(fix.CONTROL+4,c.manager),(fix.CONTROL+8,6),
                     (fix.CONTROL+12,1),(fix.CONTROL+16,1200),(fix.CONTROL+28,0xFFFFFFFF),
                     (0x3337C0,1),(0x2FEB38,0x1600000),(0x1600000,3),(0x1600000+260,0x2C6070)):
        c.w(at,value)
    c.write(fix.feed.ROW,fix.feed.row_code())
    c.record=fix.RECORDS+side*fix.STRIDE
    for i,model in enumerate(c.models):c.w(model+20,0x1500000+i*64)
    return c

def prepare(c,source=2,partner=4):
    c.source=c.actors[source];c.partner=partner;c.slot=partner//2
    c.w(c.source+0x9A4+164*(source//2),3)
    if c.u(multi.CONTROL)!=multi.MAGIC:
        for actor in c.actors:c.w(actor+0x1278,1)
    for at,v in ((forms.CONTROL,1),(forms.CONTROL+4,c.manager),(forms.CONTROL+8,6),
                 (forms.requests.CONTROL,1),(forms.requests.CONTROL+4,c.manager),
                 (forms.FORM_ENABLE,1),(forms.requests.preloader.REGISTRY_GLOBAL,0x1400000),
                 (0x1400000+69128,1)):
        c.w(at,v)
    c.callbacks[forms.heap.ENTRY]=lambda q:q.r.__setitem__(2,1)
    c.callbacks[0x20E3A0]=lambda q:q.r.__setitem__(2,c.u(c.actors[partner]+0x9A4+164*(partner//2)))
    c.r[4:9]=[c.source,0,partner//2,0,0x1600000]
    c.record=timer.RECORDS+source*timer.STRIDE
    # Match the installed parity unlock hook, including the real s1 register.
    c.w(0x203830,(3<<26)|(fusion.SIDE>>2))
    c.unlocks=[]
    c.callbacks[0x12B4F0]=lambda q:(c.unlocks.append(q.r[4]),q.r.__setitem__(2,1))
    return c

def coop_machine(mask=63):
    c=native_machine(mask=mask)
    for p,b in ((coop.GATE,coop.gate()),(coop.ELIGIBILITY,coop.eligibility()),
                (coop.BEGIN,coop.begin()),(coop.TICK,coop.tick(PREVIOUS)),
                (coop.COMMIT,coop.commit()),(coop.CONTACT,coop.contact()),(feed.ROW,feed.row_code())):c.write(p,b)
    c.callbacks[PREVIOUS]=lambda q:None
    values=(mode.MAGIC,c.manager,6,mode.COOP,2,mask,0xFFFFFFFF,0xFFFFFFFF,0,0,0,0xFFFFFFFF,
            0xFFFFFFFF,0xFFFFFFFF,0,0,0)
    c.write(mode.CONTROL,struct.pack('<'+'I'*len(values),*values))
    c.battle=0x1802000;c.w(0x2FEB38,c.battle);c.w(c.battle,3);c.w(c.battle+260,0x2C6070)
    c.w(0x3337C0,1)
    for actor in c.actors:
        for off in (2380,2388,2392,2396,2400):c.w(actor+off,-1)
    return c

def coop_request(c,player=0,chord=0x86):
    c.r[4:9]=[c.actors[player*2],0,1,0,0x1600000]
    c.w(coop.RECORDS+player*coop.RECORD_STRIDE+328,chord)
    c.run(coop.BEGIN)

def confirm(c,player,chord=0x86):
    c.w(coop.RECORDS+player*coop.RECORD_STRIDE+328,chord);c.run(coop.TICK)

f=multi

def multi_machine(side=0,slot=1,subjects=(0,1,2,3)):
    c=native_machine(side,slot)
    for p,b in f.program(f.pads.FRAME,f.pads.PAD):c.write(p,b)
    c.write(f.fusion.SYNC,f.fusion.sync_code(quad_support=True))
    c.write(f.feed.ROW,f.feed.row_code())
    c.write(f.CONTROL,struct.pack('<5I',f.MAGIC,c.manager,6,0,0))
    c.write(f.pads.CONTROL,struct.pack('<4I',f.pads.MAGIC,c.manager,6,1))
    c.write(f.seats.CONTROL+f.seats.F['owned'],struct.pack('<4I',*(subjects+(0xFFFFFFFF,)*(4-len(subjects)))))
    c.battle=0x1802000;c.w(0x2FEB38,c.battle);c.w(c.battle,3);c.w(c.battle+260,0x2C6070)
    c.w(0x3337C0,1)
    for i,actor in enumerate(c.actors):
        c.w(actor+0x1278,int(i not in subjects))
        for off in (2380,2388,2392,2396,2400):c.w(actor+off,-1)
    c.callbacks[f.pads.FRAME]=lambda q:None
    c.callbacks[f.pads.PAD]=lambda q:q.r.__setitem__(2,0x123400)
    c.subjects=subjects
    return c

def pad(seat):return f.pads.RECORDS+seat*f.pads.RECORD_STRIDE if seat<2 else f.pads.PADS+(seat-2)*f.pads.RECORD_STRIDE

def run(c,at):c.r[31]=0xFEED0000;c.run(at)

def request(c,seat,variant=0):
    c.r[4:9]=[c.actors[c.subjects[seat]],variant,1,0,0x1600000]
    c.w(pad(seat)+328,0x84);run(c,f.BEGIN)

def accept(c,seat):c.w(pad(seat)+328,4);run(c,f.TICK)

def commit(c):c.w(c.source+2376,241);c.r[4]=c.source;run(c,f.COMMIT)
