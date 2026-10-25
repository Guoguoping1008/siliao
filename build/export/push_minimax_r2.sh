#!/usr/bin/env bash
# push_minimax_r2.sh —— 把 data/index/minimax 的条文/章节 markdown 推到 R2
#
# R2 key 约定: <doc_id>/articles/<r2_object_key>
#              <doc_id>/chapters/<r2_object_key>
# (r2_object_key 存在 D1 的 articles.r2_object_key / chapters.r2_object_key)
#
# 用法:
#   bash build/export/push_minimax_r2.sh              # local (miniflare)
#   bash build/export/push_minimax_r2.sh --remote     # 真 Cloudflare
#
# ⚠️ 每个 object 一次 wrangler 调用, 3000+ 个会非常慢。
#    优先用 Cloudflare API 批量上传 (见 push_minimax_r2.py)。

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKER="$REPO/query/worker"
IDX="$REPO/data/index/minimax"

REMOTE_FLAG=""
if [[ "${1:-}" == "--remote" ]]; then
  REMOTE_FLAG="--remote"
fi

cd "$WORKER"

# 读 doc_id → r2_object_key 映射 (从 articles.json / chapters.json)
python "$REPO/build/export/push_minimax_r2.py" --index "$IDX" ${REMOTE_FLAG:+$REMOTE_FLAG}
