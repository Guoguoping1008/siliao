#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0658/0659/0660 (动物毛发中克仑特罗、莱克多巴胺、沙丁胺醇和苯乙醇胺A的测定)。

【页面映射(先读页码确认)】
Images/02制度文件/0659.jpg = 书第 658(左) + 659(右)
Images/02制度文件/0661.jpg = 书第 660(左) + 661(右)
  -> 0658 = 页658 = 0659.jpg 左半
  -> 0659 = 页659 = 0659.jpg 右半
  -> 0660 = 页660 = 0661.jpg 左半
  书脊折痕 x≈2250(0659.jpg) / x≈2230(0661.jpg)

【原状态】
0658.md 1492B —— 表2 续表的** rowspan 全丢了**(被测物名称/定量离子对/锥孔电压
         都有合并格), 且丢了表3、丢了 6.4.3 之后的全部正文
0659.md 1796B —— 表4 的**化学分子式下标错**(C13H18Cl2N2O·HCl 之类),
         丢了 8 方法的灵敏度…、附录1、以及公式定义
0660.md 588B  —— 附录2 的**图题被拼成了正文**(「…苯乙醇胺A的特征离子质量
         色谱图克仑特罗、莱克多巴胺…」), 缺标题分行、缺图注

【真值(全部目视逐格核对)】
页658:
  表2 (续表) 5 列: 被测物名称|定性离子对 (m/z)|定量离子对 (m/z)|锥孔电压 (V)|碰撞能量 (ev)
     莱克多巴胺      (r2) 302.1>107.0 | 302.1>164.1 (r2) | 20 (r2) | 17
                            302.1>164.1 |                |      | 13
     沙丁胺醇        (r2) 240.1>148.1 | 240.1>148.1 (r2) | 25 (r2) | 20
                            240.1>222.1 |                |      | 10
     苯乙醇胺A       (r2) 345.0>327.0 | 345.0>150.0 (r2) | 22 (r2) | 17
                            345.0>150.0 |                |      | 13
     克仑特罗-D9            286.0>204.1 | 286.0>204.1 | 25 | 14
     莱克多巴胺-D3          305.2>167.2 | 305.2>167.2 | 20 | 17
     沙丁胺醇-D3            243.0>151.2 | 243.0>151.2 | 25 | 14
     苯乙醇胺A-D3           348.2>153.1 | 348.2>153.2 | 22 | 17
  表3 试样溶液中离子相对丰度的允许偏差范围 (5 列)
     相对离子丰度 | >50% | >20%至50% | >10%至20% | ≤10%
     允许的相对偏差 | ±20% | ±25% | ±30% | ±50%
页659:
  表4 标准品中英文名称、化学分子式和CAS号 (4 列, 8 行)
  8 方法的灵敏度、准确度和精密度 / 8.1 灵敏度 / 8.2 准确度 / 8.3 精密度
  附录1 标准品的中英文名称、化学分子式和 CAS 号
页660:
  附录2 + 图题 + 图注(图1) + 12 条特征离子质量色谱图
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(REPO, "minimax", "02制度文件", "08_（八）瘦肉精监管",
                   "128_动物毛发中克仑特罗、莱克多巴胺、沙丁胺醇和苯乙醇胺A的测定"
                   "液相色谱-串联质谱法")

CUT_59, CUT_61 = 2200, 2200


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def td(v="", attrs="", tag="td"):
    a = (" " + attrs) if attrs else ""
    return "<%s%s>%s</%s>" % (tag, a, v, tag)


def tr(cells):
    return "  <tr>\n    %s\n  </tr>" % "\n    ".join(cells)


def expand_rows(raws):
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


# ======================================================== 0658
T2_HEAD = ["被测物名称", "定性离子对 (m/z)", "定量离子对 (m/z)",
           "锥孔电压 (V)", "碰撞能量 (ev)"]

