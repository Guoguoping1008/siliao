#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF → 逐页图 → MiniMax VLM OCR → Markdown

为什么需要单独脚本(不能直接用 mm_ocr.py):
  mm_ocr.py 吃的是「拆好的单页扫描图」(Images_split/),按 stem 找源图。
  这里输入是 PDF,得先自己渲染成图。而且这个 PDF 的**文本层是坏的**:
  字体是 Identity-H CID 但没带可用的 ToUnicode CMap,
  `page.get_text()` 抽出来是 `犐犆犛６５．１２０` 这种乱码,
  但**渲染出来完全正常**(已目视确认)。所以只能走 OCR。

已实测:
  - 页面尺寸 A4,10 页,正文是正常中文排版(非扫描件)
  - 文本层不可用 → 必须 OCR
  - OCR 用 MiniMax-Text-01,图片缩到 <=1600px 宽(模型图像 token 上限)

用法:
  python build/ocr_pdf.py "GB 10648-2013 饲料标签.pdf" --out-dir minimax/04标准及标准目录/01_饲料标签
  python build/ocr_pdf.py "xxx.pdf" --out-dir ... --dry-run
"""
import argparse
import base64
import io
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

import pymupdf
from PIL import Image

API_URL = "https://api.minimaxi.com/v1/chat/completions"
MODEL = "MiniMax-Text-01"
FALLBACK_MODEL = "MiniMax-M3"
MAX_TOKENS = 16000
TIMEOUT = 180
MAX_RETRY = 3
TARGET_W = 1600
JPEG_QUALITY = 88

ENV_PATH = r"C:/Users/Administrator/AppData/Local/hermes/profiles/qingmang/.env"


def api_key() -> str:
    with open(ENV_PATH, encoding="utf-8") as f:
        for line in f:
            if line.startswith("MINIMAX_CN_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("MINIMAX_CN_API_KEY not found in " + ENV_PATH)


PROMPT = """这是一页中国国家标准文件（GB 标准）的扫描/渲染页，竖排内容已正常横向排版。
请把这一页的文字**完整、准确**地转写成 Markdown。

严格要求：
1. 忠实转写，**不要改写、不要缩写、不要总结、不要补充原文没有的内容**。
2. 保留原文的标题层级：文件标题用 `#`，章用 `##`，条用 `###`，更细的用 `####`。
3. 表格用 HTML `<table border="1" cellspacing="0" cellpadding="4">` 输出，
   `<tr>` / `<th>` / `<td>`，需要合并单元格时用 rowspan / colspan。
   表格前不要加任何解释文字。
