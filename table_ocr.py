"""表格页 OCR -> Markdown 表格。

流程:
1. 页眉裁剪(与正文流程一致, 13%)
2. 网格检测: 自适应阈值 -> 横线/竖线投影 -> 行列边界
3. 逐格 OCR -> 按网格组装 -> Markdown 表格(含合并单元格展开)
"""
import os, sys, re, json, argparse, time
import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ocr_batch as ob

HEADER_CROP = 0.13


def binarize(gray, thr=135):
    """固定阈值二值化(扫描件背景偏灰, 不用自适应均值)"""
    return (gray < thr).astype(np.uint8)


def _runs(mask, minlen):
    out, start = [], None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= minlen:
                out.append((start, i - 1))
            start = None
    if start is not None and len(mask) - start >= minlen:
        out.append((start, len(mask) - 1))
    return out


def find_table_bbox(binary, col_thr=0.30, row_thr=0.60):
    """定位表格区域(不含正文段落)。

    跨页扫描件左右分别是正文和表格, 中间是书脊空白沟。
    找到沟后取右半幅, 若其中能检出规则网格即认为是表格页。
    """
    H, W = binary.shape
    colf = binary.sum(axis=0) / H
    med = float(np.median(colf))
    gut = colf < max(0.02, med * 0.15)
    runs_g = _runs(gut, int(W * 0.02))
    best = None
    for a, b in runs_g:
        if a < W * 0.60 and b > W * 0.40 and (b - a) > W * 0.015:
            if best is None or (b - a) > (best[1] - best[0]):
                best = (a, b)
    left = (best[1] + 1) if best else 0

    region = binary[:, left:]
    if region.sum() == 0:
        return None
    hl, vl = find_grid_lines(region, col_thr=col_thr, row_thr=row_thr)
    if len(vl) < 3 or len(hl) < 3:
        return None
    return {"x0": vl[0][0] + left, "x1": vl[-1][1] + left,
            "y0": hl[0][0], "y1": hl[-1][1], "left_page": left}


def find_grid_lines(binary, col_thr=0.30, row_thr=0.60):
    """在表格区域二值图上找横线/竖线。

    两阶段:
    1. 先在整幅上找竖线(竖线贯通度高, 可靠)。
    2. 再在"相邻两竖线之间"的列条内找横线 —— 横线不跨整幅宽度,
       在窄条内才是连续的, 这样才能稳定检出。
    """
    H, W = binary.shape
    colf = binary.sum(axis=0) / H

    def merge(rs, gap=8):
        if not rs:
            return []
        out = [list(rs[0])]
        for a, b in rs[1:]:
            if a - out[-1][1] <= gap:
                out[-1][1] = b
            else:
                out.append([a, b])
        return [tuple(x) for x in out]

    vl = merge(_runs(colf > col_thr, max(3, int(W * 0.004))))
    if len(vl) < 2:
        return [], vl

    # 在每个列条内找横线, 取各列条结果的并集
    hl_all = []
    for i in range(len(vl) - 1):
        xa, xb = vl[i][1] + 1, vl[i + 1][0]
        if xb - xa < 8:
            continue
        strip = binary[:, xa:xb]
        sf = strip.sum(axis=1) / strip.shape[1]
        found = merge(_runs(sf > row_thr, 3))
        hl_all.extend(found)

    hl = merge(sorted(set(hl_all)), gap=12)
    return hl, vl


def ocr_region(engine, img_arr, min_score=0.5):
    """对一个小区域做 OCR, 返回拼接后的文本(竖排文本从上到下拼接)"""
    res, _ = engine(img_arr)
    if not res:
        return ""
    parts = []
    for b, t, sc in (res or []):
        if sc < min_score or not t.strip():
            continue
        ys = [c[1] for c in b]; xs = [c[0] for c in b]
        parts.append((min(ys), min(xs), t.strip()))
    parts.sort()
    return "".join(p[2] for p in parts)


