"""Original L1/R1/L2/R2 badge contours, not extracted game outlines. MIT.

Type 2 number/path encoding follows Adobe Technical Note 5177. All contours fit
the checked font's existing bounding box and retain its 720-unit advance.
"""
# SPDX-License-Identifier: MIT
import struct

from deck_font_glyphs import cff_dict, cff_index, replace_outlines, tables

LABELS = ('L1', 'R1', 'L2', 'R2')
BODY = ((24, 135), (64, 95), (656, 95), (696, 135),
        (696, 585), (656, 625), (64, 625), (24, 585))
LETTERS = {
    'L': ((120, 535), (175, 535), (175, 250), (315, 250), (315, 195), (120, 195)),
    'R': ((120, 195), (120, 535), (245, 535), (305, 480), (305, 385),
          (250, 335), (320, 195), (260, 195), (200, 325), (175, 325), (175, 195)),
    '1': ((385, 460), (455, 535), (510, 535), (510, 250), (590, 250),
          (590, 195), (380, 195), (380, 250), (455, 250), (455, 455), (420, 420)),
    '2': ((370, 485), (420, 535), (540, 535), (600, 480), (600, 405),
          (445, 250), (605, 250), (605, 195), (370, 195), (370, 250),
          (545, 425), (545, 455), (515, 480), (440, 480), (405, 445)),
}
R_COUNTER = ((175, 480), (225, 480), (250, 455), (250, 410), (225, 380), (175, 380))


def number(value):
    if type(value) is not int or not -32768 <= value <= 32767:
        raise ValueError('Type 2 coordinate outside supported bounds')
    if -107 <= value <= 107:
        return bytes([value + 139])
    if 108 <= value <= 1131:
        return bytes([247 + (value - 108) // 256, (value - 108) % 256])
    if -1131 <= value <= -108:
        return bytes([251 + (-value - 108) // 256, (-value - 108) % 256])
    return b'\x1c' + struct.pack('>h', value)


def outline(label, nominal_width=707):
    if label not in LABELS or type(nominal_width) is not int:
        raise ValueError('Unsupported shoulder label or nominal width')
    contours = [(BODY, True), (LETTERS[label[0]], False), (LETTERS[label[1]], False)]
    if label[0] == 'R':
        contours.append((R_COUNTER, True))
    out = bytearray(number(720 - nominal_width))
    x = y = 0
    for points, positive in contours:
        area = sum(a * d - b * c for (a, b), (c, d) in zip(points, points[1:] + points[:1]))
        if (area > 0) != positive:
            points = tuple(reversed(points))
        ax, ay = points[0]
        out.extend(number(ax - x) + number(ay - y) + b'\x15')  # rmoveto
        x, y = ax, ay
        for ax, ay in points[1:] + points[:1]:
            out.extend(number(ax - x) + number(ay - y))
            x, y = ax, ay
        out.append(5)  # rlineto; at most 30 operands, below Type 2's 48 limit.
    out.append(14)  # endchar
    return bytes(out)


def patch_shoulders(font):
    directory = tables(font)
    _, base, size = directory[b'CFF ']
    cff = font[base:base + size]
    _, _, at, _ = cff_index(cff, cff[2])
    top, _, _, _ = cff_index(cff, at)
    fields = cff_dict(top[0])
    private_size, private_at = fields.get(18, (0, 0))
    if not (type(private_at) is int and type(private_size) is int and
            0 < private_size <= len(cff) - private_at and private_at >= 0):
        raise ValueError('Invalid private font dictionary')
    private = cff_dict(cff[private_at:private_at + private_size])
    if private.get(20) != [16] or private.get(21) != [707]:
        raise ValueError('Unsupported shoulder font widths')
    metrics = directory[b'hmtx'][1]
    if any(struct.unpack_from('>H', font, metrics + 4 * i)[0] != 720 for i in range(10, 14)):
        raise ValueError('Unexpected shoulder advances')
    return replace_outlines(font, {10 + i: outline(label) for i, label in enumerate(LABELS)})