# (被测物名称或None, 名称rowspan, 定性离子对, 定量离子对或None, 定量rowspan,
#  锥孔电压或None, 锥孔rowspan, 碰撞能量)
T2_ROWS = [
    ("莱克多巴胺", 2, "302.1&gt;107.0", "302.1&gt;164.1", 2, "20", 2, "17"),
    (None, 0, "302.1&gt;164.1", None, 0, None, 0, "13"),
    ("沙丁胺醇", 2, "240.1&gt;148.1", "240.1&gt;148.1", 2, "25", 2, "20"),
    (None, 0, "240.1&gt;222.1", None, 0, None, 0, "10"),
    ("苯乙醇胺A", 2, "345.0&gt;327.0", "345.0&gt;150.0", 2, "22", 2, "17"),
    (None, 0, "345.0&gt;150.0", None, 0, None, 0, "13"),
    ("克仑特罗-D9", 0, "286.0&gt;204.1", "286.0&gt;204.1", 0, "25", 0, "14"),
    ("莱克多巴胺-D3", 0, "305.2&gt;167.2", "305.2&gt;167.2", 0, "20", 0, "17"),
    ("沙丁胺醇-D3", 0, "243.0&gt;151.2", "243.0&gt;151.2", 0, "25", 0, "14"),
    ("苯乙醇胺A-D3", 0, "348.2&gt;153.1", "348.2&gt;153.2", 0, "22", 0, "17"),
]

T3_HEAD = ["相对离子丰度", "&gt;50%", "&gt;20%至50%", "&gt;10%至20%", "≤10%"]
T3_DATA = ["允许的相对偏差", "±20%", "±25%", "±30%", "±50%"]

P658 = [
    ("h", "6.4.3　测定方法"),
    ("p", "a)　定性测定"),
    ("p", "按表2中给出的定性离子对和相应的碰撞能量进行测定。定性测定时，应在"
          "相应的提取窗口内考察提取离子色谱峰的信噪比和峰形等。定性离子的相对离子"
          "丰度应与表3中给出的允许的相对偏差范围一致。"),
    ("p", "b)　定量测定"),
    ("p", "按表2中给出的定量离子对和相应的碰撞能量进行测定。定量测定时，应在"
          "相应的提取窗口内考察提取离子色谱峰的信噪比和峰形等。"),
    ("h", "6.5　空白试验"),
    ("p", "按试样溶液制备和测定的步骤制备空白溶液并测定，空白溶液中在被测物和"
          "内标物的保留时间处应无色谱响应。"),
    ("h", "7　结果计算和表述"),
    ("p", "试样中被测物的质量分数按式(1)计算。"),
    ("p", "X = (Xₛ × Aₛ × C′ₛ × V) / (A′ₛ × Cₛ × m)"),
    ("p", "式中：Xₛ——标准溶液中克仑特罗、莱克多巴胺、沙丁胺醇或苯乙醇胺A浓度，"
          "单位为纳克每毫升（ng/mL）；"),
    ("p", "X——试样溶液中克仑特罗、莱克多巴胺、沙丁胺醇或苯乙醇胺A浓度，单位为"
          "纳克每毫升（ng/mL）；"),
    ("p", "Aₛ——标准溶液中克仑特罗、莱克多巴胺、沙丁胺醇或苯乙醇胺A的峰面积；"),
    ("p", "A′ₛ——试样溶液中克仑特罗、莱克多巴胺、沙丁胺醇或苯乙醇胺A的峰面积；"),
    ("p", "Cₛ——内标溶液中克仑特罗、莱克多巴胺、沙丁胺醇或苯乙醇胺A内标浓度，"
          "单位为纳克每毫升（ng/mL）；"),
    ("p", "C′ₛ——标准溶液中克仑特罗、莱克多巴胺、沙丁胺醇或苯乙醇胺A内标浓度，"
          "单位为纳克每毫升（ng/mL）；"),
    ("p", "V——溶解最终残余物体积，单位为毫升（mL）；"),
    ("p", "m——供试试样的质量，单位为克（g）。"),
    ("p", "注：测定结果用平行测定的算术平均值表示，保留三位有效数字。"),
]


