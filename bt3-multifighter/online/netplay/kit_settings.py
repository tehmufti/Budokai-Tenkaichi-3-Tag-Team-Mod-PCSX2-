"""Online settings of kit 2.0: which Tag Team Mod setting is whose, the kit's own online profile, and each PC's own
display settings patched into its own copy of the match.

Every key of the mod's mod_settings.DEFAULTS has exactly one class (test_settings fails for a key without one):
  gameplay  changes the simulation for everybody (AI, damage, timing, movement, lock-on rules, cinematics, beam
            struggles, revival, giants, outnumbered...): the HOST's value, compiled into the match both PCs load
  service   a frame-scheduled host service decides it (CPU transformations, timed fusion, Body Change): the lobby's
            service switches set it, and a service that is not available online yet keeps its safe value
  local     display only, proven not to touch any hashed state or random draw (p60 research: the HUD update root
            218D88 draws MT#3 and always runs; the display filters and every HUD node draw callback never draw): every
            PC keeps its OWN value, written as one word into its own copy of the match (LOCAL below)
  forced    one value online for everybody (diagnostics off, no expanded maps / widescreen / extra intros, camera
            zoom 100 %, CPU transformation exceptions off, the host's language for in-game text)
  na        menus, launcher, character select, split screen, training: never reached online; the mod's default
The online values live in the kit's OWN profile (data/profile.json), never in the installation's mod-settings.json:
  * a host's rule changes in the lobby are saved there and are the next online match's defaults (rules only: never
    the fighters or the stage);
  * a guest never saves the host's rules: they are the match's, for that match only;
  * the host's private installation copy gets a COMPLETE settings file for each match (every key set explicitly), so
    nothing from the host's offline mod-settings.json reaches an online match, and nothing online reaches it.
"""
import copy
import json
import math
import struct

import kit_paths  # noqa: F401  (modtools on sys.path)
import mod_settings

GAMEPLAY = (
    # Controls (one rule for every player: the lock-on gestures are compiled into the shared code)
    'lockon_switch_button', 'lockon_hold_seconds', 'lockoff_enabled', 'lockoff_button', 'lockoff_hold_seconds',
    'lockon_right_stick', 'lockon_right_stick_mode', 'lockon_cycle_order', 'lockon_attacker_switch', 'lockon_after_ko',
    # who is coming at you (a warning changes when a player can act: one rule for everybody)
    'lockon_threat_marks',
    # Movement
    'ground_motion_style', 'fusion_enabled', 'tournament_ring_outs',
    'ground_running', 'ground_walk_tilt_percent', 'ground_walk_speed_percent', 'ground_run_speed_percent',
    'ground_size_speed',
    # Cinematics
    'special_pause_mode', 'ultimate_cinematics', 'transformation_cinematics', 'transformation_split_view',
    'rush_cinematics', 'prevent_cinematic_recentering', 'battle_camera_distance_percent',
    # Fusion (the timer itself is a service)
    'fusion_duration_seconds', 'fusion_defusion_animation',
    # Fighters
    'extra_character_voices',
    # Giants
    'canonical_giants', 'giant_size_multiplier', 'giant_attack_speed_percent', 'giant_damage_percent',
    'giant_armor_levels', 'giant_camera_distance_percent',
    # Spectating
    'spectator_takeover_enabled', 'spectate_fallen_fighters',
    # Revival
    'keep_fallen_fighters_in_bounds', 'revive_enabled', 'revive_stock_cost', 'revive_channel_seconds', 'revive_radius',
    'revive_health_bars', 'revive_recovery_seconds',
    # Outnumbered
    'outnumbered_preset', 'outnumbered_scope', 'outnumbered_applies_to', 'outnumbered_damage_bonus_percent',
    'outnumbered_damage_reduction_percent', 'outnumbered_recovery_speed_percent',
    'outnumbered_getup_protection_seconds', 'outnumbered_combo_breaker_hits',
    # Beam struggles
    'beam_clash_camera', 'beam_struggle_length', 'beam_struggle_push_ahead', 'beam_struggle_cpu_power_percent',
    'beam_struggle_interference', 'beam_struggle_damage_penalty_percent', 'beam_assist_enabled',
    'beam_assist_multiplier_percent', 'beam_assist_cpu', 'beam_assist_range',
)
# service name -> {key: value when the service is ON, value when it is OFF}
SERVICES = {
    'cpu_transform': {'disable_npc_transformations': (False, True), 'disable_npc_giant_transformations': (False, True)},
    'fusion_timer': {'fusion_duration_enabled': (True, False)},
    'body_change': {'true_body_change': (True, False), 'ginyu_stolen_abilities': (True, False)},
}
# The gameplay keys that decide what a player SEES or WHEN a player can act (cameras, cinematics, shared stops, zoom,
# attack warnings): the host's for everybody like every gameplay rule; the lobby names them "Camera rules: set by the
# host". A player who kept a clash camera another lacks could act while the other cannot see (kit 2.0 fairness rule).
CAMERA = ('special_pause_mode', 'ultimate_cinematics', 'transformation_cinematics', 'transformation_split_view',
          'rush_cinematics', 'prevent_cinematic_recentering', 'battle_camera_distance_percent',
          'giant_camera_distance_percent', 'beam_clash_camera', 'lockon_threat_marks')
