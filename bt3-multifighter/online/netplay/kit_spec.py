"""The online match spec of kit 2.0: what the host built in the lobby, as canonical JSON every PC can check.

Spec v2 (canonical: sort_keys, separators (',', ':'); spec_sha = sha256 of that text):
  {"schema":"ttm-online-match","v":2,"type":"versus","family":"bt3","disc":"bt3-usa","tables_sha256":...,
   "kit":"2.0.0","mod_build":...,"mode":"teams"|"ffa",
   "teams":[[{"character":29,"costume":1,"slot":0}, {"character":25,"costume":0,"slot":null}, ...], [...]],
   "stage":6,"bgm":0,
   "native":{"time":240,"com":2,"referee":2,"destructible":true},
   "gameplay":{the host's gameplay settings that differ from the mod's defaults (kit_settings)},
   "services":{"cpu_transform":false,"fusion_timer":false,"body_change":false}}
type: 'versus' (a match: intro, fight, result, then Retry / Return to lobby) or 'hub' (the in-level hub: free roam
  with consent damage, respawn, a scoreboard and challenges; tools/hub_mode.py installed into the match; always
  free-for-all with infinite Duel Time, so a K.O. never ends it).
mode 'teams': exactly two teams of 1..5 fighters each, independent sizes; 1 v 1 is prepared on the mod's free-for-all engine, where both fighters are enemies as in a duel; mode 'ffa':
  free-for-all, every fighter for himself, 2..10 fighters given as the two Team Select columns (independent sizes). The mod has no third team: 3+ teams are refused with a reason.
At most 10 fighters (the 5 v 5 engine). A fighter's "slot" is the input slot of the human who plays it, or null for a
CPU fighter. Kit 2.1: ANY fighter can be a player (up to 10 humans); the slot is the fighter's physical index in the
mod's engine, slot = 2 x position + column (0/1: the side leaders, 2..9 the other fighters, side = slot & 1).
bgm: the battle music track (0..23), resolved before a spec exists (a spec never holds 'random').
"""
import hashlib
import json
import random
import struct
import zipfile

SCHEMA, V, TYPE = 'ttm-online-match', 2, 'versus'
TYPES = ('versus', 'hub')
import kit_paths
from native_map import A
import kit_adapter
DISC = kit_paths.ADAPTER
FAMILY = 'bt4' if DISC.startswith('bt4') else 'bt3'
MODES = ('teams', 'ffa')
TIMES = (60, 90, 180, 240, 0)                     # save-word order; 0 = infinite
COM_CODES = (0, 6, 13, 21, 29)                    # member +12 per CPU level 0..4
REFEREES = ('Ox King', 'Videl', 'Supreme Kai', 'Shenron', 'Announcer 1', 'Announcer 2', 'Announcer 3')
TEAM_MAX, FIGHTERS_MAX = 5, 10
HUMAN_SLOTS = tuple(range(10))                    # kit 2.1: every fighter (slot = 2 x position + column)
STAGE_IDS = range(kit_adapter.stage_count())
BGM_TRACKS = range(24)
DEFAULT_BGM = 0
SERVICES = ('cpu_transform', 'fusion_timer', 'body_change')
DEFAULT_NATIVE = dict(time=240, com=2, referee=2, destructible=True)
SCENE = A(0x331DC8)
SIDE_STRIDE, MEMBER_STRIDE = 624, 100
MODE, COUNT = 0xD8080, 0xD8084
KIT = '2.2.0'


