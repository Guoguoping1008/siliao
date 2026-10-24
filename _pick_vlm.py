"""挑出"需要 VLM 重读"的页: 复杂表头 / 有合并迹象的表。

判据(按优先级):
  1) 表头行数 > 1 (两级表头)      -> 需要 colspan
  2) 数据行里有"首列为空"的续行    -> 需要 rowspan
  3) 列数 >= 8 (宽表)              -> 合并概率高
  4) 表头里有重复列名              -> 幻觉, 需要重新读

用法: python _pick_vlm.py
"""
import os
import re

base = r"E:/workspace/siliao/minimax"
ROW = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S | re.I)
CELL = re.compile(r"<t[dh]\b([^>]*)>(.*?)</t[dh]>", re.S | re.I)
TBL = re.compile(r"<table\b.*?</table>", re.S | re.I)

picks = []
for dp, dns, fns in os.walk(base):
    for f in sorted(fns):
        if not f.endswith(".md"):
            continue
        p = os.path.join(dp, f)
        t = open(p, encoding="utf-8").read()
        if "<table" not in t:
            continue
        for mi, m in enumerate(TBL.finditer(t)):
            rows = []
            for rm in ROW.finditer(m.group(0)):
                cells = []
                for cm in CELL.finditer(rm.group(1)):
                    d = dict(re.findall(r'(\w+)="([^"]*)"', cm.group(1)))
                    cells.append((d, re.sub(r"<[^>]+>", "", cm.group(2)).strip()))
                rows.append(cells)
            if len(rows) < 2:
                continue
            reasons = []
            # 1) 已有 colspan/rowspan
            nrs = sum(1 for r in rows for d, _ in r
                       if "rowspan" in d and int(d["rowspan"]) > 1)
            ncs = sum(1 for r in rows for d, _ in r
                       if "colspan" in d and int(d["colspan"]) > 1)
            # 2) 首列为空的续行
            cont = 0
            for i in range(1, len(rows)):
                if rows[i] and not rows[i][0][1] and rows[i - 1] and rows[i - 1][0][1]:
                    cont += 1
            # 3) 宽表
            w = max(len(r) for r in rows)
            # 4) 重复列名
            hdr = [v for d, v in rows[0]]
            dup = max((hdr.count(x) for x in set(hdr) if x), default=0)
            score = nrs * 3 + ncs * 2 + cont * 2 + (2 if w >= 8 else 0) + (2 if dup >= 3 else 0)
            if cont or ncs or dup >= 3:
                reasons.append(f"续行{cont}/cs{ncs}/rs{nrs}/宽{w}/重名{dup}")
            if score >= 4:
                picks.append((score, f[:-3],
                              os.path.relpath(p, base).replace(os.sep, "/"),
                              mi, len(rows), w, nrs, ncs, cont, dup,
                              "; ".join(reasons)))

picks.sort(reverse=True)
print(f"建议 VLM 重读的表: {len(picks)}")
stems = []
for x in picks:
    print(f"  {x[1]:<8} 分{x[0]:<4} 行{x[4]:<3} 宽{x[5]:<3} rs{x[6]:<3} cs{x[7]:<3} 续{x[8]:<3} {x[9]}")
    stems.append(x[1])
with open(r"E:/workspace/siliao/_vlm_pick.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(sorted(set(stems))))
print()
print("stem 列表已写 _vlm_pick.txt")
