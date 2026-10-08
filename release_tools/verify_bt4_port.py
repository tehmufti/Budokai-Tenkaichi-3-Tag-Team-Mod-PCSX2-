"""Detect drift in shared BT3/BT4 runtime features and the reviewed BT4 overlay.

--record is a maintainer action after reviewing adapter changes. Normal builds
only verify; they never copy BT3 addresses or erase BT4 resource adaptations.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
from build_player_bundle import closure,SEEDS,SHARED_ASSETS

ROOT=Path(__file__).resolve().parents[1]
RECEIPT=Path(__file__).with_name('bt4-port-manifest.json')
# Entry points are feature behavior too. These used to be absent from the
# receipt, allowing BT4's unconditional CMD pause to escape the port audit.
ENTRYPOINTS={
    'Play.cmd':'Play.cmd',
    'Mod settings.cmd':'Mod settings.cmd',
    'BT3 Workbench.cmd':'BT3 Workbench.cmd',
    'Install modder tools.cmd':'Install modder tools.cmd',
    'launch-modder.ps1':'launch-modder.ps1',
    # Linux developer-tree launchers (player installs generate their own); both run play_launcher.py.
    'Play.sh':'Play.sh',
    'Mod settings.sh':'Mod settings.sh',
}

# These are shared gameplay policies, not ISO resource loaders. Recording a
# new receipt must not silently bless a BT4 copy that has fallen behind BT3.
CPU_SHARED_MODULES=(
    'ai_expand','ai_shadow','battle_mode_policy','battle_modes',
    'cpu_retaliation','distinct_ai','extra_specials','ffa_targeting','initial_targets',
    'los_targets','modded_training','team_ai','team_config_ai','team_pair_ai',
    'team_six_ai','team_survivor_ai','team_targets','team_targets6',
)

# These gameplay policies carry no BT4 resource-layout facts. A refreshed
# receipt must not approve a missing scenario event, cinematic safety guard
# or split-screen defusion fix in the BT4 payload.
SESSION_SHARED_MODULES=(
    'arena_bounds','cinematic_position','cinematic_position_camera',
    'fusion_defusion_animation','fusion_defusion_placement','fusion_duration_commit',
    'story_runtime','story_rules','story_missions','story_cinematics','story_cast',
    'display_settings','quad_viewports',
)


def verify_session_parity(current):
    for module in SESSION_SHARED_MODULES:
        name=f'tools/{module}.py'
        if not current['files'].get(name,{}).get('shared'):
            raise ValueError('Shared session gameplay differs between BT3 and BT4: '+name)


def verify_cpu_parity(current,root=ROOT):
    for module in CPU_SHARED_MODULES:
        name=f'tools/{module}.py'
        if not current['files'].get(name,{}).get('shared'):
            raise ValueError('CPU behavior/targeting differs between BT3 and BT4: '+name)
    # The trainer as a whole intentionally differs: BT4 installs its own model
    # metadata. Its final gameplay composition must still install the same CPU
    # behavior, including team/training targeting after battle-mode setup.
    functions=[]
    for project in ('bt3-multifighter','bt4-multifighter'):
        path=root/project/'tools/fresh_team_trainer.py'
        tree=ast.parse(path.read_text(encoding='utf-8-sig'))
        matches=[n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='final_team_manifest']
        if len(matches)!=1:raise ValueError('Missing final gameplay installation: '+str(path))
        functions.append(ast.dump(matches[0],include_attributes=False))
    if functions[0]!=functions[1]:
        raise ValueError('BT4 final gameplay installation differs from BT3; review CPU targeting integration')


def digest(data):return hashlib.sha256(data).hexdigest()


def inventory():
    main=ROOT/'bt3-multifighter';port=ROOT/'bt4-multifighter'
    modules=closure(main/'tools',SEEDS+('modder_gui',))
    names={f'tools/{name}.py'for name in modules}
    names.update('tools/'+p.name for p in (main/'tools').glob('loading_*.json'))
    names.update(SHARED_ASSETS)
    # The bundled Linux fonts (and their license/README) ship in both payloads; compared byte for byte.
    names.update('tools/vendor/fonts/'+p.name for p in sorted((main/'tools/vendor/fonts').iterdir()) if p.is_file())
    names.update(('Tag Team Mod Logo.png','tools/native_menu_labels.json','tools/pcsx2_versions.json','assets/native-menu-pre-settings.json',
                  'launch-autopilot.ps1','launcher-lifecycle.ps1','launch-settings.ps1'))
    result={}
    for before_name,after_name in ENTRYPOINTS.items():
        before=(main/before_name).read_bytes();after=(port/after_name).read_bytes()
        same=before.decode('utf-8-sig').replace('\r\n','\n')==after.decode('utf-8-sig').replace('\r\n','\n')
        if not same:
            raise ValueError(f'Shared launcher behavior differs: {before_name} -> {after_name}')
        result[after_name]=dict(bt3=digest(before),bt4=digest(after),shared=True,bt3_path=before_name)
    for name in sorted(names):
        before=(main/name).read_bytes();after=(port/name).read_bytes()
        # JSON payloads contain compressed hex: never substitute digit strings.
        normalized=before
        if name.endswith('.py'):
            normalized=before.decode('utf-8-sig').replace('\r\n','\n').replace('SLUS-21678','SLUS-21978').replace('SLUS_216.78','SLUS_219.78').replace('28011','28012').encode()
            after=after.decode('utf-8-sig').replace('\r\n','\n').encode()
        result[name]=dict(bt3=digest(before),bt4=digest((port/name).read_bytes()),
                          shared=normalized==after)
    for name in sorted(closure(port/'tools',SEEDS+('modder_gui','bt4_preflight'))-modules):
        result[f'tools/{name}.py']=dict(bt4=digest((port/'tools'/(name+'.py')).read_bytes()),shared=False)
    # BT3's map entry point lives at the workspace root and uses a different
    # adapter. Keep BT4's intentional launcher in the review inventory too.
    result['Build expanded maps.cmd']=dict(bt4=digest((port/'Build expanded maps.cmd').read_bytes()),shared=False)
    return dict(schema=1,files=result)


def verify():
    current=inventory();expected=json.loads(RECEIPT.read_text())
    verify_cpu_parity(current);verify_session_parity(current)
    changed=[name for name,row in current['files'].items() if expected['files'].get(name)!=row]
    changed+=sorted(set(expected['files'])-set(current['files']))
    if changed:raise ValueError('BT4 port review is stale: '+', '.join(changed))
    print(f"BT4 port receipt verified: {len(current['files'])} runtime/artwork files")
    print(f'CPU behavior/targeting parity verified: {len(CPU_SHARED_MODULES)} shared modules and final gameplay installation')
    print(f'Scenario/cinematic/defusion parity verified: {len(SESSION_SHARED_MODULES)} shared modules')
    return current


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--record',action='store_true');args=parser.parse_args()
    if args.record:
        current=inventory();verify_cpu_parity(current);verify_session_parity(current)
        RECEIPT.write_text(json.dumps(current,indent=2)+'\n');print(RECEIPT)
    else:verify()
