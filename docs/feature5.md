# 掌机控制栏与扩展功能

点击屏幕边缘的“设置”入口打开控制栏；A 确认、B 返回，拖动后自动吸附八个边角。画面、控制、Amiibo、金手指分为四页；按钮按触摸操作加大，长页在空白处直接上下拖动，滚动条关闭，列表右缘的细指示条显示位置。拖动标题下方短条后自动吸附八个边角。快捷键不再打开侧栏。游戏世界按键与原生陀螺仪保持既有逻辑。

## Amiibo

内置32个塞尔达系列公开公仔身份（31个可刷，狼林克因需要应用区存档而明确禁用），不需要下载标签文件或key。选择后点“刷入公仔 / 再刷一次”，每次使用系统随机源生成新UID，公仔类型不变。若上一枚已检测或挂载，先通知移除，等游戏下次StartDetection再激活，避免每帧重新触发扫描和连续音效。NFP身份和ModelInfo布局与固定上游逐字节核对一致。

主状态只记录当前身份是否已通过真实 ModelInfo 调用返回给游戏。停止读取、重新检测及卸载不会抹掉这项记录；成功刷入新身份、加载新文件或移开公仔才清零，失败操作保留原记录。挂载或读取标签本身不算身份读取成功。累计调用次数收入默认折叠的“扫描诊断”，不能用上一枚的累计成功冒充本次成功。这仍不是奖励到账证明；游戏内掉落、领取、冷却与保存重载须分别实测。


自有标准 NTAG215 的 540 字节 `.bin` 放入 `$XDG_DATA_HOME/<game>/amiibo/`（未设置时为 `~/.local/share/<game>/amiibo/`），`<game>` 为 `totk-native` 或 `botw-native`。控制栏刷新后选择；进入游戏的 Amiibo 扫描能力后会检测到标签。扫描事件销毁时同步失效缓存，重新扫描在游戏线程重绑；宿主通知不会复活已销毁事件或触发复用后的其他句柄。读完选择“移开标签”，再选下一枚。只支持只读公仔身份；应用区存档、写入、Wolf Link 存档能力未实现。拒绝损坏 UID 校验、错误大小、符号链接及非本人所有文件。仓库不提供标签 dump。

## Atmosphère 金手指

本轮附完整BuildID绑定的可执行常用数据预设，见 [内置数据预设](cheat-presets.md)；默认关闭。

启用后显示本次开启以来的实际执行帧、内核写入、立即读回一致和写后变化次数。条件未触发、等待游戏帧、写入成功、读回变化与故障停止分别显示；不把开关亮起等同于游戏效果已确认。内存写入读回验证仍不能替代实际玩法验收。重新启用会清零本次计数，不沿用旧成功记录。错误原因已汉化。


放到相同游戏的数据目录 `cheats/<BuildID前8字节的16位大写十六进制>.txt`，权限设为 `0600`。控制栏显示准确路径，可重新加载。文件必须匹配实际加载的完整游戏版本。控制栏文件读取与解析由单一后台工作线程执行，不持有逐帧VM锁；导入期间禁止开启旧项，游戏版本变化会丢弃旧导入结果。“全部关闭”可立即停止持续写入。每项（包括 master）默认关闭；不支持的项保留原因并禁用。支持 0–A 的数据/指针/条件/按键/循环指令，内存区域仅 main 与 heap。扩展 C/F 指令及静态重编译机器码补丁不支持；不能拿其他版本的地址表替代。

写入仅限游戏的可写数据与当前堆；拒绝宿主、代码/只读区域、越界、溢出、坏指针，内核检查内存拷贝失败时停用对应金手指。全帧最多 4096 条 VM 指令，64 项、每项 1024 words、文件 64 KiB，防止死循环拖住游戏。关闭停止持续写入，已经改变的游戏状态不保证自动恢复。旧的 CAS data32 可逆补丁接口保持独立。

## 画面

帧率上限通过实际呈现节拍函数处理，144 档仍标记实验；其目标间隔为约 6.94 ms。原有游戏间隔、确定性时钟与插帧模式保持各自的计时路径，不被应用上限覆盖。上限和解除原 30 帧等待不代表设备能稳定达到该帧率，需按场景读取真实帧时间。

开发诊断 `DM_NVN_TSV` 增加 `@queue_lock_ms` 与 `@queue_api_ms`：分别为前后两次快照间、渲染提交路径的队列互斥等待和 `vkQueueSubmit2` 驱动调用耗时。异步提交的观察区间不等同于 GPU 执行帧；没有可用 Vulkan 后端时不输出这两项。现有共享队列同步继续保留，不把 CPU 锁等待、驱动调用或旧 Metal 占位计数混称为 GPU 执行时间。

