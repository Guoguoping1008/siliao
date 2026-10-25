#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0911 —— 农业转基因生物安全评价指南 附表 + 附件2 开头。

【页面映射(先读页码确认)】
Images/03相关法规法律法规文件/0911.jpg = 书第 910(左) + 911(右)
  页眉右上角印着「三、相关法律法规文件 | 911」-> 确认 0911 = **页911** = 右半
  书脊 x≈2100, 切点 cut=2070

【原状态(1803B)的 3 处错】
  1. **标题行读烂**: `# 附则 主要转基因农作物适宜生态区类型`
     -> 原文是 **「附表」** 独立一行 + 表题「主要转基因农作物适宜生态区类型（参考）」
        在**表内第一行**(colspan=2)。没有「附则」, 也没有"附则"字样。
  2. **作物列的 rowspan 丢了** —— 原表「水稻」跨 6 行、「玉米」跨 5 行、
     「大豆」跨 3 行、「棉花」跨 3 行; md 里全是空 <td>, 语义全丢。
  3. **附件2「转基因动物安全评价指南」整段缺失** —— 页911 下半页有:
        附件 2
        转基因动物安全评价指南
        (定义段) + (一)~(五) 用途列表

【页911 表格结构(目视确认 rowspan)】
  表题行: 主要转基因农作物适宜生态区类型（参考）  (colspan=2)
  表头行: 作物 | 适宜生态区类型
  水稻 rowspan=6: 华南稻区 / 华中稻区 / 西南高原稻区 / 华北稻区 / 东北稻区 / 西北稻区
  玉米 rowspan=5: 北方春玉米区 / 黄淮海夏玉米区 / 西南玉米区 / 南方玉米区 / 西北玉米区
  大豆 rowspan=3: 北方春大豆区 / 黄淮海夏大豆区 / 南方大豆区
  棉花 rowspan=3: 黄河流域棉区 / 长江流域棉区 / 西北内陆棉区
  共 1 + 1 + 6 + 5 + 3 + 3 = **19 行**
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(REPO, "minimax", "03相关法律法规文件", "05_（五）转基因管理",
                   "29_农业转基因生物（植物、动物、动物用微生物）安全评价指南", "0911.md")

TABLE_TITLE = "主要转基因农作物适宜生态区类型（参考）"

# (作物, rowspan, [生态区...])
GROUPS = [
    ("水稻", 6, ["华南稻区", "华中稻区", "西南高原稻区",
                 "华北稻区", "东北稻区", "西北稻区"]),
    ("玉米", 5, ["北方春玉米区", "黄淮海夏玉米区", "西南玉米区",
                 "南方玉米区", "西北玉米区"]),
    ("大豆", 3, ["北方春大豆区", "黄淮海夏大豆区", "南方大豆区"]),
    ("棉花", 3, ["黄河流域棉区", "长江流域棉区", "西北内陆棉区"]),
]

ANNEX_TITLE = "转基因动物安全评价指南"

ANNEX_INTRO = (
    "转基因动物是指通过显微注射、电穿孔、粒子轰击、细胞转化、病毒导入等基因操作"
    "技术，将外源片段导入受体或定向改造受体基因得到的用于农业生产或者农产品加工的"
    "动物及其产品，包括用于如下用途的畜禽、水生动物和节肢动物等。"
)

ANNEX_LIST = [
    "（一）产量性状改良：改良生长发育速度、消化吸收率和饲料转化率等；",
    "（二）品质性状改良：改良营养成分、减少致敏原、用于观赏等；",
    "（三）繁殖性状改良：调控动物的繁殖力和性别；",
    "（四）抗逆：改良动物对环境条件、疾病和化学物质的抗性；",
    "（五）环境指示：对环境质量变化有指示性作用；",
]

