"""Online overhaul: the recoveries and identity rules added after Version 14.6 (no game, emulator or network peer).

Synthetic fixtures only. Run: python -m unittest discover -s release_tools/online-overhaul-tests -p 'test_*.py'
"""
import base64
import hashlib
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
import zipfile
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
_RUNTIME = tempfile.mkdtemp(prefix='ttm-overhaul-tests-')
os.environ['TTM_KIT_RUNTIME'] = _RUNTIME            # nothing these tests write lands in the source tree
sys.path.insert(0, str(ROOT / 'bt3-multifighter/online/netplay'))
import kit_paths  # noqa: E402
import kit_codes  # noqa: E402
import kit_emu  # noqa: E402
import kit_fight  # noqa: E402
import kit_ident  # noqa: E402
import kit_install  # noqa: E402
import kit_ipc  # noqa: E402
import kit_lobby  # noqa: E402
import kit_lockstep  # noqa: E402
import kit_match  # noqa: E402
import kit_net  # noqa: E402
import kit_postmatch  # noqa: E402
import kit_resync  # noqa: E402
import kit_services  # noqa: E402
import kit_state  # noqa: E402
import kit_win  # noqa: E402
import ttm_online  # noqa: E402
from kit_codes import KitError  # noqa: E402
from pinelink import nc  # noqa: E402

try:
    import zstandard
except ImportError:                                  # the installation's Python has it; a bare Python may not
    zstandard = None


# ---- a savestate as PCSX2 2.8 writes it: ZIP method 93 (Zstandard), frames without a content size -------------------
def pcsx2_state(path, memory, method=kit_state.ZIP_ZSTANDARD, damage=False):
    entries = [('PCSX2 Savestate Version.id', b'\x00' * 36, zipfile.ZIP_STORED), (kit_state.MEMORY, memory, method),
               ('iopMemory.bin', b'\x11' * 4096, method)]
    with open(path, 'wb') as out:
        central = []
        for name, data, how in entries:
            if how == kit_state.ZIP_ZSTANDARD:
                packed = zstandard.ZstdCompressor(level=1, write_content_size=False).compress(data)
            elif how == zipfile.ZIP_DEFLATED:
                packer = zlib.compressobj(1, zlib.DEFLATED, -15)
                packed = packer.compress(data) + packer.flush()
            else:
                packed = data
            crc = zlib.crc32(data) & 0xFFFFFFFF
            if damage and name == kit_state.MEMORY:
                crc ^= 1
            raw_name = name.encode('ascii')
            offset = out.tell()
            out.write(struct.pack('<4sHHHHHIIIHH', b'PK\x03\x04', 20, 0, how, 0, 0x21, crc, len(packed), len(data),
                                  len(raw_name), 0) + raw_name + packed)
            central.append(struct.pack('<4sHHHHHHIIIHHHHHII', b'PK\x01\x02', 20, 20, 0, how, 0, 0x21, crc, len(packed),
                                       len(data), len(raw_name), 0, 0, 0, 0, 0, offset) + raw_name)
        start = out.tell()
        out.write(b''.join(central))
        out.write(struct.pack('<4sHHHHIIH', b'PK\x05\x06', 0, 0, len(central), len(central), out.tell() - start,
                              start, 0))
    return path


@unittest.skipIf(zstandard is None, 'the zstandard module is not installed in this Python')
class StatesPcsx2Saved(unittest.TestCase):
    """Resync and "watch / rejoin a running fight" read the state PCSX2 itself just saved."""

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(dir=_RUNTIME))
        self.memory = bytearray(os.urandom(4096) * 64 + b'\0' * (kit_state.EE_SIZE - 4096 * 64))
        struct.pack_into('<I', self.memory, 0x100000, 0x1234ABCD)
        self.memory = bytes(self.memory)
        self.state = pcsx2_state(self.folder / 'saved.p2s', self.memory)

    def test_zipfile_alone_cannot_read_it(self):
        with zipfile.ZipFile(self.state) as archive:
            self.assertEqual(archive.getinfo(kit_state.MEMORY).compress_type, 93)
            with self.assertRaises(NotImplementedError):           # what ended the host's fight for everybody
                archive.read(kit_state.MEMORY)

    def test_words_memory_and_bytes(self):
        self.assertEqual(kit_state.read_words(self.state, [0x100000]), {0x100000: 0x1234ABCD})
        self.assertEqual(kit_state.read_memory(self.state), self.memory)
        self.assertEqual(kit_state.read_bytes(self.state, 0x100000, 4), bytes.fromhex('cdab3412'))

    def test_machine_copy_of_a_saved_state_is_a_deflate_archive_with_the_same_bytes(self):
        archive = kit_state.StateArchive(self.state)
        target = self.folder / 'copy.p2s'
        kit_state.patch_words(self.state, target, {0x100000: (0x1234ABCD, 0x55AA55AA)}, archive=archive)
        with zipfile.ZipFile(target) as written:
            kinds = {info.filename: info.compress_type for info in written.infolist()}
        self.assertEqual(kinds[kit_state.MEMORY], zipfile.ZIP_DEFLATED)           # what PCSX2 loads from the kit
        changed = bytearray(self.memory)
        struct.pack_into('<I', changed, 0x100000, 0x55AA55AA)
        self.assertEqual(kit_state.read_memory(target), bytes(changed))

    def test_a_damaged_entry_is_refused(self):
        bad = pcsx2_state(self.folder / 'bad.p2s', self.memory, damage=True)
        with self.assertRaisesRegex(ValueError, 'damaged'):
            kit_state.read_memory(bad)

    def test_deflate_states_read_as_before(self):
        plain = pcsx2_state(self.folder / 'deflate.p2s', self.memory, method=zipfile.ZIP_DEFLATED)
        self.assertEqual(kit_state.read_words(plain, [0x100000]), {0x100000: 0x1234ABCD})


# ---- identity -----------------------------------------------------------------------------------------------------------
def identity(**changes):
    base = dict(protocol=kit_ident.PROTOCOL, code=dict(digest='c' * 64),
                pcsx2=dict(digest='p' * 64, tested=True, savestate=1, version='2.8.2', platform='Windows'),
                patches=dict(digest='a' * 64, pnach_sha256=['a' * 64], memcards='m', transfer=True),
                settings=dict(digest='s', forced={}, other={}, safe={}),
                disc=dict(serial='SLUS_216.78', crc='428113C2', loaded_elf_sha256='e', dbzp_sha256='d', afs_tables='t'),
                bios=dict(sha256='b'), bios_policy='note', mod=dict(version='0.1.0-beta.14.6', integrated=True))
    for key, value in changes.items():
        base[key] = dict(base[key], **value) if isinstance(base.get(key), dict) and isinstance(value, dict) else value
    return base


