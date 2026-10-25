#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0409/0410/0411/0412。

【页面映射(先读页码确认, 别靠文件名猜)】
Images/02制度文件/0409.jpg = 书第 408(左) + 409(右)
  0409 <- 页409: 宠物添加剂预混合饲料生产许可证申请书 —— **无边框的表单排版**,
         不是表格。当前 md 错把它包成了 <table>。
Images/02制度文件/0411.jpg = 书第 410(左) + 411(右)
  0410 <- 页410: 表1 企业基本情况 (5 列 + 嵌套 rowspan)
  0411 <- 页411: 表2 产品情况 + 表3 生产设备明细表
Images/02制度文件/0413.jpg = 书第 412(左) + 413(右)
  0412 <- 页412: 表4 检验仪器明细表 + 表5 主要管理技术人员及持有工种人员登记表

  (0415 那条是口误: 页414 是纯正文, 没有表格; 用户后来也改成了 0409/0410/0411/0412)

【书脊】
0409.jpg 折痕 x≈2250; 0411.jpg 折痕 x≈2250; 0413.jpg 折痕 x≈2250
取 cut=2130(各图表格右边界 ~2030 之后, 折痕之前)

【真值(目视逐行核对)】
页410 表1 企业基本情况 (与页400 同一张表):
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

页411:
  表2 产品情况 (4 列): 生产线序号|生产线一|生产线二|生产线三
     生产线名称 | (3 空)
     生产能力(吨/小时)(立方米)(升) | (3 空)
     产品品种 | (值) | 产品系列 | (值)   <- 两两并排, 不是 colspan
     + 空数据行
  表3 生产设备明细表 (**7 列**, 比页401 多一列「材质」)
     生产设备名称及序号 (colspan=7)
     序号|设备名称|型号规格|材质|生产厂家|出厂日期(年月)|技术性能指标
     + 空数据行

页412:
  表4 检验仪器明细表 (6 列)
     序号|仪器名称|型号规格|生产厂家|出厂日期(年月)|出厂编号|技术性能指标
     + 空数据行
  表5 主要管理技术人员及持有工种人员登记表 (8 列)
     序号|姓名|职务|职称|学历|所学专业|资格证书时间、种类及编号|发证机关
     + 空数据行
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


def hdr(txt, tag="th"):
    return "<table border=\"1\">"


# ============================================================ 0409: 页409 申请书(无表格)
def build_409():
    """页409 是**无边框表单排版**, 不是表格 —— 不要包 <table>。"""
    return "\n".join([
        "<!-- source: Images/02制度文件/0409.jpg (split: 0409, 右半, cut=%d) -->" % CUT,
        "<!-- repaired: rotated=no, method=api-minimax, form=prose, no-table -->",
        "",
        "生产许可证编号：____________________",
        "",
        "# 宠物添加剂预混合饲料生产许可证申请书",
        "",
        "产品品种：",
        "",
        "- 固态宠物添加剂预混合饲料 □",
        "- 半固态宠物添加剂预混合饲料 □",
        "- 液态宠物添加剂预混合饲料 □",
        "",
        "企业名称：____________________　　（公章）",
        "",
        "联 系 人：____________________",
        "",
        "联系方式：____________________",
        "",
        "申请事项：设立 □　　续展 □　　增加或更换生产线 □",
        "",
        "增加产品品种 □　　迁址 □",
        "",
        "申报日期：________ 年 ____ 月 ____ 日",
        "",
        "中华人民共和国农业农村部制",
        "",
    ])


# ============================================================ 0410: 页410 表1
def build_410():
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
        "<!-- source: Images/02制度文件/0411.jpg (split: 0410, 左半, cut=%d) -->" % CUT,
        "<!-- repaired: rotated=no, method=api-minimax, form=table, blank-form -->",
        "",
        hdr(None),
    ] + rows + [
        "</table>",
        "",
    ]
    return "\n".join(out)


# ============================================================ 0411: 页411 表2+表3
def build_411():
    t2 = []
    t2.append(tr([td("表2 产品情况", 'colspan="4"', "th")]))
    t2.append(tr([td("生产线序号", "th"), td("生产线一", "th"),
                   td("生产线二", "th"), td("生产线三", "th")]))
    t2.append(tr([td("生产线名称")] + [td() for _ in range(3)]))
    t2.append(tr([td("生产能力（吨/小时）（支/小时）（升）")] + [td() for _ in range(3)]))
    # 产品品种 | 产品系列(colspan=3) —— 图上产品系列横跨后 3 列
    t2.append(tr([td("产品品种"), td("产品系列", 'colspan="3"')]))
    for _ in range(6):
        t2.append(tr([td()] * 4))

    t3 = []
    t3.append(tr([td("表3 生产设备明细表", 'colspan="7"', "th")]))
    # 生产线名称及序号 只跨**前 2 列**(序号+设备名称), 右边 5 列是一个空的大格
    t3.append(tr([td("生产线名称及序号", 'colspan="2"'), td("", 'colspan="5"')]))
    t3.append(tr([td("序号", "th"), td("设备名称", "th"), td("型号规格", "th"),
                   td("材质", "th"), td("生产厂家", "th"),
                   td("出厂日期（年月）", "th"), td("技术性能指标", "th")]))
    for _ in range(10):
        t3.append(tr([td()] * 7))

    out = [
        "<!-- source: Images/02制度文件/0411.jpg (split: 0411, 右半, cut=%d) -->" % CUT,
        "<!-- repaired: rotated=no, method=api-minimax, form=table, blank-form -->",
        "",
        hdr(None),
    ] + t2 + [
        "</table>",
        "",
        hdr(None),
    ] + t3 + [
        "</table>",
        "",
    ]
    return "\n".join(out)


