#!/usr/bin/env bash
# 一条命令完成: ingest → graphrag(可选) → flatten → push
#
# 用法:
#   bash build/run_all.sh feed-law-2026            # 跳过 graphrag
#   bash build/run_all.sh feed-law-2026 --with-graphrag   # 跑 graphrag
#
# 前置:
#   1. data/raw/<doc_id>.md   (文本版) 或 .pdf (扫描版,需 MinerU)
#   2. wrangler login         (push 步骤)
#
# 步骤:
#   1. ingest.sh              OCR/章节切分 → data/markdown/<doc_id>/
#   2. graphrag(可选)         实体/关系抽取 → data/index/*.json
#   3. seed_d1.py             articles.json → build/export/seed.sql
#   4. push_to_r2.sh          R2 + D1(本地或 remote)

set -euo pipefail
DOC_ID="${1:?usage: run_all.sh <doc_id> [--with-graphrag]}"
WITH_GRAPHRAG="${2:-}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "═══════════════════════════════════════"
echo "  run_all.sh  ${DOC_ID}  ${WITH_GRAPHRAG}"
echo "═══════════════════════════════════════"

# 1. ingest
echo ""
echo "▶ 1/4 ingest.sh  (chapter_splitter)"
bash build/ingest.sh "${DOC_ID}"

# 2. graphrag(可选)
if [ "${WITH_GRAPHRAG}" = "--with-graphrag" ]; then
    echo ""
    echo "▶ 2/4 graphrag/run.sh"
    if [ ! -f build/graphrag/.env ]; then
        echo "  [SKIP] build/graphrag/.env 不存在,跳过 graphrag"
        echo "  如需开启: cp build/graphrag/.env.example build/graphrag/.env 并填 API key"
    else
        mkdir -p build/graphrag/input
        cp data/markdown/"${DOC_ID}"/articles/*.md build/graphrag/input/
        bash build/graphrag/run.sh
    fi
else
    echo ""
    echo "▶ 2/4 graphrag [SKIP]  (传 --with-graphrag 启用)"
fi

# 3. seed_d1 + push(本地 miniflare)
echo ""
echo "▶ 3/4 seed_d1.py"
python build/export/seed_d1.py \
    data/markdown/"${DOC_ID}"/articles.json \
    data/markdown/"${DOC_ID}"/chapters.json

# 4. push
echo ""
echo "▶ 4/4 push_to_r2.sh --local  (用 miniflare 本地 D1/R2)"
bash build/export/push_to_r2.sh "${DOC_ID}" --local

echo ""
echo "═══════════════════════════════════════"
echo "  DONE  ${DOC_ID}"
echo "═══════════════════════════════════════"
ls -la data/markdown/"${DOC_ID}"/articles/ | head -5
echo "  articles: $(ls data/markdown/${DOC_ID}/articles/ | wc -l)"
echo "  chapters: $(ls data/markdown/${DOC_ID}/chapters/ | wc -l)"
echo "  seed.sql: build/export/seed.sql ($(wc -l < build/export/seed.sql) lines)"
