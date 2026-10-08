"""Player installation backend. No emulator is started by this program (on Linux the PCSX2 AppImage's
runtime only reports its size and unpacks its version file)."""
import argparse
import configparser
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import traceback
import zipfile

HERE=Path(__file__).resolve().parent
WINDOWS=os.name=='nt'
# Linux: the Pythons the bundled wheels-linux set serves (Install.sh and check_installation.py use the same list).
LINUX_PYTHONS=((3,11),(3,12),(3,13),(3,14))
# Windows device names, refused in payload paths on every system (Path.is_reserved only works on Windows).
RESERVED_NAMES=frozenset({'CON','PRN','AUX','NUL','CONIN$','CONOUT$',*(f'{device}{n}' for device in ('COM','LPT') for n in '123456789\xb9\xb2\xb3')})


def _setup_messages():
    """setup_messages.py beside this file (standard library only), also when this file is loaded by path."""
    if 'setup_messages' in sys.modules:return sys.modules['setup_messages']
    spec=importlib.util.spec_from_file_location('setup_messages',HERE/'setup_messages.py')
    module=importlib.util.module_from_spec(spec);sys.modules['setup_messages']=module;spec.loader.exec_module(module)
    return module


messages=_setup_messages()
SetupFailure=messages.SetupFailure


def require(ok,message,**details):
    """message: a messages.json code (raises SetupFailure with details) or an installer-es.json key (ValueError)."""
    if not ok:
        if messages.CODE.fullmatch(message):raise SetupFailure(message,**details)
        raise ValueError(message)


def size_text(size):
    """'512 KiB', '4 MiB', '3.5 GiB': floor to one decimal with integer arithmetic (install-player.ps1 matches it)."""
    size=int(size)
    for unit,name in ((1<<30,'GiB'),(1<<20,'MiB'),(1<<10,'KiB')):
        if size>=unit:
            tenths=size*10//unit
            return f'{tenths//10}'+(f'.{tenths%10}' if tenths%10 else '')+' '+name
    return f'{size} bytes'


# ---- Preflight: what the selected files are, before anything is changed --------------------------------------------
# The same sniffing as iso_compatibility.disc.image_problem (the scanner) and install-player.ps1 (Get-IsoProblem,
# Get-BiosProblem); test_b33c_setup_flow.PreflightSniffTests compares all three on the same files.
ARCHIVES=((b'7z\xbc\xaf\x27\x1c','7z'),(b'PK\x03\x04','ZIP'),(b'PK\x05\x06','ZIP'),(b'Rar!\x1a\x07','RAR'),(b'\x1f\x8b','gzip (.gz)'))
RAW_SYNC=b'\x00'+b'\xff'*10+b'\x00'
CUE_SHEET=re.compile(rb'(?:\xef\xbb\xbf)?\s*(?:FILE|REM|TRACK|CATALOG|PERFORMER|TITLE)\s',re.I)


def iso_problem(path):
    """(code, details) for a selected game image that is not a complete, plain ISO; None when it looks right."""
    path=Path(path);size=path.stat().st_size
    with path.open('rb') as stream:head=stream.read(0x10000)
    if head[:8]==b'MComprHD':return 'TTM-ISO-02',dict(format='CHD')
    if head[:4] in (b'CISO',b'ZISO'):
        kind=head[:1].decode('ascii')+'SO';return 'TTM-ISO-03',dict(format=kind,extension=kind.lower())
    for magic,name in ARCHIVES:
        if head.startswith(magic):return 'TTM-ISO-01',dict(format=name)
    if head.startswith(RAW_SYNC) or CUE_SHEET.match(head[:64]):return 'TTM-ISO-04',{}
    if size<0x8800 or len(head)<0x8058 or head[0x8000:0x8006]!=b'\x01CD001':return 'TTM-ISO-05',dict(size=size)
    expected=struct.unpack_from('<I',head,0x8050)[0]*2048
    if size<expected:return 'TTM-ISO-06',dict(size=size,expected=expected)
    return None


# The other files a BIOS dumper writes next to the BIOS (install-player.ps1 Get-BiosProblem uses the same list).
BIOS_COMPANIONS=('.rom1','.rom2','.erom','.nvm','.mec')


def bios_problem(path):
    """(code, details) for a selected file that is not a PS2 BIOS dump; None when it looks right. A BIOS is 2, 4 or
    8 MiB with a ROMDIR table naming ROMVER (PCSX2 identifies it by that entry). The .ROM1/.ROM2 parts of a dump are
    512 KiB with a ROMDIR table but no ROMVER: they are companion files (TTM-BIOS-06), not a PS1 BIOS (TTM-BIOS-02)."""
    path=Path(path);size=path.stat().st_size
    with path.open('rb') as stream:head=stream.read(16)
    for magic,name in ARCHIVES:
        if head.startswith(magic):return 'TTM-BIOS-04',dict(format=name)
    if head.startswith(b'SCEUF') or size>8<<20:return 'TTM-BIOS-03',dict(size=size_text(size))
    data=path.read_bytes() if size in (512<<10,2<<20,4<<20,8<<20) else b''
    if size==512<<10:return ('TTM-BIOS-06',dict(size=size_text(size))) if b'ROMDIR' in data else ('TTM-BIOS-02',{})
    if b'ROMDIR' in data and b'ROMVER' in data:return None
    if b'ROMDIR' in data or path.suffix.lower() in BIOS_COMPANIONS:return 'TTM-BIOS-06',dict(size=size_text(size))
    return 'TTM-BIOS-01',dict(size=size_text(size))


def require_image(problem,path):
    if problem:raise SetupFailure(problem[0],file=str(path),unchanged=None,**problem[1])


# ---- The BIOS the player's PCSX2 already uses -----------------------------------------------------------------------
# Without a selected BIOS, setup copies the one the selected PCSX2 is set up with. PCSX2 keeps its settings in
# <data folder>/inis/PCSX2.ini. Windows: a portable PCSX2 (portable.ini or portable.txt beside pcsx2-qt.exe) uses its
# program folder joined with the text of portable.txt (usually empty), any other the Documents folder. Linux: the
# AppImage uses $XDG_CONFIG_HOME/PCSX2 or ~/.config/PCSX2, which the AppImage runtime moves to <AppImage>.config or
# <AppImage>.home when those folders exist; markers beside the AppImage change nothing (PCSX2 looks inside the mounted
# image), only 'pcsx2 -portable' uses PCSX2/ beside it. install-player.ps1 (Find-ConfiguredBios) applies the same rules
# on Windows; test_configured_bios compares both.
# Settings that name no BIOS, or one that is missing, make PCSX2 start with the first PS2 BIOS its BIOS folder lists
# (BiosTools FindBiosImage). Windows lists an NTFS folder in name order ignoring case, so there setup takes that BIOS
# too; other drives, and Linux, list files in their own order, and setup asks when there are several.
PORTABLE_MARKERS=('portable.ini','portable.txt')
# The Flatpak PCSX2's settings: setup refuses that emulator, but the BIOS set up in it is the player's own.
FLATPAK_PROFILE=('.var','app','net.pcsx2.PCSX2','config','PCSX2')
# PCSX2 writes about 20 KiB of settings; a larger PCSX2.ini is not read. In a BIOS folder, at most this many files of a
# BIOS's size are read. A portable.txt longer than any Windows path names no folder PCSX2 can use.
SETTINGS_LIMIT=4<<20
BIOS_FOLDER_LIMIT=64
BIOS_SIZES=(2<<20,4<<20,8<<20)
# The smallest and largest file PCSX2's own BIOS search reads (MIN_BIOS_SIZE, MAX_BIOS_SIZE).
PCSX2_SEARCH_SIZES=(4<<20,8<<20)
PORTABLE_TEXT_LIMIT=32767
SETTINGS_LINE=re.compile(r'\r\n|\n|\r')
# What PCSX2's StringUtil::StripWhitespace removes (std::isspace), and what a Windows folder name cannot hold.
PCSX2_BLANKS=' \t\n\v\f\r'
NOT_IN_A_NAME=':<>"|?*'
# Setup's lines about a BIOS it found or asks for (installer-es.json translates them; install-player.ps1 has copies).
# The selected PCSX2's own settings say "your PCSX2"; the settings of another PCSX2 of this user say so.
BIOS_FROM_SETTINGS='the BIOS your PCSX2 uses, from'
BIOS_ONLY_ONE='the only PS2 BIOS in the BIOS folder of your PCSX2, from'
BIOS_FROM_OTHER='a PS2 BIOS set up in another PCSX2 on this PC, from'
BIOS_ONLY_OTHER='the only PS2 BIOS in the BIOS folder of another PCSX2 on this PC, from'
BIOS_FIRST='the BIOS your PCSX2 starts with, from'
BIOS_FIRST_OTHER='the BIOS another PCSX2 on this PC starts with, from'
BIOS_NONE_SET_UP='Your PCSX2 has no PS2 BIOS set up yet: choose your BIOS file.'
BIOS_SEVERAL='Your PCSX2 has several PS2 BIOS files and none is selected in its settings: choose the one to use.'
BIOS_SEVERAL_OTHER='Another PCSX2 on this PC has several PS2 BIOS files and none is selected in its settings: choose the one to use.'
BIOS_UNUSABLE='The BIOS set up in your PCSX2 cannot be used:'
BIOS_UNUSABLE_OTHER='The BIOS set up in another PCSX2 on this PC cannot be used:'
BIOS_MISSING='The BIOS set up in your PCSX2 is missing:'
BIOS_MISSING_OTHER='The BIOS set up in another PCSX2 on this PC is missing:'
BIOS_CHOOSE='Choose your PS2 BIOS file.'
BIOS_TEXTS=(BIOS_FROM_SETTINGS,BIOS_ONLY_ONE,BIOS_FROM_OTHER,BIOS_ONLY_OTHER,BIOS_FIRST,BIOS_FIRST_OTHER,BIOS_NONE_SET_UP,
            BIOS_SEVERAL,BIOS_SEVERAL_OTHER,BIOS_UNUSABLE,BIOS_UNUSABLE_OTHER,BIOS_MISSING,BIOS_MISSING_OTHER,BIOS_CHOOSE)
SETTINGS_OF=dict(own='PCSX2 settings: ',other='settings of another PCSX2 on this PC: ')


def documents_folder(environ=None):
    """The current user's Documents folder as PCSX2 finds it on Windows: the Known Folder, so a Documents folder moved
    to OneDrive or another drive is followed (install-player.ps1 asks .NET for the same folder). TAGTEAM_SETUP_DOCUMENTS
    overrides it (the installer's own tests)."""
    environ=os.environ if environ is None else environ
    if environ.get('TAGTEAM_SETUP_DOCUMENTS'):return Path(environ['TAGTEAM_SETUP_DOCUMENTS'])
    if WINDOWS:
        import ctypes,uuid
        pointer=ctypes.c_void_p()
        folder=(ctypes.c_ubyte*16).from_buffer_copy(uuid.UUID('FDD39AD0-238F-46AF-ADB4-6C85480369C7').bytes_le)
        try:
            shell=ctypes.WinDLL('shell32');shell.SHGetKnownFolderPath.restype=ctypes.c_long
            if shell.SHGetKnownFolderPath(ctypes.byref(folder),0,None,ctypes.byref(pointer))==0 and pointer.value:
                return Path(ctypes.wstring_at(pointer.value))
        except (OSError,AttributeError):pass
        finally:
            if pointer.value:ctypes.WinDLL('ole32').CoTaskMemFree(pointer)
    return Path(environ.get('USERPROFILE' if WINDOWS else 'HOME') or Path.home())/'Documents'


def portable_data_folder(program):
    """The data folder of a portable PCSX2 on Windows (EmuFolders::GetPortableModePath): the program folder joined with
    the text of portable.txt beside it, blanks trimmed, the way PCSX2's Path::Combine joins it (even an absolute value);
    the program folder itself when that file is missing, empty or unreadable. None when that text cannot be part of a
    folder path (a drive letter, a character Windows refuses in names, longer than any path): PCSX2 cannot start then."""
    try:
        with open(Path(program)/'portable.txt','rb') as stream:data=stream.read(PORTABLE_TEXT_LIMIT+1)
    except OSError:return Path(program)
    if len(data)>PORTABLE_TEXT_LIMIT:return None
    text=data.decode('utf-8','replace').strip(PCSX2_BLANKS)
    if not text:return Path(program)
    if any(char in NOT_IN_A_NAME or ord(char)<32 for char in text):return None
    return Path(os.path.abspath(str(program).rstrip('\\/')+'\\'+text))


