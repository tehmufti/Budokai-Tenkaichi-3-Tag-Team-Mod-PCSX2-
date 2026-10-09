"""Transactional player updates. No ISO, BIOS, saves or user settings are replaced.

Run from an extracted official updater, using the existing installation's Python.
The write-ahead journal also recovers an interrupted update on the next run.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid

HERE=Path(__file__).resolve().parent
DOCUMENTS=('release.json','check_installation.py',
           'setup_messages.py','messages.json','README.md','LEEME.md','CHANGELOG.md','THIRD_PARTY_NOTICES.md')
ADAPTERS={'bt3-usa':'bt3-usa','bt3-pal':'bt3-usa','bt3-jpn':'bt3-usa','bt4-b14-rev2-eng':'bt4-b14-rev2-eng'}


def require(condition,message):
    if not condition:raise ValueError(message)


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def linked(path):
    return path.is_symlink() or bool(getattr(path.lstat(),'st_file_attributes',0)&0x400)


def bounded(root,name):
    require(isinstance(name,str) and name and '\\' not in name,'Invalid update path')
    require(not Path(name).is_absolute() and all(x not in ('','..','.') for x in name.split('/')),
            'Update path escapes its installation')
    require(not any(':' in x or x.endswith((' ','.')) for x in name.split('/')),'Invalid update filename')
    path=Path(root)
    for ancestor in (path,*path.parents):
        if ancestor.exists():require(not linked(ancestor),'Update root is reached through a link or junction')
    for part in name.split('/'):
        path/=part
        if path.exists() or path.is_symlink():require(not linked(path),'Update refuses a link or junction: '+name)
    require(path.resolve().is_relative_to(Path(root).resolve()),'Update path escaped its installation')
    return path


def atomic(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    mode=stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    fd,name=tempfile.mkstemp(prefix='.'+path.name+'-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out:out.write(data);out.flush();os.fsync(out.fileno())
        if mode is not None:os.chmod(name,mode)
        os.replace(name,path)
    finally:
        Path(name).unlink(missing_ok=True)


def json_bytes(value):return (json.dumps(value,indent=2,ensure_ascii=False)+'\n').encode('utf-8')
def read_json(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


@contextmanager
def update_lock(root):
    """OS lock releases after a crash; the separate journal is retained."""
    path=bounded(root,'.update.lock')
    with path.open('a+b') as stream:
        if path.stat().st_size==0:stream.write(b'0');stream.flush()
        stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:raise ValueError('Another update is running. Wait for it to finish.') from None
        yield


def assert_closed(root):
    import psutil
    own=os.getpid();ancestors={p.pid for p in psutil.Process().parents()}
    root=str(Path(root).resolve()).casefold()
    for p in psutil.process_iter(['pid','exe','cmdline']):
        if p.pid==own or p.pid in ancestors:continue
        try:
            args=p.info.get('cmdline') or []
            if any(root in str(arg).casefold() for arg in [p.info.get('exe') or '',*args]):
                raise ValueError('Close Play, Play online, Mod Settings, Workbench and PCSX2 before updating.')
        except (psutil.NoSuchProcess,psutil.AccessDenied):continue


class Transaction:
    def __init__(self,root,version):
        self.root=Path(root);self.path=bounded(root,'update-status.json')
        name='update-backups/'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
        self.backup=bounded(root,name);self.backup.mkdir(parents=True)
        self.state=dict(schema=1,state='applying',version=version,backup=name,files={},modes={})
        self.record()

    def record(self):atomic(self.path,json_bytes(self.state))

    def remember(self,name):
        if name in self.state['files']:return
        path=bounded(self.root,name);saved=bounded(self.backup,name)
        require(not path.exists() or path.is_file(),'Cannot replace a directory: '+name)
        old=None
        if path.exists():
            saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,saved);old=digest(saved)
            with saved.open('r+b') as stream:os.fsync(stream.fileno())
            require(digest(path)==old,'File changed while backing it up: '+name)
            self.state['modes'][name]=stat.S_IMODE(path.stat().st_mode)
        self.state['files'][name]=old
        self.record()  # Durable backup + journal always precede the destination write.

    def write(self,name,data):
        self.remember(name);atomic(bounded(self.root,name),data)

    def remove(self,name):
        self.remember(name);bounded(self.root,name).unlink(missing_ok=True)

    def finish(self):
        self.state['state']='complete';self.record()
        atomic(self.backup/'update-receipt.json',json_bytes(self.state))


def recover(root,completed=False):
    path=bounded(root,'update-status.json')
    if not path.is_file():return False
    state=read_json(path)
    if state.get('state')=='rolled-back' or (state.get('state')=='complete' and not completed):return False
    if completed and state.get('state')=='complete':state['state']='applying'
    require(state.get('schema')==1 and state.get('state') in ('applying','rolling-back'),
            'Unknown update journal; keep update-status.json and contact support.')
    backup=bounded(root,state['backup']);files=state['files']
    # Check every recovery source before altering anything.
    for name,sha in files.items():
        bounded(root,name)
        if sha is not None:require(digest(bounded(backup,name))==sha,'Update backup is damaged: '+name)
    state['state']='rolling-back';atomic(path,json_bytes(state))
    for name,sha in reversed(list(files.items())):
        target=bounded(root,name)
        if sha is None:target.unlink(missing_ok=True)
        else:
            atomic(target,bounded(backup,name).read_bytes())
            if name in state.get('modes',{}):target.chmod(state['modes'][name])
    state['state']='rolled-back';atomic(path,json_bytes(state))
    print('Previous files restored from the update backup.',flush=True)
    return True


def environment():
    env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8',PYTHONNOUSERSITE='1',BT3_RUNTIME_PROFILE='runtime28')
    for key in ('PYTHONPATH','PYTHONHOME','TAGTEAM_DISC','TAGTEAM_ADAPTER'):env.pop(key,None)
    return env


def run(root,script,*args):
    python=root/('.venv/Scripts/python.exe' if os.name=='nt' else '.venv/bin/python')
    result=subprocess.run([str(python),'-B',str(script),*map(str,args)],cwd=root,env=environment(),
                          capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=600,
                          **({'creationflags':0x08000000} if os.name=='nt' else {}))
    print(result.stdout, end='',flush=True)
    if result.returncode:raise ValueError(result.stderr.strip() or 'Check failed: '+Path(script).name)


def setup_files(setup,windows):
    result={name:(setup/name).read_bytes() for name in DOCUMENTS}
    lock='requirements-player.lock' if windows else 'requirements-player-linux.lock'
    deps='dependencies.json' if windows else 'dependencies-linux.json'
    result['requirements-player.lock']=(setup/lock).read_bytes()
    record=read_json(setup/deps)
    if not windows:
        record['licenses']={('notices/'+key.split('/',1)[1] if key.startswith('notices-linux/') else key):value
                            for key,value in record['licenses'].items()}
    result['dependencies.json']=json_bytes(record) if not windows else (setup/deps).read_bytes()
    # Linux bundles its dependency notices separately and shared font notices in notices/.
    for directory in (('notices',) if windows else ('notices','notices-linux')):
        for path in (setup/directory).rglob('*'):
            if path.is_file():result['notices/'+path.relative_to(setup/directory).as_posix()]=path.read_bytes()
    return result


def verify_bundle(setup):
    bundle=read_json(setup/'updater-files.json')
    require(bundle.get('schema')==1 and isinstance(bundle.get('files'),dict),'Invalid updater manifest.')
    actual={p.relative_to(setup).as_posix() for p in setup.rglob('*') if p.is_file()}
    require(actual==set(bundle['files'])|{'updater-files.json'},'Updater contains missing or unexpected files; extract a fresh copy.')
    for name,sha in bundle['files'].items():
        require(digest(bounded(setup,name))==sha,'Updater file is missing or damaged: '+name)
    return bundle


def source_files(root,work,setup,adapter,installer):
    result={}
    for prefix,dest in ((ADAPTERS[adapter],'game'),('iso_compatibility','iso_compatibility'),('online','online')):
        directory=work/prefix
        require(directory.is_dir(),'Missing update payload: '+prefix)
        for path in directory.rglob('*'):
            if not path.is_file():continue
            relative=path.relative_to(directory).as_posix();name=dest+'/'+relative
            if os.name!='nt' and prefix==ADAPTERS[adapter] and relative in installer.WINDOWS_ONLY_GAME_FILES:continue
            # Authors may have edited a shipped scenario. Never silently replace it.
            if name.startswith('game/missions/') and bounded(root,name).exists():continue
            result[name]=path.read_bytes()
    result.update(setup_files(setup,os.name=='nt'))
    language=read_json(root/'game/mod-settings.json').get('language','en')
    scripts=installer.windows_scripts(language) if os.name=='nt' else installer.linux_scripts(adapter,language)
    result.update({name:text.encode('ascii' if os.name=='nt' else 'utf-8') for name,text in scripts.items()})
    # No user preferences, discs, BIOS, emulator binaries or mutable online data belong in this update.
    for name in result:
        bounded(root,name)
        require(not name.startswith(('game/runtime','game/discs/','game/maps/','online/pcsx2/','online/data/','online/prep/')),
                'Unexpected mutable or emulator file in update payload: '+name)
        require(name!='game/mod-settings.json','An update must not replace user settings')
    return result


def update(root,setup=HERE):
    root=Path(root).absolute();setup=Path(setup).resolve()
    require(root.is_dir() and not linked(root),'Choose the existing Tag Team Mod installation folder.')
    # Existing dependency environment is deliberately reused; no global Python changes.
    assert_closed(root)
    with update_lock(root):
        recover(root)
        verify_bundle(setup)
        receipt=read_json(root/'installed-files.json');release=read_json(setup/'release.json')
        adapter=receipt.get('adapter');require(adapter in ADAPTERS,'This installation has an unsupported adapter.')
        require(receipt.get('schema')==1 and isinstance(receipt.get('files'),dict),'Invalid installation receipt.')
        def version(s):
            match=re.fullmatch(r'(\d+)\.(\d+)\.(\d+)-beta\.(\d+)',s)
            require(match is not None,'Unrecognized release version: '+str(s));return tuple(map(int,match.groups()))
        require(version(receipt['version'])<version(release['version']),'This installation is already this version or newer.')
        lockname='requirements-player.lock' if os.name=='nt' else 'requirements-player-linux.lock'
        require((root/'requirements-player.lock').read_bytes()==(setup/lockname).read_bytes(),
                'This release changes Python dependencies. Use its full installer and import your previous installation.')
        require(shutil.disk_usage(root).free>512<<20,'Free at least 512 MiB before updating.')
        import install_player as installer
        with tempfile.TemporaryDirectory(prefix='.ttm-update-',dir=root) as folder:
            work=Path(folder);installer.unpack(setup/'player-payload.zip',work)
            files=source_files(root,work,setup,adapter,installer)
            old=receipt['files']
            changed={name:data for name,data in files.items() if not (root/name).is_file() or digest(root/name)!=hashlib.sha256(data).hexdigest()}
            stale=[name for name in old if name not in files and name.endswith('.py') and
                   name.startswith(('game/tools/','online/netplay/','iso_compatibility/'))]
            print(f'Updating to {release["version"]}: {len(changed)} files, {len(stale)} retired modules.',flush=True)
            assert_closed(root)
            transaction=Transaction(root,release['version'])
            try:
                for name,data in changed.items():transaction.write(name,data)
                for name in stale:transaction.remove(name)
                marker=read_json(root/'game/player-install.json');marker['version']=release['version']
                transaction.write('game/player-install.json',json_bytes(marker))
                # Boot hooks are regenerated from the updated source in a temporary output folder. The guest
                # compiler picks the selected regional disc, without altering ISO or emulator configuration.
                helper=work/'compile-hook.py'
                helper.write_text('import sys\nfrom pathlib import Path\nsys.path.insert(0,sys.argv[1])\n'
                    'import guest_loading_screen as g,game_profile as p\nfrom native_map import SERIAL\n'
                    'target=Path(sys.argv[2])/p.cheat_name(SERIAL)\ng.install_cheat(target)\n',encoding='utf-8')
                hooks=work/'hooks';run(root,helper,root/'game/tools',hooks)
                cheatdir='game/runtime28/'+('' if os.name=='nt' else 'PCSX2/')+'cheats/'
                for path in hooks.iterdir():transaction.write(cheatdir+path.name,path.read_bytes())
                # Retain original ISO-derived receipts; change only the replaced/new managed code and documents.
                updated=dict(old)
                for name in stale:updated.pop(name,None)
                for name,data in files.items():
                    if not name.startswith('game/missions/'):updated[name]=hashlib.sha256(data).hexdigest()
                updated['game/player-install.json']=digest(root/'game/player-install.json')
                receipt.update(version=release['version'],files=updated)
                transaction.write('installed-files.json',json_bytes(receipt))
                for name in ('check-status.json','check-installation.log'):transaction.remember(name)
                run(root,root/'check_installation.py','--quiet-failure')
                checked=read_json(root/'check-status.json')
                require(checked.get('installation_valid') and checked.get('ready'),'Updated installation did not pass its checks.')
                status=read_json(root/'install-status.json');status.update(version=release['version'],ready=True)
                transaction.write('install-status.json',json_bytes(status))
                if os.name!='nt':
                    for name in files:
                        if name.endswith('.sh') and '/' not in name:(root/name).chmod(0o755)
                transaction.finish()
            except BaseException:
                recover(root)
                raise
            print('Update complete. Start Play as usual. Backup: '+str(transaction.backup),flush=True)
            return dict(version=release['version'],backup=str(transaction.backup),changed=len(changed))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('installation',nargs='?',type=Path);parser.add_argument('--restore',action='store_true')
    args=parser.parse_args();root=args.installation
    if root is None:
        import tkinter as tk
        from tkinter import filedialog
        window=tk.Tk();window.withdraw()
        selected=filedialog.askdirectory(title='Choose your installed Tag Team Mod folder',parent=window)
        window.destroy()
        if not selected:return 1
        root=Path(selected)
    try:
        if args.restore:
            assert_closed(root)
            with update_lock(root):recover(root,completed=True)
        else:update(root)
        return 0
    except (OSError,ValueError,KeyError,subprocess.TimeoutExpired) as error:
        print('UPDATE STOPPED: '+str(error),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
