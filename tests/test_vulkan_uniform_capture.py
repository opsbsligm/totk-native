"""Pending GPU writes must invalidate exactly the stale uniform captures."""

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UniformCaptureTest(unittest.TestCase):
    def test_pending_writes_match_the_overlap_rule(self):
        compiler = os.environ.get('CC', 'cc')
        if not shutil.which(compiler):
            self.skipTest('no C compiler')
        source = (ROOT / 'src/gfx/vkb_ucap.c').read_text()
        helpers = source[source.index('static int first_range_after('):source.index('static int arena_get(')]
        prefix = r'''
#include <assert.h>
#include <stdatomic.h>
#include <stdint.h>

typedef struct { uint64_t lo, hi, dev; _Atomic uint64_t drop_at; } urng;
typedef struct { uint64_t lo, hi, fence; } pend_t;
static urng ranges[64];
static pend_t writes[96];
static urng *g_u = ranges;
static pend_t *g_pend = writes;
static int g_npend;
static uint64_t g_drops;
'''
        main = r'''
static void check(int count, uint64_t capture_fence) {
    int expected[64] = {0};
    for (int i = 0; i < count; i++) {
        g_u[i].drop_at = UINT64_MAX;
        for (int j = 0; j < g_npend; j++) {
            if (g_pend[j].fence > capture_fence &&
                g_pend[j].lo < g_u[i].hi && g_u[i].lo < g_pend[j].hi) {
                expected[i] = 1;
                break;
            }
        }
    }
    g_drops = 0;
    drop_pending_ranges(count, capture_fence);
    uint64_t count_dropped = 0;
    for (int i = 0; i < count; i++) {
        assert(g_u[i].drop_at == (expected[i] ? 0 : UINT64_MAX));
        count_dropped += expected[i];
    }
    assert(g_drops == count_dropped);
}

static uint32_t state = 912764u;
static uint32_t random_word(void) {
    state ^= state << 13;
    state ^= state >> 17;
    state ^= state << 5;
    return state;
}

int main(void) {
    ranges[0] = (urng){10, 20, 0, 0};
    ranges[1] = (urng){30, 40, 0, 0};
    ranges[2] = (urng){40, 50, 0, 0};
    writes[0] = (pend_t){20, 30, 3};        // touches both edges without overlapping
    writes[1] = (pend_t){15, 45, 2};        // already retired when captured
    writes[2] = (pend_t){33, 47, 4};        // overlaps two ranges
    writes[3] = (pend_t){31, 50, 5};        // repeated overlap increments only once
    g_npend = 4;
    check(3, 2);
    check(0, 2);
    check(3, 5);

    for (int iteration = 0; iteration < 300; iteration++) {
        int count = (int)(random_word() % 65);
        uint64_t end = 0;
        for (int i = 0; i < count; i++) {
            uint64_t start = end + random_word() % 5;
            end = start + 1 + random_word() % 32;
            ranges[i] = (urng){start, end, 0, 0};
        }
        g_npend = (int)(random_word() % 97);
        for (int i = 0; i < g_npend; i++) {
            uint64_t start = random_word() % (end + 32);
            writes[i] = (pend_t){start, start + random_word() % 64, random_word() % 20};
        }
        check(count, random_word() % 20);
    }
}
'''
        with tempfile.TemporaryDirectory(prefix='totk-ucap-check-') as scratch:
            work = Path(scratch)
            test = work / 'uniform.c'
            binary = work / 'uniform'
            test.write_text(prefix + helpers + main)
            subprocess.run([compiler, '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror',
                            str(test), '-o', str(binary)], check=True, timeout=30)
            subprocess.run([str(binary)], check=True, timeout=5)


if __name__ == '__main__':
    unittest.main()
