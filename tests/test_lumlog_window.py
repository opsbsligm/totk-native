"""Image capture starts only after a sustained gameplay render window."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LumlogWindow(unittest.TestCase):
    def test_world_capture_waits_through_menus_and_one_heavy_transition(self):
        source = (ROOT / 'src/gfx/vkb_tex.c').read_text()
        body = source[source.index('static int lumlog_window('):source.index('void vkb_tex_lumlog(')]
        prefix = r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
static uint64_t draws;
static uint64_t vkb_draw_count(void) { return draws; }
'''
        driver = r'''
int main(int argc, char **argv) {
    assert(argc == 2);
    for (uint64_t present = 1; present <= 240; ++present) {
        if ((present >= 101 && present <= 140) || present >= 142)
            draws += 7000;
        else
            draws += 120;
        int expected = 0;
        if (strcmp(argv[1], "world") == 0)
            expected = present == 201 || present == 202;
        if (strcmp(argv[1], "absolute") == 0)
            expected = present == 130 || present == 131;
        assert(lumlog_window(present) == expected);
    }
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='totk-lumlog-', dir=Path.cwd()) as directory:
            root = Path(directory)
            probe, binary = root / 'capture.c', root / 'capture'
            probe.write_text(prefix + body + driver)
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', str(probe), '-o', str(binary)],
                           check=True, timeout=20)
            for arg, value in (('world', 'world:2'), ('absolute', '130:2'), ('disabled', 'world:0')):
                with self.subTest(mode=arg):
                    subprocess.run([str(binary), arg], env=dict(os.environ, TOTK_LUMLOG=value),
                                   check=True, timeout=5)
