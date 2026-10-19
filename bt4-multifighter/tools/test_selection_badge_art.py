"""Boot-time UI art must not depend on this PC's fonts or text layout."""
import hashlib
import struct
import unittest
from unittest.mock import patch
import coop_character_select as selection
import player_slot_labels as labels
import selection_badge_art as art
import guest_loading_screen as loading
import fonts
import native_menu_loading as menu_loading


class SelectionBadgeArtTests(unittest.TestCase):
    def test_boot_badges_do_not_open_fonts_or_rasterize_text(self):
        expected=None
        for windows in (True,False):
            for layout in ('basic','raqm'):
                art.packets.cache_clear();selection.packets.cache_clear();labels.packets.cache_clear()
                menu_loading.packets.cache_clear()
                with patch.object(fonts,'WINDOWS',windows), \
                        patch.object(fonts,'truetype',side_effect=AssertionError('System font used')), \
                        patch.object(fonts,'layout_engine',side_effect=AssertionError(layout+' layout used')):
                    en,en_dots=menu_loading.packets();es,es_dots=menu_loading.packets('es')
                    packets=selection.packets()+labels.packets()+(en,*en_dots,es,*es_dots)
                current=hashlib.sha256(b''.join(packets)).hexdigest()
                self.assertEqual(len(packets),62)
                if expected is None:expected=current
                self.assertEqual(current,expected)

    def test_every_badge_uses_the_existing_regional_gif_writer(self):
        for kind,count in (('turn',2),('slots',50),('loading-en',5),('loading-es',5)):
            geometry=art.rectangles(kind)
            self.assertEqual(len(geometry),count)
            art.packets.cache_clear()
            with patch.object(loading,'gif_packet',wraps=loading.gif_packet)as writer:
                packets=art.packets(kind)
            self.assertEqual(writer.call_args_list,[unittest.mock.call(row)for row in geometry])
            self.assertEqual(len(packets),count)
            for row in geometry:
                self.assertTrue(all(0<=x0<x1<=512 and 0<=y0<y1<=448 for x0,y0,x1,y1,_ in row))

    def test_prompt_and_slot_data_stay_inside_their_native_reservations(self):
        self.assertLessEqual(selection.DATA+sum(map(len,selection.packets())),selection.END)
        self.assertLessEqual(labels.DATA+len(labels.data()),labels.END)
        # Each ownership table entry must point to its own exact complete GIF packet.
        table=labels.data();offset=50*8
        for index,packet in enumerate(labels.packets()):
            address,size=struct.unpack_from('<2I',table,index*8)
            self.assertEqual((address,size),(labels.DATA+offset,len(packet)))
            self.assertEqual(table[offset:offset+size],packet);offset+=size
        self.assertEqual(offset,len(table))

    def test_damaged_embedded_art_is_rejected(self):
        art.rectangles.cache_clear()
        count,size,digest,encoded=art._ART['turn']
        with patch.dict(art._ART,turn=(count,size,'0'*64,encoded)):
            with self.assertRaisesRegex(ValueError,'damaged'):art.rectangles('turn')
        self.assertEqual(len(art.rectangles('turn')),2)


if __name__=='__main__':unittest.main()
