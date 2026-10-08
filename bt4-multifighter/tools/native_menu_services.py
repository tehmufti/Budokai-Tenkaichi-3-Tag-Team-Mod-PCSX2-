"""Native description, narration, plate animation and fade services.

Entry hooks are in the executable, not scene overlays. Every changed call is
limited by the actual native caller, owned menu object, scene and live lease.
Audited against analysis/sept16-mode-update/menu-research/main-menu.bin.
"""
from native_map import A, GPO, JPN, elf_path
import struct
from prototype import Assembler, ROOT, elf_reader
import mode_menu as old

CODE=0x07690000
CONTROL=0x076FF000
MAGIC=0x324D4E42
TEXT,STOCK_TEXT=0x076E2000,0x076E6000
DESCRIPTION,NARRATION,FADE,RESET,PULSE=CODE+0x3000,CODE+0x4000,CODE+0x4800,CODE+0x5000,CODE+0x6000
SFX,RETURN=CODE+0x6400,CODE+0x6800
CANCEL=CODE+0x7800
TRAMP=CODE+0x6F00
HOOKS={A(0x25D0F8):DESCRIPTION,A(0x2614B0):NARRATION,A(0x126B88):FADE,A(0x25E370):PULSE,A(0x124F68):SFX,A(0x129278):RETURN,A(0x265728):CANCEL}
ORIGINAL={A(0x25D0F8):((35 << 26) | (28 << 21) | (4 << 16) | (GPO(-0x5198) & 0xFFFF),0x27BDFFD0),A(0x2614B0):(0x27BDFFE0,(35 << 26) | (28 << 21) | (3 << 16) | (GPO(-0x4FE4) & 0xFFFF)),
          A(0x126B88):(0x27BDFFF0,0x3C020000|((A(0x301048)+0x8000)>>16)),A(0x25E370):(0x27BDFFD0,(35 << 26) | (28 << 21) | (3 << 16) | (GPO(-0x5164) & 0xFFFF)),
          A(0x124F68):(0x27BDFFF0,0x24060040),A(0x129278):(0x27BDFFF0,0xFFBF0000),
          A(0x265728):(0x27BDFFE0,0xFFB00000)}
if JPN:
    # Reviewed (release_tools/jpn_reviewed.json 0x2614b0): the Japanese menu voice routine has no voice-language test,
    # so its second word is move a3,zero instead of the gp load; both displaced words are position independent.
    ORIGINAL[A(0x2614B0)]=(0x27BDFFE0,0x0000382D)
VOLATILE=tuple(range(1,16))+(24,25,31)
STACK=0xC0


def save(a):
    a.addiu(29,29,-STACK)
    for i,r in enumerate(VOLATILE):a.i(63,r,29,i*8)
    a.r(0x10,8,0);a.i(63,8,29,0x90);a.r(0x12,8,0);a.i(63,8,29,0x98)


def restore(a):
    a.i(55,8,29,0x90);a.r(0x11,0,8);a.i(55,8,29,0x98);a.r(0x13,0,8)
    for i,r in enumerate(VOLATILE):a.i(55,r,29,i*8)
    a.addiu(29,29,STACK)


def scope(a,fail,states=(2,)):
    a.li(8,CONTROL);a.lw(9,8);a.li(10,MAGIC);a.branch(5,9,10,fail)
    a.lw(9,8,16);a.branch(4,9,0,fail);a.lw(9,8,4)
    for i,state in enumerate(states):
        a.addiu(10,0,state);a.branch(4,9,10,'state_ok')
    a.jump(fail);a.label('state_ok')
    a.li(10,old.SCENE_MANAGER);a.lw(10,10);a.li(11,0x100000);a.r(0x2B,11,10,11);a.branch(5,11,0,fail)
    a.li(11,0x1FFF000);a.r(0x2B,11,10,11);a.branch(4,11,0,fail)
    a.lw(10,10,0x18);a.addiu(11,0,4);a.branch(5,10,11,fail)
    a.li(10,old.MAIN_OBJECT);a.lw(11,10);a.lw(12,8,20);a.branch(5,11,12,fail)
    a.lw(10,11,4);a.lw(12,8,0x14C);a.branch(5,10,12,fail)


