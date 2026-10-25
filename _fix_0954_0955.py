#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0954/0955 —— 饲料卫生标准 GB 13078—2017 表1 饲料卫生指标及试验方法。

【页面映射(先读页码确认)】
Images/04标准及标准目录/0955.jpg = 书第 954(左) + 955(右)
  页眉: 左半「954 | 饲料法规文件【2023】 >>>」, 右半「四、标准及标准目录 | 955」
  -> **0954 = 页954 = 0955.jpg 左半**, **0955 = 页955 = 0955.jpg 右半**
  切点 cut=2100

【原状态】
  0954.md 3102B —— 1 表 27 行, 但表头只 6 格(产品名称被压成 1 格), 末几行格数也不对
  0955.md 2734B —— **开头是管道表残渣** + **拆成 2 个表**(本是 1 张连续表)

【原图结构(竖线检测 y=1000 得列界 325|444|641|837|1656|1822 + 逐格放大)】
  7 个列槽: 序号 | 项目 | **类别** | **具体产品名称** | 限量 | 试验方法 | 备注
  表头 2 行:
    第1行: 序号 | 项目 | **产品名称(colspan=2, 跨 类别+具体)** | 限量 | 试验方法 | 备注
    第2行: **无机污染物**(colspan=2, 跨 序号+项目) | (类别空) | (具体空)
            | 限量 | 试验方法 | 备注
  数据行: 序号(rowspan) | 项目+单位(rowspan) | 类别(rowspan) | 具体产品名称 | 限量
          | 试验方法(rowspan) | 备注
  页954: 序号1 总砷 / 序号2 铅; 页955: (续表) 序号3 汞 / 4 镉 / 5 铬

【页955 的「（续表）」位置】在**表格上边框之内、备注列的顶部**(右上角),
  不是表外的题注。

【类别列只有 2 个值】饲料原料 / 饲料产品 —— 这是必须保留的语义,
  API 草稿把它整列吞掉了。

【目视纠正 API 草稿的 3 处】
  1. 0955 序号3 的项目是「**汞** mg/kg」, API 写成了「镉」
  2. 0954 总砷组: API 把 油脂写成 ≤7(错, 原文 ≤10), 添加剂预混合饲料写成
     ≤10(错, 原文 ≤2), 浓缩饲料写成 ≤4(错, 原文 ≤10)
  3. 0954 铅组: API 把 狐狸、貉、貂 顺序写成「狐狸、貂、貉」, 且漏了
     「配合饲料 ≤5」和「单细胞蛋白饲料原料 ≤2」
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(REPO, "minimax", "04标准及标准目录", "02_饲料卫生标准")

NCOL = 7


def td(v="", attrs="", tag="td"):
    a = (" " + attrs) if attrs else ""
    return "<%s%s>%s</%s>" % (tag, a, v, tag)


def tr(cells):
    return "<tr>%s</tr>" % "".join(cells)


# ============================================================ 页 954
HEAD1 = [
    ("序号", True), ("项目", True), ("产品名称", "colspan=\"2\""),
    ("限量", True), ("试验方法", True), ("备注", True),
]

# 页954 数据: (序号, 项目+单位, [(类别, [(具体, 限量), ...])], 试验方法)
#             类别 rowspan 按组内行数算
BLOCKS_954 = [
    ("1", "总砷 mg/kg", [
        ("饲料原料", [
            ("干草及其加工产品", "≤4"),
            ("棕榈仁饼（粕）", "≤4"),
            ("藻类及其加工产品", "≤40"),
            ("甲壳类动物及其副产品（虾油除外）、鱼虾粉、水生软体动物及其副产品", "≤15"),
            ("其他水生动物源性饲料原料（不含水生动物油脂）", "≤10"),
            ("肉粉、肉骨粉", "≤10"),
            ("石粉", "≤2"),
            ("其他矿物质饲料原料", "≤10"),
            ("油脂", "≤10"),
            ("其他饲料原料", "≤7"),
        ]),
        ("饲料产品", [
            ("添加剂预混合饲料", "≤2"),
            ("浓缩饲料", "≤10"),
            ("精料补充料", "≤4"),
            ("水产配合饲料", "≤4"),
        ]),
    ], "GB/T 13079"),
    ("2", "铅 mg/kg", [
        ("饲料原料", [
            ("单细胞蛋白饲料原料", "≤2"),
            ("矿物质饲料原料", "≤5"),
            ("饲草、粗饲料及其加工产品", "≤15"),
            ("其他饲料原料", "≤30"),
        ]),
        ("饲料产品", [
            ("添加剂预混合饲料", "≤10"),
            ("浓缩饲料", "≤40"),
            ("精料补充料", "≤10"),
            ("配合饲料", "≤8"),
        ]),
    ], "GB/T 13080"),
]

