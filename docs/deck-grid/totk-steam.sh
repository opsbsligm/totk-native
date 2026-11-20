#!/usr/bin/env bash
# Steam 入口：A=确认 B=取消、60 帧、原生陀螺仪。发布版本由 current/bundle.json 决定，
# 升级发布不需要改这里；全新 Deck 把本文件装到 ~/native-recomp/launchers/ 即可复原入口。
# XDG_DATA_HOME 固定在这台掌机已有存档的位置：改动会让游戏读到另一份较旧的存档，
# 看起来像丢档。要搬家请连同 userdata/ 一起迁移，不要只改这里。
set -euo pipefail
ulimit -c 0
unset TOTK_INPUT_FIFO TOTK_INPUT_SCRIPT TOTK_FS_LOG TOTK_AUDIO_CAPTURE TOTK_INPUT_AUDIT
unset DM_NVN_TSV DM_NVN_TSV_CALLS DM_NVN_FRAMES DM_NVN_PROF DM_PRESENT_HZ DM_PRESENT_INTERVAL DM_DETCLOCK
unset TOTK_HEADLESS TOTK_SHOT LARECOMP_FNPROF
export XDG_DATA_HOME="$HOME/.local/share/ultratears/test-profiles/v8-opening-20261102"
export TOTK_GYRO=1
# 池内存改用主机可见副本：初始空岛草地的 A/B/A 是 20.93→29.67→19.46 FPS，队列提交 API p50 26.63→0.29→30.54 ms
# （docs/linux-pool-copies.md）。环境不支持时运行时自动回退导入并记录原因，不会因此启动失败。
export TOTK_POOL_COPY=1
export SDL_VIDEO_DRIVER=x11 SDL_VIDEODRIVER=x11
exec "$HOME/native-recomp/totk-native/current/run.sh"
