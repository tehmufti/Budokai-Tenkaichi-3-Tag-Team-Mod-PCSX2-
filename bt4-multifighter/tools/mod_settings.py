"""Persist user preferences without modifying an emulator or a checkpoint.

Only this module's owned fields are interpreted. Other JSON settings survive
edits so later options can share the same versioned document.
"""
import argparse
import localization
from localization import tr, value_label
import copy
import json
import math
import os
import sys
from pathlib import Path

import atomic_files
import input_binding
import feature_preferences

ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = ROOT / 'mod-settings.json'
# Written once by the player installer (player-defaults.json, validated, without
# language). Restore defaults uses it (defaults_path); a developer tree has none.
DEFAULTS_PATH = ROOT / 'mod-settings-defaults.json'
# The installer's source of those defaults. A developer tree (no player-install.json) has no installer copy, so it
# reads this file in place: its Play, Mod settings and Restore defaults then use what a new installation writes.
# Only the code DEFAULTS below stay legacy-leaning: tests, goldens and the legacy property build from them.
SHIPPED_DEFAULTS = ROOT.parent / 'player-installer' / 'player-defaults.json'
# Adapter facts. The BT4 port differs only here: 'BT4' and range(250).
ADAPTER = 'BT4'
NPC_OVERRIDE_IDS = range(250)
VERSION = 2
LANGUAGE_KEY = 'language'
PAUSE_KEY = 'pause_other_fighters_during_specials'
MODE_KEY = 'special_pause_mode'
MODES = ('all', 'target', 'none')
ULTIMATE_KEY = 'ultimate_cinematics'
TRANSFORMATION_KEY = 'transformation_cinematics'
# How a checked transformation presents itself on a split screen. 'shared'
# matches the ultimate: one authored view for both halves, every uninvolved
# fighter held for its whole close-up. 'each_half' keeps the two viewports
# and has each of them frame the close-up instead.
TRANSFORM_VIEW_KEY = 'transformation_split_view'
TRANSFORM_VIEWS = ('shared','each_half')
COOP_FUSION_KEY = 'coop_fusion_controls'
FUSION_MODES = ('swap_20s', 'split_controls', 'player1')
LOCKON_KEY = 'lockon_switch_button'
LOCKON_HOLD_KEY = 'lockon_hold_seconds'
LOCKON_BUTTONS = input_binding.BUTTONS
LOCKON_MASKS = input_binding.MASKS
# Captain Ginyu's true Body Change: exchange bodies with the fighter he actually
# hits (stock BT3 picks a random Namek-era body). Opt in for playtesting; off leaves the
# dormant guest program out of new preparations so stock behaviour remains.
TRUE_BODY_KEY = 'true_body_change'
FRIEND_BARS_KEY = 'show_friendly_healthbars'
ENEMY_BARS_KEY = 'show_enemy_healthbars'
NATIVE_HUD_KEY = 'show_native_hud'
KILL_FEED_KEY = 'show_kill_feed'
KILL_SCORE_KEY = 'show_kill_score'
NPC_TRANSFORM_KEY = 'disable_npc_transformations'
NPC_GIANT_KEY = 'disable_npc_giant_transformations'
NPC_OVERRIDES_KEY = 'npc_transform_overrides'
CORPSE_SAFETY_KEY = 'keep_fallen_fighters_in_bounds'
REVIVE_KEY = 'revive_enabled'
REVIVE_COST_KEY = 'revive_stock_cost'
REVIVE_CHANNEL_KEY = 'revive_channel_seconds'
# Every key of the Revival page, in display order.
REVIVE_KEYS = (REVIVE_KEY, REVIVE_COST_KEY, REVIVE_CHANNEL_KEY, 'revive_radius', 'revive_health_bars',
               'revive_recovery_seconds', CORPSE_SAFETY_KEY, 'show_revive_ring', 'revive_ring_opacity',
               'revive_ring_wave_height', 'revive_ring_wave_speed')
# Every key of the Outnumbered page (outnumbered.py SETTING_KEYS), in display order.
OUTNUMBERED_KEYS = ('outnumbered_preset', 'outnumbered_scope', 'outnumbered_applies_to',
                    'outnumbered_damage_bonus_percent', 'outnumbered_damage_reduction_percent',
                    'outnumbered_recovery_speed_percent', 'outnumbered_getup_protection_seconds',
                    'outnumbered_combo_breaker_hits')
# beta.37's tag attacks were removed in beta.38: their saved keys are dropped on load.
RETIRED_TAG_KEYS = ('tag_attacks_enabled', 'tag_attack_button', 'tag_attack_helpers', 'tag_attack_cost',
                    'tag_super_enabled', 'tag_super_cost', 'tag_attack_cooldown_seconds')
DISPLAY_KEYS = (FRIEND_BARS_KEY, ENEMY_BARS_KEY, NATIVE_HUD_KEY, KILL_FEED_KEY, KILL_SCORE_KEY)
# Every key of the Beam struggles page (beam_struggle.py), in display order.
BEAM_KEYS = ('beam_clash_camera', 'beam_struggle_length', 'beam_struggle_push_ahead', 'beam_struggle_cpu_power_percent',
             'beam_struggle_interference', 'beam_struggle_damage_penalty_percent',
             'beam_assist_enabled', 'beam_assist_multiplier_percent', 'beam_assist_cpu', 'beam_assist_range')
# Every key of the Movement page (ground_locomotion.py), in display order.
MOVEMENT_KEYS = ('ground_running', 'ground_walk_tilt_percent', 'ground_walk_speed_percent', 'ground_run_speed_percent',
                 'ground_size_speed')
DEFAULTS = {'version': VERSION, MODE_KEY: 'all', ULTIMATE_KEY: False,
            TRANSFORMATION_KEY: False, TRANSFORM_VIEW_KEY: 'shared',
            COOP_FUSION_KEY: 'swap_20s', LOCKON_KEY: 'r3', LOCKON_HOLD_KEY: 0.5,
            TRUE_BODY_KEY: False, FRIEND_BARS_KEY: True, ENEMY_BARS_KEY: True,
            NATIVE_HUD_KEY: True, KILL_FEED_KEY: True, KILL_SCORE_KEY: False, NPC_TRANSFORM_KEY: False, NPC_GIANT_KEY: False,
            NPC_OVERRIDES_KEY: {}, CORPSE_SAFETY_KEY: True,
            REVIVE_KEY: False, REVIVE_COST_KEY: 4, REVIVE_CHANNEL_KEY: 4.0}
DEFAULTS.update(feature_preferences.DEFAULTS)

