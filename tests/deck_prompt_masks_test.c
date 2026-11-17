/* SPDX-License-Identifier: MIT */
/* Authored Deck prompt masks: labels, plate containment, legibility, and buffer handling. */
#include "deck_prompt_masks.h"
#include <assert.h>
#include <stdio.h>

enum { W = 108 };
static unsigned char a[W * W + 2], b[W * W];

static void body_and_ink(unsigned code, int menu, float X, float Y, float *body, float *ink) {
    const NdGlyphShape s = nd_deck_shape(code);
    NdGlyphStroke st[ND_GLYPH_STROKES_MAX], st2[ND_GLYPH_STROKES_MAX];
    int n1 = s.plate ? nd_glyph_strokes('L', st, ND_GLYPH_STROKES_MAX)
                     : nd_glyph_strokes(nd_deck_face_label(code, menu), st, ND_GLYPH_STROKES_MAX);
    int n2 = s.plate ? nd_glyph_strokes(code == 4 ? '1' : '2', st2, ND_GLYPH_STROKES_MAX) : 0;
    assert(n1 > 0 && (!s.plate || n2 > 0));
    *body = s.plate ? nd_glyph_rrect(X, Y, s.body_hw, s.body_hh, s.body_rad) : hypotf(X, Y) - s.body_r;
    *ink = s.plate
        ? fminf(nd_glyph_ink(st, n1, X, Y, -s.dx, 0, s.em, s.stem),
                nd_glyph_ink(st2, n2, X, Y, s.dx, 0, s.em, s.stem))
        : nd_glyph_ink(st, n1, X, Y, 0, 0, s.em, s.stem);
}

/* Smallest gap between a knocked-out pixel and its own body edge, in mask space. Measured on the
 * geometry rather than the raster, so the antialias ramp cannot hide a letter that touches the rim. */
static float clearance(unsigned code, int menu) {
    float worst = 10.f;
    for (unsigned y = 0; y < W; y++) for (unsigned x = 0; x < W; x++) {
        float body, ink;
        body_and_ink(code, menu, (x + .5f) / W - .5f, (y + .5f) / W - .5f, &body, &ink);
        if (body < 0 && ink < 0) worst = fminf(worst, -body);
    }
    return worst;
}

/* Legibility at the size that matters: the game scales a prompt to about 40 pixels on a 1280x800
 * Deck screen, where an earlier redraw lost its letters entirely. Box-filter the mask the way that
 * scaling does, then require the cut-out to stay clearly darker than the plate around it. Bucket
 * bounds follow the source (x * W / size), so every source pixel lands in exactly one bucket; a
 * fixed integer step would drop the trailing 26 per cent at 40 px and score a clipped disc. */
static float downscaled_contrast(unsigned code, int menu, int size) {
    const NdGlyphShape s = nd_deck_shape(code);
    static unsigned char hi[48 * 48];
    assert(nd_deck_glyph_mask(code, menu, b, sizeof b, W));
    for (int y = 0; y < size; y++) for (int x = 0; x < size; x++) {
        unsigned acc = 0, n = 0;
        for (int sy = y * W / size; sy < (y + 1) * W / size; sy++)
            for (int sx = x * W / size; sx < (x + 1) * W / size; sx++, n++) acc += b[(size_t)sy * W + sx];
        assert(n);   // W >= 2 * size, so every bucket holds at least one source pixel
        hi[(size_t)y * size + x] = (unsigned char)(acc / n);
    }
    float plate = 0, letter = 0; int np = 0, nl = 0;
    for (int y = 0; y < size; y++) for (int x = 0; x < size; x++) {
        float X = (x + .5f) / size - .5f, Y = (y + .5f) / size - .5f;
        if (s.plate ? nd_glyph_rrect(X, Y, s.body_hw, s.body_hh, s.body_rad) >= 0
                    : hypotf(X, Y) - s.body_r >= 0) continue;      // outside the plate
        float v = hi[(size_t)y * size + x] / 255.f;
        if (v > .8f) { plate += v; np++; }
        else if (v < .2f) { letter += v; nl++; }                    // still knocked out after scaling
    }
    if (!np || !nl) return -1.f;                                    // plate or letter vanished
    return plate / np - letter / nl;
}

/* A push that fails has to stay failed without touching memory. The glyph builders below only
 * check the running count at the end of a chain, so a push that indexed a failed count would write
 * one element before the array — out[-1] when the chain already carries -1. The 32 guard bytes end
 * on a 4-byte boundary, which is all the stroke array asks for, so guard[16..31] is exactly where
 * st[-1] would land and a stray write in that region cannot miss the check. */
static void assert_clean(const unsigned char *guard, size_t n) {
    for (size_t i = 0; i < n; i++) assert(guard[i] == 0x5a);
}

