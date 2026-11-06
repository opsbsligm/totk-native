# 掌机控制栏与扩展功能

F1 或 Minus+Plus 打开控制栏；A 确认、B 返回，拖动后自动吸附八个边角。画面、控制、扩展分为三个页签，避免长列表堆叠。游戏世界按键与原生陀螺仪保持既有逻辑。

## Amiibo

自有标准 NTAG215 的 540 字节 `.bin` 放入 `$XDG_DATA_HOME/<game>/amiibo/`（未设置时为 `~/.local/share/<game>/amiibo/`），`<game>` 为 `totk-native` 或 `botw-native`。控制栏刷新后选择；进入游戏的 Amiibo 扫描能力后会检测到标签。读完选择“移开标签”，再选下一枚。只支持只读公仔身份；应用区存档、写入、Wolf Link 存档能力未实现。拒绝损坏 UID 校验、错误大小、符号链接及非本人所有文件。仓库不提供标签 dump。

## Atmosphère 金手指

放到相同游戏的数据目录 `cheats/<BuildID前8字节的16位大写十六进制>.txt`，权限设为 `0600`。控制栏显示准确路径，可重新加载。文件必须匹配实际加载的完整游戏版本。控制栏文件读取与解析由单一后台工作线程执行，不持有逐帧VM锁；导入期间禁止开启旧项，游戏版本变化会丢弃旧导入结果。“全部关闭”可立即停止持续写入。每项（包括 master）默认关闭；不支持的项保留原因并禁用。支持 0–A 的数据/指针/条件/按键/循环指令，内存区域仅 main 与 heap。扩展 C/F 指令及静态重编译机器码补丁不支持；不能拿其他版本的地址表替代。

写入仅限游戏的可写数据与当前堆；拒绝宿主、代码/只读区域、越界、溢出、坏指针，内核检查内存拷贝失败时停用对应金手指。全帧最多 4096 条 VM 指令，64 项、每项 1024 words、文件 64 KiB，防止死循环拖住游戏。关闭停止持续写入，已经改变的游戏状态不保证自动恢复。旧的 CAS data32 可逆补丁接口保持独立。

## 画面

TOTK：新增呈现端 FSR 1 EASU＋RCAS，可调锐化 0–100；不支持的 Vulkan 能力或资源失败自动回退双线性。默认保留双线性，用户可选择 FSR。此处输出尺寸是窗口尺寸，不冒充游戏内部渲染分辨率。BOTW：保留真实 FSR1/SMAA/TAA，在控制栏补齐上采样质量和锐化入口；FSR3.1 仍遵循既有实验能力门禁。

Steam Deck 使用 AMD GPU，本轮没有 DLSS。FSR3/4、帧生成不能仅靠移植一个菜单开关获得；深度、运动向量、抖动及 HUD 分离必须接到对应渲染后端并验证后才开放。

## 上游与许可

- [totk-pc-recomp](https://github.com/valentderah/totk-pc-recomp/tree/0ae47a578285cde080642c9e6c40316c99171ef1)：MIT；借鉴只读 Amiibo ABI 与 Atmosphère VM 执行。原作者 MIT 声明在 licenses/ 和 third_party/native-atmosphere/。
- [UltraTears](https://github.com/kuraeow/ultratears/tree/57bf619e7ef579a0675a4d41d74413ebaca02fb8)：TOTK 呈现 FSR glue 为 GPL，AMD shader/头文件为 MIT，许可保留。未复制到 BOTW。
- [Atmosphère 指令格式](https://github.com/Atmosphere-NX/Atmosphere/blob/master/docs/features/cheats.md)，[libnx NFC ABI](https://github.com/switchbrew/libnx/blob/master/nx/include/switch/services/nfc.h)。

合成标签、内存与图形组件验证不等于游戏验收；hardware_validated=false，实际游玩由用户手测。
