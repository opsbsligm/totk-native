"""原创 NSO/补丁夹具，核验压缩内容、版本、原子失败和真实写入字节。"""
from pathlib import Path
import hashlib
import struct
import sys
import unittest

import lz4.block

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from code_mods import NsoImage, Patch, apply_patches, build_id, decode_nso, parse_ips, parse_pchtxt, prepare_modules

IDENTITY = '1234567890abcdef' * 2
CONTENTS = (bytes(range(32)), b'original synthetic rodata', bytes(range(16)))


def fixture(compression=7, hashes=True):
    raw = bytearray(0x100)
    raw[:4] = b'NSO0'
    raw[0x40:0x60] = bytes.fromhex(IDENTITY).ljust(32, b'\0')
    struct.pack_into('<I', raw, 0xC, compression | (0x38 if hashes else 0))
    for index, content in enumerate(CONTENTS):
        stored = lz4.block.compress(content, store_size=False) if compression & (1 << index) else content
        struct.pack_into('<III', raw, 0x10 + index * 0x10, len(raw), index * 0x80, len(content))
        struct.pack_into('<I', raw, 0x60 + index * 4, len(stored))
        raw[0xA0 + index * 0x20:0xC0 + index * 0x20] = hashlib.sha256(content).digest()
        raw.extend(stored)
    struct.pack_into('<I', raw, 0x3C, 16)
    return bytes(raw)


