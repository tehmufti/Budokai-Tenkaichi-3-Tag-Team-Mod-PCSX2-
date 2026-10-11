"""Disc choreography, bounded extraction and native packet round-trip checks."""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

from pathlib import Path
import struct
import unittest
from unittest.mock import patch

import model_animations as animations
import tag_rush_assets as assets


def minimal_clip(frames=68):
    raw = bytearray(148 + 12)
    struct.pack_into('<HH', raw, 0, 0, frames)
    struct.pack_into('<H', raw, 6, 37)
    struct.pack_into('<HHQ', raw, 148, 1, 1, 0x3800008000080000)
    return bytes(raw)


class ChoreographyTests(unittest.TestCase):
    def test_donor_contains_both_native_retarget_height_layouts(self):
        bindings={101:dict(height=.9,rows=()),102:dict(height=.85,rows=())}
        base=0x06D20000
        raw,models,_=assets.pack_donor_bindings(bindings,base)
        for character,model in models.items():
            offset=model-base
            header=struct.unpack_from('<I',raw,offset+24)[0]
            usa_height=struct.unpack_from('<I',raw,offset+2332)[0]
            self.assertEqual(header,model+0x100)
            actual=struct.unpack_from('<f',raw,header-base+0x74)[0]
            self.assertEqual(actual,struct.unpack_from('<f',raw,usa_height-base+4)[0])
            self.assertAlmostEqual(actual,bindings[character]['height'])

    def test_beam_finishers_select_live_character_clash_poses(self):
        import tag_rush_choreography as choreography
        self.assertNotIn('beam',choreography.DERIVED)
        for name in choreography.VARIANTS:
            for phase in assets.timeline(name):
                beams=phase.flags&(assets.BEAM_LEAD|assets.BEAM_PARTNER)
                self.assertEqual(bool(phase.flags&assets.OWN_CLASH_POSE),bool(beams))
                for role in (0,1):
                    if beams&(assets.BEAM_LEAD<<role):
                        self.assertEqual(phase.roles[role].animation,1000)

    def test_admission_requires_both_native_effect_hand_nodes(self):
        rows=[dict(bone=i,parent=i-1)for i in range(53)]
        donor=dict(rows=rows,height=10.)
        with patch.object(assets,'read_donor_bindings',return_value={101:donor}):
            for missing in (None,31,45):
                skeleton=dict(rows=[r for r in rows if r['bone']!=missing],height=10.)
                with patch.object(assets,'read_skeleton',return_value=skeleton):
                    result=assets.character_admission('unused.iso',[0])[0]
                self.assertEqual(result['supported'],missing is None)
                if missing is not None:self.assertIn(missing,result['incompatible_bones'])

    def test_actual_partner_poses_come_from_mesh_and_are_in_sync(self):
        phases = assets.timeline('two_ki')
        self.assertEqual([p.source_frames for p in phases], [68, 99, 149, 119, 24, 180])
        self.assertEqual([p.roles[0].animation for p in phases[:4]], [352, 353, 354, 355])
        self.assertEqual([p.roles[2].animation for p in phases[:4]], [357, 358, 359, 360])
        self.assertEqual([p.roles[1].mesh_entry for p in phases[2:4]], [29, 30])
        self.assertTrue(all(p.roles[1] is None and p.flags & assets.HOLD_HELPER for p in phases[:2]))

    def test_nonki_roles_do_not_reach_the_beam_pose(self):
        melee = assets.timeline('two_melee')[-1]
        self.assertEqual(melee.ends, (24, 24, 24))
        self.assertFalse(melee.flags & (assets.BEAM_LEAD | assets.BEAM_PARTNER))
        for variant, end, flag in [('mixed_ki_lead', (180, 180, 180), assets.BEAM_LEAD),
                                   ('mixed_ki_partner', (180, 180, 180), assets.BEAM_PARTNER)]:
            phase = assets.timeline(variant)[-1]
            self.assertEqual(phase.ends, end)
            self.assertEqual(phase.flags & 6, flag)
            nonki=1 if variant=='mixed_ki_lead' else 0
            self.assertEqual(phase.roles[nonki].animation,1010)

    def test_source_frames_are_not_the_workbench_preview_clock(self):
        self.assertEqual(assets.OPENING[0].ticks(30), 34)
        self.assertEqual(assets.OPENING[0].ticks(25), 29)
        with self.assertRaises(ValueError): assets.OPENING[0].ticks(0)

    def test_sound_parser_rejects_pose_overlap_and_ignores_voice_move_events(self):
        raw=bytearray(148+16*3)
        struct.pack_into('<HH',raw,0,3<<8,120)
        # A global cue, recipient-dependent global cue, then character-bank
        # firing/voice bits: the latter must never become a global SFX request.
        for i,row in enumerate(((0x10000000,20,0),(0x4000000000,40,0),(0x88000,60,0))):
            struct.pack_into('<QII',raw,148+16*i,*row)
        cues=assets.source_audio_cues(raw)
        self.assertEqual([(c['frame'],c['sound_id']) for c in cues],[(20,30),(40,51)])
        self.assertEqual(cues[1]['alternate_sound_id'],11)
        self.assertEqual(cues[1]['parameter_flag'],0x8000)
        self.assertTrue(all((c['bank'],c['bone'],c['near'],c['far'])==(0,3,200.,1500.) for c in cues))
        struct.pack_into('<H',raw,6,37)
        with self.assertRaises(assets.TagRushAssetError):assets.source_audio_cues(raw)

    def test_literal_packet_retains_every_channel_byte(self):
        raw = minimal_clip()
        self.assertEqual(animations.decompress_animation(assets.literal_pack(raw)), raw)
        # Multiple packets, including a native-size boundary, round-trip too.
        padded = raw + bytes(0xC000 - len(raw))
        self.assertEqual(animations.decompress_animation(assets.literal_pack(padded)), padded)
        with self.assertRaises(assets.TagRushAssetError): assets.literal_pack(padded + b'\0')

    def test_descriptor_bounds_and_role_end_limits(self):
        clips = {source: minimal_clip(frames) for source, frames in assets.EXPECTED_FRAMES.items()}
        import tag_rush_choreography as choreography
        clips.update({assets.ClipSource(101,anim):minimal_clip(frames) for anim,frames,_ in choreography.DERIVED.values()})
        bindings = {character: dict(height=1., rows=()) for character in (101,102)}
        with patch.object(assets, 'prepared_clips', return_value=clips), patch.object(assets, 'read_donor_bindings', return_value=bindings), patch.object(assets, 'read_native_staging', return_value=assets.NATIVE_STAGING), patch.object(assets, 'read_native_approach', return_value=dict(parameters=bytes(640),camera=bytes(384))):
            result = assets.build_assets('unused.iso')
            data = result['blocks'][0][1]
            self.assertEqual(len(data), 27 * 64)
            for v in result['variants'].values():
                for p in v['phases']:
                    words = struct.unpack_from('<16I', data, p['address'] - assets.BASE)
                    self.assertEqual(words[0], p['source_frames'])
                    self.assertEqual(words[11:14], p['ends'])
                    self.assertEqual(words[14], 60)
                    self.assertEqual(words[15], result['custom_role_donors_address'] if words[7]&assets.CUSTOM_FINISHER else result['role_donors_address'])
            with self.assertRaises(assets.TagRushAssetError):
                assets.build_assets('unused.iso', end=assets.BASE + 128)
            for bad in ('unknown', '', None):
                with self.assertRaises(ValueError): assets.timeline(bad)


