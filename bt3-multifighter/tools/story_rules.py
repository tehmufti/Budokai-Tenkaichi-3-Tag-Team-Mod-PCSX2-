"""Scenario-only combat rules. Damage provenance comes from native hit flags.

In particular, 0x2000000 is the ultimate damage category, including delayed
projectiles. A previous animation/action is never used to label a later hit.
"""
import struct
from prototype import Assembler
from native_map import A
import guest_killfeed as abi
import fresh_team_combat as core

BASE, END = 0x06990000, 0x069A0000
DAMAGE, FORMS, CONTROL = BASE, BASE+0x4000, BASE+0xF000
MAGIC = 0x53525232
LAST_INVALID = CONTROL+0x100
STATS, STATS_STRIDE = CONTROL+0x200, 16  # damage/defense per mille, invulnerability, nonlethal KO floor


def stats_data(mission):
    import story_runtime as story
    from battle_mode_policy import ENGINE_ACTORS
    rows=[(1000,1000,0,0) for _ in range(ENGINE_ACTORS)]
    for f in mission['fighters']:
        s=f.get('stats',{})
        rows[story.physical(f)]=(round(s.get('damage',1)*1000),round(s.get('defense',1)*1000),
            int(s.get('invulnerable',False)),int(s.get('cannot_be_defeated',False)))
    return b''.join(struct.pack('<4I',*r) for r in rows)


def scale_integer(a,value,factor,denominator,tag):
    """Exact floor(value * factor / denominator), without a 32-bit product overflow."""
    a.r(0x1B,0,value,denominator);a.r(0x12,10,0,0);a.r(0x10,11,0,0)
    a.r(0x19,0,10,factor);a.r(0x12,10,0,0)
    a.r(0x19,0,11,factor);a.r(0x12,11,0,0)
    a.r(0x1B,0,11,denominator);a.r(0x12,11,0,0);a.r(0x21,value,10,11)


def damage_code(mission):
    """a0 points to the outer protection hook's saved ABI frame."""
    import story_runtime as story
    ids={f['id']:story.physical(f) for f in mission['fighters']}
    a=Assembler(DAMAGE);abi.prologue(a);a.move(21,4)
    a.r(0x10,8,0,0);a.r(0x12,9,0,0);a.i(63,8,29,0xF0);a.i(63,9,29,0xF8)
    a.li(8,CONTROL);a.lw(8,8);a.li(9,MAGIC);a.branch(5,8,9,'done')
    story.guard(a,'done',allow_alias=True)
    a.lw(22,21,abi.REG_OFFSET[4])  # victim, never an aliased side number
    a.move(23,0);a.lw(8,21,abi.RETURN)
    for i,(pc,reg) in enumerate(sorted(abi.ATTRIBUTION.items())):
        a.li(9,pc);a.branch(5,8,9,f'caller{i}')
        a.lw(23,21,abi.REG_OFFSET[reg]);a.jump('identified');a.label(f'caller{i}')
    a.label('identified')
    a.lw(24,21,abi.REG_OFFSET[5]);a.branch(6,24,0,'rules')
    a.li(8,1000000);a.r(0x2B,9,8,24);a.branch(4,9,0,'bounded_damage');a.move(24,8);a.label('bounded_damage')
    for f in mission['fighters']:
        index=ids[f['id']];nxt=f'scale_attacker{index}'
        a.li(8,core.POINTERS+4*index);a.lw(8,8);a.branch(5,8,23,nxt)
        story.current(a,index,'rules');a.li(8,STATS+STATS_STRIDE*index);a.lw(9,8,4);a.branch(4,9,0,'defense');a.lw(12,8);a.li(13,1000)
        scale_integer(a,24,12,13,nxt);a.jump('defense');a.label(nxt)
    a.label('defense')
    for f in mission['fighters']:
        index=ids[f['id']];nxt=f'scale_victim{index}'
        a.li(8,core.POINTERS+4*index);a.lw(8,8);a.branch(5,8,22,nxt)
        story.current(a,index,'rules');a.li(8,STATS+STATS_STRIDE*index);a.lw(9,8,8);a.branch(4,9,0,nxt+'armor')
        a.move(24,0);a.jump('scaled');a.label(nxt+'armor')
        a.lw(13,8,4);a.branch(4,13,0,'scaled');a.li(12,1000);scale_integer(a,24,12,13,nxt)
        a.li(8,STATS+STATS_STRIDE*index);a.lw(9,8,12);a.branch(4,9,0,'scaled')
        a.lw(9,21,abi.REG_OFFSET[6]);a.i(13,9,9,0x400);a.i(63,9,21,abi.REG_OFFSET[6]);a.jump('scaled');a.label(nxt)
    a.label('scaled');a.li(8,1000000);a.r(0x2B,9,8,24);a.branch(4,9,0,'store_damage');a.move(24,8)
    a.label('store_damage');a.i(63,24,21,abi.REG_OFFSET[5]);a.label('rules')
    for i,rule in enumerate(mission.get('finish_rules',[])):
        nxt=f'r{i}next';bad=f'r{i}bad';good=f'r{i}good'
        index=ids[rule['victim']]
        a.li(8,core.POINTERS+4*index);a.lw(8,8);a.branch(5,8,22,nxt)
        story.current(a,index,'done');a.lw(8,19);a.branch(6,8,0,'done')
        a.li(8,core.POINTERS+4*ids[rule['attacker']]);a.lw(8,8);a.branch(5,8,23,bad)
        if rule['attack']!='any':
            a.lw(8,21,abi.REG_OFFSET[6]);a.li(9,0x2000000 if rule['attack']=='ultimate' else 0x3800000)
            a.r(0x24,8,8,9);a.branch(4,8,0,bad)
        if 'form' in rule:
            story.current(a,ids[rule['attacker']],bad)
            a.lw(8,20,12);a.li(9,rule['form']);a.branch(5,8,9,bad)
        a.jump(good);a.label(bad)
        a.li(8,LAST_INVALID+4*index);a.addiu(9,0,i+1);a.sw(9,8)
        if rule['otherwise']=='hold_at_1_hp':
            # Native 1CE630 applies this AFTER defense/armor/rounding, before
            # HP is stored or death/kill-feed hooks can observe a KO.
            a.lw(8,21,abi.REG_OFFSET[6]);a.i(13,8,8,0x400);a.i(63,8,21,abi.REG_OFFSET[6])
        a.jump('done');a.label(good)
        a.li(8,LAST_INVALID+4*index);a.sw(0,8);a.jump('done');a.label(nxt)
    a.label('done');a.i(55,8,29,0xF0);a.i(55,9,29,0xF8);a.r(0x11,0,8,0);a.r(0x13,0,9,0);abi.epilogue(a)
    data=a.finish()
    if len(data)>FORMS-DAMAGE:raise ValueError('Too many finishing rules for this adapter')
    return data


