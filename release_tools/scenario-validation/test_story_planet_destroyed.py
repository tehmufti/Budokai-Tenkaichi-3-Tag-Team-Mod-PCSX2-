"""Native destruction journal, emitted MIPS conditions and offline authoring."""
import copy
import importlib.util
import os
import struct
import unittest

import story_missions as missions
import story_runtime as story
from native_map import A,elf_path
from prototype import ROOT,elf_reader
from test_story_missions import machine,tick


def document(occurrence=1):
    d=missions.default_mission()
    d['events']=[dict(id='aftermath',when=dict(type='planet_destroyed',occurrence=occurrence),
        actions=[dict(type='message',text='The planet has been destroyed')])]
    return missions.validate(d)


def destruction_machine(occurrence=1):
    c=machine(document(occurrence))
    c.write(story.DESTRUCTION,story.destruction_code())
    c.write(story.DESTRUCTION_NATIVE,elf_reader(elf_path(ROOT))[2](A(0x13F3C8),16))
    return c


def complete_destruction(c,stage=3):
    c.w(A(0x331DC8)+40,stage)
    c.r[31]=0xFEED0000;c.run(story.DESTRUCTION)


class PlanetConditionTests(unittest.TestCase):
    def test_default_occurrence_and_invalid_fields(self):
        d=document();d['events'][0]['when']=dict(type='planet_destroyed')
        self.assertEqual(missions.validate(d)['events'][0]['when'],dict(type='planet_destroyed',occurrence=1))
        for n in (0,1001,True,1.5):
            d=document();d['events'][0]['when']['occurrence']=n
            with self.assertRaisesRegex(ValueError,'occurrence'):missions.validate(d)
        d=document();d['events'][0]['when']['fighter']='hero'
        with self.assertRaisesRegex(ValueError,'unknown fields'):missions.validate(d)

    def test_nested_outcomes_and_reference_model_use_completion_count(self):
        d=document();d['win_when']=dict(type='all',conditions=[dict(type='planet_destroyed'),dict(type='time',seconds=2)])
        self.assertTrue(story.uses_destruction_trigger(missions.validate(d)))
        c=dict(type='planet_destroyed',occurrence=2)
        self.assertFalse(missions.matches(c,dict(seconds=3,fighters={},planet_destructions=1),set()))
        self.assertTrue(missions.matches(c,dict(seconds=3,fighters={},planet_destructions=2),set()))
        self.assertFalse(missions.matches(c,dict(seconds=3,fighters={}),set()))
        story.validate_compilation(missions.validate(d))

    def test_starting_on_destroyed_map_and_loading_do_not_trigger(self):
        c=destruction_machine();c.w(A(0x331DC8)+40,3);c.w(A(0x31BE74),1)
        tick(c,3);self.assertEqual(c.u(story.EVENTS),0);self.assertEqual(c.u(story.DESTRUCTION_COUNT),0)
        # Even a stale duplicate completion call cannot count the starting map.
        complete_destruction(c);tick(c);self.assertEqual(c.u(story.EVENTS),0)

    def test_complete_native_destruction_is_once_and_waits_for_transition_release(self):
        c=destruction_machine();c.w(A(0x3337B8),0x2000)
        complete_destruction(c);self.assertEqual(c.u(A(0x31BE74)),1);self.assertEqual(c.r[2],1)
        self.assertEqual(c.u(story.DESTRUCTION_COUNT),1);self.assertEqual(c.u(story.DESTRUCTION_STAGE),3)
        complete_destruction(c);self.assertEqual(c.u(story.DESTRUCTION_COUNT),1)
        tick(c,2);self.assertEqual(c.u(story.EVENTS),0);self.assertEqual(c.u(story.CONTROL+12),0)
        c.w(A(0x3337B8),0);tick(c,2);self.assertEqual(c.u(story.EVENTS),2)
        started=c.u(story.EVENTS+8);tick(c,10)
        self.assertEqual((c.u(story.EVENTS),c.u(story.EVENTS+8)),(2,started))

    def test_repeated_destructions_and_rewinding_keep_guest_journal_consistent(self):
        c=destruction_machine(2);initial=copy.deepcopy(c.memory)
        complete_destruction(c);tick(c,2);self.assertEqual(c.u(story.EVENTS),0)
        c.w(A(0x31BE74),0);complete_destruction(c,5);tick(c,2)
        self.assertEqual(c.u(story.DESTRUCTION_COUNT),2);self.assertEqual(c.u(story.EVENTS),2)
        c.memory=initial;tick(c,2)
        self.assertEqual(c.u(story.DESTRUCTION_COUNT),0);self.assertEqual(c.u(story.EVENTS),0)

    def test_observer_preserves_ee_registers_and_ignores_another_world(self):
        c=destruction_machine()
        for reg in (8,9,10,16):c.r[reg]=0xABCDEF01234567891020304050607080+reg
        c.f[0]=0x3F800000;c.fcr31=137;c.hi=4;c.lo=9
        before=([c.r[r] for r in (8,9,10,16)],c.f.copy(),c.fcr31,c.hi,c.lo)
        complete_destruction(c)
        self.assertEqual(([c.r[r] for r in (8,9,10,16)],c.f,c.fcr31,c.hi,c.lo),before)
        c=destruction_machine();c.w(story.CONTROL+4,c.manager+16);complete_destruction(c)
        self.assertEqual(c.u(story.DESTRUCTION_COUNT),0);self.assertEqual(c.u(A(0x31BE74)),1)

    def test_hook_installation_is_exact_and_only_required_for_triggered_scenarios(self):
        ram=bytearray(0x8000000);entry=A(0x13F3C8)
        original=elf_reader(elf_path(ROOT))[2](entry,16);ram[entry:entry+16]=original
        blocks=dict(story.destruction_blocks(ram,document()))
        self.assertEqual(blocks[entry],story.jump(story.DESTRUCTION));self.assertEqual(blocks[story.DESTRUCTION_NATIVE],original)
        ram[entry]^=1
        with self.assertRaisesRegex(ValueError,'hook changed'):story.destruction_blocks(ram,document())
        self.assertEqual(story.destruction_blocks(ram,missions.default_mission()),[])
        # A win/fail-only condition also needs the observer.
        d=missions.default_mission();d['fail_when']=dict(type='planet_destroyed')
        self.assertTrue(story.uses_destruction_trigger(missions.validate(d)))

    def test_prepared_mission_patch_includes_observer_without_section_overlap(self):
        from test_story_missions import DependencyTests
        ram,d=DependencyTests().prepared();d['events'][0]['when']=dict(type='planet_destroyed')
        entry=A(0x13F3C8);ram[entry:entry+16]=elf_reader(elf_path(ROOT))[2](entry,16)
        plan=story.build_memory(ram,missions.validate(d))
        blocks={b['address']:bytes.fromhex(b['data_hex']) for b in plan['blocks']}
        self.assertEqual(blocks[entry],story.jump(story.DESTRUCTION))
        self.assertEqual(blocks[story.DESTRUCTION],story.destruction_code())
        self.assertEqual(struct.unpack_from('<2I',blocks[story.CONTROL],104),(0,0))

    def test_workbench_status_exposes_journal_count_and_destination(self):
        from test_trainer_bridge import Client
        d=document();c=destruction_machine();raw=missions.encoded(d)
        c.write(story.CONTROL+64,bytes.fromhex(missions.digest(d)));c.w(story.DOCUMENT,len(raw));c.write(story.DOCUMENT+4,raw)
        initial=story.snapshot(Client(c));self.assertEqual(initial['planet_destructions'],0);self.assertIsNone(initial['last_destroyed_stage'])
        complete_destruction(c,5);state=story.snapshot(Client(c))
        self.assertEqual((state['planet_destructions'],state['last_destroyed_stage']),(1,5))


@unittest.skipUnless(importlib.util.find_spec('PySide6'),'Use Workbench GUI environment for authoring checks')
class PlanetEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_event_and_outcome_editor_expose_occurrence_and_graph_description(self):
        import story_editor as ui
        d=document(2);dialog=ui.EventDialog(d,d['events'][0])
        self.assertEqual(dialog.value_event()['when'],dict(type='planet_destroyed',occurrence=2))
        self.assertFalse(dialog.subject.isEnabled());self.assertFalse(dialog.value.isEnabled());self.assertTrue(dialog.occurrence.isEnabled())
        dialog.occurrence.setValue(3);self.assertEqual(dialog.value_event()['when']['occurrence'],3)
        self.assertEqual(ui.condition_label(dialog.value_event()['when']),'After planet destruction #3');dialog.close()
        dialog=ui.ConditionDialog(d);dialog.kind.setCurrentIndex(dialog.kind.findData('planet_destroyed'));dialog.occurrence.setValue(2)
        self.assertEqual(dialog.value(),dict(type='planet_destroyed',occurrence=2));self.assertFalse(dialog.fighter.isEnabled());dialog.close()


if __name__=='__main__':unittest.main()
