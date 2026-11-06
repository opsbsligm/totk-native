"""Exercise production event registry and real kernel Create/Close SVCs."""
from pathlib import Path
import subprocess,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
@unittest.skipUnless(sys.platform=='linux','Linux host runtime')
class SystemEventLifecycle(unittest.TestCase):
    def test_destroy_rebind_recycled_handle_and_host_notification(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            exe=Path(temp)/'check'
            subprocess.run(['clang','-std=gnu17','-O1','-ffunction-sections','-fdata-sections','-pthread',str(ROOT/'tests/system_event_lifecycle_test.c'),'-Wl,--gc-sections','-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True,timeout=10)
