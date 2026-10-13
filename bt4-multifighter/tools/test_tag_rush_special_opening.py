"""Per-tick opening pose guard for the Early Goku/Piccolo restraint.

Every 30 Hz tick of the acquisition phases (0 and 1) is evaluated offline for
the three reviewed body sizes. Each tick decodes the real crops exactly as the
poser preview does, runs the emitted native pose helper (FIT) at the staged
roots (including the phase-0 settle glide), and builds both actors' world
bones with the poser's FK. The October 12 regression showed Goku upright with
crossed arms, hips over the victim's head, while the victim faced the camera.
"""
# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import math
import struct
import unittest
from pathlib import Path

import numpy as np

import tag_rush_special_pair as special

GLIDE = 200.0          # staged settle start: below the hold (native Y is down)
SIZES = (('small', 25), ('normal', 27), ('large', 133))
TORSO = (3, 16, 17)
UP = np.array((0., -1., 0.))
LANE = np.array((0., 0., -1.))   # Piccolo's firing lane from the held pair


def _iso():
    name = ('SLUS_219.78.DBZBT4B14REV2ENG.iso' if 'bt4' in str(Path(__file__).resolve().parent)
            else 'Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso')
    return Path(__file__).resolve().parents[2] / 'games' / name


def _unit(x):
    n = np.linalg.norm(x)
    return x / n if n > 1e-9 else x


