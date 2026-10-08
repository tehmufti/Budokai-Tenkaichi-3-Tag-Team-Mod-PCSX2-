"""Maintainer-only: lock the reviewed player wheels and their licenses.

Windows (default): the CPython 3.11 win_amd64 wheels in wheels/ give requirements-player.lock,
dependencies.json and notices/. Download them with pip download --only-binary=:all: --no-deps
--platform win_amd64 --implementation cp --python-version 311 --abi cp311.
Linux (--platform linux): the manylinux x86-64 wheels in wheels-linux/ (one per CPython 3.11-3.14
where a package is version-specific) give requirements-player-linux.lock (one line per package with
the hash of every wheel; pip installs the one for the running Python), dependencies-linux.json and
notices-linux/ (the wheels' license texts, which cover the native libraries they bundle). comtypes is
Windows-only. --verify-pypi first compares every wheel's SHA-256 with PyPI's JSON API.
Normal release builds verify this receipt rather than resolving newer packages.
"""
import argparse
import email
import hashlib
import json
from pathlib import Path
import re
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / 'player-installer'
# Pythons the Linux wheel set serves; Install.sh, install_player.py and check_installation.py use the same list.
LINUX_PYTHONS = ('3.11', '3.12', '3.13', '3.14')
WINDOWS_ONLY = {'comtypes'}  # COM bindings for the Windows audio mute: importing them fails elsewhere
PLATFORMS = {
    'windows': dict(wheels='wheels', lock='requirements-player.lock', record='dependencies.json', notices='notices'),
    'linux': dict(wheels='wheels-linux', lock='requirements-player-linux.lock', record='dependencies-linux.json',
                  notices='notices-linux'),
}


def wanted_packages(setup=SETUP, platform='windows'):
    wanted = dict(line.split('==') for line in (setup/'requirements-player.txt').read_text().splitlines()
                  if line and not line.startswith('#'))
    wanted = {name.lower(): version for name, version in wanted.items()}
    return {k: v for k, v in wanted.items() if platform == 'windows' or k not in WINDOWS_ONLY}


def serves(filename, python):
    """True when pip on 64-bit CPython `python` ('3.12') for Linux x86-64 can install this wheel."""
    pythons, abi, platforms = filename[:-len('.whl')].split('-')[-3:]
    platforms = platforms.split('.')
    if not all(p == 'any' or re.fullmatch(r'manylinux(1|2010|2014|_2_\d+)_x86_64', p) for p in platforms): return False
    minor = int(python.split('.')[1])
    for tag in pythons.split('.'):
        if abi == 'none' and tag in ('py3', f'py3{minor}', f'cp3{minor}'): return True
        if abi == 'abi3' and re.fullmatch(r'cp3\d+', tag) and int(tag[3:]) <= minor: return True
        if abi == tag == f'cp3{minor}': return True
    return False


def lock(setup=SETUP, platform='windows'):
    """The receipts for the wheels in the platform's folder: {path relative to setup: text or bytes}."""
    paths = PLATFORMS[platform]
    wanted = wanted_packages(setup, platform)
    rows = {}; locks = []; licenses = {}; notices = {}
    for path in sorted((setup/paths['wheels']).glob('*.whl')):
        with zipfile.ZipFile(path) as archive:
            metadata = email.message_from_bytes(archive.read(next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))))
            name, version = metadata['Name'].lower(), metadata['Version']
            if wanted.get(name) != version or (platform == 'windows' and name in rows):
                raise ValueError('Unexpected/duplicate wheel: '+path.name)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            source = f'https://pypi.org/project/{name}/{version}/'
            if platform == 'windows':
                rows[name] = dict(version=version, file=path.name, sha256=digest, source=source)
                locks.append(f'{name}=={version} --hash=sha256:{digest}')
            else:
                if not any(serves(path.name, python) for python in LINUX_PYTHONS):
                    raise ValueError('Not a Linux x86-64 wheel for CPython '+', '.join(LINUX_PYTHONS)+': '+path.name)
                row = rows.setdefault(name, dict(version=version, files={}, source=source, bundled_libraries=[]))
                row['files'][path.name] = digest
                # auditwheel copies the native libraries a wheel links into <package>.libs/.
                row['bundled_libraries'] = sorted(set(row['bundled_libraries']) | {
                    n.rsplit('/', 1)[1] for n in archive.namelist() if re.match(r'[^/]+\.libs/[^/]+$', n)})
            for member in archive.namelist():
                if not member.endswith('/') and re.search(r'(license|copying|notice)', member, re.I):
                    # Keep entire bundled upstream texts, including nested dependencies.
                    target = f"{paths['notices']}/{name}/{member}"
                    data = archive.read(member)
                    if notices.get(target, data) != data:
                        raise ValueError('The wheels of one package carry different license texts: '+target)
                    notices[target] = data; licenses[target] = hashlib.sha256(data).hexdigest()
    if set(rows) != set(wanted): raise ValueError('Missing reviewed dependency wheel')
    if platform == 'windows':
        record = dict(python='3.11', platform='win_amd64', packages=rows, licenses=licenses)
    else:
        for name, row in rows.items():
            for python in LINUX_PYTHONS:
                if not any(serves(file, python) for file in row['files']):
                    raise ValueError(f'No {name} wheel for Linux x86-64 CPython {python}')
            locks.append(f"{name}=={row['version']} "+' '.join(f'--hash=sha256:{digest}' for digest in row['files'].values()))
        record = dict(python=list(LINUX_PYTHONS), platform='manylinux_x86_64', packages=rows, licenses=licenses)
    return {paths['lock']: '\n'.join(locks)+'\n', paths['record']: json.dumps(record, indent=2)+'\n', **notices}


def verify_pypi(folder):
    """Every wheel must be byte-identical to the file of that name that PyPI publishes."""
    published = {}
    for path in sorted(Path(folder).glob('*.whl')):
        name, version = path.name.split('-')[:2]
        if (name, version) not in published:
            with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/{version}/json', timeout=60) as response:
                published[name, version] = {u['filename']: u['digests']['sha256'] for u in json.load(response)['urls']}
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if published[name, version].get(path.name) != digest:
            raise ValueError(f'{path.name} does not match PyPI (local {digest})')
    return len(list(Path(folder).glob('*.whl')))


def write(outputs, setup=SETUP, platform='windows'):
    for name, data in outputs.items():
        target = setup/name
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes): target.write_bytes(data)
        # The Windows receipts keep their historical platform line endings; Linux ones are LF everywhere.
        elif platform == 'windows': target.write_text(data, encoding='ascii' if name.endswith('.lock') else 'utf-8')
        else: target.write_bytes(data.encode('utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--platform', choices=tuple(PLATFORMS), default='windows')
    parser.add_argument('--verify-pypi', action='store_true')
    args = parser.parse_args()
    if args.verify_pypi: print(f"PyPI verified {verify_pypi(SETUP/PLATFORMS[args.platform]['wheels'])} wheels")
    outputs = lock(SETUP, args.platform)
    write(outputs, SETUP, args.platform)
    record = json.loads(outputs[PLATFORMS[args.platform]['record']])
    print(f"Locked {len(record['packages'])} dependencies and {len(record['licenses'])} license files")


if __name__ == '__main__': main()
