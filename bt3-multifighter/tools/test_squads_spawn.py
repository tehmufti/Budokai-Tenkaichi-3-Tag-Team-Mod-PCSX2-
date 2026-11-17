"""Team bases of a Team Battle with three to five teams, on every stage of every scanned disc.

The planner only proposes spots; the game itself still refuses a spot without floor, inside geometry or inside
another fighter. These tests cover what can be known without the stage's collision: every team base is inside the
arena, no two bases are inside each other, the first-choice spots of all fighters are apart, and every fighter keeps
spots between the two authored anchors as a last resort (where the ordinary two-team match stands).
"""
import itertools
import json
import math
import unittest
from pathlib import Path

import battle_mode_policy as policy
import spawn_placement as spawn

PROFILES = Path(__file__).resolve().parents[2]/'compatibility-profiles'
SIZES = ((1, 1, 1), (2, 2, 2), (3, 3, 3), (4, 3, 3), (3, 2, 1), (1, 1, 1, 1), (2, 2, 2, 2), (3, 3, 2, 2), (4, 2, 2, 2),
         (1, 1, 1, 1, 1), (2, 2, 2, 2, 2), (2, 2, 2, 2, 1), (3, 2, 2, 2, 1))
RADIUS = 12.0          # an ordinary fighter's body radius
MARGIN = 100.0         # arena_bounds.read keeps this far from the arena's edge


def stages():
    """(disc, stage id, variant, anchors, usable radius) of every structurally valid stage of every profile."""
    out = []
    if not PROFILES.is_dir(): return out
    for path in sorted(PROFILES.glob('*.json')):
        try: profile = json.loads(path.read_text(encoding='utf-8'))
        except ValueError: continue
        if not isinstance(profile.get('stages'), list): continue
        serial = (profile.get('identity') or {}).get('serial', path.stem[:8])
        for stage in profile['stages']:
            for name, variant in stage.get('variants', {}).items():
                spawns = variant.get('spawns') or []; arena = variant.get('arena') or {}
                if not variant.get('structurally_valid') or len(spawns) < 2 or not arena.get('horizontal_limit'): continue
                # Raw authored coordinates; the game flips Z, which changes no distance used here.
                anchors = [(s['position'][0], -s['position'][2]) for s in spawns[:2]]
                if not 1 <= math.dist(*anchors) <= 10000: continue
                out.append((serial, stage['stage_id'], name, anchors, arena['horizontal_limit']-MARGIN))
    return out


STAGES = stages()


def plan(anchors, sizes, limit, radius=RADIUS):
    squads = policy.squad_layout(sizes)
    radii = [radius]*policy.MAX_ACTORS
    return squads, spawn.candidate_plan(anchors, radii, squads.present(), squads, limit=limit)


def roomy(anchors, limit, result, sizes, radius=RADIUS):
    """The arena holds the planned circle of bases without pulling a base back."""
    free = plan(anchors, sizes, None, radius)[1]['bases']
    return all(math.dist(free[team], base) < 1e-3 for team, base in result['bases'].items())


@unittest.skipUnless(STAGES, 'no scanned stage profiles beside this tree')
class SquadSpawnTests(unittest.TestCase):
    def test_profiles_cover_the_supported_discs(self):
        discs = {serial for serial, *_ in STAGES}
        self.assertGreaterEqual(len(STAGES), 70)
        self.assertTrue(discs & {'SLUS_216.78', 'SLES_549.45', 'SLPS_258.15', 'SLUS_219.78'}, discs)

    def test_every_base_is_inside_the_arena_on_every_stage(self):
        for serial, stage, variant, anchors, limit in STAGES:
            for sizes in SIZES:
                squads, result = plan(anchors, sizes, limit)
                farthest = max(math.hypot(*a) for a in anchors)
                for team, (x, z) in result['bases'].items():
                    self.assertTrue(math.isfinite(x) and math.isfinite(z))
                    # Never beyond the usable arena, except where the authored anchors themselves already are.
                    self.assertLessEqual(math.hypot(x, z), max(limit, farthest)+1e-3, (serial, stage, variant, sizes, team))

    def test_bases_are_not_inside_each_other(self):
        tight = set(); checked = 0
        for serial, stage, variant, anchors, limit in STAGES:
            for sizes in SIZES:
                squads, result = plan(anchors, sizes, limit)
                apart = min(math.dist(a, b) for a, b in itertools.combinations(result['bases'].values(), 2))
                if apart+1e-3 >= result['minimum_opposing']:
                    checked += 1; continue
                # Only a stage too small for the circle may pull bases together; the two-team spots remain.
                self.assertFalse(roomy(anchors, limit, result, sizes), (serial, stage, variant, sizes, apart))
                tight.add((serial, stage, variant))
        self.assertGreater(checked, len(STAGES)*len(SIZES)*0.6)
        # The original game's arenas all hold five teams.
        self.assertFalse([entry for entry in tight if entry[0] != 'SLUS_219.78'], sorted(tight)[:8])

    def test_first_choice_spots_are_apart_wherever_the_arena_has_room(self):
        for serial, stage, variant, anchors, limit in STAGES:
            for sizes in SIZES:
                squads, result = plan(anchors, sizes, limit)
                if not roomy(anchors, limit, result, sizes): continue
                first = {i: spots[0] for i, spots in enumerate(result['candidates']) if spots}
                self.assertEqual(set(first), set(i for i in range(policy.MAX_ACTORS) if squads.present() >> i & 1))
                for (i, a), (j, b) in itertools.combinations(first.items(), 2):
                    self.assertGreaterEqual(math.dist(a, b), 2*RADIUS, (serial, stage, variant, sizes, i, j))
                    if squads.team_of[i] != squads.team_of[j]:
                        self.assertGreaterEqual(math.dist(a, b), result['minimum_opposing']-1e-3, (serial, stage, variant, sizes, i, j))

    def test_every_fighter_keeps_spots_between_the_authored_anchors(self):
        for serial, stage, variant, anchors, limit in STAGES:
            gap = math.dist(*anchors)
            for sizes in SIZES:
                squads, result = plan(anchors, sizes, limit)
                for i, spots in enumerate(result['candidates']):
                    if not squads.present() >> i & 1:
                        self.assertEqual(spots, []); continue
                    self.assertLessEqual(len(spots), spawn.MAX_CANDIDATES)
                    self.assertTrue(all(math.isfinite(v) for spot in spots for v in spot))
                    # The last resort: on the line between the two authored anchors, where two teams stand.
                    x, z = spots[-7]
                    along = ((x-anchors[0][0])*(anchors[1][0]-anchors[0][0])+(z-anchors[0][1])*(anchors[1][1]-anchors[0][1]))/gap
                    self.assertTrue(-1e-3 <= along <= gap+1e-3, (serial, stage, variant, sizes, i))

    def test_giants_keep_their_distance(self):
        for serial, stage, variant, anchors, limit in STAGES[::7]:
            squads, result = plan(anchors, (2, 2, 2, 2, 2), limit, radius=40.0)
            if not roomy(anchors, limit, result, (2, 2, 2, 2, 2), 40.0): continue
            first = [spots[0] for spots in result['candidates'] if spots]
            for a, b in itertools.combinations(first, 2):
                self.assertGreaterEqual(math.dist(a, b), 80.0, (serial, stage, variant))


if __name__ == '__main__':
    unittest.main()
