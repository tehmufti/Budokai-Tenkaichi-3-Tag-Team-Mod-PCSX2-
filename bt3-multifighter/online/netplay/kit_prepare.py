"""The host's private installation copy (kit 2.0) and the conversion of its match into an online match.

The copy (Prepare): a PRIVATE COPY of the host's Tag Team Mod installation in prep/Tag Team Mod (the installation
itself is only read); only its PINE port changes, so it never meets another PCSX2. kit_prepare_auto drives it on a
hidden desktop and builds the lobby's match in it with nobody at its menus; its mod-settings.json is written
COMPLETE for each match (kit_settings.match_settings), so the host's offline settings never reach an online match.

The capture: the mod's own PLAYABLE CHECKPOINT of the match (fresh_team_trainer.export_playable: the prepared match
held just before its start, every fighter effect and the terrain placement ready, its start request already set and
the mod's loading cover and preparation gate cleared, so it plays WITHOUT the mod's watcher). The watcher names it
in its log ('Rematch checkpoint: ...'). It is taken before the intro: online matches play the whole intro.

The conversion (_convert, run by the installation copy's Python: the mod modules need numpy / Pillow / zstandard):
  (0) the installation's guest code is an accepted build (data/guest-fingerprint.json: Tag Team Mod beta.35..42, by
      build family), else TTM-NET-24; the family names the runtime pnach both PCs install for this match;
  (a) the single view (a 2-player split save is converted), the checkpoint's state checked (held start, start request
      set, no loading cover, no preparation hold, the selected-resource queue idle);
  (b) the pause menu is closed: the pause controller's port count (GP + GPO(-20648)) := 0 (no player can open it; the fight's
      Start does nothing else);
  (c) every fighter is human or CPU as the lobby says (the start gate's table, CONTROL+0x40+4i; kit 2.1: any fighter
      can be a player, slot = physical index);
  (d) spectator / takeover ports for the side leaders' players (+52 / +56);
  (e) both leaders and every human fighter may transform (actor+0x1300 := 1);
  (e2) kit 2.1: a human extra may use its special moves (extra_specials CONTROL+20, the co-op admission bits) and the
      lock-on queue resolves every human's pad through the pad resolver (lockon_queue's pad_resolver variant, as the
      mod's four-player matches install it), which netplay_core's RESOLVE then answers per slot;
  (f) netplay_fixups: each window draws its own player's takeover offer;
  (g) the fighter-update hooks of extra fighters stay dormant (no watcher online): their four enable words := 0;
  (h) the controller hub's P1/P2 override disarmed (controller_assignment +12 := 0, PASS := 3): nothing feeds it
      online;
  (i) netplay_core layout 3 + netplay_view (kit_match.build_netplay) with the players' slot mask;
  (j) kit_verify reads the finished match back and checks it against the lobby spec (TTM-NET-31 when it differs).
"""
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

import kit_paths
from native_map import A, GP, GPO
import kit_win
from kit_codes import KitError

SAVE_SLOT = 250
HUB_SETTINGS = dict(respawn_seconds=3.0, grace_seconds=2.0, decay_seconds=20.0, consent=True, respawn=True,
                    board=True)               # (h) hub_mode.config: the kit's hub (match type 'hub')
PAUSE_COUNT = (GP + GPO(-20648))                       # (GP + GPO(-20648)): the fight's pause controller port count (USA)
SPECTATOR, PORTS, HUMAN_PORTS = 0x0728F000, 52, 56
DORMANT = (('extra_reload_forms CONTROL', 0x0766F000), ('extra_reload_requests FORM_ENABLE', 0x0764F018),
           ('extra_reload_requests CONTROL', 0x0764F000), ('extra_cell_absorption AUX_CONTROL', 0x0766E000))
ASSIGNMENT, ASSIGNMENT_MAGIC, ASSIGNMENT_ARMED, ASSIGNMENT_PASS = 0x06933000, 0x43415331, 12, 0x30
BG_CONTROL, BG_MAGIC = 0x0765E000, 0x424B4731  # extra_reload_quiet BG_CONTROL: the unheld IO driver (off online)
HP_ROW, HP_SLOT, HP_STRIDE = 0x9E4, 0x994, 0xA4
FOREIGN = ('        try { $own = [bool]($path -and $wanted -and [string]::Equals([System.IO.Path]::GetFullPath($path), $wanted, '
           '[System.StringComparison]::OrdinalIgnoreCase)) } catch { }\n')
# Copy exclusions (relative to the installation root): logs, the player's own saved-match library, savestates.
SKIP_DIRS = {('game', 'analysis', 'autopilot'), ('game', 'analysis', 'prepared-states'), ('game', 'analysis', 'settings'),
             ('game', 'runtime28', 'sstates'), ('game', 'runtime28', 'snaps'), ('game', 'runtime28', 'logs'),
             ('game', 'runtime28', 'cache'), ('game', 'runtime28', 'videos'), ('game', 'runtime28', 'covers')}
# USA addresses the copy is watched by (p23 fixture capture's words, live-checked there).
BATTLE, RESULT, MODE, SCENE_SPLIT = A(0x2FEB38), A(0x333700), 0xD8080, A(0x331DC8) + 36
PREP, WORKER, AUX = 0x0768F000, 0x0766F000, 0x0766E000
NEEDED = ('numpy', 'PIL', 'zstandard')
CHECKPOINT_LINE = re.compile(r'Rematch checkpoint: (.+?\.p2s)\s*$')