# Only purely cosmetic things stay per PC (LOCAL below): HUD visibility, the target indicator's style, takeover hints,
# the revive ring's look - plus the emulator's resolution and renderer.
SERVICE_KEYS = {k: name for name, keys in SERVICES.items() for k in keys}
FORCED = {'expanded_maps': False, 'widescreen_patch': False, 'extra_character_intros': False,
          'keep_preparation_diagnostics': False, 'capture_freeze_dumps': False,
          'record_battle_diagnostics': False, 'npc_transform_overrides': {}, 'npc_transform_chance_percent': 100}
FORCED_LANGUAGE = 'language'                 # the host's lobby language (text is baked into several code pages)
NOT_APPLICABLE = (
    'version', 'native_mode_menu_enabled', 'menu_toggle_button', 'show_menu_toggle_hint',
    'loading_animation_speed_percent', 'coop_independent_selection', 'all_controllers_character_select',
    'show_player_slot_labels', 'controller_checkin', 'keep_controller_checkins', 'coop_fusion_controls',
    'show_fusion_control_owner', 'show_fusion_control_countdown', 'show_fusion_timer', 'split_hud_style',
    'split_hud_scale_percent', 'split_hud_layout', 'split_hud_filter', 'coop_hud_layout', 'show_hud_portraits',
    'show_hud_sparking_effects', 'hud_damage_trail_seconds', 'training_cpu_behavior', 'training_refill_health',
    'training_health_delay_seconds', 'training_refill_ki', 'training_refill_stocks', 'fast_disc_loading',
    'emulated_cpu_speed',
)
# Online values of not-applicable keys (none differ from the mod's defaults: the default controller check-in,
# 'connection_order', never arms the hub's P1/P2 override; the conversion disarms that override anyway).
NA_VALUES = {}


class Patch:
    """One display word of a match: `address`, the owning module's CONTROL / MAGIC (the word is patched only when that
    module is installed and, with `require`, when the build left the feature on), and the encoder."""

    def __init__(self, address, control, magic, encode, require=None, kind='u32'):
        self.address, self.control, self.magic, self.encode, self.require, self.kind = \
            address, control, magic, encode, require, kind

    def data(self, value):
        v = self.encode(value)
        return struct.pack('<f', float(v)) if self.kind == 'f32' else struct.pack('<I', int(v) & 0xFFFFFFFF)


def _bool(v):
    return 1 if v else 0


def _ticks(v):
    return math.ceil(float(v) * 30)                            # ACTOR_HZ (USA)


