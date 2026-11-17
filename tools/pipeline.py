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


def code(work, dump, jobs, mods=None):
    data = work / 'data'
    data.mkdir(exist_ok=True)
    options = ['--code-mods', mods] if mods is not None else []
    tool(work, 'input-check', 'prepare_linux_game.py', '--dump', dump, '--data', data, '--stage', 'check', *options)
    from linux_inputs import verify_generated_inputs
    try:
        verify_generated_inputs(data / 'generated', dump / 'exefs', mods)
    except (OSError, ValueError):
        tool(work, 'generate', 'prepare_linux_game.py', '--dump', dump, '--data', data, '--stage', 'lift', *options)
    else:
        print('Reusing generated C after full input, lifter and output hash verification', flush=True)
    tool(work, 'game', 'build_linux.py', '--target', 'game', '--exefs', dump / 'exefs',
         '--generated', data / 'generated', '--out', work / 'game', '--jobs', jobs, *options)
    return verify_generated_inputs(data/'generated', dump/'exefs', mods)[1] if mods is not None else None


def assets(work, dump, jobs, mods=None):
    data = work / 'data'
    data.mkdir(exist_ok=True)
    context = None
    if mods is not None:
        from linux_inputs import verify_generated_inputs
        context = verify_generated_inputs(data/'generated', dump/'exefs', mods)[1]
    tool(work, 'romfs', 'prepare_linux_game.py', '--dump', dump, '--data', data, '--stage', 'romfs')
    tool(work, 'deck-fonts', 'deck_font_prompts.py', '--romfs', data / 'romfs', '--out', data / 'deck-ui')
    tool(work, 'translator', 'build_xlate.py', '--rid', 'linux-x64', '--dotnet', 'dotnet',
         '--out', work / 'translator', '--cache', work / 'cache', '--artifacts', work / 'dotnet-artifacts', '--jobs', jobs)
    from contextlib import nullcontext
    from static_mods import temporary_exefs
    inputs = temporary_exefs(context, data) if context is not None else nullcontext(dump/'exefs')
    with inputs as exefs:
        tool(work, 'shader-export', 'export_shaders.py', data / 'romfs', data / 'shader-work', exefs)
    env = dict(os.environ, ULTRS_SHADER_TRANSLATOR=str(work / 'translator/ultrs-shaders'),
               ULTRS_BUILD_ROOT=str(work / 'texture-tool'))
    tool(work, 'shader-translate', 'run_ryujinx_xlate.py', data / 'shader-work', '--workers', jobs, env=env)
    (data / 'shaders').mkdir(exist_ok=True)
    tool(work, 'shader-pack', 'pack_shaders.py', data / 'shader-work/translated', data / 'shaders/translated.pack')
    tool(work, 'textures', 'bc7_build.py', '--romfs', data / 'romfs', '--cache', data / 'textures', '--threads', jobs, env=env)
    return context


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('runtime', 'build'))
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--jobs', type=int, choices=(1, 2, 3, 4), default=2)
    p.add_argument('--stage', choices=('code', 'assets', 'package', 'all'), default='all')
    p.add_argument('--code-mods', type=Path)
    p.add_argument('--dump', type=Path, default=Path('/input'),
                   help='Checked 1.4.3 inputs (exefs, fonts, romfs); a release data/ directory qualifies')
    a = p.parse_args()
    a.work = a.work.resolve()
    if a.command == 'build':
        a.dump = a.dump.resolve()
        if not a.dump.is_dir():
            raise SystemExit('Input directory is not a directory: ' + str(a.dump))
    a.work.mkdir(parents=True, exist_ok=True, mode=0o700)
    from build_environment import prepare
    os.environ.update(prepare(a.work))
    from check_toolchain import main as check_toolchain
    check_toolchain()
    if a.command == 'runtime':
        if a.code_mods is not None:
            p.error('--code-mods requires a private game build')
        runtime(a.work, a.jobs)
        return
    lock = (a.work / 'build.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    before = source_stamp()
    dump = a.dump
    if a.stage in ('assets', 'package', 'all'):
        from font_inputs import validate_shared_fonts
        validate_shared_fonts(dump / 'fonts')
    receipt = a.work / 'build-complete.json'
    receipt.unlink(missing_ok=True)
    if a.stage in ('code', 'all'):
        (a.work / 'code-receipt.json').unlink(missing_ok=True)
        context = code(a.work, dump, a.jobs, a.code_mods)
        from static_mods import phase_inputs
        publish(a.work, 'code', [a.work / 'game', a.work / 'data/generated'], before, inputs=phase_inputs(context))
    if a.stage in ('assets', 'all'):
        (a.work / 'assets-receipt.json').unlink(missing_ok=True)
        context = assets(a.work, dump, a.jobs, a.code_mods)
        from static_mods import phase_inputs
        publish(a.work, 'assets', [a.work / 'data/romfs', a.work / 'data/shaders', a.work / 'data/textures', a.work / 'data/deck-ui'], before, inputs=phase_inputs(context))
    if a.stage in ('package', 'all'):
        tool(a.work, 'package', 'package_linux.py', '--work', a.work, '--dump', dump,
             *(['--code-mods', a.code_mods] if a.code_mods is not None else []))
        receipt.write_text(json.dumps(dict(schema=1, game=GAME, package='package',
            hardware_validated=False), indent=2) + '\n')
    print(a.command + ' / ' + a.stage + ' completed', flush=True)


if __name__ == '__main__':
    main()
