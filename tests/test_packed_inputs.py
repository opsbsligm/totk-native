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

    def test_duplicate_and_overlapping_ranges_are_rejected(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root = Path(tmp)
            (root / 'romfs.bin').write_bytes(b'abcdef')
            for second in (dict(path='a', offset=0, size=3), dict(path='b', offset=0, size=3)):
                rows = [dict(path='a', offset=0, size=3), second]
                (root / 'index.json').write_text(json.dumps(dict(files=rows)))
                with self.assertRaises(ValueError):
                    inputs.rows_for(root)
