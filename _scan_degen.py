#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全库扫 5 类表格/OCR 退化, 给出待修清单。

用法:  python _scan_degen.py [--only <class>]
"""
import argparse
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
MINIMAX = os.path.join(REPO, "minimax")
CACHE = os.path.join(REPO, ".mm_raw_cache")

TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
TD_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)


def load(path):
    try:
        return open(path, encoding="utf-8").read()
    except Exception:
        return ""


def md_files():
    out = []
    for dp, dns, fns in os.walk(MINIMAX):
        for fn in sorted(fns):
            if fn.endswith(".md") and not fn.endswith(".bak"):
                out.append(os.path.join(dp, fn))
    return out


def rel(p):
    return os.path.relpath(p, MINIMAX).replace("\\", "/")


def stem(p):
    return os.path.splitext(os.path.basename(p))[0]


def scan_class1_longtable(txt):
    """裸 LaTeX longtable 残留"""
    return "begin{longtable}" in txt or "\\begin{tabular}" in txt


def scan_class2_flat(txt):
    """整页挤成 1~3 行(长表格被压平)"""
    lines = [l for l in txt.split("\n") if l.strip()]
    if not lines:
        return False
    if len(lines) <= 3 and len(txt) > 800:
        # 排除正常的短页
        return True
    return False


def scan_class3_pseudo_table(txt):
    """正文页被当成表格: 表里 1 列, 或每格都是长段落。

    坑: **1 列的表不一定是伪表格** —— 实测 0422 是「GB/T 标准号清单」,
    天然就是 1 列。所以 1 列时必须要求「**每一格都很长**」才判定为伪表格,
    而且要排除「格子里是编号/标准号」这种短标签。
    """
    if "<table" not in txt.lower():
        return False
    tabs = re.findall(r"<table.*?</table>", txt, re.S | re.I)
    for tb in tabs:
        rows = TR_RE.findall(tb)
        if not rows:
            continue
        widths = []
        longcells = 0
        total = 0
        short_label = 0
        for tr in rows:
            cells = TD_RE.findall(tr)
            widths.append(len(cells))
            for c in cells:
                t = re.sub(r"<[^>]+>", "", c).strip()
                total += 1
                if len(t) > 40:
                    longcells += 1
                elif len(t) <= 20:
                    short_label += 1
        if not widths:
            continue
        maxw = max(widths)
        if maxw == 1:
            # 1 列: 必须是「每格都长」的散文段, 且不能有大量短标签
            if longcells >= 3 and short_label == 0:
                return True
            continue
        # 2 列以内且多数格子是长段落 -> 伪表格
        if maxw <= 2 and longcells >= max(3, total * 0.6) and short_label == 0:
            return True
    return False


def scan_class4_empty_cells(txt):
    """空单元格撑满 (退化输出)。

    坑: **空白表单模板本来就有大量空单元格**(实测 0186「表2 产品基本情况」
    是申报表模板, 空格子是设计如此), 不是缺陷。
    只有「格子数异常多(>=60)」才是模型编造出来的退化网格。
    """
    if "<table" not in txt.lower():
        return False
    tabs = re.findall(r"<table.*?</table>", txt, re.S | re.I)
    for tb in tabs:
        cells = TD_RE.findall(tb)
        if len(cells) < 60:          # 阈值: 表单模板一般 < 60 格
            continue
        empty = sum(1 for c in cells
                    if not re.sub(r"<[^>]+>|\s|&nbsp;", "", c).strip())
        if empty / len(cells) >= 0.5:
            return True
    return False


def scan_class5_huge(tabs):
    """退化输出体积异常 (>8KB 且 表格占大头)"""
    if len(tabs) < 8000:
        return False
    tbl = sum(len(t) for t in re.findall(r"<table.*?</table>", tabs, re.S | re.I))
    if tbl / len(tabs) > 0.7:
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=os.path.join(REPO, "_degen_scan.json"))
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    files = md_files()
    hits = {k: [] for k in
            ["1_longtable", "2_flat", "3_pseudo_table", "4_empty_cells", "5_huge"]}
    for p in files:
        txt = load(p)
        if not txt:
            continue
        r = rel(p)
        checks = {
            "1_longtable": scan_class1_longtable(txt),
            "2_flat": scan_class2_flat(txt),
            "3_pseudo_table": scan_class3_pseudo_table(txt),
            "4_empty_cells": scan_class4_empty_cells(txt),
            "5_huge": scan_class5_huge(txt),
        }
        for k, v in checks.items():
            if v and (not args.only or k == args.only):
                hits[k].append(r)

    for k in hits:
        print(f"\n=== {k}: {len(hits[k])} 个 ===")
        for r in hits[k][:60]:
            print("  ", r)
        if len(hits[k]) > 60:
            print(f"   ... 还有 {len(hits[k])-60} 个")

    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(hits, f, ensure_ascii=False, indent=1)
    print(f"\n清单: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
