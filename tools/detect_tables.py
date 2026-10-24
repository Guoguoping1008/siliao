"""Find pages that contain real tables by detecting printed ruling lines.

RapidOCR has no layout model, so table detection is done on the pixels: a
table shows long horizontal/vertical strokes, which OCR boxes alone cannot
reveal. Pages flagged here are the ones worth a vision-model pass.
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

IMAGES = Path("E:/workspace/siliao/Images")
WORK = Path("E:/workspace/siliao/work")
CACHE = json.loads((WORK / "ocr_raw.json").read_text(encoding="utf-8"))


def imread_unicode(path):
    """cv2.imread cannot handle non-ASCII paths on Windows."""
    import numpy as np
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
        return img
    except Exception:
        return None


def has_ruling(path):
    img = imread_unicode(path)
    if img is None:
        return 0, 0
    h, w = img.shape

    # Scan BOTH leaves. A spread may carry tables on the left leaf only, and
    # scanning just the right half silently drops them.
    scale = 1200.0 / max(w, 1)
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    # Deskew first: photos shot at an angle hide ruling lines from a
    # fixed-axis morphological filter, which silently drops whole tables.
    img = deskew(img)

    left = img[:, :int(img.shape[1] * 0.52)]
    right = img[:, int(img.shape[1] * 0.48):]
    lh, lv = rules_in(left)
    rh, rv = rules_in(right)
    return int(lh + rh), int(lv + rv)


def rules_in(img):
    bw = cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                               cv2.THRESH_BINARY_INV, 25, 12)
    hor = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (60, 1)))
    ver = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 30)))
    ah, ch = contour_area(hor)
    av, cv_ = contour_area(ver)
    return ah + av, ch + cv_


def deskew(img):
    """Rotate the page so text lines are horizontal.

    Estimates the dominant text angle from the image's own projection profile.
    """
    small = img
    if max(small.shape) > 900:
        s = 900.0 / max(small.shape)
        small = cv2.resize(small, (int(small.shape[1] * s), int(small.shape[0] * s)))
    inv = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    best, best_score = 0.0, -1
    # only small corrections are expected from a handheld shot
    for angle in np.arange(-8, 8.1, 0.5):
        M = cv2.getRotationMatrix2D((small.shape[1] / 2, small.shape[0] / 2), angle, 1.0)
        rot = cv2.warpAffine(inv, M, (small.shape[1], small.shape[0]),
                             flags=cv2.INTER_NEAREST, borderValue=0)
        proj = rot.sum(axis=1, dtype=np.float64)
        score = float(((proj[1:] - proj[:-1]) ** 2).sum())
        if score > best_score:
            best_score, best = score, angle
    if abs(best) < 0.4:
        return img
    h, w = img.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), best, 1.0)
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


def contour_area(mask):
    """(stroke area, count of long rules) for horizontal and vertical strokes.

    Counting rules beats measuring area: dense CJK text also produces
    vertical-stroke noise, but only a table stacks many parallel rules.
    """
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    area_h = area_v = cnt_h = cnt_v = 0
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA]
        cw = stats[i, cv2.CC_STAT_WIDTH]
        ch = stats[i, cv2.CC_STAT_HEIGHT]
        if cw > 150 and ch < 40:      # long thin horizontal rule
            area_h += area
            cnt_h += 1
        if ch > 120 and cw < 40:      # long thin vertical rule
            area_v += area
            cnt_v += 1
    return area_h + area_v, cnt_h + cnt_v


def main():
    keys = sorted(CACHE)
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    end = int(sys.argv[2]) if len(sys.argv) > 2 else len(keys)
    out = WORK / "table_scan.json"
    res = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}

    for i, key in enumerate(keys[start:end], start + 1):
        if key in res:
            continue
        try:
            area, rules = has_ruling(IMAGES / key)
        except Exception:
            area, rules = 0, 0
        # Cover art is full of long decorative strokes; only scan body pages.
        is_cover = key.startswith("000封面")
        res[key] = {"area": area, "rules": rules, "cover": is_cover}
        if i % 25 == 0:
            out.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
            print(f"{i}/{len(keys)}", flush=True)

    out.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")

    # Measured separation on this corpus: plain prose yields 7-8 long rules,
    # real tables 21-68. 14 sits in the empty gap between the two.
    hits = [k for k, v in res.items() if v["rules"] >= 14 and not v.get("cover")]
    print("pages with tables:", len(hits), "/", len(res))
    for k in hits[:40]:
        print("  ", k, res[k])


if __name__ == "__main__":
    main()