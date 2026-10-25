#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0238/0239 的表格 —— **跨页续表**, 两页是同一张表的前后两半。

【原状态(都错)】
0238.md: 骨架 5 列, 但
  - 类别列写成「饲料用活动物 / 饲料 / 配合饲料」—— **把种类当成了类别**
  - 种类第2行「饲料用(含饵料用)冰鲜冷冻**动物**产品」—— 原文是「**动物**产品」? 实为「产品」(见下)
  - 漏了 3 级子列(生的宠物食品 / 其他)
  - 漏了正文(公告标题 + 一段正文 + 附件)
0239.md: 「饲料类」那行类别列串了「饲料粮谷物」, 多处行错位, 类别名不对

【跨页续表的坑】
这张表**跨 238/239 两页**: 238 是「表头 + 前 6 行」, 239 是「(续表) + 后 11 行」。
- 两页的 md **各自独立**, 0238 存前半张(带标题行), 0239 存后半张(带 (续表) 标记)
- 239 的表头重复出现, 但**第一列的 rowspan 在 239 开头要重新起**(延续上页的合并不能跨文件)
- 书脊实测 x≈2020(算法给 1705, 偏左 315px)

【真值: 目视核对过】
页238 (类别=动物源性饲料 rowspan 6):
  种类                                    | 子类          | 风险级别
  饲料用活动物                             |               | Ⅰ级
  饲料用(含饵料用)冰鲜冷冻动物产品          |               | Ⅰ级
  饲料用(含饵料用)水产品                   |               | Ⅲ级
  加工动物蛋白及油脂                        |               | Ⅱ级
  宠物食品和咬胶 (rowspan 2)                | 生的宠物食品  | Ⅰ级
                                          | 其他          | Ⅱ级
  出口列全部 = 符合进口国家或地区的要求

页239 (续表):
  类别 rowspan3 = 饲料粮谷物
    饲料粮谷物 | Ⅰ级
    饲料用草籽 | Ⅰ级
    饲料类     | Ⅱ级
  类别 rowspan4 = 植物源性饲料蛋白、糖蜜饼粕类
    种类 rowspan2 = 加工植物蛋白、糖蜜饼粕渣类
      子类 = 来自TCK疫区的麦麸 | Ⅰ级
      子类 = 其他                 | Ⅱ级
    青贮料     | Ⅲ级
    植物粉末   | Ⅲ级
  类别 rowspan1 = 配合饲料 | Ⅱ级
  类别 rowspan3 = 饲料添加剂、添加剂预混合饲料
    含动物源性成分 | Ⅱ级
    不含动物源性成分但含植物源性成分 | 按所含的植物源性成分分级
    其他 | Ⅳ级
  出口列全部 = 符合进口国家或地区的要求
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(REPO, "minimax", "02制度文件", "03_（三）进口登记和出口服务",
                      "38_质检总局关于修订进出口饲料和饲料添加剂风险级别及检验检疫监管方式的公告")

# ---------------------------------------------------------------- 监管方式文案
IMP_1 = ("进口前须申请并取得《进境动植物检疫许可证》；进口时查验检疫证书并实施检疫；"
         "对进口后的加工场所实施检疫监督。")
IMP_2 = ("进口前须申请并取得《进境动植物检疫许可证》（另有规定的按照相关规定执行）；"
         "进口时查验检疫证书并实施检疫。")
IMP_3 = "进口时查验检疫证书并实施检疫。"
IMP_4 = "进口实施检疫。"
EXP = "符合进口国家或地区的要求"

HEAD = ["类别", "种类", "风险级别", "进口检验检疫监管方式", "出口检验检疫监管方式"]


def cell(v, tag="td", attrs=""):
    a = (" " + attrs) if attrs else ""
    return f"<{tag}{a}>{v}</{tag}>"


def tr(cells, tag="tr"):
    return "  <%s>\n    %s\n  </%s>" % (tag, "\n    ".join(cells), tag)


