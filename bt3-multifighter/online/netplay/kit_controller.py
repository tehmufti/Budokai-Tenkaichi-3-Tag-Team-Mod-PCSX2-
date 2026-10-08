"""The SESSION process of a kit (kit 2.0; the child of the lobby window): the room's network, PINE, PCSX2 and every
phase of an online evening, driven by commands from the UI process (kit_ipc) and by the other members (protocol 5,
kit_net framing).

Roles: the HOST runs the room (kit_lobby.Lobby: authoritative), its own PCSX2, the match-making copy of its Tag Team
Mod installation (kit_prepare_auto) and the lockstep hub (kit_lockstep.Hub); every GUEST has one TCP channel and one
UDP socket to the host and runs its own PCSX2 (kit_lockstep.Client). Any number of guests (at most 7) may be in a room;
each one is a spectator until it claims a player slot, and members can join and leave at any time - a member who joins
while a match runs watches it at once (a state transfer), a player who leaves a running match leaves its fighter idle.

Phases: start -> check (this PC's files) -> lobby -> preparing -> sending -> loading -> fight -> results -> (Retry:
fight again | Return to lobby: lobby) ; leave -> start.

The UI's whole state is one small JSON object ('state', at most 10 per second) plus 'log' and 'chat' lines; a UI that
attaches later gets a 'snapshot' first. One loop: the IPC, the TCP channels (select-polled frames), the UDP socket, the
lockstep session (every 1 ms while a fight runs) and the phase's own steps; anything that blocks runs in a Job thread.
The fight half lives in kit_fight.FightMixin.
"""
import json
import os
import re
import socket
import struct
import threading
import time
import traceback
from pathlib import Path

import kit_paths
import kit_browser
import secrets
import kit_catalog
import kit_codes
import kit_fight
import kit_hub
import kit_ident
import kit_install
import kit_ipc
import kit_lobby
import kit_match
import kit_net
import kit_prepare_auto
import kit_prefetch
import kit_prebuild
import kit_settings
import kit_spec
import kit_text
import kit_win
from kit_codes import KitError

DEFAULT_PORT = 47400
DEFAULT_PINE = 28460
RENDERERS = {'auto': -1, 'd3d11': 3, 'opengl': 12, 'software': 13, 'vulkan': 14, 'd3d12': 15}
PING_LOBBY, PING_FIGHT = 5.0, 2.0
SILENCE = 30.0
PREAMBLE_WAIT, HELLO_WAIT = 10.0, 20.0
MAX_DELAY = 12
SHA256_HEX = re.compile(r'[0-9a-f]{64}')
UI_GONE = 120.0
SERIALS = {'SLUS_216.78': None, 'SLES_549.45': 'europe', 'SLPS_258.15': 'japan', 'SLPS_258.16': 'japan'}
SETTINGS_FILE = 'settings.json'
SETTINGS_KEYS = ('lang', 'port', 'delay', 'renderer', 'pad', 'fullscreen', 'host_address', 'audio', 'room_name', 'listed', 'directory', 'drop_load_failures')
# The frame-scheduled host services this kit runs online (kit_services). Not Body Change: its disc IO stage is built by
# extra_reload_service (not the preload builder kit_service makes W1-gated), so its read would finish at a different
# frame on every PC. Not timed fusion: its audio wait is IOP-timed.
ALLOWED_SERVICES = ('cpu_transform',)


def now():
    return time.monotonic()


class Job(kit_fight.kit_resync.Worker):
    def __init__(self, name, fn, *args, then=None, fail=None):
        self.name, self.then, self.fail = name, then, fail
        super().__init__(fn, *args)


def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=1), encoding='utf-8')
    tmp.replace(path)


def iso_region(path):
        import kit_adapter
        adapter, _, serial = kit_adapter.identity(path)
        if adapter != kit_paths.ADAPTER:
            raise KitError('TTM-NET-20', what='The selected disc adapter changed. Close Play online and reopen it for this disc.')
        return None, serial


