"""Fetch hash-pinned build inputs without adding binaries to source history."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT/'player-installer'
RELEASE_SHA = '2fa69604107504d3a311cf37acdb3ee0026b36b543c8e5f5954730bf965de0df'
RELEASE_URL = ('https://github.com/tehmufti/Budokai-Tenkaichi-3-Tag-Team-Mod-PCSX2-'
               '/releases/download/v0.1.0-beta.11.1/Tag.Team.Mod.0.1.0-beta.11.1.zip')

def digest(data):
    return hashlib.sha256(data).hexdigest()

def download(url):
    request = urllib.request.Request(url, headers={'User-Agent':'Tag-Team-Mod-Dependency-Bootstrap'})
    with urllib.request.urlopen(request, timeout=180) as response:
        return response.read()

def put(path, data, expected):
    if digest(data) != expected:
        raise ValueError('Hash mismatch: '+path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.download')
    temporary.write_bytes(data)
    temporary.replace(path)

def bootstrap(zip_path=None, platform='both'):
    cache = ROOT/f'.downloads/version11-1-{RELEASE_SHA[:16]}.zip'
    path = Path(zip_path) if zip_path else cache
    if not path.is_file():
        if zip_path:
            raise FileNotFoundError(path)
        put(cache, download(RELEASE_URL), RELEASE_SHA)
    raw = path.read_bytes()
    if digest(raw) != RELEASE_SHA:
        raise ValueError('Expected the published Version 11.1 Windows installer ZIP')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        prefix = 'Tag Team Mod Installer/setup/'
        if platform in ('windows','both'):
            record = json.loads((SETUP/'dependencies.json').read_text())
            for row in record['packages'].values():
                data = archive.read(prefix+'wheels/'+row['file'])
                put(SETUP/'wheels'/row['file'], data, row['sha256'])
        with zipfile.ZipFile(io.BytesIO(archive.read(prefix+'player-payload.zip'))) as payload:
            manifest = json.loads(payload.read('payload-manifest.json'))
            mapping = {}
            for adapter, project in (('bt3-usa','bt3-multifighter'),('bt4-b14-rev2-eng','bt4-multifighter')):
                for suffix in ('tools/vendor/SDL2.dll', 'tools/vendor-wheels/pycaw-20251023-py3-none-any.whl'):
                    mapping[adapter+'/'+suffix] = ROOT/project/suffix
            for card in ('Mcd001.ps2','Mcd002.ps2'):
                name = 'online/match/runtime/memcards/'+card
                mapping[name] = ROOT/'bt3-multifighter'/name
            for name, target in mapping.items():
                put(target, payload.read(name), manifest[name])
    if platform in ('linux','both'):
        record = json.loads((SETUP/'dependencies-linux.json').read_text())
        for package, row in record['packages'].items():
            metadata = None
            for filename, expected in row['files'].items():
                target = SETUP/'wheels-linux'/filename
                if target.is_file() and digest(target.read_bytes()) == expected:
                    continue
                if metadata is None:
                    metadata = json.loads(download(f'https://pypi.org/pypi/{package}/{row["version"]}/json'))
                candidate = next((item for item in metadata['urls'] if item['filename']==filename), None)
                if not candidate or candidate['digests']['sha256'] != expected:
                    raise ValueError('Pinned wheel is not published by PyPI: '+filename)
                put(target, download(candidate['url']), expected)
    print('Pinned dependencies and online templates are ready. Generated inputs remain ignored by Git.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-zip', type=Path)
    parser.add_argument('--platform', choices=('windows','linux','both'), default='both')
    arguments = parser.parse_args()
    bootstrap(arguments.release_zip, arguments.platform)
