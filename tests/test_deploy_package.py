"""Release installation must refuse unverified packages and keep a rollback path."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('deploy_package', ROOT / 'tools/deploy_package.py')
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_package(root, binary, commit, extras=()):
    """Build a package whose manifest lists every other file, as packaging does."""
    if root.exists():
        raise ValueError('package staging root must be fresh: ' + str(root))
    (root / 'data').mkdir(parents=True)
    (root / 'data/romfs.bin').write_bytes(b'world data')
    (root / 'ultratears').write_bytes(binary)
    for relative, payload in extras:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    files = {path.relative_to(root).as_posix(): dict(size=path.stat().st_size, sha256=digest(path))
             for path in sorted(root.rglob('*')) if path.is_file()}
    (root / 'bundle.json').write_text(json.dumps(dict(schema=1, source_commit=commit,
        version='1.4.3', private_game_content=True, hardware_validated=False, files=files), indent=2))
    return root


class DeployPackage(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.base = Path(self._tmp.name)
        self.root = self.base / 'deck'
        (self.root / 'releases').mkdir(parents=True)
        self.sequence = 0

    def tearDown(self):
        self._tmp.cleanup()

    def package(self, binary=b'\x7fELF first', commit='a' * 40, extras=()):
        self.sequence += 1
        return write_package(self.base / ('pkg%d' % self.sequence), binary, commit, extras)

    def current(self):
        return os.readlink(self.root / 'current')

    def test_first_install_moves_everything_and_links_current(self):
        package = self.package()
        target, previous, counts = deploy.install(package, self.root, 'r1')
        self.assertEqual(self.current(), 'releases/r1')
        self.assertIsNone(previous)
        self.assertEqual((counts['linked'], counts['moved']), (0, 3))
        self.assertTrue((target / 'data/romfs.bin').is_file())
        self.assertFalse(package.exists(), 'the package must be consumed, not copied')
        self.assertEqual((self.root / 'previous').read_text().strip(), '')

    def test_unchanged_game_data_is_hardlinked_from_the_release_being_replaced(self):
        deploy.install(self.package(), self.root, 'r1')
        inode = (self.root / 'releases/r1/data/romfs.bin').stat().st_ino
        target, previous, counts = deploy.install(
            self.package(b'\x7fELF second'), self.root, 'r2', self.root / 'current')
        self.assertEqual(previous, 'releases/r1')
        self.assertEqual(counts['linked'], 1, 'identical game data must not be stored twice')
        self.assertEqual(counts['moved'], 2, 'the manifest and new binary must be moved')
        self.assertEqual((target / 'data/romfs.bin').stat().st_ino, inode)
        self.assertEqual(self.current(), 'releases/r2')

    def test_tampered_package_is_refused_before_anything_moves(self):
        package = self.package()
        (package / 'data/romfs.bin').write_bytes(b'replaced while copying')
        with self.assertRaisesRegex(ValueError, 'changed since packaging'):
            deploy.install(package, self.root, 'r1')
        self.assertTrue((package / 'bundle.json').is_file(), 'inputs must survive a refusal')
        self.assertFalse((self.root / 'releases/r1').exists())
        self.assertFalse((self.root / 'current').exists())

    def test_unexpected_file_in_package_is_refused(self):
        package = self.package()
        (package / 'screenshot.png').write_bytes(b'\x89PNG')
        with self.assertRaisesRegex(ValueError, 'inventory differs'):
            deploy.install(package, self.root, 'r1')
        self.assertTrue((package / 'bundle.json').is_file())

    def test_rollback_restores_the_previous_release_and_can_be_undone(self):
        deploy.install(self.package(), self.root, 'r1')
        deploy.install(self.package(b'\x7fELF second'), self.root, 'r2', self.root / 'current')
        restored, left = deploy.rollback(self.root)
        self.assertEqual(self.current(), 'releases/r1')
        self.assertEqual((restored.name, left), ('r1', 'releases/r2'))
        deploy.rollback(self.root)  # the marker swaps, so this returns to r2
        self.assertEqual(self.current(), 'releases/r2')

    def test_rollback_refuses_when_the_previous_release_is_gone(self):
        deploy.install(self.package(), self.root, 'r1')
        deploy.install(self.package(b'\x7fELF second'), self.root, 'r2', self.root / 'current')
        (self.root / 'releases/r1/bundle.json').unlink()
        with self.assertRaisesRegex(ValueError, 'Previous release is gone'):
            deploy.rollback(self.root)
        self.assertEqual(self.current(), 'releases/r2', 'a failed rollback must not move the link')

    def test_reinstalling_the_same_release_happy_path_is_idempotent(self):
        deploy.install(self.package(), self.root, 'r1')
        twin = self.package()
        _, _, counts = deploy.install(twin, self.root, 'r1')
        self.assertEqual(counts.get('identical'), 1)
        self.assertFalse(twin.exists())
        self.assertEqual(self.current(), 'releases/r1')

    def test_reusing_a_release_id_for_different_content_is_refused(self):
        deploy.install(self.package(), self.root, 'r1')
        with self.assertRaisesRegex(ValueError, 'different content'):
            deploy.install(self.package(b'\x7fELF second'), self.root, 'r1')
        self.assertEqual(self.current(), 'releases/r1')

    def test_release_id_cannot_escape_the_release_directory(self):
        for bad in ('', '.', '..', '../outside', 'nested/id', '.hidden'):
            with self.subTest(bad):
                with self.assertRaisesRegex(ValueError, 'Invalid release id'):
                    deploy.install(self.package(), self.root, bad)
        self.assertEqual(list((self.root / 'releases').iterdir()), [])


if __name__ == '__main__':
    unittest.main()
