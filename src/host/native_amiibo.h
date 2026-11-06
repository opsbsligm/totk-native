/* SPDX-License-Identifier: MIT */
/* Virtual, read-only NTAG215 figure reader. No tag keys or copyrighted dumps. */
#pragma once
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#define ND_NFP_NOT_FOUND 0x8073u
#define ND_AMIIBO_MAX_FILES 64
typedef struct { int initialized,state,loaded; char name[256],error[160]; uint64_t generation; } NdAmiiboSnapshot;
void nd_amiibo_set_notify(void (*notify)(int activated));
void nd_amiibo_initialize(int on);
void nd_amiibo_snapshot(NdAmiiboSnapshot *out);
int nd_amiibo_load(const char *path);
void nd_amiibo_remove(void);
unsigned nd_amiibo_start(void);
unsigned nd_amiibo_stop(void);
unsigned nd_amiibo_mount(void);
unsigned nd_amiibo_unmount(void);
unsigned nd_amiibo_tag_info(void *out,size_t size);
unsigned nd_amiibo_model_info(void *out,size_t size);
// Bounded local library listing: filenames only, sorted, no symlinks or recursion.
int nd_amiibo_library(const char *game,char folder[4096],char names[ND_AMIIBO_MAX_FILES][256]);
#ifdef __cplusplus
}
#endif
