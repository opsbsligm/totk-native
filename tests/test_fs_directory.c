// Exercise the actual host filesystem implementation without registering guest HLE entries.
#define _GNU_SOURCE
#include "hle.h"
#undef HLE_NATIVE
#define HLE_NATIVE(sym, cfn, kind)
#include "fs.c"
#include <assert.h>

_Noreturn void runtime_fail(const char *message) { fputs(message, stderr); abort(); }
int main(int argc, char **argv) {
    assert(argc == 2);
    char real[1200], guest[1200] = "probe:/";
    assert(strlen(argv[1]) < 1024);
    snprintf(real, sizeof real, "%s", argv[1]);
    assert(mount_add("probe", M_TEMP, argv[1]) == 0);
    while (strlen(real) <= 1030) {
        char part[121];
        memset(part, 'a', 120); part[120] = 0;
        if (strlen(real) + 121 >= 1100) {
            size_t n = 1040 - strlen(real) - 1;
            assert(n > 0 && n < 120); part[n] = 0;
        }
        strcat(real, "/"); strcat(real, part);
        if (strlen(guest) > 7) strcat(guest, "/");
        strcat(guest, part);
        assert(mkdir(real, 0700) == 0);
    }
    assert(strlen(real) > 1024 && strlen(real) < 1100);
    uint64_t handle = UINT64_MAX;
    unsigned result = open_directory(&handle, guest, 1);
    printf("long path result=%#x handle=%llu\n", result, (unsigned long long)handle); fflush(stdout);
    assert(result == R_INVALID_PATH);
    assert(handle == UINT64_MAX && dirs[0].dir == NULL);
    assert(open_directory(&handle, "probe:/", 1) == 0);
    assert(handle == DIR_BASE && dirs[0].mode == 1);
    assert(strcmp(dirs[0].path, argv[1]) == 0);
    close_directory(handle);
    puts("Directory handle capacity: long existing path rejected; normal directory preserved");
    return 0;
}
