"""Prepare a selected battle with up to five fighters per side through PCSX2's local PINE interface.

The automatic launcher uses StreamingSession: guest frame-boundary commits
prepare the match behind its native loading screen, without intermediate
savestate reloads. Session retains the older manual checkpoint workflow for
research. Both paths retain a separate playable checkpoint for rematches.
"""
from native_map import A, CRC, SERIAL
import argparse
import hashlib
import json
import os
import shutil
import runtime_profile
import game_profile
import struct
import time
import uuid
import zipfile
from pathlib import Path

from pine import PineClient, require_runtime
from camera_snapshot import read_ram, publish, published, retract
from state128 import read_entry
import fresh_memory
import selected_resource_queue as resources
import selected_team_prepare as creation
import fresh_render_capacity as render
import packet_pool_grow as packets
import fresh_team_ai as ai
import fresh_team_combat as combat
import fresh_team_safety as safety
import multifighter_audio_effects as audio_effects
import extra_positional_audio
import lockon_switch
import guest_healthbars
import extra_transform_guard
import team_start_gate
import cinematic_camera_state
import lockon_queue
import cinematic_admission
import special_camera_arbitration
import special_concurrency
import ordinary_form_admission
import finished_camera_cleanup
import beam_clash
import dash_clash
import dash_contact_guard
import battle_modes
import battle_mode_policy
import ffa_targeting
import coop_controller
import hud_subject
import spectator_switch
import spectator_takeover
import spectator_feedback
import corpse_safety
import display_settings
import teammate_revive
import outnumbered
import extra_voice
import npc_transform_policy
import giant_options
import battle_camera_zoom
import viewport_hud
import multi_contact
import cinematic_policy
import ordinary_transform_guard
import leader_transform_safety
import effect_cleanup_owner
import effect_texture_guard
import team_intro
import team_intro_camera
import result_presentation
import guest_killfeed
import terrain_crossing_guard
import extra_specials
import extra_special_pools
import cpu_retaliation
import spawn_placement
import guest_loading_screen
import mod_settings
import special_pause
import extra_charge_aura
import special_visibility
import extra_extended_auras
import extra_generic_effects
import extra_ground_effects
import extra_reload_worker
import extra_throws
import team_participation
import camera_continuity
import fusion_partner_lifecycle
import stage_transition
import model_slot_guards
import texture_queue_guard
import throw_camera
import stage_debris_guard
from selected_team_capture import capture
from battle_mode_policy import ACTOR_COUNTS

ROOT = Path(__file__).resolve().parents[1]
STATES = runtime_profile.STATES
PREFIX = f'{SERIAL} ({game_profile.pcsx2_crc()}).'
ACK_ADDRESS = 0x073BFF00  # Reserved immutable stage token, outside game heaps.
# An actor's native idle-update count. The idle handler (1EE968; PAL 1EED40) plays the idle taunt, action 67, once
# it passes 90 (PAL 75): about 3 s of held idle. Seen live in the preparation hold (P-1).
IDLE_COUNT = 0x3D8


class ActiveRuntimeBudget:
    """Charge only intervals observed running at both ends of a PINE poll.

    PCSX2 pauses while its controller/settings dialogs are open, too. A valid
    paused connection has no preparation deadline; connection/game-identity
    failures still propagate from the individually bounded PINE operations.
    """
    def __init__(self, seconds):
        self.seconds = seconds
        self.elapsed = 0.0
        self.previous_time = None
        self.previous_status = None

    def observe(self, status):
        if status not in ('running', 'paused'):
            raise ValueError(f'Unexpected emulator status during preparation: {status}')
        now = time.monotonic()
        if self.previous_status == status == 'running':
            self.elapsed += now-self.previous_time
        self.previous_time, self.previous_status = now, status
        return status == 'running'

    @property
    def expired(self):
        return self.elapsed >= self.seconds


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class PreparationBusyError(ValueError):
    """The emulator's preparation lease is currently owned by another session."""


def acquire_lock(path):
    """One preparation per emulator; OS releases this lock after a crash."""
    try: stream = path.open('x+b')
    except FileExistsError: stream = path.open('r+b')
    try:
        if path.stat().st_size == 0: stream.write(b'0'); stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return stream
    except OSError:
        stream.close()
        raise PreparationBusyError('Another team preparation is already running') from None


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2)+'\n')
    return path


_OWNER = None


def claim_owner():
    """This process as the owner of a slot claim: its PID and start time, so a later process
    that reuses the PID is not mistaken for it."""
    global _OWNER
    if _OWNER is None:
        try:
            import psutil
            started = psutil.Process().create_time()
        except Exception:  # noqa: BLE001 - psutil missing or refused: the PID alone
            started = None
        _OWNER = dict(pid=os.getpid(), started=started)
    return dict(_OWNER)


def owner_alive(owner):
    """Is the process that wrote a slot claim still running? A claim with no owner (written
    before beta.33) or an unreadable one has none that is."""
    if not isinstance(owner, dict) or type(owner.get('pid')) is not int:
        return False
    if owner['pid'] == os.getpid():
        return owner.get('started') == claim_owner()['started']
    if owner.get('started') is None:
        return False
    try:
        import psutil
        return abs(psutil.Process(owner['pid']).create_time()-owner['started']) < .01
    except Exception:  # noqa: BLE001 - gone, reused by another user's process, or no psutil
        return False


def write_claim(path, value):
    """Replace a slot claim atomically: a crash leaves the old claim or the new one, never half."""
    partial = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.partial')
    try:
        partial.write_text(json.dumps(value, indent=2)+'\n')
        os.replace(partial, path)
    except BaseException:
        partial.unlink(missing_ok=True); raise
    return path


def merge_manifests(*items):
    blocks = []
    for item in items:
        if item.get('serial', SERIAL) != SERIAL or item.get('crc', CRC) != CRC:
            raise ValueError('Wrong game manifest')
        blocks.extend(dict(b) for b in item['blocks'])
    intervals = []
    for b in blocks:
        p = int(b['address'], 0) if isinstance(b['address'], str) else b['address']
        old, new = bytes.fromhex(b['expected_hex']), bytes.fromhex(b['data_hex'])
        if not old or len(old) != len(new) or not 0 <= p <= 0x8000000-len(new):
            raise ValueError('Invalid patch block range or length')
        b['address'] = p; intervals.append((p, p+len(new)))
    intervals.sort()
    if any(start < end for (_, end), (start, _) in zip(intervals, intervals[1:])):
        raise ValueError('Overlapping patch blocks')
    return dict(serial=SERIAL, crc=CRC, blocks=blocks)


def merge_support(*items):
    result = dict(capacity=min(item['capacity'] for item in items), features={})
    for item in items:
        for name, entries in item['features'].items():
            result['features'].setdefault(name, []).extend(entries)
    return result


def compose_manifests(ram, builders):
    """Build dependent patches against virtual RAM, then guard one atomic load.

    Later stages may intentionally replace an earlier hook/data word. Every
    intermediate guard is checked, but final guards refer to the real source.
    """
    return _compose(ram, builders)[0]


