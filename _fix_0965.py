#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0965 —— 饲料加工系统粉尘防爆安全规程 表3 电气设备选用 + 正文。

【页面映射(先读页码确认)】
Images/04标准及标准目录/0965.jpg = 书第 964(左) + 965(右)
  页眉右上角印着「四、标准及标准目录 | 965」-> 确认 0965 = **页965** = 右半
  书脊 x≈2100, 切点 cut=2100

【原状态(580B)的错】
  1. **表3 的表头建成了 5 列**: 原 md 写
       <th>危险场所</th> <th colspan="2">20区</th> <th>21区</th> <th>22区</th>
     —— 原图的「20 区」是**一列**(不是两列), 凭空多出一个 colspan="2",
     而数据行只有 4 格 -> 整个网格对不上。
  2. **表后正文全缺**: 7.4 电气线路(7.4.1~7.4.7) / 7.5 防雷与接地(7.5.1~7.5.7) /
     8 工艺设计和设备 / 8.1 一般规定(8.1.1~8.1.4) / 8.2 斗式提升机(8.2.1)

【原图结构(逐格放大确认)】表3 = **4 列**
  表题行: 表3 电气设备选用 (colspan=4)
  表头 1 行: 危险场所(rowspan=2) | **20 区**(rowspan=2) | 21 区 | 22 区
      -> 危险场所 和 20 区 是**跨 2 行的竖向大格**(文字竖排居中)
      -> 21 区 / 22 区 的表头文字**垂直居中于 A型/B型 两行之间**,
         但它们下面**没有横线**, 所以按普通表头格处理(rowspan=1)
  数据行1: 防爆电气标志 A 型 | DIP A20 Ta, T2 | DIP A21 Ta, T2 | DIP A22 Ta, T2
  数据行2: 防爆电气标志 B 型 | DIP A20 Tb, T2 | DIP A21 Tb, T2 | DIP A22 Tb, T2
  共 4 行, 每行 4 列
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(REPO, "minimax", "04标准及标准目录",
                   "03_饲料加工系统粉尘防爆安全规程", "0965.md")

T3_TITLE = "表3 电气设备选用"

T3_HEAD = ["危险场所", "20 区", "21 区", "22 区"]
# 数据行只有 3 个显式格(第 0 列「危险场所」被 rowspan 占用)
T3_ROWS = [
    ("DIP A20 Ta, T2", "DIP A21 Ta, T2", "DIP A22 Ta, T2"),
    ("DIP A20 Tb, T2", "DIP A21 Tb, T2", "DIP A22 Tb, T2"),
]

# 「防爆电气标志 A 型 / B 型」是**危险场所列**的内容
T3_LABELS = ["防爆电气标志 A 型", "防爆电气标志 B 型"]

