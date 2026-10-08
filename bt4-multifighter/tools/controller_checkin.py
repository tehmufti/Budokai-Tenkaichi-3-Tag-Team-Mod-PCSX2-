"""Controller check-in: Player Setup's seat rules, pure (no SDL, no PINE, no clock of its own).

controller_hub owns one CheckIn on its thread and feeds it the device table and press events; the watcher only
reads copies (Hub.snapshot) and asks for changes through the hub. Every time is passed in (seconds, monotonic).

A seat's source:
  empty   - nobody yet: "Press START on your controller to join"
  default - PCSX2's own port n, players 1-2 only (pass-through)
  hub     - a controller the mod reads: the P1/P2 override drives players 1-2, the private mailboxes players 3-4
  native  - a controller matched to PCSX2 port n, in seat n (pass-through: PCSX2 keeps its mapping and rumble)
  pseudo  - a press that reached the game only through PCSX2 port n (keyboard, custom bindings; pass-through)
  classic - players 3-4 in connection order: the 3rd and 4th controller, as in beta.36

The setting controller_checkin chooses the start state (MODES). The code default is beta.36's connection order;
installs ship 'three_or_more' through player-defaults.json.
"""
import copy
import dataclasses

MODES = ('three_or_more', 'two_or_more', 'connection_order')
CODE_DEFAULT_MODE = 'connection_order'
SOURCES = ('empty', 'default', 'hub', 'native', 'pseudo', 'classic')
PASS_THROUGH = ('native', 'pseudo', 'default', 'empty')
PSEUDO = {1: 'pcsx2:1', 2: 'pcsx2:2'}       # PCSX2's own ports as press sources
JOIN_DELAY = 0.150       # a join is decided after the press-matching window (-60/+120 ms) has closed
READY_GUARD = 0.5        # Continue counts only this long after the last roster change
TAKEOVER_HOLD = 2.0      # holding START this long on a free controller takes a lost seat
RESTORE_WINDOW = 60.0    # a controller of the same model arriving this soon restores a lost seat
TWIN_WINDOW = 0.025      # mirrored copies (DS4Windows, Steam Input) press within 25 ms of each other
TWIN_CLEAR = 2           # diverging presses that clear a twin mark
START, SELECT, LEFT, RIGHT = 0x8, 0x1, 0x80, 0x20


@dataclasses.dataclass
class Device:
    """One controller in the hub's table (key = identity, controller_hub.identity_keys)."""
    key: str
    name: str = ''
    display: str = ''
    kind: str = ''
    vid: int = 0
    pid: int = 0
    guid: str = ''
    serial: str = ''
    path: str = ''
    mapped: bool = True
    connected: bool = True
    first_seen: float = 0.0
    last_active: float = 0.0
    order: int = 0               # arrival order this session
    xinput: int = None           # XInput user index when SDL reads it through XInput
    native_port: int = None      # PCSX2 port 1/2 this controller is (press matching), or None
    native_score: dict = dataclasses.field(default_factory=dict)   # port -> score
    native_misses: dict = dataclasses.field(default_factory=dict)  # port -> misses
    native_confirmed: bool = False
    twin_of: str = None


@dataclasses.dataclass
class Seat:
    number: int
    source: str = 'empty'
    key: str = None
    native_port: int = None
    team: int = 0
    lost_since: float = None
    name: str = ''               # the controller's name when it joined (lost seats, the roster line)
    model: tuple = None          # (vid, pid) for the same-model restore

    @property
    def lost(self):return self.lost_since is not None


def start_source(mode, humans, number):
    """The source a seat starts with in `mode` (MODES) for `humans` players."""
    if mode == 'connection_order':
        return 'default' if number <= 2 else 'classic'
    if mode == 'three_or_more' and humans <= 2:
        return 'default'
    return 'empty'


