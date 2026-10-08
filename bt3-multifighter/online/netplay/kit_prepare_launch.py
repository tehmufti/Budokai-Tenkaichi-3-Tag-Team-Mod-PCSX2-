"""Single-process launcher/watch controller for the isolated online builder.

Public Play remains unchanged. This private path consolidates its Python probes,
storage/hooks/display steps and watcher into one interpreter. The current room
has already verified immutable media/build identity; all mutable profile, disc,
dependency and native guards must finish before startup is authorized. A cached,
authenticated neutral selector may initialize concurrently with watcher imports;
ordinary launches finish every preflight before starting the emulator.
"""
import argparse
import configparser
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import uuid


def file_stamp(path):
    value = Path(path).stat()
    return [value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns]


def clean_environment():
    rejected = {'PYTHONPATH', 'PYTHONHOME', 'TAGTEAM_DISC', 'TAGTEAM_ADAPTER', 'REVIEW_TOOLS',
                'TAGTEAM_PINE_SOCKET'}
    result = {key: value for key, value in os.environ.items() if key not in rejected}
    result.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONNOUSERSITE='1', BT3_RUNTIME_PROFILE='runtime28')
    return result


def receipt_owned(status, token, emulator_pid, worker_pid):
    """Authenticate the live watcher and emulator instances, including redirectors."""
    import psutil
    watcher_pid = status.get('pid')
    created = status.get('emulator_created')
    if (status.get('launcher_token') != token or status.get('emulator_pid') != emulator_pid or
            type(watcher_pid) is not int or watcher_pid <= 0 or
            type(created) not in (int, float) or created <= 0 or
            status.get('state') in ('FAILED', 'CLOSED') or
            not isinstance(status.get('native_mode_receipt'), dict)):
        return False
    try:
        if psutil.Process(emulator_pid).create_time() != created:
            return False
        watcher = psutil.Process(watcher_pid)
        # A Windows venv redirector may be the captured parent of the actual
        # watcher. A different alive PID does not satisfy this relationship.
        return watcher_pid == worker_pid or any(parent.pid == worker_pid for parent in watcher.parents())
    except (psutil.Error, OSError):
        return False


def launch(copy, identity_value=None, timeout=45, *, boot=None):
    """Start only the captured private builder and await its owned PINE/watcher receipt."""
    import kit_paths
    import kit_selector_cache
    import kit_win
    from kit_codes import KitError
    if os.name != 'nt':
        raise ValueError('The automated private builder launcher requires Windows')
    copy.check()
    base = copy.base
    expected = (kit_paths.PREP / 'Tag Team Mod').resolve()
    if base.dest.resolve() != expected or not base.desktop or Path(copy.install['root']).resolve() == expected:
        raise ValueError('Fast preparation launch requires an isolated owned installation copy')
    if kit_win.listener_pid(copy.slot) is not None:
        raise KitError('TTM-NET-23', what='The private preparation PINE port is already in use.',
                       fix='Close the earlier online room, then try again.')
    checked = kit_selector_cache.identity(copy)
    if identity_value is not None and checked != identity_value:
        raise ValueError('Private preparation media/build/configuration changed before launch')
    boot_path = None
    if boot is not None:
        boot_path = kit_selector_cache.validate_boot(boot, base.dest, checked, inflate=False)
    root = base.dest / 'game'
    folder = root / 'analysis/autopilot' / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    folder.mkdir(parents=True)
    token = secrets.token_hex(16)
    request = dict(schema=1, root=str(base.dest.resolve()), iso=str(Path(copy.iso).resolve()),
                   iso_stamp=file_stamp(copy.iso), adapter=copy.install['adapter'], slot=copy.slot,
                   token=token, folder=str(folder.resolve()), identity=checked)
    if boot is not None:
        request['selector_boot'] = boot
    request_path = folder / 'private-launch.json'
    request_path.write_text(json.dumps(request), encoding='utf-8')
    console = copy.run_dir / 'prepare-direct.console.txt'
    worker = None
    try:
        worker = kit_win.launch([base.python(), '-B', Path(__file__).resolve(), '--worker', request_path],
                                root, console, base.desktop, env=clean_environment())
        base.cmd_pid = worker
        kit_win.kill_with_me(worker)
        end = time.monotonic() + timeout
        exe = (root / 'runtime28/pcsx2-qt.exe').resolve()
        while time.monotonic() < end:
            copy.check()
            if not kit_win.pid_alive(worker):
                raise KitError('TTM-NET-23', what='The private preparation launcher ended before startup.',
                               fix=f'Read {console} and the private watcher error log, then try again.')
            pid = kit_win.listener_pid(copy.slot)
            if pid and Path(kit_win.process_path(pid)).resolve() == exe and kit_win.pid_alive(pid):
                try:
                    status = json.loads((folder / 'status.json').read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    status = {}
                if status.get('launcher_token') == token and status.get('emulator_pid') == pid:
                    if status.get('state') == 'FAILED':
                        raise RuntimeError('The owned preparation watcher reported a startup failure')
                    if receipt_owned(status, token, pid, worker):
                        base.pid = pid
                        kit_win.kill_with_me(pid)
                        return pid
            elif pid:
                # Never attach to or close a different process that won the port.
                raise ValueError('A foreign process acquired the private preparation PINE port')
            copy.sleep(.05)
        raise TimeoutError('The private preparation controller did not confirm owned startup')
    except BaseException:
        if worker is not None:
            kit_win.kill_tree(worker)  # only our captured worker and its children
        if boot_path is not None:
            try:
                boot_path.unlink(missing_ok=True)
            except OSError:
                pass  # do not replace the actual startup/cancellation failure
        base.pid = base.cmd_pid = None
        raise


def validate_request(path):
    path = Path(path).resolve()
    if path.stat().st_size > 1 << 20:
        raise ValueError('Oversized private launcher request')
    request = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(request, dict) or request.get('schema') != 1 or
            type(request.get('slot')) is not int or not 1024 <= request['slot'] <= 65535 or
            not isinstance(request.get('token'), str) or len(request['token']) != 32 or
            any(c not in '0123456789abcdef' for c in request['token'])):
        raise ValueError('Invalid private launcher request')
    root, folder = Path(request['root']).resolve(), Path(request['folder']).resolve()
    if (root.name != 'Tag Team Mod' or root.parent.name != 'prep' or
            folder.parent != (root / 'game/analysis/autopilot').resolve() or path.parent != folder or
            not (root / 'game/player-install.json').is_file()):
        raise ValueError('Private launcher request does not own its preparation folders')
    if file_stamp(request['iso']) != request['iso_stamp']:
        raise ValueError('Verified ISO changed before private preparation startup')
    return request, root, folder


