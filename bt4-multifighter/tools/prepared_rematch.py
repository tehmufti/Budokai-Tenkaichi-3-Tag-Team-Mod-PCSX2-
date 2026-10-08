"""Stage an immutable playable checkpoint for an acknowledged rematch handoff.

Playable exports deliberately disable the native transport magic so they can
run without a watcher. Automatic rematches restore a separate held copy first,
then refresh FFA entropy and request native intro/start before releasing it.
"""
from native_map import A, CRC, SERIAL
import json
import shutil
import struct
import time
from pathlib import Path
import battle_modes
import ffa_targeting
import fresh_team_combat as core
import native_preparation as native
import team_start_gate as start
import team_intro as intro
import guest_loading_screen as loading
from fresh_team_trainer import ACK_ADDRESS
from battle_mode_policy import ACTOR_COUNTS


def plan(ram, *, show_loading=True):
    if len(ram)!=0x8000000:raise ValueError('Rematch requires complete 128 MiB EE RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    # Older manual-mode checkpoints already start themselves. They do not have
    # the native transaction service needed for a race-free entropy update.
    transport=native.captured_transport(ram)
    selected=battle_modes.validate_memory(ram)
    if not transport:
        if selected=='ffa':raise ValueError('FFA rematches require the current native preparation service')
        return None
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if count not in ACTOR_COUNTS or tuple(struct.unpack_from('<4I',ram,core.MODE))!=(1,count,manager,count):
        raise ValueError('Rematch is not a captured prepared match')
    if tuple(struct.unpack_from('<4I',ram,start.CONTROL)) not in ((1,0,manager,count),(1,1,manager,count)) or u(start.CONTROL+20):
        raise ValueError('Rematch start gate is already released or belongs to another capture')
    battle=u(intro.BATTLE)
    if not 0x100000<=battle<0x8000000-0x200 or u(battle) not in (2,3) or u(battle+260)!=A(0x2C6070):
        raise ValueError('Rematch native battle phase changed')
    pointers=bytes(ram[core.POINTERS:core.POINTERS+count*4])
    if pointers!=ram[start.CONTROL+0x80:start.CONTROL+0x80+count*4]:
        raise ValueError('Rematch captured start actors changed')
    for i in range(count):
        actor=u(core.POINTERS+4*i)
        if not 0x100000<=actor<0x8000000-0x1600 or u(actor)!=i or u(actor+0x1278)!=0:
            raise ValueError('Rematch actors are not held in the captured start gate')
    has_intro=u(intro.CONTROL)==1
    if has_intro and ((u(intro.CONTROL+8),u(intro.CONTROL+12),u(intro.CONTROL+16))!=(manager,count,battle)
                      or u(intro.CONTROL+20) or u(intro.REQUEST) not in (0,1)):
        raise ValueError('Rematch intro capture changed')
    if u(native.CONTROL) not in (0,native.MAGIC) or u(native.CONTROL+4)!=u(native.CONTROL+8):
        raise ValueError('Rematch transport has a pending or unknown transaction')
    pieces=native.upgrade_blocks(ram)
    def word(p,value):
        data=struct.pack('<I',value)
        pieces.append(dict(address=p,expected_hex=ram[p:p+4].hex(),data_hex=data.hex()))
    word(native.CONTROL,native.MAGIC);word(native.CONTROL+16,1);word(native.CONTROL+20,0)
    word(native.CONTROL+24,manager);word(start.REQUEST,0)
    if has_intro:word(intro.REQUEST,0)
    # The original saved loading packet already contains this exact roster.
    # Reactivate it in the staged copy so even the first restored GS frame is
    # covered while the watcher waits for the new load/hold acknowledgements.
    # A v3 checkpoint's pointer (0x07480000..) is not in the v4 BUFFERS, so its
    # first restored frame is simply uncovered. The size bound is the guest's.
    cover=False
    if show_loading and all(ram[p:p+len(data)]==data for p,data in loading.code_pieces()):
        packet=u(loading.CONTROL+4)
        if packet in loading.BUFFERS and 128<=u(packet)<loading.CAPACITY-15-loading.DESCRIPTOR and not u(packet)&15:
            for p,value in ((loading.CONTROL,loading.MAGIC),(loading.CONTROL+16,0),(loading.CONTROL+32,0)):word(p,value)
            cover=True;loading.invalidate_buffers()   # the restored buffers are not what this process wrote
    return dict(serial=SERIAL,crc=CRC,blocks=pieces,manager=manager,count=count,
                battle=battle,mode=selected,ack=bytes(ram[ACK_ADDRESS:ACK_ADDRESS+16]),
                pointers=pointers,has_intro=has_intro,cover=cover)


def require_capture(p,capture):
    manager,count=capture['manager'],capture['count']
    if (p.read(ACK_ADDRESS,16)!=capture['ack'] or p.read_u32(core.ACTORS)!=manager or
        tuple(struct.unpack('<4I',p.read(core.MODE,16)))!=(1,count,manager,count) or
        p.read_u32(intro.BATTLE)!=capture['battle'] or
        tuple(struct.unpack('<2I',p.read(start.CONTROL+8,8)))!=(manager,count) or
        p.read(core.POINTERS,4*count)!=capture['pointers'] or
        p.read(start.CONTROL+0x80,4*count)!=capture['pointers']):
        raise ValueError('Prepared rematch capture changed before release acknowledgement')


def complete(p,capture,timeout=10):
    """Called only after the fresh checkpoint sentinel has been replaced."""
    loading.invalidate_buffers()
    try:
        require_capture(p,capture)
        if (not native.installed(p) or p.read_u32(native.CONTROL)!=native.MAGIC or
            p.read_u32(native.CONTROL+24)!=capture['manager'] or p.read_u32(native.CONTROL+16)!=1):
            raise ValueError('Prepared rematch transport ownership changed')
        native.quiet(p,timeout=timeout)
        require_capture(p,capture)
        live=native.read_ram(p)
        if battle_modes.validate_memory(live)!=capture['mode']:
            raise ValueError('Prepared rematch mode changed')
        changes=ffa_targeting.reseed_memory(live) if capture['mode']=='ffa' else dict(blocks=[])
        request=intro.REQUEST if capture['has_intro'] else start.REQUEST
        if p.read_u32(request) or p.read_u32(start.CONTROL)!=1 or p.read_u32(start.CONTROL+20):
            raise ValueError('Prepared rematch start request changed while held')
        changes['blocks'].append(dict(address=request,expected_hex='00000000',data_hex='01000000'))
        changes['serial']=SERIAL;changes['crc']=CRC
        native.apply(p,changes,timeout=timeout)
        require_capture(p,capture)
        for b in changes['blocks']:
            if p.read(b['address'],len(bytes.fromhex(b['data_hex']))).hex()!=b['data_hex']:
                raise ValueError('Prepared rematch seed/start transaction did not commit')
        native.resume(p)
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            require_capture(p,capture)
            if p.read_u32(native.CONTROL+16)!=0:
                raise ValueError('Prepared rematch dispatch was held again before release')
            started=p.read_u32(start.CONTROL)==0 and p.read_u32(start.CONTROL+20)==1
            playing=(capture['has_intro'] and p.read_u32(intro.CONTROL+20)==1 and
                     p.read_u32(capture['battle'])==1 and p.read_u32(start.CONTROL)==1)
            if p.read_u32(native.CONTROL+20)==0 and (started or playing):return True
            time.sleep(.02)
        raise TimeoutError('Prepared rematch did not acknowledge native intro/start release')
    except BaseException:
        # Preserve the first error. Never hold a foreign checkpoint if another
        # world replaced this capture during the operation.
        try:
            require_capture(p,capture)
            if native.installed(p) and p.read_u32(native.CONTROL)==native.MAGIC:
                native.quiet(p,timeout=2)
        except Exception:pass
        raise


class ArchiveCache:
    """Reuse one watcher's decoded playable and its last staged rematch archive.

    patch_state.patch is deterministic: the same source bytes and manifest give a
    byte-identical archive (test_prepared_rematch reproduces a recorded rematch
    archive). Both entries are keyed on the source's path, size, mtime and SHA-256;
    the archive also on the exact manifest, whose preserve blocks carry the live
    save data. A hit re-hashes the retained archive before copying it and the copy
    afterwards (record_slot only proves slot == staged copy), so the slot receives
    exactly what patch() would write. Anything unexpected takes the uncached path,
    which is the previous code. Nothing is built ahead of a rematch.
    """
    def __init__(self):
        self.playable=None  # (source identity, decoded EE RAM)
        self.archive=None   # (source identity, manifest JSON, archive path, archive SHA-256)

    @staticmethod
    def identity(source):
        import patch_state
        path=Path(source).resolve(strict=True);stat=path.stat()
        return str(path),stat.st_size,stat.st_mtime_ns,patch_state.file_digest(path)

    def read(self,source):
        """camera_snapshot.read_ram(source), decoded once while the file is unchanged."""
        from camera_snapshot import read_ram
        try:identity=self.identity(source)
        except OSError:return read_ram(source)
        if self.playable is not None and self.playable[0]==identity:return self.playable[1]
        ram=read_ram(source)
        try:unchanged=self.identity(source)==identity
        except OSError:unchanged=False
        self.playable=(identity,ram) if unchanged else None
        return ram

    def stage(self,source,manifest,staged):
        """Create staged exactly as patch_state.patch(source,manifest,staged); True if reused."""
        import patch_state
        staged=Path(staged)
        try:key=(self.identity(source),json.dumps(manifest,sort_keys=True,separators=(',',':')))
        except (OSError,TypeError,ValueError):key=None
        if key is not None and self.archive is not None and self.archive[:2]==key:
            if self.copy_verified(*self.archive[2:],staged):
                # The newest copy is the one the slot receipt keeps retained.
                self.archive=(*key,staged.resolve(),self.archive[3])
                return True
            self.archive=None
        report=patch_state.patch(source,manifest,staged)
        if (key is not None and isinstance(report,dict) and report.get('source_sha256')==key[0][3] and
                Path(report.get('output','')).resolve()==staged.resolve()):
            self.archive=(*key,staged.resolve(),report['output_sha256'])
        return False

    @staticmethod
    def copy_verified(archive,digest,staged):
        """Copy only a verified archive to a new file patch() would also accept."""
        import patch_state
        created=False
        try:
            if (staged.suffix.lower()!='.p2s' or staged.exists() or
                    not staged.resolve().is_relative_to(patch_state.OUTPUT_ROOT.resolve()) or
                    patch_state.file_digest(archive)!=digest):
                return False
            with Path(archive).open('rb') as reader,staged.open('xb') as writer:
                created=True
                shutil.copyfileobj(reader,writer,1<<20)
            if patch_state.file_digest(staged)==digest:return True
        except OSError:pass
        # Remove only this call's exclusively created copy; patch() then runs as before.
        if created:staged.unlink(missing_ok=True)
        return False
