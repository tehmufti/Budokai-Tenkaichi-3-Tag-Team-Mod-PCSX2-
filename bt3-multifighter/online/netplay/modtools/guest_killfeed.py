"""Native GS kill feed for captured 2v2/3v3 matches; offline installer only.

1CE630 is observed across its native call: only a positive-to-zero HP edge
records a death. Attribution is accepted only from audited caller registers,
never the victim's current target. The once-per-update 1CF220 call also finds
unknown/environmental deaths. The left world viewport draws compact glyphs
with ordinary native GIF packets, including in fullscreen and save states.
"""
from native_map import A, CRC, SERIAL, elf_path
import argparse
import json
import struct
import unicodedata
import localization
from pathlib import Path
from prototype import Assembler, ROOT, elf_reader
from camera_snapshot import read_ram
import fresh_team_combat as core
import guest_healthbars as bars
from battle_mode_policy import ACTOR_COUNTS
from regional import SCISSOR_Y1, Y_ORIGIN, screen_y
from native_map import ticks

GATE, ROW, IDENTIFY, RECORD = 0x07410000, 0x07410200, 0x07410400, 0x07410600
DAMAGE, DAMAGE_NATIVE, TICK, WORLD = 0x07411000, 0x07411F00, 0x07412000, 0x07413000
DRAW, TEXT, TEMPLATE = 0x07413400, 0x07414000, 0x07415000
CONTROL, EVENTS, FONT, NAMES = 0x07416000, 0x07416200, 0x07418000, 0x0741C000
UNKNOWN, END = 0x07421200, 0x07422000
DAMAGE_ENTRY, TICK_CALL = A(0x1CE630), A(0x1C2E30)
LIFETIME, FADE, MAX_EVENTS, MAX_CHARS = ticks(150), 32, 4, 40   # 5 s of updates; the 32-step fade is an alpha ramp
REGS = tuple(range(1, 29)) + (30,)
REG_OFFSET = {r: i*8 for i,r in enumerate(REGS)}
FRAME_SIZE, RETURN = 0x140, 0xE8
# Return address -> caller's proven actual attacker pointer register.
# Additional direct melee/projectile callsites are supplied by the native audit.
ATTRIBUTION = {p+8: 16 for p in (A(0x1CF2C8), A(0x1CF30C), A(0x1CF444), A(0x1CF4F8))}
ATTRIBUTION.update({A(0x1CA43C):17, A(0x1CB9C4):19, A(0x1CBCDC):18,
                    A(0x1CBEF4):19, A(0x1CC1F4):19})

