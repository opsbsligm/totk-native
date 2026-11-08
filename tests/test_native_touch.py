"""Production touch gesture ownership, geometry and cancellation without a window server."""
from pathlib import Path
import subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
HOST=ROOT/('src/host' if (ROOT/'src/host').is_dir() else 'runtime')
class Touch(unittest.TestCase):
    def test_native_touch_and_mouse_share_one_ui_pointer(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            p=Path(tmp);s=p/'mixed.c';exe=p/'mixed'
            s.write_text(r"""
#include "native_touch.h"
#include <assert.h>
int main(void) {
 NdPointer s={0};NdTouchResult r;
 r=nd_pointer_touch(&s,ND_TOUCH_DOWN,1,11,.5f,.5f,1280,720,1,0);assert(r.emit && r.down);
 r=nd_pointer_mouse(&s,ND_TOUCH_DOWN,7,640,360,1280,720,1,0);
 assert(r.consumed && !r.emit && !s.mouse.ui.active && s.touch.active);
 r=nd_pointer_mouse(&s,ND_TOUCH_MOVE,7,60,60,1280,720,0,0);assert(r.consumed && !r.emit);
 assert(!nd_pointer_remove_mouse(&s,7) && nd_pointer_active(&s));
 r=nd_pointer_touch(&s,ND_TOUCH_MOVE,1,11,.1f,.1f,1280,720,0,0);assert(r.emit && !r.cancel);
 r=nd_pointer_touch(&s,ND_TOUCH_UP,1,11,.1f,.1f,1280,720,0,0);assert(r.emit && !nd_pointer_active(&s));
 r=nd_pointer_mouse(&s,ND_TOUCH_DOWN,7,640,360,1280,720,1,0);assert(r.emit && r.down);
 r=nd_pointer_touch(&s,ND_TOUCH_DOWN,1,11,.5f,.5f,1280,720,1,0);
 assert(r.consumed && !r.emit && !s.touch.active && s.mouse.ui.active);
 r=nd_pointer_touch(&s,ND_TOUCH_CANCEL,1,11,0,0,1280,720,0,0);assert(!r.emit && s.mouse.ui.active);
 assert(!nd_pointer_remove_mouse(&s,8) && nd_pointer_active(&s));
 r=nd_pointer_mouse(&s,ND_TOUCH_MOVE,7,60,60,1280,720,0,0);assert(r.emit && !r.cancel);
 assert(nd_pointer_remove_mouse(&s,7) && !nd_pointer_active(&s));
 r=nd_pointer_touch(&s,ND_TOUCH_DOWN,1,12,.5f,.5f,1280,720,1,0);assert(r.emit);
 nd_pointer_reset(&s);assert(!nd_pointer_active(&s));
 // A world press released during touch ownership must not stay latched.
 r=nd_pointer_mouse(&s,ND_TOUCH_DOWN,7,60,60,1280,720,0,0);assert(!r.consumed && s.mouse.outside);
 r=nd_pointer_touch(&s,ND_TOUCH_DOWN,1,13,.5f,.5f,1280,720,1,0);assert(r.emit);
 r=nd_pointer_mouse(&s,ND_TOUCH_UP,7,60,60,1280,720,0,0);assert(!r.emit && !s.mouse.outside);
 r=nd_pointer_touch(&s,ND_TOUCH_UP,1,13,.5f,.5f,1280,720,1,0);assert(r.emit);
 r=nd_pointer_mouse(&s,ND_TOUCH_DOWN,7,640,360,1280,720,1,0);assert(r.emit && s.mouse.ui.active);
 return 0;
}
""")
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(HOST),str(s),'-lm','-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True,timeout=10)

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

    def test_mouse_fallback_keeps_badge_gesture_and_world_origin(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            p=Path(tmp);s=p/'mouse.c';exe=p/'mouse'
            s.write_text(r"""
#include "native_touch.h"
#include <assert.h>
int main(void) {
 NdMouse s={0};NdTouchResult r;
 r=nd_mouse_route(&s,ND_TOUCH_DOWN,7,1240,680,1280,720,1,0);
 assert(r.consumed && r.emit && r.down && s.ui.active);
 r=nd_mouse_route(&s,ND_TOUCH_MOVE,7,60,60,1280,720,0,0);
 assert(r.consumed && r.emit && r.x==60 && r.y==60 && s.ui.active);
 r=nd_mouse_route(&s,ND_TOUCH_UP,8,60,60,1280,720,0,0);
 assert(r.consumed && !r.emit && s.ui.active);
 r=nd_mouse_route(&s,ND_TOUCH_UP,7,60,60,1280,720,0,0);
 assert(r.consumed && r.emit && !r.down && !s.ui.active);
 // Starting outside cannot steal the game's drag or release at the badge.
 r=nd_mouse_route(&s,ND_TOUCH_DOWN,7,60,60,1280,720,0,0);
 assert(!r.consumed && !r.emit && s.outside);
 r=nd_mouse_route(&s,ND_TOUCH_MOVE,7,1240,680,1280,720,1,0);
 assert(!r.consumed && !r.emit && !s.ui.active);
 r=nd_mouse_route(&s,ND_TOUCH_UP,7,1240,680,1280,720,1,0);
 assert(!r.consumed && !r.emit && !s.outside);
 r=nd_mouse_route(&s,ND_TOUCH_MOVE,7,1240,680,1280,720,1,0);
 assert(r.consumed && r.emit && !s.ui.active); // ordinary hover
 r=nd_mouse_route(&s,ND_TOUCH_DOWN,7,1240,680,1280,720,1,0);assert(s.ui.active);
 r=nd_mouse_route(&s,ND_TOUCH_MOVE,7,NAN,0,1280,720,0,0);
 assert(r.cancel && !s.ui.active);
 r=nd_mouse_route(&s,ND_TOUCH_DOWN,7,1240,680,1280,720,1,0);assert(s.ui.active);
 r=nd_mouse_route(&s,ND_TOUCH_CANCEL,7,0,0,1280,720,0,0);
 assert(r.emit && r.cancel && !s.ui.active);
 r=nd_mouse_route(&s,ND_TOUCH_DOWN,7,1240,680,1280,720,1,0);assert(s.ui.active);
 nd_mouse_reset(&s);assert(!s.ui.active && !s.outside);
 r=nd_mouse_route(&s,ND_TOUCH_DOWN,7,0,0,0,720,1,0);assert(!r.emit);
 nd_mouse_reset(&s);
 r=nd_mouse_route(&s,ND_TOUCH_DOWN,7,50,50,1280,720,0,1);assert(r.emit && s.ui.active);
 r=nd_mouse_route(&s,ND_TOUCH_UP,7,-20,900,1280,720,0,1);
 assert(r.consumed && r.emit && r.x==0 && r.y==720 && !s.ui.active);
 // Another device disappearing cannot cancel an active UI drag or world press.
 r=nd_mouse_route(&s,ND_TOUCH_DOWN,7,1240,680,1280,720,1,0);assert(s.ui.active);
 assert(!nd_mouse_remove(&s,8) && s.ui.active && s.ui.device==7);
 r=nd_mouse_route(&s,ND_TOUCH_MOVE,7,60,60,1280,720,0,0);
 assert(r.consumed && r.emit && s.ui.active);
 assert(nd_mouse_remove(&s,7) && !s.ui.active && !s.outside);
 assert(!nd_mouse_remove(&s,7));
 r=nd_mouse_route(&s,ND_TOUCH_DOWN,7,60,60,1280,720,0,0);assert(s.outside);
 assert(!nd_mouse_remove(&s,8) && s.outside && s.outside_device==7);
 assert(!nd_mouse_remove(&s,7) && !s.outside);
 r=nd_mouse_route(&s,ND_TOUCH_DOWN,8,1240,680,1280,720,1,0);
 assert(r.consumed && r.emit && s.ui.active && s.ui.device==8);
 r=nd_mouse_route(&s,ND_TOUCH_UP,8,60,60,1280,720,0,0);
 assert(r.consumed && r.emit && !s.ui.active);
 return 0;
}
""")
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(HOST),str(s),'-lm','-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True,timeout=10)
