"""Retarget native status panels inside scoped HUD update/render passes.

New preparations use enhanced=True: single view shows the actual camera
subject and their target, including retained corpses. viewport_hud supplies
four compact panels in split-screen. The default emitter remains byte-identical
for existing three-a-side fixtures; the historical explanation below describes
that legacy policy.

Native `sub_1DC210(side)` decides whose health, ki and blast stocks the panel
shows, and it does it the simplest way there is: walk the actor manager and
return the FIRST actor whose +8 equals the side index. With one fighter per
side that is "the opponent". In a simultaneous six-fighter match the side-1
actors are 1, 3 and 5, so the panel is always actor 1 - the "enemy slot 1" the
user sees, whoever they are actually fighting.

Every value on the panel funnels through that one resolver: the forty-odd
accessors in the `sub_20B4A8..sub_20C8C8` band each begin with
`sub_1DC210(a1)` and then read the resolved actor, and the HUD publishes them
once per frame from the `side = 0, 1` loop in `sub_218D88`. So moving the
resolver moves health, ki, blast stocks and the fighter's identity together.

**But the accessor band is not HUD-exclusive**, which is the trap here. Only
the resolver's own call sites are confined to the band; the band itself is
called from outside it. `sub_20B4E0` (ki) has eight callers and only one is
the HUD - the rest are native AI condition leaves such as `sub_1B5940` and the
blast-move affordability filters `sub_209048`/`sub_209170`. `sub_20B518`
(blast stock) is the same. Hooking the resolver unconditionally would quietly
change what the native AI believes about side 1.

So the override is gated on a HUD pass counter. The two roots of the HUD -
`sub_218D88`, which publishes the per-side values, and `sub_219710`, which
walks the node tree and runs the per-node callbacks that re-resolve a few
values live - are each called from exactly one site. Those two CALL SITES are
redirected through wrappers that raise the counter around the call, so the
native functions themselves are untouched and the resolver only lies to the
HUD. Anything else asking the same question, on any other frame or from any
other system, gets the answer the game shipped with.

Side 0 - the player's own panel, bottom left - is never moved. Side 1 becomes:

* split screen: the second human's fighter, so co-op partners can see each
  other's health, stocks and ki instead of a fighter neither of them chose;
* otherwise: whoever the viewing human is locked on to, read from the mod's
  own target table at 0xD8000 (twelve physical ids; unused slots hold
  0xFFFFFFFF, and the whole table is meaningless until the combat core has
  published itself at 0xD8080).

Every unexpected condition falls through to the native walk, so the worst case
is the panel the game shipped with. The resolver replacement uses temporaries
only, takes no stack frame, makes no native call, and must not touch $a0: the
resumed native body still does `move $s1, $a0` at 0x1DC21C.
"""
from native_map import A, CRC, GPO, SERIAL
import argparse
import json
import struct
from pathlib import Path

import battle_mode_policy as modes
import fresh_team_combat as core
import fresh_team_camera as fresh
import team_participation as participation
from prototype import Assembler
from camera_snapshot import read_ram

HOOK = A(0x1DC210)
# lw $v1, -0x575c($gp) ; addiu $sp, $sp, -0x20 - both position independent, so
# the fallback can replay them and resume at the third instruction.
ORIGINAL_WORDS = ((35 << 26) | (28 << 21) | (3 << 16) | (GPO(-0x575C) & 0xFFFF), 0x27BDFFE0)
ORIGINAL = struct.pack('<2I', *ORIGINAL_WORDS)
RESUME = HOOK + 8
# The HUD's publish and render roots, and their single call sites.
UPDATE_SITE, UPDATE_ROOT = A(0x212998), A(0x218D88)
RENDER_SITE, RENDER_ROOT = A(0x2129D0), A(0x219710)
CODE, CONTROL, END = 0x07260000, 0x0726F000, 0x07270000
UPDATE_WRAP, RENDER_WRAP = CODE+0x400, CODE+0x500
WATCH_UPDATE = CODE+0x2000
LEFT_SUBJECT, LEFT_LAST = 40, 44
MAGIC = 0x48554431  # 'HUD1'
TABLE, POINTERS, MODE = core.TABLE, core.POINTERS, core.MODE
MANAGER = A(0x2FEB14)
# sub_126EC8 returns this constant; sub_12AB10 is "*(scene+36) == 1".
SCENE, SPLIT_OFF, SPLIT_VALUE = A(0x331DC8), 36, 1
ENEMY_SIDE = 1
DEFAULT_VIEWER, DEFAULT_PARTNER = modes.COOP_HUMANS
SLOTS = 12
FIELDS = dict(magic=0, enabled=4, manager=8, partner=12, viewer=16,
              resolved=20, subject=24, active=28, last=32, snaps=36)
