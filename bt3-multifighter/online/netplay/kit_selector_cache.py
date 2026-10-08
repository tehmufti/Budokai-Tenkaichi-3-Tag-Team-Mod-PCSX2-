"""Locally built, authenticated neutral selector checkpoints for the private builder.

These are not match combinations and never contain a prepared fighter arena.
Each disc/build/configuration has one native selector per engine. Loading one
does not restore Python ownership: the current private watcher must consume a
new guarded mode choice before the caller can regard the copy as warm.

The caller owns PrepCopy.lock and its cancellation lifecycle. No user save slot,
original installation, or remote archive is accepted by this helper.
"""
from contextlib import contextmanager
from collections import OrderedDict
import binascii
import configparser
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import shutil
import struct
import tempfile
import threading
import time
import zipfile

SCHEMA = 1
RESTORE_SLOT = 249
MAX_ARCHIVE = 64 << 20
MAX_UNCOMPRESSED = 192 << 20
MAX_METADATA = 1 << 20
MAX_ENTRIES = 64
MAX_BOOT_HOOKS = 16 << 20
RAM_BYTES = 128 << 20
IDENTITY_HASH_WORKERS = 4
_HASHES = {}
_HASH_LOCK = threading.Lock()
MAX_VALIDATED_ARCHIVES = 16
_VALIDATED_ARCHIVES = OrderedDict()
_VALIDATION_LOCK = threading.Lock()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')


def sha(path, *, memo=False):
    """Full content hash; memoization is process-local and guarded by file identity."""
    path = Path(path)
    before = path.stat()
    key = (str(path.resolve()), before.st_dev, before.st_ino, before.st_size,
           before.st_mtime_ns, before.st_ctime_ns)
    if memo:
        with _HASH_LOCK:
            if key in _HASHES:
                return _HASHES[key]
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 << 20), b''):
            digest.update(chunk)
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError('Cache identity file changed while being checked')
    value = digest.hexdigest()
    if memo:
        with _HASH_LOCK:
            _HASHES[key] = value
    return value


def files_digest(root, paths):
    """Canonical full-content identity with at most four independent hash readers."""
    root = Path(root).resolve()
    eligible = []
    total_bytes = 0
    for path in sorted(paths):
        path = Path(path)
        if path.is_file():
            if not path.resolve().is_relative_to(root):
                raise ValueError('Cache identity file escapes its installation')
            eligible.append((path.relative_to(root).as_posix(), path))
            total_bytes += path.stat().st_size
    # Small launcher/recipe groups keep their cheap ordinary serial path.
    if len(eligible) < 8 or total_bytes < (1 << 20):
        rows = {name: sha(path, memo=True) for name, path in eligible}
    else:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=IDENTITY_HASH_WORKERS,
                                thread_name_prefix='ttm-identity') as executor:
            hashes = executor.map(lambda row: sha(row[1], memo=True), eligible)
            rows = {row[0]: digest for row, digest in zip(eligible, hashes)}
    return hashlib.sha256(canonical(rows)).hexdigest()


def seed_verified_iso(copy, context):
    """Reuse the room's live full-image verifier, never a JSON/hash assertion.

    A verified context owns its reader and freshness lock. Closed contexts,
    replaced files, different paths/discs or arbitrary duck-typed objects cannot
    seed the process-local memo. Regional/codec-less rooms keep full hashing.
    """
    from kit_wire_codec import VerifiedIso
    if type(context) is not VerifiedIso:
        raise ValueError('An owned full-image verifier is required')
    path = Path(copy.iso).resolve()
    with context._lock:
        context._fresh()
        if (context.path.resolve() != path or context.sha256 != copy.install['iso_sha256'] or
                context.adapter.name != copy.install['adapter']):
            raise ValueError('Verified ISO context belongs to different installation media')
        before = path.stat()
        context._fresh()
        after = path.stat()
        stamp = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if stamp(before) != stamp(after):
            raise ValueError('Verified ISO changed while adopting its identity')
        key = (str(path), *stamp(after))
        with _HASH_LOCK:
            _HASHES[key] = context.sha256
    return context.sha256


def semantic_config(path):
    """Keep emulation semantics; exclude machine/UI/PINE/storage bookkeeping.

    The private copy has no real controllers. Keyboard mappings are checked by
    its launcher; only controller type/multitap affects serialized guest state.
    Media/card contents are independently hashed, rather than absolute paths.
    Unknown core/plugin keys remain part of the identity.
    """
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    parser.read_string(Path(path).read_text(encoding='utf-8-sig'))
    result = {}
    for section in parser.sections():
        if section in ('UI', 'Folders', 'Filenames', 'AutoUpdater', 'Logging', 'Hotkeys') or section.startswith(
                ('GameList', 'MainWindow', 'Debugger', 'Achievements')):
            continue
        values = dict(parser[section])
        if section == 'EmuCore':
            values.pop('PINESlot', None)
            values.pop('EnablePINE', None)
        if section == 'EmuCore/GS':
            for key in tuple(values):
                if key.startswith('Osd') or key in ('FullscreenMode',):
                    values.pop(key)
        if section.startswith('Pad') and section[3:].isdigit():
            values = {key: value for key, value in values.items() if key == 'Type'}
        if section == 'MemoryCards':
            for key in tuple(values):
                if key.endswith('_Filename'):
                    values[key] = Path(values[key]).name
        if values:
            result[section] = values
    if result.get('EmuCore/CPU', {}).get('ExtraMemory', '').lower() != 'true':
        raise ValueError('Selector checkpoints require expanded guest memory')
    for backend in ('SDL', 'XInput', 'DInput'):
        if result.get('InputSources', {}).get(backend, 'false').lower() != 'false':
            raise ValueError('Only the isolated keyboard preparation profile can cache selectors')
    return result


