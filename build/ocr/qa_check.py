"""
OCR 质量闸门: 批量跑完后自动找出"可疑页", 避免 1005 页里静默丢内容。

为什么必须有这个脚本 (2026-09-08 事故):
- preprocess.py 的透视校正把 058.jpg 从 1280x1707 裁成 1030x484 (剩 23%),
  整个"表 1 猪"和半个"表 2 家禽"被裁掉, OCR 行数 83→34,
  「后备种用火鸡」整行凭空消失 —— 而流水线一声不响, 全绿通过。
- feed-trial-guideline-2023 有 14/33 页 (42%) 中招。
- 1005 页规模下不可能靠肉眼复核, 必须让异常页自己冒出来。

四类检查:
1. area_loss  : preprocess 面积保留 < 阈值 (透视校正裁掉了真实内容)
2. low_lines  : OCR 行数显著低于全书中位数 (页面没识别全 / 拍虚了)
3. low_score  : 平均置信度低于阈值 (对焦不准 / 反光 / 阴影)
4. page_gap   : 页码序列断号 (漏拍) —— 依赖文件名里的页码

用法:
  python build/ocr/qa_check.py data/markdown/<doc_id>
  python build/ocr/qa_check.py data/markdown/<doc_id> --json report.json
退出码: 有 CRITICAL 级问题时返回 1, 便于挂到 run_all.sh 里卡住后续步骤。
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path


def check_area_loss(doc_dir: Path, min_area: float = 0.75) -> list[dict]:
    """preprocess_meta 里面积保留率过低的页"""
    issues = []
    meta_dir = doc_dir / "preprocess_meta"
    if not meta_dir.exists():
        return issues
    for f in sorted(meta_dir.glob("*.json")):
        m = json.loads(f.read_text(encoding="utf-8"))
        sw, sh = m.get("src_size", [0, 0])
        ow, oh = m.get("out_size", [0, 0])
        if sw * sh == 0:
            continue
        ratio = (ow * oh) / (sw * sh)
        if ratio < min_area:
            issues.append({
                "level": "CRITICAL",
                "kind": "area_loss",
                "page": f.stem,
                "detail": f"面积保留 {ratio:.2f} < {min_area} ({sw}x{sh}->{ow}x{oh})",
            })
    return issues


def check_ocr_quality(
    doc_dir: Path, line_ratio: float = 0.45, min_score: float = 0.85
) -> list[dict]:
    """行数异常少 / 置信度异常低的页"""
    issues = []
    raw_dir = doc_dir / "raw_ocr"
    if not raw_dir.exists():
        return issues

    stats = {}
    for f in sorted(raw_dir.glob("*.json")):
        lines = json.loads(f.read_text(encoding="utf-8"))
        scores = [l.get("score", 1.0) for l in lines]
        stats[f.stem] = {
            "n": len(lines),
            "avg_score": statistics.mean(scores) if scores else 0.0,
        }
    if not stats:
        return issues

    counts = [s["n"] for s in stats.values()]
    median_n = statistics.median(counts)

    for stem, s in stats.items():
        if median_n > 0 and s["n"] < median_n * line_ratio:
            issues.append({
                "level": "CRITICAL",
                "kind": "low_lines",
                "page": stem,
                "detail": f"行数 {s['n']} < 中位数 {median_n:.0f} 的 {line_ratio:.0%}",
            })
        if s["avg_score"] < min_score:
            issues.append({
                "level": "WARN",
                "kind": "low_score",
                "page": stem,
                "detail": f"平均置信度 {s['avg_score']:.3f} < {min_score}",
            })
    return issues


def check_page_gaps(doc_dir: Path) -> list[dict]:
    """文件名里的页码断号 (漏拍)。只在文件名是纯数字时生效。"""
    issues = []
    raw_dir = doc_dir / "raw_ocr"
    if not raw_dir.exists():
        return issues
    nums = []
    for f in raw_dir.glob("*.json"):
        if re.fullmatch(r"\d+", f.stem):
            nums.append(int(f.stem))
    if len(nums) < 2:
        return issues
    nums.sort()
    for a, b in zip(nums, nums[1:]):
        if b - a > 1:
            issues.append({
                "level": "CRITICAL",
                "kind": "page_gap",
                "page": f"{a}->{b}",
                "detail": f"页码断号: 缺 {list(range(a + 1, b))}",
            })
    return issues


def check_table_sanity(doc_dir: Path, sub: str = "pages") -> list[dict]:
    """markdown 表格列数不一致 (表格还原错位)"""
    issues = []
    pages_dir = doc_dir / sub
    if not pages_dir.exists():
        return issues
    for f in sorted(pages_dir.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        block: list[int] = []
        for line in text.split("\n"):
            if line.startswith("|"):
                block.append(line.count("|"))
            elif block:
                if len(set(block)) > 1:
                    issues.append({
                        "level": "WARN",
                        "kind": "table_ragged",
                        "page": f.stem,
                        "detail": f"表格列数不一致: {sorted(set(block))}",
                    })
                block = []
    return issues


def main():
    p = argparse.ArgumentParser()
    p.add_argument("doc_dir", type=Path)
    p.add_argument("--min-area", type=float, default=0.75)
    p.add_argument("--line-ratio", type=float, default=0.45)
    p.add_argument("--min-score", type=float, default=0.85)
    p.add_argument("--pages-sub", default="pages")
    p.add_argument("--json", type=Path, default=None, help="把报告写成 JSON")
    args = p.parse_args()

    issues: list[dict] = []
    issues += check_area_loss(args.doc_dir, args.min_area)
    issues += check_ocr_quality(args.doc_dir, args.line_ratio, args.min_score)
    issues += check_page_gaps(args.doc_dir)
    issues += check_table_sanity(args.doc_dir, args.pages_sub)

    crit = [i for i in issues if i["level"] == "CRITICAL"]
    warn = [i for i in issues if i["level"] == "WARN"]

    print(f"[qa_check] {args.doc_dir}")
    print(f"[qa_check] CRITICAL={len(crit)}  WARN={len(warn)}")
    for i in crit + warn:
        print(f"  [{i['level']:8}] {i['kind']:14} {i['page']:12} {i['detail']}")

    if args.json:
        args.json.write_text(
            json.dumps({"critical": crit, "warn": warn}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[qa_check] 报告已写入 {args.json}")

    if crit:
        print(f"[qa_check] FAIL: {len(crit)} 个 CRITICAL 问题, 请先修这些页再灌库")
        return 1
    print("[qa_check] PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
