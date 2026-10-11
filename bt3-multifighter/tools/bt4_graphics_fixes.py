"""Give supported BT4 discs their base game's version-matched PCSX2 GS fixes.

PCSX2 loads GameIndex.yaml once per process. Call before starting its isolated
Windows runtime; a running emulator must be closed and reopened. English and
Spanish B14 REV2 share the reviewed adapter and SLUS-21978 serial. We copy only
the selected emulator's BT3 gsHWFixes, not patches, game options or enum guesses.
Linux AppImages have immutable application resources and are left untouched.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import stat
import tempfile

ADAPTER = 'bt4-b14-rev2-eng'
SOURCE = 'SLUS-21678'
TARGET = 'SLUS-21978'
RESOURCE = 'resources/GameIndex.yaml'
BEGIN = '# Tag Team Mod: BT4 graphics alias (begin)'
END = '# Tag Team Mod: BT4 graphics alias (end)'
MAX_DATABASE = 16 << 20


def _heads(text, serial):
    return list(re.finditer(r'^'+re.escape(serial)+r':[ \t]*(?:#[^\r\n]*)?\r?$', text, re.M | re.I))


def _entry(text, serial):
    heads = _heads(text, serial)
    if len(heads) != 1:
        raise ValueError(f'Expected one {serial} GameDB entry, found {len(heads)}')
    start = heads[0].end()
    next_head = re.search(r'^[^ \t#\r\n][^\r\n]*:', text[start:], re.M)
    return text[start:start+next_head.start()] if next_head else text[start:]


def _fixes(entry):
    """Extract a flat GS-fix mapping without rewriting the rest of the YAML."""
    rows = entry.splitlines()
    starts = [i for i, row in enumerate(rows) if re.fullmatch(r'  gsHWFixes:\s*(?:#.*)?', row)]
    if len(starts) != 1:
        raise ValueError('The GameDB entry has no unambiguous hardware-fix mapping')
    result = []; values = {}
    for row in rows[starts[0]+1:]:
        if not row.strip() or row.lstrip().startswith('#'):
            continue
        if not row.startswith('    '):
            break
        match = re.fullmatch(r'    ([A-Za-z][A-Za-z0-9]*):[ \t]+([^\r\n]+)', row)
        if not match or match[1] in values or any(c in match[2] for c in '&*!{}[]'):
            raise ValueError('Unsupported or duplicated GameDB hardware fix')
        values[match[1]] = match[2].split('#', 1)[0].strip().strip('"\'')
        result.append(row)
    for key in ('halfPixelOffset', 'nativeScaling'):
        if not values.get(key, '').isdigit() or not 0 < int(values[key]) <= 32:
            raise ValueError(f'The base-game GameDB entry has no usable {key}')
    if values.get('beforeDraw') != 'OI_DBZBTGames':
        raise ValueError('The base-game GameDB entry has no DBZ draw correction')
    return result


def _alias(rows, newline='\n'):
    return (newline+newline.join([BEGIN, TARGET+':',
            '  name: "Dragon Ball Z - Budokai Tenkaichi 4"',
            '  gsHWFixes:', *rows, END])+newline).encode('utf-8')


def plan(raw, adapter):
    """Read-only plan. Existing entries are never replaced, including custom ones."""
    if adapter != ADAPTER:
        return dict(state='not-bt4', ready=False)
    if len(raw) > MAX_DATABASE or b'\0' in raw:
        raise ValueError('Invalid GameDB size/content')
    text = raw.decode('utf-8-sig')
    existing = _heads(text, TARGET)
    if existing:
        if len(existing) != 1:
            raise ValueError('Duplicate BT4 GameDB entries; no graphics changes made')
        try: _fixes(_entry(text, TARGET))
        except ValueError:
            return dict(state='existing-entry-preserved', ready=False)
        return dict(state='existing-alignment', ready=True)
    if BEGIN in text or END in text:
        raise ValueError('Incomplete BT4 graphics alias; no graphics changes made')
    rows = _fixes(_entry(text, SOURCE))
    inserted = _alias(rows, '\r\n' if '\r\n' in text else '\n')
    return dict(state='add-alignment', ready=True, data=raw+inserted, inserted=inserted)


def _database(runtime):
    """Only the resource file inside this explicit runtime, never linked resources."""
    runtime = Path(runtime).resolve()
    for path in (runtime/'resources', runtime/RESOURCE):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Linked GameDB resources are not modified')
    return runtime/RESOURCE


def plan_runtime(runtime, adapter):
    if adapter != ADAPTER:
        return dict(state='not-bt4', ready=False)
    runtime = Path(runtime)
    if not (runtime/'pcsx2-qt.exe').is_file():
        return dict(state='no-writable-windows-resources', ready=False)
    try:
        path = _database(runtime)
    except FileNotFoundError:
        return dict(state='missing-game-database', ready=False)
    return plan(path.read_bytes(), adapter)


def _atomic(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.'+path.name+'.', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as stream: stream.write(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def restore(runtime, receipt):
    """Remove our exact inserted alias, preserving unrelated changes and edited aliases."""
    receipt = Path(receipt)
    if not receipt.exists(): return False
    saved = json.loads(receipt.read_text(encoding='utf-8'))
    if saved.get('schema') != 1 or saved.get('resource') != RESOURCE:
        raise ValueError('Invalid BT4 graphics receipt')
    inserted = saved['inserted'].encode('utf-8')
    text = inserted.decode('utf-8')
    newline = '\r\n' if '\r\n' in text else '\n'
    if inserted != _alias(_fixes(_entry(text, TARGET)), newline):
        raise ValueError('Invalid BT4 graphics receipt block')
    path = _database(runtime); raw = path.read_bytes()
    changed = raw.count(inserted) == 1
    if changed: _atomic(path, raw.replace(inserted, b'', 1))
    receipt.unlink()
    return changed


def apply(runtime, adapter, receipt=None):
    """Install permanently (setup) or temporarily (Play's existing watchdog)."""
    if receipt is not None: restore(runtime, receipt)
    result = plan_runtime(runtime, adapter)
    if 'data' not in result: return result
    path = _database(runtime)
    if receipt is not None:
        _atomic(receipt, (json.dumps(dict(schema=1, resource=RESOURCE,
            inserted=result['inserted'].decode('utf-8')))+'\n').encode('utf-8'))
    _atomic(path, result['data'])
    return {key: value for key, value in result.items() if key not in ('data', 'inserted')}


def selected_adapter():
    """The validated profile is authoritative; developer BT4 uses its native identity."""
    import game_profile
    chosen = game_profile.installed_adapter()
    if chosen is not None: return chosen
    import native_map
    # BT4's native addresses deliberately alias bt3-usa internally, so ADAPTER
    # alone does not identify the payload in the developer tree.
    if native_map.SERIAL == TARGET and native_map.CRC == '428113C2': return ADAPTER
    return native_map.ADAPTER


def session(runtime, receipt):
    """Optional visual correction: a malformed/custom DB never blocks game launch."""
    adapter = selected_adapter()
    try:
        return dict(apply(runtime, adapter, receipt), adapter=adapter)
    except (OSError, ValueError, KeyError, UnicodeError) as error:
        print('BT4 graphics alignment could not be applied: '+str(error), flush=True)
        return dict(state='unavailable', ready=False, adapter=adapter)
