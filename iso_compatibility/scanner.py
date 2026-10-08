"""Offline per-resource compatibility profiles. Nothing here opens the emulator."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import struct
import tempfile
from .disc import Disc, FormatError, require, package, entry, u32, preflight
from .adapters import runtime_match, verify_stage_mapping
from .stages import inspect_stage
from .labels import unpack_bpe, english_label, native_label
from .known_discs import REVIEWED_BT3, KNOWN_RELEASE

SCHEMA = 1
SCANNER_VERSION = '2026-09-24.4'
DEFAULT_CACHE = Path(__file__).resolve().parents[1]/'compatibility-profiles'


def parts(data):
    return [data[a:b] for a,b in package(data)]


def fusion_recipes(params,mortal_potara=()):
    """Native20E340/370/3A0/3E8/450 fields, not a character-name heuristic."""
    require(len(params)>=0xC6,'Truncated native fusion parameters')
    recipes=[]
    for variant in range(3):
        kind,target=params[0xB1+variant],params[0xB4+variant]
        partners=list(dict.fromkeys(v for v in params[0xBA+4*variant:0xBE+4*variant] if v!=255))
        if target==255 or not partners:continue  # Disabled native slots retain type bytes.
        recipes.append(dict(variant=variant,result=target,partners=partners,
            kind={1:'dance',2:'potara'}.get(kind,'unknown'),native_type=kind,
            native_action={1:241,2:242}.get(kind),stock_cost=params[0xAE+variant],
            timed_defusion=kind==1 or (kind==2 and target in mortal_potara),
            timer_multiplier=1 if kind==1 else 2 if kind==2 and target in mortal_potara else None))
    return recipes


def stat_key(path):
    p=Path(path).resolve();s=p.stat()
    return dict(path=str(p),size=s.st_size,mtime_ns=s.st_mtime_ns)


def hash_file(path, progress=lambda _:None, step=1<<30):
    """SHA-256 of a file with a progress line every `step` bytes (Mod settings > Game disc passes 64 MiB)."""
    digest=hashlib.sha256();done=0;size=Path(path).stat().st_size;mark=0
    with open(path,'rb') as stream:
        while block:=stream.read(8<<20):
            digest.update(block);done+=len(block)
            if done>=mark:
                progress(f'Fingerprinting ISO: {done*100//size}%');mark=done+step
    return digest.hexdigest()


def atomic_json(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(data,stream,indent=2);stream.write('\n')
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def cache_index(path,cache=DEFAULT_CACHE):
    name=hashlib.sha256(str(Path(path).resolve()).casefold().encode()).hexdigest()[:24]
    return Path(cache)/(name+'.index.json')


def cached_profile(path,cache=DEFAULT_CACHE):
    """Fast cache: full fingerprint was computed at scan time; changed stat invalidates.

    Not a tamper-proof check: use --refresh to rehash externally modified media
    even if another tool deliberately preserved both size and timestamp.
    """
    try:
        index=json.loads(cache_index(path,cache).read_text(encoding='utf-8'))
        if index['source']!=stat_key(path):return None
        target=Path(cache)/(index['sha256']+'.json')
        raw=target.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=index['profile_sha256']:return None
        p=json.loads(raw)
        if (p['schema'],p['scanner_version'],p['source'])!=(SCHEMA,SCANNER_VERSION,index['source']):return None
        if p['identity']['iso_sha256']!=index['sha256']:return None
        # An unrecognized disc scanned before refusals named the disc (or before the
        # European adapter existed) is rescanned; verified profiles stay valid.
        match=p['identity'].get('runtime_match',{})
        if not p['identity'].get('runtime_adapter_verified') and 'refusal' not in match:return None
        # So is a disc an older scanner refused as a known unsupported release
        # although its serial has a reviewed adapter now (the Japanese SLPS-25815
        # before bt3-jpn). A refusal this scanner made for a reviewed serial (a
        # modified layout, executable or add-on) stays cached like any other.
        if (not p['identity'].get('runtime_adapter_verified') and p['identity'].get('serial') in REVIEWED_BT3
                and (match.get('refusal') or {}).get('template')==KNOWN_RELEASE):return None
        return p
    except (OSError,ValueError,KeyError,TypeError):return None


def mesh_info(data,capacity,*,allow_absent_collision=False):
    collision,geometry=entry(data,1),entry(data,2)
    # Native24FA20 supplies NULL for equal RAW offsets;24D778/24DB28 then
    # skip limb collision initialization. BT4 includes four such costumes.
    # Do not turn an absent chain into a pointer to an empty private buffer.
    absent=u32(data,8)==u32(data,12)
    require(not absent or allow_absent_collision,'This runtime adapter requires a limb collision chain')
    size=0 if absent else 16
    if not absent:
        while size+464<=min(capacity,len(collision)):
            terminal=u32(collision,size)&1;size+=464
            if terminal:break
        else:raise FormatError('Missing collision chain or exceeds private collision capacity')
    require(len(geometry)>=112 and geometry[:4]==b'pmdl','Missing PMDL geometry')
    at=u32(geometry,108);nodes=0
    while True:
        require(112<=at<=len(geometry)-12,'Geometry chain outside package')
        nodes+=1;require(nodes<=512,'Geometry exceeds draw-node capacity')
        if struct.unpack_from('<H',geometry,at+6)[0]:break
        step=u32(geometry,at);require(step>=12 and step%4==0,'Invalid geometry chain step');at+=step
    return dict(collision_bytes=size,draw_nodes=nodes,has_limb_collision=not absent)


def combat_info(data):
    """Validate all native effect slots without requiring optional parents.

    24FA20 returns NULL only for equal raw offsets. The low two bits can be
    flags: equal masked offsets with different flags are not an empty slot
    to the native loader and must not be certified as one.
    """
    entries=package(data)
    require(len(entries)>=6 and any(a!=b for a,b in entries[:6]),'Missing combat/move packages')
    slots=[]
    for slot in range(5):
        raw_start,raw_end=u32(data,4*(slot+1)),u32(data,4*(slot+2))
        start,end=entries[slot];empty=raw_start==raw_end
        require(empty or end-start>=16,f'Truncated special effect slot {slot+1}')
        slots.append(dict(slot=slot+1,offset=start,bytes=end-start,has_effect_resource=not empty))
    return dict(combat_entries=len(entries),special_effect_slots=slots,
                empty_effect_slots=[s['slot'] for s in slots if not s['has_effect_resource']])


def validate_stage_transitions(stages,issue):
    # Check the destination's effects as well as geometry, and propagate a
    # blocked destination through chains regardless of stage-number order.
    for _ in range(len(stages)+1):
        changed=False
        for row in stages:
            for name,variant in row['variants'].items():
                target=variant.get('destruction_target')
                if target is None:continue
                valid=(0<=target<len(stages) and stages[target]['variants'][name]['runtime_eligible'])
                variant['destruction_resources_valid']=valid
                if not valid and variant['runtime_eligible']:
                    variant['runtime_eligible']=False;changed=True
                    issue(f"stage:{row['stage_id']}/{name}",'Destruction replacement stage or effects failed validation')
            row['runtime_eligible']=all(v['runtime_eligible'] for v in row['variants'].values())
        if not changed:break


def scan(path,cache=DEFAULT_CACHE,refresh=False,progress=lambda _:None,progress_step=1<<30):
    if not refresh:
        cached=cached_profile(path,cache)
        if cached is not None:
            progress('Using unchanged ISO compatibility profile');return cached
    source=stat_key(path)
    preflight(path)  # a compressed, archived or incomplete image is named before the whole file is hashed
    fingerprint=hash_file(path,progress,progress_step)
    result=dict(schema=SCHEMA,scanner_version=SCANNER_VERSION,source=source,
                scanned_at=datetime.now(timezone.utc).isoformat(),
                identity=dict(iso_sha256=fingerprint),characters=[],stages=[],resources={},issues=[],
                capabilities={},verification='offline structural audit; gameplay testing is separate')
    with Disc(path) as disc:
        adapter,evidence=runtime_match(disc);recognized=evidence['verified']
        result['identity'].update(serial=disc.serial,layout=disc.kind,members=disc.member_hashes,
                                  adapter=adapter.name if adapter else None,runtime_adapter_verified=recognized,
                                  runtime_match=evidence,pcsx2_crc=evidence['pcsx2_crc'])
        result['volumes']={str(v):dict(member=disc.volume_paths[v],entries=len(entries)) for v,entries in disc.tables.items()}
        def issue(scope,message):result['issues'].append(dict(scope=scope,message=str(message)))
        def read(fid):
            raw=disc.read(fid)
            if str(fid) not in result['resources']:
                volume,offset,length=disc.locate(fid)
                result['resources'][str(fid)]=dict(member=volume,offset=offset,length=length,
                                                   sha256=hashlib.sha256(raw).hexdigest())
            return raw
        if adapter is None:
            issue('disc','No resource-layout adapter. Add a reviewed adapter; no runtime hooks enabled.')
        else:
            if not recognized:issue('disc',evidence['reason']+' Resource results are candidates only; runtime hooks disabled.')
            names={}
            try:
                ui=parts(unpack_bpe(parts(read(adapter.ui_text_file))[1]));labels,forms=parts(ui[29]),parts(ui[30])
                # The report names fighters as the disc does (the Japanese disc in kanji/kana).
                label=english_label if adapter.text_language=='en' else native_label
                for i in range(min(len(labels),len(forms),adapter.characters)):
                    names[i]=dict(name=label(labels[i]),form=label(forms[i]))
            except (ValueError,IndexError,struct.error) as error:issue('labels',error)
            table=parts(read(adapter.character_table_file))[0]
            require(adapter.characters*60<=len(table)<(adapter.characters+1)*60,'Changed character selection row layout')
            counts=[struct.unpack_from('<H',table,60*i+10)[0] for i in range(adapter.characters)]
            if disc.kind=='bt4-indexed':
                counts=[struct.unpack_from('<H',table,60*i+40)[0] for i in range(adapter.characters)]
                require(all(0<=n<=9 for n in counts),'Unsupported costume table')
            else:require(all(1<=n<=4 for n in counts),'Unsupported BT3 costume table')
            result['layout']=dict(costumes=counts,menu_only=list(adapter.menu_only),stage_count=adapter.stage_count,
                                  empty_character_slots=[i for i,n in enumerate(counts) if not n],
                                  stage_base=adapter.stage_base,split_stage_base=adapter.split_stage_base,
                                  stage_effect_base=adapter.stage_effect_base)
            for char in range(adapter.characters):
                if char in adapter.menu_only or counts[char]==0:continue
                row=dict(character_id=char,**names.get(char,dict(name=f'Character {char}',form='')),
                         costumes=[],issues=[],form_targets=[],common_resources_valid=True)
                result['characters'].append(row)
                if char%25==0:progress(f'Checking fighter resources: {char}/{adapter.characters}')
                files=adapter.files(char,0,False,counts)
                row['animation_file'],row['combat_file']=files[1:]
                try:
                    row['animation_entries']=len(package(read(files[1])))
                    row.update(combat_info(read(files[2])))
                    if disc.kind=='bt4-indexed':
                        ids=[4150+char,4400+char,4650+char,4900+char];row['sidecar_files']=ids
                        sidecars=[read(fid) for fid in ids]
                        require(all(len(b)<=limit for b,limit in zip(sidecars,(0xA800,0x4000,0x5000,0x5000))),
                                'Sidecar exceeds allocated private metadata capacity')
                        ai=parts(sidecars[0]);require(len(ai)==3 and len(ai[1])>=0x3060,'Invalid private AI/move metadata')
                        params=ai[1][:256]
                        require(sidecars[1].startswith(b'\xff\xfe'),'Missing native move-text metadata')
                        # Effect tables can use flag bits/sentinels not covered by
                        # generic PAK validation. Native sidecar service copies
                        # these unchanged; do not falsely certify inner effects.
                        row['effect_payload_validation']='presence and native buffer capacity; effect semantics unverified'
                    else:
                        main=parts(read(files[0]));require(len(main)>17 and len(main[17])>=256,'Missing native fighter parameters')
                        params=main[17][:256]
                    row['size_class']=params[2]
                    row['fusion_recipes']=fusion_recipes(params,(51,104,154) if disc.kind=='bt4-indexed' else (51,52))
                    row['form_targets']=list(dict.fromkeys(v for v in params[152:157] if v!=255))
                    require(all(v<adapter.characters and v not in adapter.menu_only for v in row['form_targets']),
                            'Transformation points outside fighter table')
                except (ValueError,IndexError,struct.error) as error:
                    row['common_resources_valid']=False;row['issues'].append(str(error));issue(f'fighter:{char}',error)
                for costume in range(counts[char]):
                    for damaged in (False,True):
                        requested=adapter.files(char,costume,damaged,counts)
                        variant=dict(costume=costume,damaged=damaged,files=requested,structurally_valid=False)
                        try:
                            raw=read(requested[0])
                            # Empty damaged slots occur in the reviewed BT4 disc.
                            # Retain this costume's intact model, never another
                            # character/costume. Malformed nonempty files fail.
                            if recognized and adapter.kind=='bt4-indexed' and damaged and not any(raw):
                                intact=adapter.files(char,costume,False,counts)
                                raw=read(intact[0]);variant['files']=intact
                                variant['damage_fallback']='same costume, intact appearance'
                            variant.update(mesh_info(raw,adapter.collision_capacity,
                                allow_absent_collision=adapter.kind=='bt4-indexed'))
                            variant['structurally_valid']=row['common_resources_valid']
                        except (ValueError,IndexError,struct.error) as error:
                            variant['error']=str(error);issue(f'fighter:{char}/costume:{costume}/damaged:{damaged}',error)
                        row['costumes'].append(variant)
                row['base_variant_valid']=any(v['structurally_valid'] and not v['damaged'] and v['costume']==0 for v in row['costumes'])
                row['runtime_eligible']=recognized and row['base_variant_valid']
            result['layout']['mesh_fallbacks']={
                str(adapter.files(r['character_id'],v['costume'],True,counts)[0]):v['files'][0]
                for r in result['characters'] for v in r['costumes']
                if v.get('damage_fallback') and v['structurally_valid']}
            fighters={r['character_id']:r for r in result['characters']}
            for row in result['characters']:
                row['form_resources']=[dict(character_id=target,
                    resources_valid=fighters.get(target,{}).get('base_variant_valid',False))
                    for target in row['form_targets']]
                for form in row['form_resources']:
                    if not form['resources_valid']:
                        issue(f"transformation:{row['character_id']}/{form['character_id']}",'Transformation destination lacks valid base resources')
                for recipe in row.get('fusion_recipes',[]):
                    ids=[recipe['result'],*recipe['partners']]
                    recipe['resources_valid']=recipe['kind']!='unknown' and all(
                        fighters.get(i,{}).get('base_variant_valid',False) for i in ids)
                    recipe['runtime_eligible']=recognized and recipe['resources_valid']
                    if not recipe['resources_valid']:issue(f"fusion:{row['character_id']}/{recipe['variant']}",'Unknown fusion type or missing result/partner resources')
            result['fusion_audit']=dict(recipes=sum(len(r.get('fusion_recipes',[])) for r in result['characters']),
                unsupported=[dict(character_id=r['character_id'],variant=f['variant']) for r in result['characters']
                    for f in r.get('fusion_recipes',[]) if not f['resources_valid']],
                initiation='Native leader or two allied extras. Extra initiation requires the private form worker; two human participants require consent. FFA fusions stay disabled.',
                timer_policy='Optional Dance timer; lore option doubles it for reviewed mortal Potara results. Fused Zamasu is not automatically defused. Preselected fusions stay untimed.',
                validation='Native parameter and resource validation; not a playtest of every animation.')
            stage_mapping=True
            try:verify_stage_mapping(disc,adapter)
            except ValueError as error:stage_mapping=False;issue('stage-loader',error)
            for stage in range(adapter.stage_count):
                if stage%10==0:progress(f'Checking stage resources: {stage}/{adapter.stage_count}')
                row=dict(stage_id=stage,variants={},issues=[],runtime_eligible=False)
                result['stages'].append(row)
                # BT4 reserves IDs with the same tiny CRI placeholder in all
                # three files. There is no map to load or repair at those IDs;
                # keep them inventoried without presenting them as broken maps.
                if recognized and adapter.name=='bt4-b14-rev2-eng':
                    ids=(adapter.stage_base+stage,adapter.split_stage_base+stage,adapter.stage_effect_base+stage)
                    placeholders=[read(fid) for fid in ids]
                    if all(len(raw)==2048 and raw[:16]==bytes.fromhex('800000240312040100005dc0000000f0') for raw in placeholders):
                        row.update(availability='unused slot',effects_present=False,effect_file=ids[2])
                        row['variants']={label:dict(file_id=fid,structurally_valid=False,runtime_eligible=False,
                            error='Unused slot; no map resources') for label,fid in zip(('normal','split_screen'),ids)}
                        continue
                for label,base in (('normal',adapter.stage_base),('split_screen',adapter.split_stage_base)):
                    variant=dict(file_id=base+stage,structurally_valid=False)
                    try:
                        resource=read(base+stage)
                        if recognized and adapter.name=='bt4-b14-rev2-eng' and label=='split_screen' and stage in (53,54):
                            # The installed native-loader hook routes these two
                            # placeholder files to the same arena's normal file.
                            require(resource[:16]==bytes.fromhex('800000240312040100005dc0000000f0'),
                                    'Reviewed missing split-stage file changed')
                            variant['native_file_id']=base+stage
                            variant['file_id']=adapter.stage_base+stage
                            variant['split_fallback']='same arena, normal geometry'
                            resource=read(variant['file_id'])
                        variant.update(inspect_stage(resource))
                        variant['structurally_valid']=True
                    except (ValueError,IndexError,struct.error) as error:
                        variant['error']=str(error);issue(f'stage:{stage}/{label}',error)
                    row['variants'][label]=variant
                try:
                    row['effect_file']=adapter.stage_effect_base+stage
                    effects=parts(read(row['effect_file']))
                    require(len(effects)==3 and all(effects),'Missing stage effect package')
                    row['effects_present']=True
                except ValueError as error:row['effects_present']=False;issue(f'stage:{stage}/effects',error)
                row['runtime_eligible']=recognized and stage_mapping and row['effects_present'] and all(v['structurally_valid'] for v in row['variants'].values())
                for variant in row['variants'].values():
                    variant['runtime_eligible']=recognized and stage_mapping and row['effects_present'] and variant['structurally_valid']
            validate_stage_transitions(result['stages'],issue)
        result['capabilities']=dict(resource_inventory=adapter is not None,
            runtime_hooks=recognized,character_extras=recognized and any(r['runtime_eligible'] for r in result['characters']),
            stage_loading=recognized and any(v['runtime_eligible'] for r in result['stages'] for v in r['variants'].values()),
            map_scaling=False,gameplay_verified=False)
        result['summary']=dict(fighters=len(result['characters']),
            base_fighters_valid=sum(r['base_variant_valid'] for r in result['characters']),
            costume_variants=sum(len(r['costumes']) for r in result['characters']),
            costume_variants_valid=sum(v['structurally_valid'] for r in result['characters'] for v in r['costumes']),
            stages=len(result['stages']),stage_variants_valid=sum(v['structurally_valid'] for r in result['stages'] for v in r['variants'].values()),
            normal_maps_eligible=sum(r['variants']['normal']['runtime_eligible'] for r in result['stages']),
            split_maps_eligible=sum(r['variants']['split_screen']['runtime_eligible'] for r in result['stages']),
            unused_stage_slots=sum(r.get('availability')=='unused slot' for r in result['stages']),
            issues=len(result['issues']))
    require(source==stat_key(path),'ISO changed while scanning; profile was not saved')
    target=Path(cache)/(fingerprint+'.json');atomic_json(target,result)
    atomic_json(cache_index(path,cache),dict(source=source,sha256=fingerprint,
                                           profile_sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
    return result


def report(profile):
    identity=profile['identity'];summary=profile['summary']
    lines=[f"# ISO compatibility: {identity['serial']}",'',profile['verification'],'',
           f"Adapter: {identity['adapter']} | reviewed executable: {identity['runtime_adapter_verified']}",
           f"Variant: {identity.get('runtime_match',{}).get('variant') or 'Unrecognized'}",
           identity.get('runtime_match',{}).get('reason',''),
           *([identity['runtime_match']['refusal']['text']] if identity.get('runtime_match',{}).get('refusal') else []),
           f"PCSX2 CRC: {identity.get('pcsx2_crc','unknown')} (identifier, not compatibility proof)",
           f"ISO SHA-256: {identity['iso_sha256']}",'',
           f"Fighters with valid base resources: {summary['base_fighters_valid']}/{summary['fighters']}",
           f"Valid costume variants: {summary['costume_variants_valid']}/{summary['costume_variants']}",
           f"Valid stage variants: {summary['stage_variants_valid']}/{2*summary['stages']}",'',
           f"Battle maps with valid loading resources: {summary['normal_maps_eligible']} normal / {summary['split_maps_eligible']} split-screen.",'',
           f"Unused stage slots with no map assets: {summary.get('unused_stage_slots',0)}. These are not failed playable maps.",
           'These are file/structure checks, not proof that every attack, effect or stage works in a match.',
           'Unknown executable revisions require a reviewed runtime adapter; a matching game CRC is insufficient.',
           'Expanded maps are a separate opt-in build; this inventory does not enable them or certify their rendering.','',
           '## Findings','']
    lines.extend(f"- {r['scope']}: {r['message']}" for r in profile['issues'])
    if not profile['issues']:lines.append('No structural failures detected.')
    lines+=['','## Every populated character and form','',
            '| ID | Fighter / form | Base resources | Valid costume variants |',
            '| --- | --- | --- | --- |']
    for row in profile['characters']:
        label=(row['name']+(' / '+row['form'] if row['form'] else '')).replace('|','/')
        valid=sum(v['structurally_valid'] for v in row['costumes'])
        lines.append(f"| {row['character_id']} | {label} | {'Pass' if row['base_variant_valid'] else 'Blocked'} | {valid}/{len(row['costumes'])} |")
    audit=profile.get('fusion_audit')
    if audit:
        names={r['character_id']:(r['name']+(' / '+r['form'] if r['form'] else '')).replace('|','/')
               for r in profile['characters']}
        name=lambda i:f'{i}: {names.get(i,"Unknown fighter")}'
        lines+=['','## Fusion recipes','',
                f"Active recipes: {audit['recipes']}. Recipes with unresolved resources: {len(audit['unsupported'])}.",
                audit['initiation'],audit['validation'],'',
                '| Fighter / form | Variant | Fusion type | Result | Eligible partners | Timed defusion | Resources |',
                '| --- | --- | --- | --- | --- | --- | --- |']
        for row in profile['characters']:
            for recipe in row.get('fusion_recipes',[]):
                lines.append(f"| {name(row['character_id'])} | {recipe['variant']} | {recipe['kind']} | {name(recipe['result'])} | "
                             +', '.join(name(i) for i in recipe['partners'])
                             +f" | {'Optional' if recipe['timed_defusion'] else 'No'} | {'Pass' if recipe['resources_valid'] else 'Blocked'} |")
    empty=[row for row in profile['characters'] if row.get('empty_effect_slots')]
    lines+=['','## Special-effect resource audit','',
            'Every populated fighter has all five effect slots checked. A slot declared empty by the game is valid; it does not mean the move is missing.',
            'Malformed or truncated nonempty resources remain rejected. Native effect behavior still needs gameplay testing.']
    for row in empty:
        lines.append(f"- {row['character_id']}: {row['name']} {row['form']}: native empty effect slots "
                     +', '.join(map(str,row['empty_effect_slots'])))
    lines+=['','## Optional costume resources','',
            'Declared-empty limb collision entries keep the native null-pointer behavior; the trainer never initializes an empty chain.',
            'An empty damaged-model file uses the same character and costume with its intact appearance. This does not create missing damaged artwork.']
    for row in profile['characters']:
        fallback=[str(v['costume']+1) for v in row['costumes'] if v.get('damage_fallback')]
        if fallback:lines.append(f"- {row['name']} {row['form']}: intact appearance when damaged for costumes "+', '.join(fallback))
    lines+=['','## Every stage slot','',
            '| ID | Normal resources | Split-screen resources | Destruction destination |',
            '| --- | --- | --- | --- |']
    for row in profile['stages']:
        variants=row['variants']
        cells=[('Pass (same-arena normal-file fallback)' if variants[k].get('split_fallback') else 'Pass')
               if variants[k]['runtime_eligible'] else variants[k].get('error','Not validated').replace('|','/') for k in ('normal','split_screen')]
        target=variants['normal'].get('destruction_target')
        lines.append(f"| {row['stage_id']} | {cells[0]} | {cells[1]} | {target if target is not None else '-'} |")
    lines+=['','## Runtime scope','',
            'Reviewed executables and menu overlays can use the corresponding trainer adapter. Asset-only ISOs are scanned and receive their own extracted references, portraits and resource profile.',
            'An unknown executable or menu overlay receives an inventory only. Installation stops before hooks are enabled; adding its addresses needs a reviewed adapter.',
            'Character/costume load guards remain active. A valid base form does not make every damaged costume valid.',
            'Expanded maps are optional generated copies. Undecoded maps and incompatible destruction chains stay at native size.',
            'For BT4 B14 REV2, Time Patroller has an invalid Japanese short-voice package; defusion uses that fighter\'s English short-voice bank as a fallback.','']
    return '\n'.join(lines)+'\n'


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('iso',nargs='?',type=Path);parser.add_argument('--cache',type=Path,default=DEFAULT_CACHE)
    parser.add_argument('--refresh',action='store_true',help='Rehash and rescan, bypassing the size/timestamp cache')
    args=parser.parse_args()
    if args.iso is None:
        import tkinter as tk
        from tkinter.filedialog import askopenfilename
        window=tk.Tk();window.withdraw()
        selected=askopenfilename(title='Choose a BT3-based ISO to scan',initialdir=DEFAULT_CACHE.parent/'games',
                                filetypes=[('PlayStation 2 disc image','*.iso')])
        window.destroy()
        if not selected:return 0
        args.iso=Path(selected)
    try:
        profile=scan(args.iso,args.cache,args.refresh,print)
        destination=args.cache/(profile['identity']['iso_sha256']+'.md')
        destination.write_text(report(profile),encoding='utf-8')
        print(json.dumps(profile['summary'],indent=2));print(f'Report: {destination}')
        refusal=profile['identity'].get('runtime_match',{}).get('refusal')
        if refusal:print(refusal['text'])
        return 0 if profile['capabilities']['runtime_hooks'] else 2
    except (OSError,ValueError,struct.error) as error:
        print(f'Scan failed: {error}');return 1


if __name__=='__main__':raise SystemExit(main())
