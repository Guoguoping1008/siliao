"""
bge-m3 检索服务:OpenAI 兼容 embedding + /v1/search 检索 endpoint
============================================================

[2026-09-20 玄穹 CEO 决策 C-b]
为什么:
- CF Workers 边缘跑不了 Python/sentence_transformers
- bge_server.py v1 只算 embedding,corpus 每次要重算 → 太慢
- v2 启动时把 bge_m3_cache.json (corpus 向量) + articles_cache.json (text) 加载到内存
- 暴露 /v1/search { query, top_k, doc_filter } → 算 query embedding + 余弦 top-k
- Workers 调 /v1/search 拿 bge 召回,再和 D1 FTS5 hybrid

启动:
    export BGE_MODEL=BAAI/bge-m3
    export BGE_PORT=8080
    export BGE_CACHE=E:/workspace/siliao/evals/bge_m3_cache.json
    export BGE_ARTICLES=E:/workspace/siliao/evals/articles_cache.json
    python build/proxy/bge_server.py

接口:
    POST /v1/embeddings      OpenAI 兼容,算单/批量 embedding
        body  : {"input": "str" | ["str", ...], "model": "BAAI/bge-m3"}
        reply : {"data": [{"embedding": [...], "index": 0}], ...}

    POST /v1/search          语义检索 endpoint (C-b 核心)
        body  : {"query": "str", "top_k": 20, "doc_id": "..." (可选)}
        reply : {"hits": [{"article_id": "...", "doc_id": "...", "score": 0.83}, ...]}

    GET  /health             探活 + cache 状态
        reply : {"status": "ok", "model": "...", "dim": 1024,
                 "corpus_size": 649, "cache_loaded": true, "elapsed_ms": ...}

性能:
    - 启动 ~25s (模型加载)
    - corpus 缓存加载 <1s
    - 单 query 检索 <100ms (CPU)
    - bge-m3 维度 1024,需 normalize_embeddings=True
"""

from __future__ import annotations
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# === [2026-09-20 玄穹 CEO 决策 C-a] ===
# 强制走 hf-mirror.com + 禁用 httpx 系统代理(Windows Clash 127.0.0.1:7897 撞 SSL EOF)
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "120")

import httpx  # noqa: E402
_orig_client_init = httpx.Client.__init__
_orig_async_client_init = httpx.AsyncClient.__init__
def _patched_sync_client_init(self, *a, **kw):
    kw.setdefault("trust_env", False)
    return _orig_client_init(self, *a, **kw)
def _patched_async_client_init(self, *a, **kw):
    kw.setdefault("trust_env", False)
    return _orig_async_client_init(self, *a, **kw)
httpx.Client.__init__ = _patched_sync_client_init
httpx.AsyncClient.__init__ = _patched_async_client_init

MODEL_NAME = os.environ.get("BGE_MODEL", "BAAI/bge-m3")
PORT = int(os.environ.get("BGE_PORT", "8080"))
HOST = os.environ.get("BGE_HOST", "127.0.0.1")
CACHE_PATH = Path(os.environ.get(
    "BGE_CACHE",
    str(Path(__file__).parent.parent.parent / "evals" / "bge_m3_cache.json"),
))
ARTICLES_PATH = Path(os.environ.get(
    "BGE_ARTICLES",
    str(Path(__file__).parent.parent.parent / "evals" / "articles_cache.json"),
))

_model = None
_corpus_vecs = None       # numpy array (N, 1024), L2 normalized
_corpus_ids = None        # list[str] N article_ids (与 vecs 行对齐)
_corpus_doc_ids = None    # list[str] N doc_ids
_corpus_text = None       # dict[article_id] -> text snippet (前 600 字)
_startup_time = time.time()


