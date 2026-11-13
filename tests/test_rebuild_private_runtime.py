"""Exercise restored entry selection with real verification subprocesses.

Only transport and decryption boundaries are replaced by authenticated-layout
fixtures here. Private recovery exercises cover the real age authentication.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class RestoredRuntimeEntrypoints(unittest.TestCase):
    def exercise(self, root, entries=(), missing=(), verify_exit=0, executable=True):
        spec = importlib.util.spec_from_file_location('private_rebuild_entry', ROOT/'tools/rebuild_private.py')
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        work = root/'work'
        calls = []
        real_run = subprocess.run

        def entry(path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('#!/bin/sh\nprintf "%s\\n" "$1" > "$(dirname "$0")/verified.txt"\nexit '+str(verify_exit)+'\n')
            path.chmod(0o700 if executable else 0o600)

        def boundary(args, **kwargs):
            args = list(map(str, args))
            calls.append(args)
            if len(args) > 2 and args[1].endswith('/recovery_gitlab.py'):
                self.assertEqual(args[2], 'fetch')
                encrypted = work/'encrypted'
                encrypted.mkdir()
                (encrypted/'index.json').write_text(json.dumps(dict(schema=3, kind='native-recovery-bundle')))
            elif len(args) > 2 and args[1].endswith('/recovery.py'):
                self.assertEqual(args[2], 'restore')
                restored = work/'restored'
                (restored/'dump/exefs').mkdir(parents=True)
                (restored/'recovery-receipt.json').write_text(json.dumps(dict(missing=list(missing))))
                for name in entries:
                    entry(restored/name)
            elif len(args) > 2 and args[1].endswith('/build.py'):
                self.assertIn(args[2], ('doctor', 'build'))
                if args[2] == 'build':
                    entry(work/'build/package/run.sh')
            else:
                return real_run(args, **kwargs)
            return SimpleNamespace(returncode=0)

        argv = ['rebuild_private.py', '--version', 'fixture-v3', '--token-file', str(root/'token'),
                '--identity', str(root/'identity'), '--work', str(work), '--jobs', '1']
        previous_umask = os.umask(0o077)
        try:
            with patch.object(tool, 'subprocess', SimpleNamespace(run=boundary)), \
                 patch.object(tool, 'shutil', SimpleNamespace(disk_usage=lambda _: SimpleNamespace(free=200*1024**3))), \
                 patch.object(sys, 'argv', argv):
                tool.main()
        finally:
            os.umask(previous_umask)
        return work, calls

    def test_all_supported_include_labels_execute_verify_without_build(self):
        for name in ('run.sh', 'dump/run.sh', 'runtime/run.sh'):
            with self.subTest(entry=name), tempfile.TemporaryDirectory() as tmp:
                work, calls = self.exercise(Path(tmp).resolve(), (name,))
                self.assertEqual(len(calls), 3)
                self.assertEqual(calls[-1], [str(work/'restored'/name), '--verify'])
                self.assertEqual((work/'restored'/name).with_name('verified.txt').read_text(), '--verify\n')
                self.assertFalse((work/'build').exists())

    def test_ambiguous_entries_fail_before_execution(self):
        for names in (('run.sh', 'dump/run.sh'), ('dump/run.sh', 'runtime/run.sh')):
            with self.subTest(entries=names), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                with self.assertRaisesRegex(SystemExit, 'Ambiguous'):
                    self.exercise(root, names)
                self.assertFalse(list((root/'work').rglob('verified.txt')))
                self.assertFalse((root/'work/build').exists())

    def test_recorded_missing_inputs_block_portable_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with self.assertRaisesRegex(SystemExit, 'recorded missing inputs'):
                self.exercise(root, ('dump/run.sh',), missing=('healthy-complete-romfs',))
            self.assertFalse(list((root/'work').rglob('verified.txt')))

    def test_failed_verification_never_falls_back_to_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with self.assertRaises(subprocess.CalledProcessError) as error:
                self.exercise(root, ('dump/run.sh',), verify_exit=7)
            self.assertEqual(error.exception.returncode, 7)
            self.assertFalse((root/'work/build').exists())

    def test_nonexecutable_entry_fails_before_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with self.assertRaisesRegex(SystemExit, 'regular executable'):
                self.exercise(root, ('dump/run.sh',), executable=False)
            self.assertFalse((root/'work/build').exists())

    def test_raw_dump_preserves_doctor_build_verify_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            work, calls = self.exercise(Path(tmp).resolve())
            self.assertEqual([args[2] for args in calls[2:4]], ['doctor', 'build'])
            self.assertEqual(calls[-1], [str(work/'build/package/run.sh'), '--verify'])
            self.assertEqual((work/'build/package/verified.txt').read_text(), '--verify\n')
