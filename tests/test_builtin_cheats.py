"""Run the shipped version-specific presets against bounded actual guest-layout memory."""
from pathlib import Path
import subprocess,tempfile,unittest,sys
ROOT=Path(__file__).resolve().parents[1]
HOST=ROOT/('src/host' if (ROOT/'src/host').is_dir() else 'runtime')
class BuiltinPresets(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith('linux'),'guarded guest copies require Linux')
    def test_exact_build_presets_unaligned_stamina_and_actual_readback(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            p=Path(tmp);source=p/'test.c';exe=p/'check'
            source.write_text(r"""
#define _GNU_SOURCE 1
#include "native_atmosphere.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
static unsigned char *main_mem,*heap;static size_t main_size=0x3ae0000,heap_size=0x20000;
static void hb(uint64_t *base,uint64_t *size) {*base=(uintptr_t)heap;*size=heap_size;}
static void ptr(unsigned char *address,void *value) {uint64_t p=(uintptr_t)value;memcpy(address,&p,8);}
static void bind(const char *id,size_t data_offset) {nd_atm_bind(id,(uintptr_t)main_mem,(uintptr_t)main_mem+data_offset,main_size-data_offset,hb);}
static void enable(size_t i) {NdAtmInfo info;nd_atm_info(i,&info);assert(info.supported && info.builtin && !info.enabled);nd_atm_request(i,1);}
int main(void) {
 main_mem=calloc(1,main_size);heap=calloc(1,heap_size);assert(main_mem && heap);
 const char *botw="8e9978d50bdd20b4c8395a106c27ffde00000000000000000000000000000000";
 const char *totk="277178b7dba1b6d4949a84778d4abc58b31b34f5000000000000000000000000";
 bind(botw,0x2a6d000);assert(nd_atm_load_defaults("totk-native")<0);assert(!nd_atm_load_defaults("botw-native"));assert(nd_atm_count()==3);
 ptr(main_mem+0x2ca1a78,heap+0x100);ptr(heap+0x180,heap+0x1000);
 ptr(main_mem+0x2c9fd70,heap+0x400);ptr(heap+0x438,heap+0x2000);
 ptr(main_mem+0x2cc5fe0,heap+0x8000);ptr(heap+0x8e40,heap+0x9000);ptr(heap+0xeb08,heap+0xf000);
 for(size_t i=0;i<3;i++) enable(i);nd_atm_frame(0);
 uint64_t stamina;uint32_t rupees;memcpy(&stamina,heap+0x22ac,8);memcpy(&rupees,heap+0x14d90,4);
 assert(heap[0x1848]==0x78 && stamina==UINT64_C(0x453b8000453b8000) && rupees==999999);
 for(size_t i=0;i<3;i++) {NdAtmInfo info;nd_atm_info(i,&info);assert(info.enabled && info.frames==1 && info.writes==1 && info.verified_writes==1 && !info.mismatches);}
 assert(nd_atm_load_defaults("botw-native")<0);nd_atm_disable_all();
 // Same 8-byte prefix, wrong remaining build bytes: must not import built-ins.
 bind("8e9978d50bdd20b4c8395a106c27ffde00000000000000000000000000000001",0x2a6d000);assert(nd_atm_load_defaults("botw-native")<0 && !nd_atm_count());
 memset(main_mem,0,main_size);memset(heap,0,heap_size);bind(totk,0x3569000);assert(!nd_atm_load_defaults("totk-native"));assert(nd_atm_count()==1);
 ptr(main_mem+0x3ad99b8,heap);
 const unsigned offsets[]={0x70,0x40,0xd0,0xc0,0x198,0x38};
 for(int i=0;i<6;i++) ptr(heap+i*0x1000+offsets[i],heap+(i+1)*0x1000);
 enable(0);nd_atm_frame(0);NdAtmInfo info;nd_atm_info(0,&info);assert(info.frames==1 && !info.writes);
 nd_atm_frame(4);uint32_t velocity;memcpy(&velocity,heap+0x60f4,4);assert(velocity==0x41200000);
 nd_atm_info(0,&info);assert(info.frames==2 && info.writes==1 && info.verified_writes==1);
 nd_atm_disable_all();nd_atm_frame(4);nd_atm_info(0,&info);assert(info.frames==2 && !info.enabled);
 nd_atm_request(0,1);nd_atm_info(0,&info);assert(!info.frames && !info.writes && !info.verified_writes);
 free(main_mem);free(heap);return 0;
}
""")
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pthread','-I',str(HOST),str(source),str(HOST/'native_atmosphere.c'),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True,timeout=15)
