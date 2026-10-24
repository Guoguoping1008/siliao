"""
二级 OCR: 针对"稀疏页"(检测框数偏少 => RapidOCR 把多行合并成一个框而丢行)。

策略: 把丢行页按水平横条切分, 每条高度 < 单行行距, 逐条识别。
横条边界用"投影找行中心"对齐, 避免把同一行切成两半。
"""
import os, sys, json, time, argparse
import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ocr_batch as ob


def find_line_bands(gray_np, nw, min_run=6, gap_frac=0.25):
    """用局部对比(减去背景)的水平投影找墨迹行带, 返回 [(y0,y1), ...]"""
    import scipy.ndimage as ndi
    bg = ndi.maximum_filter(gray_np, size=(31, 31))
    diff = (bg - gray_np).astype(np.float32)
    prof = (diff > 25).sum(axis=1).astype(np.float32)
    if prof.max() <= 0:
        return []
    thr = prof.max() * gap_frac
    runs, start = [], None
    for y in range(len(prof)):
        if prof[y] > thr:
            if start is None:
                start = y
        else:
            if start is not None:
                runs.append((start, y))
            start = None
    if start is not None:
        runs.append((start, len(prof)))
    return [(a, b) for a, b in runs if b - a >= min_run]


def ocr_page_strip(engine, path, header_crop=ob.HEADER_CROP, scale=0.85, overlap=0.55):
    """横条式 OCR: 先投影找行带, 再把相邻 1~2 行合成一条送 OCR。"""
    im = Image.open(path).convert("RGB")
    W, H = im.size
    ch = int(H * header_crop)
    body = im.crop((0, ch, W, H))
    bh = body.height
    gray = np.array(body.convert("L").resize((int(W * scale), int(bh * scale)), Image.LANCZOS))
    bands = find_line_bands(gray, gray.shape[1])
    if not bands:
        return []
    # 每条 = 一个墨迹行带, 上下各扩展半个行距
    heights = [b - a for a, b in bands]
    pitch = float(np.median(heights)) if heights else 20.0
    pad = max(4, int(pitch * overlap))

    lines = []
    used = []          # 已消费的墨迹带区间, 用于跨页去重
    for a, b in bands:
        if any(not (b <= ua or a >= ub) for ua, ub in used):
            continue
        used.append((a, b))
        y0 = max(0, a - pad)
        y1 = min(bh, b + pad)
        strip = body.crop((0, y0, W, y1))
        arr = np.array(strip.resize((int(W * scale), int((y1 - y0) * scale)), Image.LANCZOS))
        res, _ = engine(arr)
        best = None
        for bx, txt, sc in (res or []):
            txt = txt.strip()
            if sc < 0.4 or not txt:
                continue
            xs = [c[0] for c in bx]; ys = [c[1] for c in bx]
            area = (max(xs) - min(xs)) * (max(ys) - min(ys))
            if best is None or area > best[0]:
                best = (area, min(xs), max(xs), txt, float(sc))
        if best:
            lines.append({"y0": float(a), "y1": float(b),
                          "x0": best[1], "x1": best[2], "t": best[3], "s": best[4]})
    lines.sort(key=lambda i: (i["y0"], i["x0"]))
    return lines


def strip_to_paras(lines, nw):
    if not lines:
        return []
    med_len = max(1.0, float(np.median([len(i["t"]) for i in lines])))
    font_w = max(6.0, nw * 0.012)
    gx = None
    xs = sorted(i["x0"] for i in lines)
    if len(xs) >= 6:
        # 用中位分界
        mid = np.median(xs)
        gx = mid
    if gx is None:
        cols = [lines]
    else:
        left = [i for i in lines if i["x1"] <= gx]
        right = [i for i in lines if i["x0"] >= gx - font_w]
        rid = {id(i) for i in right}
        left = [i for i in left if id(i) not in rid]
        cols = [left, right]
    paras = []
    for col in cols:
        if not col:
            continue
        paras.extend(ob.merge_rows_to_paras(ob.to_rows(col, nw, nw), font_w))
    return paras


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default="E:/workspace/siliao/Markdown/_ocr_report.json")
    ap.add_argument("--images", default="E:/workspace/siliao/Images")
    ap.add_argument("--out", default="E:/workspace/siliao/Markdown")
    ap.add_argument("--threshold", type=int, default=30,
                    help="框数低于此值判定为稀疏页")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(args.report, encoding="utf-8") as f:
        log = json.load(f)
    sparse = [r for r in log if r.get("ok") and r.get("boxes", 999) < args.threshold]
    sparse.sort(key=lambda r: r["boxes"])
    print(f"[scan] total={len(log)} sparse(<{args.threshold})={len(sparse)}")
    for r in sparse[:15]:
        print(f"   boxes={r['boxes']:3d}  {r['src']}")
    if args.dry_run:
        return
    if args.limit:
        sparse = sparse[:args.limit]

    engine = RapidOCR()
    t0 = time.time()
    fixed = 0
    for i, r in enumerate(sparse, 1):
        src = os.path.join(args.images, r["src"])
        if not os.path.exists(src):
            print(f"  missing {src}")
            continue
        try:
            lines = ocr_page_strip(engine, src)
            paras = strip_to_paras(lines, 1000)
        except Exception as e:
            print(f"  ERR {r['src']}: {e}")
            continue
        if not paras:
            continue
        title = ob.pick_title(paras)
        body = [p for p in paras if p.strip() and p.strip() != title]
        lines_out = []
        if title:
            lines_out += [f"# {title}", ""]
        seen = set()
        for p in body:
            p = p.strip()
            if not p or p in seen:
                continue
            seen.add(p)
            lines_out += [p, ""]
        text = "\n".join(lines_out).rstrip() + "\n"
        outp = os.path.join(args.out, os.path.splitext(r["src"])[0] + ".md")
        if len(text) > len(open(outp, encoding="utf-8").read()) * 1.15:
            with open(outp, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            fixed += 1
            print(f"  [{i}/{len(sparse)}] FIXED {r['src']} ({len(text)} chars)")
        else:
            print(f"  [{i}/{len(sparse)}] keep  {r['src']}")
    print(f"[done] fixed={fixed} elapsed={time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()