# 0954 末尾的两行(从「狐狸、貉、貂配合饲料」起)属于 序号2 铅 —— 见下
# (原图: 序号2 铅 的第一组是 饲料产品: 狐狸、貉、貂配合饲料 / 其他配合饲料)
# 逐格放大后确认顺序为:
#   序号2 铅 mg/kg
#     饲料原料: 单细胞蛋白饲料原料 ≤2 / 矿物质饲料原料 ≤5
#                饲草、粗饲料及其加工产品 ≤15 / 其他饲料原料 ≤30
#     饲料产品: 添加剂预混合饲料 ≤10 / 浓缩饲料 ≤40 / 精料补充料 ≤10
#                配合饲料 ≤8
#   —— 上面的 BLOCKS_954 已按此修正

# ============================================================ 页 955
BLOCKS_955 = [
    ("3", "汞 mg/kg", [
        ("饲料原料", [
            ("鱼、其他水生生物及其副产品类饲料原料", "≤0.5"),
            ("其他饲料原料", "≤0.5"),
        ]),
        ("饲料产品", [
            ("水产配合饲料", "≤0.1"),
            ("其他配合饲料", "≤0.5"),
        ]),
    ], "GB/T 13081"),
    ("4", "镉 mg/kg", [
        ("饲料原料", [
            ("藻类及其加工产品", "≤0.1"),
            ("植物性饲料原料", "≤2"),
            ("水生软体动物及其副产品", "≤1"),
            ("其他动物源性饲料原料", "≤75"),
            ("石粉", "≤2"),
            ("其他矿物质饲料原料", "≤0.75"),
        ]),
        ("饲料产品", [
            ("添加剂预混合饲料", "≤2"),
            ("浓缩饲料", "≤1.25"),
            ("犊牛、羔羊精料补充料", "≤0.5"),
            ("其他精料补充料", "≤1"),
            ("虾、蟹、海参、贝类配合饲料", "≤2"),
            ("水产配合饲料（虾、蟹、海参、贝类配合饲料除外）", "≤1"),
            ("其他配合饲料", "≤0.5"),
        ]),
    ], "GB/T 13082"),
    ("5", "铬 mg/kg", [
        ("饲料原料", [
            ("其他饲料原料", "≤5"),
        ]),
        ("饲料产品", [
            ("猪用添加剂预混合饲料", "≤20"),
            ("其他添加剂预混合饲料", "≤5"),
            ("猪用浓缩饲料", "≤6"),
            ("其他浓缩饲料", "≤5"),
            ("配合饲料", "≤5"),
        ]),
    ], "GB/T 13088—2006（原子吸收光谱法）"),
]


def build_table2(blocks, caption=None):
    """表1 主体。7 个列槽: 序号|项目|类别|具体产品名称|限量|试验方法|备注"""
    rows = []
    if caption:
        rows.append(tr([td(caption, 'colspan="7"', "th")]))
    rows.append("<tr>" + "".join(
        td(t, ('colspan="2"' if c == 'colspan="2"' else ""), "th")
        for t, c in HEAD1) + "</tr>")
    rows.append(tr([td("无机污染物", 'colspan="2"'), td(""), td(""),
                    td(""), td(""), td("")]))
    for seq, item, groups, method in blocks:
        nrows = sum(len(items) for _, items in groups)
        # 标记每行是不是该序号的最后一行(试验方法放在那)
        flat = []
        for cat, items in groups:
            for name, limit in items:
                flat.append((cat, name, limit))
        for idx, (cat, name, limit) in enumerate(flat):
            cells = []
            if idx == 0:
                cells.append(td(seq, 'rowspan="%d"' % nrows))
                cells.append(td(item, 'rowspan="%d"' % nrows))
            # 类别: 连续同名的合并
            # 找该类别在 flat 里的起止
            cstart = cidx = None
            for j, (c2, _, _) in enumerate(flat):
                if c2 == cat:
                    if cstart is None:
                        cstart = j
                    cidx = j
            if cstart == idx:
                span = cidx - cstart + 1
                cells.append(td(cat, 'rowspan="%d"' % span))
            cells.append(td(name))
            cells.append(td(limit))
            if idx == 0:
                cells.append(td(method, 'rowspan="%d"' % nrows))
            cells.append(td(""))
            rows.append(tr(cells))
    return "\n".join(rows)


