"""Deterministic native navigation of the host's private match-making copy (Oct 15 redesign): no host key messages.

Every step is a press of the guest pad (kit_inject: a fixed number of the game's own pad polls, so a press can never
be too short, too long or lost to window focus, whatever speed the copy runs at) followed by a confirmation read from
game memory; a press the game did not take (a menu still sliding in) is simply repeated. Each step has its own bound
and its own bilingual error (TTM-NET-23), so a failure names the step that failed.

  title()   logos/FMV (Start skips the movie) -> the title -> New Game -> "create a save file?" No -> "start a new game
            without saving?" Yes -> main menu (scene 4). The memory card is never written, so the format question of
            an unformatted card cannot appear; the kit's card is formatted as well.
  mode()    Select until the Modded Modes page is up (native_mode_menu state 2), then its semantic choice
            (PENDING_CHOICE, the path the Workbench quick launch uses) for Team Battle / Free-for-all, 1 Player ->
            Team Select (scene 0x28) and the watcher's structured mode receipt.
  picks()   one fighter per side (the cursor's, always unlocked) and END twice -> the map select (+0x3C6C == 1).
  confirm   (kit_prepare_auto.confirm) one accept at the written map select -> the native match starts (loop 1).
The guest pad is removed (native read restored, reservation zeroed) before any checkpoint is saved.
"""
import struct
import time

import kit_inject
from kit_codes import KitError

# title_word low half on the title and its dialogs (BT3 USA, live Oct 15; dialogs share the word's layout)
TITLE_IDLE, TITLE_BACK = 0x3802, 0x0501
CREATE_NO, NOSAVE_NO, NOSAVE_YES, FORMAT_NO = 0x0401, 0x0101, 0x0001, 0x6C01
STEP_ES = {'the title screen': 'la pantalla de título', 'the main menu': 'el menú principal',
           'the Modded Modes page': 'la página Modded Modes', 'Team Select': 'la selección de equipos',
           'the map select': 'la selección de escenario', 'the guest pad': 'el mando interno'}


class Step(KitError):
    pass


def step_error(what, detail='', seconds=None):
    when = f' in {seconds:.0f} s' if seconds else ''
    es = STEP_ES.get(what, what)
    return KitError('TTM-NET-23',
                    what=f'The host\'s match-making copy did not reach {what}{when}.' + (f' ({detail})' if detail else ''),
                    fix='Press Ready again: the kit rebuilds the copy once by itself.',
                    what_es=f'La copia del anfitrión para crear combates no llegó a {es}{when}.' +
                            (f' ({detail})' if detail else ''),
                    fix_es='Pulsa Listo otra vez: el kit reconstruye la copia una vez por sí solo.')


