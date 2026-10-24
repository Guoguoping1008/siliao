"""真值标定: 直接目视测量书脊位置, 得到 ground truth 列表。

做法: 对代表页, 以 0.01 为步长扫描 0.44~0.56, 逐个把中缝竖线画在图上,
拼成一张"多候选线"对照图, 人工/视觉判读哪条对齐折痕。
本文件只负责生成对照图; 判读结果写入 GROUND_TRUTH。
"""
import os, sys
from PIL import Image, ImageDraw

REPS = [
    "Images/02制度文件/0035.jpg",
    "Images/02制度文件/0423.jpg",
    "Images/02制度文件/0015.jpg",
    "Images/02制度文件/0551.jpg",
    "Images/02制度文件/0235.jpg",
    "Images/02制度文件/0339.jpg",
    "Images/03相关法规法律法规文件/0749.jpg",
    "Images/04标准及标准目录/0953.jpg",
]

CANDS = [0.44, 0.46, 0.47, 0.48, 0.49, 0.50, 0.51, 0.52, 0.54]
COLORS = [(255, 0, 0), (255, 140, 0), (255, 200, 0), (150, 200, 0),
          (0, 160, 0), (0, 200, 200), (0, 120, 255), (160, 0, 255), (255, 0, 160)]


def main(outdir=r"C:/Users/Administrator/AppData/Local/Temp/spinetruth"):
    os.makedirs(outdir, exist_ok=True)
    for p in REPS:
        im = Image.open(p).convert("RGB")
        W, H = im.size
        Wd = 1000
        im2 = im.resize((Wd, int(H * Wd / W)), Image.LANCZOS)
        d = ImageDraw.Draw(im2)
        for frac, c in zip(CANDS, COLORS):
            x = int(Wd * frac)
            d.line([(x, 0), (x, im2.height)], fill=c, width=1)
            d.text((x + 2, 4), "%.2f" % frac, fill=c)
        out = os.path.join(outdir, "T_" + os.path.basename(p))
        im2.save(out)
        print(out)


if __name__ == "__main__":
    main()