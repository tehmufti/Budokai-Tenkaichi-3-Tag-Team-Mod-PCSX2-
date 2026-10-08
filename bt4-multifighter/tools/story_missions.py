"""Portable, versioned battle documents and deterministic, frame-driven events.

Documents contain data only: no emulator state, native addresses or executable
scripts. Runtime limits belong to adapters, not to the document format.
"""
from __future__ import annotations

import copy
import contextlib
import hashlib
import json
import math
import os
import re
import time
from pathlib import Path

import atomic_files

SCHEMA = 'tag-team-mission'
VERSION = 1
MAX_BYTES = 48 * 1024
MAX_EVENTS = 64
LIBRARY = Path(__file__).resolve().parents[1] / 'missions'
ARMED = LIBRARY / 'next-battle.json'
QUICK = LIBRARY / 'quick-launch.json'  # Workbench "Test this mission" request (story_quicklaunch)
NAME = re.compile(r'^[a-zA-Z][a-zA-Z0-9_-]{0,47}$')


def private(path):
    """Launch queues live beside the library but are never browsable missions."""
    return Path(path).name in (ARMED.name, QUICK.name)


class InvalidMission(ValueError):
    pass


def require(test, message):
    if not test:
        raise InvalidMission(message)


def integer(value, low, high, label):
    require(type(value) is int and low <= value <= high, f'{label}: expected {low}..{high}')
    return value


def number(value, low, high, label):
    require(type(value) in (int, float) and math.isfinite(value) and low <= value <= high,
            f'{label}: expected a finite number in {low}..{high}')
    return value


def fields(obj, required, optional=(), label='Object'):
    require(type(obj) is dict, f'{label} must be an object')
    require(set(required) <= obj.keys(), f'{label}: missing {set(required)-obj.keys()}')
    require(not obj.keys()-set(required)-set(optional),
            f'{label}: unknown fields {obj.keys()-set(required)-set(optional)}')


def identifier(value, label):
    require(type(value) is str and NAME.fullmatch(value), f'{label}: use a short letter/number identifier')


def validate_profile(profile):
    fields(profile, ('name', 'transform_chance'), ('notes', 'difficulty'), 'CPU profile')
    require(type(profile['name']) is str and 0 < len(profile['name']) <= 80, 'CPU profile needs a name')
    integer(profile['transform_chance'], 0, 100, 'Transformation chance')
    if 'difficulty' in profile: integer(profile['difficulty'], 0, 4, 'CPU difficulty')
    return copy.deepcopy(profile)


def validate_voice(voice, action=False):
    fields(voice, ('type','fighter','character','line') if action else ('character','line'), ('volume',), 'Voice line')
    integer(voice['character'], 0, 65535, 'Voice character')
    integer(voice['line'], 0, 99, 'Native voice line')
    integer(voice.setdefault('volume',100), 0, 100, 'Voice volume')


def validate_stats(stats):
    fields(stats, (), ('max_hp','health_percent','damage','defense','invulnerable','cannot_be_defeated','ki_percent','blast_stocks','difficulty'), 'Fighter stats')
    require(bool(stats), 'Choose at least one stat to change')
    for key,low,high in (('max_hp',1,1000000),('blast_stocks',0,99),('difficulty',0,4)):
        if key in stats:integer(stats[key],low,high,key)
    for key,low,high in (('health_percent',1,100),('damage',0,20),('defense',.05,20),('ki_percent',0,100)):
        if key in stats:number(stats[key],low,high,key)
    for key in ('invulnerable','cannot_be_defeated'):
        if key in stats:require(type(stats[key]) is bool,key+' must be boolean')


