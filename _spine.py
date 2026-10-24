#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨页扫描件的书脊定位(纯图像算法, 对 7 张实测图验证通过)。

【两种物理形态, 必须分别处理】
实测 7 张图, 书脊有两种形态:

A) **有白色装订沟**(0051 / 0059 / 0061 / 0075 / 0311):
   沟内整列几乎无墨(暗像素列高 == 0), 且这段空白有一段宽度。
   -> 找「暗像素剖面 == 0 的连续段」, 取其中点。

B) **裁切紧、无白沟**(0255 / 0155):
   两页内容贴在一起, 靠左页表格的**右边框线**分界。
   那根线是一根贯穿的竖线(暗像素列高远高于相邻文字列), 线右边立刻掉回低值。
   -> 找「暗像素剖面的窄尖峰」, 取尖峰的**右沿**。

判别: 先按 A 找(有 0 值段就用 A), 找不到再用 B。

【实测真值(肉眼逐边核对过的)】
  0051  2300   0059  2260   0061  2250   0075  2100
  0255  2750   0155  2422
"""
import numpy as np
from PIL import Image


def _profile(img):
    a = np.asarray(img.convert("L"), dtype=np.uint8)
    H, W = a.shape
    reg = (a[int(H * 0.06):int(H * 0.95)] < 150)
    return reg.sum(axis=0).astype(float), H, W


def find_zero_gap(cc, W):
    """形态 A: 找暗像素为 0 的连续段(白色装订沟)"""
    lo, hi = int(W * 0.30), int(W * 0.75)
    best = None
    x = lo
    while x < hi:
        if cc[x] == 0:
            s = x
            while x < hi and cc[x] == 0:
                x += 1
            e = x - 1
            width = e - s + 1
            # 沟要足够宽(>= 8px), 且位置在中线附近
            if width >= 8 and int(W * 0.40) <= (s + e) // 2 <= int(W * 0.68):
                if best is None or width > best[2]:
                    best = (s, e, width)
        else:
            x += 1
    if best:
        s, e, w = best
        return (s + e) // 2, f"白沟 {s}-{e} (宽{w})"
    return None, ""


def find_border_spike(cc, W):
    """形态 B: 找暗像素剖面的**孤立尖峰**(表格右边框), 取右沿。

    坑: 不能只看「峰/邻域比」, 还要**孤立性** ——
    实测 0255 真值 x=2750 的 cc=1494, 两侧邻居只有 ~650(比值 2.3),
    而页面里其它竖线(表头分隔线等)是**连续一片**的。
    所以判据: 尖峰左右各 25px 内的均值都要明显低于峰本身,
    且峰的宽度 <= 15px(单根线, 不是一整片竖线)。
    """
    lo, hi = int(W * 0.30), int(W * 0.75)
    win = 121

    def local_med(x):
        a0, a1 = max(0, x - win), min(W, x + win + 1)
        return float(np.median(cc[a0:a1]))

    best = None
    x = lo
    while x < hi:
        base = local_med(x)
        if cc[x] > max(350, 1.55 * base):
            j = x
            while j < hi and cc[j] > base:
                j += 1
            right = j - 1
            width = right - x + 1
            # 孤立性: 左右各 25px 的均值
            lmean = float(np.mean(cc[max(0, x - 25):x])) if x > 25 else 1e9
            rmean = float(np.mean(cc[right + 1:right + 26])) if right + 26 < W else 1e9
            iso = min(lmean, rmean)
            if width <= 20 and iso < cc[x] * 0.75:
                score = cc[x] / max(1.0, max(lmean, rmean))
                if best is None or score > best[0]:
                    best = (score, x, right, base, iso)
            x = j + 15
        else:
            x += 3
    if best:
        _, x, right, base, iso = best
        return right, (f"孤立尖峰 {x}-{right} (峰/邻={best[0]:.1f}, "
                       f"邻均={iso:.0f})")
    return None, ""


def find_spine(img, verbose=False):
    """返回 (cut_x, 说明)"""
    cc, H, W = _profile(img)
    cut, why = find_zero_gap(cc, W)
    if cut is not None:
        return cut, why
    cut, why = find_border_spike(cc, W)
    if cut is not None:
        return cut, why
    # 兜底: 暗像素列剖面最小
    k = max(3, W // 400)
    sm = np.convolve(cc, np.ones(k) / k, mode="same")
    lo, hi = int(W * 0.34), int(W * 0.70)
    v = lo + int(np.argmin(sm[lo:hi]))
    return v, f"沟谷 {v} (兜底)"


def split_pages(src_img, page_no):
    im = Image.open(src_img)
    W, H = im.size
    cut, why = find_spine(im)
    cut = max(200, min(W - 200, cut))
    return (im.crop((0, 0, cut, H)), im.crop((cut, 0, W, H)), cut, why)


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        c, w = find_spine(Image.open(p), verbose=True)
        print(f"{p}\n   cut={c}  {w}")
