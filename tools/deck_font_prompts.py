"""Build six narrow private UI resources without rewriting original RomFS.

Menu and world icon fonts are distinct. Unrelated SARC members stay byte exact;
allocation sizes grow with the new fonts and verified controller geometry.
No game assets ship with this source. BFOTF interoperability follows MacNativeGames' MIT tool;
see licenses/MacNativeGames.txt and NOTICE.md.
"""
# SPDX-License-Identifier: MIT
import argparse
import hashlib
import json
from pathlib import Path
import struct

from deck_font_glyphs import patch_external
import deck_font_world as world
from romfs import RomFS
import zstd_codec as zstd

FONT_PATHS = tuple('Font/' + name + '.bfarc.zs' for name in (
    'Font.Nin_NX_NVN', 'Font_CNzh.Nin_NX_NVN',
    'Font_KRko.Nin_NX_NVN', 'Font_TWzh.Nin_NX_NVN'))
PATHS = FONT_PATHS + (world.COMMON, world.RESTBL)
MAX_ARCHIVE = 32 << 20


def members(data):
    if len(data) < 32 or data[:4] != b'SARC' or data[6:8] != b'\xff\xfe':
        raise ValueError('Unsupported SARC header')
    header, size, start = struct.unpack_from('<HxxII', data, 4)
    if header != 20 or size != len(data) or not header + 12 <= start <= size or data[header:header + 4] != b'SFAT':
        raise ValueError('Invalid SARC layout')
    count = struct.unpack_from('<H', data, header + 6)[0]
    names = header + 12 + 16 * count
    if names + 8 > start or data[names:names + 4] != b'SFNT':
        raise ValueError('Invalid SARC name table')
    names += 8
    out = {}
    for i in range(count):
        _, attr, lo, hi = struct.unpack_from('<4I', data, header + 12 + i * 16)
        at = names + 4 * (attr & 0xffffff)
        if attr >> 24 != 1 or not names <= at < start or not 0 <= lo <= hi <= size - start:
            raise ValueError('Invalid SARC member')
        end = data.find(b'\0', at, start)
        if end < 0:
            raise ValueError('Unterminated SARC member name')
        name = data[at:end].decode('utf-8')
        if name in out or any(max(start + lo, a) < min(start + hi, b) for a, b in out.values()):
            raise ValueError('Duplicate or overlapping SARC member')
        out[name] = (start + lo, start + hi)
    return out


def font_body(blob):
    if len(blob) < 8:
        raise ValueError('Truncated BFOTF')
    key = struct.unpack_from('<I', blob)[0] ^ 0x18029a7f
    size = int.from_bytes(struct.pack('<I', struct.unpack_from('<I', blob, 4)[0] ^ key), 'big')
    if size != len(blob) - 8:
        raise ValueError('Unexpected BFOTF size')
    body = bytearray(blob[8:])
    for at in range(0, size - size % 4, 4):
        struct.pack_into('<I', body, at, struct.unpack_from('<I', body, at)[0] ^ key)
    return bytes(body), key


def patch_archive(archive):
    entries = members(archive)
    if 'scft/External.bfotf' not in entries:
        raise ValueError('Missing External icon font')
    lo, hi = entries['scft/External.bfotf']
    blob = archive[lo:hi]
    body, key = font_body(blob)
    patched = bytearray(patch_external(body))
    for at in range(0, len(patched) - len(patched) % 4, 4):
        struct.pack_into('<I', patched, at, struct.unpack_from('<I', patched, at)[0] ^ key)
    result = archive[:lo + 8] + patched + archive[hi:]
    if len(result) != len(archive) or result[:lo + 8] != archive[:lo + 8] or result[hi:] != archive[hi:]:
        raise ValueError('Font replacement changed unrelated archive bytes')
    return result


def build(root, output):
    if not __debug__:
        raise RuntimeError('Do not disable resource validation with Python -O')
    rom = RomFS(root)
    dictionary_pack = zstd.decompress(rom.read('Pack/ZsDic.pack.zs'))
    dictionaries = {}
    for lo, hi in members(dictionary_pack).values():
        dictionary = zstd.ZstdDict(dictionary_pack[lo:hi])
        if dictionary.dict_id in dictionaries:
            raise ValueError('Duplicate Zstandard dictionary identity')
        dictionaries[dictionary.dict_id] = dictionary
    if output.exists():
        raise ValueError('Refusing to overwrite existing Deck font outputs')
    output.mkdir(parents=True)
    records, manifest, growth = bytearray(b'NDUIF002'), [], {}
    for index, path in enumerate(PATHS):
        original = rom.read(path)
        if not 0 < len(original) <= MAX_ARCHIVE:
            raise ValueError('Font archive size outside supported bounds')
        pinned = world.COMMON_SHA if path == world.COMMON else world.RESTBL_SHA if path == world.RESTBL else None
        if pinned and hashlib.sha256(original).hexdigest() != pinned:
            raise ValueError('Unsupported original UI resource')
        info = zstd.get_frame_info(original)
        dictionary = dictionaries.get(info.dictionary_id)
        archive = zstd.decompress(original, zstd_dict=dictionary)
        if index < 4:
            patched = world.font_archive(archive, patch_archive(archive))
        elif path == world.COMMON:
            patched = world.common_archive(original, archive)
        else:
            patched = world.allocation_table(archive, growth)
        if path != world.RESTBL and len(patched) > len(archive):
            growth[path] = ((len(patched) - len(archive) + 0xffff) & ~0xffff) + 0x10000
        encoded = zstd.compress(patched, zstd_dict=dictionary)
        if not 0 < len(encoded) <= MAX_ARCHIVE:
            raise ValueError('Patched font archive exceeds runtime limit')
        old_hash, new_hash = hashlib.sha256(original).digest(), hashlib.sha256(encoded).digest()
        records.extend(struct.pack('<QQ', len(original), len(encoded)) + old_hash + new_hash)
        (output / (str(index) + '.zs')).write_bytes(encoded)
        manifest.append(dict(path=path, original_sha256=old_hash.hex(), patched_sha256=new_hash.hex(),
                             original_size=len(original), patched_size=len(encoded), archive_size=len(archive),
                             patched_archive_size=len(patched)))
    (output / 'fonts.bin').write_bytes(records)
    (output / 'recipe.json').write_text(json.dumps(dict(schema=2, recipe='deck-world-menu-v2', files=manifest,
        allocation_growth=growth,
        converter_sha256={name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
                          for name in ('deck_font_glyphs.py', 'deck_font_prompts.py', 'deck_font_world.py', 'zstd_codec.py',
                                       'deck_layout/resource_layout.py', 'deck_layout/anchor_contract.py',
                                       'deck_layout/build_controller_patch.py')}), indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--romfs', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    build(args.romfs, args.out)
