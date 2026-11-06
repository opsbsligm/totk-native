/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE 1
#include "native_atmosphere.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
static uint64_t memory[64],heap[64];
static char file[4096];
static void bounds(uint64_t *b,uint64_t *n) {*b=(uintptr_t)heap;*n=sizeof heap;}
static void fixture(const char *body) {FILE *f=fopen(file,"w");assert(f);fputs(body,f);assert(!fclose(f));assert(!chmod(file,0600));}
static void enable(size_t i) {NdAtmInfo x;nd_atm_info(i,&x);assert(x.supported && !x.enabled);nd_atm_request(i,1);}
static void stop_all(void) {for(size_t i=0;i<nd_atm_count();i++) nd_atm_request(i,0);}
int main(int argc,char **argv) {
    assert(argc==2);assert(!setenv("XDG_DATA_HOME",argv[1],1));char dir[4096];
    snprintf(dir,sizeof dir,"%s/totk-native",argv[1]);assert(!mkdir(dir,0700));
    snprintf(dir,sizeof dir,"%s/totk-native/cheats",argv[1]);assert(!mkdir(dir,0700));
    snprintf(file,sizeof file,"%s/totk-native/cheats/0123456789ABCDEF.txt",argv[1]);
    const char *id="0123456789ABCDEF000000000000000000000000000000000000000000000000";
    uint64_t base=(uintptr_t)memory;nd_atm_bind(id,base,base+64,sizeof memory-64,bounds);
    fixture("[Static]\n04000000 00000040 0000002A\n[Text]\n04000000 00000000 00000001\n[Bad]\nC0000000\n");
    assert(!nd_atm_reload("totk-native"));assert(nd_atm_count()==3);NdAtmInfo info;
    nd_atm_info(1,&info);assert(!info.supported && strstr(info.note,"rebuild"));nd_atm_info(2,&info);assert(!info.supported);
    nd_atm_frame(0);assert(!memory[8]);enable(0);nd_atm_frame(0);
#ifdef __linux__
    assert(memory[8]==42);assert(nd_atm_reload("totk-native")<0);stop_all();
    fixture("[Conditional]\n14050000 00000040 0000002A\n04000000 00000044 00000063\n21000000\n04000000 00000044 0000004D\n20000000\n");assert(!nd_atm_reload("totk-native"));enable(0);nd_atm_frame(0);assert((memory[8]>>32)==99);memory[8]=41;nd_atm_frame(0);assert((memory[8]>>32)==77);stop_all();
    fixture("[Buttons]\n80000001\n04000000 00000040 00000033\n20000000\n");assert(!nd_atm_reload("totk-native"));enable(0);memory[8]=0;nd_atm_frame(0);assert(!memory[8]);nd_atm_frame(1);assert(memory[8]==51);stop_all();
    memory[9]=(uintptr_t)&heap[1];
    fixture("[Pointer]\n580F0000 00000048\n640F0000 00000000 00000055\n");assert(!nd_atm_reload("totk-native"));enable(0);nd_atm_frame(0);assert(heap[1]==85);stop_all();
    fixture("[Heap]\n04100000 00000010 00000066\n");assert(!nd_atm_reload("totk-native"));enable(0);nd_atm_frame(0);assert(heap[2]==102);stop_all();
    char dynamic[512];snprintf(dynamic,sizeof dynamic,"[Denied text]\n400F0000 %08X %08X\n640F0000 00000000 00000077\n",(unsigned)(base>>32),(unsigned)base);
    fixture(dynamic);assert(!nd_atm_reload("totk-native"));enable(0);nd_atm_frame(0);nd_atm_info(0,&info);assert(!info.enabled && !memory[0] && strstr(info.note,"Outside"));
    fixture("[Overflow]\n400F0000 FFFFFFFF FFFFFFFF\n040F0000 00000040 00000011\n");assert(!nd_atm_reload("totk-native"));enable(0);nd_atm_frame(0);nd_atm_info(0,&info);assert(!info.enabled && strstr(info.note,"overflow"));
    fixture("[Zero loop]\n30000000 00000000\n04000000 00000040 00000011\n31000000\n");assert(!nd_atm_reload("totk-native"));memory[8]=0;enable(0);nd_atm_frame(0);assert(!memory[8]);stop_all();
    fixture("[Budget]\n30000000 FFFFFFFF\n04000000 00000040 00000011\n31000000\n");assert(!nd_atm_reload("totk-native"));enable(0);nd_atm_frame(0);nd_atm_info(0,&info);assert(!info.enabled && strstr(info.note,"budget"));
#else
    nd_atm_info(0,&info);assert(!info.enabled && strstr(info.note,"Linux"));stop_all();
#endif
    fixture("[Truncated]\n580F0000\n[Bad nesting]\n21000000\n[Bad loop]\n31000000\n");assert(!nd_atm_reload("totk-native"));
    for(size_t i=0;i<3;i++) {nd_atm_info(i,&info);assert(!info.supported);}
    fixture("[Invalid token]\n04000000 00000040 NOTHEX!!\n");assert(nd_atm_reload("totk-native")<0);assert(nd_atm_count()==3);
    fixture("[Mode]\n04000000 00000040 00000033\n");assert(!chmod(file,0644));assert(nd_atm_reload("totk-native")<0);
    unlink(file);assert(!mkfifo(file,0600));alarm(2);assert(nd_atm_reload("totk-native")<0);alarm(0);unlink(file);
    assert(!symlink("missing",file));assert(nd_atm_reload("totk-native")<0);unlink(file);
    nd_atm_bind("WRONG",base,base+64,sizeof memory-64,bounds);assert(nd_atm_reload("totk-native")<0);
    return 0;
}
