#!/usr/bin/env python3
"""
从 minimax/001目录/目录合并.md 生成结构化目录树 catalog.json。

为什么不用「目录 title ↔ documents.title」文本匹配:
  源目录是 OCR 出来的, 有大量形近字/漏字, 实测 175 个文件里只有 147 个
  能按 title 精确匹配到真实文档:
    目录「饲料质量安全管理规范」  vs 文档「饲料质量安全管理办法」(OCR 漏字)
    目录「乙醇、氨苯肿酸、洛克沙肿」 vs 文档「喹乙醇、氨苯胂酸、洛克沙胂」(形近字)
    目录「深人推进」                vs 文档「深入推进」(形近字)
    目录「投人品」                  vs 文档「投入品」(形近字)
  靠文本匹配会漏掉 28 个条目 —— 而目录的价值恰恰是**完整覆盖**。

对策: 用 ingest 已经写好的结构化字段定位, 不碰 OCR 文本:
  - documents.scope    → 一级分类
  - documents.section  → 二级分类
  - doc_id 里的序号   → 该分类下的第 N 个文件
  目录合并.md 的层级顺序 == ingest 的目录树顺序(同一棵树的两种表述)。

输出:
  data/index/minimax/catalog.json   { scopes: [ {title, sections: [ {title, page, docs: [...] } ] } ] }
  每条 doc: { title, doc_number, page, doc_id, matched, match_by }
  matched=false 的条目仍然保留在目录里(目录要完整), 只是不给链接。
"""

import difflib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG_MD = ROOT / "minimax" / "001目录" / "目录合并.md"
DOCS_JSON = ROOT / "data" / "index" / "minimax" / "documents.json"
OUT_JSON = ROOT / "data" / "index" / "minimax" / "catalog.json"

# 目录里的一级分类名 → documents.scope
SCOPE_MAP = {
    "法规": "01法规",
    "制度文件": "02制度文件",
    "相关法律法规文件": "03相关法律法规文件",
    "标准及标准目录": "04标准及标准目录",
}


def clean_title(s: str) -> str:
    """去掉 OCR 标题里内嵌的 '------ 39' 页码标记。"""
    return re.sub(r"\s*-{2,}\s*\d+\s*$", "", s).strip()


def parse_catalog(md: str):
    """把目录合并.md 解析成 scope/section/doc 三层树(保留顺序)。"""
    lines = md.splitlines()
    scopes = []
    cur_scope = None
    cur_section = None

    for i, raw in enumerate(lines):
        s = raw.strip()
        if not s or s.startswith("<!--"):
            continue

        if s.startswith("## "):
            title = s[3:].strip()
            cur_scope = {"title": title, "sections": []}
            scopes.append(cur_scope)
            cur_section = None

        elif s.startswith("### "):
            body = s[4:].strip()
            pm = re.search(r"-{2,}\s*(\d+)\s*$", body)
            cur_section = {
                "title": clean_title(body),
                "page": int(pm.group(1)) if pm else None,
                "docs": [],
            }
            if cur_scope is not None:
                cur_scope["sections"].append(cur_section)

        elif s.startswith("#### "):
            title = clean_title(s[5:].strip())
            doc_number, page = None, None
            # 下一条非空行通常是「文号 ------ 页码」
            for j in range(i + 1, min(i + 4, len(lines))):
                nxt = lines[j].strip()
                if not nxt:
                    continue
                if nxt.startswith("#"):
                    break
                m = re.search(r"-{2,}\s*(\d+)\s*$", nxt)
                if m:
                    page = int(m.group(1))
                    doc_number = nxt[: m.start()].strip()
                else:
                    doc_number = nxt
                break
            # 「四、标准及标准目录」里的 #### 直接挂在 scope 下 —— 造一个匿名 section
            if cur_section is None and cur_scope is not None:
                cur_section = {"title": None, "page": None, "docs": []}
                cur_scope["sections"].append(cur_section)
            if cur_section is not None:
                cur_section["docs"].append(
                    {"title": title, "doc_number": doc_number, "page": page}
                )

    return scopes


