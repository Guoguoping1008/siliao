"""
语义排序: 按法规 part + 章/节/条编号 重新排序, 输出 md / html / pdf 三种格式。

输入:
  data/markdown/<doc_id>/articles.json (article_splitter 产物)
  data/markdown/<doc_id>/chapters.json
  data/markdown/<doc_id>/merged.md (原始合并文本)

输出:
  data/markdown/<doc_id>/sorted.md
  data/markdown/<doc_id>/sorted.html
  data/markdown/<doc_id>/sorted.pdf
  data/markdown/<doc_id>/sort_report.json (排序逻辑 + 人工确认用)

排序规则:
  1. 按"法规 part" 分类:
     - 一、法规: 《饲料和饲料添加剂管理条例》
     - 二、制度文件: 《新饲料...审定办法》《新饲料...管理办法》等规范性文件
     - 三、法律: 畜牧法 / 农产品质量安全法 / 兽药管理条例等
     - 四、标准: GB 10648 / GB 13078 等
  2. 同一 part 内,按规章标题字典序
  3. 同一规章内,按"第X条"中文数字顺序
  4. 编号识别: "第一条" = 1, "第十一条" = 11, "第二十三条" = 23 ...

为什么:
  物理页序未知 (raw-pic 文件名是 md5), 但 OCR 出的"规章标题" + "第X条"编号是结构化信息
  按语义重排后, 法规汇编成为连贯可读的版本, 供人工确认。

用法:
  python build/ocr/semantic_sort.py data/markdown/feed-law-collection-2023
"""

from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path


# 中文数字 → 阿拉伯数字
CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "百": 100, "千": 1000}


def cn_to_int(cn: str) -> int:
    """中文数字 → 整数 (支持 一/二/十/百组合, 如 '二十三' = 23)"""
    if not cn:
        return 0
    if cn == "十":
        return 10
    result = 0
    current = 0
    for c in cn:
        if c in CN_DIGIT:
            v = CN_DIGIT[c]
            if v >= 10:
                if current == 0:
                    current = 1
                result += current * v
                current = 0
            else:
                current = v
        else:
            return 0
    return result + current


def parse_article_number(num_str: str) -> int:
    """解析 '第十一条' / '第二十三条' → 11 / 23"""
    m = re.match(r"第(.+)条", num_str)
    if m:
        return cn_to_int(m.group(1))
    return 0


# 法规 part 优先级 (按汇编顺序)
PART_ORDER = {
    "前言": 0,
    "一、法规": 1,
    "二、制度文件": 2,
    "三、法律": 3,
    "四、标准": 4,
}


# 规章标题识别 — 用首段关键短语做关键词, 用于把当前章节归属到具体规章
REGULATION_KEYWORDS = [
    ("饲料和饲料添加剂管理条例", "一、法规", "饲料和饲料添加剂管理条例"),
    ("新饲料和新饲料添加剂管理办法", "二、制度文件", "新饲料和新饲料添加剂管理办法"),
    ("新饲料、新饲料添加剂审定办法", "二、制度文件", "新饲料、新饲料添加剂审定办法"),
    ("饲料添加剂安全使用规范", "二、制度文件", "饲料添加剂安全使用规范"),
    ("饲料添加剂品种目录", "二、制度文件", "饲料添加剂品种目录"),
    ("饲料质量安全管理规范", "二、制度文件", "饲料质量安全管理规范"),
    ("兽药管理条例", "三、法律", "兽药管理条例"),
    ("农业转基因生物安全管理条例", "三、法律", "农业转基因生物安全管理条例"),
    ("畜牧法", "三、法律", "畜牧法"),
    ("农产品质量安全法", "三、法律", "农产品质量安全法"),
    ("饲料标签", "四、标准", "饲料标签 GB 10648"),
    ("饲料卫生标准", "四、标准", "饲料卫生标准 GB 13078"),
]


def detect_regulation(text: str) -> tuple[str | None, str | None]:
    """从条文 text 识别所属规章 + part"""
    for kw, part, regulation in REGULATION_KEYWORDS:
        if kw in text:
            return part, regulation
    return None, None


