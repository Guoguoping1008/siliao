import sys, numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

p = sys.argv[1]
im = Image.open(p).convert("RGB")
W, H = im.size
engine = RapidOCR()

def run(img, tag):
    nw, nh = int(img.width*0.55), int(img.height*0.55)
    res, _ = engine(np.array(img.resize((nw, nh), Image.LANCZOS)))
    items = []
    for box, txt, score in (res or []):
        xs=[c[0] for c in box]; ys=[c[1] for c in box]
        items.append({"x0":min(xs),"x1":max(xs),"y0":min(ys),"t":txt.strip(),"s":score})
    L=[i for i in items if i["x1"]<nw*0.5]
    R=[i for i in items if i["x0"]>nw*0.5]
    print(f"{tag}: left={len(L)} right={len(R)}  avg_score L={np.mean([i['s'] for i in L]):.3f} R={np.mean([i['s'] for i in R]):.3f}")
    return L,R

# 原图
run(im, "full-res 1.0x")

# 增强对比度 + 提亮
from PIL import ImageEnhance, ImageOps
g = im.convert("L")
g = ImageOps.autocontrast(g, cutoff=1)
enh = Image.merge("RGB",(g,g,g))
run(enh, "gray-autocontrast")

# 提亮阴影区
from PIL import ImageEnhance as IE
b = IE.Brightness(im).enhance(1.35)
b = IE.Contrast(b).enhance(1.3)
run(b, "brighten1.35+contrast1.3")

# 左半页单独跑
half = im.crop((0,0,int(W*0.5),H))
run(half, "left-half-only")
print("  left-half width", half.size)