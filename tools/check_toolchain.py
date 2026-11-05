"""Exercise the actual compiler and movie decoder needed by complete builds."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
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
    with tempfile.TemporaryDirectory(prefix='native-video-check-') as folder:
        damaged = Path(folder) / 'corrupt.webm'
        raw = fixture.read_bytes()
        damaged.write_bytes(b'\0' * 32 + raw[32:])
        result = decode(damaged)
        if not result.returncode:
            raise SystemExit('Movie verification admitted a corrupt container')
    print('Clang 18 and real VP9/Opus decode verified; damaged input rejected')


if __name__ == '__main__':
    main()
