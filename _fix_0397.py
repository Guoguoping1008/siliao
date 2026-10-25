#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0397 —— 宠物配合饲料生产许可证申报材料一览表(带 ✓ 勾选)。

【页面映射】
Images/02制度文件/0397.jpg = 书第 396(左) + 397(右)
  书脊实测 **x≈2020**(放大截图看折痕阴影确认)

【原状态】
0397.md 10007B —— 表头**从中间开始**(少了 序号/申报材料项目 两列, 也没有
  标题行), 且 ✓ 的位置多处错位。

【真值: 目视逐格核对(整表放大到 1.55 倍后一次读完)】
  标题: 宠物配合饲料生产许可证申报材料一览表
  11 列: 序号 | 申报材料项目 | 设立 | 续展 | 增加或更换生产线 | 增加产品品种
         | 迁址 | 变更企业名称 | 变更企业法定代表人
         | 变更企业注册地址或注册地名称 | 变更企业生产地址名称
  14 个数据行 + 表下 3 条注
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(REPO, "minimax", "02制度文件", "05_（五）宠物饲料管理",
                      "57_关于宠物饲料管理的公告")

TITLE = "宠物配合饲料生产许可证申报材料一览表"

HEAD = ["序号", "申报材料项目", "设立", "续展", "增加或更换生产线", "增加产品品种",
        "迁址", "变更企业名称", "变更企业法定代表人",
        "变更企业注册地址或注册地名称", "变更企业生产地址名称"]

# (序号, 申报材料项目, 有✓的列号集合) —— 列号 1..9 对应 HEAD[2:]
ROWS = [
    (1, "企业承诺书", [1, 2, 3, 4, 5]),
    (2, "宠物配合饲料生产许可申请书", [1, 2, 3, 4, 5]),
    (3, "工商营业执照", [1, 2, 5, 6, 7, 8, 9]),
    (4, "企业组织机构图", [1, 2, 5]),
    (5, "主要机构负责人毕业证书或职称证书", [1, 2, 5]),
    (6, "厂区平面布置图", [1, 2, 3, 4, 5]),
    (7, "生产工艺流程图和工艺说明", [1, 2, 3, 4, 5]),
    (8, "计算机自动化控制系统配料精度证明", [1, 2, 3, 4, 5]),
    (9, "混合机混合均匀度检测报告", [1, 2, 3, 4, 5]),
    (10, "检验化验室平面布置图", [1, 2, 5]),
    (11, "检验仪器购置发票", [1, 2, 5]),
    (12, "企业管理制度", [1, 2, 5]),
    (13, "企业生产许可证", [2, 3, 4, 5, 6, 7, 8, 9]),
    (14, "相关证明材料", [6, 7, 8, 9]),
]

NOTES = [
    "1.增加或者更换生产线、增加产品品种的，仅提供与申请事项相关的材料。",
    "2.表中序号8，仅适用于配料、混合工段采用计算机自动化控制系统的企业。",
    "3.表中序号9，不适用于液态宠物配合饲料生产企业。",
]


def build():
    out = [
        "<!-- source: Images/02制度文件/0397.jpg (split: 0397, 右半, cut=2020) -->",
        "<!-- repaired: rotated=no, method=api-minimax, form=table, ticks -->",
        "",
        "**%s**" % TITLE,
        "",
        "<table border=\"1\">",
    ]
    hdr = "".join("<th>%s</th>" % h for h in HEAD)
    out.append("  <tr>\n    %s\n  </tr>" % hdr)
    for no, item, marks in ROWS:
        cells = ["<td>%d</td>" % no, "<td>%s</td>" % item]
        for c in range(1, 10):
            cells.append("<td>✓</td>" if c in marks else "<td></td>")
        out.append("  <tr>\n    %s\n  </tr>" % "\n    ".join(cells))
    out.append("</table>")
    out.append("")
    out.append("注：")
    for n in NOTES:
        out.append(n)
        out.append("")
    return "\n".join(out)


def check(txt):
    errs = []
    m = re.search(r"<table.*?</table>", txt, re.S)
    if not m:
        return ["无表格"]
    tb = m.group(0)
    raws = re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S)
    if len(raws) != 15:
        errs.append("行数 %d != 15" % len(raws))
    for j, r in enumerate(raws):
        n = len(re.findall(r"<t[dh][^>]*>", r, re.I))
        if n != 11:
            errs.append("第%d行 %d格(应11)" % (j + 1, n))
    for h in HEAD:
        if h not in tb:
            errs.append("缺表头:" + h)
    # ✓ 位置逐行核对
    for i, (no, item, marks) in enumerate(ROWS):
        r = raws[i + 1]
        cells = re.findall(r"<td[^>]*>(.*?)</td>", r, re.S | re.I)
        if len(cells) != 11:
            continue
        got = [k for k in range(1, 10) if "✓" in cells[k + 1]]
        if got != marks:
            errs.append("序号%d ✓位置 %s != %s" % (no, got, marks))
    for k in NOTES:
        if k not in txt:
            errs.append("缺注:" + k[:12])
    if TITLE not in txt:
        errs.append("缺标题")
    return errs


def main():
    txt = build()
    errs = check(txt)
    out = os.path.join(OUTDIR, "0397.md")
    if errs:
        print("!! 质量门未过: %s" % "; ".join(errs[:8]))
        return 1
    open(out, "w", encoding="utf-8").write(txt)
    print("OK 0397 -> %s (%d 字节, %d 行, %d 注)" %
          (os.path.relpath(out, REPO), len(txt.encode("utf-8")),
           len(ROWS), len(NOTES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
