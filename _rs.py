
import os, re
base = r"E:/workspace/siliao/minimax"
# 找 rowspan 最大的
worst=[]
for dp,dns,fns in os.walk(base):
    for f in fns:
        if not f.endswith(".md"): continue
        p=os.path.join(dp,f)
        t=open(p,encoding="utf-8").read()
        for m in re.finditer(r'rowspan="(\d+)"', t):
            worst.append((int(m.group(1)), os.path.relpath(p,base)))
worst.sort(reverse=True)
print("最大的 rowspan:", worst[:6])
print("总 rowspan 处:", len(worst))
