"""Temporarily set quiet, borderless, unpaused startup in runtime128.

Apply before PCSX2 starts; a separate watchdog restores the individual keys
after that process exits, even if its launcher/watcher is stopped. A retained
receipt is also recovered on the next launch. A key the emulator duplicated (its INI
allows the same key twice) is collapsed to one entry and restored as it was found. Display values, the manual graphics
fix switch and the original start-paused preference are restored, preserving unrelated edits. No audio or controller settings
are changed by this module. Savestate compression is pinned to Zstandard for the session the same way, so the
states the mod reads never use a method it cannot decode; the player's own choice comes back afterwards.
"""
import runtime_profile
import argparse
import ctypes
import json
import os
import re
import sys
from pathlib import Path
from atomic_files import read_json, write_bytes, unlink

ROOT = Path(__file__).resolve().parents[1]
CONFIG = runtime_profile.CONFIG
RECEIPT = ROOT / ('analysis/presentation-settings.json' if runtime_profile.NAME == 'runtime128'
                  else f'analysis/presentation-settings-{runtime_profile.NAME}.json')
SECTION = 'EmuCore/GS'
# v2.5.211 uses OsdMessagesPos (integer enum None=0); retain legacy coverage.
VALUES = {'OsdMessagesPos': '0', 'OsdShowMessages': 'false', 'OsdShowIndicators': 'false',
          'FullscreenMode': '',  # Borderless fullscreen allows the loading cover.
          # PCSX2's game database chooses version-appropriate half-pixel/native-scaling
          # corrections. Manual fixes bypass them and can offset the cel-shaded image
          # from its outlines at upscaled resolutions. Never hard-code those enums or
          # lower the user's resolution; restore this switch after the session.
          'UserHacks': 'false'}
# Loading and split-screen speed from Mod Settings, applied for the launcher's session only.
# Fast CDVD halves emulated disc sector/read delays under 100 ms (measured: a 5v5's native load
# 21-22 s -> 19 s and its extra-fighter disc wait 13.9 s -> 9.5 s). 'default' leaves PCSX2's own
# EE cycle rate untouched, so nothing overrides a rate chosen in PCSX2 itself.
SPEED_SECTION = 'EmuCore/Speedhacks'
CPU_RATES = {'130': '1', '180': '2', '300': '3'}
SPEED_KEYS = {(SPEED_SECTION, 'fastCDVD'), (SPEED_SECTION, 'EECycleRate')}
# Savestates the mod reads must be Zstandard (2 in every PCSX2 from v2.5.211 to 2.8.x, and the
# default). PCSX2 2.6 also offers Deflate64 (1) and LZMA2 (3), which the state readers refuse.
COMPRESSION = ('EmuCore', 'SavestateCompressionType', '2')
# PCSX2's pause key: 'press Space' prompts and the watcher's automatic pause need it. A profile
# without it gets it for the session; a player's own binding is never replaced, and no
# save/load-state key is ever bound (a mid-match state load turns fighter updates off).
PAUSE_KEY = ('Hotkeys', 'TogglePause', 'Keyboard/Space')
CREATED_SECTIONS = {SPEED_SECTION, COMPRESSION[0], PAUSE_KEY[0]}


class ForeignReceipt(ValueError):
    """A presentation receipt that names another PCSX2.ini than this install's."""


def section_bounds(lines, section=SECTION):
    start = None
    for index, line in enumerate(lines):
        match = re.match(r'^\s*\[([^]]+)\]\s*$', line.strip())
        if not match: continue
        if start is not None: return start, index
        if match[1] == section: start = index+1
    if start is None: raise ValueError('Missing isolated graphics configuration section')
    return start, len(lines)


def entries(lines, key, section=SECTION):
    start, end = section_bounds(lines, section)
    matches = [(i, re.match(r'^([ \t]*'+re.escape(key)+r'[ \t]*=[ \t]*)([^\r\n]*)([\r\n]*)$', lines[i]))
               for i in range(start, end)]
    return [(i, match) for i, match in matches if match]


