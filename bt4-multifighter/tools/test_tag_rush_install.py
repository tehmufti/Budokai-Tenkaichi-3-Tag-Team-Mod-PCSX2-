"""Transactional local tag-rush composition, without a disc or emulator."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import copy
import json
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import tag_rush_install as install
import tag_team_rush as tag
import tag_rush_scene as scene
import tag_rush_safety as safety
import tag_rush_hud as captions
import tag_rush_bootstrap as bootstrap
import cinematic_contact_guard as contact
import inactive_actor_guard as inactive
import viewport_hud as hud
import quad_viewports as quad
import lockon_threat as threat

MANAGER=0x1900000
PREVIOUS=0x07254000
OPTIONS={'tag_team_rush_enabled':True}
from tag_rush_choreography import VARIANTS


def w(ram,address,value):struct.pack_into('<I',ram,address,value)
def u(ram,address):return struct.unpack_from('<I',ram,address)[0]
def put(ram,address,data):ram[address:address+len(data)]=data


def assets():
    return dict(blocks=[(install.assets.BASE,bytes(0x100*len(VARIANTS)))],
                variants={n:dict(address=install.assets.BASE+i*0x100,count=4) for i,n in enumerate(VARIANTS)},
                bytes_used=0x100*len(VARIANTS),limitations=[])



def profile_assets():
    import hashlib
    p=install.pose_profiles;data=struct.pack('<4I',p.MAGIC,161,16+161*8,0)+bytes(161*8)
    return dict(blocks=[(p.DATA,data)],table_address=p.DATA,bytes_used=len(data),sha256=hashlib.sha256(data).hexdigest())

def fixture(*,four=False):
    ram=bytearray(0x8000000)
    for address,native,_ in install.cpu_tags.hooks():put(ram,address,native)
    address,native,_=install.blue.aura_size_hook();put(ram,address,native)
    put(ram,install.recovery.HOOK,install.recovery.NATIVE_HOOK)
    put(ram,install.audio_queue.HOOK,install.audio_queue.NATIVE_HOOK)
    put(ram,install.beam_audio.HOOK,install.beam_audio.NATIVE_HOOK)
    put(ram,install.launch.CONTACT_HOOK,install._jump(contact.SPECS[2][1]))
    put(ram,install.launch.RETARGET_HOOK,install.launch.RETARGET_NATIVE)
    put(ram,install.launch.COMMIT_HOOK,install.launch.COMMIT_NATIVE)
    w(ram,install.core.ACTORS,MANAGER);w(ram,MANAGER,2)
    put(ram,install.core.MODE,struct.pack('<4I',1,4,MANAGER,4))
    put(ram,install.participation.CONTROL,struct.pack('<5I',5,MANAGER,4,15,0))
    put(ram,install.participation.FRAME,install.participation.frame_code(PREVIOUS))
    for index in range(4):
        actor=0x2200000+index*0x2000;model=0x2300000+index*0x2000
        w(ram,install.core.POINTERS+4*index,actor);w(ram,actor,index);w(ram,actor+12,index)
        w(ram,install.core.MODELS+4*index,model);w(ram,model+16,index);w(ram,model+12,index)
    put(ram,install.feed.DAMAGE,install.feed.damage_code())
    put(ram,inactive.ENTRY,inactive.code())
    put(ram,contact.PROTECTED,contact.protected_code())
    w(ram,hud.CONTROL,hud.MAGIC);w(ram,hud.CONTROL+16,PREVIOUS)
    if four:w(ram,quad.CONTROL,quad.MAGIC);put(ram,quad.DRAW,quad.draw())
    else:put(ram,hud.CODE,hud.wrapper(PREVIOUS,deferred=True))
    return ram


def admitted(iso,roster):return [dict(row,supported=True) for row in roster]


def complete_plan():
    plan=scene.installation(assets());plan['usable']=True;plan['limitations']=[]
    return plan


def apply(ram,plan):
    # Verify every expected byte against the original capture first.
    for block in plan['blocks']:
        address=block['address'];expected=bytes.fromhex(block['expected_hex'])
        assert ram[address:address+len(expected)]==expected
    for block in plan['blocks']:put(ram,block['address'],bytes.fromhex(block['data_hex']))


def ready(ram):
    """Stand in for completed guest initialization, including both receipts."""
    fx=install.effects;pool=0x2400000
    w(ram,bootstrap.STATE+bootstrap.S['phase'],bootstrap.READY)
    w(ram,bootstrap.STATE+bootstrap.S['pool'],pool)
    w(ram,tag.CONTROL+tag.C['ready'],1)
    w(ram,install.GP+install.GPO(fx.NATIVE_POOL_OFFSET),pool)
    put(ram,fx.CONTROL,struct.pack('<8I',fx.MAGIC,MANAGER,4,1,pool,0,0,2))
    for index in range(2):
        row=fx.ROWS+index*fx.STRIDE
        w(ram,row+fx.R['prepared'],fx.PREPARED)
        w(ram,row+fx.HEADER+36,row+fx.META);w(ram,row+fx.DESC+796,row+fx.HEADER)


def special_assets():
    """Small real native beam pack; synthetic poses keep installer tests narrow."""
    from test_tag_rush_effects import BEAM
    iso=install.selected_iso()
    if not Path(iso).is_file():raise unittest.SkipTest('Local game disc is unavailable')
    pack=assets();sbc=install.special_beam.build_assets(iso);ordinary=install.assets.read_native_beam_asset(iso)
    beam=dict(BEAM,resource_size=len(ordinary['resource']),metadata_size=len(ordinary['metadata']),
        **{key:ordinary[key] for key in ('resource_sha256','mutable_ranges')})
    info={key:value for key,value in sbc.items() if key!='blocks'}
    beam['special_beam']=info;pack['beam_asset']=beam;pack['special_beam_asset']=info
    pack['blocks'] += [(beam['resource_address'],ordinary['resource']),
                      (beam['metadata_address'],ordinary['metadata']),*sbc['blocks']]
    return pack


def special_ready(ram,pack):
    from test_tag_rush_special_beam import fixture as beam_fixture,ready as beam_ready,select
    c,_=beam_fixture();beam_ready(c);select(c,0,22);select(c,1,0)
    ready(ram);fx=install.effects;sbc=install.special_beam
    for lo,hi in ((fx.ROWS,fx.ROWS+2*fx.STRIDE),(sbc.STATE,sbc.STATE_END),
                  (sbc.BANKS,sbc.BANKS+2*sbc.BANK_STRIDE),(sbc.ARENAS,sbc.ARENAS+2*sbc.ARENA_SIZE)):
        put(ram,lo,c.read(lo,hi-lo))


class TagInstallTests(unittest.TestCase):
    def setUp(self):
        self.names={i:dict(name=name,base_name=name) for i,name in enumerate(('Goku','Vegeta','Hercule','Videl'))}
        self.patches=[patch.object(install,'cached_assets',return_value=(assets(),'test-iso')),
                      patch.object(install,'_costume_count',return_value=4),
                      patch.object(install.pose_profiles,'build_assets',return_value=profile_assets()),
                      patch.object(install.assets,'character_admission',side_effect=admitted),
                      patch('character_names.character_table',return_value=self.names)]
        for item in self.patches:item.start();self.addCleanup(item.stop)

    def build(self,ram,**kwargs):
        return install.build_memory(ram,OPTIONS,source='test capture',iso='unused.iso',enable_scene=True,**kwargs)

    def test_incomplete_director_never_publishes_hooks_or_ready(self):
        ram=fixture();before=bytes(ram)
        plan=self.build(ram)
        self.assertFalse(plan['usable']);self.assertEqual(plan['blocks'],[])
        self.assertIn('effects',' '.join(plan['limitations']));self.assertEqual(ram,before)

    def test_special_beam_first_install_requires_the_whole_reservation_unowned(self):
        sbc=install.special_beam;pack=special_assets();director=complete_plan()
        director['blocks'].extend(sbc.pieces(pack['special_beam_asset']))
        with patch.object(install,'cached_assets',return_value=(pack,'sbc-iso')),\
             patch.object(scene,'installation',return_value=director):
            for address in (sbc.BASE,sbc.STATE,sbc.BANKS,sbc.ARENAS,sbc.RESOURCE,sbc.END-1):
                ram=fixture();ram[address]=1;before=bytes(ram)
                with self.assertRaisesRegex(ValueError,'Special Beam Cannon reservation is occupied'):
                    self.build(ram)
                self.assertEqual(ram,before)

    def test_special_beam_armed_reinstall_checks_banks_live_recipe_and_source_without_reset(self):
        sbc=install.special_beam;fx=install.effects;pack=special_assets();director=complete_plan()
        director['blocks'].extend(sbc.pieces(pack['special_beam_asset']))
        with patch.object(install,'cached_assets',return_value=(pack,'sbc-iso')),\
             patch.object(scene,'installation',return_value=director):
            ram=fixture();apply(ram,self.build(ram));special_ready(ram,pack)
            # Native texture relocation, pool/charge flags and parsed upload
            # masks are runtime state, so a legitimate running emitter stays.
            relocation=pack['special_beam_asset']['mutable_ranges'][0][0]
            w(ram,sbc.RESOURCE+relocation,0x12345678)
            w(ram,fx.ROWS+fx.R['charged'],1);w(ram,fx.ROWS+fx.R['ticks'],30)
            w(ram,sbc.ARENAS+516,0x1357)
            before=bytes(ram);self.assertEqual(self.build(ram)['blocks'],[]);self.assertEqual(ram,before)
            cases=((sbc.STATE,'Special Beam Cannon'),(sbc.STATE+sbc.S['pool'],'Special Beam Cannon'),
                (sbc.BANKS+sbc.RECEIPT,'Special Beam Cannon'),
                (sbc.BANKS+sbc.SPECIAL_DESC+768,'Special Beam Cannon'),
                (sbc.BANKS+sbc.STANDARD_RESOURCE,'Special Beam Cannon'),
                (fx.ROWS+fx.HEADER+28,'Special Beam Cannon'),
                (fx.ROWS+fx.R['flavor'],'Special Beam Cannon'),
                (fx.ROWS+fx.DESC+16,'Special Beam Cannon'),(fx.ROWS+fx.META+60,'Special Beam Cannon'),
                (sbc.RESOURCE+256+12,'program changed'),(sbc.RESOURCE+sbc.RESOURCE_SIZE-7,'program changed'),
                (sbc.RESOURCE+sbc.RESOURCE_SIZE+12,'program changed'),
                (sbc.INIT+32,'program changed'),(sbc.SELECT+32,'program changed'))
            for address,reason in cases:
                original=ram[address];ram[address]^=1;before=bytes(ram)
                with self.subTest(address=hex(address)),self.assertRaisesRegex(ValueError,reason):self.build(ram)
                self.assertEqual(ram,before);ram[address]=original

    def test_user_authored_hold_table_is_immutable_on_reinstall(self):
        import fusion_audio_restore
        hp=install.authored_hold;bank=install.beam_audio.isolate_bank(fusion_audio_restore.bank_file(0,False))
        table=hp.data()
        self.assertEqual(len(table),hp.HEADER+12*hp.STRIDE)
        self.assertLessEqual(hp.DATA+len(table),hp.END)
        self.assertEqual(struct.unpack_from('<4I',table,48),
                         (len(hp.JOINTS),4,3*hp.STRIDE,hp.ACQUISITION_FRAMES))
        with patch.object(scene,'installation',return_value=complete_plan()),\
             patch.object(install,'review_playtest_assets'),\
             patch.object(install.beam_audio,'disc_bank',return_value=bank):
            ram=fixture();apply(ram,self.build(ram,reviewed_assets=True))
            self.assertEqual(ram[hp.DATA:hp.DATA+len(table)],table)
            self.assertEqual(install._json(install._read_meta(ram)['authored_hold']),install._json(hp.receipt()))
            self.assertFalse(self.build(ram,reviewed_assets=True)['blocks'])
            for off in (0,4,8,16,52,60,hp.HEADER+hp.VICTIM_ROOT,hp.HEADER+hp.ROTATIONS,
                        hp.HEADER+3*hp.STRIDE+hp.ROTATIONS,
                        hp.HEADER+6*hp.STRIDE+hp.ROTATIONS,
                        hp.HEADER+9*hp.STRIDE+hp.ROTATIONS,len(table)-1):
                ram[hp.DATA+off]^=1
                with self.assertRaisesRegex(ValueError,'program changed'):self.build(ram,reviewed_assets=True)
                ram[hp.DATA+off]^=1
            receipt=install._read_meta(ram);receipt['authored_hold']['payload_sha256']='00'*32
            put(ram,install.META,install._meta_bytes(receipt))
            with self.assertRaisesRegex(ValueError,'authored hold endpoints changed'):
                self.build(ram,reviewed_assets=True)

    def test_missing_or_changed_authored_hold_endpoints_publish_no_patch(self):
        hp=install.authored_hold
        for mode in ('missing','changed','changed acquisition','duplicated'):
            director=complete_plan();table=hp.data()
            director['blocks']=[(p,b) for p,b in director['blocks'] if p!=hp.DATA]
            if mode.startswith('changed'):
                offset=hp.HEADER+hp.ROTATIONS+(6*hp.STRIDE if mode=='changed acquisition'else 0)
                changed=bytearray(table);changed[offset]^=1
                director['blocks'].append((hp.DATA,bytes(changed)))
            elif mode=='duplicated':director['blocks'].extend(((hp.DATA,table),(hp.DATA,table)))
            ram=fixture();before=bytes(ram)
            with self.subTest(mode=mode),patch.object(scene,'installation',return_value=director):
                with self.assertRaisesRegex(ValueError,'authored hold endpoints changed'):self.build(ram)
            self.assertEqual(ram,before)

    def test_costume_admission_uses_each_selected_members_starting_clothes(self):
        ram=fixture();actor=u(ram,install.core.POINTERS+8)
        w(ram,actor+0x994,3);row=actor+0x9A4+164*3
        w(ram,row+4,2);w(ram,row+0x60,1)
        roster=install._roster(ram,4)
        self.assertEqual(roster[2],dict(index=2,character=2,costume=2,damaged=True))
        self.assertFalse(roster[0]['damaged']);self.assertFalse(roster[3]['damaged'])
        w(ram,row+0x60,2)
        with self.assertRaisesRegex(ValueError,'starting clothes'):install._roster(ram,4)

    def test_explicit_offline_optin_and_online_exclusion(self):
        ram=fixture()
        for kwargs in (dict(enable_scene=False),dict(online=True),dict(iso=None)):
            args=dict(iso='unused.iso',enable_scene=True);args.update(kwargs)
            result=install.build_memory(ram,OPTIONS,**args)
            self.assertFalse(result['usable']);self.assertFalse(result['blocks'])
        w(ram,install.NETPLAY_CONTROL,install.NETPLAY_MAGIC);w(ram,install.NETPLAY_CONTROL+4,1)
        self.assertFalse(self.build(ram)['usable'])
        self.assertFalse(install.build_memory(ram,{'tag_team_rush_enabled':False})['usable'])
        w(ram,install.NETPLAY_CONTROL,0);w(ram,install.modes.CONTROL+12,install.modes.FFA)
        self.assertFalse(self.build(ram)['usable'])

    def test_duplicate_forms_cannot_borrow_another_costumes_admission(self):
        rows=[dict(character=0,costume=0,damaged=False,supported=True),
              dict(character=0,costume=1,damaged=False,supported=False),
              dict(character=1,costume=0,damaged=False,supported=True)]
        for ordered in (rows,rows[::-1]):
            (_,data),words=install.admission_block(assets(),ordered)
            self.assertEqual(data,bytes((0,3,0,0)))
            self.assertEqual(words[0x3A4],4)
        rows[1]['supported']=True
        (_,data),_=install.admission_block(assets(),rows)
        self.assertEqual(data,bytes((3,3,0,0)))

    def test_recovery_hook_conflicts_refuse_before_any_patch_is_returned(self):
        ram=fixture();ram[install.recovery.HOOK]^=1;before=bytes(ram)
        with patch.object(scene,'installation',return_value=complete_plan()):
            with self.assertRaisesRegex(ValueError,'recovery status hook changed'):self.build(ram)
        self.assertEqual(ram,before)

    def test_cpu_hooks_and_separate_reservation_are_exact_and_preserved(self):
        for address,native,_ in install.cpu_tags.hooks():
            ram=fixture();ram[address]^=1;before=bytes(ram)
            with patch.object(scene,'installation',return_value=complete_plan()):
                with self.assertRaisesRegex(ValueError,'CPU decision hook changed'):self.build(ram)
            self.assertEqual(ram,before)
        ram=fixture();ram[install.cpu_tags.BASE]=1
        with patch.object(scene,'installation',return_value=complete_plan()):
            with self.assertRaisesRegex(ValueError,'CPU decision reservation is occupied'):self.build(ram)
        ram=fixture()
        with patch.object(scene,'installation',return_value=complete_plan()):
            apply(ram,self.build(ram));w(ram,tag.METERS+tag.T['cpu_held'],1)
            self.assertEqual(self.build(ram)['blocks'],[])
            self.assertEqual(u(ram,tag.METERS+tag.T['cpu_held']),1)
        for address,_,replacement in install.cpu_tags.hooks():
            self.assertEqual(ram[address:address+len(replacement)],replacement)

    def test_sound_dispatch_hook_is_exact_and_kept_on_repeated_install(self):
        ram=fixture();ram[install.audio_queue.HOOK]^=1;before=bytes(ram)
        with patch.object(scene,'installation',return_value=complete_plan()):
            with self.assertRaisesRegex(ValueError,'sound dispatch hook changed'):self.build(ram)
        self.assertEqual(ram,before)
        ram=fixture()
        with patch.object(scene,'installation',return_value=complete_plan()):
            apply(ram,self.build(ram))
            self.assertEqual(ram[install.audio_queue.HOOK:install.audio_queue.HOOK+4],install.audio_queue.INSTALLED_HOOK)
            self.assertFalse(self.build(ram)['blocks'])
            ram[install.audio_queue.HOOK]^=1
            with self.assertRaisesRegex(ValueError,'sound dispatch hook changed'):self.build(ram)

    def test_native_rush_hooks_preserve_exact_contact_chain_and_reinstall(self):
        native_contact=install._jump(contact.SPECS[2][1])
        hooks=((install.launch.CONTACT_HOOK,install.launch.CONTACT_PATCH,'contact hook'),
               (install.launch.RETARGET_HOOK,install.launch.RETARGET_PATCH,'retarget hook'),
               (install.launch.COMMIT_HOOK,install.launch.COMMIT_PATCH,'action-selection hook'))
        for address,data,reason in hooks:
            for offset in range(len(data)):
                with self.subTest(address=hex(address),offset=offset):
                    ram=fixture();ram[address+offset]^=1;before=bytes(ram)
                    with patch.object(scene,'installation',return_value=complete_plan()):
                        with self.assertRaisesRegex(ValueError,reason):self.build(ram)
                    self.assertEqual(ram,before)
        ram=fixture()
        with patch.object(scene,'installation',return_value=complete_plan()):
            apply(ram,self.build(ram))
            for address,data,_ in hooks:self.assertEqual(ram[address:address+len(data)],data)
            self.assertEqual(ram[install.launch.CONTACT_OLD:install.launch.CONTACT_OLD+8],native_contact)
            self.assertEqual(install._read_meta(ram)['native_contact'],native_contact.hex())
            self.assertFalse(self.build(ram)['blocks'])
            for address,data,reason in hooks:
                ram[address]^=1
                with self.assertRaisesRegex(ValueError,reason):self.build(ram)
                ram[address]^=1
            ram[install.launch.CONTACT_OLD]^=1
            with self.assertRaisesRegex(ValueError,'program changed'):self.build(ram)
            ram[install.launch.CONTACT_OLD]^=1
            record=install._read_meta(ram);record['native_contact']='00'*8
            put(ram,install.META,install._meta_bytes(record))
            with self.assertRaisesRegex(ValueError,'native contact predecessor'):self.build(ram)

    def test_private_beam_bank_is_local_opt_in_with_exact_exit_hook(self):
        import fusion_audio_restore
        bank=install.beam_audio.isolate_bank(fusion_audio_restore.bank_file(0,False));ram=fixture()
        with patch.object(scene,'installation',return_value=complete_plan()),\
             patch.object(install,'review_playtest_assets'),\
             patch.object(install.beam_audio,'disc_bank',return_value=bank):
            plan=self.build(ram,local_playtest=True);apply(ram,plan)
            self.assertEqual(u(ram,tag.CONTROL+install.pose_profiles.TABLE_OFFSET),install.pose_profiles.DATA)
            self.assertEqual(ram[install.pose_profiles.DATA:install.pose_profiles.DATA+16],profile_assets()['blocks'][0][1][:16])
            self.assertEqual(ram[install.beam_audio.HOOK:install.beam_audio.HOOK+4],install.beam_audio.INSTALLED_HOOK)
            self.assertEqual(ram[install.beam_audio.DATA:install.beam_audio.DATA+len(bank['data'])],bank['data'])
            init=bootstrap.code(beam_audio=True)
            self.assertEqual(ram[bootstrap.CODE:bootstrap.CODE+len(init)],init)
            self.assertFalse(self.build(ram,local_playtest=True)['blocks'])
            ram[install.pose_profiles.DATA+16]^=1
            with self.assertRaisesRegex(ValueError,'program changed'):self.build(ram,local_playtest=True)
            ram[install.pose_profiles.DATA+16]^=1
            ram[install.beam_audio.HOOK]^=1
            with self.assertRaisesRegex(ValueError,'sound cleanup hook changed'):self.build(ram,local_playtest=True)

    def test_new_pose_and_special_banks_refuse_other_owners_before_any_write(self):
        for address,reason in ((install.pose_profiles.BASE,'beam pose reservation'),
                               (install.SPECIAL_BASE,'special pair reservation'),
                               (install.FULL_NELSON_BASE,'full-nelson pose reservation'),
                               (install.authored_hold.DATA,'full-nelson pose reservation'),
                               (install.authored_hold.END-1,'full-nelson pose reservation'),
                               (install.special_beam.BASE,'Special Beam Cannon reservation')):
            ram=fixture();ram[address]=1;before=bytes(ram)
            with patch.object(scene,'installation',return_value=complete_plan()):
                with self.assertRaisesRegex(ValueError,reason):self.build(ram)
            self.assertEqual(ram,before)

    def test_full_nelson_helper_is_bounded_and_immutable_on_reinstall(self):
        plan=complete_plan()
        plan['blocks']=[(p,b) for p,b in plan['blocks']
                        if not install.FULL_NELSON_BASE<=p<install.FULL_NELSON_END]
        plan['blocks'].extend(install.authored_hold.pieces())
        address=install.FULL_NELSON_BASE
        plan['blocks'].append((address,bytes.fromhex('0800e00300000000')))
        ram=fixture()
        with patch.object(scene,'installation',return_value=plan):
            apply(ram,self.build(ram))
            self.assertEqual(self.build(ram)['blocks'],[])
            ram[address]^=1
            with self.assertRaisesRegex(ValueError,'program changed'):self.build(ram)
        plan['blocks'][-1]=(install.FULL_NELSON_END-4,bytes(8))
        with patch.object(scene,'installation',return_value=plan):
            with self.assertRaisesRegex(ValueError,'escaped its reservation'):self.build(fixture())

    def test_complete_plan_is_transactional_and_waits_for_guest_initialization(self):
        ram=fixture();before=bytes(ram);site,previous=install.frame_predecessor(ram)
        with patch.object(scene,'installation',return_value=complete_plan()):plan=self.build(ram,training=True)
        self.assertTrue(plan['usable']);self.assertEqual(ram,before)
        self.assertFalse(any(b['address']==tag.CONTROL+tag.C['ready'] for b in plan['blocks']))
        apply(ram,plan)
        self.assertEqual(u(ram,tag.CONTROL+tag.C['ready']),0)
        self.assertEqual(u(ram,bootstrap.STATE+bootstrap.S['phase']),bootstrap.WAITING)
        self.assertEqual(u(ram,site),int.from_bytes(install._jal(tag.FRAME),'little'))
        self.assertEqual(ram[contact.PROTECTED:contact.PROTECTED+8],install._jump(safety.CONTACT))
        frame=tag.frame_code(previous,bootstrap=True)
        self.assertEqual(ram[tag.FRAME:tag.FRAME+len(frame)],frame)
        ptr,count=struct.unpack_from('<2I',ram,tag.CONTROL+0x3A0)
        self.assertEqual(count,4);self.assertEqual(ram[ptr:ptr+count],bytes((3,3,1,1)))
        self.assertEqual(u(ram,tag.CONTROL+tag.C['training']),1)

    def test_reviewed_match_keeps_ordinary_fighters_when_one_outfit_cannot_tag(self):
        ram=fixture();actors=[u(ram,install.core.POINTERS+4*i) for i in range(4)]
        before=[bytes(ram[p:p+0x1600]) for p in actors]
        import fusion_audio_restore
        bank=install.beam_audio.isolate_bank(fusion_audio_restore.bank_file(0,False))
        def admission(iso,roster):
            return [dict(row,supported=row['index']!=2,reason='Ambiguous imported limb' if row['index']==2 else '') for row in roster]
        with patch.object(install.assets,'character_admission',side_effect=admission),\
             patch.object(scene,'installation',return_value=complete_plan()),\
             patch.object(install,'review_playtest_assets'),\
             patch.object(install.beam_audio,'disc_bank',return_value=bank):
            plan=self.build(ram,reviewed_assets=True)
        self.assertTrue(plan['usable']);apply(ram,plan)
        flags=u(ram,tag.CONTROL+0x3A0)
        self.assertEqual(ram[flags:flags+4],bytes((3,3,0,1)))
        self.assertEqual([bytes(ram[p:p+0x1600]) for p in actors],before)
        self.assertEqual(plan['characters'][2]['reason'],'Ambiguous imported limb')

    def test_reinstall_preserves_live_scene_and_charge_but_rejects_changed_code(self):
        ram=fixture()
        with patch.object(scene,'installation',return_value=complete_plan()):
            apply(ram,self.build(ram))
            ready(ram)
            w(ram,tag.METERS,123);w(ram,tag.CONTROL+tag.C['active'],1)
            w(ram,scene.STATE,0x12345);w(ram,safety.STATE,1)
            before=bytes(ram);plan=self.build(ram)
            self.assertTrue(plan['usable']);self.assertEqual(plan['blocks'],[]);self.assertEqual(ram,before)
            ram[tag.TICK]^=1
            with self.assertRaisesRegex(ValueError,'program changed'):self.build(ram)
            ram[tag.TICK]^=1;w(ram,tag.CONTROL+tag.C['count'],6)
            with self.assertRaisesRegex(ValueError,'control changed'):self.build(ram)
            w(ram,tag.CONTROL+tag.C['count'],4)
            w(ram,tag.CONTROL+tag.C['keep_meter_on_miss'],1)
            with self.assertRaisesRegex(ValueError,'control changed'):self.build(ram)

    def test_armed_reinstall_checks_both_native_receipts_without_rearming_disarmed_state(self):
        ram=fixture();fx=install.effects
        with patch.object(scene,'installation',return_value=complete_plan()):
            apply(ram,self.build(ram));ready(ram)
            for address in (install.GP+install.GPO(fx.NATIVE_POOL_OFFSET),
                            bootstrap.STATE+bootstrap.S['pool'],fx.CONTROL+fx.C['ready'],
                            fx.CONTROL+fx.C['init_status'],fx.ROWS+fx.R['prepared'],
                            fx.ROWS+fx.STRIDE+fx.R['prepared'],fx.ROWS+fx.DESC+796):
                old=u(ram,address);w(ram,address,0);before=bytes(ram)
                with self.assertRaisesRegex(ValueError,'effect.*(pool|receipt)'):self.build(ram)
                self.assertEqual(ram,before);w(ram,address,old)
            w(ram,tag.CONTROL+tag.C['ready'],0);w(ram,fx.CONTROL+fx.C['ready'],0)
            for phase in (bootstrap.READY,bootstrap.FAILED):
                w(ram,bootstrap.STATE+bootstrap.S['phase'],phase);before=bytes(ram)
                self.assertEqual(self.build(ram)['blocks'],[])
                self.assertEqual(ram,before);self.assertEqual(u(ram,tag.CONTROL+tag.C['ready']),0)

    def test_occupied_stale_unknown_and_overlapping_installs_are_rejected(self):
        for kind in ('occupied','manager','frame','contact','old safety','overlap','control'):
            with self.subTest(kind=kind):
                ram=fixture();plan=complete_plan()
                if kind=='occupied':ram[tag.BASE+0xFFE]=1
                elif kind=='manager':w(ram,install.core.MODE+8,MANAGER+16)
                elif kind=='frame':ram[install.participation.FRAME]^=1
                elif kind=='contact':put(ram,contact.PROTECTED,bytes(8))
                elif kind=='old safety':ram[inactive.ENTRY]^=1
                elif kind=='overlap':plan['blocks'].append((tag.TICK,bytes(8)))
                else:plan['control_words'][tag.C['ready']]=1
                before=bytes(ram)
                with patch.object(scene,'installation',return_value=plan):
                    with self.assertRaises(ValueError):self.build(ram)
                self.assertEqual(ram,before)

    def test_quad_hud_composes_around_existing_lockon_markers(self):
        ram=fixture(four=True);old=quad.draw()
        marked=bytearray(old)
        sites=threat.quad_sites(old,quad.DRAW,install.A(0x102708));self.assertEqual(len(sites),2)
        for p in sites:put(marked,p-quad.DRAW,threat.jal(threat.QUAD_LINK))
        put(ram,quad.DRAW,marked);w(ram,threat.CONTROL,threat.MAGIC)
        w(ram,threat.CONTROL+threat.FIELDS['quad_sites'],2)
        # The marker's own installer tests check its complete program. Here the
        # chain contract and exact per-view draw bytes are the unit under test.
        with patch.object(threat,'validate_memory') as validate:
            updates=install.hud_patches(ram);validate.assert_called_once_with(ram)
        changed=updates[0][1]
        self.assertEqual(len(threat.quad_sites(changed,quad.DRAW,threat.QUAD_LINK)),2)
        self.assertEqual(len(threat.quad_sites(changed,quad.DRAW,install.A(0x102708))),0)
        self.assertIn(install._jal(captions.DRAW),changed)
        w(ram,tag.CONTROL,tag.MAGIC)
        for p,b in captions.pieces(OPTIONS):put(ram,p,b)
        put(ram,quad.DRAW,changed)
        with patch.object(threat,'validate_memory'):self.assertEqual(install.hud_patches(ram),[])
        ram[quad.DRAW+24]^=1
        with patch.object(threat,'validate_memory'):
            with self.assertRaisesRegex(ValueError,'per-view renderer'):install.hud_patches(ram)

    def test_quad_hud_composes_before_the_target_markers_quad_entry(self):
        # 3-4 player matches: the target marker appends its own quad-only entry (lockon_select.quad_patch). Without
        # it among the candidates every such match stopped its setup ('Unknown per-view renderer').
        import lockon_select as sel
        marker=((sel.CONTROL,sel.MAGIC,sel.QMARKER),)
        ram=fixture(four=True);put(ram,quad.DRAW,quad.draw(marker))
        w(ram,sel.CONTROL,sel.MAGIC);w(ram,sel.CONTROL+sel.FIELDS['quad'],1)
        updates=install.hud_patches(ram)
        self.assertEqual(updates,[(quad.DRAW,quad.draw(((tag.CONTROL,tag.MAGIC,captions.DRAW),)+marker))])
        w(ram,tag.CONTROL,tag.MAGIC)
        for p,b in captions.pieces(OPTIONS):put(ram,p,b)
        put(ram,quad.DRAW,updates[0][1])
        self.assertEqual(install.hud_patches(ram),[])
        # Without the marker's quad flag the entry is not expected.
        ram=fixture(four=True);put(ram,quad.DRAW,quad.draw(marker));w(ram,sel.CONTROL,sel.MAGIC)
        with self.assertRaisesRegex(ValueError,'per-view renderer'):install.hud_patches(ram)

    def test_nonki_classification_uses_disc_names_not_bt3_ids(self):
        names={55:dict(name='Hercule'),57:dict(name='Cabba'),69:dict(name='Hatchiyack'),
               70:dict(name='Golden Frieza'),150:dict(name='Top'),157:dict(name='Zamasu'),249:dict(name='Chi-Chi')}
        roster=[dict(character=i,supported=True) for i in names]
        with patch('character_names.character_table',return_value=names):block,words=install.admission_block(assets(),roster)
        self.assertEqual(words[0x3A4],250);self.assertEqual(block[0]%16,0)
        self.assertEqual(block[1][55],1);self.assertEqual(block[1][249],1)
        self.assertTrue(all(block[1][i]==3 for i in (57,69,70,150,157)))
        self.assertEqual(block[1][0],0,'unchecked forms never borrow another roster slot')

    def test_nonki_classification_accepts_reviewed_spanish_roster_names(self):
        names={55:dict(base_name='Mr. Satan'),56:dict(base_name='Videl'),
               60:dict(base_name='Yajirobe'),165:dict(base_name='Gran Saiyaman 2'),
               176:dict(base_name='Milk'),178:dict(base_name='Octavio'),
               70:dict(base_name='Freezer',form='Golden Freezer')}
        roster=[dict(character=i,supported=True) for i in names]
        with patch('character_names.character_table',return_value=names):
            (_,flags),_=install.admission_block(assets(),roster)
        self.assertTrue(all(flags[i]==1 for i in (55,56,60,165,176,178)))
        self.assertEqual(flags[70],3,'localized names must not reuse replaced BT3 IDs')


class AssetCacheTests(unittest.TestCase):
    def test_special_beam_cache_rederives_recipe_and_exact_relocation_exceptions(self):
        sbc=install.special_beam;pack=special_assets();checked=install._asset_plan(install._asset_payload(pack))
        info=checked['special_beam_asset'];spans=install._special_beam_mutable(checked)
        self.assertEqual(spans,sbc.mutable_ranges(info))
        # The native SBC object's receipt leads; the private parse state and the
        # texture relocation exceptions follow unchanged.
        self.assertEqual(spans[0],(sbc.NSTATE,sbc.NSTATE_END))
        self.assertTrue(all(hi-lo==4 for lo,hi in spans[4:]))
        for change in ('top removed','nested removed','nested mismatch','extra exception','count','script','code block'):
            changed=copy.deepcopy(checked)
            if change=='top removed':changed.pop('special_beam_asset')
            elif change=='nested removed':changed['beam_asset'].pop('special_beam')
            elif change=='nested mismatch':changed['beam_asset']['special_beam']['slot']=2
            elif change=='code block':changed['blocks'].append((sbc.INIT,bytes(16)))
            else:
                for row in (changed['special_beam_asset'],changed['beam_asset']['special_beam']):
                    if change=='extra exception':row['mutable_ranges'].append([0,4])
                    elif change=='count':row['descriptor_counts'][0]=3
                    else:row['script_offset']=512
            with self.subTest(change=change),self.assertRaises(ValueError):
                install._asset_plan(install._asset_payload(changed))
        for address in (sbc.RESOURCE+300,sbc.RESOURCE+sbc.RESOURCE_SIZE-7):
            changed=copy.deepcopy(checked)
            for i,(base,data) in enumerate(changed['blocks']):
                if base<=address<base+len(data):
                    b=bytearray(data);b[address-base]^=1;changed['blocks'][i]=(base,bytes(b));break
            with self.assertRaisesRegex(ValueError,'source pixels or events'):
                install._asset_plan(install._asset_payload(changed))

    def test_special_beam_mutable_ranges_never_exempt_adjacent_code_magic_or_source_bytes(self):
        sbc=install.special_beam;pack=special_assets();allowed=install._special_beam_mutable(pack)
        blocks=sbc.pieces(pack['special_beam_asset'])+pack['blocks']
        parts=list(install._immutable_parts(blocks,allowed,allowed))
        def covered(address):return any(p<=address<p+len(b) for p,b in parts)
        self.assertTrue(all(covered(p) for p in (sbc.INIT,sbc.SELECT,sbc.STATE,sbc.RESOURCE,sbc.RESOURCE+300)))
        for lo,hi in allowed:
            self.assertFalse(covered(lo));self.assertFalse(covered(hi-1))
        for lo,hi in allowed[3:]:
            for adjacent in (lo-1,hi):
                if not any(a<=adjacent<b for a,b in allowed):self.assertTrue(covered(adjacent))
        for forbidden in ((sbc.INIT,sbc.SELECT),(sbc.STATE,sbc.STATE_END),
                          (sbc.RESOURCE,sbc.END),(install.authored_hold.DATA,install.authored_hold.END)):
            with self.assertRaisesRegex(ValueError,'runtime data range'):
                list(install._immutable_parts(blocks,[forbidden],allowed))

    def test_native_rush_resources_are_reviewed_against_the_selected_disc(self):
        iso=install.selected_iso()
        if not Path(iso).is_file():self.skipTest('Local game disc is unavailable')
        pack=install.assets.build_assets(iso,include_beam=True,include_camera=True)
        install.review_playtest_assets(pack,iso=iso)
        native=pack['approach']
        cases=((native['table_address']+12,'launch table'),
               (native['native_address']+24,'resource header'),
               (native['secondary_address'],'secondary poses'),
               (native['parameter_address']+20,'parameters'),
               (native['camera_address']+20,'camera'))
        for address,reason in cases:
            with self.subTest(address=hex(address)):
                changed=copy.deepcopy(pack)
                for i,(base,data) in enumerate(changed['blocks']):
                    if base<=address<base+len(data):
                        data=bytearray(data);data[address-base]^=1
                        changed['blocks'][i]=(base,bytes(data));break
                else:self.fail('Fixture address is outside the asset block')
                with self.assertRaisesRegex(ValueError,reason):install.review_playtest_assets(changed,iso=iso)

    def test_real_disc_admission_stays_in_main_arena_with_special_sources(self):
        iso=install.selected_iso()
        if not Path(iso).is_file():self.skipTest('Local game disc is unavailable')
        pack=install.assets.build_assets(iso,include_beam=True,include_camera=True)
        roster=[dict(index=i,character=character,costume=0,damaged=False)
                for i,character in enumerate((0,22,77))]
        admission=install.assets.character_admission(iso,roster)
        self.assertTrue(all(row['supported'] for row in admission))
        (address,flags),words=install.admission_block(pack,admission)
        self.assertTrue(any(install.SPECIAL_BASE<=p<p+len(b)<=install.SPECIAL_DATA_END
                            for p,b in pack['blocks']))
        expected=(max(p+len(b) for p,b in pack['blocks']
                      if install.assets.BASE<=p<p+len(b)<=install.assets.END)+15)&~15
        self.assertEqual(address,expected)
        self.assertEqual(words[0x3A0],address)
        self.assertLessEqual(address+len(flags),install.assets.END)
        self.assertTrue(all(flags[character]==3 for character in (0,22,77)))
        self.assertTrue(all(address+len(flags)<=p or p+len(b)<=address for p,b in pack['blocks']))
        # Real mixed-arena packs must still refuse a full main bank; the distant
        # special bank does not provide an escape from the admission limit.
        full=copy.deepcopy(pack)
        full['blocks']=[row for row in full['blocks'] if row[0]>=install.SPECIAL_BASE]
        full['blocks'].append((install.assets.BASE,bytes(install.assets.END-install.assets.BASE)))
        with self.assertRaisesRegex(ValueError,'admission table exceeds'):
            install.admission_block(full,admission)

    def test_camera_evaluator_source_changes_invalidate_cached_samples(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);iso=root/'disc.iso';iso.write_bytes(b'local fixture')
            asset_source=root/'tag_rush_assets.py';asset_source.write_text('assets')
            shots_source=root/'tag_rush_shots.py'
            with patch.object(install.assets,'__file__',str(asset_source)):
                missing=install._identity(iso)[2]
                shots_source.write_text('first evaluator');present=install._identity(iso)[2]
                shots_source.write_text('new evaluator');changed=install._identity(iso)[2]
            self.assertEqual(len({missing,present,changed}),3)

    def test_authored_hold_source_changes_invalidate_cached_preparation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);iso=root/'disc.iso';iso.write_bytes(b'local fixture')
            asset_source=root/'tag_rush_assets.py';asset_source.write_text('assets')
            hold_source=root/'tag_rush_authored_hold.py'
            with patch.object(install.assets,'__file__',str(asset_source)):
                missing=install._identity(iso)[2]
                hold_source.write_text('first user endpoints');present=install._identity(iso)[2]
                hold_source.write_text('edited user endpoints');changed=install._identity(iso)[2]
            self.assertEqual(len({missing,present,changed}),3)

    def test_real_disc_beam_relocations_are_bounded_and_cannot_exempt_pose_data(self):
        name=('SLUS_219.78.DBZBT4B14REV2ENG.iso' if 'bt4' in str(Path(__file__).resolve().parent)
              else 'Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso')
        iso=Path(__file__).resolve().parents[2]/'games'/name
        if not iso.is_file():self.skipTest('Local game disc is unavailable')
        pack=install.assets.build_assets(iso,include_beam=True)
        payload=install._asset_payload(pack);checked=install._asset_plan(payload)
        spans=install._beam_mutable(checked);beam=checked['beam_asset']
        self.assertEqual(len(spans),44)
        self.assertTrue(all(hi-lo==4 and beam['resource_address']<=lo<hi<=beam['resource_address']+beam['resource_size'] for lo,hi in spans))
        checked['beam_asset']['mutable_ranges'].append([0,32])
        with self.assertRaisesRegex(ValueError,'recipe changed'):install._beam_mutable(checked)

    def test_mutable_texture_words_do_not_exempt_neighboring_animations(self):
        base=install.assets.BASE;data=bytes(range(32))
        parts=list(install._immutable_parts([(base,data)],[(base+4,base+8),(base+16,base+20)]))
        self.assertEqual(parts,[(base,data[:4]),(base+8,data[8:16]),(base+20,data[20:])])
        for changed in range(len(data)):
            actual=bytearray(data);actual[changed]^=1
            matches=all(actual[p-base:p-base+len(b)]==b for p,b in parts)
            self.assertEqual(matches,changed in (*range(4,8),*range(16,20)))
        with self.assertRaisesRegex(ValueError,'runtime data range'):
            list(install._immutable_parts([(base,data)],[(tag.CONTROL,tag.END+4)]))

    def test_input_buffer_data_is_mutable_but_cannot_exempt_cpu_code(self):
        lo,hi=tag.INPUT_BUFFERS,tag.INPUT_BUFFERS_END
        self.assertEqual(list(install._immutable_parts([(lo,bytes(hi-lo))],[(lo,hi)])),[])
        for bad in ((lo-4,hi),(lo,hi+4),(tag.BUFFER_TARGET,lo)):
            with self.subTest(span=bad),self.assertRaisesRegex(ValueError,'runtime data range'):
                list(install._immutable_parts([(lo,bytes(hi-lo))],[bad]))

    def test_cache_is_per_iso_checked_and_bad_cache_is_rebuilt(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);iso=root/'disc.iso';iso.write_bytes(b'local fixture')
            with patch.object(install,'CACHE_ROOT',root/'cache'),patch.object(install.assets,'build_assets',return_value=assets()) as build:
                first,key=install.cached_assets(iso);again,key2=install.cached_assets(iso)
                self.assertEqual(first,again);self.assertEqual(key,key2);self.assertEqual(build.call_count,1)
                build.assert_called_once_with(iso.resolve(),include_beam=True,include_camera=True)
                cache=root/'cache'/(key+'.json');record=json.loads(cache.read_text())
                record['payload']['blocks'][0]['data_hex']='01';cache.write_text(json.dumps(record))
                rebuilt,_=install.cached_assets(iso);self.assertEqual(rebuilt,first);self.assertEqual(build.call_count,2)
                iso.write_bytes(b'a different ISO');_,key3=install.cached_assets(iso)
                self.assertNotEqual(key,key3);self.assertEqual(build.call_count,3)

    def test_cached_assets_cannot_escape_or_overlap_the_pose_reservation(self):
        for kind in ('outside','overlap','descriptor'):
            plan=assets()
            if kind=='outside':plan['blocks'][0]=(tag.CONTROL,b'12345678')
            elif kind=='overlap':plan['blocks'].append(plan['blocks'][0])
            else:plan['variants']['two_ki']['address']=tag.CONTROL
            with self.subTest(kind=kind),self.assertRaises(ValueError):install._asset_plan(install._asset_payload(plan))

    def test_cached_special_source_data_cannot_expand_into_helpers_or_other_banks(self):
        plan=assets();plan['blocks'].append((install.SPECIAL_BASE,bytes(32)))
        self.assertEqual(install._asset_plan(install._asset_payload(plan))['blocks'],plan['blocks'])
        for p in (install.SPECIAL_BASE-16,install.SPECIAL_DATA_END-16,install.SPECIAL_END,install.pose_profiles.DATA):
            plan['blocks'][-1]=(p,bytes(32))
            with self.assertRaisesRegex(ValueError,'cached tag animation block'):
                install._asset_plan(install._asset_payload(plan))


class CostumeBoundsTests(unittest.TestCase):
    def test_bt4_ninth_costume_reaches_topology_checks_but_tenth_is_rejected(self):
        ram=fixture();actor=u(ram,install.core.POINTERS)
        model=u(ram,install.core.MODELS);w(ram,model+12,240)
        row=actor+0x9A4;w(ram,row+4,8)
        def count(character):
            if character==240:return 9
            if character==161:raise ValueError('Menu entry, not a fighter')
            return 4
        resources=types.SimpleNamespace(costume_count=count)
        with patch.object(install,'SERIAL','SLUS-21978'),patch.dict(sys.modules,{'bt4_resources':resources}):
            before=bytes(ram)
            self.assertEqual(install._roster(ram,4)[0]['costume'],8)
            self.assertEqual(ram,before)
            w(ram,row+4,9)
            with self.assertRaisesRegex(ValueError,'costume'):install._roster(ram,4)
            w(ram,model+12,161);w(ram,row+4,0)
            with self.assertRaisesRegex(ValueError,'Menu entry'):install._roster(ram,4)

    def test_bt3_cannot_read_costumes_from_adjacent_resource_slots(self):
        ram=fixture();actor=u(ram,install.core.POINTERS)
        with patch.object(install,'SERIAL','SLUS-21678'):
            w(ram,actor+0x9A4+4,3)
            self.assertEqual(install._roster(ram,4)[0]['costume'],3)
            w(ram,actor+0x9A4+4,4)
            with self.assertRaisesRegex(ValueError,'costume'):install._roster(ram,4)
            with self.assertRaisesRegex(ValueError,'character'):install._costume_count(161)


if __name__=='__main__':unittest.main()