class Identity(unittest.TestCase):
    def test_another_language_generates_another_patch_and_is_not_refused(self):
        found = kit_ident.compare(identity(), identity(patches=dict(digest='b' * 64, pnach_sha256=['b' * 64])))
        self.assertEqual([(code, level) for code, level, _ in found], [('TTM-NET-04', 'note')])
        self.assertIn('every PC uses the host', kit_ident.note_line(*[(c, v) for c, _, v in found][0]))

    def test_a_peer_that_cannot_fetch_the_patch_is_still_refused(self):
        found = kit_ident.compare(identity(), identity(patches=dict(digest='b' * 64, transfer=False)))
        self.assertIn(('TTM-NET-04', 'refuse'), [(code, level) for code, level, _ in found])

    def test_different_mod_versions_are_refused_first_and_named(self):
        found = kit_ident.compare(identity(), identity(mod=dict(version='0.1.0-beta.14.5'), code=dict(digest='x' * 64)))
        self.assertEqual(found[0][:2], ('TTM-NET-34', 'refuse'))
        self.assertEqual(found[0][2], dict(mine='Version 14.6', theirs='Version 14.5'))
        text = KitError('TTM-NET-34', **found[0][2])
        self.assertIn('Version 14.6', str(text))
        self.assertIn('Versión', text.block('es').replace('Version', 'Versión'))
        self.assertIn('actualizador', text.block('es'))

    def test_identical_versions_and_files_have_no_findings(self):
        self.assertEqual(kit_ident.compare(identity(), identity()), [])

    def test_a_standalone_peer_without_a_version_is_judged_by_its_files(self):
        self.assertEqual(kit_ident.compare(identity(), identity(mod=dict(version=None, integrated=False))), [])

    def test_friendly_version(self):
        self.assertEqual(kit_ident.friendly_version('0.1.0-beta.14.6'), 'Version 14.6')
        self.assertEqual(kit_ident.friendly_version('0.1.0-beta.8'), 'Version 8')
        self.assertEqual(kit_ident.friendly_version('1.0.0'), '1.0.0')

    def test_every_code_has_both_languages_and_no_kit_zip_advice_for_installations(self):
        self.assertEqual(set(kit_codes.CODES), set(kit_codes.CODES_ES))
        for code in ('TTM-NET-01', 'TTM-NET-02', 'TTM-NET-03', 'TTM-NET-04', 'TTM-NET-05', 'TTM-NET-25', 'TTM-NET-27',
                     'TTM-NET-28', 'TTM-NET-34'):
            for table in (kit_codes.CODES, kit_codes.CODES_ES):
                self.assertNotIn('ZIP', table[code][2], code)

    def test_an_untested_build_every_pc_shares_is_not_refused_again_at_load(self):
        info = dict(version='PCSX2 v2.6.3', **kit_ident.GAME)
        with patch.object(kit_paths, 'INTEGRATED', True):
            self.assertEqual(kit_ident.runtime_problems(info, build=dict(tested=False)), [])
            self.assertEqual([c for c, _ in kit_ident.runtime_problems(info, build=dict(tested=True))], ['TTM-NET-28'])
        with patch.object(kit_paths, 'INTEGRATED', False):
            self.assertEqual([c for c, _ in kit_ident.runtime_problems(info, build=dict(tested=False))], ['TTM-NET-28'])
        self.assertEqual(kit_ident.runtime_problems(dict(version='PCSX2 v2.8.2', **kit_ident.GAME)), [])

    def test_a_different_running_disc_is_still_refused(self):
        info = dict(version='PCSX2 v2.8.2', serial='SLES-00000', crc='00000000')
        with patch.object(kit_paths, 'INTEGRATED', True):
            self.assertEqual([c for c, _ in kit_ident.runtime_problems(info, build=dict(tested=False))], ['TTM-NET-06'])


