# Linux 构建约定

- 目标为 x86_64 Linux，glibc 2.39+ 和系统 Vulkan 驱动。Steam Deck 使用 Mesa RADV；不随包分发 GPU 驱动、glibc 或 Vulkan loader。
- 版本固定 1.4.3，ExeFS 摘要验证先于生成。读取自己的更新后解密目录；不提供游戏解密、下载或版本猜测。
- `build.py toolchain --work /mnt/totk-build` 先构建工具链镜像，镜像标签由 Dockerfile、依赖脚本和 Python 锁文件内容共同决定。重用 Docker 的正常构建缓存；需要更新系统安全包时自行重建镜像并重新验证。
- Clang 18、Linux x86-64-v3；完整游戏构建需要支持 AVX2/FMA 的主机。默认 2 个编译任务，单容器 8 GiB 内存，工作目录最少预留 100 GiB。
- 输入只读挂载为 `/input`，源码只读挂载为 `/src`，可写产物只挂载到 `/work`；容器按调用者 UID/GID 运行，不需要特权容器或 Docker socket 挂入构建容器。
- `.NET` 首次运行、命名互斥锁、NuGet 配置与临时文件都限定在工作目录的 `.build-runtime/` 和 `cache/` 内，原有依赖缓存继续复用。不重定义 `HOME`，不要求容器 UID 有系统账户或可写的用户主目录。运行目录只允许属主访问；链接、非属主或可由其他用户写入的状态目录会被拒绝，不改写现有权限。
- `--stage code` 不代表资源已通过；`runtime` 不读取游戏输入。只有全部阶段通过才能得到 `package/`，失败会保留对应日志与未发布暂存目录。
- `package/run.sh --verify` 完整验证可能需要读取数十 GiB；普通启动只复核可执行代码和依赖摘要及资源长度。
- 错误输入、缺少字体、损坏影片、生成/编译失败必须中止，不能用旧对象或空资源补位。任何不完整或损坏转储均不能纳入完整包通过记录。
- 只分享源码时，使用 `python3 tools/export_source.py --output ../totk-native-source.tar.gz`；不要归档工作目录或个人游戏包。

此处的构建命令是原生 Linux 路线。`docs/upstream/` 中保留的 Windows/macOS 用法和历史状态不作为本项目 Linux 交付的验证结论。
