"""Rebuild production code and private assets without existing object files."""
import argparse
import fcntl
from build_receipts import publish, source_stamp
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
GAME = 'totk'


def run(work, label, args, *, env=None, cwd=ROOT):
    logs = work / 'logs'
    logs.mkdir(exist_ok=True)
    path = logs / (label + '.log')
    print(label + ': ' + str(path), flush=True)
    with path.open('w') as stream:
        result = subprocess.run(list(map(str, args)), cwd=cwd,
            stdout=stream, stderr=subprocess.STDOUT, env=env)
    if result.returncode:
        print('\n'.join(path.read_text(errors='replace').splitlines()[-50:]), file=sys.stderr)
        raise SystemExit(f'{label} failed ({result.returncode}); full log: {path}')


def tool(work, label, name, *args, env=None):
    run(work, label, [sys.executable, ROOT / 'tools' / name, *args], env=env)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def runtime(work, jobs):
    tool(work, 'runtime', 'build_linux.py', '--target', 'runtime', '--out', work / 'runtime', '--jobs', jobs)


def code(work, dump, jobs):
    data = work / 'data'
    data.mkdir(exist_ok=True)
    tool(work, 'input-check', 'prepare_linux_game.py', '--dump', dump, '--data', data, '--stage', 'check')
    from linux_inputs import verify_generated
    try:
        verify_generated(data / 'generated', dump / 'exefs')
    except (OSError, ValueError):
        tool(work, 'generate', 'prepare_linux_game.py', '--dump', dump, '--data', data, '--stage', 'lift')
    else:
        print('Reusing generated C after full input, lifter and output hash verification', flush=True)
    tool(work, 'game', 'build_linux.py', '--target', 'game', '--exefs', dump / 'exefs',
         '--generated', data / 'generated', '--out', work / 'game', '--jobs', jobs)


def assets(work, dump, jobs):
    data = work / 'data'
    data.mkdir(exist_ok=True)
    tool(work, 'romfs', 'prepare_linux_game.py', '--dump', dump, '--data', data, '--stage', 'romfs')
    tool(work, 'translator', 'build_xlate.py', '--rid', 'linux-x64', '--dotnet', 'dotnet',
         '--out', work / 'translator', '--cache', work / 'cache', '--artifacts', work / 'dotnet-artifacts', '--jobs', jobs)
    tool(work, 'shader-export', 'export_shaders.py', data / 'romfs', data / 'shader-work', dump / 'exefs')
    env = dict(os.environ, ULTRS_SHADER_TRANSLATOR=str(work / 'translator/ultrs-shaders'),
               ULTRS_BUILD_ROOT=str(work / 'texture-tool'))
    tool(work, 'shader-translate', 'run_ryujinx_xlate.py', data / 'shader-work', '--workers', jobs, env=env)
    (data / 'shaders').mkdir(exist_ok=True)
    tool(work, 'shader-pack', 'pack_shaders.py', data / 'shader-work/translated', data / 'shaders/translated.pack')
    tool(work, 'textures', 'bc7_build.py', '--romfs', data / 'romfs', '--cache', data / 'textures', '--threads', jobs, env=env)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('runtime', 'build'))
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--jobs', type=int, choices=(1, 2, 3, 4), default=2)
    p.add_argument('--stage', choices=('code', 'assets', 'package', 'all'), default='all')
    a = p.parse_args()
    a.work = a.work.resolve()
    a.work.mkdir(parents=True, exist_ok=True)
    (a.work / 'home').mkdir(exist_ok=True)
    if a.command == 'runtime':
        runtime(a.work, a.jobs)
        return
    lock = (a.work / 'build.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    before = source_stamp()
    dump = Path('/input')
    if a.stage in ('assets', 'package', 'all'):
        from font_inputs import validate_shared_fonts
        validate_shared_fonts(dump / 'fonts')
    receipt = a.work / 'build-complete.json'
    receipt.unlink(missing_ok=True)
    if a.stage in ('code', 'all'):
        (a.work / 'code-receipt.json').unlink(missing_ok=True)
        code(a.work, dump, a.jobs)
        publish(a.work, 'code', [a.work / 'game', a.work / 'data/generated'], before)
    if a.stage in ('assets', 'all'):
        (a.work / 'assets-receipt.json').unlink(missing_ok=True)
        assets(a.work, dump, a.jobs)
        publish(a.work, 'assets', [a.work / 'data/romfs', a.work / 'data/shaders', a.work / 'data/textures'], before)
    if a.stage in ('package', 'all'):
        tool(a.work, 'package', 'package_linux.py', '--work', a.work, '--dump', dump)
        receipt.write_text(json.dumps(dict(schema=1, game=GAME, package='package',
            hardware_validated=False), indent=2) + '\n')
    print(a.command + ' / ' + a.stage + ' completed', flush=True)


if __name__ == '__main__':
    main()