def description():
    a=Assembler(DESCRIPTION);save(a)
    a.li(10,A(0x335FE4));a.branch(5,31,10,'native');scope(a,'native',(2,4))
    a.lw(9,8,4);a.addiu(10,0,4);a.branch(4,9,10,'stock')
    a.lw(10,11,0x144);a.i(11,12,10,12);a.branch(4,12,0,'native');a.branch(4,10,0,'native')
    a.lw(12,11,0x148);a.lw(13,11,0x10C);a.r(0x21,12,12,13);a.addiu(12,12,1)
    a.i(11,13,12,24);a.branch(4,13,0,'native')
    a.label('mod');a.r(0x2B,13,12,10);a.branch(5,13,0,'selected');a.r(0x23,12,12,10);a.jump('mod')
    a.label('selected');a.r(0,12,0,12,2);a.r(0x21,12,12,11);a.lw(12,12,0x118)
    a.i(11,13,12,8);a.branch(4,13,0,'native');a.lw(13,8,8);a.i(11,10,13,6);a.branch(4,10,0,'native')
    a.r(0,13,0,13,3);a.r(0x21,6,12,13);a.li(12,TEXT);a.jump('bind')
    a.label('stock');a.lw(10,8,36);a.branch(4,10,0,'native');a.i(11,10,6,64);a.branch(4,10,0,'native');a.li(12,STOCK_TEXT)
    a.label('bind');a.li(9,A(0x2FF0D8));a.lw(9,9);a.li(10,0x100000);a.r(0x2B,10,9,10);a.branch(5,10,0,'native')
    a.li(10,0x1FFF000);a.r(0x2B,10,9,10);a.branch(4,10,0,'native')
    a.sw(9,29,0xA0);a.lw(10,9);a.lw(13,11,8);a.branch(5,10,13,'native');a.sw(10,29,0xA4)
    a.lw(10,9,0x48);a.branch(5,10,13,'native');a.sw(10,29,0xA8)
    a.sw(12,9);a.sw(12,9,0x48);a.call(TRAMP)
    a.lw(9,29,0xA0);a.lw(10,29,0xA4);a.sw(10,9);a.lw(10,29,0xA8);a.sw(10,9,0x48)
    restore(a);a.jr()
    a.label('native');restore(a);a.jump(TRAMP)
    return a.finish()


def route_scope(a,fail):
    """Covered automated routing only; never suppress human menu selection."""
    a.li(8,CONTROL);a.lw(9,8);a.li(10,MAGIC);a.branch(5,9,10,fail)
    a.lw(9,8,40);a.branch(4,9,0,fail);a.lw(9,8,44);a.branch(4,9,0,fail)
    a.li(10,old.SCENE_MANAGER);a.lw(10,10)
    a.li(11,0x100000);a.r(0x2B,11,10,11);a.branch(5,11,0,fail)
    a.li(11,0x1FFF000);a.r(0x2B,11,10,11);a.branch(4,11,0,fail)
    a.lw(10,10,0x18)


DUEL_VOICE_CALLERS=(A(0x354D98),A(0x354F38),A(0x355028),A(0x3551A8),A(0x3552CC),A(0x355384),A(0x3559F4),A(0x355E2C),A(0x355E5C),A(0x3561B4))
DUEL_SFX_CALLERS=(A(0x355634),A(0x35581C),A(0x355A00),A(0x355B94),A(0x355C98),A(0x355D58),A(0x355EB8))
MAIN_VOICE_CALLERS=(A(0x33617C),A(0x336418),A(0x336988))


def narration():
    a=Assembler(NARRATION);save(a)
    for caller in DUEL_VOICE_CALLERS:
        a.li(10,caller);a.branch(4,31,10,'route')
    for caller in MAIN_VOICE_CALLERS:
        a.li(10,caller);a.branch(4,31,10,'caller')
    a.jump('native');a.label('caller')
    # A committed custom choice has already restored the original menu rows.
    # Its native Duel announcement may run in state 3 before scene 38 starts.
    route_scope(a,'custom');a.addiu(11,0,4);a.branch(4,10,11,'mute')
    a.label('custom');scope(a,'native');a.jump('mute')
    a.label('route');route_scope(a,'native');a.addiu(11,0,38);a.branch(5,10,11,'native')
    a.label('mute');restore(a);a.move(2,0);a.jr()
    a.label('native');restore(a);a.jump(TRAMP+0x40)
    return a.finish()


