"""Team Setup: fighters per team for Team Battle with three to five teams, before the native character selector.

Modded Modes > Team Battle > How many teams? stores the count in the pager control (native_mode_menu.TEAMS). With
three to five teams every players row opens this panel on the pager's existing host-panel route (the same state,
lease and button words as Player Setup). Player 1 sets how many fighters each team has; the teams are then laid
out on the two rows of the native selection by battle_mode_policy.squad_layout. With two or more players Player
Setup follows (each player picks a team); otherwise the receipt is published at once.

The receipt (pager control: SQUAD_VALID = the committed choice, SQUAD_ROWS = fighters per row, SQUAD_TEAM_OF = the
team of each of the ten slots) is read by the selector code (squad_select: team chips, exact row counts) and by
the watcher (selected()). Nothing here changes a two-team match: the panel never opens for it.
"""
import struct
import time

import battle_mode_policy as policy
import fonts
import team_assignment as players
from localization import tr
from native_map import JPN
from regional import RAW_ACCEPT, RAW_BACK

MENU, MAGIC = players.MENU, players.MAGIC
TEAMS, VALID, ROWS, TEAM_OF = 0x15C, 0x160, 0x164, 0x168          # native_mode_menu.TEAMS / SQUAD_VALID / _ROWS / _TEAM_OF
CHOICES = {1: 1, 7: 2, 8: 0, 12: 4, 17: 3}                         # Team Battle's rows -> players (native_mode_menu.SQUAD_CHOICES)
DEFAULT_SIZE = 2
REDRAW = 0.2

# Panel texts (Spanish in localization.ES).
TITLE = 'TEAM SETUP'
INTRO = 'How many fighters on each team? Up to 10 in total.'
FIGHTERS, FIGHTER = '<  {n} FIGHTERS  >', '<  1 FIGHTER  >'
TEAM = 'TEAM {team}'
CONTINUE = 'Continue'
FULL = '10 fighters at most: lower another team first.'
ROWS_NOTE = 'Pick {left} fighters on the first row and {right} on the second.'
SPLIT_NOTE = 'Team {team} gets the last slot of both rows.'
FOOTER_USA = 'Player 1: Up/Down select · Left/Right fighters · Cross continue · Triangle back'
FOOTER_JPN = 'Player 1: Up/Down select · Left/Right fighters · Circle continue · Cross back'
FOOTER = FOOTER_JPN if JPN else FOOTER_USA
BG, PANEL, EDGE, GOLD, WHITE, DIM, TEXT, BAR, WARN = ((10, 16, 28), (31, 46, 66), (64, 80, 102), (249, 197, 90),
                                                      (242, 244, 249), (150, 162, 182), (203, 216, 234), (245, 184, 63),
                                                      (240, 104, 92))
_PALETTE = None


def palette():
    """The panel's fixed colours: every drawn colour exactly, the five team colours and three title edge tones."""
    global _PALETTE
    if _PALETTE is None:
        from PIL import Image
        colors = [BG, PANEL, EDGE, GOLD, WHITE, DIM, TEXT, BAR, WARN]+list(policy.TEAM_RGB)
        colors += [tuple(round(b+(f-b)*s) for f, b in zip(GOLD, BG)) for s in (1/4, 1/2, 3/4)]
        image = Image.new('P', (1, 1)); flat = [c for rgb in colors for c in rgb]
        image.putpalette(flat+flat[:3]*(256-len(colors))); _PALETTE = image
    return _PALETTE


def default_sizes(count):
    return [DEFAULT_SIZE]*count


def publish(p, choice, squads):
    """Write the receipt of a finished setup; the valid word (the committed choice) goes last."""
    if choice not in CHOICES or not isinstance(squads, policy.Squads) or not 3 <= squads.teams <= policy.MAX_TEAMS:
        raise ValueError('Team setup receipt for another kind of match')
    p.write_u32(MENU+VALID, 0)
    left, right = squads.counts()
    p.write(MENU+ROWS, struct.pack('<4B', left, right, squads.teams, 0))
    p.write(MENU+TEAM_OF, bytes(policy.ABSENT if t is None else t for t in squads.team_of))
    p.write_u32(MENU+VALID, choice)


def withdraw(p):
    if p.read_u32(MENU) == MAGIC and p.read_u32(MENU+VALID):
        p.write_u32(MENU+VALID, 0)


