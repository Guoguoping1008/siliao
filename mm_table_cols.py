"""修复全库列数不一致的 Markdown 表格块。

**核心认知: 真实网格宽度 = 数据行的最大列数(去掉尾部全空的壳)。**

三类反例(踩过的坑):

1) 0053 —— 2 列表单里嵌了 3 列子表(日粮组成: 计算值/实测值)
   | 试验编号： | 第2页 |        <- 2  (外层表单)
   |  | 计算值 | 实测值 |      <- 3  (子表, 不是错位)
   按众数截断 -> 子表数据丢失。
   => 列数 > 网格宽的行组 = **嵌套子表**, 原样保留。

2) 0313 —— 3 列表的**续行**缺首格
   | 类别 | 通用名称 | 适用范围 |           <- 3 (表头)
   |  | 低聚木糖 | 猪、鸡... |               <- 2 (续行, 类别列合并)
   按众数(2)截断 -> 首列"类别"被砍, 语义丢失。
   => 续行应该**补空**到网格宽, 空位方向跟原表一致(首格 or 末格)。

3) 0084 / 0108 —— 表头行**尾部多了空壳**
   | 评价内容 | 章节 | 直接饲喂微生物 | 发酵制品生产菌株 | |   <- 5(尾部2个空壳)
   |  |  | 细菌 | 酵母和丝状真菌 | 细菌 | 酵母和丝状真菌 |    <- 6(真实数据)
   真实网格是 6 列, 表头尾部那 2 个空壳是 OCR 噪声。
   => 表头列数 > 数据列数时, **先削表头的尾部空壳**, 而不是截数据。

修正后的规则:
  1) 网格宽 W = 数据行(分隔行之后)的最大列数
  2) 表头行: 列数 > W -> 削尾部空壳到 W; 列数 < W -> 补空到 W
  3) 分隔行: 对齐到 W
  4) 数据行: 列数 < W -> 补空到 W(方向随原表); 列数 > W -> 嵌套子表, 保留
  5) 没有分隔行: 整块按数据行最大列数处理

坑: 补空方向不能一律末尾 —— 续行的合并可能在**首列**(0313)也可能**末列**。
    判据: 统计块内少列的行, 看它们空的是第0格还是最后一格。
"""
import collections
import os
import re
import sys

MINIMAX = r"E:/workspace/siliao/minimax"


def is_sep(l):
    cells = [x.strip() for x in l.strip().strip("|").split("|")]
    return bool(cells) and all(x and set(x) <= set("-:") for x in cells)


def cells_of(l):
    return [c.strip() for c in l.strip().strip("|").split("|")]


def ncols(l):
    return len(cells_of(l))


def build_line(cells):
    return "| " + " | ".join(cells) + " |"


def sep_line(n):
    return "| " + " | ".join(["---"] * n) + " |"


def trim_tail(cells):
    """削掉尾部连续的空壳"""
    c = list(cells)
    while len(c) > 1 and not c[-1]:
        c.pop()
    return c


def pad_style(b, sep_idx, w):
    """续行的空位在首格还是末格: 统计少列行的空位位置"""
    head = tail = 0
    for i in range(sep_idx + 1, len(b)):
        c = cells_of(b[i])
        if len(c) >= w:
            continue
        if c and not c[0]:
            head += 1
        elif c and not c[-1]:
            tail += 1
    return head > tail


def split_blocks(b):
    """把一个连续 | 块拆成**多张表**。

    坑: 一个连续的 | 块里可能有多张表(中间没有空行隔开)。
    例 0075:
        | 序号 | 项目 |          <- 表A 的表头(2列)
        |---|---|---|
        | A | 试验名称 |
        ... 共 12 行 ...
        | 大类 | 亚类 | ... |  |  <- 表B 的表头(7列)
        |---|---|---|---|---|---|---|
        | 鱼类 | ... |
    如果把它们当一张表, 网格宽按最大列数算, 表A 的表头会被补一堆空列,
    表B 的表头也会被削掉尾壳 —— 两张表都被弄坏。

    识别新表的起点: 一行 | 开头, 下一行是分隔行, 且分隔行的列数
    **等于**该行的列数(标准 md 表头特征)。
    """
    tables = []
    cur = []
    i = 0
    while i < len(b):
        if (i + 1 < len(b) and not is_sep(b[i]) and is_sep(b[i + 1])
                and ncols(b[i]) == ncols(b[i + 1])):
            # 新表起点
            if cur:
                tables.append(cur)
                cur = []
        cur.append(b[i])
        i += 1
    if cur:
        tables.append(cur)
    return tables


