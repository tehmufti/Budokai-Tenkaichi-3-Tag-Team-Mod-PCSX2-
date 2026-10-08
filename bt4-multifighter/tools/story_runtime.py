"""Compile a mission into the prepared match's guest update loop.

The runtime is independent of host polling, wall-clock time and save slots.
Native form commands still use the existing checked resource loader. Ordinary
matches install nothing. A stopped/failed event releases its result hold.
"""
import math
import struct
import copy

from native_map import A, ACTOR_HZ, CRC, SERIAL
from prototype import Assembler
import story_missions as doc
import fresh_team_combat as core
import team_participation as part
import team_defeat as defeat
import guest_killfeed as abi
import battle_mode_policy as modes

BASE, END = 0x06BE0000, 0x06C00000
FRAME, ORIGINAL, RESULT, CHANCE = BASE, BASE+0xA000, BASE+0xA100, BASE+0xAA00
ARRIVAL = BASE+0x9000
CPU_INIT, CHANCE_NATIVE = BASE+0xB800, BASE+0xB700
CONTACT, COMMAND, CONTACT_NATIVE = BASE+0xC500, BASE+0xC900, BASE+0xCD00
DRAW, DRAW_NATIVE, DAMAGE = BASE+0xD000, BASE+0xE800, BASE+0xE900
DESTRUCTION, DESTRUCTION_NATIVE = BASE+0xEE00, BASE+0xEFC0
STRINGS = BASE+0x1C100
CONTROL, EVENTS, ACTORS = BASE+0xF000, BASE+0xF100, BASE+0xFA00
MAGIC = 0x53545231
FRESH = 0xFFFFFFFE  # CONTROL+52 before the first story frame: that frame is skipped (see frame())
EVENT_STRIDE = 32  # state, action, started, submitted, completed, delay-started, reserved[2]
DOCUMENT = BASE+0x10000
DESTRUCTION_COUNT, DESTRUCTION_STAGE = CONTROL+104, CONTROL+108


def jump(target): return struct.pack('<2I', (2 << 26) | (target >> 2), 0)


def physical(f): return 2*(f['slot']-1)+f['team']-1


def adapter_check(mission, *, capacity=None):
    d = doc.validate(mission)
    family='bt4' if SERIAL=='SLUS-21978' else 'bt3'
    doc.require(d.get('game_family',family)==family,
                f'This mission uses {d.get("game_family",family).upper()} character IDs; open it in that game\'s Workbench')
    capacity = modes.TEAM_CAPACITY if capacity is None else capacity
    for f in d['fighters']:
        doc.require(f['slot'] <= capacity, f"{f['id']}: this runtime currently supports {capacity} slots per side")
        doc.require(not f['reserve'] or f['slot'] > 1, 'The native first fighter on each team must start active')
    # Stage selection is supplied by scenario_menu when launched in game;
    # the manual Workbench route still validates the selected arena below.
    return d


def validate_selection(mission, selection, ram, humans=1, assignment=None):
    d=adapter_check(mission);validate_compilation(d)
    rows={r['physical_id']:r for r in selection['roster'] if r['participating']}
    ids={physical(f):f for f in d['fighters']}
    if rows.keys()!=ids.keys():raise ValueError('Select the team sizes shown in the armed story mission')
    seats=modes.human_seats('teams',humans,selection['participation_mask'],assignment)
    for index,f in ids.items():
        if (rows[index]['character'],rows[index]['costume'])!=(f['character'],f['costume']):
            raise ValueError(f"Story mission: Team {f['team']} slot {f['slot']} needs character {f['character']}, costume {f['costume']}")
        if f['reserve'] and index in seats:raise ValueError('Reserve entrances require a CPU-controlled slot')
        if f.get('copy_cpu_from'):
            source=next(physical(x) for x in d['fighters'] if x['id']==f['copy_cpu_from'])
            if index in seats or source in seats:raise ValueError('CPU copies require CPU-controlled source and destination slots')
    if d.get('stage') is not None:
        stage=struct.unpack_from('<I',ram,A(0x331DC8)+40)[0]
        if stage!=d['stage']['id']:raise ValueError(f"Choose the mission's arena: {d['stage'].get('name',d['stage']['id'])}")
    return d


def guard(a, fail, allow_alias=False):
    core.gate(a, fail)
    a.li(16, CONTROL); a.lw(8,16); a.li(9,MAGIC); a.branch(5,8,9,fail)
    a.lw(8,16,4); a.lw(9,28,-22364); a.branch(5,8,9,fail)
    a.lw(8,16,8); a.li(9,core.MODE+4); a.lw(9,9); a.branch(5,8,9,fail)
    if not allow_alias:
        a.li(8,core.PAIR+4); a.lw(8,8); a.branch(5,8,0,fail)


def current(a, index, fail):
    """s2 actor, s3 HP row, s4 model; always resolve current bodies/slots."""
    a.li(8,core.POINTERS+4*index); a.lw(18,8)
    a.li(8,ACTORS+4*index); a.lw(9,8); a.branch(5,9,18,fail)
    a.lw(8,18,0x994); a.lw(9,18,0x998); a.r(0x2B,10,8,9); a.branch(4,10,0,fail)
    a.i(11,10,9,6); a.branch(4,10,0,fail)
    a.r(0,9,0,8,7); a.r(0,10,0,8,5); a.r(0x2D,9,9,10)
    a.r(0,10,0,8,2); a.r(0x2D,9,9,10); a.r(0x2D,19,18,9); a.addiu(19,19,0x9E4)
    a.lw(8,18,12); a.i(11,9,8,modes.ENGINE_ACTORS); a.branch(4,9,0,fail)
    a.r(0,8,0,8,2); a.li(9,core.MODELS); a.r(0x2D,9,9,8); a.lw(20,9)
    # Missing models during a native reload are retried on the next update.
    a.li(9,0x100000); a.r(0x2B,8,20,9); a.branch(5,8,0,fail)
    a.li(9,0x8000000-0x1670); a.r(0x2B,8,9,20); a.branch(5,8,0,fail)
    a.lw(8,20,4); a.addiu(9,0,1); a.branch(5,8,9,fail)


def ready(a, fail, dead=False):
    if not dead:
        a.lw(8,19); a.branch(4,8,0,fail)
    a.lw(8,18,0x948)
    allowed = (216,217,218,219,220,221,222,223,224,225,230) if dead else (0,1,2,3,4,5,6,7)
    # Standing idle is action 11. Moving/attacking fighters wait for a window.
    if not dead: allowed = (11,15,17)
    label=f'idle_{len(a.words)}'
    for value in allowed:
        a.li(9,value); a.branch(4,8,9,label)
    a.jump(fail); a.label(label)
    # +964 is elapsed action time, not an input mailbox. Idle fighters
    # normally have a nonzero counter. +94C is the pending native action.
    a.lw(8,18,0x94C);a.addiu(9,0,-1);a.branch(5,8,9,fail)


