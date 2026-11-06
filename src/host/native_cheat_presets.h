/* SPDX-License-Identifier: MIT */
/* Original bounded definitions, public version-specific interoperability facts.
 * Pointer locations cross-checked against fixed EdiZon / MyNXCheats sources in docs/cheat-presets.md.
 * No executable game instructions, keys, dump bytes or code patches are bundled. */
#pragma once
typedef struct {const char *name;int n;uint32_t words[24];} NdBuiltinCheat;
static const NdBuiltinCheat nd_botw_defaults[]={
    {"Infinite health",9,{0x580f0000,0x02ca1a78,0x580f1000,0x80,0x780f0000,0x848,0x610f0000,0,0x78}},
    {"Infinite stamina",9,{0x580f0000,0x02c9fd70,0x580f1000,0x38,0x780f0000,0x2ac,0x680f0000,0x453b8000,0x453b8000}},
    {"Rupees 999999",11,{0x580f0000,0x02cc5fe0,0x580f1000,0xe40,0x580f1000,0x5b08,0x780f0000,0x5d90,0x640f0000,0,0xf423f}}
};
static const NdBuiltinCheat nd_totk_defaults[]={
    {"Moon jump (hold in-game jump)",21,{0x80000004,0x580f0000,0x03ad99b8,0x580f1000,0x70,0x580f1000,0x40,
        0x580f1000,0xd0,0x580f1000,0xc0,0x580f1000,0x198,0x580f1000,0x38,0x780f0000,0xf4,0x640f0000,0,0x41200000,0x20000000}}
};
