# 个人恢复

源码与私有加密恢复包分别保存。源码可以分享；恢复包保存在本项目私有 Generic Packages 的 `private-recovery` 中，包含自己提供的游戏转储和 key，不进入 Git 历史或公共 CI。

重置 Deck 前，保留 Mac/NAS 上的 age identity 文件；解密密钥不能只保存在将被重置的 Deck，也不上传到 GitLab。`age` 1.2.1 及以上是恢复工具的前置依赖。密钥路径由使用者传入，不写进仓库。GitLab 下载令牌用仅当前账户可读的文件。

在有 Docker 和 160 GiB 以上可用空间的 x86_64 Linux 主机执行：

```sh
python3 tools/rebuild_private.py --version YOUR_PACKAGE_VERSION \
  --token-file /private/gitlab-token --identity /private/age-identity.txt \
  --work /mnt/native-restore
```

该命令下载校验全部加密分片、完成 age 认证后解包、逐文件核对加密清单，再检查和构建。完整运行包会识别恢复目录中的 `run.sh`、`dump/run.sh` 或 `runtime/run.sh`，直接原地校验并输出入口，不再重新构建；多个入口或入口不可执行时会停止。只有不含上述入口的构建输入包（`dump/`）才走 doctor/build 路径。输出目录必须是新目录，避免覆盖已有安装或存档。工作目录需要容纳加密分片、解密暂存、恢复文件和构建产物；大文件直接使用数据盘/NAS，不能放 Mac 的 tmp。

密文分片可放在另一块磁盘、USB盘或已挂载的 NAS，共享盘不需要保存 Unix 可执行权限。使用新目录指定 `--encrypted-work`；认证后的临时归档、还原文件、运行入口和构建输出仍留在 `--work` 所在的 Linux 文件系统：

```sh
python3 tools/rebuild_private.py --version YOUR_PACKAGE_VERSION \
  --token-file /private/gitlab-token --identity /private/age-identity.txt \
  --work /mnt/linux-work/native-restore \
  --encrypted-work /mnt/encrypted-disk/native-cipher
```

两处目录均须是新目录，不能相互包含、放入源码目录、经过符号链接或包含 `..` 路径段。schema 2 集合的全部密文组件也使用独立目录。令牌和 age identity 仍由原私有路径读取，不复制到共享盘；解密认证、摘要和入口权限检查保持一致。只有位于不同文件系统时才会分摊实际空间峰值，同盘不同目录不会增加可用空间。下载前仍核对分片总量及空间，还原工作盘的既有容量门禁保留；命令结束后目录供用户检查与使用，不自动删除。

备份创建示例：

```sh
python3 tools/recovery.py seal --label MY_GAME_VERSION \
  --include dump=/mnt/my-dump --include keys=/private/my-keys \
  --recipients /private/age-recipients.txt --destination /mnt/sealed-bundle
python3 tools/recovery_gitlab.py publish --url https://gitlab.example.com:8445 \
  --project 20 --version MY_PACKAGE_VERSION --token-file /private/gitlab-token \
  --bundle /mnt/sealed-bundle
```

`seal` 只读取输入。输入变化、符号链接或非普通文件会被拒绝；加密清单包含逐文件摘要。发布会回读每个分片，下载会再次核对摘要，恢复最后核对加密清单。部分备份必须通过 `--missing` 明示缺项；一键重建遇到缺项会停止，不能把不完整资源当成可玩包。

新建单包使用 schema 3，执行权限与内容摘要一起写入 age 认证的加密清单。入口和程序只恢复为属主可执行的 `0700`，普通文件为 `0600`；组、其他用户及特殊权限均不保留。恢复先完成全部认证和内容校验，再设置权限并原子安装。非法权限、内外格式不一致或未知格式会拒绝安装。schema 2 继续表示由 base/fonts/romfs 组成的恢复集合。

根目录的 `recovery-receipt.json` 为恢复工具保留，归档不能占用该路径，避免生成回执时覆盖已认证成员。

旧 schema 1 可以继续还原文件，文件权限保持 `0600`。旧包没有记录可执行属性，不能把摘要校验通过当成运行入口已经恢复。便携运行包应使用新版工具重新封装；恢复完成后可直接验证入口：

```sh
python3 tools/recovery.py restore --bundle /mnt/my-runtime-bundle \
  --identity /private/age-identity.txt --destination /mnt/restored-runtime
/mnt/restored-runtime/runtime/run.sh --verify
```

完整构建输入版本名为 `20261105-totk143-complete`。恢复工具会核对所有组件和缺项；版本只有在发布完成且全部回读验证通过后才能用于重建。存档、Steam入口和图片单独保存为个人配置快照，恢复构建不会覆盖现有存档。
