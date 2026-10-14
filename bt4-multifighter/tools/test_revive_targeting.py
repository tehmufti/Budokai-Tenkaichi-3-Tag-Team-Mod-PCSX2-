"""Run the normal targeting/picker instructions with retained downed teammates."""
import struct
import unittest
import revive_targeting as rt
try:
    import teammate_revive as revive
except FileNotFoundError:
    raise unittest.SkipTest('Revival instruction tests need local disc-derived native headers')
import tournament_ringout as tournament
import fresh_team_ai as ai
import fresh_team_combat as core
import lockon_select as select
import lockoff_target as off
import test_revive_target_fixture as target
from native_map import A


def machine(count=6,humans=(0,),mode='teams',selector=True):
    c=target.make(count=count,humans=humans,mode=mode,order='selection_order',stick=0,install=selector)
    c.write(revive.GATE,revive.gate());c.write(revive.ACTOR,revive.actor())
    c.write(revive.CONTROL,struct.pack('<4I',revive.MAGIC,target.MANAGER,count,revive.policy.MODES[mode]))
    c.write(revive.part.CONTROL,struct.pack('<3I',5,target.MANAGER,count))
    for i in range(count):
        c.w(revive.ROWS+i*revive.STRIDE,target.ACTORS[i])
        c.w(target.ACTORS[i]+0x998,1);c.w(target.MODELS[i]+16,i)
    c.write(rt.ELIGIBLE,rt.eligible_code());c.write(rt.CONTROL,struct.pack('<4I',rt.MAGIC,rt.VERSION,target.MANAGER,count))
    return c


def down(c,i):
    c.w(target.ACTORS[i]+0x9E4,0);c.w(target.ACTORS[i]+0x948,216)


def eligible(c,viewer,body):
    c.r[4:6]=[viewer,body];c.r[29]=0x1FFFF00;c.r[31]=0xFEED0000;c.run(rt.ELIGIBLE)
    return c.r[2]


