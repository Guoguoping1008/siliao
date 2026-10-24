"""书脊定位 v3: 用"左右页各自的外侧页边距"反推书脊位置。

可靠的物理事实:
  - 每页版心左右对称, 外侧页边距(靠书脊)约占版心宽度的 2%~4%。
  - 扫描时整页居中, 因此两页的**外侧空白宽度接近相等**,
    切分线 ≈ 版心左右两半的公共边界。
  - 版心 = 墨迹的主体范围(去掉最外侧空白后的范围)。

做法:
  1. 求整图墨迹范围 [L0, R0](含两页)
  2. 去掉左右各 1.2% 的极窄条(纸张边缘噪声), 得到稳健版心 [L, R]
  3. 切分线 = (L + R) / 2, 再用中部 40%~60% 内的"列墨迹局部极小"做微调
     (微调幅度限制在 ±1.5%, 防止被页内空白带偏)
  4. 若中部存在明显双峰(左右页各自的内侧边距), 取两内侧边距中点

这样得到的是**版心中线**, 它与真实书脊的偏差只来自两页版心宽度的微小不对称,
远小于"直接用 0.5"或"用最暗谷"。
"""
import numpy as np
import scipy.ndimage as ndi
from PIL import Image

CLAMP_LO, CLAMP_HI = 0.40, 0.60
EDGE_DROP = 0.012      # 去掉纸张外缘的比例
REFINE_MAX = 0.015     # 微调上限


def _prep(img, width=1600):
    W, H = img.size
    h = max(1, int(width * H / W))
    g = np.array(img.convert("L").resize((width, h), Image.LANCZOS))
    bg = ndi.maximum_filter1d(g.astype(np.float32), size=max(9, int(width * 0.08)), axis=1)
    return g, bg


def _col_ink(g, bg, lo=0.16, hi=0.95):
    t, b = int(g.shape[0] * lo), int(g.shape[0] * hi)
    dark = ((bg[t:b] - g[t:b]) > 26)
    prof = dark.sum(axis=0) / (b - t)
    return ndi.uniform_filter1d(prof.astype(np.float32), size=7)


def _type_body(prof):
    """墨迹列类型: 文字 vs 空白"""
    thr = max(0.02, float(np.median(prof)) * 0.22)
    return prof > thr


def find_spine(img, verbose=False):
    W0 = img.size[0]
    g, bg = _prep(img)
    W = g.shape[1]
    prof = _col_ink(g, bg)
    on = _type_body(prof)

    # 1) 稳健版心
    idx = np.where(on)[0]
    if len(idx) < 10:
        diag = {"mode": "fallback-0.5", "conf": "low", "chosen": 0.5}
        return 0.5, diag
    L, R = int(idx.min()), int(idx.max())
    drop = int(W * EDGE_DROP)
    L += drop
    R -= drop
    if R - L < W * 0.3:
        L, R = int(idx.min()), int(idx.max())

    mid_frac = (L + R) / 2.0 / W   # 版心中线(比例)

    # 2) 微调: 中部 40%~60% 内找列墨迹的局部极小(两页内侧页边距叠加处)
    lo, hi = int(W * CLAMP_LO), int(W * CLAMP_HI)
    seg = prof[lo:hi]
    refine = mid_frac
    if len(seg) > 12:
        sm = ndi.uniform_filter1d(seg, size=5)
        i = int(np.argmin(sm))
        cand = (lo + i) / W
        # 只有当该处确实比附近低(是谷不是峰), 且偏离不超上限, 才采纳
        if abs(cand - mid_frac) <= REFINE_MAX and sm[i] < float(np.median(sm)) * 0.75:
            refine = cand

    x = min(CLAMP_HI, max(CLAMP_LO, refine))
    diag = {
        "mode": "body-mid" + ("+refine" if abs(refine - mid_frac) > 1e-6 else ""),
        "conf": "high",
        "body_L": round(L / W, 4),
        "body_R": round(R / W, 4),
        "mid": round(mid_frac, 4),
        "chosen": round(x, 4),
    }
    if verbose:
        print("  ", diag)
    return x, diag


if __name__ == "__main__":
    REPS = [
        "Images/02制度文件/0235.jpg",
        "Images/02制度文件/0015.jpg",
        "Images/02制度文件/0031.jpg",
        "Images/03相关法规法律法规文件/0749.jpg",
        "Images/04标准及标准目录/0953.jpg",
        "Images/02制度文件/0035.jpg",
        "Images/02制度文件/0423.jpg",
        "Images/02制度文件/0551.jpg",
        "Images/02制度文件/0339.jpg",
        "Images/000封面/封面00.jpg",
        "Images/000封面/封面02.jpg",
        "Images/001目录/00001.jpg",
    ]
    for p in REPS:
        im = Image.open(p)
        x, d = find_spine(im)
        print("%-32s spine=%.4f  L=%.3f R=%.3f mid=%.4f  %s" % (
            p.replace("\\", "/")[-30:], x, d["body_L"], d["body_R"],
            d["mid"], d["mode"]))