#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0956 / 0957 / 0958 / 0959 —— GB 13078—2018 饲料卫生标准 表1 饲料卫生指标及试验方法
(跨 5 个书页的续表)。

【页面映射(先读页码确认, 别用文件号推)】
源图只有奇数(跨页扫描对):
  Images/04标准及标准目录/0955.jpg = 书第 954(左) + 955(右)
  Images/04标准及标准目录/0957.jpg = 书第 956(左) + 957(右)
  Images/04标准及标准目录/0959.jpg = 书第 958(左) + 959(右)
页眉右上角印「四、标准及标准目录 | 95X」-> 确认:
  0956 = **页956 = 0957.jpg 的左半**
  0957 = 页957 = 0957.jpg 的右半
  0958 = **页958 = 0959.jpg 的左半**
  0959 = 页959 = 0959.jpg 的右半

【真实表结构(竖线检测 + 逐条放大核验)】表1 = **7 列**
  序号 | 项目 | 产品名称(colspan=2: 类别 + 具体产品名称) | 限量 | 试验方法 | 备注
- **续表页的表头是 1 行**(不重复「类别」子表头行), 产品名称 仍跨 2 列
- 续表页表头右侧有「（续表）」标记 -> 记在表题位置
- 序号 / 项目 / 类别 都是**纵向 rowspan**
- 备注列在 955~959 上**全是空的**(只有 959 表头有「备注」二字)
- 项目格里单位与名称**分两行**(如「汞」/「mg/kg」)
- 表尾有 2 条**通栏注释**(colspan=7), 位于框线内

【原状态 4 处错】
0956: 33 行, **表头/序号/项目列全丢**, 第 1 行是「其他动物源性饲料原料 | ≤500」残片
0957: 24 行, **表头/序号/项目列全丢**, 第 1 行是「玉米浆干粉除外） | ≤1.5」残片
0958: 48 行, **表头/序号/项目列全丢**
0959: 19 行, 有表头但**备注列错位**, 且第 2 行「六六六」项目名被截断
-> 4 页都**没有 6/7 列的完整网格**, 类别/具体产品名称 混在一格里

