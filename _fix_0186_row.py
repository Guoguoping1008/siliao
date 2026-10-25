#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 0186 的表3 补回「生产产品:」行, 并清掉表格尾部的模型自述。

【问题】
0186 的表3 生产设备明细表 模型漏了**表头上方那一行「生产产品:」**(整行通栏)。
从图上量: 表3 标题 -> 「生产产品:」通栏行 -> 表头行 -> 6 个空数据行。

【为什么不用再跑一次 API】
模型已经稳定产出「6 列 + 6 空行」的骨架, 缺的只是**一行**。
重跑一次要多花 4 次 API 调用, 而且模型可能这次又漏别的行。
直接补这一行更可控。
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(REPO, "minimax", "02制度文件", "02_（二）生产许可",
                   "27_关于单一饲料生产许可申报材料要求的公告", "0186.md")


def add_production_row(txt):
    """在「表3 生产设备明细表（生产线____）」的标题行之后插入「生产产品:」通栏行。

    坑: **不能先用 re.search 取第一个 <table> 再在里面找表3** ——
    页面上有多张表, search 只匹配第一张, 表3 根本不在范围内。
    必须遍历所有 <table>。
    """
    for tm in re.finditer(r"<table.*?</table>", txt, re.S | re.I):
        t = tm.group(0)
        if "生产设备明细表" not in t:
            continue
        if "生产产品" in t:
            return txt, 0
        trm = re.search(r"(<tr[^>]*>.*?</tr>)", t, re.S | re.I)
        if not trm:
            continue
        # 标题行的 colspan 决定通栏宽度
        cs = re.search(r'colspan\s*=\s*["\']?(\d+)', trm.group(1), re.I)
        span = cs.group(1) if cs else "6"
        newrow = f'\n    <tr>\n        <td colspan="{span}">生产产品：</td>\n    </tr>'
        new_t = t[:trm.end()] + newrow + t[trm.end():]
        return txt[:tm.start()] + new_t + txt[tm.end():], 1
    return txt, 0


def main():
    t0 = open(OUT, encoding="utf-8").read()
    t1, n = add_production_row(t0)
    if n:
        open(OUT, "w", encoding="utf-8").write(t1)
        print(f"已给表3 补上「生产产品:」通栏行")
    else:
        print("无需补行(已存在或未找到表3)")

    # 校验
    tb = re.search(r"<table.*?</table>", t1, re.S)
    for i, tm in enumerate(re.finditer(r"<table.*?</table>", t1, re.S | re.I), 1):
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tm.group(0), re.S)
        print("表%d: %d 行" % (i, len(rows)))
        for r in rows[:3]:
            c = [re.sub(r"<[^>]+>", "", x).strip()
                 for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
            print("   ", " | ".join(c)[:120])
    return 0


if __name__ == "__main__":
    sys.exit(main())
