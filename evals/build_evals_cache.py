"""
为 eval_retrieval.py 准备 TF-IDF cache (G 计划: TF-IDF 召回的预处理)

依赖: sqlite3 + schema.sql + seed.sql + seed_pages_m3.sql (跟 eval_retrieval.py 一致)

输出:
  evals/articles_cache.json  抽出所有 article 的 (article_id, doc_id, text)
  evals/tfidf_cache.json     TF-IDF 词表 + idf + 649 个 article 的 sparse tfidf vec

跑法:
    python evals/build_evals_cache.py
    # 0.4-0.6s 生成完毕, eval_retrieval.py 检测到 cache 后自动启用 hybrid 召回
"""
from __future__ import annotations
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCHEMA = ROOT / "query/worker/schema.sql"
SEED = ROOT / "build/export/seed.sql"
SEED_PAGES_M3 = ROOT / "build/export/seed_pages_m3.sql"
OUT_ARTICLES = ROOT / "evals/articles_cache.json"
OUT_TFIDF = ROOT / "evals/tfidf_cache.json"


def tokenize_zh(text: str) -> list[str]:
    """bi-gram 中文切词, 跳过空白和标点"""
    if not text:
        return []
    text = re.sub(
        r"[\s\u3000\u3001\u3002\uff0c\uff01\uff1f\uff1b\uff1a\u201c\u201d\u2018\u2019\uff08\uff09\u300a\u300b\uff3b\uff3d]+",
        "",
        text,
    )
    chars = list(text)
    grams: set[str] = set()
    for i in range(len(chars) - 1):
        g = chars[i] + chars[i + 1]
        if re.match(r"[\u4e00-\u9fff]", g):
            grams.add(g)
    return list(grams)


def extract_articles() -> list[tuple[str, str, str]]:
    """从 sqlite 抽 articles 表"""
    import sqlite3
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.executescript(SEED.read_text(encoding="utf-8"))
    # ⚠️ **不要**加载 seed_pages_m3.sql。
    #    它是 2023 版旧语料(feed-law-collection-2023-full)的灌库脚本,
    #    已经作废 —— 生产 D1 和生产 bge 语料里都没有它
    #    (实测:D1 legacy articles = 0,bge cache legacy docs = 0)。
    #    加载它会凭空多出 515 条幽灵条文(3493 vs 真实的 3164),
    #    灌回生产就是**污染**(这些条文在 D1 里根本不存在,检索会返回空).
    #
    # ⚠️ 读 **articles** 表,不是 articles_fts。
    #    articles_fts 少 186 条(封面 000封面 + 目录 001目录 被刻意排除)。
    #    但 articles_cache.json 是 bge_server 的 **excerpt 来源**
    #    (bge_server.py:147 `_corpus_text = {aid: meta[1] ...}`),
    #    必须覆盖 bge_m3_cache.json 里的每一条,否则语义层召回返回空 excerpt。
    #    生产 cache 3145 条 = 全部 articles(含封面 5 + 目录 181)—— 照此对齐。
    rows = con.execute(
        "SELECT article_id, doc_id, body FROM articles ORDER BY article_id"
    ).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def main() -> int:
    articles = extract_articles()
    print(f"[scan] {len(articles)} articles")

    # articles cache
    OUT_ARTICLES.write_text(
        json.dumps(articles, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[write] {OUT_ARTICLES} ({OUT_ARTICLES.stat().st_size/1024/1024:.2f} MB)")

    # tokenize + DF
    tokenized = []
    df: Counter = Counter()
    tf_list = []
    for aid, doc_id, text in articles:
        toks = tokenize_zh(text)
        tokenized.append((aid, doc_id, toks))
        tf = Counter(toks)
        tf_list.append(tf)
        for t in set(toks):
            df[t] += 1

    N = len(articles)
    idf = {t: math.log(N / (1 + c)) for t, c in df.items()}

    # TF-IDF 稀疏向量
    def tfidf_vec(tf: Counter) -> dict[str, float]:
        total = sum(tf.values()) or 1
        return {t: (tf[t] / total) * idf.get(t, 0) for t in tf}

    vecs = [tfidf_vec(tf) for tf in tf_list]
    print(f"[tfidf] vocab={len(df)}, vecs={len(vecs)}")

    OUT_TFIDF.write_text(
        json.dumps(
            {
                "tokenized": [(aid, doc_id, toks) for aid, doc_id, toks in tokenized],
                "df": dict(df),
                "idf": idf,
                "vecs": vecs,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"[write] {OUT_TFIDF} ({OUT_TFIDF.stat().st_size/1024/1024:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