# chapter_id → 默认规章的 fallback (用于"本条例/本办法"等代词引用)
# 基于 chapter_splitter 切出的实际章节, 推断属于哪个规章
CHAPTER_TO_REGULATION = {
    "fee_ch01": ("二、制度文件", "新饲料、新饲料添加剂审定办法"),  # 页17 起始
    "fee_ch02": ("一、法规", "饲料和饲料添加剂管理条例"),  # 一、法规 = 条例
    "fee_ch03": ("二、制度文件", "新饲料和新饲料添加剂管理办法"),  # 页15 起始
    "fee_ch04": ("一、法规", "进口登记规定"),  # 一、法规 重复出现, 暂归进口登记
    "fee_ch00": ("前言", "前言"),
}


def classify_article(article: dict) -> tuple[str, str]:
    """先尝试关键字识别, 失败则用 chapter fallback"""
    part, regulation = detect_regulation(article["text"])
    if part:
        return part, regulation
    # fallback 到章节映射
    return CHAPTER_TO_REGULATION.get(
        article["chapter_id"],
        ("未知", "未分类"),
    )


def semantic_sort(doc_dir: Path):
    """主入口: 重排 articles + 输出 md/html/pdf"""
    articles_path = doc_dir / "articles.json"
    chapters_path = doc_dir / "chapters.json"
    merged_path = doc_dir / "merged.md"

    if not articles_path.exists():
        raise FileNotFoundError(f"未找到 {articles_path}, 先跑 article_splitter.py")

    articles = json.loads(articles_path.read_text(encoding="utf-8"))
    chapters = json.loads(chapters_path.read_text(encoding="utf-8"))

    # 1. 给每个 article 打 part + regulation 标签
    for a in articles:
        part, regulation = classify_article(a)
        a["_part"] = part
        a["_regulation"] = regulation
        a["_article_num"] = parse_article_number(a["number"])

    # 2. 排序: part 优先级 → regulation 字典序 → article_num 升序
    articles_sorted = sorted(
        articles,
        key=lambda a: (
            PART_ORDER.get(a["_part"], 99),
            a["_regulation"],
            a["_article_num"],
        ),
    )

    # 3. 生成 markdown
    md_lines = []
    md_lines.append(f"# {doc_dir.name} - 语义排序后内容")
    md_lines.append("")
    md_lines.append("> 本文档由 raw-pic OCR + 章节切分 + 语义重排 生成。")
    md_lines.append("> 内容可能存在 OCR 误差, 请人工核对后再用于生产。")
    md_lines.append("")
    md_lines.append(f"- 总条文: {len(articles_sorted)}")
    md_lines.append(f"- 总章节: {len(chapters)}")
    md_lines.append("")

    current_part = None
    current_regulation = None
    for a in articles_sorted:
        # part 切换时输出分隔
        if a["_part"] != current_part:
            current_part = a["_part"]
            md_lines.append("")
            md_lines.append(f"## {current_part}")
            md_lines.append("")
            current_regulation = None
        # regulation 切换时输出规章标题
        if a["_regulation"] != current_regulation:
            current_regulation = a["_regulation"]
            md_lines.append("")
            md_lines.append(f"### {current_regulation}")
            md_lines.append("")

        md_lines.append(f"**{a['number']}**")
        md_lines.append("")
        md_lines.append(a["text"])
        md_lines.append("")
        md_lines.append("---")
        md_lines.append("")

    sorted_md = "\n".join(md_lines)
    sorted_md_path = doc_dir / "sorted.md"
    sorted_md_path.write_text(sorted_md, encoding="utf-8")
    print(f"[OK] sorted.md: {len(sorted_md)} 字符")

    # 4. 写 sort_report.json (排序逻辑 + 分类明细)
    report = {
        "total_articles": len(articles_sorted),
        "total_chapters": len(chapters),
        "part_distribution": {},
        "regulation_distribution": {},
        "articles_sorted": [
            {
                "article_id": a["article_id"],
                "chapter_id": a["chapter_id"],
                "number": a["number"],
                "article_num": a["_article_num"],
                "part": a["_part"],
                "regulation": a["_regulation"],
                "text_preview": a["text"][:60],
            }
            for a in articles_sorted
        ],
    }
    for a in articles_sorted:
        report["part_distribution"].setdefault(a["_part"], 0)
        report["part_distribution"][a["_part"]] += 1
        report["regulation_distribution"].setdefault(a["_regulation"], 0)
        report["regulation_distribution"][a["_regulation"]] += 1

    report_path = doc_dir / "sort_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] sort_report.json")

    # 5. 输出 HTML
    html_body = []
    for a in articles_sorted:
        html_body.append(
            f"<section id='{a['article_id']}'>"
            f"<h3>{a['number']} <small>({a['_regulation']} / {a['_part']})</small></h3>"
            f"<p>{a['text'].replace(chr(10), '<br>')}</p>"
            f"<p><small>原始 chapter: {a['chapter_id']} · 序号: {a['_article_num']}</small></p>"
            f"</section>"
        )
    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{doc_dir.name} 语义排序</title>
