"""What each PC tells the other before a match: the identities that must agree for lockstep, and the comparison.

  code      SHA-256 over every file of the kit's netplay folder (this code and the bundled mod modules)
  pcsx2     the PCSX2 build: on Windows pcsx2-qt.exe, every DLL next to it, resources/GameIndex.yaml (per-game fixes)
            and resources/patches.zip (EnablePatches); on Linux the AppImage file. It must be a TESTED build (below)
  patches   the Tag Team Mod pnach the kit installs (and, logged only, the memory cards both PCs start from)
  settings  the emulation settings, read from the PCSX2.ini the kit writes: the FORCED keys (digest), the keys that
            were never tested (digest) and the SAFE keys (logged only)
  disc      the game ISO, read the way the mod's disc library reads it (iso_compatibility.disc: SYSTEM.CNF's boot
            executable, its PCSX2 CRC = XOR of the ELF's words, the mod's loaded-ELF fingerprint, DBZP.BIN's SHA-256)
            plus the four AFS volume tables; never copied, never fully hashed unless asked (--disc-check full)
  bios      the BIOS file's SHA-256 and its ROMVER (version, region, date)

The policy comes from the cross-machine measurements (p27/xm, handshake-policy.json; 8101 identical updates per
variant through the fight, the KO, the results and a native rematch):
  REFUSE   a different protocol, netplay code, PCSX2 build that is not on the tested list (or two tested builds with
           different savestate versions), Tag Team Mod pnach, forced-settings digest, untested emulation setting,
           or game disc. After both PCSX2 started, PINE's version must be a tested one and serial, CRC and game
           version must be equal on both PCs (ttm_online checks that before the fight starts).
  FORCE    FORCED below: the kit writes these into PCSX2.ini on every start on both PCs. The EE FPU round mode
           desynced at update 1; EE cycle rate/skip and fast CDVD move emulated time (they split the rematch intro).
  ALLOW    BIOS dump, region and version (six dumps: USA/Europe/Japan v1.00-v2.20), NVM/MEC and memory cards, the
           OS (Windows or the Linux AppImage), GPU, renderer and every GS option, audio, frame limiter, vsync, the
           SAFE emulation keys: these are logged ('note') and never refused by default.

compare() turns two identities into findings: (code, 'refuse'|'warn'|'note', values). The BIOS policy (--bios-check
note|warn|refuse|off, default note) is the stricter of the two PCs' choices.
"""
import hashlib
import json
import os
import re
import struct
from pathlib import Path

import kit_paths
from kit_codes import KitError

KIT_VERSION = '2.2.0'
# 3 (kit 1.2.0): the guest's window draws its own player's close-up effects (netplay_view VIEWER) and there is no
# split screen any more (no --split, no 'split' in the HELLO request): an older kit is refused at the preamble.
# 4 (kit 1.3.0): the online lobby (LOBBY/PICK/CHAT, PREPARE..PREPARED, votes, rematch, END_FIGHT, resync, reconnect)
# and UDP netproto version 2 (12-byte inputs with aux, hash_ack, epochs): kits 1.0-1.2 are refused (TTM-NET-01).
# 5 (kit 2.0): rooms of any number of members (spectators, player slots, names), matches built on the spot (no
# saved matches), Retry / Return to lobby votes, netplay_core layout 3 (intros in lockstep, four slots, neutral
# pads after the decision) and UDP netproto version 3 (the host is the hub of a star): every older kit is refused.
# 6 (kit 2.1): any fighter can be a player (ten input slots, netplay_core layout 4 seats, netproto version 4).
PROTOCOL = 7
SAVESTATE_VERSION = 0x9A590000
# PCSX2 builds the cross-machine tests ran (all identical): key = the build digest of pcsx2_identity (Windows: the
# tree digest of pcsx2-qt.exe + DLLs + GameIndex.yaml + patches.zip; Linux: the AppImage's SHA-256).
TESTED_PCSX2 = {
    '316afb5f46df0b83e0a551b9532b6d54f605b2a073cbc5a6ecbd86045e18deda':
        dict(version='2.8.2', platform='Windows', savestate=SAVESTATE_VERSION),       # the kit's own (release copy)
    '6cfbd29639e450ccfa888819756d5b97fcdabd4fca230c0b7e18bf3cb9bb2f3a':
        dict(version='2.8.0', platform='Windows', savestate=SAVESTATE_VERSION),       # Tag Team Mod's runtime28
    '0c46bb6a88aa2782b10853a7b07cf3387ba99cbef2b966372cd2315b8571abea':
        dict(version='2.8.2', platform='Linux AppImage', savestate=SAVESTATE_VERSION),  # official x64 Qt AppImage
}
# pcsx2-qt.exe alone (for the message when the folder around it was changed)
KNOWN_EXE = {'982c7c62600a999cf15a25c18349426166c785e7867b2fcc5018d733245b71a3': '2.8.2',
             'a7e5933914ab64d951060b83e7fc2a2483b79baed230cbad9a604ce8e875ea4b': '2.8.0'}
