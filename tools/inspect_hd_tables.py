# SPDX-License-Identifier: MIT
"""Read-only HD input diagnostics for an existing private TOTK installation.

Print metadata only; never extract, rewrite, enable a mod, or claim full RomFS
integrity from an index declaration. Game data and diagnostic output stay private.
"""
import argparse
import ast
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import stat
import struct
import zlib

MAX_INDEX = 64 << 20
MAX_RESOURCE = 32 << 20
HEAPDEF = 'System/HeapSize/Product.Nin_NX_NVN.HeapDef.byml.zs'
RESTBL = 'System/Resource/ResourceSizeTable.Product.143.Nin_NX_NVN.rsizetable.zs'
DICTIONARIES = 'Pack/ZsDic.pack.zs'


def canonical_profile():
    from linux_inputs import expected, ROOT
    values = expected()
    source = ROOT/'tools/deck_font_world.py'
    assignments = {}
    for node in ast.parse(source.read_text()).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in ('RESTBL', 'RESTBL_SHA')):
            assignments[node.targets[0].id] = ast.literal_eval(node.value)
    if assignments.get('RESTBL') != RESTBL:
        raise ValueError('Unsupported controlled RESTBL profile')
    return dict(values, version='1.4.3', RESTBL_SHA256=assignments['RESTBL_SHA'],
                profile_source_sha256={name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                    for name in ('tools/setup_windows.py', 'tools/deck_font_world.py')})


