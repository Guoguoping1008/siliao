
import os, re, collections
base = r"E:/workspace/siliao/minimax"
for scope in sorted(os.listdir(base)):
    d = os.path.join(base, scope)
    if not os.path.isdir(d): continue
    if not any(scope.startswith(s) for s in ["01","02","03","04"]): continue
    print(f"\n{scope}/")
    for dp, dns, fns in os.walk(d):
        rel = os.path.relpath(dp, d)
        if rel == ".": continue
        depth = rel.count(os.sep)+1
        n = len([f for f in fns if f.endswith(".md")])
        if depth <= 2:
            print("  " + "  "*(depth-1) + f"{os.path.basename(dp)}/  ({n} md)")
