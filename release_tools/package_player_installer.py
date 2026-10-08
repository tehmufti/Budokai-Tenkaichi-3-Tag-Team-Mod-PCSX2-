"""Build a versioned player release with pinned, verified offline dependencies: the Windows ZIP and the
Linux x86-64 tar.gz. Both carry the same player payload bytes."""
import calendar
import argparse
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import zipfile
from build_player_bundle import build,put
from verify_bt4_port import verify

ROOT=Path(__file__).resolve().parents[1]
PREFIX='Tag Team Mod Installer/'
WINDOWS_FILES=('Install.cmd','install-player.ps1','install_player.py','requirements-player.txt',
               'player-payload.zip','player-payload.json','README.md','CHANGELOG.md','THIRD_PARTY_NOTICES.md',
               'requirements-player.lock','dependencies.json','release.json','check_installation.py','installer-es.json','LEEME.md','README.txt','player-defaults.json',
               'messages.json','setup_messages.py')
LINUX_FILES=('Install.sh','install_linux.py','install_player.py','check_installation.py','player-payload.zip','player-payload.json',
             'README.md','LEEME.md','CHANGELOG.md','THIRD_PARTY_NOTICES.md','README.txt','release.json','installer-es.json',
             'player-defaults.json','requirements-player-linux.lock','dependencies-linux.json','messages.json','setup_messages.py')
TOP_LEVEL={'windows':('Install.cmd','README.txt'),'linux':('Install.sh','README.txt')}
# The ZIP entries' fixed time (build_player_bundle.put): 2026-09-21 00:00 UTC.
TAR_MTIME=calendar.timegm((2026,9,21,0,0,0,0,0,0))
# The European disc the shipped address table (bt3-multifighter/tools/pal_native_map.json) is checked against.
PAL_ISO=ROOT/'games/Dragon Ball Z - Budokai Tenkaichi 3 (AU,EU) (En,Ja,Fr,De,Es,It) (2007) (Versus Fighting) (ISO) (PS2).iso'
# The Japanese disc behind jpn_native_map.json, and the USA disc behind bt3_english_names.json.
JPN_ISO=ROOT/'games/Dragon Ball Z - Sparking! Meteor (Japan).iso'
USA_ISO=ROOT/'games/Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso'


def check_pal_map(iso=None):
    """The European adapter's address table must be current: build_pal_map.py --check regenerates it from the
    European executable and DBZP.BIN and compares. Packaging stops when it is stale or cannot be checked."""
    iso=Path(iso or os.environ.get('TAGTEAM_PAL_ISO') or PAL_ISO)
    if not iso.is_file():raise ValueError('The European BT3 ISO is needed to check pal_native_map.json: '+str(iso))
    usa=Path(os.environ.get('TAGTEAM_USA_ISO') or USA_ISO)
    result=subprocess.run([sys.executable,'-B',str(ROOT/'release_tools/build_pal_map.py'),'--iso',str(iso),'--usa-iso',str(usa),'--check'],
                          cwd=ROOT,capture_output=True,text=True,timeout=1800)
    if result.returncode:
        raise ValueError('pal_native_map.json is stale or could not be checked:\n'+result.stdout+result.stderr)


def check_jpn_map(iso=None):
    """The Japanese adapter's address table must be current (build_pal_map.py --region jpn --check against the
    Japanese executable and DBZP.BIN), and so must the English fighter names it uses (build_english_names.py --check
    against the USA disc). Packaging stops when either is stale or cannot be checked."""
    iso=Path(iso or os.environ.get('TAGTEAM_JPN_ISO') or JPN_ISO)
    if not iso.is_file():raise ValueError('The Japanese BT3 ISO is needed to check jpn_native_map.json: '+str(iso))
    usa=Path(os.environ.get('TAGTEAM_USA_ISO') or USA_ISO)
    result=subprocess.run([sys.executable,'-B',str(ROOT/'release_tools/build_pal_map.py'),'--region','jpn','--iso',str(iso),'--usa-iso',str(usa),
                           '--check'],cwd=ROOT,capture_output=True,text=True,timeout=1800)
    if result.returncode:
        raise ValueError('jpn_native_map.json is stale or could not be checked:\n'+result.stdout+result.stderr)
    usa=Path(os.environ.get('TAGTEAM_USA_ISO') or USA_ISO)
    result=subprocess.run([sys.executable,'-B',str(ROOT/'release_tools/build_english_names.py'),'--iso',str(usa),'--check'],
                          cwd=ROOT,capture_output=True,text=True,timeout=600)
    if result.returncode:
        raise ValueError('bt3_english_names.json is stale or could not be checked:\n'+result.stdout+result.stderr)


