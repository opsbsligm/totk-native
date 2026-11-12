/* Read-only Linux RomFS mods. Original implementation, MIT. */
#pragma once
#ifndef _WIN32
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

enum { ND_MOD_LIMIT = 64 };
typedef struct { char *name; int fd; } NDModRoot;
typedef struct { NDModRoot roots[ND_MOD_LIMIT]; size_t count; } NDMods;

static void nd_mods_close(NDMods *mods) {
    for (size_t i = 0; i < mods->count; ++i) {
        close(mods->roots[i].fd);
        free(mods->roots[i].name);
    }
    mods->count = 0;
}
static int nd_mod_order(const void *a, const void *b) {
    return strcmp(((const NDModRoot *)a)->name, ((const NDModRoot *)b)->name);
}
/* Enumerate once at startup. Keep directory descriptors so replacing a mod's
   path cannot redirect an active session. Hidden mods are disabled. */
static int nd_mods_init(NDMods *mods, const char *directory) {
    if (!directory || !*directory) return 0;
    int fd = open(directory, O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return errno == ENOENT ? 0 : -1;
    DIR *dir = fdopendir(fd);
    if (!dir) { close(fd); return -1; }
    int result = 0;
    for (;;) {
        errno = 0;
        struct dirent *e = readdir(dir);
        if (!e) { if (errno) result = -1; break; }
        if (e->d_name[0] == '.') continue;
        struct stat st;
        if (fstatat(fd, e->d_name, &st, AT_SYMLINK_NOFOLLOW)) { result = -1; break; }
        if (S_ISLNK(st.st_mode)) { result = -1; break; }
        if (!S_ISDIR(st.st_mode)) continue;
        int mod = openat(fd, e->d_name, O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
        if (mod < 0) { result = -1; break; }
        int rom = openat(mod, "romfs", O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
        int saved = errno;
        close(mod);
        if (rom < 0) {
            if (saved == ENOENT) continue;
            result = -1; break;
        }
        if (mods->count == ND_MOD_LIMIT) { close(rom); result = -1; break; }
        char *name = strdup(e->d_name);
        if (!name) { close(rom); result = -1; break; }
        mods->roots[mods->count++] = (NDModRoot){name, rom};
    }
    closedir(dir);
    if (result) { nd_mods_close(mods); return -1; }
    qsort(mods->roots, mods->count, sizeof mods->roots[0], nd_mod_order);
    return 0;
}

/* Return 1 and an independently owned descriptor, 0 for absence, -1 for an
   invalid/unreadable override. Traverse every component without following links.
   Later bytewise-sorted mod names win; no recursive scans occur on game reads. */
static int nd_mods_open(const NDMods *mods, const char *path, int *out, struct stat *st) {
    if (!path || !*path || path[0] == '/' || strchr(path, '\\') || strlen(path) >= 4096) return -1;
    for (const char *p = path; *p;) {
        const char *end = strchr(p, '/');
        size_t n = end ? (size_t)(end - p) : strlen(p);
        if (!n || (n == 1 && *p == '.') || (n == 2 && !memcmp(p, "..", 2)) || (end && !end[1])) return -1;
        if (!end) break;
        p = end + 1;
    }
    for (size_t i = mods->count; i > 0; --i) {
        char buffer[4096];
        strcpy(buffer, path);
        char *part = buffer;
        int parent = dup(mods->roots[i - 1].fd);
        if (parent < 0) return -1;
        for (;;) {
            char *slash = strchr(part, '/');
            if (slash) *slash = 0;
            int fd = openat(parent, part, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK |
                            (slash ? O_DIRECTORY : 0));
            int saved = errno;
            close(parent);
            if (fd < 0) {
                if (saved == ENOENT) break;
                return -1;
            }
            if (slash) { parent = fd; part = slash + 1; continue; }
            if (fstat(fd, st) || (!S_ISREG(st->st_mode) && !S_ISDIR(st->st_mode)) || st->st_size < 0) {
                close(fd); return -1;
            }
            *out = fd;
            return 1;
        }
    }
    return 0;
}
#endif
