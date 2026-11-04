// ASTC textures as BC7 (decided 2026-10-24): desktop GPUs and the Steam Deck have no ASTC, so
// ASTC was decoded on the CPU to RGBA8 at every upload (the hitches when new parts of the world stream in, 4x the video
// memory). BC7 is what these GPUs sample natively, at 8 bits per texel - not fewer bits than TOTK's ASTC blocks.
// A cache of BC7 data by the contents of the ASTC blocks: the key of a surface (one level of one layer; every slice of a
// 3D level) is a 128-bit hash of its ASTC blocks in rows (as deswizzled for an upload) with its size and block size
// (tex/bc7key.c) - the same bytes whichever way the game lays the texture out in memory, so the build can fill the cache
// from the RomFS (next step) and the game finds the entries. Until then the cache fills as textures are met: a miss is
// decoded as before and encoded to BC7 in the background for the next time.
// Optional TOTK_BC7_CACHE_DIR on Linux: read-only TOTK_BC7_DIR base + writable delta.
// Files (TOTK_BC7_DIR, default data/textures): bc7.pack (the blocks, appended) and bc7.idx (32-byte records: key,
// offset, length, format - 0 BC7, 1 BC1; appended after the blocks are written, so an entry always has its data).
// BC1: the interface's 12x12 ASTC maps when opaque (tools/bc7build: a texture is BC1 only if none of its texels is
// transparent; half the bytes of BC7, and 12x12 ASTC holds less detail than BC1 keeps). Nothing from the game is
// in the repository or a build: the cache is made on the player's machine from the player's copy (README.md, Legal).
#ifdef _WIN32
#include <direct.h>
#endif
// Overlay adaptation: GPL-3.0-or-later, same as upstream ultratears.
#include <limits.h>
#ifdef __linux__
#include <sys/stat.h>
#include <sys/file.h>
#include <fcntl.h>
#include <unistd.h>
#endif
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#else
#include "../runtime/platform/linux_io.h"
#endif

#include "compat/gfx_compat.h"
#include "host/hle.h"
#include "vkb.h"
#include "tex/bc7.h"
#include "tex/bc7key.h"

#define VLOG(...) LOG("[vk] " __VA_ARGS__)

int vkb_bc7_on(void) {   // TOTK_BC7=0: decode ASTC to RGBA8 as before (A/B)
    static int on = -1;
    if (on < 0) { const char *e = getenv("TOTK_BC7"); on = !(e && *e == '0'); }
    return on;
}

// ---- the key (tex/bc7key.c: the build computes the same)
vkb_bc7_key vkb_bc7_key_of(const uint8_t *blocks, size_t n, uint32_t w, uint32_t h, uint32_t depth, uint32_t bw, uint32_t bh, int srgb) {
    (void)srgb;   // not part of the key: the BC7 bytes serve both views
    bc7_key k = bc7_key_of(blocks, n, w, h, depth, bw, bh);
    return (vkb_bc7_key){k.a, k.b};
}

// ---- the index in memory (open addressing) and the files
typedef struct { uint64_t a, b, off; uint32_t len, fmt; } rec_t;   // also the record in bc7.idx (fmt: VKB_BC_*)
static rec_t *g_tab;
static size_t g_cap, g_n;
static FILE *g_pack, *g_idx, *g_base;
#define BC7_DELTA (UINT64_C(1) << 63)
_Static_assert(sizeof(rec_t) == 32, "BC7 disk ABI");
static int g_overlay;
// bc7.pack as it was when opened, mapped read-only: a read is a copy, no file call and no lock (a texture has hundreds
// of surfaces; fseek + fread each, under g_mu, was much of an upload). The pages are the system's file cache, as the
// reads were: no memory of the game's, dropped by the system when it needs the RAM. Blocks appended later (encoded in
// the background) are read from the file.
static const uint8_t *g_map;
static uint64_t g_map_size;
static pthread_mutex_t g_mu = PTHREAD_MUTEX_INITIALIZER;
static int g_open;   // 1 open, -1 cannot be used
static uint64_t g_hits, g_misses, g_encoded, g_dropped, g_encode_ns;

