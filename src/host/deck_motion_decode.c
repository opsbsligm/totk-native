/* SPDX-License-Identifier: MIT */
/* Steam Deck report coordinates/scales follow SDL 3.2.30's public Steam Deck
 * backend, composed with UltraTears' SDL-to-Switch sensor rotation. This is an
 * independent sensor-only decoder, not SDL's controller configuration code.
 * See docs/native-motion.md for the public reference and byte layout. */
#include "deck_motion.h"

static int signed_le16(const unsigned char *p) {
    unsigned value = (unsigned)p[0] | (unsigned)p[1] << 8;
    return value >= 32768 ? (int)value - 65536 : (int)value;
}
int nd_deck_motion_decode(const unsigned char *p, size_t bytes,
                          uint32_t *packet, double acc[3], double gyro[3]) {
    if (!p || bytes != 64 || !packet || !acc || !gyro) return 0;
    if (p[0] != 1 || p[1] != 0 || p[2] != 9 || p[3] != 64) return 0;
    /* Steam can keep status reports flowing with IMU_MODE=0. Zero gravity
     * on all axes is not a usable orientation sample. Do not fake freshness. */
    if (!(p[24] | p[25] | p[26] | p[27] | p[28] | p[29])) return 0;
    *packet = (uint32_t)p[4] | (uint32_t)p[5] << 8 | (uint32_t)p[6] << 16 | (uint32_t)p[7] << 24;
    const double gravity_scale = -2.0 / 32768.0;
    const double angular_scale = (2000.0 / 32768.0) * (3.14159265358979323846 / 180.0);
    for (unsigned axis = 0; axis < 3; axis++) {
        acc[axis] = signed_le16(p + 24 + axis * 2) * gravity_scale;
        gyro[axis] = signed_le16(p + 30 + axis * 2) * angular_scale;
    }
    return 1;
}
