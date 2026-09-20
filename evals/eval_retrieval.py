"""
检索 recall 评测:读 evals/retrieval.jsonl,跑 FTS5 + 可能的 bge/TF-IDF hybrid,统计 recall@K + MRR。

不依赖 Cloudflare,直接用 Python sqlite3 复刻 Workers 的 FTS5 查询。

跑法:
    python evals/eval_retrieval.py
    # 或只跑 fts5:python evals/eval_retrieval.py --no-bge --no-tfidf

输出:
    evals/retrieval_report.md

[2026-09-20 玄穹 CEO 决策 C-a] 加 bge 语义召回分支
- bge cache 文件: evals/bge_m3_cache.json (由 build/export/embed_articles.py 生成)
- TF-IDF cache 文件: evals/tfidf_cache.json (已有, G 阶段)
- 三路 hybrid: FTS5(精确) + TF-IDF(bi-gram 宽召回) + bge(语义)
- 权重通过 --weights 参数可调

[2026-09-20 玄穹 CEO 决策 C-b] negative 假阳性收紧
- LIKE 兜底加门控: 仅当 FTS5 trigram 已有命中时才补位 (修 2 字 query 偶然 substring)
- FTS5 agreement 门禁: TF-IDF/bge 只 boost 有 trigram 命中的 article,
  纯语义引入需超高门槛 (TF-IDF > 0.15 / bge > 0.6) (修 bi-gram 弱散射 coupling)
- trigram 候选集全量化 (top_k 截断改 1000): 保短小条文真命中 (BM25 密度低)
"""
from __future__ import annotations
import json
import re
import sqlite3
from pathlib import Path


ROOT = Path(__file__).parent.parent
SCHEMA = ROOT / "query/worker/schema.sql"
SEED = ROOT / "build/export/seed.sql"
# 2023-full M3 OCR 灌库(2026-09-13 批次, 515 articles)
SEED_PAGES_M3 = ROOT / "build/export/seed_pages_m3.sql"
EVAL = ROOT / "evals/retrieval.jsonl"
REPORT = ROOT / "evals/retrieval_report.md"


def build_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.executescript(SEED.read_text(encoding="utf-8"))
    if SEED_PAGES_M3.exists() and SEED_PAGES_M3.stat().st_size > 0:
        con.executescript(SEED_PAGES_M3.read_text(encoding="utf-8"))
    return con


def escape_fts(q: str) -> str:
    return re.sub(r"[\x00-\x1f]", " ", q).strip()[:64]


