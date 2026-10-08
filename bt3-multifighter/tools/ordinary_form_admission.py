"""Admit ordinary forms around unrelated specials without overlapping reloads.

Fusion/tag entry remains serialized. Keep the established native eligibility,
stock cost, extra heap admission, and private reload handshake behind each
wrapper. Only the two ordinary-form wrappers get the narrower predicate.
"""
from native_map import CRC, SERIAL, elf_path
import struct
import cinematic_admission as old
import ordinary_transform_guard as ordinary
import special_concurrency as concurrent
from prototype import ROOT, elf_reader

PREDICATE = 0x077F9000  # Inside concurrent's reserved region, after its predicate.


def predicate_code():
    if concurrent.PREDICATE+len(concurrent.predicate_code())>PREDICATE:
        raise ValueError('Special and ordinary form admission code overlap')
    return concurrent.predicate_code(base=PREDICATE, ordinary_form=True)


def wrapper_parts(native):
    result=[]
    for index,(entry,cave,_) in enumerate(ordinary.ENTRIES,7):
        args=(entry,cave,cave+0x200,native(entry,8),index)
        result.append((cave,old.wrapper(*args),
            concurrent.core.rebound(old.wrapper,PREDICATE=PREDICATE)(*args)))
    return result


def build_memory(ram, source='<prepared>'):
    if len(ram)!=0x8000000:raise ValueError('Requires128MiB EE RAM')
    # Admission opens only over the complete verified camera/special layer.
    if concurrent.build_memory(ram,source=source)['blocks']:
        raise ValueError('Install concurrent specials before ordinary forms')
    native=elf_reader(elf_path(ROOT))[2]
    body=predicate_code()
    prior=ram[PREDICATE:PREDICATE+len(body)]
    if prior not in (bytes(len(body)),body):
        raise ValueError('Ordinary form admission reservation changed')
    pieces=[(PREDICATE,body)]
    for cave,previous,updated in wrapper_parts(native):
        if ram[cave:cave+len(updated)] not in (previous,updated):
            raise ValueError(f'Ordinary form admission wrapper changed at {cave:08X}')
        pieces.append((cave,updated))
    return dict(serial=SERIAL,crc=CRC,source=str(source),status='ORDINARY FORMS WITH EXCLUSIVE RELOADS',
        blocks=[dict(address=p,expected_hex=ram[p:p+len(d)].hex(),data_hex=d.hex())
                for p,d in pieces if ram[p:p+len(d)]!=d])
