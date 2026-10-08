"""Hold/release R3 to switch targets; short taps retain native form changes.

Upgrade the existing lockon_switch wrapper without changing native battle or
damage code. A plain R3 hold of15 updates queues a switch on release; D-pad/L3
chords do not. Native raw input is never consumed. At most one request remains
pending per human fighter, expiring after600 active updates by default.

The switch button is the runtime word at CONTROL+8 (R3 0x4 by default, L3 0x2
through Mod settings). The original emission keeps the chord mask 0xF2 as an
immediate, so it can only serve R3; the button-aware emission derives the mask
at runtime as 0xF6 & ~button (D-pad plus the other stick button), which equals
0xF2 for R3 and leaves L3+R3 native under an L3 binding. R3 installs keep the
original bytes so every existing exact-byte guard remains valid.
"""
from native_map import A, CRC, SERIAL
import argparse
import json
import struct
from pathlib import Path

from prototype import Assembler, ROOT
from camera_snapshot import read_ram
import fresh_team_combat as core
import lockon_switch as old
from battle_mode_policy import ACTOR_COUNTS
import battle_mode_policy as policy
import input_binding
from native_map import ACTOR_HZ, ticks

CODE, END = 0x073D7000, 0x073D8000
CONTROL, HOOK = old.CONTROL, old.HOOK
DEFAULT_TIMEOUT = ticks(600)
HOLD_UPDATES, CHORD_MASK = 15, 0xF2
STICK_CHORDS = 0xF6  # D-pad|L3|R3: the button-aware chord mask before removing the bound button
BUTTON_NAMES = {mask:input_binding.LABELS[name] for name,mask in input_binding.MASKS.items()}
CONFIGURABLE = 2
TIMING_UPDATES, TIMING_MAGIC = 0x58, 0x5C
TIMING_TAG = 0x4C4B5431  # LKT1; shared with spectator gestures
MAX_HOLD_UPDATES = 3600*ACTOR_HZ  # one hour at the game's 30 (European 25) battle updates/second
# The legacy edge-triggered emission (hold_release=False) must stay byte for
# byte what prepared presets 212..214 carry, so it keeps these offsets.
LEGACY_FIELDS = dict(old.FIELDS, queued=20, expired=24, cancelled=28,
                     timeout=0x50, coalesced=0x54, pending=0x80,
                     held=0xA0, chorded=0xC0)
# The current emission keeps its per-fighter arrays above the first 0x100 bytes
# of the control block, twelve slots each. The legacy arrays hold eight: the
# cancel path writes held/chorded/pending for EVERY fighter each frame, so at
# nine or ten fighters CPU fighter 8's pending slot landed on player 1's held
# counter and zeroed it, and the hold-to-switch gesture could never complete.
SLOTS = policy.ENGINE_ACTORS
FIELDS = dict(LEGACY_FIELDS, pending=0x100, held=0x100+4*SLOTS, chorded=0x100+8*SLOTS)
WIDE_END = FIELDS['chorded']+4*SLOTS
# Three-a-side installs (release checkpoints 8/9/10 and their cached copies)
# carry the hold/release emission with six slots in the legacy arrays.
LEGACY_SLOTS = 6


def layout():
    """(fields, slots) of the hold/release emission for the build being emitted."""
    if policy.emitted_capacity() == policy.LEGACY_TEAM_CAPACITY:
        return LEGACY_FIELDS, LEGACY_SLOTS
    return FIELDS, SLOTS
SAVED = tuple((16+i, i*8) for i in range(6))


def chord(a, button_aware):
    """Leave t0 = previous raw & chord mask; t1/t2 are scratch when button aware."""
    if button_aware == CONFIGURABLE:
        a.move(8,0);return  # User-chosen controls also work while moving.
    if not button_aware:
        a.i(12, 8, 8, CHORD_MASK); return
    # mask = (STICK_CHORDS | button) ^ button == STICK_CHORDS & ~button (no nor).
    a.lw(9, 16, FIELDS['button']); a.i(13, 10, 9, STICK_CHORDS); a.r(0x26, 9, 10, 9)
    a.r(0x24, 8, 8, 9)


