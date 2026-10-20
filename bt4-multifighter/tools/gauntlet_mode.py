"""Fighter Gauntlet (Modded Modes): setup panel, the wave-1 enemy row on the Team Select, the run plan and the
match service that streams the next waves into the enemy slots.

Flow:
- Modded Modes root row "Fighter Gauntlet" (choice CHOICE) opens the setup panel (Player Setup style picture,
  team_assignment's guest input, the controller hub's check-ins): gauntlet (grouped by category, wave count shown),
  players 1..4 (START joins), team size, HP per completed wave.
- Continue publishes the same receipt Player Setup does with every human on Team 1 and dispatches Team Battle.
- On the Team Select the players pick Team 1 natively (character, form, costume, Custom/Potara). When Team 1 is
  Done the mod writes Team 2 (wave 1 and the preloaded fighters) and marks it Done: the native stage select opens.
- The run is armed (story mission + gauntlets/next-run.json); fresh_team_trainer installs story_runtime and then
  gauntlet_runtime for that match; Retry (Fight Again) replays the prepared start.
- In the match the watcher calls service() every loop: it assigns the upcoming fighters to free enemy slots and drives
  gauntlet_reload.GauntletWorker (no combat hold). Everything the guest needs is in guest RAM.
"""
import json
import struct
import time
from pathlib import Path

import gauntlet_data as data
import gauntlet_runtime as runtime
from localization import tr
import localization
from native_map import JPN

CHOICE = 23
ROOT = Path(__file__).resolve().parents[1]
NEXT = data.FOLDER / 'next-run.json'
LOGS = ROOT / 'analysis' / 'gauntlet'
TEAM_MAX = 5
PLAYER_COLUMN, ENEMY_COLUMN = 0, 1
ENEMY_PHYSICALS = (1, 3, 5, 7, 9)
RECYCLED = (3, 5, 7, 9)
RECORD_BUDGET = 7          # initial distinct extra bundles that leave room for 4 recycled slots + 1 in transit
BASE_HP = 4 * data.BAR_HP
SELECT_SCENE, MAIN_MENU = 40, 4

# Panel / banner texts (Spanish in localization.ES).
TITLE = 'FIGHTER GAUNTLET'
INTRO = 'Beat every wave in one match.'
GAUNTLET_ROW = 'Gauntlet'
PLAYERS_ROW = 'Players'
CPU_ONLY = 'CPU only'
CPU_NOTE = 'CPU only: the whole team is CPU and you watch. L1/R1 switch the fighter you follow.'
SIZE_ROW = 'Team size'
REFILL_ROW = 'HP back per wave'
CONTINUE_LABEL = 'Continue'
WAVES_VALUE = '{n} waves'
WAVE_VALUE = '1 wave'
PREVIEW = 'Waves: {list}'
SUMMARY = 'Team 1: {n} fighter(s), {h} player(s), {c} CPU teammate(s). Pick them next, then the arena.'
FOOTER_P1_USA = 'Up/Down select · Left/Right change · Cross continue · Triangle back'
FOOTER_P1_JPN = 'Up/Down select · Left/Right change · Circle continue · Cross back'
FOOTER_P1 = FOOTER_P1_JPN if JPN else FOOTER_P1_USA     # the disc's own menu buttons (regional.RAW_ACCEPT/BACK)
FOOTER_ALL = 'Everyone: START join · SELECT leave'
CPU_RANGE = 'CPU {low} → {high}'
CPU_ONE = 'CPU {level}'
FIRST_WAVES = 'FIRST WAVES'
FINAL_BOSS = 'FINAL BOSS'
REFILL_LABELS = tuple(label for _, label, _ in data.REFILL)
BANNER_PICK = 'Fighter Gauntlet: pick Team 1 ({n} fighters). The enemies are chosen by the gauntlet.'
# In-match texts drawn by the guest (gauntlet_runtime.tables)
GUEST_TEXTS = ('WAVE {n} / {count}', 'REACHED WAVE {n} / {count}', 'NEXT WAVE', 'GET READY', 'GAUNTLET CLEARED')
SAY_CHOSEN = 'Fighter Gauntlet: {title} ({waves} waves), {humans} player(s), team of {size}, HP per wave: {refill}.'
SAY_ARMED = 'Fighter Gauntlet armed: wave 1 is {names}.'
SAY_WAVE = 'Fighter Gauntlet: wave {n} / {count} - {label}.'
SAY_CLEARED = 'Fighter Gauntlet cleared: all {count} waves.'
SAY_LOST = 'Fighter Gauntlet over: reached wave {n} / {count}.'
SAY_LOADED = 'Fighter Gauntlet: {name} ready in enemy slot {slot} ({seconds:.1f} s, the match kept running).'
SAY_LOAD_FAILED = 'Fighter Gauntlet: {name} could not be loaded ({reason}); the wave goes on without it.'
SAY_CANCELLED = 'Fighter Gauntlet: setup left ({why}).'
SAY_FIGHT = 'Fighter Gauntlet: wave 1 / {count} - fight!'
SAY_ENTERS = 'Fighter Gauntlet: wave {n} / {count} enters.'
SAY_COUNTDOWN = 'Fighter Gauntlet: wave {n} / {count} cleared; next wave in 15 s.'
SAY_RETRY = 'Fighter Gauntlet: Retry - the run starts again at wave 1.'
UNUSABLE = '{n} gauntlet(s) in the file could not be used.'


class Setup:
    def __init__(self, gauntlet, humans=1, size=3, refill='off'):
        self.gauntlet, self.humans, self.size, self.refill = gauntlet, humans, max(size, humans, 1), refill

    def describe(self, settings=None):
        label = next(l for k, l, _ in data.REFILL if k == self.refill)
        return tr(SAY_CHOSEN, settings, title=self.gauntlet['title'], waves=len(self.gauntlet['waves']),
                  humans=self.humans, size=self.size, refill=tr(label, settings))


# ---------------------------------------------------------------- the run plan
def wave_rows(gauntlet, potara):
    """gauntlet_data.plan() as the guest's wave table rows (HP = four bars + the items' and buffs' extra HP)."""
    rows = []
    for w in data.plan(gauntlet, potara):
        enemies = [dict(character=e['character'], costume=e['costume'], name=e['name'], items=e['items'],
                        hp=max(data.BAR_HP, BASE_HP + e['extra_hp']), damage=e['damage'], defense=e['defense'])
                   for e in w['enemies']]
        rows.append(dict(label=w['label'], label_es=w.get('label_es') or '', difficulty=w['difficulty'],
                         enemies=enemies, buffed=w['buffed']))
    return rows


