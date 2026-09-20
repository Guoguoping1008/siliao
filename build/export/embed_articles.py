"""
[2026-09-20 玄穹 CEO 决策 C-a.2]
离线算 649 articles 的 bge-m3 embedding,存为 JSON,供 eval_retrieval.py 复用

设计:
- 读 schema.sql + seed.sql + seed_pages_m3.sql (跟 eval_retrieval.py 一致) -> 内存 sqlite
- [默认 in-process] 直接 import sentence_transformers,模块级 lazy singleton (25s 加载, 5min 算完)
- [可选 HTTP] 调本地 bge_server.py (默认 127.0.0.1:8080, OpenAI 兼容 /v1/embeddings)
    注: bge_server.py 在 Windows 下加载期会卡住(2026-09-20 实测),推荐 --inprocess
- batch=8, bge-m3 max_seq=512, 短文本大多 <200 token
- 进度条:每 50 条打印 elapsed/eta
- 失败: --resume (skip already done)
- 输出: evals/bge_m3_cache.json
        {"model": "...", "dim": 1024, "articles": [[aid, doc_id, vec], ...]}
        ~ 649 * (8KB vec + 100B meta) = ~5.5 MB

跑法 (in-process 推荐):
    python build/export/embed_articles.py
    # 25s 模型加载 + 5-10 min CPU 算 649 条 ~ 8MB

跑法 (HTTP,需要 bge_server 启动):
    python build/proxy/bge_server.py &
    curl http://127.0.0.1:8080/health  # 等 ok
    python build/export/embed_articles.py --http
"""
from __future__ import annotations
import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# ROOT 是 siliao/ 项目根,不是 build/export/
ROOT = Path(__file__).parent.parent.parent
SCHEMA = ROOT / "query/worker/schema.sql"
SEED = ROOT / "build/export/seed.sql"
SEED_PAGES_M3 = ROOT / "build/export/seed_pages_m3.sql"
OUT = ROOT / "evals/bge_m3_cache.json"
BGE_URL = "http://127.0.0.1:8080/v1/embeddings"
BGE_MODEL = "BAAI/bge-m3"


def build_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.executescript(SEED.read_text(encoding="utf-8"))
    if SEED_PAGES_M3.exists() and SEED_PAGES_M3.stat().st_size > 0:
        con.executescript(SEED_PAGES_M3.read_text(encoding="utf-8"))
    return con


def health_check() -> dict:
    for path in ("/health", "/healthz"):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:8080{path}", timeout=10) as r:
                return json.loads(r.read())
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
            continue
    raise RuntimeError(f"bge server not responding on 127.0.0.1:8080")


# === [2026-09-20] 双模式:bge HTTP / bge in-process ===
# 默认 in-process,避免 bge_server.py Windows 启动卡死 (实测)
_BGE_INSTANCE = None


def _get_bge_model():
    """模块级 lazy singleton:首次调用加载 SentenceTransformer, ~25 秒"""
    global _BGE_INSTANCE
    if _BGE_INSTANCE is not None:
        return _BGE_INSTANCE
    # env 必须在 import sentence_transformers 之前设
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    import httpx  # noqa: E402
    _orig = httpx.Client.__init__
    def _ps(self, *a, **kw): kw.setdefault("trust_env", False); return _orig(self, *a, **kw)
    httpx.Client.__init__ = _ps

    from sentence_transformers import SentenceTransformer  # noqa: E402
    cache_dir = str(ROOT / ".models/hf")
    print(f"[bge] loading BAAI/bge-m3 from {cache_dir} (CPU, 25s)...", flush=True)
    import time as _t
    t0 = _t.time()
    _BGE_INSTANCE = SentenceTransformer("BAAI/bge-m3", cache_folder=cache_dir, device="cpu")
    print(f"[bge] loaded in {_t.time()-t0:.1f}s, dim={_BGE_INSTANCE.get_embedding_dimension()}",
          flush=True)
    return _BGE_INSTANCE


def embed_batch(texts: list[str], max_retries: int = 3) -> list[list[float]]:
    """调 bge (in-process 默认, --http 走 bge_server)"""
    if USE_HTTP:
        return _embed_batch_http(texts, max_retries)
    return _embed_batch_inprocess(texts)


def _embed_batch_inprocess(texts: list[str]) -> list[list[float]]:
    m = _get_bge_model()
    import numpy as _np
    # batch_size 是 sentence_transformers 内部小批量,bge-m3 推荐 16-32
    vecs = m.encode(texts, normalize_embeddings=True, show_progress_bar=False,
                    batch_size=16, convert_to_numpy=True)
    return [v.tolist() for v in vecs]


