"""Scan all book-spread photos, OCR them with RapidOCR, and record
per-page raw text + a heuristic table flag for later md generation."""
import json
import os
import re
import sys
import time
from pathlib import Path

from rapidocr_onnxruntime import RapidOCR

IMG_ROOT = Path("E:/workspace/siliao/Images")
CACHE = Path("E:/workspace/siliao/work/ocr_raw.json")

# Header noise: running head + page number + <<< / >>> markers + bleed-through.
HEADER_NOISE = re.compile(r"^[\s<>()（）]*$")


def load_cache():
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    return {}


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    ocr = RapidOCR()
    cache = load_cache()

    files = sorted(IMG_ROOT.rglob("*.jpg"))
    if limit:
        files = files[:limit]

    print(f"total files: {len(files)}, already cached: {len(cache)}", flush=True)

    t0 = time.time()
    for i, f in enumerate(files, 1):
        key = f.relative_to(IMG_ROOT).as_posix()
        if key in cache:
            continue
        try:
            res, _ = ocr(str(f))
        except Exception as e:  # keep going; a bad page must not kill the run
            cache[key] = {"error": str(e), "lines": []}
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            print(f"[{i}/{len(files)}] ERR {key}: {e}", flush=True)
            continue

        lines = []
        for box, text, score in (res or []):
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            lines.append({
                "text": text,
                "score": round(float(score), 3),
                "x": round(sum(xs) / len(xs), 1),
                "y": round(sum(ys) / len(ys), 1),
                "x0": round(min(xs), 1),
                "x1": round(max(xs), 1),
                "y0": round(min(ys), 1),
                "y1": round(max(ys), 1),
            })
        cache[key] = {"lines": lines}

        if i % 10 == 0:
            CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            rate = (time.time() - t0) / max(i - 1, 1)
            print(f"[{i}/{len(files)}] {rate:.2f}s/page eta={(len(files)-i)*rate/60:.0f}min", flush=True)

    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    print("DONE", len(cache), flush=True)


if __name__ == "__main__":
    main()