# Original compact 5x7 bitmap glyphs. Run encoding packs x, y and width.
GLYPHS = {
 '%':['11001','11010','00100','00100','01000','10110','00110'],
 'A':['01110','10001','10001','11111','10001','10001','10001'],
 'B':['11110','10001','10001','11110','10001','10001','11110'],
 'C':['01111','10000','10000','10000','10000','10000','01111'],
 'D':['11110','10001','10001','10001','10001','10001','11110'],
 'E':['11111','10000','10000','11110','10000','10000','11111'],
 'F':['11111','10000','10000','11110','10000','10000','10000'],
 'G':['01111','10000','10000','10111','10001','10001','01111'],
 'H':['10001','10001','10001','11111','10001','10001','10001'],
 'I':['11111','00100','00100','00100','00100','00100','11111'],
 'J':['00111','00010','00010','00010','10010','10010','01100'],
 'K':['10001','10010','10100','11000','10100','10010','10001'],
 'L':['10000','10000','10000','10000','10000','10000','11111'],
 'M':['10001','11011','10101','10101','10001','10001','10001'],
 'N':['10001','11001','10101','10011','10001','10001','10001'],
 'O':['01110','10001','10001','10001','10001','10001','01110'],
 'P':['11110','10001','10001','11110','10000','10000','10000'],
 'Q':['01110','10001','10001','10001','10101','10010','01101'],
 'R':['11110','10001','10001','11110','10100','10010','10001'],
 'S':['01111','10000','10000','01110','00001','00001','11110'],
 'T':['11111','00100','00100','00100','00100','00100','00100'],
 'U':['10001','10001','10001','10001','10001','10001','01110'],
 'V':['10001','10001','10001','10001','10001','01010','00100'],
 'W':['10001','10001','10001','10101','10101','10101','01010'],
 'X':['10001','10001','01010','00100','01010','10001','10001'],
 'Y':['10001','10001','01010','00100','00100','00100','00100'],
 'Z':['11111','00001','00010','00100','01000','10000','11111'],
 '0':['01110','10001','10011','10101','11001','10001','01110'],
 '1':['00100','01100','00100','00100','00100','00100','01110'],
 '2':['01110','10001','00001','00010','00100','01000','11111'],
 '3':['11110','00001','00001','01110','00001','00001','11110'],
 '4':['00010','00110','01010','10010','11111','00010','00010'],
 '5':['11111','10000','10000','11110','00001','00001','11110'],
 '6':['01110','10000','10000','11110','10001','10001','01110'],
 '7':['11111','00001','00010','00100','01000','01000','01000'],
 '8':['01110','10001','10001','01110','10001','10001','01110'],
 '9':['01110','10001','10001','01111','00001','00001','01110'],
 ' ':['00000']*7, '-':['00000','00000','00000','11111','00000','00000','00000'],
 '>':['00000','10000','01000','00100','01000','10000','00000'],
 '(' :['00010','00100','01000','01000','01000','00100','00010'],
 ')' :['01000','00100','00010','00010','00010','00100','01000'],
 '/' :['00001','00001','00010','00100','01000','10000','10000'],
 '.' :['00000','00000','00000','00000','00000','00100','00100'],
 "'":['00100','00100','00000','00000','00000','00000','00000'],
 '?':['01110','10001','00001','00010','00100','00000','00100'],
 '#':['01010','01010','11111','01010','11111','01010','01010'],
}


def font_data():
    result = bytearray(128*128)
    for i in range(128):
        runs = []
        for y, row in enumerate(GLYPHS.get(chr(i), GLYPHS['?'])):
            x = 0
            while x < 5:
                if row[x] == '0': x += 1; continue
                start = x
                while x < 5 and row[x] == '1': x += 1
                runs.append(start | (y<<8) | ((x-start)<<16))
        assert len(runs) <= 31
        struct.pack_into('<'+'I'*(len(runs)+1), result, i*128, len(runs), *runs)
    return bytes(result)


def name_data(names):
    """Bounded ASCII battle labels; full localized names remain in menus.

    Disc names are presentation data, not a reason to abort fighter creation.
    Fold accents for this compact atlas, mark unavailable glyphs visibly, and
    ellipsize long labels before writing either fixed-size guest string.
    """
    result = bytearray(161*128)
    normalized = {}
    for i in range(161):
        value = str(names.get(str(i), names.get(i, f'CHARACTER {i}'))).upper()
        value = ' '.join(value.replace('\n',' ').split())
        value = ''.join(c for c in unicodedata.normalize('NFKD',value)
                        if not unicodedata.combining(c)).upper()
        value = ''.join(c if c in GLYPHS else '?' for c in value.replace('°','.'))
        if len(value) > MAX_CHARS-2:
            value = value[:MAX_CHARS-5].rstrip()+'...'
        normalized[str(i)] = value
        for offset, text in ((0,value),(64,'> '+value)):
            result[i*128+offset:i*128+offset+len(text)] = text.encode('ascii')
    return bytes(result), normalized


def save(a):
    for r in REGS: a.i(63,r,29,REG_OFFSET[r])


def restore(a):
    for r in REGS: a.i(55,r,29,REG_OFFSET[r])


def prologue(a):
    a.addiu(29,29,-FRAME_SIZE); save(a); a.i(63,31,29,RETURN)


def epilogue(a):
    restore(a); a.i(55,31,29,RETURN); a.addiu(29,29,FRAME_SIZE); a.jr()