def set_value(lines, key, value, section=SECTION):
    found = entries(lines, key, section)
    if len(found) > 1: raise ValueError(f'Duplicate graphics setting: {key}')
    if found:
        index, match = found[0]
        if value is None: del lines[index]
        else: lines[index] = match[1]+value+(match[3] or '')
    elif value is not None:
        start, end = section_bounds(lines, section)
        newline = '\r\n' if any(line.endswith('\r\n') for line in lines) else '\n'
        lines.insert(start, f'{key} = {value}{newline}')


def collapse(lines, key, value, section=SECTION):
    """Leave exactly one `key` in `section` holding `value`; return (original, extra originals).

    PCSX2 keeps each INI section in a multi-key map: when it saves a key we already wrote, it
    can append its own copy instead of replacing ours, so a profile ends up with both
    'OsdShowMessages = false' (ours) and 'OsdShowMessages = true' (the emulator's). Keeping one
    entry makes the value unambiguous whichever copy the emulator reads, and heals a profile
    that older versions duplicated. Values that were not ours are remembered for restore().
    """
    found = entries(lines, key, section)
    values = [match[2] for _, match in found]
    ours = str(value).strip().lower()
    foreign = [v for v in values if v.strip().lower() != ours]
    original = foreign[0] if foreign else (values[0] if values else None)
    for index, _ in reversed(found[1:]): del lines[index]
    set_value(lines, key, value, section)
    return original, foreign[1:]


def revert(lines, key, applied, original, extra, section=SECTION):
    """Put `original` (plus any extra copies) back, but only over our own applied value."""
    found = [(index, match) for index, match in entries(lines, key, section)
             if match[2].strip().lower() == str(applied).strip().lower()]
    # Leave a deliberately changed setting alone. Never restore an entire old INI over
    # control bindings or other edits made while playing.
    if len(found) != 1: return False
    index, match = found[0]; terminator = match[3] or ''
    replacement = [match[1]+v+terminator for v in ([original] if original is not None else [])+list(extra)]
    lines[index:index+1] = replacement
    return True


def ensure_section(lines, section):
    """Append an empty [section] when the profile has none; return how to undo it, or None."""
    if any(line.strip() == f'[{section}]' for line in lines): return None
    newline = '\r\n' if any(line.endswith('\r\n') for line in lines) else '\n'
    terminated = bool(lines) and not lines[-1].endswith(('\n', '\r'))
    if terminated: lines[-1] += newline
    lines.extend([newline, f'[{section}]{newline}'])
    return dict(section=section, terminated=terminated)


def remove_created_section(lines, created):
    """Undo ensure_section when the section is still empty (nobody else wrote into it)."""
    section = created['section']
    heads = [i for i, line in enumerate(lines) if line.strip() == f'[{section}]']
    if len(heads) != 1: return
    start = heads[0]; end = start+1
    while end < len(lines) and not re.match(r'^\s*\[[^]]+\]\s*$', lines[end].strip()): end += 1
    if any(line.strip() for line in lines[start+1:end]): return
    first = start-1 if start and not lines[start-1].strip() else start
    del lines[first:end]
    if created.get('terminated') and lines and first == len(lines):
        lines[-1] = lines[-1].rstrip('\r\n')


def atomic_write(path, data):
    write_bytes(path, data)


def config_relative(config):
    """The INI's path inside this install, so the receipt survives a moved folder (L6)."""
    try:
        return Path(config).resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return None


