// [Windows port] Dirty-page tracking of guest memory pools (the API of MacNativeGames' nvn_dirty.h) through the guest
// window's write watch (MEM_WRITE_WATCH, src/runtime/platform/windows.c plat_written_pages) instead of write-protecting
// pages and catching the faults. The OS marks every page anything writes (the game, host code, file reads by the kernel),
// so there are no protection changes, no fault handler and no host pre-write hook.
// As in MacNativeGames, each page of a tracked pool has a generation: the generation of its last observed write.
// nvn_dirty_since() collects the pages written since the last look (resetting their watch bits) and gives them a new
// generation, then compares the range's generations with the caller's stamp.
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "../host/dm.h"
#include "nvn_dirty.h"

int plat_written_pages(uint64_t addr, uint64_t size, uint64_t *pages, int max, uint64_t *page);

#define MAX_RANGE 16384   // MacNativeGames: about 3,900 live pools in TOTK's world
typedef struct { uintptr_t base, end; _Atomic uint64_t *gen; _Atomic int live, watched; _Atomic uint64_t epoch; } range_t;   // watched: the OS reports its writes
static range_t g_r[MAX_RANGE];
static _Atomic int g_nr, g_live, g_live_peak;
static _Atomic uint64_t g_now = 1, g_adds_total, g_scans, g_scan_pages, g_scan_ns;
static pthread_mutex_t g_slot_mu = PTHREAD_MUTEX_INITIALIZER;
static int g_watch = -1;   // write watch available (the window was reserved with it)

// Which code a scan is booked to (nvn_dirty.h). A caller names its location before the logic that looks at the write
// watch, so the log can say where the kernel calls come from: 2026-11-23 (case-copy, Great Plateau) the game spends
// 2.7 ms a frame in them -- 556 ioctls at about 4.5 us -- and nothing in the log said who was asking.
static _Thread_local int t_scan_who = NVN_SCAN_WHO_OTHER;
static _Atomic uint64_t g_who_calls[NVN_SCAN_WHO_COUNT], g_who_ns[NVN_SCAN_WHO_COUNT];
void nvn_dirty_scan_who(int who) { t_scan_who = who >= 0 && who < NVN_SCAN_WHO_COUNT ? who : NVN_SCAN_WHO_OTHER; }
void nvn_dirty_scan_stats(uint64_t *calls, uint64_t *ns, int max) {
    for (int i = 0; i < max && i < NVN_SCAN_WHO_COUNT; i++) {
        calls[i] = atomic_load(&g_who_calls[i]);
        ns[i] = atomic_load(&g_who_ns[i]);
    }
}

static _Thread_local int t_last;   // the range this thread found last (most lookups repeat it)
static range_t *find(uintptr_t a) {
    int n = atomic_load(&g_nr), k = t_last;
    if (k < n && atomic_load_explicit(&g_r[k].live, memory_order_acquire) && a >= g_r[k].base && a < g_r[k].end) return &g_r[k];
    for (int i = 0; i < n; i++)
        if (atomic_load_explicit(&g_r[i].live, memory_order_acquire) && a >= g_r[i].base && a < g_r[i].end) { t_last = i; return &g_r[i]; }
    return NULL;
}

// Scans once per epoch (nvn_dirty_epoch_begin, a GPU submission being recorded): the first look at a range scans all of
// it, later looks in the epoch use the generations gathered then. The game writes what a submission uses before
// submitting it, so one look per submission sees those writes; per-texture and per-pool scans were hundreds of
// GetWriteWatch calls a submission (~9% of the recording thread, Great Sky Island, 2026-10-24).
// The dedup used to belong to the thread that began the epoch, so with the submission recorded on several threads every
// one of them re-scanned the same pools: Deck (case-copy, Great Plateau, 2026-11-24) 1069 tex_stale scans a frame
// costing 4.59 ms -- 20% of the frame -- where the same build on one recording thread asks 433 times. Now every thread
// recording that submission shares the one look (nvn_dirty_epoch_join); whether a range was already seen is decided by
// the epoch number itself, so a thread joining late still gets the answer gathered by another. Threads outside a
// submission (the retire thread's copy back of GPU writes) do not join and scan every time, as before.
static _Atomic uint64_t g_epoch;
static _Atomic uint64_t g_notice_epoch;  // explicit CPU flushes, independent of OS write watch
static _Thread_local int t_epoch_thread;
static _Atomic int g_epoch_seen;   // at least one submission has begun: an epoch exists to share
void nvn_dirty_epoch_begin(void) { t_epoch_thread = 1; atomic_store(&g_epoch_seen, 1); atomic_fetch_add(&g_epoch, 1); }
// A thread that records part of the submission in progress may use the look another thread already made. It returns what
// it had, for the caller to restore with nvn_dirty_epoch_leave(), so the thread that began the epoch keeps it and a
// thread that already owned one is unaffected. Joining before any submission exists leaves the thread scanning, as it
// did on its own thread before.
int nvn_dirty_epoch_join(void) {
    int saved = t_epoch_thread;
    t_epoch_thread = atomic_load(&g_epoch_seen);
    return saved;
}
void nvn_dirty_epoch_leave(int saved) { t_epoch_thread = saved; }

