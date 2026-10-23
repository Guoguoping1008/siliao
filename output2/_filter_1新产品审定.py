#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快档过滤清单 —— output2/02制度文件/1 新产品审定

用途: 把「表格结构被 OCR 打平」的 md 从 RAG 索引中排除, 只保留可检索的条文文本。
用法:
    python _filter_1新产品审定.py --list          # 打印清单
    python _filter_1新产品审定.py --build-dirs   # 生成 A/C/B 三个软链接目录供索引器读取
    python _filter_1新产品审定.py --check        # 对已有索引做体检(报告命中风险文件)

判定规则(可调, 见 QUALITY_RULES):
    A-INDEX    无表格且碎片率 < 0.42              -> 允许进索引
    C-PARTIAL  碎片率 >= 0.42 或含表头词/粘连/表格符号 -> 正文可用, 表格部分不可信
    B-EXCLUDE  长句<=1 且碎片率>=0.55, 或 表格符号>=40,
               或 表头词>=8, 或 碎片率>=0.85,
               或 (碎片率>=0.60 且 长句<=6)        -> 禁止进索引
"""
import argparse
import csv
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))          # output2/
SCOPE_REL = "02制度文件/1 新产品审定"
SCOPE_DIR = os.path.join(BASE, SCOPE_REL)
IMG_DIR = os.path.normpath(os.path.join(BASE, "..", "Images", "02制度文件"))
MANIFEST_CSV = os.path.join(BASE, "_filter_manifest_1新产品审定.csv")
MANIFEST_JSON = os.path.join(BASE, "_filter_manifest_1新产品审定.json")

HEADER_TOKENS = ("序号", "机构名称", "报告签发人", "报告签发机构", "联系电话",
                 "机构类型", "试验场地名称", "试验场地地址", "证书编号",
                 "试验机构名称", "续表", "附表")
GLUE_TOKENS = ("序号", "机构名称", "签发人", "联系电话", "机构类型",
               "报告签发", "试验场地")
SYMBOL_LINE = re.compile(r"[+＋*￥√✓\-—＝=]{1,4}")
SOURCE_RE = re.compile(r"<!--\s*source:\s*(.+?)\s*-->", re.S)

QUALITY_RULES = {
    "A": {"longs_max": None, "frag_max": 0.42, "sym_max": 4, "hdr_max": 2},
    "C": {"longs_max": None, "frag_max": 1.00, "sym_max": 39, "hdr_max": 7},
    "B": {},
}


def analyze(md_path):
    """返回单文件质量指标"""
    raw = open(md_path, encoding="utf-8").read()
    m = SOURCE_RE.search(raw)
    body = SOURCE_RE.sub("", raw)
    lines = [l.strip() for l in body.split("\n") if l.strip()]
    frag = [l for l in lines if len(l) <= 12]
    longs = [l for l in lines if len(l) >= 40]
    sym = len([l for l in lines if SYMBOL_LINE.fullmatch(l)])
    hdr = sum(body.count(t) for t in HEADER_TOKENS)
    glue = len([l for l in lines
                if sum(l.count(t) for t in GLUE_TOKENS) >= 2])
    return {
        "lines": len(lines),
        "frag": len(frag),
        "longs": len(longs),
        "sym": sym,
        "hdr": hdr,
        "glue": glue,
        "frag_ratio": round(len(frag) / max(1, len(lines)), 2),
        "cn_chars": len(re.findall(r"[\u4e00-\u9fff]", body)),
        "source": m.group(1) if m else None,
    }


def classify(d):
    if d["longs"] <= 1 and d["frag_ratio"] >= 0.55:
        return "B"
    if d["sym"] >= 40:
        return "B"
    if d["hdr"] >= 8:
        return "B"
    if d["frag_ratio"] >= 0.85:
        return "B"
    if d["frag_ratio"] >= 0.60 and d["longs"] <= 6:
        return "B"
    if d["frag_ratio"] >= 0.42 or d["hdr"] >= 3 or d["glue"] >= 1 or d["sym"] >= 5:
        return "C"
    return "A"


def collect():
    rows = []
    for fn in sorted(os.listdir(SCOPE_DIR)):
        if not fn.endswith(".md"):
            continue
        stem = fn[:-3]
        d = analyze(os.path.join(SCOPE_DIR, fn))
        cls = classify(d)
        rows.append({
            "stem": stem,
            "md": f"{SCOPE_REL}/{fn}".replace("\\", "/"),
            "jpg": f"Images/02制度文件/{stem}.jpg",
            "cls": cls,
            "index_allowed": "yes" if cls == "A" else "no",
            **{k: d[k] for k in ("frag_ratio", "longs", "hdr", "sym", "cn_chars")},
        })
    return rows


def cmd_list(args):
    rows = collect()
    buckets = {"A": [], "C": [], "B": []}
    for r in rows:
        buckets[r["cls"]].append(r["stem"])
    print(f"目录: {SCOPE_DIR}")
    print(f"总计 {len(rows)} 个 md\n")
    label = {"A": "A-INDEX   进 RAG 索引",
             "C": "C-PARTIAL 部分可用, 需人工确认",
             "B": "B-EXCLUDE 禁止进索引, 仅存元数据+图片"}
    for c in ("A", "C", "B"):
        print(f"{label[c]}  ({len(buckets[c])})")
        print("  " + " ".join(buckets[c]) + "\n")
    return 0


def cmd_build_dirs(args):
    rows = collect()
    root = os.path.join(BASE, "_rag_index_split")
    names = {"A": "A-INDEX", "C": "C-PARTIAL", "B": "B-EXCLUDE"}
    for c, name in names.items():
        d = os.path.join(root, name)
        os.makedirs(d, exist_ok=True)
        for r in rows:
            if r["cls"] != c:
                continue
            link = os.path.join(d, os.path.basename(r["md"]))
            if os.path.islink(link) or os.path.exists(link):
                os.remove(link)
            # Windows 无符号链接权限时退化为写一份索引说明
            try:
                os.symlink(os.path.normpath(os.path.join(BASE, r["md"])), link)
            except OSError:
                with open(link + ".txt", "w", encoding="utf-8") as f:
                    f.write(f"{r['md']}\nsource_image: {r['jpg']}\n")
    print(f"输出目录: {root}")
    for c, name in names.items():
        n = sum(1 for r in rows if r["cls"] == c)
        print(f"  {name}: {n} 个")
    return 0


def cmd_check(args):
    """体检: 检查索引器是否误收了 B 类文件"""
    rows = collect()
    banned = {r["stem"] for r in rows if r["cls"] == "B"}
    idx_dir = args.index_dir
    if not idx_dir or not os.path.isdir(idx_dir):
        print("用法: --check --index-dir <索引源目录>")
        print("将扫描该目录下 .md, 报告其中属于 B-EXCLUDE 的文件。")
        return 2
    hits = []
    for root, _, files in os.walk(idx_dir):
        for fn in files:
            if not fn.endswith(".md"):
                continue
            stem = fn[:-3]
            if stem in banned:
                hits.append(os.path.join(root, fn))
    print(f"扫描 {idx_dir}")
    print(f"B-EXCLUDE 文件数: {len(banned)}")
    if hits:
        print(f"\n!! 索引源中混入 {len(hits)} 个禁止索引文件:")
        for h in hits:
            print("   " + h)
        return 1
    print("\nOK: 索引源未混入 B-EXCLUDE 文件。")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="打印过滤清单")
    ap.add_argument("--build-dirs", action="store_true", help="生成 A/C/B 三个索引输入目录")
    ap.add_argument("--check", action="store_true", help="体检索引源是否混入 B 类")
    ap.add_argument("--index-dir", help="配合 --check 使用的索引源目录")
    args = ap.parse_args()

    if args.list:
        return cmd_list(args)
    if args.build_dirs:
        return cmd_build_dirs(args)
    if args.check:
        return cmd_check(args)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
