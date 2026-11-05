/* SPDX-License-Identifier: MIT */
/* Original guarded data-patch interface; shared by the two independent ports. */
#pragma once
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
void nd_cheats_bind(const char *game, const char *build_id, uint64_t module_base, uint64_t data_start, uint64_t data_bytes);
int nd_cheats_load(const char *path);
size_t nd_cheats_count(void);
const char *nd_cheats_name(size_t index);
int nd_cheats_enabled(size_t index);
void nd_cheats_request(size_t index,int enabled);
void nd_cheats_apply_pending(void);
const char *nd_cheats_error(void);
#ifdef __cplusplus
}
#endif