CONTROL_WORDS = 12
# The HUD widget object. sub_21F700 publishes the live health at +48+4*side and
# sub_21CD20 keeps the red damage trail at +40+4*side, snapping the trail up
# instantly but draining it down at only 100..200 units a frame. A subject
# change to a weaker fighter would therefore slide for seconds instead of
# showing the new fighter, so the trail is snapped whenever the subject moves.
HUD_OBJECT = A(0x2FEB48)
HUD_LIVE, HUD_TRAIL = 48, 40


def jal(target):
    return (3 << 26) | (target >> 2)


def jump(target):
    return (2 << 26) | (target >> 2)


def watched_resolver_code(legacy=False,quad_support=False):
    """Resolve both native panels from the actual camera owners, including KO.

    Single view shows the watched fighter and their target. The native split
    HUD has two records total, so those remain the two viewport subjects.
    Only the HUD scopes lie; AI accessors still use the untouched native walk.
    """
    a=Assembler(CODE)
    a.li(8,CONTROL); a.lw(9,8); a.li(10,MAGIC); a.branch(5,9,10,'native')
    for field in ('enabled','active'):
        a.lw(9,8,FIELDS[field]); a.branch(4,9,0,'native')
    a.i(11,10,4,2); a.branch(4,10,0,'native')
    a.li(9,MANAGER); a.lw(9,9); a.branch(4,9,0,'native')
    a.lw(10,8,FIELDS['manager']); a.branch(5,9,10,'native')
    a.li(10,MODE); a.lw(11,10); a.addiu(12,0,1); a.branch(5,11,12,'native')
    a.lw(11,10,8); a.branch(5,9,11,'native')
    a.lw(9,10,4); a.i(11,11,9,SLOTS+1); a.branch(4,11,0,'native')
    a.i(11,11,9,2); a.branch(5,11,0,'native')
    if not legacy:
        if quad_support:
            import multiplayer_fusion as multi
            # Leaf resolver: inspect the validated two-seat receipt without
            # calling helpers or disturbing the original accessor ABI.
            a.li(10,multi.CONTROL);a.lw(11,10);a.li(13,multi.MAGIC);a.branch(5,11,13,'legacy_fused')
            a.lw(11,10,4);a.lw(13,8,FIELDS['manager']);a.branch(5,11,13,'legacy_fused')
            a.li(10,multi.seats.views.CONTROL);a.lw(11,10,multi.seats.views.VIEW_COUNT)
            a.addiu(13,0,2);a.branch(5,11,13,'legacy_fused')
            a.li(10,multi.seats.views.SUBJECTS);a.lw(12,10);a.lw(11,10,4);a.branch(5,11,12,'legacy_fused')
            a.r(0x2B,11,12,9);a.branch(4,11,0,'legacy_fused')
            a.r(0,10,0,12,6);a.li(11,multi.ROWS);a.r(0x21,10,10,11);a.lw(11,10)
            a.addiu(13,0,3);a.branch(5,11,13,'legacy_fused')
            a.move(15,0);a.jump('owner_done');a.label('legacy_fused')
        # Split mode remains set while the co-op camera renders one fused body.
        # Resolve that body's actual opponent instead of the second human seat.
        a.li(10,modes.CONTROL);a.lw(11,10);a.li(13,modes.MAGIC);a.branch(5,11,13,'unfused')
        a.lw(11,10,4);a.lw(13,8,FIELDS['manager']);a.branch(5,11,13,'unfused')
        a.lw(11,10,8);a.branch(5,11,9,'unfused')
        a.lw(11,10,12);a.addiu(13,0,modes.COOP);a.branch(5,11,13,'unfused')
        a.lw(12,10,24);a.r(0x2B,11,12,9);a.branch(4,11,0,'unfused')
        a.move(15,0);a.jump('owner_done');a.label('unfused')
    # t7 marks a split HUD; t6 is the camera side to resolve.
    a.li(10,SCENE); a.lw(10,10,SPLIT_OFF); a.addiu(11,0,SPLIT_VALUE)
    a.move(15,0); a.branch(5,10,11,'single')
    a.addiu(15,0,1); a.move(14,4); a.jump('side')
    a.label('single'); a.li(10,fresh.LEADER_CONTROL); a.lw(14,10,12)
    a.i(11,11,14,2); a.branch(5,11,0,'side'); a.move(14,0)
    a.label('side')
    a.lw(12,8,FIELDS['viewer']); a.branch(4,15,0,'owner')
    a.branch(4,4,0,'owner'); a.lw(12,8,FIELDS['partner'])
    a.label('owner'); a.li(10,fresh.SUCCESSOR_CONTROL); a.lw(11,10)
    a.addiu(13,0,1); a.branch(5,11,13,'owner_done')
    a.lw(11,10,4); a.lw(13,8,FIELDS['manager']); a.branch(5,11,13,'owner_done')
    a.r(0,11,0,14,2); a.r(0x2D,10,10,11); a.lw(12,10,8)
    a.label('owner_done'); a.r(0x2B,11,12,9); a.branch(4,11,0,'native')
    a.branch(5,15,0,'resolve'); a.branch(4,4,0,'resolve')
    a.li(10,TABLE); a.r(0,11,0,12,2); a.r(0x2D,10,10,11)
    a.lw(11,10); a.branch(4,11,12,'native'); a.move(12,11)
    a.label('resolve'); a.r(0x2B,11,12,9); a.branch(4,11,0,'native')
    # Absences and fusion-consumed actors are never HUD subjects. Dead but
    # present actors remain valid so their health correctly reads zero.
    a.li(10,participation.CONTROL); a.lw(11,10); a.branch(4,11,0,'pointer')
    a.lw(11,10,4); a.lw(13,8,FIELDS['manager']); a.branch(5,11,13,'native')
    a.lw(11,10,8); a.branch(5,11,9,'native')
    a.lw(11,10,12); a.lw(13,10,16); a.r(0x27,13,13,0); a.r(0x24,11,11,13)
    a.addiu(13,0,1); a.r(4,13,12,13); a.r(0x24,11,11,13); a.branch(4,11,0,'native')
    a.label('pointer'); a.li(10,POINTERS); a.r(0,11,0,12,2)
    a.r(0x2D,10,10,11); a.lw(2,10)
    a.i(12,11,2,3); a.branch(5,11,0,'native')
    a.li(10,0x100000); a.r(0x2B,11,2,10); a.branch(5,11,0,'native')
    a.li(10,0x8000000-0x1600); a.r(0x2B,11,10,2); a.branch(5,11,0,'native')
    a.lw(10,2); a.branch(5,10,12,'native')
    a.lw(10,8,FIELDS['resolved']); a.addiu(10,10,1); a.sw(10,8,FIELDS['resolved'])
    a.branch(4,4,0,'left'); a.sw(12,8,FIELDS['subject']); a.jr()
    a.label('left'); a.sw(12,8,LEFT_SUBJECT); a.jr()
    a.label('native')
    for word in ORIGINAL_WORDS:a.emit(word)
    a.jump(RESUME)
    data=a.finish(); assert len(data)<=UPDATE_WRAP-CODE
    return data


