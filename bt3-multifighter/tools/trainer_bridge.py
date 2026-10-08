"""Opt-in desktop telemetry and guarded edits on the runtime owner's PINE client.

No client is created here. GUI leases expire; commands expire and carry a match
epoch plus actor/body identity. Failed native transactions retain the hold and
propagate to the runtime's recovery path. Offline snapshots never enable edits.
"""
from native_map import A
import struct
import time
import uuid
from pathlib import Path

import atomic_files
import fresh_team_combat as core
import battle_mode_policy as modes
import native_preparation as prep
from character_names import character_name

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / 'analysis' / 'trainer-ui'
FIELDS = {'hp': (0, 4), 'ki': (12, 16), 'stocks': (20, 24)}


class Rejected(ValueError):
    pass


def word(data, offset=0):
    return struct.unpack_from('<I', data, offset)[0]


def pointer(address, size=4):
    return 0x100000 <= address <= 0x8000000-size and address % 4 == 0


def body_status(p, manager, count):
    import body_swap
    values = struct.unpack('<6I', p.read(body_swap.CONTROL, 24))
    if values[:3] == (body_swap.MAGIC, manager, count) and values[5] == 1:
        return values[4]
    return 0


def defusion_pending(p, manager, count):
    import fusion_duration as duration
    identity=struct.unpack('<4I',p.read(duration.CONTROL,16))
    # The service claim (CONTROL+12) is a watcher token (fusion_duration_worker.OWNER); the
    # guest only tests it for zero, and so does this check.
    return (identity[:3]==(duration.MAGIC,manager,count) and identity[3]!=0 and
            any(p.read_u32(duration.RECORDS+i*duration.STRIDE)==3 for i in range(count)))


def snapshot(p):
    state = dict(active=False, fighters=[], reason='Waiting for a prepared match')
    mode = struct.unpack('<4I', p.read(core.MODE, 16))
    manager = p.read_u32(core.ACTORS)
    if not mode[0] or mode[1] not in modes.ACTOR_COUNTS or mode[2] != manager or mode[3] != mode[1]:
        return state
    if not pointer(manager, 632) or p.read_u32(manager) != 2:
        return state
    count = mode[1]
    policy = p.read(modes.CONTROL, 24)
    present = (1 << count)-1
    kind = 'teams'
    if word(policy) == modes.MAGIC and word(policy, 4) == manager and word(policy, 8) == count:
        present = word(policy, 20)
        kind = {0: 'teams', 1: 'ffa', 2: 'coop'}.get(word(policy, 12), 'unknown')
    battle = p.read_u32(A(0x2FEB38))
    phase = p.read_u32(battle) if pointer(battle) else -1
    flags = p.read_u32(A(0x3337B8))
    state.update(active=True, manager=manager, count=count, mode=kind, phase=phase,
                 frame=p.read_u32(prep.CONTROL+40), reason='',
                 editable=phase == 3 and not flags & 0x3900 and not p.read_u32(core.PAIR+4)
                          and not p.read_u32(manager+628) and not p.read_u32(prep.CONTROL+16))
    state['body_change_status'] = body_status(p, manager, count)
    state['defusion_pending'] = defusion_pending(p,manager,count)
    state['editable'] = state['editable'] and state['body_change_status'] == 0 and not state['defusion_pending']
    actors = struct.unpack('<'+'I'*count, p.read(core.POINTERS, count*4))
    targets = struct.unpack('<'+'I'*count, p.read(core.TABLE, count*4))
    for i, actor in enumerate(actors):
        if not present & (1 << i) or not pointer(actor, 0x1600):
            continue
        data = p.read(actor, 0x1600)
        slot = word(data, 0x994)
        if slot >= modes.TEAM_CAPACITY:
            continue
        row = 0x9E4+164*slot
        char = word(data, 0x9A4+164*slot)
        model_id = word(data, 12)
        model = p.read_u32(core.MODELS+4*model_id) if model_id < modes.ENGINE_ACTORS else 0
        if pointer(model, 0x1670):
            char = p.read_u32(model+12)
        fighter = dict(physical=i, actor=actor, model=model, character=char, name=character_name(char),
                       slot=slot, row=actor+row, team=i % 2+1, action=word(data, 0x948),
                       target=targets[i], position=list(struct.unpack_from('<3f', data, 16)))
        for name, (offset, maximum) in FIELDS.items():
            fighter[name] = word(data, row+offset)
            fighter[name+'_max'] = word(data, row+maximum)
        fighter['alive'] = 0 < fighter['hp'] <= 0x1000000
        state['fighters'].append(fighter)
    return state


class RamReader:
    def __init__(self, ram): self.ram = ram
    def read(self, address, size):
        if address < 0 or address+size > len(self.ram): raise ValueError('Snapshot address outside RAM')
        return self.ram[address:address+size]
    def read_u32(self, address): return word(self.read(address, 4))


