"""Disc-owned online equipment. The wire carries IDs, never client-supplied stats.

The native selector and battle rows store eight unsigned shorts: zero means
empty, otherwise the value is the equipment table index plus one. The game
builds the stats, effects, AI and damaged-costume request from those rows.
"""
import hashlib
import struct

SLOTS, POINTS, RECORDS = 8, 7, 350


def inventory(params, names, package):
    rows = package(params)[1]
    labels = package(names)
    if len(rows) != 14016 or len(labels) != RECORDS + 1:
        raise ValueError('Unreviewed native Potara table layout')
    items = []
    for ident in range(RECORDS):
        raw = rows[ident * 40:(ident + 1) * 40]
        text = labels[ident]
        if text[:2] != b'\xff\xfe':
            raise ValueError('Invalid native Potara name')
        name = text[2:].decode('utf-16-le').split('\0', 1)[0].strip()
        if not name or name == '0' or raw[0] not in (0, 1, 2, 3):
            continue
        cost = raw[3]
        if not 0 <= cost <= POINTS or (cost == 0 and raw[0] != 2):
            continue
        items.append(dict(id=ident, name=name, kind=raw[0], group=raw[1], cost=cost,
                          stats=list(struct.unpack_from('<4h', raw, 12)),
                          effects=raw[24:40].hex()))
    return dict(sha256=hashlib.sha256(params + names).hexdigest(), slots=SLOTS,
                points=POINTS, items=items)


def shape_problem(items):
    if not isinstance(items, list) or len(items) > SLOTS:
        return 'Potara equipment must be a list of at most eight item IDs'
    if any(type(i) is not int or not 0 <= i < RECORDS for i in items):
        return 'Invalid Potara item ID'
    if len(set(items)) != len(items):
        return 'A Potara cannot be equipped twice'
    return None


def problems(items, catalog):
    found = shape_problem(items)
    if found:
        return [found]
    inventory = getattr(catalog, 'potaras', {})
    unknown = [i for i in items if i not in inventory]
    if unknown:
        return [f'Potara {unknown[0]} is not available on this disc']
    rows = [inventory[i] for i in items]
    out = []
    if sum(r['cost'] for r in rows) > POINTS:
        out.append('Potara equipment exceeds seven points')
    groups = [(r['kind'], r['group']) for r in rows]
    if len(set(groups)) != len(groups):
        out.append('Choose only one Potara from each equipment category')
    return out


def native(items):
    found = shape_problem(items)
    if found:
        raise ValueError(found)
    values = sorted(i + 1 for i in items)
    return struct.pack('<8H', *(values + [0] * (SLOTS - len(values))))


def selected(raw):
    """Canonical IDs, with invalid gaps/order still caught by exact native readback."""
    return [i - 1 for i in struct.unpack('<8H', raw) if i]