static rec_t *slot(uint64_t a, uint64_t b) {   // g_mu held, g_cap a power of two
    size_t h = (size_t)(a ^ (b * 0x9E3779B97F4A7C15ull)) & (g_cap - 1);
    while ((g_tab[h].a || g_tab[h].b) && !(g_tab[h].a == a && g_tab[h].b == b)) h = (h + 1) & (g_cap - 1);
    return &g_tab[h];
}
static void put(const rec_t *r) {   // g_mu held
    if (g_n >= SIZE_MAX / 2 - 1) die("BC7 index overflow");
    if ((g_n + 1) * 2 > g_cap) {
        if (g_cap > SIZE_MAX / 2 / sizeof *g_tab) die("BC7 index overflow");
        rec_t *old = g_tab;
        size_t n = g_cap;
        g_cap = g_cap ? g_cap * 2 : 1 << 16;
        if (!(g_tab = calloc(g_cap, sizeof *g_tab))) die("BC7 index");
        for (size_t i = 0; i < n; i++) if (old[i].a || old[i].b) *slot(old[i].a, old[i].b) = old[i];
        free(old);
    }
    rec_t *s = slot(r->a, r->b);
    if (!s->a && !s->b) g_n++;
    *s = *r;
}
static const char *dir(void) {
    const char *d = getenv("TOTK_BC7_DIR");
    return d && *d ? d : "data/textures";
}
// A malformed index invalidates the whole cache; never append past a torn record.
static int load_index(FILE *idx, uint64_t size, uint64_t tag) {
    rec_t r;
    size_t n;
    rewind(idx);
    while ((n = fread(&r, 1, sizeof r, idx)) != 0) {
        if (n != sizeof r || !(r.a || r.b) || !r.len ||
            (r.fmt != VKB_BC_7 && r.fmt != VKB_BC_1) ||
            r.off >= BC7_DELTA || r.off > size || r.len > size - r.off) return 0;
        r.off |= tag;  // memory only: disk records always contain an ordinary offset
        put(&r);      // base first, then delta; latest disk record wins
    }
    return !ferror(idx);
}
static int file_size(FILE *f, uint64_t *out) {
    if (_fseeki64(f, 0, SEEK_END)) return 0;
    int64_t n = _ftelli64(f);
    if (n < 0 || (uint64_t)n >= BC7_DELTA) return 0;
    *out = (uint64_t)n;
    return 1;
}
static int path_of(char path[512], const char *d, const char *name) {
    int n = snprintf(path, 512, "%s/%s", d, name);
    return n >= 0 && n < 512;
}
static int make_dir(const char *d) {
    char path[512];
    if (!*d || strlen(d) >= sizeof path - 16) return 0;
    strcpy(path, d);
    for (char *p = path + 1; *p; p++) if (*p == '/' || *p == '\\') {
        char c = *p; *p = 0; _mkdir(path); *p = c;
    }
    _mkdir(path);
    return 1;
}
#ifdef __linux__
static int same_file(FILE *a, FILE *b) {
    struct stat x, y;
    return fstat(fileno(a), &x) || fstat(fileno(b), &y) ||
           (x.st_dev == y.st_dev && x.st_ino == y.st_ino);
}
static FILE *delta_file(const char *path) {
    int fd = open(path, O_RDWR | O_CREAT | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) return NULL;
    struct stat st;
    if (fstat(fd, &st) || !S_ISREG(st.st_mode) || flock(fd, LOCK_EX | LOCK_NB)) {
        close(fd); return NULL;
    }
    FILE *f = fdopen(fd, "r+b");
    if (!f) close(fd);
    return f;
}
#endif
static int open_files(void) {   // g_mu held; no writable fallback in overlay mode
    if (g_open) return g_open > 0;
    g_open = -1;
    char path[512];
    const char *d = dir(), *cache = getenv("TOTK_BC7_CACHE_DIR");
    g_overlay = cache && *cache;
    FILE *base_idx = NULL;
    uint64_t pack_size, delta_size;
    if (!path_of(path, d, "bc7.pack")) goto fail;
    if (g_overlay) {
#ifdef __linux__
        g_base = fopen(path, "rb");
        if (!g_base || !file_size(g_base, &pack_size) ||
            !path_of(path, d, "bc7.idx") || !(base_idx = fopen(path, "rb"))) goto fail;
        if (!load_index(base_idx, pack_size, 0) || !make_dir(cache)) goto fail;
        struct stat x, y;
        if (stat(d, &x) || stat(cache, &y) ||
            (x.st_dev == y.st_dev && x.st_ino == y.st_ino)) goto fail;
        if (!path_of(path, cache, "bc7.pack") || !(g_pack = delta_file(path)) ||
            !path_of(path, cache, "bc7.idx") || !(g_idx = delta_file(path))) goto fail;
        if (same_file(g_pack, g_idx) || same_file(g_pack, g_base) || same_file(g_pack, base_idx) ||
            same_file(g_idx, g_base) || same_file(g_idx, base_idx)) goto fail;
        if (!file_size(g_pack, &delta_size) ||
            !load_index(g_idx, delta_size, BC7_DELTA)) goto fail;
        fclose(base_idx); base_idx = NULL;
#else
        VLOG("BC7 overlay requires Linux file identity/locking support");
        goto fail;
#endif
    } else {
        if (!make_dir(d)) goto fail;
        if (!(g_pack = fopen(path, "r+b")) && !(g_pack = fopen(path, "w+b"))) goto fail;
        if (!file_size(g_pack, &pack_size) || !path_of(path, d, "bc7.idx")) goto fail;
        if (!(g_idx = fopen(path, "r+b")) && !(g_idx = fopen(path, "w+b"))) goto fail;
        if (!load_index(g_idx, pack_size, 0)) goto fail;
    }
    if (!path_of(path, d, "bc7.pack")) goto fail;
#ifdef __linux__
    size_t mapped_size = 0;
    if (pack_size > 0 && pack_size <= SIZE_MAX) {
        g_map = linux_map_readonly(path, (size_t)pack_size, &mapped_size);
        if (g_map) g_map_size = pack_size; // never map the growing delta
    }
#else
    HANDLE f = pack_size > 0 ? CreateFileA(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL, OPEN_EXISTING,
                                           FILE_ATTRIBUTE_NORMAL, NULL) : INVALID_HANDLE_VALUE;
    HANDLE m = f != INVALID_HANDLE_VALUE ? CreateFileMappingA(f, NULL, PAGE_READONLY, (DWORD)(pack_size >> 32), (DWORD)pack_size, NULL) : NULL;
    if (f != INVALID_HANDLE_VALUE) CloseHandle(f);
    if (m) { g_map = MapViewOfFile(m, FILE_MAP_READ, 0, 0, (SIZE_T)pack_size); CloseHandle(m); }
    if (g_map) g_map_size = pack_size;
#endif
    VLOG("BC7 cache %s: %zu surfaces%s", d, g_n, g_overlay ? " (read-only base + delta)" : "");
    g_open = 1;
    return 1;
fail:
    if (base_idx) fclose(base_idx);
    if (g_base) { fclose(g_base); g_base = NULL; }
    if (g_pack) { fclose(g_pack); g_pack = NULL; }
    if (g_idx) { fclose(g_idx); g_idx = NULL; }
    free(g_tab); g_tab = NULL; g_cap = g_n = 0;
    VLOG("BC7 cache disabled: invalid/unavailable files or base/cache alias");
    return 0;
}

