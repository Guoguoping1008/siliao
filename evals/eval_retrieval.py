"""
检索 recall 评测:读 evals/retrieval.jsonl,跑 FTS5,统计 recall@K。
不依赖 Cloudflare,直接用 Python sqlite3 复刻 Workers 的 FTS5 查询。

跑法:
    python evals/eval_retrieval.py

输出:
    evals/retrieval_report.md
"""
from __future__ import annotations
import json
import re
import sqlite3
from pathlib import Path


ROOT = Path(__file__).parent.parent
SCHEMA = ROOT / "query/worker/schema.sql"
SEED = ROOT / "build/export/seed.sql"
EVAL = ROOT / "evals/retrieval.jsonl"
REPORT = ROOT / "evals/retrieval_report.md"


def build_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.executescript(SEED.read_text(encoding="utf-8"))
    return con


def escape_fts(q: str) -> str:
    return re.sub(r"[\x00-\x1f]", " ", q).strip()[:64]


def search(con: sqlite3.Connection, q: str, top_k: int = 10) -> list[str]:
    cleaned = escape_fts(q)
    if not cleaned:
        return []
    queries = [cleaned]
    # trigram ≥3 字才匹配。2 字中文 query 多搜几个 padding 后缀,合并去重
    if len(cleaned) == 2 and re.fullmatch(r"[\u4e00-\u9fff]+", cleaned):
        for suffix in ("制", "的", "条", "法", "理"):
            queries.append(cleaned + suffix)

    seen: list[str] = []
    seen_set: set[str] = set()
    for query in queries:
        try:
            rows = con.execute(
                "SELECT article_id FROM articles_fts WHERE articles_fts MATCH ?1 ORDER BY rank LIMIT ?2",
                (query, top_k),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        for r in rows:
            if r[0] not in seen_set:
                seen.append(r[0])
                seen_set.add(r[0])
        if len(seen) >= top_k:
            break

    # 兜底:对中文 query 补一次 LIKE,确保 2 字短 query 也能召回
    if len(seen) < top_k and re.search(r"[\u4e00-\u9fff]", q):
        like = f"%{q}%"
        rows = con.execute(
            "SELECT article_id FROM articles_fts WHERE title LIKE ?1 OR text LIKE ?1 LIMIT ?2",
            (like, top_k),
        ).fetchall()
        for r in rows:
            if r[0] not in seen_set:
                seen.append(r[0])
                seen_set.add(r[0])
            if len(seen) >= top_k:
                break
    return seen[:top_k]


def main() -> int:
    con = build_db()
    n_corpus = con.execute("SELECT COUNT(*) FROM articles_fts").fetchone()[0]

    cases = []
    with EVAL.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            cases.append(json.loads(line))

    lines: list[str] = [
        "# Retrieval Recall Report",
        "",
        f"- Corpus: `{n_corpus}` articles (feed-law-2026)",
        f"- Eval cases: `{len(cases)}`",
        "- Tokenizer: FTS5 trigram (中文 ≥3 字子串匹配)",
        "",
        "| # | Query | Expected | Hits@10 | Hit | Recall |",
        "|---|---|---|---|---|---|",
    ]

    total = 0.0
    n_pass = 0
    fails: list[tuple[int, dict, list[str]]] = []
    for i, case in enumerate(cases, 1):
        hits = search(con, case["query"], top_k=10)
        expected = set(case["expect_articles"])
        hit_articles = set(hits[:10])
        rec = len(expected & hit_articles) / len(expected) if expected else 0.0
        total += rec
        passed = rec >= 0.5  # 至少 50% 召回
        if passed:
            n_pass += 1
        else:
            fails.append((i, case, hits))

        marker = "✅" if passed else "❌"
        lines.append(
            f"| {i} | `{case['query']}` | {','.join(sorted(expected))} | "
            f"{','.join(hits[:10]) or '∅'} | {marker} | {rec:.0%} |"
        )

    avg = total / len(cases) if cases else 0.0
    lines.extend([
        "",
        f"## 汇总",
        f"- 平均 recall@10: **{avg:.1%}**",
        f"- 通过用例 (recall ≥ 50%): **{n_pass}/{len(cases)}**",
        "",
    ])

    if fails:
        lines.append("## 失败用例")
        for i, case, hits in fails:
            lines.append(f"- **#{i} `{case['query']}`** — 期望 `{case['expect_articles']}`, 实际 `{hits[:10] or '∅'}`")
            lines.append(f"  - {case['desc']}")

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] report: {REPORT}")
    print(f"     avg recall@10: {avg:.1%} ({n_pass}/{len(cases)} passed)")
    return 0 if n_pass == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