def _compose(ram, builders):
    """compose_manifests, also returning the composed virtual RAM."""
    current = bytearray(ram)
    intervals = []
    # A source whose installed build is already known lends it to this
    # composition's virtual RAM (battle_mode_policy.assumed_capacity).
    with battle_mode_policy.assumed_capacity(current, battle_mode_policy.known_capacity(ram)):
        for builder in builders:
            manifest = merge_manifests(builder(current))
            for b in manifest['blocks']:
                address = b['address']; old = bytes.fromhex(b['expected_hex'])
                if current[address:address+len(old)] != old:
                    raise ValueError(f'Virtual stage guard mismatch at {address:08X}')
            spans = []
            for b in manifest['blocks']:
                address = b['address']; data = bytes.fromhex(b['data_hex'])
                current[address:address+len(data)] = data
                intervals.append((address, address+len(data))); spans.append((address, len(data)))
            battle_mode_policy.assumed_writes(current, spans)
    ranges = []
    for lo, hi in sorted(intervals):
        if ranges and lo <= ranges[-1][1]: ranges[-1] = (ranges[-1][0], max(hi, ranges[-1][1]))
        else: ranges.append((lo, hi))
    return merge_manifests(dict(blocks=[dict(address=lo,
        expected_hex=ram[lo:hi].hex(), data_hex=current[lo:hi].hex()) for lo,hi in ranges])), current


def actor_config(ram, mode, selection=None, battle_mode='teams', humans=1, assignment=None):
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager, n = u(A(0x2FEB14)), u(creation.HEADER+52)
    if n not in ACTOR_COUNTS or u(creation.HEADER) != 20 or u(creation.HEADER+8) != n-2:
        raise ValueError('Hidden selected actor creation did not complete')
    leaders = [bool(u(fresh_memory.CONTROL+96+4*i)) for i in range(2)]
    if mode != 'Original':
        leaders = {'Player': [False, True], 'Cpu': [True, True], 'TwoPlayer': [False, False]}[mode]
    mask = (1 << n)-1 if selection is None else selection['participation_mask']
    four_seats=battle_mode_policy.human_seats(battle_mode,humans,mask,assignment) if humans>=3 or assignment is not None else None
    targets = team_participation.target_plan(n, mask)
    rows = []
    for i in range(n):
        actor = u(manager+4)+i*0x1600 if i < 2 else u(creation.DESCS[i-2]+28)
        mid = u(actor+12)
        if mid >= 12: raise ValueError('Unregistered created model')
        model = u(A(0x31C640)+4*mid)
        cpu=(i not in battle_mode_policy.COOP_HUMANS) if battle_mode in ('coop','training_coop') else (leaders[i] if i < 2 else True)
        if four_seats is not None:cpu=i not in four_seats
        rows.append(dict(physical_id=i, actor=actor, model_id=mid, model=model,
                         dataset=u(model+2356), team=i&1, cpu=cpu if mask & (1 << i) else False))
    return ai.normalize(dict(actors=rows, targets=targets, preserve_count=2,
                             actor_manager=manager, ai_manager=u(A(0x2FEB10)), creation_header=creation.HEADER))


