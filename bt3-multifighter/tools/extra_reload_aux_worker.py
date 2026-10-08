"""Serial host service for Cell's temporary Android, separate from form ACK.

Only supplies operations to the caller's existing guarded client. No emulator,
connection, or process is created here. Mesh IO and construction share the
ordinary completed workspaces, but their receipts never become fighter models.
"""
from native_map import A
import struct

import extra_cell_absorption as cell
import extra_reload_aux_io as io
import extra_reload_aux_stage as stage
import extra_reload_requests as requests
import extra_reload_forms as forms
import extra_reload_quiet as runner
import native_preparation as native
from battle_mode_policy import ACTOR_COUNTS


def u(ram,p):return struct.unpack_from('<I',ram,p)[0]


def enabled(ram):
    manager=u(ram,cell.AUX_CONTROL+8);count=u(ram,cell.AUX_CONTROL+12)
    return (u(ram,cell.AUX_CONTROL)==1 and u(ram,cell.AUX_CONTROL+4)==cell.AUX_MAGIC and
            count in ACTOR_COUNTS and 0x100000<=manager<=len(ram)-640 and
            u(ram,runner.core.ACTORS)==manager and u(ram,runner.core.MODE)==1 and
            tuple(u(ram,runner.core.MODE+off) for off in (4,8,12))==(count,manager,count) and
            tuple(u(ram,requests.CONTROL+off) for off in (0,4,8,24))==(1,manager,count,1) and
            tuple(u(ram,forms.CONTROL+off) for off in (0,4,8))==(1,manager,count))


def blocks_form(ram,physical,actor):
    """Do not let an early ordinary form request monopolize the serial worker.

    Cell publishes both requests at entry. Its first READY needs the Android,
    so staging the form first and waiting for its ACK would deadlock both.
    """
    if not enabled(ram) or not 2<=physical<u(ram,cell.AUX_CONTROL+12):return False
    row=cell.auxiliary_row(physical)
    if not (u(ram,row+4) in (1,2) and u(ram,row+8)==actor and
            u(ram,row+32)==u(ram,cell.AUX_CONTROL+8) and u(ram,row+36)==physical and
            0x100000<=actor<=len(ram)-0x1600 and u(ram,actor+0x948)==239):return False
    source=u(ram,row+28);mid=u(ram,actor+12);model=u(ram,row+16)
    if (source not in (105,106) or mid>=12 or mid!=u(ram,row+12) or
            not 0x100000<=model<=len(ram)-0x1670 or
            u(ram,runner.core.POINTERS+4*physical)!=actor or
            u(ram,runner.core.MODELS+4*mid)!=model or u(ram,model+12)!=source or
            u(ram,model+20)!=u(ram,row+40)):return False
    return (u(ram,row+48)==source+1==u(ram,actor+0x12D0) and
            u(ram,row+20)==source-4==u(ram,actor+0x12F0) and
            u(ram,row+24)==(0 if source==105 else 2)==u(ram,actor+0x12F4))


def arm(p,enable=True):
    if type(enable)is not bool:raise ValueError('Cell auxiliary preference must be Boolean')
    manager=p.read_u32(runner.core.ACTORS);count=p.read_u32(requests.CONTROL+8)
    if struct.unpack('<3I',p.read(cell.AUX_CONTROL+4,12))!=(cell.AUX_MAGIC,manager,count):
        raise ValueError('Cell auxiliary service belongs to another match')
    if any(p.read_u32(cell.auxiliary_row(i)+4)==2 for i in range(2,count)):
        raise ValueError('Cannot attach while a Cell auxiliary job is claimed')
    p.write_u32(cell.AUX_CONTROL,int(enable))


def pending_hint(p):
    """Read only a small owned header and row table when combat is idle."""
    header=struct.unpack('<4I',p.read(cell.AUX_CONTROL,16))
    if header[0]!=1 or header[1]!=cell.AUX_MAGIC or header[3] not in ACTOR_COUNTS:return False
    if p.read_u32(runner.core.ACTORS)!=header[2]:return False
    rows=p.read(cell.AUX_RECORDS,(header[3]-2)*cell.AUX_STRIDE)
    return any(u(rows,i*cell.AUX_STRIDE+4)==1 for i in range(header[3]-2))


