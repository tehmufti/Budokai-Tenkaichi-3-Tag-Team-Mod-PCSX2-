"""Shared, bounded loading metadata and card layout; no game or desktop access."""
from character_names import character_info


MODES = ('teams', 'ffa', 'coop', 'training', 'training_coop')
MAX_PER_SIDE = 6
WHITE = (233, 239, 248)
MUTED = (153, 172, 201)
BACKGROUNDS = {'teams': (9, 14, 25), 'ffa': (24, 12, 23), 'coop': (8, 22, 26), 'training':(8,22,18)}
ACCENTS = {'teams': (234, 174, 61), 'ffa': (247, 98, 119), 'coop': (70, 214, 181), 'training':(116,222,132)}
BACKGROUNDS['training_coop'] = BACKGROUNDS['training']
ACCENTS['training_coop'] = ACCENTS['training']
# Cards live between the header bars and the footer heading of the 512x448 frame.
CARD_TOP, CARD_BOTTOM = 98, 346
COLUMN_X = (28, 272)
COLUMN_WIDTH = 212
BAR_Y = 70


def mode_options(mode='teams', humans=1):
    if mode not in MODES:
        raise ValueError('Unknown loading battle mode')
    if isinstance(humans, bool) or humans not in (0, 1, 2, 3, 4):
        raise ValueError('Loading presentation requires zero to four human players')
    # Team battles and free-for-all both support spectated exhibitions.
    if mode in ('coop','training_coop') and humans not in (2,3,4):
        raise ValueError('Co-op loading presentation requires two, three or four human players')
    if mode == 'training' and humans == 0:raise ValueError('Modded Training requires one to four human players')
    return mode, humans