def run_plan(gauntlet, potara, setup, players):
    """Everything the run needs, from the gauntlet and Team 1's picks [(character, costume, items16)].

    Enemy roster: physical 1 (the native leader) is wave 1's first fighter, the extras 3/5/7/9 hold the rest of
    wave 1, then preloaded fighters of the next waves (READY for their wave) while the resource budget allows, then
    copies of an already loaded extra (no extra resource record) that are free for recycling."""
    waves = wave_rows(gauntlet, potara)
    if not players:
        raise ValueError('Team 1 has no fighters')
    players = players[:TEAM_MAX]
    player_extras = {(c, k) for c, k, _ in players[1:]}
    first = waves[0]['enemies']
    roster = {1: dict(enemy=first[0], wave=1, index=0, state=runtime.ACTIVE)}
    extras = list(RECYCLED)
    for k, e in enumerate(first[1:5], 1):
        roster[extras.pop(0)] = dict(enemy=e, wave=1, index=k, state=runtime.ACTIVE)

    def distinct():
        keys = {(r['enemy']['character'], r['enemy']['costume']) for p, r in roster.items() if p != 1}
        return len(player_extras | keys)
    # Preload the following waves' fighters into the remaining extras while the record budget allows.
    queue = [(w, k, e) for w, wave in enumerate(waves[1:], 2) for k, e in enumerate(wave['enemies'])]
    preloaded = 0
    while extras and queue:
        w, k, e = queue[0]
        roster[extras[0]] = dict(enemy=e, wave=w, index=k, state=runtime.READY)
        if distinct() > RECORD_BUDGET:
            del roster[extras[0]]
            break
        extras.pop(0); queue.pop(0); preloaded += 1
    # Free slots: a copy of an extra already in the match (same bundle), else of the leader.
    for p in extras:
        source = next((r['enemy'] for q, r in roster.items() if q != 1), None)
        if source is None:
            source = next((dict(character=c, costume=k) for c, k, _ in players[1:]), None) or first[0]
        roster[p] = dict(enemy=dict(source, items=[]), wave=0, index=0, state=runtime.VANISHED)
    if distinct() > RECORD_BUDGET + 1:
        raise ValueError('This team and wave 1 use too many different fighters for the gauntlet to load the next '
                         'waves; pick fewer different fighters for Team 1')
    count = len(players)
    player_mask = sum(1 << (2 * i) for i in range(count))
    enemy_mask = sum(1 << p for p in ENEMY_PHYSICALS)
    slots = {}
    for p, r in roster.items():
        e = r['enemy']
        wave = waves[r['wave'] - 1] if r['wave'] else None
        # A fighter preloaded on the Team Select keeps its native health (hp 0) unless its plan adds some.
        hp = e.get('hp', BASE_HP)
        if r['state'] == runtime.READY and hp == BASE_HP:
            hp = 0
        slots[p] = dict(state=r['state'], wave=r['wave'], index=r['index'], character=e['character'],
                        hp=hp, damage=round(e.get('damage', 1) * 1000),
                        defense=round(e.get('defense', 1) * 1000), difficulty=wave['difficulty'] if wave else 1)
    refill = next(a for k, _, a in data.REFILL if k == setup.refill)
    return dict(gauntlet=gauntlet['id'], title=gauntlet['title'], waves=waves, players=players, roster=roster,
                slots=slots, player_mask=player_mask, enemy_mask=enemy_mask,
                wave_mask=sum(1 << p for p, r in roster.items() if r['wave'] == 1),
                participants=player_mask | enemy_mask, gate_mask=sum(1 << p for p in RECYCLED),
                refill=0xFFFFFFFF if refill is None else refill, humans=setup.humans, preloaded=preloaded)


def mission(run, game):
    """The story mission the run is built on: Team 1 as picked, Team 2 = the enemy roster (wave 1 active, the rest
    reserves whose entrance never fires: the gauntlet admits them), no enemy transformations, and an authored win
    condition that never comes true, so the story holds the enemy side's KO until the gauntlet ends the run."""
    fighters = []
    for k, (character, costume, _) in enumerate(run['players'], 1):
        fighters.append(dict(id=f'player{k}', team=1, slot=k, character=character, costume=costume))
    events = []
    first = run['waves'][0]
    for slot, p in enumerate(ENEMY_PHYSICALS, 1):
        r = run['roster'][p]; e = r['enemy']
        f = dict(id=f'enemy{slot}', team=2, slot=slot, character=e['character'], costume=e['costume'],
                 reserve=r['wave'] != 1, transformations=dict(enabled=False))
        if r['wave'] == 1:
            f.update(hp=e['hp'], difficulty=first['difficulty'],
                     stats=dict(damage=e['damage'], defense=e['defense']))
        fighters.append(f)
        if f['reserve']:
            events.append(dict(id=f'reserve{slot}', when=dict(type='time', seconds=86400),
                               actions=[dict(type='enter', fighter=f['id'], intro=False)], timeout_seconds=300))
    return dict(schema='tag-team-mission', version=1, game_family=game, player_team=1, player_selection=True,
                menus=dict(retry=True, character_select=False), cpu_profiles={}, id='fighter-gauntlet',
                title=f"Fighter Gauntlet: {run['title']}"[:120],
                description='Generated by the Fighter Gauntlet mode.', stage=None, defeat_grace_seconds=300,
                source=dict(kind='fighter-gauntlet', gauntlet=run['gauntlet']), fighters=fighters, events=events,
                win_when=dict(type='time', seconds=86400), music=None)


def arm(run, game=None):
    """Arm the story mission and the run (consumed by the next prepared Team Battle)."""
    import atomic_files
    import story_missions
    game = game or data.family()
    doc = story_missions.validate(mission(run, game))
    story_missions.arm(doc)
    record = dict(schema=1, mission=story_missions.digest(doc), run=run, armed=time.time())
    NEXT.parent.mkdir(parents=True, exist_ok=True)
    atomic_files.write_json(NEXT, record)
    return doc


def armed(mission_doc):
    """The armed run for this prepared story mission, or None (a different/stale mission ignores the file)."""
    import atomic_files
    import story_missions
    if mission_doc is None:
        return None
    try:
        record = atomic_files.read_json(NEXT)
    except (FileNotFoundError, OSError, ValueError):
        return None
    if record.get('schema') != 1 or record.get('mission') != story_missions.digest(mission_doc):
        return None
    run = record['run']
    run['slots'] = {int(k): v for k, v in run['slots'].items()}
    run['roster'] = {int(k): v for k, v in run['roster'].items()}
    return run


def consumed():
    try:
        NEXT.unlink()
    except OSError:
        pass


def disarm():
    import story_missions
    consumed()
    try:
        story_missions.disarm()
    except (OSError, AttributeError):
        pass


def settings_for(settings):
    """A gauntlet match's settings: ring-outs never decide it, downed teammates can be revived."""
    out = dict(settings)
    out['tournament_ring_outs'] = False
    out['revive_enabled'] = True
    return out