def validate(document):
    d = copy.deepcopy(document)
    fields(d, ('schema', 'version', 'id', 'title', 'fighters', 'events'),
           ('description', 'stage', 'cpu_profiles', 'source', 'player_selection', 'game_family', 'defeat_grace_seconds', 'music', 'finish_rules', 'win_when', 'fail_when', 'player_team', 'menus'), 'Mission')
    require(d['schema'] == SCHEMA and d['version'] == VERSION, 'Unsupported mission format/version')
    identifier(d['id'], 'Mission ID')
    if 'game_family' in d:require(d['game_family'] in ('bt3','bt4'), 'Unknown mission game family')
    require(type(d['title']) is str and 0 < len(d['title']) <= 120, 'Mission needs a title (up to 120 characters)')
    number(d.setdefault('defeat_grace_seconds',30),1,300,'Pending reinforcement grace period')
    if 'stage' in d and d['stage'] is not None:
        fields(d['stage'], ('id',), ('name', 'adapter'), 'Stage')
        integer(d['stage']['id'], 0, 65535, 'Stage ID')
    if 'music' in d and d['music'] is not None: integer(d['music'], 0, 65535, 'Music ID')
    if 'player_team' in d: integer(d['player_team'], 1, 2, 'Player team')
    if 'menus' in d:
        fields(d['menus'], (), ('retry', 'character_select'), 'Scenario menus')
        for value in d['menus'].values(): require(type(value) is bool, 'Menu choices must be boolean')
    require(type(d['fighters']) is list and 2 <= len(d['fighters']) <= 64, 'Mission needs 2..64 fighters')
    require(type(d['events']) is list and len(d['events']) <= MAX_EVENTS, f'At most {MAX_EVENTS} events')
    profiles = d.setdefault('cpu_profiles', {})
    require(type(profiles) is dict, 'CPU profiles must be named objects')
    for key, profile in profiles.items():
        identifier(key, 'Profile ID'); validate_profile(profile)
    fighters = {}
    seats = set()
    for f in d['fighters']:
        fields(f, ('id', 'team', 'slot', 'character'),
               ('costume', 'reserve', 'cpu_profile', 'copy_cpu_from', 'name', 'source', 'hp', 'difficulty', 'transformations', 'stats'), 'Fighter')
        identifier(f['id'], 'Fighter ID')
        require(f['id'] not in fighters, 'Duplicate fighter ID')
        integer(f['team'], 1, 2, 'Team'); integer(f['slot'], 1, 32, 'Slot')
        integer(f['character'], 0, 65535, 'Character'); integer(f.setdefault('costume', 0), 0, 255, 'Costume')
        require(type(f.setdefault('reserve', False)) is bool, 'Reserve must be true or false')
        if 'hp' in f: integer(f['hp'], 1, 1000000, 'Starting and maximum HP')
        if 'difficulty' in f: integer(f['difficulty'], 0, 4, 'CPU difficulty')
        if 'stats' in f:validate_stats(f['stats'])
        if 'transformations' in f:
            t=f['transformations'];fields(t, (), ('enabled', 'allowed_forms', 'limit'), 'Transformation policy')
            if 'enabled' in t: require(type(t['enabled']) is bool, 'Transformations enabled must be boolean')
            if 'limit' in t: integer(t['limit'], 0, 1000, 'Transformation limit')
            if 'allowed_forms' in t:
                require(type(t['allowed_forms']) is list and len(t['allowed_forms'])<=256, 'Allowed forms must be a list of IDs')
                for form in t['allowed_forms']: integer(form, 0, 65535, 'Allowed form')
        seat = (f['team'], f['slot']); require(seat not in seats, 'Two fighters occupy the same roster slot')
        seats.add(seat); fighters[f['id']] = f
        if f.get('cpu_profile'):
            require(f['cpu_profile'] in profiles, 'Unknown CPU profile')
    for side in (1, 2):
        slots = sorted(f['slot'] for f in fighters.values() if f['team'] == side)
        require(slots and slots == list(range(1, len(slots)+1)), 'Each team needs consecutive slots starting at 1')
    for f in fighters.values():
        if 'copy_cpu_from' in f:
            require(f['copy_cpu_from'] in fighters and f['copy_cpu_from'] != f['id'], 'CPU copy source must be another mission fighter')
            seen={f['id']};source=f
            while source.get('copy_cpu_from'):
                key=source['copy_cpu_from'];require(key in fighters and key not in seen,'CPU copy dependency cycle or unknown source')
                seen.add(key);source=fighters[key]
    events = {}
    for event in d['events']:
        fields(event, ('id', 'when', 'actions'), ('timeout_seconds','on_failure'), 'Event')
        identifier(event['id'], 'Event ID'); require(event['id'] not in events, 'Duplicate event ID')
        events[event['id']] = event
    def condition(c, depth=0):
        require(depth <= 6, 'Conditions are nested too deeply')
        require(type(c) is dict and type(c.get('type')) is str, 'Condition needs a type')
        kind = c['type']
        if kind in ('all', 'any'):
            fields(c, ('type', 'conditions'), label='Condition')
            require(type(c['conditions']) is list and 1 <= len(c['conditions']) <= 16, 'Use 1..16 conditions')
            for child in c['conditions']: condition(child, depth+1)
        elif kind == 'time':
            fields(c, ('type', 'seconds'), label='Time condition'); number(c['seconds'], 0, 86400, 'Time')
        elif kind == 'event':
            fields(c, ('type', 'event'), ('delay_seconds',), 'Event condition'); require(c['event'] in events, 'Unknown event reference')
            if 'delay_seconds' in c:number(c['delay_seconds'],0,86400,'Delay after event completion')
        elif kind == 'event_failed':
            fields(c, ('type','event'), label='Failed event condition');require(c['event'] in events,'Unknown event reference')
        elif kind == 'not':
            fields(c, ('type','condition'), label='Inverted condition');condition(c['condition'],depth+1)
        elif kind == 'planet_destroyed':
            fields(c, ('type',), ('occurrence',), 'Planet destruction condition')
            integer(c.setdefault('occurrence', 1), 1, 1000, 'Destruction occurrence')
        elif kind in ('defeated', 'form', 'transformed', 'health_below','health_above','active','retired'):
            key = ('character',) if kind=='form' else ('percent',) if kind in ('health_below','health_above') else ()
            fields(c, ('type', 'fighter', *key), label='Fighter condition')
            require(c['fighter'] in fighters, 'Unknown condition fighter')
            if kind == 'form': integer(c['character'], 0, 65535, 'Form')
            if kind in ('health_below','health_above'): number(c['percent'], 0, 100, 'Health threshold')
        else: raise InvalidMission(f'Unknown condition: {kind}')
    for key in ('win_when', 'fail_when'):
        if d.get(key) is not None: condition(d[key])
    require(type(d.get('finish_rules', [])) is list and len(d.get('finish_rules', []))<=64, 'At most 64 finishing rules')
    victims=set()
    for rule in d.get('finish_rules', []):
        fields(rule, ('victim', 'attacker', 'attack', 'otherwise'), ('form',), 'Finishing rule')
        require(rule['victim'] in fighters and rule['attacker'] in fighters, 'Unknown finishing-rule fighter')
        require(rule['victim']!=rule['attacker'], 'Finisher cannot be the victim')
        require(rule['victim'] not in victims, 'Use one finishing rule per victim');victims.add(rule['victim'])
        require(rule['attack'] in ('any', 'ultimate', 'special'), 'Unknown finishing attack type')
        require(rule['otherwise'] in ('hold_at_1_hp', 'fail'), 'Choose hold_at_1_hp or fail for an invalid finisher')
        if 'form' in rule: integer(rule['form'], 0, 65535, 'Required finishing form')
    entrances = {}
    for event in events.values():
        condition(event['when'])
        number(event.setdefault('timeout_seconds', 30), 1, 300, 'Event timeout')
        require(event.get('on_failure','continue') in ('continue','fail_scenario'), 'Choose continue or fail_scenario on event failure')
        require(type(event['actions']) is list and 1 <= len(event['actions']) <= 32, 'Event needs 1..32 actions')
        for action in event['actions']:
            kind = action.get('type') if type(action) is dict else None
            if kind == 'message':
                fields(action, ('type', 'text'), ('seconds',), 'Message')
                require(type(action['text']) is str and 0 < len(action['text']) <= 120, 'Message needs 1..120 characters')
                number(action.setdefault('seconds', 4), .5, 30, 'Message duration')
                continue
            if kind=='wait':
                fields(action, ('type','seconds'), ('freeze',), 'Delay action');number(action['seconds'],.01,300,'Delay')
                require(type(action.get('freeze',False)) is bool,'Freeze during delay must be boolean')
                if action.get('freeze'):number(action['seconds'],.1,30,'Frozen pause')
                continue
            require(kind in ('enter', 'transform', 'recover', 'heal', 'taunt', 'cinematic', 'voice','set_stats','despawn','take_control','target','defeat'), f'Unknown action: {kind}')
            allowed = {'enter': ('health_percent', 'intro'), 'recover': ('health_percent',),
                       'heal': ('health_percent',), 'transform': ('character',), 'taunt': (), 'voice': ('character', 'line', 'volume'),
                       'cinematic': ('animation', 'seconds', 'speed', 'camera', 'voice'),
                       'set_stats': ('stats',), 'despawn': (), 'take_control': ('player',), 'target': ('target',), 'defeat': ()}[kind]
            fields(action, ('type', 'fighter'), allowed, 'Action')
            require(action['fighter'] in fighters, 'Unknown action fighter')
            if kind=='set_stats':validate_stats(action.get('stats'))
            if kind=='take_control':integer(action.get('player'),1,4,'Player number')
            if kind=='target':
                require(action.get('target') in fighters,'Choose a target fighter')
                require(fighters[action['fighter']]['team']!=fighters[action['target']]['team'],'Target must be an enemy')
            if kind in ('enter', 'recover', 'heal'):
                number(action.setdefault('health_percent', 100), 1, 100, 'Restored health')
            if kind == 'enter':
                target = fighters[action['fighter']]
                require(target['reserve'], 'An entrance must refer to a reserve')
                require(target['id'] not in entrances, 'A reserve can enter only once')
                entrances[target['id']] = event['id']
                require(type(action.setdefault('intro', True)) is bool, 'Intro must be boolean')
            if kind == 'transform': integer(action.get('character'), 0, 65535, 'Destination form')
            if kind == 'voice': validate_voice(action, action=True)
            if kind == 'cinematic':
                anim=action.get('animation')
                if anim is not None:
                    fields(anim, ('character', 'clip'), label='Cinematic animation')
                    integer(anim['character'], 0, 65535, 'Animation donor');integer(anim['clip'], 0, 413, 'Animation clip')
                number(action.setdefault('seconds',4), .1, 30, 'Cinematic duration')
                number(action.setdefault('speed',1), .1, 3, 'Animation speed')
                camera=action.setdefault('camera',dict(eye=[0,-16,55],target=[0,-9,0]))
                fields(camera, ('eye', 'target'), ('end_eye', 'end_target','easing'), 'Cinematic camera')
                require(camera.get('easing','smooth') in ('linear','smooth','ease_in','ease_out'),'Unknown camera easing')
                for key,vec in camera.items():
                    if key=='easing':continue
                    require(type(vec) is list and len(vec)==3, 'Camera vectors need X, Y, Z')
                    for value in vec:number(value,-10000,10000,'Camera offset')
                require(camera['eye']!=camera['target'], 'Camera eye and target must differ')
                # Reject a moving shot whose view direction crosses zero.
                start=[a-b for a,b in zip(camera['eye'],camera['target'])]
                end=[a-b for a,b in zip(camera.get('end_eye',camera['eye']),camera.get('end_target',camera['target']))]
                delta=[b-a for a,b in zip(start,end)];length=sum(x*x for x in delta)
                t=max(0,min(1,-sum(a*b for a,b in zip(start,delta))/length)) if length else 0
                require(sum((a+t*b)**2 for a,b in zip(start,delta))>=1, 'Camera passes through its look-at point')
                if 'voice' in action: validate_voice(action['voice'])
        wait_budget=sum(x['seconds'] for x in event['actions'] if x['type']=='wait' and not x.get('freeze'))
        require(wait_budget<event['timeout_seconds'], 'Event timeout must exceed its scripted waits')
    require(set(entrances) == {f['id'] for f in fighters.values() if f['reserve']},
            'Every reserve needs exactly one entrance event')
    def dependencies(c):
        if c['type']=='not':return dependencies(c['condition'])
        if c['type'] in ('all', 'any'):
            return set().union(*(dependencies(x) for x in c['conditions']))
        if c['type'] in ('event','event_failed'): return {c['event']}
        if c.get('fighter') in entrances: return {entrances[c['fighter']]}
        return set()
    # Only AND dependencies are mandatory. An OR time trigger can break a cycle.
    def mandatory(c):
        if c['type']=='not':return set()
        if c['type'] == 'any': return set.intersection(*(mandatory(x) for x in c['conditions']))
        if c['type'] == 'all': return set().union(*(mandatory(x) for x in c['conditions']))
        return dependencies(c)
    visiting, seen = set(), set()
    def visit(key):
        require(key not in visiting, 'Event dependency cycle: '+key)
        if key in seen: return
        visiting.add(key)
        for other in mandatory(events[key]['when']): visit(other)
        visiting.remove(key); seen.add(key)
    for key in events: visit(key)
    require(len(encoded(d)) <= MAX_BYTES, 'Mission is too large')
    return d