# OCR 形近字 / 漏字修正表 —— 目录侧的错误写法 → 正确写法。
# 实测这些都是 OCR 在**目录页**上出的错(正文页反而是对的),
# 所以修正的是「目录读数」而不是「文档读数」。
OCR_FIXES = (
    ("深人", "深入"),
    ("投人品", "投入品"),
    ("反当动物", "反刍动物"),
    ("豆粘", "豆粕"),
    ("粘类", "粕类"),
    ("氨苯肿酸", "氨苯胂酸"),
    ("洛克沙肿", "洛克沙胂"),
    ("约品", "药品"),
    ("喹乙醇、氨苯", "乙醇、氨苯"),
    ("一2030", "—2030"),
    ("舔砖", "微量元素砖"),
)


def norm(s: str) -> str:
    """归一化: 修 OCR 错字 + 去所有标点空白, 只留可比对的字符。"""
    if not s:
        return ""
    s = s.strip()
    for bad, good in OCR_FIXES:
        s = s.replace(bad, good)
    # 剥掉文档 title 开头可能带的序号前缀(如 "38_质检总局关于...")
    # ⚠️ 只在数字+下划线开头时剥 —— 否则会误伤正常标题
    s = re.sub(r"^\d{1,4}_", "", s)
    # 去掉标点(目录用「、」, 文档用「，」, 还有空格差异)和所有空白
    s = re.sub(r"[，。、；：？！,.;:?!（）()《》「」\[\]【】—\-_\s　]+", "", s)
    return s


def similarity(a: str, b: str) -> float:
    """两个归一化标题的相似度(0~1)。"""
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def build_index(documents):
    """
    把真实文档按 (scope, section) 建索引, 同组内按 doc_id 里的序号排。
    doc_id 形如: 02制度文件_03_（三）进口登记和出口服务_38_质检总局...
    """
    from collections import defaultdict

    grouped = defaultdict(list)
    for d in documents:
        if d.get("is_toc"):
            continue
        grouped[(d.get("scope", ""), d.get("section", ""))].append(d)

    for key in grouped:
        # doc_id 末段的序号: ..._38_标题 -> 38
        def seq(d):
            m = re.search(r"_(\d+)_", d["doc_id"])
            return int(m.group(1)) if m else 0

        grouped[key].sort(key=seq)
    return grouped