DISPLAY, DISPLAY_MAGIC = 0x07277000, 0x44535031                # display_settings CONTROL ('DSP1')
LOCKOFF, LOCKOFF_MAGIC = 0x06946000, 0x4C4F4631                # lockoff_target CONTROL ('LOF1')
LOCKON, LOCKON_MAGIC = 0x06957000, 0x4C4B5331                  # lockon_select CONTROL ('LKS1')
FEEDBACK, FEEDBACK_MAGIC = 0x0728D000, 0x53504632              # spectator_feedback CONTROL + its CONFIG magic
REVIVE, REVIVE_MAGIC = 0x070BF000, 0x52565631                  # teammate_revive CONTROL ('RVV1')
LOCAL = {
    'show_friendly_healthbars': Patch(DISPLAY + 0x08, DISPLAY, DISPLAY_MAGIC, _bool),
    'show_enemy_healthbars': Patch(DISPLAY + 0x0C, DISPLAY, DISPLAY_MAGIC, _bool),
    'show_native_hud': Patch(DISPLAY + 0x10, DISPLAY, DISPLAY_MAGIC, _bool),
    'show_kill_feed': Patch(DISPLAY + 0x14, DISPLAY, DISPLAY_MAGIC, _bool),
    'show_kill_score': Patch(DISPLAY + 0x18, DISPLAY, DISPLAY_MAGIC, _bool),
    'lockoff_target_hud': Patch(LOCKOFF + 0x10, LOCKOFF, LOCKOFF_MAGIC,
                                lambda v: {'single_enemy': 0, 'hide': 1, 'show': 2}[v]),
    # the marker can be switched off per PC (only on when the match was built with it: it always is online)
    'lockon_target_marker': Patch(LOCKON + 0x18, LOCKON, LOCKON_MAGIC, _bool, require=(LOCKON + 0x18, 1)),
    'lockon_target_style': Patch(LOCKON + 0xB4, LOCKON, LOCKON_MAGIC, lambda v: {'arrow': 1, 'ring': 2, 'both': 3}[v],
                                 require=(LOCKON + 0x18, 1)),
    'takeover_hint_seconds': Patch(FEEDBACK + 0x30, FEEDBACK + 0x40, FEEDBACK_MAGIC, _ticks),
    'takeover_confirmation_seconds': Patch(FEEDBACK + 0x34, FEEDBACK + 0x40, FEEDBACK_MAGIC, _ticks),
    'show_takeover_hints': Patch(FEEDBACK + 0x38, FEEDBACK + 0x40, FEEDBACK_MAGIC, _bool),
    'show_takeover_confirmation': Patch(FEEDBACK + 0x3C, FEEDBACK + 0x40, FEEDBACK_MAGIC, _bool),
    'show_revive_ring': Patch(REVIVE + 0x50, REVIVE, REVIVE_MAGIC, _bool),
    'revive_ring_opacity': Patch(REVIVE + 0x54, REVIVE, REVIVE_MAGIC, lambda v: round(float(v) * 128)),
    'revive_ring_wave_height': Patch(REVIVE + 0x58, REVIVE, REVIVE_MAGIC, float, kind='f32'),
    'revive_ring_wave_speed': Patch(REVIVE + 0x5C, REVIVE, REVIVE_MAGIC, lambda v: round(float(v) * 65536 / 30)),
}
# The values the host's copy BUILDS the match with for the local keys: the most capable build (every display feature
# installed), so that every PC can switch each one off (or keep it) in its own copy.
BUILD_LOCAL = {'show_friendly_healthbars': True, 'show_enemy_healthbars': True, 'show_native_hud': True,
               'show_kill_feed': True, 'show_kill_score': True, 'lockoff_target_hud': 'show',
               'lockon_target_marker': True, 'lockon_target_style': 'both',
               'show_takeover_hints': True, 'show_takeover_confirmation': True, 'show_revive_ring': True}


def classes():
    """{key: class} for every key this kit knows (the order of the module text)."""
    out = {k: 'gameplay' for k in GAMEPLAY}
    out.update({k: 'service' for k in SERVICE_KEYS})
    out.update({k: 'local' for k in LOCAL})
    out.update({k: 'forced' for k in FORCED})
    out[FORCED_LANGUAGE] = 'forced'
    out.update({k: 'na' for k in NOT_APPLICABLE})
    return out


CLASS = classes()
assert len(CLASS) == len(GAMEPLAY) + len(SERVICE_KEYS) + len(LOCAL) + len(FORCED) + 1 + len(NOT_APPLICABLE), \
    'a key has two classes'


def unclassified(defaults=None):
    """The mod's settings keys that have no class here (test_settings: must be empty)."""
    return sorted(k for k in (defaults or mod_settings.DEFAULTS) if k not in CLASS)


# ---- values ----------------------------------------------------------------------------------------------------------
FIELDS = mod_settings.ui_fields()


