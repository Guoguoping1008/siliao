"""按 目录合并.md 的章节层级, 建目录并移动 md。

目标结构 = 目录的层级:
    01法规/一、法规/饲料和饲料添加剂管理条例/0003.md
    02制度文件/二、制度文件/（一）新产品审定/新饲料和新饲料添加剂管理办法/0015.md

规则:
- 一级章节(##)建一层目录, 二级章节(###)建一层, 文件(####)建一层
- 页面归属: 书页 N 的页面归给"起始页 <= N"的那个文件
- 边界页(分节标题页 / 空白页)单独处理, 不硬塞进文件目录

用法:
  python mm_reorg.py --plan     # 只打印计划
  python mm_reorg.py --apply    # 执行
"""
import os
import re
import shutil
import sys

MINIMAX = r"E:/workspace/siliao/minimax"
TOC = os.path.join(MINIMAX, "001目录", "目录合并.md")
DIGITS = re.compile(r"\D")

ENTRY_RE = re.compile(r"^(#{2,4})\s+(.*)$")
PAGE_TAIL_RE = re.compile(r"^(.*?)\s*-{2,}\s*(\d{1,4})\s*$")
DOCNO_LINE_RE = re.compile(r"^(.*?)\s*-{2,}\s*(\d{1,4})\s*$")


def safe(name):
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip().rstrip(".")


# 目录 OCR 会把页码粘进标题: "禁止在饲料和动物饮用598水中使用的药品"
# 只修"汉字+3位以内数字+汉字"这种明显的页码残留(25家/4种/20项 这类是正常内容, 排除)
TITLE_PAGENO_RE = re.compile(r"(?<=[\u4e00-\u9fa5])(\d{1,3})(?=[\u4e00-\u9fa5])")
# 常见的"数量词"不算页码残留
UNIT_WORDS = ("家", "种", "项", "个", "条", "款", "批", "级", "年", "月", "日",
              "倍", "成", "倍", "元", "类", "类", "份", "只", "头", "天", "周", "月")


def clean_title(title, page=None, all_pages=None):
    """去掉标题里被 OCR 粘进去的页码。

    例: "禁止在饲料和动物饮用598水中使用的药品"
        -> "禁止在饲料和动物饮水中使用的药品"

    粘进去的页码可能是**上一个文件**的页码(598), 不一定是当前文件的起始页,
    所以要拿全书的页码集合来判断。
    """
    t = title.strip()

    def repl(m):
        num = m.group(1)
        nxt = t[m.end():m.end() + 1]
        # 后面跟量词 -> 正常内容(如 25家 / 4种 / 20项)
        if nxt in UNIT_WORDS:
            return m.group(0)
        # 是已知页码 -> 页码残留
        if all_pages and int(num) in all_pages:
            return ""
        if page is not None and int(num) == page:
            return ""
        return m.group(0)

    return TITLE_PAGENO_RE.sub(repl, t).strip()


def parse_toc(path):
    """-> [(level, title, page, docno)]"""
    lines = [l.rstrip() for l in open(path, encoding="utf-8").read().split("\n")]
    entries = []
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        i += 1
        if not s:
            continue
        m = ENTRY_RE.match(s)
        if not m:
            continue
        level, text = len(m.group(1)), m.group(2).strip()
        pm = PAGE_TAIL_RE.match(text)
        if pm:
            entries.append((level, pm.group(1).strip(), int(pm.group(2)), ""))
            continue
        docno, page = "", None
        if i < len(lines):
            nxt = lines[i].strip()
            dm = DOCNO_LINE_RE.match(nxt)
            if dm and len(nxt) > len(dm.group(1)):
                docno = dm.group(1).strip()
                page = int(dm.group(2))
                i += 1
        entries.append((level, text, page, docno))
    return entries


def build_docs(entries):
    """-> [(level, title, page, docno, chapter, section)]

    栈里存**所有**标题行(不管有没有页码)。
    坑: 章/节标题本身带页码(如 "（一）新产品审定 ------15"),
    如果只 push 无页码的, 节就丢了, 所有文件都会挂到章根下。
    """
    docs = []
    stack = []
    for level, title, page, docno in entries:
        while stack and stack[-1][0] >= level:
            stack.pop()
        chapter = next((t for lv, t, *_ in reversed(stack) if lv == 2), "")
        section = next((t for lv, t, *_ in reversed(stack) if lv == 3), "")
        docs.append((level, title, page, docno, chapter, section))
        stack.append((level, title))
    return docs


def doc_ranges(docs):
    """独立文件(####级且有页码) -> [(标题, 起, 止, 文号, 章, 节)]"""
    files = [(t, p, dn, c, s) for lv, t, p, dn, c, s in docs if lv == 4 and p is not None]
    out = []
    for k, (t, p, dn, c, s) in enumerate(files):
        end = (files[k + 1][1] - 1) if k + 1 < len(files) else 10 ** 9
        out.append((t, p, end, dn, c, s))
    return out


