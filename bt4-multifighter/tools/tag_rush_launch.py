"""Scoped resources for the game's own rush action285/1F8C00.

The game owns startup, pause, camera, steering, contact and miss animation.
Only its move data is temporarily borrowed; the real actor and voice stay.
"""
import struct
from prototype import Assembler,ROOT,elf_reader
from native_map import A,elf_path
import tag_team_rush as tag
import fusion_partner_lifecycle as full
import extra_throws as actors
import cinematic_contact_guard as contact

CHECK,ENTER,RESTORE=0x06D9B000,0x06D9BC00,0x06D9CC00
RETARGET,CONTACT,CONTACT_OLD=0x06D9D800,0x06D9E000,0x06D9E800
COMMIT=0x06D9C200
RESET_MARKER=0x06D9E900
STATE,END=0x06D9F000,0x06DA0000
PARAMS,CAMERA=STATE+0x100,STATE+0x400
TABLE_OFFSET=0xB0;MAGIC=0x54414C31;NATIVE_MAGIC=0x54414E31
FRAMES=(13,30,13,9,6);ANIMATIONS=(329,330,331,332,335,352,353,354,355,356,363)
P=dict(owned=0,manager=4,count=8,params=12,camera=16,pointers=32,scratch=80,marker=84,marker_owned=88,dispatch=92)
NATIVE=elf_reader(elf_path(ROOT))[2]
CONTACT_HOOK=A(0x1CA6D0);RETARGET_HOOK=A(0x24D148)
RETARGET_NATIVE=struct.pack('<I',(3<<26)|(A(0x24BBE8)>>2))
RETARGET_PATCH=struct.pack('<I',(3<<26)|(RETARGET>>2))
COMMIT_HOOK=A(0x1E2428)
COMMIT_NATIVE=struct.pack('<I',(3<<26)|(A(0x1E12D0)>>2))
COMMIT_PATCH=struct.pack('<I',(3<<26)|(COMMIT>>2))
CONTACT_PATCH=struct.pack('<2I',(2<<26)|(CONTACT>>2),0)


def table(a,out,fail):
    a.li(out,tag.CONTROL);a.lw(out,out,TABLE_OFFSET)
    full.pointer(a,out,56,fail,temp=10,test=9)
    a.lw(8,out);a.li(9,MAGIC);a.branch(5,8,9,fail)
    a.lw(8,out,8);a.li(9,5);a.branch(5,8,9,fail)


def owned(a,fail):
    import tag_rush_approach as rush
    a.li(8,tag.CONTROL);a.lw(9,8);a.li(10,tag.MAGIC);a.branch(5,9,10,fail)
    a.lw(9,8,tag.C['approaching']);a.li(10,1);a.branch(5,9,10,fail)
    a.lw(9,8,tag.C['manager']);a.lw(10,28,-22364);a.branch(5,9,10,fail)
    a.li(8,STATE);a.lw(9,8,P['owned']);a.li(10,1);a.branch(5,9,10,fail)
    a.lw(9,8,P['manager']);a.lw(10,28,-22364);a.branch(5,9,10,fail)
    a.li(8,rush.STATE);a.lw(9,8);a.li(10,rush.MAGIC);a.branch(5,9,10,fail)
    a.lw(9,8,rush.S['active']);a.li(10,1);a.branch(5,9,10,fail)


def copy_words(a,src,dst,size,label):
    a.addiu(10,src,size);a.label(label);a.lw(11,src);a.sw(11,dst)
    a.addiu(src,src,4);a.addiu(dst,dst,4);a.branch(5,src,10,label)


def check_code():
    a=Assembler(CHECK);tag.save(a);a.move(16,4);table(a,17,'no')
    full.pointer(a,16,6000,'no');a.lw(8,16,5728);full.pointer(a,8,98348,'no',temp=10)
    a.lw(8,17,4);full.pointer(a,8,2400,'no',temp=10)
    for n,count in enumerate(FRAMES):
        a.lw(8,17,16+8*n);full.pointer(a,8,8,'no',temp=10);a.lw(8,8)
        a.i(11,9,8,148);a.branch(5,9,0,'no');a.li(9,0xC000);a.r(0x2B,9,9,8);a.branch(5,9,0,'no')
        a.lw(8,17,20+8*n);a.li(9,count);a.branch(5,8,9,'no')
    a.lw(18,17,12);full.pointer(a,18,32,'no');a.lw(8,18);a.li(9,NATIVE_MAGIC);a.branch(5,8,9,'no')
    for off,size in ((4,640),(12,384)):
        a.lw(8,18,off+4);a.li(9,size);a.branch(5,8,9,'no')
        a.lw(8,18,off);full.pointer(a,8,size,'no',temp=10)
    a.lw(20,18,20);full.pointer(a,20,24,'no');a.lw(8,18,24);a.li(9,6);a.branch(5,8,9,'no')
    for n in range(6):
        a.lw(8,20,4*n);full.pointer(a,8,8,'no',temp=10);a.lw(8,8)
        a.i(11,9,8,148);a.branch(5,9,0,'no');a.li(9,0xC000);a.r(0x2B,9,9,8);a.branch(5,9,0,'no')
    for off,size in ((2348,640),(2360,384)):
        a.lw(8,16,off);full.pointer(a,8,size,'no',temp=10)
    a.li(2,1);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');tag.restore(a,2);a.jr();data=a.finish();assert CHECK+len(data)<=ENTER;return data


