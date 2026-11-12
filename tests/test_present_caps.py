"""Compile the production pacing functions with an application frame-cap getter."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PresentCaps(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'linux', 'Production Linux pacing')
    def test_ui_rates_reach_actual_pacing_without_overriding_other_clock_modes(self):
        source = (ROOT / 'src/gfx/nvn/hle_nvn.c').read_text()
        controls = (ROOT / 'src/host/control_bar.cpp').read_text()
        frame_choices = controls[controls.index('static const char *rates[]'):]
        choices = re.search(r'static const int values\[\]\s*=\s*\{([0-9, ]+)\}', frame_choices)
        self.assertIsNotNone(choices)
        ui_caps = [int(value.strip()) for value in choices.group(1).split(',')]
        self.assertIn(144, ui_caps)
        # Keep the implementation under test in production. The harness replaces
        # only device/context inputs; it does not duplicate the pacing formula.
        begin = source.index('static unsigned present_ticks(const win_t *o) {')
        end = source.index('/* Exercise production policy', begin)
        policy = source[begin:end]
        now_begin = source.index('static int uncapped_now(void) {')
        now_end = source.index('\n/* Opt-in until live scene/clock validation.', now_begin)
        mode_policy = source[now_begin:now_end]
        prefix = r'''
#include <assert.h>
#include <stdint.h>
#include "gfx/nvn/totk_mfx_mode.h"
typedef struct { int interval; } win_t;
static int g_uncapped=1, g_paced_hz=60, g_hz=60, g_display_mode;
static int selected=60, interpolation, deterministic, interval_on=1;
int mfx_enabled(void) { return interpolation; }
static int dm_detclock_enabled(void) { return deterministic; }
static int uncapped_interval_on(void) { return interval_on; }
static void present_cfg(const win_t *w) { (void)w; }
int nd_control_fps_limit(void) { return selected; }
#define LOG(...) ((void)0)
'''
        main = r'''
int main(void) {
 const int caps[]={UI_CAP_VALUES};
 win_t window={.interval=2};
 for(unsigned i=0;i<sizeof caps/sizeof caps[0];i++) {
  selected=caps[i];
  assert(present_period(&window)==1000000000ull/(unsigned)selected);
  assert(present_ticks(&window)==1);
 }
 selected=144;
 g_uncapped=0;assert(present_period(&window)==2000000000ull/60);
 g_uncapped=1;deterministic=1;assert(present_period(&window)==2000000000ull/60);
 deterministic=0;interpolation=MFX_30;assert(present_period(&window)==1000000000ull/30);
 interpolation=MFX_HALF;assert(present_period(&window)==2000000000ull/60);
 interpolation=MFX_OFF;
 const int invalid[]={-1,0,29,145,1000000};
 for(unsigned i=0;i<sizeof invalid/sizeof invalid[0];i++) {
  selected=invalid[i];assert(present_period(&window)==1000000000ull/60);
 }
 return 0;
}
'''.replace('UI_CAP_VALUES', ','.join(map(str, ui_caps)))
        with tempfile.TemporaryDirectory(prefix='totk-present-caps-', dir=Path.cwd()) as folder:
            directory = Path(folder)
            for name, body, succeeds in [('current', policy, True),
                    ('old-bound-negative', policy.replace('cap<=144', 'cap<=120'), False)]:
                with self.subTest(policy=name):
                    path = directory / (name + '.c')
                    binary = directory / name
                    path.write_text(prefix + mode_policy + body + main)
                    subprocess.run(['cc', '-std=gnu17', '-O1', '-I', str(ROOT / 'src'),
                        str(path), '-o', str(binary)], check=True, capture_output=True, text=True, timeout=30)
                    def no_core():
                        import resource
                        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
                    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5,
                                            preexec_fn=no_core)
                    self.assertEqual(result.returncode == 0, succeeds, result.stderr)