def pcsx2_data_folders(pcsx2,windows=None,environ=None):
    """[(folder, own)]: the PCSX2 data folders whose inis/PCSX2.ini setup reads, in order, each once. The first
    (own=True) is the one the selected PCSX2 starts with. Windows: portable (portable.ini or portable.txt beside
    pcsx2-qt.exe), portable_data_folder (none when portable.txt names no usable folder); else Documents/PCSX2. Linux:
    <AppImage>.config/PCSX2 when the AppImage runtime finds that writable folder beside the real file (it becomes
    $XDG_CONFIG_HOME), else $XDG_CONFIG_HOME/PCSX2 when that is an absolute path, else ~/.config/PCSX2 (HOME being
    <AppImage>.home when that folder is there). The others are where another PCSX2 of this user keeps its settings:
    Windows %USERPROFILE%/Documents/PCSX2 and the program folder; Linux $XDG_CONFIG_HOME/PCSX2, ~/.config/PCSX2, the
    Flatpak PCSX2's settings and PCSX2/ beside the AppImage (where 'pcsx2 -portable' keeps them)."""
    windows=WINDOWS if windows is None else windows
    environ=os.environ if environ is None else environ
    if windows:
        program=Path(os.path.abspath(pcsx2)).parent;user=[documents_folder(environ)/'PCSX2']
        if environ.get('USERPROFILE'):user.append(Path(environ['USERPROFILE'])/'Documents'/'PCSX2')
        if any(is_file(program/name) for name in PORTABLE_MARKERS):
            own=portable_data_folder(program)
            rows=([(own,True)] if own is not None else [])+[(folder,False) for folder in user]+[(program,False)]
        else:rows=[(user[0],True)]+[(folder,False) for folder in user[1:]]+[(program,False)]
    else:
        # The AppImage runtime names its portable folders after the real file (/proc/self/exe) and uses them when they
        # are writable (access W_OK).
        appimage=os.path.realpath(pcsx2);home=environ.get('HOME') or str(Path.home())
        xdg=environ.get('XDG_CONFIG_HOME') or ''
        if os.access(appimage+'.config',os.W_OK):own=Path(appimage+'.config')/'PCSX2'
        elif xdg.startswith('/'):own=Path(xdg)/'PCSX2'
        else:own=Path(appimage+'.home' if os.access(appimage+'.home',os.W_OK) else home)/'.config'/'PCSX2'
        others=([Path(xdg)/'PCSX2'] if xdg.startswith('/') else [])+[Path(home)/'.config'/'PCSX2',Path(home).joinpath(*FLATPAK_PROFILE),
                                                                     Path(appimage).parent/'PCSX2']
        rows=[(own,True)]+[(folder,False) for folder in others]
    unique,seen=[],set()
    for folder,own in rows:
        folder=Path(os.path.abspath(folder));key=os.path.normcase(str(folder))
        if key not in seen:seen.add(key);unique.append((folder,own))
    return unique


def read_pcsx2_settings(path):
    """{'folders': {...}, 'filenames': {...}} of a PCSX2.ini, read like PCSX2's INI reader: section and key names in
    lower case, ; and # lines are comments, spaces and tabs around names and values are dropped, the first value of a
    repeated key counts. None when the file cannot be read or is too large to be PCSX2's settings."""
    try:
        path=Path(path)
        if path.stat().st_size>SETTINGS_LIMIT:return None
        text=path.read_bytes().decode('utf-8','replace').removeprefix('\ufeff')
    except OSError:return None
    found={'folders':{},'filenames':{}};section=None
    for line in SETTINGS_LINE.split(text):
        line=line.strip(' \t')
        if not line or line[0] in ';#':continue
        if line[0]=='[':
            section=line[1:line.index(']')].strip(' \t').lower() if ']' in line else None
            continue
        if section in found and '=' in line:
            key,_,value=line.partition('=')
            found[section].setdefault(key.strip(' \t').lower(),value.strip(' \t'))
    return found


def pcsx2_absolute(value,windows=None):
    """PCSX2's Path::IsAbsolute: a drive with a separator ('C:\\', 'C:/') or '\\\\' on Windows, a leading '/' elsewhere;
    anything else is relative to the data folder."""
    windows=WINDOWS if windows is None else windows
    return bool(re.match(r'[A-Za-z]:[\\/]|\\\\',value)) if windows else value.startswith('/')


def pcsx2_path(base,value,windows=None):
    """A Folders/Bios or Filenames/BIOS value as PCSX2 opens it: as it is when absolute, else joined to base the way
    PCSX2's Path::Combine does (base, one separator, value), then made absolute (install-player.ps1 Get-Pcsx2Path)."""
    if pcsx2_absolute(value,windows):return Path(os.path.abspath(value))
    return Path(os.path.abspath(str(base).rstrip('\\/')+os.sep+value))


def is_file(path):
    """Path.is_file, but False for a path that cannot be checked (no permission, invalid characters)."""
    try:return Path(path).is_file()
    except (OSError,ValueError):return False


def folder_order(name):
    """The sort key of the order Windows lists an NTFS folder in, which the OrdinalIgnoreCase sort of install-player.ps1
    matches: each character in upper case (when that is one character), compared by UTF-16 code unit."""
    return ''.join(char.upper() if len(char.upper())==1 else char for char in name).encode('utf-16-be')


def folder_files(folder):
    """The files directly in folder (not in its subfolders), in folder_order."""
    return sorted((path for path in Path(folder).iterdir() if is_file(path)),key=lambda path:folder_order(path.name))


def bios_choices(folder):
    """The PS2 BIOS files in a BIOS folder that pass bios_problem (folder_files), sorted by name ignoring case, as
    PCSX2 would offer them. A copy with the same bytes as an earlier file is the same BIOS and is left out. Only the
    first BIOS_FOLDER_LIMIT files of a BIOS's size are read."""
    try:files=folder_files(folder)
    except (OSError,ValueError):return []
    found=[];read=0;seen=set()
    for path in files:
        try:
            if path.stat().st_size not in BIOS_SIZES:continue
            read+=1
            if read>BIOS_FOLDER_LIMIT:break
            if bios_problem(path) is not None:continue
            digest=file_hash(path)
            if digest not in seen:seen.add(digest);found.append(path)
        except OSError:continue
    return found


def listed_in_name_order(folder,environ=None):
    """Whether Windows lists folder in folder_order, so that the first file PCSX2 finds there is known: a folder of a
    local NTFS drive. FAT32 and exFAT list files in the order they were written, a network drive in the order of the
    computer that holds it. False off Windows, for a network path, and through a junction or symbolic link (the folder
    is then on another drive). TAGTEAM_SETUP_FILE_SYSTEM stands for the drive's file system (the installer's own
    tests); install-player.ps1 (Test-ListedInNameOrder) asks .NET's DriveInfo the same."""
    environ=os.environ if environ is None else environ
    try:
        folder=Path(os.path.abspath(folder));root=folder.anchor
        if not root or root.startswith(('\\\\','//')):return False
        for item in (folder,*folder.parents):
            if not (item.exists() or item.is_symlink()):continue
            if item.is_symlink() or getattr(item.lstat(),'st_file_attributes',0)&stat.FILE_ATTRIBUTE_REPARSE_POINT:return False
        if environ.get('TAGTEAM_SETUP_FILE_SYSTEM'):return environ['TAGTEAM_SETUP_FILE_SYSTEM']=='NTFS'
        if not WINDOWS:return False
        import ctypes
        kernel=ctypes.WinDLL('kernel32');name=ctypes.create_unicode_buffer(261)
        if kernel.GetDriveTypeW(root)==4:return False  # DRIVE_REMOTE
        if not kernel.GetVolumeInformationW(root,None,0,None,None,None,name,len(name)):return False
        return name.value=='NTFS'
    except (OSError,ValueError,AttributeError):return False


def pcsx2_first_bios(folder):
    """The BIOS PCSX2 starts with when its settings name none, or one that is missing (FindBiosImage): the first file
    of its BIOS folder, in folder_order, that is 4 to 8 MiB and passes bios_problem. PCSX2's listing leaves hidden files
    out. As in bios_choices, only the first BIOS_FOLDER_LIMIT files of a BIOS's size are read. None when there is none."""
    try:files=folder_files(folder)
    except (OSError,ValueError):return None
    read=0
    for path in files:
        try:
            info=path.stat()
            if info.st_size not in BIOS_SIZES:continue
            read+=1
            if read>BIOS_FOLDER_LIMIT:break
            if getattr(info,'st_file_attributes',0)&stat.FILE_ATTRIBUTE_HIDDEN:continue
            if PCSX2_SEARCH_SIZES[0]<=info.st_size<=PCSX2_SEARCH_SIZES[1] and bios_problem(path) is None:return path
        except OSError:continue
    return None


def configured_bios(pcsx2,windows=None,environ=None):
    """The BIOS the selected PCSX2 is set up with. In each data folder (pcsx2_data_folders) with an inis/PCSX2.ini:
    Filenames/BIOS inside Folders/Bios (default 'bios'; both relative to the data folder unless absolute) when it
    passes bios_problem, else the only PS2 BIOS in that folder (PCSX2 falls back to it too), else, on Windows when the
    settings name no BIOS or a missing one and the folder is listed_in_name_order, the BIOS PCSX2 starts with
    (pcsx2_first_bios). The first folder that gives one wins. The selected PCSX2's own settings with several BIOS files
    and none usable selected otherwise end the search: setup must ask. Returns a dict: bios (None when none was found),
    own (it comes from the selected PCSX2's own settings, not another PCSX2's), settings (its PCSX2.ini), how
    ('configured', 'only', 'first' or None), folder (the BIOS folder to ask in), choices (the usable BIOS files there),
    rejected (a configured file of those settings that is missing or not a PS2 BIOS, also when the only PS2 BIOS of its
    folder, or the one PCSX2 starts with, was taken instead), rejected_code and rejected_values (its bios_problem; None
    when missing) and checked (every PCSX2.ini path setup looked for)."""
    windows=WINDOWS if windows is None else windows
    checked,fallback=[],None
    def result(**values):
        row=dict(bios=None,own=False,settings=None,how=None,folder=None,choices=[],rejected=None,rejected_code=None,rejected_values={})
        row.update(values);row['checked']=list(checked);return row
    for data,own in pcsx2_data_folders(pcsx2,windows,environ):
        ini=data/'inis'/'PCSX2.ini';checked.append(str(ini))
        settings=read_pcsx2_settings(ini) if is_file(ini) else None
        if settings is None:continue
        try:
            folder=pcsx2_path(data,settings['folders'].get('bios','bios'),windows)
            name=settings['filenames'].get('bios','');rejected=code=None;values={}
            if name:
                path=pcsx2_path(folder,name,windows)
                problem=bios_problem(path) if is_file(path) else ('missing',{})
                if problem is None:return result(bios=str(path),own=own,settings=str(ini),how='configured',folder=str(folder))
                rejected=str(path);code,values=(None,{}) if problem[0]=='missing' else problem
            choices=bios_choices(folder)
            if len(choices)==1:return result(bios=str(choices[0]),own=own,settings=str(ini),how='only',folder=str(folder),
                                             rejected=rejected,rejected_code=code,rejected_values=values)
            # PCSX2 replaces a BIOS setting that is empty or names a missing file, not a file that is not a PS2 BIOS.
            if len(choices)>1 and windows and code is None and listed_in_name_order(folder,environ):
                first=pcsx2_first_bios(folder)
                if first is not None:return result(bios=str(first),own=own,settings=str(ini),how='first',folder=str(folder),
                                                   rejected=rejected)
            found=result(own=own,settings=str(ini),folder=str(folder) if folder.is_dir() else None,choices=[str(path) for path in choices],
                         rejected=rejected,rejected_code=code,rejected_values=values)
        except (OSError,ValueError):continue
        if own and len(choices)>1:return found
        if fallback is None and (choices or rejected):fallback=found
    return dict(fallback,checked=list(checked)) if fallback else result()


def find_configured_bios(pcsx2,windows=None,environ=None):
    """configured_bios for setup: an unexpected error while reading the PCSX2 settings only means that no BIOS was found
    (setup then asks, or an unattended setup stops with TTM-BIOS-07 naming the error); it never stops setup itself."""
    try:return configured_bios(pcsx2,windows,environ)
    except Exception as error:  # noqa: BLE001 (a convenience must not stop setup)
        return dict(bios=None,own=False,settings=None,how=None,folder=None,choices=[],rejected=None,rejected_code=None,
                    rejected_values={},checked=[],error=f'{type(error).__name__}: {error}')


def bios_origin(found,translate=lambda text:text):
    """' (the BIOS your PCSX2 uses, from <PCSX2.ini>)' after a BIOS setup found itself ('a PS2 BIOS set up in another
    PCSX2 on this PC' when it comes from another PCSX2's settings), ' (the BIOS your PCSX2 starts with, from <BIOS
    folder>)' for pcsx2_first_bios; '' for a selected BIOS."""
    if not found or not found.get('bios'):return ''
    if found['how']=='first':return ' ('+translate(BIOS_FIRST if found['own'] else BIOS_FIRST_OTHER)+' '+found['folder']+')'
    if found['how']=='configured':text=BIOS_FROM_SETTINGS if found['own'] else BIOS_FROM_OTHER
    else:text=BIOS_ONLY_ONE if found['own'] else BIOS_ONLY_OTHER
    return ' ('+translate(text)+' '+found['settings']+')'


def bios_notes(found,language='en'):
    """The lines setup prints about the PCSX2 settings it read: a configured BIOS it cannot use (setup then took the only
    PS2 BIOS of that folder or the one PCSX2 starts with, or asks) and, when it found no BIOS, why it asks. [] when there
    is nothing to say."""
    L=translator(language);lines=[];own=found['own']
    if found['rejected'] and found['rejected_code']:
        lines+=[L(BIOS_UNUSABLE if own else BIOS_UNUSABLE_OTHER)+' '+found['rejected'],
                messages.line(found['rejected_code'],language,**found['rejected_values'])]
    elif found['rejected']:lines.append(L(BIOS_MISSING if own else BIOS_MISSING_OTHER)+' '+found['rejected'])
    if found['bios']:return lines
    if len(found['choices'])>1:lines.append(L(BIOS_SEVERAL if own else BIOS_SEVERAL_OTHER))
    else:lines.append(L(BIOS_CHOOSE) if found['rejected'] else L(BIOS_NONE_SET_UP))
    return lines


