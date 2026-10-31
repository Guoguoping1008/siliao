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

# ── 目录表「类别」列里的分类名 ──
# ⚠️ 这些是**分类**(维生素/矿物元素/酶制剂…)，不是物质名。
#    混进 substance_catalog 会让「某物质是否在目录内」的判定失真。
#    实测来源: 《饲料添加剂品种目录》各表的「类别」列。
CATEGORY_NAMES = {
    "维生素及类维生素",
    "矿物元素及其络（螯）合物",
    "矿物元素及其络(螯)合物",
    "酶制剂",
    "微生物",
    "防腐剂、防霉剂和调味剂",
    "饲料添加剂",
    "载体",
    "抗氧化剂",
    "着色剂",
    "香味剂",
    "甜味剂",
    "增味剂",
    "乳化剂",
    "稳定剂",
    "凝固剂",
    "抗结块剂",
    "制粒剂",
    "粘结剂",
    "水分控制剂",
    "品质改良剂",
    "饲料级氨基酸",
    "氨基酸、氨基酸盐及其类似物",
    "其他",
    "养殖动物",
    "适用范围",
    "通用名称",
    "类别",
}


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


def _split_enumerated_names(text: str):
    """拆「多物质挤在一格」的枚举。

    实测: 目录首行把一整类氨基酸塞进一格 ——
      「L-赖氨酸、液体L-赖氨酸（...）、L-赖氨酸盐酸盐、...、牛磺酸」
    这格是**一串独立物质名**, 不是单个物质。
    目录的语义是「这些物质都允许用于养殖动物」, 所以要拆成多条。

    ⚠️ 但不能无脑按「、」拆 —— 物质名本身可能含顿号之外的括号说明,
       如「吡啶甲酸铬」没问题, 但「DL-蛋氨酸」这种没问题,
       真正要小心的是括号内含顿号的, 如「（含维生素B1、维生素B2）」。
       括号内的顿号不拆 —— 用括号深度跟踪。
    """
    out = []
    depth = 0
    buf = []
    for ch in text:
        if ch in "（(":
            depth += 1
        elif ch in "）)":
            depth = max(0, depth - 1)
        if ch in "、,，" and depth == 0:
            seg = "".join(buf).strip()
            if seg:
                out.append(seg)
            buf = []
        else:
            buf.append(ch)
    seg = "".join(buf).strip()
    if seg:
        out.append(seg)
    return out


def _is_scope_cell(text: str) -> bool:
    """这个单元格看起来像「适用范围」而不是物质名。

    适用范围的值全是**动物/对象**的集合:
      养殖动物 / 畜禽 / 猪、家禽 / 反刍动物、猫、狗 / 断奶仔猪、肉仔鸡
      青贮玉米、玉米、豆粕…(原料) / 犬⁴、猫⁴
    而物质名是具体化学名: 丙酸锌 / 核黄素 / 磷酸三钠
    """
    s = normalize_cell(text)
    if not s:
        return False
    # 出现脚注上标的动物标记 (犬⁴) 也是适用范围
    if re.search(r"[犬猫鸡鸭猪牛羊马鱼]\s*[⁴¹²³]", s):
        return True
    # 以顿号/逗号分隔的动物清单 —— 每一段都要是已知动物词
    parts = [p for p in re.split(r"[、,，/]", s) if p.strip()]
    if len(parts) >= 1 and all(_is_animal_token(p) for p in parts):
        return True
    return False


# 适用范围里会出现的动物/对象词(用于判定"这是适用范围不是物质名")
_SCOPE_TOKENS = {
    "养殖动物", "畜禽", "反刍动物", "宠物", "犬", "猫", "狗", "猪", "鸡", "鸭", "鹅",
    "牛", "羊", "马", "驴", "兔", "鱼", "水产养殖动物", "家禽", "仔猪", "乳猪",
    "断奶仔猪", "肉仔鸡", "蛋鸡", "育肥猪", "生长育肥猪", "肉鸡", "肉牛",
    "泌乳奶牛", "成年奶牛", "奶牛", "产蛋禽", "青贮饲料", "青贮玉米",
    "猪、犬、猫", "犬、猫", "猪、家禽", "猪、牛和家禽", "反刍动物、猫、狗",
    "畜禽、鱼和虾", "猪、鸡", "猪、犬、猫", "猪、鸡、牛和水产养殖动物",
}


