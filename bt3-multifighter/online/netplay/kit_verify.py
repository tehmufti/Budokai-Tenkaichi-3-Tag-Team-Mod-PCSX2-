"""What a prepared online match holds, read back from its RAM and checked against the lobby spec (spec 6.7h, 6.8).

Both PCs run this, with the Python standard library only:
  * the host's conversion (kit_prepare), on the finished netplay.p2s: every word must equal the spec, else the
    preparation fails with TTM-NET-31 and nothing is offered;
  * the guest, OFFLINE on the received file (zipfile, eeMemory.bin): the same words, checked against the spec it
    agreed to in the lobby, and their SHA-256 compared with the host's verify_sha (MATCH);
  * the guest (and the host) LIVE after the match is loaded, over PINE: only the STATIC subset (no battle clocks):
    late attach runs frames 0..D-1 before the kit reads anything.

FULL words (verify_sha = sha256 of their canonical JSON):
  mode, count            mod Team Battle mode word 0xD8080 == 1 and its fighter count == 2 * team size
  scene                  SCENE 0x331DC8: member counts (+0xC0 per side), every member record (+0 character, +4
                         colour, +8 Z-item set, +12 CPU level code), Duel Time index (+0x10), referee (+0x14),
                         destructible (+0x18), stage (+0x1C loaded, +0x28 selected), split flag (+0x24), each side's
                         transformation word (+0x2BC) and its 161-bit transformation availability set (+0x2D0, side
                         stride 0x270, so side 1's set is at +0x540)
  models                 MODELS[i]+12, the character of fighter i (2j = team 1 slot j, 2j+1 = team 2 slot j)
  writes                 the conversion's writes read back: the pause port count (GP + GPO(-20648)) = 2 (player 2 can
                         pause), spectator ports / human ports = 3 / 3 (player 2 can take over a teammate), both
                         leaders' native transformation flag actor+0x1300 = 1, the four dormant fighter-update
                         words = 0, and spectator_feedback's seat fixup (netplay_fixups)
  code                   SHA-256 of spectator_feedback's drawing code (the fixup is in it)
  netplay                netplay_core and netplay_view magic / layout words; (kit 2.1) the seat table (slot s plays
                         physical s for every human), every fighter's human / CPU flag at the start, the human
                         extras' special-move admission bits (extra_specials CONTROL+20)
  clock (FULL only)      battle object +272 (elapsed seconds and milliseconds): 0, so the fight gets the full time
Native addresses are translated by the installation's reviewed disc adapter before validation.
"""
import hashlib
import json
import struct
import zipfile
import kit_paths
from native_map import A, GP, GPO

SCENE = A(0x331DC8)
SIDE, MEMBER = 0x270, 100
MODE, COUNT, POINTERS = 0xD8080, 0xD8084, 0xD8040
MODELS = A(0x31C640)
BATTLE = A(0x2FEB38)
PAUSE_COUNT = (GP + GPO(-20648))
SPECTATOR = 0x0728F000                     # spectator_switch.CONTROL
PORTS, HUMAN_PORTS = 52, 56                # spectator_takeover.F
DORMANT = (0x0766F000, 0x0764F018, 0x0764F000, 0x0766E000)
FEEDBACK_DRAW, FEEDBACK_PROBE = 0x07287000, 0x07289000
NETPLAY_CONTROL, NETPLAY_MAGIC, NETPLAY_LAYOUT = 0x07B01000, 0x4E504331, 4   # layout 4 (kit 2.1)
VIEW_CONTROL, VIEW_MAGIC, VIEW_LAYOUT = 0x07B01100, 0x4E505631, 4
SEAT_CONTROL, SEAT_MAGIC, NO_SLOT = 0x07B24000, 0x4E505354, 0xFFFFFFFF          # netplay_core layout 4 seats
SPECIALS_HUMANS = 0x0744F000 + 20          # extra_specials CONTROL+20: the human extras' admission bits
START_GATE = 0x073E1C00                    # team_start_gate.CONTROL (+0x40 + 4i: fighter i's CPU flag at the start)
COM_CODES = (0, 6, 13, 21, 29)
HUB_CONTROL, HUB_MAGIC = 0x06406000, 0x31425548   # hub_mode.CONTROL ('HUB1'): a 'hub' match has it installed
import kit_adapter
ROSTER_COUNT = kit_adapter.roster_count()
AVAILABLE_BYTES = (ROSTER_COUNT + 63) // 64 * 8
AVAILABLE = (1 << ROSTER_COUNT) - 1
TIMES = (60, 90, 180, 240, 0)


