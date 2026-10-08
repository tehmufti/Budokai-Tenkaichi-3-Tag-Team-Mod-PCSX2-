"""Build the player-only payload. No ISO, BIOS, saves, emulator, or captured RAM."""
import ast
import hashlib
import json
import re
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
# disc_library is started by path (Mod settings > Game disc runs it as a child process), so no import reaches it.
SEEDS=('autopilot','install_boot_hooks','mod_settings','map_scale_launch','presentation_settings','extract_loading_assets','player_storage','play_launcher','disc_library')
JSON_ASSETS=('buu_fanout_family1_legacy.json','buu_fanout_legacy.json','loading_legacy_payloads.json','native_menu_labels.json','pcsx2_versions.json')
# Assets of one payload folder. bt3-usa also serves the European and Japanese discs (install_player.ADAPTERS
# 'bt3-pal' / 'bt3-jpn'): their native addresses come from pal_native_map.json / jpn_native_map.json through
# native_map.py, so no second copy of the tools ships; the Japanese disc's English fighter names come from
# bt3_english_names.json (its own text set is Japanese only).
ADAPTER_ASSETS={'bt3-usa':('pal_native_map.json','jpn_native_map.json','bt3_english_names.json')}
NATIVE_MAP_TABLES=('pal_native_map.json','jpn_native_map.json')
# Shared non-Python runtime assets: explicit paths prevent source models or previews entering the payload.
SHARED_ASSETS=('assets/licenses/Mannequiny.txt',)


def put(archive,name,data):
    """Stable metadata makes the same reviewed files yield the same ZIP hash."""
    item=zipfile.ZipInfo(name,(2026,9,21,0,0,0));item.compress_type=zipfile.ZIP_DEFLATED
    item.external_attr=0o100644<<16
    archive.writestr(item,data,compresslevel=9)


# fonts.py renders with these on Linux (Windows keeps its own Arial); the OFL text and README ship beside them.
FONTS=('LiberationSans-Regular.ttf','LiberationSans-Bold.ttf')


def bundled_fonts(project):
    """Every file in tools/vendor/fonts: the fonts plus their license and README."""
    folder=Path(project)/'tools/vendor/fonts'
    paths=sorted(p for p in folder.iterdir() if p.is_file()) if folder.is_dir() else []
    missing=[name for name in FONTS if folder/name not in paths]
    if not any(re.search(r'(license|ofl|copying)',p.name,re.I) for p in paths):missing.append('license')
    if missing:raise ValueError('Missing bundled font files in '+str(folder)+': '+', '.join(missing))
    return paths


