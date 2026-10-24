"""书脊定位: 在跨页扫描图上找到左右两页的分界 x。

思路(按可靠性排序, 组合打分):

1. **页眉行法(主信号)**
   书眉位于页面上方约 4%~9%, 形如 "<<< 章节名 | 15" 或 "928 章节名 (2023) >>>"。
   书脊正上方, 左页页眉右端(有 >>>) 与右页页眉左端(有 <<<) 紧邻。
   取页眉带内"墨迹的最长空白间隙"作为书脊候选。

2. **正文列沟法(辅信号)**
   两页各有自己的外侧页边距, 中间夹着书脊阴影/高光, 形成一条
   "墨迹稀疏带"。在 35%~65% 范围内找该带中心。

3. **合成**
   两者都给出候选时取加权; 仅一个可用时用它; 都不行则退回 0.5。
   最终位置限制在 [0.40, 0.60], 防止被页内空白带偏。
"""
import numpy as np
import scipy.ndimage as ndi


def _to_gray(img, width=1600):
    import numpy as np
    from PIL import Image
    W, H = img.size
    h = max(1, int(width * H / W))
    return np.array(img.convert("L").resize((width, h), Image.LANCZOS))


def _col_profile(g, lo=0.18, hi=0.94):
    """返回 (宽度, 正文带内每列的墨迹占比)"""
    W = g.shape[1]
    t, b = int(g.shape[0] * lo), int(g.shape[0] * hi)
    band = g[t:b]
    # 局部背景(纸面弯曲/阴影)归一化后再二值化
    bg = ndi.maximum_filter1d(band.astype(np.float32), size=101, axis=1)
    dark = ((bg - band) > 26)
    prof = dark.sum(axis=0) / band.shape[0]
    return W, ndi.uniform_filter1d(prof.astype(np.float32), size=9)


def _widest_gap(prof, frac_lo=0.30, frac_hi=0.70, min_gap_frac=0.010):
    """在 [frac_lo, frac_hi] 内找最长的连续低墨迹带, 返回 (中心, 宽度比例)"""
    W = len(prof)
    lo, hi = int(W * frac_lo), int(W * frac_hi)
    if hi - lo < 10:
        return None
    seg = prof[lo:hi]
    thr = max(0.02, float(np.median(seg)) * 0.42)
    below = seg <= thr
    # 最长连续 True
    best = (0, None, None)
    start = None
    for i, v in enumerate(below):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start > best[0]:
                best = (i - start, start, i - 1)
            start = None
    if start is not None and len(below) - start > best[0]:
        best = (len(below) - start, start, len(below) - 1)
    gap, a, b = best
    if gap < W * min_gap_frac or a is None:
        return None
    return ((lo + a + b) / 2.0 / W, gap / W)


def _header_gap(g):
    """页眉带内的最长空白间隙 -> 书脊候选"""
    H, W = g.shape
    t, b = int(H * 0.035), int(H * 0.105)
    band = g[t:b]
    if band.size == 0:
        return None
    bg = ndi.maximum_filter1d(band.astype(np.float32), size=81, axis=1)
    dark = ((bg - band) > 26)
    prof = dark.sum(axis=0) / band.shape[0]
    prof = ndi.uniform_filter1d(prof.astype(np.float32), size=5)
    lo, hi = int(W * 0.35), int(W * 0.65)
    seg = prof[lo:hi]
    if len(seg) < 10:
        return None
    thr = max(0.02, float(np.median(seg)) * 0.35)
    below = seg <= thr
    best = (0, None, None)
    start = None
    for i, v in enumerate(below):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start > best[0]:
                best = (i - start, start, i - 1)
            start = None
    if start is not None and len(seg) - start > best[0]:
        best = (len(seg) - start, start, len(seg) - 1)
    gap, a, b = best
    if gap < W * 0.006 or a is None:
        return None
    return ((lo + a + b) / 2.0 / W, gap / W)


def find_spine(img, verbose=False):
    """返回 (书脊比例, 诊断 dict)。始终落在 [0.40, 0.62]。"""
    g = _to_gray(img)
    W, prof = _col_profile(g)
    body = _widest_gap(prof, 0.30, 0.70, 0.010)
    head = _header_gap(g)

    diag = {"body": body, "header": head}
    cands = []
    if body:
        cands.append((body[0], 0.55))
    if head:
        cands.append((head[0], 0.45))
    if not cands:
        diag["chosen"] = 0.5
        diag["mode"] = "fallback-0.5"
        return 0.5, diag

    x = sum(p * w for p, w in cands) / sum(w for _, w in cands)
    # 两个候选一致 -> 置信高
    if body and head and abs(body[0] - head[0]) < 0.035:
        diag["mode"] = "agree"
        diag["conf"] = "high"
    elif body and head:
        diag["mode"] = "disagree"
        diag["conf"] = "mid"
    else:
        diag["mode"] = "single"
        diag["conf"] = "mid"

    # 夹到安全区间: 真实书脊不会跑出 40%~62%
    x = min(0.62, max(0.40, x))
    diag["raw"] = sum(p * w for p, w in cands) / sum(w for _, w in cands)
    diag["chosen"] = x
    if verbose:
        print("  ", diag)
    return x, diag