"""After a fight (kit 2.0): the result, and the only two things the players can do next, Retry and Return to lobby.

Every game waits in its native result menu with neutral pads (netplay_core OPT_NEUTRAL_END): no native entry (Fight
Again, Character Select, replays, the main menu) can ever be chosen. The kit shows its own choice instead:
  * RETRY needs EVERY player of that fight (the members who played a fighter; the host decides alone when nobody
    played) to agree within VOTE_SECONDS; then every PC PINE-loads its own copy of the same match file (save slot
    241) and attaches late: the same fight again from its intro.
  * RETURN TO LOBBY by any player, or the time running out, sends everybody back to the lobby at once.
Spectators see the countdown and who agreed, and never vote.
The host decides (VOTE_STATE is its word): guests send VOTE {epoch, choice}; the host answers every change with
VOTE_STATE {epoch, left_s, agreed:[ids], players:[ids], decision: None | 'retry' | 'lobby'}.

RESULT (host -> every member): {epoch, winner:0|1|2, how:'ko'|'time'|'nocontest', words:[result, reason], frame,
seconds, compared, differing, resyncs, title}.
"""
import struct

RESULT_WORD, REASON_WORD = 0x333700, 0x333704            # USA (words() resolves them through A())
CHOICES = ('retry', 'lobby')
VOTE_SECONDS = 10.0
REMATCH_SLOT, RESYNC_SLOT = 241, 240
SENTINEL_OFFSET = 0xF0                                   # CONTROL+0xF0: the kit's token word (never hashed)
LOADING = 0xDEAD0001
WINNERS = (1, 2)


def words():
    """The native result and reason word addresses of the selected disc."""
    from native_map import A
    return A(RESULT_WORD), A(REASON_WORD)


def how_of(decided_result, reason):
    """'ko', 'time' or 'nocontest' (no winner)."""
    winner = (decided_result or 0) & 0x1F
    if winner not in WINNERS:
        return 'nocontest'
    return 'time' if reason == 2 else 'ko'


class Vote:
    """The Retry vote of one fight (epoch), decided on the host."""

    def __init__(self, epoch, players, started, seconds=VOTE_SECONDS, host=1):
        self.epoch = epoch
        self.players = sorted(players) if players else [host]
        self.started, self.seconds = started, seconds
        self.agreed = set()
        self.decision = None

    def cast(self, member, choice, now):
        """True when it changed something. A spectator's vote counts for nothing."""
        if self.decision is not None or member not in self.players or choice not in CHOICES:
            return False
        if choice == 'lobby':
            self.decision = 'lobby'
            return True
        if member in self.agreed:
            return False
        self.agreed.add(member)
        if self.agreed >= set(self.players):
            self.decision = 'retry'
        return True

    def tick(self, now):
        """'lobby' once the time ran out without every player agreeing (True when it just decided)."""
        if self.decision is None and now - self.started >= self.seconds:
            self.decision = 'lobby'
            return True
        return False

    def left(self, now):
        return max(0.0, self.seconds - (now - self.started))

    def drop(self, member):
        """A player left during the vote: it cannot agree any more, so the same fight cannot be played again -
        everybody returns to the lobby (True when it just decided)."""
        if member in self.players and self.decision is None:
            self.agreed.discard(member)
            self.decision = 'lobby'
            return True
        return False

    def state(self, now):
        return dict(epoch=self.epoch, left_s=round(self.left(now), 1), agreed=sorted(self.agreed),
                    players=list(self.players), decision=self.decision)


def result_message(epoch, *, winner, how, words_, frame, seconds, compared, differing, resyncs, title=None):
    return dict(type='RESULT', epoch=epoch, winner=winner, how=how, words=list(words_), frame=frame,
                seconds=seconds, compared=compared, differing=differing, resyncs=resyncs, title=title)


def read_words(link):
    r, q = words()
    data = link.read_ranges([(r, 4), (q, 4)])
    return struct.unpack('<I', data[0])[0], struct.unpack('<I', data[1])[0]
