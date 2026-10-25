#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0970 —— 全国一体化政务服务平台电子证照 饲料和饲料添加剂进口登记证。

【页面映射(先读页码确认)】
Images/04标准及标准目录/0971.jpg = 书第 970(左) + 971(右)
  页眉: 左半「970 | 饲料法规文件【2023】 >>>」, 右半「四、标准及标准目录 | 971」
  -> **0970 = 页970 = 0971.jpg 左半**, **0971 = 页971 = 0971.jpg 右半**
  切点 cut=2100

【原状态(1658B)】
  只有 1 个表, **表后的全部正文都没了**, 而且表本身有错:
  1. 第 4 列表头写成了「说明」-> 原文是「**取值**」
  2. 序号2 的取值写成了「1110000000」-> 原文是「**11100000000132664061**」(20 位)
  3. 序号4 的取值写成了「1110000000」-> 原文是「**111000000000132664**」
  4. source 注释写的是 `Images/04标准及标准目录/0971.jpg`(应为本页左半)
  5. **表后的正文全缺**: 5 证照信息项 / 5.1 信息模型 / 5.2 基础信息 / 5.2.1 证照名称
     (中文名称/英文名称/缩写名/说明/数据类型及格式/值域/约束条件/取值示例)

【表1 结构(逐格放大确认)】4 列, 10 行数据 + 表题行 + 表头行
  表题: 表1 饲料和饲料添加剂进口登记证证照类型信息取值
  表头: 序号 | 名称 | 短名 | 取值
  1  证书类型名称    ZZLXMC   固定为"饲料和饲料添加剂进口登记证"
  2  证书类型代码    ZZLXDM   11100000000132664061
  3  证书定义机构    ZZDYJG   固定为"中华人民共和国农业农村部"
  4  证书定义机构代码 ZZDYJGDM 111000000000132664
  5  证照名称        ZZMC     固定为"饲料和饲料添加剂进口登记证"
  6  证照类型代码    ZZLXDM   11100000000132664061
  7  证书定义机构    ZZDYJG   固定为"中华人民共和国农业农村部"
  8  证书定义机构代码 ZZDYJGDM 111000000000132664
  9  信息模型        XXMX     引用图1
  10 发证机关        FZJG     固定为"中华人民共和国农业农村部"
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(REPO, "minimax", "04标准及标准目录",
                   "04_全国一体化政务服务平台、电子证照、饲料和饲料添加剂进口登记证",
                   "0970.md")

TITLE = "表1 饲料和饲料添加剂进口登记证证照类型信息取值"

HEAD = ["序号", "名称", "短名", "取值"]

ROWS = [
    ("1", "证书类型名称", "ZZLXMC", "固定为“饲料和饲料添加剂进口登记证”"),
    ("2", "证书类型代码", "ZZLXDM", "11100000000132664061"),
    ("3", "证书定义机构", "ZZDYJG", "固定为“中华人民共和国农业农村部”"),
    ("4", "证书定义机构代码", "ZZDYJGDM", "111000000000132664"),
    ("5", "证照名称", "ZZMC", "固定为“饲料和饲料添加剂进口登记证”"),
    ("6", "证照类型代码", "ZZLXDM", "11100000000132664061"),
    ("7", "证书定义机构", "ZZDYJG", "固定为“中华人民共和国农业农村部”"),
    ("8", "证书定义机构代码", "ZZDYJGDM", "111000000000132664"),
    ("9", "信息模型", "XXMX", "引用图1"),
    ("10", "发证机关", "FZJG", "固定为“中华人民共和国农业农村部”"),
]

AFTER = [
    "## 5 证照信息项",
    "",
    "### 5.1 信息模型",
    "",
    "饲料和饲料添加剂进口登记证的信息包括基础信息、持证人信息、商品信息和管理信"
    "息等，其信息模型见图1。",
    "",
    "### 5.2 基础信息",
    "",
    "#### 5.2.1 证照名称",
    "",
    "中文名称：证照名称；",
    "",
    "英文名称：certificate name；",
    "",
    "缩写名：ZZMC；",
    "",
    "说明：依据国家或行业相关规定而确定的证照命名，通常与所属证照类型的类型"
    "名称相同；",
    "",
    "数据类型及格式：C26；",
    "",
    "值　　域：固定为“饲料和饲料添加剂进口登记证”；",
    "",
    "约束条件：必选；",
    "",
    "取值示例：饲料和饲料添加剂进口登记证。",
    "",
]

