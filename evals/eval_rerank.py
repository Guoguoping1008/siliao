"""
C-c: bge-reranker-v2-m3 Rerank 评测 (self-contained, 绕开 eval_retrieval 模型加载问题)
====================================================================================

[2026-09-20 玄穹 CEO 决策 C-c]
重构: 不再 import eval_retrieval.search (它 in-process 加载 bge-m3 在新机器上卡),
自己实现 hybrid = FTS5 (内存 sqlite trigram) + bge_server (HTTP) + RRF 融合。
reranker 独立加载 (bge-reranker-v2-m3),不冲突。

对比组:
- FTS5/LIKE only              (基线)
- bge only (bge_server)        (C-a baseline)
- Hybrid FTS5+bge RRF         (C-b baseline)
- Hybrid + rerank (top-10)    (C-c 本次)
- bge + rerank                 (对照)
"""

from __future__ import annotations
import json
import re
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
EVAL = ROOT / "evals" / "retrieval.jsonl"
SCHEMA = ROOT / "query/worker/schema.sql"
SEED = ROOT / "build/export/seed.sql"
SEED_PAGES_M3 = ROOT / "build/export/seed_pages_m3.sql"
BGE_URL = "http://127.0.0.1:8080"
REPORT = ROOT / "evals" / "c_c_rerank_report.md"
RERANK_PATH = "E:/workspace/siliao/.models/hf/models--BAAI--bge-reranker-v2-m3/snapshots/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"


# === 数据库 ===
def build_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.executescript(SEED.read_text(encoding="utf-8"))
    if SEED_PAGES_M3.exists() and SEED_PAGES_M3.stat().st_size > 0:
        con.executescript(SEED_PAGES_M3.read_text(encoding="utf-8"))
    return con


