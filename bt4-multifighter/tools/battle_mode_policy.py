"""Logical match relationships independent of native two-role actor identities.

Only captured mode control is trusted. Zero/uninstalled or stale control keeps
the existing team parity rule. Inputs to emit_enemy are physical actor indices,
never temporary native role aliases or model indices.
"""
import functools
import struct

CONTROL, END = 0x0712F000, 0x07130000
MAGIC = 0x364D5442
TEAMS, FFA, COOP = 0, 1, 2
MODES = {'teams': TEAMS, 'ffa': FFA, 'coop': COOP}
# The original two-human co-op pair uses physical 0 and 2. Larger sessions
# derive every seat from human_seats(), including CPU flags, pad routing and
# the extra-special dispatcher's human mask.
COOP_HUMANS = (0, 2)
HUMAN_COUNTS = (0, 1, 2, 3, 4)


def human_seats(mode, humans, present=None, assignment=None, squads=None):
    """Controller order in physical actor space, shared by every installer."""
    if mode not in ('teams','ffa','coop','training','training_coop') or humans not in HUMAN_COUNTS:
        raise ValueError('Invalid match mode/human count')
    if squads is None and mode=='ffa':squads=scoped_squads()    # a match of three to five teams being built
    if squads is not None:
        # Three to five teams: every player sits where the team layout put them (squad_seats). A caller that
        # names no seats gets the ones the match was prepared with.
        if assignment is None and squads.seats is not None and len(squads.seats)==humans:assignment=squads.seats
        seats=tuple(range(humans)) if assignment is None else tuple(assignment)
        if (mode!='ffa' or len(seats)!=humans or len(set(seats))!=humans or
                any(type(i) is not int or not 0<=i<MAX_ACTORS or squads.team_of[i] is None for i in seats)):
            raise ValueError('Invalid player seats for these teams')
        if present is not None and any(not present&(1<<i) for i in seats):
            raise ValueError('Select a fighter for every assigned player slot before starting')
        return seats
    if assignment is not None:
        import team_assignment
        if mode not in ('teams','training') or humans not in (2,3,4):raise ValueError('Team assignments require two to four players')
        seats=tuple(assignment)
        if len(seats)!=humans or seats!=team_assignment.physical_seats(tuple(i&1 for i in seats)):
            raise ValueError('Invalid player team assignment')
    elif mode in ('coop','training_coop'):
        if humans not in (2,3,4):raise ValueError('Co-op requires two, three or four humans')
        seats=tuple(2*i for i in range(humans))
    elif mode=='ffa' and humans>=3 and present is not None:
        # Match the sequential native selection order, even for unequal columns:
        # every selected left-column fighter, then the right-column fighters.
        seats=tuple(i for side in (0,1) for i in range(side,ENGINE_ACTORS,2)
                    if present&(1<<i))[:humans]
    else:seats=tuple(range(humans))
    if present is not None and (len(seats)!=humans or any(not present&(1<<i) for i in seats)):
        if assignment is not None:raise ValueError('Select a fighter for every assigned player slot before starting')
        if mode in ('coop','training_coop'):
            if humans>=3:raise ValueError(f'{humans}-player co-op needs {humans} selected allies on Team 1')
            raise ValueError('Co-op requires two humans: select at least two allies on Team 1')
        if mode=='ffa':raise ValueError(f'{humans}-player free-for-all needs at least {humans} selected fighters')
        raise ValueError('Three-player teams need two fighters on Team 1 and one on Team 2; four-player teams need two per side')
    return seats
