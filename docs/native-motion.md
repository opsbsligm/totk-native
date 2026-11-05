# 原生运动输入来源

本项目自行编写的 sensor-only 读取器和解码器以 MIT 发布。数据格式参考 SDL 3.2.30 的公开 Steam Deck 后端：[SDL_hidapi_steamdeck.c](https://github.com/libsdl-org/SDL/blob/release-3.2.30/src/joystick/hidapi/SDL_hidapi_steamdeck.c)。SDL 的版权和 zlib 许可仍属于其作者，本实现没有复制 SDL 手柄设置或按钮映射逻辑。

只接收64字节、头部 `01 00 09 40` 的报告：计数器位于4，三个有符号16位加速度位于24，三个角速度位于30；2G 与 2000°/s 量程换算后进入现有姿态融合。全零重力、错误长度和错误报告头被拒绝；读取只保留最新报告，停止时解除传感器在线状态。父启动器只维护 IMU sensor bits 的可恢复租约。

2026-11-05 在真实 Deck 上独立验证了751个新鲜有限样本和退出后的模式读回。该验证不证明游戏内的瞄准方向或灵敏度；这些仍由玩家验收。
