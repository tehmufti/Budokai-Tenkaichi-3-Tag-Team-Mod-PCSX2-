"""Selectable gait curves preserve native clip ownership, cadence and rematches."""
import support
import base64
import hashlib
import math
import struct
import unittest
import zlib

import ground_clips as clips
import ground_motion as motion
import ground_motion_cmu as cmu
import ground_locomotion as ground
import ground_root_motion as root
import model_animations as animations
import mod_settings
from gait_fixture import Builder, MODELS, ACTORS, machine, speed, clock_step, decode, native_clip, set_flag


class MotionStyleTests(unittest.TestCase):
    def test_approved_samples_are_normalized_finite_and_hash_verified(self):
        for name, data in cmu.DATA.items():
            raw = zlib.decompress(base64.b85decode(data))
            self.assertEqual(hashlib.sha256(raw).hexdigest(), cmu.SAMPLE_SHA256[name])
            rows = motion.samples(name)
            self.assertEqual(len(rows), cmu.COUNTS[name])
            for xyz, rotations in rows:
                self.assertTrue(all(math.isfinite(v) and abs(v) < .5 for v in xyz))
                for q in rotations:
                    self.assertAlmostEqual(sum(v*v for v in q), 1., places=5)

    def test_classic_keeps_previous_exact_bytes(self):
        self.assertEqual(clips.digest(), '6192e3a6cd1d797e5e0f02a56ccc33f41e1042206a55f9f955dc107c80ebbe6b')

    def test_selected_styles_roundtrip_and_preserve_nonwalking_clips(self):
        previous = clips.build_set()
        for style in ('natural', 'fighter'):
            built = clips.build_set(style=style)
            # Both profiles get the selected style, scaled by their own body.
            self.assertEqual(built, clips.build_set('female', style))
            for key, packed in built.items():
                decoded = animations.decompress_animation(packed)
                self.assertLessEqual(len(decoded), 0xC000)
                self.assertEqual(clips.compress_literal(decoded), packed)
                if key[1] in clips.SIDESTEP or key[0] == clips.STOP:
                    if key[1] in clips.SIDESTEP or key[1] in (8, 9):
                        self.assertEqual(packed, previous[key])
                        continue
                self.assertNotEqual(packed, previous[key])
                clip = animations.AnimationClip.from_decoded(key[1], decoded)
                for track in clip.tracks:
                    self.assertEqual(track.keys[0], track.keys[-1])
                    self.assertTrue(all(k.translation is None for k in track.keys) or track.bone_id == 2)
                for t in (0, clip.frame_count//3, clip.frame_count):
                    xyz, rotations = clips.authored_pose(*key, t, style=style)
                    actual = clip.evaluate(t)
                    for b in clips.TRACKED:
                        self.assertGreater(abs(sum(a*b for a, b in zip(rotations[b], actual[b].rotation))), 1-1e-7)
                    for a, b in zip(xyz, actual[2].translation):
                        self.assertAlmostEqual(a, b, places=6)

    def test_distinct_layouts_fit_and_root_curves_cannot_collide(self):
        digests = set()
        for style in motion.STYLES:
            digests.add(clips.digest(clips.build_set(style=style)))
            _, _, pieces = ground.layout_profiles(style)
            self.assertLessEqual(pieces[-1][0]+len(pieces[-1][1]), ground.CLIPS_END)
            rows = root.data_blocks([clips.build_set(p, style) for p in ('male', 'female')])
            self.assertLessEqual(rows[-1][0]+len(rows[-1][1]), root.END)
        self.assertEqual(len(digests), 3)

    def test_default_velocity_reproduces_approved_cycle_cadence(self):
        periods = {'natural': {'walk': 1.24, 'run': .77}, 'fighter': {'walk': 1.10, 'run': .68}}
        for style in periods:
            config = struct.unpack('<I5fI2fI2I', ground.config_bytes(dict(mod_settings.DEFAULTS,
                ground_motion_style=style, ground_run_speed_percent=100, ground_walk_speed_percent=40)))
            for gait, field in (('run', 1), ('walk', 2)):
                velocity = config[field]*4.074*ground.ACTOR_HZ
                self.assertAlmostEqual(velocity, motion.source_speed(gait, style), places=4)
                cycle = motion.stance_travel(gait, style)*motion.REFERENCE/velocity
                self.assertAlmostEqual(cycle, periods[style][gait], places=5)

    @unittest.skipUnless(support.HAS_NATIVE, "Provide this adapter native ELF for native animation instructions")
    def test_style_cadence_uses_actual_velocity_without_touching_native_rate(self):
        for style in ('natural', 'fighter'):
            c = machine()
            c.write(ground.CONSTS, ground.consts_bytes(style))
            c.write(ground.CONTROL+12, ground.config_bytes(dict(mod_settings.DEFAULTS,
                ground_running=True, ground_motion_style=style)))
            c.w(ground.ACTORS+ground.R['base_src'], 1)
            c.w(ground.ACTORS+ground.R['lean_src'], 1)
            before = c.fr(MODELS[0]+0xC78)
            speed(c, 0)
            expected = c.fr(ground.ACTORS+ground.R['step'])
            self.assertGreater(expected, 0.)
            self.assertAlmostEqual(c.fr(MODELS[0]+0xC78), before+expected, places=5)
            self.assertEqual(c.fr(MODELS[0]+0xC80), 2.)
            clock_step(c, 0)
            self.assertAlmostEqual(c.fr(MODELS[0]+0xC78), before+expected+2., places=5)

    @unittest.skipUnless(support.HAS_NATIVE, "Provide this adapter native ELF for native animation instructions")
    def test_guest_decoder_selects_new_curves_and_preserves_attacks_and_flight(self):
        for style in ('natural', 'fighter'):
            c = machine()
            male, female, pieces = ground.layout_profiles(style)
            for p, data in pieces: c.write(p, data)
            for directory, mapping in ((ground.DIRECTORY, male), (ground.FEMALE_DIRECTORY, female)):
                c.write(directory, ground.table_bytes(mapping)[0])
            for character in (0, motion.female_characters(ground.BT4)[0]):
                c.w(MODELS[0]+12, character)
                for gait in (clips.RUN, clips.WALK):
                    c.w(ground.ACTORS+ground.R['gait'], gait)
                    address, _, _ = decode(c, MODELS[0], 3)
                    expected = clips.build_set(style=style)[gait, 3]
                    self.assertEqual(c.read(address, len(expected)), expected)
            c.w(ACTORS[0]+0x948, 55)
            self.assertEqual(decode(c, MODELS[0], 55)[0], native_clip(0, 55))
            c.w(ACTORS[0]+0x948, 13)
            set_flag(c, ACTORS[0], 0xE)
            self.assertEqual(decode(c, MODELS[0], 3)[0], native_clip(0, 3))

    @unittest.skipUnless(support.HAS_NATIVE, "Provide this adapter native ELF for native animation instructions")
    def test_guest_root_retargets_new_curves_after_native_conversion(self):
        from gait_root_fixture import prepared, BIND, SENTINEL
        for style in ('natural', 'fighter'):
            built = clips.build_set(style=style)
            for character in (0, 12, 56):
                for gait in (clips.WALK, clips.RUN):
                    c = prepared(char=character)
                    decoded = clips.decompress_literal(built[gait, 3])
                    at = struct.unpack_from('<H', decoded, 10)[0]*4
                    count = struct.unpack_from('<H', decoded, at+2)[0]
                    expected = [struct.unpack_from('<3f', decoded, at+4+i*24) for i in range(count)]
                    c.write(c.dest, decoded)
                    for p, data in root.data_blocks(built): c.write(p, data)
                    for i in range(count): c.write(c.dest+at+4+i*24, struct.pack('<3f', 90., 91., 92.))
                    c.w(ground.ACTORS+ground.R['base_src'], 1+gait)
                    c.run(root.SITE, stops=(SENTINEL,))
                    for i, normalized in enumerate(expected):
                        actual = struct.unpack('<3f', c.read(c.dest+at+4+i*24, 12))
                        for x, b, delta in zip(actual, BIND, normalized):
                            self.assertAlmostEqual(x, b+delta*ground.legs()[character], places=5)

    def test_invalid_style_rejected(self):
        with self.assertRaises(ValueError): clips.build_set(style='unknown')
        with self.assertRaises(ValueError): motion.stance_travel('walk', 'unknown')


@unittest.skipUnless(support.HAS_NATIVE, "Provide this adapter native ELF for guarded installation checks")
class StyleInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Builder.setUpClass()
        cls.ram = Builder.ram

    def test_off_never_installs_a_style(self):
        for style in motion.STYLES:
            settings = dict(mod_settings.DEFAULTS, ground_running=False, ground_motion_style=style)
            self.assertEqual(ground.build_memory(bytearray(16), settings), {'blocks': []})

    def test_rematch_keeps_installed_style_and_accepts_other_settings(self):
        for style in motion.STYLES:
            ram = bytearray(self.ram)
            settings = dict(mod_settings.DEFAULTS, ground_running=True, ground_motion_style=style)
            first = ground.build_memory(ram, settings)
            self.assertEqual(first['motion_style'], style)
            for block in first['blocks']:
                p, data = block['address'], bytes.fromhex(block['data_hex'])
                ram[p:p+len(data)] = data
            changed = ground.build_memory(ram, dict(settings, ground_motion_style='fighter', ground_run_speed_percent=120))
            self.assertEqual(changed['motion_style'], style)
            self.assertEqual([b['address'] for b in changed['blocks']], [ground.CONTROL+12])
            style_id = struct.unpack_from('<I', bytes.fromhex(changed['blocks'][0]['data_hex']), 40)[0]
            self.assertEqual(style_id, motion.STYLES.index(style))
            self.assertEqual(ground.build_memory(ram, settings)['blocks'], [])


if __name__ == '__main__':
    unittest.main()
