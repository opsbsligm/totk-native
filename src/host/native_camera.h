/* SPDX-License-Identifier: MIT */
#pragma once
#include <stdbool.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
bool nd_totk_camera_available(void);
bool nd_totk_camera_configure(int percent);
int nd_totk_camera_percent(void);
int nd_totk_camera_applied_percent(void);
/* Transform one scalar's bits by value; caller preserves the upper vector. */
uint32_t nd_totk_camera_adjust_bits(uint32_t original);
#ifdef __cplusplus
}
#endif
