"""Require the proposed dash pair to share a native body-contact observation.

Native 1C9010 asks whether either fighter touches *its own* selected opponent.
With more than two fighters those are not necessarily the proposed pair. The
producer at 1DF804 supplies the missing provenance; attack-volume collision is
deliberately not used, since dash clashes are driven by body collision instead.
The original dash program stays byte-identical underneath this guarded layer.
"""
from native_map import A, CRC, SERIAL, elf_path
import struct

from prototype import Assembler, ROOT, elf_reader
import beam_clash as beam
import dash_clash as dash
import fresh_team_combat as core
import battle_mode_policy as policy

CHECK, RECORD, END = dash.CODE+0x4400, dash.CODE+0x5000, dash.CODE+0x6000
STAMP, MAGIC = dash.CONTROL+40, 0x44435031
ROWS, STRIDE = dash.CONTROL+0x200, 64
# Per physical row: counterpart, both model pointers, resource/character and
# private allocation identities. Reloads must produce a fresh observation.
REJECTED, OBSERVED = dash.CONTROL+44, dash.CONTROL+48
PRODUCER, ORIGINAL = A(0x1DF804), A(0x1DABE8)
NATIVE = elf_reader(elf_path(ROOT))[2]
JUMP = lambda p: struct.pack('<2I',(2<<26)|(p>>2),0)
CALL = lambda p: struct.pack('<I',(3<<26)|(p>>2))


def scan(a, actor, index, prefix, fail):
    """Captured pointer identity, including while actor+0 is an AI role alias."""
    a.li(8,core.POINTERS);a.li(9,dash.CONTROL);a.lw(10,9,8);a.move(index,0)
    a.label(prefix);a.lw(11,8);a.branch(4,actor,11,prefix+'_found')
    a.addiu(index,index,1);a.addiu(8,8,4);a.branch(5,index,10,prefix);a.jump(fail)
    a.label(prefix+'_found');a.r(0,8,0,index,2);a.addiu(9,9,0x100)
    a.r(0x2D,9,9,8);a.lw(9,9);a.branch(5,actor,9,fail)


def record_code():
    # Original a0/s3 is the actor whose body was pushed away from its opponent.
    # Resolve while its real native geometry/AI context is still in scope.
    a=Assembler(RECORD);beam.save(a);a.move(16,4)
    a.call(dash.GATE);a.branch(4,2,0,'native')
    scan(a,16,17,'source','native')
    a.r(0,8,0,17,6);a.li(18,ROWS);a.r(0x2D,18,18,8);a.sw(0,18)
    a.move(4,16);a.call(core.RESOLVER);a.move(19,2)
    scan(a,19,20,'target','native');a.branch(4,17,20,'native')
    dash.throws.model(a,16,21,'native');dash.throws.model(a,19,22,'native')
    a.sw(21,18,4);a.sw(22,18,8)
    for model,offset in ((21,12),(22,24)):
        for field,relative in ((20,0),(12,4),(5728,8)):
            a.lw(8,model,field);a.sw(8,18,offset+relative)
    a.sw(19,18);a.li(8,OBSERVED);a.lw(9,8);a.addiu(9,9,1);a.sw(9,8)
    a.label('native');beam.restore(a);a.jump(ORIGINAL)
    data=a.finish();assert len(data)<=END-RECORD;return data