def get_model():
    """延迟加载 bge-m3 模型

    ⚠️ 必须指定 **本地缓存目录**(cache_folder) —— 否则 sentence_transformers
       会去 hf-mirror.com 拉模型, 而国内网络下 hf-mirror 经常连不上
       (实测: 5 次重试全 timeout, 服务起不来)。
       模型已在 .models/hf/ 里(embed_articles.py 早就下好了),
       用 cache_folder 指过去即可, 完全离线可用。

       也支持 HF_HUB_OFFLINE=1 强制离线。
    """
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        cache_dir = os.environ.get("BGE_CACHE_DIR") or str(
            Path(__file__).resolve().parent.parent.parent / ".models" / "hf"
        )
        print(f"[bge] loading {MODEL_NAME} (cache_folder={cache_dir})...", flush=True)
        t0 = time.time()
        kwargs = {"cache_folder": cache_dir, "device": "cpu"}
        if os.environ.get("HF_HUB_OFFLINE") == "1":
            kwargs["local_files_only"] = True
        try:
            _model = SentenceTransformer(MODEL_NAME, **kwargs)
        except Exception as e:
            print(f"[bge] load failed with cache_folder, retrying offline: {e}", flush=True)
            kwargs["local_files_only"] = True
            _model = SentenceTransformer(MODEL_NAME, **kwargs)
        print(f"[bge] loaded in {time.time() - t0:.1f}s, "
              f"dim={_model.get_sentence_embedding_dimension()}", flush=True)
    return _model


def load_corpus():
    """启动时把 corpus 向量加载到 numpy,供 /v1/search 用"""
    global _corpus_vecs, _corpus_ids, _corpus_doc_ids, _corpus_text
    import numpy as np
    t0 = time.time()

    # 1. 向量
    if not CACHE_PATH.exists():
        print(f"[bge] WARN: cache {CACHE_PATH} not found, /v1/search 不可用", flush=True)
        _corpus_vecs = np.zeros((0, 1024), dtype=np.float64)
        _corpus_ids = []
        _corpus_doc_ids = []
        _corpus_text = {}
        return False

    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    _corpus_ids = [a[0] for a in cache["articles"]]
    _corpus_vecs = np.array([a[2] for a in cache["articles"]], dtype=np.float32)
    dim_seen = _corpus_vecs.shape[1]

    # 2. 元数据 (doc_id + text snippet)
    if ARTICLES_PATH.exists():
        articles = json.loads(ARTICLES_PATH.read_text(encoding="utf-8"))
        id_to_meta = {a[0]: (a[1], a[2][:600]) for a in articles}
    else:
        id_to_meta = {}

    _corpus_doc_ids = [id_to_meta.get(aid, ("", ""))[0] for aid in _corpus_ids]
    _corpus_text = {aid: id_to_meta.get(aid, ("", ""))[1] for aid in _corpus_ids}

    print(f"[bge] corpus loaded: {_corpus_vecs.shape[0]} articles, "
          f"dim={dim_seen}, elapsed={time.time() - t0:.2f}s", flush=True)
    print(f"[bge] cache: {CACHE_PATH}", flush=True)
    print(f"[bge] articles: {ARTICLES_PATH}", flush=True)
    return True