def closure(folder,seeds):
    available={p.stem for p in folder.glob('*.py')};todo=list(seeds);seen=set()
    while todo:
        name=todo.pop()
        if name in seen:continue
        if name not in available:raise ValueError('Missing runtime module: '+name)
        seen.add(name);tree=ast.parse((folder/(name+'.py')).read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            names=([x.name.split('.')[0] for x in node.names] if isinstance(node,ast.Import) else
                   [node.module.split('.')[0]] if isinstance(node,ast.ImportFrom) and node.module else [])
            for dependency in names:
                if dependency not in available or dependency in seen:continue
                if dependency.startswith('test_'):
                    # These imports are confined to developer-only preview
                    # functions, not the runtime packet generation paths.
                    if name not in ('native_menu_loading','gs_preview','loading_frames_v4'):
                        raise ValueError('Review runtime dependency on a test helper: '+name+' -> '+dependency)
                    continue
                todo.append(dependency)
    return seen


# Online play (TTM Online, bt3-multifighter/online): the lobby, its netplay code and match templates ship as online/.
# Its two blank memory cards are the only members above 4 MiB (8.25 MiB each, a few KiB compressed).
ONLINE_LARGE=('online/match/runtime/memcards/Mcd001.ps2','online/match/runtime/memcards/Mcd002.ps2')


def online_payload(project):
    """[(path, archive name)] of the online part (no caches, tests or analysis files)."""
    folder=Path(project)/'online'
    if not (folder/'netplay'/'ttm_online.py').is_file():raise ValueError('Missing the online part: '+str(folder))
    out=[]
    for path in sorted(folder.rglob('*')):
        rel=path.relative_to(folder)
        if not path.is_file() or {'__pycache__','tests','analysis'}&set(rel.parts) or path.suffix=='.pyc':continue
        out.append((path,'online/'+rel.as_posix()))
    return out


def payload_files(root=ROOT):
    """{archive name: bytes} of the player payload: both adapters, the ISO scanner and the online part."""
    files={}
    def add(path,name):
        path=Path(path)
        if path.stat().st_size>(9<<20 if name in ONLINE_LARGE else 4<<20):raise ValueError('Excessive player payload file: '+str(path))
        files[name]=path.read_bytes()
    for folder,adapter in (('bt3-multifighter','bt3-usa'),('bt4-multifighter','bt4-b14-rev2-eng')):
        project=Path(root)/folder;prefix=adapter+'/'
        seeds=SEEDS+(('bt4_preflight',) if adapter.startswith('bt4') else ())
        modules=closure(project/'tools',seeds)
        for name in modules:add(project/'tools'/(name+'.py'),prefix+'tools/'+name+'.py')
        for name in ('launch-autopilot.ps1','launcher-lifecycle.ps1','launch-settings.ps1','Mod settings.cmd','Tag Team Mod Logo.png'):
            add(project/name,prefix+name)
        for name in JSON_ASSETS:add(project/'tools'/name,prefix+'tools/'+name)
        for name in SHARED_ASSETS:add(project/name,prefix+name)
        for name in ADAPTER_ASSETS.get(adapter,()):
            if not (project/'tools'/name).is_file():
                raise ValueError('Missing '+name+' in '+str(project/'tools')+'; generate it with release_tools/'
                                 +('build_english_names.py' if name=='bt3_english_names.json' else 'build_pal_map.py'))
            add(project/'tools'/name,prefix+'tools/'+name)
        if set(NATIVE_MAP_TABLES)&set(ADAPTER_ASSETS.get(adapter,())) and 'native_map' not in modules:
            raise ValueError('The address tables (pal_native_map.json, jpn_native_map.json) are read by native_map.py: '
                             'the '+adapter+' runtime needs native_map.py')
        add(project/'tools/vendor-wheels/pycaw-20251023-py3-none-any.whl',prefix+'tools/vendor-wheels/pycaw-20251023-py3-none-any.whl')
        add(project/'tools/vendor/SDL2.dll',prefix+'tools/vendor/SDL2.dll')
        add(project/'tools/vendor/SDL2-LICENSE.txt',prefix+'tools/vendor/SDL2-LICENSE.txt')
        # The SDL game controller database (PCSX2 2.8.2's copy): the controller hub's layouts when PCSX2 has none.
        add(project/'tools/vendor/game_controller_db.txt',prefix+'tools/vendor/game_controller_db.txt')
        add(project/'tools/vendor/game_controller_db-LICENSE.txt',prefix+'tools/vendor/game_controller_db-LICENSE.txt')
        for path in bundled_fonts(project):add(path,prefix+'tools/vendor/fonts/'+path.name)
        add(project/'assets/native-menu-pre-settings.json',prefix+'assets/native-menu-pre-settings.json')
        # Ship authored presets, never the private next-battle queue or a
        # player's custom mission files. Keep this list explicit for releases.
        scenarios=['Examples/namek-piccolo-arrives.json','Examples/saiyans-goku-arrives.json',
                   'Examples/cell-games-gohan-awakens.json']
        # Public sample library: exactly the three curated story adaptations.
        # Mission 100 and user-authored documents stay in the development tree.
        for name in scenarios:add(project/'missions'/name,prefix+'missions/'+name)
        # Only exact historical patch receipts used by guarded upgrades. Never
        # include RAM, logs, saves, generated previews or a native game ELF.
        receipts={'research_opponent_patches.json'}
        for module in modules:
            text=(project/'tools'/(module+'.py')).read_text(encoding='utf-8-sig')
            for match in re.findall(r"analysis/(sept[^'\"\n]+\.(?:json|bin))",text):
                if '/' in match:continue # CLI-only captured menu fixtures are never shipped
                if '{' in match:
                    receipts.update(p.name for p in (project/'analysis').glob(re.sub(r'\{[^}]+\}','*',match)))
                else:receipts.add(match)
        for name in sorted(receipts):add(project/'analysis'/name,prefix+'analysis/'+name)
    for path in (Path(root)/'iso_compatibility').glob('*.py'):
        if not path.name.startswith('test_'):add(path,'iso_compatibility/'+path.name)
    for path,name in online_payload(Path(root)/'bt3-multifighter'):add(path,name)
    return files


def build(output,files=None):
    files=payload_files() if files is None else files
    manifest={name:hashlib.sha256(data).hexdigest() for name,data in files.items()}
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name,data in sorted(files.items()):put(archive,name,data)
        put(archive,'payload-manifest.json',json.dumps(dict(sorted(manifest.items())),indent=2).encode())
    receipt=dict(files=len(files),bytes=output.stat().st_size,sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    output.with_suffix('.json').write_text(json.dumps(receipt,indent=2))
    print(json.dumps(receipt,indent=2));return receipt


if __name__=='__main__':build(ROOT/'player-installer/player-payload.zip')
