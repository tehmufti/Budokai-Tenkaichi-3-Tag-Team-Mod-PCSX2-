"""BT4 Future Trunks (Super) + Vegeta: grounded Father-Son Galick exchange.

After the shared Sadistic Dance opening everyone stands on the ground. Trunks
charges and fires a purple Galick Gun. The victim takes it and holds it off
with Teen Gohan SSJ2's own Father-Son Kamehameha victim animations (bank16
clips 357..361: hit, catch, hold, push back, deadlock, overpowered, blown
away). Vegeta comes down beside Trunks, charges and fires his Galick Gun and
the two beams overpower the victim on that ultimate's own timing.

Native resources, all read from the selected disc and only re-timed:
- victim: Teen Gohan SSJ2 (16) ultimate clips 357..361 (authored on Goku
  Early's height-1 rig, so their donor binding is character0);
- both attackers: the reviewed Galick Gun pose sequence 261/262/263/264/267
  of Vegeta (Scouter) 29 (the same bytes as Trunks SSJ 226/264, 267), plus
  29's airborne hover, descent and landing while Vegeta enters;
- beams: the reviewed native private beam emitters, purple (tag_rush_colors).
Root travel of the source clips (bone0) moves the real actor roots instead,
so the victim really is pushed back and blown away, and release starts there.
"""
import hashlib
import math
import struct

NAME = 'super_galick_pair'
REVISION = 3
DONORS = (29, 29, 0)
GALICK, HOVER, DESCEND, LAND = 29, 38, 43, 45
VICTIM_BANK = 16
DISTANCE = 95.          # Trunks to the victim, along local +Z (victim faces +Z)
SIDE = 24.              # Vegeta lands beside Trunks (local +X), body-size spacing
BEHIND = 6.             # ...and slightly behind him
SKY = (SIDE+10., -230., DISTANCE+40.)
LANDING = 80            # frame of phase1 Vegeta touches down
LAND_FRAMES = 8
ENTRANCE_BLENDS = {(HOVER, DESCEND): 8, (DESCEND, LAND): 3, (LAND, 261): 4}
NAMES = ('Galick Gun', 'Vegeta comes down', 'Vegeta charges', 'Father-son push',
         'Deadlock', 'Overpower', 'Recover')
# Both beams must live inside the native emitter's ten-second lifetime.
FRAMES = (187, 110, 97, 86, 70, 48, 12)
EDGES = tuple(sum(FRAMES[:i]) for i in range(len(FRAMES)+1))
TRUNKS_FIRE = 67        # 261(17)+262(30)+263(20)
VEGETA_CHARGE = EDGES[1]+LANDING+LAND_FRAMES+17
VEGETA_FIRE = EDGES[2]+40
BURST_PHASE, BURST_FRAME = 5, 6          # 361 f42: the beam passes the victim
BEAM_END = EDGES[5]+30
BEAM_GROW_FRAMES = 30
BEAM_FINAL_SCALE = 1.55
TRANSLATED = frozenset((0, 2, 31, 45, 52))
LAST_BONE = 58


def _loop(source, length, frames, start=0):
    """Repeat a looping native clip for `frames`, from `start`."""
    rows, cursor, at = [], 0, start
    while cursor < frames:
        step = min(length-at, frames-cursor)
        rows.append((source, at, at+step, step)); cursor += step; at = 0
    return rows


def _hold(source, frame, frames):
    return [(source, frame, frame, frames)] if frames > 0 else []