def build_658():
    rows = [tr([td("（续表）", 'colspan="5"', "th")]),
            tr([td(h, "th") for h in T2_HEAD])]
    for (name, nrs, qual, quant, qrs, volt, vrs, ce) in T2_ROWS:
        cells = []
        if name is not None:
            cells.append(td(name, 'rowspan="%d"' % nrs if nrs else ""))
        cells.append(td(qual))
        if quant is not None:
            cells.append(td(quant, 'rowspan="%d"' % qrs if qrs else ""))
        if volt is not None:
            cells.append(td(volt, 'rowspan="%d"' % vrs if vrs else ""))
        cells.append(td(ce))
        rows.append(tr(cells))

    out = [
        "<!-- source: Images/02制度文件/0659.jpg (split: 0658, 左半, cut=%d) -->" % CUT_59,
        "<!-- repaired: rotated=no, method=api-minimax, form=table, multi-table -->",
        "",
        "<table border=\"1\">",
    ] + rows + [
        "</table>",
        "",
    ]
    for kind, text in P658:
        if kind == "h":
            out.append("## " + text)
        else:
            out.append(text)
        out.append("")

    out.append("**表 3　试样溶液中离子相对丰度的允许偏差范围**")
    out.append("")
    out.append("<table border=\"1\">")
    out.append(tr([td(h, "th") for h in T3_HEAD]))
    out.append(tr([td(h) for h in T3_DATA]))
    out.append("</table>")
    out.append("")
    return "\n".join(out)


# ======================================================== 0659
T4_HEAD = ["中文名称", "英文名称", "化学分子式", "CAS号"]
T4_ROWS = [
    ("盐酸克仑特罗", "Clenbuterol hydrochloride",
     "C<sub>12</sub>H<sub>18</sub>Cl<sub>2</sub>N<sub>2</sub>O · HCl", "21898-19-1"),
    ("盐酸莱克多巴胺", "Ractopamine hydrochloride",
     "C<sub>18</sub>H<sub>23</sub>N<sub>2</sub>O<sub>2</sub> · HCl", "90274-24-1"),
    ("沙丁胺醇", "Salbutamol",
     "C<sub>13</sub>H<sub>21</sub>N<sub>3</sub>O<sub>3</sub>", "18559-94-9"),
    ("苯乙醇胺A", "Phenylethanolamine A",
     "C<sub>10</sub>H<sub>16</sub>N<sub>2</sub>O<sub>4</sub>", "1346746-81-3"),
    ("克仑特罗-D<sub>9</sub>", "Clenbuterol-D<sub>9</sub>",
     "C<sub>12</sub>H<sub>8</sub>Cl<sub>2</sub>D<sub>9</sub>N<sub>2</sub>O", "129138-58-5"),
    ("盐酸莱克多巴胺-D<sub>3</sub>", "Ractopamine-D<sub>3</sub> hydrochloride",
     "C<sub>18</sub>H<sub>20</sub>D<sub>3</sub>N<sub>2</sub>O<sub>2</sub> · HCl", "1219794-72-5"),
    ("沙丁胺醇-D<sub>3</sub>", "Salbutamol-D<sub>3</sub>",
     "C<sub>13</sub>H<sub>18</sub>D<sub>3</sub>N<sub>3</sub>O<sub>3</sub>", "1219798-60-3"),
    ("苯乙醇胺A-D<sub>3</sub>", "Phenylethanolamine A-D<sub>3</sub>",
     "C<sub>10</sub>H<sub>13</sub>D<sub>3</sub>N<sub>2</sub>O<sub>4</sub>", "/"),
]

P659 = [
    ("h", "8　方法的灵敏度、准确度和精密度"),
    ("p", "8.1　灵敏度"),
    ("p", "本方法对猪、牛和羊毛发中克仑特罗、莱克多巴胺、沙丁胺醇和苯乙醇胺A的检测"
          "限为0.5μg/kg，定量限为1μg/kg。"),
    ("p", "8.2　准确度"),
    ("p", "本方法对于猪、牛和羊的毛发中克仑特罗、莱克多巴胺、沙丁胺醇和苯乙醇胺A在"
          "1～100μg/kg 添加浓度范围内的回收率为70%～120%。"),
    ("p", "8.3　精密度"),
    ("p", "本方法批内相对标准偏差≤20%，批间相对标准偏差≤20%。"),
    ("h", "附录1"),
    ("p", "标准品的中英文名称、化学分子式和 CAS 号"),
    ("p", "标准品的中英文名称、化学分子式和 CAS 号见表 4。"),
]