def condition(a,c,ok,no,ids,event_ids,tag):
    kind=c['type']
    if kind=='not':condition(a,c['condition'],no,ok,ids,event_ids,tag+'not');return
    if kind in ('all','any'):
        children=c['conditions']
        for i,child in enumerate(children):
            more=f'{tag}_{i}'
            condition(a,child,(ok if kind=='any' or i==len(children)-1 else more),
                      (no if kind=='all' or i==len(children)-1 else more),ids,event_ids,more+'c')
            if i<len(children)-1:a.label(more)
        return
    if kind=='time':
        a.lw(8,16,12); a.li(9,math.ceil(c['seconds']*ACTOR_HZ)); a.r(0x2B,8,8,9)
        a.branch(4,8,0,ok);a.jump(no);return
    if kind in ('event','event_failed'):
        a.li(10,EVENTS+EVENT_STRIDE*event_ids[c['event']]);a.lw(8,10);a.addiu(9,0,3 if kind=='event_failed' else 2)
        a.branch(5,8,9,no)
        if c.get('delay_seconds',0):
            a.lw(8,16,12);a.lw(9,10,16);a.r(0x23,8,8,9);a.li(9,math.ceil(c['delay_seconds']*ACTOR_HZ))
            a.r(0x2B,8,8,9);a.branch(5,8,0,no)
        a.jump(ok);return
    if kind=='planet_destroyed':
        a.lw(8,16,DESTRUCTION_COUNT-CONTROL);a.li(9,c.get('occurrence',1));a.r(0x2B,8,8,9)
        a.branch(4,8,0,ok);a.jump(no);return
    index=ids[c['fighter']];current(a,index,no)
    a.lw(8,16,112);a.li(9,1<<index);a.r(0x24,8,8,9)
    if kind=='retired':a.branch(5,8,0,ok);a.jump(no);return
    a.branch(5,8,0,no)
    a.li(8,part.CONSUMED);a.lw(8,8);a.li(9,1<<index);a.r(0x24,8,8,9);a.branch(5,8,0,no)
    if kind=='defeated':a.lw(8,19);a.branch(4,8,0,ok)
    elif kind=='active':a.lw(8,19);a.branch(7,8,0,ok)
    elif kind=='transformed':
        a.li(8,ACTORS+0x200+index*8+4);a.lw(8,8);a.branch(5,8,0,ok)
    elif kind=='form':a.lw(8,20,12);a.li(9,c['character']);a.branch(4,8,9,ok)
    else:
        health_fraction(a,c['percent']);a.lw(9,19)
        a.r(0x2B,8,8,9);a.branch(5 if kind=='health_above' else 4,8,0,ok)
    a.jump(no)


def health_fraction(a,percent):
    # Divide first, retaining the remainder, so a large HP cap cannot overflow
    # a 32-bit intermediate product. Return floor(maxHP * fraction) in t0.
    a.lw(8,19,4);a.li(9,10000);a.r(0x1B,0,8,9);a.r(0x12,10,0,0);a.r(0x10,11,0,0)
    a.li(12,round(percent*100));a.r(0x19,0,10,12);a.r(0x12,10,0,0)
    a.r(0x19,0,11,12);a.r(0x12,11,0,0);a.r(0x1B,0,11,9);a.r(0x12,11,0,0)
    a.r(0x21,8,10,11)


def heal(a,percent):
    health_fraction(a,percent)
    label=f'health_{len(a.words)}';a.branch(5,8,0,label)
    a.addiu(8,0,1);a.label(label);a.sw(8,19)


def apply_stats(a,index,stats,tag):
    import story_rules
    if 'max_hp' in stats:
        a.li(8,stats['max_hp']);a.sw(8,19,4);a.lw(9,19);a.r(0x2B,10,8,9)
        a.branch(4,10,0,tag+'cap');a.sw(8,19);a.label(tag+'cap')
    if 'health_percent' in stats:heal(a,stats['health_percent'])
    if 'ki_percent' in stats:
        a.lw(8,19,16);a.li(12,round(stats['ki_percent']*100));a.li(13,10000)
        story_rules.scale_integer(a,8,12,13,tag+'ki');a.sw(8,19,12)
    if 'blast_stocks' in stats:
        a.li(8,stats['blast_stocks']);a.lw(9,19,24);a.r(0x2B,10,9,8)
        a.branch(4,10,0,tag+'stocks');a.move(8,9);a.label(tag+'stocks');a.sw(8,19,20)
    for field,offset,scale in (('damage',0,1000),('defense',4,1000),('invulnerable',8,1),('cannot_be_defeated',12,1)):
        if field in stats:
            a.li(8,story_rules.STATS+index*story_rules.STATS_STRIDE+offset);a.li(9,round(stats[field]*scale));a.sw(9,8)
    if 'difficulty' in stats:
        from ai_shadow import AI_GLOBAL
        from team_six_ai import SHADOWS
        a.li(8,stats['difficulty']);a.sw(8,19,-8)
        a.li(21,AI_GLOBAL);a.lw(22,21)
        if index>=2:a.li(8,SHADOWS[index]);a.sw(8,21)
        a.li(4,index&1);a.li(5,stats['difficulty']);a.call(A(0x1BB478));a.sw(22,21)


def arrival_code():
    """a0 actor, a1 model. Use the current arena's guarded native spawn route."""
    import spawn_placement
    a=Assembler(ARRIVAL);abi.prologue(a);a.addiu(29,29,-0x80)
    for i in range(32):a.i(57,i,29,i*4)
    a.move(18,4);a.move(20,5)
    a.li(8,spawn_placement.STAGE);a.lw(8,8);a.li(9,0x100000);a.r(0x2B,9,8,9);a.branch(5,9,0,'reject')
    a.li(9,0x8000000-64);a.r(0x2B,9,9,8);a.branch(5,9,0,'reject')
    for off in (4000,4004):
        a.lw(8,20,off);a.addiu(9,20,3936);a.branch(4,8,9,f'sphere{off}')
        a.addiu(9,20,3968);a.branch(5,8,9,'reject');a.label(f'sphere{off}')
    # This invokes stage_transition's bounded parity/footprint lookup, so a
    # reserve arriving after planet destruction uses the new map's anchors.
    # Native 1D7418 resets motion, facing, root and model together.
    a.move(4,18);a.call(A(0x1D7570))
    for address in (A(0x24E2B0),A(0x24E3F8)):
        a.move(4,20);a.call(address)
    a.move(4,20);a.move(5,0);a.call(A(0x24DC58))
    a.move(4,18);a.call(A(0x1D70E8))
    for off in range(0,48,4):a.lw(8,18,16+off);a.sw(8,18,256+off)
    a.lw(8,20,4000);a.lw(9,20,4004)
    for off in range(0,32,4):a.lw(10,8,off);a.sw(10,9,off)
    a.addiu(4,0,-1);a.addiu(5,20,2416);a.call(A(0x23FF78));a.sw(2,20,2596)
    a.addiu(8,0,1);a.jump('done');a.label('reject');a.move(8,0)
    a.label('done');a.i(63,8,29,0x80+abi.REG_OFFSET[2])
    for i in range(32):a.i(49,i,29,i*4)
    a.addiu(29,29,0x80);abi.epilogue(a);return a.finish()


