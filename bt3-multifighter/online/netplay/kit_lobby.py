"""The online lobby of kit 2.0: the room, its members and the match the host builds on the spot. The host is
authoritative: every change is made on the host and sent to every member as a full LOBBY snapshot.

Room:     {id, name, type:'versus', max_members}; 'type' leaves room for other session types (an in-level hub) later.
Members:  member 1 is the host; each guest gets the next id when it joins and keeps it until it leaves. Joining never
          means playing: a new member is a SPECTATOR until it claims a player slot. Names are 'Player N' (the lowest
          free number) unless the member sent its own lobby name; anyone can rename themselves (never the PC's name).
Match:    {mode:'teams'|'ffa', teams:[[{character, costume, owner}, ...], [...]], stage, bgm, native, gameplay,
          services}: built by the host on the spot (any fighters, colours, stage, music and rules; no presets).
          Three to five teams: the match also holds team_count (3..5) and every fighter its team (0..4); the two
          lists stay the native columns, laid out by the mod's squad_layout on the host. Two teams hold neither. A
          fighter's owner is the member who plays it (None: CPU). Kit 2.1: ANY fighter can be claimed (up to ten
          players, one per fighter of the 5 v 5 engine); every unclaimed fighter is a CPU the host chooses. The host
          can lock a fighter (nobody may claim it: it stays a CPU) and remove a member from the room.
Players:  a member who owns a fighter. It may change its own fighter and colour; the host may change everything.
          Players press Ready; spectators never need to. The host starts the match when every player is ready.
          Any change by the host (rules, stage, team sizes, another player's fighter) clears every Ready, with a
          notice naming the change.
Messages (protocol 5):
  LOBBY (host -> every member): {rev, phase, room, members:[...], match:{...}, locked:{...}, notice, warm, delay_hint,
          vote}   (a full snapshot, at most 8 KB; rev rises by 1 on every change)
  guest -> host (untrusted, the host checks each): NAME {name} | CLAIM {team, index} | CLAIM_TEAM {team} |
          UNCLAIM {} |
          FIGHTER {team, index, character, costume} | READY {ready} | CHAT {text}
"""
import copy
import json
import secrets
import time

import kit_settings
import kit_spec

PHASES = ('lobby', 'preparing', 'sending', 'loading', 'fight', 'results')
NOTICE_KEEP = 3.0                            # seconds a refusal notice survives changes without a notice
MAX_MEMBERS = 16                  # kit 2.1: up to ten players and the spectators
CHAT_MAX = 200
MAX_BYTES = 12288
HOST = 1
LOCK_WHY = 'the host locked this fighter (it stays a CPU)'
LOCKED = {}                       # (three or more teams were locked here until the mod could play them)
TEAM_DEFAULT = 2                  # fighters of a team the host adds


def member(ident, name, role='guest', lang='en'):
    return dict(id=ident, name=name, role=role, lang=lang, ready=False, rtt_ms=None, connected=True,
                can_prepare=False)


def default_match(catalog=None, rng=None):
    """Two teams of one: random fighters when a catalog is given (a fresh lobby is never empty)."""
    teams = []
    for _ in range(2):
        if catalog is not None:
            c, k = kit_spec.random_fighter(catalog, rng)
        else:
            c, k = 0, 0
        teams.append([dict(character=c, costume=k, owner=None)])
    return dict(type='versus', mode='teams', teams=teams, stage=0, bgm=kit_spec.DEFAULT_BGM,
                native=dict(kit_spec.DEFAULT_NATIVE), gameplay={}, services={k: False for k in kit_spec.SERVICES})


