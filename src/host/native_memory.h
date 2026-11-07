/* SPDX-License-Identifier: MIT */
/* Fault-contained self copies, including RADV's CPU-visible DMA-BUF heap.
 * process_vm_* pins ordinary VM pages; mapped device memory may return EFAULT.
 * A private pipe uses kernel copy_{from,to}_user without pinning or FOLL_FORCE:
 * read-only/unmapped targets still fail. Callers retain address/region policy.
 */
#pragma once
#ifdef __linux__
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <sys/uio.h>
#include <unistd.h>

enum { ND_MEMORY_COPY_LIMIT=1024 };
static inline int nd_memory_pipe_copy(uint64_t address,void *local,size_t size,int writing) {
    if(!address || !local || !size || size>ND_MEMORY_COPY_LIMIT || address>UINT64_MAX-size) return 0;
    if(writing) {
        long page=sysconf(_SC_PAGESIZE);
        if(page<=0 || size>(size_t)page || address%(uint64_t)page>(uint64_t)page-size) return 0;
    }
    int fd[2];
    if(pipe2(fd,O_CLOEXEC|O_NONBLOCK)) return 0;
    void *remote=(void *)(uintptr_t)address;
    const void *source=writing?local:remote;
    void *target=writing?remote:local;
    ssize_t stored=write(fd[1],source,size);
    ssize_t copied=stored==(ssize_t)size?read(fd[0],target,size):-1;
    int saved=errno;
    close(fd[0]);close(fd[1]);errno=saved;
    return copied==(ssize_t)size;
}
static inline int nd_memory_copy(uint64_t address,void *local,size_t size,int writing) {
    if(!address || !local || !size || size>ND_MEMORY_COPY_LIMIT || address>UINT64_MAX-size) return 0;
    struct iovec l={local,size},r={(void *)(uintptr_t)address,size};
    ssize_t copied=writing?process_vm_writev(getpid(),&l,1,&r,1,0):process_vm_readv(getpid(),&l,1,&r,1,0);
    if(copied==(ssize_t)size) return 1;
    /* Do not retry a partial write, permission denial, or unrelated failure. */
    if(copied>=0 || errno!=EFAULT) return 0;
    return nd_memory_pipe_copy(address,local,size,writing);
}
#endif
