#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0995/0996 —— 饲料产品标准和检测方法标准目录(检测方法标准, 续)。

【页面映射(先读页码确认)】
Images/04标准及标准目录/0995.jpg = 书第 994(左) + 995(右)  -> 0995 = 页995
Images/04标准及标准目录/0997.jpg = 书第 996(左) + 997(右)  -> 0996 = 页996
  页眉: 左半「99X | 饲料法规文件【2023】 >>>」, 右半「四、标准及标准目录 | 99X」
  切点 cut=2100

【原状态】
  0995.md 2269B —— 整张表被拆成 `#### N 标准编号标准名称` 伪标题, 且
                     **部分行丢了序号**(「61 GB/T 18397—2014…」没序号),
                     还有几行**挤成一行**
  0996.md 2277B —— 同上, 开头就是「90 GB/T 21103—2007…」多行挤在一起

【原图结构(逐格放大确认)】3 列: 序号 | 标准编号 | 标准名称
  - 表头**只有 1 行**; 「（续表）」在**标准名称表头格内**(右对齐)
  - 每行 3 格, 序号连续

【逐页内容范围】
  0995(页995): 续表 行60~89
  0996(页996): 续表 行90~117

【目视纠正 1 处】0996 的「（续表）」被 API 写成**半角** `(续表)` -> 统一成全角
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(REPO, "minimax", "04标准及标准目录",
                      "05_饲料产品标准和检测方法标准目录")

CONT = "（续表）"


def td(v="", attrs="", tag="td"):
    a = (" " + attrs) if attrs else ""
    return "<%s%s>%s</%s>" % (tag, a, v, tag)


def tr(cells):
    return "<tr>%s</tr>" % "".join(cells)


def build(rows):
    out = ['<table border="1">']
    out.append(tr([td("序号", tag="th"), td("标准编号", tag="th"),
                   td("标准名称<br>" + CONT, tag="th")]))
    for r in rows:
        out.append(tr([td(c) for c in r]))
    out.append("</table>")
    out.append("")
    return "\n".join(out)


def parse_draft(path):
    """从 API 草稿里提取 (序号, 标准编号, 标准名称) 三元组。"""
    t = open(path, encoding="utf-8").read()
    t = t.replace("(续表)", CONT)
    rows = []
    for m in re.findall(r"<tr>(.*?)</tr>", t, re.S):
        cs = re.findall(r"<td[^>]*>(.*?)</td>", m, re.S)
        if len(cs) == 3 and re.fullmatch(r"\d+", cs[0].strip()):
            rows.append((cs[0].strip(), cs[1].strip(), cs[2].strip()))
    return rows


MUST = {
    "0995": [
        "GB/T 18246—2019", "饲料中氨基酸的测定",
        "GB/T 18397—2014", "复合预混合饲料中泛酸的测定",
        "GB/T 21102—2007", "动物源性饲料中兔源性成分定性检测方法",
    ],
    "0996": [
        "GB/T 21103—2007", "动物源性饲料中哺乳动物源性成分定性检测方法",
        "GB/T 23882—2009", "饲料中L-抗坏血酸-2-磷酸酯的测定",
        "GB/T 23881—2009", "饲用纤维素酶活性的测定",
    ],
}

MUST_NOT = [
    "#### ",
    "(续表)",      # 半角
]


def check(txt, must, name, first, last):
    errs = []
    for k in must:
        if k not in txt:
            errs.append("缺: " + k)
    for k in MUST_NOT:
        if k in txt:
            errs.append("不应出现: " + k)
    if txt.count("<table") != 1:
        errs.append("表数 != 1")
    m = re.findall(r"<table.*?</table>", txt, re.S)[0]
    rows = re.findall(r"<tr>(.*?)</tr>", m, re.S)
    for i, r in enumerate(rows, 1):
        tags = re.findall(r"<t[dh]([^>]*)>", r)
        width = 0
        for a in tags:
            mc = re.search(r'colspan="(\d+)"', a)
            width += int(mc.group(1)) if mc else 1
        if width != 3:
            errs.append("第 %d 行展开后列数 != 3, 实际 %d" % (i, width))
    nums = []
    for r in rows:
        cs = re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)
        if cs and re.fullmatch(r"\d+", cs[0]):
            nums.append(int(cs[0]))
    if not nums:
        errs.append("无数据行")
    else:
        if nums[0] != first:
            errs.append("起始序号 != %d, 实际 %d" % (first, nums[0]))
        if nums[-1] != last:
            errs.append("结束序号 != %d, 实际 %d" % (last, nums[-1]))
        for a, b in zip(nums, nums[1:]):
            if b != a + 1:
                errs.append("序号不连续: %d -> %d" % (a, b))
    return errs


def main():
    ok = True
    for name, first, last in (("0995", 60, 89), ("0996", 90, 117)):
        rows = parse_draft(os.path.join(OUTDIR, name + ".md.draft"))
        txt = build(rows)
        errs = check(txt, MUST[name], name, first, last)
        if errs:
            ok = False
            print("!! %s 质量门未过:" % name)
            for e in errs:
                print("   -", e)
            continue
        out = os.path.join(OUTDIR, name + ".md")
        open(out, "w", encoding="utf-8").write(txt)
        print("OK %s -> %s (%d 字节, 1 表, %d 行)" %
              (name, os.path.relpath(out, REPO), len(txt.encode("utf-8")), len(rows)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
