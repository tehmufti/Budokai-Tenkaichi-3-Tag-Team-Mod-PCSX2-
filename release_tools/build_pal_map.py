"""Generate bt3-multifighter/tools/pal_native_map.json, the USA -> European (SLES-54945) native address table, or
(--region jpn) jpn_native_map.json, the USA -> Japanese (SLPS-25815, Sparking! Meteor) table.

The tools keep USA addresses and wrap them: A(usa) for native addresses, GPO(off) for gp-relative offsets
(the assemblers apply it to base register 28), RANGE(usa, n) for native byte ranges. This script scans every
non-test tools module for those arguments, maps each through the durable research mapper (pal_addrmap.py)
and writes the table native_map.py reads for the bt3-pal (bt3-jpn) adapter. It fails, and writes nothing, unless
every statically known argument maps with 'exact' or 'high' confidence or has a reviewed value in
release_tools/pal_reviewed.json (jpn_reviewed.json) ({"overrides": {usa: target}, "ranges": {"usa+len": [target, len]},
"notes": {usa: why}}), which wins over the mapper.

The regions differ only in their inputs and two mapper data rules (REGIONS): the Japanese executable keeps USA's
gp, small-data and .bss addresses and its 60 Hz replay records, so its mapper keeps equal address pairs as evidence
and does not apply the European replay-record rule. For Japan the addresses that shipped data files hand to A() at
run time (DATA_ADDRESSES) are mapped too; the European table keeps them as reviewed overrides.

The gp window (every byte $gp can reach, USA 0x2FC270..0x30C270) is stored as constant-delta segments of
bytes that map exact/high, so offsets computed at run time still translate or fail closed.

usage:
  python -B release_tools/build_pal_map.py [--region pal|jpn] [--pal-elf P --pal-dbzp P | --iso TARGET.iso]
                                           [--usa-elf P --usa-dbzp P | --usa-iso USA.iso]
                                           [--hexrays SLUS_216.78.c] [--out FILE] [--check] [--quiet]
Defaults: --region pal; USA executable bt3-multifighter/analysis/SLUS_216.78, USA DBZP.BIN and the target disc's
files from the ISOs under games/ (opened read-only); --pal-elf/--pal-dbzp (aliases --target-elf/--target-dbzp) name
the target disc's executable and DBZP.BIN. --check regenerates in memory and exits 1 if the table is stale.
Nothing is written except --out (default the tools table); the mapper cache goes to the temp folder.
"""
import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TOOLS = ROOT / 'bt3-multifighter' / 'tools'
OUT = TOOLS / 'pal_native_map.json'
REVIEWED = HERE / 'pal_reviewed.json'
USA_ISO = ROOT / 'games' / 'Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso'
PAL_ISO = ROOT / 'games' / ('Dragon Ball Z - Budokai Tenkaichi 3 (AU,EU) (En,Ja,Fr,De,Es,It) (2007) '
                            '(Versus Fighting) (ISO) (PS2).iso')
JPN_ISO = ROOT / 'games' / 'Dragon Ball Z - Sparking! Meteor (Japan).iso'
USA_ELF = ROOT / 'bt3-multifighter' / 'analysis' / 'SLUS_216.78'
HEXRAYS = ROOT / 'bt3-multifighter' / 'analysis' / 'SLUS_216.78.c'
USA_GP, PAL_GP, JPN_GP = 0x304270, 0x305370, 0x304270
# One record per target disc. mapper: pal_addrmap.load options (the target executable's data rules).
REGIONS = {
    'pal': dict(adapter='bt3-pal', serial='SLES_549.45', name='European', gp=PAL_GP, gp_key='pal', iso=PAL_ISO,
                reviewed=REVIEWED, table='pal_native_map.json', mapper={}, data_addresses=False),
    'jpn': dict(adapter='bt3-jpn', serial='SLPS_258.15', name='Japanese', gp=JPN_GP, gp_key='jpn', iso=JPN_ISO,
                reviewed=HERE / 'jpn_reviewed.json', table='jpn_native_map.json',
                mapper=dict(keep_equal_pairs=True, replay=False), data_addresses=True),
}
# Shipped data files whose native addresses a module translates through A() at run time (no static A() argument):
# file -> (rows key, address field, reading module). fresh_team_combat.selector_sites reads these.
DATA_ADDRESSES = {ROOT / 'bt3-multifighter' / 'analysis' / 'research_opponent_patches.json':
                  ('patches', 'address', 'fresh_team_combat.selector_sites')}