def receipt_matches(saved, config, receipt):
    """Does a receipt belong to `config`? The same absolute path always does. A receipt kept
    in this install's own analysis folder also does when it names the same INI inside the
    install, wherever the folder was then (moved, renamed, another drive letter)."""
    config = Path(config).resolve()
    if Path(saved['config']).resolve() == config: return True
    if Path(receipt).resolve().parent != (ROOT/'analysis').resolve(): return False
    inside = config_relative(config)
    if inside is None: return False
    recorded = saved.get('config_relative')
    if recorded is not None: return recorded == inside
    tail = Path(inside).parts
    parts = Path(saved['config']).parts
    same = (lambda a, b: a.lower() == b.lower()) if os.name == 'nt' else (lambda a, b: a == b)
    return len(parts) > len(tail) and all(same(a, b) for a, b in zip(parts[-len(tail):], tail))


RECEIPT_FOREIGN = 'Presentation receipt belongs to another configuration'
RECEIPT_UNREADABLE = 'The saved display-settings receipt is unreadable ({detail})'
RECEIPT_SET_ASIDE = '{problem}; it was kept as {name} and the current display settings are used.'


def say(template, **values):
    """A launch-step line in the player's language (localization.tr); English if that fails."""
    try:
        import localization
        return localization.tr(template, **values)
    except Exception:  # noqa: BLE001 - a message never stops the launch
        return template.format(**values)


def set_aside(receipt, problem, **values):
    """Keep a foreign receipt as *.stale-<time>.json and go on: it can never be restored here.
    `problem` is a RECEIPT_* template; `values` fill it."""
    import time
    stale = receipt.with_name(f'{receipt.stem}.stale-{time.strftime("%Y%m%d-%H%M%S")}.json')
    os.replace(receipt, stale)
    print('WARNING: '+say(RECEIPT_SET_ASIDE, problem=say(problem, **values), name=stale.name), flush=True)