class GuestDrive:
    """Mixed into kit_prepare_auto.PrepCopy (uses its pine(), sample(), check(), obj_word(), watcher(), event())."""

    pad = None

    def buttons(self):
        """(accept, back) of the disc: the Japanese menus accept with Circle and go back with Cross."""
        from native_map import JPN
        return ('circle', 'cross') if JPN else ('cross', 'triangle')

    # ---- the guest pad -------------------------------------------------------------------------------------------
    def install_pad_patch(self):
        """The guest pad's pnach, in the PRIVATE copy's cheats folder only (PCSX2 loads every <serial>_<crc>*.pnach
        there; the installation and every client game never get it). Stale versions are replaced."""
        import kit_adapter
        from pathlib import Path
        import os
        profile = kit_adapter.profile(Path(self.install['root']))
        runtime = Path(self.base.dest) / 'game' / 'runtime28'
        cheats = (runtime if os.name == 'nt' else runtime / 'PCSX2') / 'cheats'   # the AppImage keeps its data there
        cheats.mkdir(parents=True, exist_ok=True)
        name = kit_inject.pnach_name(profile['serial'], profile['pcsx2_crc'])
        for old in cheats.glob('*' + kit_inject.PNACH_SUFFIX):
            if old.name != name:
                old.unlink()
        target = cheats / name
        data = kit_inject.pnach_text()
        if not target.is_file() or target.read_bytes() != data:
            import kit_prepare
            kit_prepare.independent_write(target, data)
        return target

    def install_pad(self, timeout=30.0):
        """Enable the guest pad once PCSX2's patch engine has placed it (kit_inject: the private copy's own pnach);
        proven live by its own poll counter."""
        self.pad = kit_inject.Injector(lambda: self.pine(5), check=self.check)
        try:
            self.pad.install(timeout=timeout)
        except kit_inject.PadUnavailable as error:
            raise step_error('the guest pad', str(error), timeout) from None
        except kit_inject.InjectError as error:
            raise KitError('TTM-NET-24', what=f"The host's game cannot take the private guest pad: {error}",
                           what_es=f'El juego del anfitrión no acepta el mando interno privado: {error}') from None
        if not self.pad.wait_polls(3, 15):
            raise step_error('the guest pad', 'its pad poll did not run', 15)
        self.event('guest pad installed', polls=self.pad.polls())
        return self.pad

    def remove_pad(self, client=None):
        """Disable the guest pad before any checkpoint; the export conversion removes its bytes from a match."""
        if self.pad is None:
            return
        try:
            self.pad.remove(client=client)
        except kit_inject.InjectError as error:
            raise step_error('the guest pad', str(error)) from None
        self.event('guest pad removed')

    def ensure_pad(self):
        if self.pad is None or not self.pad.installed:
            self.install_pad()
        return self.pad

    def tap(self, *names, hold=3, gap=4, client=None):
        self.check()
        try:
            pad = self.pad if client is not None else self.ensure_pad()
            return pad.press(*names, hold=hold, gap=gap, timeout=10.0, client=client)
        except kit_inject.InjectError as error:
            raise step_error('the guest pad', str(error)) from None

    def until(self, predicate, press, what, *, polls=45, tries=20, timeout=30.0):
        """Press until predicate(sample) holds, waiting up to `polls` game polls for its effect after each press."""
        end = time.monotonic() + timeout
        last = self.sample()
        for attempt in range(tries + 1):
            if predicate(last):
                return last, attempt
            if attempt == tries or time.monotonic() > end:
                break
            if press:
                self.tap(*press)
            start = self.pad.polls()
            while time.monotonic() < end:
                self.check()
                last = self.sample()
                if predicate(last) or (self.pad.polls() - start) & 0xFFFFFFFF >= polls:
                    break
                time.sleep(0.02)
        raise step_error(what, f'last {last}', timeout)

    def _read(self, address, size):
        for _ in range(20):
            try:
                with self.pine(3) as c:
                    return c.read(address, size)
            except kit_inject.transient_errors():
                time.sleep(0.05)
        raise step_error('the main menu', 'PINE did not answer')

    def _u32(self, address):
        return struct.unpack('<I', self._read(address, 4))[0]

    def wait_for(self, predicate, what, timeout):
        end = time.monotonic() + timeout
        last = None
        while time.monotonic() < end:
            self.check()
            last = self.sample()
            if predicate(last):
                return last
            time.sleep(0.01)
        raise step_error(what, f'last {last}', timeout)

    # ---- boot -> main menu -----------------------------------------------------------------------------------------
    def drive_title(self, timeout=45.0):
        """Power-on to the main menu without a memory-card write. Returns the seconds it took."""
        from native_map import PAL
        accept, _ = self.buttons()
        started = time.monotonic()
        end = started + timeout
        seen_title = False
        presses = []
        stuck_since, last_word = time.monotonic(), None
        while time.monotonic() < end:
            self.check()
            s = self.sample()
            if s['scene'] == 4:
                self.event('main menu reached', seconds=round(time.monotonic() - started, 2), presses=presses)
                return time.monotonic() - started
            word = s.get('title_word') or 0
            if word != last_word:
                last_word, stuck_since = word, time.monotonic()
            low = word & 0xFFFF
            if s['scene'] != 1:
                time.sleep(0.01)
                continue
            if word == 0x40703802 or (seen_title is False and low == TITLE_IDLE and (word >> 16) == 0x4070):
                seen_title = True
            if PAL and word == 0x001BA100:          # the European language chooser shares scene 1
                press = (accept,)
            elif not seen_title:
                press = ('start',)                  # logos and the opening movie (Start skips it)
            elif low in (TITLE_IDLE, TITLE_BACK, CREATE_NO, NOSAVE_YES):
                press = (accept,)
            elif low == NOSAVE_NO:
                press = ('left',)
            elif low == FORMAT_NO:
                self.event('format question', word=hex(word))
                press = (accept,)                   # No: the card stays untouched
            elif time.monotonic() - stuck_since > 1.0:
                self.event('unknown title word', word=hex(word))
                press = (accept,)
            else:
                time.sleep(0.01)
                continue
            presses.append(f'{word:#x}:{"+".join(press)}')
            self.tap(*press, hold=3, gap=6)
            # Let the dialog react before the next decision (its word changes within a few polls).
            start = self.pad.polls()
            while (self.pad.polls() - start) & 0xFFFFFFFF < 30 and time.monotonic() < end:
                cur = self.sample()
                if cur['scene'] == 4 or (cur.get('title_word') or 0) != word:
                    break
                time.sleep(0.02)
        raise step_error('the main menu', f'last {self.sample()}, presses {presses[-8:]}', timeout)

    # ---- main menu -> Team Select ----------------------------------------------------------------------------------
    def drive_mode(self, engine, timeout=40.0):
        import native_mode_menu as menu
        import kit_selector_cache
        from kit_prepare_auto import MAIN_MENU, TEAM_SELECT, PAGER, MAIN_OBJECT
        started = time.monotonic()
        # The watcher arms its pager on each main-menu arrival (state 1 -> 4); Select shows Modded Modes (state 2).
        menu_words = lambda: struct.unpack('<4I', self._read(menu.CONTROL, 16))
        for attempt in range(3):
            # The watcher arms its pager on each main-menu arrival (state 1 -> 4 with the stock result 6) and consumes
            # that result; only then is a Select (state 2, Modded Modes) and a semantic choice ours alone.
            self.wait_for(lambda x: x['scene'] == MAIN_MENU and x['pager'] and x['pager_state'] in (2, 4) and
                          x.get('main_object') == x.get('pager_owner') and bool(x.get('main_object')) and
                          menu_words()[3] == 0, 'the main menu', timeout)
            try:
                epoch = self.watcher().get('native_mode_receipt', {}).get('epoch')
            except AttributeError:
                epoch = None
            self.until(lambda x: x['scene'] == MAIN_MENU and x['pager_state'] == 2, ('select',),
                       'the Modded Modes page', polls=40, tries=25, timeout=timeout)
            choice = menu.SELECTIONS.index((engine, 1)) + 1
            self.pad.retry(lambda c: c.write(menu.CONTROL + menu.PENDING_CHOICE, struct.pack('<I', choice)), 10.0)
            self.event('mode requested', engine=engine, choice=choice, attempt=attempt)
            end = time.monotonic() + timeout
            left = None
            while time.monotonic() < end:
                self.check()
                x = self.sample()
                if x['scene'] == TEAM_SELECT and x['loop'] == 0:
                    break
                if x['scene'] == MAIN_MENU and x['pager_state'] == 4 and not self._u32(menu.CONTROL + menu.PENDING_CHOICE):
                    left = left or time.monotonic()
                    if time.monotonic() - left > 0.5:
                        break                       # the watcher reset its pager: request again
                else:
                    left = None
                time.sleep(0.01)
            if x['scene'] == TEAM_SELECT:
                break
            self.event('mode request dropped', last=x)
        else:
            raise step_error('Team Select', 'the mode request was dropped three times', timeout)
        s = x
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.check()
            status = self.watcher()
            if kit_selector_cache.mode_receipt(status, engine, after=epoch if isinstance(epoch, int) else -1):
                self.engine = engine
                self.event('mode committed', engine=engine, seconds=round(time.monotonic() - started, 2))
                return s
            time.sleep(0.02)
        raise step_error('Team Select', f'no {engine} mode receipt from the private watcher', timeout)

    # ---- Team Select -> map select --------------------------------------------------------------------------------
    def drive_picks(self, timeout=40.0):
        accept, _ = self.buttons()
        if self.at_map_select():
            return
        started = time.monotonic()
        word = lambda off, side=None: self.obj_word(off, side)
        for side in (0, 1):
            self.until(lambda _s, side=side: (word(0x134, side) or 0) >= 1, (accept,), 'Team Select',
                       polls=40, tries=25, timeout=timeout)
            self.until(lambda _s, side=side: word(0x12C, side) == 5, ('right',), 'Team Select',
                       polls=20, tries=16, timeout=timeout)
            if side == 0:
                self.until(lambda _s: word(0x13C, 0) == 8, (accept,), 'Team Select', polls=40, tries=10,
                           timeout=timeout)
            else:
                self.until(lambda _s: word(0x3C6C) == 1, (accept,), 'the map select', polls=40, tries=10,
                           timeout=timeout)
        self.event('map select', seconds=round(time.monotonic() - started, 2))
