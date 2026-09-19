"""
找双页合拍图里的中央书脊,沿书脊中线切左右页。

方法:
- 书脊在合拍图中央偏左/右,是几乎垂直的暗带(物理上两页的装订线)
- 算法: 取中间 60% 高度的列均值(避开页眉页脚/正文),列越深(均值越低)越可能是书脊
- 加权: 用列最小值(暗带更突出) + 中位数(抗反光噪点)
- 在最暗的 5% 邻域里取最暗列作为书脊 x
- 兜底: 找不到就回退 50% 中线

输出: 左/右单页 + manifest (与 split_double_page.py 同结构)
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def find_spine_x(img: np.ndarray) -> int:
    """返回书脊在 img 中的 x 坐标 (0..w)"""
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 取中间 60% 高度,避开页眉页脚和正文上下行
    y1 = int(h * 0.15)
    y2 = int(h * 0.85)
    band = gray[y1:y2, :]

    # 每列的"暗度"用 (255 - 中位数) + 权重
    col_min = np.min(band, axis=0).astype(np.float32)
    col_med = np.median(band, axis=0).astype(np.float32)
    darkness = (255.0 - col_min) * 1.5 + (255.0 - col_med) * 1.0

    # 只在中央 30%~70% 找,避免误判页边
    search_l = int(w * 0.30)
    search_r = int(w * 0.70)
    center_window = darkness[search_l:search_r]
    spine_rel = int(np.argmax(center_window))
    spine_x = search_l + spine_rel
    return spine_x


def split_one(src: Path, out_dir: Path) -> dict:
    img = cv2.imread(str(src), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"无法读取: {src}")
    h, w = img.shape[:2]

    if w < h:
        # 竖排,当成单页
        left = img
        right = None
        spine_x = -1
    else:
        spine_x = find_spine_x(img)
        # 沿书脊切: 左页 = [0, spine_x), 右页 = [spine_x, w)
        # 保险起见,书脊左右各留 5 像素(避免切到字)
        margin = 5
        cut = max(margin, min(w - margin, spine_x))
        left = img[:, :cut]
        right = img[:, cut:]

    ts = src.stem
    L_path = out_dir / f"{ts}__L.jpg"
    cv2.imwrite(str(L_path), left, [cv2.IMWRITE_JPEG_QUALITY, 92])
    manifest = {
        "src": src.name,
        "ts": ts,
        "L": L_path.name,
        "L_path": str(L_path),
        "src_size": [w, h],
        "spine_x": int(spine_x),
        "L_size": [left.shape[1], left.shape[0]],
    }
    if right is not None:
        R_path = out_dir / f"{ts}__R.jpg"
        cv2.imwrite(str(R_path), right, [cv2.IMWRITE_JPEG_QUALITY, 92])
        manifest["R"] = R_path.name
        manifest["R_path"] = str(R_path)
        manifest["R_size"] = [right.shape[1], right.shape[0]]
    return manifest


def main():
    p = argparse.ArgumentParser()
    p.add_argument("src_dir", type=Path)
    p.add_argument("out_dir", type=Path)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--manifest", type=Path, default=None)
    args = p.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.manifest or (args.out_dir / "_manifest.json")

    paths = sorted(args.src_dir.glob("*.jpg"))
    if args.limit > 0:
        paths = paths[: args.limit]
    print(f"[split] {len(paths)} 张 → {args.out_dir}  (spine-aware)")

    manifest = []
    spine_xs = []
    for i, src in enumerate(paths, 1):
        try:
            m = split_one(src, args.out_dir)
            manifest.append(m)
            if m.get("spine_x", -1) > 0:
                spine_xs.append(m["spine_x"])
            if i % 50 == 0 or i == len(paths):
                avg_spine = sum(spine_xs) / len(spine_xs) if spine_xs else 0
                print(f"[split] ({i}/{len(paths)}) spine_x avg={avg_spine:.0f}  latest {m.get('spine_x','?')}")
        except Exception as e:
            print(f"[split] FAIL {src.name}: {e}")
            manifest.append({"src": src.name, "error": str(e)})

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if spine_xs:
        sx = np.array(spine_xs)
        w = manifest[0]["src_size"][0]
        print(f"[split] 完成: {len(manifest)} 条. spine_x "
              f"min={sx.min()} max={sx.max()} mean={sx.mean():.0f} "
              f"rel_to_mid={(sx.mean()-w/2):.0f} (理想 0, 正数=书脊偏右, 负=偏左)")
    print(f"[split] manifest → {manifest_path}")


if __name__ == "__main__":
    main()
