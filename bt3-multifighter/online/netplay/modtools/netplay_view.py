"""Per-window views for lockstep online play: each window shows its own player's camera, full screen, while every copy
of the game stays bit-identical (Stage A proof of concept, stock PCSX2 2.8.2, BT3 USA; not shipped).

Lockstep needs one simulation on every machine, so the camera MATH must not differ: every copy runs the native
single view (scene+36 = 0, both side cameras on the full-screen template 0, the lock-on framing width W = 512 in
1C5C80 on both) and computes both side cameras every update (12B6E0). Only the DISPLAYED camera differs, and only
inside the render call. The one per-machine input is netplay_core CONTROL.local_slot (written by each session while
the emulator is paused on the loaded state); here only SWAP (the render) reads it (netplay_core's own self feed
already used it to commit this machine's captured pad, which is input, not view).

PROGRAMS (reservation CONTROL..END = 0x07B01100..0x07B02000, inside netplay_core's own reservation, which it leaves
free between its CONTROL block and its hash TABLE)
  SEL   logic, identical on every copy. The camera selection A(0x23EFF0) `j 0x07110000` (cinematic_policy's selector
        chain) -> `j SEL`. SEL runs the chain unchanged (its v0/v1 are kept), then, in single view, records the
        selected camera (canonical = gp-22176), view0/view1 = cinematic_policy.VIEW(side) evaluated with the
        split-screen victim rule (scene+36 reads 1 for exactly those two calls, then 0 again), shared = cinematic_policy
        CONTROL+60, current = manager+3136 (the mod's shared presentations - a checked ultimate's owner, a co-op fusion
        pair - bind the cinematic there too; the native selection only ever puts a side camera there), and a VU0 R
        snapshot (the effects random generator; a probe, never used). Never reads local_slot.
  SWAP  render only. The battle loop's single-view render call A(0x12BCD8) `jal 12B7F8` -> `jal SWAP` (12B7F8 has
        no other caller). Local side s = local_slot while netplay_core runs a lockstep session (mode LOCKSTEP, state
        RUNNING) and local_slot < 2, else 0 (after the decision every window plays on alone).
        While the fight is live (director gp-22328 state 3, no result word A(0x333700) & 0x1F) it picks
          the cinematic camera when the canonical selection is that cinematic and either s = 0 (the native single
          view is side 0's own view) or it is one shared presentation (bound as manager+3136 by the mod's shared
          paths, cinematic_policy SHARED_STOP, or no side takes part); else the cinematic when side s takes part
          (view_s); else side camera s = manager(gp-22172)+1824+656*s,
        binds a different target for this render only (manager+3136, 23E6A0, the visibility caches 24AD08/24ADF8),
        shows fresh_team_camera LEADER_CONTROL+12 = s to the render (overhead bars, the lock-on arrow), renders
        (12B7F8) and re-binds the canonical camera (manager+3136, 23E6A0) and LEADER_CONTROL+12, so the next update's
        logic sees exactly what every other copy sees. Around every single-view render (both copies, every frame) the
        newlib rand() state (_impure_ptr+168, 8 bytes) is restored, so no render-time rand() consumer (weather
        particles 148A38, screen distortion 246B20, HUD shake and banners 21CD20/21D000/2230F8/227468/227EA8) can make
        the game's random stream depend on the window; the three MT indexes and VU0 R are checked (tripwire counters).
        While it renders the live fight it also lends side s to VIEWER (CONTROL.lent = s, back to 0 right after).
  VIEWER render only. The effects' 'is this fighter the viewed one' test sub_12CF60 -> sub_207FB0 breaks a tie of
        the two sides' camera requests (207E78, the usual case outside cinematics) with fighter side == sub_23EE08(),
        the native viewed side: 0 in single view on EVERY copy, so window B drew player 1's viewer-only effects (the
        Spirit Bomb glow over Goku, white radial speed lines around the bomb and the Kamehameha) and dropped player
        2's own (Masenko's and Gekiretsu Madan's speed lines and streaks, the charge flash in front of Gohan). The
        draw callbacks that ask (vtable slot 5, drawn by 1AD3B0 inside 12B7F8: 15FF38 160330 164B40 168258 171078
        17CB60 17E088 186950 191348 1967E0 19DD38) are render-only, and 207FB0 is the only render-phase caller of
        23EE08. A(0x20805C) `jal 23EE08` (207FB0's tie-break) -> `jal VIEWER`: VIEWER returns CONTROL.lent while
        SWAP lends a side (window B: 1, exactly what 23EE08 answers in the native single view of side 1) and else
        tail-jumps to 23EE08, so window A, every logic-time call, the intro, the end and split view stay native.
  BURST render, identical on every copy. The light-burst pool (gp-22124, 10 slots) is allocated in logic (20 VU0
        random draws per slot) but 2454E0 released a slot at its first render projection when it was off screen,
        so in single view the pool depended on the displayed camera. A(0x2455A8) `jal 244D70` -> `jal BURST` and
        A(0x2455B0) `b 245640` -> `beql v0, zero, 245640`: BURST hides such a burst (alpha +32 and its fade +36 := 0,
        drawn invisible, released by its own render-count timer in 244E20 like every other burst) and returns 1 so
        2454E0 goes on; with views off it releases exactly as before and returns 0.
SHARED LOGIC CHANGES (identical on every copy; they make two humans work in single view)
  * hud_subject's resolver and the spectator/takeover payload read the split flag through `lui/ori SCENE`; those two
    immediates are redirected to CONTROL.views - 36, so with views on both use their split-screen rule: HUD panel 0
    = side 0's camera subject, panel 1 = side 1's (player 1 left, player 2 right), and port p <-> view side p (player
    2 can watch and take over a teammate after a KO). The HUD publish never depends on the window (a per-window
    publish desynced: 218D88 -> 22AB50 -> random(2) on MT#3). (A 'Choose your teams' 2-player match retires that
    two-seat spectator payload for quad_lifecycle's four seats, which never read the split flag: seat s keeps its
    own subject and takeover in either view; the redirect then sits in dead code.)
  * lockoff_target CAMERA (lock-on picks, the KO retarget, right-stick aims; logic) and lockon_select's arrow seat
    lookup (render) used quad_viewports' CAMERAS, which only its split renderer writes (stale in single view).
    Their first two words jump to gates that take each one's own single-view path (the successor side cameras /
    display_settings.SUBJECT of the bound camera) while views are on in single view.
  * lockoff's target-panel policy := 2 (show): its single-view filter hid panel 1 when player 1 unlocked, and panel
    1 is player 2's own panel here.
LAYOUT 4 (TTM Online Kit 2.1: any fighter can be a player; netplay_core OPT_SEATS)
  CAMS  logic, identical on every copy. After the selection SEL calls CAMS_CODE: while the fight is on screen (director
        2 or 3, no result word) every seated slot s >= 2 whose fighter is alive and is NOT its side's camera subject
        (fresh_team_camera SUCCESSOR_CONTROL +8 / +12) gets a camera of its own, CAMS[s - 2] (1 KiB each): SUBJ builds
        it exactly as quad_viewports' PREPARE builds a quarter view (the full-screen template manager+0, the subject's
        model framing 207DD0 / 207E78, the cinematic it takes part in through cinematic_policy VIEW with a temporary
        side-0 subject, else the follow camera 23EAD0), only full screen. CAM_LOGIC +0 records which slots have one
        (hashed). The bound camera and manager+3136 are put back when anything moved them.
  SWAP  a window whose netplay_core local slot is s >= 2 shows CAMS[s - 2] while that slot has one (a cinematic the
        canonical selection shows to everybody - manager+3136 or the shared-stop policy - is still shared), else its
        fighter's side camera (side = physical & 1: a dead fighter's window follows its team, the side camera's
        successor rule). While it renders its own camera it publishes CONTROL.subject (the fighter) and lends its
        side to VIEWER, so the lock-on arrow is drawn over THIS fighter's target and its viewer-only effects show.
  CAMERA (lockoff_target's PICK, logic) returns CAMS[s - 2] for a seated fighter that has one: lock-on picks and
        right-stick aims follow the player's own camera on every PC. MARKER (lockon_select, render) takes its seat from
        CONTROL.subject while SWAP renders a fighter's own camera.
HASH (netplay_core extra_rows=hash_rows(), class 7 'canary'): the SEL record and VU0 R snapshot, the light-burst
pool counts and the HUD panel subjects, so a view leak into any of them reads as a desync. CONTROL from 'side' on
(SWAP's and VIEWER's per-machine words: lent, viewer_calls) is never hashed.

Guest rules: 16-byte stack frames, no k0/k1, native addresses through A(); the European disc fails closed.
"""
import struct