def build_238():
    """页238: 正文 + 表(标题行 + 表头 + 6 数据行)。"""
    out = []
    out.append("<!-- source: Images/02制度文件/0239.jpg (split: 0238, 左半) -->")
    out.append("<!-- repaired: rotated=no, method=api-minimax, form=table, span=cross-page -->")
    out.append("")
    out.append("## 进出口饲料和饲料添加剂风险级别及检验检疫监管方式")
    out.append("")
    out.append("### 公告")
    out.append("")
    out.append("为进一步加强进出口饲料和饲料添加剂的风险管理, 规范进口和出口检验检疫监管方式, "
               "现对进出口饲料和饲料添加剂风险级别及检验检疫监管方式进行调整, "
               "将《进出口饲料和饲料添加剂风险级别及检验检疫监管方式》(原国家质检总局公告2014年第123号) "
               "附件中相关内容予以调整, 具体如下:")
    out.append("")
    out.append("附件:")
    out.append("")
    out.append("进出口饲料和饲料添加剂风险级别及检验检疫监管方式")
    out.append("")

    rows = []
    rows.append(tr([cell("进出口饲料和饲料添加剂风险级别及检验检疫监管方式", "th",
                         'colspan="5"')]))
    rows.append(tr([cell(h, "th") for h in HEAD]))

    # 类别 rowspan=6 (只有 类别 列是合并的)
    # 出口列**每行独立**(图上横线穿过该列, 一共 6 个独立格)
    cat = cell("动物源性饲料", "td", 'rowspan="6"')

    # 5 行: 种类(1) + 风险级别 + 进口方式
    simple = [
        ("饲料用活动物", "Ⅰ级", IMP_1),
        ("饲料用（含饵料用）冰鲜冷冻动物产品", "Ⅰ级", IMP_1),
        ("饲料用（含饵料用）水产品", "Ⅲ级", IMP_3),
        ("加工动物蛋白及油脂", "Ⅱ级", IMP_2),
    ]
    for i, (name, lvl, imp) in enumerate(simple):
        rows.append(tr([cat if i == 0 else "",
                        cell(name), cell(lvl), cell(imp), cell(EXP)]))
    # 宠物食品和咬胶 rowspan2, 带 3 级子列(生的宠物食品 / 其他)
    # 这一段的网格是 **6 格**: [种类=宠物食品和咬胶(r2)] [子类] [风险级别] [进口] [出口]
    rows.append(tr([cell("宠物食品和咬胶", "td", 'rowspan="2"'),
                    cell("生的宠物食品"), cell("Ⅰ级"), cell(IMP_1), cell(EXP)]))
    rows.append(tr([cell("其他"), cell("Ⅱ级"), cell(IMP_2), cell(EXP)]))

    # 去掉空 td
    def clean_rows(rs):
        o = []
        for r in rs:
            lines = [l for l in r.split("\n") if l.strip() != "<td></td>"]
            o.append("\n".join(lines))
        return o

    rows = clean_rows(rows)
    out.append("<table border=\"1\">")
    out.extend(rows)
    out.append("</table>")
    return "\n".join(out) + "\n"


def build_239():
    """页239: (续表) + 表头 + 11 数据行。"""
    out = []
    out.append("<!-- source: Images/02制度文件/0239.jpg (split: 0239, 右半) -->")
    out.append("<!-- repaired: rotated=no, method=api-minimax, form=table, span=cross-page -->")
    out.append("")
    out.append("（续表）")
    out.append("")

    rows = []
    rows.append(tr([cell(h, "th") for h in HEAD]))

    # ---- 类别 rowspan3: 饲料粮谷物
    # 这 3 行没有第 3 级子列, 种类列直接占满(不切)
    # 出口列**每行独立**(图上横线穿过该列)
    c1 = cell("饲料粮谷物", "td", 'rowspan="3"')
    rows.append(tr([c1, cell("饲料粮谷物"), cell("Ⅰ级"), cell(IMP_1), cell(EXP)]))
    rows.append(tr([cell("饲料用草籽"), cell("Ⅰ级"), cell(IMP_1), cell(EXP)]))
    rows.append(tr([cell("饲料类"), cell("Ⅱ级"), cell(IMP_2), cell(EXP)]))

    # ---- 类别 rowspan4: 植物源性饲料蛋白、糖蜜饼粕类
    # 组内 加工植物蛋白 那一支有第 3 级子列(来自TCK疫区的麦麸 / 其他),
    # 所以这一段是 **6 格**, 而 青贮料/植物粉末 的「种类」格要 **colspan=2**
    # 跨掉那个子列位(它们的左边界和 加工植物蛋白 对齐)。
    c2 = cell("植物源性饲料蛋白、糖蜜饼粕类", "td", 'rowspan="4"')
    k2 = cell("加工植物蛋白、糖蜜饼粕渣类", "td", 'rowspan="2"')
    rows.append(tr([c2, k2, cell("来自TCK疫区的麦麸"), cell("Ⅰ级"), cell(IMP_1), cell(EXP)]))
    rows.append(tr([cell("其他"), cell("Ⅱ级"), cell(IMP_2), cell(EXP)]))
    rows.append(tr([cell("青贮料", "td", 'colspan="2"'), cell("Ⅲ级"),
                    cell(IMP_3), cell(EXP)]))
    rows.append(tr([cell("植物粉末", "td", 'colspan="2"'), cell("Ⅲ级"),
                    cell(IMP_3), cell(EXP)]))

    # ---- 配合饲料: 类别+种类 横向合并 (colspan=2)
    rows.append(tr([cell("配合饲料", "td", 'colspan="2"'), cell("Ⅱ级"),
                    cell(IMP_2), cell(EXP)]))

    # ---- 类别 rowspan3: 饲料添加剂、添加剂预混合饲料
    # 这一组没有第 3 级子列
    c4 = cell("饲料添加剂、添加剂预混合饲料", "td", 'rowspan="3"')
    rows.append(tr([c4, cell("含动物源性成分"), cell("Ⅱ级"), cell(IMP_2), cell(EXP)]))
    rows.append(tr([cell("不含动物源性成分但含植物源性成分"),
                    cell("按所含的植物源性成分分级"),
                    cell("参照对应植物源性成分的监管方式"), cell(EXP)]))
    rows.append(tr([cell("其他"), cell("Ⅳ级"), cell(IMP_4), cell(EXP)]))

    def clean_rows(rs):
        o = []
        for r in rs:
            lines = [l for l in r.split("\n") if l.strip() != "<td></td>"]
            o.append("\n".join(lines))
        return o

    rows = clean_rows(rows)
    out.append("<table border=\"1\">")
    out.extend(rows)
    out.append("</table>")
    return "\n".join(out) + "\n"


