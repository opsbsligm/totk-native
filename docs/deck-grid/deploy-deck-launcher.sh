#!/usr/bin/env bash
# 安装 Steam 启动器到掌机。与 deploy-deck-art.sh 一样按脚本所在目录解析文件，
# 全新 Deck 只要拿到本目录就能复原入口；已有启动器先备份再覆盖。
set -euo pipefail
GAME="${GAME:-totk}"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="${LAUNCHER_DIR:-$HOME/native-recomp/launchers}"
SRC="$SRC_DIR/$GAME-steam.sh"
[ -f "$SRC" ] || { echo "missing $SRC"; exit 1; }
mkdir -p "$BIN_DIR"
TS="$(date +%Y%m%d%H%M%S)"
if [ -f "$BIN_DIR/$GAME-steam.sh" ]; then
  cmp -s "$SRC" "$BIN_DIR/$GAME-steam.sh" && { echo "unchanged: $BIN_DIR/$GAME-steam.sh"; exit 0; }
  cp -p "$BIN_DIR/$GAME-steam.sh" "$BIN_DIR/.bak-$TS-$GAME-steam.sh"
  echo "backup: $BIN_DIR/.bak-$TS-$GAME-steam.sh"
fi
install -m 755 "$SRC" "$BIN_DIR/$GAME-steam.sh"
echo "installed: $BIN_DIR/$GAME-steam.sh"
