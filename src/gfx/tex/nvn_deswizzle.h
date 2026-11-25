// Tegra 块线性 ↔ 线性。级 / 层偏移与逐级块高块深一律取 nvn/nvn_tex.c（nvn_tex_level_offset / nvn_tex_layout / nvn_tex_level_tiles）。
// Tegra block-linear ↔ linear. Level / layer offsets and per-level block height and block depth always come from nvn/nvn_tex.c (nvn_tex_level_offset / nvn_tex_layout / nvn_tex_level_tiles).
#pragma once
#include <stddef.h>
#include <stdint.h>
#include "../nvn/nvn_tex.h"

// 把第 level 级、第 layer 层（数组 / 立方体的层；非分层贴图取 0）从整张贴图存储 src_storage 解到线性 dst_linear。
// dst 按块行排：每行 dst_pitch 字节（≥ 本级块宽 × 每块字节），压缩格式一行 = 一行块。
// 3D 贴图：一次解出本级全部深度切片，切片 k 位于 dst_linear + k × dst_pitch × 本级块行数。
// 线性 / 线性渲染目标按行距复制；不支持多重采样、BUFFER，返回 -1。成功返回 0。
// Decode level number level, layer number layer (layer of an array / cube; 0 for non-layered textures) from the whole-texture storage src_storage into linear dst_linear.
// dst is laid out by block rows: dst_pitch bytes per row (≥ width in blocks of this level × bytes per block); for compressed formats one row = one row of blocks.
// 3D textures: all depth slices of this level are decoded at once; slice k is at dst_linear + k × dst_pitch × block row count of this level.
// Linear / linear-render-target storage is copied by pitch. Multisampling and BUFFER return -1; success returns 0.
int nvn_deswizzle(const nvn_texdesc *d, unsigned level, unsigned layer, const void *src_storage, void *dst_linear, size_t dst_pitch);
// 反向（单测往返用）：线性 src_linear → 写进整张贴图存储 dst_storage 的对应级 / 层
// Reverse (for unit test round trips): linear src_linear → written into the corresponding level / layer of the whole-texture storage dst_storage
int nvn_swizzle(const nvn_texdesc *d, unsigned level, unsigned layer, const void *src_linear, size_t src_pitch, void *dst_storage);
// 单点地址：本级本层内，线性 (x 字节, y 块行, z 切片) → 相对本级本层起点的块线性字节偏移（单测按手算核）
// Single-point address: within this level and layer, linear (x byte, y block row, z slice) → block-linear byte offset relative to the start of this level and layer (unit tests verify against hand calculation)
uint64_t nvn_bl_offset(uint32_t x, uint32_t y, uint32_t z, uint32_t row_bytes, uint32_t rows, unsigned tileH, unsigned tileD);

// 只搬第 level 级、第 layer 层里的一个矩形：x0/y0 是本级内的线性字节列与块行（压缩格式 = 块坐标），
// 宽 row_bytes 字节、高 rows 块行；dst_linear 行距 dst_pitch（≥ row_bytes）。正向解排布、反向回排布各一个入口，
// 反向只改矩形内的块线性字节（布局是置换，不需要读改写周边数据）。
// 游戏每次 WriteTexels 都只改地图的一小块，但整级搬运是 13 MiB 级：王国之泪左上角小地图因此每次闪一下
// （5120x5120 BC1，2026-11-25 真机日志 105 次、每次 20-26 ms）。
// Move only one rectangle of level `level`, layer `layer`: x0/y0 are the linear byte column and block row within the
// level (block coordinates for compressed formats), row_bytes wide and rows block rows high; dst rows are dst_pitch
// bytes apart (≥ row_bytes). The reverse direction rewrites only the rectangle's block-linear bytes — the layout is a
// permutation, so no read-modify-write of the surroundings is needed.
// LINEAR 存储、多重采样、BUFFER 与未知格式返回 -1；成功返回 0。
// LINEAR storage, multisampling, BUFFER and unknown formats return -1; success returns 0.
int nvn_deswizzle_region(const nvn_texdesc *d, unsigned level, unsigned layer, const void *src_storage,
                         void *dst_linear, size_t dst_pitch, uint32_t x0, uint32_t y0, uint32_t row_bytes, uint32_t rows);
int nvn_swizzle_region(const nvn_texdesc *d, unsigned level, unsigned layer, const void *src_linear, size_t src_pitch,
                       void *dst_storage, uint32_t x0, uint32_t y0, uint32_t row_bytes, uint32_t rows);

int nvn_deswizzle_geom(const nvn_texdesc *d, unsigned level, unsigned layer,
                       uint32_t *row_bytes, uint32_t *rows, uint32_t *slices,
                       uint64_t *base, unsigned *tileH, unsigned *tileD, uint32_t *bpb);
