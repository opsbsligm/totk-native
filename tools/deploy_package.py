"""Install a verified private package as a Steam Deck release and swap ``current``.

Runs on the Deck beside an existing layout of ``<root>/releases/<id>`` plus a
``current`` symlink.  Every file is checked against the package manifest before
anything is installed, and unchanged data files are hardlinked from the release
being replaced so a rebuild does not strand a second private game tree on /home.
The release that was current stays installed and is recorded in ``previous``, so
a bad build is one symlink away from being undone.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

MANIFEST = 'bundle.json'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_manifest(package):
    path = Path(package) / MANIFEST
    if not path.is_file():
        raise ValueError('Package has no ' + MANIFEST)
    data = json.loads(path.read_text())
    files = data.get('files')
    if (data.get('schema') != 1 or not isinstance(files, dict) or not files
            or not isinstance(data.get('source_commit'), str)
            or any(not isinstance(r, dict) or 'size' not in r or 'sha256' not in r
                   for r in files.values())):
        raise ValueError('Invalid package manifest')
    return data


def verify_package(package):
    """Check inventory and every file against the manifest; return the manifest.

    The manifest describes every other file but does not list itself, so it is the
    one path allowed outside the recorded inventory.
    """
    package = Path(package)
    manifest = load_manifest(package)
    actual = set()
    for path in package.rglob('*'):
        if path.is_symlink():
            raise ValueError('Package files must not be symlinks: ' + str(path))
        if path.is_file():
            actual.add(path.relative_to(package).as_posix())
    if actual != set(manifest['files']) | {MANIFEST}:
        raise ValueError('Package inventory differs from manifest')
    for name, record in manifest['files'].items():
        path = package / name
        if path.stat().st_size != record['size'] or digest(path) != record['sha256']:
            raise ValueError('Package file changed since packaging: ' + name)
    return manifest


def _place(source, destination, relative, expected_sha256, reference):
    """Hardlink from the reference release when its bytes already match, else move."""
    twin = reference / relative
    if twin.is_file() and digest(twin) == expected_sha256:
        os.link(twin, destination)
        source.unlink()
        return 'linked'
    try:
        os.rename(source, destination)
    except OSError as error:
        if error.errno != 18:  # EXDEV: cross-device, so fall back to a copy
            raise
        shutil.copy2(source, destination)
        source.unlink()
    return 'moved'


def install(package, root, release_id, reference=None):
    """Verify, install under root/releases/<id>, and atomically swap current.

    Returns (release_path, previous_target_or_None, counts).
    """
    package, root = Path(package).resolve(), Path(root).resolve()
    verify_package(package)
    if not release_id or Path(release_id).name != release_id or release_id.startswith('.'):
        raise ValueError('Invalid release id: ' + release_id)
    releases = root / 'releases'
    releases.mkdir(parents=True, exist_ok=True)
    target = releases / release_id
    counts = dict(linked=0, moved=0)
    if target.exists():
        if not (target / MANIFEST).is_file() or digest(target / MANIFEST) != digest(package / MANIFEST):
            raise ValueError('Release id already exists with different content: ' + release_id)
        counts['identical'] = 1
        shutil.rmtree(package)
    else:
        # The package is already fully verified, so files move straight into their
        # final release directory.  Nothing reads a release until ``current`` points
        # at it, and a half-built directory is removed again below rather than
        # published.
        ref = Path(reference).resolve() if reference is not None and Path(reference).is_dir() else None
        files = json.loads((package / MANIFEST).read_text())['files']
        try:
            for path in sorted(p for p in package.rglob('*') if p.is_file()):
                relative = path.relative_to(package)
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                if ref is None or relative.as_posix() == MANIFEST:
                    os.rename(path, destination)
                    counts['moved'] += 1
                    continue
                counts[_place(path, destination, relative,
                              files[relative.as_posix()]['sha256'], ref)] += 1
        except BaseException:
            shutil.rmtree(target, ignore_errors=True)
            raise
        for path in sorted((p for p in package.rglob('*') if p.is_dir()), reverse=True):
            path.rmdir()
        package.rmdir()
    link = root / 'current'
    previous = Path(os.readlink(link)).as_posix() if link.is_symlink() else None
    temporary = root / ('current.' + str(os.getpid()))
    os.symlink('releases/' + release_id, temporary)
    os.replace(temporary, link)
    (root / 'previous').write_text((previous or '') + '\n')
    return target, previous, counts


def rollback(root):
    """Point current back at the previous release, recording where it was."""
    root = Path(root)
    marker = root / 'previous'
    if not marker.is_file():
        raise ValueError('No previous-release marker under ' + str(root))
    name = marker.read_text().strip()
    candidate = root / name if name else None
    if candidate is None or not candidate.is_dir() or not (candidate / MANIFEST).is_file():
        raise ValueError('Previous release is gone: ' + name)
    link = root / 'current'
    left = Path(os.readlink(link)).as_posix() if link.is_symlink() else ''
    temporary = root / ('current.' + str(os.getpid()))
    os.symlink(name, temporary)
    os.replace(temporary, link)
    marker.write_text(left + '\n')
    return candidate, left


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package', type=Path, help='pipeline.py package output directory')
    p.add_argument('--root', type=Path, required=True, help='Deck layout root holding releases/ and current')
    p.add_argument('--id', help='release id; default <utc date>-<source commit 12>')
    p.add_argument('--reference', type=Path, help='release to hardlink identical files from; default current')
    p.add_argument('--rollback', action='store_true', help='restore the previous release and exit')
    a = p.parse_args()
    try:
        if a.rollback:
            restored, left = rollback(a.root)
            print(json.dumps(dict(action='rollback', current=str(restored), rolled_back_from=left)))
            return 0
        if a.package is None:
            p.error('--package is required unless --rollback is used')
        commit = load_manifest(a.package)['source_commit']
        if a.id is None and (len(commit) < 12
                or not all(c in '0123456789abcdef' for c in commit[:12])):
            p.error('cannot derive a release id from source_commit; pass --id')
        release_id = a.id or time.strftime('%Y%m%d', time.gmtime()) + '-' + commit[:12]
        reference = a.reference
        if reference is None and (a.root / 'current').is_symlink():
            reference = Path(os.readlink(a.root / 'current'))
            reference = reference if reference.is_absolute() else a.root / reference
        target, previous, counts = install(a.package, a.root, release_id, reference)
        print(json.dumps(dict(action='install', release=str(target), previous=previous,
                              source_commit=commit, files=counts)))
        return 0
    except (ValueError, OSError) as error:
        print('deploy refused: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