class FileRam:
    """eeMemory.bin of a Deflate (or stored) savestate, read once."""

    def __init__(self, path):
        with zipfile.ZipFile(path) as archive:
            self.data = archive.read('eeMemory.bin')

    def read_ranges(self, ranges):
        return [bytes(self.data[a:a + n]) for a, n in ranges]


class BytesRam:
    def __init__(self, data):
        self.data = data

    def read_ranges(self, ranges):
        return [bytes(self.data[a:a + n]) for a, n in ranges]


def _u(b, o=0):
    return struct.unpack_from('<I', b, o)[0]


def words(ram, static=False):
    """The verification words of a prepared match. `ram` has read_ranges([(address, length)]) -> [bytes] (FileRam,
    BytesRam or a pinelink.PineLink); static=True leaves out the battle clock (what the first updates change)."""
    scene, mode, battle, pause, spectator, models, draw = ram.read_ranges([
        (SCENE, 0x2D0 + SIDE + AVAILABLE_BYTES), (POINTERS, 0x48), (BATTLE, 4), (PAUSE_COUNT, 4), (SPECTATOR, 64),
        (MODELS, 48), (FEEDBACK_DRAW, FEEDBACK_PROBE - FEEDBACK_DRAW)])
    count = _u(mode, COUNT - POINTERS)
    n = min(count, 12)
    actors = [_u(mode, 4 * i) for i in range(n)]
    model_ptrs = [_u(models, 4 * i) for i in range(n)]
    ok = lambda p: 0x100000 <= p < 0x8000000
    battle_ptr = _u(battle)
    extra = [(p + 12, 4) for p in model_ptrs if ok(p)] + [(a + 0x1300, 4) for a in actors if ok(a)] + \
            [(a + 0x1278, 4) for a in actors if ok(a)] + [(START_GATE, 4), (START_GATE + 0x40, 4 * n)] + \
            [(START_GATE + 0x80, 4 * n)] + [(SEAT_CONTROL, 8), (SEAT_CONTROL + 0x10, 40), (SPECIALS_HUMANS, 4)] + \
            [(d, 4) for d in DORMANT] + [(NETPLAY_CONTROL, 4), (NETPLAY_CONTROL + 0x74, 4), (VIEW_CONTROL, 16)] + \
            [(NETPLAY_CONTROL + 0x1C, 4), (NETPLAY_CONTROL + 0x78, 4), (NETPLAY_CONTROL + 0xF4, 8)] + \
            [(HUB_CONTROL, 4)]
    if not static and ok(battle_ptr):
        extra.append((battle_ptr + 272, 4))
    got = iter(ram.read_ranges(extra))
    model_chars = [_u(next(got)) if ok(p) else None for p in model_ptrs]
    leaders = [_u(next(got)) if ok(a) else None for a in actors]
    cpu_flags = [_u(next(got)) if ok(a) else None for a in actors]
    gate = _u(next(got))
    gate_cpu = list(struct.unpack(f'<{n}I', next(got)))
    gate_actors = list(struct.unpack(f'<{n}I', next(got)))
    seat_head = struct.unpack('<2I', next(got))
    seats = list(struct.unpack('<10I', next(got)))
    specials_humans = _u(next(got))
    dormant = [_u(next(got)) for _ in DORMANT]
    nc_magic, nc_layout = _u(next(got)), _u(next(got))
    view = struct.unpack('<4I', next(got))
    nc_mask, nc_end_rule = _u(next(got)), _u(next(got))
    nc_end_state, nc_options = struct.unpack('<2I', next(got))
    hub_magic = _u(next(got))
    # a leader is human when its CPU flag is 0: the start gate's table while the gate holds that fighter, else the
    # fighter's own flag
    human = []
    for i, a in enumerate(actors):
        flag = gate_cpu[i] if gate == 1 and gate_actors[i] == a else cpu_flags[i]
        human.append(None if flag is None else flag == 0)
    sides = []
    for s in range(2):
        base = s * SIDE
        members = []
        k = _u(scene, base + 0xC0)
        for j in range(min(k, 5)):
            m = base + 0xC4 + MEMBER * j
            members.append([_u(scene, m), _u(scene, m + 4), _u(scene, m + 8), _u(scene, m + 12)])
        q = int.from_bytes(scene[base + 0x2D0:base + 0x2D0 + AVAILABLE_BYTES], 'little')
        sides.append(dict(count=k, members=members, transform=_u(scene, base + 0x2BC),
                          available=f'{q:x}'))
    out = dict(mode=_u(mode, MODE - POINTERS), count=count,
               scene=dict(time=_u(scene, 0x10), referee=_u(scene, 0x14), destructible=_u(scene, 0x18),
                          stage_load=_u(scene, 0x1C), split=_u(scene, 0x24), stage=_u(scene, 0x28),
                          bgm=_u(scene, 0x0C), sides=sides),
               models=model_chars,
               writes=dict(pause_count=_u(pause), ports=_u(spectator, PORTS), human_ports=_u(spectator, HUMAN_PORTS),
                           leaders_transform=leaders, dormant=dormant, human=human),
               code=dict(feedback=hashlib.sha256(draw).hexdigest()),
               netplay=dict(core=[nc_magic, nc_layout], view=[view[0], view[2], view[3]], mask=nc_mask,
                            end=[nc_end_rule, nc_end_state], options=nc_options,
                            seats=seats if list(seat_head) == [SEAT_MAGIC, 1] else None,
                            specials_humans=specials_humans),
               hub=hub_magic == HUB_MAGIC)
    if not static:
        out['clock'] = _u(next(got)) if ok(battle_ptr) else None
    return out


