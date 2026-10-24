"""表格页 OCR -> Markdown 表格（基于文本框坐标聚类，不依赖网格线检测）。

思路:
网格线检测在"扫描模糊 + 线宽 2px + 合并单元格"的表上不可靠(线会断),
但 OCR 文本框自带坐标, 且同一列的文本 x 范围高度重叠、同一行的 y 高度接近,
因此按坐标聚类即可稳健地重建行列结构, 并天然支持合并单元格。
"""
import os, sys, re, argparse, time
import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

HEADER_CROP = 0.13


def detect_table_region(engine, im, scale=0.5, header_words=None):
    """先定位表格, 再按其真实上边界裁剪。

    表格页的表头行可能紧贴书眉下方, 固定裁 13% 会把表头切掉。
    做法: OCR 整页, 找出"横向密集对齐"的一侧, 用其最小 y 作为表格上界。
    """
    s = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
    res, _ = engine(np.array(s))
    items = []
    for b, t, sc in (res or []):
        t = t.strip()
        if sc < 0.5 or not t:
            continue
        ys = [c[1] for c in b]; xs = [c[0] for c in b]
        items.append({"y0": min(ys), "y1": max(ys), "x0": min(xs),
                      "x1": max(xs), "t": t})
    if not items:
        return None
    sh = s.height
    # 书眉特征
    hdr_kw = ("饲料法规文件", "相关法律法规文件", "制度文件", "标准及标准目录")
    hdr_y = [it["y1"] for it in items
             if any(k in it["t"] for k in hdr_kw) or ">>>" in it["t"] or "<<<" in it["t"]]
    content = [it for it in items if it["y0"] > (max(hdr_y) if hdr_y else 0)]
    if not content:
        content = items
    # 表格侧: x 起点聚集在一侧的较多
    w = s.width
    right = [it for it in content if it["x0"] > w * 0.5]
    left = [it for it in content if it["x1"] < w * 0.5]
    side = right if len(right) >= len(left) else left
    if len(side) < 6:
        side = content
    top = min(it["y0"] for it in side)
    return {"top": top / scale, "sh": sh}


def ocr_boxes(engine, img, scale=0.6, min_score=0.5, zoom_small=True):
    """返回文本框 [{x0,y0,x1,y1,t,s}]（坐标已还原到原图尺度）

    zoom_small: 对小尺寸文本框(窄列里的单个数字)额外放大识别,
    否则"序号"列的 1/2 容易漏检。
    """
    s = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    res, _ = engine(np.array(s))
    out = []
    extra = []
    for b, t, sc in (res or []):
        t = t.strip()
        if sc < min_score or not t:
            continue
        xs = [c[0] for c in b]; ys = [c[1] for c in b]
        x0, y0 = min(xs), min(ys)
        x1, y1 = max(xs), max(ys)
        out.append({"x0": x0 / scale, "y0": y0 / scale,
                    "x1": x1 / scale, "y1": y1 / scale,
                    "t": t, "s": float(sc)})
        # 窄且矮的框 -> 可能是序号列的单个数字, 记下来放大重识别
        w, h = x1 - x0, y1 - y0
        if zoom_small and 0 < w < 40 and 0 < h < 40 and t.isdigit():
            extra.append((x0, y0, x1, y1))
    # 放大重识别小数字
    for x0, y0, x1, y1 in extra:
        pad = 6
        sub = img.crop((max(0, int(x0 / scale) - pad), max(0, int(y0 / scale) - pad),
                        int(x1 / scale) + pad, int(y1 / scale) + pad))
        if sub.width < 6 or sub.height < 6:
            continue
        up = np.array(sub.resize((sub.width * 4, sub.height * 4), Image.LANCZOS))
        r2, _ = engine(up)
        for b, t, sc in (r2 or []):
            if sc >= 0.5 and t.strip().isdigit():
                out.append({"x0": (x0 - pad) / scale, "y0": (y0 - pad) / scale,
                            "x1": (x1 + pad) / scale, "y1": (y1 + pad) / scale,
                            "t": t.strip(), "s": float(sc)})
                break
    return out


