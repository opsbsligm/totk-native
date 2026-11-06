/* SPDX-License-Identifier: MIT */
#pragma once
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct {char name[97],note[160];int enabled,supported;} NdAtmInfo;
typedef void (*NdAtmHeap)(uint64_t *base,uint64_t *size);
void nd_atm_bind(const char *build,uint64_t main_base,uint64_t data_start,uint64_t data_size,NdAtmHeap heap);
int nd_atm_reload(const char *game); // XDG_DATA_HOME/<game>/cheats/<first8B-buildid>.txt
int nd_atm_reload_async(const char *game); // one detached, bounded import; UI never waits for file I/O
int nd_atm_loading(void);
void nd_atm_disable_all(void);
size_t nd_atm_count(void);
void nd_atm_info(size_t index,NdAtmInfo *out);
void nd_atm_request(size_t index,int enabled);
void nd_atm_frame(uint64_t keys);
const char *nd_atm_error(void);
const char *nd_atm_file(void);
#ifdef __cplusplus
}
#endif
