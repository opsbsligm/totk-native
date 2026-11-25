// Tegra X1 块线性排布（公开描述见 deko3d / Ryujinx BlockLinearLayout）：
//   GOB = 64 字节 × 8 行 = 512 字节；GOB 内 (x 字节, y 行) 的偏移 =
//     (x%64/32)·256 + (y%8/2)·64 + (x%32/16)·32 + (y%2)·16 + x%16
//   块 = 1 个 GOB 宽 × 2^tileH 个 GOB 高 × 2^tileD 个 GOB 深，块内先排 y 再排 z；块按 x → y → z 行优先铺满本级。
// 级 / 层起点与本级实际块高块深取自 nvn_tex.c，这里只做级内寻址与搬运。
// Tegra X1 block-linear layout (public descriptions: deko3d / Ryujinx BlockLinearLayout):
//   GOB = 64 bytes × 8 rows = 512 bytes; offset of (x byte, y row) within a GOB =
//     (x%64/32)·256 + (y%8/2)·64 + (x%32/16)·32 + (y%2)·16 + x%16
//   block = 1 GOB wide × 2^tileH GOBs high × 2^tileD GOBs deep, ordered y first then z within a block; blocks fill the level in x → y → z row-major order.
// Level / layer start offsets and the actual block height and block depth of this level come from nvn_tex.c; here we only do intra-level addressing and copying.
#include "nvn_deswizzle.h"
#include <string.h>

static uint32_t gob_off(uint32_t x, uint32_t y) {
    return (x % 64 / 32) * 256 + (y % 8 / 2) * 64 + (x % 32 / 16) * 32 + (y % 2) * 16 + x % 16;
}

uint64_t nvn_bl_offset(uint32_t x, uint32_t y, uint32_t z, uint32_t row_bytes, uint32_t rows, unsigned th, unsigned td) {
    uint32_t bh = 1u << th, bd = 1u << td;
    uint64_t gobs_x = (row_bytes + 63) / 64, blocks_y = (rows + 8 * bh - 1) / (8 * bh);
    uint64_t block = 512ull * bh * bd;                                  // 一个块的字节 | bytes in one block
    return (z / bd) * gobs_x * blocks_y * block                        // 第几层块（深度方向） | which block layer (along depth)
         + (y / (8 * bh)) * gobs_x * block                             // 第几行块 | which block row
         + (x / 64) * block                                            // 第几列块 | which block column
         + ((z % bd) * bh + (y % (8 * bh)) / 8) * 512ull               // 块内第几个 GOB | which GOB within the block
         + gob_off(x, y);
}

static uint32_t mip(uint32_t s, unsigned l) { s >>= l; return s ? s : 1; }

// 本级几何：块宽字节数、块行数、切片数，以及本级本层在存储里的起点；不支持的贴图返回 -1
// Geometry of this level: width-in-blocks byte count, block row count, slice count, and where this level and layer starts in storage; returns -1 for unsupported textures
int nvn_deswizzle_geom(const nvn_texdesc *d, unsigned level, unsigned layer,
                       uint32_t *row_bytes, uint32_t *rows, uint32_t *slices, uint64_t *base, unsigned *th, unsigned *td, uint32_t *bpb) {
    if (d->target == 5 || d->target == 6 || d->target == 10 || nvn_tex_is_linear(d) || d->samples > 1) return -1;   // MS / BUFFER / LINEAR
    int bw, bh; *bpb = (uint32_t)nvn_fmt_bpb(d->format, &bw, &bh);
    if (!*bpb || level >= (d->levels ? d->levels : 1)) return -1;
    nvn_texlayout L; nvn_tex_layout(d, &L);
    if (layer >= L.layers) return -1;
    int one_d = d->target == 0 || d->target == 3;
    uint32_t w = mip(d->width, level), h = one_d ? 1 : mip(d->height, level);
    *slices = d->target == 2 ? mip(d->depth ? d->depth : 1, level) : 1;
    *row_bytes = (w + bw - 1) / bw * *bpb; *rows = (h + bh - 1) / bh;
    *base = (uint64_t)layer * L.layer_size + nvn_tex_level_offset(d, level);
    nvn_tex_level_tiles(d, level, th, td);
    return 0;
}

