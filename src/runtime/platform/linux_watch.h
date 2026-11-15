// Linux asynchronous write watch, adapted from UltraTears d657eff841e4.
// GPL-3.0-or-later. See NOTICE.md for the pinned source and retained limits.
#pragma once
#include <errno.h>
#include <fcntl.h>
#include <linux/fs.h>
#include <linux/userfaultfd.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>

// Linux 6.7 ABI, also built against the Steam Runtime's older UAPI headers.
#ifndef PAGEMAP_SCAN
struct page_region { __u64 start, end, categories; };
struct pm_scan_arg {
    __u64 size, flags, start, end, walk_end, vec, vec_len, max_pages;
    __u64 category_inverted, category_mask, category_anyof_mask, return_mask;
};
#define PAGEMAP_SCAN _IOWR('f', 16, struct pm_scan_arg)
#define PAGE_IS_WRITTEN (1 << 1)
#define PAGE_IS_PRESENT (1 << 3)
#define PAGE_IS_SWAPPED (1 << 4)
#define PAGE_IS_PFNZERO (1 << 5)
#define PM_SCAN_WP_MATCHING (1 << 0)
#define PM_SCAN_CHECK_WPASYNC (1 << 1)
#endif
#ifndef UFFD_FEATURE_WP_ASYNC
#define UFFD_FEATURE_WP_ASYNC (1 << 15)
#endif
#ifndef UFFD_FEATURE_WP_UNPOPULATED
#define UFFD_FEATURE_WP_UNPOPULATED (1 << 13)
#endif
#ifndef UFFD_USER_MODE_ONLY
#define UFFD_USER_MODE_ONLY 1
#endif

static int g_linux_uffd = -1, g_linux_pagemap = -1;
static uint64_t g_linux_watch_lo, g_linux_watch_hi;
static pthread_mutex_t g_linux_watch_mu = PTHREAD_MUTEX_INITIALIZER;

static void linux_watch_close_unlocked(void) {
    if (g_linux_uffd >= 0) close(g_linux_uffd);
    if (g_linux_pagemap >= 0) close(g_linux_pagemap);
    g_linux_uffd = g_linux_pagemap = -1;
    g_linux_watch_lo = g_linux_watch_hi = 0;
}

static void linux_watch_close(void) {
    pthread_mutex_lock(&g_linux_watch_mu);
    linux_watch_close_unlocked();
    pthread_mutex_unlock(&g_linux_watch_mu);
}

static int linux_watch_register(uint64_t lo, uint64_t hi) {
    if (g_linux_uffd < 0 || lo >= hi || lo < g_linux_watch_lo || hi > g_linux_watch_hi) return 0;
    // A first write must identify its 4 KiB page, not an entire huge page.
    if (madvise((void *)(uintptr_t)lo, hi - lo, MADV_NOHUGEPAGE)) return 0;
    struct uffdio_register reg = {.range = {.start = lo, .len = hi - lo}, .mode = UFFDIO_REGISTER_MODE_WP};
    return ioctl(g_linux_uffd, UFFDIO_REGISTER, &reg) == 0;
}

static int linux_watch_rearm_unlocked(uint64_t address, uint64_t size) {
    if (g_linux_uffd < 0 || !size || (address | size) & 4095 ||
        address < g_linux_watch_lo || address >= g_linux_watch_hi || size > g_linux_watch_hi - address) return 0;
    struct uffdio_writeprotect wp = {.range = {.start = address, .len = size}, .mode = UFFDIO_WRITEPROTECT_MODE_WP};
    return ioctl(g_linux_uffd, UFFDIO_WRITEPROTECT, &wp) == 0;
}

/* Serialize capability loss/descriptor close against scans on other threads. */
static int linux_watch_rearm(uint64_t address, uint64_t size) {
    pthread_mutex_lock(&g_linux_watch_mu);
    int result = linux_watch_rearm_unlocked(address, size);
    if (!result && g_linux_uffd >= 0) linux_watch_close_unlocked();
    pthread_mutex_unlock(&g_linux_watch_mu);
    return result;
}

static void linux_watch_remapped(uint64_t lo, uint64_t hi) {
    pthread_mutex_lock(&g_linux_watch_mu);
    if (g_linux_uffd >= 0 && !linux_watch_register(lo, hi)) linux_watch_close_unlocked();
    pthread_mutex_unlock(&g_linux_watch_mu);
}

