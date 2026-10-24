
import os, re
base = r"E:/workspace/siliao/minimax"
for stem in ("0052","0152","0077"):
    for dp,dns,fns in os.walk(base):
        if stem + ".md" in fns:
            t=open(os.path.join(dp,stem+".md"),encoding="utf-8").read()
            m=re.search(r"<table\b.*?</table>", t, re.S|re.I)
            if not m: continue
            rows=re.findall(r"<tr\b[^>]*>(.*?)</tr>", m.group(0), re.S|re.I)
            print(f"=== {stem}: {len(rows)} 行")
            for i,rm in enumerate(rows[:8]):
                cells=re.findall(r"<t[dh]\b([^>]*)>(.*?)</t[dh]>", rm, re.S|re.I)
                vals=[re.sub(r"<[^>]+>","",c[1]).strip()[:14] for c in cells]
                print(f"   {i}: {vals}")
            print()