TESTED_PINE = ('PCSX2 v2.8.2', 'PCSX2 v2.8.0')                 # PINE MsgVersion of the tested builds
from native_map import CRC
GAME = dict(serial=__import__('kit_adapter').state_name(0).split(' (')[0], crc=CRC.lower())
from native_map import SERIAL, CRC
PNACH = __import__('kit_adapter').state_name(0).split(' (')[0] + '_' + CRC + '_BT3Loading.pnach'
MEMCARDS = ('Mcd001.ps2', 'Mcd002.ps2')
# The reviewed BT3 USA variant (Tag Team Mod iso_compatibility.adapters: VARIANTS / ADAPTERS 'bt3-usa').
BT3_USA = dict(serial='SLUS_216.78', crc='428113C2',
               elf_sha256='811188ba9b416500d921cd4d9514df0cbf42f3a41a99cf5aac5a3da37171bf99',
               loaded_elf_sha256='024b4a558d90c24ea7ff193ad8a9e4cb808be4d7097e915cdda571c549adea9f',
               dbzp_sha256='30f61f9c78c3859e5dd4fcfd8df6753b0f2d2c64beb924b92da5b2eaaa5e09cc')
# The whole-image SHA-256 of the reviewed original dump (the mod's compatibility profile 93f1f911...).
ORIGINAL_SHA256 = '93f1f911e9a2bbdf92e5794fc3075ddf3f87db3df4b1cb8cfbb0448721c91172'
SETTINGS_SECTIONS = ('EmuCore', 'EmuCore/CPU', 'EmuCore/CPU/Recompiler', 'EmuCore/Speedhacks', 'EmuCore/Gamefixes',
                     'EmuCore/Profiles', 'Pad')
# Keys of those sections that never change the emulated game (the PINE slot is per PC by design).
SETTINGS_IGNORED = {'EmuCore/EnablePINE', 'EmuCore/PINESlot', 'EmuCore/EnableDiscordPresence',
                    'EmuCore/SavestateCompressionType', 'EmuCore/SavestateCompressionRatio',
                    'EmuCore/SaveStateOnShutdown', 'EmuCore/CdvdDumpBlocks', 'EmuCore/EnableRecordingTools',
                    'EmuCore/WarnAboutUnsafeSettings', 'EmuCore/InhibitScreensaver', 'EmuCore/BackupSavestate',
                    'EmuCore/EnableFastBoot', 'EmuCore/EnableFastBootFastForward'}
# FORCED (section, key, value): written by the kit on every start on both PCs; None = the key is removed (PCSX2's
# default; 'default' in the digest). A different digest means someone changed the kit.
CLAMPS = ('fpuOverflow', 'fpuExtraOverflow', 'fpuFullMode', 'vu0Overflow', 'vu0ExtraOverflow', 'vu0SignOverflow',
          'vu0Underflow', 'vu1Overflow', 'vu1ExtraOverflow', 'vu1SignOverflow', 'vu1Underflow')
FORCED = (tuple(('EmuCore/CPU', key, None) for key in ('FPU.Roundmode', 'FPUDiv.Roundmode', 'VU0.Roundmode',
                                                         'VU1.Roundmode'))
          + (('EmuCore/CPU', 'ExtraMemory', 'true'),)
          + tuple(('EmuCore/CPU/Recompiler', key, None) for key in CLAMPS)
          + tuple(('EmuCore/CPU/Recompiler', key, 'true') for key in ('EnableEE', 'EnableIOP', 'EnableVU0',
                                                                         'EnableVU1'))
          + (('EmuCore/Speedhacks', 'EECycleRate', '0'), ('EmuCore/Speedhacks', 'EECycleSkip', '0'),
             ('EmuCore/Speedhacks', 'fastCDVD', 'true'),
             ('EmuCore', 'EnableCheats', 'true'), ('EmuCore', 'EnablePatches', 'true'),
             ('EmuCore', 'EnableWideScreenPatches', 'false'), ('EmuCore', 'EnableNoInterlacingPatches', 'false'),
             ('EmuCore', 'EnableGameFixes', 'true'), ('EmuCore', 'HostFs', 'false'),
             ('Pad', 'MultitapPort1', 'true'))
          + tuple((f'Pad{n}', 'Type', 'DualShock2') for n in (1, 2, 3, 4)))
# SAFE: emulation keys the cross-machine tests changed on one PC only with identical games (logged, never refused).
SAFE = ('EmuCore/Speedhacks/vuThread', 'EmuCore/Speedhacks/IntcStat', 'EmuCore/Speedhacks/WaitLoop',
        'EmuCore/Speedhacks/vuFlagHack', 'EmuCore/Speedhacks/vu1Instant', 'EmuCore/CPU/Recompiler/EnableEECache',
        'EmuCore/CPU/Recompiler/EnableFastmem')
