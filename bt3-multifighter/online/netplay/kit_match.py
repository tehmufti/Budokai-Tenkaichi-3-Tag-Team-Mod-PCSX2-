"""Online match files of kit 2.0.

Every match is made on the spot by the host's private installation copy (kit_prepare_auto) from the lobby's spec:
there are no saved or bundled matches. The copy's playable checkpoint (the mod's own: the prepared match held just
before its intro, its start request set, playable without the mod's watcher) is converted (kit_prepare) and gets
netplay_core layout 4 and netplay_view layout 4 (build_netplay):
  * lockstep from the first update after the load (start_state ANY): the intro, the fight, the K.O. and the win quote
    all run in lockstep (the voice gate makes the intro's and the win quote's voice-stream waits agreed);
  * DECIDED when the director reaches the result menu (END_STATE, state 6); from then on every pad reads neutral
    (OPT_NEUTRAL_END): the game waits in its result menu and the kit runs Retry / Return to lobby;
  * the slot mask of the match's players (none: slot 0, which the host then feeds with neutral input); kit 2.1: slot
    s plays the fighter of physical index s (netplay_core SEATS / RESOLVE, OPT_SEATS), any of the ten;
  * input delay 1, a 5-minute stall limit: netplay_state() makes the file for the real input delay by rewriting
    CONTROL.delay / .max_stall (guarded, standard library only).
That file travels (SHA-256 checked) and both PCs keep it in states/ (the host by its inputs, a guest by SHA-256).
Each PC then plays its own PER-MACHINE copy (machine_copy): netplay_core local_slot / self_feed (its player slot, or
none: a spectator), netplay_view's watched side (a spectator's choice) and its own display settings
(kit_settings.LOCAL), every word guarded and never hashed. The first match starts PCSX2 with that copy; Retry and
every later match PINE-load a copy into the running PCSX2 (save slot 241) and attach late.
"""
import hashlib
import json
import shutil
import threading
import time
from pathlib import Path

import kit_paths
import kit_state
from kit_codes import KitError
from kit_ident import sha256_file

BUILT_DELAY, BUILT_MAX_STALL = 1, 18000
DEFAULT_MAX_STALL = 18000                    # vblanks (5 minutes) a game waits for the other PCs before it gives up
MADE_KEEP = 12                               # made matches kept in matches/ (newest)
QUEUE_CONTROL = 0x07367000                   # selected_resource_queue.CONTROL: +0 installed, +4 status (5 = done)
REMATCH_SLOT = 241
_STATE_LOCKS = {}
_STATE_LOCKS_GUARD = threading.Lock()


def _state_lock(output):
    """One process-local owner per immutable cache output, including its .part."""
    key = Path(output).resolve()
    with _STATE_LOCKS_GUARD:
        lock = _STATE_LOCKS.get(key)
        if lock is None:
            lock = _STATE_LOCKS[key] = threading.Lock()
        return lock


def queue_problem(words):
    """None when the mod's selected-resource queue is idle in a state ({address: u32} of QUEUE_CONTROL, +4)."""
    installed, status = words[QUEUE_CONTROL], words[QUEUE_CONTROL + 4]
    if installed and status != 5:
        return (f'the mod is still loading the extra fighters\' models in this save (resource queue status {status}, '
                'not 5)')
    return None


def control_words():
    import netplay_core as nc
    return nc.CONTROL + nc.F['delay'], nc.CONTROL + nc.F['max_stall']


def current_table():
    """(bytes, sha256) of the kit's hash TABLE (data/hash-table.json; kit 2.1 inside an installation: built from the
    installation's own modules, which every PC of a room shares)."""
    if kit_paths.INTEGRATED or kit_paths.ADAPTER != 'bt3-usa':
        import netplay_core as nc
        import netplay_state_hash as nh
        import netplay_view as nv
        table = nh.table_bytes(rows=nc.table_rows('lean', nv.hash_rows()))
        return table, hashlib.sha256(table).hexdigest()
    data = json.loads((kit_paths.NETPLAY / 'data' / 'hash-table.json').read_text(encoding='utf-8'))
    table = bytes.fromhex(data['hex'])
    if hashlib.sha256(table).hexdigest() != data['sha256']:
        raise KitError('TTM-NET-25', what='netplay/data/hash-table.json is damaged.')
    return table, data['sha256']