def expand_rows(raws):
    """把 rowspan/colspan 展开, 返回每行实际占用的列数。

    坑 1: **不能直接数 <td> 个数** —— 有 rowspan 的行, 被跨掉的列由上一行的
    rowspan 单元格占据, 所以该行的 <td> 数天然少于 5。
    坑 2: **colspan 也要算** —— 一个 colspan=2 的格占 2 列。
    必须维护一个「占位」队列: 每行先补上上一行 rowspan 尚未到期的列。
    """
    pending = []          # [(rowspan_剩余, 列序号)]
    out = []
    for r in raws:
        cells = re.findall(r"<t[dh]([^>]*)>(.*?)</t[dh]>", r, re.S | re.I)
        # 上一行遗留的占位列
        occ = set()
        new_pending = []
        for rem, col in pending:
            # 坑: 这里必须是 `rem >= 1` 而不是 `rem > 1`。
            # pending 里存的是「还要往下占几行」: rowspan=2 的格在起始行存 1,
            # 表示**下一行仍被占住**。用 `rem > 1` 会把最后一行的占位漏掉,
            # 导致该行少算一列(实测 0238 第 8 行算成 4 列, 应为 5)。
            if rem >= 1:
                occ.add(col)
                new_pending.append((rem - 1, col))
        col = 0
        last = -1
        for attrs, _body in cells:
            while col in occ:
                col += 1
            cs = re.search(r'colspan\s*=\s*["\']?(\d+)', attrs, re.I)
            span = int(cs.group(1)) if cs else 1
            last = max(last, col + span - 1)
            rs = re.search(r'rowspan\s*=\s*["\']?(\d+)', attrs, re.I)
            if rs and int(rs.group(1)) > 1:
                for k in range(span):
                    new_pending.append((int(rs.group(1)) - 1, col + k))
            col += span
        pending = new_pending
        # 坑: 本行的总列数 = max(最后一个格子的右边界, 所有被 rowspan 占住的列)
        # 被占列可能排在**最后**一格之后(比如 出口列被上一行的 rowspan 占住),
        # 只看 last 会漏算。
        ncols = last + 1
        if occ:
            ncols = max(ncols, max(occ) + 1)
        out.append((ncols, None))
    return out


