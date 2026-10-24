"""Repair pages whose top-of-page body lines RapidOCR's detector missed.

On this corpus the detector silently skips a line now and then, most often the
first one or two body lines under the running head (dark shadow near the book's
gutter curve). Slicing the page into thin horizontal bands and OCR-ing each
band separately recovers them at high confidence.

Output is a JSON patch keyed by image path; gen_md.py can merge it, so this
never rewrites a page that is already correct.
"""
import json
import re
import sys
from pathlib import Path

from PIL import Image
import numpy as np
from rapidocr_onnxruntime import RapidOCR

WORK = Path("E:/workspace/siliao/work")
IMAGES = Path("E:/workspace/siliao/Images")
OUT = WORK / "band_patch.json"

BAND = 85          # px tall slices on a ~3439px page
GAP = 3


def band_ocr(ocr, img, y0, y1, x0=0, x1=None, min_score=0.60):
    """OCR one horizontal slice of one leaf; return list of box dicts."""
    if x1 is None:
        x1 = img.width
    crop = img.crop((x0, y0, x1, y1))
    res, _ = ocr(crop)
    out = []
    for box, text, score in (res or []):
        if score < min_score:
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]          # slice-local y
        out.append({
            "text": text.strip(),
            "score": round(float(score), 3),
            "x": round(sum(xs) / len(xs) + x0, 1),
            "x0": round(min(xs) + x0, 1),
            "x1": round(max(xs) + x0, 1),
            "y": round(sum(ys) / len(ys) + y0, 1),   # back to page coords
            "y0": round(min(ys) + y0, 1),
            "y1": round(max(ys) + y0, 1),
        })
    return out


def find_gaps(lines, img_w, min_gap=95.0):
    """Vertical gaps bigger than a normal line pitch -> detector dropped text.

    Normal body leading on this corpus is ~70px, so a gap of 95px+ means
    whole lines were missed. Each leaf is examined on its own: a gap that is
    small on the left page can be masked by lines on the right page at the
    same height, and vice versa.
    """
    spans = []
    for side in (0, 1):
        if side == 0:
            sub = [l for l in lines if l["x"] < img_w * 0.48]
        else:
            sub = [l for l in lines if l["x"] >= img_w * 0.48]
        ys = sorted(l["y"] for l in sub)
        for a, b in zip(ys, ys[1:]):
            if b - a >= min_gap:
                spans.append((a, b, side))
    return spans


def text_bands(img, x0, x1, y0, y1, thr=10):
    """Row spans that contain ink, so each crop hugs real text.

    A missed run of text often merges into one tall ink blob; the detector
    needs roughly one text line per crop to fire.
    """
    a = np.array(img.crop((x0, y0, x1, y1)))
    dark = (a < 128).sum(axis=1)
    spans, start = [], None
    for i, v in enumerate(dark):
        if v > thr and start is None:
            start = i
        elif v <= thr and start is not None:
            if i - start > 10:
                spans.append((start + y0, i + y0))
            start = None
    if start is not None and len(dark) - start > 10:
        spans.append((start + y0, len(dark) + y0))
    return spans


def split_band(a, bs, be, line_h=72):
    """Split a tall ink blob into line-height slices.

    A missed run merges into one blob; the detector needs one line per crop.
    Line pitch on this corpus is ~70px, so slice anything much taller.
    """
    if be - bs <= line_h * 1.5:
        return [(bs, be)]
    out = []
    n = max(1, round((be - bs) / line_h))
    step = (be - bs) / n
    for i in range(n):
        out.append((int(bs + i * step), int(bs + (i + 1) * step)))
    return out


def repair_page(ocr, key, img, existing, min_gap=95.0):
    """Re-OCR only the missed spans; keep the clean existing lines.

    The band may also cover the opposite leaf (a running head at the same
    height), so keep only boxes on the same side of the gutter as the lines
    surrounding the gap.
    """
    added = []
    seen_gap = set()
    h = img.height
    for y0, y1, side in find_gaps(existing, img.width, min_gap):
        # Only the top of the leaf is repaired. The misses are the first
        # lines under the running head; deeper gaps are paragraph spacing,
        # table rows or genuine blank space, and re-reading them injects
        # garbled fragments.
        if y0 > h * 0.55:
            continue
        # A page with real blank space (chapter starts, part openers) is left
        # alone: the ink-band scan below finds nothing there anyway.
        ya = max(0, int(y0 - 20))
        yb = min(int(h * 0.55), int(y1 + 170))
        if yb - ya < 30:
            continue
        key_gap = (side, round(y0 / 50))
        if key_gap in seen_gap:
            continue
        seen_gap.add(key_gap)

        # OCR the gap leaf-by-leaf and line-by-line. A single wide crop merges
        # the missed lines into a tall ink blob and the detector skips it;
        # crops that hug one text line recover it at 0.99 confidence.
        x0 = 0 if side == 0 else int(img.width * 0.48)
        x1 = int(img.width * 0.52) if side == 0 else img.width
        got = []
        for (bs, be) in text_bands(img, x0, x1, ya, yb):
            for (ls, le) in split_band(None, bs, be):
                # padding so ascenders/descenders stay inside the crop
                got += band_ocr(ocr, img, max(0, ls - 16),
                                min(img.height, le + 16), x0=x0, x1=x1,
                                min_score=0.90)
        have = {l["text"] for l in existing}
        for g in got:
            t = g["text"]
            # A real body line on this corpus runs 20+ chars. Anything shorter
            # is a cropped fragment (the line straddled the crop edge).
            if len(t) < 20 or t in have:
                continue
            if side == 0 and g["x"] > img.width * 0.5:
                continue           # opposite leaf
            if side == 1 and g["x"] < img.width * 0.5:
                continue
            if is_header_text(t):
                continue           # running head / folio caught by the band
            if any(abs(g["y"] - e["y"]) < 25 and abs(g["x"] - e["x"]) < 120
                   for e in existing):
                continue           # garbled duplicate of a known line
            g["recovered"] = True
            added.append(g)
    return added


def is_header_text(t):
    n = re.sub(r"\s+", "", t)
    if "<<<" in t or ">>>" in t:
        return True
    if re.fullmatch(r"\d{1,4}", n):
        return True
    if re.match(r"^\d{0,4}[一二三四五六七八九十]{0,3}[、，]?$", n):
        return True
    if "饲料法规文件" in n:
        return True
    if re.match(r"^[（(]\d{4}[）)]$", n):
        return True
    return False


def main():
    keys = sys.argv[1:] or ["01法规/0005.jpg"]
    ocr = RapidOCR()
    cache = json.loads((WORK / "ocr_raw.json").read_text(encoding="utf-8"))
    patch = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}

    for key in keys:
        img = Image.open(IMAGES / key).convert("L")
        existing = cache.get(key, {}).get("lines", [])
        added = repair_page(ocr, key, img, existing)
        patch[key] = added
        OUT.write_text(json.dumps(patch, ensure_ascii=False), encoding="utf-8")
        print(f"{key}: +{len(added)} recovered lines", flush=True)
        for g in sorted(added, key=lambda g: g["y"]):
            print(f"    y={g['y']:>5.0f} sc={g['score']} | {g['text'][:64]}")


if __name__ == "__main__":
    main()