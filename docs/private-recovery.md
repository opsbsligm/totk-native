# 个人恢复

源码与私有加密恢复包分别保存。源码可以分享；恢复包保存在本项目私有 Generic Packages 的 `private-recovery` 中，包含自己提供的游戏转储和 key，不进入 Git 历史或公共 CI。

重置 Deck 前，保留 Mac/NAS 上的 age identity 文件；解密密钥不能只保存在将被重置的 Deck，也不上传到 GitLab。`age` 1.2.1 及以上是恢复工具的前置依赖。密钥路径由使用者传入，不写进仓库。GitLab 下载令牌用仅当前账户可读的文件。

在有 Docker 和 160 GiB 以上可用空间的 x86_64 Linux 主机执行：

```sh
python3 tools/rebuild_private.py --version YOUR_PACKAGE_VERSION \
  --token-file /private/gitlab-token --identity /private/age-identity.txt \
  --work /mnt/native-restore
```

该命令下载校验全部加密分片、完成 age 认证后解包、逐文件核对加密清单，再检查和构建。输出目录必须是新目录，避免覆盖已有安装或存档。工作目录需要容纳加密分片、解密暂存、恢复文件和构建产物；大文件直接使用数据盘/NAS，不能放 Mac 的 tmp。

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

完整构建输入版本名为 `20261105-totk143-complete`。恢复工具会核对所有组件和缺项；版本只有在发布完成且全部回读验证通过后才能用于重建。存档、Steam入口和图片单独保存为个人配置快照，恢复构建不会覆盖现有存档。
