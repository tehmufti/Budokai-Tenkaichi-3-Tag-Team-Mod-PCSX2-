"""Disc-derived tag beam pose overrides; ordinary animation banks stay intact.

Only reviewed character policy chooses an own slot, generic clash, or donated
beam sequence. Donated clips carry their real bind skeleton and native muzzle
flags. Runtime decoding uses the director's already scoped index-zero entry.
"""
import hashlib
import struct

from prototype import Assembler
from native_map import A, ACTOR_HZ
import beam_struggle as fp
import tag_team_rush as tag
import fusion_partner_lifecycle as full

BASE, DATA, END = 0x06DE0000, 0x06DE4000, 0x06E00000
QUERY, DONOR_PLAY = BASE, BASE+0x800
RETARGET8, CHECK8, BUILD8 = BASE+0x1000, BASE+0x1300, BASE+0x1600
RETARGET6, CHECK6, BUILD6 = BASE+0x2000, BASE+0x2300, BASE+0x2600
CHECK, RETARGET = BASE+0x3000, BASE+0x3400
BONES = (0,2,31,45,46,47,52,54)
TABLE_OFFSET = 0xB4
MAGIC = 0x54425031
HEADER, STRIDE = 16, 8
BANK_SIZE = 32
# Native source model, fire clip, slot flags, bind-set kind; four BPE pointers.
BANK_MODEL, BANK_FIRE, BANK_FLAGS, BANK_KIND, BANK_CLIPS = 0, 4, 8, 12, 16


def _source_model(skeleton, base):
    """The same two native height ABIs as the choreography's donor models."""
    rows=skeleton['rows'];model=bytearray(0x920)
    nodes=base+len(model);height=nodes+64*len(rows)
    struct.pack_into('<I',model,24,base+0x100)
    struct.pack_into('<f',model,0x174,skeleton['height'])
    struct.pack_into('<I',model,68,nodes)
    struct.pack_into('<I',model,2332,height)
    return bytes(model)+b''.join(row['header'] for row in rows)+struct.pack('<If',0,skeleton['height'])


def build_assets(iso, *, bt4=False, policy=None):
    """Compile immutable selected-disc profiles; never load another game's assets."""
    import model_assets
    import tag_rush_assets as assets
    from model_animations import decompress_animation, AnimationClip
    if policy is None:
        import tag_beam_profiles
        policy=lambda character:tag_beam_profiles.profile(character,bt4=bt4)
    count=250 if bt4 else 161
    data=bytearray(HEADER+STRIDE*count);banks={};donors={};proof=[];native_banks={}
    def align():data.extend(bytes((-len(data))%16))
    def bank(character):
        if character not in native_banks:native_banks[character]=model_assets.read_animation_bank(iso,character)
        return native_banks[character]
    def clip(character,animation):
        packed=model_assets.package_entry(bank(character),animation+1)
        raw=decompress_animation(packed)
        if not 148<=len(raw)<=49152 or not 1<=struct.unpack_from('<H',raw,2)[0]<=3600:
            raise ValueError('Invalid tag beam source animation')
        return raw
    for character in range(count):
        row=policy(character);mode=row.get('mode','auto')
        if mode=='auto':continue
        if mode not in ('own','generic','donor'):raise ValueError('Unknown tag beam pose mode')
        slot=row.get('slot',0)
        if mode!='generic' and slot not in (2,3,4):raise ValueError('Invalid tag beam slot')
        fire=364 if mode=='generic' else 196+34*slot;source=row.get('donor') if mode=='donor' else character
        if type(source) is not int or not 0<=source<count:raise ValueError('Invalid tag beam pose donor')
        raw=clip(source,fire)
        if mode=='own':
            for animation in range(fire-3,fire):clip(source,animation)
        proof.append(dict(character=character,source=source,fire=fire,sha256=hashlib.sha256(raw).hexdigest()))
        pointer=0
        if mode=='donor':
            key=(source,slot)
            if key not in banks:
                if source not in donors:
                    align();donors[source]=DATA+len(data)
                    data.extend(_source_model(assets.read_skeleton(iso,source),donors[source]))
                clips=[];translated=set()
                for animation in range(fire-3,fire+1):
                    raw=clip(source,animation)
                    translated.update(track.bone_id for track in AnimationClip.from_decoded(animation,raw).tracks
                                      if any(key.translation is not None for key in track.keys))
                    align();clips.append(DATA+len(data));data.extend(assets.literal_pack(raw))
                parameters=(model_assets.package_entry(model_assets.read_archive_entry(iso,4150+source),2)[0x29D0:0x2C50]
                            if bt4 else model_assets.package_entry(assets._mesh_package(iso,source),24))
                if len(parameters)!=640:raise ValueError('Invalid beam donor metadata')
                flags=struct.unpack_from('<I',parameters,4*(slot-2))[0]
                align();banks[key]=DATA+len(data)
                if not translated.issubset(BONES):raise ValueError('Beam donor translates an unreviewed joint')
                kind=8 if translated.intersection((46,47)) else 6 if 54 in translated else 5
                data.extend(struct.pack('<8I',donors[source],fire,flags,kind,*clips))
            pointer=banks[key]
        struct.pack_into('<2I',data,HEADER+STRIDE*character,fire,pointer)
    align()
    if DATA+len(data)>END:raise ValueError('Tag beam profiles exceed their reserved storage')
    struct.pack_into('<4I',data,0,MAGIC,count,len(data),0)
    payload=bytes(data)
    return dict(blocks=[(DATA,payload)],table_address=DATA,characters=count,bytes_used=len(data),
                sha256=hashlib.sha256(payload).hexdigest(),sources=proof,reviewed=True)


