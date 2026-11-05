"""Shared source packages remain usable after extraction without Git metadata."""
import importlib.util
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('source_tree', ROOT / 'tools/source_tree.py')
source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source)


class SourceArchive(unittest.TestCase):
    def test_export_without_git_metadata_and_detect_source_changes(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            task = Path(tmp)
            checkout = task / 'checkout'
            checkout.mkdir()
            subprocess.run(['git', 'init', '-q', '-b', 'main', str(checkout)], check=True)
            (checkout / 'hello.py').write_text('print(1)\n')
            subprocess.run(['git', '-C', str(checkout), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(checkout), '-c', 'user.name=Codex Agent',
                '-c', 'user.email=codex-agent@example.local', 'commit', '-qm', 'synthetic source fixture'], check=True)
            revision = source.revision(checkout)
            package = task / 'source.tar.gz'
            source.archive_sources(checkout, package)
            extracted = task / 'extracted'
            extracted.mkdir()
            with tarfile.open(package) as archive:
                archive.extractall(extracted, filter='data')
            self.assertFalse((extracted / '.git').exists())
            self.assertEqual(source.revision(extracted), revision)
            self.assertEqual(source.source_files(extracted), ['hello.py'])
            (extracted / 'hello.py').write_text('print(2)\n')
            with self.assertRaisesRegex(ValueError, 'changed'):
                source.source_files(extracted)
            (extracted / 'hello.py').write_text('print(1)\n')
            (extracted / 'extra.py').write_text('print(3)\n')
            with self.assertRaisesRegex(ValueError, 'inventory'):
                source.source_files(extracted)
