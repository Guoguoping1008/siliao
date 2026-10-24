"""列出全库所有含表格的页面。

输出:
  1) 汇总(页数/表格块数/按 scope 分布)
  2) 逐页明细(stem, 路径, 表格块数, 每块的行列数, 表头)
"""
import collections
import json
import os
import re

MINIMAX = r"E:/workspace/siliao/minimax"
OUT_JSON = r"E:/workspace/siliao/_tbl_list.json"


def is_sep(l):
    cells = [x.strip() for x in l.strip().strip("|").split("|")]
    return bool(cells) and all(x and set(x) <= set("-:") for x in cells)


def ncols(l):
    return len(l.strip().strip("|").split("|"))


def blocks_of(lines):
    out, cur = [], []
    for l in lines:
        if l.strip().startswith("|"):
            cur.append(l)
        else:
            if cur:
                out.append(cur)
                cur = []
    if cur:
        out.append(cur)
    return out


def split_blocks(b):
    """一个连续 | 块里可能有多张表"""
    tabs, cur, i = [], [], 0
    while i < len(b):
        if (i + 1 < len(b) and not is_sep(b[i]) and is_sep(b[i + 1])
                and ncols(b[i]) == ncols(b[i + 1])):
            if cur:
                tabs.append(cur)
                cur = []
        cur.append(b[i])
        i += 1
    if cur:
        tabs.append(cur)
    return tabs


pages = []
for dp, dns, fns in os.walk(MINIMAX):
    for f in sorted(fns):
        if not f.endswith(".md"):
            continue
        p = os.path.join(dp, f)
        lines = open(p, encoding="utf-8").read().splitlines()
        tabs = []
        for b in blocks_of(lines):
            for t in split_blocks(b):
                if len(t) < 2:
                    continue
                sep = None
                for i, l in enumerate(t):
                    if is_sep(l):
                        sep = i
                        break
                hdr = t[0]
                dat = t[sep + 1:] if sep is not None else t[1:]
                w = max(ncols(l) for l in dat) if dat else ncols(hdr)
                tabs.append({
                    "hdr": [x.strip() for x in hdr.strip().strip("|").split("|")],
                    "rows": [[x.strip() for x in l.strip().strip("|").split("|")]
                             for l in dat],
                    "cols": w,
                    "nrows": len(dat),
                    "has_sep": sep is not None,
                })
        if not tabs:
            continue
        rel = os.path.relpath(p, MINIMAX)
        pages.append({
            "stem": f[:-3],
            "path": rel.replace(os.sep, "/"),
            "scope": rel.split(os.sep)[0],
            "tables": tabs,
        })

json.dump(pages, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

by_scope = collections.Counter(pg["scope"] for pg in pages)
ntab = sum(len(pg["tables"]) for pg in pages)
nrow = sum(t["nrows"] for pg in pages for t in pg["tables"])
print(f"含表格的页: {len(pages)}    表格块: {ntab}    数据行合计: {nrow}")
print(f"按 scope: {dict(by_scope)}")
print()
print("=" * 100)
print(f"{'页':<8}{'路径':<78}{'表':>3}{'行列'}")
print("=" * 100)
for pg in pages:
    dims = ", ".join(f"{t['nrows']}x{t['cols']}" for t in pg["tables"])
    print(f"{pg['stem']:<8}{pg['path'][:76]:<78}{len(pg['tables']):>3}  {dims}")
