"""把 Markdown 管道表格转成 **HTML 表格**(支持 colspan/rowspan), 写回 md。

依据: https://developer.aliyun.com/article/1135400
      「在Markdown表格中使用HTML实现合并单元格与背景色设置」
      (原文 CSDN: blog.csdn.net/wkd_007/article/details/124435722)

HTML 表格要素:
  <table border="1">      表格
  <tr> / <th> / <td>      行 / 表头 / 单元格
  colspan="n"             跨 n 列
  rowspan="n"             跨 n 行
  bgcolor="#RRGGBB"       单元格背景色
  单元格内 <、> 转义成 &lt; &gt; ; 换行用 <br>

**为什么改用 HTML**: Markdown 管道表表达不了合并单元格, 只能"空格填充"糊弄;
换 HTML 后 colspan/rowspan 能精确还原书上的两级表头和合并格。

合并关系从 md 表格反推的两条规则:
  A) **表头块内**, 空格表示"延续左边那个标签" -> 上一格加 colspan
     例 0108: |内容|纯化提取物|  |  |组分提取物|  |  |简单提取物|  |  |
              -> 纯化提取物 colspan=3 (覆盖 纯化提取物+它的两个空位)
              -> 组分提取物 colspan=3 ; 简单提取物 colspan=3
     例 0094: 第一行是"抗菌药物|青霉素类|糖肽类|..." 14 格, 第二行是子标签 14 格
              -> 第一行的每个标签按**子表头里它下面有几个非空标签**算 colspan
  B) **数据块内**, 首格为空 = 上一行首格纵向合并 -> 上一格加 rowspan
     例 0313: |类别|通用名称|适用范围| / |  |二氧化硅|养殖动物| / |  |丙三醇|...|
              -> "类别" rowspan=4

  注意: 数据块里**非首列**的空格是右对齐空壳(表头短了), 不是合并, 不处理。

用法:
    python mm_table_html.py --plan
    python mm_table_html.py --apply
    python mm_table_html.py --stem=0031 --apply
"""
import json
import os
import re
import sys

sys.path.insert(0, r"E:/workspace/siliao")
exec(open(r"E:/workspace/siliao/mm_flat_table.py", encoding="utf-8").read())

MINIMAX = r"E:/workspace/siliao/minimax"
LIST_JSON = r"E:/workspace/siliao/_tbl_list.json"

TH_BG = "#F2F2F2"


def is_sep(l):
    cells = [x.strip() for x in l.strip().strip("|").split("|")]
    return bool(cells) and all(x and set(x) <= set("-:") for x in cells)


def cells_of(l):
    return [c.strip() for c in l.strip().strip("|").split("|")]


def blocks_of(lines):
    out, cur, start = [], [], 0
    for i, l in enumerate(lines):
        if l.strip().startswith("|"):
            if not cur:
                start = i
            cur.append(l)
        else:
            if cur:
                out.append((start, cur))
                cur = []
    if cur:
        out.append((start, cur))
    return out


def split_blocks(b):
    tabs, cur, i = [], [], 0
    while i < len(b):
        if (i + 1 < len(b) and not is_sep(b[i]) and is_sep(b[i + 1])
                and len(cells_of(b[i])) == len(cells_of(b[i + 1]))):
            if cur:
                tabs.append(cur)
                cur = []
        cur.append(b[i])
        i += 1
    if cur:
        tabs.append(cur)
    return tabs


def esc(s):
    s = s.replace("&", "&amp;")
    s = re.sub(r"<br\s*/?>", "\x00BR\x00", s, flags=re.I)
    s = s.replace("<", "&lt;").replace(">", "&gt;")
    s = s.replace("\x00BR\x00", "<br>")
    return s


def _looks_like_table(rows):
    """判断切出来的行是不是一张**真表**(而不是被切碎的表单)。

    判据:
      - 至少 2 行
      - 每行至少 2 列
      - 非空单元格里, 长度 >= 2 的占多数
        (全是单字说明是按 "| " 切碎了, 如 0061 的 试/验/编/号)
    """
    if not rows or len(rows) < 2:
        return False
    if any(len(r) < 2 for r in rows):
        return False
    cells = [c for r in rows for c in r if c]
    if not cells:
        return False
    multi = sum(1 for c in cells if len(c) >= 2)
    return multi >= len(cells) * 0.5


def header_spans(hdr, w):
    """算表头每一行的 colspan 布局。

    返回 [[(start_col, colspan, value), ...], ...]  每行一份。
    规则:
      - 只有当**下一行**存在且是子表头时, 才按子表头里该标签下面的
        非空标签个数算 colspan (例 0094)
      - 否则(单行表头)把连续非空格合并成一个 colspan (例 0108 的第一行)
    """
    rows = []
    for ri, row in enumerate(hdr):
        # 子表头行: 下一行存在, 且本格下面是空的 -> 本格向下合并
        below = hdr[ri + 1] if ri + 1 < len(hdr) else None
        items = []
        ci = 0
        while ci < w:
            val = row[ci]
            if val == "":
                # 空格: 延续左边的标签 -> 并进左边那格(已在下面处理)
                # 记录下来, 稍后给左格加 colspan
                ci += 1
                continue
            span = 1
            # 向右吞掉紧跟的空格(这些空格属于本格)
            j = ci + 1
            while j < w and row[j] == "":
                span += 1
                j += 1
            items.append([ci, span, val])
            ci = j
        rows.append(items)
    # 修正: 若某行的空格在行首(前面没有标签), 它们属于上一行的合并
    return rows


