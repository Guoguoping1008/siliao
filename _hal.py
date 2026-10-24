
import os, re
# 统计: 只有表头没有数据行, 且列数很多的表 -> 幻觉
base = r"E:/workspace/siliao/minimax"
for dp,dns,fns in os.walk(base):
    for f in sorted(fns):
        if not f.endswith(".md"): continue
        p=os.path.join(dp,f)
        t=open(p,encoding="utf-8").read()
        for m in re.finditer(r"<table\b.*?</table>", t, re.S|re.I):
            rows=re.findall(r"<tr\b.*?</tr>", m.group(0), re.S|re.I)
            ncells=len(re.findall(r"<t[dh]\b", m.group(0)))
            if len(rows) <= 2 and ncells > 30:
                print(f"  {os.path.relpath(p,base)}: {len(rows)} 行, {ncells} 格")