def design(teams=(), mode='teams', humans=1):
    """Native 512x448 layout, preserving selection side/slot and actual assets.

    The selection screen stores two sides even in FFA. Those storage sides
    disappear from its presentation; P1/P2 labels still follow physical roles.
    Up to three fighters per side keep one column of wide cards; four to six
    use two columns of compact cards. Free-for-all grids hold three columns of
    large cards up to six contestants and four columns of compact cards beyond.
    """
    mode, humans = mode_options(mode, humans)
    if not isinstance(teams, (list, tuple)) or len(teams) > 2:
        raise ValueError('Expected up to two selected teams')
    sides = {}; cards = []
    for index, team in enumerate(teams):
        side = team.get('side', index)
        fighters = team.get('fighters', [])
        if side not in (0, 1) or side in sides:
            raise ValueError('Invalid or duplicate loading team side')
        if not isinstance(fighters, (list, tuple)) or len(fighters) > MAX_PER_SIDE:
            raise ValueError('Loading screen supports up to six picks per side')
        sides[side] = fighters
        for slot, fighter in enumerate(fighters):
            cid = fighter if isinstance(fighter, int) else fighter.get('character_id')
            if isinstance(cid, bool) or not isinstance(cid, int) or not 0 <= cid < 161:
                raise ValueError('Invalid selected loading character')
            physical = slot*2+side
            role = 'CPU'
            if mode in ('coop','training_coop') and side==0 and slot<humans:
                role = 'PLAYER ' + str(physical//2+1)
            elif (mode in ('ffa','training') or (mode == 'teams' and humans >= 2)) and physical < humans:
                role = 'PLAYER ' + str(physical+1)
            elif mode == 'teams' and humans == 1:
                role = 'SLOT ' + str(slot+1)
            if isinstance(fighter,dict) and 'player' in fighter:
                player=fighter['player']
                if type(player)is not int or not 0<=player<=4:raise ValueError('Invalid player label')
                role=f'PLAYER {player}' if player else 'CPU'
            cards.append(dict(info=character_info(cid), side=side, slot=slot,
                              physical=physical, role=role))
    if mode=='ffa' and humans>=3:
        for i,card in enumerate(sorted(cards,key=lambda c:(c['side'],c['slot']))):
            card['role']=f'PLAYER {i+1}' if i<humans else 'CPU'
    accent = ACCENTS[mode]
    columns = []
    vs_y, vs_span = None, None
    if mode == 'ffa':
        cards.sort(key=lambda c: c['physical'])
        count = len(cards)
        if count <= 6:
            per_row, width, height, gap, step, portrait, small = 3, 144, 106, 12, 118, 56, False
            top = 106 if count > 3 else 166
        else:
            per_row, width, height, gap, step, portrait, small = 4, 108, 80, 8, 84, 40, True
            top = CARD_TOP
        rows = (count+per_row-1)//per_row
        for i, card in enumerate(cards):
            row, col = divmod(i, per_row)
            row_count = min(per_row, count-row*per_row)
            card.update(x=(512-(row_count*width+(row_count-1)*gap))//2+col*(width+gap),
                        y=top+row*step, width=width, height=height, accent=accent,
                        compact=True, small=small, portrait=portrait, number=i+1)
        if count:
            full = min(count, per_row)
            left = (512-(full*width+(full-1)*gap))//2
            for col in range(full):
                x0 = left+col*(width+gap)
                columns.append(dict(x0=x0, y0=top, x1=x0+width, y1=top+rows*step-(step-height),
                                    accent=accent, side=None))
        heading, subtitle = 'FREE-FOR-ALL', 'EVERY FIGHTER FOR THEMSELVES'
        groups = []
        detail = (f'{count} FIGHTERS / ALL CPU' if humans == 0
                  else f'{count} FIGHTERS / {humans} PLAYER' + ('S' if humans > 1 else ''))
        footer = 'LAST FIGHTER STANDING WINS'
    else:
        labels = ((('ALLIES', accent), ('OPPONENTS', (246, 164, 93))) if mode in ('coop','training_coop')
                  else (('TEAM 1', (68, 179, 246)), ('TEAM 2', (245, 116, 97))))
        groups = [dict(label=label, x=COLUMN_X[side]+13, y=BAR_Y+3, accent=color, side=side,
                       box=(COLUMN_X[side], BAR_Y, COLUMN_X[side]+COLUMN_WIDTH, BAR_Y+20))
                  for side, (label, color) in enumerate(labels)]
        tops, bottoms = [], []
        for side in (0, 1):
            members = [card for card in cards if card['side'] == side]
            x = COLUMN_X[side]
            if len(members) <= 3:
                for card in members:
                    card.update(x=x, y=106+card['slot']*80, width=COLUMN_WIDTH, height=72,
                                accent=groups[side]['accent'], compact=False, small=False,
                                portrait=56, number=card['slot']+1)
                if members:
                    tops.append(106); bottoms.append(106+len(members)*80-8)
            else:
                for card in members:
                    row, col = divmod(card['slot'], 2)
                    card.update(x=x+col*110, y=CARD_TOP+row*84, width=102, height=80,
                                accent=groups[side]['accent'], compact=True, small=True,
                                portrait=40, number=card['slot']+1)
                tops.append(CARD_TOP); bottoms.append(CARD_TOP+((len(members)+1)//2)*84-4)
            columns.append(dict(x0=x, y0=CARD_TOP, x1=x+COLUMN_WIDTH, y1=CARD_BOTTOM,
                                accent=groups[side]['accent'], side=side))
        if cards:
            vs_span = (min(tops), max(bottoms))
            vs_y = sum(vs_span)//2
        heading = 'CO-OP BATTLE' if mode == 'coop' else 'TEAM BATTLE'
        subtitle = 'FIGHT TOGETHER / WIN TOGETHER' if mode == 'coop' else 'YOUR SELECTED FIGHTERS'
        detail = None
        people={2:'TWO',3:'THREE',4:'FOUR'}.get(humans,'TWO')
        footer = f'{people} PLAYERS / ONE TEAM' if mode == 'coop' else 'PREPARING YOUR MATCH'
        if mode=='training':
            heading,subtitle,footer='MODDED TRAINING','PRACTICE WITH YOUR SELECTED FIGHTERS','PRACTICE OPTIONS / MOD SETTINGS'
        elif mode=='training_coop':
            heading,subtitle,footer='CO-OP TRAINING',f'{people} PLAYERS / PRACTICE TOGETHER','PRACTICE OPTIONS / MOD SETTINGS'
    return dict(mode=mode, humans=humans, heading=heading, subtitle=subtitle,
                background=BACKGROUNDS[mode], accent=accent, groups=groups,
                cards=cards, detail=detail, footer=footer, columns=columns, vs_y=vs_y,
                vs_span=vs_span)