class Roster:
    def __init__(self, humans, mode=CODE_DEFAULT_MODE, team_mode=False):
        if mode not in MODES:mode = CODE_DEFAULT_MODE
        self.humans, self.mode, self.team_mode = humans, mode, team_mode
        self.seats = [Seat(n, start_source(mode, humans, n), team=(n-1) & 1) for n in range(1, humans+1)]
        self.hub_joined = False
        self.changed_at = 0.0

    def seat(self, number):
        return self.seats[number-1] if 1 <= number <= len(self.seats) else None

    def holder(self, key):
        """The seat whose controller (or PCSX2 port) is `key`, or None."""
        return next((s for s in self.seats if s.key == key and s.source in ('hub', 'native', 'pseudo')), None)

    def claimed(self):
        return {s.key for s in self.seats if s.key and s.source in ('hub', 'native', 'pseudo')}

    def copy(self):return copy.deepcopy(self)


def p12(roster, in_match):
    """(armed, pass_mask, keys) for the P1/P2 override.

    armed: some seat 1-2 is 'hub', or is lost during a match. A set PASS bit (k-1) leaves PCSX2's record of port k
    untouched: native, pseudo, default and empty seats, and lost seats outside a match (menus stay navigable).
    keys: the controller each overridden seat publishes (None: neutral)."""
    armed, mask, keys = False, 0, [None, None]
    for number in (1, 2):
        seat = roster.seat(number) if roster is not None else None
        if seat is None:
            mask |= 1 << (number-1); continue
        if seat.lost:
            if in_match:armed = True
            else:mask |= 1 << (number-1)
            continue
        if seat.source == 'hub':
            armed = True; keys[number-1] = seat.key
        else:
            mask |= 1 << (number-1)
    return armed, mask, tuple(keys)


def classic_order(devices):
    """Connected, mapped, non-twin controllers in beta.36's order: XInput slots first, then arrival."""
    rows = [d for d in devices.values() if d.connected and d.mapped and not d.twin_of]
    return sorted(rows, key=lambda d: (0, d.xinput, d.order) if d.xinput is not None else (1, d.order, 0))


def classic_keys(devices, roster=None):
    """Players 3 and 4 in connection order: the 3rd and 4th controllers, skipping confirmed PCSX2 ports and claimed ones."""
    claimed = roster.claimed() if roster is not None else set()
    return [d.key for d in classic_order(devices)[2:] if not d.native_confirmed and d.key not in claimed][:2]


def private(roster, devices=None):
    """(P3 key, P4 key): the controllers of seats 3 and 4 (None: neutral)."""
    keys, classic = [], classic_keys(devices or {}, roster)
    for number in (3, 4):
        seat = roster.seat(number) if roster is not None else None
        if seat is None or seat.lost:keys.append(None)
        elif seat.source in ('hub', 'native'):keys.append(seat.key)
        elif seat.source == 'classic':keys.append(classic[number-3] if number-3 < len(classic) else None)
        else:keys.append(None)
    return tuple(keys)


def extras(devices, roster=None, exclude=()):
    """'Allow all controllers during character selection' with fewer than 3 humans: the two most recently active
    free controllers (not claimed, mapped, not a twin, not a PCSX2 port).

    A PCSX2 port that still drives its player (its seat is not overridden by a mod-read controller) and whose
    controller press matching has not identified yet is assumed to be the next free controller in connection order,
    as beta.36 assumed with its 3rd and 4th controllers: otherwise the most active controller, player 1's own, would
    also move a second cursor (every press counted twice)."""
    claimed = roster.claimed() if roster is not None else set()
    order = classic_order(devices)
    live = [k for k in (1, 2) if roster is None or roster.seat(k) is None or roster.seat(k).source != 'hub']
    known = {d.native_port for d in order if d.native_port is not None}
    missing = sum(1 for k in live if k not in known)
    rows = [d for d in order if d.native_port is None and d.key not in claimed][missing:]
    rows = [d for d in rows if d.key not in exclude]
    rows.sort(key=lambda d: (-d.last_active, d.order))
    keys = [d.key for d in rows[:2]]
    return tuple(keys+[None]*(2-len(keys)))


def filled(roster, seat):
    if seat.lost:return False
    if seat.source == 'default':return not roster.hub_joined
    return seat.source in ('hub', 'native', 'pseudo', 'classic')


def ready(roster, now):
    """Every seat is filled (default only while nobody joined with a mod-read controller), none is lost, and the
    roster has not changed for READY_GUARD seconds."""
    return (roster is not None and all(filled(roster, s) for s in roster.seats)
            and now-roster.changed_at >= READY_GUARD)


