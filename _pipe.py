
import os, re
base = r"E:/workspace/siliao/minimax"
print("=== 残留管道行的页 ===")
for dp,dns,fns in os.walk(base):
    for f in sorted(fns):
        if not f.endswith(".md"): continue
        p=os.path.join(dp,f)
        t=open(p,encoding="utf-8").read()
        pr=[l for l in t.splitlines() if l.strip().startswith("|")]
        if pr:
            print(f"  {os.path.relpath(p,base)}  ({len(pr)} 行)")
            for l in pr[:3]: print(f"      {l[:120]!r}")
