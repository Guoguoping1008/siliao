
import os, sys
sys.path.insert(0, r"E:/workspace/siliao")
sys.argv=["x"]
exec(open(r"E:/workspace/siliao/mm_reorg.py", encoding="utf-8").read().split("def main()")[0])
docs = build_docs(parse_toc(TOC))
allp = {p for _l,_t,p,_d,_c,_s in docs if p}
# 找 四、标准及标准目录 下的条目
print("四、标准 下的条目:")
for lv,t,p,dn,c,s in docs:
    if c.startswith("四、"):
        print(f"   L{lv} p={p} 节={s!r:14s} {t[:50]}")
