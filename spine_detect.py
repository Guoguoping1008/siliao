"""单页书脊位置检测。

对每张跨页扫描图, 独立求出一条书脊线 (可带倾斜), 用于左右切分。

原理与依据
----------
1. 横向切分位��的物理约束
   两页各自有版心, 左右对称地分布在书脊两侧。整幅图的版心中线
   (版心左右边界的中点) 是书脊位置的一阶近似 —— 实测这是最稳的基线,
   因为版心边界由印刷决定, 不受纸面弯曲/明暗影响。

2. 纵向倾斜
   弯曲扫描件的书脊会随高度漂移(实测 0235.jpg 顶部 0.473 -> 底部 0.458)。
   因此把图分成若干横条带, 每条带独立求一个候选 x, 再用稳健直线拟合。

3. 为什么不用"找空白沟"
   实测这些页面的正文排版几乎贴到折痕, 列墨迹剖面在中缝处没有明显谷值;
   段内空白(表格间隙/段落空行)反而更宽, 用投影找沟会大量误判。
   曾经"最暗谷"方案误报 139/511 页。

返回值
------
dict:
  x_top / x_bot : 书脊在图顶 / 图底处的 x 比例(0~1)
  slope         : x 从顶到底的变化量 (x_bot - x_top)
  mode          : 'lines' | 'mid' | 'fallback'
  conf          : 'high' | 'mid' | 'low'
  samples       : [(y比例, x比例), ...] 各条带候选(调试用)
"""
import numpy as np
import scipy.ndimage as ndi
from PIL import Image

# ---- 可调参数(均由标定集实测确定) ----
PREP_W = 1400          # 分析宽度(够用且快)
EDGE_DROP = 0.012      # 去掉纸张外缘噪声的比例
REFINE_MAX = 0.015     # 单条带微调的最大偏移
CLAMP_LO, CLAMP_HI = 0.40, 0.60   # 安全区间, 真值落在 0.478~0.500
NBANDS = 7             # 纵向条带数
BAND_LO, BAND_HI = 0.14, 0.92     # 有效纵向范围(避开页眉页脚)
SEARCH_LO, SEARCH_HI = 0.42, 0.58 # 单条带内搜索书脊的范围
MIN_SLOPE, MAX_SLOPE = -0.06, 0.06  # 允许的倾斜量(实测最大约 -0.037)


def _prepare(img, width=PREP_W):
    """灰度 + 局部背景归一化(消除纸面弯曲造成的整片明暗)。"""
    W, H = img.size
    h = max(1, int(width * H / W))
    g = np.array(img.convert("L").resize((width, h), Image.LANCZOS))
    bg = ndi.maximum_filter1d(g.astype(np.float32),
                              size=max(15, int(width * 0.07)), axis=1)
    return g, bg


def _col_profile(g, bg, y_lo, y_hi):
    """指定纵向区间内的列墨迹占比。"""
    t, b = int(g.shape[0] * y_lo), int(g.shape[0] * y_hi)
    if b - t < 10:
        return None
    band = (bg[t:b] - g[t:b]) > 26
    if band.size == 0:
        return None
    prof = band.sum(axis=0) / band.shape[0]
    return ndi.uniform_filter1d(prof.astype(np.float32), size=7)


def _body_bounds(prof, W):
    """版心左右边界(比例)。

    不能用 min/max: 有些页面文字满版(出血印刷), 或纸张边缘本身偏暗,
    min/max 会落到纸张外缘(实测 0235.jpg 每条带都返回 0.011~0.988, 完全无信息)。
    改用**分位数**: 取墨迹密集区的 1% / 99% 分位, 对少量异常列稳健。
    """
    thr = max(0.02, float(np.median(prof)) * 0.22)
    idx = np.where(prof > thr)[0]
    if len(idx) < 20:
        return None
    # 分位数替代 min/max(抗离群)
    L = float(np.percentile(idx, 1.0))
    R = float(np.percentile(idx, 99.0))
    drop = W * EDGE_DROP
    L += drop
    R -= drop
    if R - L < W * 0.3:          # 版心太窄, 判定失败
        return None
    return L / W, R / W


def _valley_refine(prof, W, base):
    """在 base 附近找列墨迹的局部极小(亚像素), 作为书脊微调。"""
    lo = max(0, int((base - REFINE_MAX) * W))
    hi = min(W, int((base + REFINE_MAX) * W))
    if hi - lo < 15:
        return base
    seg = prof[lo:hi]
    sm = ndi.uniform_filter1d(seg, size=5)
    i = int(np.argmin(sm))
    d = 0.0
    if 0 < i < len(sm) - 1:
        y0, y1, y2 = sm[i - 1], sm[i], sm[i + 1]
        den = y0 - 2 * y1 + y2
        if abs(den) > 1e-9:
            d = max(-1.0, min(1.0, 0.5 * (y0 - y2) / den))
    cand = (lo + i + d) / W
    # 必须是"谷"而非"峰"
    if sm[i] < float(np.median(sm)) * 0.75:
        return cand
    return base


