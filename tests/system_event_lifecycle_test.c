/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE 1
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "../src/host/threads.c"
static int creates;
// Creating guest CPU threads is outside this kernel-event-only test.
uint64_t guest_tls_alloc(void) {abort();}
Cpu *guest_cpu_new(uint64_t top,uint64_t tls) {(void)top;(void)tls;abort();}
void guest_cpu_set(Cpu *cpu) {(void)cpu;abort();}
void guest_call(Cpu *cpu,uint64_t address) {(void)cpu;(void)address;abort();}
_Noreturn void runtime_fail(const char *text) {fprintf(stderr,"%s\n",text);abort();}
uint64_t runtime_now_ns(void) {struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (uint64_t)t.tv_sec*1000000000+t.tv_nsec;}
void *runtime_symbol(const char *text) {return (void *)(uintptr_t)(strstr(text,"CreateSystemEvent")?1:2);}
uint64_t guest_call_args(uint64_t fn,int n,const uint64_t *args) {
    assert(t_self && n>=1);uint32_t *ev=(void *)(uintptr_t)args[0];
    if(fn==1) {uint64_t regs[32]={0};assert(svc_thread(0x45,regs));assert(!regs[0]);ev[0]=(uint32_t)regs[1];ev[1]=(uint32_t)regs[2];creates++;return 0;}
    assert(fn==2);return ev[0];
}
static void close_handle(uint32_t h) {uint64_t regs[32]={h};assert(svc_thread(0x16,regs));assert(!regs[0]);}
int main(void) {
    thr_t current={0};current.cur_core=-1;t_self=&current;uint32_t ev[2]={0};
    hle_bind_system_event(ev,0);assert(creates==1);hle_bind_system_event(ev,0);assert(creates==1);
    assert(hle_try_signal_system_event(ev));assert(h_peek(ev[0],O_EVENT_W));
    for(int i=0;i<1024;i++) {
        if(i) hle_bind_system_event(ev,0);
        uint32_t old=ev[0];close_handle(ev[0]);close_handle(ev[1]);
        uint64_t regs[32]={0};assert(svc_thread(0x45,regs));assert((uint32_t)regs[1]==old);
        event_t *unrelated=h_peek((uint32_t)regs[1],O_EVENT_W);assert(unrelated && !unrelated->signaled);
        t_self=NULL;assert(!hle_try_signal_system_event(ev));hle_signal_system_event(ev);assert(!unrelated->signaled);
        int before=creates;t_self=&current;hle_bind_system_event(ev,0);assert(creates==before+1);
        assert(hle_try_signal_system_event(ev));assert(h_peek(ev[0],O_EVENT_W)!=unrelated);assert(!unrelated->signaled);
        close_handle((uint32_t)regs[1]);close_handle((uint32_t)regs[2]);
        close_handle(ev[0]);close_handle(ev[1]);
    }
    assert(!hle_try_signal_system_event(ev));assert(g_nse==1);
    puts("SystemEvent: real Create/Close SVC, stale-handle isolation, 1024 rebinds and host no-revival PASS");return 0;
}