def to_html_table(tab):
    """md 表格块 -> HTML 表格字符串

    tab 可以是:
      - 原始 md 行(list[str])
      - 已切好的单元格行(list[list[str]])
    """
    # 归一成 list[list[str]]
    if tab and isinstance(tab[0], str):
        rows = [cells_of(r) for r in tab]
        sep = None
        for i, r in enumerate(tab):
            if is_sep(r):
                sep = i
                break
        hdr = rows[:sep] if sep is not None else rows[:1]
        dat = rows[sep + 1:] if sep is not None else rows[1:]
    else:
        rows = [list(r) for r in tab]
        sep = None
        for i, r in enumerate(rows):
            if _is_sep_cells(r):
                sep = i
                break
        hdr = rows[:sep] if sep is not None else rows[:1]
        dat = rows[sep + 1:] if sep is not None else rows[1:]
    w = max((len(r) for r in hdr + dat), default=0)
    if w == 0:
        return None

    def pad(r):
        r = list(r)
        while len(r) < w:
            r.append("")
        return r[:w]

    hdr = [pad(r) for r in hdr]
    dat = [pad(r) for r in dat]
    nh = len(hdr)

    out = ['<table border="1" cellspacing="0" cellpadding="4">']

    # ---------- 表头 ----------
    for ri, row in enumerate(hdr):
        out.append("<tr>")
        ci = 0
        while ci < w:
            val = row[ci]
            span = 1
            while ci + span < w and row[ci + span] == "":
                span += 1
            tag = "th" if ri == 0 else "td"
            a = f' colspan="{span}"' if span > 1 else ""
            out.append(f'<{tag}{a} bgcolor="{TH_BG}">{esc(val)}</{tag}>')
            ci += span
        out.append("</tr>")

    # ---------- 数据行: 首列纵向合并 -> rowspan ----------
    # 规则: 某行首格为空, 且**上一行首格非空** -> 上一行首格 rowspan 覆盖它。
    # 坑: 一组续行的**首行**首格也可能为空(OCR 把类别标签放到了组尾, 如 0313
    #   前 4 行首格空, 第 5 行才有"抗氧化剂...")。这种情况**不能**硬套 rowspan,
    #   否则标签位置会错。判据: 只有当空首格**上方**有非空首格时才合并。
    spans = [1] * len(dat)
    skip = [False] * len(dat)
    i = 0
    while i < len(dat):
        if dat[i][0] == "" and i > 0 and dat[i - 1][0] != "":
            # 向上找这组连续续行的起点
            j = i - 1
            while j > 0 and dat[j - 1][0] == "":
                j -= 1
            k = i
            while k < len(dat) and dat[k][0] == "":
                skip[k] = True
                k += 1
            spans[j] = k - j
            i = k
            continue
        i += 1
    # 安全阀: rowspan 不可能超过剩余行数
    for i in range(len(dat)):
        if spans[i] > len(dat) - i:
            spans[i] = len(dat) - i

    for i, row in enumerate(dat):
        out.append("<tr>")
        ci = 0
        while ci < w:
            if ci == 0 and skip[i]:
                ci += 1
                continue
            val = row[ci]
            if ci == 0 and spans[i] > 1:
                out.append(f'<td rowspan="{spans[i]}">{esc(val)}</td>')
            else:
                out.append(f"<td>{esc(val)}</td>")
            ci += 1
        out.append("</tr>")
    out.append("</table>")
    return "\n".join(out)


def main():
    apply = "--apply" in sys.argv
    only = None
    for a in sys.argv[1:]:
        if a.startswith("--stem="):
            only = a.split("=", 1)[1]

    pages = json.load(open(LIST_JSON, encoding="utf-8"))
    nfile = ntab = 0
    for pg in pages:
        if only and pg["stem"] != only:
            continue
        p = os.path.join(MINIMAX, pg["path"].replace("/", os.sep))
        if not os.path.exists(p):
            continue
        lines = open(p, encoding="utf-8").read().splitlines()
        new_lines = []
        i = 0
        changed = False
        for start, b in blocks_of(lines):
            new_lines.extend(lines[i:start])
            i = start + len(b)
            # --- 压平成一行的表: 先按行切开 ---
            flat = []
            for t in b:
                if len(t) == 1:
                    rows = split_flat_table(t[0])
                    # 坑: 切出来如果**每格只有 1 个字**(如 0061 的
                    #   "|试验编号：|..." 被按 "| " 切成 试/验/编/号),
                    #   说明切错了, 这种是**表单**不是数据表, 原样保留。
                    if rows is not None and _looks_like_table(rows):
                        flat.extend([[c] for c in rows])
                        continue
                flat.append(t)
            for t in flat:
                if len(t) < 2:
                    new_lines.extend("| " + " | ".join(r) + " |" for r in t)
                    continue
                h = to_html_table(t)
                if h is None:
                    new_lines.extend("| " + " | ".join(r) + " |" for r in t)
                    continue
                new_lines.append(h)
                changed = True
                ntab += 1
        new_lines.extend(lines[i:])
        if changed:
            nfile += 1
            if apply:
                with open(p, "w", encoding="utf-8") as f:
                    f.write("\n".join(new_lines).rstrip() + "\n")
    print(f"处理文件 {nfile} 个, 表格 {ntab} 个")
    if not apply:
        print("[DRY RUN] 加 --apply 执行")


if __name__ == "__main__":
    main()
