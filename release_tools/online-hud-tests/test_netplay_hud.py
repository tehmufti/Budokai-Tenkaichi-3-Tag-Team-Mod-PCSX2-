import support
"""Execute the client-only HUD programs without client-specific game updates."""
import struct
import unittest

import netplay_hud as h
import netplay_view as v
import netplay_core as n
import fresh_team_combat as core
import fresh_team_camera as camera
import hud_subject as native
import display_settings as display
import viewport_hud as hud
import lockoff_target as off
from native_map import GP
from test_netplay_view import Cpu, image, put
from guest_soak import STACK


def machine(slot=0):
    ram=image(slot=slot)
    put(ram,core.MODE,1,6,0x1800000,6)
    put(ram,GP-22364,0x1800000);put(ram,0x1800000,2)
    put(ram,camera.SUCCESSOR_CONTROL+8,0,1)
    put(ram,n.SEAT_CONTROL+n.SF['magic'],n.SEAT_MAGIC)
    put(ram,n.SEAT_CONTROL+n.SF['enable'],1)
    put(ram,n.SEAT_CONTROL+n.SF['seats'],0,1,2,3,4,5)
    put(ram,v.CAM_LOGIC,0x3C)
    for i in range(6):
        ptr=0x1900000+i*0x2000
        put(ram,core.POINTERS+4*i,ptr);put(ram,ptr,i)
        put(ram,core.TABLE+4*i,i^1)
    put(ram,h.CONTROL,h.MAGIC,off.HUD_POLICIES['single_enemy'])
    put(ram,display.CONTROL+display.FIELDS['hud'],1)
    for addr,data in ((h.SUBJECT,h.subject_code()),(h.FILTER,h.filter_code()),
                      (h.DRAW,h.draw_code()),(h.RENDER,h.render_code())):
        ram[addr:addr+len(data)]=data
    c=Cpu(ram,(0x100000,0x2C0000));c.stub_sentinel=True
    c.panels=[];c.scissors=[]
    c.callbacks[hud.PANEL]=lambda m:c.panels.append(tuple(m.r[4:9]))
    c.callbacks[hud.SCISSOR]=lambda m:c.scissors.append(tuple(m.r[4:8]))
    return c


