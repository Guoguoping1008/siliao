"""书脊定位 v4: 用页眉页码的 OCR 位置反推。

原理:
  书眉形如  "<<< 二、制度文件 | 423"   (右页, 左端有 <<<)
          "422 | 饲料法规文件 (2023) >>>" (左页, 右端有 >>>)
  左页页眉的**右端**与右页页眉的**左端**之间就是书脊。
  OCR 能精确给出这两个文本框的 x 范围, 两者之间取中点即为书脊。

这是唯一无歧义的信号: 页码是孤立数字, 不会被正文干扰;
且左右页码位置天然对称, 可互相校验。

对没有页眉/OCR 失败的页, 回退到 v3 的版心中线。
"""
import re
import numpy as np
import scipy.ndimage as ndi
from PIL import Image

# 页眉带: 高度比例(实测书眉在 4%~9%)
HDR_TOP, HDR_BOT = 0.030, 0.115
# 页码: 1~4 位数字
PAGENO_RE = re.compile(r"^\s*\d{1,4}\s*$")
# 页眉特征词(用于确认该行确实是书眉)
HDR_HINT = re.compile(r"(饲料法规文件|相关法律法规文件|制度文件|标准及标准目录|<<<|>>>)")

FALLBACK_LO, FALLBACK_HI = 0.40, 0.60


def _prep(img, width=1600):
    W, H = img.size
    h = max(1, int(width * H / W))
    g = np.array(img.convert("L").resize((width, h), Image.LANCZOS))
    bg = ndi.maximum_filter1d(g.astype(np.float32), size=max(9, int(width * 0.08)), axis=1)
    return g, bg


def _col_ink(g, bg, lo=0.16, hi=0.95):
    t, b = int(g.shape[0] * lo), int(g.shape[0] * hi)
    dark = ((bg[t:b] - g[t:b]) > 26)
    return ndi.uniform_filter1d((dark.sum(axis=0) / (b - t)).astype(np.float32), size=7)


def _body_mid(img):
    """v3: 版心中线(含微调)"""
    g, bg = _prep(img)
    W = g.shape[1]
    prof = _col_ink(g, bg)
    thr = max(0.02, float(np.median(prof)) * 0.22)
    idx = np.where(prof > thr)[0]
    if len(idx) < 10:
        return 0.5, {"mode": "fallback"}
    L, R = int(idx.min()), int(idx.max())
    drop = int(W * 0.012)
    L, R = L + drop, R - drop
    if R - L < W * 0.3:
        L, R = int(idx.min()), int(idx.max())
    mid = (L + R) / 2.0 / W
    lo, hi = int(W * FALLBACK_LO), int(W * FALLBACK_HI)
    seg = prof[lo:hi]
    out = mid
    if len(seg) > 12:
        sm = ndi.uniform_filter1d(seg, size=5)
        i = int(np.argmin(sm))
        cand = (lo + i) / W
        if abs(cand - mid) <= 0.015 and sm[i] < float(np.median(sm)) * 0.75:
            out = cand
    return min(FALLBACK_HI, max(FALLBACK_LO, out)), {"mode": "body-mid", "mid": round(mid, 4)}


def _header_boxes(engine, img, scale=0.5):
    """OCR 页眉带, 返回 [(x0,x1,text,...)] 坐标归一到原图比例"""
    W, H = img.size
    band = img.crop((0, int(H * HDR_TOP), W, int(H * HDR_BOT)))
    a = np.array(band.resize((int(W * scale), int(band.height * scale)), Image.LANCZOS))
    res, _ = engine(a)
    boxes = []
    for b, t, sc in (res or []):
        t = t.strip()
        if sc < 0.5 or not t:
            continue
        xs = [c[0] for c in b]; ys = [c[1] for c in b]
        boxes.append({"x0": min(xs) / scale / W, "x1": max(xs) / scale / W,
                      "t": t, "s": float(sc)})
    return boxes


def find_spine(img, engine=None, verbose=False):
    """返回 (书脊比例, 诊断)。优先页码法, 失败回退版心中线。"""
    diag = {}
    if engine is not None:
        try:
            boxes = _header_boxes(engine, img)
        except Exception as e:
            boxes = []
            diag["ocr_err"] = str(e)
        # 确认存在书眉
        hdr = [b for b in boxes if HDR_HINT.search(b["t"])]
        diag["n_hdr"] = len(hdr)
        if hdr:
            # 纯数字页码框
            nums = [b for b in boxes if PAGENO_RE.match(b["t"])]
            diag["nums"] = [(round(b["x0"], 3), b["t"]) for b in nums]
            if len(nums) >= 2:
                left_side = [b for b in nums if b["x0"] < 0.5]
                right_side = [b for b in nums if b["x0"] >= 0.5]
                if left_side and right_side:
                    lx = max(b["x1"] for b in left_side)
                    rx = min(b["x0"] for b in right_side)
                    if rx > lx:
                        x = (lx + rx) / 2.0
                        diag.update({"mode": "pageno", "conf": "high",
                                     "left_x1": round(lx, 4), "right_x0": round(rx, 4),
                                     "chosen": round(x, 4)})
                        if verbose:
                            print("  ", diag)
                        return x, diag

    x, d2 = _body_mid(img)
    diag.update(d2)
    diag.setdefault("conf", "mid")
    if verbose:
        print("  ", diag)
    return x, diag