def gate_code():
    a=Assembler(GATE); core.gate(a,'no'); a.li(8,CONTROL)
    a.lw(9,8); a.branch(4,9,0,'no'); a.lw(9,8,4); a.lw(8,28,-22364)
    a.branch(5,8,9,'no'); a.li(8,CONTROL); a.lw(9,8,8); a.branch(5,9,10,'no')
    a.li(8,core.PAIR+4); a.lw(9,8); a.branch(5,9,0,'no')
    a.addiu(2,0,1); a.jr(); a.label('no'); a.move(2,0); a.jr(); return a.finish()


def identify_code():
    a=Assembler(IDENTIFY); a.li(8,CONTROL); a.lw(9,8,8); a.move(2,0)
    a.li(8,core.POINTERS)
    a.label('loop'); a.lw(10,8); a.branch(4,10,4,'return')
    a.addiu(8,8,4); a.addiu(2,2,1); a.branch(5,2,9,'loop')
    a.addiu(2,0,-1); a.label('return'); a.jr(); return a.finish()


def row_code():
    # Actual actor pointer a0 -> v0 selected HP row, v1 current character ID.
    a=Assembler(ROW); a.lw(8,4,0x994); a.i(11,9,8,5); a.branch(4,9,0,'no')
    a.r(0,9,0,8,7); a.r(0,10,0,8,5); a.r(0x2D,9,9,10)
    a.r(0,10,0,8,2); a.r(0x2D,9,9,10); a.r(0x2D,9,9,4)
    a.addiu(2,9,0x9E4); a.lw(3,9,0x9A4)
    a.lw(8,4,12); a.i(11,10,8,12); a.branch(4,10,0,'fallback')
    a.r(0,8,0,8,2); a.li(9,core.MODELS); a.r(0x2D,8,8,9); a.lw(8,8)
    a.li(9,0x100000); a.r(0x2B,10,8,9); a.branch(5,10,0,'fallback')
    a.li(9,0x08000000-0x1670); a.r(0x2B,10,8,9); a.branch(4,10,0,'fallback')
    a.lw(3,8,12)
    a.label('fallback'); a.i(11,9,3,161); a.branch(5,9,0,'return'); a.addiu(3,0,-1)
    a.label('return'); a.jr(); a.label('no'); a.move(2,0); a.addiu(3,0,-1); a.jr(); return a.finish()


def record_code():
    a=Assembler(RECORD); a.addiu(29,29,-0x40)
    for i,r in enumerate((16,17,18,19,20,31)):a.i(63,r,29,i*8)
    a.move(16,4); a.move(17,5); a.call(GATE); a.branch(4,2,0,'return')
    a.li(18,CONTROL); a.lw(8,18,8); a.r(0x2B,9,16,8); a.branch(4,9,0,'return')
    a.r(0,8,0,16,2); a.r(0x2D,19,18,8); a.lw(9,19,0x40); a.branch(5,9,0,'return')
    a.li(9,core.POINTERS); a.r(0x2D,8,8,9); a.lw(4,8); a.call(ROW)
    a.branch(4,2,0,'return'); a.lw(8,2); a.branch(7,8,0,'return'); a.move(20,3)
    a.addiu(8,0,1); a.sw(8,19,0x40)
    a.li(19,EVENTS)
    for i in range(MAX_EVENTS-1,0,-1):
        for off in range(0,32,4):a.lw(8,19,(i-1)*32+off); a.sw(8,19,i*32+off)
    a.lw(8,18,12); a.sw(8,19); a.sw(20,19,4); a.sw(16,19,12)
    a.i(12,8,16,1); a.sw(8,19,20); a.addiu(8,0,1); a.sw(8,19,28)
    a.lw(8,18,8); a.r(0x2B,9,17,8); a.branch(4,9,0,'unknown')
    a.branch(4,16,17,'unknown')
    a.r(0,8,0,17,2); a.li(9,core.POINTERS); a.r(0x2D,8,8,9); a.lw(4,8)
    a.call(ROW); a.branch(4,2,0,'unknown'); a.sw(3,19,8); a.sw(17,19,16)
    a.i(12,8,17,1); a.sw(8,19,24); a.jump('count')
    a.label('unknown'); a.addiu(8,0,-1)
    for off in (8,16,24):a.sw(8,19,off)
    a.lw(8,18,20); a.addiu(8,8,1); a.sw(8,18,20)
    a.label('count'); a.lw(8,18,16); a.addiu(8,8,1); a.sw(8,18,16)
    a.label('return')
    for i,r in enumerate((16,17,18,19,20,31)):a.i(55,r,29,i*8)
    a.addiu(29,29,0x40); a.jr(); result=a.finish(); assert len(result)<DAMAGE-RECORD; return result