# Settings pages, in order: (English group name, keys in display order). Every
# editable key belongs to exactly one page. Keep 'Menus' first and the names
# 'Menus' and 'Controls': the player README/LEEME cite those paths.
GROUPS = (
    ('Menus', (LANGUAGE_KEY, 'native_mode_menu_enabled', 'menu_toggle_button', 'show_menu_toggle_hint',
               'loading_animation_speed_percent')),
    ('Players and controllers', ('coop_independent_selection', 'all_controllers_character_select',
                                 'show_player_slot_labels', 'controller_checkin', 'keep_controller_checkins')),
    ('Controls', (LOCKON_KEY, LOCKON_HOLD_KEY, 'lockoff_enabled', 'lockoff_button', 'lockoff_hold_seconds',
                  'lockon_right_stick', 'lockon_right_stick_mode', 'lockon_cycle_order', 'lockon_attacker_switch',
                  'lockon_after_ko')),
    ('Movement', MOVEMENT_KEYS),
    ('Cinematics', (MODE_KEY, ULTIMATE_KEY, TRANSFORMATION_KEY, TRANSFORM_VIEW_KEY, 'rush_cinematics',
                    'prevent_cinematic_recentering', 'extra_character_intros', 'battle_camera_distance_percent')),
    ('Fusion', (COOP_FUSION_KEY, 'show_fusion_control_owner', 'show_fusion_control_countdown',
                'fusion_duration_enabled', 'fusion_duration_seconds', 'show_fusion_timer',
                'fusion_defusion_animation')),
    ('Fighters', (TRUE_BODY_KEY, 'ginyu_stolen_abilities', 'extra_character_voices', NPC_TRANSFORM_KEY,
                  NPC_GIANT_KEY, 'npc_transform_chance_percent')),
    ('Giants', ('canonical_giants', 'giant_size_multiplier', 'giant_attack_speed_percent', 'giant_damage_percent',
                'giant_armor_levels', 'giant_camera_distance_percent')),
    ('HUD', (*DISPLAY_KEYS, 'lockoff_target_hud', 'lockon_target_marker', 'lockon_target_style',
            'lockon_threat_marks')),
    ('Split-screen HUD', ('split_hud_style', 'split_hud_scale_percent', 'split_hud_layout', 'split_hud_filter',
                          'coop_hud_layout', 'show_hud_portraits', 'show_hud_sparking_effects',
                          'hud_damage_trail_seconds')),
    ('Spectating', ('spectator_takeover_enabled', 'spectate_fallen_fighters', 'show_takeover_hints',
                    'show_takeover_confirmation', 'takeover_hint_seconds', 'takeover_confirmation_seconds')),
    ('Revival', REVIVE_KEYS),
    ('Outnumbered', OUTNUMBERED_KEYS),
    ('Beam struggles', BEAM_KEYS),
    ('Training', ('training_cpu_behavior', 'training_refill_health', 'training_health_delay_seconds',
                  'training_refill_ki', 'training_refill_stocks')),
    ('Launch options (restart)', ('widescreen_patch', 'fast_disc_loading', 'emulated_cpu_speed', 'expanded_maps')),
    ('Diagnostics', ('keep_preparation_diagnostics', 'capture_freeze_dumps', 'record_battle_diagnostics')),
)
# The page that also offers the per-character CPU transformation exceptions.
EXCEPTIONS_GROUP = 'Fighters'
# Pages only the desktop window has, after GROUPS: 'Game disc' chooses the ISO Play starts (disc_page.py). The
# in-game settings screens (ui_groups) never show them.
DESKTOP_PAGES = ('Game disc',)
# Turning these on is checked first (can_enable).
CHECKED_ENABLES = ('expanded_maps',)
WINDOW_TITLE = '{adapter} mod settings'
# Desktop only. Its labels are built once, so a newly saved language shows when reopened.
HEADER = ('Choose a category. Saved changes apply to the next match unless its page says otherwise. '
          'This window shows a newly saved language when you reopen it.')
