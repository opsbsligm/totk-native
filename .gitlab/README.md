# CI 执行约定

公开构建和扫描使用隔离的 Linux x86_64 Docker runner（标签 `native-games`）。游戏转储与私有生成代码不进入 runner。

管理员在 runner 的 `environment` 中设置 `NATIVE_SECURITY_PREFIX=registry.gitlab.com/security-products`；CI 固定完整的源站 manifest 摘要。若使用离线镜像缓存，前缀可指向缓存，但缓存必须提供相同 manifest 字节与所有原始 blob 摘要，不能用可变 tag 或镜像配置 ID 替代。`docker save/load` 不一定保留仓库摘要引用，缓存需用 OCI Registry 拉取验证。

单 job 使用 UID/GID 1001、禁特权、丢弃全部 capabilities、禁 services 与自定义挂载、2CPU/3GiB、按 job 隔离网络；runner 仅绑定本项目及配对项目。镜像预缓存完成后使用 `pull_policy=never`。扫描器镜像必须与 YAML 固定摘要一致；本地工具链按 `build.py` 内容标签构建、校验 AV 解码，并按 `.gitlab/toolchain.env` 的归档 SHA 上传本项目 generic packages。

`native-build` 从带清单的源码包解压，重新编译公共运行时，生成真实编译数据库与系统 SDK。C++ 扫描使用分析器本身的 Clang 内建头，必须成功处理全部编译单元；扫描器退出0但部分解析失败仍会使 job 失败。容器扫描先核对归档 SHA，再有界解压一次为 seekable tar，保留语言漏洞及 SBOM 扫描。

普通用户按根 README 的 `build.py` 流程编译，不需要配置这些 CI 管理项。