def identity(copy):
    """Content-based portable identity of the installed native preparation recipe.

    Offline mod-settings, authored scenarios, reports, paths and version labels
    do not participate. Match settings are applied after every restore. The
    template language does participate because its native menu assets differ.
    """
    import kit_adapter
    import kit_prepare
    import kit_prepare_auto
    import kit_settings
    import kit_prepare_launch
    source = Path(copy.install['root']).resolve() / 'game'
    game = copy.base.dest / 'game'
    runtime = game / 'runtime28'
    guest = [path for path in (source / 'tools').rglob('*') if path.is_file()
             and '__pycache__' not in path.parts and path.suffix.lower() != '.pyc']
    guest += list((source / 'elf').glob('*'))
    guest += list((source / 'runtime28' / 'cheats').glob('*.pnach'))
    binaries = [path for path in runtime.rglob('*') if path.is_file()
                and path.suffix.lower() in ('.exe', '.dll', '.pak', '.qm')]
    profile = kit_adapter.profile(source.parent)
    profile = {key: profile[key] for key in ('schema', 'adapter', 'iso_sha256', 'members', 'serial',
                                            'pcsx2_crc', 'runtime_variant') if key in profile}
    settings = json.loads((game / 'mod-settings.json').read_text(encoding='utf-8'))
    # The recipe is independent of its port number; source text plus the exact
    # unpatched launcher files guards private patch behavior instead.
    recipe = {Path(module.__file__).name: sha(module.__file__, memo=True)
              for module in (kit_prepare, kit_prepare_auto, kit_settings, kit_adapter, kit_prepare_launch)}
    recipe[Path(__file__).name] = sha(__file__, memo=True)
    iso, bios = Path(copy.iso), Path(copy.install['bios'])
    if getattr(copy, 'verified_iso', None) is not None:
        seed_verified_iso(copy, copy.verified_iso)
    config = configparser.ConfigParser(interpolation=None)
    config.read(runtime / 'inis' / 'PCSX2.ini', encoding='utf-8-sig')
    bios_dir = (runtime / config.get('Folders', 'Bios', fallback='bios')).resolve()
    selected_bios = (bios_dir / config.get('Filenames', 'BIOS')).resolve()
    if (not bios_dir.is_relative_to(runtime.resolve()) or not selected_bios.is_relative_to(bios_dir) or
            sha(selected_bios, memo=True) != sha(bios, memo=True)):
        raise ValueError('The private preparation BIOS differs from its verified installation')
    value = dict(schema=SCHEMA, adapter=copy.install['adapter'], profile=profile,
                 iso=dict(size=iso.stat().st_size, sha256=sha(iso, memo=True)),
                 bios=dict(size=bios.stat().st_size, sha256=sha(bios, memo=True)),
                 emulator=files_digest(runtime, binaries), guest=files_digest(source, guest),
                 recipe=hashlib.sha256(canonical(recipe)).hexdigest(),
                 launchers=files_digest(source, [source / name for name in
                           ('launch-autopilot.ps1', 'launcher-lifecycle.ps1')]),
                 config=semantic_config(runtime / 'inis' / 'PCSX2.ini'),
                 template_language=settings.get('language', 'en'),
                 cards={path.name: sha(path, memo=True) for path in sorted((runtime / 'memcards').glob('*.ps2'))})
    if value['iso']['sha256'] != copy.install['iso_sha256']:
        raise ValueError('ISO identity differs from the verified installation')
    return value


def archive_payload(path):
    """Bound the archive before decoding and verify every entry's size and CRC."""
    from state128 import read_entry, VERSION, INTERNAL
    from patch_state import inspect_payload
    path = Path(path)
    if not 0 < path.stat().st_size <= MAX_ARCHIVE:
        raise ValueError('Selector archive exceeds its storage bound')
    with zipfile.ZipFile(path) as archive, path.open('rb') as raw:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if (not 0 < len(infos) <= MAX_ENTRIES or len(names) != len(set(names)) or
                any(len(name) > 160 or '/' in name or '\\' in name or name in ('.', '..') for name in names) or
                any(info.file_size < 0 or info.file_size > RAM_BYTES or info.flag_bits & 1 for info in infos) or
                sum(info.file_size for info in infos) > MAX_UNCOMPRESSED):
            raise ValueError('Invalid or oversized selector archive inventory')
        if not {VERSION, INTERNAL, 'eeMemory.bin'}.issubset(names):
            raise ValueError('Selector archive is missing native state entries')
        payload = {}
        for info in infos:
            data = read_entry(archive, raw, info)
            if len(data) != info.file_size or binascii.crc32(data) & 0xffffffff != info.CRC:
                raise ValueError('Selector archive entry length or CRC differs')
            payload[info.filename] = data
    memory = payload['eeMemory.bin']
    if len(memory) != RAM_BYTES:
        raise ValueError('Selector archive does not contain expanded guest memory')
    layout = inspect_payload(payload[VERSION], payload[INTERNAL], len(memory))
    return memory, dict(version_hex=payload[VERSION].hex(), layout=layout,
                       entries={name: hashlib.sha256(data).hexdigest() for name, data in payload.items()})


