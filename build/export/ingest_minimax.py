"""
ingest_minimax.py —— minimax/ 目录树 → RAG 索引产物
=========================================================

输入: minimax/<章>/<节>/<文件>/<页>.md  (1021 页, 179 份文件)
输出:
    data/index/minimax/documents.json   文档清单 (章 → 节 → 文件)
    data/index/minimax/chapters.json    章节 (节级)
    data/index/minimax/articles.json    条文 (检索单元)
    data/index/minimax/articles/<article_id>.md   条文正文 (推 R2)
    data/index/minimax/chapters/<chapter_id>.md   章节正文 (推 R2)
    build/export/seed.sql               D1 seed SQL

为什么不用 chapter_splitter.py / article_splitter.py:
    minimax/ 已经是**目录驱动**重整过的成品 —— 目录树本身就是章节结构,
    markdown 里的 `#/##/###` 已经是语义化的标题层级(不是 OCR 噪声)。
    再跑一次正则反切只会把结构切碎。
    本脚本做的是「读取已有结构」,不是「猜结构」。

层级映射 (经全库 1021 页实测验证):
    minimax/<章>/           →  顶层分类 (documents 表的一层? 见下)
    minimax/<章>/<节>/      →  chapters 表的一行 (节级)
    minimax/<章>/<节>/<文件>/ →  一份法规/制度文件 = 一个 doc_id
    md 内 `#`              →  文件标题 (文档名, 覆盖目录名)
    md 内 `## 第X章`       →  章节上下文 (注入条文 text 前缀, 见 ADR-002)
    md 内 `### 第X条`      →  article (检索单元) —— 1940 个
    md 内 `### N 标题`     →  article (GB/T 数字章节) —— 171 个
    md 内 `### 短标签`      →  article (附件/表单标题) —— 556 个

顶层章 (00 封面 / 01 目录) 不是法规正文, 归到 documents 但不产条文,
    保留可追溯性, 同时不进 FTS 索引 (见 --skip-toc)。

关键设计 (踩坑防护):
  1. **article_id 全局唯一**: 用 `<doc_slug>_<文件序号>_<条序号>` 三段式。
     不能只用 doc_id + 条号 —— 同一文件里 "第一条" 可能出现在多个附属文件。
  2. **条文跨页续接**: 同一文件的条文可能跨 md 文件边界(第X条 结尾在下一页)。
     拼接时按「页序」顺序 append, 不做跨页截断。
  3. **条文编号不连续是正常的**: OCR 表格页/附录页会丢条号, 不能假设连续。
  4. **章节名注入 text 前缀**: 让搜"总则"/"附则"能召回该章下所有条文
     (FTS5 只索引条文正文, 不索引章节名 —— 详见 skill qingmang-rag-impl)。
  5. **表格页不切碎**: 表格以 markdown table 形式存在, 按 `###` 切即可;
     没有 `###` 的页整体作为一条 article (page-level fallback)。

用法:
    python build/export/ingest_minimax.py            # 全量
    python build/export/ingest_minimax.py --dry-run  # 只统计不写文件
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

# ---------- 常量 ----------

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "minimax"
OUT = REPO / "data" / "index" / "minimax"
SEED_SQL = REPO / "build" / "export" / "seed.sql"

# 顶层「章」目录 → 顶层 scope 名 (用于 documents 表的分组)
# 00 封面 / 01 目录 是书的封面和目录, 不是法规正文
SKIP_TOC_SCOPES = {"000封面", "001目录"}

# 条文切分锚点: markdown h3
H3_RE = re.compile(r"^###\s+(.+?)\s*$", re.M)
# 章节锚点: markdown h2
H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)
# 文件标题: markdown h1
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)

# 章节名(注入条文 text 前缀用): 「第X章 标题」
CHAP_NUM_RE = re.compile(r"^(第[一二三四五六七八九十百零]+章)\s*(.*)$")
# 条文号: 「第一条」
ART_NUM_RE = re.compile(r"^(第[一二三四五六七八九十百零]+条)\s*(.*)$")
# 数字章节: 「3 试验方案」/「4.2.1 xxx」
ARABIC_SEC_RE = re.compile(r"^(\d+(?:\.\d+)*)\s+(.+)$")
# 文号: 「中华人民共和国国务院令2011年第609号」
DOCNO_RE = re.compile(r"([一-鿿]{2,20}(?:令|公告|通知|通告|批复|函|决定|规程|规范|标准|指南|办法|条例|规定|意见)[^\n]{0,40}?\d{4}\s*年?第?\s*\d+\s*号)")


def slugify(text: str, maxlen: int = 24) -> str:
    """
    生成 ID / 文件名安全的 slug。
    Windows 文件名禁用: \\ / : * ? " < > |  以及保留名 (CON/PRN/AUX/NUL/COM1..9/LPT1..9)
    另外去掉控制字符, 压掉连续下划线。
    """
    s = (text or "").strip()
    # Windows 保留字符 → 下划线
    s = re.sub(r'[\\/:*?"<>|]+', "_", s)
    # 控制字符
    s = re.sub(r"[\x00-\x1f]", "", s)
    # 空白 → 下划线
    s = re.sub(r"\s+", "_", s)
    # 连续下划线压成一个
    s = re.sub(r"_+", "_", s).strip("_")
    # Windows 保留名 (CON, PRN, AUX, NUL, COM1-9, LPT1-9) —— 加前缀避开
    if re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)", s, re.I):
        s = "_" + s
    return s[:maxlen] if s else "untitled"


def doc_id_from_path(rel_parts: list[str]) -> str:
    """
    从 <章>/<节>/<文件> 路径生成 doc_id。
    例: ['02制度文件', '01_（一）新产品审定', '01_新饲料和新饲料添加剂管理办法']
      → '02制度文件_01_新产品审定_01_新饲料和新饲料添加剂管理办法'
    章层保留前缀数字保证排序稳定; 文件名前缀数字保留(目录里的序号)。
    """
    parts = [p for p in rel_parts if p]
    return "_".join(slugify(p, 32) for p in parts)


def chapter_id_from_path(chap_rel: list[str]) -> str:
    """节级 → chapter_id。"""
    return "_".join(slugify(p, 32) for p in chap_rel)


def split_pages_by_heading(text: str) -> list[tuple[str, str]]:
    """
    按 markdown h3 切块。返回 [(heading, body), ...]。
    heading 为空表示页首正文(第一个 h3 之前的内容)。
    """
    out: list[tuple[str, str]] = []
    marks = list(H3_RE.finditer(text))
    if not marks:
        return [("", text)]
    # h3 之前的引导正文
    preamble = text[: marks[0].start()].strip()
    if preamble:
        out.append(("", preamble))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end() : end].strip()
        out.append((m.group(1).strip(), body))
    return out


def chapter_context_at(text: str, char_pos: int) -> tuple[str, str]:
    """
    取 char_pos 位置所处的章节上下文。
    返回 (chapter_number, chapter_title)。找不到返回 ("", "")。
    """
    last = None
    for m in H2_RE.finditer(text):
        if m.start() <= char_pos:
            last = m
        else:
            break
    if not last:
        return ("", "")
    raw = last.group(1).strip()
    cm = CHAP_NUM_RE.match(raw)
    if cm:
        return (cm.group(1), cm.group(2).strip() or raw)
    # 「附录A」「附件1」这类也当章节上下文(用原名)
    return (raw, raw)


def strip_html_table_noise(body: str) -> str:
    """表格页常见噪声: 纯符号行 / 空单元格行。保留行, 但压掉多余空白。"""
    lines = []
    for l in body.splitlines():
        s = l.strip()
        if not s:
            lines.append("")
            continue
        lines.append(s)
    # 压掉 3 行以上连续空行
    out: list[str] = []
    blanks = 0
    for l in lines:
        if not l:
            blanks += 1
            if blanks <= 1:
                out.append(l)
        else:
            blanks = 0
            out.append(l)
    return "\n".join(out).strip()


# 单条 chunk 最大字符数。
# 超限的块 (常见于整页表格 / 无 ### 锚点的长文档) 必须切分, 否则:
#   1) RAG prompt 塞不下 (context 被稀释, LLM 抓不住重点)
#   2) bge embedding 截断 (bge-m3 上限 8192 token, 96KB 直接被砍)
#   3) FTS5 单条过长, LIKE 兜底排序失真
MAX_CHUNK_CHARS = 3000


def split_long_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """
    超长块切分。优先在空行(段落边界)切; 单段超长时在句号/分号切;
    都不行就硬切。返回非空片段列表。
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    out: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        window = remaining[:max_chars]
        # 优先段落边界
        cut = window.rfind("\n\n")
        if cut < max_chars // 3:
            # 次选句末标点
            best = max(window.rfind(c) for c in ("。", "；", "！", "？", "\n"))
            cut = best if best > max_chars // 3 else -1
        if cut < max_chars // 3:
            cut = max_chars  # 硬切
        piece = remaining[:cut].strip()
        if piece:
            out.append(piece)
        remaining = remaining[cut:].strip()
    if remaining:
        out.append(remaining)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只统计不写文件")
    ap.add_argument("--src", default=str(SRC))
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    src = Path(args.src)
    out = Path(args.out)
    if not src.exists():
        print(f"[ERR] source not found: {src}")
        return 1

    # ---------- 1. 扫描语料树: 顶层 scope → 节 → 文件 ----------
    scopes: list[dict] = []
    doc_chunks: list[dict] = []

    for scope_dir in sorted([d for d in src.iterdir() if d.is_dir()]):
        scope_name = scope_dir.name
        scope_id = slugify(scope_name, 32)

        # 章层直接挂 md (封面 / 目录) —— 无节, 单独处理
        loose_files = sorted(scope_dir.glob("*.md"))
        for f in loose_files:
            doc_chunks.append(
                {
                    "scope": scope_name,
                    "scope_id": scope_id,
                    "section": None,
                    "section_id": None,
                    "doc_dir": f.parent,
                    "files": [f],
                    "is_toc": scope_name in SKIP_TOC_SCOPES,
                }
            )

        for sec_dir in sorted([d for d in scope_dir.iterdir() if d.is_dir()]):
            sec_name = sec_dir.name
            sec_id = slugify(sec_name, 32)

            # 形态 A: <节>/ 下直接是 md 页 (无 <文件>/ 子目录)
            #   例: 03相关法律法规文件/01_（一）中华人民共和国畜牧法/0739.md
            direct_pages = sorted(sec_dir.glob("*.md"))
            if direct_pages:
                doc_chunks.append(
                    {
                        "scope": scope_name,
                        "scope_id": scope_id,
                        "section": sec_name,
                        "section_id": sec_id,
                        "doc_dir": sec_dir,
                        "files": direct_pages,
                        "is_toc": scope_name in SKIP_TOC_SCOPES,
                    }
                )

            # 形态 B: <节>/<文件>/<页>.md
            for doc_dir in sorted([d for d in sec_dir.iterdir() if d.is_dir()]):
                # 递归收页: 有些子树比 <节>/<文件>/ 深一层 (如
                # 03相关法律法规文件/<节>/<文件>/<文件>/)。用 rglob 兜住。
                pages = sorted(doc_dir.rglob("*.md"))
                if not pages:
                    continue
                doc_chunks.append(
                    {
                        "scope": scope_name,
                        "scope_id": scope_id,
                        "section": sec_name,
                        "section_id": sec_id,
                        "doc_dir": doc_dir,
                        "files": pages,
                        "is_toc": scope_name in SKIP_TOC_SCOPES,
                    }
                )

    print(f"[scan] {len(doc_chunks)} document dirs · {sum(len(c['files']) for c in doc_chunks)} pages")

    # ---------- 2. 逐文档切条文 ----------
    documents: list[dict] = []
    chapters: list[dict] = []
    articles: list[dict] = []

    # chapter 去重表: chapter_id → chapter dict
    chapter_by_id: dict[str, dict] = {}
    art_seq = 0

    art_index: dict[str, dict] = {}  # article_id → article dict

    for ci, chunk in enumerate(doc_chunks):
        files = chunk["files"]
        scope = chunk["scope"]
        section = chunk["section"]
        section_id = chunk["section_id"]

        # 文档 id: 章_节_文件 (loose 文件: 章_文件名)
        if section:
            doc_id = doc_id_from_path([scope, section, chunk["doc_dir"].name])
        else:
            # loose 文件: 用**文件名**而不是目录名, 否则同 scope 下所有文件撞 id
            # (000封面/ 下 6 个文件全叫 "000封面" → 6 个相同 doc_id)
            doc_id = doc_id_from_path([scope, chunk["doc_dir"].name, files[0].stem])

        # 读全文 (按页序拼接)
        page_texts: list[str] = []
        for p in files:
            t = p.read_text(encoding="utf-8", errors="replace")
            page_texts.append(t)
        full = "\n\n".join(page_texts)

        # 文档标题: 第一个 h1; 没有就用目录名
        h1s = H1_RE.findall(full)
        doc_title = h1s[0].strip() if h1s else chunk["doc_dir"].name
        # 目录名带序号前缀, 标题不带 → 两者都留, title 用 h1, 另存目录名
        doc_number = ""
        dm = DOCNO_RE.search(full)
        if dm:
            doc_number = dm.group(1).strip()

        # 章节上下文: 全文按 h2 切, 记录每个 h3 所在的 h2
        # 简单法: 对每个 h3 位置, 找之前最近的 h2
        h2_positions = [(m.start(), m.group(1).strip()) for m in H2_RE.finditer(full)]
        h3_positions = [(m.start(), m.group(1).strip()) for m in H3_RE.finditer(full)]

        # 章节 (节级) —— 一个 doc_dir 归属一个节; 但文档内部的「第X章」也是章节
        # 这里两级都要:
        #   (a) 节级 chapter —— 对应 minimax/<章>/<节>/ 目录, 是导航单位
        #   (b) 章级 chapter —— md 内 `## 第X章`, 是条文归属单位
        # 采用 (b) 做 articles.chapter_id(条文必须有归属),
        # (a) 存进 documents.scope/section 字段 + 另建 chapter 记录做导航。
        # ⚠️ section 可能为 None (顶层章直接挂 md, 如 000封面/001目录),
        #    此时也必须建节级 chapter, 否则 articles.chapter_id 悬空 → FK 失败。
        sec_chapter_id = f"{doc_id}__section"
        if sec_chapter_id not in chapter_by_id:
            chapter_by_id[sec_chapter_id] = {
                "chapter_id": sec_chapter_id,
                "doc_id": doc_id,
                "number": "",
                "title": section or scope,
                "kind": "section",
                "sort_order": 0,
                "article_ids": [],
                "doc_number": doc_number,
                "source": "目录",
            }

        doc_articles: list[str] = []
        doc_article_objs: list[dict] = []

        # --- 切条文 ---
        # 用位置扫描, 保证章上下文正确
        if not h3_positions:
            # 整页作为一条 (无 h3 锚点的页)
            body = strip_html_table_noise(full)
            if body.strip():
                art_seq += 1
                aid = f"{doc_id}__p{len(doc_articles)+1:03d}"
                cnum, ctitle = chapter_context_at(full, 0)
                obj = {
                    "article_id": aid,
                    "chapter_id": sec_chapter_id,
                    "doc_id": doc_id,
                    "number": "",
                    "title": doc_title,
                    "heading": "",
                    "text": body,
                    "chapter_number": cnum,
                    "chapter_title": ctitle,
                    "source_file": files[0].name if files else "",
                    "kind": "page",
                }
                doc_article_objs.append(obj)
                doc_articles.append(aid)
        else:
            # preamble (第一个 h3 之前)
            pre = full[: h3_positions[0][0]].strip()
            if pre:
                art_seq += 1
                aid = f"{doc_id}__p{len(doc_articles)+1:03d}"
                cnum, ctitle = chapter_context_at(full, 0)
                obj = {
                    "article_id": aid,
                    "chapter_id": sec_chapter_id,
                    "doc_id": doc_id,
                    "number": "",
                    "title": doc_title,
                    "heading": "",
                    "text": strip_html_table_noise(pre),
                    "chapter_number": cnum,
                    "chapter_title": ctitle,
                    "source_file": files[0].name if files else "",
                    "kind": "preamble",
                }
                doc_article_objs.append(obj)
                doc_articles.append(aid)

            for hi, (pos, heading) in enumerate(h3_positions):
                end = h3_positions[hi + 1][0] if hi + 1 < len(h3_positions) else len(full)
                body = strip_html_table_noise(full[pos:end])
                if not body.strip():
                    continue

                art_seq += 1
                aid = f"{doc_id}__a{len(doc_articles)+1:03d}"

                # 条号 / 标题解析
                number = ""
                atitle = heading
                kind = "section"
                am = ART_NUM_RE.match(heading)
                if am:
                    number = am.group(1)
                    atitle = am.group(2).strip() or number
                    kind = "article"
                else:
                    sm = ARABIC_SEC_RE.match(heading)
                    if sm:
                        number = sm.group(1)
                        atitle = sm.group(2).strip()
                        kind = "section"
                    else:
                        atitle = heading
                        kind = "section"

                cnum, ctitle = chapter_context_at(full, pos)

                # 条文归属章节: 若有 h2 上下文, 建一个 chapter 行 (章级)
                chap_id = sec_chapter_id
                if cnum:
                    # 章级 chapter_id: 用 '@@' 分隔 (Windows 文件名不能含 ':')
                    chap_id = f"{doc_id}@@{cnum}"
                    if chap_id not in chapter_by_id:
                        chapter_by_id[chap_id] = {
                            "chapter_id": chap_id,
                            "doc_id": doc_id,
                            "number": cnum,
                            "title": ctitle,
                            "kind": "chapter",
                            "sort_order": len(chapter_by_id),
                            "article_ids": [],
                            "doc_number": doc_number,
                            "source": "md-heading",
                        }

                doc_article_objs.append(
                    {
                        "article_id": aid,
                        "chapter_id": chap_id,
                        "doc_id": doc_id,
                        "number": number,
                        "title": atitle,
                        "heading": heading,
                        "text": body,
                        "chapter_number": cnum,
                        "chapter_title": ctitle,
                        "source_file": files[0].name if files else "",
                        "kind": kind,
                    }
                )
                doc_articles.append(aid)

        # ---------- 文档记录 ----------
        # 超长块切分 (整页表格 / 无 ### 锚点的长文档会产出 10K+ 字符的单条)。
        # ⚠️ 切分必须**替换**原块, 不能只追加 —— 否则索引里同时存在
        #    96KB 的巨块和它的碎片, 检索会优先命中巨块 (FTS5 rank 更靠前),
        #    RAG prompt 被巨块撑爆, 后面 8 条证据全被稀释。
        expanded: list[dict] = []
        for a in doc_article_objs:
            if len(a["text"]) <= MAX_CHUNK_CHARS:
                expanded.append(a)
                continue
            pieces = split_long_text(a["text"])
            base_aid = a["article_id"]
            for pi, piece in enumerate(pieces):
                na = dict(a)
                na["article_id"] = f"{base_aid}_s{pi:02d}"
                na["text"] = piece
                na["kind"] = a["kind"] + "-split"
                expanded.append(na)

        # 用切分后的版本替换掉原始块
        doc_article_objs = expanded
        doc_articles = [a["article_id"] for a in doc_article_objs]
        # 登记到全局索引 (articles 列表在文档处理结束后统一 extend)
        for a in doc_article_objs:
            art_index[a["article_id"]] = a
        articles.extend(doc_article_objs)

        documents.append(
            {
                "doc_id": doc_id,
                "title": doc_title,
                "dir_name": chunk["doc_dir"].name,
                "scope": scope,
                "scope_id": scope_id,
                "section": section,
                "section_id": section_id,
                "doc_number": doc_number,
                "page_count": len(files),
                "article_count": len(doc_articles),
                "is_toc": chunk["is_toc"],
                "article_ids": doc_articles,
            }
        )

        for aid in doc_articles:
            ch = chapter_by_id.get(art_index[aid]["chapter_id"])
            if ch is not None:
                ch["article_ids"].append(aid)
    # ---------- 3. 章节列表 ----------
    chapters = list(chapter_by_id.values())
    for ch in chapters:
        ch["article_count"] = len(ch["article_ids"])

    # ⚠️ 节级章节的 article_ids 只装了「直接归属」的条文, 但条文通常挂在
    #    章级子章节下 (chap_id = <doc_id>@@第X章)。不聚合的话,
    #    节级章节正文是空的, 前端点开是白页。
    #    对策: 章级 chapter 反查它所属的节级 chapter, 把条文补进节级。
    chapter_id_by_doc: dict[str, str] = {}
    for ch in chapters:
        if ch["kind"] == "section":
            chapter_id_by_doc[ch["doc_id"]] = ch["chapter_id"]

    for ch in chapters:
        if ch["kind"] != "chapter":
            continue
        sec_id = chapter_id_by_doc.get(ch["doc_id"])
        if not sec_id:
            continue
        sec = chapter_by_id.get(sec_id)
        if sec is None:
            continue
        sec_ids = set(sec["article_ids"])
        for aid in ch["article_ids"]:
            if aid not in sec_ids:
                sec["article_ids"].append(aid)
                sec_ids.add(aid)

    for ch in chapters:
        ch["article_count"] = len(ch["article_ids"])

    # ---------- 4. 写文件 ----------
    if args.dry_run:
        print(
            f"[dry-run] documents={len(documents)} chapters={len(chapters)} articles={len(articles)}"
        )
        kinds: dict[str, int] = {}
        for a in articles:
            kinds[a["kind"]] = kinds.get(a["kind"], 0) + 1
        print(f"[dry-run] article kinds: {kinds}")
        return 0

    (out / "articles").mkdir(parents=True, exist_ok=True)
    (out / "chapters").mkdir(parents=True, exist_ok=True)

    # 文件名安全: doc_id 含中文可能很长, 加上 8 位 hash 后缀并截断,
    # 保证 Windows 路径 < 260 字符。DB 里仍存完整 article_id / chapter_id。
    def safe_name(raw_id: str) -> str:
        h = hashlib.sha1(raw_id.encode("utf-8")).hexdigest()[:8]
        stem = re.sub(r'[\\/:*?"<>|]+', "_", raw_id)[:120].strip("_")
        return f"{stem}__{h}" if stem else h

    # R2 key 映射表: article_id / chapter_id → R2 object key
    r2_keys: dict[str, str] = {}
    r2_doc_ids: dict[str, str] = {}

    # ⚠️ R2 key 的 doc_id 段必须**短**。
    #    实测 miniflare/R2 对 object name 有 ~320 字节的上限(UTF-8 字节数):
    #    doc_id 是路径 slug, 中文一字 3 字节, 形态 A 的 doc_id 重复两遍目录名
    #    最长到 205 字节, 加上 "/articles/" + 长文件名就超限 →
    #    "put: The specified object name is not valid. (10020)"。
    #    对策: R2 key 用 doc_id 的 sha1 前 10 位做短前缀, 完整 doc_id 仍存在 D1。
    #    (DB 里存的是 r2_object_key, Worker 按它拼 key —— 两边一致即可。)
    def short_doc_id(doc_id: str) -> str:
        return "d" + hashlib.sha1(doc_id.encode("utf-8")).hexdigest()[:10]

    # 条文正文 (推 R2)
    for a in articles:
        body = a["text"]
        if a["chapter_number"]:
            body = f"{a['chapter_number']} {a['chapter_title']}\n\n{body}"
        fname = safe_name(a["article_id"])
        (out / "articles" / f"{fname}.md").write_text(body, encoding="utf-8")
        r2_keys[a["article_id"]] = fname + ".md"
        r2_doc_ids[a["doc_id"]] = short_doc_id(a["doc_id"])

    # 章节正文: 汇总该章下条文
    for ch in chapters:
        parts = []
        for aid in ch["article_ids"]:
            a = art_index[aid]
            label = a["number"] or a["heading"] or a["title"]
            parts.append(f"### {label}\n\n{a['text']}")
        # ⚠️ 节级章节(kind=section)也要有正文 —— 前端点开章节不能是空白页。
        #    它汇总的是本节下所有条文的正文(含各章级子章节的条文)。
        fname = safe_name(ch["chapter_id"])
        (out / "chapters" / f"{fname}.md").write_text(
            "\n\n".join(parts), encoding="utf-8"
        )
        r2_keys[ch["chapter_id"]] = fname + ".md"

    # 紧凑格式: 前端 eager 打包, indent 会让体积翻倍
    (out / "documents.json").write_text(
        json.dumps(documents, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    (out / "chapters.json").write_text(
        json.dumps(chapters, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    (out / "articles.json").write_text(
        json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 前端专用轻量清单: 不含 text 字段。
    # 理由: articles.json 带全文是 4.8MB, 前端 import.meta.glob eager 打包
    # 会把整个语料塞进 bundle(实测 mockData chunk 3.6MB / 943KB gzip)——
    # 前端 mock 模式的正文本来就从 articles/*.md 按需加载, text 字段是冗余的。
    # 保留完整 articles.json 供 eval / 灌库脚本使用(它们需要正文)。
    light_articles = [
        {
            "article_id": a["article_id"],
            "chapter_id": a["chapter_id"],
            "doc_id": a["doc_id"],
            "number": a["number"],
            "title": a["title"],
            "heading": a["heading"],
            "chapter_number": a["chapter_number"],
            "chapter_title": a["chapter_title"],
            "kind": a["kind"],
        }
        for a in articles
    ]
    # 紧凑格式: 前端会 eager 打包这个文件, indent 会让体积翻倍
    (out / "articles.light.json").write_text(
        json.dumps(light_articles, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    # 前端 mock 搜索用的**单文件语料**: article_id → 全文。
    # 理由: 前端用 import.meta.glob 加载 3145 个逐条 markdown, 在 dev/test 下
    # 每个 import() 都要过一遍模块解析器, 单次 search 实测 >5s(测试直接超时)。
    # 合成一个 json 后只需一次 import。
    # 体积: 正文 1.3MB + 元数据, gzip 后约 400KB, 可接受(mock 模式专用)。
    corpus = [
        {
            "article_id": a["article_id"],
            "text": a["text"],
        }
        for a in articles
    ]
    (out / "search-corpus.json").write_text(
        json.dumps(corpus, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    # ---------- 5. seed.sql ----------
    write_seed_sql(documents, chapters, articles, r2_keys, r2_doc_ids)

    print(f"[OK] documents={len(documents)} chapters={len(chapters)} articles={len(articles)}")
    print(f"     out: {out}")
    print(f"     seed: {SEED_SQL}")
    return 0


def esc(s: str) -> str:
    return (s or "").replace("'", "''")


def write_seed_sql(
    documents: list[dict],
    chapters: list[dict],
    articles: list[dict],
    r2_keys: dict[str, str],
    r2_doc_ids: dict[str, str],
) -> None:
    """生成 D1 seed SQL。

    FK 顺序: documents → chapters → articles → articles_fts。
    章节名注入条文 text 前缀 —— 让搜"总则"/"附则"能召回该章条文。
    r2_object_key 存 R2 对象**文件名**(Worker 拼 <doc_id>/articles/<key>)。
    """
    lines: list[str] = []
    lines.append("DELETE FROM articles_fts;")
    lines.append("DELETE FROM articles;")
    lines.append("DELETE FROM chapters;")
    lines.append("DELETE FROM documents;")

    doc_title_by_id = {d["doc_id"]: d["title"] for d in documents}

    for d in documents:
        lines.append(
            "INSERT INTO documents(doc_id, title, doc_number, issuer, version) VALUES("
            f"'{esc(d['doc_id'])}', '{esc(d['title'])}', '{esc(d['doc_number'])}', "
            f"'{esc(d['scope'])}', 'minimax-2026');"
        )

    for c in chapters:
        # r2_object_key 存**完整 R2 key**(含短 doc 前缀), Worker 直接取用
        ck = r2_keys.get(c["chapter_id"], c["chapter_id"] + ".md")
        ck_full = f"{r2_doc_ids.get(c['doc_id'], 'd')}/chapters/{ck}"
        lines.append(
            "INSERT INTO chapters(chapter_id, doc_id, number, title, article_count, sort_order, r2_object_key) VALUES("
            f"'{esc(c['chapter_id'])}', '{esc(c['doc_id'])}', '{esc(c['number'])}', "
            f"'{esc(c['title'])}', {c['article_count']}, {c['sort_order']}, "
            f"'{esc(ck_full)}');"
        )

    # 目录/封面文档的 doc_id → 它们的条文不进 FTS 索引
    toc_doc_ids = {d["doc_id"] for d in documents if d.get("is_toc")}

    for a in articles:
        title = a["title"] or ""
        # r2_object_key 存**完整 R2 key**(含短 doc 前缀), Worker 直接取用
        ak = r2_keys.get(a["article_id"], a["article_id"] + ".md")
        ak_full = f"{r2_doc_ids.get(a['doc_id'], 'd')}/articles/{ak}"
        lines.append(
            "INSERT INTO articles(article_id, chapter_id, doc_id, number, title, r2_object_key) VALUES("
            f"'{esc(a['article_id'])}', '{esc(a['chapter_id'])}', '{esc(a['doc_id'])}', "
            f"'{esc(a['number'])}', '{esc(title)}', "
            f"'{esc(ak_full)}');"
        )

        # ⚠️ 目录页(001目录)与封面(000封面)不进全文索引 ——
        #    目录里全是「文件名 + 页码」的列表, 检索命中它等于命中目录,
        #    会把「搜新兽药注册办法」的结果顶到目录条目上, 而不是正文条文。
        #    这 186 条仍在 articles / chapters / documents 表里(可追溯),
        #    只是不进 articles_fts(不参与检索)。
        if a["doc_id"] in toc_doc_ids:
            continue

        # 章节名注入: FTS5 只索引条文正文, 不索引章节名。
        # 注入后搜"总则"能召回第一章下所有条文 (ADR-002)。
        text = a["text"].replace("\n", " ").strip()
        prefix = ""
        if a["chapter_number"]:
            prefix = f"{a['chapter_number']} {a['chapter_title']} "
        # 文档标题也注入 —— 搜文件名能召回该文档下所有条文
        doc_title = doc_title_by_id.get(a["doc_id"], "")
        text = f"{prefix}{doc_title} {text}".strip()

        lines.append(
            "INSERT INTO articles_fts(article_id, chapter_id, doc_id, number, title, text) VALUES("
            f"'{esc(a['article_id'])}', '{esc(a['chapter_id'])}', '{esc(a['doc_id'])}', "
            f"'{esc(a['number'])}', '{esc(title)}', '{esc(text)}');"
        )

    SEED_SQL.parent.mkdir(parents=True, exist_ok=True)
    SEED_SQL.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"     sql: {len(lines)} statements")


if __name__ == "__main__":
    sys.exit(main())
