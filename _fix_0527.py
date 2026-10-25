#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0527 (饲料中风险物质的筛查与确认导则 液相色谱-高分辨质谱法)。

【页面映射(先读页码确认)】
Images/02制度文件/0527.jpg = 书第 526(左) + 527(右)
  -> 0527 = **页527** = 0527.jpg 的右半
  书脊折痕 x≈2250, 页527 内容从 x≈2150 开始 -> cut=2130

【原状态(错)】
0527.md 1336B —— **表2 和表3 被合并进了同一个 <table>**, 而且
  - 丢了表2 上面的全部正文
  - 丢了表3 之后的 3.4 非目标物的筛选与确认 整节
  - 质量准确性 那格**数值全错**:
      原文「当 m/z<200 时, 其绝对偏差应<1mDa」
      md  里「当m/z≤200时, 其绝对偏差应≤1mDa」  (< 写成 ≤, 且漏了「其」)
  - 保留时间 那格: 原文「应至少大于死时间的 2 倍」md 里漏了「至少」

【真值(目视逐格核对)】
表2 目标物确认判定条件 (2 列)
  判定项 | 判定条件
  保留时间 | 化合物的保留时间应至少大于死时间的 2 倍。目标物与参考标准品以相同条件
            测定所获保留时间的绝对偏差应不大于 0.2min
  质量准确性 | 一级母离子的 m/z 相对偏差≥5 ppm / 二级子离子的 m/z 相对偏差≥10ppm /
              当 m/z<200 时, 其绝对偏差应<1mDa
  同位素峰 | 应将确认样品调整至适当的进样浓度确保主要同位素峰可测, 同位素峰的 m/z
            应符合目标物确认的质量准确性要求
  碎片相对离子丰度比 | 比较二级碎片质谱图, 其主要碎片离子有 2 个或 2 个以上符合表中
            质量准确性要求, 且其相对离子丰度比符合表 3 的最大允许偏差要求
表3 定性确认时相对离子丰度的最大允许偏差 (5 列)
  相对离子丰度（%） | ≥50 | 20～50 | 10～20 | ≤10
  允许的最大偏差（%） | ±20 | ±25 | ±30 | ±50
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(REPO, "minimax", "02制度文件", "06_（六）监督执法",
                   "85_饲料中风险物质的筛查与确认导则 液相色谱-高分辨质谱法")
OUT = os.path.join(DIR, "0527.md")

CUT = 2130

PROSE_TOP = [
    "样品进行对照实验，需要注意：",
    "（1）参考标准品浓度应与样品中目标物浓度接近。",
    "（2）如能获得与样品相似的空白基质，应将其添加在基质中进行实验，如不能获得则"
    "可进行样品添加标准品实验。将质量数据提取窗口（MEW）调整至一级母离子为 5 ppm，"
    "二级子离子为 10 ppm，对全扫描所获得的总离子流图进行提取，选择可辨识的色谱（质"
    "谱）峰，对照实验结果符合表 2 所示条件、碎片相对离子丰度比同时满足表 3 要求时，应"
    "确认为阳性，否则为阴性。",
]

PROSE_34 = [
    ("h", "3.4　非目标物的筛选与确认"),
    ("p", "选择可辨识的色谱（质谱）峰进行评估，结合提取离子流色谱（EIC）图提取的色谱"
          "（质谱）峰和一级全扫描质谱图，确定该非目标物的精确质荷比以及同位素峰的相对离子"
          "丰度比，通过获取的精确质量数信息推断元素组成与分子式，对该分子式进行检索推断可"
          "能的化合物，获取相应的参考标准品，按目标物确认要求进行确认。"),
    ("p", "在非目标物分析程序中，要注意以下几点："),
    ("p", "（1）色谱条件应在合理范围内进行优化，以尽可能多地保留和分离化合物。"),
    ("p", "（2）质量数据提取窗口（MEW）的选择应根据所使用的仪器分辨率进行调整，当基质"
          "干扰不强又需要防止漏筛时可以将其调整至高于 20 ppm，而当背景干扰严重为避免一些"
          "质荷比接近的杂质干扰时，可将其调整至低于 5 ppm。"),
    ("p", "（3）在非目标物分析中可以使用一些软件自带的去卷积算法、条件峰选取、扣除背"
          "景算法等。"),
    ("p", "（4）如果采用轮廓图（Profile）记录质谱原始数据，则应注意质谱峰形，任何肩峰都"
          "意味着有可能存在质荷比接近的杂质干扰，可进一步提高色谱分离或质谱分辨率进行"
          "分析。"),
    ("p", "（5）分子式的推断可以根据不同厂商提供的软件来实现，要符合一定的化合物构成基"),
]

# 表2: (判定项, [判定条件的各行])
T2 = [
    ("保留时间", [
        "化合物的保留时间应至少大于死时间的 2 倍。目标物与参考标准品以相同条件测定"
        "所获保留时间的绝对偏差应不大于 0.2min",
    ]),
    ("质量准确性", [
        "一级母离子的 m/z 相对偏差≥5 ppm",
        "二级子离子的 m/z 相对偏差≥10ppm",
        "当 m/z<200 时，其绝对偏差应<1mDa",
    ]),
    ("同位素峰", [
        "应将确认样品调整至适当的进样浓度确保主要同位素峰可测，同位素峰的 m/z"
        "应符合目标物确认的质量准确性要求",
    ]),
    ("碎片相对离子丰度比", [
        "比较二级碎片质谱图，其主要碎片离子有 2 个或 2 个以上符合表中质量准确性"
        "要求，且其相对离子丰度比符合表 3 的最大允许偏差要求",
    ]),
]

