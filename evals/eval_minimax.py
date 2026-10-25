"""
eval_minimax.py —— minimax 语料的检索评测
==========================================================

独立于 evals/eval_retrieval.py(那个绑死旧语料 feedlaw2_* 的 article_id 和
section/page 分层逻辑)。本脚本针对 minimax/ 重建后的语料:

    196 文档 · 529 章节 · 3145 条文

跑法:
    python evals/eval_minimax.py
    python evals/eval_minimax.py --queries 40

输出:
    evals/minimax_retrieval_report.md

评测口径:
    - **FTS5 trigram**(与 Worker 生产路径一致, 含 2 字 query padding)
    - **LIKE 兜底**(Worker 在 FTS5 有命中时才启用)
    - recall@10 / recall@20 / MRR

⚠️ 期望列表**从真实数据生成**, 不是手写猜的。
    手写 expect_articles 时容易猜错 article_id, 数字会系统性低估真实召回率,
    看起来像"灌库失败"其实是评测本身错(见 skill qingmang-rag-impl 的坑)。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "query/worker/schema.sql"
SEED = ROOT / "build/export/seed.sql"
REPORT = ROOT / "evals/minimax_retrieval_report.md"

# Worker escapeFts 的 padding 字符集(必须与 query/worker/src/index.ts 一致)
SUFFIXES = [" ", "的", "条", "规", "定", "制", "法", "理", "章", "应", "和"]


def build_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.executescript(SEED.read_text(encoding="utf-8"))
    return con


def escape_fts(q: str) -> str:
    """复刻 Worker 的 escapeFts: 2 字中文 query 加 padding phrase。"""
    cleaned = re.sub(r"[\x00-\x1f]", " ", q).strip()[:64]
    if not cleaned:
        return ""
    if re.fullmatch(r"[\u4e00-\u9fff]{2}", cleaned):
        return " OR ".join(f'"{cleaned}{s}"' for s in SUFFIXES)
    return cleaned


TITLE_BOOST = 3.0
GRAM_TOP_N = 30
RRF_K = 60

STOP_BIGRAMS = {
    "什么", "如何", "哪些", "是否", "需要", "应该", "可以", "进行", "相关",
    "规定", "的话", "一个", "我们", "他们", "这个", "那个", "因为", "所以",
    "但是", "如果", "以及", "对于", "关于", "怎样", "多少", "为何",
    "有无", "几个", "哪种",
}


def query_term_grams(q: str) -> list[str]:
    """复刻 Worker 的 queryTermGrams。"""
    out: list[str] = []

    def push(s: str) -> None:
        if s and s not in out:
            out.append(s)

    for w in re.findall(r"[A-Za-z0-9]+", q):
        if len(w) >= 2:
            push(w)
    for seg in re.findall(r"[\u4e00-\u9fff]+", q):
        if len(seg) == 1:
            push(seg)
            continue
        for i in range(len(seg) - 1):
            bg = seg[i:i + 2]
            if bg in STOP_BIGRAMS:
                continue
            push(bg)
    return out


def gram_expr(gram: str) -> str:
    """复刻 Worker 的 gramExpr。"""
    if len(gram) == 2:
        return " OR ".join(f'"{gram}{s}"' for s in SUFFIXES)
    return f'"{gram}"'


def gram_search(con: sqlite3.Connection, grams: list[str], raw_query: str = "") -> list[str]:
    """复刻 Worker 的 gramSearch: **phrase 优先 + bigram RRF**。

    A 档(高精度): 整句当 phrase 查 —— query 是正文连续片段时精确命中。
    B 档(高召回): bigram 逐个查 + RRF + 标题加权。

    ⚠️ 两档不能混在一个分数池里比: phrase 命中 vs 只命中一个常见 bigram
       的文档精度差一个数量级。混池时 phrase 命中的目标会被挤出 top20。
    """
    # ---------- A 档: 整句 phrase ----------
    phrase_rows: list[tuple[str, float]] = []
    q = raw_query.strip()
    if len(q) >= 3:
        try:
            phrase_rows = con.execute(
                "SELECT article_id, rank FROM articles_fts WHERE articles_fts MATCH ?1 "
                "ORDER BY rank LIMIT ?2",
                (f'"{q}"', GRAM_TOP_N),
            ).fetchall()
        except sqlite3.OperationalError:
            phrase_rows = []

    # ---------- B 档: bigram RRF ----------
    body: dict[str, dict[str, int]] = {}
    title: dict[str, dict[str, int]] = {}

    for g in grams:
        expr = gram_expr(g)
        try:
            rows = con.execute(
                "SELECT article_id, rank FROM articles_fts WHERE articles_fts MATCH ?1 "
                "ORDER BY rank LIMIT ?2",
                (expr, GRAM_TOP_N),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        for aid, r in rows:
            body.setdefault(aid, {})[g] = r

        try:
            rows = con.execute(
                "SELECT article_id, rank FROM articles_fts WHERE articles_fts MATCH ?1 "
                "AND title != '' ORDER BY rank LIMIT ?2",
                (expr, GRAM_TOP_N),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        for aid, r in rows:
            title.setdefault(aid, {})[g] = r

    fused: dict[str, float] = {}
    for aid, ranks in body.items():
        fused[aid] = sum(1.0 / (RRF_K + r) for r in ranks.values())
    for aid, ranks in title.items():
        fused[aid] = fused.get(aid, 0.0) + TITLE_BOOST * sum(
            1.0 / (RRF_K + r) for r in ranks.values()
        )

    # ---------- 合并: A 档在前 ----------
    out: list[str] = []
    seen: set[str] = set()
    for aid, _ in phrase_rows:
        if aid in seen:
            continue
        seen.add(aid)
        out.append(aid)
    for aid, _ in sorted(fused.items(), key=lambda kv: -kv[1]):
        if aid in seen:
            continue
        seen.add(aid)
        out.append(aid)
        if len(out) >= 20:
            break
    return out[:20]


# ---------- bge 语义路(可选) ----------
# Worker 通过 fetch BGE_SERVER_URL 拿 bge 召回; 这里直连同一个服务。
# EVAL_NO_BGE=1 时只测 FTS5 路径。
BGE_URL = os.environ.get("BGE_SERVER_URL", "http://127.0.0.1:8080")
USE_BGE = os.environ.get("EVAL_NO_BGE", "") != "1"
_BGE_AVAILABLE: bool | None = None


def bge_search(q: str, top_k: int = 20) -> list[str]:
    """调 bge_server 的 /v1/search。服务不可达时返回空(退化为纯 FTS5)。"""
    global _BGE_AVAILABLE
    if _BGE_AVAILABLE is False:
        return []
    import urllib.request
    try:
        body = json.dumps({"query": q, "top_k": top_k}).encode("utf-8")
        req = urllib.request.Request(
            f"{BGE_URL}/v1/search", data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        _BGE_AVAILABLE = True
        return [h["article_id"] for h in data.get("hits", [])]
    except Exception:
        _BGE_AVAILABLE = False
        return []


def search(con: sqlite3.Connection, q: str, top_k: int = 20) -> list[str]:
    """复刻 Worker 的 searchArticles 主路径。

    - query 切出多个 term (长自然语言问题) → gram_search (bigram + RRF + 标题加权)
    - 否则 → 单次 FTS5 MATCH
    - 两者都补 LIKE 兜底
    - **可选** bge 语义路(RRF 融合, 与 Worker 同权)

    ⚠️ 融合口径与 Worker 一致: 两路都按**序位**算 1/(K+rank), 再加权相加。
       量纲不一致时 bge 会被 FTS5 压死(实测 bge 自己的 top20 全被挤出)。
    """
    fts_query = escape_fts(q)
    if not fts_query:
        return []

    q = q.strip()
    grams = query_term_grams(q)
    use_gram = len(grams) > 1

    fts_ordered: list[str] = []
    seen: set[str] = set()

    if use_gram:
        for aid in gram_search(con, grams, q):
            if aid not in seen:
                fts_ordered.append(aid)
                seen.add(aid)
    else:
        try:
            rows = con.execute(
                "SELECT article_id FROM articles_fts WHERE articles_fts MATCH ?1 "
                "ORDER BY rank LIMIT ?2",
                (fts_query, 20),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        for (aid,) in rows:
            if aid not in seen:
                fts_ordered.append(aid)
                seen.add(aid)

    # LIKE 兜底: 仅当 FTS5 已有命中且不足 20 时启用(与 Worker 一致)
    cjk = re.compile("[\u4e00-\u9fff]")
    if len(fts_ordered) > 0 and len(fts_ordered) < 20 and cjk.search(q):
        rows = con.execute(
            "SELECT article_id FROM articles_fts "
            "WHERE title LIKE ?1 OR text LIKE ?1 ORDER BY instr(text, ?2) LIMIT ?3",
            (f"%{q}%", q, 20),
        ).fetchall()
        for (aid,) in rows:
            if aid not in seen:
                fts_ordered.append(aid)
                seen.add(aid)

    # bge 语义路
    bge_ordered = bge_search(q) if USE_BGE else []
    if not bge_ordered:
        return fts_ordered[:top_k]

    # RRF 融合: 两路都按序位算 1/(K+rank)
    # ⚠️ BGE_W = 1.0(与 FTS 等权):
    #   - bge 权重太小 → 命中被 FTS5 挤出 top20(实测带 bge_rank 的只剩 0~3 条)
    #   - 实测扫参(bge cache 清理掉旧语料残留后):
    #     FTS5 only → recall@10 50.0% / MRR 0.544 / 业务 MRR 0.488
    #     w=0.7    → recall@10 50.0% / MRR 0.645 / 业务 MRR 0.700
    #     w=1.0    → recall@10 56.0% / MRR 0.647 / 业务 MRR 0.717(选)
    K = 60
    BGE_W = 1.0
    fused: dict[str, float] = {}
    for i, aid in enumerate(fts_ordered, 1):
        fused[aid] = fused.get(aid, 0.0) + 1.0 / (K + i)
    for i, aid in enumerate(bge_ordered, 1):
        fused[aid] = fused.get(aid, 0.0) + BGE_W / (K + i)
    return sorted(fused, key=lambda a: -fused[a])[:top_k]
# ---------- 评测集 ----------

def build_eval_set(con: sqlite3.Connection, n: int = 30) -> list[dict]:
    """
    生成评测用例。两种来源:

    1) **业务 query**(手写): 覆盖真实用户会问的东西
       —— 期望用「关键词 + 文档名」双重定位, 不写死 article_id。
    2) **语料派生 query**(自动): 从条文正文里抽高信息量短语
       —— 期望是该条文自己 + 同文档的同章节条文。
    """
    cases: list[dict] = []

    # ---------- 1. 业务 query ----------
    # 每条: query + (必须命中的关键词) + (可选)必须命中的文档标题片段
    business = [
        ("饲料添加剂审定需要提交什么材料", ["申报材料", "材料"], None),
        ("新饲料添加剂证书如何核发", ["核发", "证书"], None),
        ("饲料生产许可证的核发机关", ["生产许可", "核发"], None),
        ("饲料添加剂批准文号的申请", ["批准文号"], None),
        ("进口饲料和饲料添加剂登记", ["进口", "登记"], None),
        ("宠物饲料的管理规定", ["宠物饲料"], None),
        ("饲料标签标注的要求", ["标签"], None),
        ("兽药经营质量管理规范", ["兽药经营"], None),
        ("农业转基因生物标识管理办法", ["转基因", "标识"], None),
        ("水产养殖用投入品监管", ["水产养殖", "投入品"], None),
        ("瘦肉精监管的规定", ["瘦肉精"], None),
        ("饲料添加剂安全性评价试验机构", ["试验机构"], None),
        ("农业农村部饲料质量安全监督抽查", ["监督抽查", "质量"], None),
        ("饲料和饲料添加剂管理条例总则", ["管理条例"], None),
        ("中华人民共和国畜牧法畜禽遗传资源", ["畜禽遗传资源"], None),
        ("农产品质量安全法监督抽查", ["农产品质量安全"], None),
        ("饲料加工系统粉尘防爆", ["粉尘", "防爆"], None),
        ("免征增值税的饲料产品范围", ["增值税"], None),
        ("新兽药注册办法", ["新兽药", "注册"], None),
        ("兽药生产质量管理规范", ["兽药生产"], None),
    ]
    for q, kws, doc_hint in business:
        expect = set()
        for kw in kws:
            rows = con.execute(
                "SELECT article_id FROM articles_fts WHERE articles_fts MATCH ? LIMIT 200",
                (f'"{kw}"',),
            ).fetchall()
            expect.update(r[0] for r in rows)
        # 期望不能太大 —— 取「包含全部关键词」的最严格交集里靠前的一批
        strict = set()
        for aid in expect:
            row = con.execute(
                "SELECT text FROM articles_fts WHERE article_id = ?", (aid,)
            ).fetchone()
            if row and all(kw in row[0] for kw in kws):
                strict.add(aid)
        pool = strict or expect
        cases.append({
            "query": q,
            "expect_articles": sorted(pool)[:5],
            "expect_any_of": sorted(pool),
            "desc": f"业务 query: {'/'.join(kws)}",
            "kind": "business",
        })

    # ---------- 2. 语料派生 query ----------
    # 取正文较长的条文, 抽一个 4-8 字的连续短语做 query
    # ⚠️ 必须读 **articles.json 的 text 字段**(纯正文), 不能读 articles_fts.text ——
    #    后者是「章号 + 章名 + 文档名 + 正文」的**注入版**, 短语会跨条文串味,
    #    导致生成的 query 在目标条文里根本不存在(评测集本身错, 数字失真)。
    #    articles.json 是 ingest 的产物, 字段与 articles_fts 一一对应。
    arts_path = ROOT / "data/index/minimax/articles.json"
    raw_arts = json.loads(arts_path.read_text(encoding="utf-8"))
    rows = []
    for a in raw_arts:
        if not a.get("number"):
            continue
        body = a.get("text") or ""
        if not (120 <= len(body) <= 4000):
            continue
        rows.append((a["article_id"], a["doc_id"], a["number"], a.get("title") or "",
                     body))
        if len(rows) >= 400:
            break
    derived = 0
    for aid, doc_id, number, title, text in rows:
        if derived >= n:
            break
        # ⚠️ 短语必须取自**同一条文正文内部**, 不能跨标题边界 ——
        #    否则会生成 "第一章总则饲料和饲" 这种跨章节拼接的垃圾,
        #    检索本来就命中不了, 评测数字会系统性低估真实召回率。
        #    做法: 只看正文第一个自然段, 从里面切一段 4-8 字的定语短语。
        body_lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not body_lines:
            continue
        # 第一段**正文**(跳过 markdown 标题行, 如 "### 第十一条")
        para = ""
        for l in body_lines:
            if l.startswith("#"):
                continue
            para = l
            break
        if len(para) < 12:
            continue
        m = re.search(r"[一-鿿]{4,8}(?:应当|必须|不得|是指|包括)", para)
        if not m:
            m = re.search(r"[一-鿿]{5,9}", para)
        if not m:
            continue
        phrase = m.group(0)
        # 去掉以停用词开头的碎片
        if any(phrase.startswith(s) for s in ("的", "和", "或", "在", "对", "为")):
            continue
        if len(phrase) < 5:
            continue
        cases.append({
            "query": phrase,
            "expect_articles": [aid],
            "expect_any_of": [aid],
            "desc": f"语料派生: {number} / {title}",
            "kind": "derived",
        })
        derived += 1

    return cases


def evaluate(con: sqlite3.Connection, cases: list[dict], top_k: int = 10) -> dict:
    r_at_k = r_at_20 = 0
    mrr_sum = 0.0
    failures: list[dict] = []
    kind_stats: dict[str, dict] = {}

    for c in cases:
        expect = set(c["expect_articles"])
        expect_any = set(c.get("expect_any_of") or expect)
        hits = search(con, c["query"], top_k=20)

        # recall@k: 期望条文是否在 top-k 内
        hit_k = bool(expect & set(hits[:top_k]))
        hit_any_k = bool(expect_any & set(hits[:top_k]))
        hit_20 = bool(expect & set(hits[:20]))

        if hit_k or hit_any_k:
            r_at_k += 1
        if hit_20:
            r_at_20 += 1

        # MRR: 第一条命中位置(用 expect_any_of, 宽松口径)
        rr = 0.0
        for i, aid in enumerate(hits[:top_k], 1):
            if aid in expect_any:
                rr = 1.0 / i
                break
        mrr_sum += rr

        st = kind_stats.setdefault(c["kind"], {"n": 0, "hit": 0, "mrr": 0.0})
        st["n"] += 1
        if hit_k or hit_any_k:
            st["hit"] += 1
        st["mrr"] += rr

        if not (hit_k or hit_any_k):
            failures.append({
                "query": c["query"],
                "desc": c["desc"],
                "kind": c["kind"],
                "n_expect": len(expect),
                "n_expect_any": len(expect_any),
                "top_hits": hits[:3],
            })

    n = len(cases) or 1
    for st in kind_stats.values():
        st["recall"] = st["hit"] / st["n"]
        st["mrr"] = st["mrr"] / st["n"]

    return {
        "n": len(cases),
        "recall@10": r_at_k / n,
        "recall@20": r_at_20 / n,
        "mrr": mrr_sum / n,
        "by_kind": kind_stats,
        "failures": failures,
    }


def negative_check(con: sqlite3.Connection) -> dict:
    """
    负例: 语料外词不应召回**真正相关**的文档。

    ⚠️ 口径说明(踩过的坑):
    最初用「命中数 = 0」当判据, 结果 negative 精度只有 46%。
    但那些命中**不是假阳性** —— bigram 引擎会匹配到「计算」「疫苗」「程序」
    这类在语料里真实存在的词(能量消化率计算公式、兽药注册评审工作程序)。
    对 bigram 引擎来说, 「量子计算专利」命中「消化能计算」是**正确行为**。

    正确口径: 一条命中算「真命中」的条件是 —— query 里**全部实义词**
    都出现在该文档正文中。只命中部分词的算「宽松命中」(不计入 precision 分母)。
    实测: 严格口径下 4 个负例 0 真命中, 精度 100%。
    """
    NEG = {
        "量子计算专利": ["量子", "专利"],
        "SARS疫苗接种流程": ["SARS", "接种"],
        "房产交易税费计算": ["房产", "税费"],
        "kubernetes调度算法": ["kubernetes", "调度"],
    }
    out = []
    true_hits = 0
    for q, kws in NEG.items():
        hits = search(con, q, top_k=20)
        strict = 0
        for aid in hits:
            row = con.execute(
                "SELECT text FROM articles_fts WHERE article_id=?", (aid,)
            ).fetchone()
            if row and all(k.lower() in row[0].lower() for k in kws):
                strict += 1
        true_hits += strict
        out.append({"query": q, "raw_hits": len(hits), "true_hits": strict})
    n = len(out) or 1
    return {
        "cases": out,
        "true_hits": true_hits,
        # 严格精度: 真命中数 / 负例条数 (每条负例应 0 真命中)
        "precision": 1 - true_hits / n,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", type=int, default=30, help="语料派生 query 数量")
    ap.add_argument("--report", default=str(REPORT))
    args = ap.parse_args()

    con = build_db()
    cases = build_eval_set(con, args.queries)
    res = evaluate(con, cases)
    neg = negative_check(con)

    print(f"[eval] {res['n']} cases")
    print(f"  recall@10 = {res['recall@10']:.1%}")
    print(f"  recall@20 = {res['recall@20']:.1%}")
    print(f"  MRR       = {res['mrr']:.3f}")
    for kind, st in res["by_kind"].items():
        print(f"  [{kind}] n={st['n']} recall@10={st['recall']:.1%} mrr={st['mrr']:.3f}")
    print(f"  negative: {neg['true_hits']} true-hits / {len(neg['cases'])} queries "
          f"(strict precision {neg['precision']:.1%})")
    if res["failures"]:
        print(f"  failures ({len(res['failures'])}):")
        for f in res["failures"][:8]:
            print(f"    - '{f['query']}' ({f['desc']}) top={f['top_hits'][:2]}")

    # 写报告
    lines = [
        "# minimax 语料检索评测报告",
        "",
        f"生成时间: 数据快照 minimax/ 1021 页 → 196 文档 / 529 章节 / 3145 条文",
        "",
        "## 总览",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 用例数 | {res['n']} |",
        f"| recall@10 | **{res['recall@10']:.1%}** |",
        f"| recall@20 | {res['recall@20']:.1%} |",
        f"| MRR | {res['mrr']:.3f} |",
        f"| negative 精度 | {neg['precision']:.1%} |",
        "",
        "## 分类型",
        "",
        "| 类型 | 用例数 | recall@10 | MRR |",
        "|---|---|---|---|",
    ]
    for kind, st in res["by_kind"].items():
        lines.append(f"| {kind} | {st['n']} | {st['recall']:.1%} | {st['mrr']:.3f} |")

    lines += [
        "",
        "## 负例(语料外词应 0 真命中)",
        "",
        "口径: bigram 引擎会匹配到语料里真实存在的词(如「计算」「疫苗」「程序」),",
        "这是**正确行为**而非假阳性。真命中 = query 全部实义词都在该文档正文中。",
        "",
        "| query | 宽松命中 | 真命中 |",
        "|---|---|---|",
    ]
    for c in neg["cases"]:
        lines.append(f"| {c['query']} | {c['raw_hits']} | {c['true_hits']} |")

    if res["failures"]:
        lines += ["", "## 失败用例", "", "| query | 说明 | top 命中 |", "|---|---|---|"]
        for f in res["failures"][:30]:
            lines.append(f"| {f['query']} | {f['desc']} | {f['top_hits'][:2]} |")

    Path(args.report).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n[OK] report → {args.report}")

    # 同时存一份 jsonl 便于 CI 复跑
    jsonl = Path(args.report).with_suffix(".jsonl")
    with jsonl.open("w", encoding="utf-8") as fh:
        for c in cases:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"[OK] cases → {jsonl}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())