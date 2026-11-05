"""Check measured game time at 30/60fps, jitter, and pause discontinuities."""
import ctypes
import math
from pathlib import Path
import subprocess
import tempfile
import unittest

class ClockTests(unittest.TestCase):
    def test_frame_rate_does_not_change_game_speed(self):
        source=Path(__file__).resolve().parents[1]/'src/host/nd_totk_timing.c'
        with tempfile.TemporaryDirectory(prefix='totk-clock-',dir=Path.cwd()) as tmp:
            lib=Path(tmp)/'clock.so'
            subprocess.run(['cc','-std=c11','-shared','-fPIC',str(source),'-o',str(lib)],check=True)
            clock=ctypes.CDLL(str(lib))
            clock.runtime_frame_step_update.argtypes=[ctypes.c_uint64]
            clock.nd_totk_step.argtypes=[ctypes.c_float]
            clock.nd_totk_step.restype=ctypes.c_float
            now=1_000_000_000
            clock.runtime_frame_step_update(now)
            for hz in [30,60,90,120,60,30]:
                dt=round(1e9/hz)
                for _ in range(10):
                    now+=dt;clock.runtime_frame_step_update(now)
                seconds=0
                for _ in range(hz*3):
                    now+=dt;clock.runtime_frame_step_update(now)
                    seconds+=clock.nd_totk_step(1)
                self.assertAlmostEqual(seconds,3.0,places=4)
                self.assertAlmostEqual(clock.nd_totk_step(30),30/hz,places=5)
            # Sub-millisecond duplicate presents and a pause do not create a huge step.
            before=clock.nd_totk_step(1)
            now+=100;clock.runtime_frame_step_update(now)
            self.assertEqual(clock.nd_totk_step(1),before)
            now+=5_000_000_000;clock.runtime_frame_step_update(now)
            self.assertEqual(clock.nd_totk_step(1),before)
            # A 100ms hitch is clamped to the upstream physics maximum of 1/15s.
            now+=100_000_000;clock.runtime_frame_step_update(now)
            self.assertAlmostEqual(clock.nd_totk_step(1),1/15,places=6)
            # Zero/backwards time is ignored and cannot publish NaN or negative time.
            clock.runtime_frame_step_update(now-1)
            self.assertTrue(math.isfinite(clock.nd_totk_step(1)))
            self.assertGreater(clock.nd_totk_step(1),0)

if __name__=='__main__':unittest.main()
