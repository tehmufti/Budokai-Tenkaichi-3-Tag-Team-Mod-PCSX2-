"""Private tag-beam CLUTs; immutable source pixels/packets are never recolored.

Native1AE148/1AE358/1AE1F8 store a texture-header pointer at +8 of each
16-byte parsed texture row. Header+60 is its GS CLUT transfer packet. Each
role receives its own header and packet; texture pixels still reference the
reviewed source. Only IMAGE RGBA bytes change, preserving alpha/GS commands.
"""
import struct
import unicodedata
from prototype import Assembler
import tag_team_rush as tag

BASE, INIT, APPLY = 0x06D7C400, 0x06D7C400, 0x06D7CC00
RECIPES, COLORS, END = 0x06D7D800, 0x06D7DB00, 0x06D7E000
STORAGE, ROLE_STRIDE, STORAGE_END = 0x06DA0000, 0x6000, 0x06DAC000
CELL, PALETTE, PACKET_SIZE = 0x500, 64, 0x480
MAX_TEXTURES = ROLE_STRIDE // CELL
STRIDES = (520,264,136,72)
BLUE=(64,160,255); GOLD=(255,180,32); GREEN=(88,255,48); PURPLE=(178,72,255); PINK=(255,80,180)


def character_color(info, character=None, *, bt4=None):
    """Explicit local tag colors; unknown fighters use neutral gold.

    This is a tag-attack palette choice, not a claim to replace every native
    move's individual color. Name lookup follows the selected disc's roster.
    """
    if character is None and isinstance(info,dict):character=info.get('character_id')
    if type(character)is int and 0<=character<256:
        import tag_beam_profiles
        if bt4 is None:
            from native_map import SERIAL
            bt4=SERIAL=='SLUS-21978'
        chosen=tag_beam_profiles.profile(character,bt4=bt4)['color']
        if chosen is not None:return chosen
    text=' '.join(str(info.get(k,'')) for k in ('name','base_name','form')) if isinstance(info,dict) else str(info)
    name=''.join(x for x in unicodedata.normalize('NFKD',text).casefold() if x.isalnum())
    if any(x in name for x in ('gokublack','blackgoku','zamasu','zamas','freeza','frieza','freezer','cooler','kingcold','cold','beerus','bills','janemba','hit')):return PURPLE
    if any(x in name for x in ('broly','kale','kefla','cell','celula')):return GREEN
    if any(x in name for x in ('piccolo','pikoro','piccoro')):return (255,158,24)
    if any(x in name for x in ('majinbuu','superbuu','kidbuu','buu','buuhan','buutenks','majinbu','superbu','buformapura')):return PINK
    if any(x in name for x in ('goku','gogeta','vegito','vegetto','roshi','kamesennin','goten','krillin','krilin','yamcha','pan')):return BLUE
    return GOLD


def recipe(resource, resource_address, names):
    """Read the exact native shape traversal; no offsets guessed from pixels."""
    import tag_rush_assets as assets
    import model_assets as model
    assets.validate_native_beam(resource,bytes(640))
    entries=struct.unpack_from('<%dI'%struct.unpack_from('<I',resource)[0],resource,4)
    script=model.package_entry(resource,4); result=[];entry=5;group_counts=[0]*4
    for i in range(script[4]):
        kind,commands,shapes=script[64+32*i:67+32*i]
        group=3 if kind==2 else 1 if kind in(5,10,12,15,16,17,18) else 2 if kind==9 else 0
        if not kind:continue
        for shape_index in range(shapes):
            shape=model.package_entry(resource,entry);entry+=1
            count,table_words=struct.unpack_from('<2I',shape);table=table_words*4
            for texture in range(count):
                off=table+64*texture;h=struct.unpack_from('<16I',shape,off)
                if h[3]!=PACKET_SIZE or (h[12]>>20)&63!=19:raise ValueError('Tag beam color texture format changed')
                pixels,w,hgt=model._image_packet(shape,h[1]*4,h[3])
                if (w,hgt,len(pixels))!=(16,16,1024):raise ValueError('Tag beam CLUT format changed')
                source=resource_address+(entries[entry-2]&~3)+off
                palette=resource_address+(entries[entry-2]&~3)+h[1]*4
                result.append((group,group_counts[group]+shape_index,texture,source,palette))
        group_counts[group]+=shapes
        entry+=commands*(1 if kind in(2,14) else 2)
    if tuple(group_counts)!=(1,6,0,1) or not 0<len(result)<=MAX_TEXTURES:raise ValueError('Tag beam color shape recipe changed')
    table=bytearray(256*4)
    for character,info in names.items():
        if type(character)is int and 0<=character<256:
            r,g,b=character_color(info,character);struct.pack_into('<I',table,4*character,r|(g<<8)|(b<<16))
    return dict(textures=tuple(result),colors=bytes(table))


def _plan(plan):
    rows=tuple(plan.get('textures',()))
    if not 0<len(rows)<=MAX_TEXTURES or len(plan.get('colors',b''))!=1024:raise ValueError('Invalid private beam color plan')
    for group,index,texture,source,palette in rows:
        if group not in range(4) or not 0<=index<(1,6,0,1)[group] or not 0<=texture<32 or source%16 or palette%16 or not 0x06D10000<=source<palette<palette+PACKET_SIZE<=0x06D60000:
            raise ValueError('Invalid private beam texture record')
    return rows