def resolver_code(enhanced=False,legacy=False):
    """sub_1DC210(a0 = side) -> v0 = actor. Temporaries only, no stack frame."""
    if enhanced:return watched_resolver_code(legacy)
    a = Assembler(CODE)
    a.li(8, CONTROL); a.lw(9, 8); a.li(10, MAGIC); a.branch(5, 9, 10, 'native')
    a.lw(9, 8, FIELDS['enabled']); a.branch(4, 9, 0, 'native')
    # Only lie to the HUD. The same accessors answer the native AI.
    a.lw(9, 8, FIELDS['active']); a.branch(4, 9, 0, 'native')
    # Only the top-right panel moves; the player's own panel stays native.
    a.addiu(10, 0, ENEMY_SIDE); a.branch(5, 4, 10, 'native')
    a.li(9, MANAGER); a.lw(9, 9); a.branch(4, 9, 0, 'native')
    a.lw(10, 8, FIELDS['manager']); a.branch(5, 9, 10, 'native')
    # Both tables below are the mod's, and they only mean anything once the
    # combat core has published itself; before that the target entries are the
    # 0xFFFFFFFF they were initialised with.
    a.li(10, MODE); a.lw(10, 10); a.branch(4, 10, 0, 'native')
    a.li(10, MODE); a.lw(10, 10, 8); a.branch(5, 9, 10, 'native')
    # The PUBLISHED count, not manager+0. `fresh_team_combat.gate` requires the
    # raw manager word to stay 2 and hooks sub_1DC168 to answer MODE+4
    # instead, so reading the manager here would reject every seat above 1 and
    # the panel would never move.
    a.li(9, MODE); a.lw(9, 9, 4)
    a.li(10, SCENE); a.lw(10, 10, SPLIT_OFF); a.addiu(11, 0, SPLIT_VALUE)
    a.branch(5, 10, 11, 'lockon')
    # Split: the other human. A committed co-op fusion has already consumed
    # that fighter, so there is nothing of theirs left to show.
    a.li(10, modes.CONTROL); a.lw(11, 10); a.li(12, modes.MAGIC)
    a.branch(5, 11, 12, 'partner')
    a.lw(11, 10, modes.FIELDS['fused_leader']); a.lw(12, 10, modes.FIELDS['count'])
    a.r(0x2B, 13, 11, 12); a.branch(5, 13, 0, 'native')
    a.label('partner')
    a.lw(12, 8, FIELDS['partner']); a.jump('resolve')
    a.label('lockon')
    a.lw(11, 8, FIELDS['viewer'])
    a.li(13, TABLE); a.r(0, 14, 0, 11, 2); a.r(0x2D, 13, 13, 14); a.lw(12, 13)
    # Unused slots hold 0xFFFFFFFF and are caught by the count check below.
    # This one catches the other way of being wrong: never point the enemy
    # panel at the player it belongs to.
    a.branch(4, 12, 11, 'native')
    a.label('resolve')
    a.r(0x2B, 14, 12, 9); a.branch(4, 14, 0, 'native')  # t1 = published count
    a.li(13, POINTERS); a.r(0, 14, 0, 12, 2); a.r(0x2D, 13, 13, 14); a.lw(2, 13)
    a.branch(4, 2, 0, 'native')
    a.lw(13, 8, FIELDS['resolved']); a.addiu(13, 13, 1); a.sw(13, 8, FIELDS['resolved'])
    a.sw(12, 8, FIELDS['subject'])
    a.jr()
    a.label('native')
    for word in ORIGINAL_WORDS: a.emit(word)
    a.jump(RESUME)
    data = a.finish()
    assert len(data) <= UPDATE_WRAP-CODE, 'HUD resolver exceeds its reservation'
    return data


