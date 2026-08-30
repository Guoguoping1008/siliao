"""
Text-based 法条切分器: 不依赖物理坐标, 直接按"第X条"文本特征切分。

为什么独立:
- pic2md 的 group_by_paragraph 依赖 PaddleOCR bbox 的 y 间距, 但法规正文中
  相邻"第X条"的物理间距跟段内换行差不多, 物理切分不可靠
- 法规是结构化文本, 用"第X条"作为锚点反切更可靠
- 本脚本消费 merged.md, 输出与 chapter_splitter 兼容的 articles/ + articles.json

输出:
  data/markdown/<doc_id>/articles/<article_id>.md
  data/markdown/<doc_id>/articles.json
  data/markdown/<doc_id>/chapters.json
  data/markdown/<doc_id>/chapters/<chapter_id>.md

chapter_id 加 doc_id 前缀 (如 'fee_ch01') 避免多 doc 灌库时主键冲突。

用法:
  python build/ocr/article_splitter.py data/markdown/feed-law-collection-2023/merged.md \\
      feed-law-collection-2023 data
"""

from __future__ import annotations
import json
import re
from pathlib import Path


# 章节锚点(同 chapter_splitter)
CN_NUM = r"[一二三四五六七八九十]+"
ASSEMBLY_CHAPTER_RE = re.compile(
    rf"^({CN_NUM})、\s*(\S+?)\s*\d*\s*$"
)
ARTICLE_RE = re.compile(r"^第[一二三四五六七八九十百千零〇0-9]+条")


def split_articles(md_text: str) -> list[dict]:
    """把 merged.md 按"第X条"切分。每条: {number, text, offset}"""
    parts = re.split(r"(?=第[一二三四五六七八九十百千零〇0-9]+条)", md_text)
    articles = []
    for p in parts:
        p = p.strip()
        if not p or not ARTICLE_RE.match(p):
            continue
        first_line = p.split("\n")[0]
        m = re.match(r"^(第[一二三四五六七八九十百千零〇0-9]+条)", first_line)
        number = m.group(1) if m else "unknown"
        articles.append({"number": number, "text": p})
    return articles


def split_chapters(md_text: str) -> list[dict]:
    """找章节锚点位置, 返回 [{number, title, offset}, ...]"""
    chapters = []
    for line in md_text.splitlines():
        line = line.strip()
        m = ASSEMBLY_CHAPTER_RE.match(line)
        if m:
            title = m.group(2).strip()
            if title and len(title) <= 12 and not title.endswith(("。", "，")):
                chapters.append({"number": m.group(1), "title": title, "marker_line": line})
    return chapters