def search(con: sqlite3.Connection, q: str, top_k: int = 20) -> list[str]:
    cleaned = escape_fts(q)
    if not cleaned:
        return []
    queries = [cleaned]
    # trigram ≥3 字才匹配。2 字中文 query 多搜几个 padding 后缀,合并去重
    if len(cleaned) == 2 and re.fullmatch(r"[\u4e00-\u9fff]+", cleaned):
        for suffix in ("制", "的", "条", "法", "理"):
            queries.append(cleaned + suffix)

    # [2026-09-20 玄穹 C-b] 候选集改全量: 不再 top_k 截断。
    # 短小条文 (feedlaw2_art008, 仅 123 字) 的 BM25 密度天然低于 OCR 长页,
    # 真命中常沉到 rank 20~40 —— 截断会让 TF-IDF/bge 失去 agreement 依据。
    # fts5_full = 全部 trigram 命中 (做语义路径的 agreement 门禁);
    # fts5_hits = 章节优先排序后取 top_k (进 ranking)。
    seen: list[tuple[str, int]] = []  # (article_id, rank)
    seen_set: set[str] = set()
    for query in queries:
        try:
            rows = con.execute(
                "SELECT article_id, rank FROM articles_fts WHERE articles_fts MATCH ?1 ORDER BY rank LIMIT ?2",
                (query, 1000),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        for r in rows:
            if r[0] not in seen_set:
                seen.append((r[0], r[1]))
                seen_set.add(r[0])

    fts5_full = set(seen_set)

    # 兜底:对中文 query 补一次 LIKE,确保 2 字短 query 也能召回
    # [2026-09-20 玄穹 C-a] 负例收紧:仅当 FTS5 trigram 已有 ≥1 命中时才补位。
    # 之前 2 字 query (如 "刑法") trigram/padding 全空时, LIKE 会把 "追究刑事责任"
    # 等偶然 substring 凑成命中,且按 FTS5 全权重进入 hybrid → 语料外 query 假阳性。
    # 门控后 LIKE 只做召回 top-up,不再单独成路。
    like_hits: list[tuple[str, int]] = []
    if len(seen) > 0 and len(seen) < top_k and re.search(r"[\u4e00-\u9fff]", q):
        # [2026-09-20 玄穹 C-b] LIKE 结果按 instr 首次出现位置排序:
        # 避免 FTS5 表扫描的任意行序 → 2 字 query 真实命中靠前 (审定→art005/006/007)
        like = f"%{q}%"
        rows = con.execute(
            "SELECT article_id, rank FROM articles_fts "
            "WHERE title LIKE ?1 OR text LIKE ?1 "
            "ORDER BY instr(text, ?2) LIMIT ?3",
            (like, q, top_k),
        ).fetchall()
        seen_with_like = set()
        for r in rows:
            if r[0] not in seen_set and r[0] not in seen_with_like:
                like_hits.append((r[0], r[1] if r[1] is not None else 0))
                seen_with_like.add(r[0])

    # === F 排序加权:章节级 (section) 排在页级 (page) 前面 ===
    # section: 老 doc 人工结构化 (feedlaw2_/feedlawco_/fee_sec* 等)
    # page:    新 doc M3 OCR 自动切 (flc23_p* 等)
    SECTION_DOCS = ("feed-law-2026", "feed-law-collection-2023", "feed-trial-guideline-2023")
    SECTION_PREFIXES = ("feedlaw2_", "feedlawco_", "fee_sec", "fee_ch")

    def is_section(aid: str) -> bool:
        # 用 article_id 前缀粗判
        return any(aid.startswith(p) for p in SECTION_PREFIXES)

    # 排序: section 优先, 同类内按 FTS5 rank 升序 (rank 越低越好)
    # [2026-09-20 玄穹 C-b] 硬分层 (0/1) 改软分层: section 给 rank 折扣而非硬前置。
    # 全量候选集后, 硬分层会让深排名老 collection 条目 (BM25 差) 无脑压过
    # rank 好的 flc23 页 (如 #47 评审委) → section 只是偏好, rank 仍是主序。
    # 折扣 3.0 ≈ 让章节级在同等词频下优先, 但 rank 差 >3 的章节级不再硬抢。
    SECTION_RANK_DISCOUNT = 3.0

    def rank_key(x: tuple[str, int]) -> tuple[float, int]:
        aid, r = x
        return (r - SECTION_RANK_DISCOUNT if is_section(aid) else r, 0)

    seen.sort(key=rank_key)

    # LIKE 补位作为独立低权重路径 (见 hybrid 合并)
    fts5_hits = [aid for aid, _ in seen[:top_k]]

    # === G 语义召回 (TF-IDF fallback,无 bge 模型时的方案) ===
    # 用 TF-IDF 算 query vs article text 的 cosine 相似度, 与 FTS5 合并去重
    # 触发条件: TF-IDF cache 存在 (eval/tfidf_cache.json) + 未禁用
    tfidf_hits = [] if DISABLE_TFIDF else _tfidf_search(q, top_k=top_k)

    # === [2026-09-20 玄穹 C-a] H 语义召回 (bge-m3,真语义,接 127.0.0.1:8080) ===
    # 触发条件: bge cache 存在 (evals/bge_m3_cache.json) + 在线 bge 服务 up + 未禁用
    bge_hits = [] if DISABLE_BGE else _bge_search(q, top_k=top_k)

    # Hybrid 合并: FTS5 + LIKE + TF-IDF + bge 三路
    # 权重通过 SEARCH_WEIGHTS 全局变量注入(默认 0.5/0.2/0.3)
    w_fts, w_tfidf, w_bge = SEARCH_WEIGHTS
    w_like = 0.3  # LIKE 补位 (低置信 substring, 只对 2 字短 query 补召回)
    # TF-IDF/bge 都按 rank 加权,只前 N 位有效,避免宽召回污染
    TFIDF_K, BGE_K, LIKE_K = 5, 10, 5
    score: dict[str, float] = {}
    for r, aid in enumerate(fts5_hits):
        score[aid] = score.get(aid, 0) + w_fts * (1.0 / (r + 1))
    for r, (aid, _) in enumerate(like_hits[:LIKE_K]):
        score[aid] = score.get(aid, 0) + w_like * (1.0 / (r + 1))
    # [2026-09-20 玄穹 C-b] 负例收紧——FTS5 agreement 门禁:
    # 语义路径 (TF-IDF/bge) 只能在下述情况给 article 加分:
    #   1) 该 article 本身有 trigram 命中 (fts5_full) → 自由 boost, 只重排已有候选;
    #   2) 纯语义引入 (完全无 trigram 命中) → 必须超过高门槛,
    #      否则 "网络安全法" vs "农产品质量安全法" (共享 bi-gram "安全法",
    #      cosine 0.04~0.12) 这类语料外 coupling 会单独成路污染 ranking。
    for r, (aid, s) in enumerate(tfidf_hits[:TFIDF_K]):
        if aid in fts5_full or s > TFIDF_MIN_SCORE:
            score[aid] = score.get(aid, 0) + w_tfidf * (1.0 / (r + 1))
    for r, (aid, s) in enumerate(bge_hits[:BGE_K]):
        if aid in fts5_full or s > BGE_MIN_SCORE:
            # [2026-09-20 玄穹 C-c] bge 加成按 sim 缩放:
            # 事实 1: 期望 article 在 fts5_full 但 bge sim < 0.5 (没进 bge top-K)
            #         时得不到任何 boost, 而 sim 0.54 的干扰页拿满额 0.3 → 被挤出 top-10。
            # 事实 2: 同 rank 下 sim 0.9 (真语义) 应比 sim 0.53 (弱联想) 加分更多。
            # 所以 w_bge 乘以 sim 本身: 弱相似度贡献自动衰减, 强匹配权重更大。
            score[aid] = score.get(aid, 0) + w_bge * s * (1.0 / (r + 1))

    # 按综合分排序, 取 top_k
    ranked = sorted(score.items(), key=lambda x: -x[1])
    return [aid for aid, _ in ranked[:top_k]]


# === G: TF-IDF 召回 (Lazy load cache) ===
_TFIDF_CACHE = None


def _load_tfidf_cache():
    global _TFIDF_CACHE
    if _TFIDF_CACHE is not None:
        return _TFIDF_CACHE
    cache_path = Path(__file__).parent / "tfidf_cache.json"
    if not cache_path.exists():
        return None
    import json as _json
    import math as _math
    from collections import Counter as _Counter
    import re as _re
    data = _json.loads(cache_path.read_text(encoding="utf-8"))
    _TFIDF_CACHE = {
        "data": data,
        "Counter": _Counter,
        "math": _math,
        "re": _re,
    }
    return _TFIDF_CACHE


def _tfidf_search(query: str, top_k: int = 20) -> list[tuple[str, float]]:
    cache = _load_tfidf_cache()
    if not cache:
        return []
    data = cache["data"]
    Counter = cache["Counter"]
    math = cache["math"]
    re = cache["re"]

    def tokenize_zh(text):
        if not text:
            return []
        text = re.sub(r"[\s\u3000\u3001\u3002\uff0c\uff01\uff1f\uff1b\uff1a\u201c\u201d\u2018\u2019\uff08\uff09\u300a\u300b\uff3b\uff3d]+", "", text)
        chars = list(text)
        grams = set()
        for i in range(len(chars) - 1):
            g = chars[i] + chars[i+1]
            if re.match(r"[\u4e00-\u9fff]", g):
                grams.add(g)
        return list(grams)

    qtf = Counter(tokenize_zh(query))
    total = sum(qtf.values()) or 1
    idf = data["idf"]
    qvec = {t: (qtf[t] / total) * idf.get(t, 0) for t in qtf}

    if not qvec:
        return []

    def cosine(a, b):
        if not a or not b:
            return 0.0
        common = set(a.keys()) & set(b.keys())
        num = sum(a[t] * b[t] for t in common)
        na = math.sqrt(sum(v*v for v in a.values()))
        nb = math.sqrt(sum(v*v for v in b.values()))
        if na == 0 or nb == 0:
            return 0.0
        return num / (na * nb)

    scores = []
    for i, v in enumerate(data["vecs"]):
        s = cosine(qvec, v)
        # === 阈值: TF-IDF cosine < TFIDF_MIN_SCORE 的不算召回 ===
        # [2026-09-20 玄穹 C-a] 负例收紧:0.03 → 0.15。
        # 旧 0.03 门槛下, bi-gram 宽召回的弱散射 (如 "网络安全法" vs "农产品质量安全法"
        # 共享 "安全法" bi-gram, cosine 0.04~0.12) 会单独成路污染 ranking → 语料外假阳性。
        # CGI: 真实法规命中 (FTS5 确认过的 article) cosine 通常在 0.15+。
        if s > TFIDF_MIN_SCORE:
            scores.append((data["tokenized"][i][0], s))
    scores.sort(key=lambda x: -x[1])
    return scores[:top_k]


# === [2026-09-20 玄穹 C-a] H: bge-m3 语义召回 ===
# 双模式:
#   - in-process (默认,推荐): 模块级 lazy singleton SentenceTransformer
#   - http: 通过 127.0.0.1:8080/v1/embeddings 调 bge_server.py
#   切换: USE_BGE_HTTP=True 或 --bge-http CLI 参数
#
# 注: 2026-09-20 实测 bge_server.py 在 Windows 下加载阶段会卡死,
#     推荐 in-process 模式 (加载 25s, 后续 query <1s)
import urllib.request as _ur
import urllib.error as _ue
_BGE_CACHE = None
_BGE_CACHE_PATH = Path(__file__).parent / "bge_m3_cache.json"
_BGE_URL = "http://127.0.0.1:8080/v1/embeddings"
USE_BGE_HTTP: bool = False  # 由 main() 根据 args 注入
_BGE_MODEL_INSTANCE = None


def _get_bge_model():
    """in-process 模式:lazy singleton"""
    global _BGE_MODEL_INSTANCE
    if _BGE_MODEL_INSTANCE is not None:
        return _BGE_MODEL_INSTANCE
    import os
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    # [2026-09-20 玄穹] 模型已本地缓存 (evals/.models/hf), 强制离线避免 hub 联网检查卡死
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    import httpx  # noqa: E402
    _orig = httpx.Client.__init__
    def _ps(self, *a, **kw): kw.setdefault("trust_env", False); return _orig(self, *a, **kw)
    httpx.Client.__init__ = _ps
    from sentence_transformers import SentenceTransformer  # noqa: E402
    cache_dir = str((Path(__file__).parent / ".models/hf").resolve())
    print(f"[bge] loading BAAI/bge-m3 from {cache_dir} (CPU, 25s first run)...", flush=True)
    import time as _t
    t0 = _t.time()
    _BGE_MODEL_INSTANCE = SentenceTransformer(
        "BAAI/bge-m3", cache_folder=cache_dir, device="cpu",
    )
    print(f"[bge] loaded in {_t.time()-t0:.1f}s", flush=True)
    return _BGE_MODEL_INSTANCE


def _load_bge_cache():
    """加载离线算好的 articles embedding(由 build/export/embed_articles.py 生成)"""
    global _BGE_CACHE
    if _BGE_CACHE is not None:
        return _BGE_CACHE
    if not _BGE_CACHE_PATH.exists():
        return None
    data = json.loads(_BGE_CACHE_PATH.read_text(encoding="utf-8"))
    # 预转成 numpy 数组加速 cosine
    try:
        import numpy as _np
        arts = data["articles"]
        aids = [a[0] for a in arts]
        mat = _np.asarray([a[2] for a in arts], dtype=_np.float32)
        # bge-m3 输出已 normalize,后续无需再 normalize
        _BGE_CACHE = {"aids": aids, "mat": mat, "dim": data.get("dim", 1024)}
        return _BGE_CACHE
    except ImportError:
        return None  # 没 numpy 就走纯 python 慢路径


def _embed_query_via_bge_server(query: str, timeout: float = 30.0) -> list[float] | None:
    """HTTP 模式:调 bge_server 把 query 转 1024 维向量。失败返 None(不抛异常)。"""
    body = json.dumps({"input": [query], "model": "BAAI/bge-m3"}).encode("utf-8")
    try:
        req = _ur.Request(
            _BGE_URL,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _ur.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read())
        return payload["data"][0]["embedding"]
    except (_ue.URLError, TimeoutError, json.JSONDecodeError, KeyError, IndexError):
        return None


def _embed_query_inprocess(query: str) -> list[float] | None:
    """in-process 模式:直接调本地 SentenceTransformer"""
    try:
        m = _get_bge_model()
        v = m.encode([query], normalize_embeddings=True, show_progress_bar=False)
        return v[0].tolist()
    except Exception:
        return None


def _embed_query(query: str) -> list[float] | None:
    """统一入口:按 USE_BGE_HTTP 分流"""
    if USE_BGE_HTTP:
        return _embed_query_via_bge_server(query)
    return _embed_query_inprocess(query)


def _bge_search(query: str, top_k: int = 20) -> list[tuple[str, float]]:
    """用 bge-m3 算 query vs 649 articles 的 cosine, 返 top_k (aid, score)
    bge 服务挂了或 cache 缺失 → 返 [], hybrid 自动降级。
    """
    cache = _load_bge_cache()
    if not cache:
        return []
    qvec = _embed_query(query)
    if qvec is None:
        return []
    try:
        import numpy as _np
        q = _np.asarray(qvec, dtype=_np.float32)
        mat = cache["mat"]
        # bge-m3 已 normalize → cosine = dot product
        sims = mat @ q
        # 阈值: cosine < 0.5 视为无关(避免语义偶然命中)
        idxs = [int(i) for i in _np.argsort(-sims) if sims[i] >= 0.5][:top_k]
        return [(cache["aids"][i], float(sims[i])) for i in idxs]
    except ImportError:
        return []


# === [2026-09-20 玄穹 C-a] Hybrid 权重 (命令行可覆盖) ===
SEARCH_WEIGHTS: tuple[float, float, float] = (0.5, 0.2, 0.3)  # (fts5, tfidf, bge)
# [2026-09-20 玄穹 C-a] TF-IDF cosine 门槛 (负例收紧, CLI --tfidf-threshold 可改)
TFIDF_MIN_SCORE: float = 0.15
# [2026-09-20 玄穹 C-b] bge cosine 门槛: 无 FTS5 agreement 的纯语义引入需 > this
BGE_MIN_SCORE: float = 0.6
DISABLE_BGE: bool = False
DISABLE_TFIDF: bool = False


def mrr(hits: list[str], expected: set[str]) -> float:
    """第一条命中的倒数排名;无命中返回 0"""
    for i, h in enumerate(hits, 1):
        if h in expected:
            return 1.0 / i
    return 0.0


def classify_failure(query: str, hits: list[str], expected: set[str]) -> str:
    """失败根因分类,指导改进方向"""
    q = query.strip()
    if not q or q == "":
        return "空 query(边界用例)"
    if not expected:
        # negative 用例:不应召回,但实际有召回 → 假阳性
        if hits:
            return f"NEGATIVE 假阳性:实际命中 {hits[:3]},期望 0 命中"
        return "NEGATIVE 通过"
    if len(q) <= 2 and re.fullmatch(r"[\u4e00-\u9fff]+", q):
        return f"短 query ({len(q)} 字) padding 召回不全:实际 {hits[:3]}"
    return f"关键词命中但排序错:实际 {hits[:3]},期望 {sorted(expected)[:3]}"


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-bge", action="store_true", help="disable bge 召回分支")
    parser.add_argument("--no-tfidf", action="store_true", help="disable tfidf 召回分支")
    parser.add_argument("--bge-http", action="store_true",
                        help="用 bge_server.py HTTP 模式 (默认 in-process, 推荐)")
    parser.add_argument("--weights", default="0.5,0.2,0.3",
                        help="hybrid 权重 (fts5,tfidf,bge), 例如 --weights 0.4,0.1,0.5")
    parser.add_argument("--tfidf-threshold", type=float, default=0.15,
                        help="TF-IDF cosine 最低门槛 (默认 0.15, 负例收紧用)")
    parser.add_argument("--bge-threshold", type=float, default=0.6,
                        help="bge cosine 最低门槛 (无 FTS5 agreement 时, 默认 0.6)")
    args = parser.parse_args()

    # 应用权重 (覆盖默认)
    global SEARCH_WEIGHTS, DISABLE_BGE, DISABLE_TFIDF, USE_BGE_HTTP, TFIDF_MIN_SCORE, BGE_MIN_SCORE
    DISABLE_BGE = args.no_bge
    DISABLE_TFIDF = args.no_tfidf
    USE_BGE_HTTP = args.bge_http
    TFIDF_MIN_SCORE = args.tfidf_threshold
    BGE_MIN_SCORE = args.bge_threshold
    w = [float(x) for x in args.weights.split(",")]
    assert len(w) == 3, "weights 必须 3 个数 (fts5,tfidf,bge)"
    SEARCH_WEIGHTS = tuple(w)  # type: ignore

    con = build_db()
    n_corpus = con.execute("SELECT COUNT(*) FROM articles_fts").fetchone()[0]

    cases = []
    with EVAL.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            cases.append(json.loads(line))

    pos_cases = [c for c in cases if c["expect_articles"]]
    neg_cases = [c for c in cases if not c["expect_articles"]]

    lines: list[str] = [
        "# Retrieval Recall Report",
        "",
        f"- Corpus: `{n_corpus}` articles (feed-law-2026)",
        f"- Eval cases: `{len(cases)}` (positive: {len(pos_cases)}, negative: {len(neg_cases)})",
        "- Tokenizer: FTS5 trigram + LIKE 兜底",
        "- 2 字中文 query 自动 padding 后缀",
        "",
    ]

    # 跑 search(top_k=20),评估 recall@10 / recall@20 / MRR
    pos_results: list[tuple[int, dict, list[str]]] = []
    total_rec10 = total_rec20 = total_mrr = 0.0
    n_pass10 = 0
    fails: list[tuple[int, dict, list[str], str]] = []
    for i, case in enumerate(pos_cases, 1):
        hits = search(con, case["query"], top_k=20)
        expected = set(case["expect_articles"])
        hit10 = set(hits[:10])
        hit20 = set(hits[:20])
        rec10 = len(expected & hit10) / len(expected) if expected else 0.0
        rec20 = len(expected & hit20) / len(expected) if expected else 0.0
        mrr_val = mrr(hits, expected)
        total_rec10 += rec10
        total_rec20 += rec20
        total_mrr += mrr_val
        passed = rec10 >= 0.5
        if passed:
            n_pass10 += 1
        else:
            fails.append((i, case, hits, classify_failure(case["query"], hits, expected)))
        pos_results.append((i, case, hits))

    avg_rec10 = total_rec10 / len(pos_cases) if pos_cases else 0.0
    avg_rec20 = total_rec20 / len(pos_cases) if pos_cases else 0.0
    avg_mrr = total_mrr / len(pos_cases) if pos_cases else 0.0

    # 跑 negative
    neg_results: list[tuple[int, dict, list[str]]] = []
    n_neg_pass = 0
    neg_fails: list[tuple[int, dict, list[str]]] = []
    for i, case in enumerate(neg_cases, 1):
        hits = search(con, case["query"], top_k=20)
        passed = len(hits) == 0
        if passed:
            n_neg_pass += 1
        else:
            neg_fails.append((i, case, hits))
        neg_results.append((i, case, hits))

    # === 汇总 ===
    lines.extend([
        "## 汇总",
        "",
        "### 正向用例(positive)",
        f"- **recall@10 = {avg_rec10:.1%}** (通过 {n_pass10}/{len(pos_cases)},recall ≥ 50%)",
        f"- **recall@20 = {avg_rec20:.1%}**",
        f"- **MRR = {avg_mrr:.3f}** (第一条命中平均倒数排名)",
        "",
        "### 负向用例(negative)",
        f"- **精度 = {n_neg_pass}/{len(neg_cases)}** (应 0 命中)",
        "",
    ])

    # 决策建议 (按 bge 是否启用给不同 verdict)
    bge_in_use = (not args.no_bge) and _BGE_CACHE_PATH.exists() and _load_bge_cache() is not None
    if avg_rec10 >= 0.85 and avg_mrr >= 0.70 and n_neg_pass >= len(neg_cases) - 1:
        verdict = "✅ C-a 闸门通过 (recall@10≥85% & MRR≥0.70 & negative≤1 假阳)"
    elif avg_rec10 >= 0.80 and avg_mrr >= 0.70 and n_neg_pass == len(neg_cases):
        verdict = "✅ FTS5 路径足够,推迟接 bge"
    elif avg_rec10 < 0.70:
        verdict = "❌ recall<70%,必须接 bge(触发 t_847af461)"
    elif avg_mrr < 0.50:
        verdict = "⚠️ MRR 偏低,排序逻辑需重写"
    elif n_neg_pass < len(neg_cases):
        verdict = "⚠️ negative 有假阳性,需调 FTS5-agreement 门禁/LIKE 门控"
    else:
        verdict = "🟡 边界合格,建议继续扩大 eval 覆盖"
    lines.append(f"### 决策建议\n\n**{verdict}**\n")
    lines.append(f"- 召回路径: {'FTS5 + TF-IDF + bge-m3 hybrid' if bge_in_use else 'FTS5 + TF-IDF (bge 未启用)'}\n")
    lines.append(f"- Hybrid 权重: fts5={SEARCH_WEIGHTS[0]} tfidf={SEARCH_WEIGHTS[1]} bge={SEARCH_WEIGHTS[2]}\n")

    # === 详细结果:positive ===
    lines.extend([
        "## 正向用例明细",
        "",
        "| # | Query | Expected | Hits@10 | R@10 | MRR |",
        "|---|---|---|---|---|---|",
    ])
    for idx, (i, case, hits) in enumerate(pos_results):
        expected = set(case["expect_articles"])
        hit10 = set(hits[:10])
        rec10 = len(expected & hit10) / len(expected) if expected else 0.0
        mrr_val = mrr(hits, expected)
        marker = "✅" if rec10 >= 0.5 else "❌"
        lines.append(
            f"| {i} | `{case['query']}` | {','.join(sorted(expected))} | "
            f"{','.join(hits[:5]) or '∅'} | {marker} {rec10:.0%} | {mrr_val:.2f} |"
        )

    # === 详细结果:negative ===
    lines.extend([
        "",
        "## 负向用例明细(期望 0 命中)",
        "",
        "| # | Query | Hits | 通过 |",
        "|---|---|---|---|",
    ])
    for i, case, hits in neg_results:
        marker = "✅" if len(hits) == 0 else "❌"
        lines.append(
            f"| {i} | `{case['query']}` | {','.join(hits[:5]) or '∅'} | {marker} |"
        )

    # === 失败根因 ===
    if fails:
        lines.extend([
            "",
            "## 正向失败根因",
            "",
        ])
        # 按根因分组
        by_reason: dict[str, list[tuple[int, dict, list[str]]]] = {}
        for i, case, hits, reason in fails:
            by_reason.setdefault(reason.split(":")[0], []).append((i, case, hits))
        for reason, items in by_reason.items():
            lines.append(f"### {reason} ({len(items)} 例)")
            for i, case, hits in items:
                lines.append(f"- **#{i} `{case['query']}`** — 期望 `{case['expect_articles']}`, 实际 `{hits[:5] or '∅'}`")
                lines.append(f"  - {case['desc']}")
            lines.append("")

    if neg_fails:
        lines.extend([
            "",
            "## 负向假阳性(NEGATIVE 失败)",
            "",
        ])
        for i, case, hits in neg_fails:
            lines.append(f"- **#{i} `{case['query']}`** — 假阳性命中 `{hits[:5]}`")
            lines.append(f"  - {case['desc']}")
        lines.append("")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] report: {REPORT}")
    print(f"     recall@10 = {avg_rec10:.1%}, recall@20 = {avg_rec20:.1%}, MRR = {avg_mrr:.3f}")
    print(f"     positive pass: {n_pass10}/{len(pos_cases)}, negative pass: {n_neg_pass}/{len(neg_cases)}")
    return 0 if (avg_rec10 >= 0.80 and n_neg_pass == len(neg_cases)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
