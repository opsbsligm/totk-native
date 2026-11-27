// The shared write-watch epoch (src/gfx/nvn/nvn_dirty_win.c) tested against a fake write watch.
// A submission's recording can run on several threads, and every one of them asks the same question about the same
// pools ("does this texture's game memory hold new bytes"). The dedup used to belong to the thread that began the
// epoch, so each thread paid its own kernel look: on the Deck, 1069 tex_stale scans a frame costing 4.59 ms -- 20% of
// the frame -- where the same build on one recording thread asks 433 times (case-copy, Great Plateau, 2026-11-24).
// These runs hold two things: one submission pays for one look per pool whoever asks, and sharing the answer never loses
// a write, not even when a thread joins while another is still inside its look.
#define _GNU_SOURCE
#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "../src/gfx/nvn/nvn_dirty.h"

enum { PAGES = 8 };
static uint8_t *g_pool;
static pthread_mutex_t g_fake_mu = PTHREAD_MUTEX_INITIALIZER;
static int g_written[PAGES];              // the OS's watch bits
static _Atomic int g_calls;               // kernel looks made
static _Atomic int g_hold, g_inside;      // pause after consuming the OS's bits, before returning the pages

static void mark_written(int page) {
    pthread_mutex_lock(&g_fake_mu);
    g_written[page] = 1;
    pthread_mutex_unlock(&g_fake_mu);
}

// The contract plat_written_pages makes on Linux (linux_watch.h) and Windows (GetWriteWatch): the pages written since
// the last look, in order, with their watch bits cleared.
int plat_written_pages(uint64_t addr, uint64_t size, uint64_t *pages, int max, uint64_t *page) {
    atomic_fetch_add(&g_calls, 1);
    int hold = atomic_exchange(&g_hold, 0);
    *page = 4096;
    int n = 0;
    uint64_t base = (uint64_t)(uintptr_t)g_pool;
    pthread_mutex_lock(&g_fake_mu);
    for (int p = 0; p < PAGES; p++) {
        uint64_t at = base + (uint64_t)p * 4096;
        if (at < addr || at >= addr + size || !g_written[p]) continue;
        if (n == max) break;
        pages[n++] = at;
        g_written[p] = 0;
    }
    pthread_mutex_unlock(&g_fake_mu);
    if (hold) {
        atomic_store(&g_inside, 1);
        struct timespec ts = {.tv_nsec = 75 * 1000000};
        nanosleep(&ts, NULL);
    }
    return n;
}

void plat_fatal_notice(void) {}

static int calls(void) { return atomic_load(&g_calls); }

// ---- the threads that record one submission together
typedef struct { int join, iterations, page, expect, saw; } worker_arg;

static void *worker(void *arg) {
    worker_arg *w = arg;
    int saved = w->join ? nvn_dirty_epoch_join() : 0;
    for (int i = 0; i < w->iterations; i++) {
        int stale = nvn_dirty_since(g_pool + (size_t)w->page * 4096, 4096, 0);
        if (stale) w->saw++;
        if (w->expect >= 0 && stale != w->expect) {
            fprintf(stderr, "epoch: a lookup answered %d where the pool was written before the submission\n", stale);
            exit(1);
        }
    }
    if (w->join) nvn_dirty_epoch_leave(saved);
    return NULL;
}

// The submitting thread looks first (as mtl_sub_begin does), then the recording threads join it: they must use that one
// answer rather than each paying for the same pools again.
static void test_one_look_per_submission(void) {
    atomic_store(&g_calls, 0);
    mark_written(3);
    nvn_dirty_epoch_begin();
    if (!nvn_dirty_since(g_pool + 3 * 4096, 4096, 0)) { fprintf(stderr, "epoch: the submission's own look missed the write\n"); exit(1); }
    int first = calls();
    enum { THREADS = 6 };
    pthread_t t[THREADS];
    worker_arg a[THREADS];
    for (int i = 0; i < THREADS; i++) a[i] = (worker_arg){.join = 1, .iterations = 200, .page = 3, .expect = 1};
    for (int i = 0; i < THREADS; i++) assert(pthread_create(&t[i], NULL, worker, &a[i]) == 0);
    for (int i = 0; i < THREADS; i++) pthread_join(t[i], NULL);
    int extra = calls() - first;
    if (extra) { fprintf(stderr, "epoch: the recording threads made %d looks of their own for one pool\n", extra); exit(1); }
    printf("epoch: %d threads x 200 lookups shared the submission's one look\n", THREADS);
}