class Controller(kit_hub.HubMixin, kit_prebuild.PrebuildMixin, kit_prefetch.PrefetchMixin, kit_fight.FightMixin):
    def __init__(self, args, token):
        self.args = args
        self.ipc = kit_ipc.Server(token)
        self.ipc.on_attach = self.on_attach
        self.ipc.write_info(kit_paths.DATA / 'session.json')
        self.quit = False
        self.jobs = []
        self.logs = []
        self.phase = 'start'
        self.role = None
        self.me = None                       # this PC's member id (the host is 1)
        self.cfg = self.load_settings()
        self.profile = kit_settings.load_profile()
        if getattr(args, 'name', None):
            self.profile['name'] = kit_settings.clean_name(args.name)
        self.lang = self.cfg.get('lang') or 'en'
        self.dirty, self.last_state = True, 0.0
        self.error = None
        self.notice = None
        self.checks = []
        self.run_dir = None
        self.local = None
        self.emulator = None
        self.link = None
        self.preboot_owner = None
        self.preboot_lock = threading.Lock()
        self.listener = None
        self.udp = None                      # host: kit_net.HubSocket; guest: kit_net.PeerSocket
        self.members = {}                    # host: member id -> {channel, name, ip, rtt, token, ...}
        self.net = None                      # guest: {channel, name, rtt, token}
        self.handshaking = set()
        self.lobby = None
        self.chat = []
        self.joinwith = None
        self.overlay = None
        self.progress = None
        self.summary = {}
        self.prep = None
        self.prep_progress = None
        self.prep_sent = None
        self.last_prep_sent = 0.0
        self.last_warm_broadcast = 0.0
        self.prep_gen = 0
        self.test_prep = {}
        self.states = kit_paths.STATES
        self.started_at = time.time()
        self.room_salt, self.room_key = kit_browser.challenge('')
        self.join_password = ''
        self.advertiser = None
        self.init_fight()
        self.init_prebuild()
        self.init_prefetch()
        self.init_hub()

    # ---- settings, logs, UI ---------------------------------------------------------------------------------------------
    def load_settings(self):
        cfg = load_json(kit_paths.DATA / SETTINGS_FILE, {}) or {}
        a = self.args
        for key in SETTINGS_KEYS:
            value = getattr(a, key, None)
            if value not in (None, '', False):
                cfg[key] = value
        cfg.setdefault('port', DEFAULT_PORT)
        cfg.setdefault('pad', 'keyboard' if a.hidden or a.keyboard else 'SDL-0')
        cfg.setdefault('renderer', 'default')
        cfg['drop_load_failures'] = cfg.get('drop_load_failures') is True
        if not cfg.get('lang'):
            cfg['lang'] = self.detect_lang()
        return cfg

    def detect_lang(self):
        if getattr(self.args, 'lang', None) in ('en', 'es'):
            return self.args.lang
        return kit_win.ui_language()

    def save_settings(self):
        try:
            save_json(kit_paths.DATA / SETTINGS_FILE, {k: self.cfg.get(k) for k in SETTINGS_KEYS if k in self.cfg})
        except OSError:
            pass

    def save_profile(self):
        try:
            kit_settings.save_profile(self.profile)
        except OSError:
            pass

    def say(self, text):
        line = time.strftime('%H:%M:%S ') + str(text)
        self.logs.append(line)
        del self.logs[:-300]
        target = (self.run_dir / 'console.log') if self.run_dir else (kit_paths.DATA / 'session.log')
        try:
            with open(target, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except OSError:
            pass
        self.ipc.send('log', text=str(text))

    def set_phase(self, phase):
        if phase != self.phase:
            self.say(f'-- {phase}')
            self.phase = phase
            self.notice = None
        self.dirty = True

    def fail(self, error, phase=None):
        if isinstance(error, KitError):
            self.error = error.payload()
        else:
            self.error = dict(code='TTM-NET-22', en=str(error), es=str(error), remedies=['logs'])
        self.say(self.error['en'])
        if phase:
            self.set_phase(phase)
        self.dirty = True

    def note(self, key, **args):
        self.notice = dict(key=key, args=args, at=time.time())
        self.dirty = True

    def on_attach(self):
        self.ipc.send('snapshot', state=self.ui_state(), logs=self.logs[-120:], chat=self.chat[-50:])

    def my_name(self):
        if self.lobby and self.me in self.lobby.members:
            return self.lobby.members[self.me]['name']
        return self.profile.get('name') or ''

    def ui_state(self):
        lob = self.lobby.snapshot() if self.lobby else None
        catalog = dict(dir=self.local['catalog']['dir'], tables_sha256=self.local['catalog']['tables_sha256']) \
            if self.local and self.local.get('catalog') else None
        host = None
        if self.role == 'guest' and self.net:
            host = dict(name=self.net.get('name'), rtt_ms=self.net.get('rtt_ms'),
                        connected=not self.net['channel'].closed)
        return dict(phase=self.phase, role=self.role, me=self.me, lang=self.lang, settings=self.cfg,
                    profile=dict(name=self.profile.get('name'), local=self.profile.get('local') or {}),
                    checks=self.checks, lobby=lob, joinwith=self.joinwith, host=host, catalog=catalog,
                    progress=self.progress, status=self.fight_status(), results=self.results, vote=self.vote_view(),
                    overlay=self.overlay, error=self.error, notice=self.notice, kit=kit_ident.KIT_VERSION,
                    protocol=kit_ident.PROTOCOL, services=list(ALLOWED_SERVICES),
                    listing_warning=self.advertiser.error if self.advertiser else None,
                    pcsx2=dict(pid=self.emulator.pid, desktop=self.emulator.desktop,
                               alive=self.emulator.alive()) if self.emulator and self.emulator.pid else None,
                    run_dir=str(self.run_dir) if self.run_dir else None, test=bool(self.args.test_hooks),
                    advanced=dict(port=self.cfg.get('port'), delay=self.cfg.get('delay'),
                                  renderer=self.cfg.get('renderer'), pad=self.cfg.get('pad'),
                                  fullscreen=bool(self.cfg.get('fullscreen'))),
                    chat_count=len(self.chat), chat_last=(self.chat[-1] if self.chat else None),
                    prep=self.prep.status() if self.prep else None, match=self.match_view(),
                    peek=getattr(self, 'test_peek_last', None) if self.args.test_hooks else None)

    def flush_state(self):
        t = now()
        if self.dirty and t - self.last_state >= 0.1:
            self.dirty = False
            self.last_state = t
            self.ipc.send('state', state=self.ui_state())

    # ---- the loop -------------------------------------------------------------------------------------------------------
    def run(self):
        self.say(f'TTM Online Kit {kit_ident.KIT_VERSION} (protocol {kit_ident.PROTOCOL}) session process '
                 f'{os.getpid()}')
        a = self.args
        if not getattr(a, 'install', None) and kit_paths.INTEGRATED:
            a.install = str(kit_paths.INSTALL_ROOT)      # kit 2.1: the installation this kit is part of
        files = {k: str(Path(getattr(a, k)).expanduser().resolve()) for k in ('iso', 'bios') if getattr(a, k, None)}
        if getattr(a, 'install', None):
            try:
                inst = kit_install.read_installation(a.install)
                files['install'] = inst['root']
                files.setdefault('iso', inst.get('iso'))
                files.setdefault('bios', inst.get('bios'))
            except KitError as error:
                self.fail(error)
        if files:
            kit_install.save_settings(**files)
        if self.args.host:
            self.cmd_host({})
        elif self.args.join is not None and self.args.join != '':
            self.cmd_join(dict(address=self.args.join))
        try:
            while not self.quit:
                busy = self.loop_once()
                time.sleep(0.001 if busy else 0.005)
        except KeyboardInterrupt:
            pass
        except Exception:  # noqa: BLE001 - logged; the PC's game and the others must hear about it
            self.say('SESSION ERROR: ' + traceback.format_exc())
            raise
        finally:
            self.shutdown('closed its kit')
        return 0

    def loop_once(self):
        for cmd in self.ipc.poll():
            try:
                self.on_cmd(cmd)
            except KitError as error:
                self.fail(error)
            except Exception:  # noqa: BLE001 - a bad command must not end the session
                self.say('command failed: ' + traceback.format_exc())
        self.poll_jobs()
        self.tick_prep()
        if self.listener is not None:
            self.accept()
        for ident, ch in self.channels():
            for kind, payload in ch.poll_frames():
                try:
                    self.on_frame(ident, kind, payload)
                except KitError as error:
                    self.fail(error)
                except Exception:  # noqa: BLE001
                    self.say('message failed: ' + traceback.format_exc())
        self.liveness()
        if self.udp is not None and self.session is None:
            self.udp_idle()
        try:
            busy = self.tick_phase()
        except Exception:  # noqa: BLE001 - a bug in one step must not end the process (and PCSX2 with it)
            busy = False
            self.step_failed(traceback.format_exc())
        self.ui_lifetime()
        self.flush_state()
        return busy

    def channels(self):
        """[(member id, channel)]: every guest's (host), or the host's (guest: member 1)."""
        if self.role == 'host':
            return [(k, m['channel']) for k, m in list(self.members.items())]
        if self.net:
            return [(kit_lobby.HOST, self.net['channel'])]
        return []

    def step_failed(self, text):
        t = now()
        last = getattr(self, 'last_step_error', None)
        if last is None or last[0] != text or t - last[1] > 60:
            self.last_step_error = (text, t)
            self.say('step failed: ' + text)
        if self.phase == 'fight' and self.session is not None:
            try:
                self.end_fight('error', mine=True)
            except Exception:  # noqa: BLE001
                self.say('ending the fight failed: ' + traceback.format_exc())
                self.session = None
                self.set_phase('lobby')

    def poll_jobs(self):
        for job in [j for j in self.jobs if j.done]:
            self.jobs.remove(job)
            try:
                if job.error is not None:
                    if job.fail:
                        job.fail(job.error)
                    else:
                        self.fail(job.error if isinstance(job.error, KitError) else
                                  KitError('TTM-NET-22', what=f'{job.name}: {job.error}', logs=str(self.run_dir)))
                elif job.then:
                    job.then(job.value)
            except KitError as error:
                self.fail(error)
            except Exception:  # noqa: BLE001
                self.say(f'{job.name} follow-up failed: ' + traceback.format_exc())

    def job(self, name, fn, *args, then=None, fail=None):
        j = Job(name, fn, *args, then=then, fail=fail)
        self.jobs.append(j)
        return j

    def busy(self, name):
        return any(j.name == name for j in self.jobs)

    def ui_lifetime(self):
        if self.ipc.attached() or self.phase == 'fight':
            return
        if self.ipc.detached_for() > (UI_GONE if not self.args.no_ui_timeout else 1e9):
            self.say('No lobby window for two minutes: the session ends.')
            self.quit = True

    # ---- commands from the UI -------------------------------------------------------------------------------------------
    def on_cmd(self, cmd):
        name = cmd.get('cmd')
        handler = getattr(self, 'cmd_' + str(name), None)
        if handler is None:
            self.say(f'unknown command {name!r}')
            return
        handler(cmd)

    def cmd_setup(self, c):
        for key in SETTINGS_KEYS:
            if key in c:
                self.cfg[key] = c[key]
        if c.get('lang') in ('en', 'es'):
            self.lang = c['lang']
        if 'name' in c:
            self.profile['name'] = kit_settings.clean_name(c['name'])
            self.save_profile()
        for key in ('iso', 'bios', 'install', 'appimage'):
            if c.get(key):
                kit_install.save_settings(**{key: str(Path(c[key]).expanduser())})
        if c.get('install'):
            try:
                kit_install.clear_unusable(kit_install.installation_root(c['install']))
            except KitError:
                pass
            self.install_scan = None
        self.save_settings()
        self.dirty = True

    def cmd_dismiss(self, c):
        self.error = None
        self.dirty = True

    def cmd_quit(self, c):
        self.quit = True

    def cmd_files(self, c):
        settings = kit_install.load_settings()
        out = dict(iso=settings.get('iso'), bios=settings.get('bios'), install=settings.get('install'),
                   integrated=kit_paths.INTEGRATED)
        if out['install']:
            try:
                info = kit_install.read_installation(out['install'])
                out['install_info'] = dict(version=info['version'], build=info['build'], refused=info.get('refused'),
                                           refused_regions=info.get('refused_regions'))
            except KitError as error:
                out['install_info'] = dict(error=error.values.get('what') or error.code,
                                           error_es=error.values.get('what_es'))
        elif os.name == 'nt':
            if getattr(self, 'install_scan', None) is None:
                self.install_scan = kit_install.scan()
            out['install_found'] = [dict(root=r['root'], version=r['version'], ok=r['ok'], why=r['why'],
                                         why_es=r.get('why_es')) for r in self.install_scan[:4]]
        if out['iso'] and Path(out['iso']).is_file():
            try:
                region, serial = iso_region(out['iso'])
                out['iso_region'], out['iso_serial'] = region, serial
            except KitError as error:
                out['iso_error'] = error.payload()
        self.ipc.send('files', **out)

    def network_problem(self):
        try:
            port = int(self.cfg.get('port') or DEFAULT_PORT)
        except (TypeError, ValueError):
            port = -1
        if not 1 <= port <= 65535:
            return KitError('TTM-NET-17', what=f'The port {self.cfg.get("port")!r} is not a number from 1 to 65535 '
                                                '(Advanced > Port).')
        delay = self.cfg.get('delay')
        if delay not in (None, '', 0, False):
            try:
                delay = int(delay)
            except (TypeError, ValueError):
                delay = -1
            if not 1 <= delay <= MAX_DELAY:
                return KitError('TTM-NET-17', what=f'The input delay {self.cfg.get("delay")!r} is not a number from 1 '
                                                    f'to {MAX_DELAY} (Advanced > Input delay; leave it empty for '
                                                    'automatic).')
        return None

    def cmd_host(self, c):
        if self.phase != 'start' or self.busy('setup'):
            return
        self.cmd_setup(c)
        problem = self.network_problem()
        if problem:
            self.fail(problem)
            return
        if self.cfg.get('listed') and self.cfg.get('directory'):
            try:
                kit_browser.directory_url(self.cfg['directory'])
            except ValueError as error:
                self.fail(KitError('TTM-NET-17', what=str(error)))
                return
        self.room_salt, self.room_key = kit_browser.challenge(str(c.get('password') or '')[:128])
        self.begin('host')

    def cmd_join(self, c):
        if self.phase != 'start' or self.busy('setup'):
            return
        self.cmd_setup(c)
        address = (c.get('address') or self.cfg.get('host_address') or '').strip()
        if not address:
            self.fail(KitError('TTM-NET-17', what='Type the host\'s address first (Start > Host address).'))
            return
        problem = self.network_problem()
        if problem:
            self.fail(problem)
            return
        self.cfg['host_address'] = address
        recent = [a for a in (load_json(kit_paths.DATA / 'recent-hosts.json', []) or []) if a != address]
        try:
            save_json(kit_paths.DATA / 'recent-hosts.json', ([address] + recent)[:8])
        except OSError:
            pass
        self.save_settings()
        self.join_password = str(c.get('password') or '')[:128]
        self.begin('guest')

    # ---- this PC ----------------------------------------------------------------------------------------------------------
    def begin(self, role):
        self.role = role
        self.error = None
        kit_paths.RUNS.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime('%Y%m%d-%H%M%S')
        self.run_dir = kit_paths.RUNS / f'{stamp}-{role}'
        n = 1
        while self.run_dir.exists():
            n += 1
            self.run_dir = kit_paths.RUNS / f'{stamp}-{role}-{n}'
        self.run_dir.mkdir(parents=True)
        self.summary = dict(role=role, kit=kit_ident.KIT_VERSION, started=time.strftime('%Y-%m-%d %H:%M:%S'),
                            args={k: v for k, v in vars(self.args).items()}, fights=[])
        self.set_phase('check')
        self.checks = [dict(key=k, ok=None) for k in ('iso', 'catalog', 'disc', 'bios', 'pcsx2', 'settings', 'kit')]
        self.job('setup', self.local_setup, then=self.after_setup, fail=self.setup_failed)

    def check(self, key, ok, note=None, **values):
        for item in self.checks:
            if item['key'] == key:
                item.update(ok=ok, note=note, values=values)
        self.dirty = True

    def local_setup(self):
        import kit_emu
        a = self.args
        settings = kit_install.load_settings()
        install = None
        if settings.get('install'):
            try:
                install = kit_install.read_installation(settings['install'])
            except KitError:
                install = None
        iso = settings.get('iso') or (install or {}).get('iso')
        bios = settings.get('bios') or (install or {}).get('bios')
        if not iso or not Path(iso).is_file():
            raise KitError('TTM-NET-20', what='No game ISO was chosen yet (or it moved): choose it in Start > Game ISO.')
        if not bios or not Path(bios).is_file():
            raise KitError('TTM-NET-21', what='No BIOS file was chosen yet (or it moved): choose it in Start > BIOS.')
        region, serial = iso_region(iso)
        if region in ('europe', 'japan'):
            raise KitError('TTM-NET-20', what=f'{Path(iso).name} is the {"European" if region == "europe" else "Japanese"}'
                                              f' version ({serial}): online needs the USA disc (SLUS-21678) on every '
                                              'PC for now.')
        if region == 'other':
            raise KitError('TTM-NET-20', what=f'{Path(iso).name} is {serial}, not Dragon Ball Z: Budokai Tenkaichi 3 '
                                              '(USA, SLUS-21678).')
        self.check('iso', True, Path(iso).name, serial=serial)
        catalog = kit_catalog.load(iso)
        view = kit_catalog.View(catalog)
        self.check('catalog', True, kit_text.t('check.catalog_note', self.lang, fighters=len(view.selectable),
                                               stages=len(view.stages)))
        last = [0.0]

        def progress(done, total):
            t = time.time()
            if t - last[0] > 1 or done == total:
                last[0] = t
                self.check('disc', None, f'{done * 100 // max(total, 1)} %')
        disc = kit_ident.disc_identity(iso, full=a.disc_check == 'full', progress=progress,
                                       cache_file=kit_paths.DATA / 'disc-cache.json')
        self.check('disc', True, f'{disc["serial"]} CRC {disc["crc"]}' +
                   ('' if disc.get('original') in (None, True) else ' (not the original dump)'))
        bios_id = kit_ident.bios_identity(bios)
        self.check('bios', True, bios_id['describe'])
        if self.emulator is None or not self.emulator.alive():
            desktop = (a.desktop or f'ttm-kit-{a.pine_slot}') if a.hidden else None
            em = kit_emu.make(a, run_dir=self.run_dir, say=self.say, desktop=desktop)
            em.pause_key = a.pause_key
            build = em.build_identity()
            if kit_paths.INTEGRATED and not build.get('tested'):
                self.say(f'Note: {kit_ident.describe_build(build)} is the installation\'s own PCSX2, not one the '
                         'cross-PC tests ran: every PC of a room must run this same build (TTM-NET-03).')
            else:
                kit_ident.require_tested(build)
            pad = self.cfg.get('pad') or 'SDL-0'
            extra = []
            renderer = self.cfg.get('renderer') or 'default'
            if renderer != 'default' and renderer in RENDERERS:
                extra.append(('EmuCore/GS', 'Renderer', str(RENDERERS[renderer])))
            ini = em.setup(bios=bios, pad1='keyboard' if a.hidden else pad,
                           null_audio=a.hidden or self.cfg.get('audio') == 'null', extra=extra)
        else:
            em = self.emulator
            em.run_dir = self.run_dir
            build = em.build_identity()
            ini = em.ini_text
        self.check('pcsx2', True, kit_ident.describe_build(build))
        self.check('settings', True, None)
        identity = kit_ident.local_identity(disc=disc, bios=bios_id, ini_text=ini, pcsx2=build,
                                            bios_policy=a.bios_check, disc_policy=a.disc_check,
                                            name=self.profile.get('name') or self.role)
        self.check('kit', True, kit_text.t('check.kit_note', self.lang, kit=kit_ident.KIT_VERSION,
                                           protocol=kit_ident.PROTOCOL))
        (self.run_dir / 'identity.json').write_text(json.dumps(identity, indent=1), encoding='utf-8')
        prep_why = self.prep_problem(install, iso, disc) if self.role == 'host' else None
        return dict(iso=iso, bios=bios, install=install, identity=identity, catalog=catalog, view=view, emulator=em,
                    prep_why=prep_why)

    def setup_failed(self, error):
        self.fail(error if isinstance(error, KitError) else KitError('TTM-NET-22', what=str(error),
                                                                    logs=str(self.run_dir)), phase='start')
        for item in self.checks:
            if item['ok'] is None:
                item['ok'] = False
                break
        self.role = None

    def after_setup(self, local):
        self.local = local
        self.emulator = local['emulator']
        self.preboot_game()
        if self.role == 'host':
            self.start_host()
        else:
            self.start_guest()

    def preboot_game(self):
        # Windows can keep an idle VM paused. Linux starts running immediately,
        # so it retains the established statefile startup rather than exposing
        # unowned gameplay while the room is being configured.
        if self.quit or os.name != 'nt' or not kit_paths.INTEGRATED or self.emulator.alive() or self.busy('preboot'):
            return
        patch = kit_install.installation_pnach()
        if patch is None:
            return
        self.emulator.install_pnach(patch)
        owner = dict(emulator=self.emulator, local=self.local, role=self.role,
                     cancel=threading.Event(), pid=None, link=None, stopped=False)
        with self.preboot_lock:
            if self.quit:
                return
            self.preboot_owner = owner
        self.job('preboot', self.preboot_game_job, owner,
                 then=lambda result, o=owner: self.preboot_game_ready(result, o),
                 fail=lambda error, o=owner: self.preboot_game_failed(error, o))

    def preboot_current(self, owner):
        return owner is not None and self.preboot_owner is owner and not owner['cancel'].is_set() and \
            not self.quit and self.emulator is owner['emulator'] and self.local is owner['local'] and \
            self.role == owner['role']

    def dispose_preboot(self, owner):
        """Close only the link/VM this initialization owned, even after a rejoin."""
        if owner is None:
            return
        with self.preboot_lock:
            link, owner['link'] = owner['link'], None
            em = owner['emulator']
            stop = owner['pid'] is not None and em.pid == owner['pid'] and not owner['stopped']
            if stop:
                owner['stopped'] = True
        if link is not None:
            try:
                link.close()
            except (OSError, RuntimeError):
                pass
        if stop:
            em.stop()

    def invalidate_preboot(self):
        # Serialized with the short launch itself: shutdown cannot stop an
        # empty PID and then have the worker create a new VM afterward.
        with self.preboot_lock:
            owner, self.preboot_owner = self.preboot_owner, None
            if owner is not None:
                owner['cancel'].set()
            self.pending_preboot_load = False
        self.dispose_preboot(owner)

    def preboot_game_job(self, owner):
        from pinelink import PineLink
        em = owner['emulator']
        with self.preboot_lock:
            if not self.preboot_current(owner):
                return dict(cancelled=True)
            pid = em.launch_idle(owner['local']['iso'])
            owner['pid'] = pid
            self.remember_pid(pid)
        info = em.wait_idle()
        with self.preboot_lock:
            if not self.preboot_current(owner):
                return dict(cancelled=True)
        problems = kit_ident.runtime_problems(info)
        if problems:
            code, what = problems[0]
            raise KitError(code, what=what, build=info.get('version'), tested=', '.join(kit_ident.TESTED_PINE))
        link = PineLink(self.args.pine_slot, pid, owner=em.pine_owner).connect()
        with self.preboot_lock:
            owner['link'] = link
            current = self.preboot_current(owner)
            if current:
                em.link = link
        if not current:
            self.dispose_preboot(owner)
            return dict(cancelled=True)
        em.minimise()
        return dict(pid=pid, info=info, link=link)

    def preboot_game_ready(self, result, owner):
        with self.preboot_lock:
            current = self.preboot_current(owner) and not result.get('cancelled')
            if current:
                self.link = result['link']
                self.preboot_owner = None
                owner['link'] = None             # the running room now owns it
        if not current:
            self.dispose_preboot(owner)
            return
        self.say('PCSX2 is initialized and waiting for the agreed match.')
        if getattr(self, 'pending_preboot_load', False):
            self.pending_preboot_load = False
            if self.match and self.phase in ('sending', 'loading'):
                self.load_match()

    def preboot_game_failed(self, error, owner):
        with self.preboot_lock:
            current = self.preboot_current(owner)
            if current:
                self.preboot_owner = None
        self.dispose_preboot(owner)
        if not current:
            return
        self.say(f'Lobby initialization could not finish; the match will use the normal startup: {error}')
        self.link = None
        if getattr(self, 'pending_preboot_load', False):
            self.pending_preboot_load = False
            if self.match and self.phase in ('sending', 'loading'):
                self.load_match()

    # ---- host: the room ---------------------------------------------------------------------------------------------------
    def start_host(self):
        view = self.local['view']
        self.me = kit_lobby.HOST
        name = self.profile.get('name') or 'Player 1'
        self.lobby = kit_lobby.Lobby(host_name=name, catalog=view, rules=self.profile.get('rules'), lang=self.lang)
        self.lobby.room['drop_load_failures'] = self.cfg.get('drop_load_failures') is True
        self.setup_prep()
        try:
            self.listen()
        except KitError as error:
            self.fail(error, phase='start')
            self.lobby = None
            self.role = None
            return
        if self.cfg.get('room_name'):
            self.lobby.room['name'] = str(self.cfg['room_name'])[:64]
        self.lobby.bump()
        self.set_phase('lobby')
        self.broadcast()

    def listen(self):
        port = int(self.cfg.get('port') or DEFAULT_PORT)
        tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            tcp.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            tcp.bind((self.args.bind, port))
            tcp.listen(8)
        except OSError as error:
            tcp.close()
            raise KitError('TTM-NET-14', what='TCP', port=port, details=str(error)) from None
        tcp.setblocking(False)
        self.listener = tcp
        self.udp = kit_net.HubSocket((self.args.bind, port), impairment=self.impairment())
        main_ip, others = kit_win.lan_addresses()
        self.joinwith = dict(main=main_ip, others=others, port=port, default_port=port == DEFAULT_PORT)
        self.say(f'Room open on TCP and UDP port {port} ({main_ip}).')
        if self.cfg.get('listed'):
            self.advertiser = kit_browser.Advertiser(self.room_advertisement, self.cfg.get('directory') or '')

    def room_advertisement(self):
        return dict(name=self.cfg.get('room_name') or self.profile.get('name') or 'Tag Team Mod',
                    port=int(self.cfg.get('port') or DEFAULT_PORT), adapter=kit_paths.ADAPTER,
                    version=kit_ident.KIT_VERSION, protocol=kit_ident.PROTOCOL, phase=self.phase,
                    players=1 + len(self.members), password=self.room_key is not None)

    def impairment(self):
        a = self.args
        return kit_net.Impairment(a.latency, a.jitter, a.loss, seed=7 + (self.me or 0) + os.getpid() % 97)

    def accept(self):
        while True:
            try:
                conn, source = self.listener.accept()
            except (BlockingIOError, InterruptedError, OSError):
                return
            conn.setblocking(True)
            ch = kit_net.Channel(conn, f'{source[0]}:{source[1]}')
            full = len(self.members) + len(self.handshaking) + 1 >= kit_lobby.MAX_MEMBERS
            if full or self.lobby is None:
                self.job('busy', self.refuse_full, ch)
                continue
            self.say(f'Someone connected from {source[0]}.')
            self.handshaking.add(ch)
            self.udp.pending.add(source[0])
            self.job('handshake', self.host_handshake, ch, source,
                     then=self.after_handshake, fail=lambda e, ch=ch, ip=source[0]: self.handshake_failed(e, ch, ip))

    def refuse_full(self, ch):
        try:
            ch.send_preamble(kit_ident.PROTOCOL)
            ch.read_preamble(5)
            ch.try_send(type='REFUSE', codes=['TTM-NET-15'], **kit_codes.payload('TTM-NET-15'))
        except Exception:  # noqa: BLE001 - a stranger's connection ends here
            pass
        ch.close_soon()

    def hello_body(self):
        cat = self.local['catalog']
        return dict(type='HELLO', role=self.role, identity=self.local['identity'],
                    request=dict(delay=self.cfg.get('delay') or None),
                    lobby=dict(v=2, name=self.profile.get('name') or '', lang=self.lang, ui=self.args.ui or 'tk',
                               catalog=dict(family=cat['family'], disc=cat['disc'],
                                            tables_sha256=cat['tables_sha256'])))

    def host_handshake(self, ch, source):
        a = self.args
        ch.send_preamble(kit_ident.PROTOCOL)
        wait = min(a.timeout, PREAMBLE_WAIT)
        try:
            theirs = ch.read_preamble(wait)
        except TimeoutError:
            raise KitError('TTM-NET-09', seconds=int(wait), step='hello') from None
        except (ConnectionError, OSError) as error:
            raise KitError('TTM-NET-13', why=f'the connection closed during the hello ({error})') from None
        if theirs != kit_ident.PROTOCOL:
            ch.try_send(type='REFUSE', codes=['TTM-NET-01'], **kit_codes.payload('TTM-NET-01', mine=kit_ident.PROTOCOL,
                                                                                theirs=theirs))
            raise KitError('TTM-NET-01', mine=kit_ident.PROTOCOL, theirs=theirs)
        nonce = secrets.token_hex(16)
        ch.send_json(**dict(self.hello_body(), auth=dict(required=self.room_key is not None,
                     salt=self.room_salt, nonce=nonce)))
        try:
            hello = ch.expect('HELLO', min(a.timeout, HELLO_WAIT), 'hello')
        except (ValueError, AttributeError, TypeError) as error:
            raise KitError('TTM-NET-13', why=f'it did not send a kit HELLO ({type(error).__name__})') from None
        if not isinstance(hello.get('identity'), dict) or not isinstance(hello.get('lobby') or {}, dict) or \
                not isinstance(hello.get('request') or {}, dict):
            raise KitError('TTM-NET-13', why='its HELLO is malformed')
        if not kit_browser.auth_ok(self.room_key, nonce, hello.get('password_proof')):
            ch.try_send(type='REFUSE', codes=['TTM-NET-17'],
                        en='Room password is incorrect. Enter it and join again.',
                        es='La contraseña de la sala es incorrecta. Escríbela y vuelve a entrar.')
            raise KitError('TTM-NET-17', what='Room password is incorrect.')
        findings = kit_ident.compare(self.local['identity'], hello.get('identity') or {})
        cat = ((hello.get('lobby') or {}).get('catalog') or {})
        if cat.get('tables_sha256') != self.local['catalog']['tables_sha256']:
            findings.append(('TTM-NET-06', 'refuse', dict(what='the fighter tables read from the two ISOs differ')))
        refusals = [f for f in findings if f[1] == 'refuse']
        if refusals:
            code, _, values = refusals[0]
            ch.try_send(type='REFUSE', codes=[c for c, _, _ in refusals], **kit_codes.payload(code, **values))
            time.sleep(0.5)
            raise KitError(code, **values)
        token = kit_ipc.new_token()
        ch.send_json(type='ACCEPT', room=self.lobby.room, token=token, findings=[[c, lvl] for c, lvl, _ in findings])
        end = time.time() + a.timeout + 15
        rtt = None
        while rtt is None:
            try:
                kind, message = ch.receive(1.0)
            except TimeoutError:
                if time.time() > end:
                    raise KitError('TTM-NET-09', seconds=int(a.timeout), step='measuring the connection') from None
                continue
            except (ConnectionError, OSError) as error:
                raise KitError('TTM-NET-13', why=f'the connection closed while measuring ({error})') from None
            if kind != 'J' or not isinstance(message, dict):
                continue
            if message.get('type') == 'RTT':
                rtt = message.get('rtt')
                if not isinstance(rtt, dict) or not all(isinstance(rtt.get(k), (int, float)) and
                                                        not isinstance(rtt.get(k), bool) and 0 <= rtt[k] < 60000
                                                        for k in ('min', 'median', 'p95')):
                    raise KitError('TTM-NET-13', why='its round-trip measurement is malformed')
            elif message.get('type') == 'UDPFAIL':
                raise KitError('TTM-NET-11', address=ch.peer_text, seconds=message.get('seconds'),
                               port=self.cfg.get('port'))
            elif message.get('type') in ('BYE', 'REFUSE'):
                raise KitError('TTM-NET-13', why=message.get('why') or message.get('codes'))
        return dict(channel=ch, hello=hello, findings=findings, rtt=rtt, token=token, source=source)

    def handshake_failed(self, error, ch, ip):
        self.handshaking.discard(ch)
        self.udp.pending.discard(ip)
        ch.close_soon()
        text = error.code if isinstance(error, KitError) else str(error)
        self.say(f'A player who connected was refused or left ({text}); the room stays open.')
        if isinstance(error, KitError):
            self.say(str(error))
        self.note('notice.guest_refused', code=text)

    def after_handshake(self, r):
        ch = r['channel']
        self.handshaking.discard(ch)
        ip = r['source'][0]
        self.udp.pending.discard(ip)
        hello = r['hello']
        for code, level, values in r['findings']:
            if level != 'refuse':
                self.say(kit_ident.note_line(code, values))
        lob = hello.get('lobby') or {}
        ident = self.lobby.join(lob.get('name') or '', lang=lob.get('lang') or 'en') if self.lobby else None
        if ident is None:
            ch.try_send(type='REFUSE', codes=['TTM-NET-15'], **kit_codes.payload('TTM-NET-15'))
            ch.close_soon()
            return
        requested = None
        try:
            d = (hello.get('request') or {}).get('delay')
            requested = int(d) if d not in (None, '', False) and 1 <= int(d) <= MAX_DELAY else None
        except (TypeError, ValueError):
            requested = None
        rtt = r['rtt']
        self.members[ident] = dict(channel=ch.blocking(), name=self.lobby.members[ident]['name'], ip=ip, rtt=rtt,
                                   rtt_ms=rtt.get('median'), token=r['token'], request_delay=requested,
                                   lang=lob.get('lang'), last_ping=0.0)
        self.lobby.members[ident]['rtt_ms'] = rtt.get('median')
        self.udp.allow(ident, ip)
        ch.try_send(type='WELCOME', member=ident, name=self.lobby.members[ident]['name'])
        self.say(f'{self.lobby.members[ident]["name"]} joined from {ip} (round trip {rtt["median"]} ms).')
        self.summary.setdefault('members', []).append(dict(id=ident, ip=ip, rtt=rtt, at=time.strftime('%H:%M:%S')))
        self.broadcast()
        self.member_joined_during_match(ident)

    # ---- guest: join ------------------------------------------------------------------------------------------------------
    def start_guest(self):
        self.set_phase('check')
        self.job('connect', self.guest_connect, then=self.after_connect, fail=self.connect_failed)

    def guest_connect(self):
        host, port = kit_net.address(self.cfg['host_address'], int(self.cfg.get('port') or DEFAULT_PORT))
        try:
            ip = socket.gethostbyname(host)
        except OSError as error:
            raise KitError('TTM-NET-10', address=self.cfg['host_address'], error=error, port=port) from None
        self.say(f'Connecting to the host {ip}:{port}...')
        try:
            sock = socket.create_connection((ip, port), timeout=10)
        except OSError as error:
            why = 'nothing answers there' if isinstance(error, ConnectionRefusedError) else \
                'timed out' if isinstance(error, socket.timeout) else str(error)
            raise KitError('TTM-NET-10', address=f'{ip}:{port}', error=why, port=port) from None
        sock.settimeout(None)
        ch = kit_net.Channel(sock, f'{ip}:{port}')
        udp = kit_net.PeerSocket(('0.0.0.0', 0), peer=(ip, port), allowed_ip=ip, impairment=self.impairment())
        try:
            return self.guest_handshake(ch, udp)
        except BaseException:
            ch.close()
            udp.close()
            raise

    def guest_handshake(self, ch, udp):
        a = self.args
        ch.send_preamble(kit_ident.PROTOCOL)
        try:
            theirs = ch.read_preamble(a.timeout)
        except TimeoutError:
            raise KitError('TTM-NET-09', seconds=int(a.timeout), step='hello') from None
        except (ConnectionError, OSError) as error:
            raise KitError('TTM-NET-13', why=f'the connection closed during the hello ({error})') from None
        if theirs != kit_ident.PROTOCOL:
            ch.try_send(type='REFUSE', codes=['TTM-NET-01'])
            raise KitError('TTM-NET-01', mine=kit_ident.PROTOCOL, theirs=theirs)
        hello = ch.expect('HELLO', a.timeout, 'hello')
        body = self.hello_body()
        auth = hello.get('auth') or {}
        if auth.get('required'):
            salt, nonce = auth.get('salt', ''), auth.get('nonce', '')
            if not all(isinstance(x, str) and len(x) == 32 and all(c in '0123456789abcdef' for c in x)
                       for x in (salt, nonce)):
                raise KitError('TTM-NET-13', why='Malformed room password challenge.')
            body['password_proof'] = kit_browser.proof(kit_browser.password_key(self.join_password, salt), nonce)
        self.join_password = ''
        ch.send_json(**body)
        accept = ch.expect('ACCEPT', a.timeout, 'the host\'s answer')
        findings = kit_ident.compare(self.local['identity'], hello.get('identity') or {})
        rtt = kit_net.measure_rtt(udp, seconds=3.0, first_answer=min(10.0, a.timeout))
        if rtt is None:
            ch.try_send(type='UDPFAIL', seconds=10)
            raise KitError('TTM-NET-11', address=ch.peer_text, seconds=10, port=self.cfg.get('port'))
        ch.send_json(type='RTT', rtt=rtt)
        welcome = ch.expect('WELCOME', a.timeout, 'the room')
        return dict(channel=ch, udp=udp, hello=hello, accept=accept, rtt=rtt, findings=findings, welcome=welcome)

    def connect_failed(self, error):
        if isinstance(error, kit_net.RemoteRefusal):
            m = error.message
            code = (m.get('codes') or ['TTM-NET-17'])[0]
            if m.get('en'):
                self.error = dict(code=code, en=m.get('en'), es=m.get('es') or m.get('en'),
                                  remedies=list(kit_codes.REMEDIES.get(code, ())))
            else:
                self.error = kit_codes.payload(code, what='the host refused this PC.')
            self.say(self.error['en'])
            self.set_phase('start')
        else:
            self.fail(error if isinstance(error, KitError) else KitError('TTM-NET-10', address=self.cfg.get(
                'host_address'), error=str(error), port=self.cfg.get('port')), phase='start')
        self.role = None

    def after_connect(self, r):
        hello = r['hello']
        for code, level, values in r['findings']:
            if level != 'refuse':
                self.say(kit_ident.note_line(code, values))
        lob = hello.get('lobby') or {}
        self.udp = r['udp']
        self.me = int(r['welcome']['member'])
        self.net = dict(channel=r['channel'].blocking(), name=kit_lobby.chat_text(lob.get('name') or 'host')[:32],
                        rtt=r['rtt'], rtt_ms=r['rtt'].get('median'), token=r['accept'].get('token'), last_ping=0.0)
        self.lobby = None
        self.say(f'Joined the room of {self.net["name"] or "the host"} as {r["welcome"].get("name")} (round trip '
                 f'{r["rtt"]["median"]} ms).')
        self.summary.update(host=self.net['name'], rtt=r['rtt'], me=self.me,
                            findings=[dict(code=c, level=lvl) for c, lvl, _ in r['findings']])
        self.set_phase('lobby')

    # ---- liveness ----------------------------------------------------------------------------------------------------------
    def send(self, **message):
        """Guest: to the host. Host: to every guest."""
        if self.role == 'guest':
            return self.net['channel'].try_send(**message) if self.net else False
        ok = True
        for ident in list(self.members):
            ok = self.send_to(ident, **message) and ok
        return ok

    def send_to(self, ident, **message):
        if self.role == 'guest':
            return self.send(**message)
        m = self.members.get(ident)
        return m['channel'].try_send(**message) if m else False

    def liveness(self):
        t = now()
        every = PING_LOBBY if self.phase in ('lobby', 'start', 'check') else PING_FIGHT
        for ident, ch in self.channels():
            entry = self.members.get(ident) if self.role == 'host' else self.net
            if entry is None:
                continue
            if not ch.closed and t - entry.get('last_ping', 0) >= every and not ch.transfers:
                entry['last_ping'] = t
                ch.try_send(type='PING', t=time.time())
            if ch.closed or ch.silent(t) > SILENCE:
                if self.role == 'host':
                    self.member_gone(ident, KitError('TTM-NET-13', why='its connection was lost'))
                else:
                    self.host_gone(KitError('TTM-NET-13', why='the connection to the host was lost'))

    def udp_idle(self):
        if self.role == 'host':
            self.udp.recv()                              # answers the pings of joining PCs
            return
        t = now()
        for data in self.udp.recv():
            p = kit_net.parse_ping(data)
            if p and p[0] == 2 and self.net:
                self.net['rtt_ms'] = round((time.perf_counter_ns() - p[2]) / 1e6, 1)
        if self.net and t - getattr(self, 'last_udp_ping', 0) > 2.0:
            self.last_udp_ping = t
            self.udp.send(kit_net.ping_packet(1, int(t), time.perf_counter_ns()))

    def member_gone(self, ident, error=None, said=None):
        """Host: a guest left (BYE) or its connection was lost."""
        m = self.members.pop(ident, None)
        if m is None:
            return
        name = self.lobby.members.get(ident, {}).get('name', f'member {ident}') if self.lobby else str(ident)
        self.say(said or f'{name} left the room{"" if error is None else f" ({error})"}.')
        try:
            m['channel'].close_soon()
        except OSError:
            pass
        self.udp.forget(ident)
        self.member_left_match(ident)
        if self.lobby:
            self.lobby.leave(ident)
            self.broadcast()

    def host_gone(self, error, said=None):
        """Guest: the host closed the room (BYE) or the connection was lost: back to Start."""
        self.invalidate_preboot()
        self.say(said or str(error))
        if self.phase in ('fight', 'loading') and self.session is not None:
            self.abort_game()
        self.leave_match_state()
        if self.net:
            self.net['channel'].close_soon()
        self.net = None
        self.lobby = None
        self.me = None
        self.to_background()
        if self.udp is not None:
            self.udp.close()
            self.udp = None
        self.role = None
        self.error = error.payload() if isinstance(error, KitError) else None
        self.set_phase('start')

    # ---- messages ----------------------------------------------------------------------------------------------------------
    def on_frame(self, ident, kind, payload):
        if kind == 'P':
            if self.role == 'guest':
                self.on_prefetch_chunk(ident, payload)
            return
        if kind == 'B':
            self.on_chunk(ident, payload)
            return
        if not isinstance(payload, dict):
            return
        t = payload.get('type')
        if self.role == 'host' and t in HOST_ONLY:
            return                                      # a guest never tells the host what the host decides
        handler = getattr(self, 'msg_' + str(t), None)
        if handler is None:
            if t not in ('PONG',):
                self.say(f'(ignored message {t})')
            return
        handler(ident, payload)

    def msg_PING(self, ident, m):
        ch = dict(self.channels()).get(ident)
        if ch is not None and not ch.transfers:
            ch.try_send(type='PONG', t=m.get('t'))

    def msg_BYE(self, ident, m):
        if self.role == 'host':
            self.member_gone(ident, said=f'{self.lobby.members.get(ident, {}).get("name", ident)} left the room.')
            return
        why = m.get('why') or 'it closed the room'
        if why == 'closed':
            self.host_gone(None, said='The host closed the room.')
            self.note('notice.host_closed')
        elif why == 'kicked':
            self.host_gone(None, said='The host removed you from the room.')
            self.note('notice.kicked')
        elif why == 'load_failed':
            self.host_gone(None, said='You were removed from the room because your match could not load.')
            self.note('notice.load_dropped')
        else:
            self.host_gone(KitError('TTM-NET-13', why=why))

    def msg_REFUSE(self, ident, m):
        code = (m.get('codes') or ['TTM-NET-17'])[0]
        error = dict(code=code, en=m.get('en') or m.get('text') or code, es=m.get('es') or m.get('en') or code,
                     remedies=list(kit_codes.REMEDIES.get(code, ())))
        if self.role == 'guest':
            self.host_gone(KitError('TTM-NET-13', why=f'it refused: {code}'))
            self.error = error
            self.say(error['en'])
        else:
            self.member_gone(ident, KitError(code, what=error['en']))

    def msg_CHAT(self, ident, m):
        text = kit_lobby.chat_text(m.get('text', ''))
        if not text:
            return
        if self.role == 'host':
            who = self.lobby.members.get(ident, {}).get('name', '?') if self.lobby else '?'
            row = dict(who=who, text=text, at=time.strftime('%H:%M'), member=ident)
            self.send(type='CHAT', text=text, who=who, member=ident)
        else:
            row = dict(who=str(m.get('who') or '?')[:32], text=text, at=time.strftime('%H:%M'),
                       member=m.get('member'), mine=m.get('member') == self.me)
        self.chat.append(row)
        self.ipc.send('chat', **row)
        self.dirty = True

    def cmd_chat(self, c):
        text = kit_lobby.chat_text(c.get('text', ''))
        if not text or not self.lobby:
            return
        if self.role == 'host':
            self.msg_CHAT(self.me, dict(text=text))
            self.chat[-1]['mine'] = True
        else:
            self.send(type='CHAT', text=text)

    # ---- the lobby ---------------------------------------------------------------------------------------------------------
    def broadcast(self):
        """Host: the LOBBY snapshot to every guest and the UI."""
        if self.role != 'host' or not self.lobby:
            return
        snap = self.lobby.snapshot()
        self.send(type='LOBBY', **snap)
        self.dirty = True

    def msg_LOBBY(self, ident, m):
        if self.role != 'guest':
            return
        snap = {k: v for k, v in m.items() if k != 'type'}
        try:
            if self.lobby is None:
                self.lobby = kit_lobby.Lobby.from_snapshot(snap)
            else:
                self.lobby.apply(snap)
        except ValueError as error:
            self.say(f'(ignored a malformed lobby from the host: {error})')
            return
        me = self.lobby.members.get(self.me)
        if me and self.profile.get('name') != me['name'] and getattr(self, 'renamed', False):
            self.profile['name'] = me['name']
            self.save_profile()
            self.renamed = False
        self.dirty = True

    def request(self, kind, **fields):
        """A lobby change: applied directly on the host, sent to the host by a guest."""
        if self.role == 'host':
            getattr(self, 'msg_' + kind)(self.me, dict(fields, type=kind))
        else:
            self.send(type=kind, **fields)

    def cmd_name(self, c):
        name = kit_settings.clean_name(c.get('name', ''))
        if not name:
            return
        self.profile['name'] = name
        self.save_profile()
        self.renamed = True
        if self.lobby:
            self.request('NAME', name=name)

    def msg_NAME(self, ident, m):
        if self.role == 'host' and self.lobby and self.lobby.rename(ident, m.get('name', '')):
            if ident in self.members:
                self.members[ident]['name'] = self.lobby.members[ident]['name']
            self.broadcast()

    def cmd_claim(self, c):
        self.request('CLAIM', team=c.get('team'), index=c.get('index') or 0)

    def msg_CLAIM(self, ident, m):
        if self.role != 'host' or not self.lobby or self.lobby.phase != 'lobby':
            return
        try:
            team, index = int(m.get('team')), int(m.get('index') or 0)
        except (TypeError, ValueError):
            return
        found = self.lobby.claim(ident, team, index)
        if found:
            self.lobby.bump(dict(code='TTM-NET-29', key='notice.claim_refused', args=dict(what=found[0])))
        self.broadcast()

    def cmd_lock(self, c):
        """Host: lock (or unlock) a fighter: nobody may claim it, it stays a CPU."""
        if not self.host_edit():
            return
        try:
            team, index = int(c.get('team')), int(c.get('index'))
        except (TypeError, ValueError):
            return
        self.lobby.lock(team, index, bool(c.get('locked', True)))
        self.broadcast()

    def cmd_kick(self, c):
        """Host: remove a member from the room (its kit goes back to the start screen)."""
        if self.role != 'host' or not self.lobby:
            return
        try:
            ident = int(c.get('member'))
        except (TypeError, ValueError):
            return
        if ident == kit_lobby.HOST or ident not in self.members:
            return
        name = self.lobby.members.get(ident, {}).get('name', ident)
        self.send_to(ident, type='BYE', why='kicked')
        self.member_gone(ident, said=f'{name} was removed from the room by the host.')

    def cmd_unclaim(self, c):
        self.request('UNCLAIM')

    def msg_UNCLAIM(self, ident, m):
        if self.role == 'host' and self.lobby and self.lobby.phase == 'lobby' and self.lobby.unclaim(ident):
            self.broadcast()

    def cmd_fighter(self, c):
        self.request('FIGHTER', team=c.get('team'), index=c.get('index'), character=c.get('character'),
                     costume=c.get('costume'))

    def msg_FIGHTER(self, ident, m):
        if self.role != 'host' or not self.lobby or self.lobby.phase != 'lobby':
            return
        try:
            team, index, character, costume = (int(m.get(k)) for k in ('team', 'index', 'character', 'costume'))
        except (TypeError, ValueError):
            return
        self.lobby.set_fighter(ident, team, index, character, costume, self.local['view'])
        self.broadcast()

    def cmd_ready(self, c):
        self.request('READY', ready=bool(c.get('ready')))

    def msg_READY(self, ident, m):
        if self.role == 'host' and self.lobby and self.lobby.phase == 'lobby' and \
                self.lobby.set_ready(ident, bool(m.get('ready'))):
            self.broadcast()

    # host-only edits (UI commands of the host; a guest's UI never offers them)
    def host_edit(self):
        return self.role == 'host' and self.lobby is not None and self.lobby.phase == 'lobby'

    def cmd_load_policy(self, c):
        """Host-only start policy; not a gameplay rule or a guest preference."""
        if not self.host_edit() or not isinstance(c.get('drop'), bool):
            return
        self.cfg['drop_load_failures'] = c['drop']
        self.lobby.room['drop_load_failures'] = c['drop']
        self.save_settings()
        self.lobby.bump()
        self.broadcast()

    def keep_rules(self):
        """The host's rules become the next online match's defaults (never fighters or the stage)."""
        self.profile['rules'] = self.lobby.rules()
        self.save_profile()

    def cmd_rules(self, c):
        if not self.host_edit():
            return
        changes = {k: c[k] for k in ('stage', 'bgm', 'native', 'gameplay', 'services') if k in c}
        if not self.lobby.set_rules(changes, self.local['view'], ALLOWED_SERVICES):
            self.keep_rules()
        self.broadcast()

    def cmd_start_in(self, c):
        """Host: 'Start in' Menu (a versus match) or Hub (the in-level hub)."""
        if not self.host_edit():
            return
        found = self.lobby.set_type('hub' if c.get('value') == 'hub' else 'versus')
        if found:
            self.lobby.bump(dict(code='TTM-NET-29', key='notice.invalid_rule', args=dict(what=found[0])))
        else:
            self.keep_rules()
            self.engine_changed()
        self.broadcast()

    def cmd_mode(self, c):
        if not self.host_edit():
            return
        found = self.lobby.set_mode(c.get('mode'), self.local['view'])
        if found:
            self.lobby.bump(dict(code='TTM-NET-29', key='notice.invalid_rule', args=dict(what=found[0])))
        else:
            self.keep_rules()
            self.engine_changed()
        self.broadcast()

    def cmd_sizes(self, c):
        if not self.host_edit():
            return
        sizes = c.get('sizes')
        if isinstance(sizes, list) and len(sizes) == 2 and all(isinstance(n, int) for n in sizes):
            self.lobby.set_sizes(sizes, self.local['view'])
            self.engine_changed()
            self.broadcast()

    def cmd_random(self, c):
        """Host: random fighters for every CPU slot (or one slot: team/index)."""
        if not self.host_edit():
            return
        view = self.local['view']
        for t, team in enumerate(self.lobby.match['teams']):
            for i, f in enumerate(team):
                if c.get('team') is not None and (t, i) != (c.get('team'), c.get('index')):
                    continue
                if f.get('owner') is not None and c.get('team') is None:
                    continue
                ch, k = kit_spec.random_fighter(view)
                self.lobby.set_fighter(kit_lobby.HOST, t, i, ch, k, view)
        self.broadcast()

    def cmd_local(self, c):
        """This PC's own display settings (kept in its own profile; applied to its own copy of every match)."""
        values = dict(self.profile.get('local') or {})
        for key, value in (c.get('values') or {}).items():
            if key not in kit_settings.LOCAL:
                continue
            try:
                values[key] = kit_settings.coerce(key, value)
            except (TypeError, ValueError):
                continue
        self.profile['local'] = values
        self.save_profile()
        self.dirty = True

    def cmd_leave(self, c):
        self.say('Leaving.')
        if self.role == 'guest':
            self.send(type='BYE', why='leave')
            self.host_gone(None, said='You left the room.')
        elif self.role == 'host':
            self.close_room()

    def close_room(self):
        """Host: Leave = the room closes for everybody."""
        self.invalidate_preboot()
        if self.advertiser is not None:
            self.advertiser.close()
            self.advertiser = None
        self.room_key = None
        self.init_hub()
        self.send(type='BYE', why='closed')
        if self.session is not None:
            self.abort_game()
        self.leave_match_state()
        for ident in list(self.members):
            self.members[ident]['channel'].close_soon()
        self.members = {}
        for s in (self.listener, self.udp):
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass
        self.listener = self.udp = None
        self.lobby = None
        self.role = None
        self.me = None
        self.joinwith = None
        self.to_background()
        self.close_prep()
        self.prep = None
        self.set_phase('start')

    # ---- host: the match-making copy ----------------------------------------------------------------------------------------
    def host_language(self):
        return self.lang if self.lang in ('en', 'es') else 'en'

    def prep_problem(self, install, iso, disc):
        if os.name != 'nt':
            return ('why.linux', None)
        if not install:
            return ('why.no_install', None)
        if install.get('refused'):
            regions = install.get('refused_regions')
            return ('why.refused_code', regions) if regions else ('why.refused', None)
        if not install.get('python'):
            return ('why.no_python', None)
        other = install.get('iso')
        if not other or not Path(other).is_file():
            return ('why.no_iso', None)
        if Path(other).resolve() != Path(iso).resolve():
            try:
                theirs = kit_ident.disc_identity(other, full=False)
            except KitError:
                return ('why.iso_unreadable', None)
            if any(theirs.get(k) != disc.get(k) for k in ('elf_sha256', 'dbzp_sha256', 'afs_tables')):
                return ('why.other_iso', None)
        return None

    def setup_prep(self):
        why = self.local.get('prep_why')
        install = self.local.get('install')
        host = self.lobby.members[kit_lobby.HOST]
        if why:
            key, detail = why
            host['can_prepare'] = False
            self.lobby.warm = dict(state='refused' if key.startswith('why.refused') else 'none', eta_s=None,
                                   why_key=key, why=detail)
            self.say(f'This PC cannot make matches: {kit_text.t(key, "en", detail=detail or "")}.')
            return
        host['can_prepare'] = True
        if self.prep is None:
            slot = self.args.prep_pine_slot or self.args.pine_slot + 1
            self.prep = kit_prepare_auto.PrepCopy(install, self.local['iso'], slot, self.run_dir, say=self.say,
                                                  test=bool(self.args.test_hooks))
            self.prep.engine = self.wanted_engine()
            self.prep.progress = self.on_prep_progress
        self.say(f'Matches are made by this PC\'s Tag Team Mod {install["version"]} ({install["build"]} build), in a '
                 f'private copy on PINE {self.prep.slot}.')
        self.start_warm()

    def start_warm(self):
        if self.prep is None or any(self.busy(n) for n in ('warm', 'prep', 'prebuild')):
            return
        self.lobby.warm = dict(state='warming', eta_s=sum(kit_prepare_auto.ETA[k] for k in
                                                        kit_prepare_auto.WARM_STEPS), why=None)
        self.dirty = True
        self.job('warm', self.warm_job, then=self.warmed, fail=self.warm_failed)

    def warm_job(self):
        kit_match.ensure_elf(self.local['iso'])
        return self.prep.warm()

    def warmed(self, _):
        self.sync_warm(force=True)
        if self.phase in ('loading', 'fight', 'results') and self.prep is not None and self.prep.state == 'warm' and \
                not any(self.busy(n) for n in ('prep', 'prebuild', 'suspend')):
            self.job('suspend', self.prep.suspend, then=self.prep_suspended, fail=lambda e: None)

    def rewarm_if_cold(self):
        if self.role == 'host' and self.prep is not None and self.prep.state == 'cold' and self.lobby is not None \
                and self.phase == 'lobby' and not any(self.busy(n) for n in ('warm', 'prep', 'prebuild')):
            self.start_warm()

    def warm_failed(self, error):
        if isinstance(error, kit_prepare_auto.Cancelled):
            self.sync_warm(force=True)
            return
        text = error.values.get('what') if isinstance(error, KitError) else str(error)
        self.say(f'The match-making copy could not get ready: {text}')
        if self.lobby:
            self.lobby.warm = dict(state='failed', eta_s=None, why=str(text)[:160])
            self.lobby.bump(self.lobby.notice)
            self.broadcast()

    def sync_warm(self, force=False):
        if not self.lobby or self.prep is None:
            return
        state = self.prep.state
        if state in ('cold', 'warming') and self.busy('warm'):
            state = 'warming'
        old = self.lobby.warm or {}
        if force or old.get('state') != state:
            self.lobby.warm = dict(state=state, eta_s=None if state != 'warming' else old.get('eta_s'),
                                   why=self.prep.error if state == 'failed' else None)
            self.lobby.bump(self.lobby.notice)
            self.broadcast()

    def on_prep_progress(self, step, pct=None, eta_s=None):
        self.prep_progress = (step, pct, eta_s, time.time())

    def wanted_engine(self):
        """The engine mode the room's match needs (free-for-all and 1 v 1 run on the FFA engine)."""
        m = self.lobby.match if self.lobby else {}
        if m.get('mode') == 'ffa' or [len(t) for t in m.get('teams') or []] == [1, 1]:
            return 'ffa'
        return 'teams'

    def engine_changed(self):
        """The room's battle mode or sizes changed: re-warm the match-making copy in the other engine mode a few
        seconds later (so a Start does not have to restart it), unless it is busy."""
        self.engine_check_at = now() + 4.0

    def tick_engine(self):
        at = getattr(self, 'engine_check_at', None)
        if at is None or now() < at or self.role != 'host' or self.prep is None or self.phase != 'lobby':
            return
        self.engine_check_at = None
        want = self.wanted_engine()
        if self.prep.engine == want:
            return
        if any(self.busy(n) for n in ('warm', 'prep', 'prebuild', 'suspend')) or \
                self.prep.state not in ('warm', 'suspended', 'cold', 'failed'):
            self.engine_check_at = now() + 2.0                # busy (the first warm-up): look again soon
            return
        self.say(f'The room now needs the {want} engine: the match-making copy gets ready in that mode.')
        prep = self.prep

        def switch():
            kit_match.ensure_elf(self.local['iso'])
            return prep.switch_engine(want)
        self.lobby.warm = dict(state='warming', eta_s=sum(kit_prepare_auto.ETA[k] for k in kit_prepare_auto.WARM_STEPS),
                               why=None)
        self.dirty = True
        self.job('warm', switch, then=self.warmed, fail=self.warm_failed)

    def tick_prep(self):
        self.rewarm_if_cold()
        self.tick_engine()
        self.tick_prebuild()
        self.tick_prefetch()
        # Speculative preparation/reset has no committed-match callback, so
        # publish its real state here as well as through explicit warm jobs.
        self.sync_warm()
        # A completed capture is delivered before the hidden copy returns to
        # selection. Suspend it as soon as that background reset finishes.
        idle_ready = self.phase == 'lobby' and self.prefetch_meta is not None and \
            self._prefetch_meta_current(self.prefetch_meta)
        if self.role == 'host' and (self.phase in ('loading', 'fight', 'results') or idle_ready) and self.prep is not None and \
                self.prep.state == 'warm' and not any(self.busy(n) for n in ('warm', 'prep', 'prebuild', 'suspend')):
            self.job('suspend', self.prep.suspend, then=self.prep_suspended, fail=lambda e: None)
        p = self.prep_progress
        if self.role != 'host' or p is None or p is self.prep_sent:
            return
        t = now()
        if t - self.last_prep_sent < 0.5:
            return
        self.last_prep_sent = t
        self.prep_sent = p
        step, pct, eta, _ = p
        steps = kit_prepare_auto.WARM_STEPS + kit_prepare_auto.PREP_STEPS
        name = step.split('.', 1)[-1]
        left = None
        if name in steps:
            later = steps[steps.index(name) + 1:]
            if self.phase != 'preparing':
                later = [k for k in later if k in kit_prepare_auto.WARM_STEPS]
            left = round((eta if eta is not None else kit_prepare_auto.ETA.get(name, 0)) +
                         sum(kit_prepare_auto.ETA[k] for k in later))
        if self.phase == 'preparing':
            self.progress = dict(step=step, pct=int(pct or 0), eta_s=left, host=True)
            self.send(type='PROGRESS', step=step, pct=int(pct or 0), eta_s=left)
            self.dirty = True
        elif self.lobby and self.busy('warm') and t - self.last_warm_broadcast > 5:
            self.last_warm_broadcast = t
            self.lobby.warm = dict(state='warming', eta_s=left, why=None, step=step)
            self.lobby.bump(self.lobby.notice)
            self.broadcast()

    def prep_suspended(self, pids):
        if pids:
            self.say(f'The match-making copy is paused until it is needed ({len(pids)} processes).')
        self.sync_warm()

    def close_prep(self):
        self.cancel_prebuild(cancel_running=True)
        if self.prep is not None:
            self.prep.cancel.set()
            try:
                self.prep.close()
            except Exception:  # noqa: BLE001 - closing on the way out
                pass
            self.say('Closed the match-making copy.')

    def cmd_test_prep(self, c):
        """Test only (--test-hooks): options of the next preparation ({"ko": true}: team 2 starts nearly beaten)."""
        if self.args.test_hooks:
            self.test_prep = {'test_ko': True} if c.get('ko') else {}
            divisor = c.get('ko_divisor')
            if c.get('ko') and isinstance(divisor, int) and not isinstance(divisor, bool) and 2 <= divisor <= 64 and \
                    divisor != 8:
                self.test_prep['ko_divisor'] = divisor
            if c.get('bad_costume'):
                self.test_prep['bad_costume'] = True
            if c.get('leaders') and not c.get('ko'):
                self.test_prep['test_leaders'] = True
            if c.get('ki'):
                self.test_prep['test_ki'] = True
            self.say(f'TEST: preparation options {self.test_prep}')

    # ---- overlay ----------------------------------------------------------------------------------------------------------
    def show_overlay(self, key, **args):
        self.overlay = dict(show=True, key=key, args=args, since=time.time())
        self.dirty = True
        if self.emulator:
            self.emulator.flash()

    def overlay_args(self, **args):
        if self.overlay:
            self.overlay['args'].update(args)
            self.dirty = True

    def hide_overlay(self):
        if self.overlay is not None:
            self.overlay = None
            self.dirty = True

    # ---- shutdown -----------------------------------------------------------------------------------------------------------
    def shutdown(self, reason=''):
        self.invalidate_preboot()
        self.stop_prefetch_receive()
        self.stop_bot()
        if self.session is not None and self.session.result is None:
            try:
                self.session.say_bye()
            except OSError:
                pass
        if self.role == 'host':
            self.send(type='BYE', why='closed')
        elif self.net:
            self.send(type='BYE', why=reason or 'leave')
        for _, ch in self.channels():
            ch.close_soon(linger=1.0, block=True)
        if self.emulator is not None and self.emulator.pid:
            if self.emulator.stop():
                self.say('Closed the game window this session started.')
        self.close_prep()
        for s in (self.listener, self.udp):
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass
        if self.run_dir:
            self.summary['ended'] = time.strftime('%Y-%m-%d %H:%M:%S')
            self.write_summary()
        try:
            info = kit_ipc.read_info(kit_paths.DATA / 'session.json')
            if info and info.get('pid') == os.getpid():
                (kit_paths.DATA / 'session.json').unlink()
        except OSError:
            pass
        self.ipc.send('bye')
        self.ipc.close()


# messages only the host sends (a host ignores them from a guest)
HOST_ONLY = ('BULK', 'LOBBY', 'WELCOME', 'PREPARE', 'PROGRESS', 'PREP_FAILED', 'MATCH', 'GO', 'RESYNC', 'RESULT', 'VOTE_STATE',
             'RETRY', 'TO_LOBBY', 'JOINFIGHT', 'END_FIGHT', 'PREFETCH', 'PREFETCH_END', 'PREFETCH_ABORT')