class Opening:
    """Crops are decoded once per role/phase; FIT runs per tick in SceneCpu."""

    def __init__(self, iso):
        import model_assets as models
        import tag_rush_assets as assets
        import tag_rush_full_nelson as ik
        self.ik = ik
        self.donor = assets.read_skeleton(iso, special.DONOR)
        self.sources = special.read_sources(iso)
        self.db = {r['bone']: r['translation'] for r in self.donor['rows']}
        self.shift = ik.sub(self.sources[356].evaluate(24)[2].translation, self.db[2])
        characters = (0,) + tuple(c for _, c in SIZES)
        self.assets = {c: models.load_character(iso, c) for c in characters}
        self.bindings = {c: assets.read_skeleton(iso, c) for c in characters}
        self.clips = {}

    def clip(self, role, phase):
        from model_animations import AnimationClip
        key = (role, phase)
        if key not in self.clips:
            lead, victim, start, end, frames = special.SEGMENTS[phase]
            raw = special._crop(self.sources[lead if role == 0 else victim], start, end, frames,
                                self.shift if role == 0 else None, role=role, phase=phase)
            self.clips[key] = AnimationClip.from_decoded(0, raw)
        return self.clips[key]

    def pose(self, character, role, phase, frame):
        """The poser preview's retarget of one decoded crop frame."""
        from model_animations import BoneTransform
        ik, binding = self.ik, self.bindings[character]
        tb = {r['bone']: r['translation'] for r in binding['rows']}
        pose = {}
        for bone, t in self.clip(role, phase).evaluate(frame).items():
            xyz = t.translation
            if xyz is not None and bone in self.db and bone in tb:
                d = list(ik.sub(xyz, self.db[bone]))
                d[1] *= binding['height'] / self.donor['height']
                xyz = ik.add(d, tb[bone])
            pose[bone] = BoneTransform(xyz, t.rotation)
        result = {}
        for b in self.assets[character].bones:
            t = pose.get(b.native_id)
            result[b.native_id] = BoneTransform(
                tuple(t.translation) if t is not None and t.translation is not None else tuple(b.bind_translation),
                ik.qnorm(t.rotation) if t is not None else (0., 0., 0., 1.))
        return result

    def tick(self, character, phase, frame, settle):
        """World bones {0: holder, 1: victim} after the native helper for this tick."""
        import tag_rush_full_nelson_native as native
        import tag_rush_full_nelson_profiles as profiles
        import tag_rush_scene as scene
        import tag_rush_staging as staging
        import tag_team_rush as tag
        from model_animations import BoneTransform
        from test_tag_rush_scene import SceneCpu
        characters = (0, character)
        assets = tuple(self.assets[c] for c in characters)
        poses = (self.pose(0, 0, phase, frame), self.pose(character, 2, phase, frame))
        cpu = SceneCpu({'segments': [dict(address=p, data_hex=b.hex()) for p, b in native.pieces()]})
        rows, models, actors = (0x1600000, 0x1600400), (0x1800000, 0x1804000), (0x1900000, 0x1904000)
        # staging.TICK has already placed both roots on the settle glide; the
        # pair's records share one mark, so both roots start at the same point.
        root = (0., GLIDE * (1. - settle), 0.)
        state = {}

        def yawq(index):
            yaw = math.radians(special.records()[phase][4 if index == 0 else 6][3]) + math.pi
            return (0., math.sin(yaw / 2), 0., math.cos(yaw / 2))

        def world(index, pose, origin):
            m = profiles.matrix(yawq(index))
            m[:3, 3] = origin
            return {b: m @ v for b, v in profiles.world_matrices(assets[index].bones, pose).items()}

        for index, asset in enumerate(assets):
            cpu.w(rows[index] + scene.R['model'], models[index])
            cpu.w(rows[index] + scene.R['actor'], actors[index])
            cpu.w(models[index] + 12, asset.character)
            cpu.fw(models[index] + 2332, self.bindings[characters[index]]['height'])
            if phase == 0:
                cpu.w(rows[index] + staging.SETTLE, 1)
            for bone in asset.bones:
                pointer = 0x2000000 + index * 0x10000 + bone.native_id * 256
                cpu.w(models[index] + 3436 + bone.native_id * 4, pointer)
                t = poses[index][bone.native_id]
                cpu.write(pointer + 144, struct.pack('<3f', *t.translation))
                cpu.write(pointer + 160, struct.pack('<4f', *t.rotation))
            cpu.write(models[index] + 2384, struct.pack('<4f', *root, 1.))
            cpu.write(actors[index] + 16, struct.pack('<4f', *root, 1.))

        def update(machine):
            index = models.index(machine.r[4])
            pose = {}
            for bone in assets[index].bones:
                pointer = machine.u(models[index] + 3436 + bone.native_id * 4)
                pose[bone.native_id] = BoneTransform(struct.unpack('<3f', machine.read(pointer + 144, 12)),
                                                   struct.unpack('<4f', machine.read(pointer + 160, 16)))
            state[index] = world(index, pose, struct.unpack('<3f', machine.read(models[index] + 2384, 12)))
            for bone, value in state[index].items():
                pointer = machine.u(models[index] + 3436 + bone * 4)
                machine.write(pointer + 16, struct.pack('<16f', *value.T.flat))

        cpu.callbacks[native.A(0x1DC298)] = lambda m: m.r.__setitem__(2, m.r[4] + 16)
        cpu.callbacks[native.A(0x1D7198)] = lambda m: m.write(models[actors.index(m.r[4])] + 2384,
                                                             m.read(m.r[4] + 16, 16))
        cpu.callbacks[native.A(0x24E3F8)] = update
        cpu.callbacks[native.A(0x1D70E8)] = lambda m: None
        cpu.callbacks[native.A(0x1DABE8)] = lambda m: None
        # As in the game, each model's world matrices exist before the helper runs.
        for index in range(2):
            cpu.r[4] = models[index]
            update(cpu)
        decoded = dict(state)
        state.clear()
        cpu.w(scene.STATE + scene.S['phase'], phase)
        cpu.w(scene.STATE + scene.S['ticks'], round(frame / 2) + 1)
        cpu.w(tag.CONTROL + tag.C['variant'], special.VARIANT)
        cpu.r[4:6], cpu.r[31] = rows, 0xFEED0000
        cpu.run(native.FIT)
        if cpu.r[2] != 1:
            raise AssertionError('native pose helper rejected the opening tick')
        for index in range(2):
            if index not in state:   # the helper left this decoded pose in place
                state[index] = decoded[index]
        return state


