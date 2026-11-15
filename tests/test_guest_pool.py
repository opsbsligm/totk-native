"""Run production guest memory SVCs at the pool boundary and concurrently."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'linux', 'Linux guest memory SVC regression')
class GuestPool(unittest.TestCase):
    def test_shared_pool_boundary_overlap_and_concurrent_requests(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            binary = Path(folder) / 'guest-pool'
            # Production CPU/vector helpers require Clang and its matching compiler-rt.
            subprocess.run(['clang', '-std=gnu17', '-O1', '-g', '-pthread',
                '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                str(ROOT / 'tests/guest_pool_test.c'), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=20)
