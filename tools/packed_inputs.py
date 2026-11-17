"""Validate a locally packed RomFS against the exact upstream content fingerprint."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import os
import shutil


def rows_for(root):
    root = Path(root)
    for name in ('romfs.bin', 'index.json'):
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Packed RomFS requires regular ' + name)
    document = json.loads((root / 'index.json').read_text())
    rows = document.get('files')
    if not isinstance(rows, list) or not rows:
        raise ValueError('Missing packed file index')
    previous, names, end = '', set(), 0
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid packed index entry')
        name = row.get('path')
        if not isinstance(name, str) or not name or '\\' in name or '\0' in name:
            raise ValueError('Invalid packed file path')
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or path.as_posix() != name:
            raise ValueError('Packed file path escapes its namespace')
        if name <= previous or name in names:
            raise ValueError('Packed index must be sorted and unique')
        offset, size = row.get('offset'), row.get('size')
        if type(offset) is not int or type(size) is not int or size < 0 or offset != (end + 15) // 16 * 16:
            raise ValueError('Invalid or overlapping packed file range')
        end = offset + size
        previous = name
        names.add(name)
    if (root / 'romfs.bin').stat().st_size != end:
        raise ValueError('Packed image is truncated or contains trailing data')
    return rows


def validate(root, expected):
    root = Path(root)
    rows = rows_for(root)
    if len(rows) != expected['ROMFS_FILES'] or sum(r['size'] for r in rows) != expected['ROMFS_BYTES']:
        raise ValueError('Packed content count/size differs from TOTK 1.4.3')
    content = hashlib.sha256()
    with (root / 'romfs.bin').open('rb') as stream:
        for row in rows:
            stream.seek(row['offset'])
            remaining, digest = row['size'], hashlib.sha256()
            while remaining:
                block = stream.read(min(1024 * 1024, remaining))
                if not block:
                    raise ValueError('Packed file changed or is truncated')
                digest.update(block)
                remaining -= len(block)
            content.update(digest.digest())
    if content.hexdigest() != expected['ROMFS_CONTENT']:
        raise ValueError('Packed RomFS content differs from TOTK 1.4.3')
    return content.hexdigest()


def import_packed(root, output, expected):
    validate(root, expected)
    output.mkdir(parents=True, exist_ok=True)
    for name in ('romfs.bin', 'index.json'):
        source, destination = Path(root) / name, output / name
        # A work area seeded with hardlinks from an installed release (see
        # tools/deploy_package.py) presents the verified bytes in place, so a
        # copy would either fail as SameFile or strand a second 17 GiB image.
        # validate() already authenticated the content, so it is safe to keep.
        if destination.exists() and os.path.samefile(source, destination):
            continue
        shutil.copy2(source, destination)
