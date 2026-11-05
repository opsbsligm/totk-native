// LZ4 block decompression (NSO segments: loader.c, nvn/shader_archive.c).
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

static inline bool lz4_extend(const uint8_t **src, const uint8_t *end, size_t *len) {
    uint8_t byte;
    do {
        if (*src == end) return false;
        byte = *(*src)++;
        if (*len > SIZE_MAX - byte) return false;
        *len += byte;
    } while (byte == 255);
    return true;
}

// Bytes written to dst, or SIZE_MAX when the block is malformed or truncated.
static inline size_t lz4_decompress(const uint8_t *src, size_t srclen, uint8_t *dst, size_t dstlen) {
    const uint8_t *s = src, *se = src + srclen;
    uint8_t *d = dst, *de = dst + dstlen;
    while (s < se) {
        uint8_t tok = *s++;
        size_t lit = tok >> 4;
        if (lit == 15 && !lz4_extend(&s, se, &lit)) return SIZE_MAX;
        if (lit > (size_t)(de - d) || lit > (size_t)(se - s)) return SIZE_MAX;
        memcpy(d, s, lit);
        d += lit; s += lit;
        if (s == se) break;
        if (se - s < 2) return SIZE_MAX;
        size_t off = s[0] | (s[1] << 8);
        s += 2;
        size_t ml = tok & 15;
        if (ml == 15 && !lz4_extend(&s, se, &ml)) return SIZE_MAX;
        size_t remaining = (size_t)(de - d);
        if (!off || off > (size_t)(d - dst) || remaining < 4 || ml > remaining - 4) return SIZE_MAX;
        ml += 4;
        uint8_t *m = d - off;
        while (ml--) *d++ = *m++;
    }
    return d - dst;
}