def configured_bios_failure(found):
    """The coded failure of an unattended setup (no dialogs) whose PCSX2 settings give no BIOS it can use: several BIOS
    files and none selected (TTM-BIOS-08), the configured file's own problem (TTM-BIOS-01..06), or none (TTM-BIOS-07,
    naming a configured file that is missing, else every settings file setup looked for). The details name the settings
    file, and say when it is another PCSX2's. install-player.ps1 (Get-ConfiguredBiosFailure) builds the same failures."""
    settings=SETTINGS_OF['own' if found['own'] else 'other']+found['settings'] if found['settings'] else ''
    rejected=found['rejected'] and ('selected BIOS '+('not usable ('+found['rejected_code']+')' if found['rejected_code'] else 'missing')+
                                    ': '+found['rejected'])
    detail='; '.join(part for part in (rejected,settings) if part)
    if len(found['choices'])>1:
        return SetupFailure('TTM-BIOS-08',file=found['folder'],count=len(found['choices']),detail=detail)
    if found['rejected'] and found['rejected_code']:
        return SetupFailure(found['rejected_code'],file=found['rejected'],detail=settings,**found['rejected_values'])
    if found['rejected']:return SetupFailure('TTM-BIOS-07',file=found['rejected'],detail=detail)
    return SetupFailure('TTM-BIOS-07',file=found['checked'],detail=found.get('error',''))


def file_hash(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def no_reparse(path,code='TTM-DEST-07'):
    """Refuse a junction or symbolic link at path or above it: TTM-DEST-07 for the installation path, TTM-PCSX2-07 for
    an item of the PCSX2 folder setup copies."""
    path=Path(path).absolute()
    for item in (path,*path.parents):
        if item.exists() or item.is_symlink():
            if item.is_symlink() or getattr(item.lstat(),'st_file_attributes',0)&stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise SetupFailure(code,file=str(item),name=item.name,detail='Use ordinary folders, not junctions or symlinks')


def reserved_name(part):
    """A Windows device name such as 'NUL', 'com1.txt' or 'LPT3 .log'."""
    return part.partition('.')[0].partition(':')[0].rstrip(' ').upper() in RESERVED_NAMES


def python_supported(version=None):
    """Windows: exactly the reviewed 3.11. Linux: every CPython the bundled Linux wheels serve."""
    version=tuple((version or sys.version_info)[:2])
    return version==(3,11) if WINDOWS else version in LINUX_PYTHONS


def data_folder(runtime):
    """PCSX2's data folder: the runtime folder itself on Windows; for the Linux AppImage started with -portable,
    PCSX2 uses dirname($APPIMAGE)/PCSX2 (runtime_profile.DATA)."""
    runtime=Path(runtime)
    return runtime if WINDOWS else runtime/'PCSX2'


def release_info():
    return json.loads((HERE/'release.json').read_text(encoding='utf-8'))


# Each adapter's installation contract. payload: the payload folder that becomes game/. The European and Japanese
# BT3 discs (bt3-pal, bt3-jpn) run the bt3-usa tools, which take their addresses from tools/pal_native_map.json or
# tools/jpn_native_map.json at run time, so the payload holds no second copy of them. pine_slot: PCSX2's PINE slot for that adapter's tools. preflight: an extra
# offline check in game/tools. native_map: the address table in game/tools that must have been made from exactly
# the player's executable and DBZP.BIN. check_installation.ADAPTERS mirrors pine_slot, preflight and native_map.
ADAPTERS={
    'bt3-usa':dict(payload='bt3-usa',pine_slot=28011,preflight=None,native_map=None),
    'bt3-pal':dict(payload='bt3-usa',pine_slot=28011,preflight=None,native_map='pal_native_map.json'),
    'bt3-jpn':dict(payload='bt3-usa',pine_slot=28011,preflight=None,native_map='jpn_native_map.json'),
    'bt4-b14-rev2-eng':dict(payload='bt4-b14-rev2-eng',pine_slot=28012,preflight='bt4_preflight.py',native_map=None),
}


def adapter_contract(adapter,release=None):
    """ADAPTERS[adapter], for an adapter this installer knows and (given release.json) this release enables."""
    require(adapter in ADAPTERS and (release is None or adapter in release['adapters']),'Adapter is not enabled in this release')
    return ADAPTERS[adapter]


def socket_suffix(slot):
    """The Linux PINE socket name suffix: PCSX2 appends .<slot> unless the slot is 28011."""
    return '' if slot==28011 else f'.{slot}'


def check_native_map(path,profile):
    """The shipped address table must be the one made from this disc's own executable and DBZP.BIN."""
    path=Path(path)
    require(path.is_file(),'TTM-PAYLOAD-01',detail='Player payload is missing tools/'+path.name)
    table=json.loads(path.read_text(encoding='utf-8'))
    identity=profile['identity'];members=identity['members']
    require(table.get('schema')==1 and table.get('adapter')==identity['adapter'] and
            table.get('elf_sha256')==members.get('/'+identity['serial']+';1') and
            table.get('dbzp_sha256')==members.get('/BIN/DBZP.BIN;1'),
            'TTM-PAYLOAD-04',detail='tools/'+path.name)
    return table


SEE_REPORT='See COMPATIBILITY.md for the exact variant and resource inventory.'


def refusal_message(profile,translate=lambda text:text):
    """Why the scanned disc cannot be installed, naming the disc and the supported discs, in the setup language.
    The scanner stores the pieces (iso_compatibility.known_discs); installer-es.json translates each of them."""
    match=profile.get('identity',{}).get('runtime_match',{})
    refusal=match.get('refusal')
    if refusal:
        text=(translate(refusal['template']).format(disc=translate(refusal['disc']) if refusal.get('disc') else '',serial=refusal['serial'])
              +' '+translate(refusal['supported']))
    else:
        text='Unknown executable/add-on: '+match.get('reason','No reviewed runtime adapter matches this disc.')
    return text+' '+translate(SEE_REPORT)


def version_parts(text):
    """(major, minor, patch) of '2.8.2.0', 'v2.7.361' or 'PCSX2 v2.8.2-nightly'; None when unreadable."""
    match=re.match(r'\s*(?:PCSX2\s+)?v?(\d{1,6})\.(\d{1,6})\.(\d{1,6})(?!\d)',str(text or ''),re.IGNORECASE)
    return tuple(map(int,match.groups())) if match else None


def pcsx2_support(version,release):
    """(accepted, tested) under release.json: any PCSX2 2.x from pcsx2_minimum on is accepted,
    nightlies and later releases included; tested means listed in pcsx2_supported.
    game/tools/pcsx2_versions.json holds the same policy for the launcher and PINE checks."""
    parts=version_parts(version);minimum=version_parts(release['pcsx2_minimum'])
    accepted=parts is not None and parts[0]==minimum[0] and parts>=minimum
    return accepted,accepted and parts in {version_parts(v) for v in release['pcsx2_supported']}


def check_version_policy(tools,release):
    """The runtime's pcsx2_versions.json must state release.json's minimum and tested releases."""
    path=Path(tools)/'pcsx2_versions.json'
    require(path.is_file(),'Player payload is missing tools/pcsx2_versions.json; obtain a complete installer')
    policy=json.loads(path.read_text(encoding='utf-8'))
    require(policy.get('player_minimum')==release['pcsx2_minimum'] and policy.get('tested')==release['pcsx2_supported'],
            'Player payload and release.json disagree about the supported PCSX2 versions')


def pcsx2_refusal(version,release,platform,detail=''):
    """The coded refusal of an unsupported PCSX2: too new (a later major version, e.g. 3.x) or too old."""
    parts=version_parts(version);minimum=version_parts(release['pcsx2_minimum'])
    if parts is None:return SetupFailure('TTM-PCSX2-06',detail='version '+str(version or 'unknown'))
    code='TTM-PCSX2-03' if parts[0]>minimum[0] else 'TTM-PCSX2-02'
    return SetupFailure(code,version='.'.join(map(str,parts)),minimum=release['pcsx2_minimum'],platform=platform,detail=detail)


# PE machine field -> the name a player can check on the download page.
PE_MACHINES={0x014c:'32-bit x86',0xaa64:'ARM64',0x01c4:'ARM'}


def pcsx2_version(path,release=None):
    if not WINDOWS:
        release=release or release_info();version=appimage_version(path)[0]
        require_supported_appimage(version,release)
        return version
    import ctypes
    from ctypes import wintypes
    require(os.name=='nt','TTM-OS-01',needed='Windows x64',found=sys.platform)
    path=Path(path)
    with path.open('rb') as stream:
        require(stream.read(2)==b'MZ','TTM-PCSX2-01',file=str(path))
        stream.seek(0x3c);offset=struct.unpack('<I',stream.read(4))[0]
        stream.seek(offset);header=stream.read(6)
        require(header[:4]==b'PE\0\0','TTM-PCSX2-01',file=str(path))
        machine=struct.unpack('<H',header[4:6])[0] if len(header)==6 else 0
        require(machine==0x8664,'TTM-PCSX2-04',file=str(path),machine=PE_MACHINES.get(machine,f'machine 0x{machine:04x}'))
    api=ctypes.WinDLL('version',use_last_error=True)
    api.GetFileVersionInfoSizeW.argtypes=[wintypes.LPCWSTR,ctypes.POINTER(wintypes.DWORD)]
    api.GetFileVersionInfoW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID]
    api.VerQueryValueW.argtypes=[wintypes.LPCVOID,wintypes.LPCWSTR,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(wintypes.UINT)]
    size=api.GetFileVersionInfoSizeW(str(path),None);require(size,'TTM-PCSX2-06',file=str(path),detail='no version resource')
    data=ctypes.create_string_buffer(size)
    require(api.GetFileVersionInfoW(str(path),0,size,data),'TTM-PCSX2-06',file=str(path),detail='GetFileVersionInfoW failed')
    value=ctypes.c_void_p();length=wintypes.UINT()
    require(api.VerQueryValueW(data,'\\',ctypes.byref(value),ctypes.byref(length)) and length.value>=52,'TTM-PCSX2-06',
            file=str(path),detail='invalid version resource')
    info=ctypes.cast(value,ctypes.POINTER(wintypes.DWORD))
    version='.'.join(map(str,(info[2]>>16,info[2]&0xffff,info[3]>>16,info[3]&0xffff)))
    release=release or release_info()
    if not pcsx2_support(version,release)[0]:raise pcsx2_refusal(version,release,'Windows x64',detail='received '+version)
    return version


# ---- Linux: the official PCSX2 AppImage ------------------------------------------------------------------

FLATPAK_REFUSED=('Flatpak PCSX2 is not supported: its sandbox hides the PINE connection and this private profile from the mod. '
                 'Download the official PCSX2 AppImage (link in README.md) and select that file.')
NOT_ELF='Not a Linux program. Select the PCSX2 AppImage (pcsx2-vX.Y.Z-linux-appimage-x64-Qt.AppImage).'
NOT_X86_64='PCSX2 must be the x86-64 (64-bit Intel/AMD) AppImage.'
NOT_APPIMAGE=('This PCSX2 is not an AppImage (a distribution package or an extracted AppImage). Select the official PCSX2 '
              'AppImage; distribution packages are not supported yet.')
UNKNOWN_VERSION=('Could not read the PCSX2 version from this AppImage. Select the official PCSX2 AppImage under its original '
                 'file name (pcsx2-vX.Y.Z-linux-appimage-x64-Qt.AppImage).')
CANNOT_RUN=('The PCSX2 AppImage cannot run from the installation folder (a file system mounted noexec, or a damaged download). '
            'Choose a folder in your home directory, or download the AppImage again.')
# Official release asset names: pcsx2-v2.8.2-linux-appimage-x64-Qt.AppImage (the fallback when metainfo is unreadable).
APPIMAGE_FILE_NAME=re.compile(r'pcsx2-v(\d{1,6}\.\d{1,6}\.\d{1,6})(?!\d)[-.]',re.IGNORECASE)
# Where Flatpak keeps installed apps and their data: the system and user installations and the per-app home.
# Only these folders mean Flatpak; an AppImage kept in any other folder named "flatpak" is fine.
FLATPAK_ROOTS=re.compile(r'/var/lib/flatpak/|/\.local/share/flatpak/|/\.var/app/')


def appimage_check(path):
    """Refuse anything but an x86-64 type-2 AppImage (ELF with 'AI\\x02' at offset 8), explaining Flatpak builds."""
    path=Path(path)
    text=str(path.absolute()).replace('\\','/')
    if path.suffix.lower()=='.flatpak' or FLATPAK_ROOTS.search(text):raise ValueError(FLATPAK_REFUSED)
    with path.open('rb') as stream:head=stream.read(64)
    require(head[:4]==b'\x7fELF',NOT_ELF)
    require(len(head)>=20 and head[4]==2 and head[5]==1 and head[18:20]==b'\x3e\x00',NOT_X86_64)
    require(head[8:11]==b'AI\x02',NOT_APPIMAGE)


def appimage_environment():
    """The AppImage runtime would act on TARGET_APPIMAGE instead of itself, or extract-and-run: never inherit those."""
    return {k:v for k,v in os.environ.items() if k not in ('TARGET_APPIMAGE','APPIMAGE_EXTRACT_AND_RUN','APPIMAGE','APPDIR','ARGV0','OWD')}


