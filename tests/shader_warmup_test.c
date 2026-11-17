/* SPDX-License-Identifier: MIT */
/* The warm-up's report (src/gfx/shader_warmup.c): an uncounted pass says so instead of reading as finished, the
   share reaches its end when every counted name is stepped over, and a stop ends the pass as cancelled. The
   production file is compiled here, so a change to it has to pass. */
#include <assert.h>
#include <stdio.h>

#include "../src/gfx/shader_warmup.c"  // production translation unit; it depends on nothing else

int main(void) {
    // Before a shader has ever been asked for, the bar has nothing to show.
    assert(nd_shader_warm_state() == ND_SHADER_WARM_IDLE);
    assert(nd_shader_warm_share() == -1);

    // A pass that already knows how many shaders it has: the share is meaningful from the first step.
    nd_shader_warm_begin(4);
    assert(nd_shader_warm_state() == ND_SHADER_WARM_COMPILING);
    assert(nd_shader_warm_share() == 0);
    nd_shader_warm_step();
    assert(nd_shader_warm_share() == 250);
    nd_shader_warm_step();
    assert(nd_shader_warm_share() == 500);
    // A count that arrives later (the pass already knew its total) must not disturb it.
    nd_shader_warm_count(40);
    assert(nd_shader_warm_share() == 500);
    nd_shader_warm_step();
    nd_shader_warm_step();
    assert(nd_shader_warm_share() == 1000);
    assert(nd_shader_warm_done() == 4);
    nd_shader_warm_finish();
    assert(nd_shader_warm_state() == ND_SHADER_WARM_DONE);

    // The folder form: the number of shaders is only known after the list, so until then the share is unknown.
    nd_shader_warm_begin(0);
    assert(nd_shader_warm_state() == ND_SHADER_WARM_SCANNING);
    assert(nd_shader_warm_share() == -1);
    nd_shader_warm_count(2);
    assert(nd_shader_warm_state() == ND_SHADER_WARM_COMPILING);
    assert(nd_shader_warm_share() == 0);
    nd_shader_warm_step();
    assert(nd_shader_warm_share() == 500);

    // A stop in the middle ends as cancelled, and the caches keep what was done (the count is untouched).
    nd_shader_warm_cancel();
    assert(nd_shader_warm_cancel_requested());
    nd_shader_warm_finish();
    assert(nd_shader_warm_state() == ND_SHADER_WARM_CANCELLED);
    assert(nd_shader_warm_done() == 1);

    // The next boot starts over: the stop request and the counters are cleared by the pass that follows.
    nd_shader_warm_begin(1);
    assert(nd_shader_warm_state() == ND_SHADER_WARM_COMPILING);
    assert(!nd_shader_warm_cancel_requested());
    assert(nd_shader_warm_share() == 0);
    nd_shader_warm_finish();
    assert(nd_shader_warm_state() == ND_SHADER_WARM_DONE);

    // A counted pass of nothing (an empty folder) is complete, not stuck at zero.
    nd_shader_warm_begin(0);
    nd_shader_warm_count(0);
    assert(nd_shader_warm_state() == ND_SHADER_WARM_DONE);
    assert(nd_shader_warm_share() == -1);   // nothing to divide by: still no meaningful share

    puts("shader warm-up report ok");
    return 0;
}