# ---------------------------------------------------------------- Team Select: Team 2 from the run
def enemy_records(p, obj, run):
    """5 x 48-byte Team Select records of Team 2 (grid, form and base from this disc's live selector table)."""
    total = p.read_u32(obj + 0x9A8 + 4)
    if not 1 <= total <= 512:
        raise ValueError('Team Select character table has an invalid length')
    table = p.read_u32(obj + 0x9B0 + 4)
    rows = list(struct.iter_unpack('<9I', p.read(table, total * 36)))
    lookup = {}
    for grid, row in enumerate(rows):
        for form, cid in enumerate(row[2:2 + row[1]] if row[1] else (row[0],)):
            lookup.setdefault(cid, (grid, form, row[0]))
    blob = bytearray(5 * 48)
    for slot, physical in enumerate(ENEMY_PHYSICALS):
        e = run['roster'][physical]['enemy']
        if e['character'] not in lookup:
            raise ValueError(f"This disc's Team Select has no fighter {e['character']}")
        grid, form, base = lookup[e['character']]
        struct.pack_into('<8I', blob, slot * 48, grid % 7, grid // 7, form, 0, base, 0, e['costume'], e['character'])
        items = [x + 1 for x in (e.get('items') or [])][:8] if run['roster'][physical]['wave'] == 1 else []
        struct.pack_into('<8H', blob, slot * 48 + 32, *(items + [0] * (8 - len(items))))
    return bytes(blob)


# ---------------------------------------------------------------- the setup panel
ROW_H = 30
# Panel layout (round 3 redesign).
LIST_ROWS, LIST_STEP = 12, 17          # left list lines and their pitch
SETTING_H = 25                         # settings rows and the Continue bar
CARD_FIRST, PORTRAIT, BOSS = 5, 44, 52  # first-wave portraits shown, their size, the final boss portrait
BOSS_CARD = 96                         # the Setup card's final-boss portrait
PORTRAIT_COLORS = 12                   # colours per portrait (the picture's GS sprite budget)


class Panel:
    """Player-Setup style host panel (team_assignment's guest input and picture surface, the hub's check-ins)."""

    def __init__(self, owner):
        self.owner = owner
        self.active = False; self.screen = None; self.row = 0
        self.index = 0; self.humans = 1; self.size = 3; self.refill = 0
        self.hub = None; self.settings = {}; self.view = None; self.helper = None
        self.input_ready = False; self.drawn = None; self.drawn_at = 0.0; self.dirty = False; self.opened_at = None
        self.chosen = None          # the gauntlet picked on the native picker page

    def library(self):
        return self.owner.library()

    def ordered(self):
        """The gauntlets in the panel's own order: grouped by category, as listed."""
        return [g for _, items in data.grouped(self.library()['gauntlets']) for g in items]

    def gauntlet(self):
        if self.chosen is not None:
            return self.chosen
        items = self.ordered()
        return items[min(self.index, len(items) - 1)] if items else None

    def rows(self):
        return [('players',), ('size',), ('refill',), ('continue',)]

    def setup(self):
        return Setup(self.gauntlet(), self.humans, self.size, data.REFILL[self.refill][0])

    def assignment_helper(self):
        import team_assignment
        if self.helper is None:
            self.helper = team_assignment.Controller()
        self.helper.view = self.view
        self.helper.teams = [0] * self.humans
        self.helper.choice = None
        self.helper.opened_at = self.opened_at
        return self.helper

    def open_hub(self):
        if self.hub is None or self.humans == 0:
            return
        try:
            self.hub.start()
            self.hub.open_setup(self.humans, False, mode=self.settings.get('controller_checkin'),
                                keep=self.settings.get('keep_controller_checkins'))
        except RuntimeError:
            pass

    def close_hub(self, commit):
        if self.hub is None:
            return
        try:
            self.hub.close_setup(commit)
        except RuntimeError:
            pass

    def ready(self):
        return self.gauntlet() is not None and (self.humans < 2 or self.assignment_helper().ready())

    def change(self, row, step, page=0):
        kind = row[0]
        if kind == 'gauntlet':
            items = self.ordered()
            if not items:
                return
            if page:
                starts = [i for i, g in enumerate(items) if i == 0 or g['category'] != items[i - 1]['category']]
                mine = max(s for s in starts if s <= self.index)
                if page > 0:
                    self.index = next((s for s in starts if s > self.index), 0)
                elif self.index > mine:
                    self.index = mine
                else:
                    self.index = starts[starts.index(mine) - 1] if starts.index(mine) else starts[-1]
            else:
                self.index = (self.index + step) % len(items)
        elif kind == 'players':
            self.humans = (self.humans + step) % 5
            self.size = max(self.size, self.humans, 1)
            self.close_hub(False); self.open_hub()
        elif kind == 'size':
            self.size = min(TEAM_MAX, max(self.humans, 1, self.size + step))
        elif kind == 'refill':
            self.refill = (self.refill + step) % len(data.REFILL)

    def visible(self, rows=7):
        """The list lines around the selected gauntlet: ('header', title) / ('item', index, gauntlet)."""
        lines = []
        index = 0
        for title, items in data.grouped(self.library()['gauntlets']):
            lines.append(('header', title))
            for g in items:
                lines.append(('item', index, g)); index += 1
        at = next(i for i, l in enumerate(lines) if l[0] == 'item' and l[1] == self.index)
        first = max(0, min(at - rows // 2, len(lines) - rows))
        return lines[first:first + rows]

    def card_facts(self, g):
        """(wave count, (lowest, highest) CPU level names, [(character, name)] of the first waves' leaders, the
        final boss (character, name) or None) of gauntlet g."""
        waves = g['waves']
        levels = [data.difficulty(i, len(waves), w, g.get('difficulty')) for i, w in enumerate(waves)]
        names = data.LEVELS
        span = (names[min(levels)], names[max(levels)]) if levels else (names[data.EASY], names[data.HARDEST])
        lead = lambda w: (w['fighters'][0]['character'], w['fighters'][0].get('name') or fighter_name(w['fighters'][0]['character']))
        firsts = [lead(w) for w in waves[:-1][:CARD_FIRST] if w['fighters']]
        boss = lead(waves[-1]) if waves and waves[-1]['fighters'] else None
        return len(waves), span, firsts, boss

    def picture(self):
        """The Setup screen: the chosen gauntlet's card, then Players, Team size, HP back per wave, Continue."""
        from PIL import Image, ImageDraw
        import fonts
        import team_assignment as ta
        t = lambda text, **values: tr(text, self.settings, **values)
        im = Image.new('RGB', (512, 448), ta.BG)
        d = ImageDraw.Draw(im)
        title = fonts.truetype('sans-bold', 22)
        big = fonts.truetype('sans-bold', 15)
        font = fonts.truetype('sans-bold', 13)
        small = fonts.truetype('sans', 12)
        bold = fonts.truetype('sans-bold', 12)
        tiny = fonts.truetype('sans-bold', 10)
        d.rectangle((0, 0, 511, 4), fill=ta.BAR)
        d.text((18, 10), t(TITLE), font=title, fill=ta.GOLD)
        d.fontmode = '1'
        self._fit(d, (19, 36), t(INTRO), ta.TEXT, width=474)
        library = self.library()
        g = self.gauntlet()
        portraits = []
        # The chosen gauntlet: title, blurb, chips; portraits of the first waves and the final boss.
        cx0, cy0, cx1, cy1 = 14, 56, 498, 214
        d.rounded_rectangle((cx0, cy0, cx1, cy1), radius=6, fill=ta.PANEL, outline=ta.EDGE, width=2)
        if g is not None:
            count, span, firsts, boss = self.card_facts(g)
            self._fit(d, (cx0 + 12, cy0 + 8), g['title'], ta.WHITE, font='sans-bold', size=16, width=300)
            blurb_text = description(g, self.settings)
            y = self._wrap(d, blurb_text, cy0 + 32, small, ta.TEXT, lines=2, x=cx0 + 12, width=300)
            y = max(y, cy0 + 32 + 2 * 15) + 6
            x = cx0 + 12
            for chip in (t(WAVES_VALUE, n=count) if count != 1 else t(WAVE_VALUE),
                         t(CPU_RANGE, low=t(span[0]), high=t(span[1])) if span[0] != span[1] else t(CPU_ONE, level=t(span[0]))):
                x = self._chip(d, x, y, chip, tiny, ta.BG, ta.GOLD) + 6
            y += 24
            d.text((cx0 + 12, y), t(FIRST_WAVES), font=tiny, fill=ta.DIM)
            py = y + 14
            for k, (cid, name) in enumerate(firsts):
                portraits.append((cx0 + 12 + k * (PORTRAIT + 8), py, PORTRAIT, cid, name))
            self._fit(d, (cx0 + 12, py + PORTRAIT + 4), ' · '.join(n for _, n in firsts) +
                      (' · …' if count > len(firsts) + 1 else ''), ta.DIM, size=10, width=300)
            if boss is not None:
                bx = cx1 - 12 - BOSS_CARD
                d.text((bx, cy0 + 10), t(FINAL_BOSS), font=tiny, fill=ta.GOLD)
                portraits.append((bx, cy0 + 26, BOSS_CARD, boss[0], boss[1]))
                self._wrap(d, boss[1], cy0 + 30 + BOSS_CARD, fonts.truetype('sans-bold', 10), ta.WHITE, lines=2,
                           x=bx - 2, width=BOSS_CARD + 8, step=11)
        # Settings: label left, value chip right.
        y = 224
        for index, row in enumerate(self.rows()[:-1]):
            kind = row[0]
            sel = self.row == index
            d.rounded_rectangle((14, y, 498, y + SETTING_H - 4), radius=6, fill=ta.PANEL,
                                outline=ta.GOLD if sel else ta.EDGE, width=2)
            label = t({'players': PLAYERS_ROW, 'size': SIZE_ROW, 'refill': REFILL_ROW}[kind])
            value = (t(CPU_ONLY) if self.humans == 0 else str(self.humans)) if kind == 'players' else \
                str(self.size) if kind == 'size' else t(REFILL_LABELS[self.refill])
            d.text((28, y + 5), label, font=font, fill=ta.WHITE)
            self._value_chip(d, 498 - 12, y + 4, value, font, sel, ta)
            y += SETTING_H
        sel = self.row == len(self.rows()) - 1
        d.rounded_rectangle((14, y, 498, y + SETTING_H - 2), radius=6, fill=ta.GOLD if sel else ta.PANEL,
                            outline=ta.GOLD if sel else ta.EDGE, width=2)
        ready = self.ready()
        d.text((28, y + 5), t(CONTINUE_LABEL), font=big, fill=(ta.BG if sel else ta.WHITE) if ready else ta.DIM)
        if self.humans >= 2:
            seats = self.assignment_helper().seats()
            x = 200
            for n in range(self.humans):
                kind_, text, _ = seats[n] if n < len(seats) else ('default', '', None)
                color = {'empty': ta.GOLD, 'default': ta.DIM, 'pad': ta.GREEN, 'lost': ta.RED}.get(kind_, ta.DIM)
                if sel and color == ta.GOLD:
                    color = ta.BG
                d.ellipse((x, y + 10, x + 8, y + 18), fill=color)
                d.text((x + 11, y + 6), f'P{n + 1}', font=bold, fill=color)
                x += 52
        y += SETTING_H + 6
        if library['problems']:
            self._fit(d, (18, y), t(UNUSABLE, n=len(library['problems'])), ta.RED, width=476)
        elif self.humans == 0:
            self._fit(d, (18, y), t(CPU_NOTE), ta.GOLD, width=476)
        else:
            self._fit(d, (18, y), t(SUMMARY, n=self.size, h=self.humans, c=self.size - self.humans), ta.GOLD, width=476)
        d.rectangle((0, 412, 511, 447), fill=ta.PANEL)
        d.line((0, 412, 511, 412), fill=ta.EDGE)
        self._fit(d, (14, 416), t(FOOTER_P1), ta.TEXT, width=484)
        self._fit(d, (14, 431), t(FOOTER_ALL), ta.GOLD, width=484)
        out = im.quantize(palette=ta.palette(), dither=Image.Dither.NONE).convert('RGB')
        for px, py, size, cid, name in portraits:
            self._portrait(out, px, py, size, cid, name, ta)
        return out

    @staticmethod
    def _chip(d, x, y, text, font, ink, fill):
        w = d.textlength(text, font=font)
        d.rounded_rectangle((x, y, x + w + 14, y + 17), radius=8, fill=fill)
        d.text((x + 7, y + 3), text, font=font, fill=ink)
        return x + w + 14

    @staticmethod
    def _value_chip(d, right, y, value, font, selected, ta):
        """< value > in a chip ending at `right`; the arrows only on the selected row."""
        import fonts
        for s in (13, 12, 11, 10):
            f = fonts.truetype('sans-bold', s)
            w = d.textlength(value, font=f)
            if w <= 230:
                break
        width = max(70, w + 46)
        x0 = right - width
        d.rounded_rectangle((x0, y, right, y + SETTING_H - 8), radius=9, fill=ta.BG,
                            outline=ta.GOLD if selected else ta.EDGE, width=1)
        d.text((x0 + (width - w) / 2, y + 1 + (13 - s) // 2), value, font=f, fill=ta.GOLD if selected else ta.WHITE)
        if selected:
            d.text((x0 + 7, y + 2), '<', font=font, fill=ta.GOLD)
            d.text((right - 15, y + 2), '>', font=font, fill=ta.GOLD)

    @staticmethod
    def _portrait(out, x, y, size, cid, name, ta):
        """The disc's own portrait (character_names; a few colours, so the picture stays in its GS budget); a
        framed initial when the disc has none."""
        from PIL import Image, ImageDraw
        import fonts
        d = ImageDraw.Draw(out)
        frame = ta.GOLD if size in (BOSS, BOSS_CARD) else ta.EDGE
        try:
            from character_names import character_info
            path = character_info(cid)['bitmap_path']
            with Image.open(path) as source:
                pic = source.convert('RGB').resize((size, size)).quantize(colors=PORTRAIT_COLORS).convert('RGB')
            out.paste(pic, (x, y))
        except (OSError, KeyError, TypeError, ValueError, AttributeError):  # no extracted portrait
            d.rectangle((x, y, x + size - 1, y + size - 1), fill=ta.BG)
            d.text((x + size // 2 - 5, y + size // 2 - 8), (name or '?')[:1], font=fonts.truetype('sans-bold', 15),
                   fill=ta.DIM)
        d.rectangle((x - 1, y - 1, x + size, y + size), outline=frame, width=2 if size in (BOSS, BOSS_CARD) else 1)

    @staticmethod
    def _fit(d, xy, text, color, size=12, width=462, font='sans'):
        """One line, in `font` shrunk (down to 9 px) until it fits."""
        import fonts
        for s in range(size, 8, -1):
            f = fonts.truetype(font, s)
            if d.textlength(text, font=f) <= width:
                break
        d.text(xy, text, font=f, fill=color)

    @staticmethod
    def _wrap(d, text, y, font, color, lines=2, x=25, width=462, step=15):
        row, count = '', 0
        for word in text.split():
            trial = (row + ' ' + word).strip()
            if row and d.textlength(trial, font=font) > width:
                d.text((x, y), row, font=font, fill=color)
                y += step; count += 1; row = word
                if count >= lines:
                    return y
            else:
                row = trial
        if row:
            d.text((x, y), row, font=font, fill=color)
            y += step
        return y

    def tick(self, p):
        import team_assignment as ta
        wanted = (p.read_u32(ta.MENU) == ta.MAGIC and p.read_u32(ta.MENU + ta.STATE) == 1 and
                  p.read_u32(ta.MENU + ta.CHOICE) == CHOICE)
        if not wanted:
            if self.active:
                self.close(p)
            return False
        if not self.active:
            from guest_loading_screen import GuestLoadingScreen
            self.screen = GuestLoadingScreen()
            self.active = True; self.row = 0
            picked = self.owner.pager.picked(p)
            if picked is not None:
                self.chosen = picked
            self.input_ready = False; self.drawn = None; self.dirty = True; self.opened_at = time.monotonic()
            self.open_hub()
        p.write_u32(ta.MENU + ta.LEASE, ta.HOST_LEASE)
        p.write_u32(ta.MENU + 16, ta.HOST_LEASE)
        now = time.monotonic()
        if self.hub is not None:
            try:
                self.view = self.hub.snapshot()
            except RuntimeError:
                self.view = None
        buttons = p.read_u32(ta.MENU + ta.BUTTONS)
        if buttons:
            p.write_u32(ta.MENU + ta.BUTTONS, 0)
        from regional import RAW_ACCEPT, RAW_BACK
        if buttons & RAW_BACK:
            p.write_u32(ta.MENU + ta.STATE, 0)
            p.write_u32(ta.MENU + ta.VALID, 0)
            self.close(p)
            return True
        if not self.screen.presented(p):
            buttons = 0
        elif not self.input_ready:
            import mode_menu
            self.input_ready = p.read_u32(mode_menu.PAD + 0x150) == 0
            buttons = 0
        rows = self.rows()
        self.row = min(self.row, len(rows) - 1)
        if buttons & 0x50:
            self.row = (self.row + (1 if buttons & 0x40 else -1)) % len(rows)
            self.dirty = True
        step = 1 if buttons & 0x20 else -1 if buttons & 0x80 else 0
        page = 1 if buttons & 0x800 else -1 if buttons & 0x400 else 0
        row = rows[self.row]
        if step:
            self.change(row, step, page)
            self.dirty = True
        if buttons & RAW_ACCEPT and row[0] == 'continue' and self.ready():
            setup = self.setup()
            self.close(p, commit=True)
            self.owner.begin(p, setup)
            return True
        state = (self.index, id(self.chosen), self.humans, self.size, self.refill, self.row,
                 tuple(self.assignment_helper().seats()) if self.humans >= 2 else (), self.ready())
        if state != self.drawn:
            self.dirty = True
        if self.dirty and now - self.drawn_at >= 0.25:
            self.screen.show_picture(self.picture(), surface='menu', client=p)
            self.drawn, self.drawn_at, self.dirty = state, now, False
        else:
            self.screen.sync(client=p)
        return True

    def close(self, p, commit=False):
        import mode_menu
        import team_assignment as ta
        p.write_u32(ta.MENU + 28, p.read_u32(mode_menu.PAD + 0x150))
        if self.screen:
            self.screen.hide(client=p)
        if self.active:
            self.close_hub(commit)
        self.screen = None
        self.active = False

    def shutdown(self):
        if self.active:
            self.close_hub(False)
        self.active = False


# ---------------------------------------------------------------- the controller (menus)
# ---------------------------------------------------------------- native picker page (native_mode_menu page 6)
PAGE = 6                     # native_mode_menu.PAGES index of the picker page
SLOTS_N = 8                  # its native rows = label cells of one atlas
G_OFF, G_ON = 0x06C90000, 0x06CB1000          # owned label atlases (OFF / ON), 0x21000 each
GTEXT, GTABLE = 0x06CD2000, 0x06CD4000        # its description DBT (fixed slots) and the page table
GTEXT_SIZE, TEXT_SLOT = 0x2000, 0x200
GMAGIC = 0x31475047                           # 'GPG1'
# GTABLE: +0 magic, +4 list length, +16 kind[8] (1 back, 2 gauntlet), +48 picked row label, +64 item[8]
#         (virtual list index shown by each row), +96 page generation.
KIND_BACK, KIND_GAUNTLET = 1, 2
BAND = 512 * 32                                # one swizzled 32-row label cell
PIXELS = 64 + 0x60                             # cell 0 of an owned atlas: descriptor + IMAGE packet header
LINE = 46                                      # characters of one native description line
PICKER_BACK = 'Return to the mod mode groups.'
PICKER_WAVES = '{n} waves - Final: {boss}'
PICKER_WAVE = '1 wave - Final: {boss}'
PICKER_CPU = 'CPU from {low} to {high}.'
PICKER_CPU_ONE = 'CPU {level}.'
LABEL_PIXELS = 380                             # widest row label (the native label font, 22 px)


def picker_gauntlets(library):
    """Every gauntlet in picker order: the categories in menu order with Quick Test (test) last."""
    groups = [(c, [g for g in library['gauntlets'] if g['category'] == c])
              for c in dict.fromkeys(g['category'] for g in library['gauntlets'])]
    order = {c: i for i, c in enumerate(data.CATEGORY_ORDER)}
    groups.sort(key=lambda cg: (cg[0] == 'test', order.get(cg[0], 99), cg[0]))
    return [g for _, items in groups for g in items]


def _line(text, limit=LINE):
    text = ' '.join(str(text or '').split())
    if len(text) <= limit:
        return text
    cut = text[:limit - 3].rsplit(' ', 1)[0].rstrip(',;:-')
    return cut + '...'


def description(g, settings=None):
    """The gauntlet's description in the chosen language: Spanish reads the data's description_es ('' when a
    gauntlet has none: the card then shows no blurb and the picker row states its facts)."""
    if localization.language(settings) == 'es':
        return str(g.get('description_es') or '')
    return str(g.get('description') or '')


def blurb(g, settings=None):
    """The gauntlet's short blurb: its first sentence or clause, one native line."""
    text = ' '.join(str(description(g, settings) or g['title']).split())
    for mark in ('. ', ': ', '; '):
        if mark in text and len(text.split(mark)[0]) >= 12:
            text = text.split(mark)[0] + ('.' if mark == '. ' else '')
            break
    if len(text) > LINE:
        # A clause rather than a cut word: up to the last comma / bracket that keeps it on the line.
        for mark in (', ', ' (', ' - '):
            head = text[:LINE].rsplit(mark, 1)[0]
            if mark in text[:LINE] and len(head) >= 12:
                return head.rstrip('.,') + '.'
    return _line(text.rstrip('.') + '.' if not text.endswith(('.', '!', '?')) else text)


def picker_items(library, settings=None):
    """[(label, description lines 1-2, kind, gauntlet or None)] of the picker list: Back, then the gauntlets."""
    out = [(tr('Back', settings), tr(PICKER_BACK, settings), KIND_BACK, None)]
    for g in picker_gauntlets(library):
        waves = g['waves']
        boss = waves[-1]['fighters'][0] if waves and waves[-1]['fighters'] else None
        name = (boss.get('name') or fighter_name(boss['character'])) if boss else '?'
        n = len(waves)
        second = tr(PICKER_WAVES if n != 1 else PICKER_WAVE, settings, n=n, boss=name)
        if localization.language(settings) == 'es' and not description(g, settings):
            # A gauntlet with no Spanish blurb: the Spanish row states its facts instead.
            levels = [data.difficulty(i, n, w, g.get('difficulty')) for i, w in enumerate(waves)] or [data.EASY]
            low, high = data.LEVELS[min(levels)], data.LEVELS[max(levels)]
            first = (tr(PICKER_CPU, settings, low=tr(low, settings), high=tr(high, settings)) if low != high
                     else tr(PICKER_CPU_ONE, settings, level=tr(low, settings)))
        else:
            first = blurb(g, settings)
        out.append((_label(g['title']), _line(first) + '\n' + _line(second), KIND_GAUNTLET, g))
    return out


def _label(title):
    """A row label as wide as the native rows show (the generator draws 22 px text in a 512 px cell)."""
    import fonts
    from PIL import Image, ImageDraw
    font = fonts.truetype('sans-bold', 22)
    d = ImageDraw.Draw(Image.new('L', (1, 1)))
    title = ' '.join(title.split())
    if d.textlength(title, font=font) <= LABEL_PIXELS:
        return title
    while title and d.textlength(title + '...', font=font) > LABEL_PIXELS:
        title = title[:-1].rstrip()
    return title + '...'


def baked_items(length):
    """The rows' virtual items when the page opens: the native page shows rows 7, 0..4 (row 0, Back, selected);
    hidden are row 5 (below) and row 6 (above)."""
    return [(slot if slot <= 5 else length - (SLOTS_N - slot)) % length for slot in range(SLOTS_N)]


def window_items(scroll, items, length):
    """What each row must show for native scroll word `scroll` (window = rows scroll .. scroll+5)."""
    s = scroll % SLOTS_N
    top = items[s]
    want = list(items)
    for k in range(-1, SLOTS_N - 1):
        want[(s + k) % SLOTS_N] = (top + k) % length
    return want


def description_text(text, settings, hint):
    import native_menu_assets as assets
    return assets.native_text(text + ('\n' + hint if hint else ''))


def text_dbt(strings):
    """GTEXT: a native DBT of SLOTS_N fixed TEXT_SLOT-byte strings, so one can be rewritten in place."""
    out = bytearray(64)
    struct.pack_into('<I', out, 0, SLOTS_N)
    for i, text in enumerate(strings):
        struct.pack_into('<I', out, 4 + 4 * i, 64 + i * TEXT_SLOT)
        out.extend(text_slot(text))
    return bytes(out)


def text_slot(text):
    blob = ('\ufeff' + text).encode('utf-16le')[:TEXT_SLOT - 2]
    return blob + bytes(TEXT_SLOT - len(blob))


def band(ram, source, label):
    """The swizzled pixels of one label cell for atlas `source` (the generator's own colours)."""
    import native_menu_assets as assets
    return assets.swizzle(assets.compose_indices(ram, source, (label,)))[:BAND]


def page_blocks(ram, obj, atlases, settings, hint):
    """The picker page as baked when published: both atlases, the DBT and the table (native_mode_menu._assets)."""
    import native_menu_assets as assets
    library = data.load()
    items = picker_items(library, settings)
    length = len(items)
    slots = baked_items(length)
    labels = tuple(items[v][0] for v in slots)
    blocks = []
    for name, dest, limit in (('off', G_OFF, G_ON), ('on', G_ON, G_ON + 0x21000)):
        blob = assets.clone(ram, atlases[name], dest, assets.compose_indices(ram, atlases[name], labels))
        if dest + len(blob) > limit:
            raise ValueError('Gauntlet picker atlas exceeds its reservation')
        blocks.append((dest, blob))
    blocks.append((GTEXT, text_dbt([description_text(items[v][1], settings, hint) for v in slots])))
    table = bytearray(0x100)
    struct.pack_into('<2I', table, 0, GMAGIC, length)
    struct.pack_into('<8I', table, 16, *(items[v][2] for v in slots))
    struct.pack_into('<8I', table, 64, *slots)
    blocks.append((GTABLE, bytes(table)))
    return blocks


def native_atlases(view, obj):
    """The menu's own OFF / ON label atlases (its image table), as native_menu_assets.inspect finds them but
    without its native-row check (the picker page has eight rows of its own)."""
    import dataclasses
    import native_menu_assets as assets
    found = {name: assets.atlas(view, assets.u32(view, obj + 0x40 + 4 * i))
             for name, i in assets.LABEL_TABLE_INDICES.items()}
    if found['off'].palette_size == 0xC0 and 'template' in {f.name for f in dataclasses.fields(found['off'])}:
        found['off'] = dataclasses.replace(found['off'], template=found['on'])     # BT4: 4-bit OFF atlas
    return found


class Pager:
    """Host side of the picker page: keeps its two hidden rows labelled while the window scrolls."""

    def __init__(self, owner):
        self.owner = owner
        self.items = None; self.key = None; self.atlases = None; self.bands = {}
        self.writes = 0

    def tick(self, p, settings, hint):
        import mode_menu
        import native_mode_menu as menu
        if p.read_u32(GTABLE) != GMAGIC:
            return False
        page = p.read_u32(menu.CONTROL + 8)
        state = p.read_u32(menu.CONTROL + 4)
        table = p.read(GTABLE, 0x80)
        length = struct.unpack_from('<I', table, 4)[0]
        current = list(struct.unpack_from('<8I', table, 64))
        key = (settings.get('language'), hint)
        if self.items is None or self.key != key or len(self.items) != length:
            self.items = picker_items(self.owner.library(), settings); self.key = key; self.bands = {}
            if len(self.items) != length:
                return False
        obj = p.read_u32(mode_menu.MAIN_OBJECT)
        if page != PAGE or state != 2 or p.read_u32(obj + 0x144) != SLOTS_N:
            want = baked_items(length)          # off the page: back to the opening layout, out of sight
            if page == PAGE:
                return False
        else:
            want = window_items(p.read_u32(obj + 0x148), current, length)
        changed = [s for s in range(SLOTS_N) if want[s] != current[s]]
        if not changed:
            return page == PAGE
        view = menu.ReadOnlyMemory(p)
        if self.atlases is None or self.atlases[0] != obj:
            self.atlases = (obj, native_atlases(view, obj))
        for s in changed:
            label, text, kind, _ = self.items[want[s]]
            for name, dest in (('off', G_OFF), ('on', G_ON)):
                pixels = self.bands.get((name, label))
                if pixels is None:
                    pixels = self.bands[(name, label)] = band(view, self.atlases[1][name], label)
                p.write(dest + PIXELS + s * BAND, pixels)
            p.write(GTEXT + 64 + s * TEXT_SLOT, text_slot(description_text(text, self.key and settings, hint)))
            p.write_u32(GTABLE + 16 + 4 * s, kind)
            p.write_u32(GTABLE + 64 + 4 * s, want[s])
            self.writes += 1
        return page == PAGE

    def picked(self, p):
        """The gauntlet of the row the guest recorded when it was picked, or None."""
        if p.read_u32(GTABLE) != GMAGIC:
            return None
        slot = p.read_u32(GTABLE + 48)
        if not 0 <= slot < SLOTS_N:
            return None
        item = p.read_u32(GTABLE + 64 + 4 * slot)
        items = self.items or picker_items(self.owner.library(), self.owner.settings)
        return items[item][3] if item < len(items) else None


class Controller:
    """Owned by native_mode_menu.Controller (ticked before Player Setup in every scene)."""

    def __init__(self):
        self.panel = Panel(self)
        self.pager = Pager(self)
        self.settings = {}
        self.log = lambda message: None
        self.setup = None
        self.stage = None          # 'select' while Team 1 is picked, 'armed' after Team 2 was written
        self.run = None
        self.since = 0.0
        self._library = None

    def library(self):
        if self._library is None or time.monotonic() - self._library[0] > 30:
            self._library = (time.monotonic(), data.load())
        return self._library[1]

    @property
    def pending(self):
        return self.stage is not None

    def begin(self, p, setup):
        """Continue: the same receipt Player Setup publishes with every player on Team 1, then Team Battle."""
        import team_assignment as ta
        self.setup = setup
        self.stage = 'select'; self.since = time.monotonic(); self.run = None
        humans = setup.humans
        if humans >= 2:
            seats = ta.physical_seats([0] * humans)
            p.write(ta.MENU + ta.SEATS, struct.pack('<4I', *(seats + (0xFFFFFFFF,) * (4 - len(seats)))))
        p.write_u32(ta.MENU + ta.HUMANS, humans)
        p.write_u32(ta.MENU + ta.VALID, int(humans >= 2))
        # CPU only is the Team Battle "CPU Only" choice (8); 1..4 players the Player Setup choices.
        p.write_u32(ta.MENU + ta.CHOICE, {0: 8, 1: 1, 2: 7, 3: 17, 4: 12}[humans])
        p.write_u32(ta.MENU + ta.STATE, 2)
        self.log(setup.describe(self.settings))

    def scene(self, p):
        import mode_menu
        manager = p.read_u32(mode_menu.SCENE_MANAGER)
        if not 0x100000 <= manager < 0x1FFF000:
            return None
        return p.read_u32(manager + 0x18)

    def menu_tick(self, p):
        if self.stage is not None:
            self.select_tick(p)
        return self.panel.tick(p)

    def select_tick(self, p):
        import tag_tournament as tt
        scene = self.scene(p)
        if self.stage == 'select':
            if scene == MAIN_MENU and time.monotonic() - self.since > 8.0:
                self.cancel('the Team Select was left'); return
            if scene != SELECT_SCENE:
                return
            state = tt.selection_state(p)
            if state is None:
                return
            obj, sides, stage_open = state
            (lcount, lstate, left), (rcount, rstate, right) = sides
            if lstate != tt.SEL_DONE or rstate == tt.SEL_DONE:
                return
            players = [(c, k, bytes(items).hex()) for c, k, items in tt.read_selection(p, 0)]
            g = self.setup.gauntlet
            try:
                run = run_plan(g, self.library()['potara'], self.setup, players)
                blob = enemy_records(p, obj, run)
            except ValueError as error:
                self.log(f'Fighter Gauntlet: {error}')
                return
            p.write(right, blob)
            p.write_u32(right + tt.SEL_COUNT, 5)
            p.write_u32(right + tt.SEL_HOVER, 5)
            p.write_u32(right + tt.SEL_STATE, tt.SEL_DONE)
            arm(run)
            self.run = run; self.stage = 'armed'; self.since = time.monotonic()
            self.log(tr(SAY_ARMED, self.settings, names=', '.join(e['name'] for e in run['waves'][0]['enemies'])))
            return
        if self.stage == 'armed':
            # The match prepares with the armed run; back at the main menu without one, the run is withdrawn.
            if scene == MAIN_MENU and time.monotonic() - self.since > 8.0 and NEXT.exists():
                self.cancel('the arena select was left')
            elif not NEXT.exists():
                self.stage = None

    def cancel(self, why):
        disarm()
        self.stage = None; self.run = None
        self.log(tr(SAY_CANCELLED, self.settings, why=why))


# ---------------------------------------------------------------- the match service (watcher, every loop)
_NAMES = {}


def fighter_name(character):
    if not _NAMES:
        _NAMES.update({row['id']: row['name'] for row in data.default_roster(data.family())})
    return _NAMES.get(character, f'Fighter {character}')


def guest_active(p):
    return p.read_u32(runtime.CONTROL) == runtime.MAGIC and p.read_u32(runtime.CONTROL + runtime.C['waves']) > 0


STEP_BUDGET = 1.0          # seconds of back-to-back load steps per watcher loop
SWEEP_SECONDS = 5.0        # a kept bundle of a hidden slot is retried at most this often
LOAD_ATTEMPTS = 2          # a failed load is retried once (after its rollback), then that fighter is skipped
RECORD_RETRIES = 12        # io 130 (no free resource record) attempts while kept bundles may still retire


class Service:
    """Streams the upcoming fighters into free enemy slots. Everything it needs is read from guest RAM."""

    def __init__(self, log=print):
        self.log = log
        self.assigned = {}          # physical -> (wave, index) being loaded
        self.delivered = set()      # (wave, index) already made READY (a KO'd fighter never comes back)
        self.calls = []             # wall-clock times of the last ticks (cadence diagnostics)
        self.failures = {}          # (wave, index) -> count
        self.skipped = set()
        self.last_tick = 0
        self.last_state = None
        self.started = time.time()
        self.events = []
        self.sweeps = {}            # physical -> monotonic time before which its kept bundles are not retried
        self.retry_at = 0.0         # loads wait for a sweep after the records ran out (io 130)
        self.kept = 0               # superseded bundles the worker still keeps loaded

    def words(self, p):
        c = runtime.CONTROL
        block = p.read(c, 0x120)
        u = lambda off: struct.unpack_from('<I', block, off)[0]
        return {k: u(v) for k, v in runtime.C.items() if v < 0x120}

    def wave(self, p, number):
        """(difficulty, [(character, costume, hp, damage, defense)]) of wave `number` (1-based) from guest RAM."""
        row = runtime.WAVES + runtime.WAVE_HEADER + runtime.WAVE_STRIDE * (number - 1)
        head = struct.unpack('<5I', p.read(row, 20))
        fighters = [struct.unpack('<5I', p.read(row + 32 + runtime.FIGHTER_STRIDE * k, 20)) for k in range(head[0])]
        return head[1], fighters

    def slot(self, p, physical):
        row = p.read(runtime.SLOTS + runtime.SLOT_STRIDE * physical, runtime.SLOT_STRIDE)
        return {k: struct.unpack_from('<I', row, off)[0] for k, off in runtime.S.items()}

    def note(self, message):
        self.events.append((round(time.time() - self.started, 2), message))
        self.log(message)

    def tick(self, p, worker):
        if not guest_active(p):
            return
        w = self.words(p)
        if w['tick'] < self.last_tick:
            # Retry (Fight Again): the prepared start was loaded again.
            self.assigned.clear(); self.failures.clear(); self.skipped.clear(); self.delivered.clear()
            self.last_state = None
            self.note(tr(SAY_RETRY))
        self.last_tick = w['tick']
        state, waves = w['state'], w['waves']
        if (state, w['wave']) != self.last_state:
            if self.last_state is not None and w['wave'] != self.last_state[1] and state == runtime.FIGHT:
                self.report(p, runtime.INTRO, w)     # the intro was shorter than this loop's period
            self.report(p, state, w)
            self.last_state = (state, w['wave'])
        if state in (runtime.WON, runtime.LOST, runtime.INIT):
            return
        if worker is None:
            return
        self.calls = (self.calls + [time.monotonic()])[-20:]
        # A load is a handful of short host steps that each wait for one guest update: run them back to back
        # (bounded), so a slow watcher loop does not stretch a 2 s load over the whole countdown.
        deadline = time.monotonic() + STEP_BUDGET
        while True:
            try:
                self.kept = worker.kept() if hasattr(worker, 'kept') else 0
                if worker.job is not None:
                    job = worker.step(p)
                    if job is not None:
                        self.finished(p, job)
                if worker.job is None and worker.form_job is None:
                    self.assign(p, self.words(p), worker)
            except (OSError, ConnectionError):
                raise
            except Exception as error:  # noqa: BLE001 - a gauntlet load never holds or ends the match
                if type(error).__name__ == 'PineError':
                    raise
                # Nothing of a gauntlet load holds combat: drop this load (its fighter is retried or skipped)
                # and keep the match and the ordinary fighter updates running.
                job = worker.job
                if job is not None:
                    worker._fail(job, f'{type(error).__name__}: {error}')
                    self.finished(p, job)
                else:
                    self.note(f'Fighter Gauntlet: {type(error).__name__}: {error}')
                return
            if worker.job is None or time.monotonic() > deadline:
                return
            time.sleep(0.01)

    def report(self, p, state, w):
        count = w['waves']
        number = w['wave'] + 1
        if state == runtime.FIGHT and w['wave'] == 0 and self.last_state is None:
            self.note(tr(SAY_FIGHT, count=count))
        elif state == runtime.INTRO:
            self.note(tr(SAY_ENTERS, n=number, count=count))
        elif state == runtime.COUNTDOWN:
            self.note(tr(SAY_COUNTDOWN, n=number, count=count))
        elif state == runtime.WON:
            self.note(tr(SAY_CLEARED, count=count))
        elif state == runtime.LOST:
            self.note(tr(SAY_LOST, n=number, count=count))

    def upcoming(self, p, w):
        """(wave number, index, fighter) still to be loaded: the current wave's pending ones, then the next wave."""
        out = []
        ready = {}
        for physical in RECYCLED + (1,):
            s = self.slot(p, physical)
            if s['state'] in (runtime.READY, runtime.ACTIVE, runtime.KO) and s['wave']:
                ready[(s['wave'], s['index'])] = physical
        for physical, key in self.assigned.items():
            ready[key] = physical
        for key in self.delivered:
            ready.setdefault(key, None)
        current = w['wave'] + 1
        numbers = [current] if w['state'] in (runtime.FIGHT, runtime.INTRO) and w['pending'] else []
        if current < w['waves']:
            numbers.append(current + 1)
        for number in numbers:
            _, fighters = self.wave(p, number)
            for index, f in enumerate(fighters):
                key = (number, index)
                if key in ready or key in self.skipped:
                    continue
                out.append((number, index, f))
        return out

    def free_slot(self, p):
        for physical in RECYCLED:
            if physical in self.assigned:
                continue
            s = self.slot(p, physical)
            if s['state'] == runtime.VANISHED and p.read_u32(runtime.GATES + 4 * physical):
                return physical, s
        return None, None

    def sweep(self, p, worker):
        """Retire bundles kept for a hidden slot (a reference that blocked them may be gone now)."""
        retained = getattr(worker, 'retained', None)
        if not retained or not hasattr(worker, 'sweep'):
            return False
        now = time.monotonic()
        for physical in RECYCLED:
            if physical in self.assigned or not retained.get(physical) or self.sweeps.get(physical, 0) > now:
                continue
            s = self.slot(p, physical)
            if s['state'] == runtime.VANISHED and p.read_u32(runtime.GATES + 4 * physical):
                self.sweeps[physical] = now + SWEEP_SECONDS
                if worker.sweep(p, physical):
                    return True
        return False

    def assign(self, p, w, worker):
        if self.sweep(p, worker):
            return
        if time.monotonic() < self.retry_at:
            return
        todo = self.upcoming(p, w)
        if not todo:
            return
        number, index, f = todo[0]
        physical, s = self.free_slot(p)
        if physical is None:
            return
        character, costume = f[0], f[1]
        import fresh_team_combat as core
        actor = p.read_u32(core.POINTERS + 4 * physical)
        model = p.read_u32(core.MODELS + 4 * p.read_u32(actor + 12))
        slot_row = actor + 0x9A4 + 164 * p.read_u32(actor + 0x994)
        if p.read_u32(model + 12) == character and p.read_u32(slot_row + 4) == costume:
            self.ready(p, physical, number, index, f, 0.0)
            return
        if worker.recycle(p, physical, character, costume, tag=(number, index)):
            self.assigned[physical] = (number, index)

    def ready(self, p, physical, number, index, f, seconds):
        difficulty, _ = self.wave(p, number)
        row = runtime.SLOTS + runtime.SLOT_STRIDE * physical
        p.write(row + runtime.S['hp'], struct.pack('<4I', f[2], f[3], f[4], difficulty))
        p.write(row + runtime.S['wave'], struct.pack('<2I', number, index))
        p.write_u32(row + runtime.S['character'], f[0])
        p.write_u32(row + runtime.S['state'], runtime.READY)
        self.delivered.add((number, index))
        self.note(tr(SAY_LOADED, None, name=fighter_name(f[0]), slot=physical, seconds=seconds))

    def finished(self, p, job):
        physical = job['physical']
        key = self.assigned.pop(physical, job.get('tag'))
        if key is None:
            return
        number, index = key
        if job['phase'] == 'done':
            _, fighters = self.wave(p, number)
            self.ready(p, physical, number, index, fighters[index], job.get('seconds', 0.0))
            return
        self.failures[key] = self.failures.get(key, 0) + 1
        limit = LOAD_ATTEMPTS
        if 'status 130' in job.get('reason', '') and self.kept:
            # The resource records ran out while superseded bundles are still kept: wait for a sweep to free one.
            limit = RECORD_RETRIES; self.retry_at = time.monotonic() + 2.0; self.sweeps.clear()
        if self.failures[key] >= limit:
            self.skipped.add(key)
            _, fighters = self.wave(p, number)
            self.note(tr(SAY_LOAD_FAILED, None, name=fighter_name(fighters[index][0]), reason=job.get('reason', '?')))
            self.skip(p, number)

    def skip(self, p, number):
        """One fighter of wave `number` will never come: the guest's wave needs one fewer."""
        w = self.words(p)
        if w['wave'] + 1 == number and w['state'] in (runtime.FIGHT, runtime.INTRO):
            p.write_u32(runtime.CONTROL + runtime.C['pending'], max(0, w['pending'] - 1))
        else:
            row = runtime.WAVES + runtime.WAVE_HEADER + runtime.WAVE_STRIDE * (number - 1)
            p.write_u32(row, max(0, p.read_u32(row) - 1))
