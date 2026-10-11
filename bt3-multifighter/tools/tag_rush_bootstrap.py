"""One-shot guest initialization before a local tag rush can accept input.

The host installs inert data and hooks. Only the game thread may parse native
FX descriptors and publish ready after both private arenas have receipts.
Failures disable this feature, not the battle, and never retry an allocation.
"""
import struct
from prototype import Assembler
from native_map import A, ACTOR_HZ
import tag_team_rush as tag
import tag_rush_effects as effects
import fresh_team_combat as core
import fusion_partner_lifecycle as full
import battle_mode_policy as modes
import team_start_gate as start

CODE, END = 0x06D0F800, 0x06D10000
STATE, STATE_END, MAGIC = 0x06D0E100, 0x06D0E200, 0x54424931
WAITING, READY, FAILED = 0, 2, 3
S = dict(magic=0,manager=4,count=8,phase=12,age=16,error=20,pool=24)
TIMEOUT = 5*ACTOR_HZ
NETPLAY_CONTROL, NETPLAY_MAGIC = 0x07B01000, 0x4E504631


def code(beam_audio=False):
    a=Assembler(CODE);tag.save(a);a.li(16,STATE);a.li(17,tag.CONTROL)
    a.lw(8,16,S['magic']);a.li(9,MAGIC);a.branch(5,8,9,'done')
    a.lw(8,17,tag.C['magic']);a.li(9,tag.MAGIC);a.branch(5,8,9,'done')
    a.lw(8,16,S['phase']);a.li(9,FAILED);a.branch(4,8,9,'disarm')
    # A new battle or model-pool replacement requires a fresh preparation.
    # Never write through actors or a saved native pool while detecting this.
    a.lw(18,16,S['manager']);a.lw(8,17,tag.C['manager']);a.branch(5,8,18,'identity')
    full.pointer(a,18,0x1000,'identity')
    a.lw(8,28,-22364);a.branch(5,8,18,'identity')
    a.li(8,core.MODE);a.lw(9,8,8);a.branch(5,9,18,'identity')
    a.lw(19,16,S['count']);a.lw(9,17,tag.C['count']);a.branch(5,9,19,'identity')
    modes.emit_actor_count(a,19,'identity',scratch=9)
    for off in (4,12):a.lw(9,8,off);a.branch(5,9,19,'identity')
    a.li(8,NETPLAY_CONTROL);a.lw(9,8);a.li(10,NETPLAY_MAGIC);a.branch(5,9,10,'offline')
    a.lw(9,8,4);a.branch(5,9,0,'online')
    a.label('offline');a.lw(8,16,S['phase']);a.li(9,READY);a.branch(4,8,9,'keep_ready')
    a.branch(5,8,0,'identity')
    a.lw(8,17,tag.C['enabled']);a.branch(4,8,0,'done')
    a.sw(0,17,tag.C['ready'])
    a.lw(8,17,tag.C['active']);a.branch(5,8,0,'identity')
    a.li(8,A(0x333700));a.lw(8,8);a.branch(5,8,0,'done')
    # Intros, loading holds and native cinematics can legitimately last much
    # longer than the prerequisite budget. Count only ordinary battle updates.
    core.gate(a,'done')
    a.li(12,A(0x2FEB38));a.lw(12,12);full.pointer(a,12,0x108,'done')
    a.lw(8,12);a.li(9,3);a.branch(5,8,9,'done')
    a.li(8,start.CONTROL);a.lw(8,8);a.branch(5,8,0,'done')
    a.lw(8,18,628);a.branch(5,8,0,'done')
    a.lw(8,16,S['age']);a.addiu(8,8,1);a.sw(8,16,S['age'])
    a.li(9,TIMEOUT);a.r(0x2B,9,9,8);a.branch(5,9,0,'timeout')
    if beam_audio:
        import tag_rush_beam_audio
        a.call(tag_rush_beam_audio.INIT);a.branch(4,2,0,'done')
        a.i(10,8,2,0);a.branch(5,8,0,'bad_audio')
    a.li(8,effects.CONTROL);a.lw(8,8,effects.C['init_status'])
    a.branch(5,8,0,'bad_init')
    a.call(effects.INIT);a.branch(4,2,0,'init_declined')
    a.jump('receipts')
    a.label('init_declined');a.li(8,effects.CONTROL);a.lw(8,8,effects.C['init_status'])
    a.branch(4,8,0,'done');a.jump('bad_init')
    a.label('keep_ready')
    # A scene may disarm itself after failed teardown. Do not rearm it just
    # because the original descriptor receipts still exist.
    a.lw(8,17,tag.C['ready']);a.branch(4,8,0,'done')
    a.lw(8,16,S['pool']);a.lw(9,28,effects.NATIVE_POOL_OFFSET);a.branch(5,8,9,'bad_init')
    a.label('receipts');a.li(20,effects.CONTROL)
    for off,value in ((effects.C['magic'],effects.MAGIC),(effects.C['ready'],1),(effects.C['init_status'],2)):
        a.lw(8,20,off);a.li(9,value);a.branch(5,8,9,'bad_init')
    a.lw(8,20,effects.C['manager']);a.branch(5,8,18,'bad_init')
    a.lw(8,20,effects.C['count']);a.branch(5,8,19,'bad_init')
    a.lw(21,28,effects.NATIVE_POOL_OFFSET);full.pointer(a,21,24,'bad_init')
    a.lw(8,20,effects.C['pool']);a.branch(5,8,21,'bad_init')
    for slot in range(2):
        a.li(22,effects.ROWS+slot*effects.STRIDE)
        a.lw(8,22,effects.R['prepared']);a.li(9,effects.PREPARED);a.branch(5,8,9,'bad_init')
        for off,expected in ((effects.HEADER+36,effects.META),(effects.DESC+796,effects.HEADER)):
            a.lw(8,22,off);a.addiu(9,22,expected);a.branch(5,8,9,'bad_init')
    a.sw(21,16,S['pool']);a.li(8,READY);a.sw(8,16,S['phase'])
    a.li(8,1);a.sw(8,17,tag.C['ready']);a.jump('done')
    a.label('identity');a.li(8,1);a.jump('fail')
    a.label('online');a.li(8,2);a.jump('fail')
    a.label('timeout');a.li(8,3);a.jump('fail')
    if beam_audio:a.label('bad_audio');a.li(8,5);a.jump('fail')
    a.label('bad_init');a.li(8,4)
    a.label('fail');a.sw(8,16,S['error']);a.li(8,FAILED);a.sw(8,16,S['phase'])
    a.label('disarm');a.sw(0,17,tag.C['ready'])
    a.label('done');tag.restore(a);a.jr()
    data=a.finish();assert CODE+len(data)<=END;return data


def state(manager,count):
    data=bytearray(STATE_END-STATE)
    struct.pack_into('<3I',data,0,MAGIC,manager,count)
    return bytes(data)


def pieces(manager,count,beam_audio=False):
    return [(CODE,code(beam_audio)),(STATE,state(manager,count))]
