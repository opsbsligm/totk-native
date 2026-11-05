// Linux operations used by the native Vulkan back end. GPL-3.0-or-later.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

void *linux_map_readonly(const char *path, size_t minimum, size_t *size);
int linux_unmap_readonly(void *data, size_t size);
int linux_host_readable(uintptr_t address, size_t size);
int linux_replace_file(const char *temporary, const char *destination);
int linux_truncate_file(FILE *stream, uint64_t size);
int linux_sha256_hex(const void *a, size_t na, const void *b, size_t nb, char out[65]);
void linux_worker_priority(int idle);
