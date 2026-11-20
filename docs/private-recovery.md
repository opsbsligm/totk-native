# 个人恢复

源码与私有加密恢复包分别保存。源码可以分享；自己提供的游戏转储、密钥、个人运行包与存档保存在已授权的私有存储中，不进入 Git、公共 CI 或默认发布流程。以下本地恢复命令可直接读取已挂载私有存储上的密文，无须先复制全部分片到执行盘。

重置 Deck 前，保留另一台设备上的 age identity 文件；解密密钥不能只保存在将被重置的 Deck。`age` 1.2.1 及以上是前置依赖，identity 与接收者文件路径由使用者传入，不写进仓库。

`age` 默认从 `PATH` 查找。一台刚重置的 Deck 通常只在项目自有目录里放着 `age`，为此可以把 `NATIVE_AGE` 指向该二进制（绝对路径，或仍按 `PATH` 解析的裸程序名）；版本号门槛不变，也不改变包格式。

已有完整运行包时，在 Linux 执行盘选择一个全新的恢复目录：

```sh
python3 tools/recovery.py restore --bundle /mnt/private-storage/my-runtime-bundle \
  --identity /private/age-identity.txt --destination /mnt/linux-work/restored-runtime \
  --low-peak
/mnt/linux-work/restored-runtime/runtime/run.sh --verify
```

上述入口适用于以 `runtime=` 封装的完整个人包。实际还原路径以加密清单中的组件名为准；`run.sh --verify` 会完整核对包内容，不启动游戏。只有入口及全部数据核验通过后，才将入口添加到 Steam。完整运行包无需 Docker 或重新编译；原始构建输入包仍需经过对应的完整构建流程。

便携包创建示例：

```sh
python3 tools/recovery.py seal --label MY_RUNTIME_VERSION \
  --include runtime=/mnt/personal-package \
  --recipients /private/age-recipients.txt --destination /mnt/private-storage/sealed-runtime \
  --low-peak
```

`seal` 只读取输入。输入变化、符号链接或非普通文件会被拒绝。每次备份前先对照已验证的受控明文清单：相同内容复用现有密文，不因新的源码提交或随机密文重复封装整套游戏。新运行物的密封与保留须另外核验；`--low-peak` 本身不提供增量或去重功能。

低峰值封装将 age 输出直接拆为有界分片，不生成整份 `payload.age`；还原先完整解密认证一遍并丢弃明文，第二遍才在私有暂存目录流式解包。每遍重新核对分片摘要，第二遍 age 成功且全部清单和权限校验通过后才原子安装。任一遍认证、输入变化、输出或清单失败都会拒绝安装并清理本次暂存。此模式与默认模式的 schema 3 格式互相兼容；默认路径仍可使用。

此模式用多一次完整解密读取换取空间。封装或还原阶段新增占用预算各为输入大小加 1 GiB，省去同时存在的完整密文或明文归档；现有输入、已下载分片、后续构建、并发任务及执行盘保留线仍须另计。同盘换目录不会增加可用空间。大文件生成、下载、解包、校验都在容量已核验的执行盘完成，不放日用 Mac 的临时目录。

新建单包使用 schema 3，将执行权限与内容摘要一起写入 age 认证的加密清单。入口和程序恢复为属主可执行的 `0700`，普通文件为 `0600`；组、其他用户与特殊权限不保留。先完成全部认证和内容校验，再设置权限并原子安装。非法权限、内外格式不一致或未知格式会拒绝安装。schema 2 继续表示由 base/fonts/romfs 组成的恢复集合。

根目录的 `recovery-receipt.json` 为恢复工具保留，归档不能占用该路径。旧 schema 1 仍可还原文件，但没有认证过的可执行属性，文件保持 `0600`；摘要通过不能代替入口权限验收。部分备份必须通过 `--missing` 明示缺项，缺项不能算可玩包。

已有专门授权的旧 GitLab 传输流程可继续使用 `rebuild_private.py`。它会识别 `run.sh`、`dump/run.sh` 或 `runtime/run.sh`，直接原地校验完整运行包；多个入口、缺项或入口不可执行都会停止。只有不含这些入口的 `dump/` 构建输入才进入 doctor/build。该兼容工具不代表默认允许发布私有输入、密钥或运行数据。

```sh
python3 tools/rebuild_private.py --url https://gitlab.example.invalid \
  --version YOUR_PACKAGE_VERSION --token-file /private/gitlab-token \
  --identity /private/age-identity.txt --work /mnt/linux-work/native-restore \
  --encrypted-work /mnt/encrypted-disk/native-cipher --low-peak
```

`rebuild_private.py` 必须显式传入此次获准访问的 `--url`，不内置个人服务地址。它仍要求 Linux 工作盘至少 160 GiB 可用；仅从转储重新构建时需要 x86_64 与 Docker，已有完整运行包路径不重编译。`--low-peak` 会传给单包及集合的每个还原组件。密文目录与还原工作目录均须是新目录，不能互相包含、放入源码目录、经过符号链接或包含 `..`。schema 2 的组件也使用独立密文目录；令牌和 identity 不复制到共享盘。

存档、Steam 入口与图片保存在单独的个人配置快照中。本工具不会覆盖已有安装或存档；成功输出仍需使用者按实际设备完成入口、输入、陀螺仪和运行性能验收。

## 已验证到什么程度

- 恢复工具链与另一塞尔达同版本：`tools/recovery.py`、`tools/recovery_gitlab.py` 内容摘要一致，`tests/` 下的恢复与流式恢复用例在 CI 内随每个 SHA 执行。
- 当前保留的包 `20261120-totk-main-81f997f`（`--include dump=… --include keys=…`，明文 27 740 611 060 字节，密封为 38 个分片共 19 980 716 883 字节）已发布到本项目私有 Generic Packages。发布过程把每个分片完整读回一遍（不落第二份磁盘副本），逐分片比对字节数与 SHA-256 后才写 `index.json` 并回读清单。
- 上一版 `20261119-totk-main-f9face0` 另做过一次独立下载核验：全部分片重新计算摘要与尺寸，`bad=0`。核验脚本只读取密文，不改动包内容。
- 同一包在受控 Linux 工位以 `--low-peak` 完整还原过一遍：68 个成员全部就位、无缺项，退出时 `missing=[]`。该演练验证的是解密、分片摘要与加密清单一致，不代表游戏可运行；演练输出已按存储门禁清理。
- 清单本身不含逐成员路径：`index.json` 的 `files` 只是成员计数与缺项列表，逐文件摘要在 age 认证的信封内，只有成功解密才会被核对。因此“还原演练成功”已经是成员级校验，无需另存明文清单。
- 真机未验收：还原出的运行包尚未在 Deck 上跑 `run.sh --verify` 与实际启动；帧率、按键、陀螺仪、控制栏等以玩家实机验收为准，`hardware_validated=false`。
- 存档与个人配置快照的恢复路径未演练，按上面的说明手工保存。
