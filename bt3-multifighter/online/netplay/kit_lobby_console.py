"""The console lobby (--no-gui, or when tkinter is missing: on Linux "sudo apt install python3-tk" gives the window)
and the lobby script driver both lobbies share (tests and bots). Kit 2.0.

Same state machine as the window: the session process does everything; this only shows its state and sends
commands. Commands:
  host | join ADDRESS | name TEXT | lang en|es | iso PATH | bios PATH | install PATH
  find NAME           fighters (id, name, colours)       stages     stage ids and names        show | help
  claim T [I]         play fighter I (1-based, default 1) of team T   spectate   give your slot up (watch)
  fighter T I C:K     team T fighter I (1-based) is character C, colour K (1-based): your own (host: any)
  ready | unready | chat TEXT | leave | leavematch (leave the running fight, stay in the room)
  host only:  start | cancel | end | mode teams|ffa | sizes A B | stage N|random | music N|random | random
              lock T I | unlock T I (nobody may claim that fighter) | kick NAME (remove a member from the room)
              rule time 60|90|180|240|inf | rule com 0..4 | rule referee 0..6 | rule destructible on|off
              rule mod KEY VALUE (a gameplay rule; the keys: show), rule service cpu_transform on|off
  retry | lobby       after a fight (Retry needs every player within 10 s)
  startin menu|hub    host: start the next match from the menu (versus) or in the hub
  loadpolicy cancel|drop   host: cancel on a failed load, or remove that player and continue with a CPU
  hub open on|off | hub challenge NAME duel|match | hub accept [NAME] | hub decline [NAME]   (in a running hub)
  hub join            (watching a running hub) play: take a free fighter (a parked one first, else a CPU bot)
  watch 0|1           spectators: the side you watch
  display KEY VALUE   your own display settings (kept on this PC only)
Bot options: --team "T [C:K]" (claim team T, then play C colour K), --auto-ready, --auto-vote retry|lobby[,N],
--lobby-script FILE (a JSON list of steps: {"wait": "EXPR", "timeout": S}, {"do": "COMMAND"}, {"sleep": S},
{"shot": "NAME"} (the window's picture; window lobby only), {"log": "TEXT"}, {"mark": "NAME"}).
"""
import json
import queue
import sys
import threading
import time
from pathlib import Path

import kit_text
from kit_text import t

TIMES = {'60': 60, '90': 90, '180': 180, '240': 240, 'inf': 0, '0': 0, '∞': 0}


def parse_fighter(text):
    c, _, k = text.partition(':')
    return int(c), int(k or '1') - 1


