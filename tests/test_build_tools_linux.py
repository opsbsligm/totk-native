"""Exercise the real shader worker protocol with tiny synthetic fixtures, no game shaders."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class ShaderWorkerFailure(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='shader-protocol-',dir=Path.cwd())
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'jobs.jsonl').write_text(json.dumps({'job':{'key':'synthetic-fixture'}})+'\n')
        self.translator=self.root/'translator'

    def run_worker(self,code):
        self.translator.write_text('#!'+sys.executable+'\n'+code)
        self.translator.chmod(0o700)
        env=dict(os.environ,ULTRS_SHADER_TRANSLATOR=str(self.translator))
        return subprocess.run([sys.executable,str(ROOT/'tools/run_ryujinx_xlate.py'),str(self.root),'--workers','1'],
                              env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=15)

    def test_process_failure_is_not_reported_as_success(self):
        result=self.run_worker('import sys\nfor line in sys.stdin:\n print("fail synthetic-fixture test",flush=True)\n sys.exit(7)\n')
        self.assertNotEqual(result.returncode,0,result.stdout)

    def test_ok_reply_without_output_is_failure(self):
        result=self.run_worker('import sys\nfor line in sys.stdin:\n print("ok synthetic-fixture",flush=True)\n')
        self.assertNotEqual(result.returncode,0,result.stdout)
        self.assertIn('incomplete',result.stdout)

    def test_worker_writes_result_only_for_existing_output(self):
        fixture=self.root/'translated/synthetic-fixture.spv'
        code='import sys\nfrom pathlib import Path\nfor line in sys.stdin:\n'
        code+=' Path('+repr(str(fixture))+').write_bytes(b"synthetic-protocol-fixture")\n'
        code+=' print("ok synthetic-fixture",flush=True)\n'
        result=self.run_worker(code)
        self.assertEqual(result.returncode,0,result.stdout)
        self.assertIn('\tok\t',(self.root/'translate-results.tsv').read_text())


if __name__=='__main__':
    unittest.main(verbosity=2)
