"""The CPU texel write path may upload one rectangle only because that rectangle provably equals a whole-level round trip."""
from pathlib import Path
import re, subprocess, tempfile, unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [ROOT / 'tests' / 'nvn_region_test.c', ROOT / 'src' / 'gfx' / 'tex' / 'nvn_deswizzle.c',
           ROOT / 'src' / 'gfx' / 'nvn' / 'nvn_tex.c']

class RegionMove(unittest.TestCase):
    def test_rectangle_move_matches_the_whole_level_round_trip(self):
        # TOTK rewrites a small area of its 5120x5120 map every frame; re-laying out the level took 20-36 ms and made the
        # minimap flash (Deck log, 2026-11-25). Uploading just that area is only correct if it leaves the same bytes.
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as d:
            exe = Path(d) / 'nvn-region'
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-I', str(ROOT / 'src' / 'gfx'),
                            '-I', str(ROOT / 'src' / 'gfx' / 'nvn'), *[str(s) for s in SOURCES], '-o', str(exe)],
                           check=True)
            run = subprocess.run([str(exe)], check=True, capture_output=True, text=True, timeout=300)
            self.assertIn('match the whole-level round trip', run.stdout)
            self.assertNotIn('FAIL', run.stdout)
            self.assertNotIn('SKIP', run.stdout, 'a skipped case would compare nothing')

    def test_the_real_texture_and_its_neighbours_are_all_covered(self):
        # The report names each case; if the map from the Deck log ever stops being exercised, the test would pass while
        # proving nothing about the frame times it was written for.
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as d:
            exe = Path(d) / 'nvn-region'
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-I', str(ROOT / 'src' / 'gfx'),
                            '-I', str(ROOT / 'src' / 'gfx' / 'nvn'), *[str(s) for s in SOURCES], '-o', str(exe)],
                           check=True)
            run = subprocess.run([str(exe)], check=True, capture_output=True, text=True, timeout=300)
            self.assertIn('map BC1 5120x5120', run.stdout)
            for name in ('BC7 1024x1024', 'RGBA8 320x200', 'R8 108x108', '2D array', 'partial GOB column'):
                self.assertIn(name, run.stdout, f'{name}: a format or shape class left unchecked')

class Wiring(unittest.TestCase):
    """The geometry being correct proved nothing the first time: the upload cleared the rectangle before reading it, so the
    fast path never ran and the minimap kept flashing while every test stayed green. These assertions pin the wiring."""

    def setUp(self):
        self.tex = (ROOT / 'src' / 'gfx' / 'vkb_tex.c').read_text()

    def body(self, name):
        # the definition, not a forward declaration: search for the signature that opens a body
        m = re.search(re.escape(name) + r'[^;{]*\)\s*\{', self.tex)
        self.assertIsNotNone(m, f'{name}: no definition found')
        end = self.tex.index('\n}\n', m.end())
        return self.tex[m.start():end]

    def test_the_upload_reads_the_rectangle_it_was_given_not_the_one_it_already_cleared(self):
        upload = self.body('static int region_upload(')
        self.assertIn('vkb_write_rect wr', upload, 'the rectangle has to arrive by value from the caller')
        self.assertNotIn('im->wr', upload,
                         'region_upload reading im->wr reads the value the upload already cleared: the path would never run')

    def test_the_rectangle_is_taken_from_the_image_in_one_step(self):
        upload = self.body('static int tex_upload(')
        self.assertIn('vkb_write_rect wr = vkb_take_write_rect(im)', upload,
                      'read-and-clear in one call, so no ordering mistake can silently disable the fast path')
        self.assertIn('region_upload(cb, im, &L, src,', upload, 'the snapshot has to actually reach the upload')

    def test_only_the_helper_clears_the_rectangle(self):
        cleared = [name for name in ('vkb_take_write_rect', 'region_upload', 'tex_upload')
                   if 'im->wr.valid = 0' in self.body(name) or 'memset(&im->wr' in self.body(name)]
        self.assertEqual(cleared, ['vkb_take_write_rect'],
                         f'{cleared}: clearing it anywhere else means a caller can read "nothing recorded"')
