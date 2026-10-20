"""Fighter Gauntlet data: the per-game gauntlet file, its validator and the wave plan.

The file is `<game>-multifighter/gauntlets/gauntlets.json` (schema 1, the format of the gauntlet editor):

    {schema: 1, rules: {...}, games: {bt3: {roster: [{id, name, form, base, costumes, portrait, tags}],
                                           potara: [{id, name, effect, slots, kind, stats}]}},
     gauntlets: [{id, title, game, category, description, difficulty?, notes?,
                  waves: [{label, fighters: [{id, costume, potara: [item ids], buffed}],
                           cpu?, cpu_override?, difficulty?, buff_phase?, notes?}]}]}

Only the gauntlets of the running game are offered. A broken gauntlet is listed with its reason and cannot start;
it never hides the others. Without a file (or with no usable gauntlet) the built-in samples are used.

Planning (plan()): CPU level per wave = the wave's cpu_override / difficulty, else Easy (1) on the first wave rising
to Very Hard (4) on the last (never Very Easy, 0); from the halfway wave every enemy without a loadout gets the
editor's buff tiers (solo enemies the strongest), and Potara items become damage/defense/health multipliers for
fighters that enter mid-match (wave 1 also carries the real items through the Team Select record).
"""
import copy
import json
import math
from pathlib import Path

