"""Disc-derived Sadistic Dance choreography for tag-team rush attacks.

The move belongs to Android 17 (101), with Android 18 (102) as its auxiliary.
The auxiliary poses are *uncompressed* entries 29..31 of 18's mesh package,
not clips in 17's or 18's ordinary animation bank. Native 24FA50 loads them at
model+1848 and 1D36B8 / 24D390 select them as animations 414..416.

All three roles retain their authored root trajectories. These assets contain
poses only: the director owns contacts, damage, voice, cameras and beam effects.
No synthetic projectile or live native action is hidden in this module.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import struct

BASE, END = 0x06D10000, 0x06D60000
DESCRIPTOR_STRIDE = 64
SOURCE_FPS = 60
HOLD_HELPER = 1
BEAM_LEAD, BEAM_PARTNER, FINISHER = 2, 4, 8
CUSTOM_FINISHER = 16
OWN_CLASH_POSE = 32
SLAM_DOWN = 64
CHARGE_BEAM = 128
NATIVE_STAGING = ((0., -160., 0., 0.),) * 4 + ((0., 0., 0., 0.),)


class TagRushAssetError(ValueError):
    """The selected disc does not contain the reviewed choreography."""


@dataclass(frozen=True)
class ClipSource:
    character: int
    animation: int
    mesh_entry: int | None = None


@dataclass(frozen=True)
class Phase:
    name: str
    source_frames: int
    roles: tuple[ClipSource | None, ClipSource | None, ClipSource | None]
    ends: tuple[int, int, int]
    flags: int = 0
    starts: tuple[int, int, int] = (0, 0, 0)

    def ticks(self, actor_hz: int) -> int:
        if type(actor_hz) is not int or actor_hz <= 0:
            raise ValueError('Actor update frequency must be positive')
        return math.ceil(self.source_frames * actor_hz / SOURCE_FPS)


LEAD = {i: ClipSource(101, i) for i in range(352, 362)}
PARTNER = {i: ClipSource(102, i, 29 + i - 414) for i in range(414, 417)}
APPROACH_FRAMES = {329:13,330:30,331:13,332:9,335:6}
APPROACH_MAGIC = 0x54414C31
EXPECTED_FRAMES = {**{LEAD[i]: n for i, n in zip(range(352, 362),
    (68, 99, 149, 119, 262, 68, 99, 149, 119, 262))},
    **{PARTNER[i]: n for i, n in zip(range(414, 417), (149, 119, 262))},
    **{ClipSource(101,i):n for i,n in APPROACH_FRAMES.items()}, ClipSource(101,363):59}

OPENING = (
    Phase('opening strike', 68, (LEAD[352], None, LEAD[357]), (68, 0, 68), HOLD_HELPER),
    Phase('partner entrance', 99, (LEAD[353], None, LEAD[358]), (99, 0, 99), HOLD_HELPER),
    Phase('paired combination', 149, (LEAD[354], PARTNER[414], LEAD[359]), (149, 149, 149)),
    Phase('paired finishing kick', 119, (LEAD[355], PARTNER[415], LEAD[360]), (119, 119, 119)),
)


def timeline(variant: str) -> tuple[Phase, ...]:
    """Source-frame recipes; mixed roles preserve which participant uses ki.

    Beam roles use each actual fighter's native beam-clash pose. Their idle
    descriptor is a safe placement marker; OWN_CLASH_POSE selects the live
    animation bank instead of decoding that marker as a borrowed beam pose.
    """
    import tag_rush_choreography as choreography
    import tag_rush_special_pair as special
    if variant==special.NAME:return special.timeline()
    sources={name:ClipSource(101,row[0]) for name,row in choreography.DERIVED.items()}
    def phase(name,frames,roles,flags=0):
        return Phase(name,frames,tuple(sources[r] for r in roles),(frames,)*3,flags|CUSTOM_FINISHER)
    if variant == 'two_ki':
        ending=(phase('opposing airborne stances',24,('idle','idle','crossfire_wait')),
                phase('airborne crossfire beams',180,('idle','idle','beam_reaction'),BEAM_LEAD|BEAM_PARTNER|FINISHER|OWN_CLASH_POSE|CHARGE_BEAM))
    elif variant == 'two_melee':
        ending=(phase('lead body combination',62,('body_combo','idle','body_reactions')),
                phase('partner return kick',32,('retreat','relay_kick','kick_reaction')),
                phase('sideways chase strike',30,('chase_strike','idle','chase_reaction')),
                phase('paired overhead slam',36,('slam_strike','slam_strike','slam_reaction')),
                phase('airborne slam aftermath',30,('idle','idle','air_fall'),FINISHER|SLAM_DOWN))
    elif variant in ('mixed_ki_lead','mixed_ki_partner'):
        lead=variant=='mixed_ki_lead'
        ending=(phase('melee body combination',62,('idle','body_combo','body_reactions') if lead else ('body_combo','idle','body_reactions')),
                phase('launch into the firing lane',32,('idle','relay_kick','kick_reaction') if lead else ('relay_kick','idle','kick_reaction')),
                phase('aerial relay',30,('idle','retreat','tossed') if lead else ('retreat','idle','tossed')),
                phase('side-on interception beam',180,('idle','retreat','intercept_reaction') if lead else ('retreat','idle','intercept_reaction'),
                      (BEAM_LEAD if lead else BEAM_PARTNER)|FINISHER|OWN_CLASH_POSE|CHARGE_BEAM))
    else:
        raise ValueError(f'Unknown tag rush variant: {variant}')
    return OPENING + ending


TRANSLATED_BONES=frozenset((0,2,31,45,52))
LAST_AUTHORED_BONE=58
OPTIONAL_TAIL_BONES=frozenset((4,5,6,7))


def prepared_clips(iso):
    """Recompute every final clip from disc sources, including derived poses."""
    import tag_rush_choreography as choreography
    original=read_clips(iso);derived,_=choreography.prepared(iso)
    original[LEAD[357]]=choreography.stabilize_opening_victim(original[LEAD[357]],original[LEAD[359]])
    original[LEAD[358]]=choreography.recover_entrance_victim(original[LEAD[358]],original[LEAD[359]],original[LEAD[357]])
    original[LEAD[353]]=choreography.raise_entrance_contact(original[LEAD[353]],1)
    original[LEAD[354]]=choreography.raise_entrance_contact(original[LEAD[354]],2)
    original.update({ClipSource(101,animation):raw for animation,raw in derived.items()})
    used={role for name in ('two_ki','two_melee','mixed_ki_lead','mixed_ki_partner')
          for phase in timeline(name) for role in phase.roles if role is not None}
    used.update(ClipSource(101,i) for i in (*APPROACH_FRAMES,*range(352,357),363))
    result={source:raw for source,raw in original.items() if source in used}
    # Imported BT4 rigs may attach the contact marker to motion root1 instead
    # of root0. That is equivalent for this choreography only while root1 is
    # left at its native bind transform; a future animated root needs review.
    from model_animations import AnimationClip
    if any(track.bone_id == 1 for source,raw in result.items()
           for track in AnimationClip.from_decoded(source.animation,raw).tracks):
        raise TagRushAssetError('Tag choreography unexpectedly animates native motion root1')
    # Imported outfits can split a drawable joint into several native parts.
    #24BBE8 visits each part: rotations are shared safely; translations would
    #be adjusted repeatedly. The tag retarget wrapper supplies each admitted
    #translated hand marker once; all other duplicate translated parts fail.
    for source,raw in result.items():
        for track in AnimationClip.from_decoded(source.animation,raw).tracks:
            if track.bone_id>LAST_AUTHORED_BONE:
                raise TagRushAssetError('Tag choreography animates an imported accessory joint')
            if track.bone_id not in TRANSLATED_BONES and any(k.translation is not None for k in track.keys):
                raise TagRushAssetError('Tag choreography translates a segmented native joint')
    return result


def literal_pack(decoded: bytes) -> bytes:
    """Use native byte-pair packets with identity dictionaries, without loss."""
    from model_animations import AnimationClip, MAX_DECODED_SIZE
    if not 148 <= len(decoded) <= MAX_DECODED_SIZE:
        raise TagRushAssetError('Tag rush animation exceeds native scratch storage')
    AnimationClip.from_decoded(0, decoded)
    packets = bytearray()
    for start in range(0, len(decoded), 32767):
        chunk = decoded[start:start + 32767]
        packets.extend(b'\xff\x80\xfe')
        packets.extend(struct.pack('>H', len(chunk)))
        packets.extend(chunk)
    return struct.pack('<2I', len(decoded), len(packets)) + packets


def _mesh_package(iso, character, costume=0, damaged=False):
    import model_assets
    try:
        import bt4_resources
    except ImportError:
        file_id = 10 * character + (1428 if damaged else 1424) + costume
    else:
        file_id = bt4_resources.request_files(character, costume, damaged)[0]
    return model_assets.read_archive_entry(iso, file_id)


def skeleton_from_package(package, parameters=None):
    """Read bind topology only; no textures, meshes or graphics dependencies.

    Keep native PMDL part headers because 24BBE8 / 250570 walk this linked
    list directly. These compact headers are data for retargeting, never a
    drawable model. Height is mesh entry18+4, as installed at model+2332.
    """
    from model_assets import package_entry
    geometry = package_entry(package, 3)
    params = package_entry(package, 18) if parameters is None else parameters
    if len(geometry) < 144 or geometry[:4] != b'pmdl' or len(params) < 8:
        raise TagRushAssetError('Missing native skeleton or size metadata')
    count, offset = struct.unpack_from('<I', geometry, 8)[0], struct.unpack_from('<I', geometry, 108)[0]
    height = struct.unpack_from('<f', params, 4)[0]
    if not 1 <= count <= 256 or not math.isfinite(height) or not 0 < height < 100:
        raise TagRushAssetError('Invalid native skeleton size')
    # BT4 retains some edited meshes in the original 252-entry container.
    # Its separate parameter package, not mesh entry count, identifies them.
    imported = parameters is not None
    rows, stack, seen, retarget_duplicates = [], [], {}, set()
    for index in range(256):
        if not 0 <= offset <= len(geometry) - 64:
            raise TagRushAssetError('Truncated skeleton part')
        size, pop, last, vertices, bone = struct.unpack_from('<IHHHH', geometry, offset)
        if size < 64 or offset + size > len(geometry) or last not in (0,1):
            raise TagRushAssetError('Invalid skeleton part chain')
        parent = stack[-1] if stack else -1
        bind_vectors = tuple(struct.unpack_from('<3f',geometry,offset+field) for field in (16,32,48))
        bind_signature = b''.join(geometry[offset+field:offset+field+12] for field in (16,32,48))
        if bone in seen:
            previous = seen[bone]
            # Native imported outfits split drawable joints into sibling mesh
            # parts. They share a rotation channel but retain their own bind.
            # A few imported outfits repeat an identical invisible hand-effect
            # marker. The tag-only retarget wrapper deduplicates those markers
            # in a private descriptor; native drawable hierarchy is untouched.
            # Roots/contact translations and differing hand binds stay strict.
            marker=(bone in (49,50,51) and size == 64 and vertices == 0 and pop >= 1
                    and previous['leaf_marker'])
            segmented=(bone not in TRANSLATED_BONES and size > 64 and vertices > 0
                       and previous['drawable_leaf'])
            repeated_hand=(bone in (31,45) and size == 64 and vertices == 0 and pop >= 1
                           and previous['leaf_marker'] and bind_signature == previous['bind_signature']
                           and all(math.isfinite(v) for vector in bind_vectors for v in vector))
            accessory=bone>LAST_AUTHORED_BONE
            if not (imported and (accessory or (previous['parent']==parent and (marker or segmented or repeated_hand)))):
                raise TagRushAssetError('Invalid duplicate skeleton part')
            if repeated_hand:retarget_duplicates.add(bone)
        local = struct.unpack_from('<3f', geometry, offset + 48)
        if not all(math.isfinite(v) for v in local):
            raise TagRushAssetError('Non-finite skeleton bind translation')
        header = bytearray(geometry[offset:offset + 64])
        struct.pack_into('<I', header, 0, 64)
        struct.pack_into('<H', header, 8, 0)  # No drawable vertices in this data-only header.
        rows.append(dict(bone=bone, parent=parent, vertices=vertices,
                         translation=local, header=bytes(header)))
        seen.setdefault(bone, dict(parent=parent,index=index,leaf_marker=size == 64 and vertices == 0 and pop >= 1,
                                   drawable_leaf=size > 64 and vertices > 0 and pop == 1,bind_signature=bind_signature))
        stack.append(bone)
        if pop > len(stack):
            raise TagRushAssetError('Invalid skeleton parent chain')
        if pop: del stack[-pop:]
        offset += size
        if last:break
    else:
        raise TagRushAssetError('Unterminated skeleton part chain')
    # Native250570/24BBE8 receive only the first-part pointer and follow each
    #bounded size to its terminal marker. Imported meshes retain stale declared
    #counts after adding/removing hair, clothing and effect markers. That count
    #is advisory for them. Some native chains leave only outer root0 on the
    #stack at their terminal part; no following node can consume that root.
    #Do not accept an unfinished nested joint chain. The strict
    #core topology check below remains separate from these format checks.
    if imported and (stack not in ([],[0]) or rows[0]['bone']!=0 or rows[0]['parent']!=-1):
        raise TagRushAssetError('Unclosed imported skeleton root')
    if not imported and len(rows) != count:
        raise TagRushAssetError('Invalid skeleton part count')
    return dict(height=height, rows=tuple(rows), retarget_duplicate_bones=tuple(sorted(retarget_duplicates)))


def read_skeleton(iso, character, costume=0, damaged=False):
    parameters = None
    try:
        import bt4_resources  # noqa: F401 - this adapter moves mesh metadata out of the mesh.
    except ImportError:
        pass
    else:
        import model_assets
        parameters = model_assets.package_entry(model_assets.read_archive_entry(iso, 4150 + character), 2)
    return skeleton_from_package(_mesh_package(iso, character, costume, damaged), parameters)


def read_donor_bindings(iso):
    return {character: read_skeleton(iso, character) for character in (101, 102)}


def pack_donor_bindings(bindings, base):
    """Synthetic source models accepted only by native 24BBE8/250570.

    Call 24BBE8(decoded_scratch, recipient_model, donor_model, 0, 0) after
    decoding. It subtracts donor local bind translations, scales their Y
    displacement by the native height ratio, and adds recipient local binds.
    This preserves the authored travel without copying clips for each fighter.
    BT4's native retarget also reads *(model+24)+0x74 for the source height;
    retain both layouts in the data-only model so neither ABI reads null RAM.
    """
    data, models = bytearray(), {}
    for character in (101, 102):
        data.extend(bytes((-len(data)) % 16)); start = base + len(data)
        skeleton = bindings[character]; rows = skeleton['rows']
        model = bytearray(0x920)
        nodes = start + len(model)
        height = nodes + len(rows) * 64
        struct.pack_into('<I', model, 24, start + 0x100)
        struct.pack_into('<f', model, 0x174, skeleton['height'])
        struct.pack_into('<I', model, 68, nodes)
        struct.pack_into('<I', model, 2332, height)
        data.extend(model)
        data.extend(b''.join(row['header'] for row in rows))
        data.extend(struct.pack('<If', 0, skeleton['height']))
        models[character] = start
    data.extend(bytes((-len(data)) % 16))
    role_table = base + len(data)
    data.extend(struct.pack('<3I', models[101], models[102], models[101]))
    return bytes(data), models, role_table


def character_admission(iso, roster):
    """Assess requested costumes against the choreography's actual topology.

    Roster entries are character IDs or dictionaries with character/costume/
    damaged. The full native torso, limb and head chains must exist with the
    same ancestor chains. Character-specific intermediate bones are retained.
    Extra hair, fingers and props need not match. Different
    body proportions are accepted and retargeted through the donor bindings.
    """
    reference = read_donor_bindings(iso)[101]
    core = set(range(0, 22)) | {31, 32, 33, 34, 35, 45, 46, 47, 52}
    expected = {r['bone']: r['parent'] for r in reference['rows'] if r['bone'] in core}
    reference_ids = {r['bone'] for r in reference['rows']}
    # Parts4..7 form the separate tail branch, not either leg. Tail-less
    # imported outfits can omit the entire branch. Only permit this when
    # the actual source has invisible zero-bind markers rooted at pelvis3;
    # native evaluation ignores their rotation channels on a tail-less rig.
    # Partial chains or missing joints anywhere else still fail admission.
    tail_rows = {r['bone']:r for r in reference['rows'] if r['bone'] in OPTIONAL_TAIL_BONES}
    optional_tail = (set(tail_rows) == OPTIONAL_TAIL_BONES and all(
        row['parent'] == bone-1 and row.get('vertices') == 0
        and all(abs(value) < 1e-6 for value in row['translation'])
        for bone,row in tail_rows.items()))
    cache, result = {}, []
    for entry in roster:
        item = dict(character=entry) if isinstance(entry, int) else dict(entry)
        key = (int(item['character']), int(item.get('costume', 0)), bool(item.get('damaged', False)))
        if key not in cache:
            try:
                skeleton = read_skeleton(iso, *key)
                actual, nodes = {}, {}
                for row in skeleton['rows']:
                    # Match native250570's first matching part semantics.
                    actual.setdefault(row['bone'], row['parent']); nodes.setdefault(row['bone'], row)
                def parent_of(bone):
                    if bone not in actual: return None
                    parent, seen = actual[bone], set()
                    while parent not in reference_ids and parent != -1:
                        if parent not in actual or parent in seen: return None
                        seen.add(parent); parent = actual[parent]
                    return parent
                def equivalent_contact_root(bone, parent):
                    if not (bone == 52 and parent == 0 and actual.get(52) == 1 and actual.get(1) == 0):
                        return False
                    marker = nodes[52]; header = marker.get('header', b'')
                    return (len(header) == 64 and struct.unpack_from('<H',header,8)[0] == 0
                            and struct.unpack_from('<H',header,4)[0] >= 1
                            and all(abs(v) < 1e-6 for v in marker.get('translation', (float('inf'),))))
                omitted_tail = optional_tail and not OPTIONAL_TAIL_BONES.intersection(actual)
                incompatible = tuple(bone for bone, parent in expected.items()
                                     if not (omitted_tail and bone in OPTIONAL_TAIL_BONES)
                                     if parent_of(bone) != parent and not equivalent_contact_root(bone,parent))
                cache[key] = dict(supported=not incompatible, incompatible_bones=incompatible,
                                  height=skeleton['height'], reason='' if not incompatible else 'Incompatible limb topology')
            except (ValueError, IndexError, KeyError, struct.error) as error:
                cache[key] = dict(supported=False, incompatible_bones=(), height=0., reason=str(error))
        result.append(dict(character=key[0], costume=key[1], damaged=key[2], **cache[key]))
    return result


def read_clips(iso) -> dict[ClipSource, bytes]:
    """Extract and validate every reviewed role before installation writes."""
    import model_assets
    import model_animations
    banks, meshes, result = {}, {}, {}
    for source, expected_frames in EXPECTED_FRAMES.items():
        try:
            if source.mesh_entry is not None:
                if source.character not in meshes:
                    meshes[source.character] = _mesh_package(iso, source.character)
                decoded = model_assets.package_entry(meshes[source.character], source.mesh_entry)
            else:
                if source.character not in banks:
                    banks[source.character] = model_assets.read_animation_bank(iso, source.character)
                packed = model_assets.package_entry(banks[source.character], source.animation + 1)
                decoded = model_animations.decompress_animation(packed)
            clip = model_animations.AnimationClip.from_decoded(source.animation, decoded)
            if clip.frame_count != expected_frames or len(clip.tracks) < 40:
                raise TagRushAssetError(f'Unexpected duration or skeleton ({clip.frame_count} frames, {len(clip.tracks)} tracks)')
            result[source] = bytes(decoded)
        except (ValueError, IndexError, KeyError, struct.error) as error:
            raise TagRushAssetError(f'Tag rush donor {source.character}/{source.animation} is unavailable: {error}') from error
    return result


def source_audio_cues(decoded):
    """Read only reviewed global SFX events, never move/voice-bank events.

    Native1D27F8 uses the model's bone3 world position and1DA348 bank0.
    The two floats are near/far attenuation distances, not volume. Native
    events are16-byte rows at+148: uint64 mask, uint32 frame, uint32 parameter.
    Bit0x4000000000 selects11 rather than51 for models whose parameter flags
    at *(model+2332)+16 contain0x8000. Do not substitute the donor's flags.
    """
    if len(decoded) < 148:
        raise TagRushAssetError('Truncated tag rush event header')
    flags, frames = struct.unpack_from('<HH', decoded)
    count = flags >> 8
    channel_offsets = [4*x for x in struct.unpack_from('<71H', decoded, 6) if x]
    end = 148 + count * 16
    if end > len(decoded) or (channel_offsets and end > min(channel_offsets)):
        raise TagRushAssetError('Tag rush events overlap pose data')
    mapping = ((0x10000000, 30), (0x4000000000, 51),
               (0x2000000000000, 24), (0x8000000000000, 31))
    result, previous = [], -1
    for index in range(count):
        mask, frame, parameter = struct.unpack_from('<QII', decoded, 148 + index * 16)
        if not previous <= frame <= frames:
            raise TagRushAssetError('Tag rush event frame is outside its clip')
        previous = frame
        # Native ultimate handler1D3170: flag80 creates type16 visual at the
        # parameter-selected bone and global sound73 at the role's torso.
        # Do not call that whole handler: it also applies hitstop/gameplay.
        if mask & 0x80:
            if not parameter or parameter & (parameter-1):
                raise TagRushAssetError('Unreviewed tag impact bone mask')
            result.append(dict(frame=frame,bank=0,sound_id=73,bone=3,near=200.,far=1500.,
                alternate_sound_id=None,parameter_flag=0,effect_kind=16,impact_bone=parameter.bit_length()-1))
        for flag, sound in mapping:
            if mask & flag:
                result.append(dict(frame=frame, bank=0, sound_id=sound, bone=3,
                    near=200., far=1500., alternate_sound_id=11 if sound == 51 else None,
                    parameter_flag=0x8000 if sound == 51 else 0))
    return tuple(result)


def validate_native_beam(resource, metadata):
    """Bound the reviewed visual-only Kamehameha descriptor before guest use.

    14CEB0 consumes entry4, then shape/command entries in section order. The
    four native shape arrays use strides520/264/136/72. This deliberately does
    not accept an arbitrary move merely because its package table is valid.
    """
    from model_assets import package_entry
    if len(metadata) != 640 or metadata[312] != 0 or not 256 <= len(resource) <= 192 * 1024:
        raise TagRushAssetError('Unexpected native beam resource or move metadata')
    count = struct.unpack_from('<I', resource)[0]
    if count != 45:
        raise TagRushAssetError('Unexpected native beam package entry count')
    entries = {i: package_entry(resource, i) for i in range(1, count + 1)}
    script = entries[4]
    expected = ((0, 1, 0), (2, 1, 1), (5, 11, 4), (14, 2, 1), (16, 3, 1), (17, 1, 1))
    if len(script) != 1472 or script[4:6] != bytes((6, 19)):
        raise TagRushAssetError('Unexpected native beam section dimensions')
    rows = tuple(tuple(script[64 + 32*i:67 + 32*i]) for i in range(6))
    if rows != expected:
        raise TagRushAssetError('Unexpected native beam section layout')
    counts, cursor, relocations = [0, 0, 0, 0], 5, []
    for kind, commands, shapes in rows:
        if not kind:
            continue
        group = 3 if kind == 2 else 1 if kind in (5, 10, 12, 15, 16, 17, 18) else 2 if kind == 9 else 0
        counts[group] += shapes
        for _ in range(shapes):
            shape_start = struct.unpack_from('<I', resource, cursor*4)[0] & ~3
            shape = entries[cursor]; cursor += 1
            if len(shape) < 32:
                raise TagRushAssetError('Truncated native beam texture header')
            textures, words = struct.unpack_from('<2I', shape)
            table = words * 4
            if not 1 <= textures <= (32, 16, 8, 4)[group] or table < 32 or table + 64 * textures > len(shape):
                raise TagRushAssetError('Invalid native beam texture table')
            relocations.append((shape_start + 16, 4))
            for j in range(textures):
                pixels, palette = struct.unpack_from('<2I', shape, table + 64*j)
                if any(offset and not table + 64 * textures <= offset * 4 < len(shape) for offset in (pixels, palette)):
                    raise TagRushAssetError('Native beam texture points outside its package entry')
                if pixels: relocations.append((shape_start + table + 64*j + 56, 4))
                if palette: relocations.append((shape_start + table + 64*j + 60, 4))
        for _ in range(commands):
            if not entries[cursor]:
                raise TagRushAssetError('Missing native beam command')
            cursor += 1 if kind in (2, 14) else 2
    if cursor != count + 1 or counts != [1, 6, 0, 1]:
        raise TagRushAssetError('Native beam descriptor allocation changed')
    return dict(descriptor_counts=tuple(counts), descriptor_raw_bytes=sum(n*s for n, s in zip(counts, (520,264,136,72))),
                resource_sha256=hashlib.sha256(resource).hexdigest(), mutable_ranges=tuple(relocations), reviewed=True)


def read_native_beam_asset(iso):
    """Read the same reviewed visual resource from BT3 or BT4's split layout."""
    import model_assets
    try:
        import bt4_resources  # noqa: F401
    except ImportError:
        combat_id = 1433
        metadata = model_assets.package_entry(_mesh_package(iso, 0), 24)
    else:
        combat_id = 5400
        params = model_assets.package_entry(model_assets.read_archive_entry(iso, 4150), 2)
        metadata = params[0x29D0:0x2C50]
    resource = model_assets.package_entry(model_assets.read_archive_entry(iso, combat_id), 3)
    return dict(resource=resource, metadata=metadata, character=0, slot=2, **validate_native_beam(resource, metadata))


