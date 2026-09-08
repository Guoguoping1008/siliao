"""
raw_ocr/*.json → markdown 表格: 用 bbox 的 x 坐标聚类还原表格网格。

为什么需要这个脚本:
- raw_ocr_to_md.py 只按 y 排序输出一维文本流, x 坐标被丢弃
  → 表格页压成流水文本, 列结构全丢, 下游 FTS5 检索"最短试验期 42 天"这类
    跨列语义完全召回不到
- 实测 058.jpg (附录 A 试验期, 2 个表 + 二级合并表头):
  x 中心聚类 (gap>90px) 精确还原 5 列, 和纸面 类别/起始/结束日龄/结束体重/最短试验期 一一对应

核心策略:
1. 列检测: 所有行 bbox 的 x 中心排序, 相邻间距 > col_gap 处切列
   - 只用"数据行"(排除跨多列的表头) 做聚类, 避免合并表头把列压平
2. 行检测: y 中心聚类, 相邻间距 > row_gap 处切行
   - 单元格内换行 (如 "母:14(20)周龄" / "公:16(24)周龄") 会落在同一 y 带 → 用 <br> 合并
3. 合并表头: 一个 cell 的 x 跨度覆盖 >= 2 个列区间 → 标记 colspan, 输出时按 markdown
   的能力降级为"表头文字重复填充"(markdown 原生不支持 colspan)
4. 跨页续表: 检测页首无表头 + 上一页末尾是表格 → 由 table_merge_pages() 拼接

不做的:
- 不做单元格边框线检测 (Hough transform): 实测印刷表格线在手机翻拍下断裂严重,
  x 聚类比线检测稳
- 不输出 HTML table: 下游 FTS5 + LLM 都吃 markdown, 保持一致
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import NamedTuple


class Cell(NamedTuple):
    x1: float
    x2: float
    y1: float
    y2: float
    text: str
    score: float

    @property
    def xc(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def yc(self) -> float:
        return (self.y1 + self.y2) / 2

    @property
    def width(self) -> float:
        return self.x2 - self.x1


def load_cells(raw_ocr: list[dict]) -> list[Cell]:
    """PaddleOCR 行 → Cell 列表"""
    cells = []
    for ln in raw_ocr:
        text = ln["text"].strip()
        if not text:
            continue
        xs = [p[0] for p in ln["bbox"]]
        ys = [p[1] for p in ln["bbox"]]
        cells.append(
            Cell(min(xs), max(xs), min(ys), max(ys), text, float(ln.get("score", 1.0)))
        )
    return cells


def detect_columns(cells: list[Cell], col_gap: float = 90.0) -> list[tuple[float, float]]:
    """
    列边界检测: 用 x 中心聚类。

    关键: 先排除"宽单元格"(合并表头), 只用普通单元格聚类。
    合并表头如"试验阶段(体重或日龄)"宽度是普通格的 2-3 倍, 参与聚类会把
    相邻列桥接成一列。

    返回 [(x_lo, x_hi), ...] 每列的 x 区间。
    """
    if not cells:
        return []

    widths = sorted(c.width for c in cells)
    median_w = widths[len(widths) // 2]
    # 宽度超过中位数 1.8 倍 → 疑似合并单元格, 不参与列聚类
    narrow = [c for c in cells if c.width <= median_w * 1.8]
    if len(narrow) < 2:
        narrow = cells

    xs = sorted(c.xc for c in narrow)
    groups: list[list[float]] = []
    for x in xs:
        if not groups or x - groups[-1][-1] > col_gap:
            groups.append([x])
        else:
            groups[-1].append(x)

    # 每列区间取该列成员 x 中心的 min/max, 再向两侧扩半个 gap
    bounds = []
    for g in groups:
        bounds.append((min(g) - col_gap / 2, max(g) + col_gap / 2))
    return bounds


def detect_rows(cells: list[Cell], row_gap: float = 18.0) -> list[list[Cell]]:
    """
    行检测: y 中心聚类。单元格内换行会落进同一行组。

    注意: 这是"物理行"聚类, 用于 find_table_regions 判断多列结构。
    表格网格切行请用 detect_grid_rows (基于行高自适应, 能分开二级表头)。
    """
    if not cells:
        return []
    ordered = sorted(cells, key=lambda c: c.yc)
    rows: list[list[Cell]] = [[ordered[0]]]
    for prev, cur in zip(ordered, ordered[1:]):
        if cur.yc - prev.yc > row_gap:
            rows.append([cur])
        else:
            rows[-1].append(cur)
    return rows


def detect_grid_rows(cells: list[Cell], bounds: list[tuple[float, float]]) -> list[list[Cell]]:
    """
    表格切行: **以第一列(行标签列)为锚点**, 其余单元格按最近锚点归行。

    为什么不用 y 中心聚类 (实测 058.jpg):
    - 同一表格行内各列 y 中心能差 36px (排版基线不齐):
      "类别"y=51 / "起始"y=75 / "结束体重"y=87 —— 同一行表头
    - 二级表头 ("试验阶段"y=33 vs "起始"y=75) 只差 42px
      → 单一 y_gap 阈值无法同时"合并同行"且"分开二级表头"

    为什么不用 y 投影空白带:
    - 实测 育肥用火鸡(y=293-321) 与 种用火鸡(y=363-394) 之间**没有空白带**,
      因为 "公：16（24）周龄"(y=319-354) 跨在中间把间隙桥接了 → 两行被合并

    锚点法: 第一列的行标签 (肉仔鸡/蛋用维鸡/...) 在 y 上是干净分离的,
    用它们的 y 中点作为行边界, 其余单元格按 y 中心落在哪个区间归行。
    降级: 第一列为空 (纯数据表) 时回退到 y 投影空白带。
    """
    if not cells or not bounds:
        return []

    col0_hi = bounds[0][1]
    col0_cells = sorted((c for c in cells if c.xc <= col0_hi), key=lambda c: c.yc)

    # 合并"同一行标签的多行文字": 相邻 col0 cell 若 y 间隙 < 行高 * 0.35,
    # 视为同一单元格内换行。
    # 阈值实测依据 (059.jpg 表3 col0 间隙/行高比):
    #   "生产小牛肉的"→"肉用牛"  = 0.09 / -0.20  ← 同一单元格内换行, 必须合并
    #   "牛"→"生产小牛肉的"      = 0.89          ← 真实行边界, 必须分开
    #   "肉用牛"→"育肥牛"        = 0.58          ← 真实行边界, 必须分开
    # 取 0.35 把 0.09/-0.20 与 0.58/0.89 干净分开。
    # (曾用 0.8 → 把 牛/生产小牛肉的/育肥牛 全并成一行, 表格塌成 1 行)
    anchors: list[Cell] = []
    last_raw: Cell | None = None
    for c in col0_cells:
        if anchors and last_raw is not None:
            gap = c.y1 - last_raw.y2
            prev_h = last_raw.y2 - last_raw.y1
            if prev_h > 0 and gap < prev_h * 0.35:
                # 归并进上一个锚点 (只扩 y 范围, 不影响下一次比较的基准)
                prev = anchors[-1]
                anchors[-1] = prev._replace(
                    y2=max(prev.y2, c.y2), text=f"{prev.text}{c.text}"
                )
                last_raw = c
                continue
        anchors.append(c)
        last_raw = c

    if len(anchors) >= 2:
        # 相邻锚点的中点作为行分隔线
        cuts = [(a.yc + b.yc) / 2 for a, b in zip(anchors, anchors[1:])]
    else:
        # 降级: y 投影空白带
        y_min = int(min(c.y1 for c in cells))
        y_max = int(max(c.y2 for c in cells)) + 1
        covered = bytearray(y_max - y_min + 1)
        for c in cells:
            for y in range(int(c.y1) - y_min, int(c.y2) - y_min + 1):
                if 0 <= y < len(covered):
                    covered[y] = 1
        gaps: list[tuple[int, int]] = []
        run_start = None
        for i, v in enumerate(covered):
            if v == 0 and run_start is None:
                run_start = i
            elif v == 1 and run_start is not None:
                if i - run_start >= 3:
                    gaps.append((run_start + y_min, i + y_min))
                run_start = None
        cuts = [(a + b) / 2 for a, b in gaps]

    rows: list[list[Cell]] = [[] for _ in range(len(cuts) + 1)]
    for c in cells:
        idx = sum(1 for cut in cuts if c.yc > cut)
        rows[idx].append(c)
    return [r for r in rows if r]


def assign_column(cell: Cell, bounds: list[tuple[float, float]]) -> tuple[int, int]:
    """
    单元格 → 列索引区间 (start, end)。合并单元格会跨多列。

    判定分两步 (实测 058.jpg 二级表头必须这样才对):
    1. 先看 cell 的 x 区间**覆盖**了哪些列中心
       —— 合并表头"试验阶段（体重或日龄）"x=397-643, 覆盖 col2 中心(524),
          但它真实跨 col1..col3, 单看覆盖会漏
    2. 再看重叠比例: 与列区间重叠 > 35% 列宽 即算占用
    两者取并集, 保证宽表头能跨列, 窄单元格不误跨。
    """
    occupied: set[int] = set()
    for i, (lo, hi) in enumerate(bounds):
        col_c = (lo + hi) / 2
        col_w = hi - lo
        # 规则 1: 列中心落在 cell 的 x 区间内
        if cell.x1 <= col_c <= cell.x2:
            occupied.add(i)
            continue
        # 规则 2: 实质重叠
        overlap = min(cell.x2, hi) - max(cell.x1, lo)
        if col_w > 0 and overlap > col_w * 0.35:
            occupied.add(i)

    if not occupied:
        nearest = min(
            range(len(bounds)), key=lambda i: abs(cell.xc - (bounds[i][0] + bounds[i][1]) / 2)
        )
        return nearest, nearest
    return min(occupied), max(occupied)


def build_grid(
    cells: list[Cell], col_gap: float = 90.0, row_gap: float = 18.0
) -> tuple[list[list[str]], list[list[tuple[int, int]]]]:
    """
    → (grid, spans)
    grid[r][c] = 文本 (单元格内多行用 <br> 连接)
    spans[r] = [(col_start, col_end), ...] 与该行非空单元格对应, 用于识别 colspan
    """
    bounds = detect_columns(cells, col_gap)
    if not bounds:
        return [], []
    n_col = len(bounds)

    rows = detect_grid_rows(cells, bounds)
    grid: list[list[str]] = []
    spans: list[list[tuple[int, int]]] = []

    for row_cells in rows:
        line = [""] * n_col
        row_spans: list[tuple[int, int]] = []
        # 同一行内先按 y 再按 x 排序: 保证单元格内换行 (母/公) 按上下顺序拼接
        for c in sorted(row_cells, key=lambda c: (round(c.yc / 12), c.x1)):
            cs, ce = assign_column(c, bounds)
            # 单元格内换行: 同一列已有内容 → 用 <br> 追加
            if line[cs]:
                line[cs] = f"{line[cs]}<br>{c.text}"
            else:
                line[cs] = c.text
            row_spans.append((cs, ce))
        grid.append(line)
        spans.append(row_spans)

    return grid, spans


def grid_to_markdown(
    grid: list[list[str]], spans: list[list[tuple[int, int]]], header_rows: int = 1
) -> str:
    """
    grid → markdown 表格。

    合并表头处理: markdown 不支持 colspan, 策略是把跨列表头的文字
    **重复填进它覆盖的每一列**, 保证 FTS5 检索时每列都带上父级语义。
    例:  试验阶段(体重或日龄) 跨 3 列
      → | 试验阶段(体重或日龄)·起始 | 试验阶段(体重或日龄)·结束日龄 | ... |
    """
    if not grid:
        return ""
    n_col = max(len(r) for r in grid)

    # 表头合并: 前 header_rows 行按列拼接, 上级用 · 连下级
    header_parts: list[list[str]] = [[] for _ in range(n_col)]
    for r in range(min(header_rows, len(grid))):
        row_spans = spans[r] if r < len(spans) else []
        # 把该行每个单元格的文字铺到它覆盖的所有列
        filled = [""] * n_col
        cells_in_row = [(cs, ce, grid[r][cs]) for cs, ce in row_spans if cs < len(grid[r])]
        for cs, ce, text in cells_in_row:
            if not text:
                continue
            for c in range(cs, min(ce + 1, n_col)):
                filled[c] = text
        for c in range(n_col):
            if filled[c] and filled[c] not in header_parts[c]:
                header_parts[c].append(filled[c])

    header = ["·".join(p) if p else " " for p in header_parts]

    out = ["| " + " | ".join(header) + " |"]
    out.append("|" + "|".join(["---"] * n_col) + "|")
    for r in range(header_rows, len(grid)):
        row = grid[r] + [""] * (n_col - len(grid[r]))
        out.append("| " + " | ".join(c if c else " " for c in row) + " |")
    return "\n".join(out)


# ---------- 表格区域检测 (一页里区分正文段落 vs 表格) ----------

TABLE_TITLE_RE = re.compile(r"^\s*[(（]?\s*(表|附表)\s*[0-9A-Za-z一二三四五六七八九十]+")
TABLE_CONT_RE = re.compile(r"^\s*[(（]?\s*续\s*表\s*[)）]?\s*$")
NOTE_RE = re.compile(r"^\s*注\s*[:：]")


def find_table_regions(
    cells: list[Cell], min_rows: int = 3, col_gap: float = 90.0
) -> list[tuple[float, float]]:
    """
    找出页面里的表格 y 区间。

    判定依据: 连续若干行, 每行有 >= 3 个横向分离的单元格 (即多列结构)。
    正文段落每行是一个长 bbox, 只有 1 个单元格 → 天然区分。

    表标题切分 (实测 059.jpg 有 表3/表4/表5/表6 四个表连排):
    "表 N xxx" 标题行本身是单列, 会打断多列连续段, 天然成为表格分界。
    但标题与表格间距很小, 容易被 detect_rows 归进同一行 → 额外用标题行
    强制切分, 否则 4 个表会被拼成 1 个巨表, 列结构全乱。

    返回 [(y_top, y_bottom), ...]
    """
    rows = detect_rows(cells)

    # 表标题行的 y (作为强制分界线)
    title_ys = [
        min(c.y1 for c in row)
        for row in rows
        if any(TABLE_TITLE_RE.match(c.text) for c in row)
    ]

    multi_col_flags = []
    for row_cells in rows:
        # 表标题行不算多列行, 即使它旁边有别的碎片
        if any(TABLE_TITLE_RE.match(c.text) for c in row_cells):
            multi_col_flags.append(False)
            continue
        xs = sorted(c.xc for c in row_cells)
        clusters = 1
        for a, b in zip(xs, xs[1:]):
            if b - a > col_gap:
                clusters += 1
        multi_col_flags.append(clusters >= 3)

    regions = []
    start = None
    for i, flag in enumerate(multi_col_flags):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if i - start >= min_rows:
                y1 = min(c.y1 for c in rows[start])
                y2 = max(c.y2 for c in rows[i - 1])
                regions.append((y1, y2))
            start = None
    if start is not None and len(rows) - start >= min_rows:
        y1 = min(c.y1 for c in rows[start])
        y2 = max(c.y2 for c in rows[-1])
        regions.append((y1, y2))

    # 用表标题 y 再切一刀: 落在 region 内部的标题说明这里粘了两个表
    split_regions: list[tuple[float, float]] = []
    for (y1, y2) in regions:
        inner = sorted(y for y in title_ys if y1 < y < y2)
        prev = y1
        for ty in inner:
            if ty - prev > 20:
                split_regions.append((prev, ty - 1))
            prev = ty
        split_regions.append((prev, y2))
    return split_regions


def page_to_markdown(raw_ocr: list[dict], page_no: int, header_re: re.Pattern | None = None) -> str:
    """
    整页 → markdown: 表格区域走网格还原, 其余走文本行。
    """
    cells = load_cells(raw_ocr)
    if header_re:
        cells = [c for c in cells if not header_re.match(c.text)]
    if not cells:
        return f"<!-- page: {page_no} -->"

    regions = find_table_regions(cells)
    out = [f"<!-- page: {page_no} -->"]

    used: set[int] = set()
    # 按 y 顺序交错输出正文 / 表格
    blocks: list[tuple[float, str]] = []

    for (y1, y2) in regions:
        tbl_cells = [c for c in cells if y1 - 5 <= c.yc <= y2 + 5]
        for c in tbl_cells:
            used.add(id(c))
        grid, spans = build_grid(tbl_cells)
        # 表头行数: 第 0 行存在跨列单元格 → 二级表头 (占 2 行)
        header_rows = 1
        if spans and any(ce > cs for cs, ce in spans[0]):
            header_rows = 2
        md = grid_to_markdown(grid, spans, header_rows=header_rows)
        if md:
            blocks.append((y1, md))

    for c in cells:
        if id(c) not in used:
            blocks.append((c.yc, c.text))

    blocks.sort(key=lambda b: b[0])
    for _, text in blocks:
        out.append(text)

    return "\n\n".join(out)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("doc_dir", type=Path, help="data/markdown/<doc_id>/ 目录")
    p.add_argument("--out-sub", default="pages", help="输出子目录名 (默认 pages)")
    p.add_argument("--header", default="", help="页眉 regex, 匹配则丢弃该行")
    p.add_argument("--only", default="", help="只处理某个 stem (调试用)")
    args = p.parse_args()

    raw_ocr_dir = args.doc_dir / "raw_ocr"
    out_dir = args.doc_dir / args.out_sub
    out_dir.mkdir(parents=True, exist_ok=True)
    header_re = re.compile(args.header) if args.header else None

    files = sorted(raw_ocr_dir.glob("*.json"))
    if args.only:
        files = [f for f in files if f.stem == args.only]
    print(f"[table_reconstruct] {len(files)} 页 → {out_dir}/")

    n_tbl = 0
    for i, f in enumerate(files, 1):
        data = json.loads(f.read_text(encoding="utf-8"))
        md = page_to_markdown(data, page_no=i, header_re=header_re)
        if "|---" in md:
            n_tbl += 1
        (out_dir / f"{f.stem}.md").write_text(md, encoding="utf-8")

    print(f"[table_reconstruct] 完成: {len(files)} 页, 其中 {n_tbl} 页含还原表格")


if __name__ == "__main__":
    main()
