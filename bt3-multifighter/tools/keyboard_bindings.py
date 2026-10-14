"""Validated local keyboard profiles and PCSX2's repeated-key binding format.

Only input mappings are changed. Online bindings belong to this PC and never
enter the shared simulation settings. Offline profiles are applied before Play
starts the isolated emulator; existing gamepad mappings stay in place.
"""
import json
import os
import re
from pathlib import Path
import atomic_files

ROOT = Path(__file__).resolve().parents[1]
FILE = 'keyboard-bindings.json'
BUTTONS = ('Up','Right','Down','Left','Triangle','Circle','Cross','Square','Select','Start',
           'L1','L2','R1','R2','L3','R3','LUp','LRight','LDown','LLeft','RUp','RRight','RDown','RLeft')
PADS = ('Pad1','Pad2')
DEFAULT = dict(Up='Up',Right='Right',Down='Down',Left='Left',Triangle='K',Circle='L',Cross='Space',Square='J',
               Select='Tab',Start='Return',L1='E',L2='Q',R1='Shift',R2='Control',L3='T',R3='R',
               LUp='W',LRight='D',LDown='S',LLeft='A',RUp='Numpad8',RRight='Numpad6',RDown='Numpad2',RLeft='Numpad4')
LEGACY_ONLINE = dict(zip(BUTTONS,('I','U','Y','T','P','O','Q','W','R','E','A','D','S','F','G','H',
                                'X','C','V','B','J','K','L','Z')))
SPECIAL = ('Escape','Tab','Backtab','Backspace','Return','Enter','Insert','Delete','Pause','Print','Home','End',
           'Left','Up','Right','Down','PageUp','PageDown','Shift','Control','Alt','Meta','CapsLock','NumLock',
           'ScrollLock','Space','Apostrophe','Comma','Minus','Period','Slash','Semicolon','Equal','BracketLeft',
           'Backslash','BracketRight','QuoteLeft','Plus','Asterisk')
KEYS = tuple('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') + SPECIAL + tuple(f'F{i}' for i in range(1,25))
KEYS += tuple('Numpad'+name for name in ('0','1','2','3','4','5','6','7','8','9','Enter','Plus','Minus','Period',
                                      'Asterisk','Slash','Up','Down','Left','Right','Home','End','PageUp','PageDown',
                                      'Insert','Delete','Clear'))
LATIN = ('Agrave','Aacute','Acircumflex','Atilde','Adiaeresis','Aring','AE','Ccedilla','Egrave','Eacute',
         'Ecircumflex','Ediaeresis','Igrave','Iacute','Icircumflex','Idiaeresis','ETH','Ntilde','Ograve','Oacute',
         'Ocircumflex','Otilde','Odiaeresis','Ooblique','Ugrave','Uacute','Ucircumflex','Udiaeresis','Yacute',
         'THORN','ssharp','exclamdown','questiondown')
KEYS += LATIN
KEY_SET = frozenset(KEYS)
ONLINE_RESERVED = frozenset(('Pause','ScrollLock','F8'))
ALIASES = dict(return_='Return',kp_enter='NumpadEnter',escape='Escape',space='Space',backspace='Backspace',
               prior='PageUp',next='PageDown',shift_l='Shift',shift_r='Shift',control_l='Control',control_r='Control',
               alt_l='Alt',alt_r='Alt',meta_l='Meta',meta_r='Meta',super_l='Meta',super_r='Meta',
               caps_lock='CapsLock',num_lock='NumLock',scroll_lock='ScrollLock',print='Print',
               apostrophe='Apostrophe',quotedbl='Apostrophe',comma='Comma',less='Comma',minus='Minus',
               underscore='Minus',period='Period',greater='Period',slash='Slash',question='Slash',
               semicolon='Semicolon',colon='Semicolon',equal='Equal',plus='Equal',bracketleft='BracketLeft',
               braceleft='BracketLeft',bracketright='BracketRight',braceright='BracketRight',backslash='Backslash',
               bar='Backslash',grave='QuoteLeft',asciitilde='QuoteLeft',backtab='Backtab',iso_left_tab='Backtab',
               kp_add='NumpadPlus',kp_subtract='NumpadMinus',kp_multiply='NumpadAsterisk',kp_divide='NumpadSlash',
               kp_decimal='NumpadPeriod',kp_separator='NumpadPeriod',kp_prior='NumpadPageUp',kp_next='NumpadPageDown',
               kp_begin='NumpadClear')