def split_pages(boxes, gap_frac=0.05):
    """按 x 把文本框分到左/右页（跨页扫描件）"""
    if not boxes:
        return {"L": [], "R": []}
    w = max(b["x1"] for b in boxes) - min(b["x0"] for b in boxes)
    xs = sorted(b["x0"] for b in boxes)
    # 用 x 的最大空隙判断书脊
    mid_lo = xs[int(len(xs) * 0.30)]
    mid_hi = xs[int(len(xs) * 0.70)]
    return {"L": [], "R": []}


def cluster_columns(boxes, tol_frac=0.030):
    """把文本框按 x 起点聚成列。返回 [[box,...], ...] 每列内按 y 排序。

    注意: 表格里同一"逻辑列"的各单元格 x 起点会有偏差(尤其窄列),
    因此先用较大的容差把明显不同的列分开, 再对列数做"过多则合并"的收缩。
    """
    if not boxes:
        return []
    items = sorted(boxes, key=lambda b: b["x0"])
    width = max(b["x1"] for b in items) - min(b["x0"] for b in items)
    tol = max(10.0, width * tol_frac)
    cols = []
    cur = [items[0]]
    cur_ref = items[0]["x0"]
    for b in items[1:]:
        if b["x0"] - cur_ref <= tol:
            cur.append(b)
            cur_ref = float(np.median([c["x0"] for c in cur]))
        else:
            cols.append(sorted(cur, key=lambda z: z["y0"]))
            cur = [b]
            cur_ref = b["x0"]
    cols.append(sorted(cur, key=lambda z: z["y0"]))
    return cols


def merge_sparse_columns(cols, min_rows=3):
    """把"行数明显偏少"的列并入相邻列 —— 这些是列内文字换行造成的碎片列。"""
    if len(cols) <= 1:
        return cols
    n = max(len(c) for c in cols)
    out = []
    for c in cols:
        if out and len(c) < max(min_rows, n * 0.25):
            out[-1] = sorted(out[-1] + c, key=lambda z: z["y0"])
        else:
            out.append(c)
    return out


def rows_from_cols(cols, row_tol_frac=0.012, page_h=3000):
    """由各列的行位置推出全局行边界, 再把单元格内容落格。

    返回 (rows, grid), 其中 grid 是**行优先** grid[row][col]。

    行距用固定比例(实测 1.2% 页高)对这两类表都合适:
    密集表的记录行在 y 上确实靠得近, 同一记录内的换行会由后续
    merge_records 按关键列合并, 不需要在这里区分。
    """
    centers = []
    for col in cols:
        for b in col:
            centers.append((b["y0"] + b["y1"]) / 2)
    if not centers:
        return [], []

    centers = sorted(centers)
    # 同一物理行的多个框 y 完全相同, 去重后再聚类
    uniq = [centers[0]]
    for c in centers[1:]:
        if c - uniq[-1] > 2.0:
            uniq.append(c)

    tol = max(8.0, page_h * row_tol_frac)
    rows = []
    cur = [uniq[0]]
    for c in uniq[1:]:
        if c - cur[-1] <= tol:
            cur.append(c)
        else:
            rows.append(float(np.median(cur)))
            cur = [c]
    rows.append(float(np.median(cur)))

    ncol = len(cols)
    grid = [["" for _ in range(ncol)] for _ in rows]
    for ci, col in enumerate(cols):
        for b in col:
            c = (b["y0"] + b["y1"]) / 2
            ri = int(np.argmin([abs(c - r) for r in rows]))
            grid[ri][ci] = (grid[ri][ci] + b["t"]).strip()
    return rows, grid


def join_vertical(texts):
    """单元格内竖排文字: 原样按 OCR 顺序拼接（已由 y 排序）"""
    return "".join(texts)


HEADER_HINTS = ("序号", "编号", "省市", "试验机构", "机构名称", "签发人",
               "机构类型", "动物种类", "试验场地", "联系电话", "名称")


def find_header_row(grid):
    """找出表头所在行: 含最多"列名关键词"的一行。"""
    best, best_score = 0, 0
    for r, cells in enumerate(grid):
        score = 0
        for c in cells:
            t = c.strip()
            if not t:
                continue
            for h in HEADER_HINTS:
                if h in t:
                    score += 1
                    break
        if score > best_score:
            best, best_score = r, score
    return (best if best_score >= 3 else None), best_score