def checked_dependencies(source,platform='windows'):
    if platform=='linux':return checked_linux_dependencies(source)
    record=json.loads((source/'dependencies.json').read_text())
    expected={row['file'] for row in record['packages'].values()}
    if expected!={p.name for p in (source/'wheels').iterdir()}:raise ValueError('Unreviewed/missing wheel in release')
    lock=(source/'requirements-player.lock').read_text()
    for name,row in record['packages'].items():
        if hashlib.sha256((source/'wheels'/row['file']).read_bytes()).hexdigest()!=row['sha256']:
            raise ValueError('Dependency hash changed: '+name)
        if f"{name}=={row['version']} --hash=sha256:{row['sha256']}" not in lock:
            raise ValueError('Dependency lock changed: '+name)
    for name,digest in record['licenses'].items():
        if hashlib.sha256((source/name).read_bytes()).hexdigest()!=digest:raise ValueError('License changed: '+name)
    return record


def checked_linux_dependencies(source):
    """dependencies-linux.json, the Linux lock (one line per package, one hash per wheel) and wheels-linux/ agree."""
    record=json.loads((source/'dependencies-linux.json').read_text(encoding='utf-8'))
    files={file:digest for row in record['packages'].values() for file,digest in row['files'].items()}
    if set(files)!={p.name for p in (source/'wheels-linux').iterdir()}:raise ValueError('Unreviewed/missing Linux wheel in release')
    if 'comtypes' in record['packages']:raise ValueError('comtypes is Windows-only')
    lines=[line for line in (source/'requirements-player-linux.lock').read_text(encoding='utf-8').splitlines() if line and not line.startswith('#')]
    if len(lines)!=len(record['packages']):raise ValueError('Linux dependency lock changed')
    for name,row in record['packages'].items():
        for file,digest in row['files'].items():
            if hashlib.sha256((source/'wheels-linux'/file).read_bytes()).hexdigest()!=digest:
                raise ValueError('Linux dependency hash changed: '+file)
        if f"{name}=={row['version']} "+' '.join(f'--hash=sha256:{digest}' for digest in row['files'].values()) not in lines:
            raise ValueError('Linux dependency lock changed: '+name)
    for name,digest in record['licenses'].items():
        if hashlib.sha256((source/name).read_bytes()).hexdigest()!=digest:raise ValueError('License changed: '+name)
    return record


def other_notices(source):
    """notices/ files that are no Windows wheel's license (the bundled fonts' OFL): the Linux release ships them too."""
    wheels=set(json.loads((source/'dependencies.json').read_text())['packages'])
    return sorted(p.relative_to(source).as_posix() for p in (source/'notices').rglob('*')
                  if p.is_file() and p.relative_to(source/'notices').parts[0] not in wheels)


def release_paths(source,platform='windows'):
    """{source file name: path inside the release folder}, sorted by source name."""
    if platform=='windows':
        names=set(WINDOWS_FILES)|{p.relative_to(source).as_posix() for directory in ('notices','wheels') for p in (source/directory).rglob('*') if p.is_file()}
    else:
        names=set(LINUX_FILES)|set(other_notices(source))|{p.relative_to(source).as_posix()
              for directory in ('notices-linux','wheels-linux') for p in (source/directory).rglob('*') if p.is_file()}
    return {name:(name if name in TOP_LEVEL[platform] else 'setup/'+name) for name in sorted(names)}


