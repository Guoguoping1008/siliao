"""按目录文号索引到正文页。

输入:
1) 001目录/饲料法规文件2023_目录.md   —— 结构化目录(### 子类, #### 文号+页码)
2) Markdown/ 下各章节正文 —— 文件名即书的页码(0015.md = 书第 15 页)

输出:
1) 文号索引表 CSV/MD —— 每个文件条目 -> 起始页 / 页数 / 实际落盘的 md 文件
2) 缺口报告 —— 目录里有但正文未落地的条目

关键事实:
- 正文 md 的文件名 = 书页码(4 位, 如 0015), 这是目录与正文的唯一连接键
- 每个文件条目在书中占**连续一段页码**, 起点来自目录的 "------ N",
  终点 = 下一个条目的起点 - 1(最后一条用同类目结束页推断)
"""
import os, re, csv, json, argparse
from collections import OrderedDict

MD_ROOT = r"E:/workspace/siliao/Markdown"
TOC = os.path.join(MD_ROOT, "001目录", "饲料法规文件2023_目录.md")

# 目录中的一级部分 -> 实际正文目录名
PART_DIR = {
    "一、法规": "01法规",
    "二、制度文件": "02制度文件",
    "三、相关法律法规文件": "03相关法规法律法规文件",
    "四、标准及标准目录": "04标准及标准目录",
}
SUB_RE = re.compile(r"^（([一二三四五六七八九十]+)）\s*(.+)$")

# 「三、相关法律法规文件」下的（一）~（六）既是子类, 也是该子类下唯一的文件。
# 判断依据: 该（x）条目后面没有任何 #### 子项 -> 它本身就是一个文件条目。
SOLO_DOC_PREFIX = "三、相关法律法规文件"


def parse_toc(path):
    """解析结构化目录 -> [{part, sub, title, docno, page}]

    需要区分两种 ### :
    - 后继存在 #### 的 -> 子类标题（如「（一）新产品审定」）
    - 后继没有 #### 的 -> 该部分下的**直接文件**（如「一、法规」「四、标准」的条目,
      以及「三」下（一）~（三）这类既标号又自成一体的文件）
    因此先切出所有块再回填父级。
    """
    blocks = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#### "):
                blocks.append(("doc", line[5:].strip(), line))
            elif line.startswith("### "):
                blocks.append(("h3", line[4:].strip(), line))
            elif line.startswith("## "):
                blocks.append(("part", line[3:].strip(), line))

    entries = []
    part = sub = None
    for i, (kind, text, raw) in enumerate(blocks):
        if kind == "part":
            part, sub = text, None
            continue
        if kind == "h3":
            # 先剥离尾部"(文号, — p.N)"括号, 再判定是否为子类标题
            docno = page = None
            t = text
            mm = re.search(r"（([^（）]*)）\s*$", t)
            if mm:
                inner = mm.group(1)
                t = t[: mm.start()].strip()
                pm = re.search(r"[—\-]{1,2}\s*p\.(\d+)", inner)
                if pm:
                    page = int(pm.group(1))
                    inner = inner[: pm.start()].rstrip("，,、 ")
                if inner.strip():
                    docno = inner.strip()
            m = SUB_RE.match(t)
            num, name = (m.group(1), m.group(2).strip()) if m else (None, t)

            # 判定: 它到底是个独立文件, 还是一个有子项的分类?
            # 「三」下 (一)(二)(三) 是整部法律(独立文件), 后面直接跟下一个 (x);
            # 「四」兽药管理 / 「二」各 (x) 则后面挂着一串 ####。
            # 办法: 在"下一个 part 之前"寻找, 若本 h3 与下一个 h3/part 之间
            #       存在任何 doc, 则本 h3 是分类; 否则是独立文件。
            has_doc = False
            j = i + 1
            while j < len(blocks):
                if blocks[j][0] == "part":
                    break
                if blocks[j][0] == "doc":
                    has_doc = True
                    break
                if blocks[j][0] == "h3":
                    # 遇到下一个 h3, 继续往后找 part, 看它自己那段有没有 doc
                    k = j + 1
                    while k < len(blocks) and blocks[k][0] != "part":
                        if blocks[k][0] == "doc":
                            has_doc = True
                            break
                        k += 1
                    break
                j += 1
            solo = not has_doc
            if solo:
                entries.append({"part": part, "sub": sub,
                                "title": (f"（{num}）{name}" if num else name),
                                "docno": docno, "page": page})
                sub = None
            else:
                sub = (num, name)
            continue
        # kind == "doc"
        t = text
        docno = page = None
        m = re.search(r"（([^（）]*)）\s*$", t)
        if m:
            inner = m.group(1)
            t = t[: m.start()].strip()
            pm = re.search(r"[—\-]{1,2}\s*p\.(\d+)", inner)
            if pm:
                page = int(pm.group(1))
                inner = inner[: pm.start()].rstrip("，,、 ")
            if inner.strip():
                docno = inner.strip()
        entries.append({"part": part, "sub": sub, "title": t,
                        "docno": docno, "page": page})
    return entries


