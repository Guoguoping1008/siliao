
import os, re, collections
base = r"E:/workspace/siliao/minimax"
# 找出 HTML 表里, 数据行里存在"空单元格"的表 -> 可能是该加 rowspan 却没加的
ROW=re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S|re.I)
CELL=re.compile(r"<t[dh]\b([^>]*)>(.*?)</t[dh]>", re.S|re.I)
cand=[]
for dp,dns,fns in os.walk(base):
    for f in sorted(fns):
        if not f.endswith(".md"): continue
        p=os.path.join(dp,f)
        t=open(p,encoding="utf-8").read()
        for m in re.finditer(r"<table\b.*?</table>", t, re.S|re.I):
            rows=[]
            for rm in ROW.finditer(m.group(0)):
                cells=[]
                for cm in CELL.finditer(rm.group(1)):
                    d=dict(re.findall(r'(\w+)="([^"]*)"', cm.group(1)))
                    cells.append((d, re.sub(r"<[^>]+>","",cm.group(2)).strip()))
                rows.append(cells)
            if len(rows)<3: continue
            # 统计"数据行里第1列之后有空单元格"的行数
            empt=0
            for r in rows[1:]:
                for d,txt in r[1:]:
                    if not txt and "rowspan" not in d: empt+=1
            if empt>=2:
                cand.append((os.path.relpath(p,base), len(rows), empt))
cand.sort(key=lambda x:-x[2])
print(f"数据行里有空单元格(可能缺 rowspan)的表: {len(cand)}")
for x in cand[:15]: print("   ", x)
