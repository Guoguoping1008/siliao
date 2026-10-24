"""检测每页"页眉带"的实际 y 位置, 用于评估固定 13% 裁剪的覆盖率。"""
import os, sys, json, argparse
import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ocr_batch as ob

# 页眉特征词: 章节名 + 年份 + >>> / <<< / 页码
HDR_WORDS = ("饲料法规文件", "相关法律法规文件", "制度文件", "标准及标准目录", "目 录", "目录")


def probe(engine, path):
    im = Image.open(path).convert("RGB")
    W, H = im.size
    body = im.resize((int(W*0.55), int(H*0.55)), Image.LANCZOS)
    res, _ = engine(np.array(body))
    nh = body.height
    out = []
    for b, t, s in (res or []):
        t = t.strip()
        ys = [c[1] for c in b]
        y0 = min(ys)/nh
        if any(w in t for w in HDR_WORDS) or ">>>" in t or "<<<" in t \
           or (t.isdigit() and 1 <= len(t) <= 4 and y0 < 0.30):
            out.append((y0, t))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", default="E:/workspace/siliao/Images")
    ap.add_argument("--out", default="E:/workspace/siliao/_hdr_probe.json")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    imgs = []
    for dp, _, fs in os.walk(args.images):
        for fn in sorted(fs):
            if fn.lower().endswith(".jpg"):
                imgs.append(os.path.join(dp, fn))
    imgs.sort()
    if args.limit:
        imgs = imgs[:args.limit]
    eng = RapidOCR()
    rows = []
    for i, p in enumerate(imgs, 1):
        hits = probe(eng, p)
        rows.append({"src": os.path.relpath(p, args.images), "hits": hits})
        if i % 20 == 0:
            print(f"  {i}/{len(imgs)}", flush=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    # 统计: 页眉最大 y 超过 13% 的页数
    over = [r for r in rows if r["hits"] and max(h[0] for h in r["hits"]) > 0.13]
    print(f"\ntotal={len(rows)}  页眉延伸到 13% 以下的页数 = {len(over)}")
    for r in over[:20]:
        print(f"  {r['src']}  maxY={max(h[0] for h in r['hits'])*100:.1f}%")


if __name__ == "__main__":
    main()