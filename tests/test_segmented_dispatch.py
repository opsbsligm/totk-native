"""Execute cross-segment guest branches, calls and deep loops as native C."""
from collections import Counter
from pathlib import Path
import shutil,subprocess,sys,tempfile,unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/lifter'))
from gen import Module
from lifter import Lifter
import segmented
from test_jump_table_flow import assemble


class SegmentedDispatch(unittest.TestCase):
    def module(self, source):
        template,labels=assemble(source)
        m=Module.__new__(Module);m.__dict__.update(vars(template));del m.computed_target
        m.lo,m.hi=m.base,labels['finish'];m.lifter=Lifter(m.base,'c')
        m.cache,m.by_word,m.pc_words,m.stats={},{},set(),Counter()
        return m,labels

    def run_native(self, module, labels, main, extra=''):
        with patch.object(segmented,'SEGMENT_BYTES',64):
            body='\n'.join(segmented.emit(module,labels['entry'],labels['finish'],{}))
        program='''#include <stdlib.h>
#include <sys/resource.h>
#include "cpu.h"
#include "simd.h"
volatile int g_fnprof=1;
static unsigned entered,dispatched;
void fnprof_hit(uint64_t a,uint64_t b,uint64_t d) { entered++; }
void rt_dispatch(Cpu *c) { dispatched++; c->x[9]=7; }
void rt_udf(Cpu *c,uint64_t pc) { abort(); }
'''+body+'\n'+extra+'\nint main(void) {\n'+main+'\n}\n'
        with tempfile.TemporaryDirectory(prefix='segmented-native-',dir=Path.cwd()) as directory:
            for optimization in ('-O1','-O2'):
                output=Path(directory)/('native'+optimization)
                subprocess.run([shutil.which('clang'),'-x','c','-std=gnu17',optimization,
                    '-I',str(ROOT/'src/runtime'),'-','-o',str(output),'-lm'],input=program.encode(),
                    check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60)
                subprocess.run([str(output)],check=True,timeout=15)

    def test_cross_segment_conditional_indirect_call_and_return(self):
        m,labels=self.module('''.text
entry:
 cbz w0, first
 adr x16, second
 br x16
first:
 adr x16, remote
 br x16
 .rept 40
 nop
 .endr
remote:
 mov w4, #11
 b common
 .rept 40
 nop
 .endr
second:
 mov w4, #22
common:
 bl .+65536
 add w4, w4, w9
 ret
finish:
''')
        self.run_native(m,labels,'''for(unsigned path=0;path<2;path++) {
 Cpu c={0}; c.x[0]=path; f_100000(&c);
 if(c.x[4]!=(path?29:18) || entered!=path+1 || dispatched!=path+1) return 1;
} return 0;''')

    def test_deep_cross_segment_loop_uses_bounded_native_stack(self):
        m,labels=self.module('''.text
entry:
 b remote
 .rept 80
 nop
 .endr
remote:
 subs w0, w0, #1
 b.ne entry
 ret
finish:
''')
        self.run_native(m,labels,'''struct rlimit limit={512*1024,512*1024};
 if(setrlimit(RLIMIT_STACK,&limit)) return 1;
 Cpu c={0}; c.x[0]=1000000; f_100000(&c);
 return c.x[0]!=0 || entered!=1 || dispatched!=0;''')

    def test_every_instruction_target_and_invalid_targets(self):
        m,labels=self.module('''.text
entry:
 .rept 80
 nop
 .endr
 mov w4, #19
 ret
finish:
''')
        stop=labels['finish']
        self.run_native(m,labels,f'''for(uint64_t pc=0x100000;pc<{stop-4};pc+=4) {{
 Cpu c={{0}}; c.pc=pc; f_100000_resume(&c); if(c.x[4]!=19) return 1;
}}
 Cpu bad={{0}}; bad.pc=0x100001; f_100000_resume(&bad);
 bad.pc={stop}; f_100000_resume(&bad);
 return dispatched!=2 || entered!=0;''')

    def test_large_fallback_selection_preserves_instruction_patches(self):
        m,labels=self.module('.text\nentry:\n'+'.rept 1100\n nop\n.endr\n ret\nfinish:\n')
        with patch('gen.PATCHES',{labels['entry']:lambda mod,pc:'return;'}):
            text='\n'.join(m.emit_function(labels['entry'],labels['finish'],set(),{labels['entry']:'all'},{}))
        self.assertNotIn('_part_',text)
        self.assertIn('return;',text)


if __name__=='__main__':unittest.main(verbosity=2)
