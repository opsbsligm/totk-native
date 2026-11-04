"""Validate and launch the native package; keep all mutable state under XDG paths."""
import argparse
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
        env = dict(os.environ, LD_LIBRARY_PATH=str(ROOT / 'lib'))
        if totk:
            env.update(TOTK_PROFILE_DIR=str(data / 'userdata'), TOTK_SHADER_BIN=str(cache / 'compiled.bin'),
                TOTK_ROMFS=str(ROOT / 'data/romfs'), TOTK_SHADER_PACK=str(ROOT / 'data/shaders/translated.pack'),
                TOTK_BC7_DIR=str(ROOT / 'data/textures'), TOTK_BC7_CACHE_DIR=str(cache / 'textures'),
                TOTK_SHARED_FONTS=str(ROOT / 'data/fonts'))
            for key, value in dict(TOTK_LANG='zh-Hans', TOTK_OPERATION_MODE='handheld',
                TOTK_VK_POOL_SHADOW='0', TOTK_UNCAPPED='1', TOTK_UNCAPPED_HZ='60', TOTK_RT_FRAME_STEP='1').items():
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
