"""
bge-large-zh-v1.5 的 OpenAI 兼容 embedding 服务
================================================

为什么:
- graphrag 的 openai_embedding 客户端会硬编码 POST /v1/embeddings
- 我们要本地跑 bge,就得暴露一个 OpenAI 兼容的 /v1/embeddings

启动:
    export BGE_MODEL=BAAI/bge-large-zh-v1.5       # 默认值
    export BGE_PORT=8080                           # 默认值
    python build/proxy/bge_server.py

监听:  127.0.0.1:8080

接口:
    POST /v1/embeddings
        body  : {"input": "str" | ["str", ...], "model": "BAAI/bge-large-zh-v1.5"}
        reply : {"object": "list", "data": [{"embedding": [...], "index": 0}], "model": "...", "usage": {...}}

    GET  /health   -> {"status": "ok", "model": "...", "dim": 1024}

注意:
- bge 建议加 normalize_embeddings=True(余弦相似度需要)
- graphrag 默认 cosine + 1024 维,与 bge-large-zh-v1.5 完全匹配
- CPU 跑慢:16 条短文大约 5-30 秒;长文 1-3 秒/段
"""

from __future__ import annotations
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# === [2026-09-20 玄穹 CEO 决策 C-a] ===
# 强制走 hf-mirror.com + 禁用 httpx 系统代理(Windows Clash 127.0.0.1:7897 撞 SSL EOF)
# + 禁用 xet CAS(走 hf-mirror 时 cas-server.xethub.hf.co 401 unauthorized)
# HF_ENDPOINT 必须在 import huggingface_hub 之前设置
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

MODEL_NAME = os.environ.get("BGE_MODEL", "BAAI/bge-large-zh-v1.5")
PORT = int(os.environ.get("BGE_PORT", "8080"))
HOST = os.environ.get("BGE_HOST", "127.0.0.1")

# 延迟到第一次请求再加载,避免启动失败也被噪音
_model = None


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        print(f"[bge] loading {MODEL_NAME} (首次启动会下载 ~400MB)...", flush=True)
        t0 = time.time()
        _model = SentenceTransformer(MODEL_NAME)
        # bge 的 instruction: 为短查询加 "为这个句子生成表示以用于检索相关文章: "
        # 但我们这里 input 主要是段落,直接 encode 即可,文档侧不加 instruction
        print(f"[bge] loaded in {time.time() - t0:.1f}s, dim={_model.get_sentence_embedding_dimension()}", flush=True)
    return _model


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("[bge] " + (fmt % args) + "\n")

    def _send_json(self, status: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path in ("/health", "/healthz"):
            try:
                m = get_model()
                dim = m.get_sentence_embedding_dimension()
            except Exception as e:
                return self._send_json(503, {"status": "loading", "error": str(e)})
            return self._send_json(200, {"status": "ok", "model": MODEL_NAME, "dim": dim})
        return self._send_json(404, {"error": "not_found", "path": self.path})

    def do_POST(self):  # noqa: N802
        if self.path not in ("/v1/embeddings", "/v1/embeddings/"):
            return self._send_json(404, {"error": "unknown_path", "path": self.path})

        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return self._send_json(400, {"error": "empty_body"})
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError as e:
            return self._send_json(400, {"error": "bad_json", "detail": str(e)})

        # OpenAI 兼容: input 可以是 str 或 list[str]
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
                "prompt_tokens": sum(len(s) for s in inputs),  # 粗估
                "total_tokens": sum(len(s) for s in inputs),
            },
            "_meta": {"elapsed_sec": round(elapsed, 3), "batch_size": len(inputs)},
        })


def main():
    print(f"[bge] listening on {HOST}:{PORT}", flush=True)
    print(f"[bge] model: {MODEL_NAME}", flush=True)
    print(f"[bge] graphrag config: api_base=http://{HOST}:{PORT}/v1, model={MODEL_NAME}", flush=True)
    print(f"[bge] health: curl http://{HOST}:{PORT}/health", flush=True)
    # === [2026-09-20 玄穹 CEO 决策 C-a] ===
    # 启动时预加载模型:避免第一个请求阻塞整个 server(2.27GB 下载会卡几分钟)
    # 也避免 ThreadingHTTPServer 单线程下 "loading" handler 把 listen socket 卡住
    print(f"[bge] preloading model (首次启动会下载 ~2.27GB, 可能 5-15 分钟)...", flush=True)
    t0 = time.time()
    get_model()
    print(f"[bge] preloaded in {time.time() - t0:.1f}s, ready for requests", flush=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True  # 工作线程不阻塞 server shutdown
    server.serve_forever()


if __name__ == "__main__":
    main()