# Capacity describes the audited actor/resource engine, not a rule imposed by
# co-op. Five per side is the ceiling of the native select screen itself: its
# team record, the battle-config block and each actor's roster all hold exactly
# five members, and a sixth entry would overlap live data at every layer.
# Every fighter-count check in the mod - Python preconditions and guest gates
# alike - derives from this one constant, so lowering it is the whole rollback.
TEAM_CAPACITY = 5
ACTOR_COUNTS = tuple(2 * n for n in range(2, TEAM_CAPACITY + 1))
MIN_ACTORS, MAX_ACTORS = ACTOR_COUNTS[0], ACTOR_COUNTS[-1]
# Model IDs, the mod's target/pointer tables and every per-owner effect table
# are twelve wide; this is the hard ceiling the constant may never exceed.
ENGINE_ACTORS = 12
assert MAX_ACTORS <= ENGINE_ACTORS, 'Team capacity exceeds the twelve-wide engine tables'
FIELDS = dict(magic=0, manager=4, count=8, mode=12, humans=16, present=20,
              fused_leader=24, fused_partner=28, fusion_controls=32, tick=36,
              fusion_epoch=40, winner=44, request_leader=48, request_partner=52,
              request_chord=56, request_expires=60, request_accepted=64)


# The guest-side range test: count - MIN_ACTORS < COUNT_SPAN. It admits the odd
# counts in between as well, exactly as the original 4..6 gate admitted 5; the
# publisher only ever writes 2 x the larger team, so an odd count cannot occur,
# and a range test keeps every inlined copy the same size as before.
COUNT_SPAN = MAX_ACTORS - MIN_ACTORS + 1

# Every install made before five-a-side - the prepared release checkpoints and
# the presets cached from them - was built for three per side. Their guest code
# is recognised byte for byte, so rebuilding what they carry has to emit the
# capacity they were built with. building_for() scopes that; everything else
# emits TEAM_CAPACITY. Only emission follows it: Python-side preconditions keep
# accepting every current count, since a legacy match never publishes more
# than six fighters.
LEGACY_TEAM_CAPACITY = 3
_building = [TEAM_CAPACITY]


def emitted_capacity():
    """Per-side capacity the guest code being emitted right now is built for."""
    return _building[-1]


def emitted_actors():
    """Largest fighter count the guest code being emitted admits."""
    return 2 * emitted_capacity()


def count_span():
    return emitted_actors() - MIN_ACTORS + 1


def emitted_tables():
    """Width of the per-fighter guest tables for the build being emitted.

    Three-a-side builds sized them for six fighters. Current builds size them
    for every fighter the engine can hold, so no larger match shares a slot.
    """
    return 6 if emitted_capacity() == LEGACY_TEAM_CAPACITY else ENGINE_ACTORS


def stride_shifts(stride):
    """The two left shifts whose sum multiplies by stride (guest row indexing)."""
    shifts = tuple(bit for bit in range(31, -1, -1) if stride >> bit & 1)
    if len(shifts) != 2:
        raise ValueError(f'Row stride {stride} is not a sum of two powers of two')
    return shifts


class building_for:
    """Emit guest code for an install built with the given per-side capacity."""
    def __init__(self, capacity):
        if capacity not in (LEGACY_TEAM_CAPACITY, TEAM_CAPACITY):
            raise ValueError(f'No reviewed build for {capacity} per side')
        self.capacity = capacity

    def __enter__(self):
        _building.append(self.capacity)
        return self.capacity

    def __exit__(self, *exc):
        _building.pop()
        return False


def _gate_signature(capacity):
    # addiu t1,t2,-MIN; sltiu t1,t1,span - the core count gate every installed
    # guard inlines (fresh_team_combat.gate), unique to that idiom.
    span = 2 * capacity - MIN_ACTORS + 1
    return struct.pack('<2I', 0x25490000 | (-MIN_ACTORS & 0xFFFF), 0x2D290000 | span)


def installed_capacity(ram, start=0x07000000, end=0x08000000):
    """Capacity the mod code already installed in ram was built for.

    RAM with no gated guard yet (a fresh match) builds at TEAM_CAPACITY. A mix
    of both builds is refused: nothing may rewrite one without the other.
    """
    if TEAM_CAPACITY == LEGACY_TEAM_CAPACITY:  # rolled back: one build
        return TEAM_CAPACITY
    legacy = ram.find(_gate_signature(LEGACY_TEAM_CAPACITY), start, end) >= 0
    current = ram.find(_gate_signature(TEAM_CAPACITY), start, end) >= 0
    if legacy and current:
        raise ValueError('Installed guest code mixes three- and five-a-side builds')
    return LEGACY_TEAM_CAPACITY if legacy else TEAM_CAPACITY


