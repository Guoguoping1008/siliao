import sys, numpy as np, time
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

p = sys.argv[1]
full = Image.open(p).convert("RGB")
W, H = full.size
left = full.crop((0, 0, int(W*0.5), H))
eng = RapidOCR()

# 策略: 把左页切成若干横条, 每条高度 < 单行行距, 逐条 OCR
STRIP = 130  # 原图像素
scale = 0.8
t0 = time.time()
alltxt = []
y = 0
while y < left.height:
    strip = left.crop((0, y, left.width, min(y+STRIP, left.height)))
    a = np.array(strip.resize((int(strip.width*scale), int(strip.height*scale)), Image.LANCZOS))
    res, _ = eng(a)
    for b, t, s in (res or []):
        if s >= 0.4 and t.strip():
            alltxt.append((y, t))
    y += STRIP
print(f"STRIP={STRIP} -> {len(alltxt)} lines, {time.time()-t0:.1f}s\n")
for y, t in alltxt:
    print(f"  y={y:5d} | {t[:55]}")