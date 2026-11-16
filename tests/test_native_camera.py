"""Production C and AOT camera contracts using original synthetic code only."""
from collections import Counter
import array
import contextlib
import hashlib
import importlib
import io
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools/lifter'))
import native_camera
from gen import Module
from lifter import Lifter
from nso import Nso
from test_totk_static_mods import synthetic_module


class NativeCamera(unittest.TestCase):
    def compile_run(self, program, *, marker=True, extra=()):
        with tempfile.TemporaryDirectory(prefix='native-camera-', dir=Path.cwd()) as directory:
            path = Path(directory)
            source = path/'check.c'
            source.write_text(('#include <stdint.h>\nconst uint32_t nd_totk_camera_profile_v143=1;\n'
                               if marker else '') + program)
            executable = path/'check'
            result = subprocess.run(['clang', '-std=gnu11', '-O2', '-I'+str(ROOT/'src/runtime'),
                '-I'+str(ROOT/'src/host'), str(source), str(ROOT/'src/host/native_camera.c'),
                '-lm', '-pthread', *extra, '-o', str(executable)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            subprocess.run([str(executable)], check=True, timeout=10)

    def test_runtime_default_is_bit_exact_and_unsafe_angles_preserve_all_bytes(self):
        self.compile_run(r'''
#include "native_camera.h"
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <string.h>
int main(void) {
    uint32_t bits[]={0,0x80000000,0x3f800000,0x7fc12345,0x7f800000};
    assert(nd_totk_camera_available() && nd_totk_camera_percent()==100);
    for(unsigned i=0;i<sizeof bits/sizeof *bits;i++) {
        uint32_t reg[4]={bits[i],0x12345678,0x98765432,0xffffffff}, original[4];
        memcpy(original,reg,sizeof reg);nd_totk_camera_apply(reg);
        assert(!memcmp(reg,original,sizeof reg));
    }
    assert(!nd_totk_camera_configure(69) && !nd_totk_camera_configure(151));
    assert(nd_totk_camera_percent()==100 && nd_totk_camera_applied_percent()==0);
    for(int value=70;value<=150;value+=80) {
        assert(nd_totk_camera_configure(value));
        uint32_t reg[4]={0,0x12345678,0x98765432,0xffffffff};float angle=0.8f;
        memcpy(reg,&angle,4);nd_totk_camera_apply(reg);float actual;memcpy(&actual,reg,4);
        assert(fabsf(actual-(0.8f*value/100.f))<0.000001f);
        assert(reg[1]==0x12345678 && reg[2]==0x98765432 && reg[3]==0xffffffff);
        assert(nd_totk_camera_applied_percent()==value);
    }
    float invalid[]={-1.f,0.f,INFINITY,NAN,3.2f};
    for(unsigned i=0;i<sizeof invalid/sizeof *invalid;i++) {
        float original=invalid[i];nd_totk_camera_apply(&invalid[i]);
        assert(!memcmp(&original,&invalid[i],4));
    }
    nd_totk_camera_apply(0);assert(nd_totk_camera_configure(100));return 0;
}
''')

    def test_runtime_archive_without_emitted_profile_cannot_enable_fov(self):
        self.compile_run(r'''
#include "native_camera.h"
#include <assert.h>
int main(void) {
    assert(!nd_totk_camera_available());assert(!nd_totk_camera_configure(70));
    assert(!nd_totk_camera_configure(150));assert(nd_totk_camera_configure(100));
    assert(nd_totk_camera_percent()==100);return 0;
}
''', marker=False)

    def test_render_and_settings_threads_share_only_valid_atomic_values(self):
        self.compile_run(r'''
#include "native_camera.h"
#include <assert.h>
#include <math.h>
#include <pthread.h>
static void *write_settings(void *unused) {
    (void)unused;for(int i=0;i<50000;i++) assert(nd_totk_camera_configure(i%2?70:150));
    return 0;
}
int main(void) {
    pthread_t writer;assert(!pthread_create(&writer,0,write_settings,0));
    for(int i=0;i<50000;i++) {
        float angle=1.f;nd_totk_camera_apply(&angle);
        assert(angle==1.f || fabsf(angle-0.7f)<0.000001f || angle==1.5f);
    }
    assert(!pthread_join(writer,0));return 0;
}
''')

    def fixture(self):
        nso = Nso(None, raw=synthetic_module(17))
        nso.build_id = native_camera.BUILD_ID
        sites = []
        for offset, word in ((0x90,0xbd413e60),(0xd0,0xbd4066c0)):
            struct.pack_into('<III', nso.image, offset, word, 0x1e210808, 0xd65f03c0)
            sites.append((offset,word,hashlib.sha256(nso.image[offset-32:offset+32]).hexdigest()))
        m = Module.__new__(Module)
        m.name, m.base, m.nso = 'main', 0x800000000, nso
        m.lo, m.hi = m.base, m.base+nso.text[1]
        m.words = array.array('I', nso.image[:nso.text[1]])
        m.lifter = Lifter(m.base, 'c')
        m.cache, m.by_word, m.pc_words, m.stats = {}, {}, set(), Counter()
        return m, tuple(sites)

    def test_profile_rejects_wrong_version_context_instruction_and_overlapping_patch(self):
        for mutation in ('version','name','base','context','word','existing','text'):
            m,sites = self.fixture();patches={}
            if mutation=='version': m.nso.build_id='wrong'
            elif mutation=='name': m.name='sdk'
            elif mutation=='base': m.base+=4
            elif mutation=='context': m.nso.image[0x80]^=1
            elif mutation=='word': m.words[0x90//4]^=1
            elif mutation=='existing': patches[m.base+0xd0]=None
            elif mutation=='text': m.hi=m.base+0xe0
            before=patches.copy()
            with self.subTest(mutation=mutation), mock.patch.object(native_camera,'SITES',sites):
                with self.assertRaises(ValueError): native_camera.configure(m,patches)
                self.assertEqual(patches,before)

    def test_actual_emitted_load_and_multiply_reach_runtime_without_changing_other_registers(self):
        m,sites = self.fixture();patches={}
        gen = importlib.import_module('gen')
        with mock.patch.object(native_camera,'SITES',sites), mock.patch.object(gen,'PATCHES',patches):
            emitted = native_camera.configure(m,patches)
            with self.assertRaises(ValueError): native_camera.require_emitted(emitted)
            bodies=[]
            for offset,_,_ in sites:
                bodies += m.emit_function(m.base+offset,m.base+offset+12,set(),{}, {})
            native_camera.require_emitted(emitted)
        body='\n'.join(bodies)
        self.compile_run(r'''
#include "cpu.h"
#include "native_camera.h"
#include <assert.h>
#include <math.h>
#include <stdlib.h>
volatile int g_fnprof;
void fnprof_hit(uint64_t a,uint64_t b,uint64_t d) {abort();}
''' + body + r'''
int main(void) {
    unsigned char memory[512]={0};float angle=.8f,ratio=2.f;
    memcpy(memory+0x13c,&angle,4);memcpy(memory+0x64,&angle,4);
    void (*hooks[])(Cpu *)={f_800000090,f_8000000d0};
    for(unsigned hook=0;hook<2;hook++) for(int value=70;value<=150;value+=10) {
        Cpu cpu;memset(&cpu,0xa5,sizeof cpu);
        cpu.fpcr=0;cpu.fpsr=0;
        cpu.x[19]=(uint64_t)(uintptr_t)memory;cpu.x[22]=(uint64_t)(uintptr_t)memory;
        cpu.v[1]=0;memcpy(&cpu.v[1],&ratio,4);Cpu expected=cpu;
        assert(nd_totk_camera_configure(value));hooks[hook](&cpu);
        float scaled=angle*((float)value/100.f),product=scaled*ratio,actual;
        memcpy(&actual,&cpu.v[8],4);assert(fabsf(actual-product)<.000001f);
        memcpy(&expected.v[0],&cpu.v[0],sizeof cpu.v[0]);
        memcpy(&expected.v[8],&cpu.v[8],sizeof cpu.v[8]);
        /* The original floating multiply may accumulate ARM FP exceptions. */
        assert(!(cpu.fpsr & ~0x9fu));expected.fpsr=cpu.fpsr;
        assert(!memcmp(&expected,&cpu,sizeof cpu));
    }
    return 0;
}
''')

    def test_generator_publishes_capability_only_after_both_hooks_are_emitted(self):
        gen = importlib.import_module('gen')
        m,sites=self.fixture()
        # Materialize genuine function boundaries through two original BLs.
        for at,target in ((0x58,0x90),(0x5c,0xd0)):
            word=0x94000000|((target-at)//4)
            m.words[at//4]=word;struct.pack_into('<I',m.nso.image,at,word)
        with tempfile.TemporaryDirectory(prefix='camera-gen-',dir=Path.cwd()) as directory:
            out=Path(directory)
            argv=['gen.py','main','synthetic.nso',hex(m.base),str(out),'--simd','c','--native-camera']
            with mock.patch.object(gen,'Module',return_value=m), mock.patch.object(gen,'PATCHES',{}), \
                 mock.patch.object(native_camera,'SITES',sites), mock.patch.object(sys,'argv',argv), \
                 contextlib.redirect_stderr(io.StringIO()):
                gen.main()
            self.assertEqual((out/'main_table.c').read_text().count('nd_totk_camera_profile_v143 = 1;'),1)
            chunks=''.join(p.read_text()for p in out.glob('main_[0-9]*.c'))
            self.assertEqual(chunks.count('nd_totk_camera_apply(&c->v[0])'),2)
            with mock.patch.object(sys,'argv',argv+['--limit','1']), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit): gen.main()