def route_sfx():
    a=Assembler(SFX);save(a)
    for caller in DUEL_SFX_CALLERS:
        a.li(10,caller);a.branch(4,31,10,'duel')
    a.li(10,A(0x3367C0));a.branch(5,31,10,'native')
    route_scope(a,'native');a.addiu(11,0,4);a.branch(5,10,11,'native');a.jump('mute')
    a.label('duel');route_scope(a,'native');a.addiu(11,0,38);a.branch(5,10,11,'native')
    a.label('mute');restore(a);a.move(2,0);a.jr()
    a.label('native');restore(a);a.jump(TRAMP+0x100);return a.finish()


def return_policy():
    # 336A90 owns scene transitions. Its original reason-bit precedence already
    # supports a return to main (8), whereas cancel bit128 reopens Duel. Change
    # only this read result after custom character-select cancellation.
    a=Assembler(RETURN);save(a);a.call(TRAMP+0x140);a.i(63,2,29,8)
    a.i(55,10,29,17*8);a.li(11,A(0x336B04));a.branch(5,10,11,'done')
    a.i(12,10,2,0x80);a.branch(4,10,0,'done')
    a.li(8,CONTROL);a.lw(9,8);a.li(10,MAGIC);a.branch(5,9,10,'done')
    a.lw(9,8,56);a.branch(4,9,0,'done');a.lw(9,8,60)
    a.branch(4,9,0,'done');a.i(11,10,9,22);a.branch(4,10,0,'done');a.addiu(10,0,6);a.branch(4,9,10,'done')
    a.li(10,old.SCENE_MANAGER);a.lw(10,10);a.li(11,0x100000);a.r(0x2B,11,10,11);a.branch(5,11,0,'done')
    a.li(11,0x1FFF000);a.r(0x2B,11,10,11);a.branch(4,11,0,'done')
    a.lw(10,10,0x18);a.addiu(11,10,-39);a.i(11,11,11,2);a.branch(4,11,0,'done')
    a.i(13,2,2,8);a.i(63,2,29,8)
    a.addiu(12,0,2)
    for choice in (4,14,19):a.addiu(10,0,choice);a.branch(4,9,10,'coop')
    for choice in (11,16,21):a.addiu(10,0,choice);a.branch(4,9,10,'training_coop')
    for choice in (9,10,15,20):a.addiu(10,0,choice);a.branch(4,9,10,'training')
    for choice in (2,3,5,13,18):a.addiu(10,0,choice);a.branch(4,9,10,'ffa')
    a.jump('publish');a.label('coop');a.addiu(12,0,2);a.jump('publish')
    a.label('training_coop');a.addiu(12,0,5);a.jump('publish')
    a.label('training');a.addiu(12,0,5);a.jump('publish');a.label('ffa');a.addiu(12,0,3)
    a.label('publish');a.sw(12,8,64);a.lw(10,8,48);a.sw(10,8,40);a.addiu(10,0,600);a.sw(10,8,44)
    a.addiu(10,0,128);a.sw(10,8,52);a.sw(0,8,72)
    a.label('done');restore(a);a.jr();return a.finish()


# Triangle exits Team/Single Select inside 352CB8's nested scene loop, not the
# once-per-entry 336A90 result dispatcher. These exact native words identify
# the cancel-only cleanup call and its loop/epilogue contract.
CANCEL_SIGNATURES={A(0x352DF0):0x10400005,A(0x352E08):0x0C000000|(A(0x265728)>>2),
                   A(0x352E0C):0x0000802D,A(0x352E10):0x8E220000,
                   A(0x352E14):0x10000010,A(0x352E18):0xAC540018,
                   A(0x352E64):0x5240FFB2,A(0x352E68):0x8E220000,
                   A(0x352E78):0x02C0102D,A(0x352E88):0x02C0102D}


