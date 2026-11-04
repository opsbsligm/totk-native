"""Small bounded libzstd adapter, including trained dictionaries, for Python 3.11+."""
import ctypes as C
from ctypes.util import find_library
from dataclasses import dataclass

MAX_OUTPUT = 512 << 20
lib = C.CDLL(find_library('zstd') or 'libzstd.so.1')


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
