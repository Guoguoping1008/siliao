"""
合并 pic2md.py 产出的按页 .md → 单一 .md,清理页眉/页码/水印注释。

为什么需要独立脚本:
- chapter_splitter.py 假设输入是单 .md, 而 raw-pic OCR 是按页拆的
- 这本书的"页眉"是"饲料法规文件(2023) 页码", 出现在每页 (重复噪声)
- 需要去掉页眉/页码/章节扉页的孤立行, 合并成章/条粒度

清理规则:
- 去掉 <!-- page: N --> HTML 注释
- 去掉"饲料法规文件(2023)"页眉 (跨页重复)
- 合并连续短行成段落

输出: data/markdown/<doc_id>/merged.md   (chapter_splitter 可消费的整本)
"""

from __future__ import annotations
import argparse
import re
from pathlib import Path


PAGE_COMMENT_RE = re.compile(r"<!--\s*page:\s*\d+\s*-->")
HEADER_RE = re.compile(r"饲料法规文件[（(]?\s*\d{4}\s*[)）]?\s*\d+\s*$")
LEADING_NUM_TITLE = re.compile(r"^[一二三四五六七八九十]+、\s*([^\s]+)\s+\d+\s*$")


def clean_page(text: str) -> str:
    """清理单页 markdown: 去注释 + 去页眉"""
    lines = text.splitlines()
    out = []
    for ln in lines:
        ln = PAGE_COMMENT_RE.sub("", ln).strip()
        if not ln:
            continue
        if HEADER_RE.match(ln):
            continue  # 去页眉
        out.append(ln)
    return "\n\n".join(out)


def join_pages(pages_dir: Path) -> str:
    """按文件名排序合并所有 pages/*.md → 单一 markdown"""
    md_files = sorted(pages_dir.glob("*.md"))
    parts = []
    for f in md_files:
        cleaned = clean_page(f.read_text(encoding="utf-8"))
        if cleaned:
            parts.append(cleaned)
    return "\n\n".join(parts)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("pages_dir", type=Path, help="pic2md.py 输出的 pages/ 目录")
    p.add_argument("--out", type=Path, default=None, help="输出文件, 默认 <pages_dir>/../merged.md")
    args = p.parse_args()

    merged = join_pages(args.pages_dir)
    out = args.out or (args.pages_dir.parent / "merged.md")
    out.write_text(merged, encoding="utf-8")

    n_chars = len(merged)
    n_paras = len([p for p in merged.split("\n\n") if p.strip()])
    print(f"[join_pages] {out}: {n_chars} 字符, {n_paras} 段落")


if __name__ == "__main__":
    main()