# One help note per page (desktop page footer and in-game help). Keep this a
# pure literal: test_localization reads it with ast.literal_eval.
notes = {
    'Menus': 'Press the menu switch button on the original main menu to open or close the mod menus; its hint can be hidden. With mod mode menus off, only Mod settings.cmd can turn them back on. Menu settings saved in game apply when you leave Mod Settings; saved in Mod settings.cmd, after restarting Play. Language also changes match text from the next match. Loading speed applies from the next loading screen.',
    'Players and controllers': 'Check-in: on Player Setup each player presses START on their own controller to join; a light flashes with each press and SELECT leaves the seat. With 3 or 4 players everyone joins before Continue; with 2, PCSX2 keeps its order unless someone presses START (or check-in is set for 2 to 4 players). Optional keeps the connection order, and anyone may still check in. A keyboard joins as player 1 or 2 through PCSX2. Kept check-ins fill the seats again until Play closes. With own fighters on, each human picks their assigned slots; otherwise Player 1 picks. Allowing all controllers lets any controller move the cursor. Player numbers mark whose slot is whose. Saved in game, these apply when you leave Mod Settings; saved in Mod settings.cmd, after restarting Play.',
    'Controls': 'Tap the switch button: next enemy in the set order; during an attack warning, your attacker (or automatically when hit, if set). Right stick, with the button held (not R3) or alone if set (locked on in combat; no camera then): left/right steps around you, up/down picks above/below. Hold the button to lock off; tap to relock. R3 transforms. Rebind in Mod settings.cmd. Applies next match; Fight Again keeps it.',
    'Movement': 'On the ground, fighters walk or run instead of gliding just above it; dashes, jumps and flight stay as they are. Tilt the left stick past the set amount to run, less to walk; CPU fighters always run. Speeds are percentages of a natural run. With size on, small fighters run slower and giants faster; feet stay planted. Applies from the next match; a Fight Again rematch keeps the settings of its match.',
    'Cinematics': 'Special-move pause chooses who stops. Shared cameras pause everyone outside the scene for one view; off keeps separate views (paired attacks still hold their fighters). Split-screen transformations use one view or each half. Extra intros can be skipped. Zoom-out above 100% pulls the camera back. Kept in place, attacks and transformations play where they start, not at the arena centre. Applies next match; Fight Again keeps it.',
    'Fusion': 'When two humans share a fusion, swap passes control every 20 s, split gives P1 attacks and P2 movement, or Player 1 controls it. The control message and countdown show in swap mode only. The time limit covers Fusion Dance fusions made in the match, not Potara or preselected ones; its timer and power-down animation are optional. Applies from the next match; a Fight Again rematch keeps the settings of its match.',
    'Fighters': 'Ginyu can exchange bodies with the opponent he actually hits; stolen-body abilities are optional. Extra voices borrow idle native voice streams. The CPU switches and chance limit native CPU transformations; per-character exceptions override them. Humans, fusion and Body Change are unaffected. Applies from the next match; a Fight Again rematch keeps the settings of its match.',
    'Giants': 'Larger giants scale native giant forms; expanded maps give them room. Size, attack speed, damage, stagger resistance and camera distance apply only while larger giants are on; the Cinematics zoom-out multiplies that distance up to a fixed limit. Applies from the next match; a Fight Again rematch keeps the settings of its match.',
    'HUD': 'Health bars, battle HUD, kill feed, watched fighter kill count, target indicator and attacker arrows are separate switches. Battle HUD off also hides split-screen panels. The indicator is a gold arrow, a ring sized to your target, or both, in every view. Red arrows point at each enemy locked on to you, on the screen edge if off screen; they flash while it attacks. Applies next match; Fight Again keeps it.',
    'Split-screen HUD': 'Native style uses the game frames and meters; portraits and lightning need it. "Same top row" holds both panels (size in %); "Player top, target bottom" puts your target opposite you. Co-op panels show both players or each player and target. Smooth filtering softens textures. The damage trail briefly shows lost health (0 = off). Applies from the next match; a Fight Again rematch keeps the settings of its match.',
    'Spectating': 'A defeated human can watch fighters and take over a living CPU teammate, never an enemy, and not in free-for-all or CPU-only matches. Fallen fighters can be watched for their score. The hint shows the takeover button after its delay; the confirmation names your new fighter. Applies from the next match; a Fight Again rematch keeps the settings of its match.',
    'Revival': 'Stay inside the circle of a fallen teammate for the set time. Moving and taunting keep progress; damage or leaving interrupts. Revival costs blast stocks, not ki, and restores the set health. Get-up protection, corpse safety and ring appearance are adjustable. No revival in free-for-all. Applies from the next match; a Fight Again rematch keeps its settings.',
    'Outnumbered': 'For a fighter on the smaller team or, if chosen, one targeted by two or more enemies. Damage follows the living team sizes: per extra enemy each of you faces, you deal more and take less (at most 300% dealt, at least 40% taken); equal teams and free-for-all keep normal damage. Recovery speed shortens knock-backs, get-ups and hit reactions. Protection: while you get up, ordinary hits neither stagger nor hurt you; Blast 2 attacks, rushes and throws still do. The combo breaker gives 1 s of it, at most every 5 s, never during a rush or throw. Balanced: +15%/-10%, 150%, 0.5 s, 12 hits. Strong: +40%/-30%, 200%, 1 s, 8 hits. Custom uses the rows below; the two rows about who is helped apply to every preset. The "Enemies targeting you" marks are on the HUD page. Applies from the next match; a Fight Again rematch keeps its settings.',
    'Beam struggles': "Clash camera: switch to the struggle, or keep every view on its own player. Long struggles last 2x or 4x; a set input lead wins at once. CPU strength scales CPU inputs. With hits on, enemies can hit both fighters (no grabs) and lost health weakens their push. Near a struggling ally, press R3 (1 blast stock): you fly in beside them and join, adding push and final damage. Up to four per side (x3 at most). Applies next match; Fight Again keeps it.",
    'Training': 'Modded Training takes one to four players; share a team to practice together. The CPU stands still or fights back. Health refills after the delay, and ki and blast stocks refill. With health refill off, defeats can end the session. Native Training stays in the original menu. Applies from the next session; a Fight Again rematch keeps the settings of its session.',
    'Launch options (restart)': 'Applied when Play starts, so restart Play after saving. Widescreen enables the PCSX2 16:9 patch. Fast disc loading shortens loading screens. A faster emulated CPU smooths split screen; PCSX2 setting leaves the rate alone. 2x maps need Build expanded maps.cmd first (seven animated stages stay native); without that build, Play starts the original ISO.',
    'Diagnostics': 'For troubleshooting; these files can be large. Preparation dumps keep intermediate RAM images, freeze snapshots save memory when a match stops responding, and battle history records match events. Applies from the next match; a Fight Again rematch keeps the settings of its match.',
}


def _json_value(value):
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return all(_json_value(item) for item in value)
    if type(value) is dict:
        return all(type(key) is str and _json_value(item) for key, item in value.items())
    return False


