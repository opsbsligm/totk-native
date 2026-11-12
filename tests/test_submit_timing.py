"""Fault-inject clocks/driver results into the production queue wrapper."""
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SubmitTiming(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'linux', 'Production Linux Vulkan submission')
    def test_lock_and_api_time_are_separate_and_failure_still_unlocks(self):
        text = (ROOT / 'src/gfx/backend_vk.c').read_text()
        start = text.index('static _Atomic uint64_t g_submit_lock_ns')
        end = text.index('// ---------------- memory pools', start)
        body = text[start:end]
        prefix = r'''
#include <assert.h>
#include <stdatomic.h>
#include <stdint.h>
#include <vulkan/vulkan.h>
static _Atomic int g_ok;
static struct { VkQueue queue; } vkc;
static struct { PFN_vkQueueSubmit2 vkQueueSubmit2; } vk;
static int held, calls, clock_index;
static const uint64_t times[]={100,350,900,1000,1050,1100};
static uint64_t runtime_now_ns(void) { assert(clock_index<6);return times[clock_index++]; }
static void vk_queue_lock(void) { assert(!held);held=1; }
static void vk_queue_unlock(void) { assert(held);held=0; }
static VkSubmitInfo2 submission;
static VkResult VKAPI_CALL driver(VkQueue q,uint32_t n,const VkSubmitInfo2 *s,VkFence f) {
 assert(held && q==(VkQueue)(uintptr_t)1 && n==1 && s==&submission && f==VK_NULL_HANDLE);
 return ++calls==1 ? VK_SUCCESS : VK_ERROR_DEVICE_LOST;
}
'''
        main = r'''
int main(void) {
 uint64_t lock=77,api=88;
 assert(!vkb_submit_timing(&lock,&api) && lock==77 && api==88);
 g_ok=1;vkc.queue=(VkQueue)(uintptr_t)1;vk.vkQueueSubmit2=driver;
 assert(tracked_queue_submit(1,&submission)==VK_SUCCESS && !held);
 assert(vkb_submit_timing(&lock,&api) && lock==250 && api==550);
 assert(tracked_queue_submit(1,&submission)==VK_ERROR_DEVICE_LOST && !held);
 assert(vkb_submit_timing(&lock,&api) && lock==300 && api==600 && calls==2);
 g_ok=0;assert(!vkb_submit_timing(&lock,&api));
 return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='totk-submit-timing-', dir=Path.cwd()) as directory:
            path = Path(directory) / 'submit.c'
            binary = Path(directory) / 'submit'
            path.write_text(prefix + body + main)
            flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', 'vulkan'], text=True))
            subprocess.run(['cc', '-std=gnu17', '-O1', *flags, str(path), '-o', str(binary)],
                           check=True, capture_output=True, text=True, timeout=30)
            subprocess.run([str(binary)], check=True, timeout=5)
