#!/usr/bin/env python3
r"""Install or refresh one non-Steam shortcut on Steam Deck, then its grid art.

Fresh-Deck rebuild step: nothing here is tied to a specific Steam account or to
the appid Steam happened to assign, so the same command restores the entry on a
reinstalled machine. shortcuts.vdf is Valve's binary format: a section is
0x00 <name>\0 <members> 0x08, a string is 0x01 <key>\0 <value>\0 and an integer
is 0x02 <key>\0 <uint32>. The file is parsed and rewritten as typed fields, and
every entry this script does not own is re-serialised byte for byte.

Run it on the Deck (it needs no network and no Steam restart to be useful):
    python3 deck-shortcut.py --launcher ~/native-recomp/launchers/totk-steam.sh \
        --name "塞尔达传说：王国之泪（原生）" --art-dir . --icon-dir ~/.local/share/Steam/appicons
`deploy-deck-art.sh` is the one-command wrapper for exactly that.
"""
import argparse
import binascii
import os
import pathlib
import re
import struct
import sys
import time

INT, STR, SEC = "int", "str", "sec"


def _cstr(buf, i):
    j = buf.index(b"\x00", i)
    return buf[i:j], j + 1


def _parse(buf, i):
    """Read one section body; return (members, offset of the 0x08 that closes it)."""
    members = []
    while i < len(buf):
        kind = buf[i]
        if kind == 0x08:
            return members, i
        if kind == 0x00:
            name, i = _cstr(buf, i + 1)
            body, i = _parse(buf, i)
            if buf[i] != 0x08:
                raise SystemExit("shortcuts.vdf: section at byte %d unclosed" % i)
            members.append((SEC, name, body))
            i += 1
        elif kind == 0x01:
            key, i = _cstr(buf, i + 1)
            value, i = _cstr(buf, i)
            members.append((STR, key, value))
        elif kind == 0x02:
            key, i = _cstr(buf, i + 1)
            members.append((INT, key, struct.unpack("<I", buf[i:i + 4])[0]))
            i += 4
        else:
            raise SystemExit("shortcuts.vdf: unknown type %#x at byte %d" % (kind, i))
    raise SystemExit("shortcuts.vdf: section not terminated")


def _emit(members):
    out = bytearray()
    for kind, key, value in members:
        if kind is SEC:
            out += b"\x00" + key + b"\x00" + _emit(value) + b"\x08"
        elif kind is STR:
            out += b"\x01" + key + b"\x00" + value + b"\x00"
        else:
            out += b"\x02" + key + b"\x00" + struct.pack("<I", value)
    return bytes(out)


def load(path):
    """Return (header, [entry], trailing) where an entry is (key, members)."""
    buf = path.read_bytes()
    if not buf or buf[0] != 0x00:
        raise SystemExit("shortcuts.vdf: expected a binary shortcuts section")
    name, i = _cstr(buf, 1)
    members, end = _parse(buf, i)
    if buf[end] != 0x08:
        raise SystemExit("shortcuts.vdf: shortcuts section unclosed")
    # `end` stays on the section's own terminator so it is written back verbatim.
    entries = [(key, body) for kind, key, body in members if kind is SEC]
    return name, entries, buf[end:]


