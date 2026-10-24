"""把 001目录 的 6 个分页 md 合并成一个结构化目录。

处理的问题(来自 OCR 的既有缺陷):
1. `（一）新产品审定 ------15` 这类"子类标题"带页码, 应视为分类而非文件
2. 文号行紧跟在标题后, 需并入该条目而不是独立成段
3. 页码被 OCR 混进正文(如 "360中华人民共和国农业部公告第2583号 ------ 361")
4. 标题层级: 一级部分 -> 子类 -> 文件条目
"""
import os, re, sys, glob, argparse

SRC_DIR = r"E:/workspace/siliao/Markdown/001目录"
OUT = r"E:/workspace/siliao/Markdown/001目录/饲料法规文件2023_目录.md"

# 页码标记: 3~6 个连字符 + 数字
PAGE_RE = re.compile(r"\s*-{2,}\s*(\d+)\s*$")
# 文号行: 含"令/公告/发/函/号"等, 或形如 "农办牧〔2021〕43号" 的方括号编号,
# 或标准号 "GB10648-2013" / "C 0273-2021" / "NY/T 1132-2013"
DOCNO_RE = re.compile(
    r"(令|公告|发|函|批复|通知|规程|规范|办法|标准|目录|解释|纪要|号|〔|\[)"
    r"|\b(GB|DB|NY|NY/T|SC|C|CJ|MT|SN)\s*[\d.]+-\d{4}"
)
# 纯页码行(OCR 把页码单独甩出)
BARE_PAGE_RE = re.compile(r"^(\d{1,4})(?=[^\d]|$)")
# "（一）xxx" 子类标题
SUB_RE = re.compile(r"^[（(]\s*([一二三四五六七八九十]+)\s*[)）]\s*(.+)$")


def clean_page_inline(text):
    """把误插进句子中间的页码抠出来: "360中华人民共和国...第2583号 ------ 361"

    返回 (清理后的正文, 页码)
    """
    page = None
    m = re.search(r"-{2,}\s*(\d+)\s*$", text)
    if m:
        page = m.group(1)
        text = text[: m.start()]
    # 行首孤立页码: "598水中使用的药品..."
    m2 = BARE_PAGE_RE.match(text)
    if m2 and len(text) > 12:
        cand = m2.group(1)
        # 后面紧跟中文, 说明是误插页码
        if re.match(r"^\d{1,4}[\u4e00-\u9fff]", text):
            text = text[len(cand):]
    return text.strip(), page


def parse():
    files = sorted(glob.glob(os.path.join(SRC_DIR, "0*.md")))
    parts, pages, subs, docs = [], [], [], []
    cur_part = None
    cur_sub = None

    for fp in files:
        with open(fp, encoding="utf-8") as f:
            lines = f.read().split("\n")
        for raw in lines:
            line = raw.strip()
            if not line:
                continue

            # ---- 一级部分 ----
            if line.startswith("## "):
                t = line[3:].strip()
                t, pg = clean_page_inline(t)
                cur_part = t
                parts.append({"title": t, "page": pg, "subs": [], "docs": []})
                cur_sub = None
                continue

            # ---- 子类标题 (###) ----
            if line.startswith("### "):
                t = line[4:].strip()
                t, pg = clean_page_inline(t)
                m = SUB_RE.match(t)
                num = m.group(1) if m else ""
                name = m.group(2).strip() if m else t
                cur_sub = {"num": num, "title": name, "page": pg, "docs": []}
                subs.append(cur_sub)
                # 始终挂到"当前一级部分"下
                if parts:
                    parts[-1]["subs"].append(cur_sub)
                    # 若带页码且其后无子文档, 它本身就是一个文件条目
                    # (如「三」下（一）~（三): 既标子类序号, 自身即是整部法律)
                    if pg is not None:
                        parts[-1]["docs"].append({"title": name, "page": pg,
                                                  "docno": "", "num": num})
                continue

            # ---- 文件条目 (####) ----
            if line.startswith("#### "):
                t = line[5:].strip()
                t, pg = clean_page_inline(t)
                docs.append({"part": cur_part, "sub": cur_sub, "title": t, "page": pg})
                if cur_sub is not None:
                    cur_sub["docs"].append({"title": t, "page": pg})
                elif parts:
                    parts[-1]["docs"].append({"title": t, "page": pg})
                continue

            # ---- 文号行(裸行): 并入上一条目 ----
            if docs and (DOCNO_RE.search(line) or re.match(r"^\d{4}年", line)):
                t, pg = clean_page_inline(line)
                if pg is None and t.isdigit():
                    pg = t
                else:
                    if docs[-1].get("docno"):
                        docs[-1]["docno"] += " " + t
                    else:
                        docs[-1]["docno"] = t
                if pg and not docs[-1].get("page"):
                    docs[-1]["page"] = pg
                targets = []
                if cur_sub is not None and cur_sub["docs"]:
                    targets.append(cur_sub["docs"][-1])
                elif parts and parts[-1]["docs"]:
                    targets.append(parts[-1]["docs"][-1])
                for d in targets:
                    if not d.get("docno"):
                        d["docno"] = docs[-1].get("docno", "")
                    if pg and not d.get("page"):
                        d["page"] = pg
                continue

            # ---- 其它裸行: 视为上一个条目的续行 ----
            if docs:
                t, pg = clean_page_inline(line)
                if t:
                    docs[-1]["title"] += t
                if pg and not docs[-1].get("page"):
                    docs[-1]["page"] = pg

    return parts, subs, docs


def render(parts):
    out = ["# 饲料法规文件（2023） 目录", ""]
    for pi, part in enumerate(parts, 1):
        out.append(f"## {part['title']}")
        out.append("")
        # 该部分下"既标子类序号又自身成篇"的独立文件(如 三、(一)~(三))
        for d in part.get("docs", []):
            bits = [f"### （{d['num']}）{d['title']}"] if d.get("num") else [f"### {d['title']}"]
            tail = []
            if d.get("docno"):
                tail.append(d["docno"])
            if d.get("page"):
                tail.append(f"— p.{d['page']}")
            if tail:
                bits.append("（" + "，".join(tail) + "）")
            out.append("".join(bits))
            out.append("")
        # 无子类时, 到此为止
        if not part["subs"]:
            continue
        for sub in part["subs"]:
            out.append(f"### （{sub['num']}）{sub['title']}")
            out.append("")
            for d in sub["docs"]:
                bits = [f"#### {d['title']}"]
                tail = []
                if d.get("docno"):
                    tail.append(d["docno"])
                if d.get("page"):
                    tail.append(f"— p.{d['page']}")
                if tail:
                    bits.append("（" + "，".join(tail) + "）")
                out.append("".join(bits))
                out.append("")
    return "\n".join(out).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    parts, subs, docs = parse()
    ndocs = sum(len(s["docs"]) for s in subs)
    print(f"[parse] 部分={len(parts)} 子类={len(subs)} 文件={ndocs}")
    for p in parts:
        ns = len(p["subs"])
        nd = sum(len(s["docs"]) for s in p["subs"])
        print(f"   {p['title']}: 子类 {ns}, 文件 {nd}")
    text = render(parts)
    if not args.dry_run:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print(f"[saved] {args.out}  ({len(text)} chars)")


if __name__ == "__main__":
    main()