MUST = [
    "附表",
    TABLE_TITLE,
    "作物", "适宜生态区类型",
    "水稻", "华南稻区", "华中稻区", "西南高原稻区", "华北稻区", "东北稻区", "西北稻区",
    "玉米", "北方春玉米区", "黄淮海夏玉米区", "西南玉米区", "南方玉米区", "西北玉米区",
    "大豆", "北方春大豆区", "黄淮海夏大豆区", "南方大豆区",
    "棉花", "黄河流域棉区", "长江流域棉区", "西北内陆棉区",
    "附件 2",
    ANNEX_TITLE,
    "转基因动物是指通过显微注射、电穿孔、粒子轰击、细胞转化、病毒导入等基因操作技术",
    "畜禽、水生动物和节肢动物等。",
    "（一）产量性状改良：改良生长发育速度、消化吸收率和饲料转化率等；",
    "（二）品质性状改良：改良营养成分、减少致敏原、用于观赏等；",
    "（三）繁殖性状改良：调控动物的繁殖力和性别；",
    "（四）抗逆：改良动物对环境条件、疾病和化学物质的抗性；",
    "（五）环境指示：对环境质量变化有指示性作用；",
]

MUST_NOT = [
    "# 附则",
    "<td></td>",       # 作物列不允许有空格(必须用 rowspan)
]


def td(v="", attrs="", tag="td"):
    a = (" " + attrs) if attrs else ""
    return "<%s%s>%s</%s>" % (tag, a, v, tag)


def build():
    rows = []
    rows.append("<tr>%s</tr>" % td(TABLE_TITLE, 'colspan="2"', "th"))
    rows.append("<tr>%s%s</tr>" % (td("作物", tag="th"), td("适宜生态区类型", tag="th")))
    for crop, span, zones in GROUPS:
        first = True
        for z in zones:
            if first:
                rows.append("<tr>%s%s</tr>" % (
                    td(crop, 'rowspan="%d"' % span), td(z)))
                first = False
            else:
                rows.append("<tr>%s</tr>" % td(z))
    tbl = "\n".join(rows)

    return "\n".join([
        "## 附表",
        "",
        '<table border="1">',
        tbl,
        "</table>",
        "",
        "## 附件 2",
        "",
        "# " + ANNEX_TITLE,
        "",
        ANNEX_INTRO,
        "",
    ] + ANNEX_LIST + [""])


def check(txt):
    errs = []
    for k in MUST:
        if k not in txt:
            errs.append("缺: " + k)
    for k in MUST_NOT:
        if k in txt:
            errs.append("不应出现: " + k)
    # 表行数: 1 表题 + 1 表头 + 17 数据 = 19
    n = txt.count("<tr>")
    if n != 19:
        errs.append("表行数 != 19, 实际 %d" % n)
    # rowspan 必须齐
    for crop, span, _ in GROUPS:
        if '<td rowspan="%d">%s</td>' % (span, crop) not in txt:
            errs.append("rowspan 不对: %s(%d)" % (crop, span))
    # 展开后每行都应是 2 列:
    #   - colspan=2 的行只有 1 个显式格 (表题行)
    #   - 有 rowspan 的行只有 1 个显式格, 另 1 格被 rowspan 占位
    # 用 colspan/rowspan 占位网格算, 不能直接数 <td> 个数。
    # 展开后每行都应是 2 列。
    # 正确算法: 维护每列的 rowspan 剩余高度, 逐行放格。
    #   - 某列 col 有剩余高度 -> 该列被上方 rowspan 占位, 本行跳过
    #   - 否则在下一个空闲列放一个显式格; 该格的 colspan 占若干列,
    #     rowspan=N 则这 N 列的剩余高度 = N-1 (本行已算 1)
    NCOL = 2
    remain = [0] * NCOL
    for i, m in enumerate(re.findall(r"<tr>(.*?)</tr>", txt, re.S), 1):
        tags = re.findall(r"<t[dh]([^>]*)>", m)
        # 先把上一行延续下来的占位高度减 1
        remain = [r - 1 if r > 0 else 0 for r in remain]
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
            # rowspan=N: 本行起共占 N 行。remain 在**下一行开头**才 -1,
            # 所以这里存 N, 让下一行开始时正好减到 N-1。
            for c in range(col, min(NCOL, col + cs)):
                remain[c] = rs
            col += cs
            placed += 1
        if placed != len(tags) or col != NCOL:
            errs.append("第 %d 行展开后列数 != 2 (放了 %d/%d 格, 占到第 %d 列)"
                        % (i, placed, len(tags), col))
    # 标题不能是「附则」
    if txt.lstrip().startswith("# 附则"):
        errs.append("标题行读烂(附则)")
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
    print("OK 0911 -> %s (%d 字节, 1 表: 19 行 x 2 列 + rowspan 4 处)" %
          (os.path.relpath(OUT, REPO), len(txt.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
