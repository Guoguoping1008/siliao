# 数据摄入总入口: 一条命令完成 OCR -> 章节切分。
#
# 用法:  bash build/ingest.sh <doc_id>
# 前置:  data/raw/<doc_id>.md   (文本版)
#        或 data/raw/<doc_id>.pdf (扫描版,需 magic-pdf)

set -e

DOC_ID="${1:?usage: build/ingest.sh <doc_id>}"
RAW="data/raw/${DOC_ID}"
OUT="data/markdown/${DOC_ID}"

if [ -f "${RAW}.md" ]; then
    echo "[ingest] text source detected: ${RAW}.md"
    python build/ocr/chapter_splitter.py "${RAW}.md" "${DOC_ID}" "data"
elif [ -f "${RAW}.pdf" ]; then
    echo "[ingest] PDF source detected, running MinerU OCR..."
    python build/ocr/run_mineru.py "${RAW}.pdf" "${OUT}"
    # OCR 完后,chapters 目录可能不在子目录里,跑一次切分兜底
    python build/ocr/chapter_splitter.py "${OUT}/$(basename ${RAW} .pdf)/auto/$(basename ${RAW} .pdf).md" "${DOC_ID}" "data"
else
    echo "[ingest] no input found: ${RAW}.md or ${RAW}.pdf" >&2
    exit 1
fi

echo "[ingest] DONE: ${DOC_ID}"
ls "${OUT}/articles/" | wc -l | xargs echo "  articles:"
ls "${OUT}/chapters/" | wc -l | xargs echo "  chapters:"