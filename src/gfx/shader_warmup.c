/* SPDX-License-Identifier: MIT */
/* See shader_warmup.h. The pass runs on the shader thread; every reader is the presentation thread, so each value
   is read or written on its own and no pair of them is read as a whole. state carries the release/acquire edge of a
   pass: DONE and CANCELLED are stored after the last step, so anyone who sees a finished pass also sees its count. */
#include "shader_warmup.h"

#include <stdatomic.h>

static _Atomic int g_state;
static _Atomic unsigned long long g_total, g_done;
static _Atomic int g_cancel;

void nd_shader_warm_begin(unsigned long long total) {
    atomic_store_explicit(&g_done, 0, memory_order_relaxed);
    atomic_store_explicit(&g_cancel, 0, memory_order_relaxed);
    atomic_store_explicit(&g_total, total, memory_order_relaxed);
    atomic_store(&g_state, total ? ND_SHADER_WARM_COMPILING : ND_SHADER_WARM_SCANNING);
}

void nd_shader_warm_count(unsigned long long total) {
    if (atomic_load_explicit(&g_total, memory_order_relaxed)) return;   // the pass already knew
    atomic_store_explicit(&g_total, total, memory_order_relaxed);
    atomic_store(&g_state, total ? ND_SHADER_WARM_COMPILING : ND_SHADER_WARM_DONE);
}

void nd_shader_warm_step(void) {
    atomic_fetch_add_explicit(&g_done, 1, memory_order_relaxed);
}

unsigned long long nd_shader_warm_done(void) {
    return atomic_load_explicit(&g_done, memory_order_relaxed);
}

int nd_shader_warm_share(void) {
    unsigned long long total = atomic_load_explicit(&g_total, memory_order_relaxed);
    if (!total) return -1;   // still scanning: any percentage shown here would be invented
    unsigned long long done = atomic_load_explicit(&g_done, memory_order_relaxed);
    if (done >= total) return 1000;
    return (int)(done * 1000ull / total);
}

int nd_shader_warm_state(void) {
    return atomic_load(&g_state);
}

void nd_shader_warm_cancel(void) {
    atomic_store_explicit(&g_cancel, 1, memory_order_relaxed);
}

int nd_shader_warm_cancel_requested(void) {
    return atomic_load_explicit(&g_cancel, memory_order_relaxed);
}

void nd_shader_warm_finish(void) {
    atomic_store(&g_state, nd_shader_warm_cancel_requested() ? ND_SHADER_WARM_CANCELLED : ND_SHADER_WARM_DONE);
}
