"""The in-level hub (match type 'hub', kit 2.0): the lobby half of tools/hub_mode.py.

A hub is an ordinary kit 2.0 match prepared as free-for-all with infinite Duel Time and hub_mode installed (consent
damage, respawn, scoreboard; kit_prepare (h)). While it runs, the room shows the scoreboard and offers:
  * Fight freely (on / off): the player's bit in hub CONTROL.open (two opted-in fighters are hostile at once);
  * Challenge a player: a DUEL fought in the level (hub CONTROL.duel; everybody watches; the first K.O. between the
    two ends it and counts a duel win), or a FULL MATCH: the host keeps the scoreboard, runs a normal 2.0 match with
    the two challengers playing (everybody else watches), then the character-selection room stays open; returning to the hub restores scores
    (the winner gets a duel win);
  * a player who leaves is PARKED (hub CONTROL.parked: takes and deals no damage, shown AWAY).
Every hub word is written by the host as a frame-scheduled write (netplay_core SCHED, kit_lockstep.Hub.schedule):
the same frame on every PC. Kit 2.1: up to ten players (any fighter), and a member who watches a running hub can JOIN
it as a player: the host gives it a free fighter (a parked one whose player left first, else a CPU bot) at a frame K
about 1.5 s ahead - one scheduled entry seats that slot, adds it to every game's slot mask, makes the fighter human
(CPU flag 0, input words cleared) and unparks it; from K every PC waits for the newcomer's inputs (netplay_core
applies the entry before it takes K's inputs) and the newcomer's kit feeds its own captures from K on
(kit_lockstep become_player); HUB_SEAT tells every PC.
"""
import copy
import struct
import time

import kit_lobby

CHALLENGE_SECONDS = 30.0
DUEL_SECONDS = 120.0                       # a duel without a K.O. between the two ends as a draw
TELEMETRY_EVERY = 1.0
RETURN_AFTER = 6.0                         # seconds the full match's result shows before everybody returns to the hub
JOIN_LEAD = 45                             # updates (1.5 s) between a join and its frame: the newcomer's kit gets ready


def now():
    return time.monotonic()


def hub_names():
    import hub_mode
    return hub_mode


