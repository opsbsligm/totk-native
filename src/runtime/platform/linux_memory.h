/* SPDX-License-Identifier: MIT */
/* Imported/copy-backed pools keep guest pages alive through GPU retirement.
 * The registry lock also covers copy-back + discard, so a new import cannot
 * acquire a range between the overlap check and MADV_DONTNEED. */
#pragma once
#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>

typedef struct linux_memory_ref {
    uint64_t lo, hi;
    struct linux_memory_ref *next;
} linux_memory_ref;
static linux_memory_ref *g_linux_memory_refs;
static pthread_mutex_t g_linux_memory_mu = PTHREAD_MUTEX_INITIALIZER;
static uint64_t g_linux_guest_lo, g_linux_guest_hi;

void *plat_memory_hold(uint64_t address, uint64_t size) {
    if (!size || address > UINT64_MAX - size) { errno = EINVAL; return NULL; }
    linux_memory_ref *ref = malloc(sizeof *ref);
    if (!ref) return NULL;
    *ref = (linux_memory_ref){address, address + size, NULL};
    pthread_mutex_lock(&g_linux_memory_mu);
    ref->next = g_linux_memory_refs; g_linux_memory_refs = ref;
    pthread_mutex_unlock(&g_linux_memory_mu);
    return ref;
}

void plat_memory_release(void *token) {
    if (!token) return;
    pthread_mutex_lock(&g_linux_memory_mu);
    linux_memory_ref **at = &g_linux_memory_refs;
    while (*at && *at != token) at = &(*at)->next;
    if (!*at) abort();  /* invalid/double release is a runtime ownership bug */
    linux_memory_ref *ref = *at; *at = ref->next;
    pthread_mutex_unlock(&g_linux_memory_mu);
    free(ref);
}

static int linux_guest_range(uint64_t address, uint64_t size) {
    return size && !((address | size) & 4095) && address >= g_linux_guest_lo &&
        address < g_linux_guest_hi && size <= g_linux_guest_hi - address;
}

/* Caller holds g_linux_memory_mu. */
static int linux_memory_busy(uint64_t address, uint64_t size) {
    for (linux_memory_ref *r = g_linux_memory_refs; r; r = r->next)
        if (r->lo < address + size && address < r->hi) return 1;
    return 0;
}

int plat_decommit_guest(uint64_t address, uint64_t size, uint64_t restore_to) {
    if (!linux_guest_range(address, size) ||
        (restore_to && (!linux_guest_range(restore_to, size) ||
                       (restore_to < address + size && address < restore_to + size)))) {
        errno = EINVAL; return -1;
    }
    pthread_mutex_lock(&g_linux_memory_mu);
    if (linux_memory_busy(address, size) || (restore_to && linux_memory_busy(restore_to, size))) {
        pthread_mutex_unlock(&g_linux_memory_mu); return 1;
    }
    if (restore_to) memcpy((void *)(uintptr_t)restore_to, (void *)(uintptr_t)address, size);
    int result = madvise((void *)(uintptr_t)address, size, MADV_DONTNEED);
    int error = errno;
    /* DONTNEED removes the userfaultfd WP marker as well as the page. */
    if (!result) linux_watch_rearm(address, size);
    pthread_mutex_unlock(&g_linux_memory_mu);
    errno = error;
    return result;
}
