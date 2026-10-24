import sys, os, numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR
sys.path.insert(0, "E:/workspace/siliao")
import ocr_batch as ob

p = sys.argv[1]
im = Image.open(p).convert("RGB")
W, H = im.size
ch = int(H * ob.HEADER_CROP)
body = im.crop((0, ch, W, H))
nw, nh = int(W * ob.SCALE), int(body.height * ob.SCALE)
body = body.resize((nw, nh), Image.LANCZOS)
engine = RapidOCR()
res, _ = engine(np.array(body))
items = []
for box, txt, score in (res or []):
    if score < 0.5 or not txt.strip(): continue
    xs = [c[0] for c in box]; ys = [c[1] for c in box]
    items.append({"x0": min(xs), "x1": max(xs), "y0": min(ys), "y1": max(ys), "t": txt.strip()})
med_len = max(1.0, float(np.median([len(i["t"]) for i in items])))
font_w = max(6.0, float(np.median([i["x1"]-i["x0"] for i in items]))/med_len)
gx = ob.gutter_x(items, nw, nh)
print(f"nw={nw} gx={gx} font_w={font_w:.1f} band={font_w*2:.1f}")
band = font_w*2
right = [i for i in items if i["x0"] >= gx-band]
rid = {id(i) for i in right}
left = [i for i in items if i["x1"] <= gx+band and id(i) not in rid]
drop = [i for i in items if id(i) not in rid and i not in left]
print(f"left={len(left)} right={len(right)} unassigned={len(drop)}")
print("\n--- LEFT x0 range ---", int(min(i['x0'] for i in left)), int(max(i['x1'] for i in left)))
print("--- RIGHT x0 range ---", int(min(i['x0'] for i in right)), int(max(i['x1'] for i in right)))
print("\nLEFT rows (y-sorted):")
for row in ob.to_rows(left, nh):
    print(f"  y={row[0]['y0']:6.1f} x={row[0]['x0']:6.1f} | {''.join(i['t'] for i in row)[:60]}")
print("\nRIGHT rows (y-sorted):")
for row in ob.to_rows(right, nh):
    print(f"  y={row[0]['y0']:6.1f} x={row[0]['x0']:6.1f} | {''.join(i['t'] for i in row)[:60]}")
print("\nUNASSIGNED:")
for i in drop:
    print(f"  x0={i['x0']:.0f} x1={i['x1']:.0f} y={i['y0']:.0f} | {i['t'][:60]}")