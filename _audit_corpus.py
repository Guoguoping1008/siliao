#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全库 OCR 语料审计 + 入库门禁 (siliao / output2)

对 output2 下全部 md 做两级审计:
  门 1 · 文件级 —— 源图 ↔ md 文件名集合差分 + <!-- source: --> 溯源一致性
  门 2 · 内容级 —— 五信号联合判定 (碎片率 / 长句数 / 表头词 / 粘连 / 表格符号)

三档输出:
  A-INDEX   纯条文, 允许进 RAG 索引
  C-PARTIAL 正文可用 / 表格不可信 —— 进索引但由 chunk 层隔离表格区间
  B-EXCLUDE 表格结构崩塌, 禁止进索引 (仅存原文 + 图片路径)

用法:
    python _audit_corpus.py --list                 # 全库三档清单
    python _audit_corpus.py --build-dirs           # 生成 A/C/B 三个索引输入目录
    python _audit_corpus.py --check --index-dir D  # 体检索引源是否混入 B 类 (CI 门禁)
    python _audit_corpus.py --isolate-tables --out D  # 生成 C 类的表格隔离版 chunk 输入
"""
import argparse
import csv
import json
import os
import re
import sys

# ---------- 路径常量 ----------
REPO = os.path.dirname(os.path.abspath(__file__))          # E:\workspace\siliao
OUT2 = os.path.join(REPO, "output2")
IMAGES = os.path.join(REPO, "Images")

# 分类目录 -> 源图目录名 (md 目录名与 Images 下的目录名不一致时映射)
CAT_IMG_DIR = {
    "000封面": "000封面",
    "001目录": "001目录",
    "01法规": "01法规",
    "02制度文件": "02制度文件",
    "03相关法规法律法规文件": "03相关法规法律法规文件",
    "04标准及标准目录": "04标准及标准目录",
}

# ---------- 判定信号 ----------
# 表头词 —— 只收「表格列名」特征词。
# 坑: "附录" 会出现在正文散文里("见附录D"), 不能当表头信号;
#      "附表" 同理。列名必须是可独立成表的短标签。
HEADER_TOKENS = ("序号", "机构名称", "报告签发人", "报告签发机构", "联系电话",
                 "机构类型", "试验场地名称", "试验场地地址", "证书编号",
                 "试验机构名称", "续表")
GLUE_TOKENS = ("序号", "机构名称", "签发人", "联系电话", "机构类型",
               "报告签发", "试验场地")
SYMBOL_LINE = re.compile(r"[+＋*￥√✓\-—＝=]{1,4}")
MD_HEADING = re.compile(r"^#{1,6}\s+\S")
SOURCE_RE = re.compile(r"<!--\s*source:\s*(.+?)\s*-->", re.S)

# 错字白名单 —— 只用已确认的组合, 别写宽正则
TYPO_FIX = {
    "投人": "投入", "中请": "申请", "私舞": "徇私舞弊",
    "坦生": "报告", "提世": "提供", "出u": "试验",
    "左效": "有效", "报生)": "报告等)", "编生": "编制",
    "纳人": "纳入", "理吿": "理工", "认i": "认定",
}

CLS_META = {
    "A": ("A-INDEX", "yes", "纯条文文本, 条款层级完整, 检索与问答可用"),
    "C": ("C-PARTIAL", "yes", "正文可用, 表格区间不可信 —— 需 chunk 层隔离"),
    "B": ("B-EXCLUDE", "no", "表格结构丢失, 禁止进索引, 仅存元数据+图片"),
}


# ---------- 指标 ----------
def analyze_body(body):
    lines = [l.strip() for l in body.split("\n") if l.strip()]
    if not lines:
        return dict(lines=0, prose_lines=0, hdr_lines=0, frag=0, longs=0,
                    sym=0, hdr=0, glue=0,
                    frag_ratio=0.0, cn_chars=0, paren_delta=0, adj_dup=0)
    # 碎片率只统计「正文行」—— markdown 标题行(## 第三章 / ### 第十一条)是结构标记,
    # 不是 OCR 碎片. 坑: 带 12 章 + 30 条的纯条文页, 标题行数会超过正文行数,
    # 不排除的话碎片率虚高到 0.44, 被误判成 C.
    prose_lines = [l for l in lines if not MD_HEADING.match(l)]
    frag = sum(1 for l in prose_lines if len(l) <= 12)
    longs = sum(1 for l in prose_lines if len(l) >= 40)
    sym = sum(1 for l in lines if SYMBOL_LINE.fullmatch(l))
    hdr = sum(body.count(t) for t in HEADER_TOKENS)
    glue = sum(1 for l in lines
               if sum(l.count(t) for t in GLUE_TOKENS) >= 2)
    norm = lambda s: re.sub(r"[^\u4e00-\u9fff0-9]", "", s)
    adj = 0
    for i in range(len(lines) - 1):
        a, b = norm(lines[i]), norm(lines[i + 1])
        if len(a) >= 12 and len(b) >= 12 and (a in b or b in a):
            adj += 1
    return dict(lines=len(lines), prose_lines=len(prose_lines),
                hdr_lines=len(lines) - len(prose_lines),
                frag=frag, longs=longs, sym=sym, hdr=hdr,
                glue=glue, frag_ratio=round(frag / max(1, len(prose_lines)), 2),
                cn_chars=len(re.findall(r"[\u4e00-\u9fff]", body)),
                paren_delta=body.count("\uff08") - body.count("\uff09"),
                adj_dup=adj)


def classify(d):
    """五信号联合判定 —— 碎片率不能单独用

    注意: sym(表格符号行) / hdr(表头词) / glue(粘连) 三个信号**独立于碎片率**,
    必须能单独触发 B. 坑: 表格的单元格标记被打成独立行时, 这些行会被计入
    prose_lines 但 frag_ratio 可能不够高, 只靠碎片率会把这类表格放行.
    """
    # --- B: 表格结构已崩塌 ---
    if d["sym"] >= 40:
        return "B"
    if d["hdr"] >= 8:
        return "B"
    if d["longs"] <= 1 and d["frag_ratio"] >= 0.55:
        return "B"
    if d["frag_ratio"] >= 0.85:
        return "B"
    if d["frag_ratio"] >= 0.60 and d["longs"] <= 6:
        return "B"
    # --- C: 正文可用, 表格不可信 ---
    if d["frag_ratio"] >= 0.42 or d["hdr"] >= 3 or d["glue"] >= 1 or d["sym"] >= 5:
        return "C"
    return "A"


def audit_all():
    """全库审计: 门1 文件级 + 门2 内容级"""
    rows = []
    gate1 = {"missing": [], "extra": [], "dup": [], "prov_bad": [], "no_img_dir": []}

    # 收集所有 md (递归), 排除本脚本产出的辅助文件
    all_md = []
    for dp, dns, fns in os.walk(OUT2):
        dns[:] = [d for d in dns if d not in ("_rag_index_split", "_chunk_split")]
        for fn in fns:
            if fn.endswith(".md") and not fn.startswith("_"):
                all_md.append(os.path.join(dp, fn))

    # 按分类目录分组
    by_cat = {}
    for f in all_md:
        rel = os.path.relpath(f, OUT2)
        cat = os.path.dirname(rel).replace("\\", "/")
        by_cat.setdefault(cat, []).append(f)

    # --- 门 1 · 文件级: 源图 vs md, 在【顶层分类】粒度比对 ---
    # (md 的子目录是按编号连续区间拆的, 不是按源图目录拆的,
    #  所以门 1 必须在顶层分类比, 拿子目录去比会误报几千条"缺")
    by_top = {}
    for cat, files in by_cat.items():
        by_top.setdefault(cat.split("/")[0], []).extend(files)
    for top, files in sorted(by_top.items()):
        img_dir = os.path.join(IMAGES, CAT_IMG_DIR.get(top, top))
        if not os.path.isdir(img_dir):
            gate1["no_img_dir"].append(top)
            img_stems = set()
        else:
            img_stems = {os.path.splitext(fn)[0]
                         for fn in os.listdir(img_dir)
                         if fn.lower().endswith((".jpg", ".jpeg", ".png"))}
        md_stems = [os.path.splitext(os.path.basename(f))[0] for f in files]
        md_stem_set = set(md_stems)
        if len(md_stems) != len(md_stem_set):
            seen, dup = set(), set()
            for s in md_stems:
                (dup if s in seen else seen).add(s)
            gate1["dup"].extend(f"{top}/{s}" for s in sorted(dup))
        gate1["missing"].extend(f"{top}/{s}" for s in sorted(img_stems - md_stem_set))
        gate1["extra"].extend(f"{top}/{s}" for s in sorted(md_stem_set - img_stems))

    # --- 门 2 · 内容级 ---
    for cat, files in sorted(by_cat.items()):
        img_cat = cat.split("/")[0]
        for f in files:
            base = os.path.basename(f)
            stem = os.path.splitext(base)[0]
            txt = open(f, encoding="utf-8").read()
            m = SOURCE_RE.search(txt)
            body = SOURCE_RE.sub("", txt)
            expected = f"{img_cat}/{stem}.jpg"
            if not m:
                prov = "NO-SOURCE"
            else:
                src = m.group(1).replace("\\", "/")
                prov = "OK" if src == expected else f"BAD:{src}"
            if prov != "OK":
                gate1["prov_bad"].append(f"{cat}/{base}")
            d = analyze_body(body)
            cls = classify(d)
            code, allowed, note = CLS_META[cls]
            rows.append(dict(
                category=cat, stem=stem, md=os.path.relpath(f, REPO).replace("\\", "/"),
                jpg=f"Images/{img_cat}/{stem}.jpg", cls=cls, code=code,
                index_allowed=allowed, provenance=prov,
                frag_ratio=d["frag_ratio"], long_sentences=d["longs"],
                header_hits=d["hdr"], glue_hits=d["glue"], table_symbols=d["sym"],
                adj_dup=d["adj_dup"], paren_delta=d["paren_delta"],
                cn_chars=d["cn_chars"], note=note))

    return rows, gate1


# ---------- C 类: 表格区间隔离 ----------
def split_table_regions(body, d):
    """
    把 C 类 md 切成 [正文段 | 表格段] 两类区段。
    判据: 表格特征密集的连续行区间 = 表格区。
    返回 [(kind, text), ...], kind in {'prose','table'}
    """
    lines = body.split("\n")
    idx = [i for i, l in enumerate(lines) if l.strip()]
    if not idx:
        return []
    is_tbl = [False] * len(lines)
    for i in idx:
        l = lines[i].strip()
        if SYMBOL_LINE.fullmatch(l):
            is_tbl[i] = True
        elif sum(l.count(t) for t in GLUE_TOKENS) >= 2:
            is_tbl[i] = True
        elif len(l) <= 12 and sum(l.count(t) for t in HEADER_TOKENS) >= 1:
            is_tbl[i] = True
        elif MD_HEADING.match(l):
            # 标题行本身不是表格, 但如果它紧邻表格特征行则并入表格区
            is_tbl[i] = False
    # 表头词密集窗口 -> 连带区间
    for i in idx:
        if sum(lines[i].count(t) for t in HEADER_TOKENS) >= 2:
            for j in range(max(0, i - 2), min(len(lines), i + 3)):
                if lines[j].strip():
                    is_tbl[j] = True
    # 合并相邻 table 段
    segs, cur, cur_kind = [], [], None
    for i, l in enumerate(lines):
        if not l.strip():
            continue
        k = "table" if is_tbl[i] else "prose"
        if cur_kind is None:
            cur_kind, cur = k, [l]
        elif k == cur_kind:
            cur.append(l)
        else:
            segs.append((cur_kind, cur))
            cur_kind, cur = k, [l]
    if cur_kind:
        segs.append((cur_kind, cur))
    return [(k, "\n".join(v).strip()) for k, v in segs if v]


def cmd_isolate_tables(args):
    """为 C 类生成表格隔离版: 表格段单独输出到 *_tables.md, 正文段输出到 *_prose.md"""
    rows, _ = audit_all()
    crows = [r for r in rows if r["cls"] == "C"]
    outdir = args.out or os.path.join(OUT2, "_chunk_split")
    os.makedirs(outdir, exist_ok=True)
    manifest = []
    for r in crows:
        src = os.path.join(REPO, r["md"])
        body = SOURCE_RE.sub("", open(src, encoding="utf-8").read()).strip()
        segs = split_table_regions(body, r)
        prose_parts = [t for k, t in segs if k == "prose"]
        table_parts = [t for k, t in segs if k == "table"]
        cat_tag = r["category"].replace("/", "-").replace(" ", "")
        stem = r["stem"]
        pfile = f"{cat_tag}__{stem}_prose.md"
        tfile = f"{cat_tag}__{stem}_tables.md"
        with open(os.path.join(outdir, pfile), "w", encoding="utf-8") as f:
            f.write(f"<!-- source: {r['md']} -->\n")
            f.write(f"<!-- chunk-role: prose (table regions removed) -->\n\n")
            f.write("\n\n".join(prose_parts) if prose_parts else "")
        with open(os.path.join(outdir, tfile), "w", encoding="utf-8") as f:
            f.write(f"<!-- source: {r['md']} -->\n")
            f.write(f"<!-- chunk-role: table (structure unreliable, do not index) -->\n\n")
            f.write("\n\n".join(table_parts) if table_parts else "")
        manifest.append(dict(stem=stem, category=r["category"], md=r["md"], cls=r["cls"],
                             prose_chunks=len(prose_parts),
                             table_chunks=len(table_parts),
                             prose_file=pfile, table_file=tfile,
                             prose_chars=sum(len(p) for p in prose_parts),
                             table_chars=sum(len(t) for t in table_parts)))
    with open(os.path.join(outdir, "_isolate_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(f"C 类 {len(crows)} 个文件, 表格隔离输出到: {outdir}")
    print(f"{'stem':8} {'正文段':>6} {'表格段':>6} {'正文字数':>8} {'表格字数':>8}")
    for m in manifest:
        print(f"{m['stem']:8} {m['prose_chunks']:6} {m['table_chunks']:6} "
              f"{m['prose_chars']:8} {m['table_chars']:8}")
    tot_p = sum(m["prose_chars"] for m in manifest)
    tot_t = sum(m["table_chars"] for m in manifest)
    print(f"\n正文合计 {tot_p} 字 / 表格合计 {tot_t} 字 "
          f"(表格部分占比 {tot_t/max(1,tot_p+tot_t):.0%}, 已隔离)")
    return 0


# ---------- 子命令 ----------
def cmd_list(args):
    rows, gate1 = audit_all()
    buckets = {"A": [], "C": [], "B": []}
    by_cat = {}
    for r in rows:
        buckets[r["cls"]].append(r["stem"])
        by_cat.setdefault(r["category"], []).append(r["cls"])

    print("=" * 78)
    print("门 1 · 文件级一致性")
    print("=" * 78)
    print(f"  md 总数         : {len(rows)}")
    print(f"  图片缺 md       : {len(gate1['missing'])}")
    print(f"  md 多出(无源图) : {len(gate1['extra'])}")
    print(f"  文件名重复      : {len(gate1['dup'])}")
    print(f"  溯源注释异常    : {len(gate1['prov_bad'])}")
    for k in ("missing", "extra", "dup", "prov_bad"):
        if gate1[k]:
            for x in gate1[k][:20]:
                print(f"      - {x}")
    print()
    print("=" * 78)
    print("门 2 · 内容质量 (五信号联合判定)")
    print("=" * 78)
    print(f"{'分类目录':40} {'总数':>5} {'A':>4} {'C':>4} {'B':>4}")
    for cat in sorted(by_cat):
        cs = by_cat[cat]
        print(f"{cat:40} {len(cs):5} {cs.count('A'):4} {cs.count('C'):4} {cs.count('B'):4}")
    print(f"{'合计':40} {len(rows):5} {len(buckets['A']):4} {len(buckets['C']):4} {len(buckets['B']):4}")
    print()
    for c, label in (("A", "A-INDEX   进 RAG 索引"),
                      ("C", "C-PARTIAL 进索引, chunk 层隔离表格区间"),
                      ("B", "B-EXCLUDE 禁止进索引, 仅存元数据+图片")):
        print(f"{label}  ({len(buckets[c])})")
        for i in range(0, len(buckets[c]), 12):
            print("  " + " ".join(buckets[c][i:i + 12]))
        print()
    return 0


def cmd_build_dirs(args):
    rows, _ = audit_all()
    root = os.path.join(OUT2, "_rag_index_split")
    names = {"A": "A-INDEX", "C": "C-PARTIAL", "B": "B-EXCLUDE"}
    for c, name in names.items():
        d = os.path.join(root, name)
        os.makedirs(d, exist_ok=True)
        for fn in os.listdir(d):
            os.remove(os.path.join(d, fn))
        for r in rows:
            if r["cls"] != c:
                continue
            # 文件名带分类前缀, 防止不同分类下同 stem 互相覆盖
            cat_tag = r["category"].replace("/", "-").replace(" ", "")
            stem = r["stem"]
            fname = f"{cat_tag}__{stem}.md"
            tgt = os.path.join(d, fname)
            src = os.path.normpath(os.path.join(REPO, r["md"]))
            try:
                os.symlink(src, tgt)
            except OSError:
                with open(tgt + ".txt", "w", encoding="utf-8") as f:
                    f.write(f"{r['md']}\nsource_image: {r['jpg']}\n")
    print(f"输出目录: {root}")
    for c, name in names.items():
        n = sum(1 for r in rows if r["cls"] == c)
        print(f"  {name}: {n} 个")
    return 0


def cmd_check(args):
    rows, _ = audit_all()
    # 索引目录里的文件名格式是 <category-tag>__<stem>.md, 按同一格式比对
    banned = set()
    banned_stems = set()
    for r in rows:
        if r["cls"] != "B":
            continue
        cat_tag = r["category"].replace("/", "-").replace(" ", "")
        banned.add(f"{cat_tag}__{r['stem']}.md")
        banned_stems.add(r["stem"])          # 兼容旧命名(纯 stem.md)
    idx = args.index_dir
    if not idx or not os.path.isdir(idx):
        print("用法: --check --index-dir <索引源目录>")
        return 2
    hits = []
    for dp, _, fns in os.walk(idx):
        for fn in fns:
            if not fn.endswith(".md"):
                continue
            if fn in banned or os.path.splitext(fn)[0] in banned_stems:
                hits.append(os.path.join(dp, fn))
    print(f"扫描 {idx}")
    print(f"B-EXCLUDE 文件数: {len(banned_stems)}")
    if hits:
        print(f"\n!! 索引源中混入 {len(hits)} 个禁止索引文件:")
        for h in hits:
            print("   " + h)
        return 1
    print("\nOK: 索引源未混入 B-EXCLUDE 文件。")
    return 0


def cmd_report(args):
    rows, gate1 = audit_all()
    out_csv = os.path.join(OUT2, "_audit_manifest_all.csv")
    out_json = os.path.join(OUT2, "_audit_manifest_all.json")
    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    summary = {}
    for r in rows:
        summary[r["cls"]] = summary.get(r["cls"], 0) + 1
    json.dump(dict(
        generated_by="qingmang-cto 全库审计",
        scope="output2 (全库)",
        md_count=len(rows),
        gate1=dict(missing=len(gate1["missing"]), extra=len(gate1["extra"]),
                   dup=len(gate1["dup"]), provenance_bad=len(gate1["prov_bad"]),
                   missing_list=gate1["missing"], extra_list=gate1["extra"],
                   dup_list=gate1["dup"], prov_bad_list=gate1["prov_bad"]),
        summary=summary,
        rule=("B: 长句<=1且碎片率>=0.55 | 表格符号>=40 | 表头词>=8 | 碎片率>=0.85 "
              "| (碎片率>=0.60且长句<=6)   "
              "C: 碎片率>=0.42 | 表头词>=3 | 粘连>=1 | 表格符号>=5   A: 其他"),
        files=rows), open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"已写出:\n  {out_csv}\n  {out_json}")
    print(f"门1: 缺{len(gate1['missing'])} 多{len(gate1['extra'])} "
          f"重复{len(gate1['dup'])} 溯源异常{len(gate1['prov_bad'])}")
    print(f"门2: {summary}")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--build-dirs", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--report", action="store_true", help="写出全库 CSV/JSON 清单")
    ap.add_argument("--isolate-tables", action="store_true",
                    help="为 C 类生成表格隔离版 chunk 输入")
    ap.add_argument("--index-dir")
    ap.add_argument("--out")
    args = ap.parse_args()
    if args.list:
        return cmd_list(args)
    if args.build_dirs:
        return cmd_build_dirs(args)
    if args.check:
        return cmd_check(args)
    if args.report:
        return cmd_report(args)
    if args.isolate_tables:
        return cmd_isolate_tables(args)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
