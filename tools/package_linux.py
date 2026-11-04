"""Assemble a private, portable directory from verified local build outputs."""
import argparse
from build_receipts import verify
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE_LIBS = re.compile(r'^(?:ld-linux|lib(?:c|m|dl|pthread|rt|resolv|stdc\+\+|gcc_s|vulkan)\.so)')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def copy_tree(source, dest):
    if not source.is_dir():
        raise ValueError('Missing input directory: ' + str(source))
    for path in source.rglob('*'):
        if path.is_symlink():
            raise ValueError('Private package inputs must not contain symlinks: ' + str(path))
    shutil.copytree(source, dest)


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
    a = p.parse_args()
    work, dump = a.work.resolve(), a.dump.resolve()
    if subprocess.check_output(['git', '-c', 'safe.directory=' + str(ROOT), '-C', str(ROOT), 'status', '--porcelain']):
        p.error('Commit reviewed source changes before packaging; source archive must match the build')
    commit = subprocess.check_output(['git', '-c', 'safe.directory=' + str(ROOT), '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    verify(work, 'code')
    verify(work, 'assets')
    profile = json.loads((ROOT / 'UPSTREAM.json').read_text())
    totk = profile['game_version'] == '1.4.3'
    target = work / 'package'
    staging = work / 'package.new'
    if target.exists() or staging.exists():
        p.error('Package already exists; move it aside explicitly before creating a replacement')
    staging.mkdir()
    try:
        if totk:
            from linux_inputs import check_exefs, verify_generated
            check_exefs(dump / 'exefs')
            verify_generated(work / 'data/generated', dump / 'exefs')
            receipt = json.loads((work / 'game/ultratears.build.json').read_text())
            if receipt['binary_sha256'] != digest(work / 'game/ultratears'):
                raise ValueError('Game executable differs from successful build receipt')
            executable = 'ultratears'
            shutil.copy2(work / 'game' / executable, staging / executable)
            (staging / 'data').mkdir()
            for name in ('romfs', 'shaders', 'textures'):
                copy_tree(work / 'data' / name, staging / 'data' / name)
            copy_tree(dump / 'exefs', staging / 'data/exefs')
            copy_tree(dump / 'fonts', staging / 'data/fonts')
            fonts = ['0-standard', '1-chinese-simplified', '2-chinese-simplified-extension',
                     '3-chinese-traditional', '4-korean', '5-nintendo-extension']
            for name in fonts:
                font = staging / 'data/fonts' / (name + '.bfttf')
                if not font.is_file() or not 12 <= font.stat().st_size < 64 * 2**20:
                    raise ValueError('Missing or invalid shared font: ' + name)
            shutil.copy2(ROOT / 'packaging/motion_session.py', staging / 'motion_session.py')
        else:
            from legacy_sdk7 import verify_exefs
            verify_exefs(dump / 'exefs', ['main', 'subsdk0', 'sdk'])
            executable = 'savagewind'
            shutil.copy2(work / 'game' / executable, staging / executable)
            (staging / 'data').mkdir()
            for name in ('exefs', 'romfs', 'aoc1', 'aoc2'):
                copy_tree(dump / name, staging / 'data' / name)
            if (staging / 'data/romfs/System/Version.txt').read_text().strip() != '1.6.0':
                raise ValueError('Expected BOTW 1.6.0 RomFS')
            for suffix in ('so', 'so.id'):
                shutil.copy2(work / 'game' / ('swgame.' + suffix), staging / 'data' / ('swgame.' + suffix))
            for font in (ROOT / 'third_party/fonts').rglob('*'):
                if font.is_file() and font.suffix in ('.ttf', '.otf', '.txt'):
                    shutil.copy2(font, staging / font.name)
            copy_tree(ROOT / 'third_party/luts', staging / 'colour-luts')
        bundle_libraries(staging / executable, staging / 'lib')
        for rel in ('run.py', 'run.sh', 'game.sh'):
            shutil.copy2(ROOT / 'packaging' / rel, staging / rel)
        for rel in ('run.sh', 'game.sh', executable):
            (staging / rel).chmod(0o755)
        for name in ('LICENSE', 'NOTICE.md', 'UPSTREAM.json'):
            shutil.copy2(ROOT / name, staging / name)
        subprocess.run(['git', '-c', 'safe.directory=' + str(ROOT), '-C', str(ROOT), 'archive', '--format=tar.gz',
                        '--output=' + str(staging / 'source.tar.gz'), commit], check=True)
        manifest = dict(schema=1, source_commit=commit, version=profile['game_version'],
            private_game_content=True, hardware_validated=False,
            files={path.relative_to(staging).as_posix(): dict(size=path.stat().st_size, sha256=digest(path))
                   for path in sorted(staging.rglob('*')) if path.is_file()})
        (staging / 'bundle.json').write_text(json.dumps(manifest, indent=2) + '\n')
        staging.rename(target)
        print('Private package ready: ' + str(target))
    except BaseException:
        # Keep a failed staging directory for diagnosis. Never publish it as package/.
        raise


if __name__ == '__main__':
    main()
