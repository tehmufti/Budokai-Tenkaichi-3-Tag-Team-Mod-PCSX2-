"""Offline regressions, including actual disc resources when installed."""
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import shutil
import tempfile
import types
import unittest
from .disc import Disc,FormatError,entry,package,executable_fingerprint,pcsx2_crc
from .scanner import scan,cached_profile,cache_index,atomic_json,mesh_info,combat_info,validate_stage_transitions,DEFAULT_CACHE
from .adapters import identify,runtime_match,verify_stage_mapping,BY_NAME
from . import known_discs
from .stages import inspect_stage
from .map_scaling import plan_stage

ROOT=Path(__file__).resolve().parents[1]
BT3=ROOT/'games/Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso'
BT4=ROOT/'games/SLUS_219.78.DBZBT4B14REV2ENG.iso'
BT4_ES=ROOT/'games/SLUS_219.78.DBZBT4B14REV2.iso'
PAL=ROOT/'games/Dragon Ball Z - Budokai Tenkaichi 3 (AU,EU) (En,Ja,Fr,De,Es,It) (2007) (Versus Fighting) (ISO) (PS2).iso'
JPN=ROOT/'games/Dragon Ball Z - Sparking! Meteor (Japan).iso'
# Profiles of the real discs: the shared cache, or a scratch folder (TAGTEAM_TEST_PROFILES) for read-only runs.
PROFILES=Path(os.environ.get('TAGTEAM_TEST_PROFILES') or DEFAULT_CACHE)


class BoundsTests(unittest.TestCase):
    def test_declared_empty_effects_are_supported_but_not_truncated_nonempty_effects(self):
        offsets=[32,32,48,64,80,96,112]
        raw=struct.pack('<8I',6,*offsets)+bytes(80)
        self.assertEqual(combat_info(raw)['empty_effect_slots'],[1])
        # Masked-equal offsets with different native flags are NOT absent.
        bad=bytearray(raw);struct.pack_into('<I',bad,8,33)
        with self.assertRaisesRegex(FormatError,'slot 1'):combat_info(bad)

    def test_destruction_destination_effect_failure_propagates_through_stages(self):
        stages=[dict(stage_id=i,variants={n:dict(runtime_eligible=i!=2,structurally_valid=True,
            destruction_target=(i+1 if i<2 else None)) for n in ('normal','split_screen')}) for i in range(3)]
        issues=[];validate_stage_transitions(stages,lambda *x:issues.append(x))
        self.assertTrue(all(not r['runtime_eligible'] for r in stages))
        self.assertFalse(stages[0]['variants']['normal']['destruction_resources_valid'])
        self.assertEqual(len(issues),4)
    def test_bad_package_offsets_do_not_escape_buffer(self):
        for raw in (b'',struct.pack('<4I',2,16,32,500),struct.pack('<4I',2,16,12,16)):
            with self.assertRaises(FormatError):package(raw)
    def test_unused_bad_tail_does_not_hide_valid_native_entry(self):
        raw=struct.pack('<5I',3,20,24,28,1000)+b'AAAABBBB'
        self.assertEqual(entry(raw,1),b'BBBB')
        with self.assertRaises(FormatError):entry(raw,2)
        with self.assertRaises(FormatError):package(raw)