# ============================================================ 0412: 页412 表4+表5
def build_412():
    # 表4: 标题「表4 检验仪器明细表」是**表上方的题注**, 不是表内的一行
    t4 = []
    t4.append(tr([td("序号", "th"), td("仪器名称", "th"), td("型号规格", "th"),
                   td("生产厂家", "th"), td("出厂日期（年月）", "th"),
                   td("出厂编号", "th"), td("技术性能指标", "th")]))
    for _ in range(10):
        t4.append(tr([td()] * 7))

    # 表5: 标题是「表5 主要管理技术人员登记表」(没有「及持有工种人员」)
    t5 = []
    t5.append(tr([td("序号", "th"), td("姓名", "th"), td("职务", "th"),
                   td("职称", "th"), td("学历", "th"), td("所学专业", "th"),
                   td("资格证书时间、种类及编号", "th"), td("发证机关", "th")]))
    for _ in range(9):
        t5.append(tr([td()] * 8))

    out = [
        "<!-- source: Images/02制度文件/0413.jpg (split: 0412, 左半, cut=%d) -->" % CUT,
        "<!-- repaired: rotated=no, method=api-minimax, form=table, blank-form -->",
        "",
        "**表4 检验仪器明细表**",
        "",
        hdr(None),
    ] + t4 + [
        "</table>",
        "",
        "**表5 主要管理技术人员登记表**",
        "",
        hdr(None),
    ] + t5 + [
        "</table>",
        "",
        "注：“证书”指与企业签订了全日制用工劳动合同并缴纳了养老、医疗等保险等"
        "管理人员、技术人员的职称证书、最高学历证书。",
        "",
    ]
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
    if tag == "0409":
        if "<table" in txt:
            errs.append("页409 是无边框表单, 不该有 <table>")
        for k in ("生产许可证编号", "宠物添加剂预混合饲料生产许可证申请书",
                  "固态宠物添加剂预混合饲料", "半固态宠物添加剂预混合饲料",
                  "液态宠物添加剂预混合饲料", "企业名称", "联系人", "联系方式",
                  "申请事项", "设立", "续展", "增加或更换生产线", "增加产品品种",
                  "迁址", "申报日期", "中华人民共和国农业农村部制"):
            # 坑: 图上「联 系 人」是**加空格排版**的, 直接用 in 匹配会漏。
            # 所以比对前先把正文里的空白全部去掉。
            if k.replace(" ", "") not in txt.replace(" ", "").replace("　", ""):
                errs.append("缺:" + k[:18])
        return errs

    if tag == "0410":
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

    if tag == "0411":
        if len(tabs) != 2:
            return ["表数 %d != 2" % len(tabs)]
        tb2, tb3 = tabs
        r2 = re.findall(r"<tr[^>]*>(.*?)</tr>", tb2, re.S)
        r3 = re.findall(r"<tr[^>]*>(.*?)</tr>", tb3, re.S)
        w2 = [x for x, _ in expand_rows(r2)]
        w3 = [x for x, _ in expand_rows(r3)]
        if set(w2) != {4}:
            errs.append("表2 列数不统一为4: %s" % sorted(set(w2)))
        if set(w3) != {7}:
            errs.append("表3 列数不统一为7: %s" % sorted(set(w3)))
        for k in ("表2 产品情况", "生产线序号", "生产线一", "生产线三",
                  "生产线名称", "生产能力（吨/小时）（支/小时）（升）",
                  "产品品种", "产品系列"):
            if k not in tb2:
                errs.append("表2 缺:" + k)
        for k in ("表3 生产设备明细表", "生产线名称及序号", "序号", "设备名称",
                  "型号规格", "材质", "生产厂家", "出厂日期（年月）",
                  "技术性能指标"):
            if k not in tb3:
                errs.append("表3 缺:" + k)
        # 生产线名称及序号 只跨 2 列
        if 'colspan="2">生产线名称及序号' not in tb3:
            errs.append("生产线名称及序号 应只跨 2 列")
        return errs

    # 0412
    if len(tabs) != 2:
        return ["表数 %d != 2" % len(tabs)]
    tb4, tb5 = tabs
    r4 = re.findall(r"<tr[^>]*>(.*?)</tr>", tb4, re.S)
    r5 = re.findall(r"<tr[^>]*>(.*?)</tr>", tb5, re.S)
    w4 = [x for x, _ in expand_rows(r4)]
    w5 = [x for x, _ in expand_rows(r5)]
    if set(w4) != {7}:
        errs.append("表4 列数不统一为7: %s" % sorted(set(w4)))
    if set(w5) != {8}:
        errs.append("表5 列数不统一为8: %s" % sorted(set(w5)))
    if len(r4) != 11:
        errs.append("表4 行数 %d != 11" % len(r4))
    if len(r5) != 10:
        errs.append("表5 行数 %d != 10" % len(r5))
    for k in ("表4 检验仪器明细表", "序号", "仪器名称", "型号规格", "生产厂家",
              "出厂日期（年月）", "出厂编号", "技术性能指标"):
        if k not in tb4 and k not in txt:
            errs.append("表4 缺:" + k)
    for k in ("表5 主要管理技术人员登记表", "姓名", "职务", "职称",
              "学历", "所学专业", "资格证书时间、种类及编号", "发证机关"):
        if k not in tb5 and k not in txt:
            errs.append("表5 缺:" + k)
    if "注：“证书”指与企业签订了全日制用工劳动合同" not in txt:
        errs.append("缺表5 的注")
    # 表5 标题不能带「及持有工种人员」
    if "及持有工种人员" in txt:
        errs.append("表5 标题多了「及持有工种人员」")
    return errs


def main():
    for tag, builder in (("0409", build_409), ("0410", build_410),
                         ("0411", build_411), ("0412", build_412)):
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
