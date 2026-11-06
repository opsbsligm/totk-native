"""Production touch gesture ownership, geometry and cancellation without a window server."""
from pathlib import Path
import subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
HOST=ROOT/('src/host' if (ROOT/'src/host').is_dir() else 'runtime')
class Touch(unittest.TestCase):
    def test_physical_touch_ownership_cancel_multitouch_and_coordinates(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            p=Path(tmp);s=p/'test.c';exe=p/'check'
            s.write_text(r"""
#include "native_touch.h"
#include <assert.h>
int main(void) {
 NdTouch s={0};NdTouchResult r;
 r=nd_touch_route(&s,ND_TOUCH_DOWN,1,1,.5f,.5f,1280,800,0,0);assert(!r.consumed && !s.active);
 r=nd_touch_route(&s,ND_TOUCH_DOWN,1,1,.5f,.5f,1280,800,1,0);assert(r.consumed && r.emit && r.down && r.x==640 && r.y==400);
 r=nd_touch_route(&s,ND_TOUCH_DOWN,1,2,.1f,.1f,1280,800,1,1);assert(r.consumed && !r.emit && s.finger==1);
 r=nd_touch_route(&s,ND_TOUCH_UP,2,1,.5f,.5f,1280,800,1,1);assert(!r.emit && s.active);
 r=nd_touch_route(&s,ND_TOUCH_MOVE,1,1,1.2f,-.1f,1280,800,0,0);assert(r.emit && r.x==1280 && r.y==0);
 r=nd_touch_route(&s,ND_TOUCH_UP,1,1,1.2f,-.1f,1280,800,0,0);assert(r.emit && !r.down && !s.active);
 r=nd_touch_route(&s,ND_TOUCH_UP,1,2,0,0,1280,800,1,0);assert(!r.emit && !r.consumed);
 r=nd_touch_route(&s,ND_TOUCH_DOWN,1,1,NAN,0,1280,800,1,1);assert(!r.emit);
 r=nd_touch_route(&s,ND_TOUCH_DOWN,1,1,INFINITY,0,1280,800,1,1);assert(!r.emit);
 r=nd_touch_route(&s,ND_TOUCH_DOWN,1,1,0,0,0,0,1,1);assert(!r.emit);
 r=nd_touch_route(&s,ND_TOUCH_DOWN,1,1,0,0,1280,800,0,1);assert(r.emit && s.active);
 r=nd_touch_route(&s,ND_TOUCH_CANCEL,1,1,0,0,1280,800,0,1);assert(r.emit && r.cancel && !s.active);
 r=nd_touch_route(&s,ND_TOUCH_DOWN,1,1,1,1,1920,1080,1,0);assert(r.x==1920 && r.y==1080);
 r=nd_touch_route(&s,ND_TOUCH_MOVE,1,1,NAN,0,1920,1080,1,0);assert(r.cancel && !s.active);
 r=nd_touch_route(&s,ND_TOUCH_DOWN,1,1,.1f,.1f,1280,800,1,0);assert(r.emit);nd_touch_reset(&s);assert(!s.active);
 return 0;
}
""")
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(HOST),str(s),'-lm','-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True,timeout=10)
