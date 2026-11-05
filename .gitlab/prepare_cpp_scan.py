"""Forward real public-runtime compile commands and headers to the C/C++ analyzer."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tarfile


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def system_includes(compiler, language):
    run = subprocess.run([compiler, '-E', '-x', language, '-', '-v'], input='', text=True,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    section = run.stderr.split('#include <...> search starts here:', 1)[1].split('End of search list.', 1)[0]
    return [Path(line.strip()).resolve() for line in section.splitlines() if line.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source, build, output = (path.resolve() for path in (args.source, args.build, args.output))
    project = Path(os.environ['CI_PROJECT_DIR']).resolve()
    if not build.is_relative_to(project) or not output.is_relative_to(project):
        parser.error('Keep public analysis outputs under the CI checkout')
    if output.exists():
        parser.error('Use a fresh analysis output directory')
    raw = []
    for line in (build / 'logs/runtime.log').read_text().splitlines():
        match = re.match(r'^(?:\[\d+/\d+\]\s+)?((?:/\S+/)?clang(?:\+\+)?\s.*)$', line)
        if not match:
            continue
        command = shlex.split(match[1])
        if '-c' not in command or '-o' not in command:
            continue
        path = Path(command[command.index('-c') + 1])
        path = (source / path).resolve() if not path.is_absolute() else path.resolve()
        obj = Path(command[command.index('-o') + 1])
        obj = (source / obj).resolve() if not obj.is_absolute() else obj.resolve()
        if not path.is_relative_to(source) or not obj.is_relative_to(build):
            raise ValueError('Analysis accepts public runtime sources only')
        corresponding = project / path.relative_to(source)
        if not corresponding.is_file() or sha(path) != sha(corresponding):
            raise ValueError('Exported source differs from the scanned checkout')
        raw.append((path, obj, command))
    if not raw or {obj for _, obj, _ in raw} != set(build.rglob('*.o')):
        raise ValueError('Compilation database does not cover every built runtime object')
    output.mkdir(parents=True)
    resource = (Path(subprocess.check_output(['clang', '-print-resource-dir'], text=True).strip()) / 'include').resolve()
    # The analyzer uses its own Clang version. Intrinsic/resource headers must
    # match that compiler; only the build host's libc/C++ SDK is forwarded.
    languages = {language: [path for path in system_includes(compiler, language) if path != resource]
                 for language, compiler in (('c', 'clang'), ('c++', 'clang++'))}
    unique = list(dict.fromkeys(path for paths in languages.values() for path in paths))
    mappings = {str(source): str(project), str(build): str(output / 'generated')}
    native = Path(os.environ['NATIVE_DEPS']) / 'include'
    shutil.copytree(native, output / 'sdk/native')
    mappings[str(native)] = str(output / 'sdk/native')
    for index, path in enumerate(unique):
        target = output / 'sdk' / ('system-' + str(index))
        shutil.copytree(path, target)
        mappings[str(path)] = str(target)
    # Only generated public headers are forwarded; no objects, ELF files or game code.
    for path in build.rglob('*'):
        if path.is_file() and path.suffix in ('.h', '.inc'):
            target = output / 'generated' / path.relative_to(build)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    def rebase(value):
        for old, new in sorted(mappings.items(), key=lambda pair: len(pair[0]), reverse=True):
            value = value.replace(old, new)
        return value
    entries = []
    for path, obj, command in raw:
        language = 'c++' if '++' in Path(command[0]).name or path.suffix in ('.cpp', '.mm') else 'c'
        arguments = ['clang++' if language == 'c++' else 'clang']
        skip = False
        for value in command[1:]:
            if skip:
                skip = False
                continue
            if value in ('-o', '-MF', '-MT', '-MQ'):
                skip = True
                continue
            if value in ('-MD', '-MMD', '-MP'):
                continue
            arguments.append(rebase(value))
        arguments.append('-nostdlibinc')
        if language == 'c++':
            arguments.append('-nostdinc++')
        for include in languages[language]:
            arguments += ['-isystem', mappings[str(include)]]
        entries.append(dict(directory=str(project), file=str(project / path.relative_to(source)), arguments=arguments))
    (output / 'compile_commands.json').write_text(json.dumps(entries, indent=2) + '\n')
    metadata = dict(public_runtime_translation_units=len(entries), all_built_objects_covered=True,
                    game_generated_code_included=False, system_include_directories=len(unique))
    (output / 'coverage-input.json').write_text(json.dumps(metadata, indent=2) + '\n')
    archive = output.with_suffix('.tar.gz')
    with tarfile.open(archive, 'w:gz') as stream:
        stream.add(output, arcname=output.name)
    print(json.dumps(dict(**metadata, artifact=str(archive), size=archive.stat().st_size)))


if __name__ == '__main__':
    main()