def final_team_manifest(ram, activation, source, play_intro=False, pause_others=True, pause_mode=None, present_mask=None,
                        settings=None, battle_mode='teams', humans=1, assignment=None, mission=None):
    """Compose all playability guards before exposing the first ready frame."""
    training=battle_mode in ('training','training_coop')
    if training:battle_mode='coop' if battle_mode=='training_coop' else 'teams'
    preferences=mod_settings.validate_settings(settings or dict(mod_settings.DEFAULTS))
    # The queue and battle_modes read the button word installed here (R3/L3).
    button=mod_settings.lockon_mask(preferences)
    # Co-op gives player2 an extra (physical2, CPU flag0). Name it so the
    # extra special dispatchers admit a human-driven body; every other mode
    # keeps the CPU-only rule, and every other extra keeps it in co-op too.
    # The seating itself lives in battle_mode_policy.COOP_HUMANS, which the
    # CPU-flag assignment and the pad routing read as well.
    seats=battle_mode_policy.human_seats(battle_mode,humans,present_mask,assignment)
    human_extras=sum(1<<i for i in seats if i>=2)
    builders = [lambda r: activation,
        lambda r: audio_effects.build_memory(r, source=source),
        lambda r: lockon_switch.build_memory(r, source=source, button=button),
        lambda r: lockon_queue.build_memory(r, source=source, hold_updates=mod_settings.lockon_updates(preferences)),
        lambda r: guest_healthbars.build_memory(r, source=source),
        lambda r: extra_transform_guard.build_memory(r, source=source),
        lambda r: cinematic_camera_state.build_memory(r, source=source),
        lambda r: cinematic_admission.build_memory(r, source=source),
        lambda r: ordinary_transform_guard.build_memory(r, source=source),
        lambda r: leader_transform_safety.build_memory(r, source=source),
        lambda r: effect_cleanup_owner.build_memory(r, source=source),
        lambda r: effect_texture_guard.build_memory(r, source=source),
        lambda r: result_presentation.build_memory(r, source=source),
        lambda r: guest_killfeed.build_memory(r, source=source),
        lambda r: terrain_crossing_guard.build_memory(r, source=source),
        lambda r: extra_specials.build_memory(r, source=source, human_mask=human_extras),
        lambda r: cpu_retaliation.build_memory(r, source=source),
        lambda r: team_start_gate.build_memory(r, source=source)]
    if play_intro:
        builders.append(lambda r: team_intro.build_memory(r, source=source))
        builders.append(lambda r: team_intro_camera.build_memory(r, source=source))
    builders.append(lambda r: spawn_placement.build_memory(r, source=source, present_mask=present_mask))
    builders.append(lambda r: extra_special_pools.build_memory(r, source=source))
    builders.append(lambda r: extra_charge_aura.build_memory(r, source=source))
    builders.append(lambda r: extra_extended_auras.build_memory(r, source=source))
    builders.append(lambda r: extra_generic_effects.build_memory(r, source=source))
    builders.append(lambda r: extra_ground_effects.build_memory(r, source=source))
    builders.append(lambda r: special_pause.build_memory(r, source=source,
        **({'pause_others':pause_others} if pause_mode is None else {'mode':pause_mode})))
    builders.append(lambda r: special_visibility.build_memory(r, source=source))
    builders.append(lambda r: extra_throws.build_memory(r, source=source))
    builders.append(lambda r: camera_continuity.build_memory(r, source=source))
    # Scripted pair cameras (grabs, clashes, hits) anchor on the actual pair
    # instead of the two leaders.
    builders.append(lambda r: throw_camera.build_memory(r, source=source))
    builders.append(lambda r: extra_positional_audio.build_memory(r, source=source))
    builders.append(lambda r: extra_reload_worker.install_memory(r, source=source, enabled=True, forms=True))
    # Chained onto the actor-update hook before team_participation, which stays
    # the head of that chain; every earlier program keeps running behind it. A
    # person with no fighter - an all-CPU exhibition, or any match after their
    # own fighter falls - moves the camera with the same lock-on gesture they
    # would otherwise switch targets with.
    builders.append(lambda r: spectator_switch.build_memory(r, source=source))
    builders.append(lambda r: team_participation.build_memory(r, present_mask=present_mask, source=source))
    builders.append(lambda r: fusion_partner_lifecycle.build_memory(r, source=source, allow_human_partner=(battle_mode=='coop'),human_mask=human_extras if humans>=3 or assignment is not None else 0))
    builders.append(lambda r: special_camera_arbitration.build_memory(r, source=source))
    builders.append(lambda r: special_concurrency.build_memory(r, source=source))
    builders.append(lambda r: ordinary_form_admission.build_memory(r, source=source))
    builders.append(lambda r: finished_camera_cleanup.build_memory(r, source=source))
    builders.append(lambda r: beam_clash.build_memory(r, source=source))
    builders.append(lambda r: dash_clash.build_memory(r, source=source))
    builders.append(lambda r: battle_modes.build_memory(r, mode=battle_mode, humans=humans,
        fusion_controls=preferences[mod_settings.COOP_FUSION_KEY], source=source,
        show_fusion_owner=preferences['show_fusion_control_owner'],
        show_fusion_countdown=preferences['show_fusion_control_countdown']))
    if battle_mode!='ffa':
        # Free-for-all installs this policy with its own battle mode. Teams and
        # co-op NPCs get the same decisions here: damage memory, distance and
        # opportunity scoring, commitments and anti-dogpile, restricted to
        # actual enemies. Human targets stay manual in every mode.
        builders.append(lambda r: ffa_targeting.build_memory(r, source=source, battle_mode=battle_mode))
    builders.append(lambda r: coop_controller.build_memory(r, source=source))
    builders.append(lambda r: multi_contact.build_memory(r, source=source))
    builders.append(lambda r: cinematic_policy.build_memory(r, source=source,
        ultimate=preferences[mod_settings.ULTIMATE_KEY], transformation=preferences[mod_settings.TRANSFORMATION_KEY],
        transformation_view=preferences[mod_settings.TRANSFORM_VIEW_KEY]))
    # The native HUD resolver returns the first actor of the requested side, so
    # the top-right panel is always "enemy slot 1" once a side holds three
    # simultaneous fighters. Point it at the lock-on target instead, or at the
    # second human while the screen is split.
    # Player 2 sits on physical 2 in co-op and on leader 1 in every other
    # split mode (two-player teams and free-for-all).
    hud_partner=battle_mode_policy.COOP_HUMANS[1] if battle_mode=='coop' else 1
    builders.append(lambda r: hud_subject.build_memory(r, source=source, partner=hud_partner, enhanced=True))
    builders.append(lambda r: stage_transition.build_memory(r, source=source))
    import cinematic_position
    builders.append(lambda r: cinematic_position.build_memory(r,settings=preferences,source=source))
    import cinematic_position_camera
    builders.append(lambda r: cinematic_position_camera.build_memory(r,settings=preferences,source=source))
    # Walk and run on the ground (beta.37): the clip decoder and actions 13/14; off adds nothing.
    import ground_locomotion
    builders.append(lambda r: ground_locomotion.build_memory(r, settings=preferences, source=source))
    # Ten fighters leave two of the twelve model slots for summoned and
    # cosmetic models; when they run out, the move goes without its model.
    builders.append(lambda r: model_slot_guards.build_memory(r, source=source))
    # More fighters queue more texture uploads per frame; a full queue now
    # drops one upload for a frame instead of writing past its table.
    builders.append(lambda r: texture_queue_guard.build_memory(r, source=source))
    # A null stage debris pool is never walked (the first live 5v5 froze there).
    builders.append(lambda r: stage_debris_guard.build_memory(r, source=source))
    builders.append(lambda r: spectator_takeover.build_memory(r, battle_mode=battle_mode, source=source, settings=preferences))
    builders.append(lambda r: extra_voice.build_memory(r, source=source, settings=preferences))
    if play_intro:
        import extra_intros
        builders.append(lambda r: extra_intros.build_memory(r,source=source,settings=preferences,present_mask=present_mask))
    builders.append(lambda r: npc_transform_policy.build_memory(r, settings=preferences, source=source))
    builders.append(lambda r: giant_options.build_memory(r, settings=preferences, source=source))
    builders.append(lambda r: battle_camera_zoom.build_memory(r, settings=preferences, source=source))
    builders.append(lambda r: viewport_hud.build_memory(r, source=source, settings=preferences))
    builders.append(lambda r: spectator_feedback.build_memory(r, source=source, settings=preferences))
    builders.append(lambda r: corpse_safety.build_memory(r, settings=preferences, source=source))
    builders.append(lambda r: dash_contact_guard.build_memory(r, source=source))
    builders.append(lambda r: display_settings.build_memory(r, settings=preferences, source=source))
    builders.append(lambda r: teammate_revive.build_memory(r, settings=preferences, source=source))
    # Outnumbered help chains the kill-feed damage slot and the per-update call; preset Off adds nothing.
    builders.append(lambda r: outnumbered.build_memory(r, settings=preferences, source=source))
    import body_swap_worker
    builders.append(lambda r: body_swap_worker.prepare_memory(r, settings=preferences, source=source))
    if training:
        import modded_training
        builders.append(lambda r: modded_training.build_memory(r, settings=preferences, source=source))
    import fusion_duration_worker
    builders.append(lambda r: fusion_duration_worker.prepare_memory(r, settings=preferences, source=source))
    # Beam struggle options: after kill feed, retaliation, beam/dash clash, viewport HUD and revival, whose
    # programs it extends. All-legacy settings add nothing.
    import beam_struggle
    builders.append(lambda r: beam_struggle.build_memory(r, settings=preferences, source=source))
    import buu_ultimate_fanout
    builders.append(lambda r: buu_ultimate_fanout.build_memory(r, enabled=False,krillin_enabled=False, source=source))
    import inactive_actor_guard
    builders.append(lambda r: inactive_actor_guard.build_memory(r, source=source))
    if humans>=3 or assignment is not None:
        import four_player_mode
        builders.append(lambda r: four_player_mode.build_memory(r,mode=battle_mode,humans=humans,source=source,settings=preferences,assignment=assignment))
    import rush_cinematics
    builders.append(lambda r: rush_cinematics.build_memory(r, enabled=preferences['rush_cinematics']))
    import lockoff_target
    builders.append(lambda r: lockoff_target.build_memory(r,settings=preferences,source=source))
    # Hooks lock-off's INPUT/APPLY entries; all-legacy settings add nothing.
    import lockon_select
    builders.append(lambda r: lockon_select.build_memory(r,settings=preferences,source=source))
    if mission is not None:
        import story_runtime
        if training or battle_mode != 'teams':
            raise ValueError('Custom missions use Modded Team Battle, not training or free-for-all')
        if (any(f.get('transformations') for f in mission['fighters']) or any(p['transform_chance'] < 100 for p in mission.get('cpu_profiles',{}).values()) or
                any(a['type']=='transform' for e in mission['events'] for a in e['actions'])):
            builders.append(lambda r: npc_transform_policy.build_memory(r,settings=preferences,source=source,force=True))
        builders.append(lambda r: story_runtime.build_memory(r,mission,source=source))
    # Wraps those entries, the damage accumulator and the overhead-bar call again, so it is the last builder.
    import lockon_threat
    builders.append(lambda r: lockon_threat.build_memory(r,settings=preferences,source=source))
    import localization
    localization.pin_battle(preferences)
    with localization.using(preferences):
        # Scan the source's installed build once for every matching_install
        # builder below. A source that is legacy or mixed assumes nothing and
        # composes exactly as before; so does any result whose composed RAM no
        # longer reads as the assumed build.
        try:capacity=battle_mode_policy.installed_capacity(ram)
        except ValueError:capacity=None
        with battle_mode_policy.assumed_capacity(ram,capacity) as source_ram:
            if battle_mode_policy.known_capacity(source_ram) is None:
                return compose_manifests(ram, builders)
            manifest,composed=_compose(ram, builders)
        try:agrees=battle_mode_policy.installed_capacity(composed)==capacity
        except ValueError:agrees=False
        del composed
        return manifest if agrees else compose_manifests(ram, builders)


