
import os
base = r"E:/workspace/siliao/minimax"
for stem in ("0217","0061","0251","0325"):
    for dp,dns,fns in os.walk(base):
        if stem + ".md" in fns:
            t=open(os.path.join(dp,stem+".md"),encoding="utf-8").read()
            print(f"=== {stem} (len={len(t)}) ===")
            print(t[:900])
            print()