def check(txt, must, nrows_min):
    errs = []
    for k in must:
        if k not in txt:
            errs.append("缺: " + k)
    if txt.count("<table") != 1:
        errs.append("表数 != 1")
    rows = re.findall(r"<tr>(.*?)</tr>", txt, re.S)
    if len(rows) < nrows_min:
        errs.append("行数 < %d, 实际 %d" % (nrows_min, len(rows)))
    # 展开后每行 7 列
    remain = [0] * NCOL
    for i, m in enumerate(rows, 1):
        tags = re.findall(r"<t[dh]([^>]*)>", m)
        remain = [r - 1 if r > 0 else 0 for r in remain]
        col = 0
        placed = 0
        while placed < len(tags):
            if col >= NCOL:
                break
            if remain[col] > 0:
                col += 1
                continue
            a = tags[placed]
            mc = re.search(r'colspan="(\d+)"', a)
            cs = int(mc.group(1)) if mc else 1
            mr = re.search(r'rowspan="(\d+)"', a)
            rs = int(mr.group(1)) if mr else 1
            for c in range(col, min(NCOL, col + cs)):
                remain[c] = rs
            col += cs
            placed += 1
        if placed != len(tags) or col != NCOL:
            errs.append("第 %d 行展开后列数 != 7 (放了 %d/%d 格, 到第 %d 列)"
                        % (i, placed, len(tags), col))
    return errs


MUST_954 = [
    "产品名称", "无机污染物", "总量" if False else "总砷 mg/kg",
    "干草及其加工产品", "≤4", "棕榈仁饼（粕）",
    "藻类及其加工产品", "≤40",
    "甲壳类动物及其副产品（虾油除外）、鱼虾粉、水生软体动物及其副产品", "≤15",
    "其他水生动物源性饲料原料（不含水生动物油脂）", "≤10",
    "肉粉、肉骨粉", "石粉", "≤2", "其他矿物质饲料原料",
    "油脂", "其他饲料原料", "≤7",
    "添加剂预混合饲料", "浓缩饲料", "≤10", "精料补充料", "≤4", "水产配合饲料",
    "饲料原料", "饲料产品",
    "GB/T 13079", "GB/T 13080",
    "铅 mg/kg", "单细胞蛋白饲料原料", "矿物质饲料原料", "≤5",
    "饲草、粗饲料及其加工产品", "≤15", "≤30",
    "配合饲料", "≤8", "≤40",
]

MUST_955 = [
    "产品名称", "无机污染物", "汞 mg/kg",
    "鱼、其他水生生物及其副产品类饲料原料", "≤0.5",
    "水产配合饲料", "≤0.1", "其他配合饲料", "≤0.5",
    "GB/T 13081",
    "镉 mg/kg", "藻类及其加工产品", "植物性饲料原料", "≤2",
    "水生软体动物及其副产品", "≤1", "其他动物源性饲料原料", "≤75",
    "其他矿物质饲料原料", "≤0.75", "≤1.25",
    "犊牛、羔羊精料补充料", "其他精料补充料",
    "虾、蟹、海参、贝类配合饲料",
    "水产配合饲料（虾、蟹、海参、贝类配合饲料除外）",
    "GB/T 13082",
    "铬 mg/kg", "猪用添加剂预混合饲料", "≤20", "其他添加剂预混合饲料",
    "猪用浓缩饲料", "≤6", "其他浓缩饲料", "配合饲料", "≤5",
    "GB/T 13088—2006（原子吸收光谱法）",
    "饲料原料", "饲料产品",
]


def main():
    ok = True
    for name, blocks, must, cap, cont in (
            ("0954", BLOCKS_954, MUST_954, "表1 饲料卫生指标及试验方法", False),
            ("0955", BLOCKS_955, MUST_955, "表1（续表）", True)):
        tbl = build_table2(blocks, cap)
        parts = []
        parts.append('<table border="1">')
        parts.append(tbl)
        parts.append("</table>")
        txt = "\n".join(parts) + "\n"
        errs = check(txt, must, 5)
        if errs:
            ok = False
            print("!! %s 质量门未过:" % name)
            for e in errs:
                print("   -", e)
            continue
        out = os.path.join(OUTDIR, name + ".md")
        open(out, "w", encoding="utf-8").write(txt)
        print("OK %s -> %s (%d 字节, 1 表)" %
              (name, os.path.relpath(out, REPO), len(txt.encode("utf-8"))))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
