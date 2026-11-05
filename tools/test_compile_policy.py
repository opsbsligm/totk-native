"""Compile synthetic generated chunks through the real Ninja/Clang recovery rules."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
spec = importlib.util.spec_from_file_location('build_linux', ROOT / 'tools/build_linux.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class CompilePolicy(unittest.TestCase):
    def test_all_numeric_game_chunks_use_cgp_recovery_and_host_tables_do_not(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            root = Path(tmp)
            host = root / 'src/host/fixture.c'
            host.parent.mkdir(parents=True)
            host.write_text('void host_fixture(void) {}\n')
            generated = root / 'generated'
            generated.mkdir()
            (generated / 'manifest-linux.json').write_text('{}')
            files = []
            for module in ('main', 'subsdk0', 'sdk'):
                directory = generated / module
                directory.mkdir()
                for part in ('000', '001', 'table'):
                    path = directory / (module + '_' + part + '.c')
                    path.write_text('void fixture_' + module + '_' + part + '(void) {}\n')
                    files.append(path)
            out = root / 'build'
            args = ['build_linux.py', '--target', 'game', '--generated', str(generated),
                    '--exefs', str(root / 'input'), '--out', str(out), '--generate-only']
            with patch.object(builder, 'ROOT', root), \
                 patch.object(builder, 'source_lists', return_value=['src/host/fixture.c']), \
                 patch.object(builder, 'verify_generated', return_value=files), \
                 patch.object(builder, 'revision', return_value='f' * 40), \
                 patch.object(builder, 'pkg_flags', return_value=[]), \
                 patch.object(sys, 'argv', args), contextlib.redirect_stdout(io.StringIO()):
                builder.main()
            database = json.loads(subprocess.check_output(['ninja', '-f', str(out / 'build.ninja'),
                '-t', 'compdb', 'cc', 'cc_game'], text=True))
            self.assertEqual(len(database), 10)
            for row in database:
                numeric = Path(row['file']).stem.rsplit('_', 1)[-1].isdigit()
                command = shlex.split(row['command'])
                self.assertEqual('-disable-cgp' in command, numeric, row['file'])
                subprocess.run(command, check=True)


if __name__ == '__main__':
    unittest.main()
