"""Real Linux reclaim and guest SVC contracts, without private game input."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'linux', 'Linux guest reclamation')
class GuestReclaim(unittest.TestCase):
    def test_residency_zero_refill_host_references_and_accepted_default(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            binary = Path(folder) / 'guest-reclaim'
            # The real 39-bit guest addresses occupy ASan's shadow gap. UBSan
            # stays enabled; the separate retirement/registry fixture uses ASan.
            result = subprocess.run(['clang', '-std=gnu17', '-O1', '-g', '-pthread',
                '-fsanitize=undefined', '-fno-sanitize-recover=all',
                str(ROOT / 'tests/guest_reclaim_test.c'), '-o', str(binary)],
                capture_output=True, text=True, timeout=40)
            self.assertEqual(result.returncode, 0, result.stderr)
            subprocess.run([str(binary)], check=True, timeout=12)
            subprocess.run([str(binary), 'default'], check=True, timeout=12)