def init_code(count):
    """a0 exact FX row -> clone headers/CLUTs and redirect PRIVATE arrays."""
    import tag_rush_effects as fx
    a=Assembler(INIT);tag.save(a);a.move(16,4)
    a.li(8,fx.ROWS);a.move(17,0);a.branch(4,16,8,'row');a.li(8,fx.ROWS+fx.STRIDE);a.branch(5,16,8,'no');a.li(17,1)
    a.label('row');a.li(18,STORAGE);a.branch(4,17,0,'base');a.addiu(18,18,ROLE_STRIDE)
    a.label('base');a.li(19,RECIPES);a.move(20,0)
    a.label('texture');a.lw(8,19);a.r(0,8,0,8,2);a.r(0x21,8,8,16);a.lw(21,8,fx.DESC+764)
    a.lw(8,19,4);a.r(0x21,21,21,8);a.lw(8,19,8);a.r(0x21,21,21,8)
    a.lw(22,19,12);a.lw(8,21,8);a.branch(5,8,22,'no')
    a.lw(8,22,60);a.lw(9,19,16);a.branch(5,8,9,'no')
    a.move(8,22);a.move(9,18);a.li(10,16)
    a.label('header');a.lw(11,8);a.sw(11,9);a.addiu(8,8,4);a.addiu(9,9,4);a.addiu(10,10,-1);a.branch(5,10,0,'header')
    a.lw(8,22,60);a.addiu(9,18,PALETTE);a.li(10,PACKET_SIZE//4)
    a.label('packet');a.lw(11,8);a.sw(11,9);a.addiu(8,8,4);a.addiu(9,9,4);a.addiu(10,10,-1);a.branch(5,10,0,'packet')
    a.addiu(8,18,PALETTE);a.sw(8,18,60);a.sw(18,21,8)
    a.addiu(18,18,CELL);a.addiu(19,19,32);a.addiu(20,20,1);a.li(8,count);a.branch(5,20,8,'texture')
    a.li(2,1);a.jump('done');a.label('no');a.move(2,0);a.label('done');tag.restore(a,2);a.jr()
    b=a.finish();assert len(b)<=APPLY-INIT;return b


def apply_code(count):
    """a0 exact FX row; fresh colors from immutable source at each spawn."""
    import tag_rush_effects as fx
    a=Assembler(APPLY);tag.save(a);a.move(16,4);a.li(8,fx.ROWS);a.li(18,STORAGE)
    a.branch(4,16,8,'row');a.li(8,fx.ROWS+fx.STRIDE);a.branch(5,16,8,'no');a.addiu(18,18,ROLE_STRIDE)
    a.label('row');a.lw(8,16,fx.R['source_character']);a.i(11,9,8,256);a.li(17,GOLD[0]|GOLD[1]<<8|GOLD[2]<<16)
    a.branch(4,9,0,'color');a.r(0,8,0,8,2);a.li(9,COLORS);a.r(0x21,8,8,9);a.lw(8,8);a.branch(4,8,0,'color');a.move(17,8)
    a.label('color');a.li(19,RECIPES);a.move(20,0)
    a.label('texture');a.lw(8,19,12);a.lw(21,8,60);a.lw(9,19,16);a.branch(5,21,9,'no');a.addiu(21,21,96);a.addiu(22,18,PALETTE+96);a.li(23,256)
    a.label('pixel');a.i(36,8,21,0);a.i(36,9,21,1);a.i(36,10,21,2);a.move(11,8);a.move(12,8)
    for reg in (9,10):
        label='min%d'%reg;a.r(0x2B,13,reg,11);a.branch(4,13,0,label);a.move(11,reg);a.label(label)
        label='max%d'%reg;a.r(0x2B,13,12,reg);a.branch(4,13,0,label);a.move(12,reg);a.label(label)
    a.r(0x23,12,12,11);a.move(14,17)
    for off in range(3):
        a.i(12,13,14,255);a.r(0x19,0,12,13);a.r(0x12,13,0,0);a.addiu(13,13,127);a.li(15,255)
        a.r(0x1B,0,13,15);a.r(0x12,13,0,0);a.r(0x21,13,13,11);a.i(40,13,22,off);a.r(2,14,0,14,8)
    a.i(36,8,21,3);a.i(40,8,22,3)
    a.addiu(21,21,4);a.addiu(22,22,4);a.addiu(23,23,-1);a.branch(5,23,0,'pixel')
    a.addiu(18,18,CELL);a.addiu(19,19,32);a.addiu(20,20,1);a.li(8,count);a.branch(5,20,8,'texture')
    a.li(2,1);a.jump('done');a.label('no');a.move(2,0);a.label('done');tag.restore(a,2);a.jr()
    b=a.finish();assert len(b)<=RECIPES-APPLY;return b


def pieces(plan):
    rows=_plan(plan)
    raw=b''.join(struct.pack('<8I',g,STRIDES[g]*i,16*t,p,pal,0,0,0) for g,i,t,p,pal in rows)
    result=[(INIT,init_code(len(rows))),(APPLY,apply_code(len(rows))),(RECIPES,raw),(COLORS,plan['colors']),(STORAGE,bytes(STORAGE_END-STORAGE))]
    assert len(raw)<=COLORS-RECIPES and COLORS+1024<=END
    return result
