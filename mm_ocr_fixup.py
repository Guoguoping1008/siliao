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


def reprocess(rel, workers_lock=None):
    """重跑单页(强制覆盖)。"""
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
    raw, err = mm_ocr.ocr_with_retry(src)
    if raw is None:
        return ("ERR", rel, err or "")
    if mm_ocr.is_toc_page(rel):
        entries = mm_ocr.split_toc_entries(raw.replace("\n", " "))
        md = "\n".join(x for x in (mm_ocr.toc_entry_to_md(e) for e in entries) if x)
        md = re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"
    else:
        md = mm_ocr.to_markdown(raw)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(md)
    return ("OK", rel, "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--errors", action="store_true")
    ap.add_argument("--toc", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    todo = []
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
