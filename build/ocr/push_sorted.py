"""
sorted.md 上传 R2: 把语义排序后的 markdown 拆成按 part / regulation 分级上传。

为什么:
- push_to_r2.sh 上传的是 article_splitter 输出的原始 chapter/article (物理页序错乱)
- semantic_sort.py 输出的 sorted.md 是经过语义排序的版本 (按 part → regulation → 条)
- 上传 sorted 内容到 R2 的 sorted/ 子路径, 让前端可以做"按 part 浏览"或"按规章浏览"

输出结构 (R2):
  siliao-index/<doc_id>/sorted/
    sorted.md                  # 完整 sorted 全文
    parts/<part_name>.md       # 单个 part 的所有条文
    regulations/<safe_name>.md # 单个规章的所有条文

输入:
  data/markdown/<doc_id>/sorted.md
  data/markdown/<doc_id>/sort_report.json

用法:
  python build/ocr/push_sorted.py feed-law-collection-2023 --local
"""

from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path


SAFE_NAME_RE = re.compile(r"[^\w\u4e00-\u9fff\-]+")


def safe_name(s: str) -> str:
    """规章名 → R2 safe key (中文保留, 标点转 _)"""
    return SAFE_NAME_RE.sub("_", s).strip("_")


def split_sorted(sorted_md: str) -> tuple[dict[str, str], dict[str, str]]:
    """
    把 sorted.md 拆成 parts 和 regulations 两个 dict
    每个 entry 是 (name, markdown_body)
    """
    lines = sorted_md.split("\n")

    parts: dict[str, list[str]] = {}  # part_name -> 累积 lines
    regulations: dict[str, list[str]] = {}  # regulation_name -> lines

    current_part = None
    current_regulation = None

    for line in lines:
        m_part = re.match(r"^## (.+)$", line)
        m_reg = re.match(r"^### (.+)$", line)

        if m_part:
            current_part = m_part.group(1).strip()
            parts.setdefault(current_part, [])
            current_regulation = None  # 新 part, 重置 regulation
            continue
        if m_reg:
            current_regulation = m_reg.group(1).strip()
            regulations.setdefault(current_regulation, [])
            continue

        if current_part:
            parts[current_part].append(line)
        if current_regulation:
            regulations[current_regulation].append(line)

    parts_md = {k: "\n".join(v).strip() for k, v in parts.items()}
    regs_md = {k: "\n".join(v).strip() for k, v in regulations.items()}
    return parts_md, regs_md


def push_to_r2(doc_id: str, local: bool = True):
    doc_dir = Path("data/markdown") / doc_id
    sorted_md_path = doc_dir / "sorted.md"
    if not sorted_md_path.exists():
        print(f"[ERR] {sorted_md_path} 不存在, 先跑 semantic_sort.py")
        sys.exit(1)

    sorted_md = sorted_md_path.read_text(encoding="utf-8")
    parts_md, regs_md = split_sorted(sorted_md)
    print(f"[push] split: {len(parts_md)} parts, {len(regs_md)} regulations")

    # 用 wrangler CLI 上传 R2 (windows 下用 .cmd 包装)
    import subprocess
    import os
    wrangler_bin = "wrangler.cmd"  # PATH 里已有
    flag = "--local" if local else "--remote"

    bucket = "siliao-index"
    base = f"{bucket}/{doc_id}/sorted"

    # 上传 sorted.md
    cmd = [str(wrangler_bin), "r2", "object", "put", f"{base}/sorted.md",
           "--file", str(sorted_md_path), flag]
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"[push] sorted.md → {base}/sorted.md")

    # 上传 parts
    parts_dir = doc_dir / "sorted_parts"
    parts_dir.mkdir(exist_ok=True)
    for name, body in parts_md.items():
        p = parts_dir / f"{safe_name(name)}.md"
        header = f"# {name}\n\n> doc_id: {doc_id} · 法规 part\n\n"
        p.write_text(header + body, encoding="utf-8")
        cmd = [str(wrangler_bin), "r2", "object", "put", f"{base}/parts/{safe_name(name)}.md",
               "--file", str(p), flag]
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"[push] part: {name} → {base}/parts/{safe_name(name)}.md")

    # 上传 regulations
    regs_dir = doc_dir / "sorted_regs"
    regs_dir.mkdir(exist_ok=True)
    for name, body in regs_md.items():
        p = regs_dir / f"{safe_name(name)}.md"
        header = f"# {name}\n\n> doc_id: {doc_id} · 法规规章\n\n"
        p.write_text(header + body, encoding="utf-8")
        cmd = [str(wrangler_bin), "r2", "object", "put", f"{base}/regulations/{safe_name(name)}.md",
               "--file", str(p), flag]
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"[push] regulation: {name} → {base}/regulations/{safe_name(name)}.md")

    print(f"[push] DONE: {len(parts_md)} parts + {len(regs_md)} regulations + sorted.md")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("doc_id")
    p.add_argument("--local", action="store_true", default=True)
    p.add_argument("--remote", action="store_true")
    args = p.parse_args()
    local = not args.remote
    push_to_r2(args.doc_id, local=local)


if __name__ == "__main__":
    main()