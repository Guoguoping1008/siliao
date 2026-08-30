"""
手机翻拍图片 → Markdown: 串接 preprocess + PaddleOCR。

输入:  raw-pic/*.jpg
输出:  data/markdown/<doc_id>/articles/<article_id>.md
       data/markdown/<doc_id>/raw_ocr/<image_stem>.json  (PaddleOCR 原始结果)

为什么不直接改 run_mineru.py:
- run_mineru.py 是 magic-pdf 包装,只接 PDF
- 本脚本专门给手机翻拍场景用 (PaddleOCR + OpenCV 预处理)
- 走 chapter_splitter.py 前需要先拼章节, 所以输出按"页→单页 markdown"

用法:
  python build/ocr/pic2md.py raw-pic/ feed-law-collection-2023

输出结构:
  data/markdown/<doc_id>/
    raw_ocr/<image_stem>.json     # PaddleOCR 原始输出 (boxes + texts + scores)
    pages/<seq>.md                 # 按 PaddleOCR 行序拼出的单页 markdown
    preprocessed/<image_stem>.jpg # 预处理后的图片
    pages/<seq>.jpg               # 与 pages/<seq>.md 一一对应
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

# 让脚本能找到同目录下的 preprocess
sys.path.insert(0, str(Path(__file__).parent))
from preprocess import preprocess as do_preprocess  # noqa: E402

from paddleocr import PaddleOCR  # noqa: E402


def init_ocr(use_gpu: bool = False) -> PaddleOCR:
    """PaddleOCR 初始化 (中文 v4 模型, 开方向分类)"""
    return PaddleOCR(
        use_angle_cls=True,
        lang="ch",
        use_gpu=use_gpu,
        show_log=False,
    )


def ocr_one(ocr: PaddleOCR, img_path: Path) -> list[dict]:
    """
    对单张图跑 PaddleOCR, 返回按 y 坐标排好序的文本行。
    每行: {"bbox": [[x,y],...], "text": str, "score": float}
    """
    raw = ocr.ocr(str(img_path), cls=True)
    lines = []
    if not raw or not raw[0]:
        return lines
    for box, (text, score) in raw[0]:
        lines.append({
            "bbox": [[float(x), float(y)] for x, y in box],
            "text": text,
            "score": float(score),
        })

    # 按 y 坐标排序 (取 bbox[0][1] 即左上 y)
    lines.sort(key=lambda ln: (min(p[1] for p in ln["bbox"]), min(p[0] for p in ln["bbox"])))
    return lines


def group_by_paragraph(lines: list[dict], y_gap_ratio: float = 0.6) -> list[list[dict]]:
    """
    把 PaddleOCR 行聚成段落: y 间距小于上一行高度 * y_gap_ratio 的归一段。
    返回段落列表, 每段是一个 line 列表。
    """
    if not lines:
        return []

    def line_height(ln: dict) -> float:
        ys = [p[1] for p in ln["bbox"]]
        return max(ys) - min(ys)

    paragraphs = [[lines[0]]]
    for prev, cur in zip(lines, lines[1:]):
        prev_bottom = max(p[1] for p in prev["bbox"])
        cur_top = min(p[1] for p in cur["bbox"])
        gap = cur_top - prev_bottom
        if gap < line_height(prev) * y_gap_ratio:
            paragraphs[-1].append(cur)
        else:
            paragraphs.append([cur])
    return paragraphs


def paragraph_to_md(para: list[dict]) -> str:
    """一段 OCR 行 → markdown 行 (取该段最左 + 最右 bbox, 保留水平拼接的语义)"""
    if not para:
        return ""
    texts = [ln["text"].strip() for ln in para]
    return " ".join(t for t in texts if t)


def page_to_markdown(lines: list[dict], page_number: int | None = None) -> str:
    """整页 OCR → markdown"""
    paras = group_by_paragraph(lines)
    md_lines = []
    if page_number is not None:
        md_lines.append(f"<!-- page: {page_number} -->")
    for para in paras:
        md = paragraph_to_md(para)
        if md:
            md_lines.append(md)
    return "\n\n".join(md_lines)


def process_dir(
    src_dir: Path,
    doc_id: str,
    *,
    use_gpu: bool = False,
    preprocessed_dir: Path | None = None,
) -> list[Path]:
    """
    处理整个目录的图片, 输出到 data/markdown/<doc_id>/pages/
    返回所有生成的 md 文件路径(按图片文件名排序, 但不保证物理页序)。
    """
    base = Path("data/markdown") / doc_id
    raw_ocr_dir = base / "raw_ocr"
    pages_dir = base / "pages"
    preprocessed_root = preprocessed_dir or base / "preprocessed"
    meta_dir = base / "preprocess_meta"
    raw_ocr_dir.mkdir(parents=True, exist_ok=True)
    pages_dir.mkdir(parents=True, exist_ok=True)
    preprocessed_root.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    ocr = init_ocr(use_gpu=use_gpu)
    img_paths = sorted(src_dir.glob("*.jpg"))
    print(f"[pic2md] {len(img_paths)} 张图 → {pages_dir}")

    md_files: list[Path] = []
    for i, img_path in enumerate(img_paths, 1):
        print(f"[pic2md] ({i}/{len(img_paths)}) {img_path.name}")

        # 1. 预处理 (透视校正 + 水印裁剪)
        result = do_preprocess(img_path, preprocessed_root, meta_dir)
        clean_img = result.out_path

        # 2. OCR
        lines = ocr_one(ocr, clean_img)
        (raw_ocr_dir / f"{img_path.stem}.json").write_text(
            json.dumps(lines, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 3. 拼 markdown
        md = page_to_markdown(lines, page_number=i)
        md_path = pages_dir / f"{img_path.stem}.md"
        md_path.write_text(md, encoding="utf-8")
        md_files.append(md_path)

    print(f"[pic2md] 完成: {len(md_files)} 个 markdown 文件")
    return md_files


def main():
    p = argparse.ArgumentParser()
    p.add_argument("src_dir", type=Path, help="raw-pic 目录")
    p.add_argument("doc_id", help="目标 doc_id, 例如 feed-law-collection-2023")
    p.add_argument("--gpu", action="store_true", help="启用 GPU")
    p.add_argument("--limit", type=int, default=0, help="只处理前 N 张 (0 = 全部)")
    args = p.parse_args()

    src = args.src_dir
    if args.limit > 0:
        # 临时只取前 N 张
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            for i, p in enumerate(sorted(src.glob("*.jpg"))[: args.limit]):
                (tmp / p.name).write_bytes(p.read_bytes())
            process_dir(tmp, args.doc_id, use_gpu=args.gpu)
    else:
        process_dir(src, args.doc_id, use_gpu=args.gpu)


if __name__ == "__main__":
    main()