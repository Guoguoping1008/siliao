#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0248/0249。

【页面映射】
Images/02制度文件/0249.jpg = 书第 248(左) + 249(右) 页
  -> 0248 = 左半 (cut ≈ 2050~2100, 书脊实测 x≈2020)
  -> 0249 = 右半

【原状态(都错)】
0248.md  11269B —— **幻觉出的 3 列表格, 30+ 个空行**, 而且表尾被
                   运行页眉污染成 `</法规`(饲料法规文件)。
                   **页248 上根本没有表格**, 只有中英文正文。
0249.md   677B  —— 产品信息表只出了 4 列但**丢了表头的中英文**,
                   且第一列的 rowspan 丢了。

【真值(目视逐格核对)】
页248 (附件2 参考样式, **无表**):
  附件2
  No. 一××××××
  饲料和饲料添加剂产品自由销售证明
  Certificate of Free Sale
  (参考样式)
  正文: 依据中国《饲料和饲料添加剂管理条例》规定,××省(自治区、直辖市)××厅(局、委、办)
        负责饲料和饲料添加剂的监督管理工作。兹证明××××××(生产企业名称)
        (生产地址: ××××××××)已依法取得饲料和饲料添加剂生产许可
        (或依法不需要办理饲料和饲料添加剂生产许可)。产品生产所用原料在中国相关法律
        允许范围内,允许在中国自由销售并出口到××(目的国)。(如果出口目的地为港澳
        地区,可表述为: 允许在中国内地自由销售并销售香港/澳门/台湾)。
  No. 一××××××
  Certificate of Free Sale
  (Sample)
  正文(英): According to the Regulations on the Administration of Feed and Feed
        Additives of P. R. China, ×××××× (发证单位英文名称) is responsible for the
        supervision and management of feed and feed additives. This is to certify
        that ×××××× (生产企业英文名称) located at ×××××× (英文生产地址) has obtained
        the production license of feed and feed additives in accordance with the law
        (or is not required to register the production license of feed and feed
        additives in accordance with the law). The ingredients of the product(s)
        comply with the relevant laws and regulations of China. The product(s)
        are permitted to be freely sold in China and sold to ×× (目的国).
        (如果出口目的地为港澳台地区, 可表述为 The product(s) is/are permitted to be
        freely sold in Chinese inland and sold to Hong Kong/Macao/Taiwan.)

页249:
  产品信息表 (caption)
  表头: 生产许可证号 / Production License Number
        产品名称 / Name of the Product
        产品类别 / Product Classification
        产品批准文号 / Product Approval Document Number
  数据行: 4 行全空; **第一列 rowspan=4**(图上该列下方无横线穿过)
  中文声明: 本证明仅确认该产品生产的合法合规性,产品质量由生产企业承担主体责任。
  英文声明: This certificate only confirms the legality and compliance of the
           production of the product(s). The manufacturer is responsible for
           the product(s) quality.
  签署块: Director: ______ (签字)
          单位名称: ______
          单位英文名称: ______
          签署日期: ______ (英文格式)
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(REPO, "minimax", "02制度文件", "03_（三）进口登记和出口服务",
                      "43_农业农村部办公厅关于办理饲料和饲料添加剂产品自由销售证明的通知")

ZH_DISCLAIMER = "本证明仅确认该产品生产的合法合规性,产品质量由生产企业承担主体责任。"
EN_DISCLAIMER = ("This certificate only confirms the legality and compliance of "
                 "the production of the product(s). The manufacturer is responsible "
                 "for the product(s) quality.")

ZH_BODY = (
    "依据中国《饲料和饲料添加剂管理条例》规定,××省(自治区、直辖市)××厅(局、委、办)"
    "负责饲料和饲料添加剂的监督管理工作。兹证明××××××(生产企业名称)"
    "(生产地址: ××××××××)已依法取得饲料和饲料添加剂生产许可"
    "(或依法不需要办理饲料和饲料添加剂生产许可)。产品生产所用原料在中国相关法律"
    "允许范围内,允许在中国自由销售并出口到××(目的国)。(如果出口目的地为港澳"
    "地区,可表述为: 允许在中国内地自由销售并销售香港/澳门/台湾)。"
)

EN_BODY = (
    "According to the Regulations on the Administration of Feed and Feed "
    "Additives of P. R. China, ×××××× (发证单位英文名称) is responsible for the "
    "supervision and management of feed and feed additives. This is to certify "
    "that ×××××× (生产企业英文名称) located at ×××××× (英文生产地址) has obtained "
    "the production license of feed and feed additives in accordance with the law "
    "(or is not required to register the production license of feed and feed "
    "additives in accordance with the law). The ingredients of the product(s) "
    "comply with the relevant laws and regulations of China. The product(s) "
    "are permitted to be freely sold in China and sold to ×× (目的国). "
    "(如果出口目的地为港澳台地区, 可表述为 The product(s) is/are permitted to be "
    "freely sold in Chinese inland and sold to Hong Kong/Macao/Taiwan.)"
)