# Every earlier session leaves its recorded slots behind (a closed PCSX2 included), so this is routine, not a fault.
SLOTS_REUSED = 'Reused savestate slot(s) {slots} left by an earlier session.'
# The start wait counts only running time, so a timeout there cannot mean a paused PCSX2: the game stopped
# drawing (its render observer, capacity_stage CONTROL+16, stood still). Seen live: $gp corrupted mid-intro.
START_FROZE = ('The game stopped responding while the match was starting: its picture did not change for 10 seconds. '
               'Close PCSX2, then start {play} again.')
START_STALL_SECONDS = 10   # the number in START_FROZE (a translated sentence, not a template value)
SLOTS_FULL = ('Need two free savestate slots between 220 and 239 in {folder}, but the others hold savestates this mod '
              'did not create, which it never overwrites. Move those files out of that folder, then start {play} again')


class Session:
    def __init__(self, mode='Original', progress=None, play_intro=False, settings=None, battle_mode='teams', humans=1, assignment=None):
        if mode not in ('Original', 'Player', 'Cpu', 'TwoPlayer'): raise ValueError('Unknown controller mode')
        # Snapshot once, before claiming files or touching the emulator. An
        # edit in the settings window applies to the next prepared match.
        self.settings = mod_settings.load_settings() if settings is None else mod_settings.validate_settings(settings)
        if battle_mode not in ('teams','ffa','coop','training','training_coop') or humans not in battle_mode_policy.HUMAN_COUNTS:raise ValueError('Invalid match mode')
        if battle_mode in ('coop','training_coop') and humans not in (2,3,4):raise ValueError('Co-op requires two, three or four human players')
        if battle_mode=='training' and humans==0:raise ValueError('Modded Training requires one to four human players')
        # No human means every fighter is computer controlled, which is exactly
        # what the existing 'Cpu' controller mode already describes, and a
        # single full-screen view because nobody needs their own half.
        self.mode = ('TwoPlayer' if humans>=2
                     else 'Cpu' if humans==0
                     else 'Player' if battle_mode in ('ffa','training') else mode)
        self.battle_mode,self.humans=battle_mode,humans
        self.assignment=None if assignment is None else battle_mode_policy.human_seats(battle_mode,humans,assignment=assignment)
        self.progress_callback = progress
        self.play_intro = bool(play_intro)
        self.prepared = ROOT/'analysis/prepared-states'
        self.prepared.mkdir(parents=True, exist_ok=True)
        self.lock = acquire_lock(self.prepared/'.trainer.lock')
        self.run = self.prepared/time.strftime('%Y%m%d-%H%M%S')
        self.run = self.run.with_name(self.run.name+'-'+uuid.uuid4().hex[:8])
        self.index = 0
        self.source = None
        self.ram_path = self.run/'current-ee.bin'
        self.slots = []
        self.claims = []
        try:
            self.run.mkdir()
            self.reserve_slots()
            write_json(self.run/'session.json', dict(mode=mode, settings=self.settings, slots=[s for s,_ in self.slots],
                                                   status='preparing'))
        except BaseException:
            self.close(); raise

    def reusable_claim(self, slot, path, claim):
        """Only overwrite our exact prior file if an identical archive survives."""
        try:
            data = json.loads(claim.read_text())
            archive = Path(data['archive']).resolve()
            if data['slot'] != slot or not archive.is_relative_to(self.prepared.resolve()): return None
            if not archive.is_file() or digest(archive) != data['state_sha256']: return None
            if path.exists() and digest(path) != data['state_sha256']: return None
            return data
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def reserve_slots(self):
        """Claim two of savestate slots 220..239 for this run, under the exclusive trainer lock.

        Every *.trainer-claim.json is the trainer's own (PCSX2's menus cannot save to these
        slots) and names the process that wrote it. A claim whose process is gone was left by
        an interrupted session (a closed emulator, a killed watcher, a crash): its slot is
        taken over and its stale state file dropped (W1/F1). A live process's claim is reused
        only with a verified receipt, as before. A state file without any claim is someone
        else's and is never touched; neither are 218/219 or any slot outside this range.
        """
        STATES.mkdir(parents=True, exist_ok=True)
        reclaimed = []
        for slot in range(220, 240):
            path = STATES/f'{PREFIX}{slot:02}.p2s'; claim = path.with_suffix('.trainer-claim.json')
            if claim.exists():
                try: owner = json.loads(claim.read_text()).get('owner')
                except (OSError, ValueError, AttributeError): owner = None
                if owner_alive(owner):
                    data = self.reusable_claim(slot, path, claim)
                    if data is None: continue
                else:
                    try: path.unlink(missing_ok=True)
                    except OSError: continue
                    data = {}; reclaimed.append(slot)
                data.update(run=str(self.run), slot=slot, owner=claim_owner())
                try: write_claim(claim, data)
                except OSError: continue
            else:
                if path.exists(): continue
                try:
                    with claim.open('x') as f: json.dump(dict(run=str(self.run), slot=slot, owner=claim_owner()), f)
                except FileExistsError: continue
            self.slots.append((slot, path)); self.claims.append(claim)
            if len(self.slots) == 2: break
        import localization
        from native_preparation import launcher
        if reclaimed:
            print(localization.tr(SLOTS_REUSED, slots=', '.join(map(str, reclaimed))), flush=True)
        if len(self.slots) == 2: return
        # Already in the player's language: the folder is part of the sentence, so it has no fixed key.
        raise ValueError(localization.tr(SLOTS_FULL, folder=STATES, play=launcher()))

    def check_slot(self, index):
        slot, path = self.slots[index]; claim = self.claims[index]
        data = json.loads(claim.read_text())
        if data.get('run') != str(self.run) or data.get('slot') != slot:
            raise ValueError('Preparation slot ownership changed')
        if path.exists() and self.reusable_claim(slot, path, claim) is None:
            raise ValueError(f'Slot {slot} changed outside this trainer; preserving it')
        # The caller writes this slot next; close() frees it unless record_slot receipts it
        # again. An earlier receipt of this run no longer describes the file (W1).
        self._written = getattr(self, '_written', set()) | {index}
        self._recorded = getattr(self, '_recorded', set()) - {index}
        return slot, path

    def record_slot(self, index, archive):
        slot, path = self.slots[index]
        state_hash = digest(path)
        if state_hash != digest(archive): raise ValueError('Runtime state and retained checkpoint differ')
        write_claim(self.claims[index], dict(run=str(self.run), slot=slot,
            archive=str(Path(archive).resolve()), state_sha256=state_hash, owner=claim_owner()))
        self._recorded = getattr(self, '_recorded', set()) | {index}

    def close(self):
        if getattr(self, '_prepared_success', False) and not self.settings['keep_preparation_diagnostics']:
            try:
                self.compact_preparation()
            except (OSError, ValueError, zipfile.BadZipFile) as error:
                print(f'Keeping preparation diagnostics: {error}', flush=True)
        if (ROOT/'player-install.json').is_file() and not getattr(self,'settings',{}).get('keep_preparation_diagnostics',False):
            run=self.run.resolve()
            for path in getattr(self,'_raw_captures',set()):
                try:
                    if path.resolve().parent==run and path.suffix=='.bin' and path.exists() and path.stat().st_size==0x8000000:
                        path.unlink()
                except OSError as error:print(f'Could not remove temporary preparation image: {error}',flush=True)
        # Free every slot this run claimed but did not record (W1/F1): its state file is
        # scratch this run wrote (or none). An earlier receipt this run did not write over
        # stays as it is. Recorded slots keep their receipts.
        recorded, written = getattr(self, '_recorded', set()), getattr(self, '_written', set())
        for index, ((_, path), claim) in enumerate(zip(getattr(self, 'slots', []), getattr(self, 'claims', []))):
            if index in recorded: continue
            try:
                data = json.loads(claim.read_text())
                if data.get('run') != str(self.run) or ('archive' in data and index not in written): continue
                path.unlink(missing_ok=True); claim.unlink()
            except (OSError, ValueError): pass
        if getattr(self, 'lock', None) is not None:
            self.lock.close(); self.lock = None

    def compact_preparation(self):
        """Discard only this successful run's owned scratch images.

        Failed setups retain their inputs. Playable/held checkpoints, manifests,
        logs and runtime slot leases are never deleted here.
        """
        run=self.run.resolve();archive=Path(self.source).resolve()
        if not run.is_relative_to(self.prepared.resolve()) or archive.parent!=run or archive.suffix!='.p2s':
            raise ValueError('Preparation archive ownership changed')
        with zipfile.ZipFile(archive) as state:
            if state.getinfo('eeMemory.bin').file_size!=0x8000000:
                raise ValueError('Playable checkpoint is incomplete')
        removed=[];unwritten=getattr(self,'_unwritten_scratch',None)
        for path in getattr(self,'_raw_captures',set()):
            if path.resolve().parent!=run or path.suffix!='.bin':
                raise ValueError('Scratch image escaped its preparation run')
            if path.exists() and path.stat().st_size==0x8000000:
                path.unlink();removed.append(path.name)
            elif unwritten is not None and path==unwritten[0] and len(unwritten[1])==0x8000000:
                # Held in memory instead of written (StreamingSession); it
                # is discarded here exactly as the written copy was.
                self._unwritten_scratch=None;removed.append(path.name)
        if removed:
            write_json(run/'scratch-cleanup.json',dict(retained_playable=str(archive),removed=sorted(removed),
                reason='Preparation completed; intermediate RAM images are reproducible'))

    def client(self, require_running=True):
        p = PineClient(timeout=10)
        try:
            info = p.require_game(SERIAL, game_profile.pcsx2_crc())
            runtime_profile.require_version(info['version'])
            if info['status'] not in ('running', 'paused'):
                raise ValueError(f"Unexpected emulator status during preparation: {info['status']}")
            if require_running and info['status'] != 'running':
                raise ValueError('The game must be running during preparation; Space resumes it')
        except BaseException:
            p.close(); raise
        return p

    def snapshot(self, label, require_running=True):
        slot, path = self.check_slot(0)
        before = path.stat().st_mtime_ns if path.exists() else None
        # A pause right before the save waits for the player instead of failing (F2).
        with (self.running_client() if require_running else self.client(False)) as p: p.save_state(slot)
        deadline = time.monotonic()+30
        while time.monotonic() < deadline:
            time.sleep(.1)
            require_runtime()   # a closed emulator ends this file wait at once (W1)
            try:
                stat = path.stat()
                if stat.st_mtime_ns == before: continue
                with zipfile.ZipFile(path) as z:
                    if z.getinfo('eeMemory.bin').file_size != 0x8000000:
                        raise ValueError('The running emulator must have 128 MB EE memory enabled')
                target = self.run/f'{self.index:02}-{label}.p2s'
                partial = self.run/f'.{self.index:02}-{label}-{uuid.uuid4().hex}.partial'
                with path.open('rb') as source, partial.open('xb') as dest:
                    shutil.copyfileobj(source, dest)
                current = path.stat()
                if (stat.st_mtime_ns, stat.st_size) != (current.st_mtime_ns, current.st_size): continue
                # The temporary suffix is deliberately not .p2s; explicitly
                # decode the archive, including native ZIP93 and CRC checks.
                with zipfile.ZipFile(partial) as archive, partial.open('rb') as raw_file:
                    ram = read_entry(archive, raw_file, archive.getinfo('eeMemory.bin'))
                if len(ram) != 0x8000000: raise ValueError('Incomplete 128 MiB EE RAM snapshot')
                # Rename only a CRC-verified complete copy. Failed attempts
                # remain visibly partial and cannot be mistaken for recovery.
                if target.exists(): raise ValueError('Checkpoint output already exists')
                partial.rename(target)
                self.record_slot(0, target)
                self.index += 1
                self.source = target
                # Builders read this image by path; it is reproducible scratch (the .p2s is
                # the record), removed with the run's other owned captures.
                self._raw_captures = getattr(self, '_raw_captures', set()) | {self.ram_path}
                self.store_scratch(self.ram_path, ram)
                return ram
            except (FileNotFoundError, zipfile.BadZipFile, EOFError, PermissionError, KeyError):
                continue
        raise TimeoutError('PCSX2 did not finish saving the preparation checkpoint')

    def store_scratch(self, path, ram):
        path.write_bytes(ram)

    def install(self, manifest, label, require_running=True):
        from patch_state import patch
        if self.source is None: raise ValueError('Capture a source checkpoint before installation')
        with self.ram_path.open('rb') as stream:
            stream.seek(ACK_ADDRESS); expected_marker = stream.read(16)
        if len(expected_marker) != 16: raise ValueError('Missing complete captured EE RAM')
        marker = uuid.uuid4().bytes
        manifest = merge_manifests(manifest, {'blocks': [dict(address=ACK_ADDRESS,
            expected_hex=expected_marker.hex(), data_hex=marker.hex(), purpose='Immutable trainer load acknowledgement')]})
        manifest_path = write_json(self.run/f'{self.index:02}-{label}.json', manifest)
        output = self.run/f'{self.index:02}-{label}-patched.p2s'
        self.index += 1
        report = patch(self.source, manifest_path, output)
        if Path(report['output']).resolve() != output.resolve(): raise ValueError('Patcher returned an unexpected output path')
        slot, path = self.check_slot(1)
        # This slot was exclusively claimed by this run before any writes.
        shutil.copyfile(output, path)
        self.record_slot(1, output)
        with self.client(require_running) as p: p.load_state(slot)
        deadline = time.monotonic()+30
        while time.monotonic() < deadline:
            time.sleep(.1)
            with self.client(False) as p:
                if p.read(ACK_ADDRESS, len(marker)) == marker: return
        raise TimeoutError('PCSX2 did not load the prepared checkpoint')

    def wait_running(self, timeout=180):
        with self.client(False) as p:
            if p.status() == 'running': return
        print('Memory preparation installed. Focus the game and press Space to resume.', flush=True)
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            time.sleep(.2)
            with self.client(False) as p:
                if p.status() == 'running': return
        raise TimeoutError(f'The prepared match was not resumed within {timeout} seconds')

    def running_client(self):
        """A running-game client; while the user has paused, wait instead of failing."""
        while True:
            try:
                return self.client()
            except ValueError as error:
                if 'must be running' not in str(error): raise
                time.sleep(.5)

    def wait_word(self, address, expected, label, timeout=120):
        import localization
        print(localization.tr(label), flush=True)   # the player's language; failure reports keep the English step
        self.stage = label
        budget = ActiveRuntimeBudget(timeout)
        while True:
            with self.client(False) as p:
                running = budget.observe(p.status())
                value = p.read_u32(address)
            if running and value == expected: return
            if value >= 100:
                # Plain words keyed by the step: one status number means different things in different steps.
                reasons = {'Preparing expanded game memory...': {101: 'PCSX2 did not give the game its extra memory',
                                                                 102: 'PCSX2 did not give the game its extra memory',
                                                                 None: 'The expanded game memory could not be prepared'},
                           'Loading selected character resources...': {None: "A selected fighter's files could not be loaded from the disc"},
                           'Creating independent fighters...': {150: 'There are not enough model or drawing slots for this roster',
                                                                151: 'There are not enough model or drawing slots for this roster',
                                                                152: 'There are not enough model or drawing slots for this roster',
                                                                160: 'The game ran out of expanded memory for this roster',
                                                                161: 'The game ran out of expanded memory for this roster',
                                                                None: 'A selected fighter could not be created'},
                           'Expanding graphics buffers...': {None: 'The graphics buffers could not be expanded'},
                           'Initializing individual NPCs...': {None: 'The CPU fighters could not be set up'}}.get(label, {})
                reason = reasons.get(value, reasons.get(None, 'A setup step reported an error'))
                raise RuntimeError(f'{reason} (step "{label}", guest status {value} at {address:08X})')
            if budget.expired: break
            time.sleep(.2)
        raise TimeoutError(f'{label}: the game did not finish this step within {timeout} seconds')

    def prepare(self):
        self.progress('Preparing team battle', 0)
        if not isinstance(self, StreamingSession):   # the native-frame path needs the game running
            print(f'Capturing a fresh idle team match with up to {battle_mode_policy.TEAM_CAPACITY} fighters per side. You may start with the game paused.', flush=True)
        ram = self.snapshot('original-selected-match', require_running=False)
        import story_missions
        mission=story_missions.armed() if self.battle_mode == 'teams' else None
        minimum_members=2 if mission is not None or battle_mode_policy.prepare_singleton(self.battle_mode,self.humans) else 1
        selection = capture(ram,minimum_members=minimum_members)
        if mission is not None:
            import story_runtime
            mission=story_runtime.validate_selection(mission,selection,ram,self.humans,self.assignment)
        if self.battle_mode in ('coop','training_coop') or self.humans>=3 or self.assignment is not None:
            battle_mode_policy.validate_roster('coop' if self.battle_mode=='training_coop' else 'teams' if self.battle_mode=='training' else self.battle_mode,2*selection['members_per_side'],
                                               selection['participation_mask'],self.humans,self.assignment)
        if not 2 <= selection['members_per_side'] <= battle_mode_policy.TEAM_CAPACITY:
            raise ValueError(f'Select up to {battle_mode_policy.TEAM_CAPACITY} fighters on each team, with at least one extra fighter')
        capture_path = write_json(self.run/'selection.json', selection)
        self.progress('Loading fighters', 1)
        self.install(fresh_memory.build(self.source), 'memory', require_running=False)
        self.wait_running()
        self.wait_word(fresh_memory.CONTROL, 20, 'Preparing expanded game memory...')
        self.wait_idle_leaders()
        self.snapshot('heap-ready')
        loader = resources.build(self.source, hold_idle=isinstance(self, StreamingSession),fast_pump=isinstance(self, StreamingSession),minimum_members=minimum_members)
        loader_path = write_json(self.run/'resource-queue.json', loader)
        self.install(loader, 'resources')
        self.wait_word(resources.CONTROL+4, 5, 'Loading selected character resources...')
        self.wait_idle_leaders()
        self.snapshot('resources-ready')
        self.progress('Loading fighters', 2)
        bindings = write_json(self.run/'resource-bindings.json', resources.export(self.source, loader_path))
        import bt4_model_metadata
        self.install(bt4_model_metadata.build_memory(read_ram(self.source),
                     json.loads(bindings.read_text())['bindings']), 'bt4-metadata')
        self.snapshot('metadata-ready')
        self.install(creation.build(self.source, capture_path, bindings), 'actors')
        self.wait_word(creation.HEADER, 20, 'Creating independent fighters...')
        self.snapshot('actors-created')
        self.progress('Preparing arena', 3)
        self.install(render.build('observe', self.source), 'render-observer')
        self.wait_word(render.cap.CONTROL+52, 5, 'Checking rendering...')
        self.wait_counter(render.cap.CONTROL+16, 2)
        self.snapshot('render-observed')
        self.install(merge_manifests(render.build('grow', self.source), packets.build(self.source)), 'render-capacity')
        self.wait_word(render.cap.CONTROL+68, 20, 'Expanding render object capacity...')
        self.wait_word(packets.CONTROL, 5, 'Expanding graphics buffers...')
        ram = self.snapshot('render-ready')
        self.progress('Preparing arena', 4)
        config = actor_config(ram, self.mode, selection, battle_mode=self.battle_mode,humans=self.humans,assignment=self.assignment)
        write_json(self.run/'team-config.json', config)
        core = combat.build(self.source, config)
        guards = safety.build(self.source, config)
        installation = ai.build_install(self.ram_path, config)
        support = merge_support(core['support'], guards['support'], render.support(self.source), installation['support'])
        write_json(self.run/'support.json', support)
        write_json(self.run/'ai-installation.json', installation)
        self.install(merge_manifests(core, guards, installation), 'combat-engine')
        self.snapshot('combat-installed')
        self.install(ai.build_arm(self.ram_path, installation, support), 'arm-ai')
        self.wait_word(ai.CONTROL, 5, 'Initializing individual NPCs...')
        # P-1: spawn placement is built from this image and needs every captured fighter standing idle.
        self.wait_idle_leaders(actors=[row['actor'] for row in config['actors']])
        # snapshot() returns exactly the image it stored at ram_path.
        ram = self.snapshot('ai-ready')
        self.progress('Getting ready', 5)
        activation = ai.build_activation(self.ram_path, installation, support)
        if self.mode == 'TwoPlayer' or self.humans == 0:
            activation['blocks'].append(ai.block(ram, A(0x331DC8)+36,
                struct.pack('<I', int(self.mode == 'TwoPlayer')), 'Set selected controller view layout'))
        # Install every dependent quality patch before the first exposed frame.
        final = final_team_manifest(ram, activation, self.source, play_intro=self.play_intro,
            pause_mode=self.settings[mod_settings.MODE_KEY], present_mask=selection['participation_mask'],
            settings=self.settings, battle_mode=self.battle_mode, humans=self.humans,assignment=self.assignment,mission=mission)
        self.install(final, 'complete-team')
        if mission is not None:
            write_json(self.run/'mission.json',mission)
        self.wait_word(extra_ground_effects.CONTROL, 5, 'Preparing dust and terrain effects...')
        self.wait_word(extra_generic_effects.CONTROL, 5, 'Preparing each fighter\'s cosmetic effects...')
        self.wait_word(extra_extended_auras.CONTROL, 5, 'Preparing afterimages and giant auras...')
        self.wait_word(extra_charge_aura.CONTROL, 5, 'Preparing fighter auras...')
        self.wait_word(extra_special_pools.CONTROL, 5, 'Preparing individual special effects...')
        self.wait_word(spawn_placement.CONTROL, 5, 'Placing fighters on the arena terrain...')
        self.wait_word(team_participation.CONTROL, 5, 'Checking selected fighter participation...')
        self.wait_counter(ai.CONTROL+0x10, 10)
        ram = self.snapshot('ready-held')
        self.export_playable(ram)
        # The optional presentation callback uncovers the ready arena before
        # the data-only start signal. No save or reload occurs after uncovering.
        self.progress('Ready', 6)
        self.release_start()
        if mission is not None:
            try:story_missions.consumed(mission)
            except (OSError,ValueError,KeyError) as error:
                # The world is already running. A concurrently edited queue
                # must not tear down its healthy reload/camera services.
                print(f'Warning: match started, but the queued story mission could not be cleared: {error}',flush=True)
        status = dict(mode=self.mode, battle_mode=self.battle_mode, humans=self.humans,assignment=self.assignment,
            settings=self.settings, slots=[s for s,_ in self.slots],
            status='active', playable_state=str(self.source))
        # Only a retained original checkpoint is named (F9): the state-load path keeps its
        # .p2s; a streaming run's original image is scratch that compaction removes.
        original = next(self.run.glob('*original-selected-match.p2s'), None)
        if original is not None: status['original'] = str(original)
        write_json(self.run/'session.json', status)
        print(f'Team activated. Restart checkpoint: {self.source}', flush=True)
        print('The automatic launcher handles rematches. For manual sessions, reload this checkpoint to restart.', flush=True)
        self._prepared_success=True

    def progress(self, label, completed):
        self.stage = label  # the step a failure report names
        if self.progress_callback is not None: self.progress_callback(label, completed, 6)

    def export_playable(self, ram):
        from patch_state import patch
        for control in (extra_ground_effects.CONTROL, extra_generic_effects.CONTROL, extra_extended_auras.CONTROL, extra_charge_aura.CONTROL, extra_special_pools.CONTROL, spawn_placement.CONTROL, team_participation.CONTROL):
            if (struct.unpack_from('<I', ram, control)[0] != 5 or
                    struct.unpack_from('<I', ram, control+4)[0] != struct.unpack_from('<I', ram, A(0x2FEB14))[0]):
                raise ValueError('Fighter effects and terrain placement must finish before export')
        if struct.unpack_from('<I', ram, team_start_gate.REQUEST)[0] != 0:
            raise ValueError('Expected a held prepared match')
        output = self.run/f'{self.index:02}-playable-team.p2s'
        request = team_intro.REQUEST if self.play_intro else team_start_gate.REQUEST
        if struct.unpack_from('<I', ram, request)[0] != 0:
            raise ValueError('Expected an unrequested intro/start signal')
        manifest = dict(serial=SERIAL, crc=CRC, blocks=[dict(
            address=request, expected_hex='00000000', data_hex='01000000')])
        # A rematch checkpoint must be playable without a running watcher.
        if ram[guest_loading_screen.HOOK:guest_loading_screen.HOOK+4] == guest_loading_screen.code_pieces()[-1][1]:
            manifest['blocks'].append(dict(address=guest_loading_screen.CONTROL,
                expected_hex=ram[guest_loading_screen.CONTROL:guest_loading_screen.CONTROL+4].hex(),data_hex='00000000'))
        import native_preparation
        if struct.unpack_from('<I',ram,native_preparation.CONTROL)[0]==native_preparation.MAGIC:
            manifest['blocks'].append(dict(address=native_preparation.CONTROL,
                expected_hex=ram[native_preparation.CONTROL:native_preparation.CONTROL+4].hex(),data_hex='00000000'))
        report = patch(self.source, manifest, output)
        write_json(self.run/'playable-export.json', report)
        self.index += 1; self.source = output

    def release_start(self):
        with self.running_client() as p:
            manager=p.read_u32(A(0x2FEB14))
            for control in (extra_ground_effects.CONTROL, extra_generic_effects.CONTROL, extra_extended_auras.CONTROL, extra_charge_aura.CONTROL, extra_special_pools.CONTROL, spawn_placement.CONTROL, team_participation.CONTROL):
                if p.read_u32(control) != 5 or p.read_u32(control+4) != manager:
                    raise ValueError('Fighter effects or terrain placement are not ready for this match')
            count=p.read_u32(team_start_gate.CONTROL+12)
            marker=p.read(ACK_ADDRESS,16)
            if (count not in ACTOR_COUNTS or len(marker)!=16 or
                    struct.unpack('<4I',p.read(combat.MODE,16))!=(1,count,manager,count)):
                raise ValueError('Prepared start identity changed')
            if p.read(guest_loading_screen.HOOK,4)==guest_loading_screen.code_pieces()[-1][1]:
                p.write_u32(guest_loading_screen.CONTROL,0)
                if p.read_u32(guest_loading_screen.CONTROL)!=0:
                    raise RuntimeError('Loading screen did not clear; fighters remain held')
            if p.read_u32(team_start_gate.CONTROL) != 1 or p.read_u32(team_start_gate.CONTROL+8) != manager:
                raise ValueError('Prepared start-gate identity changed')
            request = team_intro.REQUEST if self.play_intro else team_start_gate.REQUEST
            if self.play_intro and (p.read_u32(team_intro.CONTROL) != 1 or
                    p.read_u32(team_intro.CONTROL+8) != manager):
                raise ValueError('Prepared intro identity changed')
            p.write(request, struct.pack('<I', 1))
        budget = ActiveRuntimeBudget(90 if self.play_intro else 10)
        stall, heartbeat = ActiveRuntimeBudget(START_STALL_SECONDS), None
        while True:
            with self.client(False) as p:
                status = p.status()
                budget.observe(status)
                if (p.read_u32(A(0x2FEB14))!=manager or p.read(ACK_ADDRESS,16)!=marker or
                        p.read_u32(team_start_gate.CONTROL+8)!=manager or
                        p.read_u32(team_start_gate.CONTROL+12)!=count or
                        struct.unpack('<4I',p.read(combat.MODE,16))!=(1,count,manager,count)):
                    raise ValueError('Prepared match changed before start acknowledgement')
                if p.read_u32(team_start_gate.CONTROL+20) == 1: return
                # Only a render observer that is installed and counting (as the watcher's freeze watch).
                counting = (p.read_u32(render.cap.CONTROL) == render.cap.MAGIC and p.read_u32(render.cap.CONTROL+48) == 1)
                beat = p.read_u32(render.cap.CONTROL+16) if counting else None
            if beat is None or beat != heartbeat:
                stall, heartbeat = ActiveRuntimeBudget(START_STALL_SECONDS), beat
            stall.observe(status)
            if stall.expired:
                from native_preparation import launcher
                raise RuntimeError(START_FROZE.format(play=launcher()))
            if budget.expired: break
            time.sleep(.1)
        raise TimeoutError('Prepared team did not accept the start signal')

    def wait_counter(self, address, minimum):
        budget = ActiveRuntimeBudget(30)
        while True:
            with self.client(False) as p:
                running = budget.observe(p.status())
                if running and p.read_u32(address) >= minimum: return
            if budget.expired: break
            time.sleep(.2)
        raise TimeoutError(f'No expected game-frame progress at {address:08X}')

    def wait_idle_leaders(self, actors=None):
        # The match-start pose can briefly change11 to67 after loading. Short
        # two-resource queues can finish during that pose; creation requires
        # genuine idle, not merely zero input. Keep the preparation hold intact.
        # actors (P-1): every captured fighter, right before the image spawn placement is built from (its guest
        # check, error 102, reads the same pose about a second later). A held fighter plays the idle taunt 67
        # (IDLE_COUNT) for about 2.6 s: wait it out, then restart every idle count so no taunt starts before the
        # placement runs. A fighter that never settles stops the setup with spawn_placement.NOT_IDLE.
        if actors is not None and not all(0x100000 <= a < 0x8000000-0x1600 for a in actors):
            raise AssertionError('Captured fighter addresses are outside game memory')   # an internal check (TTM-MATCH-06)
        budget = ActiveRuntimeBudget(30)
        while True:
            with self.client(False) as p:
                running = budget.observe(p.status())
                if p.read_u32(fresh_memory.CONTROL+80) != 1:
                    raise ValueError('Fresh preparation input hold was released unexpectedly')
                manager = p.read_u32(A(0x2FEB14))
                if manager != p.read_u32(fresh_memory.CONTROL+84):
                    raise ValueError('Fresh preparation actor manager changed')
                actor = p.read_u32(manager+4)
                held = (actor, actor+0x1600) if actors is None else actors
                if running and all(p.read_u32(a+0x948) == 11 and not any(p.read_u32(a+o)
                       for o in (0x1278, 0x127C, 0x1280, 0x1284))
                       for a in held):
                    if actors is not None:
                        for a in held: p.write_u32(a+IDLE_COUNT, 0)
                    return
            if budget.expired: break
            time.sleep(.2)
        if actors is not None:
            from native_preparation import launcher
            raise ValueError(spawn_placement.NOT_IDLE.format(play=launcher()))
        raise TimeoutError('Both held leaders did not return to idle for preparation')


