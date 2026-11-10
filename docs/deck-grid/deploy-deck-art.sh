#!/usr/bin/env bash
# Restore the Steam Deck grid art + shortcut icon for the TOTK native shortcut.
# Fresh-Deck rebuild step. Copy this directory to the Deck and run it there so
# the art files resolve next to the script:
#   scp -r docs/deck-grid deck@DECK:/tmp/deck-grid-totk
#   ssh deck@DECK /tmp/deck-grid-totk/deploy-deck-art.sh
set -euo pipefail
APPID="${TOTK_APPID:-4131851805}"   # from shortcuts.vdf; re-verify after a fresh install
GRID="${GRID_DIR:-$HOME/.local/share/Steam/userdata/404491794/config/grid}"
ASSETS="${ASSETS_DIR:-/home/deck/native-recomp/evidence/library-unlock-20261103/assets}"
SRC_DIR="${ART_DIR:-$(cd "$(dirname "$0")" && pwd)}"

mkdir -p "$GRID" "$ASSETS"
TS="$(date +%Y%m%d%H%M%S)"
BAK="$GRID/.bak-${TS}"; mkdir -p "$BAK"
[ -f "$GRID/${APPID}.png" ]   && cp -p "$GRID/${APPID}.png"   "$BAK/" || true
[ -f "$GRID/${APPID}p.png" ]  && cp -p "$GRID/${APPID}p.png"  "$BAK/" || true
[ -f "$ASSETS/totk-icon.png" ] && cp -p "$ASSETS/totk-icon.png" "$ASSETS/.bak-${TS}-totk-icon.png" || true

install -m 755 "$SRC_DIR/totk-grid.png"          "$GRID/${APPID}.png"
install -m 755 "$SRC_DIR/totk-hero.png"          "$GRID/${APPID}_hero.png"
install -m 755 "$SRC_DIR/totk-grid-p.png"        "$GRID/${APPID}p.png"
install -m 644 "$SRC_DIR/totk-shortcut-icon.png" "$ASSETS/totk-icon.png"

echo "grid dir: $GRID"
md5sum "$GRID/${APPID}.png" "$GRID/${APPID}_hero.png" "$GRID/${APPID}p.png" "$ASSETS/totk-icon.png"
echo "backup: $BAK and $ASSETS/.bak-${TS}-totk-icon.png"