def save(path, name, entries, trailing):
    body = _emit([(SEC, key, members) for key, members in entries])
    data = b"\x00" + name + b"\x00" + body + trailing
    if len(data) > 1 << 20:
        raise SystemExit("shortcuts.vdf grew past a sane size; refusing to write")
    tmp = path.with_name(path.name + ".nd-tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return data


def app_id(launcher):
    """Stable shortcut id in Steam's non-Steam range, derived from the launcher."""
    return 0x80000000 | (binascii.crc32(str(launcher).encode()) & 0x7FFFFFFF)


def find_userdata(root):
    """The one Steam account on this Deck that already has shortcuts."""
    if not root.is_dir():
        return None
    hits = [p for p in sorted(root.iterdir())
            if p.is_dir() and re.fullmatch(r"\d+", p.name)
            and (p / "config" / "shortcuts.vdf").is_file()]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise SystemExit("more than one Steam account has shortcuts; pass --steam-id")
    return None


def _fields(entry):
    return {key: (kind, value) for kind, key, value in entry[1]}


def _text(entry, key):
    """Decoded value of a string field, or '' when the entry has no such field."""
    kind_value = _fields(entry).get(key)
    if kind_value is None or kind_value[0] is not STR:
        return ""
    return kind_value[1].decode("utf-8", "replace")


def _int(entry, key, default=None):
    kind_value = _fields(entry).get(key)
    if kind_value is None or kind_value[0] is not INT:
        return default
    return kind_value[1]


def _quoted(path):
    """Steam stores Exe and StartDir quoted, exactly as it writes them itself."""
    return ('"%s"' % str(path)).encode()


def _unquoted(value):
    return value[1:-1] if len(value) > 1 and value.startswith('"') and value.endswith('"') else value


def _matches_launcher(entry, launcher):
    """True when this shortcut already runs our launcher (by path, then by name)."""
    exe = _unquoted(_text(entry, b"Exe"))
    if not exe:
        return False
    return exe == str(launcher) or os.path.basename(exe) == launcher.name


def _set(members, kind, key, value):
    for n, (k, kk, vv) in enumerate(members):
        if kk == key:
            if (k, vv) == (kind, value):
                return False
            members[n] = (kind, key, value)
            return True
    members.append((kind, key, value))
    return True


def template(appid, launcher, name, icon):
    """A new entry in the field order Steam itself writes."""
    return [
        (INT, b"appid", appid),
        (STR, b"AppName", name.encode()),
        (STR, b"Exe", _quoted(launcher)),
        (STR, b"StartDir", _quoted(launcher.parent)),
        (STR, b"icon", str(icon).encode()),
        (STR, b"ShortcutPath", b""),
        (STR, b"LaunchOptions", b""),
        (INT, b"IsHidden", 0),
        (INT, b"AllowDesktopConfig", 1),
        (INT, b"AllowOverlay", 1),
        (INT, b"OpenVR", 0),
        (INT, b"Devkit", 0),
        (STR, b"DevkitGameID", b""),
        (INT, b"DevkitOverrideAppID", 0),
        (INT, b"LastPlayTime", 0),
        (STR, b"FlatpakAppID", b""),
        (STR, b"sortas", b""),
        (SEC, b"tags", []),
    ]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--launcher", required=True, type=pathlib.Path, help="existing launcher script")
    p.add_argument("--name", required=True, help="name shown in Steam")
    p.add_argument("--art-dir", type=pathlib.Path, help="directory with the grid art from this repo")
    p.add_argument("--art-prefix", default="", help="file-name prefix of the art in --art-dir")
    p.add_argument("--icon-dir", type=pathlib.Path,
                   help="where <prefix>-shortcut-icon.png is installed and read from by Steam")
    p.add_argument("--steam-id", help="Steam account id when the Deck has several")
    p.add_argument("--steam-root", type=pathlib.Path, default=pathlib.Path.home() / ".local/share/Steam")
    p.add_argument("--appid", type=lambda s: int(s, 0), help="force a specific appid")
    p.add_argument("--check", action="store_true", help="report the current state and change nothing")
    a = p.parse_args()

    launcher = a.launcher.expanduser().resolve()
    if not launcher.is_file():
        raise SystemExit("launcher not found: %s" % launcher)
    os.umask(0o077)
    if a.steam_id:
        account = a.steam_root / "userdata" / a.steam_id
        vdf = account / "config" / "shortcuts.vdf"
    else:
        account = find_userdata(a.steam_root / "userdata")
        if account is None:
            raise SystemExit("no Steam account with shortcuts.vdf under %s; add any non-Steam "
                             "game once in Steam, or pass --steam-id" % (a.steam_root / "userdata"))
        vdf = account / "config" / "shortcuts.vdf"

    icon_path = ""
    icon_src = None
    if a.art_dir:
        if a.icon_dir is None:
            raise SystemExit("--art-dir needs --icon-dir so the shortcut icon has a home")
        icon_src = a.art_dir.expanduser() / ("%s-shortcut-icon.png" % a.art_prefix)
        if not icon_src.is_file():
            raise SystemExit("shortcut icon not found: %s" % icon_src)
        icon_path = str((a.icon_dir / ("%s-shortcut-icon.png" % a.art_prefix)).resolve(strict=False))

    if vdf.is_file():
        name, entries, trailing = load(vdf)
    else:
        name, entries, trailing = b"shortcuts", [], b"\x08"

    existing = next((e for e in entries if _matches_launcher(e, launcher)), None)
    target = a.appid or (_int(existing, b"appid") if existing else None) or app_id(launcher)

    icon = icon_path if icon_src is not None else (_text(existing, b"icon") if existing else "")
    updates = [(INT, b"appid", target), (STR, b"AppName", a.name.encode()),
               (STR, b"Exe", _quoted(launcher)), (STR, b"StartDir", _quoted(launcher.parent)),
               (STR, b"icon", icon.encode())]

    def plan():
        """Whether the entry already carries every field we intend to write."""
        if existing is None:
            return True
        want = {k: (t, v) for t, k, v in updates}
        current = _fields(existing)
        return any(current.get(k) != v for k, v in want.items())

    if a.art_dir and not a.art_prefix:
        raise SystemExit("--art-dir needs --art-prefix (the repo names its art totk-*.png)")

    grid = account / "config" / "grid"
    art = []
    if a.art_dir:
        art_dir = a.art_dir.expanduser().resolve()
        found = 0
        for stem, suffix in (("-grid", ".png"), ("-grid-p", "p.png"), ("-hero", "_hero.png")):
            f = art_dir / ("%s%s.png" % (a.art_prefix, stem))
            if f.is_file():
                found += 1
                art.append((f, grid / ("%d%s" % (target, suffix))))
        if not found:
            raise SystemExit("no %s-grid.png / %s-grid-p.png / %s-hero.png in %s"
                             % (a.art_prefix, a.art_prefix, a.art_prefix, art_dir))

    if a.check:
        print("vdf: %s" % vdf)
        print("appid: %d" % target)
        print("launcher entry present: %s" % (existing is not None))
        print("entry is current: %s" % (not plan()))
        for src, dst in art:
            ok = dst.is_file() and src.read_bytes() == dst.read_bytes()
            print("art %s: %s" % ("current" if ok else "differs", dst))
        return 0

    members = existing[1] if existing is not None else None
    if members is None:
        members = template(target, launcher, a.name, icon)
        entries.append((str(len(entries)).encode(), members))
        for kind, fld, value in updates:
            _set(members, kind, fld, value)
        changed = True
    else:
        changed = False
        for kind, fld, value in updates:
            changed |= _set(members, kind, fld, value)

    if changed:
        if vdf.is_file():
            stamp = time.strftime("%Y%m%d%H%M%S")
            backup = vdf.with_name(".bak-%s-shortcuts.vdf" % stamp)
            backup.write_bytes(vdf.read_bytes())
            print("backup: %s" % backup)
        vdf.parent.mkdir(parents=True, exist_ok=True)
        data = save(vdf, name, entries, trailing)
        print("wrote %s (%d bytes, %d shortcuts)" % (vdf, len(data), len(entries)))
    else:
        print("unchanged: %s" % vdf)

    if icon_src is not None:
        dst = pathlib.Path(icon_path)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.is_file() or dst.read_bytes() != icon_src.read_bytes():
            dst.write_bytes(icon_src.read_bytes())
            print("icon: %s" % dst)
        else:
            print("icon unchanged: %s" % dst)

    stale = grid / ("%d_logo.png" % target)
    if stale.is_file():
        stamp = time.strftime("%Y%m%d%H%M%S")
        os.replace(stale, stale.with_name(".bak-%s-%s" % (stamp, stale.name)))
        print("stale logo moved aside: %s" % stale)
    for src, dst in art:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_file() and src.read_bytes() == dst.read_bytes():
            print("art unchanged: %s" % dst)
            continue
        if dst.is_file():
            stamp = time.strftime("%Y%m%d%H%M%S")
            os.replace(dst, dst.with_name(".bak-%s-%s" % (stamp, dst.name)))
        dst.write_bytes(src.read_bytes())
        print("art: %s" % dst)
    print("appid: %d  restart Steam to refresh the library" % target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