def appimage_offset(path):
    """--appimage-offset needs neither FUSE nor a display and starts no emulator: it proves the file runs here."""
    try:
        result=subprocess.run([str(path),'--appimage-offset'],env=appimage_environment(),stdin=subprocess.DEVNULL,
                              capture_output=True,text=True,timeout=60)
    except (OSError,subprocess.SubprocessError) as error:raise ValueError(CANNOT_RUN+' ('+str(error)+')') from error
    require(result.returncode==0 and result.stdout.strip().isdigit(),CANNOT_RUN)
    return int(result.stdout)


def appimage_metainfo_version(path):
    """'2.8.2' from usr/share/metainfo/*.xml (<release version="v2.8.2" .../>), unpacked in a fresh temporary folder."""
    with tempfile.TemporaryDirectory(prefix='tagteam-appimage-') as folder:
        try:
            subprocess.run([str(path),'--appimage-extract','usr/share/metainfo'],cwd=folder,env=appimage_environment(),
                           stdin=subprocess.DEVNULL,capture_output=True,timeout=120)
        except (OSError,subprocess.SubprocessError):return None
        for xml in sorted(Path(folder).glob('squashfs-root/usr/share/metainfo/*.xml')):
            if xml.is_symlink() or not xml.is_file():continue
            match=re.search(r'<release\b[^>]*\bversion="([^"]+)"',xml.read_text(encoding='utf-8',errors='replace'))
            if match and version_parts(match.group(1)):return '.'.join(map(str,version_parts(match.group(1))))
    return None


def appimage_version(path,copy_to=None):
    """(version, how it was read) of a PCSX2 AppImage: its metainfo release, else the official file name.

    With copy_to the AppImage is copied there first (0755) and must run from that copy; a download that is not
    executable is otherwise probed through a private temporary copy. Raises ValueError for Flatpak, non-AppImage
    and unreadable files."""
    path=Path(path);appimage_check(path)
    with tempfile.TemporaryDirectory(prefix='tagteam-pcsx2-') as folder:
        probe=path
        if copy_to is not None:
            probe=Path(copy_to);shutil.copyfile(path,probe);probe.chmod(0o755);appimage_offset(probe)
        elif not os.access(path,os.X_OK):
            probe=Path(folder)/'pcsx2-qt.AppImage';shutil.copyfile(path,probe);probe.chmod(0o700)
        version=appimage_metainfo_version(probe)
    if version is not None:return version,'AppImage metainfo'
    match=APPIMAGE_FILE_NAME.match(path.name)
    require(match,UNKNOWN_VERSION)
    return match.group(1),'file name'


def require_supported_appimage(version,release):
    if not pcsx2_support(version,release)[0]:raise pcsx2_refusal(version,release,'Linux x86-64 (AppImage)')


# The Linux AppImage refusals above are installer-es.json keys; setup shows each with its own code.
PCSX2_REASON_CODES={FLATPAK_REFUSED:'TTM-PCSX2-10',NOT_ELF:'TTM-PCSX2-11',NOT_X86_64:'TTM-PCSX2-12',NOT_APPIMAGE:'TTM-PCSX2-13',
                    UNKNOWN_VERSION:'TTM-PCSX2-14',CANNOT_RUN:'TTM-PCSX2-15'}


# Payload files of each adapter's game/ folder that only Windows uses (build_player_bundle.payload_files).
WINDOWS_ONLY_GAME_FILES=('launch-autopilot.ps1','launcher-lifecycle.ps1','launch-settings.ps1','Mod settings.cmd')


def appimage_runtime(appimage,destination):
    """Linux runtime folder: only the AppImage (0755); PCSX2 keeps its profile in PCSX2/ beside it."""
    destination=Path(destination);destination.mkdir(exist_ok=False)
    target=destination/'pcsx2-qt.AppImage';os.replace(appimage,target);target.chmod(0o755)
    require(target.is_file(),'PCSX2 application was not copied')
    return target


def unpack(payload,destination):
    no_reparse(destination)
    destination=Path(destination).resolve()
    receipt=json.loads(payload.with_suffix('.json').read_text())
    require(file_hash(payload)==receipt['sha256'],'Player payload checksum failed; obtain a complete installer')
    with zipfile.ZipFile(payload) as archive:
        manifest=json.loads(archive.read('payload-manifest.json'))
        require(len(archive.namelist())==len(manifest)+1 and set(archive.namelist())==set(manifest)|{'payload-manifest.json'},'Unexpected or duplicated payload members')
        # The online part's two blank memory cards (8.25 MiB each, a few KiB compressed) are the only larger members.
        require(sum(i.file_size for i in archive.infolist())<96<<20 and
                all(i.file_size<(9<<20 if i.filename in ONLINE_LARGE else 4<<20) for i in archive.infolist()),
                'Excessive payload expansion size')
        pending=[];names=set()
        for name,digest in manifest.items():
            target=(destination/name).resolve()
            parts=name.split('/')
            require(target.is_relative_to(destination) and '\\' not in name and ':' not in name and
                    all(p and p not in ('.','..') and not p.endswith((' ','.')) and
                        not reserved_name(p) for p in parts),'Unsafe payload path')
            require(name.casefold() not in names,'Case-colliding payload path');names.add(name.casefold())
            require(not stat.S_ISLNK(archive.getinfo(name).external_attr>>16),'Payload symlinks are not supported')
            no_reparse(target)
            data=archive.read(name)
            require(hashlib.sha256(data).hexdigest()==digest,'Payload file checksum failed: '+name)
            require(not target.exists(),'Payload destination is occupied: '+str(target))
            pending.append((target,data))
        # Validate every member before creating any file, then never overwrite.
        for target,data in pending:
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as stream:stream.write(data)


def runtime_copy(source,destination):
    # The source is only read: resolve it first, so a PCSX2 reached through a junction (Scoop's apps\pcsx2\current)
    # is accepted. Reparse points are still refused inside it and anywhere on the destination path.
    no_reparse(destination)
    source=Path(source).resolve();destination=Path(destination).resolve()
    # Copy application dependencies only. No cards, states, game paths,
    # developer dumps, cheats or settings are taken from the old emulator.
    names={'resources','translations','qtplugins','d3d12','docs','platforms','styles','imageformats','iconengines','tls','networkinformation'}
    require(source!=destination and not any(destination.is_relative_to(source/name) for name in names),
            'TTM-DEST-11',file=str(destination),detail='Installation cannot be inside a PCSX2 application dependency folder')
    destination.mkdir(parents=True,exist_ok=False)
    for path in source.iterdir():
        if path.is_file() and (path.suffix.lower() in ('.dll','.json') or path.name.lower() in ('pcsx2-qt.exe','qt.conf')):
            no_reparse(path,'TTM-PCSX2-07')
            shutil.copy2(path,destination/path.name)
        elif path.is_dir() and path.name.lower() in names:
            no_reparse(path,'TTM-PCSX2-07')
            for p in path.rglob('*'):no_reparse(p,'TTM-PCSX2-07')
            shutil.copytree(path,destination/path.name)
    require((destination/'pcsx2-qt.exe').is_file(),'PCSX2 application was not copied')
    require(any(destination.rglob('qwindows.dll')),'TTM-PCSX2-05',file=str(source),missing=r'QtPlugins\platforms\qwindows.dll')


# ---- Online play (TTM Online, part of the installation since kit 2.1) ------------------------------------------------
# The payload's online/ folder (the online lobby and its netplay code, match/ templates, README / LEAME) becomes
# <installation>/online. Windows: online/pcsx2 is a second copy of the installation's own PCSX2 build (runtime_copy),
# so the online PCSX2 profile (its settings, memory cards and states) never touches the offline one; Linux: the
# installation's AppImage, with its own configuration folder (online/linux). 'Play online.cmd' / 'Play online.sh' start
# it with the installation's .venv Python; the game ISO and the BIOS come from the installation itself (nothing to
# choose); the online settings live in online/data (separate from game/mod-settings.json).
ONLINE='online'
# Created by the online lobby while it runs: never part of the receipt, kept across an upgrade only as listed in
# ONLINE_IMPORTED.
ONLINE_MUTABLE=('data','states','matches','prep','runs','linux')
ONLINE_IMPORTED=('data/profile.json','data/settings.json')
ONLINE_LARGE=('online/match/runtime/memcards/Mcd001.ps2','online/match/runtime/memcards/Mcd002.ps2')
# PCSX2's own writable folders inside online/pcsx2 (the receipt leaves them out, as for runtime28)
PCSX2_MUTABLE=('bios','inis','sstates','memcards','cheats','logs','snaps','cache','covers','videos','textures',
               'gamesettings','portable.ini','portable.txt')


def install_online(root,work,adapter,pcsx2=None):
    """<installation>/online from the payload's online/ folder (and on Windows its own copy of the installation's
    PCSX2 build) for each supported BT3/BT4 installation. Returns the online folder or None."""
    source=Path(work)/ONLINE
    if adapter not in ADAPTERS:
        if source.is_dir():shutil.rmtree(source)
        return None
    require((source/'netplay'/'ttm_online.py').is_file(),'TTM-PAYLOAD-03',script='online',
            detail='The player payload has no online part')
    target=Path(root)/ONLINE
    os.replace(source,target)
    if WINDOWS and pcsx2 is not None:
        runtime_copy(Path(pcsx2).parent,target/'pcsx2')
        (target/'pcsx2'/'portable.ini').write_text('')    # its own data folder, never Documents\PCSX2
    return target


def online_files(root):
    """{relative path: sha256} of the online part's code and templates (the lobby's own data, matches, states and
    the online PCSX2's profile folders change as it is used and are left out)."""
    files={};online=Path(root)/ONLINE
    if not online.is_dir():return files
    for path in online.rglob('*'):
        relative=path.relative_to(online)
        if not path.is_file() or '__pycache__' in path.parts or path.suffix=='.pyc':continue
        if relative.parts[0] in ONLINE_MUTABLE:continue
        if relative.parts[0]=='pcsx2' and len(relative.parts)>1 and relative.parts[1].lower() in PCSX2_MUTABLE:continue
        files[path.relative_to(root).as_posix()]=file_hash(path)
    return files


def configuration(bios_name,port):
    c=configparser.ConfigParser(interpolation=None);c.optionxform=str
    c['UI']=dict(SettingsVersion='1',StartPaused='false',PauseOnFocusLoss='false',StartFullscreen='false')
    c['Folders']=dict(Bios='bios',Snapshots='snaps',Savestates='sstates',MemoryCards='memcards',Logs='logs',
                      Cheats='cheats',CheatsWS='cheats_ws',CheatsNI='cheats_ni',Cache='cache',Textures='textures',InputProfiles='inputprofiles')
    c['Filenames']=dict(BIOS=bios_name)
    c['EmuCore']=dict(EnablePINE='true',PINESlot=str(port),EnableCheats='true',EnablePatches='true')
    c['EmuCore'].update(CdvdDumpBlocks='false',EnableRecordingTools='false')
    # Zstandard (2 in 2.6.x and 2.8.x): the mod cannot read 2.6's Deflate64/LZMA2 savestates.
    # Play.cmd also pins it for each session, in case it is changed in PCSX2's settings.
    c['EmuCore'].update(SavestateCompressionType='2')
    c['EmuCore/CPU']=dict(ExtraMemory='true')
    # A generated profile never gets PCSX2's hardware-dependent defaults, so MTVU would stay off and
    # VU1 would run on the EE thread. Every development and verification run used MTVU on.
    c['EmuCore/Speedhacks']=dict(vuThread='true')
    c['EmuCore/GS']=dict(Renderer='-1',upscale_multiplier='2',UserHacks='false',DumpGSData='false',SaveRT='false',SaveFrame='false',SaveTexture='false',SaveDepth='false',
                       DumpReplaceableTextures='false',DumpReplaceableMipmaps='false',DumpTexturesWithFMVActive='false',LoadTextureReplacements='false')
    c['AutoUpdater']=dict(CheckAtStartup='false')
    c['Logging']=dict(EnableFileLogging='false',EnableInputRecordingLogs='false',EnableControllerLogs='false',EnableLogWindow='false')
    c['InputSources']=dict(SDL='true',XInput='false',DInput='false',SDLControllerEnhancedMode='true')
    c['Pad']=dict(MultitapPort1='true',MultitapPort2='false')
    controls=dict(Up='DPadUp',Right='DPadRight',Down='DPadDown',Left='DPadLeft',
        Triangle='FaceNorth',Circle='FaceEast',Cross='FaceSouth',Square='FaceWest',Select='Back',Start='Start',
        L1='LeftShoulder',L2='+LeftTrigger',R1='RightShoulder',R2='+RightTrigger',L3='LeftStick',R3='RightStick',
        LUp='-LeftY',LRight='+LeftX',LDown='+LeftY',LLeft='-LeftX',RUp='-RightY',RRight='+RightX',RDown='+RightY',RLeft='-RightX')
    for pad in range(4):c[f'Pad{pad+1}']=dict(Type='DualShock2',**{k:f'SDL-{pad}/{v}'for k,v in controls.items()})
    c['MemoryCards']=dict(Slot1_Enable='true',Slot1_Filename='Mcd001.ps2',Slot2_Enable='true',Slot2_Filename='Mcd002.ps2')
    # A generated profile never gets PCSX2's default hotkeys (SettingsVersion is current), so bind the pause key the
    # launcher's "press Space" prompts name. Save/load-state keys stay unbound: loading a state mid-match is refused.
    c['Hotkeys']=dict(TogglePause='Keyboard/Space')
    return c