def query_code():
    """a0 live model ->v0 fire (0 auto/-1 invalid),v1 donor bank (0 own)."""
    a=Assembler(QUERY);tag.save(a);a.move(16,4);a.move(2,0);a.move(3,0)
    a.li(8,tag.CONTROL);a.lw(17,8,TABLE_OFFSET);a.branch(4,17,0,'done')
    a.li(8,DATA);a.branch(5,17,8,'no');a.lw(8,17);a.li(9,MAGIC);a.branch(5,8,9,'no')
    a.lw(18,17,4);a.addiu(8,18,-1);a.i(11,8,8,250);a.branch(4,8,0,'no')
    a.lw(19,17,8);a.li(8,END-DATA);a.r(0x2B,8,8,19);a.branch(5,8,0,'no')
    a.r(0,8,0,18,3);a.addiu(8,8,HEADER);a.r(0x2B,8,19,8);a.branch(5,8,0,'no')
    full.pointer(a,16,0x1700,'no');a.lw(20,16,12);a.r(0x2B,8,20,18);a.branch(4,8,0,'no')
    a.r(0,8,0,20,3);a.r(0x21,8,8,17);a.lw(2,8,HEADER);a.lw(3,8,HEADER+4)
    a.branch(4,2,0,'auto')
    for fire in (264,298,332,364):a.li(8,fire);a.branch(4,2,8,'valid_clip')
    a.jump('no');a.label('valid_clip');a.branch(4,3,0,'done')
    a.i(12,8,3,15);a.branch(5,8,0,'no')
    a.li(8,DATA+HEADER);a.r(0,9,0,18,3);a.r(0x21,8,8,9)
    a.r(0x2B,8,3,8);a.branch(5,8,0,'no')
    a.r(0x21,19,19,17);a.addiu(8,3,BANK_SIZE);a.r(0x2B,8,19,8);a.branch(5,8,0,'no')
    a.lw(8,3,BANK_KIND)
    for kind in (5,6,8):a.li(9,kind);a.branch(4,8,9,'kind')
    a.jump('no');a.label('kind')
    a.lw(8,3,BANK_FIRE);a.branch(5,8,2,'no');a.li(8,364);a.branch(4,2,8,'no')
    a.lw(8,3,BANK_MODEL);a.i(12,9,8,15);a.branch(5,9,0,'no');a.li(9,DATA);a.r(0x2B,9,8,9);a.branch(5,9,0,'no')
    a.addiu(8,8,0x920);a.r(0x2B,8,19,8);a.branch(5,8,0,'no')
    for offset in range(BANK_CLIPS,BANK_SIZE,4):
        a.lw(8,3,offset);a.i(12,9,8,15);a.branch(5,9,0,'no')
        a.li(9,DATA);a.r(0x2B,9,8,9);a.branch(5,9,0,'no')
        a.addiu(9,8,8);a.r(0x2B,9,19,9);a.branch(5,9,0,'no')
        a.lw(9,8,4);a.addiu(10,8,8);a.r(0x23,10,19,10);a.r(0x2B,9,10,9);a.branch(5,9,0,'no')
        a.lw(8,8);a.addiu(8,8,-148);a.li(9,49152-148+1);a.r(0x2B,8,8,9);a.branch(4,8,0,'no')
    a.jump('done');a.label('auto');a.branch(5,3,0,'no');a.jump('done')
    a.label('no');a.li(2,-1);a.move(3,0)
    a.label('done');a.i(31,3,29,full.OFFSETS[3]);tag.restore(a,2)
    # tag.restore preserves v1 as well: return the explicit donor result.
    a.jr();code=a.finish();assert QUERY+len(code)<=DONOR_PLAY;return code



