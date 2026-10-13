"""Local tag-rush contact isolation, attributed native damage and safe placement.

All routines are guest code. Installation retains the existing contact chain;
the finisher calls the ordinary damage entry, including scenario and KO hooks.
"""
import struct
from native_map import A, FLAG
from prototype import Assembler
import fresh_team_combat as core
import tag_rush_camera as camera

CONTACT, TRAMPOLINE = 0x06D06000, 0x06D06400
DAMAGE, DAMAGE_CALL, PREFLIGHT = 0x06D06800, 0x06D06B00, 0x06D07000
VICTIM_PREFLIGHT = 0x06D07600
# Native 1E9590 knockback flight, not the adjacent paired throw/vanish actions.
LAUNCHED_ACTIONS = (213, 214, 223)
DAMAGE_RETURN = DAMAGE_CALL+8
PLACE, FLOOR, QUERY = 0x06D09000, 0x06D0B000, 0x06D0B400
STATE, DAMAGE_DONE, QUERY_STATS, END = 0x06D0E000, 0x06D0E000, 0x06D0E010, 0x06D10000
CONTROL = camera.CONTROL


def emit_non_giant_model(a,model,fail):
    """Reject native size class4 regardless of optional giant enlargement.

    The model was already authenticated by the caller. Parameters are checked
    independently so missing/reloading data cannot accidentally admit a giant.
    Clobbers t0,t1,t3 only.
    """
    import fusion_partner_lifecycle as full
    assert model not in (8,9,11)
    a.lw(11,model,2332);full.pointer(a,11,3,fail)
    a.i(36,9,11,2);a.li(8,4);a.branch(4,9,8,fail)


def emit_registered(a,actor,out,fail,tag):
    """Capture-table pointer scan; no temporary actor-ID aliases. t0..t2."""
    assert actor not in (8,9,10) and out not in (8,9,10)
    a.branch(4,actor,0,fail);a.li(8,core.POINTERS);a.li(10,CONTROL);a.lw(10,10,8)
    a.branch(6,10,0,fail);a.i(11,9,10,13);a.branch(4,9,0,fail);a.move(out,0)
    a.label(tag);a.lw(9,8);a.branch(4,9,actor,tag+'_found')
    a.addiu(out,out,1);a.addiu(8,8,4);a.branch(5,out,10,tag);a.jump(fail);a.label(tag+'_found')


def emit_damage_attacker(a,out,victim,return_reg,fail,tag):
    """Only our exact native call may supply the captured initiator.

    No attribution-table entry is added: those entries describe original ELF
    call sites and are independently checked by the beam-struggle adapter.
    Clobbers t0..t3,t4,t5. out/victim must not use those registers.
    """
    assert out not in range(8,14) and victim not in range(8,14)
    a.li(9,DAMAGE_RETURN);a.branch(5,return_reg,9,fail)
    camera.emit_active(a,fail)
    a.lw(12,8,36);a.lw(13,8,8);a.r(0x2B,11,12,13);a.branch(4,11,0,fail)
    a.r(0,12,0,12,2);a.li(11,core.POINTERS);a.r(0x21,12,12,11);a.lw(12,12)
    a.branch(4,12,victim,tag+'_victim')
    # The special restraint can deliberately hit its captured Goku as well.
    # No general friendly-fire exception or attribution entry is installed.
    a.lw(12,8,44);a.li(11,4);a.branch(5,12,11,fail)
    a.lw(12,8,108);a.li(11,1);a.branch(5,12,11,fail)
    a.lw(12,8,28);a.r(0x2B,11,12,13);a.branch(4,11,0,fail)
    a.r(0,12,0,12,2);a.li(11,core.POINTERS);a.r(0x21,12,12,11);a.lw(12,12)
    a.branch(5,12,victim,fail)
    a.label(tag+'_victim');a.lw(12,8,28)
    a.lw(11,8,44);a.li(10,4);a.branch(5,11,10,tag+'_attacker');a.lw(12,8,32)
    a.label(tag+'_attacker');a.r(0x2B,11,12,13);a.branch(4,11,0,fail)
    a.r(0,12,0,12,2);a.li(11,core.POINTERS);a.r(0x21,12,12,11);a.lw(12,12)
    a.branch(4,12,0,fail);a.branch(4,12,victim,fail);a.move(out,12)


