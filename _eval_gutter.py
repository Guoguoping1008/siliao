"""在多张样本页上评估 gutter_x 的两栏判定准确率与耗时。"""
import sys, os, time, numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR
sys.path.insert(0, "E:/workspace/siliao")
from ocr_batch import gutter_x, HEADER_CROP, SCALE

engine = RapidOCR()
root = r"E:/workspace/siliao/Images"
imgs = []
for dp, _, fs in os.walk(root):
    for fn in sorted(fs):
        if fn.lower().endswith(".jpg"):
            imgs.append(os.path.join(dp, fn))
imgs.sort()
# 每层均匀抽样
by_dir = {}
for p in imgs:
    by_dir.setdefault(os.path.dirname(p), []).append(p)
sample = []
for d, lst in by_dir.items():
    step = max(1, len(lst) // 4)
    sample += lst[::step][:4]
print(f"sample {len(sample)} pages\n")

t0 = time.time()
for p in sample:
    im = Image.open(p).convert("RGB")
    W, H = im.size
    ch = int(H * HEADER_CROP)
    body = im.crop((0, ch, W, H))
    nw, nh = int(W * SCALE), int(body.height * SCALE)
    body = body.resize((nw, nh), Image.LANCZOS)
    res, _ = engine(np.array(body))
    items = []
    for box, txt, score in (res or []):
        if score < 0.5 or not txt.strip():
            continue
        xs = [c[0] for c in box]; ys = [c[1] for c in box]
        items.append({"x0": min(xs), "x1": max(xs), "y0": min(ys), "y1": max(ys), "t": txt.strip()})
    gx = gutter_x(items, nw, nh)
    tag = "2col" if gx else "1col"
    frac = f"{gx/nw:.3f}" if gx else "-"
    rel = os.path.relpath(p, root)
    print(f"{tag}  frac={frac:6s} items={len(items):3d}  {rel}")
print(f"\nelapsed {time.time()-t0:.0f}s for {len(sample)}")