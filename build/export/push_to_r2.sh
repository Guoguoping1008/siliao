#!/usr/bin/env bash
# Cloudflare 上传总入口: R2 放原文/索引, D1 放 metadata
#
# 前置:  wrangler login && wrangler r2 bucket create siliao-index
#        wrangler d1 create siliao-db && 在 query/worker/wrangler.toml 里填 database_id

set -e
cd "$(dirname "$0")/../../query/worker"

echo "[push] uploading JSON to R2..."
for f in entities relationships text_units communities community_reports documents; do
    if [ -f "../../data/index/${f}.json" ]; then
        wrangler r2 object put "siliao-index/${f}.json" --file "../../data/index/${f}.json" --remote
    fi
done

echo "[push] uploading embeddings to Vectorize..."
if [ -f ../../data/index/vectors.ndjson ]; then
    wrangler vectorize insert feed-law-index --file ../../data/index/vectors.ndjson
fi

echo "[push] updating D1 metadata..."
wrangler d1 execute siliao-db --remote --file ./schema.sql
wrangler d1 execute siliao-db --remote --command "INSERT OR REPLACE INTO index_meta (id, doc_count, entity_count, updated_at) VALUES ('main', $(jq '.doc_count' ../../data/index/index_meta.json), $(jq '.entity_count' ../../data/index/index_meta.json), datetime('now'))"

echo "[push] DONE"