def selected(ram, choice, humans):
    """The committed team setup for this choice: dict(squads=..., seats=tuple or None), or None for two teams.

    ram is anything sliceable by address (a RAM image or native_mode_menu.ReadOnlyMemory)."""
    u = lambda p: struct.unpack('<I', bytes(ram[p:p+4]))[0]
    if choice not in CHOICES or CHOICES[choice] != humans or u(MENU) != MAGIC or u(MENU+VALID) != choice:
        return None
    left, right, teams, _ = struct.unpack('<4B', bytes(ram[MENU+ROWS:MENU+ROWS+4]))
    table = bytes(ram[MENU+TEAM_OF:MENU+TEAM_OF+policy.ENGINE_ACTORS])
    try:
        squads = policy.Squads(None if t == policy.ABSENT else t for t in table)
    except ValueError:
        raise ValueError('The team setup receipt is corrupt or stale') from None
    if squads.counts() != (left, right) or squads.teams != teams or not 3 <= teams <= policy.MAX_TEAMS:
        raise ValueError('The team setup receipt is corrupt or stale')
    seats = None
    if humans >= 2:
        if u(MENU+players.VALID) != 1 or u(MENU+players.HUMANS) != humans:
            raise ValueError('The team setup has no player seats')
        seats = tuple(u(MENU+players.SEATS+4*i) for i in range(humans))
        policy.human_seats('ffa', humans, squads.present(), seats, squads)
    return dict(squads=squads, seats=seats)