def scan_body_pages():
    """扫描正文, 得到 {章节名: {页码(int): [文件路径]}}

    正文 md 已被按文号拆进子目录, 因此必须递归扫描。
    同一页码可能出现在多个位置(例如 02制度文件 下既有散页也有子目录),
    全部保留 —— 一个文号目录可能只是部分页。
    """
    out = {}
    for d in sorted(os.listdir(MD_ROOT)):
        p = os.path.join(MD_ROOT, d)
        if not os.path.isdir(p) or d.startswith("_"):
            continue
        m = {}
        for dp, _, fs in os.walk(p):
            for f in sorted(fs):
                if not f.endswith(".md"):
                    continue
                stem = os.path.splitext(f)[0]
                if not stem.isdigit():
                    continue
                m.setdefault(int(stem), []).append(os.path.join(dp, f))
        if m:
            out[d] = m
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--toc", default=TOC)
    ap.add_argument("--out-csv", default=os.path.join(MD_ROOT, "_index_by_docno.csv"))
    ap.add_argument("--out-md", default=os.path.join(MD_ROOT, "文号索引.md"))
    args = ap.parse_args()

    entries = parse_toc(args.toc)
    body = scan_body_pages()
    print(f"[toc] 条目 {len(entries)}")
    for d, m in sorted(body.items()):
        print(f"[body] {d}: {len(m)} 页有内容")

    # 目录 -> 章节: 用条目的 part 字段
    rows = []
    cur_part = None
    for e in entries:
        if e["part"] != cur_part:
            cur_part = e["part"]
        dname = PART_DIR.get(cur_part)
        pages = body.get(dname, {})
        start = e["page"]
        # 结束页 = 下一个条目的起始页 - 1
        nxt = None
        for e2 in entries:
            if e2["page"] and start and e2["page"] > start:
                nxt = e2["page"] - 1
                break
        end = nxt
        files = []
        if start:
            for p in range(start, (end or start) + 1):
                # 书页 N 的内容可能落在扫描页 N(右页)或 N-1(与 N+1 同张扫描图)
                for cand in (p, p - 1):
                    files.extend(pages.get(cand, []))
        rows.append({
            "部分": cur_part,
            "子类": (e["sub"][1] if e["sub"] else ""),
            "文件": e["title"],
            "文号": e["docno"] or "",
            "起始页": start or "",
            "结束页": end if end else "",
            "页数": (end - start + 1) if (start and end) else "",
            "md文件数": len(files),
            "命中": "Y" if files else "N",
            "md路径": ";".join(
                os.path.relpath(p, MD_ROOT).replace("\\", "/") for p in sorted(set(files))
            ),
        })

    # 写 CSV
    with open(args.out_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    hit = sum(1 for r in rows if r["命中"] == "Y")
    print(f"\n[索引] 条目 {len(rows)}, 命中正文 {hit}, 未命中 {len(rows)-hit}")
    print(f"[saved] {args.out_csv}")

    # 写 MD
    out = ["# 饲料法规文件（2023） 文号索引", "",
           f"共 {len(rows)} 个文件条目；命中正文 {hit} 个。", ""]
    cur_part = None
    cur_sub = None
    for r in rows:
        if r["部分"] != cur_part:
            cur_part = r["部分"]
            cur_sub = None
            out += [f"## {cur_part}", ""]
        if r["子类"] != cur_sub:
            cur_sub = r["子类"]
            out += [f"### {cur_sub}" if cur_sub else "### （直接条目）", ""]
        pg = f"p.{r['起始页']}" if r["起始页"] else "—"
        if r["结束页"] and r["结束页"] != r["起始页"]:
            pg += f"-{r['结束页']}"
        mark = "" if r["命中"] == "Y" else "  ⚠正文缺失"
        tail = "，".join(x for x in [r["文号"], pg] if x)
        line = f"#### {r['文件']}"
        if tail:
            line += f"（{tail}）"
        out += [line + mark, ""]
        # 直接给出可跳转的 md 相对路径
        paths = [p for p in (r.get("md路径") or "").split(";") if p]
        if paths:
            shown = paths[:6]
            more = len(paths) - len(shown)
            for p in shown:
                out += [f"- [{os.path.basename(p)}]({p})"]
            if more > 0:
                out += [f"- …… 另有 {more} 个 md 文件"]
            out += [""]
    with open(args.out_md, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out).rstrip() + "\n")
    print(f"[saved] {args.out_md}")


if __name__ == "__main__":
    main()