// A thread that joins while another is still inside its look must not take that look's in-progress answer as final: the
// pages it cleared before recording them would make a written pool look unchanged.
static void test_a_late_join_sees_the_finished_answer(void) {
    atomic_store(&g_calls, 0);
    mark_written(5);
    nvn_dirty_epoch_begin();
    atomic_store(&g_inside, 0);
    atomic_store(&g_hold, 1);
    pthread_t first, late;
    worker_arg a = {.join = 1, .iterations = 1, .page = 5, .expect = 1};
    assert(pthread_create(&first, NULL, worker, &a) == 0);
    struct timespec ts = {.tv_nsec = 1000000};
    for (int i = 0; i < 200 && !atomic_load(&g_inside); i++) nanosleep(&ts, NULL);
    assert(atomic_load(&g_inside));
    worker_arg b = {.join = 1, .iterations = 50, .page = 5, .expect = 1};
    assert(pthread_create(&late, NULL, worker, &b) == 0);
    pthread_join(first, NULL);
    pthread_join(late, NULL);
    assert(b.saw == b.iterations && calls() == 1);
    printf("epoch: a thread joining a look in progress shared its first answer\n");
}

// A thread outside the submission (the retire thread copying GPU writes back) is not part of its epoch: every look of
// its own is made, as before.
static void test_a_thread_outside_the_submission_still_looks(void) {
    atomic_store(&g_calls, 0);
    mark_written(1);
    nvn_dirty_epoch_begin();
    if (!nvn_dirty_since(g_pool + 4096, 4096, 0)) { fprintf(stderr, "epoch: the pool's write was not recorded\n"); exit(1); }
    int first = calls();
    enum { THREADS = 4 };
    pthread_t t[THREADS];
    worker_arg a[THREADS];
    for (int i = 0; i < THREADS; i++) a[i] = (worker_arg){.join = 0, .iterations = 20, .page = 1, .expect = 1};
    for (int i = 0; i < THREADS; i++) assert(pthread_create(&t[i], NULL, worker, &a[i]) == 0);
    for (int i = 0; i < THREADS; i++) pthread_join(t[i], NULL);
    int extra = calls() - first;
    if (extra != THREADS * 20) { fprintf(stderr, "epoch: threads outside the submission made %d looks, want %d\n", extra, THREADS * 20); exit(1); }
    printf("epoch: outside a submission every look is still made (%d looks, as before)\n", extra);
}

// The epoch belongs to one submission: the next one looks again, so a write landing during a submission is not lost.
static void test_the_next_epoch_looks_again(void) {
    uint64_t stamp = nvn_dirty_now();
    nvn_dirty_epoch_begin();
    mark_written(7);
    if (!nvn_dirty_since(g_pool + 7 * 4096, 4096, stamp)) { fprintf(stderr, "epoch: a write newer than the upload was missed\n"); exit(1); }
    int at = calls();
    if (!nvn_dirty_since(g_pool + 7 * 4096, 4096, stamp)) { fprintf(stderr, "epoch: the answer did not outlive the look that gathered it\n"); exit(1); }
    if (calls() != at) { fprintf(stderr, "epoch: the second look in one submission re-scanned\n"); exit(1); }
    stamp = nvn_dirty_now();   // what the submission uploaded: that write is in it now
    nvn_dirty_epoch_begin();
    if (nvn_dirty_since(g_pool + 7 * 4096, 4096, stamp)) { fprintf(stderr, "epoch: a write already uploaded was reported again\n"); exit(1); }
    if (calls() == at) { fprintf(stderr, "epoch: a new submission reused the previous submission's answer\n"); exit(1); }
    printf("epoch: one look per submission, a new submission looks again\n");
}

int main(void) {
    g_pool = aligned_alloc(4096, PAGES * 4096);
    assert(g_pool);
    memset(g_pool, 0, PAGES * 4096);
    nvn_dirty_add_range(g_pool, PAGES * 4096);
    if (!nvn_dirty_tracked(g_pool, 4096)) { fprintf(stderr, "epoch: the fake write watch was not accepted\n"); return 1; }
    test_one_look_per_submission();
    test_a_late_join_sees_the_finished_answer();
    test_a_thread_outside_the_submission_still_looks();
    test_the_next_epoch_looks_again();
    printf("OK\n");
    return 0;
}