def linux_notices(source):
    """The Linux THIRD_PARTY_NOTICES.md, generated by the installer's own code (install_player.linux_notices) from
    dependencies-linux.json, so the release and the installations it makes carry the same text."""
    spec=importlib.util.spec_from_file_location('tagteam_install_player',Path(source)/'install_player.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.linux_notices(source).encode('utf-8')


def linux_archive(source,release):
    """The Linux release tar.gz as bytes. Deterministic: sorted members, no directory entries, fixed mtime, uid/gid 0
    without owner names, Install.sh 0755 and every other file 0644, gzip header without a name or time. Its
    installer-files.json is built in memory; nothing is written into player-installer/. Its THIRD_PARTY_NOTICES.md
    is the Linux text (linux_notices), not the Windows file."""
    paths=release_paths(source,'linux')
    files={paths[name]:(source/name).read_bytes() for name in paths}
    # Keep one obvious entry point in each download, with instructions for its OS.
    files['README.txt']=(source/'README-linux.txt').read_bytes()
    files['setup/THIRD_PARTY_NOTICES.md']=linux_notices(source)
    if b'\r' in files['Install.sh']:raise ValueError('Install.sh must use LF line endings')
    manifest=dict(schema=2,version=release['version'],files={name:hashlib.sha256(files[name]).hexdigest() for name in files})
    files['setup/installer-files.json']=(json.dumps(manifest,indent=2)+'\n').encode('utf-8')
    buffer=io.BytesIO()
    with gzip.GzipFile(filename='',mode='wb',fileobj=buffer,mtime=0,compresslevel=9) as compressed:
        with tarfile.open(fileobj=compressed,mode='w',format=tarfile.PAX_FORMAT) as archive:
            for name in sorted(files):
                info=tarfile.TarInfo(PREFIX+name);info.size=len(files[name]);info.mtime=TAR_MTIME
                info.mode=0o755 if name=='Install.sh' else 0o644
                info.type=tarfile.REGTYPE;info.uid=info.gid=0;info.uname=info.gname=''
                archive.addfile(info,io.BytesIO(files[name]))
    return buffer.getvalue()


def write_receipt(output,release,**extra):
    receipt=dict(file=output.name,bytes=output.stat().st_size,sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                 version=release['version'],status='public beta; installation verified separately from gameplay',
                 adapters=release['adapters'],gameplay_certified=False,**extra)
    stem=output.name.removesuffix('.tar.gz').removesuffix('.zip')
    output.with_name(stem+'.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))
    output.with_name(stem+'.sha256').write_text(receipt['sha256']+'  '+output.name+'\n',encoding='ascii')
    problems=receipt_problems(output.with_name(stem+'.json'))
    if problems:raise ValueError('Release receipt does not match its file: '+'; '.join(problems))
    return receipt


def receipt_problems(receipt_path):
    """What is wrong with one release receipt (<name>.json): its 'file' must exist beside it with the recorded size and
    SHA-256, and the .sha256 file must name that file. A player running sha256sum -c needs all three to agree."""
    receipt_path=Path(receipt_path);problems=[]
    try:receipt=json.loads(receipt_path.read_text())
    except (OSError,ValueError) as error:return [f'{receipt_path.name}: unreadable ({error})']
    if not isinstance(receipt,dict) or 'file' not in receipt:return []  # not a release receipt
    target=receipt_path.with_name(receipt['file'])
    if not target.is_file():return [f'{receipt_path.name} names {receipt["file"]}, which does not exist']
    if target.stat().st_size!=receipt.get('bytes'):problems.append(f'{target.name}: size differs from {receipt_path.name}')
    elif hashlib.sha256(target.read_bytes()).hexdigest()!=receipt.get('sha256'):problems.append(f'{target.name}: SHA-256 differs from {receipt_path.name}')
    checksum=receipt_path.with_suffix('.sha256')
    if checksum.is_file() and checksum.read_text(encoding='ascii').strip().partition('  ')[2]!=receipt['file']:
        problems.append(f'{checksum.name} does not name {receipt["file"]}')
    return problems


def stale_receipts(folder):
    """Receipts in a release folder whose file is missing, renamed or changed (reported when packaging)."""
    return [problem for path in sorted(Path(folder).glob('*.json')) for problem in receipt_problems(path)]


def reviewed_payload(plan_path):
    """A frozen release plus individually reviewed overlays, while feature development continues locally.

    Verify every input hash; never silently include unrelated new imports or developer assets.
    """
    plan=json.loads(Path(plan_path).read_text(encoding='utf-8'))
    baseline=ROOT/plan['baseline']
    if hashlib.sha256(baseline.read_bytes()).hexdigest()!=plan['baseline_sha256']:
        raise ValueError('Reviewed release baseline changed')
    with zipfile.ZipFile(baseline) as archive:
        data=archive.read(PREFIX+'setup/player-payload.zip')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        files={n:archive.read(n) for n in archive.namelist() if n!='payload-manifest.json'}
        manifest=json.loads(archive.read('payload-manifest.json'))
        if manifest!={n:hashlib.sha256(d).hexdigest() for n,d in files.items()}:
            raise ValueError('Reviewed baseline payload manifest differs')
    baseline_files=dict(files)
    for name,row in plan['overlays'].items():
        data=(ROOT/row['source']).read_bytes()
        if hashlib.sha256(data).hexdigest()!=row['sha256']:
            raise ValueError('Review overlay again after its source changed: '+row['source'])
        files[name]=data
    for adapter in ('bt3-usa','bt4-b14-rev2-eng'):
        available={Path(n).stem for n in files if n.startswith(adapter+'/tools/') and Path(n).suffix=='.py'}
        # Any project-local import must also ship. stdlib and pinned third-party imports are unaffected.
        local={p.stem for p in (ROOT/('bt3-multifighter' if adapter=='bt3-usa' else 'bt4-multifighter')/'tools').glob('*.py')}
        for name,data in files.items():
            if not name.startswith(adapter+'/tools/') or not name.endswith('.py'):continue
            import ast
            for node in ast.walk(ast.parse(data.decode('utf-8-sig'))):
                imports=([x.name.split('.')[0] for x in node.names] if isinstance(node,ast.Import) else
                         [node.module.split('.')[0]] if isinstance(node,ast.ImportFrom) and node.module else [])
                for module in imports:
                    if module in local and module not in available and not module.startswith('test_'):
                        # Older public builds have explicitly optional story imports.
                        # Preserve that reviewed behavior, without admitting new missing dependencies.
                        old=baseline_files.get(name,b'').decode('utf-8-sig')
                        if ('import '+module+' ') in old or ('import '+module+'\r') in old or ('import '+module+'\n') in old:
                            continue
                        raise ValueError('Reviewed payload missing import '+name+' -> '+module)
    return files


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reviewed-overlay',type=Path,help='Frozen baseline and hash-checked release overlays')
    args=parser.parse_args()
    verify();check_pal_map();check_jpn_map();source=ROOT/'player-installer';checked_dependencies(source);checked_dependencies(source,'linux')
    build(source/'player-payload.zip',files=reviewed_payload(args.reviewed_overlay) if args.reviewed_overlay else None)
    release=json.loads((source/'release.json').read_text())
    output=ROOT/'releases'/('Tag Team Mod '+release['version']+'.zip');output.parent.mkdir(exist_ok=True)
    paths=release_paths(source,'windows');names=list(paths)
    manifest=dict(schema=2,version=release['version'],files={paths[name]:hashlib.sha256((source/name).read_bytes()).hexdigest() for name in names})
    (source/'installer-files.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    temporary=output.with_suffix('.tmp')
    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name in names:put(archive,PREFIX+paths[name],(source/name).read_bytes())
        put(archive,PREFIX+'setup/installer-files.json',(source/'installer-files.json').read_bytes())
    with zipfile.ZipFile(temporary) as archive:
        if archive.testzip():raise ValueError('Release ZIP validation failed')
    temporary.replace(output)
    write_receipt(output,release)
    # Linux: the same payload bytes, its own manifest (in memory) and the Linux wheels.
    linux=output.with_name('Tag Team Mod '+release['version']+' linux-x86_64.tar.gz')
    temporary=linux.with_name(linux.name+'.tmp');temporary.write_bytes(linux_archive(source,release))
    with tarfile.open(temporary) as archive:
        if archive.getmember(PREFIX+'setup/player-payload.zip').size!=(source/'player-payload.zip').stat().st_size:
            raise ValueError('Linux release validation failed')
    temporary.replace(linux)
    write_receipt(linux,release,platform='linux-x86_64')
    for problem in stale_receipts(output.parent):print('WARNING: '+problem)


if __name__=='__main__':main()
