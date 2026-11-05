/* Original native input policy, MIT. Physical east/south are bits 0/1 here. */
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
typedef struct { bool active; unsigned blocked; } NdMenuConfirm;
uint64_t nd_menu_confirm(NdMenuConfirm *, bool active, unsigned held,
                         uint64_t east_actions, uint64_t south_actions);
typedef bool (*NdMenuRead)(void *, uint64_t, void *, size_t);
/* Exact TOTK 1.4.3 profile. Unknown/malformed/unreadable state stays gameplay. */
bool nd_totk_menu_context(NdMenuRead read, void *user);
