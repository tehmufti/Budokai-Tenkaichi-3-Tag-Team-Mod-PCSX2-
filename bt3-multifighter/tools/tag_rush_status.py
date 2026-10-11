"""Read-only tag-rush diagnostics; no emulator connection or memory writes.

inspect_words accepts a read_u32 callable for an existing diagnostic reader.
The command line can inspect an existing RAM snapshot without creating one.
"""
import argparse
import json
import struct
from pathlib import Path

from native_map import A, GP, ACTOR_HZ
import tag_team_rush as tag
import tag_rush_bootstrap as boot
import mod_settings


BOOT_ERRORS = {0: None, 1: 'Captured battle changed', 2: 'Online play is excluded',
               3: 'Native effect prerequisites timed out', 4: 'Native effect initialization failed',
               5: 'Private beam sound bank could not be initialized'}


def inspect_words(read_u32):
    """Explain captured settings, startup gates, meters and roster admission.

    Native pointers are checked before dereference. This report never claims
    a scene is safe to start: the guest still performs its full preflight.
    """
    def u(address):
        if type(address) is not int or not 0 <= address <= 0x08000000-4:
            raise ValueError('Diagnostic read is outside EE RAM')
        return read_u32(address)&0xFFFFFFFF
    def pointer(address,size):return address%4==0 and 0x100000<=address<=0x08000000-size
    def byte(address):return (u(address&~3)>>(8*(address&3)))&255
    report={'installed':u(tag.CONTROL)==tag.MAGIC,'gate_reasons':[],'fighters':[]}
    if not report['installed']:
        report['gate_reasons'].append('This match has no tag-rush playtest installed')
        return report
    c={key:u(tag.CONTROL+offset)for key,offset in tag.C.items()}
    report.update({key:c[key] for key in ('enabled','ready','active','shared','training','training_full',
                                         'damage','clock','start_requests','completed','cancelled')})
    report['charge_seconds']=c['charge_ticks']/ACTOR_HZ
    reasons=report['gate_reasons']
    if not c['enabled']:reasons.append('Disabled in this match settings')
    if not c['ready']:reasons.append('Native scene initialization is not ready')
    if u(boot.STATE)==boot.MAGIC:
        report['initialization']={'phase':u(boot.STATE+boot.S['phase']),
                                  'age':u(boot.STATE+boot.S['age']),
                                  'error':BOOT_ERRORS.get(u(boot.STATE+boot.S['error']),'Unknown startup error')}
    manager=u(GP-22364)
    captured=pointer(manager,0x300) and manager==c['manager'] and u(manager)==2
    if (not captured or not u(tag.core.MODE) or u(tag.core.MODE+8)!=manager
            or c['count']!=u(tag.core.MODE+4) or c['count']!=u(tag.core.MODE+12)
            or c['count'] not in tag.modes.ACTOR_COUNTS):
        reasons.append('Battle or fighter registry differs from this preparation')
        return report
    import tag_rush_approach as approach
    if (u(approach.STATE)==approach.MAGIC and
            u(approach.STATE+approach.S['manager'])==manager and
            u(approach.STATE+approach.S['count'])==c['count']):
        ticks=u(approach.STATE+approach.S['ticks'])
        report['approach']={
            'active':bool(u(approach.STATE+approach.S['active'])),
            'seconds_left':round(max(0,approach.TIMEOUT-ticks)/ACTOR_HZ,2),
            'misses':u(approach.STATE+approach.S['misses']),
            'connected':u(approach.STATE+approach.S['connected']),
            'last_miss_reason':approach.MISS_REASONS.get(u(approach.STATE+approach.S['reason']),'Unknown approach refusal'),
        }
    if u(tag.modes.CONTROL+12)==tag.modes.FFA:reasons.append('Free-for-all has no tag teammates')
    if u(tag.start.CONTROL):reasons.append('Waiting for the match loading hold to release')
    if u(A(0x333700)):reasons.append('Game is paused')
    flags=u(A(0x3337B8))
    # Native218230 opens the pause menu with 0x4100; quiet preparation
    # cannot resume it. Keep this distinct from a stage replacement.
    if flags&0x4000:reasons.append('Native pause menu is open; resume from the game pause menu')
    elif flags&0x100:reasons.append('Native battle pause is active')
    if flags&0x2000:reasons.append('Native stage transition is active')
    if u(A(0x3337C0))!=1:reasons.append('Native battle updates are not running')
    battle=u(A(0x2FEB38))
    if not pointer(battle,0x108) or u(battle)!=3:reasons.append('Waiting for ordinary combat after the intro')
    if u(manager+628):reasons.append('A native scene or resource handshake blocks new invitations')
    flags,count=u(tag.CONTROL+0x3A0),u(tag.CONTROL+0x3A4)
    flags_valid=0<count<=4096 and pointer(flags,count)
    present=u(tag.participation.CONTROL+12)&~u(tag.participation.CONTROL+16)
    for index in range(c['count']):
        row={'physical':index,'team':index&1,'present':bool(present&(1<<index))}
        actor=u(tag.core.POINTERS+4*index)
        if not pointer(actor,0x1600) or u(actor)!=index:
            row['unavailable']='Fighter identity is not ready';report['fighters'].append(row);continue
        meter=tag.METERS+index*tag.METER_STRIDE
        row.update(cpu=bool(u(actor+0x1278)),target=u(tag.core.TABLE+4*index),action=u(actor+2376),
                   meter_percent=round(100*min(u(meter),c['charge_ticks'])/max(c['charge_ticks'],1),1),
                   allies=u(meter+tag.T['allies']))
        slot=u(actor+0x994);row['alive']=slot<5 and 0<u(actor+0x9E4+164*slot)<0x80000000
        model_id=u(actor+12)
        model=u(tag.core.MODELS+4*model_id) if model_id<12 else 0
        if pointer(model,0x1700) and u(model+16)==model_id:
            character=u(model+12);state=byte(flags+character) if flags_valid and character<count else 0
            row.update(character=character,admitted=bool(state&1),ki=bool(state&2))
            if not state&1:
                row['unavailable']='Tag attack unavailable for this form/outfit; ordinary combat and beam assist remain available'
        if u(meter+tag.T['inviter'])==index and u(meter+tag.T['expiry'])>c['clock']:
            row['invitation']={'target':u(meter+tag.T['target']),
                               'seconds_left':round((u(meter+tag.T['expiry'])-c['clock'])/ACTOR_HZ,2)}
        report['fighters'].append(row)
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings',type=Path,help='Settings profile to read; never changed')
    parser.add_argument('--snapshot',type=Path,help='Existing EE RAM or PCSX2 snapshot; never changed')
    args=parser.parse_args(argv)
    values=mod_settings.load_settings(args.settings) if args.settings else mod_settings.load_settings()
    report={'settings':{key:values[key] for key in mod_settings.TAG_TEAM_RUSH_KEYS},
            'input':'Charge Ki (L2) + Triangle + Left; release Triangle and Left before another request',
            'scope':'Supported offline matches only. Start a new match; existing matches and Fight Again retain their prepared settings.'}
    if args.snapshot:
        from camera_snapshot import read_ram
        ram=read_ram(args.snapshot)
        report['match']=inspect_words(lambda address:struct.unpack_from('<I',ram,address)[0])
    print(json.dumps(report,indent=2,ensure_ascii=False))
    return report


if __name__=='__main__':main()
