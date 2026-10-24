
import os, subprocess
repo = r"E:/workspace/siliao"
base = os.path.join(repo, "minimax")
out = subprocess.run(["git","-C",repo,"-c","core.quotepath=false","ls-tree","-r","--name-only","-z","HEAD","minimax"],
                     capture_output=True).stdout.decode("utf-8","ignore")
for p in out.split("\0"):
    if p and ("散装散运" in p or "白名单" in p):
        print("  HEAD:", p[len("minimax/"):])
print()
for dp, dns, fns in os.walk(base):
    for d in dns:
        if "散装散运" in d or "白名单" in d:
            print("  磁盘:", os.path.relpath(os.path.join(dp,d), base))