def donor_play_code():
    """a0 capture row,a1 semantic donor clip -> v0 success.

    Native 1C3E60 supplies the normal short animation blend. Index zero and its
    decode marker are scoped to the tag scene; retarget exactly once from the
    preserved source bind. No normal move slot or model identity is replaced.
    """
    import tag_rush_native_pose as pose
    a=Assembler(DONOR_PLAY);tag.save(a);a.move(16,4);a.move(17,5)
    a.lw(18,16,8);a.move(4,18);a.call(QUERY);a.branch(1,2,0,'no')
    a.branch(4,3,0,'no');a.lw(8,16,pose.BANK);a.branch(5,8,3,'no');a.move(19,3)
    a.addiu(8,2,-3);a.r(0x23,8,17,8);a.i(11,9,8,4);a.branch(4,9,0,'no')
    a.r(0,8,0,8,2);a.r(0x21,8,8,19);a.lw(20,8,BANK_CLIPS)
    a.lw(21,18,5728);full.pointer(a,21,98348,'no',temp=10)
    a.li(8,98344);a.r(0x21,21,21,8);a.lw(22,21)
    # Idle index0 follows the ordinary unpaired decode branch.
    a.move(4,0);a.call(A(0x1C4650));a.li(8,0x20000000);a.r(0x24,8,8,2);a.branch(5,8,0,'no')
    # Both native classes take the same1C3CA8 root-channel normalization.
    # Refuse an altered ISO's incompatible idle semantics before any write.
    a.li(8,0xE0000002);a.r(0x24,23,8,2);a.move(4,17);a.call(A(0x1C4650))
    a.li(8,0xE0000002);a.r(0x24,8,8,2);a.branch(5,8,23,'no')
    a.sw(0,21);a.sw(20,18,192);a.sw(20,16,180)
    a.sw(20,16,pose.POINTER);a.sw(17,16,pose.CLIP)
    a.lw(4,16,4);a.move(5,0);fp.fconst(a,12,.2);a.call(A(0x1C3E60))
    a.sw(22,21)
    a.lw(4,18,2880);a.move(5,18);a.lw(6,19,BANK_MODEL);a.move(7,0);a.move(8,0)
    a.call(RETARGET);a.branch(4,2,0,'no')
    fp.fconst(a,0,1/(.2*ACTOR_HZ));a.i(57,0,18,3208)
    a.li(2,1);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');tag.restore(a,2);a.jr();code=a.finish()
    assert DONOR_PLAY+len(code)<=RETARGET8;return code


def dispatch_code(check=False):
    """Select only the source's translated-joint shadow; never widen a rig."""
    import tag_rush_retarget as base_retarget
    a=Assembler(CHECK if check else RETARGET);tag.save(a)
    a.move(16,4);a.move(17,5);a.move(18,6)
    a.move(4,16 if check else 17);a.call(QUERY);a.branch(1,2,0,'no');a.branch(4,3,0,'no')
    a.lw(8,3,BANK_KIND);a.li(9,5);a.branch(4,8,9,'five');a.li(9,6);a.branch(4,8,9,'six')
    a.li(19,CHECK8 if check else RETARGET8);a.jump('selected')
    a.label('five');a.li(19,base_retarget.CHECK if check else base_retarget.RETARGET);a.jump('selected')
    a.label('six');a.li(19,CHECK6 if check else RETARGET6)
    a.label('selected');a.move(4,16);a.move(5,17);a.move(6,18);a.move(7,0);a.move(8,0)
    a.r(9,31,19);a.emit(0);a.jump('done');a.label('no');a.move(2,0)
    a.label('done');tag.restore(a,2);a.jr();code=a.finish()
    assert (CHECK if check else RETARGET)+len(code)<=(RETARGET if check else DATA)
    return code

def pieces(plan=None):
    import tag_rush_retarget as retarget
    result=[(QUERY,query_code()),(DONOR_PLAY,donor_play_code()),
            (RETARGET8,retarget.entry_code(base=RETARGET8,end=CHECK8,build=BUILD8,temp_size=0x1100)),
            (CHECK8,retarget.entry_code(True,base=CHECK8,end=BUILD8,build=BUILD8,temp_size=0x1100)),
            (BUILD8,retarget.build_code(base=BUILD8,end=RETARGET6,bones=BONES,nodes=0x920,meta=0xB20,stack=0xBC0)),
            (RETARGET6,retarget.entry_code(base=RETARGET6,end=CHECK6,build=BUILD6,temp_size=0x1100)),
            (CHECK6,retarget.entry_code(True,base=CHECK6,end=BUILD6,build=BUILD6,temp_size=0x1100)),
            (BUILD6,retarget.build_code(base=BUILD6,end=CHECK,bones=(0,2,31,45,52,54),nodes=0x920,meta=0xAA0,stack=0xB00)),
            (CHECK,dispatch_code(True)),(RETARGET,dispatch_code())]
    if plan is not None:
        blocks=plan.get('blocks',[])
        if len(blocks)!=1 or blocks[0][0]!=DATA:raise ValueError('Unexpected tag beam profile blocks')
        payload=bytes(blocks[0][1])
        if not HEADER<=len(payload)<=END-DATA or hashlib.sha256(payload).hexdigest()!=plan.get('sha256'):
            raise ValueError('Tag beam profile data changed')
        magic,count,size,_=struct.unpack_from('<4I',payload)
        if magic!=MAGIC or count not in (161,250) or size!=len(payload):raise ValueError('Invalid tag beam profile header')
        result.extend(blocks)
    return result
