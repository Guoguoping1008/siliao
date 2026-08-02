"""
bge-large-zh embedding 生成: 把 text_units 转成 Vectorize 可灌的 ndjson。

用法:
    1. 启动 bge 服务:  uv run --with mteb vllm serve BAAI/bge-large-zh-v1.5 --port 8080
    2. python build/export/embed_to_vectorize.py data/index/text_units.json data/index/vectors.ndjson
"""

from __future__ import annotations
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path


EMBED_URL = "http://127.0.0.1:8080/v1/embeddings"


def embed_batch(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i: i + batch_size]
        body = json.dumps({"input": batch, "model": "BAAI/bge-large-zh-v1.5"}).encode()
        req = urllib.request.Request(EMBED_URL, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            out.extend(d["embedding"] for d in data["data"])
        except urllib.error.URLError as e:
            print(f"[ERR] embedding service unavailable: {e}", file=sys.stderr)
            raise
        print(f"  embedded {len(out)}/{len(texts)}", end="\r")
    print()
    return out


def main():
    text_units_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    units = json.loads(text_units_path.read_text(encoding="utf-8"))
    # 拼文本: chapter_id + article_id + 正文
    texts = [f"{u.get('chapter_id', '')} {u.get('article_number', '')} {u.get('text', '')}" for u in units]
    vectors = embed_batch(texts)

    with out_path.open("w", encoding="utf-8") as f:
        for u, v in zip(units, vectors):
            f.write(json.dumps({
                "id": u.get("id"),
                "values": v,
                "metadata": {
                    "doc_id": u.get("document_id"),
                    "chapter_id": u.get("chapter_id"),
                    "article_id": u.get("article_id"),
                }
            }) + "\n")
    print(f"[DONE] wrote {len(units)} vectors to {out_path}")


if __name__ == "__main__":
    main()