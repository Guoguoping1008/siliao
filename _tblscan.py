
import os, re, collections
base = r"E:/workspace/siliao/minimax"
def is_sep(l):
    cells=[x.strip() for x in l.strip().strip("|").split("|")]
    return bool(cells) and all(x and set(x)<=set("-:") for x in cells)
def ncols(l): return len(l.strip().strip("|").split("|"))
def blocks_of(lines):
    out,cur=[],[]
    for l in lines:
        if l.strip().startswith("|"): cur.append(l)
        else:
            if cur: out.append(cur); cur=[]
    if cur: out.append(cur)
    return out
def split_blocks(b):
    tabs,cur,i=[],[],0
    while i<len(b):
        if i+1<len(b) and not is_sep(b[i]) and is_sep(b[i+1]) and ncols(b[i])==ncols(b[i+1]):
            if cur: tabs.append(cur); cur=[]
        cur.append(b[i]); i+=1
    if cur: tabs.append(cur)
    return tabs

rows=[]
for dp,dns,fns in os.walk(base):
    for f in sorted(fns):
        if not f.endswith(".md"): continue
        p=os.path.join(dp,f)
        lines=open(p,encoding="utf-8").read().splitlines()
        for b in blocks_of(lines):
            for t in split_blocks(b):
                if len(t)<2: continue
                sep=None
                for i,l in enumerate(t):
                    if is_sep(l): sep=i; break
                hdr = t[0] if sep is not None else t[0]
                dat = t[sep+1:] if sep is not None else t[1:]
                w = max(ncols(l) for l in dat) if dat else ncols(hdr)
                rows.append({
                    "path": os.path.relpath(p, base),
                    "stem": f[:-3],
                    "rows": len(dat), "cols": w,
                    "hdr": " | ".join(x.strip() for x in hdr.strip().strip("|").split("|"))[:70],
                })
print(f"含表格的页: {len(set(r['stem'] for r in rows))}   表格块: {len(rows)}")
print()
# 按 scope 统计
c=collections.Counter(r["path"].split(os.sep)[0] for r in rows)
print("按 scope:", dict(c))
print()
import json
open("E:/workspace/siliao/_tbl_list.json","w",encoding="utf-8").write(json.dumps(rows, ensure_ascii=False, indent=1))
for r in rows[:12]:
    print(f"  {r['stem']}  {r['rows']}行 x {r['cols']}列   {r['hdr']}")