def read_native_approach(iso):
    """Original rush move parameters and camera rows, without actor identity."""
    import model_assets
    try:
        import bt4_resources
    except ImportError:
        mesh = _mesh_package(iso, 101)
        parameters = model_assets.package_entry(mesh, 24)
        camera = model_assets.package_entry(mesh, 28)
    else:
        data = model_assets.package_entry(model_assets.read_archive_entry(iso, 4251), 2)
        parameters, camera = data[0x29D0:0x2C50], data[0x2F50:0x30D0]
    if len(parameters)!=640 or len(camera)!=384:
        raise TagRushAssetError('Native rush approach template is incomplete')
    if struct.unpack_from('<f',parameters,44)[0]!=1.5:
        raise TagRushAssetError('Native rush approach timeout changed')
    return dict(parameters=parameters,camera=camera,reviewed=True)


def read_native_staging(iso):
    """The native per-map, per-phase root offsets (Y down, yaw in degrees).

    1C0058 stores ultimate PAK entry3 at actor+5616. 211E78 selects
    16*(5*stage+phase), and 1D7688 adds that to the stage's cinematic anchor.
    The reviewed move uses the same five offsets on every native stage.
    """
    import model_assets
    try:
        import bt4_resources  # noqa: F401
    except ImportError:
        combat_id = 2443
    else:
        combat_id = 5501
    ultimate = model_assets.package_entry(model_assets.read_archive_entry(iso, combat_id), 5)
    table = model_assets.package_entry(ultimate, 3)
    if len(table) != 2816:
        raise TagRushAssetError('Unexpected native paired-rush staging table')
    for stage in range(35):
        rows = tuple(struct.unpack_from('<4f', table, stage*80+phase*16) for phase in range(5))
        if rows != NATIVE_STAGING:
            raise TagRushAssetError('Native paired-rush staging differs from reviewed choreography')
    return NATIVE_STAGING