def extract_table(engine, path, header_crop=HEADER_CROP, scale=0.75,
                  pad=8, cell_scale=2.0, verbose=False):
    """返回 dict(title, columns, rows) 或 None。"""
    im = Image.open(path).convert("RGB")
    W, H = im.size
    body = im.crop((0, int(H * header_crop), W, H))

    bw = int(W * scale)
    bh = int(body.height * scale)
    small = body.resize((bw, bh), Image.LANCZOS)
    gray = np.array(small.convert("L"))
    binary = binarize(gray)

    box = find_table_bbox(binary)
    if box is None:
        if verbose:
            print("   [bbox] 未定位到表格区域")
        return None
    if verbose:
        print(f"   [bbox] x={box['x0']}..{box['x1']} y={box['y0']}..{box['y1']}")

    tbin = binary[box["y0"]:box["y1"] + 1, box["x0"]:box["x1"] + 1]
    hl, vl = find_grid_lines(tbin)
    if len(hl) < 3 or len(vl) < 3:
        if verbose:
            print(f"   [grid] hl={len(hl)} vl={len(vl)} -> 非表格")
        return None

    if verbose:
        print(f"   [grid] {len(hl)} 横线 x {len(vl)} 竖线")

    # 单元格边界(在表格局部坐标下)
    r0, r1 = 0, tbin.shape[0] - 1
    c0, c1 = 0, tbin.shape[1] - 1
    rows_y = [int((hl[i][1] + hl[i + 1][0]) / 2) for i in range(len(hl) - 1)]
    cols_x = [int((vl[j][1] + vl[j + 1][0]) / 2) for j in range(len(vl) - 1)]
    if len(rows_y) < 2 or len(cols_x) < 2:
        return None

    # 逐格 OCR: 局部坐标 -> 原图坐标
    table = []
    for ri, ya in enumerate(rows_y):
        yb = rows_y[ri + 1] if ri + 1 < len(rows_y) else r1
        line_cells = []
        for ci, xa in enumerate(cols_x):
            xb = cols_x[ci + 1] if ci + 1 < len(cols_x) else c1
            x0 = box["x0"] + xa
            x1 = box["x0"] + xb
            y0 = box["y0"] + ya
            y1 = box["y0"] + yb
            sub = body.crop((
                int(x0 / scale) - pad, int(y0 / scale) - pad,
                int(x1 / scale) + pad, int(y1 / scale) + pad,
            ))
            if sub.width < 12 or sub.height < 12:
                line_cells.append("")
                continue
            up = sub.resize((int(sub.width * cell_scale),
                             int(sub.height * cell_scale)), Image.LANCZOS)
            txt = ocr_region(engine, np.array(up))
            line_cells.append(txt.strip())
        table.append(line_cells)

    if verbose:
        for r in table[:4]:
            print("   ", [c[:18] for c in r])
    return {"n_rows": len(table), "n_cols": len(cols_x), "cells": table}


def to_markdown(table, title=None, n_cols=None):
    """cells -> Markdown 表格文本"""
    if not table:
        return ""
    ncol = max(len(r) for r in table)
    # 表头 = 第一行
    header = table[0]
    out = []
    if title:
        out += [f"## {title}", ""]
    hdr = [ (header[i] if i < len(header) else "").replace("|", "／").replace("\n", "") or " " for i in range(ncol)]
    out.append("| " + " | ".join(hdr) + " |")
    out.append("|" + "|".join(["---"] * ncol) + "|")
    for r in table[1:]:
        cells = [ (r[i] if i < len(r) else "").replace("|", "／").replace("\n", "") for i in range(ncol) ]
        out.append("| " + " | ".join(c if c else " " for c in cells) + " |")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--scale", type=float, default=0.75)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    engine = RapidOCR()
    t0 = time.time()
    res = extract_table(engine, args.img, scale=args.scale, verbose=args.verbose)
    if res is None:
        print("未检测到表格")
        return
    md = to_markdown(res["cells"])
    print(f"[table] {res['n_rows']} 行 x {res['n_cols']} 列, {time.time()-t0:.1f}s\n")
    print(md)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(md)
        print(f"[saved] {args.out}")


if __name__ == "__main__":
    main()