@unittest.skipUnless(BT3.exists() and BT4.exists(),'Local ISO files not installed')
class RealDiscTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bt3=scan(BT3,PROFILES);cls.bt4=scan(BT4,PROFILES)

    def test_original_disc_all_selectable_costumes_and_maps(self):
        self.assertEqual(self.bt3['summary']['base_fighters_valid'],161)
        self.assertEqual(self.bt3['summary']['costume_variants_valid'],698)
        self.assertEqual(self.bt3['summary']['stage_variants_valid'],70)
        self.assertEqual(self.bt3['issues'],[])

    def test_bt4_all_populated_forms_and_costumes_have_safe_loads(self):
        self.assertEqual(self.bt4['summary']['base_fighters_valid'],241)
        self.assertEqual(self.bt4['summary']['costume_variants'],1558)
        bad={(r['character_id'],v['costume'],v['damaged']) for r in self.bt4['characters'] for v in r['costumes'] if not v['structurally_valid']}
        self.assertEqual(bad,set())
        fallback={(r['character_id'],v['costume']) for r in self.bt4['characters'] for v in r['costumes'] if v.get('damage_fallback')}
        self.assertEqual(fallback,{(240,c) for c in (0,1,2,4,5,6,7,8)})
        self.assertEqual(self.bt4['layout']['empty_character_slots'],[231,232,233,234,235])

    def test_every_combat_slot_and_transformation_destination_has_an_audit(self):
        for profile in (self.bt3,self.bt4):
            for row in profile['characters']:
                self.assertEqual(len(row['special_effect_slots']),5)
                self.assertTrue(all(f['resources_valid'] for f in row['form_resources']))
        self.assertEqual({r['character_id'] for r in self.bt4['characters'] if r['empty_effect_slots']},{104,150})

    def test_bt4_native_fusion_recipes_include_new_pairs_and_correct_timer_types(self):
        from .scanner import report
        self.assertEqual(self.bt4['fusion_audit']['recipes'],26)
        self.assertEqual(self.bt4['fusion_audit']['unsupported'],[])
        fighters={r['character_id']:r for r in self.bt4['characters']}
        for char,result,kind,timed in ((34,76,'potara',False),(118,104,'potara',True),(44,48,'dance',True)):
            recipe=fighters[char]['fusion_recipes'][0]
            self.assertEqual((recipe['result'],recipe['kind'],recipe['timed_defusion']),(result,kind,timed))
            self.assertTrue(recipe['resources_valid'])
        self.assertEqual(fighters[58]['fusion_recipes'],[])
        self.assertIn('## Fusion recipes',report(self.bt4))

    def test_missing_split_stage_uses_same_arena_normal_geometry(self):
        for sid in (53,54):
            stage=self.bt4['stages'][sid]
            self.assertTrue(stage['runtime_eligible'])
            self.assertEqual(stage['variants']['split_screen']['file_id'],1523+sid)
            self.assertEqual(stage['variants']['split_screen']['native_file_id'],1622+sid)
            self.assertFalse(stage['variants']['split_screen']['runtime_verified'])

    def test_iso_index_is_self_contained_and_mesh_tail_exception_is_bounded(self):
        with Disc(BT4) as disc:
            self.assertEqual(len(disc.tables[2]),32775)
            raw=disc.read(6280)  # Beerus: native collision and geometry valid, unused tail stale
            with self.assertRaises(FormatError):package(raw)
            self.assertGreater(mesh_info(raw,0x6000)['draw_nodes'],0)

    def test_changed_executable_never_enables_runtime_adapter(self):
        with Disc(BT4) as disc:
            self.assertTrue(identify(disc)[1])
            changed=bytearray(disc.elf);changed[4096]^=1;disc.elf=bytes(changed)
            self.assertFalse(identify(disc)[1])
        with Disc(BT4) as disc:
            disc.member_hashes['/BIN/DBZP.BIN;1']='0'*64
            self.assertFalse(identify(disc)[1])

    def test_unloaded_elf_trailer_changes_identity_but_not_runtime_compatibility(self):
        for path in (BT3,BT4):
            with self.subTest(path=path.name),Disc(path) as disc:
                original=executable_fingerprint(disc.elf)
                crc=pcsx2_crc(disc.elf)
                disc.elf+=b'\x01\x00\x00\x00'
                self.assertNotEqual(pcsx2_crc(disc.elf),crc)
                self.assertEqual(executable_fingerprint(disc.elf),original)
                self.assertTrue(identify(disc)[1])

    def test_entry_point_bss_layout_and_loaded_data_are_not_ignored(self):
        with Disc(BT4) as disc:
            original=disc.elf
            ph=struct.unpack_from('<I',original,28)[0]
            for offset in (24,ph+32+20,1852416):
                with self.subTest(offset=offset):
                    changed=bytearray(original);changed[offset]^=1;disc.elf=bytes(changed)
                    self.assertFalse(identify(disc)[1])

    @unittest.skipUnless(BT4_ES.exists(),'Spanish BT4 ISO not installed')
    def test_spanish_bt4_is_independently_audited_and_addons_cannot_be_mixed(self):
        profile=scan(BT4_ES,PROFILES)
        self.assertTrue(profile['capabilities']['runtime_hooks'])
        self.assertEqual(profile['identity']['runtime_match']['variant'],'BT4 B14 REV2 Spanish')
        self.assertEqual(profile['identity']['runtime_match']['native_language'],'es')
        self.assertEqual(profile['summary']['base_fighters_valid'],241)
        self.assertEqual(profile['summary']['costume_variants_valid'],1558)
        self.assertEqual(profile['volumes']['2']['entries'],32774)
        self.assertEqual(next(r['name'] for r in profile['characters'] if r['character_id']==13),'Gohan (Niño)')
        self.assertEqual(next(r['name'] for r in profile['characters'] if r['character_id']==100),'Androide n°16')
        self.assertNotEqual(profile['identity']['iso_sha256'],self.bt4['identity']['iso_sha256'])
        with Disc(BT4_ES) as disc:
            self.assertEqual(pcsx2_crc(disc.elf),'428113C2')
            disc.member_hashes['/BIN/DBZP.BIN;1']=self.bt4['identity']['members']['/BIN/DBZP.BIN;1']
            self.assertFalse(identify(disc)[1])
        with Disc(BT3) as disc:
            self.assertTrue(identify(disc)[1])
            disc.member_hashes['/BIN/DBZP.BIN;1']='0'*64
            self.assertFalse(identify(disc)[1])
        with Disc(BT4) as disc:
            disc.serial='SLUS_999.99'
            self.assertFalse(identify(disc)[1])

    def test_cache_invalidates_missing_changed_and_corrupted_data(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);fake=folder/'disc.iso';fake.write_bytes(b'local disc fixture')
            profile=copy.deepcopy(self.bt3)
            from .scanner import stat_key
            profile['source']=stat_key(fake)
            target=folder/(profile['identity']['iso_sha256']+'.json');atomic_json(target,profile)
            index=dict(source=profile['source'],sha256=profile['identity']['iso_sha256'],
                       profile_sha256=hashlib.sha256(target.read_bytes()).hexdigest())
            atomic_json(cache_index(fake,folder),index)
            self.assertIsNotNone(cached_profile(fake,folder))
            target.write_bytes(target.read_bytes()+b' ')
            self.assertIsNone(cached_profile(fake,folder))
            atomic_json(target,profile)
            fake.write_bytes(b'different file length')
            self.assertIsNone(cached_profile(fake,folder))

    def test_uniform_scale_expands_bounds_preserves_triangle_planes_and_normals(self):
        with Disc(BT3) as disc:raw=disc.read(369)
        plan=plan_stage(raw,2);scaled=plan.preview()
        old,new=inspect_stage(raw),inspect_stage(scaled)
        self.assertEqual(len(raw),len(scaled))
        self.assertEqual(new['arena'],{k:v*2 for k,v in old['arena'].items()})
        for before,after in zip(old['spawns'],new['spawns']):
            self.assertEqual(after['position'],[v*2 for v in before['position']])
            self.assertEqual(after['facing_point'],[v*2 for v in before['facing_point']])
        start,end=package(raw)[0];root=raw[start:end]
        u=lambda p:struct.unpack_from('<I',root,p)[0]
        sector=4*u(60);collider=4*u(sector+4);triangles=4*u(collider+16);vertices=4*u(collider+20)
        for tri in range(triangles,triangles+u(collider+4)*32,32):
            original=struct.unpack_from('<4f',raw,start+tri+16)
            changed=struct.unpack_from('<4f',scaled,start+tri+16)
            self.assertEqual(changed[:3],original[:3]);self.assertEqual(changed[3],original[3]*2)
            for i in struct.unpack_from('<3I',raw,start+tri+4):
                p=struct.unpack_from('<3f',raw,start+vertices+16*i)
                q=struct.unpack_from('<3f',scaled,start+vertices+16*i)
                self.assertEqual(q,tuple(v*2 for v in p))
        self.assertFalse(plan.summary()['ready_for_runtime'])
        self.assertEqual(plan_stage(raw,1).preview(),raw)

    def test_expanded_maps_keep_sky_and_scale_only_camera_position_channels(self):
        for file_id in (369,370):
            with Disc(BT3) as disc:raw=disc.read(file_id)
            scaled=plan_stage(raw,2).preview();entries=package(raw);base,end=entries[0];root=raw[base:end]
            u=lambda p:struct.unpack_from('<I',root,p)[0]
            h=lambda p:struct.unpack_from('<H',root,p)[0]
            group=4*u(28);materials=4*u(group+4)
            for material in range(materials,materials+h(group+2)*16,16):
                draws=4*u(material+4)
                for draw in range(draws,draws+h(material+2)*16,16):
                    start=4*u(draw+8);size=16+16*(u(start)&65535)
                    self.assertEqual(raw[base+start:base+start+size],scaled[base+start:base+start+size])
            camera_keys=0
            for start,end in entries[2:5]:
                if start==end:continue
                track=raw[start:end];changed=scaled[start:end];u=lambda p:struct.unpack_from('<I',track,p)[0]
                initial=u(24)
                self.assertEqual(struct.unpack_from('<3f',changed,initial),tuple(v*2 for v in struct.unpack_from('<3f',track,initial)))
                for row in range(u(8),u(8)+16*u(12),16):
                    channel,offset,count,_=struct.unpack_from('<4I',track,row)
                    for key in range(offset,offset+count*32,32):
                        self.assertEqual(track[key:key+8],changed[key:key+8])
                        self.assertEqual(track[key+12:key+32],changed[key+12:key+32])
                        old=struct.unpack_from('<f',track,key+8)[0];new=struct.unpack_from('<f',changed,key+8)[0]
                        self.assertEqual(new,old*2 if channel<3 else old);camera_keys+=1
            self.assertGreater(camera_keys,0)

    def test_stage_and_scale_corruption_fail_before_any_write(self):
        with Disc(BT3) as disc:raw=disc.read(369)
        for factor in (float('nan'),float('inf'),0,-1,True,10):
            with self.assertRaises(ValueError):plan_stage(raw,factor)
        damaged=bytearray(raw);start,_=package(raw)[0]
        struct.pack_into('<I',damaged,start+64,0xffffffff)
        with self.assertRaises(ValueError):plan_stage(damaged,2)


