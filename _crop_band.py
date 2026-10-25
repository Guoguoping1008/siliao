#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把跨页表1 的一页切成若干横向条带, 供逐条读格用。

用法:
  python _crop_band.py <tag> <y0> <y1> [outname] [scale]
例:
  python _crop_band.py 0957 400 900 band1
"""
import os
import sys

from PIL import Image

BASE = r"E:/workspace/siliao/Images/04标准及标准目录"
TMP = os.path.join(os.environ["LOCALAPPDATA"], "Temp")

# 各页右半(表1 所在页)的 x 范围
X0 = 2050


def main():
    tag = sys.argv[1]
    y0 = int(sys.argv[2])
    y1 = int(sys.argv[3])
    out = sys.argv[4] if len(sys.argv) > 4 else "band"
    scale = float(sys.argv[5]) if len(sys.argv) > 5 else 1.0
    im = Image.open(os.path.join(BASE, tag + ".jpg"))
    W, H = im.size
    c = im.crop((X0, y0, W, y1))
    if scale != 1.0:
        c = c.resize((int(c.width * scale), int(c.height * scale)), Image.LANCZOS)
    p = os.path.join(TMP, out + ".png")
    c.save(p)
    print(p, c.size)


if __name__ == "__main__":
    main()
