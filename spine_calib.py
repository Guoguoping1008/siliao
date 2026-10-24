"""求书脊真值: 把一张跨页图按多种比例切, 拼成对比图, 人工目视校准。

用途: 检测算法的"标准答案"。只对少量代表页做, 校准后再全量跑。
"""
import os, sys, argparse
from PIL import Image, ImageDraw

REPS = [
    "Images/02制度文件/0235.jpg",
    "Images/02制度文件/0015.jpg",
    "Images/02制度文件/0031.jpg",
    "Images/03相关法规法律法规文件/0749.jpg",
    "Images/04标准及标准目录/0953.jpg",
    "Images/02制度文件/0035.jpg",
    "Images/02制度文件/0423.jpg",
    "Images/02制度文件/0551.jpg",
]


def make_strip(path, out, width=1400):
    """把原图缩到固定宽, 上面画多条候选竖线, 便于目视比较。"""
    im = Image.open(path).convert("RGB")
    W, H = im.size
    sc = width / W
    im2 = im.resize((width, int(H * sc)), Image.LANCZOS)
    d = ImageDraw.Draw(im2)
    marks = [(0.5, (255, 0, 0)), ]
    for frac, color in marks:
        x = int(width * frac)
        d.line([(x, 0), (x, im2.height)], fill=color, width=3)
    im2.save(out)
    return im.size


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=r"C:/Users/Administrator/AppData/Local/Temp/spinecal")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    for i, p in enumerate(REPS, 1):
        if not os.path.exists(p):
            print("skip", p)
            continue
        o = os.path.join(args.outdir, f"cal{i:02d}_{os.path.basename(p)}")
        print(o, make_strip(p, o))