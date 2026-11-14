# RomFS mods（Linux / Steam Deck）

把自己的资源文件放入 `${XDG_DATA_HOME:-~/.local/share}/totk-native/mods/<名称>/romfs/`，保持游戏内相对路径。例如 `mods/01-textures/romfs/Texture/example.bntx`。重新启动游戏后生效；游戏原包与存档不改写。

多个 mod 按目录名的字节顺序加载，同一路径由后面的名称覆盖。目录名以点开头时停用。支持替换已有文件和添加新文件；文件大小与读取内容来自真实覆盖文件。缺失文件回退原 RomFS，非法路径、符号链接、非普通资源文件或不可读覆盖文件会返回错误，不静默读取其他文件。最多同时启用 64 个含 `romfs/` 的 mod；启动时记录实际数量，`TOTK_FS_LOG=1` 可记录实际命中的资源路径。运行时不递归扫描资源树，目录描述符仅保留到游戏进程结束。

内置六项 Deck 图示/布局资源优先，以保持按键提示一致；使用 mod 替换这些路径前需要显式关闭 `TOTK_STEAMDECK_UI`。没有 mod 时沿用原文件路径。

当前 RomFS 已接入 Linux 文件读取、大小与类型查询；目录枚举继续沿用现有不支持行为。静态 ExeFS 代码补丁接入下述构建链；HD 贴图包的 guest 堆扩容及控制栏管理仍待实现。组件测试不能代替游戏内贴图、内存和性能验收，`hardware_validated=false`。


## 静态 ExeFS 代码补丁（CA4）

```text
/private/totk-mods/
  10-first/exefs/<完整 NSO Build ID>.ips
  20-later/exefs/可读名称.pchtxt
  .disabled/exefs/暂不启用.pchtxt
```

```sh
python3 build.py build --dump /mnt/private/totk-1.4.3 \
  --work /mnt/build/totk --code-mods /mnt/private/totk-mods
```

原始 dump 与 Mod 根目录分别只读挂载；源码、输入、Mod 和工作目录分离。`--code-mods` 仅用于 Linux 私有游戏构建，不用于公共 runtime 归档。没有该选项时保持原构建路径；帧时序、DRS、按键及用户配置的既有默认值不改变。

构建先以受管 profile 核对全部原始 1.4.3 模块，再严格解析标准 IPS、IPS32 和 PCHTXT。完整 Build ID 绑定模块，IPS 文件名或 PCHTXT 首条指令必须匹配，允许省略完整的尾部零字节，不按任意短前缀猜测版本。支持零字节、RLE、enabled/disabled、offset_shift 和 UTF-8 字符串；点号目录停用，按目录／文件 UTF-8 字节顺序处理，后者覆盖前者。错版本、截断、非法范围、未知格式、符号链接／设备／FIFO 和预算超限明确失败。

补丁先完整校验，再进入真实 AOT；不是运行时往已编译的宿主指令地址写数据。NSO 头、段间空洞、BSS、MOD0／dynamic／符号／异常表、重定位目标、由宿主 HLE 接管的函数、既有 DRS 替换点及18处原生帧时序校验点均受保护。HLE 名单用同一 Linux 构建生成的实际编译命令，经编译器预处理后读取注册表，包含包装宏和条件分支；无法完整识别就停止，不用字符串搜索猜测。

准备好的模块只在私有同卷临时目录供生成和 shader 导出使用，成功或失败都清理，不为每个源码 SHA 保留整套 ExeFS 副本。生成成功后仅留下 `data/generated/static-mods.json`，其中绑定原始模块、活动补丁、有效模块及宿主 HLE 名单的摘要。生成清单、代码和资源阶段回执、成功 ELF 的构建记录均绑定同一组补丁；打包再次核原始输入、补丁、生成文件、二进制及两阶段回执，并复制与 AOT 相同的补丁后模块及 `provenance/static-mods.json`。补丁或任何阶段输入变化必须重新生成／编译，不会用新代码搭配旧 shader 资源。单独构建 assets 时须先有同组补丁的有效 code 生成结果。

移除代码 Mod 后，使用原始 dump 重新构建并省略 `--code-mods`；旧 Mod 生成清单不能当默认输入复用。仅删除掌机上的 IPS/PCHTXT 不会还原已编译代码。工作盘既有容量门禁保留，物理宿主／快照余量仍须另核；这不是已部署的全局配额。失败打包只清理本次创建且身份未变的 `package.new`，原始输入和成功构建输出保留。

## CA4 后续验收

静态代码补丁、运行时 RomFS 覆盖与 HD 堆策略分别验收。HD 阶段须以本作 Build ID 和实际分配链为依据，绑定游戏堆请求、根堆、GPU资源池及预算表，评估 Steam Deck 共享内存、回退与移除行为；不能照搬 BOTW SDK7 的偏移／容量，也不把 host 告警阈值当堆扩容。控制栏管理只在后端和持久化行为验证后开放。

