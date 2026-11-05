"""Validate archive/part boundaries before any decryption or filesystem install."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('recovery',ROOT/'tools/recovery.py')
recovery=importlib.util.module_from_spec(spec);spec.loader.exec_module(recovery)


class Recovery(unittest.TestCase):
    def test_archive_names_cannot_escape_or_alias(self):
        for name in ('../keys','/etc/passwd','dump/../../file','dump//file','dump/./file','dump\\file',''):
            with self.subTest(name=name),self.assertRaises(ValueError):recovery.safe_name(name)
        self.assertEqual(str(recovery.safe_name('dump/romfs/assets.bin')),'dump/romfs/assets.bin')

    def test_corrupt_part_cannot_create_restored_tree(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root=Path(tmp);bundle=root/'bundle';bundle.mkdir();output=root/'restored'
            (bundle/'payload-00000.age.part').write_bytes(b'changed')
            index=dict(schema=1,cipher='age',parts=[dict(name='payload-00000.age.part',bytes=7,sha256='0'*64)])
            (bundle/'index.json').write_text(json.dumps(index))
            with self.assertRaisesRegex(ValueError,'corrupt'):
                recovery.restore(SimpleNamespace(bundle=str(bundle),identity='unused',destination=str(output),max_bytes=1024))
            self.assertFalse(output.exists())

    def test_part_name_cannot_read_outside_bundle(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root=Path(tmp);index=dict(schema=1,cipher='age',parts=[dict(name='../identity',bytes=1,sha256='0'*64)])
            (root/'index.json').write_text(json.dumps(index))
            with self.assertRaisesRegex(ValueError,'sequence'):
                recovery.restore(SimpleNamespace(bundle=str(root),identity='unused',destination=str(root/'out'),max_bytes=1024))