def measures(state):
    """Scalar facts about one tick; native Y is down."""
    h, v = ({b: m[:3, 3] for b, m in state[i].items()} for i in (0, 1))
    flat = np.array((1., 0., 1.))

    def forward(p):
        # Chest normal from the shoulder line and spine (native Y down).
        return _unit(np.cross(p[46] - p[3], p[18] - p[32]) * flat)

    vf = forward(v)
    chest_h = (h[18] + h[32]) / 2
    side_h = _unit(h[18] - h[32])
    width_h = np.linalg.norm(h[18] - h[32])
    spine = _unit(h[46] - h[3])
    return dict(
        # >0: holder pelvis in front of the victim's chest (the wrong side)
        pelvis_front=float(np.dot(h[3] - v[17], vf)),
        # >0: holder pelvis above the victim's head (native Y is down)
        pelvis_over_head=float(v[47][1] - h[3][1]),
        # >0: wrist past the holder's chest centre, in shoulder widths
        left_cross=float(-np.dot(h[21] - chest_h, side_h) / width_h),
        right_cross=float(np.dot(h[35] - chest_h, side_h) / width_h),
        torso_gap=float(min(np.linalg.norm(h[a] - v[b]) for a in TORSO for b in (3, 16, 17, 46, 47))),
        victim_width=float(np.linalg.norm(v[18] - v[32])),
        spine_tilt=math.degrees(math.acos(max(-1., min(1., float(np.dot(spine, UP)))))),
        victim_away=float(np.dot(vf, _unit((v[17] - h[17]) * flat))),
        victim_lane=float(np.dot(vf, LANE)),
    )


CHECKS = (
    ('holder pelvis in front of the victim', 'pelvis_front', lambda s: s['pelvis_front'] > 2.),
    ('holder pelvis above the victim head', 'pelvis_over_head', lambda s: s['pelvis_over_head'] > 0.),
    ('left wrist crossed', 'left_cross', lambda s: s['left_cross'] > .25),
    ('right wrist crossed', 'right_cross', lambda s: s['right_cross'] > .25),
    ('torsos interpenetrate', 'torso_gap', lambda s: s['torso_gap'] < .25 * s['victim_width']),
    ('holder spine not upright', 'spine_tilt', lambda s: s['spine_tilt'] > 50.),
    ('victim chest faces the holder', 'victim_away', lambda s: s['victim_away'] < .5),
    ('victim not facing the firing lane', 'victim_lane', lambda s: s['victim_lane'] < .7),
)


def ticks():
    """Every 30 Hz tick of phases 0 and 1 (2 source frames per tick)."""
    settle_frames = getattr(special, 'APPROACH_FRAMES', 0)
    for phase in (0, 1):
        for frame in range(0, special.SEGMENTS[phase][4] + 1, 2):
            g = 1. if phase or not settle_frames else min(1., frame / settle_frames)
            yield phase, frame, g * g * (3 - 2 * g)


def failures(opening, sizes=SIZES):
    result = []
    for name, character in sizes:
        for phase, frame, settle in ticks():
            s = measures(opening.tick(character, phase, frame, settle))
            result += [f'{name} phase{phase} frame{frame}: {label} ({s[key]:.2f})'
                       for label, key, bad in CHECKS if bad(s)]
    return result


class OpeningPoseGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if 'bt4' in str(Path(__file__).resolve().parent):
            # The reviewed size profiles (and the poser) use the USA BT3 bodies;
            # BT4 shares the same helper code, checked in the BT3 tree.
            raise unittest.SkipTest('Opening geometry is reviewed on the USA BT3 bodies')
        iso = _iso()
        if not iso.is_file():
            raise unittest.SkipTest('Owned local disc unavailable')
        cls.opening = Opening(iso)

    def test_locked_hold_endpoint_satisfies_the_guard(self):
        # The user's reviewed grip (poser phase2/frame20) must pass every check,
        # so the thresholds cannot drift away from the real hold.
        for name, character in SIZES:
            s = measures(self.opening.tick(character, 2, 20, 1.))
            bad = [label for label, key, test in CHECKS if test(s)]
            self.assertEqual(bad, [], (name, s))

    def test_every_opening_tick_is_a_rear_grab_with_open_arms_and_a_fixed_victim(self):
        found = failures(self.opening)
        self.assertEqual(found, [], '\n'.join(found[:40]) + f'\n({len(found)} failures)')


if __name__ == '__main__':
    unittest.main()