def matching_install(function):
    """Run function(ram, ...) building for the capacity already installed in ram."""
    @functools.wraps(function)
    def run(ram, *args, **kwargs):
        capacity = known_capacity(ram)
        with building_for(installed_capacity(ram) if capacity is None else capacity):
            # A match with three to five teams carries its team table: rebuild what it holds in that build.
            teams = installed_squads(ram) if emitted_squads() is None else None
            if teams is None:
                return function(ram, *args, **kwargs)
            with building_squads(teams):
                return function(ram, *args, **kwargs)
    return run


# A composition that already scanned its source shares that answer with the
# matching_install builders it runs, instead of each rescanning 16 MiB. The
# answer is tied to one RAM object and ends with the composition; it is not a
# build context, so emitted_capacity() is unaffected. Only the current build
# is ever assumed: that answer can change only when a legacy signature appears,
# and the composition reports every range it writes (assumed_writes), so the
# first write that would change installed_capacity() ends the assumption and
# every later call scans the RAM exactly as before.
_assumed = {}


def known_capacity(ram):
    """The capacity assumed for this exact RAM object, or None."""
    entry = _assumed.get(id(ram))
    return entry[1] if entry is not None and entry[0] is ram else None


class assumed_capacity:
    """Let matching_install reuse capacity for this RAM object while the scope lasts.

    capacity must be installed_capacity(ram). Anything but the current build
    (or None) assumes nothing, so those RAMs keep the per-call scan.
    """
    def __init__(self, ram, capacity):
        self.ram = ram
        self.active = (capacity == TEAM_CAPACITY != LEGACY_TEAM_CAPACITY and
                       known_capacity(ram) is None)

    def __enter__(self):
        if self.active:
            _assumed[id(self.ram)] = (self.ram, TEAM_CAPACITY)
        return self.ram

    def __exit__(self, *exc):
        if self.active:
            forget_capacity(self.ram)
        return False


def forget_capacity(ram):
    entry = _assumed.get(id(ram))
    if entry is not None and entry[0] is ram:
        del _assumed[id(ram)]


def assumed_writes(ram, spans, start=0x07000000, end=0x08000000):
    """Keep an assumption only while no write in spans made a legacy gate visible.

    spans are (address, length) ranges just written into ram. An occurrence
    that overlaps a written byte lies within 7 bytes of it, so scanning those
    windows finds every signature a write could have created.
    """
    if known_capacity(ram) is None:
        return
    legacy = _gate_signature(LEGACY_TEAM_CAPACITY)
    reach = len(legacy)-1
    for address, length in spans:
        lo, hi = max(start, address-reach), min(end, address+length+reach)
        if lo < hi and ram.find(legacy, lo, hi) >= 0:
            forget_capacity(ram)
            return


def emit_actor_count(a, count, fail, scratch=8):
    """Branch to fail unless MIN_ACTORS <= count <= emitted_actors().

    Clobbers only the scratch register; no calls, no HI/LO. Three words plus
    the branch delay slot, the same footprint as the gates it replaces.
    """
    a.addiu(scratch, count, -MIN_ACTORS)
    a.i(11, scratch, scratch, count_span())
    a.branch(4, scratch, 0, fail)


def emit_listed_count(a, count, fail, ok, scratch):
    """Count gate of the guards that were built as 'count == 4 or count == 6'.

    Three-a-side builds keep exactly those words (the caller places label ok
    right after); current builds use the range test and never branch to ok.
    """
    if emitted_capacity() == LEGACY_TEAM_CAPACITY:
        a.addiu(scratch, 0, 4); a.branch(4, count, scratch, ok)
        a.addiu(scratch, 0, 6); a.branch(5, count, scratch, fail)
    else:
        emit_actor_count(a, count, fail, scratch)


