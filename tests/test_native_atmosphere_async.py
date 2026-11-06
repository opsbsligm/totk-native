"""Stall the actual file read while exercising real VM/UI APIs."""
from pathlib import Path
import subprocess,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
HOST=ROOT/('src/host' if (ROOT/'src/host').is_dir() else 'runtime')
@unittest.skipUnless(sys.platform=='linux','Linux linker read-wrapper and VM backend')
class AsyncImport(unittest.TestCase):
    def test_slow_read_does_not_hold_frame_lock_and_stale_import_cannot_commit(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            p=Path(temp);exe=p/'check'
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pthread','-I',str(HOST),str(ROOT/'tests/native_atmosphere_async_test.c'),str(HOST/'native_atmosphere.c'),'-Wl,--wrap=read','-o',str(exe)],check=True)
            subprocess.run([str(exe),str(p)],check=True,timeout=10)
