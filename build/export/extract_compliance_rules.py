#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
C1 · 限量规则抽取器 —— 从 articles.json 抽 (物质×动物×限量) 三元组

为什么从 articles.json 而不是 minimax/*.md
--------------------------------------
`ingest_minimax.py` 里 `source_file` 字段只记 `files[0].name` —— **一个文档下
所有 md 都记成第一个文件名**。实测《饲料添加剂安全使用规范》29 个 md 全部映射到
`0319.md`, 无法区分。

而 `articles.json` 里:
  - `text` 字段**保留了完整表格 HTML**(strip_html_table_noise 不动表格)
  - `article_id` 天然正确
  - 与 D1 里 `articles` 表一一对应(灌库时 body 就是这个 text)

所以**从 articles.json 抽** —— 溯源直接可用, 不需要猜。

5 种真实写法(全部实测自语料, 见功能设计文档 §2.4)
----------------------------------------------------
  1. 猪150～300mg/kg
  2. 猪：0.15 ～0.5 mg/kg            ← 全角/半角冒号
  3. 罗非鱼、鲶鱼—鱼苗300mg/kg—鱼种200mg/kg   ← 一个动物两个阶段值
  4. 猪30～50mg/kg(乳猪300～500mg/kg)        ← 括号是**例外**, 不是主值
  5. 同时使用时,在配合饲料中的总量不得超过150mg/kg  ← 组合约束, **不是单体**

输出
----
build/export/compliance_rules.json  —— 候选规则, 全部 review_status='pending'
build/export/substance_catalog.json —— 物质目录候选

⚠️ 抽取结果**一律 pending**, 必须人工校核后才能生效。
   判定时只读 review_status='reviewed' 的规则 —— 见功能设计文档 §4.9。
"""

import io
import json
import os
import re
import sys
from collections import Counter, OrderedDict

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INDEX = os.path.join(REPO, "data", "index", "minimax")
OUT_DIR = os.path.join(REPO, "build", "export")

# ─────────────────────────────────────────────────────────────
# 词表
# ─────────────────────────────────────────────────────────────

# 动物种类 —— 按长度降序, 保证「蛋用鸡」优先于「鸡」
ANIMALS = sorted(
    [
        "肉用鸡", "蛋用鸡", "后备母猪", "哺乳母猪", "妊娠母猪", "生长猪", "育肥猪",
        "育成猪", "种猪", "仔猪", "乳猪", "后备猪",
        "肉鸡", "蛋鸡", "肉鸭", "蛋鸭", "种鸡", "雏鸡", "青年鸡",
        "鹌鹑",
        "犊牛", "奶牛", "肉牛", "育成牛", "黄牛", "水牛",
        "罗非鱼", "虹鳟鱼", "鲶鱼", "青鱼", "草鱼", "鲤鱼", "鲫鱼", "鳙鱼",
        "虾类", "蟹类", "贝类", "其他鱼", "海参", "扇贝", "乌贼",
        "家禽", "禽类", "水产", "鱼类",
        "猪", "牛", "羊", "马", "驴", "鹅", "兔", "犬", "猫", "貂",
        "鱼",
    ],
    key=len,
    reverse=True,
)
ANIMAL_RE = "|".join(ANIMALS)

# 动物阶段 —— 跟在动物名后面, 构成更细的适用对象
STAGES = sorted(
    [
        "鱼苗", "鱼种", "仔猪", "育成猪", "育肥猪", "生长猪", "雏鸡",
        "青年鸡", "乳猪", "后备母猪", "哺乳母猪", "妊娠母猪",
    ],
    key=len,
    reverse=True,
)
STAGE_RE = "|".join(STAGES)

# 限量单位 —— **不含 %**。质量指标(蛋白质≥50%)不是限量。
LIMIT_UNITS = ["mg/kg", "g/kg", "万IU/kg", "IU/kg", "IU/g"]
LIMIT_UNIT_RE = "|".join(re.escape(u) for u in LIMIT_UNITS)

NUM = r"\d+(?:\.\d+)?"

# 范围: 猪150～300mg/kg / 猪：0.15 ～0.5 mg/kg
RANGE_RE = re.compile(
    r"(?P<animal>" + ANIMAL_RE + r")"
    r"(?P<stage>" + STAGE_RE + r")?"
    r"\s*(?:：|:)?\s*"
    r"(?P<lo>" + NUM + r")\s*[～~—\-至]\s*(?P<hi>" + NUM + r")\s*"
    r"(?P<unit>" + LIMIT_UNIT_RE + r")"
)

# 单值: 鱼苗300mg/kg (无上下限)
SINGLE_RE = re.compile(
    r"(?P<animal>" + ANIMAL_RE + r")"
    r"(?P<stage>" + STAGE_RE + r")?"
    r"\s*(?:：|:)?\s*"
    r"(?P<val>" + NUM + r")\s*"
    r"(?P<unit>" + LIMIT_UNIT_RE + r")"
)

# 组合约束 —— 「同时使用时...总量不得超过150mg/kg」
COMBINATION_RE = re.compile(r"(同时使用|配合使用|混合使用|总量|不得超过|不得同时)")

# 「适用动物」列的识别关键词
SPECIES_COL_KEYS = ["适用动物", "适用范围", "适用对象", "适用情况"]
# 物质名列
SUBSTANCE_COL_KEYS = ["通用名称", "产品名称", "物质名称", "名称"]

EMPTY_CELLS = {"—", "-", "", "　", "/", "无", "N/A"}


# ─────────────────────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────────────────────

def strip_tags(html: str) -> str:
    """HTML → 纯文本。"""
    t = re.sub(r"<br\s*/?>", "\n", html)
    t = re.sub(r"<sub>(.*?)</sub>", r"\1", t, flags=re.S)
    t = re.sub(r"<sup>(.*?)</sup>", r"\1", t, flags=re.S)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"[ \t　]+", " ", t).strip()


