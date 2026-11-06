"""Verify the live Linux kernel copy path, permissions, atomic-page guard and fd lifetime."""
from pathlib import Path
import subprocess,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
HOST=ROOT/('src/host' if (ROOT/'src/host').is_dir() else 'runtime')
class KernelMemory(unittest.TestCase):
    @unittest.skipUnless(sys.platform=='linux','Linux uaccess permission regression')
    def test_kernel_copy_permissions_bad_pages_unaligned_values_and_no_fd_leaks(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            exe=Path(temp)/'memory-check'
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(HOST),str(ROOT/'tests/native_memory_test.c'),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True,timeout=15)
