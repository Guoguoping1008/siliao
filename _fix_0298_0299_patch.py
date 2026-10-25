#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""0298/0299 的目视校正补丁。

【要修的 3 处(全部目视逐格核对过)】
1. 0298 10.4.11 鱼油: 强制性标识要求 **多了一项「粗蛋白质」**。
   图上该格从「粗脂肪」开始, 只有 粗脂肪/酸价/碘价/丙二醛 4 项。
2. 0298 10.4.12 鱼浆: 最后一项应是 **「组胶」**, 模型写成了「粗胶」。
3. 0299 表2: 模型**漏了「12.1 饼粕、精渣发酵产品」这一行**(节标题行,
   特征描述 和 强制性标识要求 都是空的)。

【为什么单独打补丁而不是重跑 API】
这三处都是**单点、确定性**的修正, 重跑 8 次 API(4 候选 x 2 页)成本高,
而且模型输出不确定, 重跑可能这次对那次错。
局部补丁更可控 —— 前提是**每一处都目视核对过**。
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(REPO, "minimax", "02制度文件", "04_（四）使用管理", "44_饲料原料目录")


def find_row(txt, no):
    """定位原料编号 == no 的那一整行 <tr>...</tr>。"""
    for m in re.finditer(r"<tr[^>]*>.*?</tr>", txt, re.S | re.I):
        r = m.group(0)
        cells = re.findall(r"<td[^>]*>(.*?)</td>", r, re.S | re.I)
        if cells:
            first = re.sub(r"<[^>]+>", "", cells[0]).strip()
            if first == no:
                return m
    return None


def fix_marks(txt, no, want):
    """把某行的 强制性标识要求 单元格(最后一格)替换成 want(列表)。"""
    m = find_row(txt, no)
    if not m:
        return txt, False
    r = m.group(0)
    cells = list(re.finditer(r"<td[^>]*>.*?</td>", r, re.S | re.I))
    if len(cells) < 4:
        return txt, False
    last = cells[-1]
    new_cell = "<td>%s</td>" % "<br>".join(want)
    new_r = r[:last.start()] + new_cell + r[last.end():]
    return txt[:m.start()] + new_r + txt[m.end():], True


def insert_row(txt, no, name, after_no=None):
    """在某张表的表头行之后插入一行(节标题行, 后两格为空)。

    after_no: 用**该表里已存在的某个编号**来定位目标表。
    坑: 不能只判断「表里不含 no」—— 页面上有 2 张表, 第一张表也不含 '12.1',
    会被误当成目标表, 行就插到错的表里去了(实测插到了表1)。
    必须用 after_no 锚定到**第二张表**。
    """
    for tm in re.finditer(r"<table.*?</table>", txt, re.S | re.I):
        tb = tm.group(0)
        if after_no and after_no not in tb:
            continue
        # 坑: 这里的判断必须是**整格相等**, 不能用 `no in tb` ——
        # '12.1' 是 '12.1.1' 的子串, 用 in 会误判「已存在」而跳过。
        # 所以要按行取第 0 格的值来比。
        rows = list(re.finditer(r"<tr[^>]*>.*?</tr>", tb, re.S | re.I))
        if len(rows) < 2:
            continue
        exists = False
        for r in rows[1:]:
            c = re.findall(r"<td[^>]*>(.*?)</td>", r.group(0), re.S | re.I)
            if c and re.sub(r"<[^>]+>", "", c[0]).strip() == no:
                exists = True
                break
        if exists:
            continue
        hdr_end = rows[0].end()
        newrow = ("<tr>\n    <td>%s</td>\n    <td>%s</td>\n    <td></td>\n"
                  "    <td></td>\n  </tr>" % (no, name))
        new_tb = tb[:hdr_end] + "\n  " + newrow + tb[hdr_end:]
        return txt[:tm.start()] + new_tb + txt[tm.end():], True
    return txt, False


def main():
    # ---- 0298
    p = os.path.join(OUTDIR, "0298.md")
    t = open(p, encoding="utf-8").read()
    t, ok1 = fix_marks(t, "10.4.11", ["粗脂肪", "酸价", "碘价", "丙二醛"])
    t, ok2 = fix_marks(t, "10.4.12",
                       ["粗蛋白质", "粗脂肪", "水分", "挥发性盐基氮", "组胶"])
    print("0298: 10.4.11 鱼油 %s; 10.4.12 鱼浆 %s" %
          ("已修" if ok1 else "未找到", "已修" if ok2 else "未找到"))
    open(p, "w", encoding="utf-8").write(t)

    # ---- 0299: 用草稿 + 补 12.1 行
    draft = p2 = os.path.join(OUTDIR, "0299.md.draft")
    if not os.path.exists(draft):
        print("0299: 找不到草稿")
        return 1
    t = open(draft, encoding="utf-8").read()
    t, ok = insert_row(t, "12.1", "饼粕、精渣发酵产品", after_no="12.1.1")
    print("0299: 补 12.1 行 %s" % ("已补" if ok else "未找到位置"))
    # 12.1.1 发酵豆粕 的强制性标识要求: 图上是 粗蛋白质/酸溶蛋白/水苏糖/水分
    # 模型读成了 粗蛋白/水分/赖氨酸/水分 —— 两处错(多一次水分, 且是赖氨酸不是水苏糖)
    t, ok3 = fix_marks(t, "12.1.1", ["粗蛋白质", "酸溶蛋白", "水苏糖", "水分"])
    print("0299: 12.1.1 发酵豆粕 强制标识 %s" % ("已修" if ok3 else "未找到"))
    out = os.path.join(OUTDIR, "0299.md")
    open(out, "w", encoding="utf-8").write(t)
    os.remove(draft)
    print("OK 写出 0299.md (%d 字节)" % len(t.encode("utf-8")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