int vkb_bc7_lookup(vkb_bc7_key k, int *fmt, size_t *len) {
    pthread_mutex_lock(&g_mu);
    int ok = open_files() && g_cap;
    if (ok) { rec_t *s = slot(k.a, k.b); ok = (s->a || s->b) && s->len; if (ok) { *fmt = (int)s->fmt; *len = s->len; } }
    pthread_mutex_unlock(&g_mu);
    return ok;
}
int vkb_bc7_has(vkb_bc7_key k, size_t n) {
    int fmt; size_t len;
    return vkb_bc7_lookup(k, &fmt, &len) && fmt == VKB_BC_7 && len == n;
}
int vkb_bc7_read(vkb_bc7_key k, uint8_t *out, size_t n) {
    pthread_mutex_lock(&g_mu);
    int ok = open_files() && g_cap;
    rec_t r = {0};
    if (ok) { r = *slot(k.a, k.b); ok = (r.a || r.b) && r.len == n; }
    int delta = !!(r.off & BC7_DELTA);
    r.off &= ~BC7_DELTA;
    int mapped = ok && !delta && r.off <= g_map_size && n <= g_map_size - r.off;
    FILE *f = g_overlay && !delta ? g_base : g_pack;
    if (ok && !mapped) ok = !_fseeki64(f, (int64_t)r.off, SEEK_SET) && fread(out, 1, n, f) == n;
    if (ok) g_hits++; else g_misses++;
    pthread_mutex_unlock(&g_mu);
    if (mapped) memcpy(out, g_map + r.off, n);   // (the mapped part is never written again)
    return ok;
}
void vkb_bc7_store(vkb_bc7_key k, const uint8_t *data, size_t n) { vkb_bc_store(k, data, n, VKB_BC_7); }
void vkb_bc_store(vkb_bc7_key k, const uint8_t *data, size_t n, int fmt) {
    if (!(k.a || k.b) || !data || !n || n > UINT32_MAX ||
        (fmt != VKB_BC_7 && fmt != VKB_BC_1)) return;
    pthread_mutex_lock(&g_mu);
    if (open_files() && !(g_cap && (slot(k.a, k.b)->a || slot(k.a, k.b)->b))) {
        uint64_t end;
        if (!file_size(g_pack, &end) || n > (BC7_DELTA - 1) - end) goto write_fail;
        rec_t r = {k.a, k.b, end, (uint32_t)n, (uint32_t)fmt};
        if (fwrite(data, 1, n, g_pack) != n || fflush(g_pack) ||
            _fseeki64(g_idx, 0, SEEK_END) || fwrite(&r, sizeof r, 1, g_idx) != 1 || fflush(g_idx)) goto write_fail;
        if (g_overlay) r.off |= BC7_DELTA;
        put(&r); // publish only after both streams flush successfully
    }
    pthread_mutex_unlock(&g_mu);
    return;
write_fail:
    g_open = -1; // no more writes or lookups after a partial write; validate on restart
    pthread_mutex_unlock(&g_mu);
}

