"""Optional stats for a fusion performed by this match's actual fighters.

The successful consumption callback creates the receipt; choosing a fused
character does not. Native stat rows remain the authority. Each row remembers
its unscaled maximum and the exact maximum we published, so refreshes and
transformations cannot multiply the same health twice. Damage modifies the
existing attributed native-damage call, retaining scenario rules and kill credit.
"""
import struct
from prototype import Assembler
from native_map import SERIAL, CRC
import fresh_team_combat as core
import battle_mode_policy as policy
import fusion_partner_lifecycle as fusion
import team_participation as part
import guest_killfeed as feed
import body_swap as body

BASE, END = 0x06DC0000, 0x06DD0000
GATE, GET, ACTIVATE, HEALTH, CLEAR, TICK, DAMAGE = (BASE+i*0x1000 for i in range(7))
CONTROL, ROWS, STRIDE = BASE+0xF000, BASE+0xF100, 256
MAGIC, VERSION = 0x46554231, 1
# Kind 1 = native action 241 (non-Potara), kind 2 = 242 (Potara).
CONFIG = CONTROL+16  # two {enabled, health, damage, defense} per-mille rows
R = dict(active=0, actor=4, partner=8, partner_actor=12, kind=16, epoch=20)
BANKS, BANK_STRIDE = 64, 16  # character, native max, published max, owned
HASH_RANGES = ((CONTROL,48),(ROWS,policy.ENGINE_ACTORS*STRIDE))


def emit_call(a, entry, *, frame=False, actor=None, kind=None, partner=None):
    """No guest call or write unless the optional module was installed."""
    done='fusion_buffs_'+str(a.pc)
    a.li(8,CONTROL);a.lw(9,8);a.li(10,MAGIC);a.branch(5,9,10,done)
    a.lw(9,8,4);a.lw(10,28,-22364);a.branch(5,9,10,done)
    if frame:a.move(4,29)
    if actor is not None:a.move(4,actor)
    if kind is not None:a.lw(5,29,kind)
    if partner is not None:a.move(6,partner)
    a.call(entry);a.label(done)


def save(a):
    fusion.save(a)
    a.r(16,8,0);a.i(63,8,29,0x290);a.r(18,8,0);a.i(63,8,29,0x298)


def restore(a):
    a.i(55,8,29,0x290);a.r(17,0,8);a.i(55,8,29,0x298);a.r(19,0,8)
    fusion.restore(a)


def gate_code():
    a=Assembler(GATE);core.gate(a,'no')
    a.li(8,CONTROL);a.lw(9,8);a.li(11,MAGIC);a.branch(5,9,11,'no')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'no')
    a.lw(9,8,8);a.branch(5,9,10,'no');a.lw(9,8,12);a.li(11,VERSION);a.branch(5,9,11,'no')
    a.li(8,part.CONTROL);a.lw(9,8);a.li(11,5);a.branch(5,9,11,'no')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'no')
    a.lw(9,8,8);a.branch(5,9,10,'no');a.li(2,1);a.jr()
    a.label('no');a.move(2,0);a.jr();return a.finish()


