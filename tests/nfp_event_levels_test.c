/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE 1
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "../src/host/threads.c"
#include "../src/runtime/hle.h"
#undef HLE_NATIVE
#define HLE_NATIVE(...)
#include "../src/host/overrides_applet.c"

uint64_t guest_tls_alloc(void) {abort();}
Cpu *guest_cpu_new(uint64_t top,uint64_t tls) {(void)top;(void)tls;abort();}
void guest_cpu_set(Cpu *cpu) {(void)cpu;abort();}
void guest_call(Cpu *cpu,uint64_t address) {(void)cpu;(void)address;abort();}
void plat_commit(uint64_t address,uint64_t size) {(void)address;(void)size;abort();}
_Noreturn void runtime_fail(const char *text) {fprintf(stderr,"%s\n",text);abort();}
uint64_t runtime_now_ns(void) {struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (uint64_t)t.tv_sec*1000000000+t.tv_nsec;}
void *runtime_symbol(const char *text) {return (void *)(uintptr_t)(strstr(text,"CreateSystemEvent")?1:2);}
uint64_t guest_call_args(uint64_t fn,int n,const uint64_t *args) {
    assert(t_self && n>=1);uint32_t *event=(void *)(uintptr_t)args[0];
    if(fn==1) {uint64_t regs[32]={0};assert(svc_thread(0x45,regs));assert(!regs[0]);event[0]=(uint32_t)regs[1];event[1]=(uint32_t)regs[2];return 0;}
    assert(fn==2);return event[0];
}
static int signaled(uint32_t *event) {event_t *value=h_peek(event[0],O_EVENT_W);assert(value);return value->signaled;}
static void close_event(uint32_t *event) {
    for(int i=0;i<2;i++) {uint64_t regs[32]={event[i]};assert(svc_thread(0x16,regs));assert(!regs[0]);}
}
int main(void) {
    thr_t current={0};current.cur_core=-1;t_self=&current;
    uint64_t handle=1;uint32_t activate[2]={0},deactivate[2]={0};
    assert(!nfp_initialize());assert(!nfp_attach_activate(activate,&handle));assert(!nfp_attach_deactivate(deactivate,&handle));
    assert(!nfp_start(&handle));assert(!nd_amiibo_scan_virtual(0));
    assert(signaled(activate) && !signaled(deactivate));
    unsigned char previous[0x58]={0},tag[0x58];
    assert(!nfp_tag(previous,&handle));assert(!nfp_mount(&handle,0,1));
    for(int i=0;i<2048;i++) {
        assert(!nd_amiibo_scan_virtual(0));
        /* Manual-reset events may both remain uncleared by the client. The service
         * must withdraw the old level when removing/replacing a virtual figure. */
        assert(!signaled(activate) && signaled(deactivate));
        assert(!nfp_start(&handle));assert(signaled(activate) && !signaled(deactivate));
        assert(!nfp_tag(tag,&handle));assert(memcmp(previous,tag,7));memcpy(previous,tag,sizeof tag);
        assert(!nfp_mount(&handle,0,1));
    }
    assert(!nfp_stop(&handle));assert(!signaled(activate) && signaled(deactivate));
    assert(!nfp_start(&handle));assert(signaled(activate) && !signaled(deactivate));
    close_event(activate);close_event(deactivate);
    uint64_t unrelated[32]={0};assert(svc_thread(0x45,unrelated));
    event_t *other=h_peek((uint32_t)unrelated[1],O_EVENT_W);assert(other && !other->signaled);
    t_self=NULL;nd_amiibo_remove();assert(!other->signaled);
    t_self=&current;assert(!nfp_start(&handle));assert(!nfp_attach_activate(activate,&handle));assert(!nfp_attach_deactivate(deactivate,&handle));
    assert(!nd_amiibo_scan_virtual(0));assert(signaled(activate) && !signaled(deactivate));assert(!other->signaled);
    assert(!nfp_finalize());puts("NFP: 2048 real kernel-event transitions, UID rotation and stale-handle isolation PASS");return 0;
}
