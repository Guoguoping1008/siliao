"""
双页合拍图 → 左/右单页 (v3: 列暗度计数 + 偏移校验 + fallback)

v2 教训: 直接找"最暗列"会被手指阴影/页眉条带骗。
v3 改进:
1. 用 (band < 100).sum(axis=0) 算"暗计数" — 抗噪,真书脊是"贯穿全图的暗"
2. 31px 滑动平均找 peak — 找稳定的"暗带中心",不是单个最暗点
3. 加 fallback:
   - 如果 peak 处 dark_count < 200, 没真书脊 → 50% 中线
   - 如果 peak 偏离中线 > 30% 半宽 (即 rel > 0.3 * w/2), 极端错位 → 50% 中线
   - 竖排图 (w < h): 当单页, 不切
4. 输出 manifest 标记 fallback, 便于 QA 抽查
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def find_spine(img: np.ndarray) -> tuple[int, float, str]:
    """返回 (spine_x, dark_count_at_peak, method)
    method: 'spine' / 'midline' / 'vertical'
    """
    h, w = img.shape[:2]
    if w < h:
        return -1, 0.0, "vertical"

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # 用 10-90% 高度带, 避页眉页脚
    band = gray[int(h * 0.10):int(h * 0.90), :]
    dark_count = (band < 100).sum(axis=0).astype(np.float32)
    # 31px 滑动平均
    kernel = np.ones(31) / 31
    smoothed = np.convolve(dark_count, kernel, mode="same")

    # 中央 30-70% 范围
    sl, sr = int(w * 0.30), int(w * 0.70)
    win = smoothed[sl:sr]
    if win.size == 0:
        return w // 2, 0.0, "midline"
    peak_rel = int(np.argmax(win))
    peak_x = sl + peak_rel
    peak_val = float(win[peak_rel])

    # Fallback 1: 没有真书脊 (peak 太弱)
    if peak_val < 200:
        return w // 2, peak_val, "midline"
    # Fallback 2: 极端偏移 (rel > 30% 半宽)
    rel = peak_x - w / 2
    if abs(rel) > 0.30 * (w / 2):
        return w // 2, peak_val, "midline"
    return peak_x, peak_val, "spine"


def split_one(src: Path, out_dir: Path) -> dict:
    img = cv2.imread(str(src), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"无法读取: {src}")
    h, w = img.shape[:2]

    spine_x, peak_val, method = find_spine(img)

    if method == "vertical":
        # 竖排, 当单页
        left = img
        right = None
    else:
        # 沿 spine 切 (margin 5px)
        margin = 5
        cut = max(margin, min(w - margin, int(spine_x)))
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
        "spine_x": int(spine_x) if spine_x > 0 else -1,
        "spine_method": method,
        "spine_peak": round(peak_val, 1),
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
    print(f"[split v3] {len(paths)} 张 → {args.out_dir}  (dark_count + fallback)")

    manifest = []
    method_count = {"spine": 0, "midline": 0, "vertical": 0}
    for i, src in enumerate(paths, 1):
        try:
            m = split_one(src, args.out_dir)
            manifest.append(m)
            method_count[m["spine_method"]] = method_count.get(m["spine_method"], 0) + 1
            if i % 50 == 0 or i == len(paths):
                print(f"[split v3] ({i}/{len(paths)}) methods={method_count}")
        except Exception as e:
            print(f"[split v3] FAIL {src.name}: {e}")
            manifest.append({"src": src.name, "error": str(e)})

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[split v3] 完成: {len(manifest)} 条. methods={method_count}")
    print(f"[split v3] manifest → {manifest_path}")


if __name__ == "__main__":
    main()