class HubMixin:
    def init_hub(self):
        self.hub_state = None              # host: the running hub {open, duel, challenges, rows, last}
        self.hub_return = None             # host: the hub to return to after a full-match challenge
        self.hub_next = None               # host: what follows the hub fight that is ending
        self.hub_restore = None            # host: scores to write into the next hub fight
        self.hub_return_at = None
        self.hub_scored_epochs = set()

    # ---- what runs ---------------------------------------------------------------------------------------------------
    def hub_running(self):
        m = self.match or {}
        return (m.get('spec') or {}).get('type') == 'hub' and self.phase == 'fight' and self.session is not None

    def hub_index(self, ident):
        """The hub fighter index (physical) a member plays: the leader of column `slot` is index `slot`."""
        slot = ((self.match or {}).get('seats') or {}).get(ident)
        return slot

    def hub_fighter_names(self):
        spec = (self.match or {}).get('spec') or {}
        view = (self.local or {}).get('view')
        names = {}
        seats = (self.match or {}).get('seats') or {}
        for t, team in enumerate(spec.get('teams') or []):
            for j, f in enumerate(team):
                names[2 * j + t] = view.name(f['character']) if view else str(f['character'])
        for ident, slot in seats.items():
            if self.lobby and ident in self.lobby.members:
                names[slot] = self.lobby.members[ident]['name']
        return names

    # ---- host: the running hub -----------------------------------------------------------------------------------------
    def hub_begin(self):
        """Host, at the start of a hub fight: a fresh record; scores of the hub before a full-match challenge return."""
        self.hub_state = dict(open=0, duel=0, parked=0, challenges={}, rows=[], last=0.0, view=None)
        restore = self.hub_restore
        self.hub_restore = None
        if restore and self.session is not None:
            h = hub_names()
            writes = []
            for i, row in restore.items():
                for key in ('kills', 'deaths', 'duel_wins'):
                    writes.append((h.ROWS + i * h.STRIDE + h.R[key], int(row.get(key, 0)), 0xFFFFFFFF))
            if writes:
                self.session.schedule(writes)
                self.say(f'Hub: the scoreboard of before the challenge is back ({len(restore)} fighters).')
        for ident, slot in ((self.match or {}).get('seats') or {}).items():
            if ident != self.me and ident not in self.members:
                self.hub_park(slot, True)

    def hub_write(self, field, value, mask=0xFFFFFFFF):
        h = hub_names()
        seq_k = self.session.schedule([(h.CONTROL + h.C[field], value, mask)])
        self.say(f'Hub: {field} := {value:#x} (mask {mask:#x}) at frame {seq_k[1]}')

    def hub_park(self, index, on):
        if index is None:
            return
        st = self.hub_state
        bit = 1 << index
        st['parked'] = (st['parked'] | bit) if on else (st['parked'] & ~bit)
        self.hub_write('parked', bit if on else 0, bit)

    def tick_hub(self):
        if self.role != 'host' or not self.hub_running() or self.hub_state is None:
            return
        st = self.hub_state
        t = now()
        for ident, ch in list(st['challenges'].items()):
            if t - ch['t'] > CHALLENGE_SECONDS:
                del st['challenges'][ident]
                st['view'] = None
        if t - st['last'] < TELEMETRY_EVERY:
            return
        st['last'] = t
        h = hub_names()
        try:
            tele = h.telemetry(lambda a, n: self.link.read_ranges([(a, n)])[0])
        except (OSError, RuntimeError, struct.error, ValueError) as error:
            if not st.get('read_error'):
                st['read_error'] = True
                self.say(f'Hub: the scoreboard could not be read ({type(error).__name__}: {error}).')
            return
        if tele.get('magic') != h.MAGIC:
            if not st.get('magic_error'):
                st['magic_error'] = True
                self.say(f'Hub: no hub record in this game (magic {tele.get("magic", 0):#x}).')
            return
        names = self.hub_fighter_names()
        seats = {slot: ident for ident, slot in ((self.match or {}).get('seats') or {}).items()}
        rows = []
        for i, r in enumerate(tele['rows']):
            rows.append(dict(i=i, name=names.get(i, f'#{i}'), member=seats.get(i), kills=r['kills'], deaths=r['deaths'],
                             wins=r['duel_wins'], down=bool(r['state']), engaged=bool(r['engaged'])))
        st['rows'] = rows
        duel = tele.get('duel') or 0
        if duel and st.get('duel_since') is None:
            st['duel_since'] = t
        if not duel:
            st['duel_since'] = None
        if duel and t - (st.get('duel_since') or t) > DUEL_SECONDS and not st.get('duel_cleared'):
            st['duel_cleared'] = True                       # once: the scheduled clear lands a few frames later
            self.hub_write('duel', 0)
            self.lobby.bump(dict(code=None, key='notice.hub_draw', args={}))
        if not duel:
            st['duel_cleared'] = False
        st['duel'] = duel
        view = dict(rows=rows, duel=[(duel & 0xFF) - 1, (duel >> 8 & 0xFF) - 1] if duel else None,
                    open=tele.get('open', 0), parked=tele.get('parked', 0),
                    challenges=[dict(by=k, target=v['target'], kind=v['kind']) for k, v in st['challenges'].items()],
                    feed=[line for line in (tele.get('lines') or [])[13:16] if line])
        if len(view['challenges']) != st.get('challenges_shown', 0):
            st['challenges_shown'] = len(view['challenges'])
            self.say(f'Hub: {len(view["challenges"])} open challenge(s) in the room.')
        if view != st.get('view'):
            if st.get('view') is None and not st.get('shown'):
                st['shown'] = True
                self.say(f'Hub: scoreboard of {len(rows)} fighters in the room.')
            st['view'] = view
            self.lobby.hub = view
            self.lobby.bump(self.lobby.notice)
            self.broadcast()

    # ---- player commands ---------------------------------------------------------------------------------------------
    def cmd_hub_open(self, c):
        self.request('HUB_OPEN', on=bool(c.get('on')))

    def msg_HUB_OPEN(self, ident, m):
        if self.role != 'host' or not self.hub_running() or self.hub_state is None:
            return
        index = self.hub_index(ident)
        if index is None:
            return
        bit = 1 << index
        on = bool(m.get('on'))
        st = self.hub_state
        if bool(st['open'] & bit) == on:
            return
        st['open'] = (st['open'] | bit) if on else (st['open'] & ~bit)
        self.hub_write('open', bit if on else 0, bit)
        st['view'] = None

    def cmd_hub_challenge(self, c):
        self.request('HUB_CHALLENGE', target=c.get('target'), how=c.get('kind'))

    def msg_HUB_CHALLENGE(self, ident, m):
        if self.role != 'host' or not self.hub_running() or self.hub_state is None:
            return
        try:
            target = int(m.get('target'))
        except (TypeError, ValueError):
            return
        kind = m.get('how')
        seats = (self.match or {}).get('seats') or {}
        if kind not in ('duel', 'match') or target == ident or ident not in seats or target not in seats:
            self.say(f'Hub: challenge {ident} -> {target} ({kind}) refused (seats {seats}).')
            return
        if self.hub_state['duel']:
            self.say(f'Hub: challenge {ident} -> {target} refused: a duel runs ({self.hub_state["duel"]:#x}).')
            self.lobby.bump(dict(code=None, key='notice.hub_busy', args={}))
            self.broadcast()
            return
        self.hub_state['challenges'][ident] = dict(target=target, kind=kind, t=now())
        self.hub_state['view'] = None
        self.say(f'Hub: {ident} challenges {target} ({kind}).')
        names = self.lobby.members
        self.lobby.bump(dict(code=None, key='notice.hub_challenge',
                             args=dict(name=names.get(ident, {}).get('name', ''),
                                       target=names.get(target, {}).get('name', ''), kind=kind)))
        self.broadcast()

    def cmd_hub_answer(self, c):
        self.request('HUB_ANSWER', challenger=c.get('challenger'), accept=bool(c.get('accept')))

    def msg_HUB_ANSWER(self, ident, m):
        if self.role != 'host' or not self.hub_running() or self.hub_state is None:
            return
        try:
            by = int(m.get('challenger'))
        except (TypeError, ValueError):
            return
        ch = self.hub_state['challenges'].get(by)
        if not ch or ch['target'] != ident:
            self.say(f'Hub: answer of {ident} to {by} ignored (no such challenge).')
            return
        self.say(f'Hub: {ident} {"accepts" if m.get("accept") else "declines"} the challenge of {by}.')
        del self.hub_state['challenges'][by]
        self.hub_state['view'] = None
        names = self.lobby.members
        a, b = names.get(by, {}).get('name', ''), names.get(ident, {}).get('name', '')
        if not m.get('accept'):
            self.lobby.bump(dict(code=None, key='notice.hub_declined', args=dict(name=b, target=a)))
            self.broadcast()
            return
        ia, ib = self.hub_index(by), self.hub_index(ident)
        if ch['kind'] == 'duel':
            self.hub_write('duel', (ia + 1) | (ib + 1) << 8)
            self.hub_state['duel'] = (ia + 1) | (ib + 1) << 8
            self.hub_state['duel_since'] = now()
            self.lobby.bump(dict(code=None, key='notice.hub_duel', args=dict(name=a, target=b)))
            self.broadcast()
            return
        self.hub_full_match(by, ident)

    # ---- full-match challenge -------------------------------------------------------------------------------------------
    def hub_full_match(self, a, b):
        """Host: keep the hub (its lobby match and scoreboard), end the hub fight, play a's and b's 1 v 1 with everybody
        else watching, then return (hub_after_match)."""
        rows = {r['i']: dict(kills=r['kills'], deaths=r['deaths'], duel_wins=r['wins'])
                for r in (self.hub_state or {}).get('rows') or []}
        self.hub_return = dict(match=copy.deepcopy(self.lobby.match), scores=rows, a=a, b=b,
                               ia=self.hub_index(a), ib=self.hub_index(b))
        names = self.lobby.members
        self.lobby.bump(dict(code=None, key='notice.hub_match', args=dict(name=names.get(a, {}).get('name', ''),
                                                                         target=names.get(b, {}).get('name', ''))))
        self.broadcast()
        self.hub_next = 'challenge'
        self.say(f'Hub: full-match challenge {a} vs {b}; opening character selection.')
        self.end_fight('challenge', mine=True)

    def hub_after_fight(self):
        """Host, in finish_fight: True when the hub decides what follows (no Retry vote)."""
        spec = (self.match or {}).get('spec') or {}
        if self.hub_next == 'challenge' and spec.get('type') == 'hub':
            self.hub_next = None
            self.hub_start_challenge()
            return True
        if self.hub_return is not None and spec.get('type') == 'versus':
            self.score_hub_challenge()
        return False

    def hub_start_challenge(self):
        ret = self.hub_return
        hub = ret['match']
        spec = (self.match or {}).get('spec') or {}

        def fighter(index):
            t, j = index % 2, index // 2
            f = spec['teams'][t][j]
            return dict(character=f['character'], costume=f['costume'], potaras=list(f.get('potaras', [])))
        self.send(type='TO_LOBBY', why='challenge')
        self.back_to_lobby()
        m = self.lobby.match
        m['type'], m['mode'] = 'versus', 'teams'
        m['teams'] = [[dict(fighter(ret['ia']), owner=ret['a'])], [dict(fighter(ret['ib']), owner=ret['b'])]]
        m['native'] = dict(hub['native'], time=kit_lobby.kit_spec.DEFAULT_NATIVE['time'])
        for ident in (ret['a'], ret['b']):
            if ident in self.lobby.members:
                self.lobby.members[ident]['ready'] = False
        self.lobby.return_to_hub = True
        self.lobby.bump()
        self.broadcast()

    def score_hub_challenge(self):
        if self.epoch in self.hub_scored_epochs:
            return
        self.hub_scored_epochs.add(self.epoch)
        ret, res = self.hub_return, self.results or {}
        winner = res.get('winner') or 0
        if res.get('how') in ('ko', 'time') and winner in (1, 2):
            # The selection room can change teams after a challenge. Credit its actual winners.
            seats = (self.match or {}).get('seats') or {}
            previous = {fighter.get('owner'): 2*j+t
                        for t, team in enumerate(ret['match']['teams'])
                        for j, fighter in enumerate(team) if fighter.get('owner') is not None}
            for member, slot in seats.items():
                if slot % 2 != winner - 1 or member not in previous:
                    continue
                row = ret['scores'].setdefault(previous[member], dict(kills=0, deaths=0, duel_wins=0))
                row['duel_wins'] = row.get('duel_wins', 0) + 1

    def tick_hub_return(self):
        # Return to lobby deliberately stays in character selection. Hub is a separate action.
        pass

    def cmd_back_to_hub(self, c):
        if self.role != 'host' or self.phase != 'lobby' or not self.hub_return:
            return
        ret, self.hub_return = self.hub_return, None
        self.hub_restore = dict(ret['scores'])
        self.lobby.match = copy.deepcopy(ret['match'])
        for team in self.lobby.match['teams']:
            for fighter in team:
                if fighter.get('owner') not in self.lobby.members:
                    fighter['owner'] = None
        self.lobby.return_to_hub = False
        for ident in self.lobby.players():
            self.lobby.members[ident]['ready'] = True
        self.lobby.bump(dict(code=None, key='notice.hub_back', args={}))
        self.broadcast()
        self.cmd_start({})

    # ---- kit 2.1: joining a running hub as a player ---------------------------------------------------------------------
    def cmd_hub_join(self, c):
        self.request('HUB_JOIN')

    def hub_free_fighter(self):
        """The fighter a newcomer gets: a parked one (its player left) first, else the lowest CPU bot; None when every
        fighter has a player."""
        spec = (self.match or {}).get('spec') or {}
        count = sum(len(t) for t in spec.get('teams') or [])
        present = {s for ident, s in ((self.match or {}).get('seats') or {}).items()
                   if ident == self.me or ident in self.members}
        free = [i for i in range(10) if i // 2 < len((spec.get('teams') or [[], []])[i & 1]) and i not in present]
        parked = (self.hub_state or {}).get('parked', 0)
        free.sort(key=lambda i: (0 if parked >> i & 1 else 1, i))
        return free[0] if free and count else None

    def msg_HUB_JOIN(self, ident, m):
        if self.role != 'host' or not self.hub_running() or self.hub_state is None:
            return
        seats = self.match.setdefault('seats', {})
        if ident in seats and (ident == self.me or ident in self.members) and \
                seats[ident] not in [s for k, s in seats.items() if k != ident]:
            if self.hub_index(ident) is not None and (ident == self.me or self.session.members.get(ident) is not None
                                                      and self.session.members[ident].slot is not None):
                return                                          # already plays
        if ident != self.me and (ident not in self.session.members or self.session.members[ident].slot is not None):
            self.say(f'Hub: {ident} cannot join yet (not in the running hub).')
            return
        f = self.hub_free_fighter()
        if f is None:
            self.lobby.bump(dict(code=None, key='notice.hub_full', args={}))
            self.broadcast()
            return
        import struct
        import netplay_core as nc
        import kit_verify
        h = hub_names()
        actor = struct.unpack('<I', self.link.read(kit_verify.POINTERS + 4 * f, 4))[0]
        writes = [(nc.SEAT_CONTROL + nc.SF['seats'] + 4 * f, f, 0xFFFFFFFF), (nc.CONTROL + nc.F['mask'], 1 << f, 1 << f),
                  (h.CONTROL + h.C['parked'], 0, 1 << f)]
        if 0x100000 <= actor < 0x8000000 - 0x1300:
            writes += [(actor + 0x1278, 0, 0xFFFFFFFF), (actor + 0x127C, 0, 0xFFFFFFFF),
                       (actor + 0x1280, 0, 0xFFFFFFFF), (actor + 0x1284, 0, 0xFFFFFFFF), (actor + 0x1300, 1, 0xFFFFFFFF)]
        try:
            seq, K = self.session.schedule(writes, lead=JOIN_LEAD)
            if ident == self.me:
                self.session.become_player(f, K)
            else:
                self.session.seat_member(ident, f, K)
        except (RuntimeError, ValueError) as error:
            self.say(f'Hub: {ident} could not join: {error}')
            return
        self.hub_state['parked'] &= ~(1 << f)
        seats[ident] = f
        t, j = f & 1, f >> 1
        for team in self.lobby.match['teams']:
            for fighter in team:
                if fighter.get('owner') == ident:
                    fighter['owner'] = None
        if j < len(self.lobby.match['teams'][t]):
            self.lobby.match['teams'][t][j]['owner'] = ident
        self.send(type='HUB_SEAT', member=ident, slot=f, K=K)
        name = self.lobby.members.get(ident, {}).get('name', '')
        self.say(f'Hub: {name} ({ident}) joins as fighter {f} from frame {K} (entry {seq}).')
        self.summary.setdefault('hub_joins', []).append(dict(member=ident, slot=f, frame=K))
        self.hub_state['view'] = None
        self.lobby.bump(dict(code=None, key='notice.hub_joined', args=dict(name=name)))
        self.broadcast()

    def msg_HUB_SEAT(self, ident, m):
        """Every guest: a member plays slot `slot` from frame K (this PC itself: it feeds that slot from K on)."""
        if self.role != 'guest' or self.session is None:
            return
        try:
            member, slot, K = int(m['member']), int(m['slot']), int(m['K'])
        except (KeyError, TypeError, ValueError):
            return
        if not 0 <= slot < 10:
            return
        if self.match is not None:
            self.match.setdefault('seats', {})[member] = slot
        if member == self.me:
            self.session.become_player(slot, K)
            try:
                import netplay_view as nv
                self.link.write_ranges([(nv.CONTROL + nv.F['watch'], (nv.NO_WATCH).to_bytes(4, 'little'))])
            except (OSError, RuntimeError):
                pass
            self.say(f'You play fighter {slot} from frame {K}.')
        else:
            self.session.add_slot(slot, K)

    def hub_member_left(self, ident):
        if self.role == 'host' and self.hub_running() and self.hub_state is not None:
            index = self.hub_index(ident)
            if index is not None:
                self.hub_park(index, True)
            for k in [k for k, v in self.hub_state['challenges'].items() if k == ident or v['target'] == ident]:
                del self.hub_state['challenges'][k]
