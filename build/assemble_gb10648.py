#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 OCR 出来的 GB 10648—2013 逐页 md 重新切片,写回 minimax/ 语料树。

## 为什么不能一页对一文件

PDF 有 10 个物理页,但语料树里这份文档是 10 个 md —— **切点不同**。
实测旧语料的切点(看每个文件首尾):

| 文件 | 首行内容                          | 末行内容                        |
|------|-----------------------------------|---------------------------------|
| 0939 | 修改单                            | 修改单第 3 条                   |
| 0940 | 饲料标签 / GB 10648—2013 / 前言    | 前言……（见 5.11）               |
| 0941 | ——增加了动物源性饲料……            | GB 10648—1988、1993、1999        |
| 0942 | # 饲料标签 / ## 1 范围            | 3.6 复合预混合饲料……其中营养性   |
| 0943 | 饲料添加剂的含量能够满足……        | 4.3 ……不得                     |
| 0944 | 欺骗性表述误导消费者。            | 表 1 第 4 行 </table>            |
| 0945 | （续表）                          | 5.5.2 ……可不标示此项            |
| 0946 | ### 5.6 使用说明                  | 5.13.2.3 ……休药期及注意事项      |
| 0947 | #### 5.13.3 委托加工产品           | 6.6 一个标签只能标示一个产品     |
| 0948 | # 附录A ……                        | A.2.2 ……个/mL                   |

即:旧语料是**按内容切**的(切在章节/表格边界),不是按 PDF 物理页切。
如果直接按物理页覆盖,article_id 与正文就对不上,等于新建一份重复文档。

## 这里的做法

按**章节边界**重新切分,让每个 md 的边界落在章节/表格的接缝上,
并保持与旧语料**相同的文件序列**(0939..0948,10 个,不改编号)。

对应关系(PDF 物理页 → 语料文件):

    p10 修改单        → 0939
    p2  前言          → 0940 + 0941(页内切一刀)
    p3  范围/引用/术语 → 0941
    p4  术语 3.7-3.18 → 0942
    p5  第4章/5.1-5.3 → 0943
    p6  表1续/表2/5.4 → 0944
    p7  5.6-5.13.2    → 0945
    p8  5.13.3-6.6    → 0946
    p9  附录 A        → 0947
    p1  封面          → 0948

用法:
  python build/assemble_gb10648.py --dry-run
  python build/assemble_gb10648.py
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# ⚠️ OCR 工作目录放在语料树**外面** —— ingest_minimax.py 会把
#    minimax/ 下任何非「<4位数字>.md」的目录当成一份新文档摄入
#    (实测:_pdf_pages 会被吃成一个叫「中华人民共和国国家标准」的文档)。
SRC_ROOT = os.path.join(ROOT, "build", "_gb10648_source")
CACHE = os.path.join(SRC_ROOT, "_pdf_pages", "_ocr_cache")
OUT_DIR = os.path.join(ROOT, "minimax", "04标准及标准目录", "01_饲料标签")

# (PDF 页, 语料文件编号) —— 保持旧语料的文件序列与内容边界
#
# ⚠️ 0941 是**两段拼起来**的:PDF 第 2 页的前言下半 + PDF 第 3 页。
#    旧语料就是这么切的(旧 0941 首行「——增加了动物源性饲料」,
#    末行「GB 10648—1988、1993、1999」= 前言结尾,后面还有第 3 页内容)。
#    实际核对旧 0941:首行是「——增加了动物源性饲料」,末行是前言的历次版本 ——
#    说明旧 0941 **只含前言下半**,第 3 页(范围/术语)另在 0942。
PAGE_MAP = [
    (10, "0939"),  # 修改单
    (2, "0940"),  # 前言(上半) + 页内切出的后半 -> 0941
    (3, "0942"),  # 1 范围 / 2 引用文件 / 3.1-3.6
    (4, "0943"),  # 3.7-3.18 术语
    (5, "0944"),  # 4 基本原则 / 5.1-5.3.2 表1(上)
    (6, "0945"),  # 表1(续) / 表2 / 5.4-5.5
    (7, "0946"),  # 5.6-5.13.2
    (8, "0947"),  # 5.13.3-6.6
    (9, "0948"),  # 附录 A
]