def selector_cancel():
    """Complete native selector cleanup, then leave its nested Duel loop.

Only the audited cancel continuation may change s2/s6 (the native loop's exit
flag/result). Its real epilogue restores the caller's saved registers. No scene
overlay instruction, pad value, roster or native result record is patched.
"""
    a=Assembler(CANCEL);save(a);a.call(TRAMP+0x180);a.i(63,2,29,8)
    a.i(55,10,29,17*8);a.li(11,A(0x352E10));a.branch(5,10,11,'done')
    a.li(8,CONTROL);a.lw(9,8);a.li(10,MAGIC);a.branch(5,9,10,'done')
    a.lw(9,8,56);a.branch(4,9,0,'done');a.lw(9,8,60)
    a.branch(4,9,0,'done');a.i(11,10,9,22);a.branch(4,10,0,'done');a.addiu(10,0,6);a.branch(4,9,10,'done')
    a.li(10,old.SCENE_MANAGER);a.lw(10,10);a.li(11,0x100000);a.r(0x2B,11,10,11);a.branch(5,11,0,'done')
    a.li(11,0x1FFF000);a.r(0x2B,11,10,11);a.branch(4,11,0,'done')
    a.lw(11,10,0x18);a.addiu(11,11,-39);a.i(11,11,11,2);a.branch(4,11,0,'done')
    for p,word in CANCEL_SIGNATURES.items():
        a.li(11,p);a.lw(11,11);a.li(12,word);a.branch(5,11,12,'done')
    a.addiu(11,0,4);a.sw(11,10,0x18)
    a.addiu(12,0,2)
    for choice in (4,14,19):a.addiu(10,0,choice);a.branch(4,9,10,'coop')
    for choice in (11,16,21):a.addiu(10,0,choice);a.branch(4,9,10,'training_coop')
    for choice in (9,10,15,20):a.addiu(10,0,choice);a.branch(4,9,10,'training')
    for choice in (2,3,5,13,18):a.addiu(10,0,choice);a.branch(4,9,10,'ffa')
    a.jump('publish');a.label('coop');a.addiu(12,0,2);a.jump('publish')
    a.label('training_coop');a.addiu(12,0,5);a.jump('publish')
    a.label('training');a.addiu(12,0,5);a.jump('publish');a.label('ffa');a.addiu(12,0,3)
    a.label('publish');a.sw(12,8,64);a.lw(10,8,48);a.sw(10,8,40);a.addiu(10,0,600);a.sw(10,8,44)
    a.addiu(10,0,128);a.sw(10,8,52);a.sw(0,8,72)
    restore(a);a.addiu(18,0,1);a.move(22,0);a.li(31,A(0x352E58));a.jr()
    a.label('done');restore(a);a.jr()
    result=a.finish();assert len(result)<0x800;return result


def reset():
    # Called only from the already scoped main-menu pad service. The native
    # movie API resets all seven plate timelines before lighting one plate.
    a=Assembler(RESET);save(a)
    # Lease cleanup may restore an object just as a scene changes. Its saved
    # fields can be restored, but its old movie APIs must not run after exit.
    a.li(8,CONTROL);a.li(10,old.SCENE_MANAGER);a.lw(10,10)
    a.li(11,0x100000);a.r(0x2B,11,10,11);a.branch(5,11,0,'done')
    a.li(11,0x1FFF000);a.r(0x2B,11,10,11);a.branch(4,11,0,'done')
    a.lw(10,10,0x18);a.addiu(11,0,4);a.branch(5,10,11,'done')
    a.li(10,old.MAIN_OBJECT);a.lw(11,10);a.lw(12,8,20);a.branch(5,11,12,'done')
    a.lw(10,11,4);a.lw(12,8,0x14C);a.branch(5,10,12,'done')
    a.move(4,0);a.call(A(0x265F88)) # stop the current main-menu voice channel
    a.li(8,CONTROL);a.lw(11,8,20);a.sw(11,29,0xA0)
    for i in range(7):
        a.lw(4,29,0xA0);a.addiu(4,4,0x10);a.move(5,0);a.li(6,TEXT+0x3000+i*32);a.addiu(7,29,0xB0);a.call(A(0x10D8B0))
        a.lw(4,29,0xA0);a.addiu(4,4,0x10);a.addiu(5,29,0xB0);a.li(6,A(0x3B10B0));a.call(A(0x10D918))
    a.lw(11,29,0xA0);a.lw(10,11,0x10C);a.addiu(10,10,1);a.r(0,10,0,10,5);a.li(6,TEXT+0x3000);a.r(0x21,6,6,10)
    a.addiu(4,11,0x10);a.move(5,0);a.addiu(7,29,0xB0);a.call(A(0x10D8B0))
    a.lw(4,29,0xA0);a.addiu(4,4,0x10);a.addiu(5,29,0xB0);a.li(6,A(0x3B10A0));a.call(A(0x10D918))
    a.label('done');restore(a);a.jr();return a.finish()


def pulse():
    a=Assembler(PULSE);save(a);a.li(10,A(0x335BC4));a.branch(5,31,10,'native');scope(a,'native')
    a.lw(10,11,0x10C);a.addiu(10,10,1);a.branch(4,21,10,'native')
    restore(a);a.jr()
    a.label('native');restore(a);a.jump(TRAMP+0xC0);return a.finish()