from native_map import A, CRC, SERIAL
from prototype import Assembler
import netplay_core as nc

CONTROL = nc.CONTROL + 0x100
SEL, SWAP, BURST, VIEWER = CONTROL + 0x100, CONTROL + 0x300, CONTROL + 0xA00, CONTROL + 0xB00
END = nc.TABLE
# layout 4: the per-fighter cameras and their programs (netplay_core VIEW_AREA)
CAMS, CAM_LOGIC = nc.VIEW_AREA, nc.VIEW_AREA + 0x2000
SUBJ_CODE, CAMS_CODE = nc.VIEW_AREA + 0x2100, nc.VIEW_AREA + 0x2800
CAMERA_GATE, MARKER_GATE = nc.VIEW_AREA + 0x2C00, nc.VIEW_AREA + 0x2D00
CAM_BYTES = 1024
MAGIC = 0x4E505631                       # 'NPV1'
LAYOUT = 4                               # 2: + `current` (manager+3136); 3: + VIEWER; 4: per-fighter cameras
FIELDS = (('magic', 0x00), ('views', 0x04), ('layout', 0x08), ('patched', 0x0C),
          # logic record (identical on every copy; hashed)
          ('canonical', 0x10), ('view0', 0x14), ('view1', 0x18), ('shared', 0x1C), ('vu0_r', 0x20),
          ('selections', 0x24), ('current', 0x28),
          # this machine's render (never hashed)
          ('side', 0x40), ('renders', 0x44), ('swaps_side', 0x48), ('swaps_cine', 0x4C), ('kept', 0x50),
          ('not_live', 0x54), ('rand_restored', 0x58), ('mt_trips', 0x5C), ('vu0_trips', 0x60), ('last', 0x64),
          ('hidden', 0x68), ('lent', 0x6C), ('viewer_calls', 0x70),
          # kit 2.0: the side this window shows (0/1; per machine, render only, never hashed). NO_WATCH (any other
          # value): the netplay_core local slot decides, as before. A spectator's kit sets it (and changes it live).
          ('watch', 0x74),
          # kit 2.1: the fighter whose own camera SWAP is rendering (render only; NO_WATCH otherwise)
          ('subject', 0x78))
NO_WATCH = 0xFFFFFFFF
F = dict(FIELDS)
CONTROL_BYTES = 0x80
LOGIC_WORDS = 7                          # canonical .. current
REDIRECT = CONTROL + F['views'] - 36     # 'scene' for the redirected split reads: +36 is CONTROL.views
PATCH_BITS = dict(hud=1, spectator=2, camera=4, marker=8, policy=16, viewer=32)
SCENE_SPLIT = 36
SIDE_CAMERA, SIDE_STRIDE = 1824, 656
GP_CANONICAL, GP_CINEMATIC, GP_MANAGER, GP_DIRECTOR = -22176, -22180, -22172, -22328
MT_INDEXES = (-21008, -22048, -21528)   # MT19937 #3, #1, #2 index words
assert SWAP - SEL >= 0x200 and VIEWER - BURST >= 0x100 and END - VIEWER >= 0x100 and CONTROL + CONTROL_BYTES <= SEL
assert CAMS + 8 * CAM_BYTES <= CAM_LOGIC and MARKER_GATE + 0x100 <= nc.VIEW_AREA_END
assert nc.CONTROL + nc.CONTROL_BYTES <= CONTROL


def natives():
    """Native addresses of the selected disc (NativeMapError under an adapter that has not reviewed them)."""
    from types import SimpleNamespace
    return SimpleNamespace(
        select_site=A(0x23EFF0), render_site=A(0x12BCD8), render=A(0x12B7F8), bind=A(0x23E6A0),
        vis_view=A(0x24AD08), vis_pair=A(0x24ADF8), scene=A(0x331DC8), result=A(0x333700), impure=A(0x2E9808),
        burst_call=A(0x2455A8), burst_branch=A(0x2455B0), release=A(0x244D70), burst_pool=A(0x2FEC04),
        viewer_site=A(0x20805C), viewed=A(0x23EE08))


def jal(target):
    return 0x0C000000 | (target >> 2)


def j(target):
    return 0x08000000 | (target >> 2)


def _sd(a, r, off): a.i(63, r, 29, off)
def _ld(a, r, off): a.i(55, r, 29, off)
def _cfc2_r(a, rt): a.emit((18 << 26) | (2 << 21) | (rt << 16) | (20 << 11) | 1)   # cfc2.i rt, vi20 (VU0 R)


def _bump(a, base, field, scratch=8):
    assert scratch != base
    a.lw(scratch, base, F[field]); a.addiu(scratch, scratch, 1); a.sw(scratch, base, F[field])


