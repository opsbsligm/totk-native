"""Source inventory shared by Git checkouts and self-contained source archives."""
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile

MANIFEST = 'source-manifest.json'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def git(root, *args):
    return subprocess.check_output(['git', '-c', 'safe.directory=' + str(root), '-C', str(root), *args],
        stderr=subprocess.DEVNULL)


def has_git(root):
    if not (root / '.git').exists():
        return False
    return Path(git(root, 'rev-parse', '--show-toplevel').decode().strip()).resolve() == root.resolve()


def source_files(root):
    root = Path(root)
    if has_git(root):
        return sorted(filter(None, git(root, 'ls-files', '-z').decode().split('\0')))
    data = json.loads((root / MANIFEST).read_text())
    if data.get('schema') != 1 or not re.fullmatch('[0-9a-f]{40}', data.get('commit', '')):
        raise ValueError('Invalid source archive manifest')
    files = data.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('Empty source archive manifest')
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*')
              if p.is_file() and '__pycache__' not in p.parts and p != root / MANIFEST and p.name != '.DS_Store'}
    if any(p.is_symlink() for p in root.rglob('*')):
        raise ValueError('Source archives must not contain symlinks')
    if actual != set(files):
        raise ValueError('Source archive inventory changed; use an isolated extraction directory')
    for name, record in files.items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Invalid source archive path')
        path = root / relative
        if any(p.is_symlink() for p in (path, *path.parents)) or path.stat().st_size != record['size'] or digest(path) != record['sha256']:
            raise ValueError('Source archive file changed: ' + name)
    return sorted(files)


def revision(root):
    if has_git(root):
        return git(root, 'rev-parse', 'HEAD').decode().strip()
    source_files(root)
    return json.loads((root / MANIFEST).read_text())['commit']


def ensure_clean(root):
    if has_git(root):
        if git(root, 'status', '--porcelain'):
            raise ValueError('Commit reviewed source changes before packaging')
    else:
        source_files(root)


def archive_sources(root, output):
    root, output = Path(root), Path(output)
    ensure_clean(root)
    commit = revision(root)
    names = source_files(root)
    records = {}
    if output.resolve().is_relative_to(root.resolve()):
        raise ValueError('Source archive output must be outside the checkout')
    with output.open('xb') as stream, tarfile.open(fileobj=stream, mode='w:gz') as archive:
        directories = {parent.as_posix() for name in names for parent in Path(name).parents if parent != Path('.')}
        for name in sorted(directories, key=lambda name: (name.count('/'), name)):
            entry = tarfile.TarInfo(name + '/')
            entry.type, entry.mode = tarfile.DIRTYPE, 0o755
            archive.addfile(entry)
        for name in names:
            path = root / name
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 2**20:
                raise ValueError('Unexpected source artifact: ' + name)
            raw = path.read_bytes()
            records[name] = dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            entry = tarfile.TarInfo(name)
            entry.size = len(raw)
            entry.mode = path.stat().st_mode & 0o777
            archive.addfile(entry, io.BytesIO(raw))
        raw = json.dumps(dict(schema=1, commit=commit, files=records), indent=2).encode() + b'\n'
        entry = tarfile.TarInfo(MANIFEST)
        entry.size, entry.mode = len(raw), 0o644
        archive.addfile(entry, io.BytesIO(raw))
    ensure_clean(root)
