# SPDX-License-Identifier: MIT
"""读取有界、无软链接的输入快照，并一次发布已验证的静态补丁模块。

仅用于 Linux 私有构建。输入版本指纹由调用方的受管 profile 提供，不能从补丁或回执取得。
"""
from contextlib import contextmanager
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import uuid

from code_mods import MAX_NSO_BYTES, MAX_PATCH_BYTES, PreparedMods

MAX_FILES = 1024
MODULE_NAMES = {'main', 'sdk', *(f'subsdk{i}' for i in range(10))}


@contextmanager
def directory(path):
    """逐级打开目录；拒绝 .. 和任何一级软链接，不先 resolve 后误信路径。"""
    path = Path(path)
    if '..' in path.parts:
        raise ValueError('输入路径不允许包含 ..')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open('/' if path.is_absolute() else '.', flags)
    try:
        for part in path.parts:
            if part in ('/', '.'):
                continue
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def read_file(parent, name, maximum):
    if not name or '/' in name or '\\' in name or name in ('.', '..') or '\0' in name:
        raise ValueError('文件名无效')
    # NONBLOCK 防止 FIFO 在 fstat 前阻塞；regular-file 验证后只读取同一个 FD。
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= maximum:
            raise ValueError('输入必须是预算内的普通文件：' + name)
        chunks, size = [], 0
        while True:
            block = os.read(fd, min(2**20, maximum + 1 - size))
            if not block:
                break
            size += len(block)
            if size > maximum:
                raise ValueError('读取期间输入超过预算：' + name)
            chunks.append(block)
        after = os.fstat(fd)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if size != before.st_size or identity(before) != identity(after):
            raise ValueError('读取期间输入发生变化：' + name)
        return b''.join(chunks)
    finally:
        os.close(fd)


def snapshot_exefs(root, expected):
    if not expected or not set(expected) <= MODULE_NAMES:
        raise ValueError('缺少受管的原始模块指纹')
    result = {}
    with directory(root) as fd:
        if set(os.listdir(fd)) & MODULE_NAMES != set(expected):
            raise ValueError('ExeFS 模块清单与受管 profile 不符')
        for name, digest in expected.items():
            raw = read_file(fd, name, MAX_NSO_BYTES)
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError('原始模块指纹不符：' + name)
            result[name] = raw
    return result


def snapshot_patches(root):
    result, total, count = {}, 0, 0
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    with directory(root) as fd:
        names = os.listdir(fd)
        if len(names) > 128:
            raise ValueError('mods 根目录项目过多')
        for name in sorted(names, key=lambda value: value.encode('utf-8')):
            if name.startswith('.'):
                continue
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISREG(info.st_mode):
                continue  # README 等根目录说明不是活动 mod。
            mod = os.open(name, flags, dir_fd=fd)
            try:
                try:
                    exefs = os.open('exefs', flags, dir_fd=mod)
                except FileNotFoundError:
                    continue  # 只包含 RomFS 的 mod 不进入代码补丁集合。
                try:
                    entries = os.listdir(exefs)
                    count += len(entries)
                    if count > MAX_FILES:
                        raise ValueError('ExeFS 补丁文件过多')
                    patches = {}
                    for filename in sorted(entries, key=lambda value: value.encode('utf-8')):
                        if filename.startswith('.') or filename.lower().endswith(('.md', '.txt')):
                            continue
                        if filename.rsplit('.', 1)[-1].lower() not in ('ips', 'ips32', 'pchtxt'):
                            raise ValueError('不支持的 ExeFS 补丁文件：' + name + '/' + filename)
                        raw = read_file(exefs, filename, MAX_PATCH_BYTES)
                        total += len(raw)
                        if total > MAX_PATCH_BYTES:
                            raise ValueError('活动补丁快照超过预算')
                        patches[filename] = raw
                    result[name] = patches
                    if len(result) > 64:
                        raise ValueError('活动代码 mod 超过 64 个')
                finally:
                    os.close(exefs)
            finally:
                os.close(mod)
    return result


def manifest(prepared: PreparedMods):
    return {'schema': 1, 'inputs': prepared.inputs,
            'patches': list(prepared.selected_patches), 'changed_modules': list(prepared.changed_modules),
            'outputs': {name: {'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                        for name, raw in sorted(prepared.modules.items())}}


def publish(prepared: PreparedMods, target):
    """全部内容先写入私有同卷目录，再用 Linux RENAME_NOREPLACE 一次发布，失败清理。

    不覆盖已有目录（包括空目录/软链接）。回执仅作溯源，后续生成或打包仍须重新绑定输入和输出。
    """
    target = Path(target)
    if target.name in ('', '.', '..'):
        raise ValueError('发布目标无效')
    rename = getattr(ctypes.CDLL(None, use_errno=True), 'renameat2', None)
    if rename is None:
        raise ValueError('需要支持 renameat2 的 Linux 构建环境')
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    raw_manifest = (json.dumps(manifest(prepared), sort_keys=True, indent=2) + '\n').encode()
    with directory(target.parent) as parent:
        pending = '.code-mods-' + uuid.uuid4().hex
        os.mkdir(pending, mode=0o700, dir_fd=parent)
        owned = True
        try:
            fd = os.open(pending, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                for name, raw in [*prepared.modules.items(), ('manifest.json', raw_manifest)]:
                    if name != 'manifest.json' and name not in MODULE_NAMES:
                        raise ValueError('发布模块名称无效')
                    child = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
                    with os.fdopen(child, 'wb') as stream:
                        stream.write(raw)
                        stream.flush()
                        os.fsync(stream.fileno())
                os.fsync(fd)
            finally:
                os.close(fd)
            if rename(parent, os.fsencode(pending), parent, os.fsencode(target.name), 1):
                error = ctypes.get_errno()
                if error == errno.EEXIST:
                    raise FileExistsError('准备目标已存在：' + str(target))
                raise OSError(error, os.strerror(error))
            owned = False
            os.fsync(parent)
        finally:
            if owned:
                shutil.rmtree(pending, dir_fd=parent)
    return manifest(prepared)
