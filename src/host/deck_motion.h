#pragma once
#include <stddef.h>
#include <stdint.h>
/* Sensor-only decoding. No button state or controller configuration is used. */
int nd_deck_motion_decode(const unsigned char *report, size_t bytes,
                          uint32_t *packet, double acceleration_g[3], double gyro_rad_s[3]);
int nd_deck_motion_start(void);
void nd_deck_motion_stop(void);