def core_options(mask, max_stall=BUILT_MAX_STALL):
    """netplay_core options of every kit 2.0 match (see the module text)."""
    import netplay_core as nc
    import netplay_view as nv
    options = nc.OPT_NEUTRAL_END | nc.OPT_VOICE | nc.OPT_SCHED | nc.OPT_SEATS      # layout 4: ten slots
    return dict(mode=nc.LOCKSTEP, delay=BUILT_DELAY, max_stall=max_stall, profile='lean', start_state=nc.ANY,
                after_state=nc.ANY, end_rule=nc.END_STATE, end_state=nc.RESULT_MENU, mask=mask or 1, options=options,
                extra_rows=nv.hash_rows())


def _combined_manifest(original, prefix_manifest, prefix_ram, manifest):
    """Combine two individually validated, sequential edits against the source.

    Core/view edits may replace bytes already written by preparation. Each
    stage retains its own guards; the final archive then guards the original
    bytes across the union of their ranges, and writes the final bytes once.
    """
    import patch_state
    final_ram, _ = patch_state.patch_memory(prefix_ram, manifest)
    _, prefix = patch_state.load_manifest(prefix_manifest)
    _, final = patch_state.load_manifest(manifest)
    ranges = sorted((a, a + len(data)) for a, _, data, _ in prefix + final)
    merged = []
    for start, end in ranges:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return dict(serial=manifest['serial'], crc=manifest['crc'],
                ram_sha256=prefix_manifest['ram_sha256'],
                blocks=[dict(address=start, expected_hex=bytes(original[start:end]).hex(),
                             data_hex=bytes(final_ram[start:end]).hex()) for start, end in merged])


def build_netplay(base, out, mask, spec=None, *, prefix_blocks=None, source_ram=None):
    """Install netplay_core (layout 4) and netplay_view into a single-view match savestate (patch_state, guarded
    blocks). Needs the mod modules' packages (numpy, Pillow; zstandard for a PCSX2-compressed source): the host runs
    it with its installation copy's Python. Optional preparation blocks are
    validated first in memory, then combined with the netplay guards so only
    one fully verified archive is written. source_ram is the caller's already
    read source image; its full hash must still match the source archive."""
    import netplay_core as nc
    import netplay_view as nv
    import patch_state
    from camera_snapshot import read_ram
    out = Path(out)
    patch_state.OUTPUT_ROOT = out.parent
    options = core_options(mask)
    ram = read_ram(base) if source_ram is None else source_ram
    original = ram
    prefix_manifest = None
    if prefix_blocks:
        prefix_manifest = dict(serial=patch_state.SERIAL, crc=patch_state.CRC,
            blocks=[dict(address=a, expected_hex=bytes(ram[a:a + len(data)]).hex(),
                         data_hex=bytes(data).hex()) for a, data in prefix_blocks])
        ram, prefix_report = patch_state.patch_memory(ram, prefix_manifest)
        prefix_manifest['ram_sha256'] = prefix_report['source_ram_sha256']
    manifest = nc.build_memory(ram, **options)
    view_blocks = nv.build_memory(ram)['blocks']
    from netplay_finish import blocks as finish_blocks
    extra = finish_blocks(ram, spec, view_blocks) if spec is not None else []
    manifest['blocks'] = view_blocks + extra + manifest['blocks']
    if prefix_manifest is not None:
        manifest = _combined_manifest(original, prefix_manifest, ram, manifest)
    elif source_ram is not None:
        # A cached image must not silently guard a different on-disk source.
        import state128
        manifest['ram_sha256'] = state128.digest(original)
    if out.exists():
        out.unlink()
    report = patch_state.patch(base, manifest, out)
    table, table_sha = current_table()
    built = kit_state.read_bytes(out, nc.TABLE, len(table))
    if built != table:
        raise ValueError('the built hash table is not the kit\'s (data/hash-table.json): the kit and its mod modules '
                         'disagree')
    return dict(state=str(out), sha256=report['output_sha256'], changed_bytes=report['changed_bytes'],
                mask=options['mask'], options=options['options'], table_sha256=table_sha)