def get_code():
    """a0 physical -> v0 active receipt or zero; only temporary regs change."""
    a=Assembler(GET);a.li(8,CONTROL);a.lw(9,8,8);a.r(0x2B,9,4,9);a.branch(4,9,0,'no')
    a.r(0,2,0,4,8);a.li(8,ROWS);a.r(0x21,2,2,8);a.lw(9,2);a.li(11,1);a.branch(5,9,11,'no')
    a.lw(8,2,R['kind']);a.addiu(8,8,-1);a.i(11,9,8,2);a.branch(4,9,0,'no')
    a.r(0,8,0,8,4);a.li(9,CONFIG);a.r(0x21,9,9,8);a.lw(9,9);a.branch(4,9,0,'no')
    a.r(0,8,0,4,2);a.li(9,core.POINTERS);a.r(0x21,9,9,8);a.lw(12,9)
    a.lw(9,2,R['actor']);a.branch(5,9,12,'no');fusion.pointer(a,12,0x1600,'no',8,9)
    a.lw(13,2,R['partner']);a.li(8,CONTROL);a.lw(9,8,8);a.r(0x2B,9,13,9);a.branch(4,9,0,'no')
    a.li(8,part.CONTROL);a.lw(9,8,16);a.r(6,9,13,9);a.i(12,9,9,1);a.branch(4,9,0,'no')
    a.lw(9,8,12);a.r(6,9,4,9);a.i(12,9,9,1);a.branch(4,9,0,'no')
    a.lw(9,8,16);a.r(6,9,4,9);a.i(12,9,9,1);a.branch(5,9,0,'no')
    a.r(0,8,0,13,2);a.li(9,core.POINTERS);a.r(0x21,9,9,8);a.lw(9,9)
    a.lw(8,2,R['partner_actor']);a.branch(5,9,8,'no')
    # Body Change is serialized. Its exact two actor records distinguish an
    # unrelated exchange from an exchange of this fused survivor.
    a.li(8,body.CONTROL);a.lw(9,8);a.li(11,body.MAGIC);a.branch(5,9,11,'yes')
    a.lw(9,8,4);a.li(11,CONTROL);a.lw(11,11,4);a.branch(5,9,11,'yes')
    a.lw(9,8,body.FINISHED-body.CONTROL);a.lw(11,2,R['epoch']);a.branch(5,9,11,'exchange')
    a.lw(9,8,16);a.branch(4,9,0,'yes')
    a.label('exchange')
    for at in (body.ROWS+4,body.ROWS+68):
        a.li(8,at);a.lw(9,8);a.branch(4,9,12,'no')
    a.label('yes');a.jr();a.label('no');a.move(2,0);a.jr();return a.finish()


def scaled(a,value,numerator,denominator):
    # At most 1,000,000*5,000, split before multiplication to avoid overflow.
    a.r(27,0,value,denominator);a.r(18,10,0);a.r(16,11,0)
    a.r(25,0,10,numerator);a.r(18,10,0)
    a.r(25,0,11,numerator);a.r(18,11,0)
    a.r(27,0,11,denominator);a.r(18,11,0);a.r(0x21,value,10,11)


def ratio(a,value,numerator,denominator):
    """Exact bounded 64-bit product / 32-bit divisor using EE instructions.

    Health ratios can multiply two million-sized numbers. EE has MULTU but
    no DDIVU, so divide its HI:LO product a bit at a time, only on row changes.
    """
    label='ratio_'+str(a.pc)
    a.r(25,0,value,numerator);a.r(16,12,0);a.r(18,13,0)
    a.move(value,0);a.move(14,0);a.li(15,64);a.label(label)
    a.r(2,10,0,12,31);a.r(0,12,0,12,1);a.r(2,11,0,13,31)
    a.r(0x25,12,12,11);a.r(0,13,0,13,1)
    a.r(0,14,0,14,1);a.r(0x25,14,14,10);a.r(0,value,0,value,1)
    a.r(0x2B,10,14,denominator);a.branch(5,10,0,label+'_next')
    a.r(0x23,14,14,denominator);a.i(13,value,value,1)
    a.label(label+'_next');a.addiu(15,15,-1);a.branch(5,15,0,label)