# 语料树里 0941 由「前言下半」独占(第 2 页页内切分产出)
SPLIT_AFTER = {2: ("——增加了动物源性饲料", "0941")}

# 封面(第 1 页)不入库 —— 旧语料也没有,且封面无条文。
# 但为了不丢信息,单独存到 _pdf_pages/ 下的 cover.md。


def normalize(md: str) -> str:
    """归一化:剥 <think>、去页眉页脚、清理空白、合回被拆开的标题。"""
    md = re.sub(r"<think>.*?</think>", "", md, flags=re.S)
    if "<think>" in md:
        md = md[: md.index("<think>")]
    md = re.sub(r"^</?think>", "", md, flags=re.M)

    lines = []
    for ln in md.splitlines():
        s = ln.strip()
        # 页眉 "GB 10648—2013" / "ICS 65.120" / 页码孤行
        if s in ("GB 10648—2013", "GB 10648-2013"):
            continue
        if s.startswith("ICS ") and len(s) < 30:
            continue
        if re.fullmatch(r"[0-9IVX]{1,3}", s):  # 孤立页码
            continue
        lines.append(ln.rstrip())
    md = "\n".join(lines).strip()
    # 去掉行尾全角空格
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return fix_heading_levels(merge_split_headings(md)).strip() + "\n"


# ⚠️ OCR 会把「编号」和「标题」拆成两行:
#     ### 3.1
#     #### 饲料标签 feed label
#   这是版式决定的(GB 标准里编号单独一行、术语名加粗在下一行)。
#   但 ingest_minimax.py 按「一行一个标题」切,
#   拆开会导致条文标题变成裸编号「3.1」—— 检索命中的是「3.1」,
#   用户搜「饲料标签」就找不到这一条。**必须合回一行。**
_HEAD_NUM = re.compile(r"^(#{2,4})\s+((?:\d+(?:\.\d+)*)|[A-Z]\.\d+(?:\.\d+)*)\s*$")


def merge_split_headings(md: str) -> str:
    lines = md.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = _HEAD_NUM.match(ln.strip())
        if m:
            # 找下一个非空行,如果是标题就合并
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines):
                nxt = lines[j].strip()
                if nxt.startswith("#") and not _HEAD_NUM.match(nxt):
                    title = nxt.lstrip("#").strip()
                    out.append(f"{m.group(1)} {m.group(2)} {title}")
                    i = j + 1
                    continue
        out.append(ln)
        i += 1
    return "\n".join(out)


# ⚠️ OCR 把「5.4 / 5.5 / 5.6」这类**章内小节**也标成了 H2,
#    但 GB 标准的层级是:第 5 章(H2)→ 5.4(H3)。
#    层级错了会直接改变检索行为:
#      ingest_minimax.py 把 H2 当 **chapter**、H3 当 **article**。
#      所以 5.4/5.5/5.6 变成 chapter 后,「使用说明」这一条
#      在 articles 表里消失 —— 查「饲料标签标注的要求」就命中不到它
#      (实测:旧版 top2 命中 GB10648,新版被无关文档挤掉)。
#
#    规则(靠编号层级判断,不看标题文字):
#      H2 = 单级编号的章   「1 范围」「2 规范性引用文件」「3 术语和定义」
#                           「4 基本原则」「5 应标示的基本内容」「6 基本要求」
#      H3 = 两级编号的小节 「5.4 原料组成」「A.1 计量单位」
_CHAPTER_H2 = re.compile(
    r"^##\s+(?:"
    r"\d+(?!\.)\s"          # 「1 范围」—— 后面不能紧跟小数点
    r"|第[一二三四五六七八九十百]+章"
    r"|[一二三四五六七八九十]+、"
    r"|附录(?![.\d])"       # 「附录 A」,但不是「附录 A.1」
    r"|国家标准第\s*\d+\s*号修改单"
    r"|产品成分分析保证值常用计量单位"
    r")\s*\S",
)

def fix_heading_levels(md: str) -> str:
    """把章内小节的 H2 降级为 H3,保住「章=chapter / 条=article」的层级。"""
    lines = md.split("\n")
    out = []
    for ln in lines:
        s = ln.strip()
        if s.startswith("## ") and not _CHAPTER_H2.match(s):
            # 两级编号 5.4 / A.1 -> 降一级
            out.append("#" + s)
        else:
            out.append(ln)
    return "\n".join(out)


