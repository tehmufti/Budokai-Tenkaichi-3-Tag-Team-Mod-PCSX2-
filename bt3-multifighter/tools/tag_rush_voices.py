"""Staggered own-character exertion voices for a local tag attack.

The native beam-struggle handler uses category20 through1DC738. Its loaded
manager+40 table supplies the character-voice line.265E38 selects the current
character/language; extra_voice safely arbitrates the two physical streams.
No borrowed donor line, forced stop, or extra actor bank arithmetic is used.
"""
from prototype import Assembler
from native_map import A, ACTOR_HZ
import tag_team_rush as tag
import tag_rush_camera as camera
import fusion_partner_lifecycle as full
import fresh_team_combat as core
import extra_voice

BASE, RESET, TICK = 0x06D7E000, 0x06D7E000, 0x06D7E400
STATE, END = 0x06D7FC00, 0x06D80000
MAGIC=0x54564331
C=dict(magic=0,manager=4,count=8,next_role=12,settle=16,played=20,last_role=24,last_character=28,last_line=32)
PLAY=A(0x265E38);IDLE=A(0x265B48)


def reset_code():
    a=Assembler(RESET);tag.save(a);a.li(16,STATE);a.sw(0,16,C['magic']);camera.emit_active(a,'done')
    for off in (C['manager'],C['count']):a.lw(9,8,off);a.sw(9,16,off)
    for off in (C['next_role'],C['settle'],C['played']):a.sw(0,16,off)
    a.li(9,MAGIC);a.sw(9,16,C['magic'])
    a.label('done');tag.restore(a);a.jr();b=a.finish();assert len(b)<=TICK-RESET;return b


def tick_code():
    import tag_rush_scene as scene
    a=Assembler(TICK);tag.save(a)
    a.li(8,A(0x333700));a.lw(8,8);a.branch(5,8,0,'done');camera.emit_active(a,'done')
    a.li(16,STATE);a.lw(9,16);a.li(10,MAGIC);a.branch(5,9,10,'done')
    for off in (C['manager'],C['count']):a.lw(9,16,off);a.lw(10,8,off);a.branch(5,9,10,'done')
    a.lw(17,16,C['next_role']);a.i(11,9,17,2);a.branch(4,9,0,'done')
    # An asynchronous stream may remain idle for its first tick. Never let the
    # partner replace the just-submitted first line; allow one second to start.
    a.lw(9,16,C['settle']);a.branch(4,9,0,'settled');a.addiu(9,9,-1);a.sw(9,16,C['settle']);a.jump('done')
    a.label('settled');a.li(18,scene.STATE);a.lw(9,18);a.li(10,scene.SCENE_MAGIC);a.branch(5,9,10,'done')
    a.lw(9,18,scene.S['retiring']);a.branch(5,9,0,'done')
    a.lw(9,18,scene.S['phase']);a.i(11,10,9,12);a.branch(4,10,0,'done')
    a.branch(4,17,0,'leader');a.i(11,10,9,2);a.branch(5,10,0,'done');a.jump('scheduled')
    a.label('leader');a.branch(5,9,0,'scheduled');a.lw(9,18,scene.S['ticks']);a.i(11,10,9,max(1,ACTOR_HZ//5));a.branch(5,10,0,'done')
    a.label('scheduled')
    # The physical owner route is allowed only with the actual extra-voice
    # arbiter installed for this manager/count. Never dispatch owner+2 SFX.
    a.li(19,extra_voice.CONTROL);a.lw(9,19);a.li(10,extra_voice.MAGIC);a.branch(5,9,10,'done')
    for off in (4,8):a.lw(9,19,off);a.lw(10,16,off);a.branch(5,9,10,'done')
    a.li(8,extra_voice.PLAY_ENTRY);a.lw(9,8);a.li(10,(2<<26)|(extra_voice.PLAY>>2));a.branch(5,9,10,'done')
    a.lw(9,8,4);a.branch(5,9,0,'done')
    for channel in (4,5):
        a.li(20,channel);extra_voice.blockers(a,20,'done');a.move(4,20);a.call(IDLE);a.branch(4,2,0,'done')
    a.r(0,8,0,17,9);a.li(9,scene.ROWS);a.r(0x21,21,8,9)
    scene.identity(a,21,'done','voice');a.lw(9,23,8);a.li(10,1);a.branch(5,9,10,'done')
    a.lw(22,21,scene.R['index']);a.lw(23,21,scene.R['character'])
    a.lw(8,16,C['manager']);a.lw(10,8,40);full.pointer(a,10,21*8,'done')
    a.i(37,18,10,20*8);a.i(37,9,10,20*8+2)
    a.i(11,8,18,100);a.branch(4,8,0,'done');a.branch(4,9,0,'done');a.r(0x21,9,9,18);a.i(11,8,9,101);a.branch(4,8,0,'done')
    a.move(4,22);a.move(5,23);a.move(6,18);a.li(7,100);a.move(8,0);a.call(PLAY)
    a.sw(22,16,C['last_role']);a.sw(23,16,C['last_character']);a.sw(18,16,C['last_line'])
    a.addiu(17,17,1);a.sw(17,16,C['next_role']);a.sw(17,16,C['played']);a.li(9,ACTOR_HZ);a.sw(9,16,C['settle'])
    a.label('done');tag.restore(a);a.jr();b=a.finish();assert len(b)<=STATE-TICK;return b


def pieces():
    return [(RESET,reset_code()),(TICK,tick_code()),(STATE,bytes(END-STATE))]
