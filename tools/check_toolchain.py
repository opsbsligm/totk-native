"""Exercise the actual compiler and movie decoder needed by complete builds."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def verify_receipt(root, receipt, required=False):
    if not receipt.exists() and not receipt.is_symlink():
        if required:
            raise ValueError('The CI toolchain receipt is missing')
        return None
    if receipt.is_symlink() or not receipt.is_file() or receipt.stat().st_size > 65536:
        raise ValueError('Invalid CI toolchain receipt file')
    source = root / '.gitlab/ci-toolchain-recipe.json'
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 65536:
        raise ValueError('Invalid source toolchain recipe')
    raw = source.read_bytes()
    recipe, recorded = json.loads(raw), json.loads(receipt.read_bytes())
    expected = hashlib.sha256(raw).hexdigest()
    if not isinstance(recipe, dict) or not isinstance(recorded, dict) or \
            recipe.get('schema') != 1 or recorded.get('schema') != 1 or \
            recorded.get('recipe_sha256') != expected or recorded.get('recipe') != recipe:
        raise ValueError('The image receipt does not match this source recipe')
    inputs = recipe.get('source_inputs', {})
    if not isinstance(inputs, dict) or set(inputs) != {'Dockerfile', 'tools/build_deps.sh', 'requirements-build.lock'}:
        raise ValueError('Unexpected toolchain source inputs')
    delta = recipe.get('delta', {})
    if not isinstance(delta, dict) or delta.get('installer_path') != '.gitlab/install_compiler_rt.py':
        raise ValueError('Unexpected compiler runtime installer')
    inputs = {**inputs, delta['installer_path']: delta.get('installer_sha256')}
    for name, digest in inputs.items():
        path = root / name
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file() or \
                hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Toolchain input changed: ' + name)
    return expected


def compiler_probe(directory):
    source, binary = directory / 'sanitizers.c', directory / 'sanitizers'
    source.write_text('''#include <limits.h>
#include <stdlib.h>
int main(int argc, char **argv) {
    char *p = malloc(8); if (!p) return 3; p[0] = 37;
    if (argc > 1 && argv[1][0] == 'a') { free(p); return *(volatile char *)p; }
    if (argc > 1) { volatile int n = INT_MAX; free(p); return n + argc; }
    int value = *(volatile char *)p; free(p); return value == 37 ? 0 : 4;
}
''')
    result = subprocess.run(['clang', '-std=gnu17', '-O1', '-g',
        '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
        str(source), '-o', str(binary)], capture_output=True, text=True, timeout=40)
    if result.returncode:
        raise ValueError('Clang 18 needs its matching sanitizer runtime: ' + result.stderr)
    env = dict(os.environ, ASAN_OPTIONS='abort_on_error=0:disable_coredump=1:detect_leaks=1',
               UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=0')
    subprocess.run([str(binary)], env=env, check=True, capture_output=True, timeout=10)
    for mode, marker in [('asan', 'ERROR: AddressSanitizer'), ('ubsan', 'runtime error: signed integer overflow')]:
        result = subprocess.run([str(binary), mode], env=env, capture_output=True, text=True, timeout=10)
        if not result.returncode or marker not in result.stderr:
            raise ValueError('The ' + mode + ' negative compiler probe was not detected')


def main(require_receipt=False):
    try:
        digest = verify_receipt(ROOT, Path('/opt/native-toolchain-receipt.json'), require_receipt)
    except (ValueError, OSError) as error:
        raise SystemExit(str(error)) from error
    if digest:
        print('CI toolchain recipe verified: ' + digest)
    version = subprocess.check_output(['clang', '--version'], text=True)
    if 'clang version 18.' not in version:
        raise SystemExit('Use the pinned Clang 18 toolchain')
    ffmpeg = Path(os.environ['NATIVE_DEPS']) / 'bin/ffmpeg'
    subprocess.run([str(ffmpeg), '-version'], check=True, stdout=subprocess.DEVNULL)
    fixture = ROOT / 'tests/fixtures/synthetic-av.webm'
    def decode(path):
        return subprocess.run([str(ffmpeg), '-v', 'error', '-xerror', '-i', str(path), '-f', 'null', '-'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30)
    valid = decode(fixture)
    if valid.returncode:
        raise SystemExit('Synthetic audio/video decode failed: ' + valid.stderr.decode(errors='replace'))
    with tempfile.TemporaryDirectory(prefix='native-toolchain-check-') as folder:
        try:
            compiler_probe(Path(folder))
        except ValueError as error:
            raise SystemExit(str(error)) from error
        damaged = Path(folder) / 'corrupt.webm'
        raw = fixture.read_bytes()
        damaged.write_bytes(b'\0' * 32 + raw[32:])
        result = decode(damaged)
        if not result.returncode:
            raise SystemExit('Movie verification admitted a corrupt container')
    print('Clang 18 and real VP9/Opus decode verified; ASan/UBSan negative probes and damaged input rejected')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-receipt', action='store_true')
    main(parser.parse_args().require_receipt)
