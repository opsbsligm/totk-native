"""Bind completed phases to production source and every actual output byte."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source_stamp():
    names = subprocess.check_output(['git', '-c', 'safe.directory=' + str(ROOT), '-C', str(ROOT), 'ls-files', '-z']).decode().split('\0')
    result = hashlib.sha256()
    for name in sorted(filter(None, names)):
        if name.startswith(('docs/', 'tests/', '.gitlab/')) or name in ('README.md', '.gitlab-ci.yml', 'CONTRIBUTING.md'):
            continue
        path = ROOT / name
        if not path.is_file() or path.is_symlink():
            raise ValueError('Invalid tracked production source: ' + name)
        result.update(name.encode() + b'\0' + bytes.fromhex(sha(path)))
    return result.hexdigest()


def output_files(work, directories):
    result = {}
    for path in directories:
        if not path.exists():
            raise ValueError('Missing phase output: ' + str(path))
        files = sorted(path.rglob('*')) if path.is_dir() else [path]
        for file in files:
            if file.is_symlink():
                raise ValueError('Phase output must not be a symlink: ' + str(file))
            if file.is_file():
                result[file.relative_to(work).as_posix()] = dict(size=file.stat().st_size, sha256=sha(file))
    if not result:
        raise ValueError('Phase produced no files')
    return result


def publish(work, phase, directories, before):
    if source_stamp() != before:
        raise ValueError('Production source changed during build; refusing receipt')
    data = dict(schema=1, phase=phase, source=before, files=output_files(work, directories))
    temporary = work / (phase + '-receipt.json.new')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(work / (phase + '-receipt.json'))


def verify(work, phase):
    data = json.loads((work / (phase + '-receipt.json')).read_text())
    if data.get('schema') != 1 or data.get('phase') != phase or data.get('source') != source_stamp():
        raise ValueError('Phase receipt does not match production source: ' + phase)
    if not isinstance(data.get('files'), dict) or not data['files']:
        raise ValueError('Missing phase output manifest: ' + phase)
    for name, record in data['files'].items():
        path = Path(name)
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('Invalid phase output path')
        file = work / path
        if file.is_symlink() or not file.is_file() or file.stat().st_size != record['size'] or sha(file) != record['sha256']:
            raise ValueError('Phase output changed: ' + name)