def payload(previous, hold_release=True, free_for_all=False, coop_controls=False, button_aware=False, pad_resolver=None, lockoff=False):
    F, slots = layout() if hold_release else (LEGACY_FIELDS, 12)
    a = Assembler(CODE); a.addiu(29, 29, -0x40)
    for reg, off in SAVED: a.i(63, reg, 29, off)
    a.li(16, CONTROL); core.gate(a, 'inactive')
    a.lw(8, 16); a.branch(4, 8, 0, 'inactive')
    a.lw(8, 16, 4); a.lw(9, 28, -22364); a.branch(5, 8, 9, 'inactive')
    a.li(8, core.PAIR+4); a.lw(8, 8); a.branch(5, 8, 0, 'done')
    a.lw(8, 16, F['frames']); a.addiu(8, 8, 1); a.sw(8, 16, F['frames'])
    a.move(17, 10); a.move(18, 0)
    a.label('actor'); a.r(0x2B, 8, 18, 17); a.branch(4, 8, 0, 'done')
    a.r(0, 9, 0, 18, 2); a.r(0x2D, 21, 16, 9)
    a.li(8, core.POINTERS); a.r(0x2D, 8, 8, 9); a.lw(19, 8)
    a.branch(4, 19, 0, 'cancel')
    a.lw(8, 19, 0x1278); a.branch(5, 8, 0, 'cancel')
    # Sample the edge even while action/transfer gates block its execution.
    a.lw(8, 19, 4)
    a.i(11, 9, 8, 2); a.branch(4, 9, 0, 'cancel')
    a.r(0, 9, 0, 8, 6); a.r(0, 10, 0, 8, 7); a.r(0x2D, 9, 9, 10)
    a.r(0, 10, 0, 8, 8); a.r(0x2D, 9, 9, 10); a.li(10, old.RECORDS); a.r(0x2D, 9, 9, 10)
    if coop_controls or pad_resolver is not None:
        import coop_controller
        a.addiu(29,29,-0x20)
        for k,r in enumerate((2,3,4,31)):a.i(63,r,29,8*k)
        a.move(4,19);a.call(coop_controller.ACTOR_PAD if pad_resolver is None else pad_resolver);a.move(9,2)
        for k,r in enumerate((2,3,4,31)):a.i(55,r,29,8*k)
        a.addiu(29,29,0x20)
    a.lw(12, 9, 328); a.lw(13, 21, F['previous']); a.sw(12, 21, F['previous'])
    a.lw(14, 16, F['button']); a.r(0x24, 12, 12, 14); a.r(0x24, 13, 13, 14)
    # A dead human has no lock-on request to replay after the surviving actors.
    a.lw(8, 19, 0x994); a.i(11, 9, 8, 5); a.branch(4, 9, 0, 'cancel')
    a.r(0, 9, 0, 8, 7); a.r(0, 10, 0, 8, 5); a.r(0x2D, 9, 9, 10)
    a.r(0, 10, 0, 8, 2); a.r(0x2D, 9, 9, 10); a.r(0x2D, 9, 9, 19)
    a.lw(8, 9, 0x9E4); a.branch(6, 8, 0, 'cancel')
    if lockoff:
        import lockoff_target as unlock
        a.move(4,19);a.lw(5,21,F['previous']);a.move(6,18)
        a.addiu(29,29,-16);a.i(63,31,29,0);a.call(unlock.INPUT)
        a.i(55,31,29,0);a.addiu(29,29,16)
        a.branch(4,2,0,'pending')
    elif hold_release:
        a.branch(4, 12, 0, 'released')
        a.branch(5, 13, 0, 'held')
        a.sw(0, 21, F['held']); a.sw(0, 21, F['chorded'])
        a.label('held'); a.lw(8, 21, F['held'])
        if button_aware == CONFIGURABLE:
            a.lw(9,16,TIMING_UPDATES);a.r(0x2B,9,8,9)
        else:a.i(11, 9, 8, HOLD_UPDATES)
        a.branch(4, 9, 0, 'hold_counted')
        a.addiu(8, 8, 1); a.sw(8, 21, F['held'])
        a.label('hold_counted'); a.lw(8, 21, F['previous'])
        chord(a, button_aware); a.branch(4, 8, 0, 'pending')
        a.addiu(8, 0, 1); a.sw(8, 21, F['chorded']); a.jump('pending')
        a.label('released'); a.branch(4, 13, 0, 'pending')
        a.lw(8, 21, F['held']); a.sw(0, 21, F['held'])
        a.lw(9, 21, F['chorded']); a.sw(0, 21, F['chorded'])
        if button_aware == CONFIGURABLE:
            a.lw(10,16,TIMING_UPDATES);a.r(0x2B,8,8,10)
        else:a.i(11, 8, 8, HOLD_UPDATES)
        a.branch(5, 8, 0, 'pending')
        a.branch(5, 9, 0, 'pending')
        a.lw(8, 21, F['previous']); chord(a, button_aware)
        a.branch(5, 8, 0, 'pending')
    else:
        # Exact previous payload is retained for guarded upgrades of212..214.
        a.branch(4, 12, 0, 'pending'); a.branch(5, 13, 0, 'pending')
    a.lw(8, 21, F['pending']); a.branch(4, 8, 0, 'new_request')
    a.lw(8, 16, F['coalesced']); a.addiu(8, 8, 1); a.sw(8, 16, F['coalesced'])
    a.label('new_request')
    a.lw(8, 16, F['timeout']); a.addiu(9, 8, -1); a.i(11, 9, 9, 3600)
    a.branch(5, 9, 0, 'timeout_ok'); a.addiu(8, 0, DEFAULT_TIMEOUT)
    a.label('timeout_ok'); a.sw(8, 21, F['pending'])
    a.lw(8, 16, F['queued']); a.addiu(8, 8, 1); a.sw(8, 16, F['queued'])
    a.label('pending'); a.lw(8, 21, F['pending']); a.branch(4, 8, 0, 'next')
    a.lw(8, 19, 0x948)
    # Transformation ownership begins before a cinematic model is bound. Keep
    # the legacy emitter exact so existing212 checkpoints remain upgradeable.
    for start, span in old.PAIRED_STATES + (((236, 8),) if hold_release else ()):
        a.addiu(9, 8, -start); a.i(11, 9, 9, span); a.branch(5, 9, 0, 'wait')
    for offset in old.PENDING:
        a.lw(8, 19, offset); a.branch(5, 8, 0, 'wait')
    # Native camera23DCE0/23DD08 bind an actual model in+768 or+772.
    # Preserve that ownership even if this actor's action does not identify the
    # paired sequence. An unrelated fighter is still free to change its target.
    a.li(8, A(0x2FEBCC)); a.lw(11, 8); a.branch(4, 11, 0, 'safe')
    a.li(8, 0x100000); a.r(0x2B, 9, 11, 8); a.branch(5, 9, 0, 'wait')
    a.li(8, 0x08000000-816); a.r(0x2B, 9, 11, 8); a.branch(4, 9, 0, 'wait')
    a.lw(8, 11, 812); a.branch(5, 8, 0, 'camera_active')
    a.lw(8, 11, 704); a.branch(4, 8, 0, 'safe')
    a.lw(8, 11, 776); a.i(12, 8, 8, 3); a.addiu(9, 0, 1); a.branch(5, 8, 9, 'safe')
    a.label('camera_active'); a.lw(8, 19, 12); a.i(11, 9, 8, 12); a.branch(4, 9, 0, 'wait')
    a.r(0, 8, 0, 8, 2); a.li(9, core.MODELS); a.r(0x2D, 8, 8, 9); a.lw(8, 8)
    a.branch(4, 8, 0, 'wait')
    for offset in (768, 772):
        a.lw(9, 11, offset); a.branch(4, 8, 9, 'wait')
    a.label('safe')
    if lockoff:
        a.move(4,19);a.move(5,18)
        a.addiu(29,29,-16);a.i(63,31,29,0);a.call(unlock.APPLY)
        a.i(55,31,29,0);a.addiu(29,29,16)
        a.branch(5,2,0,'consume')
    a.li(8, core.TABLE); a.r(0, 9, 0, 18, 2); a.r(0x2D, 15, 8, 9); a.lw(20, 15)
    a.move(14, 20); a.move(11, 0)
    a.label('search'); a.addiu(11, 11, 1); a.r(0x2B, 8, 17, 11); a.branch(5, 8, 0, 'consume')
    a.addiu(14, 14, 1); a.r(0x2B, 8, 14, 17); a.branch(5, 8, 0, 'wrapped'); a.move(14, 0)
    a.label('wrapped'); a.branch(4, 14, 20, 'consume')
    if free_for_all: a.branch(4, 14, 18, 'search')
    else: a.i(12, 8, 14, 1); a.i(12, 9, 18, 1); a.branch(4, 8, 9, 'search')
    a.li(8, core.POINTERS); a.r(0, 9, 0, 14, 2); a.r(0x2D, 8, 8, 9); a.lw(9, 8)
    a.branch(4, 9, 0, 'search')
    a.lw(8, 9, 0x994); a.i(11, 10, 8, 5); a.branch(4, 10, 0, 'search')
    a.r(0, 10, 0, 8, 7); a.r(0, 12, 0, 8, 5); a.r(0x2D, 10, 10, 12)
    a.r(0, 12, 0, 8, 2); a.r(0x2D, 10, 10, 12); a.r(0x2D, 10, 10, 9)
    a.lw(10, 10, 0x9E4); a.branch(6, 10, 0, 'search')
    a.sw(14, 15)
    a.lw(8, 16, F['switches']); a.addiu(8, 8, 1); a.sw(8, 16, F['switches'])
    a.lw(8, 21, F['per_actor']); a.addiu(8, 8, 1); a.sw(8, 21, F['per_actor'])
    a.label('consume'); a.sw(0, 21, F['pending']); a.jump('next')
    a.label('wait'); a.lw(8, 21, F['pending']); a.addiu(8, 8, -1); a.sw(8, 21, F['pending'])
    a.branch(5, 8, 0, 'next')
    a.lw(8, 16, F['expired']); a.addiu(8, 8, 1); a.sw(8, 16, F['expired']); a.jump('next')
    a.label('cancel')
    if lockoff:
        unlock.emit_clear(a,18)
    if hold_release:
        a.sw(0, 21, F['held']); a.sw(0, 21, F['chorded'])
    a.lw(8, 21, F['pending'])
    a.branch(4, 8, 0, 'next'); a.sw(0, 21, F['pending'])
    a.lw(8, 16, F['cancelled']); a.addiu(8, 8, 1); a.sw(8, 16, F['cancelled'])
    a.label('next'); a.addiu(18, 18, 1); a.jump('actor')
    a.label('inactive')
    # Drop pending requests across teardown, retaining the last edge sample so
    # a still-held button cannot replay the cancelled press after re-enabling.
    for i in range(slots):
        if lockoff:
            a.addiu(8,0,i);unlock.emit_clear(a,8)
        a.sw(0, 16, F['pending']+4*i)
        if hold_release:
            a.sw(0, 16, F['held']+4*i); a.sw(0, 16, F['chorded']+4*i)
    a.label('done')
    for reg, off in SAVED: a.i(55, reg, 29, off)
    a.addiu(29, 29, 0x40); a.jump(previous)
    data = a.finish(); assert CODE+len(data) <= END; return data