def validate_settings(settings, defaults=None):
    """The checked settings. `defaults` (developer_defaults(): the installer's values) fills the editable keys the
    saved file lacks, after the presence-based migrations below; without it the code DEFAULTS fill them."""
    if type(settings) is not dict or not _json_value(settings):
        raise ValueError('Mod settings must be a JSON object with finite JSON values.')
    result = copy.deepcopy(settings)
    # Older saved L3 holds must remain loadable when adding the second gesture.
    # Preserve their switch binding and give the new hold half a second more.
    if ('lockoff_hold_seconds' not in result
            and result.get('lockoff_button','l3')==result.get(LOCKON_KEY,DEFAULTS[LOCKON_KEY])):
        old_hold=result.get(LOCKON_HOLD_KEY,DEFAULTS[LOCKON_HOLD_KEY])
        if type(old_hold) in (int,float) and math.isfinite(old_hold) and 0<=old_hold<3599.5:
            result['lockoff_hold_seconds']=max(.5,old_hold+.5)
    # Cell's cinematic prop is part of the transformation, no longer optional.
    result.pop('cell_absorption_android', None)
    # Retired after the native move failed gameplay validation. Old saved
    # preferences must not silently turn this experiment back on.
    result.pop('buu_ultimate_all_enemies', None)
    result.pop('krillin_scattering_all_enemies', None)
    result.pop('menu_transition_cover', None)
    result.pop('fusion_lore_timers', None)  # Only Fusion Dance fusions are timed.
    # beta.38 removed beam struggle and ultimate splash damage; older saved files may still name its options.
    for key in ('beam_clash_splash', 'ultimate_splash', 'splash_damage_percent', 'splash_radius',
                'splash_friendly_fire'):
        result.pop(key, None)
    for key in RETIRED_TAG_KEYS:
        result.pop(key, None)
    # The pre-layout release enlarged the four panels to120%. Adopt the new
    # requested100% layout once; subsequent explicit sizes remain user choices.
    if 'split_hud_layout' not in result and result.get('split_hud_scale_percent') == 120:
        result['split_hud_scale_percent'] = 100
    # Never the language or the file version; a version-1 file keeps its legacy pause Boolean (no pause mode).
    legacy = PAUSE_KEY in result or result.get('version') == 1
    for key, value in (defaults or {}).items():
        if key in DEFAULTS and key not in ('version', LANGUAGE_KEY) and not (legacy and key == MODE_KEY):
            result.setdefault(key, copy.deepcopy(value))
    feature_preferences.validate_into(result)
    version = result.get('version', 1 if PAUSE_KEY in result else VERSION)
    if type(version) is not int or version not in (1, VERSION):
        raise ValueError(f"Unsupported mod settings version: {version!r}.")
    if version == 1:
        if MODE_KEY in result:
            raise ValueError('Version1 settings cannot also contain the version2 pause mode.')
        previous = result.pop(PAUSE_KEY, True)
        if type(previous) is not bool:
            raise ValueError(f'{PAUSE_KEY} must be true or false.')
        result[MODE_KEY] = 'all' if previous else 'target'
    else:
        if PAUSE_KEY in result:
            raise ValueError('Version2 settings use special_pause_mode, not the legacy Boolean.')
        result.setdefault(MODE_KEY, 'all')
    if type(result[MODE_KEY]) is not str or result[MODE_KEY] not in MODES:
        raise ValueError(f'{MODE_KEY} must be all, target, or none.')
    for key in (ULTIMATE_KEY, TRANSFORMATION_KEY, TRUE_BODY_KEY, NPC_TRANSFORM_KEY, NPC_GIANT_KEY, CORPSE_SAFETY_KEY, REVIVE_KEY) + DISPLAY_KEYS:
        result.setdefault(key, DEFAULTS[key])
        if type(result[key]) is not bool:
            raise ValueError(f'{key} must be true or false.')
    result.setdefault(TRANSFORM_VIEW_KEY, DEFAULTS[TRANSFORM_VIEW_KEY])
    if type(result[TRANSFORM_VIEW_KEY]) is not str or result[TRANSFORM_VIEW_KEY] not in TRANSFORM_VIEWS:
        raise ValueError(f'{TRANSFORM_VIEW_KEY} must be one of {TRANSFORM_VIEWS}.')
    result.setdefault(COOP_FUSION_KEY, DEFAULTS[COOP_FUSION_KEY])
    if type(result[COOP_FUSION_KEY]) is not str or result[COOP_FUSION_KEY] not in FUSION_MODES:
        raise ValueError(f'{COOP_FUSION_KEY} must be one of {FUSION_MODES}.')
    result.setdefault(LOCKON_KEY, DEFAULTS[LOCKON_KEY])
    if type(result[LOCKON_KEY]) is not str or result[LOCKON_KEY] not in LOCKON_BUTTONS:
        raise ValueError(f'{LOCKON_KEY} must be one of {LOCKON_BUTTONS}.')
    result.setdefault(LOCKON_HOLD_KEY,DEFAULTS[LOCKON_HOLD_KEY])
    duration=result[LOCKON_HOLD_KEY]
    if type(duration) not in (int,float) or not math.isfinite(duration) or not 0<=duration<=3600:
        raise ValueError('Target-switch hold time must be between 0 (tap) and 3600 seconds.')
    # Compare at both game-logic rates, 30 Hz (USA) and 25 Hz (European disc): lockoff_target and
    # lockon_updates round each hold up to whole updates of the selected disc, so a pair that is distinct
    # at one rate can round to the same update count at the other.
    if (result['lockoff_enabled'] and result['lockoff_button']==result[LOCKON_KEY]
            and any(math.ceil(result['lockoff_hold_seconds']*hz)<=max(1,math.ceil(duration*hz)) for hz in (25,30))):
        if duration>3599.5:
            raise ValueError('With the same button, lock-off hold time must be longer than target-switch hold time.')
        result['lockoff_hold_seconds']=duration+.5
    result.setdefault(REVIVE_COST_KEY,DEFAULTS[REVIVE_COST_KEY])
    cost=result[REVIVE_COST_KEY]
    if type(cost) is not int or not 0<=cost<=100:
        raise ValueError('Revival cost must be a whole number of blast stocks from 0 to 100.')
    result.setdefault(REVIVE_CHANNEL_KEY,DEFAULTS[REVIVE_CHANNEL_KEY])
    channel=result[REVIVE_CHANNEL_KEY]
    if type(channel) not in (int,float) or not math.isfinite(channel) or not 0.25<=channel<=60:
        raise ValueError('Revival proximity time must be between 0.25 and 60 seconds.')
    result.setdefault(NPC_OVERRIDES_KEY,{})
    overrides=result[NPC_OVERRIDES_KEY]
    if type(overrides) is not dict or any(type(key) is not str or not key.isascii()
            or not key.isdecimal() or str(int(key))!=key or int(key) not in NPC_OVERRIDE_IDS
            or type(value) is not bool for key,value in overrides.items()):
        raise ValueError(f'NPC transformation overrides require character IDs {NPC_OVERRIDE_IDS[0]}..'
                         f'{NPC_OVERRIDE_IDS[-1]} and true/false values.')
    result['version'] = VERSION
    return result


def lockon_mask(settings):
    """Raw pad bit of the configured logical PS2 button."""
    return LOCKON_MASKS[validate_settings(settings)[LOCKON_KEY]]


def lockon_updates(settings):
    """Minimum active battle updates before release; zero means a simple tap."""
    # Imported when used: the settings window must open even when the chosen game disc is damaged (the Game disc
    # page repairs it), and native_map resolves that disc when it is imported.
    from native_map import ACTOR_HZ
    return math.ceil(validate_settings(settings)[LOCKON_HOLD_KEY]*ACTOR_HZ)


def true_body_change(settings):
    """Whether new preparations install Ginyu's actual-pair body exchange."""
    return validate_settings(settings)[TRUE_BODY_KEY]


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate mod settings field: {key}.')
        result[key] = value
    return result


def _same_file(first, second):
    try:
        return Path(first).resolve() == Path(second).resolve()
    except (OSError, RuntimeError):
        return False


def developer_tree():
    """True in a developer tree: no player-install.json and no installer copy of the defaults, this module's own
    settings and defaults paths (a patched SETTINGS_PATH or DEFAULTS_PATH, as in tests, is not one), and the
    installer's player-defaults.json beside the tree. An installation never is: its folder has no player-installer."""
    return (_same_file(SETTINGS_PATH, ROOT / 'mod-settings.json')
            and _same_file(DEFAULTS_PATH, ROOT / 'mod-settings-defaults.json')
            and not (ROOT / 'player-install.json').exists() and not Path(DEFAULTS_PATH).exists()
            and Path(SHIPPED_DEFAULTS).is_file())


def defaults_path():
    """This tree's shipped-defaults file: DEFAULTS_PATH when it exists (an installation: the installer's validated
    copy of player-defaults.json), SHIPPED_DEFAULTS read in place in a developer tree, else None (the code DEFAULTS)."""
    if Path(DEFAULTS_PATH).is_file():
        return Path(DEFAULTS_PATH)
    return Path(SHIPPED_DEFAULTS) if developer_tree() else None


def developer_defaults(path=None):
    """Developer trees only: the shipped defaults (validated, no language) that fill the keys this tree's own settings
    file lacks. None elsewhere: an installation's file is complete, and an imported older file keeps the code
    DEFAULTS for keys its release did not have (legacy behaviour; install_player.import_previous)."""
    target = Path(path) if path is not None else Path(SETTINGS_PATH)
    if not _same_file(target, SETTINGS_PATH) or not developer_tree():
        return None
    return installed_defaults(SHIPPED_DEFAULTS)