def normalize_cell(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def is_empty(cell: str) -> bool:
    return normalize_cell(cell) in EMPTY_CELLS


def parse_tables(text: str):
    """把文本里的所有 <table> 解析成 (first_row, all_rows)。

    ⚠️ **不丢弃第 0 行** —— OCR 常把「表头 + 第一条数据」合并成一行
       (实测《饲料添加剂安全使用规范》表0 第 0 行是
        「通用名称/L-抗坏血酸(维生素C) | ... | 适用动物/猪150～300mg/kg ...」)。
       丢掉它就丢了第一条限量规则。

    返回:
      first_row  第 0 行(可能是表头, 也可能是表头+数据合并行)
      all_rows   全部行(含第 0 行)
    """
    out = []
    for m in re.finditer(r"<table[^>]*>(.*?)</table>", text, re.S):
        inner = m.group(1)
        raw_rows = re.findall(r"<tr[^>]*>(.*?)</tr>", inner, re.S)
        rows = []
        for r in raw_rows:
            cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r, re.S)
            rows.append([strip_tags(c) for c in cells])
        if rows:
            out.append((rows[0], rows))
    return out


def find_col(header, keys):
    """按关键词找列号。表头可能是「通用名称/适用范围」这种合并写法。"""
    for i, h in enumerate(header):
        if any(k in h for k in keys):
            return i
    return -1


def find_species_col(header, body_rows):
    """找「适用动物」列。

    优先用表头关键词; 表头不可靠时, 退化为「含动物+数值」最多的列。
    """
    idx = find_col(header, SPECIES_COL_KEYS)
    if idx >= 0:
        return idx
    best, best_n = -1, 0
    width = max((len(r) for r in body_rows), default=0)
    for c in range(width):
        n = sum(1 for r in body_rows
                if c < len(r) and RANGE_RE.search(normalize_cell(r[c])))
        if n > best_n:
            best, best_n = c, n
    return best if best_n > 0 else -1


def looks_like_header(cells) -> bool:
    """判断一行是不是**表头**而不是数据行。

    ⚠️ **OCR 会把表头和数据行合并** —— 实测《饲料添加剂安全使用规范》:
       表0 的第 0 行是「通用名称/L-抗坏血酸(维生素C) | ... | 适用动物/猪150～300mg/kg ...」
       也就是**表头 + 第一条数据挤在同一行**。

    判据: 一行里出现「通用名称/适用范围/英文名称」这类**列名关键词**, 且该行
    没有独立的动物+数值配对 → 视为表头行。

    但如果表头行**同时**含可解析的限量(合并行的情况), 它也得当数据处理 ——
    所以返回 True 只表示「它的第一列是列名, 不能当物质名」, 数据仍要抽。
    """
    joined = " ".join(cells)
    col_names = ["通用名称", "英文名称", "适用范围", "适用动物", "化学式", "含量规格", "类别", "产品名称"]
    return any(k in joined for k in col_names)


