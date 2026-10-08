"""Selected-roster practice, separate from native Training and ordinary matches.

Installed only for an explicit Modded Training selection. Keeps normal team
relationships and the native combat engine, with optional refill and idle CPUs.
All construction is offline. No emulator connection is made by this module.
"""
from native_map import A, elf_path
import math
import struct
from prototype import Assembler, ROOT, elf_reader
import battle_mode_policy as policy
import fresh_team_combat as core
import fresh_team_ai as ai
import team_participation as part
import team_start_gate as start
import guest_killfeed as feed
import viewport_hud as registers
import mod_settings
from native_map import ACTOR_HZ

CODE, GATE, DAMAGE_QUERY, CONTROL, ROWS, END = 0x070C0000,0x070C2000,0x070C2800,0x070CF000,0x070CF100,0x070D0000
MAGIC=0x54524E31
AI_HOOK=ai.FRAME_HOOK
# This precise native query controls the stock Training nonlethal damage clamp.
# Returning five here alone does not alter the game's global mode or menus.
DAMAGE_HOOK, NATIVE_QUERY = A(0x1CE86C),A(0x12AB38)
NATIVE=elf_reader(elf_path(ROOT))[2]
STRIDE=16  # captured actor, last health, refill delay, saved CPU flag
FIELDS=dict(health=12,ki=16,stocks=20,idle=24,delay=28,frames=32)


def gate():
    a=Assembler(GATE);core.gate(a,'no');a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,'no')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'no');a.lw(9,8,8);a.branch(5,9,10,'no')
    a.li(8,part.CONTROL);a.lw(9,8);a.addiu(11,0,5);a.branch(5,9,11,'no')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'no');a.lw(9,8,8);a.branch(5,9,10,'no')
    for p in (core.PAIR+4,start.CONTROL,A(0x333700)):a.li(8,p);a.lw(9,8);a.branch(5,9,0,'no')
    a.li(8,A(0x3337C0));a.lw(9,8);a.addiu(11,0,1);a.branch(5,9,11,'no')
    a.li(8,A(0x3337B8));a.lw(9,8);a.i(12,9,9,0x3900);a.branch(5,9,0,'no')
    a.li(8,A(0x2FEB38));a.lw(8,8);a.li(9,0x100000);a.r(0x2B,9,8,9);a.branch(5,9,0,'no')
    a.li(9,0x7FFFE00);a.r(0x2B,9,8,9);a.branch(4,9,0,'no');a.lw(9,8);a.addiu(11,0,3);a.branch(5,9,11,'no')
    # Validate every pointer before any write, including absent parity slots.
    a.li(8,ROWS);a.li(11,core.POINTERS);a.move(12,0)
    a.label('scan');a.lw(9,8);a.lw(13,11);a.branch(5,9,13,'no')
    a.i(12,13,9,15);a.branch(5,13,0,'no');a.li(13,0x100000);a.r(0x2B,13,9,13);a.branch(5,13,0,'no')
    a.li(13,0x8000000-0x1600);a.r(0x2B,13,13,9);a.branch(5,13,0,'no')
    a.lw(13,9);a.branch(5,13,12,'no');a.addiu(8,8,STRIDE);a.addiu(11,11,4);a.addiu(12,12,1)
    a.branch(5,12,10,'scan');a.addiu(2,0,1);a.jr();a.label('no');a.move(2,0);a.jr();return a.finish()


def frame():
    a=Assembler(CODE);registers.save(a);a.call(GATE);a.branch(4,2,0,'prior')
    a.li(16,CONTROL);a.lw(17,16,8);a.move(18,0);a.li(19,ROWS)
    a.lw(8,16,32);a.addiu(8,8,1);a.sw(8,16,32)
    a.label('actor');a.lw(20,19);a.lw(8,20,0x1278);a.sw(8,19,12)
    a.li(8,part.PRESENT);a.lw(8,8);a.li(9,part.CONSUMED);a.lw(9,9);a.r(0x27,9,9,0);a.r(0x24,8,8,9)
    a.addiu(9,0,1);a.r(4,9,18,9);a.r(0x24,8,8,9);a.branch(4,8,0,'next')
    a.move(4,20);a.call(feed.ROW);a.branch(4,2,0,'next');a.move(21,2);a.lw(22,21);a.branch(6,22,0,'next')
    a.lw(8,16,FIELDS['health']);a.branch(4,8,0,'energy');a.lw(8,19,4);a.r(0x2A,9,22,8)
    a.branch(4,9,0,'countdown');a.lw(8,16,FIELDS['delay']);a.sw(8,19,8)
    a.label('countdown');a.lw(8,19,8);a.branch(4,8,0,'heal');a.addiu(8,8,-1);a.sw(8,19,8);a.jump('remember')
    a.label('heal');a.lw(8,21,4);a.branch(6,8,0,'remember');a.li(9,1000000);a.r(0x2B,9,9,8);a.branch(5,9,0,'remember')
    a.sw(8,21);a.move(22,8)
    a.label('remember');a.sw(22,19,4)
    a.label('energy')
    for label,cfg,offset in (('ki',16,12),('stocks',20,20)):
        a.lw(8,16,cfg);a.branch(4,8,0,label+'done');a.lw(8,21,offset+4);a.branch(6,8,0,label+'done')
        a.li(9,10000000);a.r(0x2B,9,9,8);a.branch(5,9,0,label+'done');a.lw(9,21,offset);a.r(0x2A,9,9,8)
        a.branch(4,9,0,label+'done');a.sw(8,21,offset);a.label(label+'done')
    a.lw(8,16,FIELDS['idle']);a.branch(4,8,0,'next');a.lw(8,19,12);a.branch(4,8,0,'next')
    for off in (0x1278,0x127C,0x1280,0x1284):a.sw(0,20,off)
    a.label('next');a.addiu(19,19,STRIDE);a.addiu(18,18,1);a.branch(5,18,17,'actor')
    # Execute the entire original private scheduler, including human handling.
    # Only CPU command generation is temporarily disabled; ownership is restored
    # before the native world update can mistake a dummy for a human fighter.
    registers.restore(a);a.addiu(29,29,-16);a.i(63,31,29,0);a.call(ai.FRAME);a.i(55,31,29,0);a.addiu(29,29,16)
    registers.save(a);a.li(16,CONTROL);a.lw(17,16,8);a.move(18,0);a.li(19,ROWS)
    a.label('restore_cpu');a.lw(20,19);a.lw(8,19,12);a.sw(8,20,0x1278)
    a.addiu(19,19,STRIDE);a.addiu(18,18,1);a.branch(5,18,17,'restore_cpu');registers.restore(a);a.jr()
    a.label('prior');registers.restore(a);a.jump(ai.FRAME)
    out=a.finish();assert len(out)<GATE-CODE;return out