SCHEMA = 1
ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'gauntlets'
PATH = FOLDER / 'gauntlets.json'
MAX_WAVES = 100
MAX_WAVE_FIGHTERS = 5
MAX_ITEMS = 8               # native Team Select record: eight u16 item slots (+0x20)
POTARA_SLOTS = 7
BAR_HP = 10000              # one native health bar (story_missions: "HP (10,000 per bar)")
LEVELS = ('Very Easy', 'Easy', 'Normal', 'Hard', 'Very Hard')
EASY, HARDEST = 1, 4
REFILL = (('off', 'None (no health back)', 0), ('quarter', '1/4 bar', BAR_HP // 4), ('half', '1/2 bar', BAR_HP // 2),
          ('bar', '1 bar', BAR_HP), ('full', 'Full', None))
CATEGORY_ORDER = ('test', 'saga', 'era', 'movies', 'race', 'team', 'faction', 'alignment', 'theme', 'roster')
CATEGORY_TITLES = dict(test='Test', saga='Sagas', era='Eras', movies='Movies', race='Races', team='Teams',
                       faction='Factions', alignment='Heroes and villains', theme='Themes', roster='Rosters')


class GauntletError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise GauntletError(message)


def family():
    from native_map import SERIAL
    return 'bt4' if SERIAL == 'SLUS-21978' else 'bt3'


# ---------------------------------------------------------------- roster
def _names_bt3():
    data = json.loads((Path(__file__).resolve().parent / 'bt3_english_names.json').read_text(encoding='utf-8'))
    out = {}
    for row in data['characters']:
        name = row['base_name'] + (f" ({row['form']})" if row.get('form') else '')
        out[row['character_id']] = name
    return out


def _names_bt4():
    # The chosen disc's names (game_profile through character_names), like every other player module.
    import character_names
    return {k: row['name'] for k, row in character_names.character_table().items()
            if k not in NOT_FIGHTERS['bt4'] and isinstance(row.get('name'), str) and not row['name'].startswith('Fighter ')}


# BT4 select-screen placeholders (Random, ???, password, not selectable) are never fighters.
NOT_FIGHTERS = dict(bt3=frozenset(), bt4=frozenset({161, 162, 163, 164}))


def default_roster(game):
    names = _names_bt4() if game == 'bt4' else _names_bt3()
    return [dict(id=k, name=v, costumes=4) for k, v in sorted(names.items())]


# ---------------------------------------------------------------- built-in samples
def _f(character, costume=0, potara=(), buffed=False):
    return dict(id=character, costume=costume, potara=list(potara), buffed=buffed)


def _w(label, *fighters, **extra):
    return dict(label=label, fighters=list(fighters), **extra)


def builtin(game):
    """The samples used until the editor's file is installed (and the short test gauntlets)."""
    if game == 'bt4':
        gauntlets = [
            dict(id='quick_test_bt4', title='Quick Test', game='bt4', category='test',
                 description='Three short waves to try the mode: Cui, then Dodoria and Zarbon, then Frieza.',
                 description_es='Tres oleadas cortas para probar el modo: Cui, luego Dodoria y Zarbon, y al final Frieza.',
                 waves=[_w('Cui', _f(79)), _w("Frieza's henchmen", _f(84), _f(82)), _w('Frieza', _f(91))]),
            dict(id='tournament_of_power_sample_bt4', title='Tournament of Power (sample)', game='bt4',
                 category='saga', description='Universe 6 and Universe 11 warriors, ending with Jiren.',
                 description_es='Guerreros de los universos 6 y 11, hasta Jiren.',
                 waves=[_w('Cabba', _f(57)), _w('The Saiyan sisters', _f(118), _f(198)), _w('Hit', _f(78)),
                        _w('Top', _f(81)), _w('Dyspo', _f(229)), _w('Jiren', _f(151))])]
    else:
        gauntlets = [
            dict(id='quick_test_bt3', title='Quick Test', game='bt3', category='test',
                 description='Three short waves to try the mode: Cui, then Dodoria and Zarbon, then Frieza.',
                 description_es='Tres oleadas cortas para probar el modo: Cui, luego Dodoria y Zarbon, y al final Frieza.',
                 waves=[_w('Cui', _f(85)), _w("Frieza's henchmen", _f(84), _f(82)), _w('Frieza', _f(91))]),
            dict(id='namek_saga_sample_bt3', title='Namek Saga', game='bt3', category='saga',
                 description='Cui to Super Saiyan Goku on Namek.',
                 description_es='De Cui a Goku Super Saiyan en Namek.',
                 waves=[_w('Cui', _f(85)), _w("Frieza's henchmen", _f(84), _f(82)),
                        _w('Dragon Ball hunters', _f(13), _f(25)), _w('Vegeta', _f(29, 2, buffed=True)),
                        _w('The Ginyu Force', _f(86), _f(87), _f(88), _f(89), _f(90)),
                        _w('Frieza - 1st Form', _f(91)),
                        _w('Piccolo arrives', _f(22, 1, buffed=True), _f(13, 2, buffed=True), _f(25, 2, buffed=True)),
                        _w('Frieza - 2nd Form', _f(92)), _w('Frieza - 3rd Form', _f(93)),
                        _w('Frieza - Final Form', _f(94)), _w('Goku arrives', _f(1)),
                        _w('Full Power Frieza', _f(95)), _w('FINAL: Super Saiyan Goku', _f(2, 2))])]
    return dict(schema=SCHEMA, games={game: dict(roster=default_roster(game), potara=builtin_potara())},
                gauntlets=gauntlets)


def builtin_potara():
    """The stat items every disc has (ids as in the editor's inventory)."""
    out = []
    for base, stat in ((0, 'Attack'), (3, 'Defense'), (6, 'Ki Power'), (9, 'Super')):
        for level in range(3):
            stats = [0, 0, 0, 0]
            stats[base // 3] = 5 * (level + 1)
            out.append(dict(id=base + level, name=f'{stat} Up {level + 1}', effect=f'Plus: [{stat}] +{level + 1}',
                            slots=level + 1, kind='stat', stats=stats))
    out.append(dict(id=322, name='Strength Enhancement', effect='Plus: Maximum Health increases by 30,000.',
                    slots=1, kind='hidden', stats=[0, 0, 0, 0]))
    return out


# ---------------------------------------------------------------- validation
def _int(value, lo, hi, what):
    require(type(value) is int and lo <= value <= hi, f'{what} must be a whole number {lo}..{hi}')
    return value


def validate_gauntlet(g, game, roster, potara):
    """A normalised copy of one gauntlet, or GauntletError naming the first problem."""
    require(isinstance(g, dict), 'A gauntlet must be an object')
    gid = g.get('id')
    require(isinstance(gid, str) and 0 < len(gid) <= 80, 'Every gauntlet needs an id')
    require(g.get('game', game) == game, f'{gid}: made for {str(g.get("game")).upper()}')
    title = g.get('title') or gid
    require(isinstance(title, str) and len(title) <= 60, f'{gid}: title must be text of at most 60 characters')
    waves = g.get('waves')
    require(isinstance(waves, list) and 1 <= len(waves) <= MAX_WAVES, f'{gid}: needs 1..{MAX_WAVES} waves')
    out = dict(id=gid, title=title, game=game, category=str(g.get('category') or 'other'),
               description=str(g.get('description') or ''), description_es=str(g.get('description_es') or ''),
               notes=str(g.get('notes') or ''),
               difficulty=copy.deepcopy(g.get('difficulty')) if isinstance(g.get('difficulty'), dict) else None,
               waves=[])
    for i, w in enumerate(waves, 1):
        where = f'{gid} wave {i}'
        require(isinstance(w, dict), f'{where}: must be an object')
        fighters = w.get('fighters')
        require(isinstance(fighters, list) and 1 <= len(fighters) <= MAX_WAVE_FIGHTERS,
                f'{where}: needs 1..{MAX_WAVE_FIGHTERS} fighters')
        wave = dict(label=str(w.get('label') or '')[:60], label_es=str(w.get('label_es') or '')[:60], fighters=[],
                    notes=str(w.get('notes') or ''))
        for key in ('cpu_override', 'difficulty'):
            if w.get(key) is not None:
                wave['difficulty'] = _int(w[key], 0, 4, f'{where}: CPU level')
                break
        if w.get('cpu') is not None:
            wave['cpu'] = _int(w['cpu'], 0, 4, f'{where}: cpu')
        if w.get('buff_phase') is not None:
            require(type(w['buff_phase']) is bool, f'{where}: buff_phase must be true or false')
            wave['buff_phase'] = w['buff_phase']
        for k, f in enumerate(fighters, 1):
            at = f'{where} fighter {k}'
            require(isinstance(f, dict), f'{at}: must be an object')
            character = f.get('id', f.get('character'))
            require(type(character) is int and character in roster, f'{at}: unknown fighter {character!r}')
            costumes = roster[character].get('costumes', 4) or 4
            costume = f.get('costume', 0)
            require(type(costume) is int and 0 <= costume < max(1, min(int(costumes), 8)),
                    f'{at}: {roster[character]["name"]} has no costume {costume}')
            items = f.get('potara', [])
            require(isinstance(items, list) and len(items) <= MAX_ITEMS, f'{at}: at most {MAX_ITEMS} Potara items')
            require(all(type(x) is int and x in potara for x in items), f'{at}: unknown Potara item in {items}')
            buffed = f.get('buffed', False)
            require(type(buffed) is bool, f'{at}: buffed must be true or false')
            wave['fighters'].append(dict(character=character, costume=costume, potara=list(items), buffed=buffed,
                                         name=roster[character]['name']))
        out['waves'].append(wave)
    return out


def validate(document, game=None):
    """(usable gauntlets, problems [(id, reason)], roster, potara) of `document` for `game`."""
    game = game or family()
    require(isinstance(document, dict), 'The gauntlet file must be a JSON object')
    require(document.get('schema') == SCHEMA, f'Unsupported gauntlet file schema {document.get("schema")!r}')
    games = document.get('games') or {}
    require(isinstance(games, dict), 'games must be an object')
    data = games.get(game) or {}
    roster_rows = data.get('roster') or default_roster(game)
    roster = {}
    for row in roster_rows:
        if isinstance(row, dict) and type(row.get('id')) is int and row['id'] not in NOT_FIGHTERS[game]:
            roster[row['id']] = dict(row, name=str(row.get('name') or f"Fighter {row['id']}"))
    potara = {row['id']: row for row in (data.get('potara') or builtin_potara())
              if isinstance(row, dict) and type(row.get('id')) is int}
    usable, problems, seen = [], [], set()
    gauntlets = document.get('gauntlets')
    require(isinstance(gauntlets, list), 'gauntlets must be a list')
    for g in gauntlets:
        if isinstance(g, dict) and g.get('game', game) != game:
            continue
        try:
            v = validate_gauntlet(g, game, roster, potara)
            require(v['id'] not in seen, f"{v['id']}: duplicate id")
            seen.add(v['id'])
            usable.append(v)
        except GauntletError as e:
            problems.append((g.get('id') if isinstance(g, dict) else None, str(e)))
    return usable, problems, roster, potara


def load(game=None, path=None):
    """dict(gauntlets, problems, roster, potara, source) for the running game; never raises for a bad file."""
    game = game or family()
    path = Path(path) if path else PATH
    problems = []
    try:
        document = json.loads(path.read_text(encoding='utf-8-sig'))
        usable, problems, roster, potara = validate(document, game)
        source = str(path)
    except FileNotFoundError:
        usable, source = [], None
    except (OSError, ValueError) as e:
        usable, source = [], None
        problems = [(None, f'{path.name}: {e}')]
    if not usable:
        usable, extra, roster, potara = validate(builtin(game), game)
        problems += extra
        source = 'built-in'
    elif not any(g['category'] == 'test' for g in usable):
        # The short test gauntlet always exists.
        samples, _, _, _ = validate(builtin(game), game)
        usable = [g for g in samples if g['category'] == 'test'] + usable
    return dict(gauntlets=usable, problems=problems, roster=roster, potara=potara, source=source, game=game)


def grouped(gauntlets):
    """[(category title, [gauntlet, ...])] in menu order."""
    order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    cats = sorted({g['category'] for g in gauntlets}, key=lambda c: (order.get(c, 99), c))
    return [(CATEGORY_TITLES.get(c, c.title()), [g for g in gauntlets if g['category'] == c]) for c in cats]


# ---------------------------------------------------------------- the plan
def difficulty(index, count, wave=None, ramp=None):
    """CPU level 0..4 of wave `index` (0-based) of `count`: an explicit wave value wins; else Easy..Very Hard."""
    if wave and wave.get('difficulty') is not None:
        return wave['difficulty']
    if wave and wave.get('cpu') is not None:
        # The editor's own curve value, as the user saw it there (never below Easy).
        return max(EASY, wave['cpu'])
    start, end = EASY, HARDEST
    if ramp:
        start = max(EASY, min(HARDEST, int(ramp.get('start', EASY))))
        end = max(start, min(HARDEST, int(ramp.get('end', HARDEST))))
    if count <= 1:
        return end
    # The editor's curve: 1 + round(3 * p) with Python's round (halves to even).
    return start + int(round((end - start) * index / (count - 1)))


def halfway(count, ramp=None):
    """Index of the first buffed wave (0-based): p = index / (count - 1) >= buff_from (default 0.5)."""
    frm = float((ramp or {}).get('buff_from', 0.5))
    if count <= 1:
        return 0
    return next(i for i in range(count) if i / (count - 1) >= frm - 1e-9)


def _item_named(potara, *names):
    for row in potara.values():
        if row.get('name') in names:
            return row['id']
    return None


def tier_items(potara, size, index, count):
    """The editor's buff tiers (rules.tiers) for an enemy without its own loadout in a buffed wave."""
    ids = lambda *names: [x for x in (_item_named(potara, n) for n in names) if x is not None]
    health = _item_named(potara, 'Strength Enhancement', 'Whis Training')
    if index == count - 1:
        return ids('Attack Up 3', 'Defense Up 2') + ([health] if health is not None else [])
    if size == 1:
        if index >= count - max(1, count // 4) and health is not None:
            return ids('Attack Up 2', 'Defense Up 2') + [health]
        return ids('Attack Up 3', 'Defense Up 2', 'Ki Power Up 1', 'Super Up 1')
    if size == 2:
        return ids('Attack Up 2', 'Defense Up 2', 'Super Up 1')
    return ids('Attack Up 1', 'Defense Up 1', 'Ki Power Up 1')


def item_effects(items, potara):
    """(damage x, defense x, extra max HP) of a Potara loadout: stats [attack, defense, ki, super] are native
    steps of 5 (Attack Up 1 = +5 %), Super adds half its value to damage, health items parse their text."""
    attack = defense = super_ = 0
    health = 0
    for x in items:
        row = potara.get(x) or {}
        s = list(row.get('stats') or [0, 0, 0, 0]) + [0, 0, 0, 0]
        attack += s[0]; defense += s[1]; super_ += s[3]
        text = str(row.get('effect') or '')
        for sign, words in ((1, 'increases by'), (-1, 'decreases by'), (-1, 'reduced by')):
            if words in text:
                tail = text.split(words, 1)[1].strip().split()[0].rstrip('.').replace(',', '')
                if tail.isdigit():
                    health += sign * int(tail)
    return 1 + attack / 100 + super_ / 200, 1 + defense / 100, health


def plan(gauntlet, potara=None, players=1):
    """The run's wave list: per wave its CPU level, banner and each enemy's character, costume, items and the
    multipliers/HP it enters with. Deterministic (the guest program and the tests use the same plan)."""
    potara = potara or {row['id']: row for row in builtin_potara()}
    waves = gauntlet['waves']
    count = len(waves)
    ramp = gauntlet.get('difficulty')
    first_buffed = halfway(count, ramp)
    out = []
    for i, w in enumerate(waves):
        level = difficulty(i, count, w, ramp)
        buffed_wave = w['buff_phase'] if w.get('buff_phase') is not None else i >= first_buffed
        size = len(w['fighters'])
        enemies = []
        for f in w['fighters']:
            items = list(f['potara'])
            auto = False
            if buffed_wave and not items and not f['buffed']:
                items = tier_items(potara, size, i, count)
                auto = True
            damage, defense, health = item_effects(items, potara)
            if f['buffed']:
                damage *= 1.10; defense *= 1.10
            if buffed_wave and size == 1:
                # A lone enemy past halfway gets the solo boost on top of its items.
                damage *= 1.15; defense *= 1.15; health += BAR_HP
            enemies.append(dict(character=f['character'], costume=f['costume'], name=f['name'], items=items[:MAX_ITEMS],
                                auto_items=auto, damage=round(damage, 3), defense=round(defense, 3),
                                extra_hp=max(-30000, min(health, 200000)), buffed=f['buffed'] or buffed_wave))
        label = w.get('label') or ', '.join(e['name'] for e in enemies)
        out.append(dict(index=i, number=i + 1, count=count, label=label, label_es=w.get('label_es') or '',
                        difficulty=level, buffed=buffed_wave,
                        enemies=enemies, banner=f'WAVE {i + 1} / {count}', title=label))
    return out


def refill_amount(key, max_hp):
    """HP a living player fighter gains at the start of a countdown for setting `key`."""
    for k, _, amount in REFILL:
        if k == key:
            return max_hp if amount is None else amount
    raise GauntletError(f'Unknown HP refill {key!r}')


def split_file(document, game):
    """The per-game file the tree carries (one game's roster/potara and gauntlets)."""
    out = dict(schema=SCHEMA)
    if 'rules' in document:
        out['rules'] = document['rules']
    out['games'] = {game: document['games'][game]}
    out['gauntlets'] = [g for g in document['gauntlets'] if g.get('game') == game]
    return out