def frame(mission, cpu_flags):
    import fusion_partner_lifecycle as full_abi
    ids={f['id']:physical(f) for f in mission['fighters']}
    event_ids={e['id']:i for i,e in enumerate(mission['events'])}
    import story_cinematics as cinema
    shot_links={cinema.action_key(i,k):cinema.DESCRIPTORS+cinema.STRIDE*n for n,(i,k) in enumerate((i,k) for i,e in enumerate(mission['events']) for k,x in enumerate(e['actions']) if x['type']=='cinematic')}
    voices=[]
    # The old participation hook did not call native terrain/AI functions.
    # Our added calls must not leak FPU state or upper 64-bit GPR lanes back
    # into its caller, even on an event's failure/early-return path.
    a=Assembler(FRAME);full_abi.save(a);a.call(ORIGINAL)
    a.r(16,8,0,0);a.r(18,9,0,0);a.i(63,8,29,0x2A0);a.i(63,9,29,0x2A8)
    guard(a,'done')
    import spawn_placement
    a.li(8,spawn_placement.CONTROL);a.lw(8,8);a.addiu(9,0,5);a.branch(5,8,9,'done')
    a.li(8,A(0x3337B8));a.lw(8,8);a.i(12,8,8,0x3900);a.branch(5,8,0,'done')
    a.li(8,A(0x2FEB38));a.lw(8,8);a.branch(4,8,0,'done');a.lw(8,8);a.addiu(9,0,3);a.branch(5,8,9,'done')
    a.lw(8,16,4);a.lw(8,8,628);a.branch(5,8,0,'done')
    # The prepared world already runs in phase 3 under the mod's loading cover,
    # before the native intros. Nothing authored may start, or use the clock,
    # until the player can see the match: shots there played invisibly.
    import guest_loading_screen as cover
    a.li(8,cover.CONTROL);a.lw(8,8);a.li(9,cover.MAGIC);a.branch(4,8,9,'done')
    import native_preparation
    a.li(8,native_preparation.CONTROL+44);a.lw(8,8);a.lw(9,16,52)
    a.branch(4,8,9,'done');a.sw(8,16,52)
    # The first combat frame after any break in the native frame sequence is not story time: when the
    # loading cover drops, one phase-3 frame still runs before the native intros, and an event at time 0
    # started its shot there, under the intros. After "Fight!" the next frame counts as usual.
    # build_memory arms this with FRESH; the legacy 0xFFFFFFFF start (older prepared worlds) counts at once.
    # Only the story's very start is gated: once the clock runs, pauses and native stops resume as before.
    a.lw(10,16,12);a.branch(5,10,0,'sequence_ok')
    a.addiu(11,0,-1);a.branch(4,9,11,'sequence_ok')
    a.r(0x23,10,8,9);a.addiu(11,0,1);a.branch(5,10,11,'done')
    a.label('sequence_ok')
    a.lw(8,16,32);a.branch(5,8,0,'cpu_ready');a.call(CPU_INIT)
    a.addiu(8,0,1);a.sw(8,16,32);a.label('cpu_ready')
    a.lw(8,16,12);a.addiu(8,8,1);a.sw(8,16,12)
    for f in mission['fighters']:
        index=ids[f['id']];nxt=f'observe{index}';current(a,index,nxt)
        # Native KO/corpse services may restore a leader's visibility. Retired
        # cast members remain hidden and cannot be revived or receive input.
        a.lw(8,16,112);a.li(9,1<<index);a.r(0x24,8,8,9);a.branch(4,8,0,nxt+'present')
        a.sw(0,19);a.sw(0,20,8)
        for off in (0x1278,0x127C,0x1280,0x1284):a.sw(0,18,off)
        a.jump(nxt);a.label(nxt+'present')
        a.li(8,ACTORS+0x200+8*index);a.lw(9,8);a.lw(10,20,12);a.branch(4,9,10,nxt)
        a.sw(10,8);a.lw(9,8,4);a.addiu(9,9,1);a.sw(9,8,4);a.label(nxt)
    import story_rules
    story_rules.emit_outcomes(a,mission)
    # Journal states are guest data and rewind with the world, including a
    # rematch. Completed actions can never replay merely because a host reconnects.
    for i,event in enumerate(mission['events']):
        prefix=f'e{i}';nxt=prefix+'next';run=prefix+'run';failed=prefix+'failed'
        a.li(17,EVENTS+i*EVENT_STRIDE);a.lw(8,17);a.i(11,9,8,2);a.branch(4,9,0,nxt)
        a.branch(5,8,0,run)
        condition(a,event['when'],prefix+'start',nxt,ids,event_ids,prefix+'cond')
        a.label(prefix+'start');a.addiu(8,0,1);a.sw(8,17);a.lw(8,16,12);a.sw(8,17,8)
        a.label(run);a.lw(8,16,12);a.lw(9,17,8);a.r(0x23,8,8,9)
        a.li(9,math.ceil(event['timeout_seconds']*ACTOR_HZ));a.r(0x2B,8,8,9);a.branch(4,8,0,failed)
        for k,action in enumerate(event['actions']):
            skip=f'{prefix}a{k}skip';success=f'{prefix}a{k}success'
            a.lw(8,17,4);a.li(9,k);a.branch(5,8,9,skip)
            kind=action['type']
            if kind=='wait':
                a.lw(8,17,20);a.branch(5,8,0,f'{prefix}a{k}timer')
                a.lw(8,16,12);a.addiu(8,8,1);a.sw(8,17,20)
                a.label(f'{prefix}a{k}timer');a.lw(9,16,12);a.addiu(9,9,1);a.r(0x23,8,9,8)
                a.li(9,math.ceil(action['seconds']*ACTOR_HZ));a.r(0x2B,8,8,9);a.branch(5,8,0,nxt);a.jump(success)
            elif kind=='message':
                a.li(8,(i<<8)|k);a.sw(8,16,20);a.li(8,math.ceil(action['seconds']*ACTOR_HZ))
                a.lw(9,16,12);a.r(0x21,8,8,9);a.sw(8,16,24)
                a.jump(success)
            else:
                index=ids[action['fighter']];current(a,index,nxt)
                if kind not in ('enter','despawn'):
                    a.li(8,part.CONSUMED);a.lw(8,8);a.li(9,1<<index);a.r(0x24,8,8,9);a.branch(5,8,0,nxt)
                a.li(8,CONTROL+128+index*4);a.lw(9,8);a.li(10,i+1)
                a.branch(4,9,0,f'{prefix}a{k}claim');a.branch(5,9,10,nxt)
                a.label(f'{prefix}a{k}claim');a.sw(10,8)
                if kind=='set_stats':
                    # Stat/policy changes also apply to fallen allies. A KO is
                    # not an idle window that will eventually arrive, and
                    # invulnerability must never stall a reinforcement event.
                    # Only an explicit health change can revive a fighter.
                    apply_stats(a,index,action['stats'],f'{prefix}a{k}stats');a.jump(success)
                elif kind=='take_control':
                    import story_cast
                    ready(a,nxt);a.li(4,action['player']-1);a.li(5,index);a.call(story_cast.TRANSFER)
                    a.branch(4,2,0,nxt);a.jump(success)
                elif kind=='despawn':
                    import story_cast
                    # Wait out bound scenes, but ordinary movement/attacks and
                    # a completed or falling KO do not prevent a scripted exit.
                    a.lw(8,18,0x948);a.addiu(9,8,-11);a.i(11,9,9,169);a.branch(5,9,0,f'{prefix}a{k}exit')
                    a.addiu(9,8,-216);a.i(11,9,9,15);a.branch(4,9,0,nxt)
                    a.label(f'{prefix}a{k}exit');story_cast.emit_retire(a,index,nxt,f'{prefix}a{k}retire');a.jump(success)
                elif kind=='defeat':
                    a.lw(8,19);a.branch(4,8,0,success);ready(a,nxt)
                    a.sw(0,19);a.move(4,18);a.li(5,216);a.call(A(0x1E0290));a.jump(success)
                elif kind=='target':
                    target=ids[action['target']];current(a,target,nxt);a.lw(8,19);a.branch(6,8,0,nxt)
                    import fresh_team_ai as ai
                    a.li(8,core.TABLE+4*index);a.li(9,target);a.sw(9,8)
                    a.li(8,ai.DESCRIPTORS[index]+24);a.li(9,ai.DESCRIPTORS[target]);a.sw(9,8);a.jump(success)
                elif kind=='cinematic':
                    key=cinema.action_key(i,k);a.li(21,cinema.CONTROL)
                    a.lw(8,21,32);a.li(9,key);a.branch(5,8,9,f'{prefix}a{k}newshot')
                    a.lw(8,21,12);a.li(9,3);a.branch(4,8,9,f'{prefix}a{k}shotdone')
                    a.li(9,100);a.branch(4,8,9,failed);a.jump(nxt)
                    a.label(f'{prefix}a{k}shotdone');a.sw(0,21,12);a.jump(success)
                    a.label(f'{prefix}a{k}newshot')
                    # Only a borrowed animation replaces the current action. A camera-only shot (and a
                    # frozen hold) keeps the live pose under the shared combat hold, so it must not
                    # wait for an idle window: a CPU charging ki or a moving player stalled scenes.
                    if action.get('animation') is not None and not action.get('reset_positions'):ready(a,nxt)
                    a.move(4,18);a.move(5,20);a.li(6,shot_links[key]);a.li(7,key);a.call(cinema.START);a.jump(nxt)
                elif kind=='voice':
                    address=ACTORS+0x400+12*len(voices);voices.append(action)
                    a.li(4,index);a.li(5,address);a.call(cinema.VOICE);a.jump(success)
                elif kind=='transform':
                    a.lw(8,20,12);a.li(9,action['character']);a.branch(5,8,9,f'{prefix}a{k}request')
                    ready(a,nxt);a.jump(success)
                    a.label(f'{prefix}a{k}request')
                    ready(a,nxt);a.lw(8,20,0x91C)
                    a.li(9,0x100000);a.r(0x2B,9,8,9);a.branch(5,9,0,nxt)
                    a.li(9,0x8000000-0x200);a.r(0x2B,9,9,8);a.branch(5,9,0,nxt)
                    for slot in range(4):
                        a.i(36,9,8,152+slot);a.li(10,action['character']);a.branch(4,9,10,f'{prefix}a{k}form{slot}')
                    a.jump(failed)
                    for slot in range(4):
                        a.label(f'{prefix}a{k}form{slot}')
                        a.lw(8,16,36);a.li(9,1<<index);a.r(0x25,8,8,9);a.sw(8,16,36)
                        # Scripted forms grant the native stock requirement;
                        # the native action still consumes its usual cost.
                        a.lw(8,19,24);a.sw(8,19,20)
                        a.move(4,18);a.addiu(5,0,slot);a.addiu(6,0,1);a.addiu(7,0,1);a.call(A(0x2033C8))
                        a.branch(4,2,0,nxt);a.move(4,18);a.addiu(5,0,slot);a.call(A(0x203610));a.jump(nxt)
                elif kind in ('enter','recover'):
                    a.lw(8,17,12);a.branch(4,8,0,f'{prefix}a{k}restore')
                    ready(a,nxt);a.jump(success)
                    a.label(f'{prefix}a{k}restore')
                    if kind=='enter':
                        a.move(4,18);a.move(5,20);a.call(ARRIVAL)
                        a.branch(4,2,0,failed)
                        a.li(8,part.CONSUMED);a.lw(9,8);a.li(10,~(1<<index)&0xffffffff);a.r(0x24,9,9,10);a.sw(9,8)
                        import extra_reload_requests as reloads
                        a.li(8,reloads.RECORDS+(index-2)*reloads.STRIDE);a.sw(0,8,4);a.sw(0,8,52)
                    else:
                        a.lw(8,19);a.branch(5,8,0,success)
                        ready(a,nxt,dead=True)
                    heal(a,action['health_percent']);a.addiu(8,0,1);a.sw(8,20,8)
                    a.lw(8,16,48);a.li(9,1<<index);a.r(0x25,8,8,9);a.sw(8,16,48)
                    # Native AI queues a fresh combat command even when our
                    # command guard refuses it. Hold its CPU flag throughout
                    # the entrance/recovery, then restore the exact owner.
                    import team_start_gate as start
                    if kind=='enter':
                        a.li(8,cpu_flags[index])
                    else:a.lw(8,18,0x1278)
                    a.li(9,ACTORS+0x100+4*index);a.sw(8,9)
                    a.sw(0,18,0x1278);a.li(9,start.CONTROL+0x40+index*4);a.sw(0,9)
                    for offset in (0x127C,0x1280,0x1284):a.sw(0,18,offset)
                    # Positive HP wakes the retained KO through its native
                    # get-up handler; leave the action clock untouched.
                    a.addiu(8,0,1);a.sw(8,17,12)
                    a.li(8,abi.CONTROL+0x40+4*index);a.sw(0,8)
                    a.jump(nxt)
                elif kind=='heal':
                    a.lw(8,19);a.branch(4,8,0,nxt);heal(a,action['health_percent']);a.jump(success)
                elif kind=='taunt':
                    ready(a,nxt);a.lw(8,17,12);a.branch(5,8,0,success)
                    a.move(4,18);a.addiu(5,0,67);a.call(A(0x1E0290))
                    a.addiu(8,0,1);a.sw(8,17,12);a.jump(nxt)
            if kind=='transform':
                # Don't leave an NPC's ordinary preference bypass set while
                # later dialogue or a different actor's actions run.
                a.label(success);a.lw(8,16,36);a.li(9,~(1<<index)&0xffffffff);a.r(0x24,8,8,9);a.sw(8,16,36)
            else:a.label(success)
            a.sw(0,17,12);a.sw(0,17,20);a.li(8,k+1);a.sw(8,17,4);a.jump(nxt)
            a.label(skip)
        a.addiu(8,0,2);a.sw(8,17);a.lw(8,16,12);a.sw(8,17,16);a.jump(prefix+'clear')
        a.label(failed);a.addiu(8,0,3);a.sw(8,17);a.li(8,i+1);a.sw(8,16,16)
        a.addiu(8,0,-1);a.sw(8,16,20);a.lw(8,16,12);a.addiu(8,8,ACTOR_HZ*5);a.sw(8,16,24)
        if event.get('on_failure')=='fail_scenario':
            a.li(8,3-mission.get('player_team',1));a.sw(8,16,96);a.li(8,i+1);a.sw(8,16,100)
        a.label(prefix+'clear')
        protected=sum(1<<index for index in {ids[x['fighter']] for x in event['actions'] if x['type'] in ('enter','recover')})
        scripted=sum(1<<index for index in {ids[x['fighter']] for x in event['actions'] if x['type']=='transform'})
        for index in {ids[x['fighter']] for x in event['actions'] if 'fighter' in x}:
            label=f'{prefix}release{index}';a.li(8,CONTROL+128+index*4);a.lw(9,8);a.li(10,i+1)
            a.branch(5,9,10,label);a.sw(0,8)
            if protected&(1<<index):
                restored=label+'owner';a.lw(8,16,48);a.li(9,1<<index);a.r(0x24,8,8,9);a.branch(4,8,0,restored)
                a.li(8,ACTORS+4*index);a.lw(9,8);a.li(8,ACTORS+0x100+4*index);a.lw(10,8)
                a.sw(10,9,0x1278);a.li(8,start.CONTROL+0x40+index*4);a.sw(10,8)
                a.label(restored)
            for mask,offset in ((protected,48),(scripted,36)):
                if mask&(1<<index):
                    a.lw(8,16,offset);a.li(9,~(1<<index)&0xffffffff);a.r(0x24,8,8,9);a.sw(8,16,offset)
            a.label(label)
        a.label(nxt)
    a.label('done');a.i(55,8,29,0x2A0);a.i(55,9,29,0x2A8);a.r(17,0,8,0);a.r(19,0,9,0)
    full_abi.restore(a);a.jr()
    data=a.finish()
    if FRAME+len(data)>ARRIVAL:raise ValueError('Mission needs more guest code space; simplify nested events')
    return data