def code_signature(memory):
    import native_mode_menu as menu
    rows = []
    for address, data in menu.code_pieces():
        if bytes(memory[address:address + len(data)]) != data:
            raise ValueError(f'Native mode receipt code differs at {address:#x}')
        rows.append((address, len(data), hashlib.sha256(data).hexdigest()))
    return hashlib.sha256(canonical(rows)).hexdigest()


def _current_code_recipe():
    """Small current native-code identity; no decoded archive/RAM is retained."""
    import native_mode_menu as menu
    rows = [(address, len(data), hashlib.sha256(data).hexdigest())
            for address, data in menu.code_pieces()]
    return hashlib.sha256(canonical(rows)).hexdigest()


def selector(memory, engine):
    from kit_prepare_auto import MANAGER, TEAM_OBJECT, LOOP, SIDES, TEAM_SELECT
    import native_mode_menu as menu
    import menu_return
    import kit_adapter
    if engine not in ('teams', 'ffa') or len(memory) != RAM_BYTES:
        raise ValueError('Unknown selector engine or guest layout')
    menu_return.validate_clean(memory, 'character_select', TEAM_SELECT)
    u = lambda address: struct.unpack('<I', memory[address:address + 4])[0]
    manager, obj = u(MANAGER), u(TEAM_OBJECT)
    if not (0x100000 <= manager <= 0x2000000 - 0x634 and manager % 4 == 0 and
            0x100000 <= obj <= 0x2000000 - 0x3c70 and obj % 4 == 0):
        raise ValueError('Invalid native selector object ownership')
    if (u(manager + 0x18), u(LOOP), u(obj + 0x3c6c)) != (TEAM_SELECT, 0, 1):
        raise ValueError('Checkpoint is not a neutral native map selector')
    # The pager leaves its old expiry counter behind in state 0. Its guest
    # hook reads the lease only in states 1/2; a leftover counter is not a lease.
    if tuple(u(menu.CONTROL + offset) for offset in (0, 4, 12)) != (menu.MAGIC, 0, 0):
        raise ValueError('Checkpoint has an outstanding menu lease or choice')
    sides = []
    for index, offset in enumerate(SIDES):
        if u(obj + 0x8e8 + 4 * index) != obj + offset or u(obj + offset + 0x134) != 1:
            raise ValueError('Selector must own one native fighter per side')
        character, costume = u(obj + offset + 0x18), u(obj + offset + 0x10)
        if not 0 <= character < kit_adapter.roster_count() or not 0 <= costume <= 7:
            raise ValueError('Invalid selector fighter or costume')
        sides.append(dict(count=1, character=character, costume=costume))
    if not 0 <= u(obj + 0x98c) < kit_adapter.stage_count():
        raise ValueError('Invalid selector stage')
    return dict(manager=manager, object=obj, scene=TEAM_SELECT, loop=0, stage_select=1,
                sides=sides, engine=engine, choice=menu.SELECTIONS.index((engine, 1)),
                native_code_sha256=code_signature(memory))


class LiveMemory:
    def __init__(self, client):
        self.client = client

    def __len__(self):
        return RAM_BYTES

    def __getitem__(self, span):
        if (not isinstance(span, slice) or span.step is not None or
                not 0 <= span.start <= span.stop <= RAM_BYTES):
            raise ValueError('Contiguous bounded live read required')
        return self.client.read(span.start, span.stop - span.start)


def _read_json(path):
    path = Path(path)
    if path.stat().st_size > MAX_METADATA:
        raise ValueError('Selector metadata exceeds its bound')
    return json.loads(path.read_text(encoding='utf-8'))


def _boot_path(private_root, path):
    private_root, path = Path(private_root).resolve(), Path(path).resolve()
    states = (private_root / 'game/runtime28/sstates').resolve()
    if (private_root.name != 'Tag Team Mod' or private_root.parent.name != 'prep' or
            not states.is_relative_to(private_root) or path.parent != states or
            not path.name.startswith('.ttm-selector-boot-') or path.suffix != '.p2s'):
        raise ValueError('Selector boot archive is outside the private preparation save folder')
    return path


