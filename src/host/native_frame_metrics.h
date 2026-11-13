/* SPDX-License-Identifier: MIT */
#ifndef ND_NATIVE_FRAME_METRICS_H
#define ND_NATIVE_FRAME_METRICS_H
#include <stdint.h>

/* Count complete presentation intervals, including long frames. The first
 * timestamp establishes the window; it is not a measured frame interval. */
typedef struct {
    uint64_t last_ns, window_ns, intervals;
    double total_ms, peak_ms;
    float fps, average_ms, maximum_ms;
    int initialized;
} NdFrameMetrics;

static inline int nd_frame_metrics_present(NdFrameMetrics *s, uint64_t now_ns) {
    if (!s->initialized || now_ns < s->last_ns) {
        *s = NdFrameMetrics{};
        s->initialized = 1;
        s->last_ns = s->window_ns = now_ns;
        return 0;
    }
    if (now_ns == s->last_ns) return 0;
    double ms = (double)(now_ns - s->last_ns) * 1e-6;
    s->last_ns = now_ns;
    ++s->intervals;
    s->total_ms += ms;
    if (ms > s->peak_ms) s->peak_ms = ms;
    uint64_t elapsed_ns = now_ns - s->window_ns;
    if (elapsed_ns < UINT64_C(1000000000)) return 0;
    s->fps = (float)((double)s->intervals * 1e9 / (double)elapsed_ns);
    s->average_ms = (float)(s->total_ms / (double)s->intervals);
    s->maximum_ms = (float)s->peak_ms;
    s->window_ns = now_ns;
    s->intervals = 0;
    s->total_ms = s->peak_ms = 0;
    return 1;
}
#endif