def patches(slot):
    import kit_paths
    original_slot = 28012 if kit_paths.ADAPTER.startswith('bt4') else 28011
    changes = {
        'game/launch-autopilot.ps1': [
            ('$pineSlot = 28011', f'$pineSlot = {slot}'),
            ("if (@(Get-Process -Name 'pcsx2*' -ErrorAction SilentlyContinue).Count) {",
             "if (@(Get-Process -Name 'pcsx2*' -ErrorAction SilentlyContinue | Where-Object { $_.Path -ieq "
             "$emulatorPath }).Count) {")],
        'game/launcher-lifecycle.ps1': [(FOREIGN, FOREIGN + '        if (-not $own) { continue }   # TTM Online Kit '
                                                            'private copy\n')],
        'game/tools/pine.py': [('def __init__(self, port=28011,', f'def __init__(self, port={slot},')],
        'game/tools/play_launcher.py': [('PINE_SLOT = 28011', f'PINE_SLOT = {slot}')],
    }
    if kit_paths.ADAPTER.startswith('bt4'):
        changes['game/tools/bt4_preflight.py'] = [("PINE_SLOT='28012'", f"PINE_SLOT='{slot}'")]
    return {path: [(old.replace('28011', str(original_slot)), new) for old, new in rows]
            for path, rows in changes.items()}


def ini_set(text, keys):
    import kit_emu
    return kit_emu.ini_set(text, keys)