static int linux_watch_requested(void) {
    const char *copy = getenv("TOTK_POOL_COPY"), *imp = getenv("TOTK_POOL_IMPORT");
    const char *watch = getenv("TOTK_WRITE_WATCH");
    return copy && !strcmp(copy, "1") && !(imp && !strcmp(imp, "1")) && !(watch && !strcmp(watch, "0"));
}

static void linux_watch_init_unlocked(uint64_t lo, uint64_t hi) {
    linux_watch_close_unlocked();
    if (!linux_watch_requested() || lo >= hi || (lo | hi) & 4095) return;
    // Only asynchronous user-mode faults: no privileges or sysctl changes.
    int uffd = (int)syscall(SYS_userfaultfd, O_CLOEXEC | O_NONBLOCK | UFFD_USER_MODE_ONLY);
    if (uffd < 0) return;
    struct uffdio_api api = {.api = UFFD_API, .features = UFFD_FEATURE_WP_ASYNC | UFFD_FEATURE_WP_UNPOPULATED};
    const uint64_t required = UFFD_FEATURE_WP_ASYNC | UFFD_FEATURE_WP_UNPOPULATED;
    if (ioctl(uffd, UFFDIO_API, &api) || (api.features & required) != required) { close(uffd); return; }
    int pagemap = open("/proc/self/pagemap", O_RDONLY | O_CLOEXEC);
    if (pagemap < 0) { close(uffd); return; }
    g_linux_uffd = uffd;
    g_linux_pagemap = pagemap;
    g_linux_watch_lo = lo;
    g_linux_watch_hi = hi;
    if (!linux_watch_register(lo, hi)) linux_watch_close_unlocked();
}

static void linux_watch_init(uint64_t lo, uint64_t hi) {
    pthread_mutex_lock(&g_linux_watch_mu);
    linux_watch_init_unlocked(lo, hi);
    pthread_mutex_unlock(&g_linux_watch_mu);
}

static int linux_watch_pages_unlocked(uint64_t addr, uint64_t size, uint64_t *pages, int max, uint64_t *page) {
    if (g_linux_pagemap < 0 || !pages || !page || !size || max <= 0 ||
        (addr | size) & 4095 || addr < g_linux_watch_lo || addr > g_linux_watch_hi || size > g_linux_watch_hi - addr) return -1;
    *page = 4096;
    uint64_t at = addr, end = addr + size;
    int n = 0;
    while (at < end && n < max) {
        struct page_region regions[64];
        struct pm_scan_arg scan = {.size = sizeof scan, .flags = PM_SCAN_WP_MATCHING | PM_SCAN_CHECK_WPASYNC,
            .start = at, .end = end, .vec = (uint64_t)(uintptr_t)regions, .vec_len = 64, .max_pages = (uint64_t)(max - n),
            .category_inverted = PAGE_IS_PFNZERO, .category_mask = PAGE_IS_WRITTEN | PAGE_IS_PFNZERO,
            .category_anyof_mask = PAGE_IS_PRESENT | PAGE_IS_SWAPPED, .return_mask = PAGE_IS_WRITTEN};
        long count = ioctl(g_linux_pagemap, PAGEMAP_SCAN, &scan);
        if (count < 0 || count > 64 || scan.walk_end <= at || scan.walk_end > end) return -1;
        uint64_t previous = at;
        for (long i = 0; i < count; i++) {
            struct page_region *r = &regions[i];
            if ((r->start | r->end) & 4095 || r->start < previous || r->start >= r->end || r->end > scan.walk_end ||
                (r->end - r->start) / 4096 > (uint64_t)(max - n)) return -1;
            for (uint64_t p = r->start; p < r->end; p += 4096) pages[n++] = p;
            previous = r->end;
        }
        at = scan.walk_end;
    }
    return n;
}

static int linux_watch_pages(uint64_t addr, uint64_t size, uint64_t *pages, int max, uint64_t *page) {
    pthread_mutex_lock(&g_linux_watch_mu);
    int count = linux_watch_pages_unlocked(addr, size, pages, max, page);
    pthread_mutex_unlock(&g_linux_watch_mu);
    return count;
}