def check_code():
    a=Assembler(CHECK);beam.save(a);a.call(dash.GATE);a.branch(4,2,0,'prior')
    # Native s0/s1 are the proposed pair, s4 selects 250 versus 251.
    # Keep the native vertical/contact eligibility check, but only on a side
    # whose actual body-contact producer named this exact other fighter.
    for src,dst,prefix in ((16,17,'left'),(17,16,'right')):
        scan(a,src,18,prefix,prefix+'_next')
        a.r(0,8,0,18,6);a.li(19,ROWS);a.r(0x2D,19,19,8);a.lw(9,19)
        a.branch(5,9,dst,prefix+'_next')
        dash.throws.model(a,src,20,prefix+'_next');dash.throws.model(a,dst,21,prefix+'_next')
        for model,pointer,offset in ((20,4,12),(21,8,24)):
            a.lw(8,19,pointer);a.branch(5,8,model,prefix+'_next')
            for field,relative in ((20,0),(12,4),(5728,8)):
                a.lw(8,model,field);a.lw(9,19,offset+relative);a.branch(5,8,9,prefix+'_next')
        a.move(4,src);a.call(A(0x1DEEA8));a.branch(5,2,0,'prior')
        a.label(prefix+'_next')
    a.li(8,REJECTED);a.lw(9,8);a.addiu(9,9,1);a.sw(9,8)
    beam.restore(a);a.jump(A(0x1C9218))  # native next-actor path, before any flags
    a.label('prior');beam.restore(a);a.jump(dash.START)
    data=a.finish();assert len(data)<=RECORD-CHECK;return data


def pieces():
    return [(CHECK,check_code()),(RECORD,record_code()),
            (dash.bounds.HOOK,JUMP(CHECK)),(PRODUCER,CALL(RECORD)),
            (STAMP,struct.pack('<I',MAGIC))]


def native_dependencies():
    return [(A(0x1DEEA8),NATIVE(A(0x1DEEA8),0xC4)),
            (A(0x1DF4A8),NATIVE(A(0x1DF4A8),PRODUCER-A(0x1DF4A8))),
            (PRODUCER+4,NATIVE(PRODUCER+4,A(0x1DF85C)-(PRODUCER+4)))]


def overlay(ram):
    """Recognize only the complete exact additive layer; mutable rows are free."""
    if not any(ram[CHECK:END]) and not any(ram[STAMP:STAMP+4]):return []
    out=pieces()
    for p,b in out:
        if ram[p:p+len(b)]!=b:raise ValueError(f'Changed dash contact provenance {p:08X}')
    for p,b in native_dependencies():
        if ram[p:p+len(b)]!=b:raise ValueError(f'Changed native body-contact dependency {p:08X}')
    return out+native_dependencies()


@policy.matching_install
def build_memory(ram, source='<prepared>'):
    import multi_contact
    if len(ram)!=0x8000000:raise ValueError('Dash contact guard requires 128 MiB RAM')
    # Validates original captured identities, code and any exact existing layer.
    if multi_contact.prior_manifest(ram,dash.build_memory)['blocks']:
        raise ValueError('Install complete captured dash chain first')
    if overlay(ram):return dict(source=str(source),blocks=[],status='DASH CONTACT PAIR VERIFIED')
    if ram[dash.bounds.HOOK:dash.bounds.HOOK+8]!=JUMP(dash.START):
        raise ValueError('Unknown dash contact predecessor')
    if ram[PRODUCER:PRODUCER+8]!=NATIVE(PRODUCER,8) or NATIVE(PRODUCER,4)!=CALL(ORIGINAL):
        raise ValueError('Native body-contact producer changed')
    for p,b in native_dependencies():
        if ram[p:p+len(b)]!=b:raise ValueError(f'Native body-contact dependency changed {p:08X}')
    if any(ram[STAMP:STAMP+16]) or any(ram[ROWS:ROWS+STRIDE*policy.ENGINE_ACTORS]):
        raise ValueError('Dash contact provenance storage occupied')
    payload=pieces()+[(ROWS,bytes(STRIDE*policy.ENGINE_ACTORS))]
    return dict(serial=SERIAL,crc=CRC,source=str(source),
                status='ACTUAL BODY-PAIR DASH ADMISSION; GAMEPLAY TEST REQUIRED',
                counters=dict(observed=OBSERVED,rejected=REJECTED),
                blocks=[dict(address=p,expected_hex=ram[p:p+len(b)].hex(),data_hex=b.hex()) for p,b in payload])
