"""Native tag-only retargeting with one recipient bind per translated joint.

Some imported outfits repeat invisible hand markers. The native retargeter
walks every part, so duplicate markers would adjust the same decoded channel
twice. A stack-only recipient descriptor removes those repetitions; the real
mesh, hierarchy, bone pointers and ordinary animation bank are never edited.
"""
from prototype import Assembler
from native_map import A
import fusion_partner_lifecycle as full
import tag_team_rush as tag

BASE, END = 0x06D73000, 0x06D74000
RETARGET, CHECK, BUILD = BASE, BASE+0x300, BASE+0x600
NODES, META, STACK, TEMP_SIZE = 0x920, 0xA60, 0xAC0, 0x1000
BONES = (0, 2, 31, 45, 52)


def build_code(*, base=BUILD, end=END, bones=BONES, nodes=NODES, meta=META, stack=STACK):
    """a0 live model, a1 private TEMP_SIZE bytes ->v0 valid (no game writes)."""
    a=Assembler(base);tag.save(a);a.move(16,4);a.move(17,5)
    full.pointer(a,16,2400,'no');a.i(12,8,16,3);a.branch(5,8,0,'no');a.lw(18,16,68)
    # Both reviewed native height layouts are retained in the shallow model.
    for off,size in ((24,0x78),(2332,8)):
        a.lw(8,16,off);full.pointer(a,8,size,'no',temp=10,test=9);a.i(12,9,8,3);a.branch(5,9,0,'no');a.sw(8,17,off)
    a.sw(0,17,2328);a.addiu(8,17,nodes);a.sw(8,17,68)
    a.move(19,0);a.move(20,0);a.move(21,0)
    a.label('part');full.pointer(a,18,64,'no');a.i(12,8,18,3);a.branch(5,8,0,'no')
    a.lw(15,18);a.i(11,8,15,64);a.branch(5,8,0,'no')
    a.li(8,0x8000000);a.r(0x23,8,8,18);a.r(0x2B,8,8,15);a.branch(5,8,0,'no')
    a.i(37,14,18,10);a.branch(5,19,0,'root_checked');a.branch(5,14,0,'no');a.label('root_checked');a.li(22,-1);a.branch(4,20,0,'parent_ready')
    a.addiu(8,20,-1);a.r(0,8,0,8,2);a.r(0x21,8,17,8);a.lw(22,8,stack)
    a.label('parent_ready')
    for index,bone in enumerate(bones):
        a.li(8,bone);a.branch(4,14,8,'joint'+str(index))
    a.jump('next')
    for index in range(len(bones)):
        a.label('joint'+str(index));a.li(24,index);a.jump('joint')
    a.label('joint')
    for off in (16,20,24,32,36,40,48,52,56):
        a.lw(8,18,off);a.r(2,8,0,8,23);a.i(12,8,8,255);a.li(9,255);a.branch(4,8,9,'no')
    a.r(0,8,0,24,6);a.r(0x21,23,17,8);a.addiu(23,23,nodes)
    a.li(25,1);a.r(4,25,24,25);a.r(0x24,8,21,25);a.branch(5,8,0,'duplicate')
    a.r(0x25,21,21,25);a.r(0,8,0,24,2);a.r(0x21,8,17,8)
    a.sw(22,8,meta);a.sw(15,8,meta+4*len(bones))
    a.move(8,18);a.move(9,23);a.addiu(10,18,64)
    a.label('copy');a.lw(11,8);a.sw(11,9);a.addiu(8,8,4);a.addiu(9,9,4);a.branch(5,8,10,'copy')
    a.li(8,64);a.sw(8,23);a.i(41,0,23,6);a.jump('next')
    # Only identical invisible leaf hand markers are safe to deduplicate.
    # Root, body and contact marker duplicates remain a hard refusal.
    a.label('duplicate');a.li(8,31);a.branch(4,14,8,'hand');a.li(8,45);a.branch(5,14,8,'no')
    a.label('hand');a.li(8,64);a.branch(5,15,8,'no')
    a.r(0,9,0,24,2);a.r(0x21,9,17,9);a.lw(10,9,meta+4*len(bones));a.branch(5,10,8,'no')
    a.lw(10,9,meta);a.branch(5,10,22,'no')
    for source in (18,23):
        a.i(37,8,source,8);a.branch(5,8,0,'no')
        a.i(37,8,source,4);a.branch(4,8,0,'no')
    for off in (16,20,24,32,36,40,48,52,56):
        a.lw(8,18,off);a.lw(9,23,off);a.branch(5,8,9,'no')
    a.label('next')
    # Mirror the native part stack, bounded before every write and pop.
    a.i(11,8,20,256);a.branch(4,8,0,'no')
    a.r(0,8,0,20,2);a.r(0x21,8,17,8);a.sw(14,8,stack);a.addiu(20,20,1)
    a.i(37,8,18,4);a.r(0x2B,9,20,8);a.branch(5,9,0,'no');a.r(0x23,20,20,8)
    a.i(37,8,18,6);a.i(11,9,8,2);a.branch(4,9,0,'no');a.branch(5,8,0,'last')
    a.addiu(19,19,1);a.i(11,8,19,256);a.branch(4,8,0,'no')
    a.r(0x21,18,18,15);a.jump('part')
    a.label('last');a.li(8,(1<<len(bones))-1);a.branch(5,21,8,'no')
    a.i(11,8,20,2);a.branch(4,8,0,'no');a.branch(4,20,0,'complete')
    a.lw(8,17,stack);a.branch(5,8,0,'no')
    a.label('complete');a.li(8,1);a.i(41,8,17,nodes+64*(len(bones)-1)+6)
    a.li(2,1);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');tag.restore(a,2);a.jr();data=a.finish();assert base+len(data)<=end,len(data);return data


def entry_code(check=False, *, base=None, end=None, build=BUILD, temp_size=TEMP_SIZE):
    """CHECK(a0model) or RETARGET(a0decoded,a1model,a2donor) ->v0 valid."""
    entry=(CHECK if check else RETARGET) if base is None else base
    a=Assembler(entry);tag.save(a);a.move(16,4);a.move(17,5);a.move(18,6)
    a.addiu(29,29,-temp_size);a.move(4,16 if check else 17);a.move(5,29);a.call(build)
    a.branch(4,2,0,'done')
    if not check:
        a.move(4,16);a.move(5,29);a.move(6,18);a.move(7,0);a.move(8,0);a.call(A(0x24BBE8));a.li(2,1)
    a.label('done');a.addiu(29,29,temp_size);tag.restore(a,2);a.jr();data=a.finish()
    assert entry+len(data)<=((BUILD if check else CHECK) if end is None else end),len(data);return data


def pieces():
    return [(RETARGET,entry_code()),(CHECK,entry_code(True)),(BUILD,build_code())]