def _embed_batch_http(texts: list[str], max_retries: int = 3) -> list[list[float]]:
    """走 bge_server /v1/embeddings (实验性, Windows 下 bge_server 启动可能卡)"""
    body = json.dumps({"input": texts, "model": BGE_MODEL}).encode("utf-8")
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                BGE_URL,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=180) as r:
                payload = json.loads(r.read())
            return [item["embedding"] for item in payload["data"]]
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            wait = 2 ** attempt
            print(f"  [retry {attempt+1}/{max_retries}] {type(e).__name__}: {e}; sleep {wait}s",
                  file=sys.stderr, flush=True)
            import time as _t
            _t.sleep(wait)
    raise RuntimeError(f"bge embed failed after {max_retries} retries: {last_err}")


USE_HTTP: bool = False  # 由 main() 根据 args 注入


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=32,
                        help="每次传给 sentence_transformers 的 article 数")
    parser.add_argument("--resume", action="store_true", help="skip already embedded articles")
    parser.add_argument("--http", action="store_true", help="用 bge_server.py HTTP 模式 (默认 in-process)")
    parser.add_argument("--max-chars", type=int, default=2000,
                        help="truncate each article text to this many chars (bge-m3 max=8192 token ~= 20000 char, 我们截前 2000 字符保证速度)")
    args = parser.parse_args()

    global USE_HTTP
    USE_HTTP = args.http

    if not USE_HTTP:
        # in-process 模式:预热,失败直接 raise
        _get_bge_model()
    else:
        # http 模式:健康检查
        print("[check] bge server health...", flush=True)
        hc = health_check()
        if hc.get("status") != "ok":
            print(f"[FAIL] bge server not ready: {hc}", file=sys.stderr)
            return 1
        print(f"[check] model={hc.get('model')} dim={hc.get('dim')}", flush=True)
        if hc.get("dim") != 1024:
            print(f"[WARN] dim={hc.get('dim')} (expected 1024 for bge-m3)", flush=True)

    # Load existing cache for resume
    done: dict[str, list[float]] = {}
    if args.resume and OUT.exists():
        prev = json.loads(OUT.read_text(encoding="utf-8"))
        for aid, d_, v in prev.get("articles", []):
            done[aid] = v
        print(f"[resume] loaded {len(done)} existing embeddings from {OUT}", flush=True)

    # Load articles
    con = build_db()
    rows = con.execute(
        "SELECT article_id, doc_id, text FROM articles_fts"
    ).fetchall()
    print(f"[scan] {len(rows)} articles from sqlite", flush=True)

    # Filter to do
    todo = [(aid, did, text) for aid, did, text in rows if aid not in done]
    print(f"[todo] {len(todo)} new + {len(done)} cached = {len(rows)} total", flush=True)

    results: list[tuple[str, str, list[float]]] = list(done.items())  # type: ignore
    # convert dict to list form (will rewrite at end)
    results = [(aid, "", vec) for aid, vec in done.items()]

    t0 = time.time()
    dim_seen: int | None = None

    for i in range(0, len(todo), args.batch_size):
        batch = todo[i:i + args.batch_size]
        aids = [a for a, _, _ in batch]
        texts = [t[: args.max_chars] if t else "" for _, _, t in batch]
        vecs = embed_batch(texts)
        if dim_seen is None and vecs:
            dim_seen = len(vecs[0])
        for aid, did, v in zip(aids, [d for _, d, _ in batch], vecs):
            results.append((aid, did, v))

        done_count = i + len(batch)
        elapsed = time.time() - t0
        eta = elapsed * (len(todo) - done_count) / max(done_count, 1)
        print(f"[{done_count:>4}/{len(todo)}] +{len(batch)} in {elapsed:.1f}s, "
              f"eta {eta:.0f}s, last_dim={len(vecs[0])}", flush=True)

        # 增量保存 (每 50 条 OR 最后一批)
        if done_count % 50 == 0 or done_count == len(todo):
            _save(results, dim_seen or 1024, BGE_MODEL)
            print(f"  [save] {OUT} ({(OUT.stat().st_size/1024/1024):.2f} MB)", flush=True)

    print(f"[done] {len(results)} embeddings in {time.time() - t0:.1f}s", flush=True)
    _save(results, dim_seen or 1024, BGE_MODEL)
    print(f"[OK] {OUT} ({(OUT.stat().st_size/1024/1024):.2f} MB)", flush=True)
    return 0


def _save(articles: list[tuple[str, str, list[float]]], dim: int, model: str) -> None:
    payload = {"model": model, "dim": dim, "articles": articles}
    OUT.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())