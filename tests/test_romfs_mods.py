"""Read actual nn::fs overrides using synthetic Linux files, including hostile entries."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux read-only RomFS mods')
class RomfsMods(unittest.TestCase):
    def test_production_reads_and_descriptor_boundaries(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            binary = Path(folder) / 'romfs-mods'
            subprocess.run([shutil.which('clang') or 'cc', '-O1', '-ffunction-sections', '-fdata-sections',
                '-Wl,--gc-sections', '-include', str(ROOT / 'src/runtime/platform/linux_compat.h'),
                '-I' + str(ROOT / 'src/runtime'), '-I' + str(ROOT / 'src/host'),
                str(ROOT / 'tests/test_romfs_mods.c'), '-pthread', '-o', str(binary)], check=True)
            for mode in ('folder', 'image'):
                with self.subTest(mode=mode):
                    state = Path(folder) / mode
                    state.mkdir()
                    subprocess.run([str(binary), *(['image'] if mode == 'image' else [])],
                                   cwd=state, check=True, timeout=15)