static int move(const nvn_texdesc *d, unsigned level, unsigned layer, uint8_t *bl, uint8_t *lin, size_t pitch, int to_linear) {
    if (nvn_tex_is_linear(d)) {
        if (level || layer || d->samples > 1 || (d->target != 0 && d->target != 1 && d->target != 7)) return -1;
        int bw, bh, bpb = nvn_fmt_bpb(d->format, &bw, &bh);
        if (!bpb) return -1;
        size_t row = (size_t)((d->width + bw - 1) / bw) * bpb;
        uint32_t rows = d->target == 0 ? 1 : (d->height + bh - 1) / bh, stride = nvn_tex_linear_stride(d);
        if (pitch < row || stride < row) return -1;
        for (uint32_t y = 0; y < rows; y++) {
            if (to_linear) memcpy(lin + y * pitch, bl + (size_t)y * stride, row);
            else memcpy(bl + (size_t)y * stride, lin + y * pitch, row);
        }
        return 0;
    }
    uint32_t row_bytes, rows, slices, bpb; uint64_t base; unsigned th, td;
    if (nvn_deswizzle_geom(d, level, layer, &row_bytes, &rows, &slices, &base, &th, &td, &bpb)) return -1;
    if (pitch < row_bytes) return -1;
    bl += base;
    // [port] GOB by GOB: the address of each GOB is computed once, and its 8 rows x 4 16-byte sectors are copied at fixed
    // offsets (a 16-byte memcpy is inlined). Per 16 bytes, the full address with its divisions and a library memcpy call
    // took ~12% of the recording thread on the Great Sky Island (texture uploads, 2026-10-24).
    uint32_t bh = 1u << th, bd = 1u << td, gobs_x = (row_bytes + 63) / 64, blocks_y = (rows + 8 * bh - 1) / (8 * bh);
    uint64_t block = 512ull * bh * bd;
    for (uint32_t z = 0; z < slices; z++)
        for (uint32_t y0 = 0; y0 < rows; y0 += 8) {   // a row of GOBs
            uint64_t gy = (uint64_t)(z / bd) * gobs_x * blocks_y * block + (uint64_t)(y0 / (8 * bh)) * gobs_x * block
                        + ((uint64_t)(z % bd) * bh + (y0 % (8 * bh)) / 8) * 512ull;
            uint32_t ny = rows - y0 < 8 ? rows - y0 : 8;
            for (uint32_t gx = 0; gx < gobs_x; gx++) {
                uint8_t *gob = bl + gy + (uint64_t)gx * block;
                uint32_t x0 = gx * 64, nx = row_bytes - x0 < 64 ? row_bytes - x0 : 64;
                for (uint32_t r = 0; r < ny; r++) {
                    uint8_t *row = lin + ((size_t)z * rows + y0 + r) * pitch + x0;
                    uint8_t *g = gob + (r / 2) * 64 + (r % 2) * 16;
                    if (nx == 64) {   // the 4 sectors of the row: +0, +32, +256, +288
                        if (to_linear) { memcpy(row, g, 16); memcpy(row + 16, g + 32, 16); memcpy(row + 32, g + 256, 16); memcpy(row + 48, g + 288, 16); }
                        else { memcpy(g, row, 16); memcpy(g + 32, row + 16, 16); memcpy(g + 256, row + 32, 16); memcpy(g + 288, row + 48, 16); }
                    } else
                        for (uint32_t x = 0; x < nx; x += 16) {   // the last, partial GOB column (16 divides every block width)
                            uint32_t n = nx - x < 16 ? nx - x : 16;
                            uint8_t *p = g + (x / 32) * 256 + (x % 32 / 16) * 32;
                            if (to_linear) memcpy(row + x, p, n); else memcpy(p, row + x, n);
                        }
                }
            }
        }
    return 0;
}

int nvn_deswizzle(const nvn_texdesc *d, unsigned level, unsigned layer, const void *src, void *dst, size_t dst_pitch) {
    return move(d, level, layer, (uint8_t *)src, (uint8_t *)dst, dst_pitch, 1);
}
int nvn_swizzle(const nvn_texdesc *d, unsigned level, unsigned layer, const void *src, size_t src_pitch, void *dst) {
    return move(d, level, layer, (uint8_t *)dst, (uint8_t *)src, src_pitch, 0);
}

// 一个 GOB 的一行里搬线性 [xa,xb)：切段不跨 16 字节扇区边界（跨边界处退成两段），段内块线性地址按 gob_off 直算。

// Move linear bytes [xa,xb) of one GOB row, split so no segment crosses a 16-byte sector boundary; lin tracks xa.

static void gob_row_copy(uint8_t *gob, unsigned r, uint8_t *lin, uint32_t xa, uint32_t xb, int to_linear) {

    while (xa < xb) {

        uint32_t step = 16 - (xa & 15);

        if (step > xb - xa) step = xb - xa;

        uint8_t *g = gob + gob_off(xa, r);

        if (to_linear) memcpy(lin, g, step);

        else memcpy(g, lin, step);

        lin += step; xa += step;

    }

}

// 矩形搬运，两个方向共用：只走与矩形相交的 GOB。块线性是字节置换，反向只写矩形自己的字节，

