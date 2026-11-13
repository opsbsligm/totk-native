"""Execute the overlay's production interval accumulator with deterministic clocks."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FrameMetrics(unittest.TestCase):
    @unittest.skipUnless(shutil.which('c++'), 'C++ compiler required')
    def test_frame_rates_slow_frames_and_clock_boundaries(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            binary = Path(directory) / 'frame-metrics'
            subprocess.run([
                'c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-pedantic',
                '-I', str(ROOT / 'src/host'),
                str(ROOT / 'tests/native_frame_metrics_test.cpp'),
                '-o', str(binary),
            ], check=True, timeout=30)
            subprocess.run([str(binary)], check=True, timeout=10)
