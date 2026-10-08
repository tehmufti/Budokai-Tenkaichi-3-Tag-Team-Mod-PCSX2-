import configparser
import contextlib
import io
import os
import re
import shutil
import signal
import subprocess
import sys
import hashlib
import json
from pathlib import Path,PurePosixPath
import tempfile
import time
import struct
import types
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import zipfile
import install_player as installer
import check_installation as checker

HERE=Path(__file__).resolve().parent
BT3_TOOLS=HERE.parent/'bt3-multifighter/tools'
TESTED=['2.6.0','2.6.1','2.6.2','2.6.3','2.8.0','2.8.1','2.8.2']
# PCSX2 numeric file versions -> (accepted, tested). Nightlies and later 2.x releases are accepted.
GATE=[*[(v+'.0',True,True) for v in TESTED],('2.7.361.0',True,False),('2.9.79.0',True,False),
      ('2.8.3.0',True,False),('2.10.0.0',True,False),('2.5.211.0',False,False),('2.5.0.0',False,False),
      ('2.4.0.0',False,False),('1.7.5779.0',False,False),('3.0.0.0',False,False),('',False,False)]


class AdapterContractTests(unittest.TestCase):
    def test_every_adapter_has_one_contract_shared_by_setup_checker_scanner_and_release(self):
        release=installer.release_info()
        self.assertEqual(set(installer.ADAPTERS),set(release['adapters']))
        self.assertEqual(set(installer.ADAPTERS),set(checker.ADAPTERS))
        for name,row in installer.ADAPTERS.items():
            with self.subTest(adapter=name):
                self.assertEqual(checker.ADAPTERS[name],(row['pine_slot'],row['preflight'],row['native_map']))
                self.assertIs(installer.adapter_contract(name,release),row)
        sys.path.insert(0,str(HERE.parent));self.addCleanup(sys.path.remove,str(HERE.parent))
        from iso_compatibility.adapters import BY_NAME
        self.assertEqual(set(BY_NAME),set(installer.ADAPTERS))
        # The European disc runs the bt3-usa tools: the same payload folder, never a second copy of the tools.
        self.assertEqual(installer.ADAPTERS['bt3-pal'],dict(payload='bt3-usa',pine_slot=28011,preflight=None,native_map='pal_native_map.json'))
        self.assertEqual(release['adapters']['bt3-pal'],'BT3 Europe (SLES-54945)')
        # So does the Japanese disc, with its own address table.
        self.assertEqual(installer.ADAPTERS['bt3-jpn'],dict(payload='bt3-usa',pine_slot=28011,preflight=None,native_map='jpn_native_map.json'))
        self.assertEqual(release['adapters']['bt3-jpn'],'BT3 Japan (SLPS-25815, Sparking! Meteor)')
        self.assertEqual({row['payload'] for row in installer.ADAPTERS.values()},{'bt3-usa','bt4-b14-rev2-eng'})
        with self.assertRaisesRegex(ValueError,'not enabled'):installer.adapter_contract('bt3-japan')
        with self.assertRaisesRegex(ValueError,'not enabled'):installer.adapter_contract('bt3-pal',dict(release,adapters={'bt3-usa':'BT3 USA'}))
        self.assertEqual([installer.socket_suffix(installer.ADAPTERS[a]['pine_slot']) for a in ('bt3-usa','bt3-pal','bt4-b14-rev2-eng')],
                         ['','','.28012'])


class VersionPolicyTests(unittest.TestCase):
    def test_release_json_states_the_minimum_and_the_tested_releases(self):
        release=installer.release_info()
        self.assertEqual((release['pcsx2_minimum'],release['pcsx2_supported']),('2.6.0',TESTED))
        self.assertIn(release['pcsx2'],TESTED)

    def test_installer_gate_accepts_every_2x_build_from_260_and_flags_untested_ones(self):
        release=installer.release_info()
        for version,accepted,tested in GATE:
            with self.subTest(version=version):
                self.assertEqual(installer.pcsx2_support(version,release),(accepted,tested))
        self.assertEqual(installer.version_parts('PCSX2 v2.7.361-nightly'),(2,7,361))
        self.assertIsNone(installer.version_parts('2.6'))

    def test_receipt_records_whether_the_emulator_is_a_tested_release(self):
        release=installer.release_info()
        for version,tested in (('2.8.2.0',True),('2.6.0.0',True),('2.9.79.0',False)):
            with self.subTest(version=version):
                receipt=installer.install_receipt(release,'bt3-usa',version,{'game/tools/x.py':'0'*64})
                self.assertEqual(receipt,dict(schema=1,version=release['version'],adapter='bt3-usa',
                    emulator_version=version,pcsx2_tested=tested,files={'game/tools/x.py':'0'*64}))

    def test_payload_policy_must_match_release_json(self):
        release=installer.release_info()
        installer.check_version_policy(BT3_TOOLS,release)
        with tempfile.TemporaryDirectory() as tmp:
            tools=Path(tmp)
            with self.assertRaisesRegex(ValueError,'missing tools/pcsx2_versions.json'):installer.check_version_policy(tools,release)
            policy=json.loads((BT3_TOOLS/'pcsx2_versions.json').read_text(encoding='utf-8'))
            for change in (dict(player_minimum='2.8.0'),dict(tested=TESTED[:-1])):
                (tools/'pcsx2_versions.json').write_text(json.dumps(dict(policy,**change)),encoding='utf-8')
                with self.subTest(change=change),self.assertRaisesRegex(ValueError,'disagree'):
                    installer.check_version_policy(tools,release)

    def test_check_installation_applies_the_installed_runtime_policy(self):
        release=installer.release_info()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);tools=root/'game/tools';tools.mkdir(parents=True)
            for name in ('pcsx2_versions.py','pcsx2_versions.json'):(tools/name).write_bytes((BT3_TOOLS/name).read_bytes())
            for version,accepted,tested in GATE:
                with self.subTest(version=version),contextlib.redirect_stdout(io.StringIO()) as printed:
                    if accepted:
                        self.assertEqual(checker.check_emulator(root,dict(emulator_version=version),release),version)
                        self.assertEqual('is not one of the supported stable releases' in printed.getvalue(),not tested)
                    else:
                        with self.assertRaisesRegex(ValueError,'not supported'):
                            checker.check_emulator(root,dict(emulator_version=version),release)
            with self.assertRaisesRegex(ValueError,'does not match release.json'):
                checker.check_emulator(root,dict(emulator_version='2.8.2.0'),dict(release,pcsx2_minimum='2.8.0'))


# A version named as the minimum: "2.6.0 or newer", "from 2.6.0 on", "2.6.0 o posterior", "desde la 2.6.0".
MINIMUM_PHRASE=re.compile(r'(?P<v>\d+\.\d+\.\d+)(?:\*\*)?\s+(?:or newer|or later|and newer|and later|o posterior|o superior)'
                          r'|(?:at least|minimum|from|desde(?:\s+la)?|como m[ií]nimo)\s+(?:PCSX2\s+)?(?:\*\*)?v?(?P<w>\d+\.\d+\.\d+)',re.I)


def minimum_mentions(text):return [m.group('v') or m.group('w') for m in MINIMUM_PHRASE.finditer(text)]


def iso_image(blocks=18,declared=None):
    """A minimal plain ISO 9660 image: the primary volume descriptor at sector 16, which setup's preflight reads."""
    data=bytearray(blocks*2048);data[0x8000:0x8006]=b'\x01CD001'
    struct.pack_into('<I',data,0x8050,blocks if declared is None else declared)
    return bytes(data)


def bios_image():
    """A file that passes setup's PS2 BIOS check (4 MiB with a ROMDIR table naming ROMVER)."""
    return b'RESET\0\0\0\0\0\0\0ROMDIR\0\0\0\0\0\0ROMVER'.ljust(4<<20,b'\0')


class MinimumVersionTextTests(unittest.TestCase):
    def test_every_installer_string_naming_the_minimum_version_uses_release_json(self):
        minimum=installer.release_info()['pcsx2_minimum']
        source=(HERE/'install-player.ps1').read_text(encoding='utf-8-sig')
        translations=json.loads((HERE/'installer-es.json').read_text(encoding='utf-8'))
        code='\n'.join(line for line in source.splitlines() if not line.lstrip().startswith('#'))
        literals=[m.group(1).replace("''","'") for m in re.finditer(r"'((?:[^'\n]|'')*)'",code)]
        literals+=[m.group(1) for m in re.finditer(r'"((?:[^"`\n]|`.)*)"',code)]
        english=[text for text in literals if minimum_mentions(text)]
        self.assertGreaterEqual(len(english),1,'the PCSX2 file chooser names the minimum')
        catalog=json.loads((HERE/'messages.json').read_text(encoding='utf-8'))['codes']
        for language in ('en','es'):self.assertIn('{minimum}',catalog['TTM-PCSX2-02'][language]['what'])
        for code,row in catalog.items():
            for language in ('en','es'):
                for part in ('what','why','fix'):
                    with self.subTest(code=code,language=language,part=part):
                        self.assertLessEqual(set(minimum_mentions(row[language][part])),{minimum})
        for text in english:
            with self.subTest(text=text):
                self.assertEqual(set(minimum_mentions(text)),{minimum})
                self.assertIn(text,translations,'shown in Spanish too')
                self.assertEqual(set(minimum_mentions(translations[text])),{minimum})
        for key,value in translations.items():
            for text in (key,value):
                with self.subTest(text=text):self.assertLessEqual(set(minimum_mentions(text)),{minimum})
        # The player guides state the same minimum wherever they name one.
        for name in ('README.md','LEEME.md','README.txt'):
            text=' '.join((HERE/name).read_text(encoding='utf-8').split())
            with self.subTest(document=name):
                self.assertTrue(minimum_mentions(text));self.assertEqual(set(minimum_mentions(text)),{minimum})
        self.assertEqual(minimum_mentions('Select PCSX2 2.8.0 or newer; desde la **2.9.1**'),['2.8.0','2.9.1'])

    def test_player_guides_name_every_settings_category_and_the_cited_paths(self):
        sys.path.insert(0,str(BT3_TOOLS));self.addCleanup(sys.path.remove,str(BT3_TOOLS))
        import localization,mod_settings
        for name,language in (('README.md','en'),('LEEME.md','es')):
            text=' '.join((HERE/name).read_text(encoding='utf-8').split())
            tr=lambda value:localization.tr(value,language)
            with self.subTest(document=name):
                self.assertIn(', '.join(tr(group) for group in mod_settings.ui_groups()),text)
                self.assertIn(f"{tr('Menus')} → {tr('Language / Idioma')}",text)
                self.assertIn(f"{tr('Mod Settings')} → {tr('Controls')}",text)
        # Only releases played with the mod may be called tested (release.json keys keep their names).
        for name in ('README.md','LEEME.md','README.txt'):
            with self.subTest(document=name):
                self.assertNotRegex((HERE/name).read_text(encoding='utf-8'),
                                    r'(?i)(?<!un)tested(?: releases| versions|:)|versiones probadas|probadas:')