class HostPatch(unittest.TestCase):
    PATCH = (b'// BT3 owned loading surface\n' + b''.join(b'patch=1,EE,%08X,word,%08X\n' % (0x06000000 + 4 * i, i)
                                                          for i in range(4000)) +
             b'patch=1,EE,D0123456,extended,0000FFFF\n')

    def setUp(self):
        self.runtime = Path(tempfile.mkdtemp(dir=_RUNTIME))
        self.sha = hashlib.sha256(self.PATCH).hexdigest()

    def test_a_real_patch_passes_and_is_stored_by_its_hash(self):
        self.assertIsNone(kit_ident.patch_problem(self.PATCH, self.sha))
        path = kit_ident.store_patch(self.PATCH, self.sha, self.runtime)
        self.assertEqual(path.name, self.sha + '.pnach')
        self.assertEqual(kit_ident.pnach_files(self.runtime), {self.sha: path})
        self.assertEqual(list(path.parent.glob('*.part')), [])

    def test_crlf_patch_lines_are_accepted(self):
        data = self.PATCH.replace(b'\n', b'\r\n')
        self.assertIsNone(kit_ident.patch_problem(data, hashlib.sha256(data).hexdigest()))

    def test_wrong_hash_other_content_and_absurd_sizes_are_refused(self):
        self.assertIn('SHA-256', kit_ident.patch_problem(self.PATCH + b'patch=1,EE,0,word,0\n', self.sha))
        for junk in (b'[Cheats]\n', b'gsaspectratio=16:9\n', b'patch=1,EE,00100000,word,0;rm -rf\n', b'\x00\x01\x02\n'):
            data = self.PATCH + junk
            self.assertIn('not a patch line', kit_ident.patch_problem(data, hashlib.sha256(data).hexdigest()), junk)
        self.assertIn('size', kit_ident.patch_problem(b'', hashlib.sha256(b'').hexdigest()))
        self.assertIn('name', kit_ident.patch_problem(self.PATCH, '../../evil'))
        with self.assertRaises(KitError):
            kit_ident.store_patch(self.PATCH, 'f' * 64, self.runtime)
        self.assertEqual(kit_ident.pnach_files(self.runtime), {})

    def test_host_and_guest_exchange_it_over_patch_messages(self):
        """The controller's PATCH_WANT / PATCH pair, host and guest wired back to back (no sockets)."""
        import kit_controller
        host_runtime, guest_runtime = self.runtime / 'host', self.runtime / 'guest'
        kit_ident.store_patch(self.PATCH, self.sha, host_runtime)
        sent, logs = [], []

        class Wire:
            def send_json(self, **message):
                sent.append(json.loads(json.dumps(message)))
        host = object.__new__(kit_controller.Controller)
        host.role, host.members, host.jobs = 'host', {2: dict(channel=Wire())}, []
        host.say = logs.append
        host.busy = lambda name: False
        host.job = lambda name, fn, *a, then=None, fail=None: then(fn(*a))
        host.send_to = lambda ident, **m: sent.append(m)
        guest = object.__new__(kit_controller.Controller)
        guest.role, guest.phase, guest.match = 'guest', 'lobby', None
        guest.say = logs.append
        guest.preboots = []
        guest.preboot_game = guest.preboots.append
        guest.send = lambda **m: sent.append(m) or True
        guest.patch_wanted = None
        with patch.object(kit_controller, 'PATCH_PART', 4096):
            with patch.object(kit_paths, 'RUNTIME', guest_runtime):
                self.assertTrue(guest.want_patch(self.sha, then='preboot'))
            self.assertEqual(sent.pop(), dict(type='PATCH_WANT', sha256=self.sha))
            with patch.object(kit_paths, 'RUNTIME', host_runtime):
                host.msg_PATCH_WANT(2, dict(sha256=self.sha))
            self.assertGreater(len(sent), 1)                       # several parts
            with patch.object(kit_paths, 'RUNTIME', guest_runtime):
                for message in sent:
                    guest.msg_PATCH(1, message)
                self.assertEqual(kit_ident.pnach_files()[self.sha].read_bytes(), self.PATCH)
        self.assertIsNone(guest.patch_wanted)
        self.assertEqual(guest.preboots, [self.sha])              # its idle PCSX2 starts with the room's patch

    def test_a_tampered_part_never_becomes_a_file(self):
        import kit_controller
        guest = object.__new__(kit_controller.Controller)
        guest.role, guest.phase, guest.match, guest.say = 'guest', 'lobby', None, lambda text: None
        guest.send = lambda **m: True
        guest.patch_wanted = None
        packed = zlib.compress(self.PATCH + b'x')
        with patch.object(kit_paths, 'RUNTIME', self.runtime):
            guest.want_patch(self.sha)
            guest.msg_PATCH(1, dict(sha256=self.sha, index=0, count=1, size=len(self.PATCH) + 1,
                                    data=base64.b64encode(packed).decode()))
            self.assertEqual(kit_ident.pnach_files(), {})
        self.assertIsNone(guest.patch_wanted)


# ---- the TCP channel ----------------------------------------------------------------------------------------------------
def pair():
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    a = socket.create_connection(listener.getsockname())
    b, _ = listener.accept()
    listener.close()
    return kit_net.Channel(a).blocking(), kit_net.Channel(b).blocking()


class ChannelNeverHoldsTheLoop(unittest.TestCase):
    def tearDown(self):
        for ch in getattr(self, 'channels', ()):
            ch.close()

    def test_control_frames_queue_behind_a_transfer_and_keep_their_order(self):
        a, b = self.channels = pair()
        with a.send_lock:                                         # a transfer thread is inside a chunk
            started = time.monotonic()
            for n in range(5):
                self.assertTrue(a.try_send(type='LOBBY', n=n))
            self.assertLess(time.monotonic() - started, 0.5)      # the loop did not wait for the lock
            self.assertEqual(len(a.outbox), 5)
        a.send_chunk(b'next chunk')                               # the transfer's next frame flushes them first
        time.sleep(0.1)
        frames = b.poll_frames()
        self.assertEqual([f[1].get('n') for f in frames[:5]], [0, 1, 2, 3, 4])
        self.assertEqual(frames[5], ('B', b'next chunk'))

    def test_queued_frames_leave_on_the_next_loop_pass_without_a_transfer(self):
        a, b = self.channels = pair()
        with a.send_lock:
            a.try_send(type='PING')
        a.poll_frames()                                           # the loop's own pass
        time.sleep(0.1)
        self.assertEqual([f[1]['type'] for f in b.poll_frames()], ['PING'])

    def test_a_member_that_takes_nothing_is_given_up_after_the_send_timeout(self):
        a, b = self.channels = pair()
        a.sock.settimeout(0.3)                                    # SEND_TIMEOUT, shortened
        blob = b'x' * kit_net.CHUNK
        started = time.monotonic()
        with self.assertRaises(OSError):
            for _ in range(4096):                                 # b never reads: the buffers fill, then the deadline
                a.send_chunk(blob)
        self.assertLess(time.monotonic() - started, 20)
        self.assertTrue(a.closed)
        self.assertFalse(a.try_send(type='PING'))

    def test_silence_counts_a_stalled_transfer(self):
        a, _ = self.channels = pair()
        now = time.monotonic()
        a.transfers = 1
        a.last_rx = a.last_tx = now - 40
        self.assertGreater(a.silent(now), 30)                     # it used to be 0 for as long as 'transfers' was set
        a.last_tx = now - 1                                       # a chunk left a second ago: alive
        self.assertLess(a.silent(now), 2)
        a.transfers = 0
        self.assertGreater(a.silent(now), 30)                     # without a transfer only what arrives counts

    def test_a_deeply_nested_frame_is_dropped_not_raised(self):
        a, b = self.channels = pair()
        body = b'[' * 100000 + b']' * 100000
        a._send(struct.pack('>I', len(body) + 1) + b'J' + body)
        a.try_send(type='PING')
        time.sleep(0.2)
        self.assertEqual([f[1] for f in b.poll_frames()], [dict(type='PING')])


# ---- the fight ------------------------------------------------------------------------------------------------------------
class FakeHub:
    def __init__(self, members, frame=100, waiting=1):
        self.members = members
        self.control = dict(state=2, frame=frame, waiting=waiting)
        self.have = {m.slot: frame for m in members.values() if m.slot is not None}
        self.hold_at = None
        self.decided = None
        self.removed, self.events, self.released = [], [], 0
        self.sched_on = False

    def remove_member(self, ident):
        self.removed.append(ident)
        return self.members.pop(ident, None)

    def event(self, kind, **fields):
        self.events.append((kind, fields))

    def release(self):
        self.released += 1
        self.hold_at = None


def member(slot, confirmed=True):
    return SimpleNamespace(slot=slot, paused=False, confirmed=confirmed)


