"""Private archive transformer bounds, preservation and unknown-version refusal."""
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import deck_font_prompts as m


def archive():
    names = b'scft/External.bfotf\0'
    names += b'\0' * (-len(names) % 4)
    second = len(names) // 4
    names += b'scft/unrelated\0'
    names += b'\0' * (-len(names) % 4)
    # An own encoded fixture, not any game font.
    font = b'private synthetic outline'
    key = 0x52341423
    body = bytearray(font)
    for at in range(0, len(body) - len(body) % 4, 4):
        struct.pack_into('<I', body, at, struct.unpack_from('<I', body, at)[0] ^ key)
    blob = struct.pack('<II', key ^ 0x18029a7f, int.from_bytes(len(font).to_bytes(4, 'big'), 'little') ^ key) + body
    other = b'unchanged unrelated data'
    start = 20 + 12 + 32 + 8 + len(names)
    result = struct.pack('<4sHHIIHH', b'SARC', 20, 0xfeff, start + len(blob) + len(other), start, 0x100, 0)
    result += struct.pack('<4sHHI', b'SFAT', 12, 2, 0x65)
    result += struct.pack('<4I', 1, 0x1000000, 0, len(blob))
    result += struct.pack('<4I', 2, 0x1000000 + second, len(blob), len(blob) + len(other))
    result += struct.pack('<4sHH', b'SFNT', 8, 0) + names + blob + other
    return result, font


class FontArchiveTests(unittest.TestCase):
    def test_font_growth_preserves_every_unrelated_member_and_header_roundtrip(self):
        data, font = archive()
        lo, hi = m.members(data)['scft/External.bfotf']
        self.assertEqual(m.font_body(data[lo:hi])[0], font)
        expected = font[::-1] + b'new authored shoulder outlines'
        with patch.object(m, 'patch_external', return_value=expected):
            changed = m.patch_archive(data)
        before, after = m.members(data), m.members(changed)
        self.assertEqual(set(before), set(after))
        a, b = after['scft/External.bfotf']
        self.assertEqual(m.font_body(changed[a:b])[0], expected)
        self.assertEqual(m.font_body(changed[a:b])[1], m.font_body(data[lo:hi])[1])
        for name, (a, b) in before.items():
            if name != 'scft/External.bfotf':
                x, y = after[name]
                self.assertEqual(data[a:b], changed[x:y])
        with self.assertRaisesRegex(ValueError, 'Unsupported original'):
            m.patch_archive(data)

    def test_bad_archive_and_bfotf_ranges(self):
        data, _ = archive()
        for broken in (b'', data[:20], data[:-1]):
            with self.assertRaises(ValueError):
                m.members(broken)
        broken = bytearray(data)
        struct.pack_into('<I', broken, 20 + 12 + 12, len(data))
        with self.assertRaises(ValueError):
            m.members(broken)
        for blob in (b'', b'12345678', b'123456789012'):
            with self.assertRaises(ValueError):
                m.font_body(blob)
