#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0622 (附件2 药品生产经营环节监督检查情况表)。

【页面映射(先读页码确认)】
Images/02制度文件/0623.jpg = 书第 622(左) + 623(右)
  -> 0622 = **页622** = 0623.jpg 的左半
  书脊折痕 x≈2250, 页622 表格右边界 ~2200 -> cut=2200

【原状态(压平了)】
0622.md 760B —— 整张表被压成一段**管道串**:
  内容 |药品生产企业|药品批发企业|药品零售企业 ---|---|---|---| 监督检查人次 | | | ...
  - 缺「附件2」标签和标题
  - 缺「填报单位（公章）：」「填报日期：」
  - **「依法查处情况」这个跨 3 行的纵向标签丢了**, 3 个子行被拉平成 3 个独立行
  - 表里 **「/」的位置全丢了**(注1 说明「/」表示不用填写, 是有意义的标记)
  - 缺表下的「说明:1. 表格中"/"表示不用填写; 2. 该表格上报传真号码: 010-68310909」

【真值(目视逐格核对)】
4 列: 内容 | 药品生产企业 | 药品批发企业 | 药品零售企业
  1 监督检查人次                              |   |   |
  2 检查企业数                                |   |   |
  3 企业外租厂房、车间排查情况                 |   | / | /
  4 发现将药品销售给无合法经营或使用资质的单位的  |   |   | /
  5 未建立购销台账、实行实名购销制度的           |   |   | /
  6 发现向食品生产经营单位销售国家公布的"严禁
     用于食品和饲料加工"药品的                  |   |   |
  7 未按药品分类管理制度开展经营活动的           | / | / |
  8 依法查处情况(rowspan=3, 纵向标签)
       停产停业整顿的        |   |   |
       吊销生产、经营许可的   |   |   |
       移送相关部门的        |   |   |
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(REPO, "minimax", "02制度文件", "08_（八）瘦肉精监管",
                   "114_国家食品药品监督管理局关于开展严厉打击食品非法添加和滥用食品添加剂"
                   "专项工作的紧急通知", "0622.md")

CUT = 2200

HEAD = ["内容", "药品生产企业", "药品批发企业", "药品零售企业"]

# (标签, [3 个数据格: 药品生产企业, 药品批发企业, 药品零售企业])
# "/" 表示"不用填写"(见表下说明 1)
ROWS = [
    ("监督检查人次", ["", "", ""]),
    ("检查企业数", ["", "", ""]),
    ("企业外租厂房、车间排查情况", ["", "/", "/"]),
    ("发现将药品销售给无合法经营或使用资质的单位的", ["", "", "/"]),
    ("未建立购销台账、实行实名购销制度的", ["", "", "/"]),
    ("发现向食品生产经营单位销售国家公布的“严禁用于食品和饲料加工”药品的", ["", "", ""]),
    ("未按药品分类管理制度开展经营活动的", ["/", "/", ""]),
]

# 依法查处情况: 纵向标签跨 3 行
SUB = [
    "停产停业整顿的",
    "吊销生产、经营许可的",
    "移送相关部门的",
]

NOTES = [
    "1.表格中“/”表示不用填写；",
    "2.该表格上报传真号码：010-68310909。",
]


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def td(v="", attrs="", tag="td"):
    a = (" " + attrs) if attrs else ""
    return "<%s%s>%s</%s>" % (tag, a, v, tag)


def tr(cells):
    return "  <tr>\n    %s\n  </tr>" % "\n    ".join(cells)


def build():
    rows = [tr([td(h, "th") for h in HEAD])]
    for label, vals in ROWS:
        rows.append(tr([td(esc(label))] + [td(v) for v in vals]))
    # 依法查处情况: 纵向标签跨 **4 行**(标签所在行 + 3 个子行)
    # 坑 1: 标签格占了第 0 列, 所以 3 个子行**只有 3 个格**(子标签 + 2 个空),
    #        第 0 列由上一行的 rowspan 撑着 —— 写成 4 格就会让展开后变成 5 列。
    # 坑 2: rowspan 要算**自己所在的那一行**, 所以是 4 不是 3。
    rows.append(tr([td("依法查处情况", 'rowspan="4"')] + [td() for _ in range(3)]))
    for s in SUB:
        rows.append(tr([td(esc(s))] + [td() for _ in range(2)]))

    out = [
        "<!-- source: Images/02制度文件/0623.jpg (split: 0622, 左半, cut=%d) -->" % CUT,
        "<!-- repaired: rotated=no, method=api-minimax, form=table, blank-form -->",
        "",
        "附件2",
        "",
        "**药品生产经营环节监督检查情况表**",
        "",
        "填报单位（公章）：　　　　　　　　　　填报日期：",
        "",
        "<table border=\"1\">",
    ] + rows + [
        "</table>",
        "",
        "说明：",
        "",
    ]
    for n in NOTES:
        out.append(n)
        out.append("")
    return "\n".join(out)


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


