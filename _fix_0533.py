#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0533 (饲料中风险物质的目标物筛查与确认 液相色谱-高分辨质谱法)。

【页面映射(先读页码确认)】
Images/02制度文件/0533.jpg = 书第 532(左) + 533(右)
  -> 0533 = **页533** = 0533.jpg 的右半
  书脊折痕 x≈2250, 页533 内容从 x≈2150 开始 -> cut=2130

【原状态(残缺)】
0533.md 1963B —— **只有表2**, 丢了:
  - 表2 上面的全部正文(4.1 目标物筛查 概述/4.2 参考条件 等)
  - 4.2.2 高分辨质谱参考条件 a)~d)
  - 4.2.3 高分辨质谱谱库建库要求
  - 4.3 筛查
  - **整张表3 筛查判定条件**
表2 本身的值是对的(时间/min | 0.5%甲酸水溶液/% | 0.5%甲酸乙腈溶液/%, 7 行)。

【表3 真值(目视逐格核对, 不等号方向很重要)】
表3 筛查判定条件 (2 列)
  判别项 | 判定条件
  采样点数 | 单个目标物峰不少于 5 个采样点
  信号响应要求 | 1) 信噪比（S/N）存在时，应使 S/N≥3
               2) 当 S/N 不存在时，以 95%置信度水平上可准确定性该化合物的最低检
                  测浓度作为检测限
  质量准确性 | 1) 一级母离子 m/z≥200 时，其相对偏差应≤10 ppm
               2) 一级母离子 m/z<200 时，其绝对偏差应<1mDa
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(REPO, "minimax", "02制度文件", "06_（六）监督执法",
                   "86_饲料中风险物质的目标物筛查与确认 液相色谱-高分辨质谱法")
OUT = os.path.join(DIR, "0533.md")

CUT = 2130

# ---- 表2: (时间/min, 0.5%甲酸水溶液/%, 0.5%甲酸乙腈溶液/%)
T2_ROWS = [
    ("0", "10", "90"),
    ("0.50", "10", "90"),
    ("1.00", "40", "60"),
    ("7.00", "90", "10"),
    ("9.00", "90", "10"),
    ("9.01", "10", "90"),
    ("10.00", "10", "90"),
]
T2_HEAD = ["时间/min", "0.5%甲酸水溶液/%", "0.5%甲酸乙腈溶液/%"]
# 表2 的表头是**两行**的:
#   第 1 行: 时间/min (rowspan=2) | ESI⁺扫描模式（适用于序号 421—447 化合物）(colspan=2)
#   第 2 行:                     | 0.5%甲酸水溶液/% | 0.5%甲酸乙腈溶液/%
T2_HEAD_ROW1 = ["时间/min", "ESI⁺扫描模式（适用于序号 421—447 化合物）"]
T2_HEAD_ROW2 = ["0.5%甲酸水溶液/%", "0.5%甲酸乙腈溶液/%"]

# ---- 表3: (判别项, [判定条件的各行])
T3_ROWS = [
    ("采样点数", ["单个目标物峰不少于 5 个采样点"]),
    ("信号响应要求", [
        "1) 信噪比（S/N）存在时，应使 S/N≥3",
        "2) 当 S/N 不存在时，以 95%置信度水平上可准确定性该化合物的最低检测浓度"
        "作为检测限",
    ]),
    ("质量准确性", [
        "1) 一级母离子 m/z≥200 时，其相对偏差应≤10 ppm",
        "2) 一级母离子 m/z<200 时，其绝对偏差应<1mDa",
    ]),
]

