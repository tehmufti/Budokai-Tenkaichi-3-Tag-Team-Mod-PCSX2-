"""Reviewed BT4 Beta 14 identity mapping, separate from a modded ISO's adapter.

The configurable dance duration represents 30 lore minutes. Mortal Potara
represents 60, so its gameplay timer is twice as long. Energy-expenditure
shortening is not simulated. Preselected fused characters have no receipt.
"""
MORTAL_POTARA_RESULTS=(51,104,154) # Vegito and Kefla forms; divine Fused Zamasu (76) stays untimed.
SOURCES=(
    'https://en.dragon-ball-official.com/news/01_2255.html',
    'https://www.kanzenshuu.com/wiki/Dragon_Ball_Super_Chapter_23',
)


def timed(kind,result,lore=True):
    return kind==1 or (lore and kind==2 and result in MORTAL_POTARA_RESULTS)