def load_settings(path=None):
    """Return defaults for a missing file; reject existing malformed data. In a developer tree, keys the file lacks
    (and a missing file) take the installer's player-defaults.json, as a new installation writes them."""
    path = Path(path) if path is not None else SETTINGS_PATH
    shipped = developer_defaults(path)
    try:
        data = atomic_files.read_bytes(path)
    except FileNotFoundError:
        return validate_settings({}, defaults=shipped) if shipped else copy.deepcopy(DEFAULTS)
    try:
        settings = json.loads(data.decode('utf-8-sig'), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f'Cannot read mod settings at {path}: {error}') from error
    return validate_settings(settings, defaults=shipped)


def save_settings(updates, path=None):
    """Merge explicit edits into the latest file, preserving unrelated fields."""
    path = Path(path) if path is not None else SETTINGS_PATH
    # Validate the patch too: an invalid supplied version must not be discarded.
    normalized = validate_settings(updates)
    settings = load_settings(path)
    patch = copy.deepcopy(updates)
    patch.pop(PAUSE_KEY, None)
    # An unrelated edit or a version-only patch must not overwrite the user's
    # existing selection with validation defaults.
    if MODE_KEY in updates or PAUSE_KEY in updates:
        patch[MODE_KEY] = normalized[MODE_KEY]
    patch['version'] = VERSION
    settings.update(patch)
    settings = validate_settings(settings)
    atomic_files.write_json(path, settings)
    localization.invalidate()
    return settings


def installed_defaults(path=None):
    """The validated installer defaults (without the language), or None when absent or unusable. path: a defaults
    file; None: this tree's own (defaults_path(): an installation's copy, or a developer tree's SHIPPED_DEFAULTS)."""
    path = Path(path) if path is not None else defaults_path()
    if path is None:
        return None
    try:
        raw = json.loads(atomic_files.read_bytes(path).decode('utf-8-sig'), object_pairs_hook=_unique_object)
        if type(raw) is dict:
            raw.pop(LANGUAGE_KEY, None)
        result = validate_settings(raw)
        result.pop(LANGUAGE_KEY, None)
        return result
    except (OSError, UnicodeError, ValueError):
        return None


def default_settings(path=None):
    """What Restore defaults stages: the installed defaults when that file exists
    and validates (a developer tree: the installer's player-defaults.json), otherwise
    DEFAULTS: every editable setting plus npc_transform_overrides (so restoring
    resets the exceptions). Never contains the language or the file version. Save
    changed keys only."""
    source = installed_defaults(path) or DEFAULTS
    return {key: copy.deepcopy(source[key]) for key in DEFAULTS if key not in (LANGUAGE_KEY, 'version')}


def installer_settings(language=None):
    """What a new installation's mod-settings.json holds (install_player.write_settings): this tree's shipped
    defaults (defaults_path), validated, plus `language` (None: the code default). None without them."""
    shipped = installed_defaults()
    if shipped is None:
        return None
    return validate_settings(dict(shipped, **{LANGUAGE_KEY: language or DEFAULTS[LANGUAGE_KEY]}))


def developer_drift(path=None):
    """Developer trees only: the editable keys whose effective value differs from a new installation's, in page
    order. Empty in an installation, for another settings file, or when the file cannot be read."""
    if developer_defaults(path) is None:
        return []
    try:
        settings = load_settings(path)
        fresh = installer_settings(settings[LANGUAGE_KEY])
    except (OSError, ValueError):
        return []
    if fresh is None:
        return []
    keys = [key for key in ui_fields() if key != LANGUAGE_KEY] + [NPC_OVERRIDES_KEY]
    return [key for key in keys if settings.get(key) != fresh.get(key)]


def broken_copy_path(path=None):
    """Where repair_settings keeps the unreadable file: mod-settings.broken.json,
    or the first free mod-settings.broken-2.json, -3, ... An earlier copy is
    never overwritten, so repairing twice keeps both old files."""
    path = Path(path) if path is not None else SETTINGS_PATH
    number = 1
    while True:
        suffix = '' if number == 1 else f'-{number}'
        candidate = path.with_name(path.stem + '.broken' + suffix + path.suffix)
        if not candidate.exists():
            return candidate
        number += 1


def _keep_broken_copy(path, raw):
    while True:
        target = broken_copy_path(path)
        try:
            stream = open(target, 'xb')
        except FileExistsError:
            continue  # Created since the check: take the next free name.
        try:
            with stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return target


def repair_settings(path=None):
    """Replace a settings file that cannot be loaded with the defaults.

    Whole-file atomic replace (save_settings merges into the file, so it cannot
    fix one). Keeps the saved language when it is still readable and a copy of
    the old bytes under broken_copy_path(). Only offer this after load fails.
    """
    path = Path(path) if path is not None else SETTINGS_PATH
    language = DEFAULTS[LANGUAGE_KEY]
    try:
        raw = atomic_files.read_bytes(path)
    except FileNotFoundError:
        raw = None
    if raw is not None:
        try:
            saved = json.loads(raw.decode('utf-8-sig')).get(LANGUAGE_KEY)
            if saved in localization.LANGUAGES:
                language = saved
        except (UnicodeError, ValueError, AttributeError):
            pass
        _keep_broken_copy(path, raw)
    settings = validate_settings(dict(default_settings(), **{LANGUAGE_KEY: language}))
    atomic_files.write_json(path, settings)
    localization.invalidate()
    return settings


def can_enable(key, settings=None):
    """(allowed, message) for switching `key` on from a settings screen."""
    if key == 'expanded_maps':
        try:
            import map_scale_launch
            ready = map_scale_launch.expanded_ready()
        except (ImportError, OSError, ValueError, KeyError):
            ready = False  # An unreadable install profile counts as not built.
        if not ready:
            return False, tr('Run Build expanded maps.cmd first.', settings)
    return True, ''


def help_note(group, settings=None):
    return tr(notes[group], settings)


class SettingsController:
    """Small UI state seam; cancel and close never write preferences."""
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else SETTINGS_PATH
        self.settings = load_settings(self.path)
        self.closed = False

    def save(self, mode, *, ultimate=None, transformation=None, fusion=None, lockon=None,
             body_change=None, display=None,lockon_hold=None, npc_transform=None, npc_giant=None, npc_overrides=None,
             corpse_safety=None, revival=None):
        if self.closed:
            raise ValueError('This settings window is already closed.')
        changes = {MODE_KEY: mode}
        for key, value in ((ULTIMATE_KEY, ultimate), (TRANSFORMATION_KEY, transformation),
                           (COOP_FUSION_KEY, fusion), (LOCKON_KEY, lockon), (TRUE_BODY_KEY, body_change),
                           (LOCKON_HOLD_KEY,lockon_hold), (CORPSE_SAFETY_KEY,corpse_safety)):
            if value is not None:
                changes[key] = value
        if display is not None:
            if type(display) is not dict or any(key not in DISPLAY_KEYS for key in display):
                raise ValueError('Unknown display option.')
            changes.update(display)
        if revival is not None:
            if type(revival) is not dict or any(key not in REVIVE_KEYS for key in revival):
                raise ValueError('Unknown revival option.')
            changes.update(revival)
        for key,value in ((NPC_TRANSFORM_KEY,npc_transform),(NPC_GIANT_KEY,npc_giant),
                          (NPC_OVERRIDES_KEY,npc_overrides)):
            if value is not None: changes[key]=value
        self.settings = save_settings(changes, self.path)
        self.closed = True
        return copy.deepcopy(self.settings)

    def cancel(self):
        self.closed = True

    def save_all(self, changes):
        """Save the explicit visible form, preserving unrelated file fields."""
        if self.closed:raise ValueError('This settings window is already closed.')
        if type(changes)is not dict or any(key not in DEFAULTS for key in changes):
            raise ValueError('Unknown settings control.')
        self.settings=save_settings(changes,self.path)
        self.closed=True
        return copy.deepcopy(self.settings)


