import os
import sys

sys.path.insert(0, r"E:/workspace/siliao")
exec(open(r"E:/workspace/siliao/mm_flat_table.py", encoding="utf-8").read())

base = r"E:/workspace/siliao/minimax"
targets = ["0217", "0251", "0629", "0712", "0717", "0964", "0325", "0096"]
for stem in targets:
    for dp, dns, fns in os.walk(base):
        if stem + ".md" in fns:
            p = os.path.join(dp, stem + ".md")
            t = open(p, encoding="utf-8").read()
            lines = [l for l in t.splitlines() if l.strip().startswith("|")]
            print(f"=== {stem} ===")
            if not lines:
                print("   (无管道行)")
                continue
            rows = split_flat_table(lines[0]) if len(lines) == 1 else None
            if rows is None:
                print(f"   split 返回 None (行数={len(lines)})")
            else:
                print(f"   切出 {len(rows)} 行, 列数分布: "
                      f"{sorted(set(len(r) for r in rows))}")
                for r in rows[:4]:
                    print(f"      {[c[:22] for c in r]}")
                # looks_like_table 判定
                cells = [c for r in rows for c in r if c]
                multi = sum(1 for c in cells if len(c) >= 2)
                print(f"   非空格 {len(cells)}, 多字格 {multi} "
                      f"({multi}/{len(cells)})")
            print()
            break