class Lobby:
    def __init__(self, host_name='Player 1', room=None, catalog=None, rules=None, lang='en', rng=None):
        self.rev = 0
        self.phase = 'lobby'
        self.room = room or dict(id=secrets.token_hex(4), name=f'{host_name}\'s room', type='versus',
                                 max_members=MAX_MEMBERS)
        self.members = {HOST: member(HOST, host_name, 'host', lang)}
        self.match = default_match(catalog, rng)
        if rules:
            self.apply_rules(rules)
        self.locked = dict(LOCKED)
        self.notice = None
        self.warm = dict(state='none', eta_s=None)
        self.delay_hint = None
        self.vote = None
        self.hub = None                   # the running hub: scoreboard, challenges (kit_hub), else None
        self.return_to_hub = False
        self.next_id = HOST + 1
        self.catalog = catalog

    # ---- snapshot -------------------------------------------------------------------------------------------------
    def snapshot(self):
        return dict(rev=self.rev, phase=self.phase, room=self.room,
                    members=[self.members[k] for k in sorted(self.members)], match=self.match, locked=self.locked,
                    notice=self.notice, warm=self.warm, delay_hint=self.delay_hint, vote=self.vote, hub=self.hub, return_to_hub=self.return_to_hub)

    def size(self):
        return len(json.dumps(self.snapshot(), separators=(',', ':')))

    @classmethod
    def from_snapshot(cls, snap):
        lobby = cls.__new__(cls)
        lobby.catalog = None
        lobby.next_id = 0
        lobby.apply(snap)
        return lobby

    def apply(self, snap):
        """A guest takes the host's snapshot (all or nothing: a malformed one raises ValueError, nothing changes)."""
        problem = snapshot_problem(snap)
        if problem:
            raise ValueError(f'malformed LOBBY snapshot: {problem}')
        self.rev, self.phase = snap['rev'], snap.get('phase', 'lobby')
        self.room = snap.get('room') or {}
        self.members = {m['id']: m for m in snap['members']}
        self.match = snap['match']
        self.locked = snap.get('locked') or {}
        self.notice = snap.get('notice')
        self.warm = snap.get('warm') or {}
        self.delay_hint = snap.get('delay_hint')
        self.vote = snap.get('vote')
        self.hub = snap.get('hub')
        self.return_to_hub = bool(snap.get('return_to_hub'))

    def bump(self, notice=None):
        self.rev += 1
        if notice is None and (self.notice or {}).get('code') and \
                time.monotonic() - getattr(self, 'noticed', 0.0) < NOTICE_KEEP:
            return self.rev                      # a refusal just made: the next silent change does not hide it
        self.notice = notice
        self.noticed = time.monotonic()
        return self.rev

    # ---- members ----------------------------------------------------------------------------------------------------
    def default_name(self):
        used = {m['name'] for m in self.members.values()}
        n = 1
        while f'Player {n}' in used:
            n += 1
        return f'Player {n}'

    def unique_name(self, name, ident=None):
        name = kit_settings.clean_name(name)
        if not name:
            return None
        used = {m['name'].lower() for k, m in self.members.items() if k != ident}
        if name.lower() not in used:
            return name
        for n in range(2, 99):
            candidate = f'{name[:kit_settings.NAME_MAX - 4]} ({n})'
            if candidate.lower() not in used:
                return candidate
        return None

    def join(self, name_hint='', lang='en'):
        """A new member (a spectator); returns its id, or None when the room is full."""
        if len(self.members) >= self.room.get('max_members', MAX_MEMBERS):
            return None
        ident = self.next_id
        self.next_id += 1
        name = self.unique_name(name_hint) or self.default_name()
        self.members[ident] = member(ident, name, 'guest', lang if lang in ('en', 'es') else 'en')
        self.bump(dict(code=None, key='notice.joined', args=dict(name=name)))
        return ident

    def leave(self, ident):
        m = self.members.pop(ident, None)
        if m is None:
            return None
        for team in self.match['teams']:
            for f in team:
                if f.get('owner') == ident:
                    f['owner'] = None
        if self.phase in ('preparing', 'sending', 'loading') and self.players() == []:
            pass
        self.bump(dict(code=None, key='notice.left', args=dict(name=m['name'])))
        return m

    def rename(self, ident, name):
        m = self.members.get(ident)
        name = self.unique_name(name, ident)
        if m is None or not name or name == m['name']:
            return False
        old, m['name'] = m['name'], name
        self.bump(dict(code=None, key='notice.renamed', args=dict(old=old, name=name)))
        return True

    def owner_of(self, team, index):
        try:
            return self.match['teams'][team][index].get('owner')
        except (IndexError, TypeError):
            return None

    def slot_of(self, ident):
        """(team, index) of the fighter a member plays, or None (a spectator)."""
        for t, team in enumerate(self.match['teams']):
            for i, f in enumerate(team):
                if f.get('owner') == ident:
                    return t, i
        return None

    def players(self):
        return [k for k in sorted(self.members) if self.slot_of(k) is not None]

    def spectators(self):
        return [k for k in sorted(self.members) if self.slot_of(k) is None]

    # ---- two to five teams ------------------------------------------------------------------------------------------
    def team_count(self):
        return self.match.get('team_count') or 2

    def logical(self):
        """[[fighter, ...] per team]: every team's fighters in physical order (two teams: the two columns)."""
        return [[self.match['teams'][c][i] for c, i in members] for members in kit_spec.team_members(self.match)]

    def label_of(self, column, index):
        """(team number, fighter number) as the players see them, both from 1."""
        for t, members in enumerate(kit_spec.team_members(self.match)):
            if (column, index) in members:
                return t + 1, members.index((column, index)) + 1
        return column + 1, index + 1

    def place(self, logical):
        """Put the teams on the two native columns. Two teams are the columns themselves (no team field is
        left); three to five are laid out by the mod's squad_layout and every fighter then names its team."""
        if len(logical) == 2:
            for team in logical:
                for f in team:
                    f.pop('team', None)
            self.match['teams'] = [list(logical[0]), list(logical[1])]
            self.match.pop('team_count', None)
            return
        layout = kit_spec.squad_policy().squad_layout(tuple(len(team) for team in logical))
        slots = {}
        for t, team in enumerate(logical):
            for f, physical in zip(team, layout.members(t)):
                f['team'] = t
                slots[physical] = f
        self.match['teams'] = [[slots[i] for i in sorted(slots) if i & 1 == column] for column in (0, 1)]
        self.match['team_count'] = len(logical)

    @staticmethod
    def _sizes_fit(logical):
        sizes = [len(team) for team in logical]
        if len(logical) == 2:
            return not kit_spec.layout_problems('teams', sizes)
        return not kit_spec.team_sizes_problems(sizes)

    def _fit(self, logical):
        """Drop fighters until the teams can be played: a CPU fighter of the largest team first, a player's only
        when no CPU fighter is left there. Returns the members who lost their fighter."""
        lost = []
        while not self._sizes_fit(logical):
            order = [t for t in sorted(range(len(logical)), key=lambda t: (-len(logical[t]), -t))
                     if len(logical[t]) > 1]
            if not order:
                break
            team = next((t for t in order if any(f.get('owner') is None for f in logical[t])), order[0])
            cpu = [i for i, f in enumerate(logical[team]) if f.get('owner') is None]
            f = logical[team].pop(cpu[-1] if cpu else -1)
            if f.get('owner') is not None:
                lost.append(f['owner'])
        return lost

    def set_team_count(self, count, catalog, rng=None):
        """Host: two to five teams. A new team gets TEAM_DEFAULT random CPU fighters; a team that goes away gives
        its players (with their fighters) to the smallest remaining teams, so nobody loses a fighter while there
        is room. Returns [problems]."""
        m = self.match
        if type(count) is not int or not 2 <= count <= kit_spec.TEAMS_MAX:
            return ['two to five teams can be played']
        if m.get('type', 'versus') == 'hub':
            return ['the hub is free-for-all']
        if count >= kit_spec.TEAMS_MIN and kit_spec.squad_policy() is None:
            return ['this Tag Team Mod cannot play three to five teams (update it)']
        current = self.team_count()
        if count == current and (count == 2 or m['mode'] == 'teams'):
            return []
        logical = self.logical()
        lost = []
        if count < current:
            moved = [f for team in logical[count:] for f in team if f.get('owner') is not None]
            logical = logical[:count]
            for f in moved:
                order = sorted(range(count), key=lambda t: (len(logical[t]), t))
                room = sum(len(team) for team in logical) < kit_spec.FIGHTERS_MAX
                target = next((t for t in order if room and len(logical[t]) < kit_spec.TEAM_MAX), None)
                if target is None:                    # every team is full: the player replaces a CPU fighter
                    target = next((t for t in order if any(x.get('owner') is None for x in logical[t])), None)
                    if target is None:
                        lost.append(f['owner'])
                        continue
                    cpu = [i for i, x in enumerate(logical[target]) if x.get('owner') is None]
                    logical[target].pop(cpu[-1])
                logical[target].append(f)
        else:
            for _ in range(count - current):
                team = []
                for _ in range(TEAM_DEFAULT):
                    c, k = kit_spec.random_fighter(catalog, rng) if catalog is not None else (0, 0)
                    team.append(dict(character=c, costume=k, owner=None))
                logical.append(team)
        lost += self._fit(logical)
        if count >= kit_spec.TEAMS_MIN:
            m['mode'] = 'teams'
        self.place(logical)
        self.clear_ready()
        self.bump(dict(code=None, key='notice.rule_changed', args=dict(rule='rule.teams', value=count)))
        return []

    def claim_team(self, ident, team):
        """Member `ident` joins `team`: it plays that team's first free fighter. Returns [problems]."""
        if ident not in self.members:
            return ['not a member']
        members = kit_spec.team_members(self.match)
        if type(team) is not int or team not in range(len(members)):
            return ['no such team']
        if self.slot_of(ident) in members[team]:
            return []                                 # already on that team
        for column, index in members[team]:
            f = self.match['teams'][column][index]
            if f.get('owner') is None and not f.get('locked'):
                return self.claim(ident, column, index)
        return [f'team {team + 1} has no free fighter']

    def claimable(self, team, index=0):
        """None when a member may claim that fighter, else why not."""
        if team not in range(len(self.match['teams'])):
            return 'no such team'
        if index not in range(len(self.match['teams'][team])):
            return 'no such fighter'
        if self.match['teams'][team][index].get('locked'):
            return LOCK_WHY
        return None

    def lock(self, team, index, locked=True):
        """Host: lock a fighter (nobody may claim it; its player, if any, becomes a spectator) or unlock it."""
        try:
            f = self.match['teams'][team][index]
        except (IndexError, TypeError):
            return ['no such fighter']
        if bool(f.get('locked')) == bool(locked):
            return []
        owner = f.get('owner')
        if locked:
            f['locked'] = True
            if owner is not None:
                self.unclaim(owner, bump=False)
        else:
            f.pop('locked', None)
        shown = self.label_of(team, index)
        self.bump(dict(code=None, key='notice.locked' if locked else 'notice.unlocked',
                       args=dict(team=shown[0], index=shown[1])))
        return []

    def humans(self):
        """[(slot, team, index, member id)] of the claimed fighters (slot = 2 x index + team)."""
        out = []
        for t, team in enumerate(self.match['teams']):
            for i, f in enumerate(team):
                if f.get('owner') in self.members:
                    out.append((kit_spec.slot_of(t, i), t, i, f['owner']))
        return sorted(out)

    def claim(self, ident, team, index=0):
        """Member `ident` plays fighter `index` of `team` (it gives up any other). Returns [problems]."""
        if ident not in self.members:
            return ['not a member']
        why = self.claimable(team, index)
        if why:
            return [why]
        owner = self.owner_of(team, index)
        if owner is not None and owner != ident:
            return [f'{self.members[owner]["name"]} already plays it']
        self.unclaim(ident, bump=False)
        self.match['teams'][team][index]['owner'] = ident
        self.members[ident]['ready'] = False
        shown = self.label_of(team, index)
        self.bump(dict(code=None, key='notice.claimed', args=dict(name=self.members[ident]['name'], team=shown[0],
                                                                  index=shown[1])))
        return []

    def unclaim(self, ident, bump=True):
        at = self.slot_of(ident)
        if at is None:
            return False
        self.match['teams'][at[0]][at[1]]['owner'] = None
        if ident in self.members:
            self.members[ident]['ready'] = False
        if bump:
            self.bump(dict(code=None, key='notice.spectating', args=dict(name=self.members[ident]['name'])))
        return True

    def set_ready(self, ident, value):
        m = self.members.get(ident)
        if m is None or self.slot_of(ident) is None:
            return False
        m['ready'] = bool(value)
        self.bump()
        return True

    def clear_ready(self):
        for m in self.members.values():
            m['ready'] = False

    def all_ready(self):
        """Every player (the host excepted: its Start is its ready) pressed Ready."""
        return all(self.members[k]['ready'] for k in self.players() if k != HOST)

    # ---- the match (the host edits; a player edits only its own fighter) ----------------------------------------------
    def set_fighter(self, ident, team, index, character, costume, catalog, potaras=None):
        """Returns [problems]. The host may set any fighter; a player only the one it plays."""
        if type(team) is not int or type(index) is not int or team not in (0, 1) or index < 0:
            return ['no such fighter']
        try:
            f = self.match['teams'][team][index]
        except (IndexError, TypeError):
            return ['no such fighter']
        if ident != HOST and f.get('owner') != ident:
            return ['you can only choose your own fighter']
        items = f.get('potaras', []) if potaras is None else potaras
        found = kit_spec.fighter_problems(dict(character=character, costume=costume, potaras=items), catalog,
                                          f'team {team + 1} fighter {index + 1}')
        if found:
            self.bump(dict(code='TTM-NET-29', key='notice.invalid_pick', args=dict(what='; '.join(found[:3]))))
            return found
        if (f['character'], f['costume'], f.get('potaras', [])) == (int(character), int(costume), sorted(items)):
            return []
        f['character'], f['costume'] = int(character), int(costume)
        f['potaras'] = sorted(items)
        if ident == HOST and f.get('owner') not in (None, HOST):
            self.clear_ready()
            self.bump(dict(code=None, key='notice.host_changed_fighter',
                           args=dict(team=self.label_of(team, index)[0])))
        else:
            if f.get('owner') in self.members:
                self.members[f['owner']]['ready'] = False
            self.bump()
        return []

    def set_sizes(self, sizes, catalog, rng=None):
        """Host: the two columns' sizes (teams: 1..5 each; ffa: 1..5 per column, 2..10 in all). New fighters are
        random; shrinking drops the last ones (their owners become spectators). With three to five teams: one
        size per team (a CPU fighter goes before a player's), then the teams are laid out again."""
        if self.team_count() >= kit_spec.TEAMS_MIN:
            return self.set_team_sizes(list(sizes), catalog, rng)
        found = kit_spec.layout_problems(self.match['mode'], list(sizes))
        if found:
            self.bump(dict(code='TTM-NET-29', key='notice.invalid_rule', args=dict(what='; '.join(found))))
            return found
        changed = False
        for t, n in enumerate(sizes):
            team = self.match['teams'][t]
            while len(team) > n:
                team.pop()
                changed = True
            while len(team) < n:
                c, k = kit_spec.random_fighter(catalog, rng)
                team.append(dict(character=c, costume=k, owner=None))
                changed = True
        if changed:
            self.clear_ready()
            self.bump(dict(code=None, key='notice.rule_changed',
                           args=dict(rule='rule.sizes', value=' v '.join(str(n) for n in sizes))))
        return []

    def set_team_sizes(self, sizes, catalog, rng=None):
        count = self.team_count()
        found = [f'this room has {count} teams: give {count} sizes'] if len(sizes) != count else \
            kit_spec.team_sizes_problems(sizes)
        if found:
            self.bump(dict(code='TTM-NET-29', key='notice.invalid_rule', args=dict(what='; '.join(found))))
            return found
        logical = self.logical()
        changed = False
        for team, n in zip(logical, sizes):
            while len(team) > n:
                cpu = [i for i, f in enumerate(team) if f.get('owner') is None]
                team.pop(cpu[-1] if cpu else -1)
                changed = True
            while len(team) < n:
                c, k = kit_spec.random_fighter(catalog, rng)
                team.append(dict(character=c, costume=k, owner=None))
                changed = True
        if changed:
            self.place(logical)
            self.clear_ready()
            self.bump(dict(code=None, key='notice.rule_changed',
                           args=dict(rule='rule.sizes', value=' / '.join(str(n) for n in sizes))))
        return []

    def set_type(self, value):
        """Host: 'Start in' Menu (a versus match) or Hub (the in-level hub: free-for-all, infinite Duel Time)."""
        if value not in kit_spec.TYPES:
            return [f'match type {value!r} is not versus or hub']
        m = self.match
        if m.get('type', 'versus') == value:
            return []
        if value == 'hub' and self.team_count() >= kit_spec.TEAMS_MIN:
            self.set_team_count(2, self.catalog)      # the hub is free-for-all: the two columns again
        sizes = [len(t) for t in m['teams']]
        if value == 'hub':
            if kit_spec.layout_problems('ffa', sizes):
                return kit_spec.layout_problems('ffa', sizes)
            m['mode'] = 'ffa'
            m['native'] = dict(m['native'], time=0)
        else:
            m['mode'] = 'teams'
            if m['native'].get('time') == 0:
                m['native'] = dict(m['native'], time=kit_spec.DEFAULT_NATIVE['time'])
        m['type'] = value
        self.clear_ready()
        self.bump(dict(code=None, key='notice.rule_changed', args=dict(rule='rule.start_in', value=value)))
        return []

    def set_mode(self, mode, catalog=None):
        if mode not in kit_spec.MODES:
            return [f'mode {mode} is not teams or free-for-all']
        if mode == self.match['mode']:
            return []
        if self.match.get('type') == 'hub':
            return ['the hub is free-for-all']
        if mode == 'ffa' and self.team_count() >= kit_spec.TEAMS_MIN:
            self.set_team_count(2, catalog)           # free-for-all has no teams: the two columns again
        sizes = [len(t) for t in self.match['teams']]
        found = kit_spec.layout_problems(mode, sizes)
        if found:
            return found
        self.match['mode'] = mode
        self.clear_ready()
        self.bump(dict(code=None, key='notice.rule_changed', args=dict(rule='rule.mode', value=mode)))
        return []

    def set_rules(self, changes, catalog=None, allowed_services=()):
        """Host: {stage, bgm, native:{...}, gameplay:{key: value}, services:{name: bool}}. Clears every Ready and
        leaves a notice naming the change. Returns [problems] (empty: taken)."""
        problems, what = [], []
        m = self.match
        stage = changes.get('stage', m['stage'])
        if stage != 'random' and stage not in kit_spec.STAGE_IDS:
            problems.append(f'stage {stage} is not 0..{max(kit_spec.STAGE_IDS)}')
        bgm = changes.get('bgm', m['bgm'])
        if bgm != 'random' and not kit_spec.bgm_ok(bgm):
            problems.append(f'music {bgm} is not a track')
        native = dict(m['native'])
        native.update({k: v for k, v in (changes.get('native') or {}).items() if k in native})
        problems += kit_spec.native_problems(native)
        if m.get('type') == 'hub' and native.get('time') != 0:
            problems.append('the hub needs an infinite Duel Time')
        gameplay = kit_settings.gameplay_expand(m['gameplay'])
        changed_keys = []
        for key, value in (changes.get('gameplay') or {}).items():
            if key not in kit_settings.GAMEPLAY:
                problems.append(f'{key} is not an online rule')
                continue
            try:
                value = kit_settings.coerce(key, value)
            except (TypeError, ValueError) as error:
                problems.append(str(error))
                continue
            if not kit_settings._same(value, gameplay[key]):
                gameplay[key] = value
                changed_keys.append((key, value))
        if changed_keys:
            problems += kit_settings.gameplay_problems(kit_settings.gameplay_diff(gameplay))
        services = dict(m['services'])
        for name, on in (changes.get('services') or {}).items():
            if name not in kit_spec.SERVICES:
                problems.append(f'{name} is not a host service')
            elif on and name not in allowed_services:
                problems.append(f'{name} is not available online yet')
            else:
                services[name] = bool(on)
        if problems:
            self.bump(dict(code='TTM-NET-29', key='notice.invalid_rule', args=dict(what='; '.join(problems[:4]))))
            return problems
        if stage != m['stage']:
            what.append(('rule.stage', 'random' if stage == 'random' else
                         (catalog.stage_name(stage) if catalog else str(stage))))
            m['stage'] = stage
        if bgm != m['bgm']:
            what.append(('rule.bgm', bgm))
            m['bgm'] = bgm
        for key in ('time', 'com', 'referee', 'destructible'):
            if native[key] != m['native'][key]:
                what.append((f'rule.{key}', native[key]))
        m['native'] = native
        what += [(f'mod.{k}', v) for k, v in changed_keys]
        m['gameplay'] = kit_settings.gameplay_diff(gameplay)
        for name in kit_spec.SERVICES:
            if services.get(name) != m['services'].get(name):
                what.append((f'service.{name}', services[name]))
        m['services'] = services
        if what:
            self.clear_ready()
            key, value = what[0]
            self.bump(dict(code=None, key='notice.mod_changed' if key.startswith('mod.') else 'notice.rule_changed',
                           args=dict(rule=key, value=value)))
        return []

    def rules(self):
        """The rules part of the match (what the host's profile keeps for the next online match)."""
        m = self.match
        return dict(native=dict(m['native']), gameplay=dict(m['gameplay']), services=dict(m['services']),
                    bgm=m['bgm'] if m['bgm'] != 'random' else kit_spec.DEFAULT_BGM, mode=m['mode'],
                    type=m.get('type', 'versus'))

    def apply_rules(self, rules):
        """The host's saved online rules as this lobby's starting rules (never fighters or the stage)."""
        m = self.match
        native = dict(kit_spec.DEFAULT_NATIVE)
        native.update({k: v for k, v in (rules.get('native') or {}).items() if k in native})
        if not kit_spec.native_problems(native):
            m['native'] = native
        m['gameplay'] = kit_settings.gameplay_diff(kit_settings.normalised_gameplay(rules.get('gameplay') or {}))
        m['services'] = {k: False for k in kit_spec.SERVICES}
        if kit_spec.bgm_ok(rules.get('bgm')):
            m['bgm'] = rules['bgm']
        if rules.get('mode') in kit_spec.MODES:
            m['mode'] = rules['mode']
        if rules.get('type') == 'hub' and not kit_spec.layout_problems('ffa', [len(t) for t in m['teams']]):
            m['type'], m['mode'], m['native'] = 'hub', 'ffa', dict(m['native'], time=0)

    def spec(self, tables_sha256, kit=kit_spec.KIT, mod_build=None, rng=None):
        """The match spec (None while the stage or the music is still Random: the host resolves them at Start)."""
        m = self.match
        if m['stage'] == 'random' or m['bgm'] == 'random':
            return None
        teams = []
        count = m.get('team_count')
        for t, team in enumerate(m['teams']):
            teams.append([dict(character=f['character'], costume=f['costume'], potaras=f.get('potaras', []),
                               slot=kit_spec.slot_of(t, i) if f.get('owner') in self.members else None,
                               **({'team': f.get('team')} if count else {}))
                          for i, f in enumerate(team)])
        return kit_spec.make(tables_sha256=tables_sha256, type=m.get('type', 'versus'), mode=m['mode'], teams=teams,
                             stage=m['stage'], bgm=m['bgm'],
                             native=m['native'], gameplay=m['gameplay'], services=m['services'], kit=kit,
                             mod_build=mod_build, team_count=count)

    def resolve_random(self, catalog, rng=None):
        """Host at Start: a Random stage / music becomes a concrete one (the lobby shows it)."""
        if self.match['stage'] == 'random':
            self.match['stage'] = kit_spec.random_stage(catalog, rng)
        if self.match['bgm'] == 'random':
            self.match['bgm'] = kit_spec.random_bgm(rng)

    def seats(self):
        """{member id: input slot} of the players (slot = 2 x index + team: the fighter's physical index)."""
        return {owner: slot for slot, _, _, owner in self.humans()}