def forms_code(mission):
    """a0 actor, a1 native destination slot; v0=1 refuses ordinary forms."""
    import story_runtime as story
    a=Assembler(FORMS);abi.prologue(a);a.i(63,0,29,abi.REG_OFFSET[2])
    story.guard(a,'done')
    for f in mission['fighters']:
        t=f.get('transformations',{})
        if not t:continue
        index=story.physical(f);nxt=f'f{index}'
        a.li(8,core.POINTERS+4*index);a.lw(8,8);a.branch(5,8,4,nxt)
        if not t.get('enabled',True):a.jump('deny')
        if 'limit' in t:
            a.li(8,story.ACTORS+0x200+index*8+4);a.lw(8,8);a.li(9,t['limit'])
            a.r(0x2B,8,8,9);a.branch(4,8,0,'deny')
        if 'allowed_forms' in t:
            a.i(11,8,5,4);a.branch(4,8,0,'deny')
            story.current(a,index,'deny');a.lw(8,20,0x91C)
            a.li(9,0x100000);a.r(0x2B,9,8,9);a.branch(5,9,0,'deny')
            a.li(9,0x8000000-156);a.r(0x2B,9,9,8);a.branch(5,9,0,'deny')
            a.r(0x21,8,8,5);a.i(36,8,8,152)
            for form in t['allowed_forms']:a.li(9,form);a.branch(4,8,9,'done')
            a.jump('deny')
        a.jump('done');a.label(nxt)
    a.jump('done');a.label('deny');a.addiu(8,0,1);a.i(63,8,29,abi.REG_OFFSET[2])
    a.label('done');abi.epilogue(a)
    data=a.finish()
    if len(data)>CONTROL-FORMS:raise ValueError('Scenario form restrictions exceed adapter memory')
    return data


def emit_outcomes(a,mission,done='done'):
    import story_runtime as story
    ids={f['id']:story.physical(f) for f in mission['fighters']}
    events={e['id']:i for i,e in enumerate(mission['events'])}
    a.lw(8,16,96);a.branch(5,8,0,done)
    for i,rule in enumerate(mission.get('finish_rules',[])):
        if rule['otherwise']!='fail':continue
        nxt=f'finish{i}';index=ids[rule['victim']]
        a.li(8,LAST_INVALID+4*index);a.lw(8,8);a.li(9,i+1);a.branch(5,8,9,nxt)
        story.current(a,index,nxt);a.lw(8,19);a.branch(7,8,0,nxt)
        a.li(8,i+1);a.sw(8,16,100);a.jump('scenario_fail');a.label(nxt)
    for key,label in (('fail_when','scenario_fail'),('win_when','scenario_win')):
        if mission.get(key):
            story.condition(a,mission[key],label,key+'next',ids,events,key)
            a.label(key+'next')
    a.jump('outcomes_done')
    a.label('scenario_fail');a.li(8,3-mission.get('player_team',1));a.sw(8,16,96);a.jump(done)
    a.label('scenario_win');a.li(8,mission.get('player_team',1));a.sw(8,16,96);a.jump(done)
    a.label('outcomes_done')


def blocks(ram,mission):
    if any(ram[BASE:END]):raise ValueError('Scenario rules workspace is occupied')
    import story_cast
    return [(DAMAGE,damage_code(mission)),(FORMS,forms_code(mission)),(CONTROL,struct.pack('<I',MAGIC)),
            (STATS,stats_data(mission)),*story_cast.blocks()]
