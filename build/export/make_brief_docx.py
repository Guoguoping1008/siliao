#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成面向部门领导的 1 页 Word 简报。

## 为什么是「一页」

领导不会读技术文档。这份材料要在**一次扫视**里说清三件事:
1. 现在有什么能用
2. 还有什么没做、要多久、要花多少钱
3. 需要领导拍板什么

因此:不写表名/接口/算法,只写**部门日常语言**;数字全部来自生产实测。

## 数据来源

全部数字在写死前都用生产 API / D1 实测过(见 docs/deliverable-inventory-and-plan.md)。
"""

from __future__ import annotations

import os

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(REPO, "docs", "饲料法规智能助手-功能清单与计划-一页简报.docx")

# ── 配色 ──
C_DARK = RGBColor(0x1F, 0x33, 0x46)   # 深蓝灰:标题
C_ACCENT = RGBColor(0x1B, 0x5E, 0x8C)  # 主蓝
C_GREEN = RGBColor(0x1B, 0x7A, 0x3D)   # 已完成
C_ORANGE = RGBColor(0xB2, 0x62, 0x00)  # 待开发
C_GREY = RGBColor(0x60, 0x6B, 0x76)    # 辅助文字
C_LINE = "D4DBE2"


def shade(cell, hex_color):
    """单元格底纹。"""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def set_font(run, size=10.5, bold=False, color=None, name="微软雅黑"):
    run.font.name = name
    run.font.size = Pt(size)
    run.bold = bold
    if color is not None:
        run.font.color.rgb = color
    # 中文字形必须显式设 eastAsia,否则 Word 会用默认字体渲染
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:eastAsia"), name)
    rFonts.set(qn("w:ascii"), name)
    rFonts.set(qn("w:hAnsi"), name)


def para(doc, text="", size=10.5, bold=False, color=None, align=None,
         space_before=0, space_after=4, indent=None, line=None):
    p = doc.add_paragraph()
    if align is not None:
        p.alignment = align
    pf = p.paragraph_format
    pf.space_before = Pt(space_before)
    pf.space_after = Pt(space_after)
    if line:
        pf.line_spacing = line
    if indent is not None:
        pf.left_indent = Cm(indent)
    if text:
        set_font(p.add_run(text), size, bold, color)
    return p


def heading(doc, text, size=13, color=C_DARK, before=9, after=4):
    return para(doc, text, size=size, bold=True, color=color,
                space_before=before, space_after=after)


def hrule(doc, color=C_LINE, size=6):
    """段落下边框,当分隔线用。"""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(1)
    p.paragraph_format.space_after = Pt(3)
    pPr = p._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), color)
    bdr.append(bottom)
    pPr.append(bdr)
    return p


def cell_text(cell, text, size=9, bold=False, color=None, align=None, tight=False):
    cell.text = ""
    p = cell.paragraphs[0]
    if align is not None:
        p.alignment = align
    pad = 0.5 if tight else 1.5
    p.paragraph_format.space_before = Pt(pad)
    p.paragraph_format.space_after = Pt(pad)
    p.paragraph_format.line_spacing = 0.95 if tight else 1.0
    for i, line in enumerate(str(text).split("\n")):
        if i:
            p = cell.add_paragraph()
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(pad)
            p.paragraph_format.line_spacing = 0.95 if tight else 1.0
            if align is not None:
                p.alignment = align
        set_font(p.add_run(line), size, bold, color)


def set_col_widths(table, widths_cm):
    table.autofit = False
    for row in table.rows:
        for i, w in enumerate(widths_cm):
            if i < len(row.cells):
                row.cells[i].width = Cm(w)


def build():
    doc = Document()

    # ── 页面设置:A4 + 窄边距(1 页塞下) ──
    s = doc.sections[0]
    s.page_width = Cm(21.0)
    s.page_height = Cm(29.7)
    s.top_margin = Cm(0.9)
    s.bottom_margin = Cm(0.8)
    s.left_margin = Cm(1.5)
    s.right_margin = Cm(1.5)

    # 默认样式
    st = doc.styles["Normal"]
    st.font.name = "微软雅黑"
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")

    # ══ 页眉 ══
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p.paragraph_format.space_after = Pt(1)
    set_font(p.add_run("中国农业质量研究院 · 饲料检测研究所    2026年11月"),
             8, False, C_GREY)

    para(doc, "饲料法规智能助手", size=17, bold=True, color=C_DARK,
         space_after=0, line=0.95)
    para(doc, "已建成功能清单与下一步开发计划", size=11, bold=True,
         color=C_ACCENT, space_after=2)
    hrule(doc)

    para(doc,
         "一句话：平台已上线，可用于法规查询、条文溯源与用量合规判定；"
         "下一步重点是把它从「法规检索工具」升级为「检测工作台」。",
         size=9.5, color=C_DARK, space_after=4, line=1.15)

    # ══ 一、已建成 ══
    heading(doc, "一、已建成并可用的功能（已在生产环境运行）", size=12, before=0, after=3)

    t = doc.add_table(rows=1, cols=3)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = ["功能（部门日常说法）", "能解决什么问题", "实测情况"]
    for i, h in enumerate(hdr):
        cell_text(t.rows[0].cells[i], h, 8.5, True, C_DARK, tight=True)
        shade(t.rows[0].cells[i], "E8EEF4")

    done = [
        ("法规知识库\n196 部法规 · 3145 条文",
         "饲料、饲料添加剂、兽药、检测方法等全部法规标准，按目录树浏览",
         "已上线\n可点开原文"),
        ("全文检索\n支持中文关键词",
         "输入「维生素C 限量」立刻找到相关条文，并显示原文片段",
         "已上线\n一次 20 条"),
        ("条文与章节原文查阅",
         "从检索结果直接跳到法规原文，核对具体条款怎么写的",
         "已上线"),
        ("AI 智能问答\n带条款出处",
         "用大白话提问（如「维生素C 猪能加多少」），答案自动标注依据第几条",
         "已上线\n实测答对 300mg/kg"),
        ("多轮追问",
         "接着上一问继续问，系统自动理解「那鸡呢」指的是什么",
         "已上线\n指代自动补全"),
        ("用量合规速查\n（最重要）",
         "输入物质、动物、用量，判定「合规 / 超标 / 规则未覆盖」，并附依据条款",
         "功能已完成\n等人工校核后开放"),
        ("知识图谱\n481 个实体",
         "把物质、法规、机构等串成关系网，如「维生素C」关联到哪些条款",
         "已上线\n含 117 条别名"),
    ]
    for name, problem, status in done:
        row = t.add_row()
        cell_text(row.cells[0], name, 8, True, C_DARK, tight=True)
        cell_text(row.cells[1], problem, 8, tight=True)
        c = status.split("\n")[0]
        col = C_GREEN if "已上线" in c else C_ORANGE
        cell_text(row.cells[2], status, 8, True, col, tight=True)
    set_col_widths(t, [4.6, 8.6, 4.6])

    # ══ 二、为什么「合规速查」还没开放 + 下一步 ══
    para(doc, "", size=3, space_after=0)
    box = doc.add_table(rows=1, cols=1)
    box.style = "Table Grid"
    c = box.rows[0].cells[0]
    shade(c, "FDF3E7")
    cell_text(c,
              "需向领导说明：用量合规速查是检测所最常用的功能，程序已建好并通过测试，"
              "13 项测试全部正确判定。它现在显示「规则未覆盖」——不是功能坏了，"
              "而是法规里的限量条文需检测所专业人员逐条核对签字后才能启用。"
              "这是刻意设置的安全门：宁可提示「请人工确认」，也不能拿没核对过的规则出合规结论。"
              "工作量：人工核对约 1–2 天（检测所最熟悉业务），系统侧半天即可开放。",
              8.5, False, C_DARK, tight=True)
    set_col_widths(box, [17.8])

    # ══ 三、下一步 ══
    para(doc, "", size=3, space_after=0)
    heading(doc, "二、下一步开发计划（按日常使用频率排序）", size=12, before=0, after=3)

    t2 = doc.add_table(rows=1, cols=4)
    t2.style = "Table Grid"
    hdr2 = ["优先级", "功能", "解决的日常问题", "周期"]
    for i, h in enumerate(hdr2):
        cell_text(t2.rows[0].cells[i], h, 8.5, True, C_DARK, tight=True)
        shade(t2.rows[0].cells[i], "E8EEF4")

    plan = [
        ("P0", "开放用量合规速查",
         "现在就能查「这个用量合不合规」", "约 3 天\n（人工为主）"),
        ("P1\n★最高价值", "检测项目查询 +\n检测方法标准检索",
         "「这个产品要检哪些项目？」「按哪个标准检？」\n"
         "——现在要人工翻 20 页标准目录；数据已在库中，只是尚未结构化",
         "3–5 天"),
        ("P2", "禁用物质判定",
         "「这个物质是不是禁用的？」（现 37 条规则全是限量类，无禁用类）", "2–3 天"),
        ("P3\nP4", "配方批量审查\n标签审查",
         "上传配方表筛出风险成分；对照 GB 10648 检查标签缺项与违规宣称",
         "各 5–8 天\n（可并行）"),
    ]
    for pr, name, problem, dur in plan:
        row = t2.add_row()
        cell_text(row.cells[0], pr, 8, True,
                  C_ACCENT if "★" not in pr else C_ORANGE,
                  WD_ALIGN_PARAGRAPH.CENTER, tight=True)
        cell_text(row.cells[1], name, 8, True, C_DARK, tight=True)
        cell_text(row.cells[2], problem, 8, tight=True)
        cell_text(row.cells[3], dur, 8, False, None, WD_ALIGN_PARAGRAPH.CENTER, tight=True)
    set_col_widths(t2, [2.2, 4.0, 8.4, 3.2])

    # ══ 四、建议 ══
    para(doc, "", size=3, space_after=0)
    heading(doc, "三、建议与需要领导拍板的事项", size=12, before=0, after=3)

    box2 = doc.add_table(rows=1, cols=1)
    box2.style = "Table Grid"
    c = box2.rows[0].cells[0]
    shade(c, "EAF3EC")
    cell_text(c,
              "建议先做 P0 + P1（约 1–2 个月）：覆盖检测所最常问的三个问题——"
              "「查什么、按什么标准检、合不合规」，投入小、见效快，P1 所需数据已在库中，无需新增采集。"
              "P3、P4 建议等实际使用一段时间后再定：涉及企业和客户提交的数据，"
              "使用方式可能还会调整，现在做容易返工。\n"
              "需领导拍板：① 谁负责 P0 的限量条文人工核对（建议业务骨干，需 1–2 天）"
              "② P3 涉及企业配方，属敏感信息，届时需评估是否在内部署",
              8.5, False, C_DARK, tight=True)
    set_col_widths(box2, [17.8])

    # ══ 页脚 ══
    # ⚠️ **不要加空段落做间距** —— 空段落自带行高,会把页脚挤到第 2 页。
    #    用 hrule 自己的 space_before/after 控制间距。
    hrule(doc)
    para(doc,
         "附：全部功能均已在生产环境实测验证，非原型演示。",
         7.5, color=C_GREY, space_after=0, line=1.0)

    doc.save(OUT)
    print(f"[OK] → {OUT}")


if __name__ == "__main__":
    build()
