"""
Text-based 切分器(GB/T 阿拉伯数字体系):
支持《饲料和饲料添加剂靶动物有效性评价试验指南(试行)》这类技术标准的章节体例:
  1   范围                → 一级标题 # (顶级章节)
  1.1 ...                → 二级标题 ## (节)
  1.1.1 ...              → 三级标题 ### (子节)
  附录 X                 → 附录章节
  表 1 / 附表 1          → 表格标记(front-matter, 不切分)
  (续表)                  → 表格续表标记

不依赖物理坐标(法规/标准正文里"4.2.1 → 4.2.2"物理间距跟段内换行差不多,
物理切分不可靠), 直接按文本锚点反切。

输入:
  data/markdown/<doc_id>/merged.md
  (page_joiner.py 的产物, 已合并多页 + 去掉页眉/页码)

输出:
  data/markdown/<doc_id>/sections/<section_id>.md    # 单个 section markdown
  data/markdown/<doc_id>/sections.json               # 索引 (按 section 粒度切)
  data/markdown/<doc_id>/chapters/<chapter_id>.md    # 一级章节整块 markdown
  data/markdown/<doc_id>/chapters.json               # 一级章节索引

chapter_id / section_id 都加 doc_id 前缀,避免多 doc 灌库主键冲突。

用法:
  python build/ocr/article_splitter_ar.py data/markdown/feed-trial-guideline-2023/merged.md \\
      feed-trial-guideline-2023 data
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


# 阿拉伯数字章节体系
# - TOP_CHAPTER_RE:   1 / 2 / 3       (独立行, 后面是 1-30 字标题)
# - SECTION_RE:       1.1 / 1.1.1     (独立行)
# - APPENDIX_RE:      附录 A / 附录 B (顶级, 等价于一级章节)
# 容忍数字与中文之间 **0 个或多个空格** (OCR 经常把"3试验方案"挤在一起)
TOP_CHAPTER_RE = re.compile(r"^(\d{1,2})[\s\u3000]*([\u4e00-\u9fff][\u4e00-\u9fff、（）()A-Za-z\s]{0,28})$")
SECTION_RE = re.compile(r"^(\d{1,2}\.\d{1,2}(?:\.\d{1,2})?)[\s\u3000]*([\u4e00-\u9fff][\u4e00-\u9fff、（）()A-Za-z\s]{0,28})$")
APPENDIX_RE = re.compile(r"^附录\s*([A-ZＡ-Ｚ])\s*(.*?)$")

# 表格标记(不切分, 写到 front-matter)
TABLE_HEADER_RE = re.compile(r"^(表|附表)\s*\d+\b")
TABLE_CONT_RE = re.compile(r"^\(?续表\)?\s*$")

# 排除: 标题不能以这些标点结尾(冒号 / 逗号 / 句号 / 分号 多数是正文片段)
TITLE_BAD_ENDINGS = ("。", "，", ",", ".", ";", "；", "!", "?", "：", ":", "/", "(", "（", ")", "）", "的")

# 排除: 标题不能以这些副词 / 动词开头(说明是正文片段)
TITLE_BAD_PREFIXES = (
    "应", "可", "不", "为", "对", "在", "等", "也", "如", "若", "当", "由",
    "从", "向", "与", "和", "或", "但", "而", "且", "其", "这", "那", "其",
    "以", "使", "让", "给", "把", "被", "比", "按", "依", "根", "据",
)

# 顶级章节白名单关键词 (GB/T 类标准的常见一级章节词)
# 表格里的描述如 "3 月龄" / "6 月龄或以上" / "8 周" 不会包含这些词
TOP_CHAPTER_KEYWORDS = (
    "范围", "原则", "方案", "方法", "报告", "附录",
    "要求", "结果", "定义", "术语", "分类", "内容",
    "程序", "对象", "指标", "参考文献", "材料", "设备",
    "步骤", "条件", "规范", "判定", "评价", "评估",
    "适用", "前言", "引言", "目的", "总则", "附则",
)


def _is_section_header(line: str) -> tuple[str, str, int] | None:
    """返回 (section_number, title, level) 或 None
    level: 1=top chapter, 2=section, 3=subsection

    判定规则:
    1. 必须以阿拉伯数字章节号开头
    2. 标题 1-30 字
    3. 标题不以句末标点 / "的" 结尾(说明跟正文拼一起)
    4. 标题不以副词/介词开头(说明跟正文拼一起)
    """
    s = line.strip()
    if not s:
        return None

    # 附录 (顶级)
    m = APPENDIX_RE.match(s)
    if m:
        letter = m.group(1)
        title = m.group(2).strip()
        if 0 < len(title) <= 30 and not title.endswith(TITLE_BAD_ENDINGS):
            return (f"附录{letter}", title, 1)

    # 节/子节 (X.Y 或 X.Y.Z)
    m = SECTION_RE.match(s)
    if m:
        num = m.group(1)
        title = m.group(2).strip()
        # 排除正文片段
        if (
            0 < len(title) <= 30
            and not title.endswith(TITLE_BAD_ENDINGS)
            and not title.startswith(TITLE_BAD_PREFIXES)
            # 排除"4.2.2以及..."这类被拼一起的
            and "以及" not in title[:4]
            and "应" not in title[:2]
            and "。" not in title  # 正文含句号
        ):
            level = num.count(".") + 1
            return (num, title, level)

    # 顶级章节 (1 / 2 / 3)
    m = TOP_CHAPTER_RE.match(s)
    if m:
        num = m.group(1)
        title = m.group(2).strip()
        # 顶级章节特殊处理:
        # 1. 数字部分 1-9 (GB/T 一般 1-9 章)
        # 2. 标题 1-20 字
        # 3. **必须包含白名单关键词** (排除 "3 月龄" / "6 月龄" / "8 周" 等表格描述)
        if (
            num.isdigit() and 1 <= int(num) <= 9
            and 0 < len(title) <= 20
            and not title.endswith(TITLE_BAD_ENDINGS)
            and not title.startswith(TITLE_BAD_PREFIXES)
            and "." not in title
            and "。" not in title
            and any(kw in title for kw in TOP_CHAPTER_KEYWORDS)
        ):
            return (num, title, 1)

    return None


def _line_height_hint(line: str) -> int:
    """章节标题加粗提示(用于下游 markdown 渲染)
    top chapter: '#', section: '##', subsection: '###'
    """
    return 0  # placeholder, 真正分配在 write 时


def find_section_anchors(md_text: str) -> list[dict]:
    """扫描整段文本, 返回所有 section 锚点
    [{number, title, level, char_pos}, ...]
    按出现顺序
    """
    anchors = []
    char_pos = 0
    for ln in md_text.splitlines():
        res = _is_section_header(ln)
        if res:
            num, title, level = res
            # 跳过"前言"等非阿拉伯数字行
            anchors.append({
                "number": num,
                "title": title,
                "level": level,
                "char_pos": char_pos,
                "raw_line": ln.strip(),
            })
        char_pos += len(ln) + 1  # +1 for \n
    return anchors


def write_sections(
    doc_id: str,
    md_text: str,
    out_root: Path,
) -> tuple[list[dict], list[dict]]:
    """输出 sections.json + sections/<id>.md + chapters/<id>.md + chapters.json

    返回 (sections, chapters)
    - sections: 所有 1.x / 1.x.x 粒度的切片 (含顶级 chapter 当作 section[0])
    - chapters: 顶级 chapter 聚合 (含附录)
    """
    md_dir = out_root / "markdown" / doc_id
    sec_dir = md_dir / "sections"
    chap_dir = md_dir / "chapters"
    sec_dir.mkdir(parents=True, exist_ok=True)
    chap_dir.mkdir(parents=True, exist_ok=True)

    anchors = find_section_anchors(md_text)
    if not anchors:
        print(f"[WARN] {doc_id}: 0 章节锚点, 不切分")
        return [], []

    # doc_id 短前缀
    doc_prefix = doc_id.replace("-", "")[:3]

    # 顶级 chapter 列表 (level=1)
    # **这是合订本**(4 部不同动物的试验指南), 同 number 的顶级 chapter 会在
    # char_pos 跨度大时再次出现(每部独立的 "1适用范围"/"2基本原则"/"3试验方案"...)
    # 按 char_pos 间距分组: 同 number 间隔 > 2000 字符视为新的一部, 不到则视为误识别(表格里的描述)
    seen_top_numbers: set[str] = set()
    top_chapter_anchors: list[dict] = []
    TOP_CHAPTER_MIN_GAP = 2000  # 字符数, 约 2-3 页 OCR 文本

    for a in anchors:
        if a["level"] != 1:
            continue
        num = a["number"]
        pos = a["char_pos"]
        # 找上一个同 number 的 anchor
        last_pos = -TOP_CHAPTER_MIN_GAP  # 第一次强制通过
        for prev in reversed(top_chapter_anchors):
            if prev["number"] == num:
                last_pos = prev["char_pos"]
                break
        if pos - last_pos < TOP_CHAPTER_MIN_GAP:
            # 距离上一个同 number 太近, 视为误识别(表格里的描述)
            continue
        top_chapter_anchors.append(a)

    if not top_chapter_anchors:
        print(f"[WARN] {doc_id}: 无顶级 chapter")
        return [], []

    # ============ sections.json (按 section 粒度切) ============
    # 粒度: 顶级 chapter 也算一个 section, 包含到下一级 chapter 之间的所有内容
    # 节/子节也独立成 section
    sections: list[dict] = []
    section_counter = 0

    # 把所有 anchors 按 char_pos 顺序处理, 切片到下一个 anchor
    for idx, anchor in enumerate(anchors):
        section_counter += 1
        next_pos = anchors[idx + 1]["char_pos"] if idx + 1 < len(anchors) else len(md_text)
        body = md_text[anchor["char_pos"]:next_pos].strip()

        sid = f"{doc_prefix}_sec{section_counter:03d}"

        # 检测该 section 是否含表格
        has_table = bool(TABLE_HEADER_RE.search(body) or TABLE_CONT_RE.search(body))

        # 找所属顶级 chapter
        ch_idx = None
        for ci, ca in enumerate(top_chapter_anchors):
            if ca["char_pos"] <= anchor["char_pos"]:
                ch_idx = ci
            else:
                break
        belongs_to_chapter_num = top_chapter_anchors[ch_idx]["number"] if ch_idx is not None else "0"

        section_meta = {
            "section_id": sid,
            "number": anchor["number"],
            "title": anchor["title"],
            "level": anchor["level"],
            "doc_id": doc_id,
            "belongs_to_chapter": belongs_to_chapter_num,
            "has_table": has_table,
            "char_pos": anchor["char_pos"],
        }
        sections.append(section_meta)

        # section markdown (含 front-matter)
        # level 决定 # / ## / ###
        md_level = "#" * anchor["level"]
        meta = (
            f"<!-- doc_id: {doc_id} · section_id: {sid} · "
            f"chapter: {belongs_to_chapter_num} · "
            f"number: {anchor['number']} · level: {anchor['level']} · "
            f"has_table: {str(has_table).lower()} -->\n\n"
        )
        section_md = f"{meta}{md_level} {anchor['number']} {anchor['title']}\n\n{body}"
        (sec_dir / f"{sid}.md").write_text(section_md, encoding="utf-8")

    # ============ chapters.json (顶级 chapter 聚合) ============
    chapters: list[dict] = []
    for ci, ca in enumerate(top_chapter_anchors):
        # 找这个 chapter 下的所有 sections (anchor char_pos 落在区间内)
        next_ca = top_chapter_anchors[ci + 1] if ci + 1 < len(top_chapter_anchors) else None
        end_pos = next_ca["char_pos"] if next_ca else len(md_text)

        section_ids = []
        for s in sections:
            if ca["char_pos"] <= s["char_pos"] < end_pos:
                section_ids.append(s["section_id"])

        cid = f"{doc_prefix}_ch{ci + 1:02d}"
        ch_meta = {
            "chapter_id": cid,
            "number": ca["number"],
            "title": ca["title"],
            "section_ids": section_ids,
            "char_pos": ca["char_pos"],
            "section_count": len(section_ids),
        }
        chapters.append(ch_meta)

        # chapter markdown: 该 chapter 下的所有 sections 原文拼接
        body = md_text[ca["char_pos"]:end_pos].strip()
        header = (
            f"# {ca['number']} {ca['title']}\n\n"
            f"> doc_id: {doc_id} · chapter_id: {cid} · "
            f"sections: {len(section_ids)}\n\n"
        )
        (chap_dir / f"{cid}.md").write_text(header + body, encoding="utf-8")

    # ============ JSON 索引 ============
    (md_dir / "sections.json").write_text(
        json.dumps(sections, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (md_dir / "chapters.json").write_text(
        json.dumps(chapters, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return sections, chapters


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("merged_md", type=Path, help="merged.md 路径")
    p.add_argument("doc_id", help="目标 doc_id")
    p.add_argument("out_root", type=Path, nargs="?", default=Path("data"),
                   help="输出根目录 (默认 data/, 即 data/markdown/<doc_id>/)")
    args = p.parse_args()

    md_text = args.merged_md.read_text(encoding="utf-8")
    sections, chapters = write_sections(args.doc_id, md_text, args.out_root)

    print(f"[OK] {args.doc_id}: {len(chapters)} chapters · {len(sections)} sections")
    for c in chapters:
        print(f"  {c['chapter_id']} {c['number']} {c['title']}  ({c['section_count']} sections)")
    table_secs = [s for s in sections if s["has_table"]]
    if table_secs:
        print(f"  [INFO] {len(table_secs)} 个 section 含表格: {[s['number'] for s in table_secs]}")


if __name__ == "__main__":
    main()