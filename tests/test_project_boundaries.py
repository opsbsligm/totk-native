"""Behavioral checks for portable source/output and package integrity boundaries."""
import hashlib
import importlib.util
import json
import os
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
    def test_totk_launch_preserves_measured_clock_and_uncapped_interval(self):
        entry = module('totk_launch', 'packaging/run.py')
        class LaunchCaptured(Exception):
            pass
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            directory = Path(tmp)
            (directory / 'bundle.json').write_text(json.dumps(dict(schema=1, version='1.4.3', files={})))
            with patch.object(entry, 'ROOT', directory), patch.dict(os.environ,
                    {'XDG_DATA_HOME': str(directory / 'state'), 'XDG_CACHE_HOME': str(directory / 'cache')}, clear=True), \
                 patch.object(entry.os, 'chdir'), patch.object(entry.os, 'execvpe', side_effect=LaunchCaptured) as execute, \
                 patch.object(entry.sys, 'argv', ['run.py']):
                with self.assertRaises(LaunchCaptured):
                    entry.main()
                env = execute.call_args.args[2]
                for name in ('TOTK_UNCAPPED', 'TOTK_UNCAPPED_INTERVAL', 'TOTK_REALTIME', 'TOTK_FPS60', 'TOTK_STEAMDECK_UI'):
                    self.assertEqual(env[name], '1', name)
                self.assertEqual(env['TOTK_UNCAPPED_HZ'], '60')

    def test_launcher_rejects_the_other_game_profile(self):
        entry = module('profile_launch', 'packaging/run.py')
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            directory = Path(tmp)
            (directory / 'bundle.json').write_text(json.dumps(dict(schema=1, version='1.6.0', files={})))
            with patch.object(entry, 'ROOT', directory), patch.object(entry.sys, 'argv', ['run.py', '--verify']):
                with self.assertRaises(SystemExit) as failure:
                    entry.main()
                self.assertEqual(failure.exception.code, 2)

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