def emit_enemy(a, left, right, fail, tag, t0=8, t1=9):
    """Branch to fail for allies/self; clobber exactly t0/t1, no calls/HI/LO.

    FFA is enabled only for the captured native actor manager. Other modes and
    absent/stale controls retain parity. Callers validate bounds/aliveness.
    """
    if len({left, right, t0, t1}) != 4:
        raise ValueError('Relationship inputs and scratch registers must differ')
    native, done = tag+'_teams', tag+'_enemy'
    if emitted_squads() is not None:
        # Three to five teams: enemies are fighters of another team. The table is trusted only for the live actor
        # manager; anything else keeps parity. Same two scratch registers, five words fewer than below.
        a.branch(4, left, right, fail)
        a.li(t0, SQUAD); a.lw(t1, t0, SQUAD_FIELDS['manager']); a.lw(t0, 28, -22364)
        a.branch(5, t0, t1, native)
        a.li(t0, SQUAD+SQUAD_FIELDS['team_of']); a.r(0x21, t1, t0, right); a.r(0x21, t0, t0, left)
        a.i(36, t0, t0, 0); a.i(36, t1, t1, 0)
        a.branch(4, 0, 0, done)
        a.label(native); a.i(12, t0, left, 1); a.i(12, t1, right, 1)
        a.label(done); a.branch(4, t0, t1, fail)
        return
    a.branch(4, left, right, fail)
    a.li(t0, CONTROL); a.lw(t0, t0); a.li(t1, MAGIC)
    a.branch(5, t0, t1, native)
    a.li(t0, CONTROL); a.lw(t0, t0, 4); a.lw(t1, 28, -22364)
    a.branch(5, t0, t1, native)
    a.li(t0, CONTROL); a.lw(t0, t0, 12); a.addiu(t1, 0, FFA)
    a.branch(4, t0, t1, done)
    a.label(native); a.i(12, t0, left, 1); a.i(12, t1, right, 1)
    a.branch(4, t0, t1, fail)
    a.label(done)


def enemy(mode, left, right, squads=None):
    if mode not in MODES: raise ValueError('Unknown battle mode')
    if squads is not None:
        return left != right and squads.team_of[left] != squads.team_of[right]
    return left != right and (mode == 'ffa' or (left & 1) != (right & 1))


def targets(mode, count, present, squads=None):
    if mode not in MODES or count not in ACTOR_COUNTS or present & 3 != 3 or present >> count:
        raise ValueError('Invalid captured mode/participation')
    result=[]
    for i in range(count):
        choices=[j for j in range(count) if present & (1 << j) and enemy(mode,i,j,squads)]
        if not choices: raise ValueError('Each fighter requires another contestant')
        if squads is not None and squads.team_of[i] is not None:
            # Open against the fighter of the same rank in the next team, so every team is engaged at the start.
            team=squads.team_of[i];rank=squads.members(team).index(i)
            for step in range(1,squads.teams):
                rivals=[j for j in squads.members((team+step)%squads.teams) if j in choices]
                if rivals:
                    result.append(rivals[rank%len(rivals)]);break
            else:result.append(choices[0])
            continue
        result.append(i ^ 1 if i ^ 1 in choices else choices[0])
    return result


def prepare_singleton(mode, humans):
    """Reserve inactive parity slots when a custom mode changes a 1v1 match.

    The ordinary Team Battle selection keeps its native controller choices.
    Explicit CPU-only and two-player choices must also prepare 1v1 so their
    controller policy is installed even if Duel was set up differently.
    """
    return mode in ('ffa','training') or (mode == 'teams' and humans != 1)


