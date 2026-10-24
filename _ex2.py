
import os
base = r"E:/workspace/siliao/minimax"
for stem in ("0313","0308","0309"):
    for dp,dns,fns in os.walk(base):
        if stem + ".md" in fns:
            p = os.path.join(dp, stem+".md")
            print(f"=== {stem} ===")
            for l in open(p, encoding="utf-8").read().splitlines():
                if l.strip().startswith("|"):
                    c = l.strip().strip("|").split("|")
                    print(f"  [{len(c)}] first={c[0].strip()[:26]!r:30s} second={c[1].strip()[:26]!r}")
            print()
