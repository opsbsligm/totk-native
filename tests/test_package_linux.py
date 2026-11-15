"""Read-only inputs and staging identity must survive private packaging failures."""
from pathlib import Path
import stat
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import package_linux as package


class PackageDirectories(unittest.TestCase):
    def test_readonly_source_is_unchanged_and_output_allows_append_and_cleanup(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder); source = root/'input'; source.mkdir()
            child = source/'nested'; child.mkdir(); resource = child/'license.txt'
            resource.write_bytes(b'original synthetic license'); resource.chmod(0o444)
            child.chmod(0o555); source.chmod(0o555)
            output = root/'package.new'
            try:
                package.copy_tree(source, output)
                self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o555)
                self.assertEqual(stat.S_IMODE(child.stat().st_mode), 0o555)
                self.assertEqual(resource.read_bytes(), b'original synthetic license')
                for path in (output, output/'nested'):
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode) & 0o700, 0o700)
                (output/'nested'/'additional.txt').write_bytes(b'new output only')
                identity = (output.stat().st_dev, output.stat().st_ino)
                (output/'nested').chmod(0o500)
                self.assertTrue(package.discard_staging(output, identity))
                self.assertFalse(output.exists())
                self.assertEqual(resource.read_bytes(), b'original synthetic license')
            finally:
                source.chmod(0o700); child.chmod(0o700)

    def test_replaced_staging_and_symlink_never_remove_the_retained_tree(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder); staging = root/'package.new'; staging.mkdir()
            (staging/'unique.txt').write_bytes(b'preserve')
            identity = (staging.stat().st_dev, staging.stat().st_ino)
            retained = root/'retained'; staging.rename(retained)
            staging.mkdir(); (staging/'other.txt').write_bytes(b'another writer')
            self.assertFalse(package.discard_staging(staging, identity))
            self.assertEqual((staging/'other.txt').read_bytes(), b'another writer')
            (staging/'other.txt').unlink(); staging.rmdir()
            staging.symlink_to(retained, target_is_directory=True)
            self.assertFalse(package.discard_staging(staging, identity))
            self.assertEqual((retained/'unique.txt').read_bytes(), b'preserve')
            staging.unlink()
