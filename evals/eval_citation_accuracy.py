#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
引用准确率评测 —— 把方案文档一期的验收标准变成**可度量的门禁**
================================================================

## 为什么做这个

《饲料法规智能体架构方案》第八章写的一期验收标准是:

    「抽样问答引用准确率 ≥ 95%」

而 ADR-005 指出: **这个指标目前测不了** ——
现有 eval 只有 retrieval 指标(recall@10 / MRR)与 faithfulness 指标,
没有「引用准确率」这个口径。方案文档里躺着一个**无法验证的验收标准**,
等于没有标准。

本脚本补上这个口径:

    引用准确率 = 答案中 valid:true 的引用数 / 答案中全部引用数

`citation-validator.service.ts` 里已经能算出来(`hasOnlyValidCitations`),
本脚本做的是**端到端实测**: 打真实 API → 真实 LLM 生成 → 真实检索 → 校验。

## 与已有 eval 的区别

| eval | 测什么 | 用真实 LLM? |
|---|---|---|
| `eval_minimax.py` | 检索质量(recall/MRR) | 否 |
| `eval_qa_faithfulness.py` | **校验器逻辑**是否正确 | 否(答案手写 mock) |
| **本脚本** | **真实 LLM 产出的引用**是否有效 | **是** |

`eval_qa_faithfulness.py` 测的是「如果答案长这样, 校验器判得对不对」——
它保证校验器没坏。本脚本测的是「LLM 实际生成的答案, 引用到底准不准」——
它保证**产品**没坏。两者不可互相替代。

## 跑法

    # 实测(打真实 API, 会消耗 LLM token)
    python evals/eval_citation_accuracy.py --live

    # 用缓存基线复算(不调 API, 不烧 token) —— CI 默认走这条
    python evals/eval_citation_accuracy.py

    # 更新基线缓存(改了 prompt / 换了模型后跑)
    python evals/eval_citation_accuracy.py --live --update-baseline

## 输出

    evals/citation_accuracy_report.md    —— 报告
    evals/citation_accuracy_baseline.json —— 基线缓存(答案 + 引用, 供离线复算)
    evals/citation_accuracy_report.jsonl —— 逐条明细

## CI 门禁

    引用准确率 < 95% → CI 红
    引用数量为 0 的用例占比 > 20% → CI 红(LLM 开始不引用了 = 退化)

⚠️ **不烧 token**: CI 默认用基线缓存复算。只有手动跑 `--live` 才调 API。
   基线缓存由 `--live --update-baseline` 生成, 随仓库提交。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

BASELINE = ROOT / "evals" / "citation_accuracy_baseline.json"
REPORT = ROOT / "evals" / "citation_accuracy_report.md"
DETAIL = ROOT / "evals" / "citation_accuracy_report.jsonl"

# ── 验收阈值(方案文档第八章一期验收标准) ──
THRESHOLD_CITATION_ACCURACY = 95.0
# ── 无引用用例占比上限 ──
#    引用数量为 0 意味着 LLM 给了「无依据」的回答 —— 这在合规场景是**失败**,
#    不是「没关系」。占比过高说明 prompt 的引用要求退化了。
THRESHOLD_NO_CITATION_RATIO = 20.0

# ── 生产 API ──
API_BASE = os.environ.get("SILIAGO_API_BASE", "https://siliao-web.pages.dev/api")
API_TIMEOUT = int(os.environ.get("SILIAGO_API_TIMEOUT", "90"))