NATIVE_LO, NATIVE_HI = 0x100000, 0x3BE71C          # USA ELF image .. end of the DBZP.BIN overlay
GOOD = ('exact', 'high')
MEM_METHODS = {'lb', 'lbu', 'lh', 'lhu', 'lw', 'lwu', 'ld', 'lq', 'sb', 'sh', 'sw', 'sd', 'sq', 'lwc1', 'swc1',
               'addiu', 'daddiu'}


def hx(v):
    return '0x%x' % v


# ------------------------------------------------------------------------------------------ inputs

def iso_members(path, names):
    """Read ISO members read-only: {'elf': boot executable, 'serial': ..., name: bytes}."""
    import io
    import pycdlib
    iso = pycdlib.PyCdlib()
    iso.open(str(path))                                   # pycdlib opens the image 'rb'
    try:
        def member(p):
            out = io.BytesIO(); iso.get_file_from_iso_fp(out, iso_path=p); return out.getvalue()
        cnf = member('/SYSTEM.CNF;1')
        m = re.search(rb'(?im)^\s*BOOT2\s*=\s*cdrom0:\\([^\s;]+);1', cnf)
        if not m:
            raise SystemExit(f'{path}: SYSTEM.CNF names no boot executable')
        boot = m[1].decode('ascii')
        out = dict(serial=boot, elf=member('/' + boot + ';1'))
        for n in names:
            out[n] = member(n)
        return out
    finally:
        iso.close()


def inputs(args, region=None):
    region = region or REGIONS['pal']
    if args.pal_elf or args.pal_dbzp:
        if not (args.pal_elf and args.pal_dbzp):
            raise SystemExit('--pal-elf and --pal-dbzp go together')
        pal = (Path(args.pal_elf).read_bytes(), Path(args.pal_dbzp).read_bytes())
    else:
        m = iso_members(args.iso or region['iso'], ['/BIN/DBZP.BIN;1'])
        if m['serial'] != region['serial']:
            raise SystemExit(f'{args.iso or region["iso"]} boots {m["serial"]}, not the {region["name"]} '
                             f'{region["serial"]}')
        pal = (m['elf'], m['/BIN/DBZP.BIN;1'])
    if args.usa_elf and args.usa_dbzp:
        usa = (Path(args.usa_elf).read_bytes(), Path(args.usa_dbzp).read_bytes())
    else:
        m = None
        if not args.usa_dbzp:
            m = iso_members(args.usa_iso or USA_ISO, ['/BIN/DBZP.BIN;1'])
            if m['serial'] != 'SLUS_216.78':
                raise SystemExit(f'{args.usa_iso or USA_ISO} boots {m["serial"]}, not SLUS_216.78')
        elf = Path(args.usa_elf).read_bytes() if args.usa_elf else (
            USA_ELF.read_bytes() if USA_ELF.is_file() else m['elf'])
        usa = (elf, Path(args.usa_dbzp).read_bytes() if args.usa_dbzp else m['/BIN/DBZP.BIN;1'])
    hexrays = Path(args.hexrays) if args.hexrays else (HEXRAYS if HEXRAYS.is_file() else None)
    return usa, pal, hexrays


# ------------------------------------------------------------------------------------------ scanning

SCOPES = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef,
          ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp)


