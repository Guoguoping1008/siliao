"""表格 HTML 化收尾工具。

1) **去掉所有 bgcolor** —— 表格不要背景色, 只保留结构
2) **压平成一行的表** -> 拆行 -> 转 HTML (含跨行/跨列合并)
3) **跨行合并(rowspan)** 的识别:
   md 表格里"合并"的表现有两种:
     a) **首列为空**的续行        -> 上一行首格 rowspan
     b) **中间列为空**的续行      -> 上一行同列 rowspan
        (书上的合并格经常不在首列, 如 "试验阶段" 列跨多行)
   判定 b 需要看**列**方向: 某列在连续若干行都是空, 而这些行在该列的
   上一行有值 -> 说明上一行的那个格跨了几行。

合并关系从 md 反推的规则(依据 mm_table_cols.py 的教训):
   网格宽 W = 数据行最大列数
   表头块内: 空格 = 延续左边的标签 -> 上一格 colspan
   数据块内: 空格 = 延续**上面**的格   -> 上一格 rowspan
   但要排除"右对齐空壳": 连续多行同一列都空, 且该列在表头里也没名字
   -> 那是列数不齐, 不是合并。

用法:
    python mm_table_final.py --plan
    python mm_table_final.py --apply
"""
import json
import os
import re
import sys

sys.path.insert(0, r"E:/workspace/siliao")
exec(open(r"E:/workspace/siliao/mm_flat_table.py", encoding="utf-8").read())
exec(open(r"E:/workspace/siliao/mm_table_dedup.py", encoding="utf-8").read())

MINIMAX = r"E:/workspace/siliao/minimax"


# ---------------- 通用工具 ----------------
def is_sep(l):
    cells = [x.strip() for x in l.strip().strip("|").split("|")]
    return bool(cells) and all(x and set(x) <= set("-:") for x in cells)


def cells_of(l):
    return [c.strip() for c in l.strip().strip("|").split("|")]


def esc(s):
    s = s.replace("&", "&amp;")
    s = re.sub(r"<br\s*/?>", "\x00BR\x00", s, flags=re.I)
    s = s.replace("<", "&lt;").replace(">", "&gt;")
    s = s.replace("\x00BR\x00", "<br>")
    return s


def looks_like_table(rows):
    """判断切出来的行是不是一张**真表**(而不是被切碎的表单)。

    判据:
      - 至少 2 行
      - 每行至少 2 列
      - **列数一致**(不一致说明切错了)
      - 非空单元格里, 长度 >= 2 的占一定比例
        (全是单字说明是按 "| " 切碎了, 如 0061 的 试/验/编/号)

    坑: 阈值不能太高 —— 0217 的表 84 个格里 41 个是单字("✓" 和序号),
        只按 50% 判会误杀真表。降到 35%, 但**同时要求列数一致**,
        这样 0061 那种按字切碎的(列数 1)照样被排除。
    """
    if not rows or len(rows) < 2:
        return False
    widths = set(len(r) for r in rows)
    if len(widths) != 1:
        return False
    w = widths.pop()
    if w < 2:
        return False
    cells = [c for r in rows for c in r if c]
    if not cells:
        return False
    multi = sum(1 for c in cells if len(c) >= 2)
    return multi >= len(cells) * 0.35


# ---------------- rowspan / colspan 推断 ----------------
def infer_merges(hdr, dat):
    """从 md 表格的空格推断合并关系。

    返回 (colspans, rowspans):
      colspans: [[(start, span), ...] for each header row]  每格记 (起始列, 跨列数)
      rowspans: [[span per column] for each data row]  首格/各格的 rowspan
    """
    w = max((len(r) for r in hdr + dat), default=0)
    if w == 0:
        return [], []
    hdr = [list(r) + [""] * (w - len(r)) for r in hdr]
    dat = [list(r) + [""] * (w - len(r)) for r in dat]
    nh = len(hdr)

    # ---- colspan: 表头块内, 空格延续左边的标签 ----
    colspans = []
    for row in hdr:
        items = []
        ci = 0
        while ci < w:
            val = row[ci]
            span = 1
            while ci + span < w and row[ci + span] == "":
                span += 1
            items.append((ci, span, val))
            ci += span
        colspans.append(items)

    # ---- rowspan: 数据块内, 某列为空且上一行该列非空 -> 上一行该格跨行 ----
    # 先算出每列的"空列"是否算合并:
    #   如果某列在表头里**任何一行**都有名字 -> 是有效列, 空格算合并
    #   如果整列表头全空 -> 是"右对齐空壳"列, 空格不算合并
    valid_col = []
    for c in range(w):
        valid_col.append(any(row[c] for row in hdr))

    rowspans = [[1] * w for _ in dat]
    skip = [[False] * w for _ in dat]
    for c in range(w):
        if not valid_col[c]:
            continue
        i = 0
        while i < len(dat):
            if dat[i][c] == "" and i > 0 and dat[i - 1][c] != "":
                j = i - 1
                while j > 0 and dat[j - 1][c] == "":
                    j -= 1
                k = i
                while k < len(dat) and dat[k][c] == "":
                    skip[k][c] = True
                    k += 1
                rowspans[j][c] = k - j
                i = k
                continue
            i += 1
    return colspans, rowspans