class StaticCodeModFormats(unittest.TestCase):
    def test_all_segment_compression_combinations_and_idempotence(self):
        for mask in range(8):
            with self.subTest(mask=mask):
                original = fixture(mask)
                image = decode_nso(original)
                self.assertEqual(image.build_id, IDENTITY.ljust(64, '0'))
                for index, content in enumerate(CONTENTS):
                    self.assertEqual(image.data[0x100 + index * 0x80:0x100 + index * 0x80 + len(content)], content)
                self.assertEqual(image.data[0x120:0x180], bytes(0x60))
                self.assertEqual(struct.unpack_from('<I', image.data, 0xC)[0], 0x38)
                self.assertEqual(decode_nso(image.data), image)
                self.assertEqual(original, fixture(mask))

    def test_uncompressed_ignored_stored_size_and_unchecked_hashes(self):
        raw = bytearray(fixture(0, hashes=False))
        raw[0x60:0x6C] = bytes(12)
        raw[0xA0:0x100] = bytes(0x60)
        self.assertEqual(decode_nso(raw), decode_nso(fixture()))

    def test_bad_nso_bounds_overlap_flags_hashes_and_compression(self):
        variants = [b'', b'NSO0', fixture()[:-1]]
        for offset, value in [(0xC, 0x40), (0x10, 0x20), (0x20, 0x100),
                              (0x24, 0), (0x18, 0xFFFFFFFF), (0x3C, 0xFFFFFFFF), (0x60, 0xFFFFFFFF)]:
            raw = bytearray(fixture()); struct.pack_into('<I', raw, offset, value); variants.append(raw)
        raw = bytearray(fixture()); raw[-1] ^= 0xFF; variants.append(raw)
        raw = bytearray(fixture()); raw[0xA0] ^= 1; variants.append(raw)
        raw = bytearray(fixture()); raw[0x40:0x60] = bytes(32); variants.append(raw)
        raw = bytearray(fixture()); start, = struct.unpack_from('<I', raw, 0x10); raw[start:start + 4] = bytes(4); variants.append(raw)
        raw = bytearray(fixture()); struct.pack_into('<I', raw, 0x34, 0x20); variants.append(raw)
        for index, raw in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(ValueError):
                decode_nso(raw)

    def test_standard_ips_zero_rle_overlap_and_hash_refresh(self):
        raw = b'PATCH' + b'\0\x01\x00\0\x04\xAA\0\xBB\xCC' + b'\0\x01\x02\0\0\0\x03\xDD' + b'EOF'
        patches = parse_ips(raw)
        image = decode_nso(fixture())
        output = apply_patches(image, patches)
        self.assertEqual(output[0x100:0x106], b'\xAA\0\xDD\xDD\xDD\x05')
        self.assertEqual(decode_nso(output).data, output)
        self.assertEqual(output[0x40:0x60], image.data[0x40:0x60])
        self.assertNotEqual(output[0xA0:0xC0], image.data[0xA0:0xC0])

    def test_ips32_large_offsets_and_strict_endings(self):
        raw = b'IPS32' + (0x1000001).to_bytes(4, 'big') + b'\0\x02\0\xCC' + b'EEOF'
        self.assertEqual(parse_ips(raw), [Patch(0x1000001, b'\0\xCC')])
        for invalid in [raw[:-1], raw + b'\0', b'PATCH' + b'EOF' + bytes(3), b'IPS\x1A',
                        b'PATCH\0\x01\0\0\0\0\0\xFFEOF', b'PATCH\0\x01\0\0\x02\xFF',
                        b'IPS32\xFF\xFF\xFF\xFF\0\x02\x01\x02EEOF']:
            with self.subTest(raw=invalid), self.assertRaises(ValueError):
                parse_ips(invalid)

    def test_apply_checks_complete_set_before_producing_output(self):
        image = decode_nso(fixture()); original = image.data
        for bad in [Patch(0xFF, b'A'), Patch(0x120, b'A'), Patch(0x11F, b'AB'),
                    Patch(len(image.data), b'A'), Patch(0x100, b''), Patch(-1, b'A')]:
            with self.subTest(patch=bad), self.assertRaises(ValueError):
                apply_patches(image, [Patch(0x100, b'first'), bad])
            self.assertEqual(image.data, original)
        with self.assertRaises(ValueError):
            apply_patches(image, [Patch(0x100, b'A')], protected_ranges=[(0x100, 0x104)])
        with self.assertRaises(ValueError):
            apply_patches(image, [Patch(0x104, b'A'), Patch(0x100, b'B')],
                          protected_ranges=((a, b) for a, b in [(0x100, 0x104)]))
        self.assertEqual(apply_patches(image, [Patch(0x104, b'B')], protected_ranges=[(0x100, 0x104)])[0x104], ord('B'))
        adjacent = NsoImage(image.data, image.build_id, ((0x100, 0x110), (0x110, 0x120)))
        self.assertEqual(apply_patches(adjacent, [Patch(0x10F, b'AB')])[0x10F:0x111], b'AB')

    def test_pchtxt_enabled_disabled_shift_comments_strings_and_stop(self):
        text = '@nsobid-' + IDENTITY + ''' // version
@flag print_values
@flag offset_shift 0x100
// first block
@enabled
00000000 0001FF
@disabled
00000003 DEADBEEF
@flag offset_shift 0
@enabled
00000180 "url//test\\n\\x41\\000" // comment outside string
@stop
@unknown old invalid content
'''
        patches = parse_pchtxt(text, IDENTITY.ljust(64, '0'))
        self.assertEqual([(p.offset, p.data) for p in patches], [(0x100, b'\0\x01\xFF'), (0x180, b'url//test\nA\0')])
        output = apply_patches(decode_nso(fixture()), patches)
        self.assertEqual(output[0x100:0x103], b'\0\x01\xFF')
        self.assertEqual(output[0x103], CONTENTS[0][3])
        self.assertEqual(decode_nso(output).data, output)

    def test_pchtxt_requires_complete_identity_and_understood_syntax(self):
        prefix = '@nsobid-' + IDENTITY + '\n'
        invalid = ['@enabled\n00000100 00', '@nsobid-' + IDENTITY[:-2],
                   '@nsobid-' + IDENTITY + '01', prefix + '00000100 00', prefix + '@mystery',
                   prefix + '@enabled\n00000100 0', prefix + '@enabled\n00000100 "unterminated',
                   prefix + '@enabled\n00000100 "\\q"', prefix + '@enabled\n00000100 "\\x1234"',
                   prefix + '@flag offset_shift 0x100 extra', prefix + '@flag offset_shift -0x200\n@enabled\n00000100 00',
                   prefix + '@enabled\nFFFFFFFF 0001', prefix + '@flag offset_shift 0x100000001',
                   prefix + '@disabled\ninvalid', prefix + '@enabled\n00000100 ""']
        for index, text in enumerate(invalid):
            with self.subTest(index=index), self.assertRaises(ValueError):
                parse_pchtxt(text, IDENTITY)
        self.assertEqual(parse_pchtxt('\ufeff' + prefix + '@enabled\n00000100 AA', IDENTITY)[0].data, b'\xAA')
        self.assertEqual(build_id(IDENTITY.upper()), IDENTITY.ljust(64, '0'))
        with self.assertRaises(ValueError):
            build_id(IDENTITY[:16])

    def test_expansion_record_and_text_budgets(self):
        with self.assertRaises(ValueError):
            parse_ips(b'PATCH' + (b'\0\x01\0\0\0\xFF\xFF\0' * 257) + b'EOF')
        with self.assertRaises(ValueError):
            parse_ips(b'PATCH' + (b'\0\x01\0\0\x01\0' * 65537) + b'EOF')
        with self.assertRaises(ValueError):
            parse_pchtxt('@nsobid-' + IDENTITY + '\n//' + 'a' * 4096, IDENTITY)

    def test_mod_sets_bind_modules_sort_stack_disable_and_preserve_unmodified_bytes(self):
        main = fixture()
        sdk = bytearray(fixture()); sdk[0x40] ^= 0xFF; sdk = bytes(sdk)
        originals = {'main': main, 'sdk': sdk}
        first = ('@nsobid-' + IDENTITY + '\n@enabled\n00000100 AABB').encode()
        later = ('@nsobid-' + IDENTITY + '\n@enabled\n00000101 CC').encode()
        patch_sets = {'20-later': {'named.pchtxt': later}, '10-first': {'first.pchtxt': first},
                      '.disabled': {'wrong.pchtxt': b'invalid ignored while disabled'}}
        result = prepare_modules(originals, patch_sets, protected={'main': (), 'sdk': ()})
        self.assertEqual(result.modules['main'][0x100:0x102], b'\xAA\xCC')
        self.assertEqual(result.modules['sdk'], sdk)
        self.assertEqual(result.changed_modules, ('main',))
        self.assertEqual([p['mod'] for p in result.selected_patches], ['10-first', '20-later'])
        self.assertEqual(originals, {'main': main, 'sdk': sdk})
        self.assertEqual(result.inputs['main'], hashlib.sha256(main).hexdigest())
        noop = ('@nsobid-' + IDENTITY + '\n@enabled\n00000100 00').encode()
        unchanged = prepare_modules({'main': main}, {'a': {'p.pchtxt': noop}}, protected={'main': ()})
        self.assertEqual(unchanged.changed_modules, ())
        self.assertEqual(unchanged.modules['main'], main)

    def test_mod_sets_wrong_version_escape_protected_and_late_failure_do_not_publish(self):
        original = fixture()
        good = b'PATCH\0\x01\0\0\x01\xFFEOF'
        valid = {IDENTITY + '.ips': good}
        bad_sets = [
            {'../escape': valid}, {'good': {'../escape.ips': good}},
            {'good': {'main.ips': good}}, {'good': {'f' * 32 + '.ips': good}},
            {'10-good': valid, '20-bad': {IDENTITY + '.ips': b'PATCH broken'}},
            {'bad': {'p.pchtxt': b'\xFF\xFEinvalid'}},
        ]
        for patch_sets in bad_sets:
            with self.subTest(patch_sets=patch_sets), self.assertRaises(ValueError):
                prepare_modules({'main': original}, patch_sets, protected={'main': ()})
            self.assertEqual(original, fixture())
        with self.assertRaises(ValueError):
            prepare_modules({'main': original}, {'good': valid}, protected={'main': ((0x100, 0x104),)})
        with self.assertRaises(ValueError):
            prepare_modules({'main': original}, {}, protected={})
        with self.assertRaises(ValueError):
            prepare_modules({'main': original, 'sdk': original}, {}, protected={'main': (), 'sdk': ()})
