
import os, re, collections
base = r"E:/workspace/siliao/minimax"
print("=== 最终结构 ===")
for scope in sorted(os.listdir(base)):
    d = os.path.join(base, scope)
    if not os.path.isdir(d): continue
    if not any(scope.startswith(s) for s in ["01","02","03","04"]): continue
    nmd = sum(len([f for f in fs if f.endswith(".md")]) for _,_,fs in os.walk(d))
    flat = [f for f in os.listdir(d) if f.endswith(".md")]
    dirs = [os.path.relpath(dp,d) for dp,dns,fs in os.walk(d) if dns]
    dep = collections.Counter(x.count(os.sep)+1 for x in dirs)
    print(f"\n{scope}/   md={nmd}  根下平铺={len(flat)}  目录深度={dict(sorted(dep.items()))}")
    for dp, dns, fns in os.walk(d):
        rel = os.path.relpath(dp, d)
        if rel == ".": continue
        depth = rel.count(os.sep)+1
        n = len([f for f in fns if f.endswith(".md")])
        if depth <= 2:
            print("  " + "  "*(depth-1) + os.path.basename(dp) + f"/  ({n} md)")
