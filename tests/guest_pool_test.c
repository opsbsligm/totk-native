/* SPDX-License-Identifier: MIT */
/* Real guest memory SVCs with synthetic module metadata, no guest game bytes. */
#define _GNU_SOURCE 1
#include <assert.h>
#include <stdatomic.h>
#include <stdlib.h>
#include "../src/host/svc.c"

Module g_modules[MAX_MODULES];
int g_nmodules;
static unsigned char exception_storage[0x1000];
void *hle_alloc(uint64_t size) { assert(size == sizeof exception_storage); return exception_storage; }
int svc_thread(int num, uint64_t *r) { (void)num; (void)r; return 0; }
int runtime_ipc_svc(unsigned num, uint64_t *r) { (void)num; (void)r; return 0; }
uint64_t runtime_now_ns(void) { return 1; }
_Noreturn void runtime_fail(const char *message) { fprintf(stderr, "%s\n", message); abort(); }
void plat_commit(uint64_t address, uint64_t size) { (void)address; (void)size; abort(); }
int plat_protect(uint64_t address, uint64_t size, int protection) {
    (void)address; (void)size; (void)protection; abort();
}

static uint64_t used(unsigned id) {
    uint64_t r[32] = {0}; r[1] = id;
    assert(!runtime_svc(0x29, r, 0) && !r[0]);
    return r[1];
}
static uint64_t resize(uint64_t size) {
    uint64_t r[32] = {0}; r[1] = size;
    uint64_t result = runtime_svc(0x01, r, 0);
    assert(result == r[0]);
    assert(r[1] == (result ? size : HEAP_START));
    return result;
}
static uint64_t map(int unmap, uint64_t address, uint64_t size) {
    uint64_t r[32] = {address, size};
    uint64_t result = runtime_svc(unmap ? 0x2d : 0x2c, r, 0);
    assert(result == r[0]); return result;
}
static void query_heap(void) {
    struct { uint64_t base, size; uint32_t state, attr, perm, ipc, device, pad; } info;
    uint64_t address = HEAP_START + 0x300000;
    uint64_t r[32] = {(uintptr_t)&info, 0, address};
    assert(!runtime_svc(0x06, r, 0) && !r[0]);
    assert(info.base <= address && address - info.base < info.size);
    assert(info.state == 0 || info.state == 5);
    if (info.state == 5) assert(info.base == HEAP_START && info.size == 0x400000 && info.perm == 3);
    else assert(info.base == HEAP_START + 0x200000);
}
static void reset(void) {
    pthread_mutex_lock(&memory_lock);
    heap_size = 0; alias_bytes = 0; nstack_maps = 0;
    memset(alias_pages, 0, sizeof alias_pages);
    pthread_mutex_unlock(&memory_lock);
}

static void boundaries(void) {
    const uint64_t unit = 0x200000, image = runtime_image_bytes();
    reset(); assert(used(6) == APP_POOL && used(21) == APP_POOL);
    assert(!resize(unit));
    uint64_t aliases = APP_POOL - image - unit;
    assert(!(aliases & 4095));
    assert(!map(0, ALIAS_START, aliases));
    assert(used(7) == APP_POOL && used(22) == APP_POOL);
    /* Each request fits without the other allocation, but their sum must not. */
    assert(resize(2 * unit) == 0x10801);
    assert(heap_size == unit && used(7) == APP_POOL);
    assert(map(0, ALIAS_START + aliases, 4096) == 0x10801);
    assert(used(22) == APP_POOL);
    assert(!map(0, ALIAS_START, aliases)); /* remapping owned pages costs zero */
    assert(!map(1, ALIAS_START, unit));
    assert(used(7) == APP_POOL - unit);
    assert(!resize(2 * unit) && used(22) == APP_POOL);
    assert(!resize(unit));
    assert(!map(0, ALIAS_START, unit));
    assert(used(7) == APP_POOL);
    assert(!map(1, ALIAS_START, aliases));
    assert(used(7) == image + unit);
    assert(resize(1) == 0xca01 && resize(HEAP_CAP + unit) == 0xd001);
    assert(resize(NX_HEAP_REQUEST_LIMIT) == 0xca01);
    assert(resize(UINT64_MAX & ~(unit - 1)) == 0xca01);
    assert(used(7) == image + unit);
    assert(!resize(0) && used(7) == image);
}

