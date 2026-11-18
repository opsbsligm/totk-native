#!/usr/bin/env bash
# 复原本作在 Steam 库里的存在：非 Steam 快捷方式本身、九宫格图与快捷方式图标。
# 全新 Deck 的重建步骤。把本目录整个拷到掌机上、就地运行，图片才按脚本所在目录解析：
#   scp -r docs/deck-grid deck@DECK:/tmp/deck-grid-totk
#   ssh deck@DECK /tmp/deck-grid-totk/deploy-deck-art.sh
#
# 实际工作交给 deck-shortcut.py：它找出本机已有快捷方式的 Steam 账号，沿用 Steam 已经
# 分配给本启动器的 appid（重建后仍落在同一条目上），重写 shortcuts.vdf 且不惊动其他快捷
# 方式，并把残留的 <appid>_logo.png 挪走——否则 Steam 会用旧字标盖住新的九宫格图。
# 多账号 Deck 传 STEAM_ID 指定账号。
set -euo pipefail
GAME="${GAME:-totk}"
NAME="${GAME_NAME:-塞尔达传说：王国之泪（原生）}"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
LAUNCHER="${LAUNCHER:-$HOME/native-recomp/launchers/$GAME-steam.sh}"
STEAM="${STEAM_ROOT:-$HOME/.local/share/Steam}"
[ -f "$LAUNCHER" ] || { echo "launcher not installed: $LAUNCHER (run deploy-deck-launcher.sh first)"; exit 1; }
[ -d "$STEAM/userdata" ] || { echo "no Steam userdata under $STEAM"; exit 1; }

ARGS=(--launcher "$LAUNCHER" --name "$NAME" --art-dir "$SRC_DIR" --art-prefix "$GAME"
      --icon-dir "$STEAM/appicons")
[ -n "${STEAM_ID:-}" ] && ARGS+=(--steam-id "$STEAM_ID")

python3 "$SRC_DIR/deck-shortcut.py" "${ARGS[@]}"