ALIASES['return'] = 'Return'
for name in LATIN:ALIASES[name.casefold()] = name
for character,name in zip('ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖØÙÚÛÜÝÞß¡¿',LATIN):
    ALIASES[character.casefold()]=name
for digit in range(10): ALIASES[f'kp_{digit}'] = f'Numpad{digit}'
for name in ('Up','Down','Left','Right','Home','End','Insert','Delete'):
    ALIASES['kp_'+name.lower()] = 'Numpad'+name
for shifted,digit in zip(('exclam','at','numbersign','dollar','percent','asciicircum','ampersand','asterisk','parenleft','parenright'), '1234567890'):
    ALIASES[shifted] = digit

def event_key(event):
    """Tk key -> PCSX2 2.x Qt key name, including punctuation and numpad keys."""
    symbol = str(event.keysym)
    if os.name == 'nt':
        code = getattr(event,'keycode',0)
        if 0x60 <= code <= 0x69: return f'Numpad{code-0x60}'
        if code in (0x6A,0x6B,0x6D,0x6E,0x6F):
            return {0x6A:'NumpadAsterisk',0x6B:'NumpadPlus',0x6D:'NumpadMinus',0x6E:'NumpadPeriod',0x6F:'NumpadSlash'}[code]
    name = ALIASES.get(symbol.casefold(),symbol.upper() if len(symbol)==1 and symbol.isascii() else symbol)
    return name if name in KEY_SET else None

def validate(mapping, *, online=False):
    if type(mapping) is not dict or set(mapping)-set(BUTTONS):
        raise ValueError('Unknown keyboard control or invalid keyboard profile.')
    result = {button:mapping.get(button,'') for button in BUTTONS}
    for button,key in result.items():
        if type(key) is not str or key and key not in KEY_SET:
            raise ValueError(f'Unsupported key for {button}.')
        if online and key in ONLINE_RESERVED:
            raise ValueError('Pause, ScrollLock and F8 are reserved for the online session.')
    return result

def duplicates(mapping):
    grouped = {}
    for button,key in mapping.items():
        if key: grouped.setdefault(key,[]).append(button)
    return {key:buttons for key,buttons in grouped.items() if len(buttons)>1}

def bindings(mapping, *, online=False):
    return {button:('Keyboard/'+key if key else '') for button,key in validate(mapping,online=online).items()}

def ini_values(text):
    """Preserve repeated bindings, unlike ConfigParser(strict=False)."""
    values = {};section = ''
    for line in text.splitlines():
        clean = line.strip()
        if clean.startswith('[') and clean.endswith(']'):
            section = clean[1:-1]
            section=next((name for name in (*PADS,'Hotkeys') if name.casefold()==section.casefold()),section)
        elif '=' in clean and not clean.startswith(('#',';')):
            key,value = clean.split('=',1)
            if section in PADS:key=next((name for name in (*BUTTONS,'Type') if name.casefold()==key.strip().casefold()),key.strip())
            values.setdefault((section,key.strip()),[]).append(value.strip())
    return values

def ini_replace(text, changes):
    """Replace only owned keys; repeated rows are PCSX2's alternative bindings."""
    lines = text.splitlines();out=[];section='';pending={key:list(value) for key,value in changes.items()}
    changed={(section.casefold(),key.casefold()) for section,key in changes}
    def flush(name):
        for pair in list(pending):
            if pair[0].casefold()==name.casefold():
                out.extend(f'{pair[1]} = {value}' for value in pending.pop(pair))
    for line in lines:
        clean=line.strip()
        if clean.startswith('[') and clean.endswith(']'):
            flush(section);section=clean[1:-1];out.append(line)
        elif '=' in clean and not clean.startswith(('#',';')) and (section.casefold(),clean.split('=',1)[0].strip().casefold()) in changed:
            continue
        else:out.append(line)
    flush(section)
    for name in dict.fromkeys(pair[0] for pair in pending):
        out.append(f'[{name}]');flush(name)
    return '\r\n'.join(out).rstrip()+'\r\n'