def default_gameplay():
    return {k: copy.deepcopy(mod_settings.DEFAULTS[k]) for k in GAMEPLAY if k in mod_settings.DEFAULTS}


def default_local():
    return {k: copy.deepcopy(mod_settings.DEFAULTS[k]) for k in LOCAL if k in mod_settings.DEFAULTS}


def _same(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b)
    return a == b


def gameplay_diff(values):
    """The gameplay values that differ from the mod's defaults (what a LOBBY snapshot carries)."""
    base = default_gameplay()
    return {k: values[k] for k in base if k in values and not _same(values[k], base[k])}


def gameplay_expand(delta):
    out = default_gameplay()
    out.update({k: v for k, v in (delta or {}).items() if k in out})
    return out


def coerce(key, value):
    """A value typed in the lobby (text or number) as the setting's own type; ValueError when impossible."""
    default, kind, low, high = FIELDS[key][:4]
    if kind == 'bool':
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ('1', 'on', 'true', 'yes', 'si', 'sí'):
            return True
        if text in ('0', 'off', 'false', 'no'):
            return False
        raise ValueError(f'{key}: on or off')
    if kind in ('choice', 'button'):
        text = str(value).strip().lower()
        if text not in low:
            raise ValueError(f'{key}: one of {", ".join(low)}')
        return text
    number = float(value)
    if kind == 'int':
        if number != int(number):
            raise ValueError(f'{key}: a whole number')
        number = int(number)
    if not (low <= number <= high):
        raise ValueError(f'{key}: from {low} to {high}')
    return number


def services_values(services):
    out = {}
    for name, keys in SERVICES.items():
        on = bool((services or {}).get(name))
        for key, (yes, no) in keys.items():
            out[key] = yes if on else no
    return out


def match_settings(gameplay, services, language):
    """The COMPLETE mod-settings.json the host's private copy builds a match with: the mod's defaults, then the
    online gameplay values, the service switches, the most capable display build, the forced values and the
    language. Every key is set, so the copy's own (the host's offline) values never reach the match."""
    out = copy.deepcopy(mod_settings.DEFAULTS)
    out.update(copy.deepcopy(NA_VALUES))
    out.update(gameplay_expand(gameplay))
    out.update(services_values(services))
    out.update(copy.deepcopy(BUILD_LOCAL))
    out.update(copy.deepcopy(FORCED))
    if language:
        out[FORCED_LANGUAGE] = language
    return out


def gameplay_problems(values):
    """[text] for a host's gameplay values (empty: playable)."""
    if not isinstance(values, dict):
        return ['the rules are not a list of settings']
    unknown = sorted(k for k in values if k not in GAMEPLAY)
    if unknown:
        return [f'settings that are not online rules: {", ".join(unknown[:5])}']
    merged = match_settings(values, {}, None)
    try:
        checked = mod_settings.validate_settings(merged)
    except ValueError as error:
        return [str(error)]
    changed = [k for k in values if not _same(checked.get(k), values[k])]
    return [f'{", ".join(changed[:5])} are not consistent (the mod would change them)'] if changed else []


def normalised_gameplay(values):
    """The gameplay values as the mod reads them; key by key when the whole set does not validate (a value that cannot
    be used falls back to the default)."""
    given = {k: v for k, v in (values or {}).items() if k in GAMEPLAY}
    if not gameplay_problems(given):
        return gameplay_expand(given)
    out = {}
    for k, v in given.items():
        trial = dict(out, **{k: v})
        if not gameplay_problems(trial):
            out = trial
    return gameplay_expand(out)


def local_problems(values):
    out = []
    for k, v in (values or {}).items():
        if k not in LOCAL:
            out.append(f'{k} is not a display setting')
            continue
        try:
            LOCAL[k].data(coerce(k, v) if k in FIELDS else v)
        except (KeyError, TypeError, ValueError) as error:
            out.append(f'{k}: {error}')
    return out


