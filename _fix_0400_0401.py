#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0400/0401 (宠物配合饲料生产许可证申请表)。

【页面映射】
Images/02制度文件/0401.jpg = 书第 400(左) + 401(右)
  书脊折痕 x≈2200~2250, 页400 表格右边界 x≈2030
  -> cut=2130(在表格右边之后、折痕之前)

【原状态】
0400.md 370B —— 表格塌成一串标签
0401.md 768B —— 表2 结构不对, 且 source 写的是旧路径 back/Images_split/...

【真值(目视逐行核对)】
页400 表1 企业基本情况 (与页410 同一张表):
  企业名称 | (值通栏)
  生产地址 | (值通栏)
  通讯地址及邮编 | (值通栏)
  法定代表人 | (值通栏)
  统一社会信用代码 | (值) | 法定代表人 | (值)
  住所(注册地址) | (值通栏)
  企业类型 | (值通栏)
  注册资本(万元) | (值) | 固定资产(万元) | (值)
  所属法人机构信息 (rowspan=5, 左侧纵标签)
     名称 | (值通栏)
     住所 | (值通栏)
     统一社会信用代码 | (值) | 法定代表人 | (值)
     企业类型 | (值) | 联系人 | (值)
     联系电话 | (值) | 传真 | (值)
  主要机构设置及人员组成 (rowspan=3, 左侧纵标签)
     机构名称 | (值, 多格)
     人数 | (值, 多格)
     人员总数 | (值) | 其中专业技术人员 | (值)
  企业简介: (整行通栏)

页401:
  表2 基本生产情况 (5 列)
     生产线序号 | 生产线一 | 生产线二 | 生产线三 | 生产线四
     生产线名称 | (4 空)
     生产能力(吨/小时)(立方米)(升) | (4 空)
     产品品种 | 产品系列 (colspan=4)
     + 8 个空数据行
  表3 生产设备明细表 (6 列)
     生产设备名称及序号 (colspan=6)
     序号 | 设备名称 | 型号规格 | 生产厂家 | 出厂日期(年月) | 技术性能指标
     + 9 个空数据行

  行数来自长横线检测:
  表2 横线 y=639/728/818/907/996/1085/1174/1263/1352 -> 4 个空行
  表3 横线 y=1507/1607/1654/1725/1813/1903/1992/2085/2176/2269/2356/2451/2534 -> 9 行
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(REPO, "minimax", "02制度文件", "05_（五）宠物饲料管理",
                      "57_关于宠物饲料管理的公告")

CUT = 2130


def td(v="", attrs="", tag="td"):
    a = (" " + attrs) if attrs else ""
    return "<%s%s>%s</%s>" % (tag, a, v, tag)


def tr(cells):
    return "  <tr>\n    %s\n  </tr>" % "\n    ".join(cells)


def table(rows):
    return ["<table border=\"1\">"] + rows + ["</table>", ""]


def build_400():
    rows = []
    rows.append(tr([td("表1 企业基本情况", 'colspan="5"', "th")]))

    for label in ("企业名称", "生产地址", "通讯地址及邮编", "法定代表人"):
        rows.append(tr([td(label), td("", 'colspan="4"')]))

    rows.append(tr([td("统一社会信用代码"), td("", 'colspan="2"'),
                     td("法定代表人"), td("", 'colspan="1"')]))
    rows.append(tr([td("住所（注册地址）"), td("", 'colspan="4"')]))
    rows.append(tr([td("企业类型"), td("", 'colspan="4"')]))
    rows.append(tr([td("注册资本（万元）"), td("", 'colspan="2"'),
                     td("固定资产（万元）"), td("", 'colspan="1"')]))

    # 所属法人机构信息 rowspan=5
    org = td("所属法人机构信息", 'rowspan="5"')
    rows.append(tr([org, td("名称"), td("", 'colspan="3"')]))
    rows.append(tr([td("住所"), td("", 'colspan="3"')]))
    rows.append(tr([td("统一社会信用代码"), td("", 'colspan="1"'),
                     td("法定代表人"), td("", 'colspan="1"')]))
    rows.append(tr([td("企业类型"), td("", 'colspan="1"'),
                     td("联系人"), td("", 'colspan="1"')]))
    rows.append(tr([td("联系电话"), td("", 'colspan="1"'),
                     td("传真"), td("", 'colspan="1"')]))

    # 主要机构设置及人员组成 rowspan=3
    org2 = td("主要机构设置及人员组成", 'rowspan="3"')
    rows.append(tr([org2, td("机构名称"), td(""), td(""), td("")]))
    rows.append(tr([td("人数"), td(""), td(""), td("")]))
    rows.append(tr([td("人员总数"), td("", 'colspan="1"'),
                     td("其中专业技术人员"), td("", 'colspan="1"')]))

    rows.append(tr([td("企业简介：", 'colspan="5"')]))

    out = [
        "<!-- source: Images/02制度文件/0401.jpg (split: 0400, 左半, cut=%d) -->" % CUT,
        "<!-- repaired: rotated=no, method=api-minimax, form=table, blank-form -->",
        "",
    ] + table(rows)
    return "\n".join(out)