PROSE = [
    ("h", "4.2.2　高分辨质谱参考条件"),
    ("p", "a) 电离模式：电喷雾电离。"),
    ("p", "b) 扫描方式：正、负离子切换扫描或分别扫描；全扫描/数据依赖二级扫描，"
          "或效果相当的其他扫描模式。"),
    ("p", "c) MS 扫描范围：m/z 50～1 000。"),
    ("p", "d) MS/MS 扫描范围：m/z 50～1 000。"),
    ("h", "4.2.3　高分辨质谱谱库建库要求"),
    ("p", "化合物谱库（列表）应包含化合物中英文通用名称、分子式、CAS 号、主要母离子"
          "（分子离子、质子化离子/去质子化离子或加成离子）的精确质荷比、2 个以上特征碎片"
          "离子的精确质荷比、特征碎片离子的相对丰度比和保留时间。采用 500～1 000ng/mL 的"
          "标准工作液在数据依赖模式下采集二级碎片质谱图，母离子质量相对偏差应≤5 ppm，"
          "二级碎片离子相对偏差应≤10 ppm。碰撞能量的设置应采用高、中、低不同的碰撞能量，"
          "以获得更为丰富的碎片离子。"),
    ("h", "4.3　筛查"),
    ("p", "将质量数据提取窗又调整至一级母离子为 10 ppm，二级子离子为 20 ppm，对全扫描"
          "所获得的总离子流图进行提取，选择可辨识的色谱（质谱）峰，将其与经验证的目标化"
          "合物库中的化合物信息进行对比。对比结果同时符合表 3 中所示条件时，可认为筛查"
          "到疑似阳性样品。"),
]


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def td(v="", attrs="", tag="td"):
    a = (" " + attrs) if attrs else ""
    return "<%s%s>%s</%s>" % (tag, a, v, tag)


def tr(cells):
    return "  <tr>\n    %s\n  </tr>" % "\n    ".join(cells)


def build():
    out = [
        "<!-- source: Images/02制度文件/0533.jpg (split: 0533, 右半, cut=%d) -->" % CUT,
        "<!-- repaired: rotated=no, method=api-minimax, form=table, multi-table -->",
        "",
        "**表 2　BEH Amide 色谱柱梯度洗脱程序表**",
        "",
        "<table border=\"1\">",
        # 两行表头: 时间/min 跨 2 行, ESI+扫描模式 跨 2 列
        tr([td("时间/min", 'rowspan="2"', "th"),
            td("ESI⁺扫描模式（适用于序号 421—447 化合物）", 'colspan="2"', "th")]),
        tr([td(h, "th") for h in T2_HEAD_ROW2]),
    ]
    for r in T2_ROWS:
        out.append(tr([td(x) for x in r]))
    out.append("</table>")
    out.append("")

    for kind, text in PROSE:
        if kind == "h":
            out.append("## " + text)
        else:
            out.append(text)
        out.append("")

    out.append("**表 3　筛查判定条件**")
    out.append("")
    out.append("<table border=\"1\">")
    out.append(tr([td("判别项", "th"), td("判定条件", "th")]))
    for item, lines in T3_ROWS:
        cond = "<br>".join(esc(x) for x in lines)
        out.append(tr([td(item), td(cond)]))
    out.append("</table>")
    out.append("")
    return "\n".join(out)


def expand_rows(raws):
    """展开 rowspan/colspan, 返回每行实际占用的列数。"""
    grid = {}
    out = []
    for r in raws:
        cells = re.findall(r"<t[dh]([^>]*)>(.*?)</t[dh]>", r, re.S | re.I)
        occupied = {c for c, rem in grid.items() if rem > 0}
        col = 0
        last = -1
        new_grid = {}
        for attrs, _body in cells:
            while col in occupied:
                col += 1
            cs = re.search(r'colspan\s*=\s*["\']?(\d+)', attrs, re.I)
            span = int(cs.group(1)) if cs else 1
            rs = re.search(r'rowspan\s*=\s*["\']?(\d+)', attrs, re.I)
            rspan = int(rs.group(1)) if rs else 1
            for k in range(span):
                if rspan > 1:
                    new_grid[col + k] = rspan - 1
            last = max(last, col + span - 1)
            col += span
        for c, rem in grid.items():
            if rem > 1:
                new_grid[c] = rem - 1
        grid = new_grid
        allcols = set(occupied) | set(range(0, last + 1))
        out.append(((max(allcols) + 1) if allcols else 0, None))
    return out


