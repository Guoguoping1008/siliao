import sys, numpy as np
from PIL import Image

p = sys.argv[1]
im = Image.open(p).convert("L")
W, H = im.size
nw, nh = int(W*0.55), int(H*0.55)
g = np.array(im.resize((nw, nh), Image.LANCZOS))
# 只看左页文本区
x0, x1 = int(nw*0.10), int(nw*0.46)
strip = g[:, x0:x1]
prof = (strip < 160).sum(axis=1).astype(np.float32)
thr = max(1.0, prof.max()*0.15)
runs, start = [], None
# 低于峰值 8% 即视为行间空白, 以便在极密排版下仍能切出行
thr = max(1.0, prof.max() * 0.08)
for y in range(len(prof)):
    if prof[y] > thr:
        if start is None: start = y
    else:
        if start is not None: runs.append((start,y)); start=None
if start is not None: runs.append((start,len(prof)))
runs=[(a,b) for a,b in runs if b-a>=4]
print(f"ink runs on left page: {len(runs)}")
for i,(a,b) in enumerate(runs):
    print(f"  {i:2d} y={a:6d}-{b:6d} h={b-a:4d}")
hs=[b-a for a,b in runs]
if hs: print("median run height =", float(np.median(hs)))
tops=[a for a,b in runs]
if len(tops)>1:
    d=[tops[i+1]-tops[i] for i in range(len(tops)-1)]
    print("top gaps:", [int(x) for x in d])