def build_401():
    t2 = []
    t2.append(tr([td("表2 基本生产情况", 'colspan="5"', "th")]))
    t2.append(tr([td("生产线序号", "th"), td("生产线一", "th"), td("生产线二", "th"),
                   td("生产线三", "th"), td("生产线四", "th")]))
    t2.append(tr([td("生产线名称")] + [td() for _ in range(4)]))
    t2.append(tr([td("生产能力（吨/小时）（立方米）（升）")] + [td() for _ in range(4)]))
    # 产品品种 | 产品系列(colspan=4) —— 图上产品系列横跨后 4 列
    t2.append(tr([td("产品品种"), td("产品系列", 'colspan="4"')]))
    for _ in range(4):
        t2.append(tr([td()] * 5))

    t3 = []
    t3.append(tr([td("表3 生产设备明细表", 'colspan="6"', "th")]))
    t3.append(tr([td("生产设备名称及序号", 'colspan="6"')]))
    t3.append(tr([td("序号", "th"), td("设备名称", "th"), td("型号规格", "th"),
                   td("生产厂家", "th"), td("出厂日期（年月）", "th"),
                   td("技术性能指标", "th")]))
    for _ in range(9):
        t3.append(tr([td()] * 6))

    out = [
        "<!-- source: Images/02制度文件/0401.jpg (split: 0401, 右半, cut=%d) -->" % CUT,
        "<!-- repaired: rotated=no, method=api-minimax, form=table, blank-form -->",
        "",
    ] + table(t2) + table(t3)
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


def check(txt, tag):
    errs = []
    tabs = re.findall(r"<table.*?</table>", txt, re.S)
    if tag == "0400":
        if len(tabs) != 1:
            return ["表数 %d != 1" % len(tabs)]
        tb = tabs[0]
        raws = re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S)
        w = [x for x, _ in expand_rows(raws)]
        if set(w) != {5}:
            errs.append("各行列数不统一为5: %s" % sorted(set(w)))
        for k in ("表1 企业基本情况", "企业名称", "生产地址", "通讯地址及邮编",
                  "法定代表人", "统一社会信用代码", "住所（注册地址）", "企业类型",
                  "注册资本（万元）", "固定资产（万元）", "所属法人机构信息",
                  "名称", "住所", "联系人", "联系电话", "传真",
                  "主要机构设置及人员组成", "机构名称", "人数", "人员总数",
                  "其中专业技术人员", "企业简介："):
            if k not in tb:
                errs.append("缺:" + k)
        if 'rowspan="5"' not in tb:
            errs.append("所属法人机构信息 缺 rowspan=5")
        if 'rowspan="3"' not in tb:
            errs.append("主要机构设置及人员组成 缺 rowspan=3")
        return errs

    if len(tabs) != 2:
        return ["表数 %d != 2" % len(tabs)]
    tb2, tb3 = tabs
    r2 = re.findall(r"<tr[^>]*>(.*?)</tr>", tb2, re.S)
    r3 = re.findall(r"<tr[^>]*>(.*?)</tr>", tb3, re.S)
    w2 = [x for x, _ in expand_rows(r2)]
    w3 = [x for x, _ in expand_rows(r3)]
    if set(w2) != {5}:
        errs.append("表2 列数不统一为5: %s" % sorted(set(w2)))
    if set(w3) != {6}:
        errs.append("表3 列数不统一为6: %s" % sorted(set(w3)))
    if len(r2) != 9:
        errs.append("表2 行数 %d != 9" % len(r2))
    if len(r3) != 12:
        errs.append("表3 行数 %d != 12" % len(r3))
    for k in ("表2 基本生产情况", "生产线序号", "生产线一", "生产线四",
              "生产线名称", "生产能力（吨/小时）（立方米）（升）",
              "产品品种", "产品系列"):
        if k not in tb2:
            errs.append("表2 缺:" + k)
    for k in ("表3 生产设备明细表", "生产设备名称及序号", "序号", "设备名称",
              "型号规格", "生产厂家", "出厂日期（年月）", "技术性能指标"):
        if k not in tb3:
            errs.append("表3 缺:" + k)
    return errs


def main():
    for tag, builder in (("0400", build_400), ("0401", build_401)):
        txt = builder()
        errs = check(txt, tag)
        out = os.path.join(OUTDIR, tag + ".md")
        if errs:
            print("!! %s 质量门未过: %s" % (tag, "; ".join(errs[:8])))
            continue
        open(out, "w", encoding="utf-8").write(txt)
        n = len(re.findall(r"<table", txt))
        print("OK %s -> %s (%d 表, %d 字节)" %
              (tag, os.path.relpath(out, REPO), n, len(txt.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
