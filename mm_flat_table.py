"""处理"整张表挤在一行"的 md 管道表(OCR 没换行)。

现象(实测 0217/0251):
    |序号|申请材料|不需评审产品|需评审产品| |---|---|---|---| |1 |目录|✓|✓| |2 |...|

关键结构分析
------------
一行 md 表的形态是: |c1|c2|...|cn|      (以 | 开头, 以 | 结尾)
多行被压到一起后, 行与行之间是 " | " —— 但这个 " | " 其实是
**上一行结尾的 "|" + 一个空格 + 下一行开头的 "|"**:

    ...|✓| |2 |目录...
      ↑        ↑
    上行末尾  下行开头

所以行边界 = 出现 " | " 且其后紧跟 "|" 时, 切在**这个 "|" 之前**。

判定:
  "|" + 空格 + "|"   -> 行边界(切在第一个 | 处)
  "|" + 空格 + 非"|" -> 空单元格("| |" 里间是空的, 如 "a| |b")
  "|" + 空格 + "---" -> 行边界(下一行是分隔行)

坑: 分隔行 "|---|---|---|---|" 里的 "|" 后面跟的是 "-", 不是空格, 不会被误切。
"""
import re


def _cells_of_segment(seg):
    s = seg.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_sep(cells):
    return bool(cells) and all(c and set(c) <= set("-:") for c in cells)


def split_flat_table(line):
    """一行压平的 md 表格 -> [[cells], ...]; 失败返回 None"""
    s = line.strip()
    if not s.startswith("|"):
        return None
    if not re.search(r"\|\s*:?-{3,}:?\s*(\||\s|$)", s):
        return None

    # ---- 切行片段 ----
    segs = []
    cur_start = 0
    i = 0
    n = len(s)
    while i < n:
        if s[i] == "|" and i + 1 < n and s[i + 1] == " ":
            j = i + 1
            while j < n and s[j] == " ":
                j += 1
            if j < n and s[j] == "|":
                # " | |" -> 行边界: 切在 i 处(这个 | 结束上一行)
                segs.append(s[cur_start:i + 1])
                cur_start = j
                i = j
                continue
            if j < n and s[j] != "|":
                # " | 非|" -> 空单元格, 继续
                pass
        i += 1
    segs.append(s[cur_start:])

    seg_cells = [c for c in (_cells_of_segment(x) for x in segs) if c]
    if not seg_cells:
        return None

    # ---- 找分隔行定列数 ----
    w = None
    sep_at = None
    for k, c in enumerate(seg_cells):
        if _is_sep(c):
            w = len(c)
            sep_at = k
            break
    if w is None or sep_at is None:
        return None

    rows = []
    for k, c in enumerate(seg_cells):
        if k == sep_at:
            rows.append(c)
            continue
        if len(c) < w:
            c = c + [""] * (w - len(c))
        else:
            c = c[:w]
        rows.append(c)
    return rows


def rows_to_md(rows):
    return "\n".join("| " + " | ".join(c) + " |" for c in rows)