def apply(config=CONFIG, receipt=RECEIPT):
    config, receipt = Path(config), Path(receipt)
    if receipt.exists():
        # A receipt that can never be restored here must not stop every later launch (L6).
        try: restore(config, receipt)
        except ForeignReceipt: set_aside(receipt, RECEIPT_FOREIGN)
        except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
            set_aside(receipt, RECEIPT_UNREADABLE, detail=f'{type(error).__name__}: {error}')
    raw = config.read_bytes(); lines = raw.decode('utf-8-sig').splitlines(keepends=True)
    original = {}
    values=dict(VALUES)
    import native_map
    # BT4 changes the disc serial and has no stock GameDB alignment entry. Keep
    # its manual fixes intact rather than disable them without an automatic replacement.
    if native_map.ADAPTER == 'bt4-b14-rev2-eng': values.pop('UserHacks', None)
    import mod_settings
    import widescreen_support as wide
    settings=mod_settings.load_settings()
    wide_enabled=settings['widescreen_patch']
    # Minimal/new portable profiles may not have persisted an EmuCore section.
    # Absence means the emulator default; still validate all sections we edit.
    has_core=any(line.strip()=='[EmuCore]' for line in lines)
    core_wide=entries(lines,'EnableWideScreenPatches','EmuCore') if has_core else []
    if wide_enabled or wide.embedded() or (core_wide and core_wide[0][1][2].strip().lower()=='true'):
        values['AspectRatio']='16:9'
    duplicates = []
    for key, value in values.items():
        original[key], extra = collapse(lines, key, value)
        if extra: duplicates.append(dict(section=SECTION, key=key, values=extra))
    startup = None
    if any(re.match(r'^\s*\[UI\]\s*$', line) for line in lines):
        prior, extra = collapse(lines, 'StartPaused', 'false', 'UI')
        startup = {'StartPaused': prior}
        if extra: duplicates.append(dict(section='UI', key='StartPaused', values=extra))
    receipt.parent.mkdir(parents=True, exist_ok=True)
    extra=[]
    # A profile without [EmuCore] gets one for this session; restore removes it again if still empty.
    created=[section for section in [ensure_section(lines,COMPRESSION[0])] if section]
    section,key,value=COMPRESSION
    prior,compression_extra=collapse(lines,key,value,section)
    extra.append(dict(section=section,key=key,prior=prior,applied=value))
    if compression_extra: duplicates.append(dict(section=section,key=key,values=compression_extra))
    if wide_enabled:
        prior, wide_extra = collapse(lines,'EnableWideScreenPatches','true','EmuCore')
        extra.append(dict(section='EmuCore',key='EnableWideScreenPatches',prior=prior,applied='true'))
        if wide_extra: duplicates.append(dict(section='EmuCore',key='EnableWideScreenPatches',values=wide_extra))
    section,key,value=PAUSE_KEY
    if not any(line.strip() == f'[{section}]' for line in lines) or not entries(lines, key, section):
        created+=[created_section for created_section in [ensure_section(lines,section)] if created_section]
        set_value(lines,key,value,section)
        extra.append(dict(section=section,key=key,prior=None,applied=value))
    speed=[('fastCDVD','true' if settings.get('fast_disc_loading',True) else 'false')]
    rate=CPU_RATES.get(settings.get('emulated_cpu_speed','default'))
    if rate is not None:speed.append(('EECycleRate',rate))
    created+=[section for section in [ensure_section(lines,SPEED_SECTION)] if section]
    for key,value in speed:
        prior,speed_extra=collapse(lines,key,value,SPEED_SECTION)
        extra.append(dict(section=SPEED_SECTION,key=key,prior=prior,applied=value))
        if speed_extra: duplicates.append(dict(section=SPEED_SECTION,key=key,values=speed_extra))
    # Kept in the launch step's log, so a report shows which emulator speed a session used.
    print('Session emulator speed: '+', '.join(f'{k} = {v}' for k,v in speed)+('' if rate else ', EECycleRate = PCSX2 setting'))
    print(f'Session savestate compression: {COMPRESSION[1]} = {COMPRESSION[2]} (Zstandard)')
    resolution=entries(lines,'upscale_multiplier')
    multiplier=resolution[0][1][2] if resolution else 'PCSX2 default'
    graphics=('Session graphics: automatic hardware fixes; internal resolution = {multiplier}'
              if 'UserHacks' in values else
              'Session graphics: existing hardware fix preferences; internal resolution = {multiplier}')
    print(say(graphics, multiplier=multiplier))
    data = dict(config=str(config.resolve()), config_relative=config_relative(config), values=original,
                applied=values,extra=extra,utf8_bom=raw.startswith(b'\xef\xbb\xbf'))
    if created: data['created_sections'] = created
    if duplicates: data['duplicates'] = duplicates
    if startup is not None: data['startup_values'] = startup
    atomic_write(receipt, (json.dumps(data, indent=2)+'\n').encode())
    body = ''.join(lines).encode('utf-8')
    atomic_write(config, (b'\xef\xbb\xbf' if data['utf8_bom'] else b'')+body)
    return data


def restore(config=CONFIG, receipt=RECEIPT):
    config, receipt = Path(config), Path(receipt)
    if not receipt.exists(): return False
    saved = read_json(receipt)
    if not receipt_matches(saved, config, receipt):
        raise ForeignReceipt(RECEIPT_FOREIGN)
    raw = config.read_bytes(); lines = raw.decode('utf-8-sig').splitlines(keepends=True)
    copies = {(item['section'], item['key']): item['values'] for item in saved.get('duplicates', [])}
    for key, value in saved['values'].items():
        if key not in VALUES and key!='AspectRatio': raise ValueError('Unexpected presentation setting in receipt')
        revert(lines, key, saved['applied'][key], value, copies.get((SECTION, key), []))
    for key, value in saved.get('startup_values', {}).items():
        if key!='StartPaused': raise ValueError('Unexpected startup setting in receipt')
        revert(lines, key, 'false', value, copies.get(('UI', key), []), 'UI')
    for item in saved.get('extra',[]):
        if ((item['section'],item['key']) not in (('EmuCore','EnableWideScreenPatches'),COMPRESSION[:2],PAUSE_KEY[:2])
                and (item['section'],item['key']) not in SPEED_KEYS):
            raise ValueError('Unexpected widescreen setting in receipt')
        revert(lines, item['key'], item['applied'], item['prior'],
               copies.get((item['section'], item['key']), []), item['section'])
    created_sections = saved.get('created_sections', [])
    if any(created.get('section') not in CREATED_SECTIONS for created in created_sections):
        raise ValueError('Unexpected created section in receipt')
    # Newest first: only the first section appended may have terminated the original last line.
    for created in reversed(created_sections):
        remove_created_section(lines, created)
    body = ''.join(lines).encode('utf-8')
    atomic_write(config, (b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b'')+body)
    unlink(receipt)
    return True