def command(text, state):
    """One command line -> (ipc command name, fields) or ('local', what) or None."""
    parts = text.strip().split(None, 1)
    if not parts:
        return None
    word, rest = parts[0].lower(), (parts[1] if len(parts) > 1 else '').strip()
    lob = (state or {}).get('lobby') or {}
    match = lob.get('match') or {}
    if word == 'host':
        return 'host', {}
    if word == 'join':
        return 'join', dict(address=rest)
    if word == 'name':
        return ('name', dict(name=rest)) if lob else ('setup', dict(name=rest))
    if word == 'lang':
        return 'setup', dict(lang=rest if rest in ('en', 'es') else 'en')
    if word in ('iso', 'bios', 'install'):
        return 'setup', {word: rest}
    if word == 'claim':
        team, _, index = rest.partition(' ')
        return 'claim', dict(team=int(team) - 1, index=int(index or '1') - 1)
    if word in ('lock', 'unlock'):
        team, index = rest.split()
        return 'lock', dict(team=int(team) - 1, index=int(index) - 1, locked=word == 'lock')
    if word == 'kick':
        members = {m['name'].lower(): m['id'] for m in lob.get('members') or []}
        target = members.get(rest.strip().lower())
        if target is None:
            return 'local', f'nobody called {rest} is in the room'
        return 'kick', dict(member=target)
    if word in ('spectate', 'unclaim'):
        return 'unclaim', {}
    if word == 'fighter':
        team, index, who = rest.split()
        c, k = parse_fighter(who)
        return 'fighter', dict(team=int(team) - 1, index=int(index) - 1, character=c, costume=k)
    if word == 'ready':
        return 'ready', dict(ready=True)
    if word == 'unready':
        return 'ready', dict(ready=False)
    if word == 'chat':
        return 'chat', dict(text=rest)
    if word == 'start':
        return 'start', {}
    if word == 'mode':
        return 'mode', dict(mode=rest.lower())
    if word == 'startin':
        return 'start_in', dict(value='hub' if rest.lower() == 'hub' else 'versus')
    if word == 'loadpolicy':
        if rest.lower() not in ('cancel', 'drop'):
            return 'local', 'loadpolicy cancel|drop'
        return 'load_policy', dict(drop=rest.lower() == 'drop')
    if word == 'hub':
        sub, _, arg = rest.partition(' ')
        sub = sub.lower()
        members = {m['name'].lower(): m['id'] for m in lob.get('members') or []}
        if sub == 'join':
            return 'hub_join', {}
        if sub == 'open':
            return 'hub_open', dict(on=arg.strip().lower() in ('on', '1', 'yes', ''))
        if sub == 'challenge':
            name, _, kind = arg.strip().rpartition(' ')
            if not name:
                name, kind = kind, 'duel'
            target = members.get(name.strip().lower())
            if target is None:
                return 'local', f'nobody called {name} is in the room'
            return 'hub_challenge', dict(target=target, kind='match' if kind.lower() == 'match' else 'duel')
        if sub in ('accept', 'decline'):
            by = members.get(arg.strip().lower())
            if by is None:
                pending = [c['by'] for c in ((lob.get('hub') or {}).get('challenges') or [])
                           if c.get('target') == (state or {}).get('me')]
                by = pending[0] if pending else None
            if by is None:
                return 'local', 'no challenge to answer'
            return 'hub_answer', dict(challenger=by, accept=sub == 'accept')
    if word == 'backhub':
        return 'back_to_hub', {}
    if word == 'sizes':
        a, b = rest.split()
        return 'sizes', dict(sizes=[int(a), int(b)])
    if word == 'stage':
        return 'rules', dict(stage='random' if rest.lower() == 'random' else int(rest))
    if word == 'music':
        return 'rules', dict(bgm='random' if rest.lower() == 'random' else int(rest) - 1)
    if word == 'random':
        return 'random', {}
    if word == 'rule':
        key, _, value = rest.partition(' ')
        value = value.strip().lower()
        native = dict(match.get('native') or {})
        if key == 'time':
            native['time'] = TIMES.get(value, 240)
        elif key == 'com':
            native['com'] = int(value)
        elif key == 'referee':
            native['referee'] = int(value)
        elif key == 'destructible':
            native['destructible'] = value in ('on', '1', 'true', 'yes')
        elif key == 'mod':
            name, _, raw = value.partition(' ')
            return 'rules', dict(gameplay={name: raw.strip()})
        elif key == 'service':
            name, _, raw = value.partition(' ')
            return 'rules', dict(services={name: raw.strip() in ('on', '1', 'true', 'yes')})
        else:
            return 'local', f'unknown rule {key}'
        return 'rules', dict(native=native)
    if word in ('retry', 'lobby') and (state or {}).get('phase') == 'results':
        return 'vote', dict(choice=word)
    if word == 'leave':
        return 'leave', {}
    if word == 'leavematch':
        return 'leave_match', {}
    if word == 'end':
        return 'end_fight', {}
    if word == 'cancel':
        return 'cancel_prep', {}
    if word == 'watch':
        return 'watch', dict(side=int(rest))
    if word == 'display':
        key, _, value = rest.partition(' ')
        return 'local', ('local_display', key, value.strip())
    if word == 'quit':
        return 'quit', {}
    if word == 'dismiss':
        return 'dismiss', {}
    if word == 'test':
        sub, _, arg = rest.partition(' ')
        if sub == 'key':
            name, _, hold = arg.strip().partition(' ')
            return 'test_key', dict(key=name or 'cross', hold=float(hold) if hold else 0.12)
        if sub == 'peek':
            return 'test_peek', {}
        if sub == 'inject':
            return 'test_inject', dict(what=arg.strip() or 'hp')
        if sub == 'shot':
            return 'test_shot', dict(name=arg.strip() or 'shot')
        if sub == 'gshot':
            return 'test_gshot', dict(name=arg.strip() or 'game')
        if sub == 'bots':
            return 'bots', dict(on=arg.strip() != 'off')
        if sub == 'prep':
            return 'test_prep', dict(ko='ko' in arg.split(), leaders='leaders' in arg.split(), ki='ki' in arg.split())
    if word in ('find', 'stages', 'show', 'help'):
        return 'local', text.strip()
    return 'local', f'unknown command {word}'


