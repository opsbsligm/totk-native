/* SPDX-License-Identifier: MIT */
/* Authored Deck mask geometry. Host-side replacement only; no game pixels. */
#pragma once
#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

// The game asks for one 108x108 greyscale mask per on-screen control prompt: the mask is the plate
// silhouette with the character knocked out of it, and the layout supplies the colour. The codes
// below keep that topology, so a replacement swaps in per texture without touching any layout.
//
// The first authored version mixed a hard-edged skeleton with a per-pixel coverage term, subtracted
// the stem width twice, and drew the round letters as a handful of straight chords, so B read as a
// faceted block and 2 as a bent wire at the ~40 pixels a prompt actually occupies on 1280x800.
// Everything here is one signed distance shared by the body edge and the cut-out, and the round
// letters are elliptical arcs sampled finely enough that the faceting stays under a source pixel.
//
// Layout contracts, pinned by tests/deck_prompt_masks_test.c:
//   * face codes: rounded square with the letter cut out, the shape of the physical Deck faces, so
//     an on-screen prompt and the button under a thumb read as the same control; shoulder codes: a
//     wider rounded plate with both characters inside it. Both stay legible where the game scales
//     a prompt down to about 40 pixels;
//   * no cut-out pixel comes closer than NdGlyphShape.clear to its own body edge, so a redraw that
//     lets a letter touch or cross the plate fails the test instead of shipping a clipped prompt;
//   * menu and world differ only in the letter (A confirm, B cancel), never in the body, so one
//     redrawn plate cannot change what a prompt looks like between contexts.

typedef struct { float ax, ay, bx, by; } NdGlyphStroke;
enum { ND_GLYPH_STROKES_MAX = 34 };

static inline char nd_deck_face_label(unsigned code, int menu) {
    static const char world[] = "BAYX", menus[] = "ABYX";
    return code < 4 ? (menu ? menus : world)[code] : 0;
}

// Distance from (x,y) to the segment a->b.
static inline float nd_glyph_segment(float x, float y, float ax, float ay, float bx, float by) {
    float dx = bx - ax, dy = by - ay;
    float t = dx || dy ? ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy) : 0.f;
    t = fmaxf(0, fminf(1, t));
    return hypotf(x - ax - t * dx, y - ay - t * dy);
}

static inline int nd_glyph_push(NdGlyphStroke *out, int max, int n,
                                float ax, float ay, float bx, float by) {
    // A failed push stays failed: the chains in nd_glyph_strokes only check at the end, so an
    // already-negative n must never reach the write or it lands at out[-1].
    if (n < 0 || n >= max) return -1;
    out[n].ax = ax; out[n].ay = ay; out[n].bx = bx; out[n].by = by;
    return n + 1;
}

// Elliptical arc as a deterministic polyline: y grows downwards, so -pi/2 is the top of the glyph.
// Twelve steps over a half turn keeps the chord error below 0.002 em, under a source pixel at 108.
static inline int nd_glyph_arc(NdGlyphStroke *out, int max, int n,
                               float cx, float cy, float rx, float ry, float a0, float a1) {
    const int steps = 12;
    float px = cx + rx * cosf(a0), py = cy + ry * sinf(a0);
    for (int i = 1; i <= steps; i++) {
        float a = a0 + (a1 - a0) * (float)i / (float)steps;
        float qx = cx + rx * cosf(a), qy = cy + ry * sinf(a);
        n = nd_glyph_push(out, max, n, px, py, qx, qy);
        if (n < 0) return -1;
        px = qx; py = qy;
    }
    return n;
}