def show_npc_character_ui(parent, overrides):
    """Choose named native forms; changes commit only when this dialog is accepted."""
    import tkinter as tk
    from tkinter import ttk
    from character_names import character_table
    rows=character_table()
    dialog=tk.Toplevel(parent);dialog.title(tr('CPU transformation exceptions'))
    dialog.transient(parent);input_binding.grab_dialog(dialog)
    panel=ttk.Frame(dialog,padding=16);panel.grid(sticky='nsew')
    ttk.Label(panel,text=tr('Select a character/form, then choose Default, Allow or Block.\n'
              'Allow overrides both global CPU restrictions; it does not bypass native move rules.')).grid(
                  row=0,column=0,columnspan=2,sticky='w',pady=(0,10))
    tree=ttk.Treeview(panel,columns=('character','policy'),show='headings',height=18,selectmode='extended')
    tree.heading('character',text=tr('Current character / form'));tree.heading('policy',text=tr('Transformations'))
    tree.column('character',width=350);tree.column('policy',width=120)
    tree.grid(row=1,column=0,sticky='nsew')
    scroll=ttk.Scrollbar(panel,orient='vertical',command=tree.yview);scroll.grid(row=1,column=1,sticky='ns')
    tree.configure(yscrollcommand=scroll.set)
    pending=copy.deepcopy(overrides);result=[]
    def label(cid): return tr('Default' if str(cid) not in pending else ('Allow' if pending[str(cid)] else 'Block'))
    for cid in NPC_OVERRIDE_IDS: tree.insert('', 'end',iid=str(cid),values=(rows.get(cid,{}).get('name') or tr('Character {cid}',cid=cid),label(cid)))
    def choose(value):
        for iid in tree.selection():
            if value is None:pending.pop(iid,None)
            else:pending[iid]=value
            tree.set(iid,'policy',label(int(iid)))
    choices=ttk.Frame(panel);choices.grid(row=2,column=0,columnspan=2,sticky='w',pady=10)
    for col,(text,value) in enumerate((('Default',None),('Allow',True),('Block',False))):
        ttk.Button(choices,text=tr(text),command=lambda v=value:choose(v)).grid(row=0,column=col,padx=(0,8))
    def accept():result.append(pending);dialog.destroy()
    buttons=ttk.Frame(panel);buttons.grid(row=3,column=0,columnspan=2,sticky='e')
    ttk.Button(buttons,text=tr('Cancel'),command=dialog.destroy).grid(row=0,column=0,padx=8)
    ttk.Button(buttons,text=tr('Use these exceptions'),command=accept).grid(row=0,column=1)
    dialog.bind('<Escape>',lambda _:dialog.destroy());dialog.wait_window()
    return result[0] if result else None


def ui_fields():
    """Every active preference has one editable control, in page order."""
    rows = {
        MODE_KEY: ('all','choice',MODES,None,'Cinematics','Special-move pause'),
        ULTIMATE_KEY: (False,'bool',None,None,'Cinematics','Ultimate attacks: shared camera and pause'),
        TRANSFORMATION_KEY: (False,'bool',None,None,'Cinematics','Transformations: camera and pause'),
        TRANSFORM_VIEW_KEY: ('shared','choice',TRANSFORM_VIEWS,None,'Cinematics','Transformations in split screen'),
        COOP_FUSION_KEY: ('swap_20s','choice',FUSION_MODES,None,'Fusion','Two-player fusion controls'),
        LOCKON_KEY: ('r3','button',LOCKON_BUTTONS,None,'Controls','Target / spectator switch button'),
        LOCKON_HOLD_KEY: (.5,'float',0,3600,'Controls','Target switch hold time (seconds; 0 = tap)'),
        FRIEND_BARS_KEY: (True,'bool',None,None,'HUD','Friendly overhead health bars'),
        ENEMY_BARS_KEY: (True,'bool',None,None,'HUD','Enemy overhead health bars'),
        NATIVE_HUD_KEY: (True,'bool',None,None,'HUD','Battle HUD (including split-screen panels)'),
        KILL_FEED_KEY: (True,'bool',None,None,'HUD','Kill feed'),
        KILL_SCORE_KEY: (False,'bool',None,None,'HUD','Watched fighter kill count'),
        NPC_TRANSFORM_KEY: (False,'bool',None,None,'Fighters','Disable all CPU transformations'),
        NPC_GIANT_KEY: (False,'bool',None,None,'Fighters','Disable CPU transformations into giants'),
        CORPSE_SAFETY_KEY: (True,'bool',None,None,'Revival','Keep fallen fighters in bounds'),
        REVIVE_KEY: (False,'bool',None,None,'Revival','Enable teammate revival'),
        REVIVE_COST_KEY: (4,'int',0,100,'Revival','Revival cost (blast stocks)'),
        REVIVE_CHANNEL_KEY: (4.,'float',.25,60,'Revival','Stand nearby for (seconds)'),
    }
    rows.update(feature_preferences.OPTIONS)
    return {key: (*rows[key][:4], group, rows[key][5]) for group, keys in GROUPS for key in keys}


def ui_groups():
    return tuple(group for group, _ in GROUPS)


class PageWheel:
    """Mouse-wheel scrolling of the selected desktop settings page.

    Only wheel events over the settings window itself scroll it. Events from
    other windows (the exceptions and rebind dialogs, or a drop-down's list,
    which Tk reports as a plain path string) are ignored. Spinboxes, drop-downs
    and the category list keep their own wheel behaviour: this handler never
    changes a value. Touchpads report fractions of a notch (120); they add up.
    """
    NOTCH = 120

    def __init__(self, window, page, own):
        self.window = window    # the settings Tk window
        self.page = page        # () -> the selected page's canvas, or None
        self.own = own          # widget classes with their own wheel behaviour
        self.canvas = None; self.pending = 0

    def __call__(self, event):
        import tkinter
        widget = event.widget
        if isinstance(widget, str) or isinstance(widget, self.own):
            return None
        try:
            if widget.winfo_toplevel() is not self.window:
                return None
        except (AttributeError, tkinter.TclError):
            return None
        canvas = self.page()
        if canvas is None:
            return None
        if canvas is not self.canvas:
            self.canvas, self.pending = canvas, 0
        self.pending -= event.delta
        units = int(self.pending/self.NOTCH)   # toward zero: the remainder waits
        if units:
            self.pending -= units*self.NOTCH
            canvas.yview_scroll(units, 'units')
        return None