def validate_boot(descriptor, private_root, identity_value, *, inflate=True):
    """Authenticate a staged startup archive again in its launcher interpreter.

    A pathname/hash supplied by a caller is not authorization. The locally held
    selector key signs the original fully validated record and the exact private
    staging path. Staging fully checks every native entry, CRC/layout and code.
    Later boundaries may bind those already checked bytes by full SHA without
    repeatedly inflating the same 128MiB. This still requires the signed local
    record, exact media/config identity, bounded archive and file freshness.
    """
    if (not isinstance(descriptor, dict) or set(descriptor) != {'claim', 'mac'} or
            len(canonical(descriptor)) > MAX_METADATA):
        raise ValueError('Invalid selector boot descriptor')
    claim, mac = descriptor['claim'], descriptor['mac']
    if (not isinstance(claim, dict) or claim.get('schema') != SCHEMA or
            claim.get('engine') not in ('teams', 'ffa') or claim.get('identity') != identity_value):
        raise ValueError('Selector boot identity or engine differs')
    root = Path(private_root).resolve()
    cache_folder = (root.parent / 'native-selector-cache').resolve()
    if Path(claim.get('cache_folder', '')).resolve() != cache_folder:
        raise ValueError('Selector boot authentication key is outside its private cache')
    key = (cache_folder / 'private-authentication.key').read_bytes()
    if len(key) != 32:
        raise ValueError('Invalid local selector authentication key')
    expected = hmac.new(key, canonical(claim), hashlib.sha256).hexdigest()
    if not isinstance(mac, str) or not hmac.compare_digest(mac, expected):
        raise ValueError('Selector boot descriptor authentication failed')
    path = _boot_path(root, claim.get('state_path', ''))
    record = claim.get('record', {})
    if (record.get('schema') != SCHEMA or record.get('identity') != identity_value or
            record.get('selector', {}).get('engine') != claim['engine']):
        raise ValueError('Selector boot record differs from its signed identity')
    if not 0 < path.stat().st_size <= MAX_ARCHIVE:
        raise ValueError('Selector boot archive exceeds its storage bound')
    if sha(path) != record.get('state_sha256'):
        raise ValueError('Selector boot archive checksum differs')
    if inflate:
        memory, archive = archive_payload(path)
        if archive != record.get('archive') or selector(memory, claim['engine']) != record.get('selector'):
            raise ValueError('Selector boot archive validation differs')
    return path


class OccupiedBootHooks(ValueError):
    """An unrelated private cheat is never replaced by a cached hook payload."""


def _hook_bytes(path, size, digest):
    """Read a bounded artifact and bind its complete bytes, not its file stats."""
    if type(size) is not int or not 0 < size <= MAX_BOOT_HOOKS or \
            not isinstance(digest, str) or len(digest) != 64 or \
            any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Invalid generated boot-hook size or checksum')
    path = Path(path)
    if path.stat().st_size != size:
        raise ValueError('Generated boot-hook size differs')
    with path.open('rb') as stream:
        data = stream.read(MAX_BOOT_HOOKS + 1)
    if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError('Generated boot-hook checksum differs')
    return data


def install_boot_hooks(descriptor, private_root, identity_value):
    """Install only the exact locally generated hooks signed with this selector.

    Missing legacy metadata requests ordinary guarded generation. Any malformed
    or changed cache is rejected before a write; the launcher can regenerate
    from its pinned native source. Unrelated occupied files remain errors.
    """
    validate_boot(descriptor, private_root, identity_value, inflate=False)
    root = Path(private_root).resolve()
    claim = descriptor['claim']
    hook = claim['record'].get('boot_hooks')
    if hook is None:
        return False
    if not isinstance(hook, dict) or set(hook) != {'schema', 'filename', 'size', 'sha256'} or hook['schema'] != 1:
        raise ValueError('Invalid generated boot-hook descriptor')
    import game_profile
    from native_map import SERIAL
    filename = game_profile.cheat_name(SERIAL)
    if hook['filename'] != filename or Path(filename).name != filename or not filename.endswith('.pnach'):
        raise ValueError('Generated boot-hook filename differs from the native profile')
    cache_root = root.parent / 'native-selector-cache'
    folder = cache_root / hashlib.sha256(canonical(identity_value)).hexdigest()
    source = folder / ('boot-hooks-' + str(hook['sha256']) + '.pnach')
    if folder.resolve().parent != cache_root.resolve() or source.resolve().parent != folder.resolve():
        raise ValueError('Generated boot-hook cache path escapes its identity folder')
    data = _hook_bytes(source, hook['size'], hook['sha256'])
    cheats = root / 'game/runtime28/cheats'
    target = cheats / filename
    receipt = target.with_suffix('.owned-sha256')
    if (not cheats.resolve().is_relative_to(root) or target.resolve().parent != cheats.resolve() or
            receipt.resolve().parent != cheats.resolve()):
        raise ValueError('Generated boot-hook destination escapes its private installation')
    cheats.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    previous = None
    if existed:
        if not 0 < target.stat().st_size <= MAX_BOOT_HOOKS:
            raise OccupiedBootHooks(f'Loading hook file is occupied: {target}')
        with target.open('rb') as stream:
            previous = stream.read(MAX_BOOT_HOOKS + 1)
        if previous != data:
            owned = receipt.read_text().strip() if receipt.exists() and receipt.stat().st_size <= 65 else ''
            if hashlib.sha256(previous).hexdigest() != owned:
                raise OccupiedBootHooks(f'Loading hook file is occupied: {target}')
    if previous != data:
        # The private launcher lease serializes our writers. Also refuse a
        # newly occupied destination instead of replacing a file that appeared
        # after the original ownership check. Atomic link publishes new files
        # without the partial-write interval of opening the destination 'xb'.
        if existed:
            try:
                _hook_bytes(target, len(previous), hashlib.sha256(previous).hexdigest())
            except (OSError, ValueError) as error:
                raise OccupiedBootHooks(f'Loading hook file changed: {target}') from error
        try:
            SelectorCache._atomic(target, lambda stream: stream.write(data), replace=existed)
        except FileExistsError as error:
            raise OccupiedBootHooks(f'Loading hook file is occupied: {target}') from error
    if sha(target) != hook['sha256']:
        raise ValueError('Installed generated boot hooks changed during readback')
    SelectorCache._atomic(receipt, lambda stream: stream.write((hook['sha256'] + '\n').encode()))
    return dict(sha256=hook['sha256'], bytes=hook['size'])


