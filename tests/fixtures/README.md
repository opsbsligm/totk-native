# 公共合成音视频夹具

`synthetic-av.webm` 是本任务用 FFmpeg lavfi 蓝色画面（32×32、10 fps）和 440 Hz 正弦波生成的 1 秒 VP9/Opus 文件，不含游戏内容。源码检查只允许此精确文件及其 SHA-256；其他 WebM 仍被禁止。工具链自检实际解码它，再破坏其 EBML 头确认拒绝损坏输入。

生成命令：

```sh
ffmpeg -f lavfi -i color=c=blue:s=32x32:r=10 -f lavfi -i sine=frequency=440:sample_rate=48000 -t 1 -c:v libvpx-vp9 -deadline realtime -cpu-used 8 -c:a libopus synthetic-av.webm
```

测试文件随本项目根许可证发布。