// Pages of [a, a+len) written since the last scan get a new generation; their watch bits are reset.
static void scan_pages(range_t *r, uintptr_t a, size_t len, int count);
enum { SCAN_LOCKS = 64 };
static pthread_mutex_t g_scan_locks[SCAN_LOCKS];
static pthread_once_t g_scan_locks_once = PTHREAD_ONCE_INIT;

static void init_scan_locks(void) {
    for (int i = 0; i < SCAN_LOCKS; i++)
        if (pthread_mutex_init(&g_scan_locks[i], NULL)) die("dirty tracking: scan mutex");
}

static void scan(range_t *r, uintptr_t a, size_t len, int count) {
    uint64_t epoch = count && t_epoch_thread ? atomic_load(&g_epoch) : 0;
    if (epoch && atomic_load_explicit(&r->epoch, memory_order_acquire) == epoch) return;
    if (pthread_once(&g_scan_locks_once, init_scan_locks)) die("dirty tracking: scan mutex initialization");
    pthread_mutex_t *lock = &g_scan_locks[(size_t)(r - g_r) % SCAN_LOCKS];
    pthread_mutex_lock(lock);
    if (!epoch) scan_pages(r, a, len, count);
    else if (atomic_load_explicit(&r->epoch, memory_order_relaxed) != epoch) {
        // The OS clears watch bits as it returns them. A second scanner must wait until the first has recorded
        // the generations, or it may observe cleared bits and unpublished generations at the same time.
        scan_pages(r, r->base, r->end - r->base, count);
        atomic_store_explicit(&r->epoch, epoch, memory_order_release);
    }
    pthread_mutex_unlock(lock);
}
static void scan_pages(range_t *r, uintptr_t a, size_t len, int count) {
    uint64_t pages[512], pg = 4096;
    uintptr_t lo = a & ~(uintptr_t)0xfff, hi = (a + len + 0xfff) & ~(uintptr_t)0xfff;
    if (lo < r->base) lo = r->base;
    if (hi > r->end) hi = r->end;
    while (lo < hi) {
        struct timespec t0, t1;
        clock_gettime(CLOCK_MONOTONIC, &t0);
        int n = plat_written_pages(lo, hi - lo, pages, 512, &pg);
        clock_gettime(CLOCK_MONOTONIC, &t1);
        uint64_t spent = (uint64_t)(t1.tv_sec - t0.tv_sec) * 1000000000u + (uint64_t)(t1.tv_nsec - t0.tv_nsec);
        atomic_fetch_add(&g_scan_ns, spent);
        if (n < 0) {   // this range only (it used to switch tracking off for every pool, silently)
            if (atomic_exchange(&r->watched, 0)) {
                static _Atomic int said;
                if (atomic_fetch_add(&said, 1) < 8) LOG("dirty tracking: no write watch for pool %p..%p: treated as unchanged", (void *)r->base, (void *)r->end);
            }
            return;
        }
        atomic_fetch_add(&g_scans, 1);
        atomic_fetch_add(&g_who_calls[t_scan_who], 1);
        atomic_fetch_add(&g_who_ns[t_scan_who], spent);
        uint64_t g = n && count ? atomic_fetch_add(&g_now, 1) + 1 : 0;
        for (int i = 0; i < n; i++) {
            uintptr_t p = (pages[i] - r->base) / 4096;
            if (count) atomic_store(&r->gen[p], g);
        }
        atomic_fetch_add(&g_scan_pages, (uint64_t)n);
        if (n < 512) break;   // all of the range reported; with 512 there may be more: from after the last one
        lo = (uintptr_t)pages[n - 1] + (uintptr_t)pg;
    }
}

