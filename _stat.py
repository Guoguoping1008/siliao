
import os, re, collections
base = r"E:/workspace/siliao/minimax"
TBL=re.compile(r"<table\b.*?</table>", re.S|re.I)
ROW=re.compile(r"<tr\b.*?</tr>", re.S|re.I)
CELL=re.compile(r"<t[dh]\b([^>]*)>(.*?)</t[dh]>", re.S|re.I)
nt=0; rs=0; cs=0; bg=0; pipe=0; pages=0
rsizes=collections.Counter()
for dp,dns,fns in os.walk(base):
    for f in fns:
        if not f.endswith(".md"): continue
        p=os.path.join(dp,f)
        t=open(p,encoding="utf-8").read()
        if TBL.search(t): pages+=1
        for m in TBL.finditer(t):
            nt+=1
            for c in CELL.finditer(m.group(0)):
                d=dict(re.findall(r'(\w+)="([^"]*)"', c.group(1)))
                if "rowspan" in d and int(d["rowspan"])>1: rs+=1; rsizes[int(d["rowspan"])]+=1
                if "colspan" in d and int(d["colspan"])>1: cs+=1
                if "bgcolor" in d: bg+=1
        pipe += sum(1 for l in t.splitlines() if l.strip().startswith("|"))
print(f"含 html 表的页: {pages}   html 表: {nt}")
print(f"rowspan>1: {rs}  (分布: {dict(sorted(rsizes.items())[:12])})")
print(f"colspan>1: {cs}")
print(f"带 bgcolor 的单元格: {bg}")
print(f"残留管道行: {pipe}")
