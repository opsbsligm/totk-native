"""Authored Deck shoulder and Menu/View badges, not extracted outlines. MIT.

Type 2 number/path encoding follows Adobe Technical Note 5177. All contours fit
the checked font's existing bounding box. Shoulders retain 720-unit advances;
Menu/View retain their original 600-unit advances and 56..544 bounds.
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
SYSTEM_LABELS = {17: 'Menu', 18: 'View'}  # E04B / E04C in the pinned icon font.
SYSTEM_BODY = (
    (544, 300), (536, 363), (511, 422), (473, 473), (422, 511), (363, 536),
    (300, 544), (237, 536), (178, 511), (127, 473), (89, 422), (64, 363),
    (56, 300), (64, 237), (89, 178), (127, 127), (178, 89), (237, 64),
    (300, 56), (363, 64), (422, 89), (473, 127), (511, 178), (536, 237),
)
# An occluded rear window and a complete front window: their holes do not
# overlap, so CFF's nonzero winding rule cannot fill an unintended intersection.
VIEW_REAR = ((260, 270), (170, 270), (170, 420), (350, 420), (350, 330),
             (318, 330), (318, 388), (202, 388), (202, 302), (260, 302))
VIEW_FRONT = ((260, 180), (440, 180), (440, 330), (260, 330))
VIEW_INNER = ((292, 212), (408, 212), (408, 298), (292, 298))


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


def _outline(contours, advance, nominal_width):
    out = bytearray(number(advance - nominal_width))
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
        out.append(5)  # rlineto; at most 48 operands, Type 2's stack limit.
    out.append(14)  # endchar
    return bytes(out)


def outline(label, nominal_width=707):
    if label not in LABELS or type(nominal_width) is not int:
        raise ValueError('Unsupported shoulder label or nominal width')
    contours = [(BODY, True), (LETTERS[label[0]], False), (LETTERS[label[1]], False)]
    if label[0] == 'R':
        contours.append((R_COUNTER, True))
    return _outline(contours, 720, nominal_width)


def system_outline(label, nominal_width=707):
    if label not in SYSTEM_LABELS.values() or type(nominal_width) is not int:
        raise ValueError('Unsupported system label or nominal width')
    contours = [(SYSTEM_BODY, True)]
    if label == 'Menu':
        for y in (216, 300, 384):
            contours.append((((190, y-22), (410, y-22),
                              (410, y+22), (190, y+22)), False))
    else:
        contours.extend(((VIEW_REAR, False), (VIEW_FRONT, False), (VIEW_INNER, True)))
    return _outline(contours, 600, nominal_width)


def patch_controls(font):
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
        raise ValueError('Unsupported controller font widths')
    metrics = directory[b'hmtx'][1]
    advances = {**dict.fromkeys(range(10, 14), 720), **dict.fromkeys(SYSTEM_LABELS, 600)}
    if directory[b'hmtx'][2] < 4 * (max(advances) + 1):
        raise ValueError('Truncated controller font metrics')
    if any(struct.unpack_from('>H', font, metrics + 4*i)[0] != width
           for i, width in advances.items()):
        raise ValueError('Unexpected controller advances')
    replacements = {10+i: outline(label) for i, label in enumerate(LABELS)}
    replacements.update({i: system_outline(label) for i, label in SYSTEM_LABELS.items()})
    return replace_outlines(font, replacements)