def cpu_init(copies,mission=None):
    """Rebuild cached decisions through native setters, keeping the body's AI dataset."""
    from ai_shadow import AI_GLOBAL
    from team_six_ai import SHADOWS
    a=Assembler(CPU_INIT);abi.prologue(a)
    for index, actor, row, difficulty, behavior in copies:
        a.li(8,row);a.li(9,difficulty);a.sw(9,8,0x38);a.li(9,behavior);a.sw(9,8,0x3C)
        a.li(21,AI_GLOBAL);a.lw(22,21)
        if index>=2:a.li(8,SHADOWS[index]);a.sw(8,21)
        a.li(4,index&1);a.li(5,difficulty);a.call(A(0x1BB478))
        a.li(4,index&1);a.li(5,behavior);a.call(A(0x1BB3E0))
        a.sw(22,21)
    if mission:
        for f in mission['fighters']:
            stats={k:v for k,v in f.get('stats',{}).items() if k not in ('damage','defense','invulnerable','cannot_be_defeated')}
            if f.get('reserve'):stats.pop('health_percent',None)
            if stats:
                index=physical(f);nxt=f'initial_stats{index}';current(a,index,nxt);apply_stats(a,index,stats,nxt);a.label(nxt)
    abi.epilogue(a);code=a.finish()
    if CPU_INIT+len(code)>CONTACT:raise ValueError('Scenario starting stats exceed guest initialization space; simplify CPU overrides')
    return code


