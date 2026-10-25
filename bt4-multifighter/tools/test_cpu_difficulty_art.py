"""The CPU selector has the same immutable bytes across languages and hosts."""
import hashlib,struct,unittest
from unittest.mock import patch
import cpu_difficulty_select as menu
import cpu_difficulty_art as art
import fonts,localization,guest_loading_screen as loading

class CpuDifficultyArtTests(unittest.TestCase):
    def test_language_and_platform_do_not_change_selector_code(self):
        expected=None
        for windows in (True,False):
            for language in ('en','es'):
                menu.packets.cache_clear()
                with localization.using(language),patch.object(fonts,'WINDOWS',windows), \
                        patch.object(fonts,'truetype',side_effect=AssertionError('Runtime font access')):
                    pieces=menu.code_pieces()
                current=hashlib.sha256(b''.join(struct.pack('<I',a)+d for a,d in pieces)).hexdigest()
                if expected is None:expected=current
                self.assertEqual(current,expected)

    def test_ten_bounded_plates_and_exact_pointer_table(self):
        images=menu.packets();self.assertEqual(len(images),10)
        self.assertNotEqual(images[:5],images[5:])
        self.assertLessEqual(menu.DATA+sum(map(len,images)),menu.END)
        pieces=dict(menu.code_pieces());offset=menu.DATA
        for index,image in enumerate(images):
            self.assertEqual(struct.unpack_from('<2I',pieces[menu.TABLE],index*8),(offset,len(image)))
            self.assertEqual(image,loading.gif_packet(art.rectangles()[index]));offset+=len(image)

    def test_corrupt_art_is_rejected(self):
        art.rectangles.cache_clear()
        with patch.object(art,'SHA256','0'*64):
            with self.assertRaisesRegex(ValueError,'damaged'):art.rectangles()
        self.assertEqual(len(art.rectangles()),10)

if __name__=='__main__':unittest.main()