// ---- encoding in the background (a miss: next time it is there)
typedef struct job { vkb_bc7_key k; uint8_t *rgba; uint32_t w, h, d; int srgb; struct job *next; } job;
static job *g_jobs, **g_tail = &g_jobs;
static size_t g_queued_bytes;
static pthread_mutex_t g_jmu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t g_jcv = PTHREAD_COND_INITIALIZER;
enum { QUEUE_MAX = 512u << 20, ENCODERS = 2 };
static int quality(void) {   // TOTK_BC7_QUALITY=0..4 (bc7enc's uber level; background encoding)
    static int q = -1;
    // 0 by default: met in play this is a stopgap (one large surface took ~0.75 s at level 1); the build fills the cache
    if (q < 0) { const char *e = getenv("TOTK_BC7_QUALITY"); q = e && *e ? atoi(e) : 0; }
    return q;
}
static void *encoder(void *unused) {
    (void)unused;
    pthread_setname_np("totk-bc7");
#ifdef __linux__
    linux_worker_priority(1);
#else
    SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_LOWEST);
#endif   // the game's and the recording threads come first
    for (;;) {
        pthread_mutex_lock(&g_jmu);
        while (!g_jobs) pthread_cond_wait(&g_jcv, &g_jmu);
        job *j = g_jobs;
        g_jobs = j->next;
        if (!g_jobs) g_tail = &g_jobs;
        size_t in = (size_t)j->w * j->h * j->d * 4;
        pthread_mutex_unlock(&g_jmu);
        size_t n = bc7_size(j->w, j->h, j->d);
        if (!vkb_bc7_has(j->k, n)) {
            uint8_t *out = malloc(n);
            if (out) {
                uint64_t t0 = runtime_now_ns();
                bc7_encode(j->rgba, j->w, j->h, j->d, j->srgb, quality(), out);
                vkb_bc7_store(j->k, out, n);
                __atomic_fetch_add(&g_encode_ns, runtime_now_ns() - t0, __ATOMIC_RELAXED);
                __atomic_fetch_add(&g_encoded, 1, __ATOMIC_RELAXED);
                free(out);
            }
        }
        free(j->rgba);
        free(j);
        pthread_mutex_lock(&g_jmu);
        g_queued_bytes -= in;
        pthread_mutex_unlock(&g_jmu);
    }
    return NULL;
}
void vkb_bc7_queue(vkb_bc7_key k, const uint8_t *rgba, uint32_t w, uint32_t h, uint32_t d, int srgb) {
    size_t in = (size_t)w * h * (d ? d : 1) * 4;
    pthread_mutex_lock(&g_jmu);
    if (g_queued_bytes + in > QUEUE_MAX) { g_dropped++; pthread_mutex_unlock(&g_jmu); return; }   // met again later
    g_queued_bytes += in;
    pthread_mutex_unlock(&g_jmu);
    job *j = malloc(sizeof *j);
    uint8_t *copy = malloc(in);
    if (!j || !copy) { free(j); free(copy); pthread_mutex_lock(&g_jmu); g_queued_bytes -= in; pthread_mutex_unlock(&g_jmu); return; }
    memcpy(copy, rgba, in);
    *j = (job){k, copy, w, h, d ? d : 1, srgb, NULL};
    static int started;
    pthread_mutex_lock(&g_jmu);
    if (!started) {
        started = 1;
        for (int i = 0; i < ENCODERS; i++) {
            pthread_t t;
            if (pthread_create(&t, NULL, encoder, NULL) == 0) pthread_detach(t);
        }
    }
    *g_tail = j;
    g_tail = &j->next;
    pthread_cond_signal(&g_jcv);
    pthread_mutex_unlock(&g_jmu);
}
// A miss on an image that is BC7 / BC1 already (its contents changed after it became one): encoded now, quickly.
void vkb_bc7_encode_now(vkb_bc7_key k, const uint8_t *rgba, uint32_t w, uint32_t h, uint32_t d, int srgb, int fmt, uint8_t *out) {
    if (fmt == VKB_BC_1) { bc1_encode(rgba, w, h, d ? d : 1, 4, out); return; }   // (not kept: the cache keys BC1 by the build's choice)
    bc7_encode(rgba, w, h, d ? d : 1, srgb, 0, out);
    vkb_bc7_store(k, out, bc7_size(w, h, d ? d : 1));
}
void vkb_bc7_stats(uint64_t *hits, uint64_t *misses, uint64_t *encoded, uint64_t *dropped, uint64_t *encode_ns, size_t *queued) {
    pthread_mutex_lock(&g_mu);
    *hits = g_hits; *misses = g_misses;
    pthread_mutex_unlock(&g_mu);
    *encoded = __atomic_load_n(&g_encoded, __ATOMIC_RELAXED); *encode_ns = __atomic_load_n(&g_encode_ns, __ATOMIC_RELAXED);
    pthread_mutex_lock(&g_jmu);
    *dropped = g_dropped; *queued = g_queued_bytes;
    pthread_mutex_unlock(&g_jmu);
}
