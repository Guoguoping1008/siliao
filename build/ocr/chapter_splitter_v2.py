"""
章节切分器 v2: 解决了原 chapter_splitter.py 的 2 个问题
1. 目录里的章节标题被误识: 出现"二、制度文件"等 4 次
2. 条文(第X条)在目录里被误识为文章

策略:
- 同一 (number, title) 组合只算一次章节起点 (去重)
- "第X条" 等条文只在非目录范围内才算
- 目录范围: 从第一个 "目录" 标题开始, 到第一个 "第X章" / 真实 "一、" 章节标题(独立成行 + 后面是空行)之前
  (简单办法: 找到第一处 "一、xxx\n\n" 模式就视为目录结束)

输出同 chapter_splitter.py
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path


CHAPTER_RE = re.compile(r"^第[一二三四五六七八九十百千零〇0-9]+章\s+(.+?)\s*$")
SECTION_RE = re.compile(r"^第[一二三四五六七八九十百千零〇0-9]+节\s+(.+?)\s*$")
ARTICLE_RE = re.compile(r"^第[一二三四五六七八九十百千零〇0-9]+条\s*(.*?)\s*$")
SUBARTICLE_RE = re.compile(r"^(\d+)\.(\d+)\s+(.+?)\s*$")
LISTITEM_RE = re.compile(r"^\([一二三四五六七八九十]+\)\s*(.+?)\s*$")

CN_NUM_RE = r"[一二三四五六七八九十]+"
ASSEMBLY_CHAPTER_RE = re.compile(
    rf"^({CN_NUM_RE})、\s*(\S+?)\s*\d*\s*$"
)

TOC_HEAD = re.compile(r"^目\s*录\s*$")


@dataclass
class Chapter:
    chapter_id: str
    number: str
    title: str
    article_ids: list[str]
    start_line: int
    end_line: int
    is_toc: bool = False  # True = 这次切分来自目录页(可能是误识)


@dataclass
class Article:
    article_id: str
    chapter_id: str
    number: str
    title: str
    text: str
    start_line: int
    end_line: int


def detect_toc_range(lines: list[str]) -> tuple[int, int]:
    """返回目录范围的 (start_line, end_line) (0-indexed, end 不含)
    找不到返回 (-1, -1)
    """
    # 找第一个 "目录" 单独行
    start = -1
    for i, ln in enumerate(lines):
        if TOC_HEAD.match(ln.strip()):
            start = i
            break
    if start < 0:
        return -1, -1

    # 找结束: 第一个 "第X章 xxx" 或 "一、xxx" 标题单独成行 (后面是空行/正文)
    end = -1
    for i in range(start + 1, len(lines)):
        stripped = lines[i].strip()
        if CHAPTER_RE.match(stripped):
            end = i
            break
        # 汇编书真实章节: 短标题 (≤12字), 不是目录行 (目录行的"一、xxx" 后跟法规名/页码)
        m = ASSEMBLY_CHAPTER_RE.match(stripped)
        if m:
            title = m.group(2).strip()
            # 目录行特征: 标题后跟数字 (页码) — ASSEMBLY_CHAPTER_RE 已剥离
            # 真实章节标题特征: 单独成行,后面是空行
            if title and len(title) <= 12 and not title.endswith(("。", "，", ";", "；")):
                # 检查下一行是否空
                if i + 1 < len(lines) and lines[i + 1].strip() == "":
                    end = i
                    break
    if end < 0:
        end = len(lines)
    # 包含 end 那一行(章节起点本身仍在目录)
    return start, end + 1


def split_by_chapter_v2(md_text: str, doc_id: str) -> tuple[list[Chapter], list[Article], dict]:
    lines = md_text.splitlines()
    toc_start, toc_end = detect_toc_range(lines)
    is_toc_line = lambda ln: toc_start <= ln < toc_end

    chapters: list[Chapter] = []
    articles: list[Article] = []
    seen_chapters: set[tuple[str, str]] = set()  # (number, title) 去重

    cur_chapter: Chapter | None = None
    cur_article: Article | None = None
    cur_buf: list[str] = []

    chapter_counter = 0
    article_counter = 0

    def flush_article(line_no: int):
        nonlocal cur_article, cur_buf
        if cur_article is not None:
            cur_article.text = "\n".join(cur_buf).strip()
            cur_article.end_line = line_no - 1
            articles.append(cur_article)
        cur_article = None
        cur_buf = []

    for raw in lines:
        line_no = 1 + lines.index(raw)  # 不准,用 enumerate

    # 改用 enumerate
    for line_no, raw in enumerate(lines, 1):
        stripped = raw.strip()
        in_toc = is_toc_line(line_no - 1)

        # 1. 标准章节 "第X章 ..."
        m_chap = CHAPTER_RE.match(stripped)
        if m_chap:
            key = ("第X章", m_chap.group(1))
            if key in seen_chapters:
                continue
            seen_chapters.add(key)
            flush_article(line_no)
            chapter_counter += 1
            cur_chapter = Chapter(
                chapter_id=f"ch{chapter_counter:02d}",
                number=stripped.split()[0],
                title=m_chap.group(1),
                article_ids=[],
                start_line=line_no,
                end_line=line_no,
                is_toc=in_toc,
            )
            chapters.append(cur_chapter)
            continue

        # 2. 汇编书章节 "一、法规" / "二、制度文件 17"
        m_assem = ASSEMBLY_CHAPTER_RE.match(stripped)
        if m_assem:
            title = m_assem.group(2).strip()
            if title and len(title) <= 12 and not title.endswith(("。", "，", ";", "；")):
                key = (m_assem.group(1), title)
                if key in seen_chapters:
                    continue
                # 如果在目录范围,标记 is_toc=True 但不实际切分
                if in_toc:
                    continue
                seen_chapters.add(key)
                flush_article(line_no)
                chapter_counter += 1
                cur_chapter = Chapter(
                    chapter_id=f"ch{chapter_counter:02d}",
                    number=m_assem.group(1),
                    title=title,
                    article_ids=[],
                    start_line=line_no,
                    end_line=line_no,
                    is_toc=False,
                )
                chapters.append(cur_chapter)
                continue

        # 3. 节标记(忽略,不切分)
        m_sec = SECTION_RE.match(stripped)
        if m_sec:
            continue

        # 4. 条文 "第X条 ..." (在目录里不算)
        m_art = ARTICLE_RE.match(stripped)
        if m_art and not in_toc:
            flush_article(line_no)
            article_counter += 1
            aid = f"art{article_counter:03d}"
            if cur_chapter:
                cur_chapter.article_ids.append(aid)
            cur_article = Article(
                article_id=aid,
                chapter_id=cur_chapter.chapter_id if cur_chapter else "ch00",
                number=stripped.split()[0],
                title="",
                text="",
                start_line=line_no,
                end_line=line_no,
            )
            cur_buf = [stripped]
            continue

        if cur_article and not in_toc:
            cur_buf.append(raw)

    flush_article(len(lines))

    for i in range(len(chapters) - 1):
        chapters[i].end_line = chapters[i + 1].start_line - 1
    if chapters:
        chapters[-1].end_line = len(lines)

    return chapters, articles, {"toc_range": [toc_start, toc_end]}


def write_outputs(
    doc_id: str,
    src_md: str,
    chapters: list[Chapter],
    articles: list[Article],
    out_root: Path,
):
    md_dir = out_root / "markdown" / doc_id
    chap_dir = md_dir / "chapters"
    art_dir = md_dir / "articles"
    chap_dir.mkdir(parents=True, exist_ok=True)
    art_dir.mkdir(parents=True, exist_ok=True)

    lines = src_md.splitlines()

    for ch in chapters:
        body = "\n".join(lines[ch.start_line - 1: ch.end_line]).strip()
        header = f"# {ch.number} {ch.title}\n\n> doc_id: {doc_id} · chapter_id: {ch.chapter_id} · articles: {len(ch.article_ids)}\n\n"
        (chap_dir / f"{ch.chapter_id}.md").write_text(header + body, encoding="utf-8")

    for art in articles:
        body = art.text
        meta = (
            f"<!-- doc_id: {doc_id} · chapter_id: {art.chapter_id} · article_id: {art.article_id} · number: {art.number} -->\n\n"
        )
        (art_dir / f"{art.article_id}.md").write_text(meta + body, encoding="utf-8")

    (md_dir / "chapters.json").write_text(
        json.dumps([asdict(c) for c in chapters], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (md_dir / "articles.json").write_text(
        json.dumps([asdict(a) for a in articles], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main():
    import sys
    src = Path(sys.argv[1])
    doc_id = sys.argv[2]
    out_root = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(".")

    md_text = src.read_text(encoding="utf-8")
    chapters, articles, meta = split_by_chapter_v2(md_text, doc_id)
    write_outputs(doc_id, md_text, chapters, articles, out_root)

    print(f"[OK v2] {doc_id}: {len(chapters)} chapters · {len(articles)} articles · toc={meta['toc_range']}")
    for c in chapters:
        print(f"  {c.chapter_id} {c.number} {c.title}  ({len(c.article_ids)} articles)")


if __name__ == "__main__":
    main()