## HD 资源与内存设计（2026-11-15）

以下是确定的实现约束，尚未开放 HD 开关，不代表当前运行包已完成扩容。

固定核对的 [上游 resolution.c](https://github.com/valentderah/totk-pc-recomp/blob/0ae47a578285cde080642c9e6c40316c99171ef1/runtime/resolution.c) 按输出／场景尺寸和阴影计算增量，改写 `System/HeapSize/Product.Nin_NX_NVN.HeapDef.byml.zs` 中的 `DynamicTextureAllocatorMem` 与父级 `Graphics`，并由 [memory.c](https://github.com/valentderah/totk-pc-recomp/blob/0ae47a578285cde080642c9e6c40316c99171ef1/runtime/memory.c) 同步增加应用内存池。这个路径证明的是渲染目标扩容，不能直接当作任意 HD 贴图包已支持自动扩容。上游 [Mods 说明](https://github.com/valentderah/totk-pc-recomp/blob/0ae47a578285cde080642c9e6c40316c99171ef1/docs/mods.md) 还把资源大小表合并与包内资源列为独立能力。

本作当前 `src/host/svc.c` 的 `GetInfo`、`SetHeapSize` 和 alias 映射仍使用固定应用内存池。HD 接入按下列四层一起完成：

| 层 | 必须绑定或修改的对象 | 验收边界 |
|---|---|---|
| 资源分配 | 最终覆盖集合、实际加载格式、完整 mip 链、解压后资源与 Pack 内成员；按资源规则更新 RESTBL | 资源长度不等于所需内存，不能只改压缩文件长度；未识别格式或包内成员须拒绝整组 HD 激活 |
| 游戏堆 | 受检原始 HeapDef、实际使用该资源的叶子堆与父堆、根堆的创建／保留请求 | 不能假定 `DynamicTextureAllocatorMem` 是所有贴图的通用堆；每个变化须有本版本实际分配链依据 |
| 客体总账 | `GetInfo` 总量／已用量、`SetHeapSize`、alias 的新映射／释放、模块镜像 | 同一把内存锁下核总量与溢出；父子堆的同一份增量只在总池记一次；实际请求和返回必须读回 |
| 宿主／GPU | Linux 可用内存与 cgroup 上限、Vulkan heap budget、纹理／影子副本与暂存峰值 | APU 共享内存不把 CPU 和 GPU 的余量简单相加；没有实际预算查询就不承诺扩容能力 |

HD 启用事务在首次加载游戏资源之前决定，输入为受管版本指纹、原始表、活动 Mod 的完整资源摘要与经审查的预算配置。输出仅为私有资源覆盖、预算回执及其内容摘要，原始 dump 不变。所有相互依赖的表与预算准备成功后整组激活；失败保留原运行包和原始资源，明确显示整组 HD 未启用，不能让新贴图配旧分配表。普通 RomFS Mod 的既有路径与优先级不借机调整。

RESTBL 采用最终胜出的资源集合计算分配需求，结合受检原表及兼容的 Mod 表，仅按正确资源规则增加条目；不得按名称猜大小，也不无条件把所有表值取最大就宣称安全。压缩字典、BYML 类型／整数范围、哈希冲突和资源缺失均为显式失败。原始表／Mod 集合／预算任一改变，都使旧回执失效。所需资源超过受测预算时拒绝 HD 激活，不自动申请任意多内存，不降画质冒充已开启。

更改 HD 预算需要重启，不在游戏中缩小已经使用的堆。准备期失败可完整回退；运行中分配失败只报告并禁用下一次激活，不能声称可原地撤销已分配的游戏状态。移除 Mod 后重新启动，恢复原表、原池和原配置；移除前后均保留存档。触屏控制栏只在实际后端、状态读回与持久化均验证后开放管理入口。

实现按三步推进：①原始 HeapDef／RESTBL 的只读解析、最终资源清单与事务输出；②本版本根堆和资源分配链、客体总账与 GPU 预算联动；③生成／打包／密封恢复绑定预算摘要，再做 Deck 实跑。原创夹具须覆盖父子增量、单位／整数溢出、别名已用量、受限预算、字典与嵌套资源、失败回退及停用重启；真实 HD 包另验贴图正确性、移动镜头加载、场景切换、峰值内存、帧时间和长时间稳定性。组件测试与整机验收分别记录，`hardware_validated=false`。

当前代码需经完整 CI／安全审查、私有整游戏重建、精确包验证及 Deck 游戏内回归后才能发布。原创微型 NSO／编译夹具、真实游戏输入、画面效果和长时间稳定性分开记录，不以组件通过宣称整机完成。
