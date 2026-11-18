"""A fresh Deck gets its library entry back from the launcher alone, and nothing else moves.

`docs/deck-grid/deploy-deck-art.sh` is the rebuild step; `deck-shortcut.py` behind it has to
read and rewrite Valve's binary shortcuts.vdf. These checks build the file by hand so the
parser is tested against the format, not against itself.
"""
from pathlib import Path
import importlib.util, os, shutil, struct, subprocess, sys, tempfile, unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'docs/deck-grid/deck-shortcut.py'


def _s(key, value):
    return b'\x01' + key + b'\x00' + value + b'\x00'


def _i(key, value):
    return b'\x02' + key + b'\x00' + struct.pack('<I', value)


def _entry(appid, name, exe, icon=b''):
    """One shortcut in the field order Steam itself writes."""
    body = (_i(b'appid', appid) + _s(b'AppName', name) + _s(b'Exe', b'"' + exe + b'"')
            + _s(b'StartDir', b'"' + os.path.dirname(exe) + b'"') + _s(b'icon', icon)
            + _s(b'ShortcutPath', b'') + _s(b'LaunchOptions', b'') + _i(b'IsHidden', 0)
            + _i(b'AllowDesktopConfig', 1) + _i(b'AllowOverlay', 1) + _i(b'OpenVR', 0)
            + _i(b'Devkit', 0) + _s(b'DevkitGameID', b'') + _i(b'DevkitOverrideAppID', 0)
            + _i(b'LastPlayTime', 1794791943) + _s(b'FlatpakAppID', b'') + _s(b'sortas', b'')
            + b'\x00tags\x00\x08')
    return body


def _vdf(entries):
    out = b'\x00shortcuts\x00'
    for n, body in enumerate(entries):
        out += b'\x00' + str(n).encode() + b'\x00' + body + b'\x08'
    return out + b'\x08'


