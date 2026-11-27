"""Pass timestamps arrive in recording order, with potentially overlapping intervals."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GpuPassCoverage(unittest.TestCase):
    def test_unions_each_present_independently_in_gpu_time_order(self):
        backend = (ROOT / 'src/gfx/backend_vk.c').read_text()
        intervals = backend[backend.index('typedef struct { uint64_t frame, start, end; } pp_interval;'):
                            backend.index('static void pp_report(void)')]
        main = r'''
int main(void) {
    pp_interval intervals[] = {
        {9, 190, 200}, {8, 50, 60}, {8, 90, 80}, {8, 10, 30}, {9, 180, 198},
        {8, 30, 40}, {8, 11, 20}, {9, 150, 170}, {8, 10, 31}, {9, 200, 200},
    };
    pp_coverage result = pp_measure_coverage(intervals, sizeof intervals / sizeof intervals[0]);
    assert(result.covered == 80);
    assert(result.between == 20);
    result = pp_measure_coverage(intervals, 0);
    assert(result.covered == 0 && result.between == 0);
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='totk-pass-coverage-', dir=Path.cwd()) as directory:
            source = Path(directory) / 'coverage.c'
            binary = Path(directory) / 'coverage'
            source.write_text('#include <assert.h>\n#include <stdint.h>\n#include <stdlib.h>\n' + intervals + main)
            subprocess.run(['cc', '-std=c17', '-O1', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(binary)],
                           check=True, timeout=15)
            subprocess.run([str(binary)], check=True, timeout=5)


if __name__ == '__main__':
    unittest.main()
