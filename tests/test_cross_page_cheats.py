"""Cross-page short-write prevention in the real guarded VM, using real protected pages."""
from pathlib import Path
import subprocess,tempfile,unittest,sys
ROOT=Path(__file__).resolve().parents[1]
HOST=ROOT/('src/host' if (ROOT/'src/host').is_dir() else 'runtime')
class PageIntegrity(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith('linux'),'Linux kernel guarded copy backend')
    def test_cross_page_write_is_rejected_before_partial_change(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            p=Path(tmp);source=p/'test.c';exe=p/'check'
            source.write_text(r"""
#define _GNU_SOURCE 1
#include "native_atmosphere.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
static char file[4096];
static void code(unsigned offset) {FILE *f=fopen(file,"w");assert(f);fprintf(f,"[Write]\n08000000 %08X 01020304 05060708\n",offset);assert(!fclose(f));assert(!chmod(file,0600));assert(!nd_atm_reload("totk-native"));nd_atm_request(0,1);}
int main(int argc,char **argv) {
 assert(argc==2);assert(!setenv("XDG_DATA_HOME",argv[1],1));char path[4096];
 snprintf(path,sizeof path,"%s/totk-native",argv[1]);assert(!mkdir(path,0700));
 snprintf(path,sizeof path,"%s/totk-native/cheats",argv[1]);assert(!mkdir(path,0700));
 snprintf(file,sizeof file,"%s/totk-native/cheats/0123456789ABCDEF.txt",argv[1]);
 long page=sysconf(_SC_PAGESIZE);assert(page>16);unsigned char *p=mmap(NULL,(size_t)page*2,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);assert(p!=MAP_FAILED);
 memset(p,0x11,(size_t)page*2);assert(!mprotect(p+page,(size_t)page,PROT_READ));
 nd_atm_bind("0123456789ABCDEF000000000000000000000000000000000000000000000000",(uintptr_t)p,(uintptr_t)p,(uint64_t)page*2,NULL);
 code((unsigned)page-4);nd_atm_frame(0);NdAtmInfo info;nd_atm_info(0,&info);
 assert(!info.enabled && !info.writes && !info.verified_writes && strstr(info.note,"Cross-page"));
 for(long i=0;i<page*2;i++) {assert(p[i]==0x11);}
 code((unsigned)page-12);nd_atm_frame(0);uint64_t value;memcpy(&value,p+page-12,8);assert(value==UINT64_C(0x0102030405060708));
 nd_atm_info(0,&info);assert(info.enabled && info.writes==1 && info.verified_writes==1 && !info.mismatches);
 nd_atm_disable_all();assert(!munmap(p,(size_t)page*2));return 0;
}
""")
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pthread','-I',str(HOST),str(source),str(HOST/'native_atmosphere.c'),'-o',str(exe)],check=True)
            subprocess.run([str(exe),str(p)],check=True,timeout=15)
