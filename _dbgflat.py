import re

s = '|序号|申请材料|不需评审产品|需评审产品| |---|---|---|---| |1 |目录|✓|✓| |2 |登记表|✓|✓|'
print("len", len(s))
# 手工标注每个 "| " 的位置
for m in re.finditer(r"\| ", s):
    i = m.start()
    j = i + 2
    while j < len(s) and s[j] == " ":
        j += 1
    nxt = s[j] if j < len(s) else "<END>"
    print(f"  | at {i:3d} 后面跳过空格 -> {nxt!r}  边界={nxt != '|'}")
