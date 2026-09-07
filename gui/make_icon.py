#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成应用图标 PNG(给 .desktop 用)。只依赖 Pillow,不需要 Qt。
用法: python gui/make_icon.py [输出路径]
"""
import sys
import os

ACCENT = (74, 158, 255)
ACCENT_LT = (143, 196, 255)
BG = (34, 37, 42)


def make(path, size=256):
    from PIL import Image, ImageDraw
    S = 4                        # 先画 4 倍再缩小 = 抗锯齿
    n = size * S
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    u = n / 256.0                # 以 256 为基准的单位

    # 圆角底
    d.rounded_rectangle([8 * u, 8 * u, 248 * u, 248 * u], radius=52 * u, fill=BG + (255,))
    # 检测框
    d.rectangle([66 * u, 66 * u, 190 * u, 190 * u], outline=ACCENT + (255,), width=int(13 * u))
    # 四角角标
    L = 34 * u
    w = int(13 * u)
    for (x, y, dx, dy) in ((66, 66, 1, 1), (190, 66, -1, 1),
                           (66, 190, 1, -1), (190, 190, -1, -1)):
        x, y = x * u, y * u
        d.line([x, y, x + L * dx, y], fill=ACCENT_LT + (255,), width=w)
        d.line([x, y, x, y + L * dy], fill=ACCENT_LT + (255,), width=w)
    # 中心准星
    d.line([128 * u, 106 * u, 128 * u, 150 * u], fill=(255, 255, 255, 255), width=int(9 * u))
    d.line([106 * u, 128 * u, 150 * u, 128 * u], fill=(255, 255, 255, 255), width=int(9 * u))

    im = im.resize((size, size), Image.LANCZOS)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    im.save(path)
    return path


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "icon.png")
    print(make(out))