def local_blocks(read_u32, values):
    """[(address, bytes)] writing this PC's own display values into its copy of a match. read_u32(address) reads the
    match's RAM; a word is written only when its module is installed (its magic) and, for the marker, when the build
    left it on. Values that equal what the match holds give no block."""
    out = []
    merged = default_local()
    merged.update({k: v for k, v in (values or {}).items() if k in LOCAL})
    marker_off = not merged.get('lockon_target_marker', True)
    for key, patch in LOCAL.items():
        if key not in merged:
            continue
        try:
            if read_u32(patch.control) != patch.magic:
                continue
            if patch.require and read_u32(patch.require[0]) != patch.require[1]:
                continue
        except (IndexError, ValueError, OSError):
            continue
        value = merged[key]
        data = struct.pack('<I', 0) if key == 'lockon_target_style' and marker_off else patch.data(value)
        if read_u32(patch.address) != struct.unpack('<I', data)[0]:
            out.append((patch.address, data))
    return out


# ---- the kit's own online profile ---------------------------------------------------------------------------------------
PROFILE_VERSION = 1


def profile_path():
    return kit_paths.DATA / 'profile.json'


def default_profile():
    import kit_spec
    return dict(v=PROFILE_VERSION, name='', rules=dict(native=dict(kit_spec.DEFAULT_NATIVE), gameplay={},
                                                       services={}, bgm=kit_spec.DEFAULT_BGM,
                                                       mode='teams'),
                local={})


def load_profile(path=None):
    """The online profile (a missing or broken file gives the defaults; unknown or invalid values are dropped)."""
    import kit_spec
    out = default_profile()
    try:
        data = json.loads((path or profile_path()).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return out
    if not isinstance(data, dict):
        return out
    if isinstance(data.get('name'), str):
        out['name'] = clean_name(data['name'])
    rules = data.get('rules') if isinstance(data.get('rules'), dict) else {}
    native = dict(out['rules']['native'])
    native.update({k: v for k, v in (rules.get('native') or {}).items() if k in native})
    if not kit_spec.native_problems(native):
        out['rules']['native'] = native
    gameplay = rules.get('gameplay') if isinstance(rules.get('gameplay'), dict) else {}
    out['rules']['gameplay'] = gameplay_diff(normalised_gameplay(gameplay))
    services = rules.get('services') if isinstance(rules.get('services'), dict) else {}
    out['rules']['services'] = {k: bool(v) for k, v in services.items() if k in SERVICES}
    if kit_spec.bgm_ok(rules.get('bgm')):
        out['rules']['bgm'] = rules['bgm']
    if rules.get('mode') in kit_spec.MODES:
        out['rules']['mode'] = rules['mode']
    local = data.get('local') if isinstance(data.get('local'), dict) else {}
    out['local'] = {k: v for k, v in local.items() if k in LOCAL and not local_problems({k: v})}
    return out


def save_profile(profile, path=None):
    path = path or profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(profile, indent=1, sort_keys=True), encoding='utf-8')
    tmp.replace(path)


NAME_MAX = 16


def clean_name(text):
    """A player name as the lobby shows it: printable, trimmed, at most 16 characters (empty: no name chosen)."""
    text = ''.join(ch for ch in str(text) if ch == ' ' or ch.isprintable()).strip()
    return ' '.join(text.split())[:NAME_MAX]


# ---- what the lobby shows (labels in both languages from the mod's own localization) -----------------------------------
def groups():
    """[(group, [gameplay keys])] in the mod's settings-page order."""
    out = []
    for group, keys in mod_settings.GROUPS:
        mine = [k for k in keys if k in GAMEPLAY and k in FIELDS]
        if mine:
            out.append((group, mine))
    return out


def local_groups():
    out = []
    for group, keys in mod_settings.GROUPS:
        mine = [k for k in keys if k in LOCAL and k in FIELDS]
        if mine:
            out.append((group, mine))
    return out


def label(key, lang):
    import localization
    return localization.tr(FIELDS[key][5], lang)


def group_label(group, lang):
    import localization
    return localization.tr(group, lang)


def value_text(key, value, lang):
    import localization
    kind = FIELDS[key][1]
    if kind in ('int', 'float'):
        return f'{value:g}' if isinstance(value, float) else str(value)
    return localization.value_label(value, lang)


def choices(key):
    default, kind, low, high = FIELDS[key][:4]
    if kind in ('choice', 'button'):
        return kind, tuple(low)
    if kind == 'bool':
        return kind, (True, False)
    return kind, (low, high)
