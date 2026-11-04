// Native POSIX file mappings, shader-cache writes and hashing. GPL-3.0-or-later.
#define _GNU_SOURCE
#include "linux_io.h"
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <inttypes.h>
#include <ctype.h>
#include <openssl/evp.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

void *linux_map_readonly(const char *path, size_t minimum, size_t *size) {
    if (size) *size = 0;
    int fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return NULL;
    struct stat st;
    if (fstat(fd, &st) || !S_ISREG(st.st_mode) || st.st_size <= 0 ||
        (uintmax_t)st.st_size > SIZE_MAX || (uintmax_t)st.st_size < minimum) {
        close(fd);
        return NULL;
    }
    size_t bytes = (size_t)st.st_size;
    void *p = mmap(NULL, bytes, PROT_READ, MAP_PRIVATE, fd, 0);
    int saved = errno;
    close(fd);
    errno = saved;
    if (p == MAP_FAILED) return NULL;
    if (size) *size = bytes;
    return p;
}

int linux_unmap_readonly(void *data, size_t size) {
    return data && size && munmap(data, size) == 0;
}

int linux_host_readable(uintptr_t address, size_t size) {
    if (!size || address > UINTPTR_MAX - size) return 0;
    FILE *f = fopen("/proc/self/maps", "r");
    if (!f) return 0;
    uintptr_t cursor = address, end = address + size;
    char line[4096];
    uintmax_t lo, hi;
    int ok = 0;
    while (fgets(line, sizeof line, f)) {
        char *tail, *upper;
        if (!isxdigit((unsigned char)line[0])) continue;
        errno = 0;
        lo = strtoumax(line, &tail, 16);
        if (errno || *tail != '-') continue;
        upper = tail + 1;
        if (!isxdigit((unsigned char)*upper)) continue;
        errno = 0;
        hi = strtoumax(upper, &tail, 16);
        if (errno || *tail != ' ' || lo >= hi || hi > UINTPTR_MAX) continue;
        while (*tail == ' ') tail++;
        if (hi <= cursor) continue;
        if (lo > cursor || *tail != 'r') break;
        cursor = hi < end ? (uintptr_t)hi : end;
        if (cursor == end) { ok = 1; break; }
    }
    fclose(f);
    return ok;
}

int linux_replace_file(const char *temporary, const char *destination) {
    int fd = open(temporary, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return 0;
    int ok = fsync(fd) == 0;
    close(fd);
    if (!ok || rename(temporary, destination)) return 0;
    // A successful rename must be reported as such: the caller updates record
    // offsets to the replacement. A directory-sync failure affects durability,
    // not which file is now at destination.
    char *parent = strdup(destination);
    if (parent) {
        char *slash = strrchr(parent, '/');
        const char *directory = ".";
        if (slash) { if (slash == parent) slash[1] = 0; else *slash = 0; directory = parent; }
        fd = open(directory, O_RDONLY | O_CLOEXEC | O_DIRECTORY);
        if (fd >= 0) {
            if (fsync(fd)) fprintf(stderr, "[cache] directory sync failed: %s\n", strerror(errno));
            close(fd);
        }
        free(parent);
    }
    return 1;
}

int linux_truncate_file(FILE *stream, uint64_t size) {
    if (size > INT64_MAX || fflush(stream)) return -1;
    return ftruncate(fileno(stream), (off_t)size);
}

int linux_sha256_hex(const void *a, size_t na, const void *b, size_t nb, char out[65]) {
    EVP_MD_CTX *ctx = EVP_MD_CTX_new();
    unsigned char digest[EVP_MAX_MD_SIZE];
    unsigned int size = 0;
    int ok = ctx && EVP_DigestInit_ex(ctx, EVP_sha256(), NULL) == 1 &&
        (!na || EVP_DigestUpdate(ctx, a, na) == 1) &&
        (!nb || EVP_DigestUpdate(ctx, b, nb) == 1) &&
        EVP_DigestFinal_ex(ctx, digest, &size) == 1 && size == 32;
    EVP_MD_CTX_free(ctx);
    if (!ok) { out[0] = 0; return 0; }
    for (unsigned int i = 0; i < size; i++) {
        unsigned int high = digest[i] >> 4, low = digest[i] & 15;
        out[2*i] = (char)(high < 10 ? '0' + high : 'a' + high - 10);
        out[2*i+1] = (char)(low < 10 ? '0' + low : 'a' + low - 10);
    }
    out[64] = 0;
    return 1;
}

void linux_worker_priority(int idle) {
    // Lower only this worker, with no capabilities or global scheduler changes.
    (void)setpriority(PRIO_PROCESS, (id_t)syscall(SYS_gettid), idle ? 15 : 5);
}