def plans():
    """Per phase: ((bank, segments), ...) for Trunks, Vegeta and the victim.

    Segment = (animation, source start, source end, output frames).
    """
    g, v = GALICK, VICTIM_BANK
    charge = [(261, 0, 17, 17), (262, 0, 30, 30), (263, 0, 20, 20)]
    fire = lambda frames, start=0: _loop(264, 30, frames, start)
    hover = lambda frames, start=0: _loop(HOVER, 59, frames, start)
    trunks = [charge+fire(FRAMES[0]-67)]+[fire(n) for n in FRAMES[1:6]]+[[(267, 0, 12, FRAMES[6])]]
    vegeta = [hover(FRAMES[0]),
              hover(8, FRAMES[0] % 59)+_loop(DESCEND, 39, LANDING-8)+[(LAND, 0, 8, 8), (261, 0, 17, 17)]
              +_loop(262, 30, FRAMES[1]-LANDING-LAND_FRAMES-17),
              _loop(262, 30, 20, (FRAMES[1]-LANDING-LAND_FRAMES-17) % 30)+[(263, 0, 20, 20)]+fire(FRAMES[2]-40),
              fire(FRAMES[3]), fire(FRAMES[4]), fire(FRAMES[5]),
              [(267, 0, 12, FRAMES[6])]]
    victim = [_hold(357, 0, TRUNKS_FIRE)+[(357, 0, 120, FRAMES[0]-TRUNKS_FIRE)],
              [(358, 0, 110, 110)],
              [(358, 110, 207, 97)],
              [(359, 0, 86, 86)],
              _hold(360, 0, FRAMES[4]-36)+[(361, 0, 36, 36)],
              [(361, 36, 112, FRAMES[5])],
              _hold(361, 112, FRAMES[6])]
    result = []
    for phase in range(len(FRAMES)):
        rows = ((g, trunks[phase]), (g, vegeta[phase]), (v, victim[phase]))
        for _, segments in rows:
            if sum(s[3] for s in segments) != FRAMES[phase]:raise ValueError('Galick plan timing changed')
        result.append(rows)
    return result


def _raw_sources(iso):
    import model_assets as model
    from model_animations import decompress_animation, AnimationClip
    expected = {(GALICK, HOVER): 59, (GALICK, DESCEND): 39, (GALICK, LAND): 8,
                (GALICK, 261): 17, (GALICK, 262): 30, (GALICK, 263): 20, (GALICK, 264): 30,
                (GALICK, 267): 12, (VICTIM_BANK, 357): 162, (VICTIM_BANK, 358): 207, (VICTIM_BANK, 359): 86,
                (VICTIM_BANK, 360): 93, (VICTIM_BANK, 361): 112}
    banks, result = {}, {}
    for (character, animation), frames in expected.items():
        if character not in banks:banks[character] = model.read_animation_bank(iso, character)
        raw = decompress_animation(model.package_entry(banks[character], animation+1))
        clip = AnimationClip.from_decoded(animation, raw)
        if clip.frame_count != frames or len(clip.tracks) < 40:
            raise ValueError(f'Unreviewed Galick exchange source {character}/{animation}')
        result[character, animation] = raw
    return result


def _reduced(keys, rotation=.2, translation=.005):
    """Keep every key needed for < .2 degree / .005-unit interpolation error."""
    from model_animations import slerp
    selected = {0, len(keys)-1}
    def split(lo, hi):
        if hi-lo < 2:return
        ta, a = keys[lo]; tb, b = keys[hi]; worst = (1., None)
        for i in range(lo+1, hi):
            t, value = keys[i]; u = (t-ta)/(tb-ta)
            q = slerp(a.rotation, b.rotation, u)
            dot = min(1., abs(sum(x*y for x, y in zip(q, value.rotation))))
            error = math.degrees(2*math.acos(dot))/rotation
            if value.translation is not None:
                xyz = tuple(p*(1-u)+r*u for p, r in zip(a.translation, b.translation))
                error = max(error, math.dist(xyz, value.translation)/translation)
            if error > worst[0]:worst = (error, i)
        if worst[1] is not None:
            i = worst[1]; selected.add(i); split(lo, i); split(i, hi)
    split(0, len(keys)-1)
    return [keys[i] for i in sorted(selected)]


