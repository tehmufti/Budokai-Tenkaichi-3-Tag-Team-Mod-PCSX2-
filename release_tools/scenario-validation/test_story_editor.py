"""Creator workflows in offscreen Qt; no emulator, sockets, or game-state loads."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HAS_QT=importlib.util.find_spec('PySide6') is not None
if HAS_QT:
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    import story_editor as ui
    import story_missions as missions


@unittest.skipUnless(HAS_QT,'Use the Workbench .gui-venv Python for native UI tests')
class EditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.library=patch.object(missions,'LIBRARY',self.folder);self.library.start()
        self.socket=patch('socket.create_connection',side_effect=AssertionError('Creator must stay offline'));self.socket.start()
        self.widget=ui.StoryEditor()

    def tearDown(self):
        self.widget.close();self.widget.deleteLater();self.app.processEvents()
        self.library.stop();self.socket.stop();self.temp.cleanup()

    def test_edit_form_costume_and_cpu_probability_preserves_unknown_form(self):
        dialog=ui.FighterDialog(dict(id='long-fighter-name-'+'x'*30,team=2,slot=2,character=65000,costume=7,reserve=True),{})
        dialog.chance.setValue(25);fighter,key,profile=dialog.value()
        self.assertEqual((fighter['character'],fighter['costume']),(65000,7))
        self.assertLessEqual(len(key),48);self.assertEqual(profile['transform_chance'],25)
        self.assertTrue(fighter['reserve']);dialog.close()

    def test_library_loads_independent_copy_and_waves_round_trip(self):
        document=missions.default_mission();document['fighters'].append(dict(id='next',team=2,slot=2,character=3))
        path=self.folder/'original.json';missions.save(path,document)
        self.widget.refresh_library();self.widget.load_preset();self.widget.waves()
        result=missions.validate(self.widget.document)
        self.assertTrue(result['fighters'][-1]['reserve']);self.assertEqual(result['events'][0]['when']['fighter'],'rival')
        self.assertEqual(missions.load(path)['events'],[]);self.assertIsNone(self.widget.path)

    def test_arming_embeds_current_editor_values_and_does_not_save_emulator_state(self):
        self.widget.title.setText('Independent test battle');self.widget.stage.setValue(12)
        original=missions.arm;path=self.folder/'armed.json'
        with patch.object(missions,'arm',side_effect=lambda doc:original(doc,path)):
            self.widget.arm()
        armed=missions.armed(path);self.assertEqual(armed['title'],'Independent test battle')
        self.assertEqual(armed['stage']['id'],12)
        self.assertEqual({p.name for p in self.folder.iterdir()},{'armed.json','.armed.json.lock'})

    def test_complex_condition_is_preserved_and_second_wind_actions_are_editable(self):
        document=missions.default_mission()
        event=dict(id='return',when=dict(type='any',conditions=[dict(type='time',seconds=50),dict(type='defeated',fighter='hero')]),
            actions=[dict(type='recover',fighter='hero'),dict(type='transform',fighter='hero',character=1)])
        dialog=ui.EventDialog(document,event)
        self.assertEqual(dialog.value_event()['when'],event['when'])
        self.assertEqual(dialog.value_event()['actions'],event['actions']);dialog.close()

    def test_action_controls_expose_health_intro_and_message_duration(self):
        document=missions.default_mission();dialog=ui.ActionDialog(document,'enter')
        dialog.health.setValue(45);dialog.intro.setChecked(False)
        self.assertEqual(dialog.value(),dict(type='enter',fighter='hero',health_percent=45,intro=False));dialog.close()
        dialog=ui.ActionDialog(document,'message');dialog.text.setText('Reinforcements!');dialog.seconds.setValue(7)
        self.assertEqual(dialog.value(),dict(type='message',text='Reinforcements!',seconds=7));dialog.close()

    def test_action_node_editor_round_trips_and_reorders_without_json(self):
        document=missions.default_mission()
        actions=[dict(type='recover',fighter='hero',health_percent=1),
                 dict(type='cinematic',fighter='hero',animation=dict(character=0,clip=212),seconds=1.97,speed=.8,
                      voice=dict(character=1,line=71,volume=75),camera=dict(eye=[0,-16,55],target=[0,-9,0],end_eye=[8,-16,55])),
                 dict(type='heal',fighter='hero',health_percent=100)]
        import json
        rows=ui.ActionList(document);rows.setPlainText(json.dumps(actions));rows.list.setCurrentRow(2);rows.move(-1)
        self.assertEqual([a['type'] for a in json.loads(rows.toPlainText())],['recover','heal','cinematic'])
        dialog=ui.ActionDialog(document,'cinematic',action=actions[1]);self.assertEqual(dialog.value(),actions[1]);dialog.close();rows.close()

    def test_graph_shows_dependencies_and_ordered_editable_action_nodes(self):
        from story_graph import references
        document=missions.default_mission();document['events']=[
            dict(id='wake',when=dict(type='defeated',fighter='hero'),actions=[dict(type='recover',fighter='hero'),dict(type='heal',fighter='hero')]),
            dict(id='form',when=dict(type='event',event='wake'),actions=[dict(type='transform',fighter='hero',character=1)])]
        self.widget.document=missions.validate(document);self.widget.refresh();graph=self.widget.graph
        self.assertEqual(len(graph.nodes),5);self.assertGreater(graph.event_nodes[1].x(),graph.event_nodes[0].x())
        self.assertEqual(references(document['events'][1]['when']),{'wake'})
        graph.selected.emit(1,0);self.assertEqual(self.widget.events.currentRow(),1)
        graph.show_status(dict(events=[dict(id='wake',status='complete')]));self.assertEqual(graph.event_nodes[0].pen().color().name(),'#5acd9c')

    def test_voice_picker_returns_line_and_closes_without_emulator(self):
        from story_voice_picker import VoicePicker
        with patch('story_voice.default_iso',return_value=''):
            dialog=VoicePicker(1,71,80);dialog.loaded([(i,.5,None if i!=2 else 'Empty') for i in range(100)])
            dialog.list.setCurrentRow(71);self.assertEqual(dialog.line,71);self.assertTrue(dialog.play_button.isEnabled())
            dialog.list.setCurrentRow(2);self.assertFalse(dialog.play_button.isEnabled());dialog.close()

    def test_short_event_timeout_is_explained(self):
        document=missions.default_mission();dialog=ui.EventDialog(document);dialog.timeout.setValue(1)
        self.assertIn('KO',dialog.timing_warning.text());dialog.timeout.setValue(30);self.assertFalse(dialog.timing_warning.text());dialog.close()

    def test_stat_overrides_delays_and_camera_only_pan_round_trip(self):
        document=missions.default_mission()
        values=dict(max_hp=45000,damage=1.2,defense=1.15,invulnerable=False,blast_stocks=3)
        dialog=ui.ActionDialog(document,'set_stats',action=dict(type='set_stats',fighter='hero',stats=values))
        self.assertEqual(dialog.value()['stats'],values)
        enabled,value=dialog.stats.fields['damage'];enabled.setChecked(False)
        self.assertFalse(value.isEnabled());self.assertNotIn('damage',dialog.value()['stats']);dialog.close()
        dialog=ui.ActionDialog(document,'wait');dialog.seconds.setValue(1.75);dialog.freeze.setChecked(True)
        self.assertEqual(dialog.value(),dict(type='wait',seconds=1.75,freeze=True));dialog.close()
        dialog=ui.ActionDialog(document,'cinematic');dialog.animated.setChecked(False)
        dialog.easing.setCurrentIndex(dialog.easing.findData('ease_out'));dialog.end_eye.setText('8, -16, 55')
        result=dialog.value();self.assertNotIn('animation',result);self.assertEqual(result['camera']['easing'],'ease_out')
        self.assertTrue(dialog.clip.isEnabled())
        self.assertNotIn('animation',dialog.value());dialog.close()

    def test_camera_only_shot_can_choose_donor_and_enable_animation(self):
        shot=dict(type='cinematic',fighter='hero',seconds=3,camera=dict(eye=[0,-16,55],target=[0,-9,0]),
                  voice=dict(character=0,line=71,volume=80))
        dialog=ui.ActionDialog(missions.default_mission(),'cinematic',action=shot)
        self.assertFalse(dialog.animated.isChecked());self.assertTrue(dialog.donor.isEnabled())
        dialog.donor.setCurrentIndex(dialog.donor.findData(29));dialog.clip.setValue(384)
        result=dialog.value();self.assertEqual(result['animation'],dict(character=29,clip=384))
        self.assertEqual(result['fighter'],'hero');self.assertEqual(result['voice'],shot['voice'])
        dialog.close()

    def test_accepting_preview_copies_both_donor_and_clip_even_from_camera_only_shot(self):
        from types import SimpleNamespace
        dialog=ui.ActionDialog(missions.default_mission(),'cinematic');dialog.animated.setChecked(False)
        picker=SimpleNamespace(exec=lambda:ui.QDialog.Accepted,donor=29,clip=384,bank=None)
        with patch('story_preview.AnimationPicker',return_value=picker):dialog.preview()
        self.assertEqual(dialog.value()['animation'],dict(character=29,clip=384))
        self.assertTrue(dialog.animated.isChecked());dialog.close()

    def test_small_editor_keeps_fighter_table_and_event_flow_reachable(self):
        from PySide6.QtCore import QPoint
        self.widget.resize(640,400);self.widget.show();self.app.processEvents()
        self.assertLessEqual(self.widget.width(),640);self.assertLessEqual(self.widget.height(),400)
        self.assertGreater(self.widget.scroll.verticalScrollBar().maximum(),0)
        self.assertGreaterEqual(self.widget.fighters.height(),180)
        for child in (self.widget.fighters,self.widget.event_tabs):
            self.widget.scroll.ensureWidgetVisible(child,0,0);self.app.processEvents()
            self.assertTrue(self.widget.scroll.viewport().rect().contains(
                child.mapTo(self.widget.scroll.viewport(),QPoint(child.width()//2,child.height()//2))))

    def test_small_fighter_and_event_dialogs_keep_confirmation_buttons_visible(self):
        from PySide6.QtCore import QPoint
        for dialog in (ui.FighterDialog(missions.default_mission()['fighters'][0],{}),
                       ui.EventDialog(missions.default_mission())):
            dialog.resize(640,400);dialog.show();self.app.processEvents()
            self.assertLessEqual(dialog.height(),400)
            buttons=dialog.findChildren(ui.QDialogButtonBox)[-1]
            self.assertTrue(dialog.rect().contains(buttons.mapTo(dialog,QPoint(buttons.width()//2,buttons.height()//2))))
            self.assertGreater(dialog.form_scroll.verticalScrollBar().maximum(),0)
            dialog.close()

    def test_preview_donor_switch_discards_stale_load_and_accepts_new_bank(self):
        import story_preview as preview
        from PySide6.QtCore import QObject,Signal
        from PySide6.QtWidgets import QWidget
        from types import SimpleNamespace
        class FakeViewport(QWidget):
            playing=False
            def set_asset(self,asset):self.asset=asset
            def set_clip(self,clip):self.clip=clip
        class FakeLoader(QObject):
            loaded=Signal(object,object);failed=Signal(str);finished=Signal()
            def __init__(self,iso,body,costume,donor,parent):
                super().__init__(parent);self.args=(iso,body,costume,donor);self.unsupported=[]
            def start(self):pass
            def isRunning(self):return False
        iso=self.folder/'fixture.iso';iso.write_bytes(b'fixture')
        with patch('game_profile.iso_path',return_value=str(iso)),patch.object(preview,'Loader',FakeLoader),patch.object(preview,'ModelViewport',FakeViewport):
            dialog=preview.AnimationPicker(0,0,0,384);first=dialog.loader
            dialog.donor_box.setCurrentIndex(dialog.donor_box.findData(29))
            clip=SimpleNamespace(animation_id=384,duration_seconds=2)
            bank=SimpleNamespace(clips=[clip])
            first.loaded.emit('old-model',bank)
            self.assertIsNone(dialog.bank);self.assertFalse(dialog.buttons.button(ui.QDialogButtonBox.Ok).isEnabled())
            first.finished.emit();current=dialog.loader
            self.assertEqual(current.args[-1],29);current.loaded.emit('new-model',bank);current.finished.emit()
            self.assertEqual(dialog.donor,29);self.assertEqual(dialog.clip,384)
            self.assertEqual(dialog.viewport.asset,'new-model')
            self.assertTrue(dialog.buttons.button(ui.QDialogButtonBox.Ok).isEnabled());dialog.close()

    def test_event_completion_delay_failure_policy_and_inversion(self):
        document=missions.default_mission();document['events']=[dict(id='opening',when=dict(type='time',seconds=0),actions=[])]
        event=dict(id='arrival',when=dict(type='event',event='opening',delay_seconds=60),
                   actions=[dict(type='message',text='Arrived',seconds=3)],on_failure='fail_scenario')
        dialog=ui.EventDialog(document,event)
        self.assertEqual(dialog.value_event()['when'],event['when'])
        self.assertEqual(dialog.value_event()['on_failure'],'fail_scenario')
        dialog.edit_condition('not')
        self.assertEqual(dialog.value_event()['when'],dict(type='not',condition=event['when']))
        dialog.close()

    def test_cpu_copy_keeps_non_difficulty_stats_and_uses_effective_source_difficulty(self):
        document=missions.default_mission()
        document['fighters'][0]['stats']=dict(difficulty=4,damage=1.5)
        document['fighters'][1]['stats']=dict(difficulty=1,defense=2)
        copied=missions.copy_cpu_profile(document,'hero','rival')['fighters'][1]
        self.assertEqual(copied['difficulty'],4);self.assertEqual(copied['stats'],dict(defense=2))

    def test_preview_keeps_valid_clips_and_reports_unsupported_clip(self):
        import story_preview as preview,model_assets,model_animations
        from types import SimpleNamespace
        with patch.object(model_assets,'package_entry',side_effect=lambda data,index:b'bad' if index==2 else b'ok' if index==1 else b''), \
             patch.object(model_animations,'decompress_animation',side_effect=lambda raw:raw), \
             patch.object(model_animations.AnimationClip,'from_decoded',side_effect=lambda index,raw:SimpleNamespace(animation_id=index) if raw==b'ok' else (_ for _ in ()).throw(model_animations.AnimationFormatError('Unsupported fixture'))):
            bank,unsupported=preview.preview_bank((440).to_bytes(4,'little'))
        self.assertEqual([c.animation_id for c in bank.clips],[0]);self.assertEqual(unsupported,[(1,'Unsupported fixture')])
        with self.assertRaisesRegex(ValueError,'Truncated'):preview.preview_bank(b'')

    def test_cinematic_animation_and_voice_can_use_different_characters(self):
        document=missions.default_mission();dialog=ui.ActionDialog(document,'cinematic')
        dialog.donor.setCurrentIndex(dialog.donor.findData(1));dialog.clip.setValue(318)
        dialog.voice_enabled.setChecked(True);dialog.voice_character.setCurrentIndex(dialog.voice_character.findData(0));dialog.voice_line.setValue(71)
        action=dialog.value();document['events']=[dict(id='shot',when=dict(type='time',seconds=0),actions=[action])]
        missions.validate(document)
        self.assertEqual(action['animation'],dict(character=1,clip=318));self.assertEqual(action['voice']['character'],0)
        self.assertLess(action['camera']['eye'][1],0);dialog.close()

    def test_fighter_hp_difficulty_transform_limits_and_both_finisher_outcomes_round_trip(self):
        document=missions.default_mission();dialog=ui.FighterDialog(document['fighters'][0],{})
        dialog.hp.setValue(85000);dialog.difficulty.setCurrentIndex(dialog.difficulty.findData(4))
        dialog.form_limit.setValue(2);dialog.allowed_forms.setText('1, 2, 3')
        f,key,profile=dialog.value();document['fighters'][0]=f;document['cpu_profiles']={key:profile}
        dialog.close();dialog=ui.RulesDialog(document)
        for mode in ('fail','hold_at_1_hp'):
            dialog.rules=[dict(victim='rival',attacker='hero',attack='ultimate',otherwise=mode)]
            saved=missions.validate(dict(document,**dialog.value()))
            self.assertEqual(saved['finish_rules'][0]['otherwise'],mode)
            self.assertEqual(saved['fighters'][0]['hp'],85000);self.assertEqual(saved['fighters'][0]['difficulty'],4)
            self.assertEqual(saved['fighters'][0]['transformations']['allowed_forms'],[1,2,3])
            self.assertFalse(saved['menus']['character_select'])
        dialog.close()


if __name__=='__main__':unittest.main()
