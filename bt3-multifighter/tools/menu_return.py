"""Owned clean menu checkpoints and native post-match return destinations.

No fixed save slot is overwritten. Capture and restore borrow the trainer's
verified reusable slots for one operation, then release its lock immediately.
The authoritative checkpoints are immutable archives, never those scratch slots.
"""
from native_map import A, CRC, SERIAL, elf_path
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import hashlib
import struct
import uuid
import saved_game_state

from atomic_files import write_json
from regional import MAIN_MENU_PREFIXES

SCENE_MANAGER = A(0x2FF10C)
MAIN_OBJECT, DUEL_OBJECT, COMMON_UI = A(0x3B0E80), A(0x3B38E8), A(0x2FF0F0)
LOOP_FLAG, RESULT_FLAGS, REASON_FLAGS = A(0x3337C0), A(0x333700), A(0x333704)
MAIN, DUEL, SINGLE_SELECT, TEAM_SELECT = 4, 0x26, 0x27, 0x28
RAM_BYTES = 0x8000000


def _read(source, address, size):
    if hasattr(source, 'read'):
        value = source.read(address, size)
    else:
        value = source[address:address + size]
    if len(value) != size:
        raise ValueError('Incomplete menu state read')
    return value


def _u(source, address):
    return struct.unpack('<I', _read(source, address, 4))[0]


def _pointer(value, size=4):
    # Menu assets/objects live in ordinary EE RAM, not expanded fighter storage.
    return 0x100000 <= value <= 0x2000000 - size and value % 4 == 0


@dataclass(frozen=True)
class MenuScene:
    scene: int
    manager: int
    object: int
    kind: str | None
    ready: bool


def read_scene(source, *, allow_owned_main=False):
    """Read from a PINE-like reader or an offline RAM image; never write memory."""
    manager = _u(source, SCENE_MANAGER)
    if not _pointer(manager, 0x634):
        return MenuScene(-1, manager, 0, None, False)
    scene = _u(source, manager + 0x18)
    main, duel = _u(source, MAIN_OBJECT), _u(source, DUEL_OBJECT)
    if scene == MAIN:
        ready = False
        if _pointer(main, 0x180):
            text = _u(source, main + 8)
            if _pointer(text, 0x180):
                ready = (_u(source, text) == 64 and _u(source, text + 4) == 0x140 and
                         _read(source, text + 0x140, 16) in MAIN_MENU_PREFIXES and
                         bool(_u(source, main + 0x18) & 2) and
                         not (_u(source, main + 0x108) & 3))
        # Native grouped pages own row arrays and image pointers while leased.
        # Recovery may archive a verified lease, provided restore expires it.
        import native_mode_menu
        if hasattr(source,'read') or len(source)>=native_mode_menu.END:
            if (_u(source,native_mode_menu.CONTROL)==native_mode_menu.MAGIC and
                    _u(source,native_mode_menu.CONTROL+4) in (1,2)):
                ready=ready and allow_owned_main and owned_main(source,main)
        return MenuScene(scene, manager, main, 'main', ready and _u(source, LOOP_FLAG) == 0)
    if scene in (SINGLE_SELECT, TEAM_SELECT):
        ui = _u(source, COMMON_UI)
        ready = (main == duel == 0 and _pointer(ui, 0x30) and
                 bool(_u(source, ui + 8) & 1) and _pointer(_u(source, ui), 0x40))
        return MenuScene(scene, manager, ui, 'character_select', ready and _u(source, LOOP_FLAG) == 0)
    return MenuScene(scene, manager, 0, None, False)


def owned_main(source, obj):
    """Only this pager's live main-menu lease can be a recovery checkpoint."""
    import native_mode_menu as menu
    c=menu.CONTROL
    if (_u(source,c)!=menu.MAGIC or _u(source,c+4) not in (1,2) or
            _u(source,c+20)!=obj or _u(source,c+0x14C)!=_u(source,obj+4)):
        return False
    count=_u(source,c+0x12C)
    if count not in (9,10) or tuple(_u(source,c+0x100+4*i) for i in range(count)) not in menu.assets.NATIVE_ROW_LAYOUTS:
        return False
    if _u(source,c+4)==1:
        expected=(_u(source,c+0x144),_u(source,c+0x148))
    else:
        page=_u(source,c+8)
        if page>=len(menu.PAGES):return False
        expected=(menu.OFF,menu.ON) if page==0 else (menu.ALT_OFF,menu.ALT_ON)
    return (_u(source,obj+0x60),_u(source,obj+0x70))==expected


