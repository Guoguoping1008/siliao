
import os, re
base = r"E:/workspace/siliao/minimax"
for dp,dns,fns in os.walk(base):
    if "0035.md" in fns:
        t=open(os.path.join(dp,"0035.md"),encoding="utf-8").read()
        i=t.find("&lt;br")
        print("0035 转义后:", repr(t[max(0,i-120):i+120]) if i>0 else "没找到 &lt;br")
        break
print()
# 漏转的页: 看看它们的管道表长什么样
for dp,dns,fns in os.walk(base):
    if "0061.md" in fns:
        t=open(os.path.join(dp,"0061.md"),encoding="utf-8").read()
        for i,l in enumerate(t.splitlines()):
            if l.strip().startswith("|"):
                print(f"  {i:3d} {l[:110]!r}")
        break
