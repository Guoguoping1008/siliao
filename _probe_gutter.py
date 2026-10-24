import sys, numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR
sys.path.insert(0, "E:/workspace/siliao")
from ocr_batch import gutter_x, HEADER_CROP, SCALE

p = sys.argv[1]
im = Image.open(p).convert("RGB")
W, H = im.size
ch = int(H * HEADER_CROP)
body = im.crop((0, ch, W, H))
nw, nh = int(W * SCALE), int(body.height * SCALE)
body = body.resize((nw, nh), Image.LANCZOS)
engine = RapidOCR()
res, _ = engine(np.array(body))
items = []
for box, txt, score in (res or []):
    xs = [c[0] for c in box]; ys = [c[1] for c in box]
    items.append({"x0": min(xs), "x1": max(xs), "y0": min(ys), "y1": max(ys), "t": txt.strip()})
print("nw,nh =", nw, nh, "items =", len(items))

gx = gutter_x(items, nw, nh)
print("gutter =", gx, "=> frac", (gx / nw) if gx else None)

occ = np.zeros(nw, dtype=np.int32)
for it in items:
    occ[int(max(0, it["x0"])):int(min(nw, it["x1"]))] += 1
k = max(3, nw // 200)
sm = np.convolve(occ, np.ones(k)/k, mode="same")
print("profile near center (x, occ):")
for x in range(int(nw*0.40), int(nw*0.60), max(1, nw//120)):
    bar = "#" * int(sm[x])
    print(f"  {x:5d} {sm[x]:6.2f} {bar}")