static void push_stays_failed_without_writing(void) {
    struct { unsigned char guard[32]; NdGlyphStroke st[2]; } box;
    memset(&box, 0x5a, sizeof box);
    int n = nd_glyph_push(box.st, 2, 0, 0.f, 0.f, 1.f, 1.f); assert(n == 1);
    n = nd_glyph_push(box.st, 2, n, 0.f, 0.f, 1.f, 1.f); assert(n == 2);
    n = nd_glyph_push(box.st, 2, n, 0.f, 0.f, 1.f, 1.f); assert(n == -1);   // first overflow
    n = nd_glyph_push(box.st, 2, n, 0.f, 0.f, 1.f, 1.f); assert(n == -1);   // chained on -1
    n = nd_glyph_push(box.st, 2, n, 0.f, 0.f, 1.f, 1.f); assert(n == -1);
    assert_clean(box.guard, sizeof box.guard);
    /* The chain shape used by nd_glyph_strokes: a call that passes -1 straight through. */
    assert(nd_glyph_push(box.st, 2, -1, 0.f, 0.f, 1.f, 1.f) == -1);
    assert_clean(box.guard, sizeof box.guard);
}

/* Every character the prompts draw, and the buffer the callers actually allocate: too small fails
 * outright, and the real size fits with room for a future glyph. */
static void glyph_buffers_fail_closed_and_have_headroom(void) {
    static const char letters[] = "ABXYL12";
    for (const char *p = letters; *p; p++) {
        NdGlyphStroke full[ND_GLYPH_STROKES_MAX];
        const int n = nd_glyph_strokes(*p, full, ND_GLYPH_STROKES_MAX);
        assert(n > 0 && n <= ND_GLYPH_STROKES_MAX);   // the callers' array fits with headroom
        /* Every buffer smaller than the glyph's own count has to fail, and the chain past the
         * failed push must not write at index -1 or past the end either. */
        for (int max = 1; max < n; max++) {
            struct { unsigned char guard[32]; NdGlyphStroke st[ND_GLYPH_STROKES_MAX]; } box;
            memset(&box, 0x5a, sizeof box);
            assert(nd_glyph_strokes(*p, box.st, max) == -1);
            assert_clean(box.guard, sizeof box.guard);
        }
    }
}

int main(void) {
    const char *world = "BAYX", *menu = "ABYX";
    for (unsigned c = 0; c < 4; c++) { assert(nd_deck_face_label(c, 0) == world[c]);
                                      assert(nd_deck_face_label(c, 1) == menu[c]); }

    push_stays_failed_without_writing();
    glyph_buffers_fail_closed_and_have_headroom();

    /* Buffer handling: a rejected call leaves the caller's bytes alone, an accepted one fills exactly. */
    memset(a, 0x6d, sizeof a);
    assert(!nd_deck_glyph_mask(6, 0, a + 1, sizeof a - 2, W)); assert(a[1] == 0x6d);
    assert(!nd_deck_glyph_mask(0, 0, a + 1, 5, W));
    assert(!nd_deck_glyph_mask(0, 0, 0, 0, W));
    assert(!nd_deck_glyph_mask(0, 0, a + 1, sizeof a - 2, 257));
    assert(nd_deck_glyph_mask(0, 0, a + 1, sizeof a - 2, W));
    assert(a[0] == 0x6d && a[sizeof a - 1] == 0x6d);

    /* Context swaps the letter only: same disc, different cut-out. */
    assert(nd_deck_glyph_mask(1, 1, b, sizeof b, W)); assert(!memcmp(a + 1, b, sizeof b));
    assert(nd_deck_glyph_mask(0, 1, b, sizeof b, W)); assert(memcmp(a + 1, b, sizeof b));

    for (unsigned code = 0; code < 6; code++) for (int m = 0; m < 2; m++) {
        assert(nd_deck_glyph_mask(code, m, b, sizeof b, W));
        int solid = 0, edge = 0;
        for (unsigned i = 0; i < sizeof b; i++) { solid += b[i] == 255; edge += b[i] > 0 && b[i] < 255; }
        assert(solid > 1000 && edge > 100);                 // a plate with an antialiased edge
        assert(!b[0] && !b[W - 1] && !b[sizeof b - 1]);     // corners stay outside the body
        float clear = clearance(code, m);
        if (clear < nd_deck_shape(code).clear) {
            printf("code %u menu %d: clearance %.4f below %.4f\n", code, m, clear,
                   nd_deck_shape(code).clear);
            return 1;
        }
        /* 40 px world prompts and 48 px menu prompts both have to keep a readable letter. */
        for (int size = 40; size <= 48; size += 8) {
            float contrast = downscaled_contrast(code, m, size);
            if (contrast < .6f) {
                printf("code %u menu %d at %d px: contrast %.3f\n", code, m, size, contrast);
                return 1;
            }
        }
    }

    /* The shoulder codes carry two characters side by side: a landscape plate, not a square. */
    for (unsigned code = 4; code < 6; code++) {
        assert(nd_deck_glyph_mask(code, 0, b, sizeof b, W));
        int minx = W, maxx = -1, miny = W, maxy = -1;
        for (unsigned y = 0; y < W; y++) for (unsigned x = 0; x < W; x++) if (b[(size_t)y * W + x]) {
            if ((int)x < minx) { minx = (int)x; }
            if ((int)x > maxx) { maxx = (int)x; }
            if ((int)y < miny) { miny = (int)y; }
            if ((int)y > maxy) { maxy = (int)y; }
        }
        assert(maxx - minx > (maxy - miny) * 3 / 2);
    }
    return 0;
}
