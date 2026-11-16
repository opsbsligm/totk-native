"""Stream lifecycle and disk-budget tests; byte relays do not prove encryption."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_recovery import recovery, fixture_bundle


def relay(root, fail_pass=0, encrypt_fail=False):
    path = root/'relay.py'
    path.write_text('#!'+sys.executable+'\n'+'''import pathlib, sys
args=sys.argv[1:]
if args[0]=='-R':
    target=open(args[args.index('-o')+1],'wb') if '-o' in args else sys.stdout.buffer
    while data:=sys.stdin.buffer.read(4096): target.write(data)
    target.flush()
    sys.exit(ENCRYPT_FAIL)
count=pathlib.Path(__file__).with_suffix('.count')
n=int(count.read_text())+1 if count.exists() else 1
count.write_text(str(n))
while data:=sys.stdin.buffer.read(4096): sys.stdout.buffer.write(data)
sys.stdout.buffer.flush()
sys.exit(7 if n==FAIL_PASS else 0)
'''.replace('ENCRYPT_FAIL', str(int(encrypt_fail))).replace('FAIL_PASS', str(fail_pass)))
    path.chmod(0o700)
    return path


def seal_args(source, bundle, low_peak=True):
    return SimpleNamespace(destination=str(bundle), include=['runtime='+str(source)],
                           label='stream-fixture', missing=[], recipients='unused', low_peak=low_peak)


def restore_args(bundle, output, low_peak=True):
    return SimpleNamespace(bundle=str(bundle), identity='unused', destination=str(output),
                           max_bytes=4*1024**2, low_peak=low_peak)


class StreamingRecovery(unittest.TestCase):
    def assert_clean(self, root, output):
        self.assertFalse(output.exists())
        self.assertFalse(list(root.glob('.recovery-*')))
        self.assertFalse([t for t in threading.enumerate() if t.name=='recovery-age-input'])

    def test_multipart_roundtrip_and_legacy_compatibility_both_directions(self):
        for stream_seal, stream_restore in ((True,True),(True,False),(False,True)):
            with self.subTest(seal=stream_seal, restore=stream_restore), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);source=root/'input';source.mkdir();entry=source/'run.sh'
                entry.write_text('#!/bin/sh\nexit 0\n');entry.chmod(0o755)
                data=os.urandom(180000);(source/'data.bin').write_bytes(data)
                bundle=root/'bundle';output=root/'output'
                with patch.object(recovery,'age_tool',return_value=str(relay(root))), patch.object(recovery,'CHUNK',65536):
                    recovery.seal(seal_args(source,bundle,stream_seal))
                    self.assertGreater(len(json.loads((bundle/'index.json').read_text())['parts']),2)
                    self.assertFalse((bundle/'payload.age').exists())
                    recovery.restore(restore_args(bundle,output,stream_restore))
                self.assertEqual((output/'runtime/data.bin').read_bytes(),data)
                self.assertEqual((output/'runtime/run.sh').stat().st_mode & 0o7777,0o700)
                subprocess.run([str(output/'runtime/run.sh')],check=True)
                self.assertFalse(list(root.glob('.recovery-*')))
                self.assertEqual((root/'relay.count').read_text(),'2' if stream_restore else '1')

    def test_first_authentication_failure_creates_no_extraction_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bundle,_=fixture_bundle(root,mode=0o700);output=root/'out'
            with patch.object(recovery,'age_tool',return_value=str(relay(root,fail_pass=1))), \
                 patch.object(recovery.tempfile,'mkdtemp',side_effect=AssertionError('must not extract')), \
                 self.assertRaisesRegex(ValueError,'age failed'):
                recovery.restore(restore_args(bundle,output))
            self.assert_clean(root,output)

    def test_second_authentication_failure_never_publishes_complete_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bundle,_=fixture_bundle(root,mode=0o700);output=root/'out'
            with patch.object(recovery,'age_tool',return_value=str(relay(root,fail_pass=2))), self.assertRaisesRegex(ValueError,'age failed'):
                recovery.restore(restore_args(bundle,output))
            self.assert_clean(root,output)

    def test_ciphertext_change_between_authenticated_passes_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bundle,_=fixture_bundle(root,mode=0o700);output=root/'out'
            original=recovery.age_pipe;calls=0
            def change_after_auth(*args):
                nonlocal calls
                result=original(*args);calls+=1
                if calls==1:
                    part=bundle/'payload-00000.age.part';raw=part.read_bytes()
                    part.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
                return result
            with patch.object(recovery,'age_tool',return_value=str(relay(root))), \
                 patch.object(recovery,'age_pipe',side_effect=change_after_auth), self.assertRaises((ValueError,EOFError)):
                recovery.restore(restore_args(bundle,output))
            self.assert_clean(root,output)

    def test_low_peak_budget_still_rejects_insufficient_space(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'input';source.mkdir();(source/'data').write_bytes(b'x'*10000)
            free=1024**3+15000
            with patch.object(recovery.shutil,'disk_usage',return_value=SimpleNamespace(free=free)), \
                 patch.object(recovery,'age_tool',return_value=str(relay(root))):
                with self.assertRaisesRegex(ValueError,'free space'):
                    recovery.seal(seal_args(source,root/'legacy',False))
                recovery.seal(seal_args(source,root/'stream'))
                with self.assertRaisesRegex(ValueError,'free space'):
                    recovery.restore(restore_args(root/'stream',root/'legacy-out',False))
                recovery.restore(restore_args(root/'stream',root/'stream-out'))
            with patch.object(recovery.shutil,'disk_usage',return_value=SimpleNamespace(free=1024**3+9999)), \
                 self.assertRaisesRegex(ValueError,'free space'):
                recovery.restore(restore_args(root/'stream',root/'small-out'))
            self.assert_clean(root,root/'small-out')

    def test_understated_index_cannot_exceed_the_space_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bundle,_=fixture_bundle(root,mode=0o700);output=root/'out'
            index=json.loads((bundle/'index.json').read_text());index['input_bytes']=0
            (bundle/'index.json').write_text(json.dumps(index))
            with patch.object(recovery,'age_tool',return_value=str(relay(root))), self.assertRaisesRegex(ValueError,'byte budget'):
                recovery.restore(restore_args(bundle,output))
            self.assert_clean(root,output)

    def test_encryption_failure_does_not_publish_partial_parts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'input';source.mkdir();(source/'data').write_bytes(b'x'*10000)
            with patch.object(recovery,'age_tool',return_value=str(relay(root,encrypt_fail=True))), self.assertRaisesRegex(ValueError,'age failed'):
                recovery.seal(seal_args(source,root/'bundle'))
            self.assert_clean(root,root/'bundle')

    def test_output_error_stops_age_and_joins_input_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def produce(stream):
                for _ in range(10000):stream.write(b'x'*4096)
            def fail_output(stream):
                stream.read(1)
                raise OSError('simulated disk full')
            with self.assertRaisesRegex(OSError,'disk full'):
                recovery.age_pipe([str(relay(root)),'-R','unused'],produce,fail_output)
            self.assert_clean(root,root/'unused')

    def test_early_age_rejection_reports_failure_instead_of_a_broken_pipe(self):
        def produce(stream):
            for _ in range(10000):stream.write(b'x'*4096)
        with self.assertRaisesRegex(ValueError,'age failed'):
            recovery.age_pipe([sys.executable,'-c','import sys; sys.exit(7)'],
                              produce,lambda stream: None)
        self.assertFalse([t for t in threading.enumerate() if t.name=='recovery-age-input'])
