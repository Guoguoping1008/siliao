"""
RAG 答案忠实度评测。

不依赖真实 LLM API(避免 token 烧钱),直接 mock 答案验证 prompt 校验逻辑。
覆盖:
- 引用 [N] 必须在 hits[N-1] 存在
- "未找到" 路径:evidence 为空时答案必须含 "未找到"
- 答案不应编造 evidence 中不存在的法律条文

跑法:
    python evals/eval_qa_faithfulness.py

输出:
    evals/qa_faithfulness_report.md
"""
from __future__ import annotations
import json
import re
import sqlite3
from pathlib import Path


ROOT = Path(__file__).parent.parent
SCHEMA = ROOT / "query/worker/schema.sql"
SEED = ROOT / "build/export/seed.sql"
EVAL = ROOT / "evals/qa_faithfulness.jsonl"
REPORT = ROOT / "evals/qa_faithfulness_report.md"


def build_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.executescript(SEED.read_text(encoding="utf-8"))
    return con


def load_cases() -> list[dict]:
    cases = []
    with EVAL.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            cases.append(json.loads(line))
    return cases


# 模拟 Worker 的 validateCitations 行为
def validate_citations(answer: str, hits: list[dict]) -> list[dict]:
    re_cite = re.compile(r"\[(\d+)\]")
    nums = sorted({int(m.group(1)) for m in re_cite.finditer(answer)})
    out = []
    for n in nums:
        hit = hits[n - 1] if 0 < n <= len(hits) else None
        if hit:
            out.append({"ref": n, "valid": True, "article_id": hit.get("article_id")})
        else:
            out.append({"ref": n, "valid": False})
    return out


def main() -> int:
    con = build_db()
    corpus = con.execute("SELECT COUNT(*) FROM articles_fts").fetchone()[0]
    cases = load_cases()

    lines: list[str] = [
        "# QA Faithfulness Report",
        "",
        f"- Corpus: `{corpus}` articles",
        f"- Eval cases: `{len(cases)}`",
        "",
        "## 检查项",
        "",
        "1. **引用有效性**:LLM 输出里 `[N]` 引用必须对应检索证据 `[N]`",
        "2. **未找到路径**:检索证据为空时,答案必须明确说明未找到(不编造)",
        "3. **禁止编造**:答案不能引用证据中不存在的法律条文",
        "",
        "| # | 场景 | 输入 | 期望答案特征 | 模拟答案 | 通过 |",
        "|---|---|---|---|---|---|",
    ]

    n_pass = 0
    for i, case in enumerate(cases, 1):
        hits = case.get("mock_hits", [])
        simulated_answer = case["mock_answer"]
        expected_citations = case.get("expected_citations", [])
        expected_pattern = case.get("expected_pattern")

        # 校验引用
        citations = validate_citations(simulated_answer, hits)
        citation_pass = True
        if expected_citations == "must_be_empty":
            citation_pass = len(citations) == 0
        elif expected_citations == "must_be_valid":
            citation_pass = len(citations) > 0 and all(c["valid"] for c in citations)
        elif expected_citations == "must_include_invalid":
            citation_pass = any(not c["valid"] for c in citations)

        # 校验 pattern
        pattern_pass = True
        if expected_pattern:
            pattern_pass = bool(re.search(expected_pattern, simulated_answer))

        passed = citation_pass and pattern_pass
        if passed:
            n_pass += 1
        marker = "✅" if passed else "❌"

        lines.append(
            f"| {i} | {case['scenario']} | `{case['input']}` | "
            f"{expected_pattern or '/'} | "
            f"`{simulated_answer[:50]}{'...' if len(simulated_answer) > 50 else ''}` | {marker} |"
        )

    lines.extend([
        "",
        "## 汇总",
        f"- 通过用例: **{n_pass}/{len(cases)}**",
        f"- 失败用例细节见 evals/qa_faithfulness_report.md",
    ])

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] report: {REPORT}")
    print(f"     pass: {n_pass}/{len(cases)}")
    return 0 if n_pass == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