class Controller:
    """The watcher's side of the panel. tick() never blocks; it returns True while this panel owns the menu."""
    def __init__(self):
        self.active = False; self.screen = None; self.settings = {}; self.log = None
        self.count = 0; self.choice = None; self.sizes = []; self.row = 0; self.phase = None
        self.memory = {}                    # team count -> the sizes last confirmed in this session
        self.input_ready = False; self.notice = None; self.drawn = None; self.drawn_at = 0.0; self.dirty = False

    # ---- what the panel shows -------------------------------------------------------------------------------------
    def layout(self):
        return policy.squad_layout(self.sizes)

    def picture(self):
        from PIL import Image, ImageDraw
        im = Image.new('RGB', (512, 448), BG); d = ImageDraw.Draw(im)
        title = fonts.truetype('sans-bold', 25); font = fonts.truetype('sans-bold', 17); small = fonts.truetype('sans', 13)
        d.rectangle((0, 0, 511, 4), fill=BAR)
        d.text((24, 16), tr(TITLE), font=title, fill=GOLD)
        d.fontmode = '1'
        d.text((25, 50), tr(INTRO), font=small, fill=TEXT)
        squads = self.layout()
        for team, size in enumerate(self.sizes):
            y = 74+team*36; chosen = team == self.row; color = policy.TEAM_RGB[team]
            d.rounded_rectangle((20, y, 491, y+31), radius=6, fill=PANEL, outline=GOLD if chosen else EDGE, width=2)
            d.rectangle((30, y+7, 46, y+23), fill=color)
            d.text((56, y+5), tr(TEAM, team=team+1), font=font, fill=color)
            d.text((250, y+5), tr(FIGHTER) if size == 1 else tr(FIGHTERS, n=size), font=font, fill=WHITE)
        base = 74+len(self.sizes)*36+4
        d.rounded_rectangle((20, base, 491, base+28), radius=6, fill=PANEL,
                            outline=GOLD if self.row == len(self.sizes) else EDGE, width=2)
        d.text((33, base+4), tr(CONTINUE), font=font, fill=WHITE)
        # The two rows of the native selection, each slot in its team's colour.
        top = base+40
        left, right = squads.counts()
        d.text((25, top), tr(ROWS_NOTE, left=left, right=right), font=small, fill=TEXT)
        for row in (0, 1):
            for position in range(policy.TEAM_CAPACITY):
                team = squads.team_of[2*position+row]
                x, y = 60+position*46, top+22+row*26
                if team is None:
                    d.rectangle((x, y, x+38, y+20), outline=EDGE)
                else:
                    d.rectangle((x, y, x+38, y+20), fill=policy.TEAM_RGB[team])
                    d.text((x+15, y+2), str(team+1), font=small, fill=BG)
        split = squads.split()
        note = self.notice or (tr(SPLIT_NOTE, team=split+1) if split is not None else '')
        if note:
            d.text((300, top+30), '', font=small, fill=TEXT)
            words = note.split(); line = ''; y = top+22
            for word in words:
                trial = (line+' '+word).strip()
                if line and d.textlength(trial, font=small) > 190:
                    d.text((298, y), line, font=small, fill=WARN if self.notice else TEXT); y += 16; line = word
                else: line = trial
            d.text((298, y), line, font=small, fill=WARN if self.notice else TEXT)
        parts = [part.strip() for part in tr(FOOTER).split('·')]
        widths = [d.textlength(part, font=small) for part in parts]
        gap = max(8, (462-sum(widths))/max(1, len(parts)-1)); x = 25
        for part, width in zip(parts, widths):
            d.text((round(x), 420), part, font=small, fill=GOLD); x += width+gap
        return im.quantize(palette=palette(), dither=Image.Dither.NONE).convert('RGB')

    # ---- the watcher's tick ---------------------------------------------------------------------------------------
    def tick(self, p, team_menu):
        wanted = (p.read_u32(MENU) == MAGIC and p.read_u32(MENU+players.STATE) == 1 and
                  p.read_u32(MENU+players.CHOICE) in CHOICES and 3 <= p.read_u32(MENU+TEAMS) <= policy.MAX_TEAMS)
        if not wanted:
            if self.active: self.close(p)
            self.phase = None
            if not team_menu.active: team_menu.squads = None
            return False
        if self.phase == 'players':
            return False                      # Player Setup owns the panel until it commits or goes back
        count, choice = p.read_u32(MENU+TEAMS), p.read_u32(MENU+players.CHOICE)
        if not self.active:
            from guest_loading_screen import GuestLoadingScreen
            self.screen = GuestLoadingScreen(); self.active = True; self.count, self.choice = count, choice
            self.sizes = list(self.memory.get(count) or default_sizes(count)); self.row = 0
            self.input_ready = False; self.notice = None; self.drawn = None; self.dirty = True
            team_menu.squads = None
        p.write_u32(MENU+players.LEASE, players.HOST_LEASE); p.write_u32(MENU+16, players.HOST_LEASE)
        buttons = p.read_u32(MENU+players.BUTTONS)
        if buttons: p.write_u32(MENU+players.BUTTONS, 0)
        if buttons & RAW_BACK:
            p.write_u32(MENU+players.STATE, 0); p.write_u32(MENU+players.VALID, 0); withdraw(p)
            self.close(p); return True
        if not self.screen.presented(p): buttons = 0
        elif not self.input_ready:
            import mode_menu
            self.input_ready = p.read_u32(mode_menu.PAD+0x150) == 0
            buttons = 0
        rows = len(self.sizes)+1
        if buttons & 0x50:
            self.row = (self.row+(1 if buttons & 0x40 else -1)) % rows; self.notice = None; self.dirty = True
        if buttons & 0xA0 and self.row < len(self.sizes):
            step = 1 if buttons & 0x20 else -1
            size = self.sizes[self.row]+step
            if size < 1 or size > policy.TEAM_CAPACITY: pass
            elif sum(self.sizes)+step > policy.MAX_ACTORS: self.notice = tr(FULL)
            else:
                self.sizes[self.row] = size; self.notice = None
            self.dirty = True
        if buttons & RAW_ACCEPT:
            squads = self.layout(); self.memory[self.count] = list(self.sizes)
            if CHOICES[self.choice] >= 2:
                # Player Setup takes over on this same request, with these teams.
                team_menu.squads = squads; self.phase = 'players'
                self.close(p, keep=True)
                return False
            publish(p, self.choice, squads)
            self.close(p)
            p.write_u32(MENU+players.STATE, 2)
            return True
        now = time.monotonic()
        state = (tuple(self.sizes), self.row, self.notice)
        if state != self.drawn: self.dirty = True
        if self.dirty and now-self.drawn_at >= REDRAW:
            self.screen.show_picture(self.picture(), surface='menu', client=p)
            self.drawn, self.drawn_at, self.dirty = state, now, False
        else:
            self.screen.sync(client=p)
        return True

    def close(self, p, keep=False):
        """Hide the panel. keep: the request stays open for Player Setup (the pad word is left as it is)."""
        if not keep:
            import mode_menu
            p.write_u32(MENU+28, p.read_u32(mode_menu.PAD+0x150))
        if self.screen: self.screen.hide(client=p)
        self.screen = None; self.active = False

    def shutdown(self):
        self.active = False; self.phase = None
