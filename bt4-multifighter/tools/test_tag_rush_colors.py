# Native execution tests use only the developer's own extracted executable.
from pathlib import Path as _TestPath
import unittest as _TestUnit
from native_map import elf_path as _test_elf_path
if not _test_elf_path(_TestPath(__file__).resolve().parents[1]).is_file():
    raise _TestUnit.SkipTest('An extracted game executable is required for native tag tests')

import struct
import unittest
import tag_rush_colors as colors
import tag_rush_effects as fx
from test_tag_rush_effects import machine
from test_tag_rush_camera import run

SOURCE=0x06D30000
PALETTE=0x06D31000
ARRAY=fx.ARENAS


def configured():
    c=machine();table=bytearray(1024)
    for ident,name in ((20,'Piccolo'),(22,'Broly')):
        r,g,b=colors.character_color(name);struct.pack_into('<I',table,4*ident,r|g<<8|b<<16)
    plan=dict(textures=((0,0,0,SOURCE,PALETTE),),colors=bytes(table))
    for p,b in colors.pieces(plan):c.write(p,b)
    c.write(SOURCE,bytes(64));c.w(SOURCE+60,PALETTE);c.w(SOURCE+56,0x06D32000)
    packet=bytearray([0x7A]*colors.PACKET_SIZE)
    for i in range(256):packet[96+4*i:100+4*i]=bytes((20,80,220,i%128))
    packet[96:100]=bytes((255,255,255,100));packet[100:104]=bytes((50,50,50,20))
    c.write(PALETTE,packet)
    for index in range(2):
        row=fx.ROWS+index*fx.STRIDE;array=ARRAY+index*fx.ARENA_SIZE
        c.w(row+fx.DESC+764,array);c.w(array+8,SOURCE);c.w(row+fx.R['source_character'],20+index*2)
        c.r[4]=row;run(c,colors.INIT);assert c.r[2]==1
    return c