def compose(sources, binds, segments, frames, transitions=None):
    """Decoded native clip + per-frame bone0 travel (in the source's frame).

    Bone0's translation leaves the clip (the director moves the real root).
    Only the native contact/hand channels translate; a channel missing from
    one source uses the donor's bind translation, never a zero guess.
    """
    import tag_rush_choreography as choreography
    from model_animations import AnimationClip, BoneTransform, slerp
    clips = {}
    for animation, *_ in segments:
        clips.setdefault(animation, AnimationClip.from_decoded(animation, sources[animation]))
    bones = sorted(set.intersection(*(set(t.bone_id for t in c.tracks) for c in clips.values())))
    bones = [b for b in bones if b != 1 and b <= LAST_BONE]
    lookups = {a: {t.bone_id: t for t in c.tracks} for a, c in clips.items()}
    timeline = []
    for animation, start, end, duration in segments:
        for k in range(duration):
            timeline.append((animation, start+(end-start)*k/max(1, duration) if end != start else start))
    timeline.append((segments[-1][0], segments[-1][2]))
    if len(timeline) != frames+1:raise ValueError('Galick composition length changed')
    # Native locomotion clips are separate from the cinematic charge. Blend
    # only the entrance's three joins; retain the original attack/victim timing.
    blends = {}
    for frame in range(1, len(timeline)):
        before, after = timeline[frame-1], timeline[frame]
        duration = (transitions or {}).get((before[0], after[0]), 0)
        if before[0] != after[0] and duration:
            for k in range(min(duration, len(timeline)-frame)):
                blends[frame+k] = (before, _smooth(k/duration))
    tracks, travel = {}, []
    for frame, (animation, source) in enumerate(timeline):
        lookup = lookups[animation]
        root = lookup[0].evaluate(source).translation if 0 in lookup else None
        travel.append(tuple(root) if root is not None else (0., 0., 0.))
        for bone in bones:
            value = lookup[bone].evaluate(source)
            if frame in blends:
                (previous_animation, previous_frame), gain = blends[frame]
                previous = lookups[previous_animation][bone].evaluate(previous_frame)
                translation = value.translation
                if bone in TRANSLATED:
                    translation = _lerp(previous.translation or tuple(binds[bone]),
                                        value.translation or tuple(binds[bone]), gain)
                value = BoneTransform(translation, slerp(previous.rotation, value.rotation, gain))
            if bone in TRANSLATED:
                translation = (0., 0., 0.) if bone == 0 else value.translation or tuple(binds[bone])
            else:translation = None
            tracks.setdefault(bone, []).append((frame, BoneTransform(translation, value.rotation)))
    tracks = {bone: _reduced(keys) for bone, keys in tracks.items()}
    data = choreography._encode(frames, tracks)
    AnimationClip.from_decoded(0, data)
    if len(data) > 0xC000:raise ValueError('Galick exchange pose exceeds native decode scratch')
    return data, travel


_CACHE = {}


def _build(iso):
    import tag_rush_assets as assets
    key = str(iso)
    if key in _CACHE:return _CACHE[key]
    sources = _raw_sources(iso)
    binds = {}
    for character in set(DONORS):
        skeleton = assets.read_skeleton(iso, character)
        binds[character] = {row['bone']: row['translation'] for row in skeleton['rows']}
    clips, travel = {}, [[], [], []]
    for phase, rows in enumerate(plans()):
        for role, (bank, segments) in enumerate(rows):
            own = {animation: sources[bank, animation] for animation, *_ in segments}
            raw, path = compose(own, binds[DONORS[role]], segments, FRAMES[phase],
                                ENTRANCE_BLENDS if role == 1 else None)
            clips[assets.ClipSource(DONORS[role], 1300+role*10+phase)] = raw
            # Accumulate travel across phases; a new clip re-anchors natively.
            offset = travel[role][-1] if travel[role] else (0., 0., 0.)
            base = path[0]
            body = [tuple(o+p-b for o, p, b in zip(offset, point, base)) for point in path]
            travel[role].extend(body if not travel[role] else body[1:])
    _CACHE[key] = (clips, travel)
    return _CACHE[key]


def prepared_clips(iso):
    return dict(_build(iso)[0])


