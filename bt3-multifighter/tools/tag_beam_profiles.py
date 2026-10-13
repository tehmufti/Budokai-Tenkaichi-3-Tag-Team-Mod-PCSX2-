"""Reviewed tag-attack presentation, keyed by disc roster ID and current form.

These are pose/color choices, never replacement move parameters. 'auto' keeps
the guarded native beam selection for fighters without an explicit profile.
The IDs deliberately do not depend on the menu's language.
"""

REVISION = 2
BLUE = (64, 160, 255)
GOLD = (255, 180, 32)
ORANGE = (255, 158, 24)
GREEN = (88, 255, 48)
PURPLE = (178, 72, 255)
RED = (255, 48, 48)
PINK = (255, 80, 180)
DARK_PINK = (215, 64, 190)
CYAN = (64, 200, 255)

# Reviewed continuous-beam slots, not a move-type heuristic: type 0 also
# contains ball/projectile animations. Each slot's startup, charge loop,
# release and firing clips was decoded and its pose inspected. Colors follow
# that move's native effect palette; the explicit player choices below win.
# Roster IDs differ between discs even where animation bytes are identical.
_NATIVE_BT3 = {
    59: (4, BLUE),    # Kibitokai
    61: (4, GOLD),    # Pikkon
    64: (2, BLUE),    # Uub
    71: (2, PURPLE),  # King Vegeta
    73: (2, BLUE),    # Bardock
    75: (2, PINK),    # Fasha
    79: (2, PURPLE),  # Saibamen
    82: (4, GOLD),    # Zarbon
    83: (2, GOLD),    # Zarbon, transformed
    84: (2, GOLD),    # Dodoria, mouth beam
    85: (2, PINK),    # Cui
    86: (2, PURPLE),  # Captain Ginyu
    87: (2, PURPLE),  # Recoome, mouth beam
    89: (2, RED),     # Jeice
    91: (2, PURPLE),  # Frieza, first form
    92: (2, PURPLE),  # Frieza, second form
    93: (2, PURPLE),  # Frieza, third form
    96: (2, PURPLE),  # Mecha Frieza
    97: (2, PURPLE),  # King Cold
    98: (2, PURPLE),  # Appule
    99: (3, PURPLE),  # Frieza Soldier
    101: (3, GOLD),   # Android 17
    103: (2, PINK),   # Android 19
    104: (2, PINK),   # Dr. Gero
    110: (4, PURPLE), # Babidi
    111: (2, RED),    # Dabura
    119: (2, RED),    # Super Garlic Jr.
    125: (2, GOLD),   # Salza
    126: (2, BLUE),   # Cooler
    127: (2, PURPLE), # Cooler, final form
    129: (2, RED),    # Android 13
    131: (2, GREEN),  # Broly
    136: (4, GREEN),  # Bojack, full power
    140: (2, PINK),   # Baby Vegeta
    141: (2, PINK),   # Super Baby 1
    142: (2, PINK),   # Super Baby 2
    144: (2, BLUE),   # Super 17
    148: (2, GOLD),   # General Tao
    149: (2, GOLD),   # Cyborg Tao
    154: (2, GOLD),   # Tambourine, mouth beam
    155: (2, PINK),   # King Piccolo
}

_NATIVE_BT4 = {
    57: (2, PURPLE),  # Cabba
    61: (4, GOLD),    # Pikkon
    71: (2, PURPLE),  # Beerus
    73: (2, BLUE),    # Bardock
    75: (2, PINK),    # Fasha
    76: (4, GOLD),    # Fused Zamasu
    78: (2, CYAN),    # Hit
    79: (2, PINK),    # Cui
    82: (4, GOLD),    # Zarbon
    83: (2, GOLD),    # Zarbon, transformed
    84: (2, GOLD),    # Dodoria, mouth beam
    86: (2, PURPLE),  # Captain Ginyu
    87: (2, PURPLE),  # Recoome, mouth beam
    89: (2, RED),     # Jeice
    91: (2, PURPLE),  # Frieza, first form
    92: (2, PURPLE),  # Frieza, second form
    93: (2, PURPLE),  # Frieza, third form
    96: (2, PURPLE),  # Mecha Frieza
    97: (2, PURPLE),  # King Cold
    101: (3, GOLD),   # Android 17
    103: (2, PINK),   # Android 19
    104: (4, GREEN),  # Kefla
    111: (2, RED),    # Dabura
    118: (2, RED),    # Caulifla
    119: (2, GOLD),   # Caulifla, Super Saiyan
    126: (2, BLUE),   # Cooler
    127: (2, PURPLE), # Cooler, final form
    129: (2, RED),    # Android 13
    134: (2, PURPLE), # Cabba, Super Saiyan
    135: (2, RED),    # Caulifla, Super Saiyan 2
    136: (4, GREEN),  # Bojack, full power
    140: (2, PINK),   # Baby Vegeta
    141: (2, PINK),   # Super Baby 1
    142: (2, PINK),   # Super Baby 2
    144: (2, BLUE),   # Super 17
    146: (4, GREEN),  # Eis Shenron
    148: (2, GOLD),   # General Tao
    150: (2, PURPLE), # Top, Destroyer
    154: (4, GREEN),  # Kefla, Super Saiyan
    155: (2, PINK),   # King Piccolo
    167: (2, PURPLE), # King Vegeta
    180: (2, GOLD),   # Tambourine, mouth beam
    181: (2, GOLD),   # Cyborg Tao
    183: (2, RED),    # Super Garlic Jr.
    184: (2, PURPLE), # Saibamen
    185: (2, PINK),   # Dr. Gero
    186: (2, GOLD),   # Salza
    188: (2, GREEN),  # Broly (Z)
    191: (4, BLUE),   # Kibitokai
    193: (4, PURPLE), # Babidi
    196: (2, BLUE),   # Uub
    199: (2, GREEN),  # Kale, Super Saiyan
    200: (4, GREEN),  # Kale, Legendary Super Saiyan
    209: (3, GREEN),  # Broly, Super Saiyan 3
    210: (2, BLUE),   # Tarble
    212: (2, CYAN),   # Android 14
    214: (2, GOLD),   # Neiz
    222: (2, PURPLE), # Appule
    223: (3, PURPLE), # Frieza Soldier
    229: (4, ORANGE), # Dyspo
    230: (2, PINK),   # Frost
}