def chance_code(chances):
    """Per-CPU acceptance probability; all existing form safety rules still apply."""
    import native_preparation
    a=Assembler(CHANCE);abi.prologue(a);guard(a,'ordinary')
    a.lw(11,16,36);a.branch(4,11,0,'ordinary');a.li(12,core.POINTERS);a.move(13,0)
    a.label('script_scan');a.lw(8,12);a.branch(4,8,4,'script_found');a.addiu(12,12,4);a.addiu(13,13,1)
    a.lw(8,16,8);a.branch(5,13,8,'script_scan');a.jump('ordinary')
    a.label('script_found');a.addiu(8,0,1);a.r(4,8,13,8);a.r(0x24,8,8,11);a.branch(4,8,0,'ordinary')
    a.i(63,0,29,abi.REG_OFFSET[2]);a.jump('done')
    a.label('ordinary')
    import story_rules
    a.li(8,story_rules.CONTROL);a.lw(8,8);a.li(9,story_rules.MAGIC);a.branch(5,8,9,'no_form_rules')
    a.call(story_rules.FORMS);a.i(63,2,29,abi.REG_OFFSET[2]);a.branch(5,2,0,'done')
    a.label('no_form_rules');a.call(CHANCE_NATIVE)
    a.i(63,2,29,abi.REG_OFFSET[2]);a.branch(5,2,0,'done')
    guard(a,'done');a.lw(8,4,0x1278);a.addiu(9,0,1);a.branch(5,8,9,'done')
    for index,threshold in chances.items():
        if threshold==256:continue
        nxt=f'c{index}';a.li(8,core.POINTERS+4*index);a.lw(8,8);a.branch(5,8,4,nxt)
        if threshold:
            a.li(9,native_preparation.CONTROL+44);a.lw(9,9);a.r(2,9,0,9,6)
            a.r(0x26,9,9,4);a.li(11,0x9E3779B9);a.r(0x26,9,9,11)
            for shift,right in ((13,False),(17,True),(5,False)):
                a.r(2 if right else 0,11,0,9,shift);a.r(0x26,9,9,11)
            a.i(12,9,9,255);a.li(10,threshold);a.r(0x2B,9,9,10);a.branch(5,9,0,'done')
        a.addiu(8,0,1);a.i(63,8,29,abi.REG_OFFSET[2]);a.jump('done');a.label(nxt)
    a.label('done');abi.epilogue(a);return a.finish()


def protection_code(base, previous, kind='damage'):
    a=Assembler(base);abi.prologue(a);guard(a,'native',allow_alias=True)
    a.lw(11,16,48);a.li(12,core.POINTERS);a.move(13,0)
    a.label('scan');a.lw(8,12);a.branch(4,8,4,'found')
    if kind=='contact':a.branch(4,8,5,'found')
    a.label('next');a.addiu(12,12,4);a.addiu(13,13,1)
    a.lw(8,16,8);a.branch(5,13,8,'scan');a.jump('rules' if kind=='damage' else 'native')
    a.label('found')
    if kind=='contact':
        import story_rules
        # Contact ABI is source a0, defender a1. An immune actor can still
        # attack; only incoming contacts are refused, preventing stray stagger.
        a.branch(5,8,5,'contact_mask');a.li(8,story_rules.CONTROL);a.lw(8,8);a.li(9,story_rules.MAGIC)
        a.branch(5,8,9,'contact_mask');a.r(0,8,0,13,4);a.li(9,story_rules.STATS+8)
        a.r(0x21,8,8,9);a.lw(8,8);a.branch(5,8,0,'protected');a.label('contact_mask')
    a.addiu(8,0,1);a.r(4,8,13,8);a.r(0x24,8,8,11);a.branch(4,8,0,'next' if kind=='contact' else ('rules' if kind=='damage' else 'native'))
    if kind=='command':
        for command in (67,91,100,101,102,103):a.li(8,command);a.branch(4,5,8,'native')
    a.label('protected');abi.restore(a);a.i(55,31,29,abi.RETURN);a.addiu(29,29,abi.FRAME_SIZE);a.addiu(2,0,int(kind=='contact'));a.jr()
    if kind=='damage':
        import story_rules
        a.label('rules');a.li(8,story_rules.CONTROL);a.lw(8,8);a.li(9,story_rules.MAGIC);a.branch(5,8,9,'native')
        a.move(4,29);a.call(story_rules.DAMAGE)
    a.label('native');abi.restore(a);a.i(55,31,29,abi.RETURN);a.addiu(29,29,abi.FRAME_SIZE);a.jump(previous)
    return a.finish()


def damage_code(previous):return protection_code(DAMAGE,previous)


def uses_destruction_trigger(mission):
    def contains(c):
        return bool(c) and (c['type']=='planet_destroyed' or contains(c.get('condition')) or any(contains(x) for x in c.get('conditions',[])))
    return any(contains(e['when']) for e in mission['events']) or any(contains(mission.get(k)) for k in ('win_when','fail_when'))


def destruction_code():
    """Journal native destruction completion; no host timing or stage-ID guesses.

    Native 127430 calls 13F3C8 exactly when its explosion has finished. The
    native ended latch suppresses a duplicate call and is cleared by 13F310
    before a subsequent destruction. Ordinary arena loading does not call it.
    Events remain held by frame() until transition ownership has been released.
    """
    # A leaf with no calls, FPU work or HI/LO changes; preserve every touched
    # GPR's full 128-bit EE value without paying for a full frame save.
    a=Assembler(DESTRUCTION);a.addiu(29,29,-64)
    for i,reg in enumerate((8,9,10,16)):a.i(31,reg,29,i*16)
    guard(a,'done',allow_alias=True)
    a.li(8,A(0x31BE74));a.lw(8,8);a.branch(5,8,0,'done')
    a.lw(8,16,DESTRUCTION_COUNT-CONTROL);a.addiu(8,8,1);a.sw(8,16,DESTRUCTION_COUNT-CONTROL)
    a.li(8,A(0x331DC8)+40);a.lw(8,8);a.sw(8,16,DESTRUCTION_STAGE-CONTROL)
    a.label('done')
    for i,reg in enumerate((8,9,10,16)):a.i(30,reg,29,i*16)
    a.addiu(29,29,64);a.jump(DESTRUCTION_NATIVE)
    code=a.finish()
    if DESTRUCTION+len(code)>DESTRUCTION_NATIVE:raise ValueError('Scenario destruction observer exceeds its reservation')
    return code