def resolve(parsed):
    """('local_display', key, value) -> the local display command."""
    if parsed and parsed[0] == 'local' and isinstance(parsed[1], tuple) and parsed[1][0] == 'local_display':
        return 'local', dict(values={parsed[1][1]: parsed[1][2]})
    return parsed


# ---- the script driver ------------------------------------------------------------------------------------------------
SCRIPT_BUILTINS = {'len': len, 'any': any, 'all': all, 'min': min, 'max': max, 'sorted': sorted}


class Namespace(dict):
    def __missing__(self, key):
        return SCRIPT_BUILTINS.get(key)

    def __getattr__(self, key):                      # the bots read facts as attributes (f.phase)
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key) from None


def slot_of(match, ident):
    for t_, team in enumerate((match or {}).get('teams') or []):
        for i, f in enumerate(team):
            if f.get('owner') == ident:
                return t_, i
    return None


def facts(state):
    """What a script's "wait" expression can read."""
    s = state or {}
    lob = s.get('lobby') or {}
    match = lob.get('match') or {}
    members = {m['id']: m for m in lob.get('members') or []}
    me_id = s.get('me')
    me = members.get(me_id) or {}
    players = [k for k in members if slot_of(match, k) is not None]
    res = s.get('results') or {}
    st = s.get('status') or {}
    vote = s.get('vote') or {}
    return Namespace(phase=s.get('phase'), role=s.get('role'), lobby=lob, me=me, me_id=me_id, members=members,
                     count=len(members), players=players, spectators=[k for k in members if k not in players],
                     my_slot=slot_of(match, me_id), ready_me=bool(me.get('ready')),
                     all_ready=all(members[k].get('ready') for k in players if k != 1),
                     match=match, lobby_phase=lob.get('phase'), rev=lob.get('rev'), results=res, how=res.get('how'),
                     vote=vote, decision=vote.get('decision'), agreed=vote.get('agreed') or [],
                     status=st, frame=st.get('frame'), resyncing=st.get('resyncing'), error=s.get('error'),
                     overlay=s.get('overlay'), notice=s.get('notice'), state=s, warm=(lob.get('warm') or {}).get('state'),
                     progress=s.get('progress') or {}, step=(s.get('progress') or {}).get('step'),
                     match_view=s.get('match') or {}, peek=s.get('peek') or {},
                     chat_last=((s.get('chat_last') or {}).get('text')), chat_count=s.get('chat_count') or 0)


