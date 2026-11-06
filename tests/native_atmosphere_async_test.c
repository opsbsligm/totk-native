/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE 1
#include "native_atmosphere.h"
#include <assert.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
static _Atomic int slow,entered,release_read;
ssize_t __real_read(int,void *,size_t);
ssize_t __wrap_read(int fd,void *out,size_t n) {
    if(atomic_load(&slow)) {atomic_store(&entered,1);while(!atomic_load(&release_read)) usleep(1000);}
    return __real_read(fd,out,n);
}
static uint64_t memory[64];
static const char *id="0123456789ABCDEF000000000000000000000000000000000000000000000000";
static void bind(void) {nd_atm_bind(id,(uintptr_t)memory,(uintptr_t)memory+64,sizeof memory-64,NULL);}
static void wait_for(_Atomic int *flag) {for(int i=0;i<2000 && !atomic_load(flag);i++) usleep(1000);assert(atomic_load(flag));}
static void wait_done(void) {for(int i=0;i<2000 && nd_atm_loading();i++) usleep(1000);assert(!nd_atm_loading());}
int main(int argc,char **argv) {
    assert(argc==2);assert(!setenv("XDG_DATA_HOME",argv[1],1));char path[4096];
    snprintf(path,sizeof path,"%s/totk-native",argv[1]);assert(!mkdir(path,0700));
    snprintf(path,sizeof path,"%s/totk-native/cheats",argv[1]);assert(!mkdir(path,0700));
    snprintf(path,sizeof path,"%s/totk-native/cheats/0123456789ABCDEF.txt",argv[1]);
    FILE *f=fopen(path,"w");assert(f);fputs("[Static]\n04000000 00000040 0000002A\n",f);assert(!fclose(f));assert(!chmod(path,0600));bind();
    assert(!nd_atm_reload("totk-native"));assert(nd_atm_count()==1);
    atomic_store(&slow,1);assert(!nd_atm_reload_async("totk-native"));wait_for(&entered);
    // The worker is deliberately stalled inside read(). These production API calls must not wait for it.
    assert(nd_atm_loading());assert(nd_atm_count()==1);NdAtmInfo info;nd_atm_info(0,&info);assert(!info.enabled);
    assert(nd_atm_reload_async("totk-native")<0);nd_atm_frame(0);nd_atm_request(0,1);nd_atm_info(0,&info);assert(!info.enabled);nd_atm_disable_all();
    // Rebinding while the import is in flight invalidates its captured generation.
    bind();assert(!nd_atm_count());atomic_store(&release_read,1);wait_done();assert(!nd_atm_count());assert(strstr(nd_atm_error(),"changed"));
    atomic_store(&slow,0);assert(!nd_atm_reload_async("totk-native"));wait_done();assert(nd_atm_count()==1);
    nd_atm_info(0,&info);assert(info.supported && !info.enabled);nd_atm_request(0,1);nd_atm_frame(0);assert(memory[8]==42);
    nd_atm_disable_all();nd_atm_info(0,&info);assert(!info.enabled);puts("Async import: VM/UI never wait for file I/O; single worker, stale-generation discard and disable-all PASS");return 0;
}
