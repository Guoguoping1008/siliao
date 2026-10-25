#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0978 —— 电子证照 进口登记证 7.1.1 幅面要求 + 图2 样式图。

【页面映射(先读页码确认)】
Images/04标准及标准目录/0979.jpg = 书第 978(左) + 979(右)
  页眉右上角印着「四、标准及标准目录 | 979」-> 右半是页 979
  -> **0978 = 页978 = 0979.jpg 左半**
  切点 cut=2100

【原状态(2369B)的错 —— 把「图里的文字」当成了正文】
  0978.md 开头是:
    进口登记证REGISTERED LICENSELicense No.:经试验、审查，该产品安全、有效，
    准予在中华人民共和国登记，特此发证。This is to certify that through test…
  这些**全是图2(证书样式图)内部的文字**, 被 OCR 当成正文抄了出来。
  后面又混进了图注和规格正文, 引号/括号也被打乱:
    「"行排版，行间距34pt…」 少了前面的「"经试验、审查…」

【页978 的真实结构】
  1. **图2 饲料和饲料添加剂进口登记证样式** —— 一张**证书样式图**(不是表格)
     页首就是这张图, 上面没有正文。图内的文字(进 口 登 记 证 / REGISTERED
     LICENSE / 许可证号 / 申请企业名称 / 生产企业名称 / 商品名称 / 通用名称 /
     感官指标 / 适用范围 / 理化指标 / 经试验、审查… / This is to certify…)
     **属于图形内容, 不是正文** -> 只保留图题, 不抄图内文字。
  2. 图注 + 规格正文:
     6mm；"（）""外饲准字"在宽度范围内均匀分布，"号"在宽度范围内水平居中对齐，
     "（）"字型为Times New Roman，"外饲准字""号"字型为楷体。
     "经试验、审查，该产品安全、有效，准予在中华人民共和国登记，特此发证。"
     分3行排版，行间距34pt，字型为楷体，大小为25pt，首行上距页面上边缘79mm，
     左距页面左边缘分别为41mm、23.25mm、23.25mm，宽分别为101mm、119mm、90.5mm，
     内容在宽度范围内水平靠左对齐，第1、2行字符间距紧缩-0.4pt，
     第3行字符间距紧缩-0.8pt。
     "This is to certify that through test""and examination, the following Product"
     "is verified safe and effective, and is hereby registered by the People's
     Republic of China.Valid: from" 分3行排版，字型为Times New Roman，大小为25pt，
     首行上距页面上边缘79mm，左距页面左边缘分别为41mm、23.25mm、23.25mm，
     宽分别为101mm、119mm、90.5mm，内容在宽度范围内水平靠左对齐，
     第1、2行字符间距紧缩-0.4pt，第3行字符间距紧缩-0.8pt。
     "Valid:" 字型为Times New Roman，大小为12pt，加粗，上距页面下边缘
     27.25mm，左距页面左边缘41.25mm，宽13mm，内容在宽度范围内均匀分布。
     "from" "to" 共处1行排版，字型为Times New Roman，大小为12pt，垂直方向上
     与"Valid:"居中对齐，上距页面下边缘27.25mm，左距页面左边缘分别为
     54.25mm、65.5mm、80mm、91.5mm、96mm、112mm、124mm，宽6mm，
     内容在宽度范围内水平居中对齐。
     "Valid:" 居中对齐，上距页面下边缘27.25mm，左距页面左边缘分别为
     54.25mm、65.5mm、80mm、91.5mm、96mm、112mm、124mm，宽分别为
     10.5mm、5mm，内容在宽度范围内均匀分布。

【图页的四块结构(见 0658-0660 经验)】
  图题 / 图 / 图注 / 正文 —— 图内文字**不抄**。
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(REPO, "minimax", "04标准及标准目录",
                   "04_全国一体化政务服务平台、电子证照、饲料和饲料添加剂进口登记证",
                   "0978.md")

FIG_CAPTION = "图2 饲料和饲料添加剂进口登记证样式"

