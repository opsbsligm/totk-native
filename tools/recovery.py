"""Private, authenticated age recovery bundles; never put private inputs in Git.

All temporary data stays on the destination filesystem. Restore authenticates
the complete ciphertext before parsing its archive and atomically installs only
after every file matches the encrypted manifest. Requires age >= 1.2.1.
"""
import argparse
import hashlib
import gzip
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile

CHUNK = 512 * 1024 * 1024
BLOCK = 1024 * 1024
# Schema 2 belongs to native-recovery-set, not a single encrypted payload.
PAYLOAD_SCHEMA = 3
PAYLOAD_KIND = 'native-recovery-bundle'


def payload_schema(value):
    if not isinstance(value, dict) or type(value.get('schema')) is not int:
        raise ValueError('Invalid recovery payload schema')
    version = value['schema']
    if version not in (1, PAYLOAD_SCHEMA) or (version == PAYLOAD_SCHEMA and value.get('kind') != PAYLOAD_KIND):
        raise ValueError('Unsupported recovery payload schema')
    return version


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_name(name):
    p = PurePosixPath(name)
    if (not name or p.is_absolute() or str(p) != name or '\\' in name
            or any(v in ('.', '..') for v in p.parts)):
        raise ValueError('Unsafe archive name')
    return p


