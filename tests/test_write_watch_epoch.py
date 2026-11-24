"""The shared write-watch epoch, compiled and run against a fake write watch."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WriteWatchEpoch(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc'), 'C compiler required')
    def test_one_look_per_submission_and_no_write_is_lost(self):
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / 'write-watch-epoch'
            result = subprocess.run(
                ['cc', '-std=gnu17', '-O1', '-g', '-pthread', '-Wall', '-Wextra', '-Werror',
                 '-fsanitize=undefined', '-fno-sanitize-recover=all',
                 str(ROOT / 'tests/write_watch_epoch_test.c'), str(ROOT / 'src/gfx/nvn/nvn_dirty_win.c'),
                 '-o', str(binary)],
                capture_output=True, text=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stderr)
            run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn('OK', run.stdout)


if __name__ == '__main__':
    unittest.main()
