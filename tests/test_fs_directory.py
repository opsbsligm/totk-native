"""A resolved path must fit the persistent directory-handle record."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux host filesystem regression')
class DirectoryCapacity(unittest.TestCase):
    def test_existing_long_directory_does_not_corrupt_handle(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            work = Path(folder)
            binary = work / 'directory-capacity'
            subprocess.run([shutil.which('clang') or 'cc', '-O1', '-ffunction-sections', '-fdata-sections',
                '-Wl,--gc-sections', '-include', str(ROOT / 'src/runtime/platform/linux_compat.h'),
                '-I' + str(ROOT / 'src/runtime'), '-I' + str(ROOT / 'src/host'),
                str(ROOT / 'tests/test_fs_directory.c'), '-pthread', '-o', str(binary)], check=True)
            directory = work / 'directories'
            directory.mkdir()
            subprocess.run([str(binary), str(directory)], check=True)


if __name__ == '__main__':
    unittest.main()
