"""Guarded offline composition of tag-team attacks.

This builder does not contact PCSX2. A complete director must explicitly admit
the choreography/effects before any hook or ready word is returned to a caller.
"""
import copy
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import struct
import tempfile
import unicodedata

from native_map import A, ADAPTER, GP, GPO, SERIAL
from prototype import ROOT
import battle_mode_policy as modes
import fresh_team_combat as core
import team_participation as participation
import guest_killfeed as feed
import tag_team_rush as tag
import tag_rush_camera as camera
import tag_rush_safety as safety
import tag_rush_hud as captions
import tag_rush_assets as assets
import tag_rush_bootstrap as bootstrap
import tag_rush_effects as effects
import tag_rush_pause as active_pause
import tag_rush_recovery as recovery
import tag_rush_audio_queue as audio_queue
import tag_rush_beam_audio as beam_audio
import tag_rush_launch as launch

META, META_SIZE, META_MAGIC = 0x06D0F000, 0x800, 0x54494E31
CACHE_ROOT = ROOT/'.cache'/'tag-rush'
CACHE_VERSION = 3
NETPLAY_CONTROL, NETPLAY_MAGIC = 0x07B01000, 0x4E504631
PLAYTEST_ENV, PLAYTEST_ROOT_ENV = 'TAGTEAM_TAG_RUSH_PLAYTEST', 'TAGTEAM_TAG_RUSH_ROOT'


def playtest_requested(root=ROOT):
    """Explicit launcher opt-in scoped to this tree, never an inherited copy."""
    if os.environ.get(PLAYTEST_ENV)!='1':return False
    target=os.environ.get(PLAYTEST_ROOT_ENV)
    return bool(target) and Path(target).resolve()==Path(root).resolve()


def selected_iso():
    import game_profile,regional
    name='SLUS_219.78.DBZBT4B14REV2ENG.iso' if SERIAL=='SLUS-21978' else regional.ISO_NAME
    return game_profile.source_iso(ROOT.parent/'games'/name)


