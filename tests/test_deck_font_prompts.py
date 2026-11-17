"""Private archive transformer bounds, preservation and unknown-version refusal."""
from pathlib import Path
import os
import shutil
import tempfile
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


class OutputPublicationTests(unittest.TestCase):
    """A work area may keep the previous set hardlinked into an installed release."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.out = self.root / 'data' / 'deck-ui'
        self.out.mkdir(parents=True)
        self.release = self.root / 'release' / 'data' / 'deck-ui'
        self.release.mkdir(parents=True)
        self.links = {}
        for name in m.GENERATED:
            shared = self.release / name
            shared.write_bytes(b'installed ' + name.encode())
            os.link(shared, self.out / name)
            self.links[name] = shared

    def published(self):
        return {name: (self.out / name).read_bytes() for name in m.GENERATED}

    def generate(self, marker=b'new'):
        staging = m.stage_output(self.out)
        for name in m.GENERATED:
            (staging / name).write_bytes(marker + b' ' + name.encode())
        return staging

    def test_existing_hardlinked_set_is_replaced_without_touching_the_release(self):
        m.publish(self.generate(), self.out)
        self.assertEqual({name: b'new ' + name.encode() for name in m.GENERATED}, self.published())
        for name, shared in self.links.items():
            self.assertEqual(b'installed ' + name.encode(), shared.read_bytes())
            self.assertEqual(1, shared.stat().st_nlink)
        self.assertEqual(sorted(m.GENERATED), sorted(p.name for p in self.out.iterdir()))

    def test_publishing_twice_is_idempotent(self):
        m.publish(self.generate(b'first'), self.out)
        m.publish(self.generate(b'second'), self.out)
        self.assertEqual({name: b'second ' + name.encode() for name in m.GENERATED}, self.published())
        self.assertEqual(0, len([p for p in self.out.parent.iterdir() if p.name.startswith('deck-ui.new.')]))

    def test_a_failure_leaves_the_previous_set_complete_and_no_staging(self):
        staging = self.generate()
        (staging / 'fonts.bin').unlink()
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            m.publish(staging, self.out)
        self.assertEqual({name: b'installed ' + name.encode() for name in m.GENERATED}, self.published())
        shutil.rmtree(staging)
        self.assertEqual(0, len([p for p in self.out.parent.iterdir() if p.name.startswith('deck-ui.new.')]))

    def test_unexpected_or_non_directory_output_is_refused(self):
        (self.out / 'foreign.txt').write_text('not ours')
        with self.assertRaisesRegex(ValueError, 'Unexpected content'):
            m.stage_output(self.out)
        shutil.rmtree(self.out)
        (self.out.parent / 'deck-ui.new.stray').mkdir()
        self.out.mkdir()
        (self.out / 'file').write_text('x')
        with self.assertRaisesRegex(ValueError, 'not a plain directory'):
            m.stage_output(self.out / 'file')
        (self.out / 'file').unlink()
        m.stage_output(self.out).rmdir()
        self.assertEqual({'deck-ui', 'deck-ui.new.stray'}, {p.name for p in self.out.parent.iterdir()})
