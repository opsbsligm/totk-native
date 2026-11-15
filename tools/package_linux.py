"""Assemble a private, portable directory from verified local build outputs."""
import argparse
from build_receipts import verify
from source_tree import ensure_clean, revision, archive_sources
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE_LIBS = re.compile(r'^(?:ld-linux|lib(?:c|m|dl|pthread|rt|resolv|stdc\+\+|gcc_s|vulkan)\.so)')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def writable_output_directories(root):
    """Only give the owner access to newly copied output directories."""
    def prepare(path):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError('Package output directory identity/owner differs')
        path.chmod(stat.S_IMODE(info.st_mode) | 0o700)
    prepare(root)
    for current, directories, _ in os.walk(root, followlinks=False):
        for name in directories:
            path = Path(current) / name
            if stat.S_ISDIR(path.lstat().st_mode):
                prepare(path)


def discard_staging(staging, identity):
    """Remove only our original staging tree, including read-only copies."""
    try:
        info = staging.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != identity:
        return False
    writable_output_directories(staging)
    shutil.rmtree(staging)
    return True


def copy_tree(source, dest):
    if source.is_symlink():
        raise ValueError('Private package inputs must not contain symlinks: ' + str(source))
    if not source.is_dir():
        raise ValueError('Missing input directory: ' + str(source))
    for path in source.rglob('*'):
        if path.is_symlink():
            raise ValueError('Private package inputs must not contain symlinks: ' + str(path))
    shutil.copytree(source, dest)
    writable_output_directories(dest)


def bundle_libraries(binary, directory):
    directory.mkdir(exist_ok=True)
    pending = [binary]
    seen = set()
    while pending:
        path = pending.pop()
        text = subprocess.check_output(['ldd', str(path)], text=True)
        if 'not found' in text:
            raise ValueError('Unresolved library: ' + text)
        for line in text.splitlines():
            match = re.match(r'\s*(\S+) => (/\S+) \(', line)
            if not match:
                continue
            name, location = match.groups()
            if BASE_LIBS.match(name) or name in seen:
                continue
            seen.add(name)
            target = directory / name
            shutil.copy2(Path(location).resolve(strict=True), target)
            subprocess.run(['patchelf', '--set-rpath', '$ORIGIN', str(target)], check=True)
            pending.append(Path(location))
    subprocess.run(['patchelf', '--set-rpath', '$ORIGIN/lib', str(binary)], check=True)



def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--dump', type=Path, required=True)
    p.add_argument('--code-mods', type=Path, help='The same read-only static patches used for code and assets')
    a = p.parse_args()
    work, dump = a.work.resolve(), a.dump.resolve()
    ensure_clean(ROOT)
    commit = revision(ROOT)
    from linux_inputs import verify_generated_inputs
    from static_mods import phase_inputs
    _, context = verify_generated_inputs(work/'data/generated', dump/'exefs', a.code_mods)
    verify(work, 'code', inputs=phase_inputs(context))
    verify(work, 'assets', inputs=phase_inputs(context))
    profile = json.loads((ROOT / 'UPSTREAM.json').read_text())
    target = work / 'package'
    staging = work / 'package.new'
    if target.exists() or staging.exists():
        p.error('Package already exists; move it aside explicitly before creating a replacement')
    staging.mkdir(mode=0o700)
    staging_info = staging.stat()
    staging_identity = (staging_info.st_dev, staging_info.st_ino)
    try:
        from font_inputs import validate_shared_fonts
        validate_shared_fonts(dump / 'fonts')
        from linux_inputs import check_exefs
        check_exefs(dump / 'exefs')
        receipt = json.loads((work / 'game/ultratears.build.json').read_text())
        if receipt['binary_sha256'] != digest(work / 'game/ultratears'):
            raise ValueError('Game executable differs from successful build receipt')
        from static_mods import record as mod_record
        if (receipt.get('static_mods') != (mod_record(context) if context is not None else None)
                or receipt.get('exefs') != check_exefs(dump/'exefs')
                or receipt.get('generated_manifest_sha256') != digest(work/'data/generated/manifest-linux.json')):
            raise ValueError('Game executable was built for different generated or static mod inputs')
        executable = 'ultratears'
        shutil.copy2(work / 'game' / executable, staging / executable)
        (staging / 'data').mkdir()
        for name in ('romfs', 'shaders', 'textures', 'deck-ui'):
            copy_tree(work / 'data' / name, staging / 'data' / name)
        copy_tree(dump / 'exefs', staging / 'data/exefs')
        if context is not None:
            for module, raw in context.prepared.modules.items():
                output = staging/'data/exefs'/module
                mode = stat.S_IMODE(output.stat().st_mode)
                output.chmod(mode | stat.S_IWUSR)
                output.write_bytes(raw)
                output.chmod(mode)
            (staging/'provenance').mkdir()
            (staging/'provenance/static-mods.json').write_text(json.dumps(mod_record(context), indent=2)+'\n')
        copy_tree(dump / 'fonts', staging / 'data/fonts')
        fonts = ['0-standard', '1-chinese-simplified', '2-chinese-simplified-extension',
                 '3-chinese-traditional', '4-korean', '5-nintendo-extension']
        for name in fonts:
            font = staging / 'data/fonts' / (name + '.bfttf')
            if not font.is_file() or not 12 <= font.stat().st_size < 64 * 2**20:
                raise ValueError('Missing or invalid shared font: ' + name)
        shutil.copy2(ROOT / 'packaging/motion_session.py', staging / 'motion_session.py')
        bundle_libraries(staging / executable, staging / 'lib')
        copy_tree(ROOT / 'licenses', staging / 'licenses')
        for package in ('libssl3t64', 'libvpx9', 'libopus0', 'libzstd1', 'zlib1g'):
            copyright = Path('/usr/share/doc') / package / 'copyright'
            if copyright.is_file():
                shutil.copy2(copyright, staging / 'licenses' / (package + '-copyright.txt'))
        for rel in ('run.py', 'run.sh', 'game.sh'):
            shutil.copy2(ROOT / 'packaging' / rel, staging / rel)
        for rel in ('run.sh', 'game.sh', executable):
            (staging / rel).chmod(0o755)
        for name in ('LICENSE', 'NOTICE.md', 'UPSTREAM.json'):
            shutil.copy2(ROOT / name, staging / name)
        archive_sources(ROOT, staging / 'source.tar.gz')
        manifest = dict(schema=1, source_commit=commit, version=profile['game_version'],
            private_game_content=True, hardware_validated=False,
            files={path.relative_to(staging).as_posix(): dict(size=path.stat().st_size, sha256=digest(path))
                   for path in sorted(staging.rglob('*')) if path.is_file()})
        (staging / 'bundle.json').write_text(json.dumps(manifest, indent=2) + '\n')
        # Recheck original modules, patch bytes and generated output after copying.
        # Nothing is installed if any input changed during package assembly.
        _, final_context = verify_generated_inputs(work/'data/generated', dump/'exefs', a.code_mods)
        if phase_inputs(final_context) != phase_inputs(context):
            raise ValueError('Static mod inputs changed during package assembly')
        verify(work, 'code', inputs=phase_inputs(final_context))
        verify(work, 'assets', inputs=phase_inputs(final_context))
        staging.rename(target)
        print('Private package ready: ' + str(target))
    except BaseException:
        # The original inputs/build outputs remain authoritative. A failed copy
        # is reproducible, and must not strand another full private game tree.
        discard_staging(staging, staging_identity)
        raise


if __name__ == '__main__':
    main()