def destruction_blocks(ram,mission):
    if not uses_destruction_trigger(mission):return []
    from prototype import ROOT,elf_reader
    from native_map import elf_path
    entry=A(0x13F3C8);original=elf_reader(elf_path(ROOT))[2](entry,16)
    # This leaf is lui v1,<ended>; li v0,1; jr ra; sw v0,<ended>(v1).
    # It has no PC-relative instructions, calls, or stack frame to relocate.
    hi,_,ret,store=struct.unpack('<4I',original)
    ended=((hi&0xffff)<<16)+struct.unpack('<h',struct.pack('<H',store&0xffff))[0]
    if (hi>>16,original[4:8],ret,store>>16,ended)!=(0x3C03,struct.pack('<I',0x24020001),0x03E00008,0xAC62,A(0x31BE74)):
        raise ValueError('Native destruction completion leaf changed')
    if bytes(ram[entry:entry+16])!=original:raise ValueError('Native destruction completion hook changed')
    return [(DESTRUCTION,destruction_code()),(DESTRUCTION_NATIVE,original),(entry,jump(DESTRUCTION))]


def dependency_override(ram,address,expected):
    """Authenticate a scenario's outer guard for the existing strict validators."""
    import cinematic_contact_guard as contact
    guards={contact.PROTECTED:(CONTACT,'contact'),abi.DAMAGE_ENTRY:(DAMAGE,'damage'),
            A(0x1D4F30):(COMMAND,'command')}
    if address not in guards or len(expected)!=8:return expected
    wrapper,kind=guards[address]
    actual=bytes(ram[address:address+8])
    if actual!=jump(wrapper):return expected
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if (u(CONTROL),u(CONTROL+4),u(CONTROL+8))!=(MAGIC,u(core.ACTORS),u(core.MODE+4)):
        raise ValueError('Story protection belongs to another match')
    instruction,delay=struct.unpack('<2I',expected)
    if instruction>>26!=2 or delay:return expected
    code=protection_code(wrapper,(instruction&0x3ffffff)<<2,kind)
    if bytes(ram[wrapper:wrapper+len(code)])!=code:return expected
    return actual


def draw_code(mission):
    import textwrap
    import unicodedata
    from regional import Y_ORIGIN
    a=Assembler(DRAW);abi.prologue(a);a.call(DRAW_NATIVE)
    a.i(63,2,29,abi.REG_OFFSET[2]);guard(a,'done')
    # The native result poses each side's ORIGINAL leader. A leader retired by the story (its human moved
    # to an entrant) stayed hidden, so the victory/defeat shot showed empty ground. Once the story has
    # decided the outcome and the native result has reached its pose (phase 5+), show it again.
    a.lw(8,16,96);a.branch(4,8,0,'leaders_done')
    a.li(8,A(0x2FEB38));a.lw(8,8);a.li(9,0x100000);a.r(0x2B,9,8,9);a.branch(5,9,0,'leaders_done')
    a.li(9,0x8000000-16);a.r(0x2B,9,8,9);a.branch(4,9,0,'leaders_done')
    a.lw(8,8);a.addiu(9,0,5);a.r(0x2A,9,8,9);a.branch(5,9,0,'leaders_done')
    for index in (0,1):
        nxt=f'leader{index}';a.lw(8,16,112);a.li(9,1<<index);a.r(0x24,8,8,9);a.branch(4,8,0,nxt)
        current(a,index,nxt);a.addiu(8,0,1);a.sw(8,20,8);a.label(nxt)
    a.label('leaders_done')
    a.lw(8,16,12);a.lw(9,16,24);a.r(0x2B,8,8,9);a.branch(4,8,0,'done')
    a.lw(21,28,-22176);a.branch(4,21,0,'done')
    a.lw(22,16,20);data=bytearray()
    a.addiu(8,0,-1);a.branch(5,8,22,'messages')
    notice=b'STORY EVENT COULD NOT COMPLETE\0'
    a.li(4,STRINGS);data.extend(notice)
    a.lw(5,21,512);a.addiu(5,5,1792+8);a.r(0,5,0,5,4)
    a.lw(6,21,524);a.addiu(6,6,Y_ORIGIN-12);a.r(0,6,0,6,4)
    a.li(7,0x8080B0FF);a.call(abi.SMALL_TEXT);a.jump('done');a.label('messages')
    for i,e in enumerate(mission['events']):
        for k,action in enumerate(e['actions']):
            if action['type']!='message':continue
            nxt=f'm{i}_{k}';a.li(8,(i<<8)|k);a.branch(5,8,22,nxt)
            text=unicodedata.normalize('NFKD',action['text']).encode('ascii','ignore').decode().upper()
            # Small native glyphs fit even a quarter screen. Every view gets
            # the same story cue along its own bottom edge, away from the HUD.
            lines=textwrap.wrap(text,32)[:4] or [' ']
            for line_no,line in enumerate(lines):
                address=STRINGS+len(data);data.extend(line.encode()+b'\0')
                a.li(4,address);a.lw(5,21,512);a.addiu(5,5,1792+8);a.r(0,5,0,5,4)
                a.lw(6,21,524);a.addiu(6,6,Y_ORIGIN-12*(len(lines)-line_no));a.r(0,6,0,6,4)
                a.li(7,0x80FFFFFF);a.call(abi.SMALL_TEXT)
            a.jump('done');a.label(nxt)
    a.label('done');abi.epilogue(a);return a.finish(),bytes(data)


def result_code(mission, previous):
    """A pending reserve or second wind prevents premature victory, bounded."""
    ids={f['id']:f for f in mission['fighters']}
    a=Assembler(RESULT);abi.prologue(a);a.call(previous)
    a.i(63,2,29,abi.REG_OFFSET[2]);guard(a,'return')
    # Resolve invalid KOs before returning a native team-defeat result; the
    # frame observer might otherwise run after the game's victory decision.
    import story_rules
    story_rules.emit_outcomes(a,mission,done='outcome_checked');a.label('outcome_checked')
    a.lw(4,29,abi.REG_OFFSET[4]);a.i(11,8,4,2);a.branch(4,8,0,'return')
    a.lw(8,16,96);a.branch(4,8,0,'ordinary_result')
    a.addiu(8,8,-1);a.r(0x26,8,8,4);a.i(63,8,29,abi.REG_OFFSET[2]);a.jump('return')
    a.label('ordinary_result')
    if mission.get('win_when'):
        # An authored win condition replaces an early native enemy-team KO.
        # Defeat of the player's own team still loses normally.
        a.li(8,2-mission.get('player_team',1));a.branch(4,4,8,'hold')
    a.r(0,8,0,4,2);a.addiu(9,16,40);a.r(0x2D,21,9,8)
    a.branch(5,2,0,'defeated');a.sw(0,21);a.jump('return')
    a.label('defeated');a.lw(8,21);a.branch(5,8,0,'defeat_clock')
    a.lw(8,16,12);a.addiu(8,8,1);a.sw(8,21);a.label('defeat_clock')
    for i,e in enumerate(mission['events']):
        affected={ids[x['fighter']]['team']-1 for x in e['actions'] if x['type'] in ('enter','recover')}
        if not affected:continue
        a.li(8,EVENTS+i*EVENT_STRIDE);a.lw(9,8);a.i(11,9,9,2);a.branch(4,9,0,f'next{i}')
        # If dependencies cannot progress, a configurable grace period after
        # total team defeat prevents a stranded match.
        a.lw(8,16,12);a.addiu(8,8,1);a.lw(9,21);a.r(0x23,8,8,9)
        a.li(9,math.ceil(ACTOR_HZ*mission.get('defeat_grace_seconds',30)));a.r(0x2B,8,8,9);a.branch(4,8,0,f'next{i}')
        for side in affected:a.li(8,side);a.branch(4,4,8,'hold')
        a.label(f'next{i}')
    a.label('return');abi.epilogue(a)
    a.label('hold');abi.restore(a);a.i(55,31,29,abi.RETURN);a.addiu(29,29,abi.FRAME_SIZE);a.move(2,0);a.jr()
    return a.finish()