// 与整级往返逐字节等价（单测把两个方向都对拍整级实现）。

// Rectangle move, both directions: only the GOBs the rectangle touches. Block-linear is a byte permutation, so the

// reverse direction writing only the rectangle's own bytes is byte-identical to a full-level round trip (the unit test

// compares both directions against the full-level implementation).

static int move_region(const nvn_texdesc *d, unsigned level, unsigned layer, uint8_t *bl, uint8_t *lin_all, size_t pitch,

                       uint32_t x0, uint32_t y0, uint32_t row_bytes, uint32_t rows, int to_linear) {

    uint32_t full_row, full_rows, slices, bpb; uint64_t base; unsigned th, td;

    if (!row_bytes || !rows) return 0;

    if (nvn_tex_is_linear(d)) {           // 行距存储：矩形就是行的一段 | pitch storage: the rectangle is a run of rows

        if (level || layer || d->samples > 1 || (d->target != 0 && d->target != 1 && d->target != 7)) return -1;

        int bw, bh; if (!nvn_fmt_bpb(d->format, &bw, &bh)) return -1;

        uint32_t stride = nvn_tex_linear_stride(d), row_full = (uint32_t)((d->width + bw - 1) / bw) * (uint32_t)nvn_fmt_bpb(d->format, &bw, &bh);

        uint32_t height_rows = d->target == 0 ? 1 : (d->height + bh - 1) / bh;

        if (pitch < row_bytes || x0 >= row_full || x0 + row_bytes > row_full || y0 >= height_rows || rows > height_rows - y0) return -1;

        for (uint32_t y = y0; y < y0 + rows; y++) {

            uint8_t *a = bl + (size_t)y * stride + x0, *b = lin_all + (size_t)(y - y0) * pitch;

            if (to_linear) memcpy(b, a, row_bytes); else memcpy(a, b, row_bytes);

        }

        return 0;

    }

    if (nvn_deswizzle_geom(d, level, layer, &full_row, &full_rows, &slices, &base, &th, &td, &bpb)) return -1;

    if (pitch < row_bytes || x0 >= full_row || y0 >= full_rows ||

        row_bytes > full_row - x0 || rows > full_rows - y0) return -1;

    bl += base;

    uint32_t bh = 1u << th, bd = 1u << td, gobs_x = (full_row + 63) / 64, blocks_y = (full_rows + 8 * bh - 1) / (8 * bh);

    uint64_t block = 512ull * bh * bd, xend = (uint64_t)x0 + row_bytes;

    for (uint32_t z = 0; z < slices; z++)

        for (uint32_t y = y0; y < y0 + rows; y++) {           /* 块行：起点不必对齐 GOB | block rows, no GOB alignment */

            for (uint32_t gx = x0 / 64; (uint64_t)gx * 64 < xend; gx++) {

                uint64_t xa = x0 > (uint64_t)gx * 64 ? x0 : (uint64_t)gx * 64;

                uint64_t xb = xend < (uint64_t)gx * 64 + 64 ? xend : (uint64_t)gx * 64 + 64;

                if (xb > full_row) xb = full_row;

                if (xa >= xb) continue;

                /* 该 (x,y) 所在 GOB 的地址，分解与 nvn_bl_offset 一致 */

                uint8_t *gob = bl + (uint64_t)(z / bd) * gobs_x * blocks_y * block + (uint64_t)(y / (8 * bh)) * gobs_x * block

                             + (uint64_t)gx * block + ((uint64_t)(z % bd) * bh + (y % (8 * bh)) / 8) * 512ull;

                gob_row_copy(gob, y % 8, lin_all + ((size_t)z * rows + (y - y0)) * pitch + (xa - x0),

                             (uint32_t)xa, (uint32_t)xb, to_linear);

            }

        }

    return 0;

}

int nvn_deswizzle_region(const nvn_texdesc *d, unsigned level, unsigned layer, const void *src_storage, void *dst_linear,

                         size_t dst_pitch, uint32_t x0, uint32_t y0, uint32_t row_bytes, uint32_t rows) {

    return move_region(d, level, layer, (uint8_t *)src_storage, (uint8_t *)dst_linear, dst_pitch, x0, y0, row_bytes, rows, 1);

}

int nvn_swizzle_region(const nvn_texdesc *d, unsigned level, unsigned layer, const void *src_linear, size_t src_pitch,

                       void *dst_storage, uint32_t x0, uint32_t y0, uint32_t row_bytes, uint32_t rows) {

    return move_region(d, level, layer, (uint8_t *)dst_storage, (uint8_t *)src_linear, src_pitch, x0, y0, row_bytes, rows, 0);

}
