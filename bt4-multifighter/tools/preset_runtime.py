"""Keep extra costume/form servicing alive for one isolated preset process.

Connection failures before a reload can be retried. Once a worker operation
starts, an error is terminal: it may have acquired the guest hold or published
a transaction. Recovery belongs to an explicit checkpoint restart, never an
implicit reconnect that abandons the transaction.
"""
from native_map import A, SERIAL
import argparse
import runtime_profile
import game_profile
import struct
import time
from pathlib import Path
import psutil
from pine import PineClient, PineError
import extra_reload_worker as reloads
import extra_reload_requests as requests
import fighter_updates
import body_swap_worker as bodies
import fusion_duration_worker as fusions
import trainer_bridge
import mod_settings
import native_preparation as native
import preset_cosmetics as cosmetics
import team_start_gate as start
from atomic_files import write_json
from runtime_owner import claim, EmulatorLifetime, EmulatorClosed
from pine import set_runtime_guard
from battle_mode_policy import ACTOR_COUNTS

ROOT = Path(__file__).resolve().parents[1]
EXECUTABLE = runtime_profile.EXECUTABLE


def epoch(p):
    """Counters that rewind when the same prepared checkpoint is reloaded.

Frame counters cover a restart before the first reload transaction. Request
and row generations also catch rewinds after completed costume/form jobs.
These reads are not an atomic emulator snapshot; all writes remain guarded
by Worker.attach and the native quiet/transaction protocol.
"""
    transport = struct.unpack('<16I', p.read(native.CONTROL, 64))
    runner = p.read_u32(reloads.runner.CONTROL+4)
    rows = p.read(requests.RECORDS, requests.ROWS*requests.STRIDE)
    return (transport[10], transport[11], transport[1], runner,
            *(struct.unpack_from('<I', rows, i*requests.STRIDE)[0] for i in range(requests.ROWS)),
            *(p.read_u32(at) for at in bodies.EPOCH_WORDS),
            *(p.read_u32(at) for at in fusions.EPOCH_WORDS))


def checkpoint(p):
    """Return (identity, counters) only after the captured preset has started."""
    manager = p.read_u32(A(0x2FEB14)); battle = p.read_u32(A(0x2FEB38))
    if not 0x100000 <= battle < 0x8000000-0x200 or p.read_u32(battle) != 3:
        return None
    mode, count, captured, configured = struct.unpack('<4I', p.read(0xD8080, 16))
    enabled, owner, request_count = struct.unpack('<3I', p.read(requests.CONTROL, 12))
    if (mode != 1 or enabled != 1 or count not in ACTOR_COUNTS or
            (owner, captured, configured, request_count) != (manager, manager, count, count)):
        return None
    gate = struct.unpack('<4I', p.read(cosmetics.CONTROL, 16))
    if gate[1:] != (cosmetics.MAGIC, manager, count):
        return None
    if gate[0] >= 100:
        raise RuntimeError(f'Fighter initialization failed with status {gate[0]}')
    started = struct.unpack('<6I', p.read(start.CONTROL, 24))
    if (gate[0] != 5 or started[0] != 0 or started[2:4] != (manager, count) or started[5] != 1):
        return None
    return (manager, count, p.read(0x073BFF00, 16)), epoch(p)


def run(pid, status_file):
    ownership = lifetime = None
    try:
        ownership = claim()
        lifetime = EmulatorLifetime(pid, executable=EXECUTABLE)
        set_runtime_guard(lifetime.require_alive)
        return _run(pid, status_file, lifetime)
    except EmulatorClosed:
        print('The game has closed.', flush=True)
        try: write_json(status_file,dict(pid=pid,state='closed',message='The game has closed.',updated=time.time()))
        except OSError: pass
        return 0
    except Exception as error:
        message=f'Fighter update stopped: {error}.'
        print(message,flush=True)
        try: write_json(status_file,dict(pid=pid,state='failed',message=message,updated=time.time()))
        except OSError: pass
        return 1
    finally:
        if lifetime is not None: lifetime.revoke()
        if ownership is not None: ownership.close()


def _run(pid, status_file, lifetime):
    from controller_mailbox import Owner
    input_owner=Owner(pid)
    try:return _run_owned(pid,status_file,lifetime,input_owner)
    finally:input_owner.close()


def _run_owned(pid, status_file, lifetime, input_owner):
    last_message = None

    def report(message, state='active'):
        nonlocal last_message
        if (state, message) != last_message:
            print(message, flush=True)
        last_message = (state, message)
        # Status-file contention must not interrupt a guest transaction.
        try:
            write_json(status_file, dict(pid=pid, state=state, message=message, updated=time.time()))
        except OSError as error:
            print(f'Could not update the worker status file: {error}', flush=True)

    worker = body = fusion = capture = counters = None
    report('Waiting for the prepared match.', 'waiting')
    while True:
        lifetime.require_alive()
        operation_started = False
        try:
            with PineClient(timeout=5) as p:
                info = p.info()
                if (info.get('serial', '').upper() != SERIAL or
                        info.get('crc', '').upper() != game_profile.pcsx2_crc()):
                    worker = body = fusion = capture = counters = None
                    input_owner.close()
                elif info.get('status') == 'running':
                    current = checkpoint(p)
                    if current is None:
                        # Discard host ownership when a checkpoint is preparing
                        # or its world is withdrawn. Never carry completed stage
                        # manifests into the next world, even if pointers recur.
                        worker = body = fusion = capture = counters = None
                        input_owner.close()
                    else:
                        current_capture, current_counters = current
                        rewound = counters is not None and any(
                            new < old for new, old in zip(current_counters, counters))
                        operation_started = True
                        input_owner.attach(p,current_capture,rewound=rewound)
                        if worker is None or current_capture != capture or rewound:
                            worker = reloads.Worker(progress=report,cell_auxiliary=True)
                            worker.attach(p)
                            body = fighter_updates.attach_body(p,progress=report)
                            fusion = fighter_updates.attach_fusion(p,progress=report)
                            capture = current_capture
                            report('Fighter updates are ready.')
                        fighter_updates.poll(p,worker,body,fusion)
                        trainer_bridge.service(p,extra=worker,body=body,fusion=fusion)
                        if worker.failure:
                            raise RuntimeError(worker.failure)
                        if not worker.active:
                            worker = body = fusion = capture = counters = None
                            input_owner.close()
                        else:
                            counters = epoch(p)
                # Pausing alone keeps this worker's completed-stage ownership.
        except EmulatorClosed:
            raise
        except (OSError, PineError) as error:
            # A normal emulator close is not a failed transaction and must not
            # reconnect to a replacement opened on the same PINE endpoint.
            lifetime.require_alive()
            if operation_started:
                report(f'Fighter update stopped: {str(error).rstrip(".")}. Close PCSX2, then start {__import__("localization").entry("play") or "Play"} again.', 'failed')
                return 1
            # Booting, closing or loading a checkpoint can briefly disconnect
            # read-only preflight. Retry before touching any guest transaction.
        except Exception as error:
            report(f'Fighter update stopped: {str(error).rstrip(".")}. Close PCSX2, then start {__import__("localization").entry("play") or "Play"} again.', 'failed')
            return 1
        time.sleep(fighter_updates.poll_delay(worker,body,fusion,.15))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--status-file', type=Path, required=True)
    args = parser.parse_args()
    try: return run(args.pid, args.status_file)
    except KeyboardInterrupt: return 0


if __name__ == '__main__': raise SystemExit(main())