# ── 评测问题集 ──
# ⚠️ **期望列表从真实数据生成, 不手写猜 article_id** ——
#    手写猜错会系统性低估, 看起来像「产品坏了」其实是评测本身错
#    (见 skill qingmang-rag-impl 记录的坑)。
#    这里只写**问题**, 期望由「检索是否命中 + 引用是否有效」自动判定。
QUESTIONS: list[dict[str, Any]] = [
    {"q": "饲料添加剂新品种审定需要提交哪些材料？", "tag": "审定"},
    {"q": "未取得饲料添加剂生产许可证会怎么处罚？", "tag": "处罚"},
    {"q": "饲料标签必须标注哪些内容？", "tag": "标签"},
    {"q": "维生素C在猪饲料中的使用量上限是多少？", "tag": "限量"},
    {"q": "饲料和饲料添加剂管理办法适用于哪些动物？", "tag": "适用范围"},
    {"q": "生产许可证的有效期是多久？", "tag": "有效期"},
    {"q": "哪些行为属于违规使用饲料添加剂？", "tag": "禁用"},
    {"q": "饲料原料目录包含哪些类别？", "tag": "目录"},
    {"q": "进口饲料和饲料添加剂需要办理什么登记？", "tag": "进口"},
    {"q": "饲料添加剂生产许可证的申请条件是什么？", "tag": "许可证"},
    {"q": "兽药和饲料添加剂在标签标识上有什么要求？", "tag": "兽药标签"},
    {"q": "饲料质量检验的判定依据是什么？", "tag": "检验"},
    {"q": "什么情况下需要重新申请饲料添加剂批准文号？", "tag": "文号"},
    {"q": "饲料经营企业有哪些义务？", "tag": "经营"},
    {"q": "转基因饲料如何管理？", "tag": "转基因"},
]


