/* SPDX-License-Identifier: MIT */
#include "native_camera.h"
#include <math.h>
#include <stdatomic.h>
#include <stdint.h>

_Static_assert(sizeof(float) == sizeof(uint32_t), "Camera scalar must be 32 bits");

/* Defined by the generated main table only after both guarded hooks emit.
 * A runtime archive alone must never advertise a working game capability. */
extern const uint32_t nd_totk_camera_profile_v143 __attribute__((weak));
static atomic_int percent = 100;
static atomic_int applied_percent;

bool nd_totk_camera_available(void) {
    return &nd_totk_camera_profile_v143 && nd_totk_camera_profile_v143 == 1;
}
bool nd_totk_camera_configure(int value) {
    if (value < 70 || value > 150 || (value != 100 && !nd_totk_camera_available()))
        return false;
    int previous = atomic_exchange_explicit(&percent, value, memory_order_relaxed);
    if (previous != value)
        atomic_store_explicit(&applied_percent, 0, memory_order_relaxed);
    return true;
}
int nd_totk_camera_percent(void) {
    return atomic_load_explicit(&percent, memory_order_relaxed);
}
int nd_totk_camera_applied_percent(void) {
    return atomic_load_explicit(&applied_percent, memory_order_relaxed);
}
uint32_t nd_totk_camera_adjust_bits(uint32_t original) {
    int value = nd_totk_camera_percent();
    /* Inherit the original float bits, including NaN/zero, without arithmetic. */
    if (value == 100) return original;
    /* C union representation access avoids pointer aliasing or buffer copies. */
    union { uint32_t bits; float angle; } scalar = {.bits = original};
    float angle = scalar.angle;
    float adjusted = angle * ((float)value / 100.0f);
    if (!isfinite(angle) || angle <= 0.0f || angle >= 3.14159265f || !isfinite(adjusted)
            || adjusted <= 0.0f || adjusted >= 3.14159265f) return original;
    scalar.angle = adjusted;
    atomic_store_explicit(&applied_percent, value, memory_order_relaxed);
    return scalar.bits;
}
