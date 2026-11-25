// 区域搬运与整级往返逐字节对拍：证明「只搬游戏 WriteTexels 写过的那一块」不改变任何字节。
// 真机上王国之泪每帧用 WriteTexels 重写地图（5120x5120 BC1）的一小块，旧路径整级来回排布 26 MiB、每次 20-36 ms，
// 左上角小地图每帧闪一下（2026-11-25 真机日志 105 次）。上传改成只搬矩形的前提就是这条等价关系，
// 对拍失败 = 小地图会显示陈旧或撕裂的像素，而不是白省了时间。
// The rectangle move compared byte for byte with the whole-level round trip: that equivalence is what lets an upload take
// only the bytes the game wrote. A failure means stale or torn texels on screen, not a lost speedup.
#include "../src/gfx/tex/nvn_deswizzle.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned g_rng = 20261125u;
static unsigned next_rand(void) { g_rng = g_rng * 1103515245u + 12345u; return g_rng >> 8; }

/* 一个描述符、一个块矩形：A 整级往返 与 B 只搬矩形，必须产出同一份存储
   one descriptor, one block rectangle: A (whole level out, patch, whole level back) and B (only the rectangle moves)
   have to leave the storage identical */
static void check(const nvn_texdesc *d, const char *what, unsigned level, unsigned layer,
                  uint32_t sx, uint32_t sy, uint32_t bx, uint32_t by, unsigned z0, unsigned zslices) {
    uint32_t row_full, rows_full, slices, bpb; uint64_t base; unsigned th, td;
    if (nvn_deswizzle_geom(d, level, layer, &row_full, &rows_full, &slices, &base, &th, &td, &bpb)) return;
    if (sx >= row_full / bpb || sy >= rows_full || bx > row_full / bpb - sx || by > rows_full - sy || !bx || !by) return;
    if (!zslices) zslices = slices;                       /* whole level by default | 默认整级 */
    if (z0 >= slices || zslices > slices - z0) return;
    nvn_texlayout L; nvn_tex_layout(d, &L);
    size_t total = (size_t)L.size;
    uint32_t x0 = sx * bpb, pitch = bx * bpb;
    size_t reg = (size_t)pitch * by * zslices;   /* 矩形缓冲只装这份区域 | the region buffer holds just these slices */
    uint8_t *seed = malloc(total), *a = malloc(total), *b = malloc(total);
    uint8_t *lin_all = malloc((size_t)row_full * rows_full * slices), *lin_reg = malloc(reg), *patch = malloc(reg);
    if (!seed || !a || !b || !lin_all || !lin_reg || !patch) { puts("OOM"); exit(2); }
    for (size_t i = 0; i < total; i++) seed[i] = (uint8_t)next_rand();
    memcpy(a, seed, total); memcpy(b, seed, total);
    for (size_t i = 0; i < reg; i++) patch[i] = (uint8_t)(next_rand() & 0xff);

    if (nvn_deswizzle(d, level, layer, a, lin_all, row_full) ||
        nvn_deswizzle_region(d, level, layer, z0, zslices, b, lin_reg, pitch, x0, sy, pitch, by)) {
        printf("FAIL %s level %u: move rejected\n", what, level); exit(1);
    }
    /* B 读出的矩形必须与整级解出的同一段一致，否则后面的比较没有意义
       B's read has to match the same bytes A read, or comparing the results would prove nothing */
    for (uint32_t z = z0; z < z0 + zslices; z++)
        for (uint32_t r = 0; r < by; r++)
            if (memcmp(lin_all + ((size_t)z * rows_full + sy + r) * row_full + x0,
                       lin_reg + ((size_t)(z - z0) * by + r) * pitch, pitch)) {
                printf("FAIL %s level %u slice %u row %u: the rectangle read differs\n", what, level, z, r); exit(1);
            }
    /* 同一份新内容写进两边：整级的那份改到对应位置，矩形那份整块替换
       one new content into both: A's rows patched in place, B's whole buffer replaced */
    for (uint32_t z = z0; z < z0 + zslices; z++)
        for (uint32_t r = 0; r < by; r++) {
            uint8_t *row = patch + ((size_t)(z - z0) * by + r) * pitch;
            for (uint32_t i = 0; i < pitch; i++) row[i] = (uint8_t)(row[i] ^ 0x5a);
            memcpy(lin_all + ((size_t)z * rows_full + sy + r) * row_full + x0, row, pitch);
            memcpy(lin_reg + ((size_t)(z - z0) * by + r) * pitch, row, pitch);
        }
    if (nvn_swizzle(d, level, layer, lin_all, row_full, a) ||
        nvn_swizzle_region(d, level, layer, z0, zslices, lin_reg, pitch, b, x0, sy, pitch, by)) {
        printf("FAIL %s level %u: move back rejected\n", what, level); exit(1);
    }
    size_t first = 0, diff = 0;
    for (size_t i = 0; i < total; i++) if (a[i] != b[i]) { if (!diff) first = i; diff++; }
    if (diff) { printf("FAIL %s level %u layer %u rect %u,%u %ux%u blocks slices %u+%u: %zu bytes differ, first at +%zu\n",
                       what, level, layer, sx, sy, bx, by, z0, zslices, diff, first); exit(1); }
    free(seed); free(a); free(b); free(lin_all); free(lin_reg); free(patch);
}