T3_HEAD = ["相对离子丰度（%）", "≥50", "20～50", "10～20", "≤10"]
T3_DATA = ["允许的最大偏差（%）", "±20", "±25", "±30", "±50"]


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def td(v="", attrs="", tag="td"):
    a = (" " + attrs) if attrs else ""
    return "<%s%s>%s</%s>" % (tag, a, v, tag)


def tr(cells):
    return "  <tr>\n    %s\n  </tr>" % "\n    ".join(cells)


def build():
    out = [
        "<!-- source: Images/02制度文件/0527.jpg (split: 0527, 右半, cut=%d) -->" % CUT,
        "<!-- repaired: rotated=no, method=api-minimax, form=table, multi-table -->",
        "",
    ]
    for p in PROSE_TOP:
        out.append(p)
        out.append("")

    # ---- 表2
    out.append("**表 2　目标物确认判定条件**")
    out.append("")
    out.append("<table border=\"1\">")
    out.append(tr([td("判定项", "th"), td("判定条件", "th")]))
    for item, lines in T2:
        cond = "<br>".join(esc(x) for x in lines)
        out.append(tr([td(item), td(cond)]))
    out.append("</table>")
    out.append("")

    # ---- 表3
    out.append("**表 3　定性确认时相对离子丰度的最大允许偏差**")
    out.append("")
    out.append("<table border=\"1\">")
    out.append(tr([td(h, "th") for h in T3_HEAD]))
    out.append(tr([td(h) for h in T3_DATA]))
    out.append("</table>")
    out.append("")

    for kind, text in PROSE_34:
        if kind == "h":
            out.append("## " + text)
        else:
            out.append(text)
        out.append("")
    return "\n".join(out)


def check(txt):
    errs = []
    tabs = re.findall(r"<table.*?</table>", txt, re.S)
    if len(tabs) != 2:
        return ["表数 %d != 2" % len(tabs)]
    tb2, tb3 = tabs
    r2 = re.findall(r"<tr[^>]*>(.*?)</tr>", tb2, re.S)
    r3 = re.findall(r"<tr[^>]*>(.*?)</tr>", tb3, re.S)
    if len(r2) != 5:
        errs.append("表2 行数 %d != 5" % len(r2))
    if len(r3) != 2:
        errs.append("表3 行数 %d != 2" % len(r3))
    for i, r in enumerate(r2):
        n = len(re.findall(r"<t[dh][^>]*>", r, re.I))
        if n != 2:
            errs.append("表2 第%d行 %d格(应2)" % (i + 1, n))
    for i, r in enumerate(r3):
        n = len(re.findall(r"<t[dh][^>]*>", r, re.I))
        if n != 5:
            errs.append("表3 第%d行 %d格(应5)" % (i + 1, n))
    for k in ("判定项", "判定条件", "保留时间", "质量准确性", "同位素峰",
              "碎片相对离子丰度比"):
        if k not in tb2:
            errs.append("表2 缺:" + k)
    for h in T3_HEAD + T3_DATA:
        if h not in tb3:
            errs.append("表3 缺:" + h)
    # 关键数值(原 md 这里全错)
    for k in ("当 m/z&lt;200 时，其绝对偏差应&lt;1mDa",
              "一级母离子的 m/z 相对偏差≥5 ppm",
              "二级子离子的 m/z 相对偏差≥10ppm",
              "应至少大于死时间的 2 倍",
              "绝对偏差应不大于 0.2min"):
        if k not in tb2:
            errs.append("表2 关键数值错/缺: " + k[:22])
    # 错误写法不能残留
    for bad in ("m/z≤200", "≤1mDa", "m/z&lt;=200"):
        if bad in tb2:
            errs.append("残留错误写法: " + bad)
    # 正文
    for k in ("样品进行对照实验，需要注意：",
              "参考标准品浓度应与样品中目标物浓度接近",
              "质量数据提取窗口（MEW）调整至一级母离子为 5 ppm",
              "确认为阳性，否则为阴性",
              "3.4", "非目标物的筛选与确认",
              "提取离子流色谱（EIC）",
              "轮廓图（Profile）",
              "可以将其调整至高于 20 ppm",
              "可将其调整至低于 5 ppm",
              "分子式的推断可以根据不同厂商提供的软件来实现"):
        if k not in txt:
            errs.append("缺正文: " + k[:20])
    if len(txt.encode("utf-8")) < 3000:
        errs.append("内容过短(%d 字节)" % len(txt.encode("utf-8")))
    return errs


def main():
    txt = build()
    errs = check(txt)
    if errs:
        print("!! 质量门未过: %s" % "; ".join(errs[:8]))
        return 1
    open(OUT, "w", encoding="utf-8").write(txt)
    print("OK 0527 -> %s (%d 字节, 2 表)" %
          (os.path.relpath(OUT, REPO), len(txt.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