4. 页眉页脚（如标准号、ICS 号、页码、"GB 10648—2013"页脚）**不要**转写。
5. 公式、编号、单位、括号、破折号（——）原样保留。
6. 如果某处看不清，写 `[无法辨认]`，**不要猜测**。
7. 只输出 Markdown 正文，不要外层代码块，不要任何前言后语。"""


def render_pdf(pdf_path: str, out_dir: str, dpi: int = 200) -> list:
    """PDF 每页渲染成 PNG,返回 [(png_path, page_index)]。"""
    os.makedirs(out_dir, exist_ok=True)
    doc = pymupdf.open(pdf_path)
    pages = []
    for i in range(doc.page_count):
        pix = doc[i].get_pixmap(dpi=dpi)
        png = os.path.join(out_dir, f"_page_{i+1:03d}.png")
        pix.save(png)
        pages.append(png)
        print(f"  rendered p{i+1} -> {os.path.basename(png)} ({pix.width}x{pix.height})")
    doc.close()
    return pages


def prep_image(path: str, target_w: int = TARGET_W) -> bytes:
    """缩到 <= target_w 宽,转 JPEG bytes。"""
    im = Image.open(path)
    if im.mode != "RGB":
        im = im.convert("RGB")
    if im.width > target_w:
        h = int(im.height * target_w / im.width)
        im = im.resize((target_w, h), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()


def call_vlm(image_bytes: bytes, model: str = MODEL) -> str:
    b64 = base64.b64encode(image_bytes).decode()
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                ],
            }
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.1,
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + api_key(),
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    content = raw["choices"][0]["message"].get("content") or ""
    if not content.strip():
        raise RuntimeError("empty content from VLM")
    return content.strip()


def ocr_page(path: str, model: str = MODEL) -> str:
    last = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            return call_vlm(prep_image(path), model)
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"    [retry {attempt}/{MAX_RETRY}] {type(e).__name__}: {e}")
            if attempt == MAX_RETRY:
                break
            time.sleep(2 * attempt)
            if model == MODEL:
                model = FALLBACK_MODEL
    raise RuntimeError(f"OCR failed after {MAX_RETRY} tries: {last}")


def clean(md: str) -> str:
    """去掉常见的 OCR 噪声:外层代码块、页眉页脚残留、<think> 思考块。"""
    md = md.strip()

    # ⚠️ reasoning 模型会吐 <think>...</think> —— 那是模型的内心戏,不是正文。
    #    必须剥掉,否则会污染语料(而且这段话会进 D1 被检索到)。
    md = re.sub(r"<think>.*?</think>", "", md, flags=re.S)
    # 未闭合的 <think>(模型被 max_tokens 截断)—— 从 <think> 之后全丢
    if "<think>" in md:
        md = md[: md.index("<think>")].strip()
    # 少数情况下模型会把思考写在 </think> 之后
    md = re.sub(r"^</?think>", "", md, flags=re.M).strip()

    if md.startswith("```markdown"):
        md = md[len("```markdown"):]
    elif md.startswith("```"):
        md = md[3:]
    if md.endswith("```"):
        md = md[:-3]
    md = md.strip()
    # 页脚 "GB 10648—2013" 单独一行 -> 删
    lines = [ln for ln in md.splitlines()]
    keep = []
    for ln in lines:
        s = ln.strip()
        if s in ("GB 10648—2013", "GB 10648-2013", "GB 10648—2013 饲料标签"):
            continue
        if s.startswith("ICS ") and len(s) < 30:
            continue
        keep.append(ln)
    return "\n".join(keep).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--work-dir", default=None, help="渲染图临时目录(默认 out-dir/_pdf_pages)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--start", type=int, default=1, help="起始页(1-based)")
    ap.add_argument("--end", type=int, default=0, help="结束页(0=到底)")
    args = ap.parse_args()

    pdf = os.path.abspath(args.pdf)
    if not os.path.isfile(pdf):
        print(f"[ERROR] PDF not found: {pdf}", file=sys.stderr)
        return 1

    out_dir = os.path.abspath(args.out_dir)
    work_dir = os.path.abspath(args.work_dir or os.path.join(out_dir, "_pdf_pages"))

    print(f"[PDF] {os.path.basename(pdf)}")
    print(f"[OUT] {out_dir}")

    if args.dry_run:
        doc = pymupdf.open(pdf)
        print(f"  pages={doc.page_count}")
        for i in range(doc.page_count):
            t = doc[i].get_text()
            print(f"  p{i+1}: text_layer_chars={len(t)}")
        doc.close()
        return 0

    pages = render_pdf(pdf, work_dir, dpi=args.dpi)
    end = args.end or len(pages)

    # ⚠️ 逐页落盘 —— 不攒到最后再写。
    #    一次 OCR 10 页要好几分钟,超时会丢全部结果;每页写一次可断点续跑。
    cache_dir = os.path.join(work_dir, "_ocr_cache")
    os.makedirs(cache_dir, exist_ok=True)
    out_md = os.path.join(out_dir, "GB10648-2013_饲料标签.md")

    for idx in range(args.start - 1, min(end, len(pages))):
        pno = idx + 1
        cached = os.path.join(cache_dir, f"p{pno:03d}.md")
        if os.path.isfile(cached) and os.path.getsize(cached) > 0:
            print(f"[OCR] page {pno}/{len(pages)} -- cached, skip")
            continue

        print(f"[OCR] page {pno}/{len(pages)} ...", flush=True)
        md = clean(ocr_page(pages[idx]))
        with open(cached, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"   -> {len(md)} chars (cached)", flush=True)

    # ⚠️ 缓存里的旧文件可能是用旧版 clean() 写的(带 <think> 泄漏),
    #    这里统一重洗一遍,不重新调 API。
    for i in range(1, len(pages) + 1):
        cached = os.path.join(cache_dir, f"p{i:03d}.md")
        if not os.path.isfile(cached):
            continue
        with open(cached, encoding="utf-8") as f:
            raw = f.read()
        fixed = clean(raw)
        if fixed != raw:
            with open(cached, "w", encoding="utf-8") as f:
                f.write(fixed)
            print(f"[CLEAN] p{i:03d} 清洗 {len(raw)} -> {len(fixed)} chars")

    # 合并缓存成一份 md(按页分隔)
    parts = []
    for i in range(1, len(pages) + 1):
        cached = os.path.join(cache_dir, f"p{i:03d}.md")
        if os.path.isfile(cached):
            with open(cached, encoding="utf-8") as f:
                parts.append(f"\n<!-- page {i} -->\n\n{f.read().strip()}")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(parts).strip() + "\n")
    print(f"[OK] -> {out_md} ({os.path.getsize(out_md)} bytes, {len(parts)} pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