@contextmanager
def checked_file(root, relative, maximum):
    """Pin each directory/file FD; no symlinks, special files, or changed reads."""
    path = PurePosixPath(relative)
    if path.is_absolute() or '..' in path.parts or path.as_posix() != relative:
        raise ValueError('Invalid input path')
    flags = os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC|os.O_NOFOLLOW
    parent = os.open(root, flags)
    try:
        for part in path.parts[:-1]:
            child = os.open(part, flags, dir_fd=parent)
            os.close(parent); parent = child
        fd = os.open(path.name, os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW|os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
                raise ValueError('Input is not a bounded regular file: '+relative)
            yield stream
            after = os.fstat(stream.fileno())
            stamp = lambda s:(s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            if stamp(before) != stamp(after):
                raise ValueError('Input changed during inspection: '+relative)
    finally:
        os.close(parent)


class Byml:
    """Bounded little-endian BYML hash/scalar reader, not a rewriting codec."""
    def __init__(self, raw):
        self.raw = raw
        if len(raw) < 16 or raw[:2] != b'YB' or not 2 <= self.number(2, '<H') <= 7:
            raise ValueError('Unsupported HeapDef BYML header')
        self.version = self.number(2, '<H')
        self.keys, self.strings, self.root = struct.unpack_from('<III', raw, 4)
        self.fields_remaining = 8192

    def number(self, at, kind='<I'):
        if at < 0 or at+struct.calcsize(kind) > len(self.raw):
            raise ValueError('BYML value exceeds its file')
        return struct.unpack_from(kind, self.raw, at)[0]

    def head(self, at, kind, width):
        head = self.number(at); count = head >> 8
        if head & 255 != kind or count > 65536 or at+4+width*count > len(self.raw):
            raise ValueError('Invalid BYML node type/count/range')
        return count

    def string(self, table, index):
        count = self.head(table, 0xc2, 4)
        if not 0 <= index < count:
            raise ValueError('BYML string index is outside its table')
        offset = self.number(table+4+4*index)
        if offset < 4+4*count or table+offset >= len(self.raw):
            raise ValueError('BYML string offset is outside its payload')
        start = table+offset; end = self.raw.find(b'\0', start, min(len(self.raw), start+4096))
        if end < 0:
            raise ValueError('Unterminated or oversized BYML string')
        return self.raw[start:end].decode('utf-8')

    def fields(self, node):
        count = self.head(node, 0xc1, 8); result = {}
        if count > self.fields_remaining:
            raise ValueError('BYML field traversal exceeds its work budget')
        self.fields_remaining -= count
        for i in range(count):
            key, value = struct.unpack_from('<II', self.raw, node+4+8*i)
            name = self.string(self.keys, key & 0xffffff)
            if name in result:
                raise ValueError('Duplicate BYML key')
            result[name] = (key >> 24, value)
        return result

    def scalar(self, kind, value):
        if kind == 0xa0:
            return self.string(self.strings, value)
        if kind == 0xd0:
            if value not in (0, 1): raise ValueError('Invalid BYML boolean')
            return bool(value)
        if kind == 0xd1:
            return value if value < 2**31 else value-2**32
        if kind == 0xd3:
            return value
        if kind == 0xd2:
            result = struct.unpack('<f', struct.pack('<I', value))[0]
        elif kind in (0xd4, 0xd5, 0xd6):
            result = self.number(value, {0xd4:'<q', 0xd5:'<Q', 0xd6:'<d'}[kind])
        else:
            return {'uninterpreted_type':hex(kind)}
        if isinstance(result, float) and not math.isfinite(result):
            raise ValueError('Non-finite BYML scalar')
        return result

    def heaps(self):
        kind, node = self.fields(self.root).get('Heaps', (None, None))
        if kind != 0xc1:
            raise ValueError('HeapDef has no supported Heaps dictionary')
        entries = self.fields(node)
        if not 1 <= len(entries) <= 1024:
            raise ValueError('HeapDef heap inventory exceeds its budget')
        result = {}
        for name, (kind, node) in entries.items():
            if kind != 0xc1:
                raise ValueError('HeapDef heap is not a dictionary')
            result[name] = {key:self.scalar(*value) for key, value in self.fields(node).items()}
        for name in ('Graphics', 'DynamicTextureAllocatorMem'):
            size = result.get(name, {}).get('Size')
            if type(size) is not int or size <= 0:
                raise ValueError('Missing positive target heap size: '+name)
        return result


def dictionary_members(raw):
    """Read SARC dictionary members in memory, with no member extraction."""
    if len(raw) < 32 or raw[:4] != b'SARC' or raw[6:8] != b'\xff\xfe':
        raise ValueError('Unsupported dictionary SARC')
    header, size, start = struct.unpack_from('<HxxII', raw, 4)
    if header != 20 or size != len(raw) or raw[header:header+4] != b'SFAT':
        raise ValueError('Invalid dictionary SARC layout')
    count = struct.unpack_from('<H', raw, header+6)[0]
    if not 1 <= count <= 32 or not header+12+16*count+8 <= start <= size:
        raise ValueError('Invalid dictionary SARC inventory')
    spans = []
    for i in range(count):
        _, attr, low, high = struct.unpack_from('<4I', raw, header+12+16*i)
        if attr >> 24 != 1 or not 0 <= low < high <= size-start:
            raise ValueError('Invalid dictionary member range')
        spans.append((start+low, start+high))
    if any(a[1] > b[0] for a, b in zip(sorted(spans), sorted(spans)[1:])):
        raise ValueError('Overlapping dictionary members')
    return [raw[low:high] for low, high in spans]


def restbl_summary(raw):
    if len(raw) < 22 or raw[:6] != b'RESTBL':
        raise ValueError('Invalid RESTBL header')
    version, width, count, collisions = struct.unpack_from('<4I', raw, 6)
    if version != 1 or not 1 <= width <= 4096 or 22+8*count+collisions*(width+4) != len(raw):
        raise ValueError('Unsupported RESTBL layout')
    previous = -1; heap_allocation = None
    wanted = zlib.crc32(HEAPDEF.removesuffix('.zs').encode())
    for i in range(count):
        crc, value = struct.unpack_from('<II', raw, 22+8*i)
        if crc <= previous: raise ValueError('Unsorted RESTBL resource hashes')
        previous = crc
        if crc == wanted: heap_allocation = value
    for i in range(collisions):
        name = raw[22+8*count+i*(width+4):22+8*count+i*(width+4)+width]
        if b'\0' not in name: raise ValueError('Unterminated RESTBL collision name')
    return dict(version=version, crc_entries=count, collision_entries=collisions,
                collision_name_width=width, heapdef_crc_allocation_raw=heap_allocation)


def inspect_release(root, profile):
    """Caller supplies a controlled profile, never one read from a mod/dump."""
    import zstd_codec as zstd
    root = Path(root).resolve(strict=True)
    if profile.get('version') != '1.4.3' or set(profile.get('EXEFS', {})) != {'main','subsdk0','sdk'}:
        raise ValueError('Unsupported controlled version profile')
    hashes = {}
    for name, expected in profile['EXEFS'].items():
        with checked_file(root, 'data/exefs/'+name, 256 << 20) as stream:
            hashes[name] = hashlib.file_digest(stream, 'sha256').hexdigest()
        if hashes[name] != expected:
            raise ValueError('Original ExeFS fingerprint differs: '+name)
    with checked_file(root, 'data/romfs/index.json', MAX_INDEX) as stream:
        raw_index = stream.read(MAX_INDEX+1)
    if len(raw_index) > MAX_INDEX:
        raise ValueError('Packed index exceeds its read budget')
    index_sha = hashlib.sha256(raw_index).hexdigest(); index = json.loads(raw_index); del raw_index
    rows = index.get('files'); previous = ''; end = total = 0; selected = {}
    if not isinstance(rows, list) or len(rows) != profile['ROMFS_FILES']:
        raise ValueError('Packed file count differs from controlled profile')
    for row in rows:
        if not isinstance(row, dict): raise ValueError('Invalid packed index row')
        name, offset, size = row.get('path'), row.get('offset'), row.get('size')
        if (not isinstance(name, str) or '\\' in name or '\0' in name or name <= previous
                or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts
                or PurePosixPath(name).as_posix() != name or type(size) is not int or size < 0
                or type(offset) is not int or offset != (end+15)//16*16):
            raise ValueError('Invalid packed resource index')
        previous, end, total = name, offset+size, total+size
        if name in (HEAPDEF, RESTBL, DICTIONARIES): selected[name] = row
    if total != profile['ROMFS_BYTES'] or index.get('content_sha256') != profile['ROMFS_CONTENT']:
        raise ValueError('Packed index context differs from controlled profile')
    if set(selected) != {HEAPDEF, RESTBL, DICTIONARIES}:
        raise ValueError('Required HD source resources are missing')
    del index, rows
    with checked_file(root, 'data/romfs/romfs.bin', end) as image:
        if os.fstat(image.fileno()).st_size != end:
            raise ValueError('Packed image length differs from its index')
        def read(name):
            row = selected[name]
            if not 0 < row['size'] <= MAX_RESOURCE: raise ValueError('Oversized resource: '+name)
            image.seek(row['offset']); raw = image.read(row['size'])
            if len(raw) != row['size']: raise ValueError('Truncated packed resource')
            return raw
        dictionaries = dictionary_record = None
        def decode(raw):
            nonlocal dictionaries, dictionary_record
            info = zstd.get_frame_info(raw)
            if info.decompressed_size is None or info.decompressed_size > MAX_RESOURCE:
                raise ValueError('Unbounded or oversized resource frame')
            if info.dictionary_id and dictionaries is None:
                packed = read(DICTIONARIES); frame = zstd.get_frame_info(packed)
                if frame.dictionary_id or frame.decompressed_size is None or frame.decompressed_size > MAX_RESOURCE:
                    raise ValueError('Unsupported dictionary container frame')
                dictionaries = {}
                for member in dictionary_members(zstd.decompress(packed)):
                    item = zstd.ZstdDict(member)
                    if item.dict_id in dictionaries: raise ValueError('Duplicate dictionary identity')
                    dictionaries[item.dict_id] = item
                dictionary_record = dict(compressed_sha256=hashlib.sha256(packed).hexdigest(),
                    members={str(key):hashlib.sha256(item.data).hexdigest()
                             for key, item in dictionaries.items()})
            dictionary = (dictionaries or {}).get(info.dictionary_id) if info.dictionary_id else None
            return zstd.decompress(raw, zstd_dict=dictionary)
        heap_raw, table_raw = read(HEAPDEF), read(RESTBL)
        if hashlib.sha256(table_raw).hexdigest() != profile['RESTBL_SHA256']:
            raise ValueError('Controlled original RESTBL fingerprint differs')
        heap_data, table_data = decode(heap_raw), decode(table_raw)
        byml = Byml(heap_data); heaps = byml.heaps()
    selected_heaps = {}
    pending = [name for name in heaps if 'texture' in name.lower() or name == 'Graphics']
    while pending:
        name = pending.pop()
        if name in selected_heaps: continue
        selected_heaps[name] = heaps[name]
        if len(selected_heaps) > 64:
            raise ValueError('Selected heap metadata exceeds its report budget')
        # Preserve named references for inspection; do not infer root-heap types.
        pending.extend(value for value in heaps[name].values()
                       if isinstance(value, str) and value in heaps and value not in selected_heaps)
    return dict(schema=1, kind='totk-hd-input-inspection', version='1.4.3', read_only=True,
        profile_source_sha256=profile['profile_source_sha256'], exefs_sha256=hashes,
        romfs_context=dict(index_sha256=index_sha, files=profile['ROMFS_FILES'], bytes=total,
                           index_declaration_matched=True, full_payload_hash_verified=False),
        heapdef=dict(path=HEAPDEF, compressed_sha256=hashlib.sha256(heap_raw).hexdigest(),
                     decoded_sha256=hashlib.sha256(heap_data).hexdigest(), decoded_bytes=len(heap_data),
                     version=byml.version, original_pin_verified=False, heap_count=len(heaps),
                     selected_heaps=selected_heaps),
        restbl=dict(path=RESTBL, compressed_sha256=hashlib.sha256(table_raw).hexdigest(),
                    decoded_bytes=len(table_data), original_pin_verified=True, **restbl_summary(table_data)),
        dictionary_sources=dictionary_record, hardware_validated=False, hd_heap_expansion_validated=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = inspect_release(args.release, canonical_profile())
        result['diagnostic_source_sha256'] = {
            name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
            for name in ('inspect_hd_tables.py', 'zstd_codec.py')}
        report = json.dumps(result, ensure_ascii=False, indent=2)
        if len(report.encode()) > 32 << 10:
            raise ValueError('Metadata report exceeds its output budget')
        print(report)
    except (OSError, ValueError, KeyError, struct.error, MemoryError) as error:
        parser.exit(1, str(error)+'\n')


if __name__ == '__main__':
    main()