def return_destination(result_flags, reason_flags):
    """Match native336A90 dispatch, including its main-menu precedence."""
    if not result_flags & 8:
        return None
    if reason_flags & 8:
        return 'main'
    if reason_flags & 0x10:
        return 'character_select'
    if reason_flags & 0x80:
        return 'main'  # Safe top-level checkpoint for native Duel-menu exits.
    return None


# The same dispatcher also sends reason 0x800 to scene 6 and 0x1000 to scene 0x38
# (disassembled at 336BC8/336BE0). No clean checkpoint is captured for either.
FALLBACK_REASONS = 0x800 | 0x1000


# The boot/title scene. A match never exits to it: seen after a match with no result latched, the game
# restarted (a PCSX2 reset, or the game rebooting itself after a crash).
BOOT = 1


def restarted(result_flags, reason_flags, scene):
    """True for the boot scene after a match with no result latched (autopilot.game_restarted)."""
    return scene == BOOT and not result_flags & 8


def fallback_destination(result_flags, reason_flags, scene=None):
    """The safe top level for a post-match exit no captured menu matches, or None.

    'main' for a latched result whose reason is 0x800 or 0x1000, and for the Duel menu
    (scene 0x26) reached before any destination latched; return_destination wins over
    both. Callers act on it only once two consecutive polls agree.
    """
    if return_destination(result_flags, reason_flags) is not None:
        return None
    if result_flags & 8 and reason_flags & FALLBACK_REASONS:
        return 'main'
    if scene == DUEL:
        return 'main'
    return None


@lru_cache(maxsize=1)
def native_guards():
    from prototype import ROOT, elf_reader
    from selected_team_capture import NATIVE_RANGES
    readelf = elf_reader(elf_path(ROOT))[2]
    return tuple((address, readelf(address, size)) for address, size in
                 (*NATIVE_RANGES, (A(0x1C2A28), 8), (A(0x12BC8C), 8)))


def validate_clean(ram, expected_kind=None, expected_scene=None, *, allow_owned_main=False):
    if len(ram) != RAM_BYTES:
        raise ValueError('Clean menu checkpoint requires a complete 128 MiB image')
    if any(_u(ram, p) for p in (0xD8080, A(0x2FF084), A(0x2FF08C), LOOP_FLAG)):
        raise ValueError('Menu checkpoint contains an active or expanded battle')
    for address, expected in native_guards():
        if _read(ram, address, len(expected)) != expected:
            raise ValueError(f'Menu checkpoint contains modified battle code at {address:08X}')
    scene = read_scene(ram,allow_owned_main=allow_owned_main)
    if scene.kind=='main' and owned_main(ram,scene.object):
        if not allow_owned_main:raise ValueError('Owned menu checkpoint was not authorized')
        import native_mode_menu as menu
        for p,code in menu.old.code_pieces()[:1]+menu.code_pieces():
            if _read(ram,p,len(code))!=code:raise ValueError('Owned menu recovery code changed')
    if not scene.ready or (expected_kind is not None and scene.kind != expected_kind):
        raise ValueError('The game left the requested ready menu during checkpoint capture')
    if expected_scene is not None and scene.scene != expected_scene:
        raise ValueError('The character-selection type changed during capture')
    return scene


