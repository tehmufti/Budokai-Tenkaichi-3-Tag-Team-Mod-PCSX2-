"""Match the active tag director clock to its native effect owners.

An unrelated transformation's manager stop is not a per-model effect pause.
Observe the three captured models instead; never rewrite another action's
pause flags or defer its reload. A partially paused group cancels safely.
"""
from prototype import Assembler
from native_map import A
import tag_team_rush as tag
import tag_rush_camera as camera
import fresh_team_combat as core
import fusion_partner_lifecycle as full
import native_preparation as preparation
import team_start_gate as start
import battle_mode_policy as modes

CHECK, END = 0x06D0E200, 0x06D0F000
HOLD, ADVANCE, CANCEL = 0, 1, 2


def code():
    import tag_rush_scene as scene
    a=Assembler(CHECK);tag.save(a)
    camera.emit_active(a,'c201')
    a.lw(11,8,tag.C['manager']);full.pointer(a,11,0x300,'c202')
    core.gate(a,'c203')
    a.li(16,tag.CONTROL);a.lw(17,16,tag.C['count'])
    a.lw(8,16,tag.C['ready']);a.branch(4,8,0,'c204')
    a.li(8,modes.CONTROL);a.lw(8,8,12);a.li(9,modes.FFA);a.branch(4,8,9,'c205')
    a.li(8,preparation.CONTROL);a.lw(9,8);a.li(10,preparation.MAGIC)
    a.branch(5,9,10,'not_quiet');a.lw(9,8,16);a.branch(4,9,0,'not_quiet')
    a.lw(9,8,24);a.lw(10,16,tag.C['manager']);a.branch(5,9,10,'c206');a.jump('hold')
    a.label('not_quiet');a.li(8,A(0x333700));a.lw(8,8);a.branch(5,8,0,'hold')
    a.li(8,start.CONTROL);a.lw(8,8);a.branch(5,8,0,'hold')
    a.li(8,A(0x3337C0));a.lw(8,8);a.li(9,1);a.branch(5,8,9,'hold')
    # A stage replacement can leave the old three models published briefly.
    # That is distinct from a per-actor pause or an unrelated manager stop.
    a.li(8,A(0x3337B8));a.lw(8,8);a.i(12,8,8,0x2000);a.branch(5,8,0,'c207')
    a.li(8,scene.STATE);a.lw(8,8);a.li(9,scene.SCENE_MAGIC);a.branch(5,8,9,'c208')
    a.move(18,0);a.move(20,0);a.li(21,scene.ROWS)
    a.label('role');a.lw(10,21,scene.R['index']);a.r(0x2B,9,10,17);a.branch(4,9,0,'c209')
    a.lw(10,21,scene.R['model_id']);a.i(11,9,10,12);a.branch(4,9,0,'c210')
    scene.identity(a,21,'c211','clock')
    a.lw(8,23,8);a.li(9,1);a.branch(5,8,9,'c212')
    # This is the exact native beam predicate: model owner pause plus the
    # native global0x100 pause. Caller-scoped tag holds do not affect it.
    a.lw(4,21,scene.R['model_id']);a.call(A(0x12CE88));a.branch(4,2,0,'next')
    a.addiu(18,18,1)
    a.label('next');a.addiu(20,20,1);a.addiu(21,21,scene.STRIDE);a.li(8,3);a.branch(5,20,8,'role')
    a.branch(4,18,0,'advance');a.li(8,3);a.branch(4,18,8,'hold')
    # A victim-only hit stop would otherwise let both source effects run
    # ahead. Retire this attack without its finishing hit; do not fake a
    # common pause by editing native actor or global cinematic state.
    a.li(8,213)
    # Diagnostics only: the cancel reason in tag CONTROL end_check.
    a.label('cancel_mark');a.li(9,tag.CONTROL+tag.C['end_check']);a.sw(8,9)
    a.label('cancel');a.li(2,CANCEL);a.jump('done')
    for k in range(201,213):a.label(f'c{k}');a.li(8,k);a.jump('cancel_mark')
    a.label('hold');a.li(2,HOLD);a.jump('done')
    a.label('advance');a.li(2,ADVANCE)
    a.label('done');tag.restore(a,2);a.jr()
    data=a.finish();assert CHECK+len(data)<=END;return data


def pieces():return [(CHECK,code())]