def initial_mod_language(profile,installer_language):
    """Spanish BT4 starts localized even when setup itself ran in English.

    Only reviewed disc metadata selects this default; filenames cannot enable
    an adapter or change settings. Players can change language after install.
    """
    match=profile.get('identity',{}).get('runtime_match',{})
    if match.get('verified') and match.get('native_language')=='es':return 'es'
    return installer_language


def write_settings(game,language,defaults_path=None):
    """Write the player's game/mod-settings.json and, once, game/mod-settings-defaults.json.

    The defaults file is player-defaults.json validated, without `language`: Restore defaults (desktop
    and in game) reads it and never changes the language. It is hashed into installed-files.json like
    the other static files, so nothing may rewrite it."""
    import mod_settings
    defaults=json.loads(Path(defaults_path or HERE/'player-defaults.json').read_text(encoding='utf-8'))
    defaults.pop('language',None)
    installed=mod_settings.validate_settings(dict(defaults));installed.pop('language',None)
    selected=mod_settings.validate_settings(dict(defaults,language=language))
    with (game/'mod-settings-defaults.json').open('x',encoding='utf-8') as stream:
        stream.write(json.dumps(installed,indent=2)+'\n')
    (game/'mod-settings.json').write_text(json.dumps(selected,indent=2)+'\n',encoding='utf-8')


def installed_files(root,game,runtime):
    """SHA-256 of immutable code/resources, including game/mod-settings-defaults.json. Settings, BIOS,
    cards, saves and future logs are deliberately excluded so ordinary play never reports corruption.
    On Linux all of PCSX2's data lives in runtime28/PCSX2/, which is excluded as a whole."""
    files={}
    mutable=('bios','inis','sstates','memcards','cheats','logs','portable.ini')+(() if WINDOWS else ('pcsx2',))
    for directory in (root/'iso_compatibility',game/'tools',game/'assets',game/'analysis',runtime):
        for path in directory.rglob('*'):
            relative=path.relative_to(directory)
            if not path.is_file() or '__pycache__' in path.parts or path.suffix=='.pyc':continue
            if directory==runtime and relative.parts[0].lower() in mutable:continue
            files[path.relative_to(root).as_posix()]=file_hash(path)
    for path in game.iterdir():
        # iso-location.json: where Play found a moved ISO again (game_profile.iso_path); it changes after install.
        if path.is_file() and path.name not in ('mod-settings.json','COMPATIBILITY.md','iso-location.json'):
            files[path.relative_to(root).as_posix()]=file_hash(path)
    files.update(online_files(root))
    return files


def install_receipt(release,adapter,emulator_version,files,**emulator):
    """installed-files.json: the release, the PCSX2 build and whether it is a tested release. Linux adds
    emulator_kind='appimage' and emulator_version_source (how the AppImage's version was read)."""
    return dict(schema=1,version=release['version'],adapter=adapter,emulator_version=emulator_version,
                pcsx2_tested=pcsx2_support(emulator_version,release)[1],files=files,**emulator)


# ---- Linux launchers ------------------------------------------------------------------------------------

def translator(language):
    translations=json.loads((HERE/'installer-es.json').read_text(encoding='utf-8')) if language=='es' else {}
    return lambda text:translations.get(text,text)


def sh_quote(text):
    return "'"+str(text).replace("'","'\\''")+"'"


def desktop_string(text):
    require(not re.search(r'[\x00-\x1f\x7f]',str(text)),'Choose an installation path without control characters')
    return str(text).replace('\\','\\\\')


def desktop_exec(path):
    """One quoted Exec argument (Desktop Entry Specification: quote, escape "`$\\, double %, then string-escape)."""
    quoted='"'+re.sub(r'(["`$\\])',r'\\\1',str(path))+'"'
    return desktop_string(quoted.replace('%','%%'))


# Coded like the Windows launchers' private-Python guard (TTM-PLAY-51); Linux has no repair, so the step differs.
BROKEN_VENV=('[TTM-PLAY-51] The private Python environment (.venv) of this installation no longer runs, usually because a system upgrade '
             'replaced its Python. Run Install.sh and choose the folder of this installation itself (the one that contains Play.sh): '
             'setup installs a fresh copy beside it and offers to copy your memory cards and mod settings into it.')
PRESS_ENTER='Press Enter to close.'
# Mod settings.sh and PCSX2 settings.sh are started from desktop menus without a terminal: their errors are dialogs.
SETTINGS_NO_TK=('Mod settings needs Tk for Python, which is not installed (Debian/Ubuntu: sudo apt install python3-tk; '
                'Fedora: sudo dnf install python3-tkinter; Arch: sudo pacman -S tk). Install it, then open Mod settings again.')
SETTINGS_STOPPED='Mod settings stopped with an error. Details:'
PCSX2_NO_OPENGL=('PCSX2 could not start: the system library libOpenGL.so.0 is missing. Install it with your package manager '
                 '(Debian/Ubuntu: libopengl0; Fedora: libglvnd-opengl; Arch: libglvnd).')
PCSX2_NO_LIBRARY='PCSX2 could not start: this system library is missing (install it with your package manager):'
PCSX2_NO_FUSE=('PCSX2 could not start: its AppImage could not mount itself because FUSE is unavailable. Install FUSE 3 '
               '(the fuse3 package, which provides a setuid fusermount3) and make sure /dev/fuse exists.')
PCSX2_NO_DISPLAY='PCSX2 could not start: it needs a desktop session (DISPLAY or WAYLAND_DISPLAY).'
PCSX2_FAILED='PCSX2 closed with an error.'
DETAILS='Details:'
SCRIPT_TEXTS=(BROKEN_VENV,PRESS_ENTER,SETTINGS_NO_TK,SETTINGS_STOPPED,PCSX2_NO_OPENGL,PCSX2_NO_LIBRARY,PCSX2_NO_FUSE,
              PCSX2_NO_DISPLAY,PCSX2_FAILED,DETAILS)
# play_launcher.py settings exits with this status when it has already shown its error to the player.
SETTINGS_REPORTED=3
SH_START=('#!/bin/sh\n# Generated by the Tag Team Mod installer; keep it in the installation folder.\n'
          'here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P) || exit 1\n'
          'python="$here/.venv/bin/python"\n'
          '# A PYTHONHOME left by another program would stop the private Python from starting.\n'
          'unset PYTHONHOME\n')
# Messages must be visible when started from a desktop menu without a terminal.
SH_SHOW_ERROR=('show_error() {\n'
               '  printf \'%s\\n\' "$1" >&2\n'
               '  [ -t 2 ] && return 0\n'
               '  [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] || return 0\n'
               '  if command -v zenity >/dev/null 2>&1 && zenity --error --no-markup --title="Tag Team Mod" --text="$1" >/dev/null 2>&1; then return 0; fi\n'
               '  if command -v kdialog >/dev/null 2>&1 && kdialog --title "Tag Team Mod" --error "$1" >/dev/null 2>&1; then return 0; fi\n'
               '  if command -v xmessage >/dev/null 2>&1 && xmessage -center "Tag Team Mod: $1" >/dev/null 2>&1; then return 0; fi\n'
               '  if command -v notify-send >/dev/null 2>&1; then notify-send "Tag Team Mod" "$1" >/dev/null 2>&1; fi\n'
               '  return 0\n'
               '}\n')


def pause_if_terminal(L,condition='[ -t 0 ]'):
    return f'if {condition}; then printf \'%s \' {sh_quote(L(PRESS_ENTER))}; read -r _; fi\n'


# Ctrl+C reaches the Python child as usual, but the script itself survives it to reach its pause/report lines
# (dash, Debian's /bin/sh, would otherwise end with the signal once the child exits).
SH_KEEP_ON_INTERRUPT='trap : INT\n'


def linux_scripts(adapter,language='en'):
    """The installation's POSIX launchers (LF, mode 0755). Play.sh must be written last."""
    L=translator(language)
    broken=sh_quote(L(BROKEN_VENV))
    suffix=socket_suffix(adapter_contract(adapter)['pine_slot'])
    run_tool=lambda script,*arguments:(SH_START+
        f'if "$python" -c \'\' >/dev/null 2>&1; then\n  {SH_KEEP_ON_INTERRUPT}'
        f'  PYTHONNOUSERSITE=1 PYTHONPATH= TAGTEAM_DISC= TAGTEAM_ADAPTER= "$python" "$here/game/tools/{script}"{"".join(" "+a for a in arguments)}\n'
        f'  rc=$?\nelse\n  printf \'%s\\n\' {broken} >&2\n  rc=1\nfi\n'+pause_if_terminal(L)+'exit "$rc"\n')
    scripts={}
    scripts['Check installation.sh']=(SH_START+
        'log="$here/check-installation.log"\n'
        f'if "$python" -c \'\' >/dev/null 2>&1; then\n  {SH_KEEP_ON_INTERRUPT}'
        '  PYTHONNOUSERSITE=1 PYTHONPATH= TAGTEAM_DISC= TAGTEAM_ADAPTER= "$python" "$here/check_installation.py" "$@" >"$log" 2>&1\n'
        f'  rc=$?\nelse\n  printf \'%s\\n\' {broken} >"$log"\n  rc=1\nfi\n'
        'cat "$log"\n'
        "printf '%s\\n' "+sh_quote(L('Report saved to check-installation.log and check-status.json'))+'\n'+
        pause_if_terminal(L)+'exit "$rc"\n')
    # Usually opened from the desktop menu (no terminal): every failure ends in a dialog, and without a terminal the
    # launcher's messages are kept in game/analysis/settings/launcher.log.
    scripts['Mod settings.sh']=(SH_START+SH_SHOW_ERROR+
        'if ! "$python" -c \'\' >/dev/null 2>&1; then show_error '+broken+'; exit 1; fi\n'
        'if ! "$python" -c \'import tkinter\' >/dev/null 2>&1; then show_error '+sh_quote(L(SETTINGS_NO_TK))+'; exit 1; fi\n'
        'log="$here/game/analysis/settings/launcher.log"\n'
        'if [ ! -t 2 ] && mkdir -p "$here/game/analysis/settings" 2>/dev/null && true 2>/dev/null >>"$log"; then exec 2>>"$log"; fi\n'
        'export PYTHONNOUSERSITE=1 PYTHONPATH= TAGTEAM_DISC= TAGTEAM_ADAPTER=\n'+SH_KEEP_ON_INTERRUPT+
        '"$python" "$here/game/tools/play_launcher.py" settings "$@"\n'
        'rc=$?\n'
        f'# {SETTINGS_REPORTED}: the launcher has already shown its error.\n'
        f'if [ "$rc" -ne 0 ] && [ "$rc" -ne {SETTINGS_REPORTED} ]; then show_error {sh_quote(L(SETTINGS_STOPPED))}" $log (exit $rc)"; fi\n'
        'exit "$rc"\n')
    scripts['PCSX2 settings.sh']=(SH_START+SH_SHOW_ERROR+
        '# Opens this installation\'s own PCSX2 (no game) to adjust controllers and other PCSX2 settings.\n'
        'appimage="$here/game/runtime28/pcsx2-qt.AppImage"\n'
        f'for sock in "${{XDG_RUNTIME_DIR-/tmp}}/pcsx2.sock{suffix}" "/tmp/pcsx2.sock{suffix}"; do\n'
        '  if [ -S "$sock" ] && "$python" -c \'import socket,sys; s=socket.socket(socket.AF_UNIX); s.settimeout(1); s.connect(sys.argv[1])\' "$sock" >/dev/null 2>&1; then\n'
        '    show_error '+sh_quote(L('PCSX2 is already running. Close it first; this opens the same private PCSX2 profile.'))+'\n'
        '    exit 1\n  fi\ndone\n'
        'log="$here/pcsx2-settings.log"\n'
        'unset APPIMAGE_EXTRACT_AND_RUN\n'
        '"$appimage" -portable "$@" >"$log" 2>&1\n'
        'rc=$?\n'
        '[ "$rc" -eq 0 ] && exit 0\n'
        '# The same diagnosis as play_launcher.startup_failure: a loader error first (FUSE worked), then FUSE, then the display.\n'
        "library=$(sed -n 's/.*error while loading shared libraries: \\([^: ]*\\).*/\\1/p' \"$log\" | head -n 1)\n"
        'if [ "$library" = libOpenGL.so.0 ]; then problem='+sh_quote(L(PCSX2_NO_OPENGL))+'\n'
        'elif [ -n "$library" ]; then problem='+sh_quote(L(PCSX2_NO_LIBRARY))+'" $library"\n'
        "elif grep -qiE 'fusermount|libfuse|/dev/fuse|cannot mount|mount failed|failed to mount|(^|[^a-z])fuse([^a-z]|$)' \"$log\"; then "
        'problem='+sh_quote(L(PCSX2_NO_FUSE))+'\n'
        "elif grep -qiE 'could not connect to display|qt platform plugin' \"$log\"; then problem="+sh_quote(L(PCSX2_NO_DISPLAY))+'\n'
        'else problem='+sh_quote(L(PCSX2_FAILED))+'" (exit $rc)"\nfi\n'
        'show_error "$problem "'+sh_quote(L(DETAILS))+'" $log"\n'
        'exit "$rc"\n')
    # Online play: the online lobby with this installation's own AppImage (its own configuration folder online/linux).
    scripts['Play online.sh']=(SH_START+
        f'if "$python" -c \'\' >/dev/null 2>&1; then\n  {SH_KEEP_ON_INTERRUPT}'
        '  PYTHONNOUSERSITE=1 PYTHONPATH= TAGTEAM_DISC= TAGTEAM_ADAPTER= TTM_KIT_RUNTIME= "$python" "$here/online/netplay/ttm_online.py"'
        ' --pcsx2 "$here/game/runtime28/pcsx2-qt.AppImage" "$@"\n'
        f'  rc=$?\nelse\n  printf \'%s\\n\' {broken} >&2\n  rc=1\nfi\n'+pause_if_terminal(L,'[ "$rc" -ne 0 ] && [ -t 0 ]')+'exit "$rc"\n')
    scripts['Scan compatibility.sh']=run_tool('game_profile.py')
    scripts['Build expanded maps.sh']=run_tool('map_scale_launch.py','--build')
    scripts['Play.sh']=(SH_START+
        f'if "$python" -c \'\' >/dev/null 2>&1; then\n  {SH_KEEP_ON_INTERRUPT}'
        '  PYTHONNOUSERSITE=1 PYTHONPATH= TAGTEAM_DISC= TAGTEAM_ADAPTER= "$python" -u "$here/game/tools/play_launcher.py" play --runtime-profile runtime28 "$@"\n'
        f'  rc=$?\nelse\n  printf \'%s\\n\' {broken} >&2\n  rc=1\nfi\n'+
        pause_if_terminal(L,'[ "$rc" -ne 0 ] && [ -t 0 ]')+'exit "$rc"\n')
    return scripts