class Prepare:
    def __init__(self, run):
        self.run, self.args, self.say = run, run.args, run.say
        self.slot = self.args.prep_pine_slot or self.args.pine_slot + 1
        self.dest = kit_paths.PREP / 'Tag Team Mod'
        self.orig = kit_paths.PREP / 'orig'
        self.pid = self.cmd_pid = None
        self.desktop = f'ttm-kit-prep-{self.slot}' if self.args.hidden else None

    # ---- 1. the private copy --------------------------------------------------------------------------------------
    def copy_installation(self):
        install = self.run.install
        if not install:
            raise KitError('TTM-NET-23', what='Making a match needs your Tag Team Mod installation (beta.35 to '
                                              'beta.42).',
                           fix='Start it with --install "C:\\...\\Tag Team Mod" (the folder with Play.cmd); the kit '
                               'only reads it and remembers it.')
        source = Path(install['root'])
        record = kit_paths.PREP / 'copy.json'
        stamp = dict(source=str(source), version=install['version'])
        fresh = not (self.dest / 'Play.cmd').is_file()
        try:
            if json.loads(record.read_text(encoding='utf-8')) != stamp:
                fresh = True
        except (OSError, ValueError):
            fresh = True
        if fresh and self.dest.exists():
            shutil.rmtree(self.dest)                                   # the kit's own earlier copy (prep/ only)
            shutil.rmtree(self.orig, ignore_errors=True)
        self.say(('Making a private copy of your Tag Team Mod installation (one time, a few hundred MB)...' if fresh
                  else 'Refreshing the private copy of your Tag Team Mod installation...'))
        copied = 0
        for folder, dirs, files in os.walk(source):
            rel = Path(folder).relative_to(source)
            dirs[:] = [d for d in dirs if tuple((rel / d).parts) not in SKIP_DIRS and d != '__pycache__' and
                       not (rel == Path('.') and d == 'online')]   # kit 2.1: never the online part (prep/ is in it)
            target_dir = self.dest / rel
            target_dir.mkdir(parents=True, exist_ok=True)
            for name in files:
                s, t = Path(folder) / name, target_dir / name
                try:
                    st = s.stat()
                    if t.exists() and t.stat().st_size == st.st_size and int(t.stat().st_mtime) == int(st.st_mtime):
                        continue
                    shutil.copy2(s, t)
                    copied += 1
                except OSError as error:
                    raise KitError('TTM-NET-23', what=f'Could not copy {s}: {error}',
                                   fix='Check the free disk space and that the installation is complete.') from None
        record.write_text(json.dumps(stamp), encoding='utf-8')
        self.say(f'  private copy ready: {self.dest} ({copied} files copied)')

    # ---- the copy's patches and settings --------------------------------------------------------------------------
    def patch(self):
        for rel, edits in patches(self.slot).items():
            original = self.orig / rel
            target = self.dest / rel
            if not original.exists():
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(target, original)
            data = original.read_bytes()
            nl = b'\r\n' if b'\r\n' in data else b'\n'
            for old, new in edits:
                old_b, new_b = old.encode().replace(b'\n', nl), new.encode().replace(b'\n', nl)
                if data.count(old_b) != 1:
                    raise KitError('TTM-NET-24', what=f'{rel} of the installation is not a file the kit knows '
                                                      f'(cannot change its PINE port safely).')
                data = data.replace(old_b, new_b)
            target.write_bytes(data)
        ini = self.dest / 'game' / 'runtime28' / 'inis' / 'PCSX2.ini'
        original = self.orig / 'game' / 'runtime28' / 'inis' / 'PCSX2.ini'
        if not original.exists():
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ini, original)
        keys = [('UI', 'ConfirmShutdown', 'false'), ('EmuCore', 'EnablePINE', 'true'),
                ('EmuCore', 'PINESlot', str(self.slot))]
        if self.args.hidden:                                           # test mode: keyboard pads, no sound, F8
            import kit_emu
            pad2 = {'cross': '1', 'circle': '2', 'square': '3', 'triangle': '4', 'start': '5', 'select': '6',
                    'up': '7', 'down': '8', 'left': '9', 'right': '0', 'l1': 'M', 'r1': 'N'}
            keys += [('SPU2/Output', 'Backend', 'Null'), ('InputSources', 'SDL', 'false'),
                     ('Hotkeys', 'Screenshot', 'Keyboard/F8')]
            keys += [('Pad1', kit_emu.PAD_NAMES[k], 'Keyboard/' + v[3]) for k, v in kit_emu.PAD1_KEYS.items()]
            keys += [('Pad2', kit_emu.PAD_NAMES[k], 'Keyboard/' + v) for k, v in pad2.items()]
        text = original.read_bytes().decode('utf-8-sig', errors='replace')
        ini.write_bytes(ini_set(text, keys).encode('utf-8'))

    def python(self):
        return self.dest / '.venv' / 'Scripts' / 'python.exe'

    def copy_python(self, *args, timeout=300):
        env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME', 'TAGTEAM_DISC',
                                                                 'TAGTEAM_ADAPTER', 'REVIEW_TOOLS')}
        env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONNOUSERSITE='1')
        r = subprocess.run([str(self.python()), '-B', *[str(a) for a in args]], cwd=str(self.dest / 'game'), env=env,
                           capture_output=True, text=True, timeout=timeout, creationflags=kit_win.CREATE_NO_WINDOW)
        return r.returncode, r.stdout, r.stderr

    # ---- the copy's PCSX2 --------------------------------------------------------------------------------
    def launch(self):
        owner = kit_win.listener_pid(self.slot)
        if owner is not None:
            raise KitError('TTM-NET-23', what=f'PINE port {self.slot} (for the match preparation) is used by process '
                                              f'{owner}.', fix='Close that program, or use --prep-pine-slot N.')
        play = self.dest / 'Play.cmd'
        console = self.run.run_dir / 'prepare-play.console.txt'
        env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME', 'REVIEW_TOOLS')}
        if self.desktop:
            self.cmd_pid = kit_win.launch(['cmd.exe', '/d', '/c', str(play)], self.dest, console, self.desktop,
                                          env=dict(env, PYTHONUTF8='1', PYTHONIOENCODING='utf-8'))
            kit_win.kill_with_me(self.cmd_pid)
        else:
            self.cmd_pid = subprocess.Popen(['cmd.exe', '/d', '/c', str(play)], cwd=str(self.dest), env=env,
                                            creationflags=0x00000010).pid       # CREATE_NEW_CONSOLE: the Play window
        exe = str(self.dest / 'game' / 'runtime28' / 'pcsx2-qt.exe').lower()
        end = time.time() + 300
        while time.time() < end:
            owner = kit_win.listener_pid(self.slot)
            if owner and kit_win.process_path(owner).lower() == exe:
                self.pid = owner
                kit_win.kill_with_me(owner)
                return owner
            if not kit_win.pid_alive(self.cmd_pid):
                raise KitError('TTM-NET-23', what='The mod\'s Play ended before PCSX2 started (see its window or '
                                                  f'{console}).', fix='Fix what the Play window reported, then try '
                                                                      'again.')
            time.sleep(0.5)
        raise KitError('TTM-NET-23', what='PCSX2 of the mod\'s Play did not start within 5 minutes.',
                       fix='Close the Play window and try again.')

    def watcher_state(self):
        folder = self.dest / 'game' / 'analysis' / 'autopilot'
        try:
            runs = sorted((p for p in folder.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime)
            return json.loads((runs[-1] / 'status.json').read_text(encoding='utf-8')).get('state') if runs else None
        except (OSError, ValueError):
            return None

    def sample(self):
        import pine
        with pine.PineClient(port=self.slot, timeout=3) as p:
            u = lambda a: struct.unpack('<I', p.read(a, 4))[0]
            battle = u(BATTLE)
            director = u(battle) if 0x100000 <= battle < 0x7FFFE00 else None
            words = struct.unpack('<16I', p.read(PREP, 64))
            return dict(director=director, result=u(RESULT) & 0x1F, mode=u(MODE), fighters=u(MODE + 4),
                        split=u(SCENE_SPLIT), prep_magic=words[0], hold=words[4], armed=words[12], worker=u(WORKER),
                        aux=u(AUX), clock=u(battle + 264) if director is not None else None)

    def save(self):
        import pine
        sstates = self.dest / 'game' / 'runtime28' / 'sstates'
        path = sstates / __import__('kit_adapter').state_name(SAVE_SLOT)
        before = path.stat().st_mtime if path.exists() else None
        for attempt in range(20):
            try:
                with pine.PineClient(port=self.slot, timeout=30) as p:
                    p.save_state(SAVE_SLOT)
                break
            except Exception:  # noqa: BLE001 - the watcher holds PINE for a moment
                time.sleep(0.2)
        else:
            raise KitError('TTM-NET-23', what='PCSX2 did not accept the save request.', fix='Try --prepare again.')
        end = time.time() + 120
        while time.time() < end:
            time.sleep(0.5)
            if path.exists() and path.stat().st_mtime != before and time.time() - path.stat().st_mtime > 1.5:
                return path
        raise KitError('TTM-NET-23', what='PCSX2 did not write the match save.', fix='Try --prepare again.')

    def close(self):
        for pid in (self.pid, self.cmd_pid):
            if pid:
                kit_win.kill_tree(pid)


def have_packages():
    import importlib.util
    return all(importlib.util.find_spec(n) is not None for n in NEEDED)


def convert(capture, folder, names_file, python=None, say=print, spec=None, options=None):
    """capture.p2s -> base.p2s (single view, opposing leader human, the online writes) -> netplay.p2s; returns the
    report. spec: the lobby spec the match must hold (checked, TTM-NET-31); options: {'test_ko': True} (test hooks
    only: Team 2 starts at 1 HP so bots reach a KO quickly)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    spec_path = options_path = None
    if spec is not None:
        spec_path = folder / 'spec.json'
        spec_path.write_text(json.dumps(spec, sort_keys=True, indent=1), encoding='utf-8')
    if options:
        options_path = folder / 'options.json'
        options_path.write_text(json.dumps(options), encoding='utf-8')
    if not have_packages():
        if not python or not Path(python).is_file():
            raise KitError('TTM-NET-23', what='Preparing a match needs the Tag Team Mod installation\'s Python '
                                              '(numpy, Pillow, zstandard).',
                           fix='Choose your Tag Team Mod folder in Start > Tag Team Mod folder.')
        env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME', 'REVIEW_TOOLS')}
        env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONNOUSERSITE='1')
        if os.environ.get('TTM_KIT_TEST_GUARD'):
            env['PYTHONPATH'] = os.environ['TTM_KIT_TEST_GUARD']
        r = subprocess.run([str(python), str(Path(__file__)), 'convert', str(capture), str(folder), str(names_file),
                            str(spec_path or '-'), str(options_path or '-')],
                           capture_output=True, text=True, env=env, creationflags=kit_win.CREATE_NO_WINDOW)
        try:
            out = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            out = dict(error=(r.stderr or r.stdout).strip()[-600:] or f'exit {r.returncode}')
    else:
        out = _convert(Path(capture), folder, Path(names_file), spec, options)
    if 'error' in out:
        code = out.get('code') or 'TTM-NET-23'
        spanish = dict(what_es=out['error_es']) if out.get('error_es') else {}
        if code == 'TTM-NET-23':
            raise KitError(code, what=out['error'], fix=out.get('fix') or 'Prepare the match again.', **spanish)
        raise KitError(code, what=out['error'], **spanish)
    return out


def _names(names_file):
    try:
        rows = json.loads(Path(names_file).read_text(encoding='utf-8'))['characters']
        return {r['character_id']: r.get('name') for r in rows if isinstance(r, dict)}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def quad_backup_conversion(ram):
    """[(address, bytes)]: quad_viewports' copy of both side cameras (BACKUP), converted like the side cameras.

    The split-screen renderer (quad_viewports DRAW) copies both side cameras to BACKUP when it starts and copies them
    back when it ends. A 2-player match saved while that DRAW was running (the kit cannot choose the moment within a
    rendered frame) resumes inside it, so its end wrote the split-screen side cameras back over the converted ones:
    both cameras stayed on the half-width templates (mode 1) for the whole match and each window drew only its half
    of the screen (live, Sept 30: a 2-player 3v3 --prepare; the game itself stayed identical). With BACKUP converted
    by netplay_view.single_view_conversion's own rule the restore writes the single-view cameras back. Display only:
    BACKUP is read by nothing else."""
    import netplay_view as nv
    import quad_viewports as quad
    u = lambda a: struct.unpack_from('<I', ram, a)[0]
    if u(quad.CONTROL) != quad.MAGIC:
        return []
    manager = u(A(0x2FEBD4))                                       # gp-22172, the camera manager
    full = bytes(ram[manager:manager + 608])
    out = []
    for side in range(2):
        record = quad.BACKUP + nv.SIDE_STRIDE * side
        if u(record + 640) != 1 or u(record + 644) != side:
            continue                                            # not a split-screen copy: nothing to convert
        half = ram[manager + 608 * (side + 1):manager + 608 * (side + 2)]
        live = bytearray(ram[record:record + 608])
        for o in range(0, 608, 4):
            if live[o:o + 4] == half[o:o + 4]:
                live[o:o + 4] = full[o:o + 4]
        out += [(record, bytes(live)), (record + 640, struct.pack('<I', 0))]
    return out


def test_ko_blocks(ram, actors, divisor=8):
    """TEST HOOK ONLY (--test-hooks): Team 2 (odd fighters) nearly beaten, so bots reach a KO in seconds: its leader (the
    guest's fighter) at 1 HP, its CPU partners at an eighth of their HP, so the guest falls first and can take over a
    teammate. Both PCs load the same file, so this is part of the agreed state; a real match never gets it."""
    u = lambda a: struct.unpack_from('<I', ram, a)[0]
    out = []
    for a in actors:
        if a['index'] % 2 == 1:
            slot = u(a['actor'] + HP_SLOT)
            address = a['actor'] + HP_ROW + min(slot, 4) * HP_STRIDE
            new = 1 if a['index'] == 1 else max(1, u(address) // divisor)
            if u(address) > new:
                out.append((address, struct.pack('<I', new)))
    return out


def test_leader_blocks(ram, actors):
    """TEST HOOK ONLY (--test-hooks): both leaders (the two players' fighters) at 1 HP, every CPU partner untouched, so
    both players fall within seconds and can take over a teammate (R-TAKEOVER-R3). A real match never gets it."""
    u = lambda a: struct.unpack_from('<I', ram, a)[0]
    out = []
    for a in actors:
        if a['index'] in (0, 1):
            slot = u(a['actor'] + HP_SLOT)
            address = a['actor'] + HP_ROW + min(slot, 4) * HP_STRIDE
            if u(address) > 1:
                out.append((address, struct.pack('<I', 1)))
    return out


def test_ki_blocks(ram, actors):
    """TEST HOOK ONLY (--test-hooks): every CPU extra (index 2..) starts with full ki and blast stocks, so the CPUs
    transform early (the transformation-timing rig). A real match never gets it."""
    u = lambda a: struct.unpack_from('<I', ram, a)[0]
    out = []
    for a in actors:
        if a['index'] >= 2:
            slot = u(a['actor'] + HP_SLOT)
            row = a['actor'] + HP_ROW + min(slot, 4) * HP_STRIDE
            for value_at, max_at in ((row + 8, row + 12), (row + 16, row + 20)):
                if u(max_at) and u(value_at) != u(max_at):
                    out.append((value_at, struct.pack('<I', u(max_at))))
    return out


def full_health_blocks(ram, actors):
    """(k) [(address, bytes)]: every fighter's current health := its maximum (actor+0x9E4+0xA4*slot holds the current
    health, +4 the maximum). The copy's fight runs a moment before its capture (the mod's services attach, then the
    capture rule's settle) while nobody plays player 1's fighter and every CPU fighter acts, so a made match started
    with damage already taken, mostly by the host's leader (Stage 2 review: up to 8220 of 50000). The online fight
    starts with everyone at full health, as it starts with the full Duel Time (e)."""
    u = lambda a: struct.unpack_from('<I', ram, a)[0]
    out = []
    for a in actors:
        slot = u(a['actor'] + HP_SLOT)
        if slot > 4:
            continue
        row = a['actor'] + HP_ROW + slot * HP_STRIDE
        current, maximum = struct.unpack_from('<iI', ram, row)
        if 0 < current < maximum <= 1000000:
            out.append((row, struct.pack('<I', maximum)))
    return out


def checkpoint_from_log(lines, dest):
    """The playable checkpoint the copy's watcher named last ('Rematch checkpoint: PATH'), or None. A relative path is
    the copy's game folder's."""
    for line in reversed(list(lines or [])):
        m = CHECKPOINT_LINE.search(line)
        if m:
            path = Path(m.group(1).strip())
            if not path.is_absolute():
                path = Path(dest) / 'game' / path
            return path
    return None


def online_blocks(ram, actors, spec, problems):
    """[(address, bytes)] of the conversion's online writes (b)-(h) for a checkpoint; appends to `problems` what does
    not hold the expected values (the conversion then refuses the save)."""
    import kit_spec
    import netplay_fixups
    u = lambda a: struct.unpack_from('<I', ram, a)[0]
    blocks = []

    def word(address, allowed, new, what):
        old = u(address)
        if old == new:
            return
        if allowed is not None and old not in allowed:
            problems.append(f'{what} holds {old:#x}')
            return
        blocks.append((address, struct.pack('<I', new)))
    word(PAUSE_COUNT, (1, 2), 0, 'the pause port count')                                    # (b)
    humans = {s for s, _, _ in kit_spec.humans(spec)}                                       # physical indices
    real = {kit_spec.slot_of(t, i) for t, team in enumerate(spec['teams']) for i in range(len(team))}
    import team_start_gate as gate
    for i, a in enumerate(actors):                                                           # (c)
        if i not in real:
            continue                                                                         # a padded, absent seat
        cpu = 0 if i in humans else 1
        armed = u(gate.CONTROL) == 1 and u(gate.CONTROL + 0x80 + 4 * i) == a['actor']
        if armed:
            word(gate.CONTROL + 0x40 + 4 * i, (0, 1), cpu, f'fighter {i}\'s start CPU flag')
        else:
            word(a['actor'] + 0x1278, (0, 1), cpu, f'fighter {i}\'s CPU flag')
    import spectator_switch
    mask = kit_spec.slot_mask(spec) & 3
    if u(SPECTATOR) != spectator_switch.MAGIC:
        problems.append('the spectator / takeover service is not installed')
    elif mask:                                                                               # (d)
        word(SPECTATOR + PORTS, (1, 2, 3), 3, 'the spectator port mask')
        word(SPECTATOR + HUMAN_PORTS, (0, 1, 2, 3), mask, 'the human port mask')
    for a in actors:
        if a['index'] < 2 or a['index'] in humans:
            word(a['actor'] + 0x1300, (0, 1), 1, f'fighter {a["index"]}\'s transformation flag')   # (e)
    extras = sum(1 << i for i in humans if i >= 2)
    if spec.get('type') == 'hub':                         # kit 2.1: a newcomer may adopt any fighter of a hub
        extras |= sum(1 << i for i in real if i >= 2)
    if extras:                                                                               # (e2)
        import extra_specials
        if u(extra_specials.CONTROL) != 1:
            problems.append('the extras\' special moves are not installed (a player cannot play an extra)')
        else:
            word(extra_specials.CONTROL + 20, None, u(extra_specials.CONTROL + 20) | extras,
                 'the human extras\' special-move admission')
        try:
            blocks += lockon_resolver_blocks(ram)
        except ValueError as error:
            problems.append(f'the lock-on queue: {error}')
    battle = u(BATTLE)
    if 0x100000 <= battle < 0x7FFFE00:
        for off in (272, 288):                                                               # the clock unspent
            if u(battle + off):
                blocks.append((battle + off, bytes(4)))
    for name, address in DORMANT:                                                           # (g)
        word(address, (0, 1), 0, name)
    if (spec.get('services') or {}).get('cpu_transform') and u(BG_CONTROL) == BG_MAGIC:     # (g2)
        try:
            blocks += background_online(ram)              # kit 2.1: the unheld IO path, its loader checks agreed
        except (ValueError, ImportError):
            blocks.append((BG_CONTROL, bytes(4)))         # an unknown runner: the held IO path only (kit 2.0)
    if u(ASSIGNMENT) == ASSIGNMENT_MAGIC:                                                    # (h)
        word(ASSIGNMENT + ASSIGNMENT_ARMED, None, 0, 'the controller override')
        word(ASSIGNMENT + ASSIGNMENT_PASS, None, 3, 'the controller override pass mask')
    try:
        blocks += [(a, new) for a, _, new in netplay_fixups.seat_blocks(ram)]               # (f)
    except ValueError as error:
        problems.append(str(error))
    return blocks


def background_online(ram):
    """[(address, bytes)]: extra_reload_quiet's BACKGROUND runner (the unheld IO path of an extra's transformation)
    rebuilt for online play. Offline it starts the IO job only while the native loader is idle - its state, handle
    and pending words (0x31E760 / 0x31E764 / 0x31E77C), which drain at a different moment on every PC. Online the
    three words read a word that is always 0 and the idle test is the job's own start-phase W1 pre-drain
    (kit_service.netplay_variant: the agreed frame every PC's loader is idle). Everything else (the owner's pose,
    the manager's reload words, the task FIFO, the scene flags) is game state, identical on every PC. The job it
    calls is the one the host service builds, whose disc pump is W1 too (kit_service.netplay_variant), so the read
    completes at one agreed frame while the fight goes on: no combat hold for the disc read, as offline."""
    import extra_reload_quiet as quiet
    import netplay_core as nc
    import kit_service
    original = quiet.background_code()
    if ram[quiet.BACKGROUND:quiet.BACKGROUND + len(original)] != original:
        raise ValueError('the background IO runner is not the one the kit knows')
    saved = quiet.Assembler
    kit_service.background_variant(nc.w_entry(1))          # the same builder the host service checks with
    try:
        new = quiet.background_code()
    finally:
        quiet.Assembler = saved
    if quiet.BACKGROUND + max(len(new), len(original)) > quiet.BG_CONTROL:
        raise ValueError('the online background runner does not fit')
    if len(new) > len(original) and any(ram[quiet.BACKGROUND + len(original):quiet.BACKGROUND + len(new)]):
        raise ValueError('the space after the background runner is in use')
    return [(quiet.BACKGROUND, new + bytes(max(0, len(original) - len(new))))]


def lockon_resolver_blocks(ram):
    """[(address, bytes)]: the installed lock-on queue rebuilt as its pad-resolver variant (every human's pad through
    A(0x1DC2A0)), the same variant the mod's four-player matches install; [] when it already is or no queue is
    installed. ValueError for a queue this kit does not recognise."""
    import lockon_queue as lock
    import lockoff_target as unlock
    import battle_mode_policy as modes
    from native_map import A, GP, GPO
    u = lambda a: struct.unpack_from('<I', ram, a)[0]
    if u(lock.CONTROL) != 1:
        return []
    previous = lock.legacy_previous(ram)
    mode = u(modes.CONTROL + 12) if u(modes.CONTROL) == modes.MAGIC else modes.TEAMS
    options = dict(free_for_all=mode == modes.FFA, coop_controls=mode == modes.COOP)
    found = None
    for button_aware in (False, True, lock.CONFIGURABLE):        # (not installed_configuration: it needs a module
        for lockoff in (False, True):                           # the player installation does not have)
            for resolver in (None, A(0x1DC2A0)):
                if lockoff and (button_aware != lock.CONFIGURABLE or u(unlock.CONTROL) != unlock.MAGIC):
                    continue
                code = lock.payload(previous, button_aware=button_aware, pad_resolver=resolver, lockoff=lockoff,
                                    **options)
                if ram[lock.CODE:lock.CODE + len(code)] == code and found is None:
                    found = (button_aware, lockoff, resolver, code)
    if found is None:
        raise ValueError('the installed queue is not one the kit knows')
    button_aware, lockoff, resolver, before = found
    if resolver is not None:
        return []
    after = lock.payload(previous, button_aware=button_aware, pad_resolver=A(0x1DC2A0), lockoff=lockoff, **options)
    if lock.CODE + len(after) > lock.END:
        raise ValueError('the resolver variant does not fit')
    if len(after) > len(before) and any(ram[lock.CODE + len(before):lock.CODE + len(after)]):
        raise ValueError('the space after the queue is in use')
    return [(lock.CODE, after + bytes(max(0, len(before) - len(after))))]


def scene_title(ram, names):
    """'A + B vs C + D' from the SCENE member records (the teams as chosen, never the mod's padding)."""
    u = lambda a: struct.unpack_from('<I', ram, a)[0]
    scene = A(0x331DC8)
    teams = []
    for s in range(2):
        count = min(u(scene + 0xC0 + 0x270 * s), 5)
        teams.append([u(scene + 0xC4 + 0x270 * s + 100 * j) for j in range(count)])
    label = lambda c: names.get(c) or f'Fighter {c}'
    return ' vs '.join(' + '.join(label(c) for c in team) for team in teams), teams


def build_family(found):
    """The accepted build family of a capture's fingerprint (data/guest-fingerprint.json 'families'), else None."""
    recorded = json.loads((kit_paths.NETPLAY / 'data' / 'guest-fingerprint.json').read_text(encoding='utf-8'))
    for family in recorded.get('families', []):
        if found.get('native_prep') == family['native_prep']:
            return family
    return None


def _convert(capture, folder, names_file, spec=None, options=None):
    import hashlib
    import kit_match
    import kit_spec
    import kit_verify
    import netplay_fixups
    import patch_state
    from camera_snapshot import read_ram
    import body_swap
    import fusion_duration
    import npc_transform_policy as npc
    import team_intro
    import team_start_gate as gate
    import guest_loading_screen as cover
    import native_preparation as native_prep
    import netplay_view as nv
    from fresh_team_combat import MODELS, POINTERS, MODE as TEAM_MODE
    from battle_mode_policy import ACTOR_COUNTS
    options = options or {}
    if spec is None:
        return dict(error='a match is converted for a lobby spec only')
    ram = read_ram(capture)
    u = lambda a: struct.unpack_from('<I', ram, a)[0]
    problems = []
    battle = u(BATTLE)
    director = u(battle) if 0x100000 <= battle < 0x7FFFE00 else None
    if director not in (0, 1, 2, 3) or u(RESULT) & 0x1F:
        problems.append(f'the save is not a match before its start (director {director}, result {u(RESULT) & 0x1F})')
    mode, count = u(TEAM_MODE), u(TEAM_MODE + 4)
    if mode != 1 or count not in ACTOR_COUNTS:
        problems.append(f'not a Tag Team Mod battle (mode {mode}, {count} fighters)')
    if u(team_intro.REQUEST) != 1 and u(gate.REQUEST) != 1:
        problems.append('the save is not the mod\'s playable checkpoint (no start request)')
    if u(cover.CONTROL) != 0 or u(native_prep.CONTROL) != 0:
        problems.append('the save still holds the mod\'s loading cover or preparation gate')
    services = spec.get('services') or {}
    if not services.get('body_change') and u(body_swap.CONTROL) == body_swap.MAGIC:
        problems.append('Body Change is installed in this match')
    if not services.get('fusion_timer') and u(fusion_duration.CONTROL) == fusion_duration.MAGIC:
        problems.append('timed fusion is installed in this match')
    if not services.get('cpu_transform') and u(npc.CONTROL) == npc.MAGIC and u(npc.CONTROL + 12) != 1:
        problems.append('CPU transformations are not disabled in this match')
    if u(SCENE_SPLIT) not in (0, 1):
        problems.append(f'the save is in a view that cannot become one screen per player (split flag {u(SCENE_SPLIT)})')
    queue = kit_match.queue_problem({a: u(a) for a in (kit_match.QUEUE_CONTROL, kit_match.QUEUE_CONTROL + 4)})
    if queue:
        problems.append(queue)
    # (0) the installation's guest code: an accepted build family, else TTM-NET-24
    recorded = json.loads((kit_paths.NETPLAY / 'data' / 'guest-fingerprint.json').read_text(encoding='utf-8'))
    found = kit_verify.fingerprint(kit_verify.BytesRam(ram))
    differing = kit_verify.fingerprint_problems(found, recorded['regions'])
    family = build_family(found)
    if differing == ['npc_policy'] and services.get('cpu_transform') and family is not None:
        return dict(code='TTM-NET-30',
                    error='CPU transformations online are not available with this Tag Team Mod build yet (its CPU '
                          'transformation code is not one the kit knows): turn "CPU transformations" off in the room.',
                    error_es='Las transformaciones de la CPU en línea aún no están disponibles con esta versión de Tag '
                             'Team Mod (su código de transformaciones de la CPU no es uno que conozca el kit): '
                             'desactiva "transformaciones de la CPU" en la sala.')
    if (differing or family is None) and kit_paths.INTEGRATED:
        # kit 2.1, inside a Tag Team Mod installation: a build the kit has not recorded is still this release's
        # own (both PCs install the same release); its runtime patch is the installation's own pnach
        import kit_install
        own = kit_install.installation_pnach()
        if own:
            family, differing = dict(family='installation', pnach=own, native_prep=found.get('native_prep')), []
    if differing or family is None:
        return dict(code='TTM-NET-24', fingerprint=found,
                    error='The game code this Tag Team Mod installation installs is not one the online kit knows (Tag '
                          'Team Mod 0.1.0-beta.35 to beta.42): it differs in ' + (', '.join(differing) or 'its build') +
                          '. The installation may be another version, or a file in it was changed.',
                    error_es='El código del juego que instala esta instalación de Tag Team Mod no es uno que el kit en '
                             'línea conozca (Tag Team Mod 0.1.0-beta.35 a beta.42): difiere en ' +
                             (', '.join(differing) or 'su versión') + '. Puede ser otra versión, o se cambió un '
                             'archivo de ella.')
    actors = []
    for i in range(min(count, 12)):
        a = u(POINTERS + 4 * i)
        if not 0x100000 <= a < 0x8000000:
            problems.append(f'fighter {i} has no actor')
            break
        m = u(MODELS + 4 * i)
        character = u(m + 12) if 0x100000 <= m < 0x8000000 else None
        actors.append(dict(index=i, actor=a, identity=u(a), controller=u(a + 4), cpu=u(a + 0x1278),
                           character=character))
    if len(actors) >= 2 and (actors[0]['identity'], actors[1]['identity']) != (0, 1):
        problems.append('the first two fighters are not the two side leaders')
    if problems:
        return dict(error='This match cannot be played online: ' + '; '.join(problems) + '.',
                    fix='Start the match again.')
    blocks = []
    view = 'single'
    if u(SCENE_SPLIT) == 1:
        blocks += [(a, d) for a, d in nv.single_view_conversion(ram)]
        blocks += quad_backup_conversion(ram)
        view = 'converted from split screen'
    online = online_blocks(ram, actors, spec, problems)
    if problems:
        return dict(code='TTM-NET-24', error='The installation\'s match cannot be made an online match: ' +
                    '; '.join(problems) + '.',
                    error_es='El combate de la instalación no se puede convertir en un combate en línea: ' +
                    '; '.join(problems) + '.')
    if spec.get('type') == 'hub':                                                          # (h) the hub
        import hub_mode
        try:
            hub = hub_mode.build_memory(ram, dict(HUB_SETTINGS))
        except ValueError as error:
            return dict(error=f'The hub cannot be installed into this match: {error}.', fix='Start the hub again.')
        taken = sorted((a, a + len(d)) for a, d in blocks + online)
        for p, _, d in hub:
            if any(p < e and s < p + len(d) for s, e in taken):
                return dict(error=f'The hub would overwrite another online write at {p:#010x}.',
                            fix='Start the hub again.')
        online += [(p, d) for p, _, d in hub]
    test = []
    if options.get('test_ko'):
        divisor = options.get('ko_divisor', 8)
        divisor = divisor if isinstance(divisor, int) and 2 <= divisor <= 64 else 8
        test = test_ko_blocks(ram, actors, divisor)
    elif options.get('test_leaders'):
        test = test_leader_blocks(ram, actors)
    if options.get('test_ki'):
        test += test_ki_blocks(ram, actors)
    blocks += online + test
    folder = Path(folder)
    patch_state.OUTPUT_ROOT = folder
    base = folder / 'base.p2s'
    if base.exists():
        base.unlink()
    if blocks:
        manifest = dict(serial=patch_state.SERIAL, crc=patch_state.CRC, blocks=[
            dict(address=a, expected_hex=bytes(ram[a:a + len(d)]).hex(), data_hex=bytes(d).hex()) for a, d in blocks])
        patch_state.patch(capture, manifest, base)
    else:
        shutil.copyfile(capture, base)
    mask = kit_spec.slot_mask(spec)
    try:
        built = kit_match.build_netplay(base, folder / 'netplay.p2s', mask, spec)
    except Exception as error:  # noqa: BLE001 - explained
        return dict(error=f'The online part could not be installed into this match: {type(error).__name__}: {error}',
                    fix='Start the match again.')
    words = kit_verify.file_words(folder / 'netplay.p2s')                                      # (j)
    differ = kit_verify.problems(words, spec, netplay_fixups.fixed_sha256())
    if differ:
        return dict(code='TTM-NET-31', words=words,
                    error='The prepared match does not hold what the lobby chose: ' + '; '.join(differ[:6]) + '.',
                    error_es='El combate preparado no tiene lo que se eligió en la sala: ' +
                    '; '.join(differ[:6]) + '.')
    names = _names(names_file)
    title, scene_teams = scene_title(ram, names)
    return dict(title=title, view=view, fighters=len(actors),
                actors=[{k: v for k, v in a.items() if k != 'actor'} for a in actors], scene_teams=scene_teams,
                blocks=len(blocks), online_blocks=[f'{a:#010x}:{d.hex()}' for a, d in online],
                test_blocks=[f'{a:#010x}:{d.hex()}' for a, d in test], netplay=built, base=str(base),
                words=words, verify_sha=kit_verify.sha(words), fingerprint=found, family=family['family'],
                pnach=family['pnach'], director=director,
                netplay_sha256=hashlib.sha256((folder / 'netplay.p2s').read_bytes()).hexdigest())


if __name__ == '__main__':
    # python kit_prepare.py convert CAPTURE FOLDER NAMES_FILE [SPEC_JSON|-] [OPTIONS_JSON|-]
    # (the installation copy's Python runs this)
    if len(sys.argv) in (5, 7) and sys.argv[1] == 'convert':
        spec = options = None
        if len(sys.argv) == 7:
            spec = json.loads(Path(sys.argv[5]).read_text(encoding='utf-8')) if sys.argv[5] != '-' else None
            options = json.loads(Path(sys.argv[6]).read_text(encoding='utf-8')) if sys.argv[6] != '-' else None
        try:
            result = _convert(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), spec, options)
        except Exception as error:  # noqa: BLE001 - reported as JSON
            import traceback
            result = dict(error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc()[-1500:])
        print(json.dumps(result, default=str))