def canonical(spec):
    return json.dumps(spec, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def spec_sha(spec):
    return hashlib.sha256(canonical(spec).encode('ascii')).hexdigest()


def scene_time(seconds):
    """SCENE+0x10 for a Duel Time (seconds, 0 = infinite)."""
    return (TIMES.index(seconds) + 1) % 5


def time_of_scene(word):
    return TIMES[(word - 1) % 5]


def bgm_ok(value):
    return isinstance(value, int) and not isinstance(value, bool) and value in BGM_TRACKS


def fighter(character, costume, slot=None):
    return dict(character=int(character), costume=int(costume), slot=None if slot is None else int(slot))


def make(*, tables_sha256, mode='teams', teams, stage, bgm=DEFAULT_BGM, native=None, gameplay=None, services=None,
         kit=KIT, mod_build=None, type=TYPE):
    """teams: [[(character, costume, slot or None), ...], [...]] (two columns)."""
    n = dict(DEFAULT_NATIVE)
    n.update({k: v for k, v in (native or {}).items() if k in DEFAULT_NATIVE})
    return dict(schema=SCHEMA, v=V, type=type, family=FAMILY, disc=DISC, tables_sha256=tables_sha256,
                mod_build=mod_build, kit=kit, mode=mode,
                teams=[[fighter(*m) if not isinstance(m, dict) else fighter(m['character'], m['costume'],
                                                                              m.get('slot'))
                        for m in team] for team in teams],
                stage=stage, bgm=bgm, native=n, gameplay=dict(gameplay or {}),
                services={k: bool((services or {}).get(k, False)) for k in SERVICES})


def humans(spec):
    """[(slot, column, index)] of the human fighters, by slot."""
    out = []
    for t, team in enumerate(spec['teams']):
        for i, f in enumerate(team):
            if f.get('slot') is not None:
                out.append((f['slot'], t, i))
    return sorted(out)


def slot_of(column, index):
    """The input slot (= the engine's physical index) of a column's fighter."""
    return 2 * index + column


def slot_mask(spec):
    return sum(1 << s for s, _, _ in humans(spec))


def engine_mode(spec):
    """'teams' or 'ffa': how the host's game prepares it (1 v 1 runs on the free-for-all engine)."""
    if spec['mode'] == 'ffa':
        return 'ffa'
    return 'ffa' if [len(t) for t in spec['teams']] == [1, 1] else 'teams'


def fighter_problems(member, catalog, where):
    out = []
    try:
        c, k = int(member['character']), int(member['costume'])
    except (TypeError, ValueError, KeyError):
        return [f'{where}: not a fighter']
    if c not in catalog.chars or not catalog.chars[c].get('selectable'):
        out.append(f'{where}: character {c} cannot be chosen')
    elif not 0 <= k < catalog.costumes(c):
        out.append(f'{where}: {catalog.name(c)} has colours 1..{catalog.costumes(c)} (got {k + 1})')
    return out


def layout_problems(mode, sizes):
    """[text] for the team sizes of a mode (two columns): the lobby greys out what this says."""
    if mode not in MODES:
        return [f'mode {mode!r} is not teams or free-for-all']
    if len(sizes) != 2:
        return ['the Tag Team Mod has two teams (or free-for-all): three or more teams cannot be played']
    if any(type(s) is not int or s < 1 for s in sizes):
        return ['each column needs between one and five fighters']
    total = sum(sizes)
    if total > FIGHTERS_MAX:
        return [f'at most {FIGHTERS_MAX} fighters at once (got {total})']
    if any(s > TEAM_MAX for s in sizes):
        return [f'at most {TEAM_MAX} fighters in a column']
    if mode == 'teams' and min(sizes) < 1:
        return ['each team needs at least one fighter']
    if mode == 'ffa' and (total < 2 or min(sizes) < 1):
        return ['free-for-all needs at least two fighters']
    return []


def native_problems(native):
    out = []
    if native.get('time') not in TIMES:
        out.append(f'Duel Time {native.get("time")} is not one of 60, 90, 180, 240, infinite')
    if native.get('com') not in range(5):
        out.append(f'CPU level {native.get("com")} is not 0..4')
    if native.get('referee') not in range(len(REFEREES)):
        out.append(f'referee {native.get("referee")} is not 0..6')
    if not isinstance(native.get('destructible'), bool):
        out.append('destructible stage must be on or off')
    return out


def human_problems(spec):
    out = []
    seen = set()
    for t, team in enumerate(spec['teams']):
        for i, f in enumerate(team):
            s = f.get('slot')
            if s is None:
                continue
            if s not in HUMAN_SLOTS:
                out.append(f'team {t + 1} fighter {i + 1}: player slot {s} is not offered')
            elif s in seen:
                out.append(f'player slot {s} is used twice')
            elif s != slot_of(t, i):
                out.append(f'team {t + 1} fighter {i + 1}: its player slot is {slot_of(t, i)}, not {s}')
            seen.add(s)
    return out


def problems(spec, catalog, allowed_services=()):
    """[text] for a whole spec (empty when valid). allowed_services: the services this kit can run online."""
    out = []
    if not isinstance(spec, dict):
        return ['not a match spec']
    for key, want in (('schema', SCHEMA), ('v', V), ('family', FAMILY), ('disc', DISC)):
        if spec.get(key) != want:
            out.append(f'{key} is {spec.get(key)!r}, expected {want!r}')
    if spec.get('type') not in TYPES:
        out.append(f'match type {spec.get("type")!r} is not versus or hub')
    elif spec['type'] == 'hub':
        if spec.get('mode') != 'ffa':
            out.append('the hub is free-for-all')
        if (spec.get('native') or {}).get('time') != 0:
            out.append('the hub needs an infinite Duel Time')
    if spec.get('tables_sha256') != catalog.c.get('tables_sha256'):
        out.append('the fighter tables of the ISOs differ')
    teams = spec.get('teams')
    if not isinstance(teams, list) or not all(isinstance(t, list) for t in teams):
        return out + ['the teams are malformed']
    out += layout_problems(spec.get('mode'), [len(t) for t in teams])
    for t, team in enumerate(teams):
        for i, f in enumerate(team):
            if not isinstance(f, dict):
                out.append(f'team {t + 1} fighter {i + 1}: malformed')
                continue
            out += fighter_problems(f, catalog, f'team {t + 1} fighter {i + 1}')
    if not out:
        out += human_problems(spec)
    if spec.get('stage') not in STAGE_IDS:
        out.append(f'stage {spec.get("stage")} is not 0..{len(STAGE_IDS) - 1}')
    if not bgm_ok(spec.get('bgm')):
        out.append(f'music {spec.get("bgm")} is not a track 1..24')
    out += native_problems(spec.get('native') or {})
    import kit_settings
    gameplay = spec.get('gameplay')
    out += kit_settings.gameplay_problems(gameplay if isinstance(gameplay, dict) else None)
    services = spec.get('services') or {}
    if set(services) != set(SERVICES):
        out.append('the host services are malformed')
    else:
        for name, on in services.items():
            if on and name not in allowed_services:
                out.append(f'the service {name} is not available online')
    return out


def validate(spec, catalog, allowed_services=()):
    """KitError TTM-NET-29 unless the spec is playable."""
    found = problems(spec, catalog, allowed_services)
    if found:
        from kit_codes import KitError
        raise KitError('TTM-NET-29', what='; '.join(found[:6]))
    return spec


# ---- random choices (resolved before a spec exists; a spec never holds a random value) -------------------------------
def random_fighter(catalog, rng=None):
    rng = rng or random.SystemRandom()
    c = rng.choice(catalog.selectable)
    return c, rng.randrange(max(1, catalog.costumes(c)))


def random_team(catalog, size, rng=None):
    return [random_fighter(catalog, rng) for _ in range(size)]


def random_stage(catalog, rng=None):
    import secrets
    pool = catalog.tested or [0]
    return pool[secrets.randbelow(len(pool))] if rng is None else rng.choice(pool)


def random_bgm(rng=None):
    import secrets
    return secrets.randbelow(len(BGM_TRACKS)) if rng is None else rng.randrange(len(BGM_TRACKS))


# ---- reading a captured match back ------------------------------------------------------------------------------------
def read_ram(path):
    with zipfile.ZipFile(path) as archive:
        return archive.read('eeMemory.bin')


def scene_words(ram):
    """The SCENE words a captured battle holds."""
    u = lambda a: struct.unpack_from('<I', ram, a)[0]
    counts = (u(SCENE + 192), u(SCENE + 192 + SIDE_STRIDE))
    members = []
    for s in range(2):
        if not 0 < counts[s] <= TEAM_MAX:
            members.append([])
            continue
        base = SCENE + 196 + SIDE_STRIDE * s
        members.append([(u(base + MEMBER_STRIDE * j), u(base + MEMBER_STRIDE * j + 4),
                         u(base + MEMBER_STRIDE * j + 12)) for j in range(counts[s])])
    return dict(counts=counts, members=members, stage=u(SCENE + 28), stage2=u(SCENE + 40), time=u(SCENE + 16),
                referee=u(SCENE + 20), destructible=u(SCENE + 24), bgm=u(SCENE + 12), mode=u(MODE), count=u(COUNT))


def title(spec, catalog):
    """'Goku (Early) + Piccolo (Early) vs Kid Gohan + Krillin, Wasteland - Noon' (disc names)."""
    if spec.get('type') == 'hub':
        names = [catalog.name(f['character']) for team in spec['teams'] for f in team]
        return f'Hub: {" / ".join(names)}, {catalog.stage_name(spec["stage"])}'
    if spec['mode'] == 'ffa':
        names = [catalog.name(f['character']) for team in spec['teams'] for f in team]
        return f'{" / ".join(names)} (free-for-all), {catalog.stage_name(spec["stage"])}'
    teams = [' + '.join(catalog.name(f['character']) for f in t) for t in spec['teams']]
    return f'{teams[0]} vs {teams[1]}, {catalog.stage_name(spec["stage"])}'


def teams_of(spec):
    return [[(f['character'], f['costume']) for f in t] for t in spec['teams']]
