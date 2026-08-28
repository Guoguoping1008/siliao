#!/usr/bin/env bash
# Cloudflare 上传总入口: R2 放原文, D1 放元数据 + 全文索引
#
# 前置:
#   wrangler login
#   wrangler r2 bucket create siliao-index
#   wrangler d1 create siliao-db    # 拿到 database_id 填到 query/worker/wrangler.toml
#
# 用法:
#   ./push_to_r2.sh feed-law-2026 --remote   # 上传到 Cloudflare
#   ./push_to_r2.sh feed-law-2026 --local    # 仅 miniflare 本地

set -euo pipefail
DOC_ID="${1:?usage: push_to_r2.sh <doc_id> [--remote|--local]}"
REMOTE_FLAG="${2:---local}"

if [ ! -d "data/markdown/${DOC_ID}" ]; then
    echo "[ERR] data/markdown/${DOC_ID} 不存在,先跑 ingest.sh"
    exit 1
fi

cd "$(dirname "$0")/../../query/worker"

echo "[push] ${REMOTE_FLAG}: uploading chapters/*.md + articles/*.md to R2..."
for f in ../../data/markdown/"${DOC_ID}"/chapters/*.md; do
    [ -f "$f" ] || continue
    name=$(basename "$f")
    wrangler r2 object put "siliao-index/${DOC_ID}/chapters/${name}" --file "$f" "${REMOTE_FLAG}" >/dev/null
done
for f in ../../data/markdown/"${DOC_ID}"/articles/*.md; do
    [ -f "$f" ] || continue
    name=$(basename "$f")
    wrangler r2 object put "siliao-index/${DOC_ID}/articles/${name}" --file "$f" "${REMOTE_FLAG}" >/dev/null
done

echo "[push] initializing D1 schema..."
wrangler d1 execute siliao-db "${REMOTE_FLAG}" --file ./schema.sql

echo "[push] seeding D1 from articles.json + chapters.json..."
python ../../build/export/seed_d1.py \
    ../../data/markdown/"${DOC_ID}"/articles.json \
    ../../data/markdown/"${DOC_ID}"/chapters.json
wrangler d1 execute siliao-db "${REMOTE_FLAG}" --file ../../build/export/seed.sql

echo "[push] updating index_meta..."
doc_count=$(wrangler d1 execute siliao-db "${REMOTE_FLAG}" --command "SELECT COUNT(*) FROM documents" --json | python -c "import json,sys; print(json.load(sys.stdin)[0]['results'][0]['COUNT(*)'])")
art_count=$(wrangler d1 execute siliao-db "${REMOTE_FLAG}" --command "SELECT COUNT(*) FROM articles_fts" --json | python -c "import json,sys; print(json.load(sys.stdin)[0]['results'][0]['COUNT(*)'])")
wrangler d1 execute siliao-db "${REMOTE_FLAG}" --command "INSERT OR REPLACE INTO index_meta(id, doc_count, chunk_count, updated_at) VALUES('main', ${doc_count}, ${art_count}, datetime('now'))"

echo "[push] DONE: ${DOC_ID} → R2 + D1"