WHEEL_NOTCH = 120   # one <MouseWheel> notch, as Windows and Tk 8.7+ report it


class WheelNotch:
    """An X11 button-4/5 press, shaped like the <MouseWheel> event PageWheel reads."""
    def __init__(self, widget, delta):
        self.widget, self.delta = widget, delta


def x11_wheel_buttons(window):
    """Tk before 8.7 reports the X11 wheel as buttons 4 and 5, never as <MouseWheel>."""
    import tkinter
    try:
        system = window.tk.call('tk', 'windowingsystem')
    except tkinter.TclError:
        return False
    return system == 'x11' and tkinter.TkVersion < 8.7


def bind_wheel(window, handler):
    """<MouseWheel> everywhere; on X11 with Tk 8.6, button 4/5 become one notch up/down.

    Tk 8.7 and later send <MouseWheel> on X11 too, so the buttons are not bound there."""
    window.bind_all('<MouseWheel>', handler)
    if x11_wheel_buttons(window):
        for button, delta in ((4, WHEEL_NOTCH), (5, -WHEEL_NOTCH)):
            window.bind_all(f'<Button-{button}>', lambda event, d=delta: handler(WheelNotch(event.widget, d)))


def form_changes(settings, values, overrides):
    """Validate the complete form but only commit fields the user changed."""
    fields=ui_fields()
    if set(values)!=set(fields):raise ValueError('Incomplete settings form.')
    candidate=validate_settings(dict(settings, **values, **{NPC_OVERRIDES_KEY:overrides}))
    return {key:candidate[key] for key in (*fields,NPC_OVERRIDES_KEY)
            if candidate[key]!=settings[key]}


