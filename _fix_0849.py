#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0849 —— 进口兽药管理目录(续表), 原 md 是**压成一行��管道表**。

【页面映射(先读页码确认)】
Images/03相关法规法律法规文件/0849.jpg = 书第 848(左) + 849(右)
  页眉右上角印着「三、相关法律法规文件 | 849」-> 确认 0849 = **页849** = 右半
  书脊 x≈2100, 右页表格从 x≈2150 开始 -> cut=2120

【原状态(801B)】
  整张表被压成**一行**, 用 `|` 分隔:
    序号|兽药名称|税则号列|商品编号79 |兽用已配剂量的阿福拉纳制剂|3004.9090|30049090.8480 |...
  -> 列边界全丢, 行边界全丢, 序号和表头粘连。

【原图结构(目视 + 竖线检测确认)】
  - 页849 的表格竖线(检测到的列边界): 序号 2224~2366 | 兽药名称 2366~3221 |
    税则号列 3221~3639 | **商品编号 3639~4126**。共 **4 列**。
  - 表头**只有 1 行**(水平线 y=471 表顶 / y=550 表头底), 4 个单元格:
        序号 | 兽药名称 | 税则号列 | 商品编号
    序号/兽药名称/税则号列 都是**竖排居中**的高单元格, **没有 rowspan**。
  - 表头文字是 **商品编号**(不是"商品编码")—— 极放大看第 4 个字是「编」,
    第 5 个字是「号」。
  - 「（续表）」是**表格上方的题注**, 位于**商品编号列正上方**(不是整表题注)。
  - 数据行: **79 ~ 88**, 共 **10 行**。
  - 商品编号全是 **8 位**: 79~86 行 = `30049090.84`, 87~88 行 = `38089400.40`。
    (我第一版凭「序号连号」脑补出 .8480/.8481… 是**幻觉**, 已被回图否掉)

【修后】标准 HTML <table border="1">, 1 个表头行 + 10 个数据行, 4 列。
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(REPO, "minimax", "03相关法律法规文件", "04_（四）兽药管理",
                   "14_关于发布《进口兽药管理目录》的公告", "0849.md")

CAPTION = "（续表）"

HEAD = ["序号", "兽药名称", "税则号列", "商品编号"]

# (序号, 兽药名称, 税则号列, 商品编号)
ROWS = [
    ("79", "兽用已配剂量的阿福拉纳制剂", "3004.9090", "30049090.84"),
    ("80", "兽用已配剂量的尼卡巴嗪制剂", "3004.9090", "30049090.84"),
    ("81", "兽用已配剂量的托曲珠利制剂", "3004.9090", "30049090.84"),
    ("82", "兽用已配剂量的奥美拉唑制剂", "3004.9090", "30049090.84"),
    ("83", "兽用已配剂量的盐酸贝那普利制剂", "3004.9090", "30049090.84"),
    ("84", "兽用已配剂量的碱式碳酸铋制剂", "3004.9090", "30049090.84"),
    ("85", "兽用已配剂量的泰地罗新制剂", "3004.9090", "30049090.84"),
    ("86", "兽用已配剂量的克霉唑制剂", "3004.9090", "30049090.84"),
    ("87",
     "兽用已配剂量的碘、戊二醛、癸甲溴铵、甲醛、过硫酸氢钾复合物消毒剂，"
     "复方煤焦油酸溶液消毒防腐药",
     "3808.9400", "38089400.40"),
    ("88", "兽用已配剂量的氯己定制剂", "3808.9400", "38089400.40"),
]


def td(s):
    return "<td>" + s + "</td>"


def build():
    lines = [CAPTION, "", '<table border="1">']
    lines.append("<tr>" + "".join("<th>" + h + "</th>" for h in HEAD) + "</tr>")
    for r in ROWS:
        lines.append("<tr>" + "".join(td(c) for c in r) + "</tr>")
    lines.append("</table>")
    lines.append("")
    return "\n".join(lines)


