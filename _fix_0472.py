#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0472 (农业综合行政执法事项指导目录 2020年版)。

【页面映射(先读页码确认)】
Images/02制度文件/0471.jpg = 书第 470(左) + 471(右)
Images/02制度文件/0473.jpg = 书第 472(左) + 473(右)
  -> 0472 = **页472** = 0473.jpg 的左半
  书脊折痕 x≈2270, 页472 表格右边界 x≈2200 -> cut=2210

【原状态】
0472.md 1825B —— 整页塌成一个**扁平的管道串**:
  序号|事项名称|职权类型|实施依据|实施主体---|---|---|---|---62 |对养殖者...
  表头后面直接接 `---|---|---|---|---`, 表格结构完全丢失。

【页472 的真值(目视逐行核对)】
表格是 (续表), 6 列(实施主体 跨 2 个子列):
  序号 | 事项名称 | 职权类型 | 实施依据 | 实施主体(法定实施主体 | 第一责任层级建议)
共 3 行: 62 / 63 / 241
表格下面是正文:
  《农业综合行政执法事项指导目录（2020年版）》说明
  一、关于主要内容。…  二、关于梳理范围。…  三、关于事项的确定。…
  (页尾停在「四是同一法律行政法规条款同时包含行政」, 接页473)
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(REPO, "minimax", "02制度文件", "06_（六）监督执法",
                      "66_农业农村部关于印发《农业综合行政执法事项指导目录（2020年版）》的通知")

CUT = 2210

# 表格: (序号, 事项名称, 职权类型, 实施依据, 法定实施主体, 第一责任层级建议)
ROWS = [
    (
        "62",
        "对养殖者在饲料或者动物饮用水中添加国务院农业行政主管部门公布禁用的物质"
        "以及对人体具有直接或者潜在危害的其他物质，或者直接使用上述物质养殖动物的行政处罚",
        "行政处罚",
        "《饲料和饲料添加剂管理条例》\n"
        "第四十七条第二款：在饲料或者动物饮用水中添加国务院农业行政主管部门公布禁用的物质"
        "以及对人体具有直接或者潜在危害的其他物质，或者直接使用上述物质养殖动物的，由"
        "县级以上地方人民政府饲料管理部门责令其改正，没收违禁物品和违法所得，可以处"
        "3万元以上10万元以下罚款；构成犯罪的，依法追究刑事责任。",
        "农业农村主管部门",
        "设区的市或县级",
    ),
    (
        "63",
        "对养殖者对外提供自行配制的饲料的行政处罚",
        "行政处罚",
        "《饲料和饲料添加剂管理条例》\n"
        "第四十八条：养殖者对外提供自行配制的饲料的，由县级人民政府饲料管理部门责令改正，"
        "处2千元以上2万元以下罚款。",
        "农业农村主管部门",
        "县级",
    ),
    (
        "241",
        "对有证据证明用于违法生产饲料的饲料原料、单一饲料、饲料添加剂、药物饲料添加剂、"
        "添加剂预混合饲料、添加剂预混合饲料等的行政强制",
        "行政强制",
        "《饲料和饲料添加剂管理条例》\n"
        "第三十四条第三、四项，国务院农业行政主管部门和县级以上地方人民政府饲料管理部门"
        "在监督检查中可以采取下列措施：（三）查封、扣押有证据证明用于违法生产饲料的饲料原料、"
        "单一饲料、饲料添加剂、药物饲料添加剂、添加剂预混合饲料、添加剂预混合饲料的原料，"
        "用于违法生产饲料、饲料添加剂的饲料、饲料添加剂（四）查封违法生产、经营"
        "饲料、饲料添加剂的场所。",
        "农业农村主管部门",
        "国务院农业行政主管部门或者省设区的市或县级",
    ),
]

PROSE = [
    ("h", "《农业综合行政执法事项指导目录（2020年版）》说明"),
    ("p", "一、关于主要内容。《农业综合行政执法事项指导目录（2020年版）》（以下简称"
          "《指导目录》）主要梳理规范了农业综合行政执法的事项名称、职权类型、实施依据、"
          "实施主体（包括责任部门、第一责任层级建议）。各地可根据法律法规立改废释和地方立法"
          "等情况，进行补充、细化和完善，进一步明确行政执法事项的责任主体，研究细化执法事"
          "项的工作程序、规则、自由裁量标准等，严格规范公正文明执法。"),
    ("p", "二、关于梳理范围。《指导目录》主要梳理的是农业农村领域现行有效的法律、行政"
          "法规设定的行政处罚和行政强制事项，以及部门规章设定的警告、罚没的行政处罚事项。"),
    ("p", "三、关于事项的确定。严格按照法律、法规、规章条款的效力层级和制定部门确定的，"
          "单独作为一个事项列出；一项法律、行政法规规定给予行政处罚的行为、种类和幅度范围"
          "内做出具体规定，在实施依据中列出，不再另外单列事项。四是同一法律行政法规条款同时"
          "包含行政"),
]


def td(v="", attrs="", tag="td"):
    a = (" " + attrs) if attrs else ""
    return "<%s%s>%s</%s>" % (tag, a, v, tag)