def contact_code():
    a=Assembler(CONTACT);camera.save(a);camera.emit_active(a,'native')
    for actor,tag in ((4,'source'),(5,'target')):
        emit_registered(a,actor,14,'native' if actor==5 else 'check_target',tag)
        a.li(8,CONTROL);a.lw(9,8,camera.SHARED);a.branch(5,9,0,'blocked')
        a.lw(9,8,camera.MEMBERS);a.r(6,9,14,9);a.i(12,9,9,1)
        a.branch(5,9,0,'blocked')
        if actor==4:a.label('check_target')
    a.label('native');camera.restore(a);a.jump(TRAMPOLINE)
    a.label('blocked');a.li(2,1);camera.restore(a,skip=(2,));a.jr()
    data=a.finish();assert len(data)<=TRAMPOLINE-CONTACT;return data


def damage_code():
    """a0 victim,a1 amount,a2 native hit flags ->v0 1 submitted/0 refused.

    The director clears DAMAGE_DONE before each new rush. Reserving before the
    native call also prevents reentrant or repeated final-frame damage.
    """
    a=Assembler(DAMAGE);camera.save(a);camera.emit_active(a,'no')
    a.li(8,DAMAGE_DONE);a.lw(9,8);a.branch(5,9,0,'no')
    a.branch(6,5,0,'no');a.li(9,1000000);a.r(0x2B,9,9,5);a.branch(5,9,0,'no')
    a.li(8,CONTROL);a.lw(12,8,36);a.lw(13,8,8);a.r(0x2B,11,12,13);a.branch(4,11,0,'no')
    a.r(0,12,0,12,2);a.li(11,core.POINTERS);a.r(0x21,12,12,11);a.lw(12,12);a.branch(4,12,4,'victim')
    a.lw(12,8,44);a.li(11,4);a.branch(5,12,11,'no')
    a.lw(12,8,108);a.li(11,1);a.branch(5,12,11,'no')
    a.lw(12,8,28);a.r(0x2B,11,12,13);a.branch(4,11,0,'no')
    a.r(0,12,0,12,2);a.li(11,core.POINTERS);a.r(0x21,12,12,11);a.lw(12,12);a.branch(5,12,4,'no')
    a.label('victim');a.lw(12,8,28)
    a.lw(11,8,44);a.li(10,4);a.branch(5,11,10,'attacker');a.lw(12,8,32)
    a.label('attacker');a.r(0x2B,11,12,13);a.branch(4,11,0,'no');a.r(0,12,0,12,2)
    a.li(11,core.POINTERS);a.r(0x21,12,12,11);a.lw(16,12);a.branch(4,16,0,'no');a.branch(4,16,4,'no')
    a.li(8,DAMAGE_DONE);a.li(9,1);a.sw(9,8);a.jump('apply')
    a.label('no');a.move(2,0);a.jump('done')
    while DAMAGE+len(a.words)*4<DAMAGE_CALL:a.emit(0)
    assert DAMAGE+len(a.words)*4==DAMAGE_CALL
    a.label('apply');a.call(A(0x1CE630));a.li(2,1)
    a.label('done');camera.restore(a,skip=(2,));a.jr()
    data=a.finish();assert len(data)<=PREFLIGHT-DAMAGE;return data


