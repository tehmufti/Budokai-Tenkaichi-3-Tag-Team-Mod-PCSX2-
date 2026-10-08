"""Build an optional 2x static-stage test ISO without changing the source disc.

This is an experimental gameplay build, not a fully validated art conversion.
Ambient effects/debris and camera framing still require in-game testing. Maps
with undecoded animated scenery remain completely native, in both view modes.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import tempfile
from .disc import Disc,require,package,u32
from .map_scaling import plan_stage
from .scanner import stat_key,hash_file,atomic_json,cached_profile,scan
from .adapters import identify,verify_stage_mapping

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'games/Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso'
OUTPUT=ROOT/'games/BT3 - Expanded Maps 2x (Experimental).iso'
MANIFEST=ROOT/'compatibility-profiles/expanded-maps-2x.json'
SOURCE_HASH='93f1f911e9a2bbdf92e5794fc3075ddf3f87db3df4b1cb8cfbb0448721c91172'
BUILD_VERSION=2


def installed(source=SOURCE,output=OUTPUT,manifest=MANIFEST):
    try:
        result=json.loads(Path(manifest).read_text(encoding='utf-8'))
        require(result['build_version']==BUILD_VERSION,'Expanded-map builder changed')
        profile=cached_profile(source)
        require(result['source_sha256']==SOURCE_HASH or (profile is not None and profile['capabilities']['runtime_hooks'] and result['source_sha256']==profile['identity']['iso_sha256']),'Wrong source identity')
        require(result['source']==stat_key(source),'Original ISO changed after expanded maps were built')
        require(result['output']==stat_key(output),'Expanded-map ISO is missing or changed')
        require(result['scale']==2 and result['scaled_stages'],'Expanded-map manifest has no scaled stages')
        return result
    except (OSError,ValueError,KeyError,TypeError):return None


def build(source=SOURCE,output=OUTPUT,manifest=MANIFEST,progress=print):
    source,output,manifest=Path(source).resolve(),Path(output).resolve(),Path(manifest).resolve()
    require(source!=output and source!=manifest and output!=manifest,'Output must be separate from the original ISO')
    current=installed(source,output,manifest)
    if current:
        progress('Expanded-map test ISO is already current.');return current
    # Never replace an unrelated ISO selected as the destination.
    previous_output=None
    if output.exists():
        # Upgrade only our authenticated generated copy. A name alone is not
        # proof of ownership; preserve unrelated or manually edited images.
        previous=json.loads(manifest.read_text(encoding='utf-8'))
        previous_output=stat_key(output)
        require(bool(previous.get('source_sha256')) and
                previous.get('output')==previous_output and previous.get('experimental') is True and
                previous.get('source')==stat_key(source),
                'Existing destination is not the recorded generated map ISO')
        require(hash_file(output,progress)==previous.get('output_sha256'),
                'Generated map ISO was edited; refusing to replace it')
    before=stat_key(source);digest=hash_file(source,progress)
    profile=scan(source,progress=progress)
    require(profile['capabilities']['runtime_hooks'] and digest==profile['identity']['iso_sha256'],'Expanded maps require a reviewed executable and resource profile')
    output.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix=output.stem+'.',suffix='.partial',dir=output.parent);os.close(fd)
    result=dict(build_version=BUILD_VERSION,scale=2,source=before,source_sha256=digest,
                scaled_stages=[],native_stages=[],patches=[],experimental=True,gameplay_verified=False,
                notes=['Geometry, terrain collision, sector bounds, spawns and playable limits scale together.',
                       'Fighter size, speed, attack range and revival radius remain unchanged.',
                       'Undecoded animated-scenery maps remain native.',
                       'Sky dome remains native; authored intro camera positions scale with terrain.',
                       'Ambient effects/debris and destruction cinematics require gameplay testing.'])
    try:
        progress('Creating a separate ISO copy...');shutil.copyfile(source,temp)
        with Disc(source) as disc,open(temp,'r+b') as target:
            adapter,recognized=identify(disc)
            require(recognized,'Unreviewed stage runtime')
            verify_stage_mapping(disc,adapter)
            # Prove each pair before writing any map. Keep destruction-linked
            # arenas native if their destination cannot be expanded as well.
            eligible=set();reasons={}
            for stage in range(adapter.stage_count):
                try:
                    for mode,base in (('normal',adapter.stage_base),('split_screen',adapter.split_stage_base)):
                        raw=disc.read(base+stage);entries=package(raw);a,b=entries[0]
                        require(not u32(raw,a+16) and not (len(entries)>8 and entries[8][1]>entries[8][0]),'Animated scenery is not yet converted')
                        plan_stage(raw,2)
                    eligible.add(stage)
                except (ValueError,IndexError) as error:reasons[stage]=str(error)
            changed=True
            while changed:
                changed=False
                for stage in tuple(eligible):
                    targets=[v.get('destruction_target') for v in profile['stages'][stage]['variants'].values()]
                    if any(target is not None and target not in eligible for target in targets):
                        eligible.remove(stage);reasons[stage]='Destruction replacement must remain native';changed=True
            require(eligible,'No stage pairs can be expanded safely')
            for stage in range(adapter.stage_count):
                if stage not in eligible:
                    result['native_stages'].append(dict(stage_id=stage,reason=reasons[stage]));continue
                prepared=[];reason=None
                for mode,base in (('normal',adapter.stage_base),('split_screen',adapter.split_stage_base)):
                    raw=disc.read(base+stage);entries=package(raw);a,b=entries[0]
                    if u32(raw,a+16) or (len(entries)>8 and entries[8][1]>entries[8][0]):
                        reason='Animated stage model/keyframes are not yet converted';break
                    plan=plan_stage(raw,2);scaled=plan.preview()
                    require(len(scaled)==len(raw),'Scaled resource size changed')
                    member,offset,length=disc.locate(base+stage)
                    record=disc.iso.get_record(iso_path=member)
                    absolute=record.extent_location()*2048+offset
                    require(0<=absolute<=before['size']-length,'Stage patch exceeds ISO')
                    prepared.append((absolute,raw,scaled,mode,base+stage))
                if reason:
                    result['native_stages'].append(dict(stage_id=stage,reason=reason));continue
                progress(f'Building expanded stage {stage+1}/{adapter.stage_count} (normal and split-screen)')
                for absolute,raw,scaled,mode,fid in prepared:
                    target.seek(absolute);require(target.read(len(raw))==raw,'ISO extent differs from indexed stage')
                    target.seek(absolute);target.write(scaled)
                    target.flush();target.seek(absolute);require(target.read(len(scaled))==scaled,'Stage write verification failed')
                    result['patches'].append(dict(file_id=fid,stage_id=stage,variant=mode,offset=absolute,length=len(raw),
                        before_sha256=hashlib.sha256(raw).hexdigest(),after_sha256=hashlib.sha256(scaled).hexdigest()))
                result['scaled_stages'].append(stage)
            target.flush();os.fsync(target.fileno())
        require(before==stat_key(source),'Source ISO changed during the build')
        result['adapter']=profile['identity']['adapter']
        result['output_sha256']=hash_file(temp,progress)
        require((not output.exists()) if previous_output is None else stat_key(output)==previous_output,
                'Destination changed during the build')
        os.replace(temp,output)
        result['output']=stat_key(output);atomic_json(manifest,result)
        progress(f"Ready for testing: {len(result['scaled_stages'])} expanded stages; {len(result['native_stages'])} animated stages left native.")
        return result
    finally:
        if os.path.exists(temp):os.unlink(temp)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=SOURCE)
    parser.add_argument('--output',type=Path,default=OUTPUT);parser.add_argument('--manifest',type=Path,default=MANIFEST)
    args=parser.parse_args()
    try:build(source=args.source,output=args.output,manifest=args.manifest);return 0
    except (OSError,ValueError) as error:print(f'Expanded-map build stopped: {error}');return 1


if __name__=='__main__':raise SystemExit(main())
