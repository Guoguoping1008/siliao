"""
MinerU OCR 包装: 把 data/raw/ 下的扫描版 PDF / 图片转成 Markdown。

为什么是 MinerU 而不是 PyPDF/pytesseract:
- 法规扫描版经常含表格、印章、装订线,MinerU 版面分析能保留结构
- 输出 Markdown(而非纯文本),后续章节切分器能直接吃
- 内置公式/图片描述

调用: python build/ocr/run_mineru.py <input.pdf|dir> <output_dir>

依赖: pip install -U magic-pdf[full]
参考: https://github.com/opendatalab/MinerU
"""

from __future__ import annotations
import subprocess
import sys
from pathlib import Path


def run_mineru(input_path: Path, output_dir: Path) -> Path:
    """
    调用 magic_pdf(MinerU Python 包)处理单文件,返回该文件产物目录。
    实际 MinerU CLI:
        magic-pdf pdf-command --pdf <input> --output <output>
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "magic-pdf", "pdf-command",
        "--pdf", str(input_path),
        "--output", str(output_dir),
    ]
    print(f"[OCR] running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

    # MinerU 输出结构: <output_dir>/<input_stem>/auto/<stem>.md
    stem = input_path.stem
    md = output_dir / stem / "auto" / f"{stem}.md"
    if not md.exists():
        raise FileNotFoundError(f"MinerU 未产出 {md}")
    return md


def main():
    inp = Path(sys.argv[1])
    out_root = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data/markdown")

    inputs = list(inp.glob("*.pdf")) if inp.is_dir() else [inp]
    for f in inputs:
        doc_id = f.stem
        target = out_root / doc_id
        md = run_mineru(f, target)
        print(f"[OK] OCR done: {f.name} -> {md}")


if __name__ == "__main__":
    main()