def find_request(request, state, epoch):
    if type(request) is not dict:
        raise Rejected('Invalid trainer edit request.')
    if not state.get('editable') or request.get('epoch') != epoch:
        raise Rejected('Match changed or is busy. Refresh and try again during normal combat.')
    created = request.get('created', 0)
    now = time.time()
    if type(created) not in (int, float) or not now-5 <= created <= now:
        raise Rejected('This edit expired. Select the fighter and submit it again.')
    fighter = next((f for f in state['fighters'] if f['physical'] == request.get('physical')), None)
    if fighter is None or any(request.get(k) != fighter[k] for k in ('actor', 'model', 'character', 'slot', 'row')):
        raise Rejected('That fighter or body has changed. Refresh before editing.')
    if not fighter['alive']:
        raise Rejected('Use the in-game revival mechanic for defeated fighters.')
    field, value = request.get('field'), request.get('value')
    if type(field) is not str or field not in FIELDS or type(value) is not int:
        raise Rejected('Choose a supported gauge and an integer value.')
    limit = fighter[field+'_max']
    if not 0 < limit <= 0x1000000 or not (1 if field == 'hp' else 0) <= value <= limit:
        raise Rejected(f'Value outside current {field} range.')
    return fighter, field, value


def edit(p, request, state, epoch):
    find_request(request, state, epoch)
    # No other transaction may own the hold. Recheck after acknowledgement;
    # combat cannot mutate the selected row during validate-and-apply.
    if (p.read_u32(prep.CONTROL+16) or p.read_u32(prep.CONTROL+20)
            or p.read_u32(prep.CONTROL+4) != p.read_u32(prep.CONTROL+8)):
        raise Rejected('The trainer already owns a combat hold or pending transaction.')
    prep.quiet(p)
    try:
        held = snapshot(p)
        held['editable'] = (held.get('active') and held.get('phase') == 3
                            and held.get('manager') == state['manager']
                            and held.get('count') == state['count']
                            and held.get('frame', -1) >= state['frame']
                            and held.get('body_change_status') == 0
                            and not held.get('defusion_pending')
                            and not p.read_u32(A(0x3337B8)) & 0x3900
                            and not p.read_u32(core.PAIR+4)
                            and not p.read_u32(state['manager']+628))
        fighter, field, value = find_request(request, held, epoch)
    except Rejected:
        # The native Body Change runner executes before the hold ACK and can
        # win this frame's hold race. Status 3 owns it; never release its hold.
        if (body_status(p, state['manager'], state['count']) != 3 and
                not defusion_pending(p,state['manager'],state['count'])):
            prep.resume(p)
        raise
    address = fighter['row']+FIELDS[field][0]
    old = p.read(address, 4)
    new = struct.pack('<I', value)
    prep.apply(p, {'blocks': [dict(address=address, expected_hex=old.hex(), data_hex=new.hex())]})
    if p.read(address, 4) != new:
        raise RuntimeError('Trainer edit verification failed; match remains held')
    prep.resume(p)


class Bridge:
    def __init__(self, directory=DIRECTORY):
        self.directory = Path(directory)
        self.next_poll = 0
        self.owner = None
        self.identity = None
        self.frame = 0
        self.epoch = uuid.uuid4().hex

    def service(self, p, extra=None, body=None, fusion=None):
        now = time.monotonic()
        if now < self.next_poll: return
        self.next_poll = now+.4
        try:
            lease = atomic_files.read_json(self.directory/'lease.json')
            created = lease['created']; wall_now = time.time()
            if type(created) not in (int, float) or not wall_now-4 < created <= wall_now: return
        except (OSError, ValueError, KeyError, TypeError): return
        state = snapshot(p)
        # The launchers intentionally reconnect PINE each poll. Bind the epoch
        # to the persistent match worker, not those disposable socket clients.
        identity = (id(extra), state.get('manager'), state.get('count'))
        frame = state.get('frame', 0)
        if identity != self.identity or frame < self.frame:
            self.epoch = uuid.uuid4().hex
        self.identity, self.frame, self.owner = identity, frame, extra
        busy = (bool(extra is not None and getattr(extra, 'form_job', None)) or
                bool(body is not None and body.busy) or bool(fusion is not None and fusion.busy))
        state['editable'] = state.get('editable', False) and not busy
        state.update(epoch=self.epoch, created=time.time(), offline=False, worker_busy=busy)
        try:
            atomic_files.write_json(self.directory/'snapshot.json', state, timeout=.1)
            # One request per poll lets the guest acknowledge hold release
            # before another edit. Preserve submission order, not random UUIDs.
            paths = sorted((self.directory/'requests').glob('*.json'),
                           key=lambda path: (path.stat().st_mtime_ns, path.name))[:1]
        except OSError: return
        for path in paths:
            # Claim before touching the game: filesystem retries must never
            # repeat a successfully applied command.
            claimed = path.with_suffix('.processing')
            try: path.replace(claimed)
            except OSError: continue
            result = {'ok': False, 'created': time.time()}
            try:
                try:
                    if claimed.stat().st_size > 65536:
                        raise ValueError('Trainer edit request exceeds its size limit')
                    request = atomic_files.read_json(claimed)
                except (OSError, ValueError, UnicodeError, TypeError) as error:
                    result['message'] = f'Could not read edit request: {error}'
                else:
                    try: edit(p, request, state, self.epoch)
                    except Rejected as error: result['message'] = str(error)
                    else: result.update(ok=True, message='Gauge updated')
            except Exception:
                # A transport or guest transaction error belongs to the owner:
                # do not hide it or release an uncertain preparation hold.
                result['message'] = 'Trainer transaction failed; see the runtime log before restarting.'
                raise
            finally:
                try:
                    atomic_files.write_json(self.directory/'results'/(path.stem+'.json'), result, timeout=.1)
                    claimed.unlink(missing_ok=True)
                except OSError: pass


_bridge = Bridge()
def service(p, extra=None, body=None, fusion=None):
    return _bridge.service(p, extra, body, fusion)