def check(txt):
    errs = []
    # 表头 4 列且只有 1 个表头行
    if txt.count("<th>") != 4:
        errs.append("表头单元格数 != 4 (%d)" % txt.count("<th>"))
    if "<th>" not in txt:
        errs.append("无表头")
    # 数据行 10 行
    body = txt.split("</tr>")
    nrows = txt.count("<tr>")
    if nrows != 11:
        errs.append("总行数 != 11 (表头1 + 数据10), 实际 %d" % nrows)
    # 每行 4 格
    for i, m in enumerate(re.findall(r"<tr>(.*?)</tr>", txt, re.S)):
        n = len(re.findall(r"<t[dh][ >]", m))
        if n != 4:
            errs.append("第 %d 行格数 != 4, 实际 %d" % (i + 1, n))
    # 每格非空
    for i, m in enumerate(re.findall(r"<tr>(.*?)</tr>", txt, re.S)):
        for c in re.findall(r"<td>(.*?)</td>", m, re.S):
            if not c.strip():
                errs.append("第 %d 行有空单元格" % (i + 1))
    # 序号连续 79..88
    got = re.findall(r"<tr><td>(\d+)</td>", txt)
    want = [r[0] for r in ROWS]
    if got != want:
        errs.append("序号列不连续/不符: %s" % got)
    # 商品编号: 8 位(HS 编码 8 位), 79~86=30049090.84, 87~88=38089400.40
    if txt.count("30049090.84") != 8:
        errs.append("30049090.84 应出现 8 次, 实际 %d" % txt.count("30049090.84"))
    if txt.count("38089400.40") != 2:
        errs.append("38089400.40 应出现 2 次, 实际 %d" % txt.count("38089400.40"))
    if txt.count("3004.9090") != 8:
        errs.append("3004.9090 应出现 8 次, 实际 %d" % txt.count("3004.9090"))
    if txt.count("3808.9400") != 2:
        errs.append("3808.9400 应出现 2 次, 实际 %d" % txt.count("3808.9400"))
    # 编码格式按**列**区分:
    #   税则号列 = NNNN.NNNN  (4+4)
    #   商品编号 = NNNNNNNN.NN (8+2)
    for m in re.findall(r"<tr>(.*?)</tr>", txt, re.S):
        cs = re.findall(r"<td>(.*?)</td>", m, re.S)
        if len(cs) != 4:
            continue
        a, b = cs[2].split(".")
        if len(a) != 4 or len(b) != 4:
            errs.append("税则号列格式异常(应 4.4): %s" % cs[2])
        a, b = cs[3].split(".")
        if len(a) != 8 or len(b) != 2:
            errs.append("商品编号格式异常(应 8.2): %s" % cs[3])
    # 不能出现幻觉出来的 10 位后缀
    for bad in (".8480", ".8481", ".8482", ".8483", ".8484", ".8485", ".8486", ".8487"):
        if bad in txt:
            errs.append("幻觉后缀: " + bad)
    # 不该有管道表
    if re.search(r"[^|]\|[^|]", txt.replace("<td>", "\x00").replace("</td>", "\x00")):
        errs.append("仍有管道表残留")
    # 题注
    if CAPTION not in txt:
        errs.append("缺题注 " + CAPTION)
    # 兽药名称必须逐字正确(药名不能按常识补全)
    for nm in ("兽用已配剂量的阿福拉纳制剂",
               "兽用已配剂量的尼卡巴嗪制剂",
               "兽用已配剂量的托曲珠利制剂",
               "兽用已配剂量的奥美拉唑制剂",
               "兽用已配剂量的盐酸贝那普利制剂",
               "兽用已配剂量的碱式碳酸铋制剂",
               "兽用已配剂量的泰地罗新制剂",
               "兽用已配剂量的克霉唑制剂",
               "兽用已配剂量的碘、戊二醛、癸甲溴铵、甲醛、过硫酸氢钾复合物消毒剂，"
               "复方煤焦油酸溶液消毒防腐药",
               "兽用已配剂量的氯己定制剂"):
        if nm not in txt:
            errs.append("缺药名: " + nm)
    # 常见误读必须不出现
    for bad in ("磺胺喹噁啉", "甲硝唑"):
        if bad in txt:
            errs.append("不应出现的药名: " + bad)
    return errs


def main():
    txt = build()
    errs = check(txt)
    if errs:
        print("!! 质量门未过:")
        for e in errs:
            print("   -", e)
        return 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(txt)
    print("OK 0849 -> %s (%d 字节, 1 表: 1 表头行 + 10 数据行, 4 列)" %
          (os.path.relpath(OUT, REPO), len(txt.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
