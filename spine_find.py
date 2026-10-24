"""书脊定位 v5(最终): 用书眉的 >>> / <<< 标记 + 版心中线 联合定位。

关键事实(经 OCR 实测):
  - 书眉只出现在页面顶部 3%~10%, 且**紧贴该页的上边缘**;
  - 左页书眉形如  "234 | 饲料法规文件 (2023) >>>"  -> >>> 靠右端
  - 右页书眉形如  "<<< 二、制度文件 | 235"          -> <<< 靠左端
  - 书脊 = 左页书眉右端 与 右页书眉左端 之间。

因此:
  1. 只取**最上方** 2.5%~8% 的窄带(避开正文), OCR 后找 >>> 与 <<<;
  2. >>> 的 x 即左页书眉右端, <<< 的 x 即右页书眉左端, 中点为书脊;
  3. 若只找到一侧, 用该侧页码/章节名的位置 + 版心宽度推算另一侧;
  4. 全部失败则回退版心中线(v3)。
"""
import re
import numpy as np
import scipy.ndimage as ndi
from PIL import Image

HDR_BAND = (0.020, 0.100)      # 书眉带(实测 4%~9%, 留余量)
FALLBACK_LO, FALLBACK_HI = 0.40, 0.60
REFINE_MAX = 0.02
PAGENO_RE = re.compile(r"^\s*\d{1,4}\s*$")
# 人字标记: OCR 常把 <<< 误读成 >>>, 因此两者一视同仁
CHEV = re.compile(r"[<>]{2,}")


def _prep(img, width=1600):
    W, H = img.size
    h = max(1, int(width * H / W))
    g = np.array(img.convert("L").resize((width, h), Image.LANCZOS))
    bg = ndi.maximum_filter1d(g.astype(np.float32), size=max(9, int(width * 0.08)), axis=1)
    return g, bg


def _body_mid(img):
    """版心中线(含列墨迹谷微调) —— v3 的稳定回退"""
    g, bg = _prep(img)
    W = g.shape[1]
    t, b = int(g.shape[0] * 0.16), int(g.shape[0] * 0.95)
    dark = ((bg[t:b] - g[t:b]) > 26)
    prof = ndi.uniform_filter1d((dark.sum(axis=0) / (b - t)).astype(np.float32), size=7)
    thr = max(0.02, float(np.median(prof)) * 0.22)
    idx = np.where(prof > thr)[0]
    if len(idx) < 10:
        return 0.5, {"mode": "fallback"}
    L, R = int(idx.min()) + int(W * 0.012), int(idx.max()) - int(W * 0.012)
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
        if abs(cand - mid) <= REFINE_MAX and sm[i] < float(np.median(sm)) * 0.75:
            out = cand
    return min(FALLBACK_HI, max(FALLBACK_LO, out)), {"body_mid": round(mid, 4)}


def _hdr_boxes(engine, img, scale=0.5):
    W, H = img.size
    a, b = HDR_BAND
    band = img.crop((0, int(H * a), W, int(H * b)))
    if band.height < 6:
        return []
    arr = np.array(band.resize((max(8, int(W * scale)), max(6, int(band.height * scale))),
                               Image.LANCZOS))
    res, _ = engine(arr)
    out = []
    for bx, t, sc in (res or []):
        t = t.strip()
        if sc < 0.45 or not t:
            continue
        xs = [c[0] for c in bx]
        out.append({"x0": min(xs) / scale / W, "x1": max(xs) / scale / W,
                    "t": t, "s": float(sc)})
    return out


def find_spine(img, engine=None, verbose=False):
    """返回 (书脊比例, 诊断)"""
    diag = {}
    fbx, fbd = _body_mid(img)
    diag.update(fbd)
    diag["fallback"] = round(fbx, 4)

    if engine is not None:
        try:
            boxes = _hdr_boxes(engine, img)
        except Exception as e:
            boxes = []
            diag["ocr_err"] = str(e)[:60]
        # 书脊定位策略(经 OCR 实测校准):
        #   左页书眉整体在 x≈0.05~0.24, 右页书眉整体在 x≈0.77~0.95。
        #   人字标记(>>> / <<<) 位于各自书眉的**外端**, 并非靠近书脊,
        #   因此不能用它直接夹出书脊。
        #   真正可靠的是: 把书眉里属于"左页"的文字块 与 "右页"的文字块分开,
        #   两侧文字块的内缘(lx / rx)之间夹着书脊。
        chevs = [b for b in boxes if CHEV.search(b["t"])]
        diag["n_chev"] = len(chevs)

        # 书眉文字块: 排除误入的正文行(正文块通常很长且不含书眉特征)
        hdr_like = [b for b in boxes
                    if len(b["t"]) <= 12 and not re.search(r"[。；，,]", b["t"])]
        left_blk = [b for b in hdr_like if b["x1"] < 0.45]
        right_blk = [b for b in hdr_like if b["x0"] >= 0.55]
        if left_blk and right_blk:
                        lx = max(b["x1"] for b in left_blk)
                        rx = min(b["x0"] for b in right_blk)
                        diag.update({"left_x1": round(lx, 4), "right_x0": round(rx, 4),
                                     "n_left": len(left_blk), "n_right": len(right_blk)})
                        # 两块之间必须夹住中线附近: lx < 0.5 < rx,
                        # 且 lx 不能太靠右(否则说明左页块识别错误)
                        if lx < 0.48 and rx > 0.52 and rx > lx:
                            x = (lx + rx) / 2.0
                            diag.update({"mode": "hdr-blocks", "conf": "high",
                                         "chosen": round(x, 4)})
                            if verbose:
                                print("  ", diag)
                            return min(FALLBACK_HI, max(FALLBACK_LO, x)), diag

        # 只识别到单侧时无法可靠推算另一侧(实测误差 >9%), 直接放弃并回退。
        # 理由: 内侧页边距在不同页面差异很大(有的贴排版0.2%, 有的留白3%),
        # 单侧信息不足以定位书脊。
    diag.update({"mode": "body-mid", "conf": "mid", "chosen": round(fbx, 4)})
    if verbose:
        print("  ", diag)
    return fbx, diag


if __name__ == "__main__":
    from rapidocr_onnxruntime import RapidOCR
    eng = RapidOCR()
    REPS = [
        "Images/02制度文件/0035.jpg",
        "Images/02制度文件/0423.jpg",
        "Images/02制度文件/0015.jpg",
        "Images/02制度文件/0551.jpg",
        "Images/02制度文件/0235.jpg",
        "Images/02制度文件/0339.jpg",
        "Images/03相关法规法律法规文件/0749.jpg",
        "Images/04标准及标准目录/0953.jpg",
    ]
    for p in REPS:
        im = Image.open(p)
        x, d = find_spine(im, eng)
        print("%-30s spine=%.4f  %-9s conf=%-5s L=%.3f R=%.3f" % (
            p.replace("\\", "/")[-28:], x, d.get("mode"), d.get("conf"),
            d.get("left_x1", 0), d.get("right_x0", 0)))