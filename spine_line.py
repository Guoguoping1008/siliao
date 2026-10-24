"""书脊线定位(逐行) —— 处理斜书脊。

核心思想:
  书脊不一定垂直, 在弯曲的扫描件上会随高度漂移(实测最大约 1.5% 页宽)。
  做法: 把图像按行切成若干条带, 每条带独立找书脊 x, 再拟合成一条直线。

每条带的书脊信号:
  - 局部背景归一化(去纸面弯曲的明暗) -> 暗像素占比列投影
  - 在中线附近(40%~60%)取**最低点**(两页正文之间最空的地方)
  - 亚像素抛物线插值

稳健性:
  - 用中位数对各带结果做离群剔除
  - 用 RANSAC 式拟合: 随机取两点连线, 统计内点, 取最优直线
  - 若有效带不足, 退回全图版心中线
"""
import numpy as np
import scipy.ndimage as ndi
from PIL import Image

SEARCH_LO, SEARCH_HI = 0.42, 0.58
NBANDS = 9                 # 纵向分几条带
PREP_W = 1400               # 分析用宽度


def _prepare(img, width=PREP_W):
    W, H = img.size
    h = max(1, int(width * H / W))
    g = np.array(img.convert("L").resize((width, h), Image.LANCZOS))
    bg = ndi.maximum_filter1d(g.astype(np.float32), size=max(15, int(width * 0.07)), axis=1)
    return g, bg


def _band_spine(g, bg, y0, y1):
    """在一个横向条带内找书脊 x(亚像素)。返回 None 或 (x_frac, valley, median)。"""
    H, W = g.shape
    if y1 - y0 < 12:
        return None
    band = (bg[y0:y1] - g[y0:y1]) > 26
    if band.size == 0:
        return None
    prof = band.sum(axis=0) / band.shape[0]
    prof = ndi.uniform_filter1d(prof.astype(np.float32), size=9)
    lo, hi = int(W * SEARCH_LO), int(W * SEARCH_HI)
    seg = prof[lo:hi]
    if len(seg) < 15:
        return None
    i = int(np.argmin(seg))
    # 亚像素
    d = 0.0
    if 0 < i < len(seg) - 1:
        y0v, y1v, y2v = seg[i - 1], seg[i], seg[i + 1]
        den = (y0v - 2 * y1v + y2v)
        if abs(den) > 1e-9:
            d = 0.5 * (y0v - y2v) / den
            d = max(-1.0, min(1.0, d))
    return (lo + i + d) / W, float(seg[i]), float(np.median(seg))


def find_spine_line(img, nbands=NBANDS, min_ratio=0.55, verbose=False):
    """返回 dict:
        { x_top, x_bot, slope, y0_frac, y1_frac, mode, conf, n_eff, samples }
    slope 定义: x(y) = x_top + slope * (y_frac / (y1-y0))
    """
    g, bg = _prepare(img)
    H, W = g.shape

    # ---- 1) 逐条带取样 ----
    samples = []
    for i in range(nbands):
        a = H * i / nbands
        b = H * (i + 1) / nbands
        # 每条带内部再切上下两半, 增加采样点
        for (f0, f1) in ((0.10, 0.90),):
            r = _band_spine(g, bg, int(a + (b - a) * f0), int(a + (b - a) * f1))
            if r is None:
                continue
            x, valley, med = r
            # 有效带: 谷值显著低于中位
            if med <= 0 or valley <= med * min_ratio:
                samples.append({"y": (i + 0.5) / nbands, "x": x,
                                "valley": valley, "med": med})

    diag = {"n_bands": nbands, "n_raw": len(samples)}

    if len(samples) < 3:
        # 回退: 全图版心中线
        x, m = _body_mid(img)
        diag.update({"mode": "fallback-body", "x_top": x, "x_bot": x,
                     "slope": 0.0, "n_eff": 0})
        return diag

    # ---- 2) RANSAC 直线拟合(抗离群) ----
    best = None
    n = len(samples)
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            y1, y2 = samples[i]["y"], samples[j]["y"]
            x1, x2 = samples[i]["x"], samples[j]["x"]
            if abs(y2 - y1) < 1e-6:
                continue
            k = (x2 - x1) / (y2 - y1)
            b0 = x1 - k * y1
            inl = 0
            err = 0.0
            for s in samples:
                xp = b0 + k * s["y"]
                e = abs(s["x"] - xp)
                if e < 0.012:
                    inl += 1
                    err += e
            if best is None or inl > best[0]:
                best = (inl, k, b0, err)
    if best is None or best[0] < max(3, n // 2):
        xs = np.array([s["x"] for s in samples])
        diag.update({"mode": "median", "x_top": float(np.median(xs)),
                     "x_bot": float(np.median(xs)), "slope": 0.0,
                     "n_eff": n})
        return diag

    _, k, b0, _ = best
    y_lo, y_hi = 0.0, 1.0
    diag.update({
        "mode": "ransac",
        "x_top": float(b0 + k * y_lo),
        "x_bot": float(b0 + k * y_hi),
        "slope": float(k),
        "n_eff": best[0],
        "conf": "high" if best[0] >= max(4, int(n * 0.7)) else "mid",
    })
    if verbose:
        print("   samples:", [(round(s["y"], 2), round(s["x"], 4)) for s in samples])
        print("   ", diag)
    return diag


def _body_mid(img):
    """回退: 版心中线"""
    g, bg = _prepare(img)
    H, W = g.shape
    band = (bg[int(H * 0.16):int(H * 0.95)] - g[int(H * 0.16):int(H * 0.95)]) > 26
    prof = ndi.uniform_filter1d((band.sum(axis=0) / band.shape[0]).astype(np.float32), size=7)
    thr = max(0.02, float(np.median(prof)) * 0.22)
    idx = np.where(prof > thr)[0]
    if len(idx) < 10:
        return 0.5
    L = int(idx.min()) + int(W * 0.012)
    R = int(idx.max()) - int(W * 0.012)
    if R - L < W * 0.3:
        L, R = int(idx.min()), int(idx.max())
    return (L + R) / 2.0 / W


def x_at(diag, y_frac):
    """给定纵向比例(0=顶,1=底), 返回该处的书脊 x 比例。"""
    xt = diag.get("x_top", 0.5)
    xb = diag.get("x_bot", 0.5)
    return xt + (xb - xt) * max(0.0, min(1.0, y_frac))


if __name__ == "__main__":
    import sys
    sys.path.insert(0, r"E:/workspace/siliao")
    import spine_eval
    from PIL import Image

    print("%-30s %-8s %-8s %-8s %-7s %s" %
          ("file", "truth", "x_top", "x_bot", "slope", "mode"))
    errs = []
    for f, (truth, _why) in spine_eval.GROUND_TRUTH.items():
        im = Image.open(r"E:/workspace/siliao/" + f)
        d = find_spine_line(im)
        # 真值是"折痕中部"位置, 与 x_at(0.5) 比较
        got = x_at(d, 0.5)
        e = got - truth
        errs.append((abs(e), f))
        print("%-30s %.3f   %.4f   %.4f   %+.4f  %s" % (
            f.replace("\\", "/")[-28:], truth, d.get("x_top"),
            d.get("x_bot"), d.get("slope", 0), d.get("mode")))
    errs.sort(reverse=True)
    mae = sum(e for e, _ in errs) / len(errs)
    print("\n中部 MAE = %.4f   最大 = %.4f" % (mae, errs[0][0]))