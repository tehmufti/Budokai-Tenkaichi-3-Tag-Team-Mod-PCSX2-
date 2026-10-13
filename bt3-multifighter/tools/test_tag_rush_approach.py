"""Guest ownership around the real native rush dispatcher; no fake motion loop."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import struct
import unittest
import tag_rush_approach as rush
import tag_rush_launch as launch
import tag_rush_camera as camera
import tag_team_rush as tag
import tag_rush_safety as safety
import cinematic_contact_guard as contact
from test_tag_rush_scene import fixture
from test_tag_rush_camera import run, AUTHORED


def machine():
    c=fixture();c.connections=[];c.native_contacts=[];c.retargets=[]
    c.write(tag.ELIGIBLE,tag.eligible_code());c.write(safety.PREFLIGHT,safety.preflight_code())
    c.write(tag.VICTIM_ELIGIBLE,tag.eligible_code(tag.VICTIM_ELIGIBLE,victim=True))
    c.write(safety.VICTIM_PREFLIGHT,safety.preflight_code(safety.VICTIM_PREFLIGHT,victim=True))
    del c.callbacks[safety.PREFLIGHT]
    c.callbacks.pop(safety.VICTIM_PREFLIGHT,None)
    for index,(actor,model) in enumerate(zip(c.actors,c.models)):
        c.w(actor+0x998,1);c.w(actor+2376,11)
        c.w(tag.core.TABLE+index*4,1 if index%2==0 else 0)
        c.w(model+2360,0x3B00000+index*0x1000)
        for animation in launch.ANIMATIONS:c.w(model+192+animation*4,0x3C00000+index*0x10000+animation*4)
    c.w(tag.participation.CONTROL+12,15);c.w(tag.participation.CONTROL+16,0)
    c.w(tag.core.MODE+4,4);c.w(tag.core.MODE+12,4);c.w(rush.A(0x3337C0),1)
    def setpos(i,x,y,z):
        b=struct.pack('<4f',x,y,z,1);c.write(c.models[i]+2384,b);c.write(c.actors[i]+16,b)
    c.setpos=setpos;c.pos=lambda i:struct.unpack('<3f',c.read(c.models[i]+2384,12))
    c.setpos(0,-350,-10,0);c.setpos(2,-350,-10,100);c.setpos(1,150,-10,0)
    table,native=0x6D30000,0x6D30100;c.w(tag.CONTROL+launch.TABLE_OFFSET,table)
    c.write(table,struct.pack('<4I',launch.MAGIC,0x6D26000,5,native))
    for i,frames in enumerate(launch.FRAMES):
        ptr=0x6D31000+i*0x100;c.write(ptr,struct.pack('<2I',512,0))
        c.write(table+16+8*i,struct.pack('<2I',ptr,frames))
    c.write(native,struct.pack('<8I',launch.NATIVE_MAGIC,native+64,640,native+704,384,native+32,6,0))
    for i in range(6):
        ptr=0x6D32000+i*0x100;c.write(ptr,struct.pack('<2I',512,0));c.w(native+32+4*i,ptr)
    for off in (396,408,420):c.w(native+64+off,100000)
    def queue(m):
        for i in range(m.r[5],4):m.w(m.r[4]+2388+4*i,m.r[6] if i==m.r[5] else -1)
    c.callbacks[rush.A(0x1E02A8)]=queue
    c.callbacks[rush.A(0x1E0310)]=lambda m:[m.w(m.r[4]+2388+4*i,-1) for i in range(4)]
    original=c.callbacks[rush.A(0x1E23D0)]
    def dispatch(m):
        actor=m.r[4];pending=m.u(actor+2380);original(m)
        if pending!=0xFFFFFFFF:
            for i in range(3):m.w(actor+2388+4*i,m.u(actor+2392+4*i))
            m.w(actor+2400,-1)
        action=m.u(actor+2376)
        if action in (261,285):m.w(actor+2420,363 if action==261 else 329)
    c.callbacks[rush.A(0x1E23D0)]=dispatch
    c.callbacks[contact.PROTECTED]=lambda m:m.r.__setitem__(2,0)
    c.callbacks[launch.CONTACT_OLD]=lambda m:(m.native_contacts.append(tuple(m.r[4:8])),m.r.__setitem__(2,1))
    c.callbacks[rush.A(0x24BBE8)]=lambda m:(m.retargets.append(tuple(m.r[4:9])),m.r.__setitem__(2,19))
    def start(m):m.connections.append(tuple(m.r[4:7]));m.w(tag.CONTROL+tag.C['active'],1);m.r[2]=1
    c.callbacks[tag.START]=start
    c.w(AUTHORED+768,c.models[0])
    return c


def begin(c):
    c.r[4:7]=[0,2,1];run(c,rush.BEGIN);return c.r[2]


def native_dash(c):
    c.w(c.actors[0]+2376,285);c.w(c.actors[0]+2420,332);c.w(c.actors[0]+2388,-1)


def hit(c,index=1):
    c.r[4:8]=[c.actors[0],c.actors[index],4,0];run(c,launch.CONTACT)


def native_dash_effects(c):
    """Run actual native stop routines against separate per-model FX rows."""
    for address,size in ((0x165368,0x58),(0x165418,0xC0),(0x2ECC30,32),
                         (0x1714A0,0xD0),(0x2500E8,0x220)):
        c.write(rush.A(address),launch.NATIVE(rush.A(address),size))
    aura,trail=0x3D00000,0x3D01000
    c.w(c.r[28]-22640,aura);c.w(aura+1168,aura+0x500)
    c.w(c.r[28]-22584,trail);c.w(trail+1776,trail+0x800)
    rows=[]
    for index,model in enumerate(c.models):
        node=0x3D02000+index*0x1000;body=node+0x100
        trailnode=node+0x800;trailbody=trailnode+0x100
        c.w(aura+0x500+4*index,node);c.w(node+56,body)
        c.w(body,0x21);c.w(body+40,2);c.w(body+44,7)
        c.w(trail+0x800+4*index,trailnode);c.w(trailnode+56,trailbody);c.w(trailbody,1)
        # Native color flag2 is a separate normal powered-up aura; only bit6
        # belongs to the dash. Its effective render bit must fall back to2.
        c.w(model+2868,0x44);c.w(model+2624,0x10400016)
        rows.append((body,trailbody))
    return rows


class ApproachTests(unittest.TestCase):
    def test_real_launch_admission_accepts_airborne_victim_but_waits_for_smash_recovery(self):
        for action in (213,214,223):
            c=machine();c.w(c.actors[1]+2376,action);c.w(c.actors[0]+2376,71)
            self.assertEqual(begin(c),0);self.assertEqual(c.u(tag.METERS),750)
            c.w(c.actors[0]+2376,11);self.assertEqual(begin(c),1)
            self.assertEqual(c.u(c.actors[1]+2376),action)
            self.assertEqual(c.u(c.actors[2]+2376),11)
            native_dash(c);hit(c);run(c,rush.TICK)
            self.assertEqual(c.connections,[(0,2,1)])
            self.assertEqual([c.u(tag.METERS+i*tag.METER_STRIDE)for i in range(4)],[0,750,0,750])

    def test_attempt_spends_only_initiator_and_contact_spends_partner(self):
        for keep in (False,True):
            for index in range(4):
                with self.subTest(keep=keep,index=index):
                    c=machine();c.w(tag.CONTROL+tag.C['keep_meter_on_miss'],int(keep))
                    victim=1 if index%2==0 else 0
                    c.r[4:7]=[index,index^2,victim];run(c,rush.BEGIN);self.assertEqual(c.r[2],1)
                    expected=[750]*4
                    if not keep:expected[index]=0
                    self.assertEqual([c.u(tag.METERS+i*tag.METER_STRIDE)for i in range(4)],expected)
                    c.w(c.actors[index]+2376,285);c.w(c.actors[index]+2420,332)
                    c.r[4:8]=[c.actors[index],c.actors[victim],4,0];run(c,launch.CONTACT)
                    run(c,rush.TICK)
                    self.assertEqual(c.connections,[(index,index^2,victim)])
                    landed=[0 if i%2==index%2 else 750 for i in range(4)]
                    self.assertEqual([c.u(tag.METERS+i*tag.METER_STRIDE)for i in range(4)],landed)
                    # A later cleanup cannot repay either confirmed cost.
                    c.r[4]=1;run(c,rush.CANCEL)
                    self.assertEqual([c.u(tag.METERS+i*tag.METER_STRIDE)for i in range(4)],landed)

    def test_miss_or_refused_cinematic_never_spends_partner_meter(self):
        for keep in (False,True):
            for reason in ('timeout','wrong_target','native_miss','damage','preflight'):
                with self.subTest(keep=keep,reason=reason):
                    c=machine();c.w(tag.CONTROL+tag.C['keep_meter_on_miss'],int(keep))
                    self.assertEqual(begin(c),1);native_dash(c)
                    if reason=='timeout':c.w(rush.STATE+rush.S['ticks'],rush.TIMEOUT)
                    elif reason=='wrong_target':hit(c,3)
                    elif reason=='native_miss':c.w(c.actors[0]+2376,11)
                    elif reason=='damage':c.w(c.actors[0]+0x9E4,29999)
                    else:
                        hit(c);c.callbacks[tag.START]=lambda m:m.r.__setitem__(2,0)
                    run(c,rush.TICK)
                    self.assertFalse(c.connections);self.assertFalse(c.damage)
                    self.assertEqual([c.u(tag.METERS+i*tag.METER_STRIDE)for i in range(4)],
                                     [750 if keep else 0,750,750,750])
                    self.assertEqual(c.u(tag.CONTROL+tag.C['approaching']),0)

    def test_cancel_never_refunds_to_dead_consumed_or_replaced_actor_slots(self):
        for keep in (False,True):
            for cause in ('dead','consumed','new_model','new_actor','new_manager'):
                with self.subTest(keep=keep,cause=cause):
                    c=machine();c.w(tag.CONTROL+tag.C['keep_meter_on_miss'],int(keep))
                    begin(c)
                    # Emulate another legitimate owner resetting that slot's
                    # meter. Cancellation must not invent a later refund.
                    c.w(tag.METERS,13)
                    if cause=='dead':c.w(c.actors[0]+0x9E4,0)
                    elif cause=='consumed':c.w(tag.participation.CONTROL+16,1)
                    elif cause=='new_model':c.w(c.models[0]+12,99)
                    elif cause=='new_actor':c.w(tag.core.POINTERS,c.actors[0]+0x10000)
                    else:c.w(c.r[28]-22364,c.u(c.r[28]-22364)+0x10000)
                    c.r[4]=1;run(c,rush.CANCEL)
                    self.assertEqual([c.u(tag.METERS+i*tag.METER_STRIDE)for i in range(4)],[13,750,750,750])

    def test_begin_queues_real_ultimate_prelude_then_rush_and_leaves_other_bodies(self):
        c=machine();others=[c.read(c.actors[i],0x1600) for i in (1,2,3)]
        positions=[c.pos(i) for i in range(4)];self.assertEqual(begin(c),1)
        self.assertEqual(c.u(c.actors[0]+2376),261);self.assertEqual(c.u(c.actors[0]+2388),285)
        self.assertEqual(c.u(c.actors[0]+2420),363)
        for _ in range(12):run(c,rush.TICK)
        self.assertEqual([c.pos(i)for i in range(4)],positions)
        self.assertEqual([c.read(c.actors[i],0x1600) for i in (1,2,3)],others)
        self.assertEqual(c.connections,[]);self.assertEqual(c.damage,[])
        self.assertFalse(c.beams)

    def test_real_contact_hands_off_without_original_victim_or_duplicate_helper(self):
        c=machine();self.assertEqual(begin(c),1);native_dash(c)
        untouched=[c.read(c.actors[i],0x1600)for i in (1,2,3)]
        hit(c);self.assertEqual(c.u(rush.STATE+rush.S['contact']),1)
        self.assertEqual([c.read(c.actors[i],0x1600)for i in (1,2,3)],untouched)
        self.assertFalse(c.native_contacts);self.assertFalse(c.damage)
        run(c,rush.TICK);self.assertEqual(c.connections,[(0,2,1)])
        self.assertEqual(c.u(rush.STATE+rush.S['connected']),1)
        self.assertEqual(c.u(launch.STATE+launch.P['owned']),0)

    def test_native_dash_aura_ends_on_contact_and_owned_timeout_only(self):
        for cause in ('contact','timeout'):
            c=machine();begin(c);native_dash(c);rows=native_dash_effects(c)
            others=[(c.read(body,80),c.read(trail,80),c.read(model+2624,248))
                    for (body,trail),model in zip(rows[1:],c.models[1:])]
            if cause=='contact':hit(c)
            else:c.w(rush.STATE+rush.S['ticks'],rush.TIMEOUT)
            run(c,rush.TICK)
            body,trail=rows[0]
            self.assertEqual(c.u(body+40),1,cause)
            self.assertEqual((c.u(body),c.u(body+44)),(0x21,7),cause)
            self.assertEqual(c.u(trail),5,cause)
            self.assertEqual(c.u(c.models[0]+2868),4,cause)
            self.assertEqual(c.u(c.models[0]+2624),0x10040016,cause)
            self.assertEqual([(c.read(body,80),c.read(trail,80),c.read(model+2624,248))
                             for (body,trail),model in zip(rows[1:],c.models[1:])],others,cause)
            self.assertEqual(c.connections,[(0,2,1)] if cause=='contact' else [],cause)
            self.assertFalse(c.damage)

    def test_dash_cleanup_preserves_new_action_and_ordinary_aura(self):
        for changed in ('no_dash','params','pending','manager'):
            c=machine();begin(c);native_dash(c);rows=native_dash_effects(c)
            if changed=='no_dash':c.w(c.models[0]+2868,4)
            elif changed=='params':c.w(c.models[0]+2348,0x3E00000)
            elif changed=='pending':c.w(c.actors[0]+2380,183)
            else:c.w(c.r[28]-22364,c.u(c.r[28]-22364)+0x10000)
            before=[(c.read(body,80),c.read(trail,80),c.read(model+2624,248))
                    for (body,trail),model in zip(rows,c.models)]
            c.r[4]=1;run(c,rush.CANCEL)
            self.assertEqual([(c.read(body,80),c.read(trail,80),c.read(model+2624,248))
                              for (body,trail),model in zip(rows,c.models)],before,changed)

    def test_extra_initiator_cleans_its_own_dash_not_the_native_leader(self):
        c=machine();c.r[4:7]=[2,0,1];run(c,rush.BEGIN);self.assertEqual(c.r[2],1)
        c.w(c.actors[2]+2376,285);c.w(c.actors[2]+2420,332)
        rows=native_dash_effects(c);leader=(c.read(rows[0][0],80),c.read(rows[0][1],80))
        c.r[4:8]=[c.actors[2],c.actors[1],4,0];run(c,launch.CONTACT);run(c,rush.TICK)
        self.assertEqual(c.connections,[(2,0,1)])
        self.assertEqual(c.u(rows[2][0]+40),1);self.assertEqual(c.u(rows[2][1]),5)
        self.assertEqual(c.u(c.models[2]+2868),4)
        self.assertEqual((c.read(rows[0][0],80),c.read(rows[0][1],80)),leader)

    def test_guard_uses_native_unblockable_reaction_and_contact_is_latched(self):
        c=machine();victim=c.actors[1];c.w(victim+2376,56);c.w(victim+2420,239);c.w(victim+0x74C,0x10)
        for flag in (0x95,0x41,0xC9,0xD5,0x1C):
            flag=safety.FLAG(flag);at=victim+0x10AD+(flag>>3);c.write(at,bytes([c.read(at,1)[0]|(1<<(flag&7))]))
        self.assertEqual(begin(c),1);native_dash(c)
        self.assertEqual([c.read(launch.PARAMS+i,1)[0]for i in (323,326,329,332)],[34]*4)
        hit(c);hit(c,3);run(c,rush.TICK)
        self.assertEqual(c.connections,[(0,2,1)]);self.assertEqual(c.u(victim+0x74C),0x10)

    def test_wrong_target_and_native_miss_never_damage_or_enter_scene(self):
        for cause in ('wrong','native_done','timeout'):
            c=machine();begin(c);native_dash(c)
            if cause=='wrong':hit(c,3)
            elif cause=='native_done':c.w(c.actors[0]+2376,11)
            else:c.w(rush.STATE+rush.S['ticks'],rush.TIMEOUT)
            run(c,rush.TICK)
            self.assertEqual(c.connections,[],cause);self.assertEqual(c.damage,[],cause)
            self.assertEqual(c.u(tag.CONTROL+tag.C['approaching']),0,cause)
            self.assertEqual(c.u(rush.STATE+rush.S['misses']),1,cause)
            self.assertEqual(c.u(launch.STATE+launch.P['owned']),0,cause)

    def test_out_of_range_never_mutates_actors_and_helper_has_no_fake_distance_gate(self):
        c=machine();c.setpos(1,1001+c.pos(0)[0],-10,0)
        before=[c.read(p,0x1600)for p in c.actors]
        self.assertEqual(begin(c),0);self.assertEqual([c.read(p,0x1600)for p in c.actors],before)
        c=machine();c.setpos(2,-1800,-10,0);self.assertEqual(begin(c),1)

    def test_form_ko_giant_and_initiator_hit_abort_without_overwriting_new_form(self):
        for role,kind in ((0,'hp'),(1,'ko'),(2,'form'),(1,'giant')):
            c=machine();begin(c)
            if kind=='hp':c.w(c.actors[role]+0x9E4,29999)
            elif kind=='ko':c.w(c.actors[role]+0x9E4,0)
            elif kind=='form':c.w(c.models[role]+12,99)
            else:c.write(c.u(c.models[role]+2332)+2,b'\x04')
            run(c,rush.TICK)
            self.assertEqual(c.connections,[],kind);self.assertEqual(c.damage,[],kind)
            self.assertEqual(c.u(tag.CONTROL+tag.C['approaching']),0,kind)

    def test_healing_during_native_rush_is_allowed_but_later_damage_interrupts(self):
        for index in (0,2):
            for bank in (0,1):
                for subsequent in ('contact','damage'):
                    with self.subTest(index=index,bank=bank,subsequent=subsequent):
                        c=machine();actor=c.actors[index]
                        c.w(actor+0x994,bank);hp=actor+0x9E4+164*bank;c.w(hp,29750)
                        c.r[4:7]=[index,index^2,1];run(c,rush.BEGIN);self.assertEqual(c.r[2],1)
                        c.w(actor+2376,285);c.w(actor+2420,332);c.w(actor+2388,-1)
                        c.w(hp,30000);run(c,rush.TICK)
                        self.assertEqual(c.u(tag.CONTROL+tag.C['approaching']),1)
                        self.assertEqual(c.u(rush.ROWS+rush.R['hp']),30000)
                        self.assertEqual(c.u(rush.STATE+rush.S['misses']),0)
                        self.assertEqual(c.u(hp),30000)
                        if subsequent=='contact':
                            c.r[4:8]=[actor,c.actors[1],4,0];run(c,launch.CONTACT)
                        else:c.w(hp,29999)
                        run(c,rush.TICK)
                        self.assertEqual(c.connections,[(index,index^2,1)] if subsequent=='contact' else [])
                        self.assertEqual(c.u(rush.STATE+rush.S['reason']),0 if subsequent=='contact' else 7)
                        self.assertFalse(c.damage)

    def test_pause_holds_watchdog_stale_manager_never_writes_captured_models(self):
        c=machine();begin(c);c.w(rush.A(0x333700),1)
        for _ in range(5):run(c,rush.TICK)
        self.assertEqual(c.u(rush.STATE+rush.S['ticks']),0)
        c.w(c.r[28]-22364,c.u(c.r[28]-22364)+0x10000)
        actors=[c.read(a,0x1600)for a in c.actors];models=[c.read(m,0x1700)for m in c.models]
        run(c,rush.TICK)
        self.assertEqual([c.read(a,0x1600)for a in c.actors],actors)
        self.assertEqual([c.read(m,0x1700)for m in c.models],models)
        self.assertEqual(c.u(tag.CONTROL+tag.C['approaching']),0)

    def test_approach_does_not_install_synthetic_actor_hold(self):
        from prototype import Assembler
        a=Assembler(0x6D85000);rush.emit_hold(a,4,'yes','no')
        a.label('yes');a.li(2,1);a.jr();a.label('no');a.move(2,0);a.jr()
        c=machine();begin(c);c.write(a.base if hasattr(a,'base') else 0x6D85000,a.finish())
        for actor in c.actors:
            c.r[4]=actor;run(c,0x6D85000);self.assertEqual(c.r[2],0)


if __name__=='__main__':unittest.main()
