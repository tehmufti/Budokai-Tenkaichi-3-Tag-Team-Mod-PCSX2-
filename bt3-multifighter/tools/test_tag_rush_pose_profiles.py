"""Reviewed beam choices and scoped donated pose lifecycle in emitted code."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import hashlib
import struct
import unittest
from unittest.mock import patch

import tag_rush_pose_profiles as profiles
import tag_rush_native_pose as pose
import tag_rush_retarget as retarget
import tag_rush_scene as scene
import tag_rush_assets as assets
from test_tag_rush_native_pose import fixture, enter
from test_tag_rush_scene import start
from test_tag_rush_camera import run


def publish(c, *, fire=264, donor=True, flags=0):
    p=profiles.DATA;bank=p+0x1800;model=p+0x800
    c.write(p,bytes(0x2000));c.write(p,struct.pack('<4I',profiles.MAGIC,250,0x2000,0))
    character=c.u(c.models[0]+12)
    c.write(p+16+character*8,struct.pack('<2I',fire,bank if donor else 0))
    clips=[p+0x1900+i*0x100 for i in range(4)]
    c.write(bank,struct.pack('<8I',model,fire,flags,5,*clips))
    for ptr in clips:c.write(ptr,struct.pack('<2I',148,5))
    c.w(scene.CONTROL+profiles.TABLE_OFFSET,p)
    c.callbacks[profiles.CHECK]=lambda m:m.r.__setitem__(2,1)
    return bank,model,clips


class PoseProfileTests(unittest.TestCase):
    def test_explicit_beam_overrides_projectile_type_without_mutating_own_bank(self):
        c=fixture();model=c.models[0];params=c.u(model+2348)
        c.write(params+318,bytes(3));bank=bytes(c.read(model+192,1800))
        for clip in (264,298,332,364):
            c.w(model+192+clip*4,0x3B00000+clip*4);c.w(0x3B00000+clip*4,256)
        before=c.read(model,0x1700)
        for fire in (264,298,332,364):
            publish(c,fire=fire,donor=False);c.r[4]=model;run(c,pose.SELECT)
            self.assertEqual((c.r[2],c.r[3]),(fire,0))
        self.assertEqual(c.read(model,0x1700),before)

    def test_donor_charge_fire_retargets_once_each_and_restores_ordinary_clips(self):
        c=fixture();start(c);row=scene.ROWS;model=c.models[0]
        original=c.u(row+24);own_bank=c.read(model+196,1700)
        bank,donor,clips=publish(c);calls=[];native=c.callbacks[scene.A(0x1C3E60)]
        def decode(m):
            self.assertEqual(m.r[5],0)
            self.assertEqual(m.u(m.u(model+5728)+98344),0)
            native(m);m.fw(model+2884,12. if m.u(model+192)==clips[0] else 30.)
        def convert(m):calls.append(tuple(m.r[4:9]));m.r[2]=1
        c.callbacks[scene.A(0x1C3E60)]=decode;c.callbacks[profiles.RETARGET]=convert
        c.w(assets.BASE+28,assets.CUSTOM_FINISHER|pose.OWN_CLASH_POSE|pose.CHARGE_BEAM|2)
        self.assertEqual(enter(c),1);self.assertEqual(c.u(row+pose.BANK),bank)
        seen=[c.u(row+pose.CLIP)]
        for _ in range(50):
            c.r[4:6]=[0,row];run(c,pose.TICK);self.assertEqual(c.r[2],1)
            seen.append(c.u(row+pose.CLIP))
            self.assertEqual(c.u(c.u(model+5728)+98344),7)
        self.assertEqual(list(dict.fromkeys(seen)),[261,262,263,264])
        self.assertEqual(len(calls),4)
        self.assertTrue(all(call[1:]==(model,donor,0,0) for call in calls))
        self.assertEqual(c.read(model+196,1700),own_bank)
        c.callbacks[scene.A(0x1C3E60)]=native;c.r[4]=1;run(c,scene.FINISH)
        self.assertEqual(c.u(model+192),original)
        self.assertEqual(c.u(row+pose.ACTIVE),0);self.assertEqual(c.damage,[])

    def test_invalid_table_bank_and_packet_refuse_before_decode(self):
        for bad in ('magic','character','bank alignment','bank range','donor','donor alignment','bind kind','packet size','packed extent','fire mismatch'):
            with self.subTest(bad=bad):
                c=fixture();bank,donor,clips=publish(c);model=c.models[0]
                if bad=='magic':c.w(profiles.DATA,0)
                elif bad=='character':c.w(model+12,250)
                elif bad=='bank alignment':c.w(profiles.DATA+20,bank+1)
                elif bad=='bank range':c.w(profiles.DATA+20,profiles.END)
                elif bad=='donor':c.w(bank,0)
                elif bad=='donor alignment':c.w(bank,donor+1)
                elif bad=='bind kind':c.w(bank+profiles.BANK_KIND,7)
                elif bad=='packet size':c.w(clips[2],50000)
                elif bad=='packed extent':c.w(clips[1]+4,0x100000)
                else:c.w(bank+4,332)
                before=c.read(model,0x1700);c.r[4]=model;run(c,pose.SELECT)
                self.assertEqual(c.r[2],0xFFFFFFFF);self.assertEqual(c.r[3],0)
                self.assertEqual(c.read(model,0x1700),before);self.assertEqual(c.idle_starts,[])

    def test_bad_recipient_bind_refuses_before_startup_mutation(self):
        c=fixture();bank,_,_=publish(c);model=c.models[0]
        c.callbacks[profiles.CHECK]=lambda m:m.r.__setitem__(2,0)
        before=c.read(model,0x1700);c.r[4]=model;run(c,pose.SELECT)
        self.assertEqual(c.r[2],0xFFFFFFFF);self.assertEqual(c.r[3],0)
        self.assertEqual(c.read(model,0x1700),before);self.assertEqual(c.idle_starts,[])

    def test_incompatible_idle_normalization_refuses_before_pointer_or_marker_writes(self):
        c=fixture();start(c);bank,_,_=publish(c);model=c.models[0];row=scene.ROWS
        c.w(row+pose.BANK,bank)
        c.callbacks[scene.A(0x1C4650)]=lambda m:m.r.__setitem__(2,0xC0000000 if m.r[4]==0 else 0x80000040)
        before=c.read(model,0x1700);marker=c.u(c.u(model+5728)+98344)
        c.r[4:6]=[row,261];run(c,profiles.DONOR_PLAY)
        self.assertEqual(c.r[2],0);self.assertEqual(c.read(model,0x1700),before)
        self.assertEqual(c.u(c.u(model+5728)+98344),marker)

    def test_native_index_zero_and_beam_flags_have_identical_normalization(self):
        from native_map import A,elf_path
        from prototype import ROOT,elf_reader
        from test_tag_rush_scene import SceneCpu
        if not elf_path(ROOT).is_file():self.skipTest('Native executable not available')
        native=elf_reader(elf_path(ROOT))[2]
        calls=[];c=SceneCpu({'segments':[dict(address=A(0x1C3CA8),data_hex=native(A(0x1C3CA8),0xB0).hex())]})
        c.callbacks[A(0x1C4650)]=lambda m:m.r.__setitem__(2,0x80030001 if m.r[4]==0 else 0x80000040)
        for address in (0x24C800,0x24C728):
            c.callbacks[A(address)]=lambda m,address=address:calls.append((address,tuple(m.r[4:8])))
        for animation in (0,261,262,263,264,329,332):
            calls.clear();c.r[4:6]=[0x5200000,animation];run(c,A(0x1C3CA8))
            self.assertEqual([address for address,_ in calls],[0x24C800])

    def test_guest_code_and_profile_data_stay_between_cpu_and_online_hash_arenas(self):
        import tag_rush_cpu
        self.assertEqual(profiles.BASE,tag_rush_cpu.END)
        self.assertEqual(profiles.END,0x06E00000)
        blocks=sorted(profiles.pieces())
        for (base,data),(next_base,_) in zip(blocks,blocks[1:]):self.assertLessEqual(base+len(data),next_base)
        self.assertLessEqual(blocks[-1][0]+len(blocks[-1][1]),profiles.DATA)

    def test_donated_muzzle_uses_source_flags_not_recipients_projectile(self):
        import tag_rush_effects as fx
        from test_tag_rush_effects import machine
        for donor_mouth,own_mouth,expected in ((False,True,45),(True,False,54)):
            c=machine()
            for address,data in profiles.pieces():c.write(address,data)
            bank,_,_=publish(c,flags=0x2000 if donor_mouth else 0)
            c.w(scene.STATE,scene.SCENE_MAGIC);c.w(scene.STATE+scene.S['descriptor'],assets.BASE)
            c.w(assets.BASE+28,pose.OWN_CLASH_POSE|2)
            model=c.models[0];row=scene.ROWS;c.w(row+scene.R['model'],model)
            c.w(row+pose.ACTIVE,1);c.w(row+pose.FIRE_CLIP,264);c.w(row+pose.BANK,bank)
            c.w(c.u(model+2348),0x2000 if own_mouth else 0)
            mouth=0x3700000;c.w(model+3436+4*54,mouth);c.write(mouth+64,struct.pack('<4f',0,-50,0,1))
            for bone,z in ((31,-10),(45,10)):
                c.write(c.u(model+3436+4*bone)+64,struct.pack('<4f',0,-40,z,1))
            c.w(fx.ROWS+fx.R['source_model'],model);c.w(fx.ROWS+fx.R['target_model'],c.models[1])
            c.r[4]=fx.ROWS;run(c,fx.SELECT_SOURCE);self.assertEqual(c.r[2],expected)

    def test_real_disc_donor_pack_roundtrips_exact_native_clips_and_dual_height(self):
        import tag_rush_install as install
        import model_assets,model_animations
        try:iso=install.selected_iso()
        except (OSError,ValueError):self.skipTest('Native disc not available')
        if not iso.exists():self.skipTest('Native disc not available')
        bt4=install.SERIAL=='SLUS-21978'
        def policy(character):
            return dict(mode='donor',slot=2,donor=29) if character in (31,32) else dict(mode='auto')
        plan=profiles.build_assets(iso,bt4=bt4,policy=policy)
        payload=plan['blocks'][0][1]
        read=lambda address,size:payload[address-profiles.DATA:address-profiles.DATA+size]
        bank=struct.unpack('<2I',read(profiles.DATA+16+31*8,8))[1]
        self.assertEqual(bank,struct.unpack('<2I',read(profiles.DATA+16+32*8,8))[1])
        donor,fire,flags,_,*clips=struct.unpack('<8I',read(bank,32))
        params=struct.unpack('<I',read(donor+24,4))[0];height=struct.unpack('<I',read(donor+2332,4))[0]
        self.assertEqual(read(params+0x74,4),read(height+4,4))
        native=model_assets.read_animation_bank(iso,29)
        for index,pointer in enumerate(clips):
            size=struct.unpack('<I',read(pointer+4,4))[0]
            decoded=model_animations.decompress_animation(read(pointer,size+8))
            expected=model_animations.decompress_animation(model_assets.package_entry(native,262+index))
            self.assertEqual(decoded,expected)
        self.assertLess(profiles.DATA+len(payload),profiles.END)
        self.assertEqual(hashlib.sha256(payload).hexdigest(),plan['sha256'])

    def test_real_native_retarget_of_all_donated_joints_matches_original_exactly(self):
        import tag_rush_install as install
        import model_assets,model_animations
        from prototype import ROOT,elf_reader
        from native_map import A,elf_path
        from test_tag_rush_scene import SceneCpu
        try:iso=install.selected_iso()
        except (OSError,ValueError):self.skipTest('Native disc not available')
        if not iso.exists() or not elf_path(ROOT).exists():self.skipTest('Native disc/executable unavailable')
        native=elf_reader(elf_path(ROOT))[2];bt4=install.SERIAL=='SLUS-21978'
        choices={32:(29,2),51:(0,2),114:(80,4),160:(159,4)}
        if bt4:choices[139]=(53,2)
        choices[68 if bt4 else 37]=(37,2)
        policy=lambda character:dict(mode='donor',donor=choices[character][0],slot=choices[character][1]) if character in choices else dict(mode='auto')
        plan=profiles.build_assets(iso,bt4=bt4,policy=policy);data=plan['blocks'][0][1]
        for character,(source,slot) in choices.items():
            skeleton=assets.read_skeleton(iso,character);recipient=0x5000000
            model=bytearray(profiles._source_model(skeleton,recipient));struct.pack_into('<I',model,12,character)
            bank=struct.unpack_from('<I',data,profiles.HEADER+8*character+4)[0]
            donor=struct.unpack_from('<I',data,bank-profiles.DATA)[0]
            clips=struct.unpack_from('<4I',data,bank-profiles.DATA+profiles.BANK_CLIPS)
            for index,ptr in enumerate(clips):
                size=struct.unpack_from('<I',data,ptr-profiles.DATA+4)[0]
                raw=model_animations.decompress_animation(data[ptr-profiles.DATA:ptr-profiles.DATA+size+8])
                results=[]
                for wrapped in (False,True):
                    chunks=profiles.pieces(plan)+retarget.pieces()
                    c=SceneCpu({'segments':[dict(address=p,data_hex=b.hex())for p,b in chunks]})
                    for address,length in ((0x24BBE8,0x370),(0x250570,0x60)):c.write(A(address),native(A(address),length))
                    c.write(recipient,model);c.w(scene.CONTROL+profiles.TABLE_OFFSET,profiles.DATA)
                    scratch=0x5200000;c.write(scratch,raw);c.r[4:9]=[scratch,recipient,donor,0,0]
                    run(c,profiles.RETARGET if wrapped else A(0x24BBE8))
                    if wrapped:self.assertEqual(c.r[2],1,(character,index))
                    self.assertEqual(c.read(recipient,len(model)),model)
                    self.assertEqual(c.read(profiles.DATA,len(data)),data)
                    results.append(c.read(scratch,len(raw)))
                self.assertEqual(*results,(character,index))
                # 1C3E60 normalizes index0 before the scoped manual retarget.
                # Prove this yields the native retarget-then-normalize result
                # for the actual donated clips and recipient bind roots.
                normalized=[]
                for wrapped in (False,True):
                    c=SceneCpu({'segments':[dict(address=p,data_hex=b.hex())for p,b in profiles.pieces(plan)+retarget.pieces()]})
                    for address,length in ((0x24BBE8,0x370),(0x250570,0x60),(0x24C800,0x90)):
                        c.write(A(address),native(A(address),length))
                    c.write(recipient,model);c.w(scene.CONTROL+profiles.TABLE_OFFSET,profiles.DATA);c.write(scratch,raw)
                    if wrapped:c.r[4]=scratch;run(c,A(0x24C800))
                    c.r[4:9]=[scratch,recipient,donor,0,0]
                    run(c,profiles.RETARGET if wrapped else A(0x24BBE8))
                    if not wrapped:c.r[4]=scratch;run(c,A(0x24C800))
                    normalized.append(model_animations.AnimationClip.from_decoded(0,c.read(scratch,len(raw))))
                for first,second in zip(normalized[0].tracks,normalized[1].tracks):
                    for x,y in zip(first.keys,second.keys):
                        if x.translation is not None:
                            for a,b in zip(x.translation,y.translation):self.assertAlmostEqual(a,b,delta=.0002)


if __name__=='__main__':unittest.main()
