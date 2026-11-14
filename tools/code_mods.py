# SPDX-License-Identifier: MIT
"""静态 mod 的格式层：校验并解压 NSO，严格解析 IPS/IPS32/PCHTXT。

此模块不更改原始输入，不跳过游戏版本门禁，也不将准备好的 NSO 当作已重编译的运行包。
格式依据：Atmosphere loader 文档、IPSwitch example/README.md、hactool 的 NSO 布局。
实现独立编写；构建接入时还须校验原始模块指纹和应用自身保留的补丁位置。
"""
from __future__ import annotations

from dataclasses import dataclass
import bisect
import hashlib
import re
import struct

import lz4.block

MAX_NSO_BYTES = 256 * 2**20
MAX_PATCH_BYTES = 16 * 2**20
MAX_RECORDS = 65536


@dataclass(frozen=True)
class NsoImage:
    data: bytes
    build_id: str
    spans: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class Patch:
    offset: int
    data: bytes
    line: int = 0


def build_id(value: str) -> str:
    """只允许省略完整的尾部零字节，不按任意前缀匹配版本。"""
    if not re.fullmatch(r'[0-9a-fA-F]{32,64}', value) or len(value) % 2 or not int(value, 16):
        raise ValueError('NSO Build ID 必须包含 16–32 字节的非零十六进制标识')
    return value.lower().ljust(64, '0')


def decode_nso(raw: bytes) -> NsoImage:
    if len(raw) < 0x100 or len(raw) > MAX_NSO_BYTES or raw[:4] != b'NSO0':
        raise ValueError('NSO 头部、大小或魔数无效')
    identity = build_id(raw[0x40:0x60].hex())
    flags, = struct.unpack_from('<I', raw, 0xC)
    if flags & ~0x3F:
        raise ValueError('NSO 使用了未支持的标志')
    segments, file_spans, memory_spans = [], [], []
    for index in range(3):
        file_at, memory_at, size = struct.unpack_from('<III', raw, 0x10 + index * 0x10)
        stored, = struct.unpack_from('<I', raw, 0x60 + index * 4)
        compressed = bool(flags & (1 << index))
        stored = stored if compressed else size
        if size > MAX_NSO_BYTES - 0x100 or memory_at > MAX_NSO_BYTES - 0x100 - size:
            raise ValueError('NSO 解压段超过内存预算')
        if size:
            if not stored or file_at < 0x100 or stored > len(raw) or file_at > len(raw) - stored:
                raise ValueError('NSO 文件段越界或截断')
            file_spans.append((file_at, file_at + stored))
            memory_spans.append((memory_at, memory_at + size))
        elif stored:
            raise ValueError('NSO 空段包含非空压缩数据')
        content = raw[file_at:file_at + stored]
        if compressed and size:
            try:
                content = lz4.block.decompress(content, uncompressed_size=size)
            except lz4.block.LZ4BlockError as error:
                raise ValueError('NSO LZ4 段解压失败') from error
        if len(content) != size:
            raise ValueError('NSO 解压长度不符')
        if flags & (1 << (index + 3)):
            expected = raw[0xA0 + index * 0x20:0xC0 + index * 0x20]
            if hashlib.sha256(content).digest() != expected:
                raise ValueError('NSO 段摘要不匹配')
        segments.append((memory_at, content))
    if not memory_spans:
        raise ValueError('NSO 没有可加载的段')
    for spans in (file_spans, memory_spans):
        spans.sort()
        if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
            raise ValueError('NSO 段发生重叠')
    bss, = struct.unpack_from('<I', raw, 0x3C)
    data_end = segments[2][0] + len(segments[2][1])
    if data_end < max(end for _, end in memory_spans):
        raise ValueError('NSO data/BSS 不在全部加载段之后')
    if bss > MAX_NSO_BYTES - data_end:
        raise ValueError('NSO BSS 超过内存预算')
    result = bytearray(0x100 + max(end for _, end in memory_spans))
    result[:0x100] = raw[:0x100]
    struct.pack_into('<I', result, 0xC, (flags & ~7) | 0x38)
    # 标准解压文件以 0x100 + 段内存偏移存放内容，保留段间空洞；清除压缩文件的模块名称位置。
    struct.pack_into('<I', result, 0x1C, 0x100)
    struct.pack_into('<I', result, 0x2C, 0)
    spans = []
    for index, (memory_at, content) in enumerate(segments):
        start = 0x100 + memory_at
        struct.pack_into('<I', result, 0x10 + index * 0x10, start)
        struct.pack_into('<I', result, 0x60 + index * 4, len(content))
        result[start:start + len(content)] = content
        result[0xA0 + index * 0x20:0xC0 + index * 0x20] = hashlib.sha256(content).digest()
        if content:
            spans.append((start, start + len(content)))
    return NsoImage(bytes(result), identity, tuple(sorted(spans)))


