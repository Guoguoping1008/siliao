#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0777 —— 页面是**纯正文**(兽药管理条例 末页), 原 md **漏了第73/74条标题**。

【页面映射(先读页码确认)】
Images/03相关法规法律法规文件/0777.jpg = 书第 776(左) + 777(右)
  页眉右上角印着「三、相关法律法规文件 | 777」-> 确认 0777 = **页777** = 右半
  书脊 x≈2100, 右页内容从 x≈2100 开始 -> cut=2080

【原状态(378B)】
  只有三段正文, **第七十三条 / 第七十四条 / 第七十五条 的条标题全丢了**,
  而且**页首第七十二条的尾巴**「明文件、新兽药注册证书等文件。」也没了。

【修后】0 个表, 4 段:
  页首续句 + ### 第七十三条 + ### 第七十四条 + ### 第七十五条
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(REPO, "minimax", "03相关法律法规文件", "04_（四）兽药管理",
                   "04_兽药管理条例", "0777.md")

HEAD = "明文件、新兽药注册证书等文件。"

T73 = (
    "第七十三条　兽用麻醉药品、精神药品、毒性药品和放射性药品等特殊药品，"
    "依照国家有关规定管理。"
)

T74 = (
    "第七十四条　水产养殖中的兽药使用、兽药残留检测和监督管理以及水产养殖过程中"
    "违法用药的行政处罚，由县级以上人民政府渔业主管部门及其所属的渔政监督管理机构"
    "负责。"
)

T75 = "第七十五条　本条例自2004年11月1日起施行。"

MUST = [
    "明文件、新兽药注册证书等文件。",
    "第七十三条",
    "兽用麻醉药品、精神药品、毒性药品和放射性药品等特殊药品，依照国家有关规定管理。",
    "第七十四条",
    "水产养殖中的兽药使用、兽药残留检测和监督管理以及水产养殖过程中违法用药的行政处罚",
    "县级以上人民政府渔业主管部门及其所属的渔政监督管理机构负责",
    "第七十五条",
    "本条例自2004年11月1日起施行。",
]

MUST_NOT = [
    "<table",
    "第七章",
    "第七十二条",
    "第七十六条",
    "第五条",
]


def build():
    return "\n".join([
        HEAD,
        "",
        "### " + T73,
        "",
        "### " + T74,
        "",
        "### " + T75,
        "",
    ])


def check(txt):
    errs = []
    for k in MUST:
        if k not in txt:
            errs.append("缺: " + k)
    for k in MUST_NOT:
        if k in txt:
            errs.append("不应出现: " + k)
    for t in ("第七十三条", "第七十四条", "第七十五条"):
        if not re.search(r"\n### " + t + r"[　 ]", txt):
            errs.append("条标题未独立成行: " + t)
    return errs


def main():
    txt = build()
    errs = check(txt)
    if errs:
        print("!! 质量门未过:")
        for e in errs:
            print("   -", e)
        return 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(txt)
    print("OK 0777 -> %s (%d 字节, 0 表, 3 个条 + 页首续句)" %
          (os.path.relpath(OUT, REPO), len(txt.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
