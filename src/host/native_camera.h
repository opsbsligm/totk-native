/* SPDX-License-Identifier: MIT */
#pragma once
#include <stdbool.h>
#ifdef __cplusplus
extern "C" {
#endif
bool nd_totk_camera_available(void);
bool nd_totk_camera_configure(int percent);
int nd_totk_camera_percent(void);
int nd_totk_camera_applied_percent(void);
/* Only the low float is touched. No guest ABI or other registers are changed. */
void nd_totk_camera_apply(void *scalar);
#ifdef __cplusplus
}
#endif