TOTK：新增呈现端 FSR 1 EASU＋RCAS，可调锐化 0–100；不支持的 Vulkan 能力或资源失败自动回退双线性。默认保留双线性，用户可选择 FSR。此处输出尺寸是窗口尺寸，不冒充游戏内部渲染分辨率。BOTW：保留真实 FSR1/SMAA/TAA，在控制栏补齐上采样质量和锐化入口；FSR3.1 仍遵循既有实验能力门禁。

Steam Deck 使用 AMD GPU，本轮没有 DLSS。FSR3/4、帧生成不能仅靠移植一个菜单开关获得；深度、运动向量、抖动及 HUD 分离必须接到对应渲染后端并验证后才开放。

### FSR4 / DLSS 评估更新（2026-11-15）

AMD 在 2026-10-28 发布的 FSR SDK 2.4 已将 Upscaling 4.1.2 扩展到 RX 6000 独显及部分 Ryzen APU，其中包含 Z2 A，并增加 Vulkan 后端。因此不再采用“FSR4 仅限 RDNA4”的旧判断。[官方发布说明](https://gpuopen.com/learn/amd-fsr-sdk-2-4-rx-6000-ryzen-apus/)

不过，官方支持名单未列 Steam Deck；同属 RDNA2 不能代替具体设备支持查询。固定检查的 [SDK v2.4.0](https://github.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK/tree/7539ae8b6568ad29ed78a753404351daf3b5cca7/Kits/FidelityFX/signedbin) 中，Vulkan loader/upscaler/framegeneration 仍是 `.dll`／`.lib`，该目录无 Linux `.so`。这是当前原生 ELF 接入的缺口，Vulkan API 支持不能直接视为原生 Linux 支持；未下载 SDK、安装兼容层或修改掌机环境。

后续接入须分别证明：可用的原生 Linux 库与许可；设备和 Vulkan 特性查询；对应场景的深度、运动向量、抖动、曝光和历史重置；HUD／透明物分离及资源生命周期；实际 GPU 时间、额外内存与画面收益。按官方资源查询区分必需和可选输入，FSR4 的 reactive／composition mask 不能误列为始终必需。[输入与资源要求](https://gpuopen.com/manuals/fsr_sdk/techniques/super-resolution-ml/)

当前 TOTK 仍是呈现端 FSR1，不声明已接入 FSR3/4。DLSS 仍按 [NVIDIA RTX SDK](https://github.com/NVIDIA/DLSS) 的实际设备能力评估；Steam Deck 的 AMD GPU 没有可据此开放 DLSS 的证据。新后端只有通过实际调用、帧时间、重投影／拖影、回退、持久化和 Deck 使用链验收后才进入控制栏，默认画面路径保持原契约。`hardware_validated=false`。

## 上游与许可

- [totk-pc-recomp](https://github.com/valentderah/totk-pc-recomp/tree/0ae47a578285cde080642c9e6c40316c99171ef1)：MIT；借鉴只读 Amiibo ABI 与 Atmosphère VM 执行。原作者 MIT 声明在 licenses/ 和 third_party/native-atmosphere/。
- [UltraTears](https://github.com/kuraeow/ultratears/tree/57bf619e7ef579a0675a4d41d74413ebaca02fb8)：TOTK 呈现 FSR glue 为 GPL，AMD shader/头文件为 MIT，许可保留。未复制到 BOTW。
- [Atmosphère 指令格式](https://github.com/Atmosphere-NX/Atmosphere/blob/master/docs/features/cheats.md)，[libnx NFC ABI](https://github.com/switchbrew/libnx/blob/master/nx/include/switch/services/nfc.h)。

合成标签、内存与图形组件验证不等于游戏验收；hardware_validated=false，实际游玩由用户手测。

公开公仔ID：N3evin/AmiiboAPI@6115745c56ff762ce212ced6fbad9ea195d659b3（MIT，许可证随包）。原生SDL触屏手势直接进入应用UI，合成鼠标事件去重，完整手势归属、多指、取消与失焦受检；触摸主指抬起前不会由其他手指抢走控制。

触摸下拉框按实际44像素选项行高计算弹窗，并限制在屏幕高度75%以内；长公仔库与页面共用同一拖动滚动方式，短列表完整显示。BOTW侧栏复用随包菜单字体与中文回退（800p约22像素），不依赖系统拉丁字体、不新增重复字体图集。
