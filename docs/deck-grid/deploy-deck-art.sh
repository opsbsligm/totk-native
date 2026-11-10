#!/usr/bin/env bash
# Restore the Steam Deck grid art + shortcut icon for the TOTK native shortcut.
# Fresh-Deck rebuild step. Copy this directory to the Deck and run it there so
# the art files resolve next to the script:
#   scp -r docs/deck-grid deck@DECK:/tmp/deck-grid-totk
#   ssh deck@DECK /tmp/deck-grid-totk/deploy-deck-art.sh
#
# shortcuts.vdf on SteamOS is a binary format (field names NUL-terminated,
# values length-prefixed), so the appid is resolved by parsing it, with
# 4131851805 as the verified fallback. Override with TOTK_APPID. A stale
# <appid>_logo.png makes Steam draw the old wordmark over the grid art, so it
# is backed up and moved aside before the new art is installed.
set -euo pipefail
APPID="${TOTK_APPID:-4131851805}"
VDF="$HOME/.local/share/Steam/userdata/404491794/config/shortcuts.vdf"
RESOLVED="$(python3 - "$VDF" totk-steam.sh <<'PY'
import re, sys
data = open(sys.argv[1], "rb").read()
for m in re.finditer(rb"appid\x00", data):
    appid = int.from_bytes(data[m.end():m.end()+4], "little")
    end = data.find(b"appid\x00", m.end())
    seg = data[m.end():end if end > 0 else len(data)]
    if sys.argv[2].encode() in seg:
        print(appid); break
PY
)"
if [ -n "$RESOLVED" ] && [ "$RESOLVED" != "$APPID" ]; then
  echo "shortcuts.vdf appid $RESOLVED differs from $APPID; using $RESOLVED"
  APPID="$RESOLVED"
fi
GRID="${GRID_DIR:-$HOME/.local/share/Steam/userdata/404491794/config/grid}"
ASSETS="${ASSETS_DIR:-/home/deck/native-recomp/evidence/library-unlock-20261103/assets}"
SRC_DIR="${ART_DIR:-$(cd "$(dirname "$0")" && pwd)}"

mkdir -p "$GRID" "$ASSETS"
TS="$(date +%Y%m%d%H%M%S)"
BAK="$GRID/.bak-${TS}"; mkdir -p "$BAK"
[ -f "$GRID/${APPID}.png" ]   && cp -p "$GRID/${APPID}.png"   "$BAK/" || true
[ -f "$GRID/${APPID}p.png" ]  && cp -p "$GRID/${APPID}p.png"  "$BAK/" || true
[ -f "$GRID/${APPID}_logo.png" ] && cp -p "$GRID/${APPID}_logo.png" "$BAK/" || true
[ -f "$GRID/${APPID}_logo.png" ] && mv -v "$GRID/${APPID}_logo.png" "$BAK/${APPID}_logo.removed" || true
[ -f "$ASSETS/totk-icon.png" ] && cp -p "$ASSETS/totk-icon.png" "$ASSETS/.bak-${TS}-totk-icon.png" || true

install -m 755 "$SRC_DIR/totk-grid.png"          "$GRID/${APPID}.png"
install -m 755 "$SRC_DIR/totk-hero.png"          "$GRID/${APPID}_hero.png"
install -m 755 "$SRC_DIR/totk-grid-p.png"        "$GRID/${APPID}p.png"
install -m 644 "$SRC_DIR/totk-shortcut-icon.png" "$ASSETS/totk-icon.png"

echo "grid dir: $GRID"
echo "appid: $APPID"
md5sum "$GRID/${APPID}.png" "$GRID/${APPID}_hero.png" "$GRID/${APPID}p.png" "$ASSETS/totk-icon.png"
echo "backup: $BAK and $ASSETS/.bak-${TS}-totk-icon.png"