void nvn_dirty_add_range(const void *mem, size_t size) {
    if (g_watch < 0) {   // probe once on a page inside the guest window (the main module's base)
        uint64_t p, pg;
        g_watch = plat_written_pages(0x0800000000ull, 4096, &p, 1, &pg) >= 0;
        if (!g_watch) LOG("dirty tracking: the guest window has no write watch; every use re-uploads");
    }
    uintptr_t base = (uintptr_t)mem & ~(uintptr_t)0xfff, end = ((uintptr_t)mem + size + 0xfff) & ~(uintptr_t)0xfff;
    size_t npages = (end - base) / 4096;
    _Atomic uint64_t *gen = calloc(npages ? npages : 1, sizeof *gen);
    if (!gen) die("dirty tracking: allocation");
    pthread_mutex_lock(&g_slot_mu);
    int slot = -1, n = atomic_load(&g_nr);
    for (int i = 0; i < n; i++) if (!atomic_load(&g_r[i].live)) { slot = i; break; }
    if (slot < 0) {
        if (n == MAX_RANGE) { pthread_mutex_unlock(&g_slot_mu); free(gen); LOG("dirty tracking: more than %d pools", MAX_RANGE); return; }
        slot = n; atomic_store(&g_nr, n + 1);
    }
    range_t *r = &g_r[slot];
    free(r->gen);
    r->base = base; r->end = end; r->gen = gen;
    atomic_store(&r->watched, 1);
    atomic_store(&r->epoch, 0);
    atomic_store_explicit(&r->live, 1, memory_order_release);
    pthread_mutex_unlock(&g_slot_mu);
    scan(r, base, end - base, 0);   // forget writes from before the pool existed
    atomic_fetch_add(&g_adds_total, 1);
    int live = atomic_fetch_add(&g_live, 1) + 1, peak = atomic_load(&g_live_peak);
    while (live > peak && !atomic_compare_exchange_weak(&g_live_peak, &peak, live)) {}
}

void nvn_dirty_remove_range(const void *mem) {
    pthread_mutex_lock(&g_slot_mu);
    range_t *r = find((uintptr_t)mem & ~(uintptr_t)0xfff);
    if (r) { atomic_store(&r->live, 0); atomic_fetch_sub(&g_live, 1); }
    pthread_mutex_unlock(&g_slot_mu);
}

// Explicit flush notifications are positive evidence of CPU writes, even on
// systems without write watch. Zero here means "no notified write", NOT clean.
uint64_t nvn_dirty_notice_epoch(void) {
    return atomic_load_explicit(&g_notice_epoch, memory_order_acquire);
}
int nvn_dirty_mark_range(const void *addr, size_t len) {
    uintptr_t a = (uintptr_t)addr;
    if (!len) return 0;
    if (len > UINTPTR_MAX - a) return 0;
    pthread_mutex_lock(&g_slot_mu);
    range_t *r = find(a);
    if (!r || a + len > r->end) { pthread_mutex_unlock(&g_slot_mu); return 0; }
    uintptr_t first = (a - r->base) / 4096;
    uintptr_t end = (a + len - r->base + 4095) / 4096;
    uint64_t generation = atomic_fetch_add(&g_now, 1) + 1;
    for (uintptr_t p = first; p < end; p++) atomic_store(&r->gen[p], generation);
    atomic_fetch_add_explicit(&g_notice_epoch, 1, memory_order_release);
    pthread_mutex_unlock(&g_slot_mu);
    return 1;
}
int nvn_dirty_marked_since(const void *addr, size_t len, uint64_t stamp) {
    uintptr_t a = (uintptr_t)addr;
    if (!len) return 0;
    if (len > UINTPTR_MAX - a) return -1;
    pthread_mutex_lock(&g_slot_mu);
    range_t *r = find(a);
    if (!r || a + len > r->end) { pthread_mutex_unlock(&g_slot_mu); return -1; }
    uintptr_t first = (a - r->base) / 4096;
    uintptr_t end = (a + len - r->base + 4095) / 4096;
    int changed = 0;
    for (uintptr_t p = first; p < end; p++)
        if (atomic_load(&r->gen[p]) > stamp) { changed = 1; break; }
    pthread_mutex_unlock(&g_slot_mu);
    return changed;
}

int nvn_dirty_tracked(const void *addr, size_t len) {
    range_t *r = find((uintptr_t)addr);
    return r && g_watch > 0 && atomic_load(&r->watched) && (uintptr_t)addr + len <= r->end;
}

void nvn_dirty_protect(const void *addr, size_t len) {
    range_t *r = find((uintptr_t)addr);
    if (r) scan(r, (uintptr_t)addr, len, 1);   // writes up to now belong to the content being uploaded
}

uint64_t nvn_dirty_now(void) { return atomic_load(&g_now); }

