"""TTM Online Kit 2.0: Tag Team Mod battles online, one screen per player (delay-based lockstep over the internet or
a LAN; no video streaming).

"Play online.cmd" (Linux: "Play online.sh") opens the online LOBBY window. One PC hosts a room; anybody joins it with
the host's address and watches (a spectator) until they take a player slot. The host builds the match on the spot -
any fighters, colours, stage, music and rules - and presses Start when the players are Ready; every PC then plays it
from the intro on, one screen each. After the fight: Retry (every player agrees within 10 s) or Return to lobby.
These options are for troubleshooting, the README and the tests:

  --host / --join ADDRESS   skip the Start screen (host, or join that address)
  --name NAME               your lobby name (also changed in the lobby; never the PC's own name)
  --no-gui                  the console lobby (also used when tkinter is missing)
  --lang en|es              lobby language (default: the Start screen's switch, then Windows' language)
  --iso PATH --bios PATH    this PC's game ISO and BIOS (remembered)
  --install PATH            your Tag Team Mod folder (beta.35 to beta.42; the host makes its matches with it)
  --port N, --delay N, --renderer NAME, --keyboard, --fullscreen
  --stop                    close a PCSX2 an earlier run of this kit left open
Processes: the lobby window is the UI process; it starts the SESSION process (network, PINE, PCSX2) and talks to it
over 127.0.0.1 (kit_ipc). A lobby that crashes does not end a match: start "Play online" again and it re-attaches.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import kit_paths  # noqa: E402
import kit_ident  # noqa: E402
import kit_ipc  # noqa: E402
import kit_win  # noqa: E402

DEFAULT_PORT = 47400
DEFAULT_PINE = 28460
UI_ONLY = ('--no-gui', '--lobby-script', '--shot-dir', '--team', '--rules', '--auto-ready', '--auto-vote',
           '--new-session', '--ui-geometry')


def build_parser():
    import kit_match
    ap = argparse.ArgumentParser(prog='Play online.cmd', description=__doc__.split('\n\n')[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    role = ap.add_mutually_exclusive_group()
    role.add_argument('--host', action='store_true', help='open a room at once')
    role.add_argument('--join', nargs='?', const='', metavar='HOST[:PORT]', help='join this host\'s room at once')
    ap.add_argument('--port', type=int, help='TCP and UDP port of the host (default 47400)')
    ap.add_argument('--delay', type=int, help='input delay in updates of 33 ms (default: from the round trip)')
    ap.add_argument('--max-stall', type=int, default=kit_match.DEFAULT_MAX_STALL, help=argparse.SUPPRESS)
    ap.add_argument('--iso', help='your Dragon Ball Z Budokai Tenkaichi 3 (USA) ISO')
    ap.add_argument('--bios', help='your PlayStation 2 BIOS file')
    ap.add_argument('--install', help='your Tag Team Mod folder (only read; the host makes its matches with it)')
    ap.add_argument('--keyboard', action='store_true', help='play with the keyboard instead of controller 1')
    ap.add_argument('--pad', choices=('SDL-0', 'SDL-1', 'keyboard'), help=argparse.SUPPRESS)
    ap.add_argument('--fullscreen', action='store_true', help='start the game window in full screen')
    ap.add_argument('--renderer', choices=('default', 'auto', 'd3d11', 'opengl', 'software', 'vulkan', 'd3d12'),
                    help='graphics renderer of this PC (may differ between the PCs)')
    ap.add_argument('--pcsx2', metavar='APPIMAGE', help='Linux: your PCSX2 2.8.2 x64 AppImage (remembered)')
    ap.add_argument('--bios-check', choices=kit_ident.BIOS_POLICIES, default='note', help=argparse.SUPPRESS)
    ap.add_argument('--disc-check', choices=('full', 'quick'), default='full', help=argparse.SUPPRESS)
    ap.add_argument('--pine-slot', type=int, default=DEFAULT_PINE, help='PCSX2 PINE port of this kit (default 28460)')
    ap.add_argument('--timeout', type=float, default=60.0, help='seconds to wait for the other PC at each step')
    ap.add_argument('--name', default='', help='your name in the lobby')
    ap.add_argument('--lang', choices=('en', 'es'), help='lobby language')
    ap.add_argument('--no-gui', action='store_true', help='the console lobby instead of the window')
    ap.add_argument('--stop', action='store_true', help='close what an earlier run of this kit left open, then exit')
    ap.add_argument('--pause-key', choices=('pause', 'scrolllock'), default='pause', help=argparse.SUPPRESS)
    ap.add_argument('--audio', choices=('default', 'null'), help=argparse.SUPPRESS)
    test = ap.add_argument_group('test options')
    test.add_argument('--session', action='store_true', help=argparse.SUPPRESS)
    test.add_argument('--ui', choices=('tk', 'console'), help=argparse.SUPPRESS)
    test.add_argument('--new-session', action='store_true', help=argparse.SUPPRESS)
    test.add_argument('--latency', type=float, default=0.0, help='delay every datagram this PC sends by MS')
    test.add_argument('--jitter', type=float, default=0.0, help='random extra delay +- MS')
    test.add_argument('--loss', type=float, default=0.0, help='drop this share of the datagrams this PC sends')
    test.add_argument('--hidden', action='store_true', help='PCSX2 on a hidden desktop, keyboard pad, no sound')
    test.add_argument('--desktop', help=argparse.SUPPRESS)
    test.add_argument('--bots', type=int, metavar='SEED', help='a keyboard bot plays this PC\'s pad (with --hidden)')
    test.add_argument('--bot-profile', default='mash', help=argparse.SUPPRESS)
    test.add_argument('--hold-at', type=int, metavar='FRAME', help='hold the first fight at this frame for a '
                                                                   'screenshot (both PCs must use the same frame)')
    test.add_argument('--bind', default='0.0.0.0', help=argparse.SUPPRESS)
    test.add_argument('--send-rate', type=float, help=argparse.SUPPRESS)        # KB/s of file transfers
    test.add_argument('--test-hooks', action='store_true', help=argparse.SUPPRESS)
    test.add_argument('--no-ui-timeout', action='store_true', help=argparse.SUPPRESS)
    test.add_argument('--lobby-script', help='a JSON list of lobby steps (tests and bots)')
    test.add_argument('--shot-dir', help='where the lobby script\'s "shot" steps write the window pictures')
    test.add_argument('--team', help='bot: claim team T and play C colour K, e.g. "1 29:2"')
    test.add_argument('--rules', help=argparse.SUPPRESS)
    test.add_argument('--auto-ready', action='store_true', help='bot: press Ready whenever this PC plays a fighter')
    test.add_argument('--auto-vote', help='bot: retry|lobby[,N] after each fight (lobby after N fights)')
    test.add_argument('--ui-geometry', help=argparse.SUPPRESS)
    test.add_argument('--prep-pine-slot', type=int, help=argparse.SUPPRESS)
    test.add_argument('--prep-settle', type=float, default=1.0, help=argparse.SUPPRESS)
    test.add_argument('--prep-timeout', type=float, default=1800.0, help=argparse.SUPPRESS)
    return ap


# ---- small helpers ------------------------------------------------------------------------------------------------------
def processes_file():
    return kit_paths.DATA / 'processes.json'


def stop_leftovers(say):
    """Close a PCSX2 an earlier run of this kit left open (only if its program lies in this kit's pcsx2 folder)."""
    try:
        pid = json.loads(processes_file().read_text(encoding='utf-8')).get('pcsx2')
    except (OSError, ValueError):
        return []
    killed = []
    path = kit_win.process_path(pid).lower() if pid else ''
    if pid and kit_win.pid_alive(pid) and path.startswith(str(kit_paths.PCSX2).lower()):
        kit_win.kill_tree(pid)
        killed.append(pid)
        say(f'Closed the PCSX2 an earlier run of this kit left open (process {pid}).')
    try:
        processes_file().unlink()
    except OSError:
        pass
    return killed


def session_argv(argv):
    """The session process's command line: this kit's arguments without the UI-only ones."""
    out, skip = [], False
    takes_value = {'--lobby-script', '--shot-dir', '--team', '--rules', '--auto-vote', '--ui-geometry'}
    for item in argv:
        if skip:
            skip = False
            continue
        name = item.split('=', 1)[0]
        if name in UI_ONLY:
            skip = name in takes_value and '=' not in item
            continue
        out.append(item)
    return out


def start_session(argv, args, say):
    """Start the session process (or re-attach to a running one); returns (port, token, pid)."""
    info = kit_ipc.read_info(kit_paths.DATA / 'session.json')
    if info and not args.new_session and kit_win.pid_alive(info.get('pid')):
        say('Re-attaching to the running online session (process %s).' % info['pid'])
        return info['port'], info['token'], info['pid'], True
    token = kit_ipc.new_token()
    env = dict(os.environ)
    env[kit_ipc.TOKEN_ENV] = token
    kit_paths.DATA.mkdir(parents=True, exist_ok=True)
    out = open(kit_paths.DATA / 'session.out.txt', 'ab')
    command = [sys.executable, '-B', str(Path(__file__).resolve()), '--session',
               '--ui', 'console' if args.no_gui else 'tk'] + session_argv(argv)
    flags = 0x08000000 if os.name == 'nt' else 0                  # CREATE_NO_WINDOW: it lives on after the lobby
    proc = subprocess.Popen(command, cwd=str(kit_paths.KIT), env=env, stdin=subprocess.DEVNULL, stdout=out,
                            stderr=subprocess.STDOUT, creationflags=flags)
    end = time.time() + 30
    while time.time() < end:
        info = kit_ipc.read_info(kit_paths.DATA / 'session.json')
        if info and info.get('token') == token:
            return info['port'], token, proc.pid, False
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    raise SystemExit(f'The session process did not start (see {kit_paths.DATA / "session.out.txt"}).')


def session_main(args):
    import kit_controller
    token = os.environ.get(kit_ipc.TOKEN_ENV)
    if not token:
        raise SystemExit('the session process is started by the lobby (Play online.cmd)')
    os.environ.pop(kit_ipc.TOKEN_ENV, None)
    kit_paths.DATA.mkdir(parents=True, exist_ok=True)
    try:
        record = json.loads(processes_file().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        record = None
    if record and not kit_win.pid_alive(record.get('session')):
        stop_leftovers(print)                      # a PCSX2 whose session process died (crash) is closed
    ctl = kit_controller.Controller(args, token)
    kit_win.on_console_close(lambda: setattr(ctl, 'quit', True))
    return ctl.run()


def ui_main(argv, args):
    say = print
    port, token, pid, reattached = start_session(argv, args, say)
    client = kit_ipc.Client(port, token)

    def restart():
        """The lobby lost its session process (kit 2.0 has no rejoin: start Play online again)."""
        return None
    use_tk = not args.no_gui
    if use_tk:
        try:
            import tkinter  # noqa: F401
        except ImportError:
            import kit_text
            say(kit_text.t('tk.missing', args.lang or kit_win.ui_language()))
            use_tk = False
    if use_tk:
        import kit_lobby_ui
        return kit_lobby_ui.run(client, args, session_pid=pid, restart=restart)
    import kit_lobby_console
    return kit_lobby_console.run(client, args, session_pid=pid, restart=restart)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.session:
        return session_main(args)
    if args.stop:
        killed = stop_leftovers(print)
        print('Nothing to close.' if not killed else 'Done.')
        return 0
    return ui_main(argv, args)


if __name__ == '__main__':
    raise SystemExit(main())
