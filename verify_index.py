"""校验: 目录条目 <-> 文号索引 是否一一对应(0 丢失)。"""
import re, csv, glob, sys
from collections import Counter

TOC_DIR = r"E:/workspace/siliao/Markdown/001目录"
TOC_MD = TOC_DIR + "/饲料法规文件2023_目录.md"
CSV = r"E:/workspace/siliao/Markdown/_index_by_docno.csv"

TAIL = re.compile(r"（([^（）]*)）\s*$")
PAGE = re.compile(r"-{2,}\s*\d+\s*$")
LEAD = re.compile(r"^\d{1,4}(?=[\u4e00-\u9fff])")
# 尾部括号里只有"试行/暂行/修订"等版本标记时, 它属于标题本体, 不能剥掉
VERSION_ONLY = re.compile(r"^(试行|暂行|修订|草案|试行稿|暂行稿)$")


def clean(t):
    t = t.strip()
    t = PAGE.sub("", t).strip()
    t = LEAD.sub("", t)
    m = TAIL.search(t)
    if m and not VERSION_ONLY.match(m.group(1).strip()):
        t = t[: m.start()].strip()
    return t


# 1) 结构化目录里的 #### 文件条目
toc_docs = []
for l in open(TOC_MD, encoding="utf-8"):
    if l.startswith("#### "):
        toc_docs.append(clean(l[5:]))

# 2) 无子类的部分, 其 ### 就是文件条目
parts = []
for l in open(TOC_MD, encoding="utf-8"):
    if l.startswith("## "):
        parts.append([l[3:].strip(), 0])
    elif parts:
        if l.startswith("### "):
            parts[-1][1] += 1
        elif l.startswith("#### "):
            parts[-1][1] += 2

solo_docs = []
cur = None
for l in open(TOC_MD, encoding="utf-8"):
    s = l.strip()
    if s.startswith("## "):
        cur = s[3:].strip()
    elif s.startswith("#### "):
        cur_has_doc = True
    elif s.startswith("### ") and cur in ("一、法规", "四、标准及标准目录"):
        solo_docs.append(clean(s[4:]))

toc_all = toc_docs + solo_docs

# 3) 索引
rows = list(csv.DictReader(open(CSV, encoding="utf-8-sig")))
idx = [clean(r["文件"]) for r in rows]

a, b = Counter(toc_all), Counter(idx)
missing = a - b
extra = b - a
print(f"目录条目 {len(toc_all)}  索引条目 {len(idx)}")
print(f"目录有索引无: {sum(missing.values())}")
for k, v in missing.items():
    print("   MISSING:", k[:70])
print(f"索引有目录无: {sum(extra.values())}")
for k, v in extra.items():
    print("   EXTRA  :", k[:70])
print("\n命中正文:", sum(1 for r in rows if r["命中"] == "Y"), "/", len(rows))
sys.exit(1 if (missing or extra) else 0)