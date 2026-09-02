"""
把 article_splitter_ar.py 输出的 sections.json 转换为 seed_d1.py 兼容的 articles.json。

GB/T 类技术标准没有"条文"概念, 把每个 section(包括顶级 chapter)
当作一个 article 灌库, 检索粒度 = section(节/子节/章节级)。

输入:  data/markdown/<doc_id>/sections.json + sections/*.md
输出:  data/markdown/<doc_id>/articles.json (article_splitter 兼容格式)

字段映射:
  section.section_id    → article.article_id  (section_id → article_id)
  section.belongs_to_chapter → article.chapter_id
  section.number        → article.number
  section.title         → article.title
  sections/<sid>.md body → article.text

用法:
  python build/ocr/sections_to_articles.py data/markdown/feed-trial-guideline-2023
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("doc_dir", type=Path, help="data/markdown/<doc_id>/ 目录")
    args = p.parse_args()

    sections_path = args.doc_dir / "sections.json"
    sections_dir = args.doc_dir / "sections"
    chapters_path = args.doc_dir / "chapters.json"

    sections = json.loads(sections_path.read_text(encoding="utf-8"))
    chapters = json.loads(chapters_path.read_text(encoding="utf-8"))

    # 章节索引: belongs_to_chapter (number) → chapter_id
    chapter_id_by_number: dict[str, str] = {}
    for c in chapters:
        # chapter.number 在合订本里可能重复(number="1" 出现多次),
        # 但我们只需要把章节 number → chapter_id 做映射, 同 number 第一次出现的
        # chapter_id 用就行 (seed_d1 不依赖 number 唯一性)
        if c["number"] not in chapter_id_by_number:
            chapter_id_by_number[c["number"]] = c["chapter_id"]

    articles = []
    for s in sections:
        sid = s["section_id"]
        md_path = sections_dir / f"{sid}.md"
        if not md_path.exists():
            print(f"[WARN] missing {md_path}, skip")
            continue
        body = md_path.read_text(encoding="utf-8")
        # 去掉 front-matter 注释行
        lines = [
            ln for ln in body.splitlines()
            if not ln.strip().startswith("<!--")
        ]
        text = "\n".join(lines).strip()

        # chapter_id 反查 (number → chapter_id)
        ch_id = chapter_id_by_number.get(s["belongs_to_chapter"], f"{s['doc_id'][:3]}_ch00")

        articles.append({
            "article_id": sid,
            "chapter_id": ch_id,
            "number": s["number"],
            "title": s["title"],
            "text": text,
        })

    out_path = args.doc_dir / "articles.json"
    out_path.write_text(json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] {len(articles)} articles → {out_path}")


if __name__ == "__main__":
    main()