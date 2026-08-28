"""
检索 recall 评测:读 evals/retrieval.jsonl,跑 FTS5,统计 recall@K + MRR。

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


def search(con: sqlite3.Connection, q: str, top_k: int = 20) -> list[str]:
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


def mrr(hits: list[str], expected: set[str]) -> float:
    """第一条命中的倒数排名;无命中返回 0"""
    for i, h in enumerate(hits, 1):
        if h in expected:
            return 1.0 / i
    return 0.0


def classify_failure(query: str, hits: list[str], expected: set[str]) -> str:
    """失败根因分类,指导改进方向"""
    q = query.strip()
    if not q or q == "":
        return "空 query(边界用例)"
    if not expected:
        # negative 用例:不应召回,但实际有召回 → 假阳性
        if hits:
            return f"NEGATIVE 假阳性:实际命中 {hits[:3]},期望 0 命中"
        return "NEGATIVE 通过"
    if len(q) <= 2 and re.fullmatch(r"[\u4e00-\u9fff]+", q):
        return f"短 query ({len(q)} 字) padding 召回不全:实际 {hits[:3]}"
    if any(kw in q for kw in ["农业农村部", "主管", "机关"]):
        return "专有名词字面不匹配(需 bge 语义召回)"
    return f"关键词命中但排序错:实际 {hits[:3]},期望 {sorted(expected)[:3]}"


def main() -> int:
    con = build_db()
    n_corpus = con.execute("SELECT COUNT(*) FROM articles_fts").fetchone()[0]

    cases = []
    with EVAL.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            cases.append(json.loads(line))

    pos_cases = [c for c in cases if c["expect_articles"]]
    neg_cases = [c for c in cases if not c["expect_articles"]]

    lines: list[str] = [
        "# Retrieval Recall Report",
        "",
        f"- Corpus: `{n_corpus}` articles (feed-law-2026)",
        f"- Eval cases: `{len(cases)}` (positive: {len(pos_cases)}, negative: {len(neg_cases)})",
        "- Tokenizer: FTS5 trigram + LIKE 兜底",
        "- 2 字中文 query 自动 padding 后缀",
        "",
    ]

    # 跑 search(top_k=20),评估 recall@10 / recall@20 / MRR
    pos_results: list[tuple[int, dict, list[str]]] = []
    total_rec10 = total_rec20 = total_mrr = 0.0
    n_pass10 = 0
    fails: list[tuple[int, dict, list[str], str]] = []
    for i, case in enumerate(pos_cases, 1):
        hits = search(con, case["query"], top_k=20)
        expected = set(case["expect_articles"])
        hit10 = set(hits[:10])
        hit20 = set(hits[:20])
        rec10 = len(expected & hit10) / len(expected) if expected else 0.0
        rec20 = len(expected & hit20) / len(expected) if expected else 0.0
        mrr_val = mrr(hits, expected)
        total_rec10 += rec10
        total_rec20 += rec20
        total_mrr += mrr_val
        passed = rec10 >= 0.5
        if passed:
            n_pass10 += 1
        else:
            fails.append((i, case, hits, classify_failure(case["query"], hits, expected)))
        pos_results.append((i, case, hits))

    avg_rec10 = total_rec10 / len(pos_cases) if pos_cases else 0.0
    avg_rec20 = total_rec20 / len(pos_cases) if pos_cases else 0.0
    avg_mrr = total_mrr / len(pos_cases) if pos_cases else 0.0

    # 跑 negative
    neg_results: list[tuple[int, dict, list[str]]] = []
    n_neg_pass = 0
    neg_fails: list[tuple[int, dict, list[str]]] = []
    for i, case in enumerate(neg_cases, 1):
        hits = search(con, case["query"], top_k=20)
        passed = len(hits) == 0
        if passed:
            n_neg_pass += 1
        else:
            neg_fails.append((i, case, hits))
        neg_results.append((i, case, hits))

    # === 汇总 ===
    lines.extend([
        "## 汇总",
        "",
        "### 正向用例(positive)",
        f"- **recall@10 = {avg_rec10:.1%}** (通过 {n_pass10}/{len(pos_cases)},recall ≥ 50%)",
        f"- **recall@20 = {avg_rec20:.1%}**",
        f"- **MRR = {avg_mrr:.3f}** (第一条命中平均倒数排名)",
        "",
        "### 负向用例(negative)",
        f"- **精度 = {n_neg_pass}/{len(neg_cases)}** (应 0 命中)",
        "",
    ])

    # 决策建议
    if avg_rec10 >= 0.80 and avg_mrr >= 0.70 and n_neg_pass == len(neg_cases):
        verdict = "✅ FTS5 路径足够,推迟接 bge"
    elif avg_rec10 < 0.70:
        verdict = "❌ recall<70%,必须接 bge(触发 t_847af461)"
    elif avg_mrr < 0.50:
        verdict = "⚠️ MRR 偏低,排序逻辑需重写"
    elif n_neg_pass < len(neg_cases):
        verdict = "⚠️ negative 有假阳性,需调 LIKE 兜底阈值"
    else:
        verdict = "🟡 边界合格,建议继续扩大 eval 覆盖"
    lines.append(f"### 决策建议\n\n**{verdict}**\n")

    # === 详细结果:positive ===
    lines.extend([
        "## 正向用例明细",
        "",
        "| # | Query | Expected | Hits@10 | R@10 | MRR |",
        "|---|---|---|---|---|---|",
    ])
    for idx, (i, case, hits) in enumerate(pos_results):
        expected = set(case["expect_articles"])
        hit10 = set(hits[:10])
        rec10 = len(expected & hit10) / len(expected) if expected else 0.0
        mrr_val = mrr(hits, expected)
        marker = "✅" if rec10 >= 0.5 else "❌"
        lines.append(
            f"| {i} | `{case['query']}` | {','.join(sorted(expected))} | "
            f"{','.join(hits[:5]) or '∅'} | {marker} {rec10:.0%} | {mrr_val:.2f} |"
        )

    # === 详细结果:negative ===
    lines.extend([
        "",
        "## 负向用例明细(期望 0 命中)",
        "",
        "| # | Query | Hits | 通过 |",
        "|---|---|---|---|",
    ])
    for i, case, hits in neg_results:
        marker = "✅" if len(hits) == 0 else "❌"
        lines.append(
            f"| {i} | `{case['query']}` | {','.join(hits[:5]) or '∅'} | {marker} |"
        )

    # === 失败根因 ===
    if fails:
        lines.extend([
            "",
            "## 正向失败根因",
            "",
        ])
        # 按根因分组
        by_reason: dict[str, list[tuple[int, dict, list[str]]]] = {}
        for i, case, hits, reason in fails:
            by_reason.setdefault(reason.split(":")[0], []).append((i, case, hits))
        for reason, items in by_reason.items():
            lines.append(f"### {reason} ({len(items)} 例)")
            for i, case, hits in items:
                lines.append(f"- **#{i} `{case['query']}`** — 期望 `{case['expect_articles']}`, 实际 `{hits[:5] or '∅'}`")
                lines.append(f"  - {case['desc']}")
            lines.append("")

    if neg_fails:
        lines.extend([
            "",
            "## 负向假阳性(NEGATIVE 失败)",
            "",
        ])
        for i, case, hits in neg_fails:
            lines.append(f"- **#{i} `{case['query']}`** — 假阳性命中 `{hits[:5]}`")
            lines.append(f"  - {case['desc']}")
        lines.append("")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] report: {REPORT}")
    print(f"     recall@10 = {avg_rec10:.1%}, recall@20 = {avg_rec20:.1%}, MRR = {avg_mrr:.3f}")
    print(f"     positive pass: {n_pass10}/{len(pos_cases)}, negative pass: {n_neg_pass}/{len(neg_cases)}")
    return 0 if (avg_rec10 >= 0.80 and n_neg_pass == len(neg_cases)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
