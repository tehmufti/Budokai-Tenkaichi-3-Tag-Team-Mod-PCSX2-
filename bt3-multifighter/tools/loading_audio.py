"""Reversible mute of only the isolated PCSX2 audio sessions during loading.

No endpoint/master volume API is used, and only sessions of this installation's
own PCSX2 (exact executable path) are ever touched. Only the loading cover
mutes; a failure cover never does. Windows keeps an application's mute across
launches (per executable path and output device), so a PCSX2 closed while its
loading mute was on used to start muted forever. The mod therefore owns its
private PCSX2's session mute: a restore returns to unmuted, except for a mute
the player set after this session's helper had checked (and cleared) that
session, and each Play launch (--repair) unmutes that PCSX2 once its audio
sessions appear, unless a loading cover is muting them right then. Receipts
are written before changes; an independent helper-death watchdog restores them.
Windows/COM access is lazy so all ownership tests run without touching audio.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path
from atomic_files import read_json, write_json, unlink

ROOT = Path(__file__).resolve().parents[1]
WHEEL = ROOT/'tools/vendor-wheels/pycaw-20251023-py3-none-any.whl'
WINDOWS = os.name == 'nt'
RECEIPT = ROOT/'analysis/loading-audio-restore.json'
REPAIR_POLL = 2.0  # seconds between the launch repair's looks for new sessions of its PCSX2
CLEARED = '.cleared'  # an earlier session's receipt is set aside under this suffix: kept, never read again
REPAIRED = 'audio-repaired.json'  # in the session folder: the sessions the launch repair has checked (pid, sessions)


def cover_mutes(command):
    """Only the loading cover mutes. A cover that carries an error (setup stopped, a failed fighter
    update, a freeze or menu-return notice) never does: the player may close PCSX2 from it, and
    Windows would keep that mute for the next launch."""
    return isinstance(command, dict) and command.get('visible') is True and not command.get('error')


def loading_muted(folder, now=None):
    """True while this Play session asks for a loading cover that mutes (its presentation.json,
    fresh as loading_presentation.visible_state counts it). An unreadable command counts as muting,
    so the repair waits a poll instead of unmuting under a loading screen."""
    path = Path(folder)/'presentation.json'
    if not path.is_file(): return False
    try: command = read_json(path)
    except (OSError, ValueError): return True
    updated = command.get('updated', 0) if isinstance(command, dict) else 0
    now = time.time() if now is None else now
    return (cover_mutes(command) and isinstance(updated, (int, float)) and not isinstance(updated, bool)
            and -5 <= now-updated <= 15)


def repaired_sessions(folder, pid=None):
    """Session instances the Play-launch repair has checked, from folder/REPAIRED (only pid's, when given; an
    instance names its own process anyway): any mute they started with is gone, so a mute found on one later
    is the player's own. None when the file is missing, unreadable or another PCSX2's."""
    try: saved = read_json(Path(folder)/REPAIRED)
    except (OSError, ValueError): return set()
    if (not isinstance(saved, dict) or (pid is not None and saved.get('pid') != pid)
            or not isinstance(saved.get('sessions'), list)): return set()
    return {key for key in saved['sessions'] if isinstance(key, str)}


def process_running(pid, created):
    """The exact process (PID and creation time): a reused PID is another process."""
    import psutil
    try:
        process = psutil.Process(pid)
        return abs(process.create_time()-created) < .01 and process.status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def clear_stale_receipts(executable, root=ROOT, running=process_running):
    """Set aside this executable's loading-audio receipts left by earlier sessions (none of their PCSX2
    processes runs any more): each is renamed to its name + CLEARED, which no launch reads again. They
    can never restore anything: restore() needs the same process, and the Play-launch repair has taken
    over the mute they record. Renamed, not deleted: a receipt is the evidence of a session that closed
    under a loading mute. Returns the receipts' original paths."""
    analysis = Path(root)/'analysis'
    folder = analysis/'autopilot'
    paths = [analysis/'loading-audio-restore.json', *sorted(folder.glob('audio-restore-*.json')),
             *sorted(folder.glob('*/audio-restore-*.json'))]
    cleared = []
    for path in paths:
        try:
            # Never follow a link out of this installation's analysis folder.
            if not path.is_file() or not path.resolve().is_relative_to(analysis.resolve()): continue
            saved = read_json(path)
            if Path(saved['executable']).resolve() != Path(executable).resolve(): continue
            if any(running(record['pid'], record['created']) for record in saved['sessions'].values()):
                continue  # a live session's receipt: its own helper or watchdog restores it
            path.replace(path.with_name(path.name+CLEARED)); cleared.append(path)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue  # unreadable or in use: left for the next launch
    return cleared