def desktop_entries(root,online=True):
    """Menu entries for the install folder (copy them to ~/.local/share/applications to list them in the menu)."""
    L=translator('es');root=Path(root) if isinstance(root,str) else root
    icon=root/'game/Tag Team Mod Logo.png'
    entries={}
    for file,name,script,terminal in (('Tag Team Mod.desktop','Tag Team Mod','Play.sh',True),
                                      ('Tag Team Mod - Mod settings.desktop','Tag Team Mod - Mod settings','Mod settings.sh',False),
                                      ('Tag Team Mod - PCSX2 settings.desktop','Tag Team Mod - PCSX2 settings','PCSX2 settings.sh',False),
                                      ('Tag Team Mod - Online.desktop','Tag Team Mod - Online','Play online.sh',False)):
        if script=='Play online.sh' and not online:continue
        entries[file]=('[Desktop Entry]\nType=Application\n'
                       f'Name={name}\nName[es]={L(name)}\nExec={desktop_exec(root/script)}\nPath={desktop_string(root)}\n'
                       f'Icon={desktop_string(icon)}\nTerminal={"true" if terminal else "false"}\nCategories=Game;\n')
    return entries


def write_script(path,text):
    require('\r' not in text,'Linux launchers must use LF line endings')
    Path(path).write_bytes(text.encode('utf-8'));Path(path).chmod(0o755)


# Added to the installation's README.txt for the European or Japanese disc (DISC_NOTES).
EUROPEAN_NOTE='European disc (SLES-54945): the game runs at 50 Hz, like the original European release.\n'
JAPANESE_NOTE=('Japanese disc (SLPS-25815, Sparking! Meteor): its menus confirm with Circle and go back with Cross; the '
               'game text and voices are Japanese, the fighter names in the mod are English.\n')
LINUX_README=('Start Play.sh (sh Play.sh in a terminal, or Tag Team Mod.desktop). At the native main menu, press Select for Modded Modes.\n'
              'Original-menu modes stay native.\nSettings: Modded Modes > Mod Settings, or Mod settings.sh.\n'
              'Game disc: Mod settings.sh > Game disc switches between your BT3 USA, Europe and Japan ISOs (or BT4 English and Spanish).\n'
              'PCSX2 settings.sh opens this installation\'s own PCSX2 (no game) to adjust controller bindings.\n'
              'Four SDL controllers are mapped in the order Linux lists them; adjust bindings in PCSX2 if needed.\n'
              'The .desktop files start the same scripts; copy them to ~/.local/share/applications to add menu entries.\n'
              'The first battle uses temporary working files and a rematch checkpoint; diagnostic dumps are off. Old generated sessions are bounded.\n'
              'COMPATIBILITY.md lists resource limitations. Offline checks do not certify every move or stage in gameplay.\n'
              'No ISO or BIOS is distributed. This installation references your selected ISO and copies your BIOS into its private profile.\n'
              'Memory cards and save states: game/runtime28/PCSX2/memcards and game/runtime28/PCSX2/sstates.\n')
# The Spanish lines close each README.txt, after the English ones and their European note (readme_text).
LINUX_README_ES=('\n'
                 'Espa\u00f1ol: LEEME.md explica el mod en espa\u00f1ol. Inicia Play.sh (sh Play.sh en una terminal, o Tag Team '
                 'Mod.desktop). En el men\u00fa principal original, pulsa Select para abrir los modos del mod.\n'
                 'Ajustes: Modos del mod > Ajustes del mod, o Mod settings.sh. PCSX2 settings.sh abre el PCSX2 propio de esta '
                 'instalaci\u00f3n (sin juego) para ajustar los mandos.\n'
                 'Disco del juego: Mod settings.sh > Disco del juego cambia entre tus ISO de BT3 de EE. UU., de Europa y de '
                 'Jap\u00f3n (o BT4 en ingl\u00e9s y en espa\u00f1ol).\n'
                 'Tarjetas de memoria y estados guardados: game/runtime28/PCSX2/memcards y game/runtime28/PCSX2/sstates.\n'
                 'Si algo se detiene, la ventana muestra un bloque que empieza por un c\u00f3digo como [TTM-CHECK-10]; '
                 'c\u00f3pialo si pides ayuda. Check installation.sh comprueba esta carpeta.\n')
EUROPEAN_NOTE_ES='Disco europeo (SLES-54945): el juego funciona a 50 Hz, como la versi\u00f3n europea original.\n'
JAPANESE_NOTE_ES=('Disco japon\u00e9s (SLPS-25815, Sparking! Meteor): sus men\u00fas confirman con C\u00edrculo y vuelven '
                  'con Cruz; los textos y las voces del juego est\u00e1n en japon\u00e9s y los nombres de los luchadores del '
                  'mod, en ingl\u00e9s.\n')
DISC_NOTES={'bt3-pal':(EUROPEAN_NOTE,EUROPEAN_NOTE_ES),'bt3-jpn':(JAPANESE_NOTE,JAPANESE_NOTE_ES)}


def bundled_library_name(file):
    """'libgfortran' for auditwheel's 'libgfortran-040039e1-0352e75f.so.5.0.0' (the name without its hash and version)."""
    match=re.match(r'(.+?)-[0-9a-f]{8}(?:-[0-9a-f]{8})?\.so',file)
    return match.group(1) if match else file


LINUX_NOTICES_TAIL=('The player payload is the same as on Windows, so it also contains an unmodified SDL2 runtime for\n'
    'Windows with its license at game/tools/vendor/SDL2-LICENSE.txt and a pycaw wheel (Windows audio) with its\n'
    'license inside the wheel at game/tools/vendor-wheels/pycaw-20251023-py3-none-any.whl; neither is used on Linux.\n'
    'Upstream projects: https://github.com/libsdl-org/SDL/tree/SDL2 and https://github.com/AndreMiras/pycaw.\n\n'
    'The player payload also includes the unmodified Liberation Sans 2.1.5 fonts (Regular and Bold) at\n'
    'game/tools/vendor/fonts/, with their SIL Open Font License 1.1 in that folder and in\n'
    'notices/liberation-fonts/LICENSE. On Linux all of the mod\'s text is drawn with them. Upstream project:\n'
    'https://github.com/liberationfonts/liberation-fonts.\n\n'
    'Walking and running motion data is adapted from Mannequiny v0.4.0 by GDQuest, Luciano Munoz and contributors,\n'
    'under Creative Commons Attribution 4.0 (CC BY 4.0). The modified samples are in game/tools/ground_motion.py;\n'
    'attribution, source links and a description of changes are in game/assets/licenses/Mannequiny.txt.\n'
    'No source mannequin model is included.\n'
    'Source: https://github.com/gdquest-demos/godot-3d-mannequin/releases/tag/v0.4.0\n'
    'License: https://creativecommons.org/licenses/by/4.0/\n\n'
    'PCSX2 and Python are not redistributed in this tar.gz. Setup copies the PCSX2 AppImage the user selects into\n'
    'the installation and creates the private Python environment with a Python already installed on the system.\n'
    'Their upstream terms apply.\n\n'
    'No game ISO, PS2 BIOS, memory card, game save, RAM capture or extracted native\n'
    'game executable is included. Fighter portraits and native references are\n'
    'extracted locally from the selected ISO during setup. This is an unofficial\n'
    'fan modification, not an official Dragon Ball or PCSX2 release.\n')


def linux_notices(setup=HERE):
    """THIRD_PARTY_NOTICES.md of the Linux release and installations, generated from dependencies-linux.json: the Linux
    wheels (comtypes is Windows-only) and the native libraries each bundles, whose texts are in its notices/ folder."""
    record=json.loads((Path(setup)/'dependencies-linux.json').read_text(encoding='utf-8'))
    rows=[]
    for name,row in sorted(record['packages'].items()):
        libraries=sorted({bundled_library_name(file) for file in row['bundled_libraries']},key=str.lower)
        rows.append(f'- {name} {row["version"]}'+(' (bundles the native libraries '+', '.join(libraries)+')' if libraries else '')+
                    f'; license texts in notices/{name}/')
    return ('# Third-party components (Linux)\n\n'
            'The exact versions, wheel files, upstream project links and SHA-256 hashes\n'
            'are in dependencies.json. The notices directory preserves the upstream license\n'
            'texts shipped inside those wheels, including the texts of the native libraries\n'
            'they bundle. The installed Python packages also retain their original metadata\n'
            'and licenses. These wheels are unmodified.\n\n'
            'Bundled Python components for Linux x86-64 (CPython '+', '.join(record['python'])+'):\n\n'+
            '\n'.join(rows)+'\n\n'+LINUX_NOTICES_TAIL)


def copy_linux_documents(root):
    """The Linux lock and dependency receipt are installed under the Windows names, so check_installation.py reads
    the same files on both systems (the receipt's license paths name notices/, where they are installed); notices/
    gets the Linux wheels' license texts plus the notices that are not about a wheel (bundled fonts), and
    THIRD_PARTY_NOTICES.md the Linux text (linux_notices)."""
    renamed={'requirements-player-linux.lock':'requirements-player.lock'}
    for name in ('release.json','requirements-player-linux.lock','check_installation.py','setup_messages.py','messages.json',
                 'README.md','LEEME.md','CHANGELOG.md'):
        shutil.copy2(HERE/name,root/renamed.get(name,name))
    record=json.loads((HERE/'dependencies-linux.json').read_text(encoding='utf-8'))
    record['licenses']={('notices/'+key.split('/',1)[1] if key.startswith('notices-linux/') else key):digest
                        for key,digest in record['licenses'].items()}
    (root/'dependencies.json').write_bytes((json.dumps(record,indent=2)+'\n').encode('utf-8'))
    (root/'THIRD_PARTY_NOTICES.md').write_bytes(linux_notices(HERE).encode('utf-8'))
    shutil.copytree(HERE/'notices-linux',root/'notices')
    for path,relative in other_notices(HERE):
        target=root/'notices'/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)


def other_notices(setup):
    """(path, relative path) of notices/ files that are not a Windows wheel's license (e.g. the bundled fonts' OFL)."""
    folder=Path(setup)/'notices'
    if not folder.is_dir():return []
    record=Path(setup)/'dependencies.json'
    wheels=set(json.loads(record.read_text(encoding='utf-8'))['packages']) if record.is_file() else set()
    return [(path,path.relative_to(folder)) for path in sorted(folder.rglob('*'))
            if path.is_file() and path.relative_to(folder).parts[0] not in wheels]


# ---- Retry and upgrade: never write into, and never delete, an existing folder --------------------------------------

def folder_state(path):
    """'missing', 'failed' (an unfinished setup attempt: setup's bootstrap file, no Play launcher, not ready),
    'complete' (an installation with its receipt and Play launcher) or 'other'. install-player.ps1 (Get-FolderState)
    applies the same rule."""
    path=Path(path)
    if not os.path.lexists(path):return 'missing'
    if path.is_symlink() or not path.is_dir():return 'other'
    play=(path/'Play.cmd').exists() or (path/'Play.sh').exists()
    if (path/'install-bootstrap.json').is_file() and not play:
        try:ready=json.loads((path/'install-status.json').read_text(encoding='utf-8-sig')).get('ready') is True
        except (OSError,ValueError,AttributeError):ready=False
        return 'other' if ready else 'failed'
    if play and (path/'installed-files.json').is_file():return 'complete'
    return 'other'


def aside_name(path,stamp=None):
    """The new name of an unfinished attempt: 'Tag Team Mod (failed 20260927-171200)', never an existing path."""
    import datetime
    path=Path(path);stamp=stamp or datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    candidate=path.with_name(f'{path.name} (failed {stamp})');number=2
    while os.path.lexists(candidate):candidate=path.with_name(f'{path.name} (failed {stamp}-{number})');number+=1
    return candidate


