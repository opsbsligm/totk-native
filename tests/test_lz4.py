"""Exercise the native LZ4 decoder on valid blocks and malformed boundaries."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Lz4(unittest.TestCase):
    def test_block_lengths_offsets_and_overlap(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            source = Path(tmp) / 'test_lz4.c'
            binary = Path(tmp) / 'test_lz4'
            source.write_text(r'''
#include <assert.h>
#include "lz4.h"
#define DECODE(in, n) lz4_decompress(in, sizeof in, out, n)
int main(void) {
    uint8_t out[32];
    const uint8_t literal[] = {0xf0, 2, 'a','b','c','d','e','f','g','h','i',
                              'j','k','l','m','n','o','p','q'};
    const uint8_t overlap[] = {0x11, 'A', 1, 0, 0x10, 'B'};
    const uint8_t long_match[] = {0x1f, 'A', 1, 0, 3, 0x10, 'B'};
    const uint8_t short_literal_length[] = {0xf0, 255};
    const uint8_t short_literal[] = {0x20, 'A'};
    const uint8_t short_offset[] = {0x10, 'A', 1};
    const uint8_t short_match_length[] = {0x1f, 'A', 1, 0};
    const uint8_t zero_offset[] = {0x10, 'A', 0, 0};
    const uint8_t before_output[] = {0x10, 'A', 2, 0};
    assert(DECODE(literal, 17) == 17 && !memcmp(out, "abcdefghijklmnopq", 17));
    assert(DECODE(overlap, 7) == 7 && !memcmp(out, "AAAAAAB", 7));
    assert(DECODE(long_match, 24) == 24 && out[22] == 'A' && out[23] == 'B');
    assert(DECODE(literal, 16) == SIZE_MAX);
    assert(DECODE(overlap, 5) == SIZE_MAX);
    assert(DECODE(short_literal_length, sizeof out) == SIZE_MAX);
    assert(DECODE(short_literal, sizeof out) == SIZE_MAX);
    assert(DECODE(short_offset, sizeof out) == SIZE_MAX);
    assert(DECODE(short_match_length, sizeof out) == SIZE_MAX);
    assert(DECODE(zero_offset, sizeof out) == SIZE_MAX);
    assert(DECODE(before_output, sizeof out) == SIZE_MAX);
    return 0;
}
''')
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-I', str(ROOT / 'src/runtime'), str(source), '-o', str(binary)],
                           check=True)
            subprocess.run([str(binary)], check=True)