class DiscTests(unittest.TestCase):
    def test_local_disc_native_clips_round_trip_without_changed_root_motion(self):
        import native_map
        root = Path(__file__).resolve().parents[2]
        name = ('SLUS_219.78.DBZBT4B14REV2ENG.iso' if 'bt4' in str(Path(__file__).resolve().parent)
                else 'Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso')
        iso = root / 'games' / name
        if not iso.is_file() or native_map.TRANSLATED:
            self.skipTest('Local identity-layout game disc is not available')
        decoded = assets.read_clips(iso)
        result = assets.build_assets(iso)
        self.assertLess(result['bytes_used'], 0x64000)
        self.assertEqual(len(decoded), len(assets.EXPECTED_FRAMES))
        # The approach is intentionally not rewritten to a stationary skeleton.
        clip = animations.AnimationClip.from_decoded(352, decoded[assets.LEAD[352]])
        self.assertNotEqual(clip.evaluate(0)[0].translation, clip.evaluate(68)[0].translation)
        for source, raw in decoded.items():
            self.assertEqual(animations.decompress_animation(assets.literal_pack(raw)), raw, source)
        block_base, block = result['blocks'][1]
        approach=result['approach'];at=approach['table_address']-block_base
        self.assertEqual(struct.unpack_from('<4I',block,at),
                         (assets.APPROACH_MAGIC,result['donor_models'][101],5,approach['native_address']))
        self.assertEqual([row['animation'] for row in approach['clips']],[329,330,331,332,335])
        for i,row in enumerate(approach['clips']):
            self.assertEqual(struct.unpack_from('<2I',block,at+16+i*8),(row['address'],row['source_frames']))
            packed=block[row['address']-block_base:]
            raw=animations.decompress_animation(packed)
            self.assertEqual(raw,decoded[assets.ClipSource(101,row['animation'])])
        native=assets.read_native_approach(iso)
        for key in ('parameters','camera'):
            address=approach['parameter_address' if key=='parameters' else 'camera_address']
            self.assertEqual(block[address-block_base:address-block_base+len(native[key])],native[key])
        prepared=assets.prepared_clips(iso)
        for i,animation in enumerate((*range(352,357),363)):
            address=struct.unpack_from('<I',block,approach['secondary_address']-block_base+4*i)[0]
            raw=animations.decompress_animation(block[address-block_base:])
            source=assets.ClipSource(101,animation)
            self.assertEqual(raw,prepared[source])
            # Native approach reads these secondary clips for duration/events,
            # before the paired poses play. Contact-only edits preserve both.
            events=struct.unpack_from('<H',decoded[source])[0]>>8
            self.assertEqual(raw[:4],decoded[source][:4])
            self.assertEqual(raw[148:148+16*events],decoded[source][148:148+16*events])
        for character, address in result['donor_models'].items():
            offset=address-block_base
            nodes, height = (struct.unpack_from('<I',block,offset+i)[0] for i in (68,2332))
            cursor=nodes-block_base; ids=[]
            while True:
                size,_,last,vertices,bone=struct.unpack_from('<IHHHH',block,cursor)
                self.assertEqual(size,64);self.assertEqual(vertices,0)
                ids.append(bone)
                if last:break
                cursor+=size
            self.assertIn(2,ids);self.assertIn(47,ids)
            self.assertGreater(struct.unpack_from('<f',block,height-block_base+4)[0],0)
        admission=assets.character_admission(iso,[0,101,102])
        self.assertTrue(all(r['supported'] for r in admission),admission)
        self.assertEqual(assets.read_native_staging(iso),assets.NATIVE_STAGING)
        cues=assets.source_audio_cues(decoded[assets.LEAD[352]])
        self.assertEqual([(c['frame'],c['sound_id']) for c in cues],[(19,73),(52,51),(60,30)])
        impacts=[c for phases in result['audio_cues']['two_ki']for c in phases if c.get('effect_kind')]
        self.assertEqual([(c['role'],c['frame'],c['impact_bone'])for c in impacts],
            [(0,19,5),(0,70,11),(2,58,12),(2,97,12),(0,39,12),(0,95,3)])
        self.assertEqual(result['audio_cues']['two_melee'][-1],tuple(
            cue for cue in result['audio_cues']['two_ki'][-1] if cue['frame']<=40))
        offset=result['staging_address']-block_base
        for variant in result['variants'].values():
            self.assertEqual(tuple(struct.unpack_from('<4f',block,offset+i*16) for i in range(4)), assets.NATIVE_STAGING[:4])
            offset+=variant['count']*16
        beam=assets.read_native_beam_asset(iso)
        self.assertEqual(beam['descriptor_counts'],(1,6,0,1))
        self.assertEqual(beam['descriptor_raw_bytes'],2176)
        self.assertEqual(len(beam['resource']),107456)
        self.assertEqual(len(beam['mutable_ranges']),44)
        self.assertEqual(len(set(beam['mutable_ranges'])),44)
        self.assertTrue(all(size==4 and 0<=offset<=len(beam['resource'])-4
                            for offset,size in beam['mutable_ranges']))
        self.assertTrue(all(offset>=8 for offset,_ in beam['mutable_ranges']))
        with_beam=assets.build_assets(iso,include_beam=True)
        self.assertLess(with_beam['bytes_used'],assets.END-assets.BASE)
        self.assertEqual(with_beam['beam_asset']['resource_sha256'],beam['resource_sha256'])
        for field, value in ((0,255),(4*5,0x7FFFFFFC)):
            corrupt=bytearray(beam['resource'])
            struct.pack_into('<I',corrupt,field,value)
            with self.assertRaises(ValueError):assets.validate_native_beam(corrupt,beam['metadata'])
        metadata=bytearray(beam['metadata']);metadata[312]=1
        with self.assertRaises(assets.TagRushAssetError):assets.validate_native_beam(beam['resource'],metadata)


if __name__ == '__main__': unittest.main()
