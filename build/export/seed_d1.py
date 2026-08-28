"""
Seed D1: 把 data/markdown/<doc_id>/articles.json 灌入 articles_fts 全文索引。

跑法:
    # 1) 准备 miniflare 本地 D1
    npx wrangler d1 execute siliao-db --local --file ./schema.sql

    # 2) 跑 seed(读取 articles.json,把 text 字段入库)
    python build/export/seed_d1.py data/markdown/feed-law-2026/articles.json

    # 3) 上传到 R2 的章节/条文 markdown(单独跑 build/export/push_to_r2.sh)

也可以用于线上:
    npx wrangler d1 execute siliao-db --remote --file ./schema.sql
    npx wrangler d1 execute siliao-db --remote --command "INSERT INTO articles_fts ..."

数据流:
    articles.json(text 字段)  →  articles_fts 表(text 列)
    chapters.json             →  documents/chapters/articles 三张元数据表
"""

from __future__ import annotations
import json
import sys
from pathlib import Path


def escape_sql(s: str) -> str:
    """SQLite 单引号转义"""
    return s.replace("'", "''")


def main():
    if len(sys.argv) < 2:
        print("[ERR] usage: seed_d1.py <articles.json> [chapters.json]")
        sys.exit(1)

    arts_path = Path(sys.argv[1])
    raw_articles = json.loads(arts_path.read_text(encoding="utf-8"))
    # data/markdown/<doc_id>/articles.json  →  doc_id 是祖父目录名
    doc_id = arts_path.parent.name

    # 切分器产物没有 doc_id 字段,统一补上
    articles = [{**a, "doc_id": doc_id} for a in raw_articles]

    chapters: list[dict] = []
    if len(sys.argv) > 2:
        ch_path = Path(sys.argv[2])
        raw_chapters = json.loads(ch_path.read_text(encoding="utf-8"))
        chapters = [{**c, "doc_id": doc_id, "sort_order": idx + 1} for idx, c in enumerate(raw_chapters)]

    # 章节标题 → article_ids 反向索引,用于把章节名注入 articles 索引
    # 这样查"总则"能召回 ch01 的所有条文,查"法律责任"能召回 ch05 全部
    chapter_titles_by_art: dict[str, str] = {}
    for c in chapters:
        for aid in c.get("article_ids", []):
            # 拼章节全名:`第一章 总则`,章节号+标题,FTS5 trigram 更易命中
            chapter_titles_by_art[aid] = f"{c['number']} {c['title']}"

    # 输出一份可执行的 SQL(便于 wrangler d1 execute --file 直接吃)
    lines: list[str] = []

    # 清空 FTS5(幂等)
    lines.append("DELETE FROM articles_fts;")
    lines.append("DELETE FROM articles;")
    # 清空 chapters + documents(幂等,顺序:子表先)
    lines.append("DELETE FROM chapters;")
    lines.append("DELETE FROM documents;")

    # 灌 document(每部法规一行) — 先于 chapters(被 FK 引用)
    lines.append(
        f"INSERT INTO documents(doc_id, title) VALUES('{escape_sql(doc_id)}', '{escape_sql(doc_id)}');"
    )

    # 灌 chapter 元数据
    for c in chapters:
        lines.append(
            "INSERT INTO chapters(chapter_id, doc_id, number, title, article_count, sort_order, r2_object_key) "
            f"VALUES('{escape_sql(c['chapter_id'])}', '{escape_sql(c.get('doc_id', doc_id))}', "
            f"'{escape_sql(c['number'])}', '{escape_sql(c['title'])}', {len(c.get('article_ids', []))}, "
            f"{c.get('sort_order', 0)}, '{escape_sql(c['chapter_id'] + '.md')}');"
        )

    # 灌 articles 主表(FK 引用 chapters)
    for a in articles:
        title = (a.get("title") or "").strip()
        lines.append(
            "INSERT INTO articles(article_id, chapter_id, doc_id, number, title, r2_object_key) "
            f"VALUES('{escape_sql(a['article_id'])}', '{escape_sql(a['chapter_id'])}', "
            f"'{escape_sql(a['doc_id'])}', '{escape_sql(a['number'])}', "
            f"'{escape_sql(title)}', '{escape_sql(a['article_id'] + '.md')}');"
        )

    # 灌 articles_fts 全文索引(包含章节名前缀,便于章节级召回)
    for a in articles:
        text = (a.get("text") or "").replace("\n", " ").strip()
        title = (a.get("title") or "").strip()
        chapter_name = chapter_titles_by_art.get(a["article_id"], "")
        if chapter_name:
            text = f"{chapter_name} {text}"
        lines.append(
            "INSERT INTO articles_fts(article_id, chapter_id, doc_id, number, title, text) "
            f"VALUES('{escape_sql(a['article_id'])}', '{escape_sql(a['chapter_id'])}', "
            f"'{escape_sql(a['doc_id'])}', '{escape_sql(a['number'])}', "
            f"'{escape_sql(title)}', '{escape_sql(text)}');"
        )

    out_path = Path("build/export/seed.sql")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[OK] wrote {len(lines)} SQL statements to {out_path}")
    print(f"     articles: {len(articles)}, chapters: {len(chapters)}, doc: {doc_id}")


if __name__ == "__main__":
    main()
