#include "native_frame_metrics.h"
#include <assert.h>
#include <math.h>

static void near(float actual, double expected) {
    assert(fabs((double)actual - expected) < 0.001);
}

static void constant_rate(unsigned rate) {
    NdFrameMetrics s = {};
    assert(!nd_frame_metrics_present(&s, 0));
    for (unsigned second = 0; second < 2; ++second) {
        for (unsigned i = 1; i <= rate; ++i) {
            uint64_t ns = (uint64_t)second * 1000000000 + (uint64_t)i * 1000000000 / rate;
            assert(nd_frame_metrics_present(&s, ns) == (i == rate));
        }
        near(s.fps, rate);
        near(s.average_ms, 1000.0 / rate);
        near(s.maximum_ms, 1000.0 / rate);
        assert(s.intervals == 0 && s.total_ms == 0 && s.peak_ms == 0);
    }
}

int main() {
    constant_rate(30);
    constant_rate(60);
    constant_rate(144);
    NdFrameMetrics s = {};
    assert(!nd_frame_metrics_present(&s, 100));
    assert(!nd_frame_metrics_present(&s, 100)); // no fabricated zero-time frame
    assert(s.intervals == 0 && s.fps == 0 && s.average_ms == 0);
    for (unsigned i = 1; i <= 59; ++i)
        assert(!nd_frame_metrics_present(&s, 100 + (uint64_t)i * 16000000));
    assert(nd_frame_metrics_present(&s, 1000000100));
    near(s.fps, 60);
    near(s.average_ms, 1000.0 / 60);
    near(s.maximum_ms, 56); // the slow frame remains visible
    assert(nd_frame_metrics_present(&s, 3500000100));
    near(s.fps, 0.4);
    near(s.average_ms, 2500);
    near(s.maximum_ms, 2500);
    assert(!nd_frame_metrics_present(&s, 10)); // restart a regressed clock safely
    assert(s.intervals == 0 && s.fps == 0 && s.average_ms == 0 && s.maximum_ms == 0);
    assert(nd_frame_metrics_present(&s, 1000000010));
    near(s.fps, 1);
    near(s.average_ms, 1000);
    near(s.maximum_ms, 1000);
}