def parse_species_cell(cell: str):
    """解析「适用动物」单元格 → [{animal, stage, min, max, unit, kind}]

    kind:
      range        猪150～300mg/kg
      single       鱼苗300mg/kg
      bracket      括号内的例外值 —— 乳猪300～500
    """
    txt = normalize_cell(cell)
    out = []

    # ── 括号内容单独处理(格式 4) ──
    brackets = re.findall(r"[（(]([^）)]*)[）)]", txt)
    main_text = re.sub(r"[（(][^）)]*[）)]", "", txt)

    def harvest(s, kind):
        got = []
        for m in RANGE_RE.finditer(s):
            got.append({
                "animal": m.group("animal"), "stage": m.group("stage") or "",
                "min": float(m.group("lo")), "max": float(m.group("hi")),
                "unit": m.group("unit"), "kind": kind,
            })
        if not got:
            for m in SINGLE_RE.finditer(s):
                got.append({
                    "animal": m.group("animal"), "stage": m.group("stage") or "",
                    "min": float(m.group("val")), "max": float(m.group("val")),
                    "unit": m.group("unit"), "kind": kind,
                })
        return got

    out.extend(harvest(main_text, "range"))
    for b in brackets:
        out.extend(harvest(normalize_cell(b), "bracket"))
    return out


def is_combination(text: str) -> bool:
    """判断是不是组合约束(格式 5) —— 不针对单一物质。"""
    return bool(COMBINATION_RE.search(normalize_cell(text)))


def clean_substance(name: str) -> str:
    """清洗物质名: 去序号前缀、去斜杠后半段。"""
    s = normalize_cell(name)
    s = re.sub(r"^[（(]?\d+[）)]?", "", s)
    # 「通用名称/L-抗坏血酸(维生素C)」→ 保留后半(但表头行本身要排除)
    if "/" in s:
        s = s.split("/")[-1]
    return s.strip()


# ─────────────────────────────────────────────────────────────
# 抽取主流程
# ─────────────────────────────────────────────────────────────

def load_articles():
    path = os.path.join(INDEX, "articles.json")
    if not os.path.exists(path):
        print("[FAIL] 找不到 articles.json:", path)
        sys.exit(1)
    return json.load(io.open(path, encoding="utf-8"))


def extract_limit_rules(articles):
    """主抽取: 返回 (rules, stats)"""
    rules = []
    stats = Counter()
    seen = set()

    for a in articles:
        text = a.get("text") or ""
        if "<table" not in text:
            continue
        doc_id = a.get("doc_id", "")
        article_id = a.get("article_id", "")

        for first, rows in parse_tables(text):
            if not rows:
                continue

            # ── OCR 常把「表头 + 第一条数据」合并成一行 ──
            #    所以第 0 行既要当表头用(定位列), 也要当数据行用(抽限量)。
            merged_header = looks_like_header(first)

            # 定位「适用动物」列: 先用第 0 行(可能是真表头), 再统计
            sp_col = find_species_col(first, rows)
            if sp_col < 0:
                stats["table_no_species_col"] += 1
                continue

            name_col = find_col(first, SUBSTANCE_COL_KEYS)
            if name_col < 0:
                name_col = 0

            # 全部行都是数据行(含第 0 行) —— 合并行的第 0 行也要抽
            data_rows = rows

            for row in data_rows:
                if not row or name_col >= len(row):
                    continue

                # 组合约束(格式 5): 整行提到「总量/同时使用」且无范围 → 跳过
                if is_combination(" ".join(row)) and not any(
                        RANGE_RE.search(normalize_cell(c)) for c in row):
                    stats["combination_skipped"] += 1
                    continue

                # 物质名 = 名称列
                if merged_header and row is first:
                    # 合并行: 「通用名称/L-抗坏血酸(维生素C)」→ 取斜杠后半
                    substance = clean_substance(row[name_col])
                else:
                    substance = clean_substance(row[name_col])
                if not substance or substance in EMPTY_CELLS:
                    continue
                if substance in ("通用名称", "产品名称", "序号", "名称", "类别"):
                    continue

                # ── 扫描**所有**列找限量 ──
                #    实测: 表1 的「适用动物」列是范围, 而「最高限量」列也可能有独立值
                #    (如 维生素D3 的「猪50μg/kg肉鸡、火鸡100μg/kg」)。
                #    但「含量规格」列是质量指标(≥97.0%), 靠单位白名单排除。
                found_any = False
                for c, cell in enumerate(row):
                    if is_empty(cell):
                        continue
                    parsed = parse_species_cell(cell)
                    if not parsed:
                        continue
                    for p in parsed:
                        key = (substance, p["animal"], p["stage"], p["min"], p["max"], p["unit"])
                        if key in seen:
                            stats["dup"] += 1
                            continue
                        seen.add(key)
                        found_any = True

                        rules.append({
                            "rule_type": "limit",
                            "substance": substance,
                            "species": p["animal"],
                            "stage": p["stage"],
                            "min_value": p["min"],
                            "max_value": p["max"],
                            "unit": p["unit"],
                            "extraction_kind": p["kind"],
                            "source_article_id": article_id,
                            "source_doc_id": doc_id,
                            "source_excerpt": cell[:400],
                            "review_status": "pending",
                        })
                        stats["limit"] += 1
                if not found_any:
                    stats["row_no_limit"] += 1

    return rules, stats