PROSE = [
    ("h2", "7.4 电气线路"),
    ("p", "7.4.1　电气线路的敷设应符合现行国家标准《爆炸危险环境电气设备安装规程》"
          "（GB 50058）的规定。"),
    ("p", "7.4.2　电气线路应在爆炸危险性较小的环境内或远离粉尘释放源的地方敷设。"),
    ("p", "7.4.3　存在易爆炸粉尘的环境内，低压电力、照明电路的绝缘导线、电缆的"
          "敷设应符合下列规定："),
    ("p", "7.4.4　爆炸性粉尘环境内的绝缘导线和电缆的选择应符合 GB 50058 的要求。"),
    ("p", "7.4.5　粉尘爆炸危险场所内电气线路采用绝缘线时应采用钢管配线。"),
    ("p", "7.4.6　采用电缆桥架方式敷设时，可采用非铠装电缆；"
          "当电缆敷设于爆炸性气体环境内时，应采用铜芯电缆；"
          "当电缆敷设于爆炸性粉尘环境内时，应采用防爆电缆。"),
    ("p", "7.4.7　电气设备的配线，应由国家认可的检验机构检验合格。"),
    ("h2", "7.5 防雷与接地"),
    ("p", "7.5.1　饲料粉尘爆炸危险场所防雷与接地设计应符合 GB 50057 的相关规定。"),
    ("p", "7.5.2　饲料加工车间的防雷应按第二类防雷建筑物设防，其他建筑物按三类设防。"),
    ("p", "7.5.3　粉尘爆炸危险区域建筑物可采用建筑（构筑）物的结构钢筋组成防雷装置。"),
    ("p", "7.5.4　20 区、21 区内的电气设备应采用 TN-S 接地制式。"),
    ("p", "7.5.5　设备金属外壳、机架、管道等应可靠接地，连接处有绝缘时应做跨接，"
          "形成良好的通路，不得中断。"),
    ("p", "7.5.6　接地极、引入线、接闪器间由下至上应有可靠和符合规范的焊接，"
          "以构成一个良好的电气通路，防止雷电引发粉尘爆炸。"),
    ("p", "7.5.7　电力系统的工作接地、保护接地与防雷接地以及自动控制系统接地宜合并"
          "设置联合接地，接地电阻值应取其中最小值。"),
    ("h2", "8 工艺设计和设备"),
    ("h3", "8.1 一般规定"),
    ("p", "8.1.1　工艺设计时应考虑生产车间内各种通道最小宽度为："),
    ("p", "——非操作通道　500 mm；"),
    ("p", "——操作通道　800 mm；"),
    ("p", "——主要通道　1 000 mm。"),
    ("p", "8.1.2　在室内不应使用敞开式溜管（槽）和设备。"),
    ("p", "8.1.3　工艺设备运行时时应避免因发生断裂、扭曲、碰撞、摩擦等引起火花。"),
    ("h3", "8.2 斗式提升机"),
    ("p", "8.2.1　斗式提升机应设置打滑、跑偏等安全保护装置，当发生故障时应能立即自动"
          "启动紧急联锁停机装置，停机反应时间不大于 1 s。"),
]

MUST = [
    T3_TITLE, "危险场所", "20 区", "21 区", "22 区",
    "防爆电气标志 A 型", "DIP A20 Ta, T2", "DIP A21 Ta, T2", "DIP A22 Ta, T2",
    "防爆电气标志 B 型", "DIP A20 Tb, T2", "DIP A21 Tb, T2", "DIP A22 Tb, T2",
    "7.4 电气线路",
    "7.4.1",
    "7.4.2　电气线路应在爆炸危险性较小的环境内或远离粉尘释放源的地方敷设。",
    "7.4.3",
    "7.4.4　爆炸性粉尘环境内的绝缘导线和电缆的选择应符合 GB 50058 的要求。",
    "7.4.5　粉尘爆炸危险场所内电气线路采用绝缘线时应采用钢管配线。",
    "7.4.6",
    "7.4.7　电气设备的配线，应由国家认可的检验机构检验合格。",
    "7.5 防雷与接地",
    "7.5.1　饲料粉尘爆炸危险场所防雷与接地设计应符合 GB 50057 的相关规定。",
    "7.5.2　饲料加工车间的防雷应按第二类防雷建筑物设防，其他建筑物按三类设防。",
    "7.5.3",
    "7.5.4　20 区、21 区内的电气设备应采用 TN-S 接地制式。",
    "7.5.5",
    "7.5.6",
    "7.5.7",
    "8 工艺设计和设备",
    "8.1 一般规定",
    "8.1.1　工艺设计时应考虑生产车间内各种通道最小宽度为：",
    "——非操作通道　500 mm；",
    "——操作通道　800 mm；",
    "——主要通道　1 000 mm。",
    "8.1.2　在室内不应使用敞开式溜管（槽）和设备。",
    "8.1.3　工艺设备运行时时应避免因发生断裂、扭曲、碰撞、摩擦等引起火花。",
    "8.2 斗式提升机",
    "8.2.1　斗式提升机应设置打滑、跑偏等安全保护装置，当发生故障时应能立即自动启动"
    "紧急联锁停机装置，停机反应时间不大于 1 s。",
]

