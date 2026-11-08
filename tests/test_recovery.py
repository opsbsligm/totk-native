"""Validate archive/part boundaries before any decryption or filesystem install."""
import importlib.util
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('recovery',ROOT/'tools/recovery.py')
recovery=importlib.util.module_from_spec(spec);spec.loader.exec_module(recovery)
transport_spec=importlib.util.spec_from_file_location('recovery_transport',ROOT/'tools/recovery_gitlab.py')
transport=importlib.util.module_from_spec(transport_spec);transport_spec.loader.exec_module(transport)
MISSING=object()


def byte_relay(root):
    # Archive/permission tests only; the private integration uses real age.
    relay=root/'byte-relay'
    relay.write_text('#!/bin/sh\nif [ "$1" = "-R" ]; then cat > "$4"; else cat; fi\n')
    relay.chmod(0o700)
    return relay


def fixture_bundle(root,index_schema=3,manifest_schema=3,mode=MISSING,path='runtime/run.sh'):
    bundle=root/'bundle';bundle.mkdir()
    data=b'#!/bin/sh\nexit 0\n'
    record=dict(path=path,bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
    if mode is not MISSING:record['mode']=mode
    manifest=dict(schema=manifest_schema,files=[record],missing=[])
    if manifest_schema==3:manifest['kind']='native-recovery-bundle'
    raw=io.BytesIO()
    with tarfile.open(fileobj=raw,mode='w') as archive:
        entry=tarfile.TarInfo(path);entry.size=len(data);entry.mode=0o7777
        archive.addfile(entry,io.BytesIO(data))
        payload=json.dumps(manifest).encode();entry=tarfile.TarInfo('manifest.json');entry.size=len(payload)
        archive.addfile(entry,io.BytesIO(payload))
    payload=gzip.compress(raw.getvalue());name='payload-00000.age.part';(bundle/name).write_bytes(payload)
    index=dict(schema=index_schema,cipher='age',input_bytes=len(data),parts=[dict(name=name,bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest())])
    if index_schema==3:index['kind']='native-recovery-bundle'
    elif index_schema==2:index['kind']='native-recovery-set'
    (bundle/'index.json').write_text(json.dumps(index))
    return bundle,data


class Recovery(unittest.TestCase):
    def test_portable_runtime_entry_remains_executable_after_roundtrip(self):
        # A test-only byte relay isolates archive/mode behavior. This is not a
        # cryptographic authentication test; private integration uses real age.
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root=Path(tmp);source=root/'input';source.mkdir();bundle=root/'bundle';output=root/'restored'
            entry=source/'run.sh';entry.write_text('#!/bin/sh\nprintf "portable-runtime-ok\\n"\n');entry.chmod(0o755)
            data=source/'settings.ini';data.write_text('fps=60\n');data.chmod(0o600)
            relay=byte_relay(root)
            with patch.object(recovery,'age_tool',return_value=str(relay)):
                recovery.seal(SimpleNamespace(destination=str(bundle),include=['runtime='+str(source)],label='synthetic-runtime',missing=[],recipients='unused'))
                recovery.restore(SimpleNamespace(bundle=str(bundle),identity='unused',destination=str(output),max_bytes=1024**2))
            restored=output/'runtime/run.sh'
            self.assertEqual(subprocess.check_output([str(restored)],text=True),'portable-runtime-ok\n')
            self.assertEqual(restored.stat().st_mode & 0o7777,0o700)
            self.assertEqual((output/'runtime/settings.ini').stat().st_mode & 0o7777,0o600)
            self.assertEqual((output/'runtime/settings.ini').read_bytes(),data.read_bytes())
            self.assertEqual(entry.stat().st_mode & 0o7777,0o755)

    def test_legacy_bundle_recovers_bytes_without_guessing_executable_bits(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root=Path(tmp);bundle,data=fixture_bundle(root,1,1);output=root/'out'
            with patch.object(recovery,'age_tool',return_value=str(byte_relay(root))):
                recovery.restore(SimpleNamespace(bundle=str(bundle),identity='unused',destination=str(output),max_bytes=1024**2))
            self.assertEqual((output/'runtime/run.sh').read_bytes(),data)
            self.assertEqual((output/'runtime/run.sh').stat().st_mode & 0o7777,0o600)
            self.assertEqual((output/'recovery-receipt.json').stat().st_mode & 0o7777,0o600)

    def test_invalid_permissions_or_payload_schemas_never_install_a_tree(self):
        cases=[(3,3,value) for value in (0o755,0o4755,True,'0700',None,MISSING)]
        cases += [(1,3,0o700),(3,1,MISSING),(2,3,0o700)]
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root=Path(tmp);relay=byte_relay(root)
            for i,(outer,inner,mode) in enumerate(cases):
                with self.subTest(index=outer,manifest=inner,mode=repr(mode)):
                    case=root/str(i);case.mkdir();bundle,_=fixture_bundle(case,outer,inner,mode);output=case/'out'
                    with patch.object(recovery,'age_tool',return_value=str(relay)),self.assertRaisesRegex(ValueError,'permission|schema|manifest'):
                        recovery.restore(SimpleNamespace(bundle=str(bundle),identity='unused',destination=str(output),max_bytes=1024**2))
                    self.assertFalse(output.exists())
                    self.assertEqual(list(case.glob('.recovery-restore-*')),[])

    def test_new_permission_bundle_survives_publish_and_fetch_transport(self):
        # In-memory transport exercises format compatibility and byte readback;
        # it does not authenticate to a real GitLab or access a real token.
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root=Path(tmp);bundle,_=fixture_bundle(root,mode=0o700);remote={}
            class API:
                def put(self,path,file):remote[path]=file.read_bytes()
                def get(self,path,output=None,limit=1024**4):
                    data=remote[path]
                    if len(data)>limit:raise ValueError('Fixture exceeds requested limit')
                    if output:
                        output.write(data);return len(data),hashlib.sha256(data).hexdigest()
                    return data
            common=['--url','https://fixture.invalid','--project','21','--version','owner-exec','--token-file','unused']
            previous_umask=os.umask(0o077)
            try:
                with patch.object(transport,'GitLab',return_value=API()):
                    with patch.object(sys,'argv',['recovery_gitlab.py','publish',*common,'--bundle',str(bundle)]):transport.main()
                    downloaded=root/'downloaded'
                    with patch.object(sys,'argv',['recovery_gitlab.py','fetch',*common,'--bundle',str(downloaded)]):transport.main()
            finally:
                os.umask(previous_umask)
            self.assertEqual({p.name:p.read_bytes() for p in bundle.iterdir()},{p.name:p.read_bytes() for p in downloaded.iterdir()})
            output=root/'out'
            with patch.object(recovery,'age_tool',return_value=str(byte_relay(root))):
                recovery.restore(SimpleNamespace(bundle=str(downloaded),identity='unused',destination=str(output),max_bytes=1024**2))
            self.assertEqual((output/'runtime/run.sh').stat().st_mode & 0o7777,0o700)

    def test_reserved_receipt_cannot_replace_an_authenticated_member(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root=Path(tmp);relay=byte_relay(root)
            for i,name in enumerate(('recovery-receipt.json','Recovery-Receipt.json')):
                with self.subTest(member=name):
                    case=root/str(i);case.mkdir();bundle,_=fixture_bundle(case,1,1,path=name);output=case/'out'
                    with patch.object(recovery,'age_tool',return_value=str(relay)),self.assertRaisesRegex(ValueError,'Reserved'):
                        recovery.restore(SimpleNamespace(bundle=str(bundle),identity='unused',destination=str(output),max_bytes=1024**2))
                    self.assertFalse(output.exists())

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