class Evaluator:
    """Constant-folds the argument of A()/GPO()/RANGE() and base-28 immediates. A name resolves in its
    innermost binding scope (comprehension, function, module) to every value it is assigned there; a
    parameter or any non-constant assignment makes it unknown."""

    def __init__(self, tree):
        self.parent = {}
        for n in ast.walk(tree):
            for c in ast.iter_child_nodes(n):
                self.parent[c] = n
        self.bindings = {}                                 # (scope node, name) -> [value node | None]
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    self._bind(self.scope(n), t, n.value)
            elif isinstance(n, (ast.AugAssign, ast.AnnAssign)) and isinstance(n.target, ast.Name):
                self.bindings.setdefault((self.scope(n), n.target.id), []).append(None)
            elif isinstance(n, ast.For):
                self._bind(self.scope(n), n.target, n.iter, iterate=True)
            elif isinstance(n, ast.comprehension):
                self._bind(self.parent[n], n.target, n.iter, iterate=True)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                a = n.args
                for x in a.args + a.kwonlyargs + a.posonlyargs + [v for v in (a.vararg, a.kwarg) if v]:
                    self.bindings.setdefault((n, x.arg), []).append(None)

    def scope(self, node):
        n = self.parent.get(node)
        while n is not None and not isinstance(n, SCOPES):
            n = self.parent.get(n)
        return n

    def _bind(self, scope, target, value, iterate=False):
        if isinstance(target, ast.Name):
            vals = self._iter(value) if iterate else [value]
            for v in (vals if vals is not None else [None]):
                self.bindings.setdefault((scope, target.id), []).append(v)
        elif isinstance(target, (ast.Tuple, ast.List)):
            items = self._iter(value) if iterate else [value]
            for item in (items if items is not None else [None]):
                if isinstance(item, (ast.Tuple, ast.List)) and len(item.elts) == len(target.elts):
                    for t, v in zip(target.elts, item.elts):
                        self._bind(scope, t, v)
                else:
                    for t in target.elts:
                        self._bind(scope, t, None)
        else:
            for t in ast.walk(target):
                if isinstance(t, ast.Name):
                    self.bindings.setdefault((scope, t.id), []).append(None)

    @staticmethod
    def _iter(node):
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return list(node.elts)
        return None

    def lookup(self, name, node):
        s = self.scope(node)
        while s is not None:
            if (s, name) in self.bindings:
                return self.bindings[(s, name)]
            s = self.scope(s)
        return None

    def ev(self, node, depth=0):
        """Every constant value the expression can take (empty set when unknown)."""
        if depth > 12 or node is None:
            return set()
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return {node.value}
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return {-v for v in self.ev(node.operand, depth + 1)}
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.BitOr, ast.BitAnd)):
            left, right = self.ev(node.left, depth + 1), self.ev(node.right, depth + 1)
            if not left or not right or len(left) * len(right) > 64:
                return set()
            op = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
                  ast.BitOr: lambda a, b: a | b, ast.BitAnd: lambda a, b: a & b}[type(node.op)]
            return {op(a, b) for a in left for b in right}
        if isinstance(node, ast.Name):
            values = self.lookup(node.id, node)
            if not values:
                return set()
            out = set()
            for v in values:
                got = self.ev(v, depth + 1)
                if not got:
                    return set()
                out |= got
            return out
        return set()


def scan(tools):
    """Statically known USA arguments: A (addresses), GPO/base-28 (gp offsets), RANGE (ranges)."""
    found = dict(addr={}, gp={}, ranges={}, dynamic=[])
    for f in sorted(tools.glob('*.py')):
        if f.name.startswith('test_') or f.name == 'native_map.py':
            continue
        text = f.read_text(encoding='utf-8')
        if 'native_map' not in text:
            continue
        tree = ast.parse(text)
        e = Evaluator(tree)
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            fn = n.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
            site = f'{f.name}:{n.lineno}'
            if isinstance(fn, ast.Name) and name == 'A' and len(n.args) == 1:
                vals = e.ev(n.args[0])
                if not vals:
                    found['dynamic'].append(f'{site} A({ast.unparse(n.args[0])})')
                for v in vals:
                    found['addr'].setdefault(v, []).append(site)
            elif isinstance(fn, ast.Name) and name == 'GPO' and len(n.args) == 1:
                vals = e.ev(n.args[0])
                if not vals:
                    found['dynamic'].append(f'{site} GPO({ast.unparse(n.args[0])})')
                for v in vals:
                    found['gp'].setdefault(v, []).append(site)
            elif isinstance(fn, ast.Name) and name == 'RANGE' and len(n.args) == 2:
                a, b = e.ev(n.args[0]), e.ev(n.args[1])
                if not a or not b:
                    found['dynamic'].append(f'{site} RANGE({ast.unparse(n.args[0])}, {ast.unparse(n.args[1])})')
                for x in a:
                    for y in b:
                        found['ranges'].setdefault((x, y), []).append(site)
            elif isinstance(fn, ast.Attribute) and name in MEM_METHODS | {'i', 'mem'}:
                args = n.args
                base_i = 2 if name in ('i', 'mem') else 1
                if len(args) <= base_i + 1 or not (isinstance(args[base_i], ast.Constant) and args[base_i].value == 28):
                    continue
                if name in ('i', 'mem'):
                    ops = e.ev(args[0])
                    if not ops or not all(op in GP_OPS for op in ops):
                        continue
                vals = e.ev(args[base_i + 1])
                if not vals:
                    found['dynamic'].append(f'{site} gp offset {ast.unparse(args[base_i + 1])}')
                for v in vals:
                    found['gp'].setdefault(v - 0x10000 if 0x8000 <= v <= 0xFFFF else v, []).append(site)
    return found