MUST = [
    TITLE, "序号", "名称", "短名", "取值",
    "证书类型名称", "ZZLXMC", "固定为“饲料和饲料添加剂进口登记证”",
    "证书类型代码", "ZZLXDM", "11100000000132664061",
    "证书定义机构", "ZZDYJG", "固定为“中华人民共和国农业农村部”",
    "证书定义机构代码", "ZZDYJGDM", "111000000000132664",
    "证照名称", "ZZMC",
    "证照类型代码",
    "信息模型", "XXMX", "引用图1",
    "发证机关", "FZJG",
    "5 证照信息项", "5.1 信息模型",
    "饲料和饲料添加剂进口登记证的信息包括基础信息、持证人信息、商品信息和管理信息等，其信息模型见图1。",
    "5.2 基础信息", "5.2.1 证照名称",
    "中文名称：证照名称；",
    "英文名称：certificate name；",
    "缩写名：ZZMC；",
    "说明：依据国家或行业相关规定而确定的证照命名，通常与所属证照类型的类型名称相同；",
    "数据类型及格式：C26；",
    "值　　域：固定为“饲料和饲料添加剂进口登记证”；",
    "约束条件：必选；",
    "取值示例：饲料和饲料添加剂进口登记证。",
]

MUST_NOT = [
    "<th>说明</th>",
    "1110000000<",          # 截断的 10 位编码
    "固定为“1110000000”",
]


def td(v="", attrs="", tag="td"):
    a = (" " + attrs) if attrs else ""
    return "<%s%s>%s</%s>" % (tag, a, v, tag)


def tr(cells):
    return "<tr>%s</tr>" % "".join(cells)


def build():
    rows = [tr([td(TITLE, 'colspan="4"', "th")])]
    rows.append(tr([td(h, tag="th") for h in HEAD]))
    for r in ROWS:
        rows.append(tr([td(c) for c in r]))
    tbl = "\n".join(rows)
    return "\n".join(['<table border="1">', tbl, "</table>", ""] + AFTER)


def check(txt):
    errs = []
    for k in MUST:
        if k not in txt:
            errs.append("缺: " + k)
    for k in MUST_NOT:
        if k in txt:
            errs.append("不应出现: " + k)
    if txt.count("<table") != 1:
        errs.append("表数 != 1")
    rows = re.findall(r"<tr>(.*?)</tr>", txt, re.S)
    if len(rows) != 12:
        errs.append("行数 != 12 (表题1+表头1+数据10), 实际 %d" % len(rows))
    for i, m in enumerate(rows, 1):
        tags = re.findall(r"<t[dh]([^>]*)>", m)
        width = 0
        for a in tags:
            mc = re.search(r'colspan="(\d+)"', a)
            width += int(mc.group(1)) if mc else 1
        if width != 4:
            errs.append("第 %d 行展开后列数 != 4, 实际 %d" % (i, width))
    # 序号连续 1..10
    got = re.findall(r"<tr><td>(\d+)</td>", txt)
    if got != [r[0] for r in ROWS]:
        errs.append("序号列不连续: %s" % got)
    # 编码位数: 两个 20 位 + 两个 15 位
    if txt.count("11100000000132664061") != 2:
        errs.append("11100000000132664061 应出现 2 次")
    if txt.count("111000000000132664") != 2:
        errs.append("111000000000132664 应出现 2 次")
    # 不能有 10 位截断版
    if re.search(r"1110000000<", txt):
        errs.append("存在截断编码")
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
    print("OK 0970 -> %s (%d 字节, 1 表: 12 行 x 4 列, + 正文)" %
          (os.path.relpath(OUT, REPO), len(txt.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