def preflight_code(base=PREFLIGHT, *, victim=False):
    """a0 actual actor ->v0 1 if capture, model and pending native queues are safe.

    No pending hit is discarded to make a cinematic start. The director waits
    until the native dispatcher has drained it instead.
    """
    import beam_struggle as beam
    import extra_throws as throws
    import extra_reload_requests as reloads
    a=Assembler(base);camera.save(a);a.move(16,4);core.gate(a,'no')
    a.li(8,CONTROL);a.lw(9,8);a.li(11,camera.MAGIC);a.branch(5,9,11,'no')
    a.lw(9,8,4);a.lw(11,28,-22364);a.branch(5,9,11,'no');a.lw(9,8,12);a.branch(4,9,0,'no')
    a.lw(9,8,8);a.li(11,core.MODE+4);a.lw(11,11);a.branch(5,9,11,'no')
    emit_registered(a,16,17,'no','actor');beam.participating(a,17,'no')
    throws.hp(a,16,'no');throws.model(a,16,18,'no')
    emit_non_giant_model(a,18,'no')
    # Native1DC2C0/205E00 report this positive counter as an actor pause.
    # Starting during individual hit-stop would immediately split FX clocks.
    a.lw(8,16,4896);a.r(0x2A,9,0,8);a.branch(5,9,0,'no')
    # Director START requests11 via1E0290 then runs1E23D0. The dispatcher
    # invokes the outgoing handler's phase3 cleanup before switching to idle,
    # so ordinary charging/punching can accept without a leftover native loop.
    # Requested/queued hits and native cinematic actions remain excluded.
    a.lw(8,16,2376)
    if victim:
        for action in (*LAUNCHED_ACTIONS,217):a.li(9,action);a.branch(4,8,9,'ordinary_or_launched')
    a.addiu(9,8,-11);a.i(11,9,9,169);a.branch(4,9,0,'no')
    a.label('ordinary_or_launched')
    if victim:
        # 1E9590's ordinary knockback handler requests falling217 at1E97A0.
        # Native rush contact may arrive in that exact update. This is the
        # victim's own movement transition, not a pending hit or paired move;
        # START's normal outgoing-handler cleanup may replace it with idle.
        # All four follow-up queues and every hit/reload guard still apply.
        a.lw(8,16,2380);a.li(9,-1);a.branch(4,8,9,'pending_safe')
        a.li(9,217);a.branch(5,8,9,'no');a.lw(8,16,2376)
        for action in LAUNCHED_ACTIONS:a.li(9,action);a.branch(4,8,9,'pending_safe')
        a.jump('no');a.label('pending_safe')
    for off in ((2388,2392,2396,2400) if victim else (2380,2388,2392,2396,2400)):
        a.lw(8,16,off);a.li(9,0xFFFFFFFF);a.branch(5,8,9,'no')
    for off in (3480,3500,3512,0xFE0):a.lw(8,16,off);a.branch(5,8,0,'no')
    for flag in map(FLAG,(0xB,0xBE,0x94,0x125,0x126,0x135)):
        for bank in (0x1085,0x10AD):
            a.i(36,8,16,bank+(flag>>3));a.i(12,8,8,1<<(flag&7));a.branch(5,8,0,'no')
    a.i(11,8,17,2);a.branch(5,8,0,'ready')
    a.addiu(8,17,-2);a.r(0,8,0,8,6);a.li(9,reloads.RECORDS);a.r(0x21,8,8,9)
    a.lw(8,8,4);a.addiu(8,8,-1);a.i(11,8,8,2);a.branch(5,8,0,'no')
    a.label('ready');a.li(2,1);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');camera.restore(a,skip=(2,));a.jr()
    data=a.finish();assert base+len(data)<=(CONTROL if victim else VICTIM_PREFLIGHT);return data


def victim_preflight_code():
    return preflight_code(VICTIM_PREFLIGHT,victim=True)