def static_of(full):
    return {k: v for k, v in full.items() if k != 'clock'}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def sha(value):
    return hashlib.sha256(canonical(value).encode('ascii')).hexdigest()


def engine_count(spec):
    """The mod engine's fighter count for a spec: 2 x the larger column, at least 4 (uneven columns are padded with
    absent seats; a 1 v 1 runs on the four-seat free-for-all engine)."""
    return max(4, 2 * max(len(t) for t in spec['teams']))


def problems(w, spec, fixup_code=None, level='full'):
    """[text] where the words differ from the spec (empty: the match is the lobby's). fixup_code: the expected
    spectator_feedback code SHA-256 after the fixup (netplay_fixups.FIXED_SHA256), None to skip that check."""
    import kit_spec
    out = []
    sizes = [len(t) for t in spec['teams']]
    if w['mode'] != 1:
        out.append(f'mod mode word {w["mode"]} (not a Tag Team Mod battle)')
    if w['count'] != engine_count(spec):
        out.append(f'{w["count"]} fighters in the engine (the lobby has {" v ".join(map(str, sizes))})')
    sc = w['scene']
    native = spec['native']
    want_time = (TIMES.index(native['time']) + 1) % 5
    if sc['time'] != want_time:
        out.append(f'Duel Time index {sc["time"]} (expected {want_time} for {native["time"] or "infinite"})')
    if sc['referee'] != native['referee']:
        out.append(f'referee {sc["referee"]} (expected {native["referee"]})')
    if sc['destructible'] != (1 if native['destructible'] else 0):
        out.append(f'destructible word {sc["destructible"]} (expected {1 if native["destructible"] else 0})')
    if sc['stage'] != spec['stage'] or sc['stage_load'] != spec['stage']:
        out.append(f'stage {sc["stage"]}/{sc["stage_load"]} (expected {spec["stage"]})')
    if sc.get('bgm') != spec['bgm']:
        out.append(f'music track {sc.get("bgm")} (expected {spec["bgm"]})')
    if sc['split'] != 0:
        out.append(f'split-screen flag {sc["split"]} (online is one screen per player)')
    com = COM_CODES[native['com']]
    humans = {(t, i) for _, t, i in kit_spec.humans(spec)}
    for s, team in enumerate(spec['teams']):
        side = sc['sides'][s]
        if side['count'] != len(team):
            out.append(f'team {s + 1} has {side["count"]} fighters in the scene (expected {len(team)})')
            continue
        for j, f in enumerate(team):
            got = side['members'][j]
            want = [f['character'], f['costume'], 0, com]
            if j == 0:
                got, want = got[:3], want[:3]                     # a leader's level code is the native's
            if got != want:
                out.append(f'team {s + 1} fighter {j + 1}: character/colour/items/CPU level {got} (expected {want})')
        if int(side['available'], 16) & AVAILABLE != AVAILABLE:
            out.append(f'team {s + 1}: not every transformation is available ({side["available"]})')
    models = w['models']
    for s, team in enumerate(spec['teams']):
        for j, f in enumerate(team):
            i = 2 * j + s
            if i >= len(models) or models[i] != f['character']:
                out.append(f'fighter {i} model is character {models[i] if i < len(models) else None} '
                           f'(expected {f["character"]})')
    wr = w['writes']
    if wr['pause_count'] != 0:
        out.append(f'pause port count {wr["pause_count"]} (the pause menu must be closed online)')
    for i in range(len(wr['human'])):
        if i // 2 >= len(spec['teams'][i & 1]):
            continue                                              # a padded, absent engine seat
        want = (i & 1, i // 2) in humans
        if wr['human'][i] is not None and wr['human'][i] != want:
            out.append(f'fighter {i} is {"human" if wr["human"][i] else "a CPU"} (expected '
                       f'{"human" if want else "a CPU"})')
    for i in range(2, len(wr['leaders_transform'])):
        if (i & 1, i // 2) in humans and wr['leaders_transform'][i] != 1:
            out.append(f'fighter {i} (a player) may not transform')
    want_seats = [s if s in {kit_spec.slot_of(t, i) for _, t, i in kit_spec.humans(spec)} else NO_SLOT
                  for s in range(10)]
    if not any(want_seats[s] != NO_SLOT for s in range(10)):
        want_seats[0] = 0                                         # nobody plays: slot 0 (the host feeds it neutral)
    if w['netplay'].get('seats') != want_seats:
        out.append(f'netplay seats {w["netplay"].get("seats")} (expected {want_seats})')
    extra_humans = sum(1 << s for s, _, _ in kit_spec.humans(spec) if s >= 2)
    if (w['netplay'].get('specials_humans') or 0) & extra_humans != extra_humans:
        out.append(f'the human extras\' special moves are not admitted ({w["netplay"].get("specials_humans")})')
    if any(wr['dormant']):
        out.append(f'fighter-update words {wr["dormant"]} are not dormant')
    if fixup_code is not None and w['code']['feedback'] != fixup_code:
        out.append('the takeover prompt code is not the one this kit installs')
    if w['netplay']['core'] != [NETPLAY_MAGIC, NETPLAY_LAYOUT] or w['netplay']['view'][:2] != [VIEW_MAGIC, VIEW_LAYOUT]:
        out.append(f'netplay code words {w["netplay"]}')
    mask = kit_spec.slot_mask(spec) or 1
    if w['netplay'].get('mask') != mask:
        out.append(f'netplay slot mask {w["netplay"].get("mask")} (expected {mask})')
    if w.get('hub') != (spec.get('type') == 'hub'):
        out.append('the in-level hub is ' + ('missing' if spec.get('type') == 'hub' else 'installed in a versus match'))
    if 'clock' in w and w['clock'] not in (0, None):
        out.append(f'battle clock {w["clock"]:#x} (the fight would not get its full time)')
    return out


def file_words(path, static=False):
    return words(FileRam(path), static=static)


def differences(a, b, prefix=''):
    """Paths where two word dicts differ (for the TTM-NET-31 text)."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            out += differences(a.get(k), b.get(k), f'{prefix}{k}.')
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            out += differences(x, y, f'{prefix}{i}.')
    elif a != b:
        out.append(f'{prefix.rstrip(".")}: {a!r} != {b!r}')
    return out


# ---- the installation's guest code (spec 6.0): which mod build made a capture ---------------------------------------------
FINGERPRINT_REGIONS = (
    ('spectator_code', 0x07280000, 0x07287000),       # spectator_switch / spectator_takeover (ports words written)
    ('feedback_draw', 0x07287000, 0x07289000),        # spectator_feedback.draw (netplay_fixups seat fixup)
    ('feedback_probe', 0x07289000, 0x0728D000),
    ('npc_policy', 0x07290000, 0x0729F000),           # npc_transform_policy (CPU transformations off online)
    ('start_gate', 0x073E1000, 0x073E1C00),           # team_start_gate (opposing leader made human)
    ('native_prep', 0x07680000, 0x0768F000),          # native_preparation (the capture rule's words)
    ('reload_requests', 0x07640000, 0x0764F000),      # extra_reload_requests (dormant word)
    ('reload_forms_cell', 0x07660000, 0x0766E000),    # extra_reload_forms + extra_cell_absorption (dormant words)
)


def fingerprint(ram):
    """{region: sha256} of the mod's installed guest code in a CAPTURE (before the kit converts it)."""
    blocks = ram.read_ranges([(a, b - a) for _, a, b in FINGERPRINT_REGIONS])
    return {name: hashlib.sha256(data).hexdigest() for (name, _, _), data in zip(FINGERPRINT_REGIONS, blocks)}


def fingerprint_problems(found, recorded):
    """[region] whose code differs from every recorded build (data/guest-fingerprint.json 'regions': a region holds
    one SHA-256 or a list of them, one per accepted build family)."""
    out = []
    for name, _, _ in FINGERPRINT_REGIONS:
        want = recorded.get(name)
        allowed = want if isinstance(want, list) else [want]
        if found.get(name) not in allowed:
            out.append(name)
    return out
