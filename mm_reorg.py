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
    """-> [(level, title, page, docno, chapter, section)]"""
    docs = []
    stack = []
    for level, title, page, docno in entries:
        while stack and stack[-1][0] >= level:
            stack.pop()
        chapter = stack[-1][1] if stack else ""
        section = stack[-1][1] if stack else ""
        # 找最近的一级/二级祖先
        chapter = next((t for lv, t, *_ in reversed(stack) if lv == 2), "")
        section = next((t for lv, t, *_ in reversed(stack) if lv == 3), "")
        docs.append((level, title, page, docno, chapter, section))
        if page is None:
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


def target_dir(chapter, section, title):
    parts = []
    if chapter:
        parts.append(chapter)
    if section:
        parts.append(section)
    parts.append(title)
    return os.path.join(MINIMAX, *parts)


def main():
    apply = "--apply" in sys.argv
    # 只处理指定的一级目录(默认 01法规); 目录页/封面页不动
    scope = "01法规"
    for a in sys.argv[1:]:
        if a.startswith("--scope="):
            scope = a.split("=", 1)[1]

    docs = build_docs(parse_toc(TOC))
    ranges = doc_ranges(docs)

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
        for title, start, end, dn, c, s in ranges:
            if start <= pg <= end:
                owner = (title, c, s)
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
            dst = target_dir(owner[1], owner[2], owner[0])
            plan.append((src, dst, rel, owner[0]))
            stats["moved"] += 1
        elif is_divider:
            # 分节标题页: 物理上属于本扫描序列, 但它标记的是**下一章**。
            # 下一章的内容在另一个顶层目录(如 02制度文件), 所以这里不建
            # "二、制度文件/" 空目录(会误导), 而是留在原目录, 改名加前缀标记。
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
    for dst in sorted(bydir):
        os.makedirs(dst, exist_ok=True)
    for src, dst, rel, title in plan:
        base = os.path.basename(src)
        d = os.path.join(dst, base)
        if os.path.exists(d):
            print(f"  跳过(已存在): {rel} -> {os.path.relpath(d, MINIMAX)}")
            continue
        shutil.move(src, d)
        print(f"  {rel} -> {os.path.relpath(d, MINIMAX)}")
    print(f"\n完成: {stats['moved']} 个已移动")


if __name__ == "__main__":
    main()
