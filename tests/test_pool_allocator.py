"""Validate production pool suballocation and fence-delayed reuse."""
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'linux', 'Linux Vulkan allocator')
class PoolAllocator(unittest.TestCase):
    def test_shared_blocks_fences_memory_types_and_allocation_failures(self):
        text = (ROOT / 'src/gfx/vkb_shadow.c').read_text()
        production = text[text.index('enum { BLOCK'):]
        prefix = r'''
#include <assert.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vulkan/vulkan.h>
#define VLOG(...) ((void)0)
#define die(...) do {fprintf(stderr,__VA_ARGS__);abort();}while(0)
enum { MT_POOL_COPY };
static int vkb_mtag;
static struct {VkDevice device;VkPhysicalDeviceProperties props;VkPhysicalDeviceMemoryProperties memory;} vkc;
static struct {
 PFN_vkCreateBuffer vkCreateBuffer;PFN_vkDestroyBuffer vkDestroyBuffer;
 PFN_vkGetBufferMemoryRequirements vkGetBufferMemoryRequirements;
 PFN_vkAllocateMemory vkAllocateMemory;PFN_vkFreeMemory vkFreeMemory;
 PFN_vkBindBufferMemory vkBindBufferMemory;PFN_vkMapMemory vkMapMemory;
} vk;
static uint64_t completed;
static int mtl_wait(uint64_t fence,uint64_t timeout) {(void)timeout;return fence<=completed;}
static uint64_t mtl_last_fence(void) {return 10;}
static int vkb_pool_copies(void) {return 1;}
static int vk_check(VkResult r,const char *what) {(void)what;return r==VK_SUCCESS;}
'''
        suffix = r'''
typedef struct {VkDeviceSize size;uint32_t type;uint8_t *data;} mem_record;
static mem_record *memories[16];
static int allocations,freed,fail_map,fail_bind,fail_alloc;
static VkMemoryRequirements requirement={4096,4096,1};
static void VKAPI_CALL get_requirements(VkDevice d,VkBuffer b,VkMemoryRequirements *r) {(void)d;(void)b;*r=requirement;}
static VkResult VKAPI_CALL allocate(VkDevice d,const VkMemoryAllocateInfo *a,const VkAllocationCallbacks *cb,VkDeviceMemory *m) {
 (void)d;(void)cb;if(fail_alloc) return VK_ERROR_OUT_OF_DEVICE_MEMORY;
 assert(a->allocationSize>=requirement.size && a->memoryTypeIndex<2 && allocations<16);
 mem_record *p=malloc(sizeof *p);assert(p);p->size=a->allocationSize;p->type=a->memoryTypeIndex;p->data=malloc(p->size);assert(p->data);
 memories[allocations++]=p;*m=(VkDeviceMemory)p;return VK_SUCCESS;
}
static void VKAPI_CALL release(VkDevice d,VkDeviceMemory m,const VkAllocationCallbacks *cb) {
 (void)d;(void)cb;mem_record *p=(mem_record*)m;free(p->data);p->data=NULL;freed++;
}
static VkResult VKAPI_CALL map_memory(VkDevice d,VkDeviceMemory m,VkDeviceSize off,VkDeviceSize size,VkMemoryMapFlags f,void **p) {
 (void)d;(void)size;(void)f;if(fail_map) return VK_ERROR_MEMORY_MAP_FAILED;
 mem_record *r=(mem_record*)m;assert(off<r->size);*p=r->data+off;return VK_SUCCESS;
}
static VkResult VKAPI_CALL bind(VkDevice d,VkBuffer b,VkDeviceMemory m,VkDeviceSize off) {
 (void)d;(void)b;mem_record *p=(mem_record*)m;
 assert(!(off&(requirement.alignment-1)) && off<=p->size && requirement.size<=p->size-off);
 assert(requirement.memoryTypeBits&(1u<<p->type));
 return fail_bind?VK_ERROR_OUT_OF_DEVICE_MEMORY:VK_SUCCESS;
}
int main(void) {
 unsetenv("TOTK_POOL_MEM");
 vk.vkGetBufferMemoryRequirements=get_requirements;vk.vkAllocateMemory=allocate;
 vk.vkFreeMemory=release;vk.vkMapMemory=map_memory;vk.vkBindBufferMemory=bind;
 vkc.memory.memoryTypeCount=2;
 vkc.memory.memoryTypes[0].propertyFlags=VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT|VK_MEMORY_PROPERTY_HOST_CACHED_BIT;
 vkc.memory.memoryTypes[1].propertyFlags=VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
 uint8_t *p1,*p2,*p3,*p4,*other;
 uint32_t h1=vkb_poolmem_alloc((VkBuffer)(uintptr_t)1,&p1),h2=vkb_poolmem_alloc((VkBuffer)(uintptr_t)2,&p2);
 assert(h1 && h2 && allocations==1 && p2==p1+4096 && vkb_poolmem_bytes()==8192);
 vkb_poolmem_free(h1);
 uint32_t h3=vkb_poolmem_alloc((VkBuffer)(uintptr_t)3,&p3);assert(h3 && p3!=p1 && allocations==1);
 completed=11;
 uint32_t h4=vkb_poolmem_alloc((VkBuffer)(uintptr_t)4,&p4);assert(h4 && p4==p1 && allocations==1);
 requirement.memoryTypeBits=2;
 uint32_t h5=vkb_poolmem_alloc((VkBuffer)(uintptr_t)5,&other);assert(h5 && allocations==2 && memories[1]->type==1);
 requirement.memoryTypeBits=0;assert(!vkb_poolmem_alloc((VkBuffer)(uintptr_t)6,&other));
 requirement.memoryTypeBits=1;requirement.size=UINT64_MAX;assert(!vkb_poolmem_alloc((VkBuffer)(uintptr_t)6,&other));
 requirement.size=4096;requirement.alignment=3;assert(!vkb_poolmem_alloc((VkBuffer)(uintptr_t)6,&other));
 requirement.alignment=65536;fail_alloc=1;assert(!vkb_poolmem_alloc((VkBuffer)(uintptr_t)6,&other));fail_alloc=0;
 fail_map=1;int old_freed=freed;assert(!vkb_poolmem_alloc((VkBuffer)(uintptr_t)6,&other) && freed==old_freed+1);fail_map=0;
 requirement.alignment=4096;
 uint64_t live=vkb_poolmem_bytes();fail_bind=1;assert(!vkb_poolmem_alloc((VkBuffer)(uintptr_t)6,&other));assert(vkb_poolmem_bytes()==live);fail_bind=0;
 vkb_poolmem_free(h2);vkb_poolmem_free(h3);vkb_poolmem_free(h4);vkb_poolmem_free(h5);assert(vkb_poolmem_bytes()==0);
 for(int i=0;i<allocations;i++) {free(memories[i]->data);free(memories[i]);}
 return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='pool-allocator-', dir=Path.cwd()) as directory:
            source, binary = Path(directory) / 'allocator.c', Path(directory) / 'allocator'
            source.write_text(prefix + production + suffix)
            flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', 'vulkan'], text=True))
            result = subprocess.run(['cc', '-std=gnu17', '-O1', '-pthread', '-fsanitize=address,undefined',
                                     '-fno-sanitize-recover=all', *flags, str(source), '-o', str(binary)],
                                    capture_output=True, text=True, timeout=40)
            self.assertEqual(result.returncode, 0, result.stderr)
            subprocess.run([str(binary)], check=True, timeout=8)