def expanded_program(mission):
    program=copy.deepcopy(mission)
    for event in program['events']:
        actions=[];last_shot=None
        for action in event['actions']:
            if action['type']=='wait' and action.get('freeze'):
                camera=last_shot['camera'] if last_shot else dict(eye=[0,-16,55],target=[0,-9,0])
                action=dict(type='cinematic',fighter=last_shot['fighter'] if last_shot else program['fighters'][0]['id'],
                    seconds=action['seconds'],speed=1,camera=dict(eye=camera.get('end_eye',camera['eye']),target=camera.get('end_target',camera['target'])))
            if action['type']=='cinematic':last_shot=action
            actions.append(action)
            if action['type']=='enter' and action.get('intro',True):
                actions.append(dict(type='taunt',fighter=action['fighter']))
        event['actions']=actions
    return program


def validate_compilation(mission):
    """No world writes: check generated code fits before loading a match."""
    d=adapter_check(mission);program=expanded_program(d)
    code=frame(program,{physical(f):1 for f in d['fighters']})
    draw,strings=draw_code(program);result=result_code(d,defeat.CODE)
    import story_rules,story_cinematics,story_cast
    damage=story_rules.damage_code(d);forms=story_rules.forms_code(d)
    if len(damage)>story_rules.FORMS-story_rules.DAMAGE or len(forms)>story_cast.TRANSFER-story_rules.FORMS:
        raise ValueError('Scenario combat rules exceed their guest code reservation')
    import story_cast
    story_cast.transfer_code()
    # Reserve enough room for the CPU difficulty and behavior cache rebuilds
    # that preparation will add, as well as authored initial stats.
    cpu_init([(physical(f),0x1900000+0x2000*physical(f),0x19009A4+0x2000*physical(f),f.get('difficulty',2),0)
              for f in d['fighters'] if 'difficulty' in f or f.get('cpu_profile') or f.get('copy_cpu_from')],d)
    chance=chance_code({physical(f):round(d['cpu_profiles'][f['cpu_profile']]['transform_chance']*256/100)
                        for f in d['fighters'] if f.get('cpu_profile')})
    if CHANCE+len(chance)>CHANCE_NATIVE:raise ValueError('Too many CPU transformation overrides for the guest reservation')
    story_cinematics.start_code();story_cinematics.tick_code();story_cinematics.voice_code()
    if uses_destruction_trigger(d):destruction_code()
    if sum(x['type']=='voice' for e in program['events'] for x in e['actions'])*12>0x200:
        raise ValueError('Too many independent voice cues; use voices within cinematic actions')
    if len(draw)>DRAW_NATIVE-DRAW or STRINGS+len(strings)>END or len(result)>CHANCE-RESULT:
        raise ValueError('Mission exceeds guest presentation space; simplify its events/messages')
    return dict(event_bytes=len(code),presentation_bytes=len(draw)+len(strings))