def validate_roster(mode, count, present, humans, assignment=None, squads=None):
    """Validate capture capacity and human ownership, returning selected counts.

    Native parity slots stay reserved even when one side has fewer fighters.
    Co-op needs physical 0 and 2 for its humans; any nonempty opposing roster
    within the same engine capacity is supported.
    """
    if type(count) is not int or type(present) is not int or present < 0:
        raise ValueError('Invalid captured mode/participation')
    if squads is not None:
        if mode != 'ffa' or squads.present() != present or squads.count() != count:
            raise ValueError('The selected fighters do not match the team setup: pick the planned number on each row')
        targets(mode, count, present, squads)
        if type(humans) is not int or humans not in HUMAN_COUNTS:
            raise ValueError('Invalid human cohort')
        human_seats(mode, humans, present, assignment, squads)
        return squads.counts()
    targets(mode, count, present)
    if type(humans) is not int or humans not in HUMAN_COUNTS:
        raise ValueError('Invalid human cohort')
    # Team battles and free-for-all both offer a CPU-only exhibition.
    # Co-op retains its two-human ownership requirement below.
    counts = tuple(sum(bool(present & (1 << i)) for i in range(side, count, 2))
                   for side in range(2))
    if mode == 'coop' and humans not in (2,3,4):
        raise ValueError('Co-op requires two humans, three humans or four humans')
    if mode == 'coop' and (not humans <= counts[0] <= TEAM_CAPACITY or
                           not 1 <= counts[1] <= TEAM_CAPACITY):
        raise ValueError(f'Co-op requires {humans} humans: select {humans} to {TEAM_CAPACITY} '
                         f'fighters on the left and one to {TEAM_CAPACITY} on the right')
    if humans>=3 or assignment is not None:human_seats(mode,humans,present,assignment)
    return counts


# ---- Team Battle with three to five teams ---------------------------------------------------------------------------
# Such a match runs on the free-for-all engine. The mode word stays FFA, so every switch that turns a team feature
# off in a free-for-all holds until that feature has learned the team table, and the SQUAD block (inside the mode
# reservation) names each fighter's team. The native side of a fighter stays index & 1. Guest code for such a match
# is emitted inside building_squads(); outside it every emitter produces exactly what it always did.
MAX_TEAMS = 5
SQUAD, SQUAD_END = CONTROL+0x100, CONTROL+0x200
SQUAD_MAGIC = 0x31445153                      # 'SQD1'
SQUAD_LAYOUT = 1                              # version of squad_layout(): part of what two online peers agree on
SQUAD_FIELDS = dict(magic=0, manager=4, teams=8, count=12, team_of=16, layout=28, members=32, humans=52, shared=56, seats=60,
                    alive=64, winner_team=68, winner=72, colors=80)
# One colour per team, the same everywhere a team is shown (GS ABGR for the guest, RGB for host pictures).
TEAM_COLORS = (0x80FFBC48, 0x804878FF, 0x8078E058, 0x8040D0FF, 0x80FF80C0)
TEAM_RGB = ((72, 188, 255), (255, 120, 72), (88, 224, 120), (255, 208, 64), (192, 128, 255))
ABSENT = 0xFF


