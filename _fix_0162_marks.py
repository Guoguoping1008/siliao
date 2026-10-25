#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修正 0162 的 √ 勾选位置(用**目视核对过的真值**覆盖模型输出)。

【问题】
模型读出了 12 列 x 13 行的骨架, 但**√ 的位置读错了 6 行**:
  序号7  全空(图上是 1,4)
  序号9  6 个√(图上是 1,2,3,4,5)
  序号11 3 个√(图上是 1,2,3,4,5)
  序号12 整体左移 3 列(图上是 3..10)
  序号13 全空(图上是 6..10)
  序号3/4 少 1 个√
**根因**: √ 是很小的勾, 在 1900px 宽的图上只有几像素, 模型按印象填了。

【对策】
把 √ 的位置**从图上人工核对出来**写成真值表, 直接重写数据行的单元格。
其余(表标题/表头/行标签/3 条注)保留模型产出的。

【真值来源】
旋正后的原图 3297x2030, 用长横线/长竖线定位行列网格后逐格目视核对。
类别列编号(从「设立(已取得工商注册)」算第 1 列):
  1 设立(已取得工商注册)   2 设立(未取得工商注册)  3 续展
  4 增加或变更按生产产品    5 增加产品品种或产品系列  6 迁址
  7 变更企业名称          8 变更企业法定代表人      9 变更企业注册地址或注册地名称
  10 变更企业生产地址名称
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(REPO, "minimax", "02制度文件", "02_（二）生产许可",
                   "25_关于添加剂预混合饲料生产许可申报材料要求的公告", "0162.md")

# 序号 -> 有 √ 的类别列(1-based)。**目视核对过的真值**。
TRUTH = {
    1: [1, 2, 3, 4, 5],
    2: [1, 2, 3, 4, 5],
    3: [1, 2, 3, 4, 5],
    4: [1, 2, 3, 4, 5],
    5: [1, 3, 4, 5],
    6: [1, 3, 4, 5],
    7: [1, 4],
    8: [1, 2, 3, 4, 5],
    9: [1, 2, 3, 4, 5],
    10: [1, 2, 3, 4, 5],
    11: [1, 2, 3, 4, 5],
    12: [3, 4, 5, 6, 7, 8, 9, 10],
    13: [6, 7, 8, 9, 10],
}

# 行标签(用于按序号定位行; 兼容模型可能写出的少量 OCR 差异)
ROW_KEY = {
    1: "企业承诺书", 2: "预混合饲料生产许可证申请书", 3: "企业组织机构图",
    4: "主要负责人", 5: "厂区平面布置图", 6: "生产工艺流程图",
    7: "计算机自动化控制系统", 8: "混合机混合均匀度检验报告",
    9: "检验实验室平面布置图", 10: "检验仪器购置发票", 11: "企业管理制度",
    12: "企业生产许可证", 13: "相关证明材料",
}


def rewrite(txt):
    """用真值重写每个数据行的 √ 位置。"""
    m = re.search(r"<table.*?</table>", txt, re.S | re.I)
    if not m:
        return txt, 0
    tb = m.group(0)
    tr_pat = re.compile(r"(<tr[^>]*>)(.*?)(</tr>)", re.S | re.I)
    cell_pat = re.compile(r"<t[dh]([^>]*)>(.*?)</t[dh]>", re.S | re.I)

    out = []
    last = 0
    fixed = 0
    for rm in tr_pat.finditer(tb):
        body = rm.group(2)
        cells = list(cell_pat.finditer(body))
        # 定位数据行: 第 1 格是纯数字序号
        if len(cells) < 3:
            continue
        numtxt = re.sub(r"<[^>]+>|\s", "", cells[0].group(2))
        if not numtxt.isdigit():
            continue
        num = int(numtxt)
        if num not in TRUTH:
            continue
        want = set(TRUTH[num])
        # 类别列 = 前 2 格(序号、项目名)之后的第 1..10 格
        ncat = 10
        cats = cells[2:2 + ncat]
        if len(cats) < ncat:
            continue
        # 只有当项目名与真值行标签相符时才改, 防止对错行
        name = re.sub(r"<[^>]+>|\s", "", cells[1].group(2))
        key = ROW_KEY.get(num, "")
        if key and key not in name:
            continue
        # 构造新的 10 个类别格
        new_cats = []
        for ci, cm in enumerate(cats, 1):
            attrs = cm.group(1)
            if ci in want:
                new_cats.append(f"<td{attrs}>√</td>")
            else:
                new_cats.append(f"<td{attrs}></td>")
        # 拼回: 前 2 格 + 新类别格 + 可能剩余的格(丢掉, 保持列数一致)
        head = body[:cells[0].start()]
        pre = body[cells[0].start():cells[2].start()]
        new_body = head + pre + "".join(new_cats)
        out.append((rm.start(), rm.end(), rm.group(1) + new_body + rm.group(3)))
        fixed += 1
    if not fixed:
        return txt, 0
    pieces = []
    last = 0
    for (a, b, rep) in out:
        pieces.append(tb[last:a])
        pieces.append(rep)
        last = b
    pieces.append(tb[last:])
    return txt[:m.start()] + "".join(pieces) + txt[m.end():], fixed


def main():
    t0 = open(OUT, encoding="utf-8").read()
    new, n = rewrite(t0)
    if not n:
        print("没有匹配到数据行, 未改动")
        return 1
    open(OUT, "w", encoding="utf-8").write(new)
    print(f"已重写 {n} 行的 √ 位置")
    # 校验
    tb = re.search(r"<table.*?</table>", new, re.S).group(0)
    for rm in re.finditer(r"<tr[^>]*>(.*?)</tr>", tb, re.S):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", rm.group(1), re.S)
        if not cells:
            continue
        num = re.sub(r"<[^>]+>|\s", "", cells[0])
        if not num.isdigit():
            continue
        marks = "".join("V" if "√" in c else "." for c in cells[2:12])
        print("  序号%-3s %s" % (num, marks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
