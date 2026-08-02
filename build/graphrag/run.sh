#!/usr/bin/env bash
# GraphRAG 索引构建总入口
#
# 用法:
#   1. cp .env.example .env  并填 GRAPHRAG_API_KEY
#   2. cp data/markdown/<doc_id>/articles/*.md input/
#   3. ./run.sh
set -e

cd "$(dirname "$0")"

if [ ! -f .env ]; then
    echo "[ERR] .env 缺失,先 cp .env.example .env 并填 DeepSeek API Key" >&2
    exit 1
fi

# 检查 input 目录是否有文件
shopt -s nullglob
if [ ${#input[@]} -eq 0 ]; then
    echo "[ERR] input/ 目录为空,先复制法规章节 md" >&2
    exit 1
fi

echo "[graphrag] 开始构建,共 ${#input[@]} 个章节..."
graphrag index --root . --verbose