def build_memory(ram, config=None, source='<offline-memory>', timeout=DEFAULT_TIMEOUT, hold_updates=None):
    if len(ram) != 0x08000000: raise ValueError('Requires128MiB captured EE memory')
    if type(timeout) is not int or not 1 <= timeout <= 3600: raise ValueError('Timeout must be1..3600 game updates')
    validate_hold(hold_updates)
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager, count = u(core.ACTORS), u(core.MODE+4)
    if (not 0x100000 <= manager <= len(ram)-640 or u(manager) != 2 or
            u(core.MODE) != 1 or u(core.MODE+8) != manager or
            count not in ACTOR_COUNTS or u(core.MODE+12) != count):
        raise ValueError('Install after captured4/6 fighter activation')
    if u(CONTROL+4) != manager: raise ValueError('Lock-on controls belong to another match')
    button = u(CONTROL+FIELDS['button'])
    if not 0 < button <= 0xFFFF: raise ValueError('Lock-on button must be a raw pad bit')
    if button&(button-1):raise ValueError('Choose one target-switch button')
    name = BUTTON_NAMES.get(button, hex(button))
    previous = legacy_previous(ram)
    if ram[HOOK:HOOK+8] != struct.pack('<2I', (2 << 26) | (old.CODE >> 2), 0):
        raise ValueError('Build after lockon_switch and before another actor-chain wrapper')
    if any(ram[CODE:END]): raise ValueError('Queued lock-on reservation occupied')
    F, slots = layout()
    arrays = [CONTROL+F[name] for name in ('pending', 'held', 'chorded')]
    if (any(ram[CONTROL+20:CONTROL+32]) or any(ram[CONTROL+0x50:CONTROL+0x58])
            or any(any(ram[at:at+4*slots]) for at in arrays)):
        raise ValueError('New lock-on queue fields are occupied')
    # R3 keeps the original emission byte for byte; any other button needs the
    # runtime chord mask, because the original mask 0xF2 contains L3.
    button_aware = CONFIGURABLE if hold_updates is not None else button != old.DEFAULT_BUTTON
    chords = STICK_CHORDS & ~button if button_aware else CHORD_MASK
    pieces = [(CODE, payload(previous, button_aware=button_aware), f'Tap-native,hold-release {name} switch with bounded safe-point retry'),
              (CONTROL+20, bytes(12), 'Queued,expired,cancelled counters'),
              (CONTROL+0x50, struct.pack('<2I', timeout, 0), 'Timeout and coalesced press count'),
              (arrays[0], bytes(4*slots), 'Per-fighter pending request lifetimes'),
              (arrays[1], bytes(4*slots), 'Per-fighter saturated hold-duration counters'),
              (arrays[2], bytes(4*slots), 'Per-fighter latched D-pad/stick chord flags'),
              (HOOK, struct.pack('<2I', (2 << 26) | (CODE >> 2), 0), f'Replace old {name} wrapper in the actor chain')]
    if hold_updates is not None:
        if any(ram[CONTROL+TIMING_UPDATES:CONTROL+TIMING_MAGIC+4]):
            raise ValueError('Custom lock-on timing fields occupied')
        pieces.append((CONTROL+TIMING_UPDATES,struct.pack('<2I',max(1,hold_updates),TIMING_TAG),'Configured target-switch hold duration'))
    blocks = [dict(address=p, expected_hex=ram[p:p+len(b)].hex(), data_hex=b.hex(), purpose=why) for p, b, why in pieces]
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()),
                status=f'TAP NATIVE FORM; HOLD/RELEASE {name} FOR QUEUED LOCK-ON', blocks=blocks, control=CONTROL,
                previous=previous, timeout_updates=timeout, fields=F, button=button, button_aware=button_aware,
                telemetry={field: CONTROL+F[field] for field in ('queued', 'expired', 'cancelled', 'coalesced', 'pending')},
                support={'capacity': policy.emitted_actors(), 'features': {'lockon_queued': [
                    dict(address=b['address'], data_hex=b['data_hex']) for b in blocks if b['address'] in (CODE, HOOK)]}},
                input_rule={'button': name, 'hold_updates': HOLD_UPDATES if hold_updates is None else hold_updates, 'trigger': 'release',
                            'excluded_raw_chords': 0 if hold_updates is not None else chords, 'native_raw_input_preserved': True},
                limitations=[f'Short {name} taps remain native; hold plain {name} about half a second and release to change targets.',
                             'A D-pad direction or the other stick button during the hold/release leaves that input combination entirely to the native game.',
                             'One pending switch per human; repeated blocked long holds refresh rather than accumulate cycles.',
                             'A request expires after the configured active updates; it never forces a cinematic/damage retarget.',
                             'The candidate is chosen at execution time from living opponents; an unavailable alternative consumes the request.'])