class RevivalTargetTests(unittest.TestCase):
    def test_only_human_living_viewer_and_downed_revivable_team_member(self):
        c=machine();down(c,2);down(c,3)
        self.assertEqual(eligible(c,0,2),1)
        for viewer,body in ((0,0),(0,3),(0,4),(4,2),(2,0),(0,99)):
            self.assertEqual(eligible(c,viewer,body),0,(viewer,body))
        c.w(target.ACTORS[2]+0x9E8,0);self.assertEqual(eligible(c,0,2),0)
        c.w(target.ACTORS[2]+0x9E8,1000);c.w(target.ACTORS[2]+0x994,5)
        self.assertEqual(eligible(c,0,2),0)

    def test_no_feature_when_revival_missing_ffa_or_other_capture(self):
        for field,value in ((revive.CONTROL,0),(rt.CONTROL+8,target.MANAGER+4),
                            (revive.CONTROL+12,revive.policy.FFA)):
            c=machine();down(c,2);c.w(field,value);self.assertEqual(eligible(c,0,2),0)
        c=machine(mode='ffa');down(c,2);self.assertEqual(eligible(c,0,2),0)

    def test_hidden_consumed_absent_replaced_and_not_retained_bodies_are_excluded(self):
        for address,value in ((revive.part.CONTROL+12,0b111011),(revive.part.CONTROL+16,4),
                              (target.MODELS[2]+4,0),(target.ACTORS[2]+0x948,215),
                              (revive.ROWS+2*revive.STRIDE,target.ACTORS[4])):
            c=machine();down(c,2);c.w(address,value);self.assertEqual(eligible(c,0,2),0)

    def test_tournament_elimination_uses_real_revive_wrapper(self):
        c=machine();down(c,2)
        c.write(tournament.GATE,tournament.gate());c.write(tournament.REVIVE,tournament.revive())
        c.write(tournament.REVIVE_NATIVE,core.rebound(revive.actor,ACTOR=tournament.REVIVE_NATIVE)())
        c.write(revive.ACTOR,tournament.JUMP(tournament.REVIVE))
        c.write(tournament.CONTROL,struct.pack('<6I',tournament.MAGIC,tournament.VERSION,target.MANAGER,6,1,4))
        self.assertEqual(eligible(c,0,2),0)
        c.w(tournament.CONTROL+tournament.F['eliminated'],0)
        self.assertEqual(eligible(c,0,2),1)

    def test_normal_cycle_includes_body_without_replacing_enemies_all_sizes(self):
        for count in revive.policy.ACTOR_COUNTS:
            c=machine(count=count);down(c,2)
            seen={target.tap(c) for _ in range(count)}
            self.assertEqual(seen,{2,*range(1,count,2)})
        c=machine(selector=False);down(c,2)
        self.assertIn(2,{target.tap(c) for _ in range(6)})

    def test_lockoff_and_centre_reacquisition_can_pick_the_body(self):
        c=machine();down(c,2);target.place(c,2,(256,224,0))
        target.press(c,2,15);target.press(c,0)
        self.assertEqual(c.u(off.ROWS+off.OFF),1)
        target.tap(c)
        self.assertEqual(target.target(c),2);self.assertEqual(c.u(off.ROWS+off.OFF),0)

    def test_ko_auto_retarget_does_not_discard_selected_body_and_revival_removes_it(self):
        c=machine();down(c,2);c.w(core.TABLE,2)
        for _ in range(8):target.frame(c)
        self.assertEqual(target.target(c),2)
        self.assertEqual(c.u(select.ROWS+select.DEADN),0)
        c.w(target.ACTORS[2]+0x9E4,1000);c.w(target.ACTORS[2]+0x948,11)
        self.assertEqual(eligible(c,0,2),0)

    def test_all_player_seats_can_target_their_own_fallen_team(self):
        c=machine(humans=(0,1,2,3));down(c,4);down(c,5)
        for viewer in range(4):
            self.assertEqual(eligible(c,viewer,4+(viewer&1)),1)
            self.assertEqual(eligible(c,viewer,5-(viewer&1)),0)

    def test_marker_uses_the_same_downed_target(self):
        c=machine();down(c,2);c.w(core.TABLE,2)
        c.r[4]=0;c.r[31]=0xFEED0000;c.run(select.MARKER)
        self.assertTrue(c.packets)

    def test_resolver_and_survivor_picker_keep_body_only_for_living_human(self):
        c=machine();down(c,2);c.w(core.TABLE,2);c.write(core.RESOLVER,core.resolver_code())
        c.r[4]=target.ACTORS[0];c.r[31]=0xFEED0000;c.run(core.RESOLVER)
        self.assertEqual((c.r[2],c.r[3]),(target.ACTORS[2],2))
        picker=next(row for row in ai.program(6)['segments'] if row['address']==ai.PICKER)
        c.write(ai.PICKER,bytes.fromhex(picker['data_hex']))
        for i in range(6):c.w(ai.DESCRIPTORS[i],target.ACTORS[i])
        c.callbacks[A(0x1DC320)]=lambda m:m.r.__setitem__(2,int(m.u(m.r[4]+0x9E4)==0))
        c.r[31]=0xFEED0000;c.run(ai.PICKER)
        self.assertEqual(target.target(c),2)
        c.w(target.ACTORS[0]+0x1278,1);c.r[31]=0xFEED0000;c.run(ai.PICKER)
        self.assertIn(target.target(c),(1,3,5))

    def test_build_is_guarded_idempotent_and_ignores_disabled_revival(self):
        ram=bytearray(0x8000000)
        put=lambda p,*v:struct.pack_into('<'+'I'*len(v),ram,p,*v)
        self.assertFalse(rt.build_memory(ram)['blocks'])
        put(core.ACTORS,target.MANAGER);put(core.MODE,1,6,target.MANAGER,6)
        put(revive.CONTROL,revive.MAGIC,target.MANAGER,6,0)
        plan=rt.build_memory(ram)
        for row in plan['blocks']:
            p=row['address'];data=bytes.fromhex(row['data_hex'])
            self.assertEqual(ram[p:p+len(data)],bytes.fromhex(row['expected_hex']));ram[p:p+len(data)]=data
        self.assertFalse(rt.build_memory(ram)['blocks'])
        ram[rt.ELIGIBLE]^=1
        with self.assertRaisesRegex(ValueError,'changed'):rt.build_memory(ram)


if __name__=='__main__':unittest.main()
