"""Exercise the production Linux write-watch ABI under injected kernel results."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'linux', 'Linux UAPI')
class LinuxWriteWatch(unittest.TestCase):
    def test_pagination_rearming_failures_and_descriptor_cleanup(self):
        code = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>
static long kernel_syscall(long n, ...);
static int kernel_ioctl(int fd, unsigned long request, ...);
static int kernel_open(const char *path, int flags, ...);
static int kernel_close(int fd);
static int kernel_madvise(void *p, size_t n, int advice);
#define syscall kernel_syscall
#define ioctl kernel_ioctl
#define open kernel_open
#define close kernel_close
#define madvise kernel_madvise
#include "src/runtime/platform/linux_watch.h"
enum { OK, NO_UFFD, BAD_API, MISSING_FEATURES, NO_PAGEMAP, BAD_REGISTER, BAD_ADVISE, BAD_SCAN, BAD_REGION, NO_PROGRESS, TOO_MANY };
static int mode, calls, closed, written[4];
static const uint64_t base = 0x40000000;
static long kernel_syscall(long n, ...) {
    assert(n == SYS_userfaultfd);calls++;
    va_list ap;va_start(ap,n);int flags=va_arg(ap,int);va_end(ap);
    assert((flags & (O_CLOEXEC|O_NONBLOCK|UFFD_USER_MODE_ONLY)) == (O_CLOEXEC|O_NONBLOCK|UFFD_USER_MODE_ONLY));
    if(mode==NO_UFFD) {errno=EPERM;return -1;} return 10;
}
static int kernel_open(const char *p,int flags,...) {
    assert(!strcmp(p,"/proc/self/pagemap") && (flags&O_CLOEXEC));
    if(mode==NO_PAGEMAP) {errno=EACCES;return -1;}return 11;
}
static int kernel_close(int fd) {assert(fd==10 || fd==11);closed++;return 0;}
static int kernel_madvise(void *p,size_t n,int advice) {
    assert((uintptr_t)p==base && n==16384 && advice==MADV_NOHUGEPAGE);return mode==BAD_ADVISE?-1:0;
}
static int kernel_ioctl(int fd,unsigned long request,...) {
    calls++;va_list ap;va_start(ap,request);void *arg=va_arg(ap,void*);va_end(ap);
    if(request==UFFDIO_API) {
        assert(fd==10);struct uffdio_api *a=arg;assert(a->api==UFFD_API);
        if(mode==BAD_API) return -1;
        if(mode==MISSING_FEATURES) a->features=0;
        return 0;
    }
    if(request==UFFDIO_REGISTER) {
        struct uffdio_register *r=arg;assert(fd==10 && r->mode==UFFDIO_REGISTER_MODE_WP && r->range.start==base && r->range.len==16384);
        return mode==BAD_REGISTER?-1:0;
    }
    assert(request==PAGEMAP_SCAN && fd==11);
    struct pm_scan_arg *a=arg;assert(a->flags==(PM_SCAN_WP_MATCHING|PM_SCAN_CHECK_WPASYNC));
    if(mode==BAD_SCAN) return -1;
    if(mode==TOO_MANY) return 65;
    if(mode==NO_PROGRESS) {a->walk_end=a->start;return 0;}
    struct page_region *r=(void*)(uintptr_t)a->vec;
    if(mode==BAD_REGION) {r[0]=(struct page_region){a->start,a->end+4096,0};a->walk_end=a->end;return 1;}
    int count=0;a->walk_end=a->end;
    for(uint64_t p=a->start;p<a->end;p+=4096) {
        int i=(p-base)/4096;
        if(!written[i]) continue;
        written[i]=0;r[count++]=(struct page_region){p,p+4096,PAGE_IS_WRITTEN};
        if((uint64_t)count==a->max_pages) {a->walk_end=p+4096;break;}
    }
    return count;
}
int main(void) {
    unsetenv("TOTK_POOL_COPY");unsetenv("TOTK_POOL_IMPORT");unsetenv("TOTK_WRITE_WATCH");
    linux_watch_init(base,base+16384);assert(calls==0 && g_linux_uffd<0);
    setenv("TOTK_POOL_COPY","1",1);setenv("TOTK_POOL_IMPORT","1",1);
    linux_watch_init(base,base+16384);assert(calls==0);unsetenv("TOTK_POOL_IMPORT");
    setenv("TOTK_WRITE_WATCH","0",1);linux_watch_init(base,base+16384);assert(calls==0);unsetenv("TOTK_WRITE_WATCH");
    for(mode=NO_UFFD;mode<=BAD_ADVISE;mode++) {
        int before=closed;linux_watch_init(base,base+16384);assert(g_linux_uffd<0 && g_linux_pagemap<0);
        assert(closed-before==(mode==NO_UFFD?0:mode<=NO_PAGEMAP?1:2));
    }
    mode=OK;linux_watch_init(base,base+16384);assert(g_linux_uffd==10 && g_linux_pagemap==11);
    uint64_t pages[2]={123,456},size=0;
    int before=calls;
    assert(linux_watch_pages(base,16384,pages,0,&size)==-1);
    assert(linux_watch_pages(base,16384,NULL,2,&size)==-1);
    assert(linux_watch_pages(base,16384,pages,2,NULL)==-1);
    assert(linux_watch_pages(UINT64_MAX-4095,8192,pages,2,&size)==-1);
    assert(linux_watch_pages(base+1,4096,pages,2,&size)==-1 && calls==before);
    written[1]=written[3]=1;
    assert(linux_watch_pages(base,16384,pages,1,&size)==1 && pages[0]==base+4096 && pages[1]==456 && size==4096);
    assert(written[3]==1);
    assert(linux_watch_pages(base+8192,8192,pages,2,&size)==1 && pages[0]==base+12288);
    assert(linux_watch_pages(base,16384,pages,2,&size)==0);
    for(mode=BAD_SCAN;mode<=TOO_MANY;mode++) assert(linux_watch_pages(base,16384,pages,2,&size)==-1);
    linux_watch_close();assert(g_linux_uffd<0 && g_linux_pagemap<0);
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='write-watch-', dir=Path.cwd()) as directory:
            source = Path(directory) / 'watch.c'
            binary = Path(directory) / 'watch'
            source.write_text(code)
            subprocess.run(['cc', '-std=gnu17', '-O1', '-fsanitize=address,undefined',
                            '-fno-sanitize-recover=all', '-I', str(ROOT), str(source), '-o', str(binary)],
                           check=True, capture_output=True, text=True, timeout=40)
            subprocess.run([str(binary)], check=True, timeout=8)
