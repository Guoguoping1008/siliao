#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
C1 · 人工校核清单生成 —— 把 37 条规则铺成可逐条核对的表

为什么需要这个脚本
------------------
`review_status` 闸门要求**人工逐条校核** 37 条规则后才能提升为 reviewed。
但「人工校核」不能靠人对着 JSON 一条条看 —— 上下文(原文摘录)散在
source_excerpt 里, 看不出这条规则到底对不对。

这个脚本把每条规则铺成一行, 带:
  · 规则本身(物质/动物/阶段/上下限/单位)
  · **原文摘录**(source_excerpt) —— 校核时对照的依据
  · **溯源**(source_article_id) —— 能回原文核对
  · **自动风险标记** —— 把「机器自己都觉得可疑」的挑出来优先看

输出
----
  build/export/review_checklist.csv   —— 人工校核用(Excel 可直接打开)
  build/export/review_checklist.md    —— 同内容, Markdown 表格

用法
----
  python build/export/make_review_checklist.py
"""

import csv
import io
import json
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(REPO, "build", "export")

RULES_JSON = os.path.join(OUT_DIR, "compliance_rules.json")
CATALOG_JSON = os.path.join(OUT_DIR, "substance_catalog.json")


def _strip_abbrev(s: str) -> str:
    """去掉英文名末尾的缩写: 「… bisulfite (MPB)」→「… bisulfite」。"""
    return re.sub(r"\s*\([A-Za-z]{1,6}\)\s*$", "", s or "").strip()

# ─────────────────────────────────────────────────────────────
# 自动风险规则 —— 每条都对应一个**实测见过的问题**
# ─────────────────────────────────────────────────────────────


def flag_rules(rule, catalog_names, catalog_by_en=None):
    """给一条规则打风险标记。返回 (标记列表, 是否需要重点看)。"""
    flags = []

    sub = rule.get("substance") or ""
    species = rule.get("species") or ""
    lo = rule.get("min_value")
    hi = rule.get("max_value")
    unit = rule.get("unit") or ""
    excerpt = rule.get("source_excerpt") or ""

    # ① 上下限相等 —— 可能是 OCR 把「>5000」写成了「5000~5000」, 也可能是真单值
    if lo is not None and hi is not None and lo == hi:
        flags.append("上下限相等(单值? 需确认是区间还是单点)")

    # ② 下限为 0 —— 多半是「0~X」形式的推荐量, 不是硬上限
    if lo == 0:
        flags.append("下限为 0(可能是推荐量而非限量)")

    # ③ 单位可疑 —— 质量指标单位不该出现在限量规则里
    if unit in ("%", "％"):
        flags.append("单位是 %(疑似质量指标, 非限量)")

    # ④ 摘录里出现「质量指标」类词 —— 说明抽到了错误的列
    if re.search(r"(粗蛋白|粗纤维|粗脂肪|水分含量|灰分|含量规格)", excerpt):
        flags.append("摘录含质量指标词(可能抽错列)")

    # ⑤ 摘录里出现组合约束 —— 该行不该产生单体规则
    if re.search(r"(同时使用|配合使用|总量不得超过|不得同时)", excerpt):
        flags.append("摘录含组合约束(不应作为单体规则)")

    # ⑥ 物质名不在目录里 —— 「是否在目录内」判定会失败
    # ⚠️ 判据: 先比中文名, 再比**英文名** ——
    #    目录与安全使用规范对同一物质的中文写法可能差一两个修饰词
    #    (「亚硫酸甲萘醌」vs「亚硫酸氢钠甲萘醌」), 英文名才是唯一键。
    if catalog_names and sub not in catalog_names:
        alias = _strip_abbrev(rule.get("substance_alias") or "").lower()
        linked = bool(alias) and alias in (catalog_by_en or {})
        if not linked:
            flags.append("物质不在目录(需人工确认)")

    # ⑦ 物质名含拉丁字母 —— 可能是 OCR 掉的英文名(应换成中文通用名)
    if re.search(r"[A-Za-z]{3,}", sub) and not re.search(r"[一-鿿]", sub):
        flags.append("物质名是纯拉丁名(疑似 OCR 掉的英文名)")

    # ⑧ 动物种类是泛称 —— 判定时覆盖面过大
    if species in ("其他", "其它", "所有动物", "全部"):
        flags.append("动物种类是泛称")

    # ⑨ 摘录里出现该动物但规则里没有 —— 可能漏抽
    if excerpt and species and species not in excerpt:
        flags.append("摘录里没有该动物(可能抽错行)")

    # ⑩ 单位大小写/格式不统一
    if unit and unit != unit.strip():
        flags.append("单位首尾有空格")

    return flags


def main():
    rules_doc = json.load(io.open(RULES_JSON, encoding="utf-8"))
    rules = rules_doc["rules"]
    version = rules_doc.get("rule_set_version", "v2026.10")

    cat_doc = json.load(io.open(CATALOG_JSON, encoding="utf-8"))
    catalog_names = {s["name_cn"] for s in cat_doc["substances"]}
    catalog_by_en = {}
    for s in cat_doc["substances"]:
        if s.get("name_en"):
            catalog_by_en.setdefault(_strip_abbrev(s["name_en"]).lower(), s["name_cn"])

    rows = []
    for i, r in enumerate(rules, 1):
        flags = flag_rules(r, catalog_names, catalog_by_en)
        rows.append({
            "no": i,
            "rule_id": f"r_{i:03d}",
            "substance": r.get("substance", ""),
            "species": r.get("species", ""),
            "stage": r.get("stage", ""),
            "min": r.get("min_value", ""),
            "max": r.get("max_value", ""),
            "unit": r.get("unit", ""),
            "flags": "; ".join(flags) if flags else "",
            "n_flags": len(flags),
            "decision": "",          # ← 人工填: ok / fix / reject
            "fixed_substance": "",
            "fixed_species": "",
            "fixed_min": "",
            "fixed_max": "",
            "fixed_unit": "",
            "note": "",
            "source_article_id": r.get("source_article_id", ""),
            "source_excerpt": (r.get("source_excerpt") or "").replace("\r\n", " ").replace("\n", " "),
        })

    # ── CSV ──
    cols = list(rows[0].keys())
    csv_path = os.path.join(OUT_DIR, "review_checklist.csv")
    with io.open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"[OK] CSV → {csv_path}")

    # ── Markdown(按物质分组, 附原文摘录) ──
    md_path = os.path.join(OUT_DIR, "review_checklist.md")
    by_sub = {}
    for row in rows:
        by_sub.setdefault(row["substance"], []).append(row)

    lines = []
    lines.append(f"# C1 · 合规规则人工校核清单 · {version}")
    lines.append("")
    lines.append(f"- **规则总数**: {len(rows)}")
    flagged = [r for r in rows if r["n_flags"] > 0]
    lines.append(f"- **自动标记待重点看**: {len(flagged)} 条")
    lines.append(f"- **物质种类**: {len(by_sub)}")
    lines.append("")
    lines.append("> **校核方法**: 逐条核对「规则值」与「原文摘录」是否一致。")
    lines.append("> 一致 → decision 填 `ok`;")
    lines.append("> 值错了 → 填 `fix` 并在 fixed_* 列填正确值;")
    lines.append("> 这条不该存在 → 填 `reject`。")
    lines.append(">")
    lines.append("> ⚠️ **必须全部校核完**才能把 `review_status` 从 `pending` 提升为 `reviewed`。")
    lines.append("")
    lines.append("---")
    lines.append("")

    for sub, subrows in by_sub.items():
        lines.append(f"## {sub}")
        lines.append("")
        for row in subrows:
            mark = f"⚠️ **{row['n_flags']} 项待确认**" if row["n_flags"] else "—"
            lines.append(f"### #{row['no']} · {row['species']} · "
                         f"{row['min']}~{row['max']} {row['unit']}")
            lines.append("")
            lines.append(f"- **溯源**: `{row['source_article_id']}`")
            lines.append(f"- **自动标记**: {mark}")
            if row["flags"]:
                for fl in row["flags"].split("; "):
                    lines.append(f"  - {fl}")
            lines.append(f"- **原文摘录**: {row['source_excerpt']}")
            lines.append("")
        lines.append("")

    io.open(md_path, "w", encoding="utf-8").write("\n".join(lines))
    print(f"[OK] MD  → {md_path}")

    # ── 摘要 ──
    print()
    print(f"规则 {len(rows)} 条 / 物质 {len(by_sub)} 种")
    print(f"自动标记 {len(flagged)} 条:")
    for row in sorted(flagged, key=lambda x: -x["n_flags"]):
        print(f"  #{row['no']:2d} {row['substance']:<28} {row['species']:<8} "
              f"{row['min']}~{row['max']} {row['unit']}")
        for fl in row["flags"].split("; "):
            print(f"        - {fl}")
    if not flagged:
        print("  (无) —— 但仍需人工逐条核对上下限与原文")


if __name__ == "__main__":
    main()
