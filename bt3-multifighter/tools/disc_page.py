"""Mod settings > Game disc: the desktop page (Tk) that chooses which game ISO Play starts.

A thin client of disc_library.py, which it runs as a child process (JSON lines): the window never hashes, extracts or
imports the game's addresses itself, so it keeps working while the chosen disc is damaged. DiscPageModel holds what the
page shows for a status event without Tk (tests use it). Actions apply at once; the window's Save and Cancel are for
the other pages. Only the desktop window has this page: the in-game settings pages are unchanged.
"""
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

from localization import tr, entries

TOOLS = Path(__file__).resolve().parent
WINDOWS = os.name == 'nt'
PAGE = 'Game disc'
HELP = ('Choose which of your game ISOs {play} starts. This installation runs {family}; a disc of the other game needs '
        'its own installation. A switch applies the next time you start {play} and is refused while {play} or this '
        "installation's PCSX2 is open. Each disc keeps its own fighter names, portraits and expanded maps, so switching "
        'back is immediate. Changes on this page apply at once; Save and Cancel are for the other pages.')
DEVELOPER = ('This developer folder always starts the ISO in its games folder; the game disc can be changed only in a '
             'player installation.')
STATUSES = {'active': 'In use', 'ready': 'Ready', 'missing': 'ISO missing', 'damaged': 'Files damaged',
            'unknown': 'Drive not answering'}
INSTALLED = '{status} (installed disc)'
STARTS = 'The disc {play} starts:'
LIST = 'Discs added to this installation'
# Column widths fit the window's minimum size (860 px): wider windows stretch the disc and ISO columns. There is no
# Serial column: every disc title ends with its serial, and the summary names it. The Status column fits the widest
# state a row can have in both languages ('En uso / Archivos dañados (disco instalado)', 230 px in Segoe UI 9).
COLUMNS = (('disc', 'Disc', 235), ('status', 'Status', 240), ('iso', 'ISO location', 65))
WRAP = 500   # the text labels' first wrap width; they follow the page's width once it is shown
BUTTONS = ('Add ISO…', 'Use this disc', 'Find ISO…', 'Remove from list', 'Delete expanded maps')
PROGRESS = {'status': 'Reading the game discs…', 'identify': 'Checking the chosen file…',
            'hash': 'Checking the game ISO: {percent}%', 'fighters': 'Checking fighter resources: {done}/{total}',
            'stages': 'Checking stage resources: {done}/{total}', 'extract': 'Extracting fighter names and portraits…',
            'verify': 'Checking the mod with this disc…', 'switch': 'Switching to {disc}…', 'delete': 'Deleting…'}
CONFIRM_USE = ('Use {disc} from now on? It applies the next time you start {play}. Your mod settings and memory cards '
               'stay as they are.')
CONFIRM_LANGUAGE = "This disc's game text is in Spanish. Show the mod's menus and messages in Spanish too?"
CONFIRM_REMOVE = ('Remove {disc} from this list? Its extracted names and portraits are deleted; the ISO itself is not '
                  'touched. You can add it again at any time.')
CONFIRM_REMOVE_MAPS = 'Also delete its expanded-map ISO ({size})?'
CONFIRM_MAPS = 'Delete the expanded maps of {disc} ({size})? You can build them again with {build_expanded_maps}.'
CONFIRM_MODIFIED = 'Add this disc anyway? Expanded maps are never built from it.'
CONFIRM_ORPHANS = 'Delete {size} of expanded maps that belong to discs no longer in the list?'
ORPHANS = 'Expanded maps of discs no longer in the list use {size}.'
DELETE_ORPHANS = 'Delete them'
CHOOSE_ADD = 'Choose a game ISO to add'
CHOOSE_FIND = 'Choose the ISO of {disc}'
FILE_TYPE = 'PlayStation 2 disc image'
ALL_FILES = 'All files'
# The page's own button stops the running action; it is never called Cancel, which is the window's (closes it).
STOP = 'Stop'
CANCELLED = 'Stopped.'
USE_HINT = 'Press Use this disc to play it.'
RUNNING = '{play} or its PCSX2 is open: close PCSX2 to switch discs.'
UNREADABLE = 'The game discs could not be read.'
# disc_library.py ended without saying why (it could not start its own code, or it crashed): its error output is shown
# as the details and kept in ERROR_LOG under the game folder.
FAILED = 'The game disc could not be changed because of an unexpected error.'
ERROR_LOG = Path('analysis')/'autopilot'/'game-disc-errors.log'
STDERR_KEEP = 4000
EUROPEAN_NOTE = 'European disc (SLES-54945): the game runs at 50 Hz, like the original European release.'
JAPANESE_NOTE = ('Japanese disc (SLPS-25815, Sparking! Meteor): its menus confirm with Circle and go back with Cross; the '
                 'game text and voices are Japanese, the fighter names in the mod are English.')
