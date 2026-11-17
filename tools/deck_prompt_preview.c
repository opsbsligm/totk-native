/* SPDX-License-Identifier: MIT */
/* Render every authored Deck prompt mask to a PGM so a human can look at the artwork. */
#include "deck_prompt_masks.h"
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* File name follows the letter the mask actually carries, so the sheet reads without a key. */
static const char *glyph_name(unsigned code, int menu) {
    static char lower[2];
    if (code >= 4) return code == 4 ? "l1" : "l2";
    lower[0] = (char)tolower(nd_deck_face_label(code, menu)); lower[1] = 0;
    return lower;
}

static int save(const char *dir, unsigned code, int menu, const unsigned char *px, unsigned w) {
    char path[256];
    snprintf(path, sizeof path, "%s/%s_%s.pgm", dir, menu ? "menu" : "world", glyph_name(code, menu));
    FILE *f = fopen(path, "wb");
    if (!f) { perror(path); return 0; }
    fprintf(f, "P5\n%u %u\n255\n", w, w);
    size_t written = fwrite(px, 1, (size_t)w * w, f);
    int ok = fclose(f) == 0 && written == (size_t)w * w;
    if (!ok) fprintf(stderr, "incomplete: %s\n", path);
    return ok;
}

int main(int argc, char **argv) {
    const char *dir = argc > 1 ? argv[1] : ".";
    unsigned w = argc > 2 ? (unsigned)strtoul(argv[2], 0, 10) : 108;
    if (w < 8 || w > 256) { fprintf(stderr, "size out of range: %u\n", w); return 2; }
    unsigned char mask[256 * 256];
    for (unsigned code = 0; code < 6; code++) for (int menu = 0; menu < 2; menu++)
        if (!nd_deck_glyph_mask(code, menu, mask, sizeof mask, w) || !save(dir, code, menu, mask, w))
            return 1;
    printf("wrote 12 PGM masks to %s at %u px\n", dir, w);
    return 0;
}
