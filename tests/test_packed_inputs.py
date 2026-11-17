"""Packed inputs must authenticate bytes, never trust a claimed manifest hash."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('packed_inputs', ROOT / 'tools/packed_inputs.py')
inputs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inputs)


class PackedInputs(unittest.TestCase):
    def test_authenticates_content_and_rejects_corruption(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root = Path(tmp)
            data = b'hello'
            (root / 'romfs.bin').write_bytes(data)
            rows = [dict(path='Pack/test', offset=0, size=len(data))]
            (root / 'index.json').write_text(json.dumps(dict(files=rows, content_sha256='untrusted')))
            expected = dict(ROMFS_FILES=1, ROMFS_BYTES=5,
                ROMFS_CONTENT=hashlib.sha256(hashlib.sha256(data).digest()).hexdigest())
            inputs.validate(root, expected)
            (root / 'romfs.bin').write_bytes(b'wrong')
            with self.assertRaisesRegex(ValueError, 'content differs'):
                inputs.validate(root, expected)
            for name in ('../file', '/file', 'a/../file', 'a\\file'):
                rows[0]['path'] = name
                (root / 'index.json').write_text(json.dumps(dict(files=rows)))
                with self.subTest(name=name), self.assertRaises(ValueError):
                    inputs.rows_for(root)

    def test_import_keeps_in_place_bytes_instead_of_copying_onto_itself(self):
        """A work area seeded by hardlink from a release must not fail or duplicate."""
        import os
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            source = Path(tmp) / 'romfs'
            source.mkdir()
            data = b'abc' + b'\0' * 13 + b'de'   # row offsets are 16-byte aligned
            (source / 'romfs.bin').write_bytes(data)
            (source / 'index.json').write_text(json.dumps(dict(files=[
                dict(path='a', offset=0, size=3), dict(path='b', offset=16, size=2)])))
            expected = dict(ROMFS_FILES=2, ROMFS_BYTES=5,
                ROMFS_CONTENT=hashlib.sha256(
                    hashlib.sha256(b'abc').digest()
                    + hashlib.sha256(b'de').digest()).hexdigest())
            output = Path(tmp) / 'work' / 'romfs'
            output.mkdir(parents=True)
            for name in ('romfs.bin', 'index.json'):
                os.link(source / name, output / name)
            inputs.import_packed(source, output, expected)
            self.assertTrue(os.path.samefile(source / 'romfs.bin', output / 'romfs.bin'))
            self.assertEqual((output / 'romfs.bin').read_bytes(), data)
            # A plain directory still gets a real copy rather than a skipped write.
            fresh = Path(tmp) / 'fresh' / 'romfs'
            inputs.import_packed(source, fresh, expected)
            self.assertFalse(os.path.samefile(source / 'romfs.bin', fresh / 'romfs.bin'))
            self.assertEqual((fresh / 'romfs.bin').read_bytes(), data)

    def test_duplicate_and_overlapping_ranges_are_rejected(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root = Path(tmp)
            (root / 'romfs.bin').write_bytes(b'abcdef')
            for second in (dict(path='a', offset=0, size=3), dict(path='b', offset=0, size=3)):
                rows = [dict(path='a', offset=0, size=3), second]
                (root / 'index.json').write_text(json.dumps(dict(files=rows)))
                with self.assertRaises(ValueError):
                    inputs.rows_for(root)
