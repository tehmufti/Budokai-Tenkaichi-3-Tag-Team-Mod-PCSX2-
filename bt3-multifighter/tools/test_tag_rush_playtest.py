"""Normal offline admission, complete disc assets and trainer ordering."""
import copy
import hashlib
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import tag_rush_install as install
import tag_rush_scene as scene
import tag_team_rush as tag
import tag_rush_shots as shots
import fresh_team_trainer as trainer
import tag_rush_availability as availability
import native_map
from test_tag_rush_install import fixture,assets,apply,u,admitted,OPTIONS


class LocalPlaytestEntryTests(unittest.TestCase):
    def test_optin_is_exact_and_cannot_follow_an_online_preparation_copy(self):
        for flag,target,wanted in (('0',str(install.ROOT),False),('true',str(install.ROOT),False),
                                  ('1','',False),('1',str(install.ROOT/'online/prep/game'),False),
                                  ('1',str(install.ROOT),True)):
            with patch.dict(os.environ,{install.PLAYTEST_ENV:flag,install.PLAYTEST_ROOT_ENV:target}):
                self.assertEqual(install.playtest_requested(),wanted)

    def test_incomplete_requested_playtest_explains_failure_and_writes_nothing(self):
        ram=fixture();before=bytes(ram)
        with patch.object(install,'cached_assets',return_value=(assets(),'fixture')),\
                patch.object(install.assets,'character_admission',side_effect=admitted):
            with self.assertRaisesRegex(ValueError,'Tag attack setup stopped.*reviewed native beam'):
                install.build_offline(ram,OPTIONS,iso='unused.iso')
        self.assertEqual(ram,before)

    def test_disabled_online_and_ffa_never_read_disc_or_install(self):
        from test_tag_rush_install import w
        for kind in ('disabled','online','online_ram','ffa'):
            ram=fixture();options=OPTIONS;online=kind=='online'
            if kind=='disabled':options={'tag_team_rush_enabled':False}
            if kind=='online_ram':w(ram,install.NETPLAY_CONTROL,install.NETPLAY_MAGIC);w(ram,install.NETPLAY_CONTROL+4,1)
            if kind=='ffa':w(ram,install.modes.CONTROL+12,install.modes.FFA)
            with patch.object(install,'cached_assets') as load:
                plan=install.build_offline(ram,options,iso='unused.iso',online=online)
            self.assertEqual(plan['blocks'],[]);self.assertFalse(plan['usable']);load.assert_not_called()

    def test_normal_trainer_stage_needs_no_playtest_environment_and_keeps_online_out(self):
        for mode,enabled,online,adapter,called in (
                ('training',True,False,'bt3-usa',True),('teams',True,False,'bt3-usa',True),
                ('training_coop',True,False,'bt4-b14-rev2-eng',True),
                ('training',False,False,'bt3-usa',False),('ffa',True,False,'bt3-usa',False),
                ('teams',True,True,'bt3-usa',False),('teams',True,False,'bt3-pal',False),
                ('teams',True,False,'bt3-jpn',False)):
            events=[]
            session=SimpleNamespace(settings={'tag_team_rush_enabled':enabled},battle_mode=mode,source='fixture',
                progress=lambda *args:events.append(('progress',args)),
                snapshot=lambda name:events.append(('snapshot',name)) or b'prepared',
                install=lambda plan,name:events.append(('install',name)))
            env={install.PLAYTEST_ENV:'0',availability.ONLINE_PREPARATION_ENV:'1' if online else '0'}
            with patch.dict(os.environ,env),patch.object(native_map,'ADAPTER',adapter),\
                    patch.object(install,'build_offline',return_value={'blocks':[{}]}) as build:
                trainer.Session.install_tag_rush(session)
                self.assertEqual(build.called,called)
                if called:
                    self.assertEqual(build.call_args.args[0],b'prepared')
                    self.assertEqual(build.call_args.kwargs['training'],mode in ('training','training_coop'))
                    self.assertEqual(build.call_args.kwargs['source'],'fixture')
                    self.assertEqual([e[0] for e in events],['progress','snapshot','install'])
                else:self.assertEqual(events,[])


class RealDiscPlaytestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        name='SLUS_219.78.DBZBT4B14REV2ENG.iso' if install.SERIAL=='SLUS-21978' else 'Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso'
        cls.iso=Path(__file__).resolve().parents[2]/'games'/name
        if not cls.iso.is_file():raise unittest.SkipTest('Local game disc is unavailable')
        cls.pack=install.assets.build_assets(cls.iso,include_beam=True,include_camera=True)

    def test_normal_match_reviews_assets_then_waits_for_native_initialization(self):
        self.assertFalse(scene.installation(self.pack)['usable'])
        self.assertFalse(scene.installation(self.pack)['playtest_ready'])
        ram=fixture();before=bytes(ram)
        with patch.object(install,'cached_assets',return_value=(self.pack,'disc-fixture')):
            normal=install.build_memory(ram,OPTIONS,iso=self.iso,enable_scene=True)
            self.assertFalse(normal['usable']);self.assertEqual(normal['blocks'],[])
            plan=install.build_offline(ram,OPTIONS,iso=self.iso,training=True)
        self.assertTrue(plan['usable']);self.assertEqual(ram,before);apply(ram,plan)
        self.assertEqual(u(ram,tag.CONTROL+tag.C['ready']),0)
        self.assertEqual(u(ram,tag.CONTROL+shots.TABLE_OFFSET),self.pack['camera_asset']['table_address'])
        self.assertEqual(u(ram,tag.CONTROL+shots.MAGIC_OFFSET),shots.MAGIC)
        self.assertEqual(u(ram,install.bootstrap.STATE+install.bootstrap.S['phase']),install.bootstrap.WAITING)

    def test_missing_camera_pose_or_impact_assets_refuse_explicit_playtest(self):
        for key in ('beam_asset','camera_asset','clips','audio_cues'):
            pack=copy.deepcopy(self.pack);pack.pop(key)
            with self.assertRaises((ValueError,KeyError)):
                install.review_playtest_assets(pack,iso=self.iso)
        pack=copy.deepcopy(self.pack);pack['variants']['two_ki']['count']=4
        with self.assertRaisesRegex(ValueError,'phase count'):install.review_playtest_assets(pack,iso=self.iso)

    def test_derived_pose_cannot_approve_itself_with_a_replaced_cache_hash(self):
        self._assert_pose_source_review(special=False,reason='donor clip changed')

    def test_restraint_pose_cannot_approve_itself_with_a_replaced_cache_hash(self):
        self._assert_pose_source_review(special=True,reason='Special tag restraint source changed')

    def _assert_pose_source_review(self,*,special,reason):
        import model_animations as animations
        pack=copy.deepcopy(self.pack)
        clip=next(row for row in pack['clips'] if row['animation']>=1000
                  and bool(row.get('special_pair'))==special)
        for index,(base,data) in enumerate(pack['blocks']):
            offset=clip['address']-base
            if 0<=offset and offset+clip['size']<=len(data):
                raw=bytearray(animations.decompress_animation(data[offset:offset+clip['size']]))
                raw[-1]^=1
                changed=install.assets.literal_pack(bytes(raw))
                self.assertEqual(len(changed),clip['size'])
                pack['blocks'][index]=(base,data[:offset]+changed+data[offset+len(changed):])
                clip['decoded_sha256']=hashlib.sha256(raw).hexdigest()
                break
        else:self.fail('No captured derived pose')
        with self.assertRaisesRegex(ValueError,reason):
            install.review_playtest_assets(pack,iso=self.iso)

    def test_finisher_geometry_is_checked_independently_of_cached_metadata(self):
        import struct
        pack=copy.deepcopy(self.pack)
        row=pack['choreography_asset']['variants']['two_ki']
        address=row['address']+4*64+16
        for index,(base,data) in enumerate(pack['blocks']):
            offset=address-base
            if 0<=offset and offset+4<=len(data):
                altered=bytearray(data);struct.pack_into('<f',altered,offset,999999.)
                pack['blocks'][index]=(base,bytes(altered));break
        else:self.fail('No captured staging table')
        with self.assertRaisesRegex(ValueError,'positions or beam timings'):
            install.review_playtest_assets(pack,iso=self.iso)

    def test_unrelated_unsupported_body_keeps_zero_admission_while_others_work(self):
        ram=fixture()
        def roster(iso,rows):return [dict(row,supported=row['index']!=3) for row in rows]
        with patch.object(install,'cached_assets',return_value=(self.pack,'disc-fixture')),\
                patch.object(install.assets,'character_admission',side_effect=roster):
            plan=install.build_playtest(ram,OPTIONS,iso=self.iso)
        self.assertTrue(plan['usable']);apply(ram,plan)
        ptr=u(ram,tag.CONTROL+0x3A0);self.assertEqual(ram[ptr+3],0)
        self.assertTrue(all(ram[ptr+i]&1 for i in range(3)))


if __name__=='__main__':unittest.main()