def enter_code():
    import tag_rush_approach as rush
    a=Assembler(ENTER);tag.save(a);a.li(21,rush.ROWS);rush.identity(a,21,'no','enter')
    a.move(4,23);a.call(CHECK);a.branch(4,2,0,'no');table(a,19,'no');a.lw(20,19,12)
    a.li(18,STATE);a.lw(8,18,P['owned']);a.branch(5,8,0,'no')
    for off,key in ((2348,'params'),(2360,'camera')):a.lw(8,23,off);a.sw(8,18,P[key])
    for n,index in enumerate(ANIMATIONS):a.lw(8,23,192+4*index);a.sw(8,18,P['pointers']+4*n)
    a.lw(8,20,4);a.li(9,PARAMS);copy_words(a,8,9,640,'parameters')
    a.lw(8,20,12);a.li(9,CAMERA);copy_words(a,8,9,384,'camera')
    # The tag meter pays for this request. All four native contact variants
    # enter rush reaction34, including a defender's ordinary held guard.
    a.li(8,PARAMS);a.sw(0,8,420);a.sw(0,8,396);a.sw(0,8,408);a.li(9,34)
    for off in (323,326,329,332):a.i(40,9,8,off)
    a.sw(8,23,2348);a.li(8,CAMERA);a.sw(8,23,2360)
    for n,index in enumerate(ANIMATIONS):
        if n<5:a.lw(8,19,16+8*n)
        else:a.lw(8,20,20);a.lw(8,8,4*(n-5))
        a.sw(8,23,192+4*index)
    a.lw(8,23,5728);a.sw(8,18,P['scratch']);a.li(9,98344);a.r(0x21,8,8,9)
    a.lw(9,8);a.sw(9,18,P['marker']);a.li(9,1);a.sw(9,8);a.sw(9,18,P['marker_owned'])
    a.li(8,tag.CONTROL)
    for key in ('manager','count'):a.lw(9,8,tag.C[key]);a.sw(9,18,P[key])
    a.li(8,1);a.sw(8,18,P['owned']);a.sw(8,18,P['dispatch']);a.li(2,1);a.jump('done')
    a.label('no');a.move(2,0);a.label('done');tag.restore(a,2);a.jr()
    data=a.finish();assert ENTER+len(data)<=COMMIT;return data


def commit_code():
    """One native selection boundary: prevent the tag's L2 from replacing261.

    E23D0 runs the old action's phase2 handler before applying pending actions.
    Our accepted tag request supplies its queue only after that handler; later
    native transitions, hits and misses are completely ordinary.
    """
    import tag_rush_approach as rush
    a=Assembler(COMMIT);tag.save(a);a.move(16,4);a.call(A(0x1E12D0));a.move(18,2)
    owned(a,'done');a.li(17,STATE);a.lw(8,17,P['dispatch']);a.li(9,1);a.branch(5,8,9,'done')
    a.li(21,rush.ROWS);rush.identity(a,21,'done','commit');a.branch(5,16,22,'done')
    a.lw(8,23,2348);a.li(9,PARAMS);a.branch(5,8,9,'done')
    a.sw(0,17,P['dispatch'])
    a.move(4,22);a.move(5,0);a.li(6,261);a.call(A(0x1E02A8))
    a.move(4,22);a.li(5,1);a.li(6,285);a.call(A(0x1E02A8))
    a.move(4,22);a.li(5,261);a.call(A(0x1E0290))
    a.label('done');a.move(2,18);tag.restore(a,2);a.jr()
    data=a.finish();assert COMMIT+len(data)<=RESTORE;return data