def _gate(a, fail, control=8, scratch=9, scratch2=10):
    """Fall to `fail` unless this module is installed, views are on and the scene is in single view."""
    a.li(control, CONTROL); a.lw(scratch, control, F['magic']); a.li(scratch2, MAGIC); a.branch(5, scratch, scratch2, fail)
    a.lw(scratch, control, F['views']); a.branch(4, scratch, 0, fail)
    a.li(scratch2, natives().scene); a.lw(scratch, scratch2, SCENE_SPLIT); a.branch(5, scratch, 0, fail)


# ---- SEL: logic, after the selector chain ----------------------------------------------------------------------------
SEL_FRAME = 0x30


def sel_code(chain):
    import cinematic_policy as cinema
    n = natives()
    a = Assembler(SEL)
    a.addiu(29, 29, -SEL_FRAME)
    for i, r in enumerate((16, 17, 31)):
        _sd(a, r, 8 * i)
    a.call(chain)
    _sd(a, 2, 0x18); _sd(a, 3, 0x20)                              # the chain's result, returned unchanged
    a.li(16, CONTROL); a.lw(8, 16, F['magic']); a.li(9, MAGIC); a.branch(5, 8, 9, 'return')
    a.lw(8, 16, F['views']); a.branch(4, 8, 0, 'return')
    a.li(17, n.scene); a.lw(8, 17, SCENE_SPLIT); a.branch(5, 8, 0, 'return')
    a.lw(8, 28, GP_CANONICAL); a.sw(8, 16, F['canonical'])
    a.addiu(8, 0, 1); a.sw(8, 17, SCENE_SPLIT)                     # the split-screen victim rule, these two calls only
    a.move(4, 0); a.call(cinema.VIEW); a.sw(2, 16, F['view0'])
    a.addiu(4, 0, 1); a.call(cinema.VIEW); a.sw(2, 16, F['view1'])
    a.sw(0, 17, SCENE_SPLIT)
    a.li(8, cinema.CONTROL); a.lw(9, 8); a.li(10, cinema.MAGIC); a.move(11, 0); a.branch(5, 9, 10, 'no_policy')
    a.lw(11, 8, cinema.SHARED_STOP)
    a.label('no_policy'); a.sw(11, 16, F['shared'])
    a.lw(8, 28, GP_MANAGER); a.move(9, 0); nc._valid(a, 8, 'no_manager'); a.lw(9, 8, 3136)
    a.label('no_manager'); a.sw(9, 16, F['current'])
    _cfc2_r(a, 8); a.sw(8, 16, F['vu0_r'])
    _bump(a, 16, 'selections')
    a.call(CAMS_CODE)                                             # layout 4: the per-fighter cameras
    a.label('return')
    _ld(a, 2, 0x18); _ld(a, 3, 0x20)
    for i, r in enumerate((16, 17, 31)):
        _ld(a, r, 8 * i)
    a.addiu(29, 29, SEL_FRAME)
    a.jr()
    code = a.finish()
    assert SEL + len(code) <= SWAP, hex(len(code))
    return code


# ---- SWAP: the single-view render call --------------------------------------------------------------------------------
SWAP_SAVED = (16, 17, 18, 19, 20, 21, 22, 23, 31)
SWAP_FRAME = 0x80
RAND_LO, RAND_HI, MT0, VU0, MGR3136 = 0x50, 0x54, 0x58, 0x64, 0x68     # MT0..MT0+8: the three MT indexes
OWN_CAM, OWN_SUBJECT = 0x70, 0x74                                       # layout 4: this window's own camera
assert len(SWAP_SAVED) * 8 <= RAND_LO and OWN_SUBJECT + 4 <= SWAP_FRAME and SWAP_FRAME % 16 == 0