def fade():
    # Render through the stock full-screen fade, borrowing its color/alpha only
    # for this draw. Never hold native fade completion flags: those flags drive
    # Duel loading/readiness, so freezing them would deadlock menu navigation.
    a=Assembler(FADE);save(a);a.li(8,CONTROL);a.lw(9,8);a.li(10,MAGIC);a.branch(5,9,10,'native')
    a.lw(9,8,40);a.branch(4,9,0,'native');a.lw(9,8,44);a.branch(4,9,0,'release');a.addiu(9,9,-1);a.sw(9,8,44)
    a.li(10,old.SCENE_MANAGER);a.lw(10,10);a.li(11,0x100000);a.r(0x2B,11,10,11);a.branch(5,11,0,'release')
    a.li(11,0x1FFF000);a.r(0x2B,11,10,11);a.branch(4,11,0,'release');a.lw(10,10,0x18)
    a.addiu(11,0,4);a.branch(5,10,11,'duel_scene');a.lw(11,8,4);a.addiu(12,0,2);a.branch(4,11,12,'release');a.jump('hold')
    a.label('duel_scene');a.addiu(11,0,38);a.branch(4,10,11,'hold')
    # A scenario populates a real Team Select object behind the transition.
    # Reveal it only once the game's own Done handler opens stage selection.
    import scenario_menu
    a.addiu(11,0,40);a.branch(5,10,11,'release')
    a.li(11,scenario_menu.CONTROL);a.lw(12,11);a.li(13,scenario_menu.MAGIC);a.branch(5,12,13,'release')
    a.lw(12,11,24);a.branch(4,12,0,'release')
    a.lw(12,11,20);a.addiu(12,12,-1);a.i(11,12,12,3);a.branch(4,12,0,'release')
    a.label('hold');a.addiu(10,0,128);a.sw(10,8,52);a.jump('draw')
    a.label('release');a.lw(10,8,52);a.addiu(10,10,-8);a.branch(1,10,0,'finished');a.sw(10,8,52);a.branch(4,10,0,'finished')
    a.label('draw');a.li(9,A(0x301048));a.i(55,11,9,0);a.i(63,11,29,0xA0);a.i(55,11,9,8);a.i(63,11,29,0xA8)
    a.lw(11,9,8);a.r(0x2A,12,10,11);a.branch(4,12,0,'alpha');a.move(10,11)
    a.label('alpha');a.sw(0,9,4);a.sw(10,9,8);a.call(TRAMP+0x80)
    a.li(9,A(0x301048));a.i(55,11,29,0xA0);a.i(63,11,9,0);a.i(55,11,29,0xA8);a.i(63,11,9,8)
    a.li(8,CONTROL);a.lw(9,8,52);a.addiu(10,0,128);a.branch(5,9,10,'no_indicator')
    import native_menu_loading
    a.call(native_menu_loading.CODE)
    a.label('no_indicator');restore(a);a.jr()
    a.label('finished');a.sw(0,8,40);a.sw(0,8,44);a.sw(0,8,52)
    a.label('native');a.call(TRAMP+0x80)
    # Preserve the native return value while rendering the optional selector
    # owner hint after its fade; the helper scopes itself to co-op selection.
    a.i(63,2,29,8)
    import coop_character_select
    import player_slot_labels
    a.call(coop_character_select.DRAW);a.call(player_slot_labels.CODE);restore(a);a.jr();return a.finish()


def code_pieces():
    native=elf_reader(elf_path(ROOT))[2]
    blocks=[(DESCRIPTION,description()),(NARRATION,narration()),(FADE,fade()),(RESET,reset()),(PULSE,pulse()),(SFX,route_sfx()),(RETURN,return_policy()),(CANCEL,selector_cancel())]
    for i,(address,dest)in enumerate(HOOKS.items()):
        original=struct.pack('<2I',*ORIGINAL[address]);assert native(address,8)==original
        a=Assembler(TRAMP+i*0x40);a.words.extend(ORIGINAL[address]);a.jump(address+8)
        blocks.append((TRAMP+i*0x40,a.finish()))
        blocks.append((address,struct.pack('<2I',(2<<26)|(dest>>2),0)))
    import native_menu_loading
    return blocks+native_menu_loading.code_pieces()
