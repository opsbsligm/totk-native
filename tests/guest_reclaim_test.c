/* SPDX-License-Identifier: MIT */
/* Actual guest SVCs and Linux discard; synthetic memory, no game input. */
#define _GNU_SOURCE 1
#include <assert.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdatomic.h>
#include <sys/mman.h>
#include "../src/host/svc.c"
#include "../src/runtime/platform/linux_watch.h"
#include "../src/runtime/platform/linux_memory.h"

Module g_modules[MAX_MODULES];
int g_nmodules;
static unsigned char exception_storage[0x1000];
void *hle_alloc(uint64_t size) { assert(size == sizeof exception_storage); return exception_storage; }
int svc_thread(int num, uint64_t *r) { (void)num; (void)r; return 0; }
int runtime_ipc_svc(unsigned num, uint64_t *r) { (void)num; (void)r; return 0; }
uint64_t runtime_now_ns(void) { return 1; }
_Noreturn void runtime_fail(const char *message) { fprintf(stderr, "%s\n", message); abort(); }
void plat_commit(uint64_t address, uint64_t size) { assert(address && size); }
int plat_protect(uint64_t address, uint64_t size, int protection) {
    (void)address; (void)size; (void)protection; abort();
}

static uint64_t resize(uint64_t size) {
    uint64_t r[32] = {0}; r[1] = size;
    uint64_t result = runtime_svc(0x01, r, 0); assert(result == r[0]); return result;
}
static uint64_t map(int unmap, uint64_t address, uint64_t size) {
    uint64_t r[32] = {address, size};
    uint64_t result = runtime_svc(unmap ? 0x2d : 0x2c, r, 0); assert(result == r[0]); return result;
}
static uint64_t used(void) {
    uint64_t r[32] = {0, 7}; assert(!runtime_svc(0x29, r, 0) && !r[0]); return r[1];
}
static unsigned char *at(uint64_t address) { return (void *)(uintptr_t)address; }
static int resident(uint64_t address) {
    unsigned char vec = 0; assert(!mincore(at(address), 4096, &vec)); return vec & 1;
}
static void reserve(uint64_t address, uint64_t size) {
    assert(mmap(at(address), size, PROT_READ | PROT_WRITE,
        MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0) == at(address));
}

static void heap(void) {
    assert(!resize(0x400000));
    memset(at(HEAP_START), 0x35, 4096); memset(at(HEAP_START + 0x200000), 0x77, 8192);
    uint64_t before = used();
    void *a = plat_memory_hold(HEAP_START + 0x200000, 4096);
    void *b = plat_memory_hold(HEAP_START + 0x200000 + 2048, 4096);
    assert(a && b && resize(0x200000) == 0xd401 && used() == before);
    assert(at(HEAP_START + 0x200000)[0] == 0x77 && resident(HEAP_START + 0x200000));
    plat_memory_release(a); assert(resize(0x200000) == 0xd401 && used() == before);
    plat_memory_release(b); assert(!resize(0x200000) && used() == before - 0x200000);
    assert(!resident(HEAP_START + 0x200000) && !resident(HEAP_START + 0x201000));
    assert(!resize(0x400000));
    for (unsigned i = 0; i < 8192; i++) assert(!at(HEAP_START + 0x200000)[i]);
    assert(at(HEAP_START)[0] == 0x35);
}

static void aliases(void) {
    assert(!map(0, ALIAS_START, 12288)); memset(at(ALIAS_START), 0xa5, 12288);
    assert(!map(1, ALIAS_START + 4096, 4096) && !resident(ALIAS_START + 4096));
    assert(!map(0, ALIAS_START, 12288));
    assert(at(ALIAS_START)[0] == 0xa5 && !at(ALIAS_START + 4096)[0] && at(ALIAS_START + 8192)[0] == 0xa5);
    uint64_t before = used(); void *ref = plat_memory_hold(ALIAS_START + 8192, 4096); assert(ref);
    assert(map(1, ALIAS_START, 12288) == 0xd401 && used() == before);
    assert(alias_pages[0] && alias_pages[1] && alias_pages[2] && at(ALIAS_START)[0] == 0xa5);
    plat_memory_release(ref); assert(!map(1, ALIAS_START, 12288));
    assert(used() == before - 12288 && !resident(ALIAS_START) && !resident(ALIAS_START + 8192));
    assert(!map(1, ALIAS_START, 12288));
}