def timeline():
    import tag_rush_assets as assets
    import tag_rush_blue_native as blue
    phases = []
    for i, frames in enumerate(FRAMES):
        roles = tuple(assets.ClipSource(DONORS[role], 1300+role*10+i) for role in range(3))
        flags = assets.CUSTOM_FINISHER | blue.FLAG | assets.CHARGE_BEAM
        if i == 0:flags |= assets.BEAM_LEAD
        if i == 2:flags |= assets.BEAM_PARTNER
        if i == BURST_PHASE:flags |= assets.BEAM_LEAD | assets.BEAM_PARTNER | assets.FINISHER
        phases.append(assets.Phase(NAMES[i], frames, roles, (frames,)*3, flags))
    return tuple(phases)


def records():
    zero = (0., 0., 0., 0.)
    starts = {0: TRUNKS_FIRE, 2: VEGETA_FIRE-EDGES[2]}
    return [(1, 1, starts.get(i, 0), BURST_FRAME if i == BURST_PHASE else 0, zero, zero, zero)
            for i in range(len(FRAMES))]


def beam_schedule():
    return ((0, TRUNKS_FIRE, BEAM_END), (VEGETA_CHARGE, VEGETA_FIRE, BEAM_END))


def beam_scale(phase,ticks,hz=30):
    """Power up through the last half-second of the victim's beam deadlock."""
    if phase<4:return 1.
    if phase>4:return BEAM_FINAL_SCALE
    u=(ticks*60/hz-(FRAMES[4]-BEAM_GROW_FRAMES))/BEAM_GROW_FRAMES
    return 1.+(BEAM_FINAL_SCALE-1.)*_smooth(u)


def _smooth(t):
    t = max(0., min(1., t)); return t*t*(3.-2.*t)


def _lerp(a, b, t):
    return tuple(x+(y-x)*t for x, y in zip(a, b))


def vegeta_position(frame):
    """Waits high above and behind, then comes down beside Trunks."""
    land = (SIDE, 0., DISTANCE+BEHIND)
    start, end = EDGES[1]+8, EDGES[1]+LANDING
    if frame <= start:return SKY
    if frame >= end:return land
    u = (frame-start)/(end-start)
    e = 1.-(1.-u)**3                      # decelerating descent
    x, _, z = _lerp(SKY, land, _smooth(u))
    return (x, SKY[1]*(1.-e), z)


def roots_at(frame, travel):
    """Local root matrices (column vectors, Y down) for the three roles."""
    def matrix(position, yaw):
        c, s = math.cos(yaw), math.sin(yaw)
        return ((c, 0., s, position[0]), (0., 1., 0., position[1]), (-s, 0., c, position[2]), (0., 0., 0., 1.))
    trunks = (travel[0][frame][0], 0., DISTANCE+travel[0][frame][2])
    vegeta = vegeta_position(frame)
    victim = (travel[2][frame][0], 0., travel[2][frame][2])
    # Native Galick clips already face local -Z; Gohan's victim clips face
    # +Z. A further half-turn made both shooters face away. Aim each actual
    # root at the opposing role while retaining the clips' torso/head motion.
    def shooter_yaw(position):
        return math.atan2(position[0]-victim[0], position[2]-victim[2])
    victim_yaw = math.atan2(trunks[0]-victim[0], trunks[2]-victim[2])
    return matrix(trunks, shooter_yaw(trunks)), matrix(vegeta, shooter_yaw(vegeta)), matrix(victim, victim_yaw)


