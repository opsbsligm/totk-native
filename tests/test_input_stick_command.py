"""The FIFO's stick command must parse exactly as the harness writes it.

TOTK walks Link with the left stick only, so the automated scenes (walk, look, then open the map) need a
stick channel; it exists solely on the private development FIFO (`TOTK_INPUT_FIFO`). The harness writes
`seq:A,lx,ly,rx,ry*hold` and the game reports a rejected line, so a format that drifts fails silently as
"input ignored". These tests compile the production parser and pin both halves of the contract.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def extract(source, signature):
    start = source.index(signature)
    end = source.index('\n}\n', start) + 3
    return source[start:end]


class StickCommand(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / 'src/host/overrides_input.c').read_text()
        case = [
            '#include <stdio.h>\n#include <stdint.h>\n#include <string.h>\n',
            extract(source, 'static int parse_stick_command(const char *line,'),
            'static const char *cmds[] = {\n'
            '    "7:A,0,-24000,0,0*900",     // walk forward, held\n'
            '    "8:A,-32768,0,32767,-1*1",  // every axis, negative values\n'
            '    "9:A,0,0,0,0*3",            // centered sticks (a deliberate stop)\n'
            '    "10:A,0,0*3",               // too few axes\n'
            '    "11:A,0,0,0,0",             // no hold\n'
            '    "12:J*3",                   // the key language is not this parser\n'
            '    "A,0,0,0,0*3",              // no sequence number\n'
            '    "13:A,0,0,0,0*3 extra",     // trailing junk\n'
            '};\n',
            'int main(void) {\n'
            '    for (unsigned i = 0; i < sizeof cmds / sizeof *cmds; i++) {\n'
            '        unsigned long long seq = 0; int ax[4] = {0}; unsigned hold = 0;\n'
            '        int ok = parse_stick_command(cmds[i], &seq, ax, &hold);\n'
            '        printf("%u %d %llu %d %d %d %d %u\\n", i, ok, seq, ax[0], ax[1], ax[2], ax[3], hold);\n'
            '    }\n'
            '    return 0;\n}\n',
        ]
        cls.directory = tempfile.TemporaryDirectory(dir=Path.cwd())
        cls.addClassCleanup(cls.directory.cleanup)
        directory = Path(cls.directory.name)
        source_path = directory / 'stick-command.c'
        source_path.write_text(''.join(case))
        executable = directory / 'stick-command'
        subprocess.run(['clang', '-std=gnu11', '-O1', '-Wall', '-Wextra', '-Werror',
                        str(source_path), '-o', str(executable)], check=True, timeout=60)
        cls.rows = [line.split() for line in subprocess.run(
            [str(executable)], capture_output=True, text=True, check=True, timeout=10).stdout.splitlines()]
        cls.harness = (ROOT / 'tools/deck_pool_ab.py').read_text()

    def test_rows_are_well_formed(self):
        self.assertEqual(len(self.rows), 8)

    def test_valid_commands_carry_the_written_values(self):
        self.assertEqual(self.rows[0], ['0', '1', '7', '0', '-24000', '0', '0', '900'])
        self.assertEqual(self.rows[1], ['1', '1', '8', '-32768', '0', '32767', '-1', '1'])
        self.assertEqual(self.rows[2], ['2', '1', '9', '0', '0', '0', '0', '3'])

    def test_malformed_commands_are_refused(self):
        for row in self.rows[3:]:
            self.assertEqual(row[1], '0', f'must refuse {row}')

    def test_the_harness_writes_the_language_the_game_parses(self):
        # A stick line and a key line both go out through the same FIFO; the prefixes must agree with the parser.
        self.assertRegex(self.harness, r"f'\{sequence\}:A,\{lx\},\{ly\},\{rx\},\{ry\}\*\{hold\}\\n'")


if __name__ == '__main__':
    unittest.main()
