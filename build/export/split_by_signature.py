"""
按"文件签名"重做章节切分 (替代 v2 的烂切分)

策略:
- 扫所有 pages, 找文件签名 (部令 / 公告 / 农牧发 / 国办发 / 国务院令 / 法释 / 国发 / 农办牧 等)
- 每个签名的首次出现页 → 该份文件的起始页
- 从起始页到下一个签名起始页前 → 一个 chapter
- chapter title = 文件名 (签名上下文)
- chapter_seq = 按扫描顺序递增 (f01, f02, ...)

输出:
  markdown/<doc>/chapters_v3/<f_id>.md
  markdown/<doc>/chapters_v3/_manifest.json  (按 page_no 排序的所有 f_* 元数据)
"""

from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

ROOT = Path("E:/workspace/siliao")
DEFAULT_DOC = "feed-law-collection-2023-full"

# 文件签名模式 (按特异性从高到低, 优先匹配更具体的)
SIGNATURES = [
    ("部令",      re.compile(r"(?:中华人民共和国)?(?:农业农村部|农业部|海关总署)?令\s*[12]\d{3}\s*年?\s*第?\s*\d+\s*号")),
    ("国务院令",  re.compile(r"(?:中华人民共和国)?国务院令\s*(?:第?\s*\d+\s*号|\d+)\s*号?")),
    ("法释",      re.compile(r"法释[〔\[\(](?:19|20)\d{2}[〕\)\]]\s*\d+\s*号")),
    ("公告",      re.compile(r"(?:中华人民共和国)?(?:农业农村部|农业部|海关总署|国家税务总局|国家发改委|国务院|国家质量监督检验检疫总局)?(?:公告|总局公告)\s*第?\s*\d+\s*号")),
    ("农牧发",    re.compile(r"农牧发[〔\[\(](?:19|20)\d{2}[〕\)\]]\s*\d+\s*号")),
    ("农办牧",    re.compile(r"农办牧[〔\[\(](?:19|20)\d{2}[〕\)\]]\s*\d+\s*号")),
    ("国办发",    re.compile(r"国办发[〔\[\(](?:19|20)\d{2}[〕\)\]]\s*\d+\s*号")),
    ("国发",      re.compile(r"国发[〔\[\(](?:19|20)\d{2}[〕\)\]]\s*\d+\s*号")),
    ("农牧函",    re.compile(r"农牧函[〔\[\(](?:19|20)\d{2}[〕\)\]]\s*\d+\s*号")),
    ("农医发",    re.compile(r"农医发[〔\[\(](?:19|20)\d{2}[〕\)\]]\s*\d+\s*号")),
    ("农政发",    re.compile(r"农(?:政|经|计|质|市|牧)发[〔\[\(](?:19|20)\d{2}[〕\)\]]\s*\d+\s*号")),
]

# 一个文件签名的"标题候选": 同行或下一行的非空内容
TITLE_TAIL_MAX = 60  # 取签名后 N 字作为标题


def extract_signature(line: str) -> tuple[str, str] | None:
    """返回 (signature_str, title_candidate) 或 None"""
    line = line.strip()
    if not line:
        return None
    for kind, pat in SIGNATURES:
        m = pat.search(line)
        if m:
            sig = m.group(0).strip()
            # 标题候选: 同行签名后面的文字
            tail = line[m.end():].strip()
            # 或下一行的内容 (前 60 字)
            return (sig, tail[:TITLE_TAIL_MAX] or "(无标题)")
    return None