def health_code():
    """a0 authenticated receipt. Scale only a living current native stat row."""
    a=Assembler(HEALTH);save(a);a.move(16,4);a.lw(17,16,R['actor'])
    a.lw(18,17,0x994);a.lw(9,17,0x998);a.i(11,8,9,6);a.branch(4,8,0,'done')
    a.r(0x2B,8,18,9);a.branch(4,8,0,'done')
    fusion.row_address(a,19,17,18,8)
    a.lw(20,19,64);a.branch(6,20,0,'done');a.lw(21,19,68)
    a.r(0x2B,8,21,20);a.branch(5,8,0,'done');a.li(8,1000001);a.r(0x2B,8,21,8);a.branch(4,8,0,'done')
    a.r(0,22,0,18,4);a.r(0x21,22,22,16);a.addiu(22,22,BANKS)
    a.lw(8,22,12);a.branch(4,8,0,'fresh');a.lw(8,22,8);a.branch(5,8,21,'fresh')
    # A native form refresh may retain the same max. Carry the existing
    # receipt instead of scaling that already-modified value again.
    a.lw(8,19);a.sw(8,22);a.jump('done')
    a.label('fresh');a.lw(8,16,R['kind']);a.addiu(8,8,-1);a.r(0,8,0,8,4)
    a.li(9,CONFIG+4);a.r(0x21,9,9,8);a.lw(23,9);a.li(24,1000)
    a.move(25,21);scaled(a,25,23,24);a.li(8,1000000);a.r(0x2B,9,8,25)
    a.branch(4,9,0,'max_ready');a.move(25,8);a.label('max_ready')
    a.branch(5,25,0,'nonzero_max');a.li(25,1);a.label('nonzero_max')
    # Use the actual capped maximum when preserving the health fraction.
    ratio(a,20,25,21);a.branch(5,20,0,'hp_ready');a.li(20,1);a.label('hp_ready')
    a.lw(8,19);a.sw(8,22);a.sw(21,22,4);a.sw(25,22,8);a.li(8,1);a.sw(8,22,12)
    a.sw(20,19,64);a.sw(25,19,68)
    a.label('done');restore(a);a.jr();return a.finish()


def clear_code():
    """a0 receipt. Undo only maxima still matching our recorded row identity."""
    a=Assembler(CLEAR);save(a);a.move(16,4);a.lw(17,16,R['actor'])
    fusion.pointer(a,17,0x1600,'clear',8,9);a.move(18,0)
    a.addiu(19,17,0x9A4);a.addiu(22,16,BANKS)
    a.label('bank');a.lw(8,22,12);a.branch(4,8,0,'next')
    a.lw(8,19);a.lw(9,22);a.branch(5,8,9,'next')
    a.lw(21,19,68);a.lw(9,22,8);a.branch(5,21,9,'next')
    a.lw(25,22,4);a.branch(6,25,0,'next');a.branch(6,21,0,'next')
    a.lw(20,19,64);a.branch(6,20,0,'store');a.r(0x2B,9,21,20);a.branch(4,9,0,'bounded');a.move(20,21)
    a.label('bounded');ratio(a,20,25,21);a.branch(5,20,0,'store');a.li(20,1)
    a.label('store');a.sw(20,19,64);a.sw(25,19,68)
    a.label('next');a.addiu(18,18,1);a.addiu(19,19,164);a.addiu(22,22,BANK_STRIDE)
    a.li(8,5);a.branch(5,18,8,'bank')
    a.label('clear');a.sw(0,16);restore(a);a.jr();return a.finish()


def activate_code():
    """a0 successful survivor, a1 native kind241/242, a2 consumed physical."""
    a=Assembler(ACTIVATE);save(a);a.move(16,4);a.addiu(17,5,-240);a.move(18,6)
    a.call(GATE);a.branch(4,2,0,'done');a.addiu(8,17,-1);a.i(11,9,8,2);a.branch(4,9,0,'done')
    a.r(0,8,0,8,4);a.li(9,CONFIG);a.r(0x21,9,9,8);a.lw(8,9);a.branch(4,8,0,'done')
    a.li(8,CONTROL);a.lw(20,8,8);a.r(0x2B,8,18,20);a.branch(4,8,0,'done')
    a.li(21,core.POINTERS);a.move(19,0)
    a.label('scan');a.lw(8,21);a.branch(4,8,16,'found');a.addiu(21,21,4);a.addiu(19,19,1)
    a.branch(5,19,20,'scan');a.jump('done')
    a.label('found');a.branch(4,19,18,'done');a.r(0x26,8,19,18);a.i(12,8,8,1);a.branch(5,8,0,'done')
    a.li(8,part.CONSUMED);a.lw(9,8);a.r(6,9,18,9);a.i(12,9,9,1);a.branch(4,9,0,'done')
    a.r(0,22,0,19,8);a.li(8,ROWS);a.r(0x21,22,22,8)
    # An exact duplicate callback must not rebase onto its own boosted stats.
    a.move(4,19);a.call(GET);a.branch(5,2,0,'done')
    for off in range(0,STRIDE,4):a.sw(0,22,off)
    a.sw(16,22,R['actor']);a.sw(18,22,R['partner']);a.sw(17,22,R['kind'])
    a.r(0,8,0,18,2);a.li(9,core.POINTERS);a.r(0x21,9,9,8);a.lw(9,9);a.sw(9,22,R['partner_actor'])
    a.li(8,body.FINISHED);a.lw(8,8);a.sw(8,22,R['epoch']);a.li(8,1);a.sw(8,22)
    a.move(4,22);a.call(HEALTH)
    a.label('done');restore(a);a.jr();return a.finish()


