"""Qwen2-VL table transcription for book-photo pages.

Qwen2-VL uses dynamic resolution: a 4500x3400 page expands to thousands of
vision tokens and OOMs an 8GB card. Cap the long edge before inference.

Writes one *_tbl_<n>.md per image, holding the page's tables as md pipe
tables. Text outside the tables is handled by the line-OCR pipeline.
"""
import argparse
import json
import re
import time
from pathlib import Path

import torch
from PIL import Image

MODEL_DIR = "E:/workspace/qwen2vl/models/Qwen2-VL-7B-AWQ"

PROMPT = """这是一页中文书籍照片。请只做一件事：把页面里的表格原样转成 Markdown 表格。

严格要求：
1. 只输出表格，用标准 Markdown 管道表（用 | 分隔列，用 |---|--- 分隔表头与内容行）。
2. 一个表输出一个 Markdown 表格；页面有多个表就依次输出多个。
3. 单元格文字照抄，不要改写、不要补字、不要总结。
4. 竖排（文字旋转90度）的表格也按正常列顺序输出。
5. 表格之外的正文、页眉、页码、注释一律不要输出。
6. 跨页表格只输出本页能看到的部分，不要猜测下一页的内容。
7. 如果本页没有表格，只输出一行：NO_TABLE"""


def load(max_side=1280):
    """Reuse the project's AWQ loader, but cap vision tokens.

    Qwen2-VL dynamic resolution makes a full-resolution book photo explode to
    ~16GB of activations and OOM an 8GB card, so the processor must be built
    with a pixel budget. The loader returns the model only; the processor is
    constructed here with min/max pixels.
    """
    import sys
    sys.path.insert(0, "E:/workspace/qwen2vl")
    from awq_loader import load_awq_model
    from transformers import AutoProcessor

    # load_awq_model returns (processor, model) and already calls .eval().
    _, model = load_awq_model(MODEL_DIR, device="cuda")

    # Rebuild the processor with a pixel budget: the loader's default has none,
    # so a full-resolution page expands to ~16GB and OOMs an 8GB card.
    proc = AutoProcessor.from_pretrained(
        MODEL_DIR,
        min_pixels=256 * 28 * 28,
        max_pixels=max_side * max_side,
    )
    return proc, model


def fit(img: Image.Image, max_side=1280) -> Image.Image:
    w, h = img.size
    if max(w, h) > max_side:
        s = max_side / max(w, h)
        img = img.resize((int(w * s), int(h * s)), Image.LANCZOS)
    return img.convert("RGB")


def extract_tables(proc, model, img_path, max_side=1280, max_new_tokens=1400):
    img = fit(Image.open(img_path), max_side)
    msgs = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": PROMPT}]}]
    text = proc.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    inputs = proc(text=[text], images=[img], return_tensors="pt").to(model.device)
    with torch.inference_mode():
        out = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
    gen = out[0][inputs["input_ids"].shape[-1]:]
    return proc.decode(gen, skip_special_tokens=True)


MD_ROW = re.compile(r"^\s*\|.*\|\s*$")
SEP_ROW = re.compile(r"^\s*\|[\s:|-]+\|\s*$")


def clean_tables(raw: str):
    """Keep only well-formed md table blocks from the model output."""
    blocks, cur = [], []
    for line in raw.splitlines():
        if MD_ROW.match(line):
            cur.append(line.rstrip())
        else:
            if len(cur) >= 2 and any(SEP_ROW.match(x) for x in cur):
                blocks.append(cur)
            cur = []
    if len(cur) >= 2 and any(SEP_ROW.match(x) for x in cur):
        blocks.append(cur)
    return ["\n".join(b) for b in blocks]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", required=True, help="json list of relative image paths")
    ap.add_argument("--out", required=True, help="output dir")
    ap.add_argument("--max-side", type=int, default=1280)
    ap.add_argument("--max-new-tokens", type=int, default=1400)
    ap.add_argument("--done", help="json file of already-finished images")
    args = ap.parse_args()

    keys = json.loads(Path(args.images).read_text(encoding="utf-8"))
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    donefile = Path(args.done) if args.done else outdir / "_done.json"
    done = json.loads(donefile.read_text(encoding="utf-8")) if donefile.exists() else {}

    proc, model = load(args.max_side)
    print("model loaded", flush=True)

    for i, key in enumerate(keys, 1):
        if key in done:
            continue
        try:
            raw = extract_tables(proc, model, Path("E:/workspace/siliao/Images") / key,
                                 args.max_side, args.max_new_tokens)
        except Exception as e:
            print(f"[{i}/{len(keys)}] ERR {key}: {e}", flush=True)
            continue
        tables = clean_tables(raw)
        rel = Path(key)
        if tables:
            base = outdir / rel.parent.name / rel.stem
            (base.parent).mkdir(parents=True, exist_ok=True)
            for n, t in enumerate(tables, 1):
                (outdir / rel.parent.name / f"{rel.stem}_tbl_{n}.md").write_text(
                    f"<!-- source: {key} | table {n} -->\n\n{t}\n", encoding="utf-8")
        else:
            (outdir / rel.parent.name / "_none.txt")
        done[key] = {"tables": len(tables)}
        donefile.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")
        print(f"[{i}/{len(keys)}] {key} -> {len(tables)} tables", flush=True)

    print("DONE", len(done), flush=True)


if __name__ == "__main__":
    main()