class Fight(kit_fight.FightMixin):
    """The host's fight half with just enough around it."""

    def __init__(self, hub):
        self.init_fight()
        self.role, self.phase, self.me = 'host', 'fight', 1
        self.session = hub
        self.match = dict(seats={1: 0, 2: 1, 3: 2}, spec=dict(type='versus'))
        self.members = {2: {}, 3: {}}
        self.loaded = {2, 3}
        self.lobby = SimpleNamespace(members={2: dict(name='Bea'), 3: dict(name='Cy')}, bump=lambda notice=None: None)
        self.summary, self.overlay, self.sent, self.said = {}, None, [], []
        self.epoch = 1

    def say(self, text):
        self.said.append(text)

    def send_to(self, ident, **message):
        self.sent.append((ident, message))
        return True

    def send(self, **message):
        self.sent.append((None, message))
        return True

    def broadcast(self):
        pass

    def note(self, key, **args):
        self.notices = getattr(self, 'notices', []) + [key]

    def hide_overlay(self):
        self.overlay = None

    def hub_member_left(self, ident):
        pass

    def drop_to_cpu(self, ident):
        self.summary.setdefault('cpu', []).append(ident)
        return True


class SilentPlayers(unittest.TestCase):
    def fight(self, **hub):
        return Fight(FakeHub({2: member(1), 3: member(2)}, **hub))

    def stall(self, fight, seconds):
        clock = [1000.0]
        with patch.object(kit_fight, 'now', lambda: clock[0]):
            fight.drop_silent_players()
            clock[0] += seconds
            fight.drop_silent_players()

    def test_the_player_whose_input_is_missing_leaves_and_becomes_a_cpu(self):
        fight = self.fight()
        fight.session.have[2] = 101                               # member 3 (slot 2) has sent frame 100; member 2 not
        self.stall(fight, kit_fight.STALL_DROP + 0.1)
        self.assertEqual(fight.session.removed, [2])
        self.assertEqual(fight.summary['cpu'], [2])
        self.assertNotIn(2, fight.loaded)                         # a Retry starts without it
        self.assertIn((2, dict(type='LEFT_FIGHT', why='not_responding')), fight.sent)
        self.assertEqual(fight.summary['stall_drops'][0]['member'], 2)

    def test_nobody_is_dropped_before_the_limit_or_while_the_game_moves(self):
        fight = self.fight()
        self.stall(fight, kit_fight.STALL_DROP - 1)
        self.assertEqual(fight.session.removed, [])
        fight = self.fight()
        clock = [1000.0]
        with patch.object(kit_fight, 'now', lambda: clock[0]):
            for frame in range(100, 140):                         # a slow game: it never stays at one frame
                fight.session.control['frame'] = frame
                fight.session.have = {1: frame, 2: frame}
                fight.drop_silent_players()
                clock[0] += 1.0
        self.assertEqual(fight.session.removed, [])

    def test_not_during_a_resync_hold_or_after_the_decision(self):
        for change in (dict(hold_at=120), dict(decided=dict(frame=90))):
            fight = self.fight()
            for key, value in change.items():
                setattr(fight.session, key, value)
            self.stall(fight, 60)
            self.assertEqual(fight.session.removed, [], change)
        fight = self.fight()
        fight.resyncs = {3: object()}
        self.stall(fight, 60)
        self.assertEqual(fight.session.removed, [])

    def test_a_player_still_loading_gets_the_longer_limit(self):
        fight = Fight(FakeHub({2: member(1, confirmed=False)}))
        self.stall(fight, kit_fight.STALL_DROP + 5)
        self.assertEqual(fight.session.removed, [])
        self.stall(fight, kit_fight.STALL_DROP_FIRST + 1)
        self.assertEqual(fight.session.removed, [2])

    def test_spectators_are_never_waited_for_and_never_dropped(self):
        fight = Fight(FakeHub({2: member(1), 4: member(None)}))
        self.stall(fight, 30)
        self.assertEqual(fight.session.removed, [2])
        self.assertIn(4, fight.session.members)


class LeavingAFight(unittest.TestCase):
    def test_leaving_during_ones_own_resync_releases_the_hold(self):
        fight = Fight(FakeHub({2: member(1), 3: member(2)}))
        fight.session.hold_at = 150
        fight.resyncs = {2: object()}
        fight.overlay = dict(key='fight.resync')
        fight.msg_LEFT_FIGHT(2, dict(why='left'))
        self.assertEqual(fight.session.released, 1)               # everybody was frozen until the upload ended
        self.assertEqual(fight.resyncs, {})
        self.assertIsNone(fight.overlay)
        self.assertEqual(fight.summary['cpu'], [2])
        self.assertNotIn(2, fight.loaded)

    def test_a_member_who_left_the_fight_does_not_block_the_retry_vote(self):
        fight = Fight(FakeHub({2: member(1), 3: member(2)}))
        fight.msg_LEFT_FIGHT(2, dict(why='left'))
        players = [k for k in fight.match['seats'] if k == fight.me or (k in fight.members and k in fight.loaded)]
        vote = kit_postmatch.Vote(1, players, 0.0)
        self.assertTrue(vote.cast(1, 'retry', 1.0))
        self.assertTrue(vote.cast(3, 'retry', 1.5))
        self.assertEqual(vote.decision, 'retry')                  # member 2 is in the room but not in the fight

    def test_a_failed_resync_makes_the_fighter_a_cpu(self):
        fight = Fight(FakeHub({2: member(1), 3: member(2)}))
        fight.drop_from_fight(3, 'resync_failed')
        self.assertEqual(fight.summary['cpu'], [3])
        self.assertIn((3, dict(type='LEFT_FIGHT', why='resync_failed')), fight.sent)

    def test_a_guests_own_failure_tells_the_host_and_waits_in_the_room(self):
        fight = Fight(None)
        fight.role = 'guest'
        fight.link = None
        fight.emulator = None
        fight.local = {}
        phases = []
        fight.set_phase = phases.append
        fight.stop_prefetch_receive = fight.stop_receive = lambda: None
        fight.end_fight('aborted', mine=True)
        self.assertEqual(fight.sent, [(None, dict(type='LEFT_FIGHT', why='aborted'))])
        self.assertEqual(phases, ['lobby'])
        self.assertIsNone(fight.match)
        self.assertEqual(fight.notices, ['notice.left_fight_error'])      # and the player is told why