def legacy_previous(ram):
    """Continuation of the exact installed legacy lockon_switch body, or raise."""
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    length = len(old.code(0)); tail = old.CODE+length-8
    if u(tail) >> 26 != 2 or u(tail+4): raise ValueError('Expected native lock-on chain tail')
    previous = (u(tail) & 0x3FFFFFF) << 2
    expected = old.code(previous)
    if ram[old.CODE:old.CODE+len(expected)] != expected:
        raise ValueError('Existing lock-on payload differs; preserve and review its changes')
    return previous


def installed_configuration(ram, previous, free_for_all=False, coop_controls=False):
    """Recognize the complete queue, including the optional four-pad resolver."""
    import four_player_mode
    resolvers=(None,A(0x1DC2A0)) if four_player_mode.installed(ram) else (None,)
    for resolver in resolvers:
        for button_aware in (False, True, CONFIGURABLE):
            expected = payload(previous, free_for_all=free_for_all, coop_controls=coop_controls,
                               button_aware=button_aware,pad_resolver=resolver)
            if ram[CODE:CODE+len(expected)] == expected:
                if resolver is not None:four_player_mode.validate_pad(ram)
                return button_aware,resolver
            if button_aware==CONFIGURABLE:
                import lockoff_target as unlock
                if struct.unpack_from('<I',ram,unlock.CONTROL)[0]==unlock.MAGIC:
                    new=payload(previous,free_for_all=free_for_all,coop_controls=coop_controls,
                                button_aware=button_aware,pad_resolver=resolver,lockoff=True)
                    new+=bytes(max(0,len(expected)-len(new)))
                    if ram[CODE:CODE+len(new)]==new:
                        unlock.validate_memory(ram)
                        if resolver is not None:four_player_mode.validate_pad(ram)
                        return button_aware,resolver
    return None