HEAD = [
    ("生产许可证号", "Production License Number"),
    ("产品名称", "Name of the Product"),
    ("产品类别", "Product Classification"),
    ("产品批准文号", "Product Approval Document Number"),
]


def build_248():
    """页248: 附件2 参考样式, 中英文正文, **无表格**。"""
    return "\n".join([
        "<!-- source: Images/02制度文件/0249.jpg (split: 0248, 左半) -->",
        "<!-- repaired: rotated=no, method=api-minimax, form=prose, no-table -->",
        "",
        "附件2",
        "",
        "No. 一××××××",
        "",
        "**饲料和饲料添加剂产品自由销售证明**",
        "",
        "**Certificate of Free Sale**",
        "",
        "（参考样式）",
        "",
        ZH_BODY,
        "",
        "No. 一××××××",
        "",
        "**Certificate of Free Sale**",
        "",
        "(Sample)",
        "",
        EN_BODY,
        "",
    ])


def build_249():
    """页249: 产品信息表(4 列, 第一列 rowspan=4) + 中英文声明 + 签署块。"""
    rows = []
    # 标题行(表 caption) —— 用 <caption> 语义化
    rows.append("  <caption>产品信息表</caption>")
    # 表头: 中英双语, 换行用 <br>
    hdr = "".join(
        '<th>%s<br>%s</th>' % (zh, en) for zh, en in HEAD)
    rows.append("  <tr>\n    %s\n  </tr>" % hdr)
    # 4 个空数据行; 第一列 rowspan=4
    for i in range(4):
        cells = []
        if i == 0:
            cells.append('<td rowspan="4"></td>')
        cells.append("<td></td>")
        cells.append("<td></td>")
        cells.append("<td></td>")
        rows.append("  <tr>\n    %s\n  </tr>" % "\n    ".join(cells))

    out = [
        "<!-- source: Images/02制度文件/0249.jpg (split: 0249, 右半) -->",
        "<!-- repaired: rotated=no, method=api-minimax, form=table, blank-form -->",
        "",
        "<table border=\"1\">",
    ] + rows + [
        "</table>",
        "",
        ZH_DISCLAIMER,
        "",
        EN_DISCLAIMER,
        "",
        "Director: ______________________________　　（签字）",
        "",
        "单位名称: ______________________________",
        "",
        "单位英文名称: ______________________________",
        "",
        "签署日期: ______________________________　　（英文格式）",
        "",
    ]
    return "\n".join(out)


def expand_rows(raws):
    """把 rowspan/colspan 展开, 返回每行实际占用的列数。"""
    pending = []
    out = []
    for r in raws:
        cells = re.findall(r"<t[dh]([^>]*)>(.*?)</t[dh]>", r, re.S | re.I)
        occ = set()
        new_pending = []
        for rem, col in pending:
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
        ncols = last + 1
        if occ:
            ncols = max(ncols, max(occ) + 1)
        out.append((ncols, None))
    return out


def check(txt, tag):
    errs = []
    if tag == "0238":
        pass
    if tag == "0248":
        if "<table" in txt:
            errs.append("页248 不该有表格")
        for k in ("附件2", "Certificate of Free Sale", "饲料和饲料添加剂管理条例",
                  "生产许可证号" if False else "饲料和饲料添加剂产品自由销售证明",
                  "目的国", "Hong Kong/Macao/Taiwan", "According to the Regulations"):
            if k not in txt:
                errs.append("缺:" + k[:20])
        if "法规" in txt:
            errs.append("疑似运行页眉污染")
        # 正文不能太短(幻觉成一行)
        if len(txt) < 700:
            errs.append("正文过短(%d), 疑似漏抄" % len(txt))
    if tag == "0249":
        m = re.search(r"<table.*?</table>", txt, re.S)
        if not m:
            return ["无表格"]
        tb = m.group(0)
        raws = re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S)
        if len(raws) != 5:
            errs.append("行数 %d != 5" % len(raws))
        widths = [w for w, _ in expand_rows(raws)]
        if widths != [4, 4, 4, 4, 4]:
            errs.append("宽度序列 %s != [4,4,4,4,4]" % widths)
        for zh, en in HEAD:
            if zh not in tb or en not in tb:
                errs.append("缺表头:%s" % zh)
        if 'rowspan="4"' not in tb:
            errs.append("第一列缺 rowspan=4")
        for k in (ZH_DISCLAIMER, EN_DISCLAIMER, "Director", "单位名称",
                  "单位英文名称", "签署日期"):
            if k not in txt:
                errs.append("缺:" + k[:20])
    return errs


def main():
    for tag, builder in (("0248", build_248), ("0249", build_249)):
        txt = builder()
        errs = check(txt, tag)
        out = os.path.join(OUTDIR, tag + ".md")
        if errs:
            print("!! %s 质量门未过: %s" % (tag, "; ".join(errs[:6])))
            continue
        with open(out, "w", encoding="utf-8") as f:
            f.write(txt)
        print("OK %s -> %s (%d 字节)" %
              (tag, os.path.relpath(out, REPO), len(txt.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