def netplay_state(base, delay, max_stall=DEFAULT_MAX_STALL, states=None, say=print):
    """dict(state, state_sha256, size, delay, max_stall) of a made match at that input delay (made or reused)."""
    if not 1 <= delay <= 30 or not 60 <= max_stall <= 216000:
        raise KitError('TTM-NET-17', what=f'Input delay {delay} / stall limit {max_stall} is out of range.')
    base = Path(base)
    if not base.is_file():
        raise KitError('TTM-NET-25', what=f'{base} is missing.')
    base_sha = sha256_file(base)
    key = hashlib.sha256(f'{base_sha}:{delay}:{max_stall}:v2'.encode()).hexdigest()[:20]
    states = Path(states or kit_paths.STATES)
    states.mkdir(parents=True, exist_ok=True)
    out, meta_path = states / f'host-{key}.p2s', states / f'host-{key}.json'
    # Start can commit while the exact lobby download is being built. Both
    # workers must not truncate the same archive/.part or publish half a cache.
    # The second owner rechecks the completed hash after acquiring this lock.
    with _state_lock(out):
        return _netplay_state_locked(base, base_sha, delay, max_stall, out, meta_path, say)


def _netplay_state_locked(base, base_sha, delay, max_stall, out, meta_path, say):
    if out.is_file() and meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
            if meta.get('state_sha256') == sha256_file(out):
                return meta
        except (OSError, ValueError):
            pass
    started = time.time()
    delay_word, stall_word = control_words()
    try:
        archive = kit_state.StateArchive(base) if delay != BUILT_DELAY or max_stall != BUILT_MAX_STALL else None
        have = archive.words([delay_word, stall_word, QUEUE_CONTROL, QUEUE_CONTROL + 4]) if archive is not None \
            else kit_state.read_words(base, [delay_word, stall_word, QUEUE_CONTROL, QUEUE_CONTROL + 4])
        if (have[delay_word], have[stall_word]) != (BUILT_DELAY, BUILT_MAX_STALL):
            raise ValueError(f'{base.name} is not a delay-1 netplay state')
        problem = queue_problem(have)
        if problem:
            raise ValueError(problem)
        words = {}
        if delay != BUILT_DELAY:
            words[delay_word] = (BUILT_DELAY, delay)
        if max_stall != BUILT_MAX_STALL:
            words[stall_word] = (BUILT_MAX_STALL, max_stall)
        if words:
            say(f'Making the match file for input delay {delay}...')
            sha = kit_state.patch_words(base, out, words, archive=archive)
        else:
            shutil.copyfile(base, out)
            sha = sha256_file(out)
    except (OSError, ValueError) as error:
        raise KitError('TTM-NET-23', what=f'The match file for input delay {delay} could not be made from {base.name}: '
                                          f'{error}', fix='Start the match again.') from None
    meta = dict(state=str(out), state_sha256=sha, size=out.stat().st_size, delay=delay, max_stall=max_stall,
                base=str(base), base_sha256=base_sha, seconds=round(time.time() - started, 1))
    meta_path.write_text(json.dumps(meta, indent=1), encoding='utf-8')
    return meta