def damage_code():
    a=Assembler(DAMAGE); prologue(a); a.call(GATE); a.branch(4,2,0,'fallback')
    a.call(IDENTIFY); a.branch(1,2,0,'fallback'); a.sw(2,29,0xF0)
    a.call(ROW); a.branch(4,2,0,'fallback'); a.sw(2,29,0xF8)
    a.lw(8,2); a.sw(8,29,0xFC); a.addiu(8,0,-1); a.sw(8,29,0xF4)
    a.lw(8,29,RETURN)
    for index,(pc,reg) in enumerate(sorted(ATTRIBUTION.items())):
        a.li(9,pc); a.branch(5,8,9,f'caller{index}')
        a.i(55,4,29,REG_OFFSET[reg]); a.call(IDENTIFY); a.sw(2,29,0xF4); a.jump('native')
        a.label(f'caller{index}')
    a.label('native'); restore(a); a.call(DAMAGE_NATIVE); save(a)
    a.lw(8,29,0xFC); a.branch(6,8,0,'done'); a.lw(8,29,0xF8); a.lw(8,8)
    a.branch(7,8,0,'done'); a.lw(4,29,0xF0); a.lw(5,29,0xF4); a.call(RECORD)
    a.label('done'); epilogue(a)
    a.label('fallback'); restore(a); a.i(55,31,29,RETURN); a.addiu(29,29,FRAME_SIZE); a.jump(DAMAGE_NATIVE)
    result=a.finish(); assert len(result)<DAMAGE_NATIVE-DAMAGE; return result


def tick_code():
    a=Assembler(TICK); prologue(a); a.call(GATE); a.branch(4,2,0,'native')
    a.li(8,CONTROL); a.lw(9,8,12); a.addiu(9,9,1); a.sw(9,8,12)
    a.label('native'); restore(a); a.call(A(0x1CF220)); save(a)
    a.call(GATE); a.branch(4,2,0,'done'); a.li(16,CONTROL); a.lw(17,16,8); a.move(18,0)
    a.label('actor'); a.r(0,8,0,18,2); a.li(9,core.POINTERS); a.r(0x2D,8,8,9); a.lw(4,8)
    a.call(ROW); a.branch(4,2,0,'next'); a.lw(8,2); a.branch(6,8,0,'dead')
    a.r(0,8,0,18,2); a.r(0x2D,8,16,8); a.sw(0,8,0x40); a.jump('next')
    a.label('dead'); a.move(4,18); a.addiu(5,0,-1); a.call(RECORD)
    a.label('next'); a.addiu(18,18,1); a.branch(5,18,17,'actor')
    a.label('done'); epilogue(a); result=a.finish(); assert len(result)<WORLD-TICK; return result


def world_code():
    a=Assembler(WORLD); a.addiu(29,29,-0x20); a.i(63,31,29,0)
    a.call(bars.CODE); a.i(63,2,29,8); a.call(DRAW)
    a.i(55,2,29,8); a.i(55,31,29,0); a.addiu(29,29,0x20); a.jr(); return a.finish()


SMALL_TEXT = TEXT + 0x800