def show_ui(path=None):
    import tkinter as tk
    from tkinter import messagebox, ttk
    title=tr(WINDOW_TITLE,adapter=ADAPTER)
    window=tk.Tk();window.withdraw()
    unreadable=tr('Your settings could not be opened. The saved file was left unchanged.')
    try:controller=SettingsController(path)
    except OSError as error:
        messagebox.showerror(title,unreadable+f'\n\n{error}',parent=window);window.destroy();return 2
    except ValueError as error:
        # A malformed file cannot be merged into; offer the whole-file repair.
        target=Path(path) if path is not None else SETTINGS_PATH
        question=unreadable+f'\n\n{error}\n\n'+tr('Replace them with the default settings? A copy of the old file is kept as {name}.',
                                                   name=broken_copy_path(target).name)
        if not messagebox.askyesno(title,question,parent=window):window.destroy();return 2
        try:repair_settings(target);controller=SettingsController(path)
        except (OSError,ValueError) as failure:
            messagebox.showerror(title,tr('Your changes could not be saved.')+f'\n\n{failure}',parent=window)
            window.destroy();return 2
    window.title(title);window.geometry('940x660');window.minsize(860,520)
    outer=ttk.Frame(window,padding=16);outer.pack(fill='both',expand=True)
    ttk.Label(outer,text=tr('Mod settings'),font=('Segoe UI',16,'bold')).pack(anchor='w')
    header=ttk.Label(outer,text=tr(HEADER),wraplength=880);header.pack(anchor='w',pady=(4,12))
    outer.bind('<Configure>',lambda event:header.configure(wraplength=max(300,event.width-40)))
    # Packed before the pages so a small window never hides Save.
    buttons=ttk.Frame(outer);buttons.pack(side='bottom',fill='x',pady=(14,0))
    body=ttk.Frame(outer);body.pack(fill='both',expand=True)
    body.columnconfigure(1,weight=1);body.rowconfigure(0,weight=1)
    groups=ui_groups();fields=ui_fields();listed=groups+DESKTOP_PAGES
    categories=tk.Listbox(body,exportselection=False,activestyle='none',width=30,font=('Segoe UI',10),
                          height=len(listed),highlightthickness=0)
    for group in listed:categories.insert('end',' '+tr(group))
    categories.grid(row=0,column=0,sticky='ns',padx=(0,14))
    holder=ttk.Frame(body);holder.grid(row=0,column=1,sticky='nsew')
    holder.rowconfigure(0,weight=1);holder.columnconfigure(0,weight=1)
    containers={};pages={};canvases={};rows={};footers={}
    def fit(event,canvas,item,group):
        canvas.itemconfigure(item,width=event.width)
        # The help note wraps to the page, so a narrower window never clips it.
        if group in footers:footers[group].configure(wraplength=max(240,event.width-28))
    for group in listed:
        container=ttk.Frame(holder);container.grid(row=0,column=0,sticky='nsew')
        canvas=tk.Canvas(container,highlightthickness=0)
        scrollbar=ttk.Scrollbar(container,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        page=ttk.Frame(canvas,padding=(4,0,12,12));item=canvas.create_window(0,0,anchor='nw',window=page)
        page.bind('<Configure>',lambda event,c=canvas:c.configure(scrollregion=c.bbox('all')))
        canvas.bind('<Configure>',lambda event,c=canvas,i=item,g=group:fit(event,c,i,g))
        page.columnconfigure(0,weight=1)
        ttk.Label(page,text=tr(group),font=('Segoe UI',13,'bold')).grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,8))
        containers[group]=container;pages[group]=page;canvases[group]=canvas;rows[group]=1
    # Every field's variable exists up front: form_changes needs the whole form.
    variables={};button_labels={};choice_labels={}
    status=tk.StringVar(value='')
    def show_value(key,value):
        variables[key].set(value if fields[key][1] in ('bool','choice','button') else str(value))
        if key in choice_labels:choice_labels[key][0].set(value_label(value,controller.settings))
        if key in button_labels:button_labels[key].set(input_binding.label(value,controller.settings))
    def spin(key,direction,big=False):
        try:current=(int if fields[key][1]=='int' else float)(variables[key].get())
        except ValueError:return 'break'
        show_value(key,feature_preferences.step_value(key,current,direction,big));return 'break'
    for key,(_,kind,low,high,group,label) in fields.items():
        page=pages[group];row=rows[group];rows[group]+=1;value=controller.settings[key]
        variable=(tk.BooleanVar if kind=='bool' else tk.StringVar)(
            value=value if kind in ('bool','choice','button') else str(value))
        variables[key]=variable
        if kind=='bool':
            command=None
            if key in CHECKED_ENABLES:
                def command(v=variable,k=key,text=label):
                    if not v.get():return
                    allowed,message=can_enable(k,controller.settings)
                    if not allowed:v.set(False);messagebox.showwarning(tr(text),message,parent=window)
            ttk.Checkbutton(page,text=tr(label),variable=variable,command=command).grid(
                row=row,column=0,columnspan=2,sticky='w',pady=6)
            continue
        ttk.Label(page,text=tr(label),wraplength=380).grid(row=row,column=0,sticky='w',pady=7,padx=(0,16))
        if kind=='button':
            box=ttk.Frame(page);box.grid(row=row,column=1,sticky='w')
            text=tk.StringVar(value=input_binding.label(variable.get(),controller.settings));button_labels[key]=text
            ttk.Label(box,textvariable=text,width=10).pack(side='left')
            def rebind(v=variable,t=text,allowed=low,name=label):
                selected=input_binding.capture_dialog(window,v.get(),title=tr('Rebind: {setting}',setting=tr(name)))
                if selected and selected not in allowed:
                    messagebox.showerror(tr(name),
                        tr('That button is needed for selecting or navigating modes. Choose Select, Start, a stick click, a shoulder button or Square.'),parent=window)
                    return
                if selected:v.set(selected);t.set(input_binding.label(selected,controller.settings))
            ttk.Button(box,text=tr('Rebind…'),command=rebind).pack(side='left')
        elif kind=='choice':
            labels={value_label(v,controller.settings):v for v in low}
            shown=tk.StringVar(value=value_label(variable.get(),controller.settings))
            choice_labels[key]=(shown,labels)
            # 28 characters: the widest label ('Jugador arriba, objetivo abajo') is never clipped.
            box=ttk.Combobox(page,textvariable=shown,values=tuple(labels),state='readonly',width=28)
            box.grid(row=row,column=1,sticky='w')
            box.bind('<<ComboboxSelected>>',lambda event,v=variable,s=shown,m=labels:v.set(m[s.get()]))
        else:
            ui_low,ui_high=feature_preferences.ui_range(key)
            box=ttk.Spinbox(page,textvariable=variable,from_=ui_low,to=ui_high,
                            increment=feature_preferences.STEPS[key],width=10)
            box.grid(row=row,column=1,sticky='w')
            # Same grid as the in-game editor; Page Up/Down move ten steps.
            box.bind('<<Increment>>',lambda event,k=key:spin(k,1))
            box.bind('<<Decrement>>',lambda event,k=key:spin(k,-1))
            box.bind('<Prior>',lambda event,k=key:spin(k,1,True))
            box.bind('<Next>',lambda event,k=key:spin(k,-1,True))
    overrides=copy.deepcopy(controller.settings[NPC_OVERRIDES_KEY])
    def edit_exceptions():
        changed=show_npc_character_ui(window,overrides)
        if changed is not None:overrides.clear();overrides.update(changed)
    group=EXCEPTIONS_GROUP;ttk.Button(pages[group],text=tr('Per-character transformation exceptions…'),
        command=edit_exceptions).grid(row=rows[group],column=0,columnspan=2,sticky='w',pady=12)
    rows[group]+=1
    for group in groups:
        footers[group]=ttk.Label(pages[group],text=help_note(group),wraplength=560,foreground='#555555')
        footers[group].grid(row=rows[group],column=0,columnspan=2,sticky='w',pady=(18,8))
    # Desktop-only pages act at once (their own buttons); Save and Cancel below are for the settings pages.
    import disc_page
    def language_changed(value):
        controller.settings[LANGUAGE_KEY]=value;show_value(LANGUAGE_KEY,value)
    disc=disc_page.build(pages[disc_page.PAGE],window,controller.settings,on_language=language_changed)
    footers[disc_page.PAGE]=disc.footer
    if os.name!='nt':
        # Linux Tk fonts are wider than Segoe UI: size the minimum window from the widest settings row
        # (help notes wrap, so they are measured narrow) so nothing clips. Windows keeps 860 px.
        for footer in footers.values():footer.configure(wraplength=240)
        window.update_idletasks()
        needed=(2*16+categories.winfo_reqwidth()+14+scrollbar.winfo_reqwidth()
                +max(pages[group].winfo_reqwidth() for group in groups))
        for footer in footers.values():footer.configure(wraplength=560)
        if needed>860:window.minsize(needed,520);window.geometry(f'{max(940,needed)}x660')
    def select(_=None):
        chosen=categories.curselection()
        if chosen:
            containers[listed[chosen[0]]].tkraise()
            if listed[chosen[0]]==disc_page.PAGE:disc.shown()
    def selected_page():
        chosen=categories.curselection()
        return canvases[listed[chosen[0]]] if chosen else None
    wheel=PageWheel(window,selected_page,(ttk.Spinbox,ttk.Combobox,tk.Listbox))
    categories.bind('<<ListboxSelect>>',select);bind_wheel(window,wheel)
    categories.selection_set(0);select()
    def cancel():controller.cancel();window.destroy()
    def defaults():
        values=default_settings()
        for key in variables:
            if key in values:show_value(key,values[key])
        for key in CHECKED_ENABLES:
            if variables[key].get() and not can_enable(key,controller.settings)[0]:variables[key].set(False)
        overrides.clear();overrides.update(values[NPC_OVERRIDES_KEY])
        status.set(tr('Defaults restored. Save to keep them.'))
    def save():
        try:
            values={key: (int(var.get()) if fields[key][1]=='int' else
                         float(var.get()) if fields[key][1]=='float' else var.get())
                    for key,var in variables.items()}
            controller.save_all(form_changes(controller.settings,values,overrides))
        except (OSError,ValueError,tk.TclError) as error:
            messagebox.showerror(title,tr('Your changes could not be saved.')+f'\n\n{error}',parent=window);return
        window.destroy()
    ttk.Button(buttons,text=tr('Restore defaults'),command=defaults).pack(side='left')
    ttk.Label(buttons,textvariable=status,foreground='#555555').pack(side='left',padx=12)
    ttk.Button(buttons,text=tr('Save'),command=save).pack(side='right')
    ttk.Button(buttons,text=tr('Cancel'),command=cancel).pack(side='right',padx=8)
    window.protocol('WM_DELETE_WINDOW',cancel);window.bind('<Escape>',lambda _:cancel())
    window.deiconify();window.mainloop();return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--ui', action='store_true', help='Open the settings window')
    group.add_argument('--show', action='store_true', help='Print the effective settings as JSON')
    group.add_argument('--check', action='store_true', help='Check dependencies without opening a window')
    args = parser.parse_args(argv)
    try:
        if args.ui:
            return show_ui()
        if args.check:
            import tkinter
            if sys.version_info < (3, 11):
                raise ValueError('Python 3.11 or later is required.')
            print(f'Settings dependencies ready: Tk {tkinter.TkVersion}')
        else:
            print(json.dumps(load_settings(), indent=2))
        return 0
    except (OSError, ValueError, ImportError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