def machine_words(state, slot, watch=None, local=None, sealed=None, *, memory=None):
    """({address: (old, new)}) of a PC's own copy: netplay_core local_slot / self_feed (slot None: a spectator),
    sched_sealed (the host's copy: NO_SEAL; a guest's: below the first frame the host can schedule), netplay_view's
    watched side (None: by the slot) and this PC's display settings (kit_settings.LOCAL)."""
    import kit_settings
    import netplay_core as nc
    import netplay_view as nv
    targets = {nc.CONTROL + nc.F['local_slot']: nc.NO_SLOT if slot is None else slot,
               nc.CONTROL + nc.F['self_feed']: 0 if slot is None else 1,
               nv.CONTROL + nv.F['watch']: nv.NO_WATCH if watch is None else watch}
    if sealed is not None:
        targets[nc.CONTROL + nc.F['sched_sealed']] = sealed & 0xFFFFFFFF
    memory = kit_state.read_memory(state) if memory is None else memory
    if len(memory) != kit_state.EE_SIZE:
        raise ValueError(f'{Path(state).name} has no 128 MiB eeMemory.bin')
    u = lambda a: int.from_bytes(memory[a:a + 4], 'little')
    for address, data in kit_settings.local_blocks(u, local or {}):
        targets[address] = int.from_bytes(data, 'little')
    return {a: (u(a), v) for a, v in targets.items() if u(a) != v}


def machine_copy(state, target, slot, watch=None, local=None, sealed=None):
    """Write this PC's per-machine copy of a match (or of a resync / join state) to `target`; returns its path."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    archive = kit_state.StateArchive(state)
    words = machine_words(state, slot, watch, local, sealed, memory=archive.memory)
    tmp = target.with_name(target.name + '.build')
    if words:
        kit_state.patch_words(state, tmp, words, archive=archive)
    else:
        shutil.copyfile(state, tmp)
    tmp.replace(target)
    return target


def made_folder(spec_sha):
    return kit_paths.MATCHES / f'spec-{spec_sha[:16]}'


def made_match(spec_sha, options=None):
    """The match this kit's copy made earlier for that spec (and the same test options), else None."""
    folder = made_folder(spec_sha)
    try:
        meta = json.loads((folder / 'match.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    path = folder / 'netplay.p2s'
    if meta.get('spec_sha') != spec_sha or (meta.get('options') or None) != (options or None) or not path.is_file():
        return None
    if meta.get('kit') != _kit_version() or meta.get('netplay_sha256') != sha256_file(path):
        return None
    meta['folder'] = str(folder)
    meta['file'] = str(path)
    return meta


def _kit_version():
    import kit_ident
    return kit_ident.KIT_VERSION


def prune_made(keep=MADE_KEEP, spare=()):
    """Remove the oldest made matches beyond `keep` (never those in `spare`)."""
    folder = kit_paths.MATCHES
    if not folder.is_dir():
        return []
    made = sorted((p for p in folder.glob('spec-*') if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = []
    for path in made[keep:]:
        if str(path) in spare or path.name in spare:
            continue
        shutil.rmtree(path, ignore_errors=True)
        removed.append(path.name)
    return removed


def ensure_elf(iso):
    """Use the chosen disc's executable; a reviewed identity is required before extraction."""
    from kit_adapter import identity
    from kit_ident import Iso9660
    from native_map import elf_path
    import prototype
    adapter, _, serial = identity(iso)
    if adapter != kit_paths.ADAPTER:
        raise KitError('TTM-NET-20', what='Game adapter differs from this online session; reopen Play online.')
    target = elf_path(prototype.ROOT)
    with Iso9660(iso) as disc:
        data = disc.read('/' + serial + ';1', 16 << 20)
    if not target.is_file() or target.read_bytes() != data:
        # Installed copies are immutable. Setup already extracted this exact file.
        if kit_paths.INTEGRATED:
            raise KitError('TTM-NET-25', what='The installation executable does not match its ISO. Run Check installation.')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return target


def received_path(sha, states=None):
    return Path(states or kit_paths.STATES) / f'recv-{sha[:20]}.p2s'


def have_state(sha, states=None):
    """A state this PC already has with that SHA-256 (received earlier, or made here as host)."""
    states = Path(states or kit_paths.STATES)
    path = received_path(sha, states)
    if path.is_file() and sha256_file(path) == sha:
        return path
    if states.is_dir():
        for meta_path in states.glob('host-*.json'):
            try:
                meta = json.loads(meta_path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            if meta.get('state_sha256') == sha and Path(meta['state']).is_file() and \
                    sha256_file(meta['state']) == sha:
                return Path(meta['state'])
    return None
