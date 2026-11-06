# 来源与许可

上游仓库、精确提交、游戏版本及原移植提交记录在 `UPSTREAM.json`。保留原运行时和第三方目录中的版权、许可证及修改说明；本仓新增 Linux 工程化代码按根目录 `LICENSE` 发布。

上游各组件依其自身许可证发布，根许可证不替代第三方许可证。王国之泪的帧时序适配来源包括 MacNativeGames 的 MIT 实现；许可证保存在其独立工程 `third_party/LICENSE-MacNativeGames`。SDL / FFmpeg / shaderc 等依赖各自保留许可。当前掌机图示为项目原创 SVG；旧图示的来源及字体许可历史保留于 `licenses/controller-art/NOTICE.md`。

Linux 依赖源、版本和下载摘要在 `tools/build_deps.sh`；Python 依赖的精确版本与 wheel 摘要在 `requirements-build.lock`。Dockerfile 固定基础镜像摘要，Ubuntu 系统包从该发行版的安全更新源安装；这保证源码输入与构建流程可追溯，不承诺每次系统包更新后仍逐字节生成相同二进制。

个人游戏包附带当前精确 Git 提交的 `source.tar.gz` 和来源说明。该源码归档不包含游戏生成代码、ROM、系统字体或其他私有输入。构建目录和个人游戏包不提交到本仓，不作为 CI 制品发布。

## Application control bar

Dear ImGui sources and Vulkan backend are MIT, copied byte-for-byte from the independently pinned BOTW source snapshot `Revivedx/SavageWindRecomp@4249c880bc6b09ad0207fc3f6e7595346f08d232`. Copyright and license are retained in `third_party/imgui/LICENSE.txt` and packaged as `licenses/dependencies/imgui-LICENSE.txt`. The new original Deck vector drawings and application integration are maintained in this repository.

本项目新增的 sensor-only Deck IMU 读取器、解码器和版本绑定数据补丁模块以 MIT 发布；原生运动的数据格式参考和验证范围见 `docs/native-motion.md`。这不改变其他上游文件的许可证。

## 第五项扩展功能

只读 NFP/NTAG215 ABI 参考 libnx 与 `valentderah/totk-pc-recomp@0ae47a578285cde080642c9e6c40316c99171ef1`。Atmosphère VM 的基础执行代码适配自同一 MIT 项目，保留作者 Valiantsin Dzerakh 的 MIT 许可（`licenses/totk-pc-recomp-MIT.txt`）；本仓新增有界导入、数据/堆权限边界、默认关闭、内核安全拷贝与异常隔离。上游实际实现不能代替本游戏版本与硬件验证。

FSR1 呈现 glue 源于 `kuraeow/ultratears@57bf619e7ef579a0675a4d41d74413ebaca02fb8` 的 GPL 实现（提交号以 third_party/fsr1/UPSTREAM.json 为准）；EASU/RCAS shader 与 AMD headers 为 MIT，声明与原文件保留。新增动态能力回退、部分分配清理、输出视图生命周期与可持久化 UI 设置。

Public virtual-figure identifiers: N3evin/AmiiboAPI@6115745c56ff762ce212ced6fbad9ea195d659b3, Copyright (c) 2017 Nevin Vu, MIT (licenses/AmiiboAPI-MIT.txt). No tag dumps or encrypted application data are bundled.