def build_assets(iso, *, base=BASE, end=END, include_beam=False, include_camera=False):
    """Return guest blocks and explicit phase metadata without emulator writes.

    Each 64-byte phase descriptor has 16 little-endian words: source duration,
    three packed clip pointers, three start frames, flags, three animation IDs,
    three end frames, source FPS, three-role donor table pointer. A zero clip pointer means keep
    the partner's existing idle pose until the authored entrance. The director
    must separately hold that actor; it must not advance an old combat action.
    """
    if type(base) is not int or type(end) is not int or base % 16 or end <= base:
        raise ValueError('Invalid tag rush asset reservation')
    import tag_rush_choreography as choreography
    import tag_rush_special_pair as special
    variants = {name: timeline(name) for name in choreography.VARIANTS}
    special_pack=special.build(iso)
    decoded = prepared_clips(iso)
    source_audio = {source: source_audio_cues(raw) for source, raw in decoded.items()}
    descriptor_size = sum(len(phases) for phases in variants.values()) * DESCRIPTOR_STRIDE
    clip_base = (base + descriptor_size + 15) & ~15
    data, pointers, provenance = bytearray(), dict(special_pack['pointers']), list(special_pack['clips'])
    for source, raw in decoded.items():
        data.extend(bytes((-len(data)) % 16))
        pointers[source] = clip_base + len(data)
        packed = literal_pack(raw)
        data.extend(packed)
        provenance.append(dict(character=source.character, animation=source.animation,
            mesh_entry=source.mesh_entry, frames=struct.unpack_from('<H',raw,2)[0],
            decoded_sha256=hashlib.sha256(raw).hexdigest(), address=pointers[source], size=len(packed)))
    data.extend(bytes((-len(data)) % 16))
    bindings, donor_models, role_donors = pack_donor_bindings(read_donor_bindings(iso), clip_base + len(data))
    data.extend(bindings)
    data.extend(bytes((-len(data)) % 16))
    custom_donors=clip_base+len(data)
    data.extend(struct.pack('<3I',*(donor_models[101],)*3))
    data.extend(bytes((-len(data)) % 16))
    special_donors=clip_base+len(data)
    data.extend(struct.pack('<3I',special_pack['donor_model'],donor_models[101],special_pack['donor_model']))
    data.extend(bytes((-len(data)) % 16))
    approach_address=clip_base+len(data)
    data.extend(struct.pack('<4I',APPROACH_MAGIC,donor_models[101],len(APPROACH_FRAMES),0))
    approach_clips=[]
    for animation,frames in APPROACH_FRAMES.items():
        address=pointers[ClipSource(101,animation)]
        data.extend(struct.pack('<2I',address,frames))
        approach_clips.append(dict(animation=animation,address=address,source_frames=frames))
    native_approach=read_native_approach(iso)
    data.extend(bytes((-len(data)) % 16))
    native_address=clip_base+len(data)
    parameter_address=native_address+64
    camera_address=parameter_address+640
    secondary_address=native_address+32
    secondary_clips=[pointers[ClipSource(101,i)] for i in (*range(352,357),363)]
    data.extend(struct.pack('<8I',0x54414E31,parameter_address,640,camera_address,384,secondary_address,6,0))
    data.extend(struct.pack('<6I',*secondary_clips));data.extend(bytes(8))
    data.extend(native_approach['parameters']);data.extend(native_approach['camera'])
    struct.pack_into('<I',data,approach_address-clip_base+12,native_address)
    approach_info=dict(table_address=approach_address,donor_model=donor_models[101],
                       clips=approach_clips,native_address=native_address,parameter_address=parameter_address,
                       camera_address=camera_address,secondary_address=secondary_address,reviewed=True)
    data.extend(bytes((-len(data)) % 16))
    staging_address = clip_base + len(data)
    staging = read_native_staging(iso)
    for name,phases in variants.items():
        placements=(((0.,0.,0.,0.),)*len(phases) if name==special.NAME else
                    staging[:4]+((0.,0.,0.,0.),)*(len(phases)-4))
        for placement in placements:
            data.extend(struct.pack('<4f', *placement))
    import tag_rush_choreography as choreography
    data.extend(bytes((-len(data)) % 16))
    choreography_data,choreography_info=choreography.pack_records(variants,clip_base+len(data))
    data.extend(choreography_data)
    beam_info = None
    special_beam_info, special_beam_blocks = None, []
    if include_beam:
        beam = read_native_beam_asset(iso)
        data.extend(bytes((-len(data)) % 16))
        resource_address = clip_base + len(data)
        data.extend(beam['resource'])
        data.extend(bytes((-len(data)) % 16))
        metadata_address = clip_base + len(data)
        data.extend(beam['metadata'])
        beam_info = dict(resource_address=resource_address, metadata_address=metadata_address,
            resource_size=len(beam['resource']), metadata_size=len(beam['metadata']),
            **{key: beam[key] for key in ('descriptor_counts','descriptor_raw_bytes','resource_sha256','mutable_ranges','reviewed')})
        import tag_rush_special_beam as special_beam
        special_beam_pack=special_beam.build_assets(iso)
        special_beam_info={key:value for key,value in special_beam_pack.items() if key!='blocks'}
        special_beam_blocks=special_beam_pack['blocks']
        beam_info['special_beam']=special_beam_info
    camera_info = None
    if include_camera:
        import tag_rush_shots as shots
        from native_map import ACTOR_HZ
        data.extend(bytes((-len(data)) % 16))
        samples,camera_info=shots.build_samples(iso,clip_base+len(data),ACTOR_HZ)
        data.extend(samples)
    if clip_base + len(data) > end:
        raise TagRushAssetError('Tag rush animations exceed their reserved storage')
    descriptors, mapping = bytearray(), {}
    for name, phases in variants.items():
        start = base + len(descriptors)
        phase_rows = []
        for phase_index,phase in enumerate(phases):
            addr = base + len(descriptors)
            words = (phase.source_frames, *(pointers.get(role, 0) for role in phase.roles),
                *phase.starts, phase.flags, *(role.animation if role else 0 for role in phase.roles),
                *phase.ends, SOURCE_FPS, special_donors if name==special.NAME else
                custom_donors if phase.flags&CUSTOM_FINISHER else role_donors)
            descriptors.extend(struct.pack('<16I', *words))
            audio = tuple(dict(cue, role=role) for role, source in enumerate(phase.roles)
                for cue in source_audio.get(source, ())
                if phase.starts[role] <= cue['frame'] <= phase.ends[role])
            contacts=choreography.phase_contacts(name,phase_index)
            if contacts:
                audio=tuple(dict(frame=frame,role=role,bank=0,sound_id=73,bone=3,
                    near=200.,far=1500.,alternate_sound_id=None,parameter_flag=0,
                    effect_kind=16,impact_bone=31 if i%2==0 else 11) for i,(role,frame) in enumerate(contacts))
            phase_rows.append(dict(name=phase.name, address=addr, source_frames=phase.source_frames,
                clips=tuple(pointers.get(role, 0) for role in phase.roles), starts=phase.starts,
                ends=phase.ends, flags=phase.flags, audio_cues=audio))
        mapping[name] = dict(address=start, count=len(phases), phases=phase_rows,
            source_frames=sum(phase.source_frames for phase in phases))
    return dict(blocks=[(base, bytes(descriptors)), (clip_base, bytes(data)),*special_pack['blocks'],*special_beam_blocks], variants=mapping,
        clips=provenance, donor_models=donor_models, role_donors_address=role_donors, beam_asset=beam_info,
        camera_asset=camera_info,choreography_asset=choreography_info,special_beam_asset=special_beam_info,
        approach=approach_info,
        custom_role_donors_address=custom_donors,
        special_role_donors_address=special_donors,
        special_pair=dict(bytes_used=special_pack['bytes_used'],reviewed=True,donor_model=special_pack['donor_model']),
        staging_address=staging_address, staging=staging,
        staging_height=max(-row[1] for row in staging),
        audio_cues={name:tuple(phase['audio_cues'] for phase in row['phases']) for name,row in mapping.items()},
        source_fps=SOURCE_FPS, bytes_used=clip_base + len(data) - base,
        limitations=('Pose assets only; camera and native beam/impact effects are director responsibilities.',))