static void stacks(void) {
    assert(!stack_move(0, STACK_START, HEAP_START, 4096));
    assert(at(STACK_START)[0] == 0x35); memset(at(STACK_START), 0x67, 4096);
    void *ref = plat_memory_hold(STACK_START, 4096); assert(ref);
    assert(stack_move(1, STACK_START, HEAP_START, 4096) == 0xd401 && nstack_maps == 1);
    assert(at(HEAP_START)[0] == 0x35 && at(STACK_START)[0] == 0x67);
    plat_memory_release(ref); ref = plat_memory_hold(HEAP_START, 4096); assert(ref);
    assert(stack_move(1, STACK_START, HEAP_START, 4096) == 0xd401 && nstack_maps == 1);
    assert(at(HEAP_START)[0] == 0x35); plat_memory_release(ref);
    assert(!stack_move(1, STACK_START, HEAP_START, 4096) && !nstack_maps && !resident(STACK_START));
    for (unsigned i = 0; i < 4096; i++) assert(at(HEAP_START)[i] == 0x67);
}

static pthread_barrier_t barrier;
static void *contend(void *unused) {
    (void)unused; void *ref = plat_memory_hold(HEAP_START, 4096); assert(ref);
    pthread_barrier_wait(&barrier); pthread_barrier_wait(&barrier);
    assert(at(HEAP_START)[0] == 0x31); plat_memory_release(ref); return NULL;
}
static void races(void) {
    for (unsigned i = 0; i < 64; i++) {
        at(HEAP_START)[0] = 0x31; assert(!pthread_barrier_init(&barrier, NULL, 2));
        pthread_t t; assert(!pthread_create(&t, NULL, contend, NULL)); pthread_barrier_wait(&barrier);
        assert(plat_decommit_guest(HEAP_START, 4096, 0) == 1 && at(HEAP_START)[0] == 0x31);
        pthread_barrier_wait(&barrier); assert(!pthread_join(t, NULL)); assert(!pthread_barrier_destroy(&barrier));
        assert(!plat_decommit_guest(HEAP_START, 4096, 0) && !resident(HEAP_START));
        assert(!at(HEAP_START)[0]);
    }
}

int main(int argc, char **argv) {
    int legacy = argc == 2 && !strcmp(argv[1], "default");
    if (legacy) unsetenv("TOTK_GUEST_RECLAIM"); else setenv("TOTK_GUEST_RECLAIM", "1", 1);
    g_linux_guest_lo = LOW_START; g_linux_guest_hi = ALIAS_START + ALIAS_SIZE;
    reserve(HEAP_START, 0x400000); reserve(ALIAS_START, 16384); reserve(STACK_START, 16384);
    runtime_memory_init();
    if (legacy) {
        assert(!resize(0x400000)); at(HEAP_START + 0x200000)[0] = 0x77;
        void *ref = plat_memory_hold(HEAP_START + 0x200000, 4096); assert(ref);
        assert(!resize(0x200000) && resident(HEAP_START + 0x200000) && at(HEAP_START + 0x200000)[0] == 0x77);
        plat_memory_release(ref);
    } else {
        assert(plat_decommit_guest(HEAP_START + 1, 4096, 0) == -1);
        assert(plat_decommit_guest(UINT64_MAX - 4095, 8192, 0) == -1);
        assert(plat_decommit_guest(HEAP_START, 4096, HEAP_START) == -1);
        assert(!plat_memory_hold(UINT64_MAX - 1, 4096));
        heap(); aliases(); stacks(); races();
        /* Owned descriptors with an unsupported ioctl explicitly disable watch. */
        g_linux_uffd = open("/dev/null", O_RDONLY | O_CLOEXEC); assert(g_linux_uffd >= 0);
        g_linux_pagemap = open("/dev/null", O_RDONLY | O_CLOEXEC); assert(g_linux_pagemap >= 0);
        int a = g_linux_uffd, b = g_linux_pagemap;
        g_linux_watch_lo = g_linux_guest_lo; g_linux_watch_hi = g_linux_guest_hi;
        assert(!plat_decommit_guest(HEAP_START, 4096, 0));
        assert(g_linux_uffd == -1 && g_linux_pagemap == -1);
        assert(fcntl(a, F_GETFD) == -1 && errno == EBADF && fcntl(b, F_GETFD) == -1 && errno == EBADF);
    }
    assert(!g_linux_memory_refs && !nstack_maps);
    assert(!munmap(at(HEAP_START), 0x400000) && !munmap(at(ALIAS_START), 16384) && !munmap(at(STACK_START), 16384));
    puts(legacy ? "Guest reclaim: accepted default unchanged PASS" :
        "Guest reclaim: real SVCs, residency/zero refill, overlap, stack copy-back, 64 races and watch failure cleanup PASS");
    return 0;
}