def text_code(compact=False):
    # a0 string, a1/a2 GS 12.4 screen origin, a3 ABGR. One bounded packet.
    a=Assembler(SMALL_TEXT if compact else TEXT)
    if compact:
        import quad_viewports as views
        a.li(8,views.CONTROL);a.lw(9,8);a.li(10,views.MAGIC);a.branch(5,9,10,'full_size')
        a.lw(9,8,views.VIEW_COUNT);a.addiu(9,9,-3);a.i(11,9,9,2);a.branch(4,9,0,'full_size')
    def units(reg):
        if compact:
            # 12/16-pixel glyph runs: preserve original geometry in GS 12.4,
            # rather than resampling an already rendered small bitmap.
            a.r(0,14,0,reg,1);a.r(0x21,reg,reg,14);a.r(0,reg,0,reg,2)
        else:a.r(0,reg,0,reg,4)
    step=12 if compact else 16
    a.addiu(29,29,-0x60)
    for i,r in enumerate(tuple(range(16,24))+(31,)):a.i(63,r,29,i*8)
    for d,s in zip(range(16,20),range(4,8)):a.move(d,s)
    a.call(A(0x100878)); a.move(20,2); a.li(8,TEMPLATE)
    for off in range(0,112,4):a.lw(9,8,off); a.sw(9,20,off)
    a.sw(19,20,80); a.addiu(21,20,112); a.move(22,0); a.move(23,0)
    a.label('char'); a.i(36,8,16,0); a.branch(4,8,0,'finish')
    a.i(12,8,8,127); a.r(0,8,0,8,7); a.li(9,FONT); a.r(0x2D,8,8,9); a.lw(9,8)
    a.addiu(8,8,4)
    a.label('run'); a.branch(4,9,0,'next'); a.lw(10,8)
    a.i(12,11,10,255); units(11); a.r(0x2D,11,11,17)
    a.r(3,12,0,10,8); a.i(12,12,12,255); units(12); a.r(0x2D,12,12,18)
    a.r(3,13,0,10,16); units(13); a.r(0x2D,13,13,11); a.addiu(14,12,step)
    a.r(0,12,0,12,16); a.r(0x25,11,11,12); a.sw(11,21); a.sw(0,21,4)
    a.r(0,14,0,14,16); a.r(0x25,13,13,14); a.sw(13,21,8); a.sw(0,21,12)
    a.addiu(21,21,16); a.addiu(22,22,1); a.addiu(8,8,4); a.addiu(9,9,-1); a.jump('run')
    a.label('next'); a.addiu(16,16,1); a.addiu(17,17,6*step); a.addiu(23,23,1)
    a.i(11,8,23,MAX_CHARS); a.branch(5,8,0,'char')
    a.label('finish'); a.i(13,8,22,0x8000); a.sw(8,20,96); a.move(4,21); a.call(A(0x100890))
    for i,r in enumerate(tuple(range(16,24))+(31,)):a.i(55,r,29,i*8)
    a.addiu(29,29,0x60); a.jr()
    if compact:a.label('full_size');a.jump(TEXT)
    return a.finish()