BODY = [
    "6mm；“（）”“外饲准字”在宽度范围内均匀分布，“号”在宽度范围内水平居中对齐，"
    "“（）”字型为Times New Roman，“外饲准字”“号”字型为楷体。",

    "“经试验、审查，该产品安全、有效，准予在中华人民共和国登记，特此发证。”"
    "分3行排版，行间距34pt，字型为楷体，大小为25pt，首行上距页面上边缘79mm，"
    "左距页面左边缘分别为41mm、23.25mm、23.25mm，宽分别为101mm、119mm、90.5mm，"
    "内容在宽度范围内水平靠左对齐，第1、2行字符间距紧缩-0.4pt，"
    "第3行字符间距紧缩-0.8pt。",

    "“This is to certify that through test”“and examination, the following Product”"
    "“is verified safe and effective, and is hereby registered by the People's "
    "Republic of China.Valid: from”分3行排版，字型为Times New Roman，大小为25pt，"
    "首行上距页面上边缘79mm，左距页面左边缘分别为41mm、23.25mm、23.25mm，"
    "宽分别为101mm、119mm、90.5mm，内容在宽度范围内水平靠左对齐，"
    "第1、2行字符间距紧缩-0.4pt，第3行字符间距紧缩-0.8pt。",

    "“Valid:”字型为Times New Roman，大小为12pt，加粗，上距页面下边缘27.25mm，"
    "左距页面左边缘41.25mm，宽13mm，内容在宽度范围内均匀分布。",

    "“from”“to”共处1行排版，字型为Times New Roman，大小为12pt，垂直方向上"
    "与“Valid:”居中对齐，上距页面下边缘27.25mm，左距页面左边缘分别为"
    "54.25mm、65.5mm、80mm、91.5mm、96mm、112mm、124mm，宽6mm，"
    "内容在宽度范围内水平居中对齐。",

    "“Valid:”居中对齐，上距页面下边缘27.25mm，左距页面左边缘分别为"
    "54.25mm、65.5mm、80mm、91.5mm、96mm、112mm、124mm，宽分别为10.5mm、5mm，"
    "内容在宽度范围内均匀分布。",
]

MUST = [
    FIG_CAPTION,
    "6mm；“（）”“外饲准字”在宽度范围内均匀分布",
    "“号”在宽度范围内水平居中对齐",
    "Times New Roman",
    "“经试验、审查，该产品安全、有效，准予在中华人民共和国登记，特此发证。”",
    "分3行排版，行间距34pt，字型为楷体，大小为25pt，首行上距页面上边缘79mm",
    "左距页面左边缘分别为41mm、23.25mm、23.25mm，宽分别为101mm、119mm、90.5mm",
    "第1、2行字符间距紧缩-0.4pt，第3行字符间距紧缩-0.8pt",
    "“This is to certify that through test”“and examination, the following Product”",
    "“is verified safe and effective, and is hereby registered by the People's "
    "Republic of China.Valid: from”",
    "“Valid:”字型为Times New Roman，大小为12pt，加粗，上距页面下边缘27.25mm",
    "左距页面左边缘41.25mm，宽13mm",
    "“from”“to”共处1行排版",
    "54.25mm、65.5mm、80mm、91.5mm、96mm、112mm、124mm",
    "宽分别为10.5mm、5mm",
]

# 图内的文字**不能**出现在正文里
MUST_NOT = [
    "<table",
    "REGISTERED LICENSELicense No.:",     # 图内文字被当正文
    "进 口 登 记 证",
    "许可证号",
    "申请企业名称",
]


def build():
    parts = []
    # 图题 + 图占位(不抄图内文字)
    parts.append("**" + FIG_CAPTION + "**")
    parts.append("")
    parts.append("<!-- 图2: 饲料和饲料添加剂进口登记证样式(证书模板图) -->")
    parts.append("")
    for p in BODY:
        parts.append(p)
        parts.append("")
    return "\n".join(parts).rstrip("\n") + "\n"


def check(txt):
    errs = []
    for k in MUST:
        if k not in txt:
            errs.append("缺: " + k)
    for k in MUST_NOT:
        if k in txt:
            errs.append("不应出现: " + k)
    # 段落数(图题 1 + 图注释 1 + 正文 6 = 8)
    paras = [p for p in txt.split("\n\n") if p.strip()]
    n = len(paras)
    if n != 8:
        errs.append("段落数 != 8 (图题1+图注1+正文6), 实际 %d" % n)
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
    print("OK 0978 -> %s (%d 字节, 0 表, 图2 + 6 段正文)" %
          (os.path.relpath(OUT, REPO), len(txt.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