def private_directory(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Symlink destination refused')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def age_tool():
    age = shutil.which('age')
    if not age:
        raise ValueError('Install age >= 1.2.1 first (apt install age / brew install age)')
    version = subprocess.check_output([age, '--version'], text=True).strip()
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', version)
    if not match or tuple(map(int, match.groups())) < (1, 2, 1):
        raise ValueError('Unsupported age version: ' + version)
    return age


def seal(args):
    destination = Path(args.destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('Bundle destination must be new')
    private_directory(destination.parent)
    roots = []
    for value in args.include:
        label, source = value.split('=', 1)
        if not re.fullmatch(r'[a-z][a-z0-9-]*', label) or label == 'manifest':
            raise ValueError('Invalid component label')
        source = Path(source).absolute()
        if any(p.is_symlink() for p in (source, *source.parents)) or not source.is_dir():
            raise ValueError('Input must be an ordinary directory')
        if source == destination or source in destination.parents or destination in source.parents:
            raise ValueError('Bundle and input must not overlap')
        roots.append((label, source))
    if len(set(k for k, _ in roots)) != len(roots) or not roots:
        raise ValueError('Duplicate or missing components')
    files = []
    total = 0
    for label, root in roots:
        for directory, dirs, names in os.walk(root, followlinks=False):
            for name in dirs:
                if (Path(directory)/name).is_symlink():
                    raise ValueError('Symlink input refused')
            for name in sorted(names):
                path = Path(directory)/name
                st = path.lstat()
                if not stat.S_ISREG(st.st_mode):
                    raise ValueError('Nonregular input refused')
                archive = label + '/' + path.relative_to(root).as_posix()
                safe_name(archive)
                files.append((archive, path, st))
                total += st.st_size
    # Ciphertext + split parts may briefly coexist; do not exhaust the volume.
    if shutil.disk_usage(destination.parent).free < total*2 + 1024**3:
        raise ValueError('Need twice the input size plus 1 GiB free on output volume')
    print(json.dumps(dict(phase='seal', files=len(files), input_bytes=total,
                          estimated_peak_extra_bytes=total*2+1024**3)), flush=True)
    stage = Path(tempfile.mkdtemp(prefix='.recovery-seal-', dir=destination.parent))
    try:
        ciphertext = stage/'payload.age'
        manifest = dict(schema=PAYLOAD_SCHEMA, kind=PAYLOAD_KIND, label=args.label, files=[], missing=args.missing,
                        completeness='partial' if args.missing else 'provided-inputs')
        proc = subprocess.Popen([age_tool(), '-R', args.recipients, '-o', str(ciphertext)], stdin=subprocess.PIPE)
        try:
            with gzip.GzipFile(fileobj=proc.stdin, mode='wb', compresslevel=1) as compressed, tarfile.open(fileobj=compressed, mode='w|') as archive:
                for i, (name, path, before) in enumerate(files):
                    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
                    with os.fdopen(os.open(path, flags), 'rb') as stream:
                        opened = os.fstat(stream.fileno())
                        if (opened.st_ino, opened.st_dev, opened.st_size, opened.st_mtime_ns) != (before.st_ino, before.st_dev, before.st_size, before.st_mtime_ns):
                            raise ValueError('Input changed before archiving')
                        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
                        stream.seek(0)
                        info = tarfile.TarInfo(name)
                        info.size = opened.st_size
                        # Preserve executable intent for the restoring owner,
                        # never group/world access or setuid/setgid/sticky bits.
                        info.mode = 0o700 if opened.st_mode & stat.S_IXUSR else 0o600
                        archive.addfile(info, stream)
                        after = os.fstat(stream.fileno())
                        if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns):
                            raise ValueError('Input changed during archiving')
                    manifest['files'].append(dict(path=name, bytes=opened.st_size, sha256=sha, mode=info.mode))
                    if i % 5000 == 0:
                        print(json.dumps(dict(phase='archive', files=i+1, total=len(files))), flush=True)
                raw = json.dumps(manifest, ensure_ascii=False).encode()
                info = tarfile.TarInfo('manifest.json'); info.size = len(raw); info.mode = 0o600
                archive.addfile(info, io.BytesIO(raw))
            proc.stdin.close()
            if proc.wait() != 0:
                raise ValueError('age encryption failed')
        finally:
            if proc.poll() is None:
                proc.terminate(); proc.wait()
        parts = []
        with ciphertext.open('rb') as stream:
            index = 0
            while raw := stream.read(CHUNK):
                name = f'payload-{index:05d}.age.part'
                path = stage/name; path.write_bytes(raw); path.chmod(0o600)
                parts.append(dict(name=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
                index += 1
        ciphertext.unlink()
        index = dict(schema=PAYLOAD_SCHEMA, kind=PAYLOAD_KIND, label=args.label, cipher='age', archive='tar.gz', parts=parts,
                     input_bytes=total, files=len(files), missing=args.missing,
                     completeness=manifest['completeness'])
        (stage/'index.json').write_text(json.dumps(index, indent=2)+'\n')
        os.rename(stage, destination)
        print(json.dumps(dict(phase='sealed', bundle=str(destination), parts=len(parts))), flush=True)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def restore(args):
    bundle = Path(args.bundle).resolve(strict=True)
    raw_index = (bundle/'index.json').read_bytes()
    if len(raw_index) > 1024*1024:
        raise ValueError('Oversized bundle index')
    index = json.loads(raw_index)
    version = payload_schema(index)
    if index.get('cipher') != 'age' or not index.get('parts'):
        raise ValueError('Invalid bundle index')
    parts = index['parts']
    if len(parts) > 10000:
        raise ValueError('Too many parts')
    for i, item in enumerate(parts):
        if item['name'] != f'payload-{i:05d}.age.part' or not 0 < item['bytes'] <= CHUNK:
            raise ValueError('Invalid part sequence')
        path = bundle/item['name']
        if path.is_symlink() or path.stat().st_size != item['bytes'] or digest(path) != item['sha256']:
            raise ValueError('Missing or corrupt encrypted part')
    destination = Path(args.destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('Restore destination must be new; existing games/saves are never overwritten')
    private_directory(destination.parent)
    if shutil.disk_usage(destination.parent).free < index['input_bytes']*2 + 1024**3:
        raise ValueError('Need twice the input size plus 1 GiB free for authenticated restore')
    stage = Path(tempfile.mkdtemp(prefix='.recovery-restore-', dir=destination.parent))
    try:
        payload = stage/'authenticated.tar.gz'
        with payload.open('xb') as output:
            proc = subprocess.Popen([age_tool(), '-d', '-i', args.identity], stdin=subprocess.PIPE, stdout=output)
            try:
                for item in parts:
                    with (bundle/item['name']).open('rb') as stream:
                        shutil.copyfileobj(stream, proc.stdin, BLOCK)
                proc.stdin.close()
                if proc.wait() != 0:
                    raise ValueError('age authentication failed; nothing was installed')
            finally:
                if proc.poll() is None:
                    proc.terminate(); proc.wait()
        root = stage/'restored'; root.mkdir(mode=0o700)
        seen = set(); expanded = 0; manifest = None
        with tarfile.open(payload, 'r|gz') as archive:
            for item in archive:
                safe_name(item.name)
                if item.name.casefold() == 'recovery-receipt.json':
                    raise ValueError('Reserved recovery receipt member')
                if not item.isfile() or item.name in seen or item.size < 0:
                    raise ValueError('Duplicate or nonregular archive member')
                seen.add(item.name); expanded += item.size
                if expanded > args.max_bytes:
                    raise ValueError('Archive exceeds configured expansion limit')
                stream = archive.extractfile(item)
                if item.name == 'manifest.json':
                    if item.size > 256*1024*1024:
                        raise ValueError('Oversized manifest')
                    manifest = json.load(stream)
                    continue
                path = root/item.name
                path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                with path.open('xb') as output:
                    shutil.copyfileobj(stream, output, BLOCK)
                path.chmod(0o600)
        if not manifest:
            raise ValueError('Encrypted manifest missing')
        if payload_schema(manifest) != version:
            raise ValueError('Encrypted manifest schema differs from bundle index')
        expected = manifest['files']
        names = [item['path'] for item in expected]
        if len(names) != len(set(names)) or set(names) != seen - {'manifest.json'}:
            raise ValueError('Manifest file set mismatch')
        permissions = []
        for item in expected:
            safe_name(item['path']); path = root/item['path']
            if path.stat().st_size != item['bytes'] or digest(path) != item['sha256']:
                raise ValueError('Restored content does not match encrypted manifest')
            # Old bundles have no authenticated executable metadata. Retain
            # their conservative 0600 behavior rather than guessing from names.
            mode = item.get('mode') if version == PAYLOAD_SCHEMA else 0o600
            if type(mode) is not int or mode not in (0o600, 0o700):
                raise ValueError('Invalid executable permission metadata')
            permissions.append((path, mode))
        for path, mode in permissions:
            path.chmod(mode)
        (root/'recovery-receipt.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
        (root/'recovery-receipt.json').chmod(0o600)
        os.rename(root, destination)
        print(json.dumps(dict(phase='restored', files=len(names), missing=manifest['missing'],
                             destination=str(destination))), flush=True)
    finally:
        shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('seal')
    p.add_argument('--label', required=True)
    p.add_argument('--include', action='append', required=True, help='dump=/private/path (repeatable)')
    p.add_argument('--missing', action='append', default=[])
    p.add_argument('--recipients', required=True, help='age public recipients file, never an identity')
    p.add_argument('--destination', required=True)
    p = commands.add_parser('restore')
    p.add_argument('--bundle', required=True)
    p.add_argument('--identity', required=True)
    p.add_argument('--destination', required=True)
    p.add_argument('--max-bytes', type=int, default=128*1024**3)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        (seal if args.command == 'seal' else restore)(args)
    except (OSError, ValueError, KeyError, BrokenPipeError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error)+'\n')


if __name__ == '__main__':
    main()
