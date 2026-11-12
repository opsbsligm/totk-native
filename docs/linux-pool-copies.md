# Linux 内存池候选路径

当前默认仍导入游戏内存。`TOTK_POOL_COPY=1` 才启用候选；`TOTK_POOL_IMPORT=1` 优先恢复导入路径。正式 Steam 入口尚未启用候选。

来源固定为 [UltraTears d657eff841e4](https://github.com/kuraeow/ultratears/blob/d657eff841e4ab80cd2aa4ba30f17d85f6402d9d/src/gfx/backend_vk.c)。上游说明 AMDGPU 对导入的 userptr 内存逐次提交进行逐页检查。本项目的 Deck 诊断也观察到提交线程较高的内核 CPU 时间及约 9.5 ms 的提交 ioctl；跟踪器有开销，这些数据不能作为优化后的帧率结论。

候选把池放进可映射、coherent 的 Vulkan 内存，64 MiB 块内分配，避免每个池创建一份驱动内存分配。Linux 6.7+ 的 `userfaultfd` 异步写保护和 `PAGEMAP_SCAN` 追踪 CPU 写页；不要求 root，不修改 sysctl、功耗或频率。提交前同步使用过的池，完成后按提交时快照合并 GPU 输出，再发布游戏事件和完成标志。较新的 CPU 字节保留，不能直接用 GPU 数据覆盖整块游戏内存。

本轮适配范围为集成 GPU，且不启用独立显存 shadows。不可读的虚拟池沿用现有 NVN 处理；重叠的实际池明确拒绝。缺少写监视、监视中途失效、分配失败或快照超预算时明确终止候选运行；退出实验变量可回到默认路径。每次 GPU 写范围的快照上限 16 MiB，全部在途快照合计 256 MiB，在途范围最多 65,536。没有吸收上游的冻结页/信号处理优化。

验收需要：生产 C 的写页与合并边界测试、运行时构建和安全审查、实际 Deck 内核探测、同场景默认/候选对照，以及加载/切场景/角色与地形渲染检查。尚无优化效果验收，`hardware_validated=false`。代码路径可编译、选项可读回或单帧截图均不能替代这些条件。