class Squads:
    """The teams of one match: team_of[physical] for the twelve engine slots (None where no fighter stands)."""
    __slots__ = ('team_of', 'teams', 'seats')

    def __init__(self, team_of, seats=None):
        # seats: the physical seat of each player in player order, once the players are known (None before).
        self.seats = None if seats is None else tuple(seats)
        team_of = tuple(team_of)
        team_of += (None,)*(ENGINE_ACTORS-len(team_of))
        used = sorted({t for t in team_of if t is not None})
        if (len(team_of) != ENGINE_ACTORS or any(t is not None and type(t) is not int for t in team_of) or
                not 2 <= len(used) <= MAX_TEAMS or used != list(range(len(used))) or
                any(t is not None for t in team_of[MAX_ACTORS:])):
            raise ValueError('Two to five teams, numbered from the first, on at most ten fighters')
        if team_of[0] is None or team_of[1] is None or team_of[0] == team_of[1]:
            raise ValueError('The first fighter of each row must be on different teams')
        for side in (0, 1):
            row = [team_of[i] is not None for i in range(side, MAX_ACTORS, 2)]
            if row != sorted(row, reverse=True): raise ValueError('The fighters of a row must be contiguous')
        self.team_of, self.teams = team_of, len(used)

    def __eq__(self, other): return isinstance(other, Squads) and other.team_of == self.team_of
    def __hash__(self): return hash(self.team_of)
    def __repr__(self): return f'Squads({self.team_of[:MAX_ACTORS]})'
    def members(self, team): return tuple(i for i, t in enumerate(self.team_of) if t == team)
    def present(self): return sum(1 << i for i, t in enumerate(self.team_of) if t is not None)
    def counts(self): return tuple(sum(self.team_of[i] is not None for i in range(side, MAX_ACTORS, 2)) for side in (0, 1))
    def count(self): return 2*max(self.counts())
    def sizes(self): return tuple(len(self.members(t)) for t in range(self.teams))

    def with_seats(self, seats):
        """The same teams with the players' seats (player order)."""
        seats = tuple(seats)
        if (len(seats) > 4 or len(set(seats)) != len(seats) or
                any(type(i) is not int or not 0 <= i < MAX_ACTORS or self.team_of[i] is None for i in seats)):
            raise ValueError('Invalid player seats for these teams')
        return Squads(self.team_of, seats)

    def split(self):
        """The team with fighters on both rows, or None."""
        return next((t for t in range(self.teams) if len({i & 1 for i in self.members(t)}) == 2), None)

    def block(self, manager, seats=None):
        """The SQUAD block of this match (seats: the players' seats in player order; default: this layout's)."""
        seats = tuple(self.seats or ()) if seats is None else tuple(seats)
        data = bytearray(SQUAD_END-SQUAD)
        struct.pack_into('<4I', data, 0, SQUAD_MAGIC, manager, self.teams, self.count())
        data[16:28] = bytes(ABSENT if t is None else t for t in self.team_of)
        struct.pack_into('<I', data, SQUAD_FIELDS['layout'], SQUAD_LAYOUT)
        for team in range(self.teams):
            struct.pack_into('<I', data, SQUAD_FIELDS['members']+4*team, sum(1 << i for i in self.members(team)))
        struct.pack_into('<2I', data, SQUAD_FIELDS['humans'], sum(1 << i for i in seats),
                         int(len(seats) >= 2 and len({self.team_of[i] for i in seats}) == 1))
        data[SQUAD_FIELDS['seats']:SQUAD_FIELDS['seats']+4] = (bytes(seats)+bytes([ABSENT])*4)[:4]
        struct.pack_into('<3I', data, SQUAD_FIELDS['alive'], (1 << self.teams)-1, 0xFFFFFFFF, 0xFFFFFFFF)
        struct.pack_into('<5I', data, SQUAD_FIELDS['colors'], *TEAM_COLORS)
        return bytes(data)


def squad_layout(sizes):
    """Teams of the given sizes on the two rows of five of the native selection (physical = 2 * position + row).

    Every team is a contiguous block. Team 1 starts at physical 0, the first fighters of the two rows are on
    different teams, and a team stands on both rows only when the sizes cannot be parted otherwise: then it is the
    highest-numbered team that makes it work, at the end of both rows. Ties prefer even rows, then team 2 on the
    second row, then the lowest teams on the first. Changing any of this changes SQUAD_LAYOUT.
    """
    from itertools import combinations
    sizes = tuple(sizes); n = len(sizes)
    if (not 2 <= n <= MAX_TEAMS or any(type(s) is not int or not 1 <= s <= TEAM_CAPACITY for s in sizes) or
            sum(sizes) > MAX_ACTORS):
        raise ValueError('Two to five teams of one to five fighters, ten fighters at most')
    others = list(range(1, n)); best = None
    for k in range(len(others)):
        for extra in combinations(others, k):
            left = (0,)+extra; right = tuple(t for t in others if t not in extra)
            a, b = sum(sizes[t] for t in left), sum(sizes[t] for t in right)
            if a <= TEAM_CAPACITY and b <= TEAM_CAPACITY and right:
                key = (abs(a-b), 1 in left, left)
                if best is None or key < best[0]: best = (key, left, right, None, 0)
    if best is None:
        for x in range(n-1, 0, -1):
            rest = [t for t in others if t != x]
            for k in range(len(rest)+1):
                for extra in combinations(rest, k):
                    left = (0,)+extra; right = tuple(t for t in rest if t not in extra)
                    a, b = sum(sizes[t] for t in left), sum(sizes[t] for t in right)
                    for part in range(1, sizes[x]):
                        la, rb = a+part, b+sizes[x]-part
                        if la <= TEAM_CAPACITY and rb <= TEAM_CAPACITY:
                            key = (abs(la-rb), 1 in left, left, part)
                            if best is None or key < best[0]: best = (key, left, right, x, part)
            if best is not None: break
    if best is None: raise ValueError('These team sizes do not fit two rows of five')
    _, left, right, split, part = best
    rows = ([], [])
    for row, teams in enumerate((left, right)):
        for t in teams: rows[row].extend([t]*sizes[t])
    if split is not None:
        rows[0].extend([split]*part); rows[1].extend([split]*(sizes[split]-part))
    team_of = [None]*ENGINE_ACTORS
    for row in (0, 1):
        for position, t in enumerate(rows[row]): team_of[2*position+row] = t
    return Squads(team_of)