def wrapper_code(entry, root, snap=False, limit=0x100, enhanced=False):
    """Raise the HUD pass counter around one native root, then restore it.

    The publish wrapper additionally snaps the damage trail whenever the panel
    changes fighter, so the bar shows the new fighter at once instead of
    draining toward them over several seconds.
    """
    a = Assembler(entry)
    a.addiu(29, 29, -16); a.i(63, 31, 29, 0)
    a.li(8, CONTROL); a.lw(9, 8, FIELDS['active'])
    a.addiu(9, 9, 1); a.sw(9, 8, FIELDS['active'])
    a.call(root)
    a.li(8, CONTROL); a.lw(9, 8, FIELDS['active'])
    a.addiu(9, 9, -1); a.sw(9, 8, FIELDS['active'])
    if snap:
        if enhanced:
            a.lw(9,8,LEFT_SUBJECT); a.lw(10,8,LEFT_LAST)
            a.branch(4,9,10,'right'); a.sw(9,8,LEFT_LAST)
            a.li(10,HUD_OBJECT); a.lw(10,10); a.branch(4,10,0,'right')
            a.li(11,0x100000); a.r(0x2B,12,10,11); a.branch(5,12,0,'right')
            a.i(12,12,10,3);a.branch(5,12,0,'right')
            a.li(11,0x8000000-HUD_LIVE-8);a.r(0x2B,12,11,10);a.branch(5,12,0,'right')
            a.lw(11,10,HUD_LIVE); a.sw(11,10,HUD_TRAIL)
            a.label('right')
        a.lw(9, 8, FIELDS['subject']); a.lw(10, 8, FIELDS['last'])
        a.branch(4, 9, 10, 'done')
        a.sw(9, 8, FIELDS['last'])
        a.li(10, HUD_OBJECT); a.lw(10, 10); a.branch(4, 10, 0, 'done')
        a.li(11, 0x100000); a.r(0x2B, 12, 10, 11); a.branch(5, 12, 0, 'done')
        if enhanced:
            a.i(12,12,10,3);a.branch(5,12,0,'done')
            a.li(11,0x8000000-HUD_LIVE-8);a.r(0x2B,12,11,10);a.branch(5,12,0,'done')
        a.lw(11, 10, HUD_LIVE+4*ENEMY_SIDE); a.sw(11, 10, HUD_TRAIL+4*ENEMY_SIDE)
        a.lw(11, 8, FIELDS['snaps']); a.addiu(11, 11, 1); a.sw(11, 8, FIELDS['snaps'])
        a.label('done')
    a.i(55, 31, 29, 0); a.addiu(29, 29, 16); a.jr()
    data = a.finish()
    assert len(data) <= limit, 'HUD pass wrapper exceeds its reservation'
    return data


