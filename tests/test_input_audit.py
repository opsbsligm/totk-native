"""Exercise production SDL audit output, opt-in privacy and the shared event budget."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InputAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(dir=Path.cwd())
        cls.addClassCleanup(cls.directory.cleanup)
        directory = Path(cls.directory.name)
        source = (ROOT / 'src/host/window_sdl.c').read_text()
        start = source.index('static void input_audit_event(')
        end = source.index('\n}\n', start) + 3
        case = directory / 'input-audit.c'
        case.write_text((ROOT / 'tests/input_audit_test.c').read_text() + '\n' + source[start:end])
        cls.executable = directory / 'input-audit'
        cflags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', 'sdl3'], text=True))
        subprocess.run(['clang', '-std=gnu11', '-O1', '-Wall', '-Wextra', '-Werror',
                        *cflags, str(case), '-o', str(cls.executable)], check=True, timeout=60)

    def run_case(self, case, enabled):
        env = dict(os.environ)
        env.pop('TOTK_INPUT_AUDIT', None)
        if enabled:
            env['TOTK_INPUT_AUDIT'] = '1'
        result = subprocess.run([str(self.executable), case], env=env, capture_output=True,
                                text=True, check=True, timeout=10)
        self.assertEqual(result.stdout, '')
        return result.stderr.splitlines()

    def test_default_does_not_record_input(self):
        self.assertEqual(self.run_case('mixed', False), [])

    def test_touch_mouse_keyboard_and_focus_are_observable_without_text(self):
        lines = self.run_case('mixed', True)
        self.assertEqual(len(lines), 12)  # one arming marker and eleven actual events
        self.assertIn('audit enabled; event budget=512; text excluded', lines[0])
        self.assertFalse(any('SHOULD_NEVER_BE_LOGGED' in line for line in lines))
        self.assertEqual(sum(' scancode=' in line for line in lines), 2)
        self.assertEqual(sum('focus event=' in line for line in lines), 2)
        for phase in ('FINGER_DOWN', 'FINGER_MOTION', 'FINGER_UP', 'FINGER_CANCELED'):
            matching = [line for line in lines if 'pointer=' + phase + ' ' in line]
            self.assertEqual(len(matching), 1)
            self.assertIn('window=99 touch=123 finger=456 x=0.25000 y=0.75000 pressure=0.50000', matching[0])
        self.assertTrue(any('pointer=MOUSE_MOTION ' in line and 'x=320.000 y=540.000' in line for line in lines))
        for phase in ('MOUSE_BUTTON_DOWN', 'MOUSE_BUTTON_UP'):
            self.assertTrue(any('pointer=' + phase + ' ' in line and 'which=17 button=1' in line for line in lines))

    def test_motion_flood_has_a_finite_budget_and_explicit_coverage_limit(self):
        lines = self.run_case('flood', True)
        self.assertEqual(len(lines), 514)  # arming, 512 events, one exhaustion marker
        self.assertEqual(sum('pointer=MOUSE_MOTION ' in line for line in lines), 512)
        self.assertEqual(sum('audit budget exhausted' in line for line in lines), 1)
