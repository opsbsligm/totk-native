"""Per-frame GPU time: the replayer's rows, fed by fake submissions and clocks."""
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GpuFrameTime(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'linux', 'Production Linux Vulkan replayer')
    def test_rows_are_per_frame_complete_and_only_after_retirement(self):
        text = (ROOT / 'src/gfx/backend_vk.c').read_text()
        rows = text[text.index('// ---------------- per-frame GPU time'):text.index('static void run_posts')]
        account = text[text.index('// A retired submission into its frame'):
                      text.index('// A submission whose recording took over 100 ms')]
        prefix = r'''
#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <vulkan/vulkan.h>
typedef struct { VkDevice device; struct { VkPhysicalDeviceLimits limits; } props; } device_t;
typedef struct { uint64_t fence; int slot; uint64_t frame; } job;   // the fields the accounting reads
static device_t vkc;
static struct { VkResult (*vkGetQueryPoolResults)(VkDevice, VkQueryPool, uint32_t, uint32_t, size_t, void *, VkDeviceSize, VkQueryResultFlags); } vk;
static VkQueryPool g_tsq = (VkQueryPool)(uintptr_t)1;
static uint64_t g_now = 1000000, g_done;
static uint64_t runtime_now_ns(void) { return g_now; }
static uint64_t mtl_done(void) { return g_done; }
static VkResult VKAPI_CALL results(VkDevice d, VkQueryPool q, uint32_t first, uint32_t n, size_t bytes, void *data,
                                   VkDeviceSize stride, VkQueryResultFlags flags) {
  assert(d == vkc.device && q == g_tsq && n == 2 && first % 2 == 0 && stride == 8 && bytes == 16);
  uint64_t *t = data;
  t[0] = 1000 + 100 * first;      // every submission: 100 timestamps, 2000 ns each | 0.2 ms
  t[1] = t[0] + 100;
  return VK_SUCCESS;
}
'''
        main = r'''
int main(void) {
  uint64_t t0 = 0, t1 = 0;
  vkc.device = (VkDevice)(uintptr_t)7;
  vkc.props.limits.timestampPeriod = 2000.0;
  vk.vkGetQueryPoolResults = results;
  assert(mtl_gpu_ms(0) < 0 && !mtl_gpu_span(0, &t0, &t1));       // nothing recorded yet
  mtl_set_frame(1);
  job a = {10, 0, 1}; g_now = 1100000; gpu_account(&a);
  assert(mtl_gpu_ms(1) < 0);                                     // frame 1 is still being recorded
  mtl_set_frame(2);
  assert(mtl_gpu_ms(1) < 0);                                     // closed, but the next submission is still on the GPU
  job b = {11, 1, 1}; g_now = 1300000; gpu_account(&b);
  assert(mtl_gpu_ms(1) < 0);
  g_done = 11;
  assert(mtl_gpu_ms(1) == 0.4);                                  // both submissions added up
  assert(mtl_gpu_span(1, &t0, &t1) && t0 == 900000 && t1 == 1300000);   // the window they covered
  assert(mtl_gpu_ms(2) < 0);                                     // frame 2 is the one being recorded now
  job c = {12, 2, 2}; g_now = 1400000; gpu_account(&c); g_done = 12;
  assert(mtl_gpu_ms(2) < 0);
  mtl_set_frame(3);
  assert(mtl_gpu_ms(2) == 0.2 && mtl_gpu_ms(3) < 0);              // its own row, nothing invented for an empty frame
  for (uint64_t f = 3; f < 400; f++) { job j = {100 + f, (int)(f % 8), f}; g_now += 1000; gpu_account(&j); }
  g_done = 1000; mtl_set_frame(400);
  assert(mtl_gpu_ms(399) == 0.2 && mtl_gpu_ms(1) < 0);            // the ring keeps the newest frames
  g_tsq = VK_NULL_HANDLE;                                         // a device without timestamps: nothing new is accounted
  job d = {600, 3, 400}; gpu_account(&d); g_done = 600; mtl_set_frame(401);
  assert(mtl_gpu_ms(400) < 0 && !mtl_gpu_span(400, &t0, &t1));
  return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='totk-gpu-frame-time-', dir=Path.cwd()) as directory:
            path = Path(directory) / 'frame.c'
            binary = Path(directory) / 'frame'
            path.write_text(prefix + rows + account + main)
            try:
                flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', 'vulkan'], text=True))
            except subprocess.CalledProcessError:
                flags = []
            subprocess.run(['cc', '-std=gnu17', '-O1', '-Wall', '-Werror', *flags, str(path), '-o', str(binary), '-pthread'],
                           check=True, capture_output=True, text=True, timeout=60)
            self.assertIn('mtl_set_frame', rows)   # the frame number comes from the front end, not a counter here
            subprocess.run([str(binary)], check=True, timeout=5)


if __name__ == '__main__':
    unittest.main()
