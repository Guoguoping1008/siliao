#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0433/0434 (附件2-3 饲料质量安全监督复核检测指定单位)。

【页面映射(先读页码确认)】
Images/02制度文件/0433.jpg = 书第 432(左) + 433(右)
  0433 <- 页433: 附件2-3 的表, 序号 1~22 (带标题行)
Images/02制度文件/0435.jpg = 书第 434(左) + 435(右)
  0434 <- 页434: 附件2-3 的**续表**, 序号 23~32 (页眉右上角有「(续)」)
  书脊折痕 x≈2200, 表格右边界 ~2100 -> cut=2130

【原状态(都错)】
0433.md 828B —— 整页塌成一个字符串:
  「附件2-3 饲料质量安全监督复核检测指定单位单位名称序号国家饲料质量监督
    检验中心（北京）1 北京市饲料监察所2 天津市兽药饲料监察所...」
  —— 表格变成了纯文本流, 序号和单位名粘连
0434.md 517B —— 表格退化成了「#### 23 | 重庆市兽药饲料检测所」这样的
  伪标题, 序号和单位名用 | 拼, 已经不是表格

【真值(目视逐行核对, 32 行全部读出)】
表头: 序号 | 单位名称
1  国家饲料质量监督检验中心（北京）
2  北京市饲料监察所
3  天津市兽药饲料监察所
4  河北省兽药监察所
5  山西省饲料兽药监察所
6  内蒙古自治区饲料草种监督检验站
7  辽宁省检验检测认证中心
8  吉林省兽药饲料检验监测所
9  黑龙江省农产品和兽药饲料技术鉴定站
10 上海市兽药饲料检测所
11 江苏省畜产品质量检验测试中心
12 浙江省兽药饲料监察所
13 安徽省兽药饲料监察所
14 福建省兽药饲料监察所
15 江西省兽药饲料监察所
16 山东省饲料质量检验所
17 河南省兽药饲料监察所
18 湖北省兽药监察所
19 湖南省兽药饲料监察所
20 广东省农产品质量安全中心
21 广西饲料监测所
22 海南省兽药饲料监察所
23 重庆市兽药饲料检测所
24 四川省饲料工作总站
25 贵州省兽药饲料监察所
26 云南省兽药饲料检测所
27 陕西省饲料检测所
28 甘肃省农产品质量安全检验检测中心
29 青海省兽药饲料监察所
30 宁夏回族自治区兽药饲料监察所
31 新疆维吾尔自治区兽药饲料监察所
32 新疆生产建设兵团畜牧兽医工作总站
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(REPO, "minimax", "02制度文件", "06_（六）监督执法",
                      "59_农业农村部关于印发饲料质量安全监督抽查检测工作要求及2019年工作方案的通知")

CUT = 2130

TITLE = "饲料质量安全监督复核检测指定单位"

# 序号 -> 单位名称 (全部目视核对)
ROWS_433 = [
    (1, "国家饲料质量监督检验中心（北京）"),
    (2, "北京市饲料监察所"),
    (3, "天津市兽药饲料监察所"),
    (4, "河北省兽药监察所"),
    (5, "山西省饲料兽药监察所"),
    (6, "内蒙古自治区饲料草种监督检验站"),
    (7, "辽宁省检验检测认证中心"),
    (8, "吉林省兽药饲料检验监测所"),
    (9, "黑龙江省农产品和兽药饲料技术鉴定站"),
    (10, "上海市兽药饲料检测所"),
    (11, "江苏省畜产品质量检验测试中心"),
    (12, "浙江省兽药饲料监察所"),
    (13, "安徽省兽药饲料监察所"),
    (14, "福建省兽药饲料监察所"),
    (15, "江西省兽药饲料监察所"),
    (16, "山东省饲料质量检验所"),
    (17, "河南省兽药饲料监察所"),
    (18, "湖北省兽药监察所"),
    (19, "湖南省兽药饲料监察所"),
    (20, "广东省农产品质量安全中心"),
    (21, "广西饲料监测所"),
    (22, "海南省兽药饲料监察所"),
]

ROWS_434 = [
    (23, "重庆市兽药饲料检测所"),
    (24, "四川省饲料工作总站"),
    (25, "贵州省兽药饲料监察所"),
    (26, "云南省兽药饲料检测所"),
    (27, "陕西省饲料检测所"),
    (28, "甘肃省农产品质量安全检验检测中心"),
    (29, "青海省兽药饲料监察所"),
    (30, "宁夏回族自治区兽药饲料监察所"),
    (31, "新疆维吾尔自治区兽药饲料监察所"),
    (32, "新疆生产建设兵团畜牧兽医工作总站"),
]


def build(tag, rows, src, with_title):
    out = [
        "<!-- source: %s (split: %s, cut=%d) -->" % (src, tag, CUT),
        "<!-- repaired: rotated=no, method=api-minimax, form=table -->",
        "",
    ]
    if with_title:
        out.append("附件2-3")
        out.append("")
        out.append("**%s**" % TITLE)
        out.append("")
    out.append("<table border=\"1\">")
    out.append("  <tr>\n    <th>序号</th>\n    <th>单位名称</th>\n  </tr>")
    for no, name in rows:
        out.append("  <tr>\n    <td>%d</td>\n    <td>%s</td>\n  </tr>" % (no, name))
    out.append("</table>")
    out.append("")
    return "\n".join(out)


def check(txt, tag):
    errs = []
    tabs = re.findall(r"<table.*?</table>", txt, re.S)
    if len(tabs) != 1:
        return ["表数 %d != 1" % len(tabs)]
    tb = tabs[0]
    raws = re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S)
    rows = ROWS_433 if tag == "0433" else ROWS_434
    if len(raws) != len(rows) + 1:
        errs.append("行数 %d != %d" % (len(raws), len(rows) + 1))
    for j, r in enumerate(raws):
        n = len(re.findall(r"<t[dh][^>]*>", r, re.I))
        if n != 2:
            errs.append("第%d行 %d格(应2)" % (j + 1, n))
    # 序号序列
    got = []
    for r in raws[1:]:
        c = [re.sub(r"<[^>]+>", "", x).strip()
             for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
        if c:
            got.append(c[0])
    want = [str(no) for no, _ in rows]
    if got != want:
        errs.append("序号序列不符: %s != %s" % (got[:5], want[:5]))
    for no, name in rows:
        if name not in tb:
            errs.append("缺单位名: %s" % name[:14])
    if "<th>序号</th>" not in tb or "<th>单位名称</th>" not in tb:
        errs.append("表头不对")
    if tag == "0433":
        if "附件2-3" not in txt or TITLE not in txt:
            errs.append("缺标题")
    return errs


def main():
    jobs = [
        ("0433", ROWS_433, "Images/02制度文件/0433.jpg", True),
        ("0434", ROWS_434, "Images/02制度文件/0435.jpg", False),
    ]
    for tag, rows, src, with_title in jobs:
        txt = build(tag, rows, src, with_title)
        errs = check(txt, tag)
        out = os.path.join(OUTDIR, tag + ".md")
        if errs:
            print("!! %s 质量门未过: %s" % (tag, "; ".join(errs[:8])))
            continue
        open(out, "w", encoding="utf-8").write(txt)
        print("OK %s -> %s (%d 行, %d 字节)" %
              (tag, os.path.relpath(out, REPO), len(rows), len(txt.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
