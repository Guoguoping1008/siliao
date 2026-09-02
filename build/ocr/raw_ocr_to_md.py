"""
直接从 raw_ocr/<stem>.json 重新生成 markdown, **不做 paragraph 聚合**,
每条 PaddleOCR 行作为一行输出。

为什么需要这个脚本:
- pic2md.py 用 group_by_paragraph(y_gap_ratio=1.2) 物理聚段,
  横版大图 + 表格页 段落聚不准, 章节标题被吞到正文里
- raw_ocr/*.json 里 PaddleOCR 行已经按 y 排好序, 章节标题是独立行
- 这个脚本跳过 paragraph 聚合, 一行一行输出, 让 article_splitter 的 text-based 反切能稳定抓到锚点

用法:
  python build/ocr/raw_ocr_to_md.py data/markdown/feed-trial-guideline-2023
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


# 页眉 / 页码 regex (pic2md 里也有, 复用同款)
PAGE_COMMENT_OLD = re.compile(r"<!--\s*page:\s*\d+\s*-->")
HEADER_RE = re.compile(r"饲料法规文件[（(]?\s*\d{4}\s*[)）]?\s*\d*\s*$")


def raw_ocr_to_page_md(raw_ocr: list[dict], page_no: int) -> str:
    """
    raw_ocr: PaddleOCR 行列表 [{bbox, text, score}, ...], 已经 y-sort 过
    返回单页 markdown: 每行一行, 不做 paragraph 聚合
    """
    out_lines = [f"<!-- page: {page_no} -->"]
    for ln in raw_ocr:
        text = ln["text"].strip()
        if not text:
            continue
        # 去页眉
        if HEADER_RE.match(text):
            continue
        out_lines.append(text)
    return "\n\n".join(out_lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("doc_dir", type=Path, help="data/markdown/<doc_id>/ 目录")
    args = p.parse_args()

    raw_ocr_dir = args.doc_dir / "raw_ocr"
    pages_dir = args.doc_dir / "pages"

    files = sorted(raw_ocr_dir.glob("*.json"))
    print(f"[raw_ocr_to_md] {len(files)} 页 raw_ocr → {pages_dir}/ (覆盖)")

    pages_dir.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(files, 1):
        data = json.loads(f.read_text(encoding="utf-8"))
        md = raw_ocr_to_page_md(data, page_no=i)
        out = pages_dir / f"{f.stem}.md"
        out.write_text(md, encoding="utf-8")

    print(f"[raw_ocr_to_md] 完成: {len(files)} 页")


if __name__ == "__main__":
    main()