【本页组统一重建为 7 列网格, 按原图逐条核对】
"""

import os
import re
import sys

BASE = r"E:/workspace/siliao/minimax/04标准及标准目录/02_饲料卫生标准"

T1_TITLE = "表1 饲料卫生指标及试验方法"

# ---------------------------------------------------------------- 表头
HEADER = [
    ("th", "序号", ""),
    ("th", "项目", ""),
    ("th", "产品名称", 'colspan="2"'),
    ("th", "限量", ""),
    ("th", "试验方法", ""),
    ("th", "备注", ""),
]
NCOL = 7


def rowspan_attr(n):
    """rowspan=1 是噪音, 不输出。"""
    return 'rowspan="%d"' % n if n > 1 else ""


def td(txt, attr="", tag="td"):
    a = (" " + attr) if attr else ""
    return "<%s%s>%s</%s>" % (tag, a, txt, tag)


def tr(cells):
    return "<tr>" + "".join(cells) + "</tr>"


def header_row():
    """表头行。HEADER 每项 = (tag, 文本, 属性)"""
    return tr([td(txt, attr, tag) for tag, txt, attr in HEADER])


# ---------------------------------------------------------------- 数据行
# 每条: (序号, 项目, [(类别, 具体产品名称, 限量, 试验方法), ...])
# 序号/项目/类别/试验方法/备注 的 rowspan 由下面的组装器算。
# 「类别」为 None 表示沿用上一行的类别(= 原图里该行并入上一类别块)。
# 「限量」为 None 表示沿用上一行的限量。

def item(no, name, rows, method=None, note=None, group=None):
    """rows: [(类别|None, 具体产品名称, 限量|None) 或 (…, 试验方法), ...]"""
    return dict(no=no, name=name, rows=rows, method=method, note=note, group=group)


# ===== 页956 (0957.jpg 左半) =====  —— 序号 6~9
# 注: 这些 item 的「试验方法」是**整块一个格**(同项目内所有行共用)
P956 = [
    item(6, "氟<br>mg/kg", [
        ("饲料原料", "甲壳类动物及其副产品", "≤3 000"),
        (None, "其他动物源性饲料原料", "≤500"),
        (None, "蛭石", "≤3 000"),
        (None, "其他矿物质饲料原料", "≤400"),
        (None, "其他饲料原料", "≤150"),
        ("饲料产品", "添加剂预混合饲料", "≤800"),
        (None, "浓缩饲料", "≤500"),
        (None, "牛、羊精料补充料", "≤50"),
        (None, "猪配合饲料", "≤100"),
        (None, "肉用仔鸡、育雏鸡、育成鸡配合饲料", "≤250"),
        (None, "产蛋鸡配合饲料", "≤350"),
        (None, "鸭配合饲料", "≤200"),
        (None, "水产配合饲料", "≤350"),
        (None, "其他配合饲料", "≤150"),
    ], method="GB/T 13083"),
    item(7, "亚硝酸盐（以 NaNO<sub>2</sub> 计）<br>mg/kg", [
        ("饲料原料", "火腿肠粉等肉制品生产过程中获得的前食品和副产品", "≤80"),
        (None, "其他饲料原料", "≤15"),
        ("饲料产品", "浓缩饲料", "≤20"),
        (None, "精料补充料", "≤20"),
        (None, "配合饲料", "≤15"),
    ], method="GB/T 13085"),
    item(8, "黄曲霉毒素 B<sub>1</sub><br>μg/kg", [
        ("饲料原料", "玉米加工产品、花生饼（粕）", "≤50"),
        (None, "植物油脂（玉米油、花生油除外）", "≤10"),
        (None, "玉米油、花生油", "≤20"),
        (None, "其他植物性饲料原料", "≤30"),
        ("饲料产品", "仔猪、雏禽浓缩饲料", "≤10"),
        (None, "肉用仔鸭后期、生长鸭、产蛋鸭浓缩饲料", "≤15"),
        (None, "其他浓缩饲料", "≤20"),
        (None, "犊牛、羔羊精料补充料", "≤20"),
        (None, "泌乳期精料补充料", "≤10"),
        (None, "其他精料补充料", "≤30"),
        (None, "仔猪、雏禽配合饲料", "≤10"),
        (None, "肉用仔鸭后期、生长鸭、产蛋鸭配合饲料", "≤15"),
        (None, "其他配合饲料", "≤20"),
    ], method="NY/T 2071", group="真菌毒素"),
    item(9, "赭曲霉毒素 A<br>μg/kg", [
        ("饲料原料", "谷物及其加工产品", "≤100"),
        ("饲料产品", "配合饲料", "≤100"),
    ], method="GB/T 30957"),
]

# ===== 页957 (0957.jpg 右半) =====  —— 序号 10~14
P957 = [
    item(10, "玉米赤霉烯醇<br>mg/kg", [
        ("饲料原料", "玉米及其加工产品 玉米浆干粉除外产品（玉米皮、喷浆玉米皮、玉米浆干粉、"
                    "玉米酒精糟类产品）", "≤0.5"),
        (None, "其他植物性饲料原料", "≤1.5"),
        ("饲料产品", "犊牛、羔羊、泌乳期精料补充料", "≤1"),
        (None, "仔猪配合饲料", "≤0.5"),
        (None, "青年母猪配合饲料", "≤0.15"),
        (None, "其他猪配合饲料", "≤0.1"),
        (None, "其他配合饲料", "≤0.25"),
    ], method="NY/T 2071"),
    item(11, "脱氧雪腐镰刀菌烯醇（呕吐毒素）<br>mg/kg", [
        ("饲料原料", "谷物及其加工产品", "≤0.5"),
        (None, "其他饲料原料", "≤1"),
        ("饲料产品", "添加剂预混合饲料", "≤2"),
        (None, "浓缩饲料", "≤0.5"),
        (None, "配合饲料", "≤0.5"),
    ], method="GB/T 30956"),
    item(12, "T-2 毒素<br>mg/kg", [
        ("饲料原料", "植物性饲料原料", "≤3"),
        ("饲料产品", "猪、禽配合饲料", "≤0.5"),
    ], method="NY/T 2071"),
    item(13, "伏马毒素（B<sub>1</sub>+B<sub>2</sub>）<br>mg/kg", [
        ("饲料原料", "玉米及其加工产品、玉米酒精糟产品、玉米青贮饲料和玉米秸秆", "≤60"),
        ("饲料产品", "犊牛、羔羊精料补充料", "≤20"),
        (None, "马、兔精料补充料", "≤5"),
        (None, "其他反刍动物精料补充料", "≤50"),
        (None, "猪浓缩饲料", "≤5"),
        (None, "家禽浓缩饲料", "≤20"),
        (None, "猪、兔、马配合饲料", "≤5"),
        (None, "家禽配合饲料", "≤20"),
        (None, "鱼配合饲料", "≤10"),
    ], method="NY/T 1970"),
    item(14, "氰化物（以 HCN 计）<br>mg/kg", [
        ("饲料原料", "亚麻籽【胡麻籽】", "≤250"),
        (None, "亚麻籽【胡麻籽】饼、亚麻籽【胡麻籽】粕", "≤350"),
        (None, "木薯及其加工产品", "≤100"),
        (None, "其他饲料原料", "≤50"),
        ("饲料产品", "雏鸡配合饲料", "≤10"),
        (None, "其他配合饲料", "≤50"),
    ], method="GB/T 13084", group="天然植物毒素"),
]

# ===== 页958 (0959.jpg 左半) =====  —— 序号 15~18
P958 = [
    item(15, "游离棉酚<br>mg/kg", [
        ("饲料原料", "棉籽油", "≤200"),
        (None, "棉籽", "≤5 000"),
        (None, "脱酚棉籽蛋白、发酵棉籽蛋白", "≤400"),
        (None, "其他棉籽加工产品", "≤1 200"),
        (None, "其他饲料原料", "≤20"),
        ("饲料产品", "猪（仔猪除外）、兔配合饲料", "≤60"),
        (None, "家禽（产蛋禽除外）配合饲料", "≤100"),
        (None, "犊牛精料补充料", "≤100"),
        (None, "其他牛精料补充料", "≤500"),
        (None, "羔羊精料补充料", "≤60"),
        (None, "其他羊精料补充料", "≤300"),
        (None, "植食性、杂食性水生动物配合饲料", "≤300"),
        (None, "其他水产配合饲料", "≤150"),
        (None, "其他畜禽配合饲料", "≤20"),
    ], method="GB/T 13086"),
    item(16, "异硫氰酸酯（以丙烯基异硫氰酸酯计）<br>mg/kg", [
        ("饲料原料", "菜籽及其加工产品", "≤4 000"),
        (None, "其他饲料原料", "≤100"),
        ("饲料产品", "犊牛、羔羊精料补充料", "≤150"),
        (None, "其他牛、羊精料补充料", "≤1 000"),
        (None, "猪（仔猪除外）、家禽配合饲料", "≤500"),
        (None, "水产配合饲料", "≤800"),
        (None, "其他配合饲料", "≤150"),
    ], method="GB/T 13087"),
    item(17, "噁唑烷硫酮（以 5-乙烯基-噻唑-2-硫酮计）<br>mg/kg", [
        ("饲料原料", "菜籽及其加工产品", "≤2 500"),
        ("饲料产品", "产蛋禽配合饲料", "≤500"),
        (None, "其他家禽配合饲料", "≤1 000"),
        (None, "水产配合饲料", "≤800"),
    ], method="GB/T 13089"),
    item(18, "多氯联苯（PCB，以 PCB28、PCB52、PCB101、PCB138、PCB153、PCB180 之和计）<br>"
            "μg/kg", [
        ("饲料原料", "植物性饲料原料", "≤10"),
        (None, "矿物性饲料原料", "≤10"),
        (None, "动物脂肪、乳脂和蛋脂", "≤10"),
        (None, "其他陆生动物产品，包括乳、蛋及其制品", "≤10"),
        (None, "鱼油", "≤175"),
        (None, "鱼和其他水生动物及其制品（鱼油、脂肪酸含量大于 20% 的鱼蛋白水解物除外）", "≤30"),
        (None, "脂肪酸含量大于 20% 的鱼蛋白水解物", "≤50"),
        ("饲料产品", "添加剂预混合饲料", "≤10"),
        (None, "水产浓缩饲料、水产配合饲料", "≤40"),
        (None, "其他浓缩饲料、精料补充料、配合饲料", "≤10"),
    ], method="GB 5009.190", group="有机氯污染物"),
]

# ===== 页959 (0959.jpg 右半) =====  —— 序号 19~24 + 表尾注释
# 注意:
#  - 19/20 的「试验方法」**逐行不同**(油脂行用 GB/T 5009.19, 其余用 GB/T 13090)
#  - 21/22 的「试验方法」是**整块一个格**
#  - 23/24 的「类别」列与「具体产品名称」列**无竖线分隔** -> 合成 colspan=2
#  - 微生物部分限量用 '<' 而非 '≤'
P959 = [
    item(19, "六六六（HCH，以 α-HCH、β-HCH、γ-HCH 之和计）<br>mg/kg", [
        ("饲料原料", "谷物及其加工产品（油脂除外）、油料籽实及其加工产品（油脂除外）、鱼粉", "≤0.05", "GB/T 13090"),
        (None, "油脂", "≤2.0", "GB/T 5009.19"),
        (None, "其他饲料原料", "≤0.2", "GB/T 13090"),
        ("饲料产品", "添加剂预混合饲料、浓缩饲料、精料补充料、配合饲料", "≤0.2", "GB/T 13090"),
    ]),
    item(20, "滴滴涕（以 p,p'-DDE、o,p'-DDT、p,p'-DDD 之和计）<br>mg/kg", [
        ("饲料原料", "谷物及其加工产品（油脂除外）、油料籽实及其加工产品（油脂除外）、鱼粉", "≤0.02", "GB/T 13090"),
        (None, "油脂", "≤0.5", "GB/T 5009.19"),
        (None, "其他饲料原料", "≤0.05", "GB/T 13090"),
        ("饲料产品", "添加剂预混合饲料、浓缩饲料、精料补充料、配合饲料", "≤0.05", "GB/T 13090"),
    ]),
    item(21, "六氯苯（HCB）<br>mg/kg", [
        ("饲料原料", "油脂", "≤0.2", "SN/T 0127"),
        (None, "其他饲料原料", "≤0.01", "SN/T 0127"),
        ("饲料产品", "添加剂预混合饲料、浓缩饲料、精料补充料、配合饲料", "≤0.01", "SN/T 0127"),
    ], method="SN/T 0127"),
    item(22, "霉菌总数<br>CFU/g", [
        ("饲料原料", "谷物及其加工产品", "<4×10<sup>3</sup>", "GB/T 13092"),
        (None, "饼粕类饲料原料（发酵产品除外）", "<4×10<sup>3</sup>", "GB/T 13092"),
        (None, "乳制品及其加工副产品", "<1×10<sup>3</sup>", "GB/T 13092"),
        (None, "鱼粉", "<1×10<sup>4</sup>", "GB/T 13092"),
        (None, "其他动物源性饲料原料", "<2×10<sup>4</sup>", "GB/T 13092"),
    ], method="GB/T 13092", group="微生物污染物"),
    item(23, "细菌总数<br>CFU/g", [
        (None, "动物源性饲料原料", "<2×10<sup>4</sup>", "GB/T 13093"),
    ], method="GB/T 13093"),
    item(24, "沙门氏菌<br>（25g 中）", [
        (None, "饲料原料和饲料产品", "不得检出", "GB/T 13091"),
    ], method="GB/T 13091"),
]

# 表尾注释(框线内, 通栏 colspan=7)
NOTES_959 = [
    "表中所列限量，除特别注明外均以干物质含量 88%为基础计算（霉菌总数、细菌总数、"
    "沙门氏菌除外）。",
    "饲料原料单独饲喂时，应按相应配合饲料限量执行。",
]

PAGES = {
    "0956": dict(items=P956, cont=True),
    "0957": dict(items=P957, cont=True),
    "0958": dict(items=P958, cont=True),
    "0959": dict(items=P959, cont=True, notes=NOTES_959),
}


# ---------------------------------------------------------------- 组装
def build_rows(items):
    """把 item 列表编成 HTML 行(算 rowspan)。

    rows 每项: (类别|None, 具体产品名称, 限量|None[, 试验方法|None])
      类别=None 且该 item 完全没有类别块 -> 类别列与具体产品名称列合成 colspan=2
      试验方法=None -> 沿用 item.method(整块 rowspan)
    """
    rows = []
    for it in items:
        if it["group"]:
            # 分组带: 原图里文字从「类别」列开始(左侧 序号/项目 两列是空的),
            # 一路横到表尾 -> 空 colspan=2 + 文字 colspan=5
            rows.append(tr([
                td("", 'colspan="2"'),
                td(it["group"], 'colspan="5"', "th"),
            ]))
        n = len(it["rows"])
        # 类别分组: 连续出现的类别名合并成 rowspan
        cat_span = []
        for i, r in enumerate(it["rows"]):
            if r[0] is not None:
                j = i
                while j + 1 < n and it["rows"][j + 1][0] is None:
                    j += 1
                cat_span.append((i, j - i + 1))
        cat_at = {s_: span for s_, span in cat_span}
        lim = None
        for i, r in enumerate(it["rows"]):
            cat, prod, limv = r[0], r[1], r[2]
            meth = r[3] if len(r) > 3 else None
            if limv is not None:
                lim = limv
            cells = []
            if i == 0:
                cells.append(td(str(it["no"]), rowspan_attr(n)))
            if i == 0:
                cells.append(td(it["name"], rowspan_attr(n)))
            # 类别
            if i in cat_at:
                cells.append(td(cat, rowspan_attr(cat_at[i])))
            # 具体产品名称
            if cat is None and not cat_span:
                # 类别列整列为空 -> 与产品名合并成一个 colspan=2 的格
                cells.append(td(prod, 'colspan="2"'))
            else:
                cells.append(td(prod))
            # 限量
            cells.append(td(lim if limv is None else limv))
            # 试验方法
            if meth is not None:
                cells.append(td(meth))
            elif i == 0:
                cells.append(td(it["method"], rowspan_attr(n)))
            # 备注
            if i == 0:
                cells.append(td(it["note"] or "", rowspan_attr(n)))
            rows.append(tr(cells))
    return rows


def build_page(pageno, spec):
    out = []
    if spec["cont"]:
        # 续表页: 表**上方**一行独立的「（续表）」(原图里它浮在表格上方, 不在任何格子里),
        # 表内**没有表题行**, 只有表头行。
        out.append(header_row())
    else:
        out.append(tr([td(T1_TITLE, 'colspan="%d"' % NCOL, "th")]))
        out.append(header_row())
    out.extend(build_rows(spec["items"]))
    for nt in spec.get("notes", []):
        out.append(tr([td(nt, 'colspan="%d"' % NCOL)]))
    return "\n".join(out)


# ---------------------------------------------------------------- 质量门
def check(text, pageno, spec):
    errs = []
    if text.count("<table") != 1:
        errs.append("表数 != 1")
    m = re.search(r"<table[^>]*>(.*)</table>", text, re.S)
    if not m:
        return ["找不到 <table>"]
    tbl = m.group(1)
    trs = re.findall(r"<tr>(.*?)</tr>", tbl, re.S)
    if not trs:
        return ["表内无行"]

    # 表头列数(表头行 = 第一个含 <th> 的行; 表题行也在里面, 需跳过)
    hdr_idx = None
    for i, r in enumerate(trs):
        if "<th" in r and "序号" in r:
            hdr_idx = i
            break
    if hdr_idx is None:
        return ["找不到表头行"]
    hdr = trs[hdr_idx]
    hcs = re.findall(r"<th([^>]*)>(.*?)</th>", hdr, re.S)
    span = 0
    for a, _c in hcs:
        mm = re.search(r'colspan="(\d+)"', a)
        span += int(mm.group(1)) if mm else 1
    if span != NCOL:
        errs.append("表头展开列数 != %d (实际 %d)" % (NCOL, span))
    if "备注" not in hdr:
        errs.append("表头缺 备注 列")

    # 逐行展开列数(正确算法: 计入上方 rowspan 占用)
    remain = [0] * NCOL
    for ri, r in enumerate(trs, 1):
        cells = re.findall(r"<t[dh]([^>]*)>(.*?)</t[dh]>", r, re.S)
        col = 0
        for a, _c in cells:
            while col < NCOL and remain[col] > 0:
                col += 1
            if col >= NCOL:
                errs.append("第 %d 行单元格溢出 %d 列" % (ri, NCOL))
                break
            mm = re.search(r'colspan="(\d+)"', a)
            cs = int(mm.group(1)) if mm else 1
            rm = re.search(r'rowspan="(\d+)"', a)
            if rm:
                for k in range(col, min(col + cs, NCOL)):
                    remain[k] = int(rm.group(1)) - 1
            col += cs
        # 该行结束: 所有 rowspan 剩余高度 -1
        remain = [max(0, v - 1) for v in remain]

    # 必须出现(对**去标签后的纯文本**比较, 以便 <sub>/<sup> 片段也能匹配)
    plain = re.sub(r"<[^>]+>", "", tbl)
    for it in spec["items"]:
        if str(it["no"]) not in plain:
            errs.append("缺序号 %s" % it["no"])
        nm = it["name"]
        for frag in re.split(r"<br\s*/?>", nm):
            frag = re.sub(r"<[^>]+>", "", frag).strip()
            if frag and frag not in plain:
                errs.append("缺项目名片段: " + frag)
        for r in it["rows"]:
            prod = r[1]
            limv = r[2]
            if prod not in plain:
                errs.append("缺产品名: " + prod)
            if limv:
                lim_plain = re.sub(r"<[^>]+>", "", limv)
                if lim_plain not in plain:
                    errs.append("缺限量: " + lim_plain)
            if len(r) > 3 and r[3] and r[3] not in plain:
                errs.append("缺试验方法: " + r[3])
        if it["method"] and it["method"] != "——" and it["method"] not in plain:
            errs.append("缺试验方法: " + it["method"])

    # 禁止: 老 md 的残片 / 假列
    for bad in ("其他动物源性饲料原料 | ≤500", "玉米浆干粉除外） | ≤1.5"):
        if bad in tbl:
            errs.append("残留旧残片: " + bad)
    if "| ≤" in tbl:
        errs.append("残留管道符")
    # 续表页必须有 (续表)
    if spec["cont"] and "（续表）" not in text:
        errs.append("续表页缺 （续表） 标记")
    if spec["cont"] and "（续表）" in tbl:
        errs.append("（续表）应浮在表外, 不应塞进格子里")
    if not spec["cont"] and "（续表）" in text:
        errs.append("末页不应有 （续表）")
    # 续表页不应有表题行
    if spec["cont"] and T1_TITLE in tbl:
        errs.append("续表页不应有表题行")
    for nt in spec.get("notes", []):
        if re.sub(r"\s+", "", nt) not in re.sub(r"\s+", "", tbl):
            errs.append("缺表尾注释: " + nt[:30])
    return errs


def main():
    for pageno, spec in PAGES.items():
        tbl = build_page(pageno, spec)
        prefix = "（续表）\n\n" if spec["cont"] else ""
        text = prefix + ("<table border=\"1\">\n" + tbl + "\n</table>\n")
        errs = check(text, pageno, spec)
        if errs:
            print("!! %s 质量门未过:" % pageno)
            for e in errs[:20]:
                print("   - " + e)
            sys.exit(1)
        out = os.path.join(BASE, pageno + ".md")
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
        ntr = text.count("<tr>")
        print("OK %s -> %s (%d 字节, %d 行, %d 列)"
              % (pageno, out, len(text.encode("utf-8")), ntr, NCOL))


if __name__ == "__main__":
    main()
