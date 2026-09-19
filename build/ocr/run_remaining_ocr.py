"""
补跑剩余 186 张单页 OCR。

策略:
- 输入:  data/markdown/feed-law-collection-2023-full/single_pages/*.jpg
- 跳过:  raw_ocr/ 里已有对应 __L.json / __R.json 的
- 输出:  raw_ocr/<原stem>.json (与上次格式一致: list[{bbox,text,score}])
- 进程:  2 worker 并行, paddleocr CPU 占用 ~200% 已经够, 不贪多
- 进度:  每 10 张打一次日志, 同时把心跳写到 progress.json (供监控)
- 模型:  每 worker 各持一个 PaddleOCR 实例 (PaddleOCR 内部线程不安全)

为什么不用 pic2md.py:
- pic2md 是一次性串到底, 跑到一半崩了得从头来
- 这里只补 raw_ocr 层, 与上次保持格式一致, 后续直接接原 pipeline
"""

from __future__ import annotations
import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path("E:/workspace/siliao")
SINGLE = ROOT / "data/markdown/feed-law-collection-2023-full/single_pages"
OCR = ROOT / "data/markdown/feed-law-collection-2023-full/raw_ocr"


def init_ocr():
    """每个 worker 进程内独立 init, 避开 paddleocr 的全局状态"""
    from paddleocr import PaddleOCR
    return PaddleOCR(use_angle_cls=True, lang="ch", use_gpu=False, show_log=False)


def ocr_one(args):
    """worker 函数: (img_path_str) -> dict 写到磁盘 + 返回摘要"""
    img_path = Path(args)
    out_path = OCR / (img_path.stem + ".json")
    if out_path.exists():
        return {"img": img_path.name, "skip": True, "n_lines": 0, "elapsed": 0.0}

    t0 = time.time()
    # lazy import 在 worker 里做, 避免 fork 后 paddleocr 双初始化
    ocr = init_ocr()
    raw = ocr.ocr(str(img_path), cls=True)
    lines = []
    if raw and raw[0]:
        for box, (text, score) in raw[0]:
            lines.append({
                "bbox": [[float(x), float(y)] for x, y in box],
                "text": text,
                "score": float(score),
            })
        lines.sort(key=lambda ln: (min(p[1] for p in ln["bbox"]), min(p[0] for p in ln["bbox"])))
    elapsed = time.time() - t0

    out_path.write_text(json.dumps(lines, ensure_ascii=False), encoding="utf-8")
    return {"img": img_path.name, "skip": False, "n_lines": len(lines), "elapsed": elapsed}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 张 (调试用)")
    args = parser.parse_args()

    OCR.mkdir(parents=True, exist_ok=True)
    all_imgs = sorted(SINGLE.glob("*.jpg"))
    todo = [p for p in all_imgs if not (OCR / (p.stem + ".json")).exists()]
    if args.limit:
        todo = todo[: args.limit]
    print(f"[plan] single_pages={len(all_imgs)}  raw_ocr_done={len(all_imgs) - len(todo)}  to_run={len(todo)}  workers={args.workers}")

    if not todo:
        print("[done] nothing to do")
        return 0

    t0 = time.time()
    done = 0
    fail = 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(ocr_one, str(p)): p for p in todo}
        for fut in as_completed(futures):
            try:
                r = fut.result()
                if not r.get("skip"):
                    done += 1
            except Exception as e:
                fail += 1
                print(f"[fail] {futures[fut].name}: {e}", file=sys.stderr)
            total_done = done + fail
            if total_done % 10 == 0 or total_done == len(todo):
                el = time.time() - t0
                eta = el / max(total_done, 1) * (len(todo) - total_done)
                print(f"[prog] {total_done}/{len(todo)}  done={done} fail={fail}  elapsed={el:.0f}s  eta={eta:.0f}s")

    print(f"[final] done={done} fail={fail} total_elapsed={time.time()-t0:.0f}s")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
