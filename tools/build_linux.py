"""Build the existing 1.4.3 runtime or real generated game as native Linux x86-64.

runtime creates an archive of the production host/renderer sources, not a game
executable. game requires the real generated tables for all three modules.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

from linux_inputs import UPSTREAM, check_exefs, digest, verify_generated
from source_tree import revision

ROOT = Path(__file__).resolve().parent.parent


def source_lists():
    # Reuse the upstream source lists without importing its Windows toolchain.
    found = {}
    for node in ast.parse((ROOT/'tools/build_game.py').read_text()).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ('RUNTIME', 'TARGETS', 'GFX'):
                found[name] = ast.literal_eval(node.value)
    runtime = [p for p in found['RUNTIME'] if not p.endswith('/windows.c')]
    host = [p for p in found['TARGETS']['ultratears'] if p not in ('src/host/profiler.c', 'src/host/watch.c')]
    return runtime + ['src/runtime/platform/linux.c', 'src/runtime/platform/linux_io.c',
                      'src/host/deck_motion_decode.c', 'src/host/deck_motion_linux.c',
                      'src/host/nd_totk_timing.c',
                      'src/host/diagnostics_linux.c'] + host + found['GFX']


def pkg_flags(*packages):
    return shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', *packages], text=True))


def ninja_path(path):
    return str(path).replace('$', '$$').replace(' ', '$ ').replace(':', '$:')


# Exact recovery recipes: disable only a verified-broken CodeGenPrepare pass,
# or recover machine scheduling/allocation. O0 remains an experimental control.
# New recipes require an explicit code change and tests; no free-form flags.
RECOVERY_RECIPES = (
    ('-mllvm', '-disable-cgp'),
    ('-mllvm', '-enable-misched=false', '-mllvm', '-regalloc=fast'),
    ('-O0',),
)
CHUNK_PATH = re.compile(r'(?P<module>main|subsdk0|sdk)/(?P=module)_[0-9]+\.c')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate overrides JSON key: ' + key)
        result[key] = value
    return result


def load_compile_overrides(path, generated, verified_sources):
    """Validate exact local chunks after the existing full manifest verification.

    Return resolved chunk -> recipe mapping and SHA-256 of exact config bytes.
    No source lists, manifest entries or global flags are modified.
    """
    if path is None:
        return {}, None
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('Overrides must be a local regular JSON file')
    raw = path.read_bytes()
    document = json.loads(raw, object_pairs_hook=_unique_object)
    if (not isinstance(document, dict) or set(document) != {'schema', 'kind', 'files'}
            or type(document['schema']) is not int or document['schema'] != 1
            or document['kind'] != 'ultratears-compile-overrides'
            or not isinstance(document['files'], dict)):
        raise ValueError('Invalid compile overrides schema')
    root = Path(generated).absolute()
    if any(p.is_symlink() for p in (root, *root.parents)) or not root.is_dir():
        raise ValueError('Generated root must be a non-symlink directory')
    root = root.resolve()
    allowed = {Path(source).resolve() for source in verified_sources}
    selected = {}
    for name, entry in document['files'].items():
        if not CHUNK_PATH.fullmatch(name):
            raise ValueError('Override must name a relative generated module/chunk: ' + name)
        if (not isinstance(entry, dict) or set(entry) != {'sha256', 'extra_clang_args'}
                or not isinstance(entry['sha256'], str)
                or not re.fullmatch(r'[0-9a-fA-F]{64}', entry['sha256'])
                or not isinstance(entry['extra_clang_args'], list)
                or tuple(entry['extra_clang_args']) not in RECOVERY_RECIPES):
            raise ValueError('Invalid override hash or recovery arguments: ' + name)
        candidate = root / name
        if candidate.parent.is_symlink() or candidate.is_symlink() or not candidate.is_file():
            raise ValueError('Override source must be a regular non-symlink chunk: ' + name)
        resolved = candidate.resolve()
        if root not in resolved.parents or resolved not in allowed:
            raise ValueError('Override source is not in the verified generated inputs: ' + name)
        digest = hashlib.sha256()
        with candidate.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        if digest.hexdigest() != entry['sha256'].lower():
            raise ValueError('Override source SHA-256 mismatch: ' + name)
        selected[resolved] = tuple(entry['extra_clang_args'])
    return selected, hashlib.sha256(raw).hexdigest()


def write_game_build_record(target, generated, exefs, manifest_sha256,
                            overrides_path, overrides_sha256):
    """Publish provenance only after rechecking the actual successful build inputs."""
    sources = verify_generated(generated, exefs)
    if digest(generated/'manifest-linux.json') != manifest_sha256:
        raise ValueError('Generated input changed during compilation; refusing build record')
    selected, actual_overrides = load_compile_overrides(overrides_path, generated, sources)
    if actual_overrides != overrides_sha256:
        raise ValueError('Compile overrides changed during compilation; refusing build record')
    if target.is_symlink() or not target.is_file():
        raise ValueError('Successful game build did not produce a regular executable')
    counts = {}
    for module in ('main', 'subsdk0', 'sdk'):
        text = (generated/module/(module+'_table.c')).read_text()
        matches = re.findall(r'const uint64_t '+module+r'_fn_count\s*=\s*(\d+)\s*;', text)
        if len(matches) != 1 or int(matches[0]) <= 0:
            raise ValueError('Missing or empty game function count: '+module)
        counts[module] = int(matches[0])
    record = {'schema': 1, 'kind': 'ultratears-linux-build', 'version': '1.4.3',
              'upstream': UPSTREAM, 'binary_sha256': digest(target), 'exefs': check_exefs(exefs),
              'generated_manifest_sha256': manifest_sha256, 'function_counts': counts,
              'compile_overrides_sha256': overrides_sha256,
              'compile_overrides_files': sorted(p.relative_to(generated.resolve()).as_posix()
                                                for p in selected),
              'compile_overrides_experimental': any(r == ('-O0',) for r in selected.values()),
              'hardware_validated': False}
    output = target.with_suffix('.build.json')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', prefix='.build-record-', suffix='.json',
                                         dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(record, stream, indent=2); stream.write('\n')
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return record


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--target', choices=['runtime', 'game'], default='runtime')
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--generated', type=Path)
    ap.add_argument('--exefs', type=Path, help='Locally extracted 1.4.3 ExeFS')
    ap.add_argument('--compile-overrides', type=Path, help='SHA-bound generated-chunk recovery JSON')
    ap.add_argument('--jobs', type=int, default=1)
    ap.add_argument('--generate-only', action='store_true')
    args = ap.parse_args()
    if sys.platform != 'linux' or platform.machine().lower() not in ('x86_64', 'amd64'):
        ap.error('This build entry requires native Linux x86-64')
    if not 1 <= args.jobs <= 4:
        ap.error('--jobs must be between 1 and 4')
    if args.compile_overrides is not None and args.target != 'game':
        ap.error('--compile-overrides requires --target game')
    sources = [(ROOT/p).resolve() for p in source_lists()]
    generated = []
    generated_stamp = None
    if args.target == 'game':
        if not args.generated or not args.exefs:
            ap.error('game requires --generated and --exefs from checked local 1.4.3 input')
        try:
            generated = verify_generated(args.generated, args.exefs)
            generated_stamp = digest(args.generated/'manifest-linux.json')
        except (OSError, ValueError) as e:
            ap.error(str(e))
    try:
        recovery, overrides_sha256 = load_compile_overrides(
            args.compile_overrides, args.generated, generated)
    except (OSError, ValueError) as e:
        ap.error(str(e))
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    temporary = out / 'tmp'
    if temporary.is_symlink():
        ap.error('out/tmp must not be a symlink')
    temporary.mkdir(exist_ok=True)
    cc = shutil.which('clang')
    cxx = shutil.which('clang++')
    ar = shutil.which('llvm-ar') or shutil.which('ar')
    if not all([cc, cxx, ar, shutil.which('ninja')]):
        ap.error('clang, clang++, ar and ninja are required')
    flags = pkg_flags('sdl3', 'vulkan', 'opus', 'vpx', 'openssl', 'libzstd')
    includes = [f'-I{ROOT/p}' for p in ['src/host', 'src/gfx', 'src/gfx/nvn', 'src/gfx/nvn/include', 'src/gfx/compat', 'src/runtime']]
    if os.environ.get('ULTRS_VULKAN_INCLUDE'):
        includes.insert(0, '-I'+os.environ['ULTRS_VULKAN_INCLUDE'])
    common = ['-D_GNU_SOURCE', '-D_FILE_OFFSET_BITS=64', '-O1', '-gline-tables-only', '-fno-strict-aliasing',
              '-march=x86-64-v3', '-fPIC', '-pthread', *includes, *[x for x in flags if not x.startswith(('-l', '-L', '-Wl,'))]]
    version_text = '#define ULTRS_VERSION "1.4.3-linux"\n#define ULTRS_COMMIT "' + revision(ROOT)[:12] + '"\n'
    version_header = out / 'version.h'
    if not version_header.exists() or version_header.read_text() != version_text:
        version_header.write_text(version_text)
    common.append('-I'+str(out))
    lines = ['builddir = '+ninja_path(out),
             'rule cc', '  command = '+shlex.quote(cc)+' '+shlex.join(common)+' -std=gnu17 -MD -MF $out.d -c $in -o $out',
             '  depfile = $out.d', '  deps = gcc',
             'rule cxx', '  command = '+shlex.quote(cxx)+' '+shlex.join(common)+' -std=c++17 -fno-exceptions -fno-rtti -MD -MF $out.d -c $in -o $out',
             '  depfile = $out.d', '  deps = gcc',
             'rule ar', '  command = '+shlex.quote(ar)+' rcs $out $in',
             'rule cc_game',
             '  command = '+shlex.quote(cc)+' '+shlex.join(common)+' -mllvm -disable-cgp -std=gnu17 -MD -MF $out.d -c $in -o $out',
             '  depfile = $out.d', '  deps = gcc',
             'rule link', '  command = '+shlex.quote(cxx)+' -rdynamic -o $out @$out.rsp '+shlex.join(flags+['-pthread', '-ldl', '-lm']),
             '  rspfile = $out.rsp', '  rspfile_content = $in']
    if recovery:
        lines.extend(['rule cc_recovery',
                      '  command = '+shlex.quote(cc)+' '+shlex.join([arg for arg in common if arg != '-O1'])+' $recovery_clang_args -std=gnu17 -MD -MF $out.d -c $in -o $out',
                      '  depfile = $out.d', '  deps = gcc'])
    objects = []
    for i, source in enumerate(sources + generated):
        if not source.is_file():
            ap.error('Missing source: '+str(source))
        obj = out/'obj'/(f'{i:04d}_'+source.stem+'.o')
        obj.parent.mkdir(exist_ok=True)
        rule = 'cxx' if source.suffix == '.cpp' else 'cc'
        if source in generated and CHUNK_PATH.fullmatch(source.relative_to(args.generated.resolve()).as_posix()):
            rule = 'cc_game'
        if recovery and source.resolve() in recovery and source in generated:
            rule = 'cc_recovery'
        lines.append(f'build {ninja_path(obj)}: {rule} {ninja_path(source)}')
        if rule == 'cc_recovery':
            recipe = recovery[source.resolve()]
            optimization = [] if recipe == ('-O0',) else ['-O1']
            lines.append('  recovery_clang_args = '+shlex.join([*optimization, *recipe]))
        objects.append(obj)
    target = out/('libultratears-runtime.a' if args.target == 'runtime' else 'ultratears')
    lines.append(f'build {ninja_path(target)}: {"ar" if args.target == "runtime" else "link"} '+' '.join(ninja_path(o) for o in objects))
    lines.append('default '+ninja_path(target))
    build = out/'build.ninja'
    build.write_text('\n'.join(lines)+'\n')
    print(json.dumps({'target': args.target, 'runtime_sources': len(sources), 'generated_sources': len(generated),
                      'output': str(target), 'game_playability_validated': False,
                      'compile_overrides_sha256': overrides_sha256,
                      'compile_overrides_experimental': any(recipe == ('-O0',) for recipe in recovery.values()),
                      'compile_overrides_files': sorted(p.relative_to(args.generated.resolve()).as_posix()
                                                        for p in recovery),
                      'ninja_tmpdir': str(temporary)}), flush=True)
    if not args.generate_only:
        if args.target == 'game':
            # A failed new build must not leave an old receipt next to a changed ELF.
            target.with_suffix('.build.json').unlink(missing_ok=True)
        code = subprocess.call(['ninja', '-f', str(build), '-j', str(args.jobs), '-k', '0'],
                               env={**os.environ, 'TMPDIR': str(temporary)})
        if code == 0 and args.target == 'game':
            try:
                write_game_build_record(target, args.generated, args.exefs, generated_stamp,
                                        args.compile_overrides, overrides_sha256)
            except (OSError, ValueError) as error:
                raise SystemExit(str(error))
        raise SystemExit(code)


if __name__ == '__main__':
    main()