def _load():
    spec = importlib.util.spec_from_file_location('deck_shortcut', SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class DeckShortcut(unittest.TestCase):
    def setUp(self):
        self.m = _load()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.steam = self.root / 'Steam'
        self.config = self.steam / 'userdata' / '777777777' / 'config'
        self.config.mkdir(parents=True)
        self.launchers = self.root / 'launchers'
        self.launchers.mkdir()
        self.launcher = self.launchers / 'totk-steam.sh'
        self.launcher.write_text('#!/bin/sh\nexec true\n')
        os.chmod(self.launcher, 0o755)
        # Unrelated shortcuts must survive untouched; `_write_vdf` lays them down.

    def _write_vdf(self, extra=None):
        entries = [_entry(3427961829, b'Parsec', b'/usr/bin/flatpak'),
                   _entry(3291722138, b'Other game', b'/home/deck/other.sh')]
        if extra is not None:
            entries.append(extra)
        data = _vdf(entries)
        (self.config / 'shortcuts.vdf').write_bytes(data)
        return data

    def _run(self, *extra):
        return subprocess.run([sys.executable, str(SCRIPT), '--launcher', str(self.launcher),
                               '--steam-root', str(self.steam), *extra],
                              capture_output=True, text=True, timeout=60)

    def test_round_trip_is_byte_identical(self):
        data = self._write_vdf()
        name, entries, trailing = self.m.load(self.config / 'shortcuts.vdf')
        self.assertEqual(name, b'shortcuts')
        self.assertEqual(len(entries), 2)
        out = self.root / 'out.vdf'
        self.assertEqual(self.m.save(out, name, entries, trailing), data)

    def test_unrelated_shortcuts_survive(self):
        self._write_vdf()
        r = self._run('--name', '塞尔达传说：王国之泪（原生）')
        self.assertEqual(r.returncode, 0, r.stderr)
        _, entries, _ = self.m.load(self.config / 'shortcuts.vdf')
        ids = [self.m._int(e, b'appid') for e in entries]
        self.assertEqual(ids[:2], [3427961829, 3291722138])
        self.assertEqual(self.m._text(entries[0], b'AppName'), 'Parsec')
        self.assertEqual(self.m._text(entries[1], b'Exe'), '"/home/deck/other.sh"')

    def test_existing_entry_keeps_its_appid(self):
        # Steam already gave this launcher an appid; the rebuild must reuse it so grid
        # art installed under the old id keeps working.
        self._write_vdf(_entry(2245023905, b'old name', str(self.launcher).encode()))
        r = self._run('--name', '塞尔达传说：王国之泪（原生）')
        self.assertEqual(r.returncode, 0, r.stderr)
        _, entries, _ = self.m.load(self.config / 'shortcuts.vdf')
        self.assertEqual(len(entries), 3)
        mine = [e for e in entries if self.m._int(e, b'appid') == 2245023905]
        self.assertEqual(len(mine), 1)
        self.assertEqual(self.m._text(mine[0], b'AppName'), '塞尔达传说：王国之泪（原生）')
        self.assertIn('2245023905', r.stdout)

    def test_install_is_idempotent(self):
        self._write_vdf()
        first = self._run('--name', 'TOTK')
        self.assertEqual(first.returncode, 0, first.stderr)
        bytes_after_first = (self.config / 'shortcuts.vdf').read_bytes()
        second = self._run('--name', 'TOTK')
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn('unchanged', second.stdout)
        self.assertEqual((self.config / 'shortcuts.vdf').read_bytes(), bytes_after_first)
        _, entries, _ = self.m.load(self.config / 'shortcuts.vdf')
        self.assertEqual(len(entries), 3)

    def test_check_does_not_write(self):
        data = self._write_vdf()
        r = self._run('--name', 'TOTK', '--check')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('entry is current: False', r.stdout)
        self.assertEqual((self.config / 'shortcuts.vdf').read_bytes(), data)

    def test_missing_launcher_is_refused(self):
        data = self._write_vdf()
        gone = self.launchers / 'nope-steam.sh'
        r = subprocess.run([sys.executable, str(SCRIPT), '--launcher', str(gone),
                            '--name', 'x', '--steam-root', str(self.steam)],
                           capture_output=True, text=True, timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('launcher not found', r.stderr + r.stdout)
        self.assertEqual((self.config / 'shortcuts.vdf').read_bytes(), data)

    def test_art_and_icon_are_installed_or_named(self):
        self._write_vdf()
        art = self.root / 'art'
        art.mkdir()
        for stem in ('-grid', '-grid-p', '-hero'):
            (art / ('totk%s.png' % stem)).write_bytes(b'PNG' + stem.encode())
        icons = self.root / 'appicons'
        base = ['--name', 'TOTK', '--art-dir', str(art), '--art-prefix', 'totk',
                '--icon-dir', str(icons)]
        r = self._run(*base)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('shortcut icon not found', r.stderr + r.stdout)
        (art / 'totk-shortcut-icon.png').write_bytes(b'ICON')
        r = self._run(*base)
        self.assertEqual(r.returncode, 0, r.stderr)
        grid = self.config / 'grid'
        appid = int(r.stdout.split('appid: ')[1].split()[0])
        self.assertEqual((grid / ('%d.png' % appid)).read_bytes(), b'PNG-grid')
        self.assertEqual((grid / ('%dp.png' % appid)).read_bytes(), b'PNG-grid-p')
        self.assertEqual((grid / ('%d_hero.png' % appid)).read_bytes(), b'PNG-hero')
        self.assertEqual((icons / 'totk-shortcut-icon.png').read_bytes(), b'ICON')
        # A stale wordmark would be drawn over the new art, so it has to be moved aside.
        stale = grid / ('%d_logo.png' % appid)
        stale.write_bytes(b'STALE')
        r = self._run(*base)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(stale.exists())
        self.assertTrue(any(p.name.endswith('_logo.png') for p in grid.glob('.bak-*')))


if __name__ == '__main__':
    unittest.main()