def damage_query():
    a=Assembler(DAMAGE_QUERY);registers.save(a);a.call(GATE);a.branch(4,2,0,'native')
    a.li(8,CONTROL);a.lw(9,8,FIELDS['health']);a.branch(4,9,0,'native');a.lw(10,8,8)
    a.li(8,ROWS);a.move(9,0)
    a.label('scan');a.lw(11,8);a.branch(4,11,20,'found');a.addiu(8,8,STRIDE);a.addiu(9,9,1);a.branch(5,9,10,'scan');a.jump('native')
    a.label('found');a.li(8,part.PRESENT);a.lw(11,8);a.li(8,part.CONSUMED);a.lw(12,8)
    a.r(0x27,12,12,0);a.r(0x24,11,11,12);a.addiu(12,0,1);a.r(4,12,9,12);a.r(0x24,11,11,12);a.branch(4,11,0,'native')
    # Native s7 is the already-resolved selected health row at this exact call.
    # The stock nonlethal branch clamps damage to HP-1, so applying it to an
    # already-dead row would raise zero HP to one. Never revive a delayed victim.
    a.lw(11,23);a.branch(6,11,0,'native')
    registers.restore(a);a.addiu(2,0,5);a.jr()
    a.label('native');registers.restore(a);a.jump(NATIVE_QUERY)
    return a.finish()


def program():
    return [(CODE,frame()),(GATE,gate()),(DAMAGE_QUERY,damage_query()),
            (AI_HOOK,struct.pack('<I',(3<<26)|(CODE>>2))),
            (DAMAGE_HOOK,struct.pack('<I',(3<<26)|(DAMAGE_QUERY>>2)))]


@policy.matching_install
def build_memory(ram,settings=None,source='<prepared>'):
    if len(ram)!=0x8000000:raise ValueError('Modded Training requires original 128 MiB RAM')
    options=mod_settings.validate_settings(settings or {});u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if count not in policy.ACTOR_COUNTS or (u(core.MODE),u(core.MODE+8),u(core.MODE+12))!=(1,manager,count):raise ValueError('Invalid captured training world')
    if u(policy.CONTROL)==policy.MAGIC:
        if (u(policy.CONTROL+4),u(policy.CONTROL+8),u(policy.CONTROL+12))!=(manager,count,policy.COOP):
            raise ValueError('Practice requires team or co-op relationships in this match')
        policy.validate_roster('coop',count,u(part.PRESENT),u(policy.CONTROL+16))
    if (u(part.CONTROL+4),u(part.CONTROL+8))!=(manager,count):raise ValueError('Missing training participation')
    if any(ram[CODE:END]):raise ValueError('Training reservation occupied')
    if u(AI_HOOK)!=(3<<26)|(ai.FRAME>>2):raise ValueError('Unknown training AI continuation')
    if ram[DAMAGE_HOOK:DAMAGE_HOOK+8]!=NATIVE(DAMAGE_HOOK,8):raise ValueError('Native nonlethal damage query changed')
    control=bytearray(0x100);struct.pack_into('<8I',control,0,MAGIC,manager,count,
        int(options['training_refill_health']),int(options['training_refill_ki']),int(options['training_refill_stocks']),
        int(options['training_cpu_behavior']=='idle'),math.ceil(options['training_health_delay_seconds']*ACTOR_HZ))
    rows=bytearray(policy.ENGINE_ACTORS*STRIDE)
    for i in range(count):
        actor=u(core.POINTERS+4*i)
        if not 0x100000<=actor<0x8000000-0x1600 or u(actor)!=i:raise ValueError('Invalid training actor')
        struct.pack_into('<I',rows,i*STRIDE,actor)
    pieces=program()+[(CONTROL,bytes(control)),(ROWS,bytes(rows))]
    return dict(source=str(source),mode='training',control=CONTROL,
                blocks=[dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=b.hex()) for p,b in pieces],
                limitations=['Team-arena practice; native Training lessons, recording and reset commands remain separate.',
                             'Native timer and ring-out rules remain; choose unlimited time and a non-ring-out stage.',
                             'Health refill prevents ordinary attack KOs; disabling it permits normal defeat/results.'])