GP_OPS = {0x09, 0x19, 0x1A, 0x1B, 0x1E, 0x1F, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x29, 0x2A,
          0x2B, 0x2C, 0x2D, 0x2E, 0x2F, 0x31, 0x33, 0x36, 0x37, 0x39, 0x3E, 0x3F}


# ------------------------------------------------------------------------------------------ table

def data_addresses(found):
    """Add the native addresses of DATA_ADDRESSES rows to found['addr'] (the module translates each through A())."""
    for path, (rows, field, reader) in DATA_ADDRESSES.items():
        doc = json.loads(Path(path).read_text(encoding='utf-8'))
        for n, row in enumerate(doc[rows]):
            found['addr'].setdefault(int(row[field], 16), []).append(f'{Path(path).name}[{n}] ({reader})')


def reviewed(path=None):
    path = path or REVIEWED
    doc = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    over = {int(k, 16): int(v, 16) for k, v in doc.get('overrides', {}).items()}
    ranges = {}
    for k, (p, n) in doc.get('ranges', {}).items():
        a, b = k.split('+')
        ranges[(int(a, 16), int(b, 16))] = (int(p, 16), int(n, 16))
    return over, ranges, doc.get('notes', {})


def build(usa, pal, hexrays, tools, log, region=None):
    region = region or REGIONS['pal']
    target_gp, reviewed_file = region['gp'], region['reviewed']
    sys.path.insert(0, str(HERE))
    import pal_addrmap
    m = pal_addrmap.load(usa, pal, str(hexrays) if hexrays else None, verbose=False, **region['mapper'])
    if m.U.gp != USA_GP or m.P.gp != target_gp:
        raise SystemExit(f'unexpected gp values {m.U.gp:#x}/{m.P.gp:#x}')
    over, rev_ranges, notes = reviewed(reviewed_file)
    found = scan(tools)
    for address in json.loads((HERE/'online-native-references.json').read_text()):
        found['addr'].setdefault(int(address, 16), []).append('reviewed online native references')
    if region['data_addresses']:
        data_addresses(found)
    addr, evidence, failures = {}, {}, []

    def take(u, why):
        if u in over:
            evidence[u] = 'reviewed override' + (f': {notes.get(hx(u))}' if notes.get(hx(u)) else '')
            return over[u]
        if not NATIVE_LO <= u <= NATIVE_HI:
            failures.append(f'{hx(u)} is outside the native image ({why})')
            return None
        p, conf, region = m.map_addr(u)
        if p is None or conf not in GOOD:
            failures.append(f'{hx(u)} maps {conf} ({region}{", candidate " + hx(p) if p is not None else ""}) - {why}')
            return None
        fn = m.function_of(u) if region in ('elf-code', 'overlay-code') else None
        tag = f'{conf} {region}'
        if fn and fn.get('class') == 'changed':
            tag += ' in-changed-function %s' % hx(fn['start'])
        addr[u] = p
        evidence[u] = tag
        return p

    for u, sites in sorted(found['addr'].items()):
        take(u, ', '.join(sites[:3]) + (' ...' if len(sites) > 3 else ''))
    # gp window segments: bytes $gp reaches that map exact/high
    segments, cur = [], None
    for u in range(USA_GP - 0x8000, USA_GP + 0x8000):
        p, conf = m.map_data(u)
        d = (p - u) if (p is not None and conf in GOOD and -0x8000 <= p - target_gp < 0x8000) else None
        if d is not None and cur and cur[2] == d and cur[1] == u:
            cur[1] = u + 1
        elif d is not None:
            cur = [u, u + 1, d]; segments.append(cur)
        else:
            cur = None
    gp_ok = lambda t: t in over or t in addr or any(lo <= t < hi for lo, hi, _ in segments)
    for off, sites in sorted(found['gp'].items()):
        t = USA_GP + off
        if not gp_ok(t):
            p, conf = m.map_data(t)
            failures.append(f'gp offset {off} (USA {hx(t)}) maps {conf} - {", ".join(sites[:3])}')
    ranges = {}
    for (u, n), sites in sorted(found['ranges'].items()):
        if (u, n) in rev_ranges:
            ranges[(u, n)] = rev_ranges[(u, n)]; continue
        p0 = take(u, f'RANGE start, {sites[0]}')
        if n > 4:
            p1 = take(u + n - 4, f'RANGE end, {sites[0]}')
            if p0 is not None and p1 is not None and p1 != p0 + n - 4:
                r = m.map_range(u, n)
                failures.append(f'RANGE {hx(u)}+{hx(n)} changes layout in the {region["name"]} executable ({r}); '
                                f'needs a reviewed range - {sites[0]}')
    for (u, n), (p, pn) in rev_ranges.items():
        ranges[(u, n)] = (p, pn)
    source = dict(usa_elf_sha256=m.U.sha256, usa_dbzp_sha256=m.U.overlay_sha256, mapper_version=pal_addrmap.VERSION,
                  hexrays_sha256=pal_addrmap.hexrays_sha256(hexrays) if hexrays else None,
                  reviewed_sha256=hashlib.sha256(reviewed_file.read_bytes()).hexdigest() if reviewed_file.is_file() else None)
    if region['mapper']:
        source['mapper_options'] = dict(sorted(region['mapper'].items()))
    doc = dict(
        schema=1, adapter=region['adapter'],
        elf_sha256=m.P.sha256, dbzp_sha256=m.P.overlay_sha256,
        source=source,
        gp={'usa': hx(USA_GP), region['gp_key']: hx(target_gp),
            'segments': [[hx(lo), hx(hi), d] for lo, hi, d in segments]},
        addr={hx(u): hx(p) for u, p in sorted(addr.items())},
        ranges={f'{hx(u)}+{hx(n)}': [hx(p), hx(pn)] for (u, n), (p, pn) in sorted(ranges.items())},
        overrides={hx(u): hx(p) for u, p in sorted(over.items())},
        evidence={hx(u): evidence[u] for u in sorted(evidence)},
    )
    log(f'{len(found["addr"])} A() addresses, {len(found["gp"])} gp offsets, {len(found["ranges"])} ranges, '
        f'{len(over)} reviewed overrides; {len(segments)} gp segments; {len(found["dynamic"])} dynamic arguments')
    return doc, failures, found


