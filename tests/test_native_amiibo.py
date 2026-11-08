"""Exercise the real tag reader/state machine; no real Amiibo dumps are included."""
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
HOST=ROOT/('src/host' if (ROOT/'src/host').is_dir() else 'runtime')
class Amiibo(unittest.TestCase):
    def test_validation_events_mount_remove_and_nonblocking_inputs(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root=Path(tmp);source=root/'test.c';binary=root/'test'
            source.write_text(r'''
#define _POSIX_C_SOURCE 200809L
#include "native_amiibo.h"
#include <assert.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
static unsigned char data[540];static int activated,removed;
static void notify(int on) {NdAmiiboSnapshot s;nd_amiibo_snapshot(&s);if(on) activated++;else removed++;}
static void write_tag(const char *path,int size) {FILE *f=fopen(path,"wb");assert(f);assert(fwrite(data,1,size,f)==(size_t)size);assert(!fclose(f));}
int main(int argc,char **argv) {
    assert(argc==2);const char *path=argv[1];unsigned char out[0x100];NdAmiiboSnapshot s;
    nd_amiibo_set_notify(notify);assert(nd_amiibo_start()==ND_NFP_NOT_FOUND);
    nd_amiibo_initialize(1);assert(!nd_amiibo_start());nd_amiibo_snapshot(&s);assert(s.state==1);
    data[0]=4;data[1]=1;data[2]=2;data[3]=0x88^4^1^2;data[4]=3;data[5]=4;data[6]=5;data[7]=6;data[8]=3^4^5^6;
    memcpy(data+12,"\xf1\x10\xff\xee",4);for(int i=0;i<8;i++) data[0x54+i]=(unsigned char)(0x10+i);
    write_tag(path,539);assert(nd_amiibo_load(path)<0);assert(!activated);
    data[8]^=1;write_tag(path,540);assert(nd_amiibo_load(path)<0);data[8]^=1;
    write_tag(path,540);assert(!nd_amiibo_load(path));assert(activated==1);
    nd_amiibo_snapshot(&s);assert(!s.current_identity_read);
    assert(!nd_amiibo_tag_info(out,sizeof out));assert(out[0]==4 && out[3]==3 && out[0xa]==7 && out[0x20]==1 && out[0x24]==2);
    assert(nd_amiibo_model_info(out,sizeof out)==ND_NFP_NOT_FOUND);
    assert(!nd_amiibo_mount());assert(!nd_amiibo_start());nd_amiibo_snapshot(&s);assert(s.state==4 && activated==1);assert(!nd_amiibo_model_info(out,sizeof out));assert(out[0]==0x10 && out[3]==0x16 && out[4]==0x15 && out[5]==0x14 && out[6]==0x13);
    nd_amiibo_snapshot(&s);assert(s.current_identity_read);
    assert(nd_amiibo_model_info(out,0x3f)==ND_NFP_NOT_FOUND);assert(nd_amiibo_load(path)<0);
    nd_amiibo_snapshot(&s);assert(s.current_identity_read);
    assert(!nd_amiibo_unmount());nd_amiibo_remove();assert(removed==1);assert(nd_amiibo_tag_info(out,sizeof out)==ND_NFP_NOT_FOUND);
    nd_amiibo_snapshot(&s);assert(!s.loaded && s.state==3 && !s.current_identity_read);assert(!nd_amiibo_start());assert(!nd_amiibo_load(path));assert(activated==2);
    nd_amiibo_snapshot(&s);assert(s.model_reads==1 && !s.current_identity_read);
    nd_amiibo_stop();assert(removed==2);nd_amiibo_initialize(0);assert(nd_amiibo_start()==ND_NFP_NOT_FOUND);
    unlink(path);assert(!symlink("missing",path));assert(nd_amiibo_load(path)<0);unlink(path);
    assert(!mkfifo(path,0600));alarm(2);assert(nd_amiibo_load(path)<0);alarm(0);unlink(path);
    return 0;
}
''')
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pthread','-I',str(HOST),str(source),str(HOST/'native_amiibo.c'),'-o',str(binary)],check=True)
            subprocess.run([str(binary),str(root/'synthetic.bin')],check=True,timeout=10)
