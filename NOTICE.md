# 来源与许可

上游仓库、精确提交、游戏版本及原移植提交记录在 `UPSTREAM.json`。保留原运行时和第三方目录中的版权、许可证及修改说明；本仓新增 Linux 工程化代码按根目录 `LICENSE` 发布。

上游各组件依其自身许可证发布，根许可证不替代第三方许可证。王国之泪的帧时序适配来源包括 MacNativeGames 的 MIT 实现；许可证保存在其独立工程 `third_party/LICENSE-MacNativeGames`。旷野之息包含 SavageWindRecomp / LASRecomp 的 MIT 运行时、AMD FidelityFX 的 MIT 组件、SDL / FFmpeg / shaderc 和字体各自的许可证。

Linux 依赖源、版本和下载摘要在 `tools/build_deps.sh`；Python 依赖的精确版本与 wheel 摘要在 `requirements-build.lock`。Dockerfile 固定基础镜像摘要，Ubuntu 系统包从该发行版的安全更新源安装；这保证源码输入与构建流程可追溯，不承诺每次系统包更新后仍逐字节生成相同二进制。

个人游戏包附带当前精确 Git 提交的 `source.tar.gz` 和来源说明。该源码归档不包含游戏生成代码、ROM、系统字体或其他私有输入。构建目录和个人游戏包不提交到本仓，不作为 CI 制品发布。
