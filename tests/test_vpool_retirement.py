"""Run real pool finalization and retirement against Linux VM and an instrumented Vulkan API."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'linux', 'Linux host-storage lifetime regression')
class VpoolRetirement(unittest.TestCase):
    def test_owned_mapping_outlives_translation_and_gpu_import(self):
        vm = (ROOT/'src/gfx/nvn/totk_vpool_win.c').read_text()
        hle = (ROOT/'src/gfx/nvn/hle_nvn.c').read_text()
        backend = (ROOT/'src/gfx/backend_vk.c').read_text()
        vm = vm[vm.index('#define F_CPU_NO_ACCESS'):vm.index('static int check_request')]
        finalizer = hle[hle.index('NVN(nvnMemoryPoolFinalize,'):hle.index('NVN(nvnMemoryPoolFlushMappedRange,')]
        deletion = backend[backend.index('void mtl_pool_del('):backend.index('void mtl_pool_invalidate(')]
        retirement = backend[backend.index('typedef struct dead {'):backend.index('static void gpu_span(int slot, uint64_t fence);')]
        jobs = hle[hle.index('enum { XJ_SUBMIT = 1,'):hle.index('#define XQ')]
        limits = hle[hle.index('enum { XPOOLS = '):hle.index('static struct { uintptr_t lo, hi; } g_xpool')]
        release = hle[hle.rindex('static void x_poolrel('):hle.index('static void x_pool_reuse(', hle.rindex('static void x_poolrel('))]
        replay = hle.split('else if (j.kind == XJ_POOLREL) {', 1)[1].split('}', 1)[0]
        prefix = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <vulkan/vulkan.h>
#include "totk_vpool.h"
#define die(...) do {fprintf(stderr,__VA_ARGS__);abort();}while(0)
#define LOG(...) ((void)0)
#define VLOG(...) ((void)0)
#define LK_POOLS 0
static void nvn_dirty_remove_range(const void *p) {(void)p;}
static int async_mode = 1;
static int async_replay(void) {return async_mode;}
static void va_release(uint64_t va) {(void)va;}
static void *queued_mem;
#define NVN(name, result, ...) static result h_##name(__VA_ARGS__)
typedef int vkb_rw;
static vkb_rw g_pool_mu;
static void vkb_rw_write(vkb_rw *p,int k) {(void)p;(void)k;}
static void vkb_rw_write_end(vkb_rw *p) {(void)p;}
typedef struct {uintptr_t lo,hi;VkBuffer buf;VkDeviceMemory mem;const void *key;uint32_t sh,ch;} pool_ent;
static pool_ent g_pools[4];
static int g_npools, g_ok=1;
static uint64_t g_pool_bytes;
static struct {int has_checkpoints,has_buffer_marker;VkDevice device;} vkc;
static uint64_t vkb_frame(void) {return 1;}
static void vkb_shadow_free(uint32_t h) {(void)h;}
static void vkb_poolmem_free(uint32_t h) {(void)h;}
static void wb_forget(VkBuffer b) {(void)b;}
static void *expected_mapping;
static uint64_t expected_span;
static int destroyed_buffers, freed_imports;
static struct {void *mapping;int buffer_destroyed,memory_freed;} imports[16];
static unsigned nimports;
static int mapped(void *p) {unsigned char vec;errno=0;return mincore(p,4096,&vec)==0;}
static void VKAPI_CALL buffer_destroy(VkDevice d,VkBuffer b,const VkAllocationCallbacks *a) {
    (void)d;(void)a;unsigned i=(unsigned)(uintptr_t)b;assert(i && i<=nimports);
    assert(!imports[i].buffer_destroyed && mapped(imports[i].mapping));
    imports[i].buffer_destroyed=1;destroyed_buffers++;
}
static void VKAPI_CALL memory_free(VkDevice d,VkDeviceMemory m,const VkAllocationCallbacks *a) {
    (void)d;(void)a;unsigned i=(unsigned)(uintptr_t)m;assert(i && i<=nimports);
    assert(imports[i].buffer_destroyed && !imports[i].memory_freed && mapped(imports[i].mapping));
    imports[i].memory_freed=1;freed_imports++;
}
static struct {
    PFN_vkDestroyShaderEXT vkDestroyShaderEXT;PFN_vkDestroyImageView vkDestroyImageView;
    PFN_vkDestroyImage vkDestroyImage;PFN_vkDestroyBuffer vkDestroyBuffer;PFN_vkFreeMemory vkFreeMemory;
} vk;
static void destroy_later(VkImageView,VkImage,VkDeviceMemory,VkBuffer);
static void destroy_later_release(VkImageView,VkImage,VkDeviceMemory,VkBuffer,void (*)(void *),void *);
void mtl_pool_del(const void *);
void mtl_pool_del_release(const void *,void (*)(void *),void *);
'''
        queue = r'''
#define XD_POOL 0
static pthread_mutex_t g_xq_mu=PTHREAD_MUTEX_INITIALIZER;
static struct {uintptr_t lo,hi;} g_xpool[XPOOLS];
static int g_nxpool,drains;
static xjob queued_job;
static uint64_t x_push(xjob *j) {assert(!queued_mem);queued_job=*j;queued_mem=j->ucap;return 1;}
static void x_drain(int why) {(void)why;drains++;g_nxpool=0;}
'''
        suffix = r'''
static void run_queued_delete(void) {
    assert(queued_mem);
    xjob j=queued_job;
    REPLAY_POOL_RELEASE
    queued_mem=NULL;queued_job=(xjob){0};g_nxpool=0;
}
static void setup(pool_t *p,int flags,int imported) {
    memset(p,0,sizeof *p);p->flags=flags;p->size=0x10000;
    if(flags&NVN_MEMORY_POOL_FLAGS_PHYSICAL)p->mem=(void *)(uintptr_t)0x12340000;
    assert(totk_vpool_init(p));expected_mapping=p->host;expected_span=p->span;
    assert(expected_mapping && expected_span==0x10000 && mapped(expected_mapping));
    p->magic=MAGIC('P','O','O','L');
    if(imported) {
        assert(!g_npools);g_npools=1;g_pool_bytes=p->size;
        assert(++nimports<16);imports[nimports].mapping=p->mem;
        g_pools[0]=(pool_ent){.lo=(uintptr_t)p->mem,.hi=(uintptr_t)p->mem+p->size,
            .buf=(VkBuffer)(uintptr_t)nimports,.mem=(VkDeviceMemory)(uintptr_t)nimports,.key=p->mem};
    }
}
int main(void) {
    vk.vkDestroyBuffer=buffer_destroy;vk.vkFreeMemory=memory_free;
    pool_t p;uint64_t bytes,pools;
    setup(&p,NVN_MEMORY_POOL_FLAGS_PHYSICAL|NVN_MEMORY_POOL_FLAGS_CPU_NO_ACCESS,1);
    memset(p.host,0x35,p.span);h_nvnMemoryPoolFinalize((NVNmemoryPool *)&p);
    assert(!p.magic && !p.host && p.mem==(void *)(uintptr_t)0x12340000);
    assert(mapped(expected_mapping)); // regression: old finalization unmapped before its queued import deletion
    totk_vpool_host_stats(&bytes,&pools);assert(bytes==expected_span && pools==1);
    memset(&p,0xa5,sizeof p); // guest object reuse cannot change captured ownership
    run_queued_delete();assert(mapped(expected_mapping) && !freed_imports);
    dead_reap(UINT64_MAX);assert(mapped(expected_mapping)); // not assigned to a submitted fence yet
    dead_tag(7);dead_reap(6);assert(mapped(expected_mapping) && !freed_imports);
    dead_reap(7);assert(!mapped(expected_mapping) && freed_imports==1 && destroyed_buffers==1);
    totk_vpool_host_stats(&bytes,&pools);assert(!bytes && !pools);
    dead_reap(UINT64_MAX);assert(freed_imports==1);
    // Synchronous translation still defers the import and host allocation to GPU retirement.
    async_mode=0;setup(&p,NVN_MEMORY_POOL_FLAGS_PHYSICAL|NVN_MEMORY_POOL_FLAGS_CPU_NO_ACCESS,1);
    h_nvnMemoryPoolFinalize((NVNmemoryPool *)&p);assert(mapped(expected_mapping));
    dead_tag(8);dead_reap(7);assert(mapped(expected_mapping));dead_reap(8);assert(!mapped(expected_mapping));
    assert(freed_imports==2 && destroyed_buffers==2);
    // The actual full-queue fallback also transfers ownership through GPU retirement.
    async_mode=1;g_nxpool=XPOOLS;
    setup(&p,NVN_MEMORY_POOL_FLAGS_PHYSICAL|NVN_MEMORY_POOL_FLAGS_CPU_NO_ACCESS,1);
    h_nvnMemoryPoolFinalize((NVNmemoryPool *)&p);assert(drains==1 && !queued_mem && mapped(expected_mapping));
    dead_tag(9);dead_reap(8);assert(mapped(expected_mapping));dead_reap(9);assert(!mapped(expected_mapping));
    assert(freed_imports==3 && destroyed_buffers==3);
    // Reuse the same guest object while two independent backing allocations await different fences.
    setup(&p,NVN_MEMORY_POOL_FLAGS_PHYSICAL|NVN_MEMORY_POOL_FLAGS_CPU_NO_ACCESS,1);
    void *first=p.host;h_nvnMemoryPoolFinalize((NVNmemoryPool *)&p);run_queued_delete();dead_tag(10);
    setup(&p,NVN_MEMORY_POOL_FLAGS_PHYSICAL|NVN_MEMORY_POOL_FLAGS_CPU_NO_ACCESS,1);
    void *second=p.host;assert(first!=second);h_nvnMemoryPoolFinalize((NVNmemoryPool *)&p);run_queued_delete();dead_tag(11);
    totk_vpool_host_stats(&bytes,&pools);assert(bytes==2*expected_span && pools==2);
    dead_reap(10);assert(!mapped(first) && mapped(second));
    totk_vpool_host_stats(&bytes,&pools);assert(bytes==expected_span && pools==1);
    dead_reap(11);assert(!mapped(second) && freed_imports==5 && destroyed_buffers==5);
    // Virtual, inaccessible storage with no Vulkan import is detached by the translation job.
    async_mode=1;setup(&p,NVN_MEMORY_POOL_FLAGS_VIRTUAL,0);
    h_nvnMemoryPoolFinalize((NVNmemoryPool *)&p);assert(mapped(expected_mapping));
    run_queued_delete();assert(!mapped(expected_mapping));
    // CPU-only ownership and a null GPU backend never wait for a fence that cannot arrive.
    setup(&p,NVN_MEMORY_POOL_FLAGS_PHYSICAL|NVN_MEMORY_POOL_FLAGS_CPU_NO_ACCESS|NVN_MEMORY_POOL_FLAGS_GPU_NO_ACCESS,0);
    h_nvnMemoryPoolFinalize((NVNmemoryPool *)&p);assert(!mapped(expected_mapping) && !queued_mem);
    async_mode=0;g_ok=0;setup(&p,NVN_MEMORY_POOL_FLAGS_VIRTUAL,0);
    h_nvnMemoryPoolFinalize((NVNmemoryPool *)&p);assert(!mapped(expected_mapping));
    // Ordinary guest-owned storage is never unmapped by the pool finalizer.
    void *guest=mmap(NULL,0x10000,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);assert(guest!=MAP_FAILED);
    p=(pool_t){.magic=MAGIC('P','O','O','L'),.mem=guest,.size=0x10000,.flags=NVN_MEMORY_POOL_FLAGS_GPU_NO_ACCESS};
    h_nvnMemoryPoolFinalize((NVNmemoryPool *)&p);assert(mapped(guest));assert(!munmap(guest,0x10000));
    totk_vpool_host_stats(&bytes,&pools);assert(!bytes && !pools && !g_dead && !g_dead_new);
    puts("Owned pool VM: translation ordering, GPU-fence retirement, import-before-host release, object reuse and CPU/null paths PASS");
    return 0;
}
'''
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            source, binary = Path(folder)/'retirement.c', Path(folder)/'retirement'
            source.write_text(prefix+vm+deletion+retirement+jobs+limits+queue+release+finalizer+
                              suffix.replace('REPLAY_POOL_RELEASE', replay))
            command = ['clang','-std=gnu17','-O1','-g','-pthread','-ffunction-sections','-fdata-sections',
                       '-fsanitize=address,undefined','-fno-sanitize-recover=all','-Wl,--gc-sections',
                       '-I'+str(ROOT/'src/gfx/nvn'),'-I'+str(ROOT/'src/gfx/nvn/include'),
                       str(source),'-o',str(binary)]
            result = subprocess.run(command,capture_output=True,text=True,timeout=40)
            self.assertEqual(result.returncode,0,result.stderr)
            subprocess.run([str(binary)],check=True,timeout=10)