def preflight_environment(request, root, phase=lambda name, **fields: None):
    """Media, native profile and mutable configuration guards required before spawn."""
    game = root / 'game'
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(game / 'tools'))
    os.environ.pop('TAGTEAM_ADAPTER', None)
    os.environ.pop('TAGTEAM_DISC', None)
    os.environ['BT3_RUNTIME_PROFILE'] = 'runtime28'
    began = time.perf_counter()
    import runtime_profile
    import play_launcher
    import pcsx2_versions
    import game_profile
    phase('launcher_imports', seconds=round(time.perf_counter() - began, 4))
    if Path(sys.prefix).resolve() != (root / '.venv').resolve() or sys.version_info < (3, 11):
        raise ValueError('The private builder must use its checked Python environment')
    problem = play_launcher.venv_problem()
    if problem:
        raise ValueError(problem)
    for path in (runtime_profile.EXECUTABLE, runtime_profile.CONFIG, runtime_profile.DIRECTORY / 'portable.ini',
                 game / 'tools/autopilot.py', game / 'tools/presentation_settings.py'):
        if not path.is_file():
            raise ValueError(f'Missing private preparation file: {path.name}')
    text = runtime_profile.CONFIG.read_text(encoding='utf-8-sig')
    problem = play_launcher.check_configuration(text, request['slot'])
    if problem:
        raise ValueError(problem)
    config = configparser.ConfigParser(interpolation=None)
    config.read_string(text)
    bios_dir = (runtime_profile.DIRECTORY / config.get('Folders', 'Bios', fallback='bios')).resolve()
    bios = (bios_dir / config.get('Filenames', 'BIOS')).resolve()
    if not bios_dir.is_relative_to(runtime_profile.DIRECTORY.resolve()) or not bios.is_relative_to(bios_dir):
        raise ValueError('Private BIOS path escapes its isolated runtime')
    import hashlib
    if hashlib.sha256(bios.read_bytes()).hexdigest() != request['identity']['bios']['sha256']:
        raise ValueError('Private BIOS differs from the verified room identity')
    version = play_launcher.windows_file_version(runtime_profile.EXECUTABLE)
    if not pcsx2_versions.player_accepts(version):
        raise ValueError('Unsupported private PCSX2 runtime version')
    # Resolve and validate the installed executable/resource profile before any
    # native module imports, then pin all watcher helpers to that exact disc.
    began = time.perf_counter()
    disc = game_profile.where()
    if (not disc.get('player') or disc.get('adapter') != request['adapter'] or
            Path(disc['iso']).resolve() != Path(request['iso']).resolve()):
        raise ValueError('Private disc selection differs from the verified online room')
    os.environ['TAGTEAM_DISC'] = str(disc['key'])
    game_profile.forget()
    phase('disc_profile', seconds=round(time.perf_counter() - began, 4))
    if (game / 'tools/bt4_preflight.py').is_file():
        import bt4_preflight
        bt4_preflight.check()
    import mod_settings
    if mod_settings.load_settings().get('expanded_maps'):
        raise ValueError('The private builder must boot its verified original disc')
    if file_stamp(request['iso']) != request['iso_stamp']:
        raise ValueError('Verified ISO changed during preparation startup')
    return runtime_profile, play_launcher


