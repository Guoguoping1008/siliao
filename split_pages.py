"""把跨页扫描图按左右拆成两张单页图。

命名规则(沿用原书页码体系):
  原图 0015.jpg = 书第 14 页(左/偶) + 第 15 页(右/奇)
  -> 0014.jpg = 左半(第14页)
  -> 0015.jpg = 右半(第15页), 文件名不变

切分位置 = 图像中线。
实测依据: 书脊弯曲会使"暗像素最稀疏处"偏离中线(实测 0.31~0.34),
但两页的**排版内容**对称分布在中线两侧, 中点即两页分界。
用暗像素找书脊会切错, 必须用几何中点。

单页图(如封面 2416x3168)也照切, 但会在报告里标注, 供人工复核。
"""
import os, re, sys, time, argparse, json
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spine_detect

SRC_ROOT = r"E:/workspace/siliao/Images"
DST_ROOT = r"E:/workspace/siliao/Images_split"
# 允许覆盖已存在的左半文件(重跑场景)
OVERWRITE = False


def left_name(fn):
    """0015.jpg -> 0014.jpg ; 封面00.jpg -> 无法推断则返回 None"""
    stem, ext = os.path.splitext(fn)
    m = re.fullmatch(r"(\d+)", stem)
    if m:
        n = int(m.group(1))
        if n <= 0:
            return None
        return f"{n - 1:0{len(m.group(1))}d}{ext}"
    return None


def split_slanted(im, diag, pad_color=(255, 255, 255), out_w=None):
    """沿斜书脊线切分, 两侧外接矩形裁剪, 不完整处补白。

    斜书脊使两页在图上呈梯形: 左页"上宽下窄"(或反之)。若直接按外接矩形裁剪,
    另一侧会缺失一块三角形区域, 因此把结果贴到白底画布上, 缺失处自然为空白。

    返回 (left_img, right_img)。
    """
    W, H = im.size
    xt = diag.get("x_top", 0.5) * W      # 顶部书脊 x(像素)
    xb = diag.get("x_bot", 0.5) * W       # 底部书脊 x(像素)

    # 左页区域: 沿书脊左侧, 取外接矩形 x∈[0, max(xt,xb)]
    # 右页区域: x∈[min(xt,xb), W]
    left_x1 = int(round(max(xt, xb)))
    right_x0 = int(round(min(xt, xb)))
    left_x1 = max(1, min(W - 1, left_x1))
    right_x0 = max(1, min(W - 1, right_x0))

    lw = left_x1
    rw = W - right_x0
    ow = out_w or max(lw, rw)             # 输出统一宽度, 便于对齐比较

    left_canvas = Image.new("RGB", (ow, H), pad_color)
    right_canvas = Image.new("RGB", (ow, H), pad_color)
    left_canvas.paste(im.crop((0, 0, left_x1, H)), (0, 0))
    right_canvas.paste(im.crop((right_x0, 0, W, H)), (0, 0))
    return left_canvas, right_canvas