def extract_first_titles(md: str, sig_pos: int, sig_text: str, max_take: int = 200) -> str:
    """从签名所在行向后抓 N 字作为文件标题候选 (优先后续 2 行 + 同行尾部)"""
    # 拿签名所在行的剩余 + 后续 5 行非空内容
    lines = md.splitlines()
    out = []

    # 找签名在哪一行
    pos = 0
    sig_line_idx = 0
    for i, ln in enumerate(lines):
        if sig_text in ln:
            sig_line_idx = i
            break
        pos += len(ln) + 1
        if pos > sig_pos:
            sig_line_idx = i
            break

    # 收集 sig 行剩余 + 后续最多 5 行
    for j in range(sig_line_idx, min(sig_line_idx + 6, len(lines))):
        ln = lines[j].strip()
        if not ln or ln.startswith("<!--"):
            continue
        out.append(ln)
        if sum(len(x) for x in out) > max_take:
            break

    text = " / ".join(out)
    return text[:max_take]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", default=DEFAULT_DOC)
    parser.add_argument("--min-pages", type=int, default=1,
                        help="少于 N 页的文件签名合并到下一份 (默认 1, 保留单页文件)")
    args = parser.parse_args()

    pages_dir = ROOT / "data/markdown" / args.doc / "pages"
    out_dir = ROOT / "markdown" / args.doc / "chapters_v3"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 按文件名 (时间戳) 排序
    page_files = sorted(pages_dir.glob("*.md"))
    print(f"[scan] {len(page_files)} pages")

    # 第一遍: 找每页的第一个文件签名
    page_signatures = []  # [(page_no, stem, sig_kind, sig_text, sig_pos, title_candidate)]
    for page_path in page_files:
        stem = page_path.stem  # e.g. 20260913173708061__L
        md = page_path.read_text(encoding="utf-8")
        # 提取页码 (从注释)
        m = re.search(r"<!--\s*page:\s*(\d+)\s*-->", md)
        page_no = int(m.group(1)) if m else -1

        first_sig = None
        for kind, pat in SIGNATURES:
            m = pat.search(md)
            if m:
                first_sig = (kind, m.group(0).strip(), m.start())
                break
        if first_sig:
            kind, sig, pos = first_sig
            title = extract_first_titles(md, pos, sig, max_take=120)
            page_signatures.append((page_no, stem, kind, sig, pos, title))

    print(f"[scan] {len(page_signatures)} 页含文件签名")

    # 第二遍: 按 stem (时间戳) 排序, 合并连续同签名的页 (一份文件横跨多页)
    page_signatures.sort(key=lambda x: x[1])  # 按 stem 时间戳
    # 用 stem 序号当 page_seq, 跟 page_no 不一致也没关系

    # 合并: 连续 2+ 页同样的"kind+sig"算同一份文件
    merged = []
    cur = None
    for entry in page_signatures:
        key = (entry[2], entry[3])  # (kind, sig)
        if cur and cur[0] == key:
            cur[1].append(entry)  # 累加页
        else:
            if cur:
                merged.append(cur)
            cur = (key, [entry])
    if cur:
        merged.append(cur)

    # 过滤: 合并到 min-pages = 1, 不强行合并 (单页文件保留)
    print(f"[merge] {len(merged)} 份独立文件")

    # 按 stem 起始页序号排序 (output manifest 按物理页顺序)
    def start_seq(item):
        return item[1][0][1]  # (kind, sig), [entries], 第一条 stem

    merged.sort(key=start_seq)

    # 第三遍: 给每份文件分配 chapter_id + 写 md + 写 manifest
    manifest = []
    for idx, (key, entries) in enumerate(merged, 1):
        ch_id = f"f{idx:03d}"
        kind, sig = key
        first_page_no = entries[0][0]
        first_stem = entries[0][1]
        title = entries[0][5]
        n_pages = len(entries)
        page_stems = [e[1] for e in entries]

        manifest.append({
            "chapter_id": ch_id,
            "kind": kind,
            "signature": sig,
            "title_candidate": title,
            "first_page_no": first_page_no,
            "first_stem": first_stem,
            "n_pages": n_pages,
            "page_stems": page_stems,
        })

    # 写 manifest
    (out_dir / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[write] {out_dir}/_manifest.json ({len(manifest)} files)")

    # 第四遍: 写每章 md (直接拼接对应 pages 的内容 + 头注元数据)
    for m in manifest:
        # 拼接 page md 内容 (去掉每页的 page 注释, 改为章级元数据)
        body_parts = [f"# {m['chapter_id']} {m['signature']}",
                      f"> {m['title_candidate']}",
                      ""]
        for i, stem in enumerate(m["page_stems"]):
            page_md = (pages_dir / f"{stem}.md").read_text(encoding="utf-8")
            # 去掉每页自己的 page 注释
            page_md = re.sub(r"<!--\s*page:\s*\d+\s*-->\s*\n?", "", page_md)
            body_parts.append(page_md.rstrip())
            body_parts.append("")
        (out_dir / f"{m['chapter_id']}.md").write_text(
            "\n".join(body_parts).rstrip() + "\n", encoding="utf-8"
        )
    print(f"[write] {len(manifest)} 个 chapter md 到 {out_dir}/")

    # 简报
    print()
    print("=== 章节大小分布 ===")
    sizes = []
    for m in manifest:
        sz = (out_dir / f"{m['chapter_id']}.md").stat().st_size
        sizes.append((m["chapter_id"], sz, m["n_pages"], m["signature"], m["title_candidate"][:40]))
    sizes.sort(key=lambda x: -x[1])
    print(f"  最大: {sizes[0]}")
    print(f"  最小: {sizes[-1]}")
    big = [s for s in sizes if s[1] > 50_000]
    print(f"  >50KB 的章节: {len(big)}")
    empty = [s for s in sizes if s[1] < 500]
    print(f"  <500B 的章节: {len(empty)}")
    print()
    print("=== 前 10 份文件 ===")
    for s in sizes[:10]:
        print(f"  {s[0]}  {s[1]:>7}B  {s[2]}p  {s[3][:30]}  | {s[4]}")


if __name__ == "__main__":
    main()