def preflight_watcher(request, root, phase=lambda name, **fields: None):
    """Finish all dependency/native checks before a watcher can authorize startup."""
    game = root / 'game'
    began = time.perf_counter()
    import autopilot
    phase('watcher_import', seconds=round(time.perf_counter() - began, 4))
    original_argv = sys.argv
    began = time.perf_counter()
    try:
        sys.argv = [str(game / 'tools/autopilot.py'), '--check']
        if autopilot.main() != 0:
            raise ValueError('The private watcher dependency/native/settings check failed')
    finally:
        sys.argv = original_argv
    phase('watcher_preflight', seconds=round(time.perf_counter() - began, 4))
    if 'native_mode_receipt' not in (game / 'tools/autopilot.py').read_text(encoding='utf-8'):
        raise ValueError('Private watcher structured ownership receipt is missing')
    import mod_settings
    if mod_settings.load_settings().get('expanded_maps'):
        raise ValueError('The private builder must boot its verified original disc')
    # All immutable media/code was verified by the room and identity. Disc
    # freshness is checked again after the consolidated startup operations.
    if file_stamp(request['iso']) != request['iso_stamp']:
        raise ValueError('Verified ISO changed during preparation startup')
    return autopilot


def preflight(request, root, phase=lambda name, **fields: None):
    """Complete the original launcher guards before an ordinary uncached boot."""
    runtime, launcher = preflight_environment(request, root, phase)
    return preflight_watcher(request, root, phase), runtime, launcher


def stop_owned_process(process, created, executable):
    """A recycled PID or a different image never becomes a cleanup target."""
    try:
        if process.create_time() != created or Path(process.exe()).resolve() != Path(executable).resolve():
            return False
        process.terminate()
        try:
            process.wait(3)
        except Exception:
            if process.create_time() == created and Path(process.exe()).resolve() == Path(executable).resolve():
                process.kill(); process.wait(3)
        return True
    except Exception:
        return False  # already ended or no longer our captured instance


def emulator_command(request, root, executable):
    """Only a revalidated local selector becomes a PCSX2 startup state."""
    command = [str(executable), '-portable', '-fastboot']
    if request.get('selector_boot') is not None:
        import kit_selector_cache
        state = kit_selector_cache.validate_boot(request['selector_boot'], root, request['identity'], inflate=False)
        command += ['-statefile', str(state)]
    return command + ['--', request['iso']]


def watcher_command(request, root, folder, emulator_pid):
    command = [str(root / 'game/tools/autopilot.py'), '--mode', 'Original', '--status-file',
               str(folder / 'status.json'), '--emulator-pid', str(emulator_pid),
               '--launcher-token', request['token']]
    if request.get('selector_boot') is not None:
        # This fresh watcher did not capture the original native menus. The
        # authenticated online selector helper owns all its menu resets; the
        # offline fallback must retain its normal clean-checkpoint lifecycle.
        command.append('--no-menu-checkpoint')
    return command