class WindowsAudio:
    def __init__(self):
        sys.path.insert(0, str(WHEEL))
        import comtypes
        import psutil
        from pycaw.utils import AudioUtilities, AudioSession
        from pycaw.api.audiopolicy import IAudioSessionControl2, IAudioSessionManager2
        self.comtypes, self.psutil = comtypes, psutil
        self.utilities, self.session = AudioUtilities, AudioSession
        self.control, self.manager = IAudioSessionControl2, IAudioSessionManager2

    def sessions(self, executable):
        wanted = os.path.normcase(str(Path(executable).resolve()))
        result = []
        enum = self.utilities.GetDeviceEnumerator()
        devices = enum.EnumAudioEndpoints(0, 1)  # active render endpoints only
        for i in range(devices.GetCount()):
            device = devices.Item(i)
            interface = device.Activate(self.manager._iid_, self.comtypes.CLSCTX_ALL, None)
            sessions = interface.QueryInterface(self.manager).GetSessionEnumerator()
            for j in range(sessions.GetCount()):
                session = self.session(sessions.GetSession(j).QueryInterface(self.control))
                pid = session.ProcessId
                if not pid: continue
                try:
                    process = self.psutil.Process(pid)
                    if os.path.normcase(process.exe()) != wanted: continue
                    result.append(dict(pid=pid, created=process.create_time(),
                        instance=session.InstanceIdentifier, identifier=session.Identifier,
                        volume=session.SimpleAudioVolume))
                except (self.psutil.NoSuchProcess, self.psutil.AccessDenied):
                    continue
        return result


class AudioMute:
    def __init__(self, executable, receipt=RECEIPT, backend=None):
        # receipt=None: a controller that only unmutes (the launch repair) and never mutes.
        self.executable = Path(executable).resolve()
        self.receipt = None if receipt is None else Path(receipt)
        self.backend = backend; self.records = {}
        if self.receipt is not None and self.receipt.exists():
            saved = read_json(self.receipt)
            if Path(saved['executable']).resolve() != self.executable:
                raise ValueError('Audio recovery receipt belongs to another executable')
            self.records = saved['sessions']

    def _sessions(self):
        if self.backend is None:
            if not WINDOWS:
                # PipeWire/PulseAudio muting (pactl) is deferred: a crash could leave PCSX2 muted.
                raise RuntimeError('Loading audio muting uses Windows audio sessions; it is off on this system')
            self.backend = WindowsAudio()
        return self.backend.sessions(self.executable)

    def _save(self):
        if self.receipt is None: raise ValueError('Muting needs a recovery receipt')
        self.receipt.parent.mkdir(parents=True, exist_ok=True)
        if not self.records:
            unlink(self.receipt); return
        write_json(self.receipt, dict(executable=str(self.executable), sessions=self.records))

    def mute(self, pid, keep=None):
        """Mute pid's sessions for a loading cover. keep: session instances this controller has already
        checked and unmuted (repair's seen): a mute found on one of those is the player's own (the Windows
        volume mixer), so restore() puts it back (player_muted). On any other session a mute found is
        Windows replaying an earlier session's loading mute, and restore() unmutes it."""
        for session in self._sessions():
            if session['pid'] != pid: continue
            key = session['instance']
            record = self.records.get(key)
            if record is None:
                record = {k: session[k] for k in ('pid', 'created', 'instance', 'identifier')}
                # 'muted' (what beta.33 restored) is never the state found: this is the mod's private
                # PCSX2, and recording a replayed mute made every later restore keep the game silent.
                record['muted'] = False
                record['player_muted'] = bool(keep is not None and key in keep and session['volume'].GetMute())
                record['applied'] = False
                self.records[key] = record
                self._save()  # Written before the first mutation.
            elif record['pid'] != session['pid'] or record['created'] != session['created']:
                continue
            if record.get('applied', False): continue
            session['volume'].SetMute(1, None)
            record['applied'] = True
            self._save()

    def restore(self):
        if not self.records: return True
        for session in self._sessions():
            record = self.records.get(session['instance'])
            if record is None: continue
            if record['pid'] != session['pid'] or record['created'] != session['created']:
                continue  # PID/session reuse is never permission to alter it.
            # Unmuted, whatever an older receipt's 'muted' says; only the player's own mute is put back.
            session['volume'].SetMute(1 if record.get('player_muted') is True else 0, None)
            del self.records[session['instance']]
            self._save()
        return not self.records

    def repair(self, pid=None, seen=None, hold=None):
        """Unmute this private PCSX2's sessions (only pid's, when given) that this controller is not
        muting for a loading cover. seen: session instances already handled; each is handled once
        and added to it, so a later mute by the player stays theirs. hold(): checked right before
        each unmute; True (a loading cover is muting now) defers that session to a later call.
        Returns the number of sessions unmuted. Off Windows nothing is ever muted: nothing to do."""
        if self.backend is None and not WINDOWS: return 0
        unmuted = 0
        for session in self._sessions():
            if pid is not None and session['pid'] != pid: continue
            key = session['instance']
            if seen is not None and key in seen: continue
            record = self.records.get(key)
            if record is not None and record['pid'] == session['pid'] and record['created'] == session['created']:
                continue  # muted for the loading cover right now; restore() unmutes it
            if session['volume'].GetMute():
                if hold is not None and hold(): continue
                session['volume'].SetMute(0, None)
                unmuted += 1
            if seen is not None: seen.add(key)
        return unmuted

    def mute_states(self, pid=None):
        """{session instance: muted} of this private PCSX2's sessions (only pid's, when given), as Windows
        has them now: what the player hears, whoever set it. Read only. Off Windows: {}."""
        if self.backend is None and not WINDOWS: return {}
        return {session['instance']: bool(session['volume'].GetMute()) for session in self._sessions()
                if pid is None or session['pid'] == pid}