def fix_block(b):
    out = list(b)
    changes = []

    # 先拆成多张表, 逐张处理
    tables = split_blocks(b)
    if len(tables) > 1:
        new_all = []
        for ti, t in enumerate(tables):
            nt, ch = fix_single(t)
            new_all.extend(nt)
            for c in ch:
                changes.append(f"表{ti+1}: {c}")
        return new_all, changes
    return fix_single(b)


def fix_single(b):
    out = list(b)
    changes = []
    sep_idx = None
    for i, l in enumerate(b):
        if is_sep(l):
            sep_idx = i
            break

    if sep_idx is None:
        # 无分隔行: 网格宽 = 全部行最大列数
        w = max(ncols(l) for l in b)
        for i in range(len(b)):
            c = cells_of(b[i])
            if len(c) == w:
                continue
            if len(c) > w:
                nc = trim_tail(c)[:w]
                if len(nc) < w:
                    nc = nc + [""] * (w - len(nc))
                changes.append(f"行{i} 削壳/截断 {len(c)}->{w}")
            else:
                nc = c + [""] * (w - len(c))
                changes.append(f"行{i} 补空 {len(c)}->{w}")
            out[i] = build_line(nc)
        return out, changes

    # 网格宽 = 数据行最大列数
    data_cols = [ncols(l) for l in b[sep_idx + 1:]]
    w = max(data_cols) if data_cols else ncols(b[sep_idx - 1])

    # 1) 表头行(分隔行之上)
    # 坑: 表头比数据宽时, **不能直接削掉多出来的表头格** ——
    #   那些格是"合并到最后一个数据格"的标签(实测 0075:
    #   表头 7 格(最短试验期|最少试验重复和动物数量), 数据只有 5 格,
    #   说明最后两列的标签被 OCR 合并进了同一个数据格)。
    #   直接削 -> 标签丢失; 直接补 -> 列错位。
    #   正确做法: 把多出来的表头格**并进最后一列**, 用 " / " 连接。
    for i in range(0, sep_idx):
        c = cells_of(b[i])
        if len(c) == w:
            continue
        if len(c) > w:
            extra = c[w - 1:]
            nc = c[:w - 1] + [" / ".join(x for x in extra if x)]
            changes.append(f"表头行{i} 末列合并 {len(c)}->{w}")
        else:
            nc = c + [""] * (w - len(c))
            changes.append(f"表头行{i} 补空 {len(c)}->{w}")
        out[i] = build_line(nc)

    # 2) 分隔行
    if ncols(b[sep_idx]) != w:
        out[sep_idx] = sep_line(w)
        changes.append(f"分隔行 {ncols(b[sep_idx])}->{w}")

    # 3) 数据行
    head_pad = pad_style(b, sep_idx, w)
    for i in range(sep_idx + 1, len(b)):
        c = cells_of(b[i])
        if len(c) == w:
            continue
        if len(c) > w:
            changes.append(f"行{i} 列数{len(c)}>{w} 判为嵌套子表, 保留")
            continue
        nc = ([""] * (w - len(c)) + c) if head_pad else (c + [""] * (w - len(c)))
        out[i] = build_line(nc)
        changes.append(f"行{i} 补空 {len(c)}->{w}({'首' if head_pad else '末'})")
    return out, changes


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


def main():
    apply = "--apply" in sys.argv
    files_fixed = 0
    report = []

    for dp, dns, fns in os.walk(MINIMAX):
        for f in sorted(fns):
            if not f.endswith(".md"):
                continue
            p = os.path.join(dp, f)
            lines = open(p, encoding="utf-8").read().splitlines()
            blocks = blocks_of(lines)
            dirty = False
            new_lines = list(lines)
            for start, b in reversed(blocks):
                if len(b) < 3:
                    continue
                if len(set(ncols(l) for l in b)) == 1:
                    continue
                nb, changes = fix_block(b)
                if changes:
                    dirty = True
                    new_lines[start:start + len(b)] = nb
                    report.append((os.path.relpath(p, MINIMAX), start, changes))
            if dirty:
                files_fixed += 1
                if apply:
                    with open(p, "w", encoding="utf-8") as fh:
                        fh.write("\n".join(new_lines).rstrip() + "\n")

    print(f"改动文件 {files_fixed} 个")
    print()
    for path, start, changes in report:
        real = [c for c in changes if "保留" not in c]
        if not real:
            continue
        print(f"  {path}")
        for c in real:
            print(f"      {c}")
    if not apply:
        print("\n[DRY RUN] 加 --apply 执行")


if __name__ == "__main__":
    main()