class ServicePacketsAcrossAJoin(unittest.TestCase):
    @staticmethod
    def bulk(seq, frame):
        return dict(type='BULK', seq=seq, host_frame=frame, writes=[[kit_services.PACKET_LO + 16 * seq, '00' * 8]])

    def guest(self):
        fight = Fight(None)
        fight.role = 'guest'
        return fight

    def test_packets_the_loaded_state_holds_are_never_written_again(self):
        store = kit_services.GuestBulk()
        for seq, frame in ((1, 10), (2, 20), (3, 30)):
            self.assertTrue(store.add(self.bulk(seq, frame)))
        store.loaded(2)
        self.assertTrue(store.ready(2))
        self.assertFalse(store.ready(3))
        written, acks = [], []
        link = SimpleNamespace(write_ranges=written.append)
        store.tick(link, 29, lambda **m: acks.append(m))
        self.assertEqual(written, [])                             # its frame is not reached yet
        store.tick(link, 30, lambda **m: acks.append(m))
        self.assertEqual(len(written), 1)
        self.assertEqual(acks, [dict(type='BULK_ACK', seq=3)])
        self.assertTrue(store.ready(3))

    def test_a_member_in_the_lobby_ignores_packets_and_a_joining_one_keeps_them(self):
        fight = self.guest()
        fight.msg_BULK(1, self.bulk(4, 100))
        self.assertIsNone(fight.guest_bulk)
        fight.guest_bulk = kit_services.GuestBulk()               # what JOINFIGHT does
        fight.msg_BULK(1, self.bulk(4, 100))
        fight.msg_BULK(1, self.bulk(5, 140))
        self.assertEqual([row[0] for row in fight.guest_bulk.waiting], [4, 5])

    def test_the_resync_message_says_which_packets_the_state_holds(self):
        fight = self.guest()
        fight.guest_bulk = kit_services.GuestBulk()
        for seq in (4, 5, 6):
            fight.msg_BULK(1, self.bulk(seq, 100 + seq))
        made = []
        fight.guest_ctx = lambda: None
        with patch.object(kit_resync, 'GuestResync', lambda ctx, m: made.append(m) or 'resync'):
            fight.msg_RESYNC(1, dict(epoch=1, K=120, size=1000, reason='join', bulk=5))
        self.assertEqual(fight.resync, 'resync')
        self.assertEqual([row[0] for row in fight.guest_bulk.waiting], [6])
        self.assertTrue(fight.bulk_ready(5))
        self.assertFalse(fight.bulk_ready(6))

    def test_a_left_fight_takes_its_packets_with_it(self):
        fight = self.guest()
        fight.local = {}
        fight.stop_prefetch_receive = fight.stop_receive = lambda: None
        fight.guest_bulk = kit_services.GuestBulk()
        fight.msg_BULK(1, self.bulk(1, 50))
        fight.leave_match_state()
        self.assertIsNone(fight.guest_bulk)
        self.assertFalse(fight.bulk_ready(1))

    def test_packets_made_while_a_state_travels_follow_it(self):
        sent = []
        ctl = SimpleNamespace(link=SimpleNamespace(write_ranges=lambda writes: None), resyncs={3: object()},
                              session=SimpleNamespace(control=dict(frame=500), members={2: None, 3: None}),
                              send_to=lambda ident, **m: sent.append((ident, m['seq'])))
        broker = kit_services.Broker.__new__(kit_services.Broker)
        broker.ctl, broker.bulk_seq, broker.acks, broker.pending = ctl, 4, {}, None
        broker.stats = dict(bulk=0, bulk_bytes=0)
        broker.send_bulk([(kit_services.PACKET_LO, b'12345678')])      # seq 5: the state on its way holds it
        broker.send_bulk([(kit_services.PACKET_LO, b'abcdefgh')])      # seq 6: made after the state was saved
        self.assertEqual(sent, [(2, 5), (2, 6)])                  # the member being re-synchronized waits
        del ctl.resyncs[3]
        broker.resync_done(3, 5)
        self.assertEqual(sent, [(2, 5), (2, 6), (3, 6)])
        broker.send_bulk([(kit_services.PACKET_LO, b'ABCDEFGH')])
        self.assertEqual(sent[-2:], [(2, 7), (3, 7)])
        ctl.resyncs[2] = object()
        broker.send_bulk([(kit_services.PACKET_LO, b'ABCDEFGH')])
        broker.member_gone(2)                                     # it left: nothing is kept for it
        broker.resync_done(2, None)
        self.assertEqual(sent[-1], (3, 8))

    def test_the_host_reads_the_packet_count_with_the_schedule_count(self):
        sent = []
        hub = SimpleNamespace(delay=1, members={3: object()}, hold_at=None, sched_count=lambda: 7,
                              pause_member=lambda t: None, restart_member=lambda *a: None)
        ctx = SimpleNamespace(hub=hub, link=SimpleNamespace(w32=lambda a, v: None, save_state=lambda slot: 'x'),
                              sstates=None, send=lambda member, message: sent.append(message),
                              send_file=lambda member, path: None, alive=lambda: True, log=lambda text: None,
                              bulk_count=lambda: 4)
        work = kit_resync.HostResync(ctx, [3], 'join', 1, hold=False)
        with patch.object(kit_resync, 'Worker', lambda fn, *args: SimpleNamespace(done=True, error=None,
                                                                       value=('x', 'ab' * 32, 10, 55))):
            self.assertEqual(work.step(), 'save')
            self.assertEqual((work.sched_count, work.bulk_count), (7, 4))
            self.assertEqual(work.step(), 'send')
        work._send('x', 'ab' * 32, 10)
        self.assertEqual((sent[0]['sched'], sent[0]['bulk'], sent[0]['K']), (7, 4, 55))