def installed_variant(ram, previous, free_for_all=False, coop_controls=False):
    found=installed_configuration(ram,previous,free_for_all,coop_controls)
    return None if found is None else found[0]


def validate_hold(hold_updates):
    if hold_updates is not None and (type(hold_updates) is not int or not 0<=hold_updates<=MAX_HOLD_UPDATES):
        raise ValueError(f'Hold duration must be 0..{MAX_HOLD_UPDATES} game updates')


def rebind_memory(ram, button, source='<offline-memory>',hold_updates=None):
    """Point an already-installed teams state (presets8/9/10, playable exports) at another button.

    R3 states keep their original bytes, so no block is emitted when the word
    already matches and the installed emission can serve it. L3 over the original
    emission replaces the queue with the button-aware payload (guarded by the
    exact installed bytes plus a zero guard over the growth) and the CONTROL word.
    """
    if len(ram) != 0x08000000: raise ValueError('Requires128MiB captured EE memory')
    if type(button) is not int or not 0 < button <= 0xFFFF: raise ValueError('Lock-on button must be a raw pad bit')
    if button&(button-1):raise ValueError('Choose one target-switch button')
    validate_hold(hold_updates)
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager, count = u(core.ACTORS), u(core.MODE+4)
    if (not 0x100000 <= manager <= len(ram)-640 or u(manager) != 2 or
            u(core.MODE) != 1 or u(core.MODE+8) != manager or
            count not in ACTOR_COUNTS or u(core.MODE+12) != count):
        raise ValueError('Rebind an installed captured4/6 fighter match')
    if u(CONTROL) != 1 or u(CONTROL+4) != manager: raise ValueError('Lock-on controls belong to another match')
    previous = legacy_previous(ram)
    import battle_modes
    if battle_modes.validate_memory(ram, manager, count) is not None:
        raise ValueError('Rebind the base teams state; FFA/co-op variants are prepared from it')
    found = installed_configuration(ram, previous)
    if found is None: raise ValueError('Installed lock-on payload differs')
    installed,resolver=found
    current = u(CONTROL+FIELDS['button'])
    pieces = []
    if hold_updates is not None or installed == CONFIGURABLE:
        original=payload(previous,button_aware=installed,pad_resolver=resolver)
        replacement=payload(previous,button_aware=CONFIGURABLE,pad_resolver=resolver)
        if installed != CONFIGURABLE:
            if any(ram[CODE+len(original):CODE+len(replacement)]):
                raise ValueError('Expanded lock-on queue reservation occupied')
            if any(ram[CONTROL+TIMING_UPDATES:CONTROL+TIMING_MAGIC+4]):
                raise ValueError('Custom lock-on timing fields occupied')
            pieces.append((CODE,replacement+bytes(max(0,len(original)-len(replacement))),
                           'Configurable target-switch button and hold timing'))
        elif u(CONTROL+TIMING_MAGIC)!=TIMING_TAG or not 1<=u(CONTROL+TIMING_UPDATES)<=MAX_HOLD_UPDATES:
            raise ValueError('Installed target-switch timing is invalid')
        if hold_updates is not None:
            timing=struct.pack('<2I',max(1,hold_updates),TIMING_TAG)
            if ram[CONTROL+TIMING_UPDATES:CONTROL+TIMING_MAGIC+4]!=timing:
                pieces.append((CONTROL+TIMING_UPDATES,timing,'Configured target-switch hold duration'))
        installed=CONFIGURABLE
    elif not installed and button & CHORD_MASK:
        original = payload(previous,pad_resolver=resolver)
        replacement = payload(previous, button_aware=True,pad_resolver=resolver)
        if any(ram[CODE+len(original):CODE+len(replacement)]):
            raise ValueError('Expanded lock-on queue reservation occupied')
        pieces.append((CODE, replacement, 'Derive the chord mask from the configured button at runtime'))
        installed = True
    if current != button:
        pieces.append((CONTROL+FIELDS['button'], struct.pack('<I', button),
                       f'Lock-on switch button {BUTTON_NAMES.get(button, hex(button))}'))
    blocks = [dict(address=p, expected_hex=ram[p:p+len(d)].hex(), data_hex=d.hex(), purpose=why)
              for p, d, why in pieces]
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()), blocks=blocks,
                status=f'LOCK-ON SWITCH BUTTON {BUTTON_NAMES.get(button, hex(button))}', control=CONTROL,
                previous=previous, button=button, button_aware=installed)


