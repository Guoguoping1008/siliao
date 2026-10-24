"""0044/0045: 修正"表2 不同气候带的温湿度"。

问题(原 md):
- 0044 的表头是 5 列(气候带|温度℃|MKT℃|湿度|推算数据), 数据行却有 6 格
  -> 列错位; 且"推算数据"下面的"温度|湿度"被塞进了 Ⅰ温带 行
- 续表(0045)用了**另一套表头**(气候带|温度①|MKT②|湿度|温度|湿度),
  跟首页表头对不上
- 脚注"①记录温度；②平均热力学温度"在 0045

真表结构(看图确认):
  表2  不同气候带的温湿度
  两级合并表头:
    气候带 | 计算数据(跨3列) | 推算数据(跨2列)
           | 温度① | MKT② | 湿度 | 温度 | 湿度
  数据:
    Ⅰ温带              | 20.0 | 20.0 | 42 | (空) | (空)
    Ⅱ地中海气候，亚热带 | 21.6 | 22.0 | 52 | 21    | 45
                          |      |      |    | 25    | 60
    Ⅲ干热带            | 26.4 | 27.9 | 35 | 30    | 25
    Ⅳ湿热带            | 26.7 | 27.4 | 76 | 30    | 70

Markdown 表达不了合并单元格 -> 两级表头**逐列拼接**成一行:
  气候带 | 计算数据/温度① | 计算数据/MKT② | 计算数据/湿度 | 推算数据/温度 | 推算数据/湿度

坑(来自 skill scanned-table-ocr-md):
- 拼接时列数基准取**数据行的众数列数**, 不是表头的
- 跨页续表的表头要**和首页一致**, 不能各写各的
"""

import os
import sys

MM_ROOT = r"E:/workspace/siliao/minimax"
tgt = [x for x in os.listdir(MINIMAX) if False] if False else None

HEADER = ("| 气候带 | 计算数据/温度① | 计算数据/MKT② | 计算数据/湿度 "
          "| 推算数据/温度 | 推算数据/湿度 |")
SEP = "|---|---|---|---|---|---|"

# 0044 上的表2(第 I、II 气候带部分)
TABLE_0044 = "\n".join([
    "表2　不同气候带的温湿度",
    "",
    HEADER,
    SEP,
    "| Ⅰ温带 | 20.0 | 20.0 | 42 |  |  |",
    "| Ⅱ地中海气候，亚热带 | 21.6 | 22.0 | 52 | 21 | 45 |",
    "|  |  |  |  | 25 | 60 |",
])

# 0045 上的续表(III、IV 气候带部分)
# 脚注"①记录温度；②平均热力学温度"原 md 里**已经有了**, 这里不再重复输出。
TABLE_0045 = "\n".join([
    "（续表）",
    "",
    HEADER,
    SEP,
    "| Ⅲ干热带 | 26.4 | 27.9 | 35 | 30 | 25 |",
    "| Ⅳ湿热带 | 26.7 | 27.4 | 76 | 30 | 70 |",
])


def find(stem):
    best, best_depth = None, -1
    for dp, dns, fns in os.walk(MM_ROOT):
        for f in fns:
            if f == stem + ".md":
                d = dp.count(os.sep)
                if d > best_depth:
                    best_depth, best = d, os.path.join(dp, f)
    return best


def replace_table(path, new_block, marker):
    """把 md 里从 marker 开始的旧表格块换成新块。

    marker = 旧表格块的起始标志(表头行第一格的前几个字)
    """
    text = open(path, encoding="utf-8").read()
    lines = text.splitlines()
    out = []
    i = 0
    replaced = False
    while i < len(lines):
        ln = lines[i]
        if (not replaced and ln.strip().startswith("|")
                and marker in ln):
            # 跳过旧表格块: 连续的 | 开头行
            out.extend(new_block.splitlines())
            replaced = True
            while i < len(lines) and lines[i].strip().startswith("|"):
                i += 1
            # 跳过旧块后面紧跟的空行(避免出现两段空白)
            while i < len(lines) and not lines[i].strip():
                i += 1
            continue
        out.append(ln)
        i += 1
    if not replaced:
        print("  警告: 没找到旧表格块, marker =", marker)
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out).rstrip() + "\n")
    return True


p44 = find("0044")
p45 = find("0045")
print("0044:", p44)
print("0045:", p45)

if p44 and replace_table(p44, TABLE_0044, "气候带"):
    print("  0044 已更新")
if p45 and replace_table(p45, TABLE_0045, "气候带"):
    print("  0045 已更新")
