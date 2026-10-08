"""The lobby's fighter and stage catalog, built by each kit from its OWN BT3 USA ISO with Python's standard library
only (the guest's portable Python has no Pillow or pycdlib). Ported from the p33 prototype kit_catalog_proto.py.

  data/catalog/<tables_sha16>/catalog.json   {schema, version, family, disc, tables_sha256, characters:[{id, name,
                                              base, form, costumes, portrait, selectable}], stages:[{id, name, thumb,
                                              grid, tested}], grid:[cells], stage_grid, random_stage}
  data/catalog/<tables_sha16>/portraits/NNN.png   64x64 RGBA: AFS1 index 450, package 1, BPE, parts 29/30/31
  data/catalog/<tables_sha16>/stages/NN.png       64x64 RGBA: AFS1 index 448, package 1, BPE, part 45 (index = id)

Costume counts: AFS1 file 10*id+1424+k (k 0..3) counts when it is larger than 2 KiB and its extent is not a repeat
(equal to the mod's compatibility profile for all 161 fighters). Selectable ids (0..159) and the game's grid come
from netplay/data/bt3-usa-select-grid.json; stage names only from netplay/data/stages.json (read off the game's own
map-select labels: 28 is "Cell Game - Noon"). Both PCs must have the identical ISO (the disc check), so nothing here
travels: only ids do. A failure is TTM-NET-33.
"""
import hashlib
import json
import os
import struct
import time
import zlib
from pathlib import Path

import kit_paths
from kit_codes import KitError

AFS1 = '/DATA/PZS3US1.AFS;1'
SCHEMA, VERSION = 'ttm-online-catalog', 2
FAMILY, DISC = 'bt3', 'bt3-usa'
COUNT = 161


def data_file(name):
    return json.loads((kit_paths.NETPLAY / 'data' / name).read_text(encoding='utf-8'))