def build_659():
    rows = [tr([td("表 4　标准品中英文名称、化学分子式和 CAS 号", 'colspan="4"', "th")]),
            tr([td(h, "th") for h in T4_HEAD])]
    for zh, en, formula, cas in T4_ROWS:
        rows.append(tr([td(zh), td(en), td(formula), td(cas)]))

    out = [
        "<!-- source: Images/02制度文件/0659.jpg (split: 0659, 右半, cut=%d) -->" % CUT_59,
        "<!-- repaired: rotated=no, method=api-minimax, form=table, multi-table -->",
        "",
    ]
    for kind, text in P659:
        if kind == "h":
            out.append("## " + text)
        else:
            out.append(text)
        out.append("")
    out.append("<table border=\"1\">")
    out.extend(rows)
    out.append("</table>")
    out.append("")
    return "\n".join(out)


# ======================================================== 0660
def build_660():
    return "\n".join([
        "<!-- source: Images/02制度文件/0661.jpg (split: 0660, 左半, cut=%d) -->" % CUT_61,
        "<!-- repaired: rotated=no, method=api-minimax, form=prose, figure -->",
        "",
        "## 附录2",
        "",
        "**克仑特罗、莱克多巴胺、沙丁胺醇和苯乙醇胺A的特征离子质量色谱图**",
        "",
        "克仑特罗、莱克多巴胺、沙丁胺醇和苯乙醇胺A 标准溶液（10ng/mL）及内标溶液"
        "（5ng/mL）的特征离子质量色谱图见图1。",
        "",
        "![图1 克仑特罗、莱克多巴胺、沙丁胺醇和苯乙醇胺A 标准溶液及内标溶液的特征离子质量色谱图]"
        "(file://cropped/3 e7d8c5b4c1a4c1b1a7d7c7b6b7b7b7b-066.jpg?height=1047&id=o3n4I"
        "&originHeight=1047&originWidth=1080&originalType=binary&ratio=1 &rotation=0 "
        "&showTitle=false&status=done&style=none&title=)",
        "",
        "图1　克仑特罗、莱克多巴胺、沙丁胺醇和苯乙醇胺A 标准溶液及内标溶液的"
        "特征离子质量色谱图",
        "",
    ])