def draw_code(quad=False):
    a=Assembler(DRAW); a.addiu(29,29,-0x60)
    for i,r in enumerate(tuple(range(16,24))+(31,)):a.i(63,r,29,i*8)
    a.call(GATE); a.branch(4,2,0,'done')
    if quad:
        a.li(8,A(0x2FEB38));a.lw(8,8);a.branch(4,8,0,'done');a.lw(8,8)
        a.addiu(9,0,3);a.branch(5,8,9,'done')
    a.lw(8,28,-22176); a.branch(4,8,0,'done')
    # Draw exactly in the left viewport, or the sole full-width viewport.
    a.lw(9,8,512)
    if not quad:a.branch(5,9,0,'done')
    else:a.sw(9,29,0x50);a.lw(9,8,520);a.sw(9,29,0x54)
    a.lw(9,8,516); a.i(11,10,9,250); a.branch(5,10,0,'done')
    a.i(11,10,9,512); a.branch(4,10,0,'done')
    if not quad:
        a.lw(9,8,520); a.branch(5,9,0,'done')
        a.lw(9,8,524); a.addiu(10,0,SCISSOR_Y1); a.branch(5,9,10,'done')
    a.li(16,CONTROL); a.lw(17,16,12); a.li(18,EVENTS); a.move(19,0)
    a.label('event'); a.lw(8,18,28); a.branch(4,8,0,'next')
    a.lw(8,18); a.r(0x23,8,17,8); a.i(11,9,8,LIFETIME); a.branch(4,9,0,'next')
    a.addiu(20,0,128); a.i(11,9,8,LIFETIME-FADE); a.branch(5,9,0,'alpha')
    a.addiu(9,0,LIFETIME); a.r(0x23,20,9,8); a.r(0,20,0,20,2)
    a.label('alpha'); a.r(0,20,0,20,24)
    a.lw(21,18,8); a.i(11,8,21,161); a.branch(4,8,0,'unknown')
    a.r(0,21,0,21,7); a.li(8,NAMES); a.r(0x2D,21,21,8); a.jump('line1')
    a.label('unknown'); a.li(21,UNKNOWN)
    a.label('line1'); a.lw(22,18,24); a.call('line')
    a.lw(21,18,4); a.i(11,8,21,161); a.branch(4,8,0,'victim_unknown')
    a.r(0,21,0,21,7); a.li(8,NAMES+64); a.r(0x2D,21,21,8); a.jump('line2')
    a.label('victim_unknown'); a.li(21,UNKNOWN+32)
    a.label('line2'); a.lw(22,18,20); a.addiu(19,19,9); a.call('line'); a.addiu(19,19,-9)
    a.lw(8,16,24); a.addiu(8,8,1); a.sw(8,16,24)
    a.label('next'); a.addiu(18,18,32); a.addiu(19,19,22); a.addiu(8,0,(1 if quad else MAX_EVENTS)*22)
    a.branch(5,19,8,'event'); a.jump('done')
    a.label('line'); a.i(63,31,29,0x48)
    # Offset black shadow, followed by unobtrusive team-colored text.
    for shadow in (True,False):
        a.move(4,21); a.li(5,(1792+8+int(shadow))*16)
        a.addiu(6,19,Y_ORIGIN+screen_y(106)+int(shadow)); a.r(0,6,0,6,4)
        if quad:
            import multiview_layout
            a.lw(8,29,0x50);a.r(0,8,0,8,4);a.r(0x21,5,5,8)
            a.lw(8,29,0x54);a.addiu(8,8,screen_y(multiview_layout.FEED_Y)-screen_y(106));a.r(0,8,0,8,4);a.r(0x21,6,6,8)
        if shadow:a.move(7,20)
        else:
            a.li(7,0xEEEEEE); a.i(11,8,22,2); a.branch(4,8,0,'color_ready')
            a.r(0,8,0,22,2); a.r(0x2D,8,8,16); a.lw(7,8,0x80)
            a.label('color_ready'); a.r(0x25,7,7,20)
        a.call(SMALL_TEXT if quad else TEXT)
    a.i(55,31,29,0x48); a.jr()
    a.label('done')
    for i,r in enumerate(tuple(range(16,24))+(31,)):a.i(55,r,29,i*8)
    a.addiu(29,29,0x60); a.jr(); result=a.finish(); assert len(result)<TEXT-DRAW; return result


def payloads(native):
    original=native(DAMAGE_ENTRY,8)
    assert struct.unpack('<2I',original)==(0x27BDFFB0,0xFFB00000)
    return [(GATE,gate_code()),(ROW,row_code()),(IDENTIFY,identify_code()),(RECORD,record_code()),
            (DAMAGE,damage_code()),(DAMAGE_NATIVE,original+struct.pack('<2I',(2<<26)|((DAMAGE_ENTRY+8)>>2),0)),
            (TICK,tick_code()),(WORLD,world_code()),(DRAW,draw_code()),(TEXT,text_code()),
            (TEMPLATE,bars.sprite_template()[:112]),(FONT,font_data()),
            (UNKNOWN,localization.slot('DEFEATED',32)+b'> '+localization.guest('UNKNOWN FIGHTER')+b'\0')]


