"""Private mesh-only IO for extra Cell's temporary Android model.

Uses the serial reload IO workspace and native record/list protocol, not native
leader globals. Completed resources belong to a separate auxiliary constructor
and lifetime; they are not a replacement fighter or an ACK themselves.
"""
from native_map import A
import struct
import extra_reload_preload as preload
import extra_reload_service as io
import extra_reload_stage as stage
import selected_team_prepare as creator
import extra_reload_heap as heap

ENTRY,INNER,QUEUE,CONTROL,END=io.ENTRY,io.INNER,io.QUEUE,io.CONTROL,io.END
ABSENT=0xFFFFFFFF
ANDROID_COSTUMES={101:0,102:2}


def request_files(character,costume=0):
    if (type(character)is not int or type(costume)is not int or
            ANDROID_COSTUMES.get(character)!=costume):
        raise ValueError('Cell auxiliary requires Android17 costume0 or Android18 costume2')
    return [preload.request_files(character,costume,False)[0],ABSENT,ABSENT]



# Original-USA package audit: analysis/sept19-cell-capacity-assets.json.
# Includes every valid Cell costume/damaged variant; the next form exists at
# the same time as its temporary Android during absorption animation177.
DRAW_BUDGET={101:63+58,102:69+55}
AUX_STAGING=((0x2200,64),(192,32),(0x6E10,64),(0x6E10,64))


def heap_budget():
    # Keep the ordinary worker's real-file2MiB ceiling, independent of an old
    # capture's deliberately excessive24MiB guest admission. Every allocation
    # carries native header/footer + alignment slack, in one contiguous block.
    return heap.NEED+sum(size+alignment+36 for size,alignment in
                        ((heap.FILE_CEILING,64),)+AUX_STAGING)


def largest_free_block(ram):
    """Validate native heap1 boundary tags without following heap pointers."""
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if u(A(0x2FF084))!=heap.START or u(A(0x2FF08C))!=heap.STOP:return 0
    at,largest=heap.START,0
    for _ in range(heap.MAX_BLOCKS):
        if at>heap.STOP-32 or u(at)!=0x53484254:return 0
        used,size=u(at+4),u(at+16)
        if used not in (0,1) or size<32 or size%4 or size>heap.STOP-at:return 0
        end=at+size
        if u(end-4)!=size:return 0
        pointer,n=u(at+20),u(at+24)
        if used:
            if not at+32<=pointer<=end-4 or n>end-pointer-4:return 0
        else:
            if n!=size-32:return 0
            largest=max(largest,size)
        at=end
        if at==heap.STOP:return largest
    return 0


def texture_room(ram):
    """Texture groups for the Android, the queued form and two spare for native temporaries.

    The form is rechecked by extra_reload_worker.candidate under the same hold after the
    Android's constructor has taken the lowest free group: it needs a raw mask below 13 (the
    two-spare rule the guest form admission reads) and one group no live model uses. Counting
    used groups (the raw mask plus every live model's group, extra_reload_stage.texture_groups)
    keeps both true and still leaves two spare groups after the form, even when a destructor
    cleared a live model's bit. Below this, the visual is skipped before any allocation.
    """
    return stage.texture_groups(ram)['used'].bit_count()<=11


