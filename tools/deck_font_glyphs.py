"""Checked outline transforms for the player's private 1.4.3 icon font.

Original interoperability code. CFF INDEX semantics: Adobe Technical Note 5176;
SFNT checksums: https://learn.microsoft.com/typography/opentype/spec/otff.
No font bytes or glyph outlines are distributed.
"""
# SPDX-License-Identifier: MIT
import hashlib
import struct

EXTERNAL_SHA256 = '90a77954029dbe202f5680b95c8d8043dda4fd049e2a18786fc5d56c805fb5ec'


def checksum(data):
    data = bytes(data) + b'\0' * (-len(data) % 4)
    return sum(struct.unpack('>' + 'I' * (len(data) // 4), data)) & 0xffffffff


def tables(data):
    if len(data) < 12 or data[:4] != b'OTTO':
        raise ValueError('Expected a CFF OpenType font')
    count = struct.unpack_from('>H', data, 4)[0]
    if not 1 <= count <= 64 or 12 + count * 16 > len(data):
        raise ValueError('Invalid SFNT directory')
    result = {}
    for i in range(count):
        at = 12 + 16 * i
        tag, _, offset, size = struct.unpack_from('>4sIII', data, at)
        if tag in result or offset % 4 or offset < 12 + count * 16 or size > len(data) - offset:
            raise ValueError('Invalid SFNT table range')
        if any(max(offset, old) < min(offset + size, old + n) for _, old, n in result.values()):
            raise ValueError('Overlapping SFNT tables')
        result[tag] = (at, offset, size)
    return result


def cff_index(data, at):
    start = at
    if not 0 <= at <= len(data) - 2:
        raise ValueError('Truncated CFF INDEX')
    count = int.from_bytes(data[at:at + 2], 'big')
    if not count:
        return [], start, at + 2, 0
    if at + 3 > len(data) or count > 8192:
        raise ValueError('Invalid CFF INDEX count')
    width = data[at + 2]
    at += 3
    if not 1 <= width <= 4 or (count + 1) * width > len(data) - at:
        raise ValueError('Invalid CFF INDEX offsets')
    offsets = [int.from_bytes(data[at + i * width:at + (i + 1) * width], 'big') for i in range(count + 1)]
    base = at + (count + 1) * width
    if offsets[0] != 1 or offsets != sorted(offsets) or offsets[-1] - 1 > len(data) - base:
        raise ValueError('Invalid CFF INDEX data bounds')
    return [bytes(data[base + a - 1:base + b - 1]) for a, b in zip(offsets, offsets[1:])], start, base + offsets[-1] - 1, width


def cff_dict(data, *, spans=None):
    at, stack, result, entry = 0, [], {}, 0
    while at < len(data):
        b = data[at]
        at += 1
        if b <= 21:
            if b == 12:
                if at == len(data):
                    raise ValueError('Truncated CFF operator')
                b = (12, data[at])
                at += 1
            if b in result:
                raise ValueError('Duplicate CFF dictionary operator')
            result[b], stack = stack, []
            if spans is not None:
                spans.append((b, entry, at))
            entry = at
        elif b in (28, 29):
            size = 2 if b == 28 else 4
            if size > len(data) - at:
                raise ValueError('Truncated CFF integer')
            stack.append(int.from_bytes(data[at:at + size], 'big', signed=True))
            at += size
        elif b == 30:
            while at < len(data):
                v = data[at]
                at += 1
                if v & 15 == 15 or v >> 4 == 15:
                    break
            else:
                raise ValueError('Unterminated CFF real')
            stack.append(None)
        elif 32 <= b <= 246:
            stack.append(b - 139)
        elif 247 <= b <= 254:
            if at == len(data):
                raise ValueError('Truncated compact CFF integer')
            stack.append((b - 247) * 256 + data[at] + 108 if b <= 250 else -(b - 251) * 256 - data[at] - 108)
            at += 1
        else:
            raise ValueError('Unsupported CFF operand')
    if stack:
        raise ValueError('Trailing CFF operands')
    return result


def charstrings(font):
    directory = tables(font)
    if b'CFF ' not in directory:
        raise ValueError('Missing CFF table')
    _, offset, size = directory[b'CFF ']
    cff = font[offset:offset + size]
    if len(cff) < 4 or cff[0] != 1 or not 4 <= cff[2] < len(cff):
        raise ValueError('Unsupported CFF version')
    _, _, end, _ = cff_index(cff, cff[2])
    top, _, _, _ = cff_index(cff, end)
    if len(top) != 1:
        raise ValueError('Expected one non-CID icon font')
    fields = cff_dict(top[0])
    if (12, 30) in fields or fields.get((12, 6), [2]) != [2] or len(fields.get(17, [])) != 1:
        raise ValueError('Unsupported CID or charstring type')
    position = fields[17][0]
    if type(position) is not int:
        raise ValueError('Invalid charstring position')
    records, start, end, width = cff_index(cff, position)
    return records, offset + start, offset + end, width


def verify_checksums(font):
    directory = tables(font)
    if b'head' not in directory or directory[b'head'][2] < 54:
        raise ValueError('Missing font head')
    for tag, (at, off, size) in directory.items():
        data = bytearray(font[off:off + size])
        if tag == b'head':
            data[8:12] = b'\0' * 4
        if checksum(data) != struct.unpack_from('>I', font, at + 4)[0]:
            raise ValueError('Invalid table checksum: ' + repr(tag))
    if checksum(font) != 0xb1b0afba:
        raise ValueError('Invalid whole-font checksum')


def swap_outlines(font, first, second):
    directory = tables(font)
    required = (b'head', b'hhea', b'hmtx', b'maxp')
    if any(tag not in directory for tag in required) or directory[b'head'][2] < 54 or directory[b'hhea'][2] < 36 or directory[b'maxp'][2] < 6:
        raise ValueError('Missing font metrics')
    records, start, end, width = charstrings(font)
    glyphs = struct.unpack_from('>H', font, directory[b'maxp'][1] + 4)[0]
    metrics = struct.unpack_from('>H', font, directory[b'hhea'][1] + 34)[0]
    if glyphs != len(records) or any(type(i) is not int or not 0 <= i < min(glyphs, metrics) for i in (first, second)) or first == second:
        raise ValueError('Unsupported glyph or horizontal-metric index')
    if directory[b'hmtx'][2] < 4 * metrics + 2 * (glyphs - metrics):
        raise ValueError('Truncated horizontal metrics')
    if b'DSIG' in directory:
        _, off, size = directory[b'DSIG']
        if size < 8 or struct.unpack_from('>H', font, off + 4)[0]:
            raise ValueError('Cannot preserve a signed-font signature')
    out = bytearray(font)
    records[first], records[second] = records[second], records[first]
    offsets, total = [], 1
    for item in records:
        offsets.append(total)
        total += len(item)
    offsets.append(total)
    packed = len(records).to_bytes(2, 'big') + bytes([width]) + b''.join(n.to_bytes(width, 'big') for n in offsets) + b''.join(records)
    if len(packed) != end - start:
        raise ValueError('Glyph transform would resize the font')
    out[start:end] = packed
    base = directory[b'hmtx'][1]
    a, b = base + 4 * first, base + 4 * second
    out[a:a + 4], out[b:b + 4] = font[b:b + 4], font[a:a + 4]
    adjustment = directory[b'head'][1] + 8
    out[adjustment:adjustment + 4] = b'\0' * 4
    for _, (at, off, size) in directory.items():
        struct.pack_into('>I', out, at + 4, checksum(out[off:off + size]))
    struct.pack_into('>I', out, adjustment, (0xb1b0afba - checksum(out)) & 0xffffffff)
    verify_checksums(out)
    return bytes(out)


def patch_external(font):
    if hashlib.sha256(font).hexdigest() != EXTERNAL_SHA256:
        raise ValueError('Unsupported original 1.4.3 icon font')
    # E042 / E043 are glyphs 8 / 9 in this exact font. A/B keep menu labels;
    # deck_font_world builds a distinct world font with A/B exchanged as well.
    from deck_font_shoulders import patch_controls
    return patch_controls(swap_outlines(font, 8, 9))


def pack_index(records):
    if not 1 <= len(records) <= 8192 or any(not isinstance(r, bytes) for r in records):
        raise ValueError('Invalid replacement CFF INDEX')
    offsets = [1]
    for record in records:
        offsets.append(offsets[-1] + len(record))
    width = max(1, (offsets[-1].bit_length() + 7) // 8)
    if width > 4:
        raise ValueError('CFF INDEX overflow')
    return len(records).to_bytes(2, 'big') + bytes([width]) + b''.join(
        n.to_bytes(width, 'big') for n in offsets) + b''.join(records)


def replace_outlines(font, replacements):
    """Append a new INDEX; preserve all subroutine/private/charset offsets.

    The original INDEX remains unreferenced. Only its Top DICT pointer changes,
    using the same operand width, so no existing CFF address moves. Rebuild the
    SFNT directory for the enlarged CFF table and recompute every checksum.
    """
    verify_checksums(font)
    directory = tables(font)
    records, _, _, _ = charstrings(font)
    if any(tag not in directory for tag in (b'maxp', b'hhea', b'hmtx')) or directory[b'maxp'][2] < 6 or directory[b'hhea'][2] < 36:
        raise ValueError('Missing replacement font metrics')
    glyphs = struct.unpack_from('>H', font, directory[b'maxp'][1] + 4)[0]
    metrics = struct.unpack_from('>H', font, directory[b'hhea'][1] + 34)[0]
    if glyphs != len(records) or not 0 < metrics <= glyphs or directory[b'hmtx'][2] < 4 * metrics + 2 * (glyphs - metrics):
        raise ValueError('Invalid replacement font metrics')
    if b'DSIG' in directory:
        _, off, n = directory[b'DSIG']
        if n < 8 or struct.unpack_from('>H', font, off + 4)[0]:
            raise ValueError('Cannot preserve a signed-font signature')
    if not replacements or any(type(i) is not int or not 0 <= i < len(records) or
                               not isinstance(value, bytes) or not 0 < len(value) <= 2048
                               for i, value in replacements.items()):
        raise ValueError('Invalid replacement glyph')
    _, base, size = directory[b'CFF ']
    cff = bytearray(font[base:base + size])
    _, _, names_end, _ = cff_index(cff, cff[2])
    top, start, end, _ = cff_index(cff, names_end)
    spans = []
    fields = cff_dict(top[0], spans=spans)
    _, lo, hi = next(s for s in spans if s[0] == 17)
    width = hi - lo - 1
    if width == 1 and size <= 107:
        operand = bytes([size + 139])
    elif width == 2 and 108 <= size <= 1131:
        operand = bytes([247 + (size - 108) // 256, (size - 108) % 256])
    elif width == 3 and size <= 32767:
        operand = b'\x1c' + size.to_bytes(2, 'big')
    elif width == 5 and size <= 0x7fffffff:
        operand = b'\x1d' + size.to_bytes(4, 'big')
    else:
        raise ValueError('CharStrings pointer would resize the Top DICT')
    patched_top = top[0][:lo] + operand + b'\x11' + top[0][hi:]
    if cff_dict(patched_top) != fields | {17: [size]}:
        raise ValueError('Unexpected CFF dictionary change')
    packed_top = pack_index([patched_top])
    # Preserve the original INDEX offset width as well as its payload length.
    _, _, _, top_width = cff_index(cff, names_end)
    if packed_top[2] != top_width or len(packed_top) != end - start:
        raise ValueError('Top DICT INDEX layout would change')
    cff[start:end] = packed_top
    for i, value in replacements.items():
        records[i] = value
    cff.extend(pack_index(records))
    out = bytearray(font[:12]) + bytearray(16 * len(directory))
    for tag, (at, off, n) in directory.items():
        data = bytearray(cff if tag == b'CFF ' else font[off:off + n])
        if tag == b'head':
            data[8:12] = b'\0' * 4
        out.extend(b'\0' * (-len(out) % 4))
        struct.pack_into('>4sIII', out, at, tag, checksum(data), len(out), len(data))
        out.extend(data)
    out.extend(b'\0' * (-len(out) % 4))
    head = tables(out)[b'head'][1]
    struct.pack_into('>I', out, head + 8, (0xb1b0afba - checksum(out)) & 0xffffffff)
    verify_checksums(out)
    if charstrings(out)[0] != records:
        raise ValueError('Replacement charstrings differ after relocation')
    return bytes(out)