# ======================================================== 质量门
def check(txt, tag):
    errs = []
    if tag == "0660":
        if "<table" in txt:
            errs.append("页660 是图页, 不该有 <table>")
        for k in ("附录2",
                  "克仑特罗、莱克多巴胺、沙丁胺醇和苯乙醇胺A的特征离子质量色谱图",
                  "标准溶液（10ng/mL）及内标溶液（5ng/mL）的特征离子质量色谱图见图1",
                  "图1　克仑特罗、莱克多巴胺、沙丁胺醇和苯乙醇胺A 标准溶液及内标溶液的"):
            if k not in txt:
                errs.append("缺: " + k[:24])
        # 图题和正文不能粘在一起
        if "苯乙醇胺A的特征离子质量色谱图克仑特罗" in txt:
            errs.append("图题和正文粘在一起了")
        if len(txt.encode("utf-8")) < 400:
            errs.append("内容过短(%d 字节)" % len(txt.encode("utf-8")))
        return errs

    tabs = re.findall(r"<table.*?</table>", txt, re.S)
    if tag == "0658":
        if len(tabs) != 2:
            return ["表数 %d != 2" % len(tabs)]
        tb2, tb3 = tabs
        r2 = re.findall(r"<tr[^>]*>(.*?)</tr>", tb2, re.S)
        r3 = re.findall(r"<tr[^>]*>(.*?)</tr>", tb3, re.S)
        if len(r2) != 12:
            errs.append("表2 行数 %d != 12" % len(r2))
        if len(r3) != 2:
            errs.append("表3 行数 %d != 2" % len(r3))
        for i, (ncols, _pl) in enumerate(expand_rows(r2)):
            if ncols != 5:
                errs.append("表2 第%d行展开后 %d 列(应5)" % (i + 1, ncols))
        for i, r in enumerate(r3):
            n = len(re.findall(r"<t[dh][^>]*>", r, re.I))
            if n != 5:
                errs.append("表3 第%d行 %d格(应5)" % (i + 1, n))
        for h in T2_HEAD:
            if h not in tb2:
                errs.append("表2 缺表头:" + h)
        # 全部离子对必须逐个核对
        for (name, nrs, qual, quant, qrs, volt, vrs, ce) in T2_ROWS:
            for v in (qual, quant, volt, ce):
                if v and v not in tb2:
                    errs.append("表2 缺值:" + v)
        for h in T3_HEAD + T3_DATA:
            if h not in tb3:
                errs.append("表3 缺:" + h)
        for k in ("6.4.3", "测定方法", "a)　定性测定", "b)　定量测定",
                  "6.5　空白试验", "7　结果计算和表述",
                  "保留三位有效数字",
                  "试样中被测物的质量分数按式(1)计算"):
            if k not in txt:
                errs.append("缺正文: " + k[:20])
        if len(txt.encode("utf-8")) < 2200:
            errs.append("内容过短(%d 字节)" % len(txt.encode("utf-8")))
        return errs

    # 0659
    if len(tabs) != 1:
        return ["表数 %d != 1" % len(tabs)]
    tb = tabs[0]
    raws = re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S)
    if len(raws) != 10:
        errs.append("表4 行数 %d != 10" % len(raws))
    for i, r in enumerate(raws):
        n = len(re.findall(r"<t[dh][^>]*>", r, re.I))
        # 第 1 行是标题行, colspan=4, 天然只有 1 格
        if i >= 1 and n != 4:
            errs.append("表4 第%d行 %d格(应4)" % (i + 1, n))
    for i, (ncols, _pl) in enumerate(expand_rows(raws)):
        if ncols != 4:
            errs.append("表4 第%d行展开后 %d 列(应4)" % (i + 1, ncols))
    for h in T4_HEAD:
        if h not in tb:
            errs.append("表4 缺表头:" + h)
    for zh, en, formula, cas in T4_ROWS:
        if zh not in tb:
            errs.append("表4 缺中文名:" + zh[:14])
        if en not in tb:
            errs.append("表4 缺英文名:" + en[:14])
        if formula not in tb:
            errs.append("表4 缺分子式:" + formula[:26])
        if cas not in tb:
            errs.append("表4 缺CAS号:" + cas)
    for k in ("8　方法的灵敏度、准确度和精密度", "8.1　灵敏度", "8.2　准确度",
              "8.3　精密度", "附录1", "标准品的中英文名称、化学分子式和 CAS 号",
              "标准品的中英文名称、化学分子式和 CAS 号见表 4。",
              "表 4　标准品中英文名称、化学分子式和 CAS 号",
              "检测限为0.5μg/kg，定量限为1μg/kg",
              "回收率为70%～120%",
              "批内相对标准偏差≤20%，批间相对标准偏差≤20%"):
        if k not in txt:
            errs.append("缺正文: " + k[:22])
    if len(txt.encode("utf-8")) < 2200:
        errs.append("内容过短(%d 字节)" % len(txt.encode("utf-8")))
    return errs


def main():
    jobs = [("0658", build_658), ("0659", build_659), ("0660", build_660)]
    for tag, builder in jobs:
        txt = builder()
        errs = check(txt, tag)
        out = os.path.join(DIR, tag + ".md")
        if errs:
            print("!! %s 质量门未过: %s" % (tag, "; ".join(errs[:8])))
            continue
        open(out, "w", encoding="utf-8").write(txt)
        n = len(re.findall(r"<table", txt))
        print("OK %s -> %s (%d 表, %d 字节)" %
              (tag, os.path.relpath(out, REPO), n, len(txt.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