def tr(cells):
    return "  <tr>\n    %s\n  </tr>" % "\n    ".join(cells)


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build():
    rows = []
    # 续表的两行表头
    rows.append(tr([td("（续表）", 'colspan="6"', "th")]))
    # 第 1 行: 序号|事项名称|职权类型|实施依据|实施主体(跨 2 子列)
    rows.append(tr([
        td("序号", "th"), td("事项名称", "th"), td("职权类型", "th"),
        td("实施依据", "th"), td("实施主体", 'colspan="2"', "th"),
    ]))
    # 第 2 行: 前 4 列空(被上排表头占), 后 2 列是子表头
    rows.append(tr([
        td("", "th"), td("", "th"), td("", "th"), td("", "th"),
        td("法定实施主体", "th"), td("第一责任层级建议", "th"),
    ]))

    for no, item, typ, basis, legal, level in ROWS:
        basis_html = "<br>".join(esc(x) for x in basis.split("\n"))
        rows.append(tr([
            td(no), td(esc(item)), td(typ), td(basis_html),
            td(legal), td(level),
        ]))

    out = [
        "<!-- source: Images/02制度文件/0473.jpg (split: 0472, 左半, cut=%d) -->" % CUT,
        "<!-- repaired: rotated=no, method=api-minimax, form=table, multi-header -->",
        "",
        "<table border=\"1\">",
    ] + rows + [
        "</table>",
        "",
    ]
    for kind, text in PROSE:
        if kind == "h":
            out.append("## " + text)
        else:
            out.append(text)
        out.append("")
    return "\n".join(out)


def expand_rows(raws):
    grid = {}
    out = []
    for r in raws:
        cells = re.findall(r"<t[dh]([^>]*)>(.*?)</t[dh]>", r, re.S | re.I)
        occupied = {c for c, rem in grid.items() if rem > 0}
        col = 0
        last = -1
        new_grid = {}
        for attrs, _body in cells:
            while col in occupied:
                col += 1
            cs = re.search(r'colspan\s*=\s*["\']?(\d+)', attrs, re.I)
            span = int(cs.group(1)) if cs else 1
            rs = re.search(r'rowspan\s*=\s*["\']?(\d+)', attrs, re.I)
            rspan = int(rs.group(1)) if rs else 1
            for k in range(span):
                if rspan > 1:
                    new_grid[col + k] = rspan - 1
            last = max(last, col + span - 1)
            col += span
        for c, rem in grid.items():
            if rem > 1:
                new_grid[c] = rem - 1
        grid = new_grid
        allcols = set(occupied) | set(range(0, last + 1))
        out.append(((max(allcols) + 1) if allcols else 0, None))
    return out


def check(txt):
    errs = []
    tabs = re.findall(r"<table.*?</table>", txt, re.S)
    if len(tabs) != 1:
        return ["表数 %d != 1" % len(tabs)]
    tb = tabs[0]
    raws = re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S)
    # 3 行表头 + 3 行数据
    if len(raws) != 6:
        errs.append("行数 %d != 6" % len(raws))
    w = [x for x, _ in expand_rows(raws)]
    if set(w) != {6}:
        errs.append("各行列数不统一为6: %s" % sorted(set(w)))
    for h in ("序号", "事项名称", "职权类型", "实施依据", "实施主体",
              "法定实施主体", "第一责任层级建议", "（续表）"):
        if h not in tb:
            errs.append("缺表头:" + h)
    for no, item, typ, basis, legal, level in ROWS:
        if "<td>%s</td>" % no not in tb:
            errs.append("缺序号:" + no)
        if esc(item) not in tb:
            errs.append("缺事项名称:" + no)
        if legal not in tb:
            errs.append("缺法定实施主体:" + legal[:12])
        if level not in tb:
            errs.append("缺第一责任层级建议:" + level[:12])
    # 实施依据 的关键条款
    for k in ("《饲料和饲料添加剂管理条例》",
              "第四十七条第二款", "第四十八条", "第三十四条第三、四项"):
        if k not in tb:
            errs.append("缺实施依据:" + k[:18])
    # 正文
    for k in ("《农业综合行政执法事项指导目录（2020年版）》说明",
              "一、关于主要内容", "二、关于梳理范围", "三、关于事项的确定"):
        if k not in txt:
            errs.append("缺正文:" + k[:16])
    # 不能残留 markdown 管道串
    if "---" in tb:
        errs.append("残留管道分隔符")
    if len(txt.encode("utf-8")) < 2500:
        errs.append("内容过短(%d 字节)" % len(txt.encode("utf-8")))
    return errs


def main():
    txt = build()
    errs = check(txt)
    out = os.path.join(OUTDIR, "0472.md")
    if errs:
        print("!! 质量门未过: %s" % "; ".join(errs[:8]))
        return 1
    open(out, "w", encoding="utf-8").write(txt)
    print("OK 0472 -> %s (%d 字节, %d 行数据)" %
          (os.path.relpath(out, REPO), len(txt.encode("utf-8")), len(ROWS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