def plan_destination(path,explicit,version):
    """(destination, unfinished folder to rename aside or None, complete installation installed beside or None).
    An explicit --destination is used as given: an unfinished attempt there is renamed aside, anything else refused.
    A folder chosen in the dialog gets a free name beside an existing one: 'Tag Team Mod <version>', then ' (2)'..."""
    path=Path(path)
    state=folder_state(path)
    if state=='missing':return path,None,None
    if state=='failed':return path,path,None
    if explicit:raise SetupFailure('TTM-DEST-06',file=str(path))
    beside=path if state=='complete' else None
    for number in range(1,100):
        candidate=path.with_name(f'{path.name} {version}'+(f' ({number})' if number>1 else ''))
        found=folder_state(candidate)
        if found=='missing':return candidate,None,beside
        if found=='failed':return candidate,candidate,beside
    raise SetupFailure('TTM-DEST-06',file=str(path))


def translated(text,translations):
    """installer-es.json text for a message: the exact key, else the longest key it starts with (a key ending in ':'
    followed by an untranslated path or name)."""
    if text in translations:return translations[text]
    prefixes=[key for key in translations if text.startswith(key) and len(key)>8]
    if not prefixes:return text
    key=max(prefixes,key=len);return translations[key]+text[len(key):]


def failure_for(error):
    """The coded failure setup reports for an exception raised while installing (see setup_messages.classify)."""
    if isinstance(error,SetupFailure):return error
    if getattr(error,'setup_failure',None) is not None:return error.setup_failure
    spanish=json.loads((HERE/'installer-es.json').read_text(encoding='utf-8'))
    message=str(error)
    if isinstance(error,ValueError) and not getattr(error,'code',None):
        for text,code in PCSX2_REASON_CODES.items():
            if message.startswith(text):return SetupFailure(code,reason=dict(en=message,es=translated(message,spanish)))
        if type(error).__name__=='FormatError':  # the scanner found a structure it cannot read
            return SetupFailure('TTM-ISO-09',reason=dict(en=message,es=message))
    return messages.classify(error,translate=lambda text:translated(text,spanish))


def child_environment(**extra):
    """The environment of the Python children setup runs: UTF-8, no user site, no inherited PYTHONHOME/PYTHONPATH."""
    env=dict(os.environ,PYTHONNOUSERSITE='1',PYTHONPATH='',PYTHONUTF8='1',PYTHONIOENCODING='utf-8',**extra)
    env.pop('PYTHONHOME',None)
    return env


# Setup shows its checks' notes (a missing SDL2, an untested PCSX2 ...), not their raw proof lines: the boot hook's
# SHA-256, the release line, 'dependencies ready' and an unchanged ISO profile go to the setup log only.
RAW_CHILD_LINE=re.compile(r'^(?:[0-9a-f]{64}|Tag Team Mod \S+|Autopilot dependencies ready: .*|Using unchanged ISO compatibility profile)$')


def show_child(result):
    """A setup child's output: every line in the setup log, all but RAW_CHILD_LINE lines on screen too."""
    log=getattr(sys.stdout,'log',None)
    for line in (result.stdout or '').splitlines(True):
        if not RAW_CHILD_LINE.match(line.rstrip('\r\n')):print(line,end='')
        elif log is not None:
            try:log.write(line)
            except (OSError,ValueError):pass
    print(result.stderr or '',end='',file=sys.stderr)


def run_child(command,step,**options):
    """subprocess.run with UTF-8 text; a timeout becomes TTM-PAYLOAD-05 naming the step."""
    try:return subprocess.run(command,text=True,encoding='utf-8',errors='replace',capture_output=True,**options)
    except subprocess.TimeoutExpired as error:
        raise SetupFailure('TTM-PAYLOAD-05',step=step,detail=f'timeout after {error.timeout} s') from error


def cmd_echo(text):
    """One cmd.exe echo line (outside parenthesised blocks) that prints text exactly, ASCII only."""
    text=messages.fold(text)
    if not text.strip():return 'echo.'
    return 'echo '+re.sub(r'([&|<>^])',r'^\1',text).replace('%','%%')


def cmd_failure(code,language,**values):
    """The echo lines of a coded block for a generated .cmd file; FILE is the running script, quoted ("%~f0") so that
    a path with & or ^ (a user name such as 'Tom & Jerry') is printed whole."""
    block=messages.render(code,language,file='@@SCRIPT@@',ascii=True,**values)
    return '\n'.join(cmd_echo(line) for line in block.split('\n')).replace('@@SCRIPT@@','"%~f0"')+'\n'


CMD_ENVIRONMENT=('set "PYTHONHOME="\nset "PYTHONPATH="\nset "PYTHONNOUSERSITE=1"\nset "PYTHONUTF8=1"\n'
                 'set "PYTHONIOENCODING=utf-8"\nset "TAGTEAM_DISC="\nset "TAGTEAM_ADAPTER="\n')


def windows_scripts(language='en'):
    """The installation's .cmd launchers (ASCII; written in text mode, so CRLF). Each first checks that it still sits
    in its installation folder (TTM-PLAY-50); the Python tools also check the private Python (TTM-PLAY-51). Play.cmd
    keeps pausing on every non-zero exit, negative ones included."""
    moved=lambda name:':moved\n'+cmd_failure('TTM-PLAY-50',language,launcher=name)+'pause\nexit /b 2\n'
    python=':python\n'+cmd_failure('TTM-PLAY-51',language)+'pause\nexit /b 2\n'
    probe='"%~dp0.venv\\Scripts\\python.exe" -c "" >nul 2>&1\nif not "%errorlevel%"=="0" goto :python\n'
    def tool(name,marker,command):
        return ('@echo off\nsetlocal\nif not exist "%~dp0'+marker+'" goto :moved\n'+CMD_ENVIRONMENT+probe+command+
                'set "result=%errorlevel%"\npause\nexit /b %result%\n'+moved(name)+python)
    scripts={}
    scripts['Check installation.cmd']=tool('Check installation.cmd','check_installation.py',
        '"%~dp0.venv\\Scripts\\python.exe" "%~dp0check_installation.py" --log "%~dp0check-installation.log" %*\n')
    scripts['Scan compatibility.cmd']=tool('Scan compatibility.cmd','game\\tools\\game_profile.py',
        '"%~dp0.venv\\Scripts\\python.exe" "%~dp0game\\tools\\game_profile.py"\n')
    scripts['Build expanded maps.cmd']=tool('Build expanded maps.cmd','game\\tools\\map_scale_launch.py',
        '"%~dp0.venv\\Scripts\\python.exe" "%~dp0game\\tools\\map_scale_launch.py" --build\n')
    scripts['Mod settings.cmd']=('@echo off\nsetlocal\nif not exist "%~dp0game\\launch-settings.ps1" goto :moved\n'+CMD_ENVIRONMENT+
        'powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0game\\launch-settings.ps1"\n'
        'exit /b %errorlevel%\n'+moved('Mod settings.cmd'))
    # Online play (the online lobby window; the game disc, BIOS and PCSX2 are this installation's own).
    scripts['Play online.cmd']=tool('Play online.cmd','online\\netplay\\ttm_online.py',
        'set "TTM_KIT_RUNTIME="\n"%~dp0.venv\\Scripts\\python.exe" "%~dp0online\\netplay\\ttm_online.py" %*\n')
    scripts['Play.cmd']=('@echo off\nsetlocal\nif not exist "%~dp0game\\launch-autopilot.ps1" goto :moved\n'+CMD_ENVIRONMENT+
        'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0game\\launch-autopilot.ps1" -RuntimeProfile runtime28\n'
        'set "result=%errorlevel%"\nif not "%result%"=="0" pause\nexit /b %result%\n'+moved('Play.cmd'))
    return scripts


WINDOWS_README=('Start Play.cmd. At the native main menu, press Select for Modded Modes. Original-menu modes stay native.\n'
                'Settings: Modded Modes > Mod Settings, or Mod settings.cmd.\n'
                'Game disc: Mod settings.cmd > Game disc switches between your BT3 USA, Europe and Japan ISOs (or BT4 English and Spanish).\n'
                'Four SDL controllers are mapped in order; adjust bindings in PCSX2 if needed.\n'
                'The first battle uses temporary working files and a rematch checkpoint; diagnostic dumps are off. Old generated sessions are bounded.\n'
                'COMPATIBILITY.md lists resource limitations. Offline checks do not certify every move or stage in gameplay.\n'
                'No ISO or BIOS is distributed. This installation references your selected ISO and copies your BIOS into its private profile.\n'
                'If something stops, the window shows a block starting with a code such as [TTM-CHECK-10]; copy that block when asking for help.\n'
                'Failure reports: game\\analysis\\failures. The private PCSX2 is game\\runtime28\\pcsx2-qt.exe. Check installation.cmd checks this folder.\n')
# The Spanish lines close the Windows README.txt (after the disc note, which belongs to the English part).
WINDOWS_README_ES=('\n'
                   'Espa\u00f1ol: LEEME.md explica el mod en espa\u00f1ol. Si algo se detiene, la ventana muestra un bloque que empieza por un '
                   'c\u00f3digo como [TTM-CHECK-10]; c\u00f3pialo si pides ayuda.\n'
                   'Disco del juego: Mod settings.cmd > Disco del juego cambia entre tus ISO de BT3 de EE. UU., de Europa y de '
                   'Jap\u00f3n (o BT4 en ingl\u00e9s y en espa\u00f1ol).\n'
                   'Informes de fallo: game\\analysis\\failures. El PCSX2 privado es game\\runtime28\\pcsx2-qt.exe. Check installation.cmd '
                   'comprueba esta carpeta.\n')


def readme_text(adapter,windows):
    """The installation's README.txt: the English lines with the European or Japanese disc's note, then the Spanish
    lines with its Spanish note."""
    note,note_es=DISC_NOTES.get(adapter,('',''))
    if windows:return WINDOWS_README+note+WINDOWS_README_ES+note_es
    return LINUX_README+note+LINUX_README_ES+note_es


