"""Read-only exact-disc/profile check before the isolated BT4 launch."""
import configparser,hashlib,io,json,re
from pathlib import Path
import pycdlib
from bt4_disc import ISO,ROOT

PINE_SLOT='28012'   # the BT4 profile's PINE slot (play_launcher.PINE_SLOT of this tree)
# The summary lines the Play window and Check installation show (English keys, Spanish in localization.ES).
READY='BT4 B14 REV2 disc verified; independent profile, memory cards and PINE port {port} ready.'
SCANNED=('Compatibility scan: {fighters} fighters; {valid}/{total} costume variants validated. Unusable costumes are '
         'rejected before extra creation.')
LABELS='Battle labels verified for {count} character/form entries.'

def check_profile(config,data):
    """PCSX2.ini of the BT4 profile: PINE slot 28012 and the features the mod needs; every [Folders]
    entry and memory card stays inside this profile. PCSX2 resolves relative folders against its data
    folder (runtime_profile.DATA): the runtime folder on Windows, <runtime>/PCSX2 for the Linux AppImage."""
    runtime=Path(data).resolve()
    for key,value in [('PINESlot',PINE_SLOT),('ExtraMemory','true'),('EnableCheats','true'),('EnablePINE','true')]:
        if not re.search(rf'(?m)^{key}\s*=\s*{value}\s*$',config):raise ValueError(f'BT4 requires {key}={value}')
    folders=re.search(r'(?ms)^\[Folders\]\s*\n(.*?)(?=^\[|\Z)',config).group(1)
    for line in folders.splitlines():
        if '=' not in line:continue
        key,value=(p.strip() for p in line.split('=',1))
        resolved=(runtime/value).resolve()
        if not resolved.is_relative_to(runtime):
            raise ValueError(f'BT4 {key} must stay inside its independent profile')
    parsed=configparser.ConfigParser(interpolation=None,strict=False)
    parsed.read_string(config)
    cards=(runtime/parsed['Folders']['MemoryCards']).resolve()
    for key,value in parsed['MemoryCards'].items():
        if key.endswith('_filename') and not (cards/value).resolve().is_relative_to(cards):
            raise ValueError(f'BT4 {key} must use an independent memory card')

def check():
    import compatibility_profile
    import game_profile
    import runtime_profile
    from localization import tr
    # The scan's progress in the player's language, and nothing for the unchanged profile of every launch.
    compatibility=compatibility_profile.prepare(progress=game_profile.scan_progress)
    record={'disc_members':compatibility['identity']['members']}
    iso=pycdlib.PyCdlib();iso.open(str(ISO))
    try:
        for member,wanted in record['disc_members'].items():
            out=io.BytesIO();iso.get_file_from_iso_fp(out,iso_path=member)
            if hashlib.sha256(out.getvalue()).hexdigest()!=wanted:
                raise ValueError(f'This build requires the inspected B14 REV2 disc: {member} changed')
        # The chosen game disc's extracted references (Mod settings > Game disc; game_profile resolves them).
        from native_map import elf_path
        if hashlib.sha256(elf_path(ROOT).read_bytes()).hexdigest()!=record['disc_members']['/SLUS_219.78;1']:
            raise ValueError('BT4 native reference changed')
        for name in ('DBZ4.BIN','DBZP.BIN'):
            if hashlib.sha256(game_profile.reference(name).read_bytes()).hexdigest()!=record['disc_members'][f'/BIN/{name};1']:
                raise ValueError(f'BT4 local reference changed: {name}')
    finally:iso.close()
    check_profile(runtime_profile.CONFIG.read_text(encoding='utf-8-sig'),runtime_profile.DATA)
    # Exercise the same fixed-slot label path as match preparation for every
    # form, including translated names that are not in the selected roster.
    from character_names import character_table
    from guest_killfeed import name_data
    labels=character_table()
    name_data({i:row['name'] for i,row in labels.items()})
    print(tr(READY,port=PINE_SLOT))
    summary=compatibility['summary']
    print(tr(SCANNED,fighters=summary['base_fighters_valid'],valid=summary['costume_variants_valid'],
             total=summary['costume_variants']))
    print(tr(LABELS,count=len(labels)))
    return record

if __name__=='__main__':check()
