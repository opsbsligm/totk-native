"""Execute the production pool merge, including the CPU-write regression."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'linux', 'Linux pool-copy candidate')
class PoolCopies(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='pool-copy-', dir=Path.cwd())
        cls.addClassCleanup(cls.directory.cleanup)
        text = (ROOT / 'src/gfx/backend_vk.c').read_text()
        start = text.index('static const pool_ent *pool_find', text.index('// ---------------- pool copies'))
        end = text.index('// A pool as a host-visible copy', start)
        production = text[start:end]
        prefix = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint64_t VkBuffer;
typedef int vkb_rw;
#define LK_POOLS 0
#define GUEST_LO 0ull
#define GUEST_HI UINT64_MAX
typedef struct { uintptr_t lo,hi,base;VkBuffer buf;uint8_t *cmap;uint8_t cfilled;uint64_t cstamp,pc_sub,used_sub; } pool_ent;
static pool_ent g_pools[1];
static int g_npools=1,dirty,untracked,gpu_begin,gpu_end,allocation_fails,mark_fails;
static uint8_t *late_cpu_target,*late_end_target;
static vkb_rw g_pool_mu;
static uint64_t clock_ns,stamp=1;
static int vkb_pool_copies(void) {return 1;}
static void vkb_rw_read(vkb_rw *p,int kind) {(void)p;(void)kind;}
static void vkb_rw_read_end(vkb_rw *p) {(void)p;}
static uint64_t runtime_now_ns(void) {return ++clock_ns;}
static uint64_t nvn_dirty_now(void) {return ++stamp;}
static int nvn_dirty_since(const void *p,uint64_t n,uint64_t s) {(void)p;(void)n;(void)s;return 0;}
{NVN_SCAN_WHO}
static int nvn_dirty_runs(const void *p,uint64_t n,uint64_t s,size_t gap,void (*fn)(void*,size_t,size_t),void *ctx) {
    (void)p;(void)n;(void)s;(void)gap;
    if(untracked) return -1;
    if(dirty) {dirty=0;fn(ctx,0,4096);}return 0;
}
static void dm_guest_write_prepare(void *p,size_t n) {(void)p;(void)n;}
static void *nvn_dirty_gpu_write_begin(void *p,size_t n) {(void)n;gpu_begin++;return p;}
static void nvn_dirty_gpu_write_end(void *p) {
    assert(p);gpu_end++;
    if(late_end_target) {*late_end_target=99;late_end_target=NULL;dirty=0;}
}
static int nvn_dirty_mark_range(const void *p,size_t n) {(void)p;(void)n;dirty=1;return !mark_fails;}
static void inject_before_write(const void *p,size_t n) {
    if(late_cpu_target && (uintptr_t)late_cpu_target>=(uintptr_t)p &&
       (uintptr_t)late_cpu_target-(uintptr_t)p<n) {*late_cpu_target=99;late_cpu_target=NULL;}
}
static int interleaved_memcmp(const void *a,const void *b,size_t n) {
    int result=memcmp(a,b,n);inject_before_write(a,n);return result;
}
#define memcmp interleaved_memcmp
#define __atomic_compare_exchange_n(P,E,D,W,S,F) \
    (inject_before_write((P),sizeof *(P)),__atomic_compare_exchange_n((P),(E),(D),(W),(S),(F)))
#define die(...) do {fprintf(stderr,__VA_ARGS__);fputc('\n',stderr);exit(73);}while(0)
static void *snapshot_malloc(size_t n) {return allocation_fails?NULL:malloc(n);}
#define malloc snapshot_malloc
'''
        # The slice books its scans to a code location, so it needs those names. They are read out of the production
        # header rather than repeated here: a rename or a new location fails the test instead of hiding behind a copy.
        header = (ROOT / 'src/gfx/nvn/nvn_dirty.h').read_text().replace('\r', '')
        begin = header.index('enum { NVN_SCAN_WHO_TEX_STALE')
        who = header[begin:header.index('NVN_SCAN_WHO_COUNT };', begin) + len('NVN_SCAN_WHO_COUNT };')]
        assert 'void nvn_dirty_scan_who(int who);' in header
        prefix = prefix.replace('{NVN_SCAN_WHO}', who + '\nstatic void nvn_dirty_scan_who(int who) {(void)who;}')
        suffix = r'''
#undef malloc
#undef memcmp
#undef __atomic_compare_exchange_n
static const pool_ent *pool_find(uintptr_t addr,uint64_t n) {
    pool_ent *p=&g_pools[0];return addr>=p->lo && addr<=p->hi && n<=p->hi-addr?p:NULL;
}
static void sync_used(uint64_t fence) {g_pools[0].used_sub=fence;pc_sync(fence);}
int main(int argc,char **argv) {
    uint8_t *game=aligned_alloc(4096,8192),*copy=aligned_alloc(4096,8192);assert(game && copy);
    memset(game,10,8192);memset(copy,0,8192);
    uintptr_t lo=(uintptr_t)game;
    g_pools[0]=(pool_ent){.lo=lo,.hi=lo+8192,.base=lo,.buf=7,.cmap=copy};
    sync_used(1);assert(!memcmp(game,copy,8192));
    if(argc>1) {
        if(!strncmp(argv[1],"copy-race",9) || !strcmp(argv[1],"dirty-race")) {
            int unaligned=strstr(argv[1],"unaligned") || strstr(argv[1],"tail");
            size_t off=unaligned?1:0,bytes=unaligned?4094:4096;
            size_t target=strstr(argv[1],"tail")?4094:7;
            pc_pend_add(7,lo+off,bytes);sync_used(2);memset(copy+off,33,bytes);
            if(!strncmp(argv[1],"copy-race",9)) late_cpu_target=game+target;
            else late_end_target=game+target;
            pc_writeback(2);assert(!late_cpu_target && !late_end_target && game[target]==99);
            assert(game[target-1]==33 && game[target+1]==(target+1<off+bytes?33:10));
            if(unaligned) assert(game[0]==10 && game[4095]==10);
            sync_used(3);assert(copy[target]==99);
            free(g_pc_pend);free(copy);free(game);return 0;
        }
        if(!strcmp(argv[1],"watch-lost")) {untracked=1;sync_used(2);}
        if(!strcmp(argv[1],"pending-limit")) {
            g_pc_pend=calloc(65536,sizeof *g_pc_pend);assert(g_pc_pend);g_npc_pend=g_cappc_pend=65536;
            pc_pend_add(7,lo,1);
        }
        pc_pend_add(7,lo,128);
        if(!strcmp(argv[1],"snapshot-limit")) g_pc_pend[0].hi=lo+PC_SNAP_MAX+1;
        if(!strcmp(argv[1],"snapshot-memory")) allocation_fails=1;
        sync_used(2);
        if(!strcmp(argv[1],"snapshot-missing")) {free(g_pc_pend[0].was);g_pc_pend[0].was=NULL;pc_writeback(2);}
        if(!strcmp(argv[1],"writeback-watch-lost")) {mark_fails=1;pc_writeback(2);}
        return 74;
    }
    // One range is bound twice. A later CPU byte survives GPU writeback;
    // neighbouring bytes still receive the GPU's output.
    pc_pend_add(7,lo+256,128);pc_pend_add(7,lo+256,128);assert(g_npc_pend==1);
    sync_used(2);assert(g_pc_snapshot_live==128);
    memset(copy+256,30,128);game[260]=40;pc_writeback(2);
    assert(game[259]==30 && game[260]==40 && game[261]==30 && !g_npc_pend && !g_pc_snapshot_live);
    dirty=1;sync_used(3);assert(copy[260]==40 && copy[261]==30);
    // An earlier GPU range is still pending. Only the CPU's changed byte
    // enters that range at the next sync; its other GPU bytes stay current.
    pc_pend_add(7,lo+200,20);sync_used(4);memset(copy+200,80,20);game[202]=90;
    dirty=1;sync_used(5);assert(copy[201]==80 && copy[202]==90 && copy[203]==80);
    pc_writeback(4);assert(game[201]==80 && game[202]==90 && game[203]==80);
    // Two overlapping submissions: the first GPU output advances the
    // second snapshot, so the second output is not mistaken for CPU data.
    pc_pend_add(7,lo+100,20);sync_used(6);
    pc_pend_add(7,lo+100,20);sync_used(7);assert(g_npc_pend==2);
    memset(copy+100,50,20);pc_writeback(6);assert(game[100]==50 && g_npc_pend==1);
    memset(copy+100,60,20);game[105]=70;pc_writeback(7);
    assert(game[104]==60 && game[105]==70 && game[106]==60);
    // The address now belongs to another buffer. An old completion cannot
    // overwrite the new pool, and its snapshot is still released.
    pc_pend_add(7,lo+512,16);sync_used(8);g_pools[0].buf=8;
    memset(copy+512,99,16);pc_writeback(8);
    assert(game[512]==10 && !g_npc_pend && !g_pc_snapshot_live && gpu_begin==gpu_end);
    // A deleted pool can still have a pending completion when its address is
    // reused. That old buffer must not reserve bytes in the new pool's first
    // CPU-to-GPU fill, nor in a later dirty-page synchronization.
    pc_pend_add(8,lo+600,16);sync_used(9);
    g_pools[0].buf=9;g_pools[0].cfilled=0;
    memset(game,77,8192);memset(copy,0,8192);
    sync_used(10);assert(!memcmp(game,copy,8192));
    memset(game+600,10,16);dirty=1;
    sync_used(11);assert(!memcmp(game,copy,8192));
    pc_writeback(11);assert(!g_npc_pend && !g_pc_snapshot_live);
    free(g_pc_pend);free(copy);free(game);return 0;
}
'''
        source = Path(cls.directory.name) / 'pool.c'
        cls.binary = Path(cls.directory.name) / 'pool'
        source.write_text(prefix + production + suffix)
        subprocess.run(['cc', '-std=gnu17', '-O1', '-pthread', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', str(source), '-o', str(cls.binary)],
                       check=True, capture_output=True, text=True, timeout=40)

    def test_copy_merge_late_cpu_writes_and_pool_identity(self):
        subprocess.run([str(self.binary)], check=True, timeout=8)

    def test_cpu_write_between_comparison_and_writeback_survives(self):
        for case in ['copy-race', 'copy-race-unaligned', 'copy-race-tail']:
            with self.subTest(case=case):
                subprocess.run([str(self.binary), case], check=True, timeout=8)

    def test_cpu_write_during_gpu_dirty_clear_reaches_next_submission(self):
        subprocess.run([str(self.binary), 'dirty-race'], check=True, timeout=8)

    def test_unsafe_conditions_fail_explicitly(self):
        for case in ['watch-lost', 'pending-limit', 'snapshot-limit', 'snapshot-memory',
                     'snapshot-missing', 'writeback-watch-lost']:
            with self.subTest(case=case):
                result = subprocess.run([str(self.binary), case], capture_output=True, text=True, timeout=8)
                self.assertEqual(result.returncode, 73, result.stderr)
                self.assertIn('pool copies:', result.stderr)