def _owner(copy):
    import kit_paths
    import kit_win
    copy.check()
    dest = copy.base.dest.resolve()
    expected = (kit_paths.PREP / 'Tag Team Mod').resolve()
    exe = dest / 'game/runtime28/pcsx2-qt.exe'
    pid = copy.base.pid
    if (dest != expected or not copy.base.desktop or not pid or not kit_win.pid_alive(pid) or
            kit_win.listener_pid(copy.slot) != pid or
            Path(kit_win.process_path(pid)).resolve() != exe.resolve()):
        raise ValueError('Selector operation does not own the isolated preparation emulator')
    return pid


class WatchLease:
    """Captured current watcher, including launcher and emulator instance identity."""
    def __init__(self, copy, folder):
        folder = Path(folder).resolve()
        root = (copy.base.dest / 'game/analysis/autopilot').resolve()
        if not folder.is_relative_to(root) or folder == root:
            raise ValueError('Watcher receipt is outside the private preparation copy')
        self.folder = folder
        self.status = folder / 'status.json'
        self.bound = None
        value = self.read(copy)
        if not isinstance(value.get('native_mode_receipt'), dict):
            raise ValueError('Private watcher does not provide structured native mode receipts')

    def read(self, copy):
        import kit_win
        pid = _owner(copy)
        value = _read_json(self.status)
        binding = tuple(value.get(key) for key in ('pid', 'launcher_token', 'emulator_pid', 'emulator_created'))
        if (not isinstance(binding[0], int) or binding[0] <= 0 or not kit_win.pid_alive(binding[0]) or
                not isinstance(binding[1], str) or len(binding[1]) < 16 or binding[2] != pid or
                not isinstance(binding[3], (float, int)) or binding[3] <= 0):
            raise ValueError('Watcher does not own this live preparation instance')
        if self.bound is not None and binding != self.bound:
            raise ValueError('Private watcher instance changed during selector restoration')
        self.bound = binding
        if value.get('state') == 'FAILED':
            raise RuntimeError('Private watcher failed during selector restoration')
        return value