def write_articles(
    doc_id: str,
    md_text: str,
    out_root: Path,
):
    """输出 articles.json + articles/<id>.md

    chapter_id 用 doc_id 前缀避免多 doc 灌库时主键冲突
    (feed-law-2026 用 'fee_ch01', feed-law-collection-2023 用 'fee_col_ch01')
    """
    md_dir = out_root / "markdown" / doc_id
    art_dir = md_dir / "articles"
    art_dir.mkdir(parents=True, exist_ok=True)

    # 章节锚点 (按 char_pos)
    char_pos = 0
    chapter_anchors = []  # [(char_pos, number, title, full_line)]
    for ln in md_text.splitlines():
        m = ASSEMBLY_CHAPTER_RE.match(ln.strip())
        if m:
            title = m.group(2).strip()
            if title and len(title) <= 12 and not title.endswith(("。", "，")):
                chapter_anchors.append((char_pos, m.group(1), title, ln.strip()))
        char_pos += len(ln) + 1  # +1 for \n

    # doc_id 短前缀 (去横线, 前 3 字符)
    doc_prefix = doc_id.replace("-", "")[:3]

    # 找条文锚点 — 扫整段文本的所有"第X条"位置
    art_anchors = []  # [(char_pos, number)]
    for m in re.finditer(r"(第[一二三四五六七八九十百千零〇0-9]+条)", md_text):
        art_anchors.append((m.start(), m.group(1)))

    # 给每条 article 配 chapter
    # 返回 (number, title, idx_in_chapter_anchors) 让 caller 能精确定位
    def find_chapter(pos: int) -> tuple[str, str, int]:
        ch_num, ch_title, ch_idx = "前言", "前言", -1
        for idx, (cp, num, title, _) in enumerate(chapter_anchors):
            if cp <= pos:
                ch_num, ch_title, ch_idx = num, title, idx
            else:
                break
        return ch_num, ch_title, ch_idx

    chapters_dict: dict[str, dict] = {}
    cid_zero = f"{doc_prefix}_ch00"
    # 把 ch00 放在最前, 让 anchor idx 与 dict key idx 一一对应
    chapters_dict[cid_zero] = {
        "chapter_id": cid_zero,
        "number": "前言",
        "title": "前言",
        "full_line": "",
        "article_ids": [],
    }
    for idx, (_, num, title, full_line) in enumerate(chapter_anchors):
        cid = f"{doc_prefix}_ch{idx + 1:02d}"
        chapters_dict[cid] = {
            "chapter_id": cid,
            "number": num,
            "title": title,
            "full_line": full_line,
            "article_ids": [],
        }

    # 切条文: 每条 article text 从其 char_pos 到下一条的 char_pos
    articles = []
    for idx, (pos, number) in enumerate(art_anchors):
        next_pos = art_anchors[idx + 1][0] if idx + 1 < len(art_anchors) else len(md_text)
        text = md_text[pos:next_pos].strip()

        ch_num, ch_title, ch_idx = find_chapter(pos)
        # 按章节索引直接定位 cid (ch00 在 dict 最前, anchor idx 0 对应 ch01, idx 1 对应 ch02, ...)
        # ch_idx 是 chapter_anchors 的索引 (0-based, 不含 ch00 虚拟扉页)
        if ch_idx >= 0:
            keys = list(chapters_dict.keys())
            # chapters_dict[0] 是 cid_zero, [1] 是 fee_ch01, [2] 是 fee_ch02...
            cid = keys[ch_idx + 1]  # +1 是因为 cid_zero 占第 0 位
        else:
            cid = cid_zero

        aid = f"{doc_prefix}_art{idx + 1:03d}"
        chapters_dict[cid]["article_ids"].append(aid)

        articles.append({
            "article_id": aid,
            "chapter_id": cid,
            "number": number,
            "title": "",
            "text": text,
        })

        meta = (
            f"<!-- doc_id: {doc_id} · chapter_id: {cid} · article_id: {aid} · number: {number} -->\n\n"
        )
        (art_dir / f"{aid}.md").write_text(meta + text, encoding="utf-8")

    # 章节 markdown
    chap_dir = md_dir / "chapters"
    chap_dir.mkdir(parents=True, exist_ok=True)
    for cid, ch in chapters_dict.items():
        body_lines = []
        for aid in ch["article_ids"]:
            art = next(a for a in articles if a["article_id"] == aid)
            body_lines.append(f"## {art['number']}\n\n{art['text']}")
        body = "\n\n---\n\n".join(body_lines) if body_lines else "(本章暂无条文)"
        header_title = ch.get("full_line") or f"{ch['number']} {ch['title']}"
        header = f"# {header_title}\n\n> doc_id: {doc_id} · chapter_id: {cid} · articles: {len(ch['article_ids'])}\n\n"
        (chap_dir / f"{cid}.md").write_text(header + body, encoding="utf-8")

    # JSON 索引
    (md_dir / "articles.json").write_text(
        json.dumps(articles, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (md_dir / "chapters.json").write_text(
        json.dumps(list(chapters_dict.values()), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return articles, list(chapters_dict.values())


def main():
    import sys
    src = Path(sys.argv[1])
    doc_id = sys.argv[2]
    out_root = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(".")

    md_text = src.read_text(encoding="utf-8")
    articles, chapters = write_articles(doc_id, md_text, out_root)

    print(f"[OK] {doc_id}: {len(chapters)} chapters · {len(articles)} articles")
    for c in chapters:
        print(f"  {c['chapter_id']} {c['number']} {c['title']}  ({len(c['article_ids'])} articles)")


if __name__ == "__main__":
    main()