class ServiceSeal(unittest.TestCase):
    def pine(self, frames):
        import kit_service
        pine = kit_service.RemotePine.__new__(kit_service.RemotePine)
        pine.dirty = True
        pine.call = lambda what, **args: dict(k=100)
        pine.frame = lambda: (frames.pop(0) if len(frames) > 1 else frames[0], 2)
        return kit_service, pine

    def test_a_game_that_keeps_moving_is_waited_for(self):
        kit_service, pine = self.pine([90 + i // 4 for i in range(48)])      # ~0.5 s to pass frame 100
        with patch.object(kit_service, 'SEAL_WAIT', 0.2):
            pine.seal()
        self.assertFalse(pine.dirty)

    def test_a_game_that_stands_still_is_given_up_after_the_wait(self):
        kit_service, pine = self.pine([90])
        with patch.object(kit_service, 'SEAL_WAIT', 0.2):
            started = time.time()
            with self.assertRaises(kit_service.LinkError):
                pine.seal()
        self.assertGreaterEqual(time.time() - started, 0.15)
        self.assertGreaterEqual(kit_service.SEAL_WAIT, 120)


class Lockstep(unittest.TestCase):
    def test_the_publish_window_fits_the_cores_input_ring(self):
        self.assertLess(kit_lockstep.WINDOW, nc.IN_SLOTS)
        self.assertGreaterEqual(kit_lockstep.WINDOW, nc.IN_SLOTS // 2)

    def test_a_spectator_far_behind_never_overwrites_inputs_it_has_not_read(self):
        written = {}

        class Game:
            def control(self):
                return dict(state=nc.RUNNING, frame=40, waiting=0, stall_total=0, stall_now=0, start_game_frame=0,
                            decided_frame=0, decided_state=0, decided_result=0)

            def outgoing(self, first, last):
                return {}

            def hashes(self, first, last):
                return {}

            def publish(self, slot, frames, aux=0):
                written.update(frames)

        class Net:
            def recv(self):
                return []

            def send(self, data):
                pass
        client = kit_lockstep.Client(Game(), Net(), member=2, slot=None, mask=1, delay=2, state_sha='0' * 64)
        client.inputs[0] = {f: (nc.NEUTRAL, 0) for f in range(2, 3000)}      # the host is 100 s ahead
        client.advance_have(0)
        client.tick()
        self.assertEqual(max(written), 40 + kit_lockstep.WINDOW - 1)
        ring = {f % nc.IN_SLOTS for f in written if f >= 40}
        self.assertEqual(len(ring), len([f for f in written if f >= 40]))   # no slot of the ring written twice

    def test_a_member_joining_a_long_fight_does_not_fill_the_sched_ring(self):
        written = []

        class Game:
            def control(self):
                return dict(state=nc.RUNNING, frame=500)

            def write_sched(self, seq, frame, writes):
                written.append(seq)
        hub = kit_lockstep.Hub(Game(), None, member=1, slot=0, mask=3, delay=2, state_sha='0' * 64, sched=True,
                               members=[(2, 1, 'Bea')])
        hub.members[2].sched_through = 70                         # the player is up to date
        hub.sched_log = [(n, 400, [(0x07B20000, 1, 0xFFFFFFFF)]) for n in range(70)]
        late = hub.add_member(9, None, 'Late')                    # joins now: nothing acknowledged yet
        with self.assertRaisesRegex(RuntimeError, 'SCHED ring is full'):
            hub.schedule([(0x07B20000, 1, 0xFFFFFFFF)])           # what ended the fight for everybody
        hub.pause_member(9)                                       # join_running pauses it until its state runs
        self.assertEqual(hub.schedule([(0x07B20000, 1, 0xFFFFFFFF)])[0], 70)
        hub.restart_member(9, 500, sched_count=71)
        self.assertEqual(late.sched_through, 71)
        self.assertEqual(hub.schedule([(0x07B20000, 2, 0xFFFFFFFF)])[0], 71)

    def test_a_watcher_who_takes_a_fighter_acks_from_its_join_frame(self):
        client = object.__new__(kit_lockstep.Client)
        client.slots, client.mask, client.inputs, client.have, client.written = [0], 1, {0: {}}, {0: 2}, {0: 2}
        client.delay, client.local_next, client.hub_need = 2, 2, 2
        client.events, client.log_file, client.clock = [], None, time.perf_counter
        client.member = 3
        client.epoch = 1
        client.guest = SimpleNamespace(configure=lambda **values: None)
        client.become_player(4, 300)
        self.assertEqual(client.hub_need, 300)


class Housekeeping(unittest.TestCase):
    def test_old_states_go_and_the_newest_and_the_young_stay(self):
        folder = Path(tempfile.mkdtemp(dir=_RUNTIME))
        (folder / 'wire').mkdir()
        now = time.time()
        for n in range(10):
            for name in (f'recv-{n:020d}.p2s', f'host-k{n:019d}.p2s', f'host-k{n:019d}.json', f'wire/w{n:063d}.wire',
                         f'wire/w{n:063d}.json'):
                path = folder / name
                path.write_bytes(b'x')
                os.utime(path, (now - 3600 - n, now - 3600 - n))
        young = folder / 'recv-young000000000000000.p2s'
        young.write_bytes(b'x')
        (folder / 'left.part').write_bytes(b'x')
        os.utime(folder / 'left.part', (now - 2 * 86400, now - 2 * 86400))
        removed = kit_match.prune_states(folder, spare=['recv-0000000000000000000' + '9'], now=now)
        left = sorted(p.name for p in folder.glob('recv-*.p2s'))
        self.assertIn(young.name, left)
        self.assertIn('recv-00000000000000000009.p2s', left)                 # spared: the running match
        self.assertEqual(len(left), 7)                                       # 6 newest + the spared one... and young
        self.assertEqual(len(list(folder.glob('host-*.p2s'))), len(list(folder.glob('host-*.json'))))
        self.assertEqual(len(list((folder / 'wire').glob('*.wire'))), kit_match.STATES_KEEP)
        self.assertNotIn('left.part', [p.name for p in folder.iterdir()])
        self.assertTrue(removed)

    def test_version_gate_accepts_the_releases_and_later_schemes(self):
        for version in ('0.1.0-beta.7', '0.1.0-beta.14.6', '0.1.0-beta.15.0', '0.2.0', '1.0.0', '1.0.0-rc.1'):
            self.assertEqual(kit_install.build_status(version), 'candidate', version)
        for version in ('0.1.0-beta.6', '0.1.0-beta.3', '0.0.9', '0.1.0', 'garbage', None):
            self.assertEqual(kit_install.build_status(version), 'refused', version)
        self.assertEqual(kit_install.build_status('0.1.0-beta.41'), 'known')

    def test_a_refusal_mark_does_not_survive_an_update(self):
        root = Path(tempfile.mkdtemp(dir=_RUNTIME))
        (root / 'game').mkdir()
        (root / 'game' / 'player-install.json').write_text(json.dumps(dict(version='0.1.0-beta.14.6')))
        before = kit_install.refusal_stamp(root)
        (root / 'game' / 'player-install.json').write_text(json.dumps(dict(version='0.1.0-beta.14.7')))
        self.assertNotEqual(kit_install.refusal_stamp(root), before)

    def test_a_remembered_pid_is_only_ended_while_it_is_that_process(self):
        me = os.getpid()
        if kit_win.WINDOWS:
            self.assertFalse(kit_win.kill_tree(me, exe=Path(_RUNTIME) / 'pcsx2-qt.exe'))
            self.assertFalse(kit_win.kill_tree(me, created=1))
            self.assertEqual(kit_win.process_created(me), kit_win.process_created(me))
            self.assertTrue(kit_win.same_path(sys.executable.upper(), sys.executable))
        self.assertFalse(kit_win.same_path('', sys.executable))

    def test_a_pcsx2_just_closed_gets_a_moment_to_free_the_pine_port(self):
        em = kit_emu.Emulator(root=_RUNTIME, pine_slot=29240, run_dir=_RUNTIME)
        em.stopped = 4242                                 # stop() ended it; Windows is still taking it down
        answers = [4242, 4242, 4242, None]
        with patch.object(kit_win, 'listener_pid', lambda port: answers.pop(0) if len(answers) > 1 else answers[0]), \
                patch.object(kit_win, 'pid_alive', lambda pid: True):
            started = time.time()
            self.assertIsNone(em.port_taken())
            self.assertLess(time.time() - started, 2.0)

    def test_a_port_another_program_keeps_is_reported_at_once(self):
        em = kit_emu.Emulator(root=_RUNTIME, pine_slot=29240, run_dir=_RUNTIME)
        with patch.object(kit_win, 'listener_pid', lambda port: 777), \
                patch.object(kit_win, 'pid_alive', lambda pid: True):
            started = time.time()
            self.assertEqual(em.port_taken(), 777)
            self.assertLess(time.time() - started, 1.0)
            with self.assertRaises(KitError) as caught:
                em.launch_idle('game.iso')
            self.assertEqual(caught.exception.code, 'TTM-NET-22')

    def test_a_closed_pcsx2_that_never_frees_the_port_is_reported_after_the_wait(self):
        em = kit_emu.Emulator(root=_RUNTIME, pine_slot=29240, run_dir=_RUNTIME)
        em.stopped = 4242
        with patch.object(kit_win, 'listener_pid', lambda port: 4242), \
                patch.object(kit_win, 'pid_alive', lambda pid: True), patch.object(kit_emu, 'PORT_WAIT', 0.3):
            started = time.time()
            self.assertEqual(em.port_taken(), 4242)
            self.assertGreaterEqual(time.time() - started, 0.25)

    def test_the_resync_state_is_named_after_the_running_disc(self):
        import kit_adapter
        self.assertEqual(kit_resync.STATE_NAME, kit_emu.STATE_NAME)
        self.assertEqual(kit_resync.STATE_NAME.format(slot=240), kit_adapter.state_name(240))
        with patch.object(kit_paths, 'ADAPTER', 'bt4-b14-rev2-eng'):
            self.assertTrue(kit_adapter.state_name(240).startswith('SLUS-21978 ('))

    def test_a_stale_session_file_is_not_attached_to(self):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
        listener.close()                                          # nothing listens there any more
        self.assertFalse(ttm_online.session_listens(dict(port=port, pid=os.getpid())))
        self.assertFalse(ttm_online.session_listens(dict(port='x')))
        server = kit_ipc.Server('t' * 32)
        try:
            self.assertTrue(ttm_online.session_listens(dict(port=server.port)))
        finally:
            server.close()

    def test_the_ipc_server_is_safe_to_log_through_from_job_threads(self):
        server = kit_ipc.Server('t' * 32)
        client = kit_ipc.Client(server.port, 't' * 32)
        try:
            end = time.time() + 2
            while not server.attached() and time.time() < end:
                server.poll()
            stop = threading.Event()

            def log():
                while not stop.is_set():
                    server.send('log', text='x' * 200)
            workers = [threading.Thread(target=log) for _ in range(4)]
            for w in workers:
                w.start()
            got = 0
            end = time.time() + 1.0
            while time.time() < end:
                server.poll()
                for event in client.poll(0.01):
                    self.assertEqual(event, dict(ev='log', text='x' * 200))     # never a torn or doubled line
                    got += 1
            stop.set()
            for w in workers:
                w.join()
            self.assertGreater(got, 50)
        finally:
            client.close()
            server.close()


# ---- coming back after a lost connection ----------------------------------------------------------------------------------
class ComingBack(unittest.TestCase):
    def host(self):
        import kit_controller
        import kit_lobby
        host = object.__new__(kit_controller.Controller)
        host.role, host.phase, host.me = 'host', 'lobby', 1
        host.lobby = kit_lobby.Lobby(host_name='Host')
        host.members, host.recent_left, host.said = {}, {}, []
        host.say = host.said.append
        host.cancel_transfers = lambda ident=None: None
        host.member_left_match = lambda ident: None
        host.broadcast = lambda: None
        host.udp = SimpleNamespace(forget=lambda ident: None)
        return host

    def join(self, host, name, token):
        ident = host.lobby.join(name)
        host.members[ident] = dict(channel=SimpleNamespace(close_soon=lambda: None), token=token)
        return ident

    def test_the_ghost_leaves_and_name_and_fighter_wait_for_the_returning_member(self):
        host = self.host()
        old = self.join(host, 'Bea', 'a' * 32)
        self.assertEqual(host.lobby.claim(old, 1, 0), [])
        back = host.returning_member('a' * 32)                    # the old connection has not timed out yet
        self.assertEqual((back['name'], back['seat']), ('Bea', (1, 0)))
        self.assertNotIn(old, host.members)
        self.assertNotIn(old, host.lobby.members)
        self.assertIsNone(host.lobby.owner_of(1, 0))
        new = host.lobby.join(back['name'])
        self.assertEqual(host.lobby.members[new]['name'], 'Bea')  # not "Bea (2)"
        self.assertEqual(host.lobby.claim(new, *back['seat']), [])
        self.assertEqual(host.lobby.slot_of(new), (1, 0))

    def test_a_member_that_already_timed_out_is_still_remembered_for_a_while(self):
        import kit_controller
        host = self.host()
        old = self.join(host, 'Cy', 'c' * 32)
        host.lobby.claim(old, 1, 0)
        clock = [5000.0]
        with patch.object(kit_controller, 'now', lambda: clock[0]):
            host.member_gone(old, KitError('TTM-NET-13', why='its connection was lost'))
            clock[0] += 60
            self.assertEqual(host.returning_member('c' * 32)['seat'], (1, 0))
            self.assertIsNone(host.returning_member('c' * 32))    # a token is good once
            other = self.join(host, 'Di', 'd' * 32)
            host.member_gone(other)
            clock[0] += kit_controller.REJOIN_KEEP + 1
            self.assertIsNone(host.returning_member('d' * 32))    # too long ago

    def test_an_unknown_or_malformed_token_is_a_plain_join(self):
        host = self.host()
        self.join(host, 'Bea', 'a' * 32)
        for token in (None, '', 'b' * 32, 'a' * 31, 12345, ['a' * 32]):
            self.assertIsNone(host.returning_member(token))
        self.assertEqual(len(host.members), 1)

    def test_a_guest_presents_its_token_only_to_the_room_it_came_from(self):
        import kit_controller
        guest = object.__new__(kit_controller.Controller)
        guest.role, guest.cfg = 'guest', dict(host_address='10.0.0.5:47400')
        guest.rejoin = dict(address='10.0.0.5:47400', token='t' * 32)
        self.assertEqual(guest.rejoin_token(), 't' * 32)
        guest.cfg['host_address'] = '10.0.0.9'
        self.assertIsNone(guest.rejoin_token())

    def test_the_last_failed_rejoin_says_the_connection_was_lost(self):
        import kit_controller
        ctl = kit_controller.Controller.__new__(kit_controller.Controller)
        ctl.role, ctl.phase, ctl.cfg = 'guest', 'check', dict(host_address='10.0.0.2:47860', port=47860)
        failed, said, notes = [], [], []
        ctl.fail = lambda error, phase=None: failed.append((error.code, phase))
        ctl.say, ctl.set_phase, ctl.note = said.append, lambda phase: None, lambda key, **a: notes.append(key)
        ctl.auto_rejoin = dict(address='10.0.0.2:47860', tries=2, at=0.0, since=kit_controller.now() - 9)
        ctl.connect_failed(OSError('refused'))
        self.assertEqual((failed, notes), ([], ['notice.rejoining']))      # tries are left: it goes on
        self.assertIsNotNone(ctl.auto_rejoin)
        ctl.role, ctl.phase = 'guest', 'check'
        ctl.auto_rejoin['tries'] = kit_controller.REJOIN_TRIES
        ctl.connect_failed(OSError('refused'))
        self.assertEqual(failed, [('TTM-NET-19', 'start')])
        self.assertIsNone(ctl.auto_rejoin)
        ctl.role, ctl.phase = 'guest', 'check'
        ctl.connect_failed(OSError('refused'))                    # a join typed by the player: the plain error
        self.assertEqual(failed[-1], ('TTM-NET-10', 'start'))

    def test_two_handshakes_from_one_address_keep_the_pongs_until_both_ended(self):
        pending = kit_net._Counted()
        pending.add('203.0.113.7')
        pending.add('203.0.113.7')
        pending.discard('203.0.113.7')
        self.assertIn('203.0.113.7', pending)                     # the second PC behind that router is still joining
        pending.discard('203.0.113.7')
        self.assertNotIn('203.0.113.7', pending)
        pending.discard('203.0.113.7')
        self.assertEqual(len(pending), 0)


# ---- the rules dialog -----------------------------------------------------------------------------------------------------
sys.path.insert(0, str(ROOT / 'release_tools' / 'online-menu-tests'))
try:
    import test_menu_stability as menu
    MENU_UI = menu.ui_available()
except Exception:  # noqa: BLE001 - no Tk here: the window tests are skipped
    menu, MENU_UI = None, False


@unittest.skipUnless(MENU_UI, 'no Tk display')
class LobbyNotices(unittest.TestCase):
    def lobby(self):
        lobby = kit_lobby.Lobby.__new__(kit_lobby.Lobby)
        lobby.rev, lobby.notice = 7, None
        return lobby

    def test_a_refusal_survives_the_next_silent_change(self):
        lobby = self.lobby()
        refusal = dict(code='TTM-NET-29', key='notice.claim_refused', args=dict(what='Bea already plays it'))
        lobby.bump(refusal)
        lobby.bump()                                              # somebody's Ready, milliseconds later
        self.assertEqual((lobby.rev, lobby.notice), (9, refusal))
        claimed = dict(code=None, key='notice.claimed', args=dict(name='Cy', team=1, index=2))
        lobby.bump(claimed)                                       # a change with its own notice replaces it
        self.assertEqual(lobby.notice, claimed)
        lobby.bump()                                              # and an ordinary notice goes as before
        self.assertIsNone(lobby.notice)

    def test_a_refusal_does_not_stay_for_ever(self):
        lobby = self.lobby()
        lobby.bump(dict(code='TTM-NET-29', key='notice.claim_refused', args=dict(what='x')))
        lobby.noticed -= kit_lobby.NOTICE_KEEP + 0.1
        lobby.bump()
        self.assertIsNone(lobby.notice)


class SpinBoxCommits(unittest.TestCase):
    """What made test_spin_box_sends_one_change_per_pause fail one run in three on a visible desktop: the window manager
    moves the focus while the test waits, and every focus change used to push the last value out by another 350 ms."""

    def setUp(self):
        self.case = menu.MenuStability('test_spin_box_sends_one_change_per_pause')
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.addCleanup(self.case.tearDown)

    def rules_spin(self):
        app = self.case.app
        app.on_state(self.case.state())
        app.open_rules()
        spin = next(w for w in app.setting_widgets.values() if isinstance(w, menu.ui.ttk.Spinbox))
        app.client.sent.clear()
        return app, spin

    def test_focus_changes_while_waiting_do_not_delay_the_last_value(self):
        app, spin = self.rules_spin()
        for _ in range(10):
            spin.event_generate('<<Increment>>')
        for delay in (250, 500):
            app.root.after(delay, lambda: spin.event_generate('<FocusOut>'))
        self.case.settle(700)
        sent = [m for m in app.client.sent if m['cmd'] == 'rules']
        self.assertLessEqual(len(sent), 2)
        self.assertEqual(list(sent[-1]['gameplay'].values())[0], spin.get())

    def test_a_value_still_waiting_is_sent_when_the_dialog_closes(self):
        app, spin = self.rules_spin()
        for _ in range(3):
            spin.event_generate('<<Increment>>')
        final = spin.get()
        app.close_dialog()                                        # START does the same before it sends 'start'
        sent = [m for m in app.client.sent if m['cmd'] == 'rules']
        self.assertEqual(list(sent[-1]['gameplay'].values())[0], final)
        self.case.settle(500)
        self.assertEqual(len([m for m in app.client.sent if m['cmd'] == 'rules']), len(sent))   # and only once


if __name__ == '__main__':
    unittest.main()
