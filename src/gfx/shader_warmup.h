/* SPDX-License-Identifier: MIT */
/* The state of the background shader warm-up (vkb_shader.c's ahead thread), so the touch control bar can report
   what it is doing and let the player stop it. Ahead of the first frame that needs one, every translated shader is
   compiled once per driver into the on-disk binary cache, so a place never walked before does not stutter. Stopping
   keeps the binaries already made: the next boot carries on from there.

   The counters live here rather than in the thread so the share is a single number the interface can show. A pass
   whose total is not known yet (the folder form has no count of its own until it is scanned) reports -1 rather than
   claiming to be finished, which is what an under-counted total used to read as. */
#pragma once
#ifdef __cplusplus
extern "C" {
#endif

enum {
    ND_SHADER_WARM_IDLE = 0,   // no shader has been asked for yet, so the pass has not started
    ND_SHADER_WARM_SCANNING,   // counting the shaders to compile; the share is not known yet
    ND_SHADER_WARM_COMPILING,
    ND_SHADER_WARM_DONE,       // every shader the pass counted is compiled or already in the cache
    ND_SHADER_WARM_CANCELLED   // stopped from the control bar, with the caches left as they are
};

// Start the pass over `total` shaders (0: not counted yet, so the state is scanning).
void nd_shader_warm_begin(unsigned long long total);
// The scan's answer, for a pass that started with an unknown total. A pass that already knew its total ignores it.
void nd_shader_warm_count(unsigned long long total);
// One shader of the pass is handled, whether it was compiled, already cached, or skipped.
void nd_shader_warm_step(void);
unsigned long long nd_shader_warm_done(void);
// The share handled, 0..1000; -1 while the total is still unknown.
int nd_shader_warm_share(void);
int nd_shader_warm_state(void);   // ND_SHADER_WARM_*
// Ask the pass to stop after the shader it is on; repeated calls are harmless.
void nd_shader_warm_cancel(void);
int nd_shader_warm_cancel_requested(void);
// The pass ended: cancelled when it was asked to stop, otherwise complete.
void nd_shader_warm_finish(void);

#ifdef __cplusplus
}
#endif
