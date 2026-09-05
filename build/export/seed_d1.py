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
import re
import sys
from pathlib import Path


def escape_sql(s: str) -> str:
    """SQLite 单引号转义"""
    return s.replace("'", "''")


def main():
    """
    支持多个 articles.json 输入, 全部灌到同一份 seed.sql

    用法:
        python build/export/seed_d1.py <doc1>/articles.json [doc1/chapters.json <doc2>/articles.json ...]
    """
    if len(sys.argv) < 2:
        print("[ERR] usage: seed_d1.py <doc/articles.json> [doc/chapters.json ...]")
        sys.exit(1)

    # 把 args 按 doc 分组: arts.json 后跟可选的 chapters.json, 再下一组
    docs: list[tuple[Path, Path | None]] = []
    i = 1
    while i < len(sys.argv):
        arts_path = Path(sys.argv[i])
        chap_path = Path(sys.argv[i + 1]) if (i + 1 < len(sys.argv) and "chapters.json" in sys.argv[i + 1]) else None
        docs.append((arts_path, chap_path))
        i += 2 if chap_path else 1

    lines: list[str] = []

    # 清空 (幂等)
    lines.append("DELETE FROM articles_fts;")
    lines.append("DELETE FROM articles;")
    lines.append("DELETE FROM chapters;")
    lines.append("DELETE FROM documents;")

    total_articles = 0
    total_chapters = 0
    for arts_path, chap_path in docs:
        doc_id = arts_path.parent.name
        raw_articles = json.loads(arts_path.read_text(encoding="utf-8"))
        articles = [{**a, "doc_id": doc_id} for a in raw_articles]

        chapters: list[dict] = []
        if chap_path and chap_path.exists():
            raw_chapters = json.loads(chap_path.read_text(encoding="utf-8"))
            chapters = [
                {**c, "doc_id": doc_id, "sort_order": idx + 1}
                for idx, c in enumerate(raw_chapters)
            ]

        # 章节标题 → article_ids 反向索引
        chapter_titles_by_art: dict[str, str] = {}
        # 主键前缀化: 多 doc 灌库时 chapter_id / article_id 必须唯一
        # 规则: 如果 chapter_id 已经有"字母_xxx"的形式 (即有自定义前缀), 保留原前缀;
        #       如果是 "chNN" / "artNN" 无前缀形式, 加上 doc 前缀避免冲突
        # doc_prefix 用 doc_id 去横线 (避免 3 字符 "fee" 在多个 feed-* doc 间冲突)
        # 安全字符替换: 横线 → 空, 数字保留, 取前 8 字符确保足够唯一
        doc_prefix = doc_id.replace("-", "")[:8]
        cid_prefix_re = re.compile(r"^[a-z]+_")

        def ensure_prefix(raw_id: str) -> str:
            if cid_prefix_re.match(raw_id):
                return raw_id  # 已有前缀 (如 fee_col_xxx), 保留
            return f"{doc_prefix}_{raw_id}"

        for c in chapters:
            c["chapter_id"] = ensure_prefix(c["chapter_id"])
            new_art_ids = []
            for aid in c.get("article_ids", []):
                new_aid = ensure_prefix(aid)
                new_art_ids.append(new_aid)
            c["article_ids"] = new_art_ids
            # 章节名前缀索引: key 是 article_id (灌库后实际值的字符串), 用于每条 article 的 text 注入章节名
            for aid in c["article_ids"]:
                chapter_titles_by_art[aid] = f"{c['number']} {c['title']}"

        for a in articles:
            a["article_id"] = ensure_prefix(a["article_id"])
            # chapter_id 也要前缀化: 多 doc 灌库时 articles.chapter_id 引用 chapters.chapter_id,
            # 没加前缀会导致 FOREIGN KEY 失败
            a["chapter_id"] = ensure_prefix(a["chapter_id"])

        # 灌 document
        lines.append(
            f"INSERT INTO documents(doc_id, title) VALUES('{escape_sql(doc_id)}', '{escape_sql(doc_id)}');"
        )

        # 灌 chapter
        for c in chapters:
            lines.append(
                "INSERT INTO chapters(chapter_id, doc_id, number, title, article_count, sort_order, r2_object_key) "
                f"VALUES('{escape_sql(c['chapter_id'])}', '{escape_sql(c.get('doc_id', doc_id))}', "
                f"'{escape_sql(c['number'])}', '{escape_sql(c['title'])}', {len(c.get('article_ids', []))}, "
                f"{c.get('sort_order', 0)}, '{escape_sql(c['chapter_id'] + '.md')}');"
            )

        # 灌 articles + articles_fts
        for a in articles:
            title = (a.get("title") or "").strip()
            lines.append(
                "INSERT INTO articles(article_id, chapter_id, doc_id, number, title, r2_object_key) "
                f"VALUES('{escape_sql(a['article_id'])}', '{escape_sql(a['chapter_id'])}', "
                f"'{escape_sql(a['doc_id'])}', '{escape_sql(a['number'])}', "
                f"'{escape_sql(title)}', '{escape_sql(a['article_id'] + '.md')}');"
            )

            text = (a.get("text") or "").replace("\n", " ").strip()
            chapter_name = chapter_titles_by_art.get(a["article_id"], "")
            if chapter_name:
                text = f"{chapter_name} {text}"
            lines.append(
                "INSERT INTO articles_fts(article_id, chapter_id, doc_id, number, title, text) "
                f"VALUES('{escape_sql(a['article_id'])}', '{escape_sql(a['chapter_id'])}', "
                f"'{escape_sql(a['doc_id'])}', '{escape_sql(a['number'])}', "
                f"'{escape_sql(title)}', '{escape_sql(text)}');"
            )

        total_articles += len(articles)
        total_chapters += len(chapters)
        print(f"  [doc] {doc_id}: {len(chapters)} chapters · {len(articles)} articles")

    out_path = Path("build/export/seed.sql")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[OK] wrote {len(lines)} SQL statements to {out_path}")
    print(f"     total: {total_chapters} chapters · {total_articles} articles · {len(docs)} docs")


if __name__ == "__main__":
    main()
