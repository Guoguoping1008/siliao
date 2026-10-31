#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
C1 · 双语名对照补全 —— 从《饲料添加剂安全使用规范》抽 (中文名 ↔ 英文名)

为什么需要
----------
`extract_compliance_rules.py` 抽出来的规则里, 物质名有三种坏形态:

  1. **OCR 掉的拉丁名**   「Niacinamide」「Nicotinicacid」
     「Menadionedimethylpyrimidinolbisulfite(MPB)」
     —— 原文表头是「通用名称 | 英文名称」, 抽取器把英文名那一列当成了通用名。
     后果: 领域层的物质名匹配匹配不上 → 明明库里有规则却判 not_covered。

  2. **全角/半角括号不一致** 「L-抗坏血酸(维生素C)」(半角)
     vs 目录里的「L-抗坏血酸（维生素C）」(全角) → 精确匹配失败。

  3. **脚注标记**        「L-抗坏血酸*」

而《饲料添加剂安全使用规范》(doc 46) 的表格本身就是**双语对照表**:

  通用名称 | 英文名称 | 化学式或描述 | 来源 | 含量规格 | 适用动物 | 限量
  Niacinamide | 烟酰胺 | C₆H₆N₂O | 化学合成 | ≥99.0% | 猪、鸡 | 猪30～60 mg/kg

  L-肉碱 | L-Carnitine | C7H15NO3 | ...

这份表就是**权威对照源**。用它:
  - 把规则的 substance 换成**中文通用名**(判定与展示都该用中文)
  - 把目录条目的 name_en / substance_alias 填上(领域层三级匹配的第三级)

⚠️ 不做「猜」: 只用同表内**明确并列**的中文/英文名建对照。
   对照不上就原样保留 —— 宁可匹配不上判 not_covered, 不可猜。

输出
----
原地改写:
  build/export/compliance_rules.json    —— substance 规范化 + substance_alias 填英文名
  build/export/substance_catalog.json  —— name_en / substance_alias 填英文名
