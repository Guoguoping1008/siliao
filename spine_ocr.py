"""用 OCR 文字框反推书脊 —— 每个页面的正文块都有确定的外边界。

可靠依据:
  - 左页正文块的**右缘**(最靠右的文字框) = 左页排版右边界
  - 右页正文块的**左缘**(最靠左的文字框) = 右页排版左边界
  - 书脊落在这两者之间, 且与两页外边距对称性一致。

比"找空白沟"可靠, 因为:
  1. 文字框位置是 OCR 直接给出的, 不受纸面明暗影响
  2. 排版边界是印刷决定的, 稳定
  3. 可以在**上下两个区域**分别计算 -> 得到斜书脊的两个端点

做法:
  1. 对整页 OCR, 取文本框
  2. 用 x 投影做聚类, 分成左右两组(以 0.5 为界, 但允许跨过)
  3. 上半部分计算 (left_max_x1, right_min_x0), 下半部分同理
  4. 书脊上端 = 上半组的中点, 下端 = 下半组的中点
"""
import re
import numpy as np
from PIL import Image

# 明显的非正文噪声: 页码/页眉残留
NOISE = re.compile(r"^[\s\d\W]{0,6}$")
HDRWORD = re.compile(r"(饲料法规文件|相关法律法规文件|制度文件|标准及标准目录|[<>]{2,})")


def ocr_boxes(engine, img, scale=0.5, min_score=0.5, skip_header=True):
    W, H = img.size
    s = img.resize((int(W * scale), int(H * scale)), Image.LANCZOS)
    res, _ = engine(s)
    out = []
    for b, t, sc in (res or []):
        t = t.strip()
        if sc < min_score or len(t) < 2:
            continue
        if NOISE.match(t):
            continue
        if skip_header and HDRWORD.search(t):
            continue
        xs = [c[0] for c in b]; ys = [c[1] for c in b]
        out.append({"x0": min(xs) / scale / W, "x1": max(xs) / scale / W,
                    "y0": min(ys) / scale / H, "y1": max(ys) / scale / H,
                    "t": t, "s": float(sc)})
    return out


def _split_lr(boxes, y_lo, y_hi, margin=0.02):
    """在纵向区间内, 把文本框分成左/右两组。
    返回 (left_x1, right_x0) 或 None。

    注意: margin 必须很小。之前用 0.30 会让右页的框也落进左组,
    导致 lx 越过书脊、rx 退回左页, 结果完全颠倒。
    """
    sel = [b for b in boxes
           if b["y1"] >= y_lo and b["y0"] <= y_hi]
    if len(sel) < 6:
        return None
    # 先按 x 的最大间隙分成两簇
    xs = sorted(b["x0"] for b in sel)
    gaps = [(xs[i + 1] - xs[i], i) for i in range(len(xs) - 1)]
    g, i = max(gaps)
    if g < 0.03:
        return None
    cut = (xs[i] + xs[i + 1]) / 2.0
    left = [b for b in sel if b["x1"] <= cut + margin]
    right = [b for b in sel if b["x0"] >= cut - margin]
    if len(left) < 3 or len(right) < 3:
        return None
    # 校验: 两组不能交叉(left 组不能伸到 right 组右边)
    lx = max(b["x1"] for b in left)
    rx = min(b["x0"] for b in right)
    if rx <= lx:
        return None
    return lx, rx


def find_spine_line(engine, img, nseg=3, verbose=False):
    """返回 {x_top, x_bot, slope, mode, conf, samples}"""
    boxes = ocr_boxes(engine, img)
    diag = {"n_boxes": len(boxes)}
    if len(boxes) < 8:
        return {"mode": "no-box", "x_top": 0.5, "x_bot": 0.5, "slope": 0.0}

    samples = []
    for k in range(nseg):
        y_lo = 0.10 + (0.80 / nseg) * k
        y_hi = 0.10 + (0.80 / nseg) * (k + 1)
        r = _split_lr(boxes, y_lo, y_hi)
        if r is None:
            continue
        lx, rx = r
        if rx <= lx or rx - lx > 0.40:
            continue
        ymid = (y_lo + y_hi) / 2.0
        samples.append({"y": ymid, "x": (lx + rx) / 2.0, "lx": lx, "rx": rx})
    diag["n_seg"] = len(samples)

    if len(samples) < 2:
        if samples:
            x = float(np.median([s["x"] for s in samples]))
            diag.update({"mode": "median", "x_top": x, "x_bot": x, "slope": 0.0})
            return diag
        return {"mode": "none", "x_top": 0.5, "x_bot": 0.5, "slope": 0.0}

    if len(samples) == 2:
        k = (samples[-1]["x"] - samples[0]["x"]) / (samples[-1]["y"] - samples[0]["y"])
        b0 = samples[0]["x"] - k * samples[0]["y"]
    else:
        ys = np.array([s["y"] for s in samples])
        xs = np.array([s["x"] for s in samples])
        k, b0 = np.polyfit(ys, xs, 1)

    diag.update({
        "mode": "ocr-lines",
        "x_top": float(b0),
        "x_bot": float(b0 + k),
        "slope": float(k),
        "samples": [(round(s["y"], 2), round(s["x"], 4)) for s in samples],
        "conf": "high" if len(samples) >= 3 else "mid",
    })
    if verbose:
        print("   ", diag)
    return diag


def x_at(diag, y_frac):
    xt = diag.get("x_top", 0.5)
    xb = diag.get("x_bot", 0.5)
    return xt + (xb - xt) * max(0.0, min(1.0, y_frac))


if __name__ == "__main__":
    import sys
    sys.path.insert(0, r"E:/workspace/siliao")
    from rapidocr_onnxruntime import RapidOCR
    from PIL import Image
    import spine_eval

    eng = RapidOCR()
    print("%-30s %-7s %-8s %-8s %-8s %s" %
          ("file", "truth", "x_top", "x_bot", "mid", "mode"))
    errs = []
    for f, (truth, _why) in spine_eval.GROUND_TRUTH.items():
        im = Image.open(r"E:/workspace/siliao/" + f)
        d = find_spine_line(eng, im)
        mid = x_at(d, 0.5)
        e = mid - truth
        errs.append((abs(e), f))
        print("%-30s %.3f   %.4f   %.4f   %.4f  %s" % (
            f.replace("\\", "/")[-28:], truth, d.get("x_top"),
            d.get("x_bot"), mid, d.get("mode")))
    errs.sort(reverse=True)
    mae = sum(e for e, _ in errs) / len(errs)
    print("\n中部 MAE = %.4f   最大 = %.4f" % (mae, errs[0][0]))
    print("最差:", errs[0][1].replace("\\", "/"))