DISC_NOTES = {'bt3-pal': EUROPEAN_NOTE, 'bt3-jpn': JAPANESE_NOTE}
EXPERIMENTAL = 'Budokai Tenkaichi 4 support is experimental in this release.'


def size_text(size):
    size = float(size or 0)
    for unit, scale in (('GB', 1e9), ('MB', 1e6), ('KB', 1e3)):
        if size >= scale:
            return f'{size / scale:.1f} {unit}' if unit == 'GB' else f'{size / scale:.0f} {unit}'
    return f'{int(size)} B'


class DiscPageModel:
    """The page's content for one status event of disc_library.py (no Tk)."""

    def __init__(self, status=None, settings=None):
        self.status = status or {}
        self.settings = settings
        self.busy = False

    @property
    def developer(self):
        return bool((self.status.get('installation') or {}).get('developer'))

    @property
    def rows(self):
        return list(self.status.get('discs') or [])

    def row(self, key):
        return next((row for row in self.rows if row.get('key') == key), None)

    def current(self):
        return next((row for row in self.rows if row.get('active')), None)

    def state(self, row):
        if row.get('active') and row.get('files') == 'ok':
            return 'active'
        if row.get('files') != 'ok':
            return 'damaged'
        if row.get('iso_present') is False:
            return 'missing'
        if row.get('iso_present') is None:
            return 'unknown'
        return 'ready'

    def status_text(self, row):
        text = tr(STATUSES[self.state(row)], self.settings)
        if row.get('active') and self.state(row) != 'active':
            text = tr(STATUSES['active'], self.settings) + ' / ' + text
        return tr(INSTALLED, self.settings, status=text) if row.get('installed') else text

    def table(self):
        """(key, disc, status, ISO location) per row: the installed disc first, then as added."""
        return [(row['key'], row.get('title') or row['key'], self.status_text(row), row.get('iso') or '')
                for row in self.rows]

    def running(self):
        return self.status.get('running') is not None

    def enabled(self, key=None):
        """Which buttons can be pressed with row `key` selected."""
        row = self.row(key) if key else None
        idle = not self.busy and not self.developer and bool(self.status)
        state = self.state(row) if row else None
        # The installed disc can always be chosen again (its files belong to the installation, and Play offers to find
        # its ISO when it moved): that is the repair TTM-PLAY-46 and TTM-DISC-29 describe.
        usable = state in ('ready', 'unknown') or bool(row and row.get('installed') and row.get('files') == 'ok')
        return {
            'Add ISO…': idle,
            # A switch is refused while Play or this installation's PCSX2 is open (TTM-DISC-20): not offered then.
            'Use this disc': bool(idle and row and not row.get('active') and usable and not self.running()),
            'Find ISO…': bool(idle and row and row.get('files') == 'ok' and state in ('missing', 'unknown') and
                              not (row.get('active') and self.running())),
            'Remove from list': bool(idle and row and not row.get('active') and not row.get('installed')),
            'Delete expanded maps': bool(idle and row and row.get('expanded_maps_built') and not self.running()),
        }

    def summary(self):
        """The lines under 'The disc Play starts:'."""
        if self.developer:
            return [tr(DEVELOPER, self.settings)]
        row = self.current()
        if row is None:
            return []
        lines = [row.get('title') or row['key'],
                 '     '.join(part for part in (tr('Region: {region}', self.settings, region=row.get('region'))
                                                if row.get('region') else '',
                                                tr('Serial: {serial}', self.settings, serial=row.get('serial'))
                                                if row.get('serial') else '') if part),
                 tr('ISO: {path}', self.settings, path=row.get('iso') or '')]
        if row.get('adapter') in DISC_NOTES:
            lines.append(tr(DISC_NOTES[row['adapter']], self.settings))
        return [line for line in lines if line]

    def problems(self):
        lines = [f'[{p.get("code")}] {p.get("what")} {p.get("fix")}'.strip() for p in self.status.get('problems') or []]
        if self.running():
            lines.append(tr(RUNNING, self.settings, **entries()))
        return lines

    def orphans(self):
        return list(self.status.get('orphans') or [])

    def help(self):
        family = (self.status.get('installation') or {}).get('family_title') or ''
        text = tr(HELP, self.settings, family=family, **entries())
        if (self.status.get('installation') or {}).get('experimental'):
            text += ' ' + tr(EXPERIMENTAL, self.settings)
        return text