def tick_code():
    a=Assembler(TICK);save(a);a.call(GATE);a.branch(4,2,0,'done')
    a.li(8,core.PAIR+4);a.lw(8,8);a.branch(5,8,0,'done')
    a.li(16,ROWS);a.move(17,0);a.li(8,CONTROL);a.lw(18,8,8)
    a.label('row');a.lw(8,16);a.branch(4,8,0,'next');a.move(4,17);a.call(GET)
    a.branch(4,2,0,'expired');a.move(4,16);a.call(HEALTH);a.jump('next')
    a.label('expired')
    # Never follow a stale actor address if the match replaced the roster.
    a.r(0,8,0,17,2);a.li(9,core.POINTERS);a.r(0x21,9,9,8);a.lw(9,9);a.lw(8,16,R['actor'])
    a.branch(5,8,9,'forget');a.move(4,16);a.call(CLEAR);a.jump('next')
    a.label('forget');a.sw(0,16)
    a.label('next');a.addiu(16,16,STRIDE);a.addiu(17,17,1);a.branch(5,17,18,'row')
    a.label('done');restore(a);a.jr();return a.finish()


def damage_code():
    """a0 kill-feed saved frame, including its exact attacker/victim indices."""
    a=Assembler(DAMAGE);save(a);a.move(16,4);a.call(GATE);a.branch(4,2,0,'done')
    a.lw(8,16,feed.REG_OFFSET[6]);a.i(12,8,8,1);a.branch(5,8,0,'done')
    a.lw(17,16,0xF0);a.lw(18,16,0xF4);a.branch(4,17,18,'done')
    a.lw(19,16,feed.REG_OFFSET[5]);a.branch(6,19,0,'done')
    a.li(20,1000);a.li(21,1000);a.move(4,18);a.call(GET);a.branch(4,2,0,'defender')
    a.lw(8,2,R['kind']);a.addiu(8,8,-1);a.r(0,8,0,8,4);a.li(9,CONFIG+8);a.r(0x21,9,9,8);a.lw(20,9)
    a.label('defender');a.move(4,17);a.call(GET);a.branch(4,2,0,'apply')
    a.lw(8,2,R['kind']);a.addiu(8,8,-1);a.r(0,8,0,8,4);a.li(9,CONFIG+12);a.r(0x21,9,9,8);a.lw(21,9)
    a.label('apply');a.branch(4,20,21,'done');a.li(8,1000000);a.r(0x2B,9,8,19)
    a.branch(4,9,0,'bounded');a.move(19,8);a.label('bounded');scaled(a,19,20,21)
    a.li(8,1000000);a.r(0x2B,9,8,19);a.branch(4,9,0,'nonzero');a.move(19,8)
    a.label('nonzero');a.branch(5,19,0,'store');a.li(19,1)
    a.label('store');a.i(63,19,16,feed.REG_OFFSET[5])
    a.label('done');restore(a);a.jr();return a.finish()


def pieces():
    out=[(GATE,gate_code()),(GET,get_code()),(ACTIVATE,activate_code()),(HEALTH,health_code()),
         (CLEAR,clear_code()),(TICK,tick_code()),(DAMAGE,damage_code())]
    assert all(len(data)<=0x1000 for _,data in out)
    return out