def find_key_column(grid, header):
    """挑选"记录起始标志列": 含省市/序号等短值、且每条记录只出现一次。

    返回 (列号, 置信分)。置信分过低时返回 None —— 此时表格是"一行一记录"
    (如质谱参数表), 不应再做记录合并。
    """
    ncol = len(header) if header else (max(len(r) for r in grid) if grid else 0)
    prov = ("北京", "天津", "上海", "重庆", "河北", "辽宁", "吉林", "黑龙江",
            "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北",
            "湖南", "广东", "广西", "海南", "四川", "贵州", "云南", "陕西",
            "甘肃", "青海", "台湾", "内蒙古", "西藏", "宁夏", "新疆")
    nrows = max(1, len(grid))
    best, best_score = None, 0
    for c in range(ncol):
        vals = [r[c].strip() for r in grid if c < len(r)]
        pv = sum(1 for v in vals if any(p in v for p in prov))
        seq = sum(1 for v in vals if re.fullmatch(r"\d{1,3}", v))
        score = pv * 2 + seq
        if score > best_score:
            best, best_score = c, score
    # 关键列应在多数行都有值(每条记录一个), 否则不可靠
    if best is not None and best_score >= max(3, nrows * 0.35):
        return best, best_score
    return None, best_score


def merge_records(grid, rows_y, key_col=0, key_max_len=6):
    """把"跨行的单元格"合并回一条逻辑记录。

    表格含大量合并单元格(一个机构占 3~5 个物理行)。判定依据是"关键列"
    (通常为序号或省市): 该列出现新值就开新记录, 否则并入上一条。
    """
    if not grid:
        return grid
    if key_col >= len(grid[0]):
        return grid
    prov = ("北京", "天津", "上海", "重庆", "河北", "辽宁", "吉林", "黑龙江",
            "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北",
            "湖南", "广东", "广西", "海南", "四川", "贵州", "云南", "陕西",
            "甘肃", "青海", "台湾", "内蒙古", "西藏", "宁夏", "新疆")

    def is_key(v):
        v = v.strip()
        if not v or len(v) > 14:
            return False
        if any(p in v for p in prov):
            return True
        return bool(re.fullmatch(r"\d{1,3}[、.．]?", v))

    out = []
    for r in grid:
        k = r[key_col].strip() if key_col < len(r) else ""
        if out and not is_key(k):
            prev = out[-1]
            for c in range(max(len(prev), len(r))):
                pv = prev[c] if c < len(prev) else ""
                rv = r[c] if c < len(r) else ""
                if rv and not pv:
                    prev[c] = rv          # 合并单元格: 补上缺失值
                elif rv:
                    prev[c] = pv + rv     # 同列多行内容依次拼接
        else:
            out.append(list(r))
    return out


def to_markdown(grid, rows_y, header_row=0):
    """grid 为 行优先: grid[row][col]"""
    if not grid:
        return ""
    ncol = max(len(r) for r in grid)
    grid = grid[header_row:]
    out = []
    hdr = [(grid[0][c] if c < len(grid[0]) else "") or " " for c in range(ncol)]
    hdr = [h.replace("|", "／") for h in hdr]
    out.append("| " + " | ".join(hdr) + " |")
    out.append("|" + "|".join(["---"] * ncol) + "|")
    for r in range(1, len(grid)):
        cells = []
        for c in range(ncol):
            v = grid[r][c] if c < len(grid[r]) else ""
            cells.append(v.replace("|", "／").strip() or " ")
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def detect_rotation(engine, img, scale=0.5):
    """判断表格区域是否需要旋转 90 度。

    书籍里的附表常按 90 度印刷(横向表)。判据: 文本框的"宽高比"均值。
    摆正时单行文本框是扁的(w/h 明显大于 1), 侧转时是高的(w/h < 1)。
    """
    def probe(img2):
        s = img2.resize((int(img2.width * scale), int(img2.height * scale)), Image.LANCZOS)
        res, _ = engine(np.array(s))
        ars = []
        for b, t, sc in (res or []):
            if sc <= 0.6 or not t.strip():
                continue
            ys = [c[1] for c in b]; xs = [c[0] for c in b]
            h = max(ys) - min(ys); w = max(xs) - min(xs)
            if h < 3 or w < 3:
                continue
            ars.append(w / h)
        return (float(np.mean(ars)) if ars else 1.0), len(ars)

    a0, n0 = probe(img)
    a1, n1 = probe(img.rotate(-90, expand=True))
    if a1 > a0 * 1.6 and n1 >= 4:
        return -90, {"orig": a0, "rot": a1}
    return 0, {"orig": a0, "rot": a1}