def squad_seats(squads, human_teams):
    """Physical seat of each player: the next free fighter of the team that player chose."""
    used = [0]*squads.teams; seats = []
    for team in human_teams:
        if type(team) is not int or not 0 <= team < squads.teams: raise ValueError('Unknown team for a player')
        members = squads.members(team)
        if used[team] >= len(members):
            raise ValueError(f'Team {team+1} has no fighter left for another player')
        seats.append(members[used[team]]); used[team] += 1
    return tuple(seats)


# The build being emitted: the bottom entry is the watcher's current match (session_squads), entries above it are
# explicit scopes. None is the ordinary build.
_squads = [None]


def emitted_squads():
    """The teams the guest code being emitted right now is built for, or None for the ordinary build."""
    return _squads[-1]


def timeover_winner(squads, health, humans=(), consumed=()):
    """Who wins a match of three to five teams when the time is over: (team, fighter), or None when nobody lives.

    health: {physical: (health, full health)} for the fighters of the match. A team's score is its total remaining
    health as a share of its total full health over every one of its fighters (a fallen fighter: no health, its
    full maximum). Team a is ahead of team b when sumHealth_a * sumMax_b > sumHealth_b * sumMax_a; equal scores go
    to the lower team number; only a team with a living fighter can win. The fighter named is that team's first
    living player, else its first living fighter. battle_modes.squad_timeover_code is the same rule in the guest.
    consumed: fighters consumed by a fusion; they are not counted (the fused fighter stands for the pair).
    """
    health = {i: row for i, row in health.items() if i not in consumed}
    best = None
    for team in range(squads.teams):
        rows = [(min(max(health[i][0], 0), health[i][1]), health[i][1]) for i in squads.members(team)
                if i in health and health[i][1] > 0]
        living = [i for i in squads.members(team) if i in health and health[i][1] > 0 and health[i][0] > 0]
        if not living: continue
        total, full = sum(h for h, _ in rows), sum(m for _, m in rows)
        if best is None or total*best[2] > best[1]*full: best = (team, total, full, living)
    if best is None: return None
    players = [i for i in best[3] if i in humans]
    return best[0], (players or best[3])[0]


def scoped_squads():
    """The teams of an explicit build scope (building_squads), or None; the session default does not count."""
    return _squads[-1] if len(_squads) > 1 else None


class building_squads:
    """Emit guest code for a match with these teams (None: the ordinary build, whatever the session says)."""
    def __init__(self, squads):
        if squads is not None and not isinstance(squads, Squads): raise ValueError('Expected the teams of a match')
        self.squads = squads

    def __enter__(self):
        _squads.append(self.squads)
        return self.squads

    def __exit__(self, *exc):
        _squads.pop()
        return False


def session_build(function):
    """A preparation method: everything it emits is built for its session's teams (None: the ordinary build)."""
    import functools

    @functools.wraps(function)
    def run(self, *args, **kwargs):
        squads = getattr(self, 'squads', None)
        session_squads(squads)
        with building_squads(squads):
            return function(self, *args, **kwargs)
    return run


