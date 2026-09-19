"""
双页合拍图 → 左/右单页

输入:  Images/<timestamp>.jpg  (4240x3439 横向双页合拍)
输出:  data/markdown/<doc_id>/single_pages/<ts>__L.jpg / <ts>__R.jpg
       + manifest.json (记录 split 顺序,供下游 OCR 还原物理页序)

策略:
- 直接按宽 50% 切(中央书脊)。两张单页的尺寸约 2120x3439。
- 不做透视校正(交给 preprocess.py 沿用,后者已加面积守卫)
- 文件名加 __L / __R 后缀;manifest.json 记录:
    {
      "src": "20260913173708061.jpg",
      "ts": "20260913173708061",
      "L": "20260913173708061__L.jpg",   # 左页(偶数物理页)
      "R": "20260913173708061__R.jpg",   # 右页(奇数物理页)
      "src_size": [4240, 3439]
    }
- 物理页号 = 2*src_seq - 1 (左, 奇) / 2*src_seq (右, 偶)
  实际页码 = OCR 阶段从页眉/页脚读,这里只给物理页号。
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def split_one(src: Path, out_dir: Path) -> dict:
    """切一张双页合拍图, 返回 manifest entry"""
    img = cv2.imread(str(src), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"无法读取: {src}")
    h, w = img.shape[:2]
    if w < h:
        # 已经是竖排,直接当成单页
        left = img
        right = None
    else:
        # 横排,沿中线切;书脊一般在中央,但拍照时不一定正,先按 50% 切
        mid = w // 2
        left = img[:, :mid]
        right = img[:, mid:]

    ts = src.stem
    L_path = out_dir / f"{ts}__L.jpg"
    cv2.imwrite(str(L_path), left, [cv2.IMWRITE_JPEG_QUALITY, 92])
    manifest = {
        "src": src.name,
        "ts": ts,
        "L": L_path.name,
        "L_path": str(L_path),
        "src_size": [w, h],
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
    p.add_argument("src_dir", type=Path, help="Images/ 目录")
    p.add_argument("out_dir", type=Path, help="输出单页目录")
    p.add_argument("--limit", type=int, default=0, help="只处理前 N 张 (0=全部)")
    p.add_argument(
        "--manifest", type=Path, default=None,
        help="manifest.json 输出路径 (默认 <out_dir>/_manifest.json)"
    )
    args = p.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.manifest or (args.out_dir / "_manifest.json")

    paths = sorted(args.src_dir.glob("*.jpg"))
    if args.limit > 0:
        paths = paths[: args.limit]
    print(f"[split] {len(paths)} 张 → {args.out_dir}")

    manifest = []
    for i, p in enumerate(paths, 1):
        try:
            m = split_one(p, args.out_dir)
            manifest.append(m)
            if i % 50 == 0 or i == len(paths):
                print(f"[split] ({i}/{len(paths)}) {p.name} → {m.get('L','?')}, {m.get('R','?')}")
        except Exception as e:
            print(f"[split] FAIL {p.name}: {e}")
            manifest.append({"src": p.name, "error": str(e)})

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[split] 完成: {len(manifest)} 条 manifest → {manifest_path}")


if __name__ == "__main__":
    main()
