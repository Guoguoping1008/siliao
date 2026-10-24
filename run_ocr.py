#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Batch OCR all images under Images/ -> one .md per image under output/."""
import os, re, sys, json, time, traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "Images")
OUT = os.path.join(ROOT, "output")
PROGRESS = os.path.join(ROOT, ".ocr_progress.json")
EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff", ".gif"}

from rapidocr_onnxruntime import RapidOCR


def collect():
    items = []
    for dirpath, _dirs, files in os.walk(SRC):
        for f in sorted(files):
            if os.path.splitext(f)[1].lower() in EXTS:
                full = os.path.join(dirpath, f)
                rel = os.path.relpath(full, SRC).replace("\\", "/")
                items.append((full, rel))
    items.sort(key=lambda x: x[1])
    return items


def load_progress():
    if os.path.exists(PROGRESS):
        try:
            with open(PROGRESS, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}
    return {}


def save_progress(p):
    with open(PROGRESS, "w", encoding="utf-8") as fh:
        json.dump(p, fh, ensure_ascii=False, indent=1)


def md_path_for(rel):
    # output/000封面/封面00.md  (mirror source tree)
    stem = os.path.splitext(rel)[0]
    return os.path.join(OUT, stem + ".md")


def write_md(rel, full, lines, avg_conf, duration):
    mp = md_path_for(rel)
    os.makedirs(os.path.dirname(mp), exist_ok=True)
    title = os.path.splitext(os.path.basename(rel))[0]
    parts = [
        "# %s\n" % title,
        "> 源文件: `Images/%s`\n" % rel,
        "> OCR: rapidocr-onnxruntime | 平均置信度: %.3f | 耗时: %.2fs\n"
        % (avg_conf, duration),
        "\n## 识别文本\n",
    ]
    if lines:
        parts.append("\n".join(lines))
    else:
        parts.append("_(未识别到文本)_")
    parts.append("")
    with open(mp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(parts))
    return mp


def main():
    items = collect()
    total = len(items)
    done = load_progress()
    ocr = RapidOCR()
    print("TOTAL=%d  RESUME_DONE=%d" % (total, len(done)), flush=True)

    ok = fail = 0
    for i, (full, rel) in enumerate(items, 1):
        mp = md_path_for(rel)
        if rel in done and os.path.exists(mp):
            continue
        t0 = time.time()
        try:
            result, _ = ocr(full)
            lines, confs = [], []
            if result:
                result = sorted(result, key=lambda x: (x[0][0][1], x[0][0][0]))
                for box, txt, conf in result:
                    lines.append(str(txt).strip())
                    try:
                        confs.append(float(conf))
                    except Exception:
                        pass
            avg = sum(confs) / len(confs) if confs else 0.0
            dur = time.time() - t0
            write_md(rel, full, lines, avg, dur)
            done[rel] = {"lines": len(lines), "conf": round(avg, 3)}
            ok += 1
            print("[%d/%d] %s  lines=%d conf=%.3f %.1fs"
                  % (i, total, rel, len(lines), avg, dur), flush=True)
        except Exception as e:
            fail += 1
            dur = time.time() - t0
            write_md(rel, full, ["_OCR 失败: %s_" % e], 0.0, dur)
            done[rel] = {"lines": 0, "conf": 0.0, "error": str(e)}
            print("[%d/%d] %s  ERROR %s" % (i, total, rel, e), flush=True)
            traceback.print_exc()
        if i % 10 == 0:
            save_progress(done)

    save_progress(done)
    print("DONE ok=%d fail=%d" % (ok, fail), flush=True)


if __name__ == "__main__":
    main()