static void borrowed_tail(void) {
    const uint64_t unit = 0x200000, image = runtime_image_bytes();
    reset(); assert(!resize(3 * unit));
    /* Seed a live stack's bookkeeping without allocating or copying guest RAM.
       The resize itself still enters the actual SVC and production registry. */
    pthread_mutex_lock(&memory_lock);
    stack_maps[0] = (StackMap){STACK_START, HEAP_START + 2 * unit, 4096}; nstack_maps = 1;
    pthread_mutex_unlock(&memory_lock);
    assert(resize(2 * unit) == 0xd401 && used(7) == image + 3 * unit);
    assert(!resize(4 * unit) && !resize(3 * unit)); /* keep the borrowed page */
    pthread_mutex_lock(&memory_lock); nstack_maps = 0; pthread_mutex_unlock(&memory_lock);
    assert(!resize(2 * unit) && used(7) == image + 2 * unit);
}

static void overlaps(void) {
    reset(); uint64_t image = runtime_image_bytes();
    assert(!map(0, ALIAS_START, 8192));
    assert(!map(0, ALIAS_START + 4096, 8192));
    assert(used(7) == image + 12288);
    assert(!map(1, ALIAS_START + 4096, 4096));
    assert(!map(1, ALIAS_START + 4096, 4096));
    assert(used(22) == image + 8192);
    assert(!map(1, ALIAS_START, 12288) && used(7) == image);
    assert(map(0, ALIAS_START + 1, 4096) == 0xcc01);
    assert(map(0, ALIAS_START + ALIAS_SIZE, 4096) == 0xdc01);
    assert(used(7) == image);
}

static pthread_barrier_t start;
static _Atomic unsigned finished;
static uint64_t resize_result, map_result;
static void *grow_heap(void *unused) {
    (void)unused; pthread_barrier_wait(&start);
    resize_result = resize(0x400000); atomic_fetch_add(&finished, 1); return NULL;
}
static void *grow_alias(void *unused) {
    (void)unused; pthread_barrier_wait(&start);
    map_result = map(0, ALIAS_START, APP_POOL - runtime_image_bytes() - 0x200000);
    atomic_fetch_add(&finished, 1); return NULL;
}
static void *observe(void *unused) {
    (void)unused; pthread_barrier_wait(&start);
    do { assert(used(7) <= APP_POOL && used(22) <= APP_POOL); query_heap(); }
    while (atomic_load(&finished) != 2);
    return NULL;
}
static void concurrent_growth(void) {
    for (unsigned i = 0; i < 32; i++) {
        reset(); assert(!resize(0x200000)); atomic_store(&finished, 0);
        assert(!pthread_barrier_init(&start, NULL, 4));
        pthread_t heap, alias, reader;
        assert(!pthread_create(&heap, NULL, grow_heap, NULL));
        assert(!pthread_create(&alias, NULL, grow_alias, NULL));
        assert(!pthread_create(&reader, NULL, observe, NULL));
        pthread_barrier_wait(&start);
        assert(!pthread_join(heap, NULL) && !pthread_join(alias, NULL) && !pthread_join(reader, NULL));
        assert(!pthread_barrier_destroy(&start));
        assert((resize_result == 0) != (map_result == 0));
        assert(used(7) <= APP_POOL);
    }
}

int main(void) {
    g_nmodules = 1; g_modules[0].size = 32ULL << 20;
    runtime_memory_init();
    boundaries(); borrowed_tail(); overlaps(); concurrent_growth();
    puts("Guest pool: actual memory SVCs, ABI errors, borrowed tail, exact capacity, overlap and 32 concurrent races PASS");
    return 0;
}