def search_corpus(query: str, top_k: int = 20, doc_filter: str = ""):
    """bge-m3 语义检索: 算 query embedding + 余弦相似度 top-k

    返回: [(article_id, doc_id, score, excerpt), ...] 按 score 降序
    """
    import numpy as np
    if _corpus_vecs is None or len(_corpus_ids) == 0:
        raise RuntimeError("corpus not loaded, 跑 python build/export/embed_articles.py 先生成 cache")

    model = get_model()
    # bge-m3 短 query 推荐 instruction prefix,长 query 不加
    # 检索类 query 加,生成类不加 —— 我们走 RAG,统一加
    qvec = model.encode(
        [query],
        normalize_embeddings=True,
        show_progress_bar=False,
        prompt=None,  # bge-m3 默认不需 instruction
    )[0]
    qvec = np.asarray(qvec, dtype=np.float32)

    # 余弦 = dot (因为 L2 normalized)
    sims = _corpus_vecs @ qvec  # (N,)

    # doc 过滤
    if doc_filter:
        mask = np.array([d == doc_filter for d in _corpus_doc_ids])
        sims = np.where(mask, sims, -1e9)

    top_k = min(top_k, len(_corpus_ids))
    # argpartition 比 argsort 快,只要 top-k
    idx = np.argpartition(-sims, top_k - 1)[:top_k]
    idx = idx[np.argsort(-sims[idx])]

    hits = []
    for i in idx:
        score = float(sims[i])
        if score <= -1e8:
            continue
        aid = _corpus_ids[i]
        hits.append({
            "article_id": aid,
            "doc_id": _corpus_doc_ids[i] if i < len(_corpus_doc_ids) else "",
            "score": score,
            "excerpt": _corpus_text.get(aid, "") if _corpus_text else "",
        })
    return hits


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("[bge] " + (fmt % args) + "\n")

    def _send_json(self, status: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):  # noqa: N802
        if self.path in ("/health", "/healthz"):
            dim = None
            try:
                m = get_model()
                dim = m.get_sentence_embedding_dimension()
            except Exception:
                pass
            corpus_size = len(_corpus_ids) if _corpus_ids else 0
            return self._send_json(200, {
                "status": "ok",
                "model": MODEL_NAME,
                "dim": dim,
                "corpus_size": corpus_size,
                "cache_loaded": corpus_size > 0,
                "uptime_sec": round(time.time() - _startup_time, 1),
            })
        return self._send_json(404, {"error": "not_found", "path": self.path})

    def do_POST(self):  # noqa: N802
        if self.path not in ("/v1/embeddings", "/v1/embeddings/",
                             "/v1/search", "/v1/search/"):
            return self._send_json(404, {"error": "unknown_path", "path": self.path})

        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return self._send_json(400, {"error": "empty_body"})
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError as e:
            return self._send_json(400, {"error": "bad_json", "detail": str(e)})

        # /v1/search
        if self.path.startswith("/v1/search"):
            return self._handle_search(payload)

        # /v1/embeddings (OpenAI 兼容)
        return self._handle_embeddings(payload)

    def _handle_search(self, payload: dict):
        q = (payload.get("query") or "").strip()
        if not q:
            return self._send_json(400, {"error": "missing_query"})
        top_k = int(payload.get("top_k", 20))
        doc_filter = payload.get("doc_id") or ""
        try:
            t0 = time.time()
            hits = search_corpus(q, top_k=top_k, doc_filter=doc_filter)
            elapsed = time.time() - t0
            return self._send_json(200, {
                "object": "list",
                "query": q,
                "model": MODEL_NAME,
                "top_k": top_k,
                "hits": hits,
                "_meta": {"elapsed_sec": round(elapsed, 3), "corpus_size": len(_corpus_ids)},
            })
        except Exception as e:
            return self._send_json(500, {"error": "search_failed", "detail": str(e)})

    def _handle_embeddings(self, payload: dict):
        inp = payload.get("input")
        if inp is None:
            return self._send_json(400, {"error": "missing_input"})
        if isinstance(inp, str):
            inputs = [inp]
        elif isinstance(inp, list):
            inputs = inp
        else:
            return self._send_json(400, {"error": "input_must_be_str_or_list"})

        model_name = payload.get("model", MODEL_NAME)
        try:
            model = get_model()
            t0 = time.time()
            vecs = model.encode(inputs, normalize_embeddings=True, show_progress_bar=False)
            elapsed = time.time() - t0
        except Exception as e:
            return self._send_json(500, {"error": "encode_failed", "detail": str(e)})

        data = [
            {"object": "embedding", "embedding": vec.tolist(), "index": i}
            for i, vec in enumerate(vecs)
        ]
        return self._send_json(200, {
            "object": "list",
            "data": data,
            "model": model_name,
            "usage": {
                "prompt_tokens": sum(len(s) for s in inputs),
                "total_tokens": sum(len(s) for s in inputs),
            },
            "_meta": {"elapsed_sec": round(elapsed, 3), "batch_size": len(inputs)},
        })


def main():
    print(f"[bge] listening on {HOST}:{PORT}", flush=True)
    print(f"[bge] model: {MODEL_NAME}", flush=True)
    print(f"[bge] preloading model (首次启动会下载 ~2.27GB, 可能 5-15 分钟)...", flush=True)
    t0 = time.time()
    get_model()
    print(f"[bge] model preloaded in {time.time() - t0:.1f}s", flush=True)

    # 加载 corpus 向量到内存
    load_corpus()

    print(f"[bge] ready: POST /v1/embeddings /v1/search", flush=True)
    print(f"[bge] health: curl http://{HOST}:{PORT}/health", flush=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
