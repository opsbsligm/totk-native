"""Exercise the production font opener against real Linux descriptors."""
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FontFiles(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'linux', 'Linux read-only font loader regression')
    def test_hash_binding_offsets_changed_size_and_descriptor_lifetime(self):
        flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', 'openssl'], text=True))
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            exe = Path(directory) / 'font-files'
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-I', str(ROOT / 'src/host'),
                '-I', str(ROOT / 'src/runtime'), str(ROOT / 'tests/deck_font_files_test.c'), '-o', str(exe), *flags], check=True)
            subprocess.run([str(exe)], cwd=directory, check=True, timeout=15)