SAFE_NAMES = {'EmuCore/Speedhacks/vuThread': 'MTVU', 'EmuCore/Speedhacks/IntcStat': 'INTC spin detection',
              'EmuCore/Speedhacks/WaitLoop': 'wait loop detection', 'EmuCore/Speedhacks/vuFlagHack': 'VU flag hack',
              'EmuCore/Speedhacks/vu1Instant': 'instant VU1', 'EmuCore/CPU/Recompiler/EnableEECache': 'EE cache',
              'EmuCore/CPU/Recompiler/EnableFastmem': 'fastmem'}
BIOS_POLICIES = ('off', 'note', 'warn', 'refuse')


# ---- hashing -----------------------------------------------------------------------------------------------------------
def sha256_file(path, progress=None):
    h = hashlib.sha256()
    total = os.path.getsize(path)
    done = 0
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    return h.hexdigest()


def tree_digest(root, files):
    """SHA-256 over (relative path, file SHA-256) of `files` (sorted, '/' separators)."""
    h = hashlib.sha256()
    rows = []
    for path in sorted(files, key=lambda p: str(Path(p).relative_to(root)).replace('\\', '/').lower()):
        rel = str(Path(path).relative_to(root)).replace('\\', '/')
        rows.append(rel)
        h.update(rel.lower().encode('utf-8') + b'\0' + bytes.fromhex(sha256_file(path)) + b'\n')
    return h.hexdigest(), rows


# ---- the kit's own files -------------------------------------------------------------------------------------------------
def code_files():
    out = []
    for path in kit_paths.NETPLAY.rglob('*'):
        rel = path.relative_to(kit_paths.NETPLAY).parts
        if path.is_file() and rel[0] not in ('tests', '__pycache__') and '__pycache__' not in rel \
                and path.suffix in ('.py', '.json'):
            out.append(path)
    return out


def code_identity():
    digest, rows = tree_digest(kit_paths.NETPLAY, code_files())
    return dict(digest=digest, files=len(rows))


def pcsx2_files(root=None):
    root = Path(root or kit_paths.PCSX2)
    files = [root / 'pcsx2-qt.exe'] + sorted(root.glob('*.dll'))
    files += [root / 'resources' / 'GameIndex.yaml', root / 'resources' / 'patches.zip']
    missing = [str(p) for p in files if not p.is_file()]
    if missing:
        raise KitError('TTM-NET-25', what=f'The kit\'s PCSX2 is incomplete: {", ".join(missing[:3])} missing.')
    return root, files


def _build(digest, version, platform, files):
    tested = TESTED_PCSX2.get(digest)
    return dict(digest=digest, version=tested['version'] if tested else version, platform=platform,
                tested=tested is not None, savestate=tested['savestate'] if tested else None, files=files)


def pcsx2_identity(root=None):
    """The Windows build in `root` (default: the kit's pcsx2 folder)."""
    root, files = pcsx2_files(root)
    exe = sha256_file(root / 'pcsx2-qt.exe')
    digest, rows = tree_digest(root, files)
    out = _build(digest, KNOWN_EXE.get(exe, 'unknown') + ' (changed copy)' if exe in KNOWN_EXE else 'unknown build',
                 'Windows', len(rows))
    out['exe_sha256'] = exe
    return out


def appimage_identity(path):
    """A Linux PCSX2 AppImage (the file itself)."""
    return _build(sha256_file(path), 'unknown build', 'Linux AppImage', 1)


def describe_build(p):
    return f'PCSX2 {p.get("version")} ({p.get("platform") or "?"}, {_short(p.get("digest"))})'


def require_tested(p):
    """Local refusal (TTM-NET-28) for a PCSX2 build the cross-machine tests did not run."""
    if not p.get('tested'):
        raise KitError('TTM-NET-28', build=describe_build(p),
                       tested=', '.join(sorted({f'{b["version"]} ({b["platform"]})' for b in TESTED_PCSX2.values()})))


def pnach_files(runtime=None):
    """{sha256: path} of the runtime pnach files the kit ships (match/runtime/pnach/<sha256>.pnach): one per Tag Team
    Mod build family it accepts; a match names the one its installation's guest code needs (kit 2.0)."""
    folder = Path(runtime or kit_paths.RUNTIME) / 'pnach'
    return {p.stem: p for p in sorted(folder.glob('*.pnach'))} if folder.is_dir() else {}


