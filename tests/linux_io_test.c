// Native POSIX behavior checks; no game code, guest tables or GPU are used.
#define _GNU_SOURCE
#include "platform/linux_io.h"
#include <assert.h>
#include <fcntl.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

static void put(const char *path, const char *text) {
    FILE *f = fopen(path, "wb");
    assert(f && fwrite(text, 1, strlen(text), f) == strlen(text));
    assert(fclose(f) == 0);
}
int main(int argc, char **argv) {
    assert(argc == 2); // caller supplies a project-local test directory
    char path[PATH_MAX], temp[PATH_MAX], directory[PATH_MAX];
    assert(snprintf(directory, sizeof directory, "%s/io-XXXXXX", argv[1]) > 0);
    assert(mkdtemp(directory));
    snprintf(path, sizeof path, "%s/cache.bin", directory);
    snprintf(temp, sizeof temp, "%s/cache.new", directory);
    put(path, "old");
    size_t n = 999;
    const char *mapped = linux_map_readonly(path, 3, &n);
    assert(mapped && n == 3 && !memcmp(mapped, "old", 3));
    assert(linux_unmap_readonly((void *)mapped, n));
    assert(!linux_map_readonly(path, 4, &n) && n == 0);
    assert(!linux_map_readonly(directory, 0, &n));
    assert(symlink(path, temp) == 0);
    assert(!linux_map_readonly(temp, 0, &n));
    assert(unlink(temp) == 0);
    put(temp, "");
    assert(!linux_map_readonly(temp, 0, &n));
    puts("PASS mapping: regular nonempty file, minimum size, full unmap");
    size_t page = (size_t)sysconf(_SC_PAGESIZE);
    char *p = mmap(NULL, page * 3, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    assert(p != MAP_FAILED);
    assert(linux_host_readable((uintptr_t)p, page * 3));
    assert(!linux_host_readable((uintptr_t)p, 0));
    assert(!linux_host_readable(UINTPTR_MAX - 1, 4));
    assert(mprotect(p + page, page, PROT_NONE) == 0);
    assert(!linux_host_readable((uintptr_t)p, page * 3));
    assert(linux_host_readable((uintptr_t)p, page));
    assert(munmap(p + page, page) == 0);
    assert(!linux_host_readable((uintptr_t)p, page * 3));
    assert(munmap(p, page) == 0 && munmap(p + page * 2, page) == 0);
    puts("PASS readable range: no access, unmapped hole, overflow, valid interval");
    assert(!linux_replace_file("/nonexistent-ultratears-cache", path));
    mapped = linux_map_readonly(path, 0, &n);
    assert(mapped && n == 3 && !memcmp(mapped, "old", 3));
    assert(linux_unmap_readonly((void *)mapped, n));
    put(temp, "new-value");
    assert(!linux_replace_file(temp, directory)); // rename over directory must fail
    assert(access(temp, F_OK) == 0);
    assert(linux_replace_file(temp, path));
    assert(access(temp, F_OK) != 0);
    mapped = linux_map_readonly(path, 0, &n);
    assert(mapped && n == 9 && !memcmp(mapped, "new-value", 9));
    assert(linux_unmap_readonly((void *)mapped, n));
    puts("PASS atomic replacement: failure preserves files; success publishes full contents");
    FILE *f = fopen(path, "r+b");
    assert(f && linux_truncate_file(f, 4) == 0);
    struct stat st;
    assert(fstat(fileno(f), &st) == 0 && st.st_size == 4);
    assert(linux_truncate_file(f, UINT64_MAX) == -1);
    assert(fclose(f) == 0);
    puts("PASS truncate: native size change and overflow rejection");
    char h[65], split[65];
    assert(linux_sha256_hex("abc", 3, NULL, 0, h));
    assert(!strcmp(h, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"));
    assert(linux_sha256_hex("a", 1, "bc", 2, split) && !strcmp(h, split));
    assert(linux_sha256_hex(NULL, 0, NULL, 0, h));
    assert(!strcmp(h, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"));
    puts("PASS SHA256: known vector, segmented input, empty input");
    assert(unlink(path) == 0 && rmdir(directory) == 0);
    return 0;
}