def split_one(src, dst_dir, name_hint=None, quality=95, use_spine=False,
              slant=True):
    """把一张跨页图拆成左右两张。返回 (status, left_path, right_path, frac, mode)。

    use_spine=False : 按几何中点垂直切(默认)
    use_spine=True  : 用 spine_detect 检测书脊
    slant=True      : 沿斜书脊切, 外接矩形裁剪 + 补白(仅在 use_spine 时生效)
    """
    im = Image.open(src)
    W, H = im.size
    if W < 100:
        return None

    if use_spine:
        try:
            diag = spine_detect.detect_spine(im)
        except Exception:
            diag = {"x_top": 0.5, "x_bot": 0.5, "mode": "err"}
        diag = dict(diag)
        diag["x_top"] = min(0.58, max(0.42, diag.get("x_top", 0.5)))
        diag["x_bot"] = min(0.58, max(0.42, diag.get("x_bot", 0.5)))
        mode = diag.get("mode", "?")
        frac = (diag["x_top"] + diag["x_bot"]) / 2.0
        if slant:
            left, right = split_slanted(im, diag)
        else:
            mid = int(round(W * frac))
            left = im.crop((0, 0, mid, H))
            right = im.crop((mid, 0, W, H))
    else:
        frac, mode = 0.5, "mid"
        mid = W // 2
        left = im.crop((0, 0, mid, H))
        right = im.crop((mid, 0, W, H))

    fn = name_hint or os.path.basename(src)
    stem, ext = os.path.splitext(fn)
    right_name = fn                      # 右半保留原文件名
    lname = left_name(fn)
    if lname is None:
        # 无法推断页码(如"封面00"), 用 _L 后缀
        lname = f"{stem}_L{ext}"

    lp = os.path.join(dst_dir, lname)
    rp = os.path.join(dst_dir, right_name)
    os.makedirs(dst_dir, exist_ok=True)

    # 注意: 必须**分别**判断两个输出文件。
    # 之前只看 lp 是否存在就整体 SKIP, 导致 lp 已存在时 rp 也不写 ——
    # 重跑既有目录时右半永远不会被更新(实测 301 张全部 SKIP, 文件 mtime 未变)。
    skip_l = os.path.exists(lp) and not OVERWRITE
    skip_r = os.path.exists(rp) and not OVERWRITE
    if skip_l and skip_r:
        return ("SKIP", lp, rp, frac, mode)

    # jpg 有损, 用高保真设置
    kw = dict(quality=quality, subsampling=0, optimize=True)
    if not skip_l:
        left.save(lp, "JPEG", **kw)
    if not skip_r:
        right.save(rp, "JPEG", **kw)
    return ("OK", lp, rp, frac, mode)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=SRC_ROOT)
    ap.add_argument("--dst", default=DST_ROOT)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--folder", default="")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--spine", action="store_true",
                    help="启用书脊检测。默认关闭, 按几何中点切")
    ap.add_argument("--vertical", action="store_true",
                    help="检测到书脊后仍按垂直线切(不做斜切补白)")
    ap.add_argument("--no-spine", action="store_true",
                    help="显式指定几何中点(默认行为)")
    args = ap.parse_args()
    global OVERWRITE
    OVERWRITE = args.overwrite
    use_spine = args.spine and not args.no_spine
    slant = use_spine and not args.vertical

    imgs = []
    for dp, _, fs in os.walk(args.src):
        if args.folder and args.folder not in dp:
            continue
        for f in sorted(fs):
            if f.lower().endswith((".jpg", ".jpeg")):
                imgs.append(os.path.join(dp, f))
    imgs.sort()
    if args.limit:
        imgs = imgs[: args.limit]

    print(f"[scan] {len(imgs)} 张源图 -> {args.dst}")
    t0 = time.time()
    ok = skip = err = 0
    log = []
    for i, src in enumerate(imgs, 1):
        rel = os.path.relpath(src, args.src)
        dst_dir = os.path.join(args.dst, os.path.dirname(rel))
        try:
            r = split_one(src, dst_dir, use_spine=use_spine, slant=slant)
        except Exception as e:
            err += 1
            log.append({"src": rel, "status": "ERR", "msg": f"{type(e).__name__}: {e}"})
            print(f"  [{i}] ERR {rel}: {e}", flush=True)
            continue
        if r is None:
            err += 1
            continue
        st, lp, rp = r[0], r[1], r[2]
        frac = r[3] if len(r) > 3 else 0.5
        mode = r[4] if len(r) > 4 else "?"
        if st == "SKIP":
            skip += 1
        else:
            ok += 1
        log.append({"src": rel, "status": st,
                    "left": os.path.relpath(lp, args.dst).replace("\\", "/"),
                    "right": os.path.relpath(rp, args.dst).replace("\\", "/")})
        if i % 50 == 0 or i == len(imgs):
            el = time.time() - t0
            print(f"  {i}/{len(imgs)} ok={ok} skip={skip} err={err} "
                  f"{el/i:.2f}s/img eta={(len(imgs)-i)*el/i/60:.1f}min", flush=True)

    with open(os.path.join(args.dst, "_split_report.json"), "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=1)
    print(f"[done] ok={ok} skip={skip} err={err} total={time.time()-t0:.0f}s -> {args.dst}")


if __name__ == "__main__":
    main()