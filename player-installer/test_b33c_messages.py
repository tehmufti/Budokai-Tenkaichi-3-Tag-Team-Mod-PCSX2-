"""The installer message catalog (messages.json), its two renderers (setup_messages.py and install-player.ps1) and the
rule that every require() literal is a code or a translated key."""
import ast
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
import unittest.mock

import setup_messages as messages

HERE = Path(__file__).resolve().parent
CATALOG = json.loads((HERE/'messages.json').read_text(encoding='utf-8'))
TRANSLATIONS = json.loads((HERE/'installer-es.json').read_text(encoding='utf-8'))
FAMILIES = {'ZIP', 'OS', 'DEST', 'PY', 'PCSX2', 'BIOS', 'ISO', 'PAYLOAD', 'CHECK', 'PLAY'}
windows_only = unittest.skipUnless(os.name == 'nt', 'Windows PowerShell')


def ps_region():
    """install-player.ps1's functions (between #region/#endregion setup functions), for probes."""
    source = (HERE/'install-player.ps1').read_text(encoding='ascii')
    return source[source.index('#region setup functions'):source.index('#endregion setup functions')]


def run_ps(body, language='en', setup=HERE, env=None, timeout=120):
    """Run the setup functions plus body in Windows PowerShell 5.1; returns stdout (UTF-8)."""
    prelude = ("$ErrorActionPreference = 'Stop'\nSet-StrictMode -Version 2\n"
               "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)\n"
               f"$script:setupFolder = '{setup}'\n$script:messages = $null\n$script:translations = $null\n"
               f"$script:blockLanguage = '{language}'\n$script:failure = $null\n$script:cancelled = ''\n"
               f"$script:systemChanged = $false\n$Language = '{language}'\n")
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp)/'probe.ps1'
        # A BOM: Windows PowerShell 5.1 reads a BOM-less script as ANSI (probe bodies may hold accented test text).
        probe.write_bytes(b'\xef\xbb\xbf'+(prelude+ps_region()+'\n'+body+'\n').encode('utf-8'))
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(probe)],
                                capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL, env=dict(os.environ, **(env or {})))
    out = result.stdout.decode('utf-8', 'replace')
    if result.returncode != 0: raise AssertionError('PowerShell probe failed: '+out+result.stderr.decode('utf-8', 'replace'))
    return out


def ps_quote(text):
    return "'"+str(text).replace("'", "''")+"'"


def ps_value(value):
    if isinstance(value, dict): return '@{ '+'; '.join(f'{k} = {ps_value(v)}' for k, v in value.items())+' }'
    if value is None: return '$null'
    if isinstance(value, bool): return '$true' if value else '$false'
    if isinstance(value, (list, tuple)): return '@('+', '.join(ps_value(v) for v in value)+')'
    return ps_quote(value)


class CatalogTests(unittest.TestCase):
    def test_every_code_has_english_and_spanish_parts_with_the_same_placeholders(self):
        codes = CATALOG['codes']
        self.assertGreater(len(codes), 90)
        self.assertEqual(set(CATALOG['families']), FAMILIES)
        for code, row in codes.items():
            with self.subTest(code=code):
                match = re.fullmatch(r'TTM-([A-Z0-9]+)-(\d\d)', code)
                self.assertTrue(match); self.assertIn(match[1], FAMILIES)
                if match[1] == 'PLAY': self.assertTrue(50 <= int(match[2]) <= 59, 'installer PLAY codes are 50-59 only')
                self.assertIsInstance(row['unchanged'], bool)
                for part in ('what', 'why', 'fix'):
                    english, spanish = row['en'][part], row['es'][part]
                    self.assertTrue(english.strip() and spanish.strip())
                    self.assertEqual(sorted(re.findall(r'\{(\w+)\}', english)), sorted(re.findall(r'\{(\w+)\}', spanish)))
                    if '{reason}' not in english: self.assertNotEqual(english, spanish)
                    for text in (english, spanish):
                        self.assertNotRegex(text, r'Play\.cmd|Play\.sh|Check installation\.(cmd|sh)|any teams',
                                            'launcher names come from placeholders')
        self.assertNotIn('TTM-CHK-01', codes)

    def test_labels_are_ascii_and_the_python_fallback_matches_the_file(self):
        self.assertEqual(CATALOG['labels'], messages.LABELS)
        for language in ('en', 'es'):
            for value in CATALOG['labels'][language].values(): value.encode('ascii')
        self.assertEqual(CATALOG['families'], messages.FAMILIES)
        self.assertEqual(CATALOG['width'], messages.WIDTH)

    def test_exit_codes_follow_the_family(self):
        for code, expected in (('TTM-ZIP-01', 10), ('TTM-OS-02', 20), ('TTM-DEST-04', 30), ('TTM-PY-11', 40), ('TTM-PCSX2-03', 50),
                               ('TTM-BIOS-02', 60), ('TTM-ISO-06', 70), ('TTM-PAYLOAD-90', 80), ('TTM-CHECK-10', 90), ('TTM-PLAY-50', 2)):
            self.assertEqual(messages.exit_code(code), expected, code)


