# Linux 构建约定

- 目标为 x86_64 Linux，glibc 2.39+ 和系统 Vulkan 驱动。Steam Deck 使用 Mesa RADV；不随包分发 GPU 驱动、glibc 或 Vulkan loader。
- 版本固定 1.4.3，ExeFS 摘要验证先于生成。读取自己的更新后解密目录；不提供游戏解密、下载或版本猜测。
- `build.py toolchain --work /mnt/totk-build` 先构建工具链镜像，镜像标签由 Dockerfile、依赖脚本和 Python 锁文件内容共同决定。重用 Docker 的正常构建缓存；需要更新系统安全包时自行重建镜像并重新验证。
- Clang 18、Linux x86-64-v3；完整游戏构建需要支持 AVX2/FMA 的主机。默认 2 个编译任务，单容器 8 GiB 内存，工作目录最少预留 100 GiB。
- 输入只读挂载为 `/input`，源码只读挂载为 `/src`，可写产物只挂载到 `/work`；容器按调用者 UID/GID 运行，不需要特权容器或 Docker socket 挂入构建容器。
- `pipeline.py build` 默认读取 `/input`，掌机上直接重构建时用 `--dump <目录>` 指向同一份已核验输入（`exefs/`、`fonts/`、打包后的 `romfs/`）；已安装发布的 `data/` 就满足该结构。输入身份仍按 1.4.3 摘要逐项核验，参数只换路径，不放宽校验。
- `.NET` 首次运行、命名互斥锁、NuGet 配置与临时文件都限定在工作目录的 `.build-runtime/` 和 `cache/` 内，原有依赖缓存继续复用。不重定义 `HOME`，不要求容器 UID 有系统账户或可写的用户主目录。运行目录只允许属主访问；链接、非属主或可由其他用户写入的状态目录会被拒绝，不改写现有权限。
- `--stage code` 不代表资源已通过；`runtime` 不读取游戏输入。只有全部阶段通过才能得到 `package/`，失败会保留对应日志与未发布暂存目录。
- `package/run.sh --verify` 完整验证可能需要读取数十 GiB；普通启动只复核可执行代码和依赖摘要及资源长度。
- 错误输入、缺少字体、损坏影片、生成/编译失败必须中止，不能用旧对象或空资源补位。任何不完整或损坏转储均不能纳入完整包通过记录。
- 只分享源码时，使用 `python3 tools/export_source.py --output ../totk-native-source.tar.gz`；不要归档工作目录或个人游戏包。

此处的构建命令是原生 Linux 路线。`docs/upstream/` 中保留的 Windows/macOS 用法和历史状态不作为本项目 Linux 交付的验证结论。

## 装到掌机

`pipeline.py build` 产出的 `package/` 由 `tools/deploy_package.py` 安装成掌机上的一次发布：

    python3 tools/deploy_package.py --package /work/package --root ~/native-recomp/totk-native

- 先把包内每个文件与 `bundle.json` 逐项比对（名称、长度、SHA-256），任一不符直接拒绝，不动已装内容，也不覆盖 `releases/` 里内容不同的同名发布。
- 与被替换发布内容相同的资源（romfs、BC7 贴图、着色器包等）按硬链接复用，一次重建不会在 `/home` 上再放一份私有游戏树；真正落盘的只有可执行文件和清单。
- 全部文件到位后一次替换 `current` 符号链接：玩家要么看到完整的新发布，要么完全看不到变化。
- 被替换的发布保留在 `releases/` 并记入 `previous`；出问题用 `--rollback` 换回，再执行一次换回来。

掌机布局语义不变：仍是 `releases/<id>` 加 `current`，launcher 不需要跟着改。

## 库条目与九宫格图

发布装好后，掌机库里还需要一条指向启动器的非 Steam 快捷方式，以及封面、海报和图标。
`docs/deck-grid/` 带着图一起完成这件事，全新 Deck 上不需要任何仓外文件：

    scp -r docs/deck-grid deck@DECK:/tmp/deck-grid-totk
    ssh deck@DECK /tmp/deck-grid-totk/deploy-deck-launcher.sh
    ssh deck@DECK /tmp/deck-grid-totk/deploy-deck-art.sh

`deploy-deck-launcher.sh` 安装 `totk-steam.sh`，`deploy-deck-art.sh` 调用同目录的
`deck-shortcut.py`：它解析二进制 `shortcuts.vdf`，找出本机已有快捷方式的 Steam 账号，
沿用 Steam 已经分配给这个启动器的 appid（第一次安装时用由启动器路径派生的稳定 id），
就地更新这一条，其余快捷方式按原字节重新序列化。九宫格图装到该 appid 下，快捷方式图标
装进 `~/.local/share/Steam/appicons/`。已装过再跑一遍不会改动任何字节；加 `--check`
只报告差异。多账号 Deck 传 `STEAM_ID`。改完在 Steam 里重启一次生效。

四张图不是手工产物：`gen-deck-art.py` 从 `docs/deck-grid/src/` 里的任天堂官方宣传图
按绝对坐标裁切重生成它们，`src/SHA256SUMS` 钉住源图内容。源图入仓是因为官方下载点会
失效（媒体站 CDN 现已 403），只记 URL 就无法在新机器上复现同一批像素。换图或改构图时
改脚本里的裁切框重跑，再执行一次 `deploy-deck-art.sh`：

    python3 docs/deck-grid/gen-deck-art.py
    scp -r docs/deck-grid deck@DECK:/tmp/deck-grid-totk
    ssh deck@DECK /tmp/deck-grid-totk/deploy-deck-art.sh

