/* SPDX-License-Identifier: GPL-3.0-or-later
 * Exact snapshots for CPU-visible atlases when the platform has no write watch.
 * One translation unit owns the budget. Its normal upload lock serializes use
 * of the returned snapshot; release is allowed only when the image is retired.
 * Missing snapshots always mean unknown/changed, including allocation failure.
 */
#ifndef NATIVEDECK_CPU_TEXTURE_SHADOW_H
#define NATIVEDECK_CPU_TEXTURE_SHADOW_H
#include <pthread.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

#define ND_SHADOW_MAX (16u * 1024u * 1024u)
#define ND_SHADOW_BUDGET (64u * 1024u * 1024u)
typedef struct { unsigned char *data; size_t size; } nd_cpu_shadow;
static pthread_mutex_t nd_shadow_mu = PTHREAD_MUTEX_INITIALIZER;
static size_t nd_shadow_bytes;

static int nd_shadow_changed(const nd_cpu_shadow *s, const void *src, size_t size) {
    if (!src || !size || size > ND_SHADOW_MAX) return 1;
    pthread_mutex_lock(&nd_shadow_mu);
    int changed = !s->data || s->size != size || memcmp(s->data, src, size) != 0;
    pthread_mutex_unlock(&nd_shadow_mu);
    return changed;
}
static const unsigned char *nd_shadow_capture(nd_cpu_shadow *s, const void *src, size_t size) {
    if (!src || !size || size > ND_SHADOW_MAX) return NULL;
    pthread_mutex_lock(&nd_shadow_mu);
    if (s->size != size) {
        nd_shadow_bytes -= s->size;
        free(s->data); s->data = NULL; s->size = 0;
    }
    if (!s->data && nd_shadow_bytes <= ND_SHADOW_BUDGET - size) {
        s->data = malloc(size);
        if (s->data) { s->size = size; nd_shadow_bytes += size; }
    }
    if (s->data) memcpy(s->data, src, size);
    const unsigned char *result = s->data;
    pthread_mutex_unlock(&nd_shadow_mu);
    return result;
}
static void nd_shadow_release(nd_cpu_shadow *s) {
    pthread_mutex_lock(&nd_shadow_mu);
    nd_shadow_bytes -= s->size;
    free(s->data); s->data = NULL; s->size = 0;
    pthread_mutex_unlock(&nd_shadow_mu);
}
#endif
