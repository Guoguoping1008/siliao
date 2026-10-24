import time, sys
from rapidocr_onnxruntime import RapidOCR
from PIL import Image
import numpy as np

p = sys.argv[1] if len(sys.argv) > 1 else "E:/workspace/siliao/Images/03相关法规法律法规文件/0749.jpg"
im = Image.open(p).convert("RGB")
W, H = im.size
print("size", W, H)

# crop top 13% away (header band), then downscale for speed
crop_h = int(H * 0.13)
im2 = im.crop((0, crop_h, W, H))
im2 = im2.resize((int(im2.width * 0.55), int(im2.height * 0.55)), Image.LANCZOS)
print("ocr size", im2.size)

engine = RapidOCR()
t = time.time()
res, elapse = engine(np.array(im2))
print("time", round(time.time() - t, 2), "boxes", len(res or []))
for r in (res or [])[:25]:
    print(round(r[2], 2), r[1])