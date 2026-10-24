
import os
base = r"E:/workspace/siliao/minimax"
for stem in ("0035","0061","0217"):
    for dp,dns,fns in os.walk(base):
        if stem + ".md" in fns:
            t=open(os.path.join(dp,stem+".md"),encoding="utf-8").read()
            print(f"=== {stem} ===")
            n=0
            for l in t.splitlines():
                if l.strip().startswith("|"):
                    print(f"  {l[:130]!r}")
                    n+=1
                    if n>=5: break
            print()
