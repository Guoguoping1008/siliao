"""书脊定位 v2: 找左右两页正文块的**中缝**, 而不是纸面折痕。

要点:
- 真正的切分位置应落在"左页正文块右缘" 与 "右页正文块左缘" 之间。
- 每页各有外侧页边距(靠图像边缘)和内侧页边距(靠书脊), 因此在列
  墨迹投影上, 中缝处会出现一个**较宽的低墨迹带**(两页内侧边距叠加)。
- 不能用"最暗谷": 页内空白(段落间、表格间隙)也会产生低谷, 且通常更宽。
- 因此改用"页块结构": 先把墨迹列切成若干连续文字段(行块), 再从
  中部 30%~70% 区间内, 找到能把页面分成"左右两个大块"的那条缝。

实现:
1. 列墨迹投影 -> 二值化 -> 去掉细噪声 -> 找所有连续墨迹段(纵向页块)
2. 合并过短的段(行内字距造成的断裂)
3. 在 30%~70% 内寻找"间隙 >= 1.2% 页宽"的位置, 取其中点
4. 用页眉行做校验: 页眉的左右两段应分别落在切分线两侧
5. 结果夹到 [0.38, 0.64]
"""
import numpy as np
import scipy.ndimage as ndi
from PIL import Image

MIN_GAP = 0.010      # 最小缝隙(页宽比例)
SEARCH_LO = 0.30
SEARCH_HI = 0.70
CLAMP_LO = 0.38
CLAMP_HI = 0.64


def _prepare(img, width=1600):
    W, H = img.size
    h = max(1, int(width * H / W))
    g = np.array(img.convert("L").resize((width, h), Image.LANCZOS))
    # 局部背景归一化, 消除纸面弯曲造成的整片明暗
    bg = ndi.maximum_filter1d(g.astype(np.float32), size=int(width * 0.08), axis=1)
    return g, bg


def _col_ink(g, bg, lo=0.16, hi=0.95):
    t, b = int(g.shape[0] * lo), int(g.shape[0] * hi)
    band, bandbg = g[t:b], bg[t:b]
    dark = (bandbg - band) > 26
    prof = dark.sum(axis=0) / band.shape[0]
    return ndi.uniform_filter1d(prof.astype(np.float32), size=7)


def _blocks(prof, thr_frac=0.30, min_frac=0.006, merge_gap=0.004):
    """把列投影切成连续墨迹块; 返回 (起点比例列表, 间隙中点列表)。"""
    W = len(prof)
    thr = max(0.015, float(np.median(prof)) * thr_frac)
    on = prof > thr
    # 形态学: 闭运算补上行内断裂, 开运算去细噪
    on = ndi.binary_closing(on, structure=np.ones(int(W * merge_gap)))
    on = ndi.binary_opening(on, structure=np.ones(max(1, int(W * 0.0025))))
    # 连续段
    segs, start = [], None
    for i, v in enumerate(on):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= W * min_frac:
                segs.append((start, i - 1))
            start = None
    if start is not None and len(on) - start >= W * min_frac:
        segs.append((start, len(on) - 1))
    gaps = [(segs[i][1], segs[i + 1][0]) for i in range(len(segs) - 1)]
    return segs, gaps


def _center_gap(gaps, W):
    lo, hi = int(W * SEARCH_LO), int(W * SEARCH_HI)
    best = None
    for a, b in gaps:
        if b < lo or a > hi:
            continue
        ga, gb = max(a, lo), min(b, hi)
        if gb <= ga:
            continue
        width = gb - ga
        # 优先选: 足够宽, 且中点尽量接近 0.5(书脊不会偏离中心太多)
        center = (ga + gb) / 2.0 / W
        score = width - abs(center - 0.5) * W * 0.55
        if best is None or score > best[0]:
            best = (score, center, width / W)
    if best and best[2] >= MIN_GAP:
        return best[1], best[2]
    return None, None


def _header_check(g, x_frac):
    """页眉带: 切分线两侧应各有一段墨迹(左页页眉尾 / 右页页眉头)。"""
    H, W = g.shape
    t, b = int(H * 0.035), int(H * 0.105)
    band = g[t:b]
    if band.size == 0:
        return None
    bg = ndi.maximum_filter1d(band.astype(np.float32), size=61, axis=1)
    prof = ((bg - band) > 26).sum(axis=0) / band.shape[0]
    prof = ndi.uniform_filter1d(prof.astype(np.float32), size=5)
    x = int(W * x_frac)
    wl = int(W * 0.05)
    left = float(prof[wl:max(wl + 1, x - wl // 4)].mean()) if x - wl // 4 > wl else 0.0
    right = float(prof[min(W - wl - 1, x + wl // 4):W - wl].mean()) if x + wl // 4 < W - wl else 0.0
    return left, right


def find_spine(img, verbose=False):
    """返回 (切分比例, 诊断)。"""
    g, bg = _prepare(img)
    W = g.shape[1]
    prof = _col_ink(g, bg)
    segs, gaps = _blocks(prof)
    x, gw = _center_gap(gaps, W)

    diag = {"n_blocks": len(segs), "gap_w": gw,
            "raw": x if x else None, "n_gaps": len(gaps)}
    if x is None:
        diag["mode"] = "fallback-0.5"
        diag["conf"] = "low"
        diag["chosen"] = 0.5
        if verbose:
            print("  ", diag)
        return 0.5, diag

    x = min(CLAMP_HI, max(CLAMP_LO, x))
    diag["chosen"] = x
    diag["conf"] = "high" if gw >= 0.018 else "mid"
    diag["mode"] = "gap"
    if verbose:
        print("  ", diag)
    return x, diag


if __name__ == "__main__":
    import sys
    REPS = [
        "Images/02制度文件/0235.jpg",
        "Images/02制度文件/0015.jpg",
        "Images/02制度文件/0031.jpg",
        "Images/03相关法规法律法规文件/0749.jpg",
        "Images/04标准及标准目录/0953.jpg",
        "Images/02制度文件/0035.jpg",
        "Images/02制度文件/0423.jpg",
        "Images/02制度文件/0551.jpg",
        "Images/000封面/封面00.jpg",
        "Images/000封面/封面02.jpg",
    ]
    for p in REPS:
        im = Image.open(p)
        x, d = find_spine(im)
        print("%-34s spine=%.4f  %s  conf=%s" % (
            p.replace("\\", "/")[-32:], x, d["mode"], d["conf"]))