def swap_code():
    import fresh_team_camera as follow
    n = natives()
    a = Assembler(SWAP)
    a.addiu(29, 29, -SWAP_FRAME)
    for i, r in enumerate(SWAP_SAVED):
        _sd(a, r, 8 * i)
    _gate(a, 'native')
    a.li(16, CONTROL)
    # Bracket (every copy, every single-view frame): rand() state, MT indexes and VU0 R before the render.
    a.li(8, n.impure); a.lw(23, 8); nc._valid(a, 23, 'no_impure')
    a.lw(9, 23, 168); a.sw(9, 29, RAND_LO); a.lw(9, 23, 172); a.sw(9, 29, RAND_HI); a.jump('impure_ready')
    a.label('no_impure'); a.move(23, 0)
    a.label('impure_ready')
    for i, off in enumerate(MT_INDEXES):
        a.lw(9, 28, off); a.sw(9, 29, MT0 + 4 * i)
    _cfc2_r(a, 9); a.sw(9, 29, VU0)
    _bump(a, 16, 'renders')
    # s6 = the local side: netplay_core's per-machine local_slot, while it runs a lockstep session (after the
    # fight is decided, or a session aborted, every window plays on alone with its own pad on port 0: side 0).
    a.move(22, 0)
    a.sw(0, 29, OWN_CAM); a.addiu(8, 0, -1); a.sw(8, 29, OWN_SUBJECT)
    a.li(8, nc.CONTROL); a.lw(9, 8, nc.F['magic']); a.li(10, nc.MAGIC); a.branch(5, 9, 10, 'side_ready')
    a.lw(9, 8, nc.F['mode']); a.addiu(10, 0, nc.LOCKSTEP); a.branch(5, 9, 10, 'side_ready')
    a.lw(9, 8, nc.F['state']); a.addiu(10, 0, nc.RUNNING); a.branch(5, 9, 10, 'side_ready')
    a.lw(9, 16, F['watch']); a.i(11, 10, 9, 2); a.branch(4, 10, 0, 'by_slot')         # kit 2.0: the watched side
    a.move(22, 9); a.jump('side_ready')
    a.label('by_slot')
    a.lw(9, 8, nc.F['local_slot']); a.i(11, 10, 9, 2); a.branch(4, 10, 0, 'seated')
    a.move(22, 9); a.jump('side_ready')
    # layout 4: slot s >= 2 plays fighter SEATS[s] (side = physical & 1); its own camera while CAM_LOGIC has one
    a.label('seated')
    a.i(11, 10, 9, nc.SLOTS); a.branch(4, 10, 0, 'side_ready')
    a.li(8, nc.SEAT_CONTROL); a.lw(10, 8, nc.SF['magic']); a.li(11, nc.SEAT_MAGIC); a.branch(5, 10, 11, 'side_ready')
    a.lw(10, 8, nc.SF['enable']); a.branch(4, 10, 0, 'side_ready')
    a.r(0, 10, 0, 9, 2); a.r(0x21, 10, 10, 8); a.lw(10, 10, nc.SF['seats'])
    a.i(11, 11, 10, nc.SLOTS); a.branch(4, 11, 0, 'side_ready')
    a.i(12, 22, 10, 1)                                            # s6 = the fighter's side
    a.li(8, CAM_LOGIC); a.lw(11, 8, 0); a.r(6, 11, 9, 11); a.i(12, 11, 11, 1); a.branch(4, 11, 0, 'side_ready')
    a.addiu(11, 9, -2); a.r(0, 11, 0, 11, 10); a.li(12, CAMS); a.r(0x21, 11, 11, 12)
    a.sw(11, 29, OWN_CAM); a.sw(10, 29, OWN_SUBJECT)
    a.label('side_ready'); a.sw(22, 16, F['side'])
    # Live fight only: director state 3 and no result word.
    a.lw(8, 28, GP_DIRECTOR); nc._valid(a, 8, 'not_live'); a.lw(8, 8); a.addiu(9, 0, 3); a.branch(5, 8, 9, 'not_live')
    a.li(8, n.result); a.lw(8, 8); a.i(12, 8, 8, 0x1F); a.branch(5, 8, 0, 'not_live')
    a.lw(17, 28, GP_MANAGER); nc._valid(a, 17, 'not_live')       # s1 camera manager
    a.lw(18, 28, GP_CANONICAL)                                   # s2 the camera this update selected (bound now)
    a.lw(8, 16, F['canonical']); a.branch(5, 8, 18, 'kept')      # the logic record must describe it
    a.lw(19, 28, GP_CINEMATIC)                                   # s3 cinematic camera
    a.addiu(20, 17, SIDE_CAMERA); a.branch(4, 22, 0, 'side_camera')
    a.addiu(20, 20, SIDE_STRIDE)                                 # s4 = side camera s (default target)
    a.label('side_camera')
    # layout 4: this window's own fighter camera (it already holds the cinematic its fighter takes part in); a
    # cinematic the canonical selection shows to everybody (manager+3136, the shared-stop policy) stays shared.
    a.lw(8, 29, OWN_CAM); a.branch(4, 8, 0, 'side_path')
    a.move(20, 8)
    a.branch(4, 19, 0, 'target_ready')
    a.branch(5, 18, 19, 'target_ready')
    a.lw(8, 16, F['current']); a.branch(4, 8, 19, 'cinematic')
    a.lw(8, 16, F['shared']); a.branch(5, 8, 0, 'cinematic')
    a.jump('target_ready')
    a.label('side_path')
    a.branch(4, 19, 0, 'target_ready')
    a.branch(5, 18, 19, 'own_view')
    # The selection bound the cinematic. Side 0 keeps it: the native single view is side 0's own view. Side 1 shares
    # it when it is one presentation for everybody: the mod's shared paths (a checked ultimate's owner, a co-op
    # fusion pair) also bind it as manager+3136, or the policy stops the bystanders, or no side takes part.
    a.branch(4, 22, 0, 'cinematic')
    a.lw(8, 16, F['current']); a.branch(4, 8, 19, 'cinematic')
    a.lw(8, 16, F['shared']); a.branch(5, 8, 0, 'cinematic')     # one shared presentation for everybody
    a.lw(8, 16, F['view0']); a.lw(9, 16, F['view1']); a.r(0x25, 8, 8, 9)
    a.branch(4, 8, 0, 'cinematic')                               # shown for no participant: shared as well
    a.label('own_view')
    a.r(0, 8, 0, 22, 2); a.r(0x21, 8, 8, 16); a.lw(8, 8, F['view0'])          # view_s
    a.branch(4, 8, 0, 'target_ready')
    a.label('cinematic'); a.move(20, 19)
    a.label('target_ready')
    a.li(8, follow.LEADER_CONTROL); a.lw(21, 8, 12); a.sw(22, 8, 12)          # s5: the viewed side, for this render
    a.sw(22, 16, F['lent'])                                      # and for 207FB0's viewed-fighter tie-break (VIEWER)
    a.lw(8, 29, OWN_SUBJECT); a.sw(8, 16, F['subject'])          # layout 4: the lock-on arrow's seat (MARKER)
    a.branch(4, 20, 18, 'render_live')
    a.sw(20, 16, F['last'])
    a.lw(8, 17, 3136); a.sw(8, 29, MGR3136)
    a.r(0x23, 8, 20, 17); a.addiu(8, 8, -SIDE_CAMERA); a.i(11, 8, 8, 2 * SIDE_STRIDE)
    a.branch(4, 8, 0, 'bind_cinematic')
    a.sw(20, 17, 3136); _bump(a, 16, 'swaps_side'); a.jump('bind')
    a.label('bind_cinematic'); _bump(a, 16, 'swaps_cine')
    a.label('bind')
    a.move(4, 20); a.addiu(5, 0, 1); a.call(n.bind)
    a.move(4, 0); a.call(n.vis_view)
    a.move(4, 0); a.call(n.vis_pair)
    a.call(n.render)
    a.lw(8, 29, MGR3136); a.sw(8, 17, 3136)
    a.move(4, 18); a.addiu(5, 0, 1); a.call(n.bind)
    a.jump('leader_back')
    a.label('render_live'); a.call(n.render)
    a.label('leader_back'); a.li(8, follow.LEADER_CONTROL); a.sw(21, 8, 12)
    a.sw(0, 16, F['lent'])                                       # logic, and every other render, ask 23EE08 again
    a.addiu(8, 0, -1); a.sw(8, 16, F['subject'])
    a.jump('bracket')
    a.label('not_live'); _bump(a, 16, 'not_live'); a.jump('plain')
    a.label('kept'); _bump(a, 16, 'kept')
    a.label('plain'); a.call(n.render)
    a.label('bracket')
    a.branch(4, 23, 0, 'rand_done')
    a.lw(8, 23, 168); a.lw(9, 29, RAND_LO); a.branch(5, 8, 9, 'rand_changed')
    a.lw(8, 23, 172); a.lw(9, 29, RAND_HI); a.branch(4, 8, 9, 'rand_done')
    a.label('rand_changed'); _bump(a, 16, 'rand_restored')
    a.lw(9, 29, RAND_LO); a.sw(9, 23, 168); a.lw(9, 29, RAND_HI); a.sw(9, 23, 172)
    a.label('rand_done')
    for i, off in enumerate(MT_INDEXES):
        a.lw(8, 28, off); a.lw(9, 29, MT0 + 4 * i); a.branch(5, 8, 9, 'mt_trip')
    a.jump('mt_done')
    a.label('mt_trip'); _bump(a, 16, 'mt_trips')
    a.label('mt_done')
    _cfc2_r(a, 8); a.lw(9, 29, VU0); a.branch(4, 8, 9, 'vu0_done'); _bump(a, 16, 'vu0_trips')
    a.label('vu0_done')
    a.move(2, 0)
    for i, r in enumerate(SWAP_SAVED):
        _ld(a, r, 8 * i)
    a.addiu(29, 29, SWAP_FRAME)
    a.jr()
    a.label('native')
    for i, r in enumerate(SWAP_SAVED):
        _ld(a, r, 8 * i)
    a.addiu(29, 29, SWAP_FRAME)
    a.jump(n.render)
    code = a.finish()
    assert SWAP + len(code) <= BURST, hex(len(code))
    return code