class Runner:
    """disc_library.py in a child process: its JSON events arrive through a queue the page polls (Tk is not
    thread-safe). kill() ends the child and its own check child."""

    def __init__(self, tools=TOOLS, python=None):
        self.tools, self.python = Path(tools), python or sys.executable
        self.process = None
        self.arguments = ()
        self.events = queue.Queue()

    def start(self, *arguments):
        env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
        for name in ('TAGTEAM_ADAPTER', 'TAGTEAM_DISC'):
            env.pop(name, None)
        options = dict(cwd=str(self.tools.parent), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
        if WINDOWS:
            options['creationflags'] = subprocess.CREATE_NO_WINDOW
        self.arguments = tuple(map(str, arguments))
        self.process = subprocess.Popen([self.python, '-u', str(self.tools/'disc_library.py'), *self.arguments,
                                         '--json'], **options)
        process = self.process
        errors = []
        reader = threading.Thread(target=self._errors, args=(process, errors), daemon=True)
        reader.start()
        threading.Thread(target=self._read, args=(process, reader, errors), daemon=True).start()

    @staticmethod
    def _errors(process, errors):
        """The child's error output (a traceback when it could not even report an event), last STDERR_KEEP chars."""
        for raw in process.stderr:
            errors.append(raw.decode('utf-8', 'replace'))
            while len(errors) > 1 and sum(map(len, errors)) > STDERR_KEEP:
                errors.pop(0)

    def _read(self, process, reader=None, errors=()):
        events = 0
        for raw in process.stdout:
            try:
                event = json.loads(raw.decode('utf-8', 'replace'))
            except ValueError:
                continue
            if isinstance(event, dict):
                events += 1
                self.events.put(event)
        code = process.wait()
        if reader is not None:
            reader.join(5)
        for stream in (process.stdout, process.stderr if reader is None or not reader.is_alive() else None):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass
        stderr = ''.join(errors)[-STDERR_KEEP:].strip()
        if code not in (0, None) and stderr:
            self.log(code, stderr)
        self.events.put(dict(event='exit', code=code, stderr=stderr, events=events))

    def log(self, code, stderr):
        """Keep a failed child's error output in game/analysis/autopilot/game-disc-errors.log (best effort)."""
        try:
            path = self.tools.parent/ERROR_LOG
            path.parent.mkdir(parents=True, exist_ok=True)
            import time
            with open(path, 'a', encoding='utf-8') as stream:
                stream.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} disc_library.py {" ".join(self.arguments)} '
                             f'(exit {code})\n{stderr}\n\n')
        except OSError:
            pass

    def running(self):
        return self.process is not None and self.process.poll() is None

    def kill(self):
        process = self.process
        if process is None or process.poll() is not None:
            return
        try:
            import psutil
            for child in psutil.Process(process.pid).children(recursive=True):
                try:
                    child.kill()
                except psutil.Error:
                    pass
        except Exception:  # noqa: BLE001 - psutil missing: the child itself below
            pass
        try:
            process.kill()
        except OSError:
            pass