def build_memory(ram, mission, source='<prepared>'):
    d=adapter_check(mission);u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if len(ram)!=0x8000000:raise ValueError('Story runtime needs the prepared 128 MiB world')
    if any(ram[BASE:END]):raise ValueError('Story runtime reservation is occupied')
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if count not in modes.ACTOR_COUNTS or (u(core.MODE),u(core.MODE+8),u(core.MODE+12))!=(1,manager,count):
        raise ValueError('Story mission requires a freshly prepared match')
    if u(modes.CONTROL+12)!=modes.TEAMS:raise ValueError('Story missions currently use Team Battle')
    if d.get('stage') is not None and u(A(0x331DC8)+40)!=d['stage']['id']:
        raise ValueError(f"Choose the mission's arena: {d['stage'].get('name',d['stage']['id'])}")
    expected_mask=sum(1<<physical(f) for f in d['fighters'])
    if u(part.PRESENT)!=expected_mask:raise ValueError('Selected team sizes do not match the armed mission')
    cpu_flags={};actors=[];reserved=0;rows={};copies=[];chances={}
    for f in d['fighters']:
        index=physical(f);actor=u(core.POINTERS+4*index);slot=u(actor+0x994)
        if slot>=5:raise ValueError('Mission actor row changed')
        row=actor+0x9A4+164*slot
        if (u(row),u(row+4))!=(f['character'],f['costume']):
            raise ValueError(f"{f['id']}: select character {f['character']}, costume {f['costume']} in Team {f['team']} slot {f['slot']}")
        import team_start_gate as start
        cpu_flags[index]=u(start.CONTROL+0x40+4*index) if u(start.CONTROL) else u(actor+0x1278)
        rows[f['id']]=(index,actor,row)
        if f.get('cpu_profile'):
            profile=d['cpu_profiles'][f['cpu_profile']]
            chances[index]=round(profile['transform_chance']*256/100)
        if f['reserve']:
            if not cpu_flags[index]:raise ValueError('A human-controlled fighter cannot be a reserve')
            reserved|=1<<index
    for f in d['fighters']:
        if f.get('copy_cpu_from'):
            by_id={f['id']:f for f in d['fighters']};source_id=f['copy_cpu_from']
            while by_id[source_id].get('copy_cpu_from'):source_id=by_id[source_id]['copy_cpu_from']
            index,actor,row=rows[f['id']];source_index,_,source_row=rows[source_id]
            if not cpu_flags[index] or not cpu_flags[source_index]:
                raise ValueError('CPU settings can only be copied between CPU-controlled mission fighters')
            source_fighter=by_id[source_id]
            difficulty=source_fighter.get('stats',{}).get('difficulty',source_fighter.get('difficulty',
                d['cpu_profiles'].get(source_fighter.get('cpu_profile'),{}).get('difficulty',u(source_row+0x38))))
            copies.append((index,actor,row,difficulty,u(source_row+0x3C)))
    for f in d['fighters']:
        difficulty=f.get('difficulty',d['cpu_profiles'].get(f.get('cpu_profile'),{}).get('difficulty'))
        if difficulty is not None:
            index,actor,row=rows[f['id']]
            behavior=next((c[4] for c in copies if c[0]==index),u(row+0x3C))
            copies=[c for c in copies if c[0]!=index]
            copies.append((index,actor,row,difficulty,behavior))
    for i in range(count):actors.append(u(core.POINTERS+4*i))
    original=bytes(ram[part.APPLY:part.APPLY+8])
    if original!=part.apply_code()[:8]:raise ValueError('Participation hook changed; refusing to replace it')
    previous=u(defeat.ENTRY)
    if previous>>26!=2 or u(defeat.ENTRY+4):raise ValueError('Native result hook changed')
    previous=(previous&0x03ffffff)<<2
    if previous!=defeat.CODE:raise ValueError('Story results require the ordinary team defeat handler')
    control=bytearray(128);struct.pack_into('<3I',control,0,MAGIC,manager,count)
    struct.pack_into('<I',control,52,FRESH)
    control[64:96]=bytes.fromhex(doc.digest(d))
    raw=doc.encoded(d)
    program=expanded_program(d)
    draw,strings=draw_code(program)
    draw_original=bytes(ram[abi.WORLD:abi.WORLD+8])
    # Only ordinary relocatable prologues; no branch/delay-slot copying.
    if any(w>>26 in (1,2,3,4,5,6,7,20,21) for w in struct.unpack('<2I',draw_original)):
        raise ValueError('Story presentation hook changed')
    damage_jump=u(abi.DAMAGE_ENTRY)
    if damage_jump>>26!=2 or u(abi.DAMAGE_ENTRY+4):raise ValueError('Story protection hook changed')
    damage_previous=(damage_jump&0x3ffffff)<<2
    import cinematic_contact_guard as contact
    contact_original=bytes(ram[contact.PROTECTED:contact.PROTECTED+8])
    if u(contact.PROTECTED)>>26==2 and not u(contact.PROTECTED+4):
        contact_previous=(u(contact.PROTECTED)&0x3ffffff)<<2;contact_copy=b''
    else:
        contact_copy=contact.protected_code()
        if bytes(ram[contact.PROTECTED:contact.PROTECTED+len(contact_copy)])!=contact_copy:
            raise ValueError('Story contact protection dependency changed')
        contact_previous=CONTACT_NATIVE
    command_hook=A(0x1D4F30)
    if u(command_hook)>>26!=2 or u(command_hook+4):raise ValueError('Story input protection dependency changed')
    command_previous=(u(command_hook)&0x3ffffff)<<2
    import stage_transition
    for hook,target,_ in stage_transition.HOOKS:
        if u(hook)!=(3<<26)|(target>>2):raise ValueError('Story entrance needs the current-arena spawn guard')
    blocks=[(FRAME,frame(program,cpu_flags)),(ARRIVAL,arrival_code()),(ORIGINAL,original+jump(part.APPLY+8)),
            (RESULT,result_code(d,previous)),(CPU_INIT,cpu_init(copies,d)),(CONTROL,bytes(control)),
            (ACTORS,struct.pack('<'+'I'*count,*actors)),(DOCUMENT,struct.pack('<I',len(raw))+raw),
            (part.CONSUMED,struct.pack('<I',reserved)),(part.APPLY,jump(FRAME)),(defeat.ENTRY,jump(RESULT)),
            (DRAW,draw),(DRAW_NATIVE,draw_original+jump(abi.WORLD+8)),(STRINGS,strings),
            (abi.WORLD,jump(DRAW)),(DAMAGE,damage_code(damage_previous)),(abi.DAMAGE_ENTRY,jump(DAMAGE)),
            (CONTACT,protection_code(CONTACT,contact_previous,'contact')),
            (COMMAND,protection_code(COMMAND,command_previous,'command')),
            (contact.PROTECTED,jump(CONTACT)),(command_hook,jump(COMMAND))]
    import story_rules
    blocks.extend(story_rules.blocks(ram,d))
    blocks.extend(destruction_blocks(ram,d))
    import story_menus
    blocks.extend(story_menus.blocks(ram,d))
    import story_cinematics as cinema
    shots,_=cinema.asset_blocks(ram,d);blocks.extend(shots)
    voices=[x for e in program['events'] for x in e['actions'] if x['type']=='voice']
    if voices:
        voice_data=b''.join(struct.pack('<3I',x['character'],x['line'],x['volume']) for x in voices)
        if len(voice_data)>0x200:raise ValueError('Too many independent voice cues; use voices within cinematic actions')
        blocks.append((ACTORS+0x400,voice_data))
    for f in d['fighters']:
        if 'hp' in f:
            _,_,row=rows[f['id']]
            blocks.append((row+0x40,struct.pack('<2I',f['hp'],f['hp'])))
    # Ordinary one/two-player worlds only install TEXT. Calling the absent
    # compact entry fell through into GIF data when the first story cue drew.
    compact=abi.text_code(compact=True)
    existing=bytes(ram[abi.SMALL_TEXT:abi.SMALL_TEXT+len(compact)])
    if any(existing) and existing!=compact:raise ValueError('Story text renderer reservation changed')
    if existing!=compact:blocks.append((abi.SMALL_TEXT,compact))
    if contact_copy:blocks.append((CONTACT_NATIVE,contact_copy))
    import extra_intros
    if (u(extra_intros.CONTROL),u(extra_intros.CONTROL+4),u(extra_intros.CONTROL+8))==(extra_intros.MAGIC,manager,count):
        # Reserves get their introduction on entrance, never an invisible
        # opening-dialogue shot when "extra character intros" is enabled.
        blocks.append((extra_intros.CONTROL+32,struct.pack('<I',u(extra_intros.CONTROL+32)&~reserved)))
    for f in d['fighters']:blocks.append((ACTORS+0x200+8*physical(f),struct.pack('<2I',f['character'],0)))
    scripted_forms=any(x['type']=='transform' for e in d['events'] for x in e['actions'])
    if scripted_forms or any(f.get('transformations') for f in d['fighters']) or any(value<256 for value in chances.values()):
        import npc_transform_policy as npc
        original=bytes(ram[npc.PREDICATE:npc.PREDICATE+8])
        if original!=npc.predicate()[:8]:raise ValueError('Mission CPU chance requires the installed NPC form policy')
        blocks += [(CHANCE,chance_code(chances)),(CHANCE_NATIVE,original+jump(npc.PREDICATE+8)),
                   (npc.PREDICATE,jump(CHANCE))]
    spans=sorted((p,p+len(data)) for p,data in blocks)
    if any(end>p for (_,end),(p,_) in zip(spans,spans[1:])):raise ValueError('Story guest sections overlap')
    if any(p>=BASE and p<END and p+len(data)>END for p,data in blocks):raise ValueError('Story presentation exceeds its reserved memory')
    return dict(serial=SERIAL,crc=CRC,source=str(source),mission_id=d['id'],mission_sha256=doc.digest(d),
        blocks=[dict(address=p,expected_hex=ram[p:p+len(data)].hex(),data_hex=data.hex()) for p,data in blocks])


_documents = {}


def snapshot(reader):
    """Small opt-in Workbench status; never used to advance mission events."""
    header=reader.read(CONTROL,112);words=struct.unpack_from('<16I',header)
    if words[0]!=MAGIC or words[1]!=reader.read_u32(core.ACTORS):return None
    key=header[64:96].hex()
    try:
        mission=_documents.get(key)
        if mission is None:
            import json
            size=reader.read_u32(DOCUMENT)
            if not 0<size<=doc.MAX_BYTES:raise ValueError('Invalid mission length')
            mission=doc.validate(json.loads(reader.read(DOCUMENT+4,size).decode('utf-8')))
            if doc.digest(mission)!=key:raise ValueError('Mission checksum changed')
            if len(_documents)>=16:_documents.clear()
            _documents[key]=mission
        states=reader.read(EVENTS,len(mission['events'])*EVENT_STRIDE) if mission['events'] else b''
        names=('waiting','running','complete','failed')
        winner,invalid=struct.unpack_from('<2I',header,96)
        events=[]
        for i,event in enumerate(mission['events']):
            state,step,started=struct.unpack_from('<3I',states,i*EVENT_STRIDE)
            cursor=0;source_step=len(event['actions'])
            for k,action in enumerate(event['actions']):
                cursor+=2 if action['type']=='enter' and action.get('intro',True) else 1
                if step<cursor:source_step=k;break
            events.append(dict(id=event['id'],status=names[min(3,state)],action_index=source_step,
                action=event['actions'][source_step]['type'] if source_step<len(event['actions']) else None,
                wait_seconds=round(max(0,words[3]-started)/ACTOR_HZ,2) if state==1 else None,
                timeout_seconds=event['timeout_seconds']))
        destructions,stage=struct.unpack_from('<2I',header,104)
        return dict(id=mission['id'],title=mission['title'],seconds=round(words[3]/ACTOR_HZ,2),
            planet_destructions=destructions,last_destroyed_stage=stage if destructions else None,
            outcome=('won' if winner==mission.get('player_team',1) else 'failed') if winner else 'running',
            invalid_finisher=invalid or None,
            failed_event=mission['events'][words[4]-1]['id'] if 0<words[4]<=len(mission['events']) else None,
            events=events)
    except (ValueError,KeyError,UnicodeError):
        return dict(error='Mission status could not be decoded; use a fresh battle')