def pieces(enhanced=False,legacy=False):
    result=[(CODE, resolver_code(enhanced,legacy)),
            (UPDATE_WRAP, struct.pack('<2I',jump(WATCH_UPDATE),0) if enhanced else
             wrapper_code(UPDATE_WRAP, UPDATE_ROOT, snap=True)),
            (RENDER_WRAP, wrapper_code(RENDER_WRAP, RENDER_ROOT))]
    if enhanced:result.append((WATCH_UPDATE,wrapper_code(WATCH_UPDATE,UPDATE_ROOT,snap=True,limit=0x200,enhanced=True)))
    return result


def patches():
    return [(HOOK, struct.pack('<2I', jump(CODE), 0)),
            (UPDATE_SITE, struct.pack('<I', jal(UPDATE_WRAP))),
            (RENDER_SITE, struct.pack('<I', jal(RENDER_WRAP)))]


def expected_patches():
    return [(HOOK, ORIGINAL),
            (UPDATE_SITE, struct.pack('<I', jal(UPDATE_ROOT))),
            (RENDER_SITE, struct.pack('<I', jal(RENDER_ROOT)))]


def control_words(manager, partner=DEFAULT_PARTNER, viewer=DEFAULT_VIEWER):
    block = bytearray(4*CONTROL_WORDS)
    struct.pack_into('<5I', block, 0, MAGIC, 1, manager, partner, viewer)
    return bytes(block)


def installed(ram, enhanced=None):
    """True when this exact program is already resident and armed."""
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    if u(CONTROL) != MAGIC or u(CONTROL+FIELDS['enabled']) != 1: return False
    variants=(False,True) if enhanced is None else (enhanced,)
    import four_player_mode
    return any(all(ram[p:p+len(actual)] == actual for p,d in pieces(v)+patches()
                   for actual in (four_player_mode.dependency_override(ram,p,d),)) for v in variants)


