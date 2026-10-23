"""收尾脚本: 修跑完之后处理两类遗留问题。

1. 失败页重跑 —— 用修好的 meta 判定逻辑重试(旧逻辑把 M3 的有效正文误判成拒识)。
2. 目录页重跑 —— 用新的目录专用解析(切目录项 + 拆文号)。

用法:
  python mm_ocr_fixup.py --errors     # 只重跑失败页
  python mm_ocr_fixup.py --toc        # 只重跑 001目录
  python mm_ocr_fixup.py --all        # 都跑
"""
import os
import re
import sys
import json
import time
import argparse
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mm_ocr


def load_errors():
    """从进度文件里挑出 ERR 的页。"""
    p = mm_ocr.PROGRESS
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        prog = json.load(f)
    return [rel for rel, v in prog.items() if v.get("status") == "ERR"]


RAW_CACHE = r"E:/workspace/siliao/.mm_raw_cache"


def cache_path(rel):
    """原始 OCR 文本的本地缓存(按相对路径)。改格式时不用重烧 API。"""
    return os.path.join(RAW_CACHE, os.path.splitext(rel.replace("/", os.sep))[0] + ".txt")


def reprocess(rel, workers_lock=None, use_cache=True):
    """重跑单页(强制覆盖)。use_cache=True 时优先用本地缓存的原始 OCR。"""
    src = os.path.join(mm_ocr.SRC_ROOT, rel.replace("/", os.sep))
    if not os.path.exists(src):
        return ("ERR", rel, "src_missing")
    dst_dir = os.path.join(mm_ocr.DST_ROOT, os.path.dirname(rel.replace("/", os.sep)))
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, os.path.splitext(os.path.basename(src))[0] + ".md")
    t0 = time.time()
    if mm_ocr.is_blank_page(src):
        open(dst, "w", encoding="utf-8").write("")
        return ("BLANK", rel, "")
    raw = None
    xflag = None
    cp = cache_path(rel)
    if use_cache and os.path.exists(cp):
        raw = open(cp, encoding="utf-8").read()
    if raw is None:
        raw, err = mm_ocr.ocr_with_retry(src)
        if raw is None:
            return ("ERR", rel, err or "")
        raw, xflag = mm_ocr.cross_check_low_contrast(src, raw)
        os.makedirs(os.path.dirname(cp), exist_ok=True)
        with open(cp, "w", encoding="utf-8") as f:
            f.write(raw)
    if mm_ocr.is_toc_page(rel):
        entries = mm_ocr.split_toc_entries(raw.replace("\n", " "))
        md = mm_ocr.toc_entries_to_md(entries)
        md = re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"
        if not md.strip():
            md = mm_ocr.to_markdown(raw)
    else:
        md = mm_ocr.to_markdown(raw)
    md = md.replace("```", "")
    md = re.sub(r"[ \t]+$", "", md, flags=re.M)
    if xflag and "hallucination" in xflag:
        md = (f"<!-- OCR 低置信: {xflag} -->\n"
              f"<!-- 原始图: {rel.replace('/', ' / ')} -->\n"
              f"<!-- 扫描对比度过低({mm_ocr.local_contrast(src):.2f} < {mm_ocr.LOW_CONTRAST}), "
              f"模型输出被判定为幻觉, 已丢弃, 需人工复核或重新扫描 -->\n")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(md)
    return ("OK", rel, xflag or "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--errors", action="store_true")
    ap.add_argument("--toc", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", default="", help="指定要重跑的相对路径列表(json 文件)")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    todo = []
    if args.list:
        with open(args.list, encoding="utf-8") as f:
            todo = json.load(f)
        todo = [t.replace(".md", ".jpg") for t in todo]
        print(f"[fixup] 指定列表 {len(todo)} 张")
    if args.errors or args.all:
        errs = load_errors()
        todo += [e for e in errs if not mm_ocr.is_toc_page(e)]
        print(f"[fixup] 失败页 {len(todo)} 张")
    if args.toc or args.all:
        tocp = os.path.join(mm_ocr.SRC_ROOT, "001目录")
        for dp, _, fs in os.walk(tocp):
            for f in sorted(fs):
                if f.lower().endswith((".jpg", ".jpeg", ".png")):
                    rel = os.path.relpath(os.path.join(dp, f), mm_ocr.SRC_ROOT).replace("\\", "/")
                    todo.append(rel)
        print(f"[fixup] 目录页 -> 累计 {len(todo)} 张")

    if not todo:
        print("[fixup] 无事可做")
        return

    ok = err = blank = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(reprocess, rel) for rel in todo]
        for i, fu in enumerate(futs, 1):
            st, rel, e = fu.result()
            if st == "OK":
                ok += 1
            elif st == "BLANK":
                blank += 1
            else:
                err += 1
                print(f"  ERR {rel}: {e}", flush=True)
            if i % 10 == 0 or i == len(futs):
                el = time.time() - t0
                print(f"  {i}/{len(futs)} ok={ok} blank={blank} err={err} "
                      f"{el/60:.1f}min", flush=True)
    print(f"[fixup done] ok={ok} blank={blank} err={err}")


if __name__ == "__main__":
    main()
