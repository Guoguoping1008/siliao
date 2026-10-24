
import os, re
base = r"E:/workspace/siliao/minimax"
for dp,dns,fns in os.walk(base):
    if "0094.md" in fns:
        t=open(os.path.join(dp,"0094.md"),encoding="utf-8").read()
        m=re.search(r"<table\b.*?</table>", t, re.S|re.I)
        print("=== 当前 0094 的表 ===")
        print(m.group(0)[:1500] if m else "(无)")
        break