def build_memory(ram, partner=DEFAULT_PARTNER, viewer=DEFAULT_VIEWER,
                 source='<prepared-match>', enhanced=False):
    if len(ram) != 0x8000000: raise ValueError('Requires 128 MiB captured EE RAM')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    manager = u(MANAGER)
    if not 0x100000 <= manager <= len(ram)-16:
        raise ValueError('HUD subject requires the captured native actor manager')
    # The raw manager word stays 2 for the whole match; the roster the mod
    # actually fields is the published count, which is what the runtime reads.
    if u(MODE) != 1 or u(MODE+8) != manager:
        raise ValueError('HUD subject requires the published combat core')
    count = u(MODE+4)
    if not 2 <= count <= SLOTS or count != u(MODE+12):
        raise ValueError('HUD subject requires a captured actor roster')
    if not 0 <= viewer < count:
        raise ValueError('HUD subject viewer outside the captured roster')
    # A smaller roster than the co-op partner seat is ordinary - a padded two
    # contestant capture has no second human - and the program's own
    # "index < count" check hands those frames back to the native walk. Only a
    # seat that could never be a fighter is a builder error.
    if not 0 <= partner < SLOTS:
        raise ValueError('HUD subject partner seat outside the actor table')
    if partner == viewer:
        raise ValueError('HUD subject needs two distinct human seats')
    for index in range(count):
        actor = u(POINTERS+4*index)
        if not 0x100000 <= actor <= len(ram)-0x1600 or u(actor) != index:
            raise ValueError('Native actor identity changed')
    if installed(ram,enhanced) or (not enhanced and installed(ram)):
        if u(CONTROL+FIELDS['manager'])!=manager:
            raise ValueError('HUD subject belongs to another actor manager')
        p=CONTROL+FIELDS['partner'];data=struct.pack('<2I',partner,viewer)
        changes=[] if ram[p:p+8]==data else [dict(address=p,expected_hex=ram[p:p+8].hex(),data_hex=data.hex())]
        return dict(serial=SERIAL, crc=CRC, source=str(source), blocks=changes)
    old_enhanced=(enhanced and all(ram[p:p+len(d)]==d for p,d in pieces(True,legacy=True)+patches()))
    upgrading=enhanced and (installed(ram,False) or old_enhanced)
    if upgrading:
        if u(CONTROL+FIELDS['manager'])!=manager:
            raise ValueError('HUD subject belongs to another actor manager')
        # Compare every formerly unowned byte, not merely the entry point.
        occupied=bytearray(ram[CODE:END])
        for p,d in pieces(True,legacy=True) if old_enhanced else pieces(False):
            occupied[p-CODE:p-CODE+len(d)]=bytes(len(d))
        for p,d in [(CONTROL,bytes(4*CONTROL_WORDS))]:
            occupied[p-CODE:p-CODE+len(d)]=bytes(len(d))
        if any(occupied):raise ValueError('HUD subject extension reservation occupied')
    else:
        for address, expected in expected_patches():
            if ram[address:address+len(expected)] != expected:
                raise ValueError(f'Native HUD path changed:{address:08X}')
        if any(ram[CODE:END]):raise ValueError('HUD subject reservation occupied')
    control=bytearray(control_words(manager,partner,viewer))
    if enhanced:
        for off in (FIELDS['subject'],FIELDS['last'],LEFT_SUBJECT,LEFT_LAST):
            struct.pack_into('<I',control,off,0xFFFFFFFF)
    blocks = pieces(enhanced)+[(CONTROL, bytes(control))]+patches()
    return dict(serial=SERIAL, crc=CRC, source=str(source),
                status=('HUD FOLLOWS CAMERA SUBJECT AND TARGET; SPLIT SHOWS BOTH CAMERA SUBJECTS' if enhanced else
                        'TOP-RIGHT PANEL FOLLOWS THE LOCK-ON TARGET; SPLIT SHOWS PLAYER 2'),
                partner=partner, viewer=viewer,
                blocks=[dict(address=p, expected_hex=ram[p:p+len(d)].hex(),
                             data_hex=bytes(d).hex()) for p, d in blocks])


def validate_memory(ram):
    """Report the installed subject policy, or None when the HUD is native."""
    if all(ram[p:p+len(d)] == d for p, d in expected_patches()): return None
    if not installed(ram):
        raise ValueError(f'Unrecognized HUD subject installation:{HOOK:08X}')
    u = lambda p: struct.unpack_from('<I', ram, p)[0]
    if u(CONTROL+FIELDS['manager'])!=u(MANAGER):
        raise ValueError('HUD subject belongs to another actor manager')
    return dict(manager=u(CONTROL+FIELDS['manager']), partner=u(CONTROL+FIELDS['partner']),
                viewer=u(CONTROL+FIELDS['viewer']), resolved=u(CONTROL+FIELDS['resolved']),
                subject=u(CONTROL+FIELDS['subject']))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ram', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--partner', type=int, default=DEFAULT_PARTNER)
    p.add_argument('--viewer', type=int, default=DEFAULT_VIEWER)
    x = p.parse_args()
    manifest = build_memory(read_ram(x.ram), partner=x.partner, viewer=x.viewer, source=x.ram)
    x.out.write_text(json.dumps(manifest, indent=2)+'\n')
    print(x.out)
