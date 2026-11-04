"""Behavioral checks for portable source/output and package integrity boundaries."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class Boundaries(unittest.TestCase):
    def test_build_outputs_cannot_overlap_checkout(self):
        entry = module('entry', 'build.py')
        for path in (ROOT, ROOT / 'out', ROOT.parent):
            with self.subTest(path=path), self.assertRaises(Exception):
                entry.external_path(str(path))
        self.assertEqual(entry.external_path('/mnt/build area'), Path('/mnt/build area'))

    def test_package_rejects_path_traversal_truncation_and_changed_program(self):
        entry = module('launch', 'packaging/run.py')
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root = Path(tmp)
            (root / 'ultratears').write_bytes(b'program')
            files = {'ultratears': dict(size=7, sha256=hashlib.sha256(b'program').hexdigest())}
            with patch.object(entry, 'ROOT', root):
                entry.checked_files({'files': files}, False)
                (root / 'ultratears').write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    entry.checked_files({'files': files}, False)
                (root / 'ultratears').write_bytes(b'')
                with self.assertRaisesRegex(ValueError, 'truncated'):
                    entry.checked_files({'files': files}, False)
                for name in ('../escape', '/absolute'):
                    with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'manifest path'):
                        entry.checked_files({'files': {name: files['ultratears']}}, True)

    def test_game_inputs_are_not_present_in_public_tree(self):
        for name in ('extracted', 'generated', 'data', 'game', 'Keys'):
            self.assertFalse((ROOT / name).exists(), name)
        profile = json.loads((ROOT / 'UPSTREAM.json').read_text())
        self.assertFalse(profile['game_content_included'])