def _digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class MenuCheckpoints:
    """One watcher lifetime; observe results each poll, consider only clean menus.

    consider(reader, clean=...) waits for two equal ready observations and saves
    once per menu visit. begin_battle() resets the result-intent latch. restore()
    selects the latched destination by default, or accepts an explicit kind.
    Missing character checkpoints raise instead of silently sending users home.
    """
    def __init__(self, directory=None, *, session_factory=None, archive_reader=None, card_reader=None, live_reader=None):
        if session_factory is None:
            from fresh_team_trainer import Session
            session_factory = Session
        if archive_reader is None:
            from camera_snapshot import read_ram
            archive_reader = read_ram
        if directory is None:
            from prototype import ROOT
            directory = ROOT / 'analysis/autopilot/menu-checkpoints' / uuid.uuid4().hex
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.session_factory, self.archive_reader = session_factory, archive_reader
        self.records = {}
        self.destination = None
        self.pending_scene = self.handled_scene = None
        self.card_reader = card_reader or saved_game_state.card_signature
        self.card_revision = self.card_reader()
        if live_reader is None:
            from pine import PineClient
            live_reader=lambda:PineClient(timeout=5)
        self.live_reader=live_reader

    def begin_battle(self):
        self.destination = None
        self.pending_scene = self.handled_scene = None

    def observe_result(self, result_flags, reason_flags):
        requested = return_destination(result_flags, reason_flags)
        if requested is not None:
            self.destination = requested
        return self.destination

    def consider(self, source, *, clean):
        scene = read_scene(source) if clean else None
        return self.consider_scene(scene, clean=clean)

    def consider_scene(self, scene, *, clean):
        """Consider a detached observation after its PINE reader has closed."""
        revision=self.card_reader()
        if revision!=self.card_revision:
            self.card_revision=revision
            self.pending_scene=self.handled_scene=None
            return None  # Wait for another stable ready observation after IO.
        if clean and not isinstance(scene, MenuScene):
            raise ValueError('A clean menu observation must be a MenuScene')
        if not clean:
            scene = None
        if scene is None or not scene.ready:
            self.pending_scene = self.handled_scene = None
            return None
        # Refresh every clean visit, including returning from the options/save
        # screen. Keeping the first main menu forever reverts later settings.
        if scene == self.handled_scene:
            return None
        if scene != self.pending_scene:
            self.pending_scene = scene
            return None
        record = self.capture(scene)
        self.handled_scene = scene
        return record

    def capture(self, scene):
        if not isinstance(scene, MenuScene) or not scene.ready or scene.kind not in ('main', 'character_select'):
            raise ValueError('Capture requires a verified ready menu observation')
        session = None
        try:
            session = self.session_factory()
            ram = session.snapshot('clean-' + scene.kind, require_running=False)
            validate_clean(ram, scene.kind, scene.scene, allow_owned_main=True)
            path = Path(session.source).resolve()
            # Session.snapshot already CRC-validates the ZIP and records the
            # owned slot receipt before returning its immutable archive.
            if not path.is_file() or not path.is_relative_to(Path(session.run).resolve()):
                raise ValueError('Trainer returned an unowned menu archive')
            record = dict(kind=scene.kind, scene=scene.scene, archive=str(path), sha256=_digest(path))
            if scene.kind=='main' and owned_main(ram,scene.object):record['owned_menu']=True
            if self.card_reader()!=self.card_revision:
                raise ValueError('Memory card changed during menu capture; waiting for save completion')
            write_json(self.directory / (scene.kind + '.json'), record)
            self.records[scene.kind] = record
            return dict(record)
        finally:
            if session is not None:
                session.close()

    def archive(self, kind):
        record = self.records.get(kind)
        if record is None:
            raise ValueError(f'No clean {kind.replace("_", " ")} checkpoint was captured')
        path = Path(record['archive'])
        if not path.is_file() or _digest(path) != record['sha256']:
            raise ValueError('The immutable menu checkpoint changed; refusing to load it')
        ram = self.archive_reader(path)
        validate_clean(ram, kind, record['scene'],allow_owned_main=record.get('owned_menu',False))
        return path, ram

    def restore(self, kind=None):
        kind = kind or self.destination or 'main'
        if kind not in ('main', 'character_select'):
            raise ValueError('Unknown menu return destination')
        path, ram = self.archive(kind)
        session = None
        try:
            session = self.session_factory()
            session.source = path
            # Scratch for install()'s ACK read only; the run's cleanup removes it.
            session._raw_captures = getattr(session, '_raw_captures', set()) | {session.ram_path}
            session.ram_path.write_bytes(ram)
            # Restore clean code/scene state while retaining the game's current
            # saved options/progress. No memory-card file is replaced or edited.
            with self.live_reader() as p:
                payload=saved_game_state.preserve(p,ram)
            if self.records[kind].get('owned_menu'):
                # Expire this verified archived lease before rearming. The
                # guest restores native rows/atlases; never retain a queued mode.
                import native_mode_menu as menu
                for off in (16,menu.CHECKPOINT_WAIT,menu.PENDING_CHOICE):
                    at=menu.CONTROL+off
                    payload['blocks'].append(dict(address=at,expected_hex=_read(ram,at,4).hex(),data_hex='00000000'))
            session.install(dict(serial=SERIAL, crc=CRC, blocks=payload['blocks']),
                            'return-' + kind, require_running=False)
            # install supplies a fresh ACK and waits for it through owned
            # slots, even when the same menu image was already loaded before.
            self.pending_scene = self.handled_scene = read_scene(ram)
            self.destination = None
            return kind
        finally:
            if session is not None:
                session.close()
