"""
GraphRAG 索引产物扁平化: parquet -> JSON,供 Cloudflare Workers 加载。

输入: build/graphrag/output/<timestamp>/artifacts/*.parquet
输出:
  data/index/entities.json
  data/index/relationships.json
  data/index/text_units.json
  data/index/communities.json
  data/index/community_reports.json
  data/index/documents.json
  data/index/embeddings_meta.json   # 含 chunk_id -> vector id 的映射,准备灌 Vectorize
"""

from __future__ import annotations
import json
import sys
from pathlib import Path
import pandas as pd


def flatten_parquet(src: Path, dst: Path) -> int:
    if not src.exists():
        print(f"[WARN] {src} not found, skip")
        return 0
    df = pd.read_parquet(src)
    # 统一空值为 None
    df = df.where(pd.notnull(df), None)
    rows = df.to_dict(orient="records")
    dst.write_text(json.dumps(rows, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
    print(f"[OK] {src.name} -> {dst.name}  ({len(rows)} rows)")
    return len(rows)


def main():
    artifacts = Path(sys.argv[1])  # e.g. build/graphrag/output/2026.../artifacts
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data/index")
    out_dir.mkdir(parents=True, exist_ok=True)

    mapping = {
        "entities":          "entities.parquet",
        "relationships":     "relationships.parquet",
        "text_units":        "text_units.parquet",
        "communities":       "communities.parquet",
        "community_reports": "community_reports.parquet",
        "documents":         "documents.parquet",
    }
    counts = {}
    for key, fname in mapping.items():
        n = flatten_parquet(artifacts / fname, out_dir / f"{key}.json")
        counts[key] = n

    # 元信息(给 Cloudflare D1 用)
    (out_dir / "index_meta.json").write_text(
        json.dumps({"doc_count": counts.get("documents", 0),
                    "entity_count": counts.get("entities", 0),
                    "relationship_count": counts.get("relationships", 0),
                    "chunk_count": counts.get("text_units", 0),
                    "community_count": counts.get("communities", 0)},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[DONE] index meta: {out_dir / 'index_meta.json'}")


if __name__ == "__main__":
    main()