def restore_code():
    import tag_rush_approach as rush
    a=Assembler(RESTORE);tag.save(a);a.call(RESET_MARKER);a.li(18,STATE);a.lw(8,18,P['owned']);a.branch(4,8,0,'done')
    a.lw(8,18,P['manager']);a.lw(9,28,-22364);a.branch(5,8,9,'release')
    a.li(8,tag.CONTROL);a.lw(8,8,tag.C['count']);a.lw(9,18,P['count']);a.branch(5,8,9,'release')
    a.li(21,rush.ROWS);rush.identity(a,21,'release','restore');table(a,19,'release');a.lw(20,19,12)
    for off,key,expected in ((2348,'params',PARAMS),(2360,'camera',CAMERA)):
        a.lw(8,23,off);a.li(9,expected);a.branch(5,8,9,'restore_next'+key)
        a.lw(8,18,P[key]);a.sw(8,23,off);a.label('restore_next'+key)
    for n,index in enumerate(ANIMATIONS):
        a.lw(8,23,192+4*index)
        if n<5:a.lw(9,19,16+8*n)
        else:a.lw(9,20,20);a.lw(9,9,4*(n-5))
        a.branch(5,8,9,'pointer_next'+str(n));a.lw(8,18,P['pointers']+4*n);a.sw(8,23,192+4*index)
        a.label('pointer_next'+str(n))
    a.label('release');a.sw(0,18,P['owned']);a.sw(0,18,P['dispatch']);a.label('done');tag.restore(a);a.jr()
    data=a.finish();assert RESTORE+len(data)<=RETARGET;return data


def retarget_code():
    """Exact24D038 callsite: replace self donor only for this borrowed clip."""
    import tag_rush_approach as rush
    a=Assembler(RETARGET);tag.save(a);a.move(16,5);a.move(17,4);a.move(18,20)
    owned(a,'native');a.li(21,rush.ROWS);rush.identity(a,21,'native','retarget')
    a.branch(5,16,23,'native');a.li(8,PARAMS);a.lw(9,23,2348);a.branch(5,8,9,'native')
    for index in ANIMATIONS:a.li(8,index);a.branch(4,18,8,'borrowed')
    a.jump('native');a.label('borrowed');table(a,19,'native');a.move(4,17);a.move(5,16);a.lw(6,19,4);a.move(7,0);a.move(8,0)
    a.call(A(0x24BBE8));tag.restore(a,2);a.jr()
    a.label('native');tag.restore(a);a.jump(A(0x24BBE8))
    data=a.finish();assert RETARGET+len(data)<=CONTACT;return data


def contact_code():
    """The real collision has reached a rush capture; no paired actor writes."""
    import tag_rush_approach as rush
    a=Assembler(CONTACT);tag.save(a);a.move(16,4);a.move(17,5);a.move(18,6)
    owned(a,'native');a.li(21,rush.ROWS);rush.identity(a,21,'native','contact')
    a.branch(5,16,22,'native');a.li(8,4);a.branch(5,18,8,'native')
    a.lw(8,22,2376);a.li(9,285);a.branch(5,8,9,'native')
    # Preserve the game's installed outside-contact and scenario isolation.
    a.move(4,16);a.move(5,17);a.call(contact.PROTECTED);a.branch(5,2,0,'blocked')
    a.li(8,rush.STATE);a.lw(9,8,rush.S['contact']);a.branch(5,9,0,'blocked')
    a.li(21,rush.ROWS+2*rush.STRIDE);rush.identity(a,21,'blocked','victim')
    a.branch(5,17,22,'wrong_target');a.li(8,rush.STATE);a.li(9,1);a.sw(9,8,rush.S['contact'])
    a.jump('blocked');a.label('wrong_target');a.li(8,rush.STATE);a.li(9,8);a.sw(9,8,rush.S['reason'])
    a.li(9,2);a.sw(9,8,rush.S['contact'])
    a.label('blocked');a.move(2,0);tag.restore(a,2);a.jr()
    a.label('native');tag.restore(a);a.jump(CONTACT_OLD)
    data=a.finish();assert CONTACT+len(data)<=CONTACT_OLD;return data


def reset_marker_code():
    """End only this overlay's retarget override before decoding a normal pose."""
    import tag_rush_approach as rush
    a=Assembler(RESET_MARKER);tag.save(a);a.li(18,STATE)
    a.lw(8,18,P['owned']);a.branch(4,8,0,'done');a.lw(8,18,P['marker_owned']);a.branch(4,8,0,'done')
    a.lw(8,18,P['manager']);a.lw(9,28,-22364);a.branch(5,8,9,'release')
    a.li(21,rush.ROWS);rush.identity(a,21,'release','marker')
    a.lw(8,23,5728);a.lw(9,18,P['scratch']);a.branch(5,8,9,'release')
    full.pointer(a,8,98348,'release',temp=10);a.li(9,98344);a.r(0x21,8,8,9)
    a.lw(9,8);a.li(10,1);a.branch(5,9,10,'release');a.lw(9,18,P['marker']);a.sw(9,8)
    a.label('release');a.sw(0,18,P['marker_owned']);a.label('done');tag.restore(a);a.jr()
    data=a.finish();assert RESET_MARKER+len(data)<=STATE;return data


def pieces():
    return [(CHECK,check_code()),(ENTER,enter_code()),(COMMIT,commit_code()),(RESTORE,restore_code()),
            (RETARGET,retarget_code()),(CONTACT,contact_code()),(RESET_MARKER,reset_marker_code()),(STATE,bytes(END-STATE))]
