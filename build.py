#!/usr/bin/env python3
"""Build the standalone Linux port in an isolated, source-defined toolchain."""
import argparse
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent
GAME = ROOT.name  # Display only; build identity comes from the tracked profile.


def external_path(value):
    path = Path(value).expanduser().resolve()
    if path == ROOT or path.is_relative_to(ROOT) or ROOT.is_relative_to(path):
        raise argparse.ArgumentTypeError('Use a separate directory outside the source checkout')
    if ':' in str(path) or '\n' in str(path):
        raise argparse.ArgumentTypeError('Docker bind paths cannot contain colon or newline')
    return path


def mod_path(value):
    path = Path(value).expanduser().absolute()
    if '..' in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise argparse.ArgumentTypeError('Code mods must not contain traversal or symlink path components')
    return external_path(value)


def image_name():
    digest = hashlib.sha256()
    for rel in ('Dockerfile', 'tools/build_deps.sh', 'requirements-build.lock'):
        digest.update(rel.encode() + b'\0' + (ROOT / rel).read_bytes())
    return 'native-games/toolchain:' + digest.hexdigest()[:20]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('doctor', 'toolchain', 'runtime', 'build'))
    p.add_argument('--work', type=external_path, required=True)
    p.add_argument('--dump', type=external_path)
    p.add_argument('--distfiles', type=external_path, help='Optional cache of hash-verified public dependency archives')
    p.add_argument('--jobs', type=int, choices=(1, 2, 3, 4), default=2)
    p.add_argument('--stage', choices=('code', 'assets', 'package', 'all'), default='all')
    p.add_argument('--code-mods', type=mod_path, help='Read-only mods/<name>/exefs patches; regeneration is required')
    a = p.parse_args()
    if a.command == 'build' and (a.dump is None or not a.dump.is_dir()):
        p.error('build requires --dump with a decrypted, updated game directory')
    if a.dump and (a.dump == a.work or a.dump.is_relative_to(a.work) or a.work.is_relative_to(a.dump)):
        p.error('Input dump and output work directories must not overlap')
    if a.code_mods is not None:
        if a.command != 'build' or not a.code_mods.is_dir():
            p.error('--code-mods requires build and an existing private mod directory')
        for other in (a.work, a.dump):
            if a.code_mods == other or a.code_mods.is_relative_to(other) or other.is_relative_to(a.code_mods):
                p.error('Code mods, dump and work directories must not overlap')
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        p.error('Use an x86_64 Linux build host, including Steam Deck Desktop Mode')
    if not shutil.which('docker'):
        p.error('Docker with a running daemon is required')
    a.work.mkdir(parents=True, exist_ok=True, mode=0o700)
    if a.work.stat().st_uid == os.getuid():
        a.work.chmod(a.work.stat().st_mode | 0o700)
    free = shutil.disk_usage(a.work).free // 2**30
    required = 100 if a.command == 'build' else 10
    if free < required:
        p.error(f'Need {required} GiB free in --work; currently {free} GiB')
    print(f'Work: {a.work}; free: {free} GiB; estimated additional peak: {required} GiB', flush=True)
    image = image_name()
    if a.command == 'doctor':
        subprocess.run(['docker', 'buildx', 'version'], check=True)
        subprocess.run(['docker', 'info', '--format', '{{.OSType}}/{{.Architecture}}'], check=True)
        if a.dump:
            for name in ('exefs', 'romfs'):
                if not (a.dump / name).is_dir():
                    p.error('Missing input directory: ' + name)
        print('Host checks passed. Exact version/content validation runs before generation.')
        return
    if subprocess.run(['docker', 'image', 'inspect', image], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode:
        cache = a.distfiles or a.work / 'distfiles'
        cache.mkdir(parents=True, exist_ok=True)
        subprocess.run(['docker', 'build', '--build-arg', f'JOBS={a.jobs}',
                        '--build-context', f'distfiles={cache}',
                        '--tag', image, '--file', str(ROOT / 'Dockerfile'), str(ROOT)], check=True)
    if a.command == 'toolchain':
        print(image)
        return
    cmd = ['docker', 'run', '--rm', '--init', '--cpus', str(a.jobs),
           '--memory', '8g', '--memory-swap', '8g', '--cap-drop', 'ALL',
           '--security-opt', 'no-new-privileges', '--user', f'{os.getuid()}:{os.getgid()}',
           '--volume', f'{ROOT}:/src:ro', '--volume', f'{a.work}:/work',
           '--env', 'DOTNET_CLI_HOME=/work/home', '--env', 'PYTHONDONTWRITEBYTECODE=1']
    if a.dump:
        cmd += ['--volume', f'{a.dump}:/input:ro']
    if a.code_mods is not None:
        cmd += ['--volume', f'{a.code_mods}:/mods:ro']
    cmd += [image, 'python3', '/src/tools/pipeline.py', a.command,
            '--work', '/work', '--jobs', str(a.jobs), '--stage', a.stage]
    if a.code_mods is not None:
        cmd += ['--code-mods', '/mods']
    subprocess.run(cmd, check=True)


if __name__ == '__main__':
    main()