def encoded(document):
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(document):
    return hashlib.sha256(encoded(validate(document))).hexdigest()


def load(path):
    raw = atomic_files.read_bytes(path)
    require(len(raw) <= MAX_BYTES, 'Mission is too large')
    return validate(json.loads(raw.decode('utf-8-sig')))


def save(path, document):
    d = validate(document); atomic_files.write_json(path, d); return d


@contextlib.contextmanager
def queue_lock(path, timeout=2):
    """Serialize the Workbench and trainer's check/replace/delete transactions.

    OS locks release on process exit; no stale PID or lock-directory recovery.
    The one-byte lock file is separate from the atomically replaced document.
    """
    lock=Path(path).with_name('.'+Path(path).name+'.lock');lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('a+b') as handle:
        if handle.tell()==0:handle.write(b'\0');handle.flush()
        deadline=time.monotonic()+timeout
        while True:
            try:
                handle.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic()>=deadline:raise TimeoutError('The story mission queue is busy; try again')
                time.sleep(.02)
        try:yield
        finally:
            handle.seek(0)
            if os.name=='nt':msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(handle,fcntl.LOCK_UN)


def arm(document, path=ARMED):
    d = validate(document)
    # Embed a complete copy: editing or moving the source cannot change an armed battle.
    with queue_lock(path):atomic_files.write_json(path, {'sha256': digest(d), 'mission': d})


