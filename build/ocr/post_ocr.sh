#!/usr/bin/env bash
# OCR 跑完后的一键后处理
# 用法:  bash build/ocr/post_ocr.sh feed-law-collection-2023-full

set -euo pipefail
DOC_ID="${1:?usage: post_ocr.sh <doc_id>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY=".venv-ocr/Scripts/python.exe"

BASE="data/markdown/${DOC_ID}"
PAGES_DIR="${BASE}/pages"
RAW_OCR_DIR="${BASE}/raw_ocr"
SINGLE_PAGES_DIR="${BASE}/single_pages"

echo "═══════════════════════════════════════"
echo "  post_ocr  ${DOC_ID}"
echo "═══════════════════════════════════════"

# 1. 校验
if [ ! -d "$PAGES_DIR" ]; then
    echo "FAIL: $PAGES_DIR 不存在, OCR 没跑完?"
    exit 1
fi
PAGE_COUNT=$(ls "$PAGES_DIR"/*.md 2>/dev/null | wc -l)
echo "▶ pages/*.md: ${PAGE_COUNT} 个"

# 2. 提取页码 + 按页码排序 (失败时 fallback 时间戳)
echo ""
echo "▶ 1/4 extract_page_order.py"
$PY build/ocr/extract_page_order.py "${DOC_ID}" 2>&1 | tail -20

# 3. 拼 merged.md
echo ""
echo "▶ 2/4 page_joiner.py  (按时间戳/页码 sort 后拼 merged.md)"
$PY build/ocr/page_joiner.py "${PAGES_DIR}" 2>&1
# 覆盖输出: 拼出 merged.md
MERGED="${BASE}/merged.md"
if [ ! -f "$MERGED" ]; then
    echo "FAIL: merged.md 没生成"
    exit 1
fi
echo "  merged.md: $(wc -l < "$MERGED") lines, $(wc -c < "$MERGED") bytes"

# 4. 章节切分
echo ""
echo "▶ 3/4 chapter_splitter.py"
$PY build/ocr/chapter_splitter.py "${MERGED}" "${DOC_ID}" . 2>&1 | tail -30

# 5. 表格还原
echo ""
echo "▶ 4/4 table_reconstruct.py  (--out-sub pages_tbl)"
$PY build/ocr/table_reconstruct.py "${BASE}" --out-sub pages_tbl --header "饲料法规文件" 2>&1 | tail -20

# 6. 简报
echo ""
echo "═══════════════════════════════════════"
echo "  简报"
echo "═══════════════════════════════════════"
echo "pages:     ${PAGE_COUNT}"
echo "merged:    $(wc -l < "$MERGED") lines"
echo "chapters:  $(ls "${BASE}/chapters" 2>/dev/null | wc -l)"
echo "articles:  $(ls "${BASE}/articles" 2>/dev/null | wc -l)"
echo "tbl pages: $(ls "${BASE}/pages_tbl" 2>/dev/null | wc -l)"
