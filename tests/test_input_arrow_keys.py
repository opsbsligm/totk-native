"""Every key the FIFO and the keyboard can name must reach a Switch button.

The arrow codes 123-126 are what the window layer's keyboard map and the development FIFO (UP/DOWN/
LEFT/RIGHT) both produce.  A code that `button()` does not know silently reports "no button": the input
log confirms the press and the game never moves, which reads as the harness being broken.  These tests
extract the production mapping and pin it against the d-pad bits the SDL gamepad path already uses, so
the two input sources cannot drift apart again.
"""
import re
import subprocess
import shlex
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def extract(source, signature):
    start = source.index(signature)
    end = source.index('\n}\n', start) + 3
    return source[start:end]


class ArrowButtons(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        input_source = (ROOT / 'src/host/overrides_input.c').read_text()
        case = [
            '#include <stdio.h>\n#include <stdint.h>\n#include <string.h>\n',
            extract(input_source, 'static uint64_t button(unsigned code) {'),
            extract(input_source, 'static int script_code(const char *k, size_t n) {'),
            'int main(void) {\n',
            '    unsigned codes[] = {38, 40, 49, 34, 32, 6, 8, 12, 14, 58, 56, 36, 48, 53, 3, 17, 4, 5,\n'
            '                        123, 124, 125, 126, 200};\n',
            '    for (unsigned i = 0; i < sizeof codes / sizeof *codes; i++)\n'
            '        printf("%u %llu\\n", codes[i], (unsigned long long)button(codes[i]));\n',
            '    const char *names[] = {"UP", "DOWN", "LEFT", "RIGHT", "J", "ESCAPE"};\n',
            '    for (unsigned i = 0; i < sizeof names / sizeof *names; i++)\n'
            '        printf("%s %d\\n", names[i], script_code(names[i], strlen(names[i])));\n',
            '    return 0;\n}\n',
        ]
        cls.directory = tempfile.TemporaryDirectory(dir=Path.cwd())
        cls.addClassCleanup(cls.directory.cleanup)
        directory = Path(cls.directory.name)
        source_path = directory / 'arrow-buttons.c'
        source_path.write_text(''.join(case))
        cls.executable = directory / 'arrow-buttons'
        subprocess.run(['clang', '-std=gnu11', '-O1', '-Wall', '-Wextra', '-Werror',
                        str(source_path), '-o', str(cls.executable)], check=True, timeout=60)
        rows = subprocess.run([str(cls.executable)], capture_output=True, text=True,
                              check=True, timeout=10).stdout.split()
        cls.pressed = {}   # key code -> Switch button bit
        cls.named = {}     # FIFO name -> Mac virtual key code
        for i in range(0, len(rows), 2):
            key, value = rows[i], int(rows[i + 1])
            (cls.named if key.isalpha() or key == 'ESCAPE' else cls.pressed)[key] = value

    def test_arrows_drive_the_dpad_with_the_same_bits_as_the_gamepad(self):
        sdl = (ROOT / 'src/host/window_sdl.c').read_text()
        dpad = {}
        for sdl_name, bit in re.findall(r'SDL_GAMEPAD_BUTTON_(DPAD_\w+), (\d+)', sdl):
            dpad[sdl_name] = int(bit)
        self.assertEqual(len(dpad), 4, 'expected four d-pad entries in the SDL mapping')
        for name, arrow in (('DPAD_LEFT', 123), ('DPAD_UP', 126), ('DPAD_RIGHT', 124), ('DPAD_DOWN', 125)):
            self.assertEqual(self.pressed[str(arrow)], dpad[name],
                             f'keyboard/FIFO arrow {arrow} must press the same bit as the gamepad {name}')

    def test_fifo_names_reach_the_arrow_codes_the_window_layer_produces(self):
        self.assertEqual(self.named['LEFT'], 123)
        self.assertEqual(self.named['RIGHT'], 124)
        self.assertEqual(self.named['DOWN'], 125)
        self.assertEqual(self.named['UP'], 126)

    def test_named_buttons_are_unchanged_and_unknown_codes_press_nothing(self):
        self.assertEqual(self.pressed['38'], 1)      # J = A
        self.assertEqual(self.pressed['40'], 2)      # K = B
        self.assertEqual(self.pressed['36'], 1024)   # RETURN = Plus
        self.assertEqual(self.pressed['53'], 2048)   # ESCAPE = Minus
        self.assertEqual(self.pressed['200'], 0)     # unknown codes stay silent
