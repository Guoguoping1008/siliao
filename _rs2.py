
import os, re
base = r"E:/workspace/siliao/minimax"
for dp,dns,fns in os.walk(base):
    if "0061.md" in fns:
        t=open(os.path.join(dp,"0061.md"),encoding="utf-8").read()
        i=t.find("<table")
        print("前 900 字符:")
        print(t[i:i+900])
        break
