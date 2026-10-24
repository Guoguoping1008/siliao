
import os, re, subprocess
repo = r"E:/workspace/siliao"
# git HEAD (我的最后一个 commit) 里的结构
out = subprocess.run(["git","-C",repo,"-c","core.quotepath=false","ls-tree","-r","--name-only","-z","HEAD","minimax"],
                     capture_output=True).stdout.decode("utf-8","ignore")
paths = [p for p in out.split("\0") if p]
dirs = set()
for p in paths:
    parts = p.split("/")
    for i in range(2, len(parts)):
        dirs.add("/".join(parts[:i+1]))
from collections import Counter
c = Counter()
for d in dirs:
    c[len(d.split("/"))-2] += 1
print("git HEAD 里 minimax 的目录深度分布:", dict(sorted(c.items())))
print()
print("HEAD 里 02制度文件 的顶层子目录:")
for d in sorted(dirs):
    if d.startswith("minimax/02") and len(d.split("/"))==3:
        print("   ", d.split("/")[-1])