class Script:
    """Runs lobby steps against the live state: wait (a Python expression over facts()), do (a console command),
    sleep, shot (the UI's own capture function), log, mark. Test and bot use only."""

    def __init__(self, steps, send, shot=None, log=print, out=None, ui=None, local=None):
        self.steps, self.send, self.shot, self.log, self.ui = list(steps), send, shot, log, ui
        self.local = local
        self.i, self.state, self.since = 0, {}, time.time()
        self.done, self.failed = False, None
        self.out = out
        self.marks = []

    def feed(self, state):
        self.state = state

    def tick(self):
        while not self.done and self.i < len(self.steps):
            step = self.steps[self.i]
            if 'wait' in step:
                try:
                    names = facts(self.state)                   # globals too: a generator inside sees them
                    ok = bool(eval(step['wait'], dict(names, __builtins__=dict(SCRIPT_BUILTINS)), names))
                except Exception:  # noqa: BLE001 - not yet evaluable
                    ok = False
                if not ok:
                    if time.time() - self.since > step.get('timeout', 600):
                        if step.get('optional'):
                            self.log(f'SCRIPT step {self.i}: optional wait timed out: {step["wait"]}')
                            self.mark('optional_timeout', wait=step['wait'])
                        else:
                            self.failed = f'step {self.i}: timed out waiting for {step["wait"]}'
                            self.log('SCRIPT ' + self.failed)
                            self.done = True
                            self.mark('failed', reason=self.failed)
                            return
                    else:
                        return
            elif 'sleep' in step:
                if time.time() - self.since < step['sleep']:
                    return
            elif 'do' in step:
                parsed = resolve(command(step['do'], self.state))
                self.log(f'SCRIPT do: {step["do"]}')
                if parsed and parsed[0] != 'local':
                    self.send(parsed[0], **parsed[1])
                elif parsed and isinstance(parsed[1], dict):
                    self.send('local', **parsed[1])
                elif parsed and self.local:
                    self.local(parsed[1])
            elif 'cmd' in step:
                self.send(step['cmd'], **step.get('args', {}))
            elif 'shot' in step:
                if self.shot:
                    path = self.shot(step['shot'])
                    self.log(f'SCRIPT shot: {path}')
            elif 'log' in step:
                self.log('SCRIPT ' + step['log'])
            elif 'ui' in step:
                if self.ui:
                    try:
                        self.ui(step)
                    except Exception as error:  # noqa: BLE001 - reported in the log
                        self.log(f'SCRIPT ui step failed: {error!r}')
            elif 'mark' in step:
                self.mark(step['mark'])
            self.i += 1
            self.since = time.time()
            if 'mark' not in step:
                self.mark(f'step{self.i}')
        if self.i >= len(self.steps) and not self.done:
            self.done = True
            self.mark('done')

    def mark(self, name, **extra):
        row = dict(name=name, step=self.i, t=round(time.time(), 2), phase=self.state.get('phase'), **extra)
        self.marks.append(row)
        if self.out:
            try:
                Path(self.out).write_text(json.dumps(dict(marks=self.marks, failed=self.failed, done=self.done),
                                                     indent=1), encoding='utf-8')
            except OSError:
                pass


def bot_steps(args):
    """--team "T [C:K]" as script steps: wait for the lobby, claim team T, choose the fighter."""
    steps = []
    if args.team:
        parts = args.team.split()
        steps += [{'wait': "phase == 'lobby' and lobby.get('rev', -1) >= 0 and me_id is not None", 'timeout': 3600},
                  {'do': f'claim {parts[0]}'}]
        if len(parts) > 1:
            team, _, index = parts[0].partition('.')
            steps += [{'wait': 'my_slot is not None', 'timeout': 60},
                      {'do': f'fighter {team} {index or 1} {parts[1]}'}]
    return steps


