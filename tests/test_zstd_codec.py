"""Decode real libzstd frames with and without a trained dictionary."""
import ctypes as C
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import zstd_codec as codec


def compress(raw, dictionary=None):
    bound = codec.function('ZSTD_compressBound', C.c_size_t, C.c_size_t)(len(raw))
    output = C.create_string_buffer(bound)
    if dictionary is None:
        fn = codec.function('ZSTD_compress', C.c_size_t, C.c_void_p, C.c_size_t, C.c_void_p, C.c_size_t, C.c_int)
        n = fn(output, bound, raw, len(raw), 3)
    else:
        create = codec.function('ZSTD_createCCtx', C.c_void_p)
        free = codec.function('ZSTD_freeCCtx', C.c_size_t, C.c_void_p)
        fn = codec.function('ZSTD_compress_usingDict', C.c_size_t, C.c_void_p, C.c_void_p, C.c_size_t,
                            C.c_void_p, C.c_size_t, C.c_void_p, C.c_size_t, C.c_int)
        context = create()
        try:
            n = fn(context, output, bound, raw, len(raw), dictionary.data, len(dictionary.data), 3)
        finally:
            free(context)
    if codec._error(n):
        raise RuntimeError(codec._error_name(n))
    return output.raw[:n]


class ZstandardTests(unittest.TestCase):
    def test_actual_frames_and_invalid_input(self):
        for raw in (b'', b'public round trip fixture' * 300):
            encoded = compress(raw)
            self.assertEqual(codec.get_frame_info(encoded).decompressed_size, len(raw))
            self.assertEqual(codec.decompress(encoded), raw)
            self.assertEqual(codec.decompress(codec.compress(raw)), raw)
        encoded = compress(b'0123456789' * 100)
        with patch.object(codec, 'MAX_OUTPUT', 16), self.assertRaisesRegex(ValueError, 'oversized'):
            codec.decompress(encoded)
        for invalid in (b'', b'garbage', encoded[:-1]):
            with self.subTest(invalid=invalid[:8]), self.assertRaises(ValueError):
                codec.decompress(invalid)

    def test_trained_dictionary_is_required_and_used(self):
        samples = [(f'public fixture {i}: The bounded shader package dictionary. ' * 8).encode() for i in range(100)]
        sizes = (C.c_size_t * len(samples))(*map(len, samples))
        output = C.create_string_buffer(2048)
        train = codec.function('ZDICT_trainFromBuffer', C.c_size_t, C.c_void_p, C.c_size_t, C.c_void_p,
                               C.POINTER(C.c_size_t), C.c_uint)
        n = train(output, len(output), b''.join(samples), sizes, len(samples))
        self.assertFalse(codec._error(n))
        dictionary = codec.ZstdDict(output.raw[:n])
        self.assertGreater(dictionary.dict_id, 0)
        raw = samples[0]
        encoded = compress(raw, dictionary)
        self.assertEqual(codec.get_frame_info(encoded).dictionary_id, dictionary.dict_id)
        with self.assertRaisesRegex(ValueError, 'dictionary'):
            codec.decompress(encoded)
        self.assertEqual(codec.decompress(encoded, zstd_dict=dictionary), raw)
        encoded = codec.compress(raw, zstd_dict=dictionary)
        self.assertEqual(codec.get_frame_info(encoded).dictionary_id, dictionary.dict_id)
        self.assertEqual(codec.decompress(encoded, zstd_dict=dictionary), raw)

    def test_compression_bounds(self):
        for level in (0, 20, '9'):
            with self.assertRaises(ValueError):
                codec.compress(b'fixture', level=level)
        with patch.object(codec, 'MAX_OUTPUT', 2), self.assertRaises(ValueError):
            codec.compress(b'longer')


if __name__ == '__main__':
    unittest.main()