def armed(path=ARMED):
    try:data=atomic_files.read_json(path)
    except FileNotFoundError:return None
    d = validate(data['mission'])
    require(data['sha256'] == digest(d), 'Armed mission checksum mismatch')
    return d


def pending_for(mode):
    return mode == 'teams' and ARMED.is_file()


def consumed(document, path=ARMED):
    """Do not erase a different mission armed while preparation was running."""
    with queue_lock(path):
        current=armed(path)
        if current is not None and digest(current)==digest(document):
            atomic_files.unlink(path)


def disarm(path=ARMED):
    with queue_lock(path):atomic_files.unlink(path)


def matches(condition, snapshot, completed):
    kind = condition['type']
    if kind == 'time': return snapshot['seconds'] >= condition['seconds']
    if kind == 'event':
        return condition['event'] in completed and snapshot['seconds']-snapshot.get('event_times',{}).get(condition['event'],snapshot['seconds'])>=condition.get('delay_seconds',0)
    if kind=='event_failed':return condition['event'] in snapshot.get('failed_events',[])
    if kind=='not':return not matches(condition['condition'],snapshot,completed)
    if kind in ('all', 'any'):
        values = [matches(c, snapshot, completed) for c in condition['conditions']]
        return all(values) if kind == 'all' else any(values)
    if kind == 'planet_destroyed':
        return snapshot.get('planet_destructions', 0) >= condition.get('occurrence', 1)
    fighter = snapshot['fighters'].get(condition['fighter'])
    if kind=='retired':return bool(fighter and fighter.get('retired'))
    if not fighter or not fighter.get('entered', True): return False
    if fighter.get('retired'):return False
    if kind=='active':return fighter['hp']>0
    if kind == 'defeated': return fighter['hp'] <= 0
    if kind == 'transformed': return fighter.get('transformations',0)>0
    if kind == 'form': return fighter['character'] == condition['character']
    compare=fighter['hp']*100-fighter['hp_max']*condition['percent']
    return compare>0 if kind=='health_above' else compare<=0