class RenderTests(unittest.TestCase):
    def test_the_block_has_the_code_first_the_labels_and_unwrapped_paths(self):
        path = r'C:\Users\Player\Some very long folder name\with spaces\and more\Downloads\SCPH1001.BIN'
        log = r'C:\Users\Player\AppData\Local\TagTeamMod\logs\setup-20260927-120000.log'
        for language, labels in (('en', messages.LABELS['en']), ('es', messages.LABELS['es'])):
            with self.subTest(language=language):
                block = messages.render('TTM-BIOS-02', language, file=path, log=log, detail='size 524288 bytes')
                lines = block.split('\n')
                self.assertEqual(lines[0], '='*78); self.assertEqual(lines[-1], '='*78)
                self.assertEqual(lines[1], f'[TTM-BIOS-02] {labels["setup"]}')
                for key in ('what', 'why', 'fix'): self.assertTrue(any(line.startswith(labels[key]+': ') for line in lines))
                self.assertIn(labels['unchanged'], lines); self.assertIn(labels['copy'], lines)
                self.assertIn('  '+path, lines); self.assertIn('  '+log, lines)
                self.assertIn(labels['file']+':', lines); self.assertIn(labels['log']+':', lines)
                self.assertIn(f'{labels["details"]}: size 524288 bytes', lines)
                for line in lines:
                    if line.strip() not in (path, log): self.assertLessEqual(len(line), 78, line)
        both = messages.render('TTM-ZIP-01', 'both', install='Install.cmd')
        self.assertIn('[TTM-ZIP-01] SETUP STOPPED / INSTALACION DETENIDA', both)
        self.assertLess(both.index('WHAT HAPPENED'), both.index('QUE HA PASADO'))
        self.assertIn('Nothing was changed.', both); self.assertIn('No se ha cambiado nada.', both)
        self.assertIn('Copy this block when asking for help. / Copia este bloque si pides ayuda.', both)
        # "Nothing was changed" only when true; a failure after the folder was created says nothing of the kind.
        self.assertNotIn('Nothing was changed.', messages.render('TTM-BIOS-02', 'en', unchanged=False))
        self.assertNotIn('Nothing was changed.', messages.render('TTM-PY-11', 'en'))
        self.assertIn('[TTM-CHECK-10] INSTALLATION CHECK FAILED', messages.render('TTM-CHECK-10', 'en', reason='x'))
        self.assertIn('[TTM-PLAY-50] CANNOT START', messages.render('TTM-PLAY-50', 'en', launcher='Play.cmd'))

    def test_translated_values_unknown_placeholders_and_ascii_folding(self):
        text = messages.render('TTM-ISO-08', 'es', reason=dict(en='English reason.', es='Motivo en espa\u00f1ol.'))
        self.assertIn('Motivo en espa\u00f1ol.', text); self.assertNotIn('English reason.', text)
        self.assertEqual(messages.fill('a {missing} b {name}', 'en', dict(name='x')), 'a ? b x')
        folded = messages.render('TTM-BIOS-02', 'es', ascii=True)
        folded.encode('ascii'); self.assertIn('Copia este bloque si pides ayuda.', folded)
        self.assertEqual(messages.fold('\u00bfInstalaci\u00f3n? \u00a1S\u00ed! \u00f1'), 'Instalacion? Si! n')

    def test_setup_failure_keeps_english_text_its_details_and_renders_either_language(self):
        failure = messages.SetupFailure('TTM-ISO-06', file='x.iso', size=100, expected=200, detail='view')
        self.assertEqual(str(failure), 'The game ISO is incomplete: the file has 100 bytes, but the disc says 200 bytes. (view)')
        self.assertIsInstance(failure, ValueError)
        self.assertEqual(failure.details(), dict(size='100', expected='200', file='x.iso', detail='view'))
        again = messages.SetupFailure.from_details('TTM-ISO-06', json.loads(json.dumps(failure.details())))
        self.assertEqual(again.render('es'), failure.render('es'))
        self.assertIn('La ISO del juego est\u00e1 incompleta', failure.render('es'))
        spanish = messages.SetupFailure('TTM-ISO-08', lang='es', reason=dict(en='E', es='S'))
        self.assertEqual(str(spanish), 'S')

    def test_write_status_is_ascii_json_with_the_code_and_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'install-status.json'
            messages.write_status(path, messages.SetupFailure('TTM-DEST-04', file='C:\\Games [PS2]\\Tag Team Mod'), failed_stage='x')
            raw = path.read_bytes(); raw.decode('ascii')
            data = json.loads(raw)
            self.assertEqual((data['ready'], data['stage'], data['error_code'], data['failed_stage']), (False, 'FAILED', 'TTM-DEST-04', 'x'))
            self.assertEqual(data['error_details']['file'], 'C:\\Games [PS2]\\Tag Team Mod')
            self.assertFalse(path.with_name(path.name+'.tmp').exists())

    def test_classify_names_disk_full_access_timeouts_and_unexpected_errors(self):
        import errno, subprocess as sp
        self.assertEqual(messages.classify(OSError(errno.ENOSPC, 'No space left', 'x')).code, 'TTM-OS-03')
        full = OSError(28, 'disk full'); full.winerror = 112
        self.assertEqual(messages.classify(full).code, 'TTM-OS-03')
        self.assertEqual(messages.classify(PermissionError(errno.EACCES, 'denied', 'f')).code, 'TTM-OS-04')
        self.assertEqual(messages.classify(sp.TimeoutExpired(['python', 'autopilot.py'], 180)).values['step'], 'autopilot.py')
        self.assertEqual(messages.classify(KeyError('identity')).code, 'TTM-PAYLOAD-90')
        self.assertIn("KeyError: 'identity'", messages.classify(KeyError('identity')).detail)
        reason = messages.classify(ValueError('Unsafe payload path'), translate=lambda t: TRANSLATIONS.get(t, t))
        self.assertEqual((reason.code, reason.values['reason']['es']), ('TTM-PAYLOAD-02', TRANSLATIONS['Unsafe payload path']))
        class Coded(ValueError):
            code = 'TTM-ISO-03'; details = dict(format='CSO', extension='cso')
        coded = messages.classify(Coded('cso'))
        self.assertEqual((coded.code, coded.values['format'], coded.detail), ('TTM-ISO-03', 'CSO', ''))
        # The library's own words (FormatError.cause) become DETAILS; a 'reason' in the details is never passed twice.
        damaged = Coded('damaged'); damaged.code = 'TTM-ISO-07'; damaged.details = dict(reason='x'); damaged.cause = 'PyCdlibInvalidISO: bad'
        coded = messages.classify(damaged)
        self.assertEqual((coded.code, coded.detail, coded.values['reason']), ('TTM-ISO-07', 'PyCdlibInvalidISO: bad', 'x'))

    def test_logs_go_to_the_local_state_folder_unless_overridden(self):
        with unittest.mock.patch.dict(os.environ, {'LOCALAPPDATA': r'C:\Users\P\AppData\Local', 'TAGTEAM_SETUP_LOGS': ''}):
            os.environ.pop('TAGTEAM_SETUP_LOGS')
            self.assertEqual(messages.log_directory(True), Path(r'C:\Users\P\AppData\Local')/'TagTeamMod'/'logs')
        with unittest.mock.patch.dict(os.environ, {'XDG_STATE_HOME': '/home/p/.local/state'}):
            os.environ.pop('TAGTEAM_SETUP_LOGS', None)
            self.assertEqual(messages.log_directory(False).as_posix(), '/home/p/.local/state/tagteammod/logs')
        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.dict(os.environ, {'TAGTEAM_SETUP_LOGS': tmp}):
            first, second = messages.new_log_path(), None
            first.write_text('x'); second = messages.new_log_path()
            self.assertEqual(first.parent, Path(tmp)); self.assertNotEqual(first, second)
            self.assertRegex(first.name, r'^setup-\d{8}-\d{6}\.log$')


