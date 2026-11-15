# SPDX-License-Identifier: MIT
"""Synthetic three-module AOT/package contracts; no private game data or shaders."""
import contextlib
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import lz4.block

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import build_linux
import build_receipts
import linux_inputs
import package_linux
import prepare_linux_game
import static_mods

MOVZ, RET = 0xd2800000, 0xd65f03c0


def synthetic_module(identity):
    """Small original NSO: three functions, symbols and one RELA target."""
    text, ro, data = bytearray(0x100), bytearray(0x200), bytearray(0x200)
    struct.pack_into('<II', text, 0, 0x14000010, 8)
    struct.pack_into('<4s6i', text, 8, b'MOD0', 0x2000-8, 0x2200-8, 0x2300-8,
                     -8, -8, 0x2200-8)
    names = b'\0test_fn0\0test_fn1\0test_fn2\0'
    ro[:len(names)] = names
    for i in range(3):
        struct.pack_into('<II', text, 0x40+8*i, MOVZ|((i+1)<<5), RET)
        struct.pack_into('<IBBHQQ', ro, 0x80+24*(i+1), 1+9*i, 0x12, 0, 1, 0x40+8*i, 8)
    struct.pack_into('<II', ro, 0x100, 1, 4)
    tags = [(4, 0x1100), (5, 0x1000), (6, 0x1080), (10, len(names)),
            (7, 0x2100), (8, 24), (0, 0)]
    for i, pair in enumerate(tags):
        struct.pack_into('<QQ', data, i*16, *pair)
    struct.pack_into('<QQq', data, 0x100, 0x2180, 1027, 0x40)
    raw = bytearray(0x100)
    raw[:4] = b'NSO0'; raw[0x40:0x60] = bytes([identity])*32
    struct.pack_into('<I', raw, 0xc, 0x3f); struct.pack_into('<I', raw, 0x3c, 0x100)
    for i, segment in enumerate((text, ro, data)):
        packed = lz4.block.compress(bytes(segment), store_size=False)
        struct.pack_into('<III', raw, 0x10+16*i, len(raw), i*0x1000, len(segment))
        struct.pack_into('<I', raw, 0x60+4*i, len(packed))
        raw[0xa0+32*i:0xc0+32*i] = hashlib.sha256(segment).digest()
        raw.extend(packed)
    return bytes(raw)


