"""A/B routing covers every source, not just a physical controller.

`pad_states` used to feed only the controller's two A/B bits through the menu policy, so a key the window
layer injected (the keyboard, and the development FIFO the harness writes) reached the game unswapped. With
the Deck's menu swap in place that made the harness's confirm key land as cancel and left every automated run
on the save-selection screen. These tests extract the production seam and run it, so the ordering cannot
drift back without a failure here.
"""
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


class PadRouting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / 'src/host/overrides_input.c').read_text()
        cls.case = [
            '#include <stdio.h>\n#include <stdint.h>\n#include <stdbool.h>\n#include "menu_confirm.h"\n',
            extract(source, 'static uint64_t nd_pad_route_a_b('),
            'int main(void) {\n'
            # name, menu, keys, pad, expected buttons
            '  static const struct { const char *what; bool menu; uint64_t keys; uint64_t pad; uint64_t want; } cases[] = {\n'
            '    {"world keyboard A stays A", false, 2, 0, 2},\n'
            '    {"world pad A stays A", false, 0, 2, 2},\n'
            '    {"menu keyboard A cancels", true, 2, 0, 1},\n'
            '    {"menu pad A cancels", true, 0, 2, 1},\n'
            '    {"menu keyboard B confirms", true, 1, 0, 2},\n'
            '    {"menu pad B confirms", true, 0, 1, 2},\n'
            '    {"menu A plus shoulder keeps the shoulder", true, 2|16, 0, 1|16},\n'
            '    {"menu A held from both sources is one click", true, 2, 2, 1},\n'
            '    {"other buttons never swap", false, 1|2|4|8, 0, 1|2|4|8},\n'
            '  };\n'
            '  for (unsigned i = 0; i < sizeof cases / sizeof *cases; i++) {\n'
            '    NdMenuConfirm state = {0};\n'
            '    if (cases[i].menu) nd_pad_route_a_b(&state, true, 0, 0);   /* menu already open, keys at rest */\n'
            '    uint64_t got = nd_pad_route_a_b(&state, cases[i].menu, cases[i].keys, cases[i].pad);\n'
            '    printf("%u %s %llu\\n", i, got == cases[i].want ? "ok" : "wrong", (unsigned long long)got);\n'
            '  }\n'
            '  /* Crossing the menu boundary with a key held must not fire: it is blocked until released. */\n'
            '  NdMenuConfirm state = {0};\n'
            '  printf("held %llu\\n", (unsigned long long)nd_pad_route_a_b(&state, false, 2, 0));\n'
            '  printf("enter %llu\\n", (unsigned long long)nd_pad_route_a_b(&state, true, 2, 0));\n'
            '  printf("still_held %llu\\n", (unsigned long long)nd_pad_route_a_b(&state, true, 2, 0));\n'
            '  printf("released %llu\\n", (unsigned long long)nd_pad_route_a_b(&state, true, 0, 0));\n'
            '  printf("pressed_again %llu\\n", (unsigned long long)nd_pad_route_a_b(&state, true, 2, 0));\n'
            '  return 0;\n}\n',
        ]

    def test_routing_table_and_boundary_hold(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            source = root / 'check.c'
            binary = root / 'check'
            source.write_text(''.join(self.case) +
                              extract((ROOT / 'src/host/menu_confirm.c').read_text(),
                                      'uint64_t nd_menu_confirm('))
            compile_case = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-I', str(ROOT / 'src/host'),
                            str(source), '-o', str(binary)]
            subprocess.run(compile_case, check=True)
            rows = subprocess.run([str(binary)], check=True, capture_output=True, text=True).stdout.splitlines()
        rows = {row.split()[0]: row.split()[1:] for row in rows}
        for index in range(9):
            self.assertEqual('ok', rows[str(index)][0],
                             f'routing case {index} returned {rows[str(index)][1:]}')
        # A key down before the menu opened, still down inside it, is ignored until it is let go.
        self.assertEqual(['2'], rows['held'])
        self.assertEqual(['0'], rows['enter'])
        self.assertEqual(['0'], rows['still_held'])
        self.assertEqual(['0'], rows['released'])
        self.assertEqual(['1'], rows['pressed_again'])

    def test_the_seam_is_the_only_a_b_path(self):
        source = (ROOT / 'src/host/overrides_input.c').read_text()
        body = extract(source, 'static int pad_states(NpadState *out, int max,')
        self.assertIn('nd_pad_route_a_b(', body)
        self.assertNotIn('nd_menu_confirm(', body, 'pad_states must not route A/B a second way')


if __name__ == '__main__':
    unittest.main()
