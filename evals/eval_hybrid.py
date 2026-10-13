"""
C-b 端到端 hybrid 评测 (基于 eval_retrieval.py 的官方 search)
============================================================

[2026-09-20 玄穹 CEO 决策 C-b 验收]

发现 eval_retrieval.py 的 search() 已经是 FTS5 + TF-IDF + bge-m3 + LIKE
四路 hybrid (默认 SEARCH_WEIGHTS = (0.5, 0.2, 0.3), plus LIKE 0.3 兜底)。

本脚本做对比验证:
1. 单 bge-m3 (top-k=20) — 仅走 /v1/search
2. eval_retrieval.search() — 官方四路 hybrid
3. 报告 eval_retrieval.search() 的召回,与之前 C-a 报告对照
"""

from __future__ import annotations
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
EVAL = ROOT / "evals" / "retrieval.jsonl"
BGE_URL = "http://127.0.0.1:8080"
REPORT = ROOT / "evals" / "c_b_hybrid_report.md"

sys.path.insert(0, str(ROOT / "evals"))
from eval_retrieval import build_db, search as official_search  # noqa: E402


def bge_only(q: str, top_k: int = 20) -> list[str]:
    body = json.dumps({"query": q, "top_k": top_k}).encode("utf-8")
    req = urllib.request.Request(
        f"{BGE_URL}/v1/search",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
            return [h["article_id"] for h in data["hits"]]
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        print(f"[WARN] bge 400 on q={q!r}: {body_text[:200]}", flush=True)
        return []


def main():
    cases = []
    with EVAL.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            cases.append(json.loads(line))

    print(f"[eval] {len(cases)} cases")
    con = build_db()

    pos_pass = {"bge": 0, "hybrid": 0}
    neg_pass = {"bge": 0, "hybrid": 0}
    fail_details = {"bge": [], "hybrid": []}

    t0 = time.time()
    for i, c in enumerate(cases):
        q = c["query"]
        # retrieval.jsonl 用 expect_articles,不是 expected;无字段就是负向
        expected = set(c.get("expect_articles") or [])
        is_negative = len(expected) == 0

        bge_ids = bge_only(q, 20)
        # official_search() 走 FTS5 + TF-IDF + bge + LIKE 四路
        # bge server 必须在线 (bge_m3_cache.json 已落盘)
        hybrid_ids = official_search(con, q, 20)

        for sys_name, ids in [("bge", bge_ids), ("hybrid", hybrid_ids)]:
            topk10 = set(ids[:10])
            if is_negative:
                ok = len(topk10 & expected) == 0
                if ok:
                    neg_pass[sys_name] += 1
                else:
                    fail_details[sys_name].append({
                        "q": q, "expected": list(expected), "got": list(topk10)
                    })
            else:
                if expected and (expected & topk10):
                    if len(expected & topk10) / len(expected) >= 0.5:
                        pos_pass[sys_name] += 1
                    else:
                        fail_details[sys_name].append({
                            "q": q, "expected": list(expected),
                            "got": list(topk10),
                            "overlap": list(expected & topk10)
                        })

        if (i + 1) % 20 == 0:
            print(f"  [{i+1}/{len(cases)}] pos: bge={pos_pass['bge']}, hybrid={pos_pass['hybrid']}, "
                  f"neg: bge={neg_pass['bge']}, hybrid={neg_pass['hybrid']}",
                  flush=True)

    elapsed = time.time() - t0
    n = len(cases)
    # 负向判定: expect_articles 为空 → desc 通常含 "negative"
    n_neg = sum(1 for c in cases if not c.get("expect_articles"))
    n_pos = n - n_neg

    print(f"\n=== C-b hybrid 评测 ({elapsed:.1f}s) ===")
    print(f"{'系统':<10} {'正例 R@10 ≥50%':<20} {'负例 0 命中':<14}")
    for s in ["bge", "hybrid"]:
        print(f"{s:<10} {pos_pass[s]}/{n_pos}  ({100*pos_pass[s]/n_pos:.1f}%)      "
              f"{neg_pass[s]}/{n_neg}  ({100*neg_pass[s]/n_neg:.1f}%)")

    with REPORT.open("w", encoding="utf-8") as f:
        f.write("# C-b Hybrid 召回评测报告\n\n")
        f.write(f"- 用例总数: {n} (正例 {n_pos} + 负例 {n_neg})\n")
        f.write(f"- bge-m3 server: `{BGE_URL}`\n")
        f.write(f"- 对比: 单 bge /v1/search vs eval_retrieval.search() "
                f"(FTS5 trigram + TF-IDF + bge + LIKE 四路)\n")
        f.write(f"- 耗时: {elapsed:.1f}s\n\n")
        f.write("| 系统 | 正例 R@10 ≥50% | 负例 0 命中 |\n|---|---|---|\n")
        for s in ["bge", "hybrid"]:
            f.write(f"| {s} | {pos_pass[s]}/{n_pos} ({100*pos_pass[s]/n_pos:.1f}%) "
                    f"| {neg_pass[s]}/{n_neg} ({100*neg_pass[s]/n_neg:.1f}%) |\n")

        f.write("\n## Hybrid 失败 case\n\n")
        for case in fail_details["hybrid"][:30]:
            f.write(f"- `{case['q']}`: expected {case['expected']}, got {case.get('overlap', list(case['got']))}\n")

    print(f"\n[done] {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
