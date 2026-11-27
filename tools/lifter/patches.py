"""Per-instruction replacements applied by gen.py: guest address -> function(gen, addr) returning C code.

Every patch checks the original instruction word first, so lifting another game version (or a different build)
fails loudly instead of changing the wrong code. Runtime switches live in src/gfx/nvn/hle_nvn.c.
"""


def expect(gen, addr, word, what):
    got = gen.word(addr)
    if got != word:
        raise SystemExit(f'patch {what} at {addr:#x}: expected {word:#010x}, found {got:#010x} (not TOTK 1.4.3?)')


def drs_off(gen, addr):
    """Dynamic resolution off (1.4.3). main+0x584300 is the scene resolution controller: each frame it fits the
    recent frame times and returns {scale (float), state} to the renderer (main+0x581968), which turns the scale into
    the scene size (+0xccc). Its first test is the controller's enable bit (+0x110 bit 0); with the bit clear it
    takes its own disabled path (main+0x584c3c): scale 1.0, history untouched. The patch takes that path unless
    TOTK_DRS=1. Why: the game flips the scene targets between 1600x896 and 1432x808 over the same memory and our
    per-size images then hand stale content to the other size (terrain gone, clouds over the scene);
    image quality is better at a fixed size and upscaling will come from FSR."""
    expect(gen, addr, 0x360042e8, 'drs_off')   # tbz w8, #0, 0x800584c3c
    return ('{ extern int totk_drs_enabled(void); '
            'if (!totk_drs_enabled() || ((c->x[8] >> 0) & 1) == 0) { goto L_800584c3c; } }')


def drs_scale(gen, addr):
    """Fixed internal scene scale (TOTK_SCENE_SCALE, 1.4.3). The disabled path of the controller above returns scale
    1.0: main+0x584c44 is the `mov w23, #0x3f800000` that holds it, and the caller (main+0x581a0c) takes the low half
    of the return as a float and turns it into the scene size (+0xccc). Replacing that one word with a runtime value
    makes the scene render at a fixed fraction and the output is upscaled (FSR), which is the lever the GPU-side cost
    needs: measured on Deck, 20.6 ms a frame in render passes against 22.7 ms of recording, both above 16.7 ms.
    A fraction rather than the game's own controller: ours does not move the targets between sizes, which is what made
    the game's dynamic resolution unusable here (see drs_off). TOTK_SCENE_SCALE unset or 1.0 keeps the instruction's
    own value (no behaviour change); 0.8 renders a quarter fewer pixels."""
    expect(gen, addr, 0x52a7f017, 'drs_scale')   # mov w23, #0x3f800000 (scale 1.0f)
    return ('{ extern unsigned totk_scene_scale_bits(void); unsigned s = totk_scene_scale_bits(); '
            'c->x[23] = s ? s : 0x3f800000u; }')


PATCHES = {
    0x8005843e0: drs_off,
    0x800584c44: drs_scale,
}