def extract_catalog(articles):
    """抽取《饲料添加剂品种目录》→ 物质目录候选。

    表头: 类别 | 通用名称 | 适用范围
    """
    catalog = []
    stats = Counter()
    seen = set()

    for a in articles:
        doc_id = a.get("doc_id", "")
        if "品种目录" not in doc_id:
            continue
        text = a.get("text") or ""
        if "<table" not in text:
            continue

        for first, rows in parse_tables(text):
            if not rows:
                continue
            hdr_text = " ".join(first)
            if "通用名称" not in hdr_text:
                continue  # 不是目录表(可能是「新饲料证号」等表)

            name_col = find_col(first, ["通用名称"])
            scope_col = find_col(first, ["适用范围"])
            cat_col = find_col(first, ["类别"])
            if cat_col < 0:
                cat_col = 0
            if name_col < 0:
                continue

            for row in rows:
                if len(row) <= name_col:
                    continue
                name = clean_substance(row[name_col])
                if not name or name in EMPTY_CELLS or name == "通用名称":
                    continue
                if name in seen:
                    continue
                seen.add(name)

                category = normalize_cell(row[cat_col]) if cat_col < len(row) else ""
                scope = normalize_cell(row[scope_col]) if 0 <= scope_col < len(row) else ""

                catalog.append({
                    "name_cn": name,
                    "name_en": "",
                    "category": category,
                    "scope_text": scope,
                    "source_article_id": a.get("article_id", ""),
                    "source_doc_id": doc_id,
                    "review_status": "pending",
                })
                stats["catalog"] += 1

    return catalog, stats


# ─────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────

def main():
    articles = load_articles()
    print("[scan] articles.json:", len(articles), "条")

    rules, rstats = extract_limit_rules(articles)
    catalog, cstats = extract_catalog(articles)

    # ── 溯源完整性检查(不变量 2) ──
    no_source = [r for r in rules if not r["source_article_id"]]
    rules = [r for r in rules if r["source_article_id"]]

    os.makedirs(OUT_DIR, exist_ok=True)

    rules_path = os.path.join(OUT_DIR, "compliance_rules.json")
    with io.open(rules_path, "w", encoding="utf-8") as f:
        json.dump({
            "rule_set_version": "v2026.10",
            "note": "自动抽取候选 —— 全部 review_status='pending', 需人工校核后方可生效",
            "count": len(rules),
            "rules": rules,
        }, f, ensure_ascii=False, indent=2)

    cat_path = os.path.join(OUT_DIR, "substance_catalog.json")
    with io.open(cat_path, "w", encoding="utf-8") as f:
        json.dump({
            "rule_set_version": "v2026.10",
            "note": "物质目录候选 —— review_status='pending'",
            "count": len(catalog),
            "substances": catalog,
        }, f, ensure_ascii=False, indent=2)

    # ── 报告 ──
    print("\n=== 抽取结果 ===")
    print("  限量规则候选 : %d" % len(rules))
    print("  物质目录候选 : %d" % len(catalog))
    print("\n=== 统计 ===")
    for k, v in sorted(rstats.items()):
        print("  %-22s %d" % (k, v))
    for k, v in sorted(cstats.items()):
        print("  %-22s %d" % (k, v))
    print("\n=== 溯源完整性(不变量 2) ===")
    print("  无 source_article_id 被拒 : %d" % len(no_source))
    print("  全部规则带溯源           : %s" % ("是 ✅" if not no_source else "否 ❌"))

    # 按物质分组预览
    by_sub = OrderedDict()
    for r in rules:
        by_sub.setdefault(r["substance"], []).append(r)
    print("\n=== 按物质分组(%d 种) ===" % len(by_sub))
    for sub, rs in list(by_sub.items()):
        spec = ", ".join(
            "%s%s %g~%g%s" % (x["species"], ("/" + x["stage"]) if x["stage"] else "",
                               x["min_value"], x["max_value"], x["unit"])
            for x in rs)
        print("  %-24s %s" % (sub[:24], spec[:88]))

    print("\n[OK] rules   →", rules_path)
    print("[OK] catalog →", cat_path)


if __name__ == "__main__":
    main()
