"""Shared overlay bands in each 256 by 224 multiplayer viewport.

Keep the top 66 pixels and bottom 66 pixels for either status-panel style.
World markers and native clash prompts keep their native positions.
"""
FUSION_Y=70
SCORE_Y=114
FEED_Y=128
TAKEOVER_Y=151


def reservations(rect):
    left,right,top,bottom=rect
    return {
        'own status':(left,top,right,top+66),
        'fusion owner':(left+8,top+FUSION_Y,left+218,top+FUSION_Y+7),
        'control countdown':(left+8,top+FUSION_Y+12,left+218,top+FUSION_Y+19),
        'fusion timer':(left+8,top+FUSION_Y+24,left+128,top+FUSION_Y+39),
        'kills':(left+8,top+SCORE_Y,left+62,top+SCORE_Y+7),
        'kill feed':(left+8,top+FEED_Y,left+248,top+FEED_Y+17),
        'takeover':(left+8,top+TAKEOVER_Y,left+242,top+TAKEOVER_Y+7),
        'target status':(left,bottom-64,right,bottom),
    }
