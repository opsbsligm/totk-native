"""Check real receipt/source files and reject stale or redirected SDK inputs."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_toolchain', ROOT / 'tools/check_toolchain.py')
toolchain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(toolchain)


class ToolchainReceipt(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name) / 'source'
        self.root.mkdir()
        self.recipe_path = self.root / '.gitlab/ci-toolchain-recipe.json'
        self.receipt = Path(self.folder.name) / 'receipt.json'
        names = ['Dockerfile', 'tools/build_deps.sh', 'requirements-build.lock', '.gitlab/install_compiler_rt.py']
        for name in names:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('public synthetic input: ' + name + '\n')
        self.recipe = {'schema': 1, 'source_inputs': {
            name: hashlib.sha256((self.root / name).read_bytes()).hexdigest() for name in names[:3]},
            'delta': {'installer_path': names[3],
                      'installer_sha256': hashlib.sha256((self.root / names[3]).read_bytes()).hexdigest()}}
        self.publish()

    def publish(self):
        raw = (json.dumps(self.recipe, sort_keys=True) + '\n').encode()
        self.recipe_path.write_bytes(raw)
        self.digest = hashlib.sha256(raw).hexdigest()
        self.receipt.write_text(json.dumps({'schema': 1, 'recipe': self.recipe, 'recipe_sha256': self.digest}))

    def verify(self, required=True):
        return toolchain.verify_receipt(self.root, self.receipt, required)

    def test_exact_receipt_and_optional_source_build(self):
        self.assertEqual(self.verify(), self.digest)
        self.receipt.unlink()
        self.assertIsNone(self.verify(False))
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.verify()

    def test_receipt_mismatch_and_changed_source_inputs(self):
        self.receipt.write_text(json.dumps({'schema': 1, 'recipe': self.recipe, 'recipe_sha256': '0' * 64}))
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.verify()
        self.publish()
        for name in [*self.recipe['source_inputs'], self.recipe['delta']['installer_path']]:
            path = self.root / name
            before = path.read_bytes()
            path.write_bytes(before + b'changed\n')
            with self.assertRaisesRegex(ValueError, 'input changed'):
                self.verify()
            path.write_bytes(before)

    def test_receipt_and_input_symlinks_are_rejected(self):
        alternate = self.receipt.with_name('alternate.json')
        self.receipt.rename(alternate)
        self.receipt.symlink_to(alternate)
        with self.assertRaisesRegex(ValueError, 'receipt file'):
            self.verify()
        self.receipt.unlink()
        alternate.rename(self.receipt)
        path = self.root / 'tools/build_deps.sh'
        alternate = self.root / 'saved-public-input'
        path.rename(alternate)
        path.symlink_to(alternate)
        with self.assertRaisesRegex(ValueError, 'input changed'):
            self.verify()

    def test_unexpected_inventory_and_oversize_receipt_are_rejected(self):
        self.recipe['source_inputs']['extra-input'] = '0' * 64
        self.publish()
        with self.assertRaisesRegex(ValueError, 'Unexpected toolchain source inputs'):
            self.verify()
        self.receipt.write_bytes(b' ' * 65537)
        with self.assertRaisesRegex(ValueError, 'receipt file'):
            self.verify()
        self.receipt.write_text('[]')
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.verify()

    def test_installer_cannot_redirect_outside_the_recipe(self):
        self.recipe['delta']['installer_path'] = '../outside.py'
        self.publish()
        with self.assertRaisesRegex(ValueError, 'Unexpected compiler runtime installer'):
            self.verify()