def parse_ips(raw: bytes) -> list[Patch]:
    if len(raw) > MAX_PATCH_BYTES:
        raise ValueError('IPS 文件超过预算')
    if raw.startswith(b'PATCH'):
        width, end = 3, b'EOF'
    elif raw.startswith(b'IPS32'):
        width, end = 4, b'EEOF'
    else:
        raise ValueError('只支持标准 IPS/IPS32 头部')
    at, total, patches = 5, 0, []
    while True:
        if raw[at:at + len(end)] == end:
            if at + len(end) != len(raw):
                raise ValueError('IPS 不支持文件长度调整或尾部内容')
            return patches
        if len(patches) >= MAX_RECORDS or at + width + 2 > len(raw):
            raise ValueError('IPS 记录截断、缺少结束标记或过多')
        offset = int.from_bytes(raw[at:at + width], 'big')
        size = int.from_bytes(raw[at + width:at + width + 2], 'big')
        at += width + 2
        if size:
            if at + size > len(raw):
                raise ValueError('IPS 数据截断')
            content = raw[at:at + size]
            at += size
        else:
            if at + 3 > len(raw):
                raise ValueError('IPS RLE 记录截断')
            count = int.from_bytes(raw[at:at + 2], 'big')
            if not count:
                raise ValueError('IPS RLE 长度不能为零')
            content = raw[at + 2:at + 3] * count
            at += 3
        total += len(content)
        if total > MAX_PATCH_BYTES or offset + len(content) > 2**32:
            raise ValueError('IPS 写入超过预算或地址上限')
        patches.append(Patch(offset, content))


def _content(line: str) -> str:
    quoted, escaped = False, False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
        elif quoted and char == '\\':
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif not quoted and line[index:index + 2] == '//':
            return line[:index].strip()
    return line.strip()


def _value(text: str) -> bytes:
    if not text.startswith('"'):
        value = ''.join(text.split())
        if not value or len(value) % 2 or not re.fullmatch('[0-9a-fA-F]+', value):
            raise ValueError('补丁值必须是完整十六进制字节或引号字符串')
        return bytes.fromhex(value)
    result, at = bytearray(), 1
    escapes = {'n': 10, 'r': 13, 't': 9, 'b': 8, 'f': 12, 'v': 11, 'a': 7, '\\': 92, '"': 34, "'": 39, '?': 63}
    while at < len(text):
        char = text[at]
        at += 1
        if char == '"':
            if text[at:].strip() or not result:
                raise ValueError('字符串为空或闭合后存在额外内容')
            return bytes(result)
        if char != '\\':
            result.extend(char.encode('utf-8'))
            continue
        if at == len(text):
            raise ValueError('字符串转义截断')
        char = text[at]
        at += 1
        if char in escapes:
            result.append(escapes[char])
        elif char in '01234567' or char == 'x':
            start = at if char == 'x' else at - 1
            digits = '0123456789abcdefABCDEF' if char == 'x' else '01234567'
            end = at
            while end < len(text) and text[end] in digits and (char == 'x' or end - start < 3):
                end += 1
            if end == start:
                raise ValueError('字符串数值转义缺少数字')
            value = int(text[start:end], 16 if char == 'x' else 8)
            if value > 255:
                raise ValueError('字符串转义超过单字节范围')
            result.append(value)
            at = end
        else:
            raise ValueError('未支持的字符串转义')
    raise ValueError('字符串缺少闭合引号')