class TotkStaticMods(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='totk-static-fixture-', dir=Path.cwd())
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.dump, self.work = self.root/'dump', self.root/'work'
        self.exefs = self.dump/'exefs'; self.exefs.mkdir(parents=True)
        marker = self.dump/'romfs/Pack/ZsDic.pack.zs'; marker.parent.mkdir(parents=True)
        marker.write_bytes(b'original synthetic marker, not a game pack')
        self.originals = {n:synthetic_module(i+17) for i,n in enumerate(linux_inputs.BASES)}
        for name, raw in self.originals.items():
            (self.exefs/name).write_bytes(raw)
        self.pins = {n:hashlib.sha256(v).hexdigest() for n,v in self.originals.items()}
        patcher = mock.patch.object(linux_inputs, 'expected', return_value={'EXEFS':self.pins})
        patcher.start(); self.addCleanup(patcher.stop)
        patcher = mock.patch.object(static_mods, 'host_symbols', return_value={'test_fn1'})
        patcher.start(); self.addCleanup(patcher.stop)
        real_module = static_mods.lifter_module
        def module(name):
            # This tiny original module has no actual game clock/DRS functions.
            # Only this process gets a miniature protected-site profile.
            if name == 'native_clock':
                return SimpleNamespace(instruction_profile=lambda: ({}, {0x50:MOVZ}))
            if name == 'patches':
                return SimpleNamespace(PATCHES={linux_inputs.BASES['main'][0]+0x58:None})
            return real_module(name)
        patcher = mock.patch.object(static_mods, 'lifter_module', side_effect=module)
        patcher.start(); self.addCleanup(patcher.stop)
        self.mods = self.root/'mods'
        self.patch = self.mods/'10-value/exefs/value.pchtxt'; self.patch.parent.mkdir(parents=True)
        self.write_patch()
        self.work.mkdir()

    def write_patch(self, value=42, offset=0x140):
        self.patch.write_text('@nsobid-'+self.originals['main'][0x40:0x60].hex()+
                              '\n@enabled\n'+f'{offset:08x} '+struct.pack('<I', MOVZ|(value<<5)).hex()+'\n')

    def prepare(self):
        return static_mods.prepare(self.exefs, self.mods, work=self.work)

    def lift(self, mods=True, fail_module=None):
        old_path = list(sys.path)
        sys.path.insert(0, str(ROOT/'tools/lifter'))
        try:
            gen = importlib.import_module('gen')
            clock = importlib.import_module('native_clock')
        finally:
            sys.path[:] = old_path
        def run(command, **kwargs):
            index = command.index(str(ROOT/'tools/lifter/gen.py'))
            if command[index+1] == fail_module:
                raise subprocess.CalledProcessError(7, ['synthetic-lift-failure'])
            with mock.patch.object(sys, 'argv', command[index:]), \
                 mock.patch.object(sys, 'path', [str(ROOT/'tools/lifter'), *sys.path]), \
                 mock.patch.object(clock, 'configure', return_value=None), \
                 contextlib.redirect_stdout(kwargs['stdout']), contextlib.redirect_stderr(kwargs['stdout']):
                gen.main()
            return subprocess.CompletedProcess(command, 0)
        argv = ['prepare_linux_game.py', '--dump', str(self.dump), '--data', str(self.work/'data'), '--stage', 'lift']
        if mods:
            argv += ['--code-mods', str(self.mods)]
        with mock.patch.object(sys, 'argv', argv), mock.patch.object(prepare_linux_game.subprocess, 'run', side_effect=run), \
             contextlib.redirect_stdout(io.StringIO()):
            prepare_linux_game.main()
        return self.work/'data/generated'

    def compile_function(self, generated, value=42):
        out = self.work/'game'; out.mkdir(exist_ok=True)
        harness = self.root/'execute.c'
        harness.write_text('#include "cpu.h"\nvoid f_800000040(Cpu *);\n'
                           'int main(void){Cpu c={0};f_800000040(&c);return c.x[0]=='+str(value)+'?0:1;}\n')
        target = out/'ultratears'
        result = subprocess.run(['clang', '-std=gnu17', '-O1', '-ffunction-sections', '-fdata-sections',
            '-I'+str(ROOT/'src/runtime'), '-I'+str(ROOT/'src/host'), '-Wl,--gc-sections',
            *map(str, sorted((generated/'main').glob('main_[0-9]*.c'))), str(harness),
            str(ROOT/'src/runtime/dispatch.c'), '-lm', '-o', str(target)],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(subprocess.run([str(target)], timeout=5).returncode, 0)
        return target

    def test_metadata_hle_native_clock_and_relocation_targets_are_protected(self):
        for offset in [4, 8, 0x1000, 0x1080, 0x1100, 0x2000, 0x2100, 0x2180, 0x48, 0x50, 0x58]:
            with self.subTest(offset=hex(offset)):
                self.write_patch(offset=offset+0x100)
                with self.assertRaisesRegex(ValueError, '保留'):
                    self.prepare()
        self.write_patch(); self.assertEqual(self.prepare().prepared.changed_modules, ('main',))

    def test_real_lifter_and_compiler_execute_the_patched_function_and_remove_cleanly(self):
        generated = self.lift()
        files, context = linux_inputs.verify_generated_inputs(generated, self.exefs, self.mods)
        self.assertTrue(files); self.assertEqual(context.prepared.changed_modules, ('main',))
        self.compile_function(generated, 42)
        self.assertFalse(list((self.work/'data').glob('.mod-exefs-*')))
        self.assertFalse((generated/'static-mods').exists())
        for name, raw in self.originals.items():
            self.assertEqual((self.exefs/name).read_bytes(), raw)
        with self.assertRaisesRegex(ValueError, 'without --code-mods'):
            linux_inputs.verify_generated(generated, self.exefs)
        self.lift(mods=False)
        self.assertFalse((generated/static_mods.RECORD).exists())
        linux_inputs.verify_generated(generated, self.exefs)
        self.compile_function(generated, 1)

    def test_late_generation_failure_removes_prepared_modules_and_never_seals(self):
        with self.assertRaises(SystemExit):
            self.lift(fail_module='sdk')
        self.assertFalse((self.work/'data/generated/manifest-linux.json').exists())
        self.assertFalse(list((self.work/'data').glob('.mod-exefs-*')))

    def test_changed_patch_and_generated_output_cannot_reuse_a_receipt(self):
        generated = self.lift()
        self.write_patch(value=43)
        with self.assertRaisesRegex(ValueError, 'regenerate'):
            linux_inputs.verify_generated(generated, self.exefs, self.mods)
        self.write_patch()
        chunk = next((generated/'main').glob('main_[0-9]*.c'))
        chunk.write_text(chunk.read_text()+'\n/* changed fixture */\n')
        with self.assertRaisesRegex(ValueError, 'Generated files changed'):
            linux_inputs.verify_generated(generated, self.exefs, self.mods)

    def test_phase_receipt_rejects_assets_for_a_different_mod_set(self):
        first = static_mods.phase_inputs(self.prepare())
        folder = self.work/'asset'; folder.mkdir(); (folder/'data').write_bytes(b'synthetic')
        with mock.patch.object(build_receipts, 'source_stamp', return_value='same-source'):
            build_receipts.publish(self.work, 'assets', [folder], 'same-source', inputs=first)
            build_receipts.verify(self.work, 'assets', inputs=first)
            self.write_patch(value=43)
            with self.assertRaisesRegex(ValueError, 'static mod inputs'):
                build_receipts.verify(self.work, 'assets', inputs=static_mods.phase_inputs(self.prepare()))
            with self.assertRaisesRegex(ValueError, 'static mod inputs'):
                build_receipts.verify(self.work, 'assets')

    def package_inputs(self):
        generated = self.lift(); binary = self.compile_function(generated)
        build_linux.write_game_build_record(binary, generated, self.exefs,
            linux_inputs.digest(generated/'manifest-linux.json'), None, None, self.mods)
        for name in ['romfs', 'shaders', 'textures', 'deck-ui']:
            folder = self.work/'data'/name; folder.mkdir(exist_ok=True); (folder/'synthetic').write_bytes(b'fixture')
        fonts = self.dump/'fonts'; fonts.mkdir()
        for name in ['0-standard', '1-chinese-simplified', '2-chinese-simplified-extension',
                     '3-chinese-traditional', '4-korean', '5-nintendo-extension']:
            (fonts/(name+'.bfttf')).write_bytes(b'synthetic-font-fixture')
        identity = static_mods.phase_inputs(static_mods.verify_context(generated, self.exefs, self.mods))
        before = build_receipts.source_stamp()
        build_receipts.publish(self.work, 'code', [self.work/'game', generated], before, inputs=identity)
        build_receipts.publish(self.work, 'assets', [self.work/'data'/n for n in ['romfs','shaders','textures','deck-ui']], before, inputs=identity)
        return generated

    def package(self):
        argv = ['package_linux.py', '--work', str(self.work), '--dump', str(self.dump), '--code-mods', str(self.mods)]
        with mock.patch.object(sys, 'argv', argv), \
             mock.patch('font_inputs.validate_shared_fonts', return_value=None), \
             contextlib.redirect_stdout(io.StringIO()):
            package_linux.main()

    def test_package_uses_the_same_patched_modules_and_rejects_a_stale_binary(self):
        generated = self.package_inputs()
        self.package()
        package = self.work/'package'
        context = static_mods.verify_context(generated, self.exefs, self.mods)
        self.assertEqual((package/'data/exefs/main').read_bytes(), context.prepared.modules['main'])
        self.assertEqual(json.loads((package/'provenance/static-mods.json').read_text()), static_mods.record(context))
        self.assertEqual(subprocess.run([str(package/'ultratears')], timeout=5).returncode, 0)
        self.write_patch(value=43)
        with self.assertRaises(ValueError):
            self.package()
        self.assertTrue((package/'bundle.json').is_file())

    def test_failed_package_copy_does_not_retain_another_game_tree(self):
        self.package_inputs()
        with mock.patch.object(package_linux, 'bundle_libraries', side_effect=OSError('injected copy failure')):
            with self.assertRaisesRegex(OSError, 'copy failure'):
                self.package()
        self.assertFalse((self.work/'package.new').exists()); self.assertFalse((self.work/'package').exists())
        self.assertTrue((self.work/'game/ultratears').is_file())


class NativeHleAndClockContracts(unittest.TestCase):
    def test_actual_linux_preprocessing_finds_the_compiled_hle_bindings(self):
        with tempfile.TemporaryDirectory(prefix='hle-registry-fixture-', dir=Path.cwd()) as name:
            names = static_mods.host_symbols(name)
            self.assertIn('nvnBootstrapLoader', names)
            self.assertIn('_ZN2nn3hid14InitializeNpadEv', names)
            self.assertFalse(list(Path(name).iterdir()))

    def test_clock_profile_still_validates_all_18_sites_before_installing_any_patch(self):
        clock = static_mods.lifter_module('native_clock'); fps, guards = clock.instruction_profile()
        self.assertEqual(len(fps), 7); self.assertEqual(len(guards), 18)
        base = 0x800000000
        module = SimpleNamespace(name='main', base=base, word=lambda a:guards[a-base],
            lifter=SimpleNamespace(lift=lambda word,a:SimpleNamespace(kind='op', code=f'/* {word:x} */')))
        patches = {}; clock.configure(module, patches)
        self.assertEqual(set(patches), {base+offset for offset in guards})
        bad = next(reversed(guards)); module.word = lambda a:guards[a-base] ^ (1 if a-base==bad else 0)
        patches = {}
        with self.assertRaisesRegex(ValueError, 'Unexpected v1.4.3'):
            clock.configure(module, patches)
        self.assertEqual(patches, {})


if __name__ == '__main__':
    unittest.main()