class Iso:
    def __init__(self, path):
        self.f = open(path, 'rb')
        pvd = self.sector(16)
        if pvd[:6] != b'\x01CD001':
            self.f.close()
            raise ValueError('not an ISO 9660 image')
        self.root = self.record(pvd, 156)

    def close(self):
        self.f.close()

    def sector(self, lba, count=1):
        self.f.seek(lba * 2048)
        return self.f.read(2048 * count)

    @staticmethod
    def record(data, at):
        return dict(extent=struct.unpack_from('<I', data, at + 2)[0], size=struct.unpack_from('<I', data, at + 10)[0],
                    dir=bool(data[at + 25] & 2), name=data[at + 33:at + 33 + data[at + 32]])

    def entry(self, path):
        node = self.root
        for part in [p for p in path.strip('/').split('/') if p]:
            data = self.sector(node['extent'], (node['size'] + 2047) // 2048)[:node['size']]
            found, at = None, 0
            while at < len(data):
                if data[at] == 0:
                    at = (at // 2048 + 1) * 2048
                    continue
                r = self.record(data, at)
                if r['name'].decode('ascii', 'replace').upper() == part.upper():
                    found = r
                    break
                at += data[at]
            if found is None:
                raise FileNotFoundError(path)
            node = found
        return node

    def read_at(self, path, offset, length):
        e = self.entry(path)
        if offset + length > e['size']:
            raise ValueError(f'{path}: read beyond its end')
        self.f.seek(e['extent'] * 2048 + offset)
        return self.f.read(length)


def package(data):
    count = struct.unpack_from('<I', data)[0]
    if not 0 < count <= 4096 or 4 * (count + 2) > len(data):
        raise ValueError('invalid package count')
    offsets = struct.unpack_from('<' + str(count + 1) + 'I', data, 4)
    if offsets[0] < 4 * (count + 2) or offsets[-1] > len(data) or any(a >= b for a, b in zip(offsets, offsets[1:])):
        raise ValueError('invalid package offsets')
    return [data[a:b] for a, b in zip(offsets, offsets[1:])]


def unpack_bpe(data):
    """The game's byte-pair blocks (the mod's extract_loading_assets.unpack_bpe, with a per-block expansion cache)."""
    expected, packed = struct.unpack_from('<II', data)
    if not 0 < expected <= 16 << 20 or not 0 < packed <= len(data) - 8:
        raise ValueError('invalid compressed lengths')
    data, cursor, output = data[:packed + 8], 8, bytearray()
    while len(output) < expected:
        left, right, code = list(range(256)), [0] * 256, 0
        while code < 256:
            count = data[cursor]
            cursor += 1
            if count > 127:
                code, count = code + count - 127, 0
            if code >= 256:
                break
            for _ in range(count + 1):
                left[code] = data[cursor]
                cursor += 1
                if left[code] != code:
                    right[code] = data[cursor]
                    cursor += 1
                code += 1
        length = data[cursor] * 256 + data[cursor + 1]
        cursor += 2
        cache = {}

        def expand(c, depth=0):
            hit = cache.get(c)
            if hit is not None:
                return hit
            if depth > 256:
                raise ValueError('cyclic byte-pair dictionary')
            out = bytes((c,)) if left[c] == c else expand(left[c], depth + 1) + expand(right[c], depth + 1)
            cache[c] = out
            return out
        for value in data[cursor:cursor + length]:
            output += expand(value)
        cursor += length
    return bytes(output[:expected])


def label(data):
    if not data.startswith(b'\xff\xfe'):
        raise ValueError('expected a UTF-16 label')
    text = []
    for pos in range(2, len(data) - 1, 2):
        code = struct.unpack_from('<H', data, pos)[0]
        if not (32 <= code <= 126 or code in (0xAA, 0xB0, 0xBA) or (192 <= code <= 255 and chr(code).isalpha())):
            break
        text.append(chr(code))
    return ''.join(text).strip()


def texture64(data):
    """64x64 PSMT8 + CSM1 palette (portraits and stage thumbnails): RGBA bytes."""
    if len(data) != 0x1580:
        raise ValueError('unexpected texture size')
    tex0 = struct.unpack_from('<Q', data, 0x50)[0]
    if ((tex0 >> 20) & 63, (tex0 >> 26) & 15, (tex0 >> 30) & 15) != (19, 6, 6):
        raise ValueError('unexpected texture layout')
    pixels, palette, colors = data[0xC0:0x10C0], data[0x1140:0x1540], []
    for index in range(256):
        e = (index & 0xE7) | ((index & 8) << 1) | ((index & 16) >> 1)
        r, g, b, a = palette[e * 4:e * 4 + 4]
        colors.append(bytes((r, g, b, min(255, a * 2))))
    out = bytearray()
    for y in range(64):
        for x in range(64):
            block = (y & ~15) * 64 + (x & ~15) * 2
            swap = (((y + 2) >> 2) & 1) * 4
            row = (((y & ~3) >> 1) + (y & 1)) & 7
            out += colors[pixels[block + row * 128 + ((x + swap) & 7) * 4 + ((y >> 1) & 1) + ((x >> 2) & 2)]]
    return bytes(out)


def png(width, height, rgba):
    raw = b''.join(b'\0' + rgba[y * width * 4:(y + 1) * width * 4] for y in range(height))
    chunk = lambda kind, body: struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


def read_tables(iso_path):
    """(afs table bytes, ui package parts, menu package parts) of the ISO; ValueError when it is not BT3 USA."""
    iso = Iso(iso_path)
    try:
        magic, count = struct.unpack('<4sI', iso.read_at(AFS1, 0, 8))
        if magic != b'AFS\0' or count != 3399:
            raise ValueError('not the BT3 USA AFS1 volume')
        table = iso.read_at(AFS1, 8, count * 8)
        afs = lambda index: struct.unpack_from('<II', table, index * 8)

        def read(index):
            off, size = afs(index)
            return iso.read_at(AFS1, off, size)
        ui = package(unpack_bpe(package(read(450))[1]))
        menu = package(unpack_bpe(package(read(448))[1]))
    finally:
        iso.close()
    return table, ui, menu


def _build_usa(iso_path, out_root=None):
    """Build the catalog of `iso_path` into data/catalog/<tables_sha16>/; returns the catalog dict (with 'dir')."""
    t0 = time.perf_counter()
    try:
        table, ui, menu = read_tables(iso_path)
        afs = lambda index: struct.unpack_from('<II', table, index * 8)
        names, forms, portraits, thumbs = package(ui[29]), package(ui[30]), package(ui[31]), package(menu[45])
        if (len(names), len(forms), len(portraits), len(thumbs)) != (168, 168, 165, 38):
            raise ValueError('unexpected UI tables (not the BT3 USA disc?)')
        digest = hashlib.sha256(table + b''.join(names) + b''.join(forms)).hexdigest()
        grid = data_file('bt3-usa-select-grid.json')
        stage_data = data_file('stages.json')
        selectable = set(grid['selectable_ids'])
        out = Path(out_root or (kit_paths.DATA / 'catalog')) / digest[:16]
        (out / 'portraits').mkdir(parents=True, exist_ok=True)
        (out / 'stages').mkdir(parents=True, exist_ok=True)
        characters = []
        for cid in range(COUNT):
            base, form = label(names[cid]), label(forms[cid])
            offs = [afs(10 * cid + 1423 + k)[0] for k in range(4)]          # table index = file id - 1
            sizes = [afs(10 * cid + 1423 + k)[1] for k in range(4)]
            costumes = sum(1 for k in range(4) if sizes[k] > 0x800 and offs[k] not in offs[:k])
            (out / 'portraits' / f'{cid:03d}.png').write_bytes(png(64, 64, texture64(portraits[cid])))
            characters.append(dict(id=cid, name=base + (f' - {form}' if form else ''), base=base, form=form,
                                   costumes=costumes, portrait=f'portraits/{cid:03d}.png',
                                   selectable=cid in selectable))
        if (characters[0]['base'], characters[55]['base'], characters[133]['form']) != \
                ('Goku (Early)', 'Hercule', 'Legendary Super Saiyan'):
            raise ValueError('character identity check failed')
        tested = {int(k) for k in stage_data.get('online_tested', {})}
        stage_grid = stage_data['grid']
        stages = []
        for s in stage_data['stages']:
            sid = s['id']
            (out / 'stages' / f'{sid:02d}.png').write_bytes(png(64, 64, texture64(thumbs[sid])))
            cell = stage_grid.index(sid) if sid in stage_grid else None
            stages.append(dict(id=sid, name=s['name'], thumb=f'stages/{sid:02d}.png',
                               grid=None if cell is None else [cell // 6, cell % 6], tested=sid in tested))
        (out / 'stages' / f'{stage_data["random_id"]:02d}.png').write_bytes(
            png(64, 64, texture64(thumbs[stage_data['random_id']])))
        catalog = dict(schema=SCHEMA, version=VERSION, family=FAMILY, disc=DISC, tables_sha256=digest,
                       characters=characters, stages=stages, random_stage=stage_data['random_id'],
                       random_thumb=f'stages/{stage_data["random_id"]:02d}.png',
                       grid=[dict(cell=c['cell'], row=c['row'], col=c['col'], base=c['base'],
                                  forms=[f for f in c['forms'] if f in selectable])
                             for c in grid['grid'] if c['base'] in selectable],
                       stage_grid=stage_grid, seconds=round(time.perf_counter() - t0, 3))
    except (OSError, ValueError, KeyError, IndexError, struct.error) as error:
        raise KitError('TTM-NET-33', what=f'{Path(iso_path).name}: {error}') from None
    tmp = out / 'catalog.json.tmp'
    tmp.write_text(json.dumps(catalog, indent=1), encoding='utf-8')
    tmp.replace(out / 'catalog.json')
    catalog['dir'] = str(out)
    return catalog



def build(iso_path, out_root=None):
    """Read roster, costumes, portraits and stages from the selected reviewed disc."""
    if kit_paths.ADAPTER == 'bt3-usa':
        return _build_usa(iso_path, out_root)
    from iso_compatibility.disc import Disc, entry
    from iso_compatibility.adapters import runtime_match, verify_stage_mapping
    import kit_adapter
    t0 = time.perf_counter()
    try:
        with Disc(iso_path) as disc:
            adapter, evidence = runtime_match(disc)
            if not adapter or not evidence.get('verified') or adapter.name != kit_paths.ADAPTER:
                raise ValueError('disc does not match the selected reviewed adapter')
            verify_stage_mapping(disc, adapter)
            table_raw = disc.read(adapter.character_table_file)
            table = entry(table_raw, 0)
            counts = [struct.unpack_from('<H', table, i * 60 + (40 if adapter.kind == 'bt4-indexed' else 10))[0]
                      for i in range(adapter.characters)]
            ui = package(unpack_bpe(package(disc.read(adapter.ui_text_file))[1]))
            names, forms, portraits = package(ui[29]), package(ui[30]), package(ui[31])
            # Original BT3 has a fixed grid; BT4's expanded roster is searchable as a list.
            grid = data_file('bt3-usa-select-grid.json') if adapter.kind == 'bt3-afs' else {'grid': [], 'selectable_ids': range(adapter.characters)}
            selectable = set(grid['selectable_ids']) - set(adapter.menu_only)
            if adapter.text_language == 'ja':
                from regional import english_names
                english = english_names()
            else:
                english = None
            digest = hashlib.sha256(table_raw + b''.join(names) + b''.join(forms) + disc.elf).hexdigest()
            out = Path(out_root or (kit_paths.DATA / 'catalog')) / digest[:16]
            (out / 'portraits').mkdir(parents=True, exist_ok=True)
            (out / 'stages').mkdir(parents=True, exist_ok=True)
            characters = []
            blank = png(64, 64, bytes([32, 42, 60, 255]) * 4096)
            for cid in range(adapter.characters):
                base, form = english[cid] if english else (label(names[cid]), label(forms[cid]))
                picture = png(64, 64, texture64(portraits[cid])) if cid < len(portraits) else blank
                (out / 'portraits' / f'{cid:03d}.png').write_bytes(picture)
                characters.append(dict(id=cid, name=base + (f' - {form}' if form else ''), base=base, form=form,
                                       costumes=counts[cid], portrait=f'portraits/{cid:03d}.png',
                                       selectable=cid in selectable and counts[cid] > 0))
            # Stage identifiers/resources are verified above. Never reuse USA thumbnails for expanded BT4 IDs.
            stage_data = data_file('stages.json')
            original_stages = {s['id']: s['name'] for s in stage_data['stages']}
            stages = []
            for sid in range(adapter.stage_count):
                (out / 'stages' / f'{sid:02d}.png').write_bytes(blank)
                name = original_stages.get(sid, f'Stage {sid + 1}') if adapter.kind == 'bt3-afs' else f'Stage {sid + 1}'
                stages.append(dict(id=sid, name=name, thumb=f'stages/{sid:02d}.png', grid=None, tested=False))
            (out / 'stages/random.png').write_bytes(blank)
            catalog = dict(schema=SCHEMA, version=VERSION, family='bt4' if adapter.kind == 'bt4-indexed' else 'bt3',
                           disc=adapter.name, tables_sha256=digest, characters=characters, stages=stages,
                           random_stage=-1, random_thumb='stages/random.png', grid=grid['grid'],
                           stage_grid=list(range(adapter.stage_count)), seconds=round(time.perf_counter() - t0, 3))
    except (OSError, ValueError, KeyError, IndexError, struct.error) as error:
        raise KitError('TTM-NET-33', what=f'{Path(iso_path).name}: {error}') from None
    tmp = out / 'catalog.json.tmp'
    tmp.write_text(json.dumps(catalog, indent=1), encoding='utf-8')
    tmp.replace(out / 'catalog.json')
    catalog['dir'] = str(out)
    return catalog


def _iso_key(iso_path):
    st = os.stat(iso_path)
    return f'{os.path.abspath(iso_path).lower()}|{st.st_size}|{st.st_mtime_ns}'


def load(iso_path, out_root=None, rebuild=False):
    """The catalog of this PC's ISO (built once per ISO, about 0.7 s; then read from data/catalog)."""
    root = Path(out_root or (kit_paths.DATA / 'catalog'))
    index_path = root / 'index.json'
    try:
        index = json.loads(index_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        index = {}
    key = _iso_key(iso_path)
    sha16 = index.get(key)
    if sha16 and not rebuild:
        try:
            catalog = json.loads((root / sha16 / 'catalog.json').read_text(encoding='utf-8'))
            if catalog.get('schema') == SCHEMA and catalog.get('version') == VERSION and \
                    catalog.get('tables_sha256', '')[:16] == sha16 and \
                    (root / sha16 / 'portraits' / f'{len(catalog["characters"]) - 1:03d}.png').is_file():
                catalog['dir'] = str(root / sha16)
                return with_current_marks(catalog)
        except (OSError, ValueError):
            pass
    catalog = build(iso_path, root)
    index[key] = catalog['tables_sha256'][:16]
    root.mkdir(parents=True, exist_ok=True)
    tmp = index_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(index, indent=1), encoding='utf-8')
    tmp.replace(index_path)
    return catalog


def with_current_marks(catalog):
    """The stages' 'tested' marks from this kit's data/stages.json (R-STAGES results of this kit version)."""
    if catalog.get('disc') != 'bt3-usa':
        return catalog
    try:
        tested = {int(k) for k in data_file('stages.json').get('online_tested', {})}
    except (OSError, ValueError, KeyError, TypeError):
        return catalog
    for s in catalog.get('stages', []):
        s['tested'] = s.get('id') in tested
    return catalog


def read_dir(path):
    """A catalog folder written by build() (the UI reads the session's catalog this way)."""
    catalog = json.loads((Path(path) / 'catalog.json').read_text(encoding='utf-8'))
    catalog['dir'] = str(path)
    return with_current_marks(catalog)


class View:
    """Fast lookups over a catalog dict."""

    def __init__(self, catalog):
        self.c = catalog
        self.chars = {c['id']: c for c in catalog['characters']}
        self.stages = {s['id']: s for s in catalog['stages']}
        self.selectable = sorted(c['id'] for c in catalog['characters'] if c.get('selectable'))
        self.tested = sorted(s['id'] for s in catalog['stages'] if s.get('tested'))

    def name(self, cid):
        c = self.chars.get(cid)
        return c['name'] if c else f'#{cid}'

    def costumes(self, cid):
        c = self.chars.get(cid)
        return c['costumes'] if c else 0

    def stage_name(self, sid):
        if sid == 'random' or sid == self.c.get('random_stage'):
            return 'Random'
        s = self.stages.get(sid)
        return s['name'] if s else f'Stage {sid}'

    def find(self, text):
        t = text.strip().lower()
        return [c for c in self.c['characters'] if c.get('selectable') and t in c['name'].lower()]

    def stage_order(self):
        """Stage ids in the map-select grid order, then the ones the grid does not show."""
        seen = [s for s in self.c.get('stage_grid', []) if s in self.stages]
        return seen + sorted(s for s in self.stages if s not in seen)
