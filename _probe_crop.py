import sys, os, numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR
sys.path.insert(0, "E:/workspace/siliao")
import ocr_batch as ob

p = sys.argv[1]
im = Image.open(p).convert("RGB")
W, H = im.size
engine = RapidOCR()
for frac in [0.0, 0.06, 0.09, 0.13]:
    ch = int(H * frac)
    body = im.crop((0, ch, W, H))
    nw, nh = int(W*0.55), int(body.height*0.55)
    res, _ = engine(np.array(body.resize((nw, nh), Image.LANCZOS)))
    items = []
    for box, txt, score in (res or []):
        if score < 0.5 or not txt.strip(): continue
        xs = [c[0] for c in box]; ys = [c[1] for c in box]
        items.append({"x0":min(xs),"x1":max(xs),"y0":min(ys),"y1":max(ys),"t":txt.strip()})
    L = [i for i in items if i["x1"] < nw*0.5]
    R = [i for i in items if i["x0"] > nw*0.5]
    gx = ob.gutter_x(items, nw, nh)
    print(f"crop={frac:.2f} items={len(items):3d} left={len(L):3d} right={len(R):3d} gutter={gx}")
    # 左页最靠上的文字 y (换算回原图比例)
    if L:
        top = min(i["y0"] for i in L)/nh
        print(f"         left-page topmost text at {top*100:.1f}% of remaining -> orig {(ch/H + top*(1-ch/H))*100:.1f}%")