def preflight(ram,physical,character,costume=0):
    """None or a safe visual-skip reason, before claiming/allocating anything.

    This is admission, not reservation: caller must own the acknowledged guest
    hold and keep it until auxiliary publication. Identity errors are separate
    from normal resource exhaustion and raise before any IO can be started.
    """
    request_files(character,costume)
    w=preload.capture(ram,physical);u=lambda p:struct.unpack_from('<I',ram,p)[0]
    actor,model=w['actor'],w['model'];source=character+4
    slot,count=u(actor+0x994),u(actor+0x998)
    if (w['owner_action']!=239 or not slot<count<=5 or
            u(actor+0x9A4+164*slot)!=source or u(model+12)!=source or
            u(model+4)!=1 or u(actor+0x12D0)!=source+1 or
            u(actor+0x12F0)!=character or u(actor+0x12F4)!=costume):
        raise ValueError('Cell auxiliary owner or queued next form changed')
    if any(u(actor+off) for off in (0x1330,0x1334,0x1338)):
        raise ValueError('Cell already owns an auxiliary')
    # Native/preloader first-fit chooses the first unoccupied record, including
    # a dirty one. Never skip it in favour of a later clean record.
    found=0
    for i in range(12):
        record=w['registry']+i*56
        if u(record+48)&1:continue
        if any(u(record+off) for off in (0,16,32)):
            return 'a free resource record still owns buffers'
        if u(record+52)!=i+2:return 'a free resource handle is invalid'
        found+=1
        if found==2:break
    if found<2:return 'two free resource records are required'
    occupied=0
    for mid in range(12):
        pointer=u(preload.core.MODELS+4*mid)
        if not pointer:continue
        if not 0x100000<=pointer<=len(ram)-0x1670:
            raise ValueError('Auxiliary preflight found an invalid model pointer')
        active=u(pointer+4)
        if active not in (0,1):raise ValueError('Auxiliary model occupancy is invalid')
        if active:
            if u(pointer+16)!=mid:raise ValueError('Auxiliary model registration changed')
            occupied+=1
    pool=u(preload.REGISTRY_GLOBAL)
    if occupied>10 or u(pool+69128)<2:return 'two spare model slots are required'
    if not texture_room(ram):
        return 'four free texture groups are required (Android, next form and two spare)'
    if u(pool+397320)<DRAW_BUDGET[character]:return 'not enough draw nodes for Android and next form'
    if largest_free_block(ram)<heap_budget():return 'not enough contiguous memory for Android and next form'
    return None


def build_memory(ram,physical,character,costume=0,source='<offline-memory>',
                 timeout=io.POLL_UPDATES,quiet=True):
    files=request_files(character,costume)
    result=io.build_memory(ram,physical,character,costume,False,source,
                           timeout=timeout,quiet=quiet,allow_forms=True,mesh_only=True)
    assert result['request']['file_ids']==files
    result['status']='DORMANT CELL AUXILIARY MESH IO; CONSTRUCTOR AND ACK SEPARATE'
    result['request']['mesh_only']=True
    result['requirements']=[
        'Caller owns the acknowledged guest hold and serial IO workspace.',
        'Only one independent mesh buffer is loaded; animation and combat sections are absent.',
        'Status5 is resource readiness only; auxiliary construction/publication must precede ACK.',
        'Keep this receipt separate from the following actual fighter-form resource load.',
        'After queued IO errors retain owned buffers; do not discard a pending native queue job.']
    return result


def resource_info(ram,resource,handle,character,costume=0):
    files=request_files(character,costume)
    if type(handle)is not int or not 2<=handle<14:
        raise ValueError('Auxiliary must own an independent dynamic resource record')
    pool=struct.unpack_from('<I',ram,preload.REGISTRY_GLOBAL)[0]
    row=creator.resource_info(ram,resource,handle,character,costume,pool,
                              damaged=False,mesh_only=True)
    if row['file_ids']!=files:raise ValueError('Auxiliary resource file identity changed')
    # Native24FA50 binds PAK entries29..36 as eight auxiliary animations;
    # Cell's1D36B8 requests index4 through24D390, i.e. mesh entry33.
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    main,size=u(resource),u(resource+4)
    if size<140:raise ValueError('Auxiliary mesh has no animation table')
    start,end=u(main+33*4),u(main+34*4)
    if not 140<=start<end<=size or (end&~3)-(start&~3)<4:
        raise ValueError('Cell auxiliary animation4 is missing or invalid')
    animation=main+(start&~3)
    frames=struct.unpack_from('<H',ram,animation+2)[0]
    if not frames:raise ValueError('Cell auxiliary animation4 has no frames')
    row.update(aux_animation=animation,aux_animation_end=main+(end&~3),aux_animation_frames=frames)
    row.update(character=character,costume=costume,damaged=False,pool=pool,mesh_only=True)
    return row


def completed_resource(ram,character,costume=0):
    """Validate/detach the completed IO receipt before reusing its workspace."""
    u=lambda p:struct.unpack_from('<I',ram,p)[0]
    if (u(CONTROL+4),u(CONTROL+40),u(CONTROL+44))!=(5,1,1):
        raise ValueError('One auxiliary mesh IO job must be complete')
    if [u(CONTROL+96+4*i)for i in range(3)]!=request_files(character,costume):
        raise ValueError('Completed auxiliary IO destination changed')
    row=resource_info(ram,u(CONTROL+32),u(CONTROL+36),character,costume)
    for i in range(3):
        if any(u(row['resource']+16*i+j)!=u(CONTROL+k+4*i)for j,k in ((0,64),(4,80),(8,96))):
            raise ValueError('Completed auxiliary IO buffer identity changed')
    return row