def main():
    if not CATALOG_MD.exists():
        raise SystemExit(f"找不到目录源文件: {CATALOG_MD}")
    if not DOCS_JSON.exists():
        raise SystemExit(f"找不到 documents.json: {DOCS_JSON}")

    scopes = parse_catalog(CATALOG_MD.read_text(encoding="utf-8"))
    documents = json.loads(DOCS_JSON.read_text(encoding="utf-8"))
    grouped = build_index(documents)

    # section 名 -> 该 section 下按序排好的文档
    used = set()
    matched = 0
    unmatched = []

    for sc in scopes:
        scope_key = SCOPE_MAP.get(sc["title"].split("、", 1)[-1].strip())
        sc["scope_key"] = scope_key
        for sec in sc["sections"]:
            # 该 scope 下所有 section 的文档池
            pool = []
            for (s, sect), docs in grouped.items():
                if s == scope_key:
                    pool.append((sect, docs))

            # 优先按 section 标题精确匹配; 匹配不到再按 scope 下序号兜底
            target = norm(sec["title"]) if sec["title"] else ""
            cand = None
            for sect, docs in pool:
                if target and norm(sect.split("_", 1)[-1]) == target:
                    cand = docs
                    break
            if cand is None and not target:
                # 匿名 section(标准目录): 取 scope 下所有没被别的 section 用过的
                cand = []
                for sect, docs in pool:
                    cand.extend([d for d in docs if d["doc_id"] not in used])
                cand.sort(key=lambda d: d["doc_id"])

            if cand is None:
                cand = []

            for doc in sec["docs"]:
                key = norm(doc["title"])
                hit = None
                by = None
                for d in cand:
                    if d["doc_id"] in used:
                        continue
                    if norm(d["title"]) == key:
                        hit = d
                        by = "title"
                        break
                if hit is None:
                    # 兜底 1: 去掉尾部括号/编号后再比一次
                    k2 = re.sub(r"[（(].*?[）)]", "", key)
                    for d in cand:
                        if d["doc_id"] in used:
                            continue
                        if norm(d["title"]) == k2 or (k2 and norm(d["title"]).startswith(k2)):
                            hit = d
                            by = "title_fuzzy"
                            break
                if hit is None and doc.get("doc_number"):
                    # 兜底 1.5: 用文号里的标准号匹配
                    # 例: 目录「饲料标签 / GB10648-2013」 vs 文档
                    #     「GB 10648—2013《饲料标签》国家标准第1号修改单」
                    #     —— title 完全不同, 但文号里的标准号一致
                    std = re.sub(r"[^0-9A-Za-z]", "", doc["doc_number"])
                    if std:
                        for d in cand:
                            if d["doc_id"] in used:
                                continue
                            dt = re.sub(r"[^0-9A-Za-z]", "", norm(d["title"]))
                            if std and (std in dt or dt.startswith(std)):
                                hit = d
                                by = "doc_number"
                                break
                if hit is None:
                    # 兜底 2: 相似度匹配(OCR 漏字/形近字导致 title 不完全一致)
                    # 阈值 0.78 —— 实测未匹配的 18 条里, 正确项相似度 0.80~1.00,
                    # 而错误项最高只到 0.63, 区分度足够。
                    best, best_r = None, 0.0
                    for d in cand:
                        if d["doc_id"] in used:
                            continue
                        r = similarity(key, norm(d["title"]))
                        if r > best_r:
                            best, best_r = d, r
                    if best is not None and best_r >= 0.78:
                        hit = best
                        by = f"similarity:{best_r:.2f}"
                if hit is not None:
                    used.add(hit["doc_id"])
                    matched += 1
                    doc["doc_id"] = hit["doc_id"]
                    doc["matched"] = True
                    doc["match_by"] = by
                    # 用真实文档的 title/doc_number 覆盖 OCR 目录里的(文档侧更准)
                    doc["title"] = hit["title"]
                    if hit.get("doc_number"):
                        doc["doc_number"] = hit["doc_number"]
                    doc["article_count"] = hit.get("article_count")
                    doc["chapter_count"] = hit.get("chapter_count")
                else:
                    doc["matched"] = False
                    doc["match_by"] = None
                    unmatched.append((sc["title"], sec["title"], doc["title"]))

    # 未被目录收录的真实文档 —— 补进对应 section 末尾
    for (scope_key, sect), docs in grouped.items():
        leftover = [d for d in docs if d["doc_id"] not in used]
        if not leftover:
            continue
        # 找对应的 scope/section
        for sc in scopes:
            if sc.get("scope_key") != scope_key:
                continue
            target = norm(sect.split("_", 1)[-1])
            tgt_sec = None
            for sec in sc["sections"]:
                if sec["title"] and norm(sec["title"]) == target:
                    tgt_sec = sec
                    break
            if tgt_sec is None:
                tgt_sec = {"title": sect.split("_", 1)[-1], "page": None, "docs": []}
                sc["sections"].append(tgt_sec)
            for d in leftover:
                used.add(d["doc_id"])
                tgt_sec["docs"].append(
                    {
                        "title": d["title"],
                        "doc_number": d.get("doc_number"),
                        "page": None,
                        "doc_id": d["doc_id"],
                        "matched": True,
                        "match_by": "residual",
                        "article_count": d.get("article_count"),
                        "chapter_count": d.get("chapter_count"),
                    }
                )

    total = sum(len(s["docs"]) for sc in scopes for s in sc["sections"])
    out = {
        "scopes": scopes,
        "stats": {
            "scopes": len(scopes),
            "sections": sum(len(sc["sections"]) for sc in scopes),
            "docs": total,
            "matched": total - len(unmatched),
            "unmatched": len(unmatched),
            "documents_total": len([d for d in documents if not d.get("is_toc")]),
        },
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"✅ {OUT_JSON}")
    print(f"   scope {out['stats']['scopes']} · section {out['stats']['sections']} · "
          f"文件 {out['stats']['docs']} (匹配 {out['stats']['matched']} / 未匹配 {out['stats']['unmatched']})")
    if unmatched:
        print("\n   ⚠️ 未匹配(保留在目录里但不给链接):")
        for sc, sec, t in unmatched[:40]:
            print(f"      [{sc} / {sec}] {t[:60]}")
    return out


if __name__ == "__main__":
    main()