def detect_spine(img, nbands=NBANDS):
    """检测单张图的书脊线。返回 dict(见模块 docstring)。"""
    g, bg = _prepare(img)
    H, W = g.shape

    # ---------- 1) 全图版心中线(基线) ----------
    prof_all = _col_profile(g, bg, BAND_LO, BAND_HI)
    if prof_all is None:
        return {"x_top": 0.5, "x_bot": 0.5, "slope": 0.0,
                "mode": "fallback", "conf": "low", "samples": []}
    bb = _body_bounds(prof_all, W)
    if bb is None:
        return {"x_top": 0.5, "x_bot": 0.5, "slope": 0.0,
                "mode": "fallback", "conf": "low", "samples": []}
    L, R = bb
    base = (L + R) / 2.0
    base = _valley_refine(prof_all, W, base)

    # ---------- 2) 逐条带求候选, 检测倾斜 ----------
    samples = []
    for i in range(nbands):
        y0 = BAND_LO + (BAND_HI - BAND_LO) * i / nbands
        y1 = BAND_LO + (BAND_HI - BAND_LO) * (i + 1) / nbands
        p = _col_profile(g, bg, y0, y1)
        if p is None:
            continue
        b2 = _body_bounds(p, W)
        if b2 is None:
            continue
        l2, r2 = b2
        cand = (l2 + r2) / 2.0
        ymid = (y0 + y1) / 2.0
        samples.append((ymid, cand))

    if len(samples) < 3:
        return {"x_top": base, "x_bot": base, "slope": 0.0,
                "mode": "mid", "conf": "mid",
                "body": (round(L, 4), round(R, 4)), "samples": samples}

    # ---------- 3) 稳健直线拟合(剔除离群条带) ----------
    ys = np.array([s[0] for s in samples])
    xs = np.array([s[1] for s in samples])
    slope, intercept = _robust_line(ys, xs, base)
    slope = max(MIN_SLOPE, min(MAX_SLOPE, slope))

    x_top = intercept + slope * 0.0
    x_bot = intercept + slope * 1.0
    # 夹到安全区间
    x_top = min(CLAMP_HI, max(CLAMP_LO, x_top))
    x_bot = min(CLAMP_HI, max(CLAMP_LO, x_bot))

    return {
        "x_top": float(x_top),
        "x_bot": float(x_bot),
        "slope": float(x_bot - x_top),
        "mode": "lines",
        "conf": "high" if len(samples) >= nbands - 1 else "mid",
        "body": (round(L, 4), round(R, 4)),
        "samples": [(round(y, 3), round(x, 4)) for y, x in samples],
    }


def _robust_line(ys, xs, base):
    """拟合 x = slope*y + intercept。
    策略: 以全图基线 base 为先验, 反复剔除偏离过大的条带后最小二乘。
    比 RANSAC 稳定 —— 之前 RANSAC 会追逐离群点, 拟合出 -0.087 的假斜率。
    """
    keep = np.ones(len(ys), dtype=bool)
    slope, intercept = 0.0, float(np.mean(xs))
    for _ in range(3):
        if keep.sum() < 2:
            break
        yk, xk = ys[keep], xs[keep]
        if len(yk) >= 2:
            slope, intercept = np.polyfit(yk, xk, 1)
        else:
            slope, intercept = 0.0, float(xk[0])
        # 以"到基线的距离"和"到当前直线的距离"联合判定离群
        resid = np.abs(xs - (intercept + slope * ys))
        off = np.abs(xs - base)
        tol = max(0.010, 2.5 * float(np.median(resid[keep])))
        new_keep = (resid <= tol) & (off <= 0.05)
        if new_keep.sum() < 2:
            break
        if new_keep.sum() == keep.sum():
            break
        keep = new_keep
    return float(slope), float(intercept)


def spine_x_at(diag, y_frac):
    """给定纵向比例(0=顶, 1=底)返回书脊 x 比例。"""
    xt, xb = diag.get("x_top", 0.5), diag.get("x_bot", 0.5)
    return xt + (xb - xt) * max(0.0, min(1.0, y_frac))


if __name__ == "__main__":
    import sys
    sys.path.insert(0, r"E:/workspace/siliao")
    from PIL import Image
    try:
        import spine_eval
        GT = spine_eval.GROUND_TRUTH
    except Exception:
        GT = {}

    print("%-30s %-7s %-8s %-8s %-8s %-8s %s" %
          ("file", "truth", "x_top", "x_bot", "mid", "err", "mode"))
    errs = []
    for f, (truth, _why) in GT.items():
        im = Image.open(r"E:/workspace/siliao/" + f)
        d = detect_spine(im)
        mid = spine_x_at(d, 0.5)
        e = mid - truth
        errs.append((abs(e), f))
        print("%-30s %.3f   %.4f   %.4f   %.4f   %+.4f  %s" % (
            f.replace("\\", "/")[-28:], truth, d["x_top"], d["x_bot"],
            mid, e, d["mode"]))
    if errs:
        errs.sort(reverse=True)
        mae = sum(e for e, _ in errs) / len(errs)
        print("\nMAE = %.4f   最大 = %.4f" % (mae, errs[0][0]))
        print("最差:", errs[0][1].replace("\\", "/"))