class StreamingSession(Session):
    """Prepare on the native frame thread; save only the final rematch image.

    Builders receive every stage image in memory under the path they are given
    (camera_snapshot.publish). Retained images are still written. The reused
    current-ee.bin scratch is written only when a run keeps it on disk (a
    stopped preparation), so its files are exactly what they always were.
    """
    def snapshot(self,label,require_running=True):
        import native_preparation as native
        # A pause at a stage boundary waits for the player instead of failing (F2).
        with self.running_client() as p:
            native.quiet(p)
            if label!='ready-held':
                ram=native.read_ram(p)
        if label=='ready-held':
            # One final checkpoint, under the still-animated cover, supplies
            # native GS/IO state for rematches. It is never loaded during setup.
            self.ram_path=self.run/'current-ee.bin'
            self._raw_captures=getattr(self,'_raw_captures',set())|{self.ram_path}
            return super().snapshot(label)
        retain=self.settings['keep_preparation_diagnostics'] or label=='original-selected-match'
        target=self.run/(f'{self.index:02}-{label}.bin' if retain else 'current-ee.bin')
        if not retain and target.exists() and target not in getattr(self,'_raw_captures',set()):
            raise ValueError('Unowned preparation scratch file')
        if retain:
            with target.open('xb') as f:f.write(ram)
            self.publish_image(target,ram)
        self._raw_captures=getattr(self,'_raw_captures',set())|{target}
        if not retain:self.store_scratch(target,ram)
        # Normal runs reuse scratch; optional diagnostics retain every stage.
        self.index+=1;self.source=target;self.ram_path=target
        return ram

    def publish_image(self,path,ram):
        data=ram if type(ram) is bytes else bytes(ram)
        publish(path,data)
        self._published_images=getattr(self,'_published_images',set())|{path}
        return data

    def store_scratch(self,path,ram):
        if self.settings['keep_preparation_diagnostics']:
            return super().store_scratch(path,ram)
        # The previous image at this path is superseded; a reader that is not
        # served from memory now fails instead of reading an older stage.
        self._unwritten_scratch=None
        path.unlink(missing_ok=True)
        self._unwritten_scratch=(path,self.publish_image(path,ram))

    def keep_scratch(self):
        """Write the scratch image a run keeps on disk, as every stage once was."""
        unwritten=getattr(self,'_unwritten_scratch',None)
        if unwritten is None:return
        self._unwritten_scratch=None
        path,ram=unwritten
        try:
            with path.open('wb') as f:f.write(ram)
        except OSError as error:print(f'Could not keep the last preparation image: {error}',flush=True)

    def compact_preparation(self):
        try:super().compact_preparation()
        except BaseException:
            self.keep_scratch()
            raise

    def close(self):
        try:
            if not getattr(self,'_prepared_success',False):
                # A stopped preparation keeps its last stage image, except in a
                # player install, whose close removes every scratch image anyway.
                if (ROOT/'player-install.json').is_file():self._unwritten_scratch=None
                else:self.keep_scratch()
            super().close()
        finally:
            self.keep_scratch()
            for path in getattr(self,'_published_images',()):retract(path)
            self._published_images=set()

    def install(self,manifest,label,require_running=True):
        import native_preparation as native
        if self.source is None:raise ValueError('Capture a source before installation')
        image=published(self.ram_path)
        if image is not None:expected_marker=image[ACK_ADDRESS:ACK_ADDRESS+16]
        else:
            with self.ram_path.open('rb') as stream:
                stream.seek(ACK_ADDRESS);expected_marker=stream.read(16)
        if len(expected_marker)!=16:raise ValueError('Missing complete captured EE RAM')
        marker=uuid.uuid4().bytes
        manifest=merge_manifests(manifest,{'blocks':[dict(address=ACK_ADDRESS,
            expected_hex=expected_marker.hex(),data_hex=marker.hex())]})
        write_json(self.run/f'{self.index:02}-{label}.json',manifest);self.index+=1
        with self.running_client() as p:
            native.apply(p,manifest)
            if p.read(ACK_ADDRESS,16)!=marker:raise RuntimeError('Native stage marker was not committed')
            native.resume(p)

    def release_start(self):
        import native_preparation as native
        with self.running_client() as p:native.resume(p)
        super().release_start()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('Original', 'Player', 'Cpu', 'TwoPlayer'), default='Original')
    args = parser.parse_args()
    import sys
    for stream in (sys.stdout, sys.stderr):
        try: stream.reconfigure(errors='backslashreplace')
        except (AttributeError, ValueError, OSError): pass
    session = None
    try:
        session = Session(args.mode)
        session.prepare()
    except Exception as error:  # noqa: BLE001 - every failure is explained, with its traceback kept
        import traceback
        import player_errors
        stage = getattr(session, 'stage', None)
        explanation = player_errors.explain(error, 'preparation', stage)
        for line in player_errors.console_lines(explanation): print(line, flush=True)
        traceback.print_exc()
        if session:
            originals = list(session.run.glob('*original-selected-match.p2s'))
            if originals: print(f'Restore the original checkpoint before retrying: {originals[0]}', flush=True)
            write_json(session.run/'failure.json', dict(error=explanation.detail, code=explanation.code, stage=stage,
                                                        traceback=traceback.format_exc()))
        return 1
    finally:
        if session: session.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