def prepare_boot_hooks(request, root, runtime, phase=lambda name, **fields: None):
    """Reuse locally authenticated generated bytes or perform normal generation."""
    reused = False
    if request.get('selector_boot') is not None:
        import kit_selector_cache
        # A bad startup authorization is a fatal error, never an excuse to
        # install hooks or start an ordinary VM from an unauthenticated claim.
        kit_selector_cache.validate_boot(request['selector_boot'], root, request['identity'], inflate=False)
        try:
            reused = kit_selector_cache.install_boot_hooks(request['selector_boot'], root, request['identity'])
        except kit_selector_cache.OccupiedBootHooks:
            raise
        except (OSError, ValueError, KeyError) as error:
            # Old/missing/damaged generated artifacts may be rebuilt from the
            # still fully pinned native source. This changes no cache identity
            # and retains the original native occupied-file/receipt guards.
            phase('guest_hooks_rejected', reason=str(error)[:240])
    if not reused:
        import guest_loading_screen
        import game_profile
        from native_map import SERIAL
        guest_loading_screen.install_cheat(runtime.CHEATS / game_profile.cheat_name(SERIAL))
    phase('guest_hooks_complete', cached=bool(reused))


def run_worker(request, root, folder, phase=lambda name, **fields: None):
    """Initialize only a verified private VM; its ownership receipt follows all checks."""
    autopilot = runtime = presentation = lease = child = owned = None
    created = None
    cached = request.get('selector_boot') is not None
    try:
        if cached:
            runtime, launcher = preflight_environment(request, root, phase)
            phase('environment_preflight_complete')
        else:
            autopilot, runtime, launcher = preflight(request, root, phase)
            phase('preflight_complete')
        lease = launcher.Lease(root / 'game/analysis/autopilot/.launcher.lock').acquire()
        try:
            probe = socket.create_connection(('127.0.0.1', request['slot']), timeout=.2)
        except OSError:
            pass
        else:
            probe.close()
            raise ValueError('The private preparation PINE port is already in use')
        import player_storage
        player_storage.prune(root / 'game')
        phase('storage_complete')
        prepare_boot_hooks(request, root, runtime, phase)
        import presentation_settings as presentation
        presentation.apply()
        phase('presentation_complete')
        if file_stamp(request['iso']) != request['iso_stamp']:
            raise ValueError('Verified ISO changed before emulator launch')
        command = emulator_command(request, root, runtime.EXECUTABLE)
        if request.get('selector_boot') is not None:
            phase('selector_boot_validated')
        child = subprocess.Popen(command,
                                 cwd=str(runtime.DIRECTORY), stdin=subprocess.DEVNULL,
                                 stdout=sys.stdout, stderr=sys.stderr, env=os.environ.copy())
        import psutil
        owned = psutil.Process(child.pid)
        created = owned.create_time()
        if Path(owned.exe()).resolve() != Path(runtime.EXECUTABLE).resolve():
            raise ValueError('The spawned private emulator instance has a different executable')
        phase('emulator_spawned', emulator_pid=child.pid, emulator_created=created)
        if cached:
            # Only a fully authenticated neutral selector can run while the
            # Python watcher imports. No status/authorization is published yet;
            # a failed late check closes this exact child before any match can
            # start. The controller still requires its fresh owned watcher and
            # native Running/frame/epoch/code acknowledgements after this.
            autopilot = preflight_watcher(request, root, phase)
            phase('preflight_complete')
        if (file_stamp(request['iso']) != request['iso_stamp'] or
                owned.create_time() != created or
                Path(owned.exe()).resolve() != Path(runtime.EXECUTABLE).resolve()):
            raise ValueError('Private media or emulator ownership changed before watcher startup')
        sys.argv = watcher_command(request, root, folder, child.pid)
        return autopilot.main()
    except BaseException:
        import traceback
        traceback.print_exc()
        return 1
    finally:
        if owned is not None:
            stop_owned_process(owned, created, runtime.EXECUTABLE)
        if presentation is not None:
            try:
                presentation.restore()
            except Exception:
                import traceback
                traceback.print_exc()
        if lease is not None:
            lease.release()


def worker(path):
    request, root, folder = validate_request(path)
    # One interpreter owns both startup and the actual Autopilot. Its PID can be
    # a venv redirector child; the token plus exact emulator instance authenticates it.
    sys.stdout = (folder / 'watcher.log').open('a', encoding='utf-8', buffering=1)
    sys.stderr = (folder / 'errors.log').open('a', encoding='utf-8', buffering=1)
    began = time.perf_counter()
    def phase(name, **fields):
        value = dict(t=round(time.time(), 4), elapsed=round(time.perf_counter() - began, 4),
                     phase=name, **fields)
        with (folder / 'private-launch-phases.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(value) + '\n')
    phase('worker_ready')
    return run_worker(request, root, folder, phase)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path, required=True)
    return worker(parser.parse_args().worker)


if __name__ == '__main__':
    raise SystemExit(main())
