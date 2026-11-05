#pragma once
#include "cpu.h"
float nd_totk_step(float hz);
static inline float nd_totk_reg(Cpu *c, unsigned reg) {
    union { uint32_t bits; float value; } scalar = { .bits = (uint32_t)c->v[reg] };
    return scalar.value;
}
void f_8002a0e40(Cpu *c);