def target_dir(base, chapter, section, title):
    """目标目录 = <一级目录>/<章>/<节>/<文件>"""
    parts = []
    if chapter:
        parts.append(chapter)
    if section:
        parts.append(section)
    parts.append(title)
    return os.path.join(base, *parts)


def main():
    apply = "--apply" in sys.argv
    # 只处理指定的一级目录(默认 01法规); 目录页/封面页不动
    scope = "01法规"
    for a in sys.argv[1:]:
        if a.startswith("--scope="):
            scope = a.split("=", 1)[1]

    docs = build_docs(parse_toc(TOC))
    ranges = doc_ranges(docs)

    # 全书已知页码集合(用于识别标题里被 OCR 粘进去的页码)
    all_known_pages = {p for _lv, _t, p, _dn, _c, _sec in docs if p}

    # 扫指定目录下的页(注意: 文件名位数不统一, 001目录 用 5 位, 正文用 4 位)
    scope_dir = os.path.join(MINIMAX, scope)
    all_pages = []
    for f in sorted(os.listdir(scope_dir)):
        if f.endswith(".md") and f[:-3].isdigit():
            all_pages.append((int(f[:-3]), os.path.join(scope_dir, f)))

    # 归属
    plan = []
    stats = {"moved": 0, "kept": 0}
    unknown = []
    for pg, src in all_pages:
        owner = None
        owner_page = None
        for title, start, end, dn, c, s in ranges:
            if start <= pg <= end:
                owner = (title, c, s)
                owner_page = start
                break
        rel = os.path.relpath(src, MINIMAX)
        # 分节标题页(内容就是下一章的章名) -> 不归给上一个文件
        body = ""
        if os.path.exists(src):
            body = open(src, encoding="utf-8").read().strip()
        is_divider = (
            body
            and len(body) <= 30
            and not body.startswith("#")
            and re.match(r"^[一二三四五六七八九十]+、", body)
        )
        if owner and not is_divider:
            title = clean_title(owner[0], owner_page, all_known_pages)
            dst = target_dir(scope_dir, owner[1], owner[2], title)
            plan.append((src, dst, rel, owner[0]))
            stats["moved"] += 1
        elif is_divider:
            # 分节标题页: 物理上属于本扫描序列, 但它标记的是**下一章**。
            # 下一章的内容在另一个顶层目录(如 02制度文件), 所以这里不建
            # "二、制度文件/" 空目录(会误导), 而是留在原目录, 改名标记。
            newname = f"{os.path.splitext(os.path.basename(src))[0]}_{body}.md"
            dst = os.path.join(scope_dir, newname)
            plan.append((src, dst, rel, f"[分节页] {body}"))
            stats["moved"] += 1
            stats["divider"] = stats.get("divider", 0) + 1
        else:
            stats["kept"] += 1
            unknown.append((rel, pg, body[:40]))

    print("=" * 78)
    print(f"计划: 移动 {stats['moved']} 个, 保留原位 {stats['kept']} 个")
    print("=" * 78)
    # 按目标目录汇总
    bydir = {}
    for src, dst, rel, title in plan:
        bydir.setdefault(dst, []).append((rel, title))
    for dst in sorted(bydir):
        items = sorted(bydir[dst])
        rel = os.path.relpath(dst, MINIMAX)
        print(f"\n{rel}/   ({len(items)} 页)")
        for r, t in items:
            print(f"    {os.path.basename(r)}  <- {t[:44]}")

    if unknown:
        print()
        print("保留原位(未归属):")
        for rel, pg, body in unknown:
            print(f"    {rel}   {body!r}")

    if not apply:
        print()
        print("[DRY RUN] 加 --apply 执行")
        return

    print()
    print("=" * 78)
    print("执行")
    print("=" * 78)
    # 只给"目录目标"建目录; 分节页目标是**文件**, 不能 makedirs
    for dst in sorted(bydir):
        if dst.lower().endswith(".md"):
            continue
        os.makedirs(dst, exist_ok=True)
    for src, dst, rel, title in plan:
        if dst.lower().endswith(".md"):
            # 文件目标: 直接移到该路径
            d = dst
        else:
            d = os.path.join(dst, os.path.basename(src))
        if os.path.exists(d):
            print(f"  跳过(已存在): {rel} -> {os.path.relpath(d, MINIMAX)}")
            continue
        shutil.move(src, d)
        print(f"  {rel} -> {os.path.relpath(d, MINIMAX)}")
    print(f"\n完成: {stats['moved']} 个已移动")


if __name__ == "__main__":
    main()
