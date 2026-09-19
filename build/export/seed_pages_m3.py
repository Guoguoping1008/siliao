"""
Seed pages_m3 (M3 OCR 单页 md) → D1

按现有 schema 灌 documents / chapters / articles / articles_fts 四张表。

设计:
- doc_id = "feed-law-collection-2023-full" (已存在,只更新 title/doc_number)
- 不建 chapters (M3 单页 md 没有章节归属; 章节信息从 LLM 结构化产物 pages_struct 推断)
- articles: 每页当 1 个 article, 1.3KB 平均, FTS 友好
  - article_id = "flc23_p{seq:04d}" (4 位顺序号, 全 doc 唯一)
  - chapter_id = "flc23_p{seq:04d}_ch" (占位章节, 一页一章, 让 FK 不挂)
  - number = "p{seq:04d}"
  - title = page_no (物理页号) 或 stem
  - text = md 内容 (去掉页眉箭头标记)
  - r2_object_key = "<doc_id>/pages_m3/<stem>.md"
- documents 表 title 更新为 "饲料法规文件（2023）"

输出:
  build/export/seed_pages_m3.sql  (用 wrangler d1 execute --file 灌库)

不写 chapters.json/articles.json (M3 单页 md 模式没这些层)
"""

from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path("E:/workspace/siliao")
DEFAULT_DOC = "feed-law-collection-2023-full"
PAGES_DIR = ROOT / "data/markdown" / DEFAULT_DOC / "pages_m3"


def escape_sql(s: str) -> str:
    return s.replace("'", "''")


def clean_md(text: str) -> str:
    """去掉页眉箭头标记 / 多余空行"""
    # 去掉 >>> <<< 这种书页箭头标记 (M3 残留)
    text = re.sub(r"^[\s>]*(>>>|<<<|>>|<<)\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n[\s>]*(>>>|<<<|>>|<<)\s*\n", "\n", text)
    # 多空行压成单个
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", default=DEFAULT_DOC)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    pages_dir = ROOT / "data/markdown" / args.doc / "pages_m3"
    out_sql = Path(args.out) if args.out else ROOT / "build/export/seed_pages_m3.sql"
    out_sql.parent.mkdir(parents=True, exist_ok=True)

    doc_prefix = "flc23"  # feed-law-collection-2023

    # 按时间戳排序得到物理顺序
    page_files = sorted(pages_dir.glob("*__L.md"))
    print(f"[scan] {len(page_files)} L.md in {pages_dir}")

    # 同时拿对应的 R.md
    pairs = []
    for L in page_files:
        R = L.with_name(L.name.replace("__L.md", "__R.md"))
        if not R.exists():
            print(f"[warn] 缺 R: {L.name}", file=sys.stderr)
            continue
        L_text = clean_md(L.read_text(encoding="utf-8"))
        R_text = clean_md(R.read_text(encoding="utf-8"))
        # 提取物理页号
        m = re.search(r"(\d{14})", L.name)
        ts = m.group(1) if m else L.name
        pairs.append({
            "ts": ts,
            "stem": L.stem.replace("__L", ""),
            "L_text": L_text,
            "R_text": R_text,
            "L_size": len(L_text),
            "R_size": len(R_text),
        })
    pairs.sort(key=lambda x: x["ts"])

    print(f"[plan] {len(pairs)} 页 (每页 1 article)")

    # 生成 SQL
    lines: list[str] = []

    # 清空本 doc 数据 (幂等)
    lines.append(f"DELETE FROM articles_fts WHERE doc_id = '{args.doc}';")
    lines.append(f"DELETE FROM articles WHERE doc_id = '{args.doc}';")
    lines.append(f"DELETE FROM chapters WHERE doc_id = '{args.doc}';")
    lines.append(f"DELETE FROM documents WHERE doc_id = '{args.doc}';")

    # 插 documents
    title = "饲料法规文件（2023）"
    lines.append(
        f"INSERT INTO documents(doc_id, title, doc_number, version) "
        f"VALUES('{args.doc}', '{escape_sql(title)}', '农牧相关部令+公告汇编', 'm3-v1');"
    )

    # 占位 chapters: 全部 pages 归到一个 virtual chapter 'all_pages'
    virtual_ch = f"{doc_prefix}_all_pages"
    lines.append(
        f"INSERT INTO chapters(chapter_id, doc_id, number, title, article_count, sort_order, r2_object_key) "
        f"VALUES('{virtual_ch}', '{args.doc}', 'all', '全部页 (M3 OCR)', {len(pairs)}, 1, '{virtual_ch}.md');"
    )

    # 插每页为 1 个 article
    for seq, p in enumerate(pairs, 1):
        article_id = f"{doc_prefix}_p{seq:04d}"
        number = f"p{seq:04d}"
        title = p["stem"]
        # 拼 L+R, 但 R 标 "(右页)" 起头避免和左页粘连
        full_text = p["L_text"]
        if p["R_text"]:
            full_text = full_text + "\n\n---\n\n" + p["R_text"] if full_text else p["R_text"]
        if not full_text:
            full_text = "(空白页)"
        r2_key = f"{args.doc}/pages_m3/{p['stem']}.md"

        lines.append(
            f"INSERT INTO articles(article_id, chapter_id, doc_id, number, title, r2_object_key) "
            f"VALUES('{article_id}', '{virtual_ch}', '{args.doc}', '{number}', "
            f"'{escape_sql(title)}', '{r2_key}');"
        )
        lines.append(
            f"INSERT INTO articles_fts(article_id, chapter_id, doc_id, number, title, text) "
            f"VALUES('{article_id}', '{virtual_ch}', '{args.doc}', '{number}', "
            f"'{escape_sql(title)}', '{escape_sql(full_text)}');"
        )

    # 写
    out_sql.write_text("\n".join(lines) + "\n", encoding="utf-8")
    total_chars = sum((len(p["L_text"]) + len(p["R_text"])) for p in pairs)
    print(f"[write] {out_sql}")
    print(f"[write] {len(lines)} SQL 行")
    print(f"[stats] {len(pairs)} articles, 总字符 {total_chars/1024/1024:.2f} MB, 平均 {total_chars/len(pairs):.0f} B/article")
    return 0


if __name__ == "__main__":
    sys.exit(main())