class KnownDiscTests(unittest.TestCase):
    """A refusal names the disc and the supported discs; recognition never enables an adapter."""
    def disc(self,serial,kind='unknown',members=()):
        return types.SimpleNamespace(serial=serial,kind=kind,members={m:1 for m in members})

    def test_family_discs_are_named_and_the_supported_discs_listed(self):
        K=known_discs
        cases=((self.disc('SLPM_611.62'),None,K.KNOWN_RELEASE,'demo (SLPM-61162)'),
               # The Japanese disc has a reviewed adapter: a refusal means changed code or files.
               (self.disc('SLPS_258.15'),None,K.MODIFIED_LAYOUT,'Sparking! Meteor'),
               (self.disc('SLPS_258.15','bt3-afs'),'executable',K.MODIFIED_EXECUTABLE,'Sparking! Meteor'),
               (self.disc('SLUS_216.78','bt3-afs'),'executable',K.MODIFIED_EXECUTABLE,'USA (SLUS-21678)'),
               (self.disc('SLUS_216.78','bt3-afs'),'addon',K.MODIFIED_ADDON,'USA (SLUS-21678)'),
               (self.disc('SLES_549.45','bt3-afs'),'executable',K.MODIFIED_EXECUTABLE,'Europe (SLES-54945)'),
               (self.disc('SLES_549.45','bt3-afs'),'addon',K.MODIFIED_ADDON,'Europe (SLES-54945)'),
               (self.disc('SLES_549.45'),None,K.MODIFIED_LAYOUT,'Europe (SLES-54945)'),
               (self.disc('SLUS_219.78','bt4-indexed'),'executable',K.OTHER_BT4,'(SLUS-21978)'),
               # An older BT4 build that still boots the BT3 USA executable name is a BT4 build.
               (self.disc('SLUS_216.78','unknown',('/BIN/DBZ4.BIN;1',)),None,K.OTHER_BT4,'(SLUS-21678)'),
               (self.disc('SLKA_999.99','unknown',('/DATA/PZS3KR1.AFS;1',)),None,K.OTHER_BT3,'(SLKA-99999)'),
               (self.disc('SLUS_203.12'),None,K.NOT_SUPPORTED,'(SLUS-20312)'))
        for disc,changed,template,named in cases:
            with self.subTest(serial=disc.serial,changed=changed):
                evidence=K.explain(disc,dict(verified=False,reason='technical'),changed)
                refusal=evidence['refusal']
                self.assertEqual(refusal['template'],template)
                self.assertEqual(evidence['reason'],'technical')
                self.assertIn(named,refusal['text'])
                for supported in ('SLUS-21678','SLES-54945','SLPS-25815','B14 REV2'):self.assertIn(supported,refusal['text'])
                self.assertNotIn('{',refusal['text'])
        self.assertEqual(K.serial_text('SLES_549.45'),'SLES-54945');self.assertEqual(K.serial_text(None),'unknown')
        # The installer composes the same text in its own language from the stored pieces.
        spanish={K.KNOWN_RELEASE:'La ISO es {disc}.',K.DISCS['SLPM_611.62']:'la demo japonesa',K.SUPPORTED:'Discos admitidos.'}
        self.assertEqual(K.message(K.KNOWN_RELEASE,K.DISCS['SLPM_611.62'],'SLPM-61162',lambda text:spanish.get(text,text)),
                         'La ISO es la demo japonesa. Discos admitidos.')


