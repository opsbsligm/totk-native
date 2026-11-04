"""Validate and launch the native package; keep all mutable state under XDG paths."""
import argparse
from datetime import datetime, timezone
import shutil
import stat
import tempfile
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def checked_files(manifest, full):
    for name, expected in manifest['files'].items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Invalid manifest path: ' + name)
        path = ROOT / relative
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('Package file is a symlink: ' + name)
        if not path.is_file() or path.stat().st_size != expected['size']:
            raise ValueError('Missing or truncated package file: ' + name)
        if full or name in ('ultratears', 'savagewind', 'data/swgame.so') or name.startswith('lib/') or path.suffix in ('.py', '.sh'):
            with path.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != expected['sha256']:
                    raise ValueError('Package file checksum mismatch: ' + name)


def xdg(variable, default):
    value = os.environ.get(variable, '')
    return Path(value) if value.startswith('/') else Path.home() / default



MAX_SAVE_BYTES = 512 * 1024 * 1024


def atomic_json(path, value):
    fd, name = tempfile.mkstemp(prefix='.status-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def save_inventory(root):
    if root.is_symlink():
        raise ValueError('存档根目录不能是符号链接')
    if not root.exists():
        return {}
    if not root.is_dir():
        raise ValueError('存档路径不是目录')
    result, total = {}, 0
    def fail_walk(error):
        raise error
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=fail_walk):
        for name in dirs:
            if (Path(directory)/name).is_symlink():
                raise ValueError('存档目录含符号链接')
        for name in sorted(files):
            path = Path(directory)/name
            before = path.lstat()
            if not stat.S_ISREG(before.st_mode):
                raise ValueError('存档目录含非普通文件')
            total += before.st_size
            if total > MAX_SAVE_BYTES or len(result) >= 4096:
                raise ValueError('存档超过备份上限，未启动游戏')
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024*1024), b''):
                    digest.update(block)
            after = path.lstat()
            if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
                raise ValueError('存档仍在变化，未启动游戏')
            result[path.relative_to(root).as_posix()] = {'size': before.st_size, 'sha256': digest.hexdigest()}
    return dict(sorted(result.items()))


def backup_saves(source, destination):
    """Copy only while idle, verify both sides, then publish an immutable snapshot."""
    inventory = save_inventory(source)
    if not inventory:
        return {'snapshot': None, 'files': 0}
    digest = hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest()
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = destination/digest
    if target.exists():
        if save_inventory(target/'save') != inventory:
            raise ValueError('已有存档备份校验失败，保留原文件')
        return {'snapshot': digest, 'files': len(inventory), 'reused': True}
    if shutil.disk_usage(destination).free < sum(v['size'] for v in inventory.values()) + 256*1024*1024:
        raise ValueError('存档备份空间不足，未启动游戏')
    stage = Path(tempfile.mkdtemp(prefix='.snapshot-', dir=destination))
    try:
        (stage/'save').mkdir(mode=0o700)
        for name in inventory:
            out = stage/'save'/name
            out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy2(source/name, out)
            out.chmod(0o600)
            with out.open('rb') as stream:
                os.fsync(stream.fileno())
        if save_inventory(stage/'save') != inventory or save_inventory(source) != inventory:
            raise ValueError('存档备份或源文件并发校验失败，未启动游戏')
        atomic_json(stage/'manifest.json', {'files': inventory, 'created_at': datetime.now(timezone.utc).isoformat()})
        stage.rename(target)
        return {'snapshot': digest, 'files': len(inventory), 'reused': False}
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--verify', action='store_true', help='Verify all data without starting the game')
    args, game_args = p.parse_known_args()
    manifest = json.loads((ROOT / 'bundle.json').read_text())
    if manifest.get('schema') != 1 or manifest.get('version') not in ('1.4.3', '1.6.0'):
        p.error('Unsupported package manifest')
    checked_files(manifest, args.verify)
    if args.verify:
        print('All package files verified')
        return 0
    totk = manifest['version'] == '1.4.3'
    data = xdg('XDG_DATA_HOME', '.local/share') / ('ultratears' if totk else 'savagewind')
    cache = xdg('XDG_CACHE_HOME', '.cache') / ('totk-native' if totk else 'botw-native')
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (data / 'native-session.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('This game is already running')
        backup_saves(data / ('userdata' if totk else 'save'), data / 'native-save-backups')
        env = dict(os.environ, LD_LIBRARY_PATH=str(ROOT / 'lib'))
        if totk:
            env.update(TOTK_PROFILE_DIR=str(data / 'userdata'), TOTK_SHADER_BIN=str(cache / 'compiled.bin'),
                TOTK_ROMFS=str(ROOT / 'data/romfs'), TOTK_SHADER_PACK=str(ROOT / 'data/shaders/translated.pack'),
                TOTK_BC7_DIR=str(ROOT / 'data/textures'), TOTK_BC7_CACHE_DIR=str(cache / 'textures'),
                TOTK_SHARED_FONTS=str(ROOT / 'data/fonts'))
            for key, value in dict(TOTK_LANG='zh-Hans', TOTK_OPERATION_MODE='handheld',
                TOTK_VK_POOL_SHADOW='0', TOTK_UNCAPPED='1', TOTK_UNCAPPED_HZ='60',
                TOTK_FPS60='1', TOTK_REALTIME='1', TOTK_UNCAPPED_INTERVAL='1',
                TOTK_STEAMDECK_UI='1').items():
                env.setdefault(key, value)
            cmd = [sys.executable, str(ROOT / 'motion_session.py'), str(ROOT / 'game.sh')]
            # game.sh receives only package-controlled arguments; game options remain on the ELF command line.
            if game_args:
                p.error('This package currently accepts only --verify')
        else:
            env.update(SAVAGEWIND_DATA_ROOT=str(data))
            env.setdefault('SAVAGEWIND_FPS', '0')
            env.setdefault('SAVAGEWIND_FRAMEPACE', '1')
            cmd = [str(ROOT / 'savagewind'), '--play', str(ROOT / 'data'), *game_args]
        # exec preserves the session lock and gives Steam direct signal/process ownership.
        os.set_inheritable(lock.fileno(), True)
        os.chdir(data)
        os.execvpe(cmd[0], cmd, env)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(str(error))
