"""Check the actual binaries needed by full builds, not only their libraries."""
import os
from pathlib import Path
import subprocess


def main():
    version = subprocess.check_output(['clang', '--version'], text=True)
    if 'clang version 18.' not in version:
        raise SystemExit('Use the pinned Clang 18 toolchain')
    ffmpeg = Path(os.environ['NATIVE_DEPS']) / 'bin/ffmpeg'
    subprocess.run([str(ffmpeg), '-version'], check=True, stdout=subprocess.DEVNULL)
    filters = subprocess.check_output([str(ffmpeg), '-hide_banner', '-filters'], text=True)
    if not any(line.split()[1:2] == ['null'] for line in filters.splitlines()):
        raise SystemExit('FFmpeg lacks the null verification filter')
    print('Pinned compiler and complete movie verification tool available')


if __name__ == '__main__':
    main()