class OnlineHudTests(unittest.TestCase):
    def test_each_client_draws_its_own_actor_and_actual_target(self):
        for slot in range(6):
            with self.subTest(slot=slot):
                c=machine(slot);before=bytes(c.buffer)
                c.call(h.DRAW)
                self.assertEqual([r[0] for r in c.panels],[slot,slot^1])
                self.assertEqual(c.panels[0][1:],(4,5,216,0))
                self.assertEqual(c.panels[1][1:],(292,5,216,1))
                # Only the temporary stack frame may change; all battle and RNG state is identical.
                self.assertEqual(c.buffer[:0x100000],before[:0x100000])
                self.assertEqual(c.buffer[0x100000:STACK-0x1000],before[0x100000:STACK-0x1000])
                self.assertEqual(c.buffer[STACK:0x2000000],before[STACK:0x2000000])
                self.assertEqual(c.buffer[native.CONTROL:native.CONTROL+64],before[native.CONTROL:native.CONTROL+64])

    def test_changed_target_and_permuted_extra_seat(self):
        c=machine(4);put(c.buffer,n.SEAT_CONTROL+n.SF['seats']+16,2)
        put(c.buffer,core.TABLE+8,5);c.call(h.DRAW)
        self.assertEqual([r[0] for r in c.panels],[2,5])

    def test_dead_leader_and_spectator_follow_camera_successor(self):
        for slot,watch,expected in ((0,0xFFFFFFFF,4),(1,0xFFFFFFFF,5),(n.NO_SLOT,1,5),(4,0,4)):
            c=machine(slot);put(c.buffer,v.CONTROL+v.F['watch'],watch)
            put(c.buffer,camera.SUCCESSOR_CONTROL+8,4,5);c.call(h.SUBJECT)
            self.assertEqual(c.r[2],expected)

    def test_no_custom_panels_during_intro_results_or_disabled_hud(self):
        for addr,value in ((0x187A420,2),(0x333700,1),(v.CONTROL+v.F['views'],0),
                           (n.CONTROL+n.F['state'],n.ARMED),(display.CONTROL+display.FIELDS['hud'],0)):
            c=machine(3);put(c.buffer,addr,value);c.call(h.DRAW)
            self.assertEqual(c.panels,[],hex(addr))

    def test_targetless_never_draws_self_or_invalid_target(self):
        for target in (2,0xFFFFFFFF,9):
            c=machine(2);put(c.buffer,core.TABLE+8,target);c.call(h.DRAW)
            self.assertEqual([r[0] for r in c.panels],[2])

    def test_lockoff_visibility_policy_is_lent_and_restored(self):
        c=machine(4);put(c.buffer,off.CONTROL,off.MAGIC);put(c.buffer,off.CONTROL+off.HUD_POLICY,2)
        queried=[]
        def hide(m):
            queried.append((m.r[4],m.u(off.CONTROL+off.HUD_POLICY)));m.r[2]=1
        c.callbacks[off.HIDE_HUD]=hide;c.call(h.DRAW)
        self.assertEqual(queried,[(4,0)])
        self.assertEqual(c.u(off.CONTROL+off.HUD_POLICY),2)
        self.assertEqual([r[0] for r in c.panels],[4])

    def test_only_status_roots_hidden_clash_prompts_remain(self):
        for active in (0,1):
            for node in (0x1500010,0x1500020,0x1500030):
                c=machine();put(c.buffer,native.CONTROL+native.FIELDS['active'],active)
                put(c.buffer,GP-22324,0x1500000);put(c.buffer,0x1500000,0x1500010,0,0x1500020)
                forwarded=[];c.callbacks[display.HUD_DRAW_FILTER]=lambda m:forwarded.append(m.r[4])
                c.call(h.FILTER,a0=node)
                self.assertEqual(forwarded,[] if active and node!=0x1500030 else [node])

    def test_render_wrapper_preserves_native_return_and_registers(self):
        c=machine(3)
        c.callbacks[native.RENDER_WRAP]=lambda m:(m.r.__setitem__(2,71),m.r.__setitem__(3,92))
        saved={r:100+r for r in range(16,24)}
        c.call(h.RENDER,registers=saved)
        self.assertEqual(c.r[2:4],[71,92])
        self.assertTrue(all(c.r[r]==value for r,value in saved.items()))

    def test_real_art_uses_local_health_ki_and_stocks(self):
        from prototype import ROOT
        if not (ROOT/'runtime128/sstates/SLUS-21678 (428113C2).215.p2s').is_file() or not (ROOT/'analysis/SLUS_216.78').is_file():
            self.skipTest('Private native HUD capture and executable are unavailable')
        from test_viewport_hud_art import machine as art_machine
        from test_viewport_hud_art import Cpu as ArtCpu
        import test_viewport_hud as fixture
        c=art_machine();slot=4
        class ArtShiftCpu(ArtCpu):
            def extra_instruction(self,ins,pc):
                if ins>>26==0 and ins&63==6:
                    self.r[(ins>>11)&31]=(self.r[(ins>>16)&31]&0xFFFFFFFF)>>(self.r[(ins>>21)&31]&31)
                    return
                return super().extra_instruction(ins,pc)
        c.__class__=ArtShiftCpu
        c.write(v.CONTROL,v.control(1));c.write(n.CONTROL,n.control(mode=n.LOCKSTEP,delay=1))
        c.w(n.CONTROL+n.F['local_slot'],slot);c.w(n.CONTROL+n.F['state'],n.RUNNING)
        c.w(v.natives().scene+v.SCENE_SPLIT,0)
        c.w(GP+v.GP_DIRECTOR,0x1800000);c.w(0x1800000,3)
        c.w(n.SEAT_CONTROL+n.SF['magic'],n.SEAT_MAGIC);c.w(n.SEAT_CONTROL+n.SF['enable'],1)
        c.w(n.SEAT_CONTROL+n.SF['seats']+4*slot,slot);c.w(v.CAM_LOGIC,1<<slot)
        c.w(h.CONTROL,h.MAGIC);c.w(display.CONTROL+display.FIELDS['hud'],1)
        for addr,data in ((h.SUBJECT,h.subject_code()),(h.DRAW,h.draw_code())):c.write(addr,data)
        actor=fixture.feed_test.ACTORS[slot]
        c.w(actor+0x9E4,25000);c.w(actor+0x9E4+12,30000)
        c.w(actor+0x9E4+20,350000);c.w(core.TABLE+4*slot,3)
        c.r[31]=0xFEED0000;c.run(h.DRAW)
        own=[s for s in c.sprites if s[3]<s[5]]
        self.assertEqual(sum(s[1]==8 and s[3:7]==(0,16,16,32) for s in own),2)
        hp=[s for s in own if s[1]==8 and s[3:5]==(0,0)]
        self.assertEqual((hp[-1][2],hp[-1][5]),(1,80))
        self.assertEqual(sum(s[1:4]==(8,1,16) for s in own),2)
        self.assertTrue(any(s[11] for s in own))


if __name__=='__main__':unittest.main()
