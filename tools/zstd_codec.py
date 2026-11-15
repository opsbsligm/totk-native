"""Small bounded libzstd adapter, including trained dictionaries, for Python 3.11+."""
import ctypes as C
from ctypes.util import find_library
from dataclasses import dataclass
import sys

MAX_OUTPUT = 512 << 20
# The supported Linux toolchain declares this ABI. Loading it directly avoids
# find_library's compiler/linker probes during otherwise read-only diagnostics.
lib = C.CDLL('libzstd.so.1' if sys.platform == 'linux' else (find_library('zstd') or 'libzstd.so.1'))


def function(name, result, *args):
    f = getattr(lib, name)
    f.restype, f.argtypes = result, args
    return f


_error = function('ZSTD_isError', C.c_uint, C.c_size_t)
_error_name = function('ZSTD_getErrorName', C.c_char_p, C.c_size_t)
_size = function('ZSTD_getFrameContentSize', C.c_ulonglong, C.c_void_p, C.c_size_t)
_frame_id = function('ZSTD_getDictID_fromFrame', C.c_uint, C.c_void_p, C.c_size_t)
_dict_id = function('ZSTD_getDictID_fromDict', C.c_uint, C.c_void_p, C.c_size_t)
_create = function('ZSTD_createDCtx', C.c_void_p)
_free = function('ZSTD_freeDCtx', C.c_size_t, C.c_void_p)
_decode = function('ZSTD_decompress_usingDict', C.c_size_t, C.c_void_p, C.c_void_p,
                   C.c_size_t, C.c_void_p, C.c_size_t, C.c_void_p, C.c_size_t)


@dataclass(frozen=True)
class FrameInfo:
    decompressed_size: int | None
    dictionary_id: int


class ZstdDict:
    def __init__(self, data):
        self.data = bytes(data)
        if not self.data or len(self.data) > 64 << 20:
            raise ValueError('Invalid Zstandard dictionary size')
        self.dict_id = _dict_id(self.data, len(self.data))


def get_frame_info(data):
    size = _size(data, len(data))
    if size == 2**64 - 2:
        raise ValueError('Invalid Zstandard frame')
    return FrameInfo(None if size == 2**64 - 1 else size, _frame_id(data, len(data)))


def decompress(data, *, zstd_dict=None):
    info = get_frame_info(data)
    if info.decompressed_size is None or info.decompressed_size > MAX_OUTPUT:
        raise ValueError('Unbounded or oversized Zstandard frame')
    if info.dictionary_id and (zstd_dict is None or zstd_dict.dict_id != info.dictionary_id):
        raise ValueError('Missing or incorrect Zstandard dictionary')
    dictionary = zstd_dict.data if zstd_dict is not None else b''
    output = C.create_string_buffer(max(1, info.decompressed_size))
    context = _create()
    if not context:
        raise MemoryError('Cannot allocate Zstandard context')
    try:
        count = _decode(context, output, info.decompressed_size, data, len(data), dictionary, len(dictionary))
        if _error(count):
            raise ValueError('Zstandard decode failed: ' + _error_name(count).decode())
        if count != info.decompressed_size:
            raise ValueError('Zstandard decoded size changed')
        return output.raw[:count]
    finally:
        _free(context)


def compress(data, *, zstd_dict=None, level=9):
    """Encode bounded private assets, retaining the source dictionary identity."""
    data = bytes(data)
    if len(data) > MAX_OUTPUT or not isinstance(level, int) or not 1 <= level <= 19:
        raise ValueError('Oversized Zstandard input or invalid level')
    bound = function('ZSTD_compressBound', C.c_size_t, C.c_size_t)(len(data))
    output = C.create_string_buffer(bound)
    create = function('ZSTD_createCCtx', C.c_void_p)
    free = function('ZSTD_freeCCtx', C.c_size_t, C.c_void_p)
    encode = function('ZSTD_compress_usingDict', C.c_size_t, C.c_void_p, C.c_void_p,
                      C.c_size_t, C.c_void_p, C.c_size_t, C.c_void_p, C.c_size_t, C.c_int)
    dictionary = zstd_dict.data if zstd_dict is not None else b''
    context = create()
    if not context:
        raise MemoryError('Cannot allocate Zstandard context')
    try:
        count = encode(context, output, bound, data, len(data), dictionary, len(dictionary), level)
        if _error(count):
            raise ValueError('Zstandard encode failed: ' + _error_name(count).decode())
        encoded = output.raw[:count]
        if decompress(encoded, zstd_dict=zstd_dict) != data:
            raise ValueError('Zstandard round trip changed asset bytes')
        return encoded
    finally:
        free(context)
