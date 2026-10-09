"""Build a small updater from a verified full installer of the same release.

No development payload is rebuilt or implicitly included. The updater carries
the exact released player payload and reuses the installed Python dependencies.
Usage: python release_tools/package_player_updater.py <installer.zip|tar.gz>
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
PREFIX='Tag Team Mod Installer/'
UPREFIX='Tag Team Mod Updater/'


def sha(data):return hashlib.sha256(data).hexdigest()
def encode(value):return (json.dumps(value,indent=2)+'\n').encode('utf-8')


def installer_files(path):
    path=Path(path)
    if path.suffix=='.zip':
        with zipfile.ZipFile(path) as archive:
            rows=archive.infolist()
            if sum(r.file_size for r in rows)>512<<20:raise ValueError('Installer is too large')
            if any(r.is_dir() or (r.external_attr>>16)&0o170000==0o120000 for r in rows):raise ValueError('Unexpected installer member')
            names=[r.filename for r in rows];files={r.filename:archive.read(r) for r in rows}
        platform='windows'
    else:
        with tarfile.open(path,'r:gz') as archive:
            rows=archive.getmembers()
            if sum(r.size for r in rows)>512<<20 or any(not r.isfile() for r in rows):raise ValueError('Unexpected installer member')
            names=[r.name for r in rows];files={r.name:archive.extractfile(r).read() for r in rows}
        platform='linux'
    if len(names)!=len(set(names)):raise ValueError('Duplicate installer member')
    manifest_name=PREFIX+'setup/installer-files.json'
    manifest=json.loads(files[manifest_name])
    expected={PREFIX+n:checksum for n,checksum in manifest['files'].items()}
    if set(files)!=set(expected)|{manifest_name}:raise ValueError('Installer inventory differs from its manifest')
    for name,checksum in expected.items():
        if not name.startswith(PREFIX) or any(p in ('','.','..') or ':' in p or '\\' in p for p in name.split('/')):
            raise ValueError('Unsafe installer member')
        if sha(files[name])!=checksum:raise ValueError('Installer checksum failed: '+name)
    return platform,files


def build(installer,output=None,source=None):
    platform,original=installer_files(installer)
    source=Path(source or ROOT/'player-installer')
    prefix=PREFIX+'setup/'
    setup={n[len(prefix):]:data for n,data in original.items() if n.startswith(prefix) and
           not any(n.startswith(prefix+x) for x in ('wheels/','wheels-linux/','downloads/')) and
           n!=prefix+'installer-files.json'}
    release=json.loads(setup['release.json']);version=release['version']
    if sha(setup['player-payload.zip'])!=json.loads(setup['player-payload.json'])['sha256']:
        raise ValueError('Player payload checksum failed')
    setup['update_player.py']=(source/'update_player.py').read_bytes()
    if platform=='windows':setup['update-player.ps1']=(source/'update-player.ps1').read_bytes()
    setup['updater-files.json']=encode(dict(schema=1,version=version,files={n:sha(d) for n,d in setup.items()}))
    launch='Update.cmd' if platform=='windows' else 'Update.sh'
    files={UPREFIX+'setup/'+n:data for n,data in setup.items()}
    files[UPREFIX+launch]=(source/launch).read_bytes()
    files[UPREFIX+'README.txt']=(source/'README-updater.txt').read_bytes()
    output=Path(output or Path(installer).parent);output.mkdir(parents=True,exist_ok=True)
    name=f'Tag Team Mod Updater {version}'+('.zip' if platform=='windows' else ' linux-x86_64.tar.gz')
    target=output/name
    if platform=='windows':
        from build_player_bundle import put
        with zipfile.ZipFile(target,'w') as archive:
            for n,data in sorted(files.items()):put(archive,n,data)
    else:
        with target.open('wb') as stream,gzip.GzipFile(filename='',fileobj=stream,mode='wb',mtime=0) as gz,tarfile.open(fileobj=gz,mode='w') as archive:
            for n,data in sorted(files.items()):
                info=tarfile.TarInfo(n);info.size=len(data);info.mode=0o755 if n.endswith('/Update.sh') else 0o644
                archive.addfile(info,io.BytesIO(data))
    result=dict(file=name,version=version,sha256=sha(target.read_bytes()),bytes=target.stat().st_size,
                installer_sha256=sha(Path(installer).read_bytes()),payload_sha256=sha(setup['player-payload.zip']))
    target.with_name(name+'.json').write_bytes(encode(result))
    target.with_name(name+'.sha256').write_text(result['sha256']+'  '+name+'\n',encoding='ascii')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('installer',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args();print(json.dumps(build(args.installer,args.output),indent=2))


if __name__=='__main__':main()
