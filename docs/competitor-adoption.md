# 竞品吸收差距矩阵（王国之泪）

更新：2026-11-10。来源：竞品调研侧对话首轮结论（参考件留存 `/private/tmp/nativedeck-experience-20261105/refs/`）。

本矩阵是 97 项验收矩阵（18+63+16）**之外**的独立子矩阵，共 5 项竞品吸收能力，避免污染原 97 项口径。每项含：上游证据（本仓源码静态核验）、当前状态、吸收方案、Deck 验收标准。`hardware_validated` 一律以 Deck 实跑截图 + 配置读回为准，不拿组件通过冒充游戏验收。

## 现状锚点

- 本仓上游为 UltraTears（1.4.3，`UPSTREAM.json`），与 BOTW 上游 Savage Wind 不同源。UltraTears 的 Deck 构建路径（sigma/totk-recomp）提供 `tools/linux/warmup.sh`（首启动 shader 预热，按 A 立即进游戏、其余后台编译），本仓当前**未见等价 warmup**。
- 本仓控制栏（`src/host/control_bar.cpp`）画面页已有：帧率上限（30/40/45/60/90/120，`control_bar.cpp:340`）、输出尺寸、上采样（双线性/FSR1 + 锐化，`src/vk/fsr.c`）、原生陀螺仪；抗锯齿当前显示"使用游戏默认 / 目前不可用"（`control_bar.cpp:360`）。
- 本仓无 FOV 滑块、无阴影分辨率档位、各向异性后端有（`src/gfx/vkb_draw.c:387` `maxAnisotropy` 封顶 16x）但**未暴露到控制栏**；无 144 档；无 F10 性能浮层（`perfmon` 无对应）；无 mods 系统。
- 本仓 FPS 档位 `{"30","40","45","60","90","120"}`，无 144。
- 本仓无 romfs overlay quickmenu/gameover 修复；30 锁已解（`TOTK_FPS60/REALTIME`），60 帧下快速菜单/游戏结束表现**未逐项核对**。

## 竞品吸收子矩阵（5 项）

| # | 能力 | 当前状态（静态核验） | 吸收方案 | Deck 验收标准 | hardware_validated |
|---|------|--------------------|---------|-------------|--------------------|
| CA1 | shader 后台预热（不阻塞首入场景） | 本仓无等价 warmup（上游 sigma/totk-recomp 有 `tools/linux/warmup.sh`，本仓未接入）；首入新场景 shader 即时编译会卡顿 | 移植 sigma/totk-recomp warmup：首启动出现预热屏，按 A 立即进游戏、shader 编译后台继续（对齐"后台不阻塞+覆盖全"），治 Deck 首入场景卡顿 | Deck 实跑：冷缓存首入新场景，截图+present 时序对比预热前后；确认无首入场景卡顿尖峰（p50 回落到基线） | false |
| CA2 | >30fps 衍生界面 bug 核查（快速菜单/游戏结束） | 无 romfs overlay quickmenu/gameover 修复；30 锁已解、默认 60，快速菜单/游戏结束在 60 帧下的表现**未逐项核对** | 对照 sigma/totk-recomp 的 `make_quickmenu_fix.py`/`make_gameover_fix.py` 逐项核对：快速菜单（方向选择、光标）、游戏结束画面在 60 帧下是否仍有未修 bug；有则同法 romfs overlay 修复 | Deck 实跑 60 帧：快速菜单开合/选择、死亡游戏结束各截图；确认无光标漂移/选项错位/时序错乱；配置读回 60 帧 | false |
| CA3 | 画面页吸收：FOV 滑块 + 阴影分辨率 + 各向异性 16x | 各向异性已暴露（本分支）：控制栏画面页 关闭/2x/4x/8x/16x，覆盖线性放大+mipmap 过滤+有 mip 范围+非深度比较的采样器，持久化 `aniso=` 字段；FOV 与阴影分辨率档位仍待接后端（见下） | ① 把已有各向异性后端暴露进控制栏画面页（2x–16x）；② 新增 FOV 滑块（70%–150%）与阴影分辨率档位（896→8192），若后端缺失需接 NVN/UBO 对应字段；三项触屏可调 | Deck 实跑：控制栏画面页出现三项并可调；FOV 150% vs 100% 截图对比视角变化；阴影 8192 vs 默认截图对比锐度；各向异性 16x 截图对比远景地面清晰度；配置读回 | false |
| CA4 | mods 系统（RomFS mods + ExeFS 代码补丁 + HD 贴图包） | 无 mods 目录约定、无 `.ips`/`.pchtxt` 自动重编译、无贴图堆自动扩容 | **TOTK 优先**：移植 valentderah/totk-pc-recomp 路线——`mods/<mod>/` 放 RomFS 覆盖；`.ips`/`.pchtxt` ExeFS 代码补丁触发游戏自重编译；HD 贴图包让贴图堆按包请求自动扩容（参考其 4K 包实测 1.4.3/1.2.1），让"分享出去别人编译即用"升级为"可挂 mod" | Deck 实跑：挂一个 RomFS mod 确认生效截图；挂一个 `.ips` 代码补丁确认重编译+生效；HD 贴图包确认贴图堆扩容无 OOM；配置/菜单读回 | false |
| CA5 | 144fps 实验档 + 性能浮层 | 已实现（本分支）：帧率档含 144 实验档；性能浮层 Off/帧率/完整（帧率/平均与峰值帧时/整机 CPU/内存），控制栏触屏开关、配置持久化（`perf=` 字段）；完整档仅整机指标，Deck 无 GPU 计数器（文案已标注） | ① FPS 档追加 144 实验值（Deck 默认 60，144 标注实验、仅高刷外接有效）；② 移植 valentderah 同款 F10 性能浮层（帧率/帧时间/机器负载与温度），并暴露进控制栏触屏入口 | Deck 实跑：控制栏可调性能浮层（截图显示帧率/帧时间）；144 档配置读回（Deck 60Hz 屏下 144 仅标注实验、不强制生效） | false |

## 明确不做（记入口径，避免反复讨论）

- **DLSS**：仅 RTX 有用，Deck（Van Gogh/AMD）无 → "PC 端有价值 / Deck 暂缓"，不做。
- **HDR10**：Deck 屏幕不支持 HDR10 输出 → "PC 端有价值 / Deck 暂缓"，不做。

## 执行顺序与依赖

1. **CA1**（shader 后台预热，TOTK 缺 warmup 最直接，先做）。
2. **CA2**（核对 >30fps 界面 bug，可能产生 romfs overlay 修复）。
3. **CA3**（FOV/阴影/各向异性，各向异性为暴露、FOV/阴影需确认后端）。
4. **CA5**（144 实验档 + 性能浮层，小活）。
5. **CA4**（mods 系统，TOTK 优先于 BOTW，但本项量大，排批次内靠后）。

单项单 MR，不混。每项走 codex 开发 → liguangming 精确 SHA 审查 → 必要修复 → 当前 SHA 完整 CI/安全扫描 → 合并 → 主分支 CI → 原子部署 → 隔离存档遥操回归。

优先级让位于用户手测反馈：若用户测出实体问题先修问题。

> 静态核验基于当前 main（`afb899d`）源码；`hardware_validated=false` 项一律待 Deck 实机补齐。