class ColorTests(unittest.TestCase):
    def test_purple_charge_parameters_are_private_and_normal_pairs_restore_the_source(self):
        import tag_team_rush as tag
        c=configured();source=SOURCE+0x4000;destination=colors.PARAM_STORAGE;field=fx.DESC+448+8
        raw=struct.pack('<4f',10.,20.,240.,80.)*20;c.write(source,raw);c.write(destination,b'P'*len(raw))
        c.write(colors.PARAM_RECIPES,struct.pack('<4I',field,source,destination,0));c.w(fx.ROWS+field,source)
        c.write(colors.APPLY,colors.apply_code(1,1))
        for variant,wanted in((6,destination),(5,source),(6,destination),(0,source)):
            c.w(tag.CONTROL+tag.C['variant'],variant);c.r[4]=fx.ROWS;run(c,colors.APPLY)
            self.assertEqual(c.r[2],1);self.assertEqual(c.u(fx.ROWS+field),wanted)
            self.assertEqual(c.read(source,len(raw)),raw)
        c.w(fx.ROWS+field,123);c.r[4]=fx.ROWS;run(c,colors.APPLY)
        self.assertEqual(c.r[2],0);self.assertEqual(c.u(fx.ROWS+field),123)

    def test_character_families_and_unknown_fallback(self):
        self.assertEqual(colors.character_color('Goku - End'),colors.BLUE)
        self.assertEqual(colors.character_color('Goku Black Rose'),colors.PURPLE)
        self.assertEqual(colors.character_color('Freezer'),colors.PURPLE)
        self.assertEqual(colors.character_color('Broly'),colors.GREEN)
        self.assertEqual(colors.character_color('Piccolo'),(255,158,24))
        self.assertEqual(colors.character_color('Unknown new fighter'),colors.GOLD)

    def test_reviewed_spanish_beam_names_keep_character_colors(self):
        cases=(('Piccoro (Inicio)',(255,158,24)),('Piccoro Daimaku',(255,158,24)),
               ('Zamas (Fusion)',colors.PURPLE),('Majin Bu',colors.PINK),
               ('Súper Bu',colors.PINK),('Bu (Forma Pura)',colors.PINK),
               ({'base_name':'Súper Bu','form':'Gotenks absorbido'},colors.PINK))
        for name,want in cases:
            with self.subTest(name=name):self.assertEqual(colors.character_color(name),want)
        self.assertEqual(colors.character_color('Burter'),colors.GOLD,'Bu is not a general substring rule')

    def test_actual_bt4_english_spanish_rosters_keep_admission_and_color_parity(self):
        from pathlib import Path
        from unittest.mock import patch
        from iso_compatibility.disc import Disc,package
        from iso_compatibility.labels import unpack_bpe,english_label
        import tag_rush_install as installer
        paths=[Path(__file__).resolve().parents[2]/'games'/name for name in
               ('SLUS_219.78.DBZBT4B14REV2ENG.iso','SLUS_219.78.DBZBT4B14REV2.iso')]
        if not all(path.is_file() for path in paths):self.skipTest('Local English and Spanish BT4 discs unavailable')
        def parts(blob):return [blob[start:end] for start,end in package(blob)]
        results=[]
        for path in paths:
            with Disc(path) as disc:
                ui=parts(unpack_bpe(parts(disc.read(451))[1]))
                names,forms=parts(ui[29]),parts(ui[30])
            table={i:dict(base_name=english_label(names[i]),form=english_label(forms[i])) for i in range(250)}
            roster=[dict(character=i,supported=True) for i in table if table[i]['base_name']]
            with patch('character_names.character_table',return_value=table):
                (_,flags),_=installer.admission_block({'blocks':[(0x06D10000,bytes(16))]},roster)
            results.append((flags,[colors.character_color(table[i]) for i in table],
                            [row['character'] for row in roster]))
        self.assertEqual(results[0][0],results[1][0],'translated labels must not change the finisher variant')
        self.assertEqual(results[0][2],results[1][2],'both languages must expose the same named roster')
        for i,(english,spanish) in enumerate(zip(results[0][1],results[1][1])):
            with self.subTest(character=i):self.assertEqual(english,spanish)

    def test_two_native_descriptors_get_independent_headers_and_cluts(self):
        c=configured();before=c.read(SOURCE,64);packet=c.read(PALETTE,colors.PACKET_SIZE)
        for i in range(2):
            private=colors.STORAGE+i*colors.ROLE_STRIDE;array=ARRAY+i*fx.ARENA_SIZE
            self.assertEqual(c.u(array+8),private)
            self.assertEqual(c.u(private+56),0x06D32000)
            self.assertEqual(c.u(private+60),private+colors.PALETTE)
            self.assertEqual(c.read(private+colors.PALETTE,colors.PACKET_SIZE),packet)
        for i in range(2):c.r[4]=fx.ROWS+i*fx.STRIDE;run(c,colors.APPLY)
        a=colors.STORAGE+colors.PALETTE;b=a+colors.ROLE_STRIDE
        self.assertNotEqual(c.read(a+104,4),c.read(b+104,4))
        self.assertEqual(c.read(SOURCE,64),before);self.assertEqual(c.read(PALETTE,colors.PACKET_SIZE),packet)
        for p in (a,b):
            self.assertEqual(c.read(p,96),packet[:96]);self.assertEqual(c.read(p+1120,32),packet[1120:])
            self.assertEqual(c.read(p+96,8),packet[96:104],'white cores and neutral shading stay intact')
            self.assertEqual(c.read(p+96,1024)[3::4],packet[96:1120][3::4],'alpha is untouched')

    def test_subsequent_spawn_uses_original_palette_and_current_character(self):
        c=configured();c.r[4]=fx.ROWS;run(c,colors.APPLY)
        first=c.read(colors.STORAGE+colors.PALETTE,colors.PACKET_SIZE)
        c.w(fx.ROWS+fx.R['source_character'],22);c.r[4]=fx.ROWS;run(c,colors.APPLY)
        self.assertEqual(c.read(colors.STORAGE+colors.PALETTE+104,4),bytes((89,220,58,2)))
        c.w(fx.ROWS+fx.R['source_character'],20);c.r[4]=fx.ROWS;run(c,colors.APPLY)
        self.assertEqual(c.read(colors.STORAGE+colors.PALETTE,colors.PACKET_SIZE),first)

    def test_blue_pair_keeps_vegeta_gold_and_trunks_pair_keeps_both_purple(self):
        import tag_team_rush as tag
        for variant,wanted in ((5,(colors.BLUE,colors.GOLD)),(6,(colors.PURPLE,colors.PURPLE))):
            c=configured();c.w(tag.CONTROL+tag.C['variant'],variant)
            for role,color in enumerate(wanted):
                row=fx.ROWS+role*fx.STRIDE;c.r[4]=row;run(c,colors.APPLY)
                self.assertEqual(c.r[2],1)
                got=c.read(colors.STORAGE+role*colors.ROLE_STRIDE+colors.PALETTE+104,3)
                expected=bytes(20+(200*channel+127)//255 for channel in color)
                self.assertEqual(got,expected,(variant,role))

    def test_unknown_ids_use_gold_and_invalid_rows_cannot_write(self):
        c=configured();c.w(fx.ROWS+fx.R['source_character'],999);c.r[4]=fx.ROWS;run(c,colors.APPLY)
        self.assertEqual(c.read(colors.STORAGE+colors.PALETTE+104,3),bytes((220,161,45)))
        before=c.read(colors.STORAGE,colors.STORAGE_END-colors.STORAGE);c.r[4]=fx.ROWS+4;run(c,colors.APPLY)
        self.assertEqual(c.r[2],0);self.assertEqual(c.read(colors.STORAGE,len(before)),before)

    def test_parser_corruption_does_not_publish_private_pointer(self):
        c=configured();c.w(ARRAY+8,0x12345678);c.r[4]=fx.ROWS;run(c,colors.INIT)
        self.assertEqual(c.r[2],0);self.assertEqual(c.u(ARRAY+8),0x12345678)

    def test_source_palette_pointer_corruption_is_refused(self):
        c=configured();before=c.read(colors.STORAGE,colors.STORAGE_END-colors.STORAGE)
        c.w(SOURCE+60,0x300);c.r[4]=fx.ROWS;run(c,colors.APPLY)
        self.assertEqual(c.r[2],0);self.assertEqual(c.read(colors.STORAGE,len(before)),before)

    def test_disc_recipe_only_points_to_clut_headers_in_reviewed_resource(self):
        from pathlib import Path
        import tag_rush_assets as assets
        import model_assets
        name=('SLUS_219.78.DBZBT4B14REV2ENG.iso' if 'bt4' in str(Path(__file__)) else 'Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso')
        path=Path(__file__).resolve().parents[2]/'games'/name
        if not path.is_file():self.skipTest('Local reviewed disc unavailable')
        resource=assets.read_native_beam_asset(path)['resource']
        plan=colors.recipe(resource,SOURCE,{0:'Goku',23:'Piccolo'})
        self.assertEqual(len(plan['command_colors']),2)
        index,source,blob=plan['command_colors'][0]
        self.assertEqual(index,0)
        original=resource[source-SOURCE:source-SOURCE+len(blob)]
        changed={at for at,(a,b)in enumerate(zip(original,blob))if a!=b}
        keys=tuple(base+delta for base in(12,372,492,852)for delta in(0,16,32))
        self.assertEqual(changed,{at+c for at in keys for c in(0,1)})
        for at in keys:self.assertEqual(blob[at:at+3],bytes(colors.PURPLE));self.assertEqual(blob[at+3],original[at+3])
        _,source,blob=plan['command_colors'][1]
        original=resource[source-SOURCE:source-SOURCE+len(blob)]
        self.assertEqual({at for at,(a,b)in enumerate(zip(original,blob))if a!=b},{1328,1329})
        self.assertEqual(len(plan['textures']),18)
        locations=[]
        for group,index,texture,header,palette in plan['textures']:
            h=struct.unpack_from('<16I',resource,header-SOURCE)
            packet=resource[palette-SOURCE:palette-SOURCE+colors.PACKET_SIZE]
            rgba,w,hgt=model_assets._image_packet(packet,0,colors.PACKET_SIZE)
            self.assertEqual((len(rgba),w,hgt),(1024,16,16))
            self.assertEqual(h[3],colors.PACKET_SIZE)
            locations.append((group,index,texture))
        self.assertEqual(len(set(locations)),18)
        self.assertLess(sum(len(data) for _,data in colors.pieces(plan)),61000)

    def test_native_cache_round_trip_keeps_audio_and_private_color_programs_identical(self):
        from pathlib import Path
        from unittest.mock import patch
        import tag_rush_assets as assets
        import tag_rush_audio as audio
        import tag_rush_install as installer
        name=('SLUS_219.78.DBZBT4B14REV2ENG.iso' if 'bt4' in str(Path(__file__)) else 'Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso')
        path=Path(__file__).resolve().parents[2]/'games'/name
        if not path.is_file():self.skipTest('Local reviewed disc unavailable')
        original=assets.build_assets(path,include_beam=True)
        cached=installer._asset_plan(installer._asset_payload(original))
        self.assertNotEqual(list(original['variants']),list(cached['variants']))
        self.assertEqual(audio.pieces(original),audio.pieces(cached))
        names={0:{'name':'Goku'},23:{'name':'Piccolo'},90:{'name':'Frieza'},150:{'name':'Broly'}}
        with patch('character_names.character_table',return_value=names):
            first=installer.with_beam_colors(original)
        with patch('character_names.character_table',return_value=dict(reversed(tuple(names.items())))):
            second=installer.with_beam_colors(cached)
        self.assertEqual(first['beam_asset']['color_plan'],second['beam_asset']['color_plan'])
        self.assertEqual(fx.pieces(first['beam_asset']),fx.pieces(second['beam_asset']))
        self.assertNotIn('color_plan',original['beam_asset'],'derived palette plan must not enter cached assets')
        self.assertNotIn('color_plan',cached['beam_asset'])

    def test_real_cache_miss_and_hit_both_pass_complete_playtest_review(self):
        from pathlib import Path
        from unittest.mock import patch
        import tempfile
        import tag_rush_assets as assets
        import tag_rush_audio as audio
        import tag_rush_install as installer
        name=('SLUS_219.78.DBZBT4B14REV2ENG.iso' if 'bt4' in str(Path(__file__)) else 'Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso')
        path=Path(__file__).resolve().parents[2]/'games'/name
        if not path.is_file():self.skipTest('Local reviewed disc unavailable')
        with tempfile.TemporaryDirectory(prefix='tag-rush-cache-') as folder:
            with patch.object(installer,'CACHE_ROOT',Path(folder)),patch.object(assets,'build_assets',wraps=assets.build_assets) as build:
                first,key1=installer.cached_assets(path)
                installer.review_playtest_assets(first,iso=path)
                second,key2=installer.cached_assets(path)
                installer.review_playtest_assets(second,iso=path)
                self.assertEqual(build.call_count,1,'second preparation must read its serialized cache')
                self.assertEqual(key1,key2)
                self.assertEqual(first,second)
                self.assertEqual(audio.pieces(first),audio.pieces(second))
                one=installer.with_beam_colors(first);two=installer.with_beam_colors(second)
                self.assertEqual(fx.pieces(one['beam_asset']),fx.pieces(two['beam_asset']))

    def test_color_helper_reservations_do_not_overlap_voice_camera_or_choreography(self):
        import tag_rush_voices as voices
        self.assertLessEqual(colors.END,voices.BASE)
        self.assertLessEqual(colors.STORAGE_END,0x06DB0000)
        self.assertEqual(colors.MAX_TEXTURES,19)

if __name__=='__main__':unittest.main()
