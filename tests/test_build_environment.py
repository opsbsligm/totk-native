"""Actual filesystem boundaries and pinned SDK first-use in private build paths."""
import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_environment', ROOT / 'tools/build_environment.py')
environment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(environment)


class BuildEnvironment(unittest.TestCase):
    def test_private_paths_preserve_home_and_existing_package_cache(self):
        home = os.environ.get('HOME')
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root = Path(tmp)
            cache = root / 'cache/nuget'
            cache.parent.mkdir(mode=0o700)
            cache.mkdir(mode=0o700)
            marker = cache / 'existing-input'
            marker.write_bytes(b'preserved')
            values = environment.prepare(root)
            self.assertNotIn('HOME', values)
            self.assertEqual(os.environ.get('HOME'), home)
            self.assertTrue(all(Path(path).is_relative_to(root) for path in values.values()))
            self.assertEqual(stat.S_IMODE(Path(values['XDG_RUNTIME_DIR']).stat().st_mode), 0o700)
            self.assertEqual(Path(values['NUGET_PACKAGES']), cache)
            self.assertEqual(marker.read_bytes(), b'preserved')
            self.assertEqual(environment.prepare(root), values)

    def test_linked_runtime_or_cache_is_rejected_without_target_writes(self):
        for relative in ('.build-runtime', 'cache'):
            with self.subTest(path=relative), tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
                base = Path(tmp)
                work, target = base / 'work', base / 'unrelated'
                work.mkdir(mode=0o700); target.mkdir(mode=0o700)
                (work / relative).symlink_to(target, target_is_directory=True)
                with self.assertRaises(ValueError):
                    environment.prepare(work)
                self.assertEqual(list(target.iterdir()), [])

    def test_open_runtime_permissions_are_rejected_without_chmod(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            work = Path(tmp)
            runtime = work / '.build-runtime'
            runtime.mkdir(mode=0o755); runtime.chmod(0o755)
            with self.assertRaises(ValueError):
                environment.prepare(work)
            self.assertEqual(stat.S_IMODE(runtime.stat().st_mode), 0o755)
            self.assertEqual(list(runtime.iterdir()), [])

    def test_shared_writable_workspace_or_cache_is_rejected(self):
        for relative in ('', 'cache'):
            with self.subTest(path=relative), tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
                work = Path(tmp)
                target = work / relative
                target.mkdir(exist_ok=True); target.chmod(0o777)
                with self.assertRaises(ValueError):
                    environment.prepare(work)
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o777)

    def test_real_nuget_first_use_uses_the_private_workspace(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            values = environment.prepare(Path(tmp))
            env = dict(os.environ, **values)
            subprocess.run(['dotnet', 'nuget', 'locals', 'all', '--list'], env=env,
                           check=True, capture_output=True, timeout=45)
            self.assertTrue(Path(values['DOTNET_CLI_HOME']).is_dir())


if __name__ == '__main__':
    unittest.main()