# ---- layout 4: per-fighter cameras (logic) -------------------------------------------------------------------------------
CAM_SAVED = tuple(range(2, 26)) + (30, 31)              # never k0/k1


def _save_all(a):
    a.addiu(29, 29, -0x160)
    for i, r in enumerate(CAM_SAVED):
        _sd(a, r, 8 * i)                                          # (f20..f31: the natives keep them, by the ABI)


def _restore_all(a, skip=()):
    for i, r in enumerate(CAM_SAVED):
        if r not in skip:
            _ld(a, r, 8 * i)
    a.addiu(29, 29, 0x160)


def _copy(a, src, dst, size, tag):
    a.addiu(10, src, size); a.label(tag)
    a.i(55, 11, src, 0); a.i(55, 12, src, 8); a.i(63, 11, dst, 0); a.i(63, 12, dst, 8)
    a.addiu(src, src, 16); a.addiu(dst, dst, 16); a.branch(5, src, 10, tag)


def subj_code():
    """SUBJ(a0 = physical, a1 = camera): quad_viewports PREPARE for one full-screen view (see the module text)."""
    import cinematic_policy as cinema
    import fresh_team_combat as core
    import fresh_team_camera as follow
    import multiplayer_fusion as fusion
    a = Assembler(SUBJ_CODE)
    _save_all(a)
    a.move(16, 4); a.move(17, 5)
    a.lw(8, 28, GP_MANAGER); a.move(9, 17); _copy(a, 8, 9, 608, 'template')
    a.sw(0, 17, 640); a.i(12, 8, 16, 1); a.sw(8, 17, 644)
    a.move(4, 17); a.call(A(0x23E040))
    a.r(0, 9, 0, 16, 2); a.li(8, core.POINTERS); a.r(0x2D, 8, 8, 9); a.lw(18, 8)
    a.lw(4, 18, 12); a.addiu(5, 17, 608); a.addiu(6, 17, 624); a.call(A(0x207DD0))
    a.lw(4, 18, 12); a.call(A(0x207E78)); a.sw(2, 17, 648)
    a.li(8, follow.SUCCESSOR_CONTROL); a.lw(19, 8, 8); a.lw(9, 18); a.sw(9, 8, 8)
    a.move(20, 0); a.li(8, fusion.CONTROL); a.lw(9, 8); a.li(10, fusion.MAGIC); a.branch(5, 9, 10, 'ordinary_cinema')
    a.lw(4, 18); a.call(fusion.CINEMATIC); a.move(20, 2); a.branch(5, 20, 0, 'cinema_ready')
    a.label('ordinary_cinema'); a.move(4, 0); a.call(cinema.VIEW); a.move(20, 2)
    a.label('cinema_ready'); a.li(8, follow.SUCCESSOR_CONTROL); a.sw(19, 8, 8)
    a.branch(4, 20, 0, 'follow')
    a.lw(20, 28, GP_CINEMATIC); a.branch(4, 20, 0, 'follow')
    a.move(8, 20); a.move(9, 17); _copy(a, 8, 9, 0x80, 'authored_view')
    a.move(4, 17); a.addiu(5, 20, 544); a.call(A(0x23E598)); a.jump('done')
    a.label('follow'); a.move(4, 17); a.move(5, 0); a.call(A(0x23EAD0))
    a.label('done')
    _restore_all(a); a.jr()
    code = a.finish()
    assert SUBJ_CODE + len(code) <= CAMS_CODE, hex(len(code))
    return code


def cams_code():
    """CAMS (logic, from SEL): CAM_LOGIC +0 := the slots that got a camera this update (see the module text);
    +4 counts the cameras built, +8 the updates that built any."""
    import fresh_team_combat as core
    import fresh_team_camera as follow
    n = natives()
    a = Assembler(CAMS_CODE)
    _save_all(a)
    a.move(21, 0)                                                 # s5 = the slots with a camera
    a.li(16, nc.SEAT_CONTROL); a.lw(8, 16, nc.SF['magic']); a.li(9, nc.SEAT_MAGIC); a.branch(5, 8, 9, 'store')
    a.lw(8, 16, nc.SF['enable']); a.branch(4, 8, 0, 'store')
    a.li(8, core.MODE); a.lw(9, 8); a.addiu(10, 0, 1); a.branch(5, 9, 10, 'store')
    a.lw(23, 8, 4)                                                # s7 = fighters
    a.lw(8, 28, GP_DIRECTOR); nc._valid(a, 8, 'store'); a.lw(8, 8); a.addiu(8, 8, -2); a.i(11, 8, 8, 2)
    a.branch(4, 8, 0, 'store')                                    # READY or FIGHT only
    a.li(8, n.result); a.lw(8, 8); a.i(12, 8, 8, 0x1F); a.branch(5, 8, 0, 'store')
    a.lw(8, 28, GP_MANAGER); nc._valid(a, 8, 'store')
    a.lw(9, 8, 3136); a.sw(9, 29, 0x140)                          # manager+3136 and the bound camera, kept
    a.lw(9, 28, GP_CANONICAL); a.sw(9, 29, 0x144)
    a.addiu(17, 0, nc.PORTS)                                      # s1 = slot
    a.label('slot')
    a.r(0, 8, 0, 17, 2); a.r(0x21, 8, 8, 16); a.lw(18, 8, nc.SF['seats'])     # s2 = the fighter
    a.r(0x2B, 8, 18, 23); a.branch(4, 8, 0, 'next')
    a.li(8, follow.SUCCESSOR_CONTROL); a.lw(9, 8, 8); a.branch(4, 9, 18, 'next')     # a side's camera subject
    a.lw(9, 8, 12); a.branch(4, 9, 18, 'next')
    a.r(0, 9, 0, 18, 2); a.li(8, core.POINTERS); a.r(0x21, 8, 8, 9); a.lw(19, 8)
    nc._valid(a, 19, 'next')
    a.lw(8, 19, 0x994); a.i(11, 9, 8, 5); a.branch(4, 9, 0, 'next')          # alive: HP row of its slot > 0
    a.r(0, 9, 0, 8, 7); a.r(0, 10, 0, 8, 5); a.r(0x21, 9, 9, 10); a.r(0, 10, 0, 8, 2); a.r(0x21, 9, 9, 10)
    a.r(0x21, 9, 9, 19); a.lw(8, 9, 0x9E4); a.branch(6, 8, 0, 'next')
    a.lw(8, 19, 12); a.i(11, 9, 8, 12); a.branch(4, 9, 0, 'next')
    a.addiu(8, 17, -nc.PORTS); a.r(0, 8, 0, 8, 10); a.li(9, CAMS); a.r(0x21, 5, 8, 9)
    a.move(4, 18); a.call(SUBJ_CODE)
    a.addiu(8, 0, 1); a.r(4, 8, 17, 8); a.r(0x25, 21, 21, 8)
    a.li(8, CAM_LOGIC); a.lw(9, 8, 4); a.addiu(9, 9, 1); a.sw(9, 8, 4)
    a.label('next')
    a.addiu(17, 17, 1); a.addiu(8, 0, nc.SLOTS); a.branch(5, 17, 8, 'slot')
    a.branch(4, 21, 0, 'store')
    a.li(8, CAM_LOGIC); a.lw(9, 8, 8); a.addiu(9, 9, 1); a.sw(9, 8, 8)
    a.lw(8, 28, GP_MANAGER); a.lw(9, 29, 0x140); a.sw(9, 8, 3136)
    a.lw(4, 29, 0x144); a.lw(9, 28, GP_CANONICAL); a.branch(4, 4, 9, 'store')
    a.addiu(5, 0, 1); a.call(n.bind)                              # a camera moved the binding: put it back
    a.label('store')
    a.li(8, CAM_LOGIC); a.sw(21, 8, 0)
    _restore_all(a); a.jr()
    code = a.finish()
    assert CAMS_CODE + len(code) <= CAMERA_GATE, hex(len(code))
    return code


