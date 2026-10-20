"""Native scenario pause/results menus, with private filtered row tables."""
import struct
from native_map import A, elf_path
from prototype import ROOT, Assembler, elf_reader
import guest_killfeed as abi

BASE, ORIGINAL, DATA, END = 0x06970000, 0x06971000, 0x06972000, 0x06978000
ENTRY = A(0x212A10)
HEADERS=(A(0x2C5280),A(0x2C5408),A(0x2C5560),A(0x2C56E8),A(0x2C57B0),A(0x2C5878),
         A(0x2C5970),A(0x2C5A08),A(0x2C5B00),A(0x2C5BF8),A(0x2C5D20),A(0x2C5E48),A(0x2C5FD0),A(0x2C6038))


# Missions whose pause menu also gets the native Retry row (id 12, from the Dragon History pause layout, with the
# shared "EXIT?" Yes/No confirmation) where the native layout has none (the Duel pause a gauntlet match shows).
# Picking it ends the battle natively like the results screen's Fight Again; the watcher then reloads the prepared
# start (its rematch path). The row's own label index (0x13) reads "Reset standing position" in the Duel pause
# atlas, so it shows the atlas's "Fight Again" label (index 3, live: p90 labelscan), the disc's own language.
RETRY_ROW_MISSIONS = ('fighter-gauntlet',)
RETRY_ID, MAIN_MENU_ID, FIGHT_AGAIN_LABEL = 12, 15, 3


def allowed_ids(settings=None):
    settings=settings or {}
    # Title, Resume, Skill List, Main Menu; native confirmation submenus remain.
    result={1,8,9,15}
    if settings.get('retry',True):result.update((12,19))
    if settings.get('character_select',False):result.add(13)
    return result


def blocks(ram,mission):
    import story_runtime as story
    native=elf_reader(elf_path(ROOT))[2]
    if bytes(ram[ENTRY:ENTRY+8])!=native(ENTRY,8):raise ValueError('Scenario menu getter has an unknown hook')
    if any(ram[BASE:END]):raise ValueError('Scenario menu workspace is occupied')
    data=bytearray();mapping=[];allowed=allowed_ids(mission.get('menus'))
    retry_row=None
    if mission.get('id') in RETRY_ROW_MISSIONS and RETRY_ID in allowed:
        for source in HEADERS:
            pointer,count=struct.unpack_from('<2I',native(source,8))
            found=[native(pointer+48*i,48) for i in range(count) if struct.unpack_from('<I',native(pointer+48*i,48),4)[0]==RETRY_ID]
            if found:
                retry_row=bytearray(found[0]);struct.pack_into('<I',retry_row,0,FIGHT_AGAIN_LABEL*0x10001)
                retry_row=bytes(retry_row);break
    for source in HEADERS:
        header=bytearray(native(source,56));pointer,count=struct.unpack_from('<2I',header)
        if not 1<=count<=32:raise ValueError('Scenario menu row count changed')
        rows=[native(pointer+48*i,48) for i in range(count)]
        rows=[row for row in rows if struct.unpack_from('<I',row,4)[0] in allowed]
        # Some unrelated native layouts have no safe exit. They remain native;
        # scenario Team Battle uses the layouts with Resume/Retry/Main Menu.
        if not any(struct.unpack_from('<I',row,4)[0]==15 for row in rows):continue
        ids=[struct.unpack_from('<I',row,4)[0] for row in rows]
        if retry_row is not None and RETRY_ID not in ids and 19 not in ids:
            rows.insert(ids.index(MAIN_MENU_ID),retry_row)
        address=DATA+len(data);mapping.append((source,address))
        # These clones are installed after the native menu initializer ran.
        # Start them in its closed state rather than inheriting a selected row.
        struct.pack_into('<iII',header,20,-1,0,0)
        struct.pack_into('<2I',header,0,address+56,len(rows));data.extend(header);data.extend(b''.join(rows))
    a=Assembler(BASE);abi.prologue(a);a.call(ORIGINAL);a.i(63,2,29,abi.REG_OFFSET[2])
    story.guard(a,'done')
    for i,(old,new) in enumerate(mapping):
        a.li(8,old);a.branch(5,2,8,f'm{i}');a.li(8,new);a.i(63,8,29,abi.REG_OFFSET[2]);a.jump('done');a.label(f'm{i}')
    a.label('done');abi.epilogue(a)
    if DATA+len(data)>END:raise ValueError('Scenario menus exceed reserved memory')
    return [(BASE,a.finish()),(ORIGINAL,native(ENTRY,8)+story.jump(ENTRY+8)),
            (DATA,bytes(data)),(ENTRY,story.jump(BASE))]
