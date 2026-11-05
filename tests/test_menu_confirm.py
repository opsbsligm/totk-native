"""Run production menu policy against bounded synthetic guest objects."""
from pathlib import Path
import subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
class MenuConfirm(unittest.TestCase):
 def test_fixed_profile_visibility_and_hold_transitions(self):
  with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
   p=Path(temp);c=p/'main.c';exe=p/'check'
   c.write_text(r'''
#include "menu_confirm.h"
#include "menu_profile.h"
#include <assert.h>
#include <string.h>
static unsigned char mem[0x3000];
static uint64_t mgr=0x1000000000ull,arr=0x1000000100ull,obj=0x1000001000ull;
static int bad,pin_bad;
static bool rd(void *u,uint64_t p,void *out,size_t n) {
 (void)u;if(bad)return false;
 if(p==0x803acf960ull&&n==8){memcpy(out,&mgr,8);return true;}
 for(unsigned i=0;i<sizeof nd_menu_classes/sizeof *nd_menu_classes;i++) {
  const NdMenuClass *cl=&nd_menu_classes[i];
  if(p==cl->name_address&&n==strlen(cl->name)+1) {memcpy(out,cl->name,n);if(pin_bad)((char*)out)[0]='?';return true;}
  if(p==cl->descriptor+0x10&&n==8) {memcpy(out,&cl->getter,8);return true;}
 }
 if(p>=mgr&&p<mgr+sizeof mem&&n<=mgr+sizeof mem-p){memcpy(out,mem+(p-mgr),n);return true;}
 return false;
}
static void put(unsigned off,const void *v,size_t n){memcpy(mem+off,v,n);}
int main(void) {
 NdMenuConfirm s={0};
 assert(nd_menu_confirm(&s,false,1,1,2)==1);
 assert(nd_menu_confirm(&s,true,1,1,2)==0); // entering while interact held
 assert(nd_menu_confirm(&s,true,0,1,2)==0);
 assert(nd_menu_confirm(&s,true,2,1,2)==1); // physical A confirms
 assert(nd_menu_confirm(&s,true,1,1,2)==2); // physical B cancels
 assert(nd_menu_confirm(&s,false,1,1,2)==0); // exit cannot re-use held key
 assert(nd_menu_confirm(&s,false,0,1,2)==0);
 assert(nd_menu_confirm(&s,false,2,1,2)==2); // original gameplay sprint
 unsigned count=2;put(8,&count,4);put(0x10,&arr,8);put(0x100,&obj,8);put(0x1020,&mgr,8);
 uint64_t vt=0x80372f150ull;put(0x1000,&vt,8);mem[0x116d]=0;mem[0x116e]=2;
 assert(nd_totk_menu_context(rd,0)); // independently verified UIPouchScreen vtable
 mem[0x116e]=1;assert(!nd_totk_menu_context(rd,0));
 mem[0x116e]=2;mem[0x116d]=255;assert(!nd_totk_menu_context(rd,0)); // negative priority is closing
 mem[0x116d]=0;pin_bad=1;assert(!nd_totk_menu_context(rd,0));pin_bad=0;
 vt=0x803000008ull;put(0x1000,&vt,8);assert(!nd_totk_menu_context(rd,0)); // HUD/unrecognized type
 vt=0x803733a28ull;put(0x1000,&vt,8);assert(nd_totk_menu_context(rd,0)); // title
 count=513;put(8,&count,4);assert(!nd_totk_menu_context(rd,0));count=2;put(8,&count,4);
 uint64_t invalid=~0ull;put(0x100,&invalid,8);assert(!nd_totk_menu_context(rd,0));
 put(0x100,&obj,8);put(0x1020,&invalid,8);assert(!nd_totk_menu_context(rd,0)); // wrong parent
 bad=1;assert(!nd_totk_menu_context(rd,0));assert(!nd_totk_menu_context(0,0));
 return 0;
}
''')
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT/'src/host'),str(c),str(ROOT/'src/host/menu_confirm.c'),'-o',str(exe)],check=True)
   subprocess.run([str(exe)],check=True)