def _u(ram,address):return struct.unpack_from('<I',ram,address)[0]
def _jump(address):return struct.pack('<2I',0x08000000|(address>>2),0)
def _jal(address):return struct.pack('<I',0x0C000000|(address>>2))
def _json(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode('utf-8')


def _identity(iso):
    path=Path(iso).resolve(strict=True);stat=path.stat()
    if not path.is_file():raise ValueError('Tag-rush assets require an ISO file')
    asset_source=Path(assets.__file__)
    sources={asset_source.name:hashlib.sha256(asset_source.read_bytes()).hexdigest()}
    for name in ('tag_rush_shots.py','tag_rush_choreography.py'):
        dependency=asset_source.with_name(name)
        try:sources[name]=hashlib.sha256(dependency.read_bytes()).hexdigest()
        except FileNotFoundError:sources[name]=None
    source_hash=hashlib.sha256(_json(sources)).hexdigest()
    record=dict(path=os.path.normcase(str(path)),size=stat.st_size,mtime=stat.st_mtime_ns,
                adapter=ADAPTER,source=source_hash,version=CACHE_VERSION)
    return path,record,hashlib.sha256(_json(record)).hexdigest()


def _asset_payload(plan):
    payload=copy.deepcopy(plan)
    payload['blocks']=[dict(address=p,data_hex=bytes(b).hex()) for p,b in plan['blocks']]
    return json.loads(_json(payload))


def _asset_plan(payload):
    plan=copy.deepcopy(payload);blocks=[]
    for block in plan['blocks']:
        p=block['address'];data=bytes.fromhex(block['data_hex'])
        if type(p) is not int or p%16 or not data or not assets.BASE<=p<p+len(data)<=assets.END:
            raise ValueError('Invalid cached tag animation block')
        blocks.append((p,data))
    blocks.sort()
    if any(p+len(b)>q for (p,b),(q,_) in zip(blocks,blocks[1:])):raise ValueError('Overlapping cached tag animations')
    for entry in plan['variants'].values():
        if not assets.BASE<=entry['address']<assets.END or not 1<=entry['count']<=16:
            raise ValueError('Invalid cached tag animation descriptor')
    plan['blocks']=blocks
    _beam_mutable(plan)
    return plan


def _beam_mutable(pack):
    """Only native texture relocation words may change inside the beam PAK.

    Re-derive this list from the pristine resource. A cached list must never
    exempt arbitrary animation, metadata or code bytes from reinstall checks.
    """
    beam=pack.get('beam_asset')
    if beam is None:return []
    def read(key):
        address,size=beam[key+'_address'],beam[key+'_size']
        if type(address) is not int or type(size) is not int or address%16 or size<=0:
            raise ValueError('Invalid cached tag beam resource')
        for p,data in pack['blocks']:
            if p<=address and address+size<=p+len(data):return data[address-p:address-p+size]
        raise ValueError('Cached tag beam resource escaped its asset block')
    reviewed=assets.validate_native_beam(read('resource'),read('metadata'))
    for key,value in reviewed.items():
        if _json(beam.get(key))!=_json(value):raise ValueError('Cached tag beam recipe changed')
    base=beam['resource_address']
    return [(base+offset,base+offset+size) for offset,size in reviewed['mutable_ranges']]


def _immutable_parts(blocks,mutable):
    """Keep checks on both sides of small native-written fields within blocks."""
    ranges=sorted(mutable)
    for lo,hi in ranges:
        if type(lo) is not int or type(hi) is not int or not tag.BASE<=lo<hi<=tag.END:
            raise ValueError('Invalid tag-rush runtime data range')
    for p,data in blocks:
        cursor=p;end=p+len(data)
        for lo,hi in ranges:
            if hi<=cursor:continue
            if lo>=end:break
            if lo>cursor:yield cursor,data[cursor-p:lo-p]
            cursor=max(cursor,min(end,hi))
        if cursor<end:yield cursor,data[cursor-p:]


def cached_assets(iso):
    """One bounded, checksummed pose pack per ISO/version; no memory dumps."""
    path,identity,key=_identity(iso);cache=CACHE_ROOT/(key+'.json')
    try:
        if cache.stat().st_size>2*1024*1024:raise ValueError('Tag pose cache is too large')
        record=json.loads(cache.read_text(encoding='utf-8'));payload=record['payload']
        if record['identity']!=identity or record['sha256']!=hashlib.sha256(_json(payload)).hexdigest():
            raise ValueError('Tag pose cache changed')
        return _asset_plan(payload),key
    except (OSError,ValueError,KeyError,TypeError):pass
    plan=assets.build_assets(path,include_beam=True,include_camera=True)
    if _identity(path)[2]!=key:raise ValueError('ISO changed while reading tag animations')
    payload=_asset_payload(plan);plan=_asset_plan(payload)
    record=dict(identity=identity,payload=payload,sha256=hashlib.sha256(_json(payload)).hexdigest())
    temporary=None
    try:
        CACHE_ROOT.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile('wb',dir=CACHE_ROOT,prefix=key+'.',suffix='.tmp',delete=False) as out:
            temporary=Path(out.name);out.write(_json(record))
        os.replace(temporary,cache)
    except OSError:
        # Read-only installs can still prepare a match, without a persistent cache.
        pass
    finally:
        if temporary is not None:
            try:temporary.unlink(missing_ok=True)
            except OSError:pass
    return plan,key


def _costume_count(character):
    if SERIAL=='SLUS-21978':
        # Imported fighters can expose nine costumes. Use the selected disc's
        # reviewed resource table rather than a limit from another adapter.
        import bt4_resources
        return bt4_resources.costume_count(character)
    if not 0<=character<161:raise ValueError('Unknown tag-rush character')
    return 4  # The original game's resource layout reserves four per fighter.


def _roster(ram,count):
    result=[]
    mask=_u(ram,participation.CONTROL+12)&~_u(ram,participation.CONTROL+16)
    for index in range(count):
        if not mask&(1<<index):continue
        actor=_u(ram,core.POINTERS+4*index)
        if actor%4 or not 0x100000<=actor<0x8000000-0x1600 or _u(ram,actor)!=index:
            raise ValueError('Tag-rush roster has an uncaptured actor')
        model_id=_u(ram,actor+12);slot=_u(ram,actor+0x994)
        if model_id>=12 or slot>=5:raise ValueError('Tag-rush roster is reloading')
        model=_u(ram,core.MODELS+4*model_id)
        if model%4 or not 0x100000<=model<0x8000000-0x1670 or _u(ram,model+16)!=model_id:
            raise ValueError('Tag-rush roster model is not ready')
        row=actor+0x9A4+164*slot
        character=_u(ram,model+12);costume=_u(ram,row+4);damaged=_u(ram,row+0x60)
        if character>=4096 or costume>=_costume_count(character):
            raise ValueError('Unknown tag-rush character or costume')
        if damaged not in (0,1):raise ValueError('Unknown tag-rush starting clothes state')
        result.append(dict(index=index,character=character,costume=costume,damaged=bool(damaged)))
    return result


def admission_block(pack,admission):
    """Admit reviewed model topologies, never another mod's numeric IDs.

    Currently only the selected costumes are assessed. Unknown/new forms stay
    unarmed until their topology is assessed during a later preparation.
    """
    import character_names
    names=character_names.character_table()
    if not names:raise ValueError('The selected disc has no character-name table')
    def normalized(name):
        plain=unicodedata.normalize('NFKD',str(name))
        return ''.join(c for c in plain.casefold() if c.isalnum())
    non_ki={normalized(n) for n in ('Hercule','Mr. Satan','Mr Satan','Satan','Videl',
            'Great Saiyaman 2','Great Saiyaman II','Great Saiyawoman','Gran Saiyaman 2','Yajirobe',
            'Nam','Android 8','Android Eight','Octavio','General Blue','Chi-Chi','Milk')}
    size=max(names)+1
    if not 1<=size<=4096:raise ValueError('Unknown tag-rush character table size')
    flags=bytearray(size)
    # Guest admission is keyed by character, not costume. A supported copy
    # must never lend its approval to another selected costume of that form.
    refused={row['character'] for row in admission if not row['supported']}
    for row in admission:
        character=row['character']
        if character not in names:raise ValueError('A tag-rush fighter has no reviewed character name')
        if character in refused:continue
        name=names[character].get('base_name') or names[character].get('name','')
        if not name:raise ValueError('A tag-rush fighter has an empty character name')
        flags[character]=1 | (0 if normalized(name) in non_ki else 2)
    address=(max(p+len(b) for p,b in pack['blocks'])+15)&~15
    if address+len(flags)>assets.END:raise ValueError('Tag-rush admission table exceeds asset storage')
    return (address,bytes(flags)),{0x3A0:address,0x3A4:size}


def _control(manager,count,options,training,scene_plan,admission_words):
    import tag_rush_shots as shots
    result=bytearray(tag.control_bytes(manager,count,options,training=training,ready=False))
    words=dict(scene_plan.get('control_words',{}))
    if any(offset not in (tag.C['scene_table'],*range(0x80,0xA4,4),shots.TABLE_OFFSET,shots.MAGIC_OFFSET,0xAC,0xB0) for offset in words):
        raise ValueError('Director tried to publish a reserved tag control field')
    words.update(admission_words)
    for offset,value in words.items():
        if type(value) is not int or not 0<=value<=0xFFFFFFFF:raise ValueError('Invalid tag director control word')
        struct.pack_into('<I',result,offset,value)
    return bytes(result),tuple(words)


def frame_predecessor(ram):
    """Find only the exact known participation wrapper's predecessor call."""
    template=participation.frame_code(0)
    sites=[i for i in range(0,len(template),4) if _u(template,i)==3<<26]
    if len(sites)!=1:raise ValueError('Unknown participation frame layout')
    site=participation.FRAME+sites[0];word=_u(ram,site);previous=(word&0x3FFFFFF)<<2
    if word>>26!=3 or not 0x06000000<=previous<0x08000000 or tag.BASE<=previous<tag.END:
        raise ValueError('Unknown tag-rush frame predecessor')
    if ram[participation.FRAME:participation.FRAME+len(template)]!=participation.frame_code(previous):
        raise ValueError('Participation frame changed; tag rush was not installed')
    return site,previous


def hud_patches(ram):
    """Compose captions while retaining audited attacker-marker call hooks."""
    import viewport_hud as hud
    import quad_viewports as quad
    import lockon_threat as threat
    if _u(ram,hud.CONTROL)!=hud.MAGIC:raise ValueError('Tag rush requires the viewport HUD')
    if _u(ram,quad.CONTROL)!=quad.MAGIC:return captions.hud_patch(ram)
    entry=(tag.CONTROL,tag.MAGIC,captions.DRAW)
    before=hud.hud_extensions(ram);without=tuple(e for e in before if e!=entry);after=without+(entry,)
    marked=_u(ram,threat.CONTROL)==threat.MAGIC and bool(_u(ram,threat.CONTROL+threat.FIELDS['quad_sites']))
    if marked:threat.validate_memory(ram)
    def with_markers(code):
        if not marked:return code
        sites=threat.quad_sites(code,quad.DRAW,A(0x102708))
        if len(sites)!=2:raise ValueError('Unknown tag-rush quad marker positions')
        changed=bytearray(code)
        for site in sites:changed[site-quad.DRAW:site-quad.DRAW+4]=threat.jal(threat.QUAD_LINK)
        return bytes(changed)
    candidates=(before,without) if before!=without else (without,)
    for extensions in candidates:
        old=with_markers(quad.draw(extensions))
        if ram[quad.DRAW:quad.DRAW+len(old)]==old:break
    else:raise ValueError('Unknown per-view renderer; existing HUD was left intact')
    new=with_markers(quad.draw(after))
    if len(new)>quad.SELECT-quad.DRAW:raise ValueError('Tag caption exceeds quad renderer space')
    if any(ram[quad.DRAW+len(old):quad.DRAW+len(new)]):raise ValueError('Quad HUD extension tail is occupied')
    return [] if old==new else [(quad.DRAW,new)]


def _read_meta(ram):
    magic,size=_u(ram,META),_u(ram,META+4)
    if magic!=META_MAGIC or not 0<size<=META_SIZE-8:raise ValueError('Unknown existing tag-rush installation')
    try:return json.loads(bytes(ram[META+8:META+8+size]))
    except (ValueError,TypeError) as error:raise ValueError('Tag-rush install record is corrupt') from error


def _meta_bytes(record):
    data=_json(record)
    if len(data)>META_SIZE-8:raise ValueError('Tag-rush install record exceeds its reservation')
    return struct.pack('<2I',META_MAGIC,len(data))+data+bytes(META_SIZE-8-len(data))


def _not_usable(reason,source,**extra):
    return dict(blocks=[],usable=False,status='Tag rush not armed',source=str(source),limitations=[reason],**extra)


def with_beam_colors(pack):
    """Bind the selected roster names to private beam palettes, outside caches."""
    beam=pack.get('beam_asset')
    if not beam:return pack
    import character_names
    import tag_rush_colors as colors
    address,size=beam['resource_address'],beam['resource_size']
    for base,data in pack['blocks']:
        if base<=address and address+size<=base+len(data):
            resource=data[address-base:address-base+size]
            break
    else:raise ValueError('Native tag beam resource is missing')
    result=copy.deepcopy(pack)
    result['beam_asset']['color_plan']=colors.recipe(resource,address,character_names.character_table())
    return result


def review_playtest_assets(pack,iso=None):
    """Require the complete disc-backed recipe before deliberate local testing.

    The opt-in waives appearance approval only. It does not waive missing clips,
    mismatched descriptors, native effect recipes, or unsafe camera references.
    """
    import model_animations as animations
    import tag_rush_audio as audio
    import tag_rush_shots as shots
    import tag_rush_choreography as choreography
    from native_map import ACTOR_HZ
    def read(address,size):
        if type(address)is not int or type(size)is not int or size<=0:
            raise ValueError('Invalid local tag playtest asset reference')
        for base,data in pack['blocks']:
            if base<=address and address+size<=base+len(data):return data[address-base:address-base+size]
        raise ValueError('Tag attack asset reference is outside its captured block')
    if not pack.get('beam_asset') or not pack['beam_asset'].get('reviewed'):
        raise ValueError('Tag attack requires the reviewed native beam resources')
    _beam_mutable(pack)
    if iso is None:
        raise ValueError('The game disc is required to review tag finisher poses')
    # Derived clips must be reproducible from the selected disc. A self-consistent
    # cache hash alone cannot establish their source, channel data or root edits.
    reviewed_clips=assets.prepared_clips(iso)
    clips={}
    for row in pack.get('clips',[]):
        key=assets.ClipSource(row['character'],row['animation'],row['mesh_entry'])
        if key in clips or key not in reviewed_clips:raise ValueError('Unexpected tag playtest donor clip')
        raw=animations.decompress_animation(read(row['address'],row['size']))
        clip=animations.AnimationClip.from_decoded(key.animation,raw)
        if (raw!=reviewed_clips[key] or clip.frame_count!=row['frames'] or len(clip.tracks)<40 or
                hashlib.sha256(raw).hexdigest()!=row['decoded_sha256']):
            raise ValueError('Tag attack donor clip changed')
        clips[key]=row['address']
    if set(clips)!=set(reviewed_clips):raise ValueError('Tag attack choreography is incomplete')
    donors=pack['role_donors_address'];models=struct.unpack('<3I',read(donors,12))
    for model in models:
        data=read(model,0x920);nodes,height=struct.unpack_from('<I',data,68)[0],struct.unpack_from('<I',data,2332)[0]
        read(nodes,64);height=struct.unpack_from('<f',read(height,8),4)[0]
        if not math.isfinite(height) or height<=0:raise ValueError('Invalid tag playtest donor height')
        # BT4 reads height from its PMDL parameter header, while USA reads
        # model+2332. Every prepared donor must support both native layouts.
        header=struct.unpack_from('<I',data,24)[0]
        if header!=model+0x100 or struct.unpack_from('<f',data,0x174)[0]!=height:
            raise ValueError('Tag donor is missing its native BT4 height header')
    approach=pack.get('approach') or {}
    if approach.get('reviewed')is not True or approach.get('donor_model')!=models[0]:
        raise ValueError('Tag attack requires reviewed native rush launch poses')
    launch_rows=approach.get('clips',[])
    if len(launch_rows)!=5:raise ValueError('Native tag rush launch sequence is incomplete')
    native_address=approach.get('native_address')
    expected_launch=[launch.MAGIC,models[0],5,native_address]
    for row,animation,frames in zip(launch_rows,(329,330,331,332,335),launch.FRAMES):
        address=clips.get(assets.ClipSource(101,animation))
        if row!={'animation':animation,'address':address,'source_frames':frames}:
            raise ValueError('Native tag rush launch pose metadata changed')
        expected_launch.extend((address,frames))
    if struct.unpack('<14I',read(approach.get('table_address'),56))!=tuple(expected_launch):
        raise ValueError('Native tag rush launch table changed')
    native_header=(launch.NATIVE_MAGIC,approach.get('parameter_address'),640,
                   approach.get('camera_address'),384,approach.get('secondary_address'),6,0)
    if struct.unpack('<8I',read(native_address,32))!=native_header:
        raise ValueError('Native tag rush launch resource header changed')
    secondary=tuple(clips.get(assets.ClipSource(101,i),0) for i in (*range(352,357),363))
    if not all(secondary) or struct.unpack('<6I',read(approach.get('secondary_address'),24))!=secondary:
        raise ValueError('Native tag rush launch secondary poses changed')
    native_approach=assets.read_native_approach(iso)
    for key,size in (('parameters',640),('camera',384)):
        address=approach.get('parameter_address' if key=='parameters' else 'camera_address')
        if read(address,size)!=native_approach[key]:
            raise ValueError('Native tag rush launch '+key+' changed')
    custom_donors=pack['custom_role_donors_address']
    if struct.unpack('<3I',read(custom_donors,12))!=(models[0],)*3:
        raise ValueError('Tag attack finisher donor bindings changed')
    names=('two_ki','two_melee','mixed_ki_lead','mixed_ki_partner')
    if set(pack.get('variants',{}))!=set(names):raise ValueError('Tag attack variants are incomplete')
    for name in names:
        row=pack['variants'][name];phases=assets.timeline(name)
        if row['count']!=len(phases):raise ValueError('Tag attack phase count changed')
        for i,phase in enumerate(phases):
            phase_donors=custom_donors if phase.flags&assets.CUSTOM_FINISHER else donors
            expected=(phase.source_frames,*(clips.get(role,0) for role in phase.roles),*phase.starts,phase.flags,
                      *(role.animation if role else 0 for role in phase.roles),*phase.ends,assets.SOURCE_FPS,phase_donors)
            if struct.unpack('<16I',read(row['address']+i*64,64))!=expected:
                raise ValueError('Tag attack phase descriptor changed')
    staging=b''.join(struct.pack('<4f',*row) for name in names
                    for row in assets.NATIVE_STAGING[:4]+((0.,0.,0.,0.),)*(len(assets.timeline(name))-4))
    if read(pack['staging_address'],len(staging))!=staging:raise ValueError('Tag attack staging changed')
    choreography_info=pack.get('choreography_asset') or {}
    stage_table=choreography_info.get('table_address')
    if (type(stage_table)is not int or choreography_info.get('revision')!=choreography.REVISION or
            choreography_info.get('record_size')!=64 or choreography_info.get('reviewed')is not True):
        raise ValueError('Tag attack finisher staging is incomplete')
    expected_staging,expected_info=choreography.pack_records(pack['variants'],stage_table)
    if read(stage_table,len(expected_staging))!=expected_staging:
        raise ValueError('Tag attack finisher positions or beam timings changed')
    if _json(choreography_info)!=_json(expected_info):
        raise ValueError('Tag attack finisher staging metadata changed')
    cam=pack.get('camera_asset') or {}
    if (cam.get('source_sha256')!=shots.SOURCE_SHA256 or cam.get('actor_hz')!=ACTOR_HZ or
            cam.get('reviewed')is not True or len(cam.get('phases',()))!=5):
        raise ValueError('Tag attack requires the reviewed native camera samples')
    for i,(start,frames) in enumerate(zip(shots.PHASE_STARTS,shots.PHASE_FRAMES)):
        address,count,actual_start,actual_frames=struct.unpack('<4I',read(cam['table_address']+i*16,16))
        if (count,actual_start,actual_frames)!=(math.ceil(frames*ACTOR_HZ/60),start,frames):
            raise ValueError('Tag attack camera phase changed')
        values=struct.unpack('<'+'f'*(count*8),read(address,count*32))
        if not all(math.isfinite(x) for x in values):raise ValueError('Invalid tag camera sample')
    if set(pack.get('audio_cues',{}))!=set(names) or not audio.cue_rows(pack):
        raise ValueError('Tag attack impact/audio cues are incomplete')
    import tag_rush_damage
    schedules=tag_rush_damage.schedules(pack)
    if set(schedules)!=set(names) or not all(schedules.values()):
        raise ValueError('Tag attack damage contacts are incomplete')


def build_offline(ram,settings,source='<prepared>',training=False,iso=None,online=False):
    """Normal settings-controlled entry; incomplete preparation is an error."""
    import mod_settings
    import tag_rush_availability
    options=mod_settings.validate_settings(settings)
    reason=tag_rush_availability.preparation_reason(options,'teams',ROOT,adapter=ADAPTER,online=online)
    if reason:return _not_usable(reason,source)
    if len(ram)==0x8000000:
        if _u(ram,NETPLAY_CONTROL)==NETPLAY_MAGIC and _u(ram,NETPLAY_CONTROL+4):
            return _not_usable('Tag-team rush is unavailable online.',source)
        if _u(ram,modes.CONTROL+12)==modes.FFA:
            return _not_usable('Tag-team rush requires teammates.',source)
    plan=build_memory(ram,options,source=source,training=training,iso=selected_iso() if iso is None else iso,
                      online=online,enable_scene=True,reviewed_assets=True)
    if not plan['usable']:
        raise ValueError('Tag attack setup stopped: '+' '.join(plan.get('limitations',[])))
    return plan


def build_playtest(*args,**kwargs):
    """Compatibility for private diagnostic profiles; ordinary Play uses the same build."""
    return build_offline(*args,**kwargs)


def _ready_receipts(ram,manager,count):
    """An armed reinstall must still possess the guest's exact FX receipts."""
    pool=_u(ram,GP+GPO(effects.NATIVE_POOL_OFFSET))
    if pool%4 or not 0x100000<=pool<=len(ram)-24:
        raise ValueError('Existing tag-rush native effect pool changed')
    if _u(ram,bootstrap.STATE+bootstrap.S['pool'])!=pool:
        raise ValueError('Existing tag-rush native effect pool changed')
    for off,expected in ((effects.C['magic'],effects.MAGIC),(effects.C['manager'],manager),
                         (effects.C['count'],count),(effects.C['ready'],1),
                         (effects.C['init_status'],2),(effects.C['pool'],pool)):
        if _u(ram,effects.CONTROL+off)!=expected:
            raise ValueError('Existing tag-rush effect preparation receipt changed')
    for slot in range(2):
        row=effects.ROWS+slot*effects.STRIDE
        for off,expected in ((effects.R['prepared'],effects.PREPARED),
                             (effects.HEADER+36,row+effects.META),
                             (effects.DESC+796,row+effects.HEADER)):
            if _u(ram,row+off)!=expected:
                raise ValueError('Existing tag-rush effect preparation receipt changed')


@modes.matching_install
def build_memory(ram,settings,source='<prepared>',training=False,iso=None,online=False,enable_scene=False,local_playtest=False,reviewed_assets=False):
    """Return a transactional patch plan; never modify the supplied capture.

    A director exposes installation(asset_plan, roster, settings), returning
    usable, limitations, blocks and optional control_words/mutable_ranges.
    A missing/incomplete director returns no hooks and never publishes ready.
    """
    import mod_settings
    options=mod_settings.validate_settings(settings)
    reviewed=reviewed_assets is True or local_playtest is True
    if not options['tag_team_rush_enabled']:return _not_usable('Tag team rush is disabled.',source)
    if online:return _not_usable('Tag-team rush is unavailable online.',source)
    if len(ram)!=0x8000000:raise ValueError('Tag rush requires a full captured match')
    if _u(ram,NETPLAY_CONTROL)==NETPLAY_MAGIC and _u(ram,NETPLAY_CONTROL+4):
        return _not_usable('Tag-team rush is unavailable online.',source)
    if not enable_scene:return _not_usable('The tag cinematic director has not been enabled.',source)
    if iso is None:return _not_usable('Choose the game ISO before preparing tag-rush animations.',source)
    manager,count=_u(ram,core.ACTORS),_u(ram,core.MODE+4)
    if count not in modes.ACTOR_COUNTS or (1,manager,count)!=(_u(ram,core.MODE),_u(ram,core.MODE+8),_u(ram,core.MODE+12)):
        raise ValueError('Tag rush requires a prepared captured team match')
    if manager%4 or not 0x100000<=manager<0x8000000-0x1000 or _u(ram,manager)!=2:
        raise ValueError('Tag-rush battle manager is not live')
    if (_u(ram,participation.CONTROL),_u(ram,participation.CONTROL+4),_u(ram,participation.CONTROL+8))!=(5,manager,count):
        raise ValueError('Tag rush requires captured participation data')
    if _u(ram,modes.CONTROL+12)==modes.FFA:return _not_usable('Tag rush requires teammates; free-for-all is unchanged.',source)
    roster=_roster(ram,count)
    try:
        pack,identity=cached_assets(iso)
        admission=assets.character_admission(iso,roster)
    except (OSError,ValueError) as error:return _not_usable(str(error),source)
    if any(not row['supported'] for row in admission) and not reviewed:
        return _not_usable('This roster includes a skeleton not yet supported by the local choreography.',source,characters=admission)
    try:scene=importlib.import_module('tag_rush_scene')
    except ModuleNotFoundError as error:
        if error.name!='tag_rush_scene':raise
        return _not_usable('Tag-rush cinematic and effects integration is not complete.',source)
    if not callable(getattr(scene,'installation',None)):
        return _not_usable('Tag-rush cinematic installation is not complete.',source)
    if reviewed:
        try:review_playtest_assets(pack,iso=iso)
        except (ValueError,KeyError,TypeError,struct.error) as error:
            return _not_usable('Tag attack assets are incomplete: '+str(error),source,characters=admission)
    try:pack=with_beam_colors(pack)
    except (ValueError,KeyError,TypeError,struct.error) as error:
        return _not_usable('Tag beam colors are incomplete: '+str(error),source,characters=admission)
    scene_plan=scene.installation(pack,roster,options,**({'reviewed_assets':True} if reviewed else {}))
    if not scene_plan.get('usable'):
        return _not_usable(' '.join(scene_plan.get('limitations') or ['Tag-rush cinematic effects are not ready.']),source,characters=admission)
    try:admission_data,admission_words=admission_block(pack,admission)
    except ValueError as error:return _not_usable(str(error),source,characters=admission)
    control,scene_words=_control(manager,count,options,training,scene_plan,admission_words)
    # Refuse old checkpoints missing native provenance or selective actor holds.
    import inactive_actor_guard as inactive
    import cinematic_contact_guard as contact
    for p,data in ((feed.DAMAGE,feed.damage_code()),(inactive.ENTRY,inactive.code())):
        if ram[p:p+len(data)]!=data:raise ValueError('Prepare a new match to install the tag-rush safety hooks')
    existing=_u(ram,tag.CONTROL)==tag.MAGIC
    config={k:v for k,v in options.items() if k.startswith('tag_team_rush_')}
    config['training']=bool(training)
    config['reviewed_assets']=reviewed
    configuration=hashlib.sha256(_json(config)).hexdigest()
    expected_status=recovery.INSTALLED_HOOK if existing else recovery.NATIVE_HOOK
    if ram[recovery.HOOK:recovery.HOOK+8]!=expected_status:
        raise ValueError('Native tag recovery status hook changed; prepare a new match')
    expected_audio=audio_queue.INSTALLED_HOOK if existing else audio_queue.NATIVE_HOOK
    if ram[audio_queue.HOOK:audio_queue.HOOK+4]!=expected_audio:
        raise ValueError('Native tag sound dispatch hook changed; prepare a new match')
    native_contact=_jump(contact.SPECS[2][1])
    if contact.SPECS[2][0]!=launch.CONTACT_HOOK:
        raise ValueError('Native tag rush contact predecessor changed')
    expected_contact=launch.CONTACT_PATCH if existing else native_contact
    if ram[launch.CONTACT_HOOK:launch.CONTACT_HOOK+8]!=expected_contact:
        raise ValueError('Native tag rush contact hook changed; prepare a new match')
    expected_retarget=launch.RETARGET_PATCH if existing else launch.RETARGET_NATIVE
    if ram[launch.RETARGET_HOOK:launch.RETARGET_HOOK+4]!=expected_retarget:
        raise ValueError('Native tag rush retarget hook changed; prepare a new match')
    expected_commit=launch.COMMIT_PATCH if existing else launch.COMMIT_NATIVE
    if ram[launch.COMMIT_HOOK:launch.COMMIT_HOOK+4]!=expected_commit:
        raise ValueError('Native tag rush action-selection hook changed; prepare a new match')
    if reviewed:
        expected_exit=beam_audio.INSTALLED_HOOK if existing else beam_audio.NATIVE_HOOK
        if ram[beam_audio.HOOK:beam_audio.HOOK+4]!=expected_exit:
            raise ValueError('Native tag sound cleanup hook changed; prepare a new match')
    if existing:
        record=_read_meta(ram)
        if (record.get('manager'),record.get('count'),record.get('iso'),record.get('settings'))!=(manager,count,identity,configuration):
            raise ValueError('Tag-rush settings or capture changed; prepare a new match')
        if record.get('native_contact')!=native_contact.hex():
            raise ValueError('Existing tag-rush native contact predecessor changed')
        site,previous=record['frame_site'],record['previous']
        original=bytes.fromhex(record['contact'])
        if ram[site:site+4]!=_jal(tag.FRAME) or ram[contact.PROTECTED:contact.PROTECTED+8]!=_jump(safety.CONTACT):
            raise ValueError('Existing tag-rush hook chain changed')
    else:
        if any(ram[tag.BASE:tag.END]):raise ValueError('Tag-rush reservation is occupied')
        site,previous=frame_predecessor(ram)
        head=bytes(ram[contact.PROTECTED:contact.PROTECTED+8])
        original=head if _u(head,0)>>26==2 else bytes(ram[contact.PROTECTED:contact.PROTECTED+len(contact.protected_code())])
        record=dict(version=1,manager=manager,count=count,iso=identity,settings=configuration,
                    frame_site=site,previous=previous,contact=original.hex(),native_contact=native_contact.hex())
    static=[(tag.FRAME,tag.frame_code(previous,bootstrap=True)),(tag.GATE,tag.gate_code()),(tag.ELIGIBLE,tag.eligible_code()),
            (tag.INPUT,tag.input_code()),(tag.TICK,tag.tick_code()),*scene_plan['blocks'],
            *pack['blocks'],admission_data,*camera.pieces(),*captions.pieces(options),*safety.pieces(original),
            *bootstrap.pieces(manager,count,beam_audio=reviewed),*active_pause.pieces(),
            (launch.CONTACT_OLD,native_contact)]
    if reviewed:static.extend(beam_audio.pieces(iso,manager))
    # STATE is runtime data; neither a repeated install nor new HUD composition
    # should clear the finisher latch or scene ownership.
    mutable=[(safety.STATE,safety.STATE+0x100),(bootstrap.STATE+12,bootstrap.STATE_END),
             *scene_plan.get('mutable_ranges',[]),*_beam_mutable(pack)]
    if reviewed:mutable.append((beam_audio.STATE+8,beam_audio.STATE+64))
    immutable=list(_immutable_parts(static,mutable))
    for p,b in static:
        if not tag.BASE<=p<p+len(b)<=tag.END:raise ValueError('Tag-rush program escaped its reservation')
    spans=sorted((p,p+len(b)) for p,b in static)+[(META,META+META_SIZE),(tag.CONTROL,tag.CONTROL+0x400)]
    spans.sort()
    if any(end>begin for (_,end),(begin,_) in zip(spans,spans[1:])):raise ValueError('Tag-rush programs overlap')
    if existing:
        fixed_words=('magic','manager','count','enabled','shared','charge_ticks','damage','training_full','training')
        for offset in (*[tag.C[key] for key in fixed_words],*scene_words):
            if ram[tag.CONTROL+offset:tag.CONTROL+offset+4]!=control[offset:offset+4]:
                raise ValueError('Existing tag-rush control changed')
        phase=_u(ram,bootstrap.STATE+bootstrap.S['phase']);ready=_u(ram,tag.CONTROL+tag.C['ready'])
        if phase not in (bootstrap.WAITING,bootstrap.READY,bootstrap.FAILED) or ready not in (0,1):
            raise ValueError('Existing tag-rush initialization state changed')
        if ready and phase!=bootstrap.READY:raise ValueError('Tag rush was armed before guest initialization')
        if ready:_ready_receipts(ram,manager,count)
        for p,b in immutable:
            if ram[p:p+len(b)]!=b:raise ValueError(f'Existing tag-rush program changed at {p:08X}')
        if hud_patches(ram):raise ValueError('Existing tag-rush HUD hook changed')
        return dict(blocks=[],usable=True,status='Tag rush already installed',source=str(source),characters=admission,limitations=scene_plan.get('limitations',[]))
    parts=static+[(tag.CONTROL,bytes(control)),(META,_meta_bytes(record))]
    parts+=hud_patches(ram)
    parts+=[(site,_jal(tag.FRAME)),(contact.PROTECTED,_jump(safety.CONTACT)),
            (recovery.HOOK,recovery.INSTALLED_HOOK),(audio_queue.HOOK,audio_queue.INSTALLED_HOOK),
            (launch.CONTACT_HOOK,launch.CONTACT_PATCH),(launch.RETARGET_HOOK,launch.RETARGET_PATCH),
            (launch.COMMIT_HOOK,launch.COMMIT_PATCH)]
    if reviewed:parts.append((beam_audio.HOOK,beam_audio.INSTALLED_HOOK))
    # The installed hooks remain inert until the guest bootstrap initializes
    # both native FX descriptors and publishes ready on the game thread.
    return dict(blocks=[dict(address=p,expected_hex=bytes(ram[p:p+len(b)]).hex(),data_hex=bytes(b).hex()) for p,b in parts],
                usable=True,status='Tag attacks installed',source=str(source),characters=admission,
                assets_bytes=pack.get('bytes_used',0),limitations=scene_plan.get('limitations',[]))
