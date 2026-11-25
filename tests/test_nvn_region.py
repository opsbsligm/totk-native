"""The CPU texel write path may upload one rectangle only because that rectangle provably equals a whole-level round trip."""
from pathlib import Path
import subprocess, tempfile, unittest

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