class DiscPage:
    """The Game disc page inside the Mod settings window."""

    def __init__(self, page, window, settings=None, on_language=None, runner=None):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.page, self.window, self.settings = page, window, settings
        self.on_language = on_language
        self.runner = runner or Runner()
        self.model = DiscPageModel(settings=settings)
        self.loaded = False
        self.pending = None
        self.names = entries()
        L = lambda text, **values: tr(text, settings, **values)
        self.L = L
        page.columnconfigure(0, weight=1)
        ttk.Label(page, text=L(STARTS, **self.names), font=('Segoe UI', 10, 'bold')).grid(row=1, column=0, sticky='w')
        self.summary = tk.StringVar(value='')
        # The text labels wrap to the page's width (rewrap), so a switch's notes and the help fit a 940x660 window.
        self.wrapped, self.wrap_width = [], None
        label = ttk.Label(page, textvariable=self.summary, wraplength=WRAP, justify='left')
        label.grid(row=2, column=0, sticky='w', padx=(16, 0), pady=(2, 8))
        self.wrapped.append(label)
        self.problem = tk.StringVar(value='')
        # A red line for a damaged choice; it takes no room while there is none.
        self.problem_label = ttk.Label(page, textvariable=self.problem, wraplength=WRAP, foreground='#b00020',
                                       justify='left')
        self.problem_label.grid(row=3, column=0, sticky='w', pady=(0, 8))
        self.problem_label.grid_remove()
        self.wrapped.append(self.problem_label)
        ttk.Label(page, text=L(LIST), font=('Segoe UI', 10, 'bold')).grid(row=4, column=0, sticky='w', pady=(8, 2))
        frame = ttk.Frame(page)
        frame.grid(row=5, column=0, sticky='nsew')
        frame.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, columns=[name for name, _, _ in COLUMNS], show='headings', height=5,
                                 selectmode='browse')
        for name, heading, width in COLUMNS:
            self.tree.heading(name, text=L(heading))
            self.tree.column(name, width=width, stretch=name in ('disc', 'iso'))
        self.tree.grid(row=0, column=0, sticky='ew')
        scroll = ttk.Scrollbar(frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(xscrollcommand=scroll.set)
        scroll.grid(row=1, column=0, sticky='ew')
        # The selected disc's whole ISO path (the column is narrow at the window's minimum size).
        self.detail = tk.StringVar(value='')
        label = ttk.Label(frame, textvariable=self.detail, wraplength=WRAP, justify='left')
        label.grid(row=2, column=0, sticky='w')
        self.wrapped.append(label)
        self.tree.bind('<<TreeviewSelect>>', lambda _: self.refresh_buttons())
        bar = ttk.Frame(page)
        bar.grid(row=6, column=0, sticky='w', pady=(8, 0))
        actions = {'Add ISO…': self.add, 'Use this disc': self.use, 'Find ISO…': self.find,
                   'Remove from list': self.remove, 'Delete expanded maps': self.delete_maps}
        self.buttons = {}
        for index, name in enumerate(BUTTONS):
            button = ttk.Button(bar, text=L(name), command=actions[name])
            button.grid(row=index // 3, column=index % 3, sticky='ew', padx=(0, 6), pady=(0, 4))
            self.buttons[name] = button
        work = ttk.Frame(page)
        work.grid(row=7, column=0, sticky='ew', pady=(8, 0))
        work.columnconfigure(1, weight=1)
        self.bar = ttk.Progressbar(work, length=160, mode='determinate', maximum=100)
        self.bar.grid(row=0, column=0, sticky='w')
        self.progress = tk.StringVar(value='')
        ttk.Label(work, textvariable=self.progress).grid(row=0, column=1, sticky='w', padx=8)
        self.cancel_button = ttk.Button(work, text=L(STOP), command=self.cancel)
        self.cancel_button.grid(row=0, column=2, sticky='e')
        self.result = tk.StringVar(value='')
        label = ttk.Label(page, textvariable=self.result, wraplength=WRAP, justify='left')
        label.grid(row=8, column=0, sticky='w', pady=(8, 0))
        self.wrapped.append(label)
        # Shown only while there are expanded maps of removed discs (an empty row would still take its padding).
        self.orphan_row = orphans = ttk.Frame(page)
        orphans.grid(row=9, column=0, sticky='w', pady=(6, 0))
        orphans.grid_remove()
        self.orphan_text = tk.StringVar(value='')
        ttk.Label(orphans, textvariable=self.orphan_text).pack(side='left')
        self.orphan_button = ttk.Button(orphans, text=L(DELETE_ORPHANS), command=self.delete_orphans)
        # Empty until the first status names this installation's game (the help has its name in the middle).
        self.help = tk.StringVar(value='')
        self.footer = ttk.Label(page, textvariable=self.help, wraplength=560, foreground='#555555')
        self.footer.grid(row=10, column=0, sticky='w', pady=(18, 8))
        self.select_after = None
        page.bind('<Destroy>', lambda event: self.runner.kill() if event.widget is page else None)
        # add='+': the Mod settings window binds the page's <Configure> for its scroll region.
        page.bind('<Configure>', self.rewrap, add='+')
        self.refresh_buttons()

    # -- state

    def rewrap(self, event):
        """The text labels follow the page's width (the window's footers do the same, mod_settings.fit)."""
        width = max(300, event.width - 40)
        if width != self.wrap_width:
            self.wrap_width = width
            for label in self.wrapped:
                label.configure(wraplength=width)

    def selected(self):
        chosen = self.tree.selection()
        return chosen[0] if chosen else None

    def refresh_buttons(self):
        row = self.model.row(self.selected()) if self.selected() else None
        self.detail.set(self.L('ISO: {path}', path=row['iso']) if row and row.get('iso') else '')
        enabled = self.model.enabled(self.selected())
        for name, button in self.buttons.items():
            button.state(['!disabled'] if enabled[name] else ['disabled'])
        self.cancel_button.state(['!disabled'] if self.model.busy else ['disabled'])

    def show_status(self, status):
        self.model = DiscPageModel(status, self.settings)
        self.loaded = True
        chosen = self.selected()
        self.tree.delete(*self.tree.get_children())
        for key, disc, text, iso in self.model.table():
            self.tree.insert('', 'end', iid=key, values=(disc, text, iso))
        # A disc just added is selected, so Use this disc is one press away.
        chosen, self.select_after = self.select_after or chosen, None
        if chosen and self.tree.exists(chosen):
            self.tree.selection_set(chosen)
            self.tree.see(chosen)
        self.summary.set('\n'.join(self.model.summary()))
        self.problem.set('\n'.join(self.model.problems()))
        if self.model.problems():
            self.problem_label.grid()
        else:
            self.problem_label.grid_remove()
        orphans = self.model.orphans()
        if orphans:
            self.orphan_text.set(self.L(ORPHANS, size=size_text(sum(o.get('bytes', 0) for o in orphans))))
            self.orphan_button.pack(side='left', padx=8)
            self.orphan_row.grid()
        else:
            self.orphan_text.set('')
            self.orphan_button.pack_forget()
            self.orphan_row.grid_remove()
        self.help.set(self.model.help())
        self.refresh_buttons()

    def shown(self):
        """The page became visible: read the discs the first time (never while building the window)."""
        if not self.loaded and not self.model.busy:
            # --verify re-hashes each added disc's files (a few MB each), so a damaged one shows as such.
            self.run('status', '--verify', on_done=None)

    # -- running the backend

    def run(self, *arguments, on_done=None):
        self.model.busy = True
        self.pending = (arguments, on_done)
        if arguments[0] != 'status':
            # The previous action's line (and a selection it left pending) would read as this one's outcome; the
            # re-read after it keeps its result.
            self.result.set('')
            self.select_after = None
        self.bar.configure(mode='indeterminate')
        self.bar.start(12)
        self.progress.set(self.L(PROGRESS['status' if arguments[0] == 'status' else 'identify']))
        self.refresh_buttons()
        try:
            self.runner.start(*arguments)
        except OSError as error:
            self.finish()
            self.error(dict(what=self.L(UNREADABLE), details=str(error), block=[]))
            return
        self.window.after(100, self.poll)

    def poll(self):
        events = []
        while True:
            try:
                events.append(self.runner.events.get_nowait())
            except queue.Empty:
                break
        for event in events:
            self.handle(event)
            if event.get('event') == 'exit':
                return
        if self.model.busy:
            self.window.after(100, self.poll)

    def handle(self, event):
        kind = event.get('event')
        if kind == 'progress':
            self.show_progress(event)
        elif kind == 'status':
            self.show_status(event)
        elif kind == 'result':
            self.last_result = event
        elif kind == 'error':
            self.last_error = event
        elif kind == 'exit':
            arguments, on_done = self.pending or ((), None)
            result, error = getattr(self, 'last_result', None), getattr(self, 'last_error', None)
            cancelled, self.cancelled = getattr(self, 'cancelled', False), False
            self.last_result = self.last_error = None
            self.finish()
            handled = False
            if error is None and result is None and event.get('code') not in (0, None) and not cancelled:
                # disc_library.py ended without an event: it could not start its own code, or crashed before it could
                # explain. Never "Cancelled." (nobody cancelled) and never silence.
                import player_errors
                status = bool(arguments) and arguments[0] == 'status'
                error = dict(what=self.L(UNREADABLE if status else FAILED),
                             fix=self.L(player_errors.DISC_ACTION, **self.names),
                             details=event.get('stderr') or f'exit {event.get("code")}')
                if status:
                    self.problem.set(f'{error["what"]} {error["fix"]}')
                    self.problem_label.grid()
            if error is not None:
                handled = bool(on_done is not None and on_done(None, error))
                if not handled:
                    self.error(error)
                    if error.get('added'):
                        self.result.set(error['added'].get('message') or '')
            elif result is not None:
                # The summary above already carries a European or Japanese disc's note.
                european = {tr(note, language) for note in DISC_NOTES.values() for language in ('en', 'es')}
                notes = [note for note in result.get('notes') or [] if note not in european]
                lines = [result.get('message')] + notes + list(result.get('warnings') or [])
                if result.get('action') == 'add' and result.get('key') and not (result.get('disc') or {}).get('active'):
                    self.select_after = result['key']
                    lines.append(self.L(USE_HINT))
                self.result.set('\n'.join(line for line in lines if line))
                handled = bool(on_done is not None and on_done(result, None))
            elif arguments and arguments[0] != 'status' and event.get('code') not in (0, None):
                self.result.set(self.L(CANCELLED))
            # A chained action (on_done returned True) starts its own next step; anything else re-reads the discs.
            if arguments and arguments[0] != 'status' and not handled:
                self.run('status', '--verify')

    def show_progress(self, event):
        stage = event.get('stage')
        values = {k: v for k, v in event.items() if k not in ('event', 'stage', 'line', 'cached')}
        if stage == 'hash' and 'percent' in event:
            self.bar.stop()
            self.bar.configure(mode='determinate')
            self.bar['value'] = int(event.get('percent') or 0)
        elif stage in ('fighters', 'stages') and event.get('total'):
            self.bar.stop()
            self.bar.configure(mode='determinate')
            self.bar['value'] = int(100 * int(event.get('done') or 0) / int(event['total']))
        if stage in PROGRESS and 'line' not in event:
            try:
                self.progress.set(self.L(PROGRESS[stage], **values))
            except (KeyError, IndexError, ValueError):
                self.progress.set(self.L(PROGRESS['identify']))

    def finish(self):
        self.model.busy = False
        self.bar.stop()
        self.bar.configure(mode='determinate')
        self.bar['value'] = 0
        self.progress.set('')
        self.refresh_buttons()

    def error(self, event):
        from tkinter import messagebox
        lines = [event.get('what') or '']
        if event.get('why'):
            lines.append(event['why'])
        if event.get('fix'):
            lines.append(event['fix'])
        if event.get('file'):
            lines.append(str(event['file']))
        if event.get('details'):
            lines.append(str(event['details']))
        code = event.get('code')
        title = f'[{code}] ' + self.L(PAGE) if code else self.L(PAGE)
        messagebox.showerror(title, '\n\n'.join(line for line in lines if line), parent=self.window)

    def cancel(self):
        self.cancelled = True
        self.runner.kill()

    # -- actions

    def ask(self, text):
        from tkinter import messagebox
        return messagebox.askyesno(self.L(PAGE), text, parent=self.window)

    def choose(self, title, initial=None):
        from tkinter import filedialog
        types = [(self.L(FILE_TYPE), '*.iso *.ISO' if not WINDOWS else '*.iso'), (self.L(ALL_FILES), '*')]
        return filedialog.askopenfilename(parent=self.window, title=title, filetypes=types,
                                          initialdir=initial or None) or None

    def language_choice(self, row):
        """--match-language when the disc's game text is Spanish, the mod's is not, and the player agrees."""
        current = (self.settings or {}).get('language', 'en') if isinstance(self.settings, dict) else 'en'
        if row and row.get('native_language') == 'es' and current != 'es' and self.ask(self.L(CONFIRM_LANGUAGE)):
            return ['--match-language']
        return []

    def after_switch(self, result, error):
        if error is not None:
            return False
        for name, attribute in (('game_profile', 'pcsx2_crc'), ('character_names', 'character_table')):
            module = sys.modules.get(name)
            if module is not None:
                try:
                    getattr(module, attribute).cache_clear()
                except AttributeError:
                    pass
        if result.get('language') and self.on_language:
            self.on_language(result['language'])
        return False

    def add(self):
        # The dialog opens beside the chosen disc's ISO (the other discs are usually in the same folder).
        row = self.model.current() or next((row for row in self.model.rows if row.get('installed')), None)
        path = self.choose(self.L(CHOOSE_ADD), str(Path(row['iso']).parent) if row and row.get('iso') else None)
        if not path:
            return

        def done(result, error, path=path):
            if error is not None and error.get('code') == 'TTM-DISC-33':
                self.error(error)
                if self.ask(self.L(CONFIRM_MODIFIED)):
                    self.window.after(10, lambda: self.run('add', path, '--accept-modified-stages'))
                return True
            return False
        self.run('add', path, on_done=done)

    def use(self):
        row = self.model.row(self.selected())
        if row is None:
            return
        text = self.L(CONFIRM_USE, disc=row.get('title'), **self.names)
        if str(row.get('adapter') or '').startswith('bt4'):
            text += '\n\n' + self.L('Both BT4 discs use the same PCSX2 save-state names: load a save state only with '
                                    'the disc it was made with.')
        if not self.ask(text):
            return
        self.run('use', row['key'], *self.language_choice(row), on_done=self.after_switch)

    def find(self):
        row = self.model.row(self.selected())
        if row is None:
            return
        initial = str(Path(row['iso']).parent) if row.get('iso') else None
        path = self.choose(self.L(CHOOSE_FIND, disc=row.get('title')), initial)
        if path:
            self.run('find', row['key'], path)

    def remove(self):
        row = self.model.row(self.selected())
        if row is None or not self.ask(self.L(CONFIRM_REMOVE, disc=row.get('title') or row['key'])):
            return
        extra = []
        if row.get('expanded_maps_built') and self.ask(self.L(CONFIRM_REMOVE_MAPS, size=self.maps_size(row))):
            extra = ['--delete-expanded-maps']
        self.run('remove', row['key'], *extra)

    def maps_size(self, row):
        return size_text(row.get('maps_bytes') or 3e9)

    def delete_maps(self):
        row = self.model.row(self.selected())
        if row is None or not self.ask(self.L(CONFIRM_MAPS, disc=row.get('title'), size=self.maps_size(row),
                                              **self.names)):
            return
        self.run('delete-maps', row['key'])

    def delete_orphans(self):
        orphans = self.model.orphans()
        if not orphans or not self.ask(self.L(CONFIRM_ORPHANS, size=size_text(sum(o.get('bytes', 0)
                                                                                   for o in orphans)))):
            return
        keys = [o['key'] for o in orphans]

        def next_one(result=None, error=None):
            if error is not None or not keys:
                return False
            key = keys.pop(0)
            self.window.after(10, lambda: self.run('delete-maps', key, on_done=next_one))
            return True
        next_one()


def build(page, window, settings=None, on_language=None, runner=None):
    """The Game disc page in `page` (a ttk.Frame of the Mod settings window)."""
    return DiscPage(page, window, settings=settings, on_language=on_language, runner=runner)
