import sys, numpy as np
from PIL import Image, ImageOps
from rapidocr_onnxruntime import RapidOCR

p = sys.argv[1]
full = Image.open(p).convert("RGB")
W, H = full.size
eng = RapidOCR()

def count(img, tag, scale=1.0):
    nw, nh = int(img.width*scale), int(img.height*scale)
    a = np.array(img.resize((nw, nh), Image.LANCZOS)) if scale != 1.0 else np.array(img)
    res, _ = eng(a)
    n = sum(1 for b,t,s in (res or []) if s >= 0.5 and t.strip())
    print(f"  {tag:42s} size={nw}x{nh} boxes={n}")
    return res

left = full.crop((0,0,int(W*0.5),H))
print("LEFT HALF experiments:")
count(left, "raw 1.0x")
count(left, "raw 0.7x", 0.7)

# 灰度 + autocontrast (局部对比)
g = left.convert("L")
g = ImageOps.autocontrast(g, cutoff=0.5)
count(g.convert("RGB"), "gray+autocontrast 1.0x")
count(g.convert("RGB"), "gray+autocontrast 0.7x", 0.7)

# gamma 提亮暗部
g2 = ImageOps.autocontrast(left.convert("L"), cutoff=0.5).point(lambda v: 255*((v/255)**0.6))
count(g2.convert("RGB"), "autocontrast+gamma0.6 1.0x")

# CLAHE
try:
    from skimage import exposure
    cl = exposure.equalize_adapthist(g, kernel_size=(60, 200))
    count(cl.convert("RGB"), "CLAHE 1.0x")
except Exception as e:
    print("  CLAHE skipped:", e)