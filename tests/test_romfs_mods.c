// Exercise production nn::fs reads against synthetic base files and real mod descriptors.
#define _GNU_SOURCE
#include "hle.h"
#undef HLE_NATIVE
#define HLE_NATIVE(sym, cfn, kind)
#include "fs.c"
#include <assert.h>

_Noreturn void runtime_fail(const char *message) { fputs(message, stderr); abort(); }
uint64_t runtime_now_ns(void) { return 0; }
void plat_commit(uint64_t address, uint64_t size) { (void)address; (void)size; abort(); }
int linux_sha256_hex(const void *a, size_t na, const void *b, size_t nb, char out[65]) {
    (void)a; (void)na; (void)b; (void)nb; (void)out;
    abort(); // Font replacements are covered separately; mods must not invoke this path.
}

static void put(const char *path, const char *text) {
    FILE *f = fopen(path, "wb"); assert(f);
    size_t n = strlen(text); assert(fwrite(text, 1, n, f) == n); assert(!fclose(f));
}
static void read_equals(const char *path, const char *expected) {
    uint64_t h = 0, n = 999;
    int64_t size = -1;
    char data[64] = {0};
    assert(romfs_open(&h, path, OPEN_READ) == 0);
    assert(romfs_size(&size, h) == 0 && size == (int64_t)strlen(expected));
    assert(romfs_read(&n, h, 0, data, sizeof data) == 0 && n == strlen(expected));
    assert(!memcmp(data, expected, (size_t)n));
    assert(romfs_read(&n, h, size, data, sizeof data) == 0 && n == 0);
    assert(romfs_read(&n, h, size + 1, data, sizeof data) == R_ROM_INVALID);
    romfs_close(h);
}
int main(int argc, char **argv) {
    (void)argv;
    assert(!mkdir("base", 0700));
    put("base/common.bin", "original");
    put("base/fallback.bin", "base fallback");
    if (argc == 2) {
        put("base/romfs.bin", "originalbase fallback");
        const char names[] = "common.bin\0fallback.bin\0";
        uint64_t count = 2, strings = 24 + 2 * sizeof(Entry);
        Entry records[] = {{0, 8, 0, 11}, {8, 13, 11, 13}};
        FILE *index = fopen("base/runtime-index.bin", "wb"); assert(index);
        assert(fwrite("TOTKRFS1", 1, 8, index) == 8);
        assert(fwrite(&count, 8, 1, index) == 1);
        assert(fwrite(&strings, 8, 1, index) == 1);
        assert(fwrite(records, sizeof records, 1, index) == 1);
        assert(fwrite(names, sizeof names - 1, 1, index) == 1);
        assert(!fclose(index));
    }
    assert(!mkdir("mods", 0700));
    assert(!mkdir("mods/20-last", 0700));
    assert(!mkdir("mods/20-last/romfs", 0700));
    assert(!mkdir("mods/10-first", 0700));
    assert(!mkdir("mods/10-first/romfs", 0700));
    assert(!mkdir("mods/.disabled", 0700));
    assert(!mkdir("mods/.disabled/romfs", 0700));
    put("mods/.disabled/romfs/common.bin", "disabled");
    put("mods/10-first/romfs/common.bin", "first");
    put("mods/20-last/romfs/common.bin", "last mod has a different size");
    put("mods/10-first/romfs/added.bin", "new file");
    put("mods/10-first/romfs/empty.bin", "");
    assert(!mkdir("mods/10-first/romfs/newdir", 0700));
    put("mods/10-first/romfs/newdir/file.bin", "nested");
    assert(!setenv("TOTK_ROMFS", "base", 1));
    assert(!setenv("TOTK_MODS_DIR", "mods", 1));
    assert(mount_rom("rom", NULL, 0) == 0);
    assert(rom_mods.count == 2);
    read_equals("rom:/common.bin", "last mod has a different size");
    read_equals("rom:/fallback.bin", "base fallback");
    read_equals("rom:/added.bin", "new file");
    read_equals("rom:/empty.bin", "");
    read_equals("rom:/newdir/file.bin", "nested");
    int type = -1;
    assert(romfs_entry_type(&type, "rom:/newdir") == 0 && type == 0);
    assert(romfs_entry_type(&type, "rom:/added.bin") == 0 && type == 1);
    uint64_t h = 0;
    assert(romfs_open(&h, "rom:/missing", OPEN_READ) == R_PATH_NOT_FOUND);
    assert(romfs_open(&h, "rom:/../base/common.bin", OPEN_READ) == R_PATH_NOT_FOUND);
    assert(romfs_open(&h, "rom:/newdir", OPEN_READ) == R_PATH_NOT_FOUND);
    assert(romfs_open(&h, "rom:/common.bin", OPEN_WRITE) == R_ROM_UNSUPPORTED);
    assert(!symlink("../../../base/common.bin", "mods/20-last/romfs/escape.bin"));
    assert(romfs_open(&h, "rom:/escape.bin", OPEN_READ) == R_ROM_INVALID);
    assert(!symlink("../../../base", "mods/20-last/romfs/escape-dir"));
    assert(romfs_open(&h, "rom:/escape-dir/common.bin", OPEN_READ) == R_ROM_INVALID);
    assert(!mkfifo("mods/20-last/romfs/fifo", 0600));
    assert(romfs_open(&h, "rom:/fifo", OPEN_READ) == R_ROM_INVALID);
    // A live handle owns its descriptor even if its mod file is subsequently removed.
    assert(romfs_open(&h, "rom:/added.bin", OPEN_READ) == 0);
    assert(!unlink("mods/10-first/romfs/added.bin"));
    char data[16]; uint64_t n;
    assert(romfs_read(&n, h, 0, data, sizeof data) == 0 && n == 8 && !memcmp(data, "new file", 8));
    romfs_close(h);
    assert(romfs_open(&h, "rom:/added.bin", OPEN_READ) == R_PATH_NOT_FOUND);
    nd_mods_close(&rom_mods);
    read_equals("rom:/common.bin", "original");
    assert(!symlink("10-first", "mods/symlink-mod"));
    assert(nd_mods_init(&rom_mods, "mods") == -1 && rom_mods.count == 0);
    assert(nd_mods_init(&rom_mods, NULL) == 0 && rom_mods.count == 0);
    assert(!mkdir("too-many", 0700));
    for (int i = 0; i <= ND_MOD_LIMIT; i++) {
        char path[128];
        snprintf(path, sizeof path, "too-many/%02d", i); assert(!mkdir(path, 0700));
        snprintf(path, sizeof path, "too-many/%02d/romfs", i); assert(!mkdir(path, 0700));
    }
    assert(nd_mods_init(&rom_mods, "too-many") == -1 && rom_mods.count == 0);
    puts("RomFS mods: real reads, sizes, priority, added/empty files, fallback, path and descriptor lifetime passed");
}
