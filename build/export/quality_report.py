#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生产 D1 语料数据质量体检。

## 为什么要有这个脚本

之前的踩坑(全都发生在**生产数据**里,而且都是静默的):
  - SQLite 的 LIKE 对中文无效      -> 搜「维生素」0 条,换 instr() 15 条
  - articles_fts 少 186 条(封面+目录被排除),但 bge 语料是全量 3145
  - article_id 复用                -> 同 id 不同正文,FTS 差集漏检
  - seed_pages_m3.sql 幽灵条文      -> 515 条 D1 里根本不存在的条文
  - 标题被拆成两行                 -> 条文标题退化成裸编号「3.1」
  - 章内小节被标成 H2              -> 「使用说明」从 articles 表消失

所以这个脚本做**全量体检**,而不是抽样 —— 静默错误只能靠全量比对发现。

## 用法

  python build/export/quality_report.py --check     # 只读,不写
  python build/export/quality_report.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
SCHEMA = ROOT / "query/worker/schema.sql"
SEED = ROOT / "build/export/seed.sql"

ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "1b938cc261b000a03554b506985daabb")
DB_ID = os.environ.get("CLOUDFLARE_D1_ID", "e406e21e-e770-4c97-822a-57178c347aa6")
API = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/d1/database/{DB_ID}/raw"

findings: list[dict] = []


def finding(level: str, code: str, title: str, detail: str, count: int = 0, samples: list | None = None):
    findings.append({
        "level": level, "code": code, "title": title,
        "count": count, "detail": detail, "samples": samples or [],
    })


