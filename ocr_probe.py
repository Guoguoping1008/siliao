import sys, numpy as np
from rapidocr_onnxruntime import RapidOCR
from PIL import Image

p = sys.argv[1]
frac = float(sys.argv[2]) if len(sys.argv) > 2 else 0.13
im = Image.open(p).convert("RGB")
W, H = im.size
crop_h = int(H * frac)
im2 = im.crop((0, crop_h, W, H)).resize((int(W*0.55), int((H-crop_h)*0.55)), Image.LANCZOS)
engine = RapidOCR()
res, _ = engine(np.array(im2))
rows = []
for box, txt, score in (res or []):
    xs = [c[0] for c in box]; ys = [c[1] for c in box]
    rows.append((min(ys), min(xs), max(ys), txt, score))
rows.sort(key=lambda r: (round(r[0]/30), r[1]))
for y0, x0, y1, t, s in rows[:15]:
    print(f"y={y0:7.1f} x={x0:7.1f} | {t}")