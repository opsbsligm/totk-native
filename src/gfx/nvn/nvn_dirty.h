// 客体内存写保护脏页跟踪（nvn_dirty.c）
// Write-protect dirty-page tracking for guest memory (nvn_dirty.c)
#pragma once
#include <stddef.h>
#include <stdint.h>

void nvn_dirty_add_range(const void *mem, size_t size);           // 登记一个内存池为跟踪区间（首次调用时注册缺页钩子与宿主写前钩子） | Register a memory pool as a tracked range (the first call registers the page-fault hook and the host pre-write hook)
void nvn_dirty_stat(int *live, int *peak, int *cap);                // 在册的内存池数、峰值、跟踪表容量（内存读数行用） | number of registered memory pools, peak, tracking table capacity (for the memory readout line)
void nvn_dirty_remove_range(const void *mem);                     // 池销毁：受保护页还原可写并标失效 | Pool destruction: restore protected pages to writable and mark invalid
int nvn_dirty_tracked(const void *addr, size_t len);
void nvn_dirty_protect(const void *addr, size_t len);              // 覆盖页设只读 | Set the covered pages read-only
uint64_t nvn_dirty_now(void);                                      // 当前代号：上传前取，作为该份内容的戳 | Current generation: taken before upload, as the stamp of that content
int nvn_dirty_since(const void *addr, size_t len, uint64_t stamp);
// Runs of pages written since stamp (merged when closer than gap bytes): fn(ctx, offset, bytes); -1 = untracked
void nvn_dirty_epoch_begin(void);   // [Windows port] a new submission: one write-watch scan per range on this thread until the next
int nvn_dirty_runs(const void *addr, size_t len, uint64_t stamp, size_t gap, void (*fn)(void *ctx, size_t off, size_t n), void *ctx);
void *nvn_dirty_gpu_write_begin(void *addr, size_t len);   // write guest memory on behalf of the GPU: not counted as a CPU write
void nvn_dirty_gpu_write_end(void *tok);
typedef struct { uintptr_t page; uint64_t pc, lr; uint32_t src; } nvn_dirty_rec;   // src 0: guest write (fault), 1: host write
int nvn_dirty_recent(uintptr_t lo, uintptr_t hi, nvn_dirty_rec *out, int max);   // latest unprotections in [lo, hi) (DM_NVN_TILELOG) // 覆盖页在戳之后被写过 → 1 | Covered pages were written after the stamp -> 1
void nvn_dirty_stats(uint64_t *faults, uint64_t *preps);           // 累计：游戏写触发的缺页次数、宿主写前解保护的页数 | Cumulative: number of page faults triggered by game writes, number of pages unprotected before host writes
void nvn_dirty_mp_stats(uint64_t *calls, uint64_t *pages, uint64_t *ns);   // 累计：本模块 mprotect 调用次数、覆盖页数、耗时 | Cumulative: this module's mprotect call count, pages covered, time spent
// 扫描归因：内核调用的次数与耗时按发起它的代码位置分别记账（nvn_dirty_win.c）。调用方在进入某段逻辑前标记
// 自己的位置，之后该线程上的扫描就记到该位置名下。仅记账，不改变任何行为。 | Scan attribution: the ioctl count and
// time are booked per code location that started it. A caller names its location before the logic that scans; later scans
// on that thread are booked to it. Bookkeeping only -- it changes no behaviour.
enum { NVN_SCAN_WHO_TEX_STALE = 0,   // "does this texture's game memory hold new bytes" (vkb_tex.c)
       NVN_SCAN_WHO_TAKE_BACK,       // an attachment taken back by a texture (vkb_tex.c)
       NVN_SCAN_WHO_WB_MERGE,        // the retire thread copying GPU writes back (backend_vk.c)
       NVN_SCAN_WHO_SNAP_TAKE,       // the "before" copy of a GPU write (backend_vk.c)
       NVN_SCAN_WHO_SYNC_GATHER,     // bringing a pool copy up to date (backend_vk.c)
       NVN_SCAN_WHO_PC_SYNC,         // the host-visible pool sync (backend_vk.c)
       NVN_SCAN_WHO_VCHECK,          // a development check comparing a copy with game memory
       NVN_SCAN_WHO_VPOOL,           // a virtual pool's physical pages (totk_vpool_win.c)
       NVN_SCAN_WHO_GPU_WRITE,       // a look that forgets the GPU's own writes (nvn_dirty_gpu_write_end)
       NVN_SCAN_WHO_OTHER,
       NVN_SCAN_WHO_COUNT };
void nvn_dirty_scan_who(int who);   // 本线程后续的扫描记到此位置 | later scans on this thread are booked here
void nvn_dirty_scan_stats(uint64_t *calls, uint64_t *ns, int max);   // 每个位置的累计调用次数与耗时 | per-location totals
void nvn_dirty_slot_stats(int *live, int *used_slots, uint64_t *adds_total); // 当前存活槽、槽表高水位、登记总次数 | Currently live slots, slot table high-water mark, total number of registrations

// Explicit CPU flush notices. marked_since: -1 unknown range, 0 no notice, 1 changed.
// This does not claim OS write tracking or that unnotified memory is clean.
int nvn_dirty_mark_range(const void *addr, size_t len);
int nvn_dirty_marked_since(const void *addr, size_t len, uint64_t stamp);
uint64_t nvn_dirty_notice_epoch(void);