def build_memory(ram,config=None,source='<offline-memory>',names=None):
    if len(ram)!=0x8000000:raise ValueError('Requires128MiB captured EE RAM')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if count not in ACTOR_COUNTS or u(core.MODE)!=1 or u(core.MODE+8)!=manager or u(core.MODE+12)!=count:
        raise ValueError('Requires an active captured 2v2 or3v3 match')
    if not 0x100000<=manager<len(ram)-16 or u(manager)!=2:raise ValueError('Invalid native manager')
    if any(ram[GATE:END]):raise ValueError('Kill-feed reservation occupied')
    _,_,native=elf_reader(elf_path(ROOT))
    if ram[DAMAGE_ENTRY:DAMAGE_ENTRY+8]!=native(DAMAGE_ENTRY,8):raise ValueError('Damage entry changed')
    if ram[TICK_CALL:TICK_CALL+8]!=native(TICK_CALL,8):raise ValueError('Deferred damage frame call changed')
    if u(TICK_CALL)!=(3<<26)|(A(0x1CF220)>>2):raise ValueError('Unexpected native frame call')
    if ram[bars.CODE:bars.CODE+len(bars.wrapper())]!=bars.wrapper():raise ValueError('Install after reviewed health bars')
    for hook in bars.HOOKS:
        if u(hook)!=(3<<26)|(bars.CODE>>2) or u(hook+4)!=0:raise ValueError('World render chain changed')
    for pc in ATTRIBUTION:
        if ram[pc-16:pc]!=native(pc-16,16) or u(pc-8)!=(3<<26)|(DAMAGE_ENTRY>>2):
            raise ValueError(f'Attacker attribution callsite changed:{pc-8:X}')
    if names is None:
        from character_names import character_table
        names={i:row['name'] for i,row in character_table().items()}
        if set(names)!=set(range(161)):
            raise ValueError('Verified English character metadata for all161 native IDs is required')
    if 'names' in names:names=names['names']
    name_bytes,name_map=name_data(names)
    control=bytearray(0x100);struct.pack_into('<3I',control,0,1,manager,count)
    struct.pack_into('<2I',control,0x80,*(c&0xFFFFFF for c in bars.COLORS))
    actors=[]
    for i in range(count):
        actor=u(core.POINTERS+4*i)
        if not 0x100000<=actor<len(ram)-0x1600 or u(actor)!=i or u(actor+8)!=i&1:
            raise ValueError('Captured physical actor mismatch')
        slot=u(actor+0x994)
        if slot>=5:raise ValueError('Invalid active HP row')
        struct.pack_into('<I',control,0x40+4*i,int(struct.unpack_from('<i',ram,actor+0x9E4+164*slot)[0]<=0))
        actors.append(actor)
    pieces=(payloads(native)+[(CONTROL,bytes(control)),(EVENTS,bytes(MAX_EVENTS*32)),(NAMES,name_bytes),
       (DAMAGE_ENTRY,struct.pack('<2I',(2<<26)|(DAMAGE>>2),0)),
       (TICK_CALL,struct.pack('<I',(3<<26)|(TICK>>2)))]+
       [(h,struct.pack('<I',(3<<26)|(WORLD>>2))) for h in bars.HOOKS])
    blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex()) for p,d in pieces]
    spans=sorted((b['address'],b['address']+len(bytes.fromhex(b['data_hex']))) for b in blocks)
    assert all(end<=p for (_,end),(p,_) in zip(spans,spans[1:]))
    return dict(serial=SERIAL,crc=CRC,source=str(Path(source).resolve()),blocks=blocks,
        control=CONTROL,events=EVENTS,actors=actors,character_names=name_map,
        status='NATIVE LEFT-SIDE KILL FEED; LIVE VISUAL CHECK REQUIRED',
        telemetry=dict(game_updates=CONTROL+12,deaths=CONTROL+16,unknown_killers=CONTROL+20,drawn_entries=CONTROL+24),
        limitations=['Only audited damage callers receive killer attribution; all other deaths say DEFEATED.',
          'Latest four deaths remain for five game seconds, fading during the final second.',
          'The shared feed appears once in the left viewport in split-screen.',
          'Names use a compact uppercase 5x7 glyph font; invalid runtime IDs display UNKNOWN FIGHTER.'])


def build(source,names=None):return build_memory(read_ram(source),source=source,names=names)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True,type=Path)
    p.add_argument('--names',type=Path);p.add_argument('--out',required=True,type=Path);x=p.parse_args()
    result=build(x.source,json.loads(x.names.read_text()) if x.names else None)
    x.out.write_text(json.dumps(result,indent=2)+'\n');print(f'{x.out}: {len(result["blocks"])} guarded blocks')