def place_code():
    """a0 actor,a1 root XYZW,a2 Euler XYZW ->v0 success.

    Copies the requested point; clamps to the current expanded arena and live
    terrain, then refreshes the sector, collision and swept pose. No map-centre
    teleport or reliance on the beam-assist feature being installed.
    """
    import beam_struggle as beam
    import extra_throws as throws
    import arena_bounds
    a=Assembler(PLACE);beam.frame(a,beam.PLACE_REGS,beam.PLACE_FRAME)
    a.move(16,4);a.move(17,5);a.move(18,6);a.move(23,0)
    throws.ptr(a,16,0x1300,'done');throws.ptr(a,17,16,'done');throws.ptr(a,18,16,'done')
    throws.model(a,16,21,'done')
    POS,ROT=beam.POS,beam.ROT
    for off in range(0,16,4):
        a.lw(8,17,off);a.sw(8,29,POS+off);a.lw(8,18,off);a.sw(8,29,ROT+off)
    # Reject NaN/infinity before native terrain or matrix code sees it.
    for off in (POS,POS+4,POS+8,ROT,ROT+4,ROT+8):
        a.lw(8,29,off);a.li(9,0x7F800000);a.r(0x24,8,8,9);a.branch(4,8,9,'done')
    a.li(8,arena_bounds.STAGE);a.lw(12,8);throws.ptr(a,12,68,'done');a.lw(12,12,64)
    throws.ptr(a,12,12,'done')
    a.i(49,0,12,0);beam.fconst(a,1,110.0);beam.fop(a,1,0,0,1)
    beam.fconst(a,1,1.0);beam.fop(a,0x34,0,0,1);a.branch(17,8,1,'done')
    a.i(49,2,29,POS);a.i(49,3,29,POS+8)
    beam.fop(a,2,4,2,2);beam.fop(a,2,5,3,3);beam.fop(a,0,4,4,5);beam.fop(a,2,5,0,0)
    beam.fop(a,0x36,0,4,5);a.branch(17,8,1,'radial')
    beam.fop(a,4,4,4,4);beam.fop(a,3,0,0,4);beam.fop(a,2,2,2,0);beam.fop(a,2,3,3,0)
    a.i(57,2,29,POS);a.i(57,3,29,POS+8)
    a.label('radial');a.i(49,2,29,POS+4);beam.fconst(a,1,10.0)
    a.i(49,0,12,4);beam.fop(a,0,0,0,1);beam.fop(a,0x34,0,2,0);a.branch(17,8,0,'below_top');beam.fop(a,6,2,0)
    a.label('below_top');a.i(49,0,12,8);beam.fop(a,1,0,0,1);beam.fop(a,0x34,0,0,2);a.branch(17,8,0,'above_floor')
    beam.fop(a,6,2,0);a.label('above_floor');a.i(57,2,29,POS+4)
    a.addiu(4,29,POS);a.call(FLOOR);a.branch(4,2,0,'clamped');a.lw(9,29,POS+12);a.sw(9,29,POS+4)
    a.label('clamped');a.li(8,0x3F800000);a.sw(8,29,POS+12);a.sw(8,29,ROT+12)
    a.addiu(4,0,-1);a.addiu(5,29,POS);a.call(beam.SECTOR);a.move(7,2)
    a.move(4,16);a.addiu(5,29,POS);a.addiu(6,29,ROT);a.call(beam.SET_ROOT)
    for fn in beam.MODEL_REFRESH:a.move(4,21);a.call(fn)
    a.move(4,21);a.move(5,0);a.call(beam.MODEL_SPHERES);a.move(4,16);a.call(beam.ROOT_SYNC)
    a.addiu(8,16,16);a.addiu(9,16,256)
    a.label('copy');a.lw(10,8);a.sw(10,8,240);a.addiu(8,8,4);a.branch(5,8,9,'copy')
    a.lw(12,21,4000);a.lw(13,21,4004);throws.ptr(a,12,32,'success');throws.ptr(a,13,32,'success')
    for off in range(0,32,4):a.lw(10,12,off);a.sw(10,13,off)
    a.label('success');a.li(23,1);a.label('done');a.move(2,23);beam.unframe(a,beam.PLACE_REGS,beam.PLACE_FRAME);a.jr()
    data=a.finish();assert len(data)<=FLOOR-PLACE;return data


def trampoline_code(original):
    import cinematic_contact_guard as contact
    # An outer module can have installed a jump (with a NOP delay slot).
    if len(original)==8 and struct.unpack('<I',original[:4])[0]>>26==2 and original[4:]==bytes(4):
        destination=(struct.unpack('<I',original[:4])[0]&0x3FFFFFF)<<2
        if not 0x06000000<=destination<0x08000000 or destination in (CONTACT,TRAMPOLINE):
            raise ValueError('Unexpected tag-rush contact predecessor')
        return original
    native=contact.protected_code()
    if original==native:
        return core.rebound(contact.protected_code,PROTECTED=TRAMPOLINE)()
    raise ValueError('Unknown contact protection chain; tag rush was not installed')


def pieces(original):
    import beam_struggle as beam
    import spawn_placement as terrain
    out=[(CONTACT,contact_code()),(TRAMPOLINE,trampoline_code(original)),(DAMAGE,damage_code()),
         (PREFLIGHT,preflight_code()),(VICTIM_PREFLIGHT,preflight_code(VICTIM_PREFLIGHT,victim=True)),(PLACE,place_code()),
         (FLOOR,core.rebound(beam.floor_code,FLOOR=FLOOR,QUERY=QUERY)()),
         (QUERY,core.rebound(terrain.query_code,QUERY=QUERY,CONTROL=QUERY_STATS-16)()),
         (STATE,bytes(0x100))]
    for (p,b),(q,_) in zip(out,out[1:]):assert p+len(b)<=q,(hex(p),len(b),hex(q))
    return out


def build_memory(ram):
    import cinematic_contact_guard as contact
    head=bytes(ram[contact.PROTECTED:contact.PROTECTED+8])
    original=head if struct.unpack('<I',head[:4])[0]>>26==2 else bytes(ram[contact.PROTECTED:contact.PROTECTED+len(contact.protected_code())])
    out=pieces(original)
    for p,b in out:
        if any(ram[p:p+len(b)]):raise ValueError(f'Tag-rush safety space occupied at {p:08X}')
    out.append((contact.PROTECTED,struct.pack('<2I',0x08000000|(CONTACT>>2),0)))
    return {'blocks':[dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=b.hex()) for p,b in out]}
