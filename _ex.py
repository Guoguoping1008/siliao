
import os
base = r"E:/workspace/siliao/minimax"
# 看几个"首列合并"和"两级表头"的真实例子
targets = {
 "0313": "3列表, 续行首格空",
 "0108": "两级表头",
 "0094": "两级表头 14列",
 "0053": "2列表单 + 嵌套",
}
for stem, desc in targets.items():
    for dp,dns,fns in os.walk(base):
        if stem + ".md" in fns:
            p = os.path.join(dp, stem+".md")
            print(f"=== {stem} ({desc}) ===")
            lines = open(p, encoding="utf-8").read().splitlines()
            n = 0
            for l in lines:
                if l.strip().startswith("|"):
                    print(f"  [{len(l.strip().strip('|').split('|'))}] {l[:100]}")
                    n += 1
                    if n >= 7: break
            print()