def keyboard_profile(text, pad='Pad1'):
    parsed=ini_values(text);result={button:'' for button in BUTTONS}
    for button in BUTTONS:
        for value in parsed.get((pad,button),[]):
            if value.startswith('Keyboard/') and '&' not in value and value[9:] in KEY_SET:
                result[button]=value[9:];break
    return result

def load_offline(root=ROOT):
    path=Path(root)/FILE
    if not path.is_file():return dict(schema=1,pads={},hotkeys={})
    try:record=atomic_files.read_json(path)
    except (OSError,ValueError) as error:raise ValueError('Keyboard profile could not be read; save it again in Keyboard bindings.') from error
    if type(record) is not dict or record.get('schema')!=1 or type(record.get('pads')) is not dict:
        raise ValueError('Keyboard profile is invalid; save it again in Keyboard bindings.')
    if set(record['pads'])-set(PADS):raise ValueError('Unknown offline keyboard player.')
    for mapping in record['pads'].values():validate(mapping)
    if type(record.get('hotkeys',{})) is not dict:raise ValueError('Invalid keyboard shortcut backup.')
    for owned in record.get('hotkeys',{}).values():
        if type(owned) is not dict:raise ValueError('Invalid keyboard shortcut backup.')
        for key,values in owned.items():
            if type(key) is not str or not re.fullmatch(r'[A-Za-z0-9_]+',key) or type(values) is not list or any(
                    type(value) is not str or '\n' in value or '\r' in value for value in values):
                raise ValueError('Invalid keyboard shortcut backup.')
    return record

def save_offline(pad,mapping,root=ROOT):
    save_offline_profiles({pad:mapping},root)

def save_offline_profiles(pads,root=ROOT):
    if type(pads) is not dict or set(pads)-set(PADS):raise ValueError('Unknown keyboard player.')
    checked={pad:validate(mapping) for pad,mapping in pads.items()}
    try:record=load_offline(root)
    except ValueError:
        path=Path(root)/FILE
        if path.is_file():atomic_files.write_bytes(path.with_suffix('.json.bak'),atomic_files.read_bytes(path))
        record=dict(schema=1,pads={},hotkeys={})
    record['pads'].update(checked)
    atomic_files.write_json(Path(root)/FILE,record)

def apply_offline(root=ROOT,config=None):
    root=Path(root)
    if not (root/FILE).is_file():return False
    if config is None:
        import runtime_profile
        config=runtime_profile.CONFIG
    config=Path(config)
    if not config.resolve().is_relative_to(root.resolve()):raise ValueError('Keyboard configuration escaped the isolated emulator profile.')
    original=atomic_files.read_bytes(config);text=original.decode('utf-8-sig')
    record=load_offline(root);before=json.loads(json.dumps(record));parsed=ini_values(text);changes={}
    for pad,mapping in record['pads'].items():
        for button,value in bindings(mapping).items():
            # Keep controllers and controller chords, replace only keyboard alternatives.
            keep=[item for item in parsed.get((pad,button),[]) if 'Keyboard/' not in item and item]
            changes[(pad,button)]=keep+([value] if value else [])
        if any(mapping.values()):changes[(pad,'Type')]=['DualShock2']
    profile=config.relative_to(root).as_posix()
    owned=record.setdefault('hotkeys',{}).setdefault(profile,{})
    for key,values in list(owned.items()):
        if type(values) is not list or any(type(v) is not str or '\n' in v or '\r' in v for v in values):
            raise ValueError('Invalid keyboard shortcut backup.')
        if parsed.get(('Hotkeys',key),[])==['']:
            changes[('Hotkeys',key)]=values
        else:owned.pop(key)
    assigned={key for mapping in record['pads'].values() for key in mapping.values() if key}
    for (section,key),values in parsed.items():
        if section!='Hotkeys':continue
        current=changes.get((section,key),values)
        conflict=False
        for value in current:
            parts=[part.strip() for part in value.split('&')]
            if parts and all(part.startswith('Keyboard/') and part[9:] in assigned for part in parts):conflict=True
        if conflict:
            owned.setdefault(key,current);changes[(section,key)]=['']
        elif key in owned:owned.pop(key)
    updated=ini_replace(text,changes).encode('utf-8')
    # Persist original hotkeys before writing the INI, so an interrupted write cannot lose them.
    if record!=before:atomic_files.write_json(root/FILE,record)
    if updated!=original:atomic_files.write_bytes(config,updated)
    return updated!=original