@unittest.skipUnless(os.name=='nt','Windows PowerShell')
class PowerShellGateTests(unittest.TestCase):
    def test_prerequisite_commands_use_only_the_winget_source(self):
        source=(HERE/'install-player.ps1').read_text(encoding='utf-8-sig')
        commands=re.findall(r'^\s*(& winget\.exe install [^\r\n]+)',source,re.M)
        self.assertEqual(len(commands),2)
        # Run the actual PowerShell command lines with a harmless command
        # recorder. Neither WinGet nor the real prerequisite installers run.
        with tempfile.TemporaryDirectory() as tmp:
            probe=Path(tmp)/'probe.ps1'
            probe.write_text("$ErrorActionPreference = 'Stop'\n"
                "$script:calls = [System.Collections.Generic.List[object]]::new()\n"
                "function winget.exe { [void]$script:calls.Add([pscustomobject]@{ argv=@($args) }); $global:LASTEXITCODE=0 }\n"
                +'\n'.join(commands)+"\nConvertTo-Json -InputObject @($script:calls.ToArray()) -Depth 5 -Compress\n",
                encoding='utf-8')
            result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(probe)],
                                  capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        calls=json.loads(result.stdout)
        self.assertEqual(len(calls),2)
        for row,package in zip(calls,('Python.Python.3.11','Microsoft.VCRedist.2015+.x64')):
            args=row['argv']
            with self.subTest(package=package):
                self.assertEqual(args[0],'install')
                self.assertEqual(args[args.index('--id')+1],package)
                self.assertIn('--source',args,'an unrelated msstore failure must not block setup')
                self.assertEqual(args.count('--source'),1)
                self.assertEqual(args[args.index('--source')+1],'winget')
                self.assertEqual(args[args.index('--architecture')+1],'x64')
                self.assertIn('--exact',args)
                self.assertIn('--accept-package-agreements',args)
                self.assertIn('--accept-source-agreements',args)
                self.assertNotIn('--ignore-security-hash',args)
        self.assertEqual(calls[0]['argv'][calls[0]['argv'].index('--scope')+1],'user')

    def test_setup_script_gate_matches_the_python_gate_and_its_messages_are_translated(self):
        source=(HERE/'install-player.ps1').read_text(encoding='utf-8-sig')
        start=source.index('function Get-Pcsx2Support');end=source.index('\n}',start)+2
        inputs=[version for version,_,_ in GATE if version]+['2.8.2','v2.7.361-nightly','PCSX2 v2.6.3']
        with tempfile.TemporaryDirectory() as tmp:
            cases=Path(tmp)/'cases.json';cases.write_text(json.dumps(inputs),encoding='utf-8')
            probe=Path(tmp)/'probe.ps1'
            probe.write_text("$ErrorActionPreference = 'Stop'\r\nSet-StrictMode -Version 2\r\n"+source[start:end]+
                "\r\n$release = Get-Content -LiteralPath '%s' -Raw | ConvertFrom-Json\r\n"
                "$cases = Get-Content -LiteralPath '%s' -Raw | ConvertFrom-Json\r\n"
                "$rows = foreach ($case in $cases) { $r = Get-Pcsx2Support $case ([string]$release.pcsx2_minimum) @($release.pcsx2_supported)\r\n"
                "  [pscustomobject]@{ input = [string]$case; accepted = [bool]$r.Accepted; tested = [bool]$r.Tested } }\r\n"
                "ConvertTo-Json -InputObject @($rows) -Compress\r\n"%(HERE/'release.json',cases),encoding='utf-8')
            result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(probe)],
                                  capture_output=True,text=True,timeout=120)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        rows=json.loads(result.stdout);release=installer.release_info()
        self.assertEqual([row['input'] for row in rows],inputs)
        for row in rows:
            with self.subTest(**row):
                self.assertEqual((row['accepted'],row['tested']),installer.pcsx2_support(row['input'],release))
        translations=json.loads((HERE/'installer-es.json').read_text(encoding='utf-8'))
        for text in re.findall(r"(?:throw|L|Pick-File) '([^']*PCSX2[^']*)'",source):
            with self.subTest(text=text):
                self.assertIn(text,translations)
                self.assertIn('2.6.0' if '2.6.0' in text else 'PCSX2',translations[text])
        self.assertNotRegex(source,r"2\\\.8\\\.\(\?:0\|2\)")


class InstallerTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt','the Windows PCSX2 folder copy (Linux copies one AppImage)')
    def test_runtime_copy_keeps_qt_dependencies_but_not_user_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';source.mkdir()
            for name in ('pcsx2-qt.exe','qt.conf','SDL3.dll','QtPlugins/platforms/qwindows.dll','D3D12/D3D12Core.dll','memcards/save.ps2','inis/PCSX2.ini','sstates/save.p2s'):
                path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
            target=root/'copy';installer.runtime_copy(source,target)
            self.assertEqual((target/'qt.conf').read_bytes(),b'fixture')
            self.assertTrue((target/'QtPlugins/platforms/qwindows.dll').is_file())
            self.assertTrue((target/'D3D12/D3D12Core.dll').is_file())
            for name in ('memcards','inis','sstates'):self.assertFalse((target/name).exists())
            with self.assertRaisesRegex(ValueError,'inside a PCSX2'):
                installer.runtime_copy(source,source/'QtPlugins/nested/runtime28')

    def bundle(self,root,files):
        p=root/'payload.zip'
        with zipfile.ZipFile(p,'w') as z:
            for name,data in files.items():z.writestr(name,data)
            z.writestr('payload-manifest.json',json.dumps({k:hashlib.sha256(v).hexdigest()for k,v in files.items()}))
        p.with_suffix('.json').write_text(json.dumps(dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest())))
        return p

    def test_payload_integrity_paths_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=self.bundle(root,{'tools/example.py':b'example'})
            installer.unpack(p,root/'out')
            with self.assertRaisesRegex(ValueError,'occupied'):installer.unpack(p,root/'out')
            p.write_bytes(p.read_bytes()+b'changed')
            with self.assertRaisesRegex(ValueError,'checksum'):installer.unpack(p,root/'other')
            p=self.bundle(root,{'../outside.py':b'bad'})
            with self.assertRaisesRegex(ValueError,'Unsafe'):installer.unpack(p,root/'out')
            self.assertFalse((root/'outside.py').exists())

    def test_configuration_is_isolated_and_dumps_are_off(self):
        c=installer.configuration('user-bios.bin',28012)
        self.assertEqual(c['EmuCore/CPU']['ExtraMemory'],'true')
        self.assertEqual(c['EmuCore/Speedhacks']['vuThread'],'true')  # MTVU, as every tested profile
        self.assertEqual(c['EmuCore']['PINESlot'],'28012')
        for value in c['Folders'].values():self.assertFalse(Path(value).is_absolute())
        self.assertTrue(all(value=='false'for value in c['Logging'].values()))
        self.assertEqual(c['EmuCore/GS']['DumpGSData'],'false')
        self.assertEqual(c['EmuCore/GS']['UserHacks'],'false')  # Keep GameDB's version-appropriate alignment fixes.
        # Zstandard in 2.6.x and 2.8.x: the mod cannot read 2.6's Deflate64/LZMA2 savestates.
        self.assertEqual(c['EmuCore']['SavestateCompressionType'],'2')
        for pad in range(4):
            self.assertEqual(c[f'Pad{pad+1}']['Down'],f'SDL-{pad}/DPadDown')

    def test_spanish_disc_defaults_to_spanish_without_restricting_later_choices(self):
        for setup_language in ('en','es'):
            spanish={'identity':{'runtime_match':{'verified':True,'native_language':'es'}}}
            self.assertEqual(installer.initial_mod_language(spanish,setup_language),'es')
            for match in ({},{'verified':False,'native_language':'es'},
                          {'verified':True,'native_language':'en'},
                          {'verified':True,'native_language':None}):
                self.assertEqual(installer.initial_mod_language({'identity':{'runtime_match':match}},setup_language),setup_language)

    def test_installed_defaults_are_player_defaults_without_language_written_once_and_hashed(self):
        sys.path.insert(0,str(BT3_TOOLS));self.addCleanup(sys.path.remove,str(BT3_TOOLS))
        import mod_settings  # the installer imports it from the unpacked game/tools the same way
        defaults=json.loads((HERE/'player-defaults.json').read_text(encoding='utf-8'))
        expected=mod_settings.validate_settings(dict(defaults));expected.pop('language',None)
        for language in ('en','es'):
            with self.subTest(language=language),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);game=root/'game';game.mkdir()
                installer.write_settings(game,language)
                installed=json.loads((game/'mod-settings-defaults.json').read_text(encoding='utf-8'))
                selected=json.loads((game/'mod-settings.json').read_text(encoding='utf-8'))
                self.assertEqual(installed,expected);self.assertNotIn('language',installed)
                self.assertEqual(selected,dict(expected,language=language))
                self.assertEqual(mod_settings.validate_settings(dict(installed,language=language)),selected)
                before=(game/'mod-settings-defaults.json').read_bytes()
                with self.assertRaises(FileExistsError):installer.write_settings(game,'en')
                self.assertEqual((game/'mod-settings-defaults.json').read_bytes(),before)
                for folder in ('iso_compatibility','game/tools','game/assets','game/analysis','game/runtime28/inis'):
                    (root/folder).mkdir(parents=True,exist_ok=True)
                (root/'game/tools/pcsx2_versions.json').write_text('{}');(root/'game/runtime28/inis/PCSX2.ini').write_text('')
                files=installer.installed_files(root,game,root/'game/runtime28')
                self.assertEqual(files['game/mod-settings-defaults.json'],installer.file_hash(game/'mod-settings-defaults.json'))
                self.assertIn('game/tools/pcsx2_versions.json',files)
                self.assertNotIn('game/mod-settings.json',files);self.assertNotIn('game/runtime28/inis/PCSX2.ini',files)

    def test_late_bad_member_does_not_partially_extract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for bad in ('../outside.py','/absolute.py','a/../alias.py','C:/escape.py','a\\file.py','NUL','file.','file ',
                        'com1.txt','tools/LPT3 .log','CONIN$','aux'):
                with self.subTest(bad=bad):
                    p=self.bundle(root,{'good.py':b'good',bad:b'bad'})
                    with self.assertRaisesRegex(ValueError,'Unsafe|Unexpected'):installer.unpack(p,root/'out')
                    self.assertFalse((root/'out/good.py').exists())

    def test_case_collision_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=self.bundle(root,{'File.py':b'a','file.py':b'b'})
            with self.assertRaisesRegex(ValueError,'Case-colliding'):installer.unpack(p,root/'out')
            self.assertFalse((root/'out').exists())

    def test_member_checksum_checked_even_with_valid_outer_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'payload.zip'
            with zipfile.ZipFile(p,'w') as z:
                z.writestr('bad.py',b'changed')
                z.writestr('payload-manifest.json',json.dumps({'bad.py':hashlib.sha256(b'original').hexdigest()}))
            p.with_suffix('.json').write_text(json.dumps(dict(sha256=installer.file_hash(p))))
            with self.assertRaisesRegex(ValueError,'file checksum'):installer.unpack(p,root/'out')
            self.assertFalse((root/'out').exists())

    def test_early_install_failure_has_receipt_and_no_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/'new';target.mkdir()
            iso=root/'game.iso';iso.write_bytes(b'iso')
            bios=root/'bios.bin';bios.write_bytes(b'not a BIOS')
            exe=root/'pcsx2-qt.exe';exe.write_bytes(b'not an executable')
            with self.assertRaisesRegex(ValueError,'BIOS'):
                installer.install(SimpleNamespace(destination=target,iso=iso,bios=bios,pcsx2=exe))
            status=json.loads((target/'install-status.json').read_text())
            self.assertFalse(status['ready']);self.assertIn('Validating',status['failed_stage'])
            self.assertFalse((target/'Play.cmd').exists());self.assertFalse((target/'game').exists())
            self.assertFalse((target/'Play.sh').exists())

    def test_existing_data_is_not_touched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'save.ps2').write_bytes(b'user save')
            args=SimpleNamespace(destination=root)
            with self.assertRaisesRegex(ValueError,'unrelated files'):installer.install(args)
            self.assertEqual((root/'save.ps2').read_bytes(),b'user save')
            self.assertFalse((root/'install-status.json').exists())

    def test_config_checker_allows_controls_display_and_safe_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);runtime=checker.data_folder(root);(runtime/'inis').mkdir(parents=True)  # runtime28/PCSX2 on Linux
            (runtime/'bios').mkdir();(runtime/'bios/bios.bin').write_bytes(b'user BIOS')
            c=installer.configuration('bios.bin',28011)
            c['EmuCore/GS']['upscale_multiplier']='3';c['Pad1']['Cross']='Keyboard/J'
            c['MemoryCards']['Slot1_Filename']='My old card.ps2'
            def save():
                with (runtime/'inis/PCSX2.ini').open('w') as f:c.write(f)
            save();checker.check_config(root,'bt3-usa')
            c['Folders']['MemoryCards']='../../../foreign-cards';save()
            with self.assertRaisesRegex(ValueError,'escapes'):checker.check_config(root,'bt3-usa')
            c['Folders']['MemoryCards']='memcards';c['MemoryCards']['Slot1_Filename']='../../foreign.ps2';save()
            with self.assertRaisesRegex(ValueError,'card must stay'):checker.check_config(root,'bt3-usa')

    def test_config_checker_does_not_repair_or_override_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=checker.data_folder(root)/'inis/PCSX2.ini';path.parent.mkdir(parents=True)
            c=installer.configuration('bios.bin',28011);c['EmuCore']['EnablePINE']='false'
            with path.open('w') as f:c.write(f)
            before=path.read_bytes()
            with self.assertRaisesRegex(ValueError,'EnablePINE'):checker.check_config(root,'bt3-usa')
            self.assertEqual(path.read_bytes(),before)

    def test_checker_applies_each_adapters_pine_slot_and_refuses_unknown_adapters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);runtime=checker.data_folder(root);(runtime/'inis').mkdir(parents=True);(runtime/'bios').mkdir()
            (runtime/'bios/bios.bin').write_bytes(b'user BIOS')
            with (runtime/'inis/PCSX2.ini').open('w') as f:installer.configuration('bios.bin',28011).write(f)
            checker.check_config(root,'bt3-usa');checker.check_config(root,'bt3-pal')
            with self.assertRaisesRegex(ValueError,'PINESlot'):checker.check_config(root,'bt4-b14-rev2-eng')
            with self.assertRaisesRegex(ValueError,'does not know: bt3-japan'):checker.check_config(root,'bt3-japan')

    def test_checker_matches_the_european_address_table_to_the_installed_disc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'game/tools').mkdir(parents=True)
            members={'/SLES_549.45;1':'e'*64,'/BIN/DBZP.BIN;1':'d'*64}
            (root/'game/game-profile.json').write_text(json.dumps(dict(adapter='bt3-pal',serial='SLES_549.45',members=members)))
            table=dict(schema=1,adapter='bt3-pal',elf_sha256='e'*64,dbzp_sha256='d'*64)
            (root/'game/tools/pal_native_map.json').write_text(json.dumps(table))
            checker.check_native_map(root,'bt3-pal')
            checker.check_native_map(root,'bt3-usa')  # the USA adapter has no table to check
            for change in (dict(elf_sha256='0'*64),dict(dbzp_sha256='0'*64),dict(adapter='bt3-usa')):
                (root/'game/tools/pal_native_map.json').write_text(json.dumps(dict(table,**change)))
                with self.subTest(change=change),self.assertRaisesRegex(ValueError,'does not match the installed disc'):
                    checker.check_native_map(root,'bt3-pal')

    def test_setup_requires_the_address_table_made_from_the_selected_disc(self):
        profile=dict(identity=dict(adapter='bt3-pal',serial='SLES_549.45',members={'/SLES_549.45;1':'e'*64,'/BIN/DBZP.BIN;1':'d'*64}))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'pal_native_map.json'
            with self.assertRaisesRegex(ValueError,'missing tools/pal_native_map.json'):installer.check_native_map(path,profile)
            table=dict(schema=1,adapter='bt3-pal',elf_sha256='e'*64,dbzp_sha256='d'*64)
            path.write_text(json.dumps(table));installer.check_native_map(path,profile)
            for change in (dict(schema=2),dict(adapter='bt3-usa'),dict(elf_sha256='0'*64),dict(dbzp_sha256='0'*64)):
                path.write_text(json.dumps(dict(table,**change)))
                with self.subTest(change=change),self.assertRaisesRegex(ValueError,'not made from this disc'):
                    installer.check_native_map(path,profile)

    def test_unsupported_discs_are_named_with_the_supported_discs_in_the_setup_language(self):
        sys.path.insert(0,str(HERE.parent));self.addCleanup(sys.path.remove,str(HERE.parent))
        from iso_compatibility import known_discs as K
        translations=json.loads((HERE/'installer-es.json').read_text(encoding='utf-8'))
        # Every piece of a refusal is translated, keeping its placeholders.
        for text in (*K.TEMPLATES,*K.DISCS.values(),K.SUPPORTED,installer.SEE_REPORT):
            with self.subTest(text=text):
                self.assertIn(text,translations)
                self.assertEqual(re.findall(r'\{\w+\}',translations[text]),re.findall(r'\{\w+\}',text))
        es=lambda text:translations.get(text,text)
        for serial,kind,changed,named,nombrado in (('SLPS_258.15','bt3-afs','executable','Sparking! Meteor','Sparking! Meteor'),
                                                   ('SLPM_611.62','unknown',None,'demo (SLPM-61162)','demo japonesa'),
                                                   ('SLUS_216.78','bt3-afs','executable','USA (SLUS-21678)','EE. UU. (SLUS-21678)'),
                                                   ('SLES_549.45','bt3-afs','addon','Europe (SLES-54945)','Europa (SLES-54945)'),
                                                   ('SLUS_219.78','bt4-indexed','executable','Tenkaichi 4 build','Tenkaichi 4 distinta')):
            evidence=K.explain(SimpleNamespace(serial=serial,kind=kind,members={}),dict(verified=False,reason='technical'),changed)
            profile=dict(identity=dict(runtime_match=evidence))
            english,spanish=installer.refusal_message(profile),installer.refusal_message(profile,es)
            with self.subTest(serial=serial,changed=changed):
                self.assertEqual(english,evidence['refusal']['text']+' '+installer.SEE_REPORT)
                self.assertIn(named,english);self.assertIn(nombrado,spanish)
                for text in (english,spanish):
                    for supported in ('SLUS-21678','SLES-54945','B14 REV2'):self.assertIn(supported,text)
                self.assertIn('Discos compatibles',spanish);self.assertIn('COMPATIBILITY.md',spanish)
                self.assertNotIn('The selected ISO',spanish);self.assertNotIn('{',spanish+english)
        # A profile from an older scanner keeps its technical reason.
        self.assertEqual(installer.refusal_message(dict(identity=dict(runtime_match=dict(reason='old')))),
                         'Unknown executable/add-on: old '+installer.SEE_REPORT)

    def test_standalone_settings_use_installed_runtime_without_launcher_environment(self):
        source=Path(__file__).resolve().parents[1]/'bt3-multifighter/tools/runtime_profile.py'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);tools=root/'tools';tools.mkdir();(tools/'runtime_profile.py').write_bytes(source.read_bytes())
            env=dict(os.environ);env.pop('BT3_RUNTIME_PROFILE',None)
            def selected():
                return subprocess.check_output([sys.executable,'-c','import runtime_profile;print(runtime_profile.NAME)'],cwd=tools,env=env,text=True).strip()
            self.assertEqual(selected(),'runtime128')
            (root/'player-install.json').write_text('{"schema":1}')
            self.assertEqual(selected(),'runtime28')


def appimage_bytes(machine=0x3E,magic=b'AI\x02',size=256):
    """An ELF64 header with the AppImage type-2 magic at offset 8 and e_machine at 18."""
    head=bytearray(b'\x7fELF\x02\x01\x01\x00'+magic.ljust(8,b'\0'));head+=bytes(8)
    head[18:20]=machine.to_bytes(2,'little')
    return bytes(head).ljust(size,b'\0')


