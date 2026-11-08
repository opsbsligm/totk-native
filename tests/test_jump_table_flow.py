"""Assemble original AArch64 fixtures and check complete native branch targets."""
from pathlib import Path
from collections import Counter
import shutil
import struct
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/lifter'))
import table_flow


def assemble(source):
    with tempfile.TemporaryDirectory(prefix='table-flow-', dir=Path.cwd()) as directory:
        output = Path(directory) / 'fixture.o'
        subprocess.run([shutil.which('clang'), '--target=aarch64-linux-gnu', '-x', 'assembler',
                        '-c', '-', '-o', str(output)], input=source.encode(), check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        data = output.read_bytes()
    if data[:6] != b'\x7fELF\x02\x01':
        raise AssertionError('Expected little-endian ELF64 fixture')
    offset = struct.unpack_from('<Q', data, 40)[0]
    size, count, strings_index = struct.unpack_from('<HHH', data, 58)
    sections = [struct.unpack_from('<IIQQQQIIQQ', data, offset + index * size) for index in range(count)]
    strings_section = sections[strings_index]
    strings = data[strings_section[4]:strings_section[4] + strings_section[5]]
    names = [strings[section[0]:].split(b'\0', 1)[0].decode() for section in sections]
    text_index = names.index('.text')
    text = sections[text_index]
    symbols = {}
    for section in sections:
        if section[1] != 2:
            continue
        symbol_strings = sections[section[6]]
        table = data[symbol_strings[4]:symbol_strings[4] + symbol_strings[5]]
        for position in range(section[4], section[4] + section[5], section[9]):
            name, info, other, index, value, length = struct.unpack_from('<IBBHQQ', data, position)
            if index == text_index:
                symbols[table[name:].split(b'\0', 1)[0].decode()] = 0x100000 + value
    image = data[text[4]:text[4] + text[5]]
    nso = types.SimpleNamespace(image=image, text=(0, len(image)), rodata=(len(image), 0), relocs=[])
    module = types.SimpleNamespace(base=0x100000, nso=nso,
        word=lambda address: struct.unpack_from('<I', image, address - 0x100000)[0],
        computed_target=lambda address, entry: True)
    return module, symbols


def fixture(prefix='', before_load='', index='fmov w18, s0', bound='hi', table_register='x20'):
    return f'''.text
entry:
 cbz w0, alternate
 adr {table_register}, table_a
 b selected
alternate:
 adr {table_register}, table_b
selected:
 {index}
 cmp w18, #1
 {prefix}
 b.{bound} exit
 {before_load}
 adr x16, target_base
 ldrh w17, [{table_register}, x18, lsl #1]
 add x16, x16, x17, lsl #2
dispatch:
 br x16
target_base:
target_a:
 ret
target_b:
 ret
target_c:
 ret
target_d:
 ret
exit:
 ret
finish:
table_a:
 .hword (target_a-target_base)/4, (target_b-target_base)/4
table_b:
 .hword (target_c-target_base)/4, (target_d-target_base)/4
'''


class JumpTableFlow(unittest.TestCase):
    def resolve(self, source, configure=None):
        module, labels = assemble(source)
        if configure:
            configure(module, labels)
        return table_flow.resolve(module, labels['entry'], labels['finish']), labels

    def test_disjoint_conditional_table_bases_are_joined(self):
        result, labels = self.resolve(fixture())
        self.assertEqual(set(result[labels['dispatch']]), {labels[f'target_{name}'] for name in 'abcd'})

    def test_condition_flags_clobbered_before_branch_are_not_bounds(self):
        result, labels = self.resolve(fixture(prefix='adds x6, x6, #1'))
        self.assertEqual(result, {})

    def test_compared_register_clobber_removes_bounds(self):
        result, labels = self.resolve(fixture(prefix='mov x18, x1'))
        self.assertEqual(result, {})

    def test_w_compare_does_not_bound_unknown_high_x_bits(self):
        result, labels = self.resolve(fixture(index='fmov x18, d0'))
        self.assertEqual(result, {})

    def test_call_clobbered_table_pointer_does_not_become_constant(self):
        result, labels = self.resolve(fixture(table_register='x9', before_load='blr x2'))
        self.assertEqual(result, {})

    def test_call_preserved_table_pointer_can_still_resolve(self):
        source = fixture(before_load='blr x2\n fmov w18, s0\n cmp w18, #1\n b.hi exit')
        result, labels = self.resolve(source)
        self.assertEqual(len(result[labels['dispatch']]), 4)

    def test_relocated_table_read_requires_fallback(self):
        def configure(module, labels):
            module.nso.relocs = [(labels['table_b'] - module.base, 0, 0, 0)]
        result, labels = self.resolve(fixture(), configure)
        self.assertEqual(result, {})

    def test_writable_table_read_requires_fallback(self):
        def configure(module, labels):
            module.nso.text = (0, labels['finish'] - module.base)
        result, labels = self.resolve(fixture(), configure)
        self.assertEqual(result, {})

    def test_inclusive_bounds_include_last_case(self):
        source = fixture().replace('cmp w18, #1', 'cmp w18, #2').replace('b.hi exit', 'b.hs exit')
        result, labels = self.resolve(source)
        self.assertEqual(len(result[labels['dispatch']]), 4)

    def test_budget_exhaustion_never_returns_partial_targets(self):
        with patch.object(table_flow, 'MAX_STEPS', 4):
            result, labels = self.resolve(fixture())
        self.assertEqual(result, {})

    def test_unknown_second_branch_invalidates_partial_results(self):
        source = fixture().replace('target_a:\n ret', 'target_a:\n add x16, x0, x1\n br x16')
        result, labels = self.resolve(source)
        self.assertEqual(result, {})

    def test_loop_widens_without_discarding_independent_bounds(self):
        source = fixture().replace('entry:\n', 'entry:\n mov x5, #0\nloop:\n add x5, x5, #1\n cbnz w1, loop\n')
        result, labels = self.resolve(source)
        self.assertEqual(len(result[labels['dispatch']]), 4)

    def test_register_shift_uses_w_width(self):
        source = fixture(index='mov w18, #1\n mov w3, #32\n lsl w18, w18, w3')
        result, labels = self.resolve(source)
        self.assertEqual(set(result[labels['dispatch']]), {labels['target_b'], labels['target_d']})

    def test_signed_byte_offsets_reach_cases_before_the_base(self):
        source = fixture().replace('adr x16, target_base', 'adr x16, target_d')
        source = source.replace('ldrh w17, [x20, x18, lsl #1]', 'ldrsb x17, [x20, x18]')
        source = source.replace('.hword', '.byte').replace('-target_base)/4', '-target_d)/4')
        result, labels = self.resolve(source)
        self.assertEqual(set(result[labels['dispatch']]), {labels[f'target_{name}'] for name in 'abcd'})

    def test_signed_word_offsets_reach_cases_before_the_base(self):
        source = fixture().replace('adr x16, target_base', 'adr x16, target_d')
        source = source.replace('ldrh w17, [x20, x18, lsl #1]', 'ldrsw x17, [x20, x18, lsl #2]')
        source = source.replace('.hword', '.word').replace('-target_base)/4', '-target_d)/4')
        result, labels = self.resolve(source)
        self.assertEqual(set(result[labels['dispatch']]), {labels[f'target_{name}'] for name in 'abcd'})

    @unittest.skipUnless(sys.platform == 'linux', 'Linux guest-address mapping regression')
    def test_emitted_native_c_executes_every_conditional_table_case(self):
        from gen import Module
        from lifter import Lifter
        source = fixture()
        for name, marker in zip('abcd', (11, 22, 33, 44)):
            source = source.replace(f'target_{name}:\n ret', f'target_{name}:\n mov w4, #{marker}\n ret')
        template, labels = assemble(source)
        module = Module.__new__(Module)
        module.__dict__.update(vars(template))
        del module.computed_target
        module.lo, module.hi = module.base, labels['finish']
        module.lifter = Lifter(module.base, 'c')
        module.cache, module.by_word, module.pc_words, module.stats = {}, {}, set(), Counter()
        targets, external, tables = module.scan(labels['entry'], labels['finish'])
        self.assertEqual(len(tables[labels['dispatch']]), 4)
        body = '\n'.join(module.emit_function(labels['entry'], labels['finish'], targets, tables, {}))
        data = ','.join(str(value) for value in module.nso.image)
        program = '''#include <stdlib.h>
#include <sys/mman.h>
#include "cpu.h"
#include "simd.h"
volatile int g_fnprof;
void fnprof_hit(uint64_t a, uint64_t b, uint64_t d) { abort(); }
void rt_dispatch(Cpu *c) { abort(); }
void rt_udf(Cpu *c, uint64_t pc) { abort(); }
''' + body + '''
int main(void) {
    unsigned char image[] = {''' + data + '''};
    void *memory = mmap((void *)0x100000, 4096, PROT_READ | PROT_WRITE,
        MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
    if (memory == MAP_FAILED) return 10;
    memcpy(memory, image, sizeof(image));
    for (unsigned path = 0; path < 2; ++path) {
        for (unsigned index = 0; index < 2; ++index) {
            Cpu cpu = {0}; cpu.x[0] = path; cpu.v[0] = index;
            f_100000(&cpu);
            unsigned expected = path ? (index ? 22 : 11) : (index ? 44 : 33);
            if (cpu.x[4] != expected) return 20;
        }
    }
    return munmap(memory, 4096) != 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='table-native-', dir=Path.cwd()) as directory:
            executable = Path(directory) / 'native-cases'
            subprocess.run([shutil.which('clang'), '-x', 'c', '-std=gnu11', '-O2',
                '-I', str(ROOT / 'src/runtime'), '-', '-o', str(executable), '-lm'],
                input=program.encode(), check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run([str(executable)], check=True, timeout=10)


if __name__ == '__main__':
    unittest.main(verbosity=2)