<style>
  body {{ font-family: "Microsoft YaHei", sans-serif; max-width: 800px; margin: 2em auto; padding: 0 1em; }}
  h1 {{ border-bottom: 2px solid #333; }}
  h2 {{ background: #e0e0e0; padding: 0.4em; margin-top: 2em; }}
  h3 {{ color: #0066cc; border-left: 4px solid #0066cc; padding-left: 0.5em; }}
  section {{ margin-bottom: 1.5em; border-bottom: 1px dashed #ccc; padding-bottom: 1em; }}
  small {{ color: #888; font-weight: normal; }}
  p {{ line-height: 1.7; }}
</style>
</head>
<body>
<h1>{doc_dir.name} - 语义排序后内容</h1>
<p><em>OCR + 语义重排生成, 共 {len(articles_sorted)} 条, 请人工核对。</em></p>
{''.join(html_body)}
</body>
</html>"""
    html_path = doc_dir / "sorted.html"
    html_path.write_text(html_content, encoding="utf-8")
    print(f"[OK] sorted.html")

    # 6. 输出 PDF
    try:
        # 尝试 reportlab
        import importlib.util
        if importlib.util.find_spec("reportlab"):
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
            from reportlab.lib.units import cm

            pdf_path = doc_dir / "sorted.pdf"
            doc = SimpleDocTemplate(str(pdf_path), pagesize=A4,
                                    leftMargin=2*cm, rightMargin=2*cm,
                                    topMargin=2*cm, bottomMargin=2*cm)
            styles = getSampleStyleSheet()
            title_style = styles["Heading1"]
            part_style = styles["Heading2"]
            reg_style = styles["Heading3"]
            body_style = styles["BodyText"]

            story = []
            story.append(Paragraph(f"{doc_dir.name} - 语义排序后内容", title_style))
            story.append(Paragraph(f"共 {len(articles_sorted)} 条 · OCR + 语义重排, 请人工核对", body_style))
            story.append(Spacer(1, 0.5*cm))

            for a in articles_sorted:
                # Part / Regulation 分隔用大字号
                if a["_part"] != current_part:
                    story.append(Spacer(1, 0.5*cm))
                    story.append(Paragraph(a["_part"], part_style))
                story.append(Paragraph(a["_regulation"], reg_style))
                story.append(Paragraph(a["number"], styles["Heading4"]))
                # 段落里换行转 <br/>
                txt = a["text"].replace(chr(10), "<br/>")
                story.append(Paragraph(txt, body_style))
                story.append(Spacer(1, 0.3*cm))

            doc.build(story)
            print(f"[OK] sorted.pdf")
        else:
            print(f"[SKIP] sorted.pdf: reportlab 未安装, 跳过 PDF 输出")
    except Exception as e:
        print(f"[SKIP] sorted.pdf: {e}")

    # 7. 打印分布
    print()
    print("Part 分布:")
    for part, n in sorted(report["part_distribution"].items(), key=lambda x: PART_ORDER.get(x[0], 99)):
        print(f"  {part}: {n} 条")
    print("\nRegulations:")
    for reg, n in sorted(report["regulation_distribution"].items()):
        print(f"  {reg}: {n} 条")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("doc_dir", type=Path)
    args = p.parse_args()
    semantic_sort(args.doc_dir)


if __name__ == "__main__":
    main()