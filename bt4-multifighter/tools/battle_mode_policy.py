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


def human_seats(mode, humans, present=None, assignment=None):
    """Controller order in physical actor space, shared by every installer."""
    if mode not in ('teams','ffa','coop','training','training_coop') or humans not in HUMAN_COUNTS:
        raise ValueError('Invalid match mode/human count')
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


def enemy(mode, left, right):
    if mode not in MODES: raise ValueError('Unknown battle mode')
    return left != right and (mode == 'ffa' or (left & 1) != (right & 1))


def targets(mode, count, present):
    if mode not in MODES or count not in ACTOR_COUNTS or present & 3 != 3 or present >> count:
        raise ValueError('Invalid captured mode/participation')
    result=[]
    for i in range(count):
        choices=[j for j in range(count) if present & (1 << j) and enemy(mode,i,j)]
        if not choices: raise ValueError('Each fighter requires another contestant')
        result.append(i ^ 1 if i ^ 1 in choices else choices[0])
    return result


def prepare_singleton(mode, humans):
    """Reserve inactive parity slots when a custom mode changes a 1v1 match.

    The ordinary Team Battle selection keeps its native controller choices.
    Explicit CPU-only and two-player choices must also prepare 1v1 so their
    controller policy is installed even if Duel was set up differently.
    """
    return mode in ('ffa','training') or (mode == 'teams' and humans != 1)


def validate_roster(mode, count, present, humans, assignment=None):
    """Validate capture capacity and human ownership, returning selected counts.

    Native parity slots stay reserved even when one side has fewer fighters.
    Co-op needs physical 0 and 2 for its humans; any nonempty opposing roster
    within the same engine capacity is supported.
    """
    if type(count) is not int or type(present) is not int or present < 0:
        raise ValueError('Invalid captured mode/participation')
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
