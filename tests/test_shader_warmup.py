"""The background shader pass reports what it is doing (src/gfx/shader_warmup.c).

The control bar's line, bar, and stop button all read this one file, so the state machine it shows is
tested against the production source, not a copy: an under-counted pass once read as "complete" while
the game was still stuttering, which is the failure this guard exists to keep out.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ShaderWarmup(unittest.TestCase):
    def test_report_state_machine(self):
        # The pass runs on its own thread; the include is the production translation unit, which pulls in
        # nothing else, so the test links exactly the code the game runs.
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as d:
            exe = Path(d) / 'shader-warmup'
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pthread',
                            '-I', str(ROOT / 'src/gfx'),
                            str(ROOT / 'tests/shader_warmup_test.c'), '-o', str(exe)],
                           check=True, cwd=ROOT, timeout=120)
            result = subprocess.run([str(exe)], check=True, cwd=ROOT, timeout=60,
                                    capture_output=True, text=True)
            self.assertIn('shader warm-up report ok', result.stdout)

    def test_the_control_bar_shows_the_pass_it_reports(self):
        # A block that reads a copy of the state would pass the test above while the bar stayed blind,
        # so the exact entry points the block calls are asserted here as well.
        bar = (ROOT / 'src/host/control_bar.cpp').read_text(encoding='utf-8')
        warm = (ROOT / 'src/gfx/vkb_shader.c').read_text(encoding='utf-8')
        for call in ('nd_shader_warm_state()', 'nd_shader_warm_share()', 'nd_shader_warm_cancel()'):
            self.assertIn(call, bar, call + ' missing from the control bar')
        for call in ('nd_shader_warm_begin', 'nd_shader_warm_count', 'nd_shader_warm_step',
                     'nd_shader_warm_cancel_requested', 'nd_shader_warm_finish'):
            self.assertIn(call + '(', warm, call + ' missing from the ahead pass')


if __name__ == '__main__':
    unittest.main()