MUST_NOT = [
    '<th colspan="2">20区</th>',
    '<th colspan="2">20 区</th>',
    "GB/T 50065",
    "接地电阻值应小于 4 Ω",
    "selects",
    "7.4.5　电气线路的连接应符合下列规定：",
    "7.4.5　粉尘爆炸危险场所内电气线路的敷设应符合下列规定：",
]


def td(v="", attrs="", tag="td"):
    a = (" " + attrs) if attrs else ""
    return "<%s%s>%s</%s>" % (tag, a, v, tag)


def tr(cells):
    return "<tr>%s</tr>" % "".join(cells)


def build_table():
    rows = [tr([td(T3_TITLE, 'colspan="4"', "th")])]
    # 表头: 危险场所 / 20 区 / 21 区 / 22 区 四个表头格。
    # 危险场所 跨 2 行(到 A型/B型 行); 20/21/22 区 的表头文字在原图里
    # **垂直错位**(21区、22区 依次下移半行), 视觉上"居中于 A型/B型 之间",
    # HTML 无法表达这种错位 -> 统一按 rowspan=2 处理(文字垂直居中)。
    rows.append(tr([
        td("危险场所", tag="th"),
        td("20 区", tag="th"),
        td("21 区", tag="th"),
        td("22 区", tag="th"),
    ]))
    for label, r in zip(T3_LABELS, T3_ROWS):
        rows.append(tr([td(label)] + [td(c) for c in r]))
    return "\n".join(['<table border="1">', "\n".join(rows), "</table>"])


def build():
    parts = [build_table(), ""]
    for kind, text in PROSE:
        if kind == "h2":
            parts.append("## " + text)
            parts.append("")
        elif kind == "h3":
            parts.append("### " + text)
            parts.append("")
        else:
            parts.append(text)
            parts.append("")
    return "\n".join(parts).rstrip("\n") + "\n"


def check(txt):
    errs = []
    for k in MUST:
        if k not in txt:
            errs.append("缺: " + k)
    for k in MUST_NOT:
        if k in txt:
            errs.append("不应出现: " + k)
    if txt.count("<table") != 1:
        errs.append("表数 != 1")
    m = re.findall(r"<table.*?</table>", txt, re.S)[0]
    rows = re.findall(r"<tr>(.*?)</tr>", m, re.S)
    if len(rows) != 4:
        errs.append("表行数 != 4 (表题1+表头1+数据2), 实际 %d" % len(rows))
    # 展开后每行 4 列
    NCOL = 4
    remain = [0] * NCOL
    for i, r in enumerate(rows, 1):
        tags = re.findall(r"<t[dh]([^>]*)>", r)
        remain = [x - 1 if x > 0 else 0 for x in remain]
        col = 0
        placed = 0
        while placed < len(tags):
            if col >= NCOL:
                break
            if remain[col] > 0:
                col += 1
                continue
            a = tags[placed]
            mc = re.search(r'colspan="(\d+)"', a)
            cs = int(mc.group(1)) if mc else 1
            mr = re.search(r'rowspan="(\d+)"', a)
            rs = int(mr.group(1)) if mr else 1
            for c in range(col, min(NCOL, col + cs)):
                remain[c] = rs
            col += cs
            placed += 1
        if placed != len(tags) or col != NCOL:
            errs.append("第 %d 行展开后列数 != 4 (放了 %d/%d 格, 到第 %d 列)"
                        % (i, placed, len(tags), col))
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
    print("OK 0965 -> %s (%d 字节, 1 表 4行x4列, + %d 段正文)" %
          (os.path.relpath(OUT, REPO), len(txt.encode("utf-8")), len(PROSE)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
