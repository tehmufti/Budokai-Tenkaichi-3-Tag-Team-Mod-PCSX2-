"""Conservative recycling of exact bundles removed by true Body Change."""
import struct
from collections.abc import Mapping
import body_swap as body
import body_swap_commit as commit
import body_swap_resources as resources
import body_swap_runner as runner
import extra_reload_retire as prior


def receipt(ram,physical,resource,group):
    return dict(physical=physical,manager=body.u(ram,body.core.ACTORS),resource=resource,
                handle=body.u(ram,resource+52),group=group,
                buffers=[dict(pointer=body.u(ram,resource+16*i),size=body.u(ram,resource+16*i+4),
                              file=body.u(ram,resource+16*i+8)) for i in range(3)])


def removed_receipts(before,after,manifest):
    """Follow descriptor adoption instead of treating old native handles as freeable."""
    mappings={c['adoption']['original']:c['adoption']['replacement'] for c in manifest['configurations'] if c['adoption']}
    result=[];seen=set()
    for c in manifest['configurations']:
        original=c['world']['old_resource'];resource=mappings.get(original,original)
        if resource in seen:continue
        seen.add(resource)
        if body.u(after,resource+52)<2:continue # another native leader still owns it
        owned=receipt(after,c['world']['physical'],resource,c['old_group'])
        for i,row in enumerate(owned['buffers']):
            # A host may retain just these immutable 56-byte descriptors while
            # expiring and reusing its full lazy RAM allocation after commit.
            old=before[original] if isinstance(before,Mapping) else before
            base=0 if isinstance(before,Mapping) else original
            body.require((row['pointer'],row['size'],row['file'])==
                         tuple(body.u(old,base+16*i+o) for o in (0,4,8)),
                         'Removed body descriptor does not retain the captured old files')
        result.append(owned)
    return result,mappings


def build_memory(ram,owned):
    # Resident copies inherit uploaded textures but have independent PAK files.
    # Free an unreferenced old file triple without clearing a group still used
    # by a registered model. The generic capture below authenticates that model
    # and its geometry/group again in the guest immediately before retirement.
    shared=False
    for mid in range(12):
        model=body.u(ram,body.core.MODELS+mid*4)
        if not 0x100000<=model<=len(ram)-0x1670 or body.u(ram,model+4)!=1:continue
        geometry=body.u(ram,model+64)
        if 0x100000<=geometry<=len(ram)-112 and body.u(ram,geometry+40)==owned['group']:shared=True
    context=dict(quiet_checks=[(resources.transport.CONTROL,resources.transport.MAGIC),
        (resources.transport.CONTROL+16,1),(resources.transport.CONTROL+20,1),
        (resources.transport.CONTROL+24,owned['manager'])],
        commit_guards=[(commit.CONTROL+4,5),(body.CONTROL+16,3)],preserve_texture=shared)
    c=prior.capture(ram,owned,body_context=context)
    c['defer_busy']=True
    body.require(not any(ram[runner.RETIRE:runner.END]),'Body retirement workspace occupied')
    payload=body.core.rebound(prior.payload,ENTRY=runner.RETIRE,CONTROL=runner.RETIRE_CONTROL)(c)
    control=bytearray(0x100)
    struct.pack_into('<4I',control,8,c['world']['manager'],c['world']['actor'],owned['resource'],owned['handle'])
    return resources.parts_manifest(ram,[(runner.RETIRE,payload),(runner.RETIRE_CONTROL,bytes(control))],
        entry=runner.RETIRE,control=runner.RETIRE_CONTROL,configuration={k:v for k,v in c.items() if k!='copies'})
