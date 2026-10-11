"""Actual native rush resource overlay, retargeting and contact boundaries."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import unittest
import struct
import tag_team_rush as tag
import tag_rush_approach as rush
import tag_rush_launch as launch
import tag_rush_camera as camera
from test_tag_rush_approach import machine,begin,native_dash,hit
from test_tag_rush_camera import run,AUTHORED


class LaunchTests(unittest.TestCase):
    def test_reviewed_resource_guards_reject_before_outgoing_action_cleanup(self):
        for bad in ('missing','magic','count','frames','pointer','size','scratch','native','secondary'):
            c=machine();table=c.u(tag.CONTROL+launch.TABLE_OFFSET)
            if bad=='missing':c.w(tag.CONTROL+launch.TABLE_OFFSET,0)
            elif bad=='magic':c.w(table,0)
            elif bad=='count':c.w(table+8,4)
            elif bad=='frames':c.w(table+20,14)
            elif bad=='pointer':c.w(table+16,0x100)
            elif bad=='size':c.w(c.u(table+16),0x10000)
            elif bad=='scratch':c.w(c.models[0]+5728,0x7FFFFF0)
            elif bad=='native':c.w(c.u(table+12),0)
            else:c.w(c.u(table+12)+24,5)
            actors=[c.read(p,0x1600) for p in c.actors]
            self.assertEqual(begin(c),0,bad)
            self.assertEqual([c.read(p,0x1600) for p in c.actors],actors,bad)
            self.assertEqual(c.idle_starts,[])

    def test_overlay_uses_private_parameters_and_all_native_clips_then_restores(self):
        c=machine();models=[c.read(m,0x1700)for m in c.models]
        original_params=c.u(c.models[0]+2348);original_cam=c.u(c.models[0]+2360)
        oldclips=[c.u(c.models[0]+192+4*i)for i in launch.ANIMATIONS]
        self.assertEqual(begin(c),1)
        self.assertEqual(c.u(c.models[0]+2348),launch.PARAMS)
        self.assertEqual(c.u(c.models[0]+2360),launch.CAMERA)
        self.assertEqual([c.u(launch.PARAMS+i)for i in (396,408,420)],[0]*3)
        self.assertEqual([c.read(m,0x1700)for m in c.models[1:]],models[1:])
        for off in (12,16,192,2344):self.assertEqual(c.u(c.models[0]+off),struct.unpack_from('<I',models[0],off)[0])
        c.r[4]=1;run(c,rush.CANCEL)
        self.assertEqual(c.u(c.models[0]+2348),original_params);self.assertEqual(c.u(c.models[0]+2360),original_cam)
        self.assertEqual([c.u(c.models[0]+192+4*i)for i in launch.ANIMATIONS],oldclips)
        self.assertEqual(c.u(c.actors[0]+2388),0xFFFFFFFF)

    def test_zero_native_retarget_marker_is_owned_then_restored_before_idle(self):
        for original in (0,1,7):
            c=machine();marker=c.u(c.models[0]+5728)+98344;c.w(marker,original)
            self.assertEqual(begin(c),1);self.assertEqual(c.u(marker),1)
            cleanup=c.callbacks[rush.A(0x1E23D0)]
            def native_cleanup(m):
                self.assertEqual(m.u(marker),original);cleanup(m)
            c.callbacks[rush.A(0x1E23D0)]=native_cleanup
            c.r[4]=1;run(c,rush.CANCEL);self.assertEqual(c.u(marker),original)

    def test_restore_does_not_clobber_intervening_resource_replacement(self):
        c=machine();begin(c);c.w(c.models[0]+2348,0x3D00000)
        c.w(c.models[0]+2360,0x3E00000);c.w(c.models[0]+192+329*4,0x3F00000)
        c.r[4]=1;run(c,rush.CANCEL)
        self.assertEqual(c.u(c.models[0]+2348),0x3D00000)
        self.assertEqual(c.u(c.models[0]+2360),0x3E00000)
        self.assertEqual(c.u(c.models[0]+192+329*4),0x3F00000)

    def test_retarget_overrides_only_owned_native_clip_at_exact_callsite(self):
        for index in (329,330,331,332,335,352,353,354,355,356,363,11):
            c=machine();begin(c);c.r[20]=index;c.r[4:9]=[0x3300000,c.models[0],c.models[0],0,1]
            run(c,launch.RETARGET)
            expected=0x6D26000 if index in launch.ANIMATIONS else c.models[0]
            self.assertEqual(c.retargets[-1][2],expected,index)
            self.assertEqual(c.retargets[-1][4],0 if index in launch.ANIMATIONS else 1,index)
        c=machine();begin(c);c.r[20]=329;c.r[4:9]=[0x3300000,c.models[2],c.models[2],0,1]
        run(c,launch.RETARGET);self.assertEqual(c.retargets[-1][2],c.models[2])

    def test_unrelated_native_contacts_preserve_existing_hook_chain(self):
        c=machine();begin(c);native_dash(c)
        c.r[4:8]=[c.actors[2],c.actors[1],4,7];run(c,launch.CONTACT)
        self.assertEqual(c.native_contacts,[(c.actors[2],c.actors[1],4,7)])
        c.callbacks[launch.contact.PROTECTED]=lambda m:m.r.__setitem__(2,1)
        hit(c);self.assertEqual(c.u(rush.STATE+rush.S['contact']),0)

    def test_approach_camera_is_actual_native_camera_not_private_recreation(self):
        c=machine();begin(c);c.write(camera.QUERY,camera.query_code())
        for shared in (0,1):
            c.w(tag.CONTROL+tag.C['shared'],shared)
            for index in range(4):
                c.r[4]=index;run(c,camera.QUERY)
                self.assertEqual(c.r[2],AUTHORED if shared or index in (0,1,2) else 0)
        c.w(AUTHORED+768,c.models[3]);c.r[4]=0;run(c,camera.QUERY);self.assertEqual(c.r[2],0)

    def test_native_old_action_charge_cannot_replace_initial_tag_queue(self):
        c=machine();begin(c)
        def selector(m):
            m.w(m.r[4]+2380,55);m.w(m.r[4]+2388,55);m.w(m.r[4]+2392,-1);m.r[2]=41
        c.callbacks[rush.A(0x1E12D0)]=selector
        c.r[4]=c.actors[0];run(c,launch.COMMIT)
        self.assertEqual(c.u(c.actors[0]+2380),261)
        self.assertEqual([c.u(c.actors[0]+i)for i in (2388,2392,2396,2400)],[261,285,0xFFFFFFFF,0xFFFFFFFF])
        self.assertEqual(c.r[2],41);self.assertEqual(c.u(launch.STATE+launch.P['dispatch']),0)
        # The receipt is consumed: later native reactions must never be forced
        # back into a fresh ultimate. Other actors always keep native routing.
        c.r[4]=c.actors[0];run(c,launch.COMMIT);self.assertEqual(c.u(c.actors[0]+2380),55)
        c.w(launch.STATE+launch.P['dispatch'],1);c.r[4]=c.actors[2];run(c,launch.COMMIT)
        self.assertEqual(c.u(c.actors[2]+2380),55);self.assertEqual(c.u(launch.STATE+launch.P['dispatch']),1)

    def test_original_dispatch_and_animation_retarget_sites_match_native_executable(self):
        for action in (283,284,285,286,287,288):
            self.assertEqual(struct.unpack('<I',launch.NATIVE(rush.A(0x2C4980)+4*action,4))[0],rush.A(0x1F8C00))
        self.assertEqual(launch.NATIVE(launch.RETARGET_HOOK,4),launch.RETARGET_NATIVE)
        self.assertEqual(launch.NATIVE(launch.COMMIT_HOOK,4),launch.COMMIT_NATIVE)


if __name__=='__main__':unittest.main()
