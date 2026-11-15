# SPDX-License-Identifier: MIT
"""真实目录/FD/原子发布回归；只使用原创 NSO 夹具。"""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from code_mods import prepare_modules
from mods_snapshot import publish, snapshot_exefs, snapshot_patches
from test_code_mods import fixture, IDENTITY


class ModSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='native-code-mods-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.exefs = self.root / 'original'
        self.exefs.mkdir()
        self.original = fixture()
        (self.exefs / 'main').write_bytes(self.original)
        self.pins = {'main': hashlib.sha256(self.original).hexdigest()}
        self.mods = self.root / 'mods'
        self.mods.mkdir()

    def mod(self, name, value='AA'):
        exefs = self.mods / name / 'exefs'
        exefs.mkdir(parents=True)
        patch = exefs / 'example.pchtxt'
        patch.write_text('@nsobid-' + IDENTITY + '\n@enabled\n00000100 ' + value)
        return patch

    def prepare(self):
        return prepare_modules(snapshot_exefs(self.exefs, self.pins), snapshot_patches(self.mods), protected={'main': ()})

    def test_pins_and_directory_fd_reject_changed_original_and_extra_modules(self):
        self.assertEqual(snapshot_exefs(self.exefs, self.pins), {'main': self.original})
        (self.exefs / 'main').write_bytes(fixture(0))
        with self.assertRaisesRegex(ValueError, '指纹'):
            snapshot_exefs(self.exefs, self.pins)
        (self.exefs / 'main').write_bytes(self.original)
        (self.exefs / 'subsdk9').write_bytes(self.original)
        with self.assertRaisesRegex(ValueError, '清单'):
            snapshot_exefs(self.exefs, self.pins)

    def test_symlink_in_any_path_component_or_module_is_rejected(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.exefs, target_is_directory=True)
        with self.assertRaises(OSError):
            snapshot_exefs(alias, self.pins)
        with self.assertRaises(ValueError):
            snapshot_exefs(self.exefs / '..' / 'original', self.pins)
        (self.exefs / 'main').unlink()
        (self.root / 'outside').write_bytes(self.original)
        (self.exefs / 'main').symlink_to(self.root / 'outside')
        with self.assertRaises(OSError):
            snapshot_exefs(self.exefs, self.pins)

    def test_transient_devices_symlinks_and_unknown_patch_types_fail_without_blocking(self):
        patch = self.mod('active')
        patch.unlink()
        os.mkfifo(patch)
        with self.assertRaises(ValueError):
            snapshot_patches(self.mods)
        patch.unlink()
        patch.symlink_to(self.exefs / 'main')
        with self.assertRaises(OSError):
            snapshot_patches(self.mods)
        patch.unlink()
        patch.with_name('main').write_bytes(self.original)
        with self.assertRaisesRegex(ValueError, '不支持'):
            snapshot_patches(self.mods)

    def test_stable_snapshot_sorted_stack_and_disabled_mod_do_not_reopen_inputs(self):
        first = self.mod('10-first', 'AABB')
        self.mod('20-second', 'CC')
        hidden = self.mods / '.disabled'
        hidden.symlink_to('/nonexistent', target_is_directory=True)
        romfs = self.mods / 'only-romfs' / 'romfs'
        romfs.mkdir(parents=True)
        (self.mods / 'README.md').write_text('Local mod instructions')
        originals, patches = snapshot_exefs(self.exefs, self.pins), snapshot_patches(self.mods)
        first.write_text('bad text after snapshot')
        (self.exefs / 'main').write_bytes(b'bad original after snapshot')
        prepared = prepare_modules(originals, patches, protected={'main': ()})
        self.assertEqual(prepared.modules['main'][0x100:0x102], b'\xCC\xBB')
        target = self.root / 'prepared'
        record = publish(prepared, target)
        self.assertEqual(json.loads((target / 'manifest.json').read_text()), record)
        self.assertEqual((target / 'main').read_bytes(), prepared.modules['main'])
        self.assertEqual(record['inputs'], self.pins)

    def test_atomic_publish_never_replaces_an_existing_empty_directory_or_symlink(self):
        self.mod('active')
        prepared = self.prepare()
        target = self.root / 'prepared'
        target.mkdir()
        inode = target.stat().st_ino
        with self.assertRaises(FileExistsError):
            publish(prepared, target)
        self.assertEqual(target.stat().st_ino, inode)
        self.assertEqual(list(target.iterdir()), [])
        target.rmdir()
        target.symlink_to(self.exefs, target_is_directory=True)
        with self.assertRaises(FileExistsError):
            publish(prepared, target)
        self.assertEqual((self.exefs / 'main').read_bytes(), self.original)
        self.assertEqual(list(self.root.glob('.code-mods-*')), [])

    def test_late_validation_and_write_failure_publish_nothing_and_remove_intermediates(self):
        self.mod('10-good')
        bad = self.mod('99-bad', 'not-a-byte')
        target = self.root / 'prepared'
        with self.assertRaises(ValueError):
            publish(self.prepare(), target)
        self.assertFalse(target.exists())
        bad.unlink()
        prepared = self.prepare()
        with mock.patch('mods_snapshot.os.fsync', side_effect=OSError('injected disk failure')):
            with self.assertRaises(OSError):
                publish(prepared, target)
        self.assertFalse(target.exists())
        self.assertEqual(list(self.root.glob('.code-mods-*')), [])
        self.assertEqual((self.exefs / 'main').read_bytes(), self.original)


if __name__ == '__main__':
    unittest.main()
