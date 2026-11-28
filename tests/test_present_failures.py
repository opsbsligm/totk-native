"""Fault-inject driver enumeration failures into the actual swapchain builder."""
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]

class PresentFailures(unittest.TestCase):
    def test_no_image_use_after_enumeration_failure(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            p=Path(folder);source=p/'present_faults.c';binary=p/'present_faults'
            source.write_text(r'''
#include <assert.h>
#include "vk/present.c"
VkFunctions vk;VkContext vkc;
static int scenario,created,destroyed,view_calls;
int vk_check(VkResult r,const char *what) {(void)what;return r==VK_SUCCESS;}
void nd_control_device_reset(void) {}
void nd_fsr_shutdown(void) {}
static VkResult caps(VkPhysicalDevice d,VkSurfaceKHR s,VkSurfaceCapabilitiesKHR *c) {
 (void)d;(void)s;memset(c,0,sizeof *c);c->currentExtent=(VkExtent2D){1280,800};c->minImageCount=2;return VK_SUCCESS;
}
static VkResult formats(VkPhysicalDevice d,VkSurfaceKHR s,uint32_t *n,VkSurfaceFormatKHR *f) {
 (void)d;(void)s;if(scenario==1)return VK_ERROR_SURFACE_LOST_KHR;
 *n=1;if(f) {if(scenario==2)return VK_ERROR_SURFACE_LOST_KHR;*f=(VkSurfaceFormatKHR){VK_FORMAT_B8G8R8A8_UNORM,VK_COLOR_SPACE_SRGB_NONLINEAR_KHR};}return VK_SUCCESS;
}
static VkResult modes(VkPhysicalDevice d,VkSurfaceKHR s,uint32_t *n,VkPresentModeKHR *m) {(void)d;(void)s;*n=1;if(m)*m=VK_PRESENT_MODE_FIFO_KHR;return VK_SUCCESS;}
static VkResult create(VkDevice d,const VkSwapchainCreateInfoKHR *c,const VkAllocationCallbacks *a,VkSwapchainKHR *s) {(void)d;(void)c;(void)a;created++;*s=(VkSwapchainKHR)1;return VK_SUCCESS;}
static void destroy(VkDevice d,VkSwapchainKHR s,const VkAllocationCallbacks *a) {(void)d;(void)a;assert(s==(VkSwapchainKHR)1);destroyed++;}
static VkResult get_images(VkDevice d,VkSwapchainKHR s,uint32_t *n,VkImage *i) {
 (void)d;(void)s;if(scenario==3)return VK_ERROR_DEVICE_LOST;
 *n=scenario==4?MAX_IMAGES+1:3;
 if(i){if(scenario==5)return VK_ERROR_DEVICE_LOST;assert(0);}
 return VK_SUCCESS;
}
static VkResult view(VkDevice d,const VkImageViewCreateInfo *c,const VkAllocationCallbacks *a,VkImageView *v) {(void)d;(void)c;(void)a;(void)v;view_calls++;return VK_ERROR_UNKNOWN;}
static uint64_t copy_completed;
static int destroyed_output;
static VkResult wait_copy(VkDevice device, const VkSemaphoreWaitInfo *wait, uint64_t timeout) {
    (void)device;
    assert(timeout == 0 && wait->semaphoreCount == 1 && wait->pSemaphores[0] == (VkSemaphore)1);
    return *wait->pValues <= copy_completed ? VK_SUCCESS : VK_TIMEOUT;
}
static void destroy_output(VkDevice device, VkImage image, const VkAllocationCallbacks *allocator) {
    (void)device; (void)allocator;
    assert(image == (VkImage)1 && copy_completed >= 9);
    destroyed_output++;
}
static void free_output(VkDevice device, VkDeviceMemory memory, const VkAllocationCallbacks *allocator) {
    (void)device; (void)allocator;
    assert(memory == (VkDeviceMemory)1 && destroyed_output == 1);
}
static VkResult fail_replacement(VkDevice device, const VkImageCreateInfo *info,
                                 const VkAllocationCallbacks *allocator, VkImage *image) {
    (void)device; (void)allocator; (void)image;
    assert(info->extent.width == 1280 && destroyed_output == 1);
    return VK_ERROR_OUT_OF_DEVICE_MEMORY;
}
static void test_output_retirement(void) {
    vk.vkWaitSemaphores = wait_copy;
    vk.vkDestroyImage = destroy_output;
    vk.vkFreeMemory = free_output;
    vk.vkCreateImage = fail_replacement;
    g_out[0] = (out_t){.img=(VkImage)1,.mem=(VkDeviceMemory)1,.w=640,.h=480,.timeline=(VkSemaphore)1,.value=9};
    g_out[1] = (out_t){.img=(VkImage)2,.w=1280,.h=720,.state=OUT_PENDING,.seq=2,.timeline=(VkSemaphore)1,.value=8};
    g_out[2].state = OUT_SHOWING;
    VkImage image = VK_NULL_HANDLE;
    copy_completed = 7;
    assert(vkp_out_acquire(640, 480, &image) == -1 && !image);
    assert(vkp_out_acquire(1280, 720, &image) == -1 && !destroyed_output);
    copy_completed = 8;
    // A completed pending slot stays usable even when an earlier free slot still has an in-flight copy.
    assert(vkp_out_acquire(1280, 720, &image) == 1 && image == (VkImage)2);
    assert(g_out[0].value == 9 && g_out[1].state == OUT_WRITING && !destroyed_output);
    copy_completed = 9;
    assert(vkp_out_acquire(1280, 720, &image) == -1 && destroyed_output == 1);
    assert(g_out[0].state == OUT_FREE && !g_out[0].img && !g_out[0].value);
}
int main(void) {
 vk.vkGetPhysicalDeviceSurfaceCapabilitiesKHR=caps;vk.vkGetPhysicalDeviceSurfaceFormatsKHR=formats;
 vk.vkGetPhysicalDeviceSurfacePresentModesKHR=modes;vk.vkCreateSwapchainKHR=create;vk.vkDestroySwapchainKHR=destroy;
 vk.vkGetSwapchainImagesKHR=get_images;vk.vkCreateImageView=view;
 for(scenario=1;scenario<=5;scenario++) {created=destroyed=view_calls=0;assert(!create_swapchain());assert(!swapchain && !nimages && !view_calls);assert(created==destroyed);}
 test_output_retirement();
 return 0;
}
''')
            flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','sdl3','vulkan'],text=True))
            subprocess.run(['cc','-std=gnu17','-ffunction-sections','-fdata-sections','-I',str(ROOT/'src'),str(source),'-Wl,--gc-sections',*flags,'-pthread','-lm','-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)