def _is_animal_token(text: str) -> bool:
    """一个片段是否像动物/适用范围用词(而不是物质名)。"""
    s = normalize_cell(text)
    if not s:
        return True
    if s in _SCOPE_TOKENS:
        return True
    # 纯原料名(玉米/豆粕/麦麸…)也是适用范围
    if s in {"玉米", "豆粕", "小麦", "大麦", "燕麦", "高粱", "米糠", "麸皮",
             "玉米蛋白粉", "棉粕", "菜籽粕", "花生粕", "玉米胚芽粕", "米",
             "小麦副产品", "亚麻粕", "棕榈油", "豆油", "玉米油", "乳糖", "葡萄糖",
             "淀粉", "植物和动物蛋白", "油脂或脂肪", "植物籽实及其加工副产品",
             "含有植酸的植物籽实及其加工副产品", "动物或植物源性油脂或脂肪"}:
        return True
    # 含动物名的复合词, 如「生长育肥猪、家禽、犬、猫」
    for tok in ("猪", "鸡", "牛", "羊", "马", "犬", "猫", "鸭", "鹅", "兔",
                "畜禽", "家禽", "养殖动物", "反刍动物"):
        if tok in s:
            return True
    return False


def _strip_footnote_marks(text: str) -> str:
    """去掉脚注上标与星号: 「L-抗坏血酸*」→「L-抗坏血酸」。

    ⚠️ 目录里脚注用 * 和 ⁴¹²³ 两种标记, 规则库里的物质名没有。
       名字带不带脚注不影响「是否在目录内」, 但**影响字符串精确匹配**。
    """
    s = normalize_cell(text)
    s = re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁺]+", "", s)
    s = re.sub(r"\s*\*+\s*$", "", s)
    return s.strip()