class LiteralTests(unittest.TestCase):
    def test_every_require_literal_is_a_code_or_a_translated_key(self):
        """Amendment 2.13: a require() message is either a messages.json code or an installer-es.json key."""
        found = 0
        for name in ('install_player.py', 'check_installation.py'):
            tree = ast.parse((HERE/name).read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'require' and len(node.args) >= 2):
                    continue
                first = node.args[1]
                while isinstance(first, ast.BinOp): first = first.left
                if isinstance(first, ast.Name):  # a module constant: resolve it
                    module = __import__(name[:-3])
                    value = getattr(module, first.id)
                elif isinstance(first, ast.Constant) and isinstance(first.value, str): value = first.value
                else: self.fail(f'{name}:{node.lineno} require() message is not a literal')
                found += 1
                with self.subTest(file=name, line=node.lineno, message=value):
                    if re.fullmatch(r'TTM-[A-Z0-9]+-\d\d', value): self.assertIn(value, CATALOG['codes'])
                    else: self.assertIn(value.strip(), TRANSLATIONS)
        self.assertGreater(found, 50)

    def test_the_installers_spanish_keys_translate_every_new_line(self):
        for text in ('Checking your files before changing anything:', 'Installation folder:', 'Free space:',
                     'Install into the recommended folder?', 'Choose No to pick another folder.', 'Repaired. Open',
                     'Copy your memory cards and mod settings from the existing installation?',
                     'Repairing the private Python of an existing installation',
                     'Installing the Microsoft Visual C++ runtime required by PCSX2...',
                     'Copy your memory cards from the existing installation? (Its mod settings are for the other game and are not copied.)',
                     'Copied from the existing installation:',
                     'Not copied (already in the new installation, not valid for this version, or made for the other game):',
                     'Nothing was copied: the existing installation has no memory cards or mod settings to copy.',
                     'The existing installation cannot start its private Python, but it comes from another release: run the Install.cmd '
                     'of that release to repair it. This new installation goes beside it.'):
            with self.subTest(text=text):
                self.assertIn(text, TRANSLATIONS); self.assertNotEqual(TRANSLATIONS[text], text)
        import install_player
        self.assertIn(install_player.CANNOT_RUN, TRANSLATIONS)


