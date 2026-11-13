"""Exercise restored entry selection with real verification subprocesses.

Only transport and decryption boundaries are replaced by authenticated-layout
fixtures here. Private recovery exercises cover the real age authentication.
"""
import importlib.util
import hashlib
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
    def exercise(self, root, entries=(), missing=(), verify_exit=0, executable=True,
                 separate_encrypted=False, encrypted_path=None, recovery_set=False,
                 encrypted_free=200*1024**3, work_path=None):
        spec = importlib.util.spec_from_file_location('private_rebuild_entry', ROOT/'tools/rebuild_private.py')
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        work = work_path or root/'work'
        encrypted = encrypted_path
        if separate_encrypted:
            (root/'external-volume').mkdir(exist_ok=True)
            encrypted = encrypted or root/'external-volume/cipher'
        component_index = json.dumps(dict(schema=3, kind='native-recovery-bundle'))
        component_sha = hashlib.sha256(component_index.encode()).hexdigest()
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
                bundle = Path(args[args.index('--bundle')+1])
                bundle.mkdir()
                if recovery_set and bundle.name == 'encrypted':
                    layout = dict(schema=2, kind='native-recovery-set', components=[
                        dict(role=role, version='fixture-'+role, index_sha256=component_sha)
                        for role in ('base','fonts','romfs')])
                    (bundle/'index.json').write_text(json.dumps(layout))
                else:
                    (bundle/'index.json').write_text(component_index)
            elif len(args) > 2 and args[1].endswith('/recovery.py'):
                self.assertEqual(args[2], 'restore')
                restored = Path(args[args.index('--destination')+1])
                role = restored.name.removeprefix('restored-')
                if role in ('fonts','romfs'):
                    (restored/role).mkdir(parents=True)
                    (restored/role/'fixture.dat').write_bytes(role.encode())
                    (restored/'recovery-receipt.json').write_text(json.dumps(dict(missing=[])))
                else:
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
        if encrypted is not None:
            argv += ['--encrypted-work', str(encrypted)]
        def disk_usage(path):
            free = encrypted_free if Path(path) == root/'external-volume' else 200*1024**3
            return SimpleNamespace(free=free)
        previous_umask = os.umask(0o077)
        try:
            with patch.object(tool, 'subprocess', SimpleNamespace(run=boundary)), \
                 patch.object(tool, 'shutil', SimpleNamespace(disk_usage=disk_usage)), \
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

    def test_external_ciphertext_keeps_plaintext_and_execution_on_work_volume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            work, calls = self.exercise(root, ('dump/run.sh',), separate_encrypted=True)
            cipher = root/'external-volume/cipher'
            self.assertTrue((cipher/'encrypted/index.json').is_file())
            self.assertFalse((work/'encrypted').exists())
            self.assertFalse((cipher/'restored').exists())
            self.assertEqual(calls[0][calls[0].index('--bundle')+1], str(cipher/'encrypted'))
            self.assertEqual(calls[1][calls[1].index('--destination')+1], str(work/'restored'))
            self.assertEqual((work/'restored/dump/verified.txt').read_text(), '--verify\n')

    def test_external_ciphertext_applies_to_every_set_component(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            work, calls = self.exercise(root, ('dump/run.sh',), separate_encrypted=True,
                                       recovery_set=True,
                                       missing=('system-shared-fonts-6','healthy-complete-romfs'))
            cipher = root/'external-volume/cipher'
            fetches = [a for a in calls if len(a)>2 and a[1].endswith('/recovery_gitlab.py')]
            self.assertEqual({Path(a[a.index('--bundle')+1]) for a in fetches},
                             {cipher/n for n in ('encrypted','encrypted-base','encrypted-fonts','encrypted-romfs')})
            self.assertEqual(len(calls), 8)
            self.assertEqual((work/'restored/dump/fonts/fixture.dat').read_bytes(), b'fonts')
            self.assertEqual((work/'restored/dump/romfs/fixture.dat').read_bytes(), b'romfs')
            self.assertEqual((work/'restored/dump/verified.txt').read_text(), '--verify\n')
            self.assertFalse((cipher/'restored').exists())

    def test_external_ciphertext_rejects_overlap_before_creating_work(self):
        for relative, work_relative in [('work','work'),('work/cipher','work'),('outer','outer/work')]:
            with self.subTest(path=relative), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                with self.assertRaisesRegex(SystemExit, '2'):
                    self.exercise(root, encrypted_path=root/relative, work_path=root/work_relative)
                self.assertFalse((root/work_relative).exists())

    def test_external_ciphertext_rejects_existing_or_symlink_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve();cipher = root/'cipher';cipher.mkdir()
            (cipher/'keep.txt').write_text('preserve')
            with self.assertRaises(SystemExit):
                self.exercise(root, encrypted_path=cipher)
            self.assertEqual((cipher/'keep.txt').read_text(), 'preserve')
            self.assertFalse((root/'work').exists())
            (root/'linked').symlink_to(cipher, target_is_directory=True)
            with self.assertRaises(SystemExit):
                self.exercise(root, encrypted_path=root/'linked/new')
            self.assertFalse((root/'work').exists())
            self.assertFalse((cipher/'new').exists())

    def test_external_ciphertext_rejects_source_tree_and_insufficient_space(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with self.assertRaises(SystemExit):
                self.exercise(root, encrypted_path=ROOT/'unused-cipher-output')
            self.assertFalse((root/'work').exists())
            with self.assertRaises(SystemExit):
                self.exercise(root, separate_encrypted=True, encrypted_free=512*1024**2)
            self.assertFalse((root/'work').exists())
            self.assertFalse((root/'external-volume/cipher').exists())

    def test_output_parent_traversal_is_rejected_before_creating_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with self.assertRaises(SystemExit):
                self.exercise(root, encrypted_path=root/'outside/../work')
            with self.assertRaises(SystemExit):
                self.exercise(root, work_path=root/'outside/../work', separate_encrypted=True)
            self.assertFalse((root/'work').exists())
            self.assertFalse((root/'outside').exists())
            self.assertFalse((root/'external-volume/cipher').exists())