def mute_changes(before, after, loading):
    """The audio-repair log's lines for this PCSX2's sessions whose mute changed (or that appeared) between two
    looks, saying whether a loading cover was muting then. A mute while none was is what a silent match shows
    (before beta.34 no log said so: the helper only reported its own mutes)."""
    lines = []
    for key, muted in sorted(after.items()):
        if before.get(key) is muted: continue
        output = key.split('|', 1)[0]
        if not muted: lines.append(f'PCSX2 sound is on (output {output}).')
        elif loading: lines.append(f'PCSX2 sound is muted by the loading screen (output {output}).')
        else: lines.append(f'PCSX2 sound is muted while no loading screen mutes it (output {output}): '
                           'the Windows volume mixer or another program did it.')
    return lines


def repair_launch(executable, pid, created, folder, backend=None, root=ROOT, poll=REPAIR_POLL,
                  running=process_running, sleep=time.sleep, log=None):
    """Play launch: the private PCSX2 (pid) never keeps a mute the mod left behind.

    Clears earlier sessions' receipts, then until that PCSX2 exits unmutes each of its audio
    sessions once, when it first appears (every output device keeps its own remembered mute),
    except while this session's loading cover is muting (folder/presentation.json). Every change
    of their mute is logged (mute_changes), so a silent match can be told from the log. The sessions
    checked so far go to folder/REPAIRED, for the loading helper (repaired_sessions)."""
    say = log or (lambda text: print(time.strftime('%H:%M:%S'), text, flush=True))
    audio = AudioMute(executable, None, backend)
    cleared = clear_stale_receipts(audio.executable, root, running)
    if cleared:
        say(f'Cleared {len(cleared)} loading-audio receipt(s) of earlier sessions (kept as *{CLEARED}): '
            +', '.join(map(str, cleared)))
    seen = set(); failed = False; states = {}
    hold = lambda: loading_muted(folder)
    while running(pid, created):
        try:
            loading = hold()
            if not loading:
                checked = len(seen)
                unmuted = audio.repair(pid, seen, hold)
                if unmuted:
                    say(f'Unmuted {unmuted} audio session(s) of {audio.executable}: they started muted '
                        '(Windows kept an earlier mute); the mod keeps this PCSX2 unmuted outside loading screens.')
                if len(seen) != checked:
                    write_json(Path(folder)/REPAIRED, dict(pid=pid, created=created, sessions=sorted(seen)))
            now = audio.mute_states(pid)
            for line in mute_changes(states, now, loading): say(line)
            states = now
        except Exception as error:  # noqa: BLE001 - COM can fail transiently; the next poll retries
            if not failed:
                say(f'Audio check unavailable for now: {error}')
                failed = True
        sleep(poll)
    say(f'PCSX2 ({pid}) closed; {len(seen)} audio session(s) were checked.')
    return seen


def start_repair(executable, pid, created, folder):
    """Start repair_launch as an independent hidden process (Windows) that ends with that PCSX2."""
    import subprocess
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    with (folder/'audio-repair.log').open('a', encoding='utf-8') as output:
        return subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--repair', str(int(pid)),
            '--created', repr(float(created)), '--session', str(folder), '--emulator', str(executable)],
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            stdin=subprocess.DEVNULL, stdout=output, stderr=output)


def recover(executable, receipt=RECEIPT, timeout=5):
    controller = AudioMute(executable, receipt)
    deadline = time.monotonic()+timeout
    while True:
        try:
            if controller.restore(): return True
        except Exception as error:
            print(f'Audio restore is pending: {error}', flush=True)
        if time.monotonic() >= deadline: return False
        time.sleep(.2)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--watch', type=int, help='restore the loading mute once this helper process exits')
    mode.add_argument('--repair', type=int, metavar='PID', help='Play launch: unmute this PCSX2 until it exits')
    parser.add_argument('--created', type=float, help='creation time of the --repair process')
    parser.add_argument('--session', type=Path, help="this Play session's folder (its presentation.json)")
    parser.add_argument('--emulator', required=True, type=Path)
    parser.add_argument('--receipt', type=Path, default=RECEIPT)
    args = parser.parse_args(argv)
    if args.repair is not None:
        if args.created is None or args.session is None: parser.error('--repair needs --created and --session')
        repair_launch(args.emulator, args.repair, args.created, args.session)
    else:
        from presentation_settings import wait_process
        wait_process(args.watch)
        recover(args.emulator, args.receipt)


if __name__ == '__main__':
    main()