int main(void) {
    static const struct { nvn_texdesc d; const char *what; } cases[] = {
        { .d = { .target=1, .format=0x49, .samples=0, .width=5120, .height=5120, .depth=1, .levels=7, .stride=0 }, "map BC1 5120x5120 (from the Deck log)" },
        { .d = { .target=1, .format=0x4D, .samples=0, .width=1024, .height=1024, .depth=1, .levels=11, .stride=0 }, "BC7 1024x1024" },
        { .d = { .target=1, .format=0x0A, .samples=0, .width=320, .height=200, .depth=1, .levels=3, .stride=0 }, "RGBA8 320x200" },
        { .d = { .target=1, .format=0x01, .samples=0, .width=108, .height=108, .depth=1, .levels=1, .stride=0 }, "R8 108x108 (the prompt masks)" },
        { .d = { .target=4, .format=0x0A, .samples=0, .width=64, .height=64, .depth=12, .levels=1, .stride=0 }, "2D array RGBA8 64x64x12" },
        { .d = { .target=1, .format=0x41, .samples=0, .width=33, .height=17, .depth=1, .levels=1, .stride=0 }, "BC1 33x17 (partial GOB column)" },
        { .d = { .target=2, .format=0x0A, .samples=0, .width=64, .height=64, .depth=12, .levels=1, .stride=0 }, "3D RGBA8 64x64x12 (WriteTexels with a slice offset)" },
    };
    int checks = 0;
    for (unsigned c = 0; c < sizeof cases / sizeof *cases; c++) {
        const nvn_texdesc *d = &cases[c].d;
        unsigned levels = d->levels ? d->levels : 1, layers = d->depth ? d->depth : 1;
        for (unsigned level = 0; level < levels; level++)
            for (unsigned layer = 0; layer < layers; layer++) {
                /* 对齐的、不对齐的、整级、贴右下的、单个块 | GOB-aligned, unaligned, whole, bottom-right, one block */
                /* 对齐的、不对齐的、整级、贴右下的、单个块；3D 另加切片偏移 | GOB-aligned, unaligned, whole,
                   bottom-right, one block; 3D also with a non-zero slice offset (the game writes a slice range, not just 0) */
                static const struct { uint32_t sx, sy, bx, by; unsigned z0, zslices; } regs[] = {
                    {0, 0, 1, 1, 0, 0}, {8, 1, 16, 2, 0, 0}, {0, 0, 1u << 20, 1u << 20, 0, 0}, {3, 5, 7, 9, 0, 0},
                    {0, 0, 1u << 20, 1u << 20, 3, 4}, {4, 2, 3, 2, 1, 2},
                };
                for (unsigned p = 0; p < sizeof regs / sizeof *regs; p++) {
                    check(d, cases[c].what, level, layer, regs[p].sx, regs[p].sy, regs[p].bx, regs[p].by,
                          regs[p].z0, regs[p].zslices);
                    checks++;
                }
            }
        printf("OK %s\n", cases[c].what);
    }
    printf("%d rectangle moves match the whole-level round trip\n", checks);
    return 0;
}
