本轮 v2 图示由本项目以 SVG 自行绘制并生成 PNG/RLE，未复制游戏像素。以下保留旧 v1 图示的来源与许可证历史；该记录不把新图示归属于旧图作者。

# Steam Deck 按键示意图来源

`src/gfx/totk_deck_bitmaps.h` 是自主绘图的 RLE 产物，不含 Nintendo 游戏图像。原绘图由本项目所有者提供；原文件未标注独立作者姓名，本项目不补造原作者或将第三方材料重新授权。

几何绘制和 Fira Sans 文字布局参考 `Revivedx/SavageWindRecomp` 提交 `4249c880bc6b09ad0207fc3f6e7595346f08d232` 的 `runtime/nvn/glyphs.c`；作者及 MIT 条款见 `LICENSE.SavageWind.txt`。字体为未修改的 Fira Sans SemiBold，作者声明与 OFL 见 `OFL.FiraSans.txt`。光栅化使用该上游 Dear ImGui 的 `imstb_truetype.h`；其 MIT 声明见 `LICENSE.imgui.txt`。

本任务新增的画布适配、斜视投影和 RLE 编解码沿用 `LICENSE.adaptation.txt`。这些条款不替代各来源的许可。此工程仅使用已生成的示意图；构建无需游戏图像、系统字体或旧 nativedeck 工作区。