def waiting(roster):
    """Seat numbers still to be filled."""
    return [s.number for s in roster.seats if not filled(roster, s)] if roster is not None else []


class CheckIn:
    """The roster and its rules. Messages are (level, code, template, values) for the Play window; notices are
    (kind, values) for the panel (newest last); claims are (key, bit) the hub masks until released."""
    def __init__(self, mode=CODE_DEFAULT_MODE, keep=True):
        self.mode, self.keep = mode, keep
        self.roster = None          # the roster in use (a match) or being edited (Player Setup)
        self.setup = False          # Player Setup is open: joins, leaves and team changes
        self.committed = None       # the last Continue (kept for later matches while keep is on)
        self.fresh = False          # the roster was committed by Player Setup for the coming selection
        self.pending = []           # START edges waiting JOIN_DELAY: (time, key)
        self.holds = {}             # key -> START held since (free controllers)
        self.history = []           # recent down edges (time, key, bit) for twins
        self.twin_divergence = {}   # key -> diverging presses since marked
        self.present = set()        # keys connected at the previous step
        self.reported_lost = set()  # seat numbers reported this match
        self.reported_double = set()  # (key, port) reported this session
        self.reported_unmapped = set()  # GUIDs reported this session
        self.messages, self.notices, self.claims, self.log = [], [], [], []

    # ---- roster lifecycle (the watcher, through the hub) ----------------------------------------------------------
    def open(self, humans, team_mode, now, devices, *, mode=None, keep=None):
        """Player Setup opened: a fresh roster, pre-filled from the kept check-ins whose controllers are connected."""
        if mode is not None:self.mode = mode
        if keep is not None:self.keep = keep
        roster = Roster(humans, self.mode, team_mode)
        if self.keep and self.committed is not None:
            for kept in self.committed.seats[:humans]:
                seat = roster.seat(kept.number)
                if kept.lost:continue
                if kept.source in ('hub', 'native') and kept.key in devices and devices[kept.key].connected:
                    seat.source, seat.key, seat.native_port = kept.source, kept.key, kept.native_port
                    seat.name, seat.model = kept.name, kept.model
                    roster.hub_joined |= kept.source == 'hub'
                elif kept.source == 'pseudo':
                    seat.source, seat.key, seat.native_port, seat.name = 'pseudo', kept.key, kept.native_port, kept.name
            if roster.hub_joined:
                for seat in roster.seats:
                    if seat.source == 'default':seat.source = 'empty'
        roster.changed_at = now
        self.roster, self.setup, self.fresh, self.pending, self.holds = roster, True, False, [], {}
        return roster

    def clear(self, now):
        """Clear check-ins: every seat back to the mode's start state."""
        if self.roster is None:return
        roster = Roster(self.roster.humans, self.roster.mode, self.roster.team_mode)
        for seat, old in zip(roster.seats, self.roster.seats):seat.team = old.team
        roster.changed_at = now
        self.roster, self.pending = roster, []

    def close(self, commit, now):
        """Player Setup closed: Continue commits the roster, Back drops the draft."""
        self.setup, self.pending = False, []
        if commit and self.roster is not None:
            self.committed, self.fresh = self.roster.copy(), True
            self.reported_lost.clear()
        else:
            self.roster, self.fresh = (self.committed.copy() if self.committed is not None else None), False

    def select(self, humans, via_setup, now, devices, *, mode=None, keep=None):
        """A pager selection: the committed roster when Player Setup just committed it, otherwise the kept roster
        when it covers every player with a connected controller, otherwise connection order (beta.36)."""
        if mode is not None:self.mode = mode
        if keep is not None:self.keep = keep
        if via_setup and self.fresh and self.roster is not None and self.roster.humans == humans:
            self.fresh = False; return self.roster
        self.fresh = False
        kept = self.committed if self.keep else None
        if kept is not None and kept.humans >= humans and all(
                s.source == 'pseudo' or (s.source in ('hub', 'native') and s.key in devices and devices[s.key].connected)
                or s.source in ('default', 'classic') for s in kept.seats[:humans]):
            roster = kept.copy(); roster.seats = roster.seats[:humans]; roster.humans = humans
        else:
            roster = Roster(humans, 'connection_order')
        roster.changed_at = now
        self.roster = roster
        self.reported_lost.clear()
        return roster

    def set_team(self, number, team, now):
        seat = self.roster.seat(number) if self.roster is not None else None
        if seat is not None and seat.team != team:seat.team = team; self.roster.changed_at = now

    def new_match(self):
        self.reported_lost.clear()

    # ---- the rules (the hub thread, each poll) --------------------------------------------------------------------
    def step(self, now, devices, events, *, in_match=False, labels=None):
        """Apply presses and connection changes. events: (time, key, 'down'|'up', bit) in time order, PCSX2 ports as
        PSEUDO keys (pseudo presses only). labels: {port: name} of controllers without a layout seen with a pseudo
        press (they name a pseudo seat)."""
        self._presence(now, devices, in_match)
        for t, key, kind, bit in events:
            if kind == 'down':
                self.history.append((t, key, bit))
                self._down(t, key, bit, devices)
            elif key in self.holds and bit == START:
                del self.holds[key]
        self.history = [h for h in self.history if now-h[0] <= 1.0]
        self._twins_diverge(now, devices)
        due = [p for p in self.pending if now-p[0] >= JOIN_DELAY]
        self.pending = [p for p in self.pending if now-p[0] < JOIN_DELAY]
        for t, key in due:self._decide(t, key, now, devices, labels or {})
        self._takeover(now, devices)
        self._double_drive(devices)

    def _presence(self, now, devices, in_match):
        connected = {k for k, d in devices.items() if d.connected}
        gone, back = self.present-connected, connected-self.present
        self.present = connected
        roster = self.roster
        if roster is None:return
        for seat in roster.seats:
            if seat.source in ('hub', 'native') and seat.key in gone and not seat.lost:
                seat.lost_since = now; roster.changed_at = now
                self.log.append(f'Player {seat.number} lost {seat.name or seat.key}.')
                if seat.number not in self.reported_lost:
                    self.reported_lost.add(seat.number)
                    self.messages.append(('warning', 'TTM-CTRL-22', 'lost', dict(n=seat.number, name=seat.name or seat.key)))
                self.notices.append(('lost', dict(n=seat.number, name=seat.name or seat.key)))
        for seat in roster.seats:
            if seat.lost and seat.key in back:
                self._restore(seat, devices[seat.key], now)
        claimed = roster.claimed()
        for seat in roster.seats:
            if not seat.lost or seat.model is None:continue
            fresh = [devices[k] for k in back if k not in claimed and devices[k].mapped and not devices[k].twin_of
                     and (devices[k].vid, devices[k].pid) == seat.model and now-seat.lost_since <= RESTORE_WINDOW]
            if len(fresh) == 1:
                seat.key = fresh[0].key; self._restore(seat, fresh[0], now); claimed.add(seat.key)

    def _restore(self, seat, device, now):
        seat.lost_since = None; seat.name = device.display or device.name or seat.name
        self.roster.changed_at = now
        self.messages.append(('info', None, 'back', dict(n=seat.number, name=seat.name)))   # the Play window's INFO line

    def _down(self, t, key, bit, devices):
        roster, device = self.roster, devices.get(key)
        if device is not None and device.twin_of:return
        holder = roster.holder(key) if roster is not None else None
        pseudo = key in PSEUDO.values()
        if bit == START and holder is None and not pseudo:
            self.holds[key] = t
        if not self.setup or roster is None:return
        if bit == START and holder is None:
            if pseudo or (device is not None and device.mapped):self.pending.append((t, key))
            elif device is not None and device.guid not in self.reported_unmapped:
                self._unmapped(device)
        elif device is not None and not device.mapped and not pseudo and device.guid not in self.reported_unmapped:
            self._unmapped(device)
        elif bit == SELECT and holder is not None:
            self._leave(holder, t)
        elif bit in (LEFT, RIGHT) and holder is not None and holder.number >= 2 and roster.team_mode:
            holder.team ^= 1; roster.changed_at = t

    def _unmapped(self, device):
        self.reported_unmapped.add(device.guid)
        values = dict(name=device.display or device.name, guid=device.guid)
        self.messages.append(('warning', 'TTM-CTRL-21', 'unmapped', values))
        self.notices.append(('unmapped', values))

    def _leave(self, seat, now):
        roster = self.roster
        seat.source, seat.key, seat.native_port, seat.name, seat.model, seat.lost_since = 'empty', None, None, '', None, None
        self.log.append(f'Player {seat.number} left.')
        if not any(s.source in ('hub', 'pseudo') for s in roster.seats):
            roster.hub_joined = False
            for other in roster.seats:
                start = start_source(roster.mode, roster.humans, other.number)
                if other.source == 'empty' and start in ('default', 'classic'):other.source = start
        roster.changed_at = now

    def _twins(self, t, key, devices):
        """Other controllers with the same START press within TWIN_WINDOW of (t, key)."""
        return [k for (when, k, bit) in self.history if bit == START and k != key and abs(when-t) <= TWIN_WINDOW
                and k in devices and devices[k].mapped]

    def _decide(self, t, key, now, devices, labels):
        roster = self.roster
        if roster is None or not self.setup or roster.holder(key) is not None:return
        if key in PSEUDO.values():
            port = int(key.split(':')[1]); seat = roster.seat(port)
            if seat is None:return
            if seat.source in ('empty', 'default') or seat.lost:
                seat.source, seat.key, seat.native_port, seat.lost_since = 'pseudo', key, port, None
                seat.name, seat.model = labels.get(port, ''), None
                roster.changed_at = now
                self.log.append(f'Check-in: player {port} <- PCSX2 port {port} ({labels.get(port) or "keyboard or custom binding"}).')
            elif seat.source in ('hub', 'native'):
                self.notices.append(('keyboard_taken', dict(k=port)))
            return
        device = devices.get(key)
        if device is None or not device.connected or not device.mapped or device.twin_of:return
        twins = self._twins(t, key, devices)
        if twins:
            group = [devices[k] for k in twins]+[device]
            claimed = roster.claimed()
            held = [d for d in group if d.key in claimed]
            keep = held[0] if held else sorted(group, key=lambda d: (not d.serial, d.first_seen, d.order))[0]
            for other in group:
                if other is not keep and other.twin_of != keep.key:
                    other.twin_of = keep.key; self.twin_divergence[other.key] = 0
                    values = dict(name=keep.display or keep.name)
                    self.messages.append(('warning', 'TTM-CTRL-23', 'twin', values))
                    self.notices.append(('twin', values))
                    self.log.append(f'Controller {other.display or other.key} mirrors {keep.display or keep.key}: ignored.')
            if keep is not device or keep.key in claimed:return
            self.pending = [p for p in self.pending if p[1] not in twins]
        self._join(device, now)

    def _join(self, device, now, *, takeover=False):
        roster = self.roster
        port = device.native_port
        seat = roster.seat(port) if port else None
        # A takeover (START held 2 s on a free controller) takes the lowest lost seat as a mod-read seat, never a
        # pass-through one: only a mod-read seat masks the held START, so the match does not pause.
        if not takeover and seat is not None and (seat.source in ('empty', 'default') or seat.lost):
            source = 'native'
        else:
            source = 'hub'
            lost = [s for s in roster.seats if s.lost]
            if takeover and seat is not None and seat.lost:
                # Its own PCSX2 port's seat first: overridden by the mod, so the pad never moves two players.
                lost = [seat]+[s for s in lost if s is not seat]
            empty_high = [s for s in roster.seats if s.source == 'empty' and not s.lost and s.number >= 3]
            empty_low = [s for s in roster.seats if s.source == 'empty' and not s.lost and s.number <= 2]
            default_high = [s for s in roster.seats if s.source in ('default', 'classic') and not s.lost and s.number >= 3]
            default_low = [s for s in roster.seats if s.source == 'default' and not s.lost and s.number <= 2]
            order = lost+([] if takeover else empty_high+empty_low+default_high+default_low)
            if not order:return None
            seat = order[0]
        name = device.display or device.name or device.key
        seat.source, seat.key, seat.lost_since, seat.name = source, device.key, None, name
        seat.native_port, seat.model = (port if source == 'native' else None), (device.vid, device.pid)
        if source == 'hub' and not roster.hub_joined:
            roster.hub_joined = True
            for other in roster.seats:
                if other is not seat and other.source == 'default':other.source = 'empty'
        roster.changed_at = now
        self.claims.append((device.key, START))
        self.holds.pop(device.key, None)
        self.log.append(f'Check-in: player {seat.number} <- {name} ('
                        + (f'PCSX2 port {port}, pass-through' if source == 'native' else 'read by the mod') + ').')
        if takeover:self.messages.append(('info', None, 'back', dict(n=seat.number, name=name)))
        return seat

    def _takeover(self, now, devices):
        roster = self.roster
        if roster is None or not any(s.lost for s in roster.seats):return
        for key, since in sorted(self.holds.items(), key=lambda item: item[1]):
            device = devices.get(key)
            if (now-since >= TAKEOVER_HOLD and device is not None and device.connected and device.mapped
                    and not device.twin_of and roster.holder(key) is None):
                own = roster.seat(device.native_port) if device.native_port else None
                if own is not None and not own.lost and own.source in PASS_THROUGH:
                    # PCSX2 already passes this controller's port to that player: a takeover would make one
                    # controller move two players (its held START is that player's own pause).
                    self.holds.pop(key, None)
                    continue
                if self._join(device, now, takeover=True) is not None:
                    self.holds.pop(key, None)
                if not any(s.lost for s in roster.seats):break

    checked_until = 0.0         # down edges up to this time were compared between twins

    def _twins_diverge(self, now, devices):
        """A twin whose presses differ from its partner's TWIN_CLEAR times is a separate controller after all."""
        horizon = now-TWIN_WINDOW
        for t, key, bit in self.history:
            if not self.checked_until < t <= horizon:continue
            device = devices.get(key)
            pairs = []
            if device is not None and device.twin_of:pairs.append((key, device.twin_of))
            pairs += [(k, key) for k, d in devices.items() if d.twin_of == key]
            for twin, primary in pairs:
                partner = primary if key == twin else twin
                if any(k == partner and b == bit and abs(t2-t) <= TWIN_WINDOW for t2, k, b in self.history):continue
                seen = self.twin_divergence.get(twin, 0)+1
                self.twin_divergence[twin] = seen
                if seen >= TWIN_CLEAR and devices.get(twin) is not None:
                    devices[twin].twin_of = None; self.twin_divergence.pop(twin, None)
                    self.log.append(f'Controller {devices[twin].display or twin} is no longer treated as a mirror.')
        self.checked_until = max(self.checked_until, horizon)

    def _double_drive(self, devices):
        roster = self.roster
        if roster is None:return
        for seat in roster.seats:
            if seat.source != 'hub' or seat.lost:continue
            device = devices.get(seat.key)
            if device is None or not device.native_confirmed or device.native_port in (None, seat.number):continue
            port = device.native_port; other = roster.seat(port)
            through = other is None or other.source in PASS_THROUGH
            if through and (seat.key, port) not in self.reported_double:
                self.reported_double.add((seat.key, port))
                values = dict(name=seat.name or seat.key, n=seat.number, k=port)
                self.messages.append(('warning', 'TTM-CTRL-24', 'double', values))
                self.notices.append(('double', values))

    def take(self):
        """(messages, notices, claims, log lines) since the last call."""
        out = (self.messages, self.notices, self.claims, self.log)
        self.messages, self.notices, self.claims, self.log = [], [], [], []
        return out


def roster_line(roster, devices):
    """The watcher-log roster at Continue: 'Players: P1 ... (pass-through); P2 ... (mod); ...'."""
    parts = []
    classic = classic_keys(devices, roster)
    for seat in roster.seats:
        if seat.source == 'native':text = f'{seat.name} via PCSX2 port {seat.number} (pass-through)'
        elif seat.source == 'pseudo':text = f'{seat.name or "keyboard or custom binding"} via PCSX2 port {seat.number} (pass-through)'
        elif seat.source == 'default':text = f'PCSX2 controller {seat.number} (pass-through)'
        elif seat.source == 'hub':text = f'{seat.name} (mod)'
        elif seat.source == 'classic':
            index = seat.number-3
            key = classic[index] if index < len(classic) else None
            text = (f'{devices[key].display} (mod, connection order)' if key in devices else 'none (connection order)')
        else:text = 'empty'
        if seat.lost:text += ' (lost)'
        parts.append(f'P{seat.number} {text}')
    return 'Players: '+'; '.join(parts)+'.'