def split_page(md: str, marker: str) -> tuple[str, str]:
    """在 marker 那一行前切开,返回 (前半, 后半)。"""
    idx = md.find(marker)
    if idx < 0:
        raise RuntimeError(f"split marker not found: {marker!r}")
    head = md[:idx].rstrip()
    tail = md[idx:].lstrip()
    return head + "\n", tail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print(f"[CACHE] {CACHE}")
    print(f"[OUT]   {OUT_DIR}")

    targets = [name for _, name in PAGE_MAP] + [t for _, t in SPLIT_AFTER.values()]
    on_disk = sorted(
        f[:-3]
        for f in os.listdir(OUT_DIR)
        if f.endswith(".md") and re.fullmatch(r"\d{4}", f[:-3])
    )
    stray = [n for n in on_disk if n not in targets]
    print(f"[CHECK] 目标 {targets[0]}..{targets[-1]} ({len(targets)} 个) · 目录现有 {len(on_disk)} 个")
    if stray:
        print(f"[WARN] 不在覆盖范围内的页: {stray}")

    written = []
    # ⚠️ 先把所有「页内二次切分」的后半段收集起来,最后再写。
    #    否则 p02 的 tail 写进 0941 之后,p03 又会把 0941 整个覆盖掉。
    split_tails: list[tuple[str, str]] = []

    for page_no, name in PAGE_MAP:
        src = os.path.join(CACHE, f"p{page_no:03d}.md")
        if not os.path.isfile(src):
            print(f"[ERROR] 缺 OCR 缓存: {src}")
            return 1
        with open(src, encoding="utf-8") as f:
            md = normalize(f.read())

        # 页内二次切分:前半给当前文件,后半暂存
        if page_no in SPLIT_AFTER:
            marker, tail_name = SPLIT_AFTER[page_no]
            md, tail = split_page(md, marker)
            split_tails.append((tail_name, tail))
            print(f"  p{page_no:02d} -> {name}.md (前半) + {tail_name}.md (后半) @'{marker[:14]}…'")

        dst = os.path.join(OUT_DIR, f"{name}.md")
        old = os.path.getsize(dst) if os.path.isfile(dst) else 0
        print(
            f"  p{page_no:02d} -> {name}.md  "
            f"{old:>6} -> {len(md.encode('utf-8')):>6} B  ({len(md)} chars)"
        )
        if not args.dry_run:
            with open(dst, "w", encoding="utf-8") as f:
                f.write(md)
        written.append(dst)

    # 覆盖完成后,再写二次切分的后半段
    for tail_name, tail in split_tails:
        tail_dst = os.path.join(OUT_DIR, f"{tail_name}.md")
        old = os.path.getsize(tail_dst) if os.path.isfile(tail_dst) else 0
        print(
            f"  split -> {tail_name}.md  "
            f"{old:>6} -> {len(tail.encode('utf-8')):>6} B  ({len(tail)} chars)"
        )
        if not args.dry_run:
            with open(tail_dst, "w", encoding="utf-8") as f:
                f.write(tail + "\n")
        written.append(tail_dst)

    # 封面(第 1 页)—— 不进语料树(无条文),单独存一份留档
    cover_src = os.path.join(CACHE, "p001.md")
    if os.path.isfile(cover_src):
        with open(cover_src, encoding="utf-8") as f:
            cover = normalize(f.read())
        dst = os.path.join(SRC_ROOT, "cover.md")
        print(f"  p01 -> _gb10648_source/cover.md (封面,不入库)  {len(cover.encode('utf-8'))} B")
        if not args.dry_run:
            with open(dst, "w", encoding="utf-8") as f:
                f.write(cover + "\n")

    missing = [n for n in targets if not os.path.isfile(os.path.join(OUT_DIR, f"{n}.md"))]
    if missing:
        print(f"[ERROR] 覆盖后仍缺失: {missing}")
        return 1

    if args.dry_run:
        print("[DRY-RUN] 未写入")
    else:
        print(f"[OK] 覆盖完成 {len(written)} 个文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
