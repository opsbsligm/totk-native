"""Run the production importer and VM against bounded synthetic main/heap memory."""
from pathlib import Path
import subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
HOST=ROOT/('src/host' if (ROOT/'src/host').is_dir() else 'runtime')
class Atmosphere(unittest.TestCase):
    def test_import_bounds_control_flow_pointer_and_fault_isolation(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            p=Path(tmp);exe=p/'check'
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pthread','-I',str(HOST),str(ROOT/'tests/native_atmosphere_test.c'),str(HOST/'native_atmosphere.c'),'-o',str(exe)],check=True)
            subprocess.run([str(exe),str(p)],check=True,timeout=10)