def split_table_side(engine, im, scale=0.5):
    """跨页扫描件: 先按书脊空白沟把左右页分开, 返回表格所在的半幅。

    附表常常只占一页, 另一半是正文(如公告全文); 直接整幅旋转/聚类
    会把正文混进表格, 因此必须先切。
    """
    s = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
    res, _ = engine(np.array(s))
    items = []
    for b, t, sc in (res or []):
        if sc < 0.5 or not t.strip():
            continue
        xs = [c[0] for c in b]; ys = [c[1] for c in b]
        items.append({"x0": min(xs), "x1": max(xs), "y0": min(ys), "y1": max(ys), "t": t})
    if len(items) < 6:
        return im, 0
    W = s.width
    xs = sorted(it["x0"] for it in items)
    gaps = [(xs[i + 1] - xs[i], i) for i in range(len(xs) - 1)]
    g, i = max(gaps)
    if g <= W * 0.05:
        return im, 0
    cut = int((xs[i] + xs[i + 1]) / 2)
    left = [it for it in items if it["x1"] <= cut]
    right = [it for it in items if it["x0"] >= cut]
    if len(left) < 4 and len(right) < 4:
        return im, 0
    # 表格页的特征: 数字/括号多、且横向排布的行数多
    def tscore(arr):
        nums = sum(1 for it in arr if any(ch.isdigit() for ch in it["t"]))
        return len(arr) + nums * 0.6
    if tscore(right) >= tscore(left):
        return im.crop((int(cut / scale), 0, im.width, im.height)), cut
    return im.crop((0, 0, int(cut / scale), im.height)), 0


def process(engine, path, scale=0.6, col_tol=0.030, row_tol=0.008,
            title=None, rotate=True):
    im = Image.open(path).convert("RGB")
    W, H = im.size

    # 1) 定位表格上界(避免固定 13% 把表头切掉)
    reg = detect_table_region(engine, im, scale=0.5)
    if reg:
        top = max(int(H * 0.10), int(reg["top"]) - 30)
    else:
        top = int(H * HEADER_CROP)
    body = im.crop((0, top, W, H))

    # 2) 先切出表格所在半页(另一半是公告正文), 再摆正
    rot = 0
    body, cut = split_table_side(engine, body, scale=0.5)
    if rotate:
        rot, info = detect_rotation(engine, body, scale=0.45)
        if rot:
            body = body.rotate(rot, expand=True)

    boxes = ocr_boxes(engine, body, scale=scale)
    if not boxes:
        return None

    cols = cluster_columns(boxes, tol_frac=col_tol)
    cols = merge_sparse_columns(cols)
    if len(cols) < 2:
        return None
    rows_y, grid = rows_from_cols(cols, row_tol_frac=row_tol, page_h=body.height)
    # grid 现在是 行优先: grid[row][col]
    hr, score = find_header_row(grid)
    header_row = hr if hr is not None else 0
    header = list(grid[header_row])
    body_rows = grid[header_row + 1:]
    kc, kscore = find_key_column(body_rows, header)
    if kc is not None:
        body_rows = merge_records(body_rows, rows_y, key_col=kc)
    merged = [header] + body_rows
    md = to_markdown(merged, rows_y, header_row=0)
    return {"md": md, "n_cols": len(cols), "n_rows": len(rows_y),
            "cols": cols, "rows_y": rows_y, "grid": grid, "rot": rot}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--scale", type=float, default=0.6)
    ap.add_argument("--col-tol", type=float, default=0.030)
    args = ap.parse_args()
    engine = RapidOCR()
    t0 = time.time()
    r = process(engine, args.img, scale=args.scale, col_tol=args.col_tol)
    if not r:
        print("未识别为表格")
        return
    print(f"[table] {r['n_rows']} 行 x {r['n_cols']} 列, {time.time()-t0:.1f}s\n")
    print(r["md"])
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(r["md"])
        print(f"[saved] {args.out}")


if __name__ == "__main__":
    main()