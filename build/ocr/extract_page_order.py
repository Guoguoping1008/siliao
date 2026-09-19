"""
OCR 后的页码提取 + 按页码重排。

输入:
  data/markdown/<doc_id>/raw_ocr/<stem>.json  (PaddleOCR 原始 bbox)
  data/markdown/<doc_id>/pages/<stem>.md       (拼好的页 markdown)
  data/markdown/<doc_id>/single_pages/_manifest.json  (split 时的 spine 信息)

输出:
  data/markdown/<doc_id>/_page_order.json  [{src, ts, L, R, page_num_L, page_num_R, ...}]

页码提取规则:
- 偶数页(左页) → 页码在左上角(整页最上面 + 最左)
- 奇数页(右页) → 页码在右上角(整页最上面 + 最右)
- 页码文本: 1-4 位纯数字
- 在 OCR 行里找: bbox.x1 极小 (或 x2 极大) + y1 极小 + 文本是 1-4 位数字

为什么需要这个:
- 文件名是拍摄时间戳, 跟书的物理页序不保证一致
- 用户拍时可能跳拍(漏拍回头补)
- 按真实页码排序后, 章节切分/表格还原才能正确
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

import numpy as np

PAGE_NUM_RE = re.compile(r"^\d{1,4}$")


def extract_page_num_bbox(lines: list[dict], corner: str, page_h: int, page_w: int) -> tuple[int | None, tuple]:
    """
    从 PaddleOCR 行的 bbox 找页码。
    corner: 'TL' (top-left) / 'TR' (top-right) / 'AUTO'
    AUTO: 找 y 在顶部 12% 且 (x1 < 5%w) 或 (x2 > 95%w) 的纯数字
    返回 (页码数字, (x1, y1, x2, y2) bbox)
    """
    if not lines:
        return None, ()

    # y 在顶部 12% 内的候选 (L 顶部 5-8%, R 顶部 8-12%, 都覆盖)
    y_threshold = page_h * 0.12
    # 边角宽度 12% (x1 < 12%w 或 x2 > 88%w)
    # 因为 PaddleOCR bbox 可能比真实位置略宽,需要宽容
    x_left_max = page_w * 0.12
    x_right_min = page_w * 0.88

    candidates = []
    for ln in lines:
        ys = [p[1] for p in ln["bbox"]]
        xs = [p[0] for p in ln["bbox"]]
        y_top = min(ys)
        x1 = min(xs)
        x2 = max(xs)
        if y_top > y_threshold:
            continue
        # 必须贴近边
        if x1 < x_left_max or x2 > x_right_min:
            text = ln["text"].strip()
            if PAGE_NUM_RE.match(text):
                candidates.append((y_top, x1, x2, int(text), ln["bbox"]))
    if not candidates:
        return None, ()
    # 选 y 最小的 (页码应该在最顶)
    candidates.sort()
    _, x1, x2, num, bbox = candidates[0]
    return num, bbox


def extract_page_num_for_split(manifest: list[dict], raw_ocr_dir: Path) -> dict:
    """对每个 split 出来的 L/R 单页,提取页码"""
    out = []
    for m in manifest:
        if "error" in m:
            continue
        entry = {
            "src": m["src"],
            "L": m.get("L"),
            "R": m.get("R"),
            "spine_method": m.get("spine_method"),
            "spine_x": m.get("spine_x"),
        }
        if m.get("L"):
            json_path = raw_ocr_dir / f"{Path(m['L']).stem}.json"
            if json_path.exists():
                lines = json.loads(json_path.read_text(encoding="utf-8"))
                L_size = m.get("L_size", [0, 0])
                num, _ = extract_page_num_bbox(lines, "AUTO", L_size[1], L_size[0])
                entry["page_num_L"] = num
        if m.get("R"):
            json_path = raw_ocr_dir / f"{Path(m['R']).stem}.json"
            if json_path.exists():
                lines = json.loads(json_path.read_text(encoding="utf-8"))
                R_size = m.get("R_size", [0, 0])
                num, _ = extract_page_num_bbox(lines, "AUTO", R_size[1], R_size[0])
                entry["page_num_R"] = num
        out.append(entry)
    return out


def sort_by_page_num(pages: list[dict]) -> list[dict]:
    """按 L 的页码排序(主要),L 没页码的按 R 排"""
    def key(p):
        pl = p.get("page_num_L")
        pr = p.get("page_num_R")
        if pl is not None:
            return (0, pl)
        if pr is not None and pr > 1:
            return (0, pr - 1)  # 假设 R 是奇数页
        return (1, 0)  # 不知道排最后
    return sorted(pages, key=key)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("doc_id", help="如 feed-law-collection-2023-full")
    args = p.parse_args()
    base = Path("data/markdown") / args.doc_id
    manifest_path = base / "single_pages" / "_manifest.json"
    raw_ocr_dir = base / "raw_ocr"
    out_path = base / "_page_order.json"

    if not manifest_path.exists():
        print(f"FAIL: manifest 不存在: {manifest_path}")
        return 1
    if not raw_ocr_dir.exists():
        print(f"FAIL: raw_ocr 目录不存在: {raw_ocr_dir}")
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    print(f"[page_order] 处理 {len(manifest)} 条 manifest")
    pages = extract_page_num_for_split(manifest, raw_ocr_dir)

    # 统计页码提取成功率
    L_ok = sum(1 for p in pages if p.get("page_num_L") is not None)
    R_ok = sum(1 for p in pages if p.get("page_num_R") is not None)
    print(f"[page_order] L 页码提取: {L_ok}/{len(pages)}")
    print(f"[page_order] R 页码提取: {R_ok}/{len(pages)}")

    # 排序
    pages_sorted = sort_by_page_num(pages)
    out_path.write_text(
        json.dumps(pages_sorted, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[page_order] → {out_path}")
    # 报告前 10 和后 10
    print("[page_order] 前 10 个:")
    for p in pages_sorted[:10]:
        L = p.get('page_num_L')
        R = p.get('page_num_R')
        Ls = str(L) if L is not None else '?'
        Rs = str(R) if R is not None else '?'
        print(f"  L={Ls:>4}  R={Rs:>4}  src={p['src']}")
    print("[page_order] 后 10 个:")
    for p in pages_sorted[-10:]:
        L = p.get('page_num_L')
        R = p.get('page_num_R')
        Ls = str(L) if L is not None else '?'
        Rs = str(R) if R is not None else '?'
        print(f"  L={Ls:>4}  R={Rs:>4}  src={p['src']}")


if __name__ == "__main__":
    main()