def call_api(question: str) -> dict[str, Any]:
    """打生产 QA API(非流式), 返回解析后的 JSON。

    ⚠️ **必须带浏览器样 User-Agent** —— 实测不带会被 Cloudflare 拦:
       `HTTP 403: error code: 1010`(浏览器完整性检查)。
       urllib 默认 UA `Python-urllib/3.11` 会被直接拒。
    """
    url = f"{API_BASE}/qa"
    body = json.dumps({"q": question}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    req.add_header(
        "User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    )
    req.add_header("Origin", API_BASE.rsplit("/api", 1)[0])
    req.add_header("Referer", API_BASE.rsplit("/api", 1)[0] + "/")
    try:
        with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        raise RuntimeError(f"HTTP {e.code}: {detail[:300]}") from e
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"请求失败: {e}") from e


def score_one(result: dict[str, Any]) -> dict[str, Any]:
    """算单条用例的引用准确率。

    口径: valid:true 的引用数 / 全部引用数。
    ⚠️ 「全部引用数为 0」单独记 —— 那不是 0% 准确率, 是「没有依据」。
    """
    citations = result.get("citations") or []
    total = len(citations)
    valid = sum(1 for c in citations if c.get("valid"))
    answer = result.get("answer") or ""

    # 交叉核对: 答案里的 [N] 标记数 vs citations 数
    # 两者不等说明校验器与答案不同步 —— 那是 Worker 侧的问题
    import re

    refs_in_answer = sorted({int(m) for m in re.findall(r"\[(\d+)\]", answer)})

    return {
        "total_citations": total,
        "valid_citations": valid,
        "invalid_citations": total - valid,
        "accuracy": (valid / total * 100.0) if total else None,
        "refs_in_answer": refs_in_answer,
        "refs_synced": len(refs_in_answer) == total,
        "has_answer": bool(answer.strip()),
        "hit_articles": sorted({c.get("article_id") for c in citations if c.get("article_id")}),
        "invalid_refs": [c.get("ref") for c in citations if not c.get("valid")],
    }


def build_live() -> list[dict[str, Any]]:
    """实跑生产 API, 生成基线。"""
    rows = []
    for i, q in enumerate(QUESTIONS, 1):
        item = dict(q)
        print(f"[{i}/{len(QUESTIONS)}] {q['q']}", flush=True)
        try:
            result = call_api(q["q"])
        except RuntimeError as e:
            print(f"    ⚠️ 失败: {e}", flush=True)
            item["error"] = str(e)
            rows.append(item)
            continue
        item["answer"] = result.get("answer") or ""
        item["citations"] = result.get("citations") or []
        item["score"] = score_one(result)
        rows.append(item)
        # 轻微限速 —— 别把生产 API 打爆
        time.sleep(0.6)
    return rows


def load_baseline() -> list[dict[str, Any]]:
    if not BASELINE.exists():
        return []
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    return data.get("cases", [])


def write_report(rows: list[dict[str, Any]], mode: str) -> None:
    ok_rows = [r for r in rows if r.get("score") and not r.get("error")]

    # ── 汇总 ──
    total_cit = sum(r["score"]["total_citations"] for r in ok_rows)
    valid_cit = sum(r["score"]["valid_citations"] for r in ok_rows)
    no_cit = [r for r in ok_rows if r["score"]["total_citations"] == 0]
    out_of_sync = [r for r in ok_rows if not r["score"]["refs_synced"]]
    errors = [r for r in rows if r.get("error")]

    accuracy = (valid_cit / total_cit * 100.0) if total_cit else None
    no_cit_ratio = (len(no_cit) / len(ok_rows) * 100.0) if ok_rows else 0.0

    lines = []
    lines.append("# 引用准确率评测报告")
    lines.append("")
    lines.append(f"- 模式: **{mode}**" + ("(真实 API + 真实 LLM)" if mode == "live" else "(基线缓存离线复算)"))
    lines.append(f"- 用例数: **{len(rows)}**（成功 {len(ok_rows)}，失败 {len(errors)}）")
    lines.append(f"- 引用总数: **{total_cit}**（有效 {valid_cit}，无效 {total_cit - valid_cit}）")
    lines.append("")
    lines.append("## 判定")
    lines.append("")
    if accuracy is None:
        lines.append("- ❌ **无法计算引用准确率** —— 全部用例都没有产生引用")
    else:
        mark = "✅" if accuracy >= THRESHOLD_CITATION_ACCURACY else "❌"
        lines.append(f"- {mark} **引用准确率 = {accuracy:.1f}%**"
                     f"（阈值 {THRESHOLD_CITATION_ACCURACY}%，方案文档一期验收标准）")
    mark_nc = "✅" if no_cit_ratio <= THRESHOLD_NO_CITATION_RATIO else "❌"
    lines.append(f"- {mark_nc} **无引用用例占比 = {no_cit_ratio:.1f}%**"
                 f"（阈值 ≤{THRESHOLD_NO_CITATION_RATIO}%）")
    mark_sync = "✅" if not out_of_sync else "❌"
    lines.append(f"- {mark_sync} **答案引用标记与 citations 同步 = {len(ok_rows) - len(out_of_sync)}/{len(ok_rows)}**")
    lines.append("")
    lines.append("## 逐条明细")
    lines.append("")
    lines.append("| # | 问题 | 标签 | 引用数 | 有效 | 准确率 | 无效引用号 | 命中条文数 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        if r.get("error"):
            lines.append(f"| {i} | {r['q']} | {r.get('tag','')} | — | — | 请求失败 | — | — |")
            continue
        s = r["score"]
        acc = f"{s['accuracy']:.0f}%" if s["accuracy"] is not None else "—"
        invalid = ", ".join(str(x) for x in s["invalid_refs"]) or "—"
        lines.append(
            f"| {i} | {r['q']} | {r.get('tag','')} | {s['total_citations']} | "
            f"{s['valid_citations']} | {acc} | {invalid} | {len(s['hit_articles'])} |"
        )
    lines.append("")
    lines.append("## 口径说明")
    lines.append("")
    lines.append("```")
    lines.append("引用准确率 = 答案中 valid:true 的引用数 / 答案中全部引用数")
    lines.append("```")
    lines.append("")
    lines.append("- `valid` 由 `citation-validator.service.ts` 判定：引用号 N 必须对应"
                 "检索证据的第 N 条；N 超出证据范围 → `valid: false`（LLM 编造）")
    lines.append("- **无引用**不计入准确率分母 —— 它是「没有依据」，单独用占比阈值管")
    lines.append("- 「答案引用标记与 citations 同步」查的是校验器与答案是否脱节"
                 "（答案里写了 `[3]` 但 citations 里没有 → Worker 侧问题）")
    lines.append("")

    REPORT.write_text("\n".join(lines), encoding="utf-8")

    # 逐条明细(jsonl)
    with DETAIL.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print()
    print(f"引用准确率   : {accuracy:.1f}%" if accuracy is not None else "引用准确率   : 无法计算")
    print(f"无引用占比   : {no_cit_ratio:.1f}%")
    print(f"报告 → {REPORT}")


def check_gate(rows: list[dict[str, Any]]) -> int:
    """CI 门禁。返回进程退出码。"""
    ok_rows = [r for r in rows if r.get("score") and not r.get("error")]
    if not ok_rows:
        print("❌ 没有可用用例 —— 评测失败")
        return 1

    total_cit = sum(r["score"]["total_citations"] for r in ok_rows)
    valid_cit = sum(r["score"]["valid_citations"] for r in ok_rows)
    no_cit = [r for r in ok_rows if r["score"]["total_citations"] == 0]
    out_of_sync = [r for r in ok_rows if not r["score"]["refs_synced"]]

    failed = False

    if total_cit == 0:
        print(f"❌ 引用准确率无法计算 —— 全部 {len(ok_rows)} 个用例都没产生引用")
        failed = True
    else:
        acc = valid_cit / total_cit * 100.0
        if acc < THRESHOLD_CITATION_ACCURACY:
            print(f"❌ 引用准确率 {acc:.1f}% < {THRESHOLD_CITATION_ACCURACY}% —— 检索/生成退化")
            failed = True
        else:
            print(f"✅ 引用准确率 {acc:.1f}% ≥ {THRESHOLD_CITATION_ACCURACY}%")

    ratio = len(no_cit) / len(ok_rows) * 100.0
    if ratio > THRESHOLD_NO_CITATION_RATIO:
        print(f"❌ 无引用用例占比 {ratio:.1f}% > {THRESHOLD_NO_CITATION_RATIO}% —— prompt 引用要求退化")
        failed = True
    else:
        print(f"✅ 无引用用例占比 {ratio:.1f}% ≤ {THRESHOLD_NO_CITATION_RATIO}%")

    if out_of_sync:
        print(f"❌ {len(out_of_sync)} 个用例的答案引用标记与 citations 不同步 —— Worker 校验器问题")
        for r in out_of_sync[:5]:
            print(f"    {r['q']} → answer refs={r['score']['refs_in_answer']} "
                  f"citations={r['score']['total_citations']}")
        failed = True
    else:
        print("✅ 答案引用标记与 citations 全部同步")

    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="实跑生产 API(消耗 LLM token)")
    ap.add_argument("--update-baseline", action="store_true", help="实跑并更新基线缓存")
    ap.add_argument("--no-gate", action="store_true", help="只出报告, 不做门禁判定")
    args = ap.parse_args()

    if args.live or args.update_baseline:
        print(f"[live] 打生产 API: {API_BASE}/qa")
        rows = build_live()
        if args.update_baseline:
            payload = {
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "api_base": API_BASE,
                "cases": rows,
            }
            BASELINE.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"[baseline] → {BASELINE}")
        write_report(rows, "live")
        return 0 if args.no_gate else check_gate(rows)

    # ── 离线复算 ──
    rows = load_baseline()
    if not rows:
        print(f"❌ 没有基线缓存: {BASELINE}")
        print("   先跑: python evals/eval_citation_accuracy.py --live --update-baseline")
        return 1
    print(f"[offline] 用基线缓存复算 {len(rows)} 个用例（不调 API，不烧 token）")
    write_report(rows, "offline")
    return 0 if args.no_gate else check_gate(rows)


if __name__ == "__main__":
    sys.exit(main())