def candidate(ram):
    """Validate identity, never capacity, before deciding to load or skip."""
    if not enabled(ram) or u(ram,runner.core.PAIR+4) or u(ram,A(0x3337B8))&0x3800:return None
    manager=u(ram,cell.AUX_CONTROL+8);count=u(ram,cell.AUX_CONTROL+12)
    if (any(u(ram,manager+off) for off in (600,612,628)) or
            u(ram,manager+604)!=u(ram,manager+608)):return None
    for physical in range(2,count):
        at=cell.auxiliary_row(physical);v=struct.unpack_from('<16I',ram,at)
        generation,status,actor,mid,model,character,costume,source=v[:8]
        if status!=1 or not generation or source not in (105,106):continue
        if (character,costume)!=(source-4,0 if source==105 else 2):continue
        if (not 0x100000<=actor<=len(ram)-0x1600 or actor%4 or
                not 0x100000<=model<=len(ram)-0x1670 or model%4 or mid>=12):continue
        if (v[8:10]!=(manager,physical) or v[12]!=source+1 or
                u(ram,runner.core.POINTERS+4*physical)!=actor or u(ram,actor)!=physical or
                u(ram,actor+12)!=mid or u(ram,runner.core.MODELS+4*mid)!=model or
                u(ram,model+4)!=1 or u(ram,model+12)!=source or u(ram,model+16)!=mid or
                u(ram,model+20)!=v[10] or u(ram,actor+0x948)!=239):continue
        slot,bench=u(ram,actor+0x994),u(ram,actor+0x998)
        if not 0<=slot<bench<=5 or u(ram,actor+0x9A4+164*slot)!=source:continue
        if (u(ram,actor+0x12D0)!=source+1 or u(ram,actor+0x12F0)!=character or
                u(ram,actor+0x12F4)!=costume or
                any(u(ram,actor+off) for off in (0x1330,0x1334,0x1338)) or
                u(ram,0x0778F100+4*physical)):continue
        # Both native requests are published in the same action239 entry.
        # Require the real form row before spending the cosmetic allocation.
        form_at=requests.RECORDS+(physical-2)*requests.STRIDE
        f=struct.unpack_from('<16I',ram,form_at)
        if (not f[0] or f[1:7]!=(1,actor,mid,model,source+1,u(ram,actor+0x12D4)) or
                f[7]!=u(ram,actor+0x12E0) or f[7] not in (0,1) or
                any(value not in (0xFFFFFFFF,source+1) for value in f[8:11]) or
                f[11:13]!=(physical,v[10]) or f[14:]!=(1,239)):continue
        return dict(row=at,generation=generation,physical=physical,actor=actor,model=model,
                    model_id=mid,character=character,costume=costume,source=source,
                    old_resource=v[10],manager=manager,owner_action=239)
    return None


def poll(worker,p):
    """None means no auxiliary work; otherwise this poll belongs to it.

    A safe capacity skip has made no allocation. Once IO starts, failures retain
    the caller's hold for its existing recovery path, never orphan queued IO.
    """
    if not worker.forms or not pending_hint(p):return None
    ram=worker._snapshot(p);job=candidate(ram)
    # Stale/interrupted cosmetic rows must not starve unrelated reloads.
    # blocks_form still excludes a live Cell request until its own row resolves.
    if job is None:return None
    worker.quiet(p)
    import time
    worker._held_since=time.perf_counter();worker.timings=[]
    from extra_reload_worker import word_block
    try:
        ram=worker._snapshot(p)
        if candidate(ram)!=job:
            worker._release(p);return False
        shortage=io.preflight(ram,job['physical'],job['character'],job['costume'])
        if shortage:
            worker.apply(p,dict(blocks=[word_block(ram,job['row']+52,1),word_block(ram,job['row']+4,6)]))
            worker.progress('Cell absorption visual skipped: '+shortage)
            worker._release(p);return False
        worker.apply(p,dict(blocks=[word_block(ram,job['row']+4,2)]))
        worker.progress('Loading Cell absorption scene')
        view=worker._analysis_view(ram)
        manifest=worker._build('auxiliary IO',io.build_memory,view,job['physical'],job['character'],job['costume'])
        worker._install_stage(p,'io',ram,manifest,job)
        ram=worker._snapshot(p);view=worker._analysis_view_for(ram,('stage','commit'))
        manifest=worker._build('auxiliary model',stage.build_memory,view,job['character'],job['costume'])
        worker._install_stage(p,'stage',ram,manifest,job)
        ram=worker._snapshot(p);row=io.completed_resource(ram,job['character'],job['costume'])
        actor=job['actor'];mid=u(ram,actor+0x1338)
        if (u(ram,actor+0x1330)!=1 or u(ram,actor+0x1334)!=row['resource_handle'] or mid>=12 or
                u(ram,stage.CONTROL+40)!=mid or u(ram,job['row']+4)!=2 or
                u(ram,job['row'])!=job['generation']):
            raise RuntimeError('Cell auxiliary publication identity changed; match remains held')
        model=u(ram,runner.core.MODELS+4*mid)
        if (model!=u(ram,stage.CONTROL+44) or not 0x100000<=model<=len(ram)-0x1670 or
                tuple(u(ram,model+off) for off in (0,4,12,16,20))!=(2,1,job['character'],mid,row['resource'])):
            raise RuntimeError('Cell auxiliary model identity changed; match remains held')
        worker.apply(p,dict(blocks=[word_block(ram,job['row']+52,0),
                                   word_block(ram,job['row']+56,row['resource_handle']),
                                   word_block(ram,job['row']+60,mid),word_block(ram,job['row']+4,5)]))
        worker.progress('Cell absorption scene ready')
        # Keep the admitted resource/model/texture capacity until the already
        # queued real form is staged too. Releasing between these two loads
        # would let another transformation take the final free resource record.
        from extra_reload_worker import candidate as form_candidate
        ram=worker._snapshot(p);form_job=form_candidate(ram,specific=job['physical'])
        if (form_job is None or not form_job['form'] or form_job['owner_action']!=239 or
                form_job['character']!=job['source']+1 or form_job['actor']!=job['actor']):
            raise RuntimeError('Cell form request changed after auxiliary publication; match remains held')
        return worker._load_job(p,form_job)
    except Exception as exc:
        worker.failure=str(exc);worker.progress(worker.failure);raise