def upgrade_memory(ram, config=None, source='<offline-memory>'):
    """Upgrade the exact already-installed edge-triggered212 queue in place.

    The current actor-chain head is retained, including a preceding start hold.
    Existing pending requests and counters survive; new partial holds start clear.
    """
    if len(ram) != 0x08000000: raise ValueError('Requires128MiB captured EE memory')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager, count = u(core.ACTORS), u(core.MODE+4)
    if (not 0x100000 <= manager <= len(ram)-640 or u(manager) != 2
            or u(core.MODE) != 1 or u(core.MODE+8) != manager or count not in ACTOR_COUNTS
            or u(core.MODE+12) != count or u(CONTROL+4) != manager):
        raise ValueError('Active captured4/6 team required')
    if u(CONTROL+FIELDS['button']) != 4: raise ValueError('Expected native R3 button4')
    length = len(old.code(0)); tail = old.CODE+length-8
    if u(tail) >> 26 != 2 or u(tail+4): raise ValueError('Expected prior lock-on tail')
    previous = (u(tail) & 0x3FFFFFF) << 2
    original = payload(previous, hold_release=False); replacement = payload(previous)
    if ram[CODE:CODE+len(original)] != original:
        raise ValueError('Installed legacy R3 queue differs')
    if any(ram[CODE+len(original):CODE+len(replacement)]):
        raise ValueError('Expanded R3 queue reservation occupied')
    F, slots = layout()
    if F is LEGACY_FIELDS:
        # Three-a-side: pending requests stay where the edge-triggered queue
        # keeps them and carry over; only the new hold/chord arrays start clear.
        if any(ram[CONTROL+F['held']:CONTROL+F['held']+4*slots]) or any(ram[CONTROL+F['chorded']:CONTROL+F['chorded']+4*slots]):
            raise ValueError('New hold/chord fields occupied')
        cleared = [(CONTROL+F['held'], bytes(4*slots), 'Start partial R3 holds clear'),
                   (CONTROL+F['chorded'], bytes(4*slots), 'Start chord history clear')]
    else:
        if any(ram[CONTROL+F['pending']:CONTROL+WIDE_END]):
            raise ValueError('New hold/chord fields occupied')
        # The current emission keeps its arrays in the twelve-slot area; a legacy
        # pending request does not carry over, it simply has to be asked for again.
        cleared = [(CONTROL+F['pending'], bytes(4*slots), 'Start pending requests clear'),
                   (CONTROL+F['held'], bytes(4*slots), 'Start partial R3 holds clear'),
                   (CONTROL+F['chorded'], bytes(4*slots), 'Start chord history clear')]
    pieces = [(CODE, replacement, 'Upgrade existing R3 queue to distinguish native taps from long-release switches')] + cleared
    blocks = [dict(address=p, expected_hex=ram[p:p+len(d)].hex(), data_hex=d.hex(), purpose=why)
              for p, d, why in pieces]
    return dict(serial=SERIAL, crc=CRC, source=str(Path(source).resolve()), blocks=blocks,
                status='UPGRADE LEGACY QUEUED R3 TO HOLD/RELEASE', control=CONTROL, previous=previous,
                input_rule={'hold_updates': HOLD_UPDATES, 'trigger': 'release', 'excluded_raw_chords': CHORD_MASK},
                limitations=['Native short taps and D-pad/L3 combinations remain unchanged.',
                             'Existing pending requests/counters and outer actor-chain wrappers are preserved.'])


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path); p.add_argument('--out', required=True, type=Path)
    p.add_argument('--timeout', type=int, default=DEFAULT_TIMEOUT); x = p.parse_args()
    result = build_memory(read_ram(x.source), source=x.source, timeout=x.timeout)
    x.out.write_text(json.dumps(result, indent=2)+'\n'); print(f'{x.out}: {len(result["blocks"])} guarded blocks')
