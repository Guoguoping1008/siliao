"""
章节切分器: 把法规 Markdown 按"章/节/条"切分,产出 GraphRAG 可消费的 chunks。

输出:
  data/markdown/<doc_id>/chapters/<chapter_id>.md     # 单章 Markdown
  data/markdown/<doc_id>/articles/<article_id>.md     # 单条 Markdown(粒度更细,供检索)
  data/markdown/<doc_id>/chapters.json                # 章节索引
  data/markdown/<doc_id>/articles.json                # 条文索引

识别规则(中文法规通用):
  第X章 ...           ->  一级标题 #
  第X节 ...           ->  二级标题 ##
  第X条 ...           ->  段落条目 (作为 chunk 粒度)
  X.Y 条              ->  段落条目(子条)
  (一)(二)...         ->  列表项
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


@dataclass
class Chapter:
    chapter_id: str       # 如 "ch01"
    number: str           # "第一章"
    title: str            # "总则"
    article_ids: list[str]
    start_line: int
    end_line: int


@dataclass
class Article:
    article_id: str       # 如 "art007"
    chapter_id: str
    number: str           # "第七条"
    title: str            # 第一条后括号里的标题,如有
    text: str             # 完整条文
    start_line: int
    end_line: int


def split_by_chapter(md_text: str, doc_id: str) -> tuple[list[Chapter], list[Article]]:
    lines = md_text.splitlines()
    chapters: list[Chapter] = []
    articles: list[Article] = []

    cur_chapter: Chapter | None = None
    cur_article: Article | None = None
    cur_buf: list[str] = []

    chapter_counter = 0
    article_counter = 0

    def flush_article():
        nonlocal cur_article, cur_buf
        if cur_article is not None:
            cur_article.text = "\n".join(cur_buf).strip()
            cur_article.end_line = line_no - 1
            articles.append(cur_article)
        cur_article = None
        cur_buf = []

    line_no = 0
    for raw in lines:
        line_no += 1
        stripped = raw.strip()

        m_chap = CHAPTER_RE.match(stripped)
        if m_chap:
            flush_article()
            chapter_counter += 1
            cur_chapter = Chapter(
                chapter_id=f"ch{chapter_counter:02d}",
                number=stripped.split()[0],
                title=m_chap.group(1),
                article_ids=[],
                start_line=line_no,
                end_line=line_no,
            )
            chapters.append(cur_chapter)
            continue

        m_sec = SECTION_RE.match(stripped)
        if m_sec:
            # 节是章内的二级,不创建独立 chapter,记到当前 chapter 的 metadata
            continue

        m_art = ARTICLE_RE.match(stripped)
        if m_art:
            flush_article()
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

        if cur_article:
            cur_buf.append(raw)

    flush_article()

    # end_line 回填
    for i in range(len(chapters) - 1):
        chapters[i].end_line = chapters[i + 1].start_line - 1
    if chapters:
        chapters[-1].end_line = len(lines)

    return chapters, articles


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

    # 章节文件
    for ch in chapters:
        body = "\n".join(lines[ch.start_line - 1: ch.end_line]).strip()
        header = f"# {ch.number} {ch.title}\n\n> doc_id: {doc_id} · chapter_id: {ch.chapter_id} · articles: {len(ch.article_ids)}\n\n"
        (chap_dir / f"{ch.chapter_id}.md").write_text(header + body, encoding="utf-8")

    # 条文文件(GraphRAG 主输入)
    for art in articles:
        body = art.text
        meta = (
            f"<!-- doc_id: {doc_id} · chapter_id: {art.chapter_id} · article_id: {art.article_id} · number: {art.number} -->\n\n"
        )
        (art_dir / f"{art.article_id}.md").write_text(meta + body, encoding="utf-8")

    # JSON 索引
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
    chapters, articles = split_by_chapter(md_text, doc_id)
    write_outputs(doc_id, md_text, chapters, articles, out_root)

    print(f"[OK] {doc_id}: {len(chapters)} chapters · {len(articles)} articles")
    for c in chapters:
        print(f"  {c.chapter_id} {c.number} {c.title}  ({len(c.article_ids)} articles)")


if __name__ == "__main__":
    main()