def row_of(tb, label):
    """取出含指定标签的那一整行 <tr>...</tr>。

    坑: 用 `<tr[^>]*>.*?标签.*?</tr>` 的话, `.*?` 会**跨行**匹配到后面的
    </tr>, 于是把后面的行也算进来, 导致「这行不该有 /」误报。
    必须用「不含 </tr>」的字符类来限制在行内。
    """
    pat = r"<tr[^>]*>(?:(?!</tr>).)*?" + re.escape(esc(label)) + r"(?:(?!</tr>).)*?</tr>"
    m = re.search(pat, tb, re.S)
    return m.group(0) if m else None


def check(txt):
    errs = []
    tabs = re.findall(r"<table.*?</table>", txt, re.S)
    if len(tabs) != 1:
        return ["表数 %d != 1" % len(tabs)]
    tb = tabs[0]
    raws = re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S)
    # 1 表头 + 7 普通行 + 依法查处情况(1 个标签行 + 3 个子行) = 12
    if len(raws) != 12:
        errs.append("行数 %d != 12" % len(raws))
    for i, (ncols, _pl) in enumerate(expand_rows(raws)):
        if ncols != 4:
            errs.append("第%d行展开后 %d 列(应4)" % (i + 1, ncols))
    for h in HEAD:
        if h not in tb:
            errs.append("缺表头:" + h)
    for label, vals in ROWS:
        if esc(label) not in tb:
            errs.append("缺行标签:" + label[:18])
    for s in SUB:
        if esc(s) not in tb:
            errs.append("缺子行:" + s)
    if "依法查处情况" not in tb:
        errs.append("缺纵向标签:依法查处情况")
    if 'rowspan="4">依法查处情况' not in tb:
        errs.append("依法查处情况 缺 rowspan=4")
    # 「/」的位置必须逐个核对(这些格不能空着)
    # 用**列名**来表达期望值, 避免下标错位
    COLS = ["药品生产企业", "药品批发企业", "药品零售企业"]
    slash_expect = {
        "企业外租厂房、车间排查情况": ["药品批发企业", "药品零售企业"],
        "发现将药品销售给无合法经营或使用资质的单位的": ["药品零售企业"],
        "未建立购销台账、实行实名购销制度的": ["药品零售企业"],
        "未按药品分类管理制度开展经营活动的": ["药品生产企业", "药品批发企业"],
    }
    for label, vals in ROWS:
        if label not in slash_expect:
            continue
        r = row_of(tb, label)
        if not r:
            continue
        cells = re.findall(r"<td[^>]*>(.*?)</td>", r, re.S | re.I)
        if len(cells) != 4:
            errs.append("%s 行格子数 %d != 4" % (label[:12], len(cells)))
            continue
        # cells[0]=标签, cells[1..3]=三个数据列
        got = [COLS[i] for i in range(3) if "/" in cells[i + 1]]
        if got != slash_expect[label]:
            errs.append("/ 位置错 %s: %s != %s" % (label[:12], got, slash_expect[label]))
    # 没有 "/" 的行也不能多出 "/"
    for label, vals in ROWS:
        if label in slash_expect:
            continue
        r = row_of(tb, label)
        if not r:
            continue
        # 坑: **不能直接搜原始 HTML 里的 "/"** —— 闭合标签 </td> 里就有 "/",
        # 每行都会误命中。必须先取出**格里的文字**再判断。
        texts = [re.sub(r"<[^>]+>", "", x) for x
                 in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S | re.I)]
        if any("/" in t for t in texts):
            errs.append("%s 不该有 /" % label[:12])
    # 标题与说明
    for k in ("附件2", "药品生产经营环节监督检查情况表",
              "填报单位（公章）", "填报日期",
              "说明：", "1.表格中“/”表示不用填写；",
              "2.该表格上报传真号码：010-68310909。"):
        if k not in txt:
            errs.append("缺: " + k[:20])
    if len(txt.encode("utf-8")) < 1400:
        errs.append("内容过短(%d 字节)" % len(txt.encode("utf-8")))
    return errs


def main():
    txt = build()
    errs = check(txt)
    if errs:
        print("!! 质量门未过: %s" % "; ".join(errs[:8]))
        return 1
    open(OUT, "w", encoding="utf-8").write(txt)
    print("OK 0622 -> %s (%d 字节, %d 行)" %
          (os.path.relpath(OUT, REPO), len(txt.encode("utf-8")), 11))
    return 0


if __name__ == "__main__":
    sys.exit(main())