def config(settings):
    rows=[]
    for kind in ('non_potara','potara'):
        prefix='fusion_'+kind
        enabled=settings.get(prefix+'_buffs_enabled',False)
        if type(enabled) is not bool:raise ValueError('Fusion buff switch must be Boolean')
        values=[]
        for stat in ('health','damage','defense'):
            value=settings.get(prefix+'_'+stat+'_multiplier',1.0)
            if type(value) not in (int,float) or not .25<=value<=5:raise ValueError('Fusion multiplier must be 0.25..5')
            values.append(round(value*1000))
        rows.append((int(enabled and values!=[1000]*3),*values))
    return b''.join(struct.pack('<4I',*r) for r in rows)


@policy.matching_install
def build_memory(ram,settings=None,source='<prepared>'):
    values=config(settings or {})
    if not any(struct.unpack_from('<I',values,i)[0] for i in (0,16)):return dict(blocks=[])
    if len(ram)!=0x8000000:raise ValueError('Fusion buffs require full captured memory')
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    manager,count=u(core.ACTORS),u(core.MODE+4)
    if count not in policy.ACTOR_COUNTS or (u(core.MODE),u(core.MODE+8),u(core.MODE+12))!=(1,manager,count):
        raise ValueError('Fusion buffs require a prepared captured match')
    if (u(fusion.CONTROL),u(fusion.CONTROL+4),u(fusion.CONTROL+8))!=(1,manager,count):
        raise ValueError('Install fusion lifecycle before fusion buffs')
    control=struct.pack('<4I',MAGIC,manager,count,VERSION)+values
    if u(CONTROL)==MAGIC:
        if bytes(ram[CONTROL:CONTROL+len(control)])!=control:raise ValueError('Changed fusion buffs require a new match')
        for at,data in pieces():
            if bytes(ram[at:at+len(data)])!=data:raise ValueError('Fusion buff program changed')
        return dict(blocks=[],control=CONTROL,status='FUSION BUFFS VERIFIED')
    if any(ram[BASE:END]):raise ValueError('Fusion buff reservation occupied')
    # Confirm all three callback paths are present, including timed variants.
    for at,variants in ((fusion.COMMIT,(fusion.commit_code(),fusion.commit_code(True))),
                        (fusion.EXTRA_COMMIT,(fusion.commit_code(True,True),)),
                        (feed.TICK,(feed.tick_code(),)),(feed.DAMAGE,(feed.damage_code(),))):
        if not any(bytes(ram[at:at+len(b)])==b for b in variants):raise ValueError('Fusion buff callback dependency changed')
    blocks=pieces()+[(ROWS,bytes(policy.ENGINE_ACTORS*STRIDE)),(CONTROL,control)]
    return dict(serial=SERIAL,crc=CRC,source=str(source),control=CONTROL,
                blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex()) for p,d in blocks],
                limitations=['Only fusions performed in this match receive bonuses; preselected fused fighters use native stats.'])


def unscaled_health(ram,actor,current):
    """Remove the owned health multiplier when timed defusion splits its pool."""
    if len(ram)!=0x8000000:return current
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if (u(CONTROL),u(CONTROL+4),u(CONTROL+8))!=(MAGIC,u(core.ACTORS),u(core.MODE+4)):return current
    count=u(CONTROL+8)
    if count not in policy.ACTOR_COUNTS:return current
    for i in range(count):
        r=ROWS+i*STRIDE
        if not u(r) or u(r+R['actor'])!=actor or u(core.POINTERS+4*i)!=actor:continue
        slot=u(actor+0x994)
        if not 0<=slot<min(u(actor+0x998),5):return current
        b=r+BANKS+slot*BANK_STRIDE;row=actor+0x9A4+164*slot
        if u(b+12) and u(b)==u(row) and u(b+8)==u(row+68) and u(b+8):
            result=min(current,u(b+8))*u(b+4)//u(b+8)
            return max(1,result) if current>0 else 0
    return current
