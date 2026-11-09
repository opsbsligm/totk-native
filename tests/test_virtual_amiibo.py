"""No dumps or keys: exercise virtual figures through the production NFP reader."""
from pathlib import Path
import subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
HOST=ROOT/('src/host' if (ROOT/'src/host').is_dir() else 'runtime')
class VirtualAmiibo(unittest.TestCase):
    def test_catalog_uid_rotation_ordered_rescan_and_game_read_receipts(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            p=Path(tmp);s=p/'test.c';exe=p/'check'
            s.write_text(r"""
#include "native_amiibo.h"
#include <assert.h>
#include <string.h>
static int on,off;
static void notify(int active) {NdAmiiboSnapshot s;nd_amiibo_snapshot(&s);if(active) {assert(s.state==2);on++;}else {assert(s.state!=2 && s.state!=4);off++;}}
int main(void) {
 nd_amiibo_set_notify(notify);assert(nd_amiibo_virtual_count()==32);
 assert(!strcmp(nd_amiibo_virtual_name(0,0),"Zelda & Loftwing"));assert(*nd_amiibo_virtual_name(0,1));
 assert(!*nd_amiibo_virtual_name(9999,1));assert(!nd_amiibo_virtual_supported(9999));assert(nd_amiibo_scan_virtual(9999)<0);
 int supported=0;for(size_t i=0;i<nd_amiibo_virtual_count();i++) {if(nd_amiibo_virtual_supported(i)) supported++;else assert(nd_amiibo_scan_virtual(i)<0);}assert(supported==31);
 nd_amiibo_initialize(1);assert(!nd_amiibo_start());unsigned char previous[7]={0},tag[0x58],model[0x40];
 for(int i=0;i<2048;i++) {
  assert(!nd_amiibo_scan_virtual(0));NdAmiiboSnapshot s;nd_amiibo_snapshot(&s);
  assert(s.virtual_index==0 && s.loaded && s.scans==(unsigned)i+1 && !s.current_identity_read);
  if(i) {assert(s.state==3 && off==i && on==i);assert(nd_amiibo_mount()==ND_NFP_NOT_FOUND);assert(!nd_amiibo_start());}
  assert(on==i+1);assert(!nd_amiibo_tag_info(tag,sizeof tag));assert(tag[0]==4 && tag[0xa]==7 && tag[0x20]==1 && tag[0x24]==2);
  assert(memcmp(previous,tag,7));memcpy(previous,tag,7);
  assert(!nd_amiibo_mount());nd_amiibo_snapshot(&s);assert(!s.current_identity_read);
  assert(nd_amiibo_model_info(model,sizeof model-1)==ND_NFP_NOT_FOUND);
  nd_amiibo_snapshot(&s);assert(!s.current_identity_read);
  assert(!nd_amiibo_model_info(model,sizeof model));
  // Public Zelda & Loftwing ID 0101030004140902 -> SDK model info, exact endian layout.
  assert(!memcmp(model,"\x01\x01\x03\x09\x14\x04\x00",7));
  assert(!nd_amiibo_start());nd_amiibo_snapshot(&s);assert(s.state==4 && on==i+1);
  assert(s.current_identity_read && s.mounts==(unsigned)i+1 && s.model_reads==(unsigned)i+1 && s.tag_reads==(unsigned)i+1);
  // A rejected replacement must not clear a valid current-identity receipt.
  assert(nd_amiibo_scan_virtual(9999)<0);nd_amiibo_snapshot(&s);assert(s.current_identity_read);
 }
 // Reader stop/restart and unmount do not erase the last successful read.
 assert(!nd_amiibo_unmount());assert(!nd_amiibo_stop());NdAmiiboSnapshot s;nd_amiibo_snapshot(&s);
 assert(s.current_identity_read && s.loaded && s.state==3 && off==2048);
 assert(!nd_amiibo_start());nd_amiibo_snapshot(&s);assert(s.current_identity_read && on==2049);
 nd_amiibo_remove();assert(off==2049);nd_amiibo_snapshot(&s);assert(!s.loaded && s.virtual_index==-1 && !s.current_identity_read);
 // Previous cumulative reads must not be mistaken for the next explicit scan.
 assert(!nd_amiibo_scan_virtual(0));nd_amiibo_snapshot(&s);assert(s.loaded && s.model_reads==2048 && !s.current_identity_read);
 nd_amiibo_remove();
 assert(nd_amiibo_model_info(model,sizeof model)==ND_NFP_NOT_FOUND);return 0;
}
""")
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pthread','-I',str(HOST),str(s),str(HOST/'native_amiibo.c'),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True,timeout=15)