def _row(family, color, *, mode='own', slot=2, donor=None):
    return dict(mode=mode, slot=slot, donor=donor, color=color, family=family)


def profile(character, *, bt4=False):
    """Return a fresh policy record; no mutable table or cross-disc fallbacks."""
    if type(character) is not int or not 0 <= character < 256:
        raise ValueError('Invalid tag beam character ID')
    if character in (*range(10), 11, 25, 26, 66, 67):
        return _row('kamehameha', BLUE)
    if character == 10:
        return _row('red_kamehameha', RED)
    kame = {14:4, 15:4, 16:2, 17:4, 18:4, 19:4, 21:2,
            46:4, 47:2, 53:2, 54:2, 63:2, 105:2, 109:4,
            112:3, 115:4, 116:2, 117:2, 159:4}
    kame.update({59:2, 64:2, 85:4, 98:2, 107:4, 110:4, 122:2,
                 158:4, 177:2, 192:2, 220:2, 221:2, 224:2}
                if bt4 else {51:4, 52:2, 68:2, 107:2, 108:4, 113:2})
    if character in kame:
        return _row('kamehameha', BLUE, slot=kame[character])
    if character == 106 or (bt4 and character in (51, 52)):
        return _row('kamehameha', BLUE, mode='donor', donor=0)
    if character == 160:
        return _row('kamehameha', BLUE, mode='donor', slot=4, donor=159)
    if bt4 and character == 139:
        # Blue Gogeta's ultimate has a zero-frame charge loop. Reuse Gogeta's
        # complete beam sequence rather than entering that cinematic-only slot.
        return _row('kamehameha', BLUE, mode='donor', donor=53)
    if character == 114:
        return _row('buu_mouth_beam', PINK, mode='donor', slot=4, donor=80)
    if bt4 and character in (34, 99):
        return _row('dark_kamehameha', DARK_PINK, slot=2 if character == 34 else 4)
    if character == 13:
        return _row('masenko', GOLD)
    if character in (22, 23):
        return _row('special_beam_cannon', ORANGE, slot=4 if character == 22 else 2)
    if character in (27, 28):
        return _row('dodon_ray', ORANGE)
    if character in (29, 31) or (not bt4 and character == 34) or (bt4 and character == 217):
        return _row('galick_gun', PURPLE, mode='own' if character == 29 else 'donor',
                    donor=None if character == 29 else 29)
    gold_vegeta = (32, 33, 36, 208, 218, 219) if bt4 else (32, 33, 35, 36)
    if character in gold_vegeta:
        return _row('gold_galick_gun', GOLD, mode='donor', donor=29)
    if character == 37 or (bt4 and character == 68):
        return _row('one_handed_gold', GOLD, mode='own' if character == 37 else 'donor',
                    donor=None if character == 37 else 37)
    if character == 38:
        return _row('final_shine', GREEN, slot=2 if bt4 else 4)
    if bt4 and character in (35, 113):
        return _row('galick_gun', PURPLE, mode='donor', donor=29)
    trunks = (*range(39, 46), 72, 149, 225, 226, 227, 228) if bt4 else tuple(range(39, 46))
    if character in (*trunks, 24, 77):
        return _row('gold_clash', GOLD, mode='generic', slot=0)
    if character == 58:
        return _row('supreme_kai_beam', BLUE, slot=4)
    if character == 80:
        return _row('mouth_beam', GOLD, slot=4)
    native = (_NATIVE_BT4 if bt4 else _NATIVE_BT3).get(character)
    if native is not None:
        slot, color = native
        return _row('native_beam', color, slot=slot)
    return _row('auto', None, mode='auto', slot=0)
