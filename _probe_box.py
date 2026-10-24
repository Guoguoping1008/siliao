import sys, numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

p = sys.argv[1]
im = Image.open(p).convert("RGB")
W, H = im.size
engine = RapidOCR()
nw, nh = int(W*0.55), int(H*0.55)
res, _ = engine(np.array(im.resize((nw, nh), Image.LANCZOS)))
items=[]
for box, txt, score in (res or []):
    xs=[c[0] for c in box]; ys=[c[1] for c in box]
    items.append({"x0":min(xs),"x1":max(xs),"y0":min(ys),"y1":max(ys),"t":txt.strip(),"s":score})
L=[i for i in items if i["x1"]<nw*0.5]
L.sort(key=lambda i:i["y0"])
print(f"{'y0':>7} {'y1':>7} {'height':>7} {'len':>4}  text")
for i in L:
    print(f"{i['y0']:7.1f} {i['y1']:7.1f} {i['y1']-i['y0']:7.1f} {len(i['t']):4d}  {i['t'][:50]}")
hs=[i['y1']-i['y0'] for i in L]
print(f"\nmedian box height = {np.median(hs):.1f}  -> 单行字高约 {np.median(hs)/2.5:.1f}?")
# 估计行距: 用 box 中心差
cs=sorted((i['y0']+i['y1'])/2 for i in L)
d=[cs[i+1]-cs[i] for i in range(len(cs)-1)]
print("center gaps:", [round(x,1) for x in d])