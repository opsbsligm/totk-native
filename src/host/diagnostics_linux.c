// Optional Windows development tools are not part of Linux gameplay.
// Unsupported requests are explicit instead of pretending to record a profile.
// GPL-3.0-or-later.
#include "host.h"
#include <stdio.h>
#include <stdlib.h>

void runtime_profiler_start(void) {
    if (secure_getenv("TOTK_PROF"))
        fprintf(stderr, "[profile] TOTK_PROF is unavailable on Linux; use native perf tooling\n");
}

void runtime_watch_tick(uint64_t present) {
    static int warned;
    (void)present;
    if (!warned && secure_getenv("TOTK_WATCH")) {
        fprintf(stderr, "[watch] Windows guard-page diagnostics are unavailable on Linux\n");
        warned = 1;
    }
}