def snapshot_problem(snap):
    """None when a LOBBY snapshot has the shape a guest relies on, else what is wrong."""
    if not isinstance(snap, dict):
        return 'not an object'
    if not isinstance(snap.get('rev'), int) or isinstance(snap.get('rev'), bool):
        return 'rev'
    if snap.get('phase', 'lobby') not in PHASES:
        return 'phase'
    members = snap.get('members')
    if not isinstance(members, list) or not members or len(members) > MAX_MEMBERS:
        return 'members'
    ids = set()
    for m in members:
        if not isinstance(m, dict) or not isinstance(m.get('id'), int) or not isinstance(m.get('name'), str) or \
                m['id'] in ids:
            return 'member'
        ids.add(m['id'])
    match = snap.get('match')
    if not isinstance(match, dict) or match.get('mode') not in kit_spec.MODES or \
            match.get('type', 'versus') not in kit_spec.TYPES:
        return 'match'
    if snap.get('hub') is not None and not isinstance(snap.get('hub'), dict):
        return 'hub'
    teams = match.get('teams')
    if not isinstance(teams, list) or len(teams) != 2:
        return 'teams'
    for team in teams:
        if not isinstance(team, list) or len(team) > kit_spec.TEAM_MAX:
            return 'team'
        for f in team:
            if not isinstance(f, dict) or not all(isinstance(f.get(k), int) and not isinstance(f.get(k), bool)
                                                  for k in ('character', 'costume')):
                return 'fighter'
            if f.get('owner') is not None and f['owner'] not in ids:
                return 'owner'
            if f.get('locked') not in (None, True):
                return 'locked'
            import kit_potara
            if kit_potara.shape_problem(f.get('potaras', [])):
                return 'potaras'
    if kit_spec.layout_problems(match['mode'], [len(t) for t in teams]):
        return 'layout'
    if kit_spec.team_problems(match):
        return 'team layout'
    if not (match.get('stage') == 'random' or match.get('stage') in kit_spec.STAGE_IDS):
        return 'stage'
    if not (match.get('bgm') == 'random' or kit_spec.bgm_ok(match.get('bgm'))):
        return 'bgm'
    if not isinstance(match.get('native'), dict) or kit_spec.native_problems(match['native']):
        return 'native'
    if not isinstance(match.get('gameplay'), dict) or kit_settings.gameplay_problems(match['gameplay']):
        return 'gameplay'
    if not isinstance(match.get('services'), dict):
        return 'services'
    for key, kind in (('room', dict), ('locked', dict), ('warm', dict), ('notice', dict), ('vote', dict)):
        if snap.get(key) is not None and not isinstance(snap.get(key), kind):
            return key
    hint = snap.get('delay_hint')
    if hint is not None and (not isinstance(hint, int) or not 1 <= hint <= 30):
        return 'delay_hint'
    return None


def chat_text(text):
    text = ''.join(ch for ch in str(text) if ch == ' ' or ch.isprintable())
    return text.strip()[:CHAT_MAX]
