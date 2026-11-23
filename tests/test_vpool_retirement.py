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
        deletion = backend[backend.index('#ifdef __linux__\ntypedef struct pool_release'):backend.index('void mtl_pool_invalidate(')]
        retirement = backend[backend.index('typedef struct dead {'):backend.index('static void gpu_span(int slot, uint64_t fence);')]
        gate = backend[backend.index('static int g_pool_copies = -1;'):backend.index('static const pool_ent *pool_find(uintptr_t addr, uint64_t len);', backend.index('static int g_pool_copies = -1;'))]
        registration = backend[backend.index('void mtl_pool_add('):backend.index('static void destroy_later(VkImageView view', backend.index('void mtl_pool_add('))]
        importing = backend[backend.index('static int import_host('):backend.index('// Pinned adaptation:', backend.index('static int import_host('))]
        pool_type = backend[backend.index('typedef struct { uintptr_t lo, hi, base;'):backend.index('static pool_ent *g_pools;')]
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
#include <signal.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <vulkan/vulkan.h>
#include "totk_vpool.h"
#include "src/runtime/platform/linux_watch.h"
#include "src/runtime/platform/linux_memory.h"
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
// The candidate batch holds the table's read lock across a whole command, so the gate it extracts needs the read side
// too (same shape as tests/test_pool_copies.py): the counters, not the kernel lock, are what that gate is about.
static void vkb_rw_read(vkb_rw *p,int kind) {(void)p;(void)kind;}
static void vkb_rw_read_end(vkb_rw *p) {(void)p;}
PRODUCTION_POOL_TYPE
static pool_ent *g_pools;
static int g_npools,g_capools,g_ok=1;
static uint64_t g_pool_bytes;
static struct {int has_checkpoints,has_buffer_marker;VkDevice device;uintptr_t host_pointer_alignment;VkPhysicalDeviceProperties props;} vkc;
static void backend_init(void) {}
static int shadow_on;
static int vkb_shadow_on(void) {return shadow_on;}
static int linux_host_readable(uintptr_t a,uint64_t n) {(void)a;(void)n;return 1;}
static int pc_alloc(uintptr_t a,uintptr_t b,VkBuffer *v,uint8_t **p,uint32_t *h) {(void)a;(void)b;(void)v;(void)p;(void)h;abort();}
#define GUEST_LO 0
static int watch_ok;
int plat_written_pages(uint64_t a,uint64_t n,uint64_t *p,int m,uint64_t *s) {(void)a;(void)n;(void)p;(void)m;(void)s;return watch_ok?0:-1;}
POOL_COPIES_GATE
static uint64_t vkb_frame(void) {return 1;}
static void vkb_shadow_free(uint32_t h) {(void)h;}
static void vkb_poolmem_free(uint32_t h) {(void)h;}
static void wb_forget(VkBuffer b) {(void)b;}
static void *expected_mapping;
static uint64_t expected_span;
static int destroyed_buffers, freed_imports;
static struct {void *mapping;int buffer_destroyed,memory_freed;} imports[16];
static unsigned nimports;
enum {IMPORT_OK,PROPERTY_FAIL,BUFFER_FAIL,NO_TYPE,ALLOC_FAIL,BIND_FAIL};
static int import_failure;
static void *import_address;
static int vk_check(VkResult r,const char *where) {(void)where;return r==VK_SUCCESS;}
static uint32_t memory_type(uint32_t types) {assert(types==1);return import_failure==NO_TYPE?UINT32_MAX:0;}
static VkResult VKAPI_CALL host_properties(VkDevice d,VkExternalMemoryHandleTypeFlagBits t,const void *p,VkMemoryHostPointerPropertiesEXT *h) {
    (void)d;assert(t==VK_EXTERNAL_MEMORY_HANDLE_TYPE_HOST_ALLOCATION_BIT_EXT);
    assert(linux_memory_busy((uintptr_t)p,0x10000));import_address=(void *)p;h->memoryTypeBits=1;
    return import_failure==PROPERTY_FAIL?VK_ERROR_UNKNOWN:VK_SUCCESS;
}
static VkResult VKAPI_CALL buffer_create(VkDevice d,const VkBufferCreateInfo *b,const VkAllocationCallbacks *a,VkBuffer *out) {
    (void)d;(void)a;assert(b->size==0x10000 && linux_memory_busy((uintptr_t)import_address,b->size));
    if(import_failure==BUFFER_FAIL)return VK_ERROR_UNKNOWN;
    assert(++nimports<16);imports[nimports].mapping=import_address;*out=(VkBuffer)(uintptr_t)nimports;return VK_SUCCESS;
}
static void VKAPI_CALL requirements(VkDevice d,VkBuffer b,VkMemoryRequirements *r) {
    (void)d;(void)b;*r=(VkMemoryRequirements){.size=0x10000,.alignment=4096,.memoryTypeBits=1};
}
static VkResult VKAPI_CALL memory_allocate(VkDevice d,const VkMemoryAllocateInfo *m,const VkAllocationCallbacks *a,VkDeviceMemory *out) {
    (void)d;(void)a;assert(m->allocationSize==0x10000 && linux_memory_busy((uintptr_t)import_address,m->allocationSize));
    if(import_failure==ALLOC_FAIL)return VK_ERROR_UNKNOWN;
    *out=(VkDeviceMemory)(uintptr_t)nimports;return VK_SUCCESS;
}
static VkResult VKAPI_CALL memory_bind(VkDevice d,VkBuffer b,VkDeviceMemory m,VkDeviceSize off) {
    (void)d;assert((uintptr_t)b==(uintptr_t)m && !off && linux_memory_busy((uintptr_t)import_address,0x10000));
    return import_failure==BIND_FAIL?VK_ERROR_UNKNOWN:VK_SUCCESS;
}
static int mapped(void *p) {unsigned char vec;errno=0;return mincore(p,4096,&vec)==0;}
static void VKAPI_CALL buffer_destroy(VkDevice d,VkBuffer b,const VkAllocationCallbacks *a) {
    (void)d;(void)a;unsigned i=(unsigned)(uintptr_t)b;assert(i && i<=nimports);
    assert(!imports[i].buffer_destroyed && mapped(imports[i].mapping));
    imports[i].buffer_destroyed=1;destroyed_buffers++;
}
static void VKAPI_CALL memory_free(VkDevice d,VkDeviceMemory m,const VkAllocationCallbacks *a) {
    (void)d;(void)a;unsigned i=(unsigned)(uintptr_t)m;assert(i && i<=nimports);
    assert(imports[i].buffer_destroyed && !imports[i].memory_freed && mapped(imports[i].mapping));
    assert(linux_memory_busy((uintptr_t)imports[i].mapping,0x10000));
    imports[i].memory_freed=1;freed_imports++;
}
static struct {
    PFN_vkDestroyShaderEXT vkDestroyShaderEXT;PFN_vkDestroyImageView vkDestroyImageView;
    PFN_vkDestroyImage vkDestroyImage;PFN_vkDestroyBuffer vkDestroyBuffer;PFN_vkFreeMemory vkFreeMemory;
    PFN_vkGetMemoryHostPointerPropertiesEXT vkGetMemoryHostPointerPropertiesEXT;
    PFN_vkCreateBuffer vkCreateBuffer;PFN_vkGetBufferMemoryRequirements vkGetBufferMemoryRequirements;
    PFN_vkAllocateMemory vkAllocateMemory;PFN_vkBindBufferMemory vkBindBufferMemory;
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
        assert(!g_npools);mtl_pool_add(p->mem,p->size);
        assert(g_npools==1 && g_pools[0].host_ref && g_pool_bytes==p->size);
    }
}
int main(void) {
    vk.vkDestroyBuffer=buffer_destroy;vk.vkFreeMemory=memory_free;
    vk.vkGetMemoryHostPointerPropertiesEXT=host_properties;vk.vkCreateBuffer=buffer_create;
    vk.vkGetBufferMemoryRequirements=requirements;vk.vkAllocateMemory=memory_allocate;vk.vkBindBufferMemory=memory_bind;
    vkc.host_pointer_alignment=4096;
    pool_t p;uint64_t bytes,pools;
    setup(&p,NVN_MEMORY_POOL_FLAGS_PHYSICAL|NVN_MEMORY_POOL_FLAGS_CPU_NO_ACCESS,1);
    memset(p.host,0x35,p.span);h_nvnMemoryPoolFinalize((NVNmemoryPool *)&p);
    assert(!p.magic && !p.host && p.mem==(void *)(uintptr_t)0x12340000);
    assert(mapped(expected_mapping)); // regression: old finalization unmapped before its queued import deletion
    totk_vpool_host_stats(&bytes,&pools);assert(bytes==expected_span && pools==1);
    memset(&p,0xa5,sizeof p); // guest object reuse cannot change captured ownership
    run_queued_delete();assert(mapped(expected_mapping) && !freed_imports);
    assert(linux_memory_busy((uintptr_t)expected_mapping,expected_span));
    dead_reap(UINT64_MAX);assert(mapped(expected_mapping)); // not assigned to a submitted fence yet
    dead_tag(7);dead_reap(6);assert(mapped(expected_mapping) && !freed_imports);
    dead_reap(7);assert(!mapped(expected_mapping) && freed_imports==1 && destroyed_buffers==1);
    assert(!linux_memory_busy((uintptr_t)expected_mapping,expected_span));
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
    // Guest-owned pages remain resident until the actual import has retired;
    // the pool finalizer never unmaps them, then the guest can discard safely.
    g_ok=1;guest=mmap(NULL,0x10000,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);assert(guest!=MAP_FAILED);
    g_linux_guest_lo=(uintptr_t)guest;g_linux_guest_hi=(uintptr_t)guest+0x10000;
    memset(guest,0x73,0x10000);mtl_pool_add(guest,0x10000);
    p=(pool_t){.magic=MAGIC('P','O','O','L'),.mem=guest,.size=0x10000};
    h_nvnMemoryPoolFinalize((NVNmemoryPool *)&p);
    assert(mapped(guest) && plat_decommit_guest((uintptr_t)guest,0x10000,0)==1 && *(unsigned char *)guest==0x73);
    dead_tag(12);dead_reap(11);assert(plat_decommit_guest((uintptr_t)guest,0x10000,0)==1);
    dead_reap(12);assert(mapped(guest) && !g_linux_memory_refs);
    assert(!plat_decommit_guest((uintptr_t)guest,0x10000,0));
    unsigned char residency[16];assert(!mincore(guest,0x10000,residency));
    for(unsigned i=0;i<16;i++)assert(!(residency[i]&1));
    for(unsigned i=0;i<0x10000;i++)assert(!((unsigned char *)guest)[i]);
    assert(!munmap(guest,0x10000));
    // Every import failure releases its host reference after any Vulkan cleanup.
    g_ok=1;guest=mmap(NULL,0x10000,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);assert(guest!=MAP_FAILED);
    for(import_failure=PROPERTY_FAIL;import_failure<=BIND_FAIL;import_failure++) {
        mtl_pool_add(guest,0x10000);assert(!g_npools && !g_pool_bytes && !g_linux_memory_refs);
    }
    // The candidate's environment gate: on a machine that cannot support the copies, enabling them keeps the
    // import this pool would always have had instead of failing to start, and reports the copies as off.
    setenv("TOTK_POOL_COPY","1",1);setenv("TOTK_POOL_IMPORT","0",1);
    for (int reason=0;reason<3;reason++) {   // 0 no watch, 1 discrete GPU, 2 pool shadows
        g_pool_copies=1;watch_ok=reason!=0;shadow_on=reason==2;
        vkc.props.deviceType=reason==1?VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU:VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU;
        guest=mmap(NULL,0x10000,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);assert(guest!=MAP_FAILED);
        memset(guest,0x5a,0x10000);
        unsigned imported_before=freed_imports;
        mtl_pool_add(guest,0x10000);
        assert(!g_pool_copies && g_npools==1 && g_pools[0].buf && !g_pools[0].cmap);   // imported, copies off
        mtl_pool_del(guest);dead_tag(13+reason);dead_reap(13+reason);
        assert(freed_imports==imported_before+1 && !g_npools && !g_linux_memory_refs);
        assert(!munmap(guest,0x10000));
    }
    vkc.props.deviceType=VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU;unsetenv("TOTK_POOL_COPY");
    // A copy that holds game memory's bytes cannot be dropped silently: with a pool already registered the
    // same loss of the environment is fatal. Checked in a child process because the harness dies by aborting.
    pid_t kid=fork();
    if (kid==0) {
        setenv("TOTK_POOL_COPY","1",1);g_pool_copies=1;watch_ok=0;
        void *at=mmap(NULL,0x10000,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
        memset(at,0x2b,0x10000);mtl_pool_add(at,0x10000);   // falls back, so a pool is now registered
        assert(g_npools==1);pool_copies_off("no asynchronous write watch");_exit(0);
    }
    int status=0;assert(waitpid(kid,&status,0)==kid);
    assert(WIFSIGNALED(status) && WTERMSIG(status)==SIGABRT);
    assert(!munmap(guest,0x10000));free(g_pools);
    totk_vpool_host_stats(&bytes,&pools);assert(!bytes && !pools && !g_dead && !g_dead_new && !g_linux_memory_refs);
    puts("Owned pool VM: actual imports/failures, GPU-fence retirement, guest discard after retirement, object reuse, CPU/null paths and the candidate environment gate PASS");
    return 0;
}
'''
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            source, binary = Path(folder)/'retirement.c', Path(folder)/'retirement'
            source.write_text(prefix.replace('PRODUCTION_POOL_TYPE',pool_type).replace('POOL_COPIES_GATE',gate)+vm+importing+registration+deletion+retirement+jobs+limits+queue+release+finalizer+
                              suffix.replace('REPLAY_POOL_RELEASE', replay))
            command = ['clang','-std=gnu17','-O1','-g','-pthread','-ffunction-sections','-fdata-sections',
                       '-fsanitize=address,undefined','-fno-sanitize-recover=all','-Wl,--gc-sections',
                       '-I'+str(ROOT),'-I'+str(ROOT/'src/gfx/nvn'),'-I'+str(ROOT/'src/gfx/nvn/include'),
                       str(source),'-o',str(binary)]
            result = subprocess.run(command,capture_output=True,text=True,timeout=40)
            self.assertEqual(result.returncode,0,result.stderr)
            subprocess.run([str(binary)],check=True,timeout=10)