class AutoBot:
    """--auto-ready and --auto-vote: react to the state each tick."""

    def __init__(self, args, send):
        self.ready = args.auto_ready
        vote = (args.auto_vote or '').split(',')
        self.vote = vote[0] or None
        self.fights = int(vote[1]) if len(vote) > 1 and vote[1] else None
        self.voted_epoch = None
        self.send = send
        self.count = 0
        self.last_ready = 0.0

    def tick(self, state):
        f = facts(state)
        if self.ready and f.phase == 'lobby' and f.lobby_phase == 'lobby' and f.my_slot is not None and \
                not f.ready_me and f.role == 'guest' and time.time() - self.last_ready > 1.0:
            self.last_ready = time.time()
            self.send('ready', ready=True)
        epoch = (f.vote or {}).get('epoch')
        if self.vote and f.phase == 'results' and epoch is not None and self.voted_epoch != epoch and \
                f.my_slot is not None:
            self.voted_epoch = epoch
            self.count += 1
            choice = self.vote if self.fights is None or self.count < self.fights else 'lobby'
            self.send('vote', choice=choice)


# ---- the console UI -----------------------------------------------------------------------------------------------------
class Console:
    def __init__(self, client, args, restart=None):
        self.client, self.args = client, args
        self.state = {}
        self.lang = args.lang or 'en'
        self.catalog = None
        self.lines = queue.Queue()
        self.last_phase = None
        self.last_rev = None

    def say(self, text):
        print(text, flush=True)

    def send(self, cmd, **fields):
        self.client.send(cmd, **fields)

    def read_stdin(self):
        while True:
            try:
                line = sys.stdin.readline()
            except (OSError, ValueError):
                return
            if not line:
                return
            self.lines.put(line)

    def view(self):
        import kit_catalog
        cat = (self.state or {}).get('catalog')
        if cat and (self.catalog is None or self.catalog.c.get('dir') != cat['dir']):
            self.catalog = kit_catalog.View(kit_catalog.read_dir(cat['dir']))
        return self.catalog

    def local(self, text):
        word, _, rest = text.partition(' ')
        v = self.view()
        if word == 'help':
            self.say(__doc__.split('Commands:', 1)[1].split('Bot options')[0])
        elif word == 'find' and v:
            for c in v.find(rest):
                self.say(f'  {c["id"]:3d}  {c["name"]}  (colours 1-{c["costumes"]})')
        elif word == 'stages' and v:
            for sid in v.stage_order():
                self.say(f'  {sid:2d}  {v.stages[sid]["name"]}')
        elif word == 'show':
            self.show_lobby(force=True)
        else:
            self.say(text)

    def show_lobby(self, force=False):
        import kit_settings
        lob = self.state.get('lobby')
        if not lob or (not force and lob.get('rev') == self.last_rev):
            return
        self.last_rev = lob.get('rev')
        v = self.view()
        name = (lambda c: v.name(c)) if v else str
        m = lob['match']
        n = m['native']
        stage = 'Random' if m['stage'] == 'random' else (v.stage_name(m['stage']) if v else m['stage'])
        music = 'Random' if m['bgm'] == 'random' else m['bgm'] + 1
        self.say(f'-- lobby rev {lob["rev"]} ({lob.get("phase")}): {m["mode"]}, stage {stage}, music {music}, time '
                 f'{kit_text.TIME_LABELS.get(n["time"], n["time"])}, CPU {kit_text.COM_LABELS[n["com"]]}, referee '
                 f'{kit_text.REFEREES[self.lang][n["referee"]]}, destructible {"ON" if n["destructible"] else "OFF"}')
        members = {x['id']: x for x in lob.get('members') or []}
        for t_, team in enumerate(m['teams']):
            row = []
            for i, f in enumerate(team):
                owner = members.get(f.get('owner'), {}).get('name')
                row.append(f'{name(f["character"])} ({f["costume"] + 1})' + (f' [{owner}]' if owner else ' [CPU]'))
            self.say(f'   team {t_ + 1}: ' + ', '.join(row))
        for k, x in sorted(members.items()):
            role = 'player' if slot_of(m, k) is not None else 'watching'
            self.say(f'   {x["name"]}{" (host)" if k == 1 else ""}: {role}{" READY" if x.get("ready") else ""}'
                     + ('' if x.get('rtt_ms') is None else f' {x["rtt_ms"]} ms'))
        if force:
            self.say('   ' + t('room.load_policy', self.lang) + ': ' + t(
                'room.load_drop' if (lob.get('room') or {}).get('drop_load_failures') is True else
                'room.load_cancel', self.lang))
            values = kit_settings.gameplay_expand(m.get('gameplay'))
            for group, keys in kit_settings.groups():
                self.say(f'   {kit_settings.group_label(group, self.lang)}: ' +
                         ', '.join(f'{k}={kit_settings.value_text(k, values[k], self.lang)}' for k in keys))
            self.say(f'   {kit_text.t("room.camera", self.lang)}: ' +
                     ', '.join(f'{k}={kit_settings.value_text(k, values[k], self.lang)}' for k in kit_settings.CAMERA))
        notice = lob.get('notice')
        if notice and notice.get('key'):
            args = dict(notice.get('args') or {})
            self.say('   ' + kit_text.notice_text(notice['key'], self.lang, args))

    def on_state(self, state):
        self.state = state
        self.lang = state.get('lang') or self.lang
        if state.get('phase') != self.last_phase:
            self.last_phase = state.get('phase')
            self.say(f'== {state.get("phase")}')
            jw = state.get('joinwith') or {}
            if state.get('phase') == 'lobby' and jw.get('main'):
                addr = jw['main'] + ('' if jw.get('default_port') else f':{jw.get("port")}')
                self.say('   ' + t('lobby.joinwith', self.lang, addr=addr))
        if state.get('phase') in ('lobby', 'results'):
            self.show_lobby()
        vote = state.get('vote')
        if state.get('phase') == 'results' and vote and vote != getattr(self, 'last_vote', None):
            self.last_vote = vote
            self.say(f'   vote: {vote.get("left_s")} s left, agreed {vote.get("agreed")} of {vote.get("players")}'
                     f'{"" if not vote.get("decision") else " -> " + vote["decision"]}')
        err = state.get('error')
        if err and err != getattr(self, 'last_error', None):
            self.last_error = err
            self.say(err.get(self.lang) or err.get('en'))

    def run(self):
        threading.Thread(target=self.read_stdin, daemon=True).start()
        steps = []
        if self.args.lobby_script:
            steps = json.loads(Path(self.args.lobby_script).read_text(encoding='utf-8'))
        steps = bot_steps(self.args) + steps
        script = Script(steps, self.send, None, self.say,
                        out=Path(self.args.shot_dir) / 'script.json' if self.args.shot_dir else None,
                        local=self.local) if steps else None
        bot = AutoBot(self.args, self.send) if (self.args.auto_ready or self.args.auto_vote) else None
        import kit_ident
        self.say(t('kit', self.lang, version=kit_ident.KIT_VERSION) + ' (console lobby; type help)')
        while True:
            for ev in self.client.poll(0.05):
                kind = ev.get('ev')
                if kind in ('state', 'snapshot'):
                    self.on_state(ev['state'])
                    if script:
                        script.feed(ev['state'])
                elif kind == 'log':
                    self.say('   ' + ev.get('text', ''))
                elif kind == 'chat':
                    self.say(f'   [{ev.get("who")}] {ev.get("text")}')
                elif kind in ('bye', 'replaced'):
                    return 0
            if self.client.closed:
                self.say(t('session.lost', self.lang))
                return 1
            if script:
                script.tick()
            if bot:
                bot.tick(self.state)
            while not self.lines.empty():
                text = self.lines.get().strip()
                parsed = resolve(command(text, self.state))
                if not parsed:
                    continue
                if parsed[0] == 'local' and isinstance(parsed[1], dict):
                    self.send('local', **parsed[1])
                elif parsed[0] == 'local':
                    self.local(parsed[1])
                else:
                    self.send(parsed[0], **parsed[1])
                    if parsed[0] == 'quit':
                        return 0


def run(client, args, session_pid=None, restart=None):
    return Console(client, args, restart).run()
