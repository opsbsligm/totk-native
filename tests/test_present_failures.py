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
int main(void) {
 vk.vkGetPhysicalDeviceSurfaceCapabilitiesKHR=caps;vk.vkGetPhysicalDeviceSurfaceFormatsKHR=formats;
 vk.vkGetPhysicalDeviceSurfacePresentModesKHR=modes;vk.vkCreateSwapchainKHR=create;vk.vkDestroySwapchainKHR=destroy;
 vk.vkGetSwapchainImagesKHR=get_images;vk.vkCreateImageView=view;
 for(scenario=1;scenario<=5;scenario++) {created=destroyed=view_calls=0;assert(!create_swapchain());assert(!swapchain && !nimages && !view_calls);assert(created==destroyed);}
 return 0;
}
''')
            flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','sdl3','vulkan'],text=True))
            subprocess.run(['cc','-std=gnu17','-ffunction-sections','-fdata-sections','-I',str(ROOT/'src'),str(source),'-Wl,--gc-sections',*flags,'-pthread','-lm','-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)