def render(doc):
    return json.dumps(doc, indent=1, sort_keys=True) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--region', choices=sorted(REGIONS), default='pal', help='target disc (default pal)')
    ap.add_argument('--pal-elf', '--target-elf'); ap.add_argument('--pal-dbzp', '--target-dbzp')
    ap.add_argument('--iso', help='the target disc ISO (read-only)')
    ap.add_argument('--usa-elf'); ap.add_argument('--usa-dbzp'); ap.add_argument('--usa-iso')
    ap.add_argument('--hexrays'); ap.add_argument('--tools', default=str(TOOLS)); ap.add_argument('--out')
    ap.add_argument('--check', action='store_true'); ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--list-dynamic', action='store_true')
    args = ap.parse_args(argv)
    log = (lambda *a: None) if args.quiet else print
    tools = Path(args.tools)
    region = REGIONS[args.region]
    out = Path(args.out) if args.out else tools / region['table']
    usa, pal, hexrays = inputs(args, region)
    doc, failures, found = build(usa, pal, hexrays, tools, log, region)
    if args.list_dynamic:
        for d in found['dynamic']:
            log('dynamic', d)
    if failures:
        print(f'{len(failures)} native references have no exact/high mapping or reviewed value:', file=sys.stderr)
        for f in failures:
            print('  ' + f, file=sys.stderr)
        return 2
    text = render(doc)
    if args.check:
        old = out.read_text(encoding='utf-8') if out.is_file() else ''
        if old != text:
            print(f'{out} is stale; run build_pal_map.py --region {args.region}', file=sys.stderr)
            return 1
        log(f'{out} is current')
        return 0
    out.write_text(text, encoding='utf-8', newline='\n')
    log(f'wrote {out} ({len(doc["addr"])} addresses, {len(doc["gp"]["segments"])} gp segments)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
