"""Verify actual control settings reads cannot block or accept malformed values."""
from pathlib import Path
import subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
class ControlPreferences(unittest.TestCase):
 def test_regular_private_bounded_and_nonblocking(self):
  with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
   p=Path(temp);c=p/'main.c';exe=p/'check'
   c.write_text(r'''
#define _DARWIN_C_SOURCE 1
#define _GNU_SOURCE 1
#define _POSIX_C_SOURCE 200809L
#include "control_preferences.h"
#include <assert.h>
#include <stdio.h>
static void fixture(const char *p,const char *s) {FILE *f=fopen(p,"w");assert(f);fputs(s,f);assert(!fclose(f));assert(!chmod(p,0600));}
int main(int argc,char **argv) {
 assert(argc==2);const char *p=argv[1];int a=7,f=120,g=1;
 fixture(p,"anchor=3\nfps=60\ngyro=0\n");assert(nd_control_preferences_read(p,&a,&f,&g));assert(a==3&&f==60&&g==0);
 const char *bad[]={"anchor=1\nfps=-2\ngyro=0\n", "anchor=1\nfps=-11\ngyro=0\n", "anchor=1\nfps=-01\ngyro=0\n", "anchor=1\nfps=60\ngyro=-1\n", "anchor=99999999999999999999999999999\nfps=60\ngyro=0\n", "anchor=-1\nfps=60\ngyro=0\n", "anchor=8\nfps=60\ngyro=0\n", "anchor=1\nfps=0\ngyro=0\n", "anchor=1\nfps=60\ngyro=2\n", "anchor=1\nfps=60\ngyro=0\njunk", "anchor=1fps=60\ngyro=0"};
 for(unsigned i=0;i<sizeof bad/sizeof *bad;i++){fixture(p,bad[i]);assert(!nd_control_preferences_read(p,&a,&f,&g));assert(a==3&&f==60&&g==0);}
 fixture(p,"anchor=1\nfps=45\ngyro=1");assert(nd_control_preferences_read(p,&a,&f,&g));assert(a==1&&f==45&&g==1);
 assert(!chmod(p,0644));assert(!nd_control_preferences_read(p,&a,&f,&g));
 assert(!unlink(p));assert(!mkfifo(p,0600));assert(!nd_control_preferences_read(p,&a,&f,&g)); // no writer, must not hang
 assert(!unlink(p));assert(!symlink("missing-target",p));assert(!nd_control_preferences_read(p,&a,&f,&g));
 assert(!unlink(p));assert(!mkdir(p,0700));assert(!nd_control_preferences_read(p,&a,&f,&g));assert(!rmdir(p));
 fixture(p,"anchor=1\nfps=60\ngyro=0\n");FILE *z=fopen(p,"a");assert(z);for(int i=0;i<512;i++)fputc('0',z);fclose(z);assert(!nd_control_preferences_read(p,&a,&f,&g));
 assert(!unlink(p));
 int u=-1,sharp=-1;
 fixture(p,"anchor=4\nfps=-1\ngyro=1\nupscaler=1\nsharpness=75\n");
 assert(nd_control_preferences_read_extended(p,&a,&f,&g,&u,&sharp));assert(a==4 && f==-1 && g==1 && u==1 && sharp==75);
 fixture(p,"anchor=4\nfps=60\ngyro=1\nupscaler=2\nsharpness=50\n");assert(!nd_control_preferences_read_extended(p,&a,&f,&g,&u,&sharp));assert(u==1 && sharp==75);
 fixture(p,"anchor=4\nfps=60\ngyro=1\nupscaler=1\nsharpness=101\n");assert(!nd_control_preferences_read_extended(p,&a,&f,&g,&u,&sharp));
 fixture(p,"anchor=4\nfps=60\ngyro=1\nupscaler=1\n");assert(!nd_control_preferences_read_extended(p,&a,&f,&g,&u,&sharp));
 fixture(p,"anchor=4\nfps=60\ngyro=1\n");assert(nd_control_preferences_read_extended(p,&a,&f,&g,&u,&sharp));assert(!u && sharp==50);
 assert(!unlink(p));return 0;
}
''')
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT/'src/host'),str(c),'-o',str(exe)],check=True)
   subprocess.run([str(exe),str(p/'control.ini')],check=True,timeout=2)
 def test_first_save_preserves_preferences_with_inherited_fps(self):
  # The UI starts with FPS=-1 until the player selects an explicit cap. Saving
  # only gyro or dock must round-trip this existing launcher-inheritance state.
  with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
   p=Path(temp);c=p/'inherit.c';exe=p/'inherit'
   c.write_text(r'''
#define _DARWIN_C_SOURCE 1
#define _GNU_SOURCE 1
#define _POSIX_C_SOURCE 200809L
#include "control_preferences.h"
#include <stdio.h>
int main(int argc,char **argv) {
 if(argc!=2) return 1;
 for(int dock=0;dock<8;dock++) for(int motion=0;motion<2;motion++) {
  FILE *out=fopen(argv[1],"w");if(!out) return 2;
  if(fprintf(out,"anchor=%d\nfps=%d\ngyro=%d\n",dock,-1,motion)<0 || fclose(out) || chmod(argv[1],0600)) return 3;
  int anchor=99,fps=99,gyro=99;
  if(!nd_control_preferences_read(argv[1],&anchor,&fps,&gyro) || anchor!=dock || fps!=-1 || gyro!=motion) {
   fputs("First save lost dock/gyro while FPS inherited the launcher\n",stderr);return 4;
  }
 }
 return unlink(argv[1])?5:0;
}
''')
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT/'src/host'),str(c),'-o',str(exe)],check=True)
   subprocess.run([str(exe),str(p/'control.ini')],check=True,timeout=2)
