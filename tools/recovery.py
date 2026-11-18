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
import threading

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
    # A Deck that has just been reset usually has age in a project-owned folder rather than on
    # PATH, and the recovery run is exactly the moment when editing the shell profile is the last
    # thing a player wants. NATIVE_AGE names the binary (a path, or a bare program name) and is
    # checked the same way as the PATH lookup; nothing about the format or the checks loosens.
    override = (os.environ.get('NATIVE_AGE') or '').strip()
    if override:
        age = override if os.sep in override else shutil.which(override)
    else:
        age = shutil.which('age')
    if not age:
        raise ValueError('Install age >= 1.2.1 first (apt install age / brew install age), '
                         'or point NATIVE_AGE at an existing age binary')
    version = subprocess.check_output([age, '--version'], text=True).strip()
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', version)
    if not match or tuple(map(int, match.groups())) < (1, 2, 1):
        raise ValueError('Unsupported age version: ' + version)
    return age


def stop_process(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def age_pipe(command, produce, consume):
    """Bounded pipes, with producer errors and age exit checked before return."""
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    errors = []

    def feed():
        try:
            with proc.stdin:
                produce(proc.stdin)
        except BaseException as error:
            errors.append(error)
            stop_process(proc)

    worker = threading.Thread(target=feed, name='recovery-age-input')
    worker.start()
    try:
        result = consume(proc.stdout)
        # A tar reader may stop at its end markers before age exits. Always
        # consume the entire output and check its authentication result.
        while proc.stdout.read(BLOCK):
            pass
        worker.join()
        status = proc.wait()
        if errors and not (status and isinstance(errors[0], BrokenPipeError)):
            raise errors[0]
        if status:
            raise ValueError('age failed; nothing was installed')
        return result
    except BaseException as error:
        stop_process(proc)
        worker.join()
        # A changed input can terminate age before an archive header arrives.
        # Report that checked input failure rather than a secondary tar error.
        if errors and isinstance(errors[0], ValueError):
            raise errors[0] from error
        raise
    finally:
        stop_process(proc)
        worker.join()
        proc.stdout.close()


def split_ciphertext(stream, stage):
    parts = []
    while True:
        raw = stream.read(min(BLOCK, CHUNK))
        if not raw:
            return parts
        name = f'payload-{len(parts):05d}.age.part'
        sha = hashlib.sha256()
        size = 0
        with (stage/name).open('xb') as output:
            os.chmod(stage/name, 0o600)
            while raw:
                output.write(raw)
                sha.update(raw)
                size += len(raw)
                if size == CHUNK:
                    break
                raw = stream.read(min(BLOCK, CHUNK-size))
            output.flush()
            os.fsync(output.fileno())
        parts.append(dict(name=name, bytes=size, sha256=sha.hexdigest()))


def feed_parts(bundle, parts, output):
    """Recheck bytes on each pass; never trust an earlier path hash alone."""
    for item in parts:
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
        with os.fdopen(os.open(bundle/item['name'], flags), 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size != item['bytes']:
                raise ValueError('Encrypted part changed')
            sha = hashlib.sha256()
            size = 0
            while raw := stream.read(BLOCK):
                size += len(raw)
                if size > item['bytes']:
                    raise ValueError('Encrypted part grew')
                sha.update(raw)
                output.write(raw)
            after = os.fstat(stream.fileno())
            if (size != item['bytes'] or sha.hexdigest() != item['sha256']
                    or (before.st_ino, before.st_dev, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_ino, after.st_dev, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
                raise ValueError('Encrypted part changed')


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
    low_peak = getattr(args, 'low_peak', False)
    # Direct splitting removes the full ciphertext intermediate. The extra
    # GiB covers gzip/tar overhead and the manifest; no reserve is reduced.
    peak = total*(1 if low_peak else 2) + 1024**3
    if shutil.disk_usage(destination.parent).free < peak:
        raise ValueError('Insufficient free space for recovery seal peak')
    print(json.dumps(dict(phase='seal', files=len(files), input_bytes=total,
                          low_peak=low_peak, estimated_peak_extra_bytes=peak)), flush=True)
    stage = Path(tempfile.mkdtemp(prefix='.recovery-seal-', dir=destination.parent))
    try:
        ciphertext = stage/'payload.age'
        manifest = dict(schema=PAYLOAD_SCHEMA, kind=PAYLOAD_KIND, label=args.label, files=[], missing=args.missing,
                        completeness='partial' if args.missing else 'provided-inputs')
        def write_archive(output):
            with gzip.GzipFile(fileobj=output, mode='wb', compresslevel=1) as compressed, tarfile.open(fileobj=compressed, mode='w|') as archive:
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
        if low_peak:
            parts = age_pipe([age_tool(), '-R', args.recipients], write_archive,
                             lambda stream: split_ciphertext(stream, stage))
        else:
            proc = subprocess.Popen([age_tool(), '-R', args.recipients, '-o', str(ciphertext)], stdin=subprocess.PIPE)
            try:
                write_archive(proc.stdin)
                proc.stdin.close()
                if proc.wait() != 0:
                    raise ValueError('age encryption failed')
            finally:
                stop_process(proc)
            with ciphertext.open('rb') as stream:
                parts = split_ciphertext(stream, stage)
            ciphertext.unlink()
        if not parts:
            raise ValueError('Empty ciphertext')
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
    low_peak = getattr(args, 'low_peak', False)
    total = index['input_bytes']
    if type(total) is not int or total < 0:
        raise ValueError('Invalid input byte budget')
    peak = total*(1 if low_peak else 2) + 1024**3
    if shutil.disk_usage(destination.parent).free < peak:
        raise ValueError('Insufficient free space for authenticated restore peak')
    command = [age_tool(), '-d', '-i', args.identity]
    produce = lambda output: feed_parts(bundle, parts, output)
    if low_peak:
        # First pass must authenticate the COMPLETE ciphertext before even
        # creating an extraction stage. Its plaintext is discarded immediately.
        age_pipe(command, produce, lambda stream: None)
        print(json.dumps(dict(phase='authenticated', low_peak=True,
                              estimated_peak_extra_bytes=peak)), flush=True)
    stage = Path(tempfile.mkdtemp(prefix='.recovery-restore-', dir=destination.parent))
    try:
        payload = stage/'authenticated.tar.gz'
        if not low_peak:
            with payload.open('xb') as output:
                age_pipe(command, produce, lambda stream: shutil.copyfileobj(stream, output, BLOCK))
        root = stage/'restored'; root.mkdir(mode=0o700)

        def extract(stream):
            seen = set(); expanded = 0; data_bytes = 0; manifest = None
            with tarfile.open(fileobj=stream, mode='r|gz') as archive:
                for item in archive:
                    safe_name(item.name)
                    if item.name.casefold() == 'recovery-receipt.json':
                        raise ValueError('Reserved recovery receipt member')
                    if not item.isfile() or item.name in seen or item.size < 0:
                        raise ValueError('Duplicate or nonregular archive member')
                    seen.add(item.name); expanded += item.size
                    if expanded > args.max_bytes:
                        raise ValueError('Archive exceeds configured expansion limit')
                    member = archive.extractfile(item)
                    if item.name == 'manifest.json':
                        if item.size > 256*1024*1024:
                            raise ValueError('Oversized manifest')
                        manifest = json.load(member)
                        continue
                    data_bytes += item.size
                    if low_peak and data_bytes > total:
                        raise ValueError('Archive exceeds declared input byte budget')
                    path = root/item.name
                    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                    with path.open('xb') as output:
                        shutil.copyfileobj(member, output, BLOCK)
                    path.chmod(0o600)
            if low_peak and data_bytes != total:
                raise ValueError('Archive differs from declared input byte budget')
            return seen, manifest

        if low_peak:
            # Every part is rehashed as it feeds the second pass. No file is
            # published unless this pass also exits with successful age auth.
            seen, manifest = age_pipe(command, produce, extract)
        else:
            with payload.open('rb') as stream:
                seen, manifest = extract(stream)
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
    p.add_argument('--low-peak', action='store_true', help='Stream parts; restore authenticates once before a second extraction pass')
    p = commands.add_parser('restore')
    p.add_argument('--bundle', required=True)
    p.add_argument('--identity', required=True)
    p.add_argument('--destination', required=True)
    p.add_argument('--low-peak', action='store_true', help='Stream parts; restore authenticates once before a second extraction pass')
    p.add_argument('--max-bytes', type=int, default=128*1024**3)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        (seal if args.command == 'seal' else restore)(args)
    except (OSError, ValueError, KeyError, EOFError, tarfile.TarError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error)+'\n')


if __name__ == '__main__':
    main()
