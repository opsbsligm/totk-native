#!/usr/bin/env python3
"""从 docs/deck-grid/src 里的任天堂官方素材重生成 Steam 库四件套。

源图随仓库走：用过的两处官方来源都会失效（旧竖版素材桶已下线，zelda.com
媒体站 CDN 现在返回 403），只记 URL 的话换机器取不回同一批像素。
源图 SHA-256 见 src/SHA256SUMS。

  totk-bg.jpg      2560x1592 官方无字背景（起桥之台与浮岛，无字标无平台横幅）
  totk-keyart.jpg  1920x1080 官方含 Link 的主视觉；左下有字标、底部有平台横幅，
                   所以本脚本只取它 x>=840 的右半区
  totk-logo.png    696x362   官方白色字标，按 alpha 裁过，不含平台横幅

生成只做绝对坐标裁切、Lanczos 缩放与字标叠加，不重绘、不加滤镜。
每个框都先核与目标尺寸的宽高比（见 __main__ 里的 _check），比例不符就是拉伸变形。

    python3 docs/deck-grid/gen-deck-art.py [输出目录，默认本目录]

四件尺寸是 Steam Deck 库规格：横卡 920x430、竖海报 600x900、
详情页 hero 1920x620、快捷方式图标 1254x1254。装到掌机用同目录的
deploy-deck-art.sh。
"""
import hashlib
import pathlib
import sys
from PIL import Image

HERE = pathlib.Path(__file__).resolve().parent
OUT = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else HERE
SRC = HERE / "src"
BG = SRC / "totk-bg.jpg"
KEYART = SRC / "totk-keyart.jpg"
LOGO = SRC / "totk-logo.png"

PLAN = {
    # out 文件名: (源图, (left, top, right, bottom), 目标尺寸)
    "totk-grid.png": (BG, (0, 320, 2560, 1516), (920, 430)),
    "totk-hero.png": (BG, (0, 300, 2560, 1126), (1920, 620)),
    "totk-grid-p.png": (BG, (1339, 0, 2400, 1592), (600, 900)),
    "totk-shortcut-icon.png": (KEYART, (840, 0, 1920, 1080), (1254, 1254)),
}
LOGO_ON_POSTER = (0.70, 0.05)   # 字标宽占海报宽的比例、顶边占海报高的比例


def _aspect(src_box, size, name):
    w, h = src_box[2] - src_box[0], src_box[3] - src_box[1]
    want, got = size[0] / size[1], w / h
    if abs(want - got) / want > 0.005:
        raise SystemExit("%s: 裁切框 %dx%d 与目标 %dx%d 宽高比不符（%.2f%% 偏差）"
                         % (name, w, h, size[0], size[1], abs(want - got) / want * 100))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (src, box, size) in PLAN.items():
        im = Image.open(src).convert("RGB")
        l, t, r, b = box
        assert 0 <= l < r <= im.width and 0 <= t < b <= im.height, "%s box %s 越界" % (name, box)
        _aspect(box, size, name)
        art = im.crop(box).resize(size, Image.LANCZOS)
        if name == "totk-grid-p.png":
            logo = Image.open(LOGO).convert("RGBA")
            lw = int(size[0] * LOGO_ON_POSTER[0])
            logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
            art = art.convert("RGBA")
            art.paste(logo, ((size[0] - lw) // 2, int(size[1] * LOGO_ON_POSTER[1])), logo)
            art = art.convert("RGB")
        art.save(OUT / name, "PNG")
        print("%-26s %sx%s  %s" % (name, size[0], size[1],
                                   hashlib.sha256((OUT / name).read_bytes()).hexdigest()[:16]))


if __name__ == "__main__":
    main()
