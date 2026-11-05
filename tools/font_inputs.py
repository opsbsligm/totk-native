"""Reject missing or malformed local shared fonts before expensive game builds."""
from pathlib import Path

NAMES = ('0-standard', '1-chinese-simplified', '2-chinese-simplified-extension',
         '3-chinese-traditional', '4-korean', '5-nintendo-extension')


def validate_shared_fonts(directory):
    for name in NAMES:
        path = Path(directory) / (name + '.bfttf')
        if path.is_symlink() or not path.is_file() or not 12 <= path.stat().st_size < 64 * 2**20:
            raise ValueError('Missing or invalid shared font: ' + str(path))
        with path.open('rb') as stream:
            header = stream.read(12)
        key = int.from_bytes(header[:4], 'big') ^ 0x7f9a0218
        size = int.from_bytes(header[4:8], 'big') ^ key
        signature = int.from_bytes(header[8:12], 'big') ^ key
        if size != path.stat().st_size - 8 or signature not in (0x00010000, 0x4f54544f):
            raise ValueError('Shared font header differs: ' + str(path))
