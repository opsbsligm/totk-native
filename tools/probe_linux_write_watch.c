// Unprivileged probe of this process's Linux write-watch support. GPL-3.0-or-later.
#define _GNU_SOURCE
#include <assert.h>
#include "../src/runtime/platform/linux_watch.h"

int main(void) {
    setenv("TOTK_POOL_COPY", "1", 1);
    unsetenv("TOTK_POOL_IMPORT");
    unsetenv("TOTK_WRITE_WATCH");
    uint8_t *p = mmap(NULL, 16384, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (p == MAP_FAILED) return 1;
    linux_watch_init((uintptr_t)p, (uintptr_t)p + 16384);
    uint64_t pages[8], page = 0;
    if (linux_watch_pages((uintptr_t)p, 16384, pages, 8, &page) < 0) {
        puts("{\"write_watch_supported\":false,\"hardware_validated\":false}");
        linux_watch_close();munmap(p, 16384);return 3;
    }
    p[0] = 1;p[12288] = 2;
    assert(linux_watch_pages((uintptr_t)p, 16384, pages, 1, &page) == 1 && pages[0] == (uintptr_t)p);
    assert(linux_watch_pages((uintptr_t)p + 4096, 12288, pages, 8, &page) == 1 && pages[0] == (uintptr_t)p + 12288);
    assert(linux_watch_pages((uintptr_t)p, 16384, pages, 8, &page) == 0);
    int fd = open("/dev/zero", O_RDONLY | O_CLOEXEC);
    assert(fd >= 0 && read(fd, p + 4096, 1) == 1);close(fd);
    assert(linux_watch_pages((uintptr_t)p, 16384, pages, 8, &page) == 1 && pages[0] == (uintptr_t)p + 4096);
    linux_watch_close();munmap(p, 16384);
    puts("{\"write_watch_supported\":true,\"write_pages_and_rearm_verified\":true,\"kernel_write_verified\":true,\"hardware_validated\":false}");
    return 0;
}