def check(txt):
    errs = []
    tabs = re.findall(r"<table.*?</table>", txt, re.S)
    if len(tabs) != 2:
        return ["表数 %d != 2" % len(tabs)]
    tb2, tb3 = tabs
    r2 = re.findall(r"<tr[^>]*>(.*?)</tr>", tb2, re.S)
    r3 = re.findall(r"<tr[^>]*>(.*?)</tr>", tb3, re.S)
    if len(r2) != 9:
        errs.append("表2 行数 %d != 9" % len(r2))
    if len(r3) != 4:
        errs.append("表3 行数 %d != 4" % len(r3))
    for i, r in enumerate(r2):
        n = len(re.findall(r"<t[dh][^>]*>", r, re.I))
        # 表头 2 行本来就是 2 格(靠 rowspan/colspan 撑开), 不能直接数
        if i >= 2 and n != 3:
            errs.append("表2 第%d行 %d格(应3)" % (i + 1, n))
    # 展开后每行都应是 3 列
    for i, (ncols, _pl) in enumerate(expand_rows(r2)):
        if ncols != 3:
            errs.append("表2 第%d行展开后 %d 列(应3)" % (i + 1, ncols))
    for i, r in enumerate(r3):
        n = len(re.findall(r"<t[dh][^>]*>", r, re.I))
        if n != 2:
            errs.append("表3 第%d行 %d格(应2)" % (i + 1, n))
    # 表2 两行表头
    for h in T2_HEAD_ROW2:
        if h not in tb2:
            errs.append("表2 缺表头:" + h)
    if 'rowspan="2">时间/min' not in tb2:
        errs.append("时间/min 缺 rowspan=2")
    if "ESI⁺扫描模式（适用于序号 421—447 化合物）" not in tb2:
        errs.append("表2 缺表头:ESI+扫描模式")
    for k in ("判别项", "判定条件", "采样点数", "信号响应要求", "质量准确性"):
        if k not in tb3:
            errs.append("表3 缺:" + k)
    # 表2 数值逐个核对
    for t, a, b in T2_ROWS:
        if "<td>%s</td>" % t not in tb2 or "<td>%s</td>" % a not in tb2 \
                or "<td>%s</td>" % b not in tb2:
            errs.append("表2 数值缺失: %s/%s/%s" % (t, a, b))
    # 表3 关键数值(不等号方向)
    for k in ("单个目标物峰不少于 5 个采样点",
              "信噪比（S/N）存在时，应使 S/N≥3",
              "以 95%置信度水平上可准确定性该化合物的最低检测浓度",
              "一级母离子 m/z≥200 时，其相对偏差应≤10 ppm",
              "一级母离子 m/z&lt;200 时，其绝对偏差应&lt;1mDa"):
        if k not in tb3:
            errs.append("表3 关键数值错/缺: " + k[:24])
    # 正文
    for k in ("4.2.2", "高分辨质谱参考条件", "电喷雾电离",
              "正、负离子切换扫描或分别扫描",
              "MS 扫描范围：m/z 50～1 000",
              "MS/MS 扫描范围：m/z 50～1 000",
              "4.2.3", "高分辨质谱谱库建库要求",
              "化合物谱库（列表）应包含化合物中英文通用名称、分子式、CAS 号",
              "母离子质量相对偏差应≤5 ppm",
              "二级碎片离子相对偏差应≤10 ppm",
              "4.3", "筛查",
              "一级母离子为 10 ppm，二级子离子为 20 ppm",
              "可认为筛查到疑似阳性样品"):
        if k not in txt:
            errs.append("缺正文: " + k[:22])
    if len(txt.encode("utf-8")) < 2200:
        errs.append("内容过短(%d 字节)" % len(txt.encode("utf-8")))
    return errs


def main():
    txt = build()
    errs = check(txt)
    if errs:
        print("!! 质量门未过: %s" % "; ".join(errs[:8]))
        return 1
    open(OUT, "w", encoding="utf-8").write(txt)
    print("OK 0533 -> %s (%d 字节, 2 表)" %
          (os.path.relpath(OUT, REPO), len(txt.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