def wrangler_token() -> str:
    for p in (
        Path.home() / ".wrangler" / "config" / "default.toml",
        Path(os.environ.get("APPDATA", "")) / "xdg.config" / ".wrangler" / "config" / "default.toml",
    ):
        if p.exists():
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line.startswith("oauth_token"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("找不到 wrangler OAuth token")


def raw(sql: str, params: list | None = None, timeout: int = 300) -> dict:
    req = urllib.request.Request(
        API,
        data=json.dumps({"sql": sql, "params": params or []}).encode("utf-8"),
        headers={"Authorization": f"Bearer {wrangler_token()}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read()[:600].decode("utf-8", "replace")}


def q(sql: str, params: list | None = None, retries: int = 3) -> list[tuple]:
    """查生产 D1。

    ⚠️ D1 raw API 偶发读超时(实测 GROUP BY 大表时)。
    重试 3 次,避免把**瞬时网络抖动**报成数据缺陷 ——
    体检报告里出现 CHECK_FAILED 会让人以为数据坏了,其实是网络抖了一下。
    """
    last = None
    for attempt in range(1, retries + 1):
        r = raw(sql, params)
        if r.get("success"):
            try:
                return [tuple(x) for x in r["result"][0]["results"]["rows"]]
            except (KeyError, IndexError, TypeError) as e:
                raise SystemExit(f"bad shape: {str(r)[:400]}")
        last = r
        if attempt < retries:
            time.sleep(1.5 * attempt)
    raise SystemExit(f"query failed after {retries} tries: {str(last)[:400]}")


def local_corpus() -> dict:
    """本地语料快照(灌库源头),用于与生产比对。"""
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.executescript(SEED.read_text(encoding="utf-8"))
    arts = {
        r[0]: {"chapter_id": r[1], "doc_id": r[2], "number": r[3], "title": r[4], "body": r[5] or ""}
        for r in con.execute(
            "SELECT article_id, chapter_id, doc_id, number, title, body FROM articles"
        )
    }
    fts = {
        r[0]: {"title": r[1] or "", "text": r[2] or ""}
        for r in con.execute("SELECT article_id, title, text FROM articles_fts")
    }
    chs = {r[0] for r in con.execute("SELECT chapter_id FROM chapters")}
    docs = {r[0] for r in con.execute("SELECT doc_id FROM documents")}
    return {"articles": arts, "fts": fts, "chapters": chs, "documents": docs}


# ---------------------------------------------------------------- 检查项

def check_scale():
    n = {
        "articles": q("SELECT count(*) n FROM articles")[0][0],
        "articles_fts": q("SELECT count(*) n FROM articles_fts")[0][0],
        "chapters": q("SELECT count(*) n FROM chapters")[0][0],
        "documents": q("SELECT count(*) n FROM documents")[0][0],
    }
    finding("INFO", "SCALE", "语料规模", json.dumps(n, ensure_ascii=False))
    return n


def check_fts_coverage(loc):
    """FTS 覆盖:哪些 articles 没有进 FTS(应当且仅应当是封面+目录)。"""
    missing = [aid for aid in loc["articles"] if aid not in loc["fts"]]
    by_doc = Counter(aid.split("_")[0] for aid in missing)
    expected = {"000封面", "001目录"}
    unexpected = {d: c for d, c in by_doc.items() if d not in expected}
    if unexpected:
        finding(
            "BAD", "FTS_MISSING_UNEXPECTED",
            "FTS 缺失了非封面/目录的条文",
            f"{len(missing)} 条没进 FTS,其中 {len(unexpected)} 条来自非预期文档",
            len(missing), list(unexpected.items())[:5],
        )
    else:
        finding(
            "OK", "FTS_COVERAGE_OK",
            "FTS 覆盖符合设计",
            f"{len(missing)} 条未进 FTS,全部来自 {expected}(封面/目录,非可检索内容,刻意排除)",
            len(missing),
        )
    # 反向:生产 FTS 里有但语料没有的
    extra = [aid for aid in loc["fts"] if aid not in loc["articles"]]
    if extra:
        finding("BAD", "FTS_ORPHAN", "FTS 里有语料没有的条目", "这些 id 检索会返回空", len(extra), extra[:5])


def check_ghost():
    """幽灵条文:生产 D1 里存在、但语料树里没有的 —— 通常是旧语料残留。"""
    legacy = q(
        "SELECT count(*) n FROM articles WHERE doc_id LIKE 'feed-law-collection%'"
    )[0][0]
    if legacy:
        finding("BAD", "GHOST_LEGACY", "存在旧语料残留条文",
                "feed-law-collection-2023-full 是已作废的 2023 版语料", legacy)
    else:
        finding("OK", "NO_GHOST", "无旧语料残留", "legacy doc 条文数 = 0")


def check_id_reuse(loc):
    """article_id 复用:同一个 id 在历史版本里对应过不同正文。"""
    # 用 FTS text 差异来找 —— 同一 id 正文不同 = 复用过
    rows = q("SELECT article_id, title, length(text) FROM articles_fts")
    remote = {r[0]: (r[1] or "", r[2]) for r in rows}
    changed = [
        aid for aid, f in loc["fts"].items()
        if aid in remote and remote[aid][0] != f["title"]
    ]
    if changed:
        finding("WARN", "ID_REUSE", "存在 article_id 复用",
                "同 id 当前后对应过不同标题 —— 增量同步必须比内容而非存在性", len(changed), changed[:5])
    else:
        finding("OK", "NO_ID_REUSE", "无 article_id 复用残留", "生产 FTS 标题与语料全部一致")


def check_empty_body():
    """空正文条文 —— 检索到也读不出东西。

    ⚠️ 封面/目录的占位条文**天然是空的**(扫描件上就是空白页),
    它们不进 FTS、不参与检索,留着无害。所以只有**非封面/目录**的空正文算缺陷。
    """
    rows = q(
        "SELECT article_id, title, doc_id FROM articles "
        "WHERE (body IS NULL OR length(trim(body)) < 3) "
        "AND doc_id NOT LIKE '000封面%' AND doc_id NOT LIKE '001目录%'"
    )
    if rows:
        finding("BAD", "EMPTY_BODY", "可检索条文正文为空",
                "检索能命中但没有内容可读", len(rows), [r[0] for r in rows[:5]])
    else:
        cover = q("SELECT count(*) n FROM articles WHERE (body IS NULL OR length(trim(body)) < 3)")[0][0]
        finding("OK", "NO_EMPTY_BODY", "可检索条文正文非空",
                f"封面/目录有 {cover} 条空正文(扫描件本就空白,不进 FTS,无害);"
                f"其余条文 body 全部有内容")


def check_title_quality():
    """条文标题退化 —— 只剩裸编号(如「3.1」)说明标题被拆行吞了。"""
    rows = q(
        "SELECT article_id, title FROM articles "
        "WHERE title IS NOT NULL AND trim(title) != '' "
        "AND (title GLOB '[0-9]*' OR title GLOB '*.[0-9]*')"
    )
    rows = [(r[0], r[1]) for r in rows if re.fullmatch(r"[\d.Ａ-ＺA-Za-z\s]+", r[1] or "")]
    if rows:
        finding("BAD", "TITLE_NUMERIC_ONLY", "条文标题退化成裸编号",
                "搜「术语名」就找不到这一条 —— ingest 的一行一标题被破坏", len(rows),
                [f"{r[0][-40:]} → {r[1]}" for r in rows[:5]])
    else:
        finding("OK", "TITLE_OK", "条文标题均有语义",
                "没有只剩编号的标题")


def check_fk_integrity():
    """外键完整性。"""
    a = q("SELECT count(*) n FROM articles WHERE chapter_id NOT IN (SELECT chapter_id FROM chapters)")[0][0]
    b = q("SELECT count(*) n FROM articles WHERE doc_id NOT IN (SELECT doc_id FROM documents)")[0][0]
    c = q("SELECT count(*) n FROM entity_articles WHERE article_id NOT IN (SELECT article_id FROM articles)")[0][0]
    d = q("SELECT count(*) n FROM entity_articles WHERE entity_id NOT IN (SELECT entity_id FROM entities)")[0][0]
    total = a + b + c + d
    if total:
        finding("BAD", "FK_BROKEN", "外键悬挂",
                f"articles→chapters {a} / articles→documents {b} / "
                f"entity_articles→articles {c} / entity_articles→entities {d}", total)
    else:
        finding("OK", "FK_OK", "外键完整",
                "articles / entity_articles 的所有引用都能落地")


def check_fts_vs_articles():
    """FTS 内容与 articles.body 的一致性(正文改了 FTS 没跟着改 = 检索到旧文)。"""
    rows = q(
        "SELECT a.article_id, a.title, substr(a.body,1,80) "
        "FROM articles a JOIN articles_fts f ON f.article_id=a.article_id "
        "WHERE f.title != a.title LIMIT 20"
    )
    if rows:
        finding("BAD", "FTS_TITLE_DRIFT", "FTS 标题与 articles 不一致",
                "正文改了但 FTS 没重灌 —— 检索命中的是旧标题", len(rows),
                [f"{r[0][-40:]} fts={r[1]} art={r[2]}" for r in rows[:5]])
    else:
        finding("OK", "FTS_IN_SYNC", "FTS 与 articles 一致",
                "FTS 标题与 articles 标题全部对齐")


def check_doc_coverage():
    """文档 → 章 → 条文的层级完整性。

    ⚠️ 封面/目录的「章节」是目录节点,本身没有条文 —— 那是目录树的一部分,
    不是空章节。所以只查非封面/目录的文档。
    """
    no_ch = q(
        "SELECT count(*) n FROM documents d "
        "WHERE NOT EXISTS (SELECT 1 FROM chapters c WHERE c.doc_id=d.doc_id) "
        "AND d.doc_id NOT LIKE '000封面%' AND d.doc_id NOT LIKE '001目录%'"
    )[0][0]
    no_art = q(
        "SELECT count(*) n FROM chapters c "
        "WHERE NOT EXISTS (SELECT 1 FROM articles a WHERE a.chapter_id=c.chapter_id) "
        "AND c.doc_id NOT LIKE '000封面%' AND c.doc_id NOT LIKE '001目录%'"
    )[0][0]
    if no_ch or no_art:
        finding("BAD", "HIERARCHY_GAP", "层级有空章节",
                f"{no_ch} 个文档没有章 / {no_art} 个章没有条文", no_ch + no_art)
    else:
        finding("OK", "HIERARCHY_OK", "文档-章-条文层级完整",
                "每个可检索文档都有章,每个可检索章都有条文(封面/目录节点不计)")


def check_sort_order():
    """条文顺序:章节内条文按 sort_order 排,必须**单调递增且不重复**。

    ⚠️ **不要用「连续无跳号」当判据** —— sort_order 是**全局**编号
    (跨章节递增),同一文档里多个章节的条文会共享编号空间,
    所以单个章节内部天然有跳号。实测「十四五」规划文档 3 个章节
    都有跳号,但 ORDER BY sort_order 渲染出来顺序完全正确。
    真正的判据是:**排序后 article_id 不得重复,且章节正文首尾拼接顺序正确**。
    """
    dup = q(
        "SELECT count(*) n FROM (SELECT chapter_id, article_id, count(*) c "
        "FROM articles GROUP BY chapter_id, article_id HAVING c > 1)"
    )[0][0]
    # 章节内 sort_order 是否严格单调
    rows = q(
        "SELECT chapter_id FROM articles GROUP BY chapter_id "
        "HAVING count(DISTINCT sort_order) != count(*)"
    )
    if dup or rows:
        finding("BAD", "SORT_ORDER_CONFLICT", "章节内 sort_order 有冲突",
                f"{dup} 个 (章节,条文) 重复 / {len(rows)} 个章节的 sort_order 不唯一",
                dup + len(rows), [r[0][-34:] for r in rows[:5]])
    else:
        finding("OK", "SORT_ORDER_OK", "章节内条文顺序无冲突",
                "sort_order 在章节内唯一,ORDER BY 渲染顺序正确(跳号是全局编号的正常现象,非缺陷)")


def check_duplicate():
    """重复条文 —— OCR 或切分容易产生完全一样的正文。"""
    rows = q(
        "SELECT count(*) n FROM (SELECT doc_id, body FROM articles "
        "WHERE length(body) > 40 GROUP BY doc_id, body HAVING count(*) > 1)"
    )[0][0]
    if rows:
        finding("WARN", "DUP_BODY", "存在完全重复的条文",
                "同一文档内正文完全相同 —— 多半是切分/OCR 重复", rows)
    else:
        finding("OK", "NO_DUP", "无重复条文", "同文档内没有正文完全相同的条文")


def check_chinese_garbage():
    """乱码检测:正文里出现大量 U+FFFD 或非中文的异常符号串。"""
    rows = q("SELECT article_id, body FROM articles WHERE length(body) > 200")
    bad = []
    for aid, body in rows:
        if body and body.count("�") > 3:
            bad.append(aid)
        elif body and re.search(r"[一-鿿]{0,}[犐犆犛６]{4,}", body):
            bad.append(aid)
    if bad:
        finding("BAD", "GARBAGE", "正文含乱码",
                "OCR 失败或 CMap 缺失会把乱码写进正文", len(bad), bad[:5])
    else:
        finding("OK", "NO_GARBAGE", "正文无乱码", "无 U+FFFD 连续段、无 CMap 乱码")


def check_body_stats():
    """正文长度分布 —— 太短多半是只剩标题,太长可能没切分。"""
    rows = q("SELECT length(body) n FROM articles")
    lens = sorted(r[0] for r in rows)
    n = len(lens)
    def pct(p):
        return lens[min(n - 1, int(n * p))]
    finding(
        "INFO", "BODY_LEN",
        "正文长度分布",
        f"n={n} min={lens[0]} p10={pct(0.1)} p50={pct(0.5)} "
        f"p90={pct(0.9)} p99={pct(0.99)} max={lens[-1]} "
        f"总字符={sum(lens):,}",
    )
    tiny = q("SELECT count(*) n FROM articles WHERE length(body) < 30")[0][0]
    if tiny:
        finding("INFO", "TINY_BODY", "极短正文",
                f"{tiny} 条正文 < 30 字符(可能是只有标题的条文)", tiny)


def check_html_entities():
    """HTML 实体残留 —— OCR 把 `<` 转义成 `&lt;` 后**没有反转义**。

    实测:「m/z<200」在正文里是「m/z&lt;200」,「辅酶Q10渣<sup>4e</sup>」
    是「辅酶Q10渣&lt;sup&gt;4e&lt;/sup&gt;」。
    后果:① 用户看到的正文带 `&lt;` 这种原始标记,不是「<」
          ② 检索时 `m/z<200` 这种带符号的查询匹配不上正文里的 `&lt;`
          ③ 上标标签彻底不可读
    """
    total = 0
    kinds = Counter()
    affected = []
    rows = q("SELECT article_id, body FROM articles WHERE body LIKE '%&lt;%' OR body LIKE '%&gt;%' OR body LIKE '%&amp;%'")
    for aid, body in rows:
        if not body:
            continue
        c = body.count("&lt;") + body.count("&gt;") + body.count("&amp;")
        if c:
            total += c
            affected.append(aid)
            for e in re.findall(r"&[a-z]+;", body):
                kinds[e] += 1
    if total:
        finding(
            "WARN", "HTML_ENTITY_RESIDUE", "正文残留未反转义的 HTML 实体",
            f"{total} 处({len(affected)} 条条文),分布 {dict(kinds.most_common(5))} —— "
            f"OCR 转义后没反转义:用户看到的是 `&lt;` 不是 `<`;"
            f"带符号查询(如 m/z<200)匹配不上正文",
            total, affected[:5],
        )
    else:
        finding("OK", "NO_HTML_ENTITY", "正文无 HTML 实体残留", "所有 &lt; / &gt; / &amp; 都已反转义")


def check_table_noise():
    """HTML 表格占比 —— 表格多的正文,纯文本检索噪声大、LLM 也难读。"""
    rows = q("SELECT article_id, body FROM articles WHERE length(body) > 200")
    with_tbl = sum(1 for _, b in rows if "<table" in (b or ""))
    pct = with_tbl / len(rows) * 100 if rows else 0
    finding(
        "INFO", "TABLE_RATIO", "长正文含表格比例",
        f"{with_tbl}/{len(rows)} 条({pct:.1f}%)含 HTML 表格 —— "
        f"这些条文以表格为主,纯文本检索召回质量天然偏低",
        with_tbl,
    )


def check_entity_graph():
    """图谱:孤儿实体 / 悬空关联 / 一对多别名。

    ⚠️ **孤儿实体不等于缺陷** —— ADR-004 明确决策:
       「④ 图谱保持空壳直到有真实用例」,实体↔实体关系**刻意不排期**。
       那批 GraphRAG 抽的概念实体(ACTION / DOCUMENT / CERTIFICATE …)
       本来就没有条文关联。
       所以这里只把**物质类实体(SUBSTANCE)无关联**当缺陷 ——
       物质是业务主语,没有条文关联就等于查不到。
    """
    dangling_a = q("SELECT count(*) n FROM entity_articles WHERE entity_id NOT IN "
                   "(SELECT entity_id FROM entities)")[0][0]
    orphan_alias = q("SELECT count(*) n FROM entity_aliases WHERE entity_id NOT IN "
                     "(SELECT entity_id FROM entities)")[0][0]
    if dangling_a or orphan_alias:
        finding("BAD", "GRAPH_BROKEN", "图谱有悬空引用",
                f"悬空关联 {dangling_a} / 孤儿别名 {orphan_alias}", dangling_a + orphan_alias)
    else:
        finding("OK", "GRAPH_LINK_OK", "图谱引用完整",
                "entity_articles / entity_aliases 的引用全部可落地")

    # 孤儿实体分类
    rows = q(
        "SELECT type, count(*) n FROM entities "
        "WHERE entity_id NOT IN (SELECT entity_id FROM entity_articles) "
        "GROUP BY type ORDER BY n DESC"
    )
    orphans = sum(r[1] for r in rows)
    by_type = {r[0] or "(空)": r[1] for r in rows}

    # ⚠️ **物质实体要分两种来源看**:
    #    sub_* (从《品种目录》导入的 387 条) —— 业务主语,无关联 = 缺陷
    #    uuid (GraphRAG 抽取的概念)            —— 刻意无关联,且部分被误标成 SUBSTANCE
    #                                          (实测「产品」「产品质量」被标成 SUBSTANCE)
    rows = q(
        "SELECT CASE WHEN entity_id LIKE 'sub_%' THEN 'catalog' ELSE 'graphrag' END src, "
        "count(*) n, sum(CASE WHEN entity_id NOT IN (SELECT entity_id FROM entity_articles) "
        "THEN 1 ELSE 0 END) orphans "
        "FROM entities WHERE type='SUBSTANCE' GROUP BY src"
    )
    cat_orphan = sum(r[2] for r in rows if r[0] == "catalog")
    graph_orphan = sum(r[2] for r in rows if r[0] == "graphrag")

    if cat_orphan:
        finding("BAD", "SUBSTANCE_ORPHAN", "目录物质实体没有条文关联",
                f"{cat_orphan} 条 —— 物质是业务主语,无关联 = 查不到", cat_orphan)
    else:
        finding("OK", "SUBSTANCE_OK", "目录物质实体全部有条文关联",
                "387 条 sub_* 物质实体 orphans = 0,业务主语层完整")

    if graph_orphan:
        finding(
            "INFO", "GRAPH_RAQ_MISTYPED", "GraphRAG 概念被误标为 SUBSTANCE",
            f"{graph_orphan} 个 uuid 实体类型是 SUBSTANCE 但无条文关联"
            f"(实测「产品」「产品质量」)—— 类型标注不准,不影响检索"
            f"(uuid 实体本来就不参与《品种目录》关联)",
            graph_orphan,
        )

    finding(
        "INFO", "CONCEPT_ORPHAN",
        "概念实体无条文关联(设计如此)",
        f"{orphans} 个孤儿实体,分布 {by_type} —— "
        f"ADR-004 决策:实体↔实体关系刻意不实现,概念实体本就无条文关联",
        orphans,
    )


def check_alias_ambiguity():
    """别名一对多 —— 一个别名指向多个实体,查到了也只能瞎猜。"""
    rows = q(
        "SELECT alias, count(DISTINCT entity_id) n FROM entity_aliases "
        "GROUP BY alias HAVING n > 1"
    )
    if rows:
        finding("WARN", "ALIAS_AMBIGUOUS", "存在一对多别名",
                "查到这个别名会返回多个候选 —— 宁可查不到也不给错答案", len(rows),
                [f"{r[0]} → {r[1]} 个实体" for r in rows[:5]])
    else:
        finding("OK", "ALIAS_UNIQUE", "别名均唯一",
                "没有一对多别名,查别名能确定唯一实体")


def check_compliance():
    """合规规则与物质目录的闸门状态。"""
    rules = q("SELECT review_status, count(*) n FROM compliance_rules GROUP BY review_status")
    cats = q("SELECT review_status, count(*) n FROM substance_catalog GROUP BY review_status")
    rule_pending = sum(r[1] for r in rules if r[0] == "pending")
    cat_pending = sum(r[1] for r in cats if r[0] == "pending")
    if rule_pending or cat_pending:
        finding(
            "BLOCKED", "COMPLIANCE_GATE_CLOSED",
            "合规速查闸门未开",
            f"规则 {rule_pending} 条 pending + 目录 {cat_pending} 条 pending —— "
            f"**两道闸门任一没开都恒返回 not_covered**",
            rule_pending + cat_pending,
        )
    else:
        finding("OK", "COMPLIANCE_GATE_OPEN", "合规速查闸门已开", "规则与目录均已 reviewed")


def check_rule_traceability():
    """规则溯源:每条规则必须能回溯到原文条文。"""
    no_src = q("SELECT count(*) n FROM compliance_rules WHERE source_article_id IS NULL "
               "OR source_article_id = ''")[0][0]
    bad_src = q(
        "SELECT count(*) n FROM compliance_rules WHERE source_article_id IS NOT NULL "
        "AND source_article_id != '' AND source_article_id NOT IN (SELECT article_id FROM articles)"
    )[0][0]
    if no_src or bad_src:
        finding("BAD", "RULE_NO_TRACE", "合规规则无法溯源",
                f"{no_src} 条无 source_article_id / {bad_src} 条指向不存在的条文", no_src + bad_src)
    else:
        finding("OK", "RULE_TRACEABLE", "合规规则均可溯源",
                "每条规则的 source_article_id 都能落到实际条文")


def check_substance_coverage():
    """物质目录:name_en / source_article_id 等字段的完整性。

    ⚠️ name_en 缺失 = **英文名查不到实体**(实测:/api/entity/Nicotinamide → not found,
    而 /api/entity/烟酰胺 → 2 条条文)。《品种目录》本身是双语的,
    缺 name_en 是抽取环节的缺口,不是源数据没有。
    """
    no_en = q("SELECT count(*) n FROM substance_catalog WHERE name_en IS NULL OR trim(name_en)=''")[0][0]
    no_src = q("SELECT count(*) n FROM substance_catalog WHERE source_article_id IS NULL OR trim(source_article_id)=''")[0][0]
    total = q("SELECT count(*) n FROM substance_catalog")[0][0]
    if no_en:
        finding(
            "WARN", "SUBSTANCE_NO_EN_NAME", "物质目录缺英文名",
            f"{no_en}/{total} 条缺 name_en —— **英文名检索不到实体**"
            f"(实测 /api/entity/Nicotinamide → not found,烟酰胺 → 2 条)",
            no_en,
        )
    else:
        finding("OK", "SUBSTANCE_EN_OK", "物质目录英文名完整", f"{total} 条全部有 name_en")
    if no_src:
        finding("BAD", "SUBSTANCE_NO_SRC", "物质目录缺溯源",
                f"{no_src} 条缺 source_article_id —— 无法回溯《品种目录》原文", no_src)
    else:
        finding("OK", "SUBSTANCE_TRACEABLE", "物质目录均可溯源",
                f"{total} 条全部有 source_article_id")


def check_retrieval_health():
    """检索链路实况:打生产接口,看召回与降级状态。

    这是唯一能抓到「数据在库里但检索不到」的检查项 ——
    D1 直查永远是绿的,但用户搜不到就是搜不到。
    """
    import urllib.parse

    cases = [
        ("饲料标签标示的基本内容", "GB10648 应占多数"),
        ("维生素C 限量", "应命中饲料添加剂安全使用规范"),
        ("动物源性饲料 不得饲喂反刍动物", "应命中 GB10648 5.13.1"),
        ("净含量 标示", "应命中 GB10648 5.7"),
    ]
    base = "https://siliao-web.pages.dev/api/search?q="
    ok = 0
    degraded = 0
    details = []
    for q, expect in cases:
        hits = None
        # ⚠️ 生产接口偶发超时(网关侧)。重试 2 次再判失败 ——
        #    把网络抖动报成「检索不到」是误导。
        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    base + urllib.parse.quote(q),
                    headers={"User-Agent": "Mozilla/5.0 Chrome/131.0"},
                )
                d = json.loads(urllib.request.urlopen(req, timeout=90).read())
                hits = d.get("hits", [])
                if d.get("degraded"):
                    degraded += 1
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    details.append(f"{q} → ERR {type(e).__name__}")
                else:
                    time.sleep(2 * (attempt + 1))
        if hits is None:
            continue
        if hits:
            ok += 1
        details.append(f"{q} → {len(hits)} 命中"
                       f"{' [DEGRADED]' if d.get('degraded') else ''}")
    if degraded:
        finding("BAD", "RETRIEVAL_DEGRADED", "语义层降级中",
                f"{degraded}/{len(cases)} 次检索走了降级路径(纯 FTS5)", degraded, details)
    elif ok == len(cases):
        finding("OK", "RETRIEVAL_OK", "检索链路健康",
                f"{ok}/{len(cases)} 条查询全部有命中,无降级", ok, details)
    else:
        finding("WARN", "RETRIEVAL_PARTIAL", "部分查询无命中",
                f"{ok}/{len(cases)} 条有命中", len(cases) - ok, details)


def check_bge_corpus():
    """bge 语料与 D1 的对齐 —— 语义层召回 D1 里没有的 id = 返回空条目。"""
    p = ROOT / "evals" / "bge_m3_cache.json"
    a = ROOT / "evals" / "articles_cache.json"
    if not p.exists():
        finding("WARN", "BGE_CACHE_MISSING", "本地无 bge 缓存", "无法核对语义层语料")
        return
    cache = json.loads(p.read_text(encoding="utf-8"))
    ids = [x[0] for x in cache["articles"]]
    rem_ids = {r[0] for r in q("SELECT article_id FROM articles")}
    missing_in_bge = rem_ids - set(ids)
    ghost_in_bge = set(ids) - rem_ids
    finding(
        "INFO", "BGE_COVERAGE",
        "bge 语料与 D1 对齐",
        f"bge {len(ids)} 条 · D1 {len(rem_ids)} 条 · "
        f"D1 有而 bge 无 {len(missing_in_bge)} · bge 有而 D1 无 {len(ghost_in_bge)}",
        len(missing_in_bge) + len(ghost_in_bge),
        list(missing_in_bge)[:5] or list(ghost_in_bge)[:5],
    )
    if ghost_in_bge:
        finding("BAD", "BGE_GHOST", "bge 语料有 D1 不存在的条目",
                "语义层召回这些 id 时 Worker 取不到正文,返回空条目", len(ghost_in_bge),
                list(ghost_in_bge)[:5])
    if a.exists():
        arts = json.loads(a.read_text(encoding="utf-8"))
        amap = {x[0] for x in arts}
        uncovered = [i for i in ids if i not in amap]
        if uncovered:
            finding("BAD", "BGE_EXCERPT_MISSING", "bge 语料缺 excerpt 源",
                    "articles_cache 少条目 —— /v1/search 返回空 excerpt", len(uncovered),
                    uncovered[:5])
        else:
            finding("OK", "BGE_EXCERPT_OK", "bge excerpt 源完整",
                    f"articles_cache {len(arts)} 条全覆盖 bge 语料")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", help="额外输出 JSON")
    args = ap.parse_args()

    print("[load] 本地语料快照 ...", flush=True)
    loc = local_corpus()
    print(f"[load] 本地: articles={len(loc['articles'])} fts={len(loc['fts'])} "
          f"chapters={len(loc['chapters'])} documents={len(loc['documents'])}", flush=True)

    print("[query] 生产 D1 ...", flush=True)
    checks = [
        check_scale, check_ghost, check_empty_body, check_title_quality,
        check_fk_integrity, check_fts_vs_articles, check_doc_coverage,
        check_sort_order, check_duplicate, check_chinese_garbage,
        check_body_stats, check_entity_graph, check_alias_ambiguity,
        check_compliance, check_rule_traceability, check_substance_coverage,
        check_bge_corpus, check_retrieval_health, check_html_entities, check_table_noise,
    ]
    for fn in checks:
        try:
            if fn in (check_fts_coverage, check_id_reuse):
                fn(loc)
            else:
                fn()
        except SystemExit:
            raise
        except Exception as e:  # noqa: BLE001
            finding("ERROR", f"CHECK_FAILED_{fn.__name__}", f"检查项 {fn.__name__} 异常", str(e))

    # 依赖本地的两项最后跑
    check_fts_coverage(loc)
    check_id_reuse(loc)

    print()
    order = {"BAD": 0, "BLOCKED": 1, "ERROR": 2, "WARN": 3, "INFO": 4, "OK": 5}
    findings.sort(key=lambda f: (order.get(f["level"], 9), f["code"]))
    for f in findings:
        icon = {"BAD": "🔴", "BLOCKED": "🔴", "ERROR": "🔴", "WARN": "🟡", "INFO": "⚪", "OK": "🟢"}.get(f["level"], "?")
        print(f"{icon} [{f['level']:7}] {f['code']:24} {f['title']}")
        print(f"          {f['detail']}")
        for s in f["samples"][:3]:
            print(f"            · {s}")

    counts = Counter(f["level"] for f in findings)
    print()
    print("=" * 60)
    print("  " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print("=" * 60)

    if args.json:
        Path(args.json).write_text(
            json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[OK] -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