@windows_only
class PowerShellRendererTests(unittest.TestCase):
    CASES = (
        ('TTM-BIOS-02', 'en', dict(file=r'C:\bios\SCPH1001.BIN', log=r'C:\logs\setup-1.log', detail='size 524288 bytes'), {}),
        ('TTM-BIOS-02', 'es', dict(file=r'C:\bios\SCPH1001.BIN', log=r'C:\logs\setup-1.log', detail=''), {}),
        ('TTM-ZIP-04', 'both', dict(file=None, log=None, detail='Installer checksum failed: setup/x.py'), dict(name='setup/x.py')),
        ('TTM-ISO-08', 'es', dict(file=r'D:\Juegos\Espa\u00f1a.iso', log='', detail=''),
         dict(reason=dict(en='English.', es='La ISO elegida es otra. Espa\u00f1ol con acentos: \u00e1\u00e9\u00ed\u00f3\u00fa.'))),
        ('TTM-PY-02', 'en', dict(file=None, log='', detail='WinGet exit -2147012889'),
         dict(winget='0x80072EE7', meaning=dict(en='no internet connection', es='sin conexion'))),
        ('TTM-DEST-02', 'es', dict(file=r'C:\a\b', log='', detail=''), dict(length=151)),
        ('TTM-CHECK-06', 'en', dict(file=[r'C:\one', r'C:\two'], log='', detail=''), dict(section='EmuCore', key='EnablePINE', value='true')),
        ('TTM-OS-06', 'en', dict(file=None, log='', detail=''), dict(unknown='x')),
        ('TTM-BIOS-06', 'es', dict(file=r'C:\bios\SCPH-70004_BIOS_V12_PAL_200.ROM1', log='', detail=''), dict(size='512 KiB')),
    )

    def test_install_player_ps1_draws_the_same_block_as_setup_messages(self):
        body = []
        for index, (code, language, extra, values) in enumerate(self.CASES):
            body.append(f"$block = Format-SetupFailure '{code}' {ps_value(values)} '{language}' $null {ps_value(extra['file'])} "
                        f"{ps_quote(extra['detail'])} {ps_quote(extra['log'] or '')}")
            body.append("Write-Output ('B64:' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($block)))")
            body.append(f"Write-Output ('LINE:' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((Format-SetupLine 'TTM-DEST-21' '{language}' @{{}}))))")
        output = run_ps('\n'.join(body))
        blocks = [base64.b64decode(line[4:]).decode('utf-8') for line in output.splitlines() if line.startswith('B64:')]
        lines = [base64.b64decode(line[5:]).decode('utf-8') for line in output.splitlines() if line.startswith('LINE:')]
        self.assertEqual(len(blocks), len(self.CASES))
        for (code, language, extra, values), block, line in zip(self.CASES, blocks, lines):
            with self.subTest(code=code, language=language):
                expected = messages.render(code, language, file=extra['file'], log=extra['log'] or None, detail=extra['detail'], **values)
                self.assertEqual(block, expected)
                self.assertEqual(line, messages.line('TTM-DEST-21', 'en' if language == 'both' else language))

    def test_sizes_and_exit_codes_match_python(self):
        import install_player
        sizes = [0, 1000, 1024, 524288, 4194304, 8388609, 3758096384, 3221225471, 10**12]
        output = run_ps('\n'.join(f"Write-Output ('S:' + (Format-Size {size}))" for size in sizes) + '\n' +
                        '\n'.join(f"Write-Output ('E:' + (Get-FailureExitCode '{code}'))" for code in ('TTM-ISO-06', 'TTM-PLAY-51', 'TTM-X-01')))
        self.assertEqual([line[2:] for line in output.splitlines() if line.startswith('S:')], [install_player.size_text(s) for s in sizes])
        self.assertEqual([int(line[2:]) for line in output.splitlines() if line.startswith('E:')], [70, 2, 80])


if __name__ == '__main__': unittest.main()