def to_html(hdr, dat):
    """(表头行, 数据行) -> HTML 表格字符串"""
    w = max((len(r) for r in hdr + dat), default=0)
    if w == 0:
        return None
    hdr = [list(r) + [""] * (w - len(r)) for r in hdr]
    dat = [list(r) + [""] * (w - len(r)) for r in dat]
    colspans, rowspans = infer_merges(hdr, dat)
    skip = [[False] * w for _ in dat]
    # infer_merges 里已算好 skip, 重新取
    _, _ = None, None
    return _render(hdr, dat, w, colspans, rowspans)


def _render(hdr, dat, w, colspans, rowspans):
    # 重算 skip
    skip = [[False] * w for _ in dat]
    for c in range(w):
        i = 0
        while i < len(dat):
            if dat[i][c] == "" and i > 0 and dat[i - 1][c] != "":
                j = i - 1
                while j > 0 and dat[j - 1][c] == "":
                    j -= 1
                k = i
                while k < len(dat) and dat[k][c] == "":
                    skip[k][c] = True
                    k += 1
                i = k
                continue
            i += 1

    out = ['<table border="1" cellspacing="0" cellpadding="4">']
    # 表头
    for ri, row in enumerate(hdr):
        out.append("<tr>")
        for (ci, span, val) in colspans[ri]:
            a = f' colspan="{span}"' if span > 1 else ""
            tag = "th" if ri == 0 else "td"
            out.append(f"<{tag}{a}>{esc(val)}</{tag}>")
        out.append("</tr>")
    # 数据
    for i, row in enumerate(dat):
        out.append("<tr>")
        for c in range(w):
            if skip[i][c]:
                continue
            val = row[c]
            a = f' rowspan="{rowspans[i][c]}"' if rowspans[i][c] > 1 else ""
            out.append(f"<td{a}>{esc(val)}</td>")
        out.append("</tr>")
    out.append("</table>")
    return "\n".join(out)


def md_table_to_html(rows):
    """rows: [[cells]] -> html 字符串

    幻觉表头处理: 某个列名**连续重复 >= 3 次**且占表头一半以上 ->
    说明 OCR 把一个跨列合并格展开成了 N 个重复列名 -> 合并成 colspan。
    """
    if not rows:
        return None
    sep = None
    for i, r in enumerate(rows):
        if r and all(c and set(c) <= set("-:") for c in r):
            sep = i
            break
    if sep is not None:
        hdr = rows[:sep]
        dat = rows[sep + 1:]
    else:
        hdr = rows[:1]
        dat = rows[1:]
    if not hdr:
        return None
    # 幻觉表头: 压缩重复列
    if len(hdr) == 1 and is_hallucinated_header(hdr[0]):
        w = len(hdr[0])
        pairs = collapse_repeat_header(hdr[0])
        # 数据行也要按同样的列映射压缩
        new_hdr = [[v] for v, s in pairs]
        # 列映射: 原列索引 -> 新列索引
        colmap = []
        ci = 0
        for _, s in pairs:
            for _ in range(s):
                colmap.append(ci)
                ci += 1
        new_dat = []
        for r in dat:
            nr = []
            j = 0
            for _, s in pairs:
                # 合并同名的多列: 取第一个非空
                vals = [r[k] for k in range(j, min(j + s, len(r))) if k < len(r)]
                nr.append(next((v for v in vals if v), ""))
                j += s
            new_dat.append(nr)
        return to_html(new_hdr, new_dat)
    return to_html(hdr, dat)


# ---------------- 主流程 ----------------
def strip_bgcolor(text):
    """去掉所有 bgcolor 属性"""
    return re.sub(r'\s*bgcolor="[^"]*"', "", text)


def main():
    apply = "--apply" in sys.argv
    nfile = ntab = nflat = 0

    for dp, dns, fns in os.walk(MINIMAX):
        for f in sorted(fns):
            if not f.endswith(".md"):
                continue
            p = os.path.join(dp, f)
            text = open(p, encoding="utf-8").read()
            orig = text
            changed = False

            # 1) 去 bgcolor
            new = strip_bgcolor(text)
            if new != text:
                changed = True
                text = new

            # 2) 残留的管道表 -> HTML
            lines = text.splitlines()
            out_lines = []
            i = 0
            while i < len(lines):
                l = lines[i]
                if l.strip().startswith("|"):
                    # 收集连续的管道行
                    blk = []
                    j = i
                    while j < len(lines) and lines[j].strip().startswith("|"):
                        blk.append(lines[j])
                        j += 1
                    rows = None
                    if len(blk) == 1:
                        rows = split_flat_table(blk[0])
                    else:
                        rows = [cells_of(x) for x in blk]
                        # 多行块里也可能有压平的行
                        if len(blk) == 1:
                            rows = None
                    if rows and len(rows) >= 2:
                        if len(blk) == 1:
                            if looks_like_table(rows):
                                h = md_table_to_html(rows)
                                if h:
                                    out_lines.append(h)
                                    changed = True
                                    ntab += 1
                                    nflat += 1
                                    i = j
                                    continue
                        else:
                            h = md_table_to_html(rows)
                            if h:
                                out_lines.append(h)
                                changed = True
                                ntab += 1
                                i = j
                                continue
                    out_lines.extend(blk)
                    i = j
                    continue
                out_lines.append(l)
                i += 1
            text = "\n".join(out_lines).rstrip() + "\n"

            if changed and text != orig:
                nfile += 1
                if apply:
                    with open(p, "w", encoding="utf-8") as fh:
                        fh.write(text)
    print(f"处理文件 {nfile} 个, 新转换表 {ntab} 个(其中压平表 {nflat} 个)")
    if not apply:
        print("[DRY RUN] 加 --apply 执行")


if __name__ == "__main__":
    main()