"""

import io
import json
import os
import re
import sys
from collections import Counter, defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INDEX = os.path.join(REPO, "data", "index", "minimax")
OUT_DIR = os.path.join(REPO, "build", "export")

# 《饲料添加剂安全使用规范》
SAFETY_DOC = "46_饲料添加剂安全使用规范"

# ── 中文名判定 ──
# 通用名是中文(可含字母、希腊字母、数字、括号注)。
# 纯 ASCII 开头且不含中文的 → 是英文名那列。
CJK_RE = re.compile(r"[一-鿿]")


def _norm(s: str) -> str:
    """名字归一: 全角括号→半角、去空格、去脚注星号。"""
    if not s:
        return ""
    s = s.replace("（", "(").replace("）", ")")
    s = re.sub(r"\s*\*+\s*$", "", s)
    s = re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁺]+", "", s)
    return s.strip()


def _is_cn_name(s: str) -> bool:
    """是否是中文通用名(含中文即算)。"""
    return bool(CJK_RE.search(s or ""))


def _is_en_name(s: str) -> bool:
    """是否是英文名 —— 有拉丁字母、且**不含中文**。

    ⚠️ 要排除「dl-α-生育酚」这种中英混合的通用名(目录里就是这么写的),
       它虽然含拉丁字母但也含中文 → 不算英文名。

    ⚠️ **还要排除「kg」「mg」这种单位碎片** —— 实测「猪30～60 mg/kg」这一格
       含中文+拉丁, 拆开后 "kg" 会看起来像英文名。判据:
       · 纯短单位词(≤3 字母且全小写)不算
       · 含中文的数字串(用量文本)不算
    """
    if not s or CJK_RE.search(s):
        return False
    if not re.search(r"[A-Za-z]", s):
        return False
    # 纯单位碎片: kg / mg / g / IU / ml / mg/kg …
    if re.fullmatch(r"[A-Za-z]{1,3}(/[A-Za-z]{1,3})?", s):
        return False
    return True


def _looks_like_usage_text(s: str) -> bool:
    """是不是「用量文本」而不是名字。

    实测: 「猪30～60 mg/kg鸡30～60 mg/kg」这种格子含中文 + 数字 + 单位,
    它不是名字, 拆开后 "kg" 会被误当成英文名。
    """
    if not s:
        return False
    # 含中文 + 数字 → 用量/含量文本
    if CJK_RE.search(s) and re.search(r"\d", s):
        return True
    return False


def _split_cn_en(cell: str):
    """一格里同时含中英文时拆开。

    实测: 目录里「维生素A、维生素A乙酸酯…」后面直接跟英文名的情况存在,
    OCR 还把「通用名/英文名」写进同一格(用 / 分隔)。
    """
    c = cell or ""
    if "/" in c:
        parts = [p.strip() for p in c.split("/") if p.strip()]
        cn = [p for p in parts if _is_cn_name(p)]
        en = [p for p in parts if _is_en_name(p)]
        if cn and en:
            return cn[0], en[0]
    return None, None


def _rows_of(text: str):
    """从 article text 里切出所有表格的行(保留 HTML 单元格结构)。"""
    for m in re.finditer(r"<table.*?</table>", text, re.S):
        tbl = m.group(0)
        for r in re.findall(r"<tr>(.*?)</tr>", tbl, re.S):
            cells = [re.sub(r"<[^>]+>", "", c).strip()
                     for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r, re.S)]
            if cells:
                yield cells


def _find_bilingual_pairs(cells):
    """在一行里找 (中文名, 英文名) 配对 —— **按内容判定, 不按表头位置**。

    ⚠️ **表头不可信**: 实测《安全使用规范》p001_s03 的表头写的是
       「通用名称 | 化学名称 | 化学式描述」, 但**实际内容是英文名在前、中文名在后**:
         ['Menadione sodium bisulfite (MSB)', '亚硫酸氢钠甲萘醌', 'C₁₁H₉NaO₅S·nH₂O', …]
       ['Niacinamide',                       '烟酰胺',            'C₆H₆N₂O',           …]
       所以**不能按列下标**取 —— 必须在一行里按内容找:
         · 英文名 = 纯拉丁字母、不含中文、且**不像化学式**
         · 中文名 = 含中文、不含拉丁字母串(避免「dl-α-生育酚」这种中英混合名)

    同时处理同一格内用 / 分隔的情况(表头被 OCR 写进数据行):
      ['通用名称/L-抗坏血酸(维生素C)', '英文名称/L-Ascorbic acid (Vitamin C)', …]

    排除化学式: 含下标数字(C₆H₆N₂O)、含 ·/⁻ 等化学符号, 或匹配元素式模式。
    """
    # ── 同格斜杠分隔(表头混进数据行) ──
    for c in cells:
        cn, en = _split_cn_en(c)
        if cn and en:
            return cn, en

    en_candidates = []
    cn_candidates = []
    for c in cells:
        if not c:
            continue
        if _looks_like_formula(c):
            continue
        if _looks_like_usage_text(c):
            continue
        if _is_en_name(c) and len(c) <= 60:
            en_candidates.append(c)
        elif _is_cn_name(c) and not _has_latin_word(c) and len(c) <= 60:
            cn_candidates.append(c)

    if not en_candidates:
        return None, None
    if not cn_candidates:
        return None, None

    # 英文名取第一个; 中文名取**与它同行的中文候选** ——
    # 同表里中英并列, 谁在左谁在右都不一定(表头不可信), 所以取最近的。
    en = en_candidates[0]
    en_i = next(i for i, c in enumerate(cells) if c == en)
    cn = None
    best_dist = None
    for j, c in enumerate(cells):
        if c not in cn_candidates:
            continue
        d = abs(j - en_i)
        if best_dist is None or d < best_dist:
            cn = c
            best_dist = d
    if cn is None:
        cn = cn_candidates[0]
    return cn, en


_FORMULA_HINTS = ("·", "⁻", "₆", "₂", "₃", "₄", "₅", "₇", "₈", "₉", "ₓ", "H₂O")


def _looks_like_formula(s: str) -> bool:
    """判断一个格子是不是化学式而不是英文名。

    例: C₆H₆N₂O / C11H18N2O8 / FeSO4·7H2O / NH₂(CH₂)₄CH(NH₂)COOH·HCl
    """
    if not s:
        return False
    if any(h in s for h in _FORMULA_HINTS):
        return True
    # 元素式: 开头大写字母 + 数字, 如 C6H6N2O / FeSO4
    if re.fullmatch(r"[A-Z][A-Za-z0-9()·⁻]{2,30}", s) and re.search(r"\d", s):
        return True
    return False


def _has_latin_word(s: str) -> bool:
    """含中文的串里是否**混着**拉丁词(如「dl-α-生育酚」)。

    这种是通用名(中英混写), 不能当英文名 —— 但可以当中文名。
    """
    return bool(re.search(r"[A-Za-z]{2,}", s))


def _name_skeleton(s: str) -> str:
    """去掉盐型修饰词后的「骨架名」。

    ⚠️ **只去确定无歧义的化学修饰词**, 且调用方必须要求候选唯一。
    目的: 让「亚硫酸甲萘醌」与「亚硫酸氢钠甲萘醌」这类**同物异写**对上。

    去掉的修饰词: 氢钠 / 钠 / 钙 / 铁 / 锌 / 亚铁 / 硫酸 / 盐酸 / 磷酸 …
    保留主体: 甲萘醌 / 抗坏血酸 / 生物素 / 核黄素 …

    ⚠️ **不做语义推理** —— 只是把「盐型前后缀」剥掉, 让剩下部分可比较。
       若剥完变成空串(说明整个名字都是修饰词), 返回空 → 调用方跳过。
    """
    if not s:
        return ""
    t = s
    # 括号内容先去掉(脚注式说明)
    t = re.sub(r"[（(][^）)]*[）)]", "", t)
    # 去掉盐型修饰词
    for mod in ("亚硫酸氢钠", "亚硫酸钠", "硫酸氢钠", "磷酸氢二", "磷酸二氢",
                "亚硫酸", "硫酸", "盐酸", "磷酸", "碳酸", "醋酸", "乙酸",
                "氯化", "溴化", "碘化", "硝酸", "苹果酸", "乳酸", "柠檬酸",
                "亚铁", "硫酸亚", "氢钠", "钠", "钙", "铁", "锌", "铜", "锰",
                "钴", "硒", "碘", "钾", "镁"):
        t = t.replace(mod, "")
    t = re.sub(r"[^\w一-鿿]", "", t)
    return t


def build_name_map(articles):
    """扫《安全使用规范》的所有表, 建 中文名 → 英文名 对照表。"""
    name2en = {}
    en2cn = {}
    stats = Counter()

    for a in articles:
        doc_id = a.get("doc_id", "")
        if SAFETY_DOC not in doc_id:
            continue
        text = a.get("text") or ""
        if "<table" not in text:
            continue

        for cells in _rows_of(text):
            cn, en = _find_bilingual_pairs(cells)
            if not cn or not en:
                continue
            cn = _norm(cn)
            en = _norm(en)
            if not cn or not en:
                continue
            # 已经有且不一致 → 冲突, 不覆盖(保守)
            if cn in name2en and name2en[cn] != en:
                stats["conflict_cn"] += 1
                continue
            name2en[cn] = en
            # 英文名同时按「带缩写」「去缩写」两种形态登记 ——
            # 原文写「Menadione dimethyl pyrimidinol bisulfite (MPB)」,
            # 而规则里是「Menadionedimethylpyrimidinolbisulfite(MPB)」(OCR 掉了空格),
            # 剥掉缩写后两边才对得上。
            en2cn.setdefault(en.lower(), cn)
            stripped = _strip_abbrev(en)
            if stripped and stripped.lower() != en.lower():
                en2cn.setdefault(stripped.lower(), cn)
            stats["pairs"] += 1

    return name2en, en2cn, stats


# ─────────────────────────────────────────────────────────────
# 名字形态归一
# ─────────────────────────────────────────────────────────────

# OCR 掉的英文名 → 正确写法(含空格)。这些是「已知坏形态」的修正表。
OCR_LATIN_FIXES = {
    # OCR 把词间空格吃了
    "nicotinicacid": "Nicotinic acid",
    "niacinamide": "Niacinamide",
    "menadionedimethylpyrimidinolbisulfite": "Menadione dimethyl pyrimidinol bisulfite",
    "menadionedimethylpyrimidinolbisulfite(mpb)":
        "Menadione dimethyl pyrimidinol bisulfite",
    "menadionesodiumbisulfite": "Menadione sodium bisulfite",
    "menadionenicotinamidebisulfite": "Menadione nicotinamide bisulfite",
    "l-carnitine-l-tartrate": "L-Carnitine-L-Tartrate",
    "d-biotin": "D-Biotin",
    "naturalvitam ine": "Natural vitamin E",
    "naturalvitamine": "Natural vitamin E",
}


def normalize_latin(s: str) -> str:
    """修正 OCR 掉的英文名(去掉空格后的写法)。"""
    if not s:
        return s
    key = re.sub(r"\s+", "", _strip_abbrev(s)).lower()
    for bad, good in OCR_LATIN_FIXES.items():
        if key == bad:
            return good
    return s


def _strip_abbrev(s: str) -> str:
    """去掉末尾的缩写括号: 「…bisulfite(MPB)」→「…bisulfite」。

    实测: OCR 把「通用名 | 英文名」两列并成一格时, 会把英文名的缩写
    一起粘上来: 「Menadionedimethylpyrimidinolbisulfite(MPB)」。
    缩写本身是**该表英文名的后缀**(原文写的是
    「Menadione dimethyl pyrimidinol bisulfite (MPB)」), 所以要剥掉才能对上。
    """
    return re.sub(r"\s*\([A-Za-z]{1,6}\)\s*$", "", s or "").strip()


def is_ocr_latin(s: str) -> bool:
    """判断这个名字是不是「OCR 掉了空格的英文名」。

    判据: 纯拉丁字母(无中文) + 剥掉缩写后归一能命中修正表 + 原串本身不含空格。
    """
    if not s or CJK_RE.search(s):
        return False
    if " " in s:
        return False
    key = re.sub(r"\s+", "", _strip_abbrev(s)).lower()
    return key in OCR_LATIN_FIXES


def main():
    arts_path = os.path.join(INDEX, "articles.json")
    if not os.path.exists(arts_path):
        print("[FAIL] 找不到 articles.json:", arts_path)
        sys.exit(1)
    articles = json.load(io.open(arts_path, encoding="utf-8"))
    print("[scan] articles:", len(articles))

    name2en, en2cn, mstats = build_name_map(articles)
    print(f"[bilingual] 中文↔英文对照 {len(name2en)} 对 (冲突 {mstats['conflict_cn']})")

    # ── 改写规则 ──
    rules_path = os.path.join(OUT_DIR, "compliance_rules.json")
    rules_doc = json.load(io.open(rules_path, encoding="utf-8"))
    rules = rules_doc["rules"]
    rstats = Counter()

    for r in rules:
        sub = r.get("substance") or ""
        key = _norm(sub)

        # ① OCR 掉的拉丁名 → 先按修正表还原, 再查中文对照
        if is_ocr_latin(sub):
            fixed = normalize_latin(sub)
            cn = en2cn.get(fixed.lower())
            if not cn:
                # 对照表的 key 带缩写: 「… bisulfite (MPB)」→ 剥掉再试
                cn = en2cn.get(_strip_abbrev(fixed).lower())
            rstats["latin_fixed"] += 1
            if cn:
                r["substance"] = cn
                r["substance_alias"] = fixed
                rstats["latin_to_cn"] += 1
            else:
                r["substance_alias"] = fixed
                rstats["latin_no_cn"] += 1
            continue

        # ② 中文名 → 补英文别名
        en = name2en.get(key)
        if not en:
            # 归一后(全角→半角)再试一次
            for cn2, en2 in name2en.items():
                if _norm(cn2) == key:
                    en = en2
                    break
        if en:
            r["substance_alias"] = en
            rstats["alias_filled"] += 1

        # ③ 名称形态归一: 目录里是全角括号, 规则里是半角 —— 统一到半角
        if key != sub:
            r["substance"] = key
            rstats["paren_normalized"] += 1

    rules_doc["rules"] = rules
    json.dump(rules_doc, io.open(rules_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("[rules]", dict(rstats))

    # ── 改写目录 ──
    cat_path = os.path.join(OUT_DIR, "substance_catalog.json")
    cat_doc = json.load(io.open(cat_path, encoding="utf-8"))
    cstats = Counter()

    for s in cat_doc["substances"]:
        key = _norm(s.get("name_cn") or "")
        if not key:
            continue
        # 归一: 全角括号→半角, 去脚注
        if key != s["name_cn"]:
            s["name_cn"] = key
            cstats["name_normalized"] += 1
        en = name2en.get(key)
        if not en:
            for cn2, en2 in name2en.items():
                if _norm(cn2) == key:
                    en = en2
                    break
        if not en:
            # ⚠️ **两份文档对同一物质的中文写法可能略有出入**:
            #      目录      「二甲基嘧啶醇亚硫酸甲萘醌」
            #      安全使用规范「二甲基嘧啶醇亚硫酸氢钠甲萘醌」
            #    差一个「氢钠」。这里用**去修饰词后的骨架**做一次安全匹配:
            #    只在骨架完全相等、且候选唯一时才继承英文名 —— 不猜。
            skel = _name_skeleton(key)
            if skel:
                cands = [(cn2, en2) for cn2, en2 in name2en.items()
                         if _name_skeleton(cn2) == skel]
                if len(cands) == 1:
                    en = cands[0][1]
                    cstats["name_en_by_skeleton"] += 1
        if en:
            s["name_en"] = en
            cstats["name_en_filled"] += 1
        # 括号别名: 「L-抗坏血酸(维生素C)」→ 别名「维生素C」
        m = re.search(r"\(([^)]+)\)", key)
        if m and m.group(1).strip():
            s["substance_alias"] = m.group(1).strip()
            cstats["bracket_alias"] += 1

    cat_doc["substances"] = cat_doc["substances"]
    json.dump(cat_doc, io.open(cat_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("[catalog]", dict(cstats))

    # ── 交叉校验: 规则的物质现在都能在目录里找到吗? ──
    # ⚠️ 判据用**英文名**(唯一键), 不直接比中文串 ——
    #    目录与安全使用规范对同一物质的中文写法可能不同:
    #      目录      「二甲基嘧啶醇亚硫酸甲萘醌」
    #      安全使用规范「二甲基嘧啶醇亚硫酸氢钠甲萘醌」
    #    这是**同一个物质**(英文名都是 Menadione dimethyl pyrimidinol bisulfite)。
    #
    # ⚠️ 英文名两边都**剥掉缩写**再比:
    #    目录侧  「Menadione dimethyl pyrimidinol bisulfite (MPB)」
    #    规则侧  「Menadione dimethyl pyrimidinol bisulfite」
    def _en_key(s: str) -> str:
        return _strip_abbrev(s or "").lower()

    cat_by_en = {}
    for s in cat_doc["substances"]:
        if s.get("name_en"):
            cat_by_en.setdefault(_en_key(s["name_en"]), s["name_cn"])
    cat_names = {s["name_cn"] for s in cat_doc["substances"]}

    missing = []
    linked = 0
    for r in rules:
        if r["substance"] in cat_names:
            continue
        alias = _en_key(r.get("substance_alias") or "")
        if alias and alias in cat_by_en:
            linked += 1
            continue
        missing.append(r["substance"])
    uniq_missing = sorted(set(missing))
    print(f"[check] 规则物质: 直接命中 {len(rules)-len(missing)-linked} · "
          f"经英文名关联 {linked} · 未找到 {len(uniq_missing)}")
    for m in uniq_missing:
        print("   ⚠️", m)
    print("[OK] 完成")


if __name__ == "__main__":
    main()
