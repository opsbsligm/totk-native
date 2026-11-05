/* SPDX-License-Identifier: MIT */
/* Read-only six-axis fallback for Steam's sensorless virtual Deck gamepad.
 * Never sends a HID feature report, grabs input, or remaps buttons. */
#define _GNU_SOURCE 1
#include "deck_motion.h"
#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

extern uint64_t runtime_now_ns(void);
extern void runtime_motion_feed(const double acc[3], const double gyro[3], uint64_t now);
extern void runtime_motion_live(int on);

/* SDL's main/event thread owns start/stop. The reader owns only sensor samples. */
static pthread_t reader;
static _Atomic int running;
static int started, sensor_fd = -1;

static int hidraw_name(const char *name) {
    if (strncmp(name, "hidraw", 6) || !name[6]) return 0;
    size_t n = 6;
    while (name[n] && n < 24) {
        if (!isdigit((unsigned char)name[n])) return 0;
        n++;
    }
    return name[n] == 0;
}
static int deck_device(const char *name) {
    char *path = NULL;
    if (asprintf(&path, "/sys/class/hidraw/%s/device/uevent", name) < 0) return 0;
    FILE *f = fopen(path, "re");
    free(path);
    if (!f) return 0;
    char line[256]; int valid = 0;
    while (fgets(line, sizeof line, f))
        if (!strcmp(line, "HID_ID=0003:000028DE:00001205\n")) valid = 1;
    fclose(f);
    return valid;
}
static int newest_sample(int fd, uint32_t *packet, double acc[3], double gyro[3]) {
    unsigned char report[64]; int valid = 0;
    for (unsigned i = 0; i < 64; i++) {
        ssize_t n = read(fd, report, sizeof report);
        if (n < 0) {
            if (errno == EINTR) continue;
            return errno == EAGAIN || errno == EWOULDBLOCK ? valid : -1;
        }
        if (n == 0) return -1;
        if (nd_deck_motion_decode(report, (size_t)n, packet, acc, gyro)) valid = 1;
    }
    return valid;
}
static void *read_motion(void *unused) {
    (void)unused;
    uint32_t previous = 0; int have_packet = 0;
    uint64_t flushed_at = 0;
    while (atomic_load_explicit(&running, memory_order_relaxed)) {
        struct pollfd p = { .fd = sensor_fd, .events = POLLIN };
        int ready = poll(&p, 1, 100);
        if (ready < 0 && errno == EINTR) continue;
        if (ready < 0 || (p.revents & (POLLERR | POLLHUP | POLLNVAL))) break;
        if (!ready) continue;
        uint32_t packet; double acc[3], gyro[3];
        int valid = newest_sample(sensor_fd, &packet, acc, gyro);
        if (valid < 0) break;
        if (valid && (!have_packet || packet != previous)) {
            /* Drain queued reports and publish only the newest sample with host
             * monotonic time. Replaying old buffered reports would fake freshness. */
            previous = packet; have_packet = 1;
            uint64_t now = runtime_now_ns();
            runtime_motion_feed(acc, gyro, now);
            if (!flushed_at) {
                fprintf(stderr, "[deck-motion] first valid sample: acc (%+.3f %+.3f %+.3f) G\n", acc[0], acc[1], acc[2]);
            }
            if (!flushed_at || now - flushed_at >= 30000000000ull) {
                /* The game redirects stderr to a buffered session log. Make
                 * existing fusion/game-read counters observable without waiting
                 * for unrelated rendering messages to fill the stdio buffer. */
                fflush(stderr);
                flushed_at = now;
            }
        }
    }
    runtime_motion_live(0);
    fprintf(stderr, "[deck-motion] sensor reader stopped; no stale motion is published\n");
    return NULL;
}
void nd_deck_motion_stop(void) {
    if (!started) return;
    atomic_store_explicit(&running, 0, memory_order_relaxed);
    pthread_join(reader, NULL);
    close(sensor_fd); sensor_fd = -1; started = 0;
    runtime_motion_live(0);
}
int nd_deck_motion_start(void) {
    nd_deck_motion_stop();
    const char *opt = getenv("TOTK_STEAMDECK_GYRO");
    if (opt && !strcmp(opt, "0")) return 0;
    DIR *dir = opendir("/sys/class/hidraw");
    if (!dir) return 0;
    struct pollfd candidates[32]; unsigned count = 0;
    struct dirent *entry;
    while (count < 32 && (entry = readdir(dir))) {
        if (!hidraw_name(entry->d_name) || !deck_device(entry->d_name)) continue;
        char *path = NULL;
        if (asprintf(&path, "/dev/%s", entry->d_name) < 0) continue;
        int fd = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC | O_NOFOLLOW);
        free(path);
        if (fd < 0) continue;
        struct stat st;
        if (fstat(fd, &st) || !S_ISCHR(st.st_mode)) { close(fd); continue; }
        candidates[count++] = (struct pollfd){ .fd = fd, .events = POLLIN };
    }
    closedir(dir);
    for (unsigned attempt = 0; count && attempt < 5 && sensor_fd < 0; attempt++) {
        if (poll(candidates, count, 50) <= 0) continue;
        for (unsigned i = 0; i < count; i++) {
            uint32_t packet; double acc[3], gyro[3];
            if ((candidates[i].revents & POLLIN) && newest_sample(candidates[i].fd, &packet, acc, gyro) > 0) {
                sensor_fd = candidates[i].fd;
                break;
            }
        }
    }
    for (unsigned i = 0; i < count; i++)
        if (candidates[i].fd != sensor_fd) close(candidates[i].fd);
    if (sensor_fd < 0) return 0;
    atomic_store_explicit(&running, 1, memory_order_relaxed);
    runtime_motion_live(1);
    if (pthread_create(&reader, NULL, read_motion, NULL)) {
        atomic_store_explicit(&running, 0, memory_order_relaxed);
        close(sensor_fd); sensor_fd = -1; runtime_motion_live(0); return 0;
    }
    started = 1;
    fprintf(stderr, "[deck-motion] native read-only IMU enabled; Steam retains buttons and controller settings\n");
    return 1;
}