# A real PCSX2 AppImage for the Linux-only checks (the WSL runner sets it; nothing downloads one).
REAL_APPIMAGE=Path(os.environ.get('TAGTEAM_TEST_APPIMAGE') or '/nonexistent/pcsx2.AppImage')
linux_only=unittest.skipUnless(sys.platform.startswith('linux'),'needs Linux (POSIX modes, symlinks, sh)')


class LinuxInstallerTests(unittest.TestCase):
    """install_player.py's Linux branches: mocked on Windows (WINDOWS=False), real on Linux."""
    def linux(self):
        for module in (installer,checker):
            patcher=patch.object(module,'WINDOWS',False);patcher.start();self.addCleanup(patcher.stop)

    def test_python_policy_is_311_on_windows_and_the_wheel_set_on_linux(self):
        for windows,version,accepted in ((True,(3,11),True),(True,(3,12),False),(False,(3,11),True),(False,(3,12),True),
                                         (False,(3,13),True),(False,(3,14),True),(False,(3,10),False),(False,(3,15),False)):
            with self.subTest(windows=windows,version=version),patch.object(installer,'WINDOWS',windows):
                self.assertEqual(installer.python_supported(version),accepted)
        self.assertEqual(installer.LINUX_PYTHONS,checker.LINUX_PYTHONS)
        linux=json.loads((HERE/'dependencies-linux.json').read_text(encoding='utf-8'))['python']
        self.assertEqual([f'{a}.{b}' for a,b in installer.LINUX_PYTHONS],linux)
        script=(HERE/'Install.sh').read_text(encoding='utf-8')
        self.assertIn('python3.14 python3.13 python3.12 python3.11 python3',script)
        self.assertIn('((3, 11), (3, 12), (3, 13), (3, 14))',script)

    def test_reserved_names_are_refused_on_every_system(self):
        for name in ('NUL','nul','Aux.txt','com1','COM9.log','lpt1','LPT3 .log','CONIN$','conout$.txt','COM\xb9'):
            with self.subTest(name=name):self.assertTrue(installer.reserved_name(name))
        for name in ('console.py','nullable','COM10','auxiliary.json','com','LPT0'):
            with self.subTest(name=name):self.assertFalse(installer.reserved_name(name))

    def test_linux_profile_lives_in_the_appimage_data_folder(self):
        runtime=Path('game/runtime28')
        with patch.object(installer,'WINDOWS',True):self.assertEqual(installer.data_folder(runtime),runtime)
        with patch.object(installer,'WINDOWS',False):self.assertEqual(installer.data_folder(runtime),runtime/'PCSX2')
        # The installed runtime looks for the same executable and data folder (runtime_profile.EXECUTABLE/DATA).
        sys.path.insert(0,str(BT3_TOOLS));self.addCleanup(sys.path.remove,str(BT3_TOOLS))
        import runtime_profile
        for windows in (True,False):
            with self.subTest(windows=windows),patch.object(installer,'WINDOWS',windows):
                self.assertEqual(installer.data_folder(runtime),runtime_profile.data_directory(runtime,windows))
        self.assertEqual(runtime_profile.executable(runtime,False).name,'pcsx2-qt.AppImage')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.linux()
            data=root/'game/runtime28/PCSX2';(data/'inis').mkdir(parents=True);(data/'bios').mkdir()
            (data/'bios/bios.bin').write_bytes(b'user BIOS')
            with (data/'inis/PCSX2.ini').open('w') as f:installer.configuration('bios.bin',28012).write(f)
            self.assertEqual(checker.data_folder(root),data)
            checker.check_config(root,'bt4-b14-rev2-eng')
            with self.assertRaisesRegex(ValueError,'PINESlot'):checker.check_config(root,'bt3-usa')
            (data/'bios/bios.bin').unlink()
            with self.assertRaisesRegex(ValueError,'BIOS is missing'):checker.check_config(root,'bt4-b14-rev2-eng')

    def test_linux_receipt_excludes_the_mutable_pcsx2_data_but_hashes_the_appimage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);game=root/'game';runtime=game/'runtime28';data=runtime/'PCSX2'
            for folder in ('iso_compatibility','game/tools','game/assets','game/analysis','game/runtime28/PCSX2/inis',
                           'game/runtime28/PCSX2/bios','game/runtime28/PCSX2/cheats','game/runtime28/PCSX2/sstates'):
                (root/folder).mkdir(parents=True,exist_ok=True)
            (game/'tools/autopilot.py').write_text('code');(runtime/'pcsx2-qt.AppImage').write_bytes(appimage_bytes())
            (runtime/'portable.ini').write_text('')
            for name in ('inis/PCSX2.ini','bios/bios.bin','cheats/SLUS-21678_428113C2_BT3Loading.pnach','sstates/a.p2s'):
                (data/name).write_bytes(b'mutable')
            with patch.object(installer,'WINDOWS',True):
                windows=installer.installed_files(root,game,runtime)
            self.assertIn('game/runtime28/PCSX2/inis/PCSX2.ini',windows)  # the Windows list itself is unchanged
            with patch.object(installer,'WINDOWS',False):
                files=installer.installed_files(root,game,runtime)
            self.assertEqual(set(files),{'game/tools/autopilot.py','game/runtime28/pcsx2-qt.AppImage'})
            intact=lambda:[name for name,digest in files.items() if installer.file_hash(root/name)!=digest]
            (data/'inis/PCSX2.ini').write_bytes(b'[EmuCore]\nEnablePINE = true\n')  # PCSX2 and the launcher edit the INI
            (data/'cheats/SLUS-21678_428113C2_BT3Loading.pnach').write_bytes(b'rebuilt')
            self.assertEqual(intact(),[])
            (runtime/'pcsx2-qt.AppImage').write_bytes(appimage_bytes(size=300))
            self.assertEqual(intact(),['game/runtime28/pcsx2-qt.AppImage'])

    def test_linux_receipt_records_how_the_version_was_read(self):
        release=installer.release_info()
        receipt=installer.install_receipt(release,'bt3-usa','2.8.2',{},emulator_kind='appimage',emulator_version_source='AppImage metainfo')
        self.assertEqual(receipt,dict(schema=1,version=release['version'],adapter='bt3-usa',emulator_version='2.8.2',
                                      pcsx2_tested=True,files={},emulator_kind='appimage',emulator_version_source='AppImage metainfo'))

    def test_appimage_check_explains_flatpak_and_refuses_other_programs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def write(name,data):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);return path
            installer.appimage_check(write('pcsx2-v2.8.2-linux-appimage-x64-Qt.AppImage',appimage_bytes()))
            # Only Flatpak's own folders mean Flatpak: an AppImage kept in a folder named "flatpak" is accepted.
            installer.appimage_check(write('home/Downloads/flatpak/pcsx2-v2.8.2-linux-appimage-x64-Qt.AppImage',appimage_bytes()))
            installer.appimage_check(write('home/flatpak-apps/pcsx2.AppImage',appimage_bytes()))
            for path,message in ((write('pcsx2-v2.8.2-linux-flatpak-x64-Qt.flatpak',b'xdg-app\0'),'Flatpak'),
                                 (write('var/lib/flatpak/app/net.pcsx2.PCSX2/files/bin/pcsx2-qt',appimage_bytes()),'Flatpak'),
                                 (write('var/lib/flatpak/exports/bin/net.pcsx2.PCSX2',b'#!/bin/sh\nexec flatpak run\n'),'Flatpak'),
                                 (write('home/.local/share/flatpak/app/net.pcsx2.PCSX2/current/active/files/bin/pcsx2-qt',appimage_bytes()),'Flatpak'),
                                 (write('home/.var/app/net.pcsx2.PCSX2/pcsx2.AppImage',appimage_bytes()),'Flatpak'),
                                 (write('pcsx2-qt.exe',b'MZ'+bytes(100)),'Not a Linux program'),
                                 (write('arm.AppImage',appimage_bytes(machine=0xB7)),'x86-64'),
                                 (write('usr/bin/pcsx2-qt',appimage_bytes(magic=b'\0\0\0')),'not an AppImage')):
                with self.subTest(path=path.name),self.assertRaisesRegex(ValueError,message):installer.appimage_check(path)

    def test_version_comes_from_metainfo_then_the_official_file_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);release=installer.release_info()
            official=root/'pcsx2-v2.8.2-linux-appimage-x64-Qt.AppImage';official.write_bytes(appimage_bytes())
            renamed=root/'PCSX2.AppImage';renamed.write_bytes(appimage_bytes())
            nightly=root/'pcsx2-v2.9.79-linux-appimage-x64-Qt.AppImage';nightly.write_bytes(appimage_bytes())
            with patch.object(installer.os,'access',return_value=True),patch.object(installer,'appimage_metainfo_version',return_value='2.8.1'):
                self.assertEqual(installer.appimage_version(renamed),('2.8.1','AppImage metainfo'))
            with patch.object(installer.os,'access',return_value=True),patch.object(installer,'appimage_metainfo_version',return_value=None):
                self.assertEqual(installer.appimage_version(official),('2.8.2','file name'))
                self.assertEqual(installer.appimage_version(nightly),('2.9.79','file name'))
                self.assertEqual(installer.pcsx2_support('2.9.79',release),(True,False))
                with self.assertRaisesRegex(ValueError,'Could not read the PCSX2 version'):installer.appimage_version(renamed)
            with self.assertRaisesRegex(ValueError,'too old: 2.5.211. Select PCSX2 2.6.0 or newer for Linux'):
                installer.require_supported_appimage('2.5.211',release)

    def test_metainfo_is_unpacked_in_a_fresh_folder_without_target_appimage(self):
        calls=[]
        def extract(command,cwd,env,**options):
            calls.append((command,env))
            xml=Path(cwd)/'squashfs-root/usr/share/metainfo/net.pcsx2.PCSX2.appdata.xml';xml.parent.mkdir(parents=True)
            xml.write_text('<component><releases>\n    <release version="v2.8.2" date="2026-09-04 11:25:34 -0400" />\n'
                           '    <release version="v2.8.1" /></releases></component>',encoding='utf-8')
            return SimpleNamespace(returncode=0,stdout='',stderr='')
        with patch.dict(os.environ,TARGET_APPIMAGE='/elsewhere.AppImage',APPIMAGE_EXTRACT_AND_RUN='1'),\
             patch.object(installer.subprocess,'run',side_effect=extract):
            self.assertEqual(installer.appimage_metainfo_version('/x/pcsx2.AppImage'),'2.8.2')
        command,env=calls[0]
        self.assertEqual(command,['/x/pcsx2.AppImage','--appimage-extract','usr/share/metainfo'])
        self.assertNotIn('TARGET_APPIMAGE',env);self.assertNotIn('APPIMAGE_EXTRACT_AND_RUN',env)

    def test_linux_launchers_call_the_python_launcher_and_detect_a_broken_environment(self):
        for adapter,language,socket in (('bt3-usa','en','pcsx2.sock"'),('bt3-pal','es','pcsx2.sock"'),('bt4-b14-rev2-eng','es','pcsx2.sock.28012"')):
            scripts=installer.linux_scripts(adapter,language)
            self.assertEqual(set(scripts),{'Play.sh','Mod settings.sh','Check installation.sh','PCSX2 settings.sh',
                                           'Scan compatibility.sh','Build expanded maps.sh','Play online.sh'})
            self.assertIn('"$here/online/netplay/ttm_online.py" --pcsx2 "$here/game/runtime28/pcsx2-qt.AppImage" "$@"',
                          scripts['Play online.sh'])
            broken=installer.translator(language)(installer.BROKEN_VENV)
            for name,text in scripts.items():
                with self.subTest(adapter=adapter,script=name):
                    self.assertTrue(text.startswith('#!/bin/sh\n'));self.assertNotIn('\r',text)
                    self.assertIn('.venv/bin/python',text)
                    if name!='PCSX2 settings.sh':self.assertIn(installer.sh_quote(broken),text)
            self.assertIn('"$here/game/tools/play_launcher.py" play --runtime-profile runtime28 "$@"',scripts['Play.sh'])
            self.assertIn('\n"$python" "$here/game/tools/play_launcher.py" settings "$@"\n',scripts['Mod settings.sh'])
            self.assertIn('show_error',scripts['Mod settings.sh'])
            self.assertIn('\n"$appimage" -portable "$@" >"$log" 2>&1\n',scripts['PCSX2 settings.sh'])
            self.assertIn(socket,scripts['PCSX2 settings.sh'])
            self.assertIn('"$here/check_installation.py" "$@" >"$log"',scripts['Check installation.sh'])
            # The settings scripts report every failure themselves (no exec), in the setup language.
            for name in ('Mod settings.sh','PCSX2 settings.sh'):self.assertNotIn('exec "',scripts[name])
            L=installer.translator(language)
            self.assertIn('show_error '+installer.sh_quote(L(installer.SETTINGS_NO_TK)),scripts['Mod settings.sh'])
            for text in (installer.PCSX2_NO_OPENGL,installer.PCSX2_NO_FUSE,installer.PCSX2_NO_LIBRARY,installer.PCSX2_FAILED):
                self.assertIn(installer.sh_quote(L(text)),scripts['PCSX2 settings.sh'])
            # Ctrl+C: the child gets it, the script reaches its pause/report lines (dash would stop with it otherwise).
            for name in ('Play.sh','Mod settings.sh','Check installation.sh','Scan compatibility.sh','Build expanded maps.sh'):
                text=scripts[name]
                self.assertLess(text.index('trap : INT\n'),text.index('"$python" '+('-u ' if name=='Play.sh' else '')+'"$here/'),name)
            self.assertNotIn('trap',scripts['PCSX2 settings.sh'])
        self.assertIn('Pulsa Intro para cerrar.',installer.linux_scripts('bt3-usa','es')['Play.sh'])
        self.assertEqual(installer.sh_quote("it's"),"'it'\\''s'")
        # Mod settings.sh stays quiet for the status play_launcher uses after showing its own error.
        sys.path.insert(0,str(BT3_TOOLS));self.addCleanup(sys.path.remove,str(BT3_TOOLS))
        import play_launcher
        self.assertEqual(installer.SETTINGS_REPORTED,play_launcher.EXIT_REPORTED)
        self.assertIn(f'[ "$rc" -ne {play_launcher.EXIT_REPORTED} ]',installer.linux_scripts('bt3-usa')['Mod settings.sh'])

    def test_desktop_entries_quote_exec_per_the_specification(self):
        entries=installer.desktop_entries(PurePosixPath('/home/p/Games/Tag Team Mod'))
        self.assertEqual(entries['Tag Team Mod.desktop'],'[Desktop Entry]\nType=Application\nName=Tag Team Mod\nName[es]=Tag Team Mod\n'
            'Exec="/home/p/Games/Tag Team Mod/Play.sh"\nPath=/home/p/Games/Tag Team Mod\n'
            'Icon=/home/p/Games/Tag Team Mod/game/Tag Team Mod Logo.png\nTerminal=true\nCategories=Game;\n')
        self.assertIn('Name[es]=Tag Team Mod - Ajustes del mod\n',entries['Tag Team Mod - Mod settings.desktop'])
        self.assertIn('Terminal=false',entries['Tag Team Mod - PCSX2 settings.desktop'])
        self.assertEqual(installer.desktop_exec('/a b/100% $x`y"z\\w.sh'),'"/a b/100%% \\\\$x\\\\`y\\\\"z\\\\\\\\w.sh"')
        with self.assertRaisesRegex(ValueError,'control characters'):installer.desktop_string('/tmp/a\nb')

    def test_linux_documents_install_under_the_windows_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);installer.copy_linux_documents(root)
            linux=json.loads((HERE/'dependencies-linux.json').read_text(encoding='utf-8'))
            installed=json.loads((root/'dependencies.json').read_text(encoding='utf-8'))
            self.assertEqual({k:v for k,v in installed.items() if k!='licenses'},{k:v for k,v in linux.items() if k!='licenses'})
            # The receipt's license paths name the installed notices/ texts (the release keeps them in notices-linux/).
            self.assertEqual(sorted(installed['licenses'].values()),sorted(linux['licenses'].values()))
            for name,digest in installed['licenses'].items():
                with self.subTest(license=name):
                    self.assertTrue(name.startswith('notices/'));self.assertEqual(installer.file_hash(root/name),digest)
            self.assertEqual((root/'requirements-player.lock').read_bytes(),(HERE/'requirements-player-linux.lock').read_bytes())
            self.assertEqual((root/'THIRD_PARTY_NOTICES.md').read_text(encoding='utf-8'),installer.linux_notices())
            packages=installed['packages']
            self.assertNotIn('comtypes',packages);self.assertNotIn('comtypes',{p.name for p in (root/'notices').iterdir()})
            for name in packages:self.assertTrue((root/'notices'/name).is_dir(),name)
            others={relative.as_posix() for _,relative in installer.other_notices(HERE)}
            for relative in others:self.assertTrue((root/'notices'/relative).is_file(),relative)
            self.assertFalse(any(part in json.loads((HERE/'dependencies.json').read_text())['packages'] for part in {r.split('/')[0] for r in others}))

    def test_linux_notices_name_the_linux_wheels_and_their_bundled_libraries(self):
        text=installer.linux_notices();flat=' '.join(text.split())
        linux=json.loads((HERE/'dependencies-linux.json').read_text(encoding='utf-8'))
        for name,row in linux['packages'].items():
            with self.subTest(package=name):
                self.assertIn(f'- {name} {row["version"]}',text);self.assertIn(f'notices/{name}/',text)
                for file in row['bundled_libraries']:self.assertIn(installer.bundled_library_name(file),text)
        self.assertEqual(installer.bundled_library_name('libgfortran-040039e1-0352e75f.so.5.0.0'),'libgfortran')
        self.assertEqual(installer.bundled_library_name('libscipy_openblas64_-32a4b2a6.so'),'libscipy_openblas64_')
        self.assertEqual(installer.bundled_library_name('libXau-154567c4.so.6.0.0'),'libXau')
        for windows_only in ('comtypes','WinGet','Visual C++','ZIP'):self.assertNotIn(windows_only,text)
        for needed in ('tar.gz','Liberation Sans 2.1.5','notices/liberation-fonts/LICENSE','SDL2-LICENSE.txt','CPython 3.11, 3.12, 3.13, 3.14'):
            self.assertIn(needed,flat)
        windows=' '.join((HERE/'THIRD_PARTY_NOTICES.md').read_text(encoding='utf-8').split())
        shared='No game ISO, PS2 BIOS, memory card, game save, RAM capture or extracted native game executable is included.'
        self.assertIn(shared,windows);self.assertIn(shared,flat)
        self.assertFalse(text.endswith('\n\n'));self.assertNotIn('\r',text)

    def test_linux_prerequisites_name_the_packages(self):
        def cdll(name):
            if name!='libc.so.6':raise OSError(name)
        with patch('ctypes.CDLL',side_effect=cdll),patch('shutil.which',return_value=None),patch.object(checker.os.path,'exists',return_value=False):
            missing,warnings=checker.linux_prerequisites()
        self.assertEqual(len(missing),3)
        self.assertIn('libopengl0',missing[0]);self.assertIn('fuse3',missing[1]);self.assertIn('/dev/fuse',missing[2])
        self.assertNotIn('libfuse2',' '.join(missing))
        self.assertEqual(len(warnings),1);self.assertIn('libsdl2-2.0-0',warnings[0])

    def test_check_installation_names_sdl2_once_through_the_runtime_check(self):
        """Linux Check installation: autopilot.py --check reports SDL2 (3-4 players); the checker does not repeat it.
        Every other prerequisite note is still printed."""
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'game/tools').mkdir(parents=True);(root/'game/runtime28').mkdir()
            (root/'game/runtime28/portable.ini').write_text('',encoding='utf-8')
            appimage=root/'game/runtime28/pcsx2-qt.AppImage';appimage.write_bytes(b'\x7fELF');appimage.chmod(0o755)
            for name,value in (('release.json',dict(version='0.1.0-test')),('dependencies.json',dict(packages={})),
                               ('installed-files.json',dict(files={},adapter='bt3-usa',emulator_kind='appimage'))):
                (root/name).write_text(json.dumps(value),encoding='utf-8')
            runtime=('Three/four-player input: unavailable. SDL2 (libSDL2-2.0.so.0) is not installed, so the mod cannot '
                     'read controllers 3 and 4. Players 1 and 2 are not affected.\nAutopilot dependencies ready: python\n')
            def run(command,**_):
                autopilot=any(str(part).endswith('autopilot.py') for part in command)
                return SimpleNamespace(returncode=0,stdout=runtime if autopilot else 'Using unchanged ISO compatibility profile\n',stderr='')
            output=io.StringIO()
            with patch.object(checker,'WINDOWS',False),patch.object(checker.subprocess,'run',side_effect=run),\
                 patch.object(checker,'linux_prerequisites',return_value=([checker.MISSING_OPENGL],[checker.MISSING_SDL,'an extra note'])),\
                 patch.object(checker,'check_emulator',return_value='2.8.2'),patch.object(checker,'check_config'),\
                 contextlib.redirect_stdout(output):
                result=checker.check(root)
                self.assertFalse(result['ready']);self.assertTrue(result['installation_valid'])
                self.assertEqual(result['missing_runtime_dependencies'],[checker.MISSING_OPENGL])
                with patch.object(checker,'linux_prerequisites',return_value=([],[checker.MISSING_SDL])):
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertTrue(checker.check(root)['ready'],'optional SDL2 does not block one/two players')
        lines=output.getvalue().splitlines()
        self.assertEqual([line for line in lines if 'SDL2' in line],[runtime.splitlines()[0]],'SDL2 is named once')
        self.assertIn('Note: PCSX2 cannot start until this is installed: '+checker.MISSING_OPENGL,lines)
        self.assertIn('Note: an extra note',lines)
        # English and a path only (live Spanish Check installation, Sept 29): not shown, as in Play.
        self.assertFalse([line for line in lines if line.startswith('Autopilot dependencies ready')])

    def test_offline_check_override_keeps_not_ready_and_never_bypasses_integrity_errors(self):
        for windows in (False,True):
            for override in (False,True):
                for broken in (False,True):
                    with self.subTest(windows=windows,override=override,broken=broken),tempfile.TemporaryDirectory() as tmp:
                        result=dict(ready=False,installation_valid=True,missing_runtime_dependencies=[checker.MISSING_OPENGL])
                        with patch.object(checker,'ROOT',Path(tmp)),patch.object(checker,'WINDOWS',windows),\
                             patch.object(checker,'check',return_value=result,side_effect=ValueError('bad hash') if broken else None),\
                             contextlib.redirect_stderr(io.StringIO()):
                            code=checker.main(['--allow-missing-libraries'] if override else [])
                        self.assertEqual(code,0 if override and not windows and not broken else 1)
                        saved=json.loads((Path(tmp)/'check-status.json').read_text())
                        self.assertFalse(saved['ready'])
                        if broken:self.assertIn('bad hash',saved['error'])

    @linux_only
    def test_scripts_are_lf_0755_and_valid_sh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name,text in {**installer.linux_scripts('bt3-usa'),**installer.desktop_entries(root)}.items():
                with self.subTest(name=name):
                    installer.write_script(root/name,text)
                    self.assertEqual((root/name).stat().st_mode&0o777,0o755);self.assertNotIn(b'\r',(root/name).read_bytes())
                    if name.endswith('.sh'):
                        result=subprocess.run(['sh','-n',str(root/name)],capture_output=True,text=True,timeout=30)
                        self.assertEqual(result.returncode,0,result.stderr)

    @linux_only
    def test_play_sh_runs_the_launcher_and_reports_a_broken_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'Tag Team Mod';root.mkdir()
            for name,text in installer.linux_scripts('bt4-b14-rev2-eng').items():installer.write_script(root/name,text)
            # No display: show_error must never open a dialog during tests.
            run=lambda name,*args,**env:subprocess.run(['sh',str(root/name),*args],capture_output=True,text=True,timeout=60,
                                                       stdin=subprocess.DEVNULL,env=dict(os.environ,PYTHONPATH='/guard',DISPLAY='',WAYLAND_DISPLAY='',**env))
            result=run('Play.sh')
            self.assertEqual(result.returncode,1);self.assertIn('no longer runs',result.stderr)
            # A stand-in interpreter records what the launcher receives.
            (root/'.venv/bin').mkdir(parents=True)
            fake=root/'.venv/bin/python'
            fake.write_text('#!/bin/sh\nprintf "%s|" "$PYTHONNOUSERSITE" "$PYTHONPATH" "$@" >> "$(dirname "$0")/calls.log"\necho >> "$(dirname "$0")/calls.log"\nexit 0\n')
            fake.chmod(0o755)
            self.assertEqual(run('Play.sh','--manual-pause').returncode,0)
            self.assertEqual(run('Mod settings.sh').returncode,0)
            self.assertEqual(run('Check installation.sh','--full-iso').returncode,0)
            calls=(root/'.venv/bin/calls.log').read_text().splitlines()
            self.assertIn(f'1||-u|{root}/game/tools/play_launcher.py|play|--runtime-profile|runtime28|--manual-pause|',calls)
            self.assertIn(f'1||{root}/game/tools/play_launcher.py|settings|',calls)
            self.assertIn(f'1||{root}/check_installation.py|--full-iso|',calls)
            self.assertTrue((root/'check-installation.log').is_file())
            # PCSX2 settings.sh opens the AppImage with -portable unless PCSX2's PINE socket is live.
            appimage=root/'game/runtime28/pcsx2-qt.AppImage';appimage.parent.mkdir(parents=True)
            appimage.write_text('#!/bin/sh\necho "APPIMAGE $*"\n');appimage.chmod(0o755)
            fake.write_text('#!/bin/sh\nexec '+sys.executable+' "$@"\n')
            with tempfile.TemporaryDirectory(dir='/tmp') as runtime:
                result=run('PCSX2 settings.sh',XDG_RUNTIME_DIR=runtime)
                self.assertEqual((result.returncode,result.stderr),(0,''))
                self.assertEqual((root/'pcsx2-settings.log').read_text().strip(),'APPIMAGE -portable')  # PCSX2's output
                import socket
                with socket.socket(socket.AF_UNIX) as server:
                    server.bind(runtime+'/pcsx2.sock.28012');server.listen(1)
                    result=run('PCSX2 settings.sh',XDG_RUNTIME_DIR=runtime)
                self.assertEqual(result.returncode,1);self.assertIn('already running',result.stderr)

    def scripted_install(self,tmp,python_body,adapter='bt3-usa',language='en'):
        """An installation folder with the generated scripts and a stand-in .venv/bin/python."""
        root=Path(tmp)/'Tag Team Mod';root.mkdir()
        for name,text in installer.linux_scripts(adapter,language).items():installer.write_script(root/name,text)
        python=root/'.venv/bin/python';python.parent.mkdir(parents=True)
        python.write_text('#!/bin/sh\n'+python_body);python.chmod(0o755)
        return root

    def run_script(self,root,name,*tools,**env):
        """Run a script without a terminal and, unless given, without a display. PATH holds only the named tools, so a
        real dialog program can never open a window during the tests."""
        folder=root.parent/'bin';folder.mkdir(exist_ok=True)
        for tool in ('dirname','mkdir','sed','grep','head','cat',*tools):
            if not (folder/tool).exists() and shutil.which(tool):(folder/tool).symlink_to(shutil.which(tool))
        return subprocess.run([shutil.which('sh'),str(root/name)],capture_output=True,text=True,timeout=60,stdin=subprocess.DEVNULL,
                              env={'PATH':str(folder),'HOME':str(root.parent),'PYTHONPATH':'/guard','DISPLAY':'','WAYLAND_DISPLAY':'',**env})

    @linux_only
    def test_mod_settings_sh_reports_every_failure_without_a_terminal(self):
        with tempfile.TemporaryDirectory() as tmp:
            # No Tk: the package hints, in the installation's language, before the launcher starts.
            root=self.scripted_install(tmp,'case "$*" in *tkinter*) exit 1 ;; *play_launcher*) echo RAN >&2 ;; esac\nexit 0\n',language='es')
            result=self.run_script(root,'Mod settings.sh')
            self.assertEqual(result.returncode,1)
            self.assertIn(installer.translator('es')(installer.SETTINGS_NO_TK),result.stderr);self.assertNotIn('RAN',result.stderr)
        # 0 and play_launcher's EXIT_REPORTED (its own dialog was shown) stay quiet; any other failure is reported,
        # naming the log that keeps the launcher's messages.
        for status,reported in ((0,False),(installer.SETTINGS_REPORTED,False),(1,True),(2,True)):
            with self.subTest(status=status),tempfile.TemporaryDirectory() as tmp:
                root=self.scripted_install(tmp,f'case "$*" in *play_launcher.py*) echo "launcher detail" >&2; exit {status} ;; esac\nexit 0\n')
                result=self.run_script(root,'Mod settings.sh')
                self.assertEqual(result.returncode,status)
                log=root/'game/analysis/settings/launcher.log'
                self.assertIn('launcher detail',log.read_text())
                self.assertEqual(installer.SETTINGS_STOPPED in log.read_text(),reported)
                if reported:self.assertIn(f'{installer.SETTINGS_STOPPED} {log} (exit {status})',log.read_text())
        # On a desktop without a terminal the report is a dialog.
        with tempfile.TemporaryDirectory() as tmp:
            root=self.scripted_install(tmp,'case "$*" in *play_launcher.py*) exit 1 ;; esac\nexit 0\n')
            record=Path(tmp)/'zenity.txt';(Path(tmp)/'bin').mkdir()
            zenity=Path(tmp)/'bin/zenity';zenity.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{record}"\n');zenity.chmod(0o755)
            result=self.run_script(root,'Mod settings.sh',DISPLAY=':0')
            self.assertEqual(result.returncode,1)
            shown=record.read_text().splitlines()
            self.assertEqual(shown[:3],['--error','--no-markup','--title=Tag Team Mod'])
            self.assertTrue(shown[3].startswith('--text='+installer.SETTINGS_STOPPED+' '),shown)

    @linux_only
    def test_pcsx2_settings_sh_explains_why_pcsx2_did_not_start(self):
        L=installer.translator('es')
        cases=(('error while loading shared libraries: libOpenGL.so.0: cannot open shared object file',127,L(installer.PCSX2_NO_OPENGL)),
               ('error while loading shared libraries: libQt6Core.so.6: cannot open shared object file',127,
                L(installer.PCSX2_NO_LIBRARY)+' libQt6Core.so.6'),
               ('fuse: failed to open /dev/fuse: Permission denied\nCannot mount AppImage, please check your FUSE setup.',1,L(installer.PCSX2_NO_FUSE)),
               ('qt.qpa.xcb: could not connect to display',1,L(installer.PCSX2_NO_DISPLAY)),
               ('',3,L(installer.PCSX2_FAILED)+' (exit 3)'),
               ('PCSX2 closed normally',0,None))
        for output,status,problem in cases:
            with self.subTest(problem=problem),tempfile.TemporaryDirectory() as tmp:
                root=self.scripted_install(tmp,'exit 1\n',language='es')  # no socket probe answers: nothing is running
                appimage=root/'game/runtime28/pcsx2-qt.AppImage';appimage.parent.mkdir(parents=True)
                appimage.write_text(f'#!/bin/sh\nprintf "%s\\n" "{output}" >&2\nexit {status}\n');appimage.chmod(0o755)
                result=self.run_script(root,'PCSX2 settings.sh')
                self.assertEqual(result.returncode,status)
                log=root/'pcsx2-settings.log'
                self.assertIn(output,log.read_text())
                if problem is None:self.assertEqual(result.stderr,'')
                else:self.assertEqual(result.stderr,f'{problem} {L(installer.DETAILS)} {log}\n')

    @linux_only
    def test_play_sh_survives_ctrl_c_to_reach_its_pause_and_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            started=Path(tmp)/'started'
            root=self.scripted_install(tmp,f'case "$*" in *play_launcher.py*) : > "{started}"; exec sleep 30 ;; esac\nexit 0\n')
            process=subprocess.Popen([shutil.which('sh'),str(root/'Play.sh')],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE,start_new_session=True,env=dict(os.environ,PYTHONPATH='/guard'))
            try:
                deadline=time.monotonic()+30
                while not started.exists() and time.monotonic()<deadline:time.sleep(.05)
                self.assertTrue(started.exists())
                time.sleep(.2)
                os.killpg(process.pid,signal.SIGINT)  # Ctrl+C in the terminal: the whole foreground group
                process.communicate(timeout=30)
            finally:
                if process.poll() is None:os.killpg(process.pid,signal.SIGKILL);process.wait()
            # The script ran on after the launcher (dash would otherwise die with the signal: status -2).
            self.assertEqual(process.returncode,128+signal.SIGINT)

    @linux_only
    def test_symlinked_parents_are_resolved_but_created_folders_must_be_real(self):
        with tempfile.TemporaryDirectory() as tmp:
            real=Path(tmp)/'var/home/player';real.mkdir(parents=True);(Path(tmp)/'home').symlink_to(real.parent)
            target=real/'Tag Team Mod';target.mkdir()
            iso=real/'game.iso';iso.write_bytes(b'iso');bios=real/'bios.bin';bios.write_bytes(b'not a BIOS')
            with self.assertRaisesRegex(ValueError,'BIOS'):  # got past the path checks
                installer.install(SimpleNamespace(destination=Path(tmp)/'home/player/Tag Team Mod',iso=iso,bios=bios,pcsx2=iso))
            self.assertTrue((target/'install-status.json').is_file())
            link=real/'Linked';link.symlink_to(target)
            with self.assertRaisesRegex(ValueError,'not junctions or symlinks'):
                installer.install(SimpleNamespace(destination=link,iso=iso,bios=bios,pcsx2=iso))

    @unittest.skipUnless(sys.platform.startswith('linux') and REAL_APPIMAGE.is_file(),'set TAGTEAM_TEST_APPIMAGE to a PCSX2 AppImage (Linux)')
    def test_real_appimage_version_copy_and_exec_check(self):
        release=installer.release_info()
        with tempfile.TemporaryDirectory() as tmp:
            copy=Path(tmp)/'pcsx2-qt.AppImage'
            version,source=installer.appimage_version(REAL_APPIMAGE,copy_to=copy)
            self.assertEqual(source,'AppImage metainfo');self.assertTrue(installer.pcsx2_support(version,release)[0])
            self.assertEqual(copy.stat().st_mode&0o777,0o755);self.assertGreater(installer.appimage_offset(copy),0)
            renamed=Path(tmp)/'renamed.AppImage';renamed.write_bytes(REAL_APPIMAGE.read_bytes());renamed.chmod(0o644)
            self.assertEqual(installer.appimage_version(renamed),(version,'AppImage metainfo'))  # probed via a private copy
            self.assertEqual(renamed.stat().st_mode&0o777,0o644)
            with patch.object(installer,'WINDOWS',False):self.assertEqual(installer.pcsx2_version(REAL_APPIMAGE,release),version)