def patches_identity(runtime=None):
    """The pnach set both PCs must have (refused when different) and the starting memory cards (logged only: the
    cross-machine tests found the user's own memory cards and NVM identical)."""
    runtime = Path(runtime or kit_paths.RUNTIME)
    pnach = pnach_files(runtime)
    cards = [runtime / 'memcards' / m for m in MEMCARDS]
    missing = [str(p) for p in cards if not p.is_file()] + ([] if pnach else [str(runtime / 'pnach')])
    if missing:
        raise KitError('TTM-NET-25', what=f'Kit files are missing: {", ".join(missing)}.')
    for sha, path in pnach.items():
        if sha256_file(path) != sha:
            raise KitError('TTM-NET-25', what=f'{path} is damaged (its SHA-256 is not its name).')
    digest, _ = tree_digest(runtime, list(pnach.values()))
    cards_digest, _ = tree_digest(runtime, cards)
    return dict(digest=digest, pnach_sha256=sorted(pnach), memcards=cards_digest)


# ---- settings ------------------------------------------------------------------------------------------------------------
def ini_values(text):
    values, section = {}, None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith('[') and s.endswith(']'):
            section = s[1:-1]
        elif '=' in s and section and not s.startswith(('#', ';')):
            key, value = s.split('=', 1)
            values[f'{section}/{key.strip()}'] = value.strip()
    return values


def relevant_settings(ini_text):
    """The emulation settings that change how the game runs: {'Section/Key': value}."""
    out = {}
    for key, value in ini_values(ini_text).items():
        section, _, name = key.rpartition('/')
        if key in SETTINGS_IGNORED:
            continue
        if section in SETTINGS_SECTIONS or (re.fullmatch(r'Pad\d', section) and name == 'Type'):
            out[key] = value
    return out


def forced_values(ini_text):
    """{'Section/Key': effective value} of every FORCED key ('default' when the key is absent)."""
    values = ini_values(ini_text)
    return {f'{s}/{k}': values.get(f'{s}/{k}', 'default') for s, k, _ in FORCED}


def forced_problems(ini_text):
    """FORCED keys whose effective value in `ini_text` is not the forced one (the kit's own check of its ini)."""
    have = forced_values(ini_text)
    return [f'{s}/{k} = {have[f"{s}/{k}"]} (must be {v or "default"})' for s, k, v in FORCED
            if have[f'{s}/{k}'] != (v or 'default')]


def _digest(values):
    return hashlib.sha256(json.dumps(sorted(values.items())).encode('utf-8')).hexdigest()


def settings_identity(ini_text):
    """forced: the FORCED keys; other: every other emulation key (never tested: a difference is refused); safe: the
    SAFE keys (logged only). digest covers forced + other."""
    values = relevant_settings(ini_text)
    forced = forced_values(ini_text)
    safe = {k: values.get(k, 'default') for k in SAFE}
    other = {k: v for k, v in values.items() if k not in forced and k not in safe}
    return dict(digest=_digest(dict(forced, **other)), forced_digest=_digest(forced), forced=forced, other=other,
                safe=safe, values=values)


# ---- the game disc (ISO 9660, standard library only) ------------------------------------------------------------------------
# Image formats a player may select instead of a plain ISO: the same sniffing as the mod's iso_compatibility.disc.
ARCHIVES = ((b'7z\xbc\xaf\x27\x1c', '7z'), (b'PK\x03\x04', 'ZIP'), (b'PK\x05\x06', 'ZIP'), (b'Rar!\x1a\x07', 'RAR'),
            (b'\x1f\x8b', 'gzip (.gz)'))
RAW_SYNC = b'\x00' + b'\xff' * 10 + b'\x00'


def image_problem(head, size):
    """A text when the first 64 KiB and the size show something other than a complete ISO 9660 image (the mod's
    iso_compatibility.disc.image_problem, worded for the kit); None for a plausible ISO."""
    if head[:8] == b'MComprHD':
        return 'it is a CHD file; convert it back to an ISO (chdman extractdvd)'
    if head[:4] in (b'CISO', b'ZISO'):
        return f'it is a {head[:4].decode("ascii")[0]}SO file; decompress it to an ISO (maxcso --decompress)'
    for magic, name in ARCHIVES:
        if head.startswith(magic):
            return f'it is still packed in an archive ({name}); extract it and select the .iso inside'
    if head.startswith(RAW_SYNC) or re.match(rb'(?:\xef\xbb\xbf)?\s*(?:FILE|REM|TRACK|CATALOG|PERFORMER|TITLE)\s',
                                             head[:64], re.I):
        return 'it is a raw BIN/CUE image, not an ISO; convert it to an ISO'
    if size < 0x8800 or len(head) < 0x8058 or head[0x8000:0x8006] != b'\x01CD001':
        return 'it is not a PlayStation 2 disc image'
    expected = struct.unpack_from('<I', head, 0x8050)[0] * 2048
    if size < expected:
        return f'the ISO is incomplete: the file has {size} bytes, but the disc says {expected} bytes'
    return None


