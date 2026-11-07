/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include <assert.h>
#include <dirent.h>
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>
#include "native_memory.h"
static int descriptors(void) {
    DIR *dir=opendir("/proc/self/fd");assert(dir);int n=0;
    while(readdir(dir)) n++;
    closedir(dir);return n;
}
int main(void) {
    long page=sysconf(_SC_PAGESIZE);assert(page>1024);
    unsigned char *p=mmap(NULL,(size_t)page*2,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    assert(p!=MAP_FAILED);memset(p,0x37,(size_t)page*2);
    uint64_t value=UINT64_C(0x123456789abcdef0),seen=0;
    assert(nd_memory_copy((uintptr_t)p+3,&value,sizeof value,1));
    assert(nd_memory_copy((uintptr_t)p+3,&seen,sizeof seen,0));assert(seen==value);
    int before=descriptors();
    for(int i=0;i<10000;i++) {
        value=(uint64_t)i;
        assert(nd_memory_pipe_copy((uintptr_t)p+3,&value,sizeof value,1));
        assert(nd_memory_pipe_copy((uintptr_t)p+3,&seen,sizeof seen,0));assert(seen==value);
    }
    assert(descriptors()==before);
    /* BOTW menu detection reads the complete 99-pointer screen table (792 B). */
    uint64_t table[99],copy[99];
    for(size_t i=0;i<99;i++) table[i]=UINT64_C(0x7240000000)+i*16;
    assert(nd_memory_pipe_copy((uintptr_t)p+32,table,sizeof table,1));
    assert(nd_memory_copy((uintptr_t)p+32,copy,sizeof copy,0));
    assert(!memcmp(table,copy,sizeof table));
    memset(copy,0,sizeof copy);
    assert(nd_memory_pipe_copy((uintptr_t)p+32,copy,sizeof copy,0));
    assert(!memcmp(table,copy,sizeof table));
    assert(mprotect(p+page,(size_t)page,PROT_READ)==0);
    unsigned char saved[8];memcpy(saved,p+page-4,sizeof saved);
    assert(!nd_memory_pipe_copy((uintptr_t)p+page-4,&value,8,1));
    assert(!memcmp(saved,p+page-4,sizeof saved));
    assert(!nd_memory_pipe_copy((uintptr_t)p+page,&value,8,1));
    assert(!memcmp(saved+4,p+page,4));
    assert(nd_memory_pipe_copy((uintptr_t)p+page,&seen,8,0));
    assert(mprotect(p+page,(size_t)page,PROT_NONE)==0);
    assert(!nd_memory_pipe_copy((uintptr_t)p+page,&seen,8,0));
    assert(!nd_memory_pipe_copy((uintptr_t)p+page,&value,8,1));
    assert(!nd_memory_pipe_copy(0,&seen,8,0));
    assert(!nd_memory_pipe_copy(UINT64_MAX-3,&seen,8,0));
    assert(!nd_memory_pipe_copy((uintptr_t)p,&seen,ND_MEMORY_COPY_LIMIT+1,0));
    assert(!nd_memory_pipe_copy((uintptr_t)p,NULL,8,0));
    assert(descriptors()==before);assert(munmap(p,(size_t)page*2)==0);
    return 0;
}