# ---- gates for the two quad_viewports-camera readers ---------------------------------------------------------------
QUAD_CONTROL, QUAD_MAGIC = 0x06C0F000, 0x51564131      # quad_viewports.CONTROL / MAGIC (checked against the module)


def quad_check_words(native_branch):
    """The first six words both readers start with: li t0, quad CONTROL; lw t1,0(t0); li t2, MAGIC; bne t1,t2,X."""
    return [0x3C080000 | QUAD_CONTROL >> 16, 0x35080000 | QUAD_CONTROL & 0xFFFF, 0x8D090000,
            0x3C0A0000 | QUAD_MAGIC >> 16, 0x354A0000 | QUAD_MAGIC & 0xFFFF, native_branch]


def gate_code(base, site, single_path):
    """Own view in single view -> `single_path` (the reader's own non-quad path); else the unchanged quad path."""
    a = Assembler(base)
    _gate(a, 'quad', 8, 9, 10)
    a.jump(single_path)
    a.label('quad')
    a.li(8, QUAD_CONTROL)
    a.jump(site + 8)
    code = a.finish()
    assert len(code) <= 0x80
    return code


def camera_gate_code(site, single_path):
    """lockoff_target CAMERA (logic; a0 = physical -> v0 camera): a seated fighter with its own camera this update ->
    CAMS[s - 2]; else the single-view successor path (views on) or the quad path. Leaf: t0..t3, v0."""
    a = Assembler(CAMERA_GATE)
    _gate(a, 'quad', 8, 9, 10)
    a.li(8, nc.SEAT_CONTROL); a.lw(9, 8, nc.SF['magic']); a.li(10, nc.SEAT_MAGIC); a.branch(5, 9, 10, 'single')
    a.lw(9, 8, nc.SF['enable']); a.branch(4, 9, 0, 'single')
    a.li(10, CAM_LOGIC); a.lw(10, 10, 0); a.branch(4, 10, 0, 'single')
    a.addiu(11, 0, nc.PORTS)
    a.label('slot')
    a.r(0, 9, 0, 11, 2); a.r(0x21, 9, 9, 8); a.lw(9, 9, nc.SF['seats']); a.branch(5, 9, 4, 'next')
    a.r(6, 9, 11, 10); a.i(12, 9, 9, 1); a.branch(4, 9, 0, 'next')
    a.addiu(9, 11, -nc.PORTS); a.r(0, 9, 0, 9, 10); a.li(2, CAMS); a.r(0x21, 2, 2, 9); a.jr()
    a.label('next')
    a.addiu(11, 11, 1); a.i(11, 9, 11, nc.SLOTS); a.branch(5, 9, 0, 'slot')
    a.label('single')
    a.jump(single_path)
    a.label('quad')
    a.li(8, QUAD_CONTROL)
    a.jump(site + 8)
    code = a.finish()
    assert CAMERA_GATE + len(code) <= MARKER_GATE, hex(len(code))
    return code


def marker_gate_code(site, single_path, seat_path):
    """lockon_select MARKER's seat (render): CONTROL.subject while SWAP renders a fighter's own camera (s0 := it, on
    to the seat checks); else the single-view display subject (views on) or the quad path."""
    a = Assembler(MARKER_GATE)
    _gate(a, 'quad', 8, 9, 10)
    a.li(8, CONTROL); a.lw(9, 8, F['subject']); a.i(11, 10, 9, nc.SLOTS); a.branch(4, 10, 0, 'single')
    a.move(16, 9); a.jump(seat_path)
    a.label('single')
    a.jump(single_path)
    a.label('quad')
    a.li(8, QUAD_CONTROL)
    a.jump(site + 8)
    code = a.finish()
    assert MARKER_GATE + len(code) <= MARKER_GATE + 0x100, hex(len(code))
    return code


# ---- BURST: the light-burst pool's first-projection release ---------------------------------------------------------
def burst_code():
    n = natives()
    a = Assembler(BURST)
    a.addiu(29, 29, -0x10); _sd(a, 31, 0)
    _gate(a, 'release', 8, 9, 10)
    a.sw(0, 4, 32); a.sw(0, 4, 36)                                # alpha and fade 0: drawn invisible, timer runs
    a.i(0x31, 1, 4, 64)                                           # lwc1 $f1, 64(a0): what 2455A4 loads when kept
    _bump(a, 8, 'hidden', scratch=9)
    a.addiu(2, 0, 1); a.jump('out')
    a.label('release'); a.call(n.release); a.move(2, 0)
    a.label('out'); _ld(a, 31, 0); a.addiu(29, 29, 0x10); a.jr()
    code = a.finish()
    assert BURST + len(code) <= VIEWER
    return code