int nvn_dirty_since(const void *addr, size_t len, uint64_t stamp) {
    range_t *r = find((uintptr_t)addr);
    if (!r || g_watch <= 0 || !atomic_load(&r->watched)) return 1;   // untracked: always treat as changed
    scan(r, (uintptr_t)addr, len, 1);
    uintptr_t lo = ((uintptr_t)addr - r->base) / 4096, hi = ((uintptr_t)addr + len - r->base + 4095) / 4096;
    for (uintptr_t p = lo; p < hi; p++) if (atomic_load(&r->gen[p]) > stamp) return 1;
    return 0;
}

// Runs of pages of [addr, addr+len) written since `stamp`: fn(ctx, offset from addr, bytes), in order; runs less than
// `gap` bytes apart are merged (fewer, larger copies). -1: not tracked (its writes cannot be told).
int nvn_dirty_runs(const void *addr, size_t len, uint64_t stamp, size_t gap, void (*fn)(void *ctx, size_t off, size_t n), void *ctx) {
    range_t *r = find((uintptr_t)addr);
    if (!r || g_watch <= 0 || !atomic_load(&r->watched) || (uintptr_t)addr + len > r->end) return -1;
    scan(r, (uintptr_t)addr, len, 1);
    uintptr_t a = (uintptr_t)addr, first = (a - r->base) / 4096, last = (a + len - r->base + 4095) / 4096;
    uintptr_t run_lo = 0, run_hi = 0;   // pages, relative to the range base; run_hi 0: none open
    for (uintptr_t p = first; p < last; p++) {
        if (atomic_load(&r->gen[p]) <= stamp) continue;
        if (run_hi && (p - run_hi) * 4096 <= gap) { run_hi = p + 1; continue; }
        if (run_hi) {
            uintptr_t lo = r->base + run_lo * 4096 < a ? a : r->base + run_lo * 4096, hi = r->base + run_hi * 4096 > a + len ? a + len : r->base + run_hi * 4096;
            fn(ctx, lo - a, hi - lo);
        }
        run_lo = p; run_hi = p + 1;
    }
    if (run_hi) {
        uintptr_t lo = r->base + run_lo * 4096 < a ? a : r->base + run_lo * 4096, hi = r->base + run_hi * 4096 > a + len ? a + len : r->base + run_hi * 4096;
        fn(ctx, lo - a, hi - lo);
    }
    return 0;
}

// The GPU writes guest memory (readbacks): those writes are not the CPU's. The pages are scanned without a new
// generation afterwards (a CPU write racing with it would be lost: accepted, as the readback overwrites them anyway).
typedef struct { void *addr; size_t len; } gpu_tok;
void *nvn_dirty_gpu_write_begin(void *addr, size_t len) {
    gpu_tok *t = malloc(sizeof *t);
    if (t) *t = (gpu_tok){addr, len};
    return t;
}
void nvn_dirty_gpu_write_end(void *tok) {
    gpu_tok *t = tok;
    if (!t) return;
    // The look that forgets the GPU's own writes is its own cost, whatever logic asked for the write.
    int saved = t_scan_who;
    t_scan_who = NVN_SCAN_WHO_GPU_WRITE;
    range_t *r = find((uintptr_t)t->addr);
    if (r) scan(r, (uintptr_t)t->addr, t->len, 0);
    t_scan_who = saved;
    free(t);
}

int nvn_dirty_recent(uintptr_t lo, uintptr_t hi, nvn_dirty_rec *out, int max) { (void)lo; (void)hi; (void)out; (void)max; return 0; }
void nvn_dirty_stat(int *live, int *peak, int *cap) { *live = atomic_load(&g_live); *peak = atomic_load(&g_live_peak); *cap = MAX_RANGE; }
void nvn_dirty_stats(uint64_t *faults, uint64_t *preps) { *faults = atomic_load(&g_scan_pages); *preps = 0; }
// The time is the cost of the kernel calls themselves (the ioctls), not the bookkeeping around them; it was a
// hardcoded 0 since the Linux port, so the scan was the one per-frame cost that could not be seen in the log.
void nvn_dirty_mp_stats(uint64_t *calls, uint64_t *pages, uint64_t *ns) { *calls = atomic_load(&g_scans); *pages = atomic_load(&g_scan_pages); *ns = atomic_load(&g_scan_ns); }
void nvn_dirty_slot_stats(int *live, int *used_slots, uint64_t *adds_total) {
    *live = atomic_load(&g_live); *used_slots = atomic_load(&g_nr); *adds_total = atomic_load(&g_adds_total);
}
void dm_guest_write_prepare(void *addr, size_t n) { (void)addr; (void)n; }   // the OS tracks host writes as well
