
import os, re, subprocess
# 看 0094 之后的页有没有被改(0094 我已经手动 apply 过)
base = r"E:/workspace/siliao/minimax"
# 按 _vlm_pick.txt 顺序
stems = [l.strip() for l in open(r"E:/workspace/siliao/_vlm_pick.txt", encoding="utf-8") if l.strip()]
print("前 10:", stems[:10])
print()
# 检查这些页的表格是否有 rowspan/colspan
for stem in stems[:10]:
    found = False
    for dp, dns, fns in os.walk(base):
        if stem + ".md" in fns:
            t = open(os.path.join(dp, stem + ".md"), encoding="utf-8").read()
            nrs = len(re.findall(r'rowspan="[2-9]', t))
            ncs = len(re.findall(r'colspan="[2-9]', t))
            print(f"  {stem}: rs={nrs} cs={ncs}")
            found = True
            break