# ---- VIEWER: 207FB0's viewed-side tie-break -------------------------------------------------------------------------
def viewer_code():
    """In place of 207FB0's `jal 23EE08`: CONTROL.lent (the side SWAP lends to the live render it is running, nonzero
    only in window B) else the native 23EE08 (tail jump; its jr ra returns to 207FB0). A leaf: t0-t2 and v0 only."""
    n = natives()
    a = Assembler(VIEWER)
    a.li(8, CONTROL); a.lw(9, 8, F['magic']); a.li(10, MAGIC); a.branch(5, 9, 10, 'native')
    a.lw(2, 8, F['lent']); a.branch(4, 2, 0, 'native')
    _bump(a, 8, 'viewer_calls', scratch=9)
    a.jr()
    a.label('native')
    a.jump(n.viewed)
    code = a.finish()
    assert VIEWER + len(code) <= END
    return code


def programs(chain=None, camera=None, marker=None):
    """[(address, bytes)] of every guest program (the lints and tests read these). camera/marker: (site, single
    path) of the two quad-camera readers' gates, or None when that reader is not patched."""
    import cinematic_policy as cinema
    chain = cinema.CODE if chain is None else chain
    out = [(SEL, sel_code(chain)), (SWAP, swap_code()), (BURST, burst_code()), (VIEWER, viewer_code()),
           (SUBJ_CODE, subj_code()), (CAMS_CODE, cams_code())]
    if camera is not None:
        out.append((CAMERA_GATE, camera_gate_code(*camera)))
    if marker is not None:
        out.append((MARKER_GATE, marker_gate_code(*marker)))
    return out


# ---- builders ----------------------------------------------------------------------------------------------------------
def u32(ram, p):
    return struct.unpack_from('<I', ram, p)[0]


def words(ram, p, count):
    return list(struct.unpack_from(f'<{count}I', ram, p))


def branch_target(pc, word):
    off = word & 0xFFFF
    return pc + 4 + 4 * (off - 0x10000 if off & 0x8000 else off)


def find_pattern(ram, start, end, pattern):
    """Addresses in [start, end) where the words `pattern` appear (None = any word)."""
    out = []
    data = ram[start:end]
    count = len(data) // 4
    have = struct.unpack_from(f'<{count}I', data)
    for i in range(count - len(pattern) + 1):
        if all(w is None or have[i + k] == w for k, w in enumerate(pattern)):
            out.append(start + 4 * i)
    return out


def split_read_site(ram, start, end, base_reg, flag_reg):
    """The one `lui base,0x0033; ori base,base,0x1DC8; lw flag,36(base)` in [start, end) (the split-flag read)."""
    scene = natives().scene
    pattern = [0x3C000000 | base_reg << 16 | scene >> 16, 0x34000000 | base_reg << 21 | base_reg << 16 | scene & 0xFFFF,
               0x8C000000 | base_reg << 21 | flag_reg << 16 | SCENE_SPLIT]
    hits = find_pattern(ram, start, end, pattern)
    return hits[0] if len(hits) == 1 else None


def redirect_words(base_reg):
    return [0x3C000000 | base_reg << 16 | REDIRECT >> 16, 0x34000000 | base_reg << 21 | base_reg << 16 | REDIRECT & 0xFFFF]


def single_view_conversion(ram):
    """[(address, bytes)] turning a split-view prepared 2-player match into the native single view in place (the p25fx
    'merge' conversion, live-checked): scene+36 := 0; in each side camera's first 608 bytes every word that still
    equals its split template (side s: manager+608*(s+1)) gets template 0's word (manager+0), the live words (view
    matrix, VU matrices, +544..+559) are kept, +640 (viewport mode) := 0. This is 23EE78(0, ..)'s 23E950(cam, 0)
    without its view-matrix reset; the side cameras then frame with the full-width math from the next update on."""
    n = natives()
    if len(ram) != 0x8000000:
        raise ValueError('a 128 MiB EE image is required')
    if u32(ram, n.scene + SCENE_SPLIT) != 1:
        raise ValueError('the source is not in split view')
    manager = u32(ram, A(0x2FEBD4))                          # gp-22172, the camera manager
    if not 0x100000 <= manager < 0x7F00000:
        raise ValueError('no camera manager')
    out = [(n.scene + SCENE_SPLIT, struct.pack('<I', 0))]
    full = bytes(ram[manager:manager + 608])
    for side in range(2):
        cam = manager + SIDE_CAMERA + SIDE_STRIDE * side
        if u32(ram, cam + 640) != 1 or u32(ram, cam + 644) != side:
            raise ValueError(f'side camera {side} is not on its split template')
        half = ram[manager + 608 * (side + 1):manager + 608 * (side + 2)]
        live = bytearray(ram[cam:cam + 608])
        for o in range(0, 608, 4):
            if live[o:o + 4] == half[o:o + 4]:
                live[o:o + 4] = full[o:o + 4]
        out += [(cam, bytes(live)), (cam + 640, struct.pack('<I', 0))]
    return out


def single_view_report(ram):
    """What a converted (or natively single-view) image holds: the split flag and both side cameras' template words."""
    n = natives()
    manager = u32(ram, A(0x2FEBD4))
    sides = []
    for side in range(2):
        cam = manager + SIDE_CAMERA + SIDE_STRIDE * side
        sides.append(dict(rect=words(ram, cam + 512, 4), mode=u32(ram, cam + 640),
                          centre=[round(struct.unpack_from('<f', ram, cam + o)[0], 1) for o in (576, 580)]))
    return dict(split=u32(ram, n.scene + SCENE_SPLIT), manager=manager, sides=sides)