def parse_pchtxt(text: str, expected_id: str) -> list[Patch]:
    expected_id = build_id(expected_id)
    if len(text.encode('utf-8')) > 2**20 or '\0' in text:
        raise ValueError('PCHTXT 超过预算或包含空字符')
    identity, enabled, shift, total, patches = None, None, 0, 0, []
    for number, raw in enumerate(text.removeprefix('\ufeff').splitlines(), 1):
        if len(raw.encode('utf-8')) >= 4096:
            raise ValueError(f'PCHTXT 第 {number} 行过长')
        line = _content(raw)
        if not line or line.startswith('#'):
            continue
        try:
            if identity is None:
                if not line.startswith('@nsobid-') or build_id(line[8:]) != expected_id:
                    raise ValueError('首个有效指令缺少匹配的完整 NSO Build ID')
                identity = expected_id
            elif line == '@stop':
                break
            elif line in ('@enabled', '@disabled'):
                enabled = line == '@enabled'
            elif line == '@flag print_values':
                continue
            elif line.startswith('@flag offset_shift '):
                shift = int(line.split()[-1], 0)
                if len(line.split()) != 3 or not -2**32 <= shift <= 2**32:
                    raise ValueError('offset_shift 超过地址范围')
            elif line.startswith('@'):
                raise ValueError('未支持的 PCHTXT 指令')
            else:
                record = re.fullmatch(r'([0-9a-fA-F]{8})\s+(.+)', line)
                if not record or enabled is None:
                    raise ValueError('补丁记录无效或尚未声明 enabled/disabled')
                offset = int(record[1], 16) + shift
                content = _value(record[2])
                if offset < 0 or offset + len(content) > 2**32:
                    raise ValueError('补丁记录地址溢出')
                if enabled:
                    total += len(content)
                    if total > MAX_PATCH_BYTES or len(patches) >= MAX_RECORDS:
                        raise ValueError('PCHTXT 写入超过预算')
                    patches.append(Patch(offset, content, number))
        except ValueError as error:
            raise ValueError(f'PCHTXT 第 {number} 行：{error}') from error
    if identity is None:
        raise ValueError('PCHTXT 缺少 NSO Build ID')
    return patches


def apply_patches(image: NsoImage, patches: list[Patch], protected_ranges=()) -> bytes:
    """先检查完整集合，再生成新 NSO；拒绝头部、空洞、BSS 和应用保留位置。"""
    patches = tuple(patches)
    protected_ranges = tuple(protected_ranges)
    if any(type(left) is not int or type(right) is not int or left < 0x100 or left >= right or right > len(image.data)
           for left, right in protected_ranges):
        raise ValueError('应用保留位置范围无效')
    merged = []
    for left, right in sorted(protected_ranges):
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
        else:
            merged.append((left, right))
    protected_starts = [left for left, _ in merged]
    if len(patches) > MAX_RECORDS or sum(len(p.data) for p in patches) > MAX_PATCH_BYTES:
        raise ValueError('补丁集合超过预算')
    for patch in patches:
        if type(patch.offset) is not int or not isinstance(patch.data, bytes) or not patch.data:
            raise ValueError('补丁记录类型或长度无效')
        start, end = patch.offset, patch.offset + len(patch.data)
        cursor = start
        for left, right in image.spans:
            if left <= cursor < right:
                cursor = min(end, right)
            if cursor == end:
                break
        if start < 0x100 or cursor != end or end > len(image.data):
            raise ValueError(f'补丁越过 NSO 实际段：0x{start:x}')
        last = bisect.bisect_left(protected_starts, end) - 1
        if last >= 0 and merged[last][1] > start:
            raise ValueError(f'补丁与应用保留位置冲突：0x{start:x}')
    output = bytearray(image.data)
    for patch in patches:
        output[patch.offset:patch.offset + len(patch.data)] = patch.data
    for index in range(3):
        offset, _, size = struct.unpack_from('<III', output, 0x10 + index * 0x10)
        output[0xA0 + index * 0x20:0xC0 + index * 0x20] = hashlib.sha256(output[offset:offset + size]).digest()
    return bytes(output)


@dataclass(frozen=True)
class PreparedMods:
    modules: dict[str, bytes]
    inputs: dict[str, str]
    selected_patches: tuple[dict, ...]
    changed_modules: tuple[str, ...]


