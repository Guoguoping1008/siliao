"""校验 HTML 表格转换结果:
1) HTML 结构是否合法(标签配平)
2) 单元格内容是否零丢失(对比转换前的 git 版本)
3) 有没有漏转的管道表
"""
import collections
import html.parser
import os
import re
import subprocess

repo = r"E:/workspace/siliao"
base = os.path.join(repo, "minimax")

TBL_RE = re.compile(r"<table\b.*?</table>", re.S | re.I)
ROW_RE = re.compile(r"<tr\b.*?</tr>", re.S | re.I)
CELL_RE = re.compile(r"<t[dh]\b([^>]*)>(.*?)</t[dh]>", re.S | re.I)
PIPE_RE = re.compile(r"^\s*\|.*\|\s*$")


class V(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.err = []
        self.ntbl = 0
        self.nrowspan = 0
        self.ncolspan = 0

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.ntbl += 1
        if tag in ("tr", "td", "th"):
            self.stack.append(tag)
        if tag in ("td", "th"):
            d = dict(attrs)
            if "rowspan" in d and int(d["rowspan"]) > 1:
                self.nrowspan += 1
            if "colspan" in d and int(d["colspan"]) > 1:
                self.ncolspan += 1

    def handle_endtag(self, tag):
        if tag in ("tr", "td", "th"):
            if not self.stack:
                self.err.append(f"多余闭合 {tag}")
            elif self.stack[-1] != tag:
                self.err.append(f"不匹配 {self.stack[-1]}!={tag}")
            else:
                self.stack.pop()


def cells_of_md_line(l):
    return [c.strip() for c in l.strip().strip("|").split("|")]


def md_cells(text):
    """原 md 里所有表格的非空单元格文本"""
    out = []
    for ln in text.splitlines():
        if PIPE_RE.match(ln):
            cells = cells_of_md_line(ln)
            if all(set(c) <= set("-:") for c in cells if c):
                continue
            for c in cells:
                if c:
                    out.append(c)
    return out


def html_cells(text):
    """转换后 HTML 里的所有单元格文本(去标签)"""
    out = []
    for m in TBL_RE.finditer(text):
        for c in CELL_RE.finditer(m.group(0)):
            t = re.sub(r"<[^>]+>", "", c.group(2))
            t = t.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
            if t.strip():
                out.append(t.strip())
    return out


# ---- 1) HTML 合法性 + 合并统计 ----
ntbl = nrowsp = ncolsp = 0
errs = []
leftover = []
for dp, dns, fns in os.walk(base):
    for f in fns:
        if not f.endswith(".md"):
            continue
        p = os.path.join(dp, f)
        t = open(p, encoding="utf-8").read()
        for m in TBL_RE.finditer(t):
            v = V()
            v.feed(m.group(0))
            ntbl += v.ntbl
            nrowsp += v.nrowspan
            ncolsp += v.ncolspan
            if v.err or v.stack:
                errs.append((os.path.relpath(p, base), v.err[:3], v.stack))
        # 漏转的管道表
        if any(PIPE_RE.match(l) and not all(set(c) <= set("-:") for c in cells_of_md_line(l) if c)
               for l in t.splitlines()):
            leftover.append(os.path.relpath(p, base))

print(f"HTML 表格 {ntbl} 个   rowspan>1 {nrowsp} 处   colspan>1 {ncolsp} 处")
print(f"HTML 结构错误: {len(errs)}")
for e in errs[:6]:
    print("   ", e)
print(f"仍有管道表(漏转)的页: {len(leftover)}")
for x in leftover[:8]:
    print("   ", x)

# ---- 2) 内容零丢失 ----
out = subprocess.run(
    ["git", "-C", repo, "-c", "core.quotepath=false",
     "ls-files", "-z", "minimax"],
    capture_output=True).stdout.decode("utf-8", "ignore")
names = [n for n in out.split("\0") if n.endswith(".md")]
lost = 0
checked = 0
for n in names:
    old = subprocess.run(["git", "-C", repo, "show", f"HEAD:{n}"],
                         capture_output=True).stdout.decode("utf-8", "ignore")
    p = os.path.join(repo, n.replace("/", os.sep))
    if not os.path.exists(p):
        continue
    new = open(p, encoding="utf-8").read()
    if old == new:
        continue
    checked += 1
    mo = collections.Counter(md_cells(old))
    mn = collections.Counter(html_cells(new))
    # 只比表格相关的字符
    mo = collections.Counter("".join(md_cells(old)).replace(" ", "").replace("/", ""))
    mn = collections.Counter("".join(html_cells(new)).replace(" ", "").replace("/", ""))
    miss = mo - mn
    if miss:
        lost += 1
        print(f"  内容丢失: {n}")
        for k, v in list(miss.items())[:6]:
            print(f"      少 {v}: {k!r}")
print()
print(f"被改动的文件 {checked} 个, 内容丢失 {lost} 个")