def blocks(ram, views=1):
    """[(address, bytes)] installing per-window views into a single-view prepared match (with netplay_core installed
    from the same image: both are built from the original RAM, so their blocks never overlap)."""
    import cinematic_policy as cinema
    import fresh_team_camera as follow
    import hud_subject as hud
    import lockoff_target as off
    import lockon_select as lockon
    import quad_viewports as quad
    import spectator_switch as spec
    import spectator_takeover as take
    n = natives()
    if len(ram) != 0x8000000:
        raise ValueError('a 128 MiB EE image is required')
    if (quad.CONTROL, quad.MAGIC) != (QUAD_CONTROL, QUAD_MAGIC):
        raise ValueError('quad_viewports moved')
    if any(ram[CONTROL:END]):
        raise ValueError('per-window view reservation 0x07B01100..0x07B02000 occupied')
    if any(ram[nc.VIEW_AREA:nc.VIEW_AREA_END]):
        raise ValueError('per-fighter camera reservation 0x07B26000..0x07B30000 occupied')
    if u32(ram, n.scene + SCENE_SPLIT) != 0:
        raise ValueError('per-window views need the single-view fixture (scene+36 = 0); convert it first')
    manager = u32(ram, A(0x2FEBD4))
    for side in range(2):
        cam = manager + SIDE_CAMERA + SIDE_STRIDE * side
        if u32(ram, cam + 640) != 0 or words(ram, cam + 512, 4) != [0, 511, 0, 447]:
            raise ValueError(f'side camera {side} is not on the full-screen template')
    if words(ram, n.select_site, 2) != [j(cinema.CODE), 0] or u32(ram, cinema.CONTROL) != cinema.MAGIC:
        raise ValueError('the camera selection hook is not cinematic_policy\'s selector')
    if u32(ram, n.render_site) != jal(n.render):
        raise ValueError('the single-view render call is not native')
    if words(ram, n.burst_call - 8, 6) != [0x54400005, 0xC6010000, jal(n.release), 0x0220202D, 0x10000023, 0x2652FFFF]:
        raise ValueError('the light-burst release site is not native')
    if words(ram, n.viewer_site - 4, 4) != [0x24020001, jal(n.viewed), 0, 0x8E230000]:
        raise ValueError('207FB0\'s viewed-side tie-break is not native')
    if u32(ram, follow.LEADER_CONTROL) != 1:
        raise ValueError('fresh_team_camera\'s leader selection is not installed')
    out, camera, marker = [], None, None
    patched = PATCH_BITS['viewer']
    # hud_subject's resolver: its split read (lui t2 / ori t2 / lw t2,36(t2)) -> CONTROL.views.
    site = split_read_site(ram, hud.CODE, hud.UPDATE_WRAP, 10, 10) if u32(ram, hud.CONTROL) == hud.MAGIC else None
    if site is not None:
        out.append((site, struct.pack('<2I', *redirect_words(10))))
        patched |= PATCH_BITS['hud']
    # The spectator/takeover payload: lui t0 / ori t0 / lw t1,36(t0).
    site = split_read_site(ram, spec.CODE, take.LOOKUP, 8, 9) if u32(ram, spec.CONTROL) == spec.MAGIC else None
    if site is not None:
        out.append((site, struct.pack('<2I', *redirect_words(8))))
        patched |= PATCH_BITS['spectator']
    # lockoff_target CAMERA: its quad check jumps to its native successor path when quad is not installed.
    if u32(ram, off.CONTROL) == off.MAGIC:
        have = words(ram, off.CAMERA, 6)
        if have[:5] == quad_check_words(0)[:5] and have[5] >> 16 == 0x152A:
            single = branch_target(off.CAMERA + 20, have[5])
            if words(ram, single, 2) != [0x3C080000 | follow.SUCCESSOR_CONTROL >> 16,
                                         0x35080000 | follow.SUCCESSOR_CONTROL & 0xFFFF]:
                raise ValueError('lockoff CAMERA\'s successor path changed')
            camera = (off.CAMERA, single)
            out.append((off.CAMERA, struct.pack('<2I', j(CAMERA_GATE), 0)))
            patched |= PATCH_BITS['camera']
        # Its single-view target-panel filter would hide player 2's panel when player 1 unlocks: show it.
        if u32(ram, off.CONTROL + off.HUD_POLICY) != off.HUD_POLICIES['show']:
            out.append((off.CONTROL + off.HUD_POLICY, struct.pack('<I', off.HUD_POLICIES['show'])))
            patched |= PATCH_BITS['policy']
    # lockon_select MARKER: its seat lookup by quad rectangle never matches a full-screen camera.
    if u32(ram, lockon.CONTROL) == lockon.MAGIC:
        import display_settings as display
        hits = [p for p in find_pattern(ram, lockon.MARKER, lockon.TAIL_INPUT, quad_check_words(None)[:5])
                if u32(ram, p + 20) >> 16 == 0x152A]
        if len(hits) == 1:
            site = hits[0]
            single = branch_target(site + 20, u32(ram, site + 20))
            if words(ram, single, 2) != [0x02C0202D, jal(display.SUBJECT)] or u32(ram, single + 12) != 0x0040802D:
                raise ValueError('lockon_select\'s single-view seat path changed')
            marker = (site, single, single + 16)
            out.append((site, struct.pack('<2I', j(MARKER_GATE), 0)))
            patched |= PATCH_BITS['marker']
    out = programs(cinema.CODE, camera, marker) + out
    out += [(n.select_site, struct.pack('<I', j(SEL))), (n.render_site, struct.pack('<I', jal(SWAP))),
            (n.burst_call, struct.pack('<I', jal(BURST))), (n.burst_branch, struct.pack('<I', 0x50400023)),
            (n.viewer_site, struct.pack('<I', jal(VIEWER)))]
    import netplay_hud
    out.extend(netplay_hud.blocks(ram))
    out.append((CONTROL, control(views, patched)))
    ordered = sorted(out)
    assert all(p + len(b) <= q for (p, b), (q, _) in zip(ordered, ordered[1:])), 'overlapping view blocks'
    return out


def control(views=1, patched=0):
    blob = bytearray(CONTROL_BYTES)
    for name, value in dict(magic=MAGIC, views=int(bool(views)), layout=LAYOUT, patched=patched,
                            watch=NO_WATCH, subject=NO_WATCH).items():
        struct.pack_into('<I', blob, F[name], value)
    return bytes(blob)


def build_memory(ram, views=1):
    """A guarded manifest (patch_state.patch applies it) for the per-window view programs and patches."""
    return dict(status='NETPLAY PER-WINDOW VIEWS (Stage A proof of concept)', serial=SERIAL, crc=CRC, layout=LAYOUT,
                blocks=[dict(address=p, expected_hex=bytes(ram[p:p + len(b)]).hex(), data_hex=b.hex())
                        for p, b in blocks(ram, views)])


def hash_rows():
    """netplay_state_hash descriptors (class 7) for netplay_core's extra_rows: everything here that must be equal on
    every copy and that a view leak would change first."""
    import netplay_state_hash as nh
    import hud_subject as hud
    n = natives()
    return [(nh.DIRECT, 7, CONTROL + F['canonical'], 0, LOGIC_WORDS,
             'per-window views: selection record (canonical, view0, view1, shared), VU0 R snapshot, selections, '
             'manager+3136'),
            (nh.INDIRECT, 7, n.burst_pool, 164, 2, 'light-burst pool occupancy (gp-22124 +164/+168)'),
            (nh.DIRECT, 7, hud.CONTROL + 24, 0, 6, 'HUD panel subjects (subject, active, last, snaps, left, left last)'),
            (nh.DIRECT, 7, CAM_LOGIC, 0, 3, 'per-fighter cameras: slots with one, cameras built, updates')]


# ---- host helpers ------------------------------------------------------------------------------------------------------
def parse_control(data):
    return {name: struct.unpack_from('<I', data, offset)[0] for name, offset in FIELDS}


def read_control(client):
    return parse_control(client.read(CONTROL, CONTROL_BYTES))