def _simple_name(name: str) -> bool:
    return bool(name and name not in ('.', '..') and len(name.encode('utf-8')) <= 255
                and not any(char in name for char in ('/', '\\', '\0')))


def _pchtxt_identity(text: str) -> str:
    for raw in text.removeprefix('\ufeff').splitlines():
        line = _content(raw)
        if not line or line.startswith('#'):
            continue
        if line.startswith('@nsobid-'):
            return build_id(line[8:])
        break
    raise ValueError('PCHTXT 缺少首个 NSO Build ID 指令')


def prepare_modules(originals: dict[str, bytes], patch_sets: dict[str, dict[str, bytes]], *, protected: dict) -> PreparedMods:
    """按目录/文件字节顺序准备模块快照；调用者须先核对原始版本指纹并提供全部保留区。

    仅准备数据，不发布文件或重编译。任一活动补丁失败则整次调用失败；未改变内存的模块保留原始压缩字节。
    IPS 文件名须匹配完整 Build ID（允许省略尾部零字节）；PCHTXT 使用内容内的 Build ID。
    """
    if not originals or len(originals) > 16 or len(patch_sets) > 64 or set(protected) != set(originals):
        raise ValueError('模块、mod 数量或保留区清单不完整')
    if any(not _simple_name(name) for name in originals) or any(not _simple_name(name) for name in patch_sets):
        raise ValueError('模块或 mod 名称含路径逃逸或无效字符')
    if sum(len(raw) for raw in originals.values()) > 512 * 2**20:
        raise ValueError('原始模块集合超过预算')
    images, by_id, records, selected = {}, {}, {name: [] for name in originals}, []
    total = 0
    for name, raw in originals.items():
        image = decode_nso(raw)
        total += len(image.data)
        if total > 512 * 2**20 or image.build_id in by_id:
            raise ValueError('模块集合过大或 Build ID 不唯一')
        images[name] = image
        by_id[image.build_id] = name
    total_writes = 0
    for mod in sorted(patch_sets, key=lambda name: name.encode('utf-8')):
        if mod.startswith('.'):
            continue
        for filename, raw in sorted(patch_sets[mod].items(), key=lambda item: item[0].encode('utf-8')):
            if not _simple_name(filename):
                raise ValueError('ExeFS 补丁文件名不允许包含路径')
            suffix = filename.rsplit('.', 1)[-1].lower()
            if suffix not in ('ips', 'ips32', 'pchtxt'):
                continue
            if not isinstance(raw, bytes) or len(raw) > MAX_PATCH_BYTES:
                raise ValueError(f'{mod}/{filename}：补丁不是有界字节快照')
            try:
                if suffix == 'pchtxt':
                    if len(raw) > 2**20:
                        raise ValueError('PCHTXT 超过预算')
                    text = raw.decode('utf-8-sig')
                    identity = _pchtxt_identity(text)
                    if identity not in by_id:
                        raise ValueError('PCHTXT Build ID 不属于当前模块集合')
                    patches = parse_pchtxt(text, identity)
                else:
                    identity = build_id(filename.rsplit('.', 1)[0])
                    if identity not in by_id:
                        raise ValueError('IPS 文件名 Build ID 不属于当前模块集合')
                    patches = parse_ips(raw)
                module = by_id[identity]
                total_writes += sum(len(patch.data) for patch in patches)
                if total_writes > MAX_PATCH_BYTES or len(records[module]) + len(patches) > MAX_RECORDS:
                    raise ValueError('跨 mod 补丁集合超过预算')
                records[module].extend(patches)
                selected.append({'mod': mod, 'file': filename, 'module': module, 'build_id': identity,
                                 'sha256': hashlib.sha256(raw).hexdigest(), 'records': len(patches),
                                 'write_bytes': sum(len(patch.data) for patch in patches)})
            except (ValueError, UnicodeError) as error:
                raise ValueError(f'{mod}/{filename}：{error}') from error
    outputs, changed = {}, []
    for name, image in images.items():
        result = apply_patches(image, records[name], protected[name])
        if result == image.data:
            outputs[name] = bytes(originals[name])
        else:
            outputs[name] = result
            changed.append(name)
    return PreparedMods(outputs, {name: hashlib.sha256(raw).hexdigest() for name, raw in originals.items()},
                        tuple(selected), tuple(sorted(changed)))