// Centred stroke skeleton of one character in a 1x1 em box (cap height +-0.215, y downwards). Only
// the characters the prompts use: A B X Y for the faces, L 1 2 for the shoulder plates. Returns the
// stroke count, or -1 when the buffer is too small; an unknown letter yields 0 and draws nothing.
//
// The letterforms are drawn for the size that matters: at 40 pixels a prompt is about 14 pixels of
// cap height, so the counters (the holes in A and B) have to survive the box filter. Each letter
// therefore keeps its openings clear of the stem that bounds them, and no stroke crosses another
// except where the letter itself calls for it (X, and the A crossbar meeting its legs).
static inline int nd_glyph_strokes(char letter, NdGlyphStroke *out, int max) {
    const float top = -.215f, bot = .215f, mid = 0.f, hy = .1075f;   // cap edges and half of it
    int n = 0;
    switch (letter) {
    case 'A':
        /* Legs splayed wider than the crossbar and a flat apex keep the counter triangular at
         * 40 px; a narrower A closes to a dot once the game scales the mask down. */
        n = nd_glyph_push(out, max, n, -.295f, bot, -.020f, top);
        n = nd_glyph_push(out, max, n,  .295f, bot,  .020f, top);
        n = nd_glyph_push(out, max, n, -.035f, top,  .035f, top);   // flat apex: two strokes alone leave a notch
        if (n < 0) return -1;
        return nd_glyph_push(out, max, n, -.150f, .075f, .150f, .075f);
    case 'B':
        /* Stem pulled left and both bowls pulled right: the three feeds plus the arcs leave two
         * open counters. The earlier bowls met the stem head-on, so downscaled they filled in and
         * B read as a filled block with two scratches. */
        n = nd_glyph_push(out, max, n, -.215f, top, -.215f, bot);              // stem
        n = nd_glyph_push(out, max, n, -.215f, top, -.020f, top);              // bowl feeds
        if (n < 0) return -1;
        n = nd_glyph_push(out, max, n, -.215f, mid, -.020f, mid);
        n = nd_glyph_push(out, max, n, -.215f, bot, -.020f, bot);
        if (n < 0) return -1;
        n = nd_glyph_arc(out, max, n, -.020f, -hy, .215f, hy, -1.5707963f, 1.5707963f);   // upper bowl
        if (n < 0) return -1;
        return nd_glyph_arc(out, max, n, -.020f, hy, .230f, hy, -1.5707963f, 1.5707963f); // lower bowl
    case 'X':
        /* Arms pulled in a touch so the diagonals clear the plate rim once the face turns square. */
        n = nd_glyph_push(out, max, n, -.270f, top, .270f, bot);
        if (n < 0) return -1;
        return nd_glyph_push(out, max, n, .270f, top, -.270f, bot);
    case 'Y':
        /* Fork meeting above the middle leaves a full-length stem; a shallow V that stops at the
         * centre reads as a cross at prompt size. */
        n = nd_glyph_push(out, max, n, -.280f, top, -.015f, -.030f);
        n = nd_glyph_push(out, max, n,  .280f, top,  .015f, -.030f);
        if (n < 0) return -1;
        return nd_glyph_push(out, max, n, 0.f, -.030f, 0.f, bot);
    case 'L':
        n = nd_glyph_push(out, max, n, -.170f, top, -.170f, bot);
        if (n < 0) return -1;
        return nd_glyph_push(out, max, n, -.170f, bot, .175f, bot);
    case '1':
        n = nd_glyph_push(out, max, n, -.150f, -.060f, 0.f, top);
        n = nd_glyph_push(out, max, n, 0.f, top, 0.f, bot);
        if (n < 0) return -1;
        return nd_glyph_push(out, max, n, -.190f, bot, .190f, bot);
    case '2':
        /* Hook opened and base widened: the earlier tighter hook merged with the diagonal and the
         * digit lost its 2-ness on a shoulder plate, which is already the smaller of the two. */
        n = nd_glyph_arc(out, max, n, 0.f, -.095f, .185f, .120f, 3.1415927f, 6.2831853f);   // hook
        if (n < 0) return -1;
        n = nd_glyph_push(out, max, n, .185f, -.095f, -.190f, bot);                          // diagonal
        if (n < 0) return -1;
        return nd_glyph_push(out, max, n, -.190f, bot, .190f, bot);                          // base
    }
    return 0;
}

