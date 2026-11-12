# RomFS mods（Linux / Steam Deck）

把自己的资源文件放入 `${XDG_DATA_HOME:-~/.local/share}/totk-native/mods/<名称>/romfs/`，保持游戏内相对路径。例如 `mods/01-textures/romfs/Texture/example.bntx`。重新启动游戏后生效；游戏原包与存档不改写。

多个 mod 按目录名的字节顺序加载，同一路径由后面的名称覆盖。目录名以点开头时停用。支持替换已有文件和添加新文件；文件大小与读取内容来自真实覆盖文件。缺失文件回退原 RomFS，非法路径、符号链接、非普通资源文件或不可读覆盖文件会返回错误，不静默读取其他文件。最多同时启用 64 个含 `romfs/` 的 mod；启动时记录实际数量，`TOTK_FS_LOG=1` 可记录实际命中的资源路径。运行时不递归扫描资源树，目录描述符仅保留到游戏进程结束。

内置六项 Deck 图示/布局资源优先，以保持按键提示一致；使用 mod 替换这些路径前需要显式关闭 `TOTK_STEAMDECK_UI`。没有 mod 时沿用原文件路径。

当前已接入 Linux 文件读取、大小与类型查询；RomFS 目录枚举继续沿用现有不支持行为。ExeFS IPS/PCHTXT 重编译、HD 贴图包的 guest 堆扩容及控制栏管理仍待实现。组件测试不能代替游戏内贴图、内存和性能验收，`hardware_validated=false`。