LINUX = sys.platform.startswith('linux')
UNKNOWN = object()


def process_started(pid):
    """When `pid` started, in the unit of --start-time; None if it is gone, UNKNOWN without psutil.

    Linux: seconds since boot (/proc/<pid>/stat starttime / CLK_TCK). Unlike psutil's
    create_time() (boot time from the wall clock), a clock step cannot change it, so
    the watchdog never mistakes the emulator for a reused PID. play_launcher's
    process_start_time() produces the same value. Elsewhere: psutil's create_time().
    """
    if LINUX:
        try:
            with open(f'/proc/{pid}/stat', 'rb') as stream:
                data = stream.read()
            return float(data[data.rfind(b')') + 2:].split()[19]) / os.sysconf('SC_CLK_TCK')
        except (OSError, ValueError, IndexError):
            return None
    try:
        import psutil
    except ImportError:
        return UNKNOWN
    try:
        return psutil.Process(pid).create_time()
    except psutil.Error:
        return None


def same_process(pid, started):
    """True while `pid` is the process that started at `started` (see process_started)."""
    now = process_started(pid)
    if now is UNKNOWN:
        return True  # nothing to compare with; the PID alone is what Windows has always used
    return now is not None and abs(now-started) < .01


def wait_posix(pid, started=None, poll_interval=.25):
    """Wait for a process that is not our child: a pidfd (Linux 5.3+) or a psutil poll."""
    opener = getattr(os, 'pidfd_open', None)
    descriptor = None
    if opener is not None:
        try: descriptor = opener(pid)
        except ProcessLookupError: return
        except OSError: descriptor = None  # e.g. ENOSYS on an old kernel; poll instead
    if descriptor is not None:
        try:
            # Checked after the pidfd pins the process, so a reused PID is never waited for.
            if started is not None and not same_process(pid, started): return
            import select
            poller = select.poll(); poller.register(descriptor, select.POLLIN)
            while not poller.poll(): pass  # readable once the process has exited
        finally:
            os.close(descriptor)
        return
    import psutil
    import time
    try: process = psutil.Process(pid)
    except psutil.NoSuchProcess: return
    if started is not None and not same_process(pid, started): return
    while True:
        try:
            if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE: return
        except psutil.NoSuchProcess: return
        time.sleep(poll_interval)


def wait_process(pid, started=None):
    """Return once the emulator has exited; `started` refuses a PID that now names another process."""
    if os.name != 'nt':
        wait_posix(pid, started); return
    if started is not None and not same_process(pid, started): return
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]; kernel.OpenProcess.restype = w.HANDLE
    kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    process = kernel.OpenProcess(0x00100000, False, pid)
    if process:
        try: kernel.WaitForSingleObject(process, 0xFFFFFFFF)
        finally: kernel.CloseHandle(process)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('apply', 'restore', 'watch'))
    parser.add_argument('--pid', type=int)
    parser.add_argument('--start-time', type=float, help='When the emulator started (Linux: seconds since boot; elsewhere psutil create_time()), '
                        'so a reused PID is not waited for')
    args = parser.parse_args()
    if args.action == 'apply': apply()
    elif args.action == 'restore': restore()
    else:
        if not args.pid: raise ValueError('Watch requires the emulator PID')
        wait_process(args.pid, args.start_time)
        restore()