def default_mission():
    from native_map import SERIAL
    return validate(dict(schema=SCHEMA, version=VERSION, id='custom-battle', title='Custom battle',
        game_family='bt4' if SERIAL=='SLUS-21978' else 'bt3',
        fighters=[dict(id='hero', team=1, slot=1, character=0),
                  dict(id='rival', team=2, slot=1, character=29)], events=[]))


def profile_id(fighter):
    name=fighter+'-cpu'
    return name if len(name)<=48 else fighter[:37]+'-'+hashlib.sha256(fighter.encode()).hexdigest()[:6]+'-cpu'


def copy_cpu_profile(document, source, destination):
    d = validate(document); fighters = {f['id']: f for f in d['fighters']}
    require(source in fighters and destination in fighters, 'Select two mission fighters')
    profile = fighters[source].get('cpu_profile')
    # Independent copy, so editing the destination does not change the source.
    name = profile_id(destination)
    d['cpu_profiles'][name] = copy.deepcopy(d['cpu_profiles'].get(profile,
        dict(name='Copied CPU settings', transform_chance=100)))
    fighters[destination]['cpu_profile'] = name
    fighters[destination]['copy_cpu_from'] = source
    fighters[destination].pop('difficulty',None)
    # Stat overrides are applied after native CPU profile copies. Do not let a
    # stale destination difficulty silently undo the requested copy.
    if 'stats' in fighters[destination]:
        fighters[destination]['stats'].pop('difficulty',None)
        if not fighters[destination]['stats']:fighters[destination].pop('stats')
    if 'difficulty' in fighters[source]:fighters[destination]['difficulty']=fighters[source]['difficulty']
    if 'difficulty' in fighters[source].get('stats',{}):
        fighters[destination]['difficulty']=fighters[source]['stats']['difficulty']
    return validate(d)