def find_watcher(copy, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        _owner(copy)
        folder = copy.base.dest / 'game/analysis/autopilot'
        for candidate in sorted(folder.glob('*'), key=lambda path: path.stat().st_mtime, reverse=True):
            if candidate.is_dir():
                try:
                    return WatchLease(copy, candidate)
                except (OSError, ValueError):
                    pass
        copy.sleep(.05)
    raise ValueError('Current private watcher did not publish its ownership receipt')


def mode_receipt(status, engine, *, after=-1):
    import native_mode_menu as menu
    value = status.get('native_mode_receipt', {})
    epoch = value.get('epoch')
    return (status.get('battle_mode') == engine and status.get('humans') == 1 and
            isinstance(epoch, int) and epoch > after and value.get('custom') is True and
            value.get('choice') == menu.SELECTIONS.index((engine, 1)))


def _startup_menu_frame(client):
    """Read the audited pad hook's counter, only after verifying its code."""
    import native_mode_menu as menu
    pieces = menu.old.code_pieces()[:1]
    if (not pieces or pieces[0][0] != menu.old.CODE or
            any(client.read(address, len(data)) != data for address, data in pieces)):
        raise ValueError('Native menu frame counter code differs')
    return client.read_u32(menu.old.CONTROL + menu.old.FIELDS['frames'])


class SelectorCache:
    def __init__(self, folder=None):
        if folder is None:
            import kit_paths
            folder = kit_paths.PREP / 'native-selector-cache'
        self.folder = Path(folder).resolve()
        self.folder.mkdir(parents=True, exist_ok=True)
        key_path = self.folder / 'private-authentication.key'
        try:
            fd = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(secrets.token_bytes(32)); stream.flush(); os.fsync(stream.fileno())
        end = time.monotonic() + 1
        while True:
            self.key = key_path.read_bytes()
            if len(self.key) == 32:
                break
            if time.monotonic() >= end:
                raise ValueError('Invalid local selector authentication key')
            time.sleep(.01)

    def paths(self, engine, identity_value):
        if engine not in ('teams', 'ffa'):
            raise ValueError('Unknown selector engine')
        key = hashlib.sha256(canonical(identity_value)).hexdigest()
        folder = self.folder / key
        folder.mkdir(exist_ok=True)
        if folder.resolve().parent != self.folder:
            raise ValueError('Selector cache path escapes its root')
        return folder / (engine + '.p2s'), folder / (engine + '.json')

    @contextmanager
    def _lock(self, engine, identity_value):
        path, _ = self.paths(engine, identity_value)
        with path.with_suffix('.lock').open('a+b') as stream:
            if stream.tell() == 0:
                stream.write(b'\0'); stream.flush()
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)

    @staticmethod
    def _atomic(path, writer, *, replace=True):
        temporary = None
        try:
            fd, name = tempfile.mkstemp(prefix='.ttm-selector-', dir=path.parent)
            temporary = Path(name)
            with os.fdopen(fd, 'wb') as stream:
                writer(stream); stream.flush(); os.fsync(stream.fileno())
            if replace:
                os.replace(temporary, path)
            else:
                os.link(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def publish(self, source, engine, identity_value, lease, copy):
        with copy.lock, self._lock(engine, identity_value):
            current = lease.read(copy)
            if current.get('state') != 'MENU' or not mode_receipt(current, engine, after=0):
                raise ValueError('A genuine current native mode receipt is required to cache a selector')
            if not copy.at_map_select():
                raise ValueError('Private game is not at its neutral selector')
            source = Path(source).resolve()
            state_root = (copy.base.dest / 'game/runtime28/sstates').resolve()
            if not source.is_relative_to(state_root):
                raise ValueError('Only a locally captured private selector may be cached')
            memory, archive = archive_payload(source)
            proof = selector(memory, engine)
            with copy.pine() as client:
                if selector(LiveMemory(client), engine) != proof:
                    raise ValueError('Captured selector does not match the owned live selector')
            target, metadata = self.paths(engine, identity_value)
            # Pay generation once when publishing an owned genuine template.
            # Never sign a hash from an editable .owned-sha256 receipt alone.
            import guest_loading_screen
            import game_profile
            from native_map import SERIAL
            filename = game_profile.cheat_name(SERIAL)
            if Path(filename).name != filename or not filename.endswith('.pnach'):
                raise ValueError('Invalid generated boot-hook filename')
            generated = guest_loading_screen.pnach()
            if not isinstance(generated, bytes) or not 0 < len(generated) <= MAX_BOOT_HOOKS:
                raise ValueError('Generated boot hooks exceed their storage bound')
            digest = hashlib.sha256(generated).hexdigest()
            installed = copy.base.dest / 'game/runtime28/cheats' / filename
            if installed.resolve().parent != (copy.base.dest / 'game/runtime28/cheats').resolve() or \
                    not installed.resolve().is_relative_to(copy.base.dest.resolve()):
                raise ValueError('Generated boot-hook source escapes its private installation')
            if _hook_bytes(installed, len(generated), digest) != generated:
                raise ValueError('Private boot hooks differ from the pinned native recipe')
            hook_file = target.parent / ('boot-hooks-' + digest + '.pnach')
            self._atomic(hook_file, lambda stream: stream.write(generated))
            if _hook_bytes(hook_file, len(generated), digest) != generated:
                raise ValueError('Published generated boot hooks differ after readback')
            boot_hooks = dict(schema=1, filename=filename, size=len(generated), sha256=digest)
            def copy_archive(stream):
                with source.open('rb') as original:
                    shutil.copyfileobj(original, stream, 1 << 20)
            self._atomic(target, copy_archive)
            record = dict(schema=SCHEMA, identity=identity_value, selector=proof, archive=archive,
                          state_sha256=sha(target), created=time.time(), boot_hooks=boot_hooks)
            mac = hmac.new(self.key, canonical(record), hashlib.sha256).hexdigest()
            self._atomic(metadata, lambda stream: stream.write(canonical(dict(record=record, mac=mac))))
            return record

    def _record(self, engine, identity_value):
        path, metadata = self.paths(engine, identity_value)
        value = _read_json(metadata)
        record, mac = value['record'], value['mac']
        expected = hmac.new(self.key, canonical(record), hashlib.sha256).hexdigest()
        if not isinstance(mac, str) or not hmac.compare_digest(mac, expected):
            raise ValueError('Selector metadata authentication failed')
        if record['schema'] != SCHEMA or record['identity'] != identity_value:
            raise ValueError('Selector media/build/configuration changed')
        return path, record

    def _validate(self, engine, identity_value):
        path, record = self._record(engine, identity_value)
        if not 0 < path.stat().st_size <= MAX_ARCHIVE:
            raise ValueError('Selector archive exceeds its storage bound')
        digest = sha(path)  # Every boundary reads the full archive, never a stat-only hash memo.
        if digest != record['state_sha256']:
            raise ValueError('Selector archive checksum differs')
        key = (str(path.resolve()), engine, hashlib.sha256(canonical(record)).hexdigest(),
               digest, hashlib.sha256(canonical(identity_value)).hexdigest(), _current_code_recipe())
        with _VALIDATION_LOCK:
            if key in _VALIDATED_ARCHIVES:
                _VALIDATED_ARCHIVES.move_to_end(key)
                return path, record
        memory, archive = archive_payload(path)
        if archive != record['archive'] or selector(memory, engine) != record['selector']:
            raise ValueError('Selector archive validation differs')
        if sha(path) != digest:
            raise ValueError('Selector archive changed during native validation')
        # HMAC/identity/bounds and a fresh full SHA are still checked above on
        # every call. Identical bytes already proved in this interpreter need
        # not repeatedly inflate 128MiB. Keep only bounded scalar identities.
        with _VALIDATION_LOCK:
            _VALIDATED_ARCHIVES[key] = True
            _VALIDATED_ARCHIVES.move_to_end(key)
            while len(_VALIDATED_ARCHIVES) > MAX_VALIDATED_ARCHIVES:
                _VALIDATED_ARCHIVES.popitem(last=False)
        return path, record

    def validate(self, engine, identity_value):
        with self._lock(engine, identity_value):
            return self._validate(engine, identity_value)

    def available(self, engine, identity_value):
        try:
            self.validate(engine, identity_value)
            return True
        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
            return False

    def stage_boot(self, copy, engine, identity_value):
        """Stage one authenticated checkpoint before starting a fresh private VM."""
        import kit_paths
        with copy.lock, self._lock(engine, identity_value):
            copy.check()
            root = copy.base.dest.resolve()
            if (root != (kit_paths.PREP / 'Tag Team Mod').resolve() or not copy.base.desktop or
                    copy.base.pid is not None or self.folder != (root.parent / 'native-selector-cache').resolve()):
                raise ValueError('Selector startup requires a fresh isolated preparation copy')
            source, record = self._validate(engine, identity_value)
            target = root / 'game/runtime28/sstates' / ('.ttm-selector-boot-' + secrets.token_hex(16) + '.p2s')
            target.parent.mkdir(parents=True, exist_ok=True)
            _boot_path(root, target)
            def write(stream):
                with source.open('rb') as original:
                    shutil.copyfileobj(original, stream, 1 << 20)
            self._atomic(target, write)
            claim = dict(schema=SCHEMA, engine=engine, identity=identity_value,
                         state_path=str(target.resolve()), cache_folder=str(self.folder), record=record)
            return dict(claim=claim, mac=hmac.new(self.key, canonical(claim), hashlib.sha256).hexdigest())

    def restore_boot(self, copy, engine, identity_value, lease, descriptor, timeout=45):
        """Authorize the VM's startup checkpoint without loading it a second time.

        PCSX2's -statefile startup restores the archive before guest execution.
        Its fresh watcher/launcher receipt and exact live selector are required;
        serialized guest state never supplies Python ownership or a mode epoch.
        """
        import native_mode_menu as menu
        from native_map import SERIAL, CRC
        start, end = time.monotonic(), time.monotonic() + timeout
        with copy.lock, self._lock(engine, identity_value):
            _owner(copy)
            path = validate_boot(descriptor, copy.base.dest, identity_value, inflate=False)
            original, record = self._record(engine, identity_value)
            if not 0 < original.stat().st_size <= MAX_ARCHIVE or sha(original) != record['state_sha256']:
                raise ValueError('Current authenticated selector archive changed')
            if descriptor['claim']['engine'] != engine or descriptor['claim']['record'] != record:
                raise ValueError('Startup selector differs from the current authenticated cache')
            baseline = lease.read(copy)
            if baseline.get('state') != 'MENU':
                raise ValueError('A fresh menu watcher is required to authorize a startup selector')
            request = _read_json(lease.folder / 'private-launch.json')
            if (request.get('selector_boot') != descriptor or request.get('identity') != identity_value or
                    request.get('token') != baseline.get('launcher_token') or request.get('slot') != copy.slot or
                    Path(request.get('root', '')).resolve() != copy.base.dest.resolve() or
                    Path(request.get('iso', '')).resolve() != Path(copy.iso).resolve()):
                raise ValueError('Current owned launcher did not start this authenticated selector')
            validation = time.monotonic() - start
            clean = None
            while time.monotonic() < end:
                current = lease.read(copy)
                if current.get('state') == 'MENU' and copy.at_map_select():
                    with copy.pine() as client:
                        _owner(copy)
                        info = client.require_game(serial=SERIAL, crc=CRC)
                        # PINE publishes the game identity and parts of EE RAM
                        # during -statefile initialization while Qt still has
                        # the VM paused. Only Running follows completion of
                        # that load; do not inspect or commit partial controls.
                        if info.get('status') != 'running':
                            copy.sleep(.05)
                            continue
                        if selector(LiveMemory(client), engine) != record['selector']:
                            raise ValueError('Startup live selector differs from its authenticated template')
                    clean = current
                    break
                copy.sleep(.05)
            if clean is None:
                raise ValueError('Private VM did not finish its authenticated selector startup')
            previous_epoch = clean.get('native_mode_receipt', {}).get('epoch')
            if not isinstance(previous_epoch, int):
                raise ValueError('Private watcher has no structured native epoch')
            with copy.pine() as client:
                _owner(copy)
                if client.require_game(serial=SERIAL, crc=CRC).get('status') != 'running':
                    raise ValueError('Private startup game paused before native authorization')
                first_frame = _startup_menu_frame(client)
                # The full live proof above also requires no outstanding lease.
                client.write_u32(menu.CONTROL + 16, 0)
                client.write_u32(menu.CONTROL + 12, record['selector']['choice'] + 1)
                client.write_u32(menu.CONTROL + 4, 3)
            acknowledged = None
            while time.monotonic() < end:
                current = lease.read(copy)
                if current.get('state') == 'MENU' and mode_receipt(current, engine, after=previous_epoch):
                    with copy.pine() as client:
                        consumed = client.read_u32(menu.CONTROL + 12) == client.read_u32(menu.CONTROL + 4) == 0
                        running = client.require_game(serial=SERIAL, crc=CRC).get('status') == 'running'
                        progressed = client.read_u32(menu.old.CONTROL + menu.old.FIELDS['frames']) != first_frame
                    if consumed and running and progressed and copy.at_map_select():
                        acknowledged = current['native_mode_receipt']
                        break
                copy.sleep(.05)
            if acknowledged is None:
                raise ValueError('Current private watcher did not authorize the startup selector')
            copy.engine, copy.state, copy.settings_written = engine, 'warm', None
            path.unlink(missing_ok=True)
            return dict(validation_seconds=round(validation, 3),
                        restore_and_authorization_seconds=round(time.monotonic() - start, 3),
                        bootstrap_code_wait_seconds=0, queued_load_canary=False, direct_state_boot=True,
                        native_mode_receipt=acknowledged, loaded_game=info)

    def restore(self, copy, engine, identity_value, lease, timeout=45, *, boot=None):
        """Restore before logos or from an idle native game; never while a prep worker owns it.

        For a post-export reset the caller first waits for watcher ACTIVE, which
        means its preparation session and borrowed slots have been released.
        The subsequent MENU acknowledgement below waits for worker cleanup.
        """
        if boot is not None:
            return self.restore_boot(copy, engine, identity_value, lease, boot, timeout)
        import kit_adapter
        import native_mode_menu as menu
        from native_map import SERIAL, CRC
        start = time.monotonic()
        end = start + timeout
        with copy.lock, self._lock(engine, identity_value):
            _owner(copy)
            path, record = self._validate(engine, identity_value)
            validation = time.monotonic() - start
            baseline = lease.read(copy)
            if baseline.get('state') not in ('MENU', 'ACTIVE'):
                raise ValueError('An active preparation worker still owns the private game')
            target = copy.base.dest / 'game/runtime28/sstates' / kit_adapter.state_name(RESTORE_SLOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            self._atomic(target, lambda stream: stream.write(path.read_bytes()))
            # PINE is available before the first boot-cheat application. Loading
            # sooner lets the later bootstrap clear serialized native controls.
            boot = time.monotonic()
            while time.monotonic() < end:
                lease.read(copy)
                try:
                    with copy.pine() as client:
                        info = client.info()
                        if info.get('status') != 'shutdown':
                            client.require_game(serial=SERIAL, crc=CRC)
                            pieces = menu.code_pieces()
                            actual = client.read_ranges([(address, len(data)) for address, data in pieces])
                            if all(value == data for value, (_, data) in zip(actual, pieces)):
                                break
                except OSError:
                    pass
                copy.sleep(.05)
            else:
                raise ValueError('Private game did not finish its guarded code bootstrap')
            bootstrap_seconds = time.monotonic() - boot
            with copy.pine(timeout=30) as client:
                _owner(copy)
                info = client.require_game(serial=SERIAL, crc=CRC)
                words = tuple(client.read_u32(menu.CONTROL + offset) for offset in (0, 4, 12))
                if words not in ((0, 0, 0), (menu.MAGIC, 0, 0)):
                    raise ValueError('Only an unleased private game may restore a selector')
                # Inactive result canary: both engine selectors use the same
                # pointers. Only a completed archive load clears this marker.
                client.write_u32(menu.CONTROL + 12, 0xffffffff)
                client.load_state(RESTORE_SLOT)
            clean = None
            while time.monotonic() < end:
                current = lease.read(copy)
                if current.get('state') == 'MENU' and copy.at_map_select():
                    with copy.pine() as client:
                        words = tuple(client.read_u32(menu.CONTROL + offset) for offset in (0, 4, 12))
                    if words == (menu.MAGIC, 0, 0):
                        clean = current
                        break
                copy.sleep(.05)
            if clean is None:
                raise ValueError('Private watcher did not finish the cached clean-menu transition')
            previous_epoch = clean.get('native_mode_receipt', {}).get('epoch')
            if not isinstance(previous_epoch, int):
                raise ValueError('Private watcher has no structured native epoch')
            with copy.pine() as client:
                _owner(copy)
                client.require_game(serial=SERIAL, crc=CRC)
                if selector(LiveMemory(client), engine) != record['selector']:
                    raise ValueError('Loaded live selector differs from its authenticated template')
                client.write_u32(menu.CONTROL + 16, 0)
                client.write_u32(menu.CONTROL + 12, record['selector']['choice'] + 1)
                client.write_u32(menu.CONTROL + 4, 3)  # native semantic commit, state last
            acknowledged = None
            while time.monotonic() < end:
                current = lease.read(copy)
                if current.get('state') == 'MENU' and mode_receipt(current, engine, after=previous_epoch):
                    with copy.pine() as client:
                        consumed = client.read_u32(menu.CONTROL + 12) == client.read_u32(menu.CONTROL + 4) == 0
                    if consumed and copy.at_map_select():
                        acknowledged = current['native_mode_receipt']
                        break
                copy.sleep(.05)
            if acknowledged is None:
                raise ValueError('Current private watcher did not authorize the restored selector')
            copy.engine, copy.state, copy.settings_written = engine, 'warm', None
            return dict(validation_seconds=round(validation, 3),
                        restore_and_authorization_seconds=round(time.monotonic() - start, 3),
                        bootstrap_code_wait_seconds=round(bootstrap_seconds, 3),
                        queued_load_canary=True, native_mode_receipt=acknowledged, loaded_game=info)