def check(txt, tag, nrows):
    """质量门: 展开 rowspan/colspan 后**每行列数一致**(允许 5 或 6, 因为
    加工植物蛋白 那一支有第 3 级子列), 且关键标签齐全。

    坑: 这张表**不是固定 5 列**。基础网格 5 列, 但 加工植物蛋白 组内多出
    一个第 3 级子列 -> 该段是 6 格。所以不能硬校验 ==5, 要校验**各行一致**。
    """
    errs = []
    m = re.search(r"<table.*?</table>", txt, re.S)
    if not m:
        return ["无表格"]
    tb = m.group(0)
    raws = re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S)
    if len(raws) != nrows:
        errs.append("行数 %d != %d" % (len(raws), nrows))
    widths = []
    for i, (ncols, _pl) in enumerate(expand_rows(raws)):
        widths.append(ncols)
    # 这张表的网格宽度是**变化的**:
    #   基础 5 列; 出现第 3 级子列的组是 6 列;
    #   用 colspan=2 跨掉子列位的行回到 5 列。
    # 所以不能要求「所有数据行等宽」, 只能要求每行宽度 ∈ {5,6}。
    data_w = set(widths[1:])
    if not data_w <= {5, 6}:
        errs.append("数据行列数异常: %s" % sorted(data_w))
    # 宽度必须与图一致。
    # 0238: 前 4 行 5 列; 宠物食品组 2 行 6 列(多一个第 3 级子列)
    if tag == "0238":
        if widths[1:] != [5, 5, 5, 5, 5, 6, 6]:
            errs.append("0238 宽度序列不符: %s" % widths[1:])
    if tag == "0239":
        # 饲料粮谷物3行=5; 加工植物蛋白2行=6(有第3级子列);
        # 青贮料/植物粉末=6(种类 colspan=2 跨子列位, 但整段网格仍是 6);
        # 配合饲料(colspan=2 跨类别+种类)=5; 饲料添加剂组 3 行=5
        exp239 = [5, 5, 5, 6, 6, 6, 6, 5, 5, 5, 5]
        if widths[1:] != exp239:
            errs.append("0239 宽度序列不符: %s != %s" % (widths[1:], exp239))
    for k in (["动物源性饲料", "宠物食品和咬胶", "生的宠物食品", "加工动物蛋白及油脂"]
              if tag == "0238" else
              ["饲料粮谷物", "植物源性饲料蛋白", "TCK", "配合饲料",
               "饲料添加剂", "按所含的植物源性成分分级", "青贮料", "植物粉末"]):
        if k not in tb:
            errs.append("缺标签:" + k)
    # 类别列不能被误填成种类名。
    # 注意: **不能只看每行第一个 <td>** —— 类别列有 rowspan 时,
    # 后续行的第一个 td 是「种类」格(类别列被上一行的 rowspan 占住)。
    # 正确做法: 展开 rowspan 后再取**真正位于第 0 列**的单元格。
    if tag == "0238":
        for i, (ncols, _pl) in enumerate(expand_rows(raws)):
            r = raws[i]
            cells = re.findall(r"<t[dh]([^>]*)>(.*?)</t[dh]>", r, re.S | re.I)
            # 重算本行第 0 列的格子
            occ = set()
            for rem, col in _pending_before(raws, i):
                if rem >= 1:
                    occ.add(col)
            first = None
            c = 0
            for attrs, body in cells:
                while c in occ:
                    c += 1
                if c == 0:
                    first = re.sub(r"<[^>]+>", "", body).strip()
                    break
                cs = re.search(r'colspan\s*=\s*["\']?(\d+)', attrs, re.I)
                c += int(cs.group(1)) if cs else 1
            if first and first in ("饲料用活动物", "饲料", "配合饲料", "饲料粮谷物",
                                   "青贮料", "植物粉末", "加工动物蛋白及油脂",
                                   "宠物食品和咬胶"):
                errs.append("第%d行类别列疑似误填种类: %s" % (i + 1, first))
    return errs


def _pending_before(raws, upto):
    """返回第 upto 行之前累积的 rowspan 占位队列。"""
    pending = []
    for r in raws[:upto]:
        cells = re.findall(r"<t[dh]([^>]*)>(.*?)</t[dh]>", r, re.S | re.I)
        occ = set()
        new_pending = []
        for rem, col in pending:
            if rem >= 1:
                occ.add(col)
                new_pending.append((rem - 1, col))
        col = 0
        for attrs, _body in cells:
            while col in occ:
                col += 1
            cs = re.search(r'colspan\s*=\s*["\']?(\d+)', attrs, re.I)
            span = int(cs.group(1)) if cs else 1
            rs = re.search(r'rowspan\s*=\s*["\']?(\d+)', attrs, re.I)
            if rs and int(rs.group(1)) > 1:
                for k in range(span):
                    new_pending.append((int(rs.group(1)) - 1, col + k))
            col += span
        pending = new_pending
    return pending


def main():
    for tag, builder, nrows in (("0238", build_238, 8), ("0239", build_239, 12)):
        txt = builder()
        errs = check(txt, tag, nrows)
        out = os.path.join(OUTDIR, tag + ".md")
        if errs:
            print("!! %s 质量门未过: %s" % (tag, "; ".join(errs[:6])))
            continue
        with open(out, "w", encoding="utf-8") as f:
            f.write(txt)
        tb = re.search(r"<table.*?</table>", txt, re.S).group(0)
        nrows_act = len(re.findall(r"<tr[^>]*>", tb))
        print("OK %s -> %s (%d 行, %d 字节)" %
              (tag, os.path.relpath(out, REPO), nrows_act, len(txt.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