class LinuxInstallFlowTests(unittest.TestCase):
    """install() on its Linux path, with the AppImage probe, the payload, the ISO scan, the settings writer and the
    child checks replaced (runs on Windows too): the layout, the receipt, and Play.sh written last."""
    def setUp(self):
        self.tmp=Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,self.tmp,True)
        saved=list(sys.path);self.addCleanup(sys.path.__setitem__,slice(None),saved)  # install() extends sys.path
        self.iso=self.tmp/'game.iso';self.iso.write_bytes(iso_image())
        self.bios=self.tmp/'SCPH-39001.bin';self.bios.write_bytes(bios_image())
        self.appimage=self.tmp/'pcsx2-v2.8.2-linux-appimage-x64-Qt.AppImage';self.appimage.write_bytes(appimage_bytes())

    # The scanned disc's executable and DBZP.BIN hashes, and the European address table the bt3-usa folder ships.
    SERIALS={'bt3-usa':'SLUS_216.78','bt3-pal':'SLES_549.45','bt4-b14-rev2-eng':'SLUS_219.78'}
    TABLE=dict(schema=1,adapter='bt3-pal',elf_sha256='e'*64,dbzp_sha256='d'*64)

    def install(self,adapter,failing=None,missing=None,table=None,match=None,language='en',name=None,windows=False):
        """Install into a new folder; returns (root, events). `failing` names the child check that fails; `table`
        changes the shipped pal_native_map.json; `match` replaces a verified scan with this refused runtime match;
        `windows` takes the Windows branch (PCSX2 folder copy and .cmd launchers) instead of the Linux one."""
        release=installer.release_info();events=[];root=self.tmp/(name or adapter);root.mkdir()
        def appimage_version(path,copy_to=None):
            events.append('appimage');shutil.copyfile(path,copy_to);return '2.8.2','AppImage metainfo'
        def unpack(payload,work):
            events.append('unpack')
            for folder in ('bt3-usa','bt4-b14-rev2-eng'):
                game=Path(work)/folder
                for sub in ('tools','assets','analysis'):(game/sub).mkdir(parents=True)
                (game/'tools/autopilot.py').write_text('# payload module\n')
                (game/'tools/pcsx2_versions.json').write_text(json.dumps(dict(player_minimum=release['pcsx2_minimum'],tested=release['pcsx2_supported'])))
                for name in (*installer.WINDOWS_ONLY_GAME_FILES,'Tag Team Mod Logo.png'):(game/name).write_bytes(b'payload')
            (Path(work)/'bt3-usa/tools/pal_native_map.json').write_text(json.dumps(dict(self.TABLE,**(table or {}))))
            (Path(work)/'iso_compatibility').mkdir();(Path(work)/'iso_compatibility/scanner.py').write_text('# scanner\n')
            online=Path(work)/'online'                       # the online part (TTM Online)
            for name,data in (('netplay/ttm_online.py','# lobby\n'),('netplay/modtools/netplay_core.py','# core\n'),
                              ('match/PCSX2.ini.template','[EmuCore]\n'),('README - Play online.txt','online\n')):
                (online/name).parent.mkdir(parents=True,exist_ok=True);(online/name).write_text(data)
        def write_settings(game,language):
            (game/'mod-settings-defaults.json').write_text('{}\n');(game/'mod-settings.json').write_text(json.dumps(dict(language=language)))
        def run(command,**options):
            name=Path(command[1]).name;events.append('run:'+name)
            if name=='check_installation.py':
                self.assertEqual('--allow-missing-libraries' in command,bool(missing))
                (root/'check-status.json').write_text(json.dumps(dict(ready=not missing,installation_valid=True,
                                                                    missing_runtime_dependencies=missing or [])))
            return SimpleNamespace(returncode=int(name==failing),stdout='',stderr='')
        write_script=installer.write_script
        def spy(path,text):events.append('write:'+Path(path).name);write_script(path,text)
        scanner=types.ModuleType('iso_compatibility.scanner')
        serial=self.SERIALS[adapter]
        identity=dict(adapter=adapter,serial=serial,members={'/'+serial+';1':'e'*64,'/BIN/DBZP.BIN;1':'d'*64},
                      runtime_match=match or dict(verified=True))
        scanner.scan=lambda iso,profiles,progress=None:dict(capabilities=dict(runtime_hooks=match is None),identity=identity)
        scanner.report=lambda profile:'# Compatibility\n'
        profile=types.ModuleType('iso_compatibility.install_profile')
        profile.prepare=lambda iso,game,profiles,progress=None:events.append('prepare')
        package=types.ModuleType('iso_compatibility');package.__path__=[]
        def runtime_copy(source,destination):
            events.append('runtime_copy');Path(destination).mkdir(parents=True);(Path(destination)/'pcsx2-qt.exe').write_bytes(b'exe')
        with contextlib.ExitStack() as stack:
            for target,name,value in ((installer,'WINDOWS',windows),(installer,'appimage_version',appimage_version),(installer,'unpack',unpack),
                                      (installer,'write_settings',write_settings),(installer,'write_script',spy),
                                      (installer,'pcsx2_version',lambda path,release=None:'2.8.2.0'),(installer,'runtime_copy',runtime_copy),
                                      (installer.subprocess,'run',run),(installer.shutil,'disk_usage',lambda path:SimpleNamespace(free=10<<30))):
                stack.enter_context(patch.object(target,name,value))
            stack.enter_context(patch.dict(sys.modules,{'iso_compatibility':package,'iso_compatibility.scanner':scanner,
                                                        'iso_compatibility.install_profile':profile}))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()));stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            installer.install(SimpleNamespace(destination=root,iso=self.iso,bios=self.bios,pcsx2=self.appimage,language=language,
                                              allow_missing_libraries=bool(missing)))
        return root.resolve(),events

    def test_the_linux_installation_layout_and_receipt(self):
        for adapter,slot in (('bt3-usa',28011),('bt3-pal',28011),('bt4-b14-rev2-eng',28012)):
            with self.subTest(adapter=adapter):
                root,events=self.install(adapter)
                game=root/'game';runtime=game/'runtime28';data=runtime/'PCSX2'
                # Play.sh is the last step, after the final installation check.
                self.assertEqual(events[-1],'write:Play.sh')
                self.assertLess(events.index('run:check_installation.py'),events.index('write:Play.sh'))
                self.assertEqual([e for e in events if e.startswith('run:')],
                                 ['run:autopilot.py','run:install_boot_hooks.py',*(['run:bt4_preflight.py'] if slot==28012 else []),
                                  'run:check_installation.py'])
                # The AppImage beside PCSX2's -portable data folder, which holds the whole private profile.
                self.assertEqual((runtime/'pcsx2-qt.AppImage').read_bytes(),appimage_bytes())
                if os.name!='nt':self.assertEqual((runtime/'pcsx2-qt.AppImage').stat().st_mode&0o777,0o755)
                self.assertTrue((runtime/'portable.ini').is_file())
                self.assertEqual(sorted(p.name for p in runtime.iterdir()),['PCSX2','pcsx2-qt.AppImage','portable.ini'])
                self.assertEqual(sorted(p.name for p in data.iterdir()),['bios','cheats','inis','logs','memcards','sstates'])
                self.assertEqual((data/'bios'/self.bios.name).read_bytes(),self.bios.read_bytes())
                ini=configparser.ConfigParser(interpolation=None);ini.read(data/'inis/PCSX2.ini',encoding='utf-8')
                self.assertEqual((ini['EmuCore']['PINESlot'],ini['Filenames']['BIOS']),(str(slot),self.bios.name))
                # Windows-only launchers are not installed; the rest of the payload is.
                for name in installer.WINDOWS_ONLY_GAME_FILES:self.assertFalse((game/name).exists(),name)
                self.assertTrue((game/'Tag Team Mod Logo.png').is_file())
                scripts=installer.linux_scripts(adapter)
                for name,text in scripts.items():
                    self.assertEqual((root/name).read_text(encoding='utf-8'),text,name)
                for name in installer.desktop_entries(root,True):self.assertTrue((root/name).is_file(),name)
                self.assertEqual((root/'README.txt').read_bytes(),installer.readme_text(adapter,False).encode('utf-8'))
                # The adapter the scan certified, even when it runs another adapter's payload folder.
                self.assertEqual(json.loads((game/'player-install.json').read_text())['adapter'],adapter)
                self.assertEqual((root/'THIRD_PARTY_NOTICES.md').read_text(encoding='utf-8'),installer.linux_notices())
                self.assertFalse((root/'install-staging').exists())
                for windows in ('Play.cmd','Mod settings.cmd','Check installation.cmd'):self.assertFalse((root/windows).exists())
                # The receipt: how the version was read, the AppImage hashed, nothing of PCSX2's mutable data.
                receipt=json.loads((root/'installed-files.json').read_text(encoding='utf-8'))
                self.assertEqual({k:receipt[k] for k in ('adapter','emulator_version','emulator_kind','emulator_version_source','pcsx2_tested')},
                                 dict(adapter=adapter,emulator_version='2.8.2',emulator_kind='appimage',
                                      emulator_version_source='AppImage metainfo',pcsx2_tested=True))
                files=receipt['files']
                self.assertIn('game/runtime28/pcsx2-qt.AppImage',files);self.assertIn('game/tools/autopilot.py',files)
                self.assertIn('game/mod-settings-defaults.json',files);self.assertNotIn('game/mod-settings.json',files)
                self.assertEqual([name for name in files if name.startswith('game/runtime28/PCSX2/') or name=='game/runtime28/portable.ini'],[])
                self.assertEqual([name for name in files if Path(name).name in installer.WINDOWS_ONLY_GAME_FILES],[])
                for name,digest in files.items():self.assertEqual(installer.file_hash(root/name),digest,name)
                # Online play: every reviewed installation has online/ (its code in the receipt), its launcher and menu entry.
                bt3=adapter in installer.ADAPTERS
                self.assertEqual((root/'online/netplay/ttm_online.py').is_file(),bt3)
                self.assertEqual('online/netplay/ttm_online.py' in files,bt3)
                self.assertEqual((root/'Play online.sh').is_file(),bt3)
                self.assertEqual((root/'Tag Team Mod - Online.desktop').is_file(),bt3)
                status=json.loads((root/'install-status.json').read_text(encoding='utf-8'))
                self.assertEqual((status['ready'],status['stage'],status['adapter']),(True,'[6/6] Installed',adapter))
                # The bt3-usa folder serves both BT3 discs and carries the European address table.
                self.assertEqual('game/tools/pal_native_map.json' in files,adapter!='bt4-b14-rev2-eng')

    def test_the_windows_installation_of_each_adapter(self):
        for adapter,slot in (('bt3-usa',28011),('bt3-pal',28011),('bt4-b14-rev2-eng',28012)):
            with self.subTest(adapter=adapter):
                root,events=self.install(adapter,windows=True,name='win-'+adapter)
                game=root/'game'
                self.assertEqual(events[-1],'run:check_installation.py');self.assertIn('runtime_copy',events)
                self.assertEqual([e for e in events if e.startswith('run:')],
                                 ['run:autopilot.py','run:install_boot_hooks.py',*(['run:bt4_preflight.py'] if slot==28012 else []),
                                  'run:check_installation.py'])
                ini=configparser.ConfigParser(interpolation=None);ini.read(game/'runtime28/inis/PCSX2.ini',encoding='utf-8')
                self.assertEqual(ini['EmuCore']['PINESlot'],str(slot))
                self.assertEqual(json.loads((game/'player-install.json').read_text())['adapter'],adapter)
                receipt=json.loads((root/'installed-files.json').read_text(encoding='utf-8'))
                self.assertEqual((receipt['adapter'],receipt['emulator_version']),(adapter,'2.8.2.0'))
                self.assertNotIn('emulator_kind',receipt)
                readme=(root/'README.txt').read_text(encoding='utf-8')
                self.assertTrue(readme.startswith('Start Play.cmd.'))
                self.assertEqual(installer.EUROPEAN_NOTE in readme,adapter=='bt3-pal')
                for name in ('Play.cmd','Mod settings.cmd','Check installation.cmd','Scan compatibility.cmd','Build expanded maps.cmd'):
                    self.assertTrue((root/name).is_file(),name)
                # Online play: every reviewed adapter, with its own copy of the installation's PCSX2 build (online/pcsx2).
                bt3=adapter in installer.ADAPTERS
                self.assertEqual((root/'Play online.cmd').is_file(),bt3)
                self.assertEqual((root/'online/pcsx2/pcsx2-qt.exe').is_file(),bt3)
                self.assertEqual(events.count('runtime_copy'),2 if bt3 else 1)
                if bt3:
                    self.assertIn('"%~dp0.venv\\Scripts\\python.exe" "%~dp0online\\netplay\\ttm_online.py" %*',
                                  (root/'Play online.cmd').read_text(encoding='ascii'))
                    self.assertIn('online/pcsx2/pcsx2-qt.exe',receipt['files'])
                self.assertFalse(any(root.glob('*.sh')))
                status=json.loads((root/'install-status.json').read_text(encoding='utf-8'))
                self.assertEqual((status['ready'],status['adapter']),(True,adapter))

    def test_a_european_address_table_from_another_executable_stops_setup(self):
        for change in (dict(elf_sha256='0'*64),dict(dbzp_sha256='0'*64),dict(schema=0)):
            with self.subTest(change=change):
                name='pal-'+next(iter(change))
                with self.assertRaisesRegex(ValueError,'not made from this disc'):self.install('bt3-pal',table=change,name=name)
                root=(self.tmp/name).resolve()
                self.assertFalse((root/'Play.sh').exists());self.assertFalse((root/'game').exists())
                status=json.loads((root/'install-status.json').read_text(encoding='utf-8'))
                self.assertEqual(status['stage'],'FAILED');self.assertIn('[3/6]',status['failed_stage'])
        # The USA disc never reads that table.
        root,_=self.install('bt3-usa',table=dict(elf_sha256='0'*64),name='usa-any-table')
        self.assertTrue((root/'Play.sh').is_file())

    def test_an_unsupported_disc_is_named_in_the_setup_language(self):
        sys.path.insert(0,str(HERE.parent));self.addCleanup(sys.path.remove,str(HERE.parent))
        from iso_compatibility import known_discs
        match=known_discs.explain(SimpleNamespace(serial='SLPM_611.62',kind='unknown',members={}),dict(verified=False,reason='technical'))
        for language,expected in (('en','The selected ISO is the Japanese Dragon Ball Z: Sparking! Meteor demo'),
                                  ('es','La ISO elegida es la demo japonesa de Dragon Ball Z: Sparking! Meteor')):
            with self.subTest(language=language):
                with self.assertRaises(ValueError) as caught:self.install('bt3-usa',match=match,language=language,name='japan-'+language)
                self.assertIn(expected,str(caught.exception));self.assertIn('SLES-54945',str(caught.exception))
                root=(self.tmp/('japan-'+language)).resolve()
                self.assertFalse((root/'Play.sh').exists())
                self.assertIn(expected,json.loads((root/'install-status.json').read_text(encoding='utf-8'))['error'])

    def test_explicit_offline_install_publishes_play_but_is_not_ready(self):
        root,_=self.install('bt3-usa',missing=[checker.MISSING_OPENGL])
        status=json.loads((root/'install-status.json').read_text())
        self.assertFalse(status['ready']);self.assertTrue(status['installation_valid'])
        self.assertEqual(status['missing_runtime_dependencies'],[checker.MISSING_OPENGL])
        self.assertTrue((root/'Play.sh').is_file())

    def test_a_late_failure_leaves_no_play_sh(self):
        with self.assertRaisesRegex(ValueError,'Final installation check failed'):
            self.install('bt3-usa',failing='check_installation.py')
        root=(self.tmp/'bt3-usa').resolve()
        self.assertFalse((root/'Play.sh').exists())
        self.assertTrue((root/'Mod settings.sh').is_file(),'the other scripts are written before the check')
        status=json.loads((root/'install-status.json').read_text(encoding='utf-8'))
        self.assertEqual((status['ready'],status['stage']),(False,'FAILED'));self.assertIn('[5/6]',status['failed_stage'])
        with self.assertRaisesRegex(ValueError,'Offline runtime check failed: install_boot_hooks.py'):
            self.install('bt4-b14-rev2-eng',failing='install_boot_hooks.py')
        root=(self.tmp/'bt4-b14-rev2-eng').resolve()
        self.assertFalse((root/'Play.sh').exists());self.assertFalse((root/'Mod settings.sh').exists())


if __name__=='__main__':unittest.main()