def install(args):
    if not WINDOWS:
        # Resolve the chosen parent once (Fedora Atomic's /home -> /var/home, Steam Deck's /run/media): symlinks are
        # refused only inside the folders the installer creates.
        args.destination=Path(args.destination).absolute().parent.resolve()/Path(args.destination).name
    no_reparse(args.destination)
    root=args.destination.resolve();status=root/'install-status.json'
    require(root.is_dir() and not (root/'game').exists(),'TTM-DEST-06',file=str(root),
            detail='Choose a new destination containing only the bootstrap environment')
    allowed={'.venv','installer.log','install-status.json','install-bootstrap.json'}
    require(not any(p.name not in allowed for p in root.iterdir()),'TTM-DEST-06',file=str(root),
            detail='Destination contains files from an earlier install or unrelated files')
    stage='Validating installation inputs'
    language=getattr(args,'language','en')
    translations=json.loads((HERE/'installer-es.json').read_text(encoding='utf-8')) if language=='es' else {}
    spanish=translator('es')
    def update(stage,quiet=False,**extra):
        temporary=status.with_suffix('.tmp')
        temporary.write_text(json.dumps(dict(stage=stage,**extra),indent=2),encoding='utf-8');os.replace(temporary,status)
        if not quiet:print(translations.get(stage,stage),flush=True)
    work=root/'install-staging'
    # Only this run's verified staging folder is ever removed (the destination held no install-staging at the start).
    own_work=not work.exists()
    try:
        update(stage,ready=False)
        if WINDOWS:require(python_supported() and struct.calcsize('P')==8,'TTM-PY-04',part='Python '+sys.version.split()[0]+
                           ' ('+str(struct.calcsize('P')*8)+'-bit); the private environment needs Python 3.11 x64')
        else:require(python_supported() and struct.calcsize('P')==8,'TTM-PY-22',version=sys.version.split()[0])
        free=shutil.disk_usage(root).free
        require(free>3<<30,'TTM-DEST-05',file=str(root),free=size_text(free),needed='3 GiB')
        if getattr(args,'bios',None) is None:
            # No --bios: the BIOS the selected PCSX2 is set up with; without one setup can use, a coded failure.
            require(args.pcsx2.is_file(),'Missing input file: '+str(args.pcsx2))
            found=find_configured_bios(args.pcsx2)
            if not found['bios']:raise configured_bios_failure(found)
            for line in bios_notes(found,language):print(line,flush=True)
            args.bios=Path(found['bios'])
            print('BIOS: '+str(args.bios)+bios_origin(found,lambda text:translations.get(text,text)),flush=True)
        for path in (args.iso,args.bios,args.pcsx2):require(path.is_file(),'Missing input file: '+str(path))
        require(args.iso.resolve()!=args.bios.resolve(),'TTM-BIOS-05',file=str(args.bios))
        require_image(bios_problem(args.bios),args.bios)
        bios=args.bios.read_bytes()
        require_image(iso_problem(args.iso),args.iso)
        release=release_info()
        if WINDOWS:
            emulator_version=pcsx2_version(args.pcsx2,release);emulator={}
        else:
            desktop_string(root)
            work.mkdir()
            # The copy must run from the installation's file system (noexec is refused here, before anything else).
            emulator_version,source=appimage_version(args.pcsx2.resolve(),copy_to=work/'pcsx2-qt.AppImage')
            require_supported_appimage(emulator_version,release)
            emulator=dict(emulator_kind='appimage',emulator_version_source=source)
        stage='[3/6] Verifying player payload and scanning the selected ISO';update(stage,ready=False)
        unpack(HERE/'player-payload.zip',work)
        sys.path.insert(0,str(work))
        from iso_compatibility.scanner import scan,report
        profile=scan(args.iso,root/'compatibility-profiles',progress=print)
        (root/'COMPATIBILITY.md').write_text(report(profile),encoding='utf-8')
        if not profile['capabilities']['runtime_hooks']:
            raise SetupFailure('TTM-ISO-08',file=str(args.iso),lang=language,
                               reason=dict(en=refusal_message(profile),es=refusal_message(profile,spanish)))
        adapter=profile['identity']['adapter'];contract=adapter_contract(adapter,release);game=work/contract['payload']
        check_version_policy(game/'tools',release)
        if contract['native_map']:check_native_map(game/'tools'/contract['native_map'],profile)
        sys.path.insert(0,str(game/'tools'))
        from iso_compatibility.install_profile import prepare
        prepare(args.iso,game,root/'compatibility-profiles',progress=print)
        stage='[4/6] Creating an isolated PCSX2 profile';update(stage,ready=False)
        runtime=game/'runtime28'
        if WINDOWS:runtime_copy(args.pcsx2.parent,runtime)
        else:
            appimage_runtime(work/'pcsx2-qt.AppImage',runtime)
            # The shared payload's PowerShell launchers serve Windows only (Play.sh and the other scripts replace them);
            # they are removed before the file receipt is written.
            for name in WINDOWS_ONLY_GAME_FILES:(game/name).unlink(missing_ok=True)
        data=data_folder(runtime)
        for name in ('bios','inis','sstates','memcards','cheats','logs'):(data/name).mkdir(parents=True,exist_ok=True)
        (data/'bios'/args.bios.name).write_bytes(bios);(runtime/'portable.ini').write_text('')
        with (data/'inis/PCSX2.ini').open('w',encoding='utf-8') as stream:
            configuration(args.bios.name,contract['pine_slot']).write(stream)
        mod_language=initial_mod_language(profile,language)
        write_settings(game,mod_language)
        (game/'player-install.json').write_text(json.dumps(dict(schema=1,storage_policy=1,adapter=adapter,version=release['version'])))
        # Publish scanner first; runtime paths resolve it next to game/.
        shutil.copytree(work/'iso_compatibility',root/'iso_compatibility')
        os.replace(game,root/'game');game=root/'game';runtime=game/'runtime28'
        online=install_online(root,work,adapter,args.pcsx2 if WINDOWS else None)
        stage='[5/6] Checking dependencies, native hooks and configuration';update(stage,ready=False)
        env=child_environment(BT3_RUNTIME_PROFILE='runtime28')
        for script,arguments in (('autopilot.py',['--check']),('install_boot_hooks.py',[])):
            result=run_child([sys.executable,str(game/'tools'/script),*arguments],script,env=env,cwd=game,timeout=180)
            show_child(result)
            require(result.returncode==0,'TTM-PAYLOAD-03',script=script,detail='Offline runtime check failed: '+script)
        if contract['preflight']:
            result=run_child([sys.executable,str(game/'tools'/contract['preflight'])],contract['preflight'],env=env,cwd=game,timeout=180)
            show_child(result)
            require(result.returncode==0,'TTM-PAYLOAD-03',script=contract['preflight'],
                    detail='Adapter profile verification failed: '+contract['preflight'])
        if WINDOWS:
            for name in ('release.json','dependencies.json','requirements-player.lock','check_installation.py','setup_messages.py',
                         'messages.json','README.md','LEEME.md','CHANGELOG.md','THIRD_PARTY_NOTICES.md'):
                shutil.copy2(HERE/name,root/name)
            shutil.copytree(HERE/'notices',root/'notices')
            scripts=windows_scripts(mod_language)
            for name,text in scripts.items():
                if name=='Play online.cmd' and online is None:continue
                if name!='Play.cmd':(root/name).write_text(text,encoding='ascii')
            (root/'README.txt').write_text(readme_text(adapter,True),encoding='utf-8')
        else:
            copy_linux_documents(root)
            scripts=linux_scripts(adapter,language)
            for name,text in scripts.items():
                if name=='Play online.sh' and online is None:continue
                if name!='Play.sh':write_script(root/name,text)
            for name,text in desktop_entries(root,online is not None).items():write_script(root/name,text)
            (root/'README.txt').write_bytes(readme_text(adapter,False).encode('utf-8'))
        # Only our newly created, verified staging directory is removed.
        require(work.resolve().parent==root and work.name=='install-staging','Unexpected staging path')
        shutil.rmtree(work)
        files=installed_files(root,game,runtime)
        (root/'installed-files.json').write_text(json.dumps(install_receipt(release,adapter,emulator_version,files,**emulator),
            indent=2)+'\n',encoding='utf-8')
        offline = not WINDOWS and getattr(args,'allow_missing_libraries',False)
        # --quiet-failure: the check records its coded failure in check-status.json and setup draws that block once.
        check_args = ['--quiet-failure']+(['--allow-missing-libraries'] if offline else [])
        result=run_child([sys.executable,str(root/'check_installation.py'),*check_args],'check_installation.py',env=env,cwd=root,timeout=600)
        show_child(result)
        checked=json.loads((root/'check-status.json').read_text(encoding='utf-8')) if (root/'check-status.json').is_file() else {}
        if result.returncode!=0:
            # The check's own coded reason (for example TTM-CHECK-10) is the one the player needs to see.
            code=checked.get('error_code')
            if isinstance(code,str) and messages.CODE.fullmatch(code):
                raise SetupFailure.from_details(code,checked.get('error_details'))
            raise SetupFailure('TTM-CHECK-01',detail='Final installation check failed; see check-status.json')
        require(checked.get('installation_valid') and (checked.get('ready') or
                (offline and checked.get('missing_runtime_dependencies'))),
                'TTM-CHECK-01',detail='Final installation check did not confirm installation integrity; see check-status.json')
        update('[6/6] Installed',ready=bool(checked['ready']),installation_valid=True,
               missing_runtime_dependencies=checked.get('missing_runtime_dependencies',[]),
               version=release['version'],adapter=adapter,gameplay_verified=False,
               emulator_version=emulator_version,pcsx2_tested=pcsx2_support(emulator_version,release)[1])
        # Last publication step: no usable Play entry point exists on failure.
        if WINDOWS:(root/'Play.cmd').write_text(scripts['Play.cmd'],encoding='ascii')
        else:write_script(root/'Play.sh',scripts['Play.sh'])
    except Exception as error:
        failure=failure_for(error)
        try:error.setup_failure=failure
        except AttributeError:pass
        update('FAILED',quiet=True,ready=False,failed_stage=stage,error=str(error),error_code=failure.code,
               error_details=failure.details())
        if own_work and work.is_dir() and work.parent.resolve()==root and work.name=='install-staging':
            shutil.rmtree(work,ignore_errors=True)
        raise


def game_family(root):
    """'bt3' or 'bt4' for an installation (its game/player-install.json, else its installed-files.json receipt); None
    when neither names an adapter."""
    for name in ('game/player-install.json','installed-files.json'):
        try:adapter=json.loads((Path(root)/name).read_text(encoding='utf-8-sig')).get('adapter')
        except (OSError,ValueError,AttributeError):continue
        if isinstance(adapter,str) and adapter:return adapter.split('-')[0]
    return None


def same_game(old,new):
    family=game_family(old)
    return family is not None and family==game_family(new)


def import_previous(old,new):
    """Copy the memory cards (*.ps2) and game/mod-settings.json of an older installation into a new one. A card the
    new installation already has is never overwritten; the settings are validated by the new runtime (mod_settings),
    and invalid ones are left out. The settings are copied only from an installation of the same game: BT3 and BT4
    number their characters differently, so BT3's per-character settings would land on other BT4 fighters.
    Returns (copied, skipped) lists of names."""
    old,new=Path(old).resolve(),Path(new).resolve()
    copied,skipped=[],[]
    source=data_folder(old/'game/runtime28')/'memcards';target=data_folder(new/'game/runtime28')/'memcards'
    require((new/'game/player-install.json').is_file(),'TTM-DEST-06',file=str(new),detail='not a new installation')
    target.mkdir(parents=True,exist_ok=True)
    for card in sorted(source.glob('*.ps2')) if source.is_dir() else []:
        if (target/card.name).exists():skipped.append(card.name);continue
        shutil.copy2(card,target/card.name);copied.append(card.name)
    for name in ONLINE_IMPORTED:                     # the online name, rules and window settings (TTM Online)
        source_file,target_file=old/ONLINE/name,new/ONLINE/name
        if not source_file.is_file():continue
        if target_file.exists():skipped.append('online/'+name);continue
        try:json.loads(source_file.read_text(encoding='utf-8'))
        except (ValueError,OSError):skipped.append('online/'+name);continue
        target_file.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source_file,target_file);copied.append('online/'+name)
    settings=old/'game/mod-settings.json'
    if settings.is_file() and not same_game(old,new):skipped.append('mod-settings.json')
    elif settings.is_file():
        sys.path.insert(0,str(new/'game/tools'))
        try:
            import mod_settings
            valid=mod_settings.validate_settings(json.loads(settings.read_text(encoding='utf-8')))
            (new/'game/mod-settings.json').write_text(json.dumps(valid,indent=2)+'\n',encoding='utf-8');copied.append('mod-settings.json')
        except (ValueError,OSError):skipped.append('mod-settings.json')
    return copied,skipped


# What the import never copies: PCSX2's own profile (controller bindings, graphics) and its savestates stay with the old
# installation, which setup never changes.
NOT_IMPORTED=('Not copied: your PCSX2 settings (controller bindings, graphics) and PCSX2 savestates stay in the old '
              'installation folder.')
# The game discs added in Mod settings > Game disc (game/discs/<key>) stay with the old installation as well: that
# release extracted and checked them. The new installation starts on the disc it is installed with.
NOT_IMPORTED_DISCS=('Not copied: the game discs you added in {settings} > Game disc ({count}). Add their ISOs there '
                    'again (the disc you install with is always there).')


def added_discs(old):
    """How many game discs were added in the old installation's Mod settings > Game disc (game/discs/<key>)."""
    folder=Path(old)/'game'/'discs'
    try:return sum(1 for child in folder.iterdir() if child.is_dir() and re.fullmatch('[0-9a-f]{16}',child.name))
    except OSError:return 0


def import_summary(copied,skipped,language='en',discs=0):
    """The lines setup prints after an import, in the setup language; the last one says what is never copied."""
    L=translator(language);lines=[]
    if copied:lines.append(L('Copied from the existing installation:')+' '+', '.join(copied))
    if skipped:lines.append(L('Not copied (already in the new installation, not valid for this version, or made for the other game):')+
                            ' '+', '.join(skipped))
    if not lines:lines.append(L('Nothing was copied: the existing installation has no memory cards or mod settings to copy.'))
    if discs:lines.append(L(NOT_IMPORTED_DISCS).format(count=discs,settings=messages.platform_values()['settings']))
    return lines+[L(NOT_IMPORTED)]


class Tee:
    """Console output that is also appended to the setup log (install_linux.Tee does the same on Linux)."""
    def __init__(self,stream,log):self.stream,self.log=stream,log
    def write(self,text):
        self.stream.write(text)
        try:self.log.write(text)
        except (OSError,ValueError):pass
        return len(text)
    def flush(self):
        self.stream.flush()
        try:self.log.flush()
        except (OSError,ValueError):pass
    def __getattr__(self,name):return getattr(self.stream,name)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--language',choices=('en','es'),default='en')
    p.add_argument('--allow-missing-libraries',action='store_true',help='Install offline despite missing Linux system libraries')
    p.add_argument('--log',type=Path,help='append this run\'s output, errors and tracebacks to this file')
    p.add_argument('--quiet-failure',action='store_true',help='print no failure block (install-player.ps1 draws it from install-status.json)')
    p.add_argument('--import-from',type=Path,help='copy memory cards and mod-settings.json from this installation into --destination')
    for key in ('destination','iso','pcsx2'):p.add_argument('--'+key,type=Path)
    p.add_argument('--bios',type=Path,help='your PS2 BIOS file (default: the BIOS the selected PCSX2 is set up with)')
    args=p.parse_args(argv)
    needed=('destination',) if args.import_from else ('destination','iso','pcsx2')
    missing=[key for key in needed if getattr(args,key) is None]
    if missing:p.error('the following arguments are required: '+', '.join('--'+key for key in missing))
    log=None
    if args.log:
        try:args.log.parent.mkdir(parents=True,exist_ok=True);log=args.log.open('a',encoding='utf-8')
        except OSError:log=None
    out,err=sys.stdout,sys.stderr
    if log:sys.stdout,sys.stderr=Tee(out,log),Tee(err,log)
    try:
        if args.import_from:
            copied,skipped=import_previous(args.import_from,args.destination)
            for line in import_summary(copied,skipped,args.language,added_discs(args.import_from)):print(line,flush=True)
            return 0
        install(args)
        return 0
    except Exception as error:
        failure=failure_for(error)
        if log:log.write(traceback.format_exc())
        elif not isinstance(error,ValueError):traceback.print_exc()
        if not args.quiet_failure:print(failure.render(args.language,log=args.log),file=sys.stderr,flush=True)
        return messages.exit_code(failure.code)
    finally:
        sys.stdout,sys.stderr=out,err
        if log:log.close()


if __name__=='__main__':raise SystemExit(main())
