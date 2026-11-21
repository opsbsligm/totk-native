# totk-native


> **版权与商标**：*The Legend of Zelda: Tears of the Kingdom* © Nintendo。本仓为个人源码工程（fan project），未与任天堂关联、获其认可或赞助；*Nintendo Switch* 与 *The Legend of Zelda* 为任天堂注册商标，仅用于描述兼容性对象。仓库内官方宣传图见 [NINTENDO-ART-NOTICE.md](docs/NINTENDO-ART-NOTICE.md)；游戏代码、密钥与固件由用户从自有卡带提供，本仓不含。

《王国之泪》1.4.3 的独立 Linux / Steam Deck 原生源码工程。源码、构建工具和版本检查均在本仓库；不依赖旧 `nativedeck` 工作区，也不需要既有游戏二进制或对象文件。

## 构建与运行

需要 x86_64 Linux、Python 3.11+、Docker（含 Buildx / BuildKit）、至少 100 GiB 可用空间。默认最多使用 2 核和 8 GiB 内存；首次工具链构建需要访问官方依赖源。建议在 Linux 电脑或 NAS 上构建，再复制运行包到 Deck；运行包在 Deck 上无需 Docker。所有构建依赖装在容器里。

先准备自己提供的、已解密且应用 1.4.3 更新的目录：`exefs/`、`romfs/`。`fonts/`：自行提取的 6 个系统共享字体 BFTTF，名称见 `src/host/shared_font.c`。支持解包 RomFS；转换后的输入格式见构建文档。 不接受其他版本混用，公开源码包不含游戏、密钥、系统字体、存档或生成的游戏代码；自有数据可以保存为项目私有的加密恢复制品，见 [个人恢复](docs/private-recovery.md)。

```sh
git clone https://gitlab.example.com:8445/codex/totk-native.git
cd totk-native
python3 build.py doctor --dump /mnt/my-dump --work /mnt/totk-build
python3 build.py build --dump /mnt/my-dump --work /mnt/totk-build
/mnt/totk-build/package/run.sh --verify
/mnt/totk-build/package/run.sh
```

成功后 `package/` 是个人完整运行目录，复制到 Steam Deck 后用 `tools/deploy_package.py` 装成一次发布，再由 `docs/deck-grid/` 建出库条目和封面海报；两步的做法与幂等语义见 [构建约定](docs/build.md)。重启 Steam 后可在掌机模式打开。控制器使用 Steam Input 的普通游戏手柄布局。无需启用 Proton。

构建分为代码生成与编译、资源转换、打包；可用 `--stage code`、`--stage assets`、`--stage package` 分段诊断。输出与游戏输入必须在仓外且互不重叠；构建日志在工作目录 `logs/`。已有包不会被静默覆盖。

## 运行状态

默认 60 帧上限，使用已校验的 18 个指令转换和实时时钟；所有生成游戏块默认禁用 Clang 18 的 CodeGenPrepare，保留宿主优化。帧上限不是稳定帧率承诺。

运行器校验程序、ExeFS 模块和依赖摘要、检查资源尺寸，`--verify` 校验全部文件内容。启动前对现有存档做内容去重、逐文件校验和原子快照备份，源文件变化则中止。存档位于 XDG 用户数据目录，缓存单独保存在 XDG 缓存目录；两个游戏互不覆盖。六轴方向、实体按键、不同机器上的游戏运行和性能由实际玩家验收；`hardware_validated=false` 针对本仓本次重建产物。

## 开发与分享

`src/` 或 `runtime/` 是生产运行时，`tools/` 是版本校验与生成/构建工具，`packaging/` 是运行入口，`tests/` 是公共回归测试。历史上游文档位于 `docs/upstream/`，本 README 是 Linux 发行入口。

```sh
python3 build.py runtime --work /mnt/totk-public-check
```

这个命令编译公共运行时，CI 也执行它；它不等于完整游戏构建。GitLab 的 MR 流程要求测试、安全扫描和指定审查者通过后合并。游戏资源不进入 CI。分享源码请克隆本仓库，或用 `python3 tools/export_source.py --output /mnt/totk-source.tar.gz` 导出含校验清单的源码包；解压后无需 `.git` 即可构建。个人生成的 `package/` 包含游戏派生内容，与可分享源码包分开。

验证范围与已知限制见 [docs/validation.md](docs/validation.md)。

依赖与许可见 [NOTICE.md](NOTICE.md)、[UPSTREAM.json](UPSTREAM.json) 和 [docs/build.md](docs/build.md)。

## 掌机应用控制

点击屏幕边缘的“设置”入口打开可折叠的边缘控制栏；应用菜单用 Deck A 确认、B 返回，游戏玩法映射保持不变。原生 IMU、已接通的画面选项、金手指导入边界和验证状态见 [应用控制](docs/application-controls.md)。固定版本游戏菜单也使用物理 A 确认、B 取消；已验证的软件范围与实机验收边界见 [菜单输入](docs/menu-confirm.md)。

维护者重新生成按键图示：安装 `.gitlab/art/pipcompile.lock.txt` 中带哈希的开发依赖后执行 `python3 tools/draw_deck_art.py`。普通编译使用已提交的图示，不依赖这些绘图包；它们也纳入依赖扫描。

控制栏新增 Amiibo 标签库与版本绑定 Atmosphère 数据金手指；画面设置及支持边界见 [扩展功能说明](docs/feature5.md)。