// Distance to a character's ink: negative inside the stroke, whose half width is `stem` in em space.
// The skeleton is resolved once by the caller, so this only walks segments. A stroke point lands at
// em * point + centre, so scaling and offset keep the letter's own proportions at any placement.
static inline float nd_glyph_ink(const NdGlyphStroke *st, int count,
                                 float x, float y, float cx, float cy, float em, float stem) {
    float best = 10.f;
    for (int i = 0; i < count; i++) {
        best = fminf(best, nd_glyph_segment(x, y,
            em * st[i].ax + cx, em * st[i].ay + cy,
            em * st[i].bx + cx, em * st[i].by + cy));
    }
    return best - em * stem;
}

static inline float nd_glyph_rrect(float x, float y, float hw, float hh, float r) {
    float qx = fabsf(x) - (hw - r), qy = fabsf(y) - (hh - r);
    return fmaxf(fmaxf(qx, qy), 0.f) + hypotf(fmaxf(qx, 0.f), fmaxf(qy, 0.f)) - r;
}

// One code's geometry in the mask's own -0.5..0.5 space. `clear` is the smallest gap the test
// requires between the cut-out and the body edge, so a redraw has to state its margins.
typedef struct { int plate; float body_r, body_hw, body_hh, body_rad, em, stem, dx, clear; } NdGlyphShape;

// One silhouette for every code: the rounded rectangle, which is the physical Deck face as well as
// the shoulder plate, so no code needs its own body primitive and no plate can drift out of square.
static inline float nd_deck_body(const NdGlyphShape *s, float x, float y) {
    return nd_glyph_rrect(x, y, s->body_hw, s->body_hh, s->body_rad);
}

static inline NdGlyphShape nd_deck_shape(unsigned code) {
    NdGlyphShape s;
    // The face letters are knocked out of a rounded square the layout colours: same corner radius
    // family as the shoulder plate, so the six prompts read as one family and match the buttons.
    // `plate` now only says whether a code carries one character or a pair; the body is shared.
    if (code < 4) { s.plate = 0; s.body_r = 0; s.body_hw = s.body_hh = .40f; s.body_rad = .16f;
                    s.em = .72f; s.stem = .062f; s.dx = 0; }
    else          { s.plate = 1; s.body_r = 0; s.body_hw = .40f; s.body_hh = .23f; s.body_rad = .10f;
                    s.em = .46f; s.stem = .070f; s.dx = .180f; }
    s.clear = .030f;   // under a third of the ramp's own width, so the edge stays antialiased
    return s;
}

static inline int nd_deck_glyph_mask(unsigned code, int menu, uint8_t *out, size_t bytes, unsigned w) {
    if (!out || !w || w > 256 || bytes < (size_t)w * w || code > 5) return 0;
    const NdGlyphShape s = nd_deck_shape(code);
    const float ramp = 1.7f;   // antialias width in source pixels; under a pixel after the game's scaling
    NdGlyphStroke st[ND_GLYPH_STROKES_MAX], st2[ND_GLYPH_STROKES_MAX];
    int n1 = 0, n2 = 0;
    if (s.plate) {
        n1 = nd_glyph_strokes('L', st, ND_GLYPH_STROKES_MAX);
        n2 = nd_glyph_strokes(code == 4 ? '1' : '2', st2, ND_GLYPH_STROKES_MAX);
    } else {
        n1 = nd_glyph_strokes(nd_deck_face_label(code, menu), st, ND_GLYPH_STROKES_MAX);
    }
    if (n1 <= 0 || (s.plate && n2 <= 0)) return 0;
    for (unsigned y = 0; y < w; y++) for (unsigned x = 0; x < w; x++) {
        float X = (x + .5f) / w - .5f, Y = (y + .5f) / w - .5f;
        float body = nd_deck_body(&s, X, Y);
        float ink = s.plate
            ? fminf(nd_glyph_ink(st, n1, X, Y, -s.dx, 0, s.em, s.stem),
                    nd_glyph_ink(st2, n2, X, Y, s.dx, 0, s.em, s.stem))
            : nd_glyph_ink(st, n1, X, Y, 0, 0, s.em, s.stem);
        float coverage = fmaxf(0, fminf(1, .5f - body * w / ramp));
        float knockout = fmaxf(0, fminf(1, .5f - ink * w / ramp));
        out[(size_t)y * w + x] = (uint8_t)lroundf(255 * coverage * (1 - knockout));
    }
    return 1;
}