SHOTS = (
    # (first frame, eye from, eye to, target from, target to); local units,
    # Y down. Composition follows the native ultimate: the charge, the beam
    # arriving seen from beyond the victim, the victim catching it, then the
    # partner's arrival and the push seen from behind the victim.
    (0,   (-24., -8., DISTANCE-24.), (-20., -9., DISTANCE-21.), (0., -12., DISTANCE), (0., -12., DISTANCE)),
    (TRUNKS_FIRE, (18., -22., -48.), (14., -20., -38.), (0., -12., 20.), (0., -12., 6.)),
    (145, (-30., -14., 10.), (-26., -12., 18.), (0., -11., 4.), (0., -11., 2.)),
    (EDGES[1], (-12., -6., DISTANCE+22.), (-10., -7., DISTANCE+20.), 'arrival', 'arrival'),
    (EDGES[1]+50, (-18., -12., DISTANCE-30.), (-15., -13., DISTANCE-26.), (SIDE*.5, -13., DISTANCE+2.), (SIDE*.5, -13., DISTANCE+2.)),
    (EDGES[2], (SIDE+22., -12., DISTANCE-34.), (SIDE+19., -13., DISTANCE-30.), (SIDE*.6, -13., DISTANCE+2.), (SIDE*.6, -13., DISTANCE+2.)),
    (VEGETA_FIRE, (40., -30., -90.), (44., -34., -120.), (SIDE*.4, -14., DISTANCE*.6), (SIDE*.4, -14., DISTANCE*.6)),
    (EDGES[3], (-70., -40., DISTANCE+120.), (-64., -38., DISTANCE+112.), (SIDE*.3, -12., DISTANCE*.4), (SIDE*.3, -12., DISTANCE*.35)),
    (EDGES[4], (-16., -15., 26.), (-13., -14., 21.), 'victim', 'victim'),
    (EDGES[5], (-70., -30., -20.), (-80., -36., -55.), 'victim', 'victim'),
    (EDGES[6], (SIDE*.5+24., -26., DISTANCE+56.), (SIDE*.5+27., -29., DISTANCE+60.), (0., -10., -70.), (0., -10., -78.)),
)


def camera_at(frame, travel):
    """Look-at camera (right, down, forward, eye columns) and focus."""
    index = max(i for i, row in enumerate(SHOTS) if row[0] <= frame)
    first = SHOTS[index][0]; last = SHOTS[index+1][0] if index+1 < len(SHOTS) else EDGES[-1]
    u = _smooth((frame-first)/max(1, last-first))
    _, e0, e1, t0, t1 = SHOTS[index]
    def target(value):
        if value == 'arrival':
            x, y, z = vegeta_position(frame)
            return (x, y-12., z)
        if value == 'victim':return (travel[2][frame][0], -11., travel[2][frame][2])
        return value
    eye = _lerp(e0, e1, u); goal = _lerp(target(t0), target(t1), u)
    if first == EDGES[1]:
        # Follow his entrance, rather than aiming from ground level at a
        # clamped point far below him and losing the first half of the descent.
        x, y, z = vegeta_position(frame)
        offset = _lerp((-26., -15., -38.), (-22., -12., -34.), u)
        eye = (x+offset[0], y+offset[1], z+offset[2])
    forward = tuple(b-a for a, b in zip(eye, goal)); n = math.sqrt(sum(v*v for v in forward))
    forward = tuple(v/n for v in forward)
    right = (forward[2], 0., -forward[0]); n = math.sqrt(sum(v*v for v in right)); right = tuple(v/n for v in right)
    down = (forward[1]*right[2]-forward[2]*right[1], forward[2]*right[0]-forward[0]*right[2],
            forward[0]*right[1]-forward[1]*right[0])
    return (right, down, forward, eye), goal


def motion(iso):
    """Per two source frames: three root tables and the camera table."""
    _, travel = _build(iso)
    samples = EDGES[-1]//2+1
    roots = [bytearray(), bytearray(), bytearray()]; camera = bytearray()
    for index in range(samples):
        frame = min(2*index, EDGES[-1])
        for role, m in enumerate(roots_at(frame, travel)):
            roots[role].extend(struct.pack('<16f', *(m[r][c] for c in range(4) for r in range(4))))
        (right, down, forward, eye), focus = camera_at(frame, travel)
        camera.extend(struct.pack('<16f', *right, 0., *down, 0., *forward, 0., *eye, 1.))
        camera.extend(struct.pack('<4f', *focus, 1.))
    payload = b''.join(roots)+bytes(camera)
    return dict(samples=samples, roots=[bytes(r) for r in roots], camera=bytes(camera), edges=EDGES,
                sha256=hashlib.sha256(payload).hexdigest())