def session_squads(squads):
    """Set the build of everything the watcher emits outside an explicit scope: the match being prepared or played."""
    if squads is not None and not isinstance(squads, Squads): raise ValueError('Expected the teams of a match')
    _squads[0] = squads


def installed_squads(ram):
    """The teams of the match installed in a RAM image, or None (no image, another match, the ordinary build)."""
    if not isinstance(ram, (bytes, bytearray, memoryview)) or len(ram) < SQUAD_END: return None
    magic, manager = struct.unpack_from('<2I', ram, SQUAD)
    if magic != SQUAD_MAGIC or not manager: return None
    if struct.unpack_from('<2I', ram, CONTROL) != (MAGIC, manager): return None
    table = bytes(ram[SQUAD+16:SQUAD+16+ENGINE_ACTORS])
    seats = tuple(i for i in bytes(ram[SQUAD+SQUAD_FIELDS['seats']:SQUAD+SQUAD_FIELDS['seats']+4]) if i != ABSENT)
    try: return Squads((None if t == ABSENT else t for t in table), seats)
    except ValueError: return None


def emit_team(a, out, index, scratch=None):
    """out = team of the fighter whose physical index is in a register.

    The ordinary build keeps 'andi out,index,1'. A squads build reads the team table (three words more); it needs
    a scratch register only when out is the index register itself.
    """
    if emitted_squads() is None:
        a.i(12, out, index, 1); return
    base = out if out != index else scratch
    if base is None or base in (index, 0): raise ValueError('emit_team needs a scratch register to work in place')
    a.li(base, SQUAD+SQUAD_FIELDS['team_of']); a.r(0x21, base, base, index); a.i(36, out, base, 0)


# Team features converted for three to five teams AND seen live there. Every other team feature keeps the
# free-for-all behaviour (off) in such a match.
# 'fusion' (teammates fuse in such a match) is on in the BT3 tree only: it was never seen live on this disc.
SQUAD_FEATURES = frozenset({'successor', 'takeover', 'takeover_split', 'timeover', 'hud', 'revive', 'revive_lockon',
                            'tag_attacks'})


def squad_feature(name):
    """This build is a match of three to five teams and the named team feature is on in it."""
    return emitted_squads() is not None and name in SQUAD_FEATURES


def _emit_team_bytes(a, left, right, t0, t1):
    if emitted_squads() is None: raise ValueError('Team tests are emitted in squads builds only')
    if len({left, right, t0, t1}) != 4: raise ValueError('Relationship inputs and scratch registers must differ')
    a.li(t0, SQUAD+SQUAD_FIELDS['team_of']); a.r(0x21, t1, t0, right); a.r(0x21, t0, t0, left)
    a.i(36, t0, t0, 0); a.i(36, t1, t1, 0)


def emit_same_team(a, left, right, differ, t0=8, t1=9):
    """Squads builds only, behind a gate that has just checked the live team table, for two bounded indices:
    branch to differ unless both fighters are on one team (a fighter is on its own team). Clobbers t0/t1."""
    _emit_team_bytes(a, left, right, t0, t1); a.branch(5, t0, t1, differ)


def emit_other_team(a, left, right, same, t0=8, t1=9):
    """The opposite test under the same conditions: branch to same when both fighters are on one team."""
    _emit_team_bytes(a, left, right, t0, t1); a.branch(4, t0, t1, same)


def emit_ally(a, left, right, fail, t0=8, t1=9):
    """Squads builds only: branch to fail unless the two fighters differ and share a team. Clobbers t0/t1."""
    if emitted_squads() is None: raise ValueError('emit_ally is emitted in squads builds only')
    if len({left, right, t0, t1}) != 4: raise ValueError('Relationship inputs and scratch registers must differ')
    a.branch(4, left, right, fail)
    a.li(t0, SQUAD+SQUAD_FIELDS['team_of']); a.r(0x21, t1, t0, right); a.r(0x21, t0, t0, left)
    a.i(36, t0, t0, 0); a.i(36, t1, t1, 0)
    a.branch(5, t0, t1, fail)