class Iso9660:
    """Read-only access to files of an ISO 9660 image by path ('/BIN/DBZP.BIN;1')."""

    def __init__(self, path):
        self.path = Path(path)
        self.f = open(self.path, 'rb')
        pvd = self.sector(16)
        if pvd[:6] != b'\x01CD001':
            raise ValueError('no ISO 9660 primary volume descriptor')
        self.root = self.record(pvd, 156)

    def close(self):
        self.f.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def sector(self, lba, count=1):
        self.f.seek(lba * 2048)
        data = self.f.read(2048 * count)
        if len(data) != 2048 * count:
            raise ValueError(f'the image ends before sector {lba + count}')
        return data

    @staticmethod
    def record(data, at):
        length = data[at]
        extent, size = struct.unpack_from('<I', data, at + 2)[0], struct.unpack_from('<I', data, at + 10)[0]
        flags, name_len = data[at + 25], data[at + 32]
        name = data[at + 33:at + 33 + name_len]
        return dict(length=length, extent=extent, size=size, dir=bool(flags & 2), name=name)

    def listdir(self, entry):
        if entry['size'] > 1 << 22:
            raise ValueError('directory too large')
        data = self.sector(entry['extent'], (entry['size'] + 2047) // 2048)[:entry['size']]
        out, at = {}, 0
        while at < len(data):
            length = data[at]
            if length == 0:
                at = (at // 2048 + 1) * 2048
                continue
            r = self.record(data, at)
            if r['name'] not in (b'\x00', b'\x01'):
                out[r['name'].decode('ascii', 'replace').upper()] = r
            at += length
        return out

    def entry(self, path):
        node = self.root
        for part in [p for p in path.strip('/').split('/') if p]:
            node = self.listdir(node).get(part.upper())
            if node is None:
                return None
        return node

    def read(self, path, max_size=32 << 20):
        e = self.entry(path)
        if e is None or e['dir']:
            raise FileNotFoundError(path)
        if not 0 < e['size'] <= max_size:
            raise ValueError(f'{path} has an unexpected size ({e["size"]} bytes)')
        self.f.seek(e['extent'] * 2048)
        data = self.f.read(e['size'])
        if len(data) != e['size']:
            raise ValueError(f'{path} is truncated')
        return data

    def read_at(self, path, offset, length):
        e = self.entry(path)
        if e is None:
            raise FileNotFoundError(path)
        if offset + length > e['size']:
            raise ValueError(f'{path}: read beyond its end')
        self.f.seek(e['extent'] * 2048 + offset)
        return self.f.read(length)


def pcsx2_crc(data):
    """PCSX2 ElfObject::GetCRC: XOR of the ELF's little-endian words (iso_compatibility.disc.pcsx2_crc)."""
    result = 0
    for word, in struct.iter_unpack('<I', data[:len(data) // 4 * 4]):
        result ^= word
    return f'{result:08X}'


def executable_fingerprint(data):
    """The mod's loaded-ELF fingerprint (iso_compatibility.disc.executable_fingerprint): entry point, flags and every
    program segment's memory contract and contents, not ELF trailers."""
    if data[:7] != b'\x7fELF\x01\x01\x01' or len(data) < 52 or struct.unpack_from('<H', data, 18)[0] != 8:
        raise ValueError('the boot file is not a 32-bit little-endian MIPS executable')
    digest = hashlib.sha256(b'TagTeam loaded ELF v1\0')
    digest.update(data[:28])
    digest.update(data[36:42])
    ph = struct.unpack_from('<I', data, 28)[0]
    size, count = struct.unpack_from('<HH', data, 42)
    if size < 32 or not 0 < count < 128 or ph + size * count > len(data):
        raise ValueError('invalid ELF segments')
    digest.update(struct.pack('<H', count))
    for i in range(count):
        kind, off, va, pa, length, mem, flags, align = struct.unpack_from('<8I', data, ph + i * size)
        if off + length > len(data):
            raise ValueError('ELF segment outside the file')
        digest.update(struct.pack('<7I', kind, va, pa, length, mem, flags, align))
        digest.update(data[off:off + length])
    return digest.hexdigest()


def cached_sha256(iso, cache_file=None, progress=None):
    """The whole ISO's SHA-256, remembered per (path, size, modification time) in `cache_file` (data/disc-cache.json):
    only the first start on a PC reads the whole image."""
    iso = Path(iso).resolve()
    st = iso.stat()
    key = str(iso).lower()
    cache = {}
    if cache_file:
        try:
            cache = json.loads(Path(cache_file).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            cache = {}
    hit = cache.get(key)
    if isinstance(hit, dict) and hit.get('size') == st.st_size and hit.get('mtime_ns') == st.st_mtime_ns:
        return hit['sha256']
    digest = sha256_file(iso, progress)
    if cache_file:
        cache[key] = dict(size=st.st_size, mtime_ns=st.st_mtime_ns, sha256=digest)
        try:
            Path(cache_file).parent.mkdir(parents=True, exist_ok=True)
            Path(cache_file).write_text(json.dumps(cache, indent=1), encoding='utf-8')
        except OSError:
            pass
    return digest


def disc_identity(iso, full=True, progress=None, cache_file=None):
    """The identity of a BT3 ISO (dict); KitError TTM-NET-20 for an unreadable or unreviewed disc. With
    `full` the whole image's SHA-256 is part of it (an expanded-maps or otherwise rewritten copy keeps the same game
    code and file tables but different contents)."""
    iso = Path(iso)
    try:
        size = iso.stat().st_size
        with open(iso, 'rb') as f:
            head = f.read(0x10000)
    except OSError as error:
        raise KitError('TTM-NET-20', what=f'The game ISO cannot be read: {iso} ({error.strerror or error}).') from None
    problem = image_problem(head, size)
    if problem:
        raise KitError('TTM-NET-20', what=f'{iso} cannot be used: {problem}.')
    try:
        with Iso9660(iso) as disc:
            config = disc.read('/SYSTEM.CNF;1', 65536)
            match = re.search(rb'(?im)^\s*BOOT2\s*=\s*cdrom0:\\([^\s;]+);1', config)
            if not match:
                raise ValueError('SYSTEM.CNF names no PlayStation 2 boot executable')
            boot = '/' + match[1].decode('ascii').replace('\\', '/') + ';1'
            elf = disc.read(boot, 16 << 20)
            serial = Path(boot).name.split(';')[0]
            try:
                dbzp = hashlib.sha256(disc.read('/BIN/DBZP.BIN;1')).hexdigest()
            except FileNotFoundError:
                dbzp = None
            tables = hashlib.sha256()
            volumes = 0
            for volume in range(4):
                path = f'/DATA/PZS3{dict(bt3_pal="EU", bt3_jpn="JP").get(kit_paths.ADAPTER.replace("-", "_"), "US")}{volume}.AFS;1'
                if disc.entry(path) is None:
                    continue
                head8 = disc.read_at(path, 0, 8)
                if head8[:4] != b'AFS\0':
                    raise ValueError(f'{path} has a changed AFS header')
                count = struct.unpack_from('<I', head8, 4)[0]
                if not 0 < count <= 100000:
                    raise ValueError(f'{path} has an invalid AFS table')
                tables.update(path.encode() + head8 + disc.read_at(path, 8, count * 8))
                volumes += 1
    except (OSError, ValueError, struct.error) as error:
        raise KitError('TTM-NET-20', what=f'{iso} is not a readable PlayStation 2 game ISO ({error}).') from None
    identity = dict(serial=serial, crc=pcsx2_crc(elf), elf_sha256=hashlib.sha256(elf).hexdigest(),
                    loaded_elf_sha256=executable_fingerprint(elf), dbzp_sha256=dbzp,
                    afs_tables=tables.hexdigest() if volumes else None, afs_volumes=volumes, size=size,
                    name=iso.name)
    identity['bt3_usa'] = all(identity[k] == BT3_USA[k] for k in ('serial', 'crc', 'loaded_elf_sha256',
                                                                   'dbzp_sha256')) and volumes >= 3
    from kit_adapter import identity as reviewed_identity
    adapter, evidence, _ = reviewed_identity(iso)
    identity['adapter'] = adapter
    if adapter.startswith('bt4'):
        from iso_compatibility.disc import Disc
        with Disc(iso) as indexed:
            identity['afs_tables'] = hashlib.sha256(indexed.member('/BIN/DBZ4.BIN;1')).hexdigest()
            identity['afs_volumes'] = len(indexed.tables)
    if adapter != kit_paths.ADAPTER:
        what = f'{iso.name} uses {adapter}; this online session uses {kit_paths.ADAPTER}. Reopen Play online for the selected disc'
        raise KitError('TTM-NET-20', what=what + '.')
    if full:
        try:
            identity['sha256'] = cached_sha256(iso, cache_file, progress)
        except OSError as error:
            raise KitError('TTM-NET-20', what=f'The game ISO cannot be read: {iso} ({error}).') from None
        identity['original'] = identity['sha256'] == ORIGINAL_SHA256
    return identity


DISC_KEYS = ('serial', 'crc', 'loaded_elf_sha256', 'dbzp_sha256', 'afs_tables')


# ---- the BIOS ------------------------------------------------------------------------------------------------------------
REGIONS = {'J': 'Japan', 'A': 'USA', 'E': 'Europe', 'H': 'Asia', 'C': 'China', 'T': 'Taiwan', 'R': 'Russia',
           'K': 'Korea', 'O': 'Oceania'}


def romver(data):
    """The ROMVER text of a PS2 BIOS image (ROMDIR walk), or None."""
    at = data.find(b'RESET\0\0\0\0\0')
    if at < 0 or at % 16:
        return None
    offset = 0
    for i in range(at, min(len(data), at + 16 * 512), 16):
        name = data[i:i + 10].rstrip(b'\0')
        if not name:
            break
        size = struct.unpack_from('<I', data, i + 12)[0]
        if name == b'ROMVER':
            return data[offset:offset + size].split(b'\0')[0].strip().decode('ascii', 'replace')
        offset += (size + 15) & ~15
    return None


def bios_identity(path):
    path = Path(path)
    try:
        size = path.stat().st_size
        if not (1 << 20) <= size <= (32 << 20):
            raise KitError('TTM-NET-21', what=f'{path} is not a PlayStation 2 BIOS ({size} bytes; a BIOS has 4 MiB).')
        data = path.read_bytes()
    except OSError as error:
        raise KitError('TTM-NET-21', what=f'The BIOS file cannot be read: {path} ({error.strerror or error}).') from None
    text = romver(data)
    if text is None:
        raise KitError('TTM-NET-21', what=f'{path} is not a PlayStation 2 BIOS (no ROMVER entry).')
    parsed = re.fullmatch(r'(\d\d)(\d\d)([A-Z])([A-Z])(\d{4})(\d\d)(\d\d)', text[:14])
    describe = text
    if parsed:
        major, minor, region, kind, y, m, d = parsed.groups()
        describe = f'v{int(major)}.{minor} {REGIONS.get(region, region)} ({y}-{m}-{d})'
    return dict(sha256=hashlib.sha256(data).hexdigest(), size=size, romver=text, describe=describe, name=path.name)


# ---- this PC's identity and the comparison ----------------------------------------------------------------------------------
def local_identity(*, disc, bios, ini_text, pcsx2=None, bios_policy='note', disc_policy='quick', name=''):
    """What this PC sends to the other one. File names and paths stay on this PC (only contents are described)."""
    private = ('name', 'path')
    return dict(protocol=PROTOCOL, kit_version=KIT_VERSION, code=code_identity(), pcsx2=pcsx2 or pcsx2_identity(),
                patches=patches_identity(), settings=settings_identity(ini_text),
                disc={k: v for k, v in disc.items() if k not in private},
                bios={k: v for k, v in bios.items() if k not in private},
                bios_policy=bios_policy, disc_policy=disc_policy, name=name[:32])


def _short(value):
    return (value or '-')[:12]


def strictest(*policies, order=BIOS_POLICIES):
    return max((p for p in policies if p in order), key=order.index, default='note')


def _pairs(keys, va, vb, names=None):
    return ', '.join(f'{(names or {}).get(k, k)} ({va.get(k, "unset")} / {vb.get(k, "unset")})' for k in keys)


def compare(mine, theirs):
    """[(code, 'refuse'|'warn'|'note', values)] for two identities (the same list on both PCs, whichever side is
    'mine'). 'note' = tested to make no difference: logged, the match goes on."""
    out = []
    if mine.get('protocol') != theirs.get('protocol'):
        return [('TTM-NET-01', 'refuse', dict(mine=mine.get('protocol'), theirs=theirs.get('protocol')))]
    for key, code in (('code', 'TTM-NET-02'), ('patches', 'TTM-NET-04')):
        a, b = mine.get(key, {}), theirs.get(key, {})
        if a.get('digest') != b.get('digest'):
            out.append((code, 'refuse', dict(mine=_short(a.get('digest')), theirs=_short(b.get('digest')))))
    pa, pb = mine.get('pcsx2', {}), theirs.get('pcsx2', {})
    if pa.get('digest') and pa.get('digest') == pb.get('digest') and not pa.get('tested'):
        # kit 2.1 (inside a Tag Team Mod installation): both PCs run the SAME build, one the tests did not run - the
        # same binaries keep both games identical; a warning, never a refusal
        out.append(('TTM-NET-03', 'warn', dict(mine=describe_build(pa), theirs=describe_build(pb))))
    elif not (pa.get('tested') and pb.get('tested')) or pa.get('savestate') != pb.get('savestate'):
        out.append(('TTM-NET-03', 'refuse', dict(mine=describe_build(pa), theirs=describe_build(pb))))
    elif pa.get('digest') != pb.get('digest'):
        out.append(('TTM-NET-03', 'note', dict(mine=describe_build(pa), theirs=describe_build(pb))))
    ma, mb = (mine.get('patches') or {}).get('memcards'), (theirs.get('patches') or {}).get('memcards')
    if ma != mb:
        out.append(('TTM-NET-04', 'note', dict(what='the starting memory cards differ', mine=_short(ma),
                                               theirs=_short(mb))))
    a, b = mine.get('settings', {}), theirs.get('settings', {})
    if a.get('digest') != b.get('digest'):
        fa, fb = a.get('forced', {}), b.get('forced', {})
        oa, ob = a.get('other', {}), b.get('other', {})
        forced = sorted(k for k in set(fa) | set(fb) if fa.get(k) != fb.get(k))
        other = sorted(k for k in set(oa) | set(ob) if oa.get(k) != ob.get(k))
        text = []
        if forced:
            text.append('forced by the kit: ' + _pairs(forced[:8], fa, fb))
        if other:
            text.append('not tested between PCs: ' + _pairs(other[:8], oa, ob))
        out.append(('TTM-NET-05', 'refuse', dict(keys='; '.join(text) or 'unknown')))
    sa, sb = a.get('safe', {}), b.get('safe', {})
    safe = sorted(k for k in set(sa) | set(sb) if sa.get(k) != sb.get(k))
    if safe:
        out.append(('TTM-NET-05', 'note', dict(keys=_pairs(safe, sa, sb, SAFE_NAMES))))
    da, db = mine.get('disc', {}), theirs.get('disc', {})
    differ = [k for k in DISC_KEYS if da.get(k) != db.get(k)]
    if differ:
        out.append(('TTM-NET-06', 'refuse', dict(what='they differ in ' + ', '.join(differ) +
                                                 f' ({da.get("serial")} {da.get("crc")} / {db.get("serial")} {db.get("crc")})')))
    elif da.get('sha256') and db.get('sha256') and da['sha256'] != db['sha256']:
        odd = [who for who, d in (('this PC', da), ('the other PC', db)) if d['sha256'] != ORIGINAL_SHA256]
        out.append(('TTM-NET-06', 'refuse', dict(
            what='the game code and file tables are identical, but the contents of the two ISO files differ '
                 f'(SHA-256 {_short(da["sha256"])} / {_short(db["sha256"])}); '
                 + (' and '.join(odd) + ' does not have the original dump (an expanded-maps or otherwise modified '
                    'copy?)' if odd else 'neither is the original dump'))))
    ba, bb = mine.get('bios', {}), theirs.get('bios', {})
    if ba.get('sha256') != bb.get('sha256'):
        policy = strictest(mine.get('bios_policy'), theirs.get('bios_policy'))
        if policy != 'off':
            out.append(('TTM-NET-07', policy, dict(what=f'{ba.get("describe")} {_short(ba.get("sha256"))} / '
                                                        f'{bb.get("describe")} {_short(bb.get("sha256"))}')))
    return out


def note_line(code, values):
    """One console line for a 'note' finding (a difference the cross-machine tests found harmless)."""
    if code == 'TTM-NET-03':
        what = f'the two PCs run different tested PCSX2 builds ({values.get("mine")} / {values.get("theirs")})'
    elif code == 'TTM-NET-04':
        what = f'{values.get("what")} ({values.get("mine")} / {values.get("theirs")})'
    elif code == 'TTM-NET-05':
        what = f'settings that were tested to make no difference: {values.get("keys")}'
    elif code == 'TTM-NET-07':
        what = f'the two PCs use different BIOS files ({values.get("what")})'
    else:
        what = ', '.join(f'{k}={v}' for k, v in values.items())
    return f'Note ({code}, allowed: tested to keep both games identical): {what}.'


def peer_runtime(mine, theirs):
    """[(code, 'refuse'|'note', values)] for the other PC's PINE answers (sent with READY) against ours: the same
    game (serial, CRC, version) and a tested PCSX2 version (two different tested builds are a note)."""
    mine, theirs = mine or {}, theirs or {}
    game = ('serial', 'crc', 'game_version')
    if {k: str(theirs.get(k)).lower() for k in game} != {k: str(mine.get(k)).lower() for k in game}:
        return [('TTM-NET-06', 'refuse', dict(what=(
            f'the other PC\'s PCSX2 runs {theirs.get("serial")} CRC {theirs.get("crc")} version '
            f'{theirs.get("game_version")}, this PC {mine.get("serial")} CRC {mine.get("crc")} version '
            f'{mine.get("game_version")}')))]
    if theirs.get('version') not in TESTED_PINE:
        return [('TTM-NET-03', 'refuse', dict(mine=mine.get('version'), theirs=theirs.get('version')))]
    if theirs.get('version') != mine.get('version'):
        return [('TTM-NET-03', 'note', dict(mine=mine.get('version'), theirs=theirs.get('version')))]
    return []


def runtime_problems(info, game=None):
    """[(code, text)] for a running PCSX2's PINE info: an untested build or a different selected disc."""
    out = []
    if info.get('version') not in TESTED_PINE:
        out.append(('TTM-NET-28', f'PCSX2 reports "{info.get("version")}"; tested: {", ".join(TESTED_PINE)}'))
    want = game or GAME
    got = {k: str(info.get(k) or '').lower() for k in want}
    if got != {k: v.lower() for k, v in want.items()}:
        out.append(('TTM-NET-06', f'PCSX2 runs {info.get("serial")} CRC {info.get("crc")} version '
                                  f'{info.get("game_version")}, expected {want}'))
    return out