def extract_catalog(articles):
    """抽取《饲料添加剂品种目录》→ 物质目录候选。

    ⚠️ **这份文档里有三类完全不同的表**, 早期版本用一套列规则套全部,
       结果 74 条候选里绝大多数 name_cn 装的是「适用范围」
       (如「畜禽」「猪、家禽」)—— 目录查询会直接失效。

    实测表型:
      A) 类别 | 通用名称 | 适用范围              → 3 列标准目录
      B) 类别 | 通用名称 / 适用范围            → 2 列, 表头合并, 首行是枚举
      C) 序号 | 产品名称 | 英文名称 | 申请单位 | 适用范围 | 批准时间
         → 6 列, 是**新产品审定表**, 不是目录条目

    C 型必须排除 —— 一个审定通过的新产品 ≠ 「在品种目录内」,
    混进去会污染「某物质是否在目录内」的判定。

    ⚠️ **OCR 会吃掉空的合并单元格**:
       目录的「类别」列是**前导合并单元格**语义(每类第一行才有值,
       其余行该列为空), OCR 把空单元格直接丢了 →
       3 列表的行只剩 2 个值(物质名 + 适用范围)。
       实测 51 行如此。所以**不能按固定下标取列**, 必须按语义判定。
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
            hdr = [normalize_cell(h) for h in first]
            hdr_text = " ".join(hdr)

            # ── 表型 C: 新产品审定表 —— 排除 ──
            if ("申请单位" in hdr_text or "批准文号" in hdr_text
                    or "批准时间" in hdr_text or "新饲料证号" in hdr_text
                    or "新产品编号" in hdr_text):
                stats["skipped_new_product_table"] += 1
                continue
            if "通用名称" not in hdr_text:
                continue

            has_scope_col = "适用范围" in hdr_text
            # ⚠️ **合并表头**: 「通用名称 / 适用范围」这一格里同时含两个关键词,
            #    但它其实是**两列**(类别 | 通用名称/适用范围)。
            #    不特判就会走进 A 型分支, 把「适用范围」那一列当成物质名列 ——
            #    实测导致 L-肉碱酒石酸盐 / 二甲基嘧啶醇亚硫酸甲萘醌 等整行丢失。
            merged_name_scope = False
            for h in hdr:
                if "通用名称" in h and "适用范围" in h:
                    merged_name_scope = True
                    break

            cur_category = ""   # 合并单元格向下填充

            for row in rows:
                cells = [normalize_cell(c) for c in row]
                # ⚠️ **空串必须剔除** —— 之前写成
                #    `if c not in EMPTY_CELLS or c == ""` 会把空串**保留**,
                #    于是 3 列表的行变成 3 个值(名/范围/空), 走进「3+ 列」分支,
                #    被误判成 [类别, 物质名, 范围] → 物质名错位 → 整行丢失。
                cells = [c for c in cells if c and c not in EMPTY_CELLS]
                # 去掉全空行
                if not cells:
                    continue
                # 表头行跳过
                if "通用名称" in " ".join(cells) and "适用范围" in " ".join(cells):
                    continue

                # ── 定位「物质名」与「适用范围」两个语义位 ──
                name = ""
                scope = ""
                rest = list(cells)

                # 情形 1: 3 列表且分类名在本行(该类第一行)
                #   [类别, 物质名, 适用范围]
                # 情形 2: 3 列表但 OCR 丢了空类别列 → [物质名, 适用范围]
                # 情形 3: 2 列表 → [物质名, 适用范围]
                # 情形 4: 首行是超长枚举 → [枚举, 适用范围]
                # 情形 5: 只有 1 个值(OCR 丢了空的适用范围列) → [物质名]

                if len(rest) == 1:
                    name = rest[0]
                elif len(rest) == 2:
                    a0, a1 = rest
                    if _is_scope_cell(a1):
                        name, scope = a0, a1
                    elif _is_scope_cell(a0):
                        # [适用范围, 物质名] —— 顺序反了
                        scope, name = a0, a1
                    else:
                        name, scope = a0, ""
                        stats["ambiguous_2col"] += 1
                else:
                    # 3+ 列: 第一格若是分类名则它属于 category
                    #   判据: 分类名不是物质(在 CATEGORY_NAMES 里)
                    #   或它看起来像分类(不含动物词且短)
                    if rest[0] in CATEGORY_NAMES:
                        cur_category = rest[0]
                        rest = rest[1:]
                    elif has_scope_col and len(rest) >= 3:
                        # 首格可能是分类名但不在白名单 —— 靠「后面还有 scope 列」
                        # 无法区分, 保守: 认为是分类名(目录表第0列几乎总是分类)
                        cur_category = rest[0]
                        rest = rest[1:]
                    if rest:
                        name = rest[0]
                    if len(rest) >= 2 and _is_scope_cell(rest[1]):
                        scope = rest[1]
                    elif len(rest) >= 2 and has_scope_col:
                        scope = rest[1]

                if not name:
                    continue
                name = _strip_footnote_marks(name)
                if not name or name in EMPTY_CELLS or name in CATEGORY_NAMES:
                    continue
                # 整格就是适用范围 —— 说明 OCR 把两列并成一格了
                if _is_scope_cell(name):
                    stats["scope_as_name_skipped"] += 1
                    continue

                # ── 一格多物质 → 拆成多条 ──
                # ⚠️ 适用范围列本身也是顿号分隔的(「犬⁴、猫⁴」),
                #    所以**必须先确认 name 位不是范围**, 再拆。
                names = _split_enumerated_names(name)
                if len(names) > 1:
                    stats["enumerated_split"] += len(names)
                for one in names:
                    one = _strip_footnote_marks(one)
                    if not one or one in EMPTY_CELLS or one in CATEGORY_NAMES:
                        continue
                    # 拆出来的片段若又像范围词 —— 说明整格其实是范围,
                    # 已被上面的 _is_scope_cell 拦掉; 到这里说明是
                    # 「猪、鸡」这种被误当作物质名的, 跳过。
                    if _is_scope_cell(one):
                        stats["scope_fragment_skipped"] += 1
                        continue
                    if one in seen:
                        continue
                    seen.add(one)
                    catalog.append({
                        "name_cn": one,
                        "name_en": "",
                        "category": cur_category,
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
