"""
水印残留后处理: 对 pic2md.py 产出的 .md 文件做 regex 清理。

为什么是独立脚本:
- pic2md.py 跑一次 PaddleOCR 约 3 分钟, 不值得为水印清理重跑
- 水印残留形态很固定 ("Quad Camera" / "HUAWEI P4O" / 单独的 "G")
- regex 清理 0 风险, 即便误伤也只是去一两个字

用法:
  python build/ocr/strip_watermark.py data/markdown/feed-law-collection-2023/pages
"""

from __future__ import annotations
import argparse
import re
from pathlib import Path


WATERMARK_RESIDUE_RE = re.compile(
    r"(?:HUAWEI\s+P4O?\s*Pro\s*5G|Ultra\s+Vision\s+LEICA\s+Quad\s+Camera|Quad\s+Camera|\bG\s+Quad\s+Camera\b|\s+G\s*$)",
    re.IGNORECASE,
)

# "G " 单字出现在中间 (LEICA 边缘残字) — 谨慎, 只匹配前后空格的孤立 G
ISOLATED_G_RE = re.compile(r"\s+\bG\b\s+")


def strip(md: str) -> str:
    lines = md.split("\n")
    cleaned = []
    for ln in lines:
        ln = WATERMARK_RESIDUE_RE.sub("", ln).strip()
        ln = ISOLATED_G_RE.sub(" ", ln).strip()
        if ln:
            cleaned.append(ln)
    return "\n\n".join(cleaned)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("pages_dir", type=Path)
    args = p.parse_args()

    md_files = sorted(args.pages_dir.glob("*.md"))
    fixed = 0
    for f in md_files:
        orig = f.read_text(encoding="utf-8")
        cleaned = strip(orig)
        if cleaned != orig:
            f.write_text(cleaned, encoding="utf-8")
            fixed += 1
    print(f"[strip_watermark] 清理 {fixed}/{len(md_files)} 个文件")


if __name__ == "__main__":
    main()