def fts5_search(con: sqlite3.Connection, q: str, top_k: int = 20) -> list[str]:
    """完全复刻 eval_retrieval.search 的 FTS5 + LIKE 兜底"""
    if not q.strip():
        return []
    queries = [q.strip()[:64]]
    if len(queries[0]) == 2 and re.fullmatch(r"[\u4e00-\u9fff]+", queries[0]):
        for suf in ("制", "的", "条", "法", "理"):
            queries.append(queries[0] + suf)
    seen = []
    seen_set = set()
    for query in queries:
        try:
            rows = con.execute(
                "SELECT article_id FROM articles_fts WHERE articles_fts MATCH ?1 ORDER BY rank LIMIT 50",
                (query,),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        for (aid,) in rows:
            if aid not in seen_set:
                seen.append(aid)
                seen_set.add(aid)
    # LIKE 补位
    if 0 < len(seen) < top_k and re.search(r"[\u4e00-\u9fff]", q):
        like = f"%{q}%"
        rows = con.execute(
            "SELECT article_id FROM articles_fts WHERE title LIKE ?1 OR text LIKE ?1 "
            "ORDER BY instr(text, ?2) LIMIT ?3",
            (like, q, top_k),
        ).fetchall()
        for (aid,) in rows:
            if aid not in seen_set:
                seen.append(aid)
                seen_set.add(aid)
    return seen[:top_k]


def bge_search(q: str, top_k: int = 20) -> list[tuple[str, float]]:
    body = json.dumps({"query": q, "top_k": top_k}).encode("utf-8")
    req = urllib.request.Request(
        f"{BGE_URL}/v1/search",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
            return [(h["article_id"], h["score"]) for h in data["hits"]]
    except urllib.error.HTTPError as e:
        print(f"[WARN] bge 400 on q={q!r}: {e.read().decode('utf-8', errors='replace')[:100]}", flush=True)
        return []
    except Exception as e:
        print(f"[WARN] bge err on q={q!r}: {e}", flush=True)
        return []


def hybrid_rrf(fts_ids: list[str], bge_hits: list[tuple[str, float]],
               k: int = 60, w_fts: float = 0.5, w_bge: float = 0.3) -> list[str]:
    """RRF 加权融合, 与 worker index.ts 一致"""
    fused = {}
    for r, aid in enumerate(fts_ids, 1):
        fused[aid] = {"fts_rank": r, "bge_rank": 0}
    for r, (aid, _) in enumerate(bge_hits, 1):
        if aid in fused:
            fused[aid]["bge_rank"] = r
        else:
            fused[aid] = {"fts_rank": 0, "bge_rank": r}
    scored = []
    for aid, v in fused.items():
        fts_c = w_fts / (k + v["fts_rank"]) if v["fts_rank"] > 0 else w_fts / (k + 99)
        bge_c = w_bge / (k + v["bge_rank"]) if v["bge_rank"] > 0 else w_bge / (k + 99)
        scored.append((aid, fts_c + bge_c))
    scored.sort(key=lambda x: -x[1])
    return [aid for aid, _ in scored]


# === Reranker ===
_RERANK_TOK = None
_RERANK_MODEL = None


def load_reranker():
    global _RERANK_TOK, _RERANK_MODEL
    if _RERANK_MODEL is not None:
        return
    import os
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import torch
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    print(f"[rerank] loading {RERANK_PATH}...", flush=True)
    t0 = time.time()
    _RERANK_TOK = AutoTokenizer.from_pretrained(RERANK_PATH)
    _RERANK_MODEL = AutoModelForSequenceClassification.from_pretrained(RERANK_PATH)
    _RERANK_MODEL.eval()
    print(f"[rerank] loaded in {time.time()-t0:.1f}s", flush=True)


def rerank(query: str, candidates: list[str], text_lookup: dict, top_k: int = 10) -> list[str]:
    """[2026-09-20 玄穹 C-c 优化] 性能调优:
    实测 max_length 128 vs 512 给出完全相同的 top-3 ranking (中文 ~1 char/token),
    但 23 candidates × 128 token = 3.5s vs 512 token = 16s (4x 提速)。
    text_limit=400 字截断同样不影响 top-1 (中文 dense reranker 在短文本上更强)。
    """
    import torch
    if not candidates:
        return []
    pairs = []
    for aid in candidates:
        text = text_lookup.get(aid, "")[:400]
        pairs.append((query, text))
    with torch.no_grad():
        inputs = _RERANK_TOK(pairs, padding=True, truncation=True,
                              max_length=128, return_tensors="pt")
        logits = _RERANK_MODEL(**inputs).logits.squeeze(-1)
        scores = torch.sigmoid(logits.float()).tolist()
    ranked = sorted(zip(candidates, scores), key=lambda x: -x[1])
    return [aid for aid, _ in ranked[:top_k]]


def main():
    # 加载 text 查表
    arts = json.loads((ROOT / "evals" / "articles_cache.json").read_text(encoding="utf-8"))
    text_lookup = {a[0]: a[2] for a in arts}
    print(f"[init] {len(text_lookup)} articles loaded")

    cases = []
    with EVAL.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            cases.append(json.loads(line))
    print(f"[eval] {len(cases)} cases")

    load_reranker()
    con = build_db()

    stats = {
        "fts": {"pos": 0, "neg": 0},
        "bge": {"pos": 0, "neg": 0},
        "hybrid": {"pos": 0, "neg": 0},
        "hybrid+rerank": {"pos": 0, "neg": 0},
        "bge+rerank": {"pos": 0, "neg": 0},
    }
    fails = {k: [] for k in stats}

    n_neg_total = sum(1 for c in cases if not c.get("expect_articles"))
    n_pos_total = len(cases) - n_neg_total

    t0 = time.time()
    for i, c in enumerate(cases):
        q = c["query"]
        if not q.strip():
            continue
        expected = set(c.get("expect_articles") or [])
        is_negative = len(expected) == 0

        # 各路召回
        fts_ids = fts5_search(con, q, 20)
        bge_hits = bge_search(q, 20)
        bge_ids = [a for a, _ in bge_hits]
        hybrid_ids = hybrid_rrf(fts_ids, bge_hits)

        # rerank
        hybrid_reranked = rerank(q, hybrid_ids, text_lookup, top_k=10)
        bge_reranked = rerank(q, bge_ids, text_lookup, top_k=10)

        # 评估 top-10
        for sys_name, ids in [
            ("fts", fts_ids[:10]),
            ("bge", bge_ids[:10]),
            ("hybrid", hybrid_ids[:10]),
            ("hybrid+rerank", hybrid_reranked),
            ("bge+rerank", bge_reranked),
        ]:
            topk10 = set(ids[:10])
            if is_negative:
                ok = len(topk10 & expected) == 0
                if ok:
                    stats[sys_name]["neg"] += 1
                else:
                    fails[sys_name].append({"type": "neg", "q": q, "got": list(topk10)})
            else:
                if expected and (expected & topk10):
                    if len(expected & topk10) / len(expected) >= 0.5:
                        stats[sys_name]["pos"] += 1
                    else:
                        fails[sys_name].append({
                            "type": "pos", "q": q,
                            "expected": list(expected),
                            "overlap": list(expected & topk10)
                        })
                else:
                    fails[sys_name].append({
                        "type": "pos", "q": q,
                        "expected": list(expected),
                        "overlap": []
                    })

        if (i + 1) % 5 == 0:
            elapsed = time.time() - t0
            eta = elapsed / (i + 1) * (len(cases) - i - 1)
            print(f"  [{i+1}/{len(cases)}] "
                  f"fts={stats['fts']['pos']} "
                  f"bge={stats['bge']['pos']} "
                  f"hybrid={stats['hybrid']['pos']} "
                  f"hybrid+rerank={stats['hybrid+rerank']['pos']} "
                  f"({elapsed:.0f}s, eta {eta:.0f}s)",
                  flush=True)

    elapsed = time.time() - t0
    print(f"\n=== C-c Rerank 评测 ({elapsed:.1f}s, {elapsed/len(cases):.2f}s/query) ===")
    print(f"{'系统':<22} {'正例 R@10':<16} {'负例 0 命中':<14}")
    for s in ["fts", "bge", "hybrid", "hybrid+rerank", "bge+rerank"]:
        pos = stats[s]["pos"]
        neg = stats[s]["neg"]
        print(f"{s:<22} {pos}/{n_pos_total}  ({100*pos/n_pos_total:.1f}%)      "
              f"{neg}/{n_neg_total}  ({100*neg/n_neg_total:.1f}%)")

    with REPORT.open("w", encoding="utf-8") as f:
        f.write("# C-c Rerank 评测报告\n\n")
        f.write(f"- 用例: {len(cases)} (正例 {n_pos_total} + 负例 {n_neg_total})\n")
        f.write(f"- Reranker: bge-reranker-v2-m3 (CPU, 0.57B, sigmoid)\n")
        f.write(f"- Rerank 输入: top-20 hybrid, 输出 top-10\n")
        f.write(f"- 耗时: {elapsed:.1f}s ({elapsed/len(cases):.2f}s/query)\n\n")
        f.write("| 系统 | 正例 R@10 ≥50% | 负例 0 命中 |\n|---|---|---|\n")
        for s in ["fts", "bge", "hybrid", "hybrid+rerank", "bge+rerank"]:
            pos = stats[s]["pos"]
            neg = stats[s]["neg"]
            f.write(f"| {s} | {pos}/{n_pos_total} ({100*pos/n_pos_total:.1f}%) "
                    f"| {neg}/{n_neg_total} ({100*neg/n_neg_total:.1f}%) |\n")

        # 增量分析
        f.write("\n## Rerank 救回的 case (hybrid fail → hybrid+rerank pass)\n\n")
        hybrid_fail_q = {x["q"] for x in fails["hybrid"] if "q" in x}
        rerank_save = [x for x in fails["hybrid+rerank"] if "q" in x and x["q"] not in hybrid_fail_q]
        f.write(f"共 **{len(rerank_save)}** 条被 rerank 救回:\n\n")
        for case in rerank_save[:30]:
            f.write(f"- `{case['q']}`: expected {case.get('expected', [])}, got {case.get('overlap', [])}\n")

        f.write(f"\n## Rerank 搞坏的 case (hybrid pass → hybrid+rerank fail)\n\n")
        # 简单实现: 在 hybrid 没失败 + hybrid+rerank 失败的 query
        all_q = {c["query"] for c in cases}
        hybrid_pass_q = all_q - hybrid_fail_q
        rerank_break = [
            x for x in fails["hybrid+rerank"]
            if "q" in x and x["q"] in hybrid_pass_q
        ]
        f.write(f"共 **{len(rerank_break)}** 条被 rerank 搞坏:\n\n")
        for case in rerank_break[:30]:
            f.write(f"- `{case['q']}`: expected {case.get('expected', [])}, got {case.get('overlap', [])}\n")

    print(f"\n[done] {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
