/* Six pinned read-only UI resources. No arbitrary mod paths. MIT. */
#pragma once
#ifndef _WIN32
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include "platform/linux_io.h"

enum { ND_DECK_RESOURCE_COUNT = 6, ND_DECK_RESOURCE_HEADER = 8 + 80 * ND_DECK_RESOURCE_COUNT };
static const char *const nd_font_paths[ND_DECK_RESOURCE_COUNT] = {
    "Font/Font.Nin_NX_NVN.bfarc.zs", "Font/Font_CNzh.Nin_NX_NVN.bfarc.zs",
    "Font/Font_KRko.Nin_NX_NVN.bfarc.zs", "Font/Font_TWzh.Nin_NX_NVN.bfarc.zs",
    "UI/LayoutArchive/Common.Product.140.Nin_NX_NVN.blarc.zs",
    "System/Resource/ResourceSizeTable.Product.143.Nin_NX_NVN.rsizetable.zs"
};
static int nd_font_index(const char *path) {
    for (int i = 0; i < ND_DECK_RESOURCE_COUNT; i++) if (!strcmp(path, nd_font_paths[i])) return i;
    return -1;
}
static uint64_t nd_font_u64(const uint8_t *p) {
    uint64_t n = 0;
    for (unsigned i = 0; i < 8; i++) n |= (uint64_t)p[i] << (8 * i);
    return n;
}
static int nd_font_read(int fd, void *buffer, size_t size, uint64_t offset) {
    if (offset > INT64_MAX || size > (uint64_t)INT64_MAX - offset) return 0;
    uint8_t *p = buffer;
    while (size) {
        ssize_t n = pread(fd, p, size, (off_t)offset);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return 0;
        p += n; size -= (size_t)n; offset += (uint64_t)n;
    }
    return 1;
}
static int nd_font_hash(int fd, uint64_t offset, uint64_t size, const uint8_t expected[32]) {
    if (!size || size > 32u * 1024u * 1024u) return 0;
    void *data = malloc((size_t)size);
    if (!data) return 0;
    char hash[65];
    int ok = nd_font_read(fd, data, (size_t)size, offset) && linux_sha256_hex(data, (size_t)size, NULL, 0, hash);
    free(data);
    static const char hex[] = "0123456789abcdef";
    for (unsigned i = 0; ok && i < 32; i++)
        ok = hash[i * 2] == hex[expected[i] >> 4] && hash[i * 2 + 1] == hex[expected[i] & 15];
    return ok;
}
/* Caller retains its source fd. Returned descriptor has an independent lifetime.
   The launcher verifies the full package manifest; this additionally binds each
   replacement to the actually opened original RomFS file and both exact hashes. */
static int nd_font_open(const char *directory, int index, int source_fd,
                        uint64_t source_offset, uint64_t source_size, uint64_t *size) {
    if (index < 0 || index >= ND_DECK_RESOURCE_COUNT || !size) return -1;
    int root = -1, manifest = -1, replacement = -1, ok = 0;
    uint8_t header[ND_DECK_RESOURCE_HEADER];
    struct stat st;
    root = open(directory, O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    if (root < 0) goto done;
    manifest = openat(root, "fonts.bin", O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
    if (manifest < 0 || fstat(manifest, &st) || !S_ISREG(st.st_mode) || st.st_size != (off_t)sizeof header ||
        !nd_font_read(manifest, header, sizeof header, 0) || memcmp(header, "NDUIF002", 8)) goto done;
    const uint8_t *record = header + 8 + 80 * index;
    uint64_t old_size = nd_font_u64(record), new_size = nd_font_u64(record + 8);
    if (old_size != source_size || !nd_font_hash(source_fd, source_offset, old_size, record + 16)) goto done;
    char name[] = "0.zs"; name[0] += (char)index;
    replacement = openat(root, name, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
    if (replacement < 0 || fstat(replacement, &st) || !S_ISREG(st.st_mode) || st.st_size < 0 ||
        (uint64_t)st.st_size != new_size || !nd_font_hash(replacement, 0, new_size, record + 48)) goto done;
    *size = new_size; ok = 1;
done:
    if (manifest >= 0) close(manifest);
    if (root >= 0) close(root);
    if (!ok && replacement >= 0) close(replacement);
    return ok ? replacement : -1;
}
#endif