@unittest.skipUnless(PAL.exists() and BT3.exists(),'European and USA BT3 ISO files not installed')
class EuropeanDiscTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pal=scan(PAL,PROFILES);cls.usa=scan(BT3,PROFILES)

    def test_european_disc_is_certified_with_every_fighter_costume_and_map(self):
        p=self.pal;identity=p['identity']
        self.assertEqual((identity['adapter'],identity['serial'],identity['pcsx2_crc']),('bt3-pal','SLES_549.45','A422BB13'))
        self.assertTrue(identity['runtime_adapter_verified']);self.assertTrue(p['capabilities']['runtime_hooks'])
        self.assertEqual(identity['runtime_match']['variant'],'BT3 Europe SLES-54945 (En/Fr/De/Es/It)')
        self.assertIsNone(identity['runtime_match']['native_language'])
        for profile in (self.pal,self.usa):self.assertNotIn('refusal',profile['identity']['runtime_match'])
        self.assertEqual({k:p['summary'][k] for k in ('base_fighters_valid','costume_variants_valid','stage_variants_valid',
                                                       'normal_maps_eligible','split_maps_eligible','issues')},
                         dict(base_fighters_valid=161,costume_variants_valid=698,stage_variants_valid=70,
                              normal_maps_eligible=35,split_maps_eligible=35,issues=0))
        self.assertEqual(p['issues'],[])
        self.assertEqual({v:row['entries'] for v,row in p['volumes'].items()},{'0':2,'1':3645,'2':65201})
        self.assertEqual(p['volumes']['1']['member'],'/DATA/PZS3EU1.AFS;1')
        self.assertEqual((p['layout']['stage_base'],p['layout']['split_stage_base'],p['layout']['stage_effect_base']),(373,412,338))
        self.assertEqual(p['layout']['costumes'],self.usa['layout']['costumes'])

    def test_english_labels_differ_from_usa_in_two_names_and_files_use_the_european_ids(self):
        usa={r['character_id']:(r['name'],r['form']) for r in self.usa['characters']}
        pal={r['character_id']:(r['name'],r['form']) for r in self.pal['characters']}
        self.assertEqual(set(usa),set(pal))
        self.assertEqual({i:pal[i] for i in pal if pal[i]!=usa[i]},{37:('Vegeta (second form)','Majin'),59:('Kibitoshin','')})
        self.assertEqual(self.pal['characters'][0]['costumes'][0]['files'],[1671,1679,1680])
        self.assertEqual(self.usa['characters'][0]['costumes'][0]['files'],[1424,1432,1433])

    def test_volume_zero_numbers_global_ids_and_gameplay_files_are_identical(self):
        with Disc(PAL) as pal,Disc(BT3) as usa:
            self.assertEqual((pal.region,usa.region),('EU','US'))
            self.assertEqual(pal.locate(2),(pal.volume_paths[1],*pal.tables[1][0]))
            self.assertEqual(usa.locate(1),(usa.volume_paths[1],*usa.tables[1][0]))
            with self.assertRaisesRegex(FormatError,'Unmapped file ID 1$'):pal.locate(1)
            # Character table, stage, split stage, stage effects, animation, combat and short voices move
            # +1 (IDs 1-4), +4 (8-510) and +247 (659 on) with identical bytes.
            for usa_id,pal_id in ((4,5),(369,373),(408,412),(334,338),(1432,1679),(1433,1680),(3034,3281),(3195,3442)):
                with self.subTest(usa=usa_id):self.assertEqual(pal.read(pal_id),usa.read(usa_id))

    def test_each_disc_matches_its_own_serial_and_stage_loader_addresses(self):
        with Disc(PAL) as disc:
            adapter,verified=identify(disc)
            self.assertEqual((adapter.name,verified),('bt3-pal',True))
            verify_stage_mapping(disc,adapter)
            with self.assertRaisesRegex(FormatError,'Stage loader mapping changed'):verify_stage_mapping(disc,BY_NAME['bt3-usa'])
        with Disc(BT3) as disc:
            adapter,verified=identify(disc)
            self.assertEqual((adapter.name,verified),('bt3-usa',True))
            with self.assertRaisesRegex(FormatError,'Stage loader mapping changed'):verify_stage_mapping(disc,BY_NAME['bt3-pal'])

    def refusal(self,path,change):
        with Disc(path) as disc:
            change(disc);adapter,evidence=runtime_match(disc)
        self.assertFalse(evidence['verified'])
        return adapter,evidence['refusal']

    def test_changed_discs_are_refused_naming_the_disc(self):
        def flip(disc):changed=bytearray(disc.elf);changed[4096]^=1;disc.elf=bytes(changed)
        def addon(disc):disc.member_hashes['/BIN/DBZP.BIN;1']='0'*64
        def region(disc):disc.region='US'
        def japan(disc):disc.serial='SLPS_258.15'
        def european_serial(disc):disc.serial='SLES_549.45'
        for path,change,template,named,adapter in (
                (PAL,flip,known_discs.MODIFIED_EXECUTABLE,'Europe (SLES-54945)','bt3-pal'),
                (PAL,addon,known_discs.MODIFIED_ADDON,'Europe (SLES-54945)','bt3-pal'),
                (PAL,region,known_discs.MODIFIED_LAYOUT,'Europe (SLES-54945)','bt3-pal'),
                (PAL,japan,known_discs.MODIFIED_LAYOUT,'Sparking! Meteor','bt3-jpn'),
                (BT3,flip,known_discs.MODIFIED_EXECUTABLE,'USA (SLUS-21678)','bt3-usa'),
                (BT3,european_serial,known_discs.MODIFIED_LAYOUT,'Europe (SLES-54945)','bt3-pal')):
            with self.subTest(path=path.name,change=change.__name__):
                found,refusal=self.refusal(path,change)
                self.assertEqual((found.name,refusal['template']),(adapter,template))
                self.assertIn(named,refusal['text']);self.assertIn('SLUS-21678',refusal['text']);self.assertIn('SLES-54945',refusal['text'])

    def test_install_profile_writes_the_european_executable_and_english_names(self):
        from .install_profile import prepare
        with tempfile.TemporaryDirectory() as tmp:
            game=Path(tmp)/'game';(game/'tools').mkdir(parents=True)
            shutil.copy2(ROOT/'bt3-multifighter/tools/extract_loading_assets.py',game/'tools')
            record=prepare(PAL,game,PROFILES,progress=lambda _:None)
            self.assertEqual((record['adapter'],record['serial'],record['pcsx2_crc']),('bt3-pal','SLES_549.45','A422BB13'))
            self.assertEqual(record['runtime_variant'],'BT3 Europe SLES-54945 (En/Fr/De/Es/It)')
            with Disc(PAL) as disc:elf,text=disc.elf,disc.read(455)
            self.assertEqual((game/'analysis/SLES_549.45').read_bytes(),elf)
            self.assertEqual(sorted(p.name for p in (game/'analysis').iterdir()),['SLES_549.45'])
            characters=json.loads((game/'assets/characters.json').read_text(encoding='utf-8'))
            self.assertEqual(characters['source_sha256'],hashlib.sha256(text).hexdigest())
            rows={row['character_id']:row for row in characters['characters']}
            self.assertEqual(len(rows),161)
            self.assertEqual((rows[0]['base_name'],rows[59]['name']),('Goku (Early)','Kibitoshin'))
            self.assertTrue((game/'assets'/rows[0]['portrait']).is_file())
            self.assertEqual(json.loads((game/'game-profile.json').read_text(encoding='utf-8'))['adapter'],'bt3-pal')

    def test_cached_unrecognized_profiles_without_a_named_refusal_are_rescanned(self):
        from .scanner import stat_key
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);fake=folder/'disc.iso';fake.write_bytes(b'local disc fixture')
            def cache(profile):
                profile=copy.deepcopy(profile);profile['source']=stat_key(fake)
                target=folder/(profile['identity']['iso_sha256']+'.json');atomic_json(target,profile)
                atomic_json(cache_index(fake,folder),dict(source=profile['source'],sha256=profile['identity']['iso_sha256'],
                                                         profile_sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
                return cached_profile(fake,folder)
            self.assertIsNotNone(cache(self.pal))  # verified: reused
            # What the scanner before the European adapter stored for this disc: unverified, no named refusal.
            old=copy.deepcopy(self.pal);identity=old['identity']
            identity.update(adapter=None,runtime_adapter_verified=False)
            identity['runtime_match']=dict(verified=False,variant=None,reason='No adapter for this resource layout/region')
            self.assertIsNone(cache(old))
            with Disc(PAL) as disc:
                identity['runtime_match']=known_discs.explain(disc,dict(identity['runtime_match']))
            self.assertIsNotNone(cache(old))  # a refusal made by this scanner is reused


@unittest.skipUnless(JPN.exists() and BT3.exists(),'Japanese and USA BT3 ISO files not installed')
class JapaneseDiscTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jp=scan(JPN,PROFILES);cls.usa=scan(BT3,PROFILES)

    def test_japanese_disc_is_certified_with_every_fighter_costume_and_map(self):
        p=self.jp;identity=p['identity']
        self.assertEqual((identity['adapter'],identity['serial'],identity['pcsx2_crc']),('bt3-jpn','SLPS_258.15','F28D21F1'))
        self.assertTrue(identity['runtime_adapter_verified']);self.assertTrue(p['capabilities']['runtime_hooks'])
        self.assertEqual(identity['runtime_match']['variant'],'BT3 Japan SLPS-25815 (Sparking! Meteor)')
        self.assertIsNone(identity['runtime_match']['native_language'])
        self.assertNotIn('refusal',identity['runtime_match'])
        self.assertEqual({k:p['summary'][k] for k in ('base_fighters_valid','costume_variants_valid','stage_variants_valid',
                                                       'normal_maps_eligible','split_maps_eligible','issues')},
                         dict(base_fighters_valid=161,costume_variants_valid=698,stage_variants_valid=70,
                              normal_maps_eligible=35,split_maps_eligible=35,issues=0))
        self.assertEqual({v:row['entries'] for v,row in p['volumes'].items()},{'0':1,'1':3317,'2':63773})
        self.assertEqual(p['volumes']['1']['member'],'/DATA/PZS3JP1.AFS;1')
        self.assertEqual((p['layout']['stage_base'],p['layout']['split_stage_base'],p['layout']['stage_effect_base']),(368,407,333))
        self.assertEqual(p['layout']['costumes'],self.usa['layout']['costumes'])
        self.assertIs(known_discs.stages_modified(p),False)

    def test_names_are_japanese_in_the_report_and_files_use_the_japanese_ids(self):
        names={r['character_id']:(r['name'],r['form']) for r in self.jp['characters']}
        self.assertEqual(names[0],('\u5b6b\u609f\u7a7a\uff08\u524d\u671f\uff09',''))
        self.assertEqual(self.jp['characters'][0]['costumes'][0]['files'],[1342,1350,1351])
        self.assertEqual(self.usa['characters'][0]['costumes'][0]['files'],[1424,1432,1433])
        self.assertEqual([r['fusion_recipes'] for r in self.jp['characters']],[r['fusion_recipes'] for r in self.usa['characters']])

    def test_volume_zero_numbers_global_ids_and_gameplay_files_are_identical(self):
        with Disc(JPN) as jp,Disc(BT3) as usa:
            self.assertEqual((jp.region,usa.region),('JP','US'))
            self.assertEqual(jp.locate(1),(jp.volume_paths[1],*jp.tables[1][0]))
            # Character table, stage effects, combat and short voices: identical bytes at -0 / -1 / -82.
            for usa_id,jp_id in ((4,4),(334,333),(1433,1351),(3034,2952),(3195,3113)):
                with self.subTest(usa=usa_id):self.assertEqual(jp.read(jp_id),usa.read(usa_id))

    def test_the_disc_matches_its_own_serial_and_stage_loader_addresses(self):
        with Disc(JPN) as disc:
            adapter,verified=identify(disc)
            self.assertEqual((adapter.name,verified),('bt3-jpn',True))
            verify_stage_mapping(disc,adapter)
            with self.assertRaisesRegex(FormatError,'Stage loader mapping changed'):verify_stage_mapping(disc,BY_NAME['bt3-usa'])
        def flip(disc):changed=bytearray(disc.elf);changed[4096]^=1;disc.elf=bytes(changed)
        def addon(disc):disc.member_hashes['/BIN/DBZP.BIN;1']='0'*64
        for change,template in ((flip,known_discs.MODIFIED_EXECUTABLE),(addon,known_discs.MODIFIED_ADDON)):
            with self.subTest(change=change.__name__),Disc(JPN) as disc:
                change(disc);adapter,evidence=runtime_match(disc)
                self.assertFalse(evidence['verified'])
                self.assertEqual((adapter.name,evidence['refusal']['template']),('bt3-jpn',template))
                self.assertIn('Sparking! Meteor',evidence['refusal']['text'])

    def test_install_profile_writes_the_japanese_executable_english_names_and_disc_portraits(self):
        from .install_profile import prepare
        with tempfile.TemporaryDirectory() as tmp:
            game=Path(tmp)/'game';(game/'tools').mkdir(parents=True)
            for name in ('extract_loading_assets.py','bt3_english_names.json'):
                shutil.copy2(ROOT/'bt3-multifighter/tools'/name,game/'tools')
            record=prepare(JPN,game,PROFILES,progress=lambda _:None)
            self.assertEqual((record['adapter'],record['serial'],record['pcsx2_crc']),('bt3-jpn','SLPS_258.15','F28D21F1'))
            with Disc(JPN) as disc:elf,text=disc.elf,disc.read(450)
            self.assertEqual((game/'analysis/SLPS_258.15').read_bytes(),elf)
            characters=json.loads((game/'assets/characters.json').read_text(encoding='utf-8'))
            self.assertEqual(characters['source_sha256'],hashlib.sha256(text).hexdigest())
            rows={row['character_id']:row for row in characters['characters']}
            self.assertEqual(len(rows),161)
            self.assertEqual((rows[0]['base_name'],rows[55]['name'],rows[133]['form']),('Goku (Early)','Hercule','Legendary Super Saiyan'))
            self.assertTrue((game/'assets'/rows[0]['portrait']).is_file())
            # Without the English names the Japanese disc is refused rather than given blank names.
            (game/'tools/bt3_english_names.json').unlink();(game/'game-profile.json').unlink()
            with self.assertRaisesRegex(FormatError,'English fighter names'):prepare(JPN,game,PROFILES,progress=lambda _:None)

    def test_a_refusal_cached_before_the_japanese_adapter_is_rescanned(self):
        from .scanner import stat_key
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);fake=folder/'disc.iso';fake.write_bytes(b'local disc fixture')
            def cache(profile):
                profile=copy.deepcopy(profile);profile['source']=stat_key(fake)
                target=folder/(profile['identity']['iso_sha256']+'.json');atomic_json(target,profile)
                atomic_json(cache_index(fake,folder),dict(source=profile['source'],sha256=profile['identity']['iso_sha256'],
                                                         profile_sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
                return cached_profile(fake,folder)
            self.assertIsNotNone(cache(self.jp))
            # What beta.35 stored: an unknown volume layout and a named refusal of SLPS-25815.
            old=copy.deepcopy(self.jp);identity=old['identity']
            identity.update(adapter=None,runtime_adapter_verified=False,layout='unknown')
            identity['runtime_match']=dict(verified=False,variant=None,reason='No adapter',
                                           refusal=dict(template=known_discs.KNOWN_RELEASE))
            self.assertIsNone(cache(old))
            # A refusal this scanner makes for the reviewed serial (a repacked Japanese disc whose volumes it
            # cannot read) is reused, not rescanned on every use.
            identity['runtime_match']['refusal']=dict(template=known_discs.MODIFIED_LAYOUT)
            self.assertIsNotNone(